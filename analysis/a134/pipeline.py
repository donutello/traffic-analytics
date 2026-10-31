"""Write the module's result to analysis/output/a134/ by the data contract."""

import csv
import json
from pathlib import Path

import pandas as pd

from contract.models import SERIES_COLUMNS

from . import detect, parse

COLUMNS = SERIES_COLUMNS


def _number(value: object, digits: int | None) -> str:
    """Format one number for series.csv: empty when missing, ints without a dot."""
    if value is None or pd.isna(value):
        return ""
    return str(int(round(float(value)))) if digits is None else f"{float(value):.1f}"


def mark_states(df: pd.DataFrame, anomalies: list[dict]) -> pd.Series:
    """State of every hour: anomaly inside a traffic anomaly, normal otherwise.

    Hours filled in (issue #24) will be marked imputed later; hours that were lost and
    not filled in simply have no row.
    """
    states = pd.Series("normal", index=df.index)
    for anomaly_ in (a for a in anomalies if a["category"] == "traffic"):
        mask = (
            (df["sensor_id"] == anomaly_["sensor_id"])
            & (df["ts"] >= pd.Timestamp(anomaly_["starts_at"]))
            & (df["ts"] < pd.Timestamp(anomaly_["ends_at"]))
        )
        states[mask] = "anomaly"
    return states


def write_series(df: pd.DataFrame, states: pd.Series, out_dir: Path) -> None:
    with open(out_dir / "series.csv", "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(COLUMNS)
        for row, state in zip(df.to_dict("records"), states, strict=True):
            writer.writerow(
                [
                    row["sensor_id"],
                    row["ts"].isoformat(),
                    _number(row["volume"], None),
                    _number(row["volume_direct"], None),
                    _number(row["volume_reverse"], None),
                    _number(row["cars"], None),
                    _number(row["small_trucks"], None),
                    _number(row["medium_trucks"], None),
                    _number(row["large_trucks"], None),
                    _number(row["road_trains"], None),
                    _number(row["buses"], None),
                    _number(row["motorcycles"], None),
                    _number(row["speed_direct"], 1),
                    _number(row["speed_reverse"], 1),
                    _number(row["load_direct"], 1),
                    _number(row["load_reverse"], 1),
                    state,
                    "",
                ]
            )


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(raw_dir: Path = parse.RAW_DIR, out_dir: Path = parse.OUTPUT_DIR) -> None:
    table = parse.load_raw(raw_dir)
    if table.empty:
        print(f"no exports found in {raw_dir}: put the customer's .xlsx reports there")
        return

    sensors = parse.build_sensors(table["section"].tolist())
    table = table.sort_values(["section", "ts"], ignore_index=True)
    table["sensor_id"] = table["section"].map({sensor["name"]: sensor["id"] for sensor in sensors})
    anomalies = detect.detect_all(table, sensors)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        out_dir / "sensors.json",
        {"road": parse.ROAD, "road_name": parse.ROAD_NAME, "sensors": sensors},
    )
    write_series(table, mark_states(table, anomalies), out_dir)
    write_json(out_dir / "anomalies.json", anomalies)

    kinds = pd.Series([a["type"] for a in anomalies]).value_counts()
    print(f"sensors: {len(sensors)}, hours: {len(table)}, anomalies: {len(anomalies)}")
    for kind, count in kinds.items():
        print(f"  {kind}: {count}")
    print(f"result written to {out_dir.relative_to(out_dir.parents[1])}")
