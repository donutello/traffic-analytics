"""Tests for the A-134 parser and detectors on small made-up series."""

import datetime

import pandas as pd
import pytest
from openpyxl import Workbook

from analysis.a134 import detect, parse

SECTION = "км 8+100 а/д А-134"


def make_table(hours: list[tuple[datetime.datetime, float]]) -> pd.DataFrame:
    """A one-section table with the given (hour, volume) pairs; rest plausible defaults."""
    rows = []
    for ts, volume in hours:
        rows.append(
            [
                SECTION,
                ts,
                volume,
                volume / 2,
                volume / 2,
                volume * 0.6,
                10,
                10,
                10,
                5,
                3,
                2,
                90.0,
                88.0,
                5.0,
                4.0,
            ]
        )
    return pd.DataFrame(rows, columns=parse.TABLE_COLUMNS)


def sensors() -> list[dict]:
    known = parse.KNOWN_SENSORS["8+100"]
    return [
        {
            "id": "a134-km8-100",
            "name": SECTION,
            "km": known["km"],
            "lat": known["lat"],
            "lon": known["lon"],
            "directions": {"direct": "на Воронеж", "reverse": "из Воронежа"},
        }
    ]


def hours_of(day: str, count: int) -> list[tuple[datetime.datetime, float]]:
    first = pd.Timestamp(day, tz=parse.MSK).to_pydatetime()
    return [(first.replace(hour=h), 100.0) for h in range(count)]


def write_export(tmp_path, rows) -> None:
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    book.save(tmp_path / "export.xlsx")


def number_row(values) -> list:
    return values + [None] * (30 - len(values))


def test_parse_skips_service_rows_and_keeps_hours(tmp_path):
    write_export(
        tmp_path,
        [
            [SECTION],
            ["Отчёт за март"],
            ["Дата", "Итого", None],
            number_row(
                [
                    datetime.datetime(2024, 3, 8, 10, 0),
                    120,
                    60,
                    60,
                    70,
                    35,
                    35,
                    10,
                    5,
                    5,
                    9,
                    4,
                    5,
                    10,
                    7,
                    3,
                    3,
                    1,
                    2,
                    4,
                    2,
                    2,
                    1,
                    0,
                    1,
                    85.5,
                    90.2,
                    12.5,
                    9.0,
                ]
            ),
            number_row(["Итого", 120]),
            number_row(
                [
                    "09.03.2024 11:00",
                    "130",
                    "65",
                    "65",
                    "75",
                    40,
                    35,
                    12,
                    6,
                    6,
                    10,
                    5,
                    5,
                    12,
                    8,
                    4,
                    3,
                    1,
                    2,
                    5,
                    3,
                    2,
                    1,
                    0,
                    1,
                    "88,5",
                    91,
                    14,
                    10,
                ]
            ),
        ],
    )
    df = parse.parse_traffic_excel(tmp_path / "export.xlsx")

    assert df["section"].eq(SECTION).all()
    assert list(df["ts"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")) == [
        "2024-03-08T10:00:00+0300",
        "2024-03-09T11:00:00+0300",
    ]
    assert df["volume"].tolist() == [120, 130]
    assert df["speed_direct"].tolist() == [85.5, 88.5]


def test_load_raw_drops_duplicated_hours(tmp_path):
    write_export(
        tmp_path,
        [[SECTION], number_row([datetime.datetime(2024, 3, 8, 10, 0), 120])],
    )
    # a second file adds an overlapping and a new hour
    book = Workbook()
    sheet = book.active
    sheet.append([SECTION])
    sheet.append(number_row([datetime.datetime(2024, 3, 8, 10, 0), 999]))
    sheet.append(number_row([datetime.datetime(2024, 3, 8, 11, 0), 80]))
    book.save(tmp_path / "second.xlsx")

    df = parse.load_raw(tmp_path)
    assert len(df) == 2
    assert df.loc[df["ts"].dt.hour == 10, "volume"].item() == 120


def test_sensor_id_and_id_fallback():
    assert parse.sensor_id(SECTION) == "a134-km8-100"
    assert parse.sensor_id("переход через балку", fallback=2) == "a134-02"


def test_build_sensors_uses_known_coordinates():
    sensors = parse.build_sensors([SECTION, "км 99+000 а/д А-134"])
    assert [s["id"] for s in sensors] == ["a134-km8-100", "a134-km99-000"]
    assert sensors[0]["lat"] == pytest.approx(51.7729)
    assert sensors[1]["lat"] is None


def test_flatline_and_missing_hours_detected():
    df = make_table(hours_of("2024-01-15", 6))
    found = detect.detect_all(df, sensors())
    types = {a["type"] for a in found}
    assert {"flatline", "missing_hours"} <= types

    flatline = next(a for a in found if a["type"] == "flatline")
    assert flatline["category"] == "technical"
    assert flatline["level"] == "critical"
    assert flatline["sensor_id"] == "a134-km8-100"
    assert flatline["starts_at"] == "2024-01-15T00:00:00+03:00"
    assert flatline["ends_at"] == "2024-01-15T06:00:00+03:00"
    assert flatline["id"] == "a134-flatline-20240115-01"

    for item in found:
        assert item["detector"] != "" and item["type"] != ""
        assert item["description"]


def test_volume_drop_detected_against_month_norm():
    days = [pd.Timestamp("2024-02", tz=parse.MSK) + pd.Timedelta(days=d) for d in range(28)]
    rows = []
    for day in days:
        calm = day.day not in {14}
        for h in range(24):
            ts = day.replace(hour=h)
            rows.append(
                [
                    SECTION,
                    ts.to_pydatetime(),
                    1000.0 if calm else 100.0,
                    500.0,
                    500.0,
                    600.0,
                    50,
                    50,
                    50,
                    20,
                    20,
                    10,
                    90.0,
                    88.0,
                    10.0,
                    9.0,
                ]
            )
    df = pd.DataFrame(rows, columns=parse.TABLE_COLUMNS)
    found = detect.detect_all(df, sensors())

    drop = next(a for a in found if a["type"] == "volume_drop")
    assert drop["starts_at"] == "2024-02-14T00:00:00+03:00"
    assert drop["actual"] == pytest.approx(2400.0)
    assert drop["expected"] == pytest.approx(24000.0)
    assert drop["deviation_pct"] == pytest.approx(-90.0)
    assert drop["is_mega"] is True


def test_detect_all_on_empty_table():
    assert detect.detect_all(pd.DataFrame(columns=parse.TABLE_COLUMNS), sensors()) == []
