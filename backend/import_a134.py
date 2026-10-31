"""Import A-134 analysis data into Turso database."""

import csv
import json
from pathlib import Path

from backend.db import connect

DATA_DIR = Path(__file__).parent.parent / "analysis" / "output" / "a134"


def create_tables(db):
    """Create tables if they don't exist."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS sensors (
            id TEXT PRIMARY KEY,
            road TEXT NOT NULL,
            road_name TEXT NOT NULL,
            name TEXT NOT NULL,
            km REAL NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            directions_direct TEXT NOT NULL,
            directions_reverse TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS series (
            sensor_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            volume INTEGER NOT NULL,
            volume_direct INTEGER NOT NULL,
            volume_reverse INTEGER NOT NULL,
            cars INTEGER,
            small_trucks INTEGER,
            medium_trucks INTEGER,
            large_trucks INTEGER,
            road_trains INTEGER,
            buses INTEGER,
            motorcycles INTEGER,
            speed_direct REAL,
            speed_reverse REAL,
            load_direct REAL,
            load_reverse REAL,
            state TEXT NOT NULL,
            imputation_method TEXT,
            PRIMARY KEY (sensor_id, ts)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS anomalies (
            id TEXT PRIMARY KEY,
            sensor_id TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            category TEXT NOT NULL,
            type TEXT NOT NULL,
            detector TEXT NOT NULL,
            level TEXT NOT NULL,
            metric TEXT NOT NULL,
            actual REAL,
            expected REAL,
            deviation_pct REAL,
            score REAL,
            is_mega INTEGER NOT NULL,
            event_id TEXT,
            description TEXT
        )
    """)

    db.commit()


def import_sensors(db):
    """Import sensors.json."""
    sensors_file = DATA_DIR / "sensors.json"
    if not sensors_file.exists():
        print(f"Warning: {sensors_file} not found")
        return

    with open(sensors_file, encoding="utf-8") as f:
        data = json.load(f)

    road = data["road"]
    road_name = data["road_name"]

    for sensor in data["sensors"]:
        db.execute(
            """INSERT OR REPLACE INTO sensors 
               (id, road, road_name, name, km, lat, lon, directions_direct, directions_reverse)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sensor["id"],
                road,
                road_name,
                sensor["name"],
                sensor["km"],
                sensor["lat"],
                sensor["lon"],
                sensor["directions"]["direct"],
                sensor["directions"]["reverse"],
            ),
        )

    db.commit()
    print(f"Imported {len(data['sensors'])} sensors")


def import_series(db):
    """Import series.csv."""
    series_file = DATA_DIR / "series.csv"
    if not series_file.exists():
        print(f"Warning: {series_file} not found")
        return

    with open(series_file, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            db.execute(
                """INSERT OR REPLACE INTO series 
                   (sensor_id, ts, volume, volume_direct, volume_reverse,
                    cars, small_trucks, medium_trucks, large_trucks, road_trains,
                    buses, motorcycles, speed_direct, speed_reverse,
                    load_direct, load_reverse, state, imputation_method)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["sensor_id"],
                    row["ts"],
                    int(row["volume"]),
                    int(row["volume_direct"]),
                    int(row["volume_reverse"]),
                    int(row["cars"]) if row["cars"] else None,
                    int(row["small_trucks"]) if row["small_trucks"] else None,
                    int(row["medium_trucks"]) if row["medium_trucks"] else None,
                    int(row["large_trucks"]) if row["large_trucks"] else None,
                    int(row["road_trains"]) if row["road_trains"] else None,
                    int(row["buses"]) if row["buses"] else None,
                    int(row["motorcycles"]) if row["motorcycles"] else None,
                    float(row["speed_direct"]) if row["speed_direct"] else None,
                    float(row["speed_reverse"]) if row["speed_reverse"] else None,
                    float(row["load_direct"]) if row["load_direct"] else None,
                    float(row["load_reverse"]) if row["load_reverse"] else None,
                    row["state"],
                    row["imputation_method"] if row["imputation_method"] else None,
                ),
            )
            count += 1

    db.commit()
    print(f"Imported {count} series rows")


def import_anomalies(db):
    """Import anomalies.json."""
    anomalies_file = DATA_DIR / "anomalies.json"
    if not anomalies_file.exists():
        print(f"Warning: {anomalies_file} not found")
        return

    with open(anomalies_file, encoding="utf-8") as f:
        anomalies = json.load(f)

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
    print(f"Imported {len(anomalies)} anomalies")


def main():
    """Run all imports."""
    print(f"Importing data from {DATA_DIR}")
    db = connect()

    try:
        create_tables(db)
        import_sensors(db)
        import_series(db)
        import_anomalies(db)
        print("Import completed successfully")
    except Exception as e:
        print(f"Import failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
