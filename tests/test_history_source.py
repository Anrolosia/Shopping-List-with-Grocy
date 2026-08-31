"""Tests for the Grocy stock log history source.

The row fixtures mirror real Grocy payloads, including the shapes that make the
naive implementation wrong: several rows sharing one transaction, undone rows,
and transaction types that say nothing about buying habits.
"""

from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from custom_components.shopping_list_with_grocy.history_source import (
    DETECTION_MIN_PURCHASES,
    PREDICTION_SOURCE_GROCY_STOCK,
    PREDICTION_SOURCE_SHOPPING_LIST,
    SYNC_INTERVAL,
    SYNC_INTERVAL_EMPTY,
    StockLogSource,
    build_episodes,
    detect_source,
    resolve_source,
)
from custom_components.shopping_list_with_grocy.history_store import (
    SOURCE_GROCY_STOCK,
    PurchaseHistoryStore,
)

NOW = 1_700_000_000
DAY = 86400

# ── Helpers ──────────────────────────────────────────────────────────────────


class FakeStore:
    """Stand-in for homeassistant.helpers.storage.Store."""

    def __init__(self):
        self.data = None

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data

    def async_delay_save(self, data_func, delay):
        self.data = data_func()


class FakeResponse:
    """Minimal aiohttp response stand-in."""

    def __init__(self, rows):
        self._rows = rows

    async def json(self):
        return self._rows


class FakeApi:
    """Records requests and replays canned stock log pages."""

    def __init__(self, pages=None, error=None):
        self.pages = list(pages or [])
        self.error = error
        self.urls = []

    async def request(self, method, url, accept, **kwargs):
        self.urls.append(url)

        if self.error:
            raise self.error

        if not self.pages:
            return FakeResponse([])

        return FakeResponse(self.pages.pop(0))


def row(row_id, product_id, transaction_type="purchase", **overrides):
    """Build a stock log row."""
    base = {
        "id": row_id,
        "product_id": product_id,
        "amount": 1,
        "transaction_type": transaction_type,
        "undone": 0,
        "purchased_date": "2025-03-18",
        "row_created_timestamp": "2025-03-18 11:28:53",
        "transaction_id": f"tx{row_id}",
    }
    base.update(overrides)
    return base


def stock_episode(timestamp, product_id=1):
    """Build a journalled Grocy stock episode."""
    return {
        "p": product_id,
        "a": timestamp,
        "r": timestamp,
        "q": 1,
        "l": [],
        "oos": 0,
        "est": 0,
        "src": SOURCE_GROCY_STOCK,
    }


@pytest_asyncio.fixture
async def store():
    """Return a loaded store backed by a fake Store."""
    instance = PurchaseHistoryStore(MagicMock())
    instance._store = FakeStore()
    await instance.async_load()
    return instance


# ── build_episodes ───────────────────────────────────────────────────────────


class TestBuildEpisodes:
    def test_purchase_becomes_a_point_episode(self):
        episodes = build_episodes([row(1, 42)])

        assert len(episodes) == 1
        assert episodes[0]["p"] == 42
        assert episodes[0]["a"] == episodes[0]["r"]
        assert episodes[0]["src"] == SOURCE_GROCY_STOCK

    def test_non_purchase_types_are_ignored(self):
        """An instance poked at with the inventory feature is not a history."""
        rows = [
            row(1, 6, "inventory-correction"),
            row(2, 6, "product-opened"),
            row(3, 6, "consume", amount=-1),
        ]
        assert build_episodes(rows) == []

    def test_undone_rows_are_ignored(self):
        assert build_episodes([row(1, 110, undone=1)]) == []

    def test_undone_as_string_is_ignored(self):
        assert build_episodes([row(1, 110, undone="1")]) == []

    def test_rows_sharing_a_transaction_are_folded(self):
        """One purchase can hit several stock entries."""
        rows = [
            row(1, 42, transaction_id="tx-shared", amount=2),
            row(2, 42, transaction_id="tx-shared", amount=3),
        ]
        episodes = build_episodes(rows)

        assert len(episodes) == 1
        assert episodes[0]["q"] == 5

    def test_different_products_in_one_transaction_stay_separate(self):
        rows = [
            row(1, 42, transaction_id="tx-shared"),
            row(2, 43, transaction_id="tx-shared"),
        ]
        assert len(build_episodes(rows)) == 2

    def test_negative_amounts_are_ignored(self):
        assert build_episodes([row(1, 42, amount=-2)]) == []

    def test_rows_without_a_product_are_ignored(self):
        assert build_episodes([row(1, None)]) == []

    def test_purchased_date_wins_over_row_created(self):
        episodes = build_episodes(
            [
                row(
                    1,
                    42,
                    purchased_date="2025-03-10",
                    row_created_timestamp="2025-03-18 11:28:53",
                )
            ]
        )
        # Midday on the purchase date, not the day it was keyed in.
        assert episodes[0]["a"] == 1741608000

    def test_falls_back_to_row_created_timestamp(self):
        episodes = build_episodes([row(1, 42, purchased_date=None)])
        assert episodes[0]["a"] == 1742297333

    def test_unparseable_timestamps_are_skipped(self):
        rows = [row(1, 42, purchased_date="nope", row_created_timestamp="also nope")]
        assert build_episodes(rows) == []

    def test_episodes_are_sorted_by_time(self):
        rows = [
            row(1, 42, purchased_date="2025-05-01"),
            row(2, 42, purchased_date="2025-01-01"),
        ]
        episodes = build_episodes(rows)
        assert episodes[0]["a"] < episodes[1]["a"]


# ── detect_source ────────────────────────────────────────────────────────────


class TestDetectSource:
    def test_empty_journal_falls_back_to_the_shopping_list(self):
        assert detect_source([], NOW) == PREDICTION_SOURCE_SHOPPING_LIST

    def test_a_poked_at_instance_falls_back(self):
        """Benjamin's instance: a handful of rows, no real purchase history."""
        episodes = [stock_episode(NOW - i * DAY) for i in range(5)]
        assert detect_source(episodes, NOW) == PREDICTION_SOURCE_SHOPPING_LIST

    def test_a_used_instance_selects_the_stock_log(self):
        episodes = [
            stock_episode(NOW - i * DAY) for i in range(DETECTION_MIN_PURCHASES)
        ]
        assert detect_source(episodes, NOW) == PREDICTION_SOURCE_GROCY_STOCK

    def test_old_purchases_do_not_count(self):
        """A user who stopped tracking stock a year ago is back to the list."""
        episodes = [
            stock_episode(NOW - 400 * DAY - i * DAY)
            for i in range(DETECTION_MIN_PURCHASES * 2)
        ]
        assert detect_source(episodes, NOW) == PREDICTION_SOURCE_SHOPPING_LIST

    def test_shopping_list_episodes_do_not_count(self):
        episodes = [
            {"p": 1, "a": NOW - i * DAY, "src": 0}
            for i in range(DETECTION_MIN_PURCHASES * 2)
        ]
        assert detect_source(episodes, NOW) == PREDICTION_SOURCE_SHOPPING_LIST


class TestResolveSource:
    def test_explicit_choice_wins_over_detection(self):
        episodes = [
            stock_episode(NOW - i * DAY) for i in range(DETECTION_MIN_PURCHASES)
        ]
        resolved = resolve_source(PREDICTION_SOURCE_SHOPPING_LIST, episodes, NOW)
        assert resolved == PREDICTION_SOURCE_SHOPPING_LIST

    def test_auto_defers_to_detection(self):
        assert resolve_source("auto", [], NOW) == PREDICTION_SOURCE_SHOPPING_LIST

    def test_unknown_value_defers_to_detection(self):
        assert resolve_source("banana", [], NOW) == PREDICTION_SOURCE_SHOPPING_LIST


# ── StockLogSource ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestStockLogSource:
    async def test_first_sync_imports_and_records_bookkeeping(self, store):
        api = FakeApi(pages=[[row(7, 42), row(9, 43)]])
        source = StockLogSource(api, store)

        imported = await source.async_sync(NOW)

        assert imported == 2
        assert len(store.get_episodes(source=SOURCE_GROCY_STOCK)) == 2
        assert store.get_sync_state()["last_stock_log_id"] == 9
        assert store.get_sync_state()["stock_log_empty"] is False

    async def test_empty_stock_log_is_marked(self, store):
        source = StockLogSource(FakeApi(pages=[[]]), store)

        assert await source.async_sync(NOW) == 0
        assert store.get_sync_state()["stock_log_empty"] is True

    async def test_incremental_sync_asks_for_new_rows_only(self, store):
        api = FakeApi(pages=[[row(7, 42)], [row(11, 42)]])
        source = StockLogSource(api, store)

        await source.async_sync(NOW)
        await source.async_sync(NOW + SYNC_INTERVAL + 1)

        assert "id%3E7" in api.urls[-1]
        assert store.get_sync_state()["last_stock_log_id"] == 11

    async def test_sync_is_skipped_before_the_interval(self, store):
        api = FakeApi(pages=[[row(7, 42)]])
        source = StockLogSource(api, store)

        await source.async_sync(NOW)
        await source.async_sync(NOW + 60)

        assert len(api.urls) == 1

    async def test_empty_instances_back_off_harder(self, store):
        api = FakeApi(pages=[[]])
        source = StockLogSource(api, store)

        await source.async_sync(NOW)
        await source.async_sync(NOW + SYNC_INTERVAL + 1)
        assert len(api.urls) == 1

        await source.async_sync(NOW + SYNC_INTERVAL_EMPTY + 1)
        assert len(api.urls) == 2

    async def test_force_bypasses_the_interval(self, store):
        api = FakeApi(pages=[[row(7, 42)]])
        source = StockLogSource(api, store)

        await source.async_sync(NOW)
        await source.async_sync(NOW + 60, force=True)

        assert len(api.urls) == 2

    async def test_a_failing_grocy_does_not_break_the_cycle(self, store):
        source = StockLogSource(FakeApi(error=RuntimeError("boom")), store)

        assert await source.async_sync(NOW) == 0
        assert store.get_sync_state() == {}

    async def test_only_purchases_are_requested(self, store):
        source = StockLogSource(FakeApi(pages=[[]]), store)
        await source.async_sync(NOW)

        assert "transaction_type%3Dpurchase" in source.api.urls[0]
