"""Logs estructurados (§5 Operación) sin contraseñas, tokens ni datos de datasets (§11).

Cada línea es un objeto JSON con hora UTC, nivel, servicio y mensaje, más los campos
que el código pase en `extra` (método, ruta, estado, duración, usuario, trabajo…).
Con NEUROLAB_LOG_FORMAT=text se usa un formato legible para la consola.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

from app.core.config import settings

# Atributos propios de LogRecord: lo demás que llegue en `extra` se serializa.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}
# Defensa en profundidad: nunca escribir credenciales aunque alguien las pase al log.
_SECRET = re.compile(r"(bearer\s+)[\w\-.]+|(password|contraseña|token|secret)(\W+)\S+", re.IGNORECASE)


def _redact(text: str) -> str:
    return _SECRET.sub(lambda m: f"{m.group(1)}***" if m.group(1) else f"{m.group(2)}{m.group(3)}***", text)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "msg": _redact(record.getMessage()),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc"] = _redact(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(service: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format == "text":
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    else:
        handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level)
    # El acceso HTTP lo registra la API con campos propios; uvicorn solo lo duplicaría.
    logging.getLogger("uvicorn.access").disabled = True
