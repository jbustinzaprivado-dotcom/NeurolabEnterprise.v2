"""Preprocesamiento tabular con scikit-learn: imputación, escalado y codificación.

El preprocesador se ajusta solo con la partición de entrenamiento (sin fuga de
datos) y se guarda junto al modelo para reproducir la inferencia.
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


def _as_text(series: pd.Series) -> pd.Series:
    return series.map(lambda value: np.nan if pd.isna(value) else str(value)).astype(object)


def _split(x: pd.DataFrame, y: np.ndarray, size: float, seed: int, stratify: bool):
    try:
        return train_test_split(x, y, test_size=size, random_state=seed, stratify=y if stratify else None)
    except ValueError:
        # Alguna clase tiene muy pocas filas para estratificar: se reparte al azar.
        return train_test_split(x, y, test_size=size, random_state=seed)


def prepare(df: pd.DataFrame, target: str, task: str, split: dict[str, float], seed: int) -> PreparedData:
    df = df.copy()
    df.columns = [str(column).strip() for column in df.columns]
    df = df.dropna(subset=[target])
    if len(df) < 10:
        raise ValueError("Quedan menos de 10 filas con objetivo definido.")

    features = df.drop(columns=[target])
    dropped = [c for c in features.columns if features[c].isna().all()]
    numeric, categorical = [], []
    for column in features.columns:
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
    x_train_t = preprocessor.fit_transform(x_train).astype("float32")

    return PreparedData(
        x_train=x_train_t,
        y_train=y_train,
        x_val=preprocessor.transform(x_val).astype("float32"),
        y_val=y_val,
        x_test=preprocessor.transform(x_test).astype("float32"),
        y_test=y_test,
        preprocessor=preprocessor,
        label_encoder=label_encoder,
        feature_names=[str(name) for name in preprocessor.get_feature_names_out()],
        input_columns=numeric + categorical,
        classes=classes,
        dropped=dropped,
    )
