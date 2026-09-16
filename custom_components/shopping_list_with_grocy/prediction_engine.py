"""Purchase prediction for the Shopping List with Grocy integration.

Everything here is a pure function over the episode journal, so the whole
engine can be exercised without Home Assistant, without Grocy, and without a
clock.

The model is deliberately arithmetic rather than learned. Per product there are
usually a handful of purchases, which is far too few for a fitted model to beat
a robust median, and an explainable score is worth more than an accurate one
when the output is a suggestion a person has to trust.

Two levels of statistics live here, and they mature at very different speeds:

* Household statistics need episodes, not repeats. How long products sit on the
  list before being bought, which day the list gets built, which day the
  shopping happens. These are usable after a single shopping trip.
* Product statistics need the same product bought twice. Everything predictive
  lives here, and it only starts existing after a product comes back.

The central quantity is the interval between two purchases of one product,
measured addition to addition. The addition is the deliberate act with the
clean timestamp, and it is the act the engine is meant to automate.
"""

import logging
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone, tzinfo
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger(__name__)

DAY = 86400.0

# Only the most recent intervals are used. This is what actually lets the
# estimate follow a changing habit: a median moves when the majority of the
# sample moves, so weighting alone cannot flip it. With a trailing window a new
# habit takes over halfway through the window and fully by the end of it.
MAX_INTERVALS = 12

# How much a product's own history can weigh against the priors. Confidence
# comes from everything ever observed, while the value comes from the trailing
# window, so a long running product is not held back by the window size.
MAX_OWN_WEIGHT = 30.0

# Within the window, recent intervals still count for a little more. An
# interval observed this long ago counts for half of a fresh one. This breaks
# ties and nudges the estimate, it does not drive adaptation on its own.
HALF_LIFE_DAYS = 90.0

# A product needs this many purchases before its own interval is used at all.
# Two purchases give one interval, which is a data point, not a habit.
MIN_EPISODES_FOR_INTERVAL = 2
MIN_EPISODES_TO_SUGGEST = 3

# How hard an unproven product is pulled toward its group and toward the
# household. With one interval of its own the estimate is mostly borrowed, with
# ten it is mostly its own.
SHRINKAGE_GROUP_WEIGHT = 2.0
SHRINKAGE_HOUSEHOLD_WEIGHT = 2.0

# A prior built from one or two observations is noise wearing a statistic's
# clothes, and borrowing from it hands that noise to every product at once.
# Below these sample sizes the level simply does not exist, and products borrow
# from whatever coarser level does.
MIN_GROUP_INTERVALS = 3
MIN_HOUSEHOLD_INTERVALS = 5

# Past this multiple of its own interval a product is treated as abandoned
# rather than very overdue. Without it, the nappies you stopped buying become
# the top suggestion forever.
DORMANT_MULTIPLIER = 3.0

# An episode that sat on the list this much longer than usual was forgotten
# rather than shopped for, so its interval is not trustworthy.
DWELL_ANOMALY_MULTIPLIER = 2.0

STATE_COLD = "cold"
STATE_LEARNING = "learning"
STATE_READY = "ready"
STATE_DORMANT = "dormant"


def _weighted_median(values: List[float], weights: List[float]) -> Optional[float]:
    """Return the weighted median of *values*, or None when empty."""
    if not values:
        return None

    pairs = sorted(zip(values, weights))
    total = sum(weights)

    if total <= 0:
        return statistics.median(values)

    running = 0.0
    for value, weight in pairs:
        running += weight
        if running >= total / 2:
            return value

    return pairs[-1][0]


def _median_absolute_deviation(values: List[float]) -> Optional[float]:
    """Return the MAD, the robust cousin of the standard deviation."""
    if len(values) < 2:
        return None

    center = statistics.median(values)
    return statistics.median([abs(value - center) for value in values])


def episodes_by_product(episodes: List[Dict[str, Any]]) -> Dict[int, List[Dict]]:
    """Group episodes per product, each list sorted oldest first."""
    grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)

    for episode in episodes:
        grouped[episode["p"]].append(episode)

    for product_episodes in grouped.values():
        product_episodes.sort(key=lambda ep: ep["a"])

    return dict(grouped)


def product_intervals(product_episodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the intervals between consecutive purchases, in days.

    Normally the interval runs from one addition to the next. When the previous
    episode was flagged out of stock it runs from its removal instead: the
    product sat on the list waiting for the shop to restock it, and that wait
    says nothing about how fast it gets consumed.
    """
    intervals: List[Dict[str, Any]] = []

    for previous, current in zip(product_episodes, product_episodes[1:]):
        if previous.get("oos"):
            start = previous.get("r", previous["a"])
            basis = "removal"
        else:
            start = previous["a"]
            basis = "addition"

        days = (current["a"] - start) / DAY

        if days <= 0:
            continue

        intervals.append({"days": days, "at": current["a"], "basis": basis})

    return intervals


def household_stats(
    episodes: List[Dict[str, Any]], tz: Optional[tzinfo] = None
) -> Dict[str, Any]:
    """Return the statistics that describe the household rather than a product.

    These are the ones that exist after a single shopping trip: how long things
    wait on the list, and which days the list gets built and shopped.

    Weekdays are read in *tz*, which must be the household's own timezone. A
    list built at nine in the evening falls on the next day in UTC, and getting
    that wrong would smear the shopping day across two.
    """
    tz = tz or timezone.utc
    dwells: List[float] = []
    list_days: Counter = Counter()
    shop_days: Counter = Counter()

    for episode in episodes:
        removed = episode.get("r")

        list_days[datetime.fromtimestamp(episode["a"], tz).weekday()] += 1

        if removed is None:
            continue

        shop_days[datetime.fromtimestamp(removed, tz).weekday()] += 1

        # Out of stock episodes waited on the shop, and estimated removals have
        # an invented timestamp. Neither describes how this household shops.
        if episode.get("oos") or episode.get("est"):
            continue

        dwell = (removed - episode["a"]) / DAY
        if dwell > 0:
            dwells.append(dwell)

    intervals: List[float] = []
    for product_episodes in episodes_by_product(episodes).values():
        intervals.extend(item["days"] for item in product_intervals(product_episodes))

    trusted_intervals = len(intervals) >= MIN_HOUSEHOLD_INTERVALS

    # Sample size counts intervals, not independent shopping cycles. Seven
    # products bought on the same two trips give seven identical intervals: a
    # sample of seven carrying one observation. A spread near zero is the
    # signature of that, and a warning that the prior is thinner than it looks.
    interval_spread = _median_absolute_deviation(intervals)

    return {
        "dwell_median_days": statistics.median(dwells) if dwells else None,
        "dwell_mad_days": _median_absolute_deviation(dwells),
        "dwell_sample_size": len(dwells),
        "interval_median_days": (
            statistics.median(intervals) if trusted_intervals else None
        ),
        "interval_sample_size": len(intervals),
        "interval_sample_trusted": trusted_intervals,
        "interval_mad_days": interval_spread,
        "list_weekday": list_days.most_common(1)[0][0] if list_days else None,
        "shop_weekday": shop_days.most_common(1)[0][0] if shop_days else None,
        "list_weekday_counts": dict(list_days),
        "shop_weekday_counts": dict(shop_days),
    }


def is_dwell_anomalous(
    episode: Dict[str, Any], dwell_median_days: Optional[float]
) -> bool:
    """Return True when an episode sat on the list far longer than usual.

    Forgetting to tick something off inflates the interval that follows it, so
    those episodes are excluded from the interval estimate.
    """
    if dwell_median_days is None or episode.get("r") is None:
        return False

    dwell = (episode["r"] - episode["a"]) / DAY

    return dwell > DWELL_ANOMALY_MULTIPLIER * dwell_median_days


def estimate_interval(
    intervals: List[Dict[str, Any]],
    now: int,
    group_median: Optional[float],
    household_median: Optional[float],
) -> Dict[str, Any]:
    """Blend a product's own intervals with its group and household priors.

    With one interval of its own the estimate is mostly borrowed, with ten it
    is mostly the product's own. This is what makes an estimate usable after
    three purchases instead of eight.
    """
    window = sorted(intervals, key=lambda item: item["at"])[-MAX_INTERVALS:]

    values = [item["days"] for item in window]
    weights = [0.5 ** ((now - item["at"]) / DAY / HALF_LIFE_DAYS) for item in window]

    own = _weighted_median(values, weights)
    own_weight = min(float(len(intervals)), MAX_OWN_WEIGHT)

    numerator = 0.0
    denominator = 0.0

    if own is not None:
        numerator += own_weight * own
        denominator += own_weight

    if group_median is not None:
        numerator += SHRINKAGE_GROUP_WEIGHT * group_median
        denominator += SHRINKAGE_GROUP_WEIGHT

    if household_median is not None:
        numerator += SHRINKAGE_HOUSEHOLD_WEIGHT * household_median
        denominator += SHRINKAGE_HOUSEHOLD_WEIGHT

    if denominator <= 0:
        return {"days": None, "own_days": None, "borrowed": 1.0, "mad_days": None}

    borrowed = 1.0 - (own_weight / denominator if own is not None else 0.0)

    return {
        "days": numerator / denominator,
        "own_days": own,
        "borrowed": borrowed,
        "mad_days": _median_absolute_deviation(values),
    }


def analyze(
    episodes: List[Dict[str, Any]],
    now: int,
    groups: Optional[Dict[int, str]] = None,
    tz: Optional[tzinfo] = None,
) -> Dict[str, Any]:
    """Run the whole engine over a journal and return everything it can say.

    *groups* maps a product id to its Grocy product group, used as the middle
    level of shrinkage. It can be omitted, in which case products borrow
    straight from the household. *tz* is the household timezone, needed to read
    weekdays correctly.
    """
    groups = groups or {}
    household = household_stats(episodes, tz)
    by_product = episodes_by_product(episodes)

    usable: Dict[int, List[Dict[str, Any]]] = {}
    for product_id, product_episodes in by_product.items():
        clean = [
            episode
            for episode in product_episodes
            if not is_dwell_anomalous(episode, household["dwell_median_days"])
        ]
        usable[product_id] = product_intervals(clean)

    group_values: Dict[str, List[float]] = defaultdict(list)
    for product_id, intervals in usable.items():
        group = groups.get(product_id)
        if group:
            group_values[group].extend(item["days"] for item in intervals)

    group_medians = {
        group: statistics.median(values)
        for group, values in group_values.items()
        if len(values) >= MIN_GROUP_INTERVALS
    }

    products: Dict[int, Dict[str, Any]] = {}

    for product_id, product_episodes in by_product.items():
        intervals = usable[product_id]
        last = product_episodes[-1]
        days_since = (now - last["a"]) / DAY

        estimate = estimate_interval(
            intervals,
            now,
            group_medians.get(groups.get(product_id)),
            household["interval_median_days"],
        )

        overdue = (
            days_since / estimate["days"]
            if estimate["days"] and estimate["days"] > 0
            else None
        )

        products[product_id] = {
            "episodes": len(product_episodes),
            "intervals": len(intervals),
            "last_added": last["a"],
            "days_since_last": days_since,
            "interval_days": estimate["days"],
            "own_interval_days": estimate["own_days"],
            "borrowed": estimate["borrowed"],
            "mad_days": estimate["mad_days"],
            "overdue_ratio": overdue,
            "group": groups.get(product_id),
            "state": _product_state(product_episodes, intervals, overdue),
        }

    return {
        "household": household,
        "products": products,
        "coverage": _coverage(by_product, usable),
    }


def _product_state(
    product_episodes: List[Dict[str, Any]],
    intervals: List[Dict[str, Any]],
    overdue: Optional[float],
) -> str:
    """Classify how much the engine can say about one product.

    Data sufficiency is decided before dormancy. A product bought once has a
    borrowed estimate and an overdue ratio built on it, and calling that
    dormant would dress a guess up as a conclusion. Either way it is not
    suggested.
    """
    if len(product_episodes) < MIN_EPISODES_FOR_INTERVAL or not intervals:
        return STATE_COLD

    if overdue is not None and overdue > DORMANT_MULTIPLIER:
        return STATE_DORMANT

    if len(product_episodes) < MIN_EPISODES_TO_SUGGEST:
        return STATE_LEARNING

    return STATE_READY


def _coverage(
    by_product: Dict[int, List[Dict[str, Any]]],
    usable: Dict[int, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Return how far the journal is from being able to predict anything.

    This is the number worth watching in the early weeks: episodes accumulate
    quickly, repeats do not, and only repeats produce intervals.
    """
    counts = [len(items) for items in by_product.values()]

    return {
        "products": len(by_product),
        "episodes": sum(counts),
        "products_with_2_episodes": sum(1 for count in counts if count >= 2),
        "products_with_3_episodes": sum(1 for count in counts if count >= 3),
        "products_with_5_episodes": sum(1 for count in counts if count >= 5),
        "total_intervals": sum(len(items) for items in usable.values()),
    }


def suggest(analysis: Dict[str, Any], limit: int = 10) -> List[Dict[str, Any]]:
    """Return the products the engine believes are due, best first.

    Nothing is padded. A short honest list beats a long one with filler, since
    a single bad suggestion costs more trust than a missing good one earns.
    """
    candidates = []

    for product_id, stats in analysis["products"].items():
        if stats["state"] != STATE_READY:
            continue

        overdue = stats["overdue_ratio"]
        if overdue is None or overdue < 1.0:
            continue

        candidates.append(
            {
                "product_id": product_id,
                "score": min(overdue, DORMANT_MULTIPLIER) / DORMANT_MULTIPLIER,
                "overdue_ratio": overdue,
                "interval_days": stats["interval_days"],
                "days_since_last": stats["days_since_last"],
                "borrowed": stats["borrowed"],
            }
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)

    return candidates[:limit]
