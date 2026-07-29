from __future__ import annotations

import csv, io, json, sqlite3, uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from services.state_store import database_path
from services.commercial_automation import get_order, update_status, dashboard as base_dashboard


def _db():
    c=sqlite3.connect(database_path(), timeout=30)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA foreign_keys=ON')
    return c

def _now(): return datetime.now(timezone.utc).isoformat()
def _id(prefix): return f"{prefix}_{uuid.uuid4().hex[:18]}"

def migrate_sales_manager()->dict:
    with _db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS shipments(
          id TEXT PRIMARY KEY, order_id TEXT NOT NULL, carrier TEXT NOT NULL DEFAULT '', service TEXT NOT NULL DEFAULT '',
          tracking_number TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', shipping_cost REAL NOT NULL DEFAULT 0,
          estimated_delivery TEXT NOT NULL DEFAULT '', shipped_at TEXT NOT NULL DEFAULT '', delivered_at TEXT NOT NULL DEFAULT '',
          address TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS idx_shipments_order ON shipments(order_id);
        CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipments(status);
        CREATE TABLE IF NOT EXISTS notifications(
          id TEXT PRIMARY KEY, customer_id TEXT, order_id TEXT, channel TEXT NOT NULL DEFAULT 'internal',
          template TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '', message TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
          scheduled_at TEXT NOT NULL, sent_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id), FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status,scheduled_at);
        CREATE TABLE IF NOT EXISTS inventory_movements(
          id TEXT PRIMARY KEY, product_id TEXT NOT NULL, order_id TEXT, movement_type TEXT NOT NULL,
          quantity INTEGER NOT NULL, stock_before INTEGER, stock_after INTEGER, reason TEXT NOT NULL DEFAULT '',
          metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_inventory_movements_product ON inventory_movements(product_id,created_at);
        CREATE TABLE IF NOT EXISTS sales_sync_queue(
          id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, operation TEXT NOT NULL,
          payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TEXT NOT NULL, last_error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_sales_sync_queue ON sales_sync_queue(status,next_attempt_at);
        CREATE TABLE IF NOT EXISTS order_status_history(
          id TEXT PRIMARY KEY, order_id TEXT NOT NULL, old_status TEXT NOT NULL DEFAULT '', new_status TEXT NOT NULL,
          note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE);
        ''')
    return {'status':'ok','version':'Cloud 1.3','database':database_path()}

def queue_sync(entity_type:str, entity_id:str, operation:str, payload:dict)->dict:
    now=_now(); qid=_id('sync')
    with _db() as c:
        c.execute('INSERT INTO sales_sync_queue(id,entity_type,entity_id,operation,payload,status,attempts,next_attempt_at,last_error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                  (qid,entity_type,entity_id,operation,json.dumps(payload,ensure_ascii=False),'pending',0,now,'',now,now))
    return {'id':qid,'status':'pending'}

def save_shipment(order_id:str,payload:dict)->dict:
    order=get_order(order_id); sid=str(payload.get('id') or _id('shp')); now=_now()
    status=str(payload.get('status') or 'pending')
    shipped_at=str(payload.get('shippedAt') or (now if status=='shipped' else ''))
    delivered_at=str(payload.get('deliveredAt') or (now if status=='delivered' else ''))
    values=(order['id'],str(payload.get('carrier','')),str(payload.get('service','')),str(payload.get('trackingNumber','')),status,float(payload.get('shippingCost') or 0),str(payload.get('estimatedDelivery','')),shipped_at,delivered_at,str(payload.get('address') or order.get('address') or ''),str(payload.get('notes','')),now)
    with _db() as c:
        existing=c.execute('SELECT id FROM shipments WHERE id=?',(sid,)).fetchone()
        if existing:
            c.execute('UPDATE shipments SET order_id=?,carrier=?,service=?,tracking_number=?,status=?,shipping_cost=?,estimated_delivery=?,shipped_at=?,delivered_at=?,address=?,notes=?,updated_at=? WHERE id=?',(*values,sid))
        else:
            c.execute('INSERT INTO shipments(id,order_id,carrier,service,tracking_number,status,shipping_cost,estimated_delivery,shipped_at,delivered_at,address,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,*values[:-1],now,now))
        c.execute('UPDATE orders SET tracking_number=?,shipping_cost=?,updated_at=? WHERE id=?',(values[3],values[5],now,order['id']))
    if status in {'shipped','delivered'} and order['status'] != status:
        try: update_status(order['id'],status)
        except Exception: pass
    queue_sync('shipment',sid,'upsert',{'shipmentId':sid,'orderId':order['id'],'status':status})
    return get_shipment(sid)

def get_shipment(sid:str)->dict:
    with _db() as c: r=c.execute('SELECT s.*,o.folio FROM shipments s JOIN orders o ON o.id=s.order_id WHERE s.id=?',(sid,)).fetchone()
    if not r: raise ValueError('Envío no encontrado.')
    return dict(r)

def list_shipments(status:str='',q:str='',limit:int=100)->list[dict]:
    sql='SELECT s.*,o.folio,c.name customer_name FROM shipments s JOIN orders o ON o.id=s.order_id LEFT JOIN customers c ON c.id=o.customer_id WHERE 1=1'; args=[]
    if status: sql+=' AND s.status=?'; args.append(status)
    if q:
        sql+=' AND (s.tracking_number LIKE ? OR s.carrier LIKE ? OR o.folio LIKE ? OR c.name LIKE ?)'; args += [f'%{q}%']*4
    sql+=' ORDER BY s.updated_at DESC LIMIT ?'; args.append(max(1,min(limit,500)))
    with _db() as c: rows=c.execute(sql,args).fetchall()
    return [dict(x) for x in rows]

def create_notification(payload:dict)->dict:
    nid=_id('ntf'); now=_now(); scheduled=str(payload.get('scheduledAt') or now)
    with _db() as c:
        c.execute('INSERT INTO notifications(id,customer_id,order_id,channel,template,subject,message,status,attempts,last_error,scheduled_at,sent_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (nid,payload.get('customerId'),payload.get('orderId'),str(payload.get('channel') or 'internal'),str(payload.get('template') or ''),str(payload.get('subject') or ''),str(payload.get('message') or ''),'pending',0,'',scheduled,'',now))
    queue_sync('notification',nid,'create',{'notificationId':nid,'channel':payload.get('channel','internal')})
    return get_notification(nid)

def get_notification(nid:str)->dict:
    with _db() as c:r=c.execute('SELECT * FROM notifications WHERE id=?',(nid,)).fetchone()
    if not r: raise ValueError('Notificación no encontrada.')
    return dict(r)

def process_notifications(limit:int=50)->dict:
    now=_now(); processed=[]
    with _db() as c:
        rows=c.execute("SELECT * FROM notifications WHERE status='pending' AND scheduled_at<=? ORDER BY created_at LIMIT ?",(now,limit)).fetchall()
        for r in rows:
            # Channels are prepared for external delivery; internal/whatsapp links are marked ready without pretending an external send.
            status='ready' if r['channel'] in {'whatsapp','email','sms'} else 'sent'
            c.execute('UPDATE notifications SET status=?,attempts=attempts+1,sent_at=?,last_error=? WHERE id=?',(status,now,'',r['id']))
            processed.append({'id':r['id'],'status':status})
    return {'status':'ok','processed':processed}

def list_notifications(status:str='',limit:int=100)->list[dict]:
    sql='SELECT n.*,c.name customer_name,o.folio FROM notifications n LEFT JOIN customers c ON c.id=n.customer_id LEFT JOIN orders o ON o.id=n.order_id WHERE 1=1'; args=[]
    if status: sql+=' AND n.status=?'; args.append(status)
    sql+=' ORDER BY n.created_at DESC LIMIT ?'; args.append(max(1,min(limit,500)))
    with _db() as c: rows=c.execute(sql,args).fetchall()
    return [dict(x) for x in rows]

def record_status_history(order_id:str,old_status:str,new_status:str,note:str=''):
    with _db() as c:c.execute('INSERT INTO order_status_history(id,order_id,old_status,new_status,note,created_at) VALUES(?,?,?,?,?,?)',(_id('hst'),order_id,old_status,new_status,note,_now()))
    queue_sync('order',order_id,'status',{'old':old_status,'new':new_status,'note':note})

def advanced_search(q:str='',status:str='',date_from:str='',date_to:str='',limit:int=100)->dict:
    like=f'%{q.strip()}%'; sql='''SELECT o.id,o.folio,o.status,o.total,o.created_at,c.name customer_name,c.whatsapp,
      GROUP_CONCAT(oi.title,' | ') products FROM orders o LEFT JOIN customers c ON c.id=o.customer_id
      LEFT JOIN order_items oi ON oi.order_id=o.id WHERE 1=1'''; args=[]
    if q: sql+=' AND (o.folio LIKE ? OR c.name LIKE ? OR c.whatsapp LIKE ? OR oi.title LIKE ? OR o.tracking_number LIKE ?)';args += [like]*5
    if status: sql+=' AND o.status=?';args.append(status)
    if date_from: sql+=' AND o.created_at>=?';args.append(date_from)
    if date_to: sql+=' AND o.created_at<=?';args.append(date_to+'T23:59:59')
    sql+=' GROUP BY o.id ORDER BY o.created_at DESC LIMIT ?';args.append(max(1,min(limit,500)))
    with _db() as c: rows=c.execute(sql,args).fetchall()
    return {'status':'ok','results':[dict(x) for x in rows]}

def statistics(days:int=30)->dict:
    since=(datetime.now(timezone.utc)-timedelta(days=max(1,days))).isoformat()
    with _db() as c:
        sales=c.execute("SELECT COUNT(*) n,COALESCE(SUM(total),0) total,COALESCE(AVG(total),0) avg FROM orders WHERE created_at>=? AND status<>'cancelled'",(since,)).fetchone()
        daily=[dict(x) for x in c.execute("SELECT substr(created_at,1,10) day,COUNT(*) orders_count,ROUND(SUM(total),2) revenue FROM orders WHERE created_at>=? AND status<>'cancelled' GROUP BY substr(created_at,1,10) ORDER BY day",(since,)).fetchall()]
        top=[dict(x) for x in c.execute("SELECT oi.product_id,oi.title,SUM(oi.quantity) units,ROUND(SUM(oi.quantity*oi.unit_price),2) revenue FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE o.created_at>=? AND o.status<>'cancelled' GROUP BY oi.product_id,oi.title ORDER BY revenue DESC LIMIT 20",(since,)).fetchall()]
        customers=[dict(x) for x in c.execute("SELECT c.id,c.name,COUNT(o.id) orders_count,ROUND(COALESCE(SUM(o.total),0),2) lifetime_value FROM customers c LEFT JOIN orders o ON o.customer_id=c.id AND o.status<>'cancelled' GROUP BY c.id ORDER BY lifetime_value DESC LIMIT 20").fetchall()]
    base=base_dashboard()
    return {'status':'ok','periodDays':days,'salesCount':sales['n'],'revenue':round(sales['total'],2),'averageTicket':round(sales['avg'],2),'daily':daily,'topProducts':top,'topCustomers':customers,'operations':base}

def report_csv(kind:str='sales',days:int=30)->str:
    data=statistics(days); out=io.StringIO(); w=csv.writer(out)
    if kind=='products':
        w.writerow(['product_id','producto','unidades','ingresos'])
        for x in data['topProducts']: w.writerow([x['product_id'],x['title'],x['units'],x['revenue']])
    elif kind=='customers':
        w.writerow(['customer_id','cliente','pedidos','valor_total'])
        for x in data['topCustomers']: w.writerow([x['id'],x['name'],x['orders_count'],x['lifetime_value']])
    else:
        w.writerow(['dia','pedidos','ingresos'])
        for x in data['daily']: w.writerow([x['day'],x['orders_count'],x['revenue']])
    return out.getvalue()

def sync_queue(status:str='',limit:int=100)->list[dict]:
    sql='SELECT * FROM sales_sync_queue WHERE 1=1';args=[]
    if status: sql+=' AND status=?';args.append(status)
    sql+=' ORDER BY created_at DESC LIMIT ?';args.append(max(1,min(limit,500)))
    with _db() as c: rows=c.execute(sql,args).fetchall()
    return [dict(x) for x in rows]
