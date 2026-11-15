"""Load test of the dashboard API (issue #8): docs/load-test.md tells how to run it.

A scenario is an anonymous dashboard session: the charts of /api/series, the anomaly
panel of /api/anomalies, the comparison view, plus the map (/api/sensors) and the picker
(/api/meta) on load. Task weights sum up to 100: 45 series, 30 anomalies (24 list + 6
detail), 15 comparison, 7 sensors, 3 meta. The parameters are real sensors, roads and
periods of the loaded database, the whole period (open dashboard bounds) included.
"""

import random

from locust import HttpUser, between, task

SENSORS = [
    "a133-km12-0",
    "a133-km40-0",
    "a134-km8-100",
    "r22-km448-650",
    "r22-km478-742",
    "r298-km310-000",
    "r298-km389-000",
]

# Shapes are (path, name); the name groups a request shape in the locust CSV.
SERIES_SHAPES = (
    [(f"/api/series?sensor={s}&granularity=day", "series day whole period") for s in SENSORS]
    + [(f"/api/series?sensor={s}&granularity=week", "series week whole period") for s in SENSORS]
    + [
        (
            f"/api/series?sensor={s}&granularity=hour&from=2026-09-01&to=2026-09-07",
            "series hour week",
        )
        for s in SENSORS[:4]
    ]
    + [
        (
            f"/api/series?sensor={s}&granularity=hour&from=2026-08-01&to=2026-10-01",
            "series hour two months",
        )
        for s in SENSORS[:3]
    ]
    + [
        (
            f"/api/series?sensor={s}&granularity=day&from=2025-01-01&to=2026-01-01",
            "series day year",
        )
        for s in SENSORS[:3]
    ]
    + [("/api/series?sensor=a134-km8-100&granularity=hour", "series hour WHOLE period (worst)")]
)

ANOMALY_SHAPES = [
    ("/api/anomalies", "anomalies whole period"),
    ("/api/anomalies?road=a133", "anomalies road"),
    ("/api/anomalies?road=r22&level=high", "anomalies road+level"),
    ("/api/anomalies?from=2025-01-01&to=2026-01-01", "anomalies year window"),
    ("/api/anomalies?road=a134&source=ours", "anomalies road+source"),
]

DETAIL_SHAPES = [
    (
        "/api/anomalies/a133-volume-drop-20230101-01",
        "/api/anomalies/{id} with event",
    ),
    ("/api/anomalies/a134-missing-hours-20230901-01", "/api/anomalies/{id} plain"),
]

COMPARISON_SHAPES = [
    ("/api/comparison", "comparison all roads whole period"),
    ("/api/comparison?road=a134", "comparison road"),
    ("/api/comparison?road=r298&from=2025-06-01&to=2026-06-01", "comparison road+year"),
]

SENSOR_SHAPES = [
    ("/api/sensors", "sensors whole period"),
    ("/api/sensors?road=r22", "sensors road"),
]


class DashboardUser(HttpUser):
    # one request every ~1.1 s, so ~110 users hold the target of 100 requests per second
    wait_time = between(1.06, 1.23)

    def _get(self, shapes):
        path, name = random.choice(shapes)
        self.client.get(path, name=name)

    @task(45)
    def series(self):
        self._get(SERIES_SHAPES)

    @task(24)
    def anomalies(self):
        self._get(ANOMALY_SHAPES)

    @task(6)
    def anomaly_detail(self):
        self._get(DETAIL_SHAPES)

    @task(15)
    def comparison(self):
        self._get(COMPARISON_SHAPES)

    @task(7)
    def sensors(self):
        self._get(SENSOR_SHAPES)

    @task(3)
    def meta(self):
        self._get([("/api/meta", "/api/meta")])
