"""Punto de entrada de la API FastAPI.

    venv\\Scripts\\python.exe services\\api\\app\\main.py     (lo usa run.bat)
    Documentación interactiva: http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import SessionLocal, migrate
from app.services import audit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("neurolab.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrate()
    if settings.seed_demo:
        from app.seed import seed

        with SessionLocal() as db:
            if seed(db):
                logger.info("Base vacía: se cargaron los datos demo.")
    if settings.auth_dev_bypass:
        logger.warning("Modo desarrollo: las peticiones sin token actúan como %s.", settings.dev_user_id)
    yield


app = FastAPI(
    title=settings.project_name,
    version=settings.code_version,
    description="API de NeuroLab Enterprise: proyectos, arquitecturas, datasets, entrenamientos y modelos.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_prefix)


@app.middleware("http")
async def remember_client_ip(request: Request, call_next):
    """La auditoría registra desde qué dirección se hizo cada acción (§11)."""
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    token = audit.client_ip.set(forwarded or (request.client.host if request.client else ""))
    try:
        return await call_next(request)
    finally:
        audit.client_ip.reset(token)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    """Mensaje controlado hacia el cliente; la traza completa solo en el log del servidor."""
    logger.exception("Error no controlado", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Error interno. El incidente quedó registrado."})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
