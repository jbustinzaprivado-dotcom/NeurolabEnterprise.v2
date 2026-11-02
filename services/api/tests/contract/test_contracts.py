"""Pruebas de contrato (§15): esquemas de la API y de los eventos en tiempo real.

1. La API publicada coincide con docs/api: si una ruta, un parámetro o un esquema cambia,
   la prueba falla hasta regenerar los contratos (scripts/exportar_contratos.py).
2. Cada evento que emite el canal SSE en entrenamientos reales (clasificación, regresión,
   cancelación y fallo) cumple el esquema que consume la interfaz.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.core.database import SessionLocal
from app.repositories.models import Dataset
from app.schemas.events import EVENTS
from tests.conftest import ANA
from workers.training.main import process_next_job

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location("exportar_contratos", ROOT / "services/api/scripts/exportar_contratos.py")
exportar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(exportar)


def _normalized(content) -> object:
    return json.loads(json.dumps(content, ensure_ascii=False))


@pytest.mark.parametrize("name", ["openapi.json", "eventos-sse.json"])
def test_published_contract_matches_the_code(client, name):
    published = ROOT / "docs" / "api" / name
    assert published.is_file(), f"Falta docs/api/{name}: ejecuta services/api/scripts/exportar_contratos.py"
    current = _normalized(exportar.build()[name])
    assert json.loads(published.read_text(encoding="utf-8")) == current, (
        f"El contrato {name} cambió. Si el cambio es intencional, ejecuta "
        "services/api/scripts/exportar_contratos.py y revisa el diff de docs/api."
    )


def test_every_route_is_versioned_and_documented(client):
    paths = exportar.build()["openapi.json"]["paths"]
    assert paths and all(path.startswith("/api/v1/") for path in paths)
    for path, operations in paths.items():
        for method, operation in operations.items():
            assert operation.get("summary") or operation.get("description"), f"{method.upper()} {path} sin descripción"
            assert "200" in operation["responses"] or any(code.startswith("2") for code in operation["responses"])


def _stream(client, job_id: str) -> list[tuple[str, dict]]:
    events, name = [], None
    with client.stream("GET", f"{API}/training-jobs/{job_id}/events", headers=ANA) as stream:
        for line in stream.iter_lines():
            if line.startswith("event:"):
                name = line.split(": ", 1)[1]
            elif line.startswith("data:") and name:
                events.append((name, json.loads(line.split(": ", 1)[1])))
    return events


def _assert_contract(events: list[tuple[str, dict]]) -> None:
    names = [name for name, _ in events]
    assert names[0] == "snapshot" and names[-1] == "end"
    assert set(names) <= set(EVENTS), f"Eventos fuera de contrato: {set(names) - set(EVENTS)}"
    for name, data in events:
        EVENTS[name].model_validate(data)


def _launch(client, project: str, architecture: str, dataset: str, target: str, **extra) -> str:
    archs = client.get(f"{API}/projects/{project}/architectures", headers=ANA).json()
    datasets = client.get(f"{API}/projects/{project}/datasets", headers=ANA).json()
    payload = {
        "architectureId": next(a["id"] for a in archs if a["name"] == architecture),
        "datasetId": next(d["id"] for d in datasets if d["name"] == dataset),
        "targetColumn": target, "epochs": 4, "batchSize": 32, "learningRate": 0.02, **extra,
    }
    response = client.post(f"{API}/projects/{project}/training-jobs", json=payload, headers=ANA)
    assert response.status_code == 202, response.text
    return response.json()["id"]


def test_classification_events_follow_the_contract(client):
    job_id = _launch(client, "PRJ-101", "ff-iris", "iris", "especie")
    assert process_next_job("worker-contrato") == (job_id, "COMPLETED")
    events = _stream(client, job_id)
    _assert_contract(events)
    metric = next(data for name, data in events if name == "metric")
    assert {"accuracy", "val_accuracy", "f1", "val_f1"} <= set(metric)


def test_regression_events_follow_the_contract(client):
    project = client.get(f"{API}/projects/PRJ-031", headers=ANA).json()
    if project["status"] == "ARCHIVED":  # el proyecto demo de regresión está archivado
        assert client.patch(f"{API}/projects/PRJ-031", json={"status": "ACTIVE"}, headers=ANA).status_code == 200
    job_id = _launch(client, "PRJ-031", "ff-precios", "viviendas-lima", "precio_soles")
    assert process_next_job("worker-contrato") == (job_id, "COMPLETED")
    events = _stream(client, job_id)
    _assert_contract(events)
    metric = next(data for name, data in events if name == "metric")
    assert "mae" in metric and "accuracy" not in metric


def test_cancelled_and_failed_jobs_follow_the_contract(client):
    cancelled = _launch(client, "PRJ-101", "ff-iris", "iris", "especie")
    assert client.post(f"{API}/training-jobs/{cancelled}/cancel", json={"reason": "Prueba de contrato."},
                       headers=ANA).status_code == 200
    _assert_contract(_stream(client, cancelled))

    failed = _launch(client, "PRJ-101", "ff-iris", "iris", "especie")
    with SessionLocal() as db:
        # Dataset sin archivo en el almacén: el worker falla con mensaje controlado.
        dataset_id = client.get(f"{API}/training-jobs/{failed}", headers=ANA).json()["datasetId"]
        dataset = db.get(Dataset, dataset_id)
        original, dataset.storage_key = dataset.storage_key, "uploads/no-existe.csv"
        db.commit()
    try:
        assert process_next_job("worker-contrato") == (failed, "FAILED")
    finally:
        with SessionLocal() as db:
            db.get(Dataset, dataset_id).storage_key = original
            db.commit()
    events = _stream(client, failed)
    _assert_contract(events)
    assert any(name == "log" and data["level"] == "error" for name, data in events)
