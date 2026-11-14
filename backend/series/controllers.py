"""GET /api/series."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.common.periods import parse_bound
from backend.common.query import Db, FromParam, ToParam
from backend.series import services

router = APIRouter(prefix="/api", tags=["series"])

State = Literal["normal", "anomaly", "imputed"]
Granularity = Literal["hour", "day", "week"]


class SeriesPoint(BaseModel):
    ts: str = Field(description="hour: contract time of the hour start; day/week: the Moscow date")
    label: str = Field(description="short axis label in Russian, e.g. «8 марта» or «09:00»")
    volume: int = Field(description="hour: vehicles per hour; day/week: the mean of the hours")
    state: State


class SeriesOut(BaseModel):
    points: list[SeriesPoint]


@router.get("/series", response_model=SeriesOut)
def get_series(
    db: Db,
    sensor: str,
    granularity: Granularity = "hour",
    start: FromParam = None,
    end: ToParam = None,
) -> dict:
    return {
        "points": services.points(
            db, sensor, granularity, parse_bound(start, end=False), parse_bound(end, end=True)
        )
    }
