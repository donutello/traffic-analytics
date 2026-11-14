"""Anomaly detectors for A-133, working on the gap-filled hourly table.

Every detector compares an hour or a day with the normal value for the same hour on
the same kind of day (weekday / weekend / holiday, see holidays.py), and every finding
comes out as a contract anomaly (English codes, a Russian `description` for the
dashboard). `level` is never chosen by hand: `level_from_score` buckets the score the
way contract v1 orders it. The thresholds themselves, with one-line reasons, are in the
module README, settled in issues #18/#19.

The detectors skip hours marked `imputation_method` - those belong to the technical
story (issue #18) and must not pollute the traffic one.
"""

import numpy as np
import pandas as pd

from .holidays import day_kind
from .parse import ROAD

# Detection thresholds, settled in issue #19 and re-settled with the smarter ports
# (see the README credit section); the README explains each one.
HOURLY_Z = 3.0  # an hour is off when the robust z and the practical magnitude agree
HOURLY_MIN_RUN = 4  # hours of the same direction (drop or spike) to report one
PRACTICAL_HOUR_PCT, PRACTICAL_HOUR_ABS = 35.0, 50.0  # hourly volume: the deviation in
PRACTICAL_DAILY_PCT, PRACTICAL_DAILY_ABS = 25.0, 100.0  # % of norm AND cars must reach
DROUGHT_Z, SURGE_Z = -3.0, 3.0  # daily volume vs the norm of the month and kind
SPEED_DROP_KMH = 15.0  # км/ч a direction's speed must fall under its hour norm
SPEED_DROP_Z = 3.0  # ... and the robust z must agree (the %-based pass of #19 is gone)
SPEED_DROP_MIN_RUN = 4  # hours in a row; a day that is only briefly slow is weather noise
MAD_TO_SIGMA = 1.4826  # MAD to sigma for a normal distribution (modified z-score)
RELATIVE_FLOOR = 0.10  # sigma is never below 10 % of the norm...
FLOOR_VOLUME_HOUR = 20.0  # ... and never below these absolute floors: авт./ч hours,
FLOOR_VOLUME_DAY = 100.0  # авт./сутки days, км/ч speed, % load (dilczech floors)
FLOOR_SPEED, FLOOR_LOAD = 3.0, 2.0
CONGESTION_SPEED = 50.0  # км/ч, below which the approach to Lipetsk counts as congested
CONGESTION_LOAD = 20.0  # %, lane occupancy confirming the congestion
CONGESTION_MIN_HOURS = 2  # single slow hours are measurement noise, a queue is a run
FREE_FLOW_SPEED = 80.0  # км/ч free flow on this approach: the `expected` for congestion
PROFILE_CORR = 0.70  # day profile below this correlation with the norm: distorted
PROFILE_MIN_DAY_VOLUME = 800  # a thin day correlates badly by noise alone (two-lane road)
MONTH_COMPLETENESS = 75.0  # % of hours present, below which the whole month is suspect
YOY_MADT_PCT = 25.0  # % the monthly average daily volume may deviate from its norm
YOY_MIX_PP = 8.0  # percentage points the heavy-truck share may change
YOY_SPEED = 15.0  # км/ч the mean monthly speed may drop
LOAD_DEV_PCT = 20.0  # % the monthly median occupancy may drift from its calendar norm
MONTH_VALIDITY = 95.0  # % real hours a month needs to be compared year over year at all
MEGA_PCT = 60.0  # |deviation| of a traffic anomaly from which it is highlighted (FR3)

SHARE_DEV_PP = 25.0  # п.п. the direct-share of the day-kind norm the flow may tip by
SHARE_MIN_RUN = 4  # hours in a row of the same tip before it is one finding
SHARE_MIN_VOLUME = 60  # hour volume under which a share of a handful of cars is noise

REGIME_MIN_DAYS = 7  # consecutive complete days one side of the frozen norm (dilczech)
REGIME_LOOKBACK_DAYS = 168  # how far back the frozen norm may reach
REGIME_MIN_REFS = 6  # same-kind days the frozen norm needs
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
SCORE_SHARE_BASE = 2.5  # a 25 п.п. one-sided tip of the direction mix starts at medium


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


def _center_and_mad(values: pd.Series) -> tuple[float, float]:
    """Median and MAD of one group of values; MAD 0 everywhere gives MAD 0, the floor
    (never a collapse to a hair-width sigma) is what keeps quiet hours quiet."""
    median = float(values.median())
    if np.isnan(median):
        return np.nan, 0.0
    mad = float((values - median).abs().median())
    if not (mad > 0) or np.isnan(mad):
        mad = 0.0
    return median, mad


def _sigma(median: float, mad: float, floor: float) -> float:
    """The floored robust scale of dilczech's baseline: sigma = max(1.4826*MAD,
    10 % of the norm, floor). The z thresholds of #19 keep their meaning on it."""
    return max(MAD_TO_SIGMA * mad, abs(median) * RELATIVE_FLOOR, floor)


def _floor_for(metric: str) -> float:
    if metric.startswith("speed"):
        return FLOOR_SPEED
    if metric.startswith("load"):
        return FLOOR_LOAD
    return FLOOR_VOLUME_HOUR


def _kind_and_month(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["date"] = work["ts"].dt.date
    work["hour"] = work["ts"].dt.hour
    work["day_type"] = [day_kind(ts) for ts in work["ts"]]
    # the calendar month pooled over all years: a stormy December stays a minority of
    # its own norm instead of dragging that norm down with it
    work["month"] = work["ts"].dt.month
    work["hour_imputed"] = work["imputation_method"].ne("")
    work["day_imputed"] = work.groupby(["section", "date"])["hour_imputed"].transform("any")
    return work


def _hourly_detector(
    work: pd.DataFrame, sensor_id: str, metric: str, low_type: str, high_type: str, noun: str
) -> list[dict]:
    """Hours versus the same hour of the same kind of days: runs of deviant hours.

    A daily sum hides an accident: twelve hours cut in half still leave a day that
    looks normal. So every hour is compared with the median of the very same hour on
    the same kind of days of the same calendar month (pooled over the years), and an
    hour counts as deviant only when BOTH the modified z against the floored robust
    scale and the practical magnitude test pass: |actual - norm| must reach
    max(35 % of the norm, 50 авт./ч) (dilczech's AND, which replaces the old flat
    25 % rule - night hours stopped firing on wobbles of a few cars). >= HOURLY_MIN_RUN
    deviant hours in a row become one anomaly with the exact interval. Runs over the
    total volume and over each direction separately.
    """
    found: list[dict] = []
    floor = _floor_for(metric)
    for (_month, _kind), group in work.groupby(["month", "day_type"]):
        if len(group["date"].unique()) < 4:
            continue
        stats = pd.DataFrame(
            {hour: _center_and_mad(values) for hour, values in group.groupby("hour")[metric]},
            index=["median", "mad"],
        ).T
        stats["sigma"] = [
            _sigma(median, mad, floor)
            for median, mad in zip(stats["median"], stats["mad"], strict=True)
        ]
        stats = stats[stats["median"].notna()]
        if stats.empty:
            continue

        marked = group.copy()
        med = marked["hour"].map(stats["median"])
        sigma = marked["hour"].map(stats["sigma"])
        marked = marked[med.notna() & sigma.notna()]
        med, sigma = marked["hour"].map(stats["median"]), marked["hour"].map(stats["sigma"])
        marked["z"] = (marked[metric] - med) / sigma
        marked["residual"] = marked[metric] - med
        marked["dev"] = np.where(med > 0, marked["residual"] / med * 100, 0.0)
        bar = np.maximum(np.abs(med) * PRACTICAL_HOUR_PCT / 100.0, PRACTICAL_HOUR_ABS)
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
                expected = float(run["hour"].map(stats["median"]).mean())
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


def _speed_drop_runs(
    work: pd.DataFrame, sensor_id: str, speed_metric: str, volume_metric: str, where: str
) -> list[dict]:
    """One direction's speed against its own hour norm, measured in км/ч (dilczech).

    The old %-based speed pass is gone. Norms are built only from hours where this
    direction really counted cars (an empty hour logs a meaningless speed), and an
    hour is flagged only when its own direction is moving too, the speed lies at
    SPEED_DROP_KMH км/ч or more under the norm, and the robust z agrees. >=
    SPEED_DROP_MIN_RUN such hours in a row become one anomaly.
    """
    found: list[dict] = []
    for (_month, _kind), group in work.groupby(["month", "day_type"]):
        reference = group[group[volume_metric] > 0]
        if reference["date"].nunique() < 4:
            continue
        stats = pd.DataFrame(
            {
                hour: _center_and_mad(values)
                for hour, values in reference.groupby("hour")[speed_metric]
            },
            index=["median", "mad"],
        ).T
        stats["sigma"] = [
            _sigma(median, mad, FLOOR_SPEED)
            for median, mad in zip(stats["median"], stats["mad"], strict=True)
        ]
        stats = stats[stats["median"].notna()]
        if stats.empty:
            continue

        marked = group[group[volume_metric] > 0].copy()
        med = marked["hour"].map(stats["median"])
        sigma = marked["hour"].map(stats["sigma"])
        marked = marked[med.notna() & sigma.notna()]
        med, sigma = marked["hour"].map(stats["median"]), marked["hour"].map(stats["sigma"])
        marked["gap"] = marked[speed_metric] - med
        marked["z"] = marked["gap"] / sigma
        flagged = marked[(marked["gap"] <= -SPEED_DROP_KMH) & (marked["z"] <= -SPEED_DROP_Z)]
        flagged = flagged.sort_values("ts")
        if flagged.empty:
            continue
        gaps = flagged["ts"].diff() != pd.Timedelta(hours=1)
        for _, run in flagged.groupby(gaps.cumsum()):
            if len(run) < SPEED_DROP_MIN_RUN:
                continue
            start, end = run["ts"].iloc[0], run["ts"].iloc[-1] + pd.Timedelta(hours=1)
            actual = float(run[speed_metric].mean())
            expected = float(run["hour"].map(stats["median"]).mean())
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


def _share_imbalance(work: pd.DataFrame, sensor_id: str) -> list[dict]:
    """The two directions tipping out of their usual split (baseline-relative).

    Two-lane approaches breathe unevenly: mornings one way, evenings the other, Friday
    evenings strongly one way. What is news is a stretch that tips against the norm of
    the very same hour on the very same kind of day: an accident with a lane blocked, a
    detour, or one loop starting to under-read. Every hour's direct share is compared
    with the same-kind hour-share norm, and >= SHARE_MIN_RUN hours running >=
    SHARE_DEV_PP п.п. to one side make one finding. Quiet hours (under
    SHARE_MIN_VOLUME cars) say nothing about a share and are skipped.
    """
    found: list[dict] = []
    busy = work[(work["volume_direct"] + work["volume_reverse"]) >= SHARE_MIN_VOLUME].copy()
    if busy.empty:
        return found
    busy["share"] = busy["volume_direct"] / (busy["volume_direct"] + busy["volume_reverse"])
    for (_month, _kind), group in busy.groupby(["month", "day_type"]):
        if group["date"].nunique() < 4:
            continue
        norm = group.groupby("hour")["share"].median()
        med = group["hour"].map(norm)
        marked = group[med.notna()].copy()
        share_norm = marked["hour"].map(norm)
        marked["tip_pp"] = (marked["share"] - share_norm) * 100
        flagged = marked[marked["tip_pp"].abs() >= SHARE_DEV_PP].sort_values("ts")
        if flagged.empty:
            continue
        gaps = flagged["ts"].diff() != pd.Timedelta(hours=1)
        for _, run in flagged.groupby(gaps.cumsum()):
            if len(run) < SHARE_MIN_RUN or not np.all(
                np.sign(run["tip_pp"]) == np.sign(run["tip_pp"].iloc[0])
            ):
                continue
            start, end = run["ts"].iloc[0], run["ts"].iloc[-1] + pd.Timedelta(hours=1)
            side = "прямого" if run["tip_pp"].iloc[0] > 0 else "обратного"
            tip = float(run["tip_pp"].mean())
            actual = float(run["share"].mean() * 100)
            expected = float(run["hour"].map(norm).mean() * 100)
            score = min(SCORE_SHARE_BASE + (abs(tip) - SHARE_DEV_PP) * 0.06, 4.0)
            found.append(
                anomaly(
                    sensor_id,
                    start,
                    end,
                    "traffic",
                    "direction_imbalance",
                    "direction",
                    level_from_score(score),
                    "direction_share",
                    actual,
                    expected,
                    None,
                    score,
                    f"Поток {len(run)} часов подряд на {abs(tip):.0f} п.п. "
                    f"перекосился в {side} сторону: доля прямого направления "
                    f"{actual:.0f}% против обычного {expected:.0f}%",
                )
            )
    return found


def _daily_amplitude(work: pd.DataFrame, sensor_id: str) -> list[dict]:
    """Whole days versus the median of the same calendar month and kind of day.

    The old rule's ±50 %-alone trigger (a flat percent with no reference to any
    scale) is replaced by the practical-magnitude AND, as in the hourly pass: z and
    a deviation of max(25 % of the norm, 100 авт./сутки) must agree. The floored
    scale is now what keeps a calm month's tight MAD from inflating z, not the
    percent rule."""
    found: list[dict] = []
    daily = work.groupby(["month", "day_type", "date"])["volume"].sum().reset_index()
    for (_month, _kind), group in daily.groupby(["month", "day_type"]):
        if len(group) < 4:
            continue
        median, mad = _center_and_mad(group["volume"])
        if np.isnan(median):
            continue
        sigma = _sigma(median, mad, FLOOR_VOLUME_DAY)
        bar = max(abs(median) * PRACTICAL_DAILY_PCT / 100.0, PRACTICAL_DAILY_ABS)
        for day, volume in zip(group["date"], group["volume"], strict=True):
            residual = volume - median
            z = residual / sigma
            dev = residual / median * 100 if median > 0 else 0.0
            day_ts = pd.Timestamp(day, tz=work["ts"].iloc[0].tzinfo)
            drop = z <= DROUGHT_Z and residual <= -bar
            surge = z >= SURGE_Z and residual >= bar
            if not (drop or surge):
                continue
            type_ = "volume_spike" if surge else "volume_drop"
            verb = "выше" if surge else "ниже"
            score = min(abs(z), 9.9)
            found.append(
                anomaly(
                    sensor_id,
                    day_ts,
                    day_ts + pd.Timedelta(days=1),
                    "traffic",
                    type_,
                    "amplitude",
                    level_from_score(score),
                    "volume",
                    float(volume),
                    median,
                    dev,
                    score,
                    f"Суточный трафик {int(volume)} авт. {verb} нормы {int(median)} "
                    f"на {abs(dev):.0f}% (z = {z:.1f})",
                )
            )
    return found


def _congestion(work: pd.DataFrame, sensor_id: str) -> list[dict]:
    """Runs of slow daytime hours that the lane occupancy confirms as a queue."""
    found: list[dict] = []
    day = work[(work["hour"] >= 7) & (work["hour"] <= 21)]
    slow = (day["speed_direct"] < CONGESTION_SPEED) & (day["load_direct"] > CONGESTION_LOAD)
    slow &= day["speed_direct"].notna() & day["load_direct"].notna()
    flagged = day[slow].sort_values("ts")
    run_id = (flagged["ts"].diff() != pd.Timedelta(hours=1)).cumsum()
    for _, run in flagged.groupby(run_id):
        if len(run) < CONGESTION_MIN_HOURS:
            continue
        start, end = run["ts"].iloc[0], run["ts"].iloc[-1] + pd.Timedelta(hours=1)
        min_row = run.loc[run["speed_direct"].idxmin()]
        load = float(run["load_direct"].max())
        speed = float(min_row["speed_direct"])
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
                "speed_direct",
                speed,
                FREE_FLOW_SPEED,
                dev,
                SCORE_CONGESTION,
                f"Со {start:%H:%M} несколько часов подряд скорость ниже "
                f"{min_row['speed_direct']:.0f} км/ч при загрузке {load:.0f}%",
            )
        )
    return found


def _profiles(work: pd.DataFrame, sensor_id: str) -> list[dict]:
    """Days whose whole hourly shape is unlike the norm of its kind of days."""
    found: list[dict] = []
    for (_month, _kind), group in work.groupby(["month", "day_type"]):
        complete = group.groupby("date").size()
        full_days = set(complete[complete == 24].index)
        norm = group[group["date"].isin(full_days)].groupby("hour")["volume"].median()
        if norm.isna().any() or float(norm.std()) <= 0:
            continue
        for day, day_df in group.groupby("date"):
            if day not in full_days or len(day_df) < 24:
                continue
            profile = day_df.set_index("hour")["volume"].sort_index()
            if float(profile.std()) <= 0 or float(profile.sum()) <= PROFILE_MIN_DAY_VOLUME:
                continue
            corr = float(np.corrcoef(norm.values, profile.reindex(norm.index).values)[0, 1])
            if corr >= PROFILE_CORR:
                continue
            day_ts = pd.Timestamp(day, tz=work["ts"].iloc[0].tzinfo)
            found.append(
                anomaly(
                    sensor_id,
                    day_ts,
                    day_ts + pd.Timedelta(days=1),
                    "traffic",
                    "profile_shift",
                    "profile",
                    level_from_score(SCORE_PROFILE),
                    "volume",
                    float(profile.sum()),
                    float(norm.sum()),
                    (float(profile.sum()) - float(norm.sum())) / float(norm.sum()) * 100,
                    SCORE_PROFILE,
                    "Форма суточного хода нетипична "
                    f"(корреляция с нормой {corr:.2f} < {PROFILE_CORR:.2f})",
                )
            )
    return found


def _regime_changes(days: pd.DataFrame, sensor_id: str) -> list[dict]:
    """Sustained one-sided shifts of daily volume (dilczech's detect_regime_changes).

    An amplitude detector compares a day with a norm that contains the recent weeks,
    so a new steady level absorbs itself: after a few weeks everything is normal
    again and the change is never told. Here the norm is FROZEN: for a window of
    REGIME_MIN_DAYS consecutive complete days the norm of every day is the median of
    the same-kind days strictly before the window (within REGIME_LOOKBACK_DAYS, at
    least REGIME_MIN_REFS of them). The window fires when every day lies below 0.75
    (or above 1.25) of its frozen norm; overlapping follow-on windows are skipped, so
    one report per regime window. Days and volumes come from complete non-imputed
    days only (the caller filters them)."""
    found: list[dict] = []
    if days.empty:
        return found
    tz = days["ts"].iloc[0].tzinfo
    daily = days.groupby("date")["volume"].sum()
    daily.index = pd.DatetimeIndex(pd.to_datetime(daily.index))
    daily = daily.sort_index()
    kinds = pd.Series([day_kind(ts) for ts in daily.index], index=daily.index)
    last_end: pd.Timestamp | None = None
    for first in daily.index:
        if last_end is not None and first <= last_end:
            continue
        window = pd.DatetimeIndex([first + pd.Timedelta(days=k) for k in range(REGIME_MIN_DAYS)])
        if not window.isin(daily.index).all():  # a window day missing from the export
            continue
        window_kinds = kinds.loc[window]
        before = daily[
            (daily.index < first) & (daily.index >= first - pd.Timedelta(days=REGIME_LOOKBACK_DAYS))
        ]
        ref_kinds = kinds.loc[before.index]
        norms: dict[str, float] = {}
        skip = False
        for kind in window_kinds.unique():
            refs = before[ref_kinds == kind]
            if len(refs) < REGIME_MIN_REFS:
                skip = True
                break
            median, _ = _center_and_mad(refs)
            if not (median > 0):
                skip = True
                break
            norms[kind] = median
        if skip:
            continue
        norm_series = window_kinds.map(norms)
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

    Hourly detectors only look at real hours; day-shape and daily-sum detectors use
    whole days without a single imputed hour, so a technical hole (issue #18) is never
    counted twice - once as sensor work, once as traffic.
    """
    found: list[dict] = []
    work = _kind_and_month(filled)
    hours = work[~work["hour_imputed"]]
    days = work[~work["day_imputed"]]
    for section, sec_df in hours.groupby("section"):
        sensor_id = sensor_ids[section]
        found += _hourly_detector(
            sec_df, sensor_id, "volume", "volume_drop", "volume_spike", "Поток"
        )
        found += _hourly_detector(
            sec_df,
            sensor_id,
            "volume_direct",
            "volume_drop",
            "volume_spike",
            "Поток (на Липецк)",
        )
        found += _hourly_detector(
            sec_df,
            sensor_id,
            "volume_reverse",
            "volume_drop",
            "volume_spike",
            "Поток (из Липецка)",
        )
        found += _speed_drop_runs(sec_df, sensor_id, "speed_direct", "volume_direct", "на Липецк")
        found += _speed_drop_runs(
            sec_df, sensor_id, "speed_reverse", "volume_reverse", "из Липецка"
        )
        found += _share_imbalance(sec_df, sensor_id)
        found += _congestion(sec_df, sensor_id)
    for section, sec_df in days.groupby("section"):
        sensor_id = sensor_ids[section]
        found += _daily_amplitude(sec_df, sensor_id)
        found += _profiles(sec_df, sensor_id)
        found += _regime_changes(sec_df, sensor_id)
    return found


def detect_monthly(filled: pd.DataFrame, sensor_ids: dict[str, str]) -> list[dict]:
    """Year-over-year monthly detectors: a month is judged against the same calendar
    month of the other years, among months that are at least MONTH_VALIDITY % real on
    both sides of the comparison; scores are fixed rule weights (see the README),
    levels come from the contract table like everywhere else."""
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
                    "madt": daily.mean() if len(daily) > 0 else np.nan,
                    "speed": speed,
                    "load": real_hours["load_direct"].median(),
                    "heavy_share": month_df["heavy"].sum() / volume * 100 if volume > 0 else np.nan,
                }
            )
        stats_df = pd.DataFrame(stats)
        stats_df["cal_month"] = [p.month for p in stats_df["month_key"]]

        for _cal_month, group in stats_df.groupby("cal_month"):
            # A month compares year over year only itself valid (dilczech's gate too):
            # months with a hole in them must enter neither the comparison nor its
            # peer norm. The peer median is taken over the OTHER years only - the
            # compared month must not be its own anchor.
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
                                f"отклонилась на {dev:+.1f}% от нормы {int(med_madt)}",
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
                                f"нормы {med_heavy:.1f}% ({delta_points:+.1f} п.п.)",
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
                                f"на {abs(delta_speed):.1f} км/ч ниже нормы",
                            )
                        )

                # ODM 218.2.020-2012 splits service levels by lane occupancy, so the
                # monthly median occupancy is a level, not a rate: its drift from the
                # same calendar month of the other years says the month served worse (or
                # better) than usual even when volumes stayed inside their band.
                if pd.notna(row.load) and pd.notna(med_load) and med_load > 0:
                    dev = (row.load - med_load) / med_load * 100
                    if abs(dev) >= LOAD_DEV_PCT:
                        score = min(SCORE_LOAD_BASE + (abs(dev) - LOAD_DEV_PCT) * 0.08, 4.5)
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
                                f"против нормы {med_load:.1f}% ({dev:+.0f}%)",
                            )
                        )

    return found


MERGE_GAP_HOURS = 12  # episodes of one story this close are one finding, not two
MERGE_TYPES = frozenset({"speed_drop", "volume_drop", "volume_spike", "congestion"})
MERGE_NOUNS = {
    "speed_direct": "Скорость на Липецк",
    "speed_reverse": "Скорость из Липецка",
    "volume": "Поток",
    "volume_direct": "Поток (на Липецк)",
    "volume_reverse": "Поток (из Липецка)",
}


def _merge_group(group: list[dict]) -> list[dict]:
    """Chain episodes of one sensor and metric whose gap is at most MERGE_GAP_HOURS."""
    merged: list[dict] = []
    for item in sorted(group, key=lambda a: a["starts_at"]):
        gap = (
            pd.Timestamp(item["starts_at"]) - pd.Timestamp(merged[-1]["ends_at"])
            if merged
            else None
        )
        if merged is None or not merged or gap > pd.Timedelta(hours=MERGE_GAP_HOURS):
            merged.append(dict(item))
            continue
        last = merged[-1]
        hours_new = (
            pd.Timestamp(item["ends_at"]) - pd.Timestamp(item["starts_at"])
        ).total_seconds() / 3600
        hours_old = (
            pd.Timestamp(last["ends_at"]) - pd.Timestamp(last["starts_at"])
        ).total_seconds() / 3600
        promoted = PROMOTION_NOTE in (last["description"] or "") or PROMOTION_NOTE in (
            item["description"] or ""
        )
        if item["type"] == "congestion":
            actual = min(float(last["actual"]), float(item["actual"]))
        else:
            actual = (last["actual"] * hours_old + item["actual"] * hours_new) / (
                hours_old + hours_new
            )
        last["ends_at"] = item["ends_at"]
        last["actual"] = round(actual, 1)
        if last["expected"] and item["expected"]:
            expected = (last["expected"] * hours_old + item["expected"] * hours_new) / (
                hours_old + hours_new
            )
            last["expected"] = round(expected, 1)
            last["deviation_pct"] = round((actual - expected) / expected * 100, 1)
        last["score"] = max(last["score"], item["score"])
        hours_total = int(
            round(
                (pd.Timestamp(last["ends_at"]) - pd.Timestamp(last["starts_at"])).total_seconds()
                / 3600
            )
        )
        start = pd.Timestamp(last["starts_at"])
        noun = MERGE_NOUNS.get(last["metric"], "Поток")
        if item["type"] == "congestion":
            text = (
                f"Со {start:%d.%m %H:%M} заторы повторяются: скорость ниже "
                f"{actual:.0f} км/ч, суммарно {hours_total} ч"
            )
        elif item["type"] == "speed_drop":
            text = (
                f"{noun} устойчиво ниже нормы на "
                f"{abs(actual - (last['expected'] or 0)):.0f} км/ч "
                f"({hours_total} ч с {start:%d.%m})"
            )
        else:
            verb = "выше" if item["type"] == "volume_spike" else "ниже"
            dev = abs(last["deviation_pct"] or 0)
            text = f"{noun} держится {verb} нормы на {dev:.0f}% ({hours_total} ч)"
        if promoted and PROMOTION_NOTE not in text:
            text += " Находка подтверждена вторым каналом."
        last["description"] = text
    return merged


def _merge_repeated(anomalies: list[dict]) -> list[dict]:
    """One finding per ongoing story (see _merge_group), other findings pass through."""
    traffic, rest = [], []
    for item in anomalies:
        if item["category"] == "traffic" and item["type"] in MERGE_TYPES:
            traffic.append(item)
        else:
            rest.append(item)
    out = rest
    for _key, group in pd.DataFrame(
        [(a["sensor_id"], a["type"], a["metric"], a) for a in traffic],
        columns=["sensor_id", "type", "metric", "item"],
    ).groupby(["sensor_id", "type", "metric"]):
        out += _merge_group(list(group["item"]))
    return out


def finalize(found: list[dict]) -> list[dict]:
    """Merge adjacent episodes of the same story, then give every finding its id and
    mega flag (mega: traffic and |deviation| >= 60)."""
    found = _merge_repeated(found)
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
