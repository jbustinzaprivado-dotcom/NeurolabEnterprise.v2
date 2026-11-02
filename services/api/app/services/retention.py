"""Política de retención (§11) con los plazos que fija M10.

- Auditoría: se borran los eventos más antiguos que el plazo.
- Métricas: de los trabajos cerrados hace más del plazo se borran las métricas y los
  logs por época; el trabajo, su resultado final y su evaluación se conservan.
- Artefactos: se borran los archivos de los modelos RETIRADOS más antiguos que el plazo.
  Un modelo aprobado nunca se purga, y su ficha y checksum quedan como trazabilidad.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import utcnow
from app.modules import state_machine as sm
from app.repositories.models import AuditEvent, ModelVersion, TrainingEvent, TrainingJob, TrainingMetric
from app.services import audit, platform_settings


def apply_retention(db: Session, now: datetime | None = None) -> dict[str, int]:
    policy = platform_settings.security(db)
    now = now or utcnow()
    audit_cut = now - timedelta(days=int(policy["auditRetentionDays"]))
    metrics_cut = now - timedelta(days=int(policy["metricsRetentionDays"]))
    artifact_cut = now - timedelta(days=int(policy["artifactRetentionDays"]))

    audit_rows = db.execute(delete(AuditEvent).where(AuditEvent.created_at < audit_cut)).rowcount or 0

    closed = select(TrainingJob.id).where(TrainingJob.status.in_(sm.TERMINAL), TrainingJob.ended_at < metrics_cut)
    metric_rows = db.execute(delete(TrainingMetric).where(TrainingMetric.job_id.in_(closed))).rowcount or 0
    event_rows = db.execute(
        delete(TrainingEvent).where(TrainingEvent.job_id.in_(closed), TrainingEvent.type.in_(["metric", "log"]))
    ).rowcount or 0

    purged = 0
    retired = db.scalars(
        select(ModelVersion).where(ModelVersion.status == "RETIRED", ModelVersion.updated_at < artifact_cut)
    )
    for model in retired:
        if model.metadata_json.get("artifactsPurgedAt"):
            continue
        shutil.rmtree(settings.data_dir / model.storage_key, ignore_errors=True)
        model.metadata_json = {**model.metadata_json, "artifactsPurgedAt": now.isoformat()}
        purged += 1

    counts = {"auditoria": audit_rows, "metricas": metric_rows, "eventos": event_rows, "artefactos": purged}
    if any(counts.values()):
        audit.record(db, "system", "retention.applied", "settings", "retention", **counts)
    db.commit()
    return counts
