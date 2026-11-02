"""RBAC y comprobación de pertenencia a proyecto (§4.2, §11).

Quien no es miembro recibe 404 en lugar de 403: así no puede averiguar que
el recurso existe (protección contra acceso horizontal).
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.repositories.models import Project, ProjectMember, User

ALL_MEMBERS = frozenset({"owner", "engineer", "reviewer", "reader"})

PROJECT_ACTIONS: dict[str, frozenset[str]] = {
    "project.read": ALL_MEMBERS,
    "project.update": frozenset({"owner"}),
    "members.manage": frozenset({"owner"}),
    "docs.write": frozenset({"owner", "engineer"}),
    "architecture.write": frozenset({"owner", "engineer"}),
    "dataset.write": frozenset({"owner", "engineer"}),
    "dataset.delete": frozenset({"owner"}),
    "training.launch": frozenset({"owner", "engineer"}),
    "training.cancel": frozenset({"owner", "engineer"}),
    "model.review": frozenset({"owner", "reviewer"}),
    "model.retire": frozenset({"owner"}),
    "model.download": frozenset({"owner", "engineer", "reviewer"}),
    "audit.read": frozenset({"owner", "reviewer"}),
    "report.export": frozenset({"owner", "engineer", "reviewer"}),
}

# Roles globales que pueden crear proyectos nuevos.
PROJECT_CREATORS = frozenset({"admin", "owner", "engineer"})


def project_role(db: Session, user: User, project_id: str) -> str | None:
    if user.role == "admin":
        return "admin"
    member = db.get(ProjectMember, (project_id, user.id))
    return member.role if member else None


def allowed(role: str | None, action: str) -> bool:
    if role == "admin":
        return True
    return role is not None and role in PROJECT_ACTIONS[action]


def require_project(db: Session, user: User, project_id: str, action: str = "project.read") -> tuple[Project, str]:
    project = db.get(Project, project_id)
    role = project_role(db, user, project_id) if project else None
    if project is None or role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proyecto no encontrado.")
    if not allowed(role, action):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu rol en el proyecto no permite esta acción.")
    return project, role


def permissions_for(role: str | None) -> list[str]:
    return [action for action in PROJECT_ACTIONS if allowed(role, action)]
