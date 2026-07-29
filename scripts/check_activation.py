from __future__ import annotations

import json

from services.cloud_database import check_cloud_database
from services.cloud_storage import storage_status
from services.deployment_readiness import deployment_readiness


def main() -> int:
    payload = {
        "deployment": deployment_readiness(check_database=True),
        "database": check_cloud_database().as_dict(),
        "storage": storage_status(check_remote=True),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["deployment"]["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
