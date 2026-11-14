"""Tests for the R-22 module: parser, holidays, failures, gap fill, detectors, links.

Everything here runs on small made-up series; the thresholds tested are the ones the
module README settles (issues #34/#36)."""

import pandas as pd
from openpyxl import Workbook

from analysis.r22 import corporate, detect, events, holidays, parse, pipeline, quality

SECTION = 'км 448+650 а/д Р-22 "Каспий" а/д М-4 "Дон", подъезд к г. Саратов'
SID = "r22-km448-650"
SENSOR_IDS = {SECTION: SID}

# class weights sum to 1 so the class balances hold exactly in every built row
CLASS_WEIGHTS = [0.50, 0.15, 0.10, 0.08, 0.04, 0.08, 0.05]


def raw_row(
    ts, volume, speed=85.0, load=5.0, speed_r=85.0, load_r=4.0, direct=None, reverse=None
) -> list:
    """One raw-table row whose own sums balance; only the knobs a test needs vary."""
    direct = volume / 2 if direct is None else direct
    reverse = volume / 2 if reverse is None else reverse
    interleaved = [volume, direct, reverse]
    for weight in CLASS_WEIGHTS:  # each class split half and half by direction
        interleaved += [direct * weight + reverse * weight, direct * weight, reverse * weight]
    return [
        SECTION,
        pd.Timestamp(ts).to_pydatetime(),
        *interleaved,
        speed,
        speed_r,
        load,
        load_r,
    ]


def make_table(rows: list[list]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=parse.TABLE_COLUMNS)


def day_rows(day: str, volume: float = 200.0, flat_hours=None, **overrides) -> list[list]:
    """One full day of raw rows; the volume wobbles hour by hour so ordinary days
    never look stuck, except hours listed in flat_hours which repeat one value."""
    first = pd.Timestamp(day, tz=parse.MSK)
    rows = []
    for h in range(24):
        value = volume + 7.0 * (h % 4)
        if flat_hours and h in flat_hours:
            value = flat_hours[h]
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
    return pd.DataFrame(rows, columns=columns)


def work_hours(specs: list[tuple[str, dict]]) -> pd.DataFrame:
    """The detectors' own working frame from filled-frame specs (real hours only)."""
    work = detect._working_frame(filled_frame(specs))
    return work[~work["hour_imputed"]]


def weeks_of_days(start: str, count: int, volume=80.0) -> list[tuple[str, dict]]:
    """`count` consecutive clean days of plain wobbling volume, starting at start."""
    specs = []
    first = pd.Timestamp(start, tz=parse.MSK)
    for d in range(count):
        for h in range(24):
            specs.append(
                (
                    (first + pd.Timedelta(days=d)).replace(hour=h).isoformat(),
                    {"volume": volume + 5.0 * ((h % 5) + (d % 3))},
                )
            )
    return specs


# --- contract plumbing -------------------------------------------------------------


def test_level_from_score_is_the_contract_table():
    assert detect.level_from_score(1.9) == "low"
    assert detect.level_from_score(2.0) == "medium"
    assert detect.level_from_score(3.4) == "medium"
    assert detect.level_from_score(3.5) == "high"
    assert detect.level_from_score(4.9) == "high"
    assert detect.level_from_score(5.0) == "critical"


def test_finalize_ids_mega_and_order():
    items = [
        detect.anomaly(
            SID,
            pd.Timestamp("2026-05-03T20:00", tz=parse.MSK),
            pd.Timestamp("2026-05-04T00:00", tz=parse.MSK),
            "traffic",
            "volume_drop",
            "amplitude",
            "high",
            "volume",
            100.0,
            40.0,
            -60.0,
            4.0,
            "тест",
        ),
        detect.anomaly(
            SID,
            pd.Timestamp("2026-01-20T00:00", tz=parse.MSK),
            pd.Timestamp("2026-01-20T04:00", tz=parse.MSK),
            "technical",
            "flatline",
            "sensor",
            "high",
            "volume",
            1.0,
            None,
            None,
            4.0,
            "тест",
        ),
    ]
    done = detect.finalize(items)
    assert done[0]["starts_at"] < done[1]["starts_at"]  # sorted
    assert all(a["id"].startswith("r22-") for a in done)
    assert len({a["id"] for a in done}) == 2
    assert done[0]["type"] == "flatline" and done[0]["deviation_pct"] is None
    assert done[1]["is_mega"]  # traffic at exactly |dev| = 60 counts as mega


def test_mega_is_own_traffic_only_and_big():
    traffic_small = detect.anomaly(
        SID,
        pd.Timestamp("2026-05-03T20:00", tz=parse.MSK),
        pd.Timestamp("2026-05-04T00:00", tz=parse.MSK),
        "traffic",
        "volume_drop",
        "amplitude",
        "medium",
        "volume",
        45.0,
        50.0,
        -10.0,
        2.5,
        "тест",
    )
    big = dict(traffic_small, deviation_pct=-61.0)
    corporate_like = dict(
        traffic_small,
        category="corporate",
        type="capacity_warning",
        detector="corporate",
        deviation_pct=-90.0,
        score=None,
    )
    done = detect.finalize([traffic_small, big, corporate_like])
    mega = {a["id"]: a["is_mega"] for a in done}
    by_type = {(a["type"], a["deviation_pct"]): a["is_mega"] for a in done}
    assert len(mega) == 3
    assert by_type[("volume_drop", -10.0)] is False
    assert by_type[("volume_drop", -61.0)] is True
    assert by_type[("capacity_warning", -90.0)] is False  # corporate is never mega


# --- parser -------------------------------------------------------------------------


def test_parse_reads_labels_commas_and_hours(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.append([SECTION, None, None])
    row = ["05.01.2026 00:59:59", "1 234,5"] + ["10"] * 27
    sheet.append(row)
    sheet.append(["итого", 10])
    path = tmp_path / "svod.xlsx"
    book.save(path)

    table = parse.parse_traffic_excel(path)
    assert len(table) == 1
    hourly = table.iloc[0]
    assert hourly["ts"] == (
        pd.Timestamp("2026-01-05T00:59:59").tz_localize(parse.MSK).floor("h")
    )  # the label ends the hour; the series stamps its start
    assert hourly["volume"] == 1234.5  # thin space and decimal comma handled
    assert table.iloc[0]["section"] == SECTION


def test_build_sensors_uses_known_anchors_and_r22_directions():
    sensors = parse.build_sensors([SECTION])
    assert sensors[0]["id"] == SID
    assert sensors[0]["km"] == 448.65
    assert 51.3 < sensors[0]["lat"] < 51.5 and 41.0 < sensors[0]["lon"] < 41.2
    assert sensors[0]["directions"]["direct"] == "на Саратов"
    far = parse.build_sensors(['км 478+742 а/д Р-22 "Каспий"'])
    assert far[0]["id"] == "r22-km478-742"
    assert far[0]["lat"] > sensors[0]["lat"]  # the second sensor sits east, toward Saratov


# --- holidays -----------------------------------------------------------------------


def test_day_kinds_and_groups():
    assert holidays.day_kind(pd.Timestamp("2024-01-07")) == "holiday"
    assert holidays.day_kind(pd.Timestamp("2024-05-10")) == "holiday"  # transfer day
    assert holidays.day_kind(pd.Timestamp("2024-04-29")) == "holiday"
    assert holidays.day_kind(pd.Timestamp("2024-04-16")) == "weekday"
    assert holidays.day_group(pd.Timestamp("2026-05-11")) == "holiday"
    assert holidays.day_group(pd.Timestamp("2024-04-16")) == "weekday-1"
    assert holidays.day_group(pd.Timestamp("2024-04-17")) == "weekday-2"


# --- quality ------------------------------------------------------------------------


def test_balance_contradiction_makes_the_hour_bad():
    rows = day_rows("2026-04-06") + day_rows("2026-04-07")
    bad_hour = raw_row(pd.Timestamp("2026-04-07 10:00", tz=parse.MSK), 600)
    bad_hour[2 + 1] = 400.0  # volume_direct: 400 + 100 != 600
    bad_hour[2 + 2] = 100.0
    rows[24 + 10] = bad_hour
    table = make_table(rows)
    found, bad = quality.detect_failures(table, SENSOR_IDS)
    assert pd.Timestamp("2026-04-07T10:00", tz=parse.MSK) in bad[SID]
    assert not any(a["type"] == "balance_drift" for a in found)  # one hour is no drift

    filled = quality.fill_gaps(table, bad, SENSOR_IDS)
    hour = filled[filled["ts"] == pd.Timestamp("2026-04-07T10:00", tz=parse.MSK)]
    assert hour["imputation_method"].iloc[0] != ""  # repaired, never read as traffic


def test_half_split_hour_is_untrusted_and_never_left_empty():
    # the real export logs 48 hours with a total volume but no reverse-direction
    # count; the contract wants no empty volume columns, so those hours must be
    # untrusted (not a share story) and fully numbered after the fill
    rows = day_rows("2026-04-06") + day_rows("2026-04-07")
    split_hour = raw_row(pd.Timestamp("2026-04-07 13:00", tz=parse.MSK), 300.0)
    split_hour[4] = None  # volume_reverse empty while the total is present
    rows[24 + 13] = split_hour
    table = make_table(rows)
    found, bad = quality.detect_failures(table, SENSOR_IDS)
    stamp = pd.Timestamp("2026-04-07T13:00", tz=parse.MSK)
    assert stamp in bad[SID]
    assert not any(a["detector"] == "direction_share" for a in found)
    filled = quality.fill_gaps(table, bad, SENSOR_IDS)
    hour = filled[filled["ts"] == stamp].iloc[0]
    assert pd.notna(hour["volume_reverse"]) and hour["imputation_method"] != ""


def test_flatline_zero_telemetry_and_short_days():
    rows = day_rows("2026-04-06") + day_rows(
        "2026-04-07", flat_hours={10: 300.0, 11: 300.0, 12: 300.0, 13: 300.0, 14: 300.0}
    )
    # a day that logs perfectly round zeros on everything for 13 hours
    dead = []
    first = pd.Timestamp("2026-04-08", tz=parse.MSK)
    for h in range(24):
        if 9 <= h < 22:
            row = raw_row(first.replace(hour=h), 0.0, speed=0.0, load=0.0, speed_r=0.0, load_r=0.0)
        else:
            row = raw_row(first.replace(hour=h), 200.0 + 7.0 * (h % 4))
        dead.append(row)
    short_day = [r for r in day_rows("2026-04-09") if r[1].hour < 18]
    table = make_table(rows + dead + short_day)
    found, bad = quality.detect_failures(table, SENSOR_IDS)
    by_type = {a["type"] for a in found}
    assert {"flatline", "zero_telemetry", "missing_hours"} <= by_type
    flat = next(a for a in found if a["type"] == "flatline")
    assert flat["starts_at"] == "2026-04-07T10:00:00+03:00"
    assert flat["ends_at"] == "2026-04-07T15:00:00+03:00"  # half-open, 5 stuck hours
    for stamp in pd.date_range("2026-04-08 09:00", "2026-04-08 21:00", freq="h"):
        assert stamp.tz_localize(parse.MSK) in bad[SID]


def test_missing_days_report_once_per_consecutive_run():
    # r22 reports each run of short days as ONE story, not one per day: the km 478
    # sensor was silent for months and 477 identical rows would bury everything else
    rows = day_rows("2026-04-06")
    rows += [r for r in day_rows("2026-04-07") if r[1].hour < 20]  # run of two ...
    rows += [r for r in day_rows("2026-04-08") if r[1].hour < 14]
    rows += day_rows("2026-04-09")  # a normal day splits the runs ...
    rows += [r for r in day_rows("2026-04-10") if r[1].hour < 22]  # ... by one lone day
    table = make_table(rows)
    found, _ = quality.detect_failures(table, SENSOR_IDS)
    missing = [a for a in found if a["type"] == "missing_hours"]
    assert len(missing) == 2
    days = {(a["starts_at"][:10], a["ends_at"][:10]) for a in missing}
    assert ("2026-04-07", "2026-04-09") in days  # run covers both short days
    assert ("2026-04-10", "2026-04-11") in days


def test_zero_speed_run_reports_once_and_repairs_singles():
    full = []
    first = pd.Timestamp("2026-04-07", tz=parse.MSK)
    for h in range(24):
        speed = 0.5 if h in (11, 12, 20) else 85.0
        full.append(raw_row(first.replace(hour=h), 200.0 + 7.0 * (h % 4), speed=speed))
    table = make_table(day_rows("2026-04-06") + full)
    found, _ = quality.detect_failures(table, SENSOR_IDS)
    zero = [a for a in found if a["type"] == "zero_speed"]
    assert len(zero) == 1  # the 2-hour run reports; the single hour only repairs
    assert zero[0]["starts_at"] == "2026-04-07T11:00:00+03:00"


def test_direction_tip_run_is_technical_and_untrusted():
    rows = []
    start = pd.Timestamp("2026-04-06", tz=parse.MSK)  # nine quiet weekday days ...
    for d in range(9):
        day = start + pd.Timedelta(days=d)
        for h in range(24):
            if 12 <= h <= 19:
                rows.append(raw_row(day.replace(hour=h), 220.0 + (h % 2) * 8.0))
            else:
                rows.append(raw_row(day.replace(hour=h), 20.0))
    tip_day = start + pd.Timedelta(days=10)  # ... then one day reading one side dead
    for h in range(24):
        if 12 <= h <= 19:
            value = 220.0 + (h % 2) * 8.0  # wobble, so a flat sensor is not the story
            rows.append(raw_row(tip_day.replace(hour=h), value, direct=0.0, reverse=value))
        else:
            rows.append(raw_row(tip_day.replace(hour=h), 20.0))
    table = make_table(rows)
    found, bad = quality.detect_failures(table, SENSOR_IDS)
    tips = [a for a in found if a["detector"] == "direction_share"]
    assert len(tips) == 1
    assert tips[0]["category"] == "technical"
    assert tips[0]["starts_at"] == "2026-04-16T12:00:00+03:00"
    for h in range(12, 20):
        assert pd.Timestamp(f"2026-04-16T{h:02d}:00", tz=parse.MSK) in bad[SID]


def test_fill_gaps_interpolates_short_and_profiles_long():
    rows = day_rows("2026-04-06") + day_rows("2026-04-07") + day_rows("2026-04-08")
    keep = []
    for i, row in enumerate(rows):
        day, hour = divmod(i, 24)
        if (day == 0 and hour in (10, 11)) or (day == 1 and 4 <= hour <= 8):
            continue  # holes: 2 hours then 5 hours
        keep.append(row)
    filled = quality.fill_gaps(make_table(keep), {}, SENSOR_IDS)
    stamps = filled["ts"]
    assert (stamps.diff().dropna() == pd.Timedelta(hours=1)).all()  # hole-free grid
    imputed = filled[filled["imputation_method"] != ""]
    assert set(imputed["imputation_method"]) == {"interpolation", "profile"}
    # the 2-hour hole interpolates; of the 5-hour one only its first 3 reach the
    # interpolation limit, the rest fall back to the same-kind day profile
    assert int(imputed["imputation_method"].eq("interpolation").sum()) == 5
    assert int(imputed["imputation_method"].eq("profile").sum()) == 2


# --- detectors ----------------------------------------------------------------------


def test_hourly_amplitude_needs_z_and_magnitude():
    specs = weeks_of_days("2026-04-06", 42)  # six of every weekday: norms can speak
    spike_day = pd.Timestamp("2026-04-22", tz=parse.MSK)  # a Wednesday
    by_ts = {s[0]: s[1] for s in specs}
    for h in range(12, 17):
        by_ts[spike_day.replace(hour=h).isoformat()]["volume"] = 420.0
    bump = pd.Timestamp("2026-04-30", tz=parse.MSK)
    for h in range(12, 17):
        by_ts[bump.replace(hour=h).isoformat()]["volume"] += 45.0  # real, but small
    work = work_hours(sorted(by_ts.items()))
    found = detect._hourly_amp(work, SID, "volume", "volume_drop", "volume_spike", "Поток")
    spikes = [a for a in found if a["type"] == "volume_spike"]
    assert len(spikes) == 1
    assert spikes[0]["starts_at"] == "2026-04-22T12:00:00+03:00"
    assert spikes[0]["ends_at"] == "2026-04-22T17:00:00+03:00"  # half-open run
    assert spikes[0]["is_mega"] is False  # filled early; finalize sets it, score set here


def test_speed_drop_is_measured_in_kmh():
    specs = weeks_of_days("2026-04-06", 42)
    by_ts = {s[0]: s[1] for s in specs}
    day = pd.Timestamp("2026-04-23", tz=parse.MSK)
    for h in range(13, 18):
        by_ts[day.replace(hour=h).isoformat()]["speed_direct"] = 48.0  # ~37 under norm
        by_ts[day.replace(hour=h).isoformat()]["speed_reverse"] = 84.0
    work = work_hours(sorted(by_ts.items()))
    found = detect._speed_drop(work, SID, "speed_direct", "volume_direct", "на Саратов")
    assert len(found) == 1
    assert found[0]["metric"] == "speed_direct"
    assert found[0]["actual"] < found[0]["expected"] - 20  # км/ч, not percent


def test_congestion_needs_slow_and_loaded_same_record():
    specs = weeks_of_days("2026-04-06", 40, volume=400.0)
    by_ts = {s[0]: s[1] for s in specs}
    slow_grid = pd.Timestamp("2026-05-06", tz=parse.MSK)  # 50/20 thresholds: hours in
    # slow WITHOUT load and loaded WITHOUT slow must both stay silent ...
    for h in range(9, 12):
        by_ts[slow_grid.replace(hour=h).isoformat()]["speed_direct"] = 25.0
    loaded = pd.Timestamp("2026-05-08", tz=parse.MSK)
    for h in range(9, 12):
        by_ts[loaded.replace(hour=h).isoformat()]["load_direct"] = 55.0
    queue = pd.Timestamp("2026-05-13", tz=parse.MSK)  # ... only both together report
    for h in range(9, 13):
        by_ts[queue.replace(hour=h).isoformat()]["speed_direct"] = 22.0
        by_ts[queue.replace(hour=h).isoformat()]["load_direct"] = 60.0
    work = work_hours(sorted(by_ts.items()))
    found = detect._congestion(work, SID, "speed_direct", "load_direct", "на Саратов")
    assert len(found) == 1
    assert found[0]["type"] == "congestion"
    assert found[0]["starts_at"] == "2026-05-13T09:00:00+03:00"
    assert found[0]["ends_at"] == "2026-05-13T13:00:00+03:00"


def test_promotion_bonus_once_and_capped():
    start = pd.Timestamp("2026-06-11T15:00", tz=parse.MSK)
    end = pd.Timestamp("2026-06-11T20:00", tz=parse.MSK)
    volume = detect.anomaly(
        SID,
        start,
        end,
        "traffic",
        "volume_spike",
        "amplitude",
        "medium",
        "volume",
        900.0,
        500.0,
        80.0,
        3.0,
        "поток",
    )
    speed = detect.anomaly(
        SID,
        start,
        end,
        "traffic",
        "speed_drop",
        "amplitude",
        "high",
        "speed_direct",
        40.0,
        80.0,
        -50.0,
        6.3,
        "скорость",
    )
    third = detect.anomaly(
        SID,
        start,
        end,
        "traffic",
        "congestion",
        "thresholds",
        "low",
        "load_direct",
        55.0,
        None,
        None,
        1.5,
        "затор",
    )
    done = detect.promote_correlated([volume, speed, third])
    scores = {a["type"]: a["score"] for a in done}
    assert scores["volume_spike"] == 3.5  # +0.5 once for a matching second channel
    assert scores["speed_drop"] == 6.5  # capped, never past 6.5
    assert scores["congestion"] == 1.5  # load is neither of the two channels
    detect.promote_correlated(done)  # a second pass changes nothing (marker sentence)
    assert scores == {a["type"]: a["score"] for a in done}


def test_monthly_pass_compares_each_month_with_the_other_years():
    # year-over-year pass: a month is compared with the same month of the other
    # years only (never with itself and never with the one year it is checked
    # against) - a real doubling of flow across 2024/2025 must speak
    tripping = weeks_of_days("2024-06-01", 61, volume=100.0) + weeks_of_days(
        "2025-06-01", 61, volume=300.0
    )
    done = detect.detect_monthly(filled_frame(sorted(tripping)), SENSOR_IDS)
    hits = {(f["type"], f["starts_at"][:7]) for f in done if f["detector"] == "yoy"}
    assert ("volume_drop", "2024-06") in hits
    assert ("volume_spike", "2025-06") in hits

    # two quiet years that look the same must produce no year-over-year findings
    calm = weeks_of_days("2024-06-01", 61, volume=100.0) + weeks_of_days(
        "2025-06-01", 61, volume=104.0
    )
    done = detect.detect_monthly(filled_frame(sorted(calm)), SENSOR_IDS)
    assert [f for f in done if f["detector"] == "yoy" and f["metric"] == "volume"] == []


# --- pipeline -----------------------------------------------------------------------


def test_event_linking_needs_matching_kind_and_near_day():
    anomaly = {
        "id": "r22-x-1",
        "sensor_id": SID,
        "category": "traffic",
        "type": "volume_spike",
        "starts_at": "2024-12-30T18:00:00+03:00",
        "ends_at": "2024-12-30T23:00:00+03:00",
        "event_id": None,
    }
    far = dict(
        anomaly,
        id="r22-x-2",
        starts_at="2024-12-20T18:00:00+03:00",
        ends_at="2024-12-20T23:00:00+03:00",
    )
    wrong_kind = dict(
        anomaly,
        id="r22-x-3",
        type="flatline",
        category="technical",
        starts_at="2024-12-30T20:00:00+03:00",
        ends_at="2024-12-30T22:00:00+03:00",
    )
    holiday = {
        "id": "r22-holiday-20241231",
        "date": "2024-12-31",
        "category": "holiday",
        "title": "кануны",
        "day": pd.Timestamp("2024-12-31").date(),
    }
    events_list = [holiday]
    links = pipeline.link_events([anomaly, far, wrong_kind], events_list)
    assert links[holiday["id"]] == 1  # eve of the holiday links; the far and
    assert anomaly["event_id"] == holiday["id"]  # technical neighbours do not
    assert far["event_id"] is None and wrong_kind["event_id"] is None


def test_states_put_imputed_above_anomaly():
    filled = filled_frame(
        [
            ("2026-05-05T11:00", {}),
            ("2026-05-05T12:00", {"imputation_method": "profile"}),
            ("2026-05-05T13:00", {}),
        ]
    )
    anomalies = [
        {
            "sensor_id": SID,
            "category": "traffic",
            "type": "volume_drop",
            "starts_at": "2026-05-05T11:00:00+03:00",
            "ends_at": "2026-05-05T14:00:00+03:00",
        }
    ]
    states = pipeline.mark_states(filled, anomalies)
    assert list(states) == ["anomaly", "imputed", "anomaly"]


def test_corporate_rows_get_levels_and_their_own_numbers(tmp_path):
    csv_text = (
        "sensor_id,starts,ends,category,type,severity,metric,actual,expected,"
        "deviation_pct,description\n"
        f"{SID},2025-07-05T08:00:00,2025-07-05T18:00:00,corporate,capacity_warning,"
        "orange,none,,,,ремонт полосы\n"
    )
    path = tmp_path / "corporate_findings.csv"
    path.write_text(csv_text, encoding="utf-8")
    items = corporate.load_corporate(path)
    assert items[0]["level"] == detect.level_from_score(2.8)  # orange, not the number
    assert items[0]["score"] is None and items[0]["is_mega"] is False
    numbered = pipeline.number_corporate(items)
    assert numbered[0]["id"] == "r22-corp-0001"


def test_events_strip_days(tmp_path):
    csv_text = (
        "id,date,category,title,description,source_url\n"
        "r22-holiday-20250101,2025-01-01,holiday,Новый год,,https://example.ru/a\n"
    )
    path = tmp_path / "events.csv"
    path.write_text(csv_text, encoding="utf-8")
    loaded = events.load_events(path)
    assert str(loaded[0]["day"]) == "2025-01-01"  # linking helper present ...
    assert "day" not in events.strip_days(loaded)[0]  # ... and stripped for the output
