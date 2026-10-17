"""The data contract: what a road module writes to analysis/output/<road>/.

These models are the single source of truth. docs/contract.md explains them in plain words.
Status: draft v0, to be confirmed by the contract owners (see docs/contract.md).
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field


def start_of_hour(value: datetime) -> datetime:
    if (value.minute, value.second, value.microsecond) != (0, 0, 0):
        raise ValueError("must be the start of an hour")
    return value


Hour = Annotated[AwareDatetime, AfterValidator(start_of_hour)]
"""ISO 8601 time with an offset, always the start of an hour: 2025-03-08T10:00:00+03:00."""

Id = Annotated[str, Field(pattern=r"^_?[a-z0-9]+-[a-z0-9-]+$")]
"""Every id starts with the road code and a dash: a134-km12, a134-0001."""

Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
"""A machine-readable name in snake_case: volume_drop, amplitude."""

Text = Annotated[str, Field(min_length=1)]
Count = Annotated[int, Field(ge=0)]
Percent = Annotated[float, Field(ge=0, le=100)]
Speed = Annotated[float, Field(ge=0)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Directions(Contract):
    direct: Text
    reverse: Text


class Sensor(Contract):
    id: Id
    name: Text
    km: Annotated[float, Field(ge=0)]
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]
    directions: Directions


class Road(Contract):
    """sensors.json: the road section and its sensors."""

    road: Annotated[str, Field(pattern=r"^_?[a-z0-9]+$")]
    road_name: Text
    sensors: Annotated[list[Sensor], Field(min_length=1)]


class SeriesRow(Contract):
    """One line of series.csv: one hour of one sensor. Columns go in exactly this order."""

    sensor_id: Id
    ts: Hour
    volume: Count
    volume_direct: Count
    volume_reverse: Count
    cars: Count | None
    small_trucks: Count | None
    medium_trucks: Count | None
    large_trucks: Count | None
    road_trains: Count | None
    buses: Count | None
    motorcycles: Count | None
    speed_direct: Speed | None
    speed_reverse: Speed | None
    load_direct: Percent | None
    load_reverse: Percent | None
    state: Literal["normal", "anomaly", "imputed"]
    imputation_method: Literal["interpolation", "profile"] | None


SERIES_COLUMNS = list(SeriesRow.model_fields)


class Anomaly(Contract):
    """One item of anomalies.json (ours) or corporate_anomalies.json (the customer's system)."""

    id: Id
    sensor_id: Id
    starts_at: Hour
    ends_at: Hour
    category: Literal["traffic", "technical"]
    type: Code
    detector: Code
    level: Literal["low", "medium", "high", "critical"]
    metric: Code
    actual: float | None
    expected: float | None
    deviation_pct: float | None
    score: Annotated[float, Field(ge=0)] | None
    is_mega: bool
    event_id: Id | None
    description: str | None


class Event(Contract):
    """One item of events.json: an outside event that explains anomalies."""

    id: Id
    date: date
    category: Literal["accident", "roadworks", "weather", "holiday", "outage", "other"]
    title: Text
    description: str | None
    source_url: Annotated[str, Field(pattern=r"^https?://")]
