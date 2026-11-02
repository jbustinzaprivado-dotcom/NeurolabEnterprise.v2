# Contratos de la API · NeuroLab Enterprise

Entregable del §17 (contratos de la API) y base de las pruebas de contrato del §15.

| Archivo | Contenido |
|---|---|
| [openapi.json](openapi.json) | Contrato REST completo de `/api/v1`: rutas, parámetros, cuerpos y respuestas (OpenAPI 3.1) |
| [eventos-sse.json](eventos-sse.json) | Esquema JSON de cada evento del canal en vivo de entrenamientos |

Con la API en marcha, la misma especificación se puede explorar en http://localhost:8000/docs.

**Los contratos se generan desde el código; no se editan a mano:**

```
venv\Scripts\python.exe services\api\scripts\exportar_contratos.py
```

`services/api/tests/contract` falla si el código cambia un contrato sin regenerar estos archivos. Así cualquier cambio de contrato queda visible en el diff de la revisión.

## Convenciones

- **Versión:** toda ruta empieza por `/api/v1`. Un cambio incompatible requerirá `/api/v2`.
- **Formato:** JSON en camelCase, igual que los tipos de `apps/web/src/types`. Las fechas van en ISO 8601 con zona horaria.
- **Autenticación:** cabecera `Authorization: Bearer <token>`. Con Keycloak es el token de acceso OIDC. `GET /auth/config` y `GET /health` son públicas.
- **Errores:** cuerpo `{"detail": "<mensaje legible>"}`. En los errores de validación (422), `detail` es la lista de campos con su motivo.

| Código | Significado |
|---|---|
| 401 | Sin token, token inválido o sesión expirada |
| 403 | Autenticado, pero el rol no permite la acción, o la cuenta no está registrada o está suspendida |
| 404 | No existe **o no eres miembro del proyecto**; así no se revela si un recurso ajeno existe |
| 409 | Conflicto de estado: transición no permitida, nombre duplicado o recurso en uso |
| 410 | Recurso eliminado, por ejemplo un dataset borrado |
| 413 / 415 | Archivo demasiado grande, o tipo de archivo no admitido |
| 422 | Datos inválidos |
| 429 | Límite de tasa superado; la cabecera `Retry-After` indica cuántos segundos esperar |
| 503 | El proveedor de identidad no responde |

Cada respuesta lleva `X-Request-ID`, con el que la petición se encuentra en los logs.

## Recursos

| Área | Rutas principales | Módulo |
|---|---|---|
| Sesión | `GET /auth/config` · `POST /auth/session` · `GET /auth/me` · `GET /users` · `GET /config` | — |
| Panel | `GET /dashboard` · `GET /health` | M01 |
| Proyectos | `GET/POST /projects` · `GET/PATCH /projects/{id}` · miembros · documentos | M02 |
| Arquitecturas | `POST /architectures/validate` · `GET/POST /projects/{id}/architectures` | M04 |
| Datasets | `GET/POST /projects/{id}/datasets` · `GET/DELETE /datasets/{id}` | M05 |
| Entrenamientos | `POST/GET /projects/{id}/training-jobs` · `GET /training-jobs/{id}` · `cancel` · `retry` · `priority` · `start` · `metrics` · `logs` · `events` | M06 |
| Evaluación | `GET /training-jobs/{id}/evaluation` · `GET /evaluations` · observaciones | M07 |
| Modelos | `GET /projects/{id}/models` · `GET /models/{id}` · `POST /models/{id}/status` · `GET /models/{id}/download` | M08 |
| Reportes | `POST /projects/{id}/reports/exports` · `GET /projects/{id}/reports/training-history.csv` | M09 |
| Auditoría | `GET /projects/{id}/audit-events` · `GET /audit-events` | M09, M10 |
| Administración | `GET /admin/snapshot` · usuarios y roles · límites · políticas · retención · exportación de auditoría | M10 |

Están todas las rutas propuestas en el §9 del Documento Maestro.

## Canal en vivo (SSE)

`GET /api/v1/training-jobs/{id}/events`, autenticado como cualquier otra ruta. La interfaz lo lee con `fetch` en lugar de `EventSource` para poder enviar la cabecera `Authorization`.

```
retry: 3000

event: snapshot
data: {"id": "JOB-…", "status": "RUNNING", "epoch": 3, …}

id: 1842
event: metric
data: {"epoch": 4, "epochs": 20, "progress": 20.0, "loss": 0.41, "val_loss": 0.45, "accuracy": 0.86, …}

id: 1843
event: status
data: {"previous": "RUNNING", "status": "COMPLETED", "reason": "Modelo registrado como ff-iris v3.0.", …}

event: end
data: {"status": "COMPLETED"}
```

| Evento | Cuándo | Campos |
|---|---|---|
| `snapshot` | Primer mensaje | El trabajo completo, igual que `GET /training-jobs/{id}` |
| `status` | Cambio de estado | `previous`, `status`, `reason`, `progress`, `epoch`, `createdAt` |
| `metric` | Fin de cada época | `epoch`, `epochs`, `progress`, `loss`, `val_loss` y las métricas de la tarea (`accuracy`, `f1` en clasificación; `mae` en regresión), `createdAt` |
| `log` | Nota del worker o de la API | `level` (info, warn, error, success), `message`, `createdAt` |
| `end` | El trabajo llegó a un estado final y no quedan eventos | `status` |

- **Reconexión:** el cliente reenvía el último `id` recibido en la cabecera `Last-Event-ID` y el servidor entrega solo lo posterior. REST sigue siendo la fuente de verdad: el canal solo retransmite eventos ya guardados en `training_events`.
- **Inactividad:** si no hay eventos, el servidor envía un comentario `: keep-alive` cada 15 segundos.
