"""Reglas de negocio puras: estados, CSV, cabeza de salida, permisos y tokens."""

import time

import pytest

from app.core import security
from app.modules import state_machine as sm
from app.modules.datasets import DatasetRejected, head_matches, inspect_csv, target_profile
from app.modules.permissions import allowed

# ---- RN-02 · máquina de estados ----


@pytest.mark.parametrize(
    "current,target",
    [("QUEUED", "PREPARING"), ("QUEUED", "CANCELLED"), ("PREPARING", "RUNNING"), ("RUNNING", "COMPLETED"),
     ("RUNNING", "CANCELLED"), ("PREPARING", "FAILED")],
)
def test_allowed_transitions(current, target):
    sm.ensure_transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [("QUEUED", "RUNNING"), ("COMPLETED", "RUNNING"), ("FAILED", "QUEUED"), ("CANCELLED", "COMPLETED"),
     ("RUNNING", "PREPARING")],
)
def test_forbidden_transitions(current, target):
    with pytest.raises(sm.InvalidTransition):
        sm.ensure_transition(current, target)


# ---- RN-01 · verificación de CSV ----

GOOD = ("a,b,clase\n" + "".join(f"{i},{i * 2},{'x' if i % 2 else 'y'}\n" for i in range(20))).encode()


def test_valid_csv_schema():
    report = inspect_csv(GOOD)
    assert (report.rows, report.columns) == (20, 3)
    assert [c["kind"] for c in report.schema] == ["integer", "integer", "categorical"]


def test_semicolon_csv_from_spreadsheet():
    report = inspect_csv(GOOD.decode().replace(",", ";").encode("latin-1"))
    assert report.columns == 3


@pytest.mark.parametrize(
    "content,fragment",
    [
        (b"", "vacío"),
        (b"\x00\x01\x02binario", "binario"),
        (("1,2,3\n" * 20).encode(), "encabezados"),
        (("a,a\n" + "1,2\n" * 20).encode(), "duplicados"),
        (b"a,b\n1,2\n3,4\n", "filas"),
        (("solo\n" + "1\n" * 20).encode(), "dos columnas"),
    ],
)
def test_rejected_csv(content, fragment):
    with pytest.raises(DatasetRejected, match=fragment):
        inspect_csv(content)


def test_target_profile_and_head():
    schema = inspect_csv(GOOD).schema
    binary = target_profile(schema, "clase")
    assert binary == {"task": "classification", "classes": 2}
    assert head_matches(binary, 1, "sigmoid") and head_matches(binary, 2, "softmax")
    assert not head_matches(binary, 1, "softmax")
    with pytest.raises(ValueError):
        target_profile(schema, "no_existe")


def test_regression_head():
    schema = [{"name": "y", "kind": "float", "nulls": 0, "unique": 90}]
    profile = target_profile(schema, "y")
    assert profile["task"] == "regression"
    assert head_matches(profile, 1, "linear") and not head_matches(profile, 1, "relu")


# ---- RBAC ----


def test_project_permissions():
    assert allowed("owner", "members.manage")
    assert allowed("engineer", "training.launch")
    assert not allowed("reviewer", "training.launch")
    assert not allowed("reader", "model.download")
    assert allowed("admin", "dataset.delete")
    assert not allowed(None, "project.read")


# ---- Tokens y contraseñas ----


def test_token_roundtrip_and_tampering():
    token, _ = security.issue_token("USR-1")
    assert security.decode_token(token) == "USR-1"
    payload, signature = token.split(".")
    assert security.decode_token(f"{payload}x.{signature}") is None
    assert security.decode_token("basura") is None


def test_expired_token(monkeypatch):
    token, _ = security.issue_token("USR-1", ttl_minutes=1)
    monkeypatch.setattr(time, "time", lambda: 10**10)
    assert security.decode_token(token) is None


def test_password_hash():
    stored = security.hash_password("secreta")
    assert security.verify_password("secreta", stored)
    assert not security.verify_password("otra", stored)
