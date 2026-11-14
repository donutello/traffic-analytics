"""SQL for /api/sensors."""

import libsql


def sensor_rows(db: libsql.Connection, road: str | None) -> list[tuple]:
    where, args = ("WHERE road = ?", [road]) if road else ("", [])
    return db.execute(
        "SELECT id, name, road, km, lon, lat, direction_direct, direction_reverse"
        f" FROM sensors {where} ORDER BY road, km",
        args,
    ).fetchall()


def anomaly_counts(db: libsql.Connection, period: str, args: list[str]) -> list[tuple]:
    """(sensor_id, source, count) of the anomalies whose interval touches the period."""
    return db.execute(
        "SELECT a.sensor_id, a.source, COUNT(*) FROM anomalies a"
        f" WHERE 1{period} GROUP BY a.sensor_id, a.source",
        args,
    ).fetchall()


def mega_sensor_ids(db: libsql.Connection) -> set[str]:
    return {
        row[0]
        for row in db.execute(
            "SELECT sensor_id FROM anomalies WHERE is_mega = 1"  # of any period, per contract.md
        ).fetchall()
    }
