from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from services.state_store import database_path, load_state, save_state

LOW_STOCK_DEFAULT = 2
PROTECTED_FIELDS = {"id", "createdAt", "created_at"}


def _plain(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _products(state: dict[str, Any]) -> list[dict[str, Any]]:
    value = state.get("products", [])
    return [dict(x) for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _images(product: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key in ("imageBase64", "image_base64", "image", "imagePath", "image_path"):
        value = product.get(key)
        if isinstance(value, str) and value.strip(): result.append(value.strip())
    for key in ("galleryBase64", "gallery", "images", "imagePaths"):
        value = product.get(key)
        if isinstance(value, list): result.extend(str(x).strip() for x in value if str(x).strip())
    return list(dict.fromkeys(result))


def _image_fingerprint(value: str) -> str:
    raw = value.split(",", 1)[-1]
    try: data = base64.b64decode(raw, validate=False)
    except Exception: data = raw.encode("utf-8", "ignore")
    return hashlib.sha256(data).hexdigest()


def canonical_name(product: dict[str, Any]) -> str:
    parts = [product.get("brand"), product.get("model"), product.get("title")]
    return " ".join(x for x in (_plain(p) for p in parts) if x)


def product_quality(product: dict[str, Any], low_stock: int = LOW_STOCK_DEFAULT) -> dict[str, Any]:
    checks = {
        "title": bool(str(product.get("title") or "").strip()),
        "brand": _plain(product.get("brand")) not in {"", "sin identificar", "unknown"},
        "model": bool(str(product.get("model") or "").strip()),
        "category": bool(str(product.get("category") or "").strip()),
        "subcategory": bool(str(product.get("subcategory") or "").strip()),
        "price": float(product.get("price") or 0) > 0,
        "stock": product.get("stock") is not None,
        "size": bool(product.get("size") or product.get("sizes") or product.get("talla") or product.get("tallas")),
        "image": bool(_images(product)),
        "description": bool(str(product.get("description") or product.get("notes") or "").strip()),
        "gender": bool(str(product.get("gender") or "").strip()),
        "color": _plain(product.get("color") or product.get("primaryColor")) not in {"", "sin identificar"},
    }
    weights = {"title":10,"brand":10,"model":10,"category":8,"subcategory":6,"price":10,"stock":8,"size":8,"image":14,"description":6,"gender":5,"color":5}
    score = round(sum(weights[k] for k,v in checks.items() if v) / sum(weights.values()) * 100)
    stock = int(product.get("stock") or 0)
    issues=[]
    labels={"title":"sin nombre","brand":"sin marca","model":"sin modelo","category":"sin categoría","subcategory":"sin subcategoría","price":"sin precio","size":"sin talla","image":"sin imagen","description":"sin descripción","gender":"sin género","color":"sin color"}
    for key,label in labels.items():
        if not checks[key]: issues.append(label)
    if stock <= 0: issues.append("sin stock")
    elif stock <= low_stock: issues.append("stock bajo")
    level = "Excelente" if score >= 90 else "Bueno" if score >= 75 else "Incompleto" if score >= 50 else "Crítico"
    return {"score":score,"level":level,"checks":checks,"issues":issues,"complete":score>=90,"stockStatus":"out" if stock<=0 else "low" if stock<=low_stock else "ok"}


def find_duplicates(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups=[]; used=set()
    fingerprints={str(p.get("id",i)): {_image_fingerprint(x) for x in _images(p)} for i,p in enumerate(products)}
    for i,a in enumerate(products):
        aid=str(a.get("id",i))
        if aid in used: continue
        members=[aid]; reasons=[]
        an=canonical_name(a); asku=_plain(a.get("sku"))
        for j in range(i+1,len(products)):
            b=products[j]; bid=str(b.get("id",j))
            if bid in used: continue
            exact_image=bool(fingerprints[aid] & fingerprints[bid])
            same_sku=bool(asku and asku==_plain(b.get("sku")))
            bn=canonical_name(b); similarity=SequenceMatcher(None,an,bn).ratio() if an and bn else 0
            same_identity=similarity>=0.88 and _plain(a.get("brand"))==_plain(b.get("brand"))
            if exact_image or same_sku or same_identity:
                members.append(bid); used.add(bid)
                reasons.append("imagen exacta" if exact_image else "SKU repetido" if same_sku else f"nombre similar {similarity:.0%}")
        if len(members)>1:
            used.add(aid); groups.append({"groupId":hashlib.sha1('|'.join(members).encode()).hexdigest()[:12],"productIds":members,"reasons":sorted(set(reasons)),"confidence":1.0 if "imagen exacta" in reasons or "SKU repetido" in reasons else .88})
    return groups


def inventory_report(state: dict[str, Any], low_stock: int = LOW_STOCK_DEFAULT) -> dict[str, Any]:
    products=_products(state); enriched=[]
    for p in products:
        q=product_quality(p,low_stock); enriched.append({"id":p.get("id"),"title":p.get("title"),**q})
    duplicates=find_duplicates(products)
    return {"generatedAt":datetime.now(timezone.utc).isoformat(),"total":len(products),"complete":sum(x["complete"] for x in enriched),"critical":sum(x["level"]=="Crítico" for x in enriched),"outOfStock":sum(x["stockStatus"]=="out" for x in enriched),"lowStock":sum(x["stockStatus"]=="low" for x in enriched),"missingImages":sum(not x["checks"]["image"] for x in enriched),"missingPrice":sum(not x["checks"]["price"] for x in enriched),"duplicateGroups":len(duplicates),"averageQuality":round(sum(x["score"] for x in enriched)/len(enriched),1) if enriched else 100.0,"products":enriched,"duplicates":duplicates}


def migrate_inventory_state(state: dict[str, Any]) -> dict[str, Any]:
    migrated=deepcopy(state); products=_products(migrated)
    for p in products:
        q=product_quality(p)
        p["inventoryQuality"]=q["score"]; p["inventoryLevel"]=q["level"]; p["inventoryIssues"]=q["issues"]; p["stockStatus"]=q["stockStatus"]; p["inventoryIntelligenceVersion"]=1
    migrated["products"]=products; migrated["inventoryIntelligenceVersion"]=1
    return migrated


def _db() -> sqlite3.Connection:
    c=sqlite3.connect(database_path(),timeout=20)
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA synchronous=NORMAL"); c.execute("PRAGMA foreign_keys=ON")
    c.execute("CREATE TABLE IF NOT EXISTS inventory_backups(id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS inventory_audit(id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, product_ids TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inventory_audit_action ON inventory_audit(action)")
    return c


def backup_state(action: str, state: dict[str, Any]) -> int:
    with _db() as c:
        cur=c.execute("INSERT INTO inventory_backups(action,payload) VALUES(?,?)",(action,json.dumps(state,ensure_ascii=False)))
        c.execute("DELETE FROM inventory_backups WHERE id NOT IN (SELECT id FROM inventory_backups ORDER BY id DESC LIMIT 25)")
        return int(cur.lastrowid)


def merge_products(primary_id: str, duplicate_ids: list[str], confirm: bool=False) -> dict[str, Any]:
    state=load_state(); products=_products(state); byid={str(p.get("id")):p for p in products}
    if primary_id not in byid: raise ValueError("Producto principal inexistente")
    ids=[x for x in dict.fromkeys(duplicate_ids) if x!=primary_id]
    missing=[x for x in ids if x not in byid]
    if missing: raise ValueError("Productos inexistentes: "+", ".join(missing))
    primary=deepcopy(byid[primary_id]); merged_from=[]
    for did in ids:
        other=byid[did]; merged_from.append(did)
        for key,value in other.items():
            if key in PROTECTED_FIELDS: continue
            if key in {"galleryBase64","gallery","images","imagePaths"}:
                current=primary.get(key,[]); current=current if isinstance(current,list) else []
                incoming=value if isinstance(value,list) else []
                primary[key]=list(dict.fromkeys([*current,*incoming]))
            elif key=="stock": primary[key]=int(primary.get(key) or 0)+int(value or 0)
            elif key in {"sizes","tallas","secondaryColors"}:
                current=primary.get(key,[]); current=current if isinstance(current,list) else [current] if current else []
                incoming=value if isinstance(value,list) else [value] if value else []
                primary[key]=list(dict.fromkeys([*current,*incoming]))
            elif (primary.get(key) in (None,"",[],{})) and value not in (None,"",[],{}): primary[key]=value
        primary.setdefault("mergedProductIds",[]); primary["mergedProductIds"]=list(dict.fromkeys([*primary["mergedProductIds"],did,*other.get("mergedProductIds",[])]))
    preview={"primary":primary,"removeIds":ids,"backupRequired":True}
    if not confirm: return {"status":"preview",**preview}
    backup_id=backup_state("merge_products",state)
    state["products"]=[primary if str(p.get("id"))==primary_id else p for p in products if str(p.get("id")) not in ids]
    state=migrate_inventory_state(state); save_state(state)
    with _db() as c: c.execute("INSERT INTO inventory_audit(action,product_ids,details) VALUES(?,?,?)",("merge",json.dumps([primary_id,*ids]),json.dumps({"backupId":backup_id},ensure_ascii=False)))
    return {"status":"merged","backupId":backup_id,"primaryId":primary_id,"removedIds":ids,"state":state}


def recent_audit(limit: int=100) -> list[dict[str, Any]]:
    with _db() as c: rows=c.execute("SELECT id,action,product_ids,details,created_at FROM inventory_audit ORDER BY id DESC LIMIT ?",(max(1,min(limit,500)),)).fetchall()
    return [{"id":r[0],"action":r[1],"productIds":json.loads(r[2]),"details":json.loads(r[3]),"createdAt":r[4]} for r in rows]
