"""Carga los datos demo no sensibles (§17) si la base está vacía.

Se ejecuta al arrancar la API, o manualmente:
    venv\\Scripts\\python.exe services\\api\\app\\seed.py

El historial de entrenamientos (solo con NEUROLAB_SEED_HISTORY, activo en desarrollo)
se deja en cola: el worker lo ejecuta de verdad con TensorFlow/Keras al arrancar.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, migrate
from app.core.security import hash_password
from app.demo.catalog import PROJECTS, USERS, DemoProject
from app.modules import state_machine as sm
from app.modules.architecture import validate_architecture
from app.modules.datasets import inspect_csv
from app.repositories.models import (
    Architecture,
    Dataset,
    JobObservation,
    Project,
    ProjectDocument,
    ProjectMember,
    TrainingJob,
    User,
)
from app.schemas.architecture import ArchitectureIn
from app.schemas.training import PRIORITY_RANK, TrainingJobIn
from app.services import audit, job_events
from app.services.training import build_params


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _initials(name: str) -> str:
    parts = name.split()
    return (parts[0][0] + parts[1][0]).upper()


def _seed_project(db: Session, spec: DemoProject, with_history: bool) -> int:
    # Se crea activo para que el historial pase la validación (§10); el estado final va al cerrar.
    project = Project(
        id=spec.id, name=spec.name, family=spec.family, status="ACTIVE", owner_id=spec.owner,
        description=spec.description, tags=spec.tags, created_at=_at(spec.created), updated_at=_at(spec.updated),
    )
    for user_id, role, added in spec.members:
        project.members.append(ProjectMember(user_id=user_id, role=role, added_at=_at(added)))
    for title, body, author, updated in spec.documents:
        project.documents.append(ProjectDocument(title=title, body=body, author_id=author, updated_at=_at(updated)))
    db.add(project)
    db.flush()

    datasets: dict[str, Dataset] = {}
    for item in spec.datasets:
        content = item.generator()
        report = inspect_csv(content)
        dataset = Dataset(
            project_id=project.id, name=item.name, version=1, description=item.description,
            original_filename=f"{item.name}.csv", storage_key="", size_bytes=len(content), rows=report.rows,
            columns=report.columns, checksum=hashlib.sha256(content).hexdigest(), privacy=item.privacy,
            tags=item.tags, license=item.license, split={"train": 0.7, "validation": 0.15, "test": 0.15},
            metadata_json={"schema": report.schema, "warnings": report.warnings}, created_by=spec.owner,
            created_at=_at(spec.created),
        )
        db.add(dataset)
        db.flush()
        dataset.storage_key = f"uploads/{project.id}/{dataset.id}.csv"
        path = settings.data_dir / dataset.storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        datasets[item.name] = dataset

    architectures: dict[str, Architecture] = {}
    for item in spec.architectures:
        arch_in = ArchitectureIn.model_validate({
            "name": item.name, "family": item.family, "justification": item.justification,
            "input": item.input, "layers": item.layers,
        })
        summary = validate_architecture(arch_in)
        if not summary.valid:
            raise ValueError(f"Arquitectura demo {item.name} no válida: {summary.issues}")
        arch = Architecture(
            project_id=project.id, name=arch_in.name, family=arch_in.family, version=1,
            justification=arch_in.justification,
            config_json=arch_in.model_dump(mode="json", by_alias=True, exclude={"name", "justification"}),
            summary_json=summary.model_dump(mode="json", by_alias=True), created_by=spec.owner,
            created_at=_at(spec.created),
        )
        db.add(arch)
        db.flush()
        architectures[item.name] = arch

    queued = 0
    if with_history:
        for item in spec.jobs:
            payload = TrainingJobIn(
                architecture_id=architectures[item.architecture].id, dataset_id=datasets[item.dataset].id,
                target_column=item.target, epochs=item.epochs, batch_size=item.batch_size, optimizer=item.optimizer,
                learning_rate=item.learning_rate, early_stopping_patience=item.early_stopping_patience,
                priority=item.priority,
            )
            role = next(role for user_id, role, _ in spec.members if user_id == item.owner)
            job = TrainingJob(
                project_id=project.id, architecture_id=payload.architecture_id, dataset_id=payload.dataset_id,
                target_column=payload.target_column, params_json=build_params(db, project, payload, role),
                code_version=settings.code_version, priority=PRIORITY_RANK[payload.priority], created_by=item.owner,
            )
            db.add(job)
            db.flush()
            job_events.emit(db, job.id, "status", previous=None, status=sm.QUEUED, reason=None, progress=0.0, epoch=0)
            audit.record(db, item.owner, "training.launch", "training_job", job.id, project.id, origen="datos demo")
            if item.cancel_reason:
                job.cancel_requested, job.cancel_reason = True, item.cancel_reason
                job_events.transition(db, job, sm.CANCELLED, item.cancel_reason)
                audit.record(db, item.owner, "training.cancel", "training_job", job.id, project.id, reason=item.cancel_reason)
            else:
                queued += 1
            for kind, title, body, author in item.observations:
                db.add(JobObservation(job_id=job.id, kind=kind, title=title, body=body, author_id=author))

    project.status = spec.status
    project.updated_at = _at(spec.updated)
    audit.record(db, "system", "seed.demo", "project", project.id, project.id)
    return queued


def seed(db: Session, with_history: bool | None = None) -> bool:
    """Carga usuarios y catálogo demo si no hay usuarios; devuelve si cargó algo."""
    if db.scalar(select(User.id).limit(1)):
        return False
    history = settings.seed_history if with_history is None else with_history

    password = hash_password(settings.demo_password)
    for user_id, name, handle, title, role in USERS:
        db.add(User(
            id=user_id, email=f"{handle}@neurolab.enterprise", display_name=name,
            initials=_initials(name), title=title, role=role, password_hash=password,
            mfa_enabled=role in {"admin", "owner", "reviewer"},
        ))
    db.flush()

    queued = sum(_seed_project(db, spec, history) for spec in PROJECTS)
    db.commit()
    if queued:
        print(f"Datos demo: {queued} entrenamientos en cola; el worker los ejecutará al arrancar.")
    return True


if __name__ == "__main__":
    migrate()
    with SessionLocal() as session:
        print("Datos demo creados." if seed(session) else "La base ya tenía datos; no se modificó.")
