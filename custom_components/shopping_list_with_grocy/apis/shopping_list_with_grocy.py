import base64
import json
import logging
import re
import unicodedata
from asyncio import gather
from datetime import date, datetime, timedelta, timezone

import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish
from aiohttp import ClientResponse, ClientSession
from async_timeout import timeout
from dateutil.relativedelta import relativedelta
from homeassistant.core import HomeAssistant

from ..const import DOMAIN

LOGGER = logging.getLogger(__name__)


class ShoppingListWithGrocyApi:
    def __init__(self, websession: ClientSession, hass: HomeAssistant, config):
        self.hass = hass
        self.config = config
        self.web_session = websession
        self.api_url = config.get("api_url")
        self.verify_ssl = config.get("verify_ssl")
        if self.verify_ssl is None:
            self.verify_ssl = True
        self.api_key = config.get("api_key")
        self.mqtt_server = config.get("mqtt_server", "127.0.0.1")
        self.mqtt_port = config.get("mqtt_port", 1883)
        self.mqtt_username = config.get("mqtt_username", None)
        self.mqtt_password = config.get("mqtt_password", None)
        self.ha_products = []
        self.final_data = []
        self.state_topic = "homeassistant/sensor/"
        self.current_time = datetime.now(timezone.utc)
        self.client = mqtt.Client("ha-client")
        if self.mqtt_username is not None and self.mqtt_password is not None:
            self.client.username_pw_set(self.mqtt_username, self.mqtt_password)
        self.last_db_changed_time = None

    def get_entity_in_hass(self, entity_id):
        return self.hass.states.get(entity_id)

    def strip_accents(self, s):
        return "".join(
            c
            for c in unicodedata.normalize("NFD", s)
            if unicodedata.category(c) != "Mn"
        )

    def replace_umlauts(self, s):
        """replace special German umlauts (vowel mutations) from text.
        ä -> ae...
        ü -> ue
        """
        vowel_char_map = {
            ord("ä"): "ae",
            ord("ü"): "ue",
            ord("ö"): "oe",
            ord("ß"): "ss",
        }

        return s.translate(vowel_char_map)

    def slugify(self, s):
        s = s.lower().strip()
        s = re.sub(r"[^\w\s-]", "", s)
        s = re.sub(r"[\s_-]+", "_", s)
        s = re.sub(r"^-+|-+$", "", s)

        return self.strip_accents(self.replace_umlauts(s))

    def encode_base64(self, message):
        message_bytes = message.encode()
        base64_bytes = base64.b64encode(message_bytes)

        return base64_bytes.decode()

    def update_object_in_mqtt(self, topic, subject):
        self.client.publish(
            topic,
            subject,
            qos=0,
            retain=True,
        )

    async def request(
        self, method, url, accept, payload={}, **kwargs
    ) -> ClientResponse:
        """Make a request."""
        if method == "get":
            headers = {
                **kwargs.get("headers", {}),
                "accept": accept,
                "GROCY-API-KEY": f"{self.api_key}",
                "cache-control": "no-cache",
            }
            return await self.web_session.request(
                method,
                f"{self.api_url.strip('/')}/{url}",
                **kwargs,
                headers=headers,
            )

        headers = {
            **kwargs.get("headers", {}),
            "accept": accept,
            "GROCY-API-KEY": f"{self.api_key}",
            "Content-Type": "application/json",
        }

        return await self.web_session.request(
            method,
            f"{self.api_url.strip('/')}/{url}",
            **kwargs,
            headers=headers,
            data=payload,
            ssl=self.verify_ssl,
        )

    async def fetch_products(self, path: str):
        return await self.request(
            "get",
            f"api/objects/{path}" + ("?order=name%3Aasc" if path == "products" else ""),
            "application/json",
        )

    async def fetch_image(self, image_name: str):
        return await self.request(
            "get",
            f"api/files/productpictures/{image_name}?force_serve_as=picture&best_fit_width=180",
            "application/octet-stream",
        )

    async def fetch_last_db_changed_time(self):
        response = await self.request(
            "get",
            f"api/system/db-changed-time",
            "application/json",
        )
        last_changed = await response.json()

        return datetime.strptime(last_changed["changed_time"], "%Y-%m-%d %H:%M:%S")

    async def fetch_list(self, path: str):
        data = {}
        response = await self.fetch_products(path)
        data = await response.json()

        return data

    async def parse_products(self, data):
        self.current_time = datetime.now(timezone.utc)

        entities = self.hass.states.async_entity_ids()
        rex = re.compile("sensor.shopping_list_with_grocy_[^|]+")
        self.ha_products = rex.findall(r"(?=(" + "|".join(entities) + r"))")

        self.client.connect(self.mqtt_server, self.mqtt_port)
        self.client.loop_start()
        for product in data["products"]:
            shop_list_id = ""
            in_shop_list = "0"
            note = ""
            picture = ""
            location = ""
            group = ""
            product_name = product["name"]
            product_id = product["id"]
            product_picture = product["picture_file_name"]
            product_location = product["location_id"]
            product_group = product["product_group_id"]
            slug = self.slugify(product_name)
            object_id = "shopping_list_with_grocy_" + slug
            topic = self.state_topic + object_id + "/state"
            entity = "sensor." + object_id
            if entity in self.ha_products:
                self.ha_products.remove(entity)

            if product_picture is not None and product_picture != "null":
                picture_response = await self.fetch_image(
                    self.encode_base64(product_picture)
                )
                picture_bytes = await picture_response.read()
                picture = base64.b64encode(picture_bytes).decode("utf-8")

            for in_shopping_list in data["shopping_list"]:
                if product_id == in_shopping_list["product_id"]:
                    shop_list_id = in_shopping_list["id"]
                    in_shop_list = in_shopping_list["amount"]
                    note = (
                        in_shopping_list["note"]
                        if (
                            in_shopping_list["note"] is not None
                            and in_shopping_list["note"] != "null"
                        )
                        else ""
                    )

            if product_location is not None and product_location != "null":
                for locations in data["locations"]:
                    if product_location == locations["id"]:
                        location = locations["name"]

            if product_group is not None and product_group != "null":
                for groups in data["product_groups"]:
                    if product_group == groups["id"]:
                        group = groups["name"]

            entity = self.get_entity_in_hass("sensor." + object_id)

            if entity is None:
                LOGGER.debug(
                    "Product %s (%s) not found, creating it...",
                    product_name,
                    "sensor." + object_id,
                )
                prod_dict_config = {
                    "name": product_name,
                    "value_template": "{{ value_json.qty_in_shopping_list }}",
                    "json_attributes_topic": topic,
                    "state_topic": topic,
                    "icon": "mdi:cart",
                    "unique_id": object_id,
                    "object_id": object_id,
                }
                self.update_object_in_mqtt(
                    topic + "/config",
                    json.dumps(prod_dict_config),
                )

            if entity is None or entity.last_updated <= self.current_time:
                prod_dict = {
                    "product_id": product_id,
                    "id_in_shopping_list": shop_list_id,
                    "qty_in_shopping_list": in_shop_list,
                    "product_image": picture,
                    "topic": topic,
                    "note": note,
                    "location": location,
                    "group": group,
                }
                self.update_object_in_mqtt(
                    topic,
                    json.dumps(prod_dict),
                )

        if len(self.ha_products) > 0:
            for product in self.ha_products:
                if product.endswith("))"):
                    product = product[:-2]

                entity_id = product.replace("sensor.", "")
                LOGGER.error("product %s not found on Grocy, deleting it...", entity_id)
                topic = self.state_topic + entity_id + "/state"
                self.update_object_in_mqtt(
                    topic + "/config",
                    "",
                )
                self.update_object_in_mqtt(
                    topic,
                    "",
                )
        self.client.loop_stop()
        self.client.disconnect()

    async def update_grocy_product(
        self, product_id, product_note, remove_product=False
    ):
        endpoint = "remove-product" if remove_product else "add-product"
        payload = {
            "product_id": int(product_id),
            "list_id": 1,
            "product_amount": 1,
            "note": product_note,
        }
        if remove_product:
            payload = {"product_id": int(product_id), "list_id": 1, "product_amount": 1}

        return await self.request(
            "post",
            f"api/stock/shoppinglist/{endpoint}",
            "*/*",
            json.dumps(payload),
        )

    async def manage_product(self, product_id, note="", remove_product=False):
        LOGGER.debug("manage_product, product_id: %s", product_id)
        entity = self.get_entity_in_hass(product_id)
        if entity is not None:
            qty = int(entity.attributes.get("qty_in_shopping_list")) + 1
            if remove_product:
                qty = int(entity.attributes.get("qty_in_shopping_list")) - 1
            await self.update_grocy_product(
                entity.attributes.get("product_id"), note, remove_product
            )
            entity_attributes = entity.attributes.copy()
            entity_attributes.update(qty_in_shopping_list=qty, note=note)
            self.client.connect(self.mqtt_server, self.mqtt_port)
            self.client.loop_start()
            self.update_object_in_mqtt(
                entity_attributes.get("topic"),
                json.dumps(entity_attributes),
            )
            self.client.loop_stop()
            self.client.disconnect()

    async def update_note(self, product_id, note):
        LOGGER.debug("update_note, product_id: %s", product_id)
        entity = self.get_entity_in_hass(product_id)
        if entity is not None:
            payload = {
                "product_id": entity.attributes.get("product_id"),
                "shopping_list_id": "1",
                "amount": entity.attributes.get("qty_in_shopping_list"),
                "note": note,
            }

            await self.request(
                "put",
                f"api/objects/shopping_list/{entity.attributes.get('id_in_shopping_list')}",
                "*/*",
                json.dumps(payload),
            )
            entity_attributes = entity.attributes.copy()
            entity_attributes.update(note=note)
            self.client.connect(self.mqtt_server, self.mqtt_port)
            self.client.loop_start()
            self.update_object_in_mqtt(
                entity_attributes.get("topic"),
                json.dumps(entity_attributes),
            )
            self.client.loop_stop()
            self.client.disconnect()

    async def update_refreshing_status(self, refreshing):
        object_id = "updating_shopping_list_with_grocy"
        topic = "shopping-list-with-grocy/binary_sensor/updating"
        state_topic = topic + "/state"
        availability_topic = topic + "/availability"
        entity = self.get_entity_in_hass("binary_sensor." + object_id)

        self.client.connect(self.mqtt_server, self.mqtt_port)
        self.client.loop_start()
        if entity is None:
            prod_dict_config = {
                "name": "ShoppingListWithGrocy Update in progress",
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
                "icon": "mdi:refresh",
                "unique_id": object_id,
                "object_id": object_id,
            }
            self.update_object_in_mqtt(
                "homeassistant/binary_sensor/" + object_id + "/config",
                json.dumps(prod_dict_config),
            )
            self.update_object_in_mqtt(
                availability_topic,
                "online",
            )

        self.update_object_in_mqtt(
            state_topic,
            refreshing,
        )
        self.client.loop_stop()
        self.client.disconnect()

    async def is_update_paused(self):
        object_id = "pause_update_shopping_list_with_grocy"
        topic = "shopping-list-with-grocy/switch/pause_update"
        state_topic = topic + "/state"
        availability_topic = topic + "/availability"
        entity = self.get_entity_in_hass("switch." + object_id)

        if entity is None:
            self.client.connect(self.mqtt_server, self.mqtt_port)
            self.client.loop_start()
            prod_dict_config = {
                "name": "ShoppingListWithGrocy Pause update",
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
                "icon": "mdi:pause-octagon",
                "unique_id": object_id,
                "object_id": object_id,
            }
            self.update_object_in_mqtt(
                "homeassistant/switch/" + object_id + "/config",
                json.dumps(prod_dict_config),
            )
            self.update_object_in_mqtt(
                availability_topic,
                "online",
            )
            self.update_object_in_mqtt(
                state_topic,
                "OFF",
            )
            self.client.loop_stop()
            self.client.disconnect()
            return False

        return entity.state == "on"

    async def retrieve_data(self, force=False):
        last_db_changed_time = await self.fetch_last_db_changed_time()
        is_update_paused = await self.is_update_paused()
        update_data = False
        if not is_update_paused and (
            self.last_db_changed_time is None
            or (last_db_changed_time > self.last_db_changed_time)
        ):
            update_data = True
            self.last_db_changed_time = last_db_changed_time

        async with timeout(60):
            if force or (update_data and not is_update_paused):
                await self.update_refreshing_status("ON")
                titles = [
                    "products",
                    "shopping_list",
                    "locations",
                    "product_groups",
                ]
                data = await gather(*[self.fetch_list(path) for path in titles])
                self.final_data = {
                    title: products for title, products in zip(titles, data)
                }
                await self.parse_products(self.final_data)
                await self.update_refreshing_status("OFF")
                return self.final_data
            else:
                return self.final_data
