"""The response cache of the API (issue #8, docs/load-test.md): it serves the stored
answers and the import throws them away."""

import pytest
from fastapi.testclient import TestClient

from backend.common import cache
from backend.db import connect, ensure_schema, get_db
from backend.load import main as load
from backend.main import app


@pytest.fixture
def db(tmp_path):
    db = connect(str(tmp_path / "cache.db"))
    ensure_schema(db)
    yield db
    db.close()


@pytest.fixture
def client(db):
    cache.clear()
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()
    cache.clear()


def test_a_second_answer_for_the_same_url_comes_from_the_cache(client, db):
    url = "/api/anomalies?road=_example"
    load(["_example"], db=db)
    assert len(client.get(url).json()["anomalies"]) == 6
    db.execute("DELETE FROM anomalies")  # the rows the dashboard reads are now gone
    db.commit()
    assert len(client.get(url).json()["anomalies"]) == 6  # the cached answer stays
    assert db.execute("SELECT COUNT(*) FROM anomalies").fetchone()[0] == 0


def test_the_import_clears_the_cache(client, db):
    url = "/api/anomalies?road=_example"
    assert client.get(url).json()["anomalies"] == []  # cached while the tables are empty
    assert load(["_example"], db=db) == 0
    assert len(client.get(url).json()["anomalies"]) == 6  # the fresh answer, not the old []
