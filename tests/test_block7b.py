from __future__ import annotations
import importlib
import json
import zipfile
from pathlib import Path


def _reload(monkeypatch, tmp_path):
    data = tmp_path / "data"
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(data))
    monkeypatch.setenv("ELEGANCE_SQLITE_PATH", str(data / "elegance.sqlite3"))
    import services.runtime_config as runtime_config
    import services.state_store as state_store
    import services.mobile_command_center as mobile
    importlib.reload(runtime_config); importlib.reload(state_store); importlib.reload(mobile)
    return state_store, mobile


def test_device_registration_and_heartbeat(monkeypatch, tmp_path):
    _, mobile = _reload(monkeypatch, tmp_path)
    created = mobile.register_device("S26 Ultra")
    assert created["device"]["platform"] == "android"
    beat = mobile.heartbeat(created["device"]["id"])
    assert beat["status"] == "ok"
    assert mobile.mobile_status()["deviceCount"] == 1


def test_emergency_snapshot_is_valid(monkeypatch, tmp_path):
    state_store, mobile = _reload(monkeypatch, tmp_path)
    state_store.save_state({"products": [{"id": "p1", "name": "Tenis"}], "inventory": {"p1": 1}, "settings": {}})
    result = mobile.create_emergency_snapshot(include_database=True)
    path = Path(result["path"])
    assert path.exists() and result["sha256"]
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read("manifest.json"))
        state = json.loads(archive.read("emergency/state.json"))
    assert manifest["purpose"] == "mobile-emergency-readonly"
    assert state["products"][0]["id"] == "p1"
    assert mobile.list_emergency_snapshots()[0]["valid"] is True


def test_mobile_center_files_and_routes_exist():
    root = Path(__file__).resolve().parents[1]
    assert (root / "web" / "mobile-center.html").exists()
    routes = (root / "api" / "routes.py").read_text(encoding="utf-8")
    assert "/mobile-center" in routes
    assert "/api/admin/mobile-command-center/snapshots" in routes
