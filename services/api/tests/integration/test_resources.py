"""Límites de recursos por entrenamiento (§10): núcleos de CPU, memoria y GPU."""

import psutil
import pytest

from app.core.database import SessionLocal
from app.repositories.models import TrainingJob
from app.services import platform_settings
from tests.conftest import ANA, SOFIA
from workers.training.jobs import resources
from workers.training.main import process_next_job

API = "/api/v1"


@pytest.fixture
def iris(client):
    archs = client.get(f"{API}/projects/PRJ-101/architectures", headers=ANA).json()
    datasets = client.get(f"{API}/projects/PRJ-101/datasets", headers=ANA).json()
    return {
        "architectureId": next(a["id"] for a in archs if a["name"] == "ff-iris"),
        "datasetId": next(d["id"] for d in datasets if d["name"] == "iris"),
        "targetColumn": "especie", "epochs": 4, "batchSize": 16, "learningRate": 0.02,
    }


def _launch(client, iris) -> str:
    response = client.post(f"{API}/projects/PRJ-101/training-jobs", json=iris, headers=ANA)
    assert response.status_code == 202, response.text
    return response.json()["id"]


def test_limits_are_listed_and_editable_in_m10(client):
    limits = {item["id"]: item for item in client.get(f"{API}/admin/snapshot", headers=SOFIA).json()["limits"]}
    assert {"cpuThreads", "memory", "gpu"} <= set(limits)
    assert limits["memory"]["unit"] == "MB" and limits["gpu"]["min"] == 0
    updated = client.put(f"{API}/admin/limits/cpuThreads", json={"value": 2}, headers=SOFIA)
    assert updated.status_code == 200, updated.text
    with SessionLocal() as db:
        assert platform_settings.limit(db, "cpuThreads") == 2
    assert client.put(f"{API}/admin/limits/memory", json={"value": 100}, headers=SOFIA).status_code == 422


def test_cpu_pinning_restricts_and_restores_cores():
    before = psutil.Process().cpu_affinity()
    if len(before) < 2:
        pytest.skip("Hace falta más de un núcleo para comprobar la afinidad.")
    with resources.CpuPinning(1) as pinned:
        assert pinned.applied == 1
        assert len(psutil.Process().cpu_affinity()) == 1
    assert psutil.Process().cpu_affinity() == before


def test_training_records_the_resources_it_used(client, iris):
    with SessionLocal() as db:
        platform_settings.set_limit(db, "cpuThreads", 2)
        db.commit()
    job_id = _launch(client, iris)
    assert process_next_job("worker-recursos") == (job_id, "COMPLETED")
    with SessionLocal() as db:
        used = db.get(TrainingJob, job_id).result_json["resources"]
    assert used["cpuThreads"] in {2, psutil.cpu_count()}  # 2, o todos si el sistema no admite afinidad
    assert used["peakMemoryMb"] > 0 and used["memoryLimitMb"] == 4096
    logs = [event["payload"].get("message", "") for event in client.get(f"{API}/training-jobs/{job_id}/logs", headers=ANA).json()]
    assert any(message.startswith("Recursos: ") for message in logs)


def test_training_over_the_memory_limit_fails_with_a_clear_message(client, iris, monkeypatch):
    monkeypatch.setattr(resources, "memory_mb", lambda: 999_999.0)
    job_id = _launch(client, iris)
    assert process_next_job("worker-memoria") == (job_id, "FAILED")
    job = client.get(f"{API}/training-jobs/{job_id}", headers=ANA).json()
    assert "límite de memoria" in job["statusReason"] and "4096 MB" in job["statusReason"]
    assert job["epoch"] <= 1  # se detiene en la primera época, no al final


def test_gpu_limit_zero_hides_gpus(monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.setattr(resources, "read_limits", lambda: resources.JobLimits(cpu_threads=4, memory_mb=4096, gpus=0))
    assert resources.hide_gpus_if_disabled() == 0
    import os

    assert os.environ["CUDA_VISIBLE_DEVICES"] == "-1"
