"""Anomaly detectors for A-134, working on the gap-filled hourly table.

Every detector compares an hour or a day with the normal value for the same hour on
the same kind of day (weekday / weekend / holiday, see holidays.py), and every finding
comes out as a contract anomaly (English codes, a Russian `description` for the
dashboard). `level` is never chosen by hand: `level_from_score` buckets the score the
way contract v1 orders it. The thresholds themselves, with one-line reasons, are in
the module README, settled in issues #24/#25.

The detectors skip hours marked `imputation_method` - those belong to the technical
story (issue #24) and must not pollute the traffic one.
"""

import numpy as np
import pandas as pd

from .holidays import day_kind
from .parse import ROAD

# Detection thresholds, settled in issue #25; the README explains each one.
HOURLY_Z, HOURLY_PCT = 3.0, 25.0  # an hour is off when modified-z and deviation agree
HOURLY_MIN_RUN = 4  # hours of the same direction (drop or spike) to report one
DROUGHT_Z, DROUGHT_PCT = -3.0, -25.0  # daily volume vs the norm of the month and kind
SURGE_Z, SURGE_PCT = 3.0, 25.0
SPIKE_PCT = 50.0  # these deviations alone are enough, no z-score needed
CONGESTION_SPEED = 50.0  # км/ч, below which the approach to Voronezh counts as congested
CONGESTION_LOAD = 20.0  # %, lane occupancy confirming the congestion
CONGESTION_MIN_HOURS = 2  # single slow hours are measurement noise, a queue is a run
FREE_FLOW_SPEED = 80.0  # км/ч free flow on this approach: the `expected` for congestion
PROFILE_CORR = 0.70  # day profile below this correlation with the norm: distorted
PROFILE_MIN_DAY_VOLUME = 1000  # a thin day correlates badly by noise alone
MONTH_COMPLETENESS = 75.0  # % of hours present, below which the whole month is suspect
YOY_MADT_PCT = 25.0  # % the monthly average daily volume may deviate from its norm
YOY_MIX_PP = 8.0  # percentage points the heavy-truck share may change
YOY_SPEED = 15.0  # км/ч the mean monthly speed may drop
LOAD_DEV_PCT = 20.0  # % the monthly median occupancy may drift from its calendar norm
MEGA_PCT = 60.0  # |deviation| of a traffic anomaly from which it is highlighted (FR3)

SCORE_YOY_MADT_BASE = 3.5  # fixed rule weights for the monthly detectors (see README)
SCORE_YOY_SPEED_BASE = 2.5
SCORE_MIX_BASE = 2.0
SCORE_LOAD_BASE = 2.0
SCORE_MONTH_INTEGRITY = 3.0
SCORE_PROFILE = 2.5
SCORE_CONGESTION = 4.5


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


def _mad(series: pd.Series, fallback: float = 1.0) -> float:
    """Median absolute deviation with the fallbacks of the ported analyzer."""
    median = float(series.median())
    mad = float((series - median).abs().median())
    if not (mad > 0) or np.isnan(mad):
        mad = float(series.std())
    if not (mad > 0) or np.isnan(mad):
        return fallback
    return mad


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
    the same kind of days of the same calendar month (pooled over the years), and
    >= HOURLY_MIN_RUN deviant hours in a row become one anomaly with the exact
    interval. Works for volume and for speed, which is why weather waves show up.
    """
    found: list[dict] = []
    for (_month, _kind), group in work.groupby(["month", "day_type"]):
        if len(group["date"].unique()) < 4:
            continue
        stats = group.groupby("hour")[metric].agg(["median", _mad])
        stats.columns = ["median", "mad"]
        stats = stats[stats["median"].notna()]

        marked = group.copy()
        med = marked["hour"].map(stats["median"])
        mad = marked["hour"].map(stats["mad"])
        marked = marked[med.notna() & (mad > 0)]
        med, mad = marked["hour"].map(stats["median"]), marked["hour"].map(stats["mad"])
        marked["z"] = 0.6745 * (marked[metric] - med) / mad
        marked["dev"] = np.where(med > 0, (marked[metric] - med) / med * 100, 0.0)
        drop = (marked["z"] <= -HOURLY_Z) & (marked["dev"] <= -HOURLY_PCT)
        spike = (marked["z"] >= HOURLY_Z) & (marked["dev"] >= HOURLY_PCT)
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


def _daily_amplitude(work: pd.DataFrame, sensor_id: str) -> list[dict]:
    """Whole days versus the median of the same calendar month and kind of day."""
    found: list[dict] = []
    daily = work.groupby(["month", "day_type", "date"])["volume"].sum().reset_index()
    for (_month, _kind), group in daily.groupby(["month", "day_type"]):
        if len(group) < 4:
            continue
        median = float(group["volume"].median())
        mad = _mad(group["volume"])
        for day, volume in zip(group["date"], group["volume"], strict=True):
            z = 0.6745 * (volume - median) / mad
            dev = (volume - median) / median * 100 if median > 0 else 0.0
            day_ts = pd.Timestamp(day, tz=work["ts"].iloc[0].tzinfo)
            drop = (z < DROUGHT_Z and dev <= DROUGHT_PCT) or dev <= -SPIKE_PCT
            surge = (z > SURGE_Z and dev >= SURGE_PCT) or dev >= SPIKE_PCT
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


def detect_traffic(filled: pd.DataFrame, sensor_ids: dict[str, str]) -> list[dict]:
    """Traffic detectors on the gap-filled series.

    Hourly detectors only look at real hours; day-shape and daily-sum detectors use
    whole days without a single imputed hour, so a technical hole (issue #24) is never
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
            sec_df, sensor_id, "speed_direct", "speed_drop", "speed_spike", "Скорость"
        )
        found += _congestion(sec_df, sensor_id)
    for section, sec_df in days.groupby("section"):
        sensor_id = sensor_ids[section]
        found += _daily_amplitude(sec_df, sensor_id)
        found += _profiles(sec_df, sensor_id)
    return found


def detect_monthly(filled: pd.DataFrame, sensor_ids: dict[str, str]) -> list[dict]:
    """Year-over-year monthly detectors: a month is judged against the same calendar
    month of the other years. Scores are fixed rule weights (see the README), levels
    come from the contract table like everywhere else."""
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
            stats.append(
                {
                    "month_key": month_key,
                    "completeness": (1 - month_df["lost"].mean()) * 100,
                    "madt": daily.mean() if len(daily) > 0 else np.nan,
                    "speed": real_hours["speed_direct"].mean(),
                    "load": real_hours["load_direct"].median(),
                    "heavy_share": month_df["heavy"].sum() / volume * 100 if volume > 0 else np.nan,
                }
            )
        stats_df = pd.DataFrame(stats)
        stats_df["cal_month"] = [p.month for p in stats_df["month_key"]]

        for _cal_month, group in stats_df.groupby("cal_month"):
            if len(group) < 2:
                continue
            med_madt = group["madt"].median()
            med_speed = group["speed"].median()
            med_load = group["load"].median()
            med_heavy = group["heavy_share"].median()

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
