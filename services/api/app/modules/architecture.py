"""Validación de arquitecturas en backend (§10: el frontend no es frontera de seguridad).

Calcula formas y parámetros capa a capa con las mismas fórmulas que Keras
(padding `valid`, GRU con `reset_after=True`), de modo que el resumen
coincide con `model.count_params()`.
"""

from __future__ import annotations

from math import prod

from app.core.config import settings
from app.schemas.architecture import ArchitectureIn, ArchitectureIssue, ArchitectureSummary, LayerConfig, LayerResult

FAMILY_LAYERS: dict[str, frozenset[str]] = {
    "FEEDFORWARD": frozenset({"Dense", "Dropout", "BatchNormalization"}),
    "RNN": frozenset({"LSTM", "GRU", "Dense", "Dropout", "BatchNormalization"}),
    "CNN": frozenset({"Conv2D", "MaxPooling2D", "Flatten", "Dense", "Dropout", "BatchNormalization"}),
    "GAN": frozenset({"Dense", "Dropout", "BatchNormalization"}),
}

LIMITS = {
    "units": (1, 4096),
    "filters": (1, 1024),
    "kernel_size": (1, 11),
    "pool_size": (1, 8),
}

RECURRENT = frozenset({"LSTM", "GRU"})


def input_shape_for(arch: ArchitectureIn) -> list[int]:
    cfg = arch.input
    if arch.family == "RNN":
        return [cfg.timesteps, cfg.seq_features]
    if arch.family == "CNN":
        return [cfg.height, cfg.width, cfg.channels]
    if arch.family == "GAN":
        return [cfg.latent]
    return [cfg.features]


def returns_sequences(layers: list[LayerConfig], index: int) -> bool:
    """Una capa recurrente devuelve la secuencia completa si otra recurrente la sigue."""
    return any(layer.type in RECURRENT for layer in layers[index + 1 :])


def validate_architecture(arch: ArchitectureIn) -> ArchitectureSummary:
    issues: list[ArchitectureIssue] = []

    def error(message: str, index: int | None = None) -> None:
        issues.append(ArchitectureIssue(severity="error", message=message, layer_index=index))

    def warning(message: str, index: int | None = None) -> None:
        issues.append(ArchitectureIssue(severity="warning", message=message, layer_index=index))

    shape = input_shape_for(arch)
    if any(dim < 1 for dim in shape):
        error(f"La forma de entrada {shape} debe tener dimensiones positivas.")
    if not arch.layers:
        error("La arquitectura necesita al menos una capa.")

    allowed = FAMILY_LAYERS[arch.family]
    results: list[LayerResult] = []
    broken = any(dim < 1 for dim in shape)

    for index, layer in enumerate(arch.layers):
        position = index + 1
        if layer.type not in allowed:
            error(f"La capa {position} ({layer.type}) no es válida para la familia {arch.family}.", index)
            broken = True

        for attr, (low, high) in LIMITS.items():
            value = getattr(layer, attr)
            if value is not None and not low <= value <= high:
                error(f"Capa {position}: {attr} debe estar entre {low} y {high}.", index)
                broken = True
        if layer.dropout is not None and not 0 <= layer.dropout < 0.9:
            error(f"Capa {position}: la tasa de dropout debe estar en [0, 0.9).", index)
            broken = True

        if broken:
            continue

        in_shape = list(shape)
        params = 0
        last = shape[-1]

        if layer.type == "Dense":
            if layer.units is None:
                error(f"Capa {position}: Dense requiere unidades.", index)
                broken = True
                continue
            if len(shape) != 1:
                error(f"Capa {position}: Dense espera un vector; añade Flatten o una capa recurrente antes.", index)
                broken = True
                continue
            params = last * layer.units + layer.units
            shape = [layer.units]
        elif layer.type == "Dropout":
            if layer.dropout is None:
                error(f"Capa {position}: Dropout requiere una tasa.", index)
                broken = True
                continue
        elif layer.type == "BatchNormalization":
            params = 4 * last
        elif layer.type == "Conv2D":
            if layer.filters is None or layer.kernel_size is None:
                error(f"Capa {position}: Conv2D requiere filtros y tamaño de kernel.", index)
                broken = True
                continue
            if len(shape) != 3:
                error(f"Capa {position}: Conv2D espera una entrada (alto, ancho, canales).", index)
                broken = True
                continue
            height, width, channels = shape
            k = layer.kernel_size
            if height - k + 1 < 1 or width - k + 1 < 1:
                error(f"Capa {position}: el kernel {k}×{k} es mayor que la entrada {height}×{width}.", index)
                broken = True
                continue
            params = k * k * channels * layer.filters + layer.filters
            shape = [height - k + 1, width - k + 1, layer.filters]
        elif layer.type == "MaxPooling2D":
            if len(shape) != 3:
                error(f"Capa {position}: MaxPooling2D espera una entrada (alto, ancho, canales).", index)
                broken = True
                continue
            pool = layer.pool_size or 2
            if shape[0] // pool < 1 or shape[1] // pool < 1:
                error(f"Capa {position}: el pooling {pool}×{pool} deja la salida vacía.", index)
                broken = True
                continue
            shape = [shape[0] // pool, shape[1] // pool, shape[2]]
        elif layer.type == "Flatten":
            shape = [prod(shape)]
        elif layer.type in RECURRENT:
            if layer.units is None:
                error(f"Capa {position}: {layer.type} requiere unidades.", index)
                broken = True
                continue
            if len(shape) != 2:
                error(f"Capa {position}: {layer.type} espera una secuencia (pasos, características).", index)
                broken = True
                continue
            units = layer.units
            if layer.type == "LSTM":
                params = 4 * (units * (last + units) + units)
            else:
                params = 3 * (units * (last + units) + 2 * units)
            shape = [shape[0], units] if returns_sequences(arch.layers, index) else [units]

        results.append(
            LayerResult(index=index, type=layer.type, input_shape=in_shape, output_shape=list(shape), params=params)
        )

    total = sum(result.params for result in results)
    if total > settings.max_params:
        error(f"La red suma {total:,} parámetros; el límite configurado es {settings.max_params:,}.")

    if arch.layers and not broken:
        tail = arch.layers[-1]
        if tail.type != "Dense":
            error("La última capa debe ser Dense para producir la salida del modelo.", len(arch.layers) - 1)
        elif tail.activation == "softmax" and tail.units == 1:
            warning("Softmax con una sola unidad siempre devuelve 1; usa sigmoid para clasificación binaria.")
        if arch.family == "GAN":
            issues.append(
                ArchitectureIssue(
                    severity="info",
                    message="Se valida el generador; el discriminador se construye simétrico al entrenar.",
                )
            )

    return ArchitectureSummary(
        valid=not any(issue.severity == "error" for issue in issues),
        input_shape=input_shape_for(arch),
        output_shape=shape if results else [],
        total_params=total,
        layers=results,
        issues=issues,
    )


def is_trainable_family(family: str) -> bool:
    return family in settings.training_families
