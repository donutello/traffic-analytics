import libsql
from fastapi import HTTPException

from backend.anomalies.repositories.a134 import get_anomalies, get_anomaly_by_id
from contract.models import Anomaly


def get_a134_anomalies(
    db: libsql.Connection,
    sensor_id: str | None = None,
    level: str | None = None,
    category: str | None = None,
) -> list[Anomaly]:
    return [Anomaly(**data) for data in get_anomalies(db, sensor_id, level, category)]


def get_a134_anomaly(db: libsql.Connection, anomaly_id: str) -> Anomaly:
    data = get_anomaly_by_id(db, anomaly_id)
    if not data:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return Anomaly(**data)
