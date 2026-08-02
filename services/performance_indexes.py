from __future__ import annotations
import sqlite3
from services.state_store import database_path

def migrate_performance_indexes() -> dict:
    c = sqlite3.connect(database_path(), timeout=60)
    try:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        statements = []
        if "recognition_reviews" in tables:
            statements += [
                "CREATE INDEX IF NOT EXISTS idx_reviews_status_created ON recognition_reviews(status, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_reviews_product ON recognition_reviews(product_id)",
            ]
        if "product_variants" in tables:
            statements += [
                "CREATE INDEX IF NOT EXISTS idx_variants_product ON product_variants(product_id)",
                "CREATE INDEX IF NOT EXISTS idx_variants_stock ON product_variants(stock)",
            ]
        if "product_publication" in tables:
            statements.append("CREATE INDEX IF NOT EXISTS idx_publication_status_updated ON product_publication(status, updated_at DESC)")
        for sql in statements:
            c.execute(sql)
        c.commit()
        return {"status":"ok","indexes":len(statements)}
    finally:
        c.close()
