from __future__ import annotations

import re
import shutil
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

from services.fashion_library import CATEGORY_TREE, normalize_text as library_normalize_text
from services.smart_catalog import enrich_product

ROOT = Path(__file__).resolve().parents[1]
from services.runtime_config import data_dir
DATA = data_dir()
DB = DATA / "elegance.sqlite3"
CATALOG = DATA / "catalogo"

_ALIASES = {
    "nike": "Nike",
    "nike sportswear": "Nike",
    "jordan": "Jordan",
    "air jordan": "Jordan",
    "adidas": "Adidas",
    "adidas originals": "Adidas",
    "hugo boss": "Hugo Boss",
    "hugoboss": "Hugo Boss",
    "boss": "Hugo Boss",
    "new balance": "New Balance",
    "newbalance": "New Balance",
    "converse": "Converse",
    "puma": "Puma",
    "reebok": "Reebok",
    "vans": "Vans",
    "under armour": "Under Armour",
    "underarmour": "Under Armour",
    "lacoste": "Lacoste",
    "gucci": "Gucci",
    "louis vuitton": "Louis Vuitton",
    "lv": "Louis Vuitton",
    "balenciaga": "Balenciaga",
    "versace": "Versace",
    "skechers": "Skechers",
    "fila": "Fila",
    "on running": "On Running",
    "on": "On Running",
}
_UNKNOWN = {"", "unknown", "sin marca", "sin identificar", "por identificar", "calzado"}


_CATEGORY_KEYWORDS = {
    "Calzado": {
        "Sneakers": ["sneaker", "tenis", "trainer", "jordan", "dunk", "air force", "air max", "yeezy", "samba", "gazelle", "campus", "converse", "vans", "running"],
        "Botas": ["bota", "boot", "timberland", "1460", "work boot"],
        "Botines": ["botin", "ankle boot", "chelsea"],
        "Zapatos": ["zapato", "loafer", "oxford", "derby"],
        "Sandalias": ["sandalia", "slide", "sandal"],
        "Tacones": ["tacon", "heel", "pump"],
        "Mocasines": ["mocasin", "moccasin", "loafer"],
    },
    "Ropa": {
        "Playeras": ["playera", "camiseta", "t shirt", "tee"],
        "Camisas": ["camisa", "shirt"],
        "Sudaderas": ["sudadera", "hoodie", "sweatshirt"],
        "Chamarras": ["chamarra", "chaqueta", "jacket", "coat"],
        "Pantalones": ["pantalon", "trouser", "pants"],
        "Jeans": ["jean", "denim"],
        "Shorts": ["short"],
        "Vestidos": ["vestido", "dress"],
        "Faldas": ["falda", "skirt"],
    },
    "Bolsas": {
        "Bolsos": ["bolso", "handbag", "shoulder bag", "birkin", "kelly", "speedy"],
        "Mochilas": ["mochila", "backpack"],
        "Crossbody": ["crossbody"],
        "Tote": ["tote"],
        "Clutch": ["clutch"],
        "Carteras": ["cartera", "wallet"],
    },
    "Accesorios": {
        "Gorras": ["gorra", "cap", "hat"],
        "Cinturones": ["cinturon", "belt"],
        "Lentes": ["lentes", "gafas", "sunglasses", "eyewear"],
        "Bufandas": ["bufanda", "scarf"],
        "Guantes": ["guante", "glove"],
        "Llaveros": ["llavero", "keychain"],
    },
    "Joyería": {
        "Relojes": ["reloj", "watch", "rolex", "omega", "santos"],
        "Pulseras": ["pulsera", "bracelet"],
        "Collares": ["collar", "necklace"],
        "Anillos": ["anillo", "ring"],
        "Aretes": ["arete", "earring"],
    },
    "Equipaje": {
        "Maletas": ["maleta", "suitcase", "luggage"],
        "Carry-on": ["carry on", "carry-on"],
        "Duffles": ["duffle", "keepall"],
        "Organizadores": ["organizador", "organizer"],
    },
    "Otros": {
        "Coleccionables": ["coleccionable", "collectible"],
        "Cuidado del producto": ["limpiador", "protector", "cuidado", "care kit"],
        "Empaque": ["empaque", "caja", "packaging"],
    },
}

def classify_category(product: dict[str, Any]) -> tuple[str, str, float, str]:
    existing_category = str(product.get("category") or product.get("categoria") or "").strip()
    existing_subcategory = str(product.get("subcategory") or product.get("subcategoria") or "").strip()
    if existing_category in CATEGORY_TREE and existing_subcategory in CATEGORY_TREE[existing_category]:
        return existing_category, existing_subcategory, float(product.get("categoryConfidence") or 1.0), str(product.get("categorySource") or "manual")
    haystack = library_normalize_text(" ".join(str(product.get(k) or "") for k in ("title", "brand", "model", "notes", "sku")))
    best=("Otros", "Coleccionables", 0, "fallback")
    for category, children in _CATEGORY_KEYWORDS.items():
        for subcategory, words in children.items():
            score=sum(1 for word in words if library_normalize_text(word) in haystack)
            if score>best[2]: best=(category, subcategory, score, "automatic-keywords")
    if best[2] == 0:
        brand=normalize_brand(str(product.get("brand") or ""))
        if brand not in {"Sin identificar", ""}:
            return "Calzado", "Sneakers", 0.55, "legacy-footwear-safe-default"
        return "Otros", "Coleccionables", 0.35, "safe-fallback"
    return best[0], best[1], min(0.99, 0.62 + best[2]*0.1), best[3]


def _plain(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.strip().lower())


def normalize_brand(value: str) -> str:
    key = _plain(value)
    if key in _UNKNOWN:
        return "Sin identificar"
    if key in _ALIASES:
        return _ALIASES[key]
    # Keep user-created brands but standardize whitespace and capitalization.
    return " ".join(word.upper() if len(word) <= 3 and word.isalpha() else word.capitalize() for word in key.split())


def normalize_model(value: str) -> str:
    key = re.sub(r"\s+", " ", (value or "").strip())
    if _plain(key) in {"", "unknown", "sin modelo", "modelo pendiente", "por identificar"}:
        return ""
    return key


def _safe_folder(value: str, fallback: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value.strip())
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:100] or fallback


def organize_state(state: dict[str, Any], *, move_files: bool = True) -> dict[str, Any]:
    products = state.get("products")
    if not isinstance(products, list):
        return {"state": state, "moved": 0, "normalized": 0, "errors": [], "categories": {}}

    CATALOG.mkdir(parents=True, exist_ok=True)
    normalized = 0
    moved = 0
    errors: list[str] = []
    categories: dict[str, int] = {}
    subcategories: dict[str, int] = {}
    classified = 0
    preserved = 0

    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        for product in products:
            if not isinstance(product, dict):
                continue
            enrich_product(product)
            before_brand = str(product.get("brand") or "")
            before_model = str(product.get("model") or "")
            brand = normalize_brand(before_brand)
            model = normalize_model(before_model)
            product["brand"] = brand
            product["model"] = model
            had_category = bool(str(product.get("category") or product.get("categoria") or "").strip())
            category, subcategory, category_confidence, category_source = classify_category(product)
            product["category"] = category
            product["subcategory"] = subcategory
            product["categoryConfidence"] = category_confidence
            product["categorySource"] = category_source
            product["catalogPath"] = f"{category}/{subcategory}/{brand}/{model or 'Modelo pendiente'}"
            if brand != before_brand or model != before_model:
                normalized += 1
            if had_category: preserved += 1
            else: classified += 1
            categories[category] = categories.get(category, 0) + 1
            sub_key = f"{category} / {subcategory}"
            subcategories[sub_key] = subcategories.get(sub_key, 0) + 1

            product_id = str(product.get("id") or "")
            if not move_files or not product_id.startswith("mobile-"):
                continue
            file_id = product_id.removeprefix("mobile-")
            row = con.execute(
                "SELECT source_path,thumb_path FROM mobile_files WHERE id=?", (file_id,)
            ).fetchone()
            if not row:
                continue
            destination = CATALOG / _safe_folder(category, "Otros") / _safe_folder(subcategory, "Coleccionables") / _safe_folder(brand, "Sin identificar") / _safe_folder(model or "Modelo pendiente", "Modelo pendiente")
            destination.mkdir(parents=True, exist_ok=True)
            updates: dict[str, str] = {}
            for column in ("source_path", "thumb_path"):
                raw = row[column]
                if not raw:
                    continue
                source = Path(raw)
                if not source.exists():
                    continue
                target = destination / source.name
                try:
                    if source.resolve() != target.resolve():
                        if target.exists() and target.resolve() != source.resolve():
                            target = destination / f"{file_id}_{source.name}"
                        shutil.move(str(source), str(target))
                        moved += 1
                    updates[column] = str(target)
                except OSError as exc:
                    errors.append(f"{source.name}: {exc}")
            if updates:
                con.execute(
                    "UPDATE mobile_files SET source_path=COALESCE(?,source_path),thumb_path=COALESCE(?,thumb_path),updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (updates.get("source_path"), updates.get("thumb_path"), file_id),
                )
        con.commit()
    finally:
        con.close()

    state["catalogCategories"] = dict(sorted(categories.items()))
    state["catalogSubcategories"] = dict(sorted(subcategories.items()))
    state["categorySchemaVersion"] = 3
    state["smartCatalogVersion"] = 3
    return {"state": state, "moved": moved, "normalized": normalized, "classified": classified, "preserved": preserved, "errors": errors[:25], "categories": state["catalogCategories"], "subcategories": state["catalogSubcategories"], "catalog_root": str(CATALOG)}
