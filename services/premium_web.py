from __future__ import annotations
import html, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'

def _read(name: str) -> str:
    return (WEB / name).read_text(encoding='utf-8')

def page(name: str, **values) -> str:
    text = _read(name)
    for key, value in values.items():
        text = text.replace('{{'+key+'}}', str(value))
    return text

def home_page() -> str:
    return page('home.html')

def catalog_page() -> str:
    return page('catalog.html')

def product_page(product: dict) -> str:
    title = html.escape(str(product.get('title') or 'Producto Elegance'))
    description = html.escape(str(product.get('description') or 'Descubre este producto en Elegance.')[:260])
    image = html.escape(str((product.get('images') or ['/assets/web/elegance-hero.png'])[0]))
    price = float(product.get('effectivePrice') or 0)
    payload = json.dumps(product, ensure_ascii=False).replace("</", "<\\/")
    return page('product.html', TITLE=title, DESCRIPTION=description, IMAGE=image,
                PRICE=f'${price:,.2f}', PRODUCT_JSON=payload)

def admin_page(user: dict) -> str:
    return page('admin.html', DISPLAY_NAME=html.escape(str(user.get('display_name','Usuario'))), ROLE=html.escape(str(user.get('role',''))))

def login_page(next_path: str='/admin') -> str:
    return page('login.html', NEXT=json.dumps(next_path))

def setup_page() -> str:
    return page('setup.html')

def error_page(code: int, message: str) -> str:
    return page('error.html', CODE=str(code), MESSAGE=html.escape(message))

def catalog_admin_page() -> str:
    return page('catalog-admin.html')

def system_check_page() -> str:
    return page('system-check.html')
