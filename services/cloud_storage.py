from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from services.runtime_config import data_dir


@dataclass(frozen=True)
class StorageResult:
    backend: str
    path: str
    public_url: str
    sha256: str
    size: int

    def as_dict(self) -> dict:
        return {
            "backend": self.backend,
            "path": self.path,
            "publicUrl": self.public_url,
            "sha256": self.sha256,
            "size": self.size,
        }


def storage_mode() -> str:
    value = os.getenv("ELEGANCE_STORAGE_MODE", "local").strip().lower()
    return value if value in {"local", "supabase", "mirror"} else "local"


def bucket_name() -> str:
    return os.getenv("SUPABASE_STORAGE_BUCKET", "elegance-products").strip() or "elegance-products"


def _safe_object_path(value: str) -> str:
    value = value.replace("\\", "/").strip(" /")
    parts = []
    for part in value.split("/"):
        part = re.sub(r"[^A-Za-z0-9._-]+", "-", part).strip(".-")
        if part:
            parts.append(part[:120])
    if not parts:
        raise ValueError("La ruta del archivo está vacía.")
    return "/".join(parts)


def _local_write(object_path: str, content: bytes) -> StorageResult:
    root = data_dir() / "uploads"
    destination = (root / object_path).resolve()
    if root.resolve() not in destination.parents:
        raise ValueError("Ruta de almacenamiento inválida.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    relative = destination.relative_to(data_dir()).as_posix()
    return StorageResult(
        backend="local",
        path=relative,
        public_url=f"/media/{relative}",
        sha256=hashlib.sha256(content).hexdigest(),
        size=len(content),
    )


def _supabase_write(object_path: str, content: bytes, content_type: str) -> StorageResult:
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not base or not service_key:
        raise RuntimeError("Supabase Storage no está configurado.")
    bucket = urllib.parse.quote(bucket_name(), safe="")
    encoded_path = urllib.parse.quote(object_path, safe="/")
    url = f"{base}/storage/v1/object/{bucket}/{encoded_path}"
    request = urllib.request.Request(
        url,
        data=content,
        method="POST",
        headers={
            "Authorization": f"Bearer {service_key}",
            "apikey": service_key,
            "Content-Type": content_type,
            "x-upsert": "true",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status not in {200, 201}:
                raise RuntimeError(f"Supabase Storage respondió HTTP {response.status}.")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Supabase Storage rechazó el archivo: HTTP {exc.code}: {detail}") from exc
    public_url = f"{base}/storage/v1/object/public/{bucket}/{encoded_path}"
    return StorageResult(
        backend="supabase",
        path=object_path,
        public_url=public_url,
        sha256=hashlib.sha256(content).hexdigest(),
        size=len(content),
    )


def store_bytes(object_path: str, content: bytes, content_type: str = "") -> dict:
    if not content:
        raise ValueError("El archivo está vacío.")
    max_mb = max(1, int(os.getenv("ELEGANCE_MAX_UPLOAD_MB", "25")))
    if len(content) > max_mb * 1024 * 1024:
        raise ValueError(f"El archivo supera el máximo permitido de {max_mb} MB.")
    safe_path = _safe_object_path(object_path)
    content_type = content_type or mimetypes.guess_type(safe_path)[0] or "application/octet-stream"
    mode = storage_mode()
    results: list[StorageResult] = []
    if mode in {"local", "mirror"}:
        results.append(_local_write(safe_path, content))
    if mode in {"supabase", "mirror"}:
        results.append(_supabase_write(safe_path, content, content_type))
    primary = next((r for r in results if r.backend == "supabase"), results[0])
    return {
        "status": "stored",
        "mode": mode,
        "primary": primary.as_dict(),
        "copies": [r.as_dict() for r in results],
    }


def storage_status(check_remote: bool = False) -> dict:
    mode = storage_mode()
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    configured = bool(base and os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip())
    remote_reachable = None
    detail = "no comprobado"
    if check_remote and configured:
        request = urllib.request.Request(
            f"{base}/storage/v1/bucket/{urllib.parse.quote(bucket_name(), safe='')}",
            headers={
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()}",
                "apikey": os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                remote_reachable = response.status == 200
                detail = f"HTTP {response.status}"
        except Exception as exc:
            remote_reachable = False
            detail = f"{type(exc).__name__}: {exc}"
    return {
        "mode": mode,
        "bucket": bucket_name(),
        "localPath": str((data_dir() / "uploads").resolve()),
        "supabaseConfigured": configured,
        "remoteReachable": remote_reachable,
        "detail": detail,
        "maxUploadMb": max(1, int(os.getenv("ELEGANCE_MAX_UPLOAD_MB", "25"))),
    }
