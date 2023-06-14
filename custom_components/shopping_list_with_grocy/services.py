import logging

import voluptuous as vol
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    SERVICE_ADD,
    SERVICE_ATTR_NOTE,
    SERVICE_ATTR_PRODUCT_ID,
    SERVICE_ATTR_SHOPPING_LIST_ID,
    SERVICE_NOTE,
    SERVICE_REFRESH,
    SERVICE_REMOVE,
)

LOGGER = logging.getLogger(__name__)


REFRESH_SCHEMA = vol.Schema({})

ADD_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICE_ATTR_PRODUCT_ID): cv.string,
        vol.Required(SERVICE_ATTR_SHOPPING_LIST_ID, default=1): cv.positive_int,
        vol.Required(SERVICE_ATTR_NOTE, default=""): cv.string,
    }
)

REMOVE_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICE_ATTR_PRODUCT_ID): cv.string,
        vol.Required(SERVICE_ATTR_SHOPPING_LIST_ID, default=1): cv.positive_int,
    }
)

NOTE_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICE_ATTR_PRODUCT_ID): cv.string,
        vol.Required(SERVICE_ATTR_SHOPPING_LIST_ID, default=1): cv.positive_int,
        vol.Required(SERVICE_ATTR_NOTE, default=""): cv.string,
    }
)


@callback
def async_setup_services(hass) -> None:
    """Set up services for shopping list with grocy integration."""

    async def async_call_shopping_list_with_grocy_service(service_call) -> None:
        """Call correct shopping list with grocy service."""
        service = service_call.service
        coordinator = hass.data[DOMAIN]["instances"]["coordinator"]
        data = service_call.data

        if service == SERVICE_REFRESH:
            await coordinator.request_update()

        if service == SERVICE_ADD:
            product_id = data.get(SERVICE_ATTR_PRODUCT_ID, "")
            note = data.get(SERVICE_ATTR_NOTE, "")
            shopping_list_id = data.get(SERVICE_ATTR_SHOPPING_LIST_ID, 1)
            await coordinator.add_product(product_id, shopping_list_id, note)

        if service == SERVICE_REMOVE:
            product_id = data.get(SERVICE_ATTR_PRODUCT_ID, "")
            shopping_list_id = data.get(SERVICE_ATTR_SHOPPING_LIST_ID, 1)
            await coordinator.remove_product(product_id, shopping_list_id)

        if service == SERVICE_NOTE:
            product_id = data.get(SERVICE_ATTR_PRODUCT_ID, "")
            note = data.get(SERVICE_ATTR_NOTE, "")
            shopping_list_id = data.get(SERVICE_ATTR_SHOPPING_LIST_ID, 1)
            await coordinator.update_note(product_id, shopping_list_id, note)

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        async_call_shopping_list_with_grocy_service,
        schema=REFRESH_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD,
        async_call_shopping_list_with_grocy_service,
        schema=ADD_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE,
        async_call_shopping_list_with_grocy_service,
        schema=REMOVE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_NOTE,
        async_call_shopping_list_with_grocy_service,
        schema=NOTE_SCHEMA,
    )


@callback
def async_unload_services(hass) -> None:
    """Unload shopping list with grocy services."""
    hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
    hass.services.async_remove(DOMAIN, SERVICE_ADD)
    hass.services.async_remove(DOMAIN, SERVICE_REMOVE)
    hass.services.async_remove(DOMAIN, SERVICE_NOTE)
