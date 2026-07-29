from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from services.cloud_database import check_cloud_database
from services.runtime_config import data_dir
from services.cloud_storage import storage_status


def _https_url(name: str) -> tuple[bool, str]:
    value = os.getenv(name, "").strip()
    if not value:
        return False, "no configurada"
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        return False, "debe ser una URL HTTPS válida"
    return True, parsed.netloc


def deployment_readiness(check_database: bool = True) -> dict:
    env = os.getenv("ELEGANCE_ENV", "development").lower()
    checks: dict[str, dict] = {}

    public_ok, public_detail = _https_url("ELEGANCE_PUBLIC_URL")
    checks["publicUrl"] = {"ok": public_ok, "detail": public_detail}

    origins = [x.strip() for x in os.getenv("ELEGANCE_ALLOWED_ORIGINS", "").split(",") if x.strip()]
    origins_ok = bool(origins) and all(x.startswith("https://") and "localhost" not in x and "127.0.0.1" not in x for x in origins)
    checks["cors"] = {"ok": origins_ok, "detail": origins if origins else "sin orígenes configurados"}

    storage = data_dir()
    try:
        probe = storage / ".elegance_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        storage_ok = True
        storage_detail = str(storage)
    except Exception as exc:
        storage_ok = False
        storage_detail = f"{type(exc).__name__}: {exc}"
    checks["persistentStorage"] = {"ok": storage_ok, "detail": storage_detail}

    supabase_url_ok, supabase_url_detail = _https_url("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    publishable = os.getenv("SUPABASE_PUBLISHABLE_KEY", os.getenv("SUPABASE_ANON_KEY", "")).strip()
    checks["supabase"] = {
        "ok": supabase_url_ok and bool(service_key) and bool(publishable),
        "detail": {
            "url": supabase_url_detail,
            "serviceRoleConfigured": bool(service_key),
            "publishableKeyConfigured": bool(publishable),
        },
    }

    storage_cloud = storage_status(check_remote=False)
    storage_mode_ok = storage_cloud["mode"] in {"supabase", "mirror"} and storage_cloud["supabaseConfigured"]
    checks["cloudStorage"] = {
        "ok": storage_mode_ok,
        "detail": {
            "mode": storage_cloud["mode"],
            "bucket": storage_cloud["bucket"],
            "supabaseConfigured": storage_cloud["supabaseConfigured"],
        },
    }

    db = check_cloud_database() if check_database else None
    checks["postgresql"] = {
        "ok": bool(db and db.reachable),
        "detail": db.as_dict() if db else {"configured": bool(os.getenv("DATABASE_URL")), "checked": False},
    }

    required = ["publicUrl", "cors", "persistentStorage", "supabase", "postgresql", "cloudStorage"] if env == "production" else ["persistentStorage"]
    ready = all(checks[name]["ok"] for name in required)
    return {
        "status": "ready" if ready else "not-ready",
        "environment": env,
        "ready": ready,
        "requiredChecks": required,
        "checks": checks,
    }
