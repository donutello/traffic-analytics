"""Data access layer for A-134 import."""

import libsql


def create_tables(db: libsql.Connection) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS sensors (
            id TEXT PRIMARY KEY, road TEXT NOT NULL, road_name TEXT NOT NULL,
            name TEXT NOT NULL, km REAL NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
            directions_direct TEXT NOT NULL, directions_reverse TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS series (
            sensor_id TEXT NOT NULL, ts TEXT NOT NULL, volume INTEGER NOT NULL,
            volume_direct INTEGER NOT NULL, volume_reverse INTEGER NOT NULL,
            cars INTEGER, small_trucks INTEGER, medium_trucks INTEGER,
            large_trucks INTEGER, road_trains INTEGER, buses INTEGER, motorcycles INTEGER,
            speed_direct REAL, speed_reverse REAL, load_direct REAL, load_reverse REAL,
            state TEXT NOT NULL, imputation_method TEXT,
            PRIMARY KEY (sensor_id, ts)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS anomalies (
            id TEXT PRIMARY KEY, sensor_id TEXT NOT NULL, starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL, category TEXT NOT NULL, type TEXT NOT NULL,
            detector TEXT NOT NULL, level TEXT NOT NULL, metric TEXT NOT NULL,
            actual REAL, expected REAL, deviation_pct REAL, score REAL,
            is_mega INTEGER NOT NULL, event_id TEXT, description TEXT
        )
    """)
    db.commit()


def upsert_sensors(db: libsql.Connection, sensors: list[dict]) -> None:
    for s in sensors:
        db.execute(
            """INSERT OR REPLACE INTO sensors
               (id, road, road_name, name, km, lat, lon, directions_direct, directions_reverse)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                s["id"],
                s["road"],
                s["road_name"],
                s["name"],
                s["km"],
                s["lat"],
                s["lon"],
                s["directions"]["direct"],
                s["directions"]["reverse"],
            ),
        )
    db.commit()


def upsert_series(db: libsql.Connection, rows: list[dict]) -> None:
    for r in rows:
        db.execute(
            """INSERT OR REPLACE INTO series
               (sensor_id, ts, volume, volume_direct, volume_reverse, cars, small_trucks,
                medium_trucks, large_trucks, road_trains, buses, motorcycles,
                speed_direct, speed_reverse, load_direct, load_reverse, state, imputation_method)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["sensor_id"],
                r["ts"],
                int(r["volume"]),
                int(r["volume_direct"]),
                int(r["volume_reverse"]),
                int(r["cars"]) if r["cars"] else None,
                int(r["small_trucks"]) if r["small_trucks"] else None,
                int(r["medium_trucks"]) if r["medium_trucks"] else None,
                int(r["large_trucks"]) if r["large_trucks"] else None,
                int(r["road_trains"]) if r["road_trains"] else None,
                int(r["buses"]) if r["buses"] else None,
                int(r["motorcycles"]) if r["motorcycles"] else None,
                float(r["speed_direct"]) if r["speed_direct"] else None,
                float(r["speed_reverse"]) if r["speed_reverse"] else None,
                float(r["load_direct"]) if r["load_direct"] else None,
                float(r["load_reverse"]) if r["load_reverse"] else None,
                r["state"],
                r["imputation_method"] if r["imputation_method"] else None,
            ),
        )
    db.commit()


def upsert_anomalies(db: libsql.Connection, anomalies: list[dict]) -> None:
    for a in anomalies:
        db.execute(
            """INSERT OR REPLACE INTO anomalies
               (id, sensor_id, starts_at, ends_at, category, type, detector, level,
                metric, actual, expected, deviation_pct, score, is_mega, event_id, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                a["id"],
                a["sensor_id"],
                a["starts_at"],
                a["ends_at"],
                a["category"],
                a["type"],
                a["detector"],
                a["level"],
                a["metric"],
                a["actual"],
                a["expected"],
                a["deviation_pct"],
                a["score"],
                int(a["is_mega"]),
                a["event_id"],
                a["description"],
            ),
        )
    db.commit()
