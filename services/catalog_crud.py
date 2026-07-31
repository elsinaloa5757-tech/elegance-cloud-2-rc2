from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from services.state_store import database_path, load_state, save_state
from services.product_workflow import migrate_sprint6, list_inventory, sum_variant_stock
from services.public_catalog import sync_products, update_publication
from services.universal_products import classify as universal_classify, save_product_attributes

UNIVERSAL_CATEGORIES = [
    "Calzado", "Ropa", "Accesorios", "Relojes", "Bolsos", "Belleza",
    "Hogar", "Electrónica", "Juguetes", "Deportes", "Otros",
]
STATUS_VALUES = {"available", "sold_out", "inactive", "draft"}
LIST_ONLY_HEAVY_FIELDS = {
    "imageBase64", "galleryBase64", "image_base64", "gallery_base64",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db() -> sqlite3.Connection:
    connection = sqlite3.connect(database_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _browser_image_url(value: str) -> str:
    """Turn legacy filesystem references into URLs the browser can request."""
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or raw.startswith(("https://", "http://", "data:", "blob:", "/media/", "/assets/")):
        return raw
    if raw.startswith("data/"):
        return "/media/" + raw[5:]
    marker = "/data/"
    if marker in raw:
        return "/media/" + raw.split(marker, 1)[1]
    for prefix in ("uploads/", "products/", "media_library/", "storage_manager/"):
        if raw.startswith(prefix):
            return "/media/" + raw
    return raw if raw.startswith("/") else "/media/" + raw.lstrip("./")


def _state() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state = load_state()
    if not isinstance(state, dict):
        state = {}
    products = state.setdefault("products", [])
    if not isinstance(products, list):
        products = []
        state["products"] = products
    return state, products


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        values = value
    else:
        import re
        values = re.split(r"[,;/|]+", str(value or ""))
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _category(payload: dict[str, Any], current: dict[str, Any] | None = None) -> tuple[str, str, dict]:
    current = current or {}
    explicit = str(payload.get("category") or "").strip()
    subcategory = str(payload.get("subcategory") or current.get("subcategory") or "").strip()
    if explicit:
        category = explicit
        result = {"category": category, "subcategory": subcategory, "confidence": 1.0, "method": "manual"}
    else:
        result = universal_classify({
            "title": payload.get("title") or current.get("title") or "",
            "brand": payload.get("brand") or current.get("brand") or "",
            "model": payload.get("model") or current.get("model") or "",
            "description": payload.get("description") or current.get("description") or "",
        })
        category = str(result.get("category") or current.get("category") or "Otros")
        subcategory = str(result.get("subcategory") or subcategory)
    if category not in UNIVERSAL_CATEGORIES:
        # Preserve a valid existing taxonomy name, but group unknown values in Otros.
        category = category or "Otros"
    return category, subcategory, result


def _ensure_publication_table() -> None:
    with _db() as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS product_publication(
            product_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'draft',
            featured INTEGER NOT NULL DEFAULT 0, promotion_price REAL,
            hide_when_sold_out INTEGER NOT NULL DEFAULT 1, slug TEXT NOT NULL DEFAULT '',
            public_title TEXT NOT NULL DEFAULT '', public_description TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_publication_slug ON product_publication(slug) WHERE slug<>'';
        CREATE INDEX IF NOT EXISTS idx_publication_status ON product_publication(status);
        """)


def _sync_variants(product_id: str, variants: list[dict[str, Any]], default_price: float) -> None:
    stamp = _now()
    with _db() as connection:
        connection.execute("DELETE FROM product_variants WHERE product_id=?", (product_id,))
        for item in variants:
            size = str(item.get("size") or "").strip()
            color = str(item.get("color") or "").strip()
            stock = max(0, int(item.get("stock") or 0))
            sale_price = max(0.0, float(item.get("salePrice", item.get("sale_price", default_price)) or 0))
            purchase_price = max(0.0, float(item.get("purchasePrice", item.get("purchase_price", 0)) or 0))
            connection.execute(
                "INSERT INTO product_variants(id,product_id,size,color,sku,stock,purchase_price,sale_price,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(item.get("id") or f"var_{uuid.uuid4().hex[:16]}"), product_id, size, color,
                    str(item.get("sku") or "").strip(), stock, purchase_price, sale_price,
                    "available" if stock > 0 else "sold_out", stamp, stamp,
                ),
            )


def create_product(payload: dict[str, Any]) -> dict[str, Any]:
    migrate_sprint6()
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValueError("El nombre del producto es obligatorio.")
    category, subcategory, classification = _category(payload)
    stamp = _now()
    product_id = f"prd_{uuid.uuid4().hex[:16]}"
    price = max(0.0, float(payload.get("price") or payload.get("salePrice") or 0))
    variants = payload.get("variants") if isinstance(payload.get("variants"), list) else []
    sizes = _clean_list(payload.get("sizes"))
    colors = _clean_list(payload.get("colors"))
    if not variants and (sizes or colors or payload.get("stock") is not None):
        variants = [{"size": sizes[0] if sizes else "", "color": colors[0] if colors else "", "stock": payload.get("stock") or 0, "salePrice": price}]
    product = {
        "id": product_id,
        "title": title,
        "brand": str(payload.get("brand") or "").strip(),
        "model": str(payload.get("model") or "").strip(),
        "category": category,
        "subcategory": subcategory,
        "type": str(payload.get("type") or category),
        "sizes": sizes,
        "colors": colors,
        "price": price,
        "purchasePrice": max(0.0, float(payload.get("purchasePrice") or 0)),
        "description": str(payload.get("description") or "").strip(),
        "status": str(payload.get("status") or "draft") if str(payload.get("status") or "draft") in STATUS_VALUES else "draft",
        "stock": 0,
        "originalImages": [],
        "approvedStudioImages": [],
        "createdAt": stamp,
        "updatedAt": stamp,
        "catalogPath": f"{category}/{subcategory or 'General'}/{str(payload.get('brand') or 'Sin marca').strip()}/{str(payload.get('model') or title).strip()}",
    }
    state, products = _state()
    products.append(product)
    save_state(state)
    _sync_variants(product_id, variants, price)
    product["stock"] = sum_variant_stock(product_id)
    product["status"] = "available" if product["stock"] > 0 else product["status"]
    state, products = _state()
    for index, item in enumerate(products):
        if str(item.get("id")) == product_id:
            products[index] = product
            break
    save_state(state)
    if isinstance(payload.get("attributes"), dict):
        save_product_attributes(product_id, payload["attributes"], "catalog-crud")
    _ensure_publication_table()
    sync_products()
    if bool(payload.get("publish")):
        update_publication(product_id, {"status": "published", "title": title, "description": product["description"]})
    return {"product": get_product(product_id), "classification": classification}


def get_product(product_id: str) -> dict[str, Any]:
    product = next((item for item in list_inventory() if str(item.get("id")) == str(product_id)), None)
    if not product:
        raise KeyError("Producto no encontrado.")
    return product


def update_product(product_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    migrate_sprint6()
    state, products = _state()
    product = next((item for item in products if str(item.get("id")) == str(product_id)), None)
    if not product:
        raise KeyError("Producto no encontrado.")
    category, subcategory, classification = _category(payload, product)
    for field in ("title", "brand", "model", "description", "type"):
        if field in payload:
            product[field] = str(payload.get(field) or "").strip()
    product["category"] = category
    product["subcategory"] = subcategory
    if "price" in payload or "salePrice" in payload:
        product["price"] = max(0.0, float(payload.get("price", payload.get("salePrice", 0)) or 0))
    if "purchasePrice" in payload:
        product["purchasePrice"] = max(0.0, float(payload.get("purchasePrice") or 0))
    if "sizes" in payload:
        product["sizes"] = _clean_list(payload.get("sizes"))
    if "colors" in payload:
        product["colors"] = _clean_list(payload.get("colors"))
    if "status" in payload:
        status = str(payload.get("status") or "draft")
        if status not in STATUS_VALUES:
            raise ValueError("Estado de producto inválido.")
        product["status"] = status
    product["updatedAt"] = _now()
    product["catalogPath"] = f"{category}/{subcategory or 'General'}/{product.get('brand') or 'Sin marca'}/{product.get('model') or product.get('title') or 'Producto'}"
    save_state(state)
    if isinstance(payload.get("variants"), list):
        _sync_variants(product_id, payload["variants"], float(product.get("price") or 0))
    product["stock"] = sum_variant_stock(product_id)
    if product["stock"] <= 0 and product.get("status") == "available":
        product["status"] = "sold_out"
    elif product["stock"] > 0 and product.get("status") == "sold_out":
        product["status"] = "available"
    save_state(state)
    if isinstance(payload.get("attributes"), dict):
        save_product_attributes(product_id, payload["attributes"], "catalog-crud")
    _ensure_publication_table()
    sync_products()
    if "publicationStatus" in payload:
        update_publication(product_id, {"status": str(payload.get("publicationStatus") or "draft")})
    return {"product": get_product(product_id), "classification": classification}


def delete_product(product_id: str, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        raise ValueError("La eliminación requiere confirmación explícita.")
    state, products = _state()
    before = len(products)
    state["products"] = [item for item in products if str(item.get("id")) != str(product_id)]
    if len(state["products"]) == before:
        raise KeyError("Producto no encontrado.")
    with _db() as connection:
        for table in ("product_variants", "inventory_movements", "product_image_hashes", "product_attributes"):
            try:
                connection.execute(f"DELETE FROM {table} WHERE product_id=?", (product_id,))
            except sqlite3.OperationalError:
                pass
        connection.execute("DELETE FROM product_publication WHERE product_id=?", (product_id,))
    save_state(state)
    return {"deleted": True, "productId": product_id}


def list_products(filters: dict[str, Any] | None = None) -> dict[str, Any]:
    filters = filters or {}
    products = list_inventory()
    q = str(filters.get("q") or "").strip().lower()
    category = str(filters.get("category") or "").strip().lower()
    brand = str(filters.get("brand") or "").strip().lower()
    status = str(filters.get("status") or "").strip().lower()
    size = str(filters.get("size") or "").strip().lower()
    color = str(filters.get("color") or "").strip().lower()
    result = []
    thumbnails: dict[str, str] = {}
    try:
        with _db() as connection:
            cursor = connection.execute(
                """SELECT a.product_id,a.is_cover,o.backend,o.public_url
                   FROM product_media_assets a
                   JOIN product_media_outputs o ON o.asset_id=a.id
                   WHERE a.status='ready' AND o.format='thumbnail'
                   ORDER BY a.is_cover DESC,
                            CASE WHEN o.backend='supabase' THEN 0 ELSE 1 END,
                            a.created_at"""
            )
            rows = cursor.fetchall() if hasattr(cursor, "fetchall") else cursor
        for row in rows:
            thumbnails.setdefault(
                str(row["product_id"]), _browser_image_url(str(row["public_url"] or ""))
            )
    except sqlite3.OperationalError:
        pass
    for product in products:
        haystack = " ".join(str(product.get(key) or "") for key in ("title", "brand", "model", "category", "subcategory")).lower()
        if q and q not in haystack:
            continue
        if category and str(product.get("category") or "").lower() != category:
            continue
        if brand and str(product.get("brand") or "").lower() != brand:
            continue
        if status and str(product.get("status") or "").lower() != status:
            continue
        if size and size not in [str(item).lower() for item in product.get("sizes", [])]:
            continue
        if color and color not in [str(item).lower() for item in product.get("colors", [])]:
            continue
        fallback_images: list[str] = []
        for field in ("catalogImage", "image", "imagePath", "approvedStudioImage"):
            value = product.get(field)
            if isinstance(value, str) and value.strip():
                fallback_images.append(_browser_image_url(value))
        for field in ("originalImages", "images", "approvedStudioImages"):
            values = product.get(field)
            if isinstance(values, list):
                for value in values:
                    candidate = (
                        value.get("publicUrl") or value.get("path")
                        if isinstance(value, dict)
                        else value
                    )
                    if isinstance(candidate, str) and candidate.strip():
                        fallback_images.append(_browser_image_url(candidate))
        encoded = str(product.get("imageBase64") or "").strip()
        if not encoded:
            gallery = product.get("galleryBase64")
            if isinstance(gallery, list) and gallery:
                encoded = str(gallery[0] or "").strip()
        if encoded:
            fallback_images.append(
                encoded if encoded.startswith("data:") else f"data:image/webp;base64,{encoded}"
            )
        fallback_images.sort(
            key=lambda value: 0
            if value.startswith(("https://", "http://"))
            else 1
            if value.startswith("data:")
            else 2
        )
        item = dict(product)
        # The catalog row only needs a small thumbnail. Keeping full embedded
        # galleries here made every list request several megabytes and delayed
        # rendering on phones. The detail endpoint still returns all fields.
        for field in LIST_ONLY_HEAVY_FIELDS:
            item.pop(field, None)
        item["thumbnailUrl"] = (
            thumbnails.get(str(product.get("id") or ""))
            or (fallback_images[0] if fallback_images else "")
        )
        result.append(item)
    result.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {"products": result, "count": len(result), "facets": facets(products)}


def facets(products: list[dict[str, Any]] | None = None) -> dict[str, list[str]]:
    products = products if products is not None else list_inventory()
    def values(field: str) -> list[str]:
        found: set[str] = set()
        for product in products:
            value = product.get(field)
            if isinstance(value, list):
                found.update(str(item).strip() for item in value if str(item).strip())
            elif str(value or "").strip():
                found.add(str(value).strip())
        return sorted(found, key=str.lower)
    return {
        "categories": sorted(set(UNIVERSAL_CATEGORIES) | set(values("category")), key=str.lower),
        "brands": values("brand"), "sizes": values("sizes"), "colors": values("colors"),
        "statuses": sorted(STATUS_VALUES),
    }


def duplicate_report() -> dict[str, Any]:
    migrate_sprint6()
    with _db() as connection:
        rows = [dict(row) for row in connection.execute("SELECT sha256,product_id,original_path,created_at FROM product_image_hashes ORDER BY created_at DESC").fetchall()]
    # Exact duplicates cannot coexist because sha256 is a primary key; report cross-product logical fingerprints too.
    groups: dict[str, list[dict[str, Any]]] = {}
    for product in list_inventory():
        fingerprint = "|".join([
            str(product.get("brand") or "").strip().lower(),
            str(product.get("model") or "").strip().lower(),
            str(product.get("category") or "").strip().lower(),
        ])
        if fingerprint.strip("|"):
            digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
            groups.setdefault(digest, []).append({"id": product.get("id"), "title": product.get("title"), "fingerprint": fingerprint})
    probable = [items for items in groups.values() if len(items) > 1]
    return {"imageHashes": rows, "imageHashCount": len(rows), "probableProductGroups": probable, "probableGroupCount": len(probable)}
