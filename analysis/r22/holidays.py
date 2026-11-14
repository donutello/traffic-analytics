"""Official Russian non-working days 2023-2026, used as a "kind of day" for the norms.

The detectors compare every hour with the same kind of day, so the module must know
the official holidays and transfer days. This module's export covers the whole
2023-2026 window, so every year below is read; the table is the verified one the other
road modules use. The days below are the non-working
public holiday days plus the weekend days the government moved to a weekday, per year:

- 2023: Decree of the Russian Government No. 1505 of 29.08.2022 on transfer of days
  (Jan 1 -> Feb 24, Jan 8 -> May 8); see the production calendar page
  https://www.consultant.ru/law/ref/calendar/proizvodstvennye/2023/
- 2024: Decree No. 1314 of 10.08.2023 (Jan 6 -> May 10, Apr 27 -> Apr 29, Nov 2 -> Apr 30,
  Dec 28 -> Dec 30, Jan 7 -> Dec 31);
  https://www.consultant.ru/document/cons_doc_LAW_449986/262c5d0d25135393aa6fe898ec1141cd79f3ddf2/
- 2025: Decree No. 1335 of 04.10.2024 (Jan 4 -> May 2, Feb 23 -> May 8, Mar 8 -> Jun 13,
  Nov 1 -> Nov 3, Jan 5 -> Dec 31);
  https://www.consultant.ru/law/ref/calendar/proizvodstvennye/2025/
- 2026: Decree No. 1466 of 24.09.2025 (Jan 3 -> Jan 9, Jan 4 -> Dec 31) plus
  Mar 9 and May 11, the extra Mondays the holidays of Mar 8 and May 9 fall onto;
  https://www.consultant.ru/law/ref/calendar/proizvodstvennye/2026/

Weekend days in the set are kept so the whole rest-period is one kind of day; in
`day_kind` a holiday wins over an ordinary weekend.
"""

import datetime
import itertools

RANGE_2023 = frozenset(
    {datetime.date(2023, 1, day) for day in range(1, 9)}
    | {
        datetime.date(2023, 2, 23),
        datetime.date(2023, 2, 24),
        datetime.date(2023, 3, 8),
        datetime.date(2023, 5, 1),
        datetime.date(2023, 5, 8),
        datetime.date(2023, 5, 9),
        datetime.date(2023, 6, 12),
        datetime.date(2023, 11, 4),
    }
)

RANGE_2024 = frozenset(
    {datetime.date(2024, 1, day) for day in range(1, 9)}
    | {
        datetime.date(2024, 2, 23),
        datetime.date(2024, 3, 8),
        datetime.date(2024, 4, 29),
        datetime.date(2024, 4, 30),
        datetime.date(2024, 5, 1),
        datetime.date(2024, 5, 9),
        datetime.date(2024, 5, 10),
        datetime.date(2024, 6, 12),
        datetime.date(2024, 11, 4),
        datetime.date(2024, 12, 30),
        datetime.date(2024, 12, 31),
    }
)

RANGE_2025 = frozenset(
    {datetime.date(2025, 1, day) for day in range(1, 9)}
    | {
        datetime.date(2025, 2, 23),
        datetime.date(2025, 3, 8),
        datetime.date(2025, 5, 1),
        datetime.date(2025, 5, 2),
        datetime.date(2025, 5, 8),
        datetime.date(2025, 5, 9),
        datetime.date(2025, 6, 12),
        datetime.date(2025, 6, 13),
        datetime.date(2025, 11, 3),
        datetime.date(2025, 11, 4),
        datetime.date(2025, 12, 31),
    }
)

RANGE_2026 = frozenset(
    {datetime.date(2026, 1, day) for day in range(1, 9)}
    | {
        datetime.date(2026, 1, 9),
        datetime.date(2026, 2, 23),
        datetime.date(2026, 3, 9),
        datetime.date(2026, 5, 1),
        datetime.date(2026, 5, 9),
        datetime.date(2026, 5, 11),
        datetime.date(2026, 6, 12),
        datetime.date(2026, 11, 4),
        datetime.date(2026, 12, 31),
    }
)

HOLIDAYS: frozenset[datetime.date] = frozenset(
    itertools.chain(RANGE_2023, RANGE_2024, RANGE_2025, RANGE_2026)
)
"""Every day Russia did not work in 2023-2026 (holidays plus transferred days)."""


def day_kind(ts) -> str:
    """Kind of day of a timestamp: holiday, weekend or weekday (holiday wins)."""
    moment = ts.date() if hasattr(ts, "date") else ts
    if moment in HOLIDAYS:
        return "holiday"
    return "weekend" if moment.weekday() >= 5 else "weekday"


def day_group(ts) -> str:
    """Norm pool key of a day: its weekday number, or holiday for every day off.

    The hourly and daily norms compare a day with earlier and later days that traffic
    should look like: the same weekday, with all days off pooled into one group, since
    a holiday profile has little to do with the weekday it would have been.
    """
    moment = ts.date() if hasattr(ts, "date") else ts
    return "holiday" if moment in HOLIDAYS else f"weekday-{moment.weekday()}"
