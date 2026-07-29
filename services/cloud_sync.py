from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
import os
import shutil
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageOps

from services.state_store import database_path

BACKEND = Path(__file__).resolve().parents[1]
CONFIG_PATH = BACKEND / 'config' / 'public_cloud.json'
DEFAULT_ENDPOINT = 'https://czekazhacqaamwecjthp.supabase.co/functions/v1/elegance-sync'
_WORKER_LOCK = threading.Lock()
_WORKER_STARTED = False
_WAKE = threading.Event()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(database_path(), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA foreign_keys=ON')
    _migrate(con)
    return con


def _migrate(con: sqlite3.Connection) -> None:
    con.executescript('''
    CREATE TABLE IF NOT EXISTS cloud_sync_queue(
      id TEXT PRIMARY KEY,
      operation TEXT NOT NULL DEFAULT 'upsert',
      product_id TEXT NOT NULL,
      payload TEXT NOT NULL,
      source_hash TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0,
      max_attempts INTEGER NOT NULL DEFAULT 5,
      next_attempt_at TEXT,
      last_error TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      completed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_cloud_sync_queue_status ON cloud_sync_queue(status,next_attempt_at,created_at);
    CREATE TABLE IF NOT EXISTS cloud_sync_state(
      product_id TEXT PRIMARY KEY,
      source_hash TEXT NOT NULL,
      cloud_updated_at TEXT,
      image_urls TEXT NOT NULL DEFAULT '[]',
      last_queue_id TEXT,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS cloud_sync_history(
      id TEXT PRIMARY KEY,
      queue_id TEXT,
      product_id TEXT,
      event TEXT NOT NULL,
      success INTEGER NOT NULL DEFAULT 0,
      detail TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_cloud_sync_history_created ON cloud_sync_history(created_at DESC);
    CREATE TABLE IF NOT EXISTS cloud_backups(
      id TEXT PRIMARY KEY,
      path TEXT NOT NULL,
      reason TEXT NOT NULL,
      size_bytes INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      restored_at TEXT
    );
    ''')
    con.commit()


def load_cloud_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            config = json.loads(CONFIG_PATH.read_text(encoding='utf-8-sig'))
        except Exception:
            config = {}
    config.setdefault('sync_endpoint', DEFAULT_ENDPOINT)
    config.setdefault('sync_key', '')
    config['sync_key'] = os.getenv('ELEGANCE_SYNC_KEY', '').strip() or config['sync_key']
    config.setdefault('public_catalog_url', 'https://elegance-public-catalog.vercel.app')
    config.setdefault('auto_sync', True)
    config.setdefault('upload_images', True)
    config.setdefault('max_image_mb', 14)
    config.setdefault('timeout_seconds', 90)
    config.setdefault('image_quality', 86)
    config.setdefault('max_image_edge', 1800)
    config.setdefault('thumbnail_edge', 480)
    config.setdefault('max_attempts', 5)
    config.setdefault('retry_base_seconds', 15)
    config.setdefault('worker_interval_seconds', 4)
    return config


def save_cloud_config(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_cloud_config()
    allowed = {
        'sync_endpoint','sync_key','public_catalog_url','auto_sync','upload_images','max_image_mb',
        'timeout_seconds','image_quality','max_image_edge','thumbnail_edge','max_attempts',
        'retry_base_seconds','worker_interval_seconds'
    }
    for key in allowed:
        if key in payload:
            # Never replace an existing secret with the masked value shown by the UI.
            if key == 'sync_key' and str(payload[key]).startswith('••••'):
                continue
            current[key] = payload[key]
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
    return current


def create_backup(reason: str = 'cloud_sync') -> dict[str, Any]:
    db = Path(database_path())
    folder = db.parent / 'cloud_backups'
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    target = folder / f'elegance_cloud11_{stamp}.sqlite3'
    if db.exists():
        with sqlite3.connect(db) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
    item = {'id': uuid.uuid4().hex, 'path': str(target), 'reason': reason, 'sizeBytes': target.stat().st_size if target.exists() else 0, 'createdAt': _now()}
    with _connect() as con:
        con.execute('INSERT INTO cloud_backups(id,path,reason,size_bytes,created_at) VALUES(?,?,?,?,?)',
                    (item['id'], item['path'], reason, item['sizeBytes'], item['createdAt']))
        con.commit()
    return item


def list_backups(limit: int = 30) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute('SELECT * FROM cloud_backups ORDER BY created_at DESC LIMIT ?', (max(1,min(limit,100)),)).fetchall()
    return [dict(r) for r in rows]


def restore_backup(backup_id: str) -> dict[str, Any]:
    # Safety backup before restoring any previous snapshot.
    safety = create_backup('before_restore')
    with _connect() as con:
        row = con.execute('SELECT * FROM cloud_backups WHERE id=?', (backup_id,)).fetchone()
    if not row:
        raise ValueError('Respaldo no encontrado.')
    source = Path(row['path'])
    if not source.exists():
        raise ValueError('El archivo del respaldo ya no existe.')
    db = Path(database_path())
    tmp = db.with_suffix('.restore.tmp')
    shutil.copy2(source, tmp)
    # Validate the snapshot before replacing the live database.
    with sqlite3.connect(tmp) as check:
        ok = check.execute('PRAGMA integrity_check').fetchone()[0]
        if ok != 'ok':
            tmp.unlink(missing_ok=True)
            raise ValueError(f'Respaldo inválido: {ok}')
    shutil.move(str(tmp), str(db))
    with _connect() as con:
        con.execute('UPDATE cloud_backups SET restored_at=? WHERE id=?', (_now(), backup_id))
        con.commit()
    return {'ok': True, 'restored': backup_id, 'safetyBackup': safety}


def _candidate_paths(value: str) -> list[Path]:
    raw = str(value or '').strip()
    if not raw or raw.startswith(('http://','https://','data:')):
        return []
    raw = raw.replace('\\','/')
    if raw.startswith('/media/'):
        raw = 'data/' + raw[len('/media/'):]
    raw = raw.lstrip('./')
    return [BACKEND / raw, BACKEND / 'data' / raw, Path(raw)]


def _encoded_variant(path: Path, *, edge: int, quality: int, suffix: str) -> dict[str, str]:
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert('RGB')
        img.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        img.save(output, 'WEBP', quality=max(55,min(quality,95)), method=6)
    data = output.getvalue()
    digest = hashlib.sha256(data).hexdigest()[:16]
    return {
        'filename': f'{path.stem}-{suffix}-{digest}',
        'extension': 'webp',
        'content_type': 'image/webp',
        'base64': base64.b64encode(data).decode('ascii'),
        'sha256': hashlib.sha256(data).hexdigest(),
        'bytes': str(len(data)),
        'variant': suffix,
    }


def _image_uploads(product: dict[str, Any], config: dict[str, Any]) -> list[dict[str, str]]:
    uploads: list[dict[str, str]] = []
    seen: set[str] = set()
    max_mb = float(config.get('max_image_mb') or 14)
    quality = int(config.get('image_quality') or 86)
    max_edge = int(config.get('max_image_edge') or 1800)
    thumb_edge = int(config.get('thumbnail_edge') or 480)
    for value in product.get('images') or []:
        for candidate in _candidate_paths(str(value)):
            if not candidate.exists() or not candidate.is_file():
                continue
            resolved = str(candidate.resolve())
            if resolved in seen:
                break
            seen.add(resolved)
            if candidate.stat().st_size > max_mb * 1024 * 1024:
                break
            try:
                uploads.append(_encoded_variant(candidate, edge=max_edge, quality=quality, suffix='web'))
                uploads.append(_encoded_variant(candidate, edge=thumb_edge, quality=max(68, quality-8), suffix='thumb'))
            except Exception:
                mime = mimetypes.guess_type(candidate.name)[0] or 'application/octet-stream'
                raw = candidate.read_bytes()
                uploads.append({
                    'filename': candidate.stem,
                    'extension': candidate.suffix.lower().lstrip('.') or 'bin',
                    'content_type': mime,
                    'base64': base64.b64encode(raw).decode('ascii'),
                    'sha256': hashlib.sha256(raw).hexdigest(),
                    'bytes': str(len(raw)),
                    'variant': 'original',
                })
            break
    return uploads


def _normalize(product: dict[str, Any], config: dict[str, Any], include_uploads: bool = True) -> dict[str, Any]:
    mapped = {
        'id': str(product.get('id') or ''),
        'slug': str(product.get('slug') or ''),
        'title': str(product.get('title') or product.get('name') or 'Producto Elegance'),
        'description': str(product.get('description') or ''),
        'brand': str(product.get('brand') or ''),
        'model': str(product.get('model') or ''),
        'category': str(product.get('category') or 'Otros'),
        'subcategory': str(product.get('subcategory') or ''),
        'gender': str(product.get('gender') or ''),
        'sizes': list(product.get('sizes') or []),
        'colors': list(product.get('colors') or []),
        'keywords': list(product.get('keywords') or []),
        'stock': int(product.get('stock') or 0),
        'available': bool(product.get('available')),
        'low_stock': bool(product.get('lowStock') or product.get('low_stock')),
        'price': float(product.get('price') or 0),
        'promotion_price': product.get('promotionPrice'),
        'effective_price': float(product.get('effectivePrice') or product.get('price') or 0),
        'featured': bool(product.get('featured')),
        'status': str(product.get('status') or 'published'),
        'images': [x for x in (product.get('images') or []) if str(x).startswith(('http://','https://'))],
        'source_updated_at': str(product.get('updatedAt') or _now()),
    }
    signature = json.dumps(mapped, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')
    mapped['source_hash'] = hashlib.sha256(signature).hexdigest()
    if include_uploads and config.get('upload_images', True):
        mapped['image_uploads'] = _image_uploads(product, config)
    return mapped


def _history(con: sqlite3.Connection, queue_id: str | None, product_id: str | None, event: str, success: bool, detail: Any) -> None:
    con.execute('INSERT INTO cloud_sync_history(id,queue_id,product_id,event,success,detail,created_at) VALUES(?,?,?,?,?,?,?)',
                (uuid.uuid4().hex, queue_id, product_id, event, 1 if success else 0,
                 json.dumps(detail, ensure_ascii=False, default=str), _now()))


def enqueue_products(products: list[dict[str, Any]], *, backup: bool = True, force: bool = False) -> dict[str, Any]:
    config = load_cloud_config()
    backup_item = create_backup('before_sync_batch') if backup and products else None
    queued = skipped = 0
    ids: list[str] = []
    with _connect() as con:
        for product in products:
            normalized = _normalize(product, config, include_uploads=False)
            product_id = normalized['id']
            if not product_id:
                skipped += 1
                continue
            state = con.execute('SELECT source_hash FROM cloud_sync_state WHERE product_id=?', (product_id,)).fetchone()
            pending = con.execute("SELECT id FROM cloud_sync_queue WHERE product_id=? AND source_hash=? AND status IN ('pending','processing','retry') LIMIT 1", (product_id, normalized['source_hash'])).fetchone()
            if not force and ((state and state['source_hash'] == normalized['source_hash']) or pending):
                skipped += 1
                continue
            qid = uuid.uuid4().hex
            con.execute('INSERT INTO cloud_sync_queue(id,operation,product_id,payload,source_hash,status,attempts,max_attempts,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (qid, 'upsert', product_id, json.dumps(product, ensure_ascii=False, default=str), normalized['source_hash'], 'pending', 0, int(config.get('max_attempts') or 5), _now(), _now()))
            _history(con, qid, product_id, 'queued', True, {'sourceHash': normalized['source_hash']})
            ids.append(qid); queued += 1
        con.commit()
    start_worker(); _WAKE.set()
    return {'ok': True, 'queued': queued, 'skippedUnchanged': skipped, 'queueIds': ids, 'backup': backup_item}


def _send_one(row: sqlite3.Row, config: dict[str, Any]) -> dict[str, Any]:
    key = str(config.get('sync_key') or '').strip()
    if not key:
        raise RuntimeError('Falta la clave segura de sincronización.')
    product = json.loads(row['payload'])
    normalized = _normalize(product, config, include_uploads=True)
    response = requests.post(
        str(config['sync_endpoint']),
        json={'action': 'sync', 'products': [normalized]},
        headers={'x-elegance-sync-key': key, 'content-type': 'application/json'},
        timeout=float(config.get('timeout_seconds') or 90),
    )
    try:
        data = response.json()
    except Exception:
        data = {'error': response.text[:1500]}
    if response.status_code >= 400 or not data.get('ok', False):
        raise RuntimeError(data.get('error') or f'HTTP {response.status_code}')
    return data


def process_queue(limit: int = 10) -> dict[str, Any]:
    config = load_cloud_config()
    processed = succeeded = failed = 0
    with _connect() as con:
        rows = con.execute("SELECT * FROM cloud_sync_queue WHERE status IN ('pending','retry') AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY created_at LIMIT ?", (_now(), max(1,min(limit,50)))).fetchall()
    for row in rows:
        processed += 1
        with _connect() as con:
            con.execute("UPDATE cloud_sync_queue SET status='processing',attempts=attempts+1,updated_at=? WHERE id=?", (_now(), row['id']))
            con.commit()
        try:
            result = _send_one(row, config)
            image_urls: list[str] = []
            for item in result.get('results') or []:
                image_urls.extend(item.get('images') or [])
            with _connect() as con:
                con.execute("UPDATE cloud_sync_queue SET status='completed',completed_at=?,updated_at=?,last_error=NULL WHERE id=?", (_now(),_now(),row['id']))
                con.execute('INSERT INTO cloud_sync_state(product_id,source_hash,cloud_updated_at,image_urls,last_queue_id,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET source_hash=excluded.source_hash,cloud_updated_at=excluded.cloud_updated_at,image_urls=excluded.image_urls,last_queue_id=excluded.last_queue_id,updated_at=excluded.updated_at',
                            (row['product_id'], row['source_hash'], _now(), json.dumps(image_urls), row['id'], _now()))
                _history(con,row['id'],row['product_id'],'completed',True,result)
                con.commit()
            succeeded += 1
        except Exception as exc:
            attempts = int(row['attempts']) + 1
            max_attempts = int(row['max_attempts'])
            terminal = attempts >= max_attempts
            delay = int(config.get('retry_base_seconds') or 15) * (2 ** max(0, attempts-1))
            next_at = datetime.fromtimestamp(time.time()+delay, timezone.utc).isoformat()
            with _connect() as con:
                con.execute("UPDATE cloud_sync_queue SET status=?,next_attempt_at=?,last_error=?,updated_at=? WHERE id=?",
                            ('failed' if terminal else 'retry', None if terminal else next_at, str(exc)[:2000], _now(), row['id']))
                _history(con,row['id'],row['product_id'],'failed' if terminal else 'retry_scheduled',False,{'error':str(exc),'attempts':attempts,'nextAttemptAt':None if terminal else next_at})
                con.commit()
            failed += 1
    return {'ok': failed == 0, 'processed': processed, 'succeeded': succeeded, 'failed': failed}


def retry_failed(queue_ids: list[str] | None = None) -> dict[str, Any]:
    with _connect() as con:
        if queue_ids:
            marks = ','.join('?' for _ in queue_ids)
            cur = con.execute(f"UPDATE cloud_sync_queue SET status='retry',attempts=0,next_attempt_at=NULL,last_error=NULL,updated_at=? WHERE id IN ({marks})", [_now(), *queue_ids])
        else:
            cur = con.execute("UPDATE cloud_sync_queue SET status='retry',attempts=0,next_attempt_at=NULL,last_error=NULL,updated_at=? WHERE status='failed'", (_now(),))
        con.commit()
    start_worker(); _WAKE.set()
    return {'ok': True, 'retried': cur.rowcount}


def queue_status(limit: int = 100) -> dict[str, Any]:
    with _connect() as con:
        counts = {r['status']: r['count'] for r in con.execute('SELECT status,COUNT(*) count FROM cloud_sync_queue GROUP BY status').fetchall()}
        rows = con.execute('SELECT id,product_id,status,attempts,max_attempts,next_attempt_at,last_error,created_at,updated_at,completed_at FROM cloud_sync_queue ORDER BY created_at DESC LIMIT ?', (max(1,min(limit,300)),)).fetchall()
    return {'ok': True, 'counts': counts, 'items': [dict(r) for r in rows]}


def sync_history(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute('SELECT * FROM cloud_sync_history ORDER BY created_at DESC LIMIT ?', (max(1,min(limit,300)),)).fetchall()
    items=[]
    for row in rows:
        item=dict(row)
        try: item['detail']=json.loads(item['detail'])
        except Exception: pass
        items.append(item)
    return items


def ping_cloud() -> dict[str, Any]:
    config = load_cloud_config()
    key = str(config.get('sync_key') or '').strip()
    if not key:
        return {'ok': False, 'configured': False, 'error': 'Falta la clave segura de sincronización.'}
    try:
        response = requests.post(str(config['sync_endpoint']), json={'action':'ping'}, headers={'x-elegance-sync-key':key}, timeout=20)
        data = response.json() if response.content else {}
        return {'configured': True, 'httpStatus': response.status_code, **data}
    except Exception as exc:
        return {'ok': False, 'configured': True, 'error': str(exc)}


def sync_public_products(products: list[dict[str, Any]], *, backup: bool = True, wait: bool = False, force: bool = False) -> dict[str, Any]:
    result = enqueue_products(products, backup=backup, force=force)
    if wait and result.get('queued'):
        result['processing'] = process_queue(limit=max(1, int(result['queued'])))
    return result


def _worker_loop() -> None:
    while True:
        try:
            process_queue(limit=5)
        except Exception:
            pass
        interval = float(load_cloud_config().get('worker_interval_seconds') or 4)
        _WAKE.wait(timeout=max(1.0, interval)); _WAKE.clear()


def start_worker() -> None:
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        thread = threading.Thread(target=_worker_loop, name='elegance-cloud-sync', daemon=True)
        thread.start(); _WORKER_STARTED = True


# Start the resilient background queue when the service is imported.
start_worker()
