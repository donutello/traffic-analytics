"""Tests for the R-298 module: parser, holidays, failures, gap fill, detectors, links.

Everything here runs on small made-up series; the thresholds tested are the ones the
module README settles (issues #29/#30)."""

import pandas as pd
from openpyxl import Workbook

from analysis.r298 import corporate, detect, events, holidays, parse, pipeline, quality

SECTION = "км 310+000 а/д Р-298 Курск-Борисоглебск"
SID = "r298-km310-000"
SENSOR_IDS = {SECTION: SID}

# class weights sum to 1 so the class balances hold exactly in every built row
CLASS_WEIGHTS = [0.50, 0.15, 0.10, 0.08, 0.04, 0.08, 0.05]


def raw_row(
    ts, volume, speed=85.0, load=5.0, speed_r=85.0, load_r=4.0, direct=None, reverse=None
) -> list:
    """One raw-table row whose own sums balance; only the knobs a test needs vary."""
    direct = volume / 2 if direct is None else direct
    reverse = volume / 2 if reverse is None else reverse
    numbers = [volume, direct, reverse]
    for weight in CLASS_WEIGHTS:  # each class split half and half by direction
        numbers += [direct * weight, reverse * weight]
    # interleave as class, class_direct, class_reverse like the export
    interleaved = [volume, direct, reverse]
    for weight in CLASS_WEIGHTS:
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
    assert all(a["id"].startswith("r298-") for a in done)
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
    done = detect.finalize([traffic_small, big])
    mega = {a["deviation_pct"]: a["is_mega"] for a in done}
    assert mega[-10.0] is False and mega[-61.0] is True


# --- parser -------------------------------------------------------------------------


def test_parse_reads_labels_commas_and_hours(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.append([SECTION, None, None])
    row = ["05.01.2026 00:59:59", "1 234,5"] + ["10"] * 27
    sheet.append(row)
    sheet.append(["итого", 10])
    path = tmp_path / "report.xlsx"
    book.save(path)

    table = parse.parse_traffic_excel(path)
    assert len(table) == 1
    hourly = table.iloc[0]
    assert hourly["ts"] == pd.Timestamp("2026-01-05T00:59:59").tz_localize(parse.MSK).floor("h")
    assert hourly["volume"] == 1234.5  # thin space and decimal comma handled
    assert table.iloc[0]["section"] == SECTION

    sensors = parse.build_sensors([SECTION])
    assert sensors[0]["id"] == SID
    assert sensors[0]["lat"] > 51 and sensors[0]["lon"] > 40  # real anchors, not 0.0
    assert sensors[0]["km"] == 310.0


# --- holidays -----------------------------------------------------------------------


def test_day_kinds_and_groups():
    assert holidays.day_kind(pd.Timestamp("2026-03-09")) == "holiday"
    assert holidays.day_kind(pd.Timestamp("2026-03-08")) == "weekend"
    assert holidays.day_kind(pd.Timestamp("2026-04-15")) == "weekday"
    # detection groups pool all days off, but name ordinary weekdays separately
    assert holidays.day_group(pd.Timestamp("2026-01-07")) == "holiday"
    assert holidays.day_group(pd.Timestamp("2026-05-11")) == "holiday"
    assert holidays.day_group(pd.Timestamp("2026-04-15")) == "weekday-2"
    assert holidays.day_group(pd.Timestamp("2026-04-18")) == "weekday-5"


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


def test_flatline_zero_telemetry_and_integrity():
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
    assert flat["ends_at"] == "2026-04-07T15:00:00+03:00"  # half-open
    for stamp in pd.date_range("2026-04-08 09:00", "2026-04-08 21:00", freq="h"):
        assert stamp.tz_localize(parse.MSK) in bad[SID]


def test_zero_speed_run_reports_once_and_repairs_singles():
    # one full day with a two-hour zero-speed run and one single dropout
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
    found = detect._speed_drop(work, SID, "speed_direct", "volume_direct", "на Борисоглебск")
    assert len(found) == 1
    assert found[0]["metric"] == "speed_direct"
    assert found[0]["actual"] < found[0]["expected"] - 20  # км/ч, not percent


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
        "medium",
        "speed_direct",
        55.0,
        80.0,
        -30.0,
        6.3,
        "скорость",
    )
    detect.promote_correlated([volume, speed])
    assert volume["score"] == 3.5  # +0.5 once
    assert speed["score"] == 6.5  # the cap, never past it
    assert volume["level"] == detect.level_from_score(3.5)
    detect.promote_correlated([volume, speed])  # the second pass changes nothing
    assert volume["score"] == 3.5 and speed["score"] == 6.5


def test_regime_change_fires_on_a_frozen_norm_without_overlap():
    specs = []
    first = pd.Timestamp("2026-03-01", tz=parse.MSK)
    for d in range(81):  # March-May: 30 kalm days, then everything moves up
        level = 4000.0 + 40.0 * (d % 4) if d < 61 else 6000.0 + 40.0 * (d % 4)
        specs.append(((first + pd.Timedelta(days=d)).isoformat(), {"volume": level}))
    days = detect._working_frame(filled_frame(specs))
    days = days[~days["day_imputed"]]
    found = detect._regime_changes(days, SID)
    assert found, "the step must be told as a regime"
    assert found[0]["detector"] == "regime"
    assert found[0]["starts_at"] >= "2026-05-01"
    starts = [a["starts_at"] for a in sorted(found, key=lambda a: a["starts_at"])]
    ends = [a["ends_at"] for a in sorted(found, key=lambda a: a["starts_at"])]
    for prev_end, next_start in zip(ends, starts[1:], strict=False):  # one pair short by design
        assert pd.Timestamp(next_start) >= pd.Timestamp(prev_end)  # windows never overlap


def test_monthly_pass_is_completeness_plus_trend():
    specs = []
    for month, volume in [(3, 4000.0), (4, 4150.0), (5, 4300.0), (6, 6100.0)]:
        days = [31, 30, 31, 30][month - 3]
        for d in range(1, days + 1):
            for h in (8, 14, 20):  # a coarse but complete enough hour set
                specs.append(
                    (f"2026-{month:02d}-{d:02d}T{h:02d}:00", {"volume": volume + 30.0 * h})
                )
    frame = filled_frame(specs)
    found = detect.detect_monthly(frame, {SECTION: SID})
    june = [a for a in found if a["detector"] == "trend" and a["starts_at"].startswith("2026-06")]
    assert len(june) == 1 and june[0]["type"] == "volume_spike"  # June stepped up
    assert not [
        a for a in found if a["starts_at"].startswith("2026-03") and a["detector"] == "trend"
    ]  # March has no two valid predecessors: silence, not guessing

    holey = list(specs)
    holey += [
        ("2026-07-05T12:00", {"volume": 6000.0, "imputation_method": "profile"}) for h in range(24)
    ]
    frame2 = filled_frame(holey)
    july = [
        a
        for a in detect.detect_monthly(frame2, {SECTION: SID})
        if a["starts_at"].startswith("2026-07")
    ]
    assert (
        len(july) == 1 and july[0]["type"] == "missing_hours" and july[0]["category"] == "technical"
    )


# --- events and corporate -------------------------------------------------------------


def test_events_file_loads_and_links_are_kind_aware():
    loaded = events.load_events()
    assert loaded and all(e["source_url"].startswith("https") for e in loaded)
    assert all(e["category"] in pipeline.EVENT_KINDS for e in loaded)
    stripped = events.strip_days(loaded)
    assert all("day" not in e for e in stripped)

    hit = detect.anomaly(
        SID,
        pd.Timestamp("2026-05-03T20:00", tz=parse.MSK),
        pd.Timestamp("2026-05-04T00:00", tz=parse.MSK),
        "traffic",
        "volume_drop",
        "amplitude",
        "high",
        "volume",
        1.0,
        2.0,
        -50.0,
        4.0,
        "тест",
    )
    miss = dict(hit, event_id=None, type="flatline", category="technical")
    far = dict(
        hit,
        event_id=None,
        starts_at="2026-05-31T20:00:00+03:00",
        ends_at="2026-06-01T00:00:00+03:00",
    )
    event = {
        "id": "r298-accident-0001",
        "category": "accident",
        "day": pd.Timestamp("2026-05-03").date(),
    }
    links = pipeline.link_events([hit, miss, far], [event])
    assert hit["event_id"] == "r298-accident-0001"
    assert miss["event_id"] is None and far["event_id"] is None
    assert links["r298-accident-0001"] == 1


def test_corporate_shape_and_numbering():
    items = corporate.load_corporate()
    assert 12 <= len(items) <= 18
    assert all(a["detector"] == "corporate" for a in items)
    assert all(a["score"] is None and a["is_mega"] is False for a in items)
    assert all(a["level"] in ("high", "medium", "low") for a in items)
    assert [a["starts_at"] for a in items] == sorted(a["starts_at"] for a in items)
    numbered = pipeline.number_corporate(items)
    assert numbered[0]["id"] == "r298-corp-0001"
