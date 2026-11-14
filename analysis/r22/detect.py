"""Anomaly detectors for R-22, working on the gap-filled hourly table.

Every hourly detector compares an hour or a day with a sliding same-weekday norm: the
median of that same weekday (all days off pooled as one kind, see holidays.day_group)
within 84 days of the compared day, at least 6 such days. Sliding instead of
calendar-month pooling because the road has a clear seasonal cycle and three years of
history: the June evening of a sensor is compared with May and July evenings of both
nearby years, and a stormy month stays a minority of its own norm. The window looks
backwards AND forwards in time: this project is offline, so tomorrow is allowed to
explain today (issue #37, argued in the README).

Every finding comes out as a contract anomaly (English codes, a Russian `description`
for the dashboard). `level` is never chosen by hand: `level_from_score` buckets the
score the way contract v1 orders it. The detectors skip hours marked
`imputation_method` - those belong to the technical story (issue #36).
"""

import numpy as np
import pandas as pd

from .holidays import day_group
from .parse import ROAD

# Detection thresholds, settled in issue #37 and explained in the module README.
NORM_WINDOW_DAYS = 84  # a reference is a same-kind day this near in time
ROLL_WINDOW = f"{2 * NORM_WINDOW_DAYS + 1}D"  # the closed +-window as a pandas window
MIN_REF_DAYS = 6  # same-kind days the sliding norm needs before it speaks
HOURLY_Z = 3.0  # an hour is off when the robust z and the practical magnitude agree
HOURLY_MIN_RUN = 4  # hours of the same direction (drop or spike) to report one
PRACTICAL_HOUR_PCT, PRACTICAL_HOUR_ABS = 35.0, 50.0  # hourly volume: the deviation in
PRACTICAL_DAILY_PCT, PRACTICAL_DAILY_ABS = 25.0, 100.0  # % of norm AND cars must reach
DROUGHT_Z, SURGE_Z = -3.0, 3.0  # daily volume vs the sliding same-weekday norm
SPEED_DROP_KMH = 15.0  # км/ч a direction's speed must fall under its hour norm
SPEED_DROP_Z = 3.0  # ... and the robust z must agree
SPEED_DROP_MIN_RUN = 4  # hours in a row, the same rule as the hourly volume run
MAD_TO_SIGMA = 1.4826  # MAD to sigma for a normal distribution (modified z-score)
RELATIVE_FLOOR = 0.10  # sigma is never below 10 % of the norm...
FLOOR_VOLUME_HOUR = 20.0  # ... and never below these absolute floors: авт./ч hours,
FLOOR_VOLUME_DAY = 100.0  # авт./сутки days, км/ч speed, % load (dilczech floors)
FLOOR_SPEED, FLOOR_LOAD = 3.0, 2.0
CONGESTION_SPEED = 50.0  # км/ч, under which the hour counts as standing, per direction
CONGESTION_LOAD = 20.0  # %, lane occupancy confirming the congestion on the same record
CONGESTION_MIN_HOURS = 2  # single slow hours are measurement noise, a queue is a run
FREE_FLOW_SPEED = 80.0  # км/ч free flow on this two-lane rural stretch (ODM): the
# expected speed a congestion description measures itself against
PROFILE_CORR = 0.70  # day profile below this correlation with the norm: distorted
PROFILE_MIN_DAY_VOLUME = 1200  # a thin day correlates badly by noise alone
MONTH_COMPLETENESS = 75.0  # % of hours present, below which the whole month is suspect
MONTH_VALIDITY = 95.0  # % real hours a month needs to enter any monthly comparison
YOY_MADT_PCT = 25.0  # % the monthly average daily volume may deviate from its year norm
YOY_MIX_PP = 8.0  # percentage points the heavy-truck share may change
YOY_SPEED = 15.0  # км/ч the flow-weighted monthly speed may drop
YOY_LOAD_PCT = 20.0  # % the month's median lane occupancy may drift
MEGA_PCT = 60.0  # |deviation| of a traffic anomaly from which it is highlighted (FR3)

REGIME_MIN_DAYS = 7  # consecutive complete days one side of the frozen norm (dilczech)
REGIME_LOOKBACK_DAYS = 168  # how far back the frozen norm may reach
REGIME_MIN_REFS = 6  # same-weekday days the frozen norm needs
REGIME_RATIO_LO, REGIME_RATIO_HI = 0.75, 1.25  # "one side of the norm" means 25 %+ here

PROMOTE_STEP, PROMOTE_CAP = 0.5, 6.5  # volume+speed confirmation (dilczech promotion)
PROMOTION_NOTE = "вторым каналом"  # its presence in a description marks a used bonus
VOLUME_METRICS = frozenset({"volume", "volume_direct", "volume_reverse"})
SPEED_METRICS = frozenset({"speed_direct", "speed_reverse"})

SCORE_YOY_MADT_BASE = 3.5  # fixed rule weights for the monthly detectors (see README)
SCORE_YOY_SPEED_BASE = 2.5
SCORE_MIX_BASE = 2.0
SCORE_LOAD_BASE = 2.0
SCORE_MONTH_INTEGRITY = 3.0
SCORE_REGIME_BASE = 3.5  # regime starts at the high band and grows 0.1 per % beyond 25
SCORE_REGIME_CAP = 6.5
SCORE_PROFILE = 2.5
SCORE_CONGESTION = 4.5

WORDS = {
    "volume": "Поток",
    "volume_direct": "Поток (на Саратов)",
    "volume_reverse": "Поток (на Борисоглебск и М-4 «Дон»)",
    "speed_direct": "на Саратов",
    "speed_reverse": "на Борисоглебск и М-4 «Дон»",
}


def level_from_score(score: float | None) -> str:
    """The one place severity is decided, exactly the table of contract v1."""
    if score is None:
        raise ValueError("only a detector with a score may ask for a level")
    if score >= 5.0:
        return "critical"
    if score >= 3.5:
        return "high"
    if score >= 2.0:
        return "medium"
    return "low"


def anomaly(
    sensor_id: str,
    starts_at: pd.Timestamp,
    ends_at: pd.Timestamp,
    category: str,
    type_: str,
    detector: str,
    level: str,
    metric: str,
    actual: float | None,
    expected: float | None,
    deviation_pct: float | None,
    score: float | None,
    description: str,
) -> dict:
    """One anomaly by the contract; is_mega and event_id are set later by the caller."""
    return {
        "id": "",
        "sensor_id": sensor_id,
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "category": category,
        "type": type_,
        "detector": detector,
        "level": level,
        "metric": metric,
        "actual": None if actual is None else round(float(actual), 1),
        "expected": None if expected is None else round(float(expected), 1),
        "deviation_pct": None if deviation_pct is None else round(float(deviation_pct), 1),
        "score": None if score is None else max(0.0, round(float(score), 1)),
        "is_mega": False,
        "event_id": None,
        "description": description,
    }


def _sigma(median: float, mad: float, floor: float) -> float:
    """The floored robust scale of dilczech's baseline: sigma = max(1.4826*MAD,
    10 % of the norm, floor). The z thresholds keep their meaning on it."""
    return max(MAD_TO_SIGMA * mad, abs(median) * RELATIVE_FLOOR, floor)


def _floor_for(metric: str) -> float:
    if metric.startswith("speed"):
        return FLOOR_SPEED
    if metric.startswith("load"):
        return FLOOR_LOAD
    return FLOOR_VOLUME_HOUR


def _working_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["date"] = work["ts"].dt.date
    # tz-naive calendar key: the norm windows count days, and this export sits on one
    # fixed UTC+3 offset, so dropping it cannot shift a date across midnight
    work["date_ts"] = work["ts"].dt.tz_convert(None).dt.normalize()
    work["hour"] = work["ts"].dt.hour
    work["day_group"] = [day_group(ts) for ts in work["ts"]]
    work["hour_imputed"] = work["imputation_method"].ne("")
    work["day_imputed"] = work.groupby(["section", "date"])["hour_imputed"].transform("any")
    return work


def _rolling_stats(values: pd.Series, dates: pd.Series, floor: float) -> pd.DataFrame:
    """Sliding median, MAD and sigma of one (weekday-kind, hour) series by date.

    The window is the closed NORM_WINDOW_DAYS days to either side; a day gets a norm
    only once MIN_REF_DAYS same-kind days have telemetry inside its window (the first
    and last days of a sensor's coverage are the honest exceptions the README tells
    about; for the km 478 station this also means the norms across its long offline
    stretch are the two years of history on either side of the hole).
    """
    series = pd.Series(values.to_numpy(dtype="float64"), index=pd.DatetimeIndex(dates))
    series = series[~series.index.duplicated()].sort_index()
    median = series.rolling(ROLL_WINDOW, center=True, min_periods=MIN_REF_DAYS).median()
    mad = series.rolling(ROLL_WINDOW, center=True, min_periods=MIN_REF_DAYS).apply(
        lambda window: float(np.median(np.abs(window - np.median(window)))), raw=True
    )
    stats = pd.DataFrame({"median": median, "mad": mad})
    stats["sigma"] = [
        _sigma(median_value, mad_value, floor)
        for median_value, mad_value in zip(stats["median"], stats["mad"], strict=True)
    ]
    return stats


def _norms_for(work: pd.DataFrame, metric: str, floor: float) -> pd.DataFrame:
    """Norm table (median/mad/sigma per kind, hour and date) for one hour metric.

    Only the hours the caller placed in `work` (real, and, for speed, moving) set a
    norm; groups too thin to ever reach MIN_REF_DAYS simply produce no norms.
    """
    tables = []
    for (group, hour), part in work.groupby(["day_group", "hour"]):
        if part[metric].notna().sum() < MIN_REF_DAYS:
            continue
        values = part[metric].dropna()
        stats = _rolling_stats(values, part.loc[values.index, "date_ts"], floor)
        stats = stats[stats["median"].notna()].reset_index(names="date_ts")
        stats["day_group"], stats["hour"] = group, hour
        tables.append(stats)
    if not tables:
        return pd.DataFrame(columns=["date_ts", "day_group", "hour", "median", "mad", "sigma"])
    return pd.concat(tables, ignore_index=True)


def _hourly_amp(
    work: pd.DataFrame, sensor_id: str, metric: str, low_type: str, high_type: str, noun: str
) -> list[dict]:
    """Hours versus the sliding same-weekday norm of the same hour: deviant runs.

    A daily sum hides an accident: twelve hours cut in half still leave a day that
    looks normal. So every real hour is compared with the sliding median of that same
    weekday (holiday kind apart), and an hour counts as deviant only when BOTH the
    modified z against the floored robust scale and the practical magnitude test pass:
    |actual - norm| must reach max(35 % of the norm, 50 авт./ч) (dilczech's AND, which
    quiets the night hours that a pure percent or pure z rule used to shout about).
    >= HOURLY_MIN_RUN deviant hours in a row become one anomaly with the exact
    half-open interval. Runs over the total volume and over each direction separately.
    """
    found: list[dict] = []
    norms = _norms_for(work, metric, _floor_for(metric))
    if norms.empty:
        return found
    marked = work.merge(norms, on=["day_group", "hour", "date_ts"], how="inner")
    marked["z"] = (marked[metric] - marked["median"]) / marked["sigma"]
    marked["residual"] = marked[metric] - marked["median"]
    marked["dev"] = np.where(marked["median"] > 0, marked["residual"] / marked["median"] * 100, 0.0)
    bar = np.maximum(marked["median"] * PRACTICAL_HOUR_PCT / 100.0, PRACTICAL_HOUR_ABS)
    drop = (marked["z"] <= -HOURLY_Z) & (marked["residual"] <= -bar)
    spike = (marked["z"] >= HOURLY_Z) & (marked["residual"] >= bar)
    marked["flag"] = np.where(drop, -1, np.where(spike, 1, 0))
    marked = marked.sort_values("ts")
    for sign, type_, verb in ((-1, low_type, "ниже"), (1, high_type, "выше")):
        flagged = marked[marked["flag"] == sign]
        if flagged.empty:
            continue
        gaps = flagged["ts"].diff() != pd.Timedelta(hours=1)
        for _, run in flagged.groupby(gaps.cumsum()):
            if len(run) < HOURLY_MIN_RUN:
                continue
            start, end = run["ts"].iloc[0], run["ts"].iloc[-1] + pd.Timedelta(hours=1)
            actual = float(run[metric].mean())
            expected = float(run["median"].mean())
            dev = (actual - expected) / expected * 100 if expected > 0 else 0.0
            score = min(float(run["z"].abs().max()), 9.9)
            found.append(
                anomaly(
                    sensor_id,
                    start,
                    end,
                    "traffic",
                    type_,
                    "amplitude",
                    level_from_score(score),
                    metric,
                    actual,
                    expected,
                    dev,
                    score,
                    f"{noun} держится {verb} нормы на {abs(dev):.0f}% в течение "
                    f"{len(run)} часов подряд (с {start:%H:%M}, |z| = {score:.1f})",
                )
            )
    return found


def _speed_drop(
    work: pd.DataFrame, sensor_id: str, speed_metric: str, volume_metric: str, where: str
) -> list[dict]:
    """One direction's speed against its own sliding hour norm, measured in км/ч.

    Norms are built only from hours where this direction really counted cars (an empty
    hour logs a meaningless speed), and an hour is flagged only when its own direction
    is moving too, the speed lies at SPEED_DROP_KMH км/ч or more under the norm, and
    the robust z agrees. >= SPEED_DROP_MIN_RUN such hours in a row make one anomaly.
    """
    found: list[dict] = []
    moving = work[work[volume_metric] > 0]
    norms = _norms_for(moving, speed_metric, FLOOR_SPEED)
    if norms.empty:
        return found
    marked = moving.merge(norms, on=["day_group", "hour", "date_ts"], how="inner")
    marked["gap"] = marked[speed_metric] - marked["median"]
    marked["z"] = marked["gap"] / marked["sigma"]
    flagged = marked[(marked["gap"] <= -SPEED_DROP_KMH) & (marked["z"] <= -SPEED_DROP_Z)]
    flagged = flagged.sort_values("ts")
    gaps = flagged["ts"].diff() != pd.Timedelta(hours=1)
    for _, run in flagged.groupby(gaps.cumsum()):
        if len(run) < SPEED_DROP_MIN_RUN:
            continue
        start, end = run["ts"].iloc[0], run["ts"].iloc[-1] + pd.Timedelta(hours=1)
        actual = float(run[speed_metric].mean())
        expected = float(run["median"].mean())
        dev = (actual - expected) / expected * 100 if expected > 0 else 0.0
        score = min(float(run["z"].abs().max()), 9.9)
        found.append(
            anomaly(
                sensor_id,
                start,
                end,
                "traffic",
                "speed_drop",
                "amplitude",
                level_from_score(score),
                speed_metric,
                actual,
                expected,
                dev,
                score,
                f"Скорость {where} держится ниже нормы на {abs(actual - expected):.0f} "
                f"км/ч в течение {len(run)} часов подряд (с {start:%H:%M}, "
                f"|z| = {score:.1f})",
            )
        )
    return found


def _daily_amp(days: pd.DataFrame, sensor_id: str) -> list[dict]:
    """Whole days versus the sliding same-weekday norm of daily volume.

    Same AND-test as the hourly pass: z and a deviation of max(25 % of the norm,
    100 авт./сутки) must both agree; the floored scale is what keeps a calm summer's
    tight MAD from inflating z. Only complete non-imputed days arrive here."""
    found: list[dict] = []
    if days.empty:
        return found
    daily = days.groupby(["day_group", "date", "date_ts"], as_index=False)["volume"].sum()
    tables = []
    for group, part in daily.groupby("day_group"):
        if len(part) < MIN_REF_DAYS:
            continue
        stats = _rolling_stats(part["volume"], part["date_ts"], FLOOR_VOLUME_DAY)
        stats = stats[stats["median"].notna()].reset_index(names="date_ts")
        stats["day_group"] = group
        tables.append(stats)
    if not tables:
        return found
    norms = pd.concat(tables, ignore_index=True)
    marked = daily.merge(norms, on=["day_group", "date_ts"], how="inner")
    marked = marked.rename(columns={"median": "norm_median"})
    marked["residual"] = marked["volume"] - marked["norm_median"]
    marked["z"] = marked["residual"] / marked["sigma"]
    marked["dev"] = marked["residual"] / marked["norm_median"] * 100
    bar = np.maximum(marked["norm_median"] * PRACTICAL_DAILY_PCT / 100.0, PRACTICAL_DAILY_ABS)
    drop = (marked["z"] <= DROUGHT_Z) & (marked["residual"] <= -bar)
    surge = (marked["z"] >= SURGE_Z) & (marked["residual"] >= bar)
    tz = days["ts"].dt.tz
    marked = marked[drop | surge]
    for row in marked.itertuples():
        surge_flag = row.z >= SURGE_Z
        day_ts = row.date_ts.tz_localize(tz)
        score = min(abs(row.z), 9.9)
        verb = "выше" if surge_flag else "ниже"
        found.append(
            anomaly(
                sensor_id,
                day_ts,
                day_ts + pd.Timedelta(days=1),
                "traffic",
                "volume_spike" if surge_flag else "volume_drop",
                "amplitude",
                level_from_score(score),
                "volume",
                float(row.volume),
                float(row.norm_median),
                row.dev,
                score,
                f"Суточный трафик {int(row.volume)} авт. {verb} нормы {int(row.norm_median)} "
                f"на {abs(row.dev):.0f}% (z = {row.z:.1f})",
            )
        )
    return found


def _congestion(
    work: pd.DataFrame, sensor_id: str, speed_metric: str, load_metric: str, where: str
) -> list[dict]:
    """Runs of slow daytime hours that the same record's lane occupancy confirms."""
    found: list[dict] = []
    day = work[(work["hour"] >= 7) & (work["hour"] <= 21)]
    slow = (day[speed_metric] < CONGESTION_SPEED) & (day[load_metric] > CONGESTION_LOAD)
    slow &= day[speed_metric].notna() & day[load_metric].notna()
    flagged = day[slow].sort_values("ts")
    run_id = (flagged["ts"].diff() != pd.Timedelta(hours=1)).cumsum()
    for _, run in flagged.groupby(run_id):
        if len(run) < CONGESTION_MIN_HOURS:
            continue
        start, end = run["ts"].iloc[0], run["ts"].iloc[-1] + pd.Timedelta(hours=1)
        min_row = run.loc[run[speed_metric].idxmin()]
        load = float(run[load_metric].max())
        speed = float(min_row[speed_metric])
        dev = (speed - FREE_FLOW_SPEED) / FREE_FLOW_SPEED * 100
        found.append(
            anomaly(
                sensor_id,
                start,
                end,
                "traffic",
                "congestion",
                "speed_load",
                level_from_score(SCORE_CONGESTION),
                speed_metric,
                speed,
                FREE_FLOW_SPEED,
                dev,
                SCORE_CONGESTION,
                f"Со {start:%H:%M} несколько часов подряд скорость {where} ниже "
                f"{speed:.0f} км/ч при загрузке {load:.0f}%",
            )
        )
    return found


def _profiles(days: pd.DataFrame, sensor_id: str) -> list[dict]:
    """Days whose whole hourly shape is unlike the sliding norm of its kind.

    The norm curve of a date is the sliding same-weekday median of every hour (built
    from clean complete days only); a day correlates badly with it when the traffic
    moved to other hours - an early queue, a day that ran backwards - even when its
    totals stayed inside the band the daily detector watches."""
    found: list[dict] = []
    if days.empty:
        return found
    norms = _norms_for(days, "volume", FLOOR_VOLUME_HOUR)
    if norms.empty:
        return found
    per_day = days.groupby("date_ts")["volume"].sum()
    for day_ts, day_df in days.groupby("date_ts"):
        if len(day_df) < 24 or float(per_day.get(day_ts, 0.0)) <= PROFILE_MIN_DAY_VOLUME:
            continue
        profile = day_df.set_index("hour")["volume"].sort_index()
        if float(profile.std()) <= 0:
            continue
        day_norms = norms[norms["date_ts"] == day_ts].set_index("hour")["median"].sort_index()
        if len(day_norms) < 24 or day_norms.isna().any():
            continue
        corr = float(np.corrcoef(day_norms.to_numpy(), profile.to_numpy())[0, 1])
        if corr >= PROFILE_CORR:
            continue
        day_start = day_ts.tz_localize(days["ts"].dt.tz)
        found.append(
            anomaly(
                sensor_id,
                day_start,
                day_start + pd.Timedelta(days=1),
                "traffic",
                "profile_shift",
                "profile",
                level_from_score(SCORE_PROFILE),
                "volume",
                float(profile.sum()),
                float(day_norms.sum()),
                (float(profile.sum()) - float(day_norms.sum())) / float(day_norms.sum()) * 100,
                SCORE_PROFILE,
                "Форма суточного хода нетипична "
                f"(корреляция с нормой {corr:.2f} < {PROFILE_CORR:.2f})",
            )
        )
    return found


def _regime_changes(days: pd.DataFrame, sensor_id: str) -> list[dict]:
    """Sustained one-sided shifts of daily volume (dilczech's detect_regime_changes).

    The amplitude detectors compare a day with a sliding norm that contains the recent
    weeks, so a new steady level absorbs itself: after a couple of months everything is
    normal again and the change is never told. Here the norm is FROZEN: for a window of
    REGIME_MIN_DAYS consecutive complete days the norm of every day is the median of
    the same weekday (holiday kind apart) strictly before the window (within
    REGIME_LOOKBACK_DAYS, at least REGIME_MIN_REFS of them). The window fires when
    every day lies below 0.75 (or above 1.25) of its frozen norm; overlapping
    follow-on windows are skipped, so one report per regime window. This is also the
    module's honest "sustained shift" teller: on this road it is the tool that would
    tell a construction-season level change from seasonal noise."""
    found: list[dict] = []
    if days.empty:
        return found
    tz = days["ts"].iloc[0].tzinfo
    daily = days.groupby("date")["volume"].sum()
    daily.index = pd.DatetimeIndex(pd.to_datetime(daily.index))
    daily = daily.sort_index()
    groups = pd.Series([day_group(ts) for ts in daily.index], index=daily.index)
    last_end: pd.Timestamp | None = None
    for first in daily.index:
        if last_end is not None and first <= last_end:
            continue
        window = pd.DatetimeIndex([first + pd.Timedelta(days=k) for k in range(REGIME_MIN_DAYS)])
        if not window.isin(daily.index).all():  # a window day missing from the export
            continue
        window_groups = groups.loc[window]
        before = daily[
            (daily.index < first) & (daily.index >= first - pd.Timedelta(days=REGIME_LOOKBACK_DAYS))
        ]
        ref_groups = groups.loc[before.index]
        norms: dict[str, float] = {}
        skip = False
        for group in window_groups.unique():
            refs = before[ref_groups == group]
            if len(refs) < REGIME_MIN_REFS:
                skip = True
                break
            median = float(refs.median())
            if not (median > 0):
                skip = True
                break
            norms[group] = median
        if skip:
            continue
        norm_series = window_groups.map(norms)
        ratios = daily.loc[window].to_numpy() / norm_series.to_numpy()
        drop, spike = bool((ratios < REGIME_RATIO_LO).all()), bool((ratios > REGIME_RATIO_HI).all())
        if not (drop or spike):
            continue
        last_end = window[-1]
        mean_volume = float(daily.loc[window].mean())
        mean_norm = float(norm_series.mean())
        dev = (mean_volume - mean_norm) / mean_norm * 100
        score = min(SCORE_REGIME_BASE + (abs(dev) - 25.0) * 0.1, SCORE_REGIME_CAP)
        type_ = "volume_spike" if spike else "volume_drop"
        start = first.tz_localize(tz)
        found.append(
            anomaly(
                sensor_id,
                start,
                (window[-1] + pd.Timedelta(days=1)).tz_localize(tz),  # half-open: +24 h
                "traffic",
                type_,
                "regime",
                level_from_score(score),
                "volume",
                mean_volume,
                mean_norm,
                dev,
                score,
                f"Поток держится {'выше' if spike else 'ниже'} прежней нормы на "
                f"{abs(dev):.0f}% {REGIME_MIN_DAYS} дней подряд (с {first:%d.%m})",
            )
        )
    return found


def _promote(item: dict, other_channel: str) -> None:
    """One confirmation bonus per finding, never past the top of the band."""
    if PROMOTION_NOTE in (item["description"] or "") or item["score"] >= PROMOTE_CAP:
        return
    item["score"] = round(min(item["score"] + PROMOTE_STEP, PROMOTE_CAP), 1)
    item["level"] = level_from_score(item["score"])
    item["description"] += f" Находка подтверждена вторым каналом ({other_channel})."


def promote_correlated(anomalies: list[dict]) -> list[dict]:
    """Volume and speed findings of one sensor that overlap in time confirm each
    other (dilczech's promotion): each side of a confirmed pair gets its score up by
    PROMOTE_STEP (capped at PROMOTE_CAP, level recomputed through the one contract
    table) and a sentence in the description. A finding is promoted at most once -
    the marker sentence shows it - and findings already at or above the cap of 6.5
    are left alone."""
    traffic = [a for a in anomalies if a["category"] == "traffic" and a["score"] is not None]
    volume = [a for a in traffic if a["metric"] in VOLUME_METRICS]
    speed = [a for a in traffic if a["metric"] in SPEED_METRICS]
    for v in volume:
        for s in speed:
            if v["sensor_id"] != s["sensor_id"]:
                continue
            if pd.Timestamp(v["starts_at"]) < pd.Timestamp(s["ends_at"]) and pd.Timestamp(
                s["starts_at"]
            ) < pd.Timestamp(v["ends_at"]):
                _promote(v, "скорость")
                _promote(s, "поток")
    return anomalies


def detect_traffic(filled: pd.DataFrame, sensor_ids: dict[str, str]) -> list[dict]:
    """Traffic detectors on the gap-filled series.

    Hourly detectors only look at real hours; day-shape, daily-sum and regime
    detectors use whole days without a single imputed hour, so a technical hole
    (issue #36) is never counted twice - once as sensor work, once as traffic.
    """
    found: list[dict] = []
    work = _working_frame(filled)
    hours = work[~work["hour_imputed"]]
    days = work[~work["day_imputed"]]
    for section, sec_df in hours.groupby("section"):
        sensors_id = sensor_ids[section]
        found += _hourly_amp(sec_df, sensors_id, "volume", "volume_drop", "volume_spike", "Поток")
        found += _hourly_amp(
            sec_df,
            sensors_id,
            "volume_direct",
            "volume_drop",
            "volume_spike",
            WORDS["volume_direct"],
        )
        found += _hourly_amp(
            sec_df,
            sensors_id,
            "volume_reverse",
            "volume_drop",
            "volume_spike",
            WORDS["volume_reverse"],
        )
        found += _speed_drop(
            sec_df, sensors_id, "speed_direct", "volume_direct", WORDS["speed_direct"]
        )
        found += _speed_drop(
            sec_df, sensors_id, "speed_reverse", "volume_reverse", WORDS["speed_reverse"]
        )
        found += _congestion(
            sec_df, sensors_id, "speed_direct", "load_direct", WORDS["speed_direct"]
        )
        found += _congestion(
            sec_df, sensors_id, "speed_reverse", "load_reverse", WORDS["speed_reverse"]
        )
    for section, sec_df in days.groupby("section"):
        sensor_id = sensor_ids[section]
        found += _daily_amp(sec_df, sensor_id)
        found += _profiles(sec_df, sensor_id)
        found += _regime_changes(sec_df, sensor_id)
    return found


def detect_monthly(filled: pd.DataFrame, sensor_ids: dict[str, str]) -> list[dict]:
    """Year-over-year monthly detectors (issue #37): a month is judged against the
    same calendar month of the other years, among months that are at least
    MONTH_VALIDITY % real on both sides of the comparison; scores are fixed rule
    weights (see the README), levels come from the contract table like everywhere else.

    Three years of export are what makes this pass possible on this road (R-298 had to
    skip it): nearly every calendar month has one or two other-year peers of the same
    sensor to stand next to. A month with a hole in it enters neither the comparison
    nor its peer norm, and the compared month is never its own peer.
    """
    found: list[dict] = []
    work = filled.copy()
    work["month_key"] = work["ts"].dt.tz_localize(None).dt.to_period("M")
    work["heavy"] = work["large_trucks"].fillna(0) + work["road_trains"].fillna(0)
    work["lost"] = work["imputation_method"].ne("")

    for section, sec_df in work.groupby("section"):
        sensor_id = sensor_ids[section]
        stats = []
        for month_key, month_df in sec_df.groupby("month_key"):
            daily = month_df[~month_df["lost"]].groupby(month_df["ts"].dt.date)["volume"].sum()
            volume = month_df[~month_df["lost"]]["volume"].sum()
            real_hours = month_df[~month_df["lost"]]
            # the month's speed is the flow-weighted mean (dilczech): a half-empty
            # night hour must not outvote a full evening hour the way a plain mean
            # lets it, and hours whose direction counted nothing carry no speed
            moving = real_hours[
                real_hours["speed_direct"].notna() & (real_hours["volume_direct"] > 0)
            ]
            speed = (
                float(
                    (moving["speed_direct"] * moving["volume_direct"]).sum()
                    / moving["volume_direct"].sum()
                )
                if len(moving) > 0
                else np.nan
            )
            stats.append(
                {
                    "month_key": month_key,
                    "completeness": (1 - month_df["lost"].mean()) * 100,
                    "madt": float(daily.mean()) if len(daily) > 0 else np.nan,
                    "speed": speed,
                    "load": real_hours["load_direct"].median(),
                    "heavy_share": month_df["heavy"].sum() / volume * 100 if volume > 0 else np.nan,
                }
            )
        stats_df = pd.DataFrame(stats).sort_values("month_key")
        stats_df["cal_month"] = [p.month for p in stats_df["month_key"]]

        for _cal_month, group in stats_df.groupby("cal_month"):
            usable = group[group["completeness"] >= MONTH_VALIDITY]
            for row in group.itertuples():
                start = row.month_key.start_time.tz_localize(filled["ts"].dt.tz)
                end = (row.month_key + 1).start_time.tz_localize(filled["ts"].dt.tz)

                if row.completeness < MONTH_COMPLETENESS:
                    found.append(
                        anomaly(
                            sensor_id,
                            start,
                            end,
                            "technical",
                            "missing_hours",
                            "integrity",
                            level_from_score(SCORE_MONTH_INTEGRITY),
                            "volume",
                            row.completeness,
                            95.0,
                            row.completeness - 100.0,
                            SCORE_MONTH_INTEGRITY,
                            f"Данные за месяц неполные "
                            f"(сохранено лишь {row.completeness:.0f}% часов)",
                        )
                    )
                    # the month belongs to the technical story; its year-over-year
                    # comparisons would only re-tell the missing hours as traffic
                    continue
                if row.completeness < MONTH_VALIDITY:
                    continue

                peers = usable[usable["month_key"] != row.month_key]
                if peers.empty:
                    continue
                med_madt = float(peers["madt"].dropna().median())
                med_speed = float(peers["speed"].dropna().median())
                med_load = float(peers["load"].dropna().median())
                med_heavy = float(peers["heavy_share"].dropna().median())

                if pd.notna(row.madt) and med_madt > 0:
                    dev = (row.madt - med_madt) / med_madt * 100
                    if abs(dev) >= YOY_MADT_PCT:
                        surge = dev > 0
                        score = min(SCORE_YOY_MADT_BASE + (abs(dev) - YOY_MADT_PCT) * 0.1, 6.5)
                        found.append(
                            anomaly(
                                sensor_id,
                                start,
                                end,
                                "traffic",
                                "volume_spike" if surge else "volume_drop",
                                "yoy",
                                level_from_score(score),
                                "volume",
                                row.madt,
                                float(med_madt),
                                dev,
                                score,
                                f"Среднесуточная интенсивность месяца {int(row.madt)} авт. "
                                f"отклонилась на {dev:+.1f}% от нормы {int(med_madt)} "
                                "для этого месяца по другим годам",
                            )
                        )

                if pd.notna(row.heavy_share) and pd.notna(med_heavy):
                    delta_points = row.heavy_share - med_heavy
                    if abs(delta_points) >= YOY_MIX_PP:
                        score = min(SCORE_MIX_BASE + (abs(delta_points) - YOY_MIX_PP) * 0.1, 3.5)
                        dev = delta_points / med_heavy * 100 if med_heavy > 0 else None
                        found.append(
                            anomaly(
                                sensor_id,
                                start,
                                end,
                                "traffic",
                                "vehicle_mix_shift",
                                "mix",
                                level_from_score(score),
                                "large_trucks",
                                row.heavy_share,
                                float(med_heavy),
                                dev,
                                score,
                                f"Доля тяжёлых грузовиков {row.heavy_share:.1f}% против "
                                f"нормы {med_heavy:.1f}% для этого месяца "
                                f"({delta_points:+.1f} п.п.)",
                            )
                        )

                if pd.notna(row.speed) and pd.notna(med_speed):
                    delta_speed = row.speed - med_speed
                    if delta_speed <= -YOY_SPEED:
                        score = min(
                            SCORE_YOY_SPEED_BASE + (abs(delta_speed) - YOY_SPEED) * 0.1, 5.0
                        )
                        found.append(
                            anomaly(
                                sensor_id,
                                start,
                                end,
                                "traffic",
                                "speed_drop",
                                "yoy",
                                level_from_score(score),
                                "speed_direct",
                                row.speed,
                                float(med_speed),
                                delta_speed / med_speed * 100 if med_speed > 0 else None,
                                score,
                                f"Средняя скорость за месяц {row.speed:.0f} км/ч, "
                                f"на {abs(delta_speed):.1f} км/ч ниже нормы для этого месяца",
                            )
                        )

                # ODM 218.2.020-2012 splits service levels by lane occupancy, so the
                # monthly median occupancy is a level, not a rate: its drift from the
                # same calendar month of the other years says the month served worse
                # (or better) than usual even when volumes stayed inside their band.
                if pd.notna(row.load) and pd.notna(med_load) and med_load > 0:
                    dev = (row.load - med_load) / med_load * 100
                    if abs(dev) >= YOY_LOAD_PCT:
                        score = min(SCORE_LOAD_BASE + (abs(dev) - YOY_LOAD_PCT) * 0.08, 4.5)
                        found.append(
                            anomaly(
                                sensor_id,
                                start,
                                end,
                                "traffic",
                                "level_of_service_shift",
                                "load",
                                level_from_score(score),
                                "load_direct",
                                row.load,
                                float(med_load),
                                dev,
                                score,
                                f"Медианная загрузка полосы за месяц {row.load:.1f}% "
                                f"против нормы {med_load:.1f}% для этого месяца ({dev:+.0f}%)",
                            )
                        )

    return found


def finalize(found: list[dict]) -> list[dict]:
    """Give every finding its id and mega flag (mega: traffic and |deviation| >= 60)."""
    used: dict[str, int] = {}
    for item in found:
        stamp = item["starts_at"][:10].replace("-", "")
        base = f"{ROAD}-{item['type'].replace('_', '-')}-{stamp}"
        used[base] = used.get(base, 0) + 1
        item["id"] = f"{base}-{used[base]:02d}"
        if (
            item["category"] == "traffic"
            and item["deviation_pct"] is not None
            and abs(item["deviation_pct"]) >= MEGA_PCT
        ):
            item["is_mega"] = True
    return sorted(found, key=lambda a: (a["sensor_id"], a["starts_at"], a["type"], a["detector"]))
