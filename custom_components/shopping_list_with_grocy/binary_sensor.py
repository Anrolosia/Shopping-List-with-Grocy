from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import DOMAIN


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

    async def update_state(self, state):
        self._attr_is_on = state
        self.hass.states.async_set(self.entity_id, "on" if state else "off")

        if not self.hass:
            return

        self.async_schedule_update_ha_state()
