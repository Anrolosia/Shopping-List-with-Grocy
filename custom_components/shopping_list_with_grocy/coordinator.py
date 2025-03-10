import asyncio
import logging
from datetime import timedelta

from async_timeout import timeout
from homeassistant.const import CONF_NAME
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, STATE_INIT
from .utils import is_update_paused

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
        self.data = hass.data.setdefault(DOMAIN, {}).setdefault("products", {})
        self.disable_timeout = entry.options.get("disable_timeout", False)
        self._parsed_data = {}
        homeassistant_products = self.data.get("homeassistant_products", {})
        # Ensure it's a dictionary (failsafe)
        if not isinstance(homeassistant_products, dict):
            LOGGER.error("❌ homeassistant_products is not a dictionary! Resetting.")
            homeassistant_products = {}
        self._parsed_data.update(homeassistant_products)
        self.entities = []
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_coordinator",
            update_interval=timedelta(seconds=30),
        )

    async def _async_update_data(self):
        await self.retrieve_data()
        return self.data

    async def add_product(self, product_id, shopping_list_id, note):
        return await self.api.manage_product(product_id, shopping_list_id, note)

    async def remove_product(self, product_id, shopping_list_id):
        return await self.api.manage_product(product_id, shopping_list_id, "", True)

    async def update_note(self, product_id, shopping_list_id, note):
        return await self.api.update_note(product_id, shopping_list_id, note)

    async def request_update(self):
        await self.retrieve_data(True)
        return self.data

    async def retrieve_data(self, force=False):
        try:
            paused = is_update_paused(self.hass)

            if not paused:
                if self.disable_timeout:
                    data = await self.api.retrieve_data(force)
                else:
                    async with timeout(60):
                        data = await self.api.retrieve_data(force)

                if data is not None:
                    self.last_successful_fetch = self.hass.loop.time()
                    self.data = data
                    homeassistant_products = self.data.get("homeassistant_products", {})
                    # Ensure it's a dictionary (failsafe)
                    if not isinstance(homeassistant_products, dict):
                        LOGGER.error(
                            "❌ homeassistant_products is not a dictionary! Resetting."
                        )
                        homeassistant_products = {}
                    for product_id, product_data in homeassistant_products.items():
                        if product_id in self._parsed_data:
                            self._parsed_data[product_id]["qty_in_shopping_lists"] = (
                                product_data["qty_in_shopping_lists"]
                            )

                            existing_attributes = self._parsed_data[product_id][
                                "attributes"
                            ]
                            new_attributes = product_data["attributes"]

                            existing_shopping_keys = {
                                key
                                for key in existing_attributes
                                if key.startswith("list_")
                            }
                            new_shopping_keys = {
                                key for key in new_attributes if key.startswith("list_")
                            }
                            keys_to_remove = existing_shopping_keys - new_shopping_keys

                            for key in keys_to_remove:
                                existing_attributes.pop(key, None)

                            existing_attributes.update(new_attributes)

                        else:
                            self._parsed_data[product_id] = product_data

                else:
                    LOGGER.warning("Received empty or invalid data from API.")
        except asyncio.TimeoutError:
            LOGGER.error("Timeout occurred while fetching data from Grocy API.")
        except Exception as e:
            LOGGER.exception(
                "Unexpected error while fetching data from Grocy API: %s", e
            )
