from __future__ import annotations
import os, sqlite3
from pathlib import Path
from typing import Any
from services.runtime_config import data_dir, database_file
from services.security_platform import repair_owner_state
from services.legacy_recovery import recovery_report


def _count(conn: sqlite3.Connection, table: str) -> int | None:
    try:return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except sqlite3.Error:return None


def system_check() -> dict[str, Any]:
    db=database_file(); data=data_dir(); result={'status':'ok','database':str(db),'dataDir':str(data),'databaseExists':db.exists(),'checks':[]}
    def add(key,label,ok,detail=''):
        result['checks'].append({'key':key,'label':label,'ok':bool(ok),'detail':str(detail)})
    add('server','Servidor activo',True,'FastAPI respondió correctamente')
    add('data_dir','Carpeta persistente',data.exists(),data)
    add('database','Base encontrada',db.exists(),db)
    if not db.exists():
        result['status']='attention'; return result
    try:
        with sqlite3.connect(db) as c:
            integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
            add('integrity','Integridad SQLite',integrity=='ok',integrity)
            repair=repair_owner_state()
            users=_count(c,'auth_users') or 0
            owners=int(c.execute("SELECT COUNT(*) FROM auth_users WHERE role='owner' AND active=1").fetchone()[0]) if users else 0
            products=next((x for x in (_count(c,'catalog_products'),_count(c,'products')) if x is not None),0)
            add('users','Usuarios encontrados',users>0,users)
            add('owner','Propietario encontrado',owners>0,owners)
            add('products','Catálogo accesible',products is not None,products)
            result.update({'integrity':integrity,'users':users,'owners':owners,'products':products,'ownerRepair':repair})
    except sqlite3.Error as exc:
        add('sqlite','Apertura de base',False,exc); result['status']='error'
    media=data/'media_library'; add('media','Biblioteca multimedia',media.exists(),media)
    backups=data/'backups'; count=len(list(backups.glob('*'))) if backups.exists() else 0
    add('backups','Respaldos disponibles',count>0,count)
    result['backupCount']=count
    try:
        rr=recovery_report(); recoverable=sum(len(x.get('tables',[])) for x in rr.get('recoverable',[]))
        add('legacy_recovery','Datos históricos recuperables',recoverable==0,recoverable)
        result['recoverableTables']=recoverable
    except Exception as exc:
        add('legacy_recovery','Análisis histórico',False,exc)
    if any(not x['ok'] for x in result['checks'] if x['key'] in {'database','integrity','users','owner'}): result['status']='attention'
    return result
