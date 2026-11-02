"""Callback que persiste cada época y aplica la cancelación cooperativa (RN-05)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import keras

from app.core.database import SessionLocal, utcnow
from app.modules import state_machine as sm
from app.repositories.models import TrainingJob, TrainingMetric, WorkerNode
from app.services import job_events

# Se activa con Ctrl+C: el worker termina la época en curso y sale limpio.
shutdown_requested = threading.Event()


class ProgressCallback(keras.callbacks.Callback):
    def __init__(
        self,
        job_id: str,
        worker_id: str,
        epochs: int,
        max_seconds: int,
        extra: Callable[[keras.Model], dict[str, float]] | None = None,
    ) -> None:
        super().__init__()
        self.job_id = job_id
        self.worker_id = worker_id
        self.epochs = epochs
        self.deadline = time.monotonic() + max_seconds
        # Métricas adicionales por época que Keras no calcula (p. ej. F1 macro).
        self.extra = extra
        self.stop_reason: str | None = None

    def on_epoch_end(self, epoch: int, logs: dict[str, Any] | None = None) -> None:
        values = {name: float(value) for name, value in (logs or {}).items() if name != "learning_rate"}
        if self.extra is not None:
            values.update(self.extra(self.model))
        number = epoch + 1
        now = utcnow()
        with SessionLocal() as db:
            job = db.get(TrainingJob, self.job_id)
            if job.status != sm.RUNNING or job.worker_id != self.worker_id:
                # La recuperación cerró el trabajo (se creyó caído a este worker): no se escribe nada más.
                self.stop_reason = "lost"
                self.model.stop_training = True
                return
            db.add_all(
                TrainingMetric(job_id=self.job_id, epoch=number, metric_name=name, metric_value=value, recorded_at=now)
                for name, value in values.items()
            )
            job.epoch = number
            # El 100 % se reserva para cuando la evaluación final y el registro terminan.
            job.progress = min(99.0, number / self.epochs * 100)
            job.heartbeat_at = now
            job.result_json = {**job.result_json, "latest": values}
            job_events.emit(db, self.job_id, "metric", epoch=number, epochs=self.epochs, progress=job.progress, **values)

            worker = db.get(WorkerNode, self.worker_id)
            if worker is not None:
                worker.last_seen_at = now

            if job.cancel_requested:
                self.stop_reason = "cancelled"
            elif shutdown_requested.is_set():
                self.stop_reason = "shutdown"
            elif time.monotonic() > self.deadline:
                self.stop_reason = "timeout"
            if self.stop_reason:
                self.model.stop_training = True
                job_events.log(db, self.job_id, f"Deteniendo al final de la época {number} ({self.stop_reason}).", "warn")
            db.commit()
