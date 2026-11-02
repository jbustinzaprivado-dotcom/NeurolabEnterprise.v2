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
| Almacenamiento de objetos (§5) | Interfaz única con backend S3 (SeaweedFS en Docker y en la CI; también MinIO o AWS) y backend local `data/` para desarrollo; producción exige S3 | Cumple (en local, respaldo `data/` mientras no haya MinIO) |
| Proveedor de identidad seguro (§11) | Tokens HMAC propios y bloqueo tras 5 intentos fallidos. El acceso sin token solo existe en desarrollo y la API no arranca con él en producción | Parcial: falta un IdP externo |
| Límites de tasa (§11) | Por usuario (editable en M10, 600/min por defecto) y por IP en el inicio de sesión (10/min); responde 429 con `Retry-After` | Cumple |
| Política de retención (§11) | Auditoría, métricas por época y artefactos de modelos retirados; el worker la aplica cada hora y M10 puede lanzarla a mano | Cumple |
| Cifrado en tránsito (§11) | HTTP en local; HTTPS va con el despliegue | Pendiente (fase 6) |
| TanStack Query (§5) | Caché compartida en `apps/web/src/lib/api/queryClient.ts`; las mutaciones invalidan las claves afectadas | Cumple |
| Logs estructurados (§5) | JSON por línea con `request_id`, ruta, estado, duración y usuario; se redactan tokens y contraseñas | Cumple |
| Métricas (§5) | Prometheus en `/metrics` (solo red interna) y `infra/monitoring/prometheus.yml` | Cumple |
| Copias de seguridad probadas (§11) | `respaldo.ps1`, `restaurar.ps1` y `probar_respaldo.ps1` en `infra/postgres` | Cumple; ejecutar tras crear la base |
| CI (§14, §15) | GitHub Actions: pruebas contra PostgreSQL, `alembic check` y build del frontend | Cumple |
| Docker (§5) | `infra/docker`: imágenes de API/worker y web, compose con PostgreSQL y Prometheus | Escrito; sin probar localmente (Docker no instalado) |

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

## Datos demo (§17)

Con la base vacía, la API carga datos demo no sensibles definidos en `app/demo/`:

- **Usuarios:** los 9 del directorio, con contraseña `neurolab2026`.
- **Proyectos:** 12, con miembros, documentos y etiquetas.
- **Datasets:** 7 CSV generados dentro del proyecto. Son sintéticos o vienen incluidos en scikit-learn; ninguna fila corresponde a una persona real.
- **Arquitecturas:** 15. Las Feedforward entrenan; las RNN, CNN y GAN quedan documentadas (§18).
- **Historial (solo en desarrollo, `NEUROLAB_SEED_HISTORY`):** unos diez entrenamientos que la semilla deja en cola y el worker ejecuta de verdad al arrancar (alrededor de 1 minuto). Incluyen uno cancelado y uno con parada temprana. Las pruebas no cargan este historial.

## Operación (§5, §11)

- **Logs:** JSON por línea (`NEUROLAB_LOG_FORMAT=text` para consola legible). Cada respuesta lleva `X-Request-ID` para seguir una petición en los logs.
- **Métricas:** `GET http://localhost:8000/metrics` (Prometheus). Responde solo desde la propia máquina, salvo con `NEUROLAB_METRICS_REMOTE=true`.
- **Respaldos** (desde la raíz):
  ```
  powershell -ExecutionPolicy Bypass -File infra\postgres\respaldo.ps1
  powershell -ExecutionPolicy Bypass -File infra\postgres\probar_respaldo.ps1
  powershell -ExecutionPolicy Bypass -File infra\postgres\restaurar.ps1 -Respaldo <carpeta>
  ```
  Quedan en `data/backups/<fecha>`: volcado de PostgreSQL, ZIP de datasets y modelos, y manifiesto con checksums. Se conservan los 7 últimos. Con `NEUROLAB_STORAGE_BACKEND=s3` los archivos viven en el bucket: respáldalo con las herramientas del proveedor (por ejemplo `weed` en SeaweedFS o `aws s3 sync`).
- **Docker:** copia `infra/docker/.env.example` como `infra/docker/.env`, y luego:
  ```
  docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env up --build
  ```
  Web en http://localhost:8080 y Prometheus en http://localhost:9090.

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
