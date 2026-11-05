"""Límites de recursos y políticas efectivas (M10).

Los valores por defecto salen del entorno (`NEUROLAB_*`); lo que administración
cambia se guarda en la tabla `settings` y prevalece. API y worker leen siempre
desde aquí, así un cambio en la consola se aplica al siguiente trabajo.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.models import Setting

LIMIT_DEFS: dict[str, dict[str, Any]] = {
    "concurrency": {
        "label": "Entrenamientos activos por usuario", "unit": "trabajos", "min": 1, "max": 10, "step": 1,
        "hint": "Trabajos en cola o en ejecución que una persona puede tener a la vez.",
        "default": settings.max_active_jobs_per_user,
    },
    "projectConcurrency": {
        "label": "Entrenamientos activos por proyecto", "unit": "trabajos", "min": 1, "max": 20, "step": 1,
        "hint": "Evita que un solo proyecto acapare la cola compartida.",
        "default": settings.max_active_jobs_per_project,
    },
    "duration": {
        "label": "Duración máxima por trabajo", "unit": "min", "min": 1, "max": 240, "step": 1,
        "hint": "Al superarla, el worker cierra el trabajo al final de la época en curso.",
        "default": max(1, settings.max_job_seconds // 60),
    },
    "epochs": {
        "label": "Épocas por trabajo", "unit": "épocas", "min": 10, "max": 2000, "step": 10,
        "hint": "Tope de épocas que la API acepta al encolar.",
        "default": settings.max_epochs,
    },
    "upload": {
        "label": "Tamaño máximo de carga", "unit": "MB", "min": 1, "max": 500, "step": 1,
        "hint": "Límite por archivo CSV al registrar un dataset (RN-01).",
        "default": settings.max_upload_mb,
    },
    "rate": {
        "label": "Peticiones por minuto y usuario", "unit": "req/min", "min": 60, "max": 3000, "step": 30,
        "hint": "Límite de tasa de la API (§11); el canal SSE no cuenta.",
        "default": settings.rate_limit_per_minute,
    },
    # Recursos de cada entrenamiento (§10): los aplica el worker mientras entrena.
    "cpuThreads": {
        "label": "Núcleos de CPU por trabajo", "unit": "núcleos", "min": 1, "max": 64, "step": 1,
        "hint": "El worker fija el entrenamiento a estos núcleos; el resto queda libre para la API y la base.",
        "default": settings.max_job_cpu_threads,
    },
    "memory": {
        "label": "Memoria por trabajo", "unit": "MB", "min": 512, "max": 65536, "step": 256,
        "hint": "Si el proceso de entrenamiento la supera, el worker lo detiene y lo marca como fallido.",
        "default": settings.max_job_memory_mb,
    },
    "gpu": {
        "label": "GPU por trabajo", "unit": "GPU", "min": 0, "max": 8, "step": 1,
        "hint": "Con 0 el worker no usa GPU. Rige desde que el worker se reinicia (TensorFlow fija las GPU al arrancar).",
        "default": settings.max_job_gpus,
    },
    "storage": {
        "label": "Cuota de almacenamiento", "unit": "GB", "min": 1, "max": 500, "step": 1,
        "hint": "Datasets y artefactos de modelo en el almacenamiento de objetos.",
        "default": settings.storage_limit_gb,
    },
}

SECURITY_DEFAULTS: dict[str, Any] = {
    "sessionMinutes": settings.token_ttl_minutes,
    "mfaPolicy": "ADMINS",
    "auditRetentionDays": 365,
    "artifactRetentionDays": 730,
    "metricsRetentionDays": 365,
    "exportRequiresReview": False,
}


def _stored(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    return row.value if row is not None else None


def _store(db: Session, key: str, value: Any) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def limit(db: Session, limit_id: str) -> float:
    overrides = _stored(db, "limits") or {}
    return overrides.get(limit_id, LIMIT_DEFS[limit_id]["default"])


def limits(db: Session) -> dict[str, float]:
    overrides = _stored(db, "limits") or {}
    return {key: overrides.get(key, meta["default"]) for key, meta in LIMIT_DEFS.items()}


def set_limit(db: Session, limit_id: str, value: float) -> float:
    meta = LIMIT_DEFS[limit_id]
    if not meta["min"] <= value <= meta["max"]:
        raise ValueError(f"{meta['label']} debe estar entre {meta['min']} y {meta['max']} {meta['unit']}.")
    previous = limit(db, limit_id)
    _store(db, "limits", {**(_stored(db, "limits") or {}), limit_id: value})
    return previous


def security(db: Session) -> dict[str, Any]:
    return {**SECURITY_DEFAULTS, **(_stored(db, "security") or {})}


def set_security(db: Session, values: dict[str, Any]) -> list[str]:
    current = security(db)
    changed = [key for key, value in values.items() if current.get(key) != value]
    _store(db, "security", {**current, **values})
    return changed
