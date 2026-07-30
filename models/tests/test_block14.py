from __future__ import annotations

import asyncio
import importlib
import io
from pathlib import Path

from starlette.datastructures import UploadFile


def _reload_storage(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(tmp_path))
    import services.runtime_config as runtime_config
    import services.state_store as state_store
    import services.storage_manager as storage_manager

    importlib.reload(runtime_config)
    importlib.reload(state_store)
    return importlib.reload(storage_manager)


def test_original_is_hash_verified_before_safe_delete(monkeypatch, tmp_path: Path):
    storage = _reload_storage(monkeypatch, tmp_path)
    source = tmp_path / "phone.jpg"
    source.write_bytes(b"original-phone-photo")
    monkeypatch.setattr(storage, "create_backup", lambda reason: {"ok": True})

    def fake_edge(action, payload, timeout=None):
        assert action == "storage_upload"
        item = payload["object"]
        return {"ok": True, "object": {"sha256": item["sha256"], "url": None}}

    monkeypatch.setattr(storage, "_edge", fake_edge)
    prepared = storage.prepare_source_original("mobile-1", source)
    uploaded = storage.upload_objects([prepared["object"]["id"]])

    assert uploaded["ok"] is True
    assert uploaded["verified"] == 1
    assert storage.safe_to_delete(product_id="mobile-1")["safe"] is True


def test_serverless_storage_upload_skips_nested_sqlite_backup(monkeypatch, tmp_path: Path):
    storage = _reload_storage(monkeypatch, tmp_path)
    monkeypatch.setenv("ELEGANCE_SERVERLESS", "1")
    source = tmp_path / "phone.jpg"
    source.write_bytes(b"serverless-original")
    monkeypatch.setattr(
        storage,
        "create_backup",
        lambda reason: (_ for _ in ()).throw(AssertionError(reason)),
    )
    monkeypatch.setattr(
        storage,
        "_edge",
        lambda action, payload, timeout=None: {
            "ok": True,
            "object": {"sha256": payload["object"]["sha256"], "url": None},
        },
    )

    prepared = storage.prepare_source_original("mobile-serverless", source)
    uploaded = storage.upload_objects([prepared["object"]["id"]])

    assert uploaded["ok"] is True
    assert uploaded["verified"] == 1


def test_mobile_upload_only_allows_phone_delete_after_cloud_verification(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(tmp_path))
    import services.runtime_config as runtime_config
    import services.state_store as state_store
    import services.storage_manager as storage_manager
    import services.mobile_inbox as mobile_inbox

    importlib.reload(runtime_config)
    importlib.reload(state_store)
    importlib.reload(storage_manager)
    mobile = importlib.reload(mobile_inbox)
    batch = mobile.create_batch("S26 Ultra", 1)
    monkeypatch.setattr(
        storage_manager,
        "prepare_source_original",
        lambda product_id, source: {"object": {"id": "cloud-object-1"}},
    )
    monkeypatch.setattr(
        storage_manager,
        "upload_objects",
        lambda ids: {"ok": True, "verified": 1, "failed": 0},
    )
    upload = UploadFile(filename="whatsapp.jpg", file=io.BytesIO(b"photo-content"))
    result = asyncio.run(mobile.save_upload(batch["id"], upload))

    assert result["cloudStatus"] == "verified"
    assert result["safeToDeleteFromPhone"] is True
    with mobile._connect() as connection:
        row = connection.execute(
            "SELECT cloud_object_id,cloud_status,cloud_verified_at FROM mobile_files WHERE id=?",
            (result["id"],),
        ).fetchone()
    assert row["cloud_object_id"] == "cloud-object-1"
    assert row["cloud_status"] == "verified"
    assert row["cloud_verified_at"]


def test_mobile_upload_keeps_delete_warning_when_cloud_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(tmp_path))
    import services.runtime_config as runtime_config
    import services.state_store as state_store
    import services.storage_manager as storage_manager
    import services.mobile_inbox as mobile_inbox

    importlib.reload(runtime_config)
    importlib.reload(state_store)
    importlib.reload(storage_manager)
    mobile = importlib.reload(mobile_inbox)
    batch = mobile.create_batch("S26 Ultra", 1)
    monkeypatch.setattr(
        storage_manager,
        "prepare_source_original",
        lambda product_id, source: (_ for _ in ()).throw(RuntimeError("sin conexión")),
    )
    upload = UploadFile(filename="whatsapp.jpg", file=io.BytesIO(b"photo-content"))
    result = asyncio.run(mobile.save_upload(batch["id"], upload))

    assert result["cloudStatus"] == "retry"
    assert result["safeToDeleteFromPhone"] is False
    assert "No lo borres" in result["message"]
