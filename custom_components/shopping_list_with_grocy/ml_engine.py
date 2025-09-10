"""Statistical Analysis Engine for Shopping List Suggestions."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean
from typing import Dict, List

from homeassistant.util import dt

from .analysis_const import (
    CONF_CONSUMPTION_WEIGHT,
    CONF_FREQUENCY_WEIGHT,
    CONF_SCORE_THRESHOLD,
    CONF_SEASONAL_WEIGHT,
    DEFAULT_CONSUMPTION_WEIGHT,
    DEFAULT_FREQUENCY_WEIGHT,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_SEASONAL_WEIGHT,
)

LOGGER = logging.getLogger(__name__)


class PurchasePredictionEngine:
    """Engine for predicting shopping needs based on statistical analysis."""

    def __init__(self, hass, config=None):
        """Initialize the prediction engine."""
        self.hass = hass
        self.config = config or {}

    @property
    def consumption_weight(self):
        """Get consumption analysis weight."""
        return self.config.get(CONF_CONSUMPTION_WEIGHT, DEFAULT_CONSUMPTION_WEIGHT)

    @property
    def frequency_weight(self):
        """Get frequency analysis weight."""
        return self.config.get(CONF_FREQUENCY_WEIGHT, DEFAULT_FREQUENCY_WEIGHT)

    @property
    def seasonal_weight(self):
        """Get seasonal analysis weight."""
        return self.config.get(CONF_SEASONAL_WEIGHT, DEFAULT_SEASONAL_WEIGHT)

    @property
    def score_threshold(self):
        """Get score threshold for suggestions."""
        return self.config.get(CONF_SCORE_THRESHOLD, DEFAULT_SCORE_THRESHOLD)

    def _calculate_consumption_score(self, history: List[Dict]) -> float:
        """Calculate consumption score based on purchase frequency and patterns."""
        if not history:
            return 0.0

        purchases = []

        for i in range(1, len(history)):
            try:
                prev_state = float(history[i - 1].get("state", "0"))
                curr_state = float(history[i].get("state", "0"))

                prev_changed = history[i - 1].get("last_changed")
                curr_changed = history[i].get("last_changed")

                if (
                    isinstance(prev_changed, datetime)
                    and isinstance(curr_changed, datetime)
                    and curr_state > prev_state
                ):
                    prev_local = dt.as_local(prev_changed)
                    curr_local = dt.as_local(curr_changed)
                    time_diff = (curr_local - prev_local).days or 1
                    purchase_frequency = 1.0 / time_diff if time_diff > 0 else 1.0
                    purchases.append(purchase_frequency)
            except (ValueError, TypeError, AttributeError):
                continue

        avg_frequency = mean(purchases) if purchases else 0.0
        return min(1.0, avg_frequency * 7)

    def _calculate_seasonal_score(
        self, history: List[Dict], current_date: datetime
    ) -> float:
        """Calculate seasonal score based on historical patterns."""
        if not history:
            return 0.0

        monthly_counts = defaultdict(lambda: defaultdict(int))
        current_local = dt.as_local(current_date)
        cutoff_date = current_local - timedelta(days=365)
        valid_entries = 0

        for entry in history:
            try:
                last_changed = entry.get("last_changed")
                if isinstance(last_changed, datetime):
                    local_date = dt.as_local(last_changed)
                    if local_date > cutoff_date:
                        monthly_counts[local_date.month][local_date.year] += 1
                        valid_entries += 1
            except (AttributeError, TypeError, ValueError):
                continue

        if valid_entries == 0:
            return 0.2

        current_month = current_local.month
        current_year = current_local.year

        month_counts = monthly_counts[current_month]
        all_month_averages = []

        for month in range(1, 13):
            month_data = monthly_counts[month]
            if month_data:
                historical_data = [
                    count
                    for year, count in month_data.items()
                    if not (month == current_month and year == current_year)
                ]
                if historical_data:
                    all_month_averages.append(mean(historical_data))

        current_month_count = month_counts.get(current_year, 0)

        baseline = mean(all_month_averages) if all_month_averages else 0

        if baseline == 0:
            return 0.2

        ratio = current_month_count / baseline if baseline > 0 else 0

        normalized_score = min(1.0, ratio / 2.0)

        confidence = min(1.0, len(all_month_averages) / 6)

        return min(1.0, ratio * confidence)

    def _calculate_consumption_rate(self, history: List[Dict]) -> float:
        """Calculate consumption rate based on purchase intervals."""
        if not history:
            return 0.0

        purchase_dates = []

        for entry in history:
            try:
                last_changed = entry.get("last_changed")
                if isinstance(last_changed, datetime):
                    state = float(entry.get("state", "0"))
                    if state > 0:
                        purchase_dates.append(dt.as_local(last_changed))
            except (ValueError, TypeError, AttributeError):
                continue

        if len(purchase_dates) < 2:
            return 0.0

        purchase_dates.sort()
        intervals = []
        for i in range(1, len(purchase_dates)):
            interval = (purchase_dates[i] - purchase_dates[i - 1]).days
            if interval > 0:
                intervals.append(interval)

        if not intervals:
            return 0.0

        avg_interval = mean(intervals)
        return min(1.0, 30.0 / avg_interval) if avg_interval > 0 else 0.0

    async def analyze_purchase_patterns(
        self, entity_id: str, history: List[Dict], friendly_name: str = ""
    ) -> Dict:
        """Analyze purchase patterns using statistical methods."""
        try:
            if history and history[-1].get("state"):
                try:
                    current_list_quantity = float(history[-1]["state"])
                    if current_list_quantity > 0:
                        return {
                            "score": 0.0,
                            "confidence": 1.0,
                            "factors": [
                                {
                                    "type": "already_in_list",
                                    "score": 0.0,
                                    "description": f"Already in shopping list (quantity: {current_list_quantity})",
                                }
                            ],
                        }
                except (ValueError, TypeError):
                    pass

            factors = []
            total_score = 0.0
            active_weights = 0.0

            consumption_rate = self._calculate_consumption_rate(history)
            if consumption_rate > 0:
                consumption_score = consumption_rate
                factors.append(
                    {
                        "type": "consumption_pattern",
                        "score": consumption_score,
                        "description": f"Purchase interval pattern score: {consumption_score:.2f}",
                    }
                )
                total_score += consumption_score * self.consumption_weight
                active_weights += self.consumption_weight

            now = dt.now()
            purchases = []
            for entry in history:
                try:
                    curr_changed = entry.get("last_changed")
                    state = float(entry.get("state", "0"))

                    if (
                        isinstance(curr_changed, datetime)
                        and dt.as_local(curr_changed) > now - timedelta(days=30)
                        and state > 0
                    ):
                        purchases.append(curr_changed)
                except (ValueError, TypeError, AttributeError):
                    continue

            frequency_score = min(1.0, len(purchases) / 10.0)
            if frequency_score > 0:
                factors.append(
                    {
                        "type": "purchase_frequency",
                        "score": frequency_score,
                        "description": f"Shopping list activity {len(purchases)} times in last 30 days",
                    }
                )
                total_score += frequency_score * self.frequency_weight
                active_weights += self.frequency_weight

            seasonal_score = self._calculate_seasonal_score(history, datetime.now())
            if seasonal_score > 0:
                factors.append(
                    {
                        "type": "seasonality",
                        "score": seasonal_score,
                        "description": f"Historical activity in current month: {seasonal_score:.1%}",
                    }
                )
                total_score += seasonal_score * self.seasonal_weight
                active_weights += self.seasonal_weight

            confidence = min(1.0, len(history) / 100)

            normalized_score = (
                total_score / active_weights if active_weights > 0 else 0.0
            )

            return {
                "score": normalized_score,
                "confidence": confidence,
                "factors": factors,
            }

        except Exception as err:
            LOGGER.error("Error analyzing purchase patterns for %s: %s", entity_id, err)
            return {"score": 0.0, "confidence": 0.0, "factors": []}

    def should_suggest_purchase(self, analysis: Dict) -> bool:
        """Determine if a product should be suggested for purchase."""
        return analysis["score"] > self.score_threshold
