from __future__ import annotations
import hashlib, json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from services.state_store import database_path
DB=Path(database_path()); DATA=DB.parent; LIB=DATA/'media_library'; ORIGINALS=LIB/'originals'; DERIVATIVES=LIB/'derivatives'; TRASH=LIB/'trash'
for p in (ORIGINALS,DERIVATIVES,TRASH): p.mkdir(parents=True,exist_ok=True)
def _now(): return datetime.now(timezone.utc).isoformat()
def _db():
 c=sqlite3.connect(DB,timeout=30); c.row_factory=sqlite3.Row; return c
def migrate_media_library():
 with _db() as c:
  c.executescript("""
  CREATE TABLE IF NOT EXISTS media_assets(id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,original_name TEXT NOT NULL DEFAULT '',stored_path TEXT NOT NULL,media_type TEXT NOT NULL DEFAULT 'image',kind TEXT NOT NULL DEFAULT 'original',status TEXT NOT NULL DEFAULT 'active',product_id TEXT NOT NULL DEFAULT '',source TEXT NOT NULL DEFAULT 'upload',parent_id TEXT NOT NULL DEFAULT '',metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
  CREATE UNIQUE INDEX IF NOT EXISTS idx_media_sha_kind_path ON media_assets(sha256,kind,stored_path);
  CREATE INDEX IF NOT EXISTS idx_media_product ON media_assets(product_id,status);
  CREATE INDEX IF NOT EXISTS idx_media_status ON media_assets(status,created_at);
  CREATE TABLE IF NOT EXISTS publication_settings(id INTEGER PRIMARY KEY CHECK(id=1),public_base_url TEXT NOT NULL DEFAULT '',auto_sync INTEGER NOT NULL DEFAULT 1,preserve_history INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);
  """)
  c.execute("INSERT OR IGNORE INTO publication_settings VALUES(1,'',1,1,?)",(_now(),))
 return {'status':'ok','database':str(DB),'library':str(LIB)}
def get_asset(asset_id):
 with _db() as c:r=c.execute('SELECT * FROM media_assets WHERE id=?',(asset_id,)).fetchone()
 if not r: raise KeyError('Archivo no encontrado.')
 x=dict(r); x['metadata']=json.loads(x.pop('metadata_json') or '{}'); return x
def register_bytes(data:bytes,filename:str,product_id:str='',source:str='upload',kind:str='original',metadata:dict|None=None):
 migrate_media_library(); digest=hashlib.sha256(data).hexdigest(); ext=Path(filename or '').suffix.lower() or '.bin'; safe=f'{digest[:24]}{ext}'; folder=ORIGINALS if kind=='original' else DERIVATIVES; path=folder/safe; duplicate=path.exists()
 if not duplicate:path.write_bytes(data)
 rel='/media/media_library/'+('originals' if kind=='original' else 'derivatives')+'/'+safe; stamp=_now(); aid='med_'+uuid.uuid4().hex
 with _db() as c:
  row=c.execute('SELECT * FROM media_assets WHERE sha256=? AND kind=? AND stored_path=?',(digest,kind,rel)).fetchone()
  if row:
   if product_id and not row['product_id']:c.execute('UPDATE media_assets SET product_id=?,updated_at=? WHERE id=?',(product_id,stamp,row['id']))
   return {'asset':dict(row),'duplicate':True,'url':rel}
  c.execute('INSERT INTO media_assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(aid,digest,filename or '',rel,'image',kind,'active',product_id,source,'',json.dumps(metadata or {},ensure_ascii=False),stamp,stamp))
 return {'asset':get_asset(aid),'duplicate':duplicate,'url':rel}
def register_existing(path_or_url:str,product_id:str='',source:str='legacy',kind:str='original'):
 value=str(path_or_url or '').strip()
 if not value:return None
 if value.startswith('/media/'):path=DATA/value[len('/media/'):]
 elif value.startswith('data/'):path=DATA.parent/value
 else:
  p=Path(value); path=p if p.is_absolute() else DATA/p
 if not path.exists() or not path.is_file():return None
 return register_bytes(path.read_bytes(),path.name,product_id,source,kind,{'legacyPath':value})
def list_assets(status='active',product_id='',limit=500):
 migrate_media_library(); q='SELECT * FROM media_assets WHERE status=?'; args=[status]
 if product_id:q+=' AND product_id=?';args.append(product_id)
 q+=' ORDER BY created_at DESC LIMIT ?';args.append(max(1,min(2000,int(limit))))
 with _db() as c:rows=c.execute(q,args).fetchall()
 out=[]
 for r in rows:
  x=dict(r);x['metadata']=json.loads(x.pop('metadata_json') or '{}');out.append(x)
 return out
def archive_asset(asset_id,status='archived'):
 if status not in {'active','archived','trash'}:raise ValueError('Estado no válido.')
 get_asset(asset_id)
 with _db() as c:c.execute('UPDATE media_assets SET status=?,updated_at=? WHERE id=?',(status,_now(),asset_id))
 return {'status':'ok','asset':get_asset(asset_id),'physicalFilePreserved':True}
def settings():
 migrate_media_library()
 with _db() as c:return dict(c.execute('SELECT * FROM publication_settings WHERE id=1').fetchone())
def update_settings(payload):
 current=settings();base=str(payload.get('public_base_url',current['public_base_url']) or '').strip().rstrip('/');auto=1 if payload.get('auto_sync',bool(current['auto_sync'])) else 0
 with _db() as c:c.execute('UPDATE publication_settings SET public_base_url=?,auto_sync=?,preserve_history=1,updated_at=? WHERE id=1',(base,auto,_now()))
 return settings()
def backfill_state_assets(state:dict):
 count=0
 for p in state.get('products',[]) if isinstance(state,dict) else []:
  pid=str(p.get('id') or ''); vals=[]
  for k in ('catalogImage','image','imagePath','approvedStudioImage'):
   if p.get(k):vals.append(p[k])
  for k in ('originalImages','images','editedImages','approvedStudioImages'):
   if isinstance(p.get(k),list):vals += [(x.get('path') if isinstance(x,dict) else x) for x in p[k]]
  for v in dict.fromkeys(str(x) for x in vals if x):
   try:
    if register_existing(v,pid):count+=1
   except Exception:pass
 return {'registered':count}
