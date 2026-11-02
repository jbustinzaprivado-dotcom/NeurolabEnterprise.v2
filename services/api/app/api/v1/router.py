from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    architectures,
    audit,
    auth,
    datasets,
    evaluation,
    models,
    projects,
    system,
    training,
)

api_router = APIRouter()
for module in (system, auth, projects, architectures, datasets, training, evaluation, models, audit, admin):
    api_router.include_router(module.router)
