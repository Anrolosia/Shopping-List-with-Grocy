import asyncio
import copy
import logging
import re
from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENTITY_VERSION

LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the sensor platform."""

    entity_registry = async_get(hass)

    old_entity_id = "sensor.product_items"
    if entity_registry.async_is_registered(old_entity_id):
        entity_registry.async_remove(old_entity_id)
        hass.states.async_remove(old_entity_id)

    if hass.states.get(old_entity_id):
        LOGGER.warning(
            "Failed to remove %s from Home Assistant states. Retrying...", old_entity_id
        )
        hass.states.async_remove(old_entity_id)

    if DOMAIN not in hass.data:
        LOGGER.error(
            "Domain %s not found in hass.data! Available keys: %s",
            DOMAIN,
            list(hass.data.keys()),
        )
        return

    if config_entry.entry_id not in hass.data[DOMAIN]:
        LOGGER.error(
            "Entry ID %s not found in hass.data[%s]! Available keys: %s",
            config_entry.entry_id,
            DOMAIN,
            list(hass.data[DOMAIN].keys()),
        )
        return

    if "entities" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["entities"] = {}

    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    if not coordinator:
        LOGGER.error("No coordinator found in hass.data[DOMAIN]. Todo setup aborted.")
        return

    if config_entry.options is None or len(config_entry.options) == 0:
        config_data = config_entry.data
    else:
        config_data = config_entry.options

    existing_entities = []
    for state in hass.states.async_all():
        if state.entity_id.startswith(
            f"sensor.shopping_list_with_grocy_product_v{ENTITY_VERSION}_"
        ):
            product_id = state.entity_id.split("_")[-1]
            existing_sensor = DynamicProductSensor(
                coordinator,
                {
                    "product_id": product_id,
                    "name": state.name,
                    "qty_in_shopping_lists": state.state,
                },
            )
            existing_entities.append(existing_sensor)

    sensors = [
        GrocyShoppingListSensor(
            coordinator, "shopping_list", "Shopping List Items", config_data
        ),
        GrocyShoppingListSensor(coordinator, "products", "Product Items", config_data),
    ]

    for sensor in sensors:
        coordinator.entities.append(sensor)

    for sensor in sensors:
        if not hasattr(sensor, "entity_id") or sensor.entity_id is None:
            sensor.entity_id = f"sensor.{sensor._attr_unique_id}"

    async_add_entities(existing_entities + sensors)
    for sensor in sensors:
        current_entity_id = sensor.entity_id
        expected_entity_id = f"sensor.{sensor._attr_unique_id}"

        if current_entity_id != expected_entity_id:
            LOGGER.warning(
                "Entity ID mismatch: Expected %s but got %s. Attempting correction...",
                expected_entity_id,
                current_entity_id,
            )

            sensor.entity_id = expected_entity_id
            sensor.async_write_ha_state()

    pattern = re.compile(r"list_\d+_.*")

    async def async_add_or_update_dynamic_sensor(product):
        product_id = product["product_id"]
        entity_id = f"sensor.{DOMAIN}_product_v{ENTITY_VERSION}_{product_id}"
        LOGGER.debug("Attempting to add/update sensor: %s", entity_id)

        existing_sensor = hass.states.get(entity_id)

        if existing_sensor:
            existing_state = str(existing_sensor.state)
            existing_attributes = existing_sensor.attributes.copy()

            attributes_to_remove = product.get("attributes_to_remove", [])
            for key in attributes_to_remove:
                if key in existing_attributes:
                    existing_attributes.pop(key, None)

            keys_in_product = {
                key for key in product["attributes"].keys() if pattern.match(key)
            }

            keys_in_existing = {
                key for key in existing_attributes.keys() if pattern.match(key)
            }

            keys_to_remove = keys_in_existing - keys_in_product

            for key in keys_to_remove:
                existing_attributes.pop(key, None)

            updated_attributes = {**existing_attributes}

            for key, value in product["attributes"].items():
                if key not in attributes_to_remove:
                    updated_attributes[key] = value

            new_state = str(product["qty_in_shopping_lists"])

            state_changed = new_state != existing_state
            attributes_changed = updated_attributes != existing_attributes

            if state_changed or attributes_changed:
                hass.states.async_set(
                    entity_id, new_state, attributes=updated_attributes
                )

                await asyncio.sleep(1)

                # Persist changes in coordinator to prevent rollback
                if product_id in coordinator._parsed_data:
                    coordinator._parsed_data[product_id] = copy.deepcopy(
                        product
                    )  # 🔥 This prevents unwanted overwrites
                    coordinator._parsed_data[product_id][
                        "qty_in_shopping_lists"
                    ] = new_state
                    coordinator._parsed_data[product_id][
                        "attributes"
                    ] = updated_attributes
        else:
            sensor = DynamicProductSensor(coordinator, product)
            async_add_entities([sensor])

    async def async_remove_grocy_sensor(product_id):
        entity_id = f"sensor.{DOMAIN}_product_v{ENTITY_VERSION}_{product_id}"

        entity_registry = async_get(hass)
        if entity_registry.async_is_registered(entity_id):
            entity_registry.async_remove(entity_id)

        hass.states.async_remove(entity_id)

        await asyncio.sleep(0.1)

    async_dispatcher_connect(
        hass, f"{DOMAIN}_add_or_update_sensor", async_add_or_update_dynamic_sensor
    )
    async_dispatcher_connect(hass, f"{DOMAIN}_remove_sensor", async_remove_grocy_sensor)

    for product in coordinator._parsed_data.values():
        await async_add_or_update_dynamic_sensor(product)


class DynamicProductSensor(CoordinatorEntity, SensorEntity):

    def __init__(self, coordinator, product):
        super().__init__(coordinator)
        product_id = product.get("product_id", "unknown")
        unique_id = f"{DOMAIN}_product_v{ENTITY_VERSION}_{product_id}"
        entity_id = f"sensor.{unique_id}"

        self._product_id = str(product_id)
        self._attr_name = product.get("name", "Unknown Product")
        self.entity_id = entity_id
        self._attr_unique_id = unique_id

        if coordinator.config_entry and coordinator.config_entry.entry_id:
            self._attr_config_entry_id = coordinator.config_entry.entry_id
        else:
            self._attr_config_entry_id = None

    @property
    def state(self):
        product = self.coordinator._parsed_data.get(self._product_id)
        if product:
            qty = product.get("qty_in_shopping_lists", 0)
            return qty
        return None

    @property
    def extra_state_attributes(self):
        product = self.coordinator._parsed_data.get(self._product_id)
        if product:
            return product.get("attributes", {})
        return {}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()

        if self.entity_id not in self.coordinator.entities:
            self.coordinator.entities.append(self)

        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    @property
    def icon(self):
        return "mdi:cart"


class GrocyShoppingListSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, sensor_type, name, config):
        super().__init__(coordinator)
        unique_id = f"{DOMAIN}_{sensor_type}"
        entity_id = f"sensor.{unique_id}"
        self._attr_name = name
        self.entity_id = entity_id
        self._attr_unique_id = unique_id
        self.sensor_type = sensor_type
        self.config = config

    @property
    def name(self):
        return self._attr_name

    @property
    def data(self):
        if not self.coordinator.data:
            return []
        return self.coordinator.data.get(self.sensor_type, [])

    @property
    def state(self):
        return len(self.data)

    @property
    def icon(self):
        return (
            "mdi:cart" if self.sensor_type == "shopping_list" else "mdi:package-variant"
        )

    @property
    def extra_state_attributes(self):
        return {}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()

        entity_registry = async_get(self.hass)
        registry_entry = entity_registry.async_get(self.entity_id)

        if (
            registry_entry
            and registry_entry.entity_id != f"sensor.{self._attr_unique_id}"
        ):
            LOGGER.warning(
                "⚠️ Entity ID mismatch: Expected %s but got %s. Correcting...",
                f"sensor.{self._attr_unique_id}",
                registry_entry.entity_id,
            )
            entity_registry.async_update_entity(
                registry_entry.entity_id, new_entity_id=f"sensor.{self._attr_unique_id}"
            )
