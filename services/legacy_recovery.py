from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.runtime_config import data_dir, database_file

BUSINESS_TABLES = [
    'catalog_products','products','product_variants','product_media_assets','product_media_outputs',
    'customers','orders','order_items','sales','sale_items','layaways','layaway_payments',
    'payments','shipments','inventory_movements','categories','public_requests'
]
MEDIA_DIR_NAMES = ('media_library','uploads','processed','edited','thumbnails')


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _integrity(path: Path) -> bool:
    try:
        with _connect(path) as c:
            return c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    except sqlite3.Error:
        return False


def _tables(c: sqlite3.Connection) -> set[str]:
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _count(c: sqlite3.Connection, table: str) -> int:
    try:
        return int(c.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except sqlite3.Error:
        return 0


def candidate_databases(install_root: Path | None = None) -> list[Path]:
    data = data_dir()
    root = install_root or data.parent
    candidates: set[Path] = set()
    locations = [data, root/'app', root/'updates', root/'backups', data/'backups', data/'secure_backups']
    for loc in locations:
        if loc.exists():
            for p in loc.rglob('*.sqlite3'):
                try:
                    if p.resolve() != database_file().resolve() and p.stat().st_size > 0:
                        candidates.add(p.resolve())
                except OSError:
                    pass
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def inspect_database(path: Path) -> dict[str, Any]:
    result = {'path': str(path), 'valid': False, 'modifiedAt': None, 'size': 0, 'score': 0, 'counts': {}}
    try:
        st = path.stat(); result['size'] = st.st_size; result['modifiedAt'] = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()
        if not _integrity(path):
            result['error'] = 'integrity_check failed'; return result
        with _connect(path) as c:
            tables = _tables(c)
            counts = {t: _count(c,t) for t in BUSINESS_TABLES if t in tables}
            result['counts'] = counts
            result['tables'] = len(tables)
            result['score'] = sum(counts.values()) + len([n for n in counts.values() if n > 0]) * 100
            result['valid'] = True
    except (OSError, sqlite3.Error) as exc:
        result['error'] = str(exc)
    return result


def recovery_report() -> dict[str, Any]:
    target = database_file()
    current = inspect_database(target) if target.exists() else {'path': str(target), 'valid': False, 'counts': {}, 'score': 0}
    candidates = [inspect_database(p) for p in candidate_databases()]
    candidates = [x for x in candidates if x['valid']]
    candidates.sort(key=lambda x: (x['score'], x.get('modifiedAt') or ''), reverse=True)
    recoverable = []
    current_counts = current.get('counts', {})
    for c in candidates:
        tables = [t for t,n in c['counts'].items() if n > 0 and current_counts.get(t,0) == 0]
        if tables:
            recoverable.append({'path': c['path'], 'tables': tables, 'score': c['score'], 'counts': c['counts']})
    return {'status':'ok','generatedAt':_utc(),'target':current,'candidates':candidates[:30],'recoverable':recoverable[:20]}


def _columns(c: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in c.execute(f'PRAGMA table_info("{table}")')]


def _backup_target(target: Path) -> Path | None:
    if not target.exists(): return None
    out = data_dir()/'secure_backups'/f'elegance_pre_recovery_{datetime.now().strftime("%Y%m%d_%H%M%S")}.sqlite3'
    out.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(target); dst = sqlite3.connect(out)
    try: src.backup(dst)
    finally: src.close(); dst.close()
    return out


def _copy_empty_table(target: sqlite3.Connection, source: sqlite3.Connection, table: str) -> int:
    if table not in _tables(target) or table not in _tables(source) or _count(target,table) > 0:
        return 0
    tc, sc = _columns(target,table), _columns(source,table)
    cols = [x for x in tc if x in sc]
    if not cols: return 0
    quoted = ','.join(f'"{x}"' for x in cols); placeholders = ','.join('?' for _ in cols)
    rows = source.execute(f'SELECT {quoted} FROM "{table}"').fetchall()
    if not rows: return 0
    target.executemany(f'INSERT OR IGNORE INTO "{table}" ({quoted}) VALUES ({placeholders})', [tuple(r[x] for x in cols) for r in rows])
    return target.total_changes


def _copy_media(root: Path) -> dict[str,int]:
    target = data_dir()/'media_library'; target.mkdir(parents=True,exist_ok=True)
    copied=skipped=0
    search_roots=[root/'app',root/'updates',root/'backups',data_dir()]
    for base in search_roots:
        if not base.exists(): continue
        for name in MEDIA_DIR_NAMES:
            for src_dir in base.rglob(name):
                if not src_dir.is_dir() or src_dir.resolve()==target.resolve(): continue
                for src in src_dir.rglob('*'):
                    if not src.is_file(): continue
                    try:
                        rel=src.relative_to(src_dir); dst=target/rel; dst.parent.mkdir(parents=True,exist_ok=True)
                        if dst.exists(): skipped+=1; continue
                        shutil.copy2(src,dst); copied+=1
                    except (OSError,ValueError): skipped+=1
    return {'copied':copied,'skipped':skipped}


def recover_empty_business_data() -> dict[str, Any]:
    target_path=database_file(); root=data_dir().parent
    report=recovery_report(); backup=_backup_target(target_path)
    imported: dict[str,int]={}; sources=[]
    with _connect(target_path) as target:
        target.execute('PRAGMA foreign_keys=OFF')
        for item in report['recoverable']:
            source_path=Path(item['path']); sources.append(str(source_path))
            with _connect(source_path) as source:
                for table in item['tables']:
                    if table in imported: continue
                    before=_count(target,table)
                    _copy_empty_table(target,source,table)
                    after=_count(target,table)
                    if after>before: imported[table]=after-before
            target.commit()
        target.execute('PRAGMA foreign_keys=ON')
        target.execute('PRAGMA optimize')
    media=_copy_media(root)
    manifest={'status':'ok','createdAt':_utc(),'backup':str(backup) if backup else None,'sources':sources,'imported':imported,'media':media}
    out=data_dir()/'recovery_reports'; out.mkdir(parents=True,exist_ok=True)
    p=out/f'recovery_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'; p.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest['reportFile']=str(p)
    return manifest
