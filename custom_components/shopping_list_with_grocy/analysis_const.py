import voluptuous as vol

DEFAULT_CONSUMPTION_WEIGHT = 0.4
DEFAULT_FREQUENCY_WEIGHT = 0.5
DEFAULT_SEASONAL_WEIGHT = 0.1

DEFAULT_SCORE_THRESHOLD = 0.3

CONF_ANALYSIS_SETTINGS = "analysis_settings"
CONF_CONSUMPTION_WEIGHT = "consumption_weight"
CONF_FREQUENCY_WEIGHT = "frequency_weight"
CONF_SEASONAL_WEIGHT = "seasonal_weight"
CONF_SCORE_THRESHOLD = "score_threshold"

ANALYSIS_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_CONSUMPTION_WEIGHT, default=DEFAULT_CONSUMPTION_WEIGHT
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
        vol.Required(CONF_FREQUENCY_WEIGHT, default=DEFAULT_FREQUENCY_WEIGHT): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=1.0)
        ),
        vol.Required(CONF_SEASONAL_WEIGHT, default=DEFAULT_SEASONAL_WEIGHT): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=1.0)
        ),
        vol.Required(CONF_SCORE_THRESHOLD, default=DEFAULT_SCORE_THRESHOLD): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=1.0)
        ),
    }
)
