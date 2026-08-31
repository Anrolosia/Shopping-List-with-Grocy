"""Purchase history capture for the Shopping List with Grocy integration.

The prediction engine needs a purchase history that outlives the recorder, so
this module keeps its own journal in Home Assistant's storage helper instead of
reading entity states back from the database.

An *episode* is one stay of a product on a shopping list: it opens when the
product is added and closes when it is removed. Adding is the primary signal.
It is a deliberate action with a clean timestamp, and it is exactly the action
the prediction engine is meant to automate. Removal is only used to compute the
dwell time and to handle out of stock episodes.

Stored shape (``.storage/shopping_list_with_grocy.history``)::

    {
        "episodes": [
            {"p": 42, "a": 1735689600, "r": 1736294400, "q": 2,
             "l": [1], "oos": 0, "est": 0}
        ],
        "tracking": {"42": {"state": "open", "a": 1735689600, ...}},
        "last_observation": 1736294400
    }

Episode keys are kept short because the journal is rewritten in full on every
save: p=product id, a=added, r=removed, q=quantity, l=shopping list ids,
oos=out of stock, est=removal timestamp is estimated.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.history"

# An addition only counts once the product has stayed on the list for this
# long. Anything shorter is a mistyped entry the user immediately undid.
MIN_OPEN_DWELL = 15 * 60

# A removal only counts once the product has stayed off the list for this long.
# This absorbs moves between shopping lists, which briefly look like a removal
# followed by an addition.
CLOSE_GRACE = 5 * 60

# When the gap between two observations is larger than this, Home Assistant was
# most likely down. Removals detected on the first observation after such a gap
# get their timestamp flagged as estimated so they can be excluded from dwell
# statistics.
STALE_OBSERVATION_GAP = 60 * 60

SAVE_DELAY = 60

# Magic note value recognised by the Lovelace card (slwg-products.ts renders
# those tiles in red). An episode marked out of stock measures its interval
# from the removal instead of the addition, because the product sat on the list
# waiting for restock rather than waiting to be bought.
OUT_OF_STOCK_NOTE = "out_of_stock"

STATE_ABSENT = "absent"
STATE_PENDING_OPEN = "pending_open"
STATE_OPEN = "open"
STATE_PENDING_CLOSE = "pending_close"

_LIST_QTY_RE = re.compile(r"^list_(\d+)_qty$")


def _now() -> int:
    """Return the current UTC timestamp as a whole number of seconds."""
    return int(dt_util.utcnow().timestamp())


def _to_number(value: Any) -> float:
    """Coerce a Grocy quantity into a float, defaulting to zero."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_out_of_stock(note: Any) -> bool:
    """Return True when a shopping list note carries the out of stock marker."""
    if not isinstance(note, str):
        return False
    return note.strip().lower() == OUT_OF_STOCK_NOTE


def read_observation(product: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce one parsed product into the fields the journal cares about.

    Returns the total quantity, the shopping lists the product currently sits
    on, and whether any of those lists flagged it as out of stock.
    """
    attributes = product.get("attributes") or {}

    lists: List[int] = []
    out_of_stock = False

    for key, value in attributes.items():
        match = _LIST_QTY_RE.match(key)
        if not match:
            continue
        if _to_number(value) <= 0:
            continue

        list_id = int(match.group(1))
        lists.append(list_id)

        if _is_out_of_stock(attributes.get(f"list_{list_id}_note")):
            out_of_stock = True

    quantity = _to_number(product.get("qty_in_shopping_lists"))

    # The per list attributes are the authoritative view. A product can carry a
    # stale aggregate while every list entry is gone, and closing on the
    # aggregate alone would keep the episode open forever.
    if not lists:
        quantity = 0.0

    return {
        "quantity": quantity,
        "lists": sorted(lists),
        "out_of_stock": out_of_stock,
    }


class PurchaseHistoryStore:
    """Persist shopping list episodes for the prediction engine."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the journal."""
        self.hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._episodes: List[Dict[str, Any]] = []
        self._tracking: Dict[str, Dict[str, Any]] = {}
        self._last_observation: Optional[int] = None
        self._loaded = False

    async def async_load(self) -> None:
        """Load the journal from disk."""
        data = await self._store.async_load()

        if data:
            self._episodes = data.get("episodes", []) or []
            self._tracking = data.get("tracking", {}) or {}
            self._last_observation = data.get("last_observation")

        self._loaded = True

        LOGGER.debug(
            "Purchase history loaded: %d episode(s), %d tracked product(s)",
            len(self._episodes),
            len(self._tracking),
        )

    def _data_to_save(self) -> Dict[str, Any]:
        """Return the journal in its serialized form."""
        return {
            "episodes": self._episodes,
            "tracking": self._tracking,
            "last_observation": self._last_observation,
        }

    async def async_shutdown(self) -> None:
        """Flush any pending write before the entry unloads."""
        if not self._loaded:
            return
        await self._store.async_save(self._data_to_save())

    async def async_observe(self, parsed_products: Dict[str, Dict[str, Any]]) -> None:
        """Advance the episode state machine from a fresh coordinator payload.

        Called on every successful Grocy fetch. Cheap enough to run inline: it
        is a dict walk over the products plus an occasional debounced write.
        """
        if not self._loaded:
            LOGGER.debug("Purchase history not loaded yet, skipping observation")
            return

        now = _now()
        stale = (
            self._last_observation is not None
            and now - self._last_observation > STALE_OBSERVATION_GAP
        )

        if stale:
            LOGGER.debug(
                "Gap of %d s since last observation, removals will be flagged "
                "as estimated",
                now - self._last_observation,
            )

        changed = False

        for product_id, product in parsed_products.items():
            observation = read_observation(product)
            changed |= self._advance(str(product_id), observation, now, stale)

        changed |= self._forget_missing_products(set(parsed_products), now)

        self._last_observation = now

        if changed:
            self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    def _advance(
        self,
        product_id: str,
        observation: Dict[str, Any],
        now: int,
        stale: bool,
    ) -> bool:
        """Move a single product through the episode state machine."""
        entry = self._tracking.get(product_id)
        state = entry["state"] if entry else STATE_ABSENT
        present = observation["quantity"] > 0

        if state == STATE_ABSENT:
            if not present:
                return False
            # Hold the addition until it has survived the debounce window. The
            # timestamp kept is the moment it first appeared, not the moment it
            # gets promoted.
            self._tracking[product_id] = {
                "state": STATE_PENDING_OPEN,
                "a": now,
                "q": observation["quantity"],
                "l": observation["lists"],
                "oos": int(observation["out_of_stock"]),
            }
            return True

        if state == STATE_PENDING_OPEN:
            if not present:
                # Added and removed within the debounce window: a fat finger,
                # not a shopping intent.
                self._tracking.pop(product_id, None)
                return True

            self._merge_observation(entry, observation)

            if now - entry["a"] >= MIN_OPEN_DWELL:
                entry["state"] = STATE_OPEN
                LOGGER.debug(
                    "Opened purchase episode for product %s (qty %s)",
                    product_id,
                    entry["q"],
                )
            return True

        if state == STATE_OPEN:
            if present:
                return self._merge_observation(entry, observation)

            entry["state"] = STATE_PENDING_CLOSE
            entry["r"] = now
            entry["est"] = int(stale)
            return True

        if state == STATE_PENDING_CLOSE:
            if present:
                # Back on a list before the grace window expired. This is a
                # move between shopping lists or a quick undo, so the episode
                # never really ended.
                entry["state"] = STATE_OPEN
                entry.pop("r", None)
                entry.pop("est", None)
                self._merge_observation(entry, observation)
                return True

            if now - entry["r"] >= CLOSE_GRACE:
                self._close(product_id, entry)
                return True

            return False

        LOGGER.debug(
            "Unknown tracking state %s for product %s, resetting", state, product_id
        )
        self._tracking.pop(product_id, None)
        return True

    def _merge_observation(
        self, entry: Dict[str, Any], observation: Dict[str, Any]
    ) -> bool:
        """Fold a new observation into an open or pending episode.

        Quantity edits and list moves update the episode in place instead of
        creating new ones: the user tweaks quantities while building the list,
        and each tweak is not a separate purchase. The out of stock flag is
        sticky, since the episode is contaminated as soon as it is set once.
        """
        changed = False

        if entry.get("q") != observation["quantity"]:
            entry["q"] = observation["quantity"]
            changed = True

        if entry.get("l") != observation["lists"]:
            entry["l"] = observation["lists"]
            changed = True

        if observation["out_of_stock"] and not entry.get("oos"):
            entry["oos"] = 1
            changed = True

        return changed

    def _close(self, product_id: str, entry: Dict[str, Any]) -> None:
        """Commit a finished episode to the journal."""
        episode = {
            "p": int(product_id),
            "a": entry["a"],
            "r": entry["r"],
            "q": entry.get("q", 0),
            "l": entry.get("l", []),
            "oos": int(entry.get("oos", 0)),
            "est": int(entry.get("est", 0)),
        }

        self._episodes.append(episode)
        self._tracking.pop(product_id, None)

        LOGGER.debug(
            "Closed purchase episode for product %s (dwell %d s, oos %d, est %d)",
            product_id,
            episode["r"] - episode["a"],
            episode["oos"],
            episode["est"],
        )

    def _forget_missing_products(self, known_ids: set, now: int) -> bool:
        """Drop tracking for products that no longer exist in Grocy."""
        gone = [pid for pid in self._tracking if pid not in known_ids]

        for product_id in gone:
            entry = self._tracking[product_id]

            if entry["state"] in (STATE_OPEN, STATE_PENDING_CLOSE):
                entry.setdefault("r", now)
                entry["est"] = 1
                self._close(product_id, entry)
            else:
                self._tracking.pop(product_id, None)

        return bool(gone)

    def get_episodes(self, product_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return closed episodes, optionally for a single product."""
        if product_id is None:
            return list(self._episodes)

        return [ep for ep in self._episodes if ep["p"] == int(product_id)]

    def get_open_episodes(self) -> Dict[str, Dict[str, Any]]:
        """Return the products currently being tracked."""
        return dict(self._tracking)

    def dump(self) -> Dict[str, Any]:
        """Return a debug view of the journal."""
        products = {ep["p"] for ep in self._episodes}

        return {
            "episode_count": len(self._episodes),
            "product_count": len(products),
            "tracked_count": len(self._tracking),
            "out_of_stock_count": sum(1 for ep in self._episodes if ep["oos"]),
            "estimated_count": sum(1 for ep in self._episodes if ep["est"]),
            "oldest_episode": min((ep["a"] for ep in self._episodes), default=None),
            "newest_episode": max((ep["a"] for ep in self._episodes), default=None),
            "last_observation": self._last_observation,
            "episodes": self._episodes,
            "tracking": self._tracking,
        }
