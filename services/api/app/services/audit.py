"""Auditoría de acciones relevantes (§11): trabajos, permisos, exportaciones y modelos."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.models import AuditEvent

# IP del cliente de la petición en curso; la fija un middleware de la API.
client_ip: ContextVar[str] = ContextVar("client_ip", default="")

# Acción → (etiqueta, categoría, severidad) para la consola de M10.
CATALOG: dict[str, tuple[str, str, str]] = {
    "auth.login": ("Inicio de sesión", "ACCESO", "info"),
    "auth.invite_accepted": ("Invitación aceptada", "ACCESO", "info"),
    "auth.failed": ("Inicio de sesión fallido", "ACCESO", "warning"),
    "auth.locked": ("Cuenta bloqueada por intentos fallidos", "ACCESO", "critical"),
    "retention.applied": ("Política de retención aplicada", "CONFIGURACION", "info"),
    "project.create": ("Proyecto creado", "PERMISOS", "info"),
    "project.update": ("Proyecto actualizado", "CONFIGURACION", "info"),
    "members.change": ("Cambio de rol en proyecto", "PERMISOS", "warning"),
    "members.remove": ("Miembro retirado del proyecto", "PERMISOS", "warning"),
    "document.save": ("Documentación guardada", "CONFIGURACION", "info"),
    "document.delete": ("Documentación eliminada", "CONFIGURACION", "warning"),
    "architecture.create": ("Arquitectura versionada", "CONFIGURACION", "info"),
    "dataset.upload": ("Dataset registrado", "DATASETS", "info"),
    "dataset.reject": ("Carga de dataset rechazada", "DATASETS", "warning"),
    "dataset.delete": ("Dataset eliminado", "DATASETS", "warning"),
    "training.launch": ("Entrenamiento encolado", "ENTRENAMIENTOS", "info"),
    "training.cancel": ("Cancelación solicitada", "ENTRENAMIENTOS", "warning"),
    "training.retry": ("Reintento encolado", "ENTRENAMIENTOS", "info"),
    "training.priority": ("Prioridad cambiada", "ENTRENAMIENTOS", "info"),
    "training.start_now": ("Inicio sin turno", "ENTRENAMIENTOS", "warning"),
    "observation.create": ("Observación registrada", "MODELOS", "info"),
    "observation.review": ("Observación revisada", "MODELOS", "info"),
    "model.register": ("Versión de modelo registrada", "MODELOS", "info"),
    "model.status": ("Estado de modelo cambiado", "MODELOS", "warning"),
    "model.download": ("Descarga de modelo", "EXPORTACIONES", "warning"),
    "report.export": ("Exportación de informe", "EXPORTACIONES", "warning"),
    "audit.export": ("Exportación de auditoría", "EXPORTACIONES", "warning"),
    "user.invited": ("Invitación enviada", "PERMISOS", "info"),
    "user.role_changed": ("Cambio de rol global", "PERMISOS", "warning"),
    "user.suspended": ("Cuenta suspendida", "PERMISOS", "warning"),
    "user.reactivated": ("Cuenta reactivada", "PERMISOS", "info"),
    "user.invite_revoked": ("Invitación revocada", "PERMISOS", "warning"),
    "limits.updated": ("Límite de recursos modificado", "RECURSOS", "warning"),
    "settings.updated": ("Políticas de seguridad actualizadas", "CONFIGURACION", "warning"),
    "seed.demo": ("Datos demo cargados", "CONFIGURACION", "info"),
}


def describe(action: str) -> tuple[str, str, str]:
    return CATALOG.get(action, (action, "CONFIGURACION", "info"))


def record(
    db: Session,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str,
    project_id: str | None = None,
    **metadata: Any,
) -> None:
    """Añade el evento a la sesión; se confirma junto con el cambio que lo origina."""
    db.add(
        AuditEvent(
            actor_id=actor_id,
            project_id=project_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_json=metadata,
            ip=client_ip.get(),
        )
    )
