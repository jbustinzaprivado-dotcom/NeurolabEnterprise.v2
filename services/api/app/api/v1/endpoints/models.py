"""M08 · Registro de modelos: versiones inmutables, revisión y descarga autorizada."""

from __future__ import annotations

import hashlib
import io
import zipfile

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.storage import get_store
from app.modules.permissions import allowed, require_project
from app.repositories.models import ModelVersion
from app.schemas.training import ModelStatusIn, ModelVersionOut
from app.services import audit
from app.services.serializers import model_out

router = APIRouter(tags=["models"])

HASH_FILE = "HUELLA.txt"


def _hash_note(model: ModelVersion, files: dict[str, bytes]) -> str:
    """Explica qué cubre la huella registrada y cómo comprobarla con el contenido del ZIP.

    La huella del modelo se calcula sobre los artefactos (nombre y contenido de cada archivo, en
    orden alfabético), no sobre el ZIP: el ZIP se arma en cada descarga y su propia huella cambia.
    """
    lines = [
        f"NeuroLab Enterprise · {model.name} v{model.version}",
        "",
        f"Huella registrada (SHA-256): {model.checksum}",
        "",
        "Cubre los archivos del modelo, no el ZIP: se calcula concatenando, en orden alfabético,",
        "el nombre y el contenido de cada archivo. El ZIP se arma en cada descarga, así que su",
        "propia huella cambia; la de su contenido, no.",
        "",
        "Huella de cada archivo (SHA-256):",
        *(f"  {hashlib.sha256(content).hexdigest()}  {name}" for name, content in sorted(files.items())),
        "",
        "Para comprobarla, descomprime el ZIP en una carpeta y ejecuta en ella:",
        "",
        "  python -c \"import hashlib,pathlib; h=hashlib.sha256(); "
        f"[(h.update(p.name.encode()), h.update(p.read_bytes())) for p in sorted(pathlib.Path('.').iterdir()) if p.name != '{HASH_FILE}']; "
        "print(h.hexdigest())\"",
        "",
        "Debe imprimir la huella registrada.",
    ]
    return "\n".join(lines) + "\n"

# Ciclo de revisión: borrador → revisado → aprobado; cualquiera puede retirarse.
MODEL_TRANSITIONS = {
    "DRAFT": {"REVIEWED", "RETIRED"},
    "REVIEWED": {"APPROVED", "RETIRED"},
    "APPROVED": {"RETIRED"},
    "RETIRED": set(),
}


def _load(db, user, model_id: str, action: str = "project.read") -> tuple[ModelVersion, str]:
    model = db.get(ModelVersion, model_id)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modelo no encontrado.")
    _, role = require_project(db, user, model.project_id, action)
    return model, role


@router.get("/projects/{project_id}/models", response_model=list[ModelVersionOut])
def list_models(project_id: str, user: CurrentUser, db: DB) -> list[ModelVersionOut]:
    require_project(db, user, project_id)
    rows = db.scalars(
        select(ModelVersion).where(ModelVersion.project_id == project_id).order_by(ModelVersion.created_at.desc())
    )
    return [model_out(row) for row in rows]


@router.get("/models/{model_id}", response_model=ModelVersionOut)
def get_model(model_id: str, user: CurrentUser, db: DB) -> ModelVersionOut:
    model, _ = _load(db, user, model_id)
    return model_out(model)


@router.post("/models/{model_id}/status", response_model=ModelVersionOut)
def change_status(model_id: str, payload: ModelStatusIn, user: CurrentUser, db: DB) -> ModelVersionOut:
    model, role = _load(db, user, model_id)
    action = "model.retire" if payload.status == "RETIRED" else "model.review"
    if not allowed(role, action):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu rol en el proyecto no permite este cambio de estado.")
    if payload.status not in MODEL_TRANSITIONS[model.status]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"No se puede pasar de {model.status} a {payload.status}.")
    if payload.status == "APPROVED" and model.job.created_by == user.id and role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Quien entrenó el modelo no puede aprobarlo (separación de funciones).")

    previous, model.status = model.status, payload.status
    history = list(model.metadata_json.get("reviewHistory", []))
    history.append({"from": previous, "to": payload.status, "by": user.id, "note": payload.note})
    model.metadata_json = {**model.metadata_json, "reviewHistory": history}
    audit.record(db, user.id, "model.status", "model_version", model.id, model.project_id,
                 previous=previous, status=payload.status, note=payload.note)
    db.commit()
    return model_out(model)


@router.get("/models/{model_id}/download")
def download(model_id: str, user: CurrentUser, db: DB) -> StreamingResponse:
    """Empaqueta pesos `.keras`, preprocesador `.pkl` y metadatos en un ZIP."""
    model, _ = _load(db, user, model_id, "model.download")
    store = get_store()
    keys = store.list(model.storage_key)
    if not keys:
        raise HTTPException(status.HTTP_410_GONE, "Los artefactos del modelo no están disponibles.")

    files = {key.rsplit("/", 1)[-1]: store.get(key) for key in keys}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
        archive.writestr(HASH_FILE, _hash_note(model, files))
    buffer.seek(0)
    audit.record(db, user.id, "model.download", "model_version", model.id, model.project_id, version=model.version)
    db.commit()
    filename = f"{model.name}-v{model.version}.zip".replace(" ", "_")
    return StreamingResponse(
        buffer, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
