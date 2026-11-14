"""Business logic layer for A-134 import."""

import csv
import json
from pathlib import Path

from backend.db import connect
from backend.importer.repositories.a134 import (
    create_tables,
    upsert_anomalies,
    upsert_sensors,
    upsert_series,
)

DATA_DIR = Path(__file__).parent.parent.parent.parent / "analysis" / "output" / "a134"


def _load_sensors() -> list[dict]:
    sensors_file = DATA_DIR / "sensors.json"
    if not sensors_file.exists():
        print(f"Warning: {sensors_file} not found")
        return []
    with open(sensors_file, encoding="utf-8") as f:
        data = json.load(f)
    for sensor in data["sensors"]:
        sensor["road"] = data["road"]
        sensor["road_name"] = data["road_name"]
    return data["sensors"]


def _load_series() -> list[dict]:
    series_file = DATA_DIR / "series.csv"
    if not series_file.exists():
        print(f"Warning: {series_file} not found")
        return []
    with open(series_file, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_anomalies() -> list[dict]:
    anomalies_file = DATA_DIR / "anomalies.json"
    if not anomalies_file.exists():
        print(f"Warning: {anomalies_file} not found")
        return []
    with open(anomalies_file, encoding="utf-8") as f:
        return json.load(f)


def run_import() -> None:
    print(f"Importing data from {DATA_DIR}")
    db = connect()
    try:
        create_tables(db)

        sensors = _load_sensors()
        upsert_sensors(db, sensors)
        print(f"Imported {len(sensors)} sensors")

        series_rows = _load_series()
        upsert_series(db, series_rows)
        print(f"Imported {len(series_rows)} series rows")

        anomalies = _load_anomalies()
        upsert_anomalies(db, anomalies)
        print(f"Imported {len(anomalies)} anomalies")

        print("Import completed successfully")
    except Exception as e:
        print(f"Import failed: {e}")
        raise
    finally:
        db.close()
