"""Conversión de filas ORM a los contratos públicos de la API."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.modules.architecture import is_trainable_family
from app.modules.permissions import permissions_for
from app.repositories.models import (
    Architecture,
    AuditEvent,
    Dataset,
    ModelVersion,
    Project,
    TrainingJob,
    User,
)
from app.schemas.architecture import ArchitectureOut, ArchitectureSummary
from app.schemas.dataset import DatasetOut
from app.schemas.project import ProjectDocumentOut, ProjectMemberOut, ProjectOut, UserOut
from app.schemas.training import PRIORITY_RANK, AuditEventOut, ModelVersionOut, TrainingJobOut

_PRIORITY_BY_RANK = {rank: name for name, rank in PRIORITY_RANK.items()}


def user_out(user: User) -> UserOut:
    return UserOut.model_validate(user)


def project_out(project: Project, my_role: str) -> ProjectOut:
    members = [
        ProjectMemberOut(
            user_id=member.user_id,
            display_name=member.user.display_name,
            role=member.role,
            added_at=member.added_at,
        )
        for member in sorted(project.members, key=lambda m: m.added_at)
    ]
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        family=project.family,
        status=project.status,
        owner_id=project.owner_id,
        members=members,
        tags=project.tags,
        documents=[ProjectDocumentOut.model_validate(document) for document in project.documents],
        created_at=project.created_at,
        updated_at=project.updated_at,
        my_role=my_role,
        permissions=permissions_for(my_role),
    )


def architecture_out(arch: Architecture) -> ArchitectureOut:
    return ArchitectureOut(
        id=arch.id,
        project_id=arch.project_id,
        name=arch.name,
        family=arch.family,
        version=arch.version,
        justification=arch.justification,
        config=arch.config_json,
        summary=ArchitectureSummary.model_validate(arch.summary_json),
        trainable=is_trainable_family(arch.family),
        created_by=arch.created_by,
        created_at=arch.created_at,
    )


def dataset_out(dataset: Dataset) -> DatasetOut:
    return DatasetOut(
        id=dataset.id,
        project_id=dataset.project_id,
        project_name=dataset.project.name,
        name=dataset.name,
        version=dataset.version,
        description=dataset.description,
        format=dataset.format,
        status=dataset.status,
        original_filename=dataset.original_filename,
        size_bytes=dataset.size_bytes,
        rows=dataset.rows,
        columns=dataset.columns,
        checksum=dataset.checksum,
        privacy=dataset.privacy,
        access=dataset.access,
        tags=dataset.tags or [],
        license=dataset.license,
        split=dataset.split,
        column_schema=dataset.metadata_json.get("schema", []),
        warnings=dataset.metadata_json.get("warnings", []),
        created_by=dataset.created_by,
        created_by_name=dataset.author.display_name,
        created_at=dataset.created_at,
    )


def job_out(db: Session, job: TrainingJob, include_error: bool = False) -> TrainingJobOut:
    params = job.params_json
    latest = job.result_json.get("latest", {})
    end = job.ended_at or (utcnow() if job.started_at else None)
    duration = int((end - job.started_at).total_seconds()) if job.started_at and end else 0
    model_id = db.scalar(select(ModelVersion.id).where(ModelVersion.job_id == job.id))
    return TrainingJobOut(
        id=job.id,
        project=job.project.name,
        project_id=job.project_id,
        architecture_id=job.architecture_id,
        architecture_name=job.architecture.name,
        architecture_version=job.architecture.version,
        family=job.architecture.family,
        dataset_id=job.dataset_id,
        dataset_name=job.dataset.name,
        dataset_version=job.dataset.version,
        target_column=job.target_column,
        status=job.status,
        status_reason=job.status_reason,
        priority=_PRIORITY_BY_RANK.get(max(job.priority, 0), "NORMAL"),
        epochs=params["epochs"],
        epoch=job.epoch,
        batch=params["batchSize"],
        optimizer=params["optimizer"],
        learning_rate=params["learningRate"],
        seed=params["seed"],
        loss=latest.get("loss", 0.0),
        accuracy=latest.get("accuracy", 0.0),
        val_loss=latest.get("val_loss", 0.0),
        val_accuracy=latest.get("val_accuracy", 0.0),
        task=params.get("task", "classification"),
        class_weight=params.get("classWeight", "none"),
        threshold=params.get("threshold"),
        mae=latest.get("mae"),
        val_mae=latest.get("val_mae"),
        progress=round(job.progress, 1),
        queued_at=job.queued_at,
        started_at=job.started_at,
        ended_at=job.ended_at,
        duration_seconds=duration,
        owner=job.owner.display_name,
        owner_id=job.created_by,
        cancel_requested=job.cancel_requested,
        attempt=job.attempt,
        retry_of_id=job.retry_of_id,
        code_version=job.code_version,
        model_version_id=model_id,
        error_detail=job.error_detail if include_error else None,
    )


def model_out(model: ModelVersion) -> ModelVersionOut:
    return ModelVersionOut(
        id=model.id,
        project_id=model.project_id,
        job_id=model.job_id,
        architecture_id=model.architecture_id,
        name=model.name,
        version=model.version,
        label=f"v{model.version}.0",
        status=model.status,
        checksum=model.checksum,
        metrics=model.metrics_json,
        metadata=model.metadata_json,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def audit_out(event: AuditEvent, names: dict[str, str]) -> AuditEventOut:
    return AuditEventOut(
        id=event.id,
        actor_id=event.actor_id,
        actor=names.get(event.actor_id, event.actor_id),
        project_id=event.project_id,
        action=event.action,
        target_type=event.target_type,
        target_id=event.target_id,
        metadata=event.metadata_json,
        created_at=event.created_at,
    )
