"""Tests for the purchase history episode state machine.

The store is exercised without a real HA storage backend: the Store instance is
swapped for a fake, and the clock is driven manually so that the debounce
windows can be crossed deterministically.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from custom_components.shopping_list_with_grocy import history_store
from custom_components.shopping_list_with_grocy.history_store import (
    CLOSE_GRACE,
    MIN_OPEN_DWELL,
    SOURCE_GROCY_STOCK,
    SOURCE_SHOPPING_LIST,
    STALE_OBSERVATION_GAP,
    PurchaseHistoryStore,
    normalize_episode,
    read_observation,
    resolve_added_at,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


class FakeStore:
    """Stand-in for homeassistant.helpers.storage.Store."""

    def __init__(self):
        self.data = None
        self.save_count = 0

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data
        self.save_count += 1

    def async_delay_save(self, data_func, delay):
        self.data = data_func()
        self.save_count += 1


class Clock:
    """Manually advanced clock patched over history_store._now."""

    def __init__(self, monkeypatch, start=1_700_000_000):
        self.now = start
        monkeypatch.setattr(history_store, "_now", lambda: self.now)

    def advance(self, seconds):
        self.now += seconds


def grocy_time(timestamp):
    """Render an epoch the way Grocy writes row_created_timestamp."""
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def product(product_id, quantity, lists=None, note="", done=0, created=None):
    """Build a parsed product payload the way parse_products does."""
    attributes = {"product_id": product_id}

    for list_id in lists or []:
        attributes[f"list_{list_id}_qty"] = quantity
        attributes[f"list_{list_id}_note"] = note
        attributes[f"list_{list_id}_done"] = done
        attributes[f"list_{list_id}_created"] = grocy_time(created) if created else None

    return {
        "name": f"Product {product_id}",
        "product_id": product_id,
        "qty_in_shopping_lists": quantity,
        "attributes": attributes,
    }


def payload(*products):
    """Build the dict parse_products hands to the store."""
    return {str(p["product_id"]): p for p in products}


@pytest_asyncio.fixture
async def store(monkeypatch):
    """Return a loaded store backed by a fake Store."""
    instance = PurchaseHistoryStore(MagicMock())
    instance._store = FakeStore()
    await instance.async_load()
    return instance


@pytest.fixture
def clock(monkeypatch):
    """Return a manually advanced clock."""
    return Clock(monkeypatch)


async def open_episode(store, clock, product_id=1, quantity=2, lists=(1,), note=""):
    """Drive a product through the debounce window into an open episode."""
    await store.async_observe(payload(product(product_id, quantity, lists, note)))
    clock.advance(MIN_OPEN_DWELL + 1)
    await store.async_observe(payload(product(product_id, quantity, lists, note)))


async def close_episode(store, clock, product_id=1):
    """Drive an open product through the grace window into the journal."""
    await store.async_observe(payload(product(product_id, 0)))
    clock.advance(CLOSE_GRACE + 1)
    await store.async_observe(payload(product(product_id, 0)))


# ── normalize_episode ────────────────────────────────────────────────────────


class TestNormalizeEpisode:
    def test_fills_optional_keys(self):
        episode = normalize_episode({"p": 1, "a": 1, "r": 2})

        assert episode == {
            "p": 1,
            "a": 1,
            "r": 2,
            "q": 0,
            "l": [],
            "oos": 0,
            "est": 0,
            "src": SOURCE_SHOPPING_LIST,
        }

    def test_keeps_existing_values(self):
        episode = normalize_episode(
            {"p": 1, "a": 1, "r": 2, "src": SOURCE_GROCY_STOCK, "oos": 1}
        )

        assert episode["src"] == SOURCE_GROCY_STOCK
        assert episode["oos"] == 1


# ── read_observation ─────────────────────────────────────────────────────────


class TestReadObservation:
    def test_collects_lists_with_quantity(self):
        result = read_observation(product(1, 2, [1, 3]))
        assert result["lists"] == [1, 3]
        # Two outstanding entries of two, the same total parse_products puts in
        # qty_in_shopping_lists.
        assert result["quantity"] == 4

    def test_ignores_lists_with_zero_quantity(self):
        parsed = product(1, 2, [1])
        parsed["attributes"]["list_5_qty"] = 0
        assert read_observation(parsed)["lists"] == [1]

    def test_aggregate_without_list_entries_is_zeroed(self):
        """A stale aggregate must not keep an episode open forever."""
        parsed = product(1, 4, [])
        assert read_observation(parsed)["quantity"] == 0

    def test_ticked_off_entries_are_not_outstanding(self):
        """Ticking a product off marks the Grocy row done, it does not delete
        it, and that tick is the purchase."""
        assert read_observation(product(1, 2, [1], done=1))["quantity"] == 0

    def test_a_missing_done_flag_means_outstanding(self):
        parsed = product(1, 2, [1])
        del parsed["attributes"]["list_1_done"]
        assert read_observation(parsed)["quantity"] == 2

    def test_done_as_a_string_is_understood(self):
        assert read_observation(product(1, 2, [1], done="1"))["quantity"] == 0

    def test_quantity_counts_outstanding_lists_only(self):
        parsed = product(1, 2, [1])
        parsed["attributes"]["list_4_qty"] = 5
        parsed["attributes"]["list_4_done"] = 1
        result = read_observation(parsed)
        assert result["quantity"] == 2
        assert result["lists"] == [1]

    def test_a_ticked_off_entry_cannot_be_out_of_stock(self):
        parsed = product(1, 1, [1], "out_of_stock", done=1)
        assert not read_observation(parsed)["out_of_stock"]

    def test_reads_the_row_creation_time(self):
        parsed = product(1, 1, [1], created=1788986400)
        assert read_observation(parsed)["created"] == [1788986400]

    def test_takes_the_earliest_creation_across_lists(self):
        parsed = product(1, 1, [1], created=1788986400)
        parsed["attributes"]["list_2_qty"] = 1
        parsed["attributes"]["list_2_done"] = 0
        parsed["attributes"]["list_2_created"] = grocy_time(1788900000)

        assert read_observation(parsed)["created"] == [1788900000]

    def test_an_unparseable_creation_time_is_dropped(self):
        parsed = product(1, 1, [1])
        parsed["attributes"]["list_1_created"] = "not a date"

        assert read_observation(parsed)["created"] is None

    def test_a_ticked_off_row_contributes_no_creation_time(self):
        assert (
            read_observation(product(1, 1, [1], done=1, created=1))["created"] is None
        )

    def test_detects_out_of_stock_note(self):
        assert read_observation(product(1, 1, [1], "out_of_stock"))["out_of_stock"]

    def test_out_of_stock_note_is_normalized(self):
        assert read_observation(product(1, 1, [1], "  Out_Of_Stock "))["out_of_stock"]

    def test_other_notes_are_not_out_of_stock(self):
        assert not read_observation(product(1, 1, [1], "the big one"))["out_of_stock"]

    def test_missing_attributes(self):
        result = read_observation({"qty_in_shopping_lists": 3})
        assert result == {
            "quantity": 0,
            "lists": [],
            "out_of_stock": False,
            "created": None,
        }

    def test_unparseable_quantity(self):
        parsed = product(1, 1, [1])
        parsed["attributes"]["list_1_qty"] = "nope"
        assert read_observation(parsed)["lists"] == []


class TestResolveAddedAt:
    def test_a_row_created_since_the_last_look_wins(self):
        """A whole list can be built while updates are paused, and every
        product would otherwise share one timestamp."""
        assert resolve_added_at({"created": [500]}, 1000, 100) == 500

    def test_a_row_older_than_the_last_look_is_ignored(self):
        """Re-adding a product updates its existing row in place, so the
        creation time can be a week old."""
        assert resolve_added_at({"created": [50]}, 1000, 100) == 1000

    def test_a_row_from_the_future_is_ignored(self):
        assert resolve_added_at({"created": [5000]}, 1000, 100) == 1000

    def test_no_creation_time_falls_back_to_now(self):
        assert resolve_added_at({"created": []}, 1000, 100) == 1000

    def test_the_first_observation_ever_falls_back_to_now(self):
        assert resolve_added_at({"created": [500]}, 1000, None) == 1000

    def test_the_window_picks_between_timezone_readings(self):
        """Grocy timestamps carry no timezone. The reading that is hours off
        falls outside the window and is discarded."""
        assert resolve_added_at({"created": [500, 500 - 14400]}, 1000, 100) == 500

    def test_the_later_reading_wins_when_both_fit(self):
        """Never invent an addition older than it really was."""
        assert resolve_added_at({"created": [500, 900]}, 1000, 100) == 900


# ── Opening ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestOpening:
    async def test_addition_below_dwell_is_discarded(self, store, clock):
        """Added then removed within the debounce window is a fat finger."""
        await store.async_observe(payload(product(1, 2, [1])))
        clock.advance(60)
        await store.async_observe(payload(product(1, 0)))

        assert store.get_episodes() == []
        assert store.get_open_episodes() == {}

    async def test_a_list_built_while_paused_keeps_its_own_timestamps(
        self, store, clock
    ):
        """The pause switch blocks the whole fetch, so a list built over
        several minutes arrives in a single observation."""
        await store.async_observe(payload(product(9, 1, [1])))
        start = clock.now
        clock.advance(600)

        first = start + 60
        second = start + 300
        await store.async_observe(
            payload(
                product(1, 1, [1], created=first),
                product(2, 1, [1], created=second),
            )
        )

        tracking = store.get_open_episodes()
        assert tracking["1"]["a"] == first
        assert tracking["2"]["a"] == second

    async def test_a_recycled_row_does_not_backdate_the_episode(self, store, clock):
        """Adding a product whose ticked-off row still exists updates that row
        in place, keeping a creation time from the previous shop."""
        await store.async_observe(payload(product(9, 1, [1])))
        stale = clock.now - 7 * 86400
        clock.advance(600)
        now = clock.now

        await store.async_observe(payload(product(1, 1, [1], created=stale)))

        assert store.get_open_episodes()["1"]["a"] == now

    async def test_addition_gone_after_a_long_gap_still_counts(self, store, clock):
        """Observations only happen when Grocy changes, so a product can be
        added and bought entirely between two of them. That is a purchase, not
        a fat finger."""
        added = clock.now
        await store.async_observe(payload(product(1, 2, [1])))
        clock.advance(3 * 86400)
        await store.async_observe(payload(product(1, 0)))

        episodes = store.get_episodes()
        assert len(episodes) == 1
        assert episodes[0]["a"] == added
        assert episodes[0]["est"] == 1

    async def test_addition_opens_after_dwell(self, store, clock):
        await open_episode(store, clock)
        assert store.get_open_episodes()["1"]["state"] == "open"

    async def test_opened_episode_keeps_first_seen_timestamp(self, store, clock):
        """The debounce must not shift the recorded addition time."""
        first_seen = clock.now
        await open_episode(store, clock)
        assert store.get_open_episodes()["1"]["a"] == first_seen


# ── Editing an open episode ──────────────────────────────────────────────────


@pytest.mark.asyncio
class TestEditing:
    async def test_quantity_edit_does_not_create_an_episode(self, store, clock):
        """Tweaking quantities while building the list is not a purchase."""
        await open_episode(store, clock, quantity=1)
        clock.advance(60)
        await store.async_observe(payload(product(1, 4, [1])))

        assert store.get_episodes() == []
        assert store.get_open_episodes()["1"]["q"] == 4

    async def test_move_between_lists_does_not_close(self, store, clock):
        """A move briefly looks like a removal followed by an addition."""
        await open_episode(store, clock, lists=(1,))
        clock.advance(60)
        await store.async_observe(payload(product(1, 0)))
        clock.advance(60)
        await store.async_observe(payload(product(1, 2, [2])))

        assert store.get_episodes() == []
        assert store.get_open_episodes()["1"]["l"] == [2]

    async def test_out_of_stock_flag_is_sticky(self, store, clock):
        """Clearing the note later must not clear the contamination."""
        await open_episode(store, clock)
        clock.advance(60)
        await store.async_observe(payload(product(1, 2, [1], "out_of_stock")))
        clock.advance(60)
        await store.async_observe(payload(product(1, 2, [1], "")))
        await close_episode(store, clock)

        assert store.get_episodes()[0]["oos"] == 1


# ── Closing ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestClosing:
    async def test_removal_below_grace_does_not_close(self, store, clock):
        await open_episode(store, clock)
        clock.advance(60)
        await store.async_observe(payload(product(1, 0)))

        assert store.get_episodes() == []
        assert store.get_open_episodes()["1"]["state"] == "pending_close"

    async def test_removal_closes_after_grace(self, store, clock):
        added = clock.now
        await open_episode(store, clock)
        clock.advance(3 * 86400)
        removed = clock.now
        await close_episode(store, clock)

        episodes = store.get_episodes()
        assert len(episodes) == 1
        assert episodes[0]["a"] == added
        assert episodes[0]["r"] == removed
        assert episodes[0]["src"] == SOURCE_SHOPPING_LIST
        assert store.get_open_episodes() == {}

    async def test_ticking_a_product_off_closes_the_episode(self, store, clock):
        """The real shopping workflow: items are ticked off in the shop."""
        added = clock.now
        await open_episode(store, clock)
        clock.advance(12 * 3600)
        bought = clock.now

        await store.async_observe(payload(product(1, 2, [1], done=1)))
        clock.advance(CLOSE_GRACE + 1)
        await store.async_observe(payload(product(1, 2, [1], done=1)))

        episodes = store.get_episodes()
        assert len(episodes) == 1
        assert episodes[0]["a"] == added
        assert episodes[0]["r"] == bought
        assert episodes[0]["q"] == 2

    async def test_unticking_within_the_grace_window_reopens(self, store, clock):
        await open_episode(store, clock)
        clock.advance(60)
        await store.async_observe(payload(product(1, 2, [1], done=1)))
        clock.advance(60)
        await store.async_observe(payload(product(1, 2, [1], done=0)))

        assert store.get_episodes() == []
        assert store.get_open_episodes()["1"]["state"] == "open"

    async def test_clearing_the_list_after_ticking_off_is_a_no_op(self, store, clock):
        """The row is deleted later, but the episode already closed."""
        await open_episode(store, clock)
        clock.advance(3600)
        await store.async_observe(payload(product(1, 2, [1], done=1)))
        clock.advance(CLOSE_GRACE + 1)
        await store.async_observe(payload(product(1, 2, [1], done=1)))
        clock.advance(86400)
        await store.async_observe(payload(product(1, 0)))
        clock.advance(CLOSE_GRACE + 1)
        await store.async_observe(payload(product(1, 0)))

        assert len(store.get_episodes()) == 1

    async def test_a_return_after_the_grace_window_starts_a_new_episode(
        self, store, clock
    ):
        """The grace window can expire between two observations. The earlier
        purchase must not be swallowed by the next one."""
        first_added = clock.now
        await open_episode(store, clock)
        clock.advance(3600)
        bought = clock.now
        await store.async_observe(payload(product(1, 2, [1], done=1)))

        clock.advance(4 * 86400)
        await store.async_observe(payload(product(1, 2, [1])))

        episodes = store.get_episodes()
        assert len(episodes) == 1
        assert episodes[0]["a"] == first_added
        assert episodes[0]["r"] == bought
        assert store.get_open_episodes()["1"]["state"] == "pending_open"

    async def test_two_cycles_produce_two_episodes(self, store, clock):
        await open_episode(store, clock)
        clock.advance(86400)
        await close_episode(store, clock)
        clock.advance(7 * 86400)
        await open_episode(store, clock)
        clock.advance(86400)
        await close_episode(store, clock)

        assert len(store.get_episodes()) == 2


# ── Restart and deletion ─────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRestartAndDeletion:
    async def test_a_quiet_grocy_is_not_a_gap(self, store, clock):
        """parse_products is skipped entirely while the Grocy database is
        unchanged, so hours can pass between two observations on a healthy
        instance. That must not be mistaken for a restart."""
        await open_episode(store, clock)
        clock.advance(STALE_OBSERVATION_GAP * 8)
        await close_episode(store, clock)

        assert store.get_episodes()[0]["est"] == 0

    async def test_normal_removal_is_not_flagged_estimated(self, store, clock):
        await open_episode(store, clock)
        clock.advance(600)
        await close_episode(store, clock)

        assert store.get_episodes()[0]["est"] == 0

    async def test_removal_seen_first_after_a_restart_is_estimated(self, store, clock):
        """HA was down while the product left the list, so the removal
        timestamp is only an upper bound."""
        await open_episode(store, clock)

        resumed = PurchaseHistoryStore(MagicMock())
        resumed._store = store._store
        await resumed.async_load()

        clock.advance(STALE_OBSERVATION_GAP + 60)
        await close_episode(resumed, clock)

        assert resumed.get_episodes()[0]["est"] == 1

    async def test_only_the_first_observation_after_a_restart_is_stale(
        self, store, clock
    ):
        """Later removals in the same session are seen live."""
        await open_episode(store, clock, product_id=1)
        await open_episode(store, clock, product_id=2)

        resumed = PurchaseHistoryStore(MagicMock())
        resumed._store = store._store
        await resumed.async_load()

        clock.advance(STALE_OBSERVATION_GAP + 60)
        await resumed.async_observe(payload(product(1, 0), product(2, 1, [1])))
        clock.advance(CLOSE_GRACE + 1)
        await resumed.async_observe(payload(product(1, 0), product(2, 1, [1])))

        clock.advance(STALE_OBSERVATION_GAP + 60)
        await close_episode(resumed, clock, product_id=2)

        assert resumed.get_episodes(product_id=1)[0]["est"] == 1
        assert resumed.get_episodes(product_id=2)[0]["est"] == 0

    async def test_deleted_product_closes_its_open_episode(self, store, clock):
        await open_episode(store, clock)
        clock.advance(60)
        await store.async_observe({})

        episodes = store.get_episodes()
        assert len(episodes) == 1
        assert episodes[0]["est"] == 1
        assert store.get_open_episodes() == {}

    async def test_deleted_product_drops_pending_tracking(self, store, clock):
        await store.async_observe(payload(product(1, 2, [1])))
        clock.advance(60)
        await store.async_observe({})

        assert store.get_episodes() == []
        assert store.get_open_episodes() == {}

    async def test_state_survives_a_reload(self, store, clock):
        """Tracking must be persisted, or a reload closes every episode."""
        await open_episode(store, clock)

        reloaded = PurchaseHistoryStore(MagicMock())
        reloaded._store = store._store
        await reloaded.async_load()

        assert reloaded.get_open_episodes()["1"]["state"] == "open"


# ── Journal API ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestJournal:
    async def test_observation_before_load_is_ignored(self, clock):
        instance = PurchaseHistoryStore(MagicMock())
        instance._store = FakeStore()

        await instance.async_observe(payload(product(1, 2, [1])))

        assert instance.get_open_episodes() == {}

    async def test_legacy_episodes_default_to_the_shopping_list(self):
        backend = FakeStore()
        backend.data = {"episodes": [{"p": 1, "a": 1, "r": 2, "q": 1}]}

        instance = PurchaseHistoryStore(MagicMock())
        instance._store = backend
        await instance.async_load()

        assert instance.get_episodes()[0]["src"] == SOURCE_SHOPPING_LIST

    async def test_episodes_filter_by_product(self, store, clock):
        await open_episode(store, clock, product_id=1)
        await open_episode(store, clock, product_id=2)
        clock.advance(600)
        await store.async_observe({})

        assert len(store.get_episodes(product_id=2)) == 1

    async def test_episodes_filter_by_source(self, store):
        store.add_episodes(
            [{"p": 9, "a": 1, "r": 1, "q": 1, "src": SOURCE_GROCY_STOCK}]
        )

        assert store.get_episodes(source=SOURCE_GROCY_STOCK)[0]["p"] == 9
        assert store.get_episodes(source=SOURCE_SHOPPING_LIST) == []

    async def test_sync_state_round_trip(self, store):
        store.set_sync_state(last_stock_log_id=42)
        store.set_sync_state(stock_log_empty=False)

        assert store.get_sync_state() == {
            "last_stock_log_id": 42,
            "stock_log_empty": False,
        }

    async def test_dump_counts_sources(self, store, clock):
        await open_episode(store, clock)
        clock.advance(600)
        await close_episode(store, clock)
        store.add_episodes(
            [{"p": 9, "a": 1, "r": 1, "q": 1, "src": SOURCE_GROCY_STOCK}]
        )

        snapshot = store.dump()
        assert snapshot["episode_count"] == 2
        assert snapshot["shopping_list_count"] == 1
        assert snapshot["grocy_stock_count"] == 1