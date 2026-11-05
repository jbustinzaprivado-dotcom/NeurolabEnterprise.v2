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
    # Con proveedor de identidad (oidc) queda apagado salvo que se pida, y entonces no arranca.
    auth_dev_bypass: bool = field(default_factory=lambda: _env_bool(
        "AUTH_DEV_BYPASS", _env("ENV", "development") == "development" and _env("AUTH_PROVIDER", "local") == "local"))
    dev_user_id: str = field(default_factory=lambda: _env("DEV_USER_ID", "USR-207"))
    demo_password: str = field(default_factory=lambda: _env("DEMO_PASSWORD", "neurolab2026"))
    seed_demo: bool = field(default_factory=lambda: _env_bool("SEED_DEMO", _env("ENV", "development") != "production"))
    # Historial de entrenamientos demo en cola (§17); apagado en pruebas para no alterar la cola.
    seed_history: bool = field(default_factory=lambda: _env_bool("SEED_HISTORY", _env("ENV", "development") == "development"))

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
    # Recursos por entrenamiento (§10): valores iniciales; luego se editan en M10.
    max_job_cpu_threads: int = field(default_factory=lambda: int(_env("MAX_JOB_CPU_THREADS", "4")))
    max_job_memory_mb: int = field(default_factory=lambda: int(_env("MAX_JOB_MEMORY_MB", "4096")))
    max_job_gpus: int = field(default_factory=lambda: int(_env("MAX_JOB_GPUS", "0")))
    # Almacenamiento de objetos (§5): "s3" (MinIO/AWS) o "local" (carpeta data/, desarrollo).
    storage_backend: str = field(default_factory=lambda: _env("STORAGE_BACKEND", "local"))
    s3_endpoint: str = field(default_factory=lambda: _env("S3_ENDPOINT", ""))
    s3_bucket: str = field(default_factory=lambda: _env("S3_BUCKET", "neurolab"))
    s3_access_key: str = field(default_factory=lambda: _env("S3_ACCESS_KEY", ""))
    s3_secret_key: str = field(default_factory=lambda: _env("S3_SECRET_KEY", ""))
    s3_region: str = field(default_factory=lambda: _env("S3_REGION", "us-east-1"))
    # Operación (§5): logs JSON por defecto; "text" para leerlos cómodamente en consola.
    log_format: str = field(default_factory=lambda: _env("LOG_FORMAT", "json"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    metrics_remote: bool = field(default_factory=lambda: _env_bool("METRICS_REMOTE", False))
    # En contenedores la API escucha en 0.0.0.0; en local, solo en la propia máquina.
    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8000")))
    # Proveedor de identidad (§11): "local" (contraseñas propias, desarrollo y pruebas) u "oidc".
    auth_provider: str = field(default_factory=lambda: _env("AUTH_PROVIDER", "local"))
    oidc_issuer: str = field(default_factory=lambda: _env("OIDC_ISSUER", "").rstrip("/"))
    oidc_audience: str = field(default_factory=lambda: _env("OIDC_AUDIENCE", "neurolab-api"))
    oidc_client_id: str = field(default_factory=lambda: _env("OIDC_CLIENT_ID", "neurolab-web"))
    # Dirección desde la que la API alcanza al proveedor si difiere de la pública (p. ej. en Docker).
    oidc_internal_url: str = field(default_factory=lambda: _env("OIDC_INTERNAL_URL", "").rstrip("/"))
    # Esquemas adicionales que la API crea al arrancar para servicios que comparten la base.
    extra_schemas: list[str] = field(default_factory=lambda: _env_list("EXTRA_SCHEMAS", ""))
    # Límites de tasa y bloqueo de cuentas (§11).
    rate_limit_per_minute: int = field(default_factory=lambda: int(_env("RATE_LIMIT_PER_MINUTE", "600")))
    login_attempts_per_minute: int = field(default_factory=lambda: int(_env("LOGIN_ATTEMPTS_PER_MINUTE", "10")))
    max_failed_logins: int = field(default_factory=lambda: int(_env("MAX_FAILED_LOGINS", "5")))
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
                "Falta NEUROLAB_DATABASE_URL. Ejecuta infra/postgres/crear_base.ps1, que la crea "
                "y la deja en .env (ver services/api/README.md)."
            )
        return self.database_url

    @property
    def resolved_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        if self.env == "production":
            raise RuntimeError("NEUROLAB_SECRET_KEY es obligatoria en producción.")
        return DEV_SECRET

    def check_runtime(self) -> None:
        """Se niega a arrancar con configuraciones de desarrollo fuera de desarrollo (§11)."""
        if self.auth_provider not in {"local", "oidc"}:
            raise RuntimeError("NEUROLAB_AUTH_PROVIDER debe ser 'local' u 'oidc'.")
        if self.oidc_enabled and not self.oidc_issuer:
            raise RuntimeError("Falta NEUROLAB_OIDC_ISSUER para el proveedor de identidad.")
        if self.oidc_enabled and self.auth_dev_bypass:
            raise RuntimeError("Con NEUROLAB_AUTH_PROVIDER=oidc no se admite NEUROLAB_AUTH_DEV_BYPASS: la identidad la da el proveedor.")
        if self.env == "production":
            if self.auth_dev_bypass:
                raise RuntimeError("NEUROLAB_AUTH_DEV_BYPASS no puede estar activo en producción.")
            if self.seed_history:
                raise RuntimeError("NEUROLAB_SEED_HISTORY no puede estar activo en producción.")
            self.resolved_secret_key  # noqa: B018  exige NEUROLAB_SECRET_KEY
            if self.storage_backend != "s3":
                raise RuntimeError("En producción los archivos van a un almacén de objetos: NEUROLAB_STORAGE_BACKEND=s3 (§5).")
            if self.auth_provider != "oidc" or not self.oidc_issuer:
                raise RuntimeError("En producción la identidad la gestiona un proveedor externo: NEUROLAB_AUTH_PROVIDER=oidc y NEUROLAB_OIDC_ISSUER (§11).")

    @property
    def oidc_enabled(self) -> bool:
        return self.auth_provider == "oidc"

    def ensure_dirs(self) -> None:
        for path in (self.uploads_dir, self.models_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
