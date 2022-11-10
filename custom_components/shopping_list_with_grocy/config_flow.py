"""Config flow for Trakt."""
import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries

from .const import DOMAIN


class ShoppingListWithGrocyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow to handle Trakt OAuth2 authentication."""

    VERSION = 1
    DOMAIN = DOMAIN
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

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
