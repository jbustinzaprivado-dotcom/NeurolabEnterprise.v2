"""Recuperación (§15): reinicio de la API y fallo de worker sin perder el estado persistido.

La desconexión del navegador (reanudar con Last-Event-ID) se prueba en test_training_flow.
"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.database import SessionLocal, utcnow
from app.main import app
from app.repositories.models import AuditEvent, ModelVersion, Project, TrainingJob, User
from tests.conftest import ANA
from workers.training.callbacks.progress import ProgressCallback
from workers.training.jobs.runner import Heartbeat
from workers.training.main import claim_next, process_next_job, reap_stale_jobs

API = "/api/v1"


@pytest.fixture(scope="module")
def iris(client):
    archs = client.get(f"{API}/projects/PRJ-101/architectures", headers=ANA).json()
    datasets = client.get(f"{API}/projects/PRJ-101/datasets", headers=ANA).json()
    return {
        "architectureId": next(a["id"] for a in archs if a["name"] == "ff-iris"),
        "datasetId": next(d["id"] for d in datasets if d["name"] == "iris"),
        "targetColumn": "especie",
        "epochs": 6,
        "batchSize": 16,
        "learningRate": 0.02,
    }


def launch(client, iris) -> str:
    response = client.post(f"{API}/projects/PRJ-101/training-jobs", json=iris, headers=ANA)
    assert response.status_code == 202, response.text
    return response.json()["id"]


def age_heartbeat(job_id: str, seconds: int = 3600) -> None:
    """Simula que el worker dejó de dar señales hace `seconds` segundos."""
    with SessionLocal() as db:
        db.execute(update(TrainingJob).where(TrainingJob.id == job_id)
                   .values(heartbeat_at=utcnow() - timedelta(seconds=seconds)))
        db.commit()


def event_types(client, job_id: str) -> list[str]:
    with client.stream("GET", f"{API}/training-jobs/{job_id}/events", headers=ANA) as stream:
        return [line.split(": ", 1)[1] for line in stream.iter_lines() if line.startswith("event:")]


def test_api_restart_keeps_jobs_models_and_history(client, iris):
    job_id = launch(client, iris)
    assert process_next_job("worker-reinicio") == (job_id, "COMPLETED")
    before = client.get(f"{API}/training-jobs/{job_id}", headers=ANA).json()
    curves = client.get(f"{API}/training-jobs/{job_id}/metrics", headers=ANA).json()
    with SessionLocal() as db:
        counts = {model.__name__: db.scalar(select(func.count()).select_from(model))
                  for model in (User, Project, TrainingJob, ModelVersion)}

    # Un arranque nuevo vuelve a migrar y a revisar los datos demo: no debe duplicar ni perder nada.
    with TestClient(app) as restarted:
        after = restarted.get(f"{API}/training-jobs/{job_id}", headers=ANA).json()
        assert restarted.get(f"{API}/training-jobs/{job_id}/metrics", headers=ANA).json() == curves
        assert event_types(restarted, job_id)[-1] == "end"
    with SessionLocal() as db:
        assert counts == {model.__name__: db.scalar(select(func.count()).select_from(model))
                          for model in (User, Project, TrainingJob, ModelVersion)}
    assert after == before


def test_crashed_worker_leaves_a_recoverable_job(client, iris, monkeypatch):
    job_id = launch(client, iris)
    original = ProgressCallback.on_epoch_end

    def crash_after_third_epoch(self, epoch, logs=None):
        original(self, epoch, logs)
        if epoch + 1 == 3:
            raise KeyboardInterrupt  # el proceso muere de golpe: ningún código de cierre se ejecuta

    monkeypatch.setattr(ProgressCallback, "on_epoch_end", crash_after_third_epoch)
    with pytest.raises(KeyboardInterrupt):
        process_next_job("worker-caido")
    monkeypatch.undo()

    job = client.get(f"{API}/training-jobs/{job_id}", headers=ANA).json()
    assert job["status"] == "RUNNING" and job["epoch"] == 3

    # Mientras el latido es reciente, nadie toca el trabajo; cuando envejece, se recupera.
    assert reap_stale_jobs() == 0
    age_heartbeat(job_id)
    assert reap_stale_jobs() == 1

    job = client.get(f"{API}/training-jobs/{job_id}", headers=ANA).json()
    assert job["status"] == "FAILED" and "dejó de responder" in job["statusReason"]
    # Las épocas ya entrenadas siguen consultables y el canal en vivo se cierra.
    points = client.get(f"{API}/training-jobs/{job_id}/metrics", headers=ANA).json()["points"]
    assert [p["epoch"] for p in points] == [1, 2, 3]
    assert event_types(client, job_id)[-2:] == ["status", "end"]

    # Reintentar crea un trabajo nuevo que otro worker completa.
    retry = client.post(f"{API}/training-jobs/{job_id}/retry", headers=ANA)
    assert retry.status_code == 202
    assert process_next_job("worker-relevo") == (retry.json()["id"], "COMPLETED")


def test_worker_presumed_dead_does_not_overwrite_the_recovered_job(client, iris, monkeypatch):
    job_id = launch(client, iris)
    original = ProgressCallback.on_epoch_end

    def reaped_mid_training(self, epoch, logs=None):
        if epoch + 1 == 2:
            # Otro worker cree que este se cayó (p. ej. una pausa de red) y cierra el trabajo.
            age_heartbeat(job_id)
            assert reap_stale_jobs() == 1
        original(self, epoch, logs)

    monkeypatch.setattr(ProgressCallback, "on_epoch_end", reaped_mid_training)
    assert process_next_job("worker-lento") == (job_id, "FAILED")

    job = client.get(f"{API}/training-jobs/{job_id}", headers=ANA).json()
    assert job["status"] == "FAILED" and job["epoch"] == 1 and "dejó de responder" in job["statusReason"]
    with SessionLocal() as db:
        assert db.scalar(select(ModelVersion).where(ModelVersion.job_id == job_id)) is None
        assert db.scalar(select(func.max(AuditEvent.id)).where(AuditEvent.action == "model.register",
                                                               AuditEvent.metadata_json["jobId"].as_string() == job_id)) is None


def test_heartbeat_keeps_a_long_running_job_alive(client, iris):
    job_id = launch(client, iris)
    assert claim_next("worker-paciente") == job_id
    age_heartbeat(job_id)
    with Heartbeat(job_id, "worker-paciente", interval=0.05):
        time.sleep(0.4)  # una época o una carga larga, sin ningún final de época
    assert reap_stale_jobs() == 0

    # El latido solo renueva trabajos activos del propio worker.
    with SessionLocal() as db:
        assert not Heartbeat(job_id, "otro-worker").beat()
        job = db.get(TrainingJob, job_id)
        job.status = "CANCELLED"
        db.commit()
    assert not Heartbeat(job_id, "worker-paciente").beat()


def test_two_workers_never_claim_the_same_job(client, iris):
    job_id = launch(client, iris)
    assert claim_next("worker-a") == job_id
    assert claim_next("worker-b") is None
    with SessionLocal() as db:
        job = db.get(TrainingJob, job_id)
        assert job.worker_id == "worker-a"
        job.status = "CANCELLED"
        db.commit()
