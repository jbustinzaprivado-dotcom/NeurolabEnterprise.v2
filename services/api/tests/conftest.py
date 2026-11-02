"""Entorno de pruebas aislado: base PostgreSQL de pruebas y almacenamiento temporal.

§15 pide pruebas de integración contra PostgreSQL: se usa `NEUROLAB_TEST_DATABASE_URL`
(variable o `.env`), cuyo esquema se borra y se vuelve a migrar en cada ejecución. Si no
está configurada, se recurre a SQLite temporal y se avisa de que la cobertura es parcial.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _from_dotenv(key: str) -> str:
    path = ROOT / ".env"
    if not path.is_file():
        return ""
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        name, _, value = raw.strip().partition("=")
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


_DATA_DIR = tempfile.mkdtemp(prefix="neurolab-tests-")
_TEST_URL = os.environ.get("NEUROLAB_TEST_DATABASE_URL") or _from_dotenv("NEUROLAB_TEST_DATABASE_URL")
_DEV_URL = os.environ.get("NEUROLAB_DATABASE_URL") or _from_dotenv("NEUROLAB_DATABASE_URL")

if _TEST_URL:
    # Salvaguarda: las pruebas borran el esquema; nunca deben apuntar a la base de trabajo.
    if _TEST_URL == _DEV_URL or not _TEST_URL.rsplit("/", 1)[-1].endswith("_test"):
        raise RuntimeError("NEUROLAB_TEST_DATABASE_URL debe ser una base distinta cuyo nombre termine en _test.")
    from sqlalchemy import create_engine

    _reset = create_engine(_TEST_URL)
    with _reset.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")
    _reset.dispose()
    os.environ["NEUROLAB_DATABASE_URL"] = _TEST_URL
else:
    warnings.warn(
        "Sin NEUROLAB_TEST_DATABASE_URL: las pruebas usan SQLite temporal, no PostgreSQL (§15).",
        stacklevel=1,
    )
    os.environ["NEUROLAB_DATABASE_URL"] = f"sqlite:///{Path(_DATA_DIR, 'tests.db').as_posix()}"

os.environ["NEUROLAB_DATA_DIR"] = _DATA_DIR
os.environ["NEUROLAB_ENV"] = "test"
os.environ["NEUROLAB_AUTH_DEV_BYPASS"] = "false"
# Las pruebas usan tokens propios; el proveedor OIDC se prueba aparte con claves locales.
os.environ["NEUROLAB_AUTH_PROVIDER"] = "local"
os.environ["NEUROLAB_SEED_DEMO"] = "true"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import issue_token  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Cada prueba empieza con los contadores de tasa a cero (son por IP y por usuario)."""
    from app.core.rate_limit import limiter

    limiter.reset()


@pytest.fixture(scope="session")
def client():
    # Con NEUROLAB_STORAGE_BACKEND=s3 (la CI usa SeaweedFS) el bucket de pruebas se vacía al empezar.
    from app.core.storage import get_store

    store = get_store()
    if store.backend == "s3":
        for prefix in ("uploads", "models"):
            store.delete_prefix(prefix)
    with TestClient(app) as test_client:
        yield test_client
    shutil.rmtree(_DATA_DIR, ignore_errors=True)


def auth(user_id: str) -> dict[str, str]:
    token, _ = issue_token(user_id)
    return {"Authorization": f"Bearer {token}"}


# Usuarios demo (app/seed.py) y su rol en PRJ-101 «Clasificación de especies Iris».
ANA = auth("USR-207")  # engineer global · owner del proyecto
LUIS = auth("USR-212")  # engineer
ROSA = auth("USR-218")  # reviewer
CARLA = auth("USR-231")  # reader
DIEGO = auth("USR-223")  # owner global · ajeno a PRJ-101
SOFIA = auth("USR-201")  # admin
