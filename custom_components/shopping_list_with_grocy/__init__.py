import asyncio
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_NAME,
    CONF_NAME,
    EVENT_HOMEASSISTANT_STARTED,
    Platform,
)
from homeassistant.core import CoreState, HomeAssistant, asyncio, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
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
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.TODO,
]

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=60)

mqtt_lock = asyncio.Lock()


async def async_setup(hass: HomeAssistant, config: dict):
    update_domain_data(hass, "configuration", CONFIG_SCHEMA(config).get(DOMAIN, {}))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    LOGGER.info("🔄 Initializing Shopping List with Grocy")

    migration_success = True
    if entry.version < 7:
        LOGGER.debug("🔄 Running migration...")
        migration_success = await async_migrate_entry(hass, entry)
        if not migration_success:
            LOGGER.error("❌ Migration failed. Initialization stopped.")
            return False
    else:
        LOGGER.debug("✔️ Migration already up to date.")

    if not migration_success:
        LOGGER.error("❌ Migration failed. Initialization stopped.")
        return False

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("instances", {})
    hass.data[DOMAIN].setdefault("entities", {})
    hass.data[DOMAIN].setdefault("ha_started_handled", False)

    config = entry.options or entry.data
    verify_ssl = config.get("verify_ssl", True)

    api = ShoppingListWithGrocyApi(
        async_get_clientsession(hass, verify_ssl=verify_ssl), hass, config
    )
    session = async_get_clientsession(hass)
    coordinator = ShoppingListWithGrocyCoordinator(hass, session, entry, api)

    hass.data[DOMAIN]["instances"]["coordinator"] = coordinator
    hass.data[DOMAIN]["instances"]["session"] = session
    hass.data[DOMAIN]["instances"]["api"] = api
    hass.data[DOMAIN]["todo_initialized"] = False
    hass.data[DOMAIN][entry.entry_id] = coordinator
    hass.data[DOMAIN]["shopping_lists"] = []

    deleted = await remove_restored_entities(hass)

    if deleted:
        await asyncio.sleep(3)

    await coordinator.async_config_entry_first_refresh()

    if DOMAIN in hass.data and hass.data[DOMAIN]["todo_initialized"] == True:
        LOGGER.info("⚠️ TODO setup already initialized, skipping duplicate setup.")
    else:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async_setup_services(hass)

    return True


async def remove_old_entities_and_init(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: ShoppingListWithGrocyCoordinator,
):
    deleted = await remove_restored_entities(hass)

    if deleted:
        await asyncio.sleep(3)

    if entry.state == ConfigEntryState.SETUP_IN_PROGRESS:
        await coordinator.async_config_entry_first_refresh()
        LOGGER.info("✅ Coordinator first refresh done")
    else:
        await coordinator.async_refresh()

    if DOMAIN in hass.data and "todo_setup_done" in hass.data[DOMAIN]:
        LOGGER.info("⚠️ TODO setup already initialized, skipping duplicate setup.")
    else:
        hass.data[DOMAIN]["todo_setup_done"] = True
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_setup_services(hass)


async def remove_restored_entities(hass: HomeAssistant):
    entity_registry = async_get_entity_registry(hass)

    entities = set(hass.states.async_entity_ids())

    rex = re.compile(
        r"^sensor\.shopping_list_with_grocy_product_v1_.+|switch\.shoppinglistwithgrocy_pause_update|binary_sensor\.shoppinglistwithgrocy_update_in_progress$"
    )

    entities_to_remove = {
        entity_id
        for entity_id in entities
        if rex.match(entity_id)
        and hass.states.get(entity_id)
        and hass.states.get(entity_id).attributes.get("restored", False)
    }

    if entities_to_remove:
        LOGGER.info("🗑️ Removed old Home Assistant and MQTT entities")
        LOGGER.info("🗑️ Deleting %d restored entities", len(entities_to_remove))

        for entity_id in entities_to_remove:
            entity_entry = entity_registry.async_get(entity_id)
            if entity_entry:
                LOGGER.info("🗑️ Permanent deletion of the entity: %s", entity_id)
                entity_registry.async_remove(entity_id)
            else:
                LOGGER.warning(
                    "⚠️ Unable to delete %s, entity does not exist in registry",
                    entity_id,
                )
        LOGGER.info("✅ Deletion completed, coordinator launched")

        await asyncio.sleep(2)

        return True

    return False


async def remove_mqtt_topics(hass: HomeAssistant, config_entry: ConfigEntry):
    TOPIC_REGEX = re.compile(
        r"^homeassistant/switch/pause_update_shopping_list_with_grocy.*|homeassistant/binary_sensor/updating_shopping_list_with_grocy.*|homeassistant/sensor/shopping_list_with_grocy_product_v1_.*|homeassistant/sensor/shopping_list_with_grocy/shopping_list_with_grocy_product_v1_.*|shopping-list-with-grocy/.*$"
    )

    if config_entry.options is None or len(config_entry.options) == 0:
        config = config_entry.data
    else:
        config = config_entry.options
    client = mqtt.Client(client_id="ha-client", clean_session=True)
    mqtt_server = config.get("mqtt_server", "127.0.0.1")
    mqtt_port = config.get("mqtt_custom_port", config.get("mqtt_port", 1883))
    mqtt_username = config.get("mqtt_username") or None
    mqtt_password = config.get("mqtt_password") or None
    if mqtt_username and mqtt_password:
        client.username_pw_set(mqtt_username, mqtt_password)

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("✅ MQTT connection successful!")
            client.subscribe("homeassistant/sensor/#")
            client.subscribe("shopping-list-with-grocy/#")
            client.subscribe("homeassistant/switch/#")
            client.subscribe("homeassistant/binary_sensor/#")
        else:
            print(f"❌ MQTT connection failed with code {rc}")

    def on_message(client, userdata, msg):
        topic = msg.topic
        if TOPIC_REGEX.match(topic):
            matched_topics.add(topic)

    client.on_connect = on_connect
    client.on_message = on_message

    matched_topics = set()

    async def find_mqtt_topics(config_entry):
        client.connect(mqtt_server, mqtt_port)
        client.loop_start()

        await asyncio.sleep(5)

        client.loop_stop()
        client.disconnect()

        return matched_topics

    found_topics = await find_mqtt_topics(config_entry)
    if found_topics:
        session = mqtt_session(client, mqtt_server, mqtt_port)
        mqtt_lock = asyncio.Lock()
        if session is None:
            LOGGER.error(
                "❌ MQTT publish failed: MQTT session is None. Topic: %s", topic
            )
            return

        async with mqtt_lock:
            try:
                async with session:
                    await asyncio.gather(
                        *(remove_product(client, topic) for topic in found_topics)
                    )
            except Exception as e:
                LOGGER.error("⚠️ MQTT publish error: %s", str(e))


async def remove_product(client, topic):
    async with mqtt_lock:
        try:
            LOGGER.debug("✅ Deleting MQTT topic: %s", topic)
            client.publish(topic, None, qos=1, retain=True)
            await asyncio.sleep(0.2)
            LOGGER.debug(f"Deleted MQTT topic: {topic}")
        except Exception as e:
            LOGGER.error("⚠️ MQTT deletion error: %s", str(e))


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

        hass.config_entries.async_update_entry(
            config_entry, data=v2_data, options=v2_options, version=2
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

        hass.config_entries.async_update_entry(
            config_entry, data=v2_data, options=v2_options, version=3
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

        hass.config_entries.async_update_entry(
            config_entry, data=v2_data, options=v2_options, version=4
        )

    #
    # To v7
    #

    if config_entry.version in {4, 5, 6}:
        await remove_mqtt_topics(hass, config_entry)
        hass.config_entries.async_update_entry(config_entry, version=7)
        try:
            await asyncio.wait_for(hass.async_block_till_done(), timeout=10)
        except asyncio.TimeoutError:
            LOGGER.warning("⚠️ Migration took too long, continuing without blocking.")

    LOGGER.info("Migration to version %s successful", config_entry.version)

    return True


@asynccontextmanager
async def mqtt_session(client, mqtt_server, mqtt_port):
    LOGGER.debug("🟢 Connecting to MQTT server: %s:%s", mqtt_server, mqtt_port)

    try:
        client.connect(mqtt_server, mqtt_port)
        client.loop_start()
        yield
    finally:
        LOGGER.debug("🔴 Disconnecting from MQTT server")
        client.disconnect()
        client.loop_stop()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload Shopping List with Grocy integration."""
    LOGGER.info("🔄 Unloading Shopping List with Grocy...")

    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )

    if unload_ok:
        # ✅ Vérifie que DOMAIN existe avant de le supprimer
        if DOMAIN in hass.data:
            hass.data.pop(DOMAIN)

        # ✅ Vérifie si d'autres intégrations existent avant de décharger les services
        if not hass.data.get(DOMAIN, {}):
            async_unload_services(hass)

    return unload_ok
