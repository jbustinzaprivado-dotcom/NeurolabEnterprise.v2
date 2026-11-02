"""Casos de uso de M06 en la API: validar, encolar, cancelar y reintentar.

La API nunca entrena (RN-03): deja el trabajo en QUEUED y el worker lo toma.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules import datasets as ds
from app.modules import state_machine as sm
from app.modules.architecture import is_trainable_family
from app.repositories.models import Architecture, Dataset, Project, TrainingJob, User
from app.schemas.training import PRIORITY_RANK, TrainingJobIn
from app.services import audit, job_events, platform_settings

# Prioridad máxima que cada rol del proyecto puede asignar ("cola y prioridad por permisos", M06).
PRIORITY_CEILING = {"admin": "CRITICA", "owner": "CRITICA", "engineer": "ALTA"}
# Rango reservado a «iniciar sin turno»: queda por delante de cualquier prioridad.
START_NOW_RANK = -1


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _check_quotas(db: Session, user_id: str, project_id: str) -> None:
    active = select(func.count()).select_from(TrainingJob).where(TrainingJob.status.in_(sm.ACTIVE))
    per_user = int(platform_settings.limit(db, "concurrency"))
    per_project = int(platform_settings.limit(db, "projectConcurrency"))
    if db.scalar(active.where(TrainingJob.created_by == user_id)) >= per_user:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Ya tienes {per_user} entrenamientos activos; espera a que termine alguno.",
        )
    if db.scalar(active.where(TrainingJob.project_id == project_id)) >= per_project:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"El proyecto alcanzó su límite de {per_project} entrenamientos activos.",
        )


def build_params(db: Session, project: Project, payload: TrainingJobIn, role: str) -> dict:
    """Valida todo lo que §10 exige antes de encolar y devuelve los parámetros congelados."""
    arch = db.get(Architecture, payload.architecture_id)
    if arch is None or arch.project_id != project.id:
        raise _unprocessable("La arquitectura no pertenece a este proyecto.")
    dataset = db.get(Dataset, payload.dataset_id)
    if dataset is None or dataset.project_id != project.id or dataset.status == "DELETED":
        raise _unprocessable("El dataset no pertenece a este proyecto.")
    if dataset.status != "READY":
        raise _unprocessable("El dataset no está verificado (RN-01); no se puede entrenar con él.")
    if not arch.summary_json.get("valid"):
        raise _unprocessable("La arquitectura tiene errores de validación; corrígela y guarda una nueva versión.")
    if not is_trainable_family(arch.family):
        raise _unprocessable(
            f"La familia {arch.family} está documentada pero aún no habilitada para entrenamiento "
            f"(habilitadas: {', '.join(settings.training_families)})."
        )
    if project.status == "ARCHIVED":
        raise _unprocessable("El proyecto está archivado: conserva su historial pero no admite nuevos entrenamientos.")
    max_epochs = int(platform_settings.limit(db, "epochs"))
    if payload.epochs > max_epochs:
        raise _unprocessable(f"El máximo de épocas es {max_epochs}.")
    if payload.batch_size > settings.max_batch_size:
        raise _unprocessable(f"El batch size máximo es {settings.max_batch_size}.")

    ceiling = PRIORITY_CEILING.get(role, "NORMAL")
    if PRIORITY_RANK[payload.priority] < PRIORITY_RANK[ceiling]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Tu rol puede asignar como máximo prioridad {ceiling}.")

    schema = dataset.metadata_json.get("schema", [])
    try:
        profile = ds.target_profile(schema, payload.target_column)
    except ValueError as exc:
        raise _unprocessable(str(exc)) from exc
    if payload.task != "auto" and payload.task != profile["task"]:
        column = next(col for col in schema if col["name"] == payload.target_column)
        if payload.task == "regression" and column["kind"] in {"categorical", "boolean"}:
            raise _unprocessable("No se puede hacer regresión sobre un objetivo categórico.")
        if payload.task == "classification" and column["unique"] > ds.MAX_CLASSES:
            raise _unprocessable(f"El objetivo tiene más de {ds.MAX_CLASSES} valores distintos para clasificar.")
        profile = {"task": payload.task, "classes": column["unique"] if payload.task == "classification" else 0}
    if len(schema) - 1 < 1:
        raise _unprocessable("El dataset no tiene columnas de características además del objetivo.")

    head = arch.config_json["layers"][-1]
    if not ds.head_matches(profile, head.get("units"), head.get("activation")):
        raise _unprocessable(
            f"La capa de salida no corresponde al objetivo «{payload.target_column}»: "
            f"se esperaba {ds.expected_head(profile)}."
        )

    return {
        "epochs": payload.epochs,
        "batchSize": payload.batch_size,
        "optimizer": payload.optimizer,
        "learningRate": payload.learning_rate,
        "earlyStoppingPatience": payload.early_stopping_patience,
        "seed": payload.seed,
        "task": profile["task"],
        "classes": profile["classes"],
        "datasetVersion": dataset.version,
        "architectureVersion": arch.version,
    }


def enqueue(db: Session, user: User, project: Project, role: str, payload: TrainingJobIn) -> TrainingJob:
    params = build_params(db, project, payload, role)
    _check_quotas(db, user.id, project.id)
    job = TrainingJob(
        project_id=project.id,
        architecture_id=payload.architecture_id,
        dataset_id=payload.dataset_id,
        target_column=payload.target_column,
        params_json=params,
        code_version=settings.code_version,
        priority=PRIORITY_RANK[payload.priority],
        created_by=user.id,
    )
    db.add(job)
    db.flush()
    job_events.emit(db, job.id, "status", previous=None, status=sm.QUEUED, reason=None, progress=0.0, epoch=0)
    audit.record(db, user.id, "training.launch", "training_job", job.id, project.id, priority=payload.priority, **params)
    db.commit()
    return job


def request_cancel(db: Session, user: User, job: TrainingJob, role: str, reason: str) -> str:
    """Devuelve el estado resultante: CANCELLED si aún estaba en cola, CANCEL_REQUESTED si corre."""
    if role == "engineer" and job.created_by != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puedes cancelar tus propios entrenamientos.")
    if job.status in sm.TERMINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, f"El trabajo ya terminó ({job.status}).")
    if job.cancel_requested:
        return "CANCEL_REQUESTED"

    job.cancel_requested = True
    job.cancel_reason = reason
    if job.status == sm.QUEUED:
        # Nadie lo está ejecutando: la API puede cerrarlo sin esperar al worker.
        job_events.transition(db, job, sm.CANCELLED, reason)
        result = sm.CANCELLED
    else:
        job_events.log(db, job.id, f"Cancelación solicitada: {reason} Se detendrá al terminar la época actual.", "warn")
        result = "CANCEL_REQUESTED"
    audit.record(db, user.id, "training.cancel", "training_job", job.id, job.project_id, reason=reason, status=job.status)
    db.commit()
    return result


def change_priority(db: Session, user: User, job: TrainingJob, role: str, priority: str) -> None:
    if job.status != sm.QUEUED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Solo se cambia la prioridad de un trabajo en cola.")
    if job.created_by != user.id and role not in {"owner", "admin"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Reasignar la prioridad de un trabajo ajeno corresponde al responsable.")
    ceiling = PRIORITY_CEILING.get(role, "NORMAL")
    if PRIORITY_RANK[priority] < PRIORITY_RANK[ceiling]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Tu rol puede asignar como máximo prioridad {ceiling}.")
    previous = job.priority
    job.priority = PRIORITY_RANK[priority]
    job_events.log(db, job.id, f"Prioridad cambiada a {priority}.")
    audit.record(db, user.id, "training.priority", "training_job", job.id, job.project_id,
                 previous=previous, priority=priority)
    db.commit()


def start_now(db: Session, user: User, job: TrainingJob, role: str) -> None:
    """Pasa el trabajo al frente de la cola: el próximo worker libre lo toma primero."""
    if job.status != sm.QUEUED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Solo se adelanta un trabajo que aún está en cola.")
    if job.created_by != user.id and role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Adelantar un trabajo ajeno está reservado a administración.")
    job.priority = START_NOW_RANK
    job_events.log(db, job.id, "Inicio sin turno: pasa al frente de la cola.", "warn")
    audit.record(db, user.id, "training.start_now", "training_job", job.id, job.project_id)
    db.commit()


def retry(db: Session, user: User, job: TrainingJob) -> TrainingJob:
    """Un reintento es un trabajo nuevo: el historial del original no se toca."""
    if job.status not in sm.RETRYABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Solo se reintentan trabajos fallidos o cancelados.")
    dataset = db.get(Dataset, job.dataset_id)
    if dataset is None or dataset.status != "READY":
        raise _unprocessable("El dataset original ya no está disponible.")
    _check_quotas(db, user.id, job.project_id)
    clone = TrainingJob(
        project_id=job.project_id,
        architecture_id=job.architecture_id,
        dataset_id=job.dataset_id,
        target_column=job.target_column,
        params_json=dict(job.params_json),
        code_version=settings.code_version,
        priority=job.priority,
        attempt=job.attempt + 1,
        retry_of_id=job.id,
        created_by=user.id,
    )
    db.add(clone)
    db.flush()
    job_events.emit(db, clone.id, "status", previous=None, status=sm.QUEUED, reason=f"Reintento de {job.id}", progress=0.0, epoch=0)
    audit.record(db, user.id, "training.retry", "training_job", clone.id, job.project_id, retryOf=job.id)
    db.commit()
    return clone
