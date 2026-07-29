\
from __future__ import annotations
import hashlib, shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path

root=Path(sys.argv[1] if len(sys.argv)>1 else r'C:\EleganceServer')
target=root/'data'/'elegance.sqlite3'

def tables(path:Path)->set[str]:
    if not path.exists():return set()
    try:
        with sqlite3.connect(path) as c:return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.Error:return set()

def count_users(path:Path)->int:
    if 'auth_users' not in tables(path):return 0
    try:
        with sqlite3.connect(path) as c:return int(c.execute('SELECT COUNT(*) FROM auth_users').fetchone()[0])
    except sqlite3.Error:return 0

def valid(path:Path)->bool:
    try:
        with sqlite3.connect(path) as c:return c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    except sqlite3.Error:return False

def ensure(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS auth_users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, role TEXT NOT NULL, password_hash TEXT NOT NULL, salt TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, failed_attempts INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at REAL NOT NULL, created_at TEXT NOT NULL, ip TEXT, user_agent TEXT);
    CREATE TABLE IF NOT EXISTS auth_audit(id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, user_id TEXT, username TEXT, detail TEXT, ip TEXT, created_at TEXT NOT NULL);
    ''')

target.parent.mkdir(parents=True,exist_ok=True)
if not target.exists():sqlite3.connect(target).close()
with sqlite3.connect(target) as c:ensure(c)

patterns=[root/'app'/'data'/'elegance.sqlite3']
for base in (root/'updates',root/'backups',root/'data'/'backups',root/'data'/'secure_backups'):
    if base.exists():patterns.extend(base.rglob('*.sqlite3'))
candidates=[]
seen=set()
for p in patterns:
    try:key=str(p.resolve()).lower()
    except OSError:key=str(p).lower()
    if key in seen or p==target:continue
    seen.add(key)
    u=count_users(p)
    if u and valid(p):candidates.append((p.stat().st_mtime,u,p))
candidates.sort(reverse=True)
source=candidates[0][2] if candidates else None
recovered=0
if count_users(target)==0 and source:
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
    backup=root/'updates'/f'pre-account-recovery-{stamp}.sqlite3';backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,backup)
    with sqlite3.connect(target) as dst,sqlite3.connect(source) as src:
        ensure(dst)
        rows=src.execute('SELECT id,username,display_name,role,password_hash,salt,active,failed_attempts,locked_until,created_at,updated_at FROM auth_users').fetchall()
        dst.executemany('INSERT OR IGNORE INTO auth_users VALUES(?,?,?,?,?,?,?,?,?,?,?)',rows)
        dst.commit();recovered=len(rows)
with sqlite3.connect(target) as c:
    ensure(c)
    users=int(c.execute('SELECT COUNT(*) FROM auth_users').fetchone()[0])
    owners=int(c.execute("SELECT COUNT(*) FROM auth_users WHERE role='owner' AND active=1").fetchone()[0])
    if users and not owners:
        row=c.execute("SELECT id FROM auth_users WHERE active=1 ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END,created_at LIMIT 1").fetchone()
        if row:c.execute("UPDATE auth_users SET role='owner' WHERE id=?",(row[0],));c.commit();owners=1
print(f'RECOVERED_USERS={recovered}')
print(f'TARGET_USERS={users}')
print(f'TARGET_OWNERS={owners}')
print(f'SOURCE={source or "NONE"}')
