"""Modelo de datos (§8 del Documento Maestro).

Los archivos (CSV, pesos, preprocesadores) viven en el almacenamiento de
objetos; las tablas solo guardan metadatos y su `storage_key`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, UTCDateTime, utcnow


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    initials: Mapped[str] = mapped_column(String(4))
    title: Mapped[str] = mapped_column(String(120), default="")
    # Rol global: admin | owner | engineer | reviewer | reader.
    role: Mapped[str] = mapped_column(String(16))
    # ACTIVE | INVITED | SUSPENDED | LOCKED
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Intentos fallidos consecutivos; al superar el límite la cuenta pasa a LOCKED (§11).
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_access_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("PRJ"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    family: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    members: Mapped[list[ProjectMember]] = relationship(back_populates="project", cascade="all, delete-orphan")
    documents: Mapped[list[ProjectDocument]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectDocument.updated_at.desc()"
    )


class ProjectDocument(Base):
    """Documentación de contexto del proyecto (M02)."""

    __tablename__ = "project_documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("DOC"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="documents")


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    # Rol dentro del proyecto: owner | engineer | reviewer | reader.
    role: Mapped[str] = mapped_column(String(16))
    added_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("project_id", "name", "version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("DS"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(Text, default="")
    format: Mapped[str] = mapped_column(String(8), default="CSV")
    # READY | QUARANTINED | DELETED
    status: Mapped[str] = mapped_column(String(16), default="READY")
    storage_key: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    rows: Mapped[int] = mapped_column(Integer)
    columns: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    privacy: Mapped[str] = mapped_column(String(16), default="INTERNAL")
    # PROJECT | ENGINEERS | OWNER: quién del proyecto puede leerlo.
    access: Mapped[str] = mapped_column(String(16), default="PROJECT")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    license: Mapped[str] = mapped_column(String(80), default="")
    split: Mapped[dict[str, float]] = mapped_column(JSON)
    # Esquema verificado (RN-01): tipos, nulos y cardinalidad por columna.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    project: Mapped[Project] = relationship()
    author: Mapped[User] = relationship()


class Architecture(Base):
    __tablename__ = "architectures"
    __table_args__ = (UniqueConstraint("project_id", "name", "version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ARC"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    family: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    justification: Mapped[str] = mapped_column(Text, default="")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class TrainingJob(Base):
    __tablename__ = "training_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("JOB"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    architecture_id: Mapped[str] = mapped_column(ForeignKey("architectures.id"))
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"))
    target_column: Mapped[str] = mapped_column(String(120))
    # Parámetros congelados al encolar: epochs, batchSize, optimizer, learningRate, seed...
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    code_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=2)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    epoch: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Traza técnica protegida: solo la ven administradores (§12 Confiabilidad).
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    retry_of_id: Mapped[str | None] = mapped_column(ForeignKey("training_jobs.id"), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    queued_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    project: Mapped[Project] = relationship()
    architecture: Mapped[Architecture] = relationship()
    dataset: Mapped[Dataset] = relationship()
    owner: Mapped[User] = relationship(foreign_keys=[created_by])


class TrainingMetric(Base):
    __tablename__ = "training_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("training_jobs.id"), index=True)
    epoch: Mapped[int] = mapped_column(Integer)
    metric_name: Mapped[str] = mapped_column(String(40))
    metric_value: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class TrainingEvent(Base):
    """Bitácora ordenada del trabajo; su `id` es el `Last-Event-ID` del canal SSE."""

    __tablename__ = "training_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("training_jobs.id"), index=True)
    # status | metric | log
    type: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("project_id", "name", "version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("MDL"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("training_jobs.id"), unique=True)
    architecture_id: Mapped[str] = mapped_column(ForeignKey("architectures.id"))
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(255))
    checksum: Mapped[str] = mapped_column(String(64))
    # DRAFT | REVIEWED | APPROVED | RETIRED
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    job: Mapped[TrainingJob] = relationship()


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(String(32), index=True)
    project_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(32))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class JobObservation(Base):
    """Limitaciones, riesgos y observaciones registrados sobre una evaluación (M07)."""

    __tablename__ = "job_observations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("OBS"))
    job_id: Mapped[str] = mapped_column(ForeignKey("training_jobs.id"), index=True)
    # LIMITATION | OBSERVATION | RISK
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Setting(Base):
    """Ajustes editables desde M10; prevalecen sobre los valores por defecto del entorno."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class WorkerNode(Base):
    """Latido de cada worker; alimenta la salud del sistema y la recuperación."""

    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(120))
    pid: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="IDLE")
    current_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
