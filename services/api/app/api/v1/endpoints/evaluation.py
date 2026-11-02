"""M07 · Evaluación: ejecuciones evaluadas sobre la partición de prueba y observaciones."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser, load_job
from app.modules import state_machine as sm
from app.modules.permissions import allowed, project_role
from app.repositories.models import JobObservation, ModelVersion, ProjectMember, TrainingJob, TrainingMetric, User
from app.schemas.training import ObservationIn, ObservationOut
from app.services import audit

router = APIRouter(tags=["evaluation"])


def _accessible_jobs(db: Session, user: User, project_id: str | None):
    query = select(TrainingJob).where(TrainingJob.status == sm.COMPLETED)
    if user.role != "admin":
        query = query.join(ProjectMember, ProjectMember.project_id == TrainingJob.project_id).where(
            ProjectMember.user_id == user.id
        )
    if project_id:
        query = query.where(TrainingJob.project_id == project_id)
    return db.scalars(query.order_by(TrainingJob.ended_at.desc()))


def _short(label: str) -> str:
    return label[:4].upper() if len(label) > 4 else label.upper()


def evaluation_run(db: Session, job: TrainingJob) -> dict | None:
    """Forma `EvaluationRun` de `apps/web/src/types/evaluation.ts`.

    Clasificación trae la matriz de confusión; regresión, R², RMSE y MAE de prueba en las
    unidades del objetivo (la matriz queda vacía).
    """
    evaluation = job.result_json.get("evaluation")
    if not evaluation or evaluation.get("task") not in {"classification", "regression"}:
        return None
    task = evaluation["task"]

    by_epoch: dict[int, dict[str, float]] = defaultdict(dict)
    for row in db.scalars(select(TrainingMetric).where(TrainingMetric.job_id == job.id)):
        by_epoch[row.epoch][row.metric_name] = row.metric_value
    history = [
        {
            "epoch": epoch,
            "loss": values.get("loss", 0.0),
            "valLoss": values.get("val_loss", 0.0),
            "accuracy": values.get("accuracy", 0.0),
            "valAccuracy": values.get("val_accuracy", 0.0),
            "f1": values.get("f1", values.get("accuracy", 0.0)),
            "valF1": values.get("val_f1", values.get("val_accuracy", 0.0)),
            "mae": values.get("mae"),
            "valMae": values.get("val_mae"),
        }
        for epoch, values in sorted(by_epoch.items())
    ]
    best = min(history, key=lambda point: point["valLoss"])["epoch"] if history else job.epoch
    classes = evaluation["confusionMatrix"]["classes"] if task == "classification" else []
    model = db.scalar(select(ModelVersion).where(ModelVersion.job_id == job.id))
    params = job.params_json
    duration = int((job.ended_at - job.started_at).total_seconds()) if job.started_at and job.ended_at else 0
    return {
        "id": job.id,
        "jobId": job.id,
        "task": task,
        "target": job.target_column,
        "testMetrics": {key: evaluation["test"][key] for key in ("r2", "rmse", "mae") if key in evaluation["test"]},
        "name": f"{job.architecture.name} v{model.version}.0" if model else job.architecture.name,
        "project": job.project.name,
        "projectId": job.project_id,
        "dataset": job.dataset.name,
        "datasetVersion": f"v{job.dataset.version}",
        "family": job.architecture.family,
        "architecture": job.architecture.name,
        "optimizer": params["optimizer"],
        "learningRate": params["learningRate"],
        "batchSize": params["batchSize"],
        "seed": params["seed"],
        "epochs": job.epoch,
        "bestEpoch": best,
        "durationSeconds": duration,
        "finishedAt": job.ended_at.isoformat() if job.ended_at else None,
        "status": job.status,
        "split": "TEST",
        "samples": evaluation["testRows"],
        "testLoss": evaluation["test"].get("loss", 0.0),
        "latencyP95Ms": evaluation.get("latencyP95Ms", 0.0),
        "confusion": [row["counts"] for row in classes],
        "history": history,
        "classes": [{"id": row["label"], "label": row["label"], "short": _short(row["label"])} for row in classes],
        "modelVersionId": model.id if model else None,
    }


@router.get("/evaluations")
def list_evaluations(user: CurrentUser, db: DB, project_id: str | None = Query(default=None, alias="projectId")) -> list[dict]:
    runs = (evaluation_run(db, job) for job in _accessible_jobs(db, user, project_id))
    return [run for run in runs if run is not None]


def _observation_out(row: JobObservation, names: dict[str, str]) -> ObservationOut:
    return ObservationOut(
        id=row.id, run_id=row.job_id, kind=row.kind, title=row.title, body=row.body,
        author=names.get(row.author_id, row.author_id), created_at=row.created_at, reviewed=row.reviewed,
    )


@router.get("/observations", response_model=list[ObservationOut])
def list_observations(user: CurrentUser, db: DB) -> list[ObservationOut]:
    job_ids = [job.id for job in _accessible_jobs(db, user, None)]
    names = dict(db.execute(select(User.id, User.display_name)).all())
    rows = db.scalars(
        select(JobObservation).where(JobObservation.job_id.in_(job_ids)).order_by(JobObservation.created_at.desc())
    )
    return [_observation_out(row, names) for row in rows]


@router.post("/training-jobs/{job_id}/observations", response_model=ObservationOut, status_code=status.HTTP_201_CREATED)
def add_observation(job_id: str, payload: ObservationIn, user: CurrentUser, db: DB) -> ObservationOut:
    job, role = load_job(db, user, job_id)
    if role == "reader":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Los lectores no registran observaciones.")
    row = JobObservation(job_id=job.id, kind=payload.kind, title=payload.title.strip(),
                         body=payload.body.strip(), author_id=user.id)
    db.add(row)
    db.flush()
    audit.record(db, user.id, "observation.create", "observation", row.id, job.project_id, kind=row.kind, jobId=job.id)
    db.commit()
    return _observation_out(row, {user.id: user.display_name})


@router.post("/observations/{observation_id}/review", response_model=ObservationOut)
def toggle_review(observation_id: str, user: CurrentUser, db: DB) -> ObservationOut:
    row = db.get(JobObservation, observation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Observación no encontrada.")
    job = db.get(TrainingJob, row.job_id)
    role = project_role(db, user, job.project_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Observación no encontrada.")
    if not allowed(role, "model.review"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo revisores y responsables marcan observaciones como revisadas.")
    row.reviewed = not row.reviewed
    audit.record(db, user.id, "observation.review", "observation", row.id, job.project_id, reviewed=row.reviewed)
    db.commit()
    names = dict(db.execute(select(User.id, User.display_name)).all())
    return _observation_out(row, names)
