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
             "l": [1], "oos": 0, "est": 0, "src": 0}
        ],
        "tracking": {"42": {"state": "open", "a": 1735689600, ...}},
        "sync": {"last_stock_log_id": 0, "stock_log_empty": False},
        "last_observation": 1736294400
    }

Episode keys are kept short because the journal is rewritten in full on every
save: p=product id, a=added, r=removed, q=quantity, l=shopping list ids,
oos=out of stock, est=removal timestamp is estimated, src=where the episode
came from.

Both sources are journalled side by side. The prediction engine reads one of
them at a time, so a user can switch modes without losing history.
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

# Home Assistant restarts are the only thing that can hide a removal, and they
# only ever show up on the first observation after a load. A gap during a live
# session just means Grocy was quiet: parse_products is skipped entirely when
# the Grocy database has not changed, so hours can pass between two
# observations on a perfectly healthy instance.
#
# Removals detected on that first post-load observation carry a timestamp that
# is only an upper bound, so they are flagged as estimated and can be excluded
# from dwell statistics.
STALE_OBSERVATION_GAP = 60 * 60

SAVE_DELAY = 60

# Magic note value recognised by the Lovelace card (slwg-products.ts renders
# those tiles in red). An episode marked out of stock measures its interval
# from the removal instead of the addition, because the product sat on the list
# waiting for restock rather than waiting to be bought.
OUT_OF_STOCK_NOTE = "out_of_stock"

# Where an episode came from. Shopping list episodes span an interval, Grocy
# stock episodes are point events where the addition and removal timestamps are
# the same.
SOURCE_SHOPPING_LIST = 0
SOURCE_GROCY_STOCK = 1

# The state machine is driven by Grocy database changes, not by the clock:
# parse_products is skipped entirely while Grocy is unchanged, so hours or days
# can pass between two observations. Every window below is therefore checked
# against elapsed time on the next observation, never assumed to have been
# checked promptly.
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


def normalize_episode(episode: Dict[str, Any]) -> Dict[str, Any]:
    """Fill in the optional keys of an episode.

    Episodes reach the journal from three places: the state machine, a Grocy
    stock backfill, and older versions of the file on disk. Normalising on the
    way in means every reader can index the keys directly.
    """
    episode.setdefault("q", 0)
    episode.setdefault("l", [])
    episode.setdefault("oos", 0)
    episode.setdefault("est", 0)
    episode.setdefault("src", SOURCE_SHOPPING_LIST)
    return episode


def _is_done(value: Any) -> bool:
    """Return True when a shopping list entry has been ticked off.

    Older payloads have no done attribute at all, and a missing flag means the
    entry is still outstanding.
    """
    if value is None:
        return False

    try:
        return int(value) != 0
    except (TypeError, ValueError):
        return bool(value)


def _is_out_of_stock(note: Any) -> bool:
    """Return True when a shopping list note carries the out of stock marker."""
    if not isinstance(note, str):
        return False
    return note.strip().lower() == OUT_OF_STOCK_NOTE


def read_observation(product: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce one parsed product into the fields the journal cares about.

    Returns the outstanding quantity, the shopping lists the product is still
    waiting on, and whether any of those lists flagged it as out of stock.

    Entries already ticked off do not count as outstanding. Ticking a product
    off a to-do list marks the Grocy row done rather than deleting it, and that
    tick happens in the shop, at the moment of the purchase. It is a better
    close signal than the row eventually disappearing, which can happen days
    later when the list is cleared.

    The per list attributes are the authoritative view rather than
    ``qty_in_shopping_lists``, which counts ticked entries and can also carry a
    stale aggregate after every entry is gone. Closing on the aggregate would
    keep episodes open forever.
    """
    attributes = product.get("attributes") or {}

    lists: List[int] = []
    quantity = 0.0
    out_of_stock = False

    for key, value in attributes.items():
        match = _LIST_QTY_RE.match(key)
        if not match:
            continue

        entry_quantity = _to_number(value)
        if entry_quantity <= 0:
            continue

        list_id = int(match.group(1))

        if _is_done(attributes.get(f"list_{list_id}_done")):
            continue

        lists.append(list_id)
        quantity += entry_quantity

        if _is_out_of_stock(attributes.get(f"list_{list_id}_note")):
            out_of_stock = True

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
        self._sync: Dict[str, Any] = {}
        self._last_observation: Optional[int] = None
        self._loaded = False
        self._resumed = False

    async def async_load(self) -> None:
        """Load the journal from disk."""
        data = await self._store.async_load()

        if data:
            self._episodes = data.get("episodes", []) or []
            self._tracking = data.get("tracking", {}) or {}
            self._sync = data.get("sync", {}) or {}
            self._last_observation = data.get("last_observation")

            # Episodes journalled by older versions predate the optional
            # keys, and all of them came from the shopping list.
            for episode in self._episodes:
                normalize_episode(episode)

        self._loaded = True
        self._resumed = False

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
            "sync": self._sync,
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

        # Only the first observation after a load can have missed anything.
        stale = (
            not self._resumed
            and self._last_observation is not None
            and now - self._last_observation > STALE_OBSERVATION_GAP
        )
        self._resumed = True

        if stale:
            LOGGER.debug(
                "Resuming after a gap of %d s, removals detected now will be "
                "flagged as estimated",
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
                if now - entry["a"] >= MIN_OPEN_DWELL:
                    # It outlived the debounce window somewhere inside the gap
                    # between two observations, so it was a real addition that
                    # has since been bought. Only the removal time is unknown.
                    entry["r"] = now
                    entry["est"] = 1
                    self._close(product_id, entry)
                    return True

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
                if now - entry["r"] >= CLOSE_GRACE:
                    # The grace window expired inside the gap between two
                    # observations, so the episode really did end back then.
                    # What is on the list now is a new one.
                    self._close(product_id, entry)
                    self._tracking[product_id] = {
                        "state": STATE_PENDING_OPEN,
                        "a": now,
                        "q": observation["quantity"],
                        "l": observation["lists"],
                        "oos": int(observation["out_of_stock"]),
                    }
                    return True

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
            "src": SOURCE_SHOPPING_LIST,
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

    def add_episodes(self, episodes: List[Dict[str, Any]]) -> None:
        """Append externally built episodes, such as a Grocy stock backfill."""
        if not episodes:
            return

        self._episodes.extend(normalize_episode(episode) for episode in episodes)
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    def get_sync_state(self) -> Dict[str, Any]:
        """Return the bookkeeping used by external history sources."""
        return dict(self._sync)

    def set_sync_state(self, **values: Any) -> None:
        """Merge values into the external source bookkeeping."""
        self._sync.update(values)
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    def get_episodes(
        self,
        product_id: Optional[int] = None,
        source: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return closed episodes, optionally filtered by product and source."""
        episodes = self._episodes

        if source is not None:
            episodes = [
                ep for ep in episodes if ep.get("src", SOURCE_SHOPPING_LIST) == source
            ]

        if product_id is not None:
            episodes = [ep for ep in episodes if ep["p"] == int(product_id)]

        return list(episodes)

    def get_open_episodes(self) -> Dict[str, Dict[str, Any]]:
        """Return the products currently being tracked."""
        return dict(self._tracking)

    def dump(self) -> Dict[str, Any]:
        """Return a debug view of the journal."""
        products = {ep["p"] for ep in self._episodes}
        from_list = self.get_episodes(source=SOURCE_SHOPPING_LIST)
        from_stock = self.get_episodes(source=SOURCE_GROCY_STOCK)

        return {
            "episode_count": len(self._episodes),
            "product_count": len(products),
            "shopping_list_count": len(from_list),
            "grocy_stock_count": len(from_stock),
            "sync": dict(self._sync),
            "tracked_count": len(self._tracking),
            "out_of_stock_count": sum(1 for ep in self._episodes if ep["oos"]),
            "estimated_count": sum(1 for ep in self._episodes if ep["est"]),
            "oldest_episode": min((ep["a"] for ep in self._episodes), default=None),
            "newest_episode": max((ep["a"] for ep in self._episodes), default=None),
            "last_observation": self._last_observation,
            "episodes": self._episodes,
            "tracking": self._tracking,
        }
