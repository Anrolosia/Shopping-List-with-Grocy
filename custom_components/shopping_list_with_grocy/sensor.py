import asyncio
import copy
import logging
import re
from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENTITY_VERSION

LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)


class GrocyMultipleChoicesSensor(SensorEntity):
    """Sensor that tracks recent multiple choice events for voice assistants."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._attr_name = "Grocy Multiple Choices"
        self._attr_unique_id = "grocy_multiple_choices"
        self._attr_icon = "mdi:format-list-numbered"
        self._event_unsub = None

    async def async_added_to_hass(self):
        """Register dispatcher signal listener when entity is added to hass."""
        from homeassistant.helpers.dispatcher import async_dispatcher_connect

        if self._event_unsub is None:
            self._event_unsub = async_dispatcher_connect(
                self.hass,
                "grocy_multiple_choices_updated",
                self._handle_multiple_choices_event,
            )

    async def async_will_remove_from_hass(self):
        """Unregister dispatcher signal listener when entity is removed from hass."""
        if self._event_unsub is not None:
            self._event_unsub()
            self._event_unsub = None

    async def _handle_multiple_choices_event(self, event=None):

        self.async_write_ha_state()

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        import time

        current_time = time.time()

        recent_choices = self.hass.data.get(DOMAIN, {}).get(
            "recent_multiple_choices", {}
        )

        valid_choices = {
            product_name: choice_data
            for product_name, choice_data in recent_choices.items()
            if current_time - choice_data.get("timestamp", 0) < 300
        }

        if valid_choices:
            return "multiple_found"
        return "none"

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        recent_choices = self.hass.data.get(DOMAIN, {}).get(
            "recent_multiple_choices", {}
        )
        import time

        current_time = time.time()

        valid_choices = {
            product_name: choice_data
            for product_name, choice_data in recent_choices.items()
            if current_time - choice_data.get("timestamp", 0) < 300
        }

        return {"recent_choices": valid_choices, "choice_count": len(valid_choices)}


class GrocyShoppingSuggestionsSensor(SensorEntity):
    """Representation of a Sensor that holds shopping suggestions."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._attr_name = "Grocy Shopping Suggestions"
        self._attr_unique_id = "grocy_shopping_suggestions"
        self._state = None
        self._attributes = {}
        self._reset_timer_cancel = None
        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}
        if "suggestions" not in hass.data[DOMAIN]:
            hass.data[DOMAIN]["suggestions"] = {"products": [], "last_update": None}

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._reset_timer_cancel = async_track_time_interval(
            self.hass, self._check_auto_reset, timedelta(minutes=15)
        )

    async def async_will_remove_from_hass(self):
        """When entity will be removed from hass."""
        if self._reset_timer_cancel:
            self._reset_timer_cancel()
        await super().async_will_remove_from_hass()

    async def _check_auto_reset(self, now):
        """Check if suggestions should be auto-reset after 1 hour."""
        if DOMAIN not in self.hass.data or "suggestions" not in self.hass.data[DOMAIN]:
            return

        suggestions_data = self.hass.data[DOMAIN]["suggestions"]
        last_update_str = suggestions_data.get("last_update")

        if not last_update_str:
            return

        try:
            last_update = datetime.fromisoformat(last_update_str.replace("Z", "+00:00"))
            if last_update.tzinfo is None:
                last_update = (
                    last_update.replace(tzinfo=now.tzinfo)
                    if now.tzinfo
                    else last_update
                )

            time_diff = now - last_update
            if time_diff >= timedelta(hours=1):
                self.hass.data[DOMAIN]["suggestions"] = {
                    "products": [],
                    "last_update": None,
                }

                self.async_write_ha_state()
            else:
                remaining = timedelta(hours=1) - time_diff

        except (ValueError, TypeError) as e:
            LOGGER.warning("Error parsing last_update time for auto-reset: %s", e)

    @property
    def state(self) -> int:
        """Return the number of suggestions."""
        if DOMAIN in self.hass.data and "suggestions" in self.hass.data[DOMAIN]:
            return len(self.hass.data[DOMAIN]["suggestions"].get("products", []))
        return 0

    @property
    def extra_state_attributes(self):
        """Return entity specific state attributes."""
        if DOMAIN in self.hass.data and "suggestions" in self.hass.data[DOMAIN]:
            return {
                "suggestions": self.hass.data[DOMAIN]["suggestions"].get(
                    "products", []
                ),
                "last_update": self.hass.data[DOMAIN]["suggestions"].get("last_update"),
            }
        return {"suggestions": [], "last_update": None}


class GrocyVoiceResponseHelperSensor(SensorEntity):
    """Permanent sensor for Grocy voice assistant responses."""

    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self._attr_name = "Grocy Voice Response Helper"
        self._attr_unique_id = f"{DOMAIN}_voice_response_helper"
        self._state = "idle"
        self._sync_not_enabled = None

    async def async_added_to_hass(self):
        await self._load_sync_not_enabled()
        await super().async_added_to_hass()

    async def _load_sync_not_enabled(self):
        from .services import get_voice_translation

        msg = await get_voice_translation(self.hass, "sync_not_enabled")
        self._sync_not_enabled = (
            msg if msg else "Bidirectional sync is not enabled yet."
        )

    @property
    def name(self):
        return self._attr_name

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return {"sync_not_enabled": self._sync_not_enabled}

    async def async_update(self):
        await self._load_sync_not_enabled()


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the sensor platform."""

    async_add_entities(
        [
            GrocyShoppingSuggestionsSensor(hass),
            GrocyMultipleChoicesSensor(hass),
            GrocyVoiceResponseHelperSensor(hass),
        ]
    )

    entity_registry = async_get(hass)

    old_entity_id = "sensor.product_items"
    if entity_registry.async_is_registered(old_entity_id):
        entity_registry.async_remove(old_entity_id)
        hass.states.async_remove(old_entity_id)

    if hass.states.get(old_entity_id):
        hass.states.async_remove(old_entity_id)

    if DOMAIN not in hass.data:
        return

    if config_entry.entry_id not in hass.data[DOMAIN]:
        return

    if "entities" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["entities"] = {}

    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    if not coordinator:
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
            sensor.entity_id = expected_entity_id
            sensor.async_write_ha_state()

    pattern = re.compile(r"list_\d+_.*")

    async def async_add_or_update_dynamic_sensor(product):
        product_id = str(product["product_id"])
        entity_id = f"sensor.{DOMAIN}_product_v{ENTITY_VERSION}_{product_id}"

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

            if "entity_picture" in product.get("attributes", {}):
                updated_attributes["entity_picture"] = product["attributes"][
                    "entity_picture"
                ]

            new_state = str(product.get("qty_in_shopping_lists", existing_state))

            state_changed = new_state != existing_state
            attributes_changed = updated_attributes != existing_attributes

            force_picture_update = False
            if "entity_picture" in product.get("attributes", {}):
                try:
                    current_pic = existing_attributes.get("entity_picture")
                    incoming_pic = product["attributes"].get("entity_picture")
                    if current_pic != incoming_pic:
                        force_picture_update = True
                except Exception:
                    force_picture_update = True

            if state_changed or attributes_changed or force_picture_update:

                hass.states.async_set(
                    entity_id, new_state, attributes=updated_attributes
                )

                await asyncio.sleep(1)

                if product_id in coordinator._parsed_data:
                    coordinator._parsed_data[product_id] = copy.deepcopy(product)
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

        async_dispatcher_connect(
            self.hass, "grocy_multiple_choices_force_update", self._force_update
        )

    @property
    def icon(self):
        return "mdi:cart"

    async def _force_update(self):
        """Callback to force update of HA state."""
        await self.async_update_ha_state(force_refresh=True)


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
            entity_registry.async_update_entity(
                registry_entry.entity_id, new_entity_id=f"sensor.{self._attr_unique_id}"
            )

    async def async_will_remove_from_hass(self):
        await super().async_will_remove_from_hass()

        entity_registry = async_get(self.hass)
        registry_entry = entity_registry.async_get(self.entity_id)

        if registry_entry:
            entity_registry.async_remove(registry_entry.entity_id)
