"""Turn meter readings into a usage forecast for the current billing cycle.

Idea in three steps:
1. Consecutive readings give usage per interval, e.g. 92 units over 14 days.
2. Estimate a "typical daily rate" with a recency-weighted average: longer
   intervals count more (they are more reliable), recent ones count more
   (your habits change with the season).
3. Project the cycle: units already used + typical rate x days remaining,
   with a low/high range based on how much your daily usage has varied.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RateEstimate:
    per_day: float  # typical units per day
    spread: float  # weighted standard deviation of units per day
    intervals_used: int


@dataclass(frozen=True)
class CycleProjection:
    cycle_start: date
    cycle_end: date
    used_so_far: float
    remaining_days: int
    expected_units: float
    low_units: float
    high_units: float
    rate: RateEstimate


def _clean(readings: pd.DataFrame) -> pd.DataFrame:
    return readings.sort_values("read_on").reset_index(drop=True)


def usage_intervals(readings: pd.DataFrame) -> pd.DataFrame:
    """Usage between each pair of consecutive readings.

    Columns: start, end, days, units, per_day.
    """
    df = _clean(readings)
    out = pd.DataFrame(
        {
            "start": df["read_on"].shift(1),
            "end": df["read_on"],
            "days": df["read_on"].diff().dt.days,
            "units": df["value"].diff(),
        }
    ).iloc[1:]
    out = out[out["days"] > 0].copy()
    out["days"] = out["days"].astype(int)
    out["per_day"] = out["units"] / out["days"]
    return out.reset_index(drop=True)


def estimate_rate(
    intervals: pd.DataFrame, lookback: int = 6, half_life: float = 3.0
) -> RateEstimate:
    """Recency-weighted average of units/day over the last `lookback` intervals.

    `half_life` is measured in intervals: an interval this many steps back
    counts half as much as the latest one.
    """
    if intervals.empty:
        raise ValueError("Need at least two readings on different dates to estimate usage.")

    recent = intervals.tail(lookback)
    age = np.arange(len(recent))[::-1]  # 0 = most recent interval
    weights = recent["days"].to_numpy(float) * 0.5 ** (age / half_life)
    values = recent["per_day"].to_numpy(float)

    mean = float(np.average(values, weights=weights))
    spread = float(np.sqrt(np.average((values - mean) ** 2, weights=weights)))
    return RateEstimate(per_day=mean, spread=spread, intervals_used=len(recent))


def reading_at(readings: pd.DataFrame, day: date) -> float:
    """Meter value on `day`, linearly interpolated between the surrounding readings."""
    df = _clean(readings)
    xs = np.array([t.toordinal() for t in df["read_on"]], dtype=float)
    target = pd.Timestamp(day).toordinal()
    if target < xs[0] or target > xs[-1]:
        first, last = df["read_on"].iloc[0].date(), df["read_on"].iloc[-1].date()
        raise ValueError(f"{day} is outside your readings ({first} to {last}).")
    return float(np.interp(target, xs, df["value"].to_numpy(float)))


def project_cycle(
    readings: pd.DataFrame,
    cycle_start: date,
    cycle_days: int,
    lookback: int = 6,
    half_life: float = 3.0,
) -> CycleProjection:
    """Project total units for a billing cycle that began on `cycle_start`."""
    if cycle_days <= 0:
        raise ValueError("The billing cycle must be at least one day long.")

    df = _clean(readings)
    rate = estimate_rate(usage_intervals(df), lookback=lookback, half_life=half_life)

    cycle_start = pd.Timestamp(cycle_start).date()
    baseline = reading_at(df, cycle_start)
    latest_day = df["read_on"].iloc[-1].date()
    used = float(df["value"].iloc[-1]) - baseline

    cycle_end = cycle_start + timedelta(days=cycle_days)
    remaining = max((cycle_end - latest_day).days, 0)

    low_rate = max(rate.per_day - rate.spread, 0.0)
    high_rate = rate.per_day + rate.spread
    return CycleProjection(
        cycle_start=cycle_start,
        cycle_end=cycle_end,
        used_so_far=used,
        remaining_days=remaining,
        expected_units=used + rate.per_day * remaining,
        low_units=used + low_rate * remaining,
        high_units=used + high_rate * remaining,
        rate=rate,
    )
