from __future__ import annotations

import importlib
import io

from PIL import Image


def _image_bytes(size=(900, 700), value=(30, 40, 50)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, value).save(out, format="JPEG", quality=90)
    return out.getvalue()


def _reload(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ELEGANCE_SQLITE_PATH", str(tmp_path / "elegance.sqlite3"))
    monkeypatch.setenv("ELEGANCE_STORAGE_MODE", "local")
    import services.runtime_config as runtime_config
    import services.state_store as state_store
    import services.cloud_storage as cloud_storage
    import services.product_media_flow as media
    importlib.reload(runtime_config)
    importlib.reload(state_store)
    importlib.reload(cloud_storage)
    return importlib.reload(media)


def test_batch_variants_cover_and_dedup(monkeypatch, tmp_path):
    media = _reload(monkeypatch, tmp_path)
    first = _image_bytes()
    second = _image_bytes(value=(80, 90, 100))
    result = media.upload_batch("prd_demo", [("front.jpg", first, "image/jpeg"), ("side.jpg", second, "image/jpeg")])
    assert result["summary"] == {"accepted": 2, "duplicates": 0, "failed": 0}
    items = media.list_assets("prd_demo")["items"]
    assert len(items) == 2
    assert sum(1 for item in items if item["isCover"]) == 1
    for item in items:
        assert item["status"] == "ready"
        assert set(item["preferred"]) == {"original", "catalog", "thumbnail", "whatsapp"}
    duplicate = media.upload_batch("prd_demo", [("copy.jpg", first, "image/jpeg")])
    assert duplicate["summary"]["duplicates"] == 1
    assert duplicate["summary"]["accepted"] == 0


def test_cover_variant_and_delete(monkeypatch, tmp_path):
    media = _reload(monkeypatch, tmp_path)
    result = media.upload_batch("prd_demo", [
        ("a.jpg", _image_bytes(value=(10, 20, 30)), "image/jpeg"),
        ("b.jpg", _image_bytes(value=(120, 130, 140)), "image/jpeg"),
    ])
    a, b = result["accepted"]
    cover = media.set_cover("prd_demo", b["id"])
    assert cover["coverAssetId"] == b["id"]
    assigned = media.assign_variant("prd_demo", b["id"], "var_black_26")
    assert assigned["variantId"] == "var_black_26"
    try:
        media.delete_asset("prd_demo", b["id"], False)
        assert False
    except ValueError:
        pass
    deleted = media.delete_asset("prd_demo", b["id"], True)
    assert deleted["deleted"] is True
    remaining = media.list_assets("prd_demo")["items"]
    assert len(remaining) == 1 and remaining[0]["isCover"] is True
