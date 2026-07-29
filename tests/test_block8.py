from __future__ import annotations

import importlib
from pathlib import Path


def test_block8_files_exist():
    root = Path(__file__).resolve().parents[1]
    win = root / "server_windows"
    for name in [
        "Diagnosticar-Bloque8.ps1",
        "Configurar-PostgreSQL-Bloque8.ps1",
        "Instalar-Tunel-Cloudflare-Bloque8.ps1",
        "Prueba-Final-Bloque8.ps1",
    ]:
        assert (win / name).exists(), name


def test_installation_report_detects_missing_real_infrastructure(monkeypatch, tmp_path):
    data = tmp_path / "data"
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(data))
    monkeypatch.setenv("ELEGANCE_SQLITE_PATH", str(data / "elegance.sqlite3"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ELEGANCE_PUBLIC_URL", raising=False)
    monkeypatch.delenv("ELEGANCE_EXTERNAL_BACKUP_DIR", raising=False)
    import services.runtime_config as runtime_config
    import services.home_server as home_server
    import services.server_installation as server_installation
    importlib.reload(runtime_config)
    importlib.reload(home_server)
    importlib.reload(server_installation)
    report = server_installation.installation_report(check_database=False)
    assert report["status"] == "attention"
    assert "databaseConfigured" in report["blockers"]
    assert "publicUrlConfigured" in report["warnings"]
    assert (data / "block8_installation_report.json").exists()


def test_block8_route_is_present():
    root = Path(__file__).resolve().parents[1]
    routes = (root / "api" / "routes.py").read_text(encoding="utf-8")
    assert "/api/admin/server-installation" in routes
