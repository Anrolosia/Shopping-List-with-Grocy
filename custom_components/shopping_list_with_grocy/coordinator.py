"""Coordinator for the Shopping List with Grocy integration."""

import logging
import time
from datetime import timedelta

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .utils import is_update_paused

LOGGER = logging.getLogger(__name__)

# TTL for ephemeral voice/choice entries before they are garbage-collected.
_CHOICE_TTL_SECONDS = 2 * 60  # 2 minutes


def _purge_stale_keys(mapping: dict, threshold: float) -> bool:
    """Remove entries whose 'timestamp' is older than *threshold* seconds ago.

    Returns True if anything was removed.
    """
    now = time.time()
    stale = [k for k, v in mapping.items() if now - v.get("timestamp", 0) > threshold]
    for k in stale:
        del mapping[k]
    return bool(stale)


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
            LOGGER.error("❌ homeassistant_products is not a dictionary! Resetting.")
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

    async def cleanup_orphaned_choices(self) -> None:
        """Garbage-collect ephemeral voice/choice data older than TTL.

        Single authoritative implementation — services.py delegates here
        instead of duplicating the logic.
        """
        if DOMAIN not in self.hass.data:
            return

        domain = self.hass.data[DOMAIN]
        changed = False

        for bucket in ("product_choices", "recent_multiple_choices", "voice_responses"):
            mapping = domain.get(bucket, {})
            if mapping:
                changed |= _purge_stale_keys(mapping, _CHOICE_TTL_SECONDS)

        if changed:
            async_dispatcher_send(self.hass, "grocy_multiple_choices_updated")

    # Keep the old private name as an alias so existing callers inside this
    # file don't break while we migrate them.
    _cleanup_orphaned_choices = cleanup_orphaned_choices

    async def retrieve_data(self, force=False):
        """Fetch fresh data from Grocy if the DB has changed."""
        await self.cleanup_orphaned_choices()

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
                            new_attributes = product_data.get("attributes", {})

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
