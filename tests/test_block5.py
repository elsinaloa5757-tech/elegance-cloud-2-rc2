from __future__ import annotations

import importlib


def _reload(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEGANCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ELEGANCE_SQLITE_PATH", str(tmp_path / "elegance.sqlite3"))
    import services.runtime_config as runtime_config
    import services.state_store as state_store
    import services.product_workflow as product_workflow
    import services.public_catalog as public_catalog
    import services.universal_products as universal_products
    import services.catalog_crud as catalog_crud
    importlib.reload(runtime_config)
    importlib.reload(state_store)
    importlib.reload(product_workflow)
    importlib.reload(public_catalog)
    importlib.reload(universal_products)
    return importlib.reload(catalog_crud)


def test_catalog_crud_and_filters(monkeypatch, tmp_path):
    crud = _reload(monkeypatch, tmp_path)
    created = crud.create_product({
        "title": "Nike Air Max Negro", "brand": "Nike", "model": "Air Max",
        "category": "Calzado", "price": 1899, "sizes": ["26"], "colors": ["Negro"],
        "variants": [{"size": "26", "color": "Negro", "stock": 2, "salePrice": 1899}],
    })
    product = created["product"]
    assert product["stock"] == 2
    listed = crud.list_products({"brand": "Nike", "category": "Calzado"})
    assert listed["count"] == 1
    updated = crud.update_product(product["id"], {"price": 1999, "description": "Edición actualizada"})
    assert updated["product"]["price"] == 1999
    assert updated["product"]["description"] == "Edición actualizada"


def test_catalog_delete_requires_confirmation(monkeypatch, tmp_path):
    crud = _reload(monkeypatch, tmp_path)
    product = crud.create_product({"title": "Bolso Elegance", "category": "Bolsos"})["product"]
    try:
        crud.delete_product(product["id"], False)
        assert False, "must require confirmation"
    except ValueError:
        pass
    result = crud.delete_product(product["id"], True)
    assert result["deleted"] is True
    assert crud.list_products()["count"] == 0


def test_duplicate_report(monkeypatch, tmp_path):
    crud = _reload(monkeypatch, tmp_path)
    crud.create_product({"title": "Modelo A", "brand": "Nike", "model": "Dunk", "category": "Calzado"})
    crud.create_product({"title": "Modelo A variante", "brand": "Nike", "model": "Dunk", "category": "Calzado"})
    report = crud.duplicate_report()
    assert report["probableGroupCount"] == 1
