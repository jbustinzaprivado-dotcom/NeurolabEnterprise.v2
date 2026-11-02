# Guía operativa · NeuroLab Enterprise

Entregable del §17: despliegue, monitoreo y respaldo. Incluye el **checklist de producción**, que es la condición de salida de la fase 6 (§14).

## 1. Componentes y puertos

| Servicio | Puerto local | Arranque |
|---|---|---|
| Interfaz web (Vite) | 5173 | `run.bat` o `npm run dev` en `apps/web` |
| API FastAPI | 8000 (`/docs`, `/metrics`) | `venv\Scripts\python.exe services\api\app\main.py` |
| Worker de entrenamiento | — | `venv\Scripts\python.exe workers\training\main.py` |
| Keycloak | 8180 (`/admin`) | `infra\keycloak\iniciar.ps1` |
| PostgreSQL 18 | 5432 | Servicio de Windows `postgresql-x64-18` |

En Docker: web en 8080, Keycloak en 8180 y Prometheus en 9090.

## 2. Instalación local (primera vez)

**Requisitos:** Python 3.12 o superior, Node.js 20 o superior, PostgreSQL 18 y Java 21 o superior para Keycloak. Keycloak 26.8.1 va descomprimido en `Downloads\Semana 12\herramientas`.

1. Crea las bases y `.env`. Pide la contraseña del usuario `postgres` una sola vez:
   ```
   powershell -ExecutionPolicy Bypass -File infra\postgres\crear_base.ps1
   ```
   Crea los usuarios `neurolab` y `keycloak`, sus bases (`neurolab`, `neurolab_test` y `keycloak`), claves aleatorias y la configuración OIDC.
2. Ejecuta `run.bat`. Instala las dependencias y abre cuatro ventanas: Keycloak, la API, el worker y la web.
3. La primera vez, la API aplica las migraciones y carga los datos demo, y Keycloak importa el reino `neurolab`.

**Detener:** cierra las ventanas o pulsa Ctrl+C en cada una. El worker termina la época en curso antes de salir, y ese trabajo queda `FAILED` con el motivo para reintentarlo.

## 3. Configuración

Toda la configuración va en variables `NEUROLAB_*`, leídas del entorno o de `.env`. **Los secretos nunca se suben al repositorio** (`.env` está en `.gitignore`). La referencia completa está en `.env.example`.

| Variable | Valor local | Producción |
|---|---|---|
| `NEUROLAB_ENV` | `development` | `production`: la API rechaza configuraciones inseguras al arrancar |
| `NEUROLAB_DATABASE_URL` | La escribe `crear_base.ps1` | Obligatoria |
| `NEUROLAB_AUTH_PROVIDER` / `NEUROLAB_OIDC_ISSUER` | `oidc` / `http://localhost:8180/realms/neurolab` | Obligatorias; el emisor debe ir en HTTPS |
| `NEUROLAB_OIDC_INTERNAL_URL` | — | Solo si la API alcanza a Keycloak por otra dirección, como en Docker |
| `NEUROLAB_AUTH_DEV_BYPASS` | `false` | Prohibido en producción |
| `NEUROLAB_STORAGE_BACKEND` | `local` (carpeta `data/`) | `s3`, con `NEUROLAB_S3_ENDPOINT`, `_BUCKET`, `_ACCESS_KEY` y `_SECRET_KEY` |
| `NEUROLAB_SECRET_KEY` | — | Obligatoria |
| `NEUROLAB_SEED_DEMO` / `NEUROLAB_SEED_HISTORY` | `true` / `true` | `false` / `false` |
| `NEUROLAB_CORS_ORIGINS` | `http://localhost:5173` | Dominio público de la web |
| `NEUROLAB_API_PROXY` (solo `npm run dev`) | `http://localhost:8000` | — : en producción nginx hace de proxy |
| `NEUROLAB_LOG_FORMAT` | `json` (`text` para leer en consola) | `json` |
| `NEUROLAB_TRAINING_FAMILIES` | `FEEDFORWARD` | Se amplía cuando cada familia tenga sus pruebas |
| `NEUROLAB_WORKER_STALE_SECONDS` | `120` | Ajustar si la base o la red tienen pausas largas |

Los límites de uso (épocas, carga, duración, concurrencia, tasa y cuota) tienen valores iniciales en variables, y luego se editan en **M10** sin reiniciar nada.

## 4. Proveedor de identidad (Keycloak)

- **Consola:** http://localhost:8180/admin, usuario `admin`, con la clave `KEYCLOAK_ADMIN_PASSWORD` de `.env`.
- **Dar acceso a una persona:**
  1. Invítala en M10 con su correo.
  2. En la consola de Keycloak, entra en el reino `neurolab` → *Users* → *Add user* con **el mismo correo**, marca *Email verified* y asígnale una contraseña.

  En su primer acceso la cuenta queda enlazada con su usuario de NeuroLab.
- **Seguridad:** Keycloak aplica la política de contraseñas (10 caracteres como mínimo, con al menos un dígito) y bloquea la cuenta tras 5 intentos fallidos. Los tokens de acceso duran 5 minutos y la interfaz los renueva sola.
- **Si Keycloak no responde,** la interfaz muestra *"El proveedor de identidad no responde"* y la API devuelve 503 en `/auth/config`. Los entrenamientos en curso no se ven afectados.

## 5. Despliegue con Docker

```
copy infra\docker\.env.example infra\docker\.env      # y cambia todas las claves
docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env up --build
```

Levanta PostgreSQL (con una base aparte para Keycloak), SeaweedFS como almacén S3, Keycloak, la API, el worker, la web con nginx y Prometheus. La API y el worker se reinician solos si fallan al arrancar. Para tener más capacidad de entrenamiento, se agregan réplicas del worker: `--scale worker=3`.

> El compose está escrito y revisado, pero **todavía no se ha probado en una máquina con Docker**.

## 6. Monitoreo

**Logs:** una línea JSON por evento, con `ts`, `level`, `service` (api o worker), `logger` y `msg`. Las peticiones incluyen además `request_id`, `route`, `status`, `duration_ms` y `user`. Tokens, contraseñas y claves se redactan antes de escribirse.

Para seguir una petición concreta, busca en los logs el `X-Request-ID` que devolvió la respuesta.

**Métricas (Prometheus):** `GET /metrics` en la API. Responde solo desde la propia máquina, salvo con `NEUROLAB_METRICS_REMOTE=true`.

| Métrica | Qué mide |
|---|---|
| `neurolab_http_requests_total{route,method,status}` | Peticiones atendidas |
| `neurolab_http_request_duration_seconds` | Latencia (histograma) |
| `neurolab_rate_limited_total{scope}` | Rechazos por límite de tasa (`user` o `login`) |
| `neurolab_training_jobs{status}` | Trabajos por estado (la cola es `QUEUED`) |
| `neurolab_model_versions{status}` | Versiones por estado |
| `neurolab_workers_online` | Workers con latido reciente |

**Alertas recomendadas** (por configurar en Prometheus o en Alertmanager):

| Condición | Expresión |
|---|---|
| Sin workers | `neurolab_workers_online == 0` durante 2 min |
| Cola atascada | `neurolab_training_jobs{status="QUEUED"} > 0` y ningún `RUNNING` durante 10 min |
| Errores de servidor | `rate(neurolab_http_requests_total{status=~"5.."}[5m]) > 0` |
| Posible abuso | `rate(neurolab_rate_limited_total[5m]) > 1` |
| Latencia alta | p95 de `neurolab_http_request_duration_seconds` > 1 s |

**Salud:** `GET /api/v1/health` (pública) y el panel *Salud del sistema* de M10.

## 7. Respaldo, restauración y retención

```
powershell -ExecutionPolicy Bypass -File infra\postgres\respaldo.ps1                # respaldo nuevo
powershell -ExecutionPolicy Bypass -File infra\postgres\probar_respaldo.ps1         # respalda, restaura en neurolab_test y compara
powershell -ExecutionPolicy Bypass -File infra\postgres\restaurar.ps1 -Respaldo <carpeta>
```

- **Contenido del respaldo:** cada uno queda en `data\backups\<fecha>\` con el volcado de PostgreSQL (`neurolab.dump`), un ZIP de `data\uploads` y `data\models`, y un manifiesto con los checksums SHA-256. Se conservan los 7 últimos (`-Conservar N`).
- **Restaurar:** detén antes la API y el worker. El script verifica los checksums antes de tocar nada.
- **Almacén S3:** con `NEUROLAB_STORAGE_BACKEND=s3`, los archivos se respaldan con las herramientas del proveedor (`weed` en SeaweedFS o `aws s3 sync`).
- **Keycloak:** el reino se puede recrear desde `infra/keycloak/neurolab-realm.json`, pero las cuentas creadas después viven en la base `keycloak`. Respáldala aparte:
  ```
  & "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -U postgres -h localhost -Fc -f keycloak.dump keycloak
  ```
- **Retención:** el worker aplica cada hora los plazos de M10 (auditoría 365 días, métricas 365 días, artefactos retirados 730 días). También se puede lanzar desde M10 → *Aplicar retención*.

## 8. Recuperación ante fallos

| Falla | Qué hace el sistema | Qué hacer |
|---|---|---|
| El navegador se desconecta | El entrenamiento sigue; al volver, el canal en vivo reenvía solo lo pendiente | Nada |
| La API se reinicia | El estado está en PostgreSQL; al arrancar no duplica ni pierde datos | Nada |
| El worker muere a mitad de un trabajo | A los 120 s sin latido, otro worker lo marca `FAILED` y conserva las épocas ya entrenadas | Reintentar desde M06 |
| Un worker creído caído vuelve | Detecta que el trabajo ya no es suyo y lo abandona sin escribir nada | Nada |
| Falta el archivo de un dataset | El trabajo falla con mensaje controlado | Volver a subir el dataset |
| Keycloak no responde | Nadie puede iniciar sesión; los trabajos en curso siguen | Reiniciar Keycloak |
| Se pierde la base de datos | — | `restaurar.ps1` con el último respaldo |

Todos estos casos, salvo los de Keycloak y la pérdida de la base, tienen prueba automática (`services/api/tests/integration/test_recovery.py` y `test_training_flow.py`).

## 9. Actualizar a una versión nueva

1. `git pull` en la carpeta del proyecto.
2. Haz un respaldo (sección 7).
3. Ejecuta `run.bat`: reinstala las dependencias y la API aplica las migraciones pendientes al arrancar.

## 10. Pruebas

```
cd services\api
..\..\venv\Scripts\python.exe -m pytest
```

Hay 101 pruebas, que usan la base `neurolab_test` (se recrea en cada ejecución):

- `tests/unit`: validaciones, permisos y métricas;
- `tests/integration`: API con PostgreSQL, almacenamiento, cola, seguridad y recuperación;
- `tests/contract`: contratos REST y SSE de `docs/api`.

La CI de GitHub Actions las corre en cada push contra PostgreSQL y SeaweedFS, junto con `alembic check` y el build del frontend.

## 11. Checklist de producción (fase 6)

| # | Control | Estado |
|---|---|---|
| 1 | La API se niega a arrancar en producción sin OIDC, sin clave secreta o sin almacén S3, o con el acceso de desarrollo o el historial demo activos | ✅ Probado (`test_production_refuses_development_settings`) |
| 2 | Identidad con proveedor externo, RBAC por proyecto y 404 para recursos ajenos | ✅ |
| 3 | Límites de tasa, de carga, de duración y de concurrencia, y cuotas | ✅ |
| 4 | Auditoría de acciones relevantes y logs sin secretos | ✅ |
| 5 | Pruebas unitarias, de integración, de contrato y de recuperación en CI | ✅ |
| 6 | Prueba end-to-end desde el navegador | ⏳ Pendiente: el flujo está probado a nivel de API |
| 7 | Respaldo probado con restauración real (`probar_respaldo.ps1`) sobre la base de trabajo | ⏳ Pendiente de ejecutar |
| 8 | Respaldo de la base de Keycloak incluido en el script | ⏳ Pendiente: hoy es un comando manual |
| 9 | HTTPS en la web, la API y Keycloak (cifrado en tránsito, §11) | ⏳ Pendiente |
| 10 | Despliegue con Docker probado de punta a punta | ⏳ Pendiente: Docker no está instalado |
| 11 | Alertas configuradas en Prometheus (sección 6) | ⏳ Pendiente: las métricas existen |
| 12 | Claves de producción nuevas, sin valores de ejemplo, y datos demo desactivados | ⏳ Al desplegar |
| 13 | MFA obligatorio para administradores, configurado en Keycloak | ⏳ Al desplegar: la política existe en M10, pero la exige Keycloak |
