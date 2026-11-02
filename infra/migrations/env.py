"""Entorno de Alembic: usa el mismo motor y metadatos que la API."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import context

API_DIR = Path(__file__).resolve().parents[2] / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.core.database import Base, UTCDateTime, engine  # noqa: E402
from app.repositories import models  # noqa: E402,F401  registra las tablas

target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """Las migraciones no dependen del código de la app: UTCDateTime se escribe como DateTime(tz)."""
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_item=render_item,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
