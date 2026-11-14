"""A next-hour volume forecast by the module's own baseline idea, honestly measured.

The forecaster is the detection norm of detect.py turned around into a prediction
(issue #40): the point forecast of one hour is the median of the sensor's own REAL
hours of the same weekday kind and the same hour within the WINDOW_DAYS days before
it, at least MIN_REFS of them; under that there is no forecast, only the reason. No
new model and no new dependency: the same floored robust scale that sets z in
detection draws a wide band around the point (=BAND_SIGMAS of sigma, a normal
distribution stays inside a +-3.5 sigma band with ~99.95 % probability - an
expectation, not a promise).

The customer framing of #40 is one screen: the last full hour, and next to it the
expected volume of the hour coming after it. `hour_forecast(filled_hours, target,
cutoff)` answers exactly that question, using only hours at or before `cutoff`.

`backtest()` measures the error on the real three-year series by walking it forward
one week at a time: at the start of every week the forecaster gets only the hours
strictly before that moment and forecasts every real hour of the week ahead; the
SAME HOUR ONE WEEK EARLIER is the naive baseline the rule must beat to earn its
place. The backtest deliberately never looks forward (the offline caveat of #37 is
allowed for detection norms, not for a claimed forecast error)."""

import numpy as np
import pandas as pd

from . import detect
from .trends import calendar_keys

WINDOW_DAYS = detect.NORM_WINDOW_DAYS  # 84, the same reference radius as the norms
MIN_REFS = detect.MIN_REF_DAYS  # ... and the same minimum number of references
BAND_SIGMAS = 3.5  # expected band of ~99.95 % for the normal case
STEP_DAYS = 7  # walk-forward: a fresh one-week forecast run every week
NAIVE_LAG_DAYS = 7  # the baseline to beat: the same hour one week earlier
MAPE_MIN_ACTUAL = 10.0  # MAPE is only reported on hours with this much real traffic,
# a night hour of 2 cars makes any percentage a lottery; WAPE has no such floor
METRIC = "volume"


def _to_local(ts: pd.Timestamp) -> pd.Timestamp:
    """Drop the fixed +03 offset for calendar arithmetic (see _working_frame)."""
    return ts.tz_convert(None) if ts.tzinfo is not None else ts


def real_hours(filled: pd.DataFrame) -> pd.DataFrame:
    """Real (not imputed) hours of every sensor with the keys the forecaster selects
    by: weekday kind within WEEKDAY_POOLING, hour of day, and metric value."""
    work = filled.copy()
    work["ts_local"] = work["ts"].dt.tz_convert(None)
    work["day_group"] = [detect.day_group(ts) for ts in work["ts_local"]]
    work["hour"] = work["ts_local"].dt.hour
    hours = work[work["imputation_method"].eq("") & work[METRIC].notna()]
    return hours.sort_values("ts_local", ignore_index=True)


def _select(times: np.ndarray, values: np.ndarray, target: pd.Timestamp, cutoff: pd.Timestamp):
    """Reference values: same (weekday kind, hour) bucket, inside
    [target - WINDOW_DAYS days, cutoff] of the sensor's own sorted real hours."""
    lo = np.datetime64(target - pd.Timedelta(days=WINDOW_DAYS))
    hi = np.datetime64(cutoff)
    return values[np.searchsorted(times, lo) : np.searchsorted(times, hi, side="right")]


def _point_forecast(refs: np.ndarray) -> dict | None:
    """The forecast itself: median of the references, floored robust band around it.
    None below MIN_REFS references - the forecaster stays silent instead of guessing."""
    if len(refs) < MIN_REFS:
        return None
    median = float(np.median(refs))
    mad = float(np.median(np.abs(refs - median)))
    sigma = detect._sigma(median, mad, detect.FLOOR_VOLUME_HOUR)
    return {
        "refs": len(refs),
        "volume": median,
        "sigma": sigma,
        "band_low": max(0.0, median - BAND_SIGMAS * sigma),
        "band_high": median + BAND_SIGMAS * sigma,
    }


def hour_forecast(hours: pd.DataFrame, target: pd.Timestamp, cutoff: pd.Timestamp) -> dict | None:
    """Expected volume of hour `target` from ONE sensor's real hours at or before
    `cutoff` (the last full hour the dashboard shows; usually target = cutoff + 1 h).

    `hours` holds columns ts and volume only. The answer is {"refs", "volume",
    "sigma", "band_low", "band_high"} or None when fewer than MIN_REFS same-kind
    same-hour references fall within WINDOW_DAYS days before the target: the stated
    reason of a missing forecast is the reference count, and the backtest output
    carries exactly those counts."""
    local_target = _to_local(pd.Timestamp(target))
    local_cutoff = _to_local(pd.Timestamp(cutoff))
    group = detect.day_group(local_target)
    ts_local = hours["ts"].map(_to_local)
    mask = (
        ts_local.map(detect.day_group).eq(group)
        & ts_local.dt.hour.eq(local_target.hour)
        & ts_local.le(local_cutoff)
        & hours[METRIC].notna()
    )
    part = hours[mask].loc[ts_local[mask].sort_values().index]
    refs = _select(
        pd.DatetimeIndex(part["ts"].map(_to_local)).to_numpy(),
        part[METRIC].to_numpy(dtype="float64"),
        local_target,
        local_cutoff,
    )
    return _point_forecast(refs)


def _buckets(hours: pd.DataFrame) -> dict:
    """Per (weekday kind, hour) selection arrays of one sensor, sorted in time."""
    buckets = {}
    for (group, hour), part in hours.groupby(["day_group", "hour"]):
        part = part.sort_values("ts_local")
        buckets[(group, hour)] = (
            pd.DatetimeIndex(part["ts_local"]).to_numpy(),
            part[METRIC].to_numpy(dtype="float64"),
        )
    return buckets


def _metrics(rows: pd.DataFrame) -> dict:
    """MAE, WAPE and floored MAPE of one frame of {actual, pred} forecast points."""
    n = len(rows)
    if n == 0:
        return {"n": 0, "mae": None, "wape_pct": None, "mape_pct": None}
    error = (rows["pred"] - rows["actual"]).abs()
    big = rows[rows["actual"] >= MAPE_MIN_ACTUAL]
    return {
        "n": n,
        "mae": round(float(error.mean()), 1),
        "wape_pct": round(float(error.sum() / rows["actual"].sum() * 100), 1),
        "mape_pct": (
            round(float((error.loc[big.index] / big["actual"]).mean() * 100), 1)
            if len(big)
            else None
        ),
    }


def _versus(rows: pd.DataFrame) -> dict:
    """The honest comparison: both rules measured on the SAME hours (head to head -
    a rule may not win by being allowed to skip the hard hours)."""
    both = rows[rows["pred"].notna() & rows["naive"].notna()]
    forecaster, naive = _metrics(both), _metrics(both.assign(pred=both["naive"]))
    gain = None
    if forecaster["mae"] is not None and naive["mae"] not in (None, 0):
        gain = round((naive["mae"] - forecaster["mae"]) / naive["mae"] * 100, 1)
    return {"n": forecaster["n"], "forecaster": forecaster, "naive": naive, "mae_gain_pct": gain}


def backtest_sensor(hours: pd.DataFrame, sensor_id: str) -> pd.DataFrame:
    """One sensor's walk-forward points: every real hour of every full week gets a
    row with the actual, the forecast from the hours strictly before the week
    started, and the same hour one week earlier as the naive baseline."""
    hours = hours[hours["sensor_id"].eq(sensor_id)]
    if hours.empty:
        return pd.DataFrame()
    first, last = hours["ts_local"].iloc[0], hours["ts_local"].iloc[-1]
    start = first.normalize()
    if start.dayofweek:
        start += pd.Timedelta(days=7 - start.dayofweek)  # first week boundary (Monday)
    buckets = _buckets(hours)
    known = dict(zip(hours["ts_local"], hours[METRIC], strict=True))
    rows = []
    for origin in pd.date_range(start, last, freq=f"{STEP_DAYS}D"):
        cutoff = origin - pd.Timedelta(hours=1)
        week = hours[
            (hours["ts_local"] >= origin)
            & (hours["ts_local"] < origin + pd.Timedelta(days=STEP_DAYS))
        ]
        for row in week.itertuples():
            times, values = buckets[(row.day_group, row.hour)]
            refs = _select(times, values, row.ts_local, cutoff)
            forecast = _point_forecast(refs)
            naive = known.get(row.ts_local - pd.Timedelta(days=NAIVE_LAG_DAYS))
            calendar = calendar_keys(row.ts_local)
            rows.append(
                {
                    "sensor_id": sensor_id,
                    "ts": row.ts_local,
                    "season": calendar["season"],
                    "day_kind": calendar["day_kind"],
                    "hour": calendar["hour"],
                    "actual": float(getattr(row, METRIC)),
                    "pred": None if forecast is None else forecast["volume"],
                    "band_low": None if forecast is None else forecast["band_low"],
                    "band_high": None if forecast is None else forecast["band_high"],
                    "refs": len(refs),
                    "naive": None if naive is None or pd.isna(naive) else float(naive),
                }
            )
    return pd.DataFrame(rows)


def _error_tables(rows: pd.DataFrame) -> dict:
    """Head-to-head error overall, per season and per kind of day (all tables compare
    both rules on the hours where both could speak; the forecaster is the only one
    that can see holiday norms, and the naive can only repeat what last week did)."""
    tables = {"overall": _versus(rows)}
    for field, keys in (
        ("season", ("winter", "spring", "summer", "autumn")),
        ("day_kind", ("weekday", "weekend", "holiday")),
    ):
        tables[f"by_{field}"] = {
            key: _versus(part)
            if len(part := rows[rows[field].eq(key)])
            else _versus(pd.DataFrame(columns=rows.columns))
            for key in keys
        }
    return tables


def _coverage(rows: pd.DataFrame) -> dict:
    """How many of the forecast hours actually fell inside the +-3.5 sigma band."""
    spoken = rows[rows["pred"].notna()]
    if spoken.empty:
        return {"forecast_hours": 0, "inside_band": 0, "coverage_pct": None}
    inside = (
        (spoken["actual"] >= spoken["band_low"]) & (spoken["actual"] <= spoken["band_high"])
    ).sum()
    return {
        "forecast_hours": len(spoken),
        "inside_band": int(inside),
        "coverage_pct": round(float(inside) / len(spoken) * 100, 2),
        "normal_expectation_pct": 99.95,
    }


def backtest(filled: pd.DataFrame) -> dict:
    """Walk-forward forecast error of the whole module table: per sensor and pooled,
    head to head with the naive baseline, per season, with the band coverage and the
    reasons every missing forecast has (reference-count buckets)."""
    hours = real_hours(filled)
    per_sensor, every = {}, []
    for sensor_id, part in hours.groupby("sensor_id"):
        rows = backtest_sensor(part, sensor_id)
        if rows.empty:
            per_sensor[sensor_id] = {"weeks_walked": 0, "real_hours_evaluated": 0}
            continue
        every.append(rows)
        silent = int((rows["refs"] == 0).sum())
        few = int(((rows["refs"] > 0) & (rows["refs"] < MIN_REFS)).sum())
        per_sensor[sensor_id] = {
            "weeks_walked": int(rows["ts"].dt.to_period("W").nunique()),
            "real_hours_evaluated": len(rows),
            "forecasts": int(rows["pred"].notna().sum()),
            "no_forecast": {"no_references": silent, "fewer_than_6_references": few},
            "naive_available": int(rows["naive"].notna().sum()),
            "results": _error_tables(rows),
            "band": _coverage(rows),
        }
    pooled = pd.concat(every, ignore_index=True) if every else pd.DataFrame()
    overall = {"sensors": len(per_sensor)}
    if len(pooled):
        overall["real_hours_evaluated"] = len(pooled)
        overall["forecasts"] = int(pooled["pred"].notna().sum())
        overall["results"] = _error_tables(pooled)
        overall["band"] = _coverage(pooled)
    return {
        "method": {
            "forecaster": f"median of the sensor's own real hours of the same weekday "
            f"kind and hour within the {WINDOW_DAYS} days before the target, at least "
            f"{MIN_REFS} of them (the detection norm of detect.py as a prediction)",
            "walk_forward": f"every {STEP_DAYS} days a new run, using only hours strictly "
            "before the week start; every real hour of the week ahead is evaluated",
            "naive_baseline": f"the same hour {NAIVE_LAG_DAYS} days earlier (real hours only)",
            "band": f"+- {BAND_SIGMAS} sigma on the floored robust scale of detect.py",
            "metrics": f"MAE авт./ч, WAPE %, MAPE % on hours with at least "
            f"{MAPE_MIN_ACTUAL:.0f} авт./ч actual; head to head = same hours for both rules",
        },
        "sensors": per_sensor,
        "overall": overall,
    }


def summarize(backtest_data: dict) -> list[str]:
    """Two plain-text lines for the pipeline print: the headline error against the
    naive baseline and where the rule wins and loses by season."""
    results = backtest_data.get("overall", {}).get("results")
    if not results:
        return ["forecast backtest: nothing to measure (no real hours)"]
    head = results["overall"]
    lines = [
        f"backtest: forecaster MAE {head['forecaster']['mae']} авт./ч / WAPE "
        f"{head['forecaster']['wape_pct']}% vs naive {head['naive']['mae']} / "
        f"{head['naive']['wape_pct']}% on {head['n']} real hours (gain "
        f"{head['mae_gain_pct']}%)"
    ]
    gained = {
        season: table["mae_gain_pct"]
        for season, table in results["by_season"].items()
        if table["mae_gain_pct"] is not None and table["n"] > 0
    }
    if gained:
        best = max(gained, key=gained.get)
        worst = min(gained, key=gained.get)
        lines.append(
            f"seasons: best vs naive is {best} ({gained[best]:+}%), worst is "
            f"{worst} ({gained[worst]:+}%)"
        )
    return lines
