r"""Regenera los contratos publicados en docs/api (§15 Contrato, §17 contratos API).

    venv\Scripts\python.exe services\api\scripts\exportar_contratos.py

- docs/api/openapi.json: rutas, parámetros y esquemas REST de /api/v1.
- docs/api/eventos-sse.json: esquema de cada evento del canal de entrenamiento.

La prueba tests/contract/test_contracts.py falla si el código cambia un contrato sin
regenerar estos archivos: así cualquier cambio de contrato queda visible en la revisión.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
ROOT = API_DIR.parents[1]
DOCS = ROOT / "docs" / "api"
sys.path.insert(0, str(API_DIR))
# Los contratos no dependen de la configuración local; no hace falta una base real.
os.environ.setdefault("NEUROLAB_DATABASE_URL", "sqlite://")
os.environ["NEUROLAB_AUTH_PROVIDER"] = "local"


def build() -> dict[str, dict]:
    from app.main import app
    from app.schemas.events import EVENTS

    events = {name: model.model_json_schema(by_alias=True) for name, model in EVENTS.items()}
    return {
        "openapi.json": app.openapi(),
        "eventos-sse.json": {
            "title": "Eventos SSE de /api/v1/training-jobs/{id}/events",
            "description": (
                "Cada mensaje SSE lleva `event: <nombre>` y `data: <JSON>`. Los eventos persistidos "
                "(status, metric, log) llevan además `id:` para reanudar con la cabecera Last-Event-ID."
            ),
            "events": events,
        },
    }


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    for name, content in build().items():
        (DOCS / name).write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"docs/api/{name} actualizado.")


if __name__ == "__main__":
    main()
