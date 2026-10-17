from backend.db import connect


def test_connect_runs_sql(tmp_path):
    db = connect(str(tmp_path / "test.db"))
    db.execute("CREATE TABLE sensors (id TEXT PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO sensors VALUES (?, ?)", ("a134-km12", "км 12+300"))
    db.commit()
    assert db.execute("SELECT name FROM sensors").fetchall() == [("км 12+300",)]
    db.close()
