"""Contratos de M06 (entrenamientos), M07 (evaluación) y M08 (registro de modelos)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.architecture import NetworkFamily
from app.schemas.common import CamelModel

JobStatus = Literal["QUEUED", "PREPARING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
Priority = Literal["CRITICA", "ALTA", "NORMAL", "BAJA"]
PRIORITY_RANK: dict[str, int] = {"CRITICA": 0, "ALTA": 1, "NORMAL": 2, "BAJA": 3}


class TrainingJobIn(CamelModel):
    architecture_id: str
    dataset_id: str
    target_column: str = Field(min_length=1, max_length=120)
    task: Literal["auto", "classification", "regression"] = "auto"
    epochs: int = Field(default=30, ge=1)
    batch_size: int = Field(default=16, ge=1)
    optimizer: Literal["adam", "adamw", "sgd", "rmsprop"] = "adam"
    learning_rate: float = Field(default=0.001, gt=0, le=1)
    early_stopping_patience: int | None = Field(default=None, ge=1, le=100)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    priority: Priority = "NORMAL"


class PriorityIn(CamelModel):
    priority: Priority


class ObservationIn(CamelModel):
    kind: Literal["LIMITATION", "OBSERVATION", "RISK"]
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=3, max_length=4000)


class ObservationOut(CamelModel):
    id: str
    run_id: str
    kind: str
    title: str
    body: str
    author: str
    created_at: datetime
    reviewed: bool


class CancelIn(CamelModel):
    reason: str = Field(default="Cancelado por el usuario.", max_length=500)


class TrainingJobOut(CamelModel):
    """Forma de `TrainingJob` en `apps/web/src/types/domain.ts`, más trazabilidad."""

    id: str
    project: str
    project_id: str
    architecture_id: str
    architecture_name: str
    architecture_version: int
    family: NetworkFamily
    dataset_id: str
    dataset_name: str
    dataset_version: int
    target_column: str
    status: JobStatus
    status_reason: str | None
    priority: Priority
    epochs: int
    epoch: int
    batch: int
    optimizer: str
    learning_rate: float
    seed: int
    loss: float
    accuracy: float
    val_loss: float
    val_accuracy: float
    progress: float
    queued_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int
    owner: str
    owner_id: str
    cancel_requested: bool
    attempt: int
    retry_of_id: str | None
    code_version: str
    model_version_id: str | None
    error_detail: str | None = None


class EpochPoint(CamelModel):
    epoch: int
    loss: float
    val_loss: float
    accuracy: float
    val_accuracy: float
    metrics: dict[str, float]


class JobCurves(CamelModel):
    job_id: str
    epoch: int
    points: list[EpochPoint]


class JobEventOut(CamelModel):
    id: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


ModelStatus = Literal["DRAFT", "REVIEWED", "APPROVED", "RETIRED"]


class ModelVersionOut(CamelModel):
    id: str
    project_id: str
    job_id: str
    architecture_id: str
    name: str
    version: int
    label: str
    status: ModelStatus
    checksum: str
    metrics: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ModelStatusIn(CamelModel):
    status: ModelStatus
    note: str = Field(default="", max_length=1000)


class AuditEventOut(CamelModel):
    id: int
    actor_id: str
    actor: str
    project_id: str | None
    action: str
    target_type: str
    target_id: str
    metadata: dict[str, Any]
    created_at: datetime
