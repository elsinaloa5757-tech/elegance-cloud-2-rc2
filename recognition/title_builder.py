from __future__ import annotations

import re


def clean_model(brand: str, model: str) -> str:
    value = model.strip()
    if value.lower().startswith(brand.lower() + " "):
        value = value[len(brand):].strip()
    return value


def build_title(*, brand: str, model: str, color: str, sku: str = "") -> str:
    brand = brand.strip() or "Calzado"
    model = clean_model(brand, model)
    color = color.strip()
    pieces = [brand]
    if model:
        pieces.append(model)
    elif brand.lower() not in {"sin identificar", "calzado"}:
        pieces.append("modelo pendiente")
    if color and color.lower() not in model.lower():
        pieces.append(color)
    title = re.sub(r"\s+", " ", " ".join(pieces)).strip()
    return title
