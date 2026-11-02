"""M01 · Dashboard: agrega el estado real con la forma `DashboardSnapshot` del frontend."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import utcnow
from app.modules import state_machine as sm
from app.repositories.models import ModelVersion, Project, ProjectMember, TrainingJob, TrainingMetric, User, WorkerNode
from app.schemas.training import PRIORITY_RANK
from app.services import platform_settings
from app.services.serializers import job_out

WORKER_ONLINE_SECONDS = 15
DAY_LABELS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _tone(ratio: float) -> str:
    return "ok" if ratio < 0.7 else "warning" if ratio < 0.9 else "danger"


def _storage_gb() -> float:
    total = sum(path.stat().st_size for path in settings.data_dir.rglob("*") if path.is_file())
    return round(total / 1024**3, 3)


def health(db: Session) -> dict:
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        db_status = "HEALTHY"
    except Exception:  # noqa: BLE001 — la salud informa, no propaga
        db_status = "DOWN"
    latency = round((time.perf_counter() - started) * 1000)

    cutoff = utcnow() - timedelta(seconds=WORKER_ONLINE_SECONDS)
    online = db.scalar(
        select(func.count())
        .select_from(WorkerNode)
        .where(WorkerNode.last_seen_at >= cutoff, WorkerNode.status != "OFFLINE")
    ) or 0
    queued = db.scalar(select(func.count()).select_from(TrainingJob).where(TrainingJob.status == sm.QUEUED)) or 0
    running = db.scalar(
        select(func.count()).select_from(TrainingJob).where(TrainingJob.status.in_([sm.PREPARING, sm.RUNNING]))
    ) or 0
    storage = _storage_gb()
    expected = max(settings.workers_expected, online)
    limits = platform_settings.limits(db)

    meters = [
        ("workers", "Workers en línea", online, expected, "wkr."),
        ("running", "Entrenamientos en curso", running, expected, "trab."),
        ("queue", "Cola de trabajos", queued, limits["projectConcurrency"], "trab."),
        ("storage", "Almacén de artefactos", storage, limits["storage"], "GB"),
    ]
    return {
        "apiStatus": "HEALTHY" if db_status == "HEALTHY" else "DEGRADED",
        "apiLatencyMs": latency,
        "workersOnline": online,
        "workersExpected": expected,
        "queueDepth": queued,
        "databaseStatus": db_status,
        "storageUsedGb": storage,
        "storageLimitGb": limits["storage"],
        "meters": [
            {"id": id_, "label": label, "used": used, "limit": limit, "unit": unit,
             "tone": _tone(used / limit if limit else 1.0)}
            for id_, label, used, limit, unit in meters
        ],
    }


def snapshot(db: Session, user: User) -> dict:
    projects_q = select(Project)
    if user.role != "admin":
        projects_q = projects_q.join(ProjectMember).where(ProjectMember.user_id == user.id)
    projects = list(db.scalars(projects_q))
    project_ids = [p.id for p in projects]

    jobs = list(
        db.scalars(select(TrainingJob).where(TrainingJob.project_id.in_(project_ids)).order_by(TrainingJob.queued_at.desc()))
    )
    serialized = [job_out(db, job).model_dump(mode="json", by_alias=True) for job in jobs]
    active = [j for j in serialized if j["status"] in (sm.PREPARING, sm.RUNNING)]
    queued = sorted(
        (j for j in serialized if j["status"] == sm.QUEUED), key=lambda j: (PRIORITY_RANK[j["priority"]], j["queuedAt"])
    )
    recent = [j for j in serialized if j["status"] in sm.TERMINAL][:10]

    now = utcnow()
    days = [(now - timedelta(days=13 - i)).date() for i in range(14)]
    jobs_per_day = {day: 0 for day in days}
    for job in jobs:
        day = job.queued_at.date()
        if day in jobs_per_day:
            jobs_per_day[day] += 1
    epochs_per_day = {day: 0 for day in days}
    rows = db.execute(
        select(TrainingMetric.recorded_at)
        .join(TrainingJob, TrainingJob.id == TrainingMetric.job_id)
        .where(TrainingJob.project_id.in_(project_ids), TrainingMetric.metric_name == "loss")
    )
    for (recorded_at,) in rows:
        if recorded_at.date() in epochs_per_day:
            epochs_per_day[recorded_at.date()] += 1
    activity = [
        {"day": DAY_LABELS[day.weekday()] if index % 2 == 0 else "", "jobs": jobs_per_day[day], "epochs": epochs_per_day[day]}
        for index, day in enumerate(days)
    ]

    models = list(db.scalars(select(ModelVersion).where(ModelVersion.project_id.in_(project_ids))))
    approved = [m for m in models if m.status == "APPROVED"]
    completed = [j for j in serialized if j["status"] == sm.COMPLETED]
    best = max(completed, key=lambda j: j["valAccuracy"], default=None)
    last7 = sum(jobs_per_day[d] for d in days[7:])
    prev7 = sum(jobs_per_day[d] for d in days[:7])
    health_data = health(db)

    kpis = [
        {
            "id": "projects", "label": "Proyectos activos", "accent": "indigo", "icon": "projects",
            "value": sum(1 for p in projects if p.status == "ACTIVE"),
            "trend": {"direction": "flat", "value": f"{len(projects)} accesibles"},
            "footnote": f"{len(projects)} en total · {len({p.family for p in projects})} familias de red",
            "spark": [len(projects)] * 14,
        },
        {
            "id": "runs", "label": "Entrenamientos en ejecución", "accent": "violet", "icon": "training",
            "value": len(active),
            "trend": {"direction": "up" if last7 > prev7 else "down" if last7 < prev7 else "flat",
                      "value": f"{last7} esta semana"},
            "footnote": f"{health_data['workersOnline']}/{health_data['workersExpected']} workers disponibles",
            "spark": [jobs_per_day[d] for d in days],
        },
        {
            "id": "models", "label": "Modelos aprobados", "accent": "emerald", "icon": "model",
            "value": len(approved),
            "trend": {"direction": "flat", "value": f"{len(models)} versiones"},
            "footnote": "Versiones inmutables trazables (RN-04)",
            "spark": [sum(1 for m in models if m.created_at.date() <= d) for d in days],
        },
        {
            "id": "accuracy", "label": "Mejor accuracy validada", "accent": "amber", "icon": "metrics",
            "value": round(best["valAccuracy"] * 100, 2) if best else 0, "decimals": 2, "unit": "%",
            "trend": {"direction": "flat", "value": f"{len(completed)} trabajos completados"},
            "footnote": f"{best['id']} · {best['architectureName']}" if best else "Aún no hay entrenamientos completados",
            "spark": [round(j["valAccuracy"] * 100, 2) for j in reversed(completed[:14])] or [0],
        },
    ]

    alerts = []
    for job in serialized:
        if job["status"] == sm.FAILED and job["endedAt"] and now - datetime.fromisoformat(job["endedAt"]) < timedelta(days=3):
            alerts.append({
                "severity": "high", "title": f"{job['id']} falló",
                "description": job["statusReason"] or "Error de entrenamiento.",
                "createdAt": job["endedAt"], "module": "M06 · Entrenamientos",
            })
    if queued and health_data["workersOnline"] == 0:
        alerts.append({
            "severity": "high", "title": "No hay workers en línea",
            "description": f"{len(queued)} trabajos esperan en cola. Inicia el worker de entrenamiento.",
            "createdAt": now.isoformat(), "module": "M10 · Salud del sistema",
        })
    pending = [m for m in models if m.status in ("DRAFT", "REVIEWED")]
    if pending:
        alerts.append({
            "severity": "medium", "title": f"{len(pending)} versiones pendientes de revisión",
            "description": "Revisa y aprueba o retira los modelos nuevos.",
            "createdAt": max(m.created_at for m in pending).isoformat(), "module": "M08 · Registro de modelos",
        })
    for index, alert in enumerate(alerts, start=1):
        alert["id"] = f"ALR-{index}"

    last_activity = {}
    for job in jobs:
        last_activity.setdefault(job.project_id, job.queued_at)
    top_projects = sorted(projects, key=lambda p: last_activity.get(p.id, p.updated_at), reverse=True)[:4]

    return {
        "generatedAt": now.isoformat(),
        "kpis": kpis,
        "activeJobs": active,
        "queuedJobs": queued,
        "recentJobs": recent,
        "topProjects": [
            {
                "id": p.id, "name": p.name, "description": p.description, "family": p.family, "status": p.status,
                "members": len(p.members),
                "lastActivityAt": max(last_activity.get(p.id, p.updated_at), p.updated_at).isoformat(),
            }
            for p in top_projects
        ],
        "alerts": alerts[:6],
        "health": health_data,
        "activity": activity,
    }
