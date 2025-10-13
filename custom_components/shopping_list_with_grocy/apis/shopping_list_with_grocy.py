import asyncio
import base64
import copy
import json
import logging
import re
import time
import unicodedata
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import urlencode

import aiohttp
from async_timeout import timeout
from dateutil.relativedelta import relativedelta
from homeassistant.components.todo import TodoItemStatus
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from ..const import DOMAIN, ENTITY_VERSION, OTHER_FIELDS
from ..frontend_translations import async_load_frontend_translations, get_voice_response
from ..utils import is_update_paused

LOGGER = logging.getLogger(__name__)


class ShoppingListWithGrocyApi:
    def __init__(self, websession: aiohttp.ClientSession, hass: HomeAssistant, config):
        """Initialize the API client."""
        self.hass = hass
        self.config = config
        self.web_session = websession

        self.api_url = (
            config.get("api_url", "").strip() if config.get("api_url") else None
        )
        if not self.api_url:
            raise ValueError("Grocy API URL is required")

        self.verify_ssl = config.get("verify_ssl", True)
        self.api_key = config.get("api_key")
        if not self.api_key:
            raise ValueError("Grocy API key is required")

        self.image_size = config.get("image_download_size", 0)
        self.ha_products = []
        self.final_data = {}
        self.pagination_limit = 40
        self.disable_timeout = config.get("disable_timeout", False)

        self.current_time = datetime.now(timezone.utc)
        self.last_db_changed_time = None

        self.bidirectional_sync_enabled = config.get("enable_bidirectional_sync", False)
        self.bidirectional_sync_stopped = False

        concurrency = 8 if self.image_size <= 50 else 5 if self.image_size <= 100 else 3
        self._image_fetch_semaphore = asyncio.Semaphore(concurrency)

    async def get_frontend_translation(self, key: str, **kwargs) -> str:
        """Get translation from frontend translation files."""
        try:
            language = self.hass.config.language or "en"
            frontend_translations = await async_load_frontend_translations(
                self.hass, language
            )
            template = get_voice_response(frontend_translations, key)

            if kwargs:
                try:
                    return template.format(**kwargs)
                except (KeyError, ValueError):
                    return template
            return template
        except Exception as e:
            LOGGER.warning("Failed to get frontend translation for '%s': %s", key, e)
            return key

    def get_entity_in_hass(self, entity_id):
        """Retrieve an entity from Home Assistant."""
        entity = self.hass.states.get(entity_id)
        if entity is None:
            LOGGER.debug("Entity %s not found in Home Assistant.", entity_id)
        return entity

    def encode_base64(self, message):
        """Encode a message in Base64 format."""
        if not isinstance(message, str):
            raise TypeError(
                "encode_base64 expects a string, got %s" % type(message).__name__
            )
        return base64.b64encode(message.encode()).decode()

    def serialize_datetime(self, obj):
        """Serialize a datetime or date object to ISO format."""
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError(
            "serialize_datetime expects a datetime or date object, got %s"
            % type(obj).__name__
        )

    def build_item_list(self, data) -> list:
        if data is None or "shopping_lists" not in data:
            return []

        shopping_list_map = {}

        for shopping_list in data["shopping_lists"]:
            shopping_list_id = shopping_list["id"]
            shopping_list_map[shopping_list_id] = {
                "id": shopping_list_id,
                "name": shopping_list["name"],
                "products": [],
            }

        for product in data["products"]:
            product_id = int(product["id"])
            qty_factor = (
                float(product["qu_factor_purchase_to_stock"])
                if "qu_factor_purchase_to_stock" in product
                and product["qu_id_purchase"] != product["qu_id_stock"]
                else 1.0
            )

            for in_shopping_list in data["shopping_list"]:
                if product_id != int(in_shopping_list["product_id"]):
                    continue

                shopping_list_id = in_shopping_list["shopping_list_id"]

                if shopping_list_id in shopping_list_map:
                    in_shop_list = str(
                        round(int(in_shopping_list["amount"]) / qty_factor)
                    )
                    shopping_list_map[shopping_list_id]["products"].append(
                        {
                            "name": f"{product['name']} (x{in_shop_list})",
                            "shop_list_id": in_shopping_list["id"],
                            "status": (
                                TodoItemStatus.NEEDS_ACTION
                                if int(in_shopping_list["done"]) == 0
                                else TodoItemStatus.COMPLETED
                            ),
                        }
                    )

        result = list(shopping_list_map.values())

        return result

    async def request(
        self,
        method: str,
        url: str,
        accept: str,
        payload: dict = None,
        *,
        req_timeout: int | None = None,
        log_level: int = logging.ERROR,
        **kwargs,
    ) -> aiohttp.ClientResponse:
        """Make an asynchronous HTTP request."""
        if not self.api_url:
            raise ValueError("Grocy API URL is not configured")
        if not self.api_key:
            raise ValueError("Grocy API key is not configured")

        method = method.upper()
        is_get = method == "GET"

        headers = {
            **kwargs.get("headers", {}),
            "accept": accept,
            "GROCY-API-KEY": self.api_key,
        }

        if is_get:
            headers["cache-control"] = "no-cache"
        else:
            headers["Content-Type"] = "application/json"

        try:
            base_url = self.api_url.rstrip("/") if self.api_url else ""
            full_url = f"{base_url}/{url}"

            if self.disable_timeout or req_timeout is None:
                # No timeout wrapper
                response = await self.web_session.request(
                    method,
                    full_url,
                    headers=headers,
                    json=payload if payload and not is_get else None,
                    ssl=self.verify_ssl,
                    **kwargs,
                )
            else:
                # Only apply a timeout when explicitly requested
                async with timeout(req_timeout):
                    response = await self.web_session.request(
                        method,
                        full_url,
                        headers=headers,
                        json=payload if payload and not is_get else None,
                        ssl=self.verify_ssl,
                        **kwargs,
                    )

            if response.status >= 400:
                error_text = await response.text()
                LOGGER.error("Grocy API error: %s - %s", response.status, error_text)
                raise aiohttp.ClientError(
                    f"API request failed: {response.status} - {error_text}"
                )

            return response

        except asyncio.TimeoutError as err:
            LOGGER.log(
                log_level,
                "Timeout connecting to Grocy API at %s: %s",
                self.api_url,
                err,
            )
            raise
        except aiohttp.ClientError as err:
            LOGGER.log(
                log_level, "Error connecting to Grocy API at %s: %s", self.api_url, err
            )
            raise

    async def fetch_products(self, path: str, offset: int):
        """Fetch paginated products or other objects."""
        params = {
            "limit": self.pagination_limit,
            "offset": offset,
        }

        if path == "products":
            params["order"] = "name:asc"

        url = f"api/objects/{path}?{urlencode(params)}"

        return await self.request("get", url, "application/json")

    async def fetch_image(self, image_name: str):
        """Fetch an image from the API."""
        url = f"api/files/productpictures/{image_name}?force_serve_as=picture&best_fit_width={self.image_size}"
        return await self.request(
            "get",
            url,
            "application/octet-stream",
            req_timeout=self.compute_timeout(),
            log_level=logging.DEBUG,
        )

    async def fetch_last_db_changed_time(self):
        """Fetch the last database change timestamp."""
        response = await self.request(
            "get",
            "api/system/db-changed-time",
            "application/json",
            req_timeout=self.compute_timeout(),
        )

        last_changed = await response.json()

        return datetime.strptime(last_changed["changed_time"], "%Y-%m-%d %H:%M:%S")

    async def fetch_list(self, path: str, max_pages: int = 1000):
        """Retrieves data."""
        data = []
        offset = 0

        while True:
            response = await self.fetch_products(path, offset)

            new_results = await response.json()

            if not new_results:
                break

            data.extend(new_results)

            offset += self.pagination_limit
            if offset // self.pagination_limit >= max_pages:
                break

        return data

    async def remove_product(self, product):
        if product.endswith("))"):
            product = product[:-2]

        async_dispatcher_send(
            self.hass, f"{DOMAIN}_remove_sensor", product.split("_")[-1]
        )

    async def parse_products(self, data):
        self.current_time = datetime.now(timezone.utc)

        entities = set(self.hass.states.async_entity_ids())
        rex = re.compile(
            rf"sensor.shopping_list_with_grocy_product_v{ENTITY_VERSION}_[^|]+"
        )
        self.ha_products = set(rex.findall("|".join(entities)))

        quantity_units = {q["id"]: q["name"] for q in data["quantity_units"]}
        locations = {l["id"]: l["name"] for l in data["locations"]}
        product_groups = {g["id"]: g["name"] for g in data["product_groups"]}

        current_product_ids = {str(product["id"]) for product in data["products"]}

        to_remove = {
            entity
            for entity in self.ha_products
            if entity.split("_")[-1] not in current_product_ids
        }

        if to_remove:
            LOGGER.info("🗑️ Delete %d obsolete product(s)", len(to_remove))
            await asyncio.gather(
                *(self.remove_product(product) for product in to_remove)
            )

        self.ha_products -= to_remove

        parsed_products = []
        for product in data["products"]:
            product_id = int(product["id"])

            userfields = product.get("userfields", {})
            qty_factor = (
                float(product.get("qu_factor_purchase_to_stock", 1.0))
                if product.get("qu_id_purchase") != product.get("qu_id_stock")
                else 1.0
            )

            qty_unit_purchase = quantity_units.get(product.get("qu_id_purchase"), "")
            qty_unit_stock = quantity_units.get(product.get("qu_id_stock"), "")

            location = locations.get(product.get("location_id"), "")
            consume_location = locations.get(
                product.get("default_consume_location_id"), ""
            )
            group = product_groups.get(product.get("product_group_id"), "")

            """
            if self.image_size > 0 and product.get("picture_file_name"):
                try:
                    self.hass.async_create_task(
                        self._fetch_and_update_image(product_id, product["picture_file_name"])
                    )
                except Exception:
                    LOGGER.debug("Failed to schedule image fetch for product %s", product_id, exc_info=True)
            """

            shopping_lists = {}
            qty_in_shopping_lists = 0

            for in_shopping_list in data["shopping_list"]:
                if product_id == int(in_shopping_list["product_id"]):
                    shopping_list_id = int(in_shopping_list["shopping_list_id"])
                    in_shop_list = str(
                        round(int(in_shopping_list["amount"]) / qty_factor)
                    )
                    shopping_lists[f"list_{shopping_list_id}"] = {
                        "shop_list_id": in_shopping_list["id"],
                        "qty": int(in_shop_list),
                        "note": in_shopping_list.get("note", ""),
                    }
                    qty_in_shopping_lists += int(in_shop_list)

            # Gather stock entries for this product once to derive quantities and dates
            stock_entries = [
                stock
                for stock in data["stock"]
                if str(stock.get("product_id")) == str(product_id)
            ]

            stock_qty = sum(float(s.get("amount", 0)) for s in stock_entries)
            opened_qty = sum(
                float(s.get("amount", 0)) * int(s.get("open", 0)) for s in stock_entries
            )

            unopened_qty = max(0, stock_qty - opened_qty)

            # Aggregate dates from stock if available
            best_before_dates = [
                s.get("best_before_date")
                for s in stock_entries
                if s.get("best_before_date")
            ]
            opened_dates = [
                s.get("opened_date") for s in stock_entries if s.get("opened_date")
            ]
            purchase_dates = [
                # Grocy uses 'purchased_date'; expose as 'purchase_date'
                s.get("purchased_date") or s.get("purchase_date")
                for s in stock_entries
                if s.get("purchased_date") or s.get("purchase_date")
            ]

            best_before_date = min(best_before_dates) if best_before_dates else None
            opened_date = max(opened_dates) if opened_dates else None
            purchase_date = max(purchase_dates) if purchase_dates else None

            prod_dict = {
                "product_id": product_id,
                "parent_product_id": product.get("parent_product_id"),
                "qty_in_stock": round(stock_qty, 2),
                "qty_opened": round(opened_qty, 2),
                "qty_unopened": round(unopened_qty, 2),
                "qty_unit_purchase": qty_unit_purchase,
                "qty_unit_stock": qty_unit_stock,
                "qu_factor_purchase_to_stock": float(qty_factor),
                "location": location,
                "consume_location": consume_location,
                "group": group,
                "userfields": userfields,
                "list_count": len(shopping_lists),
            }

            # Add dates only if present
            if best_before_date:
                prod_dict["best_before_date"] = best_before_date
            if opened_date:
                prod_dict["opened_date"] = opened_date
            if purchase_date:
                prod_dict["purchase_date"] = purchase_date

            for shop_list, details in shopping_lists.items():
                prod_dict.update(
                    {
                        f"{shop_list}_qty": details["qty"],
                        f"{shop_list}_shop_list_id": int(details["shop_list_id"]),
                        f"{shop_list}_note": details["note"],
                    }
                )

            for field in OTHER_FIELDS:
                if field in product:
                    prod_dict[field] = product[field]

            parsed_product = {
                "name": product["name"],
                "product_id": product_id,
                "qty_in_shopping_lists": qty_in_shopping_lists,
                "attributes": prod_dict,
            }
            parsed_products.append(parsed_product)
            async_dispatcher_send(
                self.hass, f"{DOMAIN}_add_or_update_sensor", parsed_product
            )

        parsed_products_dict = {
            str(product["product_id"]): product for product in parsed_products
        }

        return parsed_products_dict

    async def _kick_off_image_fetches(self, data: dict):
        """Schedule image downloads out-of-band, without blocking startup."""
        if not data or "products" not in data or self.image_size <= 0:
            return
        try:
            count = 0
            for product in data["products"]:
                picture = product.get("picture_file_name")
                if picture:
                    product_id = int(product["id"])
                    self.hass.async_create_task(
                        self._fetch_and_update_image(product_id, picture)
                    )
                    count += 1
        except Exception:
            LOGGER.debug("Failed to schedule background image fetches", exc_info=True)

    async def _fetch_and_update_image(self, product_id: int, picture_file_name: str):
        """Fetch an image in background and dispatch an update for the product sensor."""
        async with self._image_fetch_semaphore:
            try:
                encoded_name = self.encode_base64(picture_file_name)
                response = await self.fetch_image(encoded_name)
                if response is None:
                    LOGGER.debug(
                        "No response while fetching image for product %s", product_id
                    )
                    return

                picture_bytes = await response.read()
                picture = base64.b64encode(picture_bytes).decode("utf-8")

                data_uri = f"data:image/png;base64,{picture}"

                try:
                    if self.final_data and isinstance(self.final_data, dict):
                        hap = self.final_data.get("homeassistant_products")
                        if isinstance(hap, dict):
                            key = str(product_id)
                            if key in hap and "attributes" in hap[key]:
                                hap[key]["attributes"]["product_image"] = picture
                                hap[key]["attributes"]["entity_picture"] = data_uri
                except Exception:
                    LOGGER.debug(
                        "Failed to persist background image into final_data for product %s",
                        product_id,
                        exc_info=True,
                    )

                async_dispatcher_send(
                    self.hass,
                    f"{DOMAIN}_add_or_update_sensor",
                    {
                        "product_id": product_id,
                        "attributes": {
                            "product_image": picture,
                            "entity_picture": data_uri,
                        },
                    },
                )

            except Exception as e:
                LOGGER.debug("Failed to fetch image for product %s: %s", product_id, e)

    async def update_grocy_shoppinglist_product(self, product_id: int, done: bool):
        """Mark a product as done or not in the shopping list."""
        return await self.request(
            "put",
            f"api/objects/shopping_list/{product_id}",
            "*/*",
            {"done": done},
        )

    async def remove_product_from_shopping_list(self, product_id: int):
        """Remove a product from the shopping list."""
        return await self.request(
            "delete",
            f"api/objects/shopping_list/{product_id}",
            "*/*",
            {},
        )

    async def update_grocy_product(
        self,
        product_id,
        qu_factor_purchase_to_stock,
        shopping_list_id,
        product_note,
        remove_product=False,
        quantity=1,
    ):
        """Update or remove a product from the shopping list."""
        endpoint = "remove-product" if remove_product else "add-product"

        grocy_quantity = quantity * float(qu_factor_purchase_to_stock)

        payload = {
            "product_id": int(product_id),
            "list_id": shopping_list_id,
            "product_amount": grocy_quantity,
        }

        if not remove_product:
            payload["note"] = product_note

        return await self.request(
            "post",
            f"api/stock/shoppinglist/{endpoint}",
            "*/*",
            payload,
        )

    async def manage_product(
        self, product_id, shopping_list_id=1, note="", remove_product=False, quantity=1
    ):
        """Add or remove a product from the shopping list."""
        entity = self.get_entity_in_hass(product_id)
        if entity is None:
            return

        state_value = entity.state
        if not state_value.isdigit():
            state_value = "0"

        attributes = entity.attributes.copy()
        if "product_id" in attributes:
            change = -quantity if remove_product else quantity
            total_qty = max(0, int(state_value) + change)
            qty = max(
                0,
                int(attributes.get(f"list_{shopping_list_id}_qty", 0)) + change,
            )
            list_count = max(
                0, attributes.get("list_count", 0) + (1 if not remove_product else -1)
            )

            await self.update_grocy_product(
                attributes.get("product_id"),
                attributes.get("qu_factor_purchase_to_stock", 1),
                str(shopping_list_id),
                note,
                remove_product,
                quantity,
            )

            if qty > 0:
                attributes_to_remove = []
                attributes.update(
                    {
                        "qty_in_shopping_lists": total_qty,
                        f"list_{shopping_list_id}_qty": qty,
                        f"list_{shopping_list_id}_note": note,
                        "list_count": list_count,
                    }
                )
            else:
                attributes_to_remove = [
                    f"list_{shopping_list_id}_qty",
                    f"list_{shopping_list_id}_note",
                    f"list_{shopping_list_id}_shop_list_id",
                ]
                attributes["qty_in_shopping_lists"] = total_qty
                attributes["list_count"] = list_count

            payload = {
                "product_id": attributes.get("product_id"),
                "qty_in_shopping_lists": total_qty,
                "attributes": attributes,
                "attributes_to_remove": attributes_to_remove,
            }

            async_dispatcher_send(
                self.hass,
                f"{DOMAIN}_add_or_update_sensor",
                payload,
            )

    async def update_note(self, product_id, shopping_list_id, note):
        """Update a note on a product in the shopping list."""
        entity = self.get_entity_in_hass(product_id)
        if entity is None:
            return

        payload = {
            "product_id": entity.attributes.get("product_id"),
            "shopping_list_id": shopping_list_id,
            "amount": entity.attributes.get(f"list_{shopping_list_id}_qty", 0),
            "note": note,
        }

        await self.request(
            "put",
            f"api/objects/shopping_list/{entity.attributes.get(f'list_{shopping_list_id}_shop_list_id')}",
            "*/*",
            payload,
        )

        entity_attributes = entity.attributes.copy()
        entity_attributes[f"list_{shopping_list_id}_note"] = note

        async_dispatcher_send(
            self.hass,
            "shopping_list_with_grocy_add_or_update_sensor",
            {
                "product_id": entity.attributes.get("product_id"),
                "qty_in_shopping_lists": entity.state,
                "attributes": entity_attributes,
            },
        )

    def normalize_text_for_search(self, text: str) -> str:
        """Normalize text for search by removing accents and converting to lowercase."""
        if not text:
            return ""

        normalized = unicodedata.normalize("NFD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")

        return ascii_text.lower().strip()

    def calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts using SequenceMatcher."""
        normalized1 = self.normalize_text_for_search(text1)
        normalized2 = self.normalize_text_for_search(text2)

        if not normalized1 or not normalized2:
            return 0.0

        return SequenceMatcher(None, normalized1, normalized2).ratio()

    def find_similar_products(self, search_name: str, threshold: float = 0.6) -> list:
        """Find products similar to the search term using fuzzy matching."""
        if not search_name or not self.final_data or "products" not in self.final_data:
            return []

        similar_products = []
        products = self.final_data["products"]

        for product in products:
            product_name = product.get("name", "")
            similarity = self.calculate_similarity(search_name, product_name)

            if similarity >= threshold:
                similar_products.append(
                    {
                        "id": product["id"],
                        "name": product_name,
                        "similarity": similarity,
                    }
                )

        similar_products.sort(key=lambda x: x["similarity"], reverse=True)

        return similar_products[:10]

    def is_case_only_difference(self, search_name: str, product_name: str) -> bool:
        """Check if two strings differ only by case (uppercase/lowercase)."""
        return (
            search_name.lower() == product_name.lower() and search_name != product_name
        )

    def extract_product_name_from_ha_item(self, item_name: str) -> tuple[str, int]:
        """Extract product name and quantity from Home Assistant item name."""
        item_name = item_name.strip()

        pattern1 = r"^(.+?)\s*\([x×](\d+)\)\s*$"
        match1 = re.match(pattern1, item_name)
        if match1:
            product_name = match1.group(1).strip()
            quantity = int(match1.group(2))
            LOGGER.error(
                "🔍 Extracted from HA item '%s' (pattern 1): name='%s', qty=%d",
                item_name,
                product_name,
                quantity,
            )
            return product_name, quantity

        pattern2 = r"^(\d+)\s+(.+)$"
        match2 = re.match(pattern2, item_name)
        if match2:
            quantity = int(match2.group(1))
            product_name = match2.group(2).strip()
            LOGGER.error(
                "🔍 Extracted from HA item '%s' (pattern 2): name='%s', qty=%d",
                item_name,
                product_name,
                quantity,
            )
            return product_name, quantity

        LOGGER.error(
            "🔍 No pattern matched for HA item '%s': name='%s', qty=1",
            item_name,
            item_name,
        )
        return item_name, 1

    async def search_product_in_grocy(self, search_name: str) -> dict:
        """Search for a product in Grocy by name with exact, contains, and fuzzy matching."""
        if not search_name:
            return {"found": False, "matches": [], "search_type": "none"}

        if not self.final_data or "products" not in self.final_data:
            LOGGER.error("❌ No product data available for search")
            return {"found": False, "matches": [], "search_type": "no_data"}

        products = self.final_data["products"]
        normalized_search = self.normalize_text_for_search(search_name)

        case_only_matches = []
        for product in products:
            product_name = product.get("name", "")
            if self.is_case_only_difference(search_name, product_name):
                case_only_matches.append(product)
                LOGGER.debug(
                    "Case-only match found: '%s' -> '%s' (ID: %s)",
                    search_name,
                    product_name,
                    product.get("id"),
                )

        if case_only_matches:
            return {
                "found": True,
                "matches": case_only_matches,
                "search_type": "case_only",
                "search_term": search_name,
            }

        exact_matches = []
        for product in products:
            product_name = product.get("name", "")
            normalized_product = self.normalize_text_for_search(product_name)

            if normalized_product == normalized_search:
                exact_matches.append(product)

        if exact_matches:
            return {
                "found": True,
                "matches": exact_matches,
                "search_type": "exact",
                "search_term": search_name,
            }

        contains_matches = []
        for product in products:
            product_name = product.get("name", "")
            normalized_product = self.normalize_text_for_search(product_name)

            if normalized_search in normalized_product:
                contains_matches.append(product)

        if contains_matches:
            return {
                "found": True,
                "matches": contains_matches,
                "search_type": "contains",
                "search_term": search_name,
            }

        LOGGER.debug("No exact/contains matches, trying fuzzy search...")
        similar_products = self.find_similar_products(search_name, threshold=0.6)

        if similar_products:
            LOGGER.debug(
                "Found %d similar products with fuzzy matching:",
                len(similar_products),
            )

            return {
                "found": True,
                "matches": similar_products,
                "search_type": "fuzzy",
                "search_term": search_name,
            }

        LOGGER.error(
            "❌ No matches found for '%s' (including fuzzy search)", search_name
        )
        return {
            "found": False,
            "matches": [],
            "search_type": "not_found",
            "search_term": search_name,
        }

    async def create_product_in_grocy(self, product_name: str) -> dict:
        """Create a new product in Grocy with default parameters."""
        if not product_name:
            raise ValueError("Product name is required")

        formatted_name = product_name.strip()
        if formatted_name:
            formatted_name = formatted_name[0].upper() + formatted_name[1:]

        LOGGER.debug("Creating new product in Grocy: '%s'", formatted_name)

        default_location_id = None
        default_qu_id = None

        if self.final_data:
            if "locations" in self.final_data and self.final_data["locations"]:
                default_location_id = self.final_data["locations"][0].get("id")
                LOGGER.debug("Using default location ID: %s", default_location_id)

            if (
                "quantity_units" in self.final_data
                and self.final_data["quantity_units"]
            ):
                default_qu_id = self.final_data["quantity_units"][0].get("id")
                LOGGER.debug("Using default quantity unit ID: %s", default_qu_id)

        if not default_location_id or not default_qu_id:
            raise ValueError(
                "Unable to get default location or quantity unit from Grocy"
            )

        payload = {
            "name": formatted_name,
            "location_id": default_location_id,
            "qu_id_stock": default_qu_id,
            "qu_id_purchase": default_qu_id,
            "qu_id_consume": default_qu_id,
            "qu_id_price": default_qu_id,
        }

        try:
            response = await self.request(
                "post",
                "api/objects/products",
                "application/json",
                payload,
            )

            result = await response.json()
            product_id = result.get("created_object_id")

            LOGGER.debug(
                "Product created successfully: '%s' with ID %s",
                formatted_name,
                product_id,
            )

            voice_mode = self.hass.data.get(DOMAIN, {}).get("voice_mode", False)
            if not voice_mode:
                title = await self.get_frontend_translation(
                    "product_created_notification_title"
                )
                message = await self.get_frontend_translation(
                    "product_created_notification_message",
                    product_name=formatted_name,
                    product_id=product_id,
                )

                await self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": title,
                        "message": message,
                        "notification_id": f"grocy_product_created_{product_id}",
                    },
                )

            return {
                "success": True,
                "product_id": product_id,
                "product_name": formatted_name,
            }

        except Exception as e:
            LOGGER.error("❌ Failed to create product '%s': %s", formatted_name, e)
            raise

    async def add_product_to_grocy_shopping_list(
        self,
        product_id: int,
        quantity: int = 1,
        shopping_list_id: int = 1,
        note: str = "",
    ):
        """Add a product to Grocy shopping list or increment existing quantity."""
        try:
            existing_entry = None
            if self.final_data and "shopping_list" in self.final_data:
                for item in self.final_data["shopping_list"]:
                    if int(item["product_id"]) == int(product_id) and int(
                        item["shopping_list_id"]
                    ) == int(shopping_list_id):
                        existing_entry = item
                        break

            if existing_entry:
                new_amount = int(existing_entry["amount"]) + quantity

                payload = {
                    "product_id": int(product_id),
                    "shopping_list_id": int(shopping_list_id),
                    "amount": new_amount,
                    "note": note or existing_entry.get("note", ""),
                }

                await self.request(
                    "put",
                    f"api/objects/shopping_list/{existing_entry['id']}",
                    "*/*",
                    payload,
                )

            else:
                payload = {
                    "product_id": int(product_id),
                    "list_id": shopping_list_id,
                    "product_amount": quantity,
                    "note": note,
                }

                await self.request(
                    "post",
                    "api/stock/shoppinglist/add-product",
                    "*/*",
                    payload,
                )

            return True

        except Exception as e:
            LOGGER.error("❌ Failed to add product to Grocy shopping list: %s", e)
            raise

    async def handle_ha_todo_item_creation(
        self, item_summary: str, shopping_list_id: int = 1
    ) -> dict:
        """Handle creation of a todo item from Home Assistant."""
        if not self.bidirectional_sync_enabled or self.bidirectional_sync_stopped:
            LOGGER.error("🚫 Bidirectional sync is disabled or stopped")
            return {"success": False, "reason": "sync_disabled"}

        if not self.final_data:
            LOGGER.error("⚠️ No data available, refreshing...")
            await self.retrieve_data(force=True)
            if not self.final_data:
                LOGGER.error("❌ Still no data after refresh, stopping for safety")
                self.stop_bidirectional_sync("No data available after refresh")
                return {"success": False, "reason": "no_data_safety_stop"}

        try:
            product_name, quantity = self.extract_product_name_from_ha_item(
                item_summary
            )

            LOGGER.error(
                "🔍 DEBUG: item_summary='%s' -> product_name='%s', quantity=%d",
                item_summary,
                product_name,
                quantity,
            )

            if not product_name:
                LOGGER.error("❌ Empty product name extracted from '%s'", item_summary)
                return {"success": False, "reason": "empty_name"}

            search_result = await self.search_product_in_grocy(product_name)

            if search_result["found"]:
                matches = search_result["matches"]

                should_auto_add = (
                    search_result.get("search_type") == "case_only"
                    or (
                        search_result.get("search_type") == "exact"
                        and len(matches) == 1
                    )
                    or (
                        len(matches) == 1
                        and self.is_case_only_difference(
                            product_name, matches[0]["name"]
                        )
                    )
                )

                if should_auto_add:

                    matched_product = matches[0]
                    search_type = search_result.get("search_type", "unknown")

                    add_result = await self.add_product_to_grocy_shopping_list(
                        matched_product["id"], quantity, shopping_list_id
                    )

                    if add_result:
                        return {
                            "success": True,
                            "reason": "auto_added_case_match",
                            "product_name": matched_product["name"],
                            "product_id": matched_product["id"],
                            "quantity": quantity,
                            "original_search": product_name,
                        }
                    else:
                        return {
                            "success": False,
                            "reason": "auto_add_failed",
                            "error": "Failed to add product to shopping list",
                        }
                else:

                    matches_with_create_option = matches.copy()
                    create_option_text = await self.get_frontend_translation(
                        "create_new_product", product_name=product_name
                    )
                    matches_with_create_option.append(
                        {
                            "id": "create_new",
                            "name": create_option_text,
                            "similarity": 0.0,
                            "is_create_option": True,
                        }
                    )

                    return {
                        "success": False,
                        "reason": "multiple_matches",
                        "matches": matches_with_create_option,
                        "search_term": product_name,
                        "quantity": quantity,
                        "shopping_list_id": shopping_list_id,
                    }

            else:
                create_option_text = await self.get_frontend_translation(
                    "create_new_product", product_name=product_name
                )

                return {
                    "success": False,
                    "reason": "multiple_matches",
                    "matches": [
                        {
                            "id": "create_new",
                            "name": create_option_text,
                            "similarity": 0.0,
                            "is_create_option": True,
                        }
                    ],
                    "search_term": product_name,
                    "quantity": quantity,
                    "shopping_list_id": shopping_list_id,
                }

        except Exception as e:
            LOGGER.error("❌ Error handling HA todo item creation: %s", e)
            return {"success": False, "reason": "error", "error": str(e)}

    def stop_bidirectional_sync(self, reason: str = "manual"):
        """Emergency stop for bidirectional sync."""
        self.bidirectional_sync_stopped = True
        LOGGER.error(
            "🛑 EMERGENCY STOP: Bidirectional sync has been stopped. Reason: %s", reason
        )

        self.hass.async_create_task(
            self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "⚠️ Shopping List Sync Stopped",
                    "message": f"Bidirectional sync has been emergency stopped due to: {reason}. Use the restart service to re-enable.",
                    "notification_id": "grocy_sync_emergency_stop",
                },
            )
        )

    def restart_bidirectional_sync(self):
        """Restart bidirectional sync after emergency stop."""
        self.bidirectional_sync_stopped = False
        LOGGER.error("🔄 Bidirectional sync has been restarted")

        self.hass.async_create_task(
            self.hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": "grocy_sync_emergency_stop"},
            )
        )

    def compute_timeout(self) -> int:
        table = {0: 60, 50: 60, 100: 90, 150: 120, 200: 180}
        if self.image_size in table:
            return table[self.image_size]
        nearest = min(table.keys(), key=lambda k: abs(k - int(self.image_size or 0)))
        return table[nearest]

    async def update_refreshing_status(self, refreshing):
        entity = self.hass.data[DOMAIN]["entities"].get(
            "updating_shopping_list_with_grocy"
        )

        if entity is None:
            return False

        self.hass.async_create_task(entity.update_state(refreshing))

    async def retrieve_data(self, force=False):
        """Retrieves data and updates if necessary."""
        try:
            last_db_changed_time = await self.fetch_last_db_changed_time()
            paused = is_update_paused(self.hass)

            should_update = force or (
                not paused
                and (
                    self.last_db_changed_time is None
                    or last_db_changed_time > self.last_db_changed_time
                )
            )

            if should_update:
                await self.update_refreshing_status(True)
                titles = [
                    "products",
                    "shopping_lists",
                    "shopping_list",
                    "locations",
                    "stock",
                    "product_groups",
                    "quantity_units",
                ]

                t = self.compute_timeout()

                if self.disable_timeout:
                    results = await asyncio.gather(
                        *(self.fetch_list(path) for path in titles),
                        return_exceptions=True,
                    )
                else:
                    async with timeout(t):
                        results = await asyncio.gather(
                            *(self.fetch_list(path) for path in titles),
                            return_exceptions=True,
                        )

                for idx, r in enumerate(results):
                    if isinstance(r, Exception):
                        LOGGER.warning("Fetch %s failed: %s", titles[idx], r)

                self.final_data = dict(zip(titles, results))

                if self.disable_timeout:
                    self.final_data["homeassistant_products"] = (
                        await self.parse_products(self.final_data)
                    )
                    self.final_data["shopping_lists_data"] = self.build_item_list(
                        self.final_data
                    )
                else:
                    async with timeout(t):
                        self.final_data["homeassistant_products"] = (
                            await self.parse_products(self.final_data)
                        )
                        self.final_data["shopping_lists_data"] = self.build_item_list(
                            self.final_data
                        )

                self.last_db_changed_time = last_db_changed_time
                self.hass.async_create_task(
                    self._kick_off_image_fetches(self.final_data)
                )

        finally:
            await self.update_refreshing_status(False)

        return self.final_data
