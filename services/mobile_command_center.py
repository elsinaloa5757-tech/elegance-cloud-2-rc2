from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.runtime_config import data_dir, database_file
from services.state_store import load_state

MOBILE_DIR_NAME = "mobile_command_center"
DEVICES_FILE = "devices.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    root = data_dir() / MOBILE_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _devices_path() -> Path:
    return _root() / DEVICES_FILE


def _read_devices() -> dict[str, Any]:
    path = _devices_path()
    if not path.exists():
        return {"devices": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"devices": []}
    except Exception:
        return {"devices": []}


def _write_devices(payload: dict[str, Any]) -> None:
    path = _devices_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def register_device(name: str, platform: str = "android") -> dict[str, Any]:
    clean_name = (name or "S26 Ultra").strip()[:80]
    clean_platform = (platform or "android").strip().lower()[:30]
    payload = _read_devices()
    devices = payload.setdefault("devices", [])
    existing = next((d for d in devices if d.get("name", "").lower() == clean_name.lower()), None)
    if existing:
        existing.update({"platform": clean_platform, "lastSeenAt": _now(), "enabled": True})
        device = existing
    else:
        device = {
            "id": secrets.token_urlsafe(12),
            "name": clean_name,
            "platform": clean_platform,
            "createdAt": _now(),
            "lastSeenAt": _now(),
            "enabled": True,
        }
        devices.append(device)
    _write_devices(payload)
    return {"status": "ok", "device": device}


def heartbeat(device_id: str) -> dict[str, Any]:
    payload = _read_devices()
    device = next((d for d in payload.get("devices", []) if d.get("id") == device_id and d.get("enabled", True)), None)
    if not device:
        raise ValueError("Dispositivo no registrado o deshabilitado")
    device["lastSeenAt"] = _now()
    _write_devices(payload)
    return {"status": "ok", "device": device}


def list_devices() -> list[dict[str, Any]]:
    return list(_read_devices().get("devices", []))


def disable_device(device_id: str) -> dict[str, Any]:
    payload = _read_devices()
    device = next((d for d in payload.get("devices", []) if d.get("id") == device_id), None)
    if not device:
        raise ValueError("Dispositivo no encontrado")
    device["enabled"] = False
    device["disabledAt"] = _now()
    _write_devices(payload)
    return {"status": "ok", "device": device}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_state_summary(state: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "products", "inventory", "customers", "clients", "orders", "sales",
        "layaways", "payments", "shipments", "settings", "categories",
    )
    return {key: state.get(key) for key in keys if key in state}


def create_emergency_snapshot(include_database: bool = True) -> dict[str, Any]:
    target_dir = _root() / "emergency_snapshots"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = target_dir / f"elegance_mobile_emergency_{stamp}.zip"
    state = load_state()
    summary = _safe_state_summary(state if isinstance(state, dict) else {})
    manifest: dict[str, Any] = {
        "format": 1,
        "createdAt": _now(),
        "purpose": "mobile-emergency-readonly",
        "serverMode": os.getenv("ELEGANCE_SERVER_MODE", "home"),
        "containsDatabase": False,
        "files": [],
        "instructions": "Este paquete es una copia de emergencia de solo lectura. No sustituye el respaldo completo del servidor.",
    }
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        state_bytes = json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8")
        archive.writestr("emergency/state.json", state_bytes)
        manifest["files"].append({"path": "emergency/state.json", "size": len(state_bytes), "sha256": hashlib.sha256(state_bytes).hexdigest()})
        db = database_file()
        if include_database and db.exists() and not os.getenv("DATABASE_URL", "").strip():
            try:
                with sqlite3.connect(db) as connection:
                    connection.execute("PRAGMA wal_checkpoint(FULL)")
            except Exception:
                pass
            archive.write(db, "emergency/elegance.sqlite3")
            manifest["containsDatabase"] = True
            manifest["files"].append({"path": "emergency/elegance.sqlite3", "size": db.stat().st_size, "sha256": _sha256(db)})
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return {
        "status": "ok",
        "name": target.name,
        "path": str(target),
        "size": target.stat().st_size,
        "sha256": _sha256(target),
        "createdAt": manifest["createdAt"],
        "containsDatabase": manifest["containsDatabase"],
    }


def snapshot_path(name: str) -> Path:
    safe = Path(name).name
    path = _root() / "emergency_snapshots" / safe
    if path.suffix.lower() != ".zip" or not path.exists():
        raise FileNotFoundError(safe)
    return path


def list_emergency_snapshots() -> list[dict[str, Any]]:
    folder = _root() / "emergency_snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    output = []
    for path in sorted(folder.glob("elegance_mobile_emergency_*.zip"), reverse=True):
        valid = True
        try:
            with zipfile.ZipFile(path) as archive:
                valid = archive.testzip() is None and "manifest.json" in archive.namelist()
        except Exception:
            valid = False
        output.append({
            "name": path.name,
            "size": path.stat().st_size,
            "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "sha256": _sha256(path),
            "valid": valid,
        })
    return output


def mobile_status() -> dict[str, Any]:
    devices = list_devices()
    snapshots = list_emergency_snapshots()
    return {
        "status": "ok",
        "mode": "command-center",
        "deviceCount": len([d for d in devices if d.get("enabled", True)]),
        "devices": devices,
        "latestEmergencySnapshot": snapshots[0] if snapshots else None,
        "capabilities": {
            "installableWebApp": True,
            "mobileUploads": True,
            "serverMonitoring": True,
            "manualBackups": True,
            "emergencyReadOnlyCopy": True,
            "phoneAsPrimaryServer": False,
        },
    }
