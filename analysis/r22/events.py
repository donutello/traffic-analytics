"""Load the manual-review events (issue #32) from events.csv next to this file.

events.csv is the module's working table of real outside events found by browsing news
and the official calendar: one line per event, Russian title and description (the
dashboard shows them), a source_url for every line (the contract requires it, and every
URL in the file was actually opened during this research). The pipeline writes the file
out as events.json by the contract and links anomalies whose interval overlaps an event
day and whose type matches the event category.
"""

import csv
import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVENTS_CSV = HERE / "events.csv"


def load_events(path: Path = EVENTS_CSV) -> list[dict]:
    """events.json items plus a parsed `day` used for linking."""
    events = []
    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            events.append(
                {
                    "id": row["id"],
                    "date": row["date"],
                    "category": row["category"],
                    "title": row["title"],
                    "description": row["description"] or None,
                    "source_url": row["source_url"],
                    "day": datetime.date.fromisoformat(row["date"]),
                }
            )
    return events


def strip_days(events: list[dict]) -> list[dict]:
    """Drop the linking helper, leaving exactly the contract fields."""
    return [{k: v for k, v in event.items() if k != "day"} for event in events]
