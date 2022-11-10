"""The Trakt integration."""
import logging
from datetime import timedelta

from async_timeout import timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_NAME,
    CONF_NAME,
    EVENT_HOMEASSISTANT_STARTED,
)
from homeassistant.core import CoreState, HomeAssistant, asyncio, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .apis.shopping_list_with_grocy import ShoppingListWithGrocyApi
from .const import DOMAIN, STATE_INIT
from .schema import configuration_schema
from .services import async_setup_services, async_unload_services
from .utils import update_domain_data

LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = configuration_schema
PLATFORMS = ["sensor"]

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=120)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Shopping List with Grocy component from a yaml (not supported)."""
    update_domain_data(hass, "configuration", CONFIG_SCHEMA(config).get(DOMAIN, {}))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    config = entry.data
    api = ShoppingListWithGrocyApi(async_get_clientsession(hass), hass, config)
    session = async_get_clientsession(hass)
    coordinator = ShoppingListWithGrocyCoordinator(hass, session, entry, api)

    name = config.get(CONF_NAME)

    configuration = {}
    update_domain_data(hass, "configuration", configuration)

    await coordinator.async_config_entry_first_refresh()

    instances = {"coordinator": coordinator, "api": api}
    update_domain_data(hass, "instances", instances)

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    for platform in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, platform)
        )

    async_setup_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )

    if unload_ok:
        hass.data.pop(DOMAIN)
        if not hass.data[DOMAIN]:
            async_unload_services(hass)

    return unload_ok


class ShoppingListWithGrocyCoordinator(DataUpdateCoordinator):
    """Define an object to hold shopping list with grocy data."""

    def __init__(self, hass, session, entry, api):
        """Initialize."""
        self.hass = hass
        self.state = STATE_INIT
        self.config = entry.data
        self.name = self.config.get(CONF_NAME)
        self.api = api
        self._shopping_list_with_grocy_tracker = None

        super().__init__(
            hass, LOGGER, name=self.name, update_interval=timedelta(seconds=120)
        )
        # super().__init__(hass, LOGGER, name=self.name, update_method=api.retrieve_data)

        # wait for 10 seconds after HA startup to allow entities to be initialized
        @callback
        def handle_startup(_event):
            hass.async_create_task(self.async_init_shopping_list_with_grocy_sensor())

            @callback
            def async_timer_finished(_now):
                self.state = const.STATE_READY
                async_dispatcher_send(self.hass, const.EVENT_STARTED)

            async_call_later(hass, 10, async_timer_finished)

        if hass.state == CoreState.running:
            handle_startup(None)
        else:
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, handle_startup)

    async def _async_update_data(self):
        async with timeout(60):
            return await self.api.retrieve_data()

    async def async_init_shopping_list_with_grocy_sensor(self):
        """watch for changes in the shopping list with grocy sensor"""

        shopping_list_with_grocy_entity = self.hass.states.get(
            "sensor.products_shopping_list_with_grocy"
        )
        if not shopping_list_with_grocy_entity:
            return None

        @callback
        async def async_shopping_list_with_grocy_state_updated(
            entity, old_state, new_state
        ):
            """the shopping list with grocy sensor has been updated"""
            async_dispatcher_send(self.hass, "shopping_list_with_grocy_sensor_updated")

        self._shopping_list_with_grocy_tracker = async_track_state_change(
            self.hass,
            "sensor.products_shopping_list_with_grocy",
            async_shopping_list_with_grocy_state_updated,
        )

    async def request_update(self):
        async with timeout(60):
            return await self.api.retrieve_data(True)

    async def add_product(self, product_id, note):
        await self.api.manage_product(product_id, note)

    async def remove_product(self, product_id):
        await self.api.manage_product(product_id, "", True)

    async def update_note(self, product_id, note):
        await self.api.update_note(product_id, note)
