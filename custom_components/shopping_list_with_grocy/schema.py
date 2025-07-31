from datetime import datetime
from typing import Any, Dict

import pytz
import voluptuous as vol
from dateutil.tz import tzlocal
from homeassistant.helpers import config_validation as cv
from voluptuous import ALLOW_EXTRA, PREVENT_EXTRA, In, Optional, Required, Schema

from .analysis_const import (
    CONF_ANALYSIS_SETTINGS,
    CONF_CONSUMPTION_WEIGHT,
    CONF_FREQUENCY_WEIGHT,
    CONF_SCORE_THRESHOLD,
    CONF_SEASONAL_WEIGHT,
    DEFAULT_CONSUMPTION_WEIGHT,
    DEFAULT_FREQUENCY_WEIGHT,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_SEASONAL_WEIGHT,
)
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


ANALYSIS_SCHEMA = vol.Schema(
    {
        Optional(CONF_CONSUMPTION_WEIGHT, default=DEFAULT_CONSUMPTION_WEIGHT): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1)
        ),
        Optional(CONF_FREQUENCY_WEIGHT, default=DEFAULT_FREQUENCY_WEIGHT): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1)
        ),
        Optional(CONF_SEASONAL_WEIGHT, default=DEFAULT_SEASONAL_WEIGHT): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1)
        ),
        Optional(CONF_SCORE_THRESHOLD, default=DEFAULT_SCORE_THRESHOLD): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1)
        ),
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
