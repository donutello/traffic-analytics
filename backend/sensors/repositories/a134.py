"""Repository layer for sensors data access."""

import libsql


def get_sensors(db: libsql.Connection) -> list[dict]:
    result = db.execute(
        "SELECT id, name, km, lat, lon, "
        "directions_direct, directions_reverse "
        "FROM sensors WHERE road = 'a134'"
    )
    return [
        {
            "id": row[0],
            "name": row[1],
            "km": row[2],
            "lat": row[3],
            "lon": row[4],
            "directions": {"direct": row[5], "reverse": row[6]},
        }
        for row in result.fetchall()
    ]


def get_sensor_by_id(db: libsql.Connection, sensor_id: str) -> dict | None:
    result = db.execute(
        "SELECT id, name, km, lat, lon, "
        "directions_direct, directions_reverse "
        "FROM sensors WHERE id = ? AND road = 'a134'",
        (sensor_id,),
    )
    row = result.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "km": row[2],
        "lat": row[3],
        "lon": row[4],
        "directions": {"direct": row[5], "reverse": row[6]},
    }
