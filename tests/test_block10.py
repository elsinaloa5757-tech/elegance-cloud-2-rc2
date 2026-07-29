from pathlib import Path

def test_database_diagnostics_module_exists():
    root=Path(__file__).resolve().parents[1]
    assert (root/'services'/'database_diagnostics.py').exists()

def test_database_diagnostics_page_exists():
    root=Path(__file__).resolve().parents[1]
    assert (root/'web'/'database-diagnostics.html').exists()

def test_routes_registered():
    text=(Path(__file__).resolve().parents[1]/'api'/'routes.py').read_text(encoding='utf-8')
    assert '/api/admin/database/diagnostics' in text
    assert '/database-diagnostics' in text

def test_account_recovery_helper_exists():
    root=Path(__file__).resolve().parents[1]
    assert (root/'server_windows'/'Recuperar-Cuenta-Persistente.py').exists()
