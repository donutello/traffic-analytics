"""API endpoints for A-134 road section."""

from typing import Annotated

import libsql
from fastapi import APIRouter, Depends, Query

from backend.db import get_db
from backend.services.a134_service import (
    get_a134_anomalies,
    get_a134_anomaly,
    get_a134_sensor,
    get_a134_sensors,
    get_a134_series,
)
from contract.models import Anomaly, Sensor, SeriesRow

router = APIRouter(prefix="/api/v1/a134", tags=["A-134"])


# ========== SENSORS ==========


@router.get("/sensors", response_model=list[Sensor])
def list_sensors(db: Annotated[libsql.Connection, Depends(get_db)]) -> list[Sensor]:
    """Get all sensors for A-134."""
    return get_a134_sensors(db)


@router.get("/sensors/{sensor_id}", response_model=Sensor)
def get_sensor(sensor_id: str, db: Annotated[libsql.Connection, Depends(get_db)]) -> Sensor:
    """Get a specific sensor by ID."""
    return get_a134_sensor(db, sensor_id)


# ========== SERIES ==========


@router.get("/series", response_model=list[SeriesRow])
def list_series(
    db: Annotated[libsql.Connection, Depends(get_db)],
    sensor_id: str | None = Query(None, description="Filter by sensor ID"),
    limit: int = Query(100, ge=1, le=1000, description="Max rows to return"),
) -> list[SeriesRow]:
    """Get hourly series data for A-134."""
    return get_a134_series(db, sensor_id=sensor_id, limit=limit)


# ========== ANOMALIES ==========


@router.get("/anomalies", response_model=list[Anomaly])
def list_anomalies(
    db: Annotated[libsql.Connection, Depends(get_db)],
    sensor_id: str | None = Query(None, description="Filter by sensor ID"),
    level: str | None = Query(None, description="Filter by level"),
    category: str | None = Query(None, description="Filter by category"),
) -> list[Anomaly]:
    """Get all anomalies for A-134."""
    return get_a134_anomalies(db, sensor_id=sensor_id, level=level, category=category)


@router.get("/anomalies/{anomaly_id}", response_model=Anomaly)
def get_anomaly(anomaly_id: str, db: Annotated[libsql.Connection, Depends(get_db)]) -> Anomaly:
    """Get a specific anomaly by ID."""
    return get_a134_anomaly(db, anomaly_id)
