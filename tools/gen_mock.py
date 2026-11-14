"""Generate the frontend prototype's static mock data from analysis/output/_example.

The files mirror exactly the API endpoints of issues #5 and #6, so the UI is
written against real shapes and can be flipped to FastAPI by changing api/index.ts.
Static files cannot filter or group, so every response the API would compute is
precomputed here from one source of truth (the _example module output).
"""

import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # so `uv run python tools/gen_mock.py` finds the contract package

from contract.models import Anomaly, Event, Road, SeriesRow  # noqa: E402

SRC = ROOT / "analysis" / "output" / "_example"
OUT = ROOT / "frontend" / "public" / "mock"

MONTHS = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]
LEVELS = {"low": "низкий", "medium": "средний", "high": "высокий", "critical": "критический"}
CATEGORIES = {"traffic": "транспортная", "technical": "техническая"}
ANOMALY_TYPES = {
    "volume_drop": "падение потока",
    "volume_spike": "всплеск потока",
    "gap": "пропуск данных",
    "speed_drop": "падение скорости",
    "speed_spike": "всплеск скорости",
    "congestion": "пробка",
    "flatline": "зависание датчика",
    "missing_hours": "пропуски данных",
}
EVENT_CATEGORIES = {
    "accident": "ДТП",
    "roadworks": "ремонт дороги",
    "weather": "погода",
    "holiday": "праздник",
    "outage": "отключение",
    "other": "другое",
}


def time_label(dt: datetime) -> str:
    return f"{dt.day} {MONTHS[dt.month - 1]}, {dt:%H:%M}"


def day_label(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


def dump(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


road = Road.model_validate_json((SRC / "sensors.json").read_text(encoding="utf-8"))
road_code = road.road
our_anomalies = [
    Anomaly.model_validate(a)
    for a in json.loads((SRC / "anomalies.json").read_text(encoding="utf-8"))
]
corp_anomalies = [
    Anomaly.model_validate(a)
    for a in json.loads((SRC / "corporate_anomalies.json").read_text(encoding="utf-8"))
]
events = [
    Event.model_validate(e) for e in json.loads((SRC / "events.json").read_text(encoding="utf-8"))
]

with (SRC / "series.csv").open(encoding="utf-8") as handle:
    rows = [
        SeriesRow.model_validate({k: v or None for k, v in r.items()})
        for r in csv.DictReader(handle)
    ]

first_ts = min(r.ts for r in rows)
last_ts = max(r.ts for r in rows)
data_to = last_ts.date()


def anomaly_item(a: Anomaly, source: str) -> dict:
    sensor = next(s for s in road.sensors if s.id == a.sensor_id)
    return {
        "id": a.id,
        "sensor_id": a.sensor_id,
        "sensor_name": sensor.name,
        "starts_at": a.starts_at.isoformat(),
        "ends_at": a.ends_at.isoformat(),
        "starts_label": time_label(a.starts_at),
        "ends_label": time_label(a.ends_at),
        "duration_label": f"{int((a.ends_at - a.starts_at) / timedelta(hours=1))} ч",
        "days_ago": (data_to - a.starts_at.date()).days,
        "category": a.category,
        "category_label": CATEGORIES[a.category],
        "type": a.type,
        "type_label": ANOMALY_TYPES.get(a.type, a.type),
        "detector": a.detector,
        "level": a.level,
        "level_label": LEVELS[a.level],
        "metric": a.metric,
        "actual": a.actual,
        "expected": a.expected,
        "deviation_pct": a.deviation_pct,
        "score": a.score,
        "is_mega": a.is_mega,
        "event_id": a.event_id,
        "description": a.description,
        "source": source,
        "source_label": "наш алгоритм" if source == "ours" else "корпоративная система",
    }


events_out = [
    {
        "id": e.id,
        "date": e.date.isoformat(),
        "date_label": day_label(e.date),
        "category": e.category,
        "category_label": EVENT_CATEGORIES[e.category],
        "title": e.title,
        "description": e.description,
        "source_url": e.source_url,
    }
    for e in events
]
event_labels = {ev["id"]: ev for ev in events_out}

items_by_sensor: dict[str, list[dict]] = {}
for source, source_list in (("ours", our_anomalies), ("corporate", corp_anomalies)):
    for a in source_list:
        items_by_sensor.setdefault(a.sensor_id, []).append(anomaly_item(a, source))
for items in items_by_sensor.values():
    items.sort(key=lambda i: i["starts_at"])

# sensors.geojson: GET /api/sensors (#6). The map marker color depends on anomaly_count.
geo = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s.lon, s.lat]},
            "properties": {
                "id": s.id,
                "name": s.name,
                "road": road_code,
                "km": s.km,
                "anomaly_count": len(items_by_sensor.get(s.id, [])),
                "is_mega": any(i["is_mega"] for i in items_by_sensor.get(s.id, [])),
                "directions": {"direct": s.directions.direct, "reverse": s.directions.reverse},
            },
        }
        for s in road.sensors
    ],
}

# anomalies/<road>.json: list behind GET /api/anomalies, grouped per sensor for the side panel (#6).
# anomalies/<road>/<id>.json: GET /api/anomalies/{id} with the linked event resolved (#6).
anomaly_files = {
    sensor_id: {
        "counts": {
            "ours": sum(1 for i in items if i["source"] == "ours"),
            "corporate": sum(1 for i in items if i["source"] == "corporate"),
        },
        "anomalies": items,
    }
    for sensor_id, items in items_by_sensor.items()
}

# series/<road>.<granularity>.json: GET /api/series (#5). State: anomaly if an anomaly interval
# covers the hour, else the series state (filled gaps stay "imputed").
for sensor in road.sensors:
    hours = [r for r in rows if r.sensor_id == sensor.id]
    hour_points = [
        {
            "ts": r.ts.isoformat(),
            "label": f"{r.ts:%H:%M}",
            "volume": r.volume,
            "state": "anomaly"
            if any(
                a.sensor_id == r.sensor_id
                and a.starts_at <= r.ts + timedelta(hours=1)
                and a.ends_at >= r.ts
                for a in our_anomalies
            )
            else r.state,
        }
        for r in hours
    ]

    files = {f"{sensor.id}.hour.json": {"points": hour_points}}
    for granularity, day_of in (
        ("day", lambda ts: ts.date()),
        ("week", lambda ts: ts.date() - timedelta(days=ts.weekday())),
    ):
        groups: dict[date, list[tuple[SeriesRow, dict]]] = {}
        for r, hour_point in zip(hours, hour_points, strict=True):
            groups.setdefault(day_of(r.ts), []).append((r, hour_point))
        points = []
        for day in sorted(groups):
            states = [hour_point["state"] for _, hour_point in groups[day]]
            state = (
                "anomaly" if "anomaly" in states else "imputed" if "imputed" in states else "normal"
            )
            points.append(
                {
                    "ts": day.isoformat(),
                    "label": day_label(day),
                    "volume": round(sum(r.volume for r, _ in groups[day]) / len(groups[day])),
                    "state": state,
                }
            )
        files[f"{sensor.id}.{granularity}.json"] = {"points": points}
    for name, data in files.items():
        dump(OUT / "series" / name, data)

dump(OUT / "sensors.geojson", geo)
dump(
    OUT / "meta.json",
    {
        "roads": [{"code": road_code, "name": road.road_name, "sensors": len(road.sensors)}],
        "period": {"from": first_ts.date().isoformat(), "to": data_to.isoformat()},
        "generated_from": "analysis/output/_example",
    },
)
for sensor_id, data in anomaly_files.items():
    dump(OUT / "anomalies" / f"{sensor_id}.json", data)
    for item in data["anomalies"]:
        detail = {**item, "event": event_labels.get(item["event_id"]) if item["event_id"] else None}
        dump(OUT / "anomalies" / road_code / f"{item['id']}.json", detail)
dump(OUT / "events.json", events_out)
print("ok:", sum(1 for _ in OUT.rglob("*")), "files")
