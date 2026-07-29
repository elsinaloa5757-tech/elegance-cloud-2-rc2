from __future__ import annotations

import json, re, shutil, sqlite3, uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import quote

from services.state_store import database_path, load_state, save_state

LOCK=RLock()
VALID_STATUSES={'draft','pending','layaway','paid','prepared','shipped','delivered','cancelled'}
RESERVING={'pending','layaway','paid','prepared','shipped','delivered'}
TERMINAL={'delivered','cancelled'}
STATUS_ES={'draft':'borrador','pending':'pendiente','layaway':'apartado','paid':'pagado','prepared':'preparado','shipped':'enviado','delivered':'entregado','cancelled':'cancelado'}


def _db()->sqlite3.Connection:
    c=sqlite3.connect(database_path(),timeout=30)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA synchronous=NORMAL')
    return c

def migrate_commercial()->dict:
    with _db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS customers(id TEXT PRIMARY KEY,name TEXT NOT NULL,phone TEXT NOT NULL DEFAULT '',whatsapp TEXT NOT NULL DEFAULT '',email TEXT NOT NULL DEFAULT '',address TEXT NOT NULL DEFAULT '',references_text TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_whatsapp ON customers(whatsapp) WHERE whatsapp<>'';
        CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name);
        CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,folio TEXT UNIQUE NOT NULL,customer_id TEXT,status TEXT NOT NULL,total REAL NOT NULL DEFAULT 0,subtotal REAL NOT NULL DEFAULT 0,shipping_cost REAL NOT NULL DEFAULT 0,delivery_type TEXT NOT NULL DEFAULT 'personal',address TEXT NOT NULL DEFAULT '',references_text TEXT NOT NULL DEFAULT '',tracking_number TEXT NOT NULL DEFAULT '',payment_method TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',layaway_due TEXT NOT NULL DEFAULT '',stock_reserved INTEGER NOT NULL DEFAULT 0,idempotency_key TEXT UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,FOREIGN KEY(customer_id) REFERENCES customers(id));
        CREATE TABLE IF NOT EXISTS order_items(id TEXT PRIMARY KEY,order_id TEXT NOT NULL,product_id TEXT NOT NULL,title TEXT NOT NULL,size TEXT NOT NULL DEFAULT '',color TEXT NOT NULL DEFAULT '',quantity INTEGER NOT NULL,unit_price REAL NOT NULL,image_path TEXT NOT NULL DEFAULT '',FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY,order_id TEXT NOT NULL,amount REAL NOT NULL,method TEXT NOT NULL,reference TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS commercial_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,action TEXT NOT NULL,details TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS commercial_backups(id INTEGER PRIMARY KEY AUTOINCREMENT,reason TEXT NOT NULL,state_payload TEXT NOT NULL,db_copy TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status); CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id); CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at); CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);
        ''')
    backup_id=backup('commercial_migration')
    return {'status':'ok','version':'4.1.0-rc1','backupId':backup_id,'database':database_path()}

def _now()->str: return datetime.now(timezone.utc).isoformat()
def _id(prefix:str)->str: return prefix+'_'+uuid.uuid4().hex[:16]
def _digits(v:Any)->str: return re.sub(r'\D','',str(v or ''))
def _audit(c,etype,eid,action,details): c.execute('INSERT INTO commercial_audit(entity_type,entity_id,action,details,created_at) VALUES(?,?,?,?,?)',(etype,eid,action,json.dumps(details,ensure_ascii=False),_now()))

def backup(reason:str)->int:
    state=load_state(); db=Path(database_path()); folder=db.parent/'commercial_backups'; folder.mkdir(exist_ok=True)
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f'); copy_path=folder/f'elegance_{stamp}.sqlite3'
    if db.exists(): shutil.copy2(db,copy_path)
    with _db() as c:
        cur=c.execute('INSERT INTO commercial_backups(reason,state_payload,db_copy,created_at) VALUES(?,?,?,?)',(reason,json.dumps(state,ensure_ascii=False),str(copy_path),_now()))
        c.execute('DELETE FROM commercial_backups WHERE id NOT IN (SELECT id FROM commercial_backups ORDER BY id DESC LIMIT 30)')
        return int(cur.lastrowid)

def upsert_customer(payload:dict)->dict:
    name=str(payload.get('name','')).strip(); phone=_digits(payload.get('phone')); wa=_digits(payload.get('whatsapp') or phone)
    if not name: raise ValueError('El nombre del cliente es obligatorio.')
    cid=str(payload.get('id') or _id('cus')); now=_now()
    with _db() as c:
        existing=c.execute('SELECT id FROM customers WHERE id=?',(cid,)).fetchone()
        if wa:
            duplicate=c.execute('SELECT id FROM customers WHERE whatsapp=? AND id<>?',(wa,cid)).fetchone()
            if duplicate: raise ValueError('Ya existe un cliente con ese WhatsApp.')
        values=(name,phone,wa,str(payload.get('email','')).strip(),str(payload.get('address','')).strip(),str(payload.get('references','')).strip(),str(payload.get('notes','')).strip(),now)
        if existing:
            c.execute('UPDATE customers SET name=?,phone=?,whatsapp=?,email=?,address=?,references_text=?,notes=?,updated_at=? WHERE id=?',(*values,cid)); action='updated'
        else:
            c.execute('INSERT INTO customers(id,name,phone,whatsapp,email,address,references_text,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,*values[:-1],now,now)); action='created'
        _audit(c,'customer',cid,action,{'name':name})
    return get_customer(cid)

def get_customer(cid:str)->dict:
    with _db() as c: r=c.execute('SELECT * FROM customers WHERE id=?',(cid,)).fetchone()
    if not r: raise ValueError('Cliente no encontrado.')
    return dict(r)

def search_customers(q:str='',limit:int=50)->list[dict]:
    term=f"%{q.strip()}%"; digits=f"%{_digits(q)}%"
    with _db() as c:
        rows=c.execute('SELECT * FROM customers WHERE name LIKE ? OR phone LIKE ? OR whatsapp LIKE ? ORDER BY updated_at DESC LIMIT ?',(term,digits,digits,max(1,min(limit,200)))).fetchall()
    return [dict(x) for x in rows]

def _products()->tuple[dict,list[dict]]:
    state=load_state(); products=state.get('products',[]) if isinstance(state.get('products'),list) else []
    return state,[p for p in products if isinstance(p,dict)]

def _find_product(products,pid):
    return next((p for p in products if str(p.get('id'))==str(pid)),None)

def _folio(c)->str:
    day=datetime.now().strftime('%Y%m%d'); n=c.execute("SELECT COUNT(*) FROM orders WHERE folio LIKE ?",(f'EL-{day}-%',)).fetchone()[0]+1
    return f'EL-{day}-{n:04d}'

def create_order(payload:dict)->dict:
    items=payload.get('items') or []
    if not isinstance(items,list) or not items: raise ValueError('El pedido necesita al menos un producto.')
    status=str(payload.get('status','draft')).lower()
    if status not in VALID_STATUSES: raise ValueError('Estado de pedido inválido.')
    customer_id=str(payload.get('customerId') or '') or None
    if customer_id: get_customer(customer_id)
    state,products=_products(); normalized=[]; subtotal=0.0
    for raw in items:
        pid=str(raw.get('productId','')); p=_find_product(products,pid)
        if not p: raise ValueError(f'Producto inexistente: {pid}')
        qty=int(raw.get('quantity') or 0)
        if qty<=0: raise ValueError('La cantidad debe ser mayor que cero.')
        price=float(raw.get('unitPrice',p.get('price') or 0)); subtotal+=qty*price
        normalized.append({'id':_id('itm'),'product_id':pid,'title':str(p.get('title') or p.get('name') or pid),'size':str(raw.get('size') or ''),'color':str(raw.get('color') or p.get('color') or ''),'quantity':qty,'unit_price':price,'image_path':str(raw.get('imagePath') or p.get('approvedStudioImage') or '')})
    shipping=max(0,float(payload.get('shippingCost') or 0)); oid=_id('ord'); now=_now(); idem=str(payload.get('idempotencyKey') or '').strip() or None
    with LOCK:
        backup_id=backup('create_order')
        state,products=_products()
        if status in RESERVING:
            for item in normalized:
                p=_find_product(products,item['product_id']); available=int(p.get('stock') or 0)
                if available<item['quantity']: raise ValueError(f"Existencia insuficiente para {item['title']}: disponible {available}.")
            for item in normalized:
                p=_find_product(products,item['product_id']); p['stock']=int(p.get('stock') or 0)-item['quantity']
            save_state(state)
        with _db() as c:
            if idem:
                prior=c.execute('SELECT id FROM orders WHERE idempotency_key=?',(idem,)).fetchone()
                if prior: return get_order(prior['id'])
            folio=_folio(c); total=subtotal+shipping
            c.execute('INSERT INTO orders(id,folio,customer_id,status,total,subtotal,shipping_cost,delivery_type,address,references_text,tracking_number,payment_method,notes,layaway_due,stock_reserved,idempotency_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(oid,folio,customer_id,status,total,subtotal,shipping,str(payload.get('deliveryType','personal')),str(payload.get('address','')),str(payload.get('references','')),str(payload.get('trackingNumber','')),str(payload.get('paymentMethod','')),str(payload.get('notes','')),str(payload.get('layawayDue','')),1 if status in RESERVING else 0,idem,now,now))
            for i in normalized: c.execute('INSERT INTO order_items(id,order_id,product_id,title,size,color,quantity,unit_price,image_path) VALUES(?,?,?,?,?,?,?,?,?)',(i['id'],oid,i['product_id'],i['title'],i['size'],i['color'],i['quantity'],i['unit_price'],i['image_path']))
            _audit(c,'order',oid,'created',{'folio':folio,'status':status,'backupId':backup_id})
    return get_order(oid)

def get_order(oid:str)->dict:
    with _db() as c:
        o=c.execute('SELECT o.*,c.name customer_name,c.whatsapp customer_whatsapp,c.phone customer_phone FROM orders o LEFT JOIN customers c ON c.id=o.customer_id WHERE o.id=? OR o.folio=?',(oid,oid)).fetchone()
        if not o: raise ValueError('Pedido no encontrado.')
        items=[dict(x) for x in c.execute('SELECT * FROM order_items WHERE order_id=?',(o['id'],)).fetchall()]
        payments=[dict(x) for x in c.execute('SELECT * FROM payments WHERE order_id=? ORDER BY created_at',(o['id'],)).fetchall()]
    d=dict(o); d['items']=items; d['payments']=payments; d['paid']=round(sum(float(x['amount']) for x in payments),2); d['balance']=round(max(0,float(d['total'])-d['paid']),2); d['statusLabel']=STATUS_ES.get(d['status'],d['status']); return d

def update_status(oid:str,new_status:str)->dict:
    new_status=new_status.lower()
    if new_status not in VALID_STATUSES: raise ValueError('Estado inválido.')
    with LOCK:
        order=get_order(oid); old=order['status']
        if old==new_status: return order
        backup_id=backup('update_order_status')
        state,products=_products(); reserved=bool(order['stock_reserved'])
        if new_status in RESERVING and not reserved:
            for item in order['items']:
                p=_find_product(products,item['product_id']); available=int((p or {}).get('stock') or 0)
                if available<int(item['quantity']): raise ValueError(f"Existencia insuficiente para {item['title']}.")
            for item in order['items']:
                p=_find_product(products,item['product_id']); p['stock']=int(p.get('stock') or 0)-int(item['quantity'])
            reserved=True; save_state(state)
        elif new_status=='cancelled' and reserved and old!='delivered':
            for item in order['items']:
                p=_find_product(products,item['product_id'])
                if p: p['stock']=int(p.get('stock') or 0)+int(item['quantity'])
            reserved=False; save_state(state)
        with _db() as c:
            c.execute('UPDATE orders SET status=?,stock_reserved=?,updated_at=? WHERE id=?',(new_status,1 if reserved else 0,_now(),order['id']))
            _audit(c,'order',order['id'],'status_changed',{'from':old,'to':new_status,'backupId':backup_id})
    return get_order(order['id'])

def add_payment(oid:str,payload:dict)->dict:
    order=get_order(oid); amount=float(payload.get('amount') or 0)
    if amount<=0: raise ValueError('El pago debe ser mayor que cero.')
    if amount>order['balance']+0.01: raise ValueError('El pago supera el saldo pendiente.')
    with _db() as c:
        pid=_id('pay'); c.execute('INSERT INTO payments(id,order_id,amount,method,reference,notes,created_at) VALUES(?,?,?,?,?,?,?)',(pid,order['id'],amount,str(payload.get('method') or 'efectivo'),str(payload.get('reference') or ''),str(payload.get('notes') or ''),_now())); _audit(c,'order',order['id'],'payment_added',{'paymentId':pid,'amount':amount})
    updated=get_order(order['id'])
    if updated['balance']<=0 and updated['status'] in {'pending','layaway'}: updated=update_status(order['id'],'paid')
    return updated

def list_orders(filters:dict)->list[dict]:
    sql='SELECT o.*,c.name customer_name FROM orders o LEFT JOIN customers c ON c.id=o.customer_id WHERE 1=1'; args=[]
    for key,col in [('status','o.status'),('customerId','o.customer_id'),('deliveryType','o.delivery_type'),('paymentMethod','o.payment_method')]:
        if filters.get(key): sql+=f' AND {col}=?'; args.append(filters[key])
    if filters.get('dateFrom'): sql+=' AND o.created_at>=?'; args.append(filters['dateFrom'])
    if filters.get('dateTo'): sql+=' AND o.created_at<?'; args.append(filters['dateTo']+'T23:59:59')
    sql+=' ORDER BY o.created_at DESC LIMIT ?'; args.append(max(1,min(int(filters.get('limit') or 100),500)))
    with _db() as c: rows=c.execute(sql,args).fetchall()
    return [dict(x) for x in rows]

def dashboard()->dict:
    with _db() as c:
        rows=c.execute('SELECT status,COUNT(*) count,COALESCE(SUM(total),0) total FROM orders GROUP BY status').fetchall()
        paid=c.execute('SELECT COALESCE(SUM(amount),0) FROM payments').fetchone()[0]
        pending=c.execute("SELECT COUNT(*) FROM orders WHERE status IN ('pending','layaway','paid','prepared','shipped')").fetchone()[0]
        layaway=c.execute("SELECT COUNT(*) FROM orders WHERE status='layaway'").fetchone()[0]
        deliveries=c.execute("SELECT COUNT(*) FROM orders WHERE status IN ('prepared','shipped')").fetchone()[0]
    state,products=_products(); low=sum(1 for p in products if int(p.get('stock') or 0)<=2)
    return {'status':'ok','ordersByStatus':{r['status']:{'count':r['count'],'total':r['total']} for r in rows},'paymentsTotal':paid,'activeOrders':pending,'layaways':layaway,'pendingDeliveries':deliveries,'lowStockProducts':low}

def whatsapp(oid:str,kind:str='confirmation')->dict:
    o=get_order(oid); number=_digits(o.get('customer_whatsapp') or o.get('customer_phone'))
    lines=[f"Hola {o.get('customer_name') or ''},",f"Pedido {o['folio']} — {STATUS_ES.get(o['status'],o['status'])}"]
    lines += [f"• {i['quantity']} x {i['title']} {('Talla '+i['size']) if i['size'] else ''}" for i in o['items']]
    lines += [f"Total: ${o['total']:,.2f}",f"Pagado: ${o['paid']:,.2f}",f"Saldo: ${o['balance']:,.2f}"]
    if o['delivery_type']=='shipping': lines.append(f"Envío: {o['address']} {o['references_text']}")
    if o['tracking_number']: lines.append(f"Guía: {o['tracking_number']}")
    templates={'payment':'Te compartimos el saldo pendiente de tu pedido.','prepared':'Tu pedido ya está preparado.','shipping':'Tu pedido ha sido enviado.','delivery':'Tu pedido fue entregado. Gracias por elegir elegance.'}
    if kind in templates: lines.insert(1,templates[kind])
    text='\n'.join(x.strip() for x in lines if x.strip()); url=f'https://wa.me/{number}?text={quote(text)}' if number else f'https://wa.me/?text={quote(text)}'
    return {'status':'ok','phone':number,'message':text,'url':url,'images':[i['image_path'] for i in o['items'] if i['image_path']]}

def receipt(oid:str)->dict:
    o=get_order(oid)
    return {'status':'ok','receipt':{'folio':o['folio'],'date':o['created_at'],'customer':o.get('customer_name'),'items':o['items'],'subtotal':o['subtotal'],'shipping':o['shipping_cost'],'total':o['total'],'paid':o['paid'],'balance':o['balance'],'status':o['statusLabel'],'deliveryType':o['delivery_type'],'trackingNumber':o['tracking_number']}}

def audit(limit:int=100)->list[dict]:
    with _db() as c: rows=c.execute('SELECT * FROM commercial_audit ORDER BY id DESC LIMIT ?',(max(1,min(limit,500)),)).fetchall()
    return [dict(x) for x in rows]
