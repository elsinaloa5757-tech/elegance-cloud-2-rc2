from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class CloudDatabaseStatus:
    configured: bool
    reachable: bool
    provider: str
    detail: str

    def as_dict(self) -> dict:
        return {
            "configured": self.configured,
            "reachable": self.reachable,
            "provider": self.provider,
            "detail": self.detail,
        }


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def safe_database_label(url: str) -> str:
    if not url:
        return "not-configured"
    parsed = urlparse(url)
    host = parsed.hostname or "unknown-host"
    database = (parsed.path or "/").lstrip("/") or "unknown-db"
    return f"{parsed.scheme}://{host}/{database}"


def check_cloud_database(connect_timeout: int = 5) -> CloudDatabaseStatus:
    url = database_url()
    if not url:
        return CloudDatabaseStatus(False, False, "none", "DATABASE_URL no está configurada.")
    scheme = urlparse(url).scheme.lower()
    if scheme not in {"postgres", "postgresql"}:
        return CloudDatabaseStatus(True, False, scheme or "unknown", "DATABASE_URL debe apuntar a PostgreSQL.")
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=connect_timeout) as conn:
            with conn.cursor() as cur:
                cur.execute("select current_database(), current_user, version()")
                db, user, version = cur.fetchone()
        return CloudDatabaseStatus(True, True, "postgresql", f"Conectado a {db} como {user}; {version.split(',')[0]}.")
    except Exception as exc:
        return CloudDatabaseStatus(True, False, "postgresql", f"No disponible: {type(exc).__name__}: {exc}")
