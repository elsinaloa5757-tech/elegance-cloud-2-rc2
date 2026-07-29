from __future__ import annotations
import json
from services.cloud_database import check_cloud_database

if __name__ == "__main__":
    status = check_cloud_database()
    print(json.dumps(status.as_dict(), ensure_ascii=False, indent=2))
    raise SystemExit(0 if status.reachable else 2)
