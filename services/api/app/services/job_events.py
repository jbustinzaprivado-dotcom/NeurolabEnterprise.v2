"""Transiciones y bitácora de los entrenamientos, compartidas por API y worker.

Cada cambio de estado queda persistido y genera un `TrainingEvent`; el canal
SSE solo reenvía esos eventos, así REST sigue siendo la fuente de verdad (§5).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.modules import state_machine as sm
from app.repositories.models import TrainingEvent, TrainingJob


def emit(db: Session, job_id: str, type_: str, **payload: Any) -> None:
    db.add(TrainingEvent(job_id=job_id, type=type_, payload=payload))


def log(db: Session, job_id: str, message: str, level: str = "info") -> None:
    emit(db, job_id, "log", level=level, message=message)


def transition(db: Session, job: TrainingJob, target: str, reason: str | None = None) -> None:
    sm.ensure_transition(job.status, target)
    previous, job.status = job.status, target
    now = utcnow()
    if target == sm.RUNNING:
        job.started_at = now
    if target in sm.TERMINAL:
        job.ended_at = now
        if target == sm.COMPLETED:
            job.progress = 100.0
    if reason:
        job.status_reason = reason
    emit(db, job.id, "status", previous=previous, status=target, reason=reason, progress=job.progress, epoch=job.epoch)
