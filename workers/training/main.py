"""Worker de entrenamiento: proceso independiente de la API (RN-03).

    venv\\Scripts\\python.exe workers\\training\\main.py      (lo usa run.bat)

Toma trabajos QUEUED de la base de datos por prioridad y antigüedad, los
reclama con una actualización condicional (dos workers nunca toman el mismo),
publica su latido y marca como FAILED los trabajos de workers caídos.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "services" / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

from sqlalchemy import inspect, select, update  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal, engine, utcnow  # noqa: E402
from app.modules import state_machine as sm  # noqa: E402
from app.repositories.models import TrainingJob, WorkerNode  # noqa: E402
from app.services import job_events  # noqa: E402
from app.services.retention import apply_retention  # noqa: E402

logger = logging.getLogger("neurolab.worker")

# La política de retención (§11) se revisa al arrancar y luego cada hora.
RETENTION_EVERY_SECONDS = 3600


def heartbeat(worker_id: str, status: str, job_id: str | None = None) -> None:
    with SessionLocal() as db:
        node = db.get(WorkerNode, worker_id)
        if node is None:
            node = WorkerNode(id=worker_id, hostname=socket.gethostname(), pid=os.getpid())
            db.add(node)
        node.status = status
        node.current_job_id = job_id
        node.last_seen_at = utcnow()
        db.commit()


def reap_stale_jobs() -> int:
    """Recuperación (§15): un trabajo sin latido reciente pertenece a un worker caído."""
    cutoff = utcnow() - timedelta(seconds=settings.worker_stale_seconds)
    with SessionLocal() as db:
        stale = list(
            db.scalars(
                select(TrainingJob).where(
                    TrainingJob.status.in_([sm.PREPARING, sm.RUNNING]), TrainingJob.heartbeat_at < cutoff
                )
            )
        )
        for job in stale:
            job_events.transition(db, job, sm.FAILED, "El worker dejó de responder; reintenta el trabajo.")
        db.commit()
        return len(stale)


def claim_next(worker_id: str) -> str | None:
    with SessionLocal() as db:
        candidates = db.scalars(
            select(TrainingJob.id)
            .where(TrainingJob.status == sm.QUEUED)
            .order_by(TrainingJob.priority, TrainingJob.queued_at)
            .limit(5)
        ).all()
        for job_id in candidates:
            sm.ensure_transition(sm.QUEUED, sm.PREPARING)
            claimed = db.execute(
                update(TrainingJob)
                .where(TrainingJob.id == job_id, TrainingJob.status == sm.QUEUED)
                .values(status=sm.PREPARING, worker_id=worker_id, heartbeat_at=utcnow())
            ).rowcount
            if claimed == 1:
                job_events.emit(db, job_id, "status", previous=sm.QUEUED, status=sm.PREPARING,
                                reason=None, progress=0.0, epoch=0)
                job_events.log(db, job_id, f"Asignado al worker {worker_id}.")
                db.commit()
                return job_id
            db.rollback()
    return None


def process_next_job(worker_id: str) -> tuple[str, str] | None:
    """Reclama y ejecuta un trabajo; devuelve (job_id, estado final) o None si la cola está vacía."""
    from workers.training.jobs.runner import run_job

    job_id = claim_next(worker_id)
    if job_id is None:
        return None
    heartbeat(worker_id, "BUSY", job_id)
    final = run_job(job_id, worker_id)
    heartbeat(worker_id, "IDLE")
    return job_id, final


def wait_for_schema() -> None:
    while not inspect(engine).has_table("training_jobs"):
        logger.info("Esperando a que la API cree el esquema de base de datos...")
        time.sleep(2)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from workers.training.callbacks.progress import shutdown_requested

    def on_signal(*_):
        logger.info("Señal de parada: se termina la época en curso y se sale.")
        shutdown_requested.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    wait_for_schema()
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    logger.info("Worker %s listo. Familias entrenables: %s", worker_id, ", ".join(settings.training_families))
    import workers.training.jobs.runner  # noqa: F401  carga TensorFlow una sola vez, antes del primer trabajo

    last_retention = float("-inf")
    while not shutdown_requested.is_set():
        heartbeat(worker_id, "IDLE")
        if reaped := reap_stale_jobs():
            logger.warning("%d trabajos huérfanos marcados como FAILED.", reaped)
        if time.monotonic() - last_retention >= RETENTION_EVERY_SECONDS:
            last_retention = time.monotonic()
            with SessionLocal() as db:
                if counts := {k: v for k, v in apply_retention(db).items() if v}:
                    logger.info("Retención aplicada: %s.", counts)
        result = process_next_job(worker_id)
        if result:
            logger.info("%s terminó en %s.", *result)
        else:
            shutdown_requested.wait(settings.worker_poll_seconds)

    with SessionLocal() as db:
        node = db.get(WorkerNode, worker_id)
        if node:
            node.status = "OFFLINE"
            db.commit()
    logger.info("Worker detenido.")


if __name__ == "__main__":
    main()
