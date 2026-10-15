from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from predictor import db

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_readings.csv"


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    yield connection
    connection.close()


def test_add_and_fetch_sorted_by_date(conn):
    db.add_reading(conn, "electricity", date(2026, 2, 1), 120)
    db.add_reading(conn, "electricity", date(2026, 1, 1), 100)
    df = db.get_readings(conn, "electricity")
    assert list(df["value"]) == [100, 120]
    assert df["read_on"].is_monotonic_increasing


def test_reading_lower_than_earlier_one_is_rejected(conn):
    db.add_reading(conn, "electricity", date(2026, 1, 1), 100)
    with pytest.raises(ValueError, match="earlier"):
        db.add_reading(conn, "electricity", date(2026, 2, 1), 90)


def test_reading_higher_than_later_one_is_rejected(conn):
    db.add_reading(conn, "electricity", date(2026, 2, 1), 120)
    with pytest.raises(ValueError, match="later"):
        db.add_reading(conn, "electricity", date(2026, 1, 15), 130)


def test_negative_reading_is_rejected(conn):
    with pytest.raises(ValueError):
        db.add_reading(conn, "electricity", date(2026, 1, 1), -5)


def test_same_day_reading_is_updated_not_duplicated(conn):
    db.add_reading(conn, "electricity", date(2026, 1, 1), 100)
    db.add_reading(conn, "electricity", date(2026, 1, 1), 105)
    df = db.get_readings(conn, "electricity")
    assert list(df["value"]) == [105]


def test_utilities_are_kept_separate(conn):
    db.add_reading(conn, "electricity", date(2026, 1, 1), 100)
    db.add_reading(conn, "water", date(2026, 1, 1), 7)
    assert list(db.get_readings(conn, "water")["value"]) == [7]


def test_delete_reading(conn):
    db.add_reading(conn, "electricity", date(2026, 1, 1), 100)
    db.delete_reading(conn, "electricity", date(2026, 1, 1))
    assert db.get_readings(conn, "electricity").empty


def test_import_skips_bad_rows_and_reports_them(conn):
    frame = pd.DataFrame(
        {
            "Date": ["2026-01-01", "2026-01-15", "not a date", "2026-02-01"],
            "Reading": [100, 110, 120, 105],  # last one goes backwards
        }
    )
    added, problems = db.import_csv(conn, "electricity", frame)
    assert added == 2
    assert len(problems) == 2


def test_import_requires_expected_columns(conn):
    with pytest.raises(ValueError):
        db.import_csv(conn, "electricity", pd.DataFrame({"when": [1], "kwh": [2]}))


def test_sample_data_imports_cleanly(conn):
    added, problems = db.import_csv(conn, "electricity", pd.read_csv(SAMPLE))
    assert added == 20
    assert problems == []
