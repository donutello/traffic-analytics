"""Import the road modules' results from analysis/output/ into the database.

    uv run python -m backend.load            # every road directory under analysis/output/
    uv run python -m backend.load _example   # one road by name

A road is read with contract.validate.read_road and loaded only when its files follow the
contract: errors are printed and nothing at all is loaded for that road. Loading a road
first deletes its old rows, so running the import twice changes nothing, and every road
is loaded inside one transaction: either all of its rows are in, or none.

corporate_anomalies.json is optional (read_road checks it only when the file is there).
When it is, its items are imported like ours, only with source='corporate'.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import libsql

from backend.db import connect, ensure_schema
from contract.validate import MAX_ERRORS_PER_FILE, OUTPUT, RoadOutput, read_road

MOSCOW = timezone(timedelta(hours=3))
"""Contract times are Moscow time: UTC+3, and Russia has no DST."""

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


def msk(value: datetime) -> str:
    """Contract time (ISO with an offset) to naive Moscow text, see backend/schema.sql."""
    return value.astimezone(MOSCOW).strftime("%Y-%m-%d %H:%M:%S")


def sensor_rows(out: RoadOutput, road: str) -> list[tuple]:
    return [
        (
            s.id,
            road,
            out.road.road_name,
            s.name,
            s.km,
            s.lat,
            s.lon,
            s.directions.direct,
            s.directions.reverse,
        )
        for s in out.road.sensors
    ]


def measurement_rows(out: RoadOutput) -> list[tuple]:
    return [
        (
            r.sensor_id,
            msk(r.ts),
            r.volume,
            r.volume_direct,
            r.volume_reverse,
            r.cars,
            r.small_trucks,
            r.medium_trucks,
            r.large_trucks,
            r.road_trains,
            r.buses,
            r.motorcycles,
            r.speed_direct,
            r.speed_reverse,
            r.load_direct,
            r.load_reverse,
            r.state,
            r.imputation_method,
        )
        for r in out.series
    ]


def anomaly_rows(out: RoadOutput, road: str) -> list[tuple]:
    """Both anomaly files in one table; only source tells them apart."""
    rows = []
    for source, items in (("ours", out.anomalies), ("corporate", out.corporate_anomalies)):
        for a in items:
            rows.append(
                (
                    a.id,
                    source,
                    road,
                    a.sensor_id,
                    msk(a.starts_at),
                    msk(a.ends_at),
                    a.category,
                    a.type,
                    a.detector,
                    a.level,
                    a.metric,
                    a.actual,
                    a.expected,
                    a.deviation_pct,
                    a.score,
                    int(a.is_mega),
                    a.event_id,
                    a.description,
                )
            )
    return rows


def event_rows(out: RoadOutput, road: str) -> list[tuple]:
    return [
        (e.id, road, e.date.isoformat(), e.category, e.title, e.description, e.source_url)
        for e in out.events
    ]


def print_errors(directory: Path, errors: dict[str, list[tuple[str, str]]]) -> None:
    """Show contract errors the same way as contract.validate does."""
    for name, found in errors.items():
        for where, message in found[:MAX_ERRORS_PER_FILE]:
            print(f"{directory / name}: {where}: {message}")
        if len(found) > MAX_ERRORS_PER_FILE:
            print(f"{directory / name}: ... and {len(found) - MAX_ERRORS_PER_FILE} more")


def load_road(db: libsql.Connection, directory: Path) -> RoadOutput | None:
    """Load one road in one transaction; None (errors printed) if its files are invalid."""
    out = read_road(directory)
    if out.errors:
        print_errors(directory, out.errors)
        return None
    road = out.road.road
    db.execute("BEGIN")
    try:
        for statement in DELETE_ROAD:
            db.execute(statement, (road,))
        db.executemany(INSERT_SENSOR, sensor_rows(out, road))
        db.executemany(INSERT_MEASUREMENT, measurement_rows(out))
        db.executemany(INSERT_EVENT, event_rows(out, road))
        db.executemany(INSERT_ANOMALY, anomaly_rows(out, road))
    except Exception:
        db.rollback()
        raise
    db.commit()
    return out


def print_summary(out: RoadOutput) -> None:
    ours, corporate = len(out.anomalies), len(out.corporate_anomalies)
    print(
        f"{out.road.road}: {len(out.road.sensors)} sensors, {len(out.series)} measurements, "
        f"{ours + corporate} anomalies ({ours} ours + {corporate} corporate), "
        f"{len(out.events)} events"
    )


def main(argv: list[str], db: libsql.Connection | None = None) -> int:
    """Roads are names under analysis/output/; an open connection can be passed in."""
    if argv:
        directories = [OUTPUT / arg for arg in argv]
    else:
        directories = sorted(p for p in OUTPUT.iterdir() if p.is_dir()) if OUTPUT.is_dir() else []
    if not directories:
        print(f"nothing to load from {OUTPUT}")
        return 0

    own_db = db is None
    if own_db:
        db = connect()
    try:
        ensure_schema(db)
        failed = False
        for directory in directories:
            if not directory.is_dir():
                print(f"{directory}: not a directory")
                failed = True
                continue
            out = load_road(db, directory)
            if out is None:
                failed = True
            else:
                print_summary(out)
    finally:
        if own_db:
            db.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
