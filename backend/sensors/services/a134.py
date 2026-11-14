import libsql
from fastapi import HTTPException

from backend.sensors.repositories.a134 import get_sensor_by_id, get_sensors
from contract.models import Sensor


def get_a134_sensors(db: libsql.Connection) -> list[Sensor]:
    return [Sensor(**data) for data in get_sensors(db)]


def get_a134_sensor(db: libsql.Connection, sensor_id: str) -> Sensor:
    data = get_sensor_by_id(db, sensor_id)
    if not data:
        raise HTTPException(status_code=404, detail="Sensor not found")
    return Sensor(**data)
