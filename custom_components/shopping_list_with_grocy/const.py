"""Constants for the Shopping List with Grocy integration."""

DOMAIN = "shopping_list_with_grocy"

ENTITY_VERSION = 2

STATE_INIT = "init"
STATE_READY = "ready"
STATE_COMPLETED = "completed"

EVENT_STARTED = "shopping_list_with_grocy_started"
SERVICE_REFRESH = "refresh_products"
SERVICE_SEARCH = "search_products"
SERVICE_ADD = "add_product"
SERVICE_REMOVE = "remove_product"
SERVICE_NOTE = "update_note"
SERVICE_ATTR_PRODUCT_ID = "product_id"
SERVICE_ATTR_SHOPPING_LIST_ID = "shopping_list_id"
SERVICE_ATTR_NOTE = "note"
SERVICE_ATTR_AMOUNT = "amount"

OTHER_FIELDS = {
    "qu_id_purchase",
    "qu_id_stock",
    "min_stock_amount",
    "default_best_before_days",
    "default_best_before_days_after_open",
    "default_best_before_days_after_freezing",
    "default_best_before_days_after_thawing",
    "parent_product_id",
    "calories",
    "cumulate_min_stock_amount_of_sub_products",
    "due_type",
    "quick_consume_amount",
    "should_not_be_frozen",
    "treat_opened_as_out_of_stock",
    "no_own_stock",
    "move_on_open",
}
