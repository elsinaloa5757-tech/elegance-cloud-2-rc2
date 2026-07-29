from __future__ import annotations

import re
import sqlite3
import threading
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from services.runtime_config import data_dir

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = data_dir()
DB_PATH = DATA_DIR / "fashion_library.sqlite3"
SCHEMA_VERSION = 1
LIBRARY_VERSION = "2026.07-sprint2-rc1"
_LOCK = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().strip()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def slugify(value: str) -> str:
    return normalize_text(value).replace(" ", "-") or "sin-nombre"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA temp_store=MEMORY")
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS library_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  parent_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  normalized_name TEXT NOT NULL,
  level INTEGER NOT NULL DEFAULT 0,
  sort_order INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id, sort_order, name);
CREATE INDEX IF NOT EXISTS idx_categories_normalized ON categories(normalized_name);

CREATE TABLE IF NOT EXISTS brands (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  normalized_name TEXT NOT NULL,
  country TEXT NOT NULL DEFAULT '',
  website TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_brands_normalized ON brands(normalized_name);

CREATE TABLE IF NOT EXISTS brand_categories (
  brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  PRIMARY KEY(brand_id, category_id)
);
CREATE INDEX IF NOT EXISTS idx_brand_categories_category ON brand_categories(category_id, brand_id);

CREATE TABLE IF NOT EXISTS families (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  slug TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(brand_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_families_brand ON families(brand_id, normalized_name);
CREATE INDEX IF NOT EXISTS idx_families_category ON families(category_id);

CREATE TABLE IF NOT EXISTS models (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id INTEGER REFERENCES families(id) ON DELETE SET NULL,
  brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
  category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  slug TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  model_code TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  release_year INTEGER,
  confidence REAL NOT NULL DEFAULT 1.0,
  source TEXT NOT NULL DEFAULT 'seed',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(brand_id, slug, model_code)
);
CREATE INDEX IF NOT EXISTS idx_models_brand ON models(brand_id, normalized_name);
CREATE INDEX IF NOT EXISTS idx_models_family ON models(family_id);
CREATE INDEX IF NOT EXISTS idx_models_category ON models(category_id);
CREATE INDEX IF NOT EXISTS idx_models_code ON models(model_code);

CREATE TABLE IF NOT EXISTS variants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  slug TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  sku TEXT NOT NULL DEFAULT '',
  colorway TEXT NOT NULL DEFAULT '',
  materials TEXT NOT NULL DEFAULT '',
  size_system TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 1.0,
  source TEXT NOT NULL DEFAULT 'seed',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(model_id, slug, sku)
);
CREATE INDEX IF NOT EXISTS idx_variants_model ON variants(model_id, normalized_name);
CREATE INDEX IF NOT EXISTS idx_variants_sku ON variants(sku);

CREATE TABLE IF NOT EXISTS change_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type TEXT NOT NULL,
  entity_id INTEGER,
  operation TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  library_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_change_log_since ON change_log(id, created_at);
"""

CATEGORY_TREE = {
    "Calzado": ["Sneakers", "Botas", "Botines", "Zapatos", "Sandalias", "Tacones", "Mocasines"],
    "Ropa": ["Playeras", "Camisas", "Sudaderas", "Chamarras", "Pantalones", "Jeans", "Shorts", "Vestidos", "Faldas"],
    "Bolsas": ["Bolsos", "Mochilas", "Crossbody", "Tote", "Clutch", "Carteras"],
    "Accesorios": ["Gorras", "Cinturones", "Lentes", "Bufandas", "Guantes", "Llaveros"],
    "Joyería": ["Relojes", "Pulseras", "Collares", "Anillos", "Aretes"],
    "Equipaje": ["Maletas", "Carry-on", "Duffles", "Organizadores"],
    "Otros": ["Coleccionables", "Cuidado del producto", "Empaque"]
}

BRANDS = {
    "Nike": ["Calzado", "Ropa", "Accesorios"], "Jordan": ["Calzado", "Ropa", "Accesorios"],
    "Adidas": ["Calzado", "Ropa", "Accesorios"], "New Balance": ["Calzado", "Ropa"],
    "Puma": ["Calzado", "Ropa", "Accesorios"], "Reebok": ["Calzado", "Ropa"],
    "Converse": ["Calzado", "Ropa"], "Vans": ["Calzado", "Ropa", "Accesorios"],
    "Timberland": ["Calzado", "Ropa", "Accesorios"], "Dr. Martens": ["Calzado", "Accesorios"],
    "Louis Vuitton": ["Calzado", "Ropa", "Bolsas", "Accesorios", "Joyería", "Equipaje"],
    "Gucci": ["Calzado", "Ropa", "Bolsas", "Accesorios", "Joyería", "Equipaje"],
    "Dior": ["Calzado", "Ropa", "Bolsas", "Accesorios", "Joyería"],
    "Prada": ["Calzado", "Ropa", "Bolsas", "Accesorios", "Equipaje"],
    "Balenciaga": ["Calzado", "Ropa", "Bolsas", "Accesorios"],
    "Burberry": ["Calzado", "Ropa", "Bolsas", "Accesorios"],
    "Versace": ["Calzado", "Ropa", "Bolsas", "Accesorios", "Joyería"],
    "Hermès": ["Calzado", "Ropa", "Bolsas", "Accesorios", "Joyería", "Equipaje"],
    "Chanel": ["Calzado", "Ropa", "Bolsas", "Accesorios", "Joyería"],
    "Cartier": ["Joyería", "Accesorios"], "Rolex": ["Joyería"], "Omega": ["Joyería"],
    "Tiffany & Co.": ["Joyería", "Accesorios"], "Bvlgari": ["Joyería", "Accesorios"],
    "Coach": ["Calzado", "Bolsas", "Accesorios"], "Michael Kors": ["Calzado", "Ropa", "Bolsas", "Accesorios", "Joyería"],
    "The North Face": ["Calzado", "Ropa", "Accesorios", "Equipaje"], "Columbia": ["Calzado", "Ropa", "Accesorios"],
    "Levi's": ["Calzado", "Ropa", "Accesorios"], "Ralph Lauren": ["Calzado", "Ropa", "Bolsas", "Accesorios"]
}

SEED_MODELS = [
    ("Nike", "Air Max", "Air Max 1", "Sneakers"), ("Nike", "Air Max", "Air Max 90", "Sneakers"),
    ("Nike", "Dunk", "Dunk Low", "Sneakers"), ("Nike", "Air Force", "Air Force 1 Low", "Sneakers"),
    ("Jordan", "Air Jordan", "Air Jordan 1", "Sneakers"), ("Jordan", "Air Jordan", "Air Jordan 3", "Sneakers"),
    ("Jordan", "Air Jordan", "Air Jordan 4", "Sneakers"), ("Jordan", "Air Jordan", "Air Jordan 11", "Sneakers"),
    ("Adidas", "Originals", "Samba OG", "Sneakers"), ("Adidas", "Yeezy", "Yeezy Boost 350 V2", "Sneakers"),
    ("New Balance", "Made", "990", "Sneakers"), ("New Balance", "Lifestyle", "574", "Sneakers"),
    ("Timberland", "Premium", "6-Inch Premium Waterproof Boot", "Botas"),
    ("Dr. Martens", "Originals", "1460 Boot", "Botas"),
    ("Louis Vuitton", "Keepall", "Keepall Bandoulière", "Duffles"),
    ("Louis Vuitton", "Speedy", "Speedy Bandoulière", "Bolsos"),
    ("Gucci", "GG Marmont", "GG Marmont Shoulder Bag", "Bolsos"),
    ("Chanel", "Classic", "Classic Handbag", "Bolsos"),
    ("Hermès", "Birkin", "Birkin", "Bolsos"), ("Hermès", "Kelly", "Kelly", "Bolsos"),
    ("Rolex", "Oyster Perpetual", "Submariner", "Relojes"), ("Rolex", "Oyster Perpetual", "Datejust", "Relojes"),
    ("Cartier", "Love", "Love Bracelet", "Pulseras"), ("Cartier", "Santos", "Santos de Cartier", "Relojes")
]


def initialize_library() -> dict[str, Any]:
    with _LOCK, _connect() as con:
        con.executescript(SCHEMA)
        now = _utc_now()
        con.execute("INSERT OR REPLACE INTO library_meta(key,value,updated_at) VALUES('schema_version',?,?)", (str(SCHEMA_VERSION), now))
        con.execute("INSERT OR IGNORE INTO library_meta(key,value,updated_at) VALUES('library_version',?,?)", (LIBRARY_VERSION, now))
        con.execute("INSERT OR IGNORE INTO library_meta(key,value,updated_at) VALUES('created_at',?,?)", (now, now))
        for order, (parent, children) in enumerate(CATEGORY_TREE.items(), 1):
            con.execute("INSERT OR IGNORE INTO categories(parent_id,name,slug,normalized_name,level,sort_order,created_at,updated_at) VALUES(NULL,?,?,?,?,?,?,?)",
                        (parent, slugify(parent), normalize_text(parent), 0, order, now, now))
            pid = con.execute("SELECT id FROM categories WHERE slug=?", (slugify(parent),)).fetchone()[0]
            for child_order, child in enumerate(children, 1):
                child_slug = f"{slugify(parent)}-{slugify(child)}"
                con.execute("INSERT OR IGNORE INTO categories(parent_id,name,slug,normalized_name,level,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                            (pid, child, child_slug, normalize_text(child), 1, child_order, now, now))
        for brand, categories in BRANDS.items():
            con.execute("INSERT OR IGNORE INTO brands(name,slug,normalized_name,created_at,updated_at) VALUES(?,?,?,?,?)",
                        (brand, slugify(brand), normalize_text(brand), now, now))
            bid = con.execute("SELECT id FROM brands WHERE slug=?", (slugify(brand),)).fetchone()[0]
            for category in categories:
                row = con.execute("SELECT id FROM categories WHERE parent_id IS NULL AND name=?", (category,)).fetchone()
                if row:
                    con.execute("INSERT OR IGNORE INTO brand_categories(brand_id,category_id) VALUES(?,?)", (bid, row[0]))
        for brand, family, model, subcat in SEED_MODELS:
            bid = con.execute("SELECT id FROM brands WHERE slug=?", (slugify(brand),)).fetchone()[0]
            crow = con.execute("SELECT id FROM categories WHERE level=1 AND name=?", (subcat,)).fetchone()
            cid = crow[0] if crow else None
            con.execute("INSERT OR IGNORE INTO families(brand_id,category_id,name,slug,normalized_name,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                        (bid, cid, family, slugify(family), normalize_text(family), now, now))
            fid = con.execute("SELECT id FROM families WHERE brand_id=? AND slug=?", (bid, slugify(family))).fetchone()[0]
            con.execute("INSERT OR IGNORE INTO models(family_id,brand_id,category_id,name,slug,normalized_name,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (fid, bid, cid, model, slugify(model), normalize_text(model), "sprint2_seed", now, now))
        con.commit()
    clear_cache()
    return stats()


@lru_cache(maxsize=1)
def stats() -> dict[str, Any]:
    with _connect() as con:
        counts = {}
        for table in ("categories", "brands", "families", "models", "variants", "change_log"):
            counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        meta = {r["key"]: r["value"] for r in con.execute("SELECT key,value FROM library_meta")}
    return {"database": str(DB_PATH), "schema_version": SCHEMA_VERSION, "library_version": meta.get("library_version", LIBRARY_VERSION), **counts}


def clear_cache() -> None:
    stats.cache_clear()


def category_tree() -> list[dict[str, Any]]:
    with _connect() as con:
        rows = [dict(r) for r in con.execute("SELECT id,parent_id,name,slug,level,sort_order FROM categories WHERE active=1 ORDER BY level,sort_order,name")]
    parents = []
    by_id = {}
    for row in rows:
        row["children"] = []
        by_id[row["id"]] = row
        if row["parent_id"] is None:
            parents.append(row)
    for row in rows:
        if row["parent_id"] in by_id:
            by_id[row["parent_id"]]["children"].append(row)
    return parents


def list_brands(category: str = "", q: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(int(limit), 250)); offset = max(0, int(offset))
    clauses = ["b.active=1"]; params: list[Any] = []
    joins = ""
    if category:
        joins = " JOIN brand_categories bc ON bc.brand_id=b.id JOIN categories c ON c.id=bc.category_id "
        clauses.append("(c.slug=? OR c.normalized_name=?)")
        params += [category, normalize_text(category)]
    if q:
        clauses.append("b.normalized_name LIKE ?")
        params.append(f"%{normalize_text(q)}%")
    where = " AND ".join(clauses)
    with _connect() as con:
        total = con.execute(f"SELECT COUNT(DISTINCT b.id) FROM brands b {joins} WHERE {where}", params).fetchone()[0]
        rows = [dict(r) for r in con.execute(f"SELECT DISTINCT b.id,b.name,b.slug,b.country,b.website FROM brands b {joins} WHERE {where} ORDER BY b.name LIMIT ? OFFSET ?", params+[limit,offset])]
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def search(query: str, entity: str = "all", limit: int = 30, offset: int = 0) -> dict[str, Any]:
    needle = normalize_text(query)
    limit = max(1, min(int(limit), 100)); offset = max(0, int(offset))
    if not needle:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    types = {entity} if entity in {"category","brand","family","model","variant"} else {"category","brand","family","model","variant"}
    statements=[]; params=[]
    if "category" in types:
        statements.append("SELECT 'category' entity_type,id,name,slug,'' brand,'' family,'' code FROM categories WHERE active=1 AND normalized_name LIKE ?")
        params.append(f"%{needle}%")
    if "brand" in types:
        statements.append("SELECT 'brand' entity_type,id,name,slug,name brand,'' family,'' code FROM brands WHERE active=1 AND normalized_name LIKE ?")
        params.append(f"%{needle}%")
    if "family" in types:
        statements.append("SELECT 'family' entity_type,f.id,f.name,f.slug,b.name brand,'' family,'' code FROM families f JOIN brands b ON b.id=f.brand_id WHERE f.active=1 AND f.normalized_name LIKE ?")
        params.append(f"%{needle}%")
    if "model" in types:
        statements.append("SELECT 'model' entity_type,m.id,m.name,m.slug,b.name brand,COALESCE(f.name,'') family,m.model_code code FROM models m JOIN brands b ON b.id=m.brand_id LEFT JOIN families f ON f.id=m.family_id WHERE m.active=1 AND (m.normalized_name LIKE ? OR lower(m.model_code) LIKE ?)")
        params.extend([f"%{needle}%", f"%{needle}%"])
    if "variant" in types:
        statements.append("SELECT 'variant' entity_type,v.id,v.name,v.slug,b.name brand,COALESCE(f.name,'') family,v.sku code FROM variants v JOIN models m ON m.id=v.model_id JOIN brands b ON b.id=m.brand_id LEFT JOIN families f ON f.id=m.family_id WHERE v.active=1 AND (v.normalized_name LIKE ? OR lower(v.sku) LIKE ?)")
        params.extend([f"%{needle}%", f"%{needle}%"])
    union = " UNION ALL ".join(statements)
    with _connect() as con:
        all_rows = [dict(r) for r in con.execute(union, params)]
    rank = lambda r: (0 if normalize_text(r["name"]) == needle else 1 if normalize_text(r["name"]).startswith(needle) else 2, r["entity_type"], r["name"])
    all_rows.sort(key=rank)
    return {"items": all_rows[offset:offset+limit], "total": len(all_rows), "limit": limit, "offset": offset, "query": query}


def upsert_entity(entity: str, payload: dict[str, Any]) -> dict[str, Any]:
    if entity not in {"brand", "family", "model", "variant"}:
        raise ValueError("Entidad no compatible.")
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("El nombre es obligatorio.")
    now = _utc_now(); slug = str(payload.get("slug") or slugify(name))
    with _LOCK, _connect() as con:
        if entity == "brand":
            con.execute("INSERT INTO brands(name,slug,normalized_name,country,website,created_at,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(slug) DO UPDATE SET name=excluded.name,normalized_name=excluded.normalized_name,country=excluded.country,website=excluded.website,updated_at=excluded.updated_at",
                        (name,slug,normalize_text(name),str(payload.get('country','')),str(payload.get('website','')),now,now))
            row=con.execute("SELECT * FROM brands WHERE slug=?",(slug,)).fetchone()
        elif entity == "family":
            brand_id=int(payload.get("brand_id") or 0)
            if not brand_id: raise ValueError("brand_id es obligatorio.")
            con.execute("INSERT INTO families(brand_id,category_id,name,slug,normalized_name,description,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(brand_id,slug) DO UPDATE SET name=excluded.name,normalized_name=excluded.normalized_name,category_id=excluded.category_id,description=excluded.description,updated_at=excluded.updated_at",
                        (brand_id,payload.get('category_id'),name,slug,normalize_text(name),str(payload.get('description','')),now,now))
            row=con.execute("SELECT * FROM families WHERE brand_id=? AND slug=?",(brand_id,slug)).fetchone()
        elif entity == "model":
            brand_id=int(payload.get("brand_id") or 0)
            if not brand_id: raise ValueError("brand_id es obligatorio.")
            code=str(payload.get('model_code',''))
            con.execute("INSERT INTO models(family_id,brand_id,category_id,name,slug,normalized_name,model_code,description,release_year,confidence,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(brand_id,slug,model_code) DO UPDATE SET name=excluded.name,normalized_name=excluded.normalized_name,family_id=excluded.family_id,category_id=excluded.category_id,description=excluded.description,release_year=excluded.release_year,confidence=excluded.confidence,source=excluded.source,updated_at=excluded.updated_at",
                        (payload.get('family_id'),brand_id,payload.get('category_id'),name,slug,normalize_text(name),code,str(payload.get('description','')),payload.get('release_year'),float(payload.get('confidence',1)),str(payload.get('source','manual')),now,now))
            row=con.execute("SELECT * FROM models WHERE brand_id=? AND slug=? AND model_code=?",(brand_id,slug,code)).fetchone()
        else:
            model_id=int(payload.get("model_id") or 0)
            if not model_id: raise ValueError("model_id es obligatorio.")
            sku=str(payload.get('sku',''))
            con.execute("INSERT INTO variants(model_id,name,slug,normalized_name,sku,colorway,materials,size_system,confidence,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(model_id,slug,sku) DO UPDATE SET name=excluded.name,normalized_name=excluded.normalized_name,colorway=excluded.colorway,materials=excluded.materials,size_system=excluded.size_system,confidence=excluded.confidence,source=excluded.source,updated_at=excluded.updated_at",
                        (model_id,name,slug,normalize_text(name),sku,str(payload.get('colorway','')),str(payload.get('materials','')),str(payload.get('size_system','')),float(payload.get('confidence',1)),str(payload.get('source','manual')),now,now))
            row=con.execute("SELECT * FROM variants WHERE model_id=? AND slug=? AND sku=?",(model_id,slug,sku)).fetchone()
        result=dict(row)
        con.execute("INSERT INTO change_log(entity_type,entity_id,operation,payload,library_version,created_at) VALUES(?,?,?,?,?,?)",(entity,result['id'],'upsert',str(result),LIBRARY_VERSION,now))
        con.commit()
    clear_cache()
    return result


def changes_since(since_id: int = 0, limit: int = 500) -> dict[str, Any]:
    limit=max(1,min(int(limit),1000))
    with _connect() as con:
        rows=[dict(r) for r in con.execute("SELECT * FROM change_log WHERE id>? ORDER BY id LIMIT ?",(max(0,int(since_id)),limit))]
    return {"changes":rows,"last_id":rows[-1]['id'] if rows else int(since_id),"library_version":LIBRARY_VERSION}
