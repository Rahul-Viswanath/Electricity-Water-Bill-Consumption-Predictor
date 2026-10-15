# Meter Usage Predictor

Log your electricity or water meter readings, see how your usage is trending, and get an estimate of your next bill before it arrives.

Built with Python, SQLite, pandas and Streamlit.

## What it does

- Stores meter readings per utility (electricity, water) in a local SQLite database
- Rejects impossible readings (a meter never goes backwards)
- Shows usage per day for every interval between readings
- Projects the current billing cycle: units used so far + typical daily use x days remaining
- Gives a low / expected / high range, based on how much your usage has varied
- Converts projected units into a rupee bill using a configurable slab tariff, fixed charge and tax
- Imports readings from CSV and ships with sample data

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Then click **Load sample electricity data** in the sidebar to see it working.

Run the tests:

```bash
pytest
```

## Set your own tariff

`tariffs.json` ships with **placeholder rates**. Copy the slabs, fixed charge and tax from your latest bill:

```json
"electricity": {
  "name": "My tariff",
  "unit_label": "kWh",
  "mode": "telescopic",
  "fixed_charge": 100.0,
  "tax_percent": 10.0,
  "slabs": [
    { "upto": 100, "rate": 3.5 },
    { "upto": null, "rate": 9.5 }
  ]
}
```

- `telescopic`: each slab's rate applies only to the units inside that slab.
- `flat_slab`: the slab your total lands in sets the rate for all units.
- Slabs are per billing cycle. Use the same cycle length you set in the sidebar.

## How the prediction works

1. **Intervals.** Two consecutive readings give units used over some number of days, so a daily rate.
2. **Typical rate.** A weighted average of the last few daily rates. Longer intervals weigh more because they are more reliable, and recent intervals weigh more because usage changes with the season (an AC in summer, a geyser in winter). The weighting is controlled by `lookback` and `half_life` in `predictor/forecast.py`.
3. **Projection.** `units so far + typical rate x remaining days`. The low and high cases use the rate minus or plus one weighted standard deviation.
4. **Bill.** Units go through the tariff: usage charge by slab, plus fixed charge, plus tax.

The more regularly you log readings, the better it gets. Every two weeks works well.

## Project layout

```
app.py                 Streamlit interface
predictor/
  db.py                SQLite storage and CSV import
  forecast.py          Usage intervals, rate estimate, cycle projection
  tariff.py            Slab tariff and bill calculation
tariffs.json           Your tariff settings
data/sample_readings.csv
tests/                 pytest suite for db, forecast and tariff logic
```

The calculation code is separate from the UI, so it can be tested and reused (for example by a Telegram bot or an API).

## Ideas to extend it

- **Seasonality:** compare with the same period last year, or fit a model with `scikit-learn` using month and temperature as features
- **Backtesting:** predict each past cycle from the readings before it and report the average error. A real accuracy number is great README material
- **Alerts:** a Telegram message when the projected bill crosses your budget, or when you are about to move into a higher slab
- **Photo input:** read the meter from a photo with OCR
- **Multiple meters or households**, with a login
- **REST API** with FastAPI, then deploy the app (Streamlit Community Cloud, Render or Docker)
- **Smart meter data:** import the CSV export from your utility's portal if it offers one

## Limitations

- The forecast is a statistical estimate, not your utility's official bill. Their rounding, surcharges and subsidies may differ.
- Meter replacements and rollovers are not handled yet. Rejected readings are the only protection.
