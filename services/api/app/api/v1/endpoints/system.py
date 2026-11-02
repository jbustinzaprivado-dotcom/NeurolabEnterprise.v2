"""M01 · Dashboard y salud del sistema (M10)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.services import dashboard

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: DB) -> dict:
    """Sin autenticación para sondas; no expone datos de proyectos."""
    data = dashboard.health(db)
    return {
        "status": data["apiStatus"],
        "database": data["databaseStatus"],
        "workersOnline": data["workersOnline"],
        "queueDepth": data["queueDepth"],
        "version": settings.code_version,
        "trainingFamilies": settings.training_families,
    }


@router.get("/dashboard")
def get_dashboard(user: CurrentUser, db: DB) -> dict:
    return dashboard.snapshot(db, user)
