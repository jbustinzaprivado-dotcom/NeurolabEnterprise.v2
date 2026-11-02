"""Seguridad (§11): límites de tasa, bloqueo de cuentas, retención y configuración de producción."""

from datetime import timedelta

import pytest

from app.core.config import Settings, settings
from app.core.database import SessionLocal, utcnow
from app.core.storage import get_store
from app.repositories.models import AuditEvent, ModelVersion, TrainingJob, TrainingMetric
from app.services.retention import apply_retention
from tests.conftest import ANA, LUIS, SOFIA
from workers.training.main import process_next_job

API = "/api/v1"
JORGE = {"email": "jorge.campos@neurolab.enterprise", "password": "neurolab2026"}


def test_account_locks_after_failed_logins(client):
    wrong = {**JORGE, "password": "incorrecta"}
    for _ in range(settings.max_failed_logins - 1):
        assert client.post(f"{API}/auth/login", json=wrong).status_code == 401
    locked = client.post(f"{API}/auth/login", json=wrong)
    assert locked.status_code == 403 and "bloqueada" in locked.json()["detail"]
    # Bloqueada, ni la contraseña correcta entra.
    assert client.post(f"{API}/auth/login", json=JORGE).status_code == 403

    snapshot = client.get(f"{API}/admin/snapshot", headers=SOFIA).json()
    assert next(u for u in snapshot["users"] if u["id"] == "USR-251")["status"] == "LOCKED"
    assert any(e["action"] == "auth.locked" and e["severity"] == "critical" for e in snapshot["audit"])

    client.post(f"{API}/admin/users/USR-251/status", headers=SOFIA)  # desbloquear
    assert client.post(f"{API}/auth/login", json=JORGE).status_code == 200


def test_login_attempts_are_rate_limited_per_ip(client):
    wrong = {"email": "nadie@neurolab.enterprise", "password": "x"}
    codes = [client.post(f"{API}/auth/login", json=wrong).status_code for _ in range(settings.login_attempts_per_minute + 1)]
    assert codes[:-1] == [401] * settings.login_attempts_per_minute
    assert codes[-1] == 429


def test_api_rate_limit_per_user(client):
    assert client.put(f"{API}/admin/limits/rate", headers=SOFIA, json={"value": 60}).status_code == 200
    try:
        codes = [client.get(f"{API}/auth/me", headers=LUIS).status_code for _ in range(61)]
        assert codes[:60] == [200] * 60
        blocked = client.get(f"{API}/auth/me", headers=LUIS)
        assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) >= 1
        # Cada identidad tiene su propio cupo.
        assert client.get(f"{API}/auth/me", headers=ANA).status_code == 200
    finally:
        client.put(f"{API}/admin/limits/rate", headers=SOFIA, json={"value": settings.rate_limit_per_minute})


def test_retention_policy(client):
    archs = client.get(f"{API}/projects/PRJ-101/architectures", headers=ANA).json()
    datasets = client.get(f"{API}/projects/PRJ-101/datasets", headers=ANA).json()
    process_next_job("drain")
    job = client.post(f"{API}/projects/PRJ-101/training-jobs", headers=ANA, json={
        "architectureId": next(a["id"] for a in archs if a["name"] == "ff-iris"),
        "datasetId": next(d["id"] for d in datasets if d["name"] == "iris"),
        "targetColumn": "especie", "epochs": 3, "batchSize": 16,
    }).json()
    assert process_next_job("retention-worker") == (job["id"], "COMPLETED")

    old = utcnow() - timedelta(days=4000)
    with SessionLocal() as db:
        db.add(AuditEvent(actor_id="system", action="seed.demo", target_type="x", target_id="antiguo",
                          metadata_json={}, created_at=old))
        trained = db.get(TrainingJob, job["id"])
        trained.ended_at = old
        model = db.query(ModelVersion).filter_by(job_id=job["id"]).one()
        model.status, model.updated_at = "RETIRED", old
        prefix = model.storage_key
        db.commit()
        model_id = model.id
    assert len(get_store().list(prefix)) == 3  # model.keras, preprocessor.pkl, metadata.json

    with SessionLocal() as db:
        counts = apply_retention(db)
    assert counts["auditoria"] >= 1 and counts["metricas"] > 0 and counts["artefactos"] == 1

    with SessionLocal() as db:
        assert db.query(AuditEvent).filter_by(target_id="antiguo").count() == 0
        assert db.query(TrainingMetric).filter_by(job_id=job["id"]).count() == 0
        kept = db.get(TrainingJob, job["id"])
        assert kept.status == "COMPLETED" and "evaluation" in kept.result_json  # el resumen se conserva
        assert db.get(ModelVersion, model_id).metadata_json["artifactsPurgedAt"]
    assert get_store().list(prefix) == []
    assert client.get(f"{API}/models/{model_id}/download", headers=ANA).status_code == 410


def test_production_refuses_development_settings(monkeypatch):
    monkeypatch.setenv("NEUROLAB_ENV", "production")
    monkeypatch.setenv("NEUROLAB_AUTH_DEV_BYPASS", "true")
    with pytest.raises(RuntimeError, match="DEV_BYPASS"):
        Settings().check_runtime()

    monkeypatch.setenv("NEUROLAB_AUTH_DEV_BYPASS", "false")
    monkeypatch.setenv("NEUROLAB_SECRET_KEY", "")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        Settings().check_runtime()

    # Sin almacén de objetos (§5) tampoco arranca en producción.
    monkeypatch.setenv("NEUROLAB_SECRET_KEY", "clave-de-produccion")
    monkeypatch.setenv("NEUROLAB_STORAGE_BACKEND", "local")
    with pytest.raises(RuntimeError, match="STORAGE_BACKEND"):
        Settings().check_runtime()

    monkeypatch.setenv("NEUROLAB_STORAGE_BACKEND", "s3")
    Settings().check_runtime()
