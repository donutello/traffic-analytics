"""Generate fake-but-realistic customer raw exports (demo/CI stand-ins).

`uv run python tools/gen_raw.py`          -> the A-134 demo export (default, as before)
`uv run python tools/gen_raw.py a133`     -> the A-133 demo export (this mode, new)

The A-133 module has no real customer export yet, so it runs on the a133 files written
here: same vertical report layout, two sections (км 12+000 near Елецкая Лозовка and
км 40+000 near Боринское), their own seed, and the reviewed A-133 events embedded on
their real dates (analysis/a133/events.csv) plus sensor incidents that are not events:
whole lost days, a stuck run, an incomplete day, zero-speed hours, a twelve-hour dead
reporter and two quiet metering-drift months for the balance audit. Regenerate with the
command above, then rerun `uv run python -m analysis.a133`.

Original purpose below (A-134):

The module now runs on the customer's real export (kept out of git in
analysis/data/raw/a134/), but a public repo needs a way to exercise the whole pipeline
without that file: this tool writes .xlsx files in exactly the vertical report layout
`analysis/a134/parse.py` reads (section rows «км …» plus hourly rows: a date and 28
numbers), for 2023-2025, two sections, with plausible daily, weekly and seasonal patterns
and vehicle classes.

Into the traffic it embeds, on their real reviewed dates (analysis/a134/events.csv):
accidents (one 8-12 hour window of low volume and speed), roadworks (multi-day shifts),
weather waves (multi-day speed drops), holiday effects, an outage (six dead hours),
plus sensor incidents that are not events: whole lost days, a stuck sensor run, an
incomplete day and zero-speed hours. The seed is fixed, so the file is reproducible:
`uv run python tools/gen_raw.py` reruns the same export (issue #27 infrastructure).
The committed `analysis/output/a134/` is built from the real export, not from this
demo data: rerunning the pipeline after `gen_raw` only makes sense for a local demo,
it overwrites that output with synthetic numbers.
"""

import datetime as dt
import sys
from pathlib import Path

import numpy as np
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # so `uv run python tools/gen_raw.py` finds the package

from analysis.a134.holidays import day_kind  # noqa: E402
from analysis.a134.parse import MSK, RAW_DIR  # noqa: E402

SEED = 20251114
YEARS = (2023, 2024, 2025)

SECTIONS = [
    ("км 8+100 а/д А-134", 1.0),  # sensor km 8+100 (хутор Ветряк)
    ("км 4+700 а/д А-134", 0.78),  # sensor km 4+700 (развязка у «Града», город ближе)
]

# the stuck sensor of the main section: seven evening hours repeating one count
STUCK_HOURS = {
    dt.datetime(2024, 8, 14, 21),
    dt.datetime(2024, 8, 14, 22),
    dt.datetime(2024, 8, 14, 23),
    dt.datetime(2024, 8, 15, 0),
    dt.datetime(2024, 8, 15, 1),
    dt.datetime(2024, 8, 15, 2),
    dt.datetime(2024, 8, 15, 3),
}
STUCK_VALUE = 437

# hour -> the share of the daily peak, two evening/morning humps plus a night floor
WEEKDAY_PROFILE = {h: 0.13 for h in range(24)}
for _hour, center, width, height in ((8, 8.0, 1.5, 1.0), (18, 18.2, 1.7, 1.12)):
    for h in range(24):
        WEEKDAY_PROFILE[h] += height * np.exp(-0.5 * ((h - center) / width) ** 2)
WEEKEND_PROFILE = {h: 0.15 for h in range(24)}
for h in range(24):
    WEEKEND_PROFILE[h] += 0.75 * np.exp(-0.5 * ((h - 13.5) / 3.6) ** 2)


def _base_shape(kind: str, hour: int) -> float:
    if kind == "weekday":
        return float(WEEKDAY_PROFILE[hour])
    if kind == "weekend":
        return float(WEEKEND_PROFILE[hour]) * 0.92
    return (0.30 + float(WEEKEND_PROFILE[hour]) * 0.70) * 0.68


def _event_effects(day: dt.date, hour: int):
    """(volume multiplier, speed multiplier) for reviewed events, on their real dates."""
    vol, speed = 1.0, 1.0

    def window(name_span, hours, v, s):
        nonlocal vol, speed
        if day in name_span and (hours is None or hours[0] <= hour < hours[1]):
            vol *= v
            speed *= s

    # accidents: an 8-12 hour block on the reviewed day
    window({dt.date(2023, 10, 26)}, (10, 18), 0.45, 0.55)
    window({dt.date(2024, 6, 2)}, (11, 21), 0.42, 0.6)
    window({dt.date(2025, 2, 25)}, (7, 17), 0.44, 0.5)
    window({dt.date(2025, 12, 15)}, (0, 9), 0.5, 0.6)
    window({dt.date(2025, 12, 16)}, (0, 8), 0.6, 0.7)
    # other: the sewer collapse on Московский проспект
    window({dt.date(2025, 5, 20)}, (9, 20), 0.52, 0.65)
    # roadworks: multi-day pattern shifts on the reviewed works' windows
    window(
        {dt.date(y, m, d) for y in (2023,) for m, ds in ((10, range(13, 20)),) for d in ds},
        None,
        0.75,
        0.7,
    )
    window({dt.date(2024, 4, d) for d in range(19, 30)}, None, 0.78, 0.68)
    window({dt.date(2024, 5, 25), dt.date(2024, 5, 26), dt.date(2024, 5, 27)}, None, 0.88, 0.85)
    window({dt.date(2025, 10, d) for d in range(8, 16)}, None, 0.8, 0.7)
    # weather waves: slow and thinner traffic on the reviewed dates
    window({dt.date(2023, 6, 3)}, (15, 23), 0.8, 0.45)
    window({dt.date(2023, 6, 4)}, (0, 8), 0.9, 0.75)
    window({dt.date(2023, 12, 12), dt.date(2023, 12, 13)}, None, 0.82, 0.55)
    window({dt.date(2023, 12, 15), dt.date(2023, 12, 16), dt.date(2023, 12, 17)}, None, 0.72, 0.45)
    window({dt.date(2024, 2, 8), dt.date(2024, 2, 9)}, None, 0.86, 0.6)
    window({dt.date(2024, 2, 12)}, None, 0.75, 0.5)
    window({dt.date(2025, 8, 3)}, (19, 24), 0.6, 0.45)
    window({dt.date(2025, 8, 4)}, (0, 10), 0.85, 0.7)
    # holidays: the generic holiday shape comes from day_kind; these reviewed days
    # additionally differ from their own holiday norm
    window({dt.date(2023, 1, 1)}, None, 0.65, 1.0)
    window({dt.date(2025, 1, 1)}, None, 0.63, 1.0)
    window({dt.date(2023, 5, 9)}, (8, 14), 0.3, 0.6)
    window({dt.date(2024, 5, 1)}, (9, 20), 1.38, 0.9)
    window({dt.date(2025, 5, 1)}, (10, 18), 1.3, 0.92)
    return vol, speed


def _truck_mix(rng: np.random.Generator, hour: int, doy: int):
    """Vehicle class shares per hour: trucks dominate the night, bikes the summer."""
    night = hour < 6 or hour >= 22
    cars = rng.uniform(0.48, 0.56) if night else rng.uniform(0.60, 0.68)
    small = rng.uniform(0.09, 0.13)
    medium = rng.uniform(0.04, 0.07)
    large = rng.uniform(0.06, 0.11) if night else rng.uniform(0.03, 0.06)
    trains = rng.uniform(0.02, 0.05) if night else rng.uniform(0.005, 0.03)
    buses = rng.uniform(0.0, 0.004) if night else rng.uniform(0.004, 0.014)
    motorcycles = rng.uniform(0.0, 0.001) if (doy < 100 or doy > 300) else rng.uniform(0.0, 0.018)
    return cars, small, medium, large, trains, buses, motorcycles


def _dead_hours(sensor: str, day: dt.date):
    """Hours of this sensor that never appear in the export (connection/power lost)."""
    if day == dt.date(2023, 7, 9) and sensor == SECTIONS[0][0]:
        return range(0, 24)
    if day in (dt.date(2024, 2, 21), dt.date(2024, 2, 22)) and sensor == SECTIONS[1][0]:
        return range(0, 24)
    if day == dt.date(2023, 9, 28) and sensor == SECTIONS[0][0]:
        return range(6, 12)
    if day == dt.date(2025, 3, 18) and sensor == SECTIONS[0][0]:
        return range(3, 9)
    return ()


def _incomplete_day(sensor: str, day: dt.date) -> int:
    """The export cut off at this hour for this sensor (an incomplete day)."""
    if day == dt.date(2025, 11, 5) and sensor == SECTIONS[1][0]:
        return 19
    return 24


def generate(raw_dir: Path = RAW_DIR) -> None:
    rng = np.random.default_rng(SEED)
    raw_dir.mkdir(parents=True, exist_ok=True)
    total_hours = {sensor: 0 for sensor, _ in SECTIONS}

    for year in YEARS:
        book = Workbook(write_only=True)
        sheet = book.create_sheet(f"Отчёт {year}")
        first = dt.datetime(year, 1, 1, tzinfo=MSK)
        days = (dt.date(year + 1, 1, 1) - dt.date(year, 1, 1)).days
        stamps = [first + dt.timedelta(hours=h) for h in range(days * 24)]
        year_rows = 0
        for sensor, scale in SECTIONS:
            rows = 0
            sheet.append(["Отчёт по участку а/д А-134, подъезд к г. Воронеж"])
            sheet.append([sensor])
            for ts in stamps:
                day, hour = ts.date(), ts.hour
                if hour in _dead_hours(sensor, day) or hour >= _incomplete_day(sensor, day):
                    continue

                kind = day_kind(day)
                doy = ts.timetuple().tm_yday
                seasonal = 1 + 0.10 * np.sin(2 * np.pi * (doy - 105) / 365)
                if 120 < doy < 260:
                    seasonal += 0.05  # дачный сезон
                weekly = {0: 1.0, 1: 1.0, 2: 1.02, 3: 1.03, 4: 1.06, 5: 1.05, 6: 1.04}[
                    day.weekday()
                ]
                boost = 1.0
                if day.weekday() == 4 and hour in range(16, 21):
                    boost = 1.08  # вечер пятницы: выезд из города
                if day.weekday() == 6 and hour in range(16, 22):
                    boost = 1.06  # вечер воскресенья: возврат

                ev_vol, ev_speed = _event_effects(day, hour)

                volume = (
                    520
                    * scale
                    * _base_shape(kind, hour)
                    * seasonal
                    * weekly
                    * boost
                    * ev_vol
                    * rng.normal(1, 0.045)
                )
                volume = int(max(volume, 1))

                share = rng.normal(0.5, 0.03)
                if day.weekday() == 4 and hour >= 16:
                    share -= 0.06
                if day.weekday() == 6 and 15 <= hour < 21:
                    share -= 0.07
                share = float(np.clip(share, 0.32, 0.68))
                volume_direct = int(volume * share)
                volume_reverse = volume - volume_direct

                loaded = volume_direct / 2000 * 100
                free = 84 - (0 if sensor == SECTIONS[0][0] else 4)
                speed_direct = free - 95 * max(loaded / 100 - 0.30, 0)
                speed_direct *= ev_speed
                speed_direct = float(np.clip(speed_direct + rng.normal(0, 3.0), 8, 95))
                speed_reverse = float(np.clip(speed_direct + rng.normal(0, 2.5), 8, 95))
                load_direct = float(np.clip(loaded + rng.normal(0, 1.2), 0.3, 97))
                load_reverse = float(np.clip(load_direct + rng.normal(0, 1.2), 0.3, 97))

                # zero speed while cars pass: the speed channel died (sensor incident)
                if day == dt.date(2025, 3, 19) and hour in range(2, 6) and sensor == SECTIONS[0][0]:
                    speed_direct = 0.0

                cars, small, medium, large, trains, buses, motorcycles = _truck_mix(rng, hour, doy)
                others = {
                    "small_trucks": int(volume * small),
                    "medium_trucks": int(volume * medium),
                    "large_trucks": int(volume * large),
                    "road_trains": int(volume * trains),
                    "buses": int(volume * buses),
                    "motorcycles": int(volume * motorcycles),
                }
                cars_count = volume - sum(others.values())

                split = {"direct": share, "reverse": 1 - share}
                row = [ts.replace(tzinfo=None), volume, volume_direct, volume_reverse]
                for total in (cars_count, *others.values()):
                    half = int(total * split["direct"] + 0.5)
                    row.extend([total, half, total - half])
                row.extend(
                    [
                        round(speed_direct, 1),
                        round(speed_reverse, 1),
                        round(load_direct, 1),
                        round(load_reverse, 1),
                    ]
                )
                if sensor == SECTIONS[0][0] and ts.replace(tzinfo=None) in STUCK_HOURS:
                    # stuck counter: one and the same value for hours, other columns idle
                    row[1] = row[2] = STUCK_VALUE
                    row[3] = 0
                sheet.append(row)
                rows += 1
            total_hours[sensor] += rows
            year_rows += rows
        path = raw_dir / f"a134_export_{year}.xlsx"
        book.save(path)
        print(f"{path.name}: {year_rows} hours written for {len(SECTIONS)} sections")

    print("raw export generated:")
    for sensor, rows in total_hours.items():
        print(f"  {sensor}: {rows} hours")


SEED_A133 = 20251115

A133_SECTIONS = [
    ("км 12+000 а/д А-133", 0.80),  # sensor km 12 (about Елецкая Лозовка, Хлевенский округ)
    ("км 40+000 а/д А-133", 1.00),  # sensor km 40 (about Боринское, closer to the city)
]

A133_STUCK_HOURS = {
    dt.datetime(2024, 8, 14, 21),
    dt.datetime(2024, 8, 14, 22),
    dt.datetime(2024, 8, 14, 23),
    dt.datetime(2024, 8, 15, 0),
    dt.datetime(2024, 8, 15, 1),
    dt.datetime(2024, 8, 15, 2),
    dt.datetime(2024, 8, 15, 3),
}
A133_STUCK_VALUE = 311

# hour ranges of the km 12 reporter's twelve silent hours (the whole run reads zero)
A133_ZERO_TELEMETRY = {dt.datetime(2025, 2, 4, h) for h in range(0, 12)}


def _a133_event_effects(day: dt.date, hour: int):
    """(volume multiplier, speed multiplier) for the reviewed A-133 events, on dates
    checked against gorod48/newslipetsk/zr.ru/oka.fm and the official calendar."""
    vol, speed = 1.0, 1.0

    def window(name_span, hours, v, s):
        nonlocal vol, speed
        if day in name_span and (hours is None or hours[0] <= hour < hours[1]):
            vol *= v
            speed *= s

    # accidents, on their published dates (the morning after a night crash stays slow)
    window({dt.date(2023, 12, 22)}, (15, 24), 0.55, 0.6)  # массовая авария у Боринского
    window({dt.date(2023, 12, 23)}, (0, 4), 0.8, 0.85)
    window({dt.date(2024, 9, 26)}, (0, 10), 0.6, 0.7)  # «Дон», 349-й км, около 01:00
    window({dt.date(2024, 12, 30)}, (0, 15), 0.4, 0.5)  # А-133, 20-й км, около 02:00
    window({dt.date(2024, 12, 31)}, (0, 7), 0.65, 0.75)
    window({dt.date(2025, 4, 18)}, (11, 20), 0.5, 0.6)  # Грязи-Липецк, пожар после ДТП
    window({dt.date(2025, 11, 24)}, (13, 22), 0.6, 0.65)  # Липецк-Грязи, дерево
    window({dt.date(2025, 12, 29)}, (14, 24), 0.5, 0.6)  # Липецк-Хлевное, двое погибли
    window({dt.date(2025, 12, 30)}, (0, 7), 0.7, 0.8)
    # weather: мокрый снег на М-4 и подходах, прогноз на 19-20.12.2024 (zr.ru)
    window({dt.date(2024, 12, 19)}, None, 0.8, 0.6)
    window({dt.date(2024, 12, 20)}, None, 0.75, 0.5)
    window({dt.date(2024, 12, 21)}, None, 0.9, 0.65)
    # roadworks: the repair season, the М-4 section works, two city/oblast stretches
    window({dt.date(2024, 4, d) for d in range(19, 31)}, None, 0.82, 0.62)
    window(
        {dt.date(2024, 7, d) for d in range(24, 29)},
        (10, 18),
        0.85,
        0.62,
    )  # перекрытие Карла Маркса и разъезды
    window({dt.date(2025, 9, d) for d in range(15, 29)}, None, 0.86, 0.62)
    window({dt.date(2025, 11, d) for d in range(8, 15)}, None, 0.9, 0.6)
    # holidays: the generic shape comes from day_kind; these days additionally differ
    # from their own holiday norm
    window({dt.date(2023, 1, 1)}, None, 0.65, 1.0)
    window({dt.date(2025, 1, 1)}, None, 0.63, 1.0)
    window({dt.date(2023, 5, 9)}, (8, 14), 0.35, 0.7)
    window({dt.date(2025, 5, 9)}, (8, 14), 0.35, 0.7)
    # other: День города-2023 (14-16 июля, вечерние пики к площадкам), ночные БПЛА
    window({dt.date(2023, 7, 14), dt.date(2023, 7, 15)}, (12, 19), 1.42, 0.85)
    window({dt.date(2024, 4, 19)}, (20, 24), 0.55, 0.6)
    window({dt.date(2025, 7, 17)}, (0, 5), 0.45, 0.6)
    return vol, speed


def _a133_dead_hours(sensor: str, day: dt.date):
    """Hours of this sensor that never appear in the export (connection/power lost)."""
    if day == dt.date(2023, 8, 9) and sensor == A133_SECTIONS[0][0]:
        return range(0, 24)
    if day == dt.date(2024, 3, 3) and sensor == A133_SECTIONS[1][0]:
        return range(0, 24)
    if day == dt.date(2024, 3, 4) and sensor == A133_SECTIONS[1][0]:
        return range(0, 11)
    if day == dt.date(2024, 9, 28) and sensor == A133_SECTIONS[0][0]:
        return range(6, 12)
    if day == dt.date(2025, 11, 17) and sensor == A133_SECTIONS[1][0]:
        return range(18, 24)  # the evening the city centre lost power
    return ()


def _a133_incomplete_day(sensor: str, day: dt.date) -> int:
    """The export cut off at this hour for this sensor (an incomplete day)."""
    if day == dt.date(2025, 10, 9) and sensor == A133_SECTIONS[1][0]:
        return 19
    return 24


def generate_a133() -> None:
    """Write the A-133 demo exports: a133_export_<year>.xlsx, two sections, 2023-2025."""
    from analysis.a133.holidays import day_kind
    from analysis.a133.parse import MSK, RAW_DIR

    rng = np.random.default_rng(SEED_A133)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    total_hours = {sensor: 0 for sensor, _ in A133_SECTIONS}

    for year in YEARS:
        book = Workbook(write_only=True)
        sheet = book.create_sheet(f"Отчёт {year}")
        first = dt.datetime(year, 1, 1, tzinfo=MSK)
        days = (dt.date(year + 1, 1, 1) - dt.date(year, 1, 1)).days
        stamps = [first + dt.timedelta(hours=h) for h in range(days * 24)]
        year_rows = 0
        for sensor, scale in A133_SECTIONS:
            rows = 0
            sheet.append(["Отчёт по участку а/д А-133, подъезд к г. Липецк"])
            sheet.append([sensor])
            for ts in stamps:
                day, hour = ts.date(), ts.hour
                if hour in _a133_dead_hours(sensor, day) or hour >= _a133_incomplete_day(
                    sensor, day
                ):
                    continue

                kind = day_kind(day)
                doy = ts.timetuple().tm_yday
                seasonal = 1 + 0.10 * np.sin(2 * np.pi * (doy - 105) / 365)
                if 120 < doy < 260:
                    seasonal += 0.05  # дачный сезон
                weekly = {0: 1.0, 1: 1.0, 2: 1.02, 3: 1.03, 4: 1.06, 5: 1.05, 6: 1.04}[
                    day.weekday()
                ]
                boost = 1.0
                if day.weekday() == 4 and hour in range(16, 21):
                    boost = 1.08  # вечер пятницы: выезд с трассы в города и на дачи
                if day.weekday() == 6 and hour in range(16, 22):
                    boost = 1.06  # вечер воскресенья: возврат

                ev_vol, ev_speed = _a133_event_effects(day, hour)

                volume = (
                    360
                    * scale
                    * _base_shape(kind, hour)
                    * seasonal
                    * weekly
                    * boost
                    * ev_vol
                    * rng.normal(1, 0.045)
                )
                volume = int(max(volume, 1))

                share = rng.normal(0.5, 0.03)
                if day.weekday() == 4 and hour >= 16:
                    share -= 0.06
                if day.weekday() == 6 and 15 <= hour < 21:
                    share -= 0.07
                share = float(np.clip(share, 0.32, 0.68))
                volume_direct = int(volume * share)
                volume_reverse = volume - volume_direct

                loaded = volume_direct / 1000 * 100  # two-lane approach: capacity ~1000/h
                free = 87 - (0 if sensor == A133_SECTIONS[0][0] else 1)
                speed_direct = free - 95 * max(loaded / 100 - 0.30, 0)
                speed_direct *= ev_speed
                speed_direct = float(np.clip(speed_direct + rng.normal(0, 3.0), 8, 95))
                speed_reverse = float(np.clip(speed_direct + rng.normal(0, 2.5), 8, 95))
                load_direct = float(np.clip(loaded + rng.normal(0, 1.2), 0.3, 97))
                load_reverse = float(np.clip(load_direct + rng.normal(0, 1.2), 0.3, 97))

                # zero speed while cars pass: the speed channel died (sensor incident)
                if (
                    day == dt.date(2025, 3, 21)
                    and hour in range(2, 6)
                    and sensor == A133_SECTIONS[1][0]
                ):
                    speed_direct = 0.0

                cars, small, medium, large, trains, buses, motorcycles = _truck_mix(rng, hour, doy)
                others = {
                    "small_trucks": int(volume * small),
                    "medium_trucks": int(volume * medium),
                    "large_trucks": int(volume * large),
                    "road_trains": int(volume * trains),
                    "buses": int(volume * buses),
                    "motorcycles": int(volume * motorcycles),
                }
                cars_count = volume - sum(others.values())
                if (
                    sensor == A133_SECTIONS[1][0]
                    and day.year == 2025
                    and day.month == 6
                    and 2 <= day.day <= 14
                    and 9 <= hour < 17
                ):
                    # systematic metering drift: the heavy track double-counted all June
                    # (added after cars_count on purpose - only then the class sum stops
                    # agreeing with the total, which is exactly what the audit hunts)
                    others["large_trucks"] += 6

                split = {"direct": share, "reverse": 1 - share}
                row = [ts.replace(tzinfo=None), volume, volume_direct, volume_reverse]
                for total in (cars_count, *others.values()):
                    half = int(total * split["direct"] + 0.5)
                    row.extend([total, half, total - half])
                row.extend(
                    [
                        round(speed_direct, 1),
                        round(speed_reverse, 1),
                        round(load_direct, 1),
                        round(load_reverse, 1),
                    ]
                )
                if (
                    sensor == A133_SECTIONS[0][0]
                    and day.year == 2024
                    and day.month == 11
                    and 4 <= day.day <= 16
                    and 8 <= hour < 16
                ):
                    # the reverse loop ran hot all November: parts outgrow the total
                    row[3] += 8
                if sensor == A133_SECTIONS[0][0] and ts.replace(tzinfo=None) in A133_STUCK_HOURS:
                    # stuck counter: one and the same value for hours, other columns idle
                    row[1] = row[2] = A133_STUCK_VALUE
                    row[3] = 0
                if sensor == A133_SECTIONS[0][0] and ts.replace(tzinfo=None) in A133_ZERO_TELEMETRY:
                    # the reporter went silent for half a day: every channel reads zero
                    row = [row[0], *([0] * 28)]
                sheet.append(row)
                rows += 1
            total_hours[sensor] += rows
            year_rows += rows
        path = RAW_DIR / f"a133_export_{year}.xlsx"
        book.save(path)
        print(f"{path.name}: {year_rows} hours written for {len(A133_SECTIONS)} sections")

    print("raw export generated:")
    for sensor, rows in total_hours.items():
        print(f"  {sensor}: {rows} hours")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "a133":
        generate_a133()
    else:
        generate()
