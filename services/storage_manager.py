from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageOps

from services.state_store import database_path
from services.cloud_sync import load_cloud_config, create_backup
from services.runtime_config import data_dir

BACKEND = Path(__file__).resolve().parents[1]
STORE = data_dir() / 'storage_manager'
VARIANTS = STORE / 'variants'
RESTORED = data_dir() / 'restored_from_cloud'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(database_path(), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.executescript('''
    CREATE TABLE IF NOT EXISTS storage_objects(
      id TEXT PRIMARY KEY,
      product_id TEXT,
      source_path TEXT,
      variant TEXT NOT NULL,
      sha256 TEXT NOT NULL,
      size_bytes INTEGER NOT NULL,
      content_type TEXT NOT NULL,
      local_path TEXT,
      bucket TEXT NOT NULL,
      object_path TEXT NOT NULL,
      cloud_url TEXT,
      cloud_verified INTEGER NOT NULL DEFAULT 0,
      cloud_verified_at TEXT,
      status TEXT NOT NULL DEFAULT 'prepared',
      attempts INTEGER NOT NULL DEFAULT 0,
      last_error TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(sha256,variant,bucket)
    );
    CREATE INDEX IF NOT EXISTS idx_storage_objects_product ON storage_objects(product_id);
    CREATE INDEX IF NOT EXISTS idx_storage_objects_status ON storage_objects(status,updated_at);
    CREATE TABLE IF NOT EXISTS storage_history(
      id TEXT PRIMARY KEY,
      object_id TEXT,
      product_id TEXT,
      event TEXT NOT NULL,
      success INTEGER NOT NULL DEFAULT 0,
      detail TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_storage_history_created ON storage_history(created_at DESC);
    CREATE TABLE IF NOT EXISTS storage_restore_jobs(
      id TEXT PRIMARY KEY,
      object_id TEXT NOT NULL,
      target_path TEXT NOT NULL,
      expected_sha256 TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      error TEXT,
      created_at TEXT NOT NULL,
      completed_at TEXT
    );
    ''')
    con.commit()
    return con


def _history(con: sqlite3.Connection, object_id: str | None, product_id: str | None, event: str, success: bool, detail: Any) -> None:
    con.execute('INSERT INTO storage_history(id,object_id,product_id,event,success,detail,created_at) VALUES(?,?,?,?,?,?,?)',
                (uuid.uuid4().hex, object_id, product_id, event, 1 if success else 0,
                 json.dumps(detail,ensure_ascii=False,default=str), _now()))


def _resolve_path(value: str) -> Path | None:
    raw=str(value or '').strip()
    if not raw or raw.startswith(('http://','https://','data:')):
        return None
    raw=raw.replace('\\','/')
    if raw.startswith('/media/'):
        raw='data/'+raw[len('/media/'):]
    for p in (BACKEND/raw.lstrip('./'), BACKEND/'data'/raw.lstrip('./'), Path(raw)):
        if p.exists() and p.is_file():
            return p.resolve()
    return None


def _encode_image(path: Path, variant: str, edge: int, quality: int) -> tuple[bytes,str,str]:
    if variant == 'original':
        data=path.read_bytes()
        return data, mimetypes.guess_type(path.name)[0] or 'application/octet-stream', path.suffix.lower().lstrip('.') or 'bin'
    with Image.open(path) as img:
        img=ImageOps.exif_transpose(img).convert('RGB')
        img.thumbnail((edge,edge),Image.Resampling.LANCZOS)
        out=io.BytesIO(); img.save(out,'WEBP',quality=max(55,min(quality,95)),method=6)
        return out.getvalue(),'image/webp','webp'


def _prepare_one(product_id: str, source: Path, variant: str, *, edge: int, quality: int, bucket: str) -> dict[str,Any]:
    data,content_type,ext=_encode_image(source,variant,edge,quality)
    digest=_sha(data)
    folder=VARIANTS/product_id
    folder.mkdir(parents=True,exist_ok=True)
    local=folder/f'{digest}-{variant}.{ext}'
    if not local.exists(): local.write_bytes(data)
    object_path=f'products/{product_id}/{digest}-{variant}.{ext}'
    now=_now()
    with _connect() as con:
        row=con.execute('SELECT * FROM storage_objects WHERE sha256=? AND variant=? AND bucket=?',(digest,variant,bucket)).fetchone()
        if row:
            return dict(row)
        oid=uuid.uuid4().hex
        con.execute('INSERT INTO storage_objects(id,product_id,source_path,variant,sha256,size_bytes,content_type,local_path,bucket,object_path,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (oid,product_id,str(source),variant,digest,len(data),content_type,str(local),bucket,object_path,'prepared',now,now))
        _history(con,oid,product_id,'prepared',True,{'variant':variant,'sha256':digest,'bytes':len(data)})
        con.commit()
        return dict(con.execute('SELECT * FROM storage_objects WHERE id=?',(oid,)).fetchone())


def prepare_product_images(product: dict[str,Any]) -> dict[str,Any]:
    cfg=load_cloud_config(); pid=str(product.get('id') or '')
    if not pid: raise ValueError('Producto sin ID.')
    sources=[]; seen=set()
    for value in product.get('images') or []:
        p=_resolve_path(str(value))
        if p and str(p) not in seen: seen.add(str(p)); sources.append(p)
    prepared=[]; duplicates=0
    for source in sources:
        specs=[]
        if cfg.get('storage_keep_original',True): specs.append(('original',0,100,str(cfg.get('private_storage_bucket') or 'elegance-private')))
        if cfg.get('storage_keep_edited',True): specs.append(('edited',int(cfg.get('max_image_edge') or 1800),int(cfg.get('image_quality') or 86),str(cfg.get('private_storage_bucket') or 'elegance-private')))
        specs.extend([
            ('web',int(cfg.get('max_image_edge') or 1800),int(cfg.get('image_quality') or 86),str(cfg.get('public_storage_bucket') or 'elegance-public')),
            ('thumb',int(cfg.get('thumbnail_edge') or 480),max(68,int(cfg.get('image_quality') or 86)-8),str(cfg.get('public_storage_bucket') or 'elegance-public')),
        ])
        for variant,edge,quality,bucket in specs:
            before=None
            data=_prepare_one(pid,source,variant,edge=edge,quality=quality,bucket=bucket)
            prepared.append(data)
    return {'ok':True,'productId':pid,'sourceCount':len(sources),'objects':prepared,'deduplicated':duplicates}


def _edge(action: str, payload: dict[str,Any], timeout: float|None=None) -> dict[str,Any]:
    cfg=load_cloud_config(); key=str(os.getenv('ELEGANCE_SYNC_KEY','').strip() or cfg.get('sync_key') or '')
    if not key: raise RuntimeError('Falta sync_key.')
    r=requests.post(str(cfg.get('sync_endpoint')),json={'action':action,**payload},headers={'x-elegance-sync-key':key,'content-type':'application/json'},timeout=timeout or float(cfg.get('timeout_seconds') or 90))
    try: data=r.json()
    except Exception: data={'ok':False,'error':r.text[:1500]}
    if r.status_code>=400 or not data.get('ok'): raise RuntimeError(data.get('error') or f'HTTP {r.status_code}')
    return data


def upload_pending(limit: int=20) -> dict[str,Any]:
    create_backup('before_storage_upload')
    with _connect() as con:
        rows=con.execute("SELECT * FROM storage_objects WHERE status IN ('prepared','retry','failed') ORDER BY created_at LIMIT ?",(max(1,min(limit,100)),)).fetchall()
    ok=failed=0; results=[]
    for row in rows:
        local=Path(row['local_path'] or '')
        try:
            if not local.exists(): raise RuntimeError('Archivo local preparado no encontrado.')
            raw=local.read_bytes()
            if _sha(raw)!=row['sha256']: raise RuntimeError('La verificación SHA-256 local falló.')
            payload={'object':{'id':row['id'],'product_id':row['product_id'],'variant':row['variant'],'sha256':row['sha256'],'bucket':row['bucket'],'object_path':row['object_path'],'content_type':row['content_type'],'size_bytes':row['size_bytes'],'base64':base64.b64encode(raw).decode('ascii')}}
            result=_edge('storage_upload',payload)
            remote=result.get('object') or {}
            if remote.get('sha256') and remote['sha256']!=row['sha256']: raise RuntimeError('La verificación SHA-256 en nube no coincide.')
            with _connect() as con:
                con.execute("UPDATE storage_objects SET status='verified',cloud_verified=1,cloud_verified_at=?,cloud_url=?,attempts=attempts+1,last_error=NULL,updated_at=? WHERE id=?",(_now(),remote.get('url'),_now(),row['id']))
                _history(con,row['id'],row['product_id'],'uploaded_verified',True,remote); con.commit()
            ok+=1; results.append(remote)
        except Exception as exc:
            with _connect() as con:
                con.execute("UPDATE storage_objects SET status=CASE WHEN attempts+1>=5 THEN 'failed' ELSE 'retry' END,attempts=attempts+1,last_error=?,updated_at=? WHERE id=?",(str(exc)[:2000],_now(),row['id']))
                _history(con,row['id'],row['product_id'],'upload_failed',False,{'error':str(exc)}); con.commit()
            failed+=1
    return {'ok':failed==0,'processed':len(rows),'verified':ok,'failed':failed,'results':results}


def storage_status(limit:int=200)->dict[str,Any]:
    with _connect() as con:
        counts={r['status']:r['count'] for r in con.execute('SELECT status,COUNT(*) count FROM storage_objects GROUP BY status')}
        total=con.execute('SELECT COALESCE(SUM(size_bytes),0) n FROM storage_objects').fetchone()['n']
        rows=[dict(r) for r in con.execute('SELECT * FROM storage_objects ORDER BY created_at DESC LIMIT ?',(max(1,min(limit,500)),)).fetchall()]
    return {'ok':True,'counts':counts,'totalBytes':total,'objects':rows}


def safe_to_delete(product_id:str|None=None, source_path:str|None=None)->dict[str,Any]:
    clauses=['cloud_verified=1']; args=[]
    if product_id: clauses.append('product_id=?'); args.append(product_id)
    if source_path: clauses.append('source_path=?'); args.append(source_path)
    with _connect() as con:
        verified=con.execute(f"SELECT COUNT(*) n FROM storage_objects WHERE {' AND '.join(clauses)}",args).fetchone()['n']
        q=['cloud_verified=0']
        a=[]
        if product_id: q.append('product_id=?'); a.append(product_id)
        if source_path: q.append('source_path=?'); a.append(source_path)
        unsafe=con.execute(f"SELECT COUNT(*) n FROM storage_objects WHERE {' AND '.join(q)}",a).fetchone()['n']
    return {'ok':True,'safe':verified>0 and unsafe==0,'verifiedObjects':verified,'unverifiedObjects':unsafe,'message':'El archivo puede borrarse: todas sus variantes están verificadas en la nube.' if verified>0 and unsafe==0 else 'No borres todavía: faltan copias verificadas en la nube.'}


def restore_object(object_id:str,target_folder:str|None=None)->dict[str,Any]:
    with _connect() as con: row=con.execute('SELECT * FROM storage_objects WHERE id=?',(object_id,)).fetchone()
    if not row: raise ValueError('Objeto no encontrado.')
    folder=Path(target_folder) if target_folder else RESTORED
    folder.mkdir(parents=True,exist_ok=True)
    result=_edge('storage_download',{'bucket':row['bucket'],'object_path':row['object_path']},timeout=120)
    raw=base64.b64decode(result.get('base64') or '')
    if _sha(raw)!=row['sha256']: raise RuntimeError('La restauración falló la verificación SHA-256.')
    target=folder/Path(row['object_path']).name
    tmp=target.with_suffix(target.suffix+'.part'); tmp.write_bytes(raw); os.replace(tmp,target)
    with _connect() as con:
        _history(con,row['id'],row['product_id'],'restored',True,{'target':str(target),'sha256':row['sha256']}); con.commit()
    return {'ok':True,'path':str(target),'sha256':row['sha256'],'verified':True}


def inventory_cloud()->dict[str,Any]:
    return _edge('storage_inventory',{})


def cleanup_orphans(dry_run:bool=True)->dict[str,Any]:
    local=storage_status(5000)['objects']
    keep=[{'bucket':x['bucket'],'object_path':x['object_path']} for x in local if x.get('cloud_verified')]
    return _edge('storage_cleanup_orphans',{'keep':keep,'dry_run':bool(dry_run)},timeout=120)


def history(limit:int=200)->list[dict[str,Any]]:
    with _connect() as con: rows=con.execute('SELECT * FROM storage_history ORDER BY created_at DESC LIMIT ?',(max(1,min(limit,500)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r)
        try:d['detail']=json.loads(d['detail'])
        except Exception:pass
        out.append(d)
    return out
