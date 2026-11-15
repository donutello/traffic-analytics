"""Import one road's contract files into the database: validate → transform → one transaction.

The command line is backend/load.py; the SQL is in backend/importer/repositories.py.
"""

from datetime import datetime
from pathlib import Path

import libsql

from backend.common.cache import clear as clear_response_cache
from backend.common.periods import MOSCOW_TZ, TIME_FORMAT
from backend.db import connect, ensure_schema
from backend.importer import repositories
from contract.validate import MAX_ERRORS_PER_FILE, OUTPUT, RoadOutput, read_road


def msk(value: datetime) -> str:
    """Contract time (ISO with an offset) to naive Moscow text, see backend/schema.sql."""
    return value.astimezone(MOSCOW_TZ).strftime(TIME_FORMAT)


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
        repositories.reset_road(db, road)
        repositories.insert_sensors(db, sensor_rows(out, road))
        repositories.insert_measurements(db, measurement_rows(out))
        repositories.insert_events(db, event_rows(out, road))
        repositories.insert_anomalies(db, anomaly_rows(out, road))
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
    clear_response_cache()  # the answers above changed, the cache may not keep old ones
    return 1 if failed else 0
