"""M02 · Proyectos de IA: listado, alta, edición y miembros."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import or_, select

from app.api.deps import DB, CurrentUser
from app.core.database import utcnow
from app.modules.permissions import PROJECT_CREATORS, project_role, require_project
from app.repositories.models import Project, ProjectDocument, ProjectMember, User
from app.schemas.project import DocumentIn, MemberIn, ProjectIn, ProjectOut, ProjectPatch
from app.services import audit
from app.services.serializers import project_out

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    user: CurrentUser,
    db: DB,
    q: str | None = Query(default=None, max_length=120),
    status_: str | None = Query(default=None, alias="status"),
    family: str | None = None,
) -> list[ProjectOut]:
    """Solo proyectos accesibles al usuario (§9)."""
    query = select(Project).order_by(Project.updated_at.desc())
    if user.role != "admin":
        query = query.join(ProjectMember).where(ProjectMember.user_id == user.id)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Project.name.ilike(like), Project.description.ilike(like)))
    if status_:
        query = query.where(Project.status == status_)
    if family:
        query = query.where(Project.family == family)
    return [project_out(p, project_role(db, user, p.id) or "reader") for p in db.scalars(query)]


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectIn, user: CurrentUser, db: DB) -> ProjectOut:
    if user.role not in PROJECT_CREATORS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu rol no permite crear proyectos.")
    if len(_clean_tags(payload.tags)) > MAX_TAGS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Un proyecto admite hasta {MAX_TAGS} etiquetas.")
    project = Project(
        name=payload.name.strip(),
        description=payload.description.strip(),
        family=payload.family,
        status=payload.status,
        owner_id=user.id,
        tags=_clean_tags(payload.tags),
    )
    project.members.append(ProjectMember(user_id=user.id, role="owner"))
    db.add(project)
    db.flush()
    audit.record(db, user.id, "project.create", "project", project.id, project.id, name=project.name)
    db.commit()
    db.refresh(project)
    return project_out(project, project_role(db, user, project.id))


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, user: CurrentUser, db: DB) -> ProjectOut:
    project, role = require_project(db, user, project_id)
    return project_out(project, role)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, payload: ProjectPatch, user: CurrentUser, db: DB) -> ProjectOut:
    changes = payload.model_dump(exclude_unset=True)
    # Las etiquetas forman parte de la documentación (M02): owner e ingenieros. El resto de
    # la ficha (nombre, problema, familia, estado) solo la cambia el responsable.
    action = "docs.write" if changes and set(changes) == {"tags"} else "project.update"
    project, role = require_project(db, user, project_id, action)
    if "tags" in changes and len(_clean_tags(changes["tags"])) > MAX_TAGS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Un proyecto admite hasta {MAX_TAGS} etiquetas.")
    for field, value in changes.items():
        if field == "tags":
            value = _clean_tags(value)
        setattr(project, field, value.strip() if isinstance(value, str) else value)
    audit.record(db, user.id, "project.update", "project", project.id, project.id, fields=sorted(changes))
    db.commit()
    db.refresh(project)
    return project_out(project, role)


@router.post("/projects/{project_id}/members", response_model=ProjectOut)
def upsert_member(project_id: str, payload: MemberIn, user: CurrentUser, db: DB) -> ProjectOut:
    project, role = require_project(db, user, project_id, "members.manage")
    target = db.get(User, payload.user_id)
    if target is None or target.status != "ACTIVE":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado.")
    if target.role == "reader" and payload.role in {"owner", "engineer"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Un lector global solo puede ser lector o revisor.")
    member = db.get(ProjectMember, (project_id, target.id))
    previous = member.role if member else None
    if member is None:
        project.members.append(ProjectMember(user_id=target.id, role=payload.role))
    else:
        if previous == "owner" and payload.role != "owner" and _owner_count(project) == 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "El proyecto debe conservar al menos un responsable.")
        member.role = payload.role
    audit.record(db, user.id, "members.change", "user", target.id, project_id, previous=previous, role=payload.role)
    db.commit()
    db.refresh(project)
    return project_out(project, role)


@router.delete("/projects/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(project_id: str, user_id: str, user: CurrentUser, db: DB) -> Response:
    project, _ = require_project(db, user, project_id, "members.manage")
    member = db.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El usuario no es miembro del proyecto.")
    if member.role == "owner" and _owner_count(project) == 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "El proyecto debe conservar al menos un responsable.")
    db.delete(member)
    audit.record(db, user.id, "members.remove", "user", user_id, project_id, previous=member.role)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _owner_count(project: Project) -> int:
    return sum(1 for member in project.members if member.role == "owner")


MAX_TAGS = 8


def _clean_tags(tags: list[str]) -> list[str]:
    """Sin duplicados ignorando mayúsculas; se conserva la primera grafía."""
    seen: dict[str, str] = {}
    for tag in tags:
        clean = " ".join(tag.replace(",", " ").split())
        if clean:
            seen.setdefault(clean.lower(), clean)
    return list(seen.values())


@router.post("/projects/{project_id}/documents", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def add_document(project_id: str, payload: DocumentIn, user: CurrentUser, db: DB) -> ProjectOut:
    project, role = require_project(db, user, project_id, "docs.write")
    document = ProjectDocument(title=payload.title.strip(), body=payload.body.strip(), author_id=user.id)
    project.documents.append(document)
    project.updated_at = utcnow()
    db.flush()
    audit.record(db, user.id, "document.save", "document", document.id, project_id, title=document.title)
    db.commit()
    db.refresh(project)
    return project_out(project, role)


@router.patch("/projects/{project_id}/documents/{document_id}", response_model=ProjectOut)
def update_document(project_id: str, document_id: str, payload: DocumentIn, user: CurrentUser, db: DB) -> ProjectOut:
    project, role = require_project(db, user, project_id, "docs.write")
    document = db.get(ProjectDocument, document_id)
    if document is None or document.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado.")
    document.title, document.body = payload.title.strip(), payload.body.strip()
    project.updated_at = utcnow()
    audit.record(db, user.id, "document.save", "document", document.id, project_id, title=document.title)
    db.commit()
    db.refresh(project)
    return project_out(project, role)


@router.delete("/projects/{project_id}/documents/{document_id}", response_model=ProjectOut)
def delete_document(project_id: str, document_id: str, user: CurrentUser, db: DB) -> ProjectOut:
    project, role = require_project(db, user, project_id, "docs.write")
    document = db.get(ProjectDocument, document_id)
    if document is None or document.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado.")
    project.documents.remove(document)
    project.updated_at = utcnow()
    audit.record(db, user.id, "document.delete", "document", document_id, project_id, title=document.title)
    db.commit()
    db.refresh(project)
    return project_out(project, role)
