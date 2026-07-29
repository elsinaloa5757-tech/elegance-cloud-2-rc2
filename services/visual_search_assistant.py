from __future__ import annotations

import json, re, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from services.state_store import database_path

DB = Path(database_path())

BRANDS = [
    'Nike','Jordan','Adidas','Puma','New Balance','Timberland','Vans','Crocs',
    'Reebok','Converse','Gucci','Dior','Louis Vuitton','Versace','Prada','Coach'
]
COLOR_WORDS = ['negro','blanco','rojo','rosa','azul','verde','beige','gris','café','marrón','amarillo','naranja','morado','dorado','plateado']
SKU_RE = re.compile(r'\b[A-Z]{1,4}\d{2,5}[A-Z0-9-]*-\d{2,4}\b|\b[A-Z]{2,5}-?\d{3,8}\b', re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def migrate() -> None:
    with _db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS visual_search_sessions(
          id TEXT PRIMARY KEY,
          product_id TEXT NOT NULL,
          review_id TEXT NOT NULL DEFAULT '',
          image_ref TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'waiting',
          source TEXT NOT NULL DEFAULT 'Google Lens (asistido)',
          source_url TEXT NOT NULL DEFAULT '',
          pasted_text TEXT NOT NULL DEFAULT '',
          extracted_json TEXT NOT NULL DEFAULT '{}',
          confidence REAL NOT NULL DEFAULT 0,
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_visual_search_product ON visual_search_sessions(product_id,created_at);
        ''')


def create_session(product_id: str, review_id: str, image_ref: str) -> dict[str, Any]:
    migrate()
    sid = uuid.uuid4().hex
    row = {
        'id': sid, 'product_id': product_id, 'review_id': review_id or '',
        'image_ref': image_ref or '', 'status': 'waiting',
        'source': 'Google Lens (asistido)', 'created_at': _now(), 'updated_at': _now()
    }
    with _db() as c:
        c.execute('''INSERT INTO visual_search_sessions
        (id,product_id,review_id,image_ref,status,source,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?)''', tuple(row[k] for k in ['id','product_id','review_id','image_ref','status','source','created_at','updated_at']))
    return row


def _clean_text(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '')).strip()


def extract_metadata(text: str='', url: str='') -> dict[str, Any]:
    raw = _clean_text(text)
    lower = raw.lower()
    result: dict[str, Any] = {}
    for brand in BRANDS:
        if brand.lower() in lower:
            result['brand'] = brand
            break
    skus = SKU_RE.findall(raw.upper())
    if skus:
        result['sku'] = skus[0]
        result['manufacturer_code'] = skus[0]
    colors = [c for c in COLOR_WORDS if c in lower]
    if colors:
        result['color'] = ' / '.join(dict.fromkeys(colors))
    # Strong product-name lines: prefer first informative line, excluding prices/navigation.
    lines = [x.strip(' -|•') for x in re.split(r'[\r\n]+', text or '') if x.strip()]
    candidates = [x for x in lines if 8 <= len(x) <= 140 and not re.search(r'comprar|precio|envío|patrocinado|ver todo|\$\s*\d', x, re.I)]
    if candidates:
        result['title'] = candidates[0]
        model = candidates[0]
        if result.get('brand'):
            model = re.sub(re.escape(result['brand']), '', model, flags=re.I).strip(' -|')
        if model:
            result['model'] = model
    # Common footwear evidence.
    if any(x in lower for x in ['sneaker','tenis','zapato','air jordan','air max','retro']):
        result['category'] = 'Calzado'; result['subcategory'] = 'Tenis'
    if any(x in lower for x in ['perfume','eau de parfum','eau de toilette']):
        result['category'] = 'Perfumería'; result['subcategory'] = 'Fragancias'
    if url:
        result['source_url'] = url.strip()
        try:
            host = urlparse(url).netloc.replace('www.','')
            if host: result['source'] = host
        except Exception:
            pass
    if raw:
        result['description'] = raw[:700]
    evidence=[]
    if result.get('brand'): evidence.append('Marca encontrada en el texto pegado')
    if result.get('sku'): evidence.append('Código/SKU con patrón reconocible')
    if result.get('title'): evidence.append('Nombre comercial extraído del resultado')
    if colors: evidence.append('Colores mencionados en el resultado')
    result['evidence'] = evidence
    result['confidence'] = min(.95, .35 + .13*len(evidence)) if evidence else .15
    return result


def register_result(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    migrate()
    extracted = extract_metadata(str(payload.get('pasted_text') or ''), str(payload.get('source_url') or ''))
    # Explicit user-entered fields take precedence over extraction.
    for key in ['title','brand','model','category','subcategory','sku','manufacturer_code','color','material','gender','description','source']:
        value = payload.get(key)
        if value not in (None,''):
            extracted[key] = value
    confidence = float(payload.get('confidence') or extracted.get('confidence') or .5)
    notes = str(payload.get('notes') or '')
    with _db() as c:
        row = c.execute('SELECT * FROM visual_search_sessions WHERE id=?',(session_id,)).fetchone()
        if not row: raise KeyError('Sesión de búsqueda visual no encontrada.')
        c.execute('''UPDATE visual_search_sessions SET status='captured',source=?,source_url=?,pasted_text=?,extracted_json=?,confidence=?,notes=?,updated_at=? WHERE id=?''',(
            str(extracted.get('source') or payload.get('source') or 'Google Lens (asistido)'),
            str(payload.get('source_url') or extracted.get('source_url') or ''), str(payload.get('pasted_text') or ''),
            json.dumps(extracted,ensure_ascii=False), confidence, notes, _now(), session_id))
    return {'session_id':session_id,'product_id':row['product_id'],'review_id':row['review_id'],'extracted':extracted,'confidence':confidence}


def mark_applied(session_id: str) -> None:
    migrate()
    with _db() as c:
        c.execute("UPDATE visual_search_sessions SET status='applied',updated_at=? WHERE id=?",(_now(),session_id))
