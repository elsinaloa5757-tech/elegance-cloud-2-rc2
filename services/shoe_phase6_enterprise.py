from __future__ import annotations

import difflib
import json
import re
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np

from services.state_store import database_path
from services.shoe_phase4 import _decode, _foreground, _norm, _hist, _edge
from services.shoe_phase5 import _extract as shoe_extract, _split_model_variant, remember_phase5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(database_path(), timeout=60)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


CATEGORY_PROFILES = {
    "calzado": {
        "label": "Calzado",
        "parts": {
            "heel": (0.00, 0.00, 0.36, 1.00),
            "mid": (0.25, 0.00, 0.75, 1.00),
            "toe": (0.64, 0.00, 1.00, 1.00),
            "upper": (0.00, 0.00, 1.00, 0.62),
            "sole": (0.00, 0.56, 1.00, 1.00),
        },
    },
    "ropa": {
        "label": "Ropa",
        "parts": {
            "collar": (0.25, 0.00, 0.75, 0.26),
            "chest": (0.18, 0.18, 0.82, 0.55),
            "left_body": (0.00, 0.20, 0.50, 0.88),
            "right_body": (0.50, 0.20, 1.00, 0.88),
            "hem": (0.12, 0.72, 0.88, 1.00),
        },
    },
    "bolsas": {
        "label": "Bolsas",
        "parts": {
            "handle": (0.18, 0.00, 0.82, 0.32),
            "body": (0.10, 0.22, 0.90, 0.86),
            "left": (0.00, 0.20, 0.45, 0.90),
            "right": (0.55, 0.20, 1.00, 0.90),
            "base": (0.12, 0.72, 0.88, 1.00),
        },
    },
    "accesorios": {
        "label": "Accesorios",
        "parts": {
            "top": (0.10, 0.00, 0.90, 0.36),
            "center": (0.18, 0.24, 0.82, 0.78),
            "lower": (0.10, 0.64, 0.90, 1.00),
            "left": (0.00, 0.12, 0.46, 0.90),
            "right": (0.54, 0.12, 1.00, 0.90),
        },
    },
}


def _category_key(value: str) -> str:
    v = _norm_text(value)
    if any(x in v for x in ("ropa", "camisa", "playera", "pantalon", "sudadera", "chamarra", "vestido")):
        return "ropa"
    if any(x in v for x in ("bolsa", "bolso", "mochila", "handbag", "backpack")):
        return "bolsas"
    if any(x in v for x in ("accesorio", "gorra", "reloj", "lentes", "cinturon", "cartera")):
        return "accesorios"
    return "calzado"


def _norm_text(value: Any) -> str:
    s = str(value or "").casefold().strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9+#.-]+", " ", s)
    return " ".join(s.split())


def migrate_phase6_enterprise() -> dict[str, Any]:
    with _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS fashion_master_v6(
          id TEXT PRIMARY KEY,
          category TEXT NOT NULL DEFAULT 'Calzado',
          subcategory TEXT NOT NULL DEFAULT '',
          brand TEXT NOT NULL,
          family TEXT NOT NULL DEFAULT '',
          model TEXT NOT NULL,
          colorway TEXT NOT NULL DEFAULT '',
          aliases_json TEXT NOT NULL DEFAULT '[]',
          source TEXT NOT NULL DEFAULT 'master',
          confidence REAL NOT NULL DEFAULT 1.0,
          active INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT NOT NULL,
          UNIQUE(category,brand,model,colorway)
        );
        CREATE INDEX IF NOT EXISTS idx_fashion_master_v6_lookup
          ON fashion_master_v6(category,brand,family,model);

        CREATE TABLE IF NOT EXISTS visual_reference_v6(
          id TEXT PRIMARY KEY,
          category TEXT NOT NULL,
          subcategory TEXT NOT NULL DEFAULT '',
          brand TEXT NOT NULL,
          family TEXT NOT NULL DEFAULT '',
          model TEXT NOT NULL,
          colorway TEXT NOT NULL DEFAULT '',
          image_ref TEXT NOT NULL DEFAULT '',
          feature_json TEXT NOT NULL,
          confirmed INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_visual_reference_v6_model
          ON visual_reference_v6(category,brand,model,colorway);

        CREATE TABLE IF NOT EXISTS visual_dna_v6(
          id TEXT PRIMARY KEY,
          category TEXT NOT NULL,
          brand TEXT NOT NULL,
          family TEXT NOT NULL DEFAULT '',
          model TEXT NOT NULL,
          reference_count INTEGER NOT NULL DEFAULT 0,
          dna_json TEXT NOT NULL,
          colorways_json TEXT NOT NULL DEFAULT '[]',
          quality REAL NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          UNIQUE(category,brand,model)
        );

        CREATE TABLE IF NOT EXISTS family_dna_v6(
          id TEXT PRIMARY KEY,
          category TEXT NOT NULL,
          brand TEXT NOT NULL,
          family TEXT NOT NULL,
          model_count INTEGER NOT NULL DEFAULT 0,
          dna_json TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(category,brand,family)
        );
        """)
        # Import the current Shoe Intelligence master into the universal master.
        rows = c.execute("""
          SELECT brand,family,model,colorway,category,subcategory,aliases_json,source,confidence
          FROM shoe_master_models WHERE active=1
        """).fetchall()
        stamp = _now()
        for r in rows:
            c.execute("""
              INSERT OR IGNORE INTO fashion_master_v6
              (id,category,subcategory,brand,family,model,colorway,aliases_json,source,confidence,active,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,1,?)
            """, (
                uuid.uuid4().hex, r["category"] or "Calzado", r["subcategory"] or "Tenis",
                r["brand"], r["family"] or "", r["model"], r["colorway"] or "",
                r["aliases_json"] or "[]", r["source"] or "shoe_master",
                float(r["confidence"] or 1.0), stamp
            ))
        c.commit()
    return stats()


def stats() -> dict[str, Any]:
    with _db() as c:
        masters = c.execute("SELECT COUNT(*) FROM fashion_master_v6 WHERE active=1").fetchone()[0]
        refs = c.execute("SELECT COUNT(*) FROM visual_reference_v6 WHERE confirmed=1").fetchone()[0]
        models = c.execute("SELECT COUNT(*) FROM visual_dna_v6").fetchone()[0]
        families = c.execute("SELECT COUNT(*) FROM family_dna_v6").fetchone()[0]
        cats = c.execute("SELECT COUNT(DISTINCT category) FROM fashion_master_v6 WHERE active=1").fetchone()[0]
    return {
        "status": "ok", "masterItems": masters, "visualReferences": refs,
        "dnaModels": models, "dnaFamilies": families, "categories": cats
    }


def _tokens(s: str) -> set[str]:
    return set(_norm_text(s).split())


def _name_score(query: str, row: dict[str, Any]) -> float:
    q = _norm_text(query)
    if not q:
        return 0.0
    aliases = row.get("aliases") or []
    fields = [row.get("brand",""), row.get("family",""), row.get("model",""),
              row.get("colorway",""), *aliases]
    vals = [_norm_text(x) for x in fields if str(x or "").strip()]
    if any(q == x for x in vals):
        return 1.0
    qnums = set(re.findall(r"\d+", q))
    qt = _tokens(q)
    best = 0.0
    for v in vals:
        ratio = difflib.SequenceMatcher(None, q, v).ratio()
        vt = _tokens(v)
        jac = len(qt & vt) / max(1, len(qt | vt))
        contains = 1.0 if q in v or v in q else 0.0
        score = ratio*.52 + jac*.34 + contains*.14
        nums = set(re.findall(r"\d+", v))
        if qnums and nums and qnums != nums:
            score -= .34
        best = max(best, score)
    return max(0.0, min(1.0, best))


def correct_name(query: str, brand: str = "", category: str = "", limit: int = 8) -> dict[str, Any]:
    migrate_phase6_enterprise()
    with _db() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM fashion_master_v6 WHERE active=1").fetchall()]
    bn = _norm_text(brand)
    ck = _category_key(category) if category else ""
    items = []
    for r in rows:
        if bn and _norm_text(r["brand"]) != bn:
            continue
        if ck and _category_key(r["category"]) != ck:
            continue
        try:
            r["aliases"] = json.loads(r.pop("aliases_json") or "[]")
        except Exception:
            r["aliases"] = []
        s = _name_score(query, r)
        if s < .28:
            continue
        items.append({
            "brand": r["brand"], "family": r["family"], "model": r["model"],
            "colorway": r["colorway"], "category": r["category"],
            "confidence": round(s,4),
            "normalizedName": " ".join(x for x in (r["brand"],r["model"],r["colorway"]) if x)
        })
    items.sort(key=lambda x: x["confidence"], reverse=True)
    return {"status":"ok","query":query,"items":items[:max(1,min(limit,25))]}


def _region_vectors(gray: np.ndarray, mask: np.ndarray, category: str) -> dict[str, list[float]]:
    h,w = gray.shape[:2]
    profile = CATEGORY_PROFILES[_category_key(category)]["parts"]
    out = {}
    for name,(ax0,ay0,ax1,ay1) in profile.items():
        x0,x1 = int(w*ax0), max(int(w*ax1), int(w*ax0)+1)
        y0,y1 = int(h*ay0), max(int(h*ay1), int(h*ay0)+1)
        r = gray[y0:y1,x0:x1]
        m = mask[y0:y1,x0:x1]
        if not r.size:
            out[name] = []
            continue
        r = cv2.resize(r,(24,16),interpolation=cv2.INTER_AREA).astype(np.float32)/255.0
        m = cv2.resize(m,(24,16),interpolation=cv2.INTER_NEAREST).astype(np.float32)/255.0
        out[name] = _norm((r*m).reshape(-1))
    return out


def _hog(gray: np.ndarray, mask: np.ndarray) -> list[float]:
    g=cv2.resize(gray,(128,64),interpolation=cv2.INTER_AREA)
    m=cv2.resize(mask,(128,64),interpolation=cv2.INTER_NEAREST)
    g=cv2.bitwise_and(g,g,mask=m)
    hog=cv2.HOGDescriptor((128,64),(32,32),(16,16),(16,16),9)
    d=hog.compute(g)
    return _norm(d.reshape(-1) if d is not None else [])


def _extract_generic(data: bytes, category: str) -> dict[str, Any]:
    img = _decode(data)
    crop,mask,bbox = _foreground(img)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    h,w = crop.shape[:2]
    small = cv2.resize(mask,(64,32),interpolation=cv2.INTER_AREA).astype(np.float32)/255.0
    profiles = _norm(np.concatenate([small.mean(axis=1),small.mean(axis=0)]))
    return {
        "category": CATEGORY_PROFILES[_category_key(category)]["label"],
        "bbox": bbox,
        "aspect": round(w/max(h,1),6),
        "fill": round(np.count_nonzero(mask)/(mask.size or 1),6),
        "profiles": profiles,
        "hog": _hog(gray,mask),
        "edge": _edge(gray,mask),
        "color": _hist(crop,mask),
        "parts": _region_vectors(gray,mask,category),
    }


def _extract(data: bytes, category: str) -> dict[str, Any]:
    # Footwear reuses the mature Phase 5 extractor, then exposes its regions as semantic parts.
    if _category_key(category) == "calzado":
        f = shoe_extract(data)
        return {
            "category":"Calzado", "bbox":f.get("bbox"), "aspect":f.get("aspect",0),
            "fill":f.get("fill",0), "profiles":f.get("profiles",[]),
            "hog":f.get("hog",[]), "edge":f.get("edge",[]), "color":f.get("color",[]),
            "parts":f.get("grayRegions") or {}
        }
    return _extract_generic(data, category)


def _arr(v: Any) -> list[float]:
    if not isinstance(v,list): return []
    out=[]
    for x in v:
        try: out.append(float(x))
        except Exception: out.append(0.0)
    return out


def _matrix(vectors: list[list[float]]) -> np.ndarray:
    vectors=[_arr(v) for v in vectors if v]
    if not vectors: return np.empty((0,0),np.float32)
    n=max(len(v) for v in vectors)
    a=np.zeros((len(vectors),n),np.float32)
    for i,v in enumerate(vectors): a[i,:len(v)]=v
    return a


def _median(vectors: list[list[float]]) -> list[float]:
    a=_matrix(vectors)
    if not a.size: return []
    return [round(float(x),6) for x in np.median(a,axis=0)]


def _median_num(values: list[float]) -> float:
    return round(float(np.median(np.asarray(values,np.float32))),6) if values else 0.0


def _centroid(features: list[dict[str,Any]], category: str) -> dict[str,Any]:
    d={}
    for k in ("profiles","hog","edge","color"):
        d[k]=_median([f.get(k,[]) for f in features])
    for k in ("aspect","fill"):
        d[k]=_median_num([float(f.get(k) or 0) for f in features])
    part_names=CATEGORY_PROFILES[_category_key(category)]["parts"].keys()
    d["parts"]={name:_median([(f.get("parts") or {}).get(name,[]) for f in features]) for name in part_names}
    return d


def _cos(a: Any,b: Any) -> float:
    av=np.asarray(_arr(a),np.float32); bv=np.asarray(_arr(b),np.float32)
    n=min(av.size,bv.size)
    if not n:return 0.0
    av=av[:n];bv=bv[:n]
    na=float(np.linalg.norm(av));nb=float(np.linalg.norm(bv))
    return 0.0 if na<1e-9 or nb<1e-9 else float(np.dot(av,bv)/(na*nb))


def _compare(q: dict[str,Any], d: dict[str,Any], category: str) -> dict[str,Any]:
    shape=max(0,_cos(q.get("profiles"),d.get("profiles")))*.62
    shape+=max(0,1-abs(float(q.get("aspect",0))-float(d.get("aspect",0)))/1.8)*.23
    shape+=max(0,1-abs(float(q.get("fill",0))-float(d.get("fill",0)))/.7)*.15
    hog=max(0,_cos(q.get("hog"),d.get("hog")))
    edge=max(0,_cos(q.get("edge"),d.get("edge")))
    color=max(0,_cos(q.get("color"),d.get("color")))
    names=list(CATEGORY_PROFILES[_category_key(category)]["parts"].keys())
    qp=q.get("parts") or {}; dp=d.get("parts") or {}
    part_scores={n:max(0,_cos(qp.get(n),dp.get(n))) for n in names}
    pieces=sum(part_scores.values())/max(1,len(part_scores))
    identity=shape*.30 + pieces*.31 + hog*.24 + edge*.15
    return {
        "identity":max(0,min(1,identity)), "shape":shape, "pieces":pieces,
        "hog":hog, "edge":edge, "color":color, "partScores":part_scores
    }


def _family_from_master(category: str, brand: str, model: str) -> str:
    with _db() as c:
        r=c.execute("""SELECT family FROM fashion_master_v6
          WHERE lower(category)=lower(?) AND lower(brand)=lower(?) AND lower(model)=lower(?)
          AND active=1 ORDER BY confidence DESC LIMIT 1""",(category,brand,model)).fetchone()
    return (str(r["family"]).strip() if r and r["family"] else "") or model


def remember(data: bytes, category: str, brand: str, model: str, colorway: str = "",
             subcategory: str = "", family: str = "", image_ref: str = "") -> dict[str,Any]:
    migrate_phase6_enterprise()
    category = CATEGORY_PROFILES[_category_key(category)]["label"]
    base,cw = _split_model_variant(model,colorway)
    brand=brand.strip(); base=base.strip()
    if not brand or not base: raise ValueError("Marca y modelo son obligatorios.")
    family=(family or _family_from_master(category,brand,base)).strip()
    feat=_extract(data,category)
    rid=uuid.uuid4().hex
    with _db() as c:
        c.execute("""INSERT INTO visual_reference_v6
          (id,category,subcategory,brand,family,model,colorway,image_ref,feature_json,confirmed,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,1,?)""",
          (rid,category,subcategory,brand,family,base,cw,image_ref,json.dumps(feat,separators=(",",":")),_now()))
        c.execute("""INSERT OR IGNORE INTO fashion_master_v6
          (id,category,subcategory,brand,family,model,colorway,aliases_json,source,confidence,active,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,1.0,1,?)""",
          (uuid.uuid4().hex,category,subcategory,brand,family,base,cw,"[]","visual_confirmed",_now()))
        c.commit()
    if _category_key(category)=="calzado":
        try: remember_phase5(data,brand,base,colorway=cw,image_ref=image_ref)
        except Exception: pass
    rebuild_dna()
    return {"status":"ok","referenceId":rid,"category":category,"brand":brand,"family":family,"model":base,"colorway":cw}


def rebuild_dna() -> dict[str,Any]:
    migrate_phase6_enterprise()
    with _db() as c:
        rows=[dict(r) for r in c.execute("SELECT * FROM visual_reference_v6 WHERE confirmed=1").fetchall()]
    groups={}
    for r in rows:
        groups.setdefault((r["category"],r["brand"],r["model"]),[]).append(r)
    stamp=_now()
    with _db() as c:
        for (cat,brand,model),items in groups.items():
            feats=[]; cws=[]; fam=""
            for r in items:
                fam=fam or (r["family"] or "")
                try: feats.append(json.loads(r["feature_json"]))
                except Exception: continue
                cw=str(r["colorway"] or "").strip()
                if cw and cw not in cws:cws.append(cw)
            if not feats:continue
            dna=_centroid(feats,cat); q=min(1.0,.42+.12*min(len(feats),5))
            c.execute("""INSERT INTO visual_dna_v6
              (id,category,brand,family,model,reference_count,dna_json,colorways_json,quality,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(category,brand,model) DO UPDATE SET
              family=excluded.family,reference_count=excluded.reference_count,dna_json=excluded.dna_json,
              colorways_json=excluded.colorways_json,quality=excluded.quality,updated_at=excluded.updated_at""",
              (uuid.uuid4().hex,cat,brand,fam or model,model,len(feats),json.dumps(dna,separators=(",",":")),
               json.dumps(cws,ensure_ascii=False),q,stamp))
        c.execute("DELETE FROM family_dna_v6")
        models=[dict(r) for r in c.execute("SELECT * FROM visual_dna_v6").fetchall()]
        fg={}
        for r in models: fg.setdefault((r["category"],r["brand"],r["family"]),[]).append(r)
        for (cat,brand,fam),items in fg.items():
            ds=[json.loads(x["dna_json"]) for x in items]
            fd=_centroid(ds,cat)
            c.execute("""INSERT INTO family_dna_v6
              (id,category,brand,family,model_count,dna_json,updated_at)
              VALUES(?,?,?,?,?,?,?)""",
              (uuid.uuid4().hex,cat,brand,fam,len(items),json.dumps(fd,separators=(",",":")),stamp))
        c.commit()
    x=stats();x["builtModels"]=len(groups);return x


def import_phase5_and_rebuild() -> dict[str,Any]:
    migrate_phase6_enterprise()
    with _db() as c:
        existing=c.execute("SELECT COUNT(*) FROM visual_reference_v6 WHERE source IS NULL").fetchone()[0] if False else 0
    # Import Phase 5 references only if same image/model/colorway is not already represented.
    with _db() as c:
        p5=[dict(r) for r in c.execute("SELECT * FROM shoe_visual_features_v5 WHERE confirmed=1").fetchall()]
        stamp=_now()
        imported=0
        for r in p5:
            dup=c.execute("""SELECT 1 FROM visual_reference_v6
              WHERE category='Calzado' AND lower(brand)=lower(?) AND lower(model)=lower(?)
              AND lower(colorway)=lower(?) AND image_ref=? LIMIT 1""",
              (r["brand"],r["base_model"],r["colorway"] or "",r["image_ref"] or "")).fetchone()
            if dup: continue
            try:
                f=json.loads(r["feature_json"])
                feat={"category":"Calzado","bbox":f.get("bbox"),"aspect":f.get("aspect",0),"fill":f.get("fill",0),
                      "profiles":f.get("profiles",[]),"hog":f.get("hog",[]),"edge":f.get("edge",[]),
                      "color":f.get("color",[]),"parts":f.get("grayRegions") or {}}
            except Exception:
                continue
            fam=_family_from_master("Calzado",r["brand"],r["base_model"])
            c.execute("""INSERT INTO visual_reference_v6
              (id,category,subcategory,brand,family,model,colorway,image_ref,feature_json,confirmed,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,1,?)""",
              (uuid.uuid4().hex,"Calzado","Tenis",r["brand"],fam,r["base_model"],r["colorway"] or "",
               r["image_ref"] or "",json.dumps(feat,separators=(",",":")),stamp))
            imported+=1
        c.commit()
    x=rebuild_dna();x["importedPhase5"]=imported;return x


def _variant_match(q: dict[str,Any], category: str, brand: str, model: str) -> tuple[str,float]:
    with _db() as c:
        rows=[dict(r) for r in c.execute("""SELECT colorway,feature_json FROM visual_reference_v6
          WHERE confirmed=1 AND lower(category)=lower(?) AND lower(brand)=lower(?) AND lower(model)=lower(?)
          AND colorway<>''""",(category,brand,model)).fetchall()]
    best_name="";best=0.0
    for r in rows:
        try:e=_compare(q,json.loads(r["feature_json"]),category)
        except Exception:continue
        # Variant emphasizes color but retains enough geometry to avoid absurd matches.
        s=e["color"]*.68+e["pieces"]*.20+e["edge"]*.12
        if s>best:best=s;best_name=r["colorway"]
    return best_name,max(0,min(1,best))


def recognize(data: bytes, category: str = "Calzado", limit: int = 8) -> dict[str,Any]:
    migrate_phase6_enterprise()
    category=CATEGORY_PROFILES[_category_key(category)]["label"]
    q=_extract(data,category)
    with _db() as c:
        models=[dict(r) for r in c.execute("SELECT * FROM visual_dna_v6 WHERE lower(category)=lower(?)",(category,)).fetchall()]
        fams=[dict(r) for r in c.execute("SELECT * FROM family_dna_v6 WHERE lower(category)=lower(?)",(category,)).fetchall()]
    if not models:
        return {"status":"ok","engine":"phase6-enterprise-integral","category":category,"items":[],"decision":"unknown",
                "message":"No hay ADN visual para esta categoría todavía."}
    family_scores={}
    for r in fams:
        try:family_scores[(r["brand"],r["family"])]=_compare(q,json.loads(r["dna_json"]),category)["identity"]
        except Exception:pass
    items=[]
    for r in models:
        try:e=_compare(q,json.loads(r["dna_json"]),category)
        except Exception:continue
        fs=family_scores.get((r["brand"],r["family"]),0.0)
        raw=e["identity"]*.88+fs*.12
        refs=int(r["reference_count"]);qual=float(r["quality"])
        support=min(1.0,.55+.11*min(refs,4))
        conf=max(0,min(.995,raw*(.78+.22*qual)*support))
        cw,cws=_variant_match(q,category,r["brand"],r["model"])
        items.append({
          "category":category,"brand":r["brand"],"family":r["family"],"model":r["model"],
          "modelConfidence":round(conf,4),"familyConfidence":round(fs,4),
          "colorway":cw,"colorwayConfidence":round(cws,4),
          "references":refs,"dnaQuality":round(qual,4),"novelty":round(max(0,1-raw),4),
          "evidence":{
            "shape":round(float(e["shape"]),4),"pieces":round(float(e["pieces"]),4),
            "hog":round(float(e["hog"]),4),"edge":round(float(e["edge"]),4),
            "color":round(float(e["color"]),4),
            "partScores":{k:round(float(v),4) for k,v in e["partScores"].items()}
          }
        })
    items.sort(key=lambda x:x["modelConfidence"],reverse=True)
    top=items[0]["modelConfidence"] if items else 0.0
    second=items[1]["modelConfidence"] if len(items)>1 else 0.0
    margin=max(0,top-second)
    decision="high_confidence" if top>=.82 and margin>=.08 else ("review" if top>=.68 else ("low_confidence" if top>=.55 else "unknown"))
    return {"status":"ok","engine":"phase6-enterprise-integral","category":category,
            "decision":decision,"margin":round(margin,4),"items":items[:max(1,min(limit,25))]}
