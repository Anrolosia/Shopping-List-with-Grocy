import asyncio
import logging
from datetime import timedelta

from async_timeout import timeout
from homeassistant.const import CONF_NAME
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, STATE_INIT

LOGGER = logging.getLogger(__name__)


class ShoppingListWithGrocyCoordinator(DataUpdateCoordinator):
    """Coordinator to manage fetching data from Grocy API."""

    def __init__(self, hass, session, entry, api):
        """Initialize the coordinator."""
        self.hass = hass
        self.session = session
        self.entry = entry
        self.api = api
        self.last_successful_fetch = None
        self._data = {}  # Ensure data is initialized properly
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_coordinator",
            update_interval=timedelta(seconds=30),
        )

    async def _async_update_data(self):
        await self.retrieve_data()
        return self._data

    async def add_product(self, product_id, shopping_list_id, note):
        """Add a product to the shopping list."""
        return await self.api.manage_product(product_id, shopping_list_id, note)

    async def remove_product(self, product_id, shopping_list_id):
        """Remove a product from the shopping list."""
        return await self.api.manage_product(product_id, shopping_list_id, "", True)

    async def update_note(self, product_id, shopping_list_id, note):
        """Update the note for a product in the shopping list."""
        return await self.api.update_note(product_id, shopping_list_id, note)

    async def request_update(self):
        """Force an update of the shopping list."""
        await self.retrieve_data(True)
        return self._data

    async def retrieve_data(self, force=False):
        """Fetch data from API with retries and error handling."""
        try:
            async with timeout(60):
                data = await self.api.retrieve_data(force)
                if data is not None:
                    self.last_successful_fetch = self.hass.loop.time()
                    self._data = data  # Ensure data is always updated
                else:
                    LOGGER.warning("Received empty or invalid data from API.")
        except asyncio.TimeoutError:
            LOGGER.error("Timeout occurred while fetching data from Grocy API.")
        except Exception as e:
            LOGGER.exception(
                "Unexpected error while fetching data from Grocy API: %s", e
            )
