"""Business logic for /api/meta."""

import libsql

from backend.meta import repositories


def meta(db: libsql.Connection) -> dict:
    roads = [
        {"code": road, "name": road_name, "sensors": count}
        for road, road_name, count in repositories.road_rows(db)
    ]
    period = repositories.period_row(db)
    return {"roads": roads, "period": {"from": period[0], "to": period[1]}}
