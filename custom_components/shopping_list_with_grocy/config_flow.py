"""Config flow for Trakt."""
import logging
import re
from typing import Any, Dict, Optional

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN


class ShoppingListWithGrocyOptionsConfigFlow(config_entries.OptionsFlow):  # type: ignore
    """Handle option configuration via Integrations page."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        if config_entry.options is None or len(config_entry.options) == 0:
            self.options = dict(config_entry.data)
        else:
            self.options = dict(config_entry.options)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict = {}

        if user_input is not None:
            if not is_valid_url(user_input["api_url"]):
                errors["base"] = "invalid_api_url"
            if errors == {}:
                self.user_input = user_input
                self.options = user_input
                return self.async_create_entry(
                    title="ShoppingListWithGrocy", data=self.options
                )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "api_url", default=self.options.get("api_url")
                    ): cv.string,
                    vol.Required(
                        "verify_ssl", default=self.options.get("verify_ssl", True)
                    ): cv.boolean,
                    vol.Required(
                        "api_key", default=self.options.get("api_key")
                    ): cv.string,
                    vol.Required(
                        "mqtt_server",
                        default=self.options.get("mqtt_server", "127.0.0.1"),
                    ): cv.string,
                    vol.Required(
                        "mqtt_port", default=self.options.get("mqtt_port", 1883)
                    ): vol.All(cv.port, vol.In([1883, 1884, 8883, 8884])),
                    vol.Required(
                        "mqtt_username", default=self.options.get("mqtt_username")
                    ): cv.string,
                    vol.Required(
                        "mqtt_password", default=self.options.get("mqtt_password")
                    ): cv.string,
                    vol.Optional(
                        "adding_products_in_sensor",
                        default=self.options.get("adding_products_in_sensor", False),
                    ): cv.boolean,
                }
            ),
            errors=errors,
        )


class ShoppingListWithGrocyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow to handle Trakt OAuth2 authentication."""

    VERSION = 1
    DOMAIN = DOMAIN
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ShoppingListWithGrocyOptionsConfigFlow:
        """Tell Home Assistant that this integration supports configuration options."""
        return ShoppingListWithGrocyOptionsConfigFlow(config_entry)

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return logging.getLogger(__name__)

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors: dict = {}

        # Only a single instance of the integration is allowed:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            if not is_valid_url(user_input["api_url"]):
                errors["base"] = "invalid_api_url"
            if errors == {}:
                self.user_input = user_input
                self.config = user_input
                return self.async_create_entry(
                    title="ShoppingListWithGrocy", data=self.config
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("api_url"): cv.string,
                    vol.Required("verify_ssl", default=True): cv.boolean,
                    vol.Required("api_key"): cv.string,
                    vol.Required("mqtt_server", default="127.0.0.1"): cv.string,
                    vol.Required("mqtt_port", default=1883): vol.All(
                        cv.port, vol.In([1883, 1884, 8883, 8884])
                    ),
                    vol.Required("mqtt_username"): cv.string,
                    vol.Required("mqtt_password"): cv.string,
                    vol.Optional(
                        "adding_products_in_sensor", default=False
                    ): cv.boolean,
                }
            ),
            errors=errors,
        )

    async def async_oauth_create_entry(self, data: dict) -> dict:
        """
        Create an entry for the flow.

        Ok to override if you want to fetch extra info or even add another step.
        """
        augmented_data = {**data, **self.user_input}
        return self.async_create_entry(
            title="ShoppingListWithGrocy", data=augmented_data
        )


def is_valid_url(url):
    regex = re.compile(
        r"^https?://"  # http:// or https://
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"  # domain...
        r"localhost|"  # localhost...
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
        r"(?::\d+)?"  # optional port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )

    return url is not None and regex.search(url)
