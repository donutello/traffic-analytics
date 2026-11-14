"""Tests for the #40 extras: trend tables and the walk-forward forecaster.

Small made-up frames only; the numbers asserted are the thresholds the modules
document (6 references, the 84-day window, the 20 авт./ч sigma floor, the 3.5 sigma
band) and the two promises of issue #40: no look-ahead, and the smarter rule measured
against the same-hour-last-week baseline."""

import json

import numpy as np
import pandas as pd

from analysis.r22 import forecast, parse, trends

SID = "r22-km448-650"


def hourly_frame(start: str, days: int, volume_fn, sensor_id: str = SID) -> pd.DataFrame:
    """A gap-filled-looking table of `days` full days from start; volume_fn(day, hour)
    gives the value, every hour real, with the columns the #40 modules select on."""
    first = pd.Timestamp(start, tz=parse.MSK)
    rows = []
    for d in range(days):
        for h in range(24):
            rows.append(
                {
                    "sensor_id": sensor_id,
                    "ts": (first + pd.Timedelta(days=d)).replace(hour=h),
                    "volume": float(volume_fn(d, h)),
                    "imputation_method": "",
                }
            )
    return pd.DataFrame(rows)


def seasonal_frame(start: str = "2024-02-19", weeks: int = 18, seed: int = 7) -> pd.DataFrame:
    """18 weeks of plausible traffic: a daily hump, quieter weekends, a slow upward
    drift and hour noise. The drift is what the naive baseline barely feels and the
    reference median should ride out; the noise is what the median should beat."""
    rng = np.random.default_rng(seed)

    def volume(d, h):
        base = 220.0 + 150.0 * max(0.0, np.sin((h - 5) / 24 * 2 * np.pi))
        if (pd.Timestamp(start) + pd.Timedelta(days=d)).dayofweek >= 5:
            base *= 0.7
        return max(0.0, base + 0.6 * d + rng.normal(0.0, 45.0))

    return hourly_frame(start, weeks * 7, volume)


def hour_rows(volume_value: float, start: str, hours: int) -> pd.DataFrame:
    """A plain ts+volume hours frame for hour_forecast (the dashboard-side input)."""
    first = pd.Timestamp(start, tz=parse.MSK)
    stamps = [first + pd.Timedelta(hours=k) for k in range(hours)]
    return pd.DataFrame({"ts": stamps, "volume": float(volume_value)})


# --- trends --------------------------------------------------------------------------


def trends_fixture():
    filled = pd.concat(
        [
            hourly_frame("2024-05-01", 1, lambda d, h: 100.0),  # a holiday (May 1)
            hourly_frame("2024-05-20", 5, lambda d, h: 100.0),  # Mon..Fri weekdays
            hourly_frame("2024-05-25", 2, lambda d, h: 100.0),  # Sat, Sun
        ],
        ignore_index=True,
    )
    filled.loc[
        filled["ts"] == pd.Timestamp("2024-05-21 03:00", tz=parse.MSK), "imputation_method"
    ] = "profile"

    def anomaly(day, kind, score, type_="volume_drop", hours=1):
        start = pd.Timestamp(day, tz=parse.MSK)
        return {
            "category": kind,
            "type": type_,
            "score": score,
            "starts_at": start.isoformat(),
            "ends_at": (start + pd.Timedelta(hours=hours)).isoformat(),
        }

    findings = [
        anomaly("2024-05-01 12:00", "traffic", 3.0),  # holiday, spring, month 5
        anomaly("2024-05-25 08:00", "traffic", 4.0, hours=4),  # weekend
        anomaly("2024-05-22 09:00", "traffic", 5.0, hours=2, type_="speed_drop"),  # weekday
        anomaly("2024-05-23 00:00", "technical", 3.0, type_="missing_hours", hours=24),
    ]
    return filled, findings


def bucket(table: list[dict], key):
    return next(row for row in table if row["bucket"] == key)


def test_trends_counts_and_rates_each_kind_of_day_separately():
    filled, findings = trends_fixture()
    data = trends.build_trends(filled, findings)
    assert data["totals"]["own_findings"] == 4
    assert data["totals"]["traffic_findings"] == 3
    assert data["totals"]["technical_findings"] == 1  # counted in totals, never in tables

    kinds = data["traffic"]["by_day_kind"]
    assert bucket(kinds, "holiday")["count"] == 1
    assert bucket(kinds, "holiday")["per_1000h"] == round(1 / 24 * 1000, 3)
    assert bucket(kinds, "weekend")["per_1000h"] == round(1 / 48 * 1000, 3)
    weekday = bucket(kinds, "weekday")
    assert weekday["count"] == 1
    assert weekday["real_hours"] == 120 - 1  # the imputed hour leaves the denominator
    assert weekday["per_1000h"] == round(1 / 119 * 1000, 3)

    hours = bucket(data["traffic"]["by_hour"], 8)
    assert hours["hours_affected"] == 4.0  # the whole run counts, not just its start
    assert bucket(data["traffic"]["by_day_kind"], "weekend")["mean_score"] == 4.0
    assert bucket(data["traffic"]["by_type"], "speed_drop")["max_score"] == 5.0
    assert all(
        row["count"] == 0 for row in data["traffic"]["by_season"] if row["bucket"] == "winter"
    )
    assert json.loads(json.dumps(data))["totals"]["traffic_findings"] == 3  # stays JSON-clean


# --- the forecaster itself -------------------------------------------------------------


def test_forecaster_is_silent_below_six_references():
    # Thursdays around 2024-06-27: four same-kind Thursdays are not enough, ten are
    # (2024-05-09, a Thursday, is a holiday and belongs to the pool of days off)
    target = pd.Timestamp("2024-06-27 10:00", tz=parse.MSK)
    cutoff = pd.Timestamp("2024-06-26 23:00", tz=parse.MSK)
    short = hour_rows(100.0, "2024-05-30", 28 * 24)  # Thursdays 30.05, 6./13./20.06 only
    assert forecast.hour_forecast(short, target, cutoff) is None
    long = hour_rows(100.0, "2024-04-08", 80 * 24)  # ten plain Thursdays before cutoff
    result = forecast.hour_forecast(long, target, cutoff)
    assert result is not None and result["refs"] == 10


def test_forecast_band_uses_the_floored_sigma():
    # every reference says 100: MAD 0, 10 % of the median 10, the volume floor 20
    # wins, and the 3.5-sigma band is 100 +- 70 (see detect.py floors, issue #40)
    target = pd.Timestamp("2024-06-27 10:00", tz=parse.MSK)
    cutoff = pd.Timestamp("2024-06-26 23:00", tz=parse.MSK)
    result = forecast.hour_forecast(hour_rows(100.0, "2024-04-08", 80 * 24), target, cutoff)
    assert result["refs"] == 10
    assert result["volume"] == 100.0
    assert result["band_low"] == 30.0 and result["band_high"] == 170.0


# --- the walk-forward backtest -----------------------------------------------------------


def test_backtest_beats_the_naive_baseline_on_seasonal_made_up_data():
    filled = seasonal_frame()
    data = forecast.backtest(filled)
    head = data["overall"]["results"]["overall"]
    assert head["n"] > 1000
    assert head["forecaster"]["mae"] < head["naive"]["mae"]
    assert head["forecaster"]["wape_pct"] < head["naive"]["wape_pct"]
    assert head["mae_gain_pct"] > 0
    assert json.loads(json.dumps(data))  # the committed file must serialize
    assert data["sensors"][SID]["no_forecast"]["fewer_than_6_references"] > 0  # warm-up weeks


def test_backtest_forecast_never_looks_at_the_future():
    target = pd.Timestamp("2024-05-16 10:00", tz=parse.MSK)
    cutoff = target - pd.Timedelta(hours=1)
    hours = seasonal_frame()[["ts", "volume"]]
    before = forecast.hour_forecast(hours, target, cutoff)
    assert before is not None
    shuffled = hours.copy()  # keep every row, scramble every value after the cutoff
    future = shuffled["ts"] > cutoff
    shuffled.loc[future, "volume"] = np.random.default_rng(1).permutation(
        shuffled.loc[future, "volume"].to_numpy()
    )
    assert forecast.hour_forecast(shuffled, target, cutoff) == before


def test_week_backtest_rows_of_earlier_weeks_survive_a_future_shuffle():
    filled = seasonal_frame(weeks=14)
    real = forecast.real_hours(filled)
    plain = forecast.backtest_sensor(real, SID)
    shuffle_from = pd.Timestamp("2024-05-01", tz=parse.MSK).tz_convert(None)  # week 11 on
    mixed = filled.copy()
    future = mixed["ts"].dt.tz_convert(None) >= shuffle_from
    mixed.loc[future, "volume"] = np.random.default_rng(2).permutation(
        mixed.loc[future, "volume"].to_numpy()
    )
    moved = forecast.backtest_sensor(forecast.real_hours(mixed), SID)
    early = plain["ts"] < shuffle_from
    pd.testing.assert_series_equal(plain.loc[early, "pred"], moved.loc[early, "pred"])
