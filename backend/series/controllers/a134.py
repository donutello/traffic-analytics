from typing import Annotated

import libsql
from fastapi import APIRouter, Depends, Query

from backend.db import get_db
from backend.series.services.a134 import get_a134_series
from contract.models import SeriesRow

router = APIRouter(prefix="/api/v1/a134", tags=["A-134 Series"])


@router.get("/series", response_model=list[SeriesRow])
def list_series(
    db: Annotated[libsql.Connection, Depends(get_db)],
    sensor_id: str | None = Query(None, description="Filter by sensor ID"),
    limit: int = Query(100, ge=1, le=1000, description="Max rows to return"),
) -> list[SeriesRow]:
    return get_a134_series(db, sensor_id=sensor_id, limit=limit)
