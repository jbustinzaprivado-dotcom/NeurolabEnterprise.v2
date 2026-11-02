"""Flujo end-to-end del MVP (§18) con TensorFlow real, cancelación y registro de modelos."""

import io
import zipfile

import pytest

from app.core.database import SessionLocal
from app.repositories.models import TrainingJob
from tests.conftest import ANA, CARLA, DIEGO, LUIS, ROSA, SOFIA
from workers.training.jobs import runner
from workers.training.main import claim_next, process_next_job

API = "/api/v1"
WORKER = "pytest-worker"


@pytest.fixture(scope="module")
def iris(client):
    archs = client.get(f"{API}/projects/PRJ-101/architectures", headers=ANA).json()
    datasets = client.get(f"{API}/projects/PRJ-101/datasets", headers=ANA).json()
    arch = next(a for a in archs if a["name"] == "ff-iris")
    dataset = next(d for d in datasets if d["name"] == "iris")
    return {"architectureId": arch["id"], "datasetId": dataset["id"], "targetColumn": "especie"}


def launch(client, iris, headers=ANA, **overrides):
    payload = {**iris, "epochs": 15, "batchSize": 16, "learningRate": 0.02, **overrides}
    return client.post(f"{API}/projects/PRJ-101/training-jobs", json=payload, headers=headers)


def test_end_to_end_training_registers_model(client, iris):
    response = launch(client, iris)
    assert response.status_code == 202
    job_id = response.json()["id"]
    assert response.json()["status"] == "QUEUED"

    assert process_next_job(WORKER) == (job_id, "COMPLETED")

    job = client.get(f"{API}/training-jobs/{job_id}", headers=ANA).json()
    assert job["status"] == "COMPLETED" and job["progress"] == 100 and job["epoch"] == 15
    assert job["modelVersionId"] and job["accuracy"] > 0.6

    curves = client.get(f"{API}/training-jobs/{job_id}/metrics", headers=ANA).json()
    assert [p["epoch"] for p in curves["points"]] == list(range(1, 16))

    evaluation = client.get(f"{API}/training-jobs/{job_id}/evaluation", headers=ANA).json()
    matrix = evaluation["confusionMatrix"]["classes"]
    assert [row["label"] for row in matrix] == ["setosa", "versicolor", "virginica"]
    assert sum(row["total"] for row in matrix) == evaluation["testRows"]

    with client.stream("GET", f"{API}/training-jobs/{job_id}/events", headers=ANA) as stream:
        events = [line.split(": ", 1)[1] for line in stream.iter_lines() if line.startswith("event:")]
    assert events[0] == "snapshot" and events[-1] == "end"
    assert events.count("metric") == 15
    assert {"status", "log"} <= set(events)

    # Reanudar con Last-Event-ID solo entrega lo posterior.
    logs = client.get(f"{API}/training-jobs/{job_id}/logs", headers=ANA).json()
    with client.stream("GET", f"{API}/training-jobs/{job_id}/events",
                       headers={**ANA, "Last-Event-ID": str(logs[-2]["id"])}) as stream:
        resumed = [line for line in stream.iter_lines() if line.startswith("event:")]
    assert resumed == ["event: snapshot", f"event: {logs[-1]['type']}", "event: end"]


def test_versions_are_immutable_and_reviewed(client, iris):
    process_next_job(WORKER)  # vacía la cola si quedó algo
    job_id = launch(client, iris, epochs=5).json()["id"]
    process_next_job(WORKER)

    models = client.get(f"{API}/projects/PRJ-101/models", headers=ANA).json()
    labels = sorted(model["label"] for model in models)
    assert labels[:2] == ["v1.0", "v2.0"]
    latest = next(model for model in models if model["jobId"] == job_id)
    assert latest["status"] == "DRAFT" and len(latest["checksum"]) == 64

    status_url = f"{API}/models/{latest['id']}/status"
    assert client.post(status_url, json={"status": "APPROVED"}, headers=ROSA).status_code == 409  # salto de estado
    assert client.post(status_url, json={"status": "REVIEWED"}, headers=LUIS).status_code == 403  # engineer
    assert client.post(status_url, json={"status": "REVIEWED", "note": "Métricas correctas"}, headers=ROSA).status_code == 200
    # Separación de funciones: Ana entrenó el modelo, no puede aprobarlo aunque sea owner.
    assert client.post(status_url, json={"status": "APPROVED"}, headers=ANA).status_code == 403
    approved = client.post(status_url, json={"status": "APPROVED"}, headers=SOFIA).json()
    assert approved["status"] == "APPROVED" and len(approved["metadata"]["reviewHistory"]) == 2

    download = client.get(f"{API}/models/{latest['id']}/download", headers=ROSA)
    assert download.status_code == 200
    names = set(zipfile.ZipFile(io.BytesIO(download.content)).namelist())
    assert names == {"model.keras", "preprocessor.pkl", "metadata.json"}
    assert client.get(f"{API}/models/{latest['id']}/download", headers=CARLA).status_code == 403


def test_cancel_queued_job(client, iris):
    job_id = launch(client, iris).json()["id"]
    result = client.post(f"{API}/training-jobs/{job_id}/cancel", json={"reason": "Parámetros erróneos."}, headers=ANA).json()
    assert result["status"] == "CANCELLED"
    assert claim_next(WORKER) is None
    assert client.post(f"{API}/training-jobs/{job_id}/cancel", headers=ANA).status_code == 409


def test_cooperative_cancel_at_epoch_end(client, iris, monkeypatch):
    """RN-05: la solicitud llega durante la época 2; el worker termina esa época y para."""

    class CancelAtEpochTwo(runner.ProgressCallback):
        def on_epoch_end(self, epoch, logs=None):
            if epoch == 1:
                client.post(f"{API}/training-jobs/{self.job_id}/cancel", json={"reason": "Prueba RN-05."}, headers=ANA)
            super().on_epoch_end(epoch, logs)

    monkeypatch.setattr(runner, "ProgressCallback", CancelAtEpochTwo)
    job_id = launch(client, iris, epochs=10).json()["id"]
    assert process_next_job(WORKER) == (job_id, "CANCELLED")

    job = client.get(f"{API}/training-jobs/{job_id}", headers=ANA).json()
    assert job["epoch"] == 2 and job["statusReason"] == "Prueba RN-05." and job["modelVersionId"] is None
    assert len(client.get(f"{API}/training-jobs/{job_id}/metrics", headers=ANA).json()["points"]) == 2

    retry = client.post(f"{API}/training-jobs/{job_id}/retry", headers=ANA).json()
    assert retry["attempt"] == 2 and retry["retryOfId"] == job_id and retry["status"] == "QUEUED"
    client.post(f"{API}/training-jobs/{retry['id']}/cancel", headers=ANA)


def test_launch_validation(client, iris):
    # Cabeza de salida incompatible con un objetivo numérico.
    bad = launch(client, iris, targetColumn="largo_petalo")
    assert bad.status_code == 422 and "linear" in bad.json()["detail"]
    assert launch(client, iris, epochs=10_000).status_code == 422
    assert launch(client, iris, headers=LUIS, priority="CRITICA").status_code == 403  # engineer: hasta ALTA
    assert launch(client, iris, headers=ROSA).status_code == 403  # reviewer no entrena
    assert launch(client, iris, headers=DIEGO).status_code == 404  # ajeno al proyecto

    rnn = client.post(f"{API}/projects/PRJ-101/architectures", headers=ANA, json={
        "name": "lstm-prueba", "family": "RNN", "input": {"timesteps": 4, "seqFeatures": 1},
        "layers": [{"type": "LSTM", "units": 4}, {"type": "Dense", "units": 3, "activation": "softmax"}],
    }).json()
    disabled = launch(client, iris, architectureId=rnn["id"])
    assert disabled.status_code == 422 and "aún no habilitada" in disabled.json()["detail"]


def test_foreign_user_cannot_read_or_cancel_job(client, iris):
    job_id = launch(client, iris).json()["id"]
    assert client.get(f"{API}/training-jobs/{job_id}", headers=DIEGO).status_code == 404
    assert client.post(f"{API}/training-jobs/{job_id}/cancel", headers=DIEGO).status_code == 404
    # Luis es engineer del proyecto pero el trabajo es de Ana.
    assert client.post(f"{API}/training-jobs/{job_id}/cancel", headers=LUIS).status_code == 403
    client.post(f"{API}/training-jobs/{job_id}/cancel", headers=ANA)


def test_missing_dataset_file_fails_with_controlled_message(client, iris):
    from app.core.storage import get_store

    job_id = launch(client, iris, epochs=2).json()["id"]
    with SessionLocal() as db:
        key = db.get(TrainingJob, job_id).dataset.storage_key
    store = get_store()
    content = store.get(key)
    store.delete(key)
    try:
        assert process_next_job(WORKER) == (job_id, "FAILED")
    finally:
        store.put(key, content, "text/csv")
    job = client.get(f"{API}/training-jobs/{job_id}", headers=ANA).json()
    assert job["statusReason"] == "El archivo del dataset no está en el almacenamiento."
    assert client.get(f"{API}/dashboard", headers=ANA).json()["alerts"][0]["severity"] == "high"


def test_dashboard_and_report(client):
    snapshot = client.get(f"{API}/dashboard", headers=ANA).json()
    assert {"kpis", "activeJobs", "queuedJobs", "recentJobs", "topProjects", "alerts", "health", "activity"} <= set(snapshot)
    assert len(snapshot["activity"]) == 14 and snapshot["recentJobs"]

    report = client.get(f"{API}/projects/PRJ-101/reports/training-history.csv", headers=ROSA)
    assert report.status_code == 200
    lines = report.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0].startswith("job_id,estado") and len(lines) > 3
    assert client.get(f"{API}/projects/PRJ-101/reports/training-history.csv", headers=CARLA).status_code == 403
