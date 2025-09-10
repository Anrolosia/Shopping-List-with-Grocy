import asyncio
import logging
import time
from datetime import timedelta

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .utils import is_update_paused

LOGGER = logging.getLogger(__name__)


class ShoppingListWithGrocyCoordinator(DataUpdateCoordinator):
    """Coordinator to manage fetching data from Grocy API."""

    def __init__(self, hass, session, entry, api):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_coordinator",
            update_interval=timedelta(seconds=30),
        )
        self.hass = hass
        self.session = session
        self.entry = entry
        self.api = api
        self.last_successful_fetch = None
        self.entities = []

        self.data = hass.data.setdefault(DOMAIN, {}).setdefault("products", {})
        self._parsed_data = {}

        homeassistant_products = self.data.get("homeassistant_products", {})
        if not isinstance(homeassistant_products, dict):
            LOGGER.error(
                "\u274c homeassistant_products is not a dictionary! Resetting."
            )
            homeassistant_products = {}
        self._parsed_data.update(homeassistant_products)

    async def _async_update_data(self):
        await self.retrieve_data()
        return self.data

    async def add_product(self, product_id, shopping_list_id, note, quantity=1):
        return await self.api.manage_product(
            product_id, shopping_list_id, note, False, quantity
        )

    async def remove_product(self, product_id, shopping_list_id):
        return await self.api.manage_product(product_id, shopping_list_id, "", True)

    async def update_note(self, product_id, shopping_list_id, note):
        return await self.api.update_note(product_id, shopping_list_id, note)

    async def request_update(self):
        await self.retrieve_data(True)
        return self.data

    async def _cleanup_orphaned_choices(self) -> None:
        """Clean up orphaned product choices older than 2 minutes."""
        if DOMAIN not in self.hass.data:
            return

        current_time = time.time()
        cleanup_threshold = 2 * 60  # 2 minutes in seconds
        cleaned_something = False

        product_choices = self.hass.data.get(DOMAIN, {}).get("product_choices", {})
        if product_choices:
            keys_to_remove = []
            for choice_key, choice_data in product_choices.items():
                choice_timestamp = choice_data.get("timestamp", 0)
                age_seconds = current_time - choice_timestamp
                if age_seconds > cleanup_threshold:
                    keys_to_remove.append(choice_key)

            for key in keys_to_remove:
                del product_choices[key]
                cleaned_something = True

        recent_choices = self.hass.data.get(DOMAIN, {}).get(
            "recent_multiple_choices", {}
        )
        if recent_choices:
            keys_to_remove = []
            for choice_key, choice_data in recent_choices.items():
                choice_timestamp = choice_data.get("timestamp", 0)
                age_seconds = current_time - choice_timestamp
                if age_seconds > cleanup_threshold:
                    keys_to_remove.append(choice_key)

            for key in keys_to_remove:
                del recent_choices[key]
                cleaned_something = True

        voice_responses = self.hass.data.get(DOMAIN, {}).get("voice_responses", {})
        if voice_responses:
            keys_to_remove = []
            for response_key, response_data in voice_responses.items():
                response_timestamp = response_data.get("timestamp", 0)
                age_seconds = current_time - response_timestamp
                if age_seconds > cleanup_threshold:
                    keys_to_remove.append(response_key)

            for key in keys_to_remove:
                del voice_responses[key]
                cleaned_something = True

        if cleaned_something:
            from homeassistant.helpers.dispatcher import async_dispatcher_send

            async_dispatcher_send(self.hass, "grocy_multiple_choices_updated")

    async def retrieve_data(self, force=False):

        await self._cleanup_orphaned_choices()

        try:
            paused = is_update_paused(self.hass)

            if not paused:
                data = await self.api.retrieve_data(force)

                if data is not None:
                    self.last_successful_fetch = self.hass.loop.time()
                    self.data = data
                    homeassistant_products = self.data.get("homeassistant_products", {})
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
        except Exception as e:
            LOGGER.exception(
                "Unexpected error while fetching data from Grocy API: %s", e
            )
