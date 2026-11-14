import shutil
from datetime import datetime
from pathlib import Path

import pytest

from backend import load
from backend.db import connect, ensure_schema
from contract.validate import OUTPUT, read_road

EXAMPLE = OUTPUT / "_example"

CENSUS = ("sensors", "measurements", "anomalies", "events")


@pytest.fixture
def db(tmp_path):
    db = connect(str(tmp_path / "test.db"))
    ensure_schema(db)
    yield db
    db.close()


def counts(db) -> dict[str, int]:
    return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in CENSUS}


def counts_in_files(directory: Path = EXAMPLE) -> dict[str, int]:
    files = read_road(directory)
    return {
        "sensors": len(files.road.sensors),
        "measurements": len(files.series),
        "anomalies": len(files.anomalies) + len(files.corporate_anomalies),
        "events": len(files.events),
    }


def test_loading_the_example_set_loads_every_file(db):
    load.load_road(db, EXAMPLE)
    assert counts(db) == counts_in_files()
    files = read_road(EXAMPLE)
    assert db.execute(
        "SELECT source, COUNT(*) FROM anomalies GROUP BY source ORDER BY source"
    ).fetchall() == [
        ("corporate", len(files.corporate_anomalies)),
        ("ours", len(files.anomalies)),
    ]


def test_msk_stores_moscow_wall_clock_without_an_offset():
    msk = load.msk
    assert msk(datetime.fromisoformat("2025-03-08T23:30:00+03:00")) == "2025-03-08 23:30:00"
    # the same instants wearing other offsets come out identical, and 23:30 vs 00:30
    # of the next Moscow day land on different days, whatever these offsets are
    assert msk(datetime.fromisoformat("2025-03-08T20:30:00+00:00")) == "2025-03-08 23:30:00"
    assert msk(datetime.fromisoformat("2025-03-09T00:30:00+03:00")) == "2025-03-09 00:30:00"
    assert msk(datetime.fromisoformat("2025-03-08T22:30:00+01:00")) == "2025-03-09 00:30:00"


def test_loaded_hours_group_into_moscow_days(db):
    # the example series is the full Moscow days of 7, 8 and 9 March for two sensors
    load.load_road(db, EXAMPLE)
    assert db.execute(
        "SELECT date(ts), COUNT(*) FROM measurements GROUP BY date(ts) ORDER BY date(ts)"
    ).fetchall() == [("2025-03-07", 48), ("2025-03-08", 48), ("2025-03-09", 48)]


def test_loading_twice_changes_nothing(db):
    load.load_road(db, EXAMPLE)
    first = counts(db)
    load.load_road(db, EXAMPLE)
    assert counts(db) == first


def test_reload_replaces_data_without_duplicates(db, tmp_path):
    edited = Path(shutil.copytree(EXAMPLE, tmp_path / "_example"))
    lines = (edited / "series.csv").read_text("utf-8").splitlines()
    cells = lines[1].split(",")
    cells[2] = str(int(cells[2]) + 100)  # the volume column of the first sensor's first hour
    lines[1] = ",".join(cells)
    (edited / "series.csv").write_text("\n".join(lines) + "\n", "utf-8")

    load.load_road(db, EXAMPLE)
    volume_before = db.execute("SELECT SUM(volume) FROM measurements").fetchone()[0]
    load.load_road(db, edited)
    assert counts(db) == counts_in_files()
    assert db.execute("SELECT SUM(volume) FROM measurements").fetchone()[0] == volume_before + 100


def test_a_broken_road_loads_nothing_and_exits_nonzero(db, tmp_path, capsys, monkeypatch):
    broken = Path(shutil.copytree(EXAMPLE, tmp_path / "_example"))
    (broken / "anomalies.json").write_text("{ not json", "utf-8")
    monkeypatch.setattr(load, "OUTPUT", tmp_path)

    assert load.main(["_example"], db) == 1
    printed = capsys.readouterr().out
    assert "anomalies.json" in printed and "not valid JSON" in printed
    assert counts(db) == dict.fromkeys(CENSUS, 0)


def test_a_crash_midway_leaves_the_previous_data_intact(db, monkeypatch):
    load.load_road(db, EXAMPLE)
    original = load.anomaly_rows
    monkeypatch.setattr(
        load,
        "anomaly_rows",
        lambda out, road: [(r[0], "bogus", *r[2:]) for r in original(out, road)],
    )
    with pytest.raises(ValueError):
        load.load_road(db, EXAMPLE)  # an invalid source fails on the anomalies INSERT
    assert counts(db) == counts_in_files()  # the rolled-back reload deleted and lost nothing


def test_main_loads_every_road_and_prints_one_line_per_road(db, tmp_path, capsys, monkeypatch):
    shutil.copytree(EXAMPLE, tmp_path / "_example")
    monkeypatch.setattr(load, "OUTPUT", tmp_path)

    assert load.main([], db) == 0
    assert capsys.readouterr().out == (
        "_example: 2 sensors, 144 measurements, 6 anomalies (4 ours + 2 corporate), 3 events\n"
    )
    assert load.main(["_example"], db) == 0  # the second run says the same and changes nothing
    assert counts(db) == counts_in_files()
