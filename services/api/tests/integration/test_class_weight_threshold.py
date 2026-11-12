"""Peso de clases y umbral de alerta en clasificación binaria (caso de fuga de clientes, PRJ-118)."""

import pytest

from tests.conftest import ANA
from workers.training.main import process_next_job

API = "/api/v1"


@pytest.fixture(scope="module")
def fuga(client):
    archs = client.get(f"{API}/projects/PRJ-118/architectures", headers=ANA).json()
    datasets = client.get(f"{API}/projects/PRJ-118/datasets", headers=ANA).json()
    return {
        "architectureId": next(a["id"] for a in archs if a["name"] == "ff-fuga"),
        "datasetId": next(d["id"] for d in datasets if d["name"] == "clientes-fuga"),
        "targetColumn": "fuga", "epochs": 25, "batchSize": 32, "learningRate": 0.005,
    }


def _train(client, payload: dict) -> dict:
    job = client.post(f"{API}/projects/PRJ-118/training-jobs", json=payload, headers=ANA)
    assert job.status_code == 202, job.text
    assert process_next_job("worker-umbral") == (job.json()["id"], "COMPLETED")
    run = next(r for r in client.get(f"{API}/evaluations", headers=ANA).json() if r["jobId"] == job.json()["id"])
    return {"job": client.get(f"{API}/training-jobs/{job.json()['id']}", headers=ANA).json(), "run": run}


def _detected(run: dict) -> int:
    return run["confusion"][1][1]  # fila «si» real, columna «si» predicha


def test_peso_balanceado_detecta_mas_casos_de_la_clase_minoritaria(client, fuga):
    plain = _train(client, fuga)
    balanced = _train(client, {**fuga, "classWeight": "balanced"})
    assert plain["job"]["classWeight"] == "none" and balanced["job"]["classWeight"] == "balanced"
    assert _detected(balanced["run"]) > _detected(plain["run"])
    logs = [e["payload"].get("message", "") for e in
            client.get(f"{API}/training-jobs/{balanced['job']['id']}/logs", headers=ANA).json()]
    assert any(line.startswith("Peso de clases balanceado") for line in logs)


def test_umbral_se_aplica_y_permite_recalcular_la_matriz(client, fuga):
    trained = _train(client, {**fuga, "threshold": 0.3})
    assert trained["job"]["threshold"] == 0.3
    binary = trained["run"]["binary"]
    assert binary["threshold"] == 0.3 and binary["positiveClass"] == "si"
    assert len(binary["scores"]) == trained["run"]["samples"]
    # La matriz publicada es la misma que se obtiene de los puntajes con el umbral entrenado.
    matrix = [[0, 0], [0, 0]]
    for real, score in binary["scores"]:
        matrix[real][int(score >= 0.3)] += 1
    assert matrix == trained["run"]["confusion"]


def test_umbral_no_aplica_fuera_de_la_clasificacion_binaria(client):
    archs = client.get(f"{API}/projects/PRJ-101/architectures", headers=ANA).json()
    datasets = client.get(f"{API}/projects/PRJ-101/datasets", headers=ANA).json()
    payload = {"architectureId": next(a["id"] for a in archs if a["name"] == "ff-iris"),
               "datasetId": next(d["id"] for d in datasets if d["name"] == "iris"),
               "targetColumn": "especie", "epochs": 3, "threshold": 0.3, "classWeight": "balanced"}
    job = client.post(f"{API}/projects/PRJ-101/training-jobs", json=payload, headers=ANA).json()
    assert job["threshold"] is None and job["classWeight"] == "balanced"  # 3 clases: sin clase positiva
    client.post(f"{API}/training-jobs/{job['id']}/cancel", json={"reason": "prueba"}, headers=ANA)
    bad = client.post(f"{API}/projects/PRJ-101/training-jobs", json={**payload, "threshold": 0.99}, headers=ANA)
    assert bad.status_code == 422
