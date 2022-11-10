from datetime import datetime
from typing import Any, Dict

import pytz
from dateutil.tz import tzlocal
from homeassistant.helpers import config_validation as cv
from voluptuous import ALLOW_EXTRA, PREVENT_EXTRA, In, Required, Schema

from .const import DOMAIN


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


def domain_schema() -> Schema:
    return {
        DOMAIN: {
            Required("api_url", default=""): cv.string,
            Required("api_key", default=""): cv.string,
        }
    }


configuration_schema = dictionary_to_schema(domain_schema(), extra=ALLOW_EXTRA)
