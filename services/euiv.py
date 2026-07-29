from __future__ import annotations

import json, math, re, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from services.state_store import database_path

DB = Path(database_path())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def migrate_euiv() -> None:
    with _db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS euiv_references(
          id TEXT PRIMARY KEY,
          product_id TEXT NOT NULL DEFAULT '',
          brand TEXT NOT NULL DEFAULT '',
          model TEXT NOT NULL DEFAULT '',
          title TEXT NOT NULL DEFAULT '',
          sku TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT '',
          subcategory TEXT NOT NULL DEFAULT '',
          colors TEXT NOT NULL DEFAULT '',
          image_ref TEXT NOT NULL DEFAULT '',
          phash TEXT NOT NULL DEFAULT '',
          hist_json TEXT NOT NULL DEFAULT '[]',
          orb_json TEXT NOT NULL DEFAULT '[]',
          source TEXT NOT NULL DEFAULT 'confirmed',
          evidence_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_euiv_brand_model ON euiv_references(brand,model);
        CREATE INDEX IF NOT EXISTS idx_euiv_sku ON euiv_references(sku);
        CREATE TABLE IF NOT EXISTS euiv_candidates(
          id TEXT PRIMARY KEY,
          product_id TEXT NOT NULL,
          review_id TEXT NOT NULL DEFAULT '',
          name TEXT NOT NULL DEFAULT '',
          brand TEXT NOT NULL DEFAULT '',
          model TEXT NOT NULL DEFAULT '',
          sku TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT '',
          subcategory TEXT NOT NULL DEFAULT '',
          colors TEXT NOT NULL DEFAULT '',
          description TEXT NOT NULL DEFAULT '',
          image_url TEXT NOT NULL DEFAULT '',
          source_name TEXT NOT NULL DEFAULT '',
          source_url TEXT NOT NULL DEFAULT '',
          confidence REAL NOT NULL DEFAULT 0,
          evidence_json TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'suggested',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_euiv_candidates_product ON euiv_candidates(product_id,created_at);
        ''')


def _phash(image: np.ndarray) -> str:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(gray))[:8, :8]
    med = float(np.median(dct[1:, 1:]))
    bits = (dct > med).flatten()
    return ''.join('1' if x else '0' for x in bits)


def _hist(image: np.ndarray) -> list[float]:
    hsv = cv2.cvtColor(cv2.resize(image, (256, 256)), cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
    cv2.normalize(h, h)
    return [round(float(x), 6) for x in h.flatten()]


def _orb(image: np.ndarray) -> list[list[int]]:
    gray = cv2.cvtColor(cv2.resize(image, (480, 480)), cv2.COLOR_BGR2GRAY)
    detector = cv2.ORB_create(nfeatures=220)
    _, des = detector.detectAndCompute(gray, None)
    if des is None:
        return []
    return des[:120].astype(int).tolist()


def visual_signature(image: np.ndarray) -> dict[str, Any]:
    return {'phash': _phash(image), 'hist': _hist(image), 'orb': _orb(image)}


def _hamming(a: str, b: str) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return 1.0 - sum(x != y for x, y in zip(a, b)) / len(a)


def _hist_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    aa = np.asarray(a, dtype=np.float32)
    bb = np.asarray(b, dtype=np.float32)
    return float(max(0.0, min(1.0, cv2.compareHist(aa, bb, cv2.HISTCMP_CORREL))))


def _orb_similarity(a: list[list[int]], b: list[list[int]]) -> float:
    if len(a) < 4 or len(b) < 4:
        return 0.0
    da = np.asarray(a, dtype=np.uint8)
    db = np.asarray(b, dtype=np.uint8)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    matches = matcher.knnMatch(da, db, k=2)
    good = [m for pair in matches if len(pair) == 2 for m, n in [pair] if m.distance < .76 * n.distance]
    return min(1.0, len(good) / max(12.0, min(len(da), len(db)) * .34))


def signature_similarity(sig: dict[str, Any], ref: dict[str, Any]) -> tuple[float, dict[str, float]]:
    p = _hamming(sig.get('phash', ''), ref.get('phash', ''))
    h = _hist_similarity(sig.get('hist', []), ref.get('hist', []))
    o = _orb_similarity(sig.get('orb', []), ref.get('orb', []))
    # ORB is most useful when the same model/angle recurs; histogram and pHash are supportive only.
    score = .42 * o + .33 * p + .25 * h
    return round(score, 4), {'orb': round(o, 4), 'phash': round(p, 4), 'color': round(h, 4)}


def learn_reference(product_id: str, image_ref: str, image: np.ndarray, metadata: dict[str, Any], source: str='confirmed', evidence: list[str] | None=None) -> str:
    migrate_euiv()
    sig = visual_signature(image)
    rid = uuid.uuid4().hex
    with _db() as c:
        c.execute('''INSERT INTO euiv_references
        (id,product_id,brand,model,title,sku,category,subcategory,colors,image_ref,phash,hist_json,orb_json,source,evidence_json,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
            rid, product_id, str(metadata.get('brand','')), str(metadata.get('model','')), str(metadata.get('title','')),
            str(metadata.get('sku','')), str(metadata.get('category','')), str(metadata.get('subcategory','')),
            str(metadata.get('colors','')), image_ref, sig['phash'], json.dumps(sig['hist']), json.dumps(sig['orb']),
            source, json.dumps(evidence or [], ensure_ascii=False), _now(), _now()))
    return rid


def local_visual_candidates(images: list[np.ndarray], limit: int=8) -> list[dict[str, Any]]:
    migrate_euiv()
    if not images:
        return []
    signatures = [visual_signature(im) for im in images[:4]]
    with _db() as c:
        rows = c.execute('SELECT * FROM euiv_references ORDER BY updated_at DESC LIMIT 2000').fetchall()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        ref = {'phash': row['phash'], 'hist': json.loads(row['hist_json'] or '[]'), 'orb': json.loads(row['orb_json'] or '[]')}
        comparisons = [signature_similarity(sig, ref) for sig in signatures]
        best_score, parts = max(comparisons, key=lambda x: x[0])
        if best_score < .42:
            continue
        # Exact model auto-identification requires a high threshold; lower scores stay as selectable suggestions.
        confidence = min(.98, .18 + .86 * best_score)
        candidates.append({
            'name': row['title'] or ' '.join(x for x in [row['brand'], row['model']] if x),
            'brand': row['brand'], 'model': row['model'], 'sku': row['sku'],
            'category': row['category'], 'subcategory': row['subcategory'], 'colors': row['colors'],
            'image': row['image_ref'], 'source': 'Biblioteca Elegance', 'sourceUrl': '',
            'confidence': round(confidence, 3),
            'evidence': [f'Coincidencia visual local: {round(best_score*100)}%', f'ORB {round(parts["orb"]*100)}% · forma {round(parts["phash"]*100)}% · color {round(parts["color"]*100)}%'],
            'autoEligible': bool(confidence >= .91 and row['brand'] and row['model'])
        })
    candidates.sort(key=lambda x: x['confidence'], reverse=True)
    # De-duplicate same brand/model.
    out=[]; seen=set()
    for x in candidates:
        key=(x['brand'].lower(),x['model'].lower(),x['sku'].lower())
        if key in seen: continue
        seen.add(key); out.append(x)
        if len(out)>=limit: break
    return out


def infer_footwear_from_sizes(sizes: list[str], current_category: str='') -> dict[str, Any]:
    """Conservative category inference. Shoe-size ranges are useful evidence, not model evidence."""
    if current_category and current_category not in ('Otros',''):
        return {}
    nums=[]
    for value in sizes:
        nums += [float(x) for x in re.findall(r'\d+(?:\.5)?', str(value))]
    if nums and all(18 <= n <= 50 for n in nums):
        return {
            'category': {'value':'Calzado','confidence':.78,'source':'local-heuristic','evidence':'Rango numérico compatible con talla de calzado detectado por OCR'},
            'subcategory': {'value':'Tenis','confidence':.68,'source':'local-heuristic','evidence':'Fotografía de producto con talla de calzado; requiere confirmación si no hay marca/modelo'}
        }
    return {}


def save_candidates(product_id: str, review_id: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    migrate_euiv()
    with _db() as c:
        c.execute("UPDATE euiv_candidates SET status='superseded' WHERE product_id=? AND status='suggested'", (product_id,))
        for item in candidates:
            cid=uuid.uuid4().hex
            item['id']=cid
            c.execute('''INSERT INTO euiv_candidates
            (id,product_id,review_id,name,brand,model,sku,category,subcategory,colors,description,image_url,source_name,source_url,confidence,evidence_json,status,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
                cid,product_id,review_id,item.get('name',''),item.get('brand',''),item.get('model',''),item.get('sku',''),
                item.get('category',''),item.get('subcategory',''),item.get('colors',''),item.get('description',''),
                item.get('image',''),item.get('source',''),item.get('sourceUrl',''),float(item.get('confidence',0)),
                json.dumps(item.get('evidence',[]),ensure_ascii=False),'suggested',_now()))
    return candidates


def list_candidates(product_id: str, limit: int=20) -> list[dict[str, Any]]:
    migrate_euiv()
    with _db() as c:
        rows=c.execute("SELECT * FROM euiv_candidates WHERE product_id=? AND status='suggested' ORDER BY confidence DESC,created_at DESC LIMIT ?",(product_id,limit)).fetchall()
    out=[]
    for r in rows:
        x=dict(r); x['evidence']=json.loads(x.pop('evidence_json') or '[]'); out.append(x)
    return out


def candidate(candidate_id: str) -> dict[str, Any] | None:
    migrate_euiv()
    with _db() as c:
        r=c.execute('SELECT * FROM euiv_candidates WHERE id=?',(candidate_id,)).fetchone()
    if not r:return None
    x=dict(r);x['evidence']=json.loads(x.pop('evidence_json') or '[]');return x


def accept_candidate(candidate_id: str) -> dict[str, Any]:
    migrate_euiv()
    item=candidate(candidate_id)
    if not item: raise KeyError('Coincidencia no encontrada.')
    with _db() as c:
        c.execute("UPDATE euiv_candidates SET status='accepted' WHERE id=?",(candidate_id,))
        c.execute("UPDATE euiv_candidates SET status='discarded' WHERE product_id=? AND id<>? AND status='suggested'",(item['product_id'],candidate_id))
    return item
