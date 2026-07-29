from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.runtime_config import database_file, data_dir


def _table_count(conn: sqlite3.Connection, table: str) -> int | None:
    try:
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except sqlite3.Error:
        return None


def database_diagnostics() -> dict[str, Any]:
    path = database_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    result: dict[str, Any] = {
        "status": "ok",
        "path": str(path),
        "dataDir": str(data_dir()),
        "exists": exists,
        "size": path.stat().st_size if exists else 0,
        "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat() if exists else None,
        "walExists": Path(str(path) + '-wal').exists(),
        "shmExists": Path(str(path) + '-shm').exists(),
        "environment": {
            "serverMode": os.getenv('ELEGANCE_SERVER_MODE', ''),
            "dataDirConfigured": os.getenv('ELEGANCE_DATA_DIR', ''),
            "sqlitePathConfigured": os.getenv('ELEGANCE_SQLITE_PATH', ''),
        },
    }
    if not exists:
        result.update({"integrity": "missing", "ownerCount": 0, "productCount": None})
        return result
    try:
        with sqlite3.connect(path, timeout=10) as conn:
            result["integrity"] = conn.execute('PRAGMA integrity_check').fetchone()[0]
            result["ownerCount"] = int(conn.execute("SELECT COUNT(*) FROM auth_users WHERE role='owner' AND active=1").fetchone()[0]) if _table_count(conn, 'auth_users') is not None else 0
            result["userCount"] = _table_count(conn, 'auth_users') or 0
            result["productCount"] = _table_count(conn, 'catalog_products')
            result["journalMode"] = conn.execute('PRAGMA journal_mode').fetchone()[0]
            result["pageCount"] = int(conn.execute('PRAGMA page_count').fetchone()[0])
    except sqlite3.Error as exc:
        result.update({"status": "error", "integrity": "error", "error": str(exc)})
    return result


def database_fingerprint() -> dict[str, Any]:
    path = database_file()
    if not path.exists():
        return {"exists": False, "path": str(path)}
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {"exists": True, "path": str(path), "sha256": digest.hexdigest(), "size": path.stat().st_size}
