"""Almacenamiento de objetos para datasets y artefactos de modelos (§5).

La base guarda solo metadatos y la clave del objeto (`storage_key`); los archivos viven
aquí. Dos implementaciones con la misma interfaz:

- `s3`: cualquier servicio compatible con S3 (SeaweedFS en docker-compose y CI, MinIO, AWS S3).
- `local`: carpeta `data/` con la misma estructura de claves, como respaldo de desarrollo
  cuando no hay un servicio S3 en la máquina.

Claves: `uploads/<proyecto>/<dataset>.csv` y `models/<proyecto>/<nombre>/v<N>/<archivo>`.
"""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import settings


class ObjectNotFound(FileNotFoundError):
    pass


class ObjectStore(Protocol):
    backend: str

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def list(self, prefix: str) -> list[str]: ...
    def delete_prefix(self, prefix: str) -> int: ...
    def total_bytes(self) -> int: ...


def _safe(key: str) -> str:
    """Las claves las genera la API, pero se rechaza cualquier intento de salir del almacén."""
    clean = key.strip("/")
    if not clean or ".." in clean.split("/") or "\\" in clean:
        raise ValueError(f"Clave de objeto no válida: {key!r}")
    return clean


class LocalObjectStore:
    backend = "local"

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / _safe(key)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)  # escritura atómica: nunca queda un objeto a medias

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list(self, prefix: str) -> list[str]:
        base = self._path(prefix)
        if not base.is_dir():
            return []
        return sorted(p.relative_to(self.root).as_posix() for p in base.rglob("*") if p.is_file())

    def delete_prefix(self, prefix: str) -> int:
        keys = self.list(prefix)
        shutil.rmtree(self._path(prefix), ignore_errors=True)
        return len(keys)

    def total_bytes(self) -> int:
        return sum(p.stat().st_size for folder in ("uploads", "models") if (self.root / folder).is_dir()
                   for p in (self.root / folder).rglob("*") if p.is_file())


class S3ObjectStore:
    backend = "s3"

    def __init__(self, bucket: str, client) -> None:
        self.bucket = bucket
        self.client = client
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(Bucket=self.bucket, Key=_safe(key), Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            return self.client.get_object(Bucket=self.bucket, Key=_safe(key))["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise ObjectNotFound(key) from exc
            raise

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=_safe(key))
            return True
        except ClientError:
            return False

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_safe(key))

    def _objects(self, prefix: str = ""):
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            yield from page.get("Contents", [])

    def list(self, prefix: str) -> list[str]:
        return sorted(obj["Key"] for obj in self._objects(_safe(prefix) + "/"))

    def delete_prefix(self, prefix: str) -> int:
        keys = self.list(prefix)
        for start in range(0, len(keys), 1000):
            chunk = [{"Key": key} for key in keys[start:start + 1000]]
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": chunk})
        return len(keys)

    def total_bytes(self) -> int:
        return sum(obj["Size"] for obj in self._objects())


@lru_cache(maxsize=1)
def get_store() -> ObjectStore:
    if settings.storage_backend == "s3":
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint or None,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
            region_name=settings.s3_region,
            # Compatibilidad con servicios S3 propios (SeaweedFS, MinIO): rutas en lugar de
            # subdominios y sin las sumas de verificación que boto3 ≥ 1.36 exige por defecto.
            config=Config(
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                retries={"max_attempts": 5, "mode": "standard"},
            ),
        )
        return S3ObjectStore(settings.s3_bucket, client)
    return LocalObjectStore(settings.data_dir)
