# NeuroLab Enterprise

Plataforma web para diseñar, entrenar, evaluar, versionar y aprobar redes neuronales con TensorFlow/Keras, con trazabilidad, seguridad y procesamiento asíncrono. Lleva a un sistema real las operaciones de la Semana 11 del curso PIAD-427, según el Documento Maestro de Desarrollo.

**Stack:** React + TypeScript + Vite · FastAPI · worker TensorFlow/Keras · PostgreSQL + Alembic · almacén S3 · Keycloak (OIDC) · SSE · Docker · GitHub Actions.

## Arranque rápido (Windows)

```
powershell -ExecutionPolicy Bypass -File infra\postgres\crear_base.ps1
run.bat
```

Abre http://localhost:5173 y entra con un usuario demo, por ejemplo `ana.quispe`, con la contraseña `neurolab2026`. La primera vez el script pide la contraseña del usuario `postgres`. Requisitos y detalles en la [guía operativa](docs/operations/guia-operativa.md#2-instalación-local-primera-vez).

## Documentación

| Documento | Para quién |
|---|---|
| [Manual de usuario](docs/manual-de-usuario.md) | Quien usa la plataforma: los módulos M01 a M10 paso a paso |
| [Arquitectura](docs/architecture/arquitectura.md) | Equipo técnico: objetivo, roles, flujos, componentes, seguridad y decisiones |
| [Modelo de datos](docs/architecture/modelo-de-datos.md) | Entidades, relaciones, almacén de objetos y retención |
| [Contratos de la API](docs/api/README.md) | REST (`openapi.json`) y eventos en vivo (`eventos-sse.json`) |
| [Despliegue en Render](docs/operations/despliegue-render.md) | Publicar la plataforma con `render.yaml`, Cloudflare R2 y Keycloak |
| [Guía operativa](docs/operations/guia-operativa.md) | Despliegue, configuración, monitoreo, respaldo, recuperación y checklist de producción |
| [API: detalle técnico](services/api/README.md) | Cumplimiento por sección del Documento Maestro, datos demo y pruebas |

## Estructura

```
apps/web/            interfaz React (features/ por módulo M01–M10)
services/api/        API FastAPI, pruebas y contratos
workers/training/    worker de entrenamiento TensorFlow/Keras
infra/               migraciones, PostgreSQL, Keycloak, Docker y monitoreo
docs/                arquitectura, API, operación y manual
```
