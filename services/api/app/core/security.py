"""Autenticación (§11).

- `oidc`: tokens del proveedor de identidad externo (Keycloak), validados en `app.core.oidc`.
  La cuenta del proveedor se enlaza con su usuario de NeuroLab por `sub` o, la primera vez,
  por correo verificado; quien no esté registrado en NeuroLab no entra.
- `local`: contraseñas PBKDF2 y tokens firmados con HMAC-SHA256 (desarrollo y pruebas).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db, utcnow
from app.core.oidc import OidcError, get_verifier
from app.core.oidc import subject as oidc_subject
from app.repositories.models import User
from app.services import audit

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, expected = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(digest.hex(), expected)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> str:
    key = settings.resolved_secret_key.encode()
    return _b64(hmac.new(key, payload.encode(), hashlib.sha256).digest())


def issue_token(user_id: str, ttl_minutes: int | None = None) -> tuple[str, int]:
    expires_at = int(time.time()) + 60 * (ttl_minutes or settings.token_ttl_minutes)
    payload = _b64(json.dumps({"sub": user_id, "exp": expires_at}).encode())
    return f"{payload}.{_sign(payload)}", expires_at


def decode_token(token: str) -> str | None:
    """Devuelve el `sub` si la firma es válida y el token no expiró."""
    try:
        payload, signature = token.split(".")
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    try:
        claims = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(claims.get("exp", 0)) < time.time():
        return None
    return claims.get("sub")


_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sesión no válida o expirada.",
    headers={"WWW-Authenticate": "Bearer"},
)


def bearer_subject(token: str) -> str | None:
    """Identificador del portador según el proveedor activo, o None si el token no vale."""
    if settings.oidc_enabled:
        return oidc_subject(token)
    return decode_token(token)


def _not_registered() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Tu cuenta del proveedor de identidad no está registrada en NeuroLab. Solicita acceso a administración.",
    )


def _oidc_user(db: Session, token: str) -> User:
    try:
        claims = get_verifier().verify(token)
    except OidcError as exc:
        raise _UNAUTHORIZED from exc

    user = db.scalar(select(User).where(User.external_subject == claims["sub"]))
    if user is None:
        # Primer acceso: se enlaza por correo, solo si el proveedor lo verificó.
        email = str(claims.get("email", "")).strip().lower()
        if not email or claims.get("email_verified") is not True:
            raise _not_registered()
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user is None or user.external_subject is not None:
            raise _not_registered()
        user.external_subject = claims["sub"]
        audit.record(db, user.id, "auth.linked", "user", user.id)
        db.commit()
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if settings.oidc_enabled:
            user = _oidc_user(db, token)
        else:
            user_id = decode_token(token)
            if user_id is None:
                raise _UNAUTHORIZED
            user = db.get(User, user_id)
    elif settings.auth_dev_bypass:
        user = db.get(User, settings.dev_user_id)
    else:
        raise _UNAUTHORIZED

    if user is None:
        raise _UNAUTHORIZED
    if user.status in {"SUSPENDED", "LOCKED"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La cuenta está suspendida.")
    now = utcnow()
    if user.status == "INVITED":
        # Primer acceso con el proveedor: la invitación queda aceptada.
        user.status, user.status_reason = "ACTIVE", None
        audit.record(db, user.id, "auth.invite_accepted", "user", user.id)
        user.last_access_at = now
        db.commit()
    elif user.last_access_at is None or now - user.last_access_at > timedelta(minutes=5):
        user.last_access_at = now
        db.commit()
    return user
