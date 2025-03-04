from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    switch = ShoppingListWithGrocySwitch(
        coordinator,
        "pause_update_shopping_list_with_grocy",
        "ShoppingListWithGrocy Pause update",
    )

    hass.data[DOMAIN]["entities"]["pause_update_shopping_list_with_grocy"] = switch

    async_add_entities([switch])


class ShoppingListWithGrocySwitch(SwitchEntity):

    def __init__(self, coordinator, object_id, name):
        unique_id = "pause_update_shopping_list_with_grocy"
        entity_id = f"switch.{unique_id}"
        self.coordinator = coordinator
        self._attr_name = name
        self.entity_id = entity_id
        self._attr_unique_id = unique_id
        self._attr_icon = "mdi:pause-octagon"
        self._state = False

    async def async_turn_on(self):
        self._state = True
        self.schedule_update_ha_state()

    async def async_turn_off(self):
        self._state = False
        self.schedule_update_ha_state()

    @property
    def is_on(self):
        return self._state
