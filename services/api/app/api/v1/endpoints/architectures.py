"""M04 · Diseñador de arquitecturas: validación y versiones guardadas."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.modules.architecture import validate_architecture
from app.modules.permissions import require_project
from app.repositories.models import Architecture
from app.schemas.architecture import ArchitectureIn, ArchitectureOut, ArchitectureSummary
from app.services import audit
from app.services.serializers import architecture_out

router = APIRouter(tags=["architectures"])


@router.post("/architectures/validate", response_model=ArchitectureSummary)
def validate(payload: ArchitectureIn, user: CurrentUser) -> ArchitectureSummary:
    """Vista previa del resumen sin guardar nada."""
    return validate_architecture(payload)


@router.get("/projects/{project_id}/architectures", response_model=list[ArchitectureOut])
def list_architectures(project_id: str, user: CurrentUser, db: DB) -> list[ArchitectureOut]:
    require_project(db, user, project_id)
    rows = db.scalars(
        select(Architecture)
        .where(Architecture.project_id == project_id)
        .order_by(Architecture.name, Architecture.version.desc())
    )
    return [architecture_out(arch) for arch in rows]


@router.post("/projects/{project_id}/architectures", response_model=ArchitectureOut, status_code=status.HTTP_201_CREATED)
def create_architecture(project_id: str, payload: ArchitectureIn, user: CurrentUser, db: DB) -> ArchitectureOut:
    """Guarda una arquitectura validada; repetir el nombre crea la versión siguiente."""
    require_project(db, user, project_id, "architecture.write")
    summary = validate_architecture(payload)
    if not summary.valid:
        errors = [issue.message for issue in summary.issues if issue.severity == "error"]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"message": "Arquitectura no válida.", "issues": errors})

    name = payload.name.strip()
    latest = db.scalar(
        select(func.max(Architecture.version)).where(Architecture.project_id == project_id, Architecture.name == name)
    )
    arch = Architecture(
        project_id=project_id,
        name=name,
        family=payload.family,
        version=(latest or 0) + 1,
        justification=payload.justification.strip(),
        config_json=payload.model_dump(mode="json", by_alias=True, exclude={"name", "justification"}),
        summary_json=summary.model_dump(mode="json", by_alias=True),
        created_by=user.id,
    )
    db.add(arch)
    db.flush()
    audit.record(
        db, user.id, "architecture.create", "architecture", arch.id, project_id,
        name=name, version=arch.version, family=arch.family, params=summary.total_params,
    )
    db.commit()
    return architecture_out(arch)


@router.get("/architectures/{architecture_id}", response_model=ArchitectureOut)
def get_architecture(architecture_id: str, user: CurrentUser, db: DB) -> ArchitectureOut:
    arch = db.get(Architecture, architecture_id)
    if arch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arquitectura no encontrada.")
    require_project(db, user, arch.project_id)
    return architecture_out(arch)
