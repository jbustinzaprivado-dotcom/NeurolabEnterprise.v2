"""Métricas Prometheus (§5 Operación) en `GET /metrics`.

Peticiones y latencia por ruta (plantilla, no URL concreta, para no disparar la
cardinalidad) y, en cada lectura, el estado de la cola y de los workers leído de
la base. Solo números agregados: nunca identificadores de usuarios ni datos.
"""

from __future__ import annotations

from datetime import timedelta

from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select

from app.core.database import SessionLocal, utcnow

registry = CollectorRegistry()

http_requests = Counter(
    "neurolab_http_requests_total", "Peticiones HTTP atendidas por la API.",
    ["method", "route", "status"], registry=registry,
)
http_latency = Histogram(
    "neurolab_http_request_duration_seconds", "Latencia de las peticiones HTTP.",
    ["method", "route"], registry=registry,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
rate_limited = Counter(
    "neurolab_rate_limited_total", "Peticiones rechazadas por límite de tasa (§11).",
    ["scope"], registry=registry,
)


class PlatformCollector:
    """Estado de la plataforma calculado al momento de cada lectura."""

    def collect(self):
        from app.repositories.models import ModelVersion, TrainingJob, WorkerNode

        jobs = GaugeMetricFamily("neurolab_training_jobs", "Entrenamientos por estado.", labels=["status"])
        models = GaugeMetricFamily("neurolab_model_versions", "Versiones de modelo por estado.", labels=["status"])
        workers = GaugeMetricFamily("neurolab_workers_online", "Workers con latido en los últimos 15 s.")
        with SessionLocal() as db:
            for status, count in db.execute(select(TrainingJob.status, func.count()).group_by(TrainingJob.status)):
                jobs.add_metric([status], count)
            for status, count in db.execute(select(ModelVersion.status, func.count()).group_by(ModelVersion.status)):
                models.add_metric([status], count)
            cutoff = utcnow() - timedelta(seconds=15)
            workers.add_metric([], db.scalar(
                select(func.count()).select_from(WorkerNode)
                .where(WorkerNode.last_seen_at >= cutoff, WorkerNode.status != "OFFLINE")
            ) or 0)
        yield jobs
        yield models
        yield workers


registry.register(PlatformCollector())
