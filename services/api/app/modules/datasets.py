"""Verificación de datasets CSV (RN-01, §10).

Se valida tipo, tamaño y contenido; el archivo nunca se ejecuta. El esquema
resultante solo guarda estadísticas (tipos, nulos, cardinalidad), nunca valores
de las filas, para no filtrar datos sensibles en logs ni respuestas.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pandas.api import types as ptypes

from app.core.config import settings

# Un objetivo entero con pocos valores distintos se trata como clasificación.
MAX_CLASSES = 50
# Columnas de texto con más categorías que esto se descartan (identificadores, nombres).
MAX_CATEGORIES = 50


class DatasetRejected(ValueError):
    """El archivo no puede registrarse: no es un CSV válido o incumple límites."""


@dataclass
class CsvReport:
    rows: int
    columns: int
    schema: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


def read_csv_bytes(content: bytes) -> pd.DataFrame:
    if not content.strip():
        raise DatasetRejected("El archivo está vacío.")
    if b"\x00" in content[:8192]:
        raise DatasetRejected("El archivo parece binario; se espera texto CSV.")
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            sample = content[:65536].decode(encoding, errors="ignore")
            try:
                sep = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                sep = ","
            return pd.read_csv(io.BytesIO(content), encoding=encoding, sep=sep)
        except UnicodeDecodeError:
            continue
        except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
            raise DatasetRejected(f"No se pudo interpretar el CSV: {exc}") from exc
    raise DatasetRejected("Codificación no soportada; guarda el archivo como UTF-8.")


def column_kind(series: pd.Series) -> str:
    if ptypes.is_bool_dtype(series):
        return "boolean"
    if ptypes.is_numeric_dtype(series):
        return "integer" if ptypes.is_integer_dtype(series) else "float"
    return "categorical"


def inspect_csv(content: bytes, max_upload_mb: float | None = None) -> CsvReport:
    max_mb = max_upload_mb or settings.max_upload_mb
    if len(content) > max_mb * 1024 * 1024:
        raise DatasetRejected(f"El archivo supera el límite de {max_mb:g} MB.")

    df = read_csv_bytes(content)
    headers = [str(column).strip() for column in df.columns]
    if len(headers) < 2:
        raise DatasetRejected("El CSV necesita al menos dos columnas (características y objetivo).")
    if any(not h or h.lower().startswith("unnamed") for h in headers):
        raise DatasetRejected("Todas las columnas necesitan un encabezado explícito.")
    if all(_looks_numeric(h) for h in headers):
        raise DatasetRejected("La primera fila parece datos, no encabezados.")
    # pandas renombra los duplicados como «col.1», «col.2»...
    renamed = {h for h in headers if re.fullmatch(r".+\.\d+", h) and h.rsplit(".", 1)[0] in headers}
    if renamed or len(set(headers)) != len(headers):
        raise DatasetRejected("Hay encabezados duplicados.")
    if len(df) < settings.min_dataset_rows:
        raise DatasetRejected(f"El CSV tiene {len(df)} filas; el mínimo es {settings.min_dataset_rows}.")

    df.columns = headers
    warnings: list[str] = []
    schema = []
    for name in headers:
        series = df[name]
        nulls = int(series.isna().sum())
        kind = column_kind(series)
        unique = int(series.nunique(dropna=True))
        schema.append({"name": name, "kind": kind, "nulls": nulls, "unique": unique})
        if nulls == len(df):
            warnings.append(f"La columna «{name}» está vacía y se ignorará al entrenar.")
        elif nulls / len(df) > 0.3:
            warnings.append(f"La columna «{name}» tiene {nulls / len(df):.0%} de valores nulos; se imputarán.")
        if kind == "categorical" and unique > MAX_CATEGORIES:
            warnings.append(f"La columna «{name}» tiene {unique} categorías; se descartará como característica.")

    return CsvReport(rows=len(df), columns=len(headers), schema=schema, warnings=warnings)


def _looks_numeric(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def target_profile(schema: list[dict[str, Any]], target: str) -> dict[str, Any]:
    """Tipo de problema y número de clases según el esquema verificado."""
    column = next((col for col in schema if col["name"] == target), None)
    if column is None:
        raise ValueError(f"La columna objetivo «{target}» no existe en el dataset.")
    if column["kind"] == "float" or (column["kind"] == "integer" and column["unique"] > MAX_CLASSES):
        return {"task": "regression", "classes": 0}
    if column["unique"] < 2:
        raise ValueError(f"La columna objetivo «{target}» tiene un solo valor; no hay nada que aprender.")
    if column["unique"] > MAX_CLASSES:
        raise ValueError(f"La columna objetivo «{target}» tiene {column['unique']} clases; el máximo es {MAX_CLASSES}.")
    return {"task": "classification", "classes": column["unique"]}


def expected_head(profile: dict[str, Any]) -> str:
    if profile["task"] == "regression":
        return "Dense de 1 unidad con activación linear"
    if profile["classes"] == 2:
        return "Dense de 1 unidad con sigmoid (o 2 unidades con softmax)"
    return f"Dense de {profile['classes']} unidades con softmax"


def head_matches(profile: dict[str, Any], units: int | None, activation: str | None) -> bool:
    activation = activation or "linear"
    if profile["task"] == "regression":
        return units == 1 and activation == "linear"
    if profile["classes"] == 2 and units == 1:
        return activation == "sigmoid"
    return units == profile["classes"] and activation == "softmax"
