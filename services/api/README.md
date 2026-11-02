# NeuroLab Enterprise · Backend

API FastAPI + worker de entrenamiento TensorFlow/Keras, según el Documento Maestro (§8 entidades, §9 endpoints, §10 reglas, §18 MVP).

## Cumplimiento del Documento Maestro

El documento es la regla principal. Estado frente a lo que exige:

| Documento Maestro | Implementación | Estado |
|---|---|---|
| PostgreSQL (§5, §14) | PostgreSQL local; conexión en `.env` | Cumple |
| Migraciones (§14, §17) | Alembic en `infra/migrations`; la API las aplica al arrancar | Cumple |
| Pruebas de integración con PostgreSQL (§15) | Base `neurolab_test`; sin ella, respaldo SQLite con aviso | Cumple con `.env` |
| Tiempo real WebSocket o SSE (§5) | SSE que reenvía eventos persistidos; `Last-Event-ID` para reanudar | Cumple |
| Familias progresivas (§18) | Se validan las cuatro; solo FEEDFORWARD entrena | Cumple |
| Almacenamiento de objetos (§5) | Carpetas `data/uploads` y `data/models` | Pendiente |
| Proveedor de identidad seguro (§11) | Tokens HMAC propios; acceso sin token solo en desarrollo | Pendiente |
| Límites de tasa y retención (§11) | Cuotas por usuario y proyecto; retención guardada sin aplicar | Pendiente |
| TanStack Query (§5) | Hooks propios en `apps/web/src/lib/api` | Pendiente |
| Docker, CI/CD, logs, respaldos (§5, §11, §14) | No implementado | Pendiente |

Donde el documento no especifica: la cola de trabajos usa la propia tabla `training_jobs` (el worker reclama con UPDATE condicional) y los datasets admitidos son CSV.

## Base de datos (primera vez)

`run.bat` llama a `infra/postgres/crear_base.ps1`, que crea el usuario `neurolab` y las bases `neurolab` y `neurolab_test` en el PostgreSQL local y guarda la conexión en `.env`. Pide la contraseña del superusuario `postgres` una sola vez. Para hacerlo a mano:

```
powershell -ExecutionPolicy Bypass -File infra\postgres\crear_base.ps1
```

Cambios de esquema: edita `app/repositories/models.py` y genera la migración:

```
cd services\api
..\..\venv\Scripts\python.exe -m alembic revision --autogenerate -m "descripcion"
```

## Ejecutar

`run.bat` en la raíz levanta API, worker y frontend. Por separado:

```
venv\Scripts\python.exe services\api\app\main.py      # API → http://localhost:8000/docs
venv\Scripts\python.exe workers\training\main.py      # worker
```

El frontend consume solo la API (no hay datos simulados). Sin token, la API de desarrollo actúa como Ana Quispe; desde el menú de perfil se cambia a cualquier usuario demo para probar los roles (`POST /auth/dev-login`, solo con `NEUROLAB_AUTH_DEV_BYPASS=true`).

Usuarios demo (contraseña `neurolab2026`): `ana.quispe@neurolab.enterprise` (owner de PRJ-101), `rosa.medina@…` (revisora), `carla.nunez@…` (lectora), `sofia.ramirez@…` (admin), `diego.salas@…` (ajeno a PRJ-101).

## Pruebas

```
cd services\api
..\..\venv\Scripts\python.exe -m pytest
```

Usan la base `neurolab_test` de `.env` (se borra y se vuelve a migrar en cada ejecución). Incluyen el flujo E2E con TensorFlow real, cancelación cooperativa, aislamiento entre proyectos y que el resumen de parámetros coincide con Keras.

## Endpoints (`/api/v1`)

| Método | Ruta | Uso |
|---|---|---|
| POST | `/auth/login` · `/auth/dev-login` · GET `/auth/me` · `/users` · `/config` | Sesión, directorio y límites vigentes |
| GET/POST | `/projects` · GET/PATCH `/projects/{id}` | Proyectos accesibles |
| POST/DELETE | `/projects/{id}/members[/{userId}]` | Miembros (solo owner) |
| POST/PATCH/DELETE | `/projects/{id}/documents[/{docId}]` | Documentación (owner/engineer) |
| POST | `/architectures/validate` | Resumen de formas y parámetros sin guardar |
| GET/POST | `/projects/{id}/architectures` | Versiones de arquitectura |
| GET/POST | `/projects/{id}/datasets` (multipart) · GET/DELETE `/datasets/{id}` | CSV verificado (RN-01) |
| GET/POST | `/projects/{id}/training-jobs` · GET `/training-jobs` | Encolar (202) y listar |
| GET | `/training-jobs/{id}` · `/metrics` · `/evaluation` · `/logs` | Estado persistido |
| GET | `/training-jobs/{id}/events` | Canal SSE |
| POST | `/training-jobs/{id}/cancel` · `/retry` · `/priority` · `/start` | Cancelación (RN-05), reintento y cola |
| GET | `/evaluations` · `/observations` · POST `/training-jobs/{id}/observations` | Evaluación (M07) y limitaciones |
| GET | `/projects/{id}/models` · `/models/{id}` · `/models/{id}/download` | Registro (RN-04) |
| POST | `/models/{id}/status` | DRAFT → REVIEWED → APPROVED / RETIRED |
| GET | `/projects/{id}/audit-events` · `/audit-events` (admin) | Auditoría |
| GET | `/projects/{id}/reports/training-history.csv` · `/reports/exports` | Exportaciones auditadas (M09) |
| GET/POST/PATCH/PUT | `/admin/snapshot` · `/admin/users` · `/admin/limits/{id}` · `/admin/settings` | Consola M10 (solo admin) |
| GET | `/dashboard` · `/health` | M01 y salud |
