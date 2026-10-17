"""Check a road's output against the data contract (docs/contract.md).

    uv run python -m contract.validate [analysis/output/<road> ...]

Without arguments, checks every directory in analysis/output/. Exits with 1 if anything fails.
"""

import csv
import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ValidationError

from contract.models import SERIES_COLUMNS, Anomaly, Event, Road, SeriesRow

OUTPUT = Path(__file__).parent.parent / "analysis" / "output"

REQUIRED = ("sensors.json", "series.csv", "anomalies.json")
OPTIONAL = ("events.json", "corporate_anomalies.json")
MAX_ERRORS_PER_FILE = 20

Error = tuple[str, str]  # (where in the file, what is wrong)


@dataclass
class RoadOutput:
    """Everything one road module produced, already checked against the contract."""

    road: Road | None = None
    series: list[SeriesRow] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    corporate_anomalies: list[Anomaly] = field(default_factory=list)
    errors: dict[str, list[Error]] = field(default_factory=dict)


def pydantic_errors(error: ValidationError, prefix: str = "") -> Iterator[Error]:
    for e in error.errors():
        path = "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in e["loc"])
        yield prefix + path.lstrip(".") or "/", e["msg"]


def check_ids(items: list[BaseModel], road: str) -> Iterator[Error]:
    seen = set()
    for i, item in enumerate(items):
        if not item.id.startswith(f"{road}-"):
            yield f"[{i}].id", f"{item.id!r} must start with {road + '-'!r}"
        if item.id in seen:
            yield f"[{i}].id", f"duplicate id {item.id!r}"
        seen.add(item.id)


def read_json(path: Path, errors: list[Error]) -> object:
    try:
        return json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        errors.append(("/", f"not valid JSON: {e}"))
        return None


def read_list[T: BaseModel](path: Path, model: type[T], errors: list[Error]) -> list[T]:
    """Check every item on its own, so one bad item doesn't hide the problems of the others."""
    data = read_json(path, errors)
    if data is None:
        return []
    if not isinstance(data, list):
        errors.append(("/", "must be a list"))
        return []
    items = []
    for i, item in enumerate(data):
        try:
            items.append(model.model_validate(item))
        except ValidationError as e:
            errors.extend(pydantic_errors(e, prefix=f"[{i}]."))
    return items


def read_series(path: Path, sensor_ids: set[str] | None, errors: list[Error]) -> list[SeriesRow]:
    rows = []
    seen = set()
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        if next(reader, None) != SERIES_COLUMNS:
            errors.append(("line 1", f"header must be exactly: {','.join(SERIES_COLUMNS)}"))
            return rows
        for values in reader:
            line = f"line {reader.line_num}"
            if len(values) != len(SERIES_COLUMNS):
                errors.append((line, f"expected {len(SERIES_COLUMNS)} cells, got {len(values)}"))
                continue
            # An empty cell means "no value".
            cells = {col: v or None for col, v in zip(SERIES_COLUMNS, values, strict=True)}
            try:
                row = SeriesRow.model_validate(cells)
            except ValidationError as e:
                errors.extend(pydantic_errors(e, prefix=f"{line}: "))
                continue
            if sensor_ids is not None and row.sensor_id not in sensor_ids:
                errors.append((line, f"unknown sensor_id {row.sensor_id!r}"))
            if (row.sensor_id, row.ts) in seen:
                errors.append((line, f"duplicate hour {row.ts.isoformat()} for {row.sensor_id}"))
            seen.add((row.sensor_id, row.ts))
            if (row.state == "imputed") != (row.imputation_method is not None):
                errors.append((line, "imputation_method is set if and only if state is imputed"))
            rows.append(row)
    return rows


def read_road(directory: Path) -> RoadOutput:
    """Read and check one road directory. `errors` is empty when it follows the contract."""
    out = RoadOutput()
    road = directory.name
    files = {p.name for p in directory.iterdir() if not p.name.startswith(".")}

    def errors(name: str) -> list[Error]:
        return out.errors.setdefault(name, [])

    for name in sorted(files - set(REQUIRED) - set(OPTIONAL)):
        errors(name).append(("/", "unexpected file"))
    for name in REQUIRED:
        if name not in files:
            errors(name).append(("/", "required file is missing"))

    if "sensors.json" in files:
        data = read_json(directory / "sensors.json", errors("sensors.json"))
        try:
            out.road = None if data is None else Road.model_validate(data)
        except ValidationError as e:
            errors("sensors.json").extend(pydantic_errors(e))
    if out.road:
        if out.road.road != road:
            errors("sensors.json").append(
                ("road", f"{out.road.road!r} must equal the directory name {road!r}")
            )
        errors("sensors.json").extend(
            (f"sensors{where}", msg) for where, msg in check_ids(out.road.sensors, road)
        )
    sensor_ids = {s.id for s in out.road.sensors} if out.road else None

    if "events.json" in files:
        out.events = read_list(directory / "events.json", Event, errors("events.json"))
        errors("events.json").extend(check_ids(out.events, road))
    event_ids = {e.id for e in out.events}

    for name in ("anomalies.json", "corporate_anomalies.json"):
        if name not in files:
            continue
        anomalies = read_list(directory / name, Anomaly, errors(name))
        errors(name).extend(check_ids(anomalies, road))
        for i, a in enumerate(anomalies):
            if sensor_ids is not None and a.sensor_id not in sensor_ids:
                errors(name).append((f"[{i}].sensor_id", f"unknown sensor_id {a.sensor_id!r}"))
            if a.ends_at <= a.starts_at:
                errors(name).append((f"[{i}].ends_at", "must be later than starts_at"))
            if a.event_id is not None and a.event_id not in event_ids:
                errors(name).append(
                    (f"[{i}].event_id", f"unknown event_id {a.event_id!r} (not in events.json)")
                )
        setattr(out, name.removesuffix(".json"), anomalies)

    if "series.csv" in files:
        out.series = read_series(directory / "series.csv", sensor_ids, errors("series.csv"))

    out.errors = {name: found for name, found in out.errors.items() if found}
    return out


def shown(path: Path) -> Path:
    try:
        return path.resolve().relative_to(Path.cwd())
    except ValueError:
        return path


def main(argv: list[str]) -> int:
    directories = [Path(a) for a in argv] or sorted(p for p in OUTPUT.iterdir() if p.is_dir())
    if not directories:
        print(f"nothing to check in {OUTPUT}")
        return 0

    failed = False
    for directory in map(shown, directories):
        if not directory.is_dir():
            print(f"{directory}: not a directory")
            failed = True
            continue
        errors = read_road(directory).errors
        if not errors:
            print(f"{directory}: ok")
            continue
        failed = True
        for name, found in errors.items():
            for where, message in found[:MAX_ERRORS_PER_FILE]:
                print(f"{directory / name}: {where}: {message}")
            if len(found) > MAX_ERRORS_PER_FILE:
                print(f"{directory / name}: ... and {len(found) - MAX_ERRORS_PER_FILE} more")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
