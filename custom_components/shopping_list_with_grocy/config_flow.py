import logging
import re
import uuid
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
        self._data = {}
        self._data["unique_id"] = self.options.get("unique_id")

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._errors = {}

        if user_input is not None:
            if not is_valid_url(user_input["api_url"]):
                self._errors["base"] = "invalid_api_url"
            if self._errors == {}:
                self._data.update(user_input)

                if user_input["mqtt_port"] > 1:
                    return self.async_create_entry(
                        title="ShoppingListWithGrocy", data=self._data
                    )

                return await self.async_step_mqtt_port()

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
                    ): vol.All(cv.port, vol.In([1883, 1884, 8883, 8884, 1])),
                    vol.Required(
                        "mqtt_username", default=self.options.get("mqtt_username")
                    ): cv.string,
                    vol.Required(
                        "mqtt_password", default=self.options.get("mqtt_password")
                    ): cv.string,
                    vol.Optional(
                        "image_download_size",
                        default=self.options.get("image_download_size", 100),
                    ): vol.All(cv.positive_int, vol.In([0, 50, 100, 150, 200])),
                    vol.Optional(
                        "adding_products_in_sensor",
                        default=self.options.get("adding_products_in_sensor", False),
                    ): cv.boolean,
                }
            ),
            errors=self._errors,
        )

    async def async_step_mqtt_port(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._errors = {}

        if user_input is not None:
            if self._errors == {}:
                self._data.update(user_input)
                return self.async_create_entry(
                    title="ShoppingListWithGrocy", data=self._data
                )

        return self.async_show_form(
            step_id="mqtt_port",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "mqtt_custom_port", default=self.options.get("mqtt_custom_port")
                    ): cv.port,
                }
            ),
            errors=self._errors,
        )


@config_entries.HANDLERS.register(DOMAIN)
class ShoppingListWithGrocyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 4
    DOMAIN = DOMAIN
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        self._errors = {}
        self._data = {}
        self._data["unique_id"] = str(uuid.uuid4())

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

        # Only a single instance of the integration is allowed:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            if not is_valid_url(user_input["api_url"]):
                self._errors["base"] = "invalid_api_url"
            if self._errors == {}:
                self._data.update(user_input)

                if user_input["mqtt_port"] > 1:
                    return self.async_create_entry(
                        title="ShoppingListWithGrocy", data=self._data
                    )

                return await self.async_step_mqtt_port()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("api_url"): cv.string,
                    vol.Required("verify_ssl", default=True): cv.boolean,
                    vol.Required("api_key"): cv.string,
                    vol.Required("mqtt_server", default="127.0.0.1"): cv.string,
                    vol.Required("mqtt_port", default=1883): vol.All(
                        cv.port, vol.In([1883, 1884, 8883, 8884, 1])
                    ),
                    vol.Required("mqtt_username"): cv.string,
                    vol.Required("mqtt_password"): cv.string,
                    vol.Optional(
                        "image_download_size",
                        default=100,
                    ): vol.All(cv.positive_int, vol.In([0, 50, 100, 150, 200])),
                    vol.Optional(
                        "adding_products_in_sensor", default=False
                    ): cv.boolean,
                }
            ),
            errors=self._errors,
        )

    async def async_step_mqtt_port(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._errors = {}

        if user_input is not None:
            if self._errors == {}:
                self._data.update(user_input)
                return self.async_create_entry(
                    title="ShoppingListWithGrocy", data=self._data
                )

        return self.async_show_form(
            step_id="mqtt_port",
            data_schema=vol.Schema(
                {
                    vol.Required("mqtt_custom_port", default=1883): cv.port,
                }
            ),
            errors=self._errors,
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
