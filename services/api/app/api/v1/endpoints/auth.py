from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.core.database import utcnow
from app.core.oidc import OidcError, get_verifier
from app.core.security import issue_token, verify_password
from app.repositories.models import User
from app.schemas.common import CamelModel
from app.schemas.project import LoginIn, TokenOut, UserOut
from app.services import audit, platform_settings
from app.services.serializers import user_out

router = APIRouter(tags=["auth"])


class DevLoginIn(CamelModel):
    user_id: str


def _start_session(db: Session, user: User) -> TokenOut:
    if user.status in {"SUSPENDED", "LOCKED"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La cuenta está suspendida.")
    if user.status == "INVITED":
        # Primer acceso: la invitación queda aceptada.
        user.status, user.status_reason = "ACTIVE", None
        audit.record(db, user.id, "auth.invite_accepted", "user", user.id)
    user.last_access_at = utcnow()
    user.failed_logins = 0
    ttl = int(platform_settings.security(db)["sessionMinutes"])
    token, expires_at = issue_token(user.id, ttl)
    audit.record(db, user.id, "auth.login", "user", user.id)
    db.commit()
    return TokenOut(access_token=token, expires_at=expires_at, user=user_out(user))


_IDP_ONLY = "El inicio de sesión se hace con el proveedor de identidad de la organización."


@router.get("/auth/config")
def auth_config() -> dict:
    """Pública: cómo iniciar sesión. La interfaz la lee antes de tener token."""
    if settings.oidc_enabled:
        try:
            endpoints = get_verifier().browser_endpoints()
        except OidcError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                "El proveedor de identidad no responde. Comprueba que Keycloak esté en marcha.") from exc
        return {
            "provider": "oidc",
            "issuer": settings.oidc_issuer,
            "clientId": settings.oidc_client_id,
            "devLogin": False,
            **endpoints,
        }
    return {"provider": "local", "devLogin": settings.auth_dev_bypass}


@router.post("/auth/session", response_model=UserOut)
def oidc_session(user: CurrentUser, db: DB) -> UserOut:
    """La interfaz lo llama al volver del proveedor: deja constancia del inicio de sesión."""
    if not settings.oidc_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No disponible.")
    user.failed_logins = 0
    audit.record(db, user.id, "auth.login", "user", user.id, proveedor="oidc")
    db.commit()
    return user_out(user)


@router.post("/auth/login", response_model=TokenOut)
def login(payload: LoginIn, db: DB) -> TokenOut:
    if settings.oidc_enabled:
        # Con proveedor externo, NeuroLab no guarda ni comprueba contraseñas (§11).
        raise HTTPException(status.HTTP_404_NOT_FOUND, _IDP_ONLY)
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email.strip().lower()))
    # Mismo mensaje para usuario inexistente y contraseña errónea.
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales inválidas.")
    if user.status == "LOCKED":
        raise HTTPException(status.HTTP_403_FORBIDDEN, _LOCKED_MESSAGE)
    if not verify_password(payload.password, user.password_hash):
        # Bloqueo tras intentos fallidos consecutivos (§11); solo administración desbloquea.
        user.failed_logins += 1
        if user.failed_logins >= settings.max_failed_logins:
            user.status = "LOCKED"
            user.status_reason = f"Bloqueada tras {user.failed_logins} intentos fallidos de inicio de sesión."
            audit.record(db, user.id, "auth.locked", "user", user.id, intentos=user.failed_logins)
            db.commit()
            raise HTTPException(status.HTTP_403_FORBIDDEN, _LOCKED_MESSAGE)
        audit.record(db, user.id, "auth.failed", "user", user.id, intentos=user.failed_logins)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales inválidas.")
    return _start_session(db, user)


_LOCKED_MESSAGE = "Cuenta bloqueada por intentos fallidos. Solicita el desbloqueo a administración."


@router.post("/auth/dev-login", response_model=TokenOut)
def dev_login(payload: DevLoginIn, db: DB) -> TokenOut:
    """Solo desarrollo: cambia de usuario demo sin contraseña para probar los roles."""
    if not settings.auth_dev_bypass or settings.oidc_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No disponible.")
    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado.")
    return _start_session(db, user)


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return user_out(user)


@router.get("/users", response_model=list[UserOut])
def directory(user: CurrentUser, db: DB) -> list[UserOut]:
    """Directorio para invitar miembros; no expone datos más allá del perfil público."""
    users = db.scalars(select(User).where(User.status == "ACTIVE").order_by(User.display_name))
    return [user_out(item) for item in users]


@router.get("/config")
def client_config(user: CurrentUser, db: DB) -> dict:
    """Límites vigentes para validar formularios en la interfaz (la API vuelve a validarlos)."""
    limits = platform_settings.limits(db)
    return {
        "maxUploadMb": limits["upload"],
        "maxEpochs": limits["epochs"],
        "maxBatchSize": settings.max_batch_size,
        "maxJobMinutes": limits["duration"],
        "maxActiveJobsPerUser": limits["concurrency"],
        "storageLimitGb": limits["storage"],
        "trainingFamilies": settings.training_families,
        "devLogin": settings.auth_dev_bypass,
        "version": settings.code_version,
    }
