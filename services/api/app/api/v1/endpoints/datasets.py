"""M05 · Datasets: carga controlada, verificación de esquema, versiones y borrado seguro."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.core.database import utcnow
from app.modules import state_machine as sm
from app.modules.datasets import DatasetRejected, inspect_csv
from app.modules.permissions import require_project
from app.repositories.models import Dataset, TrainingJob
from app.schemas.dataset import DatasetOut
from app.services import audit, platform_settings
from app.services.serializers import dataset_out

router = APIRouter(tags=["datasets"])

_CHUNK = 1024 * 1024

# Alcance de lectura declarado en el dataset (M05 · permisos).
ACCESS_ROLES = {
    "PROJECT": {"owner", "engineer", "reviewer", "reader", "admin"},
    "ENGINEERS": {"owner", "engineer", "admin"},
    "OWNER": {"owner", "admin"},
}


def can_read(role: str, dataset: Dataset) -> bool:
    return role in ACCESS_ROLES.get(dataset.access, ACCESS_ROLES["PROJECT"])


async def _read_limited(upload: UploadFile, max_mb: float) -> bytes:
    """Lee por bloques y corta en cuanto se supera el límite, sin cargar archivos enormes."""
    limit = max_mb * 1024 * 1024
    chunks, size = [], 0
    while chunk := await upload.read(_CHUNK):
        size += len(chunk)
        if size > limit:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"El archivo supera {max_mb:g} MB.")
        chunks.append(chunk)
    return b"".join(chunks)


def _tags(raw: str) -> list[str]:
    seen: dict[str, str] = {}
    for tag in raw.split(","):
        clean = " ".join(tag.split())
        if clean:
            seen.setdefault(clean.lower(), clean)
    return list(seen.values())[:12]


@router.get("/projects/{project_id}/datasets", response_model=list[DatasetOut])
def list_datasets(project_id: str, user: CurrentUser, db: DB) -> list[DatasetOut]:
    _, role = require_project(db, user, project_id)
    rows = db.scalars(
        select(Dataset)
        .where(Dataset.project_id == project_id, Dataset.status != "DELETED")
        .order_by(Dataset.name, Dataset.version.desc())
    )
    return [dataset_out(row) for row in rows if can_read(role, row)]


@router.post("/projects/{project_id}/datasets", response_model=DatasetOut, status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    project_id: str,
    user: CurrentUser,
    db: DB,
    file: UploadFile = File(...),
    name: str | None = Form(default=None, max_length=120),
    description: str = Form(default="", max_length=2000),
    privacy: str = Form(default="INTERNAL", pattern="^(PUBLIC|INTERNAL|SENSITIVE)$"),
    access: str = Form(default="PROJECT", pattern="^(PROJECT|ENGINEERS|OWNER)$"),
    license: str = Form(default="", max_length=80),
    tags: str = Form(default="", max_length=400),
    train: float = Form(default=0.7),
    validation: float = Form(default=0.15),
    test: float = Form(default=0.15),
) -> DatasetOut:
    """Registra un CSV. Repetir el nombre crea la versión siguiente; nunca se sobrescribe."""
    require_project(db, user, project_id, "dataset.write")

    filename = Path(file.filename or "").name
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Solo se admiten archivos .csv.")
    parts = (train, validation, test)
    if abs(sum(parts) - 1) > 0.001 or min(parts) < 0.05 or max(parts) > 0.9:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "La partición debe sumar 1 y cada parte debe estar entre 0.05 y 0.9.",
        )

    max_mb = platform_settings.limit(db, "upload")
    content = await _read_limited(file, max_mb)
    try:
        report = inspect_csv(content, max_mb)
    except DatasetRejected as exc:
        audit.record(db, user.id, "dataset.reject", "dataset", "-", project_id, filename=filename, reason=str(exc))
        db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    display = (name or Path(filename).stem).strip()
    latest = db.scalar(select(func.max(Dataset.version)).where(Dataset.project_id == project_id, Dataset.name == display))
    dataset = Dataset(
        project_id=project_id,
        name=display,
        version=(latest or 0) + 1,
        description=description.strip(),
        original_filename=filename,
        storage_key="",
        size_bytes=len(content),
        rows=report.rows,
        columns=report.columns,
        checksum=hashlib.sha256(content).hexdigest(),
        privacy=privacy,
        access=access,
        tags=_tags(tags),
        license=license.strip(),
        split={"train": train, "validation": validation, "test": test},
        metadata_json={"schema": report.schema, "warnings": report.warnings},
        created_by=user.id,
    )
    db.add(dataset)
    db.flush()
    dataset.storage_key = f"uploads/{project_id}/{dataset.id}.csv"
    path = settings.data_dir / dataset.storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    audit.record(
        db, user.id, "dataset.upload", "dataset", dataset.id, project_id,
        name=display, version=dataset.version, rows=report.rows, checksum=dataset.checksum,
    )
    db.commit()
    return dataset_out(dataset)


@router.get("/datasets/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, user: CurrentUser, db: DB) -> DatasetOut:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or dataset.status == "DELETED":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset no encontrado.")
    _, role = require_project(db, user, dataset.project_id)
    if not can_read(role, dataset):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset no encontrado.")
    return dataset_out(dataset)


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: str, user: CurrentUser, db: DB) -> Response:
    """Borrado seguro: bloqueado si hay entrenamientos activos; conserva el archivo si hay historial."""
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or dataset.status == "DELETED":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset no encontrado.")
    require_project(db, user, dataset.project_id, "dataset.delete")

    jobs = list(db.scalars(select(TrainingJob.status).where(TrainingJob.dataset_id == dataset_id)))
    if any(job_status in sm.ACTIVE for job_status in jobs):
        raise HTTPException(status.HTTP_409_CONFLICT, "Hay entrenamientos activos que usan este dataset.")

    dataset.status = "DELETED"
    dataset.deleted_at = utcnow()
    if not jobs:
        (settings.data_dir / dataset.storage_key).unlink(missing_ok=True)
    audit.record(
        db, user.id, "dataset.delete", "dataset", dataset.id, dataset.project_id,
        name=dataset.name, version=dataset.version, fileKept=bool(jobs),
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
