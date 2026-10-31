"""Read the customer's A-134 Excel exports into one clean hourly table.

An export is a vertical report: rows with a section label («км 8+100 …») alternate with
hourly rows: a date plus 28 numeric columns. This module turns every readable hour of
every section into one row whose names match the contract (`contract/models.py`,
SeriesRow), so the whole road reads as one clean hourly series per sensor.
"""

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

ROAD = "a134"
ROAD_NAME = "А-134, подъезд к г. Воронеж"
MSK = timezone(timedelta(hours=3))
"""The customer's data is in Moscow time, so every timestamp carries +03:00."""

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / ROAD
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output" / ROAD

DATE_RE = re.compile(r"^\s*\d{1,2}[./]\d{1,2}[./]\d{4}(\s+\d{1,2}:\d{2}(:\d{2})?)?\s*$")
KM_RE = re.compile(r"км\s*(\d+)(?:\+(\d+))?", re.IGNORECASE)
SKIPPED = frozenset({"итого", "среднее", "%", "дата"})

# Only the columns the contract needs: totals per vehicle class plus per-direction
# speed and load. The export's per-direction splits by vehicle class are dropped.
SOURCE_COLUMNS = [
    "volume",
    "volume_direct",
    "volume_reverse",
    "cars",
    "_cd",
    "_cr",
    "small_trucks",
    "_sd",
    "_sr",
    "medium_trucks",
    "_md",
    "_mr",
    "large_trucks",
    "_ld",
    "_lr",
    "road_trains",
    "_rd",
    "_rr",
    "buses",
    "_bd",
    "_br",
    "motorcycles",
    "_md2",
    "_mr2",
    "speed_direct",
    "speed_reverse",
    "load_direct",
    "load_reverse",
]
KEEP_COLUMNS = [c for c in SOURCE_COLUMNS if not c.startswith("_")]
KEEP_POSITIONS = [i for i, c in enumerate(SOURCE_COLUMNS) if not c.startswith("_")]
TABLE_COLUMNS = ["section", "ts", *KEEP_COLUMNS]

# Coordinates for known sensors, keyed by the km mark as the export writes it.
# Approximate, taken from landmarks on OSM (the pedestrian bridges and bus stops of the
# М-4 «Дон» — Воронеж rebuilding, «хутор Ветряк» near km 8+150). Add an entry for every
# new sensor that appears in the exports (issue #22).
KNOWN_SENSORS: dict[str, dict[str, float]] = {
    "8+100": {"km": 8.1, "lat": 51.7729, "lon": 39.1891},
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
    if DATE_RE.match(str(cell)):
        try:
            return pd.to_datetime(str(cell), dayfirst=True).to_pydatetime().replace(tzinfo=MSK)
        except ValueError:
            return None
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
            if ("а/д" in text.lower() or "а-134" in text.lower() or "подъезд" in text.lower()) and (
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
        numbers = [_clean_numbers(v) for v in values]
        records.append([section, ts, *(numbers[i] for i in KEEP_POSITIONS)])

    workbook.close()
    return pd.DataFrame(records, columns=TABLE_COLUMNS)


def _sensor_key(section: str) -> str:
    match = KM_RE.search(section)
    return f"{match.group(1)}+{match.group(2)}" if match and match.group(2) else ""


def sensor_id(section: str, fallback: int = 0) -> str:
    """Id of a sensor: the road code plus its km mark, for example a134-km8-100."""
    match = KM_RE.search(section)
    if not match:
        return f"{ROAD}-{fallback:02d}"
    km, meters = match.group(1), match.group(2) or "0"
    return f"{ROAD}-km{int(km)}-{meters}"


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
            "directions": {"direct": "на Воронеж", "reverse": "из Воронежа"},
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
