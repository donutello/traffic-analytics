from typing import Annotated

import libsql
from fastapi import APIRouter, Depends, Query

from backend.anomalies.services.a134 import get_a134_anomalies, get_a134_anomaly
from backend.db import get_db
from contract.models import Anomaly

router = APIRouter(prefix="/api/v1/a134", tags=["A-134 Anomalies"])


@router.get("/anomalies", response_model=list[Anomaly])
def list_anomalies(
    db: Annotated[libsql.Connection, Depends(get_db)],
    sensor_id: str | None = Query(None, description="Filter by sensor ID"),
    level: str | None = Query(None, description="Filter by level"),
    category: str | None = Query(None, description="Filter by category"),
) -> list[Anomaly]:
    return get_a134_anomalies(db, sensor_id=sensor_id, level=level, category=category)


@router.get("/anomalies/{anomaly_id}", response_model=Anomaly)
def get_anomaly(anomaly_id: str, db: Annotated[libsql.Connection, Depends(get_db)]) -> Anomaly:
    return get_a134_anomaly(db, anomaly_id)
