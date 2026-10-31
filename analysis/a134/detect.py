"""Anomaly detectors for A-134, ported from the earlier standalone analyzer.

The detectors work on the parsed hourly table (analysis/a134/parse.py) and return
anomalies by the data contract (`contract/models.py`, Anomaly): English codes, Russian
description for the dashboard. The thresholds are listed, explained and discussed in the
module README; they are settled for good in issue #25.
"""

import numpy as np
import pandas as pd

from .parse import ROAD

# Detection thresholds, carried over from the standalone analyzer (see the README).
FLATLINE_MIN_HOURS = 5  # the same volume > 10 авт./ч for this many hours: a stuck sensor
BALANCE_MIN_DAY_VOLUME = 500  # only judge the direction split on busy days
BALANCE_BAND = (0.15, 0.85)  # share of the direct direction outside this band: suspicious
CONGESTION_SPEED = 50.0  # км/ч, below which the approach to Voronezh counts as congested
CONGESTION_LOAD = 20.0  # %, lane occupancy confirming the congestion
PROFILE_CORR = 0.70  # Pearson correlation of the daily profile with the norm of the month
PROFILE_MIN_DAY_VOLUME = 1000  # only judge the profile on busy days
DROUGHT_Z, DROUGHT_PCT = -3.0, -25.0  # daily volume vs the norm of the month (see README)
SURGE_Z, SURGE_PCT = 3.0, 25.0
SPIKE_PCT = 50.0  # these deviations alone are enough, no z-score needed
MONTH_COMPLETENESS = 75.0  # % of hours present, below which the whole month is suspect
YOY_MADT_PCT = 25.0  # % the monthly average daily volume may deviate from its norm
YOY_MADT_CRITICAL = 40.0  # % from which that deviation is critical
YOY_MIX_PP = 8.0  # percentage points the heavy-truck share may change
YOY_SPEED = 15.0  # км/ч the mean monthly speed may drop
MEGA_PCT = 60.0  # |deviation| of a traffic anomaly from which it is highlighted (FR3)

LEVEL_CRITICAL, LEVEL_HIGH = "critical", "high"


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


def detect_daily(df: pd.DataFrame, sensor_ids: dict[str, str]) -> list[dict]:
    """Detectors over one calendar day of one section: integrity, stuck sensor,
    direction split, congestion, distorted profile, volume drop and surge."""
    found: list[dict] = []
    work = df.copy()
    work["date"] = work["ts"].dt.date
    work["hour"] = work["ts"].dt.hour
    work["is_weekend"] = work["ts"].dt.dayofweek >= 5
    work["month_key"] = work["ts"].dt.tz_localize(None).dt.strftime("%Y-%m")

    for section, sec_df in work.groupby("section"):
        sensor_id = sensor_ids[section]

        for day, day_df in sec_df.groupby("date"):
            day_df = day_df.sort_values("hour")
            day_ts = pd.Timestamp(day, tz=day_df["ts"].iloc[0].tzinfo)
            end = day_ts + pd.Timedelta(days=1)

            hours = len(day_df)
            if hours < 24:
                found.append(
                    anomaly(
                        sensor_id,
                        day_ts,
                        end,
                        "technical",
                        "missing_hours",
                        "integrity",
                        LEVEL_CRITICAL,
                        "volume",
                        hours,
                        24,
                        (hours - 24) / 24 * 100,
                        3.0,
                        f"В сутках сохранено лишь {hours} часов вместо 24",
                    )
                )

            # A stuck sensor: the same volume (> 10 авт./ч) for FLATLINE_MIN_HOURS or more
            # hours in a row; one anomaly per run, [starts_at, ends_at) covers the run.
            stamps = day_df["ts"].tolist()
            values = day_df["volume"].tolist()
            run_start = 0
            for i in range(1, len(values) + 1):
                same = (
                    i < len(values)
                    and values[i] == values[run_start]
                    and values[i] is not None
                    and pd.notna(values[i])
                    and values[i] > 10
                )
                if not same:
                    run_len = i - run_start
                    if run_len >= FLATLINE_MIN_HOURS:
                        found.append(
                            anomaly(
                                sensor_id,
                                stamps[run_start],
                                stamps[run_start] + pd.Timedelta(hours=run_len),
                                "technical",
                                "flatline",
                                "sensor",
                                LEVEL_CRITICAL,
                                "volume",
                                values[run_start],
                                None,
                                None,
                                4.0,
                                f"Интенсивность не менялась {run_len} часов подряд "
                                f"({int(values[run_start])} авт./ч)",
                            )
                        )
                    run_start = i

            daytime = day_df[(day_df["hour"] >= 7) & (day_df["hour"] <= 21)]
            day_volume = daytime["volume"].sum()
            if day_volume > BALANCE_MIN_DAY_VOLUME:
                share = daytime["volume_direct"].sum() / day_volume * 100
                if not BALANCE_BAND[0] * 100 <= share <= BALANCE_BAND[1] * 100:
                    found.append(
                        anomaly(
                            sensor_id,
                            day_ts,
                            end,
                            "technical",
                            "direction_imbalance",
                            "direction",
                            LEVEL_HIGH,
                            "volume_direct",
                            share,
                            50.0,
                            share - 50.0,
                            2.8,
                            f"Доля прямого направления составила {share:.1f}% от дневного объёма",
                        )
                    )

            if len(daytime) > 0:
                slow = daytime.dropna(subset=["speed_direct"])
                if len(slow) > 0:
                    min_row = slow.loc[slow["speed_direct"].idxmin()]
                    load = daytime["load_direct"].max()
                    if (
                        pd.notna(load)
                        and min_row["speed_direct"] < CONGESTION_SPEED
                        and load > CONGESTION_LOAD
                    ):
                        found.append(
                            anomaly(
                                sensor_id,
                                day_ts,
                                end,
                                "traffic",
                                "congestion",
                                "speed_load",
                                LEVEL_CRITICAL,
                                "speed_direct",
                                min_row["speed_direct"],
                                80.0,
                                (min_row["speed_direct"] - 80.0) / 80.0 * 100,
                                4.5,
                                f"В {int(min_row['hour']):02d}:00 скорость упала до "
                                f"{min_row['speed_direct']:.0f} км/ч при загрузке {load:.0f}%",
                            )
                        )

        # The norm of the month and day type: the median volume of every hour.
        for (_month_key, _is_weekend), group in sec_df.groupby(["month_key", "is_weekend"]):
            norm = group.groupby("hour")["volume"].median()
            full_days = group[group["hour"].groupby(group["date"]).transform("size") == 24]

            for day, day_df in full_days.groupby("date"):
                profile = day_df.set_index("hour")["volume"].sort_index()
                if norm.std() > 0 and profile.std() > 0 and profile.sum() > PROFILE_MIN_DAY_VOLUME:
                    corr = float(np.corrcoef(norm.values, profile.reindex(norm.index).values)[0, 1])
                    if corr < PROFILE_CORR:
                        day_ts = pd.Timestamp(day, tz=group["ts"].iloc[0].tzinfo)
                        found.append(
                            anomaly(
                                sensor_id,
                                day_ts,
                                day_ts + pd.Timedelta(days=1),
                                "traffic",
                                "profile_shift",
                                "profile",
                                LEVEL_HIGH,
                                "volume",
                                float(profile.sum()),
                                float(norm.sum()),
                                (profile.sum() - norm.sum()) / norm.sum() * 100,
                                2.5,
                                "Форма суточного хода нетипична "
                                f"(корреляция с нормой {corr:.2f} < 0,70)",
                            )
                        )

            daily = group.groupby("date")["volume"].sum()
            if len(daily) < 3:
                continue
            median = daily.median()
            mad = (daily - median).abs().median()
            mad = mad if (mad > 0 and pd.notna(mad)) else (daily.std() or 1.0)
            mad = mad if (mad > 0 and pd.notna(mad)) else 1.0

            for day, volume in daily.items():
                z = 0.6745 * (volume - median) / mad
                dev = (volume - median) / median * 100 if median > 0 else 0.0
                day_ts = pd.Timestamp(day, tz=group["ts"].iloc[0].tzinfo)
                drop = (z < DROUGHT_Z and dev <= DROUGHT_PCT) or dev <= -SPIKE_PCT
                surge = (z > SURGE_Z and dev >= SURGE_PCT) or dev >= SPIKE_PCT
                if drop or surge:
                    type_ = "volume_spike" if surge else "volume_drop"
                    level = LEVEL_HIGH if surge else LEVEL_CRITICAL
                    verb = "выше" if surge else "ниже"
                    found.append(
                        anomaly(
                            sensor_id,
                            day_ts,
                            day_ts + pd.Timedelta(days=1),
                            "traffic",
                            type_,
                            "amplitude",
                            level,
                            "volume",
                            float(volume),
                            float(median),
                            dev,
                            abs(z),
                            f"Суточный трафик {int(volume)} авт. {verb} нормы {int(median)} "
                            f"на {abs(dev):.0f}% (z = {z:.1f})",
                        )
                    )

    return found


def detect_monthly(df: pd.DataFrame, sensor_ids: dict[str, str]) -> list[dict]:
    """Year-over-year detectors: for every calendar month, its statistics are compared
    with the median of the same calendar month in the other years."""
    found: list[dict] = []
    work = df.copy()
    work["month_key"] = work["ts"].dt.tz_localize(None).dt.to_period("M")
    work["heavy"] = work["large_trucks"].fillna(0) + work["road_trains"].fillna(0)

    for section, sec_df in work.groupby("section"):
        sensor_id = sensor_ids[section]
        stats = []
        for month_key, month_df in sec_df.groupby("month_key"):
            expected_hours = month_key.days_in_month * 24
            daily = month_df.groupby(month_df["ts"].dt.date)["volume"].sum()
            volume = month_df["volume"].sum()
            stats.append(
                {
                    "month_key": month_key,
                    "completeness": len(month_df) / expected_hours * 100,
                    "madt": daily.mean() if len(daily) > 0 else np.nan,
                    "speed": month_df["speed_direct"].mean(),
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
            med_heavy = group["heavy_share"].median()

            for row in group.itertuples():
                start = row.month_key.start_time.tz_localize(df["ts"].dt.tz)
                end = (row.month_key + 1).start_time.tz_localize(df["ts"].dt.tz)

                if row.completeness < MONTH_COMPLETENESS:
                    found.append(
                        anomaly(
                            sensor_id,
                            start,
                            end,
                            "technical",
                            "missing_hours",
                            "integrity",
                            LEVEL_CRITICAL,
                            "volume",
                            row.completeness,
                            95.0,
                            row.completeness - 100.0,
                            None,
                            f"Данные за месяц неполные "
                            f"(сохранено лишь {row.completeness:.0f}% часов)",
                        )
                    )

                if pd.notna(row.madt) and med_madt > 0:
                    dev = (row.madt - med_madt) / med_madt * 100
                    if abs(dev) >= YOY_MADT_PCT:
                        surge = dev > 0
                        found.append(
                            anomaly(
                                sensor_id,
                                start,
                                end,
                                "traffic",
                                "volume_spike" if surge else "volume_drop",
                                "yoy",
                                LEVEL_CRITICAL if abs(dev) >= YOY_MADT_CRITICAL else LEVEL_HIGH,
                                "volume",
                                row.madt,
                                med_madt,
                                dev,
                                None,
                                f"Среднесуточная интенсивность месяца {int(row.madt)} авт. "
                                f"отклонилась на {dev:+.1f}% от нормы {int(med_madt)}",
                            )
                        )

                if pd.notna(row.heavy_share) and pd.notna(med_heavy):
                    delta_points = row.heavy_share - med_heavy
                    if abs(delta_points) >= YOY_MIX_PP:
                        dev = delta_points / med_heavy * 100 if med_heavy > 0 else None
                        found.append(
                            anomaly(
                                sensor_id,
                                start,
                                end,
                                "traffic",
                                "vehicle_mix_shift",
                                "mix",
                                LEVEL_HIGH,
                                "large_trucks",
                                row.heavy_share,
                                med_heavy,
                                dev,
                                None,
                                f"Доля тяжёлых грузовиков {row.heavy_share:.1f}% против "
                                f"нормы {med_heavy:.1f}% ({delta_points:+.1f} п.п.)",
                            )
                        )

                if pd.notna(row.speed) and pd.notna(med_speed):
                    delta_speed = row.speed - med_speed
                    if delta_speed <= -YOY_SPEED:
                        found.append(
                            anomaly(
                                sensor_id,
                                start,
                                end,
                                "traffic",
                                "speed_drop",
                                "yoy",
                                LEVEL_CRITICAL,
                                "speed_direct",
                                row.speed,
                                med_speed,
                                delta_speed / med_speed * 100 if med_speed > 0 else None,
                                None,
                                f"Средняя скорость за месяц {row.speed:.0f} км/ч, "
                                f"на {abs(delta_speed):.1f} км/ч ниже нормы",
                            )
                        )

    return found


def detect_all(df: pd.DataFrame, sensors: list[dict]) -> list[dict]:
    """Run every detector, number and mark the findings, sorted by sensor and time."""
    if df.empty:
        return []
    sensor_ids = {sensor["name"]: sensor["id"] for sensor in sensors}
    found = detect_daily(df, sensor_ids) + detect_monthly(df, sensor_ids)

    used: dict[str, int] = {}
    for item in found:
        stamp = item["starts_at"][:10].replace("-", "")
        base = f"{ROAD}-{item['type'].replace('_', '-')}-{stamp}"
        used[base] = used.get(base, 0) + 1
        item["id"] = f"{base}-{used[base]:02d}"
        if item["deviation_pct"] is not None and abs(item["deviation_pct"]) >= MEGA_PCT:
            item["is_mega"] = True

    return sorted(found, key=lambda a: (a["sensor_id"], a["starts_at"], a["type"], a["detector"]))
