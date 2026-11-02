"""Contratos de M02 (proyectos), M10 (usuarios) y autenticación."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.architecture import NetworkFamily
from app.schemas.common import CamelModel

UserRole = Literal["admin", "owner", "engineer", "reviewer", "reader"]
ProjectStatus = Literal["DRAFT", "ACTIVE", "ARCHIVED"]
ProjectMemberRole = Literal["owner", "engineer", "reviewer", "reader"]


class LoginIn(CamelModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)


class UserOut(CamelModel):
    id: str
    display_name: str
    email: str
    initials: str
    title: str
    role: UserRole
    status: str


class TokenOut(CamelModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: int
    user: UserOut


class ProjectMemberOut(CamelModel):
    user_id: str
    display_name: str
    role: ProjectMemberRole
    added_at: datetime


class ProjectDocumentOut(CamelModel):
    id: str
    title: str
    body: str
    author_id: str
    updated_at: datetime


class DocumentIn(CamelModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=1, max_length=20000)


class ProjectIn(CamelModel):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=4000)
    family: NetworkFamily
    status: ProjectStatus = "DRAFT"
    tags: list[str] = Field(default_factory=list, max_length=12)


class ProjectPatch(CamelModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    family: NetworkFamily | None = None
    status: ProjectStatus | None = None
    tags: list[str] | None = Field(default=None, max_length=12)


class ProjectOut(CamelModel):
    id: str
    name: str
    description: str
    family: NetworkFamily
    status: ProjectStatus
    owner_id: str
    members: list[ProjectMemberOut]
    tags: list[str]
    documents: list[ProjectDocumentOut]
    created_at: datetime
    updated_at: datetime
    # Rol del usuario actual y acciones que la API le permitirá (para la UI).
    my_role: str
    permissions: list[str]


class MemberIn(CamelModel):
    user_id: str
    role: ProjectMemberRole
