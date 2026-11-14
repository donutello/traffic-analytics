"""Tests for the A-134 module: parser, failures, gap fill, detectors, linking, output.

Everything here runs on small made-up series; the thresholds tested are the ones the
module README settles (issues #24/#25)."""

import datetime

import pandas as pd
import pytest
from openpyxl import Workbook

from analysis.a134 import corporate, detect, events, holidays, parse, pipeline, quality

SECTION = "км 8+100 а/д А-134"
SID = "a134-km8-100"
SENSOR_IDS = {SECTION: SID}


def raw_row(ts, volume, speed=88.0, load=5.0) -> list:
    """One raw-table row at plausible defaults; only the knobs a test needs vary."""
    return [
        SECTION,
        ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts,
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
        speed,
        88.0,
        load,
        4.0,
    ]


def make_table(rows: list[list]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=parse.TABLE_COLUMNS)


def day_rows(day: str, volume: float = 200.0, flat: bool = False, **overrides) -> list[list]:
    """One day of raw rows; `flat` keeps the volume identical (for flatline tests),
    otherwise it wobbles hour by hour so ordinary days never look stuck."""
    first = pd.Timestamp(day, tz=parse.MSK)
    rows = []
    for h in range(24):
        value = volume if flat else volume + 7.0 * (h % 4)
        rows.append(raw_row(first.replace(hour=h), value, **overrides))
    return rows


def filled_frame(specs: list[tuple[str, dict]]) -> pd.DataFrame:
    """A gap-filled-table frame from (iso-ts, values) specs; defaults look normal."""
    columns = [
        "section",
        "sensor_id",
        "ts",
        "volume",
        "speed_direct",
        "load_direct",
        "large_trucks",
        "road_trains",
        "imputation_method",
    ]
    rows = []
    for ts, values in specs:
        rows.append(
            [
                SECTION,
                SID,
                pd.Timestamp(ts, tz=parse.MSK),
                values.get("volume", 1000.0),
                values.get("speed_direct", 85.0),
                values.get("load_direct", 5.0),
                10.0,
                5.0,
                values.get("imputation_method", ""),
            ]
        )
    frame = pd.DataFrame(rows, columns=columns)
    frame["ts"] = pd.to_datetime(frame["ts"])
    return frame


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
    write_export(tmp_path, [[SECTION], number_row([datetime.datetime(2024, 3, 8, 10, 0), 120])])
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
    assert parse.sensor_id("км 4+700 а/д А-134") == "a134-km4-700"
    assert parse.sensor_id("переход через балку", fallback=2) == "a134-02"


def test_utc_labelled_early_hours_are_moved_to_local_time(tmp_path):
    # the merged report labels every 2023 hour 3 h in front of the 2024+ clock (#real
    # export): the parser shifts those early labels by +3 h and drops the ones that
    # then re-report an hour the corrected recorder had already written itself
    write_export(
        tmp_path,
        [
            [SECTION],
            number_row([datetime.datetime(2023, 12, 1, 1, 0), 120]),
            number_row([datetime.datetime(2023, 12, 26, 23, 0), 130]),
            number_row([datetime.datetime(2024, 3, 8, 10, 0), 140]),
        ],
    )
    df = parse.parse_traffic_excel(tmp_path / "export.xlsx")
    assert list(df["ts"].dt.strftime("%Y-%m-%dT%H")) == ["2023-12-01T04", "2024-03-08T10"]
    assert df["volume"].tolist() == [120, 140]


def test_build_sensors_uses_known_coordinates():
    # only km 8+100 exists in the real export; a new section must come with coordinates
    sensors = parse.build_sensors([SECTION, "км 4+700 а/д А-134", "км 99+000 а/д А-134"])
    assert [s["id"] for s in sensors] == ["a134-km4-700", "a134-km8-100", "a134-km99-000"]
    known = next(s for s in sensors if s["id"] == SID)
    assert known["lat"] == pytest.approx(51.7729)
    assert all(s["lat"] is None for s in sensors if s["id"] != SID)


def test_day_kind_uses_the_official_calendar():
    d = datetime.date
    assert holidays.day_kind(d(2023, 1, 3)) == "holiday"  # New Year holidays
    assert holidays.day_kind(d(2023, 2, 24)) == "holiday"  # day moved from Jan 1 (Decree 1505)
    assert holidays.day_kind(d(2024, 5, 10)) == "holiday"  # day moved (Decree 1314)
    assert holidays.day_kind(d(2025, 11, 3)) == "holiday"  # day moved (Decree 1335)
    assert holidays.day_kind(d(2026, 3, 9)) == "holiday"  # extra Monday (Decree 1466)
    assert holidays.day_kind(d(2026, 12, 31)) == "holiday"  # day moved from Jan 4 (1466)
    assert holidays.day_kind(d(2024, 7, 6)) == "weekend"
    assert holidays.day_kind(d(2024, 7, 4)) == "weekday"


def test_level_from_score_is_the_contract_table_exactly():
    assert detect.level_from_score(9.9) == "critical"
    assert detect.level_from_score(5.0) == "critical"
    assert detect.level_from_score(4.9) == "high"
    assert detect.level_from_score(3.5) == "high"
    assert detect.level_from_score(3.4) == "medium"
    assert detect.level_from_score(2.0) == "medium"
    assert detect.level_from_score(1.9) == "low"
    with pytest.raises(ValueError):
        detect.level_from_score(None)


# --- technical failures (issue #24) -------------------------------------------------


def test_flatline_detected_and_hours_marked_untrusted():
    rows = []
    for day in pd.date_range("2024-01-13", "2024-01-20", freq="D"):
        rows += day_rows(day.date().isoformat(), volume=200.0 + day.dayofyear % 7)
    stuck_start = pd.Timestamp("2024-01-15 00:00", tz=parse.MSK)
    for h in range(6):  # six identical hours in a row: the sensor froze
        rows[24 * 2 + h] = raw_row(stuck_start + pd.Timedelta(hours=h), 437.0)
    df = make_table(rows)

    found, bad_hours = quality.detect_failures(df, SENSOR_IDS)
    flat = next(a for a in found if a["type"] == "flatline")
    assert flat["category"] == "technical"
    assert flat["level"] == "high"  # score 4.0 sits in the high band of contract v1
    assert flat["starts_at"] == "2024-01-15T00:00:00+03:00"
    assert flat["ends_at"] == "2024-01-15T06:00:00+03:00"
    assert flat["description"]
    assert len(bad_hours[SID]) == 6


def test_fluctuating_hours_are_normal_but_a_dead_speed_channel_is_caught():
    rows = []
    for h in range(24):  # a day with moving volume: no flatline anywhere in it
        ts = pd.Timestamp("2024-03-04", tz=parse.MSK) + pd.Timedelta(hours=h)
        rows.append(raw_row(ts, 190.0 + 20 * (h % 2)))
    flat_day = day_rows("2024-03-05", flat=True)  # one day-volume all day: it froze
    df = make_table([*rows, *flat_day])
    found, bad_hours = quality.detect_failures(df, SENSOR_IDS)
    flat = [a for a in found if a["type"] == "flatline"]
    assert [a["starts_at"] for a in flat] == ["2024-03-05T00:00:00+03:00"]
    assert flat[0]["expected"] is None
    assert flat[0]["level"] == "high"
    all_bad = set(bad_hours[SID])
    assert len(all_bad) == 24

    rows = []  # a day where cars pass but the speed sensor reads zero for 8 hours
    for h in range(24):
        ts = pd.Timestamp("2024-03-06", tz=parse.MSK) + pd.Timedelta(hours=h)
        rows.append(raw_row(ts, 190.0 + 20 * (h % 2), speed=0.0 if 3 <= h < 11 else 88.0))
    found, bad_hours = quality.detect_failures(make_table(rows), SENSOR_IDS)
    zero = [a for a in found if a["type"] == "zero_speed"]
    assert len(zero) == 1 and zero[0]["level"] == "medium"
    assert zero[0]["starts_at"] == "2024-03-06T03:00:00+03:00"
    assert len(bad_hours[SID]) == 8

    rows = []  # one dropped speed hour: repaired quietly, no anomaly of its own
    for h in range(24):
        ts = pd.Timestamp("2024-03-07", tz=parse.MSK) + pd.Timedelta(hours=h)
        rows.append(raw_row(ts, 190.0 + 20 * (h % 2), speed=0.0 if h == 6 else 88.0))
    found, bad_hours = quality.detect_failures(make_table(rows), SENSOR_IDS)
    assert all(a["type"] != "zero_speed" for a in found)
    assert len(bad_hours[SID]) == 1


def test_missing_hours_reported_per_short_day():
    rows = []
    for day in pd.date_range("2024-03-04", "2024-03-07", freq="D"):
        iso = day.date().isoformat()
        if iso == "2024-03-05":
            rows += day_rows(iso)[:12] + day_rows(iso)[18:]  # 18 of 24 hours survived
        else:
            rows += day_rows(iso, volume=150.0 + day.day)
    df = make_table(rows)

    found, _ = quality.detect_failures(df, SENSOR_IDS)
    missing = [a for a in found if a["type"] == "missing_hours"]
    assert len(missing) == 1 and missing[0]["actual"] == 18.0
    assert missing[0]["level"] == "medium" and missing[0]["detector"] == "integrity"


def test_one_blind_direction_on_busy_hours_is_caught():
    rows = day_rows("2024-03-04", volume=1000.0)  # 50/50: normal
    rows += day_rows("2024-03-05", volume=900.0)
    for r in rows[24:]:  # every hour reads one loop only: the reverse tube died
        r[3] = r[2]
        r[4] = 0.0
    df = make_table(rows)

    found, bad_hours = quality.detect_failures(df, SENSOR_IDS)
    imbalance = [a for a in found if a["type"] == "direction_imbalance"]
    assert len(imbalance) == 1
    assert imbalance[0]["starts_at"] == "2024-03-05T00:00:00+03:00"
    assert imbalance[0]["ends_at"] == "2024-03-06T00:00:00+03:00"
    assert "обратного" in imbalance[0]["description"]
    assert len(bad_hours[SID]) == 24

    lonely = day_rows("2024-03-06", volume=900.0)  # one starved hour: repaired, not reported
    lonely[7][3] = lonely[7][2]
    lonely[7][4] = 0.0
    found_lonely, bad_lonely = quality.detect_failures(make_table(lonely), SENSOR_IDS)
    assert all(a["type"] != "direction_imbalance" for a in found_lonely)
    assert len(bad_lonely[SID]) == 1

    quiet = make_table(day_rows("2024-03-07", volume=10.0))  # barely counted: one loop is noise
    found_quiet, _ = quality.detect_failures(quiet, SENSOR_IDS)
    assert all(a["type"] != "direction_imbalance" for a in found_quiet)


def test_empty_table_is_safe():
    found, bad_hours = quality.detect_failures(pd.DataFrame(columns=parse.TABLE_COLUMNS), {})
    assert found == [] and bad_hours == {}


# --- gap fill (issue #24) -------------------------------------------------------------


def build_july_with_holes(hole_day: str, hole_from: int, hole_to: int) -> pd.DataFrame:
    rows = []
    for day in pd.date_range("2024-07-01", "2024-07-28", freq="D"):
        iso = day.date().isoformat()
        volume = 980.0 if day.day % 2 else 1020.0
        for h in range(24):
            ts = day + pd.Timedelta(hours=h)
            if iso == hole_day and hole_from <= h < hole_to:
                continue
            rows.append(raw_row(ts, volume))
    return make_table(rows)


def test_short_hole_is_interpolated():
    filled = quality.fill_gaps(build_july_with_holes("2024-07-09", 10, 12), {}, SENSOR_IDS)
    day = filled[filled["ts"].dt.strftime("%Y-%m-%d").eq("2024-07-09")]
    at_gap = day[day["imputation_method"] != ""]
    assert len(at_gap) == 2
    assert set(at_gap["imputation_method"]) == {"interpolation"}
    assert at_gap["volume"].tolist() == pytest.approx([980.0, 980.0])


def test_long_hole_gets_the_day_profile_median():
    filled = quality.fill_gaps(build_july_with_holes("2024-07-17", 8, 15), {}, SENSOR_IDS)
    day = filled[filled["ts"].dt.strftime("%Y-%m-%d").eq("2024-07-17")]
    filled_hours = day[day["imputation_method"] != ""]
    assert len(filled_hours) == 7  # the 7-hour hole: some edge hours are interpolated
    assert set(filled_hours["imputation_method"]) <= {"interpolation", "profile"}
    assert "profile" in set(filled_hours["imputation_method"])  # the middle uses norms
    assert filled_hours["volume"].between(970.0, 1030.0).all()


def test_untrusted_hours_are_replaced_and_marked():
    df = build_july_with_holes("2024-07-24", 0, 0)
    bad = {SID: set(df.loc[df["ts"].dt.strftime("%Y-%m-%d") == "2024-07-24", "ts"])}
    filled = quality.fill_gaps(df, bad, SENSOR_IDS)
    day = filled[filled["ts"].dt.strftime("%Y-%m-%d").eq("2024-07-24")]
    assert (day["imputation_method"] != "").all()  # every stuck hour went imputed
    assert day["volume"].min() > 900.0  # the recorded values are gone, the norm stands


def test_fill_output_is_a_complete_hourly_grid():
    filled = quality.fill_gaps(build_july_with_holes("2024-07-10", 10, 12), {}, SENSOR_IDS)
    hours = filled["ts"]
    assert len(filled) == 28 * 24
    assert (hours.diff().dropna() == pd.Timedelta(hours=1)).all()


# --- traffic detectors (issue #25) ----------------------------------------------------


def july_fill(day_specs: dict[str, dict]) -> pd.DataFrame:
    """Two quiet Julys at 1000 avt/ch (hour wobble keeps every day-sum identical, so
    only the explicitly given day overrides can trigger any detector)."""
    specs = []
    for year in (2023, 2024):
        for day in range(1, 32):
            key = f"{year}-07-{day:02d}"
            override = day_specs.get(key, {})
            for h in range(24):
                in_window = (
                    "hours" not in override or override["hours"][0] <= h < override["hours"][1]
                )
                values = {"volume": 1030.0 if day % 2 else 970.0}
                if in_window:
                    values.update({k: v for k, v in override.items() if k != "hours"})
                specs.append((f"{key}T{h:02d}:00", values))
    return filled_frame(specs)


def test_hourly_drop_reports_the_exact_interval():
    filled = july_fill({"2024-07-11": {"volume": 100.0, "hours": (8, 14)}})
    found = detect.detect_traffic(filled, {SECTION: SID})
    hourly = [a for a in found if a["detector"] == "amplitude" and a["metric"] == "volume"]
    assert len(hourly) == 1  # the day-sum is -23%: below the daily bar, only hours fire
    item = hourly[0]
    assert item["type"] == "volume_drop"
    assert item["starts_at"] == "2024-07-11T08:00:00+03:00"
    assert item["ends_at"] == "2024-07-11T14:00:00+03:00"
    assert item["deviation_pct"] == pytest.approx(-90.0)
    assert item["level"] == "critical"  # z-score of 20 tops out at 9.9 -> critical
    assert item["is_mega"] is False  # the mega flag arrives with finalize


def test_hourly_spike_and_speed_drop_detected():
    filled = july_fill(
        {
            "2024-07-11": {"volume": 2100.0, "hours": (10, 16)},
            "2024-07-16": {"speed_direct": 30.0, "hours": (8, 16)},
        }
    )
    found = detect.detect_traffic(filled, {SECTION: SID})
    spike = [
        a
        for a in found
        if a["type"] == "volume_spike" and a["starts_at"] == "2024-07-11T10:00:00+03:00"
    ]
    slow = [a for a in found if a["type"] == "speed_drop"]
    assert len(spike) == 1 and spike[0]["actual"] > spike[0]["expected"]
    assert len(slow) == 1 and slow[0]["metric"] == "speed_direct"
    assert slow[0]["starts_at"] == "2024-07-16T08:00:00+03:00"


def test_daily_extreme_is_flagged_whole_day():
    filled = july_fill({"2024-07-20": {"volume": 100.0}})
    found = detect.detect_traffic(filled, {SECTION: SID})
    daily = [
        a
        for a in found
        if a["type"] == "volume_drop" and a["starts_at"] == "2024-07-20T00:00:00+03:00"
    ]
    assert len(daily) == 2  # 24 deviant hours collapse into one hourly run and one day
    assert any(a["detector"] == "amplitude" and a["actual"] == pytest.approx(2400.0) for a in daily)


def test_imputed_hours_never_count_as_traffic():
    filled = july_fill(
        {"2024-07-10": {"volume": 100.0, "hours": (8, 14), "imputation_method": "profile"}}
    )
    filled.loc[(filled["ts"].dt.strftime("%Y-%m-%d") == "2024-07-10"), "imputation_method"] = (
        "profile"
    )
    assert detect.detect_traffic(filled, {SECTION: SID}) == []


def test_congestion_needs_slow_and_loaded_hours_in_a_row():
    base = july_fill({})
    extra_days = []
    ts = pd.Timestamp("2023-07-03T17:00", tz=parse.MSK)
    for offset in range(3):  # three slow loaded hours: a real queue
        extra_days.append(
            (
                (ts + pd.Timedelta(hours=offset)).isoformat(),
                {"speed_direct": 45.0, "load_direct": 30.0},
            )
        )
    extra_days.append(
        ("2023-07-05T12:00", {"speed_direct": 40.0, "load_direct": 33.0})  # lone hour: noise
    )
    filled = filled_frame(
        [
            (r["ts"].isoformat(), {k: r[k] for k in ("volume", "speed_direct", "load_direct")})
            for _, r in base.iterrows()
            if r["ts"].strftime("%Y-%m-%d") not in ("2023-07-03", "2023-07-05")
        ]
        + extra_days
    )
    found = detect.detect_traffic(filled, {SECTION: SID})
    congestion = [a for a in found if a["type"] == "congestion"]
    assert len(congestion) == 1
    assert congestion[0]["starts_at"] == "2023-07-03T17:00:00+03:00"
    assert congestion[0]["level"] == "high"


def test_profile_shift_on_a_day_shaped_backwards():
    specs = []
    for year in (2023, 2024):
        for day in range(1, 32):
            key = f"{year}-07-{day:02d}"
            for h in range(24):
                if key == "2024-07-15":
                    volume = 300.0 if 8 <= h < 20 else 1900.0  # reversed day/night
                else:
                    volume = 1900.0 if 8 <= h < 20 else 300.0
                    volume += 30.0 if day % 2 else -30.0
                specs.append((f"{key}T{h:02d}:00", {"volume": volume}))
    found = detect.detect_traffic(filled_frame(specs), {SECTION: SID})
    shifts = [a for a in found if a["type"] == "profile_shift"]
    assert len(shifts) == 1
    assert shifts[0]["starts_at"] == "2024-07-15T00:00:00+03:00"
    assert "корреляция" in shifts[0]["description"]


def test_traffic_detectors_on_empty_filled_are_safe():
    empty = filled_frame([])
    assert detect.detect_traffic(empty, {SECTION: SID}) == []
    assert detect.detect_monthly(empty, {SECTION: SID}) == []


# --- ids, mega and linking (issues #25/#27) --------------------------------------------


def test_finalize_numbers_ids_and_flags_mega_only_for_traffic():
    ts = pd.Timestamp("2024-07-10T08:00", tz=parse.MSK)
    items = [
        detect.anomaly(
            SID,
            ts,
            ts + pd.Timedelta(hours=4),
            "traffic",
            "volume_drop",
            "amplitude",
            "high",
            "volume",
            100,
            500,
            -80.0,
            4.2,
            "а",
        ),
        detect.anomaly(
            SID,
            ts + pd.Timedelta(hours=9),
            ts + pd.Timedelta(hours=13),
            "traffic",
            "volume_drop",
            "amplitude",
            "medium",
            "volume",
            600,
            500,
            20.0,
            2.1,
            "б",
        ),
        detect.anomaly(
            SID,
            ts,
            ts + pd.Timedelta(days=1),
            "technical",
            "missing_hours",
            "integrity",
            "medium",
            "volume",
            2,
            24,
            -91.7,
            3.0,
            "в",
        ),
    ]
    done = detect.finalize(items)
    by_id = {a["id"]: a for a in done}
    assert "a134-volume-drop-20240710-01" in by_id and "a134-volume-drop-20240710-02" in by_id
    assert by_id["a134-volume-drop-20240710-01"]["is_mega"] is True  # -80% >= 60%
    assert by_id["a134-volume-drop-20240710-02"]["is_mega"] is False
    tech = next(a for a in done if a["category"] == "technical")
    assert tech["is_mega"] is False  # a dead sensor is never a "mega" traffic story


def test_event_linking_follows_the_kind_table():
    ts = pd.Timestamp("2024-07-10T00:00", tz=parse.MSK)

    def item(type_, category="traffic"):
        return detect.anomaly(
            SID,
            ts,
            ts + pd.Timedelta(hours=5),
            category,
            type_,
            "amplitude",
            "medium",
            "volume",
            1,
            2,
            -50.0,
            2.0,
            "тест",
        )

    late = detect.anomaly(
        SID,
        ts + pd.Timedelta(days=2, hours=2),
        ts + pd.Timedelta(days=2, hours=7),
        "traffic",
        "volume_drop",
        "amplitude",
        "medium",
        "volume",
        1,
        2,
        -50.0,
        2.0,
        "тест",
    )
    anomalies = [item("volume_drop"), item("congestion"), item("missing_hours", "technical"), late]
    ev = [
        {"id": "e-hol", "category": "holiday", "day": datetime.date(2024, 7, 10)},
        {"id": "e-out", "category": "outage", "day": datetime.date(2024, 7, 10)},
        {"id": "e-near", "category": "holiday", "day": datetime.date(2024, 7, 11)},
        {"id": "e-far", "category": "accident", "day": datetime.date(2024, 7, 20)},
    ]
    links = pipeline.link_events(anomalies, ev)

    assert anomalies[0]["event_id"] == "e-hol"  # volume drop suits a holiday
    assert anomalies[1]["event_id"] is None  # holiday ≠ congestion in the kind table
    assert anomalies[2]["event_id"] == "e-out"  # technical finds only explain an outage
    assert anomalies[3]["event_id"] == "e-near"  # the day after the event still counts
    assert links == {"e-hol": 1, "e-out": 1, "e-near": 1, "e-far": 0}


def test_events_file_is_the_reviewed_research():
    loaded = events.load_events()
    assert len(loaded) == 20
    assert len({e["id"] for e in loaded}) == 20
    allowed = {"accident", "roadworks", "weather", "holiday", "outage", "other"}
    assert {e["category"] for e in loaded} <= allowed
    assert all(e["source_url"].startswith("https://") for e in loaded)
    assert all(e["title"] for e in loaded)
    stripped = events.strip_days(loaded)
    assert all("day" not in e for e in stripped)


def test_corporate_conversion_keeps_the_customer_separate():
    loaded = corporate.load_corporate()
    assert len(loaded) == 25
    assert all(a["detector"] == "corporate" for a in loaded)
    assert all(a["score"] is None and a["is_mega"] is False for a in loaded)
    assert all(a["starts_at"].endswith("+03:00") for a in loaded)
    # the real export carries one sensor, and its period is 01.09.2023 - 30.09.2026
    assert {a["sensor_id"] for a in loaded} == {SID}
    assert all(a["starts_at"][:10] >= "2023-09-01" for a in loaded)
    assert all(a["ends_at"][:10] <= "2026-10-01" for a in loaded)
    levels = {a["level"] for a in loaded}
    assert levels <= {"low", "medium", "high", "critical"}
    red = [a for a in loaded if a["level"] == "critical"]  # representative 4.2 -> high,
    assert red == []  # so nothing corporate may come out critical
    assert {a["id"] for a in loaded} == {""}
    numbered = pipeline.number_corporate(loaded)
    assert numbered[0]["id"] == "a134-corp-0001"


def test_series_states_imputed_wins_over_anomaly():
    specs = [
        ("2024-07-10T08:00", {"imputation_method": "profile"}),
        ("2024-07-10T09:00", {}),
        ("2024-07-10T10:00", {}),
    ]
    filled = filled_frame(specs)
    ts = pd.Timestamp("2024-07-10T08:00", tz=parse.MSK)
    anomalies = [
        detect.anomaly(
            SID,
            ts,
            ts + pd.Timedelta(hours=3),
            "traffic",
            "volume_drop",
            "amplitude",
            "medium",
            "volume",
            1,
            5,
            -80.0,
            2.0,
            "тест",
        )
    ]
    states = pipeline.mark_states(filled, anomalies)
    assert list(states) == ["imputed", "anomaly", "anomaly"]
