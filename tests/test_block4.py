from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from services.cloud_storage import store_bytes, storage_status


def test_local_storage_round_trip(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ELEGANCE_STORAGE_MODE", "local")
    result = store_bytes("products/test/sample.txt", b"elegance", "text/plain")
    assert result["status"] == "stored"
    assert result["primary"]["backend"] == "local"
    assert (tmp_path / result["primary"]["path"]).read_bytes() == b"elegance"


def test_public_runtime_config(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ELEGANCE_STORAGE_MODE", "local")
    with TestClient(create_app()) as client:
        response = client.get("/api/public/config")
        assert response.status_code == 200
        payload = response.json()
        assert payload["features"]["publicCatalog"] is True
        assert payload["limits"]["maxUploadMb"] >= 1


def test_storage_status_does_not_expose_secret(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "super-secret")
    payload = storage_status(check_remote=False)
    assert "super-secret" not in str(payload)
