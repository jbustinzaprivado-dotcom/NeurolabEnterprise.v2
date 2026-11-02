#!/bin/sh
# Primera inicialización de PostgreSQL: base y usuario propios de Keycloak (§11),
# separados de los datos de NeuroLab.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE ROLE keycloak LOGIN PASSWORD '${KEYCLOAK_DB_PASSWORD}';
CREATE DATABASE keycloak OWNER keycloak;
EOSQL
