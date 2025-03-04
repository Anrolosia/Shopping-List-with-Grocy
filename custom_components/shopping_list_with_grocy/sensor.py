import asyncio
import logging
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

    LOGGER.info("Setting up sensors for Shopping List with Grocy")

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

    sensors = [
        GrocyShoppingListSensor(
            coordinator, "shopping_list", "Shopping List Items", config_data
        ),
        GrocyShoppingListSensor(coordinator, "products", "Product Items", config_data),
    ]

    for sensor in sensors:
        coordinator.entities.append(sensor)

    async_add_entities(sensors, True)

    async def async_add_or_update_dynamic_sensor(product):
        entity_id = f"sensor.{DOMAIN}_product_v{ENTITY_VERSION}_{product['product_id']}"
        entity_registry = async_get(hass)

        existing_sensor = hass.states.get(entity_id)

        if existing_sensor:
            existing_attributes = existing_sensor.attributes.copy()
            attributes_to_remove = product.get("attributes_to_remove", [])

            for key in attributes_to_remove:
                if key in existing_attributes:
                    existing_attributes.pop(key, None)

            updated_attributes = {**existing_attributes}

            for key, value in product["attributes"].items():
                if key not in attributes_to_remove:
                    updated_attributes[key] = value

            hass.states.async_set(
                entity_id,
                product["qty_in_shopping_lists"],
                attributes=updated_attributes,
            )
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

    for product in coordinator._parsed_data:
        await async_add_or_update_dynamic_sensor(product)


class DynamicProductSensor(CoordinatorEntity, SensorEntity):

    def __init__(self, coordinator, product):
        super().__init__(coordinator)
        unique_id = (
            f"{DOMAIN}_product_v{ENTITY_VERSION}_{product.get('product_id', 'unknown')}"
        )
        entity_id = f"sensor.{unique_id}"
        self._attr_name = product.get("name", "Unknown Product")
        self.entity_id = entity_id
        self._attr_unique_id = unique_id
        if coordinator.config_entry and coordinator.config_entry.entry_id:
            self._attr_config_entry_id = coordinator.config_entry.entry_id
        else:
            self._attr_config_entry_id = None
        self._state = product.get("qty_in_shopping_lists", 0)
        self._attr_extra_state_attributes = product.get("attributes", {})

    @property
    def state(self):
        return self._state

    async def async_update(self):
        if isinstance(self.coordinator._parsed_data, dict):
            products = self.coordinator._parsed_data.values()
        elif isinstance(self.coordinator._parsed_data, list):
            products = self.coordinator._parsed_data
        else:
            products = []

        product = next(
            (
                p
                for p in products
                if p.get("product_id") == self._attr_unique_id.split("_")[-1]
            ),
            None,
        )

        if product:
            self._state = product.get("qty_in_shopping_lists", 0)
            self._attr_extra_state_attributes.update(product.get("attributes", {}))

            self.async_write_ha_state()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def force_update(self):
        await self.coordinator.async_request_refresh()

    @property
    def icon(self):
        return "mdi:cart"


class GrocyShoppingListSensor(CoordinatorEntity):

    def __init__(self, coordinator, sensor_type, name, config):
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{sensor_type}"
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
