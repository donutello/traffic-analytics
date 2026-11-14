"""The FastAPI app. Run it with: uv run uvicorn backend.main:app --reload"""

from fastapi import FastAPI

from backend.anomalies.controllers.a134 import router as anomalies_router
from backend.sensors.controllers.a134 import router as sensors_router
from backend.series.controllers.a134 import router as series_router

app = FastAPI(title="Traffic Analytics")

app.include_router(sensors_router)
app.include_router(series_router)
app.include_router(anomalies_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
