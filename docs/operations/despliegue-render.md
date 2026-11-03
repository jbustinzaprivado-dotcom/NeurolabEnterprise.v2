# Despliegue en Render · NeuroLab Enterprise

Guía para publicar la plataforma con el Blueprint [`render.yaml`](../../render.yaml). Complementa la [guía operativa](guia-operativa.md).

## Qué se crea

| Servicio Render | Tipo | Plan del Blueprint | Qué hace |
|---|---|---|---|
| `neurolab-web` | Static Site | gratuito | La interfaz React, con HTTPS |
| `neurolab-api` | Web Service (Docker) | starter | API FastAPI; aplica las migraciones al arrancar |
| `neurolab-worker` | Background Worker (Docker) | standard | Entrena con TensorFlow; necesita más memoria |
| `neurolab-keycloak` | Web Service (Docker) | standard | Proveedor de identidad con el reino `neurolab` |
| `neurolab-db` | PostgreSQL | basic | Base de NeuroLab (esquema `public`) y de Keycloak (esquema `keycloak`) |

El **almacén de objetos** va fuera de Render, porque Render no ofrece S3. Esta guía usa **Cloudflare R2**, que tiene una capa gratuita. AWS S3 o Backblaze B2 sirven igual.

> **Costo:** el plan gratuito de Render no incluye workers y duerme los servicios web sin uso. El worker, Keycloak y la base son de pago. Revisa los precios vigentes en render.com/pricing antes de crear el Blueprint; los planes se pueden cambiar después en cada servicio.

## 1. Almacén de objetos (Cloudflare R2)

1. En el panel de Cloudflare, abre **R2 → Create bucket**, con el nombre `neurolab`.
2. Ve a **R2 → Manage API tokens → Create API token**. Elige el permiso **Object Read & Write**, limitado al bucket `neurolab`.
3. Anota los tres datos que muestra **una sola vez**:
   - **Access Key ID**
   - **Secret Access Key**
   - **Endpoint**, con la forma `https://<id-de-cuenta>.r2.cloudflarestorage.com`

## 2. Crear el Blueprint en Render

1. En Render, ve a **New → Blueprint** y conecta el repositorio `NeurolabEnterprise.v2`, en la rama `main`. Render detecta `render.yaml`.
2. Render pide las variables marcadas con `sync: false`. Las de S3 y del emisor se piden dos veces, una para la API y otra para el worker: pon el mismo valor en ambas. Las direcciones públicas siguen la forma `https://<nombre-del-servicio>.onrender.com`. Si un nombre ya está ocupado, Render le añade un sufijo; en ese caso, corrige la variable en el paso 3.

| Servicio | Variable | Valor |
|---|---|---|
| `neurolab-api` y `neurolab-worker` | `NEUROLAB_S3_ENDPOINT` | El endpoint de R2 |
| `neurolab-api` y `neurolab-worker` | `NEUROLAB_S3_ACCESS_KEY` | La Access Key ID de R2 |
| `neurolab-api` y `neurolab-worker` | `NEUROLAB_S3_SECRET_KEY` | La Secret Access Key de R2 |
| `neurolab-api` y `neurolab-worker` | `NEUROLAB_OIDC_ISSUER` | `https://neurolab-keycloak.onrender.com/realms/neurolab` |
| `neurolab-api` | `NEUROLAB_CORS_ORIGINS` | `https://neurolab-web.onrender.com` |
| `neurolab-keycloak` | `KC_HOSTNAME` | `https://neurolab-keycloak.onrender.com` |
| `neurolab-keycloak` | `NEUROLAB_WEB_URL` | `https://neurolab-web.onrender.com` |
| `neurolab-web` | `VITE_API_BASE_URL` | `https://neurolab-api.onrender.com/api/v1` |

3. Pulsa **Apply**. Render crea la base y luego los servicios, y construye las imágenes; la primera vez tarda varios minutos.
4. **Si alguna dirección real difiere** de la que pusiste, corrige la variable en el servicio: *Environment → Save changes*. Render vuelve a desplegarlo. `VITE_API_BASE_URL` se incluye al compilar la interfaz, así que tras cambiarla hace falta un despliegue nuevo de `neurolab-web`.

Las claves `NEUROLAB_SECRET_KEY` y `KC_BOOTSTRAP_ADMIN_PASSWORD` las genera Render al azar. No están en el repositorio.

## 3. Orden de arranque

- La **API** crea el esquema `keycloak` en la base al arrancar (`NEUROLAB_EXTRA_SCHEMAS`), aplica las migraciones y carga los datos demo.
- **Keycloak** puede fallar una vez si arranca antes de que exista su esquema. Render lo reinicia solo y el segundo intento funciona.
- El **worker** espera a que exista el esquema de NeuroLab.

## 4. Verificar

| Comprobación | Dónde | Esperado |
|---|---|---|
| API viva | `https://neurolab-api.onrender.com/api/v1/health` | JSON con `"status": "HEALTHY"` y `"workersOnline": 1` |
| Reino publicado | `https://neurolab-keycloak.onrender.com/realms/neurolab` | JSON con `"realm": "neurolab"` |
| Inicio de sesión | `https://neurolab-web.onrender.com` → **Iniciar sesión** | Formulario de Keycloak; entra con `ana.quispe` y la contraseña `neurolab2026` |
| Worker | M10 → *Salud del sistema* | "1 en línea" |
| Entrenamiento | M06: encola `ff-iris` | Las épocas llegan en vivo y M08 muestra la versión nueva |

## 5. Antes de compartir la dirección

La API se niega a arrancar en producción con una configuración insegura: sin OIDC, sin clave secreta, sin S3, con acceso de desarrollo o con historial demo. Aun así, antes de abrirla a otras personas:

1. **Contraseñas demo.** Los 9 usuarios demo tienen la contraseña `neurolab2026`, que está publicada en el repositorio. Para un entorno compartido:
   - entra a la consola de Keycloak: `https://neurolab-keycloak.onrender.com/admin`, usuario `admin`, con la clave `KC_BOOTSTRAP_ADMIN_PASSWORD` del panel de Render;
   - en el reino `neurolab` → *Users*, cambia sus contraseñas o desactiva los usuarios que no uses.
2. **MFA para administración.** En el reino `neurolab` → *Users* → `sofia.ramirez` → *Required user actions* → **Configure OTP**. Es el punto 13 del checklist.
3. **Sin datos demo.** Para un entorno sin datos de ejemplo, pon `NEUROLAB_SEED_DEMO=false` antes del primer arranque. Los datos ya cargados no se borran solos.
4. **Respaldos.**
   - Los planes de pago de Render Postgres incluyen respaldos automáticos; revisa su retención en el servicio de la base.
   - El bucket de R2 se respalda aparte.

## 6. Actualizaciones

Con `autoDeploy: true`, cada push a `main` vuelve a desplegar los servicios. La API aplica las migraciones pendientes al arrancar.

Si la CI de GitHub falla, conviene no subir a `main` hasta corregirla. También puedes desactivar *Auto-Deploy* y desplegar a mano desde el panel.

## Limitaciones

- **Sin GPU:** el entrenamiento corre en CPU, que alcanza para los datasets demo.
- **Un solo worker:** para más capacidad, sube las instancias de `neurolab-worker` en su panel. La cola reparte los trabajos sin duplicarlos.
- **Arranque en frío del Static Site:** no lo tiene. Los servicios de pago no se duermen.
