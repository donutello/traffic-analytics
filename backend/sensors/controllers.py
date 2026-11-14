"""GET /api/sensors."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.common.periods import parse_bound
from backend.common.query import Db, FromParam, ToParam
from backend.sensors import services

router = APIRouter(prefix="/api", tags=["sensors"])


class Directions(BaseModel):
    direct: str
    reverse: str


class SensorProperties(BaseModel):
    id: str
    name: str
    road: str
    km: float
    anomaly_count: int = Field(description="ours + corporate anomalies touching the period")
    is_mega: bool = Field(description="any is_mega anomaly of this sensor (of any period)")
    directions: Directions


class GeoPoint(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: list[float] = Field(description="lon, lat (WGS 84)")


class SensorFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoPoint
    properties: SensorProperties


class SensorsOut(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[SensorFeature]


@router.get("/sensors", response_model=SensorsOut)
def get_sensors(
    db: Db,
    road: str | None = None,
    start: FromParam = None,
    end: ToParam = None,
) -> dict:
    """The map: every sensor with its anomaly count in the period and mega flag."""
    return {
        "features": services.features(db, road, parse_bound(start, False), parse_bound(end, True))
    }
