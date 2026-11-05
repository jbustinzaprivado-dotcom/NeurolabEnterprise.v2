"""Preprocesamiento con scikit-learn: imputación, escalado y codificación.

El preprocesador se ajusta solo con la partición de entrenamiento (sin fuga de
datos) y se guarda junto al modelo para reproducir la inferencia.

Redes recurrentes y convolucionales leen la misma tabla CSV, una fila por ejemplo:
- RNN: columnas ordenadas por instante (t00_var1, t00_var2, t01_var1, …) que se
  reacomodan en (pasos, variables por paso).
- CNN: píxeles en orden de fila (p000, p001, …) que se reacomodan en
  (alto, ancho, canales).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from pandas.api import types as ptypes
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, OneHotEncoder, StandardScaler

from app.modules.datasets import MAX_CATEGORIES


@dataclass
class PreparedData:
    x_train: np.ndarray
    y_train: np.ndarray
    x_val: np.ndarray
    y_val: np.ndarray
    x_test: np.ndarray
    y_test: np.ndarray
    preprocessor: ColumnTransformer
    label_encoder: LabelEncoder | None
    feature_names: list[str]
    input_columns: list[str]
    classes: list[str]
    dropped: list[str] = field(default_factory=list)

    @property
    def input_dim(self) -> int:
        return self.x_train.shape[1]

    @property
    def input_shape(self) -> tuple[int, ...]:
        return tuple(int(size) for size in self.x_train.shape[1:])


def input_shape_for(config: dict) -> tuple[int, ...] | None:
    """Forma de cada ejemplo según la entrada declarada; None para redes densas."""
    spec = config.get("input", {})
    if config.get("family") == "RNN":
        return (int(spec["timesteps"]), int(spec["seqFeatures"]))
    if config.get("family") == "CNN":
        return (int(spec["height"]), int(spec["width"]), int(spec["channels"]))
    return None


def describe_shape(shape: tuple[int, ...]) -> str:
    if len(shape) == 2:
        return f"secuencias de {shape[0]} pasos × {shape[1]} variables"
    return f"imágenes de {shape[0]}×{shape[1]} con {shape[2]} canal(es)"


def _as_text(series: pd.Series) -> pd.Series:
    return series.map(lambda value: np.nan if pd.isna(value) else str(value)).astype(object)


def _split(x: pd.DataFrame, y: np.ndarray, size: float, seed: int, stratify: bool):
    try:
        return train_test_split(x, y, test_size=size, random_state=seed, stratify=y if stratify else None)
    except ValueError:
        # Alguna clase tiene muy pocas filas para estratificar: se reparte al azar.
        return train_test_split(x, y, test_size=size, random_state=seed)


def _shaped_features(features: pd.DataFrame, shape: tuple[int, ...]) -> list[str]:
    """Para RNN/CNN todas las columnas cuentan, en su orden, y deben ser numéricas."""
    expected = int(np.prod(shape))
    if features.shape[1] != expected:
        raise ValueError(
            f"La entrada espera {describe_shape(shape)} = {expected} columnas numéricas además del objetivo; "
            f"el dataset tiene {features.shape[1]}."
        )
    text = [c for c in features.columns if not ptypes.is_numeric_dtype(features[c]) or ptypes.is_bool_dtype(features[c])]
    if text:
        raise ValueError(f"Para {describe_shape(shape)} todas las columnas deben ser numéricas; no lo son: "
                         f"{', '.join(text[:5])}{'…' if len(text) > 5 else ''}.")
    empty = [c for c in features.columns if features[c].isna().all()]
    if empty:
        raise ValueError(f"Columnas sin ningún valor: {', '.join(empty[:5])}.")
    return list(features.columns)


def prepare(
    df: pd.DataFrame, target: str, task: str, split: dict[str, float], seed: int,
    shape: tuple[int, ...] | None = None,
) -> PreparedData:
    df = df.copy()
    df.columns = [str(column).strip() for column in df.columns]
    df = df.dropna(subset=[target])
    if len(df) < 10:
        raise ValueError("Quedan menos de 10 filas con objetivo definido.")

    features = df.drop(columns=[target])
    numeric: list[str] = []
    categorical: list[str] = []
    dropped: list[str] = []
    if shape:
        numeric = _shaped_features(features, shape)
    else:
        dropped = [c for c in features.columns if features[c].isna().all()]
    for column in ([] if shape else features.columns):
        if column in dropped:
            continue
        series = features[column]
        if ptypes.is_numeric_dtype(series) and not ptypes.is_bool_dtype(series):
            numeric.append(column)
        elif series.nunique(dropna=True) <= MAX_CATEGORIES:
            categorical.append(column)
        else:
            dropped.append(column)
    if not numeric and not categorical:
        raise ValueError("No quedan columnas útiles como características.")

    x = features[numeric + categorical].copy()
    for column in categorical:
        x[column] = _as_text(x[column])

    label_encoder = None
    classes: list[str] = []
    if task == "classification":
        label_encoder = LabelEncoder()
        y = label_encoder.fit_transform(_as_text(df[target])).astype("int64")
        classes = [str(c) for c in label_encoder.classes_]
    else:
        y = pd.to_numeric(df[target], errors="raise").to_numpy(dtype="float32")

    stratify = task == "classification"
    x_rest, x_test, y_rest, y_test = _split(x, y, split["test"], seed, stratify)
    val_share = split["validation"] / (split["train"] + split["validation"])
    x_train, x_val, y_train, y_val = _split(x_rest, y_rest, val_share, seed, stratify)

    preprocessor = ColumnTransformer(
        [
            ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric),
            (
                "cat",
                Pipeline([
                    ("impute", SimpleImputer(strategy="most_frequent")),
                    ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                ]),
                categorical,
            ),
        ]
    )
    def shaped(values: np.ndarray) -> np.ndarray:
        values = values.astype("float32")
        return values.reshape((len(values), *shape)) if shape else values

    return PreparedData(
        x_train=shaped(preprocessor.fit_transform(x_train)),
        y_train=y_train,
        x_val=shaped(preprocessor.transform(x_val)),
        y_val=y_val,
        x_test=shaped(preprocessor.transform(x_test)),
        y_test=y_test,
        preprocessor=preprocessor,
        label_encoder=label_encoder,
        feature_names=[str(name) for name in preprocessor.get_feature_names_out()],
        input_columns=numeric + categorical,
        classes=classes,
        dropped=dropped,
    )
