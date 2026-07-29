from __future__ import annotations

import json, sqlite3, uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from services.state_store import database_path, load_state


def _db():
    c=sqlite3.connect(database_path(),timeout=30); c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA foreign_keys=ON')
    return c

def _now(): return datetime.now(timezone.utc).isoformat()
def _id(p): return f'{p}_{uuid.uuid4().hex[:18]}'
def _json(v): return json.dumps(v,ensure_ascii=False,separators=(',',':'))

def migrate_brain()->dict:
    with _db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS suppliers(
          id TEXT PRIMARY KEY,name TEXT NOT NULL,contact_name TEXT NOT NULL DEFAULT '',phone TEXT NOT NULL DEFAULT '',
          whatsapp TEXT NOT NULL DEFAULT '',email TEXT NOT NULL DEFAULT '',address TEXT NOT NULL DEFAULT '',tax_id TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name);
        CREATE TABLE IF NOT EXISTS purchase_orders(
          id TEXT PRIMARY KEY,folio TEXT UNIQUE NOT NULL,supplier_id TEXT,status TEXT NOT NULL DEFAULT 'draft',subtotal REAL NOT NULL DEFAULT 0,
          shipping_cost REAL NOT NULL DEFAULT 0,total REAL NOT NULL DEFAULT 0,expected_at TEXT NOT NULL DEFAULT '',received_at TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,FOREIGN KEY(supplier_id) REFERENCES suppliers(id));
        CREATE TABLE IF NOT EXISTS purchase_items(
          id TEXT PRIMARY KEY,purchase_id TEXT NOT NULL,product_id TEXT NOT NULL DEFAULT '',description TEXT NOT NULL,quantity INTEGER NOT NULL,
          unit_cost REAL NOT NULL DEFAULT 0,received_quantity INTEGER NOT NULL DEFAULT 0,FOREIGN KEY(purchase_id) REFERENCES purchase_orders(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS cash_accounts(
          id TEXT PRIMARY KEY,name TEXT NOT NULL,currency TEXT NOT NULL DEFAULT 'MXN',opening_balance REAL NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cash_movements(
          id TEXT PRIMARY KEY,account_id TEXT NOT NULL,movement_type TEXT NOT NULL,category TEXT NOT NULL,amount REAL NOT NULL,
          reference_type TEXT NOT NULL DEFAULT '',reference_id TEXT NOT NULL DEFAULT '',description TEXT NOT NULL DEFAULT '',metadata TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,FOREIGN KEY(account_id) REFERENCES cash_accounts(id));
        CREATE INDEX IF NOT EXISTS idx_cash_movements_date ON cash_movements(created_at);
        CREATE TABLE IF NOT EXISTS whatsapp_conversations(
          id TEXT PRIMARY KEY,customer_id TEXT,phone TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',assigned_to TEXT NOT NULL DEFAULT '',
          consent_status TEXT NOT NULL DEFAULT 'unknown',last_message_at TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_phone_open ON whatsapp_conversations(phone) WHERE status='open';
        CREATE TABLE IF NOT EXISTS whatsapp_messages(
          id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,direction TEXT NOT NULL,message_type TEXT NOT NULL DEFAULT 'text',body TEXT NOT NULL DEFAULT '',
          media_ref TEXT NOT NULL DEFAULT '',provider_message_id TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'queued',metadata TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,FOREIGN KEY(conversation_id) REFERENCES whatsapp_conversations(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS automation_rules(
          id TEXT PRIMARY KEY,name TEXT NOT NULL,event_name TEXT NOT NULL,conditions TEXT NOT NULL DEFAULT '{}',actions TEXT NOT NULL DEFAULT '[]',
          enabled INTEGER NOT NULL DEFAULT 1,priority INTEGER NOT NULL DEFAULT 100,last_run_at TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS automation_runs(
          id TEXT PRIMARY KEY,rule_id TEXT,event_name TEXT NOT NULL,entity_type TEXT NOT NULL DEFAULT '',entity_id TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL,details TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,FOREIGN KEY(rule_id) REFERENCES automation_rules(id));
        CREATE TABLE IF NOT EXISTS brain_audit(
          id TEXT PRIMARY KEY,module TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,action TEXT NOT NULL,
          actor TEXT NOT NULL DEFAULT 'system',before_data TEXT NOT NULL DEFAULT '{}',after_data TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS brain_sync_outbox(
          id TEXT PRIMARY KEY,aggregate_type TEXT NOT NULL,aggregate_id TEXT NOT NULL,event_type TEXT NOT NULL,payload TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,next_attempt_at TEXT NOT NULL,last_error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_brain_sync_outbox ON brain_sync_outbox(status,next_attempt_at);
        ''')
        if not c.execute('SELECT 1 FROM cash_accounts LIMIT 1').fetchone():
            c.execute('INSERT INTO cash_accounts(id,name,currency,opening_balance,active,created_at) VALUES(?,?,?,?,?,?)',('cash_main','Caja principal','MXN',0,1,_now()))
    return {'status':'ok','version':'Cloud 2.0','database':database_path(),'modules':['commerce','communications','ai','finance','supply','automation','analytics','security','cloud-sync']}

def _audit(c,module,etype,eid,action,before=None,after=None,actor='system'):
    c.execute('INSERT INTO brain_audit VALUES(?,?,?,?,?,?,?,?,?)',(_id('aud'),module,etype,eid,action,actor,_json(before or {}),_json(after or {}),_now()))

def _outbox(c,atype,aid,event,payload):
    now=_now(); c.execute('INSERT INTO brain_sync_outbox VALUES(?,?,?,?,?,?,?,?,?,?,?)',(_id('evt'),atype,aid,event,_json(payload),'pending',0,now,'',now,now))

def upsert_supplier(payload:dict)->dict:
    sid=str(payload.get('id') or _id('sup')); name=str(payload.get('name') or '').strip()
    if not name: raise ValueError('El nombre del proveedor es obligatorio.')
    now=_now()
    with _db() as c:
        old=c.execute('SELECT * FROM suppliers WHERE id=?',(sid,)).fetchone()
        vals=(name,str(payload.get('contactName','')),str(payload.get('phone','')),str(payload.get('whatsapp','')),str(payload.get('email','')),str(payload.get('address','')),str(payload.get('taxId','')),str(payload.get('notes','')),1 if payload.get('active',True) else 0,now)
        if old: c.execute('UPDATE suppliers SET name=?,contact_name=?,phone=?,whatsapp=?,email=?,address=?,tax_id=?,notes=?,active=?,updated_at=? WHERE id=?',(*vals,sid))
        else: c.execute('INSERT INTO suppliers VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(sid,*vals[:-1],now,now))
        row=dict(c.execute('SELECT * FROM suppliers WHERE id=?',(sid,)).fetchone()); _audit(c,'supply','supplier',sid,'upsert',dict(old) if old else {},row); _outbox(c,'supplier',sid,'supplier.upserted',row)
    return row

def list_suppliers(q:str='',limit:int=100):
    with _db() as c: rows=c.execute('SELECT * FROM suppliers WHERE name LIKE ? OR contact_name LIKE ? ORDER BY updated_at DESC LIMIT ?',(f'%{q}%',f'%{q}%',max(1,min(limit,500)))).fetchall()
    return [dict(x) for x in rows]

def create_purchase(payload:dict)->dict:
    items=payload.get('items') or []
    if not items: raise ValueError('La compra necesita partidas.')
    pid=_id('pur'); now=_now()
    with _db() as c:
        n=c.execute("SELECT COUNT(*) FROM purchase_orders WHERE folio LIKE ?",(f"CP-{datetime.now().strftime('%Y%m%d')}-%",)).fetchone()[0]+1
        folio=f"CP-{datetime.now().strftime('%Y%m%d')}-{n:04d}"; subtotal=sum(int(i.get('quantity',0))*float(i.get('unitCost',0)) for i in items); ship=float(payload.get('shippingCost') or 0)
        c.execute('INSERT INTO purchase_orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(pid,folio,payload.get('supplierId'),str(payload.get('status') or 'draft'),subtotal,ship,subtotal+ship,str(payload.get('expectedAt') or ''),'',str(payload.get('notes') or ''),now,now))
        for i in items: c.execute('INSERT INTO purchase_items VALUES(?,?,?,?,?,?,?)',(_id('pit'),pid,str(i.get('productId') or ''),str(i.get('description') or i.get('productId') or 'Producto'),int(i.get('quantity') or 0),float(i.get('unitCost') or 0),0))
        result=get_purchase(pid,c); _audit(c,'supply','purchase',pid,'created',{},result); _outbox(c,'purchase',pid,'purchase.created',result)
    return result

def get_purchase(pid:str,c=None):
    own=c is None; c=c or _db()
    try:
        r=c.execute('SELECT p.*,s.name supplier_name FROM purchase_orders p LEFT JOIN suppliers s ON s.id=p.supplier_id WHERE p.id=? OR p.folio=?',(pid,pid)).fetchone()
        if not r: raise ValueError('Compra no encontrada.')
        d=dict(r); d['items']=[dict(x) for x in c.execute('SELECT * FROM purchase_items WHERE purchase_id=?',(d['id'],)).fetchall()]; return d
    finally:
        if own: c.close()

def add_cash_movement(payload:dict)->dict:
    mid=_id('mov'); amount=float(payload.get('amount') or 0); typ=str(payload.get('type') or '')
    if amount<=0 or typ not in {'income','expense','transfer_in','transfer_out'}: raise ValueError('Movimiento de caja inválido.')
    row={'id':mid,'account_id':str(payload.get('accountId') or 'cash_main'),'movement_type':typ,'category':str(payload.get('category') or 'general'),'amount':amount,'reference_type':str(payload.get('referenceType') or ''),'reference_id':str(payload.get('referenceId') or ''),'description':str(payload.get('description') or ''),'metadata':_json(payload.get('metadata') or {}),'created_at':_now()}
    with _db() as c:
        c.execute('INSERT INTO cash_movements VALUES(:id,:account_id,:movement_type,:category,:amount,:reference_type,:reference_id,:description,:metadata,:created_at)',row); _audit(c,'finance','cash_movement',mid,'created',{},row); _outbox(c,'cash_movement',mid,'cash.movement.created',row)
    return row

def finance_summary(days:int=30)->dict:
    since=(datetime.now(timezone.utc)-timedelta(days=max(1,days))).isoformat()
    with _db() as c:
        x=c.execute("SELECT COALESCE(SUM(CASE WHEN movement_type IN ('income','transfer_in') THEN amount ELSE 0 END),0) income,COALESCE(SUM(CASE WHEN movement_type IN ('expense','transfer_out') THEN amount ELSE 0 END),0) expense FROM cash_movements WHERE created_at>=?",(since,)).fetchone()
        sales=c.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE created_at>=?",(since,)).fetchone()[0]
        purchases=c.execute("SELECT COALESCE(SUM(total),0) FROM purchase_orders WHERE created_at>=? AND status<>'cancelled'",(since,)).fetchone()[0]
    income=float(x['income'])+float(sales); expense=float(x['expense'])+float(purchases)
    return {'status':'ok','days':days,'income':round(income,2),'expense':round(expense,2),'profit':round(income-expense,2),'salesPayments':round(float(sales),2),'purchases':round(float(purchases),2)}

def open_conversation(payload:dict)->dict:
    phone=''.join(ch for ch in str(payload.get('phone') or '') if ch.isdigit())
    if not phone: raise ValueError('Teléfono requerido.')
    now=_now()
    with _db() as c:
        old=c.execute("SELECT * FROM whatsapp_conversations WHERE phone=? AND status='open'",(phone,)).fetchone()
        if old: return dict(old)
        cid=_id('wac'); c.execute('INSERT INTO whatsapp_conversations VALUES(?,?,?,?,?,?,?,?,?)',(cid,payload.get('customerId'),phone,'open',str(payload.get('assignedTo') or ''),str(payload.get('consentStatus') or 'unknown'),now,now,now)); row=dict(c.execute('SELECT * FROM whatsapp_conversations WHERE id=?',(cid,)).fetchone()); _audit(c,'communications','conversation',cid,'opened',{},row)
    return row

def queue_message(conversation_id:str,payload:dict)->dict:
    mid=_id('wam'); now=_now(); direction=str(payload.get('direction') or 'outbound')
    with _db() as c:
        if not c.execute('SELECT 1 FROM whatsapp_conversations WHERE id=?',(conversation_id,)).fetchone(): raise ValueError('Conversación no encontrada.')
        c.execute('INSERT INTO whatsapp_messages VALUES(?,?,?,?,?,?,?,?,?,?)',(mid,conversation_id,direction,str(payload.get('messageType') or 'text'),str(payload.get('body') or ''),str(payload.get('mediaRef') or ''),str(payload.get('providerMessageId') or ''),'queued' if direction=='outbound' else 'received',_json(payload.get('metadata') or {}),now)); c.execute('UPDATE whatsapp_conversations SET last_message_at=?,updated_at=? WHERE id=?',(now,now,conversation_id)); row=dict(c.execute('SELECT * FROM whatsapp_messages WHERE id=?',(mid,)).fetchone()); _audit(c,'communications','message',mid,'queued',{},row); _outbox(c,'whatsapp_message',mid,'whatsapp.message.queued',row)
    return row

def upsert_rule(payload:dict)->dict:
    rid=str(payload.get('id') or _id('rul')); name=str(payload.get('name') or '').strip(); event=str(payload.get('eventName') or '').strip()
    if not name or not event: raise ValueError('Nombre y evento son obligatorios.')
    now=_now()
    with _db() as c:
        old=c.execute('SELECT * FROM automation_rules WHERE id=?',(rid,)).fetchone(); vals=(name,event,_json(payload.get('conditions') or {}),_json(payload.get('actions') or []),1 if payload.get('enabled',True) else 0,int(payload.get('priority') or 100),now)
        if old: c.execute('UPDATE automation_rules SET name=?,event_name=?,conditions=?,actions=?,enabled=?,priority=?,updated_at=? WHERE id=?',(*vals,rid))
        else: c.execute('INSERT INTO automation_rules VALUES(?,?,?,?,?,?,?,?,?,?)',(rid,*vals[:-1],'',now,now))
        row=dict(c.execute('SELECT * FROM automation_rules WHERE id=?',(rid,)).fetchone()); _audit(c,'automation','rule',rid,'upsert',dict(old) if old else {},row)
    return row

def run_event(event_name:str,payload:dict)->dict:
    executed=[]
    with _db() as c:
        rules=c.execute('SELECT * FROM automation_rules WHERE enabled=1 AND event_name=? ORDER BY priority,id',(event_name,)).fetchall()
        for r in rules:
            actions=json.loads(r['actions'] or '[]'); run_id=_id('run'); details={'payload':payload,'actions':actions}
            c.execute('INSERT INTO automation_runs VALUES(?,?,?,?,?,?,?,?)',(run_id,r['id'],event_name,str(payload.get('entityType') or ''),str(payload.get('entityId') or ''),'completed',_json(details),_now())); c.execute('UPDATE automation_rules SET last_run_at=? WHERE id=?',(_now(),r['id'])); executed.append({'ruleId':r['id'],'runId':run_id,'actions':actions})
    return {'status':'ok','event':event_name,'executed':executed}

def predictive_analytics(days:int=90)->dict:
    since=(datetime.now(timezone.utc)-timedelta(days=max(7,days))).isoformat(); state=load_state(); products=state.get('products',[]) if isinstance(state.get('products'),list) else []
    with _db() as c:
        rows=c.execute("SELECT oi.product_id,oi.title,SUM(oi.quantity) units,COUNT(DISTINCT o.id) orders_count FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE o.created_at>=? AND o.status<>'cancelled' GROUP BY oi.product_id,oi.title",(since,)).fetchall()
    sold={str(r['product_id']):dict(r) for r in rows}; recommendations=[]
    for p in products:
        pid=str(p.get('id') or ''); stock=int(p.get('stock') or 0); units=int(sold.get(pid,{}).get('units') or 0); daily=units/max(1,days); cover=999 if daily<=0 else stock/daily; reorder=max(0,round(daily*30-stock))
        if stock<=2 or cover<21: recommendations.append({'productId':pid,'title':p.get('title') or p.get('name') or pid,'stock':stock,'unitsSold':units,'daysOfCover':round(cover,1) if cover<999 else None,'recommendedPurchase':reorder,'priority':'high' if stock<=1 or cover<7 else 'medium'})
    recommendations.sort(key=lambda x:(0 if x['priority']=='high' else 1,x['daysOfCover'] if x['daysOfCover'] is not None else 999))
    return {'status':'ok','periodDays':days,'recommendations':recommendations[:100],'productsAnalyzed':len(products)}

def brain_dashboard(days:int=30)->dict:
    with _db() as c:
        counts={name:c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for name,table in [('suppliers','suppliers'),('purchases','purchase_orders'),('conversations','whatsapp_conversations'),('rules','automation_rules'),('pendingSync','brain_sync_outbox')]}
        audit=[dict(x) for x in c.execute('SELECT * FROM brain_audit ORDER BY created_at DESC LIMIT 20').fetchall()]
    return {'status':'ok','version':'Cloud 2.0','modules':counts,'finance':finance_summary(days),'analytics':predictive_analytics(max(days,30)),'recentAudit':audit}

def integrity_report()->dict:
    with _db() as c:
        fk=[dict(x) for x in c.execute('PRAGMA foreign_key_check').fetchall()]; quick=c.execute('PRAGMA quick_check').fetchone()[0]
        pending=c.execute("SELECT COUNT(*) FROM brain_sync_outbox WHERE status='pending'").fetchone()[0]
    return {'status':'ok' if quick=='ok' and not fk else 'warning','databaseQuickCheck':quick,'foreignKeyErrors':fk,'pendingOutbox':pending,'checkedAt':_now()}
