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
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_registry import async_get
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .apis.shopping_list_with_grocy import ShoppingListWithGrocyApi
from .const import DOMAIN
from .coordinator import ShoppingListWithGrocyCoordinator
from .frontend_translations import async_load_frontend_translations, get_todo_strings

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

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        LOGGER.debug("Coordinator update received for Todo entity %s", self.entity_id)

        shopping_lists_data = self.coordinator.data.get("shopping_lists_data", [])
        if shopping_lists_data:

            for list_data in shopping_lists_data:
                if str(list_data.get("id")) == str(self._list_id):
                    self._data = list_data
                    LOGGER.debug(
                        "Updated _data for list %s with %d products",
                        self._list_id,
                        len(list_data.get("products", [])),
                    )
                    break
        else:

            shopping_lists = self.coordinator.api.build_item_list(self.coordinator.data)
            shopping_list = next(
                (lst for lst in shopping_lists if lst["id"] == self._list_id), None
            )
            if shopping_list:
                self._data = shopping_list
                new_name = f"{self._list_prefix} {shopping_list['name'] or f'List #{shopping_list['id']}'}".strip()
                if self._attr_name != new_name:
                    self._attr_name = new_name

        super()._handle_coordinator_update()

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
            TodoListEntityFeature.UPDATE_TODO_ITEM
            | TodoListEntityFeature.DELETE_TODO_ITEM
        )

        if bidirectional_sync_enabled:
            self._attr_supported_features = (
                base_features | TodoListEntityFeature.CREATE_TODO_ITEM
            )
            LOGGER.debug(
                "Bidirectional sync enabled - CREATE_TODO_ITEM feature available"
            )
        else:
            self._attr_supported_features = base_features
            LOGGER.debug(
                "Bidirectional sync disabled - CREATE_TODO_ITEM feature not available"
            )

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the current todo items."""
        return [
            TodoItem(
                summary=product["name"],
                uid=str(product["shop_list_id"]),
                status=product["status"],
            )
            for product in self._data.get("products", [])
        ]

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete todo items from Grocy and update local state."""
        LOGGER.debug("Deleting %d items from list %s", len(uids), self._list_id)

        self._data["products"] = [
            product
            for product in self._data.get("products", [])
            if str(product["shop_list_id"]) not in uids
        ]
        self.async_write_ha_state()

        tasks = [
            self.api.remove_product_from_shopping_list(int(item_id)) for item_id in uids
        ]
        try:
            await asyncio.gather(*tasks)
            LOGGER.debug("Successfully deleted %d items", len(uids))
        except Exception as e:
            LOGGER.error("Failed to delete items: %s", e)

        await self.coordinator.async_refresh()

    @property
    def extra_state_attributes(self):

        config_entry = None
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            config_entry = entry
            break

        bidirectional_sync_enabled = False
        if config_entry:
            config = config_entry.options or config_entry.data
            bidirectional_sync_enabled = config.get("enable_bidirectional_sync", False)

        return {
            "product_choices": self.hass.data[DOMAIN].get("product_choices", {}),
            "recent_multiple_choices": self.hass.data[DOMAIN].get(
                "recent_multiple_choices", {}
            ),
            "enable_bidirectional_sync": bidirectional_sync_enabled,
        }

    async def async_create_todo_item(self, item: TodoItem) -> None:
        if getattr(self.api, "bidirectional_sync_stopped", False):
            LOGGER.error("Bidirectional sync is stopped, cannot create item")
            return

        multiple_choice = False

        try:
            result = await self.api.handle_ha_todo_item_creation(
                item.summary, shopping_list_id=self._list_id
            )

            LOGGER.debug("Full result on item '%s': %s", item.summary, result)
            if result["success"]:
                LOGGER.debug(
                    "Successfully created item '%s' in Grocy via bidirectional sync",
                    item.summary,
                )
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

                voice_mode = self.hass.data.get(DOMAIN, {}).get("voice_mode", False)
                if not voice_mode:
                    language = self.hass.config.language or "en"
                    frontend_translations = await async_load_frontend_translations(
                        self.hass, language
                    )

                    title = get_todo_strings(
                        frontend_translations, "product_selected_title"
                    )
                    message_template = get_todo_strings(
                        frontend_translations, "product_added"
                    )
                    message = message_template.format(
                        choice=result.get("choice_number", ""),
                        product=result["product_name"],
                    )

                    await self.hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {
                            "title": title,
                            "message": message,
                            "notification_id": f"grocy_product_added_{int(time.time())}",
                        },
                    )

            elif result["reason"] == "multiple_matches":
                matches = result["matches"]
                choice_key = f"product_choice_{int(time.time())}"
                service_options = [
                    f"{i}. {match['name']}" for i, match in enumerate(matches[:5], 1)
                ]
                service_options_text = "\n".join(service_options)

                voice_mode = self.hass.data.get(DOMAIN, {}).get("voice_mode", False)
                if not voice_mode:
                    yaml_service = (
                        "service: shopping_list_with_grocy.select_choice_by_number\n"
                        "data:\n"
                        "\u00A0\u00A0choice_number: [REPLACE_WITH_NUMBER_FROM_LIST_ABOVE]"
                    )

                    language = self.hass.config.language or "en"
                    frontend_translations = await async_load_frontend_translations(
                        self.hass, language
                    )

                    title_template = get_todo_strings(
                        frontend_translations, "multiple_choice_title"
                    )
                    title = title_template.format(term=result["search_term"])

                    message_template = get_todo_strings(
                        frontend_translations, "multiple_choice_message"
                    )
                    message = message_template.format(
                        options=service_options_text, yaml=yaml_service
                    )

                    await self.hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {
                            "title": title,
                            "message": message,
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

                LOGGER.debug(
                    "Before: hass.data[DOMAIN].keys() = %s",
                    list(self.hass.data[DOMAIN].keys()),
                )
                if "recent_multiple_choices" not in self.hass.data[DOMAIN]:
                    self.hass.data[DOMAIN]["recent_multiple_choices"] = {}
                    LOGGER.debug(
                        "recent_multiple_choices initialized in hass.data[DOMAIN]"
                    )
                else:
                    LOGGER.debug(
                        "recent_multiple_choices already exists: %s",
                        self.hass.data[DOMAIN]["recent_multiple_choices"],
                    )

                normalized_name = result["search_term"].strip().lower()
                LOGGER.debug("Storing choice for normalized_name='%s'", normalized_name)
                self.hass.data[DOMAIN]["recent_multiple_choices"][normalized_name] = {
                    "timestamp": time.time(),
                    "matches_count": len(matches),
                    "choice_key": choice_key,
                }
                LOGGER.debug(
                    "After storing: recent_multiple_choices = %s",
                    self.hass.data[DOMAIN]["recent_multiple_choices"],
                )

                await asyncio.sleep(0.1)
                LOGGER.debug(
                    "Sending dispatcher signal: grocy_multiple_choices_updated"
                )
                async_dispatcher_send(
                    self.hass,
                    "grocy_multiple_choices_updated",
                    {"product_name": normalized_name, "matches_count": len(matches)},
                )
                LOGGER.debug("Dispatcher signal sent successfully")

                self.async_write_ha_state()

                voice_mode = self.hass.data.get(DOMAIN, {}).get("voice_mode", False)
                if voice_mode:
                    multiple_choice = True
                    raise Exception(
                        f"Multiple products found for '{result['search_term']}'. Please choose from: {', '.join([match['name'] for match in matches[:3]])}"
                    )
                else:
                    return

            else:
                error_reason = result.get("reason", "unknown")
                LOGGER.error(
                    "❌ Failed to create item '%s': %s", item.summary, error_reason
                )

        except Exception as e:
            if not multiple_choice:
                LOGGER.error("Error creating todo item '%s': %s", item.summary, e)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update an existing todo item."""
        LOGGER.debug(
            "Updating todo item: %s (UID: %s, Status: %s)",
            item.summary,
            item.uid,
            item.status,
        )

        try:

            checked = item.status == TodoItemStatus.COMPLETED

            for product in self._data.get("products", []):
                if str(product["shop_list_id"]) == str(item.uid):
                    product["status"] = (
                        TodoItemStatus.COMPLETED
                        if checked
                        else TodoItemStatus.NEEDS_ACTION
                    )
                    break

            self.async_write_ha_state()

            try:
                await self.api.update_grocy_shoppinglist_product(int(item.uid), checked)
                LOGGER.debug(
                    "Successfully updated item %s to status: %s",
                    item.uid,
                    "completed" if checked else "needs action",
                )
            except Exception as e:
                LOGGER.error("Failed to update item %s in Grocy: %s", item.uid, e)

                for product in self._data.get("products", []):
                    if str(product["shop_list_id"]) == str(item.uid):
                        product["status"] = (
                            TodoItemStatus.NEEDS_ACTION
                            if checked
                            else TodoItemStatus.COMPLETED
                        )
                        break
                self.async_write_ha_state()
                raise

            self.hass.async_create_task(self.coordinator.async_refresh())

        except Exception as e:
            LOGGER.error("Error updating todo item '%s': %s", item.summary, e)
            raise


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
):
    """Set up the To-do List platform."""
    coordinator = hass.data[DOMAIN].get(config_entry.entry_id)
    if not coordinator:
        LOGGER.error("❌ No coordinator found for entry ID %s", config_entry.entry_id)
        return

    if "shopping_lists" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["shopping_lists"] = []

    shopping_lists_data = coordinator.data.get("shopping_lists_data", [])
    fallback_lists = coordinator.data.get("shopping_lists", [])

    if shopping_lists_data:
        LOGGER.debug(
            "Found %d shopping lists in coordinator shopping_lists_data",
            len(shopping_lists_data),
        )
        lists = shopping_lists_data
    else:
        LOGGER.debug(
            "Using fallback: Found %d shopping lists in coordinator data",
            len(fallback_lists),
        )
        lists = fallback_lists

    entities = [
        ShoppingListWithGrocyTodoListEntity(hass, coordinator, list_data, "SWLG -")
        for list_data in lists
    ]

    async_add_entities(entities)
    LOGGER.debug("Added %d shopping lists to To-do platform", len(entities))
