"""Entrenamiento real de redes recurrentes (LSTM) y convolucionales (CNN) con datos demo (§18)."""

import dataclasses

from app import seed as seed_module
from app.core.database import SessionLocal
from tests.conftest import ANA, DIEGO
from workers.training.main import process_next_job

API = "/api/v1"


def _pick(client, project: str, headers: dict, architecture: str, dataset: str) -> dict:
    archs = client.get(f"{API}/projects/{project}/architectures", headers=headers).json()
    datasets = client.get(f"{API}/projects/{project}/datasets", headers=headers).json()
    return {
        "architectureId": max((a for a in archs if a["name"] == architecture), key=lambda a: a["version"])["id"],
        "datasetId": next(d["id"] for d in datasets if d["name"] == dataset),
    }


def _train(client, project: str, headers: dict, payload: dict) -> dict:
    response = client.post(f"{API}/projects/{project}/training-jobs", json=payload, headers=headers)
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    assert process_next_job("worker-formas") == (job_id, "COMPLETED")
    job = client.get(f"{API}/training-jobs/{job_id}", headers=headers).json()
    logs = [e["payload"].get("message", "") for e in client.get(f"{API}/training-jobs/{job_id}/logs", headers=headers).json()]
    return {"job": job, "logs": logs}


def test_lstm_learns_failures_from_vibration_sequences(client):
    payload = {**_pick(client, "PRJ-102", DIEGO, "lstm-vibracion", "series-vibracion"),
               "targetColumn": "falla_48h", "epochs": 12, "batchSize": 32, "learningRate": 0.01}
    result = _train(client, "PRJ-102", DIEGO, payload)
    assert any("secuencias de 30 pasos × 2 variables" in line for line in result["logs"])
    # 69 % de las filas son «no»: el modelo debe superar claramente esa línea base.
    assert result["job"]["accuracy"] > 0.8


def test_cnn_classifies_joint_images(client):
    payload = {**_pick(client, "PRJ-126", ANA, "cnn-juntas", "imagenes-juntas"),
               "targetColumn": "clase", "epochs": 10, "batchSize": 32, "learningRate": 0.005}
    result = _train(client, "PRJ-126", ANA, payload)
    assert any("imágenes de 16×16 con 1 canal(es)" in line for line in result["logs"])
    assert result["job"]["accuracy"] > 0.6  # 4 clases: el azar daría 0,25


def test_shape_mismatch_is_rejected_before_queueing(client):
    # La LSTM espera 30×2 = 60 columnas; el dataset resumido tiene muchas menos.
    payload = {**_pick(client, "PRJ-102", DIEGO, "lstm-vibracion", "vibracion-compresores"),
               "targetColumn": "falla_48h", "epochs": 2}
    response = client.post(f"{API}/projects/PRJ-102/training-jobs", json=payload, headers=DIEGO)
    assert response.status_code == 422
    assert "60 columnas" in response.json()["detail"] and "t00_var1" in response.json()["detail"]


def test_complement_adds_new_demo_items_without_touching_existing(monkeypatch):
    with SessionLocal() as db:
        assert seed_module.complement(db) == []  # base recién cargada: nada que agregar

    spec = next(p for p in seed_module.PROJECTS if p.id == "PRJ-126")
    arch = spec.architectures[0]
    changed = dataclasses.replace(arch, justification="Otra versión", layers=[*arch.layers[:-2], *arch.layers[-1:]])
    extra = dataclasses.replace(spec.datasets[0], name="imagenes-juntas-extra")
    patched = dataclasses.replace(spec, architectures=[changed], datasets=[*spec.datasets, extra])
    monkeypatch.setattr(seed_module, "PROJECTS", [patched])
    with SessionLocal() as db:
        added = seed_module.complement(db)
    assert added == ["PRJ-126: dataset imagenes-juntas-extra", "PRJ-126: arquitectura cnn-juntas v2"]
    with SessionLocal() as db:
        assert seed_module.complement(db) == []  # idempotente
