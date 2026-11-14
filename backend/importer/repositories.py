"""SQL of the import: deleting one road's old rows and inserting its new ones.

Time conversion and the transaction around it live in backend/importer/services.py.
"""

import libsql

INSERT_SENSOR = """\
INSERT INTO sensors (id, road, road_name, name, km, lat, lon, direction_direct, direction_reverse)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""

INSERT_MEASUREMENT = """\
INSERT INTO measurements
    (sensor_id, ts, volume, volume_direct, volume_reverse, cars, small_trucks, medium_trucks,
     large_trucks, road_trains, buses, motorcycles, speed_direct, speed_reverse, load_direct,
     load_reverse, state, imputation_method)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

INSERT_ANOMALY = """\
INSERT INTO anomalies
    (id, source, road, sensor_id, starts_at, ends_at, category, type, detector, level, metric,
     actual, expected, deviation_pct, score, is_mega, event_id, description)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

INSERT_EVENT = """\
INSERT INTO events (id, road, date, category, title, description, source_url)
VALUES (?, ?, ?, ?, ?, ?, ?)"""

DELETE_ROAD = (
    "DELETE FROM measurements WHERE sensor_id IN (SELECT id FROM sensors WHERE road = ?)",
    "DELETE FROM anomalies WHERE road = ?",
    "DELETE FROM events WHERE road = ?",
    "DELETE FROM sensors WHERE road = ?",
)


def reset_road(db: libsql.Connection, road: str) -> None:
    """Drop the road's rows so a reload replaces them without duplicates."""
    for statement in DELETE_ROAD:
        db.execute(statement, (road,))


def insert_sensors(db: libsql.Connection, rows: list[tuple]) -> None:
    db.executemany(INSERT_SENSOR, rows)


def insert_measurements(db: libsql.Connection, rows: list[tuple]) -> None:
    db.executemany(INSERT_MEASUREMENT, rows)


def insert_events(db: libsql.Connection, rows: list[tuple]) -> None:
    db.executemany(INSERT_EVENT, rows)


def insert_anomalies(db: libsql.Connection, rows: list[tuple]) -> None:
    db.executemany(INSERT_ANOMALY, rows)
