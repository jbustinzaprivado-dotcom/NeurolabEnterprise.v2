"""Operación (§5): logs estructurados sin secretos (§11), métricas e identificador de petición."""

import json
import logging

from app.core.log_config import JsonFormatter
from tests.conftest import ANA


def _format(message: str, **extra) -> dict:
    record = logging.makeLogRecord({"name": "neurolab.test", "levelname": "INFO", "msg": message, **extra})
    return json.loads(JsonFormatter("api").format(record))


def test_json_log_carries_structured_fields():
    entry = _format("GET /api/v1/projects 200", status=200, route="/api/v1/projects", duration_ms=3.2)
    assert entry["service"] == "api" and entry["level"] == "INFO"
    assert entry["status"] == 200 and entry["route"] == "/api/v1/projects"
    assert entry["ts"].endswith("+00:00")


def test_json_log_never_writes_secrets():
    entry = _format("Authorization: Bearer abc.DEF-123 password=hunter2 token: xyz")
    assert "abc.DEF-123" not in entry["msg"] and "hunter2" not in entry["msg"] and "xyz" not in entry["msg"]
    assert "***" in entry["msg"]


def test_metrics_endpoint_and_request_id(client):
    response = client.get("/api/v1/projects", headers=ANA)
    assert len(response.headers["X-Request-ID"]) >= 8
    echoed = client.get("/api/v1/projects", headers={**ANA, "X-Request-ID": "traza-123"})
    assert echoed.headers["X-Request-ID"] == "traza-123"

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    body = metrics.text
    assert 'neurolab_http_requests_total{method="GET",route="/api/v1/projects",status="200"}' in body
    assert "neurolab_http_request_duration_seconds_bucket" in body
    assert "neurolab_training_jobs" in body and "neurolab_workers_online" in body
