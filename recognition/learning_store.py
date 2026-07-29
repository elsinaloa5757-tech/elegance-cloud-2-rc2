from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import numpy as np

from services.runtime_config import database_file

_DB = database_file()
_LOCK = Lock()

@dataclass(frozen=True)
class LearnedMatch:
    brand: str
    model: str
    title: str
    sku: str
    similarity: float


def _connect() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(_DB, timeout=20)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "CREATE TABLE IF NOT EXISTS recognition_samples ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, brand TEXT NOT NULL, model TEXT NOT NULL, "
        "title TEXT NOT NULL, sku TEXT NOT NULL DEFAULT '', embedding BLOB NOT NULL, "
        "dimension INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_recognition_brand ON recognition_samples(brand)")
    return con


def save_sample(*, brand: str, model: str, title: str, sku: str, embedding: np.ndarray) -> None:
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    vector /= np.clip(np.linalg.norm(vector), 1e-12, None)
    with _LOCK, _connect() as con:
        con.execute(
            "INSERT INTO recognition_samples(brand,model,title,sku,embedding,dimension) VALUES(?,?,?,?,?,?)",
            (brand.strip(), model.strip(), title.strip(), sku.strip(), vector.tobytes(), int(vector.size)),
        )
        con.commit()


def best_match(embedding: np.ndarray, *, brand: str | None = None) -> LearnedMatch | None:
    query = np.asarray(embedding, dtype=np.float32).reshape(-1)
    query /= np.clip(np.linalg.norm(query), 1e-12, None)
    sql = "SELECT brand,model,title,sku,embedding,dimension FROM recognition_samples"
    args: tuple[object, ...] = ()
    if brand and brand not in {"Unknown", ""}:
        sql += " WHERE brand=?"
        args = (brand,)
    with _LOCK, _connect() as con:
        rows = con.execute(sql, args).fetchall()
    best: LearnedMatch | None = None
    for row in rows:
        vector = np.frombuffer(row[4], dtype=np.float32, count=int(row[5]))
        if vector.size != query.size:
            continue
        similarity = float(np.dot(query, vector))
        if best is None or similarity > best.similarity:
            best = LearnedMatch(row[0], row[1], row[2], row[3], similarity)
    return best


def sample_count() -> int:
    with _LOCK, _connect() as con:
        return int(con.execute("SELECT COUNT(*) FROM recognition_samples").fetchone()[0])
