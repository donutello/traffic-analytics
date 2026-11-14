"""Technical failures and gap filling (issue #24), so failures never look like traffic.

Two steps, both before the traffic detectors run:

`detect_failures` reads the raw parsed table and reports what the sensor did not really
measure, as `technical` anomalies: days with fewer than 24 hours (an incomplete export
day or a whole lost day), a stuck sensor (the same volume > 10 авт./ч for at least 5
consecutive hours), zero speed while cars are counted, a dead reporter (every channel
reading zero for at least 12 consecutive hours), and one direction of the tube dead
(its count missing or starved to nothing while the other direction is busy - then the
hour's total counts one loop instead of two and must not be trusted either). It also
returns the set of hours no one should trust.

`fill_gaps` then rebuilds a hole-free hourly series per sensor: untrusted hours and
hours that never arrived are filled - a straight line between the neighbours for gaps
of 3 hours or less (`interpolation`), otherwise the median of the same hour on the same
kind of day (holiday apart, the norms sit on the other years of the export, `profile`).
Filled hours carry state `imputed` plus the method, and the traffic detectors skip
them, so a dead sensor is reported once, as technical, and never a second time as a
traffic anomaly.
"""

import numpy as np
import pandas as pd

from .detect import anomaly, level_from_score
from .holidays import day_kind

# Thresholds are settled in #25 and explained in the module README.
FLATLINE_MIN_HOURS = 5  # identical volume (real hours) from this run length: a stuck sensor
FLATLINE_MIN_VOLUME = 10  # below this the identical low count is plausible at night
DEAD_DIR_MIN_HOURS = 2  # one-direction hours to report one technical anomaly (all are imputed)
DEAD_DIR_ACTIVE_OTHER = 200  # the other direction must read this busy before a starved side counts
DEAD_DIR_STARVE_SHARE = 0.05  # a side under 5 % of the hour's total while the other is busy: dead
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
MIN_PROFILE_SAMPLES = 3  # same-kind hours needed before a median is trusted

SCORE_INTEGRITY = 3.0  # fixed rule weights, positioned on the shared v1 scale
SCORE_FLATLINE = 4.0
SCORE_ZERO_SPEED = 2.5
SCORE_DIRECTION = 2.8
SCORE_ZERO_TELEMETRY = 3.5  # louder than a partial lost day (3.0), quieter than a
# stuck sensor inventing plausible numbers (4.0): the hours are zeros nobody can read

NUMERIC = [
    "volume",
    "volume_direct",
    "volume_reverse",
    "cars",
    "small_trucks",
    "medium_trucks",
    "large_trucks",
    "road_trains",
    "buses",
    "motorcycles",
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


def detect_failures(df: pd.DataFrame, sensor_ids: dict[str, str]):
    """Technical anomalies from the raw table, plus the hours that must not be trusted.

    Returns `(anomalies, bad_hours)` where `bad_hours` maps sensor_id to the set of
    timestamps whose recorded values are unusable (stuck hours, dead speed hours).
    """
    found: list[dict] = []
    bad_hours: dict[str, set] = {}

    for section, sec_df in df.groupby("section"):
        sensor_id = sensor_ids[section]
        sec_df = sec_df.sort_values("ts").reset_index(drop=True)

        # A stuck sensor: the same volume (> 10 авт./ч) for FLATLINE_MIN_HOURS or more
        # consecutive hours. Runs may cross midnight, so the walk goes over the sensor's
        # whole series, hour by hour.
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
                bad_hours.setdefault(sensor_id, set()).update(stamps[run_start:i])
            run_start = i

        # Zero speed while the hour counts cars: the speed channel died. The hours are
        # untrusted even away from the stuck runs; overlap is skipped, one story each.
        # Single-hour dropouts only get repaired (imputed); from
        # ZERO_SPEED_MIN_ANOMALY_HOURS hours in a row it is worth an anomaly of its own.
        stuck = bad_hours.get(sensor_id, set())
        zero = (sec_df["volume"].fillna(0) >= 5) & (
            (sec_df["speed_direct"] <= ZERO_SPEED_KMH) | (sec_df["speed_reverse"] <= ZERO_SPEED_KMH)
        )
        zero &= sec_df["ts"].notna()
        for start, end in _consecutive_runs(sec_df["ts"], zero):
            hours = pd.date_range(start, end, freq="h", inclusive="left")
            if any(ts in stuck for ts in hours):
                continue
            bad_hours.setdefault(sensor_id, set()).update(hours)
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
        # that is the reporter itself sending emptiness. From ZERO_TEL_MIN_HOURS in a
        # row the run is reported, and every such hour is untrusted either way: no
        # traffic detector may read a dead reporter as an empty road.
        packet_zero = sec_df["ts"].notna()
        for column in TELEMETRY_CHANNELS:
            packet_zero &= sec_df[column].fillna(-1.0).eq(0.0)
        for start, end in _consecutive_runs(sec_df["ts"], packet_zero):
            hours = pd.date_range(start, end, freq="h", inclusive="left")
            if len(hours) < ZERO_TEL_MIN_HOURS:
                continue
            bad_hours.setdefault(sensor_id, set()).update(hours)
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
        tz = sec_df["ts"].iloc[0].tzinfo
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

        # One direction of the tube dead: its hour is missing from the export or stays
        # under 5 % of the total while the other direction reads busy. The hour then
        # counts one loop instead of two: never traffic. Runs of DEAD_DIR_MIN_HOURS get
        # one technical anomaly; a run that overlaps hours another failure already tells
        # (or that overlaps another already-reported blind run) keeps no second story.
        total = sec_df["volume"]
        direct_dead = sec_df["volume_direct"].isna() | (
            (total > 0)
            & (sec_df["volume_direct"] <= DEAD_DIR_STARVE_SHARE * total)
            & (sec_df["volume_reverse"] > DEAD_DIR_ACTIVE_OTHER)
        )
        reverse_dead = sec_df["volume_reverse"].isna() | (
            (total > 0)
            & (sec_df["volume_reverse"] <= DEAD_DIR_STARVE_SHARE * total)
            & (sec_df["volume_direct"] > DEAD_DIR_ACTIVE_OTHER)
        )
        blind = (direct_dead | reverse_dead) & sec_df["ts"].notna()
        reported = set(bad_hours.get(sensor_id, ()))
        for start, end in _consecutive_runs(sec_df["ts"], blind):
            hours = pd.date_range(start, end, freq="h", inclusive="left")
            bad_hours.setdefault(sensor_id, set()).update(hours)
            if len(hours) < DEAD_DIR_MIN_HOURS or any(ts in reported for ts in hours):
                continue
            window = sec_df[sec_df["ts"].isin(hours)]
            straight = int(direct_dead[window.index].sum())
            side = "прямого" if straight >= len(window) // 2 else "обратного"
            reported.update(hours)
            found.append(
                anomaly(
                    sensor_id,
                    start,
                    end,
                    "technical",
                    "direction_imbalance",
                    "direction",
                    level_from_score(SCORE_DIRECTION),
                    "volume",
                    float(len(hours)),
                    None,
                    None,
                    SCORE_DIRECTION,
                    f"Датчик {side} направления не работал {len(hours)} часов подряд: "
                    "поток считала только одна петля",
                )
            )

    return found, bad_hours


def fill_gaps(df: pd.DataFrame, bad_hours: dict[str, set], sensor_ids: dict[str, str]):
    """A complete hole-free hourly table per sensor from its first to its last hour.

    Untrusted hours are dropped first, then every hole is filled: holes of at most
    MAX_INTERPOLATE_HOURS by a straight line between the neighbours, longer ones by the
    median of the same hour on the same kind of day. Returns the expanded table with
    `sensor_id`, `imputation_method` ('' means the values stayed real) and `ts` grid.
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
        todo = missing & (table["imputation_method"] == "")
        for bucket in (
            table[~missing].groupby(["month", "day_type", "hour"])[NUMERIC].median(),
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
