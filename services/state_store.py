from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

from services.runtime_config import database_file
_DB = database_file()
_LOCK = Lock()


def _connect() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(_DB, timeout=20)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS app_state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    return connection


def save_state(state: dict[str, Any]) -> None:
    payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    with _LOCK, _connect() as connection:
        connection.execute(
            "INSERT INTO app_state(id,payload,updated_at) VALUES(1,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP",
            (payload,),
        )
        connection.commit()


def load_state() -> dict[str, Any]:
    with _LOCK, _connect() as connection:
        row = connection.execute("SELECT payload FROM app_state WHERE id=1").fetchone()
    if not row:
        return {}
    try:
        value = json.loads(row[0])
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def database_path() -> str:
    _connect().close()
    return str(_DB)
