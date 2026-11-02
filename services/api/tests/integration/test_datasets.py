"""M05: carga controlada, versionado y borrado seguro."""

from tests.conftest import ANA, CARLA

API = "/api/v1"
CSV = ("edad,ingreso,segmento,compra\n" + "".join(
    f"{20 + i % 40},{1000 + i * 37},{'A' if i % 3 else 'B'},{'si' if i % 2 else 'no'}\n" for i in range(60)
)).encode()


def upload(client, content=CSV, filename="clientes.csv", headers=ANA, **form):
    return client.post(
        f"{API}/projects/PRJ-101/datasets",
        files={"file": (filename, content, "text/csv")},
        data=form,
        headers=headers,
    )


def test_upload_creates_versions(client):
    first = upload(client)
    assert first.status_code == 201
    body = first.json()
    assert (body["name"], body["version"], body["rows"], body["status"]) == ("clientes", 1, 60, "READY")
    assert {c["name"]: c["kind"] for c in body["columnSchema"]}["segmento"] == "categorical"

    second = upload(client).json()
    assert second["version"] == 2 and second["id"] != body["id"]


def test_upload_rejections(client):
    assert upload(client, filename="datos.xlsx").status_code == 415
    rejected = upload(client, content=b"1,2\n3,4\n")
    assert rejected.status_code == 422
    assert upload(client, train="0.9", validation="0.2", test="0.1").status_code == 422
    assert upload(client, headers=CARLA).status_code == 403


def test_safe_delete(client):
    dataset = upload(client, filename="temporal.csv").json()
    assert client.delete(f"{API}/datasets/{dataset['id']}", headers=ANA).status_code == 204
    assert client.get(f"{API}/datasets/{dataset['id']}", headers=ANA).status_code == 404
    names = {d["id"] for d in client.get(f"{API}/projects/PRJ-101/datasets", headers=ANA).json()}
    assert dataset["id"] not in names
