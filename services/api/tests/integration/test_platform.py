"""Documentación (M02), cola (M06), evaluación (M07), informes (M09) y administración (M10)."""

from tests.conftest import ANA, CARLA, DIEGO, LUIS, ROSA, SOFIA
from workers.training.main import process_next_job

API = "/api/v1"


def iris_payload(client, **overrides):
    archs = client.get(f"{API}/projects/PRJ-101/architectures", headers=ANA).json()
    datasets = client.get(f"{API}/projects/PRJ-101/datasets", headers=ANA).json()
    return {
        "architectureId": next(a["id"] for a in archs if a["name"] == "ff-iris"),
        "datasetId": next(d["id"] for d in datasets if d["name"] == "iris"),
        "targetColumn": "especie", "epochs": 6, "batchSize": 16, "learningRate": 0.02, **overrides,
    }


def test_project_documents(client):
    created = client.post(f"{API}/projects/PRJ-101/documents", headers=LUIS,
                          json={"title": "Criterios de éxito", "body": "Accuracy de prueba ≥ 0.9."})
    assert created.status_code == 201
    doc = created.json()["documents"][0]
    assert doc["title"] == "Criterios de éxito" and doc["authorId"] == "USR-212"

    assert client.post(f"{API}/projects/PRJ-101/documents", headers=CARLA,
                       json={"title": "Lectora", "body": "x"}).status_code == 403
    edited = client.patch(f"{API}/projects/PRJ-101/documents/{doc['id']}", headers=ANA,
                          json={"title": "Criterios de éxito v2", "body": "Accuracy ≥ 0.92."}).json()
    assert edited["documents"][0]["title"] == "Criterios de éxito v2"
    remaining = client.delete(f"{API}/projects/PRJ-101/documents/{doc['id']}", headers=ANA).json()
    assert all(d["id"] != doc["id"] for d in remaining["documents"])


def test_queue_priority_and_start_now(client):
    process_next_job("drain")
    job = client.post(f"{API}/projects/PRJ-101/training-jobs", headers=ANA, json=iris_payload(client)).json()
    assert client.post(f"{API}/training-jobs/{job['id']}/priority", headers=LUIS, json={"priority": "ALTA"}).status_code == 403
    raised = client.post(f"{API}/training-jobs/{job['id']}/priority", headers=ANA, json={"priority": "CRITICA"})
    assert raised.json()["priority"] == "CRITICA"
    started = client.post(f"{API}/training-jobs/{job['id']}/start", headers=ANA)
    assert started.status_code == 200
    listed = {j["id"] for j in client.get(f"{API}/training-jobs", headers=ROSA).json()}
    assert job["id"] in listed
    assert client.get(f"{API}/training-jobs", headers=DIEGO).json() == [] or job["id"] not in {
        j["id"] for j in client.get(f"{API}/training-jobs", headers=DIEGO).json()
    }
    assert process_next_job("worker-test") == (job["id"], "COMPLETED")


def test_evaluations_and_observations(client):
    runs = client.get(f"{API}/evaluations", headers=ROSA).json()
    assert runs, "debe existir al menos una ejecución completada"
    run = runs[0]
    assert len(run["confusion"]) == len(run["classes"]) == 3
    assert run["history"][0]["valF1"] >= 0 and run["latencyP95Ms"] > 0
    assert 1 <= run["bestEpoch"] <= run["epochs"]

    created = client.post(f"{API}/training-jobs/{run['jobId']}/observations", headers=ROSA, json={
        "kind": "LIMITATION", "title": "Muestra pequeña", "body": "Solo 23 flores en prueba.",
    })
    assert created.status_code == 201
    obs = created.json()
    assert client.post(f"{API}/training-jobs/{run['jobId']}/observations", headers=CARLA,
                       json={"kind": "RISK", "title": "Lectora", "body": "No permitido"}).status_code == 403
    assert client.post(f"{API}/observations/{obs['id']}/review", headers=LUIS).status_code == 403
    assert client.post(f"{API}/observations/{obs['id']}/review", headers=ROSA).json()["reviewed"] is True
    assert obs["id"] in {o["id"] for o in client.get(f"{API}/observations", headers=ANA).json()}


def test_report_export_is_audited(client):
    payload = {"format": "PDF", "sections": ["ficha", "historial"], "rows": 12, "bytes": 2048,
               "fingerprint": "ab" * 32, "masked": [], "scopeLabel": "Últimos 90 días",
               "actor": {"id": "USR-218", "name": "Rosa Medina Vega", "roleLabel": "Revisor", "projectRoleLabel": "Revisor"}}
    created = client.post(f"{API}/projects/PRJ-101/reports/exports", headers=ROSA, json=payload)
    assert created.status_code == 201 and created.json()["id"].startswith("EXP-")
    assert client.post(f"{API}/projects/PRJ-101/reports/exports", headers=CARLA, json=payload).status_code == 403
    listed = client.get(f"{API}/reports/exports", headers=ANA).json()
    assert listed[0]["fingerprint"] == "ab" * 32
    assert client.get(f"{API}/reports/exports", headers=DIEGO).json() == []


def test_admin_console(client):
    assert client.get(f"{API}/admin/snapshot", headers=ANA).status_code == 403
    snapshot = client.get(f"{API}/admin/snapshot", headers=SOFIA).json()
    assert {"users", "audit", "limits", "settings", "health"} <= set(snapshot)
    assert any(e["action"] == "training.launch" and e["ip"] for e in snapshot["audit"])

    invited = client.post(f"{API}/admin/users", headers=SOFIA,
                          json={"displayName": "Nora Vílchez Paz", "email": "nora.vilchez@neurolab.enterprise", "role": "engineer"}).json()
    nora = next(u for u in invited["users"] if u["email"] == "nora.vilchez@neurolab.enterprise")
    assert nora["status"] == "INVITED"
    # El primer inicio de sesión acepta la invitación.
    login = client.post(f"{API}/auth/login", json={"email": nora["email"], "password": "neurolab2026"})
    assert login.status_code == 200 and login.json()["user"]["status"] == "ACTIVE"

    suspended = client.post(f"{API}/admin/users/{nora['id']}/status", headers=SOFIA).json()
    assert next(u for u in suspended["users"] if u["id"] == nora["id"])["status"] == "SUSPENDED"
    assert client.post(f"{API}/auth/login", json={"email": nora["email"], "password": "neurolab2026"}).status_code == 403
    assert client.post(f"{API}/admin/users/USR-201/status", headers=SOFIA).status_code == 409

    changed = client.put(f"{API}/admin/limits/epochs", headers=SOFIA, json={"value": 20}).json()
    assert next(l for l in changed["limits"] if l["id"] == "epochs")["limit"] == 20
    over = client.post(f"{API}/projects/PRJ-101/training-jobs", headers=ANA, json=iris_payload(client, epochs=30))
    assert over.status_code == 422 and "20" in over.json()["detail"]
    assert client.put(f"{API}/admin/limits/epochs", headers=SOFIA, json={"value": 5}).status_code == 422
    client.put(f"{API}/admin/limits/epochs", headers=SOFIA, json={"value": 500})

    settings = {**snapshot["settings"], "sessionMinutes": 60}
    saved = client.put(f"{API}/admin/settings", headers=SOFIA, json=settings).json()
    assert saved["settings"]["sessionMinutes"] == 60
    assert saved["audit"][0]["action"] == "settings.updated"


def test_config_and_dev_login_disabled_in_tests(client):
    config = client.get(f"{API}/config", headers=ANA).json()
    assert config["trainingFamilies"] == ["FEEDFORWARD", "RNN", "CNN"] and config["devLogin"] is False
    assert client.post(f"{API}/auth/dev-login", json={"userId": "USR-201"}).status_code == 404
