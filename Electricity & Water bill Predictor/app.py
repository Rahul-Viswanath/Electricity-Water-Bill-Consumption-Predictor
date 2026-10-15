"""Meter Usage Predictor: log readings, see usage trends, project the next bill.

Run with:  streamlit run app.py
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from predictor import db
from predictor.forecast import project_cycle, usage_intervals
from predictor.tariff import compute_bill, load_tariffs

CURRENCY = "₹"
SAMPLE_CSV = Path(__file__).parent / "data" / "sample_readings.csv"

st.set_page_config(page_title="Meter Usage Predictor", page_icon="⚡", layout="wide")
st.title("Meter Usage Predictor")
st.caption("Log your meter readings, see how your usage is trending, and estimate your next bill.")

conn = db.connect()
tariffs = load_tariffs()

# ------------------------------------------------------------------ sidebar
utility = st.sidebar.radio("Utility", list(tariffs), format_func=str.title)
tariff = tariffs[utility]
unit = tariff.unit_label

cycle_days = st.sidebar.number_input(
    "Billing cycle length (days)",
    min_value=7,
    max_value=400,
    value=60,
    step=1,
    help="How often you are billed, e.g. 30 for monthly or 60 for every two months.",
)

with st.sidebar.expander("Tariff in use"):
    st.write(f"**{tariff.name}** ({tariff.mode.replace('_', ' ')})")
    slab_rows, lower = [], 0.0
    for slab in tariff.slabs:
        label = f"{lower:g}+" if slab.upto is None else f"{lower:g} to {slab.upto:g}"
        slab_rows.append({f"Slab ({unit})": label, f"Rate ({CURRENCY}/{unit})": slab.rate})
        lower = slab.upto or lower
    st.table(pd.DataFrame(slab_rows))
    st.write(f"Fixed charge: {CURRENCY}{tariff.fixed_charge:,.2f}  |  Tax/duty: {tariff.tax_percent:g}%")
    st.caption("These are placeholder rates. Edit tariffs.json to match your own bill.")

st.sidebar.divider()
st.sidebar.subheader("Data")

if st.sidebar.button("Load sample electricity data"):
    added, problems = db.import_csv(conn, "electricity", pd.read_csv(SAMPLE_CSV))
    st.sidebar.success(f"Loaded {added} sample readings. Switch to Electricity to see them.")
    for problem in problems[:3]:
        st.sidebar.warning(problem)

upload = st.sidebar.file_uploader("Import CSV (columns: date, reading)", type="csv")
if upload is not None and st.sidebar.button(f"Import into {utility}"):
    try:
        added, problems = db.import_csv(conn, utility, pd.read_csv(upload))
    except ValueError as exc:
        st.sidebar.error(str(exc))
    else:
        st.sidebar.success(f"Imported {added} readings.")
        for problem in problems[:5]:
            st.sidebar.warning(problem)

# ------------------------------------------------------------------ add a reading
readings = db.get_readings(conn, utility)

st.subheader(f"Log a {utility} reading")
with st.form("add_reading"):
    col_date, col_value = st.columns(2)
    read_on = col_date.date_input("Reading date", value=date.today(), max_value=date.today())
    default_value = float(readings["value"].iloc[-1]) if not readings.empty else 0.0
    value = col_value.number_input(
        f"Meter reading ({unit})", min_value=0.0, value=default_value, step=1.0, format="%.1f"
    )
    submitted = st.form_submit_button("Save reading")

if submitted:
    try:
        db.add_reading(conn, utility, read_on, value)
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.success(f"Saved {value:g} {unit} for {read_on}.")
        readings = db.get_readings(conn, utility)

with st.expander(f"All readings ({len(readings)})"):
    if readings.empty:
        st.write("No readings yet.")
    else:
        shown = readings.assign(read_on=readings["read_on"].dt.date).rename(
            columns={"read_on": "Date", "value": f"Reading ({unit})"}
        )
        st.dataframe(shown, hide_index=True)
        to_delete = st.selectbox("Delete a reading", shown["Date"], index=None, placeholder="Pick a date")
        if to_delete is not None and st.button("Delete selected reading"):
            db.delete_reading(conn, utility, to_delete)
            st.rerun()

if len(readings) < 2:
    st.info(
        "Add at least two readings on different dates to get an estimate. "
        "Tip: load the sample data from the sidebar to see how it looks."
    )
    st.stop()

# ------------------------------------------------------------------ usage trend
intervals = usage_intervals(readings)

st.subheader("Usage trend")
trend = intervals.set_index("end")[["per_day"]].rename(columns={"per_day": f"{unit} per day"})
st.bar_chart(trend)

# ------------------------------------------------------------------ projection
first_day = readings["read_on"].iloc[0].date()
last_day = readings["read_on"].iloc[-1].date()
cutoff = last_day - timedelta(days=14)
earlier_days = [t.date() for t in readings["read_on"] if t.date() <= cutoff]
default_start = earlier_days[-1] if earlier_days else first_day

st.subheader("Projected bill for this cycle")
cycle_start = st.date_input(
    "This billing cycle started on",
    value=default_start,
    min_value=first_day,
    max_value=last_day,
    help="Use the date of your last bill or last meter reading by the utility.",
)

try:
    projection = project_cycle(readings, cycle_start, int(cycle_days))
except ValueError as exc:
    st.error(str(exc))
    st.stop()

low, expected, high = (
    compute_bill(units, tariff)
    for units in (projection.low_units, projection.expected_units, projection.high_units)
)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Typical daily use", f"{projection.rate.per_day:.1f} {unit}")
m2.metric("Used so far", f"{projection.used_so_far:,.0f} {unit}")
m3.metric(
    "Projected total",
    f"{projection.expected_units:,.0f} {unit}",
    help=f"Likely range: {projection.low_units:,.0f} to {projection.high_units:,.0f} {unit}",
)
m4.metric(
    "Projected bill",
    f"{CURRENCY}{expected.total:,.0f}",
    help=f"Likely range: {CURRENCY}{low.total:,.0f} to {CURRENCY}{high.total:,.0f}",
)

st.caption(
    f"Cycle runs {projection.cycle_start} to {projection.cycle_end}, with "
    f"{projection.remaining_days} days left. The range reflects how much your daily "
    f"usage has varied over the last {projection.rate.intervals_used} readings."
)

with st.expander("Bill breakdown"):
    breakdown = pd.DataFrame(
        {
            "Low": [low.units, low.energy_charge, low.fixed_charge, low.tax, low.total],
            "Expected": [expected.units, expected.energy_charge, expected.fixed_charge, expected.tax, expected.total],
            "High": [high.units, high.energy_charge, high.fixed_charge, high.tax, high.total],
        },
        index=[f"Units ({unit})", f"Usage charge ({CURRENCY})", f"Fixed charge ({CURRENCY})", f"Tax/duty ({CURRENCY})", f"Total ({CURRENCY})"],
    ).round(2)
    st.dataframe(breakdown)

st.caption("Estimates only. Your utility's actual bill is the source of truth.")
