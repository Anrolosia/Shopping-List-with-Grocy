"""Platform for sensor integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.const import CONF_NAME
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform, service
from homeassistant.helpers.entity import Entity

from .const import DOMAIN

LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the sensor platform."""
    config = config_entry.options
    if config is None or len(config) == 0:
        config = config_entry.data
    coordinator = hass.data[DOMAIN]["instances"]["coordinator"]

    sensors = []

    sensor = ShoppingListSensor(
        hass=hass,
        config_entry=config_entry,
        coordinator=coordinator,
        source="products",
        prefix="Products",
        mdi_icon="mdi:cart",
    )

    sensors.append(sensor)

    sensor = ShoppingListSensor(
        hass=hass,
        config_entry=config_entry,
        coordinator=coordinator,
        source="shopping_list",
        prefix="Shopping list",
        mdi_icon="mdi:cart-check",
    )

    sensors.append(sensor)

    async_add_entities(sensors)

    platform = entity_platform.async_get_current_platform()


class ShoppingListSensor(Entity):
    """Representation of a shopping list with grocy sensor."""

    def __init__(
        self,
        hass,
        config_entry,
        coordinator,
        source: str,
        prefix: str,
        mdi_icon: str,
    ):
        """Initialize the sensor."""
        self.hass = hass
        if config_entry.options is None or len(config_entry.options) == 0:
            self.config = config_entry.data
        else:
            self.config = config_entry.options
        self.coordinator = coordinator
        self.source = source
        self.prefix = prefix
        self.mdi_icon = mdi_icon

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self.prefix} Shopping List with Grocy"

    @property
    def data(self):
        if self.coordinator.data:
            return self.coordinator.data.get(self.source, {})
        return []

    @property
    def state(self):
        """Return the state of the sensor."""
        return max([len(self.data), 0])

    @property
    def icon(self):
        """Return the unit of measurement."""
        return self.mdi_icon

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the sensor."""
        return (
            {"data": self.data}
            if self.config.get("adding_products_in_sensor", False)
            else []
        )

    async def async_update(self):
        """Request coordinator to update data."""
        await self.coordinator.async_request_refresh()
