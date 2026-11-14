"""Read the customer's R-22 Excel exports into one clean hourly table.

An export is a vertical report: rows with a section label («км 448+650 …») alternate
with hourly rows: a date plus 28 numeric columns, the same form the A-133, A-134 and
R-298 modules read. This module turns every readable hour of every section into one row
whose names match the contract (`contract/models.py`, SeriesRow), so the whole road
reads as one clean hourly series per sensor. Like those modules this one keeps the
per-direction splits by vehicle class: the balance audit (quality.py) also checks them
against the direction counts.

Two known quirks of this customer export were checked for here (docs/contract and the
sibling modules describe both): Russian decimal commas (handled in `_clean_numbers` -
this particular file already parses as plain integers) and the +3 h label shift of the
A-134 export. The shift does NOT apply to this report: the hour profile of every
section bottoms exactly at 03:00-04:00 and peaks in the middle of the day, so the
labels already sit on the Moscow clock. Like R-298's, the export labels every hour at
its own end minute («01.09.2023 00:59:59» is the 00 o'clock hour), so every stamp is
cut to the start of its hour.

One R-22-specific note for readers of the raw file: the kilometre marks are the Р-22
numbering of the official approach road to Saratov, and this stretch lies in Voronezh
oblast, not near Saratov itself: km 444-459.6 is the Borisoglebsk section (the
«Обход Борисоглебска» construction zone), km 465-484 the capital-repair section by the
villages of Танцырей/Третьяки/Старовоскресеновка/Нововоскресеновка, while the Saratov
end of the same road is far further along (the customer labels the whole corridor
«подъезд к г. Саратов»). The second sensor, inside the repair zone, reports only in
2023-2024 and a few weeks again in summer 2026 (see the README).
"""

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

ROAD = "r22"
ROAD_NAME = "Р-22 «Каспий», подъезд к г. Саратов"
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
# speed and lane load. Class splits keep their real names here; quality.py uses them
# for the balance audit, the output drops them again.
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
# Approximate, up to a few kilometres (flagged so in the README and to the dashboard):
# each point is the geocentre of the place the official papers about this road name at
# the sensor's kilometre (sources in the module README), so it sits where the sensor's
# km is on the road, not at the exact pole. Add an entry for every new sensor found
# later, same way: find the settlement or works zone at that km, geocode it.
KNOWN_SENSORS: dict[str, dict[str, float]] = {
    # km 444-459.6 is the «Обход Борисоглебска» zone (Росавтодор), the old road runs
    # through the city: point = city geocentre, sources in the README.
    "448+650": {"km": 448.65, "lat": 51.3736, "lon": 41.1104},  # г. Борисоглебск
    # km 465-484 is the capital-repair zone by Танцырей/Третьяки/Старовоскресеновка/
    # Нововоскресеновка; the sensor stands in its far part: point = geocentre of the
    # two Воскресеновка hamlets, sources in the README.
    "478+742": {"km": 478.742, "lat": 51.4100, "lon": 42.5620},  # Нововоскресеновка area
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
    """Read one export file into rows with TABLE_COLUMNS; unreadable rows are skipped.

    The export labels every hour at its own end minute («01.09.2023 00:59:59» is the
    00 o'clock hour), so every stamp is cut to the start of its hour.
    """
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
        records.append([section, ts, *numbers])

    workbook.close()
    return pd.DataFrame(records, columns=TABLE_COLUMNS)


def _sensor_key(section: str) -> str:
    match = KM_RE.search(section)
    return f"{match.group(1)}+{match.group(2)}" if match and match.group(2) else ""


def sensor_id(section: str, fallback: int = 0) -> str:
    """Id of a sensor: the road code plus its km mark, for example r22-km448-650."""
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
            "directions": {"direct": "на Саратов", "reverse": "на Борисоглебск и М-4 «Дон»"},
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
