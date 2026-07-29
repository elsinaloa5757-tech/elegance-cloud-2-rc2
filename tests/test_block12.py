from pathlib import Path
import importlib, sqlite3


def test_block12_files_exist():
    root=Path(__file__).resolve().parents[1]
    assert (root/'services/legacy_recovery.py').exists()
    assert (root/'server_windows/Actualizar-Bloque12.ps1').exists()


def test_recovery_fills_only_empty_tables(monkeypatch,tmp_path):
    data=tmp_path/'data'; data.mkdir()
    target=data/'elegance.sqlite3'
    old=tmp_path/'updates'/'old'/'data'; old.mkdir(parents=True)
    source=old/'elegance.sqlite3'
    with sqlite3.connect(target) as c:
        c.execute('CREATE TABLE products(id TEXT PRIMARY KEY,title TEXT)')
        c.execute('CREATE TABLE customers(id TEXT PRIMARY KEY,name TEXT)')
        c.execute("INSERT INTO customers VALUES('c1','Actual')")
    with sqlite3.connect(source) as c:
        c.execute('CREATE TABLE products(id TEXT PRIMARY KEY,title TEXT)')
        c.execute('CREATE TABLE customers(id TEXT PRIMARY KEY,name TEXT)')
        c.execute("INSERT INTO products VALUES('p1','Tenis recuperado')")
        c.execute("INSERT INTO customers VALUES('c2','Anterior')")
    monkeypatch.setenv('ELEGANCE_DATA_DIR',str(data))
    monkeypatch.setenv('ELEGANCE_SQLITE_PATH',str(target))
    import services.runtime_config as rc, services.legacy_recovery as lr
    importlib.reload(rc); importlib.reload(lr)
    result=lr.recover_empty_business_data()
    assert result['imported']['products']==1
    with sqlite3.connect(target) as c:
        assert c.execute('SELECT COUNT(*) FROM products').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM customers').fetchone()[0]==1
