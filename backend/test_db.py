import pytest

from backend.db import connect, ensure_schema

INSERT_HOUR = (
    "INSERT INTO measurements (sensor_id, ts, volume, volume_direct, volume_reverse, state) "
    "VALUES (?, ?, 10, 5, 5, 'normal')"
)


@pytest.fixture
def db(tmp_path):
    db = connect(str(tmp_path / "test.db"))
    yield db
    db.close()


def test_connect_runs_sql(tmp_path):
    db = connect(str(tmp_path / "test.db"))
    db.execute("CREATE TABLE sensors (id TEXT PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO sensors VALUES (?, ?)", ("a134-km12", "км 12+300"))
    db.commit()
    assert db.execute("SELECT name FROM sensors").fetchall() == [("км 12+300",)]
    db.close()


def add_sensor(db, sensor_id: str = "_example-km12", road: str = "_example") -> None:
    db.execute(
        "INSERT INTO sensors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sensor_id, road, "Пример", "км 12+300", 12.3, 51.7, 39.2, "в город", "из города"),
    )


def test_ensure_schema_creates_every_table(db):
    ensure_schema(db)
    names = {row[0] for row in db.execute("SELECT name FROM sqlite_master").fetchall()}
    assert {"sensors", "events", "measurements", "anomalies"} <= names
    assert ("idx_anomalies_sensor_starts",) in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    ).fetchall()


def test_ensure_schema_is_idempotent(db):
    ensure_schema(db)
    db.execute(
        "INSERT INTO events VALUES ('a134-x', 'a134', '2025-03-08', 'accident', 'ДТП', null, "
        "'https://example.com')"
    )
    db.commit()
    ensure_schema(db)  # a second run over a filled database must keep everything
    assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_same_sensor_hour_cannot_be_added_twice(db):
    # the measurements key (sensor_id, ts) is the contract rule of one line per hour
    ensure_schema(db)
    add_sensor(db)
    db.execute(INSERT_HOUR, ("_example-km12", "2025-03-08 23:00:00"))
    with pytest.raises(ValueError):
        db.execute(INSERT_HOUR, ("_example-km12", "2025-03-08 23:00:00"))


def test_day_grouping_splits_at_the_moscow_midnight(db):
    """The stored text is naive Moscow wall-clock time (see backend/schema.sql), so date()
    groups by Moscow calendar days whatever timezone this machine runs in: the hours 23:30
    and 00:30 fall into two different days."""
    ensure_schema(db)
    add_sensor(db)
    for hour in ("2025-03-08 23:30:00", "2025-03-09 00:30:00", "2025-03-09 01:30:00"):
        db.execute(INSERT_HOUR, ("_example-km12", hour))
    db.commit()
    assert db.execute(
        "SELECT date(ts), COUNT(*) FROM measurements GROUP BY date(ts) ORDER BY date(ts)"
    ).fetchall() == [("2025-03-08", 1), ("2025-03-09", 2)]


def test_week_grouping_splits_at_the_moscow_monnight(db):
    """Same for weeks: 23:30 on Sunday and 00:30 on Monday are hours of two Moscow weeks."""
    ensure_schema(db)
    add_sensor(db)
    for hour in ("2025-03-09 23:30:00", "2025-03-10 00:30:00"):
        db.execute(INSERT_HOUR, ("_example-km12", hour))
    db.commit()
    assert db.execute(
        "SELECT strftime('%Y-%W', ts), COUNT(*) FROM measurements "
        "GROUP BY strftime('%Y-%W', ts) ORDER BY 1"
    ).fetchall() == [("2025-09", 1), ("2025-10", 1)]
