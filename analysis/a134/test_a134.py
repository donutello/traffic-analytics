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
        "volume_direct",
        "volume_reverse",
        "speed_direct",
        "speed_reverse",
        "load_direct",
        "load_reverse",
        "large_trucks",
        "road_trains",
        "imputation_method",
    ]
    rows = []
    for ts, values in specs:
        volume = values.get("volume", 1000.0)
        rows.append(
            [
                SECTION,
                SID,
                pd.Timestamp(ts, tz=parse.MSK),
                volume,
                values.get("volume_direct", volume / 2),
                values.get("volume_reverse", volume / 2),
                values.get("speed_direct", 85.0),
                values.get("speed_reverse", 85.0),
                values.get("load_direct", 5.0),
                values.get("load_reverse", 4.0),
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
        if a["type"] == "volume_spike"
        and a["metric"] == "volume"
        and a["starts_at"] == "2024-07-11T10:00:00+03:00"
    ]
    both_directions = [
        a
        for a in found
        if a["type"] == "volume_spike"
        and a["metric"] in ("volume_direct", "volume_reverse")
        and a["starts_at"] == "2024-07-11T10:00:00+03:00"
    ]
    slow = [a for a in found if a["type"] == "speed_drop"]
    assert len(spike) == 1 and spike[0]["actual"] > spike[0]["expected"]
    assert len(both_directions) == 2  # the per-direction runs see the same spike
    assert all(a["metric"] == "speed_direct" for a in slow)
    assert len(slow) == 1  # the reverse lane never slowed: its own run stays quiet
    assert slow[0]["starts_at"] == "2024-07-16T08:00:00+03:00"


def test_daily_extreme_is_flagged_whole_day():
    filled = july_fill({"2024-07-20": {"volume": 100.0}})
    found = detect.detect_traffic(filled, {SECTION: SID})
    daily = [
        a
        for a in found
        if a["type"] == "volume_drop"
        and a["metric"] == "volume"
        and a["starts_at"] == "2024-07-20T00:00:00+03:00"
    ]
    assert len(daily) == 2  # 24 deviant hours collapse into one hourly run and one day
    assert any(a["detector"] == "amplitude" and a["actual"] == pytest.approx(2400.0) for a in daily)
    directions = [
        a
        for a in found
        if a["type"] == "volume_drop"
        and a["metric"] in ("volume_direct", "volume_reverse")
        and a["starts_at"] == "2024-07-20T00:00:00+03:00"
    ]
    assert len(directions) == 2  # both direction runs cover the same whole day


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


# --- smart-city ports (dilczech / sasha_k, see the README credit section) --------------


def tight_july(overrides: dict[str, dict]) -> pd.DataFrame:
    """Two quiet Julys with a day/night profile where every hour repeats one
    near-identical value (MAD 0): without the floor the old fallback made the sigma
    of a hair, and any small absolute wobble became a 20-sigma storm. Only the
    explicitly given (day, hours)-overrides may deviate."""
    specs = []
    for year in (2023, 2024):
        for day in range(1, 32):
            key = f"{year}-07-{day:02d}"
            for h in range(24):
                level = (1000.0 if 7 <= h < 22 else 30.0) + (1.0 if h % 2 else -1.0)
                override = overrides.get(key, {})
                if override and override["hours"][0] <= h < override["hours"][1]:
                    level = override["level"]
                specs.append((f"{key}T{h:02d}:00", {"volume": level}))
    return filled_frame(specs)


def test_floored_scale_silences_tight_mad_night_hours():
    # the night here reads a rock-steady 30 авт./ч (MAD 0 -> the old fallback turned
    # it into a sigma of 1): a jump to 80 авт./ч is +167 % and would have been a
    # 33-sigma "storm"; the 20-авт./ч floor says z = 2.5 and the hour stays quiet
    filled = tight_july({"2024-07-11": {"level": 80.0, "hours": (0, 4)}})
    assert detect.detect_traffic(filled, {SECTION: SID}) == []


def test_practical_floor_silences_small_absolute_drops():
    # 1000 down to 660 авт./ч passes the floored z (|z| = 3.4) but the absolute car
    # count stays under max(35 % of norm, 50): a third of a hundred cars at daytime
    # is not an incident, and dilczech's practical AND keeps it unreported
    filled = tight_july({"2024-07-11": {"level": 660.0, "hours": (8, 12)}})
    assert detect.detect_traffic(filled, {SECTION: SID}) == []
    # and the same day truly halved: everything passes and it is told
    fired = tight_july({"2024-07-11": {"level": 400.0, "hours": (8, 12)}})
    hourly = [
        a
        for a in detect.detect_traffic(fired, {SECTION: SID})
        if a["detector"] == "amplitude" and a["metric"] == "volume" and a["type"] == "volume_drop"
    ]
    assert len(hourly) == 1 and hourly[0]["deviation_pct"] == pytest.approx(-60.0, abs=0.5)


def test_speed_drop_is_measured_in_km_h_and_needs_moving_cars():
    fired = july_fill({"2024-07-11": {"speed_direct": 55.0, "hours": (8, 12)}})
    found = detect.detect_traffic(fired, {SECTION: SID})
    slow = [a for a in found if a["type"] == "speed_drop"]
    assert len(slow) == 1 and slow[0]["metric"] == "speed_direct"
    assert slow[0]["starts_at"] == "2024-07-11T08:00:00+03:00"
    assert slow[0]["ends_at"] == "2024-07-11T12:00:00+03:00"
    assert slow[0]["expected"] - slow[0]["actual"] >= 15.0  # the gap is in км/ч
    assert "км/ч" in slow[0]["description"]

    mild = july_fill({"2024-07-11": {"speed_direct": 75.0, "hours": (8, 14)}})
    assert [
        a for a in detect.detect_traffic(mild, {SECTION: SID}) if a["type"] == "speed_drop"
    ] == []

    masked = july_fill({"2024-07-11": {"speed_direct": 55.0, "hours": (8, 13)}}).copy()
    at_noon = masked["ts"].dt.strftime("%Y-%m-%dT%H") == "2024-07-11T10"
    masked.loc[at_noon, "volume_direct"] = 0.0  # the loop read no car in that hour
    for item in detect.detect_traffic(masked, {SECTION: SID}):
        if item["type"] == "speed_drop" and item["metric"] == "speed_direct":
            assert not item["starts_at"] <= "2024-07-11T10:00:00+03:00" < item["ends_at"]


def test_regime_change_fires_once_for_a_sustained_shift():
    # Jan 2024 is the frozen history, Feb 4-11 (8 flat-shifted days) the new regime:
    # every day reads 60 % of its kind's historical median for 7 days straight
    specs = []
    for day in pd.date_range("2024-01-01", "2024-04-30", freq="D"):
        shift = pd.Timestamp("2024-02-04") <= day <= pd.Timestamp("2024-02-11")
        level = 600.0 if shift else 1000.0
        for h in range(24):
            specs.append(
                (
                    (day + pd.Timedelta(hours=h)).isoformat(),
                    {"volume": level + (1.0 if h % 2 else -1.0)},
                )
            )
    found = detect.detect_traffic(filled_frame(specs), {SECTION: SID})
    regime = [a for a in found if a["detector"] == "regime"]
    assert len(regime) == 1  # one report per window: the overlapping windows are eaten
    item = regime[0]
    assert item["type"] == "volume_drop"
    assert item["starts_at"] == "2024-02-04T00:00:00+03:00"
    assert item["ends_at"] == "2024-02-11T00:00:00+03:00"  # half-open, first day to day 8
    assert item["deviation_pct"] == pytest.approx(-40.0, abs=1.0)
    assert item["score"] == pytest.approx(5.0, abs=0.2)  # 3.5 + 0.1 per % past 25
    assert item["level"] == "critical"

    # a one-day storm inside an otherwise flat spell is an amplitude story, not a regime
    specs = []
    for day in pd.date_range("2024-03-01", "2024-03-31", freq="D"):
        level = 450.0 if day.day == 13 else 500.0  # one Sunday 10 % under the Sundays
        for h in range(24):
            specs.append(
                (
                    (day + pd.Timedelta(hours=h)).isoformat(),
                    {"volume": level + (1.0 if h % 2 else -1.0)},
                )
            )
    found = detect.detect_traffic(filled_frame(specs), {SECTION: SID})
    assert [a for a in found if a["detector"] == "regime"] == []


def test_correlation_promotion_bumps_each_side_once_and_caps():
    ts = pd.Timestamp("2024-07-10T08:00", tz=parse.MSK)

    def item(metric, type_, start, hours, score, text):
        return detect.anomaly(
            SID,
            start,
            start + pd.Timedelta(hours=hours),
            "traffic",
            type_,
            "amplitude",
            detect.level_from_score(score),
            metric,
            1.0,
            2.0,
            -50.0,
            score,
            text,
        )

    vol = item("volume", "volume_drop", ts, 4, 1.5, "Поток упал.")
    spd = item("speed_direct", "speed_drop", ts + pd.Timedelta(hours=1), 2, 3.4, "Скорость упала.")
    loud = item("volume", "volume_drop", ts + pd.Timedelta(hours=2), 2, 8.0, "Громкая.")
    far = item("speed_direct", "speed_drop", ts + pd.Timedelta(days=1), 2, 4.0, "Далекая.")
    items = [vol, spd, loud, far]
    detect.promote_correlated(items)
    detect.promote_correlated(items)  # the second pass must find nothing new to give

    assert vol["score"] == 2.0 and vol["level"] == "medium"  # 1.5 + 0.5 crosses the band
    assert spd["score"] == 3.9 and spd["level"] == "high"
    assert vol["description"].count("вторым каналом") == 1  # once, never twice
    assert spd["description"].count("вторым каналом") == 1
    assert "скорость" in vol["description"] and "поток" in spd["description"]
    assert loud["score"] == 8.0 and loud["description"] == "Громкая."  # at/above the cap
    assert far["score"] == 4.0 and far["description"] == "Далекая."  # no time overlap


def test_zero_telemetry_run_is_a_technical_failure():
    rows = day_rows("2024-03-04", volume=300.0)
    for h in range(24):  # a whole day of reported-but-empty packets
        stamp = pd.Timestamp("2024-03-05", tz=parse.MSK) + pd.Timedelta(hours=h)
        row = raw_row(stamp, 0.0, speed=0.0, load=0.0)
        row[13], row[15] = 0.0, 0.0  # the reverse speed and load channels too
        rows.append(row)
    found, bad_hours = quality.detect_failures(make_table(rows), SENSOR_IDS)
    telemetry = [a for a in found if a["type"] == "zero_telemetry"]
    assert len(telemetry) == 1
    assert telemetry[0]["category"] == "technical"
    assert telemetry[0]["starts_at"] == "2024-03-05T00:00:00+03:00"
    assert telemetry[0]["ends_at"] == "2024-03-06T00:00:00+03:00"
    assert telemetry[0]["level"] == "high"
    assert len(bad_hours[SID]) == 24  # no traffic detector may read these as an empty road

    rows = day_rows("2024-03-06", volume=300.0)
    for h in range(9, 15):  # six quiet but real hours: short, so not telemetry death
        stamp = pd.Timestamp("2024-03-06", tz=parse.MSK) + pd.Timedelta(hours=h)
        row = raw_row(stamp, 0.0, speed=0.0, load=0.0)
        row[13], row[15] = 0.0, 0.0
        rows[h - 9] = row
    found, bad_hours = quality.detect_failures(make_table(rows), SENSOR_IDS)
    assert [a for a in found if a["type"] == "zero_telemetry"] == []
    assert len(bad_hours.get(SID, ())) == 0


def test_month_yoy_compares_only_valid_months_on_flow_weighted_speed():
    # 2024-07's month speed is the flow-weighted 68 км/ч ((70*900 + 50*100)/1000),
    # not the plain 60 км/ч the bare mean used to say; and 2025-07, a fifth of which
    # is imputed (84 % valid - over the complaint bar, under the YoY bar), may
    # neither compare itself nor anchor 2024-07's norm with its matching 68 км/ч
    specs = []
    for year in (2023, 2024, 2025):
        for day in range(1, 32):
            key = f"{year}-07-{day:02d}"
            for h in range(24):
                values = {"volume": 1000.0, "speed_direct": 85.0}
                if year == 2024:
                    values.update(
                        {
                            "speed_direct": 70.0 if h < 12 else 50.0,
                            "volume_direct": 900.0 if h < 12 else 100.0,
                        }
                    )
                if year == 2025:
                    values["speed_direct"] = 68.0
                    if day <= 5:
                        values["imputation_method"] = "profile"
                specs.append((f"{key}T{h:02d}:00", values))
    found = detect.detect_monthly(filled_frame(specs), {SECTION: SID})
    assert len(found) == 1  # the 84 %-valid 2025 July is silently outside all YoY
    year = found[0]
    assert year["detector"] == "yoy" and year["metric"] == "speed_direct"
    assert year["type"] == "speed_drop"
    assert year["starts_at"].startswith("2024-07-01")
    assert year["actual"] == pytest.approx(68.0)  # flow-weighted, not the plain 60
    assert year["expected"] == pytest.approx(85.0)  # the 2025 outlier month is no peer
