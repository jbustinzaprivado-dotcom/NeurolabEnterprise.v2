"""Auditoría (M10) y reportes exportables (M09)."""

from __future__ import annotations

import csv
import io
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.modules.permissions import require_project
from app.repositories.models import AuditEvent, Project, ProjectMember, TrainingJob, User
from app.schemas.common import CamelModel
from app.schemas.training import AuditEventOut
from app.services import audit
from app.services.serializers import audit_out, job_out

router = APIRouter(tags=["audit", "reports"])


def _names(db) -> dict[str, str]:
    return dict(db.execute(select(User.id, User.display_name)).all())


@router.get("/projects/{project_id}/audit-events", response_model=list[AuditEventOut])
def project_audit(
    project_id: str, user: CurrentUser, db: DB, limit: int = Query(default=100, ge=1, le=500)
) -> list[AuditEventOut]:
    require_project(db, user, project_id, "audit.read")
    rows = db.scalars(
        select(AuditEvent).where(AuditEvent.project_id == project_id).order_by(AuditEvent.id.desc()).limit(limit)
    )
    names = _names(db)
    return [audit_out(row, names) for row in rows]


@router.get("/audit-events", response_model=list[AuditEventOut])
def global_audit(user: CurrentUser, db: DB, limit: int = Query(default=200, ge=1, le=1000)) -> list[AuditEventOut]:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo administración consulta la auditoría global.")
    names = _names(db)
    return [audit_out(row, names) for row in db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit))]


class ReportExportIn(CamelModel):
    """Huella de un informe generado en el navegador (M09); el contenido no viaja a la API."""

    format: Literal["CSV", "PDF"]
    sections: list[str] = Field(max_length=10)
    rows: int = Field(ge=0)
    bytes: int = Field(ge=0)
    fingerprint: str = Field(max_length=128)
    masked: list[str] = Field(default_factory=list, max_length=50)
    scope_label: str = Field(max_length=120)
    actor: dict[str, str]


def _export_out(event: AuditEvent, project_names: dict[str, str]) -> dict:
    meta = event.metadata_json
    return {
        "id": f"EXP-{event.id}",
        "at": event.created_at.isoformat(),
        "actor": meta.get("actor", {"id": event.actor_id, "name": event.actor_id, "roleLabel": "", "projectRoleLabel": ""}),
        "projectId": event.project_id,
        "projectName": project_names.get(event.project_id, event.project_id),
        "format": meta.get("format", "CSV"),
        "sections": meta.get("sections", []),
        "rows": meta.get("rows", 0),
        "bytes": meta.get("bytes", 0),
        "fingerprint": meta.get("fingerprint", ""),
        "masked": meta.get("masked", []),
        "scopeLabel": meta.get("scopeLabel", ""),
    }


@router.get("/reports/exports")
def list_report_exports(user: CurrentUser, db: DB, limit: int = Query(default=40, ge=1, le=200)) -> list[dict]:
    query = select(AuditEvent).where(AuditEvent.action == "report.export", AuditEvent.metadata_json.isnot(None))
    if user.role != "admin":
        mine = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
        query = query.where(AuditEvent.project_id.in_(mine))
    rows = [row for row in db.scalars(query.order_by(AuditEvent.id.desc()).limit(limit)) if "fingerprint" in row.metadata_json]
    project_names = dict(db.execute(select(Project.id, Project.name)).all())
    return [_export_out(row, project_names) for row in rows]


@router.post("/projects/{project_id}/reports/exports", status_code=status.HTTP_201_CREATED)
def record_report_export(project_id: str, payload: ReportExportIn, user: CurrentUser, db: DB) -> dict:
    project, _ = require_project(db, user, project_id, "report.export")
    event = AuditEvent(
        actor_id=user.id, project_id=project_id, action="report.export", target_type="project",
        target_id=project_id, metadata_json=payload.model_dump(by_alias=True), ip=audit.client_ip.get(),
    )
    db.add(event)
    db.commit()
    return _export_out(event, {project.id: project.name})


@router.get("/projects/{project_id}/reports/training-history.csv")
def training_history_csv(project_id: str, user: CurrentUser, db: DB) -> StreamingResponse:
    """Historial de entrenamiento exportable (M09); la exportación queda auditada."""
    project, _ = require_project(db, user, project_id, "report.export")
    jobs = db.scalars(select(TrainingJob).where(TrainingJob.project_id == project_id).order_by(TrainingJob.queued_at))

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "job_id", "estado", "arquitectura", "version_arq", "dataset", "version_dataset", "objetivo",
        "epocas", "epoca_final", "batch", "optimizador", "learning_rate", "semilla",
        "loss", "accuracy", "val_loss", "val_accuracy", "encolado", "inicio", "fin", "duracion_s",
        "responsable", "intento", "motivo",
    ])
    for job in jobs:
        out = job_out(db, job)
        writer.writerow([
            out.id, out.status, out.architecture_name, out.architecture_version, out.dataset_name,
            out.dataset_version, out.target_column, out.epochs, out.epoch, out.batch, out.optimizer,
            out.learning_rate, out.seed, f"{out.loss:.4f}", f"{out.accuracy:.4f}", f"{out.val_loss:.4f}",
            f"{out.val_accuracy:.4f}", out.queued_at.isoformat(),
            out.started_at.isoformat() if out.started_at else "", out.ended_at.isoformat() if out.ended_at else "",
            out.duration_seconds, out.owner, out.attempt, out.status_reason or "",
        ])
    audit.record(db, user.id, "report.export", "project", project_id, project_id, report="training-history")
    db.commit()
    filename = f"historial-{project.id}.csv"
    return StreamingResponse(
        iter(["﻿" + buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
