# Keycloak para Render (§11): reino de NeuroLab incluido y dominio público de la web añadido
# a las direcciones de retorno al arrancar (el reino del repo solo admite localhost).
FROM keycloak/keycloak:26.8.1

COPY infra/keycloak/neurolab-realm.json /opt/keycloak/neurolab-realm.json
COPY --chmod=755 infra/render/keycloak-entrypoint.sh /opt/keycloak/bin/render-entrypoint.sh

ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_HTTP_ENABLED=true \
    KC_PROXY_HEADERS=xforwarded

ENTRYPOINT ["/opt/keycloak/bin/render-entrypoint.sh"]
