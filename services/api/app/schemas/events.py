"""Contrato de los eventos en tiempo real (§9, §15): canal SSE `/training-jobs/{id}/events`.

El canal abre con `snapshot` (el trabajo tal como lo devuelve REST), reenvía cada evento
persistido (`status`, `metric`, `log`) con su `id` para reanudar con `Last-Event-ID`, y
cierra con `end` cuando el trabajo llega a un estado final. La interfaz
(`apps/web/src/features/training/useJobStream.ts`) depende de estos campos.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.training import JobStatus, TrainingJobOut

TerminalStatus = Literal["COMPLETED", "FAILED", "CANCELLED"]


class _Persisted(BaseModel):
    """Eventos guardados en `training_events`: llevan la fecha en que se registraron."""

    model_config = ConfigDict(extra="forbid")
    created_at: datetime = Field(alias="createdAt")


class StatusEvent(_Persisted):
    previous: JobStatus | None
    status: JobStatus
    reason: str | None
    progress: float = Field(ge=0, le=100)
    epoch: int = Field(ge=0)


class MetricEvent(_Persisted):
    """Fin de una época. Además de estos campos llegan las métricas de Keras de la tarea
    (`accuracy`, `val_accuracy`, `mae`, `f1`…), siempre numéricas."""

    model_config = ConfigDict(extra="allow")
    epoch: int = Field(ge=1)
    epochs: int = Field(ge=1)
    progress: float = Field(ge=0, le=100)
    loss: float
    val_loss: float

    def model_post_init(self, _context) -> None:
        for name, value in (self.model_extra or {}).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"La métrica «{name}» debe ser numérica.")


class LogEvent(_Persisted):
    level: Literal["info", "warn", "error", "success"]
    message: str = Field(min_length=1)


class EndEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TerminalStatus


EVENTS: dict[str, type[BaseModel]] = {
    "snapshot": TrainingJobOut,
    "status": StatusEvent,
    "metric": MetricEvent,
    "log": LogEvent,
    "end": EndEvent,
}
