import csv
import json
import shutil
from pathlib import Path

import pytest

from contract.validate import OUTPUT, read_road

EXAMPLE = OUTPUT / "_example"


@pytest.fixture
def road(tmp_path: Path) -> Path:
    return Path(shutil.copytree(EXAMPLE, tmp_path / "_example"))


def edit_json(path: Path, change) -> None:
    data = json.loads(path.read_text("utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")


def edit_series(path: Path, change) -> None:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    change(rows)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validate(directory: Path) -> dict:
    return read_road(directory).errors


def messages(errors: dict, name: str) -> str:
    return "\n".join(f"{where}: {msg}" for where, msg in errors.get(name, []))


def test_example_follows_contract():
    assert validate(EXAMPLE) == {}


def test_example_covers_every_state():
    with (EXAMPLE / "series.csv").open(encoding="utf-8") as f:
        states = {row["state"] for row in csv.DictReader(f)}
    anomalies = json.loads((EXAMPLE / "anomalies.json").read_text("utf-8"))
    assert states == {"normal", "anomaly", "imputed"}
    assert any(a["is_mega"] and a["event_id"] for a in anomalies)
    assert {a["category"] for a in anomalies} == {"traffic", "technical"}


def test_missing_and_unexpected_files(road: Path):
    (road / "anomalies.json").rename(road / "anomaly.json")
    errors = validate(road)
    assert "required file is missing" in messages(errors, "anomalies.json")
    assert "unexpected file" in messages(errors, "anomaly.json")


def test_road_must_match_directory(road: Path):
    edit_json(road / "sensors.json", lambda d: d.update(road="a134"))
    assert "must equal the directory name" in messages(validate(road), "sensors.json")


def test_ids_need_road_prefix_and_must_be_unique(road: Path):
    def change(events):
        events[0]["id"] = "a134-crash"
        events[1]["id"] = events[2]["id"]

    edit_json(road / "events.json", change)
    found = messages(validate(road), "events.json")
    assert "must start with '_example-'" in found
    assert "duplicate id" in found


def test_series_header_is_fixed(road: Path):
    edit_series(road / "series.csv", lambda rows: [r.pop("buses") for r in rows])
    assert "header must be exactly" in messages(validate(road), "series.csv")


def test_series_rows(road: Path):
    def change(rows):
        rows[0]["sensor_id"] = "_example-km99"
        rows[1]["volume"] = "12.5"
        rows[2]["state"] = "imputed"
        rows[3]["ts"] = rows[4]["ts"]
        rows[5]["ts"] = "2025-03-07T05:30:00+03:00"
        rows[6]["ts"] = "2025-03-07T06:00:00"

    edit_series(road / "series.csv", change)
    found = messages(validate(road), "series.csv")
    assert "line 2: unknown sensor_id '_example-km99'" in found
    assert "line 3: volume: Input should be a valid integer" in found
    assert "line 4: imputation_method is set if and only if state is imputed" in found
    assert "line 6: duplicate hour" in found
    assert "line 7: ts: Value error, must be the start of an hour" in found
    assert "line 8: ts: Input should have timezone info" in found


def test_anomaly_links_and_interval(road: Path):
    def change(anomalies):
        anomalies[0]["event_id"] = "_example-nothing"
        anomalies[1]["ends_at"] = anomalies[1]["starts_at"]
        anomalies[2]["sensor_id"] = "_example-km99"
        anomalies[3]["level"] = "severe"

    edit_json(road / "anomalies.json", change)
    found = messages(validate(road), "anomalies.json")
    assert "[0].event_id: unknown event_id" in found
    assert "[1].ends_at: must be later than starts_at" in found
    assert "[2].sensor_id: unknown sensor_id" in found
    assert "[3].level:" in found


def test_corporate_anomalies_use_the_same_schema(road: Path):
    edit_json(road / "corporate_anomalies.json", lambda d: d[0].pop("is_mega"))
    assert "[0].is_mega: Field required" in messages(validate(road), "corporate_anomalies.json")


def test_event_links_need_events_file(road: Path):
    (road / "events.json").unlink()
    assert "unknown event_id" in messages(validate(road), "anomalies.json")


def test_broken_json(road: Path):
    (road / "sensors.json").write_text("{", "utf-8")
    assert "not valid JSON" in messages(validate(road), "sensors.json")
