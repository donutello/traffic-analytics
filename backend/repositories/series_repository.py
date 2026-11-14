"""Repository layer for series data access."""

import libsql


def get_series(
    db: libsql.Connection,
    sensor_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Получает временные ряды для трассы А-134 с опциональной фильтрацией."""
    query = """
        SELECT sensor_id, ts, volume, volume_direct, volume_reverse,
               cars, small_trucks, medium_trucks, large_trucks, road_trains,
               buses, motorcycles, speed_direct, speed_reverse,
               load_direct, load_reverse, state, imputation_method
        FROM series
        WHERE sensor_id LIKE 'a134-%'
    """
    params: list[str | int] = []

    if sensor_id:
        query += " AND sensor_id = ?"
        params.append(sensor_id)

    query += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)

    result = db.execute(query, params)
    rows = result.fetchall()

    return [
        {
            "sensor_id": row[0],
            "ts": row[1],
            "volume": row[2],
            "volume_direct": row[3],
            "volume_reverse": row[4],
            "cars": row[5],
            "small_trucks": row[6],
            "medium_trucks": row[7],
            "large_trucks": row[8],
            "road_trains": row[9],
            "buses": row[10],
            "motorcycles": row[11],
            "speed_direct": row[12],
            "speed_reverse": row[13],
            "load_direct": row[14],
            "load_reverse": row[15],
            "state": row[16],
            "imputation_method": row[17],
        }
        for row in rows
    ]
