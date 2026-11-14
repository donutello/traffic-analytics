from typing import Annotated

import libsql
from fastapi import APIRouter, Depends

from backend.db import get_db
from backend.sensors.services.a134 import get_a134_sensor, get_a134_sensors
from contract.models import Sensor

router = APIRouter(prefix="/api/v1/a134", tags=["A-134 Sensors"])


@router.get("/sensors", response_model=list[Sensor])
def list_sensors(db: Annotated[libsql.Connection, Depends(get_db)]) -> list[Sensor]:
    return get_a134_sensors(db)


@router.get("/sensors/{sensor_id}", response_model=Sensor)
def get_sensor(sensor_id: str, db: Annotated[libsql.Connection, Depends(get_db)]) -> Sensor:
    return get_a134_sensor(db, sensor_id)
