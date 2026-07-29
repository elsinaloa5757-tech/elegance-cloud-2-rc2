from __future__ import annotations

import json, re, shutil, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import quote

from services.state_store import database_path, load_state
from services.commercial_automation import upsert_customer, search_customers, create_order

LOCK = RLock()
PUBLIC_STATUSES = {'draft','published','hidden','sold_out'}


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(database_path(), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA synchronous=NORMAL')
    return c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:16]}'


def _digits(value: Any) -> str:
    return re.sub(r'\D', '', str(value or ''))


def _backup(reason: str) -> str:
    db = Path(database_path())
    folder = db.parent / 'catalog_backups'
    folder.mkdir(exist_ok=True)
    target = folder / f"elegance_catalog_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.sqlite3"
    if db.exists():
        shutil.copy2(db, target)
    return str(target)


def migrate_public_catalog() -> dict:
    backup_path = _backup('public_catalog_migration')
    with _db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS product_publication(
            product_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'draft',
            featured INTEGER NOT NULL DEFAULT 0,
            promotion_price REAL,
            hide_when_sold_out INTEGER NOT NULL DEFAULT 1,
            slug TEXT NOT NULL DEFAULT '',
            public_title TEXT NOT NULL DEFAULT '',
            public_description TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_publication_slug ON product_publication(slug) WHERE slug<>'';
        CREATE INDEX IF NOT EXISTS idx_publication_status ON product_publication(status);
        CREATE TABLE IF NOT EXISTS sales_requests(
            id TEXT PRIMARY KEY,
            folio TEXT UNIQUE NOT NULL,
            customer_id TEXT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '',
            whatsapp TEXT NOT NULL DEFAULT '',
            delivery_type TEXT NOT NULL DEFAULT 'personal',
            address TEXT NOT NULL DEFAULT '',
            references_text TEXT NOT NULL DEFAULT '',
            shipping_cost REAL NOT NULL DEFAULT 0,
            subtotal REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'catalog',
            campaign TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'new',
            idempotency_key TEXT UNIQUE,
            notes TEXT NOT NULL DEFAULT '',
            commercial_order_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sales_request_items(
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            title TEXT NOT NULL,
            size TEXT NOT NULL DEFAULT '',
            color TEXT NOT NULL DEFAULT '',
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            image_path TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(request_id) REFERENCES sales_requests(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS catalog_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            product_id TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'direct',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_requests_status ON sales_requests(status);
        CREATE INDEX IF NOT EXISTS idx_requests_created ON sales_requests(created_at);
        CREATE INDEX IF NOT EXISTS idx_events_type_created ON catalog_events(event_type,created_at);
        ''')
    sync_products()
    return {'status':'ok','version':'4.2.0-rc2','backup':backup_path,'database':database_path()}


def _slug(text: str) -> str:
    value = re.sub(r'[^a-z0-9]+', '-', str(text or '').lower()).strip('-')
    return value[:90] or f'producto-{uuid.uuid4().hex[:8]}'


def _products() -> list[dict]:
    state = load_state()
    products = state.get('products', []) if isinstance(state, dict) else []
    return [p for p in products if isinstance(p, dict)]


def _product(pid: str) -> dict | None:
    return next((p for p in _products() if str(p.get('id')) == str(pid)), None)


def _title(p: dict) -> str:
    return str(p.get('title') or p.get('name') or p.get('model') or p.get('id') or 'Producto Elegance')


def _public_image_url(value: str) -> str:
    value=str(value or '').strip().replace('\\','/')
    if not value: return ''
    if value.startswith(('http://','https://','data:','/')): return value
    if value.startswith('data/'): return '/media/'+value[5:]
    return '/media/'+value.lstrip('./')


def _images(p: dict) -> list[str]:
    """Return product images in a customer-friendly order.

    Originals are intentionally preferred over generated Studio derivatives because
    a failed crop/background render must never become the catalog cover. An explicit
    catalogImage remains the only field allowed to override the original cover.
    """
    found: list[str] = []
    for key in ('catalogImage','image','imagePath'):
        value = p.get(key)
        if isinstance(value, str) and value and value not in found:
            found.append(_public_image_url(value))
    for key in ('originalImages','images','editedImages','approvedStudioImages'):
        value = p.get(key)
        if isinstance(value, list):
            for item in value:
                path = item.get('path') if isinstance(item, dict) else item
                if isinstance(path, str) and path and path not in found:
                    found.append(_public_image_url(path))
    value = p.get('approvedStudioImage')
    if isinstance(value, str) and value and value not in found:
        found.append(_public_image_url(value))
    return found


def sync_products() -> dict:
    products = _products(); now = _now(); created = 0
    with _db() as c:
        for p in products:
            pid = str(p.get('id') or '').strip()
            if not pid: continue
            exists = c.execute('SELECT product_id FROM product_publication WHERE product_id=?',(pid,)).fetchone()
            if not exists:
                base = _slug(_title(p)); slug = base; n = 2
                while c.execute('SELECT 1 FROM product_publication WHERE slug=?',(slug,)).fetchone():
                    slug = f'{base}-{n}'; n += 1
                stock = int(p.get('stock') or 0)
                status = 'draft' if stock > 0 else 'sold_out'
                c.execute('INSERT INTO product_publication(product_id,status,featured,hide_when_sold_out,slug,public_title,public_description,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                          (pid,status,0,1,slug,_title(p),str(p.get('description') or p.get('commercialDescription') or ''),now))
                created += 1
    return {'status':'ok','products':len(products),'created':created}


def _publication_map() -> dict[str, dict]:
    with _db() as c:
        rows = c.execute('SELECT * FROM product_publication').fetchall()
    return {str(r['product_id']): dict(r) for r in rows}


def _sizes(p: dict) -> list[str]:
    raw = p.get('sizes') or p.get('size') or []
    if isinstance(raw, str): raw = re.split(r'[,/|;]+', raw)
    if not isinstance(raw, list): return []
    return [str(x.get('size') if isinstance(x,dict) else x).strip() for x in raw if str(x.get('size') if isinstance(x,dict) else x).strip()]


def _colors(p: dict) -> list[str]:
    raw = p.get('colors') or p.get('color') or p.get('primaryColor') or []
    if isinstance(raw, str): raw = re.split(r'[,/|;]+', raw)
    if not isinstance(raw, list): return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _public_product(p: dict, pub: dict) -> dict:
    stock = max(0, int(p.get('stock') or 0))
    price = float(p.get('price') or 0)
    promo = pub.get('promotion_price')
    effective = float(promo) if promo is not None else price
    status = str(pub.get('status') or 'draft')
    if stock <= 0: status = 'sold_out'
    return {
        'id': str(p.get('id')),
        'slug': pub.get('slug'),
        'title': pub.get('public_title') or _title(p),
        'description': pub.get('public_description') or str(p.get('description') or p.get('commercialDescription') or ''),
        'brand': str(p.get('brand') or ''), 'model': str(p.get('model') or ''),
        'category': str(p.get('category') or p.get('universalCategory') or 'Otros'),
        'subcategory': str(p.get('subcategory') or ''), 'gender': str(p.get('gender') or ''),
        'sizes': _sizes(p), 'colors': _colors(p), 'keywords': p.get('keywords') or p.get('tags') or [],
        'stock': stock, 'available': stock > 0, 'lowStock': 0 < stock <= 2,
        'price': price, 'promotionPrice': promo, 'effectivePrice': effective,
        'featured': bool(pub.get('featured')), 'status': status,
        'images': _images(p), 'shareUrl': f"/catalog/product/{pub.get('slug')}",
        'updatedAt': pub.get('updated_at')
    }


def list_public_products(filters: dict | None = None, admin: bool = False) -> list[dict]:
    filters = filters or {}; sync_products(); pubs = _publication_map(); out=[]
    q = str(filters.get('q') or '').lower().strip()
    for p in _products():
        pid = str(p.get('id') or ''); pub = pubs.get(pid)
        if not pub: continue
        item = _public_product(p,pub)
        if not admin:
            if item['status'] != 'published': continue
            if not item['available'] and bool(pub.get('hide_when_sold_out')): continue
        if filters.get('category') and item['category'].lower()!=str(filters['category']).lower(): continue
        if filters.get('subcategory') and item['subcategory'].lower()!=str(filters['subcategory']).lower(): continue
        if filters.get('brand') and item['brand'].lower()!=str(filters['brand']).lower(): continue
        if filters.get('size') and str(filters['size']).lower() not in [x.lower() for x in item['sizes']]: continue
        if filters.get('color') and str(filters['color']).lower() not in [x.lower() for x in item['colors']]: continue
        if filters.get('available') in (True,'true','1') and not item['available']: continue
        if filters.get('featured') in (True,'true','1') and not item['featured']: continue
        if filters.get('new') in (True,'true','1'):
            # New = among latest product records; fallback to publication update time.
            pass
        if q:
            hay = ' '.join(map(str,[item['title'],item['brand'],item['model'],item['category'],item['subcategory'],item['sizes'],item['colors'],item['keywords']])).lower()
            if q not in hay: continue
        out.append(item)
    out.sort(key=lambda x:(not x['featured'], x['title'].lower()))
    return out


def get_public_product(identifier: str, admin: bool = False) -> dict:
    sync_products(); pubs = _publication_map(); p = _product(identifier)
    if not p:
        pid = next((pid for pid,pub in pubs.items() if pub.get('slug')==identifier),None)
        p = _product(pid) if pid else None
    if not p: raise ValueError('Producto no encontrado.')
    item = _public_product(p,pubs[str(p.get('id'))])
    if not admin and item['status']!='published': raise ValueError('Producto no publicado.')
    return item


def update_publication(product_id: str, payload: dict) -> dict:
    if not _product(product_id): raise ValueError('Producto no encontrado.')
    status = str(payload.get('status') or '').lower()
    if status and status not in PUBLIC_STATUSES: raise ValueError('Estado de publicación inválido.')
    _backup('publication_update')
    sync_products(); fields=[]; args=[]
    mapping={'status':'status','featured':'featured','promotionPrice':'promotion_price','hideWhenSoldOut':'hide_when_sold_out','slug':'slug','title':'public_title','description':'public_description'}
    for key,col in mapping.items():
        if key in payload:
            value=payload[key]
            if key in {'featured','hideWhenSoldOut'}: value=1 if bool(value) else 0
            if key=='slug': value=_slug(value)
            fields.append(f'{col}=?'); args.append(value)
    if status=='published': fields.append('published_at=?'); args.append(_now())
    fields.append('updated_at=?'); args.append(_now()); args.append(product_id)
    with _db() as c:
        c.execute(f"UPDATE product_publication SET {','.join(fields)} WHERE product_id=?",args)
    return get_public_product(product_id,admin=True)


def bulk_publish(product_ids: list[str], status: str) -> dict:
    if status not in PUBLIC_STATUSES: raise ValueError('Estado de publicación inválido.')
    results=[]
    for pid in product_ids[:500]:
        try: results.append({'productId':pid,'product':update_publication(str(pid),{'status':status})})
        except Exception as exc: results.append({'productId':pid,'error':str(exc)})
    return {'status':'ok','updated':sum(1 for x in results if 'product' in x),'results':results}


def track_event(payload: dict) -> dict:
    event = str(payload.get('eventType') or '').strip()
    if event not in {'visit','product_view','cart_add','cart_open','request_created','share'}: raise ValueError('Evento inválido.')
    with _db() as c:
        c.execute('INSERT INTO catalog_events(event_type,product_id,session_id,source,metadata,created_at) VALUES(?,?,?,?,?,?)',
                  (event,str(payload.get('productId') or ''),str(payload.get('sessionId') or ''),str(payload.get('source') or 'direct'),json.dumps(payload.get('metadata') or {},ensure_ascii=False),_now()))
    return {'status':'ok'}


def _request_folio(c: sqlite3.Connection) -> str:
    day=datetime.now().strftime('%Y%m%d'); n=c.execute('SELECT COUNT(*) FROM sales_requests WHERE folio LIKE ?',(f'SOL-{day}-%',)).fetchone()[0]+1
    return f'SOL-{day}-{n:04d}'


def create_sales_request(payload: dict) -> dict:
    idem=str(payload.get('idempotencyKey') or '').strip() or None
    if idem:
        with _db() as c:
            prior=c.execute('SELECT id FROM sales_requests WHERE idempotency_key=?',(idem,)).fetchone()
        if prior: return get_sales_request(prior['id'])
    items=payload.get('items') or []
    if not isinstance(items,list) or not items: raise ValueError('La solicitud necesita productos.')
    name=str(payload.get('name') or '').strip(); phone=_digits(payload.get('phone')); wa=_digits(payload.get('whatsapp') or phone)
    if not name: raise ValueError('El nombre es obligatorio.')
    if not wa and not phone: raise ValueError('Se requiere teléfono o WhatsApp.')
    normalized=[]; subtotal=0.0
    for raw in items:
        product=get_public_product(str(raw.get('productId') or ''))
        qty=int(raw.get('quantity') or 0)
        if qty<=0: raise ValueError('Cantidad inválida.')
        if qty>product['stock']: raise ValueError(f"Existencia insuficiente para {product['title']}. Disponible: {product['stock']}.")
        size=str(raw.get('size') or '')
        if product['sizes'] and size and size not in product['sizes']: raise ValueError(f'Talla no disponible para {product["title"]}.')
        color=str(raw.get('color') or '')
        price=float(product['effectivePrice']); subtotal += price*qty
        normalized.append({'id':_id('sri'),'product_id':product['id'],'title':product['title'],'size':size,'color':color,'quantity':qty,'unit_price':price,'image_path':product['images'][0] if product['images'] else ''})
    shipping=max(0,float(payload.get('shippingCost') or 0)); total=subtotal+shipping
    # Detect or create customer without exposing duplicates to public UI.
    matches=search_customers(wa or phone,limit=5); customer=None
    for candidate in matches:
        if _digits(candidate.get('whatsapp') or candidate.get('phone')) in {wa,phone} - {''}: customer=candidate; break
    if customer is None:
        customer=upsert_customer({'name':name,'phone':phone,'whatsapp':wa,'address':payload.get('address',''),'references':payload.get('references',''),'notes':'Registrado automáticamente desde catálogo público.'})
    rid=_id('req'); now=_now()
    with LOCK, _db() as c:
        folio=_request_folio(c)
        c.execute('INSERT INTO sales_requests(id,folio,customer_id,customer_name,phone,whatsapp,delivery_type,address,references_text,shipping_cost,subtotal,total,source,campaign,status,idempotency_key,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (rid,folio,customer['id'],name,phone,wa,str(payload.get('deliveryType') or 'personal'),str(payload.get('address') or ''),str(payload.get('references') or ''),shipping,subtotal,total,str(payload.get('source') or 'catalog'),str(payload.get('campaign') or ''),'new',idem,str(payload.get('notes') or ''),now,now))
        for i in normalized:
            c.execute('INSERT INTO sales_request_items(id,request_id,product_id,title,size,color,quantity,unit_price,image_path) VALUES(?,?,?,?,?,?,?,?,?)',(i['id'],rid,i['product_id'],i['title'],i['size'],i['color'],i['quantity'],i['unit_price'],i['image_path']))
    track_event({'eventType':'request_created','sessionId':payload.get('sessionId',''),'source':payload.get('source','catalog'),'metadata':{'requestId':rid,'total':total}})
    return get_sales_request(rid)


def get_sales_request(identifier: str) -> dict:
    with _db() as c:
        row=c.execute('SELECT * FROM sales_requests WHERE id=? OR folio=?',(identifier,identifier)).fetchone()
        if not row: raise ValueError('Solicitud no encontrada.')
        items=[dict(x) for x in c.execute('SELECT * FROM sales_request_items WHERE request_id=?',(row['id'],)).fetchall()]
    result=dict(row); result['items']=items; result['whatsapp']=request_whatsapp(result['id']); return result


def list_requests(status: str='', source: str='', limit: int=100) -> list[dict]:
    sql='SELECT * FROM sales_requests WHERE 1=1'; args=[]
    if status: sql+=' AND status=?'; args.append(status)
    if source: sql+=' AND source=?'; args.append(source)
    sql+=' ORDER BY created_at DESC LIMIT ?'; args.append(max(1,min(limit,500)))
    with _db() as c: rows=c.execute(sql,args).fetchall()
    return [dict(x) for x in rows]


def request_whatsapp(identifier: str) -> dict:
    with _db() as c:
        row=c.execute('SELECT * FROM sales_requests WHERE id=? OR folio=?',(identifier,identifier)).fetchone()
        if not row: raise ValueError('Solicitud no encontrada.')
        items=c.execute('SELECT * FROM sales_request_items WHERE request_id=?',(row['id'],)).fetchall()
    lines=[f"Hola, soy {row['customer_name']}.",f"Quiero solicitar el pedido {row['folio']}:"]
    for i in items:
        detail=f"• {i['quantity']} x {i['title']}"
        if i['size']: detail+=f" | Talla {i['size']}"
        if i['color']: detail+=f" | Color {i['color']}"
        lines.append(detail)
    lines.append(f"Total estimado: ${row['total']:,.2f}")
    lines.append('Entrega personal' if row['delivery_type']=='personal' else f"Envío a: {row['address']} {row['references_text']}")
    lines.append('Quedo pendiente de la confirmación de existencia y compra por parte de Elegance.')
    text='\n'.join(lines); number=_digits(row['whatsapp'] or row['phone'])
    return {'phone':number,'message':text,'url':f'https://wa.me/?text={quote(text)}','images':[i['image_path'] for i in items if i['image_path']]}


def confirm_request(identifier: str) -> dict:
    request=get_sales_request(identifier)
    if request['commercial_order_id']:
        return {'status':'ok','request':request,'orderId':request['commercial_order_id'],'alreadyConfirmed':True}
    order=create_order({'customerId':request['customer_id'],'status':'pending','deliveryType':request['delivery_type'],'address':request['address'],'references':request['references_text'],'shippingCost':request['shipping_cost'],'notes':f"Creado desde solicitud pública {request['folio']}. Origen: {request['source']}",'idempotencyKey':f"public-request:{request['id']}",'items':[{'productId':i['product_id'],'size':i['size'],'color':i['color'],'quantity':i['quantity'],'unitPrice':i['unit_price'],'imagePath':i['image_path']} for i in request['items']]})
    with _db() as c:
        c.execute('UPDATE sales_requests SET status=?,commercial_order_id=?,updated_at=? WHERE id=?',('confirmed',order['id'],_now(),request['id']))
    return {'status':'ok','request':get_sales_request(request['id']),'order':order}


def reject_request(identifier: str) -> dict:
    request=get_sales_request(identifier)
    if request['commercial_order_id']: raise ValueError('No se puede rechazar una solicitud que ya creó un pedido.')
    with _db() as c: c.execute('UPDATE sales_requests SET status=?,updated_at=? WHERE id=?',('rejected',_now(),request['id']))
    return get_sales_request(request['id'])


def dashboard() -> dict:
    with _db() as c:
        events={r['event_type']:r['n'] for r in c.execute('SELECT event_type,COUNT(*) n FROM catalog_events GROUP BY event_type').fetchall()}
        requests={r['status']:r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM sales_requests GROUP BY status').fetchall()}
        top=[dict(r) for r in c.execute("SELECT product_id,COUNT(*) views FROM catalog_events WHERE event_type='product_view' GROUP BY product_id ORDER BY views DESC LIMIT 10").fetchall()]
    pubs=list_public_products(admin=True)
    return {'status':'ok','published':sum(1 for p in pubs if p['status']=='published'),'drafts':sum(1 for p in pubs if p['status']=='draft'),'hidden':sum(1 for p in pubs if p['status']=='hidden'),'soldOut':sum(1 for p in pubs if p['status']=='sold_out'),'events':events,'requests':requests,'topProducts':top}
