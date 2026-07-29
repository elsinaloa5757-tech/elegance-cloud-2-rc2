from __future__ import annotations

import importlib
from pathlib import Path


def test_home_production_allows_local_database(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEGANCE_ENV", "production")
    monkeypatch.setenv("ELEGANCE_SERVER_MODE", "home")
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ELEGANCE_ALLOWED_ORIGINS", "http://127.0.0.1:8000")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from services.runtime_config import require_production_configuration
    require_production_configuration()


def test_cloud_production_still_requires_database(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEGANCE_ENV", "production")
    monkeypatch.setenv("ELEGANCE_SERVER_MODE", "cloud")
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ELEGANCE_ALLOWED_ORIGINS", "https://example.com")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from services.runtime_config import require_production_configuration
    try:
        require_production_configuration()
    except RuntimeError as exc:
        assert "DATABASE_URL" in str(exc)
    else:
        raise AssertionError("Cloud production must require DATABASE_URL")


def test_home_server_status_and_external_backup(monkeypatch, tmp_path):
    data = tmp_path / "data"
    external = tmp_path / "external"
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(data))
    monkeypatch.setenv("ELEGANCE_SQLITE_PATH", str(data / "elegance.sqlite3"))
    monkeypatch.setenv("ELEGANCE_EXTERNAL_BACKUP_DIR", str(external))
    monkeypatch.setenv("ELEGANCE_ENABLE_BACKUP_SCHEDULER", "0")

    import services.runtime_config as runtime_config
    import services.full_backup as full_backup
    import services.home_server as home_server
    import services.state_store as state_store
    importlib.reload(runtime_config)
    importlib.reload(state_store)
    importlib.reload(full_backup)
    importlib.reload(home_server)

    state_store.save_state({"products": [], "settings": {}})
    result = home_server.run_scheduled_backup("daily")
    assert result["status"] == "ok"
    assert result["externalCopy"]["status"] == "ok"
    assert Path(result["externalCopy"]["path"]).exists()
    status = home_server.server_status()
    assert status["backup"]["count"] >= 1
    assert status["storage"]["free"] > 0
    assert status["publicAccess"]["directRouterPortsRequired"] is False


def test_windows_server_files_exist():
    root = Path(__file__).resolve().parents[1] / "server_windows"
    required = {
        "Instalar-Servidor-Elegance.ps1",
        "Instalar-Tunel-Cloudflare.ps1",
        "Crear-Respaldo-Ahora.ps1",
        "LEEME_SERVIDOR_WINDOWS.txt",
    }
    assert required.issubset({p.name for p in root.iterdir()})
