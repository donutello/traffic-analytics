"""Smoke tests for A-134 API endpoints."""

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_sensors():
    response = client.get("/api/v1/a134/sensors")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_get_sensor():
    # Сначала получаем список датчиков
    list_response = client.get("/api/v1/a134/sensors")
    sensors = list_response.json()
    assert len(sensors) > 0

    # Берём ID первого датчика
    sensor_id = sensors[0]["id"]

    # Получаем этот датчик по ID
    response = client.get(f"/api/v1/a134/sensors/{sensor_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == sensor_id


def test_get_sensor_not_found():
    response = client.get("/api/v1/a134/sensors/nonexistent")
    assert response.status_code == 404


def test_list_series():
    response = client.get("/api/v1/a134/series")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 5


def test_list_anomalies():
    response = client.get("/api/v1/a134/anomalies")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
