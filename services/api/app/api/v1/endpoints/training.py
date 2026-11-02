"""M06 · Entrenamientos y M07 · Evaluación: cola, estado, métricas y canal SSE."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, load_job
from app.core.database import SessionLocal
from app.modules import state_machine as sm
from app.modules.permissions import require_project
from app.repositories.models import ProjectMember, TrainingEvent, TrainingJob, TrainingMetric
from app.schemas.training import (
    CancelIn,
    EpochPoint,
    JobCurves,
    JobEventOut,
    PriorityIn,
    TrainingJobIn,
    TrainingJobOut,
)
from app.services import training as service
from app.services.serializers import job_out

router = APIRouter(tags=["training"])

SSE_POLL_SECONDS = 0.5
SSE_KEEPALIVE_SECONDS = 15.0


@router.post("/projects/{project_id}/training-jobs", response_model=TrainingJobOut, status_code=status.HTTP_202_ACCEPTED)
def launch(project_id: str, payload: TrainingJobIn, user: CurrentUser, db: DB) -> TrainingJobOut:
    """Valida y encola; devuelve el trabajo con su `id` (§9). El worker lo ejecuta."""
    project, role = require_project(db, user, project_id, "training.launch")
    job = service.enqueue(db, user, project, role, payload)
    return job_out(db, job)


@router.get("/projects/{project_id}/training-jobs", response_model=list[TrainingJobOut])
def list_jobs(
    project_id: str,
    user: CurrentUser,
    db: DB,
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[TrainingJobOut]:
    require_project(db, user, project_id)
    query = select(TrainingJob).where(TrainingJob.project_id == project_id)
    if status_:
        query = query.where(TrainingJob.status == status_)
    rows = db.scalars(query.order_by(TrainingJob.queued_at.desc()).limit(limit))
    return [job_out(db, job) for job in rows]


@router.get("/training-jobs", response_model=list[TrainingJobOut])
def list_accessible_jobs(
    user: CurrentUser,
    db: DB,
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[TrainingJobOut]:
    """Trabajos de todos los proyectos a los que el usuario pertenece (M06)."""
    query = select(TrainingJob)
    if user.role != "admin":
        query = query.join(ProjectMember, ProjectMember.project_id == TrainingJob.project_id).where(
            ProjectMember.user_id == user.id
        )
    if status_:
        query = query.where(TrainingJob.status == status_)
    rows = db.scalars(query.order_by(TrainingJob.queued_at.desc()).limit(limit))
    return [job_out(db, job) for job in rows]


@router.post("/training-jobs/{job_id}/priority", response_model=TrainingJobOut)
def change_priority(job_id: str, payload: PriorityIn, user: CurrentUser, db: DB) -> TrainingJobOut:
    job, role = load_job(db, user, job_id, "training.launch")
    service.change_priority(db, user, job, role, payload.priority)
    return job_out(db, job)


@router.post("/training-jobs/{job_id}/start", response_model=TrainingJobOut)
def start_now(job_id: str, user: CurrentUser, db: DB) -> TrainingJobOut:
    job, role = load_job(db, user, job_id, "training.launch")
    service.start_now(db, user, job, role)
    return job_out(db, job)


@router.get("/training-jobs/{job_id}", response_model=TrainingJobOut)
def get_job(job_id: str, user: CurrentUser, db: DB) -> TrainingJobOut:
    """Estado persistido: tras recargar o reconectar, la UI se recupera desde aquí."""
    job, role = load_job(db, user, job_id)
    return job_out(db, job, include_error=role == "admin")


@router.post("/training-jobs/{job_id}/cancel")
def cancel(job_id: str, user: CurrentUser, db: DB, payload: CancelIn | None = None) -> dict:
    job, role = load_job(db, user, job_id, "training.cancel")
    result = service.request_cancel(db, user, job, role, (payload or CancelIn()).reason)
    return {"jobId": job.id, "status": result, "job": job_out(db, job).model_dump(mode="json", by_alias=True)}


@router.post("/training-jobs/{job_id}/retry", response_model=TrainingJobOut, status_code=status.HTTP_202_ACCEPTED)
def retry(job_id: str, user: CurrentUser, db: DB) -> TrainingJobOut:
    job, _ = load_job(db, user, job_id, "training.launch")
    return job_out(db, service.retry(db, user, job))


@router.get("/training-jobs/{job_id}/metrics", response_model=JobCurves)
def metrics(job_id: str, user: CurrentUser, db: DB) -> JobCurves:
    """Curvas época a época (forma `JobCurves` del frontend)."""
    job, _ = load_job(db, user, job_id)
    by_epoch: dict[int, dict[str, float]] = defaultdict(dict)
    rows = db.scalars(select(TrainingMetric).where(TrainingMetric.job_id == job_id).order_by(TrainingMetric.epoch))
    for row in rows:
        by_epoch[row.epoch][row.metric_name] = row.metric_value
    points = [
        EpochPoint(
            epoch=epoch,
            loss=values.get("loss", 0.0),
            val_loss=values.get("val_loss", 0.0),
            accuracy=values.get("accuracy", 0.0),
            val_accuracy=values.get("val_accuracy", 0.0),
            metrics=values,
        )
        for epoch, values in sorted(by_epoch.items())
    ]
    return JobCurves(job_id=job.id, epoch=job.epoch, points=points)


@router.get("/training-jobs/{job_id}/evaluation")
def evaluation(job_id: str, user: CurrentUser, db: DB) -> dict:
    """Evaluación final sobre la partición de prueba (M07)."""
    job, _ = load_job(db, user, job_id)
    result = job.result_json.get("evaluation")
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El trabajo aún no tiene evaluación final.")
    return {"jobId": job.id, **result}


@router.get("/training-jobs/{job_id}/logs", response_model=list[JobEventOut])
def logs(job_id: str, user: CurrentUser, db: DB, after: int = Query(default=0, ge=0)) -> list[JobEventOut]:
    load_job(db, user, job_id)
    rows = db.scalars(
        select(TrainingEvent)
        .where(TrainingEvent.job_id == job_id, TrainingEvent.id > after)
        .order_by(TrainingEvent.id)
        .limit(500)
    )
    return [JobEventOut.model_validate(row) for row in rows]


def _sse(event_id: int | None, event: str, data: dict) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _fetch(job_id: str, after: int) -> tuple[list[TrainingEvent], str]:
    with SessionLocal() as db:
        # El estado se lee antes que los eventos: si ya es final, todos sus eventos están confirmados.
        current = db.get(TrainingJob, job_id).status
        rows = list(
            db.scalars(
                select(TrainingEvent)
                .where(TrainingEvent.job_id == job_id, TrainingEvent.id > after)
                .order_by(TrainingEvent.id)
                .limit(200)
            )
        )
        return rows, current


@router.get("/training-jobs/{job_id}/events")
async def events(
    job_id: str,
    request: Request,
    user: CurrentUser,
    db: DB,
    last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    """Canal SSE autenticado (§9).

    Empieza con un `snapshot` del estado persistido y luego reenvía cada evento
    guardado (`status`, `metric`, `log`). Con `Last-Event-ID` el cliente retoma
    donde se quedó tras una desconexión; al llegar a un estado final emite `end`.
    """
    job, _ = load_job(db, user, job_id)
    snapshot = job_out(db, job).model_dump(mode="json", by_alias=True)
    cursor = last_event_id if last_event_id is not None else after

    async def stream():
        nonlocal cursor
        yield "retry: 3000\n\n"
        yield _sse(None, "snapshot", snapshot)
        idle = 0.0
        while not await request.is_disconnected():
            rows, current = await asyncio.to_thread(_fetch, job_id, cursor)
            for row in rows:
                cursor = row.id
                yield _sse(row.id, row.type, {**row.payload, "createdAt": row.created_at.isoformat()})
            if rows:
                idle = 0.0
                continue
            if current in sm.TERMINAL:
                yield _sse(None, "end", {"status": current})
                return
            await asyncio.sleep(SSE_POLL_SECONDS)
            idle += SSE_POLL_SECONDS
            if idle >= SSE_KEEPALIVE_SECONDS:
                idle = 0.0
                yield ": keep-alive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
