from __future__ import annotations
import sqlite3, time
from datetime import datetime, timedelta, timezone
from typing import Any
from services.state_store import database_path
from services.security_platform import list_audit, list_users, list_backups, system_status
from services.sales_manager import statistics as sales_statistics
from services.commercial_automation import dashboard as commercial_dashboard


def _db():
    c=sqlite3.connect(database_path(),timeout=30); c.row_factory=sqlite3.Row; return c

def _one(sql:str,args=()):
    try:
        with _db() as c: return c.execute(sql,args).fetchone()
    except sqlite3.Error: return None

def _count(table:str)->int:
    r=_one(f'SELECT COUNT(*) n FROM {table}')
    return int(r['n']) if r else 0

def executive_dashboard(days:int=30)->dict[str,Any]:
    days=max(1,min(int(days),365)); sales=sales_statistics(days); commercial=commercial_dashboard()
    low=[]
    try:
        with _db() as c:
            low=[dict(x) for x in c.execute("SELECT id,title,brand,stock FROM products WHERE COALESCE(stock,0)<=3 ORDER BY stock ASC,title LIMIT 30").fetchall()]
    except sqlite3.Error: pass
    return {
      'status':'ok','version':'Cloud 1.4','generatedAt':datetime.now(timezone.utc).isoformat(),
      'metrics':{
        'products':_count('products'),'customers':_count('customers'),'orders':_count('orders'),
        'users':len(list_users()),'salesCount':sales.get('salesCount',0),'revenue':sales.get('revenue',0),
        'averageTicket':sales.get('averageTicket',0),'activeOrders':commercial.get('activeOrders',0),
        'layaways':commercial.get('layaways',0),'pendingDeliveries':commercial.get('pendingDeliveries',0),
        'lowStock':len(low),
      },
      'daily':sales.get('daily',[]),'topProducts':sales.get('topProducts',[])[:10],
      'topCustomers':sales.get('topCustomers',[])[:10],'lowStockProducts':low,
      'recentActivity':list_audit(20),'system':system_status(),
    }

def global_search(q:str,limit:int=40)->dict[str,Any]:
    q=(q or '').strip(); limit=max(1,min(int(limit),100))
    if not q:return {'status':'ok','query':'','results':[]}
    like=f'%{q}%'; out=[]
    with _db() as c:
        queries=[
          ('product',"SELECT id,title label,brand secondary,'/catalog-admin' href FROM products WHERE title LIKE ? OR brand LIKE ? OR model LIKE ? LIMIT ?",(like,like,like,limit)),
          ('customer',"SELECT id,name label,COALESCE(whatsapp,phone,'') secondary,'/commercial-cloud' href FROM customers WHERE name LIKE ? OR whatsapp LIKE ? OR phone LIKE ? LIMIT ?",(like,like,like,limit)),
          ('order',"SELECT id,folio label,status secondary,'/commercial-cloud' href FROM orders WHERE folio LIKE ? OR tracking_number LIKE ? LIMIT ?",(like,like,limit)),
        ]
        for kind,sql,args in queries:
            try:
                for r in c.execute(sql,args).fetchall(): out.append({'kind':kind,**dict(r)})
            except sqlite3.Error: pass
    return {'status':'ok','query':q,'count':len(out[:limit]),'results':out[:limit]}
