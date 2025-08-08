import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta

import homeassistant.helpers.entity_registry as er
import voluptuous as vol
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_registry import async_get
from homeassistant.helpers.issue_registry import async_create_issue, async_delete_issue

from .analysis_const import CONF_ANALYSIS_SETTINGS
from .const import (
    DOMAIN,
    ENTITY_VERSION,
    SERVICE_ADD,
    SERVICE_ATTR_NOTE,
    SERVICE_ATTR_PRODUCT_ID,
    SERVICE_ATTR_SHOPPING_LIST_ID,
    SERVICE_NOTE,
    SERVICE_REFRESH,
    SERVICE_REMOVE,
    SERVICE_SEARCH,
)
from .frontend_translations import (
    async_load_frontend_translations,
    get_notification_strings,
    get_voice_response,
)
from .ml_engine import PurchasePredictionEngine

LOGGER = logging.getLogger(__name__)


async def get_voice_translation(hass, voice_key: str, **kwargs) -> str:
    """Get voice response from frontend translations with formatting."""
    language = hass.config.language or "en"
    frontend_translations = await async_load_frontend_translations(hass, language)
    voice_template = get_voice_response(frontend_translations, voice_key)

    if kwargs:
        try:
            return voice_template.format(**kwargs)
        except (KeyError, ValueError):
            return voice_template
    return voice_template


def get_translation(hass, key: str, language: str = "en", **kwargs) -> str:
    """Get translated string - use frontend translations for voice_responses."""
    try:

        if key.startswith("voice_responses."):

            return key

        if not language or language == "en":
            ha_language = hass.config.language or "en"
        else:
            ha_language = language

        translation_file = os.path.join(
            os.path.dirname(__file__), "translations", f"{ha_language}.json"
        )

        if not os.path.exists(translation_file):

            translation_file = os.path.join(
                os.path.dirname(__file__), "translations", "en.json"
            )

        with open(translation_file, "r", encoding="utf-8") as f:
            translations = json.load(f)

        keys = key.split(".")
        value = translations
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:

                return key

        if isinstance(value, str) and kwargs:
            for placeholder, replacement in kwargs.items():
                value = value.replace(f"{{{placeholder}}}", str(replacement))

        return value

    except Exception as e:
        return key


async def async_force_todo_entities_refresh(hass):
    """Force TODO entities to update their attributes after cleanup."""
    from homeassistant.helpers import entity_registry

    er = entity_registry.async_get(hass)
    todo_entities = [
        entry
        for entry in er.entities.values()
        if entry.domain == "todo" and entry.platform == DOMAIN
    ]
    for entity_entry in todo_entities:
        entity = hass.states.get(entity_entry.entity_id)
        if entity:

            entity_obj = hass.data.get("entity_components", {}).get("todo")
            if entity_obj:
                for ent in entity_obj.entities:
                    if ent.entity_id == entity_entry.entity_id:
                        ent.async_write_ha_state()
                        break


async def async_create_restart_repair_issue(hass, context: str = "setup"):
    """Create a repair issue for restart requirement."""
    try:
        async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id="restart_required",
            is_fixable=True,
            severity="warning",
            translation_key="restart_required",
            translation_placeholders={"name": "Shopping List with Grocy"},
            learn_more_url="https://github.com/Anrolosia/Shopping-List-with-Grocy",
        )
    except Exception as e:
        LOGGER.error("Failed to create repair issue: %s", e)
        raise


async def async_remove_restart_repair_issue(hass):
    """Remove the restart repair issue."""
    await async_delete_issue(hass, DOMAIN, "restart_required")


REFRESH_SCHEMA = vol.Schema({})

SEARCH_SCHEMA = vol.Schema(
    {
        vol.Required("search_term"): cv.string,
        vol.Optional("max_results", default=5): cv.positive_int,
        vol.Optional("quantity", default=1): cv.positive_int,
        vol.Optional("shopping_list_id", default=1): cv.positive_int,
    }
)

ADD_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICE_ATTR_PRODUCT_ID): cv.string,
        vol.Required(SERVICE_ATTR_SHOPPING_LIST_ID, default=1): cv.positive_int,
        vol.Required(SERVICE_ATTR_NOTE, default=""): cv.string,
        vol.Optional("quantity", default=1): cv.positive_int,
        vol.Optional("disable_notification", default=False): cv.boolean,
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

SUGGEST_GROCERY_SCHEMA = vol.Schema(
    {
        vol.Optional("disable_notification", default=False): cv.boolean,
    }
)


async def async_suggest_grocery_list_service(call):
    """Service to suggest grocery items based on ML analysis."""
    hass = call.hass

    config_entry = hass.config_entries.async_entries(DOMAIN)[0]
    config = dict(config_entry.options)

    user_language = config_entry.data.get("language", hass.config.language)

    try:
        translations = await async_load_frontend_translations(hass, user_language)
        suggestion_strings = get_notification_strings(translations, "suggestions")
    except Exception as e:
        suggestion_strings = {
            "title": "Grocy Shopping Suggestions",
            "card_hint": "New shopping suggestions are available! View them in the Shopping Suggestions dashboard panel.",
        }

    analysis_settings = config.get(CONF_ANALYSIS_SETTINGS, {})

    prediction_engine = PurchasePredictionEngine(hass, analysis_settings)

    ent_reg = async_get(hass)

    product_entities = [
        entry.entity_id
        for entry in ent_reg.entities.values()
        if entry.domain == "sensor"
        and entry.platform == "shopping_list_with_grocy"
        and entry.unique_id.startswith(f"{DOMAIN}_product_v{ENTITY_VERSION}_")
    ]

    now = datetime.now()
    all_products = []

    for entity_id in product_entities:
        state = hass.states.get(entity_id)
        if not state:
            continue

        try:
            entity = ent_reg.entities.get(entity_id)
            if entity:
                friendly_name = entity.original_name
            else:
                friendly_name = None
        except (KeyError, AttributeError):
            friendly_name = None

        if not friendly_name:
            friendly_name = state.attributes.get("friendly_name", entity_id)

        history = await hass.async_add_executor_job(
            get_significant_states,
            hass,
            now - timedelta(days=60),
            now,
            [entity_id],
            None,
            None,
        )

        history_list = []
        if entity_id in history:
            for state_obj in history[entity_id]:
                try:
                    state_val = state_obj.state if hasattr(state_obj, "state") else "0"
                    last_changed = (
                        state_obj.last_changed
                        if hasattr(state_obj, "last_changed")
                        else None
                    )

                    if last_changed:
                        history_list.append(
                            {"state": state_val, "last_changed": last_changed}
                        )
                except Exception as e:
                    continue

        if not history_list:
            history_list = []

        analysis = await prediction_engine.analyze_purchase_patterns(
            entity_id, history_list, friendly_name
        )

        friendly_name = ent_reg.entities[entity_id].original_name
        if not friendly_name:
            friendly_name = state.attributes.get("friendly_name", entity_id)

        product_info = {
            "entity_id": entity_id,
            "friendly_name": friendly_name,
            "score": analysis["score"],
            "confidence": analysis["confidence"],
            "factors": analysis["factors"],
        }

        all_products.append(product_info)

    all_products.sort(key=lambda x: x["score"], reverse=True)

    suggested = []
    debug_info = []

    for product in all_products:
        analysis = {
            "score": product["score"],
            "confidence": product["confidence"],
            "factors": product["factors"],
        }
        if prediction_engine.should_suggest_purchase(analysis):
            suggested.append(product)

    if len(suggested) < 10:
        remaining_needed = 10 - len(suggested)
        additional_products = [p for p in all_products if p not in suggested][
            :remaining_needed
        ]
        suggested.extend(additional_products)

    for product in all_products:
        debug_info.append(
            f"{product['friendly_name']}:\n"
            f"  Score: {product['score']:.2f}\n"
            f"  Confidence: {product['confidence']:.2f}\n"
            f"  Factors: "
            + "\n    ".join(
                [f"{f['type']}: {f['description']}" for f in product["factors"]]
            )
        )

    filtered_products = [
        p for p in suggested if p["score"] >= prediction_engine.score_threshold
    ]
    filtered_products.sort(key=lambda x: x["score"], reverse=True)

    notification_title = suggestion_strings["title"]

    product_entries = []
    actions = []
    for i, product in enumerate(filtered_products):
        name_text = product["friendly_name"]
        score_text = (
            f"Score: {product['score']:.2f} (Confidence: {product['confidence']:.2f})"
        )
        product_entries.append(f"{name_text}\n{score_text}")

    if not call.data.get("disable_notification", False):
        notification_data = {
            "title": notification_title,
            "message": suggestion_strings["card_hint"].format(
                url="/grocy-shopping-suggestions"
            ),
            "notification_id": f"grocy_suggestions_{int(time.time())}",
        }
        await hass.services.async_call(
            "persistent_notification", "create", notification_data
        )

    if "suggestions" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["suggestions"] = {}

    suggestions_data = {
        "last_update": datetime.now().isoformat(),
        "products": [
            {
                "id": p["entity_id"],
                "name": p["friendly_name"],
                "score": p["score"],
                "confidence": p["confidence"],
            }
            for p in filtered_products
        ],
    }

    hass.data[DOMAIN]["suggestions"].update(suggestions_data)

    entity_id = "sensor.grocy_shopping_suggestions"
    hass.states.async_set(
        entity_id,
        len(filtered_products),
        {
            "suggestions": suggestions_data["products"],
            "last_update": suggestions_data["last_update"],
            "friendly_name": "Grocy Shopping Suggestions",
        },
    )


@callback
def async_setup_services(hass) -> None:
    """Set up services for shopping list with grocy integration."""

    async def async_cleanup_orphaned_choices() -> None:
        """Clean up orphaned product choices older than 2 minutes."""
        if DOMAIN not in hass.data:
            return

        current_time = time.time()
        cleanup_threshold = 2 * 60  # 2 minutes in seconds

        product_choices = hass.data.get(DOMAIN, {}).get("product_choices", {})
        if product_choices:
            keys_to_remove = []
            for choice_key, choice_data in product_choices.items():
                choice_timestamp = choice_data.get("timestamp", 0)
                if current_time - choice_timestamp > cleanup_threshold:
                    keys_to_remove.append(choice_key)

            for key in keys_to_remove:
                del product_choices[key]

        recent_choices = hass.data.get(DOMAIN, {}).get("recent_multiple_choices", {})
        if recent_choices:
            keys_to_remove = []
            for choice_key, choice_data in recent_choices.items():
                choice_timestamp = choice_data.get("timestamp", 0)
                if current_time - choice_timestamp > cleanup_threshold:
                    keys_to_remove.append(choice_key)

            for key in keys_to_remove:
                del recent_choices[key]

        voice_responses = hass.data.get(DOMAIN, {}).get("voice_responses", {})
        if voice_responses:
            keys_to_remove = []
            for response_key, response_data in voice_responses.items():
                response_timestamp = response_data.get("timestamp", 0)
                if current_time - response_timestamp > cleanup_threshold:
                    keys_to_remove.append(response_key)

            for key in keys_to_remove:
                del voice_responses[key]

    async def async_call_shopping_list_with_grocy_service(service_call) -> None:
        """Call correct shopping list with grocy service."""
        service = service_call.service
        coordinator = hass.data[DOMAIN]["instances"]["coordinator"]
        data = service_call.data

        if service == SERVICE_REFRESH:

            await async_cleanup_orphaned_choices()
            await coordinator.request_update()

        if service == SERVICE_ADD:
            product_id = data.get(SERVICE_ATTR_PRODUCT_ID, "")
            note = data.get(SERVICE_ATTR_NOTE, "")
            shopping_list_id = data.get(SERVICE_ATTR_SHOPPING_LIST_ID, 1)
            quantity = data.get("quantity", 1)
            await coordinator.add_product(product_id, shopping_list_id, note, quantity)

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

    hass.services.async_register(
        DOMAIN,
        "suggest_grocery_list",
        async_suggest_grocery_list_service,
        schema=SUGGEST_GROCERY_SCHEMA,
    )

    async def async_reset_suggestions_service(service_call) -> None:
        """Reset shopping suggestions to analysis in progress state."""
        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}
        hass.data[DOMAIN]["suggestions"] = {"products": [], "last_update": None}

        entity_id = "sensor.grocy_shopping_suggestions"
        hass.states.async_set(
            entity_id,
            0,
            {
                "suggestions": [],
                "last_update": None,
                "friendly_name": "Grocy Shopping Suggestions",
            },
        )

    hass.services.async_register(
        DOMAIN,
        "reset_suggestions",
        async_reset_suggestions_service,
        schema=vol.Schema({}),
    )

    async def async_search_products_service(service_call) -> None:
        """Service to search for products in Grocy and return results for voice assistant."""
        search_term = service_call.data.get("search_term", "").strip()
        max_results = service_call.data.get("max_results", 5)
        quantity = service_call.data.get("quantity", 1)
        shopping_list_id = service_call.data.get("shopping_list_id", 1)

        if not search_term:
            LOGGER.error("Search term is required for product search")
            return

        try:

            instances = hass.data.get(DOMAIN, {}).get("instances", {})
            api = instances.get("api")

            if not api:
                LOGGER.error("API instance not found for product search")
                return

            await async_cleanup_orphaned_choices()

            search_results = await api.search_product_in_grocy(search_term)

            if search_results["found"]:
                matches = search_results["matches"][:max_results]

                choices_text = []
                for i, match in enumerate(matches, 1):
                    choices_text.append(f"{i} - {match.get('name', 'Unknown')}")

                choice_key = f"search_{int(time.time())}"
                if "product_choices" not in hass.data.get(DOMAIN, {}):
                    hass.data[DOMAIN]["product_choices"] = {}

                hass.data[DOMAIN]["product_choices"][choice_key] = {
                    "original_name": search_term,
                    "matches": matches,
                    "timestamp": time.time(),
                    "quantity": quantity,
                    "shopping_list_id": shopping_list_id,
                }

                response_data = {
                    "found": True,
                    "search_term": search_term,
                    "search_type": search_results["search_type"],
                    "choice_count": len(matches),
                    "choices_text": ", ".join(choices_text),
                    "choice_key": choice_key,
                    "matches": [
                        {"id": m.get("id"), "name": m.get("name")} for m in matches
                    ],
                }
            else:

                response_data = {
                    "found": False,
                    "search_term": search_term,
                    "search_type": search_results["search_type"],
                    "choice_count": 0,
                    "choices_text": "",
                    "choice_key": None,
                    "matches": [],
                }

            hass.bus.async_fire(f"{DOMAIN}_product_search_result", response_data)

            hass.states.async_set(
                f"sensor.{DOMAIN}_last_search_result",
                "found" if response_data["found"] else "not_found",
                attributes=response_data,
            )

        except Exception as e:
            LOGGER.error("Error searching for products: %s", e)

            hass.bus.async_fire(
                f"{DOMAIN}_product_search_result",
                {
                    "found": False,
                    "search_term": search_term,
                    "error": str(e),
                    "choice_count": 0,
                    "choices_text": "",
                    "choice_key": None,
                    "matches": [],
                },
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEARCH,
        async_search_products_service,
        schema=SEARCH_SCHEMA,
    )

    async def async_test_bidirectional_sync_service(service_call) -> None:
        """Test bidirectional sync functionality without enabling it."""
        test_product_name = service_call.data.get("product_name", "Test Product")
        shopping_list_id = service_call.data.get("shopping_list_id", 1)

        instances = hass.data.get(DOMAIN, {}).get("instances", {})
        api = instances.get("api")

        if not api:
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Test Failed",
                    "message": "API instance not found",
                    "notification_id": "grocy_sync_test_result",
                },
            )
            return

        try:
            original_sync_enabled = getattr(api, "bidirectional_sync_enabled", False)
            original_sync_stopped = getattr(api, "bidirectional_sync_stopped", False)

            api.bidirectional_sync_enabled = True
            api.bidirectional_sync_stopped = False

            result = await api.handle_ha_todo_item_creation(
                test_product_name, shopping_list_id
            )

            api.bidirectional_sync_enabled = original_sync_enabled
            api.bidirectional_sync_stopped = original_sync_stopped

            test_results = []

            if result["success"]:
                test_results.append("Product handling: SUCCESS")
                test_results.append(
                    f"   Product: {result.get('product_name', 'Unknown')}"
                )
                test_results.append(f"   Quantity: {result.get('quantity', 'Unknown')}")
                test_results.append(
                    f"   List ID: {result.get('shopping_list_id', 'Unknown')}"
                )

                notification_message = f"Test successful! Product '{result.get('product_name')}' would be added to list {result.get('shopping_list_id')} with quantity {result.get('quantity')}."
                notification_title = "Bidirectional Sync Test - SUCCESS"

            elif result["reason"] == "multiple_matches":
                test_results.append("Multiple matches found (as expected)")
                test_results.append(
                    f"   Search term: {result.get('search_term', 'Unknown')}"
                )
                test_results.append(
                    f"   Matches found: {len(result.get('matches', []))}"
                )

                matches_info = []
                for match in result.get("matches", []):  # Show all matches
                    matches_info.append(
                        f"• {match.get('name', 'Unknown')} (ID: {match.get('id', 'Unknown')})"
                    )

                notification_message = (
                    f"Multiple matches found for '{test_product_name}':\n"
                    + "\n".join(matches_info)
                )
                notification_title = "Bidirectional Sync Test - Multiple Matches"

            else:
                test_results.append(
                    f"Test failed: {result.get('reason', 'Unknown error')}"
                )
                notification_message = (
                    f"Test failed: {result.get('reason', 'Unknown error')}"
                )
                notification_title = "Bidirectional Sync Test - FAILED"
            test_results.append(
                f"Current sync status: {'enabled' if original_sync_enabled else 'disabled'}"
            )
            test_results.append(
                f"Emergency stop status: {'stopped' if original_sync_stopped else 'running'}"
            )

            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": notification_title,
                    "message": notification_message
                    + "\n\nCheck logs for detailed results.",
                    "notification_id": "grocy_sync_test_result",
                },
            )

        except Exception as e:
            LOGGER.error("Bidirectional sync test failed: %s", e)
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Bidirectional Sync Test Failed",
                    "message": f"Test failed with error: {str(e)}",
                    "notification_id": "grocy_sync_test_result",
                },
            )

    async def async_emergency_stop_sync_service(service_call) -> None:
        """Emergency stop for bidirectional sync."""
        reason = service_call.data.get("reason", "Manual emergency stop")
        LOGGER.error("Emergency stop requested: %s", reason)

        instances = hass.data.get(DOMAIN, {}).get("instances", {})
        api = instances.get("api")

        if not api:
            return

        api.stop_bidirectional_sync(reason)
        LOGGER.error("Bidirectional sync stopped via emergency service")

    async def async_restart_sync_service(service_call) -> None:
        """Restart bidirectional sync after emergency stop."""
        LOGGER.error("Restart sync requested")

        instances = hass.data.get(DOMAIN, {}).get("instances", {})
        api = instances.get("api")

        if not api:
            return

        api.restart_bidirectional_sync()
        LOGGER.error("Bidirectional sync restarted via service")

    async def async_choose_product_service(service_call) -> None:
        """Choose a product from multiple matches."""
        choice_key = service_call.data.get("choice_key")
        selected_product_id = service_call.data.get("product_id")

        if not choice_key or not selected_product_id:
            LOGGER.error("Missing choice_key or product_id in choose_product service")
            return

        choices = hass.data.get(DOMAIN, {}).get("product_choices", {})
        choice_data = choices.get(choice_key)

        if not choice_data:
            LOGGER.error("Choice data not found for key: %s", choice_key)
            return

        instances = hass.data.get(DOMAIN, {}).get("instances", {})
        api = instances.get("api")

        if not api:
            LOGGER.error("API instance not found for product choice")
            return

        try:

            if selected_product_id == "create_new":
                original_product_name = choice_data.get("original_name", "Unknown")

                creation_result = await api.create_product_in_grocy(
                    original_product_name
                )

                if creation_result.get("success"):
                    new_product_id = creation_result.get("product_id")

                    await api.add_product_to_grocy_shopping_list(
                        new_product_id,
                        choice_data["quantity"],
                        choice_data["shopping_list_id"],
                    )
                else:
                    LOGGER.error(
                        "Failed to create new product: %s", original_product_name
                    )
                    return
            else:

                await api.add_product_to_grocy_shopping_list(
                    selected_product_id,
                    choice_data["quantity"],
                    choice_data["shopping_list_id"],
                )

            del choices[choice_key]

            recent_choices = hass.data.get(DOMAIN, {}).get(
                "recent_multiple_choices", {}
            )
            keys_to_remove = []
            for key, value in recent_choices.items():
                if value.get("choice_key") == choice_key:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                del recent_choices[key]

            coordinator = instances.get("coordinator")
            if coordinator:
                await coordinator.async_refresh()

            await async_force_todo_entities_refresh(hass)

        except Exception as e:
            LOGGER.error("Error processing product choice: %s", e)

    async def async_select_choice_by_number_service(service_call) -> None:
        """Select a product choice by number (1-5)."""
        choice_number = service_call.data.get("choice_number", 1)
        silent = service_call.data.get(
            "silent", False
        )  # New parameter to suppress notifications

        if silent:
            if "voice_mode" not in hass.data.get(DOMAIN, {}):
                if DOMAIN not in hass.data:
                    hass.data[DOMAIN] = {}
                hass.data[DOMAIN]["voice_mode"] = True
            else:
                hass.data[DOMAIN]["voice_mode"] = True

        choices = hass.data.get(DOMAIN, {}).get("product_choices", {})

        if not choices:

            await async_cleanup_orphaned_choices()
            choices = hass.data.get(DOMAIN, {}).get("product_choices", {})

            await async_force_todo_entities_refresh(hass)

            if not choices:
                if silent:
                    voice_response = await get_voice_translation(hass, "no_choices")
                    hass.states.async_set(
                        "sensor.shopping_list_with_grocy_voice_response_helper",
                        "error",
                        {
                            "voice_response": voice_response,
                            "success": False,
                            "reason": "no_choices_available",
                            "choice_number": choice_number,
                            "timestamp": time.time(),
                        },
                    )

                    hass.bus.async_fire(
                        "grocy_voice_choice_result",
                        {
                            "success": False,
                            "reason": "no_choices_available",
                            "voice_response": voice_response,
                            "choice_number": choice_number,
                        },
                    )

                if not silent:
                    language = hass.config.language or "en"
                    frontend_translations = await async_load_frontend_translations(
                        hass, language
                    )
                    no_choice_strings = get_notification_strings(
                        frontend_translations, "no_choices"
                    )

                    await hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {
                            "title": no_choice_strings.get(
                                "title", "❌ No Choices Available"
                            ),
                            "message": no_choice_strings.get(
                                "message",
                                "Product choices have expired. Please make a new voice search.",
                            ),
                            "notification_id": f"grocy_no_choices_{int(time.time())}",
                        },
                    )
                return

        latest_choice_key = max(
            choices.keys(), key=lambda k: choices[k].get("timestamp", 0)
        )
        choice_data = choices[latest_choice_key]

        current_time = time.time()
        choice_age = current_time - choice_data.get("timestamp", 0)

        if choice_age > 120:  # 2 minutes = 120 seconds
            LOGGER.error(
                "Most recent choice has expired (%.1f minutes old), cleaning up",
                choice_age / 60,
            )

            await async_cleanup_orphaned_choices()

            await async_force_todo_entities_refresh(hass)

            choices = hass.data.get(DOMAIN, {}).get("product_choices", {})
            if not choices:
                if silent:
                    voice_response = await get_voice_translation(hass, "no_choices")
                    hass.states.async_set(
                        "sensor.shopping_list_with_grocy_voice_response_helper",
                        "error",
                        {
                            "voice_response": voice_response,
                            "success": False,
                            "reason": "no_choices_available",
                            "choice_number": choice_number,
                            "timestamp": time.time(),
                        },
                    )

                    hass.bus.async_fire(
                        "grocy_voice_choice_result",
                        {
                            "success": False,
                            "reason": "no_choices_available",
                            "voice_response": voice_response,
                            "choice_number": choice_number,
                        },
                    )

                if not silent:
                    language = hass.config.language or "en"
                    frontend_translations = await async_load_frontend_translations(
                        hass, language
                    )
                    no_choice_strings = get_notification_strings(
                        frontend_translations, "no_choices"
                    )

                    await hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {
                            "title": no_choice_strings.get(
                                "title", "❌ No Choices Available"
                            ),
                            "message": no_choice_strings.get(
                                "message",
                                "Product choices have expired. Please make a new voice search.",
                            ),
                            "notification_id": f"grocy_no_choices_{int(time.time())}",
                        },
                    )
                return

            latest_choice_key = max(
                choices.keys(), key=lambda k: choices[k].get("timestamp", 0)
            )
            choice_data = choices[latest_choice_key]

        matches = choice_data.get("matches", [])

        if choice_number < 1 or choice_number > len(matches):
            LOGGER.error(
                "Invalid choice number: %s (available: 1-%s)",
                choice_number,
                len(matches),
            )

            if silent:

                voice_response = await get_voice_translation(
                    hass,
                    "invalid_choice",
                    choice_number=choice_number,
                    max_choices=len(matches),
                )
                hass.states.async_set(
                    "sensor.shopping_list_with_grocy_voice_response_helper",
                    "error",
                    {
                        "voice_response": voice_response,
                        "success": False,
                        "reason": "invalid_choice_number",
                        "choice_number": choice_number,
                        "available_choices": len(matches),
                        "timestamp": time.time(),
                    },
                )

                hass.bus.async_fire(
                    "grocy_voice_choice_result",
                    {
                        "success": False,
                        "reason": "invalid_choice_number",
                        "voice_response": voice_response,
                        "choice_number": choice_number,
                        "available_choices": len(matches),
                    },
                )

            if not silent:
                language = hass.config.language or "en"
                frontend_translations = await async_load_frontend_translations(
                    hass, language
                )
                invalid_choice_strings = get_notification_strings(
                    frontend_translations, "invalid_choice"
                )

                title = invalid_choice_strings.get("title", "❌ Invalid Choice")
                message_template = invalid_choice_strings.get(
                    "message",
                    "Choice {choice_number} is invalid. Please select between 1 and {max_choices}.",
                )
                message = message_template.format(
                    choice_number=choice_number, max_choices=len(matches)
                )

                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": title,
                        "message": message,
                        "notification_id": f"grocy_invalid_choice_{int(time.time())}",
                    },
                )
            return

        selected_product = matches[choice_number - 1]
        selected_product_id = selected_product.get("id")

        if selected_product_id == "create_new":
            product_name = choice_data.get("original_name", "Unknown Product")
        else:
            product_name = selected_product.get("name", "Unknown Product")

        if not selected_product_id:
            LOGGER.error("Product ID not found for choice %s", choice_number)
            return

        choices = hass.data.get(DOMAIN, {}).get("product_choices", {})
        quantity = 1  # Default quantity
        if latest_choice_key in choices:
            quantity = choices[latest_choice_key].get("quantity", 1)

        try:
            await async_choose_product_service(
                type(
                    "ServiceCall",
                    (),
                    {
                        "data": {
                            "choice_key": latest_choice_key,
                            "product_id": selected_product_id,
                        }
                    },
                )()
            )

            if silent:

                if selected_product_id == "create_new":

                    voice_response = await get_voice_translation(
                        hass,
                        "product_created",
                        product_name=product_name,
                        quantity=quantity,
                    )
                else:

                    voice_response = await get_voice_translation(
                        hass,
                        "product_added",
                        product_name=product_name,
                        quantity=quantity,
                    )
                hass.states.async_set(
                    "sensor.shopping_list_with_grocy_voice_response_helper",
                    "success",
                    {
                        "voice_response": voice_response,
                        "success": True,
                        "reason": "choice_selected",
                        "choice_number": choice_number,
                        "product_name": product_name,
                        "product_id": selected_product_id,
                        "timestamp": time.time(),
                    },
                )

                hass.bus.async_fire(
                    "grocy_voice_choice_result",
                    {
                        "success": True,
                        "reason": "choice_selected",
                        "voice_response": voice_response,
                        "choice_number": choice_number,
                        "product_name": product_name,
                        "product_id": selected_product_id,
                        "is_created": selected_product_id == "create_new",
                    },
                )

            if not silent:
                language = hass.config.language or "en"
                frontend_translations = await async_load_frontend_translations(
                    hass, language
                )
                choice_success_strings = get_notification_strings(
                    frontend_translations, "choice_success"
                )

                title = choice_success_strings.get("title", "✅ Product Selected")
                message_template = choice_success_strings.get(
                    "message",
                    "Choice {choice_number}: {product_name} added to your shopping list!",
                )
                message = message_template.format(
                    choice_number=choice_number, product_name=product_name
                )

                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": title,
                        "message": message,
                        "notification_id": f"grocy_choice_success_{int(time.time())}",
                    },
                )

        except Exception as e:
            if silent:
                voice_response = await get_voice_translation(
                    hass, "selection_error", choice_number=choice_number
                )
                hass.states.async_set(
                    "sensor.shopping_list_with_grocy_voice_response_helper",
                    "error",
                    {
                        "voice_response": voice_response,
                        "success": False,
                        "reason": "selection_error",
                        "choice_number": choice_number,
                        "error": str(e),
                        "timestamp": time.time(),
                    },
                )

                hass.bus.async_fire(
                    "grocy_voice_choice_result",
                    {
                        "success": False,
                        "reason": "selection_error",
                        "voice_response": voice_response,
                        "choice_number": choice_number,
                        "error": str(e),
                    },
                )
        finally:
            if silent and DOMAIN in hass.data and "voice_mode" in hass.data[DOMAIN]:
                hass.data[DOMAIN]["voice_mode"] = False

    async def async_update_product_quantity_service(service_call) -> None:
        """Update the quantity of the most recently added product."""
        quantity = service_call.data.get("quantity", 1)

        recent_choices = hass.data.get(DOMAIN, {}).get("recent_multiple_choices", {})
        product_choices = hass.data.get(DOMAIN, {}).get("product_choices", {})

        if not recent_choices:
            return

        latest_timestamp = max(
            recent_choices.values(), key=lambda x: x.get("timestamp", 0)
        )
        latest_choice_key = None

        for key, value in recent_choices.items():
            if value.get("timestamp") == latest_timestamp.get("timestamp"):
                latest_choice_key = value.get("choice_key")
                break

        if not latest_choice_key or latest_choice_key not in product_choices:
            return

        choice_data = product_choices[latest_choice_key]
        selected_product_id = choice_data.get("selected_product_id")
        product_name = choice_data.get("selected_product_name", "Unknown Product")

        if not selected_product_id:
            return

        instances = hass.data.get(DOMAIN, {}).get("instances", {})
        api = instances.get("api")

        if not api:
            return

        try:

            await api.add_product_to_grocy_shopping_list(
                selected_product_id, quantity, 1, ""
            )

            if hasattr(api, "coordinator"):
                await api.coordinator.async_refresh()

        except Exception as e:
            LOGGER.error("Error updating quantity: %s", e)

    async def async_voice_add_product_with_response_service(service_call) -> None:
        """Add a product via voice with proper response handling for automations."""
        product_name = service_call.data.get("product_name", "")
        todo_entity_id = service_call.data.get(
            "todo_entity_id"
        )  # Get specific entity if provided

        if not product_name:
            voice_response = await get_voice_translation(hass, "no_product_name")
            hass.states.async_set(
                "sensor.shopping_list_with_grocy_voice_response_helper",
                "error",
                {
                    "product_name": product_name,
                    "voice_response": voice_response,
                    "success": False,
                    "reason": "no_product_name",
                    "timestamp": time.time(),
                },
            )
            await asyncio.sleep(0.5)
            hass.bus.async_fire(
                "grocy_voice_add_result",
                {
                    "success": False,
                    "product_name": product_name,
                    "reason": "no_product_name",
                    "voice_response": voice_response,
                },
            )
            return

        instances = hass.data.get(DOMAIN, {}).get("instances", {})
        api = instances.get("api")

        if not api:
            voice_response = await get_voice_translation(
                hass, "add_error", product_name=product_name
            )
            await asyncio.sleep(0.5)
            hass.bus.async_fire(
                "grocy_voice_add_result",
                {
                    "success": False,
                    "product_name": product_name,
                    "reason": "api_not_found",
                    "voice_response": voice_response,
                },
            )
            return

        try:
            if "voice_mode" not in hass.data.get(DOMAIN, {}):
                if DOMAIN not in hass.data:
                    hass.data[DOMAIN] = {}
                hass.data[DOMAIN]["voice_mode"] = True
            else:
                hass.data[DOMAIN]["voice_mode"] = True

            hass.states.async_set(
                "sensor.shopping_list_with_grocy_voice_response_helper",
                "processing",
                {
                    "product_name": product_name,
                    "voice_response": "",
                    "success": None,
                    "reason": "processing",
                    "timestamp": time.time(),
                },
            )

            if todo_entity_id:

                if (
                    todo_entity_id.startswith("todo.")
                    and "shopping_list_with_grocy" in todo_entity_id
                    and hass.states.get(todo_entity_id) is not None
                ):
                    todo_entity = todo_entity_id
                else:
                    voice_response = await get_voice_translation(
                        hass, "add_error", product_name=product_name
                    )
                    await asyncio.sleep(0.5)
                    hass.bus.async_fire(
                        "grocy_voice_add_result",
                        {
                            "success": False,
                            "product_name": product_name,
                            "reason": "invalid_todo_entity",
                            "voice_response": voice_response,
                        },
                    )
                    return
            else:

                todo_entities = [
                    entity_id
                    for entity_id in hass.states.async_entity_ids()
                    if entity_id.startswith("todo.")
                    and "shopping_list_with_grocy" in entity_id
                ]

                if not todo_entities:
                    voice_response = await get_voice_translation(
                        hass, "add_error", product_name=product_name
                    )
                    await asyncio.sleep(0.5)
                    hass.bus.async_fire(
                        "grocy_voice_add_result",
                        {
                            "success": False,
                            "product_name": product_name,
                            "reason": "no_todo_entity",
                            "voice_response": voice_response,
                        },
                    )
                    return

                todo_entity = todo_entities[0]  # Use the first todo entity

            try:

                await hass.services.async_call(
                    "todo",
                    "add_item",
                    {"item": product_name.strip()},
                    target={"entity_id": todo_entity},
                    blocking=True,  # Wait for completion
                )

                await asyncio.sleep(1.0)

                instances = hass.data.get(DOMAIN, {}).get("instances", {})
                api = instances.get("api")

                if api:
                    extracted_product_name, _ = api.extract_product_name_from_ha_item(
                        product_name
                    )
                    normalized_name = extracted_product_name.strip().lower()
                else:
                    normalized_name = product_name.strip().lower()

                recent_choices = hass.data.get(DOMAIN, {}).get(
                    "recent_multiple_choices", {}
                )

                if normalized_name in recent_choices:

                    choice_data = recent_choices[normalized_name]
                    choice_key = choice_data.get("choice_key", "")

                    if choice_key:
                        product_choices = hass.data.get(DOMAIN, {}).get(
                            "product_choices", {}
                        )
                        matches = product_choices.get(choice_key, {}).get("matches", [])

                        await async_cleanup_orphaned_choices()

                        quantity = 1  # Default quantity
                        clean_product_name = product_name  # Default to original name
                        if api:
                            clean_product_name, extracted_quantity = (
                                api.extract_product_name_from_ha_item(product_name)
                            )
                            quantity = extracted_quantity

                        if matches:

                            choice_number_text = await get_voice_translation(
                                hass, "choice_number"
                            )
                            voice_choices = []
                            for i, match in enumerate(matches, 1):
                                voice_choices.append(
                                    f"- {choice_number_text} {i}, {match['name']}"
                                )
                            voice_response = await get_voice_translation(
                                hass,
                                "multiple_choices_detailed",
                                product_name=clean_product_name,
                                quantity=quantity,
                                choices_list=chr(10).join(voice_choices),
                            )
                        else:
                            voice_response = await get_voice_translation(
                                hass,
                                "multiple_choices_simple",
                                product_name=clean_product_name,
                                quantity=quantity,
                            )
                    else:

                        quantity = 1  # Default quantity
                        clean_product_name = product_name  # Default to original name
                        if api:
                            clean_product_name, extracted_quantity = (
                                api.extract_product_name_from_ha_item(product_name)
                            )
                            quantity = extracted_quantity

                        voice_response = await get_voice_translation(
                            hass,
                            "multiple_choices_simple",
                            product_name=clean_product_name,
                            quantity=quantity,
                        )

                    if "voice_responses" not in hass.data.get(DOMAIN, {}):
                        hass.data[DOMAIN]["voice_responses"] = {}

                    response_key = f"voice_result_{int(time.time() * 1000)}"
                    hass.data[DOMAIN]["voice_responses"][response_key] = {
                        "success": False,
                        "product_name": product_name,
                        "reason": "multiple_choices",
                        "voice_response": voice_response,
                        "choice_key": choice_key,
                        "matches_count": len(matches) if matches else 0,
                        "timestamp": time.time(),
                    }

                    hass.bus.async_fire(
                        "grocy_voice_add_result",
                        {
                            "success": False,
                            "product_name": product_name,
                            "reason": "multiple_choices",
                            "voice_response": voice_response,
                            "choice_key": choice_key,
                            "matches_count": len(matches) if matches else 0,
                            "response_key": response_key,
                        },
                    )

                    hass.states.async_set(
                        "sensor.shopping_list_with_grocy_voice_response_helper",
                        "multiple_choices",
                        {
                            "product_name": product_name,
                            "voice_response": voice_response,
                            "success": False,
                            "reason": "multiple_choices",
                            "choice_key": choice_key,
                            "matches_count": len(matches) if matches else 0,
                            "timestamp": time.time(),
                        },
                    )
                else:
                    if "voice_responses" not in hass.data.get(DOMAIN, {}):
                        hass.data[DOMAIN]["voice_responses"] = {}

                    quantity = 1  # Default quantity
                    clean_product_name = product_name  # Default to original name
                    if api:
                        clean_product_name, extracted_quantity = (
                            api.extract_product_name_from_ha_item(product_name)
                        )
                        quantity = extracted_quantity

                    voice_response = await get_voice_translation(
                        hass,
                        "product_success",
                        product_name=clean_product_name,
                        quantity=quantity,
                    )
                    response_key = f"voice_result_{int(time.time() * 1000)}"
                    hass.data[DOMAIN]["voice_responses"][response_key] = {
                        "success": True,
                        "product_name": product_name,
                        "reason": "success",
                        "voice_response": voice_response,
                        "timestamp": time.time(),
                    }

                    hass.bus.async_fire(
                        "grocy_voice_add_result",
                        {
                            "success": True,
                            "product_name": product_name,
                            "reason": "success",
                            "voice_response": voice_response,
                            "response_key": response_key,
                        },
                    )

                    hass.states.async_set(
                        "sensor.shopping_list_with_grocy_voice_response_helper",
                        "success",
                        {
                            "product_name": product_name,
                            "voice_response": voice_response,
                            "success": True,
                            "reason": "success",
                            "timestamp": time.time(),
                        },
                    )

            except Exception as todo_exception:
                await asyncio.sleep(1.0)

                instances = hass.data.get(DOMAIN, {}).get("instances", {})
                api = instances.get("api")

                if api:
                    extracted_product_name, _ = api.extract_product_name_from_ha_item(
                        product_name
                    )
                    normalized_name = extracted_product_name.strip().lower()
                else:
                    normalized_name = product_name.strip().lower()

                recent_choices = hass.data.get(DOMAIN, {}).get(
                    "recent_multiple_choices", {}
                )

                if normalized_name in recent_choices:
                    choice_data = recent_choices[normalized_name]
                    choice_key = choice_data.get("choice_key", "")

                    if choice_key:
                        product_choices = hass.data.get(DOMAIN, {}).get(
                            "product_choices", {}
                        )
                        matches = product_choices.get(choice_key, {}).get("matches", [])

                        await async_cleanup_orphaned_choices()

                        quantity = 1  # Default quantity
                        clean_product_name = product_name  # Default to original name
                        if api:
                            clean_product_name, extracted_quantity = (
                                api.extract_product_name_from_ha_item(product_name)
                            )
                            quantity = extracted_quantity

                        if matches:
                            choice_number_text = await get_voice_translation(
                                hass, "choice_number"
                            )
                            voice_choices = []
                            for i, match in enumerate(matches, 1):
                                voice_choices.append(
                                    f"- {choice_number_text} {i}, {match['name']}"
                                )
                            voice_response = await get_voice_translation(
                                hass,
                                "multiple_choices_detailed",
                                product_name=clean_product_name,
                                quantity=quantity,
                                choices_list=chr(10).join(voice_choices),
                            )
                        else:
                            voice_response = await get_voice_translation(
                                hass,
                                "multiple_choices_simple",
                                product_name=clean_product_name,
                                quantity=quantity,
                            )
                    else:

                        quantity = 1  # Default quantity
                        clean_product_name = product_name  # Default to original name
                        if api:
                            clean_product_name, extracted_quantity = (
                                api.extract_product_name_from_ha_item(product_name)
                            )
                            quantity = extracted_quantity

                        voice_response = await get_voice_translation(
                            hass,
                            "multiple_choices_simple",
                            product_name=clean_product_name,
                            quantity=quantity,
                        )

                    await asyncio.sleep(0.5)

                    hass.bus.async_fire(
                        "grocy_voice_add_result",
                        {
                            "success": False,
                            "product_name": product_name,
                            "reason": "multiple_choices",
                            "voice_response": voice_response,
                            "choice_key": choice_key,
                            "matches_count": len(matches) if matches else 0,
                        },
                    )
                else:

                    voice_response = await get_voice_translation(
                        hass, "add_error", product_name=product_name
                    )
                    await asyncio.sleep(0.5)
                    hass.bus.async_fire(
                        "grocy_voice_add_result",
                        {
                            "success": False,
                            "product_name": product_name,
                            "reason": "error",
                            "voice_response": voice_response,
                        },
                    )

        except Exception as e:
            LOGGER.error("Error in voice add product with response: %s", e)
            voice_response = await get_voice_translation(
                hass, "add_error", product_name=product_name
            )
            await asyncio.sleep(0.5)
            hass.bus.async_fire(
                "grocy_voice_add_result",
                {
                    "success": False,
                    "product_name": product_name,
                    "reason": "general_error",
                    "voice_response": voice_response,
                },
            )
        finally:

            if DOMAIN in hass.data and "voice_mode" in hass.data[DOMAIN]:
                hass.data[DOMAIN]["voice_mode"] = False

    async def async_voice_add_product_service(service_call) -> None:
        """Add a product via voice with proper feedback for multiple choices."""
        product_name = service_call.data.get("product_name", "")
        shopping_list_id = service_call.data.get("shopping_list_id", 1)
        silent = service_call.data.get("silent", False)

        if not product_name:
            return

        instances = hass.data.get(DOMAIN, {}).get("instances", {})
        api = instances.get("api")

        if not api:
            return

        try:
            result = await api.handle_ha_todo_item_creation(
                product_name, shopping_list_id
            )

            if result["success"]:
                success_message = await get_voice_translation(
                    hass,
                    "product_added",
                    product_name=product_name,
                    quantity=result.get("quantity", 1),
                )
                hass.bus.async_fire(
                    "grocy_voice_product_added",
                    {
                        "product_name": product_name,
                        "success": True,
                        "message": success_message,
                    },
                )
            elif result["reason"] == "multiple_matches":
                matches = result["matches"]
                choice_key = f"product_choice_{int(time.time())}"

                if "product_choices" not in hass.data[DOMAIN]:
                    hass.data[DOMAIN]["product_choices"] = {}

                hass.data[DOMAIN]["product_choices"][choice_key] = {
                    "matches": matches,
                    "original_name": result["search_term"],
                    "quantity": result["quantity"],
                    "shopping_list_id": result["shopping_list_id"],
                    "timestamp": time.time(),
                }

                if not silent:
                    service_options = []
                    for i, match in enumerate(matches[:5], 1):
                        service_options.append(
                            f"{i}. {match['name']} → product_id: {match['id']}"
                        )
                    service_options_text = "\n".join(service_options)

                    await hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {
                            "title": "Multiple Products Found",
                            "message": f"Multiple products match '{result['search_term']}':\n\n{service_options_text}\n\n🎤 Say 'Choice 1', 'Choice 2', etc. to select",
                            "notification_id": f"grocy_multiple_matches_{int(time.time())}",
                        },
                    )

                voice_choices = []
                for i, match in enumerate(matches[:5], 1):
                    voice_choices.append(f"{i}. {match['name']}")
                voice_choices_text = ", ".join(voice_choices)

                voice_message = await get_voice_translation(
                    hass,
                    "multiple_choices_voice",
                    product_name=product_name,
                    count=len(matches),
                    choices_text=voice_choices_text,
                )

                hass.bus.async_fire(
                    "grocy_voice_multiple_choices",
                    {
                        "product_name": product_name,
                        "matches_count": len(matches),
                        "choice_key": choice_key,
                        "message": voice_message,
                    },
                )
            else:
                error_message = await get_voice_translation(
                    hass, "product_error", product_name=product_name
                )
                hass.bus.async_fire(
                    "grocy_voice_product_error",
                    {
                        "product_name": product_name,
                        "success": False,
                        "message": error_message,
                    },
                )

        except Exception as e:
            LOGGER.error("Error in voice add product: %s", e)
            error_message = await get_voice_translation(
                hass, "product_error", product_name=product_name
            )
            hass.bus.async_fire(
                "grocy_voice_product_error",
                {
                    "product_name": product_name,
                    "success": False,
                    "message": error_message,
                },
            )

    TEST_BIDIRECTIONAL_SCHEMA = vol.Schema(
        {
            vol.Optional("product_name", default="Test Product"): str,
            vol.Optional("shopping_list_id", default=1): int,
        }
    )

    hass.services.async_register(
        DOMAIN,
        "test_bidirectional_sync",
        async_test_bidirectional_sync_service,
        schema=TEST_BIDIRECTIONAL_SCHEMA,
    )

    EMERGENCY_STOP_SCHEMA = vol.Schema(
        {
            vol.Optional("reason", default="Manual emergency stop"): str,
        }
    )

    hass.services.async_register(
        DOMAIN,
        "emergency_stop_sync",
        async_emergency_stop_sync_service,
        schema=EMERGENCY_STOP_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        "restart_sync",
        async_restart_sync_service,
        schema=vol.Schema({}),
    )

    CHOOSE_PRODUCT_SCHEMA = vol.Schema(
        {
            vol.Required("choice_key"): str,
            vol.Required("product_id"): int,
        }
    )

    hass.services.async_register(
        DOMAIN,
        "choose_product",
        async_choose_product_service,
        schema=CHOOSE_PRODUCT_SCHEMA,
    )

    SELECT_CHOICE_BY_NUMBER_SCHEMA = vol.Schema(
        {
            vol.Required("choice_number"): int,
            vol.Optional("silent", default=False): bool,
        }
    )

    hass.services.async_register(
        DOMAIN,
        "select_choice_by_number",
        async_select_choice_by_number_service,
        schema=SELECT_CHOICE_BY_NUMBER_SCHEMA,
    )

    UPDATE_PRODUCT_QUANTITY_SCHEMA = vol.Schema(
        {
            vol.Required("quantity"): int,
        }
    )

    hass.services.async_register(
        DOMAIN,
        "update_product_quantity",
        async_update_product_quantity_service,
        schema=UPDATE_PRODUCT_QUANTITY_SCHEMA,
    )

    VOICE_ADD_PRODUCT_SCHEMA = vol.Schema(
        {
            vol.Required("product_name"): str,
            vol.Optional("shopping_list_id", default=1): int,
            vol.Optional("silent", default=False): bool,
        }
    )

    hass.services.async_register(
        DOMAIN,
        "voice_add_product",
        async_voice_add_product_service,
        schema=VOICE_ADD_PRODUCT_SCHEMA,
    )

    VOICE_ADD_PRODUCT_WITH_RESPONSE_SCHEMA = vol.Schema(
        {
            vol.Required("product_name"): str,
            vol.Optional("shopping_list_id", default=1): int,
            vol.Optional("todo_entity_id"): str,  # Allow specifying the todo entity
        }
    )

    hass.services.async_register(
        DOMAIN,
        "voice_add_product_with_response",
        async_voice_add_product_with_response_service,
        schema=VOICE_ADD_PRODUCT_WITH_RESPONSE_SCHEMA,
    )

    async def async_voice_select_choice_service(service_call) -> None:
        """Select a product choice by voice input - converts words to numbers automatically."""
        voice_input = service_call.data.get("voice_input", "")
        silent = service_call.data.get("silent", False)

        if not voice_input:
            if silent:
                voice_response = await get_voice_translation(hass, "no_choice_input")
                hass.states.async_set(
                    "sensor.shopping_list_with_grocy_voice_response_helper",
                    "error",
                    {
                        "voice_response": voice_response,
                        "success": False,
                        "reason": "no_voice_input",
                        "voice_input": voice_input,
                        "timestamp": time.time(),
                    },
                )
            return

        from .utils import convert_word_to_number

        choice_number = convert_word_to_number(voice_input)

        if choice_number is None:
            if silent:
                voice_response = await get_voice_translation(
                    hass, "invalid_voice_choice", voice_input=voice_input
                )
                hass.states.async_set(
                    "sensor.shopping_list_with_grocy_voice_response_helper",
                    "error",
                    {
                        "voice_response": voice_response,
                        "success": False,
                        "reason": "invalid_voice_input",
                        "voice_input": voice_input,
                        "timestamp": time.time(),
                    },
                )
            return

        await async_select_choice_by_number_service(
            type(
                "ServiceCall",
                (),
                {
                    "data": {
                        "choice_number": choice_number,
                        "silent": silent,
                    }
                },
            )()
        )

    VOICE_SELECT_CHOICE_SCHEMA = vol.Schema(
        {
            vol.Required("voice_input"): str,
            vol.Optional("silent", default=False): bool,
        }
    )

    hass.services.async_register(
        DOMAIN,
        "voice_select_choice",
        async_voice_select_choice_service,
        schema=VOICE_SELECT_CHOICE_SCHEMA,
    )

    async def async_list_product_choices_service(service_call) -> None:
        """List all available product choices for debugging."""

        await async_cleanup_orphaned_choices()

        choices = hass.data.get(DOMAIN, {}).get("product_choices", {})

        if not choices:
            message = "No product choices available."
        else:
            choice_list = []
            for choice_key, choice_data in choices.items():
                choice_list.append(f"Choice key: {choice_key}")
                choice_list.append(
                    f"  Original name: {choice_data.get('original_name', 'Unknown')}"
                )
                choice_list.append(
                    f"  Quantity: {choice_data.get('quantity', 'Unknown')}"
                )
                choice_list.append(
                    f"  Shopping list: {choice_data.get('shopping_list_id', 'Unknown')}"
                )
                matches = choice_data.get("matches", [])
                choice_list.append(f"  Available products:")
                for match in matches[:5]:
                    choice_list.append(
                        f"    • {match.get('name', 'Unknown')} (ID: {match.get('id', 'Unknown')})"
                    )
                choice_list.append("")

            message = "Available product choices:\n\n" + "\n".join(choice_list)

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Product Choices Debug",
                "message": message,
                "notification_id": f"grocy_choices_debug_{int(time.time())}",
            },
        )

    hass.services.async_register(
        DOMAIN,
        "list_product_choices",
        async_list_product_choices_service,
        schema=vol.Schema({}),
    )

    async def async_force_cleanup_service(service_call) -> None:
        """Force cleanup of orphaned choices for testing."""
        product_choices = hass.data.get(DOMAIN, {}).get("product_choices", {})
        recent_choices = hass.data.get(DOMAIN, {}).get("recent_multiple_choices", {})
        voice_responses = hass.data.get(DOMAIN, {}).get("voice_responses", {})

        current_time = time.time()
        for key, data in product_choices.items():
            timestamp = data.get("timestamp", 0)
            age_minutes = (current_time - timestamp) / 60

        for key, data in recent_choices.items():
            timestamp = data.get("timestamp", 0)
            age_minutes = (current_time - timestamp) / 60

        for key, data in voice_responses.items():
            timestamp = data.get("timestamp", 0)
            age_minutes = (current_time - timestamp) / 60

        await async_cleanup_orphaned_choices()

        product_choices_after = hass.data.get(DOMAIN, {}).get("product_choices", {})
        recent_choices_after = hass.data.get(DOMAIN, {}).get(
            "recent_multiple_choices", {}
        )
        voice_responses_after = hass.data.get(DOMAIN, {}).get("voice_responses", {})

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "🧪 Force Cleanup Test",
                "message": f"Cleanup executed!\n\nBefore: {len(product_choices)} product choices, {len(recent_choices)} recent choices, {len(voice_responses)} voice responses\n\nAfter: {len(product_choices_after)} product choices, {len(recent_choices_after)} recent choices, {len(voice_responses_after)} voice responses\n\nCheck logs for detailed timestamps.",
                "notification_id": f"grocy_force_cleanup_{int(time.time())}",
            },
        )

    hass.services.async_register(
        DOMAIN,
        "force_cleanup",
        async_force_cleanup_service,
        schema=vol.Schema({}),
    )


@callback
def async_unload_services(hass) -> None:
    """Unload shopping list with grocy services."""
    hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
    hass.services.async_remove(DOMAIN, SERVICE_ADD)
    hass.services.async_remove(DOMAIN, SERVICE_REMOVE)
    hass.services.async_remove(DOMAIN, SERVICE_NOTE)
    hass.services.async_remove(DOMAIN, "suggest_grocery_list")
    hass.services.async_remove(DOMAIN, "reset_suggestions")
    hass.services.async_remove(DOMAIN, "test_bidirectional_sync")
    hass.services.async_remove(DOMAIN, "emergency_stop_sync")
    hass.services.async_remove(DOMAIN, "restart_sync")
    hass.services.async_remove(DOMAIN, "choose_product")
    hass.services.async_remove(DOMAIN, "select_choice_by_number")
    hass.services.async_remove(DOMAIN, "update_product_quantity")
    hass.services.async_remove(DOMAIN, "voice_add_product")
    hass.services.async_remove(DOMAIN, "voice_add_product_with_response")
    hass.services.async_remove(DOMAIN, "list_product_choices")
    hass.services.async_remove(DOMAIN, "force_cleanup")
