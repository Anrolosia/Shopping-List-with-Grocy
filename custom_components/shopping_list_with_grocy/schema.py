from typing import Any, Dict

import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from voluptuous import ALLOW_EXTRA, PREVENT_EXTRA, Optional, Required, Schema

from .const import (
    CONF_AUTO_SELECT_FIRST,
    CONF_PREFER_GENERIC_PRODUCTS,
    CONF_SUGGEST_CREATE_ONLY_NO_MATCH,
    DEFAULT_AUTO_SELECT_FIRST,
    DEFAULT_PREFER_GENERIC_PRODUCTS,
    DEFAULT_SUGGEST_CREATE_ONLY_NO_MATCH,
    DOMAIN,
)


def dictionary_to_schema(
    dictionary: Dict[str, Any],
    extra: str = PREVENT_EXTRA,
) -> Schema:
    return Schema(
        {
            key: dictionary_to_schema(value) if isinstance(value, dict) else value
            for key, value in dictionary.items()
        },
        extra=extra,
    )


SELECTION_CRITERIA_SCHEMA = vol.Schema(
    {
        Optional(
            CONF_PREFER_GENERIC_PRODUCTS, default=DEFAULT_PREFER_GENERIC_PRODUCTS
        ): vol.All(vol.Coerce(bool)),
        Optional(CONF_AUTO_SELECT_FIRST, default=DEFAULT_AUTO_SELECT_FIRST): vol.All(
            vol.Coerce(bool)
        ),
        Optional(
            CONF_SUGGEST_CREATE_ONLY_NO_MATCH,
            default=DEFAULT_SUGGEST_CREATE_ONLY_NO_MATCH,
        ): vol.All(vol.Coerce(bool)),
    }
)


def domain_schema() -> Schema:
    return {
        DOMAIN: {
            Required("api_url", default=""): cv.string,
            Required("api_key", default=""): cv.string,
        }
    }


configuration_schema = dictionary_to_schema(domain_schema(), extra=ALLOW_EXTRA)
