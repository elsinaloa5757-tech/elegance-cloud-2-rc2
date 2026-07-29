from __future__ import annotations
import hashlib, json, os, shutil, sqlite3, tempfile, zipfile
from datetime import datetime, timezone
from pathlib import Path
from services.state_store import database_path
from services.runtime_config import data_dir

ROOT=Path(__file__).resolve().parents[1]
DATA=data_dir()
BACKUPS=DATA/'full_backups'
EXCLUDE_DIRS={'full_backups','exports','__pycache__'}

def _now(): return datetime.now(timezone.utc).isoformat()
def _sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
 return h.hexdigest()
def _integrity(db:Path)->str:
 try:
  with sqlite3.connect(db) as c:return str(c.execute('PRAGMA integrity_check').fetchone()[0])
 except Exception as exc:return f'error: {exc}'
def create_full_backup(reason:str='manual')->dict:
 BACKUPS.mkdir(parents=True,exist_ok=True)
 db=Path(database_path())
 if db.exists():
  with sqlite3.connect(db) as c:c.execute('PRAGMA wal_checkpoint(FULL)')
 stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
 target=BACKUPS/f'elegance_full_{stamp}.zip'
 manifest={'format':1,'createdAt':_now(),'reason':reason,'databaseIntegrity':_integrity(db),'files':[]}
 with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for p in sorted(DATA.rglob('*')):
   if not p.is_file() or any(part in EXCLUDE_DIRS for part in p.relative_to(DATA).parts):continue
   rel=p.relative_to(DATA).as_posix()
   z.write(p,'data/'+rel)
   manifest['files'].append({'path':'data/'+rel,'size':p.stat().st_size,'sha256':_sha(p)})
  z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
 digest=_sha(target)
 return {'status':'ok','name':target.name,'size':target.stat().st_size,'sha256':digest,'createdAt':manifest['createdAt'],'integrity':manifest['databaseIntegrity']}
def list_full_backups()->list[dict]:
 BACKUPS.mkdir(parents=True,exist_ok=True);out=[]
 for p in sorted(BACKUPS.glob('elegance_full_*.zip'),reverse=True):
  ok=True;created=datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat();reason='';count=0
  try:
   with zipfile.ZipFile(p) as z:
    bad=z.testzip();ok=bad is None
    m=json.loads(z.read('manifest.json'));created=m.get('createdAt',created);reason=m.get('reason','');count=len(m.get('files',[]))
  except Exception:ok=False
  out.append({'name':p.name,'size':p.stat().st_size,'modified':created,'reason':reason,'fileCount':count,'valid':ok,'sha256':_sha(p)})
 return out
def restore_full_backup(name:str,confirm:bool)->dict:
 if not confirm:raise ValueError('La restauración requiere confirmación explícita.')
 safe=Path(name).name;src=BACKUPS/safe
 if not src.exists() or src.suffix.lower()!='.zip':raise ValueError('Respaldo completo no encontrado.')
 with zipfile.ZipFile(src) as z:
  if z.testzip() is not None:raise ValueError('El ZIP de respaldo está dañado.')
  manifest=json.loads(z.read('manifest.json'))
  members={x.filename:x for x in z.infolist() if x.filename.startswith('data/') and not x.is_dir()}
  for item in manifest.get('files',[]):
   n=item['path'];info=members.get(n)
   if not info:raise ValueError(f'Falta un archivo del respaldo: {n}')
   if hashlib.sha256(z.read(n)).hexdigest()!=item['sha256']:raise ValueError(f'Archivo alterado en el respaldo: {n}')
 pre=create_full_backup('pre_restore')
 with tempfile.TemporaryDirectory(prefix='elegance_restore_') as td:
  tmp=Path(td)
  with zipfile.ZipFile(src) as z:z.extractall(tmp)
  restored=tmp/'data';candidate=restored/'elegance.sqlite3'
  if not candidate.exists() or _integrity(candidate)!='ok':raise ValueError('La base principal del respaldo no pasó la verificación de integridad.')
  for p in restored.rglob('*'):
   if p.is_file():
    rel=p.relative_to(restored);dest=DATA/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
 return {'status':'ok','restored':safe,'preRestoreBackup':pre['name'],'integrity':'ok','restartRequired':True}
