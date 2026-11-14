"""SQL for /api/meta."""

import libsql


def road_rows(db: libsql.Connection) -> list[tuple]:
    """One (road, road_name, sensor count) row per loaded road."""
    return db.execute(
        "SELECT road, road_name, COUNT(*) FROM sensors GROUP BY road, road_name ORDER BY road"
    ).fetchall()


def period_row(db: libsql.Connection) -> tuple:
    """The first and the last day with measurements."""
    return db.execute("SELECT date(MIN(ts)), date(MAX(ts)) FROM measurements").fetchone()
