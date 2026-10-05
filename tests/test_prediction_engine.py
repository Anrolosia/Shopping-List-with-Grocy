"""Tests for the statistical prediction engine.

Every function under test is pure, so the fixtures build journals by hand and
the clock is just an integer. Days are the unit throughout, and the helpers
below let a scenario read as "bought on these days" rather than as epochs.
"""

from datetime import timedelta, timezone

import pytest

from custom_components.shopping_list_with_grocy.prediction_engine import (
    DAY,
    DORMANT_MULTIPLIER,
    MAX_INTERVALS,
    MIN_CYCLE_GAPS,
    MIN_ELAPSED_FRACTION,
    MIN_GROUP_INTERVALS,
    MIN_HOUSEHOLD_INTERVALS,
    MIN_SESSION_SIZE,
    STATE_COLD,
    STATE_DORMANT,
    STATE_LEARNING,
    STATE_READY,
    analyze,
    cycle_length,
    episodes_by_product,
    estimate_interval,
    household_stats,
    is_dwell_anomalous,
    product_intervals,
    shopping_sessions,
    suggest,
)

# A Monday at midday UTC, so that weekday assertions read naturally.
MONDAY = 1788177600
NOW = MONDAY + int(400 * DAY)


def episode(product_id, added_day, dwell_hours=15, oos=0, est=0, qty=1.0):
    """Build an episode from a day offset, with a realistic overnight dwell."""
    added = MONDAY + int(added_day * DAY)

    return {
        "p": product_id,
        "a": added,
        "r": added + int(dwell_hours * 3600),
        "q": qty,
        "l": [1],
        "oos": oos,
        "est": est,
        "src": 0,
    }


def every(product_id, days, count, start=0, **kwargs):
    """Build a product bought on a regular cadence."""
    return [episode(product_id, start + days * i, **kwargs) for i in range(count)]


# ── Grouping and intervals ───────────────────────────────────────────────────


class TestIntervals:
    def test_groups_and_sorts_by_addition(self):
        grouped = episodes_by_product([episode(1, 10), episode(1, 2), episode(2, 5)])

        assert sorted(grouped) == [1, 2]
        assert [ep["a"] for ep in grouped[1]] == sorted(ep["a"] for ep in grouped[1])

    def test_measures_addition_to_addition(self):
        intervals = product_intervals(every(1, 7, 3))

        assert [round(item["days"]) for item in intervals] == [7, 7]
        assert all(item["basis"] == "addition" for item in intervals)

    def test_one_episode_has_no_interval(self):
        assert product_intervals([episode(1, 0)]) == []

    def test_out_of_stock_measures_from_the_removal(self):
        """The product waited on the shop, and that wait says nothing about
        how fast it gets consumed."""
        first = episode(1, 0, dwell_hours=14 * 24, oos=1)
        second = episode(1, 21)
        intervals = product_intervals([first, second])

        assert intervals[0]["basis"] == "removal"
        assert round(intervals[0]["days"]) == 7

    def test_simultaneous_additions_are_dropped(self):
        assert product_intervals([episode(1, 5), episode(1, 5)]) == []


# ── Shopping trips ───────────────────────────────────────────────────────────


def trip(day, size, product_start=1):
    """Build one shopping trip: a burst of removals minutes apart."""
    episodes = []

    for index in range(size):
        item = episode(product_start + index, day - 1)
        item["r"] = MONDAY + int(day * DAY) + index * 30
        episodes.append(item)

    return episodes


class TestShoppingSessions:
    def test_a_burst_of_removals_is_one_trip(self):
        sessions = shopping_sessions(trip(7, 14))

        assert len(sessions) == 1
        assert sessions[0]["size"] == 14

    def test_trips_days_apart_are_separate(self):
        sessions = shopping_sessions(trip(7, 5) + trip(14, 5, 100))

        assert [session["size"] for session in sessions] == [5, 5]

    def test_estimated_removals_are_ignored(self):
        """Their timestamp is whenever Home Assistant came back, not a trip."""
        stray = episode(500, 0, est=1)
        stray["r"] = MONDAY + int(3.5 * DAY)

        assert len(shopping_sessions(trip(7, 5) + [stray])) == 1

    def test_no_episodes_means_no_trips(self):
        assert shopping_sessions([]) == []


class TestCycleLength:
    def test_three_trips_give_a_cycle(self):
        journal = trip(7, 5) + trip(14, 5, 100) + trip(21, 5, 200)
        stats = cycle_length(journal)

        assert stats["trip_count"] == 3
        assert stats["cycle_days"] == pytest.approx(7, abs=0.01)
        assert stats["cycle_sample_size"] == MIN_CYCLE_GAPS

    def test_two_trips_are_not_enough(self):
        journal = trip(7, 5) + trip(14, 5, 100)

        assert cycle_length(journal)["cycle_days"] is None

    def test_a_stray_tick_is_not_a_trip(self):
        """Counting it would drag the cycle estimate down."""
        journal = trip(7, 5) + trip(10, MIN_SESSION_SIZE - 1, 50) + trip(14, 5, 100)
        journal += trip(21, 5, 200)
        stats = cycle_length(journal)

        assert stats["trip_count"] == 3
        assert stats["cycle_days"] == pytest.approx(7, abs=0.01)

    def test_an_irregular_rhythm_shows_spread(self):
        journal = trip(7, 5) + trip(14, 5, 100) + trip(35, 5, 200) + trip(40, 5, 300)

        assert cycle_length(journal)["cycle_mad_days"] > 1


# ── Household statistics ─────────────────────────────────────────────────────


class TestHouseholdStats:
    def test_dwell_median_from_a_single_trip(self):
        """The statistic that exists before any product repeats."""
        stats = household_stats([episode(i, 0) for i in range(10)])

        assert stats["dwell_sample_size"] == 10
        assert round(stats["dwell_median_days"] * 24) == 15

    def test_out_of_stock_is_excluded_from_the_dwell(self):
        stats = household_stats([episode(1, 0), episode(2, 0, dwell_hours=200, oos=1)])

        assert stats["dwell_sample_size"] == 1

    def test_estimated_removals_are_excluded_from_the_dwell(self):
        stats = household_stats([episode(1, 0), episode(2, 0, est=1)])

        assert stats["dwell_sample_size"] == 1

    def test_open_episodes_are_ignored(self):
        open_episode = episode(1, 0)
        open_episode["r"] = None

        assert household_stats([open_episode])["dwell_sample_size"] == 0

    def test_finds_the_list_and_shop_weekdays(self):
        stats = household_stats([episode(i, 0) for i in range(5)])

        # The list is built at midday and ticked off fifteen hours later, so
        # the shopping lands on the following day. That split is the point of
        # tracking the two weekdays separately.
        assert stats["list_weekday"] == 0
        assert stats["shop_weekday"] == 1

    def test_weekday_is_read_in_the_household_timezone(self):
        """A list built late in the evening falls on the next day in UTC."""
        late = episode(1, 0)
        late["a"] = MONDAY + int(10.5 * 3600)  # 22:30 UTC, 18:30 at UTC-4

        assert household_stats([late])["list_weekday"] == 0
        assert (
            household_stats([late], timezone(timedelta(hours=-4)))["list_weekday"] == 0
        )

        earlier = episode(1, 0)
        earlier["a"] = MONDAY - 3600  # 11:00 UTC Monday, 07:00 at UTC-4
        assert household_stats([earlier])["list_weekday"] == 0

        overnight = episode(1, 0)
        overnight["a"] = MONDAY + int(13 * 3600)  # 01:00 UTC Tuesday, 21:00 Monday
        assert household_stats([overnight])["list_weekday"] == 1
        assert (
            household_stats([overnight], timezone(timedelta(hours=-4)))["list_weekday"]
            == 0
        )


class TestPriorSampleSize:
    def test_a_household_prior_needs_a_sample(self):
        """One interval from one product is noise, and borrowing from it hands
        that noise to every product at once."""
        journal = every(1, 8, 2)
        stats = household_stats(journal)

        assert stats["interval_sample_size"] == 1
        assert stats["interval_median_days"] is None
        assert stats["interval_sample_trusted"] is False

    def test_the_household_prior_appears_once_earned(self):
        journal = []
        for product_id in range(1, MIN_HOUSEHOLD_INTERVALS + 1):
            journal.extend(every(product_id, 8, 2, start=product_id))
        stats = household_stats(journal)

        assert stats["interval_sample_size"] >= MIN_HOUSEHOLD_INTERVALS
        assert stats["interval_median_days"] == pytest.approx(8, abs=0.1)

    def test_a_degenerate_prior_is_visible_in_its_spread(self):
        """Seven products bought on the same two trips give seven identical
        intervals: a sample of seven carrying one observation."""
        journal = []
        for product_id in range(1, 8):
            journal.extend(every(product_id, 8, 2))
        stats = household_stats(journal)

        assert stats["interval_sample_size"] == 7
        assert stats["interval_sample_trusted"] is True
        assert stats["interval_mad_days"] == pytest.approx(0, abs=0.001)

    def test_a_varied_prior_shows_spread(self):
        journal = []
        for product_id, days in enumerate([4, 7, 9, 14, 21, 30], start=1):
            journal.extend(every(product_id, days, 2))

        assert household_stats(journal)["interval_mad_days"] > 1

    def test_an_untrusted_prior_leaves_products_without_an_estimate(self):
        """A cold product must not be handed an overdue ratio built on one
        observation of an unrelated product."""
        journal = every(1, 8, 2) + [episode(2, 0)]
        now = MONDAY + int(40 * DAY)
        products = analyze(journal, now)["products"]

        assert products[2]["interval_days"] is None
        assert products[2]["overdue_ratio"] is None

    def test_a_group_prior_needs_a_sample_too(self):
        journal = every(1, 7, 2) + [episode(2, 0)]
        groups = {1: "dairy", 2: "dairy"}
        now = MONDAY + int(40 * DAY)

        assert MIN_GROUP_INTERVALS > 1
        assert analyze(journal, now, groups)["products"][2]["interval_days"] is None


class TestDwellAnomaly:
    def test_a_forgotten_tick_is_anomalous(self):
        assert is_dwell_anomalous(episode(1, 0, dwell_hours=200), 15 / 24)

    def test_a_normal_dwell_is_not(self):
        assert not is_dwell_anomalous(episode(1, 0), 15 / 24)

    def test_no_household_median_means_no_judgement(self):
        assert not is_dwell_anomalous(episode(1, 0, dwell_hours=500), None)

    def test_an_open_episode_is_not_judged(self):
        open_episode = episode(1, 0)
        open_episode["r"] = None

        assert not is_dwell_anomalous(open_episode, 15 / 24)

    def test_an_out_of_stock_wait_is_not_a_forgotten_tick(self):
        """Waiting for the shop to restock is long by design."""
        waiting = episode(1, 0, dwell_hours=200, oos=1)

        assert not is_dwell_anomalous(waiting, 15 / 24)


# ── Interval estimation ──────────────────────────────────────────────────────


class TestEstimateInterval:
    def test_no_data_at_all_gives_nothing(self):
        assert estimate_interval([], NOW, None, None)["days"] is None

    def test_a_product_with_no_history_borrows_entirely(self):
        estimate = estimate_interval([], NOW, None, 10.0)

        assert estimate["days"] == 10.0
        assert estimate["borrowed"] == 1.0

    def test_many_intervals_outweigh_the_priors(self):
        intervals = product_intervals(every(1, 7, 21))
        estimate = estimate_interval(intervals, NOW, 30.0, 30.0)

        # The priors sit at 30 against an own interval of 7, so even a small
        # borrowed share moves the estimate a lot. That is shrinkage doing its
        # job, and the constants deserve calibration against real data.
        assert 7 < estimate["days"] < 11
        assert estimate["borrowed"] < 0.2

    def test_one_interval_is_pulled_hard_toward_the_priors(self):
        intervals = product_intervals(every(1, 7, 2))
        estimate = estimate_interval(intervals, NOW, 30.0, 30.0)

        assert estimate["own_days"] == pytest.approx(7, abs=0.1)
        assert estimate["days"] > 20
        assert estimate["borrowed"] > 0.7

    def test_a_changed_habit_is_followed(self):
        """A trailing window is what makes this work. Weighting alone cannot
        flip a median, since a median follows the majority of its sample."""
        old = [episode(1, i * 30) for i in range(10)]
        recent = [episode(1, 270 + i * 5) for i in range(1, 13)]
        intervals = product_intervals(old + recent)
        now = MONDAY + int(340 * DAY)

        assert estimate_interval(intervals, now, None, None)["days"] < 10

    def test_only_the_last_intervals_are_used(self):
        intervals = product_intervals(every(1, 7, MAX_INTERVALS + 20))
        estimate = estimate_interval(intervals, NOW, None, None)

        assert estimate["days"] == pytest.approx(7, abs=0.1)

    def test_mad_reports_spread(self):
        regular = estimate_interval(product_intervals(every(1, 7, 6)), NOW, None, None)
        erratic = product_intervals(
            [episode(1, 0), episode(1, 2), episode(1, 30), episode(1, 33)]
        )

        assert regular["mad_days"] == pytest.approx(0, abs=0.01)
        assert estimate_interval(erratic, NOW, None, None)["mad_days"] >= 1


# ── The whole engine ─────────────────────────────────────────────────────────


class TestAnalyze:
    def test_elapsed_time_after_restock_starts_at_removal(self):
        """A product restocked late still has time left, measured from the
        removal that ended its wait on the shop."""
        restocked = episode(1, 10, dwell_hours=5 * 24, oos=1)
        journal = [episode(1, 0), restocked]
        now = MONDAY + int(20 * DAY)

        stats = analyze(journal, now)["products"][1]

        assert stats["days_since_last"] == pytest.approx(5, abs=0.01)

    def test_an_out_of_stock_wait_is_kept_as_an_interval(self):
        """Its interval is measured from the removal, not the addition."""
        journal = [
            episode(1, 0),
            episode(1, 4, dwell_hours=10 * 24, oos=1),
            episode(1, 20),
        ]
        intervals = product_intervals(journal)

        assert len(intervals) == 2
        assert intervals[1]["basis"] == "removal"
        assert intervals[1]["days"] == pytest.approx(20 - 14, abs=0.01)

    def test_a_forgotten_tick_does_not_bridge_two_intervals(self):
        """Dropping the forgotten episode must not join its neighbours into one
        span: 0 to 7 is observed, 7 to 14 is not."""
        forgotten = [episode(1, 0), episode(1, 7, dwell_hours=200), episode(1, 14)]

        intervals = product_intervals(forgotten, 15 / 24)

        assert [round(item["days"]) for item in intervals] == [7]

    def test_one_usable_interval_is_not_enough_to_suggest(self):
        """Three episodes with one forgotten tick leave a single interval."""
        journal = every(2, 1, 20) + [
            episode(1, 0),
            episode(1, 7, dwell_hours=200),
            episode(1, 14),
        ]

        products = analyze(journal, MONDAY + int(17 * DAY))["products"]

        assert products[1]["state"] == STATE_LEARNING

    def test_a_single_trip_produces_no_intervals(self):
        """The real starting point: many episodes, no repeats, nothing to
        predict from."""
        analysis = analyze([episode(i, 0) for i in range(14)], NOW)

        assert analysis["coverage"]["products"] == 14
        assert analysis["coverage"]["products_with_2_episodes"] == 0
        assert analysis["coverage"]["total_intervals"] == 0
        assert analysis["household"]["dwell_median_days"] is not None
        assert all(
            stats["state"] == STATE_COLD for stats in analysis["products"].values()
        )

    def test_coverage_counts_repeats(self):
        journal = every(1, 7, 5) + every(2, 7, 2) + [episode(3, 0)]
        coverage = analyze(journal, NOW)["coverage"]

        assert coverage["products"] == 3
        assert coverage["products_with_2_episodes"] == 2
        assert coverage["products_with_3_episodes"] == 1
        assert coverage["total_intervals"] == 5

    def test_a_product_with_one_episode_is_cold_not_dormant(self):
        """Its overdue ratio rests on a borrowed estimate, and calling that
        dormant would dress a guess up as a conclusion."""
        journal = [episode(1, 0)] + every(2, 7, 6)
        now = MONDAY + int(60 * DAY)

        assert analyze(journal, now)["products"][1]["state"] == STATE_COLD

    def test_states_track_how_much_is_known(self):
        now = MONDAY + int(24 * DAY)
        journal = [episode(1, 0)] + every(2, 7, 2, start=14) + every(3, 7, 4)
        products = analyze(journal, now)["products"]

        assert products[1]["state"] == STATE_COLD
        assert products[2]["state"] == STATE_LEARNING
        assert products[3]["state"] == STATE_READY

    def test_an_abandoned_product_goes_dormant(self):
        """Without this, the nappies you stopped buying stay the top
        suggestion forever."""
        journal = every(1, 7, 6)
        now = MONDAY + int(300 * DAY)

        assert analyze(journal, now)["products"][1]["state"] == STATE_DORMANT

    def test_a_forgotten_tick_does_not_inflate_the_interval(self):
        journal = [
            episode(1, 0),
            episode(1, 7, dwell_hours=200),
            episode(1, 14),
            episode(1, 21),
            episode(1, 28),
        ]
        now = MONDAY + int(30 * DAY)
        products = analyze(journal, now)["products"]

        assert products[1]["intervals"] == 3

    def test_groups_feed_the_middle_level_of_shrinkage(self):
        journal = every(1, 7, 8) + every(2, 7, 8, start=1) + every(3, 7, 2, start=2)
        groups = {1: "dairy", 2: "dairy", 3: "dairy"}
        now = MONDAY + int(60 * DAY)

        with_groups = analyze(journal, now, groups)["products"][3]
        without = analyze(journal, now)["products"][3]

        assert with_groups["group"] == "dairy"
        assert with_groups["interval_days"] < without["interval_days"] + 0.001

    def test_overdue_ratio_measures_lateness(self):
        journal = every(1, 7, 5)
        now = MONDAY + int(28 * DAY) + int(14 * DAY)
        products = analyze(journal, now)["products"]

        assert products[1]["overdue_ratio"] > 1.5


# ── Suggestions ──────────────────────────────────────────────────────────────


class TestSuggest:
    def test_nothing_is_suggested_without_history(self):
        analysis = analyze([episode(i, 0) for i in range(14)], NOW)

        assert suggest(analysis) == []

    def test_a_due_product_is_suggested(self):
        journal = every(1, 7, 5)
        now = MONDAY + int(28 * DAY) + int(9 * DAY)

        assert suggest(analyze(journal, now))[0]["product_id"] == 1

    def test_a_product_bought_yesterday_is_not(self):
        journal = every(1, 7, 5)
        now = MONDAY + int(29 * DAY)

        assert suggest(analyze(journal, now)) == []

    def test_the_horizon_reaches_the_next_trip(self):
        """A product bought every seven days, in a household that shops every
        seven, belongs on every list even before it is overdue."""
        journal = every(1, 7, 5)
        now = MONDAY + int(28 * DAY) + int(5 * DAY)

        assert suggest(analyze(journal, now), horizon_days=7)[0]["product_id"] == 1
        assert suggest(analyze(journal, now), horizon_days=0) == []

    def test_a_just_bought_product_is_held_back(self):
        """Whatever the projection says, suggesting it hours later is noise."""
        journal = every(1, 7, 5)
        now = MONDAY + int(28 * DAY) + int(0.5 * DAY)
        results = suggest(analyze(journal, now), horizon_days=30)

        assert results == []

    def test_the_hold_back_ends_partway_through_the_interval(self):
        journal = every(1, 10, 5)
        now = MONDAY + int(40 * DAY) + int(MIN_ELAPSED_FRACTION * 10 * DAY) + 3600
        results = suggest(analyze(journal, now), horizon_days=30)

        assert [item["product_id"] for item in results] == [1]

    def test_products_already_on_a_list_are_excluded(self):
        """Analysis only sees closed episodes, so without this the engine
        suggests what the user just added."""
        journal = every(1, 7, 5) + every(2, 7, 5)
        now = MONDAY + int(28 * DAY) + int(9 * DAY)

        results = suggest(analyze(journal, now), exclude={1})
        assert [item["product_id"] for item in results] == [2]

    def test_the_horizon_defaults_to_the_household_cycle(self):
        journal = trip(7, 5) + trip(14, 5) + trip(21, 5) + trip(28, 5)
        now = MONDAY + int(32 * DAY)
        analysis = analyze(journal, now)

        assert analysis["household"]["cycle_days"] == pytest.approx(7, abs=0.01)
        assert suggest(analysis)[0]["horizon_days"] == pytest.approx(7, abs=0.01)

    def test_learning_products_are_not_suggested(self):
        """Two purchases is a data point, not a habit."""
        journal = every(1, 7, 2)
        now = MONDAY + int(60 * DAY)
        analysis = analyze(journal, now)

        assert analysis["products"][1]["state"] != STATE_READY
        assert suggest(analysis) == []

    def test_dormant_products_are_not_suggested(self):
        journal = every(1, 7, 6)
        now = MONDAY + int(300 * DAY)

        assert suggest(analyze(journal, now)) == []

    def test_the_list_is_never_padded(self):
        journal = every(1, 7, 5) + [episode(i, 0) for i in range(2, 40)]
        now = MONDAY + int(28 * DAY) + int(9 * DAY)

        assert len(suggest(analyze(journal, now))) == 1

    def test_the_most_overdue_comes_first(self):
        journal = every(1, 7, 5) + every(2, 7, 5)
        now = MONDAY + int(28 * DAY) + int(20 * DAY)
        results = suggest(analyze(journal, now))

        assert results == sorted(results, key=lambda r: -r["score"])

    def test_the_score_is_capped(self):
        journal = every(1, 7, 5)
        now = MONDAY + int(28 * DAY) + int(int(DORMANT_MULTIPLIER) * 7 - 1) * 86400
        results = suggest(analyze(journal, now), horizon_days=7)

        assert all(0 < item["score"] <= 1 for item in results)

    def test_the_limit_is_respected(self):
        journal = []
        for product_id in range(1, 20):
            journal.extend(every(product_id, 7, 5))
        now = MONDAY + int(28 * DAY) + int(9 * DAY)

        assert len(suggest(analyze(journal, now), limit=5)) == 5
