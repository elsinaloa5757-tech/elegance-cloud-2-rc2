from __future__ import annotations

from pathlib import Path
from pprint import pprint

import requests

folder_text = input(
    "Ruta de la carpeta con imágenes: "
).strip().strip('"')

folder = Path(folder_text)

if not folder.is_dir():
    raise SystemExit("La carpeta no existe.")

allowed = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}

paths = [
    path
    for path in folder.iterdir()
    if path.suffix.lower() in allowed
]

if not paths:
    raise SystemExit(
        "No se encontraron imágenes compatibles."
    )

handles = []
payload = []

try:
    for path in paths:
        handle = path.open("rb")
        handles.append(handle)

        payload.append(
            (
                "files",
                (
                    path.name,
                    handle,
                    "image/jpeg",
                ),
            )
        )

    response = requests.post(
        "http://127.0.0.1:8000/analyze",
        files=payload,
        params={
            "eps": 0.22,
            "min_samples": 1,
        },
        timeout=900,
    )

    print()
    print("Código HTTP:", response.status_code)
    pprint(response.json())
finally:
    for handle in handles:
        handle.close()
