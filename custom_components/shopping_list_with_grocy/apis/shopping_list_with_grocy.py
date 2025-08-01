import asyncio
import base64
import json
import logging
import re
import time
import unicodedata
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import aiohttp
from async_timeout import timeout
from dateutil.relativedelta import relativedelta
from homeassistant.components.todo import (
    TodoItemStatus,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from ..const import DOMAIN, ENTITY_VERSION, OTHER_FIELDS
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
        self.final_data = []
        self.pagination_limit = 40
        self.disable_timeout = config.get("disable_timeout", False)

        self.current_time = datetime.now(timezone.utc)
        self.last_db_changed_time = None

        self.bidirectional_sync_enabled = config.get("enable_bidirectional_sync", False)
        self.bidirectional_sync_stopped = False

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
        shopping_list_details = {item["id"]: item for item in data["shopping_lists"]}

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

                if shopping_list_id not in shopping_list_map:
                    shopping_list = shopping_list_details.get(shopping_list_id)
                    if shopping_list:
                        shopping_list_map[shopping_list_id] = {
                            "id": shopping_list_id,
                            "name": shopping_list["name"],
                            "products": [],
                        }

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

        return list(shopping_list_map.values())

    async def request(
        self, method: str, url: str, accept: str, payload: dict = None, **kwargs
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

            timeout_value = None if self.disable_timeout else 30
            async with timeout(timeout_value):
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
                    LOGGER.error(
                        "Grocy API error: %s - %s", response.status, error_text
                    )
                    raise aiohttp.ClientError(
                        f"API request failed: {response.status} - {error_text}"
                    )

                return response

        except asyncio.TimeoutError as err:
            LOGGER.error("Timeout connecting to Grocy API at %s: %s", self.api_url, err)
            raise
        except aiohttp.ClientError as err:
            LOGGER.error("Error connecting to Grocy API at %s: %s", self.api_url, err)
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
        return await self.request("get", url, "application/octet-stream")

    async def fetch_last_db_changed_time(self):
        """Fetch the last database change timestamp."""
        response = await self.request(
            "get", "api/system/db-changed-time", "application/json"
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
            object_id = f"{DOMAIN}_product_v{ENTITY_VERSION}_{product_id}"
            entity = f"sensor.{object_id}"

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

            picture = ""
            if self.image_size > 0 and product.get("picture_file_name"):
                picture_response = await self.fetch_image(
                    self.encode_base64(product["picture_file_name"])
                )
                picture_bytes = await picture_response.read()
                picture = base64.b64encode(picture_bytes).decode("utf-8")

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

            stock_qty = sum(
                float(stock["amount"])
                for stock in data["stock"]
                if str(stock["product_id"]) == str(product_id)
            )
            opened_qty = sum(
                float(stock["amount"]) * int(stock["open"])
                for stock in data["stock"]
                if str(stock["product_id"]) == str(product_id)
            )

            unopened_qty = max(0, stock_qty - opened_qty)

            prod_dict = {
                "product_id": product_id,
                "parent_product_id": product.get("parent_product_id"),
                "qty_in_stock": round(stock_qty, 2),
                "qty_opened": round(opened_qty, 2),
                "qty_unopened": round(unopened_qty, 2),
                "qty_unit_purchase": qty_unit_purchase,
                "qty_unit_stock": qty_unit_stock,
                "qu_factor_purchase_to_stock": float(qty_factor),
                "product_image": picture,
                "location": location,
                "consume_location": consume_location,
                "group": group,
                "userfields": userfields,
                "list_count": len(shopping_lists),
            }

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
    ):
        """Update or remove a product from the shopping list."""
        endpoint = "remove-product" if remove_product else "add-product"
        payload = {
            "product_id": int(product_id),
            "list_id": shopping_list_id,
            "product_amount": round(float(qu_factor_purchase_to_stock)),
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
        self, product_id, shopping_list_id=1, note="", remove_product=False
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
            change = -1 if remove_product else 1
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

            async_dispatcher_send(
                self.hass,
                f"{DOMAIN}_add_or_update_sensor",
                {
                    "product_id": attributes.get("product_id"),
                    "qty_in_shopping_lists": total_qty,
                    "attributes": attributes,
                    "attributes_to_remove": attributes_to_remove,
                },
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

    def extract_product_name_from_ha_item(self, item_name: str) -> tuple[str, int]:
        """Extract product name and quantity from Home Assistant item name."""
        pattern = r"^(.+?)\s*\([x×](\d+)\)\s*$"
        match = re.match(pattern, item_name.strip())

        if match:
            product_name = match.group(1).strip()
            quantity = int(match.group(2))
            LOGGER.error(
                "🔍 Extracted from HA item '%s': name='%s', qty=%d",
                item_name,
                product_name,
                quantity,
            )
            return product_name, quantity

        LOGGER.error("🔍 No quantity pattern found in '%s', assuming qty=1", item_name)
        return item_name.strip(), 1

    async def search_product_in_grocy(self, search_name: str) -> dict:
        """Search for a product in Grocy by name with exact and fuzzy matching."""
        if not search_name:
            return {"found": False, "matches": [], "search_type": "none"}

        if not self.final_data or "products" not in self.final_data:
            LOGGER.error("❌ No product data available for search")
            return {"found": False, "matches": [], "search_type": "no_data"}

        products = self.final_data["products"]
        normalized_search = self.normalize_text_for_search(search_name)

        LOGGER.error(
            "🔍 Searching for product: '%s' (normalized: '%s')",
            search_name,
            normalized_search,
        )

        exact_matches = []
        for product in products:
            product_name = product.get("name", "")
            normalized_product = self.normalize_text_for_search(product_name)

            if normalized_product == normalized_search:
                exact_matches.append(product)
                LOGGER.error(
                    "✅ Exact match found: '%s' (ID: %s)",
                    product_name,
                    product.get("id"),
                )

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
                LOGGER.error(
                    "📝 Contains match found: '%s' (ID: %s)",
                    product_name,
                    product.get("id"),
                )

        if contains_matches:
            return {
                "found": True,
                "matches": contains_matches,
                "search_type": "contains",
                "search_term": search_name,
            }

        LOGGER.error("❌ No matches found for '%s'", search_name)
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

        LOGGER.error("🆕 Creating new product in Grocy: '%s'", formatted_name)

        default_location_id = None
        default_qu_id = None

        if self.final_data:
            if "locations" in self.final_data and self.final_data["locations"]:
                default_location_id = self.final_data["locations"][0].get("id")
                LOGGER.error("📍 Using default location ID: %s", default_location_id)

            if (
                "quantity_units" in self.final_data
                and self.final_data["quantity_units"]
            ):
                default_qu_id = self.final_data["quantity_units"][0].get("id")
                LOGGER.error("📏 Using default quantity unit ID: %s", default_qu_id)

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

            LOGGER.error(
                "✅ Product created successfully: '%s' with ID %s",
                formatted_name,
                product_id,
            )

            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "New Product Created",
                    "message": f"Product '{formatted_name}' was created automatically in Grocy (ID: {product_id})",
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
        LOGGER.error(
            "➕ Adding product ID %s to shopping list %s (qty: %d)",
            product_id,
            shopping_list_id,
            quantity,
        )

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
                LOGGER.error(
                    "📈 Product already exists, updating quantity from %s to %s",
                    existing_entry["amount"],
                    new_amount,
                )

                payload = {
                    "product_id": int(product_id),
                    "shopping_list_id": int(shopping_list_id),
                    "amount": new_amount,
                    "note": note or existing_entry.get("note", ""),
                }

                response = await self.request(
                    "put",
                    f"api/objects/shopping_list/{existing_entry['id']}",
                    "*/*",
                    payload,
                )

                LOGGER.error("✅ Product quantity updated in Grocy shopping list")

            else:
                payload = {
                    "product_id": int(product_id),
                    "list_id": shopping_list_id,
                    "product_amount": quantity,
                    "note": note,
                }

                response = await self.request(
                    "post",
                    "api/stock/shoppinglist/add-product",
                    "*/*",
                    payload,
                )

                LOGGER.error("✅ New product added to Grocy shopping list")

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

            if not product_name:
                LOGGER.error("❌ Empty product name extracted from '%s'", item_summary)
                return {"success": False, "reason": "empty_name"}

            search_result = await self.search_product_in_grocy(product_name)

            if search_result["found"]:
                matches = search_result["matches"]

                if len(matches) == 1:
                    product = matches[0]
                    product_id = product["id"]
                    LOGGER.error(
                        "✅ Single product match found: '%s' (ID: %s)",
                        product["name"],
                        product_id,
                    )

                elif len(matches) > 1:
                    LOGGER.error(
                        "⚠️ Multiple matches found for '%s': %d products",
                        product_name,
                        len(matches),
                    )
                    return {
                        "success": False,
                        "reason": "multiple_matches",
                        "matches": matches,
                        "search_term": product_name,
                        "quantity": quantity,
                        "shopping_list_id": shopping_list_id,
                    }

            else:
                LOGGER.error(
                    "🆕 No product found, creating new product: '%s'", product_name
                )
                create_result = await self.create_product_in_grocy(product_name)

                if not create_result["success"]:
                    return {"success": False, "reason": "creation_failed"}

                product_id = create_result["product_id"]

                await self.retrieve_data(force=True)

            await self.add_product_to_grocy_shopping_list(
                product_id, quantity, shopping_list_id
            )

            if hasattr(self, "coordinator"):
                await self.coordinator.async_refresh()

            return {
                "success": True,
                "product_id": product_id,
                "product_name": product_name,
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
                self.last_db_changed_time = last_db_changed_time

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

                if self.disable_timeout:
                    results = await asyncio.gather(
                        *(self.fetch_list(path) for path in titles)
                    )
                else:
                    async with timeout(60):
                        results = await asyncio.gather(
                            *(self.fetch_list(path) for path in titles)
                        )

                self.final_data = dict(zip(titles, results))

                if self.disable_timeout:
                    self.final_data["homeassistant_products"] = (
                        await self.parse_products(self.final_data)
                    )
                else:
                    async with timeout(60):
                        self.final_data["homeassistant_products"] = (
                            await self.parse_products(self.final_data)
                        )

        finally:
            await self.update_refreshing_status(False)

        return self.final_data
