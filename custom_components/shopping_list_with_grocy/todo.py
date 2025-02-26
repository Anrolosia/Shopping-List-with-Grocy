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
        self,
        coordinator: DataUpdateCoordinator,
        data: list,
        list_prefix: str,
    ):
        """Initialize the Shopping with Grocy Todo List Entity."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.api = coordinator.api
        self._data = data
        self._list_prefix = list_prefix
        self._list_id = data["id"]
        self._list_name = data["name"] if data["name"] != "" else "List #" + data["id"]
        self._attr_name = (f"{list_prefix} " if list_prefix else "") + (
            f"{self._list_name}"
        )
        self._attr_unique_id = f"{DOMAIN}.list.{data["id"]}"

        self.entity_id = self._get_default_entity_id("Shopping List")

        LOGGER.debug(
            "Initialized ShoppingListWithGrocyTodoListEntity: name='%s', unique_id='%s', "
            "entity_id='%s'",
            self._attr_name,
            self._attr_unique_id,
            self.entity_id,
        )

    def _get_default_entity_id(self, title: str) -> str:
        """Return the entity ID for the given title."""
        entity_id = f"todo.shopping_list_with_grocy_{title.lower().replace(' ', '_')}"
        LOGGER.debug("Generated entity ID: '%s' for title: '%s'", entity_id, title)
        return entity_id

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete todo items from Grocy."""
        LOGGER.debug("Deleting todo items: %s from list: %s", uids, self._data)
        list_id = self._list_id

        for item_id in uids:
            try:
                LOGGER.debug("item id: %s, list_id: %s", item_id, list_id)
                await self.api.remove_product_from_shopping_list(item_id)
                LOGGER.debug("Item %s deleted fromlist", item_id)
            except Exception as e:
                LOGGER.error("Failed to delete item %s from list: %s", item_id, e)

        await self.coordinator.async_refresh()
        LOGGER.debug("Requested data refresh after deletions.")

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update a todo item in Grocy."""
        LOGGER.debug("Updating todo item: %s in list: %s", item.uid, self._list_id)
        try:
            list_id = self._list_id
            item_id = item.uid
            checked = item.status == TodoItemStatus.COMPLETED

            await self.api.update_grocy_shoppinglist_product(
                item_id,
                "1" if checked else "0",
            )
            LOGGER.debug("Successfully updated item %s in Shopping list.", item_id)

        except Exception as e:
            LOGGER.error("Failed to update item %s in Shopping list: %s", item.uid, e)

        finally:
            await self.coordinator.async_refresh()
            LOGGER.debug("Requested data refresh after update.")

    def _handle_coordinator_update(self) -> None:
        shopping_lists = self.coordinator.api.build_item_list(self.coordinator._data)
        for shopping_list in shopping_lists:
            if shopping_list["id"] == self._list_id:
                self._data = shopping_list
                list_prefix = self._list_prefix
                list_name = (
                    shopping_list["name"]
                    if shopping_list["name"] != ""
                    else "List #" + shopping_list["id"]
                )
                new_name = (f"{list_prefix} " if list_prefix else "") + (
                    f"{self._list_name}"
                )
                if self._attr_name != new_name:
                    self._attr_name = new_name
                break
        super()._handle_coordinator_update()

    @property
    def todo_items(self) -> list[TodoItem]:
        items = []
        for product in self._data.get("products", []):
            items.append(
                TodoItem(
                    summary=product["name"],
                    uid=product["shop_list_id"],
                    status=product["status"],
                )
            )

        return items


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
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

    await coordinator._async_update_data()

    list_prefix = "SLWG -"

    shopping_lists = api.build_item_list(coordinator._data)

    LOGGER.debug(
        "Fetched %d total items from ShoppingListWithGrocy", len(shopping_lists)
    )

    entities = [
        ShoppingListWithGrocyTodoListEntity(coordinator, list, list_prefix)
        for list in shopping_lists
    ]
    LOGGER.debug(
        "Created %d ShoppingListWithGrocyTodoListEntity instances", len(entities)
    )

    async_add_entities(entities)
    LOGGER.debug("Added %d entities to Home Assistant", len(entities))
