"""SQL for /api/series. Grouping the hours into day and week buckets happens in SQL (ADR 0005)."""

import libsql

# An hour counts as inside our anomaly interval even when it only touches its edge:
# exactly the rule tools/gen_mock.py used, so /api/series reproduces the mock files.
COVERED_HOUR = """EXISTS (
        SELECT 1 FROM anomalies a
        WHERE a.source = 'ours' AND a.sensor_id = m.sensor_id
          AND a.starts_at <= datetime(m.ts, '+1 hour') AND a.ends_at >= m.ts)"""


def _period(lo: str | None, hi: str | None) -> tuple[str, list[str]]:
    bounds, args = ["m.sensor_id = ?"], []
    if lo:
        bounds.append("m.ts >= ?")
        args.append(lo)
    if hi:
        bounds.append("m.ts < ?")
        args.append(hi)
    return " AND ".join(bounds), args


def hour_rows(db: libsql.Connection, sensor: str, lo: str | None, hi: str | None) -> list[tuple]:
    where, args = _period(lo, hi)
    return db.execute(
        f"SELECT m.ts, m.volume, CASE WHEN {COVERED_HOUR} THEN 'anomaly' ELSE m.state END"
        f" AS state FROM measurements m WHERE {where} ORDER BY m.ts",
        [sensor, *args],
    ).fetchall()


def bucket_rows(
    db: libsql.Connection, sensor: str, lo: str | None, hi: str | None, bucket: str
) -> list[tuple]:
    """One (bucket, volume sum, hours, any anomaly, any imputed) row per group."""
    where, args = _period(lo, hi)
    return db.execute(
        f"SELECT {bucket} AS bucket, SUM(m.volume), COUNT(*), MAX({COVERED_HOUR}),"
        f" MAX(m.state = 'imputed') FROM measurements m WHERE {where}"
        " GROUP BY bucket ORDER BY bucket",
        [sensor, *args],
    ).fetchall()
