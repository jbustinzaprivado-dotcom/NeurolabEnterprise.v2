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
| Proveedor de identidad seguro (§11) | Keycloak 26.8.1 (reino `neurolab`, `infra/keycloak`). La interfaz entra con Authorization Code + PKCE; la API valida tokens RS256 por JWKS (emisor, audiencia `neurolab-api`, expiración) y enlaza cada cuenta con su usuario de NeuroLab. En producción la API no arranca sin OIDC. El modo `local` (contraseñas propias, bloqueo tras 5 intentos) queda para pruebas | Cumple; HTTPS pendiente (fase 6) |
| Límites de tasa (§11) | Por usuario (editable en M10, 600/min por defecto) y por IP en el inicio de sesión (10/min); responde 429 con `Retry-After` | Cumple |
| Política de retención (§11) | Auditoría, métricas por época y artefactos de modelos retirados; el worker la aplica cada hora y M10 puede lanzarla a mano | Cumple |
| Cifrado en tránsito (§11) | HTTP en local; HTTPS va con el despliegue | Pendiente (fase 6) |
| TanStack Query (§5) | Caché compartida en `apps/web/src/lib/api/queryClient.ts`; las mutaciones invalidan las claves afectadas | Cumple |
| Logs estructurados (§5) | JSON por línea con `request_id`, ruta, estado, duración y usuario; se redactan tokens y contraseñas | Cumple |
| Métricas (§5) | Prometheus en `/metrics` (solo red interna) y `infra/monitoring/prometheus.yml` | Cumple |
| Copias de seguridad probadas (§11) | `respaldo.ps1`, `restaurar.ps1` y `probar_respaldo.ps1` en `infra/postgres` | Cumple; ejecutar tras crear la base |
| CI (§14, §15) | GitHub Actions: pruebas contra PostgreSQL, `alembic check` y build del frontend | Cumple |
| Docker (§5) | `infra/docker`: imágenes de API/worker y web, compose con PostgreSQL, SeaweedFS, Keycloak y Prometheus | Escrito; sin probar localmente (Docker no instalado) |

Donde el documento no especifica: la cola de trabajos usa la propia tabla `training_jobs` (el worker reclama con UPDATE condicional) y los datasets admitidos son CSV.

## Base de datos (primera vez)

`run.bat` llama a `infra/postgres/crear_base.ps1`, que crea en el PostgreSQL local el usuario `neurolab` con las bases `neurolab` y `neurolab_test`, y el usuario `keycloak` con su base `keycloak`. Guarda en `.env` las conexiones, las claves generadas al azar y la configuración del proveedor de identidad. Pide la contraseña del superusuario `postgres` una sola vez; si `.env` ya tiene todo, no hace nada. Para hacerlo a mano:

```
powershell -ExecutionPolicy Bypass -File infra\postgres\crear_base.ps1
```

Cambios de esquema: edita `app/repositories/models.py` y genera la migración:

```
cd services\api
..\..\venv\Scripts\python.exe -m alembic revision --autogenerate -m "descripcion"
```

## Proveedor de identidad (§11)

Keycloak está en `Downloads\Semana 12\herramientas\keycloak-26.8.1` (fuera del repositorio; necesita Java 21 o superior; aquí se usa el JDK 25). `run.bat` lo arranca cuando `.env` tiene `NEUROLAB_AUTH_PROVIDER=oidc`. A mano:

```
powershell -ExecutionPolicy Bypass -File infra\keycloak\iniciar.ps1
```

- La primera vez importa `infra/keycloak/neurolab-realm.json`: el cliente público `neurolab-web` y los 9 usuarios demo (usuario = parte del correo antes de `@`, por ejemplo `ana.quispe`; contraseña `neurolab2026`).
- Consola de administración: http://localhost:8180/admin, usuario `admin`, clave `KEYCLOAK_ADMIN_PASSWORD` de `.env`.
- Keycloak aplica su propia política de contraseñas y el bloqueo tras 5 intentos fallidos.
- Roles y permisos por proyecto siguen en NeuroLab. Una cuenta de Keycloak entra solo si su correo verificado coincide con un usuario de NeuroLab. En el primer acceso queda enlazada por su identificador (`sub`), y la auditoría registra `auth.linked`.
- Para dar acceso a alguien nuevo: invítalo en M10 y crea su cuenta en Keycloak con el mismo correo.
- `-BaseLocal` usa la base de archivos interna de Keycloak en lugar de PostgreSQL (solo para pruebas rápidas).
- Para volver a contraseñas propias y al cambio de usuario demo, pon en `.env` `NEUROLAB_AUTH_PROVIDER=local` y `NEUROLAB_AUTH_DEV_BYPASS=true`.

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
  Web en http://localhost:8080, Keycloak en http://localhost:8180 y Prometheus en http://localhost:9090.

## Ejecutar

`run.bat` en la raíz levanta API, worker y frontend. Por separado:

```
venv\Scripts\python.exe services\api\app\main.py      # API → http://localhost:8000/docs
venv\Scripts\python.exe workers\training\main.py      # worker
```

El frontend consume solo la API (no hay datos simulados). Con OIDC, la interfaz pide iniciar sesión en Keycloak; para probar otro rol, cierra sesión y entra con otro usuario demo. En modo `local` con `NEUROLAB_AUTH_DEV_BYPASS=true`, sin token la API actúa como Ana Quispe y el menú de perfil cambia de usuario demo (`POST /auth/dev-login`).

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
| GET | `/auth/config` (pública) | Cómo iniciar sesión: proveedor, cliente y direcciones de Keycloak |
| POST | `/auth/session` (OIDC) · `/auth/login` · `/auth/dev-login` (local) · GET `/auth/me` · `/users` · `/config` | Sesión, directorio y límites vigentes |
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
