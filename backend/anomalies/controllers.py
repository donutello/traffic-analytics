"""GET /api/anomalies and GET /api/anomalies/{id}."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.anomalies import services
from backend.common.periods import parse_bound
from backend.common.query import Db, FromParam, ToParam

router = APIRouter(prefix="/api", tags=["anomalies"])

Level = Literal["low", "medium", "high", "critical"]
Source = Literal["ours", "corporate"]


class AnomalyItem(BaseModel):
    id: str
    sensor_id: str
    sensor_name: str
    starts_at: str
    ends_at: str
    starts_label: str
    ends_label: str
    duration_label: str
    days_ago: int
    category: str
    category_label: str
    type: str
    type_label: str
    detector: str
    level: Level
    level_label: str
    metric: str
    actual: float | None
    expected: float | None
    deviation_pct: float | None
    score: float | None
    is_mega: bool
    event_id: str | None
    description: str | None
    source: Source
    source_label: str


class EventItem(BaseModel):
    id: str
    date: str
    date_label: str
    category: str
    category_label: str
    title: str
    description: str | None
    source_url: str


class AnomalyDetail(AnomalyItem):
    event: EventItem | None = Field(description="the linked event with its description and link")


class AnomalyCounts(BaseModel):
    ours: int
    corporate: int


class AnomalyListOut(BaseModel):
    counts: AnomalyCounts = Field(description="items in this response, by source")
    anomalies: list[AnomalyItem]


@router.get("/anomalies", response_model=AnomalyListOut)
def get_anomalies(
    db: Db,
    road: str | None = None,
    sensor: str | None = None,
    start: FromParam = None,
    end: ToParam = None,
    anomaly_type: Annotated[str | None, Query(alias="type")] = None,
    source: Source | None = None,
    level: Level | None = None,
) -> dict:
    """The side panel: our and the corporate system's findings, ours+corporate in one list."""
    return services.query(
        db,
        road,
        sensor,
        anomaly_type,
        source,
        level,
        parse_bound(start, False),
        parse_bound(end, True),
    )


@router.get("/anomalies/{anomaly_id}", response_model=AnomalyDetail)
def get_anomaly(db: Db, anomaly_id: str) -> dict:
    return services.detail(db, anomaly_id)
