"""Business logic for /api/anomalies: the Russian display item and the detail with its event.

The comparison feature reuses anomaly_item and data_last_day from here (docs/adr/0009).
"""

from datetime import date, timedelta

import libsql
from fastapi import HTTPException

from backend.anomalies import repositories
from backend.common.periods import (
    day_label,
    parse_moment,
    period_conditions,
    time_label,
    with_offset,
)

# Russian text the dashboard shows. Codes stay English (docs/contract.md, "General rules").
LEVEL_LABELS = {"low": "низкий", "medium": "средний", "high": "высокий", "critical": "критический"}
CATEGORY_LABELS = {"traffic": "транспортная", "technical": "техническая"}
ANOMALY_TYPE_LABELS = {
    "volume_drop": "падение потока",
    "volume_spike": "всплеск потока",
    "gap": "пропуск данных",
    "speed_drop": "падение скорости",
    "speed_spike": "всплеск скорости",
    "congestion": "пробка",
    "flatline": "зависание датчика",
    "missing_hours": "пропуски данных",
}
EVENT_CATEGORY_LABELS = {
    "accident": "ДТП",
    "roadworks": "ремонт дороги",
    "weather": "погода",
    "holiday": "праздник",
    "outage": "отключение",
    "other": "другое",
}
SOURCE_LABELS = {"ours": "наш алгоритм", "corporate": "корпоративная система"}


def anomaly_item(row: tuple, last_day: date | None) -> dict:
    """One anomalies row (+ joined sensor_name as the last column) as an API item."""
    a = dict(zip(repositories.ANOMALY_COLUMNS, row, strict=False))  # the row ends with the name
    starts, ends = parse_moment(a["starts_at"]), parse_moment(a["ends_at"])
    return {
        "id": a["id"],
        "sensor_id": a["sensor_id"],
        "sensor_name": row[-1],
        "starts_at": with_offset(a["starts_at"]),
        "ends_at": with_offset(a["ends_at"]),
        "starts_label": time_label(starts),
        "ends_label": time_label(ends),
        "duration_label": f"{round((ends - starts) / timedelta(hours=1))} ч",
        "days_ago": (last_day - starts.date()).days if last_day else 0,
        "category": a["category"],
        "category_label": CATEGORY_LABELS[a["category"]],
        "type": a["type"],
        "type_label": ANOMALY_TYPE_LABELS.get(a["type"], a["type"]),
        "detector": a["detector"],
        "level": a["level"],
        "level_label": LEVEL_LABELS[a["level"]],
        "metric": a["metric"],
        "actual": a["actual"],
        "expected": a["expected"],
        "deviation_pct": a["deviation_pct"],
        "score": a["score"],
        "is_mega": a["is_mega"],
        "event_id": a["event_id"],
        "description": a["description"],
        "source": a["source"],
        "source_label": SOURCE_LABELS[a["source"]],
    }


def query(
    db: libsql.Connection,
    road: str | None,
    sensor: str | None,
    anomaly_type: str | None,
    source: str | None,
    level: str | None,
    lo: str | None,
    hi: str | None,
) -> dict:
    """The side panel: our and the corporate system's findings, ours+corporate in one list."""
    conditions = []
    for value, column in (
        (road, "a.road"),
        (sensor, "a.sensor_id"),
        (anomaly_type, "a.type"),
        (source, "a.source"),
        (level, "a.level"),
    ):
        if value:
            conditions.append((f"{column} = ?", value))
    conditions += period_conditions(lo, hi, "a")

    rows = repositories.find_anomalies(db, conditions, "a.starts_at, a.id")
    last_day = repositories.data_last_day(db)
    items = [anomaly_item(row, last_day) for row in rows]
    return {
        "counts": {
            "ours": sum(1 for item in items if item["source"] == "ours"),
            "corporate": sum(1 for item in items if item["source"] == "corporate"),
        },
        "anomalies": items,
    }


def event_of(event_id: str, db: libsql.Connection) -> dict | None:
    """The event that explains an anomaly, with its Russian label and link."""
    found = repositories.find_event(db, event_id)
    if found is None:
        return None
    event_id, event_date, category, title, description, source_url = found
    return {
        "id": event_id,
        "date": event_date,
        "date_label": day_label(date.fromisoformat(event_date)),
        "category": category,
        "category_label": EVENT_CATEGORY_LABELS[category],
        "title": title,
        "description": description,
        "source_url": source_url,
    }


def detail(db: libsql.Connection, anomaly_id: str) -> dict:
    """One finding with its sizes and, when an event explains it, the event and its link."""
    row = repositories.find_anomaly(db, anomaly_id)
    if row is None:
        raise HTTPException(404, f"anomaly {anomaly_id!r} is not in the database")
    item = anomaly_item(row, repositories.data_last_day(db))
    event = event_of(item["event_id"], db) if item["event_id"] else None
    return {**item, "event": event}
