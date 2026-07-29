from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.cloud_database import check_cloud_database
from services.home_server import external_backup_dir, server_status
from services.runtime_config import data_dir

REPORT_FILE = "block8_installation_report.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _tcp_open(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".elegance-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _read_cloudflared_version() -> str:
    if not _command_exists("cloudflared"):
        return ""
    try:
        result = subprocess.run(
            ["cloudflared", "--version"], capture_output=True, text=True, timeout=5, check=False
        )
        return (result.stdout or result.stderr).strip().splitlines()[0]
    except Exception:
        return ""


def installation_report(check_database: bool = True) -> dict[str, Any]:
    status = server_status()
    root = data_dir()
    external = external_backup_dir()
    port = int(os.getenv("PORT", "8000"))
    public_url = os.getenv("ELEGANCE_PUBLIC_URL", "").strip()
    db_url = os.getenv("DATABASE_URL", "").strip()
    db_check = check_cloud_database().as_dict() if (check_database and db_url) else {
        "configured": bool(db_url),
        "reachable": False,
        "provider": "postgresql" if db_url else "none",
        "detail": "Comprobación omitida." if db_url else "DATABASE_URL no configurada.",
    }

    checks = {
        "dataDirectoryWritable": _writable(root),
        "freeDiskAtLeast5GB": status["storage"]["free"] >= 5 * 1024**3,
        "databaseConfigured": bool(db_url),
        "databaseReachable": bool(db_check.get("reachable")),
        "localPortListening": _tcp_open("127.0.0.1", port),
        "cloudflaredInstalled": _command_exists("cloudflared"),
        "publicUrlConfigured": bool(public_url),
        "externalBackupConfigured": external is not None,
        "externalBackupWritable": _writable(external) if external is not None else False,
        "automaticBackupRunning": bool(status["server"]["schedulerRunning"]),
        "atLeastOneBackup": status["backup"]["count"] > 0,
    }

    required = [
        "dataDirectoryWritable",
        "freeDiskAtLeast5GB",
        "databaseConfigured",
        "databaseReachable",
        "localPortListening",
        "automaticBackupRunning",
        "atLeastOneBackup",
    ]
    recommended = ["cloudflaredInstalled", "publicUrlConfigured", "externalBackupConfigured", "externalBackupWritable"]
    blockers = [key for key in required if not checks[key]]
    warnings = [key for key in recommended if not checks[key]]

    report = {
        "status": "ready" if not blockers else "attention",
        "generatedAt": _now(),
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "database": db_check,
        "server": {
            "port": port,
            "publicUrl": public_url,
            "cloudflaredVersion": _read_cloudflared_version(),
            "dataDirectory": str(root),
            "externalBackupDirectory": str(external) if external else "",
        },
        "nextActions": _next_actions(checks),
    }
    path = root / REPORT_FILE
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _next_actions(checks: dict[str, bool]) -> list[str]:
    actions: list[str] = []
    if not checks["databaseConfigured"]:
        actions.append("Ejecutar Configurar-PostgreSQL-Bloque8.ps1 como administrador.")
    elif not checks["databaseReachable"]:
        actions.append("Revisar el servicio PostgreSQL y la contraseña guardada en .env.server.")
    if not checks["localPortListening"]:
        actions.append("Iniciar o reiniciar la tarea programada Elegance Server.")
    if not checks["atLeastOneBackup"]:
        actions.append("Ejecutar Crear-Respaldo-Ahora.ps1 y verificar el archivo generado.")
    if not checks["externalBackupConfigured"]:
        actions.append("Configurar ELEGANCE_EXTERNAL_BACKUP_DIR en una segunda unidad.")
    elif not checks["externalBackupWritable"]:
        actions.append("Conectar o dar permisos de escritura a la unidad de respaldo externo.")
    if not checks["cloudflaredInstalled"]:
        actions.append("Ejecutar Instalar-Tunel-Cloudflare-Bloque8.ps1.")
    if not checks["publicUrlConfigured"]:
        actions.append("Completar el túnel y guardar ELEGANCE_PUBLIC_URL.")
    if not actions:
        actions.append("Realizar la prueba final desde el S26 Ultra usando datos móviles.")
    return actions
