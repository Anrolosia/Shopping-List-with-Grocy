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

    elif notification_type in [
        "choice_success",
        "no_choices",
        "invalid_choice",
        "multiple_matches",
    ]:
        choice_strings = notifications.get(notification_type, {})

        if choice_strings:
            return choice_strings

        fallbacks = {
            "choice_success": {
                "title": "✅ Product Selected",
                "message": "Choice {choice_number}: {product_name} added to your shopping list!",
            },
            "no_choices": {
                "title": "❌ No Choices Available",
                "message": "Product choices have expired. Please make a new voice search.",
            },
            "invalid_choice": {
                "title": "❌ Invalid Choice",
                "message": "Choice {choice_number} is invalid. Please select between 1 and {max_choices}.",
            },
            "multiple_matches": {
                "title": "🔍 Multiple Options Found",
                "message": "Multiple products found for '{product_name}':\n\n{choices_list}\n\nUse the shopping_list_with_grocy.select_choice_by_number service with your choice number.",
            },
        }

        return fallbacks.get(
            notification_type,
            {
                "title": "Shopping List with Grocy",
                "message": "Notification from Shopping List with Grocy integration.",
            },
        )

    return {
        "title": "Shopping List with Grocy",
        "message": "Notification from Shopping List with Grocy integration.",
    }


def get_todo_strings(translations: Dict[str, Any], todo_key: str) -> str:
    """Get todo strings from frontend translations with fallbacks."""

    todo_section = translations.get("todo", {})

    if todo_key in todo_section:
        return todo_section[todo_key]

    fallbacks = {
        "product_selected_title": "✅ Product Selected",
        "product_added": "Choice {choice}: {product} added to your shopping list!",
        "multiple_choice_title": "Multiple choices for '{term}'",
        "multiple_choice_message": "Multiple products match your request:\n\n{options}\n\n📋 To add, go to Developer Tools → Services and copy-paste:\n\n{yaml}",
    }

    return fallbacks.get(todo_key, f"Todo: {todo_key}")


def get_voice_response(translations: Dict[str, Any], voice_key: str) -> str:
    """Get voice response strings from frontend translations with fallbacks."""

    voice_section = translations.get("voice_responses", {})

    if voice_key in voice_section:
        return voice_section[voice_key]

    fallbacks = {
        "no_choices": "No choices available. Previous choices have expired, please make a new search.",
        "invalid_choice": "Choice {choice_number} is invalid. Available choices range from 1 to {max_choices}. Please repeat your choice.",
        "product_added": "{product_name} added to your shopping list!",
        "selection_error": "Error selecting choice {choice_number}. Please try again.",
        "add_error": "Error adding {product_name}.",
        "no_product_name": "I didn't understand the product name.",
        "multiple_choices_detailed": "Multiple products found for {product_name}. Your options are:\n{choices_list}.\nSay 'choice' followed by the number of your choice.",
        "multiple_choices_simple": "Multiple choices found for {product_name}, check the app.",
        "product_success": "{product_name} added to your shopping list!",
        "product_error": "Error adding {product_name}",
        "multiple_choices_voice": "I found {count} choices for {product_name}: {choices_text}. Say the number of your choice, for example 'Choice 2'.",
        "create_new_product": "🆕 Create '{product_name}' as new product",
        "product_created": "✅ {product_name} created and added to your shopping list!",
        "choice_number": "number",
    }

    return fallbacks.get(voice_key, f"Voice response: {voice_key}")
