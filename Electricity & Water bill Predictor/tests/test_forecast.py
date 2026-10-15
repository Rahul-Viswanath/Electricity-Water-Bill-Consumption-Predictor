from datetime import date

import pandas as pd
import pytest

from predictor.forecast import estimate_rate, project_cycle, reading_at, usage_intervals


def make(start, steps, first=0.0):
    """Build readings from (days_since_previous, units_used) steps."""
    t, v = pd.Timestamp(start), first
    rows = [(t, v)]
    for days, units in steps:
        t, v = t + pd.Timedelta(days=days), v + units
        rows.append((t, v))
    return pd.DataFrame(rows, columns=["read_on", "value"])


def test_usage_intervals():
    out = usage_intervals(make("2026-01-01", [(10, 50), (20, 80)]))
    assert list(out["days"]) == [10, 20]
    assert list(out["units"]) == [50, 80]
    assert list(out["per_day"]) == [5.0, 4.0]


def test_usage_intervals_sorts_unordered_input():
    shuffled = make("2026-01-01", [(10, 50), (10, 50)]).iloc[[2, 0, 1]]
    assert list(usage_intervals(shuffled)["per_day"]) == [5.0, 5.0]


def test_constant_usage_gives_constant_rate_and_no_spread():
    rate = estimate_rate(usage_intervals(make("2026-01-01", [(10, 50)] * 5)))
    assert rate.per_day == pytest.approx(5.0)
    assert rate.spread == pytest.approx(0.0, abs=1e-9)


def test_recent_intervals_count_more():
    # Usage doubles in the latest interval; plain mean would be 6.25.
    steps = [(10, 50)] * 3 + [(10, 100)]
    rate = estimate_rate(usage_intervals(make("2026-01-01", steps)))
    assert 6.25 < rate.per_day < 10.0


def test_single_interval_has_zero_spread():
    rate = estimate_rate(usage_intervals(make("2026-01-01", [(10, 50)])))
    assert rate.per_day == pytest.approx(5.0)
    assert rate.spread == 0.0


def test_one_reading_cannot_be_forecast():
    with pytest.raises(ValueError):
        estimate_rate(usage_intervals(make("2026-01-01", [])))


def test_reading_at_interpolates():
    df = make("2026-01-01", [(10, 50)])
    assert reading_at(df, date(2026, 1, 6)) == pytest.approx(25)


def test_reading_at_outside_range_raises():
    df = make("2026-01-01", [(10, 50)])
    with pytest.raises(ValueError):
        reading_at(df, date(2025, 12, 1))


def test_project_cycle_midway():
    # 5 units/day, 10 days into a 30-day cycle: 50 used + 20 days * 5 = 150.
    df = make("2026-01-01", [(5, 25), (5, 25)])
    proj = project_cycle(df, date(2026, 1, 1), cycle_days=30)
    assert proj.used_so_far == pytest.approx(50)
    assert proj.remaining_days == 20
    assert proj.expected_units == pytest.approx(150)
    assert proj.low_units <= proj.expected_units <= proj.high_units


def test_project_cycle_already_finished_equals_usage_to_date():
    df = make("2026-01-01", [(5, 25), (5, 25)])
    proj = project_cycle(df, date(2026, 1, 1), cycle_days=5)
    assert proj.remaining_days == 0
    assert proj.expected_units == pytest.approx(50)


def test_project_cycle_range_widens_with_variable_usage():
    steady = project_cycle(make("2026-01-01", [(10, 50)] * 4), date(2026, 1, 1), 60)
    bumpy = project_cycle(
        make("2026-01-01", [(10, 20), (10, 90), (10, 30), (10, 80)]), date(2026, 1, 1), 60
    )
    assert (bumpy.high_units - bumpy.low_units) > (steady.high_units - steady.low_units)


def test_project_cycle_rejects_start_before_first_reading():
    df = make("2026-01-01", [(5, 25)])
    with pytest.raises(ValueError):
        project_cycle(df, date(2025, 12, 1), cycle_days=30)


def test_project_cycle_rejects_zero_length_cycle():
    df = make("2026-01-01", [(5, 25)])
    with pytest.raises(ValueError):
        project_cycle(df, date(2026, 1, 1), cycle_days=0)
