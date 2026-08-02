from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from services.state_store import database_path, load_state, save_state

KEY = "cleanup_test_catalog_20260801_rc2"

def _now():
    return datetime.now(timezone.utc).isoformat()

def run_once():
    db = Path(database_path())
    db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db, timeout=60)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL)")
        if c.execute("SELECT 1 FROM app_settings WHERE key=?", (KEY,)).fetchone():
            return {"status":"already_done"}
        state = load_state()
        if not isinstance(state, dict):
            state = {}
        backup = db.parent / f"state_before_{KEY}.json"
        backup.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        removed = len(state.get("products", [])) if isinstance(state.get("products"), list) else 0
        state["products"] = []
        save_state(state)
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        targets = [
            "product_publication","product_variants","inventory_movements","product_image_hashes",
            "recognition_reviews","recognition_corrections","product_attributes","media_assets",
            "product_media_assets","product_media_versions","catalog_events"
        ]
        cleared=[]
        for table in targets:
            if table in tables:
                c.execute(f'DELETE FROM "{table}"')
                cleared.append(table)
        c.execute("INSERT OR REPLACE INTO app_settings(key,value,updated_at) VALUES(?,?,?)",
                  (KEY,json.dumps({"removedProducts":removed,"tables":cleared}),_now()))
        c.commit()
        return {"status":"cleaned","removedProducts":removed,"tables":cleared,"backup":str(backup)}
    finally:
        c.close()
