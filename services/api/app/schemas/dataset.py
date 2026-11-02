"""Contratos del M05 · Datasets."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from app.schemas.common import CamelModel


class DatasetSplit(CamelModel):
    train: float
    validation: float
    test: float


class DatasetOut(CamelModel):
    id: str
    project_id: str
    project_name: str
    name: str
    version: int
    description: str
    format: str
    status: Literal["READY", "QUARANTINED", "DELETED"]
    original_filename: str
    size_bytes: int
    rows: int
    columns: int
    checksum: str
    privacy: str
    access: str
    tags: list[str]
    license: str
    split: DatasetSplit
    column_schema: list[dict[str, Any]]
    warnings: list[str]
    created_by: str
    created_by_name: str
    created_at: datetime
