import asyncio
import logging
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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

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
    _attr_supported_features = (
        TodoListEntityFeature.UPDATE_TODO_ITEM | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        data: dict,
        list_prefix: str = "",
    ):
        """Initialize the Shopping with Grocy Todo List Entity."""
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

        LOGGER.debug(
            "Initialized ShoppingListWithGrocyTodoListEntity: name='%s', unique_id='%s', entity_id='%s'",
            self._attr_name,
            self._attr_unique_id,
            self.entity_id,
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete todo items from Grocy and update local state."""
        LOGGER.debug("Deleting %d items from list %s", len(uids), self._list_id)

        self._data["products"] = [
            product
            for product in self._data.get("products", [])
            if product["shop_list_id"] not in uids
        ]

        self.async_write_ha_state()

        tasks = [
            self.api.remove_product_from_shopping_list(item_id) for item_id in uids
        ]

        try:
            await asyncio.gather(*tasks)
            LOGGER.debug("Successfully deleted %d items", len(uids))
        except Exception as e:
            LOGGER.error("Failed to delete items: %s", e)

        await self.coordinator.async_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update a todo item in Grocy and update local state."""
        LOGGER.debug("Updating item '%s' in list '%s'", item.uid, self._list_id)

        checked = item.status == TodoItemStatus.COMPLETED

        for product in self._data.get("products", []):
            if str(product["shop_list_id"]) == str(item.uid):
                product["status"] = (
                    TodoItemStatus.COMPLETED if checked else TodoItemStatus.NEEDS_ACTION
                )
                break

        self.async_write_ha_state()

        try:
            await self.api.update_grocy_shoppinglist_product(
                item.uid, "1" if checked else "0"
            )
            LOGGER.debug("Successfully updated item %s", item.uid)
        except Exception as e:
            LOGGER.error("Failed to update item %s: %s", item.uid, e)

        self.hass.async_create_task(self.coordinator.async_refresh())

    def _handle_coordinator_update(self) -> None:
        """Handle data updates from coordinator."""
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

    @property
    def todo_items(self) -> list[TodoItem]:
        return [
            TodoItem(
                summary=product["name"],
                uid=str(product["shop_list_id"]),
                status=product["status"],
            )
            for product in self._data.get("products", [])
        ]

    @property
    def icon(self):
        return "mdi:cart"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the shopping list integration."""

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    if (
        "todo_initialized" in hass.data[DOMAIN]
        and hass.data[DOMAIN]["todo_initialized"]
    ):
        LOGGER.info("TODO already initialized, skipping duplicate setup.")
        return False

    hass.data[DOMAIN]["todo_initialized"] = True

    config = entry.options or entry.data
    verify_ssl = config.get("verify_ssl", True)

    instance_data = hass.data[DOMAIN]["instances"]
    coordinator = instance_data.get("coordinator")
    api = instance_data.get("api")
    session = instance_data.get("session")

    if not coordinator or not api or not session:
        LOGGER.error(
            "Missing required instances in hass.data[DOMAIN]. Todo setup aborted."
        )
        return

    list_prefix = "SLWG -"
    shopping_lists = api.build_item_list(coordinator.data)

    entities = [
        ShoppingListWithGrocyTodoListEntity(
            hass, coordinator, shopping_list, list_prefix
        )
        for shopping_list in shopping_lists
    ]

    async_add_entities(entities)

    async def async_check_new_lists(_=None):
        """Check for new or removed shopping lists periodically."""
        entity_registry = async_get(hass)
        platform = entity_platform.current_platform.get()
        if not platform:
            return

        existing_list_ids = set(hass.data[DOMAIN]["shopping_lists"])
        grocy_list_data = api.build_item_list(coordinator.data)

        if isinstance(grocy_list_data, dict):
            grocy_list_ids = set(grocy_list_data.keys())
        elif isinstance(grocy_list_data, list):
            grocy_list_ids = {lst["id"] for lst in grocy_list_data if "id" in lst}
        else:
            LOGGER.error(
                "❌ Unexpected type for shopping_lists: %s", type(grocy_list_data)
            )
            grocy_list_ids = set()

        new_list_ids = grocy_list_ids - existing_list_ids
        removed_list_ids = existing_list_ids - grocy_list_ids

        new_entities = []
        for list_id in new_list_ids:
            list_data = next(
                (lst for lst in grocy_list_data if lst["id"] == list_id), None
            )
            if not list_data:
                continue

            entity_id = f"todo.{DOMAIN}_list_{list_id}"

            existing_entity = hass.states.get(entity_id)
            if existing_entity:
                continue

            entity = ShoppingListWithGrocyTodoListEntity(
                hass, coordinator, list_data, "SLWG -"
            )
            new_entities.append(entity)

        if new_entities:
            try:
                async_add_entities(new_entities)
            except Exception as e:
                LOGGER.error("❌ Error adding entities: %s", e)

        for list_id in removed_list_ids:
            entity_id = f"todo.{DOMAIN}_list_{list_id}"
            existing_entity = hass.states.get(entity_id)

            if existing_entity:
                if entity_registry.async_is_registered(entity_id):
                    entity_registry.async_remove(entity_id)

                hass.states.async_remove(entity_id)

                await asyncio.sleep(0.1)

                hass.data[DOMAIN]["shopping_lists"].remove(list_id)

        await coordinator.async_refresh()

    hass.data[DOMAIN]["remove_check_task"] = async_track_time_interval(
        hass, async_check_new_lists, timedelta(seconds=30)
    )
