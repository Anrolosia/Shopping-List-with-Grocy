"""Grocy stock log history source for the Shopping List with Grocy integration.

Users who actually track stock in Grocy already own a clean purchase history:
the ``stock_log`` table records every transaction with a real date, and Grocy
keeps it forever. That history is strictly better than watching shopping list
episodes, since it carries no dwell noise and needs no warm up period.

This module pulls those purchases into the journal so the prediction engine can
use them. It always runs: the sync is cheap and the result is what makes the
source detection possible in the first place. Deciding the mode before
collecting anything would mean guessing.

Grocy quirks handled here:

* A single purchase can produce several ``stock_log`` rows sharing one
  ``transaction_id``, one per stock entry. They are folded into one episode
  with the amounts summed.
* ``undone`` rows are reversals the user cancelled. They are skipped.
* Only ``transaction_type == "purchase"`` counts. Instances that were merely
  poked at with the inventory feature produce ``inventory-correction`` and
  ``product-opened`` rows, which say nothing about buying habits.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from .history_store import SOURCE_GROCY_STOCK, PurchaseHistoryStore

LOGGER = logging.getLogger(__name__)

PREDICTION_SOURCE_AUTO = "auto"
PREDICTION_SOURCE_SHOPPING_LIST = "shopping_list"
PREDICTION_SOURCE_GROCY_STOCK = "grocy_stock"

TRANSACTION_PURCHASE = "purchase"

PAGE_SIZE = 200
MAX_PAGES = 100

# How many purchases over the detection window are enough to trust the stock
# log as the primary signal. Below this the instance was poked at rather than
# used, and the shopping list stays the better source.
DETECTION_WINDOW_DAYS = 180
DETECTION_MIN_PURCHASES = 30

# Instances with a populated stock log are re-synced on this cadence. Empty
# ones back off hard, since polling them costs a request for nothing.
SYNC_INTERVAL = 60 * 60
SYNC_INTERVAL_EMPTY = 24 * 60 * 60


def _parse_grocy_datetime(value: Any) -> Optional[int]:
    """Parse a Grocy timestamp into a UTC epoch, or None if unusable.

    Grocy writes naive timestamps in the server's own timezone. They are read
    as UTC here: the prediction engine works in days, so a few hours of skew
    changes nothing, and guessing at a timezone the API does not expose would
    add a failure mode for no gain.
    """
    if not isinstance(value, str) or not value.strip():
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue

        if fmt == "%Y-%m-%d":
            # A date with no time: put it at midday so that a timezone shift
            # in either direction cannot move it onto another day, which would
            # corrupt the day of week statistics.
            parsed = parsed + timedelta(hours=12)

        return int(parsed.replace(tzinfo=timezone.utc).timestamp())

    LOGGER.debug("Unparseable Grocy timestamp: %s", value)
    return None


def _row_timestamp(row: Dict[str, Any]) -> Optional[int]:
    """Return the moment a purchase happened.

    ``purchased_date`` is the date the user says they bought the product, which
    is the one that matters. ``row_created_timestamp`` is only when the row was
    keyed in, so it is a fallback.
    """
    return _parse_grocy_datetime(row.get("purchased_date")) or _parse_grocy_datetime(
        row.get("row_created_timestamp")
    )


def build_episodes(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Turn raw stock log rows into journal episodes.

    Rows sharing a transaction are folded together per product. The resulting
    episodes are point events: the addition and removal timestamps are equal,
    because a purchase has no dwell.
    """
    grouped: Dict[tuple, Dict[str, Any]] = {}

    for row in rows:
        if row.get("transaction_type") != TRANSACTION_PURCHASE:
            continue

        try:
            if int(row.get("undone", 0) or 0):
                continue
        except (TypeError, ValueError):
            continue

        product_id = row.get("product_id")
        if product_id is None:
            continue

        timestamp = _row_timestamp(row)
        if timestamp is None:
            continue

        try:
            amount = float(row.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0

        # A purchase logged with a negative amount is a correction, not a buy.
        if amount <= 0:
            continue

        key = (row.get("transaction_id") or row.get("id"), int(product_id))

        if key in grouped:
            grouped[key]["q"] += amount
            continue

        grouped[key] = {
            "p": int(product_id),
            "a": timestamp,
            "r": timestamp,
            "q": amount,
            "l": [],
            "oos": 0,
            "est": 0,
            "src": SOURCE_GROCY_STOCK,
        }

    return sorted(grouped.values(), key=lambda ep: ep["a"])


def detect_source(
    episodes: List[Dict[str, Any]],
    now: int,
    window_days: int = DETECTION_WINDOW_DAYS,
    minimum: int = DETECTION_MIN_PURCHASES,
) -> str:
    """Pick the prediction source from what the journal actually holds.

    Pure function over the journal, so it can be re-evaluated at any time
    without touching the network.
    """
    cutoff = now - window_days * 86400

    recent = [
        ep
        for ep in episodes
        if ep.get("src") == SOURCE_GROCY_STOCK and ep.get("a", 0) >= cutoff
    ]

    if len(recent) >= minimum:
        return PREDICTION_SOURCE_GROCY_STOCK

    return PREDICTION_SOURCE_SHOPPING_LIST


def resolve_source(configured: str, episodes: List[Dict[str, Any]], now: int) -> str:
    """Resolve the configured prediction source into an effective one."""
    if configured in (PREDICTION_SOURCE_SHOPPING_LIST, PREDICTION_SOURCE_GROCY_STOCK):
        return configured

    return detect_source(episodes, now)


class StockLogSource:
    """Keep the journal's Grocy stock episodes in sync with the Grocy server."""

    def __init__(self, api, store: PurchaseHistoryStore) -> None:
        """Initialize the source."""
        self.api = api
        self.store = store

    async def _fetch_page(self, after_id: int, offset: int) -> List[Dict[str, Any]]:
        """Fetch one page of purchase rows newer than *after_id*."""
        params = [
            ("query[]", f"transaction_type={TRANSACTION_PURCHASE}"),
            ("query[]", f"id>{after_id}"),
            ("order", "id:asc"),
            ("limit", PAGE_SIZE),
            ("offset", offset),
        ]

        response = await self.api.request(
            "get",
            f"api/objects/stock_log?{urlencode(params)}",
            "application/json",
            log_level=logging.DEBUG,
        )

        if response is None:
            return []

        rows = await response.json()

        return rows if isinstance(rows, list) else []

    def _due(self, now: int) -> bool:
        """Return True when enough time has passed to re-sync."""
        state = self.store.get_sync_state()
        last = state.get("last_stock_sync")

        if last is None:
            return True

        interval = (
            SYNC_INTERVAL_EMPTY if state.get("stock_log_empty") else SYNC_INTERVAL
        )

        return now - last >= interval

    async def async_sync(self, now: int, force: bool = False) -> int:
        """Pull new purchases into the journal and return how many were added.

        The first call backfills the whole history. Later calls only ask for
        rows past the highest id already seen, so they stay cheap.
        """
        if not force and not self._due(now):
            return 0

        state = self.store.get_sync_state()
        after_id = int(state.get("last_stock_log_id", 0) or 0)
        first_run = state.get("last_stock_sync") is None

        rows: List[Dict[str, Any]] = []
        offset = 0

        try:
            for _ in range(MAX_PAGES):
                page = await self._fetch_page(after_id, offset)
                if not page:
                    break

                rows.extend(page)

                if len(page) < PAGE_SIZE:
                    break

                offset += PAGE_SIZE
        except Exception as err:  # noqa: BLE001
            # Grocy being unreachable must never break the sync cycle. The next
            # run picks up from the same id.
            LOGGER.debug("Could not fetch the Grocy stock log: %s", err)
            return 0

        episodes = build_episodes(rows)

        highest_id = after_id
        for row in rows:
            try:
                highest_id = max(highest_id, int(row.get("id", 0)))
            except (TypeError, ValueError):
                continue

        self.store.add_episodes(episodes)

        known = self.store.get_episodes(source=SOURCE_GROCY_STOCK)

        self.store.set_sync_state(
            last_stock_log_id=highest_id,
            last_stock_sync=now,
            stock_log_empty=not known,
        )

        if episodes:
            LOGGER.debug(
                "Imported %d purchase episode(s) from the Grocy stock log",
                len(episodes),
            )
        elif first_run:
            LOGGER.debug(
                "The Grocy stock log holds no usable purchases, the shopping "
                "list stays the prediction source"
            )

        return len(episodes)
