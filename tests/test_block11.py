from pathlib import Path

def test_block11_files_exist():
    root=Path(__file__).resolve().parents[1]
    assert (root/'services/system_check.py').exists()
    assert (root/'web/system-check.html').exists()
    assert (root/'server_windows/Actualizar-Bloque11.ps1').exists()

def test_setup_repairs_admin(monkeypatch,tmp_path):
    monkeypatch.setenv('ELEGANCE_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('ELEGANCE_SQLITE_PATH',str(tmp_path/'elegance.sqlite3'))
    import importlib, services.runtime_config as rc, services.state_store as ss, services.security_platform as sp
    importlib.reload(rc);importlib.reload(ss);importlib.reload(sp)
    sp.migrate_security()
    ph,salt=sp._hash('Password123')
    with sp._db() as c:c.execute('INSERT INTO auth_users VALUES(?,?,?,?,?,?,?,?,?,?,?)',('1','admin','Admin','admin',ph,salt,1,0,0,sp.now(),sp.now()))
    assert sp.setup_required() is False
    with sp._db() as c: assert c.execute("SELECT role FROM auth_users WHERE id='1'").fetchone()[0]=='owner'
