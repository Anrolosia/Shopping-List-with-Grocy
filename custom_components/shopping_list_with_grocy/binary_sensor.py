"""Binary sensor platform for Shopping List with Grocy."""

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import DOMAIN

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    binary_sensor = ShoppingListWithGrocyBinarySensor(
        coordinator,
        "updating_shopping_list_with_grocy",
        "ShoppingListWithGrocy Update in progress",
    )

    hass.data[DOMAIN]["entities"]["updating_shopping_list_with_grocy"] = binary_sensor

    async_add_entities([binary_sensor])


class ShoppingListWithGrocyBinarySensor(BinarySensorEntity):
    def __init__(self, coordinator, object_id, name):
        unique_id = "updating_shopping_list_with_grocy"
        entity_id = f"binary_sensor.{unique_id}"
        self.coordinator = coordinator
        self._attr_name = name
        self.entity_id = entity_id
        self._attr_unique_id = unique_id
        self._attr_icon = "mdi:refresh"
        self._attr_is_on = False

    @property
    def is_on(self):
        return self._attr_is_on

    async def update_state(self, state: bool) -> None:
        """Update the sensor state via the proper HA mechanism."""
        self._attr_is_on = state
        # Use async_write_ha_state instead of hass.states.async_set to go
        # through the entity registry properly and avoid state inconsistencies.
        if self.hass:
            self.async_write_ha_state()
