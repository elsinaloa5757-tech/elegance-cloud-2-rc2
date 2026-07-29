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
    con = sqlite3.connect(_DB, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "CREATE TABLE IF NOT EXISTS product_history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT NOT NULL, "
        "event_type TEXT NOT NULL, before_json TEXT NOT NULL DEFAULT '{}', "
        "after_json TEXT NOT NULL DEFAULT '{}', note TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_product_history_product "
        "ON product_history(product_id, created_at DESC)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS correction_memory ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, original_brand TEXT NOT NULL DEFAULT '', "
        "original_model TEXT NOT NULL DEFAULT '', corrected_brand TEXT NOT NULL, "
        "corrected_model TEXT NOT NULL DEFAULT '', uses INTEGER NOT NULL DEFAULT 1, "
        "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(original_brand, original_model, corrected_brand, corrected_model))"
    )
    return con


def _safe_json(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def record_event(
    *,
    product_id: str,
    event_type: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    note: str = "",
) -> None:
    if not product_id:
        return
    with _LOCK, _connect() as con:
        con.execute(
            "INSERT INTO product_history(product_id,event_type,before_json,after_json,note) "
            "VALUES(?,?,?,?,?)",
            (product_id, event_type, _safe_json(before), _safe_json(after), note.strip()),
        )
        con.commit()


def remember_correction(
    *, original_brand: str, original_model: str, corrected_brand: str, corrected_model: str
) -> None:
    corrected_brand = corrected_brand.strip()
    corrected_model = corrected_model.strip()
    if not corrected_brand:
        return
    with _LOCK, _connect() as con:
        con.execute(
            "INSERT INTO correction_memory(original_brand,original_model,corrected_brand,corrected_model) "
            "VALUES(?,?,?,?) ON CONFLICT(original_brand,original_model,corrected_brand,corrected_model) "
            "DO UPDATE SET uses=uses+1,updated_at=CURRENT_TIMESTAMP",
            (
                original_brand.strip(),
                original_model.strip(),
                corrected_brand,
                corrected_model,
            ),
        )
        con.commit()


def capture_state_changes(old_state: dict[str, Any], new_state: dict[str, Any]) -> dict[str, int]:
    old_products = {
        str(item.get("id")): item
        for item in old_state.get("products", [])
        if isinstance(item, dict) and item.get("id")
    }
    new_products = {
        str(item.get("id")): item
        for item in new_state.get("products", [])
        if isinstance(item, dict) and item.get("id")
    }
    created = updated = deleted = corrections = 0

    for product_id, after in new_products.items():
        before = old_products.get(product_id)
        if before is None:
            record_event(product_id=product_id, event_type="created", after=after)
            created += 1
            continue
        tracked = ("title", "brand", "model", "color", "stock", "price", "status", "sku")
        if any(before.get(key) != after.get(key) for key in tracked):
            record_event(product_id=product_id, event_type="updated", before=before, after=after)
            updated += 1
            old_brand = str(before.get("brand") or "")
            old_model = str(before.get("model") or "")
            new_brand = str(after.get("brand") or "")
            new_model = str(after.get("model") or "")
            if (old_brand, old_model) != (new_brand, new_model) and new_brand:
                remember_correction(
                    original_brand=old_brand,
                    original_model=old_model,
                    corrected_brand=new_brand,
                    corrected_model=new_model,
                )
                corrections += 1

    for product_id, before in old_products.items():
        if product_id not in new_products:
            record_event(product_id=product_id, event_type="deleted", before=before)
            deleted += 1

    return {"created": created, "updated": updated, "deleted": deleted, "corrections": corrections}


def recent_history(*, product_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    sql = "SELECT id,product_id,event_type,before_json,after_json,note,created_at FROM product_history"
    args: tuple[Any, ...] = ()
    if product_id:
        sql += " WHERE product_id=?"
        args = (product_id,)
    sql += " ORDER BY id DESC LIMIT ?"
    args += (limit,)
    with _LOCK, _connect() as con:
        rows = con.execute(sql, args).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            before = json.loads(row[3])
        except json.JSONDecodeError:
            before = {}
        try:
            after = json.loads(row[4])
        except json.JSONDecodeError:
            after = {}
        result.append({
            "id": row[0], "product_id": row[1], "event_type": row[2],
            "before": before, "after": after, "note": row[5], "created_at": row[6],
        })
    return result


def correction_suggestions(*, brand: str = "", model: str = "", limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    sql = (
        "SELECT original_brand,original_model,corrected_brand,corrected_model,uses,updated_at "
        "FROM correction_memory"
    )
    where: list[str] = []
    args: list[Any] = []
    if brand:
        where.append("LOWER(original_brand)=LOWER(?)")
        args.append(brand.strip())
    if model:
        where.append("LOWER(original_model)=LOWER(?)")
        args.append(model.strip())
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY uses DESC,updated_at DESC LIMIT ?"
    args.append(limit)
    with _LOCK, _connect() as con:
        rows = con.execute(sql, tuple(args)).fetchall()
    return [dict(row) for row in rows]


def memory_summary() -> dict[str, int]:
    with _LOCK, _connect() as con:
        history = int(con.execute("SELECT COUNT(*) FROM product_history").fetchone()[0])
        corrections = int(con.execute("SELECT COUNT(*) FROM correction_memory").fetchone()[0])
        learned_uses = int(con.execute("SELECT COALESCE(SUM(uses),0) FROM correction_memory").fetchone()[0])
    return {"history_events": history, "correction_rules": corrections, "correction_uses": learned_uses}
