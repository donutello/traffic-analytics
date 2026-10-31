"""API endpoints for A-134 road section."""

from typing import Annotated

import libsql
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.db import get_db
from contract.models import Anomaly, Sensor, SeriesRow

router = APIRouter(prefix="/api/v1/a134", tags=["A-134"])


# ========== SENSORS ==========


@router.get("/sensors", response_model=list[Sensor])
def list_sensors(db: Annotated[libsql.Connection, Depends(get_db)]) -> list[Sensor]:
    """Get all sensors for A-134."""
    result = db.execute(
        """SELECT id, name, km, lat, lon,
                  directions_direct, directions_reverse
           FROM sensors WHERE road = 'a134'"""
    )
    rows = result.fetchall()

    return [
        Sensor(
            id=row[0],
            name=row[1],
            km=row[2],
            lat=row[3],
            lon=row[4],
            directions={"direct": row[5], "reverse": row[6]},
        )
        for row in rows
    ]


@router.get("/sensors/{sensor_id}", response_model=Sensor)
def get_sensor(sensor_id: str, db: Annotated[libsql.Connection, Depends(get_db)]) -> Sensor:
    """Get a specific sensor by ID."""
    result = db.execute(
        """SELECT id, name, km, lat, lon,
                  directions_direct, directions_reverse
           FROM sensors WHERE id = ? AND road = 'a134'""",
        (sensor_id,),
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Sensor not found")

    return Sensor(
        id=row[0],
        name=row[1],
        km=row[2],
        lat=row[3],
        lon=row[4],
        directions={"direct": row[5], "reverse": row[6]},
    )


# ========== SERIES ==========


@router.get("/series", response_model=list[SeriesRow])
def list_series(
    db: Annotated[libsql.Connection, Depends(get_db)],
    sensor_id: str | None = Query(None, description="Filter by sensor ID"),
    limit: int = Query(100, ge=1, le=1000, description="Max rows to return"),
) -> list[SeriesRow]:
    """Get hourly series data for A-134."""
    query = """
        SELECT sensor_id, ts, volume, volume_direct, volume_reverse,
               cars, small_trucks, medium_trucks, large_trucks, road_trains,
               buses, motorcycles, speed_direct, speed_reverse,
               load_direct, load_reverse, state, imputation_method
        FROM series
        WHERE sensor_id LIKE 'a134-%'
    """
    params: list[str] = []

    if sensor_id:
        query += " AND sensor_id = ?"
        params.append(sensor_id)

    query += " ORDER BY ts DESC LIMIT ?"
    params.append(str(limit))

    result = db.execute(query, params)
    rows = result.fetchall()

    return [
        SeriesRow(
            sensor_id=row[0],
            ts=row[1],
            volume=row[2],
            volume_direct=row[3],
            volume_reverse=row[4],
            cars=row[5],
            small_trucks=row[6],
            medium_trucks=row[7],
            large_trucks=row[8],
            road_trains=row[9],
            buses=row[10],
            motorcycles=row[11],
            speed_direct=row[12],
            speed_reverse=row[13],
            load_direct=row[14],
            load_reverse=row[15],
            state=row[16],
            imputation_method=row[17],
        )
        for row in rows
    ]


# ========== ANOMALIES ==========


@router.get("/anomalies", response_model=list[Anomaly])
def list_anomalies(
    db: Annotated[libsql.Connection, Depends(get_db)],
    sensor_id: str | None = Query(None, description="Filter by sensor ID"),
    level: str | None = Query(None, description="Filter by level"),
    category: str | None = Query(None, description="Filter by category"),
) -> list[Anomaly]:
    """Get all anomalies for A-134."""
    query = """
        SELECT id, sensor_id, starts_at, ends_at, category, type, detector,
               level, metric, actual, expected, deviation_pct, score,
               is_mega, event_id, description
        FROM anomalies
        WHERE id LIKE 'a134-%'
    """
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

    result = db.execute(query, params)
    rows = result.fetchall()

    return [
        Anomaly(
            id=row[0],
            sensor_id=row[1],
            starts_at=row[2],
            ends_at=row[3],
            category=row[4],
            type=row[5],
            detector=row[6],
            level=row[7],
            metric=row[8],
            actual=row[9],
            expected=row[10],
            deviation_pct=row[11],
            score=row[12],
            is_mega=bool(row[13]),
            event_id=row[14],
            description=row[15],
        )
        for row in rows
    ]


@router.get("/anomalies/{anomaly_id}", response_model=Anomaly)
def get_anomaly(anomaly_id: str, db: Annotated[libsql.Connection, Depends(get_db)]) -> Anomaly:
    """Get a specific anomaly by ID."""
    result = db.execute(
        """SELECT id, sensor_id, starts_at, ends_at, category, type,
                  detector, level, metric, actual, expected, deviation_pct,
                  score, is_mega, event_id, description
           FROM anomalies WHERE id = ? AND id LIKE 'a134-%'""",
        (anomaly_id,),
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Anomaly not found")

    return Anomaly(
        id=row[0],
        sensor_id=row[1],
        starts_at=row[2],
        ends_at=row[3],
        category=row[4],
        type=row[5],
        detector=row[6],
        level=row[7],
        metric=row[8],
        actual=row[9],
        expected=row[10],
        deviation_pct=row[11],
        score=row[12],
        is_mega=bool(row[13]),
        event_id=row[14],
        description=row[15],
    )
