from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

import requests

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
SCENE_PATH = ASSETS_DIR / "elegance_scenario_official.png"
FALLBACK_SCENE_PATH = ASSETS_DIR / "elegance_boutique_official.png"
OPENAI_IMAGE_ENDPOINT = "https://api.openai.com/v1/images/edits"


@dataclass(frozen=True)
class GenerativeResult:
    image_bytes: bytes
    engine: str
    note: str


def _scene_bytes() -> bytes:
    path = SCENE_PATH if SCENE_PATH.exists() else FALLBACK_SCENE_PATH
    if not path.exists():
        raise RuntimeError("No se encontró el escenario oficial de elegance")
    return path.read_bytes()


def _prompt(brand_theme: str, product_name: str = "") -> str:
    brand = brand_theme.strip() or "automático"
    product = product_name.strip() or "el calzado de la primera imagen"
    return f"""
Crea una fotografía comercial vertical, fotorrealista y de alta gama para el catálogo de elegance.

IMAGEN 1: fotografía original del producto sostenido por una mano.
IMAGEN 2: referencia visual oficial de la boutique elegance. Puede contener un sneaker y un brazo de ejemplo; IGNÓRALOS por completo. Usa exclusivamente la arquitectura, pantera, recepción, tapete, iluminación azul hielo y atmósfera de la boutique.

Objetivo: reconstruir una sola fotografía nueva y coherente, no un collage ni un recorte pegado.
Conserva con máxima fidelidad el diseño exacto de {product}: silueta, logotipos, materiales, costuras, suela, agujetas, color y proporciones. Conserva la misma mano de la primera imagen, su tono de piel, pulsera, tatuajes y pose general. Reconstruye de forma natural el contacto físico de palma y dedos con el producto; los dedos deben rodear o sostener la suela con anatomía correcta. La mano debe sostenerlo físicamente, sin huecos, cortes, duplicaciones ni extremidades extra.

Integra el producto dentro del ambiente de la segunda imagen como si la foto hubiera sido tomada realmente en esa boutique. Usa iluminación azul hielo coherente, sombras de contacto reales, reflejos naturales y profundidad de campo profesional. Adapta discretamente la ambientación secundaria a la marca o modelo: {brand}, sin reemplazar la identidad principal de elegance.

Elimina por completo el fondo original, etiquetas de talla, stickers, textos flotantes, bordes de recorte y cualquier elemento duplicado. No copies el sneaker, brazo ni mano de la IMAGEN 2. No agregues otro tenis, otra mano, un brazo adicional, etiquetas de talla ni rectángulos. Debe existir exactamente un producto y exactamente una mano sosteniéndolo. No cambies el modelo del producto. Mantén visible el logotipo elegance en cursiva dentro de la boutique, pero no escribas títulos ni tallas sobre la imagen.

Composición: producto grande y protagonista, sostenido por la mano en primer plano, perspectiva natural, boutique completa al fondo, aspecto fotográfico premium, 1024x1536 vertical.
""".strip()


def edit_with_openai(
    image_bytes: bytes,
    *,
    api_key: str | None,
    brand_theme: str = "Automático",
    product_name: str = "",
    model: str = "gpt-image-1",
    timeout_seconds: int = 300,
) -> GenerativeResult:
    key = (api_key or os.getenv("OPENAI_API_KEY", "")).strip()
    if not key:
        raise ValueError("Falta configurar la OpenAI API key para la edición generativa real.")

    files = [
        ("image[]", ("producto.jpg", image_bytes, "image/jpeg")),
        ("image[]", ("escenario_elegance.png", _scene_bytes(), "image/png")),
    ]
    data = {
        "model": model or "gpt-image-1",
        "prompt": _prompt(brand_theme, product_name),
        "size": "1024x1536",
        "quality": os.getenv("ELEGANCE_IMAGE_QUALITY", "medium"),
        "output_format": "jpeg",
        "output_compression": "88",
        "background": "opaque",
    }
    try:
        response = requests.post(
            OPENAI_IMAGE_ENDPOINT,
            headers={"Authorization": f"Bearer {key}"},
            files=files,
            data=data,
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"No se pudo conectar con el motor generativo: {exc}") from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except Exception:
            detail = response.text
        raise RuntimeError(f"OpenAI Images {response.status_code}: {detail}")

    payload = response.json()
    items = payload.get("data") or []
    if not items or not items[0].get("b64_json"):
        raise RuntimeError("El motor generativo no devolvió una imagen final.")
    try:
        result = base64.b64decode(items[0]["b64_json"])
    except Exception as exc:
        raise RuntimeError("La imagen generada llegó dañada.") from exc
    return GenerativeResult(
        image_bytes=result,
        engine=model or "gpt-image-1",
        note="Edición generativa completa optimizada: producto y mano reconstruidos dentro del escenario; salida JPEG ligera para catálogo.",
    )
