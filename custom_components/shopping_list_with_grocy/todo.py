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
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
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
        self, coordinator: DataUpdateCoordinator, data: dict, list_prefix: str = ""
    ):
        """Initialize the Shopping with Grocy Todo List Entity."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.api = coordinator.api
        self._data = data
        self._list_prefix = list_prefix
        self._list_id = data["id"]
        self._list_name = data["name"] or f"List #{data['id']}"
        self._attr_name = f"{list_prefix} {self._list_name}".strip()
        self._attr_unique_id = f"{DOMAIN}.list.{self._list_id}"
        self.entity_id = (
            f"todo.shopping_list_with_grocy_{self._list_name.lower().replace(' ', '_')}"
        )

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
            if product["shop_list_id"] == item.uid:
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

        await self.coordinator.async_refresh()

    def _handle_coordinator_update(self) -> None:
        """Handle data updates from coordinator."""
        shopping_lists = self.coordinator.api.build_item_list(self.coordinator._data)
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
                uid=product["shop_list_id"],
                status=product["status"],
            )
            for product in self._data.get("products", [])
        ]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the shopping list integration."""
    config = entry.options or entry.data
    verify_ssl = config.get("verify_ssl", True)

    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    api = ShoppingListWithGrocyApi(session, hass, config)
    coordinator = ShoppingListWithGrocyCoordinator(hass, session, entry, api)

    await coordinator.async_config_entry_first_refresh()

    list_prefix = "SLWG -"
    shopping_lists = api.build_item_list(coordinator._data)

    LOGGER.debug(
        "Fetched %d total items from ShoppingListWithGrocy", len(shopping_lists)
    )

    entities = [
        ShoppingListWithGrocyTodoListEntity(coordinator, shopping_list, list_prefix)
        for shopping_list in shopping_lists
    ]

    async_add_entities(entities)
    LOGGER.debug("Added %d entities to Home Assistant", len(entities))
