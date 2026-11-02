"""Construcción de modelos Keras desde una configuración ya validada por la API."""

from __future__ import annotations

from typing import Any

import keras

OPTIMIZERS = {
    "adam": keras.optimizers.Adam,
    "adamw": keras.optimizers.AdamW,
    "sgd": keras.optimizers.SGD,
    "rmsprop": keras.optimizers.RMSprop,
}

RECURRENT = {"LSTM", "GRU"}


def _layer(spec: dict[str, Any], return_sequences: bool) -> keras.layers.Layer:
    kind = spec["type"]
    activation = spec.get("activation") or "linear"
    if kind == "Dense":
        return keras.layers.Dense(spec["units"], activation=activation)
    if kind == "Dropout":
        return keras.layers.Dropout(spec["dropout"])
    if kind == "BatchNormalization":
        return keras.layers.BatchNormalization()
    if kind == "Conv2D":
        return keras.layers.Conv2D(spec["filters"], spec["kernelSize"], activation=activation)
    if kind == "MaxPooling2D":
        return keras.layers.MaxPooling2D(spec.get("poolSize") or 2)
    if kind == "Flatten":
        return keras.layers.Flatten()
    if kind == "LSTM":
        return keras.layers.LSTM(spec["units"], activation=activation, return_sequences=return_sequences)
    if kind == "GRU":
        return keras.layers.GRU(spec["units"], activation=activation, return_sequences=return_sequences)
    raise ValueError(f"Capa no soportada: {kind}")


def build_model(
    config: dict[str, Any],
    input_shape: tuple[int, ...],
    task: str,
    optimizer: str,
    learning_rate: float,
) -> keras.Model:
    layers = config["layers"]
    model = keras.Sequential(name=config.get("family", "model").lower())
    model.add(keras.Input(shape=input_shape))
    for index, spec in enumerate(layers):
        follows_recurrent = any(item["type"] in RECURRENT for item in layers[index + 1 :])
        model.add(_layer(spec, return_sequences=follows_recurrent))

    if task == "regression":
        loss, metrics = "mse", ["mae"]
    elif layers[-1]["units"] == 1:
        loss, metrics = "binary_crossentropy", ["accuracy"]
    else:
        loss, metrics = "sparse_categorical_crossentropy", ["accuracy"]

    model.compile(optimizer=OPTIMIZERS[optimizer](learning_rate=learning_rate), loss=loss, metrics=metrics)
    return model
