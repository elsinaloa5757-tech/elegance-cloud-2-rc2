from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import socket
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from PIL import Image, ImageOps

from services.state_store import load_state, save_state

ROOT = Path(__file__).resolve().parents[1]
from services.runtime_config import data_dir
DATA = data_dir()
INBOX = DATA / "mobile_inbox"
MEDIA = DATA / "mobile_media"
DB = DATA / "elegance.sqlite3"
_LOCK = threading.RLock()
_WORKER_STARTED = False
_STOP = threading.Event()
_ANALYZER = None


def _connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS mobile_batches(
          id TEXT PRIMARY KEY,
          device_name TEXT NOT NULL,
          status TEXT NOT NULL,
          total INTEGER NOT NULL DEFAULT 0,
          received INTEGER NOT NULL DEFAULT 0,
          processed INTEGER NOT NULL DEFAULT 0,
          duplicates INTEGER NOT NULL DEFAULT 0,
          errors INTEGER NOT NULL DEFAULT 0,
          products INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS mobile_files(
          id TEXT PRIMARY KEY,
          batch_id TEXT NOT NULL,
          original_name TEXT NOT NULL,
          sha256 TEXT NOT NULL,
          source_path TEXT NOT NULL,
          thumb_path TEXT,
          status TEXT NOT NULL DEFAULT 'queued',
          error TEXT NOT NULL DEFAULT '',
          result_json TEXT NOT NULL DEFAULT '',
          cloud_object_id TEXT NOT NULL DEFAULT '',
          cloud_status TEXT NOT NULL DEFAULT 'pending',
          cloud_verified_at TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(sha256)
        );
        CREATE INDEX IF NOT EXISTS idx_mobile_files_batch ON mobile_files(batch_id);
        CREATE INDEX IF NOT EXISTS idx_mobile_files_status ON mobile_files(status);
        """
    )
    columns = {row["name"] for row in con.execute("PRAGMA table_info(mobile_files)")}
    for name, ddl in (
        ("cloud_object_id", "TEXT NOT NULL DEFAULT ''"),
        ("cloud_status", "TEXT NOT NULL DEFAULT 'pending'"),
        ("cloud_verified_at", "TEXT"),
    ):
        if name not in columns:
            con.execute(f"ALTER TABLE mobile_files ADD COLUMN {name} {ddl}")
    con.commit()
    return con


def local_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def mobile_url(port: int = 8000) -> str:
    return f"http://{local_ip()}:{port}/mobile"


def create_batch(device_name: str, total: int) -> dict[str, Any]:
    batch_id = uuid.uuid4().hex
    with _LOCK, _connect() as con:
        con.execute(
            "INSERT INTO mobile_batches(id,device_name,status,total) VALUES(?,?,?,?)",
            (batch_id, device_name.strip() or "S26 Ultra", "receiving", max(0, int(total))),
        )
        con.commit()
    return {"id": batch_id, "status": "receiving", "mobile_url": mobile_url()}


async def save_upload(batch_id: str, upload: UploadFile) -> dict[str, Any]:
    INBOX.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex
    suffix = Path(upload.filename or "image.jpg").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}:
        suffix = ".jpg"
    target = INBOX / f"{file_id}{suffix}"
    hasher = hashlib.sha256()
    size = 0
    with target.open("wb") as fh:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            hasher.update(chunk)
            size += len(chunk)
    digest = hasher.hexdigest()
    if size == 0:
        target.unlink(missing_ok=True)
        raise ValueError("Archivo vacío")

    with _LOCK, _connect() as con:
        exists = con.execute("SELECT id FROM mobile_files WHERE sha256=?", (digest,)).fetchone()
        if exists:
            target.unlink(missing_ok=True)
            con.execute(
                "UPDATE mobile_batches SET received=received+1,duplicates=duplicates+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (batch_id,),
            )
            con.commit()
            return {"status": "duplicate", "sha256": digest, "size": size}
        con.execute(
            "INSERT INTO mobile_files(id,batch_id,original_name,sha256,source_path,status) VALUES(?,?,?,?,?,'queued')",
            (file_id, batch_id, upload.filename or target.name, digest, str(target)),
        )
        con.execute(
            "UPDATE mobile_batches SET received=received+1,status='processing',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (batch_id,),
        )
        con.commit()

    # Vercel's filesystem is temporary. Persist and verify the original before
    # telling the phone that the upload can be removed from its gallery.
    cloud_status = "pending"
    safe_to_delete = False
    cloud_error = ""
    try:
        from services.storage_manager import prepare_source_original, upload_objects
        prepared = prepare_source_original(f"mobile-{file_id}", target)
        object_id = str(prepared["object"]["id"])
        uploaded = upload_objects([object_id])
        safe_to_delete = bool(uploaded.get("ok") and uploaded.get("verified"))
        cloud_status = "verified" if safe_to_delete else "retry"
        with _LOCK, _connect() as con:
            con.execute(
                """UPDATE mobile_files
                   SET cloud_object_id=?,cloud_status=?,cloud_verified_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                       updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (object_id, cloud_status, 1 if safe_to_delete else 0, file_id),
            )
            con.commit()
    except Exception as exc:  # local queue remains recoverable and retryable
        cloud_status = "retry"
        cloud_error = str(exc)
        with _LOCK, _connect() as con:
            con.execute(
                "UPDATE mobile_files SET cloud_status='retry',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (f"Copia remota pendiente: {cloud_error}"[:1000], file_id),
            )
            con.commit()

    # A Vercel function has no permanent background worker. Process the item
    # before this invocation finishes while the verified original is still
    # present on its temporary filesystem.
    if os.getenv("ELEGANCE_SERVERLESS", "").strip() == "1" and safe_to_delete:
        with _LOCK, _connect() as con:
            row = con.execute("SELECT * FROM mobile_files WHERE id=?", (file_id,)).fetchone()
            if row:
                con.execute(
                    "UPDATE mobile_files SET status='processing',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (file_id,),
                )
                con.commit()
        if row:
            _process_file(row)
            with _LOCK, _connect() as con:
                pending = con.execute(
                    "SELECT COUNT(*) FROM mobile_files WHERE batch_id=? AND status IN ('queued','processing')",
                    (batch_id,),
                ).fetchone()[0]
                batch = con.execute(
                    "SELECT total,received FROM mobile_batches WHERE id=?",
                    (batch_id,),
                ).fetchone()
                if pending == 0 and batch and int(batch["received"]) >= int(batch["total"]):
                    con.execute(
                        "UPDATE mobile_batches SET status='done',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (batch_id,),
                    )
                    con.commit()
    return {
        "status": "queued",
        "id": file_id,
        "sha256": digest,
        "size": size,
        "cloudStatus": cloud_status,
        "safeToDeleteFromPhone": safe_to_delete,
        "message": (
            "Original verificado en la nube. Ya puedes borrarlo del teléfono."
            if safe_to_delete
            else "No lo borres todavía: la copia remota sigue pendiente."
        ),
    }


def batch_status(batch_id: str) -> dict[str, Any]:
    with _LOCK, _connect() as con:
        row = con.execute("SELECT * FROM mobile_batches WHERE id=?", (batch_id,)).fetchone()
        if not row:
            raise KeyError(batch_id)
        data = dict(row)
        latest = con.execute(
            """SELECT original_name,status,error,result_json,cloud_status,cloud_verified_at
               FROM mobile_files WHERE batch_id=? ORDER BY created_at DESC LIMIT 12""",
            (batch_id,),
        ).fetchall()
        cloud = con.execute(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN cloud_status='verified' THEN 1 ELSE 0 END) verified,
                      SUM(CASE WHEN cloud_status!='verified' THEN 1 ELSE 0 END) pending
               FROM mobile_files WHERE batch_id=?""",
            (batch_id,),
        ).fetchone()
    data["latest"] = [dict(x) | {"result": json.loads(x["result_json"]) if x["result_json"] else None} for x in latest]
    data["cloudVerified"] = int(cloud["verified"] or 0)
    data["cloudPending"] = int(cloud["pending"] or 0)
    data["safeToDeleteFromPhone"] = bool(
        int(data["received"]) >= int(data["total"])
        and int(data["total"]) > 0
        and data["cloudPending"] == 0
    )
    return data


def recent_batches(limit: int = 20) -> list[dict[str, Any]]:
    with _LOCK, _connect() as con:
        rows = con.execute("SELECT * FROM mobile_batches ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def _make_thumb(source: Path, file_id: str) -> tuple[Path, str]:
    MEDIA.mkdir(parents=True, exist_ok=True)
    out = MEDIA / f"{file_id}.webp"
    with Image.open(source) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((640, 640), Image.Resampling.LANCZOS)
        im.save(out, "WEBP", quality=76, method=4)
    encoded = base64.b64encode(out.read_bytes()).decode("ascii")
    return out, encoded


def _append_product(result: dict[str, Any], thumb_b64: str, file_id: str) -> None:
    state = load_state()
    products = list(state.get("products") or [])
    title = str(result.get("title") or "Calzado modelo pendiente").strip()
    brand = str(result.get("brand") or "Sin identificar").strip()
    model = str(result.get("model") or "").strip()
    sku = str(result.get("sku") or "").strip() or f"MOV-{file_id[:10].upper()}"
    product = {
        "id": f"mobile-{file_id}",
        "sku": sku,
        "title": title,
        "brand": brand,
        "model": model,
        "color": str(result.get("color") or ""),
        "price": 0,
        "stock": 0,
        "sizes": "",
        "notes": "Importado desde el teléfono. Modelo pendiente cuando no existe evidencia suficiente.",
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "imageBase64": thumb_b64,
        "galleryBase64": [thumb_b64],
        "scenarioApplied": False,
        "identificationConfidence": max(float(result.get("brand_confidence") or 0), float(result.get("model_confidence") or 0)),
    }
    if not any(p.get("id") == product["id"] for p in products):
        products.append(product)
    state["products"] = products
    state["processedImages"] = int(state.get("processedImages") or 0) + 1
    activities = list(state.get("activities") or [])
    activities.insert(0, {
        "text": f"Móvil publicó: {title}",
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "iconCode": 0xe1c8,
    })
    state["activities"] = activities[:80]
    save_state(state)


def _process_file(row: sqlite3.Row) -> None:
    global _ANALYZER
    source = Path(row["source_path"])
    batch_id = row["batch_id"]
    file_id = row["id"]
    try:
        out, thumb_b64 = _make_thumb(source, file_id)
        if _ANALYZER is None:
            from services.analyzer import AnalyzerService
            _ANALYZER = AnalyzerService()
        from starlette.datastructures import UploadFile as StarletteUploadFile
        data = source.read_bytes()
        upload = StarletteUploadFile(filename=row["original_name"], file=io.BytesIO(data))
        import asyncio
        analyzed = asyncio.run(_ANALYZER.analyze([upload], eps=0.075, min_samples=1))
        if analyzed.groups:
            group = analyzed.groups[0]
            result = {
                "brand": group.brand,
                "model": group.model_family,
                "title": group.suggested_title,
                "sku": group.sku,
                "color": group.dominant_color,
                "brand_confidence": group.brand_confidence,
                "model_confidence": group.model_confidence,
                "needs_review": group.needs_manual_review,
            }
        else:
            result = {"brand": "Sin identificar", "model": "", "title": "Calzado modelo pendiente", "needs_review": True}
        _append_product(result, thumb_b64, file_id)
        with _LOCK, _connect() as con:
            con.execute(
                "UPDATE mobile_files SET status='done',thumb_path=?,result_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (str(out), json.dumps(result, ensure_ascii=False), file_id),
            )
            con.execute(
                "UPDATE mobile_batches SET processed=processed+1,products=products+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (batch_id,),
            )
            con.commit()
    except Exception as exc:  # noqa: BLE001 - queue must survive individual failures
        with _LOCK, _connect() as con:
            con.execute(
                "UPDATE mobile_files SET status='error',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (str(exc)[:500], file_id),
            )
            con.execute(
                "UPDATE mobile_batches SET processed=processed+1,errors=errors+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (batch_id,),
            )
            con.commit()


def _worker_loop() -> None:
    while not _STOP.is_set():
        row = None
        with _LOCK, _connect() as con:
            row = con.execute("SELECT * FROM mobile_files WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row:
                con.execute("UPDATE mobile_files SET status='processing',updated_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
                con.commit()
        if row:
            _process_file(row)
            with _LOCK, _connect() as con:
                pending = con.execute("SELECT COUNT(*) FROM mobile_files WHERE batch_id=? AND status IN ('queued','processing')", (row["batch_id"],)).fetchone()[0]
                batch = con.execute("SELECT total,received FROM mobile_batches WHERE id=?", (row["batch_id"],)).fetchone()
                if pending == 0 and batch and int(batch["received"]) >= int(batch["total"]):
                    con.execute("UPDATE mobile_batches SET status='done',updated_at=CURRENT_TIMESTAMP WHERE id=?", (row["batch_id"],))
                    con.commit()
        else:
            _STOP.wait(0.7)


def start_worker() -> None:
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    _connect().close()
    thread = threading.Thread(target=_worker_loop, name="elegance-mobile-worker", daemon=True)
    thread.start()
    _WORKER_STARTED = True


def stop_worker() -> None:
    _STOP.set()
