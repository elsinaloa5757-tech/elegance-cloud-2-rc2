from __future__ import annotations

import re
import unicodedata
from typing import Any

BRAND_ALIASES = {
    "nike": "Nike", "air jordan": "Jordan", "jordan": "Jordan", "adidas": "Adidas",
    "new balance": "New Balance", "newbalance": "New Balance", "puma": "Puma",
    "reebok": "Reebok", "vans": "Vans", "converse": "Converse", "timberland": "Timberland",
    "gucci": "Gucci", "louis vuitton": "Louis Vuitton", "lv": "Louis Vuitton",
    "balenciaga": "Balenciaga", "versace": "Versace", "lacoste": "Lacoste",
    "hugo boss": "Hugo Boss", "boss": "Hugo Boss", "rolex": "Rolex", "omega": "Omega",
}
COLOR_WORDS = {
    "Negro": ["negro", "black"], "Blanco": ["blanco", "white"], "Azul": ["azul", "blue", "navy"],
    "Rojo": ["rojo", "red", "burgundy"], "Verde": ["verde", "green", "olive"],
    "Gris": ["gris", "gray", "grey"], "Beige": ["beige", "cream", "arena", "tan"],
    "Café": ["cafe", "brown", "camel"], "Rosa": ["rosa", "pink"], "Morado": ["morado", "purple"],
    "Amarillo": ["amarillo", "yellow", "gold"], "Naranja": ["naranja", "orange"],
}

def plain(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()

def classify_brand(product: dict[str, Any]) -> tuple[str, float, str]:
    current = str(product.get("brand") or "").strip()
    key = plain(current)
    if key and key not in {"sin identificar", "unknown", "calzado"}:
        return BRAND_ALIASES.get(key, current.strip()), 1.0, "preserved"
    text = plain(" ".join(str(product.get(k) or "") for k in ("title", "model", "notes", "sku")))
    for alias, brand in sorted(BRAND_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if alias in text:
            return brand, .92, "automatic-text"
    return "Sin identificar", .25, "safe-fallback"

def classify_gender(product: dict[str, Any]) -> tuple[str, float]:
    existing = str(product.get("gender") or product.get("genero") or "").strip()
    if existing in {"Hombre", "Mujer", "Unisex", "Niño", "Niña"}: return existing, 1.0
    text = plain(" ".join(str(product.get(k) or "") for k in ("title", "model", "notes", "category", "subcategory")))
    if any(x in text for x in ("mujer", "dama", "women", "woman", "femenino", "tacon", "falda", "vestido")): return "Mujer", .86
    if any(x in text for x in ("nino", "kids", "infantil", "junior", "gs", "ps", "td")): return "Niño", .75
    if any(x in text for x in ("hombre", "caballero", "men", "masculino")): return "Hombre", .86
    return "Unisex", .58

def classify_colors(product: dict[str, Any]) -> tuple[str, list[str], float]:
    existing = str(product.get("color") or product.get("primaryColor") or "").strip()
    text = plain(" ".join(str(product.get(k) or "") for k in ("color", "title", "model", "notes")))
    found=[]
    for name, words in COLOR_WORDS.items():
        if any(plain(w) in text for w in words): found.append(name)
    if existing and plain(existing) not in {"", "sin color"}:
        primary=existing
        secondary=[x for x in found if plain(x)!=plain(primary)]
        return primary, secondary[:4], 1.0
    if found: return found[0], found[1:5], .82
    return "Sin identificar", [], .25

def classify_season(product: dict[str, Any]) -> tuple[str, float]:
    existing = str(product.get("season") or product.get("temporada") or "").strip()
    if existing in {"Primavera", "Verano", "Otoño", "Invierno", "Todo el año"}: return existing, 1.0
    text=plain(" ".join(str(product.get(k) or "") for k in ("title", "model", "notes", "subcategory")))
    if any(x in text for x in ("bota", "boot", "chamarra", "abrigo", "bufanda", "invierno")): return "Invierno", .78
    if any(x in text for x in ("sandalia", "short", "verano", "summer")): return "Verano", .78
    if any(x in text for x in ("impermeable", "rain", "otono")): return "Otoño", .68
    return "Todo el año", .72

def enrich_product(product: dict[str, Any]) -> dict[str, Any]:
    brand, brand_confidence, brand_source = classify_brand(product)
    gender, gender_confidence = classify_gender(product)
    primary, secondary, color_confidence = classify_colors(product)
    season, season_confidence = classify_season(product)
    product["brand"] = brand
    product["brandConfidence"] = brand_confidence
    product["brandSource"] = brand_source
    product["gender"] = gender
    product["genderConfidence"] = gender_confidence
    product["color"] = primary
    product["primaryColor"] = primary
    product["secondaryColors"] = secondary
    product["colorConfidence"] = color_confidence
    product["season"] = season
    product["seasonConfidence"] = season_confidence
    product["smartCatalogVersion"] = 3
    return product
