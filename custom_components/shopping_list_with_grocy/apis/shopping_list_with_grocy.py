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

from ..const import DOMAIN, MQTT_ENTITY_VERSION, OTHER_FIELDS

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
        self.mqtt_custom_port = config.get("mqtt_custom_port", 0)
        if self.mqtt_port == 1 and self.mqtt_custom_port > 0:
            self.mqtt_port = self.mqtt_custom_port
        self.mqtt_username = config.get("mqtt_username", None)
        self.mqtt_password = config.get("mqtt_password", None)
        self.image_size = config.get("image_download_size", 0)
        self.ha_products = []
        self.final_data = []
        self.config_topic = "homeassistant/sensor/"
        self.state_topic = "shopping-list-with-grocy/products/"
        self.current_time = datetime.now(timezone.utc)
        self.client = mqtt.Client("ha-client")
        if self.mqtt_username is not None and self.mqtt_password is not None:
            self.client.username_pw_set(self.mqtt_username, self.mqtt_password)
        self.last_db_changed_time = None
        self.pagination_limit = 40

    def get_entity_in_hass(self, entity_id):
        return self.hass.states.get(entity_id)

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

    def serialize_datetime(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError("Type not serializable")

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

    async def fetch_products(self, path: str, offset: int):
        return await self.request(
            "get",
            f"api/objects/{path}?limit="
            + str(self.pagination_limit)
            + "&offset="
            + str(offset)
            + ("&order=name%3Aasc" if path == "products" else ""),
            "application/json",
        )

    async def fetch_image(self, image_name: str):
        return await self.request(
            "get",
            f"api/files/productpictures/{image_name}?force_serve_as=picture&best_fit_width={self.image_size}",
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
        pages = {}
        data = []
        offset = 0
        new_results = True
        pages[path] = 0
        if path == "stock":
            response = await self.request(
                "get",
                f"api/{path}",
                "application/json",
            )
            new_results = await response.json()
            data.extend(new_results)
        else:
            while new_results:
                response = await self.fetch_products(
                    path, self.pagination_limit * pages[path]
                )
                new_results = await response.json()
                data.extend(new_results)
                pages[path] += 1

        return data

    async def remove_product(self, product):
        if product.endswith("))"):
            product = product[:-2]

        entity_id = product.replace("sensor.", "")
        LOGGER.debug("product %s not found on Grocy, deleting it...", entity_id)
        config_topic = self.config_topic + entity_id + "/config"
        state_topic = self.state_topic + entity_id + "/state"
        attributes_topic = self.state_topic + entity_id + "/attributes"
        self.client.connect(self.mqtt_server, self.mqtt_port)
        self.client.loop_start()
        self.update_object_in_mqtt(
            config_topic,
            "",
        )
        self.update_object_in_mqtt(
            state_topic,
            "",
        )
        self.update_object_in_mqtt(
            attributes_topic,
            "",
        )
        self.client.loop_stop()
        self.client.disconnect()

    async def parse_products(self, data):
        self.current_time = datetime.now(timezone.utc)

        entities = self.hass.states.async_entity_ids()
        rex = re.compile("sensor.shopping_list_with_grocy_[^|]+")
        self.ha_products = rex.findall(r"(?=(" + "|".join(entities) + r"))")

        self.client.connect(self.mqtt_server, self.mqtt_port)
        self.client.loop_start()
        for product in data["products"]:
            shopping_lists = {}
            userfields = {}
            otherfields = {}
            if "userfields" in product:
                userfields = product["userfields"]
            qty_in_shopping_lists = 0
            qty_in_stock = "0"
            aggregated_stock = "0"
            picture = ""
            location = ""
            consume_location = ""
            group = ""
            product_name = product["name"]
            product_id = product["id"]
            parent_product_id = product["parent_product_id"]
            product_picture = product["picture_file_name"]
            product_location = product["location_id"]
            default_consume_location = product["default_consume_location_id"]
            product_group = product["product_group_id"]
            qty_factor = 1.0
            if "qu_factor_purchase_to_stock" in product and (
                product["qu_id_purchase"] != product["qu_id_stock"]
            ):
                qty_factor = float(product["qu_factor_purchase_to_stock"])
            object_id = (
                "shopping_list_with_grocy_product_v"
                + str(MQTT_ENTITY_VERSION)
                + "_"
                + str(product_id)
            )

            qty_unit_purchase = ""
            qty_unit_stock = ""
            for quantity_unit in data["quantity_units"]:
                if product["qu_id_purchase"] == quantity_unit["id"]:
                    qty_unit_purchase = quantity_unit["name"]
                if product["qu_id_stock"] == quantity_unit["id"]:
                    qty_unit_stock = quantity_unit["name"]

            config_topic = self.config_topic + object_id + "/config"
            state_topic = self.state_topic + object_id + "/state"
            attributes_topic = self.state_topic + object_id + "/attributes"

            entity = "sensor." + object_id
            if entity in self.ha_products:
                self.ha_products.remove(entity)

            if (
                self.image_size > 0
                and product_picture is not None
                and product_picture != "null"
            ):
                picture_response = await self.fetch_image(
                    self.encode_base64(product_picture)
                )
                picture_bytes = await picture_response.read()
                picture = base64.b64encode(picture_bytes).decode("utf-8")

            for in_shopping_list in data["shopping_list"]:
                if product_id == in_shopping_list["product_id"]:
                    shop_list_id = in_shopping_list["id"]
                    shopping_list_id = in_shopping_list["shopping_list_id"]
                    in_shop_list = in_shopping_list["amount"]
                    in_shop_list = str(round(int(in_shop_list) / qty_factor))
                    note = (
                        in_shopping_list["note"]
                        if (
                            in_shopping_list["note"] is not None
                            and in_shopping_list["note"] != "null"
                        )
                        else ""
                    )
                    shopping_lists["list_" + str(shopping_list_id)] = {
                        "shop_list_id": shop_list_id,
                        "qty": int(in_shop_list),
                        "note": note,
                    }
                    qty_in_shopping_lists += int(in_shop_list)

            stock_qty = 0
            aggregated_qty = 0
            opened_qty = 0
            opened_aggregated_qty = 0
            unopened_qty = 0
            unopened_aggregated_qty = 0
            for in_stock in data["stock"]:
                if (
                    product_id == in_stock["product_id"]
                    and "amount_aggregated" in in_stock
                ):
                    stock_qty += int(in_stock["amount"])
                    aggregated_qty += float(in_stock["amount_aggregated"])
                if (
                    product_id == in_stock["product_id"]
                    and "amount_opened_aggregated" in in_stock
                ):
                    opened_qty += int(in_stock["amount_opened"])
                    opened_aggregated_qty += float(in_stock["amount_opened_aggregated"])
            qty_in_stock = str(stock_qty)
            aggregated_stock = str(aggregated_qty)
            unopened_qty = stock_qty - opened_qty
            if unopened_qty < 0:
                unopened_qty = 0
            unopened_aggregated_qty = aggregated_qty - opened_aggregated_qty
            if unopened_aggregated_qty < 0:
                unopened_aggregated_qty = 0

            if product_location is not None and product_location != "null":
                for locations in data["locations"]:
                    if product_location == locations["id"]:
                        location = locations["name"]
            if (
                default_consume_location is not None
                and default_consume_location != "null"
            ):
                for locations in data["locations"]:
                    if default_consume_location == locations["id"]:
                        consume_location = locations["name"]

            if product_group is not None and product_group != "null":
                for groups in data["product_groups"]:
                    if product_group == groups["id"]:
                        group = groups["name"]

            entity = self.get_entity_in_hass("sensor." + object_id)

            if entity is None or entity.last_updated <= self.current_time:
                prod_dict = {
                    "product_id": product_id,
                    "parent_product_id": parent_product_id,
                    "qty_in_stock": qty_in_stock,
                    "qty_opened": opened_qty,
                    "qty_unopened": unopened_qty,
                    "qty_unit_purchase": qty_unit_purchase,
                    "qty_unit_stock": qty_unit_stock,
                    "aggregated_stock": aggregated_stock,
                    "aggregated_opened": opened_aggregated_qty,
                    "aggregated_unopened": unopened_aggregated_qty,
                    "qu_factor_purchase_to_stock": str(qty_factor),
                    "product_image": picture,
                    "topic": state_topic,
                    "location": location,
                    "consume_location": consume_location,
                    "group": group,
                    "userfields": userfields,
                }
                for shop_list in shopping_lists:
                    prod_dict.update(
                        {
                            shop_list + "_qty": shopping_lists[shop_list].get("qty"),
                            shop_list
                            + "_shop_list_id": shopping_lists[shop_list].get(
                                "shop_list_id"
                            ),
                            shop_list + "_note": shopping_lists[shop_list].get("note"),
                        }
                    )
                for field in OTHER_FIELDS:
                    if field in product:
                        prod_dict.update({field: product[field]})

                prod_dict.update({"list_count": len(shopping_lists)})
                self.update_object_in_mqtt(
                    state_topic,
                    qty_in_shopping_lists,
                )
                self.update_object_in_mqtt(
                    attributes_topic,
                    json.dumps(prod_dict),
                )

            if entity is None:
                LOGGER.debug(
                    "Product %s (%s) not found, creating it...",
                    product_name,
                    "sensor." + object_id,
                )
                prod_dict_config = {
                    "name": product_name,
                    "json_attributes_topic": attributes_topic,
                    "json_attributes_template": "{{ value_json | tojson }}",
                    "state_topic": state_topic,
                    "icon": "mdi:cart",
                    "unique_id": object_id,
                    "object_id": object_id,
                }
                self.update_object_in_mqtt(
                    config_topic,
                    json.dumps(prod_dict_config),
                )

        self.client.loop_stop()
        self.client.disconnect()

        if len(self.ha_products) > 0:
            for product in self.ha_products:
                await self.remove_product(product)

    async def update_grocy_product(
        self,
        product_id,
        qu_factor_purchase_to_stock,
        shopping_list_id,
        product_note,
        remove_product=False,
    ):
        endpoint = "remove-product" if remove_product else "add-product"
        payload = {
            "product_id": int(product_id),
            "list_id": shopping_list_id,
            "product_amount": round(float(qu_factor_purchase_to_stock)),
            "note": product_note,
        }
        if remove_product:
            payload = {
                "product_id": int(product_id),
                "list_id": shopping_list_id,
                "product_amount": round(float(qu_factor_purchase_to_stock)),
            }

        return await self.request(
            "post",
            f"api/stock/shoppinglist/{endpoint}",
            "*/*",
            json.dumps(payload),
        )

    async def manage_product(
        self, product_id, shopping_list_id=1, note="", remove_product=False
    ):
        LOGGER.debug("manage_product, product_id: %s", product_id)
        entity = self.get_entity_in_hass(product_id)
        if entity is not None:
            total_qty = int(entity.state) + 1
            qty = 1
            list_count = entity.attributes.get("list_count") + 1
            if (
                entity.attributes.get("list_" + str(shopping_list_id) + "_qty")
                is not None
            ):
                qty = (
                    int(entity.attributes.get("list_" + str(shopping_list_id) + "_qty"))
                    + 1
                )
                list_count -= 1
            if remove_product:
                total_qty = int(entity.state) - 1
                qty = (
                    int(entity.attributes.get("list_" + str(shopping_list_id) + "_qty"))
                    - 1
                )
            await self.update_grocy_product(
                entity.attributes.get("product_id"),
                entity.attributes.get("qu_factor_purchase_to_stock"),
                str(shopping_list_id),
                note,
                remove_product,
            )
            entity_attributes = entity.attributes.copy()
            if qty > 0:
                entity_attributes.update(
                    {
                        "qty_in_shopping_lists": total_qty,
                        "list_" + str(shopping_list_id) + "_qty": qty,
                        "list_" + str(shopping_list_id) + "_note": note,
                        "list_count": list_count,
                    }
                )
            else:
                entity_attributes.pop("list_" + str(shopping_list_id) + "_qty")
                entity_attributes.pop("list_" + str(shopping_list_id) + "_note")
                entity_attributes.pop("list_" + str(shopping_list_id) + "_shop_list_id")
                entity_attributes.update(
                    {
                        "qty_in_shopping_lists": total_qty,
                        "list_count": entity.attributes.get("list_count") - 1,
                    }
                )
            self.client.connect(self.mqtt_server, self.mqtt_port)
            self.client.loop_start()
            self.update_object_in_mqtt(
                entity_attributes.get("topic").replace("state", "attributes"),
                json.dumps(entity_attributes),
            )
            self.update_object_in_mqtt(
                entity_attributes.get("topic"),
                total_qty,
            )
            self.client.loop_stop()
            self.client.disconnect()

    async def update_note(self, product_id, shopping_list_id, note):
        LOGGER.debug("update_note, product_id: %s", product_id)
        entity = self.get_entity_in_hass(product_id)
        if entity is not None:
            payload = {
                "product_id": entity.attributes.get("product_id"),
                "shopping_list_id": shopping_list_id,
                "amount": entity.attributes.get(
                    "list_" + str(shopping_list_id) + "_qty"
                ),
                "note": note,
            }

            await self.request(
                "put",
                f"api/objects/shopping_list/{entity.attributes.get('list_' + str(shopping_list_id) + '_shop_list_id')}",
                "*/*",
                json.dumps(payload),
            )
            entity_attributes = entity.attributes.copy()
            entity_attributes.update({"list_" + str(shopping_list_id) + "_note": note})
            self.client.connect(self.mqtt_server, self.mqtt_port)
            self.client.loop_start()
            self.update_object_in_mqtt(
                entity_attributes.get("topic").replace("state", "attributes"),
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
                    "stock",
                    "product_groups",
                    "quantity_units",
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
