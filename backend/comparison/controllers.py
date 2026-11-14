"""GET /api/comparison."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.anomalies.controllers import AnomalyItem
from backend.common.periods import parse_bound
from backend.common.query import Db, FromParam, ToParam
from backend.comparison import services

router = APIRouter(prefix="/api", tags=["comparison"])


class ComparisonPair(BaseModel):
    ours: AnomalyItem
    corporate: AnomalyItem


class ComparisonTotals(BaseModel):
    ours: int = Field(description="our findings whose interval touches the period")
    corporate: int = Field(description="the corporate system's findings touching the period")
    both: int = Field(description="matching pairs (one finding can make several pairs)")
    only_ours: int = Field(description="our findings that no corporate finding overlaps")
    only_corporate: int = Field(description="corporate findings that no finding of ours overlaps")


class ComparisonShares(BaseModel):
    ours_found_pct: float = Field(description="% of our findings the corporate system also found")
    corporate_found_pct: float = Field(
        description="% of the corporate findings our algorithm also found"
    )


class RoadComparison(BaseModel):
    road: str
    road_name: str
    totals: ComparisonTotals = Field(description="counted from the three lists below")
    shares: ComparisonShares
    both_found: list[ComparisonPair] = Field(description="the matched findings side by side")
    only_ours: list[AnomalyItem]
    only_corporate: list[AnomalyItem]


class ComparisonOut(BaseModel):
    """FR4 (issue #7): where our logic and the corporate system agree and where they differ.

    Matching rule: findings on the same sensor whose half-open intervals [starts_at, ends_at)
    overlap match. The match is none-or-many, not one-to-one: a finding counts as mutually found
    when ANY finding of the other side on its sensor overlaps it, and both_found then lists every
    such pair.
    """

    roads: list[RoadComparison] = Field(
        description="one comparison per road; every road when road= is empty"
    )
    totals: ComparisonTotals = Field(description="all roads together")
    shares: ComparisonShares = Field(description="over all roads together")


@router.get("/comparison", response_model=ComparisonOut)
def get_comparison(
    db: Db,
    road: str | None = None,
    start: FromParam = None,
    end: ToParam = None,
) -> dict:
    """FR4: our findings against the corporate system's over a period (issue #7)."""
    return services.comparison(db, road, parse_bound(start, False), parse_bound(end, True))
