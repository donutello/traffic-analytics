"""Trends of the module's own findings (issue #40): how often and how strong anomalies
are by season of the year, kind of day and hour of day.

Every traffic finding of anomalies.json is counted in the month/quarter/season, kind of
day (weekday / weekend / holiday, the same table as holidays.py) and hour of the hour
it STARTS in; hours_affected then spreads the finding over its whole interval.
Frequency is shown twice: a plain count, and findings per 1000 real (not imputed)
sensor hours of the same bucket, so a sensor being offline for a year cannot make that
year look seasonally quiet. Strength is the module score on the shared contract 0..10
scale, so these tables can one day be put next to the other roads' tables.

Technical findings (the sensor-health story of #36) are counted in the totals only:
they describe the telemetry, not the traffic, and km 478's silence would otherwise
out-shout every traffic season.
"""

import pandas as pd

from .holidays import day_kind

SEASONS = {
    12: "winter",
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
}
ORDER = {
    "season": ["winter", "spring", "summer", "autumn"],
    "day_kind": ["weekday", "weekend", "holiday"],
}


def season_of(month: int) -> str:
    """Meteorological season: winter is Dec-Feb, spring Mar-May, and so on."""
    return SEASONS[month]


def calendar_keys(moment: pd.Timestamp) -> dict:
    """The seasonal calendar of one timestamp: month, quarter, season, day kind, hour."""
    month = moment.month
    return {
        "month": month,
        "quarter": (month - 1) // 3 + 1,
        "season": season_of(month),
        "day_kind": day_kind(moment),
        "hour": moment.hour,
    }


DIMENSIONS = [
    ("month", "by_month"),
    ("quarter", "by_quarter"),
    ("season", "by_season"),
    ("day_kind", "by_day_kind"),
    ("hour", "by_hour"),
    ("type", "by_type"),
]


def _bucket_table(
    findings: pd.DataFrame, denominator: pd.Series, total_real_hours: int, field: str
) -> list[dict]:
    """One bucket per value of `field`: counts, affected hours, scores and the
    frequency per 1000 real hours of the same bucket (per type the denominator is the
    whole record, since a type is not a span of time)."""
    rows = []
    keys = (
        ORDER.get(field, sorted(findings[field].unique()))
        if len(findings)
        else ORDER.get(field, [])
    )
    grouped = dict(tuple(findings.groupby(field))) if len(findings) else {}
    for key in keys:
        part = grouped.get(key)
        scores = (
            part["score"].dropna() if part is not None and len(part) else pd.Series(dtype=float)
        )
        # a type is not a span of time, so its frequency runs against the whole record
        real_hours = total_real_hours if field == "type" else int(denominator.get(key, 0))
        count = 0 if part is None else len(part)
        rows.append(
            {
                "bucket": key.item() if hasattr(key, "item") else key,  # numpy int keys
                "count": count,
                "hours_affected": 0.0 if part is None else round(float(part["hours"].sum()), 1),
                "mean_score": None if scores.empty else round(float(scores.mean()), 2),
                "max_score": None if scores.empty else round(float(scores.max()), 1),
                "real_hours": real_hours,
                "per_1000h": round(count / real_hours * 1000, 3) if real_hours > 0 else None,
            }
        )
    return rows


def build_trends(filled: pd.DataFrame, anomalies: list[dict]) -> dict:
    """Trend tables over the module's own anomalies, keyed by the real-hour calendar.

    `filled` is the gap-filled hourly table (its real hours are the frequency
    denominator), `anomalies` the finalized list the same run wrote to anomalies.json.
    """
    real = filled[filled["imputation_method"].eq("")]
    hours = pd.DataFrame(
        {**calendar_keys(ts), "ts": ts} for ts in real["ts"]
    )  # one row per real hour with its calendar keys
    total_real_hours = len(hours)

    rows = []
    for item in anomalies:
        if item["category"] != "traffic" or item["score"] is None:
            continue
        start = pd.Timestamp(item["starts_at"])
        end = pd.Timestamp(item["ends_at"])
        rows.append(
            {
                **calendar_keys(start),
                "type": item["type"],
                "score": float(item["score"]),
                "hours": (end - start) / pd.Timedelta(hours=1),
            }
        )
    findings = pd.DataFrame(rows)

    denominators = {
        field: hours.groupby(field).size()
        for field in ("month", "quarter", "season", "day_kind", "hour")
    }
    tables = {}
    for field, name in DIMENSIONS:
        denominator = denominators.get(field, pd.Series(dtype=int))
        tables[name] = _bucket_table(findings, denominator, total_real_hours, field)

    kinds = pd.Series([a["category"] for a in anomalies]).value_counts()
    starts = pd.Series([a["starts_at"] for a in anomalies if a["category"] == "traffic"])
    return {
        "method": {
            "basis": "the module's own anomalies; every finding counted in the season, "
            "day kind and hour its first deviant hour starts in",
            "frequency": "count and findings per 1000 real (not imputed) sensor hours "
            "of the same bucket; per type against the whole record",
            "strength": "mean and max of the module score on the shared contract 0..10 scale",
            "technical_findings": "excluded from the tables (sensor health, not traffic)",
        },
        "totals": {
            "own_findings": len(anomalies),
            "traffic_findings": int(kinds.get("traffic", 0)),
            "technical_findings": int(kinds.get("technical", 0)),
            "hours_affected": round(float(findings["hours"].sum()), 1) if len(findings) else 0.0,
            "real_hours_in_record": total_real_hours,
            "first_finding": None if starts.empty else str(starts.min()),
            "last_finding": None if starts.empty else str(starts.max()),
        },
        "traffic": tables,
    }


def _peak(table: list[dict], field: str) -> dict | None:
    """The busiest bucket of a table (a table without any finding has none)."""
    filled_rows = [row for row in table if row["count"] > 0]
    if not filled_rows:
        return None
    return max(filled_rows, key=lambda row: row[field])


def summarize(trends: dict) -> list[str]:
    """Two plain-text lines for the pipeline print: where the findings concentrate."""
    tables = trends["traffic"]
    lines = []
    season = _peak(tables["by_season"], "mean_score")
    kind = _peak(tables["by_day_kind"], "per_1000h")
    if season:
        lines.append(
            f"trends: strongest season {season['bucket']} "
            f"(mean score {season['mean_score']}, max {season['max_score']}, "
            f"{season['count']} findings)"
        )
    if kind:
        lines.append(
            f"trends: most frequent kind of day {kind['bucket']} "
            f"({kind['per_1000h']} findings per 1000 real hours)"
        )
    return lines
