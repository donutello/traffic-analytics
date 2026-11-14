"""Business logic for /api/sensors: GeoJSON features with period-scope counts."""

import libsql

from backend.common.periods import period_conditions
from backend.sensors import repositories


def features(db: libsql.Connection, road: str | None, lo: str | None, hi: str | None) -> list[dict]:
    parts = period_conditions(lo, hi, "a")
    period = "".join(f" AND {sql}" for sql, _ in parts)
    args = [value for _, value in parts]

    counts: dict[str, int] = {}
    for sensor_id, _source, count in repositories.anomaly_counts(db, period, args):
        counts[sensor_id] = counts.get(sensor_id, 0) + count
    mega = repositories.mega_sensor_ids(db)

    return [
        {
            "geometry": {"coordinates": [lon, lat]},
            "properties": {
                "id": sensor_id,
                "name": name,
                "road": sensor_road,
                "km": km,
                "anomaly_count": counts.get(sensor_id, 0),
                "is_mega": sensor_id in mega,
                "directions": {"direct": direct, "reverse": reverse},
            },
        }
        for sensor_id, name, sensor_road, km, lon, lat, direct, reverse in repositories.sensor_rows(
            db, road
        )
    ]
