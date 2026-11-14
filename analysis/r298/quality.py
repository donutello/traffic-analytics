"""Technical failures and gap filling (issue #29), so a broken sensor never looks like traffic.

Two steps, both before the traffic detectors run:

`detect_failures` reads the raw parsed table and reports what the sensor did not really
measure, as `technical` anomalies: days with fewer than 24 hours (an incomplete export
day or a whole lost day), a stuck sensor (the same volume > 10 авт./ч for at least 5
consecutive hours), zero speed while cars are counted, a dead reporter (every channel
reading zero for at least 12 consecutive hours), hours whose own numbers contradict each
other (the direction and vehicle-class sums must add up to the hour total), and months
where that balance disagrees again and again in the same direction (a metering drift).
It also returns the set of hours no one should trust.

Direction splits get one extra check, baseline-relative rather than a fixed band: the
customer's export for this road really can run almost one-sided at night (an A-134-style
"outside 15-85 % is broken" rule would call normal R-298 nights broken), so an hour is
suspect only when its direct share moves more than 25 п.п. away from the median share of
the same hour on the same kind of day, on hours busy enough for a share to mean
something. Long same-direction runs of those hours read as one loop dying, not as traffic.

`fill_gaps` then rebuilds a hole-free hourly series per sensor: untrusted hours and
hours that never arrived are filled - a straight line between the neighbours for gaps of
3 hours or less (`interpolation`), otherwise the median of the same hour on the same
kind of day (holiday apart). Filled hours carry state `imputed` plus the method, and
the traffic detectors skip them, so a dead sensor is reported once, as technical, and
never a second time as a traffic anomaly.
"""

import numpy as np
import pandas as pd

from .detect import anomaly, level_from_score
from .holidays import day_kind

# Thresholds are settled in #29 and argued in the module README.
FLATLINE_MIN_HOURS = 5  # identical volume (real hours) from this run length: a stuck sensor
FLATLINE_MIN_VOLUME = 10  # below this the identical low count is plausible at night
ZERO_SPEED_KMH = 1.0  # speed at or below this while cars pass: the speed channel died
ZERO_SPEED_MIN_ANOMALY_HOURS = 2  # single-hour dropouts are repaired by imputation, not reported
ZERO_TEL_MIN_HOURS = 12  # hours of all-zero channels that pass for a dead reporter
# the seven channels of one reported hour; all zero at once is what a dead
# reporter ships (dilczech's zero-packet check), not what an empty road logs
TELEMETRY_CHANNELS = [
    "volume",
    "volume_direct",
    "volume_reverse",
    "speed_direct",
    "speed_reverse",
    "load_direct",
    "load_reverse",
]
MAX_INTERPOLATE_HOURS = 3  # longer holes get the day-profile median instead
BALANCE_TOL_ABS = 10.0  # авт./ч of slack that counting rounding always has
BALANCE_TOL_REL = 0.02  # ... plus 2 % of the hour, on whichever side of the gap is larger
BALANCE_AUDIT_MIN_HOURS = 30  # disagreeing hours of the month needed before it speaks
BALANCE_AUDIT_MIN_DAYS = 7  # ... spread over at least this many days
BALANCE_AUDIT_SIGN_SHARE = 0.8  # ... with this share of them on the same side
BALANCE_AUDIT_MEDIAN = 5.0  # ... and a median disagreement of at least this many cars
SHARE_DEV_PP = 25.0  # п.п. the direct share of the same-kind hour norm the flow may tip by
SHARE_MIN_RUN = 4  # hours in a row of the same tip before it is one finding
SHARE_MIN_VOLUME = 60  # hour volume under which a share of a handful of cars is noise
SHARE_MIN_REF_HOURS = 6  # same-kind hours of that hour needed before its norm speaks
SCORE_INTEGRITY = 3.0  # fixed rule weights, positioned on the shared v1 scale
SCORE_FLATLINE = 4.0
SCORE_ZERO_SPEED = 2.8
SCORE_DIRECTION = 2.8
SCORE_ZERO_TELEMETRY = 3.5  # louder than a partial lost day (3.0), quieter than a
# stuck sensor inventing plausible numbers (4.0): the hours are zeros nobody can read
SCORE_BALANCE_DRIFT = 3.2  # silent metering drift: quieter than a flat sensor, louder
# than one lost hour group (3.0), because it corrupts every number it touches quietly

CLASS_COLUMNS = [
    "cars",
    "small_trucks",
    "medium_trucks",
    "large_trucks",
    "road_trains",
    "buses",
    "motorcycles",
]

NUMERIC = [
    "volume",
    "volume_direct",
    "volume_reverse",
    *CLASS_COLUMNS,
    "speed_direct",
    "speed_reverse",
    "load_direct",
    "load_reverse",
]


def _consecutive_runs(ts: pd.Series, mask: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """[start, end) of every run of `mask` whose timestamps are consecutive hours."""
    good = pd.DataFrame({"ts": ts[mask]})
    break_start = good["ts"].diff() != pd.Timedelta(hours=1)
    runs = []
    for _, group in good.groupby(break_start.cumsum()):
        start = group["ts"].iloc[0]
        runs.append((start, group["ts"].iloc[-1] + pd.Timedelta(hours=1)))
    return runs


def _balance_checks(
    sec_df: pd.DataFrame, sensor_id: str, tz, found: list[dict], bad_hours: set
) -> None:
    """Hour identity checks and the monthly systematic audit of both balances.

    Four identities per hour: the two directions must add to the total, the seven
    classes must add to the total, and each direction's classes must add to that
    direction's count (the class splits by direction this export ships, checked on the
    raw table). Hours that break any of them beyond the tolerance are not traffic and
    not usable; a month that breaks again and again mostly in one direction is a
    metering drift and gets one finding of its own.
    """
    complete_dir = (
        sec_df["volume"].notna()
        & sec_df["volume_direct"].notna()
        & sec_df["volume_reverse"].notna()
    )
    complete_cls = sec_df["volume"].notna() & sec_df[CLASS_COLUMNS].notna().all(axis=1)
    class_direct = [f"{column}_direct" for column in CLASS_COLUMNS]
    class_reverse = [f"{column}_reverse" for column in CLASS_COLUMNS]
    complete_cls_dir = sec_df["volume_direct"].notna() & sec_df[class_direct].notna().all(axis=1)
    complete_cls_rev = sec_df["volume_reverse"].notna() & sec_df[class_reverse].notna().all(axis=1)

    parts = pd.DataFrame({"ts": sec_df["ts"]})
    parts["directions"] = np.where(
        complete_dir,
        sec_df["volume"] - sec_df["volume_direct"] - sec_df["volume_reverse"],
        np.nan,
    )
    parts["classes"] = np.where(
        complete_cls, sec_df["volume"] - sec_df[CLASS_COLUMNS].sum(axis=1), np.nan
    )
    parts["classes_direct"] = np.where(
        complete_cls_dir,
        sec_df["volume_direct"] - sec_df[class_direct].sum(axis=1),
        np.nan,
    )
    parts["classes_reverse"] = np.where(
        complete_cls_rev,
        sec_df["volume_reverse"] - sec_df[class_reverse].sum(axis=1),
        np.nan,
    )
    parts["month"] = parts["ts"].dt.tz_localize(None).dt.to_period("M")

    # The tolerance grows with the larger side of the gap (dilczech), so a big hour is
    # judged in percent, a small one gets its rounding slack.
    def tolerance(left: pd.Series, right: pd.Series) -> pd.Series:
        bigger = pd.concat([left.abs(), right.abs()], axis=1).max(axis=1)
        return np.maximum(BALANCE_TOL_ABS, bigger * BALANCE_TOL_REL)

    hard = pd.Series(False, index=sec_df.index)
    for name, left, right in (
        ("directions", sec_df["volume"], sec_df["volume_direct"] + sec_df["volume_reverse"]),
        ("classes", sec_df["volume"], sec_df[CLASS_COLUMNS].sum(axis=1)),
        (
            "classes_direct",
            sec_df["volume_direct"],
            sec_df[class_direct].sum(axis=1),
        ),
        (
            "classes_reverse",
            sec_df["volume_reverse"],
            sec_df[class_reverse].sum(axis=1),
        ),
    ):
        hard |= parts[name].abs() > tolerance(left, right)
    bad_hours.update(parts.loc[hard, "ts"])

    for name in ("directions", "classes", "classes_direct", "classes_reverse"):
        drifted = parts[parts[name].abs() >= 1.0]
        for month, group in drifted.groupby("month"):
            diffs = group[name]
            hours = len(group)
            days = group["ts"].dt.date.nunique()
            if hours < BALANCE_AUDIT_MIN_HOURS or days < BALANCE_AUDIT_MIN_DAYS:
                continue
            above = float((diffs > 0).mean())
            below = float((diffs < 0).mean())
            dominant = max(above, below)
            median_diff = float(diffs.abs().median())
            if dominant < BALANCE_AUDIT_SIGN_SHARE or median_diff < BALANCE_AUDIT_MEDIAN:
                continue
            sign = 1 if above >= below else -1
            words = {
                "directions": "сумма двух направлений расходилась",
                "classes": "сумма классов техники расходилась",
                "classes_direct": "сумма классов прямого направления расходилась",
                "classes_reverse": "сумма классов обратного направления расходилась",
            }[name]
            start = month.start_time.tz_localize(tz)
            found.append(
                anomaly(
                    sensor_id,
                    start,
                    (month + 1).start_time.tz_localize(tz),
                    "technical",
                    "balance_drift",
                    "balance",
                    level_from_score(SCORE_BALANCE_DRIFT),
                    "volume",
                    float(sign * median_diff),
                    0.0,
                    None,
                    SCORE_BALANCE_DRIFT,
                    f"За месяц в {hours} часах {words} с общим счётом в среднем на "
                    f"{median_diff:.0f} авт./ч, почти всегда в одну сторону: "
                    "учёт стабильно не сходится",
                )
            )


def _share_checks(sec_df: pd.DataFrame, sensor_id: str, found: list[dict], bad_hours: set) -> None:
    """The baseline-relative direction-merge check: long tips away from the hour norm.

    Every busy hour gets its direct share, compared with the median share of the same
    hour on the same kind of day (only trusted hours set that norm, and hours quiet
    enough for the share to be noise say nothing). An hour tipped >= SHARE_DEV_PP п.п.
    is unreadable - either one loop under-counts its direction, or the sensor really
    only sees one direction - so it goes to `bad_hours` and never reads as traffic.
    Runs of SHARE_MIN_RUN tipped hours to the same side get one anomaly. The known
    false-alarm of this rule: a one-sided road closure or detour that empties one
    direction for hours looks exactly like a dead loop from a counter's point of view.
    """
    trusted = ~sec_df["ts"].isin(bad_hours)
    busy = sec_df[trusted & (sec_df["volume"] >= SHARE_MIN_VOLUME)].copy()
    if busy.empty:
        return
    busy["share"] = busy["volume_direct"] / busy["volume"] * 100.0
    busy["day_type"] = [day_kind(ts) for ts in busy["ts"]]
    busy["hour"] = [ts.hour for ts in busy["ts"]]
    ref_counts = busy.groupby(["day_type", "hour"])["share"].count()
    norm = busy.groupby(["day_type", "hour"])["share"].median()
    keys = pd.MultiIndex.from_frame(busy[["day_type", "hour"]])
    share_norm = pd.Series(np.nan, index=busy.index)
    usable = ref_counts.reindex(keys).to_numpy() >= SHARE_MIN_REF_HOURS
    share_norm[usable] = norm.reindex(keys[usable]).to_numpy()
    busy["tip_pp"] = busy["share"] - share_norm
    tipped = busy[busy["tip_pp"].abs() >= SHARE_DEV_PP].sort_values("ts")
    if tipped.empty:
        return

    reported = set()
    for start, end in _consecutive_runs(tipped["ts"], pd.Series(True, index=tipped.index)):
        run = tipped[(tipped["ts"] >= start) & (tipped["ts"] < end)]
        bad_hours.update(run["ts"])
        same_side = run["tip_pp"] > 0
        if len(run) < SHARE_MIN_RUN or not same_side.all() and not (~same_side).all():
            continue
        if any(ts in reported for ts in run["ts"]):
            continue
        reported.update(run["ts"])
        sign = 1 if same_side.iloc[0] else -1
        side = "прямого" if sign > 0 else "обратного"
        tip = float(run["tip_pp"].abs().median())
        actual = float(run["share"].median())
        score = SCORE_DIRECTION
        found.append(
            anomaly(
                sensor_id,
                start,
                end,
                "technical",
                "direction_imbalance",
                "direction_share",
                level_from_score(score),
                "volume",
                actual,
                float(actual - sign * tip),
                None,
                score,
                f"Доля прямого направления отклонялась от обычного для этих часов "
                f"{len(run)} часов подряд в среднем на {tip:.0f} п.п. "
                f"(в сторону {side}): одна петля, похоже, перестала считать",
            )
        )


def detect_failures(df: pd.DataFrame, sensor_ids: dict[str, str]):
    """Technical anomalies from the raw table, plus the hours that must not be trusted.

    Returns `(anomalies, bad_hours)` where `bad_hours` maps sensor_id to the set of
    timestamps whose recorded values are unusable (stuck hours, dead speed hours,
    hours whose own numbers contradict each other, tipped direction splits).
    """
    found: list[dict] = []
    bad_hours: dict[str, set] = {}

    for section, sec_df in df.groupby("section"):
        sensor_id = sensor_ids[section]
        sec_df = sec_df.sort_values("ts").reset_index(drop=True)
        tz = sec_df["ts"].iloc[0].tzinfo
        bad = bad_hours.setdefault(sensor_id, set())

        # Hours whose own sums contradict themselves, and the monthly drift audit.
        _balance_checks(sec_df, sensor_id, tz, found, bad)

        # A stuck sensor: the same volume (> 10 авт./ч) for FLATLINE_MIN_HOURS or more
        # consecutive hours. Runs may cross midnight, so the walk goes over the
        # sensor's whole series, hour by hour.
        stamps = sec_df["ts"].tolist()
        values = sec_df["volume"].tolist()
        run_start = 0
        for i in range(1, len(values) + 1):
            same = (
                i < len(values)
                and pd.notna(values[i])
                and values[i] == values[i - 1]
                and values[i] > FLATLINE_MIN_VOLUME
                and stamps[i] - stamps[i - 1] == pd.Timedelta(hours=1)
            )
            if same:
                continue
            run_len = i - run_start
            if run_len >= FLATLINE_MIN_HOURS:
                found.append(
                    anomaly(
                        sensor_id,
                        stamps[run_start],
                        stamps[i - 1] + pd.Timedelta(hours=1),
                        "technical",
                        "flatline",
                        "sensor",
                        level_from_score(SCORE_FLATLINE),
                        "volume",
                        values[run_start],
                        None,
                        None,
                        SCORE_FLATLINE,
                        f"Интенсивность не менялась {run_len} часов подряд "
                        f"({int(values[run_start])} авт./ч): датчик завис",
                    )
                )
                bad.update(stamps[run_start:i])
            run_start = i

        # Zero speed while the hour counts cars: the speed channel died. The hours are
        # untrusted even away from the stuck runs; overlap is skipped, one story each.
        # Single-hour dropouts only get repaired (imputed); from
        # ZERO_SPEED_MIN_ANOMALY_HOURS hours in a row it is worth an anomaly of its own.
        zero = (sec_df["volume"].fillna(0) >= 5) & (
            (sec_df["speed_direct"] <= ZERO_SPEED_KMH) | (sec_df["speed_reverse"] <= ZERO_SPEED_KMH)
        )
        for start, end in _consecutive_runs(sec_df["ts"], zero):
            hours = pd.date_range(start, end, freq="h", inclusive="left")
            if any(ts in bad for ts in hours):
                continue
            bad.update(hours)
            if len(hours) < ZERO_SPEED_MIN_ANOMALY_HOURS:
                continue
            found.append(
                anomaly(
                    sensor_id,
                    start,
                    end,
                    "technical",
                    "zero_speed",
                    "sensor",
                    level_from_score(SCORE_ZERO_SPEED),
                    "speed_direct",
                    0.0,
                    None,
                    None,
                    SCORE_ZERO_SPEED,
                    f"Скорость 0 км/ч при трафике {len(hours)} часов подряд: "
                    "датчик скорости не работает",
                )
            )

        # All seven channels exactly zero for hours on end (dilczech's zero-packet
        # suspicion): a road can go quiet in a storm, but it does not log a perfectly
        # round zero on every channel, every direction, for half a day at a time -
        # that is the reporter itself sending emptiness.
        packet_zero = sec_df["ts"].notna()
        for column in TELEMETRY_CHANNELS:
            packet_zero &= sec_df[column].fillna(-1.0).eq(0.0)
        for start, end in _consecutive_runs(sec_df["ts"], packet_zero):
            hours = pd.date_range(start, end, freq="h", inclusive="left")
            if len(hours) < ZERO_TEL_MIN_HOURS:
                continue
            bad.update(hours)
            found.append(
                anomaly(
                    sensor_id,
                    start,
                    end,
                    "technical",
                    "zero_telemetry",
                    "sensor",
                    level_from_score(SCORE_ZERO_TELEMETRY),
                    "volume",
                    0.0,
                    None,
                    None,
                    SCORE_ZERO_TELEMETRY,
                    f"Все каналы читали ноль {len(hours)} часов подряд: "
                    "телеметрия молчала, датчик ничего не измерил",
                )
            )

        # Days of the export period shorter than 24 hours: lost connection, an incomplete
        # report or a whole lost day (then 0 из 24). One technical anomaly per day.
        counts = sec_df["ts"].dt.date.value_counts()
        for day in pd.date_range(sec_df["ts"].min(), sec_df["ts"].max(), freq="D").date:
            hours = int(counts.get(day, 0))
            if hours == 24:
                continue
            day_ts = pd.Timestamp(day, tz=tz)
            found.append(
                anomaly(
                    sensor_id,
                    day_ts,
                    day_ts + pd.Timedelta(days=1),
                    "technical",
                    "missing_hours",
                    "integrity",
                    level_from_score(SCORE_INTEGRITY),
                    "volume",
                    hours,
                    24,
                    (hours - 24) / 24 * 100,
                    SCORE_INTEGRITY,
                    f"Из 24 часов в сутках сохранено лишь {hours}",
                )
            )

        # The direction split tipped long away from its own hour norm: checked last,
        # so the failures above set the norm and keep their own hours out of it.
        _share_checks(sec_df, sensor_id, found, bad)

    return found, bad_hours


def fill_gaps(df: pd.DataFrame, bad_hours: dict[str, set], sensor_ids: dict[str, str]):
    """A complete hole-free hourly table per sensor from its first to its last hour.

    Untrusted hours are dropped first, then every hole is filled: holes of at most
    MAX_INTERPOLATE_HOURS by a straight line between the neighbours, longer ones by the
    median of the same hour on the same kind of day, starting from the most similar
    days and relaxing. Returns the expanded table with `sensor_id`,
    `imputation_method` ('' means the values stayed real) and a gap-free `ts` grid.
    """
    parts = []
    for section, sec_df in df.groupby("section"):
        sensor_id = sensor_ids[section]
        grid = pd.DataFrame({"ts": pd.date_range(sec_df["ts"].min(), sec_df["ts"].max(), freq="h")})
        table = grid.merge(sec_df[["ts", *NUMERIC]], on="ts", how="left")
        if bad_hours.get(sensor_id):
            table.loc[table["ts"].isin(bad_hours[sensor_id]), NUMERIC] = np.nan

        missing = table["volume"].isna()
        table["day_type"] = [day_kind(ts) for ts in table["ts"]]
        table["hour"] = [ts.hour for ts in table["ts"]]
        table["month"] = [ts.month for ts in table["ts"]]
        table["imputation_method"] = ""

        # Short holes: a straight line, and only inside the series.
        if missing.any():
            interpolated = {
                column: table[column].interpolate(
                    method="linear", limit=MAX_INTERPOLATE_HOURS, limit_area="inside"
                )
                for column in NUMERIC
            }
            for column in NUMERIC:
                table.loc[missing, column] = interpolated[column][missing]
            table.loc[missing & table["volume"].notna(), "imputation_method"] = "interpolation"

        # Long holes: the median of the same hour on the same kind of day, starting from
        # the most similar days and relaxing; only hours with nothing yet are touched.
        # (No year-month bucket here: this export covers one spring and summer of one
        # year, so a month bucket would hold a single copy of itself.)
        todo = missing & (table["imputation_method"] == "")
        for bucket in (
            table[~missing].groupby(["day_type", "hour"])[NUMERIC].median(),
            table[~missing].groupby("hour")[NUMERIC].median(),
        ):
            if not todo.any():
                break
            idx = table.index[todo & table["volume"].isna()]
            if len(idx) == 0:
                continue
            filled_values = bucket.reindex(
                pd.MultiIndex.from_frame(table.loc[idx, bucket.index.names])
            )
            for column in NUMERIC:
                current = table.loc[idx, column].to_numpy(dtype="float64")
                candidate = filled_values[column].to_numpy(dtype="float64")
                table.loc[idx, column] = np.where(np.isnan(current), candidate, current)
            table.loc[idx, "imputation_method"] = np.where(
                table.loc[idx, "volume"].notna(), "profile", ""
            )
            todo = missing & (table["imputation_method"] == "")

        # Hours left with a volume do exist now; mark them like the rest of the holes.
        table.loc[
            missing & table["volume"].notna() & (table["imputation_method"] == ""),
            "imputation_method",
        ] = "profile"
        # Without any same-kind history at all: the column's own median, still `profile`.
        leftover = missing & table["volume"].isna()
        for column in NUMERIC:
            table.loc[leftover & table[column].isna(), column] = table[column].median()
        table.loc[leftover, "imputation_method"] = "profile"

        table["section"] = section
        table["sensor_id"] = sensor_id
        parts.append(table)

    filled = pd.concat(parts, ignore_index=True).sort_values(["sensor_id", "ts"])
    return filled.reset_index(drop=True)
