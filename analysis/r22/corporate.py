"""The customer corporate system's findings for this road, transcribed (issue #38).

corporate_findings.csv is a hand-retyped extract from the customer's monitoring
interface for the whole 2023-2026 export period: what it flagged and the numbers it
showed. The corporate system on this road is its own personality (issue #38 tells the
whole comparison): it noticed the big weather days of 2023-2024 almost every time and
marked them red, read the long 2024 lane-closure and diversion windows on the repair
section as traffic drops only when the yearly norm happened to disagree, missed all
summer daytime roadworks queues on the same section, and cried wolf at empty holiday
nights. Like everywhere else, it is blind to everything the sensor itself did wrong.

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
