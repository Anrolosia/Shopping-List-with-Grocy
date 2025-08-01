"""Support for Grocy shopping suggestions."""

import logging
import os
import time

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.core import HomeAssistant

from ..const import DOMAIN

LOGGER = logging.getLogger(__name__)

FRONTEND_PATH = os.path.join(os.path.dirname(__file__), "www")

PANEL_NAME = "grocy-shopping-suggestions"
PANEL_ICON = "mdi:cart"


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Set up the Grocy shopping suggestions frontend."""

    static_url_path = f"/{DOMAIN}"
    panel_url_path = PANEL_NAME

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                url_path=f"{static_url_path}/suggestion-card.js",
                path=os.path.join(FRONTEND_PATH, "suggestion-card.js"),
                cache_headers=False,
            ),
            StaticPathConfig(
                url_path=f"{static_url_path}/translations",
                path=os.path.join(FRONTEND_PATH, "translations"),
                cache_headers=False,
            ),
            StaticPathConfig(
                url_path=static_url_path,
                path=FRONTEND_PATH,
                cache_headers=False,
            ),
        ]
    )

    if PANEL_NAME not in hass.data.get(DOMAIN, {}).get("panels", []):
        try:
            module_url = f"{static_url_path}/suggestion-card.js?t={int(time.time())}"

            language = hass.config.language
            sidebar_title_translations = {
                "fr": "Suggestions d'Achats",
                "en": "Shopping Suggestions",
                "es": "Sugerencias de compra",
            }
            sidebar_title = sidebar_title_translations.get(
                language, "Shopping Suggestions"
            )

            await async_register_panel(
                hass,
                webcomponent_name=PANEL_NAME,
                frontend_url_path=panel_url_path,
                sidebar_title=sidebar_title,
                sidebar_icon=PANEL_ICON,
                module_url=module_url,
                embed_iframe=False,
                require_admin=False,
            )

            if "panels" not in hass.data[DOMAIN]:
                hass.data[DOMAIN]["panels"] = []
            hass.data[DOMAIN]["panels"].append(PANEL_NAME)
        except Exception as e:
            LOGGER.error("Failed to register panel: %s", str(e))


async def async_unload_frontend(hass: HomeAssistant) -> None:
    """Unload the frontend panel."""
    if PANEL_NAME in hass.data.get(DOMAIN, {}).get("panels", []):
        hass.components.frontend.async_remove_panel(PANEL_NAME)
        hass.data[DOMAIN]["panels"].remove(PANEL_NAME)
