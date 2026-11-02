from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.permissions import require_project
from app.repositories.models import TrainingJob, User

DB = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def load_job(db: Session, user: User, job_id: str, action: str = "project.read") -> tuple[TrainingJob, str]:
    """Carga un trabajo comprobando la pertenencia a su proyecto (§12 Seguridad)."""
    job = db.get(TrainingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entrenamiento no encontrado.")
    try:
        _, role = require_project(db, user, job.project_id, action)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Entrenamiento no encontrado.") from exc
        raise
    return job, role
