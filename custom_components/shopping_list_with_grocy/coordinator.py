import asyncio
import logging
from datetime import timedelta

from async_timeout import timeout
from homeassistant.const import CONF_NAME
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, STATE_INIT

LOGGER = logging.getLogger(__name__)


class ShoppingListWithGrocyCoordinator(DataUpdateCoordinator):
    """Define an object to hold shopping list with grocy data."""

    def __init__(self, hass, session, entry, api):
        """Initialize."""
        self.hass = hass
        self.state = STATE_INIT
        self.config = entry.data
        self.name = self.config.get(CONF_NAME)
        self.api = api
        self._data = {}
        self._lock = asyncio.Lock()

        super().__init__(
            hass, LOGGER, name=self.name, update_interval=timedelta(seconds=30)
        )

    async def _async_update_data(self):
        async with self._lock:
            async with timeout(60):
                self._data = await self.api.retrieve_data()
                return self._data

    async def request_update(self):
        async with self._lock:
            async with timeout(60):
                self._data = await self.api.retrieve_data(True)
                return self._data

    async def add_product(self, product_id, shopping_list_id, note):
        await self.api.manage_product(product_id, shopping_list_id, note)

    async def remove_product(self, product_id, shopping_list_id):
        await self.api.manage_product(product_id, shopping_list_id, "", True)

    async def update_note(self, product_id, shopping_list_id, note):
        await self.api.update_note(product_id, shopping_list_id, note)
