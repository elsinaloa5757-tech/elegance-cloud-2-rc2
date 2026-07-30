from __future__ import annotations

import base64
import sqlite3

from services import catalog_crud


class _MissingMediaDatabase:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args):
        raise sqlite3.OperationalError("product media has not been migrated")


def test_mobile_product_exposes_embedded_thumbnail(monkeypatch):
    encoded = base64.b64encode(b"small-webp").decode("ascii")
    monkeypatch.setattr(
        catalog_crud,
        "list_inventory",
        lambda: [
            {
                "id": "mobile-image",
                "title": "Nike 720",
                "brand": "Nike",
                "imageBase64": encoded,
                "updatedAt": "2026-07-30T12:00:00",
            }
        ],
    )
    monkeypatch.setattr(catalog_crud, "_db", lambda: _MissingMediaDatabase())

    result = catalog_crud.list_products()

    assert result["count"] == 1
    assert result["products"][0]["thumbnailUrl"] == f"data:image/webp;base64,{encoded}"


def test_durable_cloud_thumbnail_is_preferred(monkeypatch):
    monkeypatch.setattr(
        catalog_crud,
        "list_inventory",
        lambda: [{"id": "cloud-image", "title": "Bolso", "imageBase64": "fallback"}],
    )

    class _Rows(_MissingMediaDatabase):
        def execute(self, *_args):
            return [
                {
                    "product_id": "cloud-image",
                    "is_cover": 1,
                    "backend": "supabase",
                    "public_url": "https://example.supabase.co/storage/thumb.webp",
                }
            ]

    monkeypatch.setattr(catalog_crud, "_db", lambda: _Rows())

    result = catalog_crud.list_products()

    assert result["products"][0]["thumbnailUrl"].startswith("https://example.supabase.co/")
