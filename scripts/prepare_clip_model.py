"""Descarga y valida el modelo CLIP local durante la instalación de Elegance."""
from __future__ import annotations

import sys

try:
    from sentence_transformers import SentenceTransformer
except Exception as exc:
    print(f"ERROR: sentence-transformers no está disponible: {exc}")
    raise SystemExit(1)

MODEL_NAME = "clip-ViT-B-32"

try:
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    vector = model.encode(["a product photo"], show_progress_bar=False, convert_to_numpy=True)
    if getattr(vector, "shape", (0,))[0] != 1:
        raise RuntimeError("El modelo no devolvió una representación válida.")
    print(f"Modelo visual {MODEL_NAME} preparado correctamente.")
except Exception as exc:
    print(f"ERROR: no se pudo preparar {MODEL_NAME}: {exc}")
    raise SystemExit(1)
