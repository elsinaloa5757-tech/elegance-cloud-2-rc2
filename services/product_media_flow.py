from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from services.cloud_storage import store_bytes
from services.runtime_config import database_file
from services.state_store import load_state, save_state

DB = database_file()
FORMATS = {
    "original": None,
    "catalog": (1600, 1600),
    "thumbnail": (480, 480),
    "whatsapp": (1080, 1080),
}
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def migrate_product_media() -> dict[str, Any]:
    with _db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS product_media_assets(
              id TEXT PRIMARY KEY,
              product_id TEXT NOT NULL,
              source_name TEXT NOT NULL,
              content_type TEXT NOT NULL,
              sha256 TEXT NOT NULL,
              byte_size INTEGER NOT NULL,
              status TEXT NOT NULL,
              is_cover INTEGER NOT NULL DEFAULT 0,
              variant_id TEXT NOT NULL DEFAULT '',
              error TEXT NOT NULL DEFAULT '',
              attempts INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(product_id, sha256)
            );
            CREATE TABLE IF NOT EXISTS product_media_outputs(
              id TEXT PRIMARY KEY,
              asset_id TEXT NOT NULL,
              format TEXT NOT NULL,
              backend TEXT NOT NULL,
              object_path TEXT NOT NULL,
              public_url TEXT NOT NULL,
              sha256 TEXT NOT NULL,
              byte_size INTEGER NOT NULL,
              width INTEGER NOT NULL DEFAULT 0,
              height INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              UNIQUE(asset_id, format, backend),
              FOREIGN KEY(asset_id) REFERENCES product_media_assets(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_product_media_product ON product_media_assets(product_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_product_media_sha ON product_media_assets(sha256);
            """
        )
    return {"status": "ok", "version": "6.0-rc2"}


def _encode_variant(data: bytes, size: tuple[int, int] | None) -> tuple[bytes, int, int, str]:
    image = Image.open(io.BytesIO(data))
    image.load()
    image = ImageOps.exif_transpose(image).convert("RGB")
    if size:
        image.thumbnail(size, Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="WEBP", quality=88, method=6)
    return output.getvalue(), image.width, image.height, "image/webp"


def _record_output(connection: sqlite3.Connection, asset_id: str, fmt: str, result: dict, width: int, height: int) -> None:
    for copy in result.get("copies", []):
        connection.execute(
            """INSERT INTO product_media_outputs
            (id,asset_id,format,backend,object_path,public_url,sha256,byte_size,width,height,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(asset_id,format,backend) DO UPDATE SET
              object_path=excluded.object_path, public_url=excluded.public_url,
              sha256=excluded.sha256, byte_size=excluded.byte_size,
              width=excluded.width, height=excluded.height, created_at=excluded.created_at""",
            (
                "out_" + uuid.uuid4().hex[:18], asset_id, fmt, copy["backend"], copy["path"],
                copy["publicUrl"], copy["sha256"], int(copy["size"]), width, height, now(),
            ),
        )


def _process_asset(asset_id: str, data: bytes) -> dict[str, Any]:
    with _db() as connection:
        asset = connection.execute("SELECT * FROM product_media_assets WHERE id=?", (asset_id,)).fetchone()
        if not asset:
            raise ValueError("Imagen no encontrada.")
        connection.execute(
            "UPDATE product_media_assets SET status='processing', attempts=attempts+1, error='', updated_at=? WHERE id=?",
            (now(), asset_id),
        )
        product_id = asset["product_id"]
        source_name = Path(asset["source_name"]).stem or "image"
        try:
            for fmt, dimensions in FORMATS.items():
                if fmt == "original":
                    payload = data
                    width = height = 0
                    content_type = asset["content_type"] or "application/octet-stream"
                    extension = Path(asset["source_name"]).suffix.lower() or ".bin"
                else:
                    payload, width, height, content_type = _encode_variant(data, dimensions)
                    extension = ".webp"
                object_path = f"products/{product_id}/{asset_id}/{fmt}/{source_name}{extension}"
                result = store_bytes(object_path, payload, content_type)
                _record_output(connection, asset_id, fmt, result, width, height)
            connection.execute(
                "UPDATE product_media_assets SET status='ready', updated_at=? WHERE id=?", (now(), asset_id)
            )
            connection.commit()
        except Exception as exc:
            connection.execute(
                "UPDATE product_media_assets SET status='failed', error=?, updated_at=? WHERE id=?",
                (f"{type(exc).__name__}: {exc}"[:1000], now(), asset_id),
            )
            connection.commit()
            raise
    return get_asset(asset_id)


def upload_batch(product_id: str, files: list[tuple[str, bytes, str]], variant_id: str = "") -> dict[str, Any]:
    migrate_product_media()
    product_id = str(product_id or "").strip()
    if not product_id:
        raise ValueError("Se requiere productId para asociar las imágenes.")
    if not files:
        raise ValueError("Selecciona al menos una imagen.")
    accepted: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for filename, data, content_type in files:
        if not data:
            failed.append({"filename": filename, "error": "Archivo vacío."})
            continue
        content_type = (content_type or "").lower()
        if content_type and content_type not in ALLOWED_CONTENT_TYPES:
            failed.append({"filename": filename, "error": "Formato de imagen no admitido."})
            continue
        digest = hashlib.sha256(data).hexdigest()
        with _db() as connection:
            existing = connection.execute(
                "SELECT * FROM product_media_assets WHERE product_id=? AND sha256=?", (product_id, digest)
            ).fetchone()
            if existing:
                duplicates.append({"filename": filename, "assetId": existing["id"], "sha256": digest})
                continue
            asset_id = "img_" + uuid.uuid4().hex[:20]
            created = now()
            connection.execute(
                """INSERT INTO product_media_assets
                (id,product_id,source_name,content_type,sha256,byte_size,status,is_cover,variant_id,error,attempts,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (asset_id, product_id, filename or "image", content_type or "application/octet-stream", digest,
                 len(data), "queued", 0, variant_id, "", 0, created, created),
            )
        try:
            accepted.append(_process_asset(asset_id, data))
        except Exception as exc:
            failed.append({"filename": filename, "assetId": asset_id, "error": str(exc)})
    if accepted and not any(a.get("isCover") for a in list_assets(product_id)["items"]):
        set_cover(product_id, accepted[0]["id"])
    return {
        "status": "ok" if not failed else "partial",
        "productId": product_id,
        "accepted": accepted,
        "duplicates": duplicates,
        "failed": failed,
        "summary": {"accepted": len(accepted), "duplicates": len(duplicates), "failed": len(failed)},
    }


def _asset_dict(row: sqlite3.Row, outputs: list[dict[str, Any]]) -> dict[str, Any]:
    by_format: dict[str, list[dict[str, Any]]] = {}
    for output in outputs:
        by_format.setdefault(output["format"], []).append(output)
    preferred: dict[str, dict[str, Any]] = {}
    for fmt, items in by_format.items():
        preferred[fmt] = next((x for x in items if x["backend"] == "supabase"), items[0])
    return {
        "id": row["id"], "productId": row["product_id"], "sourceName": row["source_name"],
        "contentType": row["content_type"], "sha256": row["sha256"], "byteSize": row["byte_size"],
        "status": row["status"], "isCover": bool(row["is_cover"]), "variantId": row["variant_id"],
        "error": row["error"], "attempts": row["attempts"], "createdAt": row["created_at"],
        "updatedAt": row["updated_at"], "outputs": by_format, "preferred": preferred,
    }


def get_asset(asset_id: str) -> dict[str, Any]:
    migrate_product_media()
    with _db() as connection:
        row = connection.execute("SELECT * FROM product_media_assets WHERE id=?", (asset_id,)).fetchone()
        if not row:
            raise ValueError("Imagen no encontrada.")
        outputs = [dict(x) for x in connection.execute(
            "SELECT * FROM product_media_outputs WHERE asset_id=? ORDER BY format,backend", (asset_id,)
        ).fetchall()]
    return _asset_dict(row, outputs)


def list_assets(product_id: str) -> dict[str, Any]:
    migrate_product_media()
    with _db() as connection:
        rows = connection.execute(
            "SELECT * FROM product_media_assets WHERE product_id=? ORDER BY is_cover DESC, created_at", (product_id,)
        ).fetchall()
        items = []
        for row in rows:
            outputs = [dict(x) for x in connection.execute(
                "SELECT * FROM product_media_outputs WHERE asset_id=? ORDER BY format,backend", (row["id"],)
            ).fetchall()]
            items.append(_asset_dict(row, outputs))
    return {"status": "ok", "productId": product_id, "count": len(items), "items": items}


def set_cover(product_id: str, asset_id: str) -> dict[str, Any]:
    migrate_product_media()
    with _db() as connection:
        row = connection.execute(
            "SELECT id FROM product_media_assets WHERE id=? AND product_id=? AND status='ready'", (asset_id, product_id)
        ).fetchone()
        if not row:
            raise ValueError("La imagen de portada debe existir, pertenecer al producto y estar lista.")
        connection.execute("UPDATE product_media_assets SET is_cover=0, updated_at=? WHERE product_id=?", (now(), product_id))
        connection.execute("UPDATE product_media_assets SET is_cover=1, updated_at=? WHERE id=?", (now(), asset_id))
    asset = get_asset(asset_id)
    cover_url = (asset.get("preferred", {}).get("catalog") or asset.get("preferred", {}).get("original") or {}).get("public_url", "")
    state = load_state()
    products = state.get("products") if isinstance(state.get("products"), list) else []
    product = next((p for p in products if str(p.get("id")) == product_id), None)
    if product is not None:
        product["image"] = cover_url
        product["approvedStudioImage"] = cover_url
        product["coverAssetId"] = asset_id
        product["updatedAt"] = now()
        save_state(state)
    return {"status": "ok", "productId": product_id, "coverAssetId": asset_id, "coverUrl": cover_url}


def assign_variant(product_id: str, asset_id: str, variant_id: str) -> dict[str, Any]:
    with _db() as connection:
        changed = connection.execute(
            "UPDATE product_media_assets SET variant_id=?, updated_at=? WHERE id=? AND product_id=?",
            (variant_id.strip(), now(), asset_id, product_id),
        ).rowcount
    if not changed:
        raise ValueError("Imagen no encontrada para ese producto.")
    return get_asset(asset_id)


def retry_asset(asset_id: str) -> dict[str, Any]:
    asset = get_asset(asset_id)
    original = next((item for item in asset.get("outputs", {}).get("original", []) if item.get("backend") == "local"), None)
    if not original:
        raise ValueError("El reintento automático requiere conservar una copia original local.")
    from services.runtime_config import data_dir
    path = data_dir() / original["object_path"]
    if not path.exists():
        raise ValueError("No se encontró la copia original local.")
    return _process_asset(asset_id, path.read_bytes())


def delete_asset(product_id: str, asset_id: str, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        raise ValueError("La eliminación requiere confirmación explícita.")
    with _db() as connection:
        row = connection.execute(
            "SELECT is_cover FROM product_media_assets WHERE id=? AND product_id=?", (asset_id, product_id)
        ).fetchone()
        if not row:
            raise ValueError("Imagen no encontrada.")
        connection.execute("DELETE FROM product_media_assets WHERE id=?", (asset_id,))
    if bool(row["is_cover"]):
        remaining = list_assets(product_id)["items"]
        ready = next((x for x in remaining if x["status"] == "ready"), None)
        if ready:
            set_cover(product_id, ready["id"])
    return {"status": "ok", "deleted": True, "assetId": asset_id}
