"""Business logic for /api/comparison: pairing and counting, per road and over all roads.

The matching rule (none-or-many interval overlap on the same sensor) is written down
on the response model ComparisonOut; it is implemented in comparison().
"""

import libsql

from backend.anomalies.repositories import data_last_day
from backend.anomalies.services import anomaly_item
from backend.common.periods import period_conditions
from backend.comparison import repositories


def overlaps(a: dict, b: dict) -> bool:
    """Whether two anomaly items overlap in time ([starts_at, ends_at), so a bare touch
    is not an overlap). Their contract times share format and offset: text order is time order."""
    return a["starts_at"] < b["ends_at"] and b["starts_at"] < a["ends_at"]


def percent_of(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def comparison(db: libsql.Connection, road: str | None, lo: str | None, hi: str | None) -> dict:
    """Our findings against the corporate system's over a period (issue #7)."""
    conditions = ([("a.road = ?", road)] if road else []) + period_conditions(lo, hi, "a")
    rows = repositories.comparison_rows(db, conditions)
    last_day = data_last_day(db)
    road_names = dict(repositories.road_name_rows(db))

    roads_in_order = dict.fromkeys(row[2] for row in rows)  # rows start with id, source, road
    by_road = {code: {"ours": [], "corporate": []} for code in roads_in_order}
    for row in rows:
        by_road[row[2]][row[1]].append(anomaly_item(row, last_day))

    roads_out = []
    grand = dict(ours=0, corporate=0, both=0, only_ours=0, only_corporate=0)
    found = dict(ours=0, corporate=0)
    for code, by_source in by_road.items():
        ours, corporate = by_source["ours"], by_source["corporate"]
        corporate_by_sensor: dict[str, list[dict]] = {}
        for c in corporate:
            corporate_by_sensor.setdefault(c["sensor_id"], []).append(c)
        pairs, matched_ours, matched_corporate = [], set(), set()
        for a in ours:  # none-or-many: every overlapping pair goes into both_found
            for c in corporate_by_sensor.get(a["sensor_id"], []):
                if overlaps(a, c):
                    pairs.append({"ours": a, "corporate": c})
                    matched_ours.add(a["id"])
                    matched_corporate.add(c["id"])
        only_ours = [a for a in ours if a["id"] not in matched_ours]
        only_corporate = [c for c in corporate if c["id"] not in matched_corporate]
        totals = dict(
            ours=len(ours),
            corporate=len(corporate),
            both=len(pairs),
            only_ours=len(only_ours),
            only_corporate=len(only_corporate),
        )
        roads_out.append(
            {
                "road": code,
                "road_name": road_names.get(code, code),
                "totals": totals,
                "shares": {
                    "ours_found_pct": percent_of(len(matched_ours), len(ours)),
                    "corporate_found_pct": percent_of(len(matched_corporate), len(corporate)),
                },
                "both_found": pairs,
                "only_ours": only_ours,
                "only_corporate": only_corporate,
            }
        )
        grand = {key: grand[key] + value for key, value in totals.items()}
        found["ours"] += len(matched_ours)
        found["corporate"] += len(matched_corporate)
    return {
        "roads": roads_out,
        "totals": grand,
        "shares": {
            "ours_found_pct": percent_of(found["ours"], grand["ours"]),
            "corporate_found_pct": percent_of(found["corporate"], grand["corporate"]),
        },
    }
