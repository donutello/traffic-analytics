"""Tests for the A-133 module: parser, balance audit, failures, gap fill, detectors.

Everything here runs on small made-up series; the raw export files are not needed
(the real CI box never sees analysis/data/raw/). Thresholds tested are the ones the
module README settles (issues #18/#19)."""

import datetime

import pandas as pd
import pytest
from openpyxl import Workbook

from analysis.a133 import corporate, detect, events, holidays, parse, pipeline, quality

SECTION = "км 12+000 а/д А-133"
SID = "a133-km12-0"
SENSOR_IDS = {SECTION: SID}


def raw_row(ts, volume, speed=88.0, load=5.0) -> list:
    """One raw-table row whose own numbers balance (total = directions = class sum);
    only the knobs a test needs vary."""
    others = [10.0, 10.0, 5.0, 3.0, 2.0, 2.0]
    cars = volume - sum(others)
    row = [
        SECTION,
        ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts,
        volume,
        volume / 2,
        volume / 2,
    ]
    for total in [cars, *others]:
        row.extend([total, total / 2, total / 2])
    row.extend([speed, speed * 0.94, load, load * 0.8])
    return row


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


# --- parser (issue #16) ------------------------------------------------------------------


def test_parse_keeps_hours_splits_and_skips_service_rows(tmp_path):
    write_export(
        tmp_path,
        [
            [SECTION],
            ["Дата", "Итого"],
            number_row(
                [
                    datetime.datetime(2024, 3, 8, 10, 0),
                    120,
                    60,
                    60,
                    70,
                    35,
                    35,
                    30,
                    15,
                    15,
                    10,
                    5,
                    5,
                    5,
                    2,
                    3,
                    3,
                    1,
                    2,
                    2,
                    1,
                    1,
                    0,
                    "1",
                    0,
                    85.5,
                    90.2,
                    12.5,
                    9.0,
                ]
            ),
            number_row(["Итого", 120]),
            number_row(
                ["09.03.2024 11:00", "130", "65", "65", "80", "40", "40", "50", "25", "25"]
                + ["10", "5", "5", "5", "3", "2", "3", "2", "1", "2", "1", "1", "1", "1", "0"]
                + ["88,5", 91, 14, 10]
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
    assert df["speed_direct"].tolist() == [85.5, 88.5]  # the comma variant too
    # unlike a134 this parser keeps the class splits for the balance audit
    assert df["cars_direct"].tolist() == [35, 40]
    assert df["small_trucks_reverse"].tolist() == [15, 25]


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


def test_sensor_id_and_known_coordinates():
    assert parse.sensor_id(SECTION) == "a133-km12-0"
    assert parse.sensor_id("км 40+000 а/д А-133") == "a133-km40-0"
    assert parse.sensor_id("пост у моста", fallback=2) == "a133-02"

    sensors = parse.build_sensors(
        [SECTION, "км 40+000 а/д А-133", "км 55+000 а/д А-133"],
    )
    assert [s["id"] for s in sensors] == ["a133-km12-0", "a133-km40-0", "a133-km55-0"]
    by_id = {s["id"]: s for s in sensors}
    assert by_id["a133-km12-0"]["lat"] == pytest.approx(52.29525)
    assert by_id["a133-km40-0"]["km"] == 40.0
    assert by_id["a133-km55-0"]["lat"] is None  # a new section must come with coordinates


def test_day_kind_uses_the_official_calendar():
    d = datetime.date
    assert holidays.day_kind(d(2023, 1, 3)) == "holiday"  # New Year holidays
    assert holidays.day_kind(d(2024, 12, 30)) == "holiday"  # moved by Decree 1314
    assert holidays.day_kind(d(2025, 5, 2)) == "holiday"  # Jan 4 moved by Decree 1335
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


# --- technical failures and the balance audit (issue #18) ---------------------------------


def test_flatline_detected_and_hours_marked_untrusted():
    rows = []
    for day in pd.date_range("2024-01-13", "2024-01-20", freq="D"):
        rows += day_rows(day.date().isoformat(), volume=300.0 + day.dayofyear % 7)
    stuck_start = pd.Timestamp("2024-01-15 00:00", tz=parse.MSK)
    for h in range(6):  # six identical hours in a row: the sensor froze
        rows[24 * 2 + h] = raw_row(stuck_start + pd.Timedelta(hours=h), 437.0)
    df = make_table(rows)

    found, bad_hours = quality.detect_failures(df, SENSOR_IDS)
    flat = next(a for a in found if a["type"] == "flatline")
    assert flat["category"] == "technical"
    assert flat["level"] == "high"  # score 4.0 sits in the high band of contract v1
    assert len(bad_hours[SID]) == 6


def test_dead_speed_channel_and_missing_days():
    rows = []
    for h in range(24):  # cars pass but the speed sensor reads zero for 8 hours
        ts = pd.Timestamp("2024-03-06", tz=parse.MSK) + pd.Timedelta(hours=h)
        rows.append(raw_row(ts, 190.0 + 20 * (h % 2), speed=0.0 if 3 <= h < 11 else 88.0))
    found, bad_hours = quality.detect_failures(make_table(rows), SENSOR_IDS)
    zero = [a for a in found if a["type"] == "zero_speed"]
    assert len(zero) == 1 and zero[0]["level"] == "medium"
    assert len(bad_hours[SID]) == 8

    rows = []
    for day in pd.date_range("2024-03-04", "2024-03-07", freq="D"):
        iso = day.date().isoformat()
        if iso == "2024-03-05":
            rows += day_rows(iso, volume=250.0)[:18]  # only 18 hours survived
        else:
            rows += day_rows(iso, volume=250.0 + day.day)
    found, _ = quality.detect_failures(make_table(rows), SENSOR_IDS)
    missing = [a for a in found if a["type"] == "missing_hours"]
    assert len(missing) == 1 and missing[0]["actual"] == 18.0


def test_zero_telemetry_run_is_a_technical_failure():
    rows = day_rows("2024-03-04", volume=300.0)
    for h in range(13):  # thirteen reported-but-empty packets: the reporter died
        stamp = pd.Timestamp("2024-03-05", tz=parse.MSK) + pd.Timedelta(hours=h)
        rows.append(raw_row(stamp, 0.0, speed=0.0, load=0.0))
    found, bad_hours = quality.detect_failures(make_table(rows), SENSOR_IDS)
    telemetry = [a for a in found if a["type"] == "zero_telemetry"]
    assert len(telemetry) == 1
    assert telemetry[0]["level"] == "high"
    assert len(bad_hours[SID]) == 13

    rows = day_rows("2024-03-06", volume=300.0)
    for h in range(6):  # six empty packets: short, repaired quietly, no anomaly
        stamp = pd.Timestamp("2024-03-06", tz=parse.MSK) + pd.Timedelta(hours=h)
        rows[h] = raw_row(stamp, 0.0, speed=0.0, load=0.0)
    found, _ = quality.detect_failures(make_table(rows), SENSOR_IDS)
    assert [a for a in found if a["type"] == "zero_telemetry"] == []


def september_drift_table(direction_drift: float = 0.0, class_drift: float = 0.0):
    """Two September weeks where every working hour's parts disagree with the total:
    classes over by class_drift, directions over by direction_drift."""
    rows = []
    for day in pd.date_range("2023-09-02", "2023-09-16", freq="D"):
        for h in range(24):
            ts = day + pd.Timedelta(hours=h)
            row = raw_row(ts, 400.0 + 11.0 * (h % 3))
            if 9 <= h < 17:
                row[14] += class_drift  # large_trucks total reads high
                row[4] += direction_drift  # the reverse loop reads high
            rows.append(row)
    return make_table(rows)


def test_systematic_class_drift_gets_one_monthly_finding():
    found, bad_hours = quality.detect_failures(september_drift_table(class_drift=6.0), SENSOR_IDS)
    drift = [a for a in found if a["type"] == "balance_drift"]
    assert len(drift) == 1
    assert drift[0]["detector"] == "balance"
    assert "классов" in drift[0]["description"]
    assert drift[0]["starts_at"].startswith("2023-09-01")
    assert drift[0]["ends_at"].startswith("2023-10-01")  # the whole audited month
    assert drift[0]["level"] == "medium"  # a quiet drift is told calmly
    assert SID not in bad_hours or bad_hours[SID] == set()  # 6 cars is under the hard bar


def test_big_direction_disagreement_marks_hours_without_traffic_stories():
    found, bad_hours = quality.detect_failures(
        september_drift_table(direction_drift=30.0), SENSOR_IDS
    )
    assert bad_hours[SID]  # hours whose parts contradict the total are not trusted
    drift = [a for a in found if a["type"] == "balance_drift"]
    assert len(drift) == 1 and "направлений" in drift[0]["description"]


def test_small_random_disagreement_is_silent():
    rows = []
    for day in pd.date_range("2023-09-02", "2023-09-16", freq="D"):
        for h in range(24):
            ts = day + pd.Timedelta(hours=h)
            rows.append(raw_row(ts, 400.0 + 11.0 * (h % 3)))
    # balanced rows disagree by nothing anywhere: neither the audit nor the hard bar speaks
    found, bad_hours = quality.detect_failures(make_table(rows), SENSOR_IDS)
    assert [a for a in found if a["type"] == "balance_drift"] == []
    assert bad_hours.get(SID, set()) == set()


def test_empty_table_is_safe():
    found, bad_hours = quality.detect_failures(pd.DataFrame(columns=parse.TABLE_COLUMNS), {})
    assert found == [] and bad_hours == {}


# --- gap fill (issue #18) ------------------------------------------------------------------


def build_july_with_holes(hole_day: str, hole_from: int, hole_to: int) -> pd.DataFrame:
    rows = []
    for day in pd.date_range("2024-07-01", "2024-07-28", freq="D"):
        iso = day.date().isoformat()
        volume = 780.0 if day.day % 2 else 820.0
        for h in range(24):
            ts = day + pd.Timedelta(hours=h)
            if iso == hole_day and hole_from <= h < hole_to:
                continue
            rows.append(raw_row(ts, volume))
    return make_table(rows)


def test_short_hole_is_interpolated_long_hole_uses_the_profile():
    filled = quality.fill_gaps(build_july_with_holes("2024-07-09", 10, 12), {}, SENSOR_IDS)
    day = filled[filled["ts"].dt.strftime("%Y-%m-%d").eq("2024-07-09")]
    at_gap = day[day["imputation_method"] != ""]
    assert len(at_gap) == 2
    assert set(at_gap["imputation_method"]) == {"interpolation"}

    filled = quality.fill_gaps(build_july_with_holes("2024-07-17", 8, 15), {}, SENSOR_IDS)
    day = filled[filled["ts"].dt.strftime("%Y-%m-%d").eq("2024-07-17")]
    at_gap = day[day["imputation_method"] != ""]
    assert len(at_gap) == 7
    assert "profile" in set(
        at_gap["imputation_method"]
    )  # the middle of a long hole falls back to norms
    assert at_gap["volume"].between(760.0, 840.0).all()

    hours = filled["ts"]
    assert (hours.diff().dropna() == pd.Timedelta(hours=1)).all()  # the grid is hole-free


# --- traffic detectors (issue #19) ----------------------------------------------------------


def july_fill(day_specs: dict[str, dict]) -> pd.DataFrame:
    """Two quiet Julys (hour wobble keeps every day-sum identical, so only the
    explicitly given day overrides can trigger any detector)."""
    specs = []
    for year in (2023, 2024):
        for day in range(1, 32):
            key = f"{year}-07-{day:02d}"
            override = day_specs.get(key, {})
            for h in range(24):
                window = override.get("hours")
                in_window = window is None or window[0] <= h < window[1]
                values = {"volume": 1030.0 if day % 2 else 970.0}
                if in_window:
                    values.update({k: v for k, v in override.items() if k != "hours"})
                specs.append((f"{key}T{h:02d}:00", values))
    return filled_frame(specs)


def test_hourly_drop_reports_the_exact_interval():
    filled = july_fill({"2024-07-11": {"volume": 100.0, "hours": (8, 14)}})
    found = detect.detect_traffic(filled, {SECTION: SID})
    hourly = [a for a in found if a["detector"] == "amplitude" and a["metric"] == "volume"]
    assert len(hourly) == 1
    assert hourly[0]["type"] == "volume_drop"
    assert hourly[0]["starts_at"] == "2024-07-11T08:00:00+03:00"
    assert hourly[0]["ends_at"] == "2024-07-11T14:00:00+03:00"
    assert hourly[0]["deviation_pct"] == pytest.approx(-90.0)


def test_speed_drop_is_measured_in_km_h_and_needs_moving_cars():
    fired = july_fill({"2024-07-11": {"speed_direct": 55.0, "hours": (8, 12)}})
    found = detect.detect_traffic(fired, {SECTION: SID})
    slow = [a for a in found if a["type"] == "speed_drop"]
    assert len(slow) == 1 and slow[0]["metric"] == "speed_direct"
    assert slow[0]["expected"] - slow[0]["actual"] >= 15.0  # the gap is in км/ч
    assert "км/ч" in slow[0]["description"]

    mild = july_fill({"2024-07-11": {"speed_direct": 75.0, "hours": (8, 14)}})
    mild_found = detect.detect_traffic(mild, {SECTION: SID})
    assert [a for a in mild_found if a["type"] == "speed_drop"] == []

    masked = july_fill({"2024-07-11": {"speed_direct": 55.0, "hours": (8, 13)}}).copy()
    at_noon = masked["ts"].dt.strftime("%Y-%m-%dT%H") == "2024-07-11T10"
    masked.loc[at_noon, "volume_direct"] = 0.0  # the loop read no car in that hour
    for item in detect.detect_traffic(masked, {SECTION: SID}):
        if item["type"] == "speed_drop" and item["metric"] == "speed_direct":
            assert not item["starts_at"] <= "2024-07-11T10:00:00+03:00" < item["ends_at"]


def test_share_imbalance_needs_a_long_one_sided_tip():
    # five hours when the road reads 80/20 instead of the usual 50/50: the total is
    # untouched, so only the direction-share detector has a story here
    specs = []
    for year in (2023, 2024):
        for day in range(1, 32):
            key = f"{year}-07-{day:02d}"
            for h in range(24):
                values = {"volume": 1000.0, "volume_direct": 505.0 if day % 2 else 495.0}
                if key == "2024-07-11" and 8 <= h < 13:
                    values["volume_direct"] = 800.0
                    values["volume_reverse"] = 200.0
                specs.append((f"{key}T{h:02d}:00", values))
    found = detect.detect_traffic(filled_frame(specs), {SECTION: SID})
    tip = [a for a in found if a["type"] == "direction_imbalance" and a["category"] == "traffic"]
    assert len(tip) == 1
    assert tip[0]["starts_at"] == "2024-07-11T08:00:00+03:00"
    assert tip[0]["ends_at"] == "2024-07-11T13:00:00+03:00"
    assert "перекосился" in tip[0]["description"]

    # a two-hour tip of the same size: too short to be told (hourly noise is many things)
    specs_short = [
        spec
        for spec in specs
        if not (spec[0] == "2024-07-15T10:00" or spec[0] == "2024-07-15T11:00")
    ]
    short = filled_frame(specs_short)
    short.loc[
        short["ts"].dt.strftime("%Y-%m-%dT%H").isin(["2024-07-15T10", "2024-07-15T11"]),
        ["volume_direct", "volume_reverse"],
    ] = [800.0, 200.0]
    found = detect.detect_traffic(short, {SECTION: SID})
    assert [
        a
        for a in found
        if a["type"] == "direction_imbalance"
        and a["category"] == "traffic"
        and a["starts_at"].startswith("2024-07-15")
    ] == []


def test_congestion_needs_slow_and_loaded_hours_in_a_row():
    base = july_fill({})
    extra = [
        (
            (pd.Timestamp("2023-07-03T17:00", tz=parse.MSK) + pd.Timedelta(hours=off)).isoformat(),
            {"speed_direct": 45.0, "load_direct": 30.0},
        )
        for off in range(3)
    ]
    extra.append(("2023-07-05T12:00", {"speed_direct": 40.0, "load_direct": 33.0}))  # lone hour
    filled = filled_frame(
        [
            (
                row["ts"].isoformat(),
                {k: row[k] for k in ("volume", "speed_direct", "load_direct")},
            )
            for _, row in base.iterrows()
            if row["ts"].strftime("%Y-%m-%d") not in ("2023-07-03", "2023-07-05")
        ]
        + extra
    )
    found = detect.detect_traffic(filled, {SECTION: SID})
    congestion = [a for a in found if a["type"] == "congestion"]
    assert len(congestion) == 1
    assert congestion[0]["starts_at"] == "2023-07-03T17:00:00+03:00"
    assert congestion[0]["level"] == "high"


def test_imputed_hours_never_count_as_traffic():
    specs = {"2024-07-10": {"volume": 100.0, "hours": (0, 24), "imputation_method": "profile"}}
    filled = july_fill(specs)
    assert detect.detect_traffic(filled, {SECTION: SID}) == []


def test_regime_change_fires_once_for_a_sustained_shift():
    specs = []
    for day in pd.date_range("2024-01-01", "2024-04-30", freq="D"):
        shift = pd.Timestamp("2024-02-04") <= day <= pd.Timestamp("2024-02-11")
        level = 600.0 if shift else 1000.0
        for h in range(24):
            specs.append(((day + pd.Timedelta(hours=h)).isoformat(), {"volume": level}))
    found = detect.detect_traffic(filled_frame(specs), {SECTION: SID})
    regime = [a for a in found if a["detector"] == "regime"]
    assert len(regime) == 1  # overlapping windows are eaten, one report per regime
    assert regime[0]["deviation_pct"] == pytest.approx(-40.0, abs=1.0)
    assert regime[0]["level"] == "critical"


def test_traffic_detectors_on_empty_filled_are_safe():
    empty = filled_frame([])
    assert detect.detect_traffic(empty, {SECTION: SID}) == []
    assert detect.detect_monthly(empty, {SECTION: SID}) == []


# --- merging, ids, mega, linking (issues #19/#21) -------------------------------------------


def drop_anomaly(start: pd.Timestamp, hours: int, score: float, actual: float) -> dict:
    return detect.anomaly(
        SID,
        start,
        start + pd.Timedelta(hours=hours),
        "traffic",
        "volume_drop",
        "amplitude",
        detect.level_from_score(score),
        "volume",
        actual,
        500.0,
        (actual - 500.0) / 500.0 * 100,
        score,
        "Поток тише нормы.",
    )


def test_nearby_episodes_merge_into_one_finding_distant_do_not():
    ts = pd.Timestamp("2024-07-10T08:00", tz=parse.MSK)
    a = drop_anomaly(ts, 4, 4.2, 150.0)  # 08-12, -70 %
    b = drop_anomaly(ts + pd.Timedelta(hours=6), 4, 2.5, 250.0)  # 14-18: 2 h gap, same story
    far = drop_anomaly(ts + pd.Timedelta(days=2), 4, 2.5, 250.0)  # 36 h away: stays separate
    done = detect.finalize([a, b, far])
    assert len(done) == 2
    first, second = done
    assert first["starts_at"] == "2024-07-10T08:00:00+03:00"
    assert first["ends_at"] == "2024-07-10T18:00:00+03:00"
    assert first["actual"] == pytest.approx(200.0)  # equal-hour weighted mean
    assert first["score"] == pytest.approx(4.2)  # the loudest episode's score stands
    assert first["deviation_pct"] == pytest.approx(-60.0)  # exactly on the mega bar
    assert first["is_mega"] is True
    assert second["starts_at"].startswith("2024-07-12")


def test_finalize_numbers_ids_sequentially():
    ts = pd.Timestamp("2024-07-10T08:00", tz=parse.MSK)
    done = detect.finalize(
        [drop_anomaly(ts, 4, 4.0, 150.0), drop_anomaly(ts + pd.Timedelta(days=5), 4, 2.5, 250.0)]
    )
    ids = [a["id"] for a in done]
    assert ids == ["a133-volume-drop-20240710-01", "a133-volume-drop-20240715-01"]


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

    slow = item("speed_drop")
    tech = item("missing_hours", "technical")
    anomalies = [item("volume_drop"), slow, tech]
    ev = [
        {"id": "e-acc", "category": "accident", "day": datetime.date(2024, 7, 10)},
        {"id": "e-out", "category": "outage", "day": datetime.date(2024, 7, 10)},
    ]
    links = pipeline.link_events(anomalies, ev)
    assert anomalies[0]["event_id"] == "e-acc"  # volume drop suits an accident
    assert anomalies[1]["event_id"] == "e-acc"  # so does the clearance slow-down
    assert anomalies[2]["event_id"] == "e-out"  # technical finds only explain an outage
    assert links == {"e-acc": 2, "e-out": 1}


def test_promotion_bumps_each_side_once():
    ts = pd.Timestamp("2024-07-10T08:00", tz=parse.MSK)
    vol = detect.anomaly(
        SID,
        ts,
        ts + pd.Timedelta(hours=4),
        "traffic",
        "volume_drop",
        "amplitude",
        detect.level_from_score(1.5),
        "volume",
        1.0,
        2.0,
        -50.0,
        1.5,
        "Поток упал.",
    )
    spd = detect.anomaly(
        SID,
        ts + pd.Timedelta(hours=1),
        ts + pd.Timedelta(hours=3),
        "traffic",
        "speed_drop",
        "amplitude",
        detect.level_from_score(3.4),
        "speed_direct",
        1.0,
        2.0,
        -50.0,
        3.4,
        "Скорость упала.",
    )
    items = [vol, spd]
    detect.promote_correlated(items)
    detect.promote_correlated(items)  # the second pass must find nothing new to give
    assert vol["score"] == 2.0 and vol["level"] == "medium"
    assert spd["score"] == 3.9 and spd["level"] == "high"
    assert vol["description"].count("вторым каналом") == 1
    assert spd["description"].count("вторым каналом") == 1


# --- research files and output plumbing (issues #17/#20/#21) ---------------------------------


def test_events_file_is_the_reviewed_research():
    loaded = events.load_events()
    assert len(loaded) == 19
    assert len({e["id"] for e in loaded}) == 19
    allowed = {"accident", "roadworks", "weather", "holiday", "outage", "other"}
    assert {e["category"] for e in loaded} <= allowed
    assert all(e["source_url"].startswith("https://") for e in loaded)
    assert all(e["title"] for e in loaded)
    assert {e["date"][:4] for e in loaded} == {"2023", "2024", "2025"}
    assert all("day" not in e for e in events.strip_days(loaded))


def test_corporate_conversion_keeps_the_customer_separate():
    loaded = corporate.load_corporate()
    assert len(loaded) == 24
    assert all(a["detector"] == "corporate" for a in loaded)
    assert all(a["score"] is None and a["is_mega"] is False for a in loaded)
    assert all(a["starts_at"].endswith("+03:00") for a in loaded)
    assert {a["sensor_id"] for a in loaded} == {"a133-km12-0", "a133-km40-0"}
    assert all(a["level"] != "critical" for a in loaded)  # class red tops out at high
    numbered = pipeline.number_corporate(loaded)
    assert numbered[0]["id"] == "a133-corp-0001"
    assert len({a["id"] for a in numbered}) == 24


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
