"""Configuración central (§5 Operación: variables de entorno, separación dev/test/prod).

Todo valor dependiente del entorno se lee de variables `NEUROLAB_*` o de un
archivo `.env` en la raíz del repositorio. Los secretos nunca llegan al bundle
de React (§11).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[4]
API_DIR = ROOT_DIR / "services" / "api"

DEV_SECRET = "dev-only-secret-change-me"


def _load_dotenv(path: Path) -> None:
    """Carga `.env` sin dependencias externas; las variables ya definidas prevalecen."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT_DIR / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(f"NEUROLAB_{name}", default)


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").lower() in {"1", "true", "yes", "si", "sí"}


def _env_list(name: str, default: str) -> list[str]:
    return [item.strip() for item in _env(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: _env("ENV", "development"))
    project_name: str = "NeuroLab Enterprise API"
    code_version: str = "1.0.0"
    api_prefix: str = "/api/v1"

    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(ROOT_DIR / "data"))))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", ""))

    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", ""))
    token_ttl_minutes: int = field(default_factory=lambda: int(_env("TOKEN_TTL_MINUTES", "480")))
    # Solo desarrollo: sin cabecera Authorization se actúa como el usuario demo.
    auth_dev_bypass: bool = field(default_factory=lambda: _env_bool("AUTH_DEV_BYPASS", _env("ENV", "development") == "development"))
    dev_user_id: str = field(default_factory=lambda: _env("DEV_USER_ID", "USR-207"))
    demo_password: str = field(default_factory=lambda: _env("DEMO_PASSWORD", "neurolab2026"))
    seed_demo: bool = field(default_factory=lambda: _env_bool("SEED_DEMO", _env("ENV", "development") != "production"))

    cors_origins: list[str] = field(default_factory=lambda: _env_list("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"))

    # Límites configurables (§10, §11).
    max_upload_mb: int = field(default_factory=lambda: int(_env("MAX_UPLOAD_MB", "50")))
    min_dataset_rows: int = field(default_factory=lambda: int(_env("MIN_DATASET_ROWS", "10")))
    max_epochs: int = field(default_factory=lambda: int(_env("MAX_EPOCHS", "500")))
    max_batch_size: int = field(default_factory=lambda: int(_env("MAX_BATCH_SIZE", "1024")))
    max_params: int = field(default_factory=lambda: int(_env("MAX_PARAMS", "50000000")))
    max_active_jobs_per_user: int = field(default_factory=lambda: int(_env("MAX_ACTIVE_JOBS_PER_USER", "3")))
    max_active_jobs_per_project: int = field(default_factory=lambda: int(_env("MAX_ACTIVE_JOBS_PER_PROJECT", "4")))
    max_job_seconds: int = field(default_factory=lambda: int(_env("MAX_JOB_SECONDS", "1800")))
    storage_limit_gb: float = field(default_factory=lambda: float(_env("STORAGE_LIMIT_GB", "20")))
    # §18: RNN, CNN y GAN se habilitan progresivamente para entrenamiento.
    training_families: list[str] = field(default_factory=lambda: _env_list("TRAINING_FAMILIES", "FEEDFORWARD"))

    worker_poll_seconds: float = field(default_factory=lambda: float(_env("WORKER_POLL_SECONDS", "1.0")))
    worker_stale_seconds: int = field(default_factory=lambda: int(_env("WORKER_STALE_SECONDS", "120")))
    workers_expected: int = field(default_factory=lambda: int(_env("WORKERS_EXPECTED", "1")))

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def resolved_database_url(self) -> str:
        """PostgreSQL (§5); las credenciales viven en `.env`, nunca en el código (§11)."""
        if not self.database_url:
            raise RuntimeError(
                "Falta NEUROLAB_DATABASE_URL. Crea la base con infra/postgres/crear_base.sql y copia "
                ".env.example como .env (ver services/api/README.md)."
            )
        return self.database_url

    @property
    def resolved_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        if self.env == "production":
            raise RuntimeError("NEUROLAB_SECRET_KEY es obligatoria en producción.")
        return DEV_SECRET

    def ensure_dirs(self) -> None:
        for path in (self.uploads_dir, self.models_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
