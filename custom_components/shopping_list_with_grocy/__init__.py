import logging
import uuid
from datetime import timedelta

from async_timeout import timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_NAME,
    CONF_NAME,
    EVENT_HOMEASSISTANT_STARTED,
    Platform,
)
from homeassistant.core import CoreState, HomeAssistant, asyncio, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .apis.shopping_list_with_grocy import ShoppingListWithGrocyApi
from .const import DOMAIN, STATE_INIT
from .coordinator import ShoppingListWithGrocyCoordinator
from .schema import configuration_schema
from .services import async_setup_services, async_unload_services
from .utils import update_domain_data

LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = configuration_schema
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.TODO]

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=30)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Shopping List with Grocy component from a yaml (not supported)."""
    update_domain_data(hass, "configuration", CONFIG_SCHEMA(config).get(DOMAIN, {}))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    config = entry.options
    if config is None or len(config) == 0:
        config = entry.data
    verify_ssl = config.get("verify_ssl")
    if verify_ssl is None:
        verify_ssl = True
    api = ShoppingListWithGrocyApi(
        async_get_clientsession(hass, verify_ssl=verify_ssl), hass, config
    )
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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async_setup_services(hass)

    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    LOGGER.debug("Migrating from version %s", config_entry.version)

    #
    # To v2
    #

    if config_entry.version == 1:
        unique_id = str(uuid.uuid4())

        v2_options: ConfigEntry = {**config_entry.options}
        if v2_options is not None and len(v2_options) < 0:
            v2_options["unique_id"] = unique_id

        v2_data: ConfigEntry = {**config_entry.data}
        v2_data["unique_id"] = unique_id

        config_entry.version = 2

        hass.config_entries.async_update_entry(
            config_entry, data=v2_data, options=v2_options
        )

    #
    # To v3
    #

    if config_entry.version == 2:
        v2_options: ConfigEntry = {**config_entry.options}
        if v2_options is not None and len(v2_options) < 0:
            v2_options["adding_images"] = True

        v2_data: ConfigEntry = {**config_entry.data}
        v2_data["adding_images"] = True

        config_entry.version = 3

        hass.config_entries.async_update_entry(
            config_entry, data=v2_data, options=v2_options
        )

    #
    # To v4
    #

    if config_entry.version == 3:
        v2_options: ConfigEntry = {**config_entry.options}
        if v2_options is not None and len(v2_options) < 0:
            if v2_options["adding_images"]:
                v2_options["image_download_size"] = 100
            else:
                v2_options["image_download_size"] = 0
            v2_options.pop("adding_images")

        v2_data: ConfigEntry = {**config_entry.data}
        if v2_data["adding_images"]:
            v2_data["image_download_size"] = 100
        else:
            v2_data["image_download_size"] = 0
        v2_data.pop("adding_images")

        config_entry.version = 4

        hass.config_entries.async_update_entry(
            config_entry, data=v2_data, options=v2_options
        )

    LOGGER.info("Migration to version %s successful", config_entry.version)

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
