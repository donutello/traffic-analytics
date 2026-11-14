"""SQL for /api/comparison. The anomaly rows are the ones the anomalies feature reads."""

import libsql

from backend.anomalies.repositories import find_anomalies


def comparison_rows(db: libsql.Connection, conditions: list[tuple[str, str]]) -> list[tuple]:
    return find_anomalies(
        db,
        conditions,
        "a.road, a.sensor_id, a.starts_at, a.id",  # grouped per road and sensor
    )


def road_name_rows(db: libsql.Connection) -> list[tuple]:
    return db.execute("SELECT road, road_name FROM sensors GROUP BY road, road_name").fetchall()
