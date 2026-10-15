"""SQLite storage for meter readings."""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "meter.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utility TEXT NOT NULL,
    read_on TEXT NOT NULL,
    value REAL NOT NULL,
    UNIQUE (utility, read_on)
)
"""


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open (and create if needed) the readings database."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def _iso(day: date) -> str:
    return pd.Timestamp(day).date().isoformat()


def get_readings(conn: sqlite3.Connection, utility: str) -> pd.DataFrame:
    """Return all readings for a utility, oldest first, as columns read_on, value."""
    df = pd.read_sql_query(
        "SELECT read_on, value FROM readings WHERE utility = ? ORDER BY read_on",
        conn,
        params=(utility,),
    )
    df["read_on"] = pd.to_datetime(df["read_on"])
    return df


def add_reading(conn: sqlite3.Connection, utility: str, read_on: date, value: float) -> None:
    """Insert a reading, or update it if one already exists for that date.

    A meter only counts upwards, so a reading lower than an earlier one (or higher
    than a later one) is almost certainly a typo and is rejected.
    """
    if value < 0:
        raise ValueError("A meter reading cannot be negative.")
    iso = _iso(read_on)

    earlier = conn.execute(
        "SELECT value FROM readings WHERE utility = ? AND read_on < ? "
        "ORDER BY read_on DESC LIMIT 1",
        (utility, iso),
    ).fetchone()
    later = conn.execute(
        "SELECT value FROM readings WHERE utility = ? AND read_on > ? "
        "ORDER BY read_on ASC LIMIT 1",
        (utility, iso),
    ).fetchone()

    if earlier and value < earlier[0]:
        raise ValueError(
            f"{value:g} is lower than the earlier reading of {earlier[0]:g}. "
            "Meters only go up. Check for a typo, or a meter replacement."
        )
    if later and value > later[0]:
        raise ValueError(
            f"{value:g} is higher than the later reading of {later[0]:g}. "
            "Check the date and the value."
        )

    conn.execute(
        "INSERT INTO readings (utility, read_on, value) VALUES (?, ?, ?) "
        "ON CONFLICT (utility, read_on) DO UPDATE SET value = excluded.value",
        (utility, iso, float(value)),
    )
    conn.commit()


def delete_reading(conn: sqlite3.Connection, utility: str, read_on: date) -> None:
    conn.execute(
        "DELETE FROM readings WHERE utility = ? AND read_on = ?", (utility, _iso(read_on))
    )
    conn.commit()


def import_csv(conn: sqlite3.Connection, utility: str, df: pd.DataFrame) -> tuple[int, list[str]]:
    """Import rows from a DataFrame with 'date' (YYYY-MM-DD) and 'reading' columns.

    Returns (rows_added, list_of_problems). Bad rows are skipped, not fatal.
    """
    lookup = {str(col).strip().lower(): col for col in df.columns}
    if not {"date", "reading"} <= lookup.keys():
        raise ValueError("The CSV needs 'date' and 'reading' columns.")

    rows = pd.DataFrame(
        {
            "raw_date": df[lookup["date"]],
            "date": pd.to_datetime(df[lookup["date"]], errors="coerce"),
            "reading": pd.to_numeric(df[lookup["reading"]], errors="coerce"),
        }
    )

    errors: list[str] = []
    bad = rows[rows["date"].isna() | rows["reading"].isna()]
    for _, row in bad.iterrows():
        errors.append(f"Skipped unreadable row: date={row['raw_date']!r}")

    added = 0
    for _, row in rows.drop(bad.index).sort_values("date").iterrows():
        try:
            add_reading(conn, utility, row["date"].date(), float(row["reading"]))
        except ValueError as exc:
            errors.append(f"{row['date'].date()}: {exc}")
        else:
            added += 1
    return added, errors
