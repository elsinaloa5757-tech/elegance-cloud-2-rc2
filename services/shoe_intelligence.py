from __future__ import annotations

import io
import json
import math
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from services.state_store import database_path, load_state

ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "assets" / "data" / "shoe_master_pack_v2.json"

SEED_MODELS = [
    ("Nike","Air Force","Air Force 1 Low",["AF1","Air Force One"]),
    ("Nike","Air Max","Air Max 1",["AM1"]),
    ("Nike","Air Max","Air Max 90",["AM90"]),
    ("Nike","Air Max","Air Max 95",["AM95"]),
    ("Nike","Air Max","Air Max 97",["AM97"]),
    ("Nike","Air Max","Air Max Plus",["TN","Tuned Air"]),
    ("Nike","Dunk","Dunk Low",["Nike Dunk Low"]),
    ("Nike","Dunk","Dunk High",["Nike Dunk High"]),
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
    ("New Balance","Lifestyle","550",["NB 550"]),
    ("New Balance","Lifestyle","574",["NB 574"]),
    ("New Balance","Lifestyle","9060",["NB 9060"]),
    ("New Balance","Lifestyle","2002R",["NB 2002R"]),
    ("Puma","Suede","Suede Classic",["Puma Suede"]),
    ("Puma","RS","RS-X",["Puma RSX"]),
    ("ASICS","GEL","GEL-Kayano 14",["Kayano 14"]),
    ("ASICS","GEL","GEL-NYC",["Gel NYC"]),
    ("ASICS","GEL","GEL-1130",["Gel 1130"]),
    ("Reebok","Classic","Classic Leather",["Reebok Classic"]),
    ("Converse","Chuck Taylor","Chuck Taylor All Star High",["Chuck Taylor High"]),
    ("Converse","Chuck Taylor","Chuck Taylor All Star Low",["Chuck Taylor Low"]),
    ("Vans","Old Skool","Old Skool",["Vans Old Skool"]),
    ("Vans","Sk8","Sk8-Hi",["Vans Sk8 Hi"]),
    ("Timberland","Premium Boot","6-Inch Premium Waterproof Boot",["6 Inch Premium"]),
    ("Dr. Martens","1460","1460 Boot",["Doc Martens 1460"]),
    ("Crocs","Clog","Classic Clog",["Crocs Classic"]),
    ("Salomon","XT","XT-6",["Salomon XT6"]),
    ("Hoka","Clifton","Clifton",["Hoka Clifton"]),
    ("Hoka","Bondi","Bondi",["Hoka Bondi"]),
    ("On","Cloud","Cloud 5",["On Cloud 5"]),
    ("Balenciaga","Triple S","Triple S",["Balenciaga Triple S"]),
    ("Balenciaga","Track","Track",["Balenciaga Track"]),
    ("Gucci","Ace","Ace Sneaker",["Gucci Ace"]),
    ("Louis Vuitton","LV Trainer","LV Trainer",["Louis Vuitton Trainer"]),
    ("Dior","B27","B27 Sneaker",["Dior B27"]),
]


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


def _pack() -> list[dict[str, Any]]:
    if not PACK_PATH.exists():
        return []
    try:
        data = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


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

        CREATE TABLE IF NOT EXISTS shoe_visual_memory(
          id TEXT PRIMARY KEY,
          master_id TEXT,
          brand TEXT NOT NULL,
          model TEXT NOT NULL,
          source_product_id TEXT NOT NULL DEFAULT '',
          fingerprint_json TEXT NOT NULL,
          dhash TEXT NOT NULL DEFAULT '',
          image_ref TEXT NOT NULL DEFAULT '',
          confirmed INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          FOREIGN KEY(master_id) REFERENCES shoe_master_models(id)
        );
        CREATE INDEX IF NOT EXISTS idx_shoe_visual_brand_model ON shoe_visual_memory(brand,model);
        """)

        stamp = _now()
        for brand, family, model, aliases in SEED_MODELS:
            c.execute(
                """INSERT OR IGNORE INTO shoe_master_models
                (id,brand,family,model,aliases_json,source,confidence,active,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex, brand, family, model, json.dumps(aliases,ensure_ascii=False),
                 "universal_seed",1.0,1,stamp,stamp),
            )

        for item in _pack():
            brand = str(item.get("brand") or "").strip()
            model = str(item.get("model") or "").strip()
            if not brand or not model:
                continue
            c.execute(
                """INSERT OR IGNORE INTO shoe_master_models
                (id,brand,family,model,colorway,sku,category,subcategory,aliases_json,source,confidence,active,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    uuid.uuid4().hex, brand, str(item.get("family") or ""), model,
                    str(item.get("colorway") or ""), str(item.get("sku") or ""),
                    str(item.get("category") or "Calzado"), str(item.get("subcategory") or "Tenis"),
                    json.dumps(item.get("aliases") or [],ensure_ascii=False),
                    "phase2_pack_v2",1.0,1,stamp,stamp,
                ),
            )
        c.commit()
    return stats()


def stats() -> dict[str, Any]:
    with _connect() as c:
        total = c.execute("SELECT COUNT(*) FROM shoe_master_models WHERE active=1").fetchone()[0]
        brands = c.execute("SELECT COUNT(DISTINCT brand) FROM shoe_master_models WHERE active=1").fetchone()[0]
        learned = c.execute("SELECT COUNT(*) FROM shoe_master_models WHERE active=1 AND source='catalog_learning'").fetchone()[0]
        visual = c.execute("SELECT COUNT(*) FROM shoe_visual_memory WHERE confirmed=1").fetchone()[0]
    return {"status":"ok","models":total,"brands":brands,"learnedFromCatalog":learned,"visualReferences":visual}


def _score(query: str, row: dict[str, Any]) -> float:
    q = _norm(query)
    if not q:
        return 0.0
    fields = [
        row.get("brand",""), row.get("family",""), row.get("model",""),
        row.get("colorway",""), row.get("sku",""), *(row.get("aliases") or []),
    ]
    norms = [_norm(x) for x in fields if str(x or "").strip()]
    if any(q == x for x in norms):
        return 1.0

    q_tokens = set(q.split())
    q_numbers = set(re.findall(r"\d+", q))
    best = 0.0
    for idx, text in enumerate(norms):
        tokens = set(text.split())
        if not tokens:
            continue
        inter = len(q_tokens & tokens)
        precision = inter / len(q_tokens) if q_tokens else 0.0
        recall = inter / len(tokens) if tokens else 0.0
        score = precision * 0.68 + recall * 0.22
        if q in text:
            score += 0.18
        nums = set(re.findall(r"\d+", text))
        if q_numbers:
            if nums == q_numbers:
                score += 0.22
            elif nums:
                score -= 0.48
        if idx >= 2:
            score += 0.05
        best = max(best,score)
    return max(0.0,min(0.99,best))


def search_candidates(query: str, brand: str = "", limit: int = 12) -> dict[str, Any]:
    migrate_shoe_intelligence()
    with _connect() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM shoe_master_models WHERE active=1").fetchall()]
    results=[]
    bn=_norm(brand)
    for row in rows:
        if bn and _norm(row.get("brand")) != bn:
            continue
        try:
            row["aliases"]=json.loads(row.pop("aliases_json") or "[]")
        except Exception:
            row["aliases"]=[]
        s=_score(query,row)
        if s <= 0:
            continue
        row["score"]=round(s,4)
        results.append(row)
    results.sort(key=lambda x:(x["score"],x.get("confidence",0)),reverse=True)
    return {"status":"ok","query":query,"items":results[:max(1,min(int(limit),50))]}


def upsert_model(payload: dict[str, Any], source: str = "manual") -> dict[str, Any]:
    migrate_shoe_intelligence()
    brand=str(payload.get("brand") or "").strip()
    model=str(payload.get("model") or payload.get("name") or "").strip()
    if not brand or not model:
        raise ValueError("Marca y modelo son obligatorios.")
    family=str(payload.get("family") or "").strip()
    colorway=str(payload.get("colorway") or payload.get("color") or "").strip()
    sku=str(payload.get("sku") or payload.get("styleCode") or "").strip()
    aliases=payload.get("aliases") or []
    if isinstance(aliases,str):
        aliases=[x.strip() for x in aliases.split(",") if x.strip()]
    stamp=_now()
    with _connect() as c:
        row=c.execute(
            "SELECT id FROM shoe_master_models WHERE lower(brand)=lower(?) AND lower(model)=lower(?) AND lower(colorway)=lower(?) AND lower(sku)=lower(?)",
            (brand,model,colorway,sku),
        ).fetchone()
        mid=row["id"] if row else uuid.uuid4().hex
        if row:
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
    state=load_state()
    products=state.get("products",[]) if isinstance(state,dict) else []
    learned=skipped=0
    for p in products:
        if not isinstance(p,dict):
            continue
        brand=str(p.get("brand") or "").strip()
        model=str(p.get("model") or "").strip()
        if not brand or not model or model.casefold() in {"pendiente","modelo pendiente","por confirmar"}:
            skipped+=1
            continue
        upsert_model({
            "brand":brand,"model":model,"family":p.get("family") or "",
            "colorway":p.get("colorway") or p.get("color") or "",
            "sku":p.get("sku") or p.get("styleCode") or "",
            "category":p.get("category") or "Calzado",
            "subcategory":p.get("subcategory") or "Tenis",
            "aliases":[str(p.get("title") or p.get("name") or "").strip()],
        },source="catalog_learning")
        learned+=1
    result=stats()
    result.update({"learned":learned,"skipped":skipped})
    return result


def _dhash(img: Image.Image) -> str:
    g=ImageOps.grayscale(img).resize((9,8),Image.Resampling.LANCZOS)
    px=list(g.getdata())
    bits=[]
    for y in range(8):
        base=y*9
        for x in range(8):
            bits.append(1 if px[base+x] > px[base+x+1] else 0)
    value=0
    for bit in bits:
        value=(value<<1)|bit
    return f"{value:016x}"


def _fingerprint(img: Image.Image) -> list[float]:
    im=ImageOps.exif_transpose(img).convert("RGB")
    im.thumbnail((512,512),Image.Resampling.LANCZOS)
    # coarse visual descriptor: 8x8 RGB + grayscale edge profile
    small=im.resize((8,8),Image.Resampling.LANCZOS)
    vec=[]
    for r,g,b in list(small.getdata()):
        vec.extend((r/255.0,g/255.0,b/255.0))
    gray=ImageOps.grayscale(im).resize((16,16),Image.Resampling.LANCZOS)
    vals=list(gray.getdata())
    for y in range(16):
        for x in range(15):
            vec.append((vals[y*16+x+1]-vals[y*16+x])/255.0)
    norm=math.sqrt(sum(v*v for v in vec)) or 1.0
    return [round(v/norm,6) for v in vec]


def _cos(a:list[float],b:list[float]) -> float:
    n=min(len(a),len(b))
    if not n:
        return 0.0
    return sum(a[i]*b[i] for i in range(n))


def _ham(a:str,b:str) -> int:
    try:
        return (int(a,16)^int(b,16)).bit_count()
    except Exception:
        return 64


def remember_visual(image_bytes: bytes, brand: str, model: str, source_product_id: str = "", image_ref: str = "") -> dict[str,Any]:
    migrate_shoe_intelligence()
    if not brand.strip() or not model.strip():
        raise ValueError("Marca y modelo son obligatorios para aprender visualmente.")
    img=Image.open(io.BytesIO(image_bytes))
    img.load()
    fp=_fingerprint(img)
    dh=_dhash(img)
    with _connect() as c:
        master=c.execute(
            "SELECT id FROM shoe_master_models WHERE lower(brand)=lower(?) AND lower(model)=lower(?) ORDER BY confidence DESC LIMIT 1",
            (brand,model),
        ).fetchone()
        mid=master["id"] if master else upsert_model({"brand":brand,"model":model},source="visual_learning")["id"]
        rid=uuid.uuid4().hex
        c.execute(
            """INSERT INTO shoe_visual_memory(id,master_id,brand,model,source_product_id,fingerprint_json,dhash,image_ref,confirmed,created_at)
            VALUES(?,?,?,?,?,?,?,?,1,?)""",
            (rid,mid,brand,model,source_product_id,json.dumps(fp),dh,image_ref,_now()),
        )
        c.commit()
    return {"status":"ok","visualId":rid,"brand":brand,"model":model}


def recognize_visual(image_bytes: bytes, limit: int = 8) -> dict[str,Any]:
    migrate_shoe_intelligence()
    img=Image.open(io.BytesIO(image_bytes))
    img.load()
    qfp=_fingerprint(img)
    qdh=_dhash(img)
    with _connect() as c:
        rows=[dict(r) for r in c.execute("SELECT * FROM shoe_visual_memory WHERE confirmed=1").fetchall()]
    by_model={}
    for row in rows:
        try:
            fp=json.loads(row["fingerprint_json"])
        except Exception:
            continue
        cos=max(0.0,min(1.0,_cos(qfp,fp)))
        h=_ham(qdh,row.get("dhash") or "")
        hash_score=max(0.0,1.0-h/64.0)
        visual=cos*0.78+hash_score*0.22
        key=(row["brand"],row["model"])
        prev=by_model.get(key)
        if prev is None or visual>prev:
            by_model[key]=visual
    items=[
        {"brand":k[0],"model":k[1],"visualScore":round(v,4)}
        for k,v in by_model.items()
    ]
    items.sort(key=lambda x:x["visualScore"],reverse=True)
    return {
        "status":"ok",
        "references":len(rows),
        "items":items[:max(1,min(int(limit),25))],
        "message":"Sin referencias visuales confirmadas todavía." if not rows else "",
    }
