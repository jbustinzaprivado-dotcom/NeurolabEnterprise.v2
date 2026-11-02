"""Autenticación: contraseñas PBKDF2 y tokens firmados con HMAC-SHA256.

Es el enlace con el proveedor de identidad (§11): sustituir `issue_token` y
`decode_token` por la validación del IdP no cambia el resto de la API.
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
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db, utcnow
from app.repositories.models import User

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


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        user_id = decode_token(header[7:].strip())
        if user_id is None:
            raise _UNAUTHORIZED
    elif settings.auth_dev_bypass:
        user_id = settings.dev_user_id
    else:
        raise _UNAUTHORIZED

    user = db.get(User, user_id)
    if user is None:
        raise _UNAUTHORIZED
    if user.status != "ACTIVE":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La cuenta está suspendida.")
    now = utcnow()
    if user.last_access_at is None or now - user.last_access_at > timedelta(minutes=5):
        user.last_access_at = now
        db.commit()
    return user
