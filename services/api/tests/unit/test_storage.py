"""Almacén de objetos (§5): misma conducta en el backend local y en S3 (simulado con moto)."""

import boto3
import pytest
from moto import mock_aws

from app.core.storage import LocalObjectStore, ObjectNotFound, S3ObjectStore


@pytest.fixture(params=["local", "s3"])
def store(request, tmp_path):
    if request.param == "local":
        yield LocalObjectStore(tmp_path)
        return
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        yield S3ObjectStore("neurolab-pruebas", client)


def test_put_get_list_and_delete(store):
    store.put("uploads/PRJ-1/DS-1.csv", b"a,b\n1,2\n", "text/csv")
    store.put("models/PRJ-1/ff/v1/model.keras", b"pesos")
    store.put("models/PRJ-1/ff/v1/metadata.json", b"{}", "application/json")

    assert store.get("uploads/PRJ-1/DS-1.csv") == b"a,b\n1,2\n"
    assert store.exists("models/PRJ-1/ff/v1/model.keras")
    assert store.list("models/PRJ-1/ff/v1") == ["models/PRJ-1/ff/v1/metadata.json", "models/PRJ-1/ff/v1/model.keras"]
    assert store.list("models/PRJ-1/ff/v2") == []
    assert store.total_bytes() == len(b"a,b\n1,2\n") + len(b"pesos") + 2

    assert store.delete_prefix("models/PRJ-1/ff/v1") == 2
    assert store.list("models/PRJ-1/ff/v1") == []
    store.delete("uploads/PRJ-1/DS-1.csv")
    with pytest.raises(ObjectNotFound):
        store.get("uploads/PRJ-1/DS-1.csv")


def test_prefix_does_not_match_siblings(store):
    """`v1` no debe arrastrar a `v10`: el prefijo se trata como carpeta."""
    store.put("models/P/ff/v1/a", b"1")
    store.put("models/P/ff/v10/a", b"2")
    assert store.list("models/P/ff/v1") == ["models/P/ff/v1/a"]


@pytest.mark.parametrize("key", ["../fuera.csv", "uploads/../../secreto", "uploads\\x.csv", ""])
def test_rejects_keys_that_escape_the_store(store, key):
    with pytest.raises(ValueError):
        store.put(key, b"x")
