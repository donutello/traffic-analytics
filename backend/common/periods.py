"""Time helpers shared by the API and the import.

The database stores naive Moscow wall-clock text (backend/schema.sql); the contract
and the API speak ISO 8601 with an offset. Russia has no DST, so the offset is +03:00.
"""

from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

MOSCOW = "+03:00"
MOSCOW_TZ = timezone(timedelta(hours=3))
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

MONTHS = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]


def with_offset(stored: str) -> str:
    """Naive Moscow text from the database ('2025-03-08 09:00:00') to contract time."""
    return f"{stored[:10]}T{stored[11:]}{MOSCOW}"


def parse_bound(value: str | None, end: bool) -> str | None:
    """A from/to parameter to naive Moscow text for comparing with the stored columns.

    A plain date means the whole Moscow day: as an end bound it becomes the next
    midnight, which every period filter here compares strictly (ts < to, starts_at < to).
    """
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(422, f"bad time {value!r}: write it as a date or ISO 8601") from exc
    if moment.tzinfo is None:  # a time without an offset is read as Moscow wall-clock time
        moment = moment.replace(tzinfo=MOSCOW_TZ)
    if end and len(value) == 10:
        moment += timedelta(days=1)
    return moment.astimezone(MOSCOW_TZ).strftime(TIME_FORMAT)


def parse_moment(stored: str) -> datetime:
    return datetime.strptime(stored, TIME_FORMAT)


def day_label(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]}"


def time_label(moment: datetime) -> str:
    return f"{moment.day} {MONTHS[moment.month - 1]}, {moment:%H:%M}"


def period_conditions(lo: str | None, hi: str | None, alias: str) -> list[tuple[str, str]]:
    """Interval overlap of [starts_at, ends_at) with [lo, hi), as (sql, value) pairs."""
    parts = []
    if lo:
        parts.append((f"{alias}.ends_at > ?", lo))
    if hi:
        parts.append((f"{alias}.starts_at < ?", hi))
    return parts
