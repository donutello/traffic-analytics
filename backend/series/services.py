"""Business logic for /api/series: point shapes and the day/week rollups."""

from datetime import date

import libsql

from backend.common.periods import day_label, with_offset
from backend.series import repositories


def points(db: libsql.Connection, sensor: str, granularity: str, lo: str | None, hi: str | None):
    """One sensor's series; day and week groups average the hours of the group (gen_mock)."""
    if granularity == "hour":
        rows = repositories.hour_rows(db, sensor, lo, hi)
        return [
            {"ts": with_offset(ts), "label": ts[11:16], "volume": volume, "state": state}
            for ts, volume, state in rows
        ]

    # day buckets are Moscow calendar days; a week bucket starts on its Moscow Monday
    bucket = "date(m.ts)" if granularity == "day" else "date(m.ts, 'weekday 0', '-6 days')"
    points = []
    for day, total, hours, any_anomaly, any_imputed in repositories.bucket_rows(
        db, sensor, lo, hi, bucket
    ):
        state = "anomaly" if any_anomaly else "imputed" if any_imputed else "normal"
        points.append(
            {
                "ts": day,
                "label": day_label(date.fromisoformat(day)),
                "volume": round(total / hours),
                "state": state,
            }
        )
    return points
