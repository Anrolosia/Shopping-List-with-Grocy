import logging
from datetime import timedelta

from homeassistant.const import CONF_NAME
from homeassistant.helpers import entity_platform
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


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

    coordinator = hass.data[DOMAIN][config_entry.entry_id]

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

    LOGGER.info(
        "Adding the following sensors: %s",
        [sensor._attr_unique_id for sensor in sensors],
    )
    async_add_entities(sensors, True)

    platform = entity_platform.async_get_current_platform()
    LOGGER.info("Platform registered: %s", platform.domain)


class GrocyShoppingListSensor(CoordinatorEntity):
    """Representation of a Grocy sensor."""

    def __init__(self, coordinator, sensor_type, name, config):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{sensor_type}"
        self.sensor_type = sensor_type
        self.config = config

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def data(self):
        """Return the data associated with the sensor."""
        return self.coordinator.data.get(self.sensor_type, [])

    @property
    def state(self):
        """Return the state of the sensor."""
        return len(self.data)

    @property
    def icon(self):
        """Return an icon for the sensor."""
        return (
            "mdi:cart" if self.sensor_type == "shopping_list" else "mdi:package-variant"
        )

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        return {}

    async def async_update(self):
        """Ensure data is updated from coordinator."""
        await self.coordinator.async_request_refresh()
