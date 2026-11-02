"""M10 · Administración y seguridad: cuentas, auditoría, límites, políticas y salud.

Solo para el rol global `admin`. Cada acción devuelve la foto completa de la
consola, de modo que la interfaz se actualiza con una única respuesta.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.core.database import utcnow
from app.core.rate_limit import invalidate_limit_cache, limiter
from app.core.security import hash_password
from app.modules import state_machine as sm
from app.repositories.models import AuditEvent, Dataset, Project, ProjectMember, TrainingJob, User, WorkerNode
from app.schemas.common import CamelModel
from app.schemas.project import UserRole
from app.services import audit, dashboard, platform_settings
from app.services.retention import apply_retention

router = APIRouter(prefix="/admin", tags=["admin"])

# Igual que `statusActionMeta` del frontend.
STATUS_ACTIONS = {
    "ACTIVE": ("SUSPENDED", "user.suspended"),
    "INVITED": ("SUSPENDED", "user.invite_revoked"),
    "SUSPENDED": ("ACTIVE", "user.reactivated"),
    "LOCKED": ("ACTIVE", "user.reactivated"),
}


class InviteIn(CamelModel):
    display_name: str = Field(min_length=3, max_length=120)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    role: UserRole


class RoleIn(CamelModel):
    role: UserRole


class LimitIn(CamelModel):
    value: float


class SecurityIn(CamelModel):
    session_minutes: int = Field(ge=15, le=1440)
    mfa_policy: Literal["ADMINS", "ALL", "OPTIONAL"]
    audit_retention_days: int = Field(ge=30, le=3650)
    artifact_retention_days: int = Field(ge=30, le=3650)
    metrics_retention_days: int = Field(ge=30, le=3650)
    export_requires_review: bool


class AuditExportIn(CamelModel):
    events: int = Field(ge=0)


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo administración accede a la consola de gobierno.")


def _initials(name: str) -> str:
    parts = name.split()
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


def _flat(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    return {key: value if isinstance(value, (str, int, float, bool)) else str(value)
            for key, value in metadata.items() if value is not None}


def _usage(db: Session) -> dict[str, float]:
    """Uso actual de cada límite, para las barras de la consola."""
    active = list(db.scalars(select(TrainingJob).where(TrainingJob.status.in_(sm.ACTIVE))))
    per_user: dict[str, int] = {}
    per_project: dict[str, int] = {}
    for job in active:
        per_user[job.created_by] = per_user.get(job.created_by, 0) + 1
        per_project[job.project_id] = per_project.get(job.project_id, 0) + 1
    longest = max(
        ((utcnow() - job.started_at).total_seconds() / 60 for job in active if job.started_at), default=0
    )
    largest = db.scalar(select(func.max(Dataset.size_bytes)).where(Dataset.status != "DELETED")) or 0
    return {
        "concurrency": max(per_user.values(), default=0),
        "projectConcurrency": max(per_project.values(), default=0),
        "duration": round(longest, 1),
        "epochs": max((job.params_json["epochs"] for job in active), default=0),
        "upload": round(largest / 1024**2, 2),
        "rate": limiter.peak(),
        "storage": dashboard.health(db)["storageUsedGb"],
    }


def _health(db: Session) -> list[dict[str, Any]]:
    started = time.perf_counter()
    data = dashboard.health(db)
    latency = round((time.perf_counter() - started) * 1000)
    cutoff = utcnow() - timedelta(seconds=dashboard.WORKER_ONLINE_SECONDS)
    workers = list(db.scalars(select(WorkerNode).where(WorkerNode.last_seen_at >= cutoff, WorkerNode.status != "OFFLINE")))
    busy = sum(1 for worker in workers if worker.status == "BUSY")
    is_sqlite = settings.resolved_database_url.startswith("sqlite")
    return [
        {"id": "api", "label": "API de plataforma", "status": data["apiStatus"],
         "detail": f"FastAPI {settings.code_version} · {settings.env}", "latencyMs": data["apiLatencyMs"]},
        {"id": "db", "label": "SQLite (modo WAL)" if is_sqlite else "PostgreSQL", "status": data["databaseStatus"],
         "detail": "Base local de desarrollo" if is_sqlite else "Base de datos de producción", "latencyMs": latency},
        {"id": "workers", "label": "Workers de entrenamiento",
         "status": "HEALTHY" if workers else "DOWN" if data["queueDepth"] else "DEGRADED",
         "detail": f"{len(workers)} en línea · {busy} ocupados · cola {data['queueDepth']}", "latencyMs": None},
        {"id": "storage", "label": "Almacenamiento de objetos",
         "status": "HEALTHY" if data["storageUsedGb"] < data["storageLimitGb"] * 0.9 else "DEGRADED",
         "detail": f"{data['storageUsedGb']:.3f} de {data['storageLimitGb']:g} GB en data/", "latencyMs": None},
        {"id": "events", "label": "Canal SSE de eventos", "status": data["apiStatus"],
         "detail": "Eventos persistidos y reanudables con Last-Event-ID", "latencyMs": None},
    ]


def snapshot(db: Session) -> dict[str, Any]:
    users = list(db.scalars(select(User).order_by(User.display_name)))
    memberships = dict(db.execute(
        select(ProjectMember.user_id, func.count()).group_by(ProjectMember.user_id)
    ).all())
    by_id = {user.id: user for user in users}
    projects = dict(db.execute(select(Project.id, Project.name)).all())
    usage = _usage(db)
    limits = platform_settings.limits(db)

    events = []
    for event in db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(500)):
        label, category, severity = audit.describe(event.action)
        actor = by_id.get(event.actor_id)
        target_user = by_id.get(event.target_id) if event.target_type == "user" else None
        events.append({
            "id": f"AUD-{event.id}",
            "createdAt": event.created_at.isoformat(),
            "actorId": event.actor_id,
            "actorName": actor.display_name if actor else "Sistema",
            "actorRole": actor.role if actor else "admin",
            "action": event.action,
            "label": label,
            "category": category,
            "target": f"{target_user.display_name} · {target_user.id}" if target_user
                      else f"{event.target_type} · {event.target_id}",
            "projectId": event.project_id,
            "projectName": projects.get(event.project_id) if event.project_id else None,
            "severity": severity,
            "ip": event.ip or "—",
            "metadata": _flat(event.metadata_json),
        })

    return {
        "users": [
            {
                "id": user.id, "displayName": user.display_name, "email": user.email, "initials": user.initials,
                "title": user.title, "role": user.role, "status": user.status, "mfaEnabled": user.mfa_enabled,
                "projects": memberships.get(user.id, 0),
                "lastAccessAt": user.last_access_at.isoformat() if user.last_access_at else None,
                "createdAt": user.created_at.isoformat(), "statusReason": user.status_reason,
            }
            for user in users
        ],
        "audit": events,
        "limits": [
            {"id": key, "label": meta["label"], "unit": meta["unit"], "used": usage[key], "limit": limits[key],
             "min": meta["min"], "max": meta["max"], "step": meta["step"], "hint": meta["hint"]}
            for key, meta in platform_settings.LIMIT_DEFS.items()
        ],
        "settings": platform_settings.security(db),
        "health": _health(db),
    }


@router.get("/snapshot")
def get_snapshot(user: CurrentUser, db: DB) -> dict:
    _require_admin(user)
    return snapshot(db)


@router.post("/users", status_code=status.HTTP_201_CREATED)
def invite(payload: InviteIn, user: CurrentUser, db: DB) -> dict:
    """Alta en estado INVITED; la invitación se acepta al iniciar sesión por primera vez."""
    _require_admin(user)
    email = payload.email.strip().lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese correo.")
    highest = max((int(uid.split("-")[1]) for uid in db.scalars(select(User.id)) if uid.split("-")[-1].isdigit()), default=200)
    new_user = User(
        id=f"USR-{highest + 1}", email=email, display_name=payload.display_name.strip(),
        initials=_initials(payload.display_name.strip()), title="Invitado", role=payload.role, status="INVITED",
        status_reason="Invitación enviada; pendiente de aceptación.",
        password_hash=hash_password(settings.demo_password),
    )
    db.add(new_user)
    audit.record(db, user.id, "user.invited", "user", new_user.id, correo=email, rol=payload.role)
    db.commit()
    return snapshot(db)


@router.patch("/users/{user_id}/role")
def change_role(user_id: str, payload: RoleIn, user: CurrentUser, db: DB) -> dict:
    _require_admin(user)
    if user_id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "No puedes cambiar tu propio rol desde la consola.")
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado.")
    previous, target.role = target.role, payload.role
    audit.record(db, user.id, "user.role_changed", "user", target.id, rolAnterior=previous, rolNuevo=payload.role)
    db.commit()
    return snapshot(db)


@router.post("/users/{user_id}/status")
def toggle_status(user_id: str, user: CurrentUser, db: DB) -> dict:
    _require_admin(user)
    if user_id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "La sesión de gobierno no puede suspenderse a sí misma.")
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado.")
    next_status, action = STATUS_ACTIONS[target.status]
    label = audit.describe(action)[0]
    previous, target.status = target.status, next_status
    target.status_reason = None if next_status == "ACTIVE" else f"{label} por {user.display_name}."
    if next_status == "ACTIVE":
        target.failed_logins = 0
    audit.record(db, user.id, action, "user", target.id, estadoAnterior=previous, estadoNuevo=next_status)
    db.commit()
    return snapshot(db)


@router.put("/limits/{limit_id}")
def update_limit(limit_id: str, payload: LimitIn, user: CurrentUser, db: DB) -> dict:
    _require_admin(user)
    if limit_id not in platform_settings.LIMIT_DEFS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Límite desconocido.")
    try:
        previous = platform_settings.set_limit(db, limit_id, payload.value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    invalidate_limit_cache()
    meta = platform_settings.LIMIT_DEFS[limit_id]
    audit.record(db, user.id, "limits.updated", "limit", limit_id,
                 limite=meta["label"], anterior=previous, nuevo=payload.value, unidad=meta["unit"])
    db.commit()
    return snapshot(db)


@router.put("/settings")
def update_settings(payload: SecurityIn, user: CurrentUser, db: DB) -> dict:
    _require_admin(user)
    changed = platform_settings.set_security(db, payload.model_dump(by_alias=True))
    if changed:
        audit.record(db, user.id, "settings.updated", "settings", "security", campos=", ".join(changed))
    db.commit()
    return snapshot(db)


@router.post("/retention/run")
def run_retention(user: CurrentUser, db: DB) -> dict:
    """Aplica ahora la política de retención (el worker también la aplica cada hora)."""
    _require_admin(user)
    counts = apply_retention(db)
    return {**snapshot(db), "retention": counts}


@router.post("/audit/export")
def record_audit_export(payload: AuditExportIn, user: CurrentUser, db: DB) -> dict:
    """La descarga la genera el navegador con los eventos visibles; aquí queda trazada."""
    _require_admin(user)
    audit.record(db, user.id, "audit.export", "audit", "csv", formato="CSV", eventos=payload.events)
    db.commit()
    return snapshot(db)
