import logging
import re
import uuid
from typing import Any, Dict, Optional

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .analysis_const import (
    ANALYSIS_SCHEMA,
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
from .services import async_create_restart_repair_issue

_LOGGER = logging.getLogger(__name__)


async def _create_restart_repair_issue(hass, notification_key: str) -> None:
    """Create a restart required repair issue."""

    context_map = {
        "restart_required_setup": "setup",
        "restart_required_settings": "settings",
        "restart_required_analysis": "analysis",
    }

    context = context_map.get(notification_key, "setup")

    try:
        await async_create_restart_repair_issue(hass, context)
    except Exception as e:
        _LOGGER.error("Failed to create restart repair issue: %s", e)


class ShoppingListWithGrocyOptionsConfigFlow(config_entries.OptionsFlow):  # type: ignore
    """Handle option configuration via Integrations page."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options or config_entry.data)

        if CONF_ANALYSIS_SETTINGS not in self.options:
            self.options[CONF_ANALYSIS_SETTINGS] = {
                CONF_CONSUMPTION_WEIGHT: DEFAULT_CONSUMPTION_WEIGHT,
                CONF_FREQUENCY_WEIGHT: DEFAULT_FREQUENCY_WEIGHT,
                CONF_SEASONAL_WEIGHT: DEFAULT_SEASONAL_WEIGHT,
                CONF_SCORE_THRESHOLD: DEFAULT_SCORE_THRESHOLD,
            }
        self._data = {"unique_id": self.options.get("unique_id")}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        self._errors = {}

        if user_input is not None:
            if user_input.get("show_advanced", False):
                if not is_valid_url(user_input.get("api_url", "")):
                    self._errors["base"] = "invalid_api_url"
                else:
                    self.options.update(
                        {
                            "api_url": user_input["api_url"],
                            "api_key": user_input["api_key"],
                            "verify_ssl": user_input.get("verify_ssl", True),
                            "disable_timeout": user_input.get("disable_timeout", False),
                            "image_download_size": user_input.get(
                                "image_download_size", 100
                            ),
                        }
                    )
                    return await self.async_step_advanced()

            if not is_valid_url(user_input.get("api_url", "")):
                self._errors["base"] = "invalid_api_url"

            if not self._errors:
                updated_data = {
                    "api_url": user_input["api_url"],
                    "api_key": user_input["api_key"],
                    "verify_ssl": user_input.get("verify_ssl", True),
                    "disable_timeout": user_input.get("disable_timeout", False),
                    "image_download_size": user_input.get("image_download_size", 100),
                    "enable_bidirectional_sync": user_input.get(
                        "enable_bidirectional_sync", False
                    ),
                    "unique_id": self.options.get("unique_id"),
                    CONF_ANALYSIS_SETTINGS: self.options.get(
                        CONF_ANALYSIS_SETTINGS,
                        {
                            CONF_CONSUMPTION_WEIGHT: DEFAULT_CONSUMPTION_WEIGHT,
                            CONF_FREQUENCY_WEIGHT: DEFAULT_FREQUENCY_WEIGHT,
                            CONF_SEASONAL_WEIGHT: DEFAULT_SEASONAL_WEIGHT,
                            CONF_SCORE_THRESHOLD: DEFAULT_SCORE_THRESHOLD,
                        },
                    ),
                }

                old_api_url = self.options.get("api_url")
                old_api_key = self.options.get("api_key")
                old_bidirectional_sync = self.options.get(
                    "enable_bidirectional_sync", False
                )
                old_disable_timeout = self.options.get("disable_timeout", False)
                old_image_size = self.options.get("image_download_size", 100)

                settings_changed = (
                    old_api_url
                    and old_api_key
                    and (
                        old_api_url != user_input["api_url"]
                        or old_api_key != user_input["api_key"]
                        or old_bidirectional_sync
                        != user_input.get("enable_bidirectional_sync", False)
                        or old_disable_timeout
                        != user_input.get("disable_timeout", False)
                        or old_image_size != user_input.get("image_download_size", 100)
                    )
                )
                first_time_setup = not (old_api_url and old_api_key)

                if settings_changed or first_time_setup:
                    notification_key = (
                        "restart_required_setup"
                        if first_time_setup
                        else "restart_required_settings"
                    )
                    await _create_restart_repair_issue(self.hass, notification_key)

                return self.async_create_entry(title="", data=updated_data)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "api_url", default=self.options.get("api_url", "")
                    ): str,
                    vol.Required(
                        "verify_ssl", default=self.options.get("verify_ssl", True)
                    ): bool,
                    vol.Required(
                        "api_key", default=self.options.get("api_key", "")
                    ): str,
                    vol.Optional(
                        "disable_timeout",
                        default=self.options.get("disable_timeout", False),
                    ): bool,
                    vol.Optional(
                        "image_download_size",
                        default=self.options.get("image_download_size", 100),
                    ): vol.All(vol.Coerce(int), vol.In([0, 50, 100, 150, 200])),
                    vol.Optional(
                        "enable_bidirectional_sync",
                        default=self.options.get("enable_bidirectional_sync", False),
                    ): bool,
                    vol.Optional("show_advanced", default=False): bool,
                }
            ),
            errors=self._errors,
            description_placeholders={
                "disclaimer": "ℹ️ The shopping suggestions work great with default settings. Only access advanced settings if you need to fine-tune the algorithm."
            },
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle advanced settings with disclaimer."""
        self._errors = {}
        current_settings = self.options.get(CONF_ANALYSIS_SETTINGS, {})

        if user_input is not None:
            try:
                analysis_settings = {
                    CONF_CONSUMPTION_WEIGHT: user_input.get(
                        CONF_CONSUMPTION_WEIGHT, DEFAULT_CONSUMPTION_WEIGHT
                    ),
                    CONF_FREQUENCY_WEIGHT: user_input.get(
                        CONF_FREQUENCY_WEIGHT, DEFAULT_FREQUENCY_WEIGHT
                    ),
                    CONF_SEASONAL_WEIGHT: user_input.get(
                        CONF_SEASONAL_WEIGHT, DEFAULT_SEASONAL_WEIGHT
                    ),
                    CONF_SCORE_THRESHOLD: user_input.get(
                        CONF_SCORE_THRESHOLD, DEFAULT_SCORE_THRESHOLD
                    ),
                }

                analysis_settings = ANALYSIS_SCHEMA(analysis_settings)
                total_weight = (
                    analysis_settings[CONF_CONSUMPTION_WEIGHT]
                    + analysis_settings[CONF_FREQUENCY_WEIGHT]
                    + analysis_settings[CONF_SEASONAL_WEIGHT]
                )
                if not 0.99 <= total_weight <= 1.01:
                    self._errors["base"] = "weight_sum_error"
            except vol.Invalid:
                self._errors["base"] = "invalid_analysis_settings"

            if not self._errors:
                updated_data = dict(self.options)
                updated_data[CONF_ANALYSIS_SETTINGS] = analysis_settings

                old_settings = self.options.get(CONF_ANALYSIS_SETTINGS, {})
                if old_settings != analysis_settings:
                    await _create_restart_repair_issue(
                        self.hass, "restart_required_analysis"
                    )

                return self.async_create_entry(title="", data=updated_data)

        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCORE_THRESHOLD,
                        default=current_settings.get(
                            CONF_SCORE_THRESHOLD, DEFAULT_SCORE_THRESHOLD
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                    vol.Required(
                        CONF_CONSUMPTION_WEIGHT,
                        default=current_settings.get(
                            CONF_CONSUMPTION_WEIGHT, DEFAULT_CONSUMPTION_WEIGHT
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                    vol.Required(
                        CONF_FREQUENCY_WEIGHT,
                        default=current_settings.get(
                            CONF_FREQUENCY_WEIGHT, DEFAULT_FREQUENCY_WEIGHT
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                    vol.Required(
                        CONF_SEASONAL_WEIGHT,
                        default=current_settings.get(
                            CONF_SEASONAL_WEIGHT, DEFAULT_SEASONAL_WEIGHT
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                }
            ),
            errors=self._errors,
            description_placeholders={
                "warning": "⚠️ These settings control how shopping suggestions are calculated. Incorrect values may completely break the feature. We recommend leaving defaults unchanged unless you fully understand the algorithm. All weights must sum to 1.0."
            },
        )


@config_entries.HANDLERS.register(DOMAIN)
class ShoppingListWithGrocyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 8
    DOMAIN = DOMAIN
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        self._errors = {}
        self._data = {"unique_id": str(uuid.uuid4())}

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ):
        return ShoppingListWithGrocyOptionsConfigFlow(config_entry)

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return logging.getLogger(__name__)

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            if not is_valid_url(user_input["api_url"]):
                self._errors["base"] = "invalid_api_url"
            if not self._errors:
                self._data.update(user_input)

                await _create_restart_repair_issue(self.hass, "restart_required_setup")

                return self.async_create_entry(
                    title="ShoppingListWithGrocy", data=self._data
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("api_url"): cv.string,
                    vol.Required("verify_ssl", default=True): cv.boolean,
                    vol.Required("api_key"): cv.string,
                    vol.Optional("disable_timeout", default=False): cv.boolean,
                    vol.Optional("image_download_size", default=100): vol.All(
                        cv.positive_int, vol.In([0, 50, 100, 150, 200])
                    ),
                }
            ),
            errors=self._errors,
        )


def is_valid_url(url):
    regex = re.compile(
        r"^https?://"  # http:// or https://
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,}(?:\.[A-Z]{2,})?|"
        r"localhost|"  # localhost
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # IP address
        r"(?::\d+)?"  # Optional port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )
    return url is not None and regex.search(url)
