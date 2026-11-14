"""Repository layer for anomalies data access."""

import libsql


def get_anomalies(
    db: libsql.Connection,
    sensor_id: str | None = None,
    level: str | None = None,
    category: str | None = None,
) -> list[dict]:
    query = (
        "SELECT id, sensor_id, starts_at, ends_at, category, type, "
        "detector, level, metric, actual, expected, deviation_pct, "
        "score, is_mega, event_id, description "
        "FROM anomalies WHERE id LIKE 'a134-%'"
    )
    params: list[str | float] = []
    if sensor_id:
        query += " AND sensor_id = ?"
        params.append(sensor_id)
    if level:
        query += " AND level = ?"
        params.append(level)
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY starts_at DESC"

    return [
        {
            "id": row[0],
            "sensor_id": row[1],
            "starts_at": row[2],
            "ends_at": row[3],
            "category": row[4],
            "type": row[5],
            "detector": row[6],
            "level": row[7],
            "metric": row[8],
            "actual": row[9],
            "expected": row[10],
            "deviation_pct": row[11],
            "score": row[12],
            "is_mega": bool(row[13]),
            "event_id": row[14],
            "description": row[15],
        }
        for row in db.execute(query, params).fetchall()
    ]


def get_anomaly_by_id(db: libsql.Connection, anomaly_id: str) -> dict | None:
    result = db.execute(
        "SELECT id, sensor_id, starts_at, ends_at, category, type, "
        "detector, level, metric, actual, expected, deviation_pct, "
        "score, is_mega, event_id, description "
        "FROM anomalies WHERE id = ? AND id LIKE 'a134-%'",
        (anomaly_id,),
    )
    row = result.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "sensor_id": row[1],
        "starts_at": row[2],
        "ends_at": row[3],
        "category": row[4],
        "type": row[5],
        "detector": row[6],
        "level": row[7],
        "metric": row[8],
        "actual": row[9],
        "expected": row[10],
        "deviation_pct": row[11],
        "score": row[12],
        "is_mega": bool(row[13]),
        "event_id": row[14],
        "description": row[15],
    }
