#!/bin/bash
# Arranque de Keycloak en Render. Variables (las define render.yaml):
#   NEUROLAB_WEB_URL   dirección pública de la interfaz, p. ej. https://neurolab-web.onrender.com
#   KC_HOSTNAME        dirección pública de Keycloak,    p. ej. https://neurolab-keycloak.onrender.com
#   KC_DB_URL_HOST/PORT/DATABASE, KC_DB_USERNAME/PASSWORD, KC_BOOTSTRAP_ADMIN_PASSWORD
set -euo pipefail

web="${NEUROLAB_WEB_URL%/}"
if [[ -z "$web" ]]; then
  echo "Falta NEUROLAB_WEB_URL (dirección pública de la interfaz)." >&2
  exit 1
fi

# El reino de desarrollo admite solo localhost: se añade el dominio público (sin herramientas
# externas; la imagen de Keycloak no trae sed ni jq).
realm="$(</opt/keycloak/neurolab-realm.json)"
logout_old='"post.logout.redirect.uris": "http://localhost:5173/*##http://localhost:8080/*"'
logout_new="\"post.logout.redirect.uris\": \"http://localhost:5173/*##http://localhost:8080/*##$web/*\""
realm="${realm/"$logout_old"/$logout_new}"
redirect_old='"http://localhost:8080/*"'
redirect_new="\"http://localhost:8080/*\", \"$web/*\""
realm="${realm/"$redirect_old"/$redirect_new}"
mkdir -p /opt/keycloak/data/import
printf '%s' "$realm" > /opt/keycloak/data/import/neurolab-realm.json

# Las tablas de Keycloak van en su propio esquema de la base de Render.
exec /opt/keycloak/bin/kc.sh start \
  --import-realm \
  --http-port="${PORT:-8080}" \
  --db-schema="${KC_DB_SCHEMA:-keycloak}"
