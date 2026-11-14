"""The customer corporate system's findings for this road, transcribed (issue #20).

corporate_findings.csv is a hand-retyped extract from the customer's monitoring
interface for 2023-2025: what it flagged as an anomaly (sensor, interval, type,
its own severity class yellow/orange/red) and the numbers it showed. The transcription
is imperfect exactly the way the real interface is: it lags behind events, picks wider
intervals than we do, misses short accidents, and keeps a steady stream of false alarms
- this demo stand-in leans into that: it cries wolf on quiet sensor restarts and stays
quiet through most of the weather.

This module only converts the CSV to contract-shaped items (detector `corporate`,
`score` null, `is_mega` always false). The corporate severity class is mapped onto the
v1 score bands through fixed representative scores, so a corporate `red` lands where
the contract table puts it (`level` still comes from `level_from_score`, one function).
"""

import csv
from pathlib import Path

from .detect import level_from_score

HERE = Path(__file__).resolve().parent
FINDINGS_CSV = HERE / "corporate_findings.csv"

# Representative scores per corporate severity class: yellow sits in the low band,
# orange in medium, red in high (contract v1 level table). The score itself is null
# in the output - the corporate system has no score of its own.
CLASS_SCORE = {"yellow": 1.5, "orange": 2.8, "red": 4.2}


def load_corporate(path: Path = FINDINGS_CSV) -> list[dict]:
    """Convert corporate_findings.csv to contract-shaped anomalies, earliest first."""
    with path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))

    items = []
    for row in sorted(rows, key=lambda r: (r["starts"], r["sensor_id"])):
        severity = row["severity"].strip().lower()
        items.append(
            {
                "id": "",  # numbered by the caller together with all other output ids
                "sensor_id": row["sensor_id"],
                "starts_at": f"{row['starts']}+03:00",
                "ends_at": f"{row['ends']}+03:00",
                "category": row["category"],
                "type": row["type"],
                "detector": "corporate",
                # the class lands on the v1 table through the same level_from_score
                "level": level_from_score(CLASS_SCORE[severity]),
                "metric": row["metric"],
                "actual": None if row["actual"] == "" else float(row["actual"]),
                "expected": None if row["expected"] == "" else float(row["expected"]),
                "deviation_pct": None
                if row["deviation_pct"] == ""
                else float(row["deviation_pct"]),  # the number the interface showed
                "score": None,
                "is_mega": False,
                "event_id": None,
                "description": None,
            }
        )
    return items
