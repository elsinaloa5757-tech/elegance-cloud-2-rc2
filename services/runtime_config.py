from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    """Return the persistent application data directory.

    Production deployments must set ELEGANCE_DATA_DIR to a mounted persistent
    volume. Development defaults to the bundled backend/data directory.
    """
    configured = os.getenv("ELEGANCE_DATA_DIR", "").strip()
    target = Path(configured).expanduser() if configured else BACKEND_DIR / "data"
    target.mkdir(parents=True, exist_ok=True)
    return target.resolve()


def database_file() -> Path:
    override = os.getenv("ELEGANCE_SQLITE_PATH", "").strip()
    path = Path(override).expanduser() if override else data_dir() / "elegance.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def require_production_configuration() -> None:
    if os.getenv("ELEGANCE_ENV", "development").lower() != "production":
        return
    server_mode = os.getenv("ELEGANCE_SERVER_MODE", "cloud").strip().lower()
    if server_mode != "home" and not os.getenv("DATABASE_URL", "").strip():
        raise RuntimeError("DATABASE_URL es obligatoria en producción de nube. En servidor propio usa ELEGANCE_SERVER_MODE=home.")
    if not os.getenv("ELEGANCE_DATA_DIR", "").strip():
        raise RuntimeError("ELEGANCE_DATA_DIR sigue siendo obligatorio para archivos temporales y caché persistente.")
    origins = [x.strip() for x in os.getenv("ELEGANCE_ALLOWED_ORIGINS", "").split(",") if x.strip()]
    if not origins:
        raise RuntimeError("ELEGANCE_ALLOWED_ORIGINS debe contener al menos un origen permitido.")
    if server_mode != "home":
        if any("localhost" in x or "127.0.0.1" in x for x in origins):
            raise RuntimeError("ELEGANCE_ALLOWED_ORIGINS debe contener únicamente orígenes HTTPS públicos en producción de nube.")
        if any(not x.startswith("https://") for x in origins):
            raise RuntimeError("Todos los orígenes de producción de nube deben usar HTTPS.")
    else:
        public = [x for x in origins if "localhost" not in x and "127.0.0.1" not in x]
        if any(not x.startswith("https://") for x in public):
            raise RuntimeError("Los orígenes públicos del servidor propio deben usar HTTPS.")
