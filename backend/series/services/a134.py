import libsql

from backend.series.repositories.a134 import get_series
from contract.models import SeriesRow


def get_a134_series(
    db: libsql.Connection, sensor_id: str | None = None, limit: int = 100
) -> list[SeriesRow]:
    return [SeriesRow(**data) for data in get_series(db, sensor_id, limit)]
