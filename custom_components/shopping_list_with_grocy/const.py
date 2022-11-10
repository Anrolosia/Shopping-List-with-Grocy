"""Constants for the Shopping List with Grocy integration."""

DOMAIN = "shopping_list_with_grocy"

STATE_INIT = "init"
STATE_READY = "ready"
STATE_COMPLETED = "completed"

EVENT_STARTED = "shopping_list_with_grocy_started"
SERVICE_REFRESH = "refresh_products"
SERVICE_ADD = "add_product"
SERVICE_REMOVE = "remove_product"
SERVICE_NOTE = "update_note"
SERVICE_ATTR_PRODUCT_ID = "product_id"
SERVICE_ATTR_NOTE = "note"
