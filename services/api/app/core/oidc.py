"""Validación de tokens del proveedor de identidad externo (§11), p. ej. Keycloak.

La interfaz obtiene el token con el flujo Authorization Code + PKCE; la API solo comprueba
que el token de acceso esté firmado por el proveedor (RS256, claves públicas JWKS), que lo
emitió el reino configurado, que va dirigido a `neurolab-api` y que no ha expirado.
Los roles y la pertenencia a proyectos siguen viviendo en NeuroLab.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.request
from collections import OrderedDict

import jwt

from app.core.config import settings

_ALGORITHMS = ["RS256"]
_LEEWAY_SECONDS = 30
_CACHE_SIZE = 512


class OidcError(Exception):
    pass


class OidcVerifier:
    def __init__(self, issuer: str, audience: str, internal_url: str = "") -> None:
        self.issuer = issuer
        self.audience = audience
        self.internal_url = internal_url
        self._jwks: jwt.PyJWKClient | None = None
        self._discovery: dict | None = None
        self._lock = threading.Lock()
        # Tokens ya validados (por huella SHA-256) hasta que expiran: el middleware de tasa y
        # la dependencia de usuario no repiten la verificación RSA en cada petición.
        self._cache: OrderedDict[str, dict] = OrderedDict()

    def _fetch_json(self, url: str) -> dict:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310  URL de configuración
            return json.loads(response.read())

    def _base(self) -> str:
        return self.internal_url or self.issuer

    def discovery(self) -> dict:
        """Documento `.well-known/openid-configuration` del reino (se lee una vez)."""
        with self._lock:
            if self._discovery is None:
                try:
                    self._discovery = self._fetch_json(f"{self._base()}/.well-known/openid-configuration")
                except (OSError, ValueError) as exc:
                    raise OidcError(f"No se pudo contactar al proveedor de identidad: {exc}") from exc
            return self._discovery

    def jwks_client(self) -> jwt.PyJWKClient:
        if self._jwks is None:
            jwks_uri = self.discovery()["jwks_uri"]
            if self.internal_url and jwks_uri.startswith(self.issuer):
                jwks_uri = self.internal_url + jwks_uri[len(self.issuer):]
            self._jwks = jwt.PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600, timeout=5)
        return self._jwks

    def browser_endpoints(self) -> dict:
        """Direcciones que usa la interfaz (son las públicas del proveedor)."""
        document = self.discovery()
        return {
            "authorizationEndpoint": document["authorization_endpoint"],
            "tokenEndpoint": document["token_endpoint"],
            "endSessionEndpoint": document.get("end_session_endpoint"),
        }

    def verify(self, token: str) -> dict:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            claims = self._cache.get(digest)
            if claims is not None and claims["exp"] > time.time():
                self._cache.move_to_end(digest)
                return claims

        try:
            key = self.jwks_client().get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=_ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                leeway=_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except (jwt.PyJWTError, OSError) as exc:
            raise OidcError(str(exc)) from exc

        with self._lock:
            self._cache[digest] = claims
            while len(self._cache) > _CACHE_SIZE:
                self._cache.popitem(last=False)
        return claims


_verifier: OidcVerifier | None = None


def get_verifier() -> OidcVerifier:
    global _verifier
    if _verifier is None or _verifier.issuer != settings.oidc_issuer:
        _verifier = OidcVerifier(settings.oidc_issuer, settings.oidc_audience, settings.oidc_internal_url)
    return _verifier


def set_verifier(verifier: OidcVerifier | None) -> None:
    """Las pruebas inyectan un verificador con claves generadas localmente."""
    global _verifier
    _verifier = verifier


def subject(token: str) -> str | None:
    """`sub` de un token válido, o None (lo usa el límite de tasa por usuario)."""
    try:
        return get_verifier().verify(token)["sub"]
    except OidcError:
        return None
