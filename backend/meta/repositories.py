"""SQL for /api/meta."""

import libsql


def road_rows(db: libsql.Connection) -> list[tuple]:
    """One (road, road_name, sensor count) row per loaded road."""
    return db.execute(
        "SELECT road, road_name, COUNT(*) FROM sensors GROUP BY road, road_name ORDER BY road"
    ).fetchall()


def period_row(db: libsql.Connection) -> tuple:
    """The first and the last day with measurements.

    MIN and MAX are two queries on purpose: SQLite turns a lone MIN or MAX into one
    seek into the ends of the ts index (backend/schema.sql), but with both in one
    query it reads every index entry instead.
    """
    first = db.execute("SELECT date(MIN(ts)) FROM measurements").fetchone()[0]
    last = db.execute("SELECT date(MAX(ts)) FROM measurements").fetchone()[0]
    return first, last
