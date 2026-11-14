import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.db import connect, get_db
from backend.load import main as load
from backend.main import app

MOCK = Path(__file__).resolve().parent.parent / "frontend" / "public" / "mock"
FULL_PERIOD = "from=2025-03-07&to=2025-03-09"  # everything the _example set contains
SENSORS = ("_example-km12", "_example-km47")
ANOMALY_IDS = (
    "_example-km12-0001",
    "_example-km12-0002",
    "_example-km47-0001",
    "_example-km47-0002",
    "_example-corp-0001",
    "_example-corp-0002",
)


def mock_file(*parts: str):
    return json.loads(MOCK.joinpath(*parts).read_text("utf-8"))


@pytest.fixture
def db(tmp_path):
    db = connect(str(tmp_path / "api.db"))
    assert load(["_example"], db=db) == 0
    yield db
    db.close()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health():
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------- series (issue #5)


@pytest.mark.parametrize("sensor", SENSORS)
@pytest.mark.parametrize("granularity", ["hour", "day", "week"])
def test_series_equals_the_mock_file(client, sensor, granularity):
    """The endpoint answers exactly what the static prototype file served (#5, ADR 0007)."""
    got = client.get(f"/api/series?sensor={sensor}&{FULL_PERIOD}&granularity={granularity}")
    assert got.status_code == 200
    assert got.json() == mock_file("series", f"{sensor}.{granularity}.json")


def test_series_hour_states_from_the_database(client):
    points = client.get(f"/api/series?sensor=_example-km12&{FULL_PERIOD}&granularity=hour").json()[
        "points"
    ]
    by_ts = {p["ts"]: p for p in points}
    assert by_ts["2025-03-07T00:00:00+03:00"]["state"] == "normal"
    # a traffic anomaly interval [10:00, 16:00) also marks the touching edge hours (gen_mock)
    assert by_ts["2025-03-08T09:00:00+03:00"]["state"] == "anomaly"
    assert by_ts["2025-03-08T10:00:00+03:00"]["state"] == "anomaly"
    # inside an anomaly interval even an imputed hour comes back as anomaly
    assert by_ts["2025-03-09T02:00:00+03:00"]["state"] == "anomaly"


def test_series_day_rolls_an_hour_of_the_group_up(client, db):
    """A group with no anomaly but a filled-in hour is imputed; with an anomaly, anomaly."""
    db.execute(
        "INSERT INTO sensors VALUES ('_example-km99', '_example', 'Пример', 'км 99', 99, 1, 1,"
        " 'в город', 'из города')"
    )
    state_hour = (
        "INSERT INTO measurements (sensor_id, ts, volume, volume_direct, volume_reverse, state)"
        " VALUES ('_example-km99', ?, 100, 50, 50, ?)"
    )
    db.execute(state_hour, ("2025-04-01 10:00:00", "imputed"))
    db.execute(state_hour, ("2025-04-01 11:00:00", "normal"))
    db.execute(state_hour, ("2025-04-02 10:00:00", "normal"))
    db.execute(
        "INSERT INTO anomalies (id, source, road, sensor_id, starts_at, ends_at, category, type,"
        " detector, level, metric, is_mega) VALUES"
        " ('_example-km99-0001', 'ours', '_example', '_example-km99',"
        " '2025-04-02 10:00:00', '2025-04-02 11:00:00', 'traffic', 'volume_drop',"
        " 'amplitude', 'high', 'volume', 1)"
    )
    db.commit()
    points = client.get("/api/series?sensor=_example-km99&granularity=day").json()["points"]
    assert [(p["ts"], p["volume"], p["state"]) for p in points] == [
        ("2025-04-01", 100, "imputed"),
        ("2025-04-02", 100, "anomaly"),
    ]


def test_series_period_filter_keeps_whole_days(client):
    points = client.get(
        "/api/series?sensor=_example-km12&from=2025-03-08&to=2025-03-08&granularity=hour"
    ).json()["points"]
    assert len(points) == 24
    assert {p["ts"][:10] for p in points} == {"2025-03-08"}
    # an offset from contract time means the same Moscow hour
    with_zone = client.get(
        "/api/series?sensor=_example-km12&from=2025-03-08T00:00:00%2B03:00"
        "&to=2025-03-08T23:00:00%2B03:00&granularity=hour"
    ).json()["points"]
    assert {p["ts"][:10] for p in with_zone} == {"2025-03-08"}


def test_series_rejects_unknown_granularity_and_time(client):
    assert client.get("/api/series?sensor=_example-km12&granularity=month").status_code == 422
    assert client.get("/api/series?sensor=_example-km12&from=yesterday").status_code == 422


# ---------------------------------------------------------------- sensors (issue #6)


def test_sensors_equal_the_mock_geojson(client):
    got = client.get(f"/api/sensors?{FULL_PERIOD}")
    assert got.status_code == 200
    assert got.json() == mock_file("sensors.geojson")


def test_sensors_road_filter(client):
    assert len(client.get("/api/sensors?road=_example").json()["features"]) == 2
    assert client.get("/api/sensors?road=a133").json() == {
        "type": "FeatureCollection",
        "features": [],
    }


def test_sensors_count_only_anomalies_touching_the_period(client):
    """Only km47 has anomalies on March 7 (2 of them); km12's start on March 8."""
    one_day = client.get("/api/sensors?road=_example&from=2025-03-07&to=2025-03-07").json()
    by_id = {f["properties"]["id"]: f["properties"] for f in one_day["features"]}
    assert by_id["_example-km12"]["anomaly_count"] == 0
    assert by_id["_example-km47"]["anomaly_count"] == 2
    # both sensors do keep their mega flag: it speaks of the sensor, not the period
    assert by_id["_example-km12"]["is_mega"] is True and by_id["_example-km47"]["is_mega"]


# ---------------------------------------------------------------- anomalies (issue #6)


@pytest.mark.parametrize("sensor", SENSORS)
def test_anomalies_equal_the_mock_list_files(client, sensor):
    got = client.get(f"/api/anomalies?sensor={sensor}&{FULL_PERIOD}")
    assert got.status_code == 200
    assert got.json() == mock_file("anomalies", f"{sensor}.json")


def test_anomalies_join_the_sensor_name(client):
    items = client.get("/api/anomalies?sensor=_example-km47").json()["anomalies"]
    assert all(item["sensor_name"] == "км 47+850" for item in items)


def test_anomalies_filter_by_source(client):
    ours = client.get("/api/anomalies?sensor=_example-km12&source=ours").json()
    assert ours["counts"] == {"ours": 2, "corporate": 0}
    assert all(item["source_label"] == "наш алгоритм" for item in ours["anomalies"])
    corporate = client.get("/api/anomalies?source=corporate").json()
    assert [item["id"] for item in corporate["anomalies"]] == [
        "_example-corp-0002",
        "_example-corp-0001",
    ]


def test_anomalies_filter_by_level_and_type(client):
    critical = client.get("/api/anomalies?level=critical").json()["anomalies"]
    assert [item["id"] for item in critical] == ["_example-km12-0001"]
    spikes = client.get("/api/anomalies?type=volume_spike").json()["anomalies"]
    assert [item["id"] for item in spikes] == ["_example-corp-0002"]
    assert spikes[0]["type_label"] == "всплеск потока"
    assert client.get("/api/anomalies?level=nonsense").status_code == 422


def test_anomalies_filter_by_period_overlap(client):
    """March 7: km47's missing hours [13,16) and the corporate spike [8,9); nothing of km12."""
    one_day = client.get("/api/anomalies?road=_example&from=2025-03-07&to=2025-03-07").json()
    assert [item["id"] for item in one_day["anomalies"]] == [
        "_example-corp-0002",
        "_example-km47-0001",
    ]
    assert one_day["counts"] == {"ours": 1, "corporate": 1}
    assert client.get("/api/anomalies?from=2025-06-01&to=2025-06-02").json() == {
        "counts": {"ours": 0, "corporate": 0},
        "anomalies": [],
    }


@pytest.mark.parametrize("anomaly_id", ANOMALY_IDS)
def test_anomaly_detail_equals_the_mock_file(client, anomaly_id):
    got = client.get(f"/api/anomalies/{anomaly_id}")
    assert got.status_code == 200
    assert got.json() == mock_file("anomalies", "_example", f"{anomaly_id}.json")


def test_anomaly_detail_carries_the_linked_event(client):
    detail = client.get("/api/anomalies/_example-km12-0001").json()
    assert detail["event"]["id"] == "_example-crash-0308"
    assert detail["event"]["source_url"].startswith("https://")
    assert detail["event"]["category_label"] == "ДТП"


def test_anomaly_detail_unknown_id_is_404(client):
    assert client.get("/api/anomalies/_example-nothing-9999").status_code == 404


# ---------------------------------------------------------------- meta


def test_meta_describes_the_database(client):
    """The header data: per road its name and sensor count, plus the whole period (mock #6)."""
    assert client.get("/api/meta").json() == {
        k: v for k, v in mock_file("meta.json").items() if k != "generated_from"
    }
