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
import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish
from async_timeout import timeout
from dateutil.relativedelta import relativedelta
from homeassistant.components.todo import (
    TodoItemStatus,
)
from homeassistant.core import HomeAssistant

from ..const import DOMAIN, MQTT_ENTITY_VERSION, OTHER_FIELDS

LOGGER = logging.getLogger(__name__)


class ShoppingListWithGrocyApi:
    def __init__(self, websession: aiohttp.ClientSession, hass: HomeAssistant, config):
        """Initialize the API client."""
        self.hass = hass
        self.config = config
        self.web_session = websession

        # Configuration API
        self.api_url = config.get("api_url")
        self.verify_ssl = config.get("verify_ssl", True)
        self.api_key = config.get("api_key")

        # Configuration MQTT
        self.mqtt_server = config.get("mqtt_server", "127.0.0.1")
        self.mqtt_port = config.get("mqtt_custom_port", config.get("mqtt_port", 1883))
        self.mqtt_username = config.get("mqtt_username") or None
        self.mqtt_password = config.get("mqtt_password") or None

        # Image and data management
        self.image_size = config.get("image_download_size", 0)
        self.ha_products = []
        self.final_data = []
        self.pagination_limit = 40

        # Topics MQTT
        self.config_topic = "homeassistant/sensor/shopping_list_with_grocy/"
        self.state_topic = "shopping-list-with-grocy/products/"

        # Time management
        self.current_time = datetime.now(timezone.utc)
        self.last_db_changed_time = None

        # MQTT Initialization
        self.mqtt_lock = (
            asyncio.Lock()
        )  # Ajout d'un verrou pour éviter les accès concurrents
        self.client = mqtt.Client(client_id="ha-client")
        self.client.on_connect = self.on_connect

        if self.mqtt_username and self.mqtt_password:
            self.client.username_pw_set(self.mqtt_username, self.mqtt_password)

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

    @asynccontextmanager
    async def mqtt_session(self):
        """Centralized MQTT connection management with detailed logs."""
        LOGGER.debug(
            "🟢 Connecting to MQTT server: %s:%s", self.mqtt_server, self.mqtt_port
        )

        try:
            self.client.connect(self.mqtt_server, self.mqtt_port)
            self.client.loop_start()
            yield
        finally:
            LOGGER.debug("🔴 Disconnecting from MQTT server")
            self.client.disconnect()
            self.client.loop_stop()

    async def create_mqtt_sensor(
        self, object_id, product_name, state_topic, attributes_topic
    ):
        """Creates a MQTT sensor that is properly integrated with Home Assistant"""
        discovery_topic = f"{self.config_topic}{object_id}/config"

        sensor_config = {
            "name": product_name,
            "state_topic": state_topic,
            "json_attributes_topic": attributes_topic,
            "json_attributes_template": "{{ value_json | tojson }}",
            "icon": "mdi:cart",
            "unique_id": f"shopping_list_with_grocy_{object_id}",
            "object_id": object_id,
            "unit_of_measurement": "pcs",
        }

        LOGGER.debug(
            "🟢 Création du sensor MQTT : %s", json.dumps(sensor_config, indent=2)
        )

        await self.mqtt_publish(discovery_topic, json.dumps(sensor_config))

    async def update_object_in_mqtt(self, topic, subject):
        """Secure MQTT publishing with `retain=True`, ensuring connection before publishing."""
        if not topic or subject is None:
            LOGGER.error(
                "❌ MQTT publish failed: topic is empty or subject is None. Topic: %s, Subject: %s",
                subject,
            )
            return

        # Checks if MQTT session is available
        session = self.mqtt_session()
        if session is None:
            LOGGER.error(
                "❌ MQTT publish failed: MQTT session is None. Topic: %s", topic
            )
            return

        async with self.mqtt_lock:  # Prevents multiple simultaneous posts
            try:
                async with session:  # Handles MQTT session properly
                    LOGGER.debug(
                        "✅ Publishing to MQTT topic: %s, Payload: %s", topic, subject
                    )
                    self.client.publish(
                        topic, subject if subject else "", qos=0, retain=True
                    )
            except Exception as e:
                LOGGER.error("⚠️ MQTT publish error: %s", str(e))

    def serialize_datetime(self, obj):
        """Serialize a datetime or date object to ISO format."""
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError(
            "serialize_datetime expects a datetime or date object, got %s"
            % type(obj).__name__
        )

    def on_connect(self, client, userdata, flags, rc):
        """Handle MQTT connection events."""
        mqtt_errors = {
            0: "Connection successful",
            1: "Connection refused – incorrect protocol version",
            2: "Connection refused – invalid client identifier",
            3: "Connection refused – server unavailable",
            4: "Connection refused – bad username or password",
            5: "Connection refused – not authorized",
        }
        if rc == 0:
            LOGGER.debug("Connected to MQTT Broker!")
        else:
            LOGGER.error(
                "Failed to connect to MQTT Broker: %s",
                mqtt_errors.get(rc, "Unknown error"),
            )

    def build_item_list(self, data) -> list:
        if data is None or "shopping_lists" not in data:
            return []

        shopping_list_map = {}  # Stores already created shopping lists
        shopping_list_details = {item["id"]: item for item in data["shopping_lists"]}

        for product in data["products"]:
            product_id = product["id"]
            qty_factor = (
                float(product["qu_factor_purchase_to_stock"])
                if "qu_factor_purchase_to_stock" in product
                and product["qu_id_purchase"] != product["qu_id_stock"]
                else 1.0
            )

            for in_shopping_list in data["shopping_list"]:
                if product_id != in_shopping_list["product_id"]:
                    continue

                shopping_list_id = in_shopping_list["shopping_list_id"]

                # Retrieving the shopping list
                if shopping_list_id not in shopping_list_map:
                    shopping_list = shopping_list_details.get(shopping_list_id)
                    if shopping_list:
                        shopping_list_map[shopping_list_id] = {
                            "id": shopping_list_id,
                            "name": shopping_list["name"],
                            "products": [],
                        }

                # Adding the product to the list
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
                                if in_shopping_list["done"] == "0"
                                else TodoItemStatus.COMPLETED
                            ),
                        }
                    )

        return list(shopping_list_map.values())

    async def request(
        self, method: str, url: str, accept: str, payload: dict = None, **kwargs
    ) -> aiohttp.ClientResponse:
        """Make an asynchronous HTTP request."""
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

        return await self.web_session.request(
            method,
            f"{self.api_url.rstrip('/')}/{url}",
            headers=headers,
            json=payload if payload and not is_get else None,
            ssl=self.verify_ssl,
            **kwargs,
        )

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

        # Parsing JSON response efficiently
        last_changed = await response.json()

        return datetime.strptime(last_changed["changed_time"], "%Y-%m-%d %H:%M:%S")

    async def fetch_list(self, path: str, max_pages: int = 1000):
        """Retrieves data."""
        data = []
        offset = 0

        while True:
            if path == "stock":
                response = await self.request("get", f"api/{path}", "application/json")
            else:
                response = await self.fetch_products(path, offset)

            new_results = await response.json()

            # Stop condition: if no new result is returned
            if not new_results:
                break

            data.extend(new_results)

            # Managing the maximum number of pages to avoid infinite loops
            offset += self.pagination_limit
            if offset // self.pagination_limit >= max_pages:
                break

        return data

    async def remove_product(self, product):
        """Remove a product by clearing its MQTT topics."""
        if product.endswith("))"):
            product = product[:-2]

        entity_id = product.removeprefix("sensor.")
        LOGGER.debug("Product %s not found on Grocy, deleting it...", entity_id)

        base_topic = f"{self.state_topic}{entity_id}"
        topics = [
            f"{self.config_topic}{entity_id}/config",
            f"{base_topic}/state",
            f"{base_topic}/attributes",
        ]

        for topic in topics:
            await self.update_object_in_mqtt(topic, "")

    async def parse_products(self, data):
        """Parse products data and update MQTT topics."""
        self.current_time = datetime.now(timezone.utc)

        # Optimizing Home Assistant entity search
        entities = set(self.hass.states.async_entity_ids())
        rex = re.compile(r"sensor.shopping_list_with_grocy_[^|]+")
        self.ha_products = set(rex.findall("|".join(entities)))

        # Indexing data to avoid repeated searches
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

        for product in data["products"]:
            product_id = product["id"]
            object_id = (
                f"shopping_list_with_grocy_product_v{MQTT_ENTITY_VERSION}_{product_id}"
            )
            entity = f"sensor.{object_id}"

            # Retrieving product fields
            userfields = product.get("userfields", {})
            qty_factor = (
                float(product.get("qu_factor_purchase_to_stock", 1.0))
                if product.get("qu_id_purchase") != product.get("qu_id_stock")
                else 1.0
            )

            # Unit Recovery
            qty_unit_purchase = quantity_units.get(product.get("qu_id_purchase"), "")
            qty_unit_stock = quantity_units.get(product.get("qu_id_stock"), "")

            # Retrieving location information
            location = locations.get(product.get("location_id"), "")
            consume_location = locations.get(
                product.get("default_consume_location_id"), ""
            )
            group = product_groups.get(product.get("product_group_id"), "")

            # Product Image Management
            picture = ""
            if self.image_size > 0 and product.get("picture_file_name"):
                picture_response = await self.fetch_image(
                    self.encode_base64(product["picture_file_name"])
                )
                picture_bytes = await picture_response.read()
                picture = base64.b64encode(picture_bytes).decode("utf-8")

            # Building MQTT topics
            config_topic = f"{self.config_topic}{object_id}/config"
            state_topic = f"{self.state_topic}{object_id}/state"
            attributes_topic = f"{self.state_topic}{object_id}/attributes"

            # Initialization of shopping lists and quantities
            shopping_lists = {}
            qty_in_shopping_lists = 0

            # Processing shopping lists
            for in_shopping_list in data["shopping_list"]:
                if product_id == in_shopping_list["product_id"]:
                    shopping_list_id = in_shopping_list["shopping_list_id"]
                    in_shop_list = str(
                        round(int(in_shopping_list["amount"]) / qty_factor)
                    )
                    shopping_lists[f"list_{shopping_list_id}"] = {
                        "shop_list_id": in_shopping_list["id"],
                        "qty": int(in_shop_list),
                        "note": in_shopping_list.get("note", ""),
                    }
                    qty_in_shopping_lists += int(in_shop_list)

            # Calculation of stock quantities
            stock_qty = sum(
                int(stock["amount"])
                for stock in data["stock"]
                if stock["product_id"] == product_id
            )
            aggregated_qty = sum(
                float(stock["amount_aggregated"])
                for stock in data["stock"]
                if stock["product_id"] == product_id
            )
            opened_qty = sum(
                int(stock["amount_opened"])
                for stock in data["stock"]
                if stock["product_id"] == product_id
            )
            opened_aggregated_qty = sum(
                float(stock["amount_opened_aggregated"])
                for stock in data["stock"]
                if stock["product_id"] == product_id
            )

            unopened_qty = max(0, stock_qty - opened_qty)
            unopened_aggregated_qty = max(0, aggregated_qty - opened_aggregated_qty)

            # Recovering the existing entity
            entity_state = self.get_entity_in_hass(entity)

            # Checking if the entity needs to be updated
            if entity_state is None or entity_state.last_updated <= self.current_time:
                prod_dict = {
                    "product_id": product_id,
                    "parent_product_id": product.get("parent_product_id"),
                    "qty_in_stock": str(stock_qty),
                    "qty_opened": opened_qty,
                    "qty_unopened": unopened_qty,
                    "qty_unit_purchase": qty_unit_purchase,
                    "qty_unit_stock": qty_unit_stock,
                    "aggregated_stock": str(aggregated_qty),
                    "aggregated_opened": opened_aggregated_qty,
                    "aggregated_unopened": unopened_aggregated_qty,
                    "qu_factor_purchase_to_stock": str(qty_factor),
                    "product_image": picture,
                    "topic": state_topic,
                    "location": location,
                    "consume_location": consume_location,
                    "group": group,
                    "userfields": userfields,
                    "list_count": len(shopping_lists),
                }

                # Added shopping_list information
                for shop_list, details in shopping_lists.items():
                    prod_dict.update(
                        {
                            f"{shop_list}_qty": details["qty"],
                            f"{shop_list}_shop_list_id": details["shop_list_id"],
                            f"{shop_list}_note": details["note"],
                        }
                    )

                # Adding other fields
                for field in OTHER_FIELDS:
                    if field in product:
                        prod_dict[field] = product[field]

                # MQTT Status Update
                LOGGER.debug(
                    "🟢 Mise à jour de l'état MQTT - Object ID: %s, State Topic: %s, Attributes Topic: %s",
                    object_id,
                    state_topic,
                    attributes_topic,
                )

                # Check before publication
                if not state_topic or not attributes_topic:
                    LOGGER.error(
                        "❌ MQTT Sensor non mis à jour, state_topic ou attributes_topic est vide !"
                    )
                else:
                    await self.update_object_in_mqtt(state_topic, qty_in_shopping_lists)
                    await self.update_object_in_mqtt(
                        attributes_topic, json.dumps(prod_dict)
                    )

            # Create a new entity if it does not exist
            if entity_state is None:
                LOGGER.debug(
                    "Product %s (%s) not found, creating it...", product["name"], entity
                )
                LOGGER.debug(
                    "🟢 Création du sensor MQTT - Object ID: %s, State Topic: %s, Attributes Topic: %s",
                    object_id,
                    state_topic,
                    attributes_topic,
                )

                if state_topic and attributes_topic:
                    await self.create_mqtt_sensor(
                        object_id, product["name"], state_topic, attributes_topic
                    )
                else:
                    LOGGER.error(
                        "❌ MQTT Sensor non créé, state_topic ou attributes_topic est vide !"
                    )

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

    async def mqtt_publish(self, topic: str, payload):
        """Publish a message to MQTT with optimized connection handling."""
        if not topic or payload is None or payload == "":
            LOGGER.error(
                "❌ MQTT publish failed: topic or subject is empty. Topic: %s, Payload: %s",
                topic,
                payload,
            )
            return

        await self.update_object_in_mqtt(topic, payload)

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
            total_qty = max(0, int(state_value) + (-1 if remove_product else 1))
            qty = max(
                0,
                int(attributes.get(f"list_{shopping_list_id}_qty", 0))
                + (-1 if remove_product else 1),
            )
            list_count = max(
                0, attributes.get("list_count", 0) + (1 if not remove_product else -1)
            )

            await self.update_grocy_product(
                attributes.get("product_id"),
                attributes.get("qu_factor_purchase_to_stock"),
                str(shopping_list_id),
                note,
                remove_product,
            )

            # Updating Attributes
            if qty > 0:
                attributes.update(
                    {
                        "qty_in_shopping_lists": total_qty,
                        f"list_{shopping_list_id}_qty": qty,
                        f"list_{shopping_list_id}_note": note,
                        "list_count": list_count,
                    }
                )
            else:
                for key in [
                    f"list_{shopping_list_id}_qty",
                    f"list_{shopping_list_id}_note",
                    f"list_{shopping_list_id}_shop_list_id",
                ]:
                    attributes.pop(key, None)
                attributes["qty_in_shopping_lists"] = total_qty
                attributes["list_count"] = list_count

            # Publication MQTT
            await self.mqtt_publish(
                attributes.get("topic").replace("state", "attributes"),
                json.dumps(attributes),
            )
            await self.mqtt_publish(attributes.get("topic"), total_qty)

    async def update_note(self, product_id, shopping_list_id, note):
        """Update a note on a product in the shopping list."""
        LOGGER.debug("update_note, product_id: %s", product_id)
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
        await self.mqtt_publish(
            entity_attributes.get("topic").replace("state", "attributes"),
            json.dumps(entity_attributes),
        )

    async def create_mqtt_binary_sensor(
        self, object_id, name, state_topic, availability_topic, icon="mdi:refresh"
    ):
        """Creates a binary MQTT sensor properly integrated with Home Assistant"""
        discovery_topic = f"homeassistant/binary_sensor/{object_id}/config"
        sensor_config = {
            "name": name,
            "state_topic": state_topic,
            "payload_on": "ON",
            "payload_off": "OFF",
            "availability": [
                {
                    "topic": availability_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                }
            ],
            "icon": icon,
            "unique_id": object_id,
            "object_id": object_id,
        }

        LOGGER.debug(
            "🟢 Création du sensor MQTT : %s", json.dumps(sensor_config, indent=2)
        )
        await self.update_object_in_mqtt(discovery_topic, json.dumps(sensor_config))
        await self.update_object_in_mqtt(availability_topic, "online")

    async def create_mqtt_switch_sensor(
        self, object_id, name, state_topic, availability_topic, icon="mdi:refresh"
    ):
        """Creates a switch MQTT sensor properly integrated with Home Assistant"""
        discovery_topic = f"homeassistant/switch/{object_id}/config"
        sensor_config = {
            "name": name,
            "state_topic": state_topic,
            "payload_on": "ON",
            "payload_off": "OFF",
            "state_on": "ON",
            "state_off": "OFF",
            "availability": [
                {
                    "topic": availability_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                }
            ],
            "command_topic": state_topic,
            "optimistic": False,
            "entity_category": "config",
            "icon": icon,
            "unique_id": object_id,
            "object_id": object_id,
        }

        LOGGER.debug(
            "🟢 Création du sensor MQTT : %s", json.dumps(sensor_config, indent=2)
        )
        await self.update_object_in_mqtt(discovery_topic, json.dumps(sensor_config))
        await self.update_object_in_mqtt(availability_topic, "online")

    async def update_refreshing_status(self, refreshing):
        """Updates the refresh status"""
        object_id = "updating_shopping_list_with_grocy"
        topic = "shopping-list-with-grocy/binary_sensor/updating"
        state_topic = f"{topic}/state"
        availability_topic = f"{topic}/availability"

        entity = self.get_entity_in_hass(f"binary_sensor.{object_id}")

        if entity is None:
            await self.create_mqtt_binary_sensor(
                object_id,
                "ShoppingListWithGrocy Update in progress",
                state_topic,
                availability_topic,
            )
            await self.update_object_in_mqtt(state_topic, refreshing)
            return False

        await self.update_object_in_mqtt(state_topic, refreshing)

    async def is_update_paused(self):
        """Check if the update is paused."""
        object_id = "pause_update_shopping_list_with_grocy"
        topic = "shopping-list-with-grocy/switch/pause_update"
        state_topic = f"{topic}/state"
        availability_topic = f"{topic}/availability"
        entity = self.get_entity_in_hass(f"switch.{object_id}")

        if entity is None:
            await self.create_mqtt_switch_sensor(
                object_id,
                "ShoppingListWithGrocy Pause update",
                state_topic,
                availability_topic,
                "mdi:pause-octagon",
            )
            await self.update_object_in_mqtt(state_topic, "OFF")
            return False

        return entity.state == "on"

    async def retrieve_data(self, force=False):
        """Retrieves data and updates if necessary."""
        await self.update_refreshing_status("ON")
        try:
            last_db_changed_time = await self.fetch_last_db_changed_time()
            is_update_paused = await self.is_update_paused()

            # Checking if an update is needed
            should_update = force or (
                not is_update_paused
                and (
                    self.last_db_changed_time is None
                    or last_db_changed_time > self.last_db_changed_time
                )
            )
            if should_update:
                self.last_db_changed_time = last_db_changed_time
            else:
                return self.final_data

            async with self.mqtt_session():
                async with timeout(60):
                    LOGGER.info("Fetching new data from Grocy API")

                    titles = [
                        "products",
                        "shopping_lists",
                        "shopping_list",
                        "locations",
                        "stock",
                        "product_groups",
                        "quantity_units",
                    ]
                    # Exécuter les requêtes en parallèle pour plus d'efficacité
                    results = await asyncio.gather(
                        *(self.fetch_list(path) for path in titles)
                    )

                    self.final_data = dict(zip(titles, results))  # Met à jour le cache
                    await self.parse_products(self.final_data)
        finally:
            await self.update_refreshing_status("OFF")

        return self.final_data
