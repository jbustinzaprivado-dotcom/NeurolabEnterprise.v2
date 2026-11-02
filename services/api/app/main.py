"""Punto de entrada de la API FastAPI.

    venv\\Scripts\\python.exe services\\api\\app\\main.py     (lo usa run.bat)
    Documentación interactiva: http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import sys
import time
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
from app.core.rate_limit import limit_cache, limiter
from app.core.security import decode_token
from app.services import audit, platform_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("neurolab.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.check_runtime()
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


def _current_rate_limit() -> int:
    """Peticiones por minuto vigentes (M10); se relee como mucho cada 30 s."""
    now = time.monotonic()
    if now - limit_cache["read_at"] > 30:
        with SessionLocal() as db:
            limit_cache["value"] = platform_settings.limit(db, "rate")
        limit_cache["read_at"] = now
    return int(limit_cache["value"])


@app.middleware("http")
async def enforce_rate_limit(request: Request, call_next):
    """Límites de tasa (§11): por usuario en toda la API y por IP en el inicio de sesión.

    El canal SSE y la sonda de salud quedan fuera: son conexiones largas o de infraestructura.
    """
    path = request.url.path
    if not path.startswith(settings.api_prefix) or path.endswith(("/events", "/health")):
        return await call_next(request)

    ip = request.client.host if request.client else "?"
    if path.endswith(("/auth/login", "/auth/dev-login")):
        key, limit = f"login:{ip}", settings.login_attempts_per_minute
    else:
        header = request.headers.get("Authorization", "")
        subject = decode_token(header[7:].strip()) if header.lower().startswith("bearer ") else None
        key, limit = f"user:{subject or 'ip:' + ip}", _current_rate_limit()

    wait = limiter.check(key, limit)
    if wait:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Demasiadas solicitudes: el límite es {limit} por minuto. Reintenta en {wait} s."},
            headers={"Retry-After": str(wait)},
        )
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    """Mensaje controlado hacia el cliente; la traza completa solo en el log del servidor."""
    logger.exception("Error no controlado", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Error interno. El incidente quedó registrado."})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
