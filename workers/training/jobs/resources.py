"""Límites de recursos de cada entrenamiento (§10): núcleos de CPU, memoria y GPU.

- CPU: el proceso del worker se fija a N núcleos mientras entrena (afinidad del sistema
  operativo), así un entrenamiento no deja sin CPU a la API ni a la base de datos.
- Memoria: se mide el uso real del proceso durante el entrenamiento; si supera el límite,
  el trabajo se detiene con un mensaje claro en lugar de agotar la memoria de la máquina.
- GPU: TensorFlow fija las GPU visibles al arrancar, por eso el límite se aplica al iniciar
  el worker (con 0 se ocultan antes de importar TensorFlow).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import psutil

logger = logging.getLogger("neurolab.worker")
_process = psutil.Process()


@dataclass(frozen=True)
class JobLimits:
    cpu_threads: int
    memory_mb: int
    gpus: int


def read_limits() -> JobLimits:
    from app.core.database import SessionLocal
    from app.services import platform_settings

    with SessionLocal() as db:
        return JobLimits(
            cpu_threads=int(platform_settings.limit(db, "cpuThreads")),
            memory_mb=int(platform_settings.limit(db, "memory")),
            gpus=int(platform_settings.limit(db, "gpu")),
        )


def memory_mb() -> float:
    """Memoria física que usa ahora el proceso del worker, en MB."""
    return _process.memory_info().rss / 2**20


def hide_gpus_if_disabled() -> int:
    """Antes de importar TensorFlow: con el límite en 0 el worker no ve ninguna GPU."""
    gpus = read_limits().gpus
    if gpus == 0:
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    elif "CUDA_VISIBLE_DEVICES" not in os.environ:
        os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(str(index) for index in range(gpus))
    return gpus


class CpuPinning:
    """Fija el proceso a los primeros N núcleos mientras dura el entrenamiento."""

    def __init__(self, cores: int) -> None:
        self.requested = cores
        self.applied: int | None = None
        self._previous: list[int] | None = None

    def __enter__(self) -> CpuPinning:
        try:
            available = _process.cpu_affinity()
        except (AttributeError, psutil.Error, OSError):
            # macOS no admite afinidad: el entrenamiento usa todos los núcleos.
            logger.info("El sistema no permite fijar núcleos; el límite de CPU no se aplica.")
            return self
        self._previous = list(available)
        chosen = available[: max(1, min(self.requested, len(available)))]
        try:
            _process.cpu_affinity(chosen)
            self.applied = len(chosen)
        except (psutil.Error, OSError) as exc:
            logger.warning("No se pudo fijar la CPU a %d núcleos: %s", len(chosen), exc)
        return self

    def __exit__(self, *_exc) -> None:
        if self._previous is not None and self.applied is not None:
            try:
                _process.cpu_affinity(self._previous)
            except (psutil.Error, OSError):
                logger.warning("No se pudo restaurar la afinidad de CPU del worker.", exc_info=True)


def total_cores() -> int:
    return psutil.cpu_count(logical=True) or 1
