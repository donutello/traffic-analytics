"""Read the customer's A-133 Excel exports into one clean hourly table.

An export is a vertical report: rows with a section label («км 12+000 …») alternate with
hourly rows: a date plus 28 numeric columns. This module turns every readable hour of
every section into one row whose names match the contract (`contract/models.py`,
SeriesRow), so the whole road reads as one clean hourly series per sensor. Unlike the
A-134 parser this one keeps the per-direction splits by vehicle class: the balance
audit (quality.py) also checks them against the direction counts.
"""

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

ROAD = "a133"
ROAD_NAME = "А-133, подъезд к г. Липецк"
MSK = timezone(timedelta(hours=3))
"""The customer's data is in Moscow time, so every timestamp carries +03:00."""

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / ROAD
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output" / ROAD

DATE_RE = re.compile(r"^\s*\d{1,2}[./]\d{1,2}[./]\d{4}(\s+\d{1,2}:\d{2}(:\d{2})?)?\s*$")
DATE_FORMATS = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y")
KM_RE = re.compile(r"км\s*(\d+)(?:\+(\d+))?", re.IGNORECASE)
SKIPPED = frozenset({"итого", "среднее", "%", "дата"})

# The 28 numeric columns of the export, in order: the hour total, the two direction
# counts, seven vehicle classes each again split by direction, then per-direction
# speed and lane load. Class splits keep their real names here (the A-134 parser drops
# them); quality.py uses them for the balance audit, the output drops them again.
SOURCE_COLUMNS = [
    "volume",
    "volume_direct",
    "volume_reverse",
    "cars",
    "cars_direct",
    "cars_reverse",
    "small_trucks",
    "small_trucks_direct",
    "small_trucks_reverse",
    "medium_trucks",
    "medium_trucks_direct",
    "medium_trucks_reverse",
    "large_trucks",
    "large_trucks_direct",
    "large_trucks_reverse",
    "road_trains",
    "road_trains_direct",
    "road_trains_reverse",
    "buses",
    "buses_direct",
    "buses_reverse",
    "motorcycles",
    "motorcycles_direct",
    "motorcycles_reverse",
    "speed_direct",
    "speed_reverse",
    "load_direct",
    "load_reverse",
]
TABLE_COLUMNS = ["section", "ts", *SOURCE_COLUMNS]

# Coordinates for the two known sensors, keyed by the km mark as the export writes it.
# Approximate to a few hundred metres: taken from the OSM way of the road itself
# (relation 3899145, chain the points along the А-133 geometry to the km mark) and the
# neighbouring villages - the km 12 point lies near Елецкая Лозовка (Хлевенский округ),
# the km 40 point near Боринское. The customer's report carries these two sections; add
# an entry for every new sensor found in later exports.
KNOWN_SENSORS: dict[str, dict[str, float]] = {
    "12+000": {"km": 12.0, "lat": 52.29525, "lon": 39.16719},
    "40+000": {"km": 40.0, "lat": 52.47469, "lon": 39.40193},
}


def _clean_numbers(cell: object) -> float | None:
    """Read one numeric cell of the export: thin spaces, thousands separators, commas."""
    if cell is None or isinstance(cell, (int, float)):
        return cell
    text = str(cell).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_datetime(cell: object) -> datetime | None:
    if isinstance(cell, datetime):
        return cell.replace(tzinfo=MSK) if cell.tzinfo is None else cell.astimezone(MSK)
    if isinstance(cell, date):
        return datetime(cell.year, cell.month, cell.day, tzinfo=MSK)
    text = str(cell).strip().replace("/", ".")
    if DATE_RE.match(text):
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=MSK)
            except ValueError:
                continue
    return None


def parse_traffic_excel(filepath: Path) -> pd.DataFrame:
    """Read one export file into rows with TABLE_COLUMNS; unreadable rows are skipped."""
    workbook = load_workbook(filepath, read_only=True, data_only=True)
    sheet = workbook.active
    records = []
    section = "неизвестный участок"

    for row in sheet.iter_rows(values_only=True):
        if not row:
            continue

        for cell in row[:6]:
            if not isinstance(cell, str):
                continue
            text = cell.strip()
            if KM_RE.search(text):
                section = text
                break
            if ("а/д" in text.lower() or "а-133" in text.lower() or "подъезд" in text.lower()) and (
                "отчет" not in text.lower()
            ):
                section = text
                break

        first = row[0]
        if first is None or str(first).strip().lower() in SKIPPED:
            continue
        ts = _parse_datetime(first)
        if ts is None:
            continue
        ts = ts.replace(minute=0, second=0, microsecond=0)

        values = list(row[1:29])
        values += [None] * (len(SOURCE_COLUMNS) - len(values))
        records.append([section, ts, *(_clean_numbers(v) for v in values)])

    workbook.close()
    return pd.DataFrame(records, columns=TABLE_COLUMNS)


def _sensor_key(section: str) -> str:
    match = KM_RE.search(section)
    return f"{match.group(1)}+{match.group(2)}" if match and match.group(2) else ""


def sensor_id(section: str, fallback: int = 0) -> str:
    """Id of a sensor: the road code plus its km mark, for example a133-km12-0."""
    match = KM_RE.search(section)
    if not match:
        return f"{ROAD}-{fallback:02d}"
    km, meters = match.group(1), match.group(2) or "0"
    return f"{ROAD}-km{int(km)}-{int(meters)}"


def build_sensors(sections: list[str]) -> list[dict]:
    """One sensors.json entry per section found in the exports, sorted by km."""

    def km_value(section: str) -> float:
        match = KM_RE.search(section)
        if not match:
            return float("inf")
        return int(match.group(1)) + int(match.group(2) or 0) / 1000

    sensors = []
    for index, section in enumerate(sorted(set(sections), key=km_value), start=1):
        known = KNOWN_SENSORS.get(_sensor_key(section))
        match = KM_RE.search(section)
        sensor = {
            "id": sensor_id(section, fallback=index),
            "name": section,
            "km": known["km"] if known else (km_value(section) if match else None),
            "lat": known["lat"] if known else None,
            "lon": known["lon"] if known else None,
            "directions": {"direct": "на Липецк", "reverse": "из Липецка"},
        }
        if not known:
            print(f"no coordinates for section {section!r}: add them to KNOWN_SENSORS in parse.py")
        sensors.append(sensor)
    return sensors


def load_raw(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Parse every export in raw_dir; drop duplicated hours (first file wins)."""
    files = sorted(raw_dir.glob("*.xlsx")) + sorted(raw_dir.glob("*.xls"))
    parts = []
    for path in files:
        print(f"reading {path.name} …", end=" ", flush=True)
        try:
            part = parse_traffic_excel(path)
        except Exception as error:  # one broken report must not stop the rest
            print(f"FAILED ({error})")
            continue
        print(f"{len(part)} hours")
        parts.append(part)

    if not parts:
        return pd.DataFrame(columns=TABLE_COLUMNS)

    table = pd.concat(parts, ignore_index=True).drop_duplicates(
        subset=["section", "ts"], keep="first"
    )
    return table.sort_values(["section", "ts"], ignore_index=True)
