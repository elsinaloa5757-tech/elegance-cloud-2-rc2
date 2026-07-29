from __future__ import annotations
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_migration_dry_run(tmp_path: Path):
    db = tmp_path / "sample.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("create table products(id integer primary key, name text not null, price real, image blob)")
        conn.execute("insert into products values(1,'Prueba',1299.5,?)", (b'abc',))
    report = tmp_path / "report.json"
    result = subprocess.run([sys.executable, str(ROOT/'scripts/sqlite_to_postgres.py'), '--sqlite', str(db), '--dry-run', '--manifest', str(report)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(report.read_text(encoding='utf-8'))
    assert payload['tables'] == 1
    assert payload['sourceManifest']['products']['rows'] == 1
    assert len(payload['sourceManifest']['products']['sha256']) == 64


def test_application_creation(monkeypatch):
    monkeypatch.setenv('ELEGANCE_ENV','development')
    from api.app import create_app
    app = create_app()
    assert app.title == 'Elegance AI'
