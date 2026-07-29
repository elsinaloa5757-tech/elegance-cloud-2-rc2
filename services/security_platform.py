from __future__ import annotations

import base64, hashlib, hmac, json, os, secrets, shutil, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.state_store import database_path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
BACKUPS = DATA / 'secure_backups'
ENV_FILE = ROOT / '.env'
ROLES = {
    'owner': {'*'},
    'admin': {'dashboard','inventory','catalog','studio','ai','customers','orders','payments','users','backups'},
    'seller': {'dashboard','inventory:view','catalog:view','customers','orders','payments'},
    'catalog_editor': {'dashboard','inventory:view','catalog','studio','ai'},
}
PUBLIC_PREFIXES = ('/catalog','/api/public','/health','/api/health','/manifest.webmanifest','/sw.js','/offline','/static','/assets','/docs','/openapi.json','/favicon')
PUBLIC_EXACT = {'/','/login','/setup','/api/auth/status','/api/auth/setup','/api/auth/login','/api/system/status','/api/system/deployment-readiness','/api/system/home-server','/robots.txt','/sitemap.xml','/system-status'}

def _db() -> sqlite3.Connection:
    conn=sqlite3.connect(database_path(), timeout=30)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn

def now() -> str: return datetime.now(timezone.utc).isoformat()

def migrate_security() -> dict[str,Any]:
    DATA.mkdir(parents=True,exist_ok=True); BACKUPS.mkdir(parents=True,exist_ok=True)
    with _db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS auth_users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, role TEXT NOT NULL, password_hash TEXT NOT NULL, salt TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, failed_attempts INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at REAL NOT NULL, created_at TEXT NOT NULL, ip TEXT, user_agent TEXT, FOREIGN KEY(user_id) REFERENCES auth_users(id));
        CREATE TABLE IF NOT EXISTS auth_audit(id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, user_id TEXT, username TEXT, detail TEXT, ip TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS password_recovery(id TEXT PRIMARY KEY, user_id TEXT NOT NULL, token_hash TEXT NOT NULL, expires_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        ''')
    return {'status':'ok','users':user_count(),'database':database_path()}

def user_count()->int:
    with _db() as c: return int(c.execute('SELECT COUNT(*) FROM auth_users').fetchone()[0])

def owner_count() -> int:
    migrate_security_schema_only()
    with _db() as c:
        return int(c.execute("SELECT COUNT(*) FROM auth_users WHERE role='owner' AND active=1").fetchone()[0])


def migrate_security_schema_only() -> None:
    DATA.mkdir(parents=True,exist_ok=True); BACKUPS.mkdir(parents=True,exist_ok=True)
    with _db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS auth_users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, role TEXT NOT NULL, password_hash TEXT NOT NULL, salt TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, failed_attempts INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at REAL NOT NULL, created_at TEXT NOT NULL, ip TEXT, user_agent TEXT, FOREIGN KEY(user_id) REFERENCES auth_users(id));
        CREATE TABLE IF NOT EXISTS auth_audit(id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, user_id TEXT, username TEXT, detail TEXT, ip TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS password_recovery(id TEXT PRIMARY KEY, user_id TEXT NOT NULL, token_hash TEXT NOT NULL, expires_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        ''')


def repair_owner_state() -> dict[str, Any]:
    migrate_security_schema_only()
    with _db() as c:
        users=int(c.execute('SELECT COUNT(*) FROM auth_users').fetchone()[0])
        owners=int(c.execute("SELECT COUNT(*) FROM auth_users WHERE role='owner' AND active=1").fetchone()[0])
        if users == 0:
            return {'status':'empty','users':0,'owners':0,'promoted':None}
        if owners > 0:
            return {'status':'ok','users':users,'owners':owners,'promoted':None}
        row=c.execute("SELECT id,username FROM auth_users WHERE active=1 ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END, created_at LIMIT 1").fetchone()
        if not row:
            return {'status':'no-active-user','users':users,'owners':0,'promoted':None}
        c.execute("UPDATE auth_users SET role='owner',updated_at=? WHERE id=?",(now(),row['id']))
        c.execute('INSERT INTO auth_audit(event,user_id,username,detail,ip,created_at) VALUES(?,?,?,?,?,?)',('owner_repaired',row['id'],row['username'],'Promoción automática por ausencia de propietario activo.','',now()))
        return {'status':'repaired','users':users,'owners':1,'promoted':row['username']}


def setup_required()->bool:
    return repair_owner_state().get('users',0) == 0

def _hash(password:str,salt:bytes|None=None)->tuple[str,str]:
    salt=salt or secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,310000)
    return base64.b64encode(digest).decode(),base64.b64encode(salt).decode()

def _valid_password(password:str)->None:
    if len(password)<10 or not any(x.isupper() for x in password) or not any(x.islower() for x in password) or not any(x.isdigit() for x in password):
        raise ValueError('La contraseña debe tener al menos 10 caracteres, mayúscula, minúscula y número.')

def audit(event:str,user_id:str='',username:str='',detail:Any='',ip:str='')->None:
    if not isinstance(detail,str): detail=json.dumps(detail,ensure_ascii=False)
    with _db() as c: c.execute('INSERT INTO auth_audit(event,user_id,username,detail,ip,created_at) VALUES(?,?,?,?,?,?)',(event,user_id,username,detail[:2000],ip,now()))

def create_owner(username:str,password:str,display_name:str='Propietario')->dict:
    migrate_security()
    if not setup_required(): raise ValueError('El propietario inicial ya fue configurado.')
    _valid_password(password); username=username.strip().lower()
    if len(username)<3: raise ValueError('El usuario debe tener al menos 3 caracteres.')
    ph,salt=_hash(password); uid=secrets.token_hex(12)
    with _db() as c: c.execute('INSERT INTO auth_users VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uid,username,display_name.strip() or 'Propietario','owner',ph,salt,1,0,0,now(),now()))
    audit('owner_setup',uid,username)
    return {'id':uid,'username':username,'role':'owner'}

def create_user(payload:dict,actor:dict)->dict:
    if actor.get('role') not in ('owner','admin'): raise PermissionError('Permiso insuficiente.')
    role=str(payload.get('role','seller'))
    if role not in ROLES or (role=='owner' and actor.get('role')!='owner'): raise ValueError('Rol no permitido.')
    username=str(payload.get('username','')).strip().lower(); password=str(payload.get('password',''))
    _valid_password(password)
    ph,salt=_hash(password); uid=secrets.token_hex(12)
    try:
        with _db() as c: c.execute('INSERT INTO auth_users VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uid,username,str(payload.get('displayName') or username),role,ph,salt,1,0,0,now(),now()))
    except sqlite3.IntegrityError as exc: raise ValueError('Ese usuario ya existe.') from exc
    audit('user_created',actor['id'],actor['username'],{'created':username,'role':role})
    return {'id':uid,'username':username,'role':role}

def login(username:str,password:str,ip:str='',ua:str='')->dict:
    migrate_security(); username=username.strip().lower()
    with _db() as c: row=c.execute('SELECT * FROM auth_users WHERE username=?',(username,)).fetchone()
    if not row or not row['active']:
        audit('login_failed','',username,'unknown_or_inactive',ip); raise ValueError('Credenciales incorrectas.')
    if float(row['locked_until'])>time.time(): raise ValueError('Usuario bloqueado temporalmente. Intenta más tarde.')
    expected,_=_hash(password,base64.b64decode(row['salt']))
    if not hmac.compare_digest(expected,row['password_hash']):
        attempts=int(row['failed_attempts'])+1; lock=time.time()+900 if attempts>=5 else 0
        with _db() as c: c.execute('UPDATE auth_users SET failed_attempts=?,locked_until=?,updated_at=? WHERE id=?',(0 if lock else attempts,lock,now(),row['id']))
        audit('login_failed',row['id'],username,{'attempts':attempts,'locked':bool(lock)},ip); raise ValueError('Credenciales incorrectas.')
    token=secrets.token_urlsafe(40); th=hashlib.sha256(token.encode()).hexdigest(); expires=time.time()+8*3600
    with _db() as c:
        c.execute('UPDATE auth_users SET failed_attempts=0,locked_until=0,updated_at=? WHERE id=?',(now(),row['id']))
        c.execute('DELETE FROM auth_sessions WHERE expires_at<?',(time.time(),))
        c.execute('INSERT INTO auth_sessions VALUES(?,?,?,?,?,?)',(th,row['id'],expires,now(),ip,ua[:500]))
    audit('login_success',row['id'],username,'',ip)
    return {'token':token,'expiresAt':expires,'user':{'id':row['id'],'username':username,'displayName':row['display_name'],'role':row['role']}}

def session_user(token:str)->dict|None:
    if not token:return None
    th=hashlib.sha256(token.encode()).hexdigest()
    with _db() as c:
        r=c.execute('SELECT u.* FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1',(th,time.time())).fetchone()
    return dict(r) if r else None

def logout(token:str,user:dict|None=None)->None:
    if token:
        with _db() as c:c.execute('DELETE FROM auth_sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
    if user:audit('logout',user['id'],user['username'])

def change_password(user:dict,current:str,new:str)->None:
    _valid_password(new)
    with _db() as c:r=c.execute('SELECT * FROM auth_users WHERE id=?',(user['id'],)).fetchone()
    expected,_=_hash(current,base64.b64decode(r['salt']))
    if not hmac.compare_digest(expected,r['password_hash']):raise ValueError('Contraseña actual incorrecta.')
    ph,salt=_hash(new)
    with _db() as c:
        c.execute('UPDATE auth_users SET password_hash=?,salt=?,updated_at=? WHERE id=?',(ph,salt,now(),user['id']))
        c.execute('DELETE FROM auth_sessions WHERE user_id=?',(user['id'],))
    audit('password_changed',user['id'],user['username'])

def list_users()->list[dict]:
    with _db() as c: rows=c.execute('SELECT id,username,display_name,role,active,created_at,updated_at FROM auth_users ORDER BY created_at').fetchall()
    return [dict(x) for x in rows]

def list_audit(limit:int=100)->list[dict]:
    with _db() as c: rows=c.execute('SELECT * FROM auth_audit ORDER BY id DESC LIMIT ?',(max(1,min(limit,500)),)).fetchall()
    return [dict(x) for x in rows]

def has_permission(user:dict,module:str)->bool:
    perms=ROLES.get(user.get('role',''),set())
    return '*' in perms or module in perms or module.split(':')[0] in perms

def is_public(path:str)->bool:
    return path in PUBLIC_EXACT or any(path.startswith(x) for x in PUBLIC_PREFIXES)

def backup_database(reason:str='manual')->dict:
    migrate_security(); src=Path(database_path()); stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f'); dest=BACKUPS/f'elegance_secure_{stamp}.sqlite3'
    with _db() as c: c.execute('PRAGMA wal_checkpoint(FULL)')
    shutil.copy2(src,dest); digest=hashlib.sha256(dest.read_bytes()).hexdigest(); audit('backup_created',detail={'reason':reason,'file':dest.name,'sha256':digest})
    return {'status':'ok','file':str(dest),'name':dest.name,'sha256':digest,'size':dest.stat().st_size}

def restore_database(name:str,confirm:bool)->dict:
    if not confirm: raise ValueError('La restauración requiere confirm=true.')
    safe=Path(name).name; src=BACKUPS/safe
    if not src.exists():raise ValueError('Respaldo no encontrado.')
    pre=backup_database('pre_restore'); target=Path(database_path()); shutil.copy2(src,target)
    with _db() as c: integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity!='ok': shutil.copy2(Path(pre['file']),target); raise RuntimeError('El respaldo no pasó la verificación de integridad.')
    migrate_security(); audit('backup_restored',detail={'file':safe})
    return {'status':'ok','restored':safe,'integrity':integrity,'preRestoreBackup':pre['name']}

def list_backups()->list[dict]:
    out=[]
    for p in sorted(BACKUPS.glob('*.sqlite3'),reverse=True): out.append({'name':p.name,'size':p.stat().st_size,'modified':datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat()})
    return out

def system_status()->dict:
    p=Path(database_path());
    try:
        with _db() as c: integrity=c.execute('PRAGMA quick_check').fetchone()[0]
    except Exception as exc: integrity=f'error: {exc}'
    return {'status':'ok' if integrity=='ok' else 'degraded','version':'5.1.0-rc1','setupRequired':setup_required(),'database':{'path':str(p),'exists':p.exists(),'size':p.stat().st_size if p.exists() else 0,'integrity':integrity},'security':{'httpsReady':True,'roles':list(ROLES),'sessionHours':8},'pwa':{'manifest':True,'serviceWorker':True,'offline':True},'repository':{'current':'sqlite','future':['postgresql','supabase']}}

def ensure_release_backup(release:str='5.1.0-rc1')->dict:
    """Creates one immutable pre-migration copy per release, before startup migrations."""
    DATA.mkdir(parents=True,exist_ok=True); BACKUPS.mkdir(parents=True,exist_ok=True)
    marker=BACKUPS/f'.pre_migration_{release}'
    if marker.exists(): return {'status':'ok','created':False,'release':release}
    src=Path(database_path())
    if src.exists() and src.stat().st_size:
        stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        dest=BACKUPS/f'elegance_pre_migration_{release.replace(".","_")}_{stamp}.sqlite3'
        shutil.copy2(src,dest)
        marker.write_text(dest.name,encoding='utf-8')
        return {'status':'ok','created':True,'file':dest.name,'release':release}
    marker.write_text('no-existing-database',encoding='utf-8')
    return {'status':'ok','created':False,'release':release}
