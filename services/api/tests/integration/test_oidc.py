"""Proveedor de identidad externo (§11): validación de tokens OIDC y enlace de cuentas.

Se firma con una clave RSA generada en la prueba y se inyecta como si viniera del JWKS
del proveedor; no hace falta Keycloak en marcha.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import oidc
from app.core.config import settings

ISSUER = "http://localhost:8180/realms/neurolab"
AUDIENCE = "neurolab-api"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _LocalVerifier(oidc.OidcVerifier):
    def discovery(self):
        base = f"{ISSUER}/protocol/openid-connect"
        return {"authorization_endpoint": f"{base}/auth", "token_endpoint": f"{base}/token",
                "end_session_endpoint": f"{base}/logout", "jwks_uri": f"{base}/certs"}

    def jwks_client(self):
        public = _KEY.public_key()
        return SimpleNamespace(get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public))


@pytest.fixture
def oidc_mode():
    previous = {name: getattr(settings, name) for name in ("auth_provider", "oidc_issuer")}
    object.__setattr__(settings, "auth_provider", "oidc")
    object.__setattr__(settings, "oidc_issuer", ISSUER)
    oidc.set_verifier(_LocalVerifier(ISSUER, AUDIENCE))
    yield
    for name, value in previous.items():
        object.__setattr__(settings, name, value)
    oidc.set_verifier(None)


def _token(email: str | None, *, sub: str | None = None, key=_KEY, verified: bool = True, **overrides) -> dict:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": [AUDIENCE, "account"],
        "sub": sub or str(uuid.uuid4()),
        "iat": now,
        "exp": now + 300,
        "email_verified": verified,
        "azp": "neurolab-web",
    }
    if email:
        claims["email"] = email
    claims.update(overrides)
    return {"Authorization": f"Bearer {jwt.encode(claims, key, algorithm='RS256')}"}


def test_config_is_public_and_describes_the_provider(client, oidc_mode):
    body = client.get("/api/v1/auth/config").json()
    base = f"{ISSUER}/protocol/openid-connect"
    assert body == {"provider": "oidc", "issuer": ISSUER, "clientId": "neurolab-web", "devLogin": False,
                    "authorizationEndpoint": f"{base}/auth", "tokenEndpoint": f"{base}/token",
                    "endSessionEndpoint": f"{base}/logout"}


def test_first_access_links_the_account_by_verified_email(client, oidc_mode):
    sub = str(uuid.uuid4())
    me = client.get("/api/v1/auth/me", headers=_token("Sofia.Ramirez@neurolab.enterprise", sub=sub))
    assert me.status_code == 200, me.text
    assert me.json()["id"] == "USR-201"

    # Ya enlazada, la cuenta se reconoce por `sub` aunque el correo cambie en el proveedor.
    again = client.get("/api/v1/auth/me", headers=_token("otro@correo.example", sub=sub))
    assert again.json()["id"] == "USR-201"

    # Otra cuenta del proveedor con el mismo correo no puede apropiarse del usuario.
    intruder = client.get("/api/v1/auth/me", headers=_token("sofia.ramirez@neurolab.enterprise"))
    assert intruder.status_code == 403


def test_session_endpoint_records_the_login(client, oidc_mode):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.repositories.models import AuditEvent

    me = client.post("/api/v1/auth/session", headers=_token("rosa.medina@neurolab.enterprise"))
    assert me.status_code == 200, me.text
    assert me.json()["id"] == "USR-218"
    with SessionLocal() as db:
        event = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.login",
                                                    AuditEvent.actor_id == "USR-218")
                           .order_by(AuditEvent.id.desc())).first()
    assert event is not None and event.metadata_json == {"proveedor": "oidc"}


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(lambda: _token("luis.paredes@neurolab.enterprise", exp=int(time.time()) - 120), id="expirado"),
        pytest.param(lambda: _token("luis.paredes@neurolab.enterprise", aud="otra-api"), id="audiencia"),
        pytest.param(lambda: _token("luis.paredes@neurolab.enterprise", iss="http://falso/realms/neurolab"), id="emisor"),
        pytest.param(lambda: _token("luis.paredes@neurolab.enterprise", key=_OTHER_KEY), id="firma"),
        pytest.param(lambda: {"Authorization": "Bearer no-es-un-jwt"}, id="basura"),
    ],
)
def test_invalid_tokens_are_rejected(client, oidc_mode, headers):
    assert client.get("/api/v1/auth/me", headers=headers()).status_code == 401


def test_unknown_or_unverified_accounts_are_refused(client, oidc_mode):
    assert client.get("/api/v1/auth/me", headers=_token("nadie@externo.example")).status_code == 403
    unverified = _token("carla.nunez@neurolab.enterprise", verified=False)
    assert client.get("/api/v1/auth/me", headers=unverified).status_code == 403
    assert client.get("/api/v1/auth/me", headers=_token(None)).status_code == 403


def test_config_reports_an_unreachable_provider(client, oidc_mode):
    class _Down(oidc.OidcVerifier):
        def _fetch_json(self, url):
            raise OSError("conexión rechazada")

    oidc.set_verifier(_Down(ISSUER, AUDIENCE))
    assert client.get("/api/v1/auth/config").status_code == 503
    assert client.get("/api/v1/auth/me", headers=_token("ana.quispe@neurolab.enterprise")).status_code == 401


def test_local_credentials_are_disabled(client, oidc_mode):
    login = client.post("/api/v1/auth/login", json={"email": "sofia.ramirez@neurolab.enterprise",
                                                    "password": settings.demo_password})
    assert login.status_code == 404
    assert client.post("/api/v1/auth/dev-login", json={"userId": "USR-201"}).status_code == 404
    # Los tokens propios de NeuroLab tampoco valen con el proveedor activo.
    from tests.conftest import SOFIA

    assert client.get("/api/v1/auth/me", headers=SOFIA).status_code == 401
