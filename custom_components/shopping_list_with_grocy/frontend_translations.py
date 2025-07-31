import logging
import os
from typing import Any, Dict

from homeassistant.core import HomeAssistant
from homeassistant.util.json import load_json_object

LOGGER = logging.getLogger(__name__)

FRONTEND_TRANSLATIONS_PATH = os.path.join(
    os.path.dirname(__file__), "frontend", "www", "translations"
)


async def async_load_frontend_translations(
    hass: HomeAssistant, language: str
) -> Dict[str, Any]:
    """Load frontend translations for the specified language."""

    languages_to_try = [language, "en"] if language != "en" else ["en"]

    for lang in languages_to_try:
        translation_file = os.path.join(FRONTEND_TRANSLATIONS_PATH, f"{lang}.json")

        if os.path.exists(translation_file):
            try:
                translations = await hass.async_add_executor_job(
                    load_json_object, translation_file
                )
                return translations.get("shopping_list_with_grocy", {})
            except Exception as e:
                LOGGER.warning("Failed to load translations for %s: %s", lang, e)
                continue

    LOGGER.warning("No frontend translations could be loaded, using empty fallback")
    return {}


def get_notification_strings(
    translations: Dict[str, Any], notification_type: str, context: str = None
) -> Dict[str, str]:
    """Get notification strings from translations with fallbacks."""

    notifications = translations.get("notifications", {})

    if notification_type == "restart_required" and context:
        restart_messages = notifications.get("restart_required", {})
        context_strings = restart_messages.get(context, {})

        if context_strings:
            return context_strings

        fallbacks = {
            "setup": {
                "title": "Restart Required - Shopping List with Grocy",
                "message": "Please restart Home Assistant for the Shopping List with Grocy integration to work properly.\n\nYou can restart from Settings > System > Restart or use Developer Tools > YAML.",
            },
            "settings": {
                "title": "Restart Required - Shopping List with Grocy",
                "message": "Please restart Home Assistant for the API changes to take effect.\n\nYou can restart from Settings > System > Restart or use Developer Tools > YAML.",
            },
            "analysis": {
                "title": "Restart Required - Shopping List with Grocy",
                "message": "Please restart Home Assistant to apply the new analysis settings.\n\nYou can restart from Settings > System > Restart or use Developer Tools > YAML.",
            },
        }

        return fallbacks.get(context, fallbacks["setup"])

    elif notification_type == "suggestions":
        suggestion_strings = notifications.get("suggestions", {})

        if suggestion_strings:
            return suggestion_strings

        return {
            "title": "Grocy Shopping Suggestions",
            "card_hint": "New shopping suggestions are available! View them in the Shopping Suggestions dashboard panel.",
        }

    return {
        "title": "Shopping List with Grocy",
        "message": "Notification from Shopping List with Grocy integration.",
    }
