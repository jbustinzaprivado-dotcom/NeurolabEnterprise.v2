"""Contratos del M04, espejo de `features/architectures/model.ts`."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import CamelModel

NetworkFamily = Literal["FEEDFORWARD", "RNN", "CNN", "GAN"]
Activation = Literal["relu", "tanh", "sigmoid", "softmax", "linear", "gelu"]
LayerType = Literal["Dense", "Dropout", "BatchNormalization", "Conv2D", "MaxPooling2D", "Flatten", "LSTM", "GRU"]


class LayerConfig(CamelModel):
    id: str = ""
    type: LayerType
    units: int | None = None
    filters: int | None = None
    kernel_size: int | None = None
    pool_size: int | None = None
    dropout: float | None = None
    activation: Activation | None = None


class InputConfig(CamelModel):
    features: int = 4
    timesteps: int = 50
    seq_features: int = 16
    height: int = 64
    width: int = 64
    channels: int = 3
    latent: int = 100


class ArchitectureIn(CamelModel):
    name: str = Field(min_length=2, max_length=120)
    family: NetworkFamily
    justification: str = Field(default="", max_length=2000)
    input: InputConfig = Field(default_factory=InputConfig)
    layers: list[LayerConfig] = Field(max_length=64)
    # Conexiones dibujadas en el lienzo: se conservan para la vista, no afectan al modelo.
    connections: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class ArchitectureIssue(CamelModel):
    severity: Literal["error", "warning", "info"]
    message: str
    layer_index: int | None = None


class LayerResult(CamelModel):
    index: int
    type: LayerType
    input_shape: list[int]
    output_shape: list[int]
    params: int


class ArchitectureSummary(CamelModel):
    valid: bool
    input_shape: list[int]
    output_shape: list[int]
    total_params: int
    layers: list[LayerResult]
    issues: list[ArchitectureIssue]


class ArchitectureOut(CamelModel):
    id: str
    project_id: str
    name: str
    family: NetworkFamily
    version: int
    justification: str
    config: dict[str, Any]
    summary: ArchitectureSummary
    trainable: bool
    created_by: str
    created_at: datetime
