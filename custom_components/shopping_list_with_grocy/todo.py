import asyncio
import logging
import time
from datetime import timedelta

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_registry import async_get
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .apis.shopping_list_with_grocy import ShoppingListWithGrocyApi
from .const import DOMAIN
from .coordinator import ShoppingListWithGrocyCoordinator

LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=15)


class ShoppingListWithGrocyTodoListEntity(
    CoordinatorEntity[ShoppingListWithGrocyCoordinator], TodoListEntity
):
    """A To-do List representation of a Shopping with Grocy List."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        data: dict,
        list_prefix: str = "",
    ):
        super().__init__(coordinator)
        self.hass = hass
        self.coordinator = coordinator
        self.api = coordinator.api
        self._data = data
        self._list_prefix = list_prefix
        self._list_id = data["id"]
        self._list_name = data["name"] or f"List #{data['id']}"
        self._attr_name = f"{list_prefix} {self._list_name}".strip()
        self._attr_unique_id = f"{DOMAIN}.list.{self._list_id}"
        self.entity_id = f"todo.{DOMAIN}_list_{self._list_id}"
        self.hass.data[DOMAIN]["shopping_lists"].append(self._list_id)

        self._update_supported_features()

        LOGGER.debug(
            "Initialized ShoppingListWithGrocyTodoListEntity: name='%s', unique_id='%s', entity_id='%s'",
            self._attr_name,
            self._attr_unique_id,
            self.entity_id,
        )

    def _update_supported_features(self):
        config_entry = None
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            config_entry = entry
            break

        bidirectional_sync_enabled = False
        if config_entry:
            config = config_entry.options or config_entry.data
            bidirectional_sync_enabled = config.get("enable_bidirectional_sync", False)

        base_features = (
            TodoListEntityFeature.UPDATE_TODO_ITEM |
            TodoListEntityFeature.DELETE_TODO_ITEM
        )

        if bidirectional_sync_enabled:
            self._attr_supported_features = base_features | TodoListEntityFeature.CREATE_TODO_ITEM
            LOGGER.error("🔄 Bidirectional sync enabled - CREATE_TODO_ITEM feature available")
        else:
            self._attr_supported_features = base_features
            LOGGER.error("🚫 Bidirectional sync disabled - CREATE_TODO_ITEM feature not available")

    @property
    def extra_state_attributes(self):
        # Inject product_choices and recent_multiple_choices as attributes
        return {
            "product_choices": self.hass.data[DOMAIN].get("product_choices", {}),
            "recent_multiple_choices": self.hass.data[DOMAIN].get("recent_multiple_choices", {})
        }

    async def async_create_todo_item(self, item: TodoItem) -> None:
        LOGGER.error("Creating new item '%s' in list '%s'", item.summary, self._list_id)

        if getattr(self.api, 'bidirectional_sync_stopped', False):
            LOGGER.error("🛑 Bidirectional sync is stopped, cannot create item")
            return

        try:
            result = await self.api.handle_ha_todo_item_creation(
                item.summary,
                shopping_list_id=self._list_id
            )

            if result["success"]:
                LOGGER.error("✅ Successfully created item '%s' in Grocy via bidirectional sync", item.summary)
                new_product = {
                    "name": f"{result['product_name']} (x{result['quantity']})",
                    "shop_list_id": f"temp_{result['product_id']}",
                    "status": TodoItemStatus.NEEDS_ACTION,
                }
                if "products" not in self._data:
                    self._data["products"] = []
                self._data["products"].append(new_product)
                self.async_write_ha_state()
                await self.coordinator.async_refresh()

            elif result["reason"] == "multiple_matches":
                matches = result["matches"]
                choice_key = f"product_choice_{int(time.time())}"
                service_options = [
                    f"{i}. {match['name']} → product_id: {match['id']}"
                    for i, match in enumerate(matches[:5], 1)
                ]
                service_options_text = "\n".join(service_options)

                await self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": "Multiple Products Found",
                        "message": f"Multiple products match '{result['search_term']}':\n\n{service_options_text}\n\n📋 Go to Developer Tools → Services and copy-paste:\n\nservice: shopping_list_with_grocy.choose_product\ndata:\n  choice_key: \"{choice_key}\"\n  product_id: [REPLACE_WITH_ID_FROM_LIST_ABOVE]",
                        "notification_id": f"grocy_multiple_matches_{int(time.time())}",
                    },
                )

                if "product_choices" not in self.hass.data[DOMAIN]:
                    self.hass.data[DOMAIN]["product_choices"] = {}
                self.hass.data[DOMAIN]["product_choices"][choice_key] = {
                    "matches": matches,
                    "original_name": result["search_term"],
                    "quantity": result["quantity"],
                    "shopping_list_id": result["shopping_list_id"],
                    "timestamp": time.time(),
                }

                if "recent_multiple_choices" not in self.hass.data[DOMAIN]:
                    self.hass.data[DOMAIN]["recent_multiple_choices"] = {}
                normalized_name = result["search_term"].strip().lower()
                self.hass.data[DOMAIN]["recent_multiple_choices"][normalized_name] = {
                    "timestamp": time.time(),
                    "matches_count": len(matches),
                    "choice_key": choice_key
                }

                async_dispatcher_send(
                    self.hass,
                    "grocy_multiple_choices_updated"
                )
                self.async_write_ha_state()
                LOGGER.error("⚠️ Multiple products found for '%s', user choice required", result["search_term"])

            else:
                error_reason = result.get("reason", "unknown")
                LOGGER.error("❌ Failed to create item '%s': %s", item.summary, error_reason)

        except Exception as e:
            LOGGER.error("❌ Error creating todo item '%s': %s", item.summary, e)
