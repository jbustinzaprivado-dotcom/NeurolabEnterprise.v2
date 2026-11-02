"""Límites de tasa (§11): ventana deslizante de 60 s por identidad.

Vive en memoria del proceso de la API, que es único en este despliegue. Con varias
réplicas habría que moverlo a un almacén compartido; la interfaz no cambiaría.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

WINDOW_SECONDS = 60.0


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int) -> int:
        """Registra el intento; devuelve 0 si se permite o los segundos a esperar si no."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, int(WINDOW_SECONDS - (now - hits[0])) + 1)
            hits.append(now)
            return 0

    def peak(self) -> int:
        """Mayor número de peticiones de una misma identidad en la ventana actual."""
        now = time.monotonic()
        with self._lock:
            return max(
                (sum(1 for hit in hits if now - hit < WINDOW_SECONDS) for key, hits in self._hits.items()
                 if key.startswith("user:")),
                default=0,
            )

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()

# Valor vigente de M10 cacheado unos segundos para no leer la base en cada petición.
limit_cache: dict[str, float] = {"value": 0.0, "read_at": float("-inf")}


def invalidate_limit_cache() -> None:
    limit_cache["read_at"] = float("-inf")
