"""Write the module's result to analysis/output/r22/ by the data contract (issue #39).

The run is: parse the raw exports -> technical failures and gap filling (#36) ->
traffic detectors (#37) -> cross-channel confirmation promotion -> manual-review
events and anomaly-event linking (#35) -> the corporate system's findings (#38). All
five contract files come out of one command, `uv run python -m analysis.r22`; the same
run then refreshes the #40 trend/backtest results under analysis/r22/results/.
"""

import csv
import json
from pathlib import Path

import pandas as pd

from contract.models import SERIES_COLUMNS

from . import corporate, detect, events, forecast, parse, quality, trends

COLUMNS = SERIES_COLUMNS

# The extras of issue #40 (trend tables and the forecast backtest) are machine-readable
# results too, but NOT contract files, and the contract allows nothing else in a road
# output directory - so they live inside the module, in analysis/r22/results/.
RESULTS_DIR = Path(__file__).resolve().parent / "results"

# An anomaly links to an event only when their times overlap AND the anomaly kind fits
# the event category: an accident is a volume drop, a queue, a sustained slow-down
# under the crash clearance, or a broken day shape, never a stuck sensor.
EVENT_KINDS = {
    "accident": {"volume_drop", "congestion", "speed_drop", "profile_shift"},
    "roadworks": {"volume_drop", "volume_spike", "profile_shift", "speed_drop", "congestion"},
    "weather": {"volume_drop", "congestion", "speed_drop", "profile_shift"},
    "holiday": {"volume_drop", "volume_spike", "profile_shift"},
    "outage": {"missing_hours", "flatline", "zero_speed", "zero_telemetry"},
    "other": {"volume_drop", "volume_spike", "congestion", "profile_shift", "speed_drop"},
}
# only outage events are explained by technical findings; everything else needs a traffic one
TECHNICAL_ONLY = {"outage"}


def mark_states(filled: pd.DataFrame, anomalies: list[dict]) -> pd.Series:
    """Per-hour state: a filled hour is imputed (even inside an anomaly, contract rule),
    an hour inside a traffic anomaly is anomaly, everything else stays normal."""
    imputed = filled["imputation_method"].ne("")
    states = pd.Series("normal", index=filled.index)
    for item in (a for a in anomalies if a["category"] == "traffic"):
        mask = (
            (filled["sensor_id"] == item["sensor_id"])
            & (filled["ts"] >= pd.Timestamp(item["starts_at"]))
            & (filled["ts"] < pd.Timestamp(item["ends_at"]))
        )
        states[mask & ~imputed] = "anomaly"
    states[imputed] = "imputed"
    return states


def link_events(anomalies: list[dict], events_list: list[dict]) -> dict[str, int]:
    """Attach event_id to anomalies whose interval overlaps the event day **or the day
    before/after it** (news dates round to a day, and an overnight accident clears the
    next morning) and whose type suits the event category; return how many links each
    event got (issue #35: the README reports which reviewed events the algorithm found
    and which it missed)."""
    links = {event["id"]: 0 for event in events_list}
    for event in events_list:
        wanted = EVENT_KINDS[event["category"]]
        want_technical = event["category"] in TECHNICAL_ONLY
        day_start = pd.Timestamp(event["day"], tz=parse.MSK) - pd.Timedelta(days=1)
        day_end = day_start + pd.Timedelta(days=3)
        for item in anomalies:
            if item["type"] not in wanted:
                continue
            if (item["category"] == "technical") != want_technical:
                continue
            starts = pd.Timestamp(item["starts_at"])
            ends = pd.Timestamp(item["ends_at"])
            if starts < day_end and ends > day_start and item["event_id"] is None:
                item["event_id"] = event["id"]
                links[event["id"]] += 1
    return links


def number_corporate(corporate_items: list[dict]) -> list[dict]:
    for i, item in enumerate(corporate_items, start=1):
        item["id"] = f"{parse.ROAD}-corp-{i:04d}"
    return corporate_items


def _number(value: object, digits: int | None) -> str:
    """Format one number for series.csv: empty when missing, ints without a dot."""
    if value is None or pd.isna(value):
        return ""
    return str(int(round(float(value)))) if digits is None else f"{float(value):.1f}"


def write_series(filled: pd.DataFrame, states: pd.Series, out_dir: Path) -> None:
    with open(out_dir / "series.csv", "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(COLUMNS)
        for row, state in zip(filled.to_dict("records"), states, strict=True):
            writer.writerow(
                [
                    row["sensor_id"],
                    row["ts"].isoformat(),
                    _number(max(row["volume"], 0), None),
                    _number(max(row["volume_direct"], 0), None),
                    _number(max(row["volume_reverse"], 0), None),
                    _number(row["cars"], None),
                    _number(row["small_trucks"], None),
                    _number(row["medium_trucks"], None),
                    _number(row["large_trucks"], None),
                    _number(row["road_trains"], None),
                    _number(row["buses"], None),
                    _number(row["motorcycles"], None),
                    _number(max(row["speed_direct"], 0), 1),
                    _number(max(row["speed_reverse"], 0), 1),
                    _number(max(row["load_direct"], 0), 1),
                    _number(max(row["load_reverse"], 0), 1),
                    state,
                    row["imputation_method"],
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
    section_ids = {sensor["name"]: sensor["id"] for sensor in sensors}
    table = table.sort_values(["section", "ts"], ignore_index=True)
    table["sensor_id"] = table["section"].map(section_ids)

    failures, bad_hours = quality.detect_failures(table, section_ids)
    filled = quality.fill_gaps(table, bad_hours, section_ids)
    traffic = detect.detect_traffic(filled, section_ids)
    monthly = detect.detect_monthly(filled, section_ids)
    # volume and speed findings of one sensor that overlap in time confirm each
    # other (+0.5 once each, contract table relevels them) before ids are handed out
    anomalies = detect.finalize(failures + detect.promote_correlated(traffic + monthly))

    event_list = events.load_events()
    links = link_events(anomalies, event_list)
    corp = number_corporate(corporate.load_corporate())

    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        out_dir / "sensors.json",
        {"road": parse.ROAD, "road_name": parse.ROAD_NAME, "sensors": sensors},
    )
    write_series(filled, mark_states(filled, anomalies), out_dir)
    write_json(out_dir / "anomalies.json", anomalies)
    write_json(out_dir / "events.json", events.strip_days(event_list))
    write_json(out_dir / "corporate_anomalies.json", corp)

    kinds = pd.Series([a["type"] for a in anomalies]).value_counts()
    filled_hours = int(filled["imputation_method"].ne("").sum())
    print(f"sensors: {len(sensors)}, hours: {len(filled)}, anomalies: {len(anomalies)}")
    for kind, count in kinds.items():
        print(f"  {kind}: {count}")
    print(f"imputed hours: {filled_hours}, corporate findings: {len(corp)}")
    found = sum(count > 0 for count in links.values())
    print(f"manual-review events: {len(event_list)}, found by the algorithm: {found}")
    for event in event_list:
        mark = "found" if links[event["id"]] else "missed"
        print(f"  {event['day']} [{event['category']:<8}] {mark:>6}  {event['title']}")
    print(f"result written to {out_dir.relative_to(out_dir.parents[1])}")

    # the #40 extras: trend tables and the walk-forward forecast error, refreshed from
    # the very same run's filled series and finalized findings, kept out of the
    # contract directory (docs/contract: no other files allowed there)
    trends_data = trends.build_trends(filled, anomalies)
    backtest_data = forecast.backtest(filled)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(RESULTS_DIR / "trends.json", trends_data)
    write_json(RESULTS_DIR / "forecast_backtest.json", backtest_data)
    for line in trends.summarize(trends_data) + forecast.summarize(backtest_data):
        print(line)
    print(f"module results written to {RESULTS_DIR.relative_to(RESULTS_DIR.parents[2])}")


if __name__ == "__main__":
    run()
