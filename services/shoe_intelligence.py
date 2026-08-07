from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from services.state_store import database_path, load_state


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(database_path(), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _norm(value: Any) -> str:
    text = str(value or "").casefold().strip()
    text = re.sub(r"[^a-z0-9áéíóúüñ+#.-]+", " ", text)
    return " ".join(text.split())


SEED_MODELS = [
    ("Nike","Air Force","Air Force 1 Low",["AF1","Air Force One"]),
    ("Nike","Air Max","Air Max 1",["AM1"]),
    ("Nike","Air Max","Air Max 90",["AM90"]),
    ("Nike","Air Max","Air Max 95",["AM95"]),
    ("Nike","Air Max","Air Max 97",["AM97"]),
    ("Nike","Air Max","Air Max Plus",["TN","Tuned Air"]),
    ("Nike","Dunk","Dunk Low",["Nike Dunk Low"]),
    ("Nike","Dunk","Dunk High",["Nike Dunk High"]),
    ("Nike","Blazer","Blazer Mid '77",["Blazer Mid"]),
    ("Nike","Pegasus","Air Zoom Pegasus",["Pegasus"]),
    ("Nike","Vapormax","Air VaporMax",["VaporMax"]),
    ("Jordan","Air Jordan","Air Jordan 1 Low",["Jordan 1 Low","AJ1 Low"]),
    ("Jordan","Air Jordan","Air Jordan 1 Mid",["Jordan 1 Mid","AJ1 Mid"]),
    ("Jordan","Air Jordan","Air Jordan 1 High",["Jordan 1 High","AJ1 High"]),
    ("Jordan","Air Jordan","Air Jordan 3 Retro",["Jordan 3","AJ3"]),
    ("Jordan","Air Jordan","Air Jordan 4 Retro",["Jordan 4","AJ4"]),
    ("Jordan","Air Jordan","Air Jordan 5 Retro",["Jordan 5","AJ5"]),
    ("Jordan","Air Jordan","Air Jordan 6 Retro",["Jordan 6","AJ6"]),
    ("Jordan","Air Jordan","Air Jordan 11 Retro",["Jordan 11","AJ11"]),
    ("Adidas","Originals","Samba OG",["Samba"]),
    ("Adidas","Originals","Gazelle",["Adidas Gazelle"]),
    ("Adidas","Originals","Campus 00s",["Campus"]),
    ("Adidas","Superstar","Superstar",["Shell Toe"]),
    ("Adidas","Forum","Forum Low",["Adidas Forum Low"]),
    ("Adidas","Ultraboost","Ultraboost",["Ultra Boost"]),
    ("Adidas","Yeezy","Yeezy Boost 350 V2",["350 V2"]),
    ("Adidas","Yeezy","Yeezy 500",["Yeezy 500"]),
    ("New Balance","99X","990",["NB 990"]),
    ("New Balance","99X","991",["NB 991"]),
    ("New Balance","99X","992",["NB 992"]),
    ("New Balance","99X","993",["NB 993"]),
    ("New Balance","Lifestyle","550",["NB 550"]),
    ("New Balance","Lifestyle","574",["NB 574"]),
    ("New Balance","Lifestyle","9060",["NB 9060"]),
    ("New Balance","Lifestyle","2002R",["NB 2002R"]),
    ("Puma","Suede","Suede Classic",["Puma Suede"]),
    ("Puma","RS","RS-X",["Puma RSX"]),
    ("Puma","Speedcat","Speedcat OG",["Speedcat"]),
    ("ASICS","GEL","GEL-Kayano 14",["Kayano 14"]),
    ("ASICS","GEL","GEL-NYC",["Gel NYC"]),
    ("ASICS","GEL","GEL-1130",["Gel 1130"]),
    ("Reebok","Classic","Classic Leather",["Reebok Classic"]),
    ("Reebok","Club C","Club C 85",["Club C"]),
    ("Converse","Chuck Taylor","Chuck Taylor All Star High",["Chuck Taylor High","All Star High"]),
    ("Converse","Chuck Taylor","Chuck Taylor All Star Low",["Chuck Taylor Low","All Star Low"]),
    ("Vans","Old Skool","Old Skool",["Vans Old Skool"]),
    ("Vans","Sk8","Sk8-Hi",["Vans Sk8 Hi"]),
    ("Vans","Slip-On","Classic Slip-On",["Vans Slip On"]),
    ("Timberland","Premium Boot","6-Inch Premium Waterproof Boot",["6 Inch Premium","Yellow Boot"]),
    ("Timberland","Field Boot","Field Boot",["Timberland Field Boot"]),
    ("Dr. Martens","1460","1460 Boot",["Doc Martens 1460"]),
    ("Dr. Martens","1461","1461 Oxford",["Doc Martens 1461"]),
    ("Crocs","Clog","Classic Clog",["Crocs Classic"]),
    ("Skechers","D'Lites","D'Lites",["Skechers D Lites"]),
    ("Skechers","Go Walk","GO WALK",["Go Walk"]),
    ("Under Armour","Curry","Curry Flow",["UA Curry"]),
    ("Salomon","XT","XT-6",["Salomon XT6"]),
    ("Hoka","Clifton","Clifton",["Hoka Clifton"]),
    ("Hoka","Bondi","Bondi",["Hoka Bondi"]),
    ("On","Cloud","Cloud 5",["On Cloud 5"]),
    ("On","Cloudmonster","Cloudmonster",["On Cloudmonster"]),
    ("Balenciaga","Triple S","Triple S",["Balenciaga Triple S"]),
    ("Balenciaga","Track","Track",["Balenciaga Track"]),
    ("Gucci","Ace","Ace Sneaker",["Gucci Ace"]),
    ("Louis Vuitton","LV Trainer","LV Trainer",["Louis Vuitton Trainer"]),
    ("Dior","B27","B27 Sneaker",["Dior B27"]),
]


def migrate_shoe_intelligence() -> dict[str, Any]:
    with _connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS shoe_master_models(
          id TEXT PRIMARY KEY,
          brand TEXT NOT NULL,
          family TEXT NOT NULL DEFAULT '',
          model TEXT NOT NULL,
          colorway TEXT NOT NULL DEFAULT '',
          sku TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT 'Calzado',
          subcategory TEXT NOT NULL DEFAULT 'Tenis',
          aliases_json TEXT NOT NULL DEFAULT '[]',
          source TEXT NOT NULL DEFAULT 'seed',
          confidence REAL NOT NULL DEFAULT 1.0,
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(brand,model,colorway,sku)
        );
        CREATE INDEX IF NOT EXISTS idx_shoe_master_brand_model ON shoe_master_models(brand,model);
        CREATE INDEX IF NOT EXISTS idx_shoe_master_sku ON shoe_master_models(sku);
        CREATE TABLE IF NOT EXISTS shoe_intelligence_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          kind TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );
        """)
        stamp = _now()
        for brand, family, model, aliases in SEED_MODELS:
            c.execute(
                """INSERT OR IGNORE INTO shoe_master_models
                (id,brand,family,model,aliases_json,source,confidence,active,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex,brand,family,model,json.dumps(aliases,ensure_ascii=False),
                 "universal_seed",1.0,1,stamp,stamp),
            )
        c.commit()
    return stats()


def stats() -> dict[str, Any]:
    with _connect() as c:
        total = c.execute("SELECT COUNT(*) FROM shoe_master_models WHERE active=1").fetchone()[0]
        brands = c.execute("SELECT COUNT(DISTINCT brand) FROM shoe_master_models WHERE active=1").fetchone()[0]
        learned = c.execute("SELECT COUNT(*) FROM shoe_master_models WHERE active=1 AND source='catalog_learning'").fetchone()[0]
    return {"status":"ok","models":total,"brands":brands,"learnedFromCatalog":learned}


def _score(query: str, row: dict[str, Any]) -> float:
    q = _norm(query)
    if not q:
        return 0.0
    fields = [
        row.get("brand",""), row.get("family",""), row.get("model",""),
        row.get("colorway",""), row.get("sku",""),
        *(row.get("aliases") or []),
    ]
    norms = [_norm(x) for x in fields if str(x or "").strip()]
    if any(q == x for x in norms):
        return 1.0
    q_tokens = set(q.split())
    best = 0.0
    for text in norms:
        tokens = set(text.split())
        if not tokens:
            continue
        inter = len(q_tokens & tokens)
        union = len(q_tokens | tokens)
        token_score = inter / union if union else 0.0
        contains = 0.35 if q in text or text in q else 0.0
        best = max(best, min(0.99, token_score + contains))
    return best


def search_candidates(query: str, brand: str = "", limit: int = 12) -> dict[str, Any]:
    migrate_shoe_intelligence()
    with _connect() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM shoe_master_models WHERE active=1").fetchall()]
    results = []
    brand_n = _norm(brand)
    for row in rows:
        if brand_n and _norm(row.get("brand")) != brand_n:
            continue
        try:
            row["aliases"] = json.loads(row.pop("aliases_json") or "[]")
        except Exception:
            row["aliases"] = []
        score = _score(query, row)
        if score <= 0:
            continue
        row["score"] = round(score, 4)
        results.append(row)
    results.sort(key=lambda x: (x["score"], x.get("confidence",0)), reverse=True)
    return {"status":"ok","query":query,"items":results[:max(1,min(int(limit),50))]}


def upsert_model(payload: dict[str, Any], source: str = "manual") -> dict[str, Any]:
    migrate_shoe_intelligence()
    brand = str(payload.get("brand") or "").strip()
    model = str(payload.get("model") or payload.get("name") or "").strip()
    if not brand or not model:
        raise ValueError("Marca y modelo son obligatorios.")
    family = str(payload.get("family") or "").strip()
    colorway = str(payload.get("colorway") or payload.get("color") or "").strip()
    sku = str(payload.get("sku") or payload.get("styleCode") or "").strip()
    aliases = payload.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [x.strip() for x in aliases.split(",") if x.strip()]
    stamp = _now()
    with _connect() as c:
        existing = c.execute(
            "SELECT id FROM shoe_master_models WHERE lower(brand)=lower(?) AND lower(model)=lower(?) AND lower(colorway)=lower(?) AND lower(sku)=lower(?)",
            (brand,model,colorway,sku),
        ).fetchone()
        mid = existing["id"] if existing else uuid.uuid4().hex
        if existing:
            c.execute(
                """UPDATE shoe_master_models SET family=?,category=?,subcategory=?,aliases_json=?,source=?,confidence=?,active=1,updated_at=? WHERE id=?""",
                (family,str(payload.get("category") or "Calzado"),str(payload.get("subcategory") or "Tenis"),
                 json.dumps(aliases,ensure_ascii=False),source,float(payload.get("confidence") or 1.0),stamp,mid),
            )
        else:
            c.execute(
                """INSERT INTO shoe_master_models
                (id,brand,family,model,colorway,sku,category,subcategory,aliases_json,source,confidence,active,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (mid,brand,family,model,colorway,sku,str(payload.get("category") or "Calzado"),
                 str(payload.get("subcategory") or "Tenis"),json.dumps(aliases,ensure_ascii=False),
                 source,float(payload.get("confidence") or 1.0),1,stamp,stamp),
            )
        c.commit()
    return {"status":"ok","id":mid,"brand":brand,"model":model}


def learn_from_catalog() -> dict[str, Any]:
    migrate_shoe_intelligence()
    state = load_state()
    products = state.get("products",[]) if isinstance(state,dict) else []
    learned = skipped = 0
    for product in products:
        if not isinstance(product,dict):
            continue
        brand = str(product.get("brand") or "").strip()
        model = str(product.get("model") or "").strip()
        title = str(product.get("title") or product.get("name") or "").strip()
        if not brand or not model or model.casefold() in {"pendiente","modelo pendiente","por confirmar"}:
            skipped += 1
            continue
        aliases = [title] if title and _norm(title) != _norm(model) else []
        upsert_model({
            "brand": brand,
            "model": model,
            "family": product.get("family") or "",
            "colorway": product.get("colorway") or product.get("color") or "",
            "sku": product.get("sku") or product.get("styleCode") or "",
            "category": product.get("category") or "Calzado",
            "subcategory": product.get("subcategory") or "Tenis",
            "aliases": aliases,
            "confidence": 1.0,
        }, source="catalog_learning")
        learned += 1
    result = stats()
    result.update({"status":"ok","learned":learned,"skipped":skipped})
    return result
