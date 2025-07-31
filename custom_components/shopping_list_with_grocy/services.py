import logging
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
)
from .frontend_translations import (
    async_load_frontend_translations,
    get_notification_strings,
)
from .ml_engine import PurchasePredictionEngine

LOGGER = logging.getLogger(__name__)


async def async_create_restart_repair_issue(hass, context: str = "setup"):
    """Create a repair issue for restart requirement."""
    LOGGER.info("Creating restart repair issue with context: %s", context)

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

        LOGGER.info("Repair issue created successfully")
    except Exception as e:
        LOGGER.error("Failed to create repair issue: %s", e)
        raise


async def async_remove_restart_repair_issue(hass):
    """Remove the restart repair issue."""
    await async_delete_issue(hass, DOMAIN, "restart_required")


REFRESH_SCHEMA = vol.Schema({})

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

        LOGGER.debug("Processing product: %s", friendly_name)

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
                    LOGGER.debug(
                        "Skipping invalid history entry for %s: %s", entity_id, e
                    )
                    continue

        LOGGER.debug(
            "Found %d valid history entries for %s", len(history_list), friendly_name
        )

        if not history_list:
            LOGGER.warning("No valid history found for %s", entity_id)
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

    hass.services.async_register(
        DOMAIN,
        "suggest_grocery_list",
        async_suggest_grocery_list_service,
        schema=SUGGEST_GROCERY_SCHEMA,
    )

    async def async_reset_suggestions_service(service_call) -> None:
        """Reset shopping suggestions to analysis in progress state."""
        LOGGER.info("Manually resetting shopping suggestions")

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

        LOGGER.info("Shopping suggestions reset successfully")

    hass.services.async_register(
        DOMAIN,
        "reset_suggestions",
        async_reset_suggestions_service,
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
