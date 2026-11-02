"""Autenticación, RBAC y aislamiento entre proyectos (§12 Seguridad, §15)."""

from tests.conftest import ANA, CARLA, DIEGO, LUIS, SOFIA

API = "/api/v1"


def test_login_and_me(client):
    response = client.post(f"{API}/auth/login", json={"email": "ana.quispe@neurolab.enterprise", "password": "neurolab2026"})
    assert response.status_code == 200
    token = response.json()["accessToken"]
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["id"] == "USR-207"


def test_login_rejects_bad_password(client):
    response = client.post(f"{API}/auth/login", json={"email": "ana.quispe@neurolab.enterprise", "password": "x"})
    assert response.status_code == 401


def test_requests_without_valid_token_are_rejected(client):
    assert client.get(f"{API}/projects").status_code == 401
    assert client.get(f"{API}/projects", headers={"Authorization": "Bearer falso.token"}).status_code == 401


def test_project_list_only_shows_membership(client):
    ids = {p["id"] for p in client.get(f"{API}/projects", headers=ANA).json()}
    assert "PRJ-101" in ids and "PRJ-102" not in ids
    admin_ids = {p["id"] for p in client.get(f"{API}/projects", headers=SOFIA).json()}
    assert {"PRJ-101", "PRJ-102"} <= admin_ids


def test_foreign_project_is_invisible(client):
    # Diego no pertenece a PRJ-101: recibe 404, no 403, para no revelar que existe.
    assert client.get(f"{API}/projects/PRJ-101", headers=DIEGO).status_code == 404
    assert client.get(f"{API}/projects/PRJ-101/datasets", headers=DIEGO).status_code == 404


def test_reader_cannot_write(client):
    payload = {"name": "lectora", "family": "FEEDFORWARD", "input": {"features": 4},
               "layers": [{"type": "Dense", "units": 3, "activation": "softmax"}]}
    assert client.post(f"{API}/projects/PRJ-101/architectures", json=payload, headers=CARLA).status_code == 403
    assert client.post(f"{API}/projects", json={"name": "No permitido", "family": "RNN"}, headers=CARLA).status_code == 403


def test_create_project_and_manage_members(client):
    created = client.post(f"{API}/projects", headers=LUIS, json={
        "name": "Detección de fraude", "family": "FEEDFORWARD", "tags": ["Banca", "banca", " tabular "],
    })
    assert created.status_code == 201
    project = created.json()
    assert project["myRole"] == "owner" and project["tags"] == ["Banca", "tabular"]
    pid = project["id"]

    added = client.post(f"{API}/projects/{pid}/members", headers=LUIS, json={"userId": "USR-207", "role": "engineer"})
    assert {m["userId"] for m in added.json()["members"]} == {"USR-212", "USR-207"}
    # Un engineer del proyecto no gestiona miembros.
    assert client.post(f"{API}/projects/{pid}/members", headers=ANA, json={"userId": "USR-218", "role": "reviewer"}).status_code == 403
    # El único responsable no puede quedarse fuera.
    assert client.delete(f"{API}/projects/{pid}/members/USR-212", headers=LUIS).status_code == 409

    audit = client.get(f"{API}/projects/{pid}/audit-events", headers=LUIS).json()
    assert {"project.create", "members.change"} <= {event["action"] for event in audit}
