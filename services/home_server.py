from __future__ import annotations

import json
import os
import shutil
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.full_backup import create_full_backup, list_full_backups
from services.runtime_config import data_dir, database_file

_STATE_LOCK = threading.Lock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
STATE_FILE = "home_server_state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path() -> Path:
    path = data_dir() / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"lastDailyBackup": "", "lastWeeklyBackup": "", "lastError": "", "startedAt": _now()}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"lastDailyBackup": "", "lastWeeklyBackup": "", "lastError": "state_corrupt", "startedAt": _now()}


def _save_state(state: dict[str, Any]) -> None:
    tmp = _state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_state_path())


def _age_hours(value: str) -> float:
    if not value:
        return 10**9
    try:
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(value)).total_seconds() / 3600)
    except Exception:
        return 10**9


def external_backup_dir() -> Path | None:
    configured = os.getenv("ELEGANCE_EXTERNAL_BACKUP_DIR", "").strip()
    if not configured:
        return None
    path = Path(configured).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def copy_backup_external(backup_name: str) -> dict[str, Any]:
    target_dir = external_backup_dir()
    if target_dir is None:
        return {"status": "skipped", "reason": "ELEGANCE_EXTERNAL_BACKUP_DIR no configurado"}
    source = data_dir() / "full_backups" / Path(backup_name).name
    if not source.exists():
        raise FileNotFoundError(source)
    destination = target_dir / source.name
    shutil.copy2(source, destination)
    return {"status": "ok", "path": str(destination), "size": destination.stat().st_size}


def run_scheduled_backup(kind: str = "daily") -> dict[str, Any]:
    kind = "weekly" if kind == "weekly" else "daily"
    result = create_full_backup(f"scheduled_{kind}")
    external = copy_backup_external(result["name"])
    with _STATE_LOCK:
        state = _load_state()
        state["lastDailyBackup" if kind == "daily" else "lastWeeklyBackup"] = result["createdAt"]
        state["lastError"] = ""
        _save_state(state)
    return {"status": "ok", "kind": kind, "backup": result, "externalCopy": external}


def _scheduler_loop() -> None:
    interval = max(60, int(os.getenv("ELEGANCE_BACKUP_CHECK_SECONDS", "900")))
    daily_hours = max(1, int(os.getenv("ELEGANCE_DAILY_BACKUP_HOURS", "24")))
    weekly_hours = max(24, int(os.getenv("ELEGANCE_WEEKLY_BACKUP_HOURS", "168")))
    while not _STOP.wait(interval):
        try:
            state = _load_state()
            if _age_hours(state.get("lastDailyBackup", "")) >= daily_hours:
                run_scheduled_backup("daily")
                state = _load_state()
            if _age_hours(state.get("lastWeeklyBackup", "")) >= weekly_hours:
                run_scheduled_backup("weekly")
        except Exception as exc:
            with _STATE_LOCK:
                state = _load_state()
                state["lastError"] = f"{type(exc).__name__}: {exc}"
                _save_state(state)


def start_backup_scheduler() -> None:
    global _THREAD
    if os.getenv("ELEGANCE_ENABLE_BACKUP_SCHEDULER", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    if _THREAD and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=_scheduler_loop, name="elegance-backup-scheduler", daemon=True)
    _THREAD.start()


def stop_backup_scheduler() -> None:
    _STOP.set()
    if _THREAD and _THREAD.is_alive():
        _THREAD.join(timeout=3)


def server_status() -> dict[str, Any]:
    root = data_dir()
    usage = shutil.disk_usage(root)
    db = database_file()
    backups = list_full_backups()
    state = _load_state()
    public_url = os.getenv("ELEGANCE_PUBLIC_URL", "").strip()
    tunnel_mode = os.getenv("ELEGANCE_TUNNEL_MODE", "cloudflared").strip().lower()
    return {
        "status": "ok",
        "server": {
            "hostname": socket.gethostname(),
            "mode": os.getenv("ELEGANCE_SERVER_MODE", "home"),
            "startedAt": state.get("startedAt", ""),
            "schedulerRunning": bool(_THREAD and _THREAD.is_alive()),
        },
        "database": {
            "engine": "postgresql" if os.getenv("DATABASE_URL", "").strip() else "sqlite",
            "path": str(db) if not os.getenv("DATABASE_URL", "").strip() else "configured-by-DATABASE_URL",
            "exists": db.exists() if not os.getenv("DATABASE_URL", "").strip() else True,
            "size": db.stat().st_size if db.exists() else 0,
        },
        "storage": {
            "path": str(root),
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "freePercent": round((usage.free / usage.total) * 100, 2) if usage.total else 0,
        },
        "backup": {
            "count": len(backups),
            "latest": backups[0] if backups else None,
            "lastDailyBackup": state.get("lastDailyBackup", ""),
            "lastWeeklyBackup": state.get("lastWeeklyBackup", ""),
            "lastError": state.get("lastError", ""),
            "externalDirectoryConfigured": external_backup_dir() is not None,
        },
        "publicAccess": {
            "url": public_url,
            "configured": bool(public_url),
            "tunnelMode": tunnel_mode,
            "directRouterPortsRequired": False if tunnel_mode == "cloudflared" else None,
        },
    }
