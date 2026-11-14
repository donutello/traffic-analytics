"""SQL for /api/anomalies; the comparison feature reads the same anomaly rows."""

from datetime import date

import libsql

ANOMALY_COLUMNS = [
    "id",
    "source",
    "road",
    "sensor_id",
    "starts_at",
    "ends_at",
    "category",
    "type",
    "detector",
    "level",
    "metric",
    "actual",
    "expected",
    "deviation_pct",
    "score",
    "is_mega",
    "event_id",
    "description",
]

# sensor_name comes from sensors (docs/contract.md); the extra column is the last one.
ANOMALY_SELECT = (
    "SELECT a."
    + ", a.".join(ANOMALY_COLUMNS)
    + ", s.name FROM anomalies a JOIN sensors s ON s.id = a.sensor_id"
)


def find_anomalies(
    db: libsql.Connection, conditions: list[tuple[str, str]], order: str
) -> list[tuple]:
    """The anomaly rows (+ joined sensor_name as the last column) matching the filters."""
    where = " WHERE " + " AND ".join(sql for sql, _ in conditions) if conditions else ""
    args = [value for _, value in conditions]
    return db.execute(ANOMALY_SELECT + where + f" ORDER BY {order}", args).fetchall()


def find_anomaly(db: libsql.Connection, anomaly_id: str) -> tuple | None:
    return db.execute(ANOMALY_SELECT + " WHERE a.id = ?", (anomaly_id,)).fetchone()


def find_event(db: libsql.Connection, event_id: str) -> tuple | None:
    return db.execute(
        "SELECT id, date, category, title, description, source_url FROM events WHERE id = ?",
        (event_id,),
    ).fetchone()


def data_last_day(db: libsql.Connection) -> date | None:
    """The last day of the stored data: 'N дней назад' counts from it, as gen_mock does."""
    row = db.execute("SELECT date(MAX(ts)) FROM measurements").fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None
