import json
from datetime import datetime, timedelta
from math import ceil
from typing import Any, Dict, List, Tuple

from .const import DOMAIN


def update_domain_data(hass, key, content):
    if hass.data.get(DOMAIN) and hass.data[DOMAIN].get(key):
        hass.data[DOMAIN][key].update(content)
    else:
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][key] = content
