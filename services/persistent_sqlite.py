from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.runtime_config import database_file

_SNAPSHOT_ID = "main"
_LOCK_ID = 7_575_702_002
_SKIP_PREFIXES = (
    "/assets/",
    "/favicon",
    "/manifest.webmanifest",
    "/robots.txt",
    "/sw.js",
)
_SKIP_EXACT = {"/health", "/api/health"}


def enabled() -> bool:
    return bool(os.getenv("DATABASE_URL", "").strip())


def should_sync(path: str) -> bool:
    if not enabled():
        return False
    return path not in _SKIP_EXACT and not any(path.startswith(prefix) for prefix in _SKIP_PREFIXES)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _remove_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")
        try:
            sidecar.unlink()
        except FileNotFoundError:
            pass


def _restore(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _remove_sidecars(path)
    temporary = path.with_suffix(path.suffix + ".hydrate")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _snapshot(path: Path) -> bytes:
    if not path.exists():
        return b""
    with sqlite3.connect(path, timeout=30) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return path.read_bytes()


@dataclass
class LeaseStatus:
    enabled: bool
    hydrated: bool = False
    persisted: bool = False
    revision: int = 0
    size_bytes: int = 0
    sha256: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "hydrated": self.hydrated,
            "persisted": self.persisted,
            "revision": self.revision,
            "sizeBytes": self.size_bytes,
            "sha256": self.sha256,
        }


class PersistentSQLiteLease:
    """Serialize one Elegance request around a durable SQLite snapshot.

    A transaction-scoped Postgres advisory lock prevents two serverless
    instances from updating the same SQLite database concurrently.
    """

    def __init__(self) -> None:
        self.status = LeaseStatus(enabled=enabled())
        self._connection: Any = None
        self._path = database_file()

    def __enter__(self) -> LeaseStatus:
        if not self.status.enabled:
            return self.status

        import psycopg

        self._connection = psycopg.connect(
            os.environ["DATABASE_URL"].strip(),
            autocommit=False,
            prepare_threshold=None,
            connect_timeout=10,
            application_name="elegance-vercel",
        )
        cursor = self._connection.cursor()
        cursor.execute("select pg_advisory_xact_lock(%s)", (_LOCK_ID,))
        cursor.execute(
            "select revision, sqlite_blob, sha256, size_bytes "
            "from elegance_private.runtime_databases where id=%s for update",
            (_SNAPSHOT_ID,),
        )
        row = cursor.fetchone()
        if row:
            revision, payload, digest, size_bytes = row
            data = bytes(payload)
            if len(data) != int(size_bytes) or _sha256(data) != str(digest):
                raise RuntimeError("La instantánea persistente de Elegance no superó la verificación de integridad.")
            _restore(self._path, data)
            self.status.hydrated = True
            self.status.revision = int(revision)
            self.status.size_bytes = len(data)
            self.status.sha256 = str(digest)
        return self.status

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        del traceback
        if not self.status.enabled or self._connection is None:
            return False
        try:
            if exc_type is None:
                payload = _snapshot(self._path)
                if payload:
                    digest = _sha256(payload)
                    cursor = self._connection.cursor()
                    cursor.execute(
                        "insert into elegance_private.runtime_databases"
                        "(id,revision,sqlite_blob,sha256,size_bytes,source,created_at,updated_at) "
                        "values (%s,1,%s,%s,%s,'vercel',now(),now()) "
                        "on conflict (id) do update set "
                        "revision=elegance_private.runtime_databases.revision+1,"
                        "sqlite_blob=excluded.sqlite_blob,sha256=excluded.sha256,"
                        "size_bytes=excluded.size_bytes,source=excluded.source,updated_at=now() "
                        "returning revision",
                        (_SNAPSHOT_ID, payload, digest, len(payload)),
                    )
                    self.status.revision = int(cursor.fetchone()[0])
                    self.status.persisted = True
                    self.status.size_bytes = len(payload)
                    self.status.sha256 = digest
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self._connection.close()
            self._connection = None
        return False

