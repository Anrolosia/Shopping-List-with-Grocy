"""Tests for PurchasePredictionEngine (ml_engine).

The engine's public methods (_calculate_consumption_score,
_calculate_consumption_rate, should_suggest_purchase) are pure functions
of their inputs — no HA required.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from custom_components.shopping_list_with_grocy.ml_engine import (
    PurchasePredictionEngine,
)
from custom_components.shopping_list_with_grocy.analysis_const import (
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_CONSUMPTION_WEIGHT,
    DEFAULT_FREQUENCY_WEIGHT,
    DEFAULT_SEASONAL_WEIGHT,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_engine(config=None):
    hass = MagicMock()
    return PurchasePredictionEngine(hass, config or {})


def utc(days_ago: int) -> datetime:
    """Return a timezone-aware UTC datetime N days in the past."""
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def make_history(*state_days: tuple) -> list:
    """Build a history list from (state_value, days_ago) tuples."""
    return [
        {"state": str(state), "last_changed": utc(days_ago)}
        for state, days_ago in state_days
    ]


# ── Default weights ───────────────────────────────────────────────────────────


class TestDefaults:
    def test_default_weights(self):
        engine = make_engine()
        assert engine.consumption_weight == DEFAULT_CONSUMPTION_WEIGHT
        assert engine.frequency_weight == DEFAULT_FREQUENCY_WEIGHT
        assert engine.seasonal_weight == DEFAULT_SEASONAL_WEIGHT
        assert engine.score_threshold == DEFAULT_SCORE_THRESHOLD

    def test_custom_weights(self):
        engine = make_engine(
            {
                "consumption_weight": 0.6,
                "frequency_weight": 0.3,
                "seasonal_weight": 0.1,
                "score_threshold": 0.5,
            }
        )
        assert engine.consumption_weight == 0.6
        assert engine.score_threshold == 0.5


# ── _calculate_consumption_score ─────────────────────────────────────────────


class TestConsumptionScore:
    def test_empty_history_returns_zero(self):
        engine = make_engine()
        assert engine._calculate_consumption_score([]) == 0.0

    def test_single_entry_returns_zero(self):
        engine = make_engine()
        history = make_history((1, 5))
        assert engine._calculate_consumption_score(history) == 0.0

    def test_increasing_state_is_a_purchase(self):
        """State going 0→1 within 7 days → frequency ~1/week → score ~1.0."""
        engine = make_engine()
        history = make_history((0, 8), (1, 1))
        score = engine._calculate_consumption_score(history)
        assert score > 0.0

    def test_non_increasing_state_ignored(self):
        """State staying flat → no purchase detected → score 0."""
        engine = make_engine()
        history = make_history((2, 10), (2, 5), (2, 1))
        score = engine._calculate_consumption_score(history)
        assert score == 0.0

    def test_score_capped_at_one(self):
        """Very frequent purchases → score never exceeds 1.0."""
        engine = make_engine()
        # Purchase every day for 10 days
        history = make_history(*[(i, 10 - i) for i in range(10)])
        score = engine._calculate_consumption_score(history)
        assert score <= 1.0

    def test_score_non_negative(self):
        engine = make_engine()
        history = make_history((0, 30), (1, 20), (0, 10), (1, 1))
        score = engine._calculate_consumption_score(history)
        assert score >= 0.0

    def test_invalid_state_values_skipped(self):
        """Non-numeric states don't crash — they're skipped."""
        engine = make_engine()
        history = [
            {"state": "unavailable", "last_changed": utc(10)},
            {"state": "1", "last_changed": utc(5)},
            {"state": "unknown", "last_changed": utc(1)},
        ]
        # Should not raise
        score = engine._calculate_consumption_score(history)
        assert isinstance(score, float)


# ── _calculate_consumption_rate ───────────────────────────────────────────────


class TestConsumptionRate:
    def test_empty_history_returns_zero(self):
        engine = make_engine()
        assert engine._calculate_consumption_rate([]) == 0.0

    def test_single_entry_returns_zero(self):
        engine = make_engine()
        assert engine._calculate_consumption_rate(make_history((1, 5))) == 0.0

    def test_monthly_purchase_gives_reasonable_rate(self):
        """30-day average interval → rate = 30/30 = 1.0."""
        engine = make_engine()
        history = make_history((1, 60), (1, 30), (1, 0))
        rate = engine._calculate_consumption_rate(history)
        assert 0.9 <= rate <= 1.0

    def test_yearly_purchase_gives_low_rate(self):
        """365-day interval → rate = 30/365 ≈ 0.08."""
        engine = make_engine()
        history = make_history((1, 365), (1, 0))
        rate = engine._calculate_consumption_rate(history)
        assert rate < 0.1

    def test_rate_capped_at_one(self):
        engine = make_engine()
        history = make_history((1, 2), (1, 1), (1, 0))
        rate = engine._calculate_consumption_rate(history)
        assert rate <= 1.0

    def test_zero_state_entries_ignored(self):
        """Entries with state=0 don't count as purchases."""
        engine = make_engine()
        history = make_history((0, 10), (0, 5), (0, 1))
        rate = engine._calculate_consumption_rate(history)
        assert rate == 0.0


# ── should_suggest_purchase ───────────────────────────────────────────────────


class TestShouldSuggest:
    def test_score_above_threshold_suggests(self):
        engine = make_engine({"score_threshold": 0.3})
        assert engine.should_suggest_purchase({"score": 0.5}) is True

    def test_score_below_threshold_does_not_suggest(self):
        engine = make_engine({"score_threshold": 0.3})
        assert engine.should_suggest_purchase({"score": 0.1}) is False

    def test_score_exactly_at_threshold_does_not_suggest(self):
        """Threshold is exclusive (>) not inclusive (>=)."""
        engine = make_engine({"score_threshold": 0.3})
        assert engine.should_suggest_purchase({"score": 0.3}) is False

    def test_zero_score_never_suggests(self):
        engine = make_engine()
        assert engine.should_suggest_purchase({"score": 0.0}) is False
