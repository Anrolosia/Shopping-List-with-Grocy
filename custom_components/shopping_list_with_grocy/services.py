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
    SERVICE_SEARCH,
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

SEARCH_SCHEMA = vol.Schema(
    {
        vol.Required("search_term"): cv.string,
        vol.Optional("max_results", default=5): cv.positive_int,
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

    async def async_search_products_service(service_call) -> None:
        """Service to search for products in Grocy and return results for voice assistant."""
        search_term = service_call.data.get("search_term", "").strip()
        max_results = service_call.data.get("max_results", 5)
        
        if not search_term:
            LOGGER.error("Search term is required for product search")
            return

        try:
            # Get the Grocy API instance
            instances = hass.data.get(DOMAIN, {}).get("instances", {})
            api = instances.get("api")
            
            if not api:
                LOGGER.error("❌ API instance not found for product search")
                return

            # Search for products
            LOGGER.info("🔍 Searching for products matching: %s", search_term)
            search_results = await api.search_product_in_grocy(search_term)

            if search_results["found"]:
                matches = search_results["matches"][:max_results]
                
                # Create numbered list for voice response
                choices_text = []
                for i, match in enumerate(matches, 1):
                    choices_text.append(f"{i} - {match.get('name', 'Unknown')}")
                
                # Store results for potential number selection
                choice_key = f"search_{int(time.time())}"
                if "product_choices" not in hass.data.get(DOMAIN, {}):
                    hass.data[DOMAIN]["product_choices"] = {}
                
                hass.data[DOMAIN]["product_choices"][choice_key] = {
                    "original_name": search_term,
                    "matches": matches,
                    "timestamp": time.time(),
                    "quantity": 1,
                    "shopping_list_id": 1
                }
                
                # Create response data for automation
                response_data = {
                    "found": True,
                    "search_term": search_term,
                    "search_type": search_results["search_type"],
                    "choice_count": len(matches),
                    "choices_text": ", ".join(choices_text),
                    "choice_key": choice_key,
                    "matches": [{"id": m.get("id"), "name": m.get("name")} for m in matches]
                }
                
                LOGGER.info("✅ Found %d matches for '%s'", len(matches), search_term)
                
            else:
                # No matches found
                response_data = {
                    "found": False,
                    "search_term": search_term,
                    "search_type": search_results["search_type"],
                    "choice_count": 0,
                    "choices_text": "",
                    "choice_key": None,
                    "matches": []
                }
                
                LOGGER.info("❌ No matches found for '%s'", search_term)

            # Fire event with results for automations to catch
            hass.bus.async_fire(
                f"{DOMAIN}_product_search_result",
                response_data
            )

            # Also create a temporary sensor with the results
            hass.states.async_set(
                f"sensor.{DOMAIN}_last_search_result",
                "found" if response_data["found"] else "not_found",
                attributes=response_data
            )

        except Exception as e:
            LOGGER.error("Error searching for products: %s", e)
            # Fire error event
            hass.bus.async_fire(
                f"{DOMAIN}_product_search_result",
                {
                    "found": False,
                    "search_term": search_term,
                    "error": str(e),
                    "choice_count": 0,
                    "choices_text": "",
                    "choice_key": None,
                    "matches": []
                }
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
        
        LOGGER.error("🧪 Testing bidirectional sync functionality with product: '%s'", test_product_name)
        
        instances = hass.data.get(DOMAIN, {}).get("instances", {})
        api = instances.get("api")
        
        if not api:
            LOGGER.error("❌ API instance not found for bidirectional sync test")
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "❌ Test Failed",
                    "message": "API instance not found",
                    "notification_id": "grocy_sync_test_result",
                },
            )
            return
        
        try:
            LOGGER.error("🔍 Testing search for product: '%s'", test_product_name)
            
            original_sync_enabled = getattr(api, 'bidirectional_sync_enabled', False)
            original_sync_stopped = getattr(api, 'bidirectional_sync_stopped', False)
            
            api.bidirectional_sync_enabled = True
            api.bidirectional_sync_stopped = False
            
            result = await api.handle_ha_todo_item_creation(test_product_name, shopping_list_id)
            
            api.bidirectional_sync_enabled = original_sync_enabled
            api.bidirectional_sync_stopped = original_sync_stopped
            
            test_results = []
            
            if result["success"]:
                test_results.append("✅ Product handling: SUCCESS")
                test_results.append(f"   Product: {result.get('product_name', 'Unknown')}")
                test_results.append(f"   Quantity: {result.get('quantity', 'Unknown')}")
                test_results.append(f"   List ID: {result.get('shopping_list_id', 'Unknown')}")
                
                notification_message = f"Test successful! Product '{result.get('product_name')}' would be added to list {result.get('shopping_list_id')} with quantity {result.get('quantity')}."
                notification_title = "✅ Bidirectional Sync Test - SUCCESS"
                
            elif result["reason"] == "multiple_matches":
                test_results.append("⚠️ Multiple matches found (as expected)")
                test_results.append(f"   Search term: {result.get('search_term', 'Unknown')}")
                test_results.append(f"   Matches found: {len(result.get('matches', []))}")
                
                matches_info = []
                for match in result.get('matches', [])[:3]:  # Show first 3 matches
                    matches_info.append(f"• {match.get('name', 'Unknown')} (ID: {match.get('id', 'Unknown')})")
                
                notification_message = f"Multiple matches found for '{test_product_name}':\n" + "\n".join(matches_info)
                if len(result.get('matches', [])) > 3:
                    notification_message += f"\n... and {len(result.get('matches', [])) - 3} more"
                notification_title = "⚠️ Bidirectional Sync Test - Multiple Matches"
                
            else:
                test_results.append(f"❌ Test failed: {result.get('reason', 'Unknown error')}")
                notification_message = f"Test failed: {result.get('reason', 'Unknown error')}"
                notification_title = "❌ Bidirectional Sync Test - FAILED"
            
            test_results.append(f"📊 Current sync status: {'enabled' if original_sync_enabled else 'disabled'}")
            test_results.append(f"📊 Emergency stop status: {'stopped' if original_sync_stopped else 'running'}")
            
            LOGGER.error("🧪 Bidirectional sync test completed:")
            for result_line in test_results:
                LOGGER.error("   %s", result_line)
            
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": notification_title,
                    "message": notification_message + "\n\nCheck logs for detailed results.",
                    "notification_id": "grocy_sync_test_result",
                },
            )
            
        except Exception as e:
            LOGGER.error("❌ Bidirectional sync test failed: %s", e)
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "❌ Bidirectional Sync Test Failed",
                    "message": f"Test failed with error: {str(e)}",
                    "notification_id": "grocy_sync_test_result",
                },
            )

    async def async_emergency_stop_sync_service(service_call) -> None:
        """Emergency stop for bidirectional sync."""
        reason = service_call.data.get("reason", "Manual emergency stop")
        LOGGER.error("🛑 Emergency stop requested: %s", reason)
        
        instances = hass.data.get(DOMAIN, {}).get("instances", {})
        api = instances.get("api")
        
        if not api:
            LOGGER.error("❌ API instance not found for emergency stop")
            return
        
        api.stop_bidirectional_sync(reason)
        LOGGER.error("🛑 Bidirectional sync stopped via emergency service")

    async def async_restart_sync_service(service_call) -> None:
        """Restart bidirectional sync after emergency stop."""
        LOGGER.error("🔄 Restart sync requested")
        
        instances = hass.data.get(DOMAIN, {}).get("instances", {})
        api = instances.get("api")
        
        if not api:
            LOGGER.error("❌ API instance not found for restart")
            return
        
        api.restart_bidirectional_sync()
        LOGGER.error("🔄 Bidirectional sync restarted via service")

    async def async_choose_product_service(service_call) -> None:
        """Choose a product from multiple matches."""
        choice_key = service_call.data.get("choice_key")
        selected_product_id = service_call.data.get("product_id")
        
        if not choice_key or not selected_product_id:
            LOGGER.error("❌ Missing choice_key or product_id in choose_product service")
            return
        
        choices = hass.data.get(DOMAIN, {}).get("product_choices", {})
        choice_data = choices.get(choice_key)
        
        if not choice_data:
            LOGGER.error("❌ Choice data not found for key: %s", choice_key)
            return
        
        instances = hass.data.get(DOMAIN, {}).get("instances", {})
        api = instances.get("api")
        
        if not api:
            LOGGER.error("❌ API instance not found for product choice")
            return
        
        try:
            await api.add_product_to_grocy_shopping_list(
                selected_product_id,
                choice_data["quantity"],
                choice_data["shopping_list_id"]
            )
            
            del choices[choice_key]
            
            coordinator = instances.get("coordinator")
            if coordinator:
                await coordinator.async_refresh()
            
            LOGGER.error("✅ Product choice completed: ID %s", selected_product_id)
            
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "✅ Product Added",
                    "message": f"Selected product (ID: {selected_product_id}) added to shopping list.",
                    "notification_id": f"grocy_product_choice_completed_{int(time.time())}",
                },
            )
            
        except Exception as e:
            LOGGER.error("❌ Error processing product choice: %s", e)

    async def async_select_choice_by_number_service(service_call) -> None:
        """Select a product choice by number (1-5)."""
        choice_number = service_call.data.get("choice_number", 1)
        
        # Get all available choices
        choices = hass.data.get(DOMAIN, {}).get("product_choices", {})
        
        if not choices:
            LOGGER.error("❌ No product choices available")
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "❌ No Choices Available",
                    "message": "No product choices are currently available for selection.",
                    "notification_id": f"grocy_no_choices_{int(time.time())}",
                },
            )
            return
        
        # Get the most recent choice (latest timestamp)
        latest_choice_key = max(choices.keys(), key=lambda k: choices[k].get("timestamp", 0))
        choice_data = choices[latest_choice_key]
        
        matches = choice_data.get("matches", [])
        
        if choice_number < 1 or choice_number > len(matches):
            LOGGER.error("❌ Invalid choice number: %s (available: 1-%s)", choice_number, len(matches))
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "❌ Invalid Choice",
                    "message": f"Choice {choice_number} is invalid. Please select between 1 and {len(matches)}.",
                    "notification_id": f"grocy_invalid_choice_{int(time.time())}",
                },
            )
            return
        
        # Get the selected product (choice_number is 1-based, list is 0-based)
        selected_product = matches[choice_number - 1]
        selected_product_id = selected_product.get("id")
        product_name = selected_product.get("name", "Unknown Product")
        
        if not selected_product_id:
            LOGGER.error("❌ Product ID not found for choice %s", choice_number)
            return
        
        # Call the choose_product service directly
        try:
            await async_choose_product_service(type('ServiceCall', (), {
                'data': {
                    'choice_key': latest_choice_key,
                    'product_id': selected_product_id
                }
            })())
            
            LOGGER.error("✅ Choice %s selected: %s (ID: %s)", choice_number, product_name, selected_product_id)
            
            # Create a success notification
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "✅ Product Selected",
                    "message": f"Choice {choice_number}: {product_name} added to your shopping list!",
                    "notification_id": f"grocy_choice_success_{int(time.time())}",
                },
            )
            
        except Exception as e:
            LOGGER.error("❌ Error selecting choice %s: %s", choice_number, e)

    async def async_voice_add_product_service(service_call) -> None:
        """Add a product via voice with proper feedback for multiple choices."""
        product_name = service_call.data.get("product_name", "")
        shopping_list_id = service_call.data.get("shopping_list_id", 1)
        
        if not product_name:
            LOGGER.error("❌ No product name provided")
            return
        
        instances = hass.data.get(DOMAIN, {}).get("instances", {})
        api = instances.get("api")
        
        if not api:
            LOGGER.error("❌ API instance not found")
            return
        
        try:
            result = await api.handle_ha_todo_item_creation(product_name, shopping_list_id)
            
            # Fire an event with the result so blueprints can respond appropriately
            if result["success"]:
                hass.bus.async_fire("grocy_voice_product_added", {
                    "product_name": product_name,
                    "success": True,
                    "message": f"{product_name} ajouté à votre liste de courses"
                })
            elif result["reason"] == "multiple_matches":
                matches = result["matches"]
                choice_key = f"product_choice_{int(time.time())}"
                
                # Store choices
                if "product_choices" not in hass.data[DOMAIN]:
                    hass.data[DOMAIN]["product_choices"] = {}
                
                hass.data[DOMAIN]["product_choices"][choice_key] = {
                    "matches": matches,
                    "original_name": result["search_term"],
                    "quantity": result["quantity"],
                    "shopping_list_id": result["shopping_list_id"],
                    "timestamp": time.time(),
                }
                
                # Create notification
                service_options = []
                for i, match in enumerate(matches[:5], 1):
                    service_options.append(f"{i}. {match['name']} → product_id: {match['id']}")
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
                
                # Fire event for voice response
                hass.bus.async_fire("grocy_voice_multiple_choices", {
                    "product_name": product_name,
                    "matches_count": len(matches),
                    "choice_key": choice_key,
                    "message": f"J'ai trouvé {len(matches)} choix pour {product_name}. Consultez vos notifications puis dites le numéro de votre choix, par exemple 'Choix 2'."
                })
            else:
                hass.bus.async_fire("grocy_voice_product_error", {
                    "product_name": product_name,
                    "success": False,
                    "message": f"Erreur lors de l'ajout de {product_name}"
                })
                
        except Exception as e:
            LOGGER.error("❌ Error in voice add product: %s", e)
            hass.bus.async_fire("grocy_voice_product_error", {
                "product_name": product_name,
                "success": False,
                "message": f"Erreur lors de l'ajout de {product_name}"
            })

    TEST_BIDIRECTIONAL_SCHEMA = vol.Schema({
        vol.Optional("product_name", default="Test Product"): str,
        vol.Optional("shopping_list_id", default=1): int,
    })

    hass.services.async_register(
        DOMAIN,
        "test_bidirectional_sync",
        async_test_bidirectional_sync_service,
        schema=TEST_BIDIRECTIONAL_SCHEMA,
    )

    EMERGENCY_STOP_SCHEMA = vol.Schema({
        vol.Optional("reason", default="Manual emergency stop"): str,
    })

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

    CHOOSE_PRODUCT_SCHEMA = vol.Schema({
        vol.Required("choice_key"): str,
        vol.Required("product_id"): int,
    })

    hass.services.async_register(
        DOMAIN,
        "choose_product",
        async_choose_product_service,
        schema=CHOOSE_PRODUCT_SCHEMA,
    )

    SELECT_CHOICE_BY_NUMBER_SCHEMA = vol.Schema({
        vol.Required("choice_number"): int,
    })

    hass.services.async_register(
        DOMAIN,
        "select_choice_by_number",
        async_select_choice_by_number_service,
        schema=SELECT_CHOICE_BY_NUMBER_SCHEMA,
    )

    VOICE_ADD_PRODUCT_SCHEMA = vol.Schema({
        vol.Required("product_name"): str,
        vol.Optional("shopping_list_id", default=1): int,
    })

    hass.services.async_register(
        DOMAIN,
        "voice_add_product",
        async_voice_add_product_service,
        schema=VOICE_ADD_PRODUCT_SCHEMA,
    )

    async def async_list_product_choices_service(service_call) -> None:
        """List all available product choices for debugging."""
        choices = hass.data.get(DOMAIN, {}).get("product_choices", {})
        
        if not choices:
            message = "No product choices available."
        else:
            choice_list = []
            for choice_key, choice_data in choices.items():
                choice_list.append(f"Choice key: {choice_key}")
                choice_list.append(f"  Original name: {choice_data.get('original_name', 'Unknown')}")
                choice_list.append(f"  Quantity: {choice_data.get('quantity', 'Unknown')}")
                choice_list.append(f"  Shopping list: {choice_data.get('shopping_list_id', 'Unknown')}")
                matches = choice_data.get('matches', [])
                choice_list.append(f"  Available products:")
                for match in matches[:5]:
                    choice_list.append(f"    • {match.get('name', 'Unknown')} (ID: {match.get('id', 'Unknown')})")
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
        
        LOGGER.error("Available product choices: %s", choices.keys() if choices else "None")

    hass.services.async_register(
        DOMAIN,
        "list_product_choices",
        async_list_product_choices_service,
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
    hass.services.async_remove(DOMAIN, "voice_add_product")
    hass.services.async_remove(DOMAIN, "list_product_choices")
