"""GET /api/meta."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.common.query import Db
from backend.meta import services

router = APIRouter(prefix="/api", tags=["meta"])


class RoadMeta(BaseModel):
    code: str
    name: str
    sensors: int


class PeriodOut(BaseModel):
    start: str | None = Field(alias="from")
    end: str | None = Field(alias="to")


class MetaOut(BaseModel):
    roads: list[RoadMeta] = Field(description="one entry per loaded road")
    period: PeriodOut = Field(description="first and last day with measurements")


@router.get("/meta", response_model=MetaOut)
def get_meta(db: Db) -> dict:
    return services.meta(db)
