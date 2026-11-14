"""Business logic layer for A-134 endpoints."""

import libsql
from fastapi import HTTPException

from backend.repositories.sensor_repository import (
    get_sensor_by_id,
    get_sensors_by_road,
)
from contract.models import Sensor


def get_a134_sensors(db: libsql.Connection) -> list[Sensor]:
    """Возвращает список датчиков трассы А-134 в виде Pydantic-моделей."""
    raw_sensors = get_sensors_by_road(db, road="a134")

    return [
        Sensor(
            id=data["id"],
            name=data["name"],
            km=data["km"],
            lat=data["lat"],
            lon=data["lon"],
            directions={
                "direct": data["directions_direct"],
                "reverse": data["directions_reverse"],
            },
        )
        for data in raw_sensors
    ]


def get_a134_sensor(db: libsql.Connection, sensor_id: str) -> Sensor:
    """Возвращает один датчик А-134 по ID."""
    data = get_sensor_by_id(db, sensor_id=sensor_id, road="a134")

    if not data:
        raise HTTPException(status_code=404, detail="Sensor not found")

    return Sensor(
        id=data["id"],
        name=data["name"],
        km=data["km"],
        lat=data["lat"],
        lon=data["lon"],
        directions={
            "direct": data["directions_direct"],
            "reverse": data["directions_reverse"],
        },
    )


from backend.repositories.series_repository import get_series
from backend.repositories.anomaly_repository import get_anomalies, get_anomaly_by_id
from contract.models import SeriesRow, Anomaly


def get_a134_series(
    db: libsql.Connection,
    sensor_id: str | None = None,
    limit: int = 100,
) -> list[SeriesRow]:
    """Возвращает временные ряды для А-134 в виде Pydantic-моделей."""
    raw_series = get_series(db, sensor_id=sensor_id, limit=limit)

    return [
        SeriesRow(
            sensor_id=data["sensor_id"],
            ts=data["ts"],
            volume=data["volume"],
            volume_direct=data["volume_direct"],
            volume_reverse=data["volume_reverse"],
            cars=data["cars"],
            small_trucks=data["small_trucks"],
            medium_trucks=data["medium_trucks"],
            large_trucks=data["large_trucks"],
            road_trains=data["road_trains"],
            buses=data["buses"],
            motorcycles=data["motorcycles"],
            speed_direct=data["speed_direct"],
            speed_reverse=data["speed_reverse"],
            load_direct=data["load_direct"],
            load_reverse=data["load_reverse"],
            state=data["state"],
            imputation_method=data["imputation_method"],
        )
        for data in raw_series
    ]


def get_a134_anomalies(
    db: libsql.Connection,
    sensor_id: str | None = None,
    level: str | None = None,
    category: str | None = None,
) -> list[Anomaly]:
    """Возвращает аномалии для А-134 в виде Pydantic-моделей."""
    raw_anomalies = get_anomalies(db, sensor_id=sensor_id, level=level, category=category)

    return [
        Anomaly(
            id=data["id"],
            sensor_id=data["sensor_id"],
            starts_at=data["starts_at"],
            ends_at=data["ends_at"],
            category=data["category"],
            type=data["type"],
            detector=data["detector"],
            level=data["level"],
            metric=data["metric"],
            actual=data["actual"],
            expected=data["expected"],
            deviation_pct=data["deviation_pct"],
            score=data["score"],
            is_mega=data["is_mega"],
            event_id=data["event_id"],
            description=data["description"],
        )
        for data in raw_anomalies
    ]


def get_a134_anomaly(db: libsql.Connection, anomaly_id: str) -> Anomaly:
    """Возвращает одну аномалию А-134 по ID."""
    data = get_anomaly_by_id(db, anomaly_id=anomaly_id)

    if not data:
        raise HTTPException(status_code=404, detail="Anomaly not found")

    return Anomaly(
        id=data["id"],
        sensor_id=data["sensor_id"],
        starts_at=data["starts_at"],
        ends_at=data["ends_at"],
        category=data["category"],
        type=data["type"],
        detector=data["detector"],
        level=data["level"],
        metric=data["metric"],
        actual=data["actual"],
        expected=data["expected"],
        deviation_pct=data["deviation_pct"],
        score=data["score"],
        is_mega=data["is_mega"],
        event_id=data["event_id"],
        description=data["description"],
    )
