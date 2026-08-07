from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np

from services.state_store import database_path
from services.shoe_phase4 import _decode, _foreground, _norm, _hist, _edge, _hu, _orb, _orbscore, _cos


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(database_path(), timeout=60)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _split_model_variant(model: str, colorway: str = "") -> tuple[str, str]:
    raw = (model or "").strip()
    cw = (colorway or "").strip()
    if cw:
        return raw, cw
    m = re.match(r'^(.*?)(?:\s*["“](.+?)["”])\s*$', raw)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.match(r"^(.*?)(?:\s+[-–—]\s+)(.+)$", raw)
    if m and len(m.group(2).split()) <= 6:
        return m.group(1).strip(), m.group(2).strip()
    return raw, ""


def migrate_phase5() -> dict[str, Any]:
    with _connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS shoe_visual_features_v5(
          id TEXT PRIMARY KEY,
          brand TEXT NOT NULL,
          base_model TEXT NOT NULL,
          colorway TEXT NOT NULL DEFAULT '',
          source_product_id TEXT NOT NULL DEFAULT '',
          image_ref TEXT NOT NULL DEFAULT '',
          feature_json TEXT NOT NULL,
          confirmed INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_visual_v5_model ON shoe_visual_features_v5(brand,base_model);
        CREATE INDEX IF NOT EXISTS idx_visual_v5_colorway ON shoe_visual_features_v5(brand,base_model,colorway);
        """)
        c.commit()
    return phase5_stats()


def phase5_stats() -> dict[str, Any]:
    with _connect() as c:
        refs = c.execute("SELECT COUNT(*) FROM shoe_visual_features_v5 WHERE confirmed=1").fetchone()[0]
        models = c.execute("SELECT COUNT(DISTINCT lower(brand)||'|'||lower(base_model)) FROM shoe_visual_features_v5 WHERE confirmed=1").fetchone()[0]
        variants = c.execute("SELECT COUNT(DISTINCT lower(brand)||'|'||lower(base_model)||'|'||lower(colorway)) FROM shoe_visual_features_v5 WHERE confirmed=1 AND colorway<>''").fetchone()[0]
    return {"status":"ok","references":refs,"models":models,"variants":variants}


def _resize_mask(mask: np.ndarray, size=(64, 32)) -> np.ndarray:
    return cv2.resize(mask, size, interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


def _profiles(mask: np.ndarray) -> list[float]:
    m = _resize_mask(mask)
    return _norm(np.concatenate([m.mean(axis=1), m.mean(axis=0)]))


def _hog(gray: np.ndarray, mask: np.ndarray) -> list[float]:
    g = cv2.resize(gray, (128, 64), interpolation=cv2.INTER_AREA)
    m = cv2.resize(mask, (128, 64), interpolation=cv2.INTER_NEAREST)
    g = cv2.bitwise_and(g, g, mask=m)
    hog = cv2.HOGDescriptor((128,64),(32,32),(16,16),(16,16),9)
    d = hog.compute(g)
    return _norm(d.reshape(-1) if d is not None else [])


def _gray_regions(gray: np.ndarray, mask: np.ndarray) -> dict[str, list[float]]:
    h, w = gray.shape[:2]
    boxes = {
        "heel": (0, 0, max(1,int(w*.36)), h),
        "mid": (int(w*.25), 0, max(int(w*.26)+1,int(w*.75)), h),
        "toe": (int(w*.64), 0, w, h),
        "upper": (0, 0, w, max(1,int(h*.62))),
        "sole": (0, int(h*.56), w, h),
    }
    out = {}
    for name,(x0,y0,x1,y1) in boxes.items():
        r = gray[y0:y1,x0:x1]
        m = mask[y0:y1,x0:x1]
        if not r.size:
            out[name] = []
            continue
        r = cv2.resize(r, (24,16), interpolation=cv2.INTER_AREA).astype(np.float32)/255.0
        m = cv2.resize(m, (24,16), interpolation=cv2.INTER_NEAREST).astype(np.float32)/255.0
        out[name] = _norm((r*m).reshape(-1))
    return out


def _extract(data: bytes) -> dict[str, Any]:
    img = _decode(data)
    crop, mask, bbox = _foreground(img)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    h,w = crop.shape[:2]
    orb = _orb(gray, mask)
    return {
        "bbox": bbox,
        "aspect": round(w/max(h,1),6),
        "fill": round(np.count_nonzero(mask)/(mask.size or 1),6),
        "hu": _hu(mask),
        "profiles": _profiles(mask),
        "hog": _hog(gray,mask),
        "edge": _edge(gray,mask),
        "grayRegions": _gray_regions(gray,mask),
        "color": _hist(crop,mask),
        "orb": orb.tolist(),
    }


def _shape_score(a: dict, b: dict) -> float:
    ar = max(0.0, 1.0-abs(float(a.get("aspect",0))-float(b.get("aspect",0)))/1.8)
    fill = max(0.0, 1.0-abs(float(a.get("fill",0))-float(b.get("fill",0)))*1.6)
    prof = max(0.0,_cos(a.get("profiles",[]),b.get("profiles",[])))
    hu1=a.get("hu") or []
    hu2=b.get("hu") or []
    hu=0.0
    if hu1 and hu2:
        d=sum(min(4.0,abs(float(x)-float(y))) for x,y in zip(hu1,hu2))/max(1,len(hu1))
        hu=max(0.0,1.0-d/4.0)
    return ar*.16 + fill*.10 + prof*.42 + hu*.32


def _regional_gray(a: dict,b: dict) -> tuple[float,dict[str,float]]:
    names=("heel","mid","toe","upper","sole")
    ra=a.get("grayRegions") or {}
    rb=b.get("grayRegions") or {}
    direct={n:max(0.0,_cos(ra.get(n,[]),rb.get(n,[]))) for n in names}
    swapped=dict(direct)
    swapped["heel"]=max(0.0,_cos(ra.get("heel",[]),rb.get("toe",[])))
    swapped["toe"]=max(0.0,_cos(ra.get("toe",[]),rb.get("heel",[])))
    sd=sum(direct.values())/len(names)
    ss=sum(swapped.values())/len(names)
    return (ss,swapped) if ss>sd else (sd,direct)


def _orb_array(v: Any) -> np.ndarray:
    try:
        a=np.asarray(v,dtype=np.uint8)
        return a.reshape((-1,32)) if a.size else np.empty((0,32),np.uint8)
    except Exception:
        return np.empty((0,32),np.uint8)


def _compare(a: dict,b: dict) -> dict[str,Any]:
    shape=_shape_score(a,b)
    hog=max(0.0,_cos(a.get("hog",[]),b.get("hog",[])))
    edge=max(0.0,_cos(a.get("edge",[]),b.get("edge",[])))
    regions,parts=_regional_gray(a,b)
    local=_orbscore(_orb_array(a.get("orb")),_orb_array(b.get("orb")))
    color=max(0.0,_cos(a.get("color",[]),b.get("color",[])))

    # Identity ignores most color dependence and downweights fragile point matching.
    identity=shape*.30 + regions*.27 + hog*.22 + edge*.14 + local*.07

    # Variant/colorway is separate from silhouette identity.
    colorway=(color*.70 + regions*.20 + edge*.10) if identity>=.55 else color*.45

    return {
        "identity":max(0,min(1,identity)),
        "colorway":max(0,min(1,colorway)),
        "shape":shape,
        "regions":regions,
        "hog":hog,
        "edge":edge,
        "local":local,
        "color":color,
        "parts":parts,
    }


def remember_phase5(data:bytes,brand:str,model:str,colorway:str="",source_product_id:str="",image_ref:str="") -> dict[str,Any]:
    migrate_phase5()
    brand=brand.strip()
    base,cw=_split_model_variant(model,colorway)
    if not brand or not base:
        raise ValueError("Marca y modelo son obligatorios.")
    feat=_extract(data)
    rid=uuid.uuid4().hex
    with _connect() as c:
        c.execute(
            """INSERT INTO shoe_visual_features_v5
            (id,brand,base_model,colorway,source_product_id,image_ref,feature_json,confirmed,created_at)
            VALUES(?,?,?,?,?,?,?,1,?)""",
            (rid,brand,base,cw,source_product_id,image_ref,json.dumps(feat,separators=(",",":")),_now()),
        )
        c.commit()
    return {"status":"ok","referenceId":rid,"brand":brand,"model":base,"colorway":cw}


def recognize_phase5(data:bytes,limit:int=8) -> dict[str,Any]:
    migrate_phase5()
    q=_extract(data)
    with _connect() as c:
        rows=[dict(r) for r in c.execute("SELECT * FROM shoe_visual_features_v5 WHERE confirmed=1").fetchall()]

    scored=[]
    for row in rows:
        try:
            ev=_compare(q,json.loads(row["feature_json"]))
        except Exception:
            continue
        scored.append({
            "brand":row["brand"],
            "model":row["base_model"],
            "colorway":row["colorway"],
            "evidence":ev,
        })

    grouped={}
    for item in scored:
        grouped.setdefault((item["brand"],item["model"]),[]).append(item)

    results=[]
    for (brand,model),items in grouped.items():
        items.sort(key=lambda x:x["evidence"]["identity"],reverse=True)
        top=items[:2]
        identity=top[0]["evidence"]["identity"] if len(top)==1 else (
            top[0]["evidence"]["identity"]*.72 + top[1]["evidence"]["identity"]*.28
        )
        best=top[0]
        variant=max(items,key=lambda x:x["evidence"]["colorway"])
        results.append({
            "brand":brand,
            "model":model,
            "modelConfidence":identity,
            "colorway":variant["colorway"],
            "colorwayConfidence":variant["evidence"]["colorway"],
            "evidence":best["evidence"],
            "referenceCount":len(items),
        })

    results.sort(key=lambda x:x["modelConfidence"],reverse=True)
    for r in results:
        r["modelConfidence"]=round(float(r["modelConfidence"]),4)
        r["colorwayConfidence"]=round(float(r["colorwayConfidence"]),4)
        ev=r["evidence"]
        for k in ("identity","colorway","shape","regions","hog","edge","local","color"):
            ev[k]=round(float(ev[k]),4)
        ev["parts"]={k:round(float(v),4) for k,v in ev["parts"].items()}

    return {
        "status":"ok",
        "engine":"phase5-hierarchical-multiview",
        "references":len(rows),
        "items":results[:max(1,min(int(limit),25))],
        "message":"Fase 5 necesita referencias confirmadas." if not rows else "",
    }
