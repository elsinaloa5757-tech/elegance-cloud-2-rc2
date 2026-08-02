from __future__ import annotations
import json, sqlite3, uuid
from datetime import datetime, timezone, timedelta
from typing import Any
from services.state_store import database_path, load_state, save_state

def now(): return datetime.now(timezone.utc).isoformat()
def connect():
    c=sqlite3.connect(database_path(),timeout=60); c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); return c

def migrate_scalability_platform():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS scalability_jobs(
          id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',
          stage TEXT NOT NULL DEFAULT 'queued',total INTEGER NOT NULL DEFAULT 0,
          completed INTEGER NOT NULL DEFAULT 0,failed INTEGER NOT NULL DEFAULT 0,
          payload_json TEXT NOT NULL DEFAULT '{}',result_json TEXT NOT NULL DEFAULT '{}',
          error TEXT NOT NULL DEFAULT '',cancel_requested INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_scalability_jobs_status ON scalability_jobs(status,created_at DESC);
        CREATE TABLE IF NOT EXISTS visual_memory(
          id TEXT PRIMARY KEY,product_id TEXT NOT NULL,title TEXT NOT NULL DEFAULT '',
          brand TEXT NOT NULL DEFAULT '',model TEXT NOT NULL DEFAULT '',image_url TEXT NOT NULL DEFAULT '',
          exact_hash TEXT NOT NULL DEFAULT '',perceptual_hash TEXT NOT NULL DEFAULT '',
          feature_json TEXT NOT NULL DEFAULT '[]',confirmed INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_visual_memory_brand_model ON visual_memory(brand,model);
        CREATE TABLE IF NOT EXISTS product_trash(
          id TEXT PRIMARY KEY,product_id TEXT NOT NULL,snapshot_json TEXT NOT NULL,
          reason TEXT NOT NULL DEFAULT '',deleted_at TEXT NOT NULL,purge_after TEXT NOT NULL,
          restored_at TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS performance_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,operation TEXT NOT NULL,
          duration_ms REAL NOT NULL DEFAULT 0,success INTEGER NOT NULL DEFAULT 1,
          details_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL);
        """)
        c.execute("UPDATE scalability_jobs SET status='recoverable',stage='interrupted',updated_at=? WHERE status='running'",(now(),))
        c.commit()
    return {"status":"ok"}

def products():
    s=load_state(); return [p for p in (s.get("products",[]) if isinstance(s,dict) else []) if isinstance(p,dict)]

def paginate(page=1,page_size=30,q="",category="",brand="",status=""):
    q=q.casefold().strip(); category=category.casefold().strip(); brand=brand.casefold().strip(); status=status.casefold().strip()
    def ok(p):
        text=" ".join(str(p.get(k,"")) for k in ("title","name","brand","model","sku")).casefold()
        if q and q not in text:return False
        if category and str(p.get("category","")).casefold()!=category:return False
        if brand and str(p.get("brand","")).casefold()!=brand:return False
        st=str(p.get("status") or p.get("publicationStatus") or "draft").casefold()
        return not status or st==status
    rows=[p for p in products() if ok(p)]
    size=max(1,min(int(page_size),100)); page=max(1,int(page)); start=(page-1)*size
    all_rows=products()
    facets={
        "categories":sorted({str(p.get("category") or "").strip() for p in all_rows if str(p.get("category") or "").strip()}),
        "brands":sorted({str(p.get("brand") or "").strip() for p in all_rows if str(p.get("brand") or "").strip()}),
        "statuses":sorted({str(p.get("status") or p.get("publicationStatus") or "draft").strip() for p in all_rows}),
    }
    return {"status":"ok","items":rows[start:start+size],"page":page,"pageSize":size,
            "total":len(rows),"pages":max(1,(len(rows)+size-1)//size),
            "hasMore":start+size<len(rows),"facets":facets}

def create_job(kind,total,payload=None):
    migrate_scalability_platform(); jid=uuid.uuid4().hex; stamp=now()
    with connect() as c:
        c.execute("INSERT INTO scalability_jobs(id,kind,total,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                  (jid,kind,max(0,int(total)),json.dumps(payload or {},ensure_ascii=False),stamp,stamp)); c.commit()
    return get_job(jid)

def get_job(jid):
    with connect() as c:r=c.execute("SELECT * FROM scalability_jobs WHERE id=?",(jid,)).fetchone()
    if not r:raise KeyError(jid)
    d=dict(r); d["payload"]=json.loads(d.pop("payload_json") or "{}"); d["result"]=json.loads(d.pop("result_json") or "{}")
    d["progress"]=round(d["completed"]*100/d["total"],1) if d["total"] else 0
    return d

def list_jobs(limit=50):
    with connect() as c: ids=[r[0] for r in c.execute("SELECT id FROM scalability_jobs ORDER BY created_at DESC LIMIT ?",(min(max(int(limit),1),200),))]
    return [get_job(x) for x in ids]

def job_action(jid,action):
    with connect() as c:
        if action=="cancel": c.execute("UPDATE scalability_jobs SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,updated_at=? WHERE id=?",(now(),jid))
        elif action=="resume": c.execute("UPDATE scalability_jobs SET status='queued',stage='queued',cancel_requested=0,error='',updated_at=? WHERE id=?",(now(),jid))
        c.commit()
    return get_job(jid)

def remember(payload):
    pid=str(payload.get("productId") or "").strip()
    if not pid:raise ValueError("Falta productId")
    mid=str(payload.get("id") or uuid.uuid4().hex); stamp=now()
    with connect() as c:
        c.execute("""INSERT OR REPLACE INTO visual_memory
        (id,product_id,title,brand,model,image_url,exact_hash,perceptual_hash,feature_json,confirmed,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(mid,pid,str(payload.get("title") or ""),str(payload.get("brand") or ""),
        str(payload.get("model") or ""),str(payload.get("imageUrl") or ""),str(payload.get("exactHash") or ""),
        str(payload.get("perceptualHash") or ""),json.dumps(payload.get("feature") or []),1 if payload.get("confirmed",True) else 0,stamp,stamp)); c.commit()
    return {"status":"ok","memoryId":mid}

def memory():
    with connect() as c:
        total=c.execute("SELECT COUNT(*) FROM visual_memory").fetchone()[0]
        confirmed=c.execute("SELECT COUNT(*) FROM visual_memory WHERE confirmed=1").fetchone()[0]
    return {"status":"ok","total":total,"confirmed":confirmed}

def trash_product(pid,reason="",days=30):
    s=load_state(); rows=s.get("products",[]); i=next((i for i,p in enumerate(rows) if str(p.get("id"))==pid),-1)
    if i<0:raise KeyError(pid)
    product=rows.pop(i); tid=uuid.uuid4().hex; dt=datetime.now(timezone.utc)
    with connect() as c:
        c.execute("INSERT INTO product_trash(id,product_id,snapshot_json,reason,deleted_at,purge_after) VALUES(?,?,?,?,?,?)",
                  (tid,pid,json.dumps(product,ensure_ascii=False),reason,dt.isoformat(),(dt+timedelta(days=max(1,days))).isoformat())); c.commit()
    s["products"]=rows; save_state(s); return {"status":"trashed","trashId":tid}

def trash_list(limit=100):
    with connect() as c: rows=c.execute("SELECT * FROM product_trash WHERE restored_at='' ORDER BY deleted_at DESC LIMIT ?",(min(max(int(limit),1),500),)).fetchall()
    return [dict(r) for r in rows]

def restore(tid):
    with connect() as c:r=c.execute("SELECT * FROM product_trash WHERE id=? AND restored_at=''",(tid,)).fetchone()
    if not r:raise KeyError(tid)
    p=json.loads(r["snapshot_json"]); s=load_state(); rows=s.setdefault("products",[])
    if not any(str(x.get("id"))==str(p.get("id")) for x in rows if isinstance(x,dict)): rows.append(p); save_state(s)
    with connect() as c:c.execute("UPDATE product_trash SET restored_at=? WHERE id=?",(now(),tid)); c.commit()
    return {"status":"restored","productId":p.get("id")}

def diagnostics():
    migrate_scalability_platform(); rows=products(); missing=0; suspicious=0
    import re
    for p in rows:
        image=p.get("thumbnailUrl") or p.get("catalogUrl") or p.get("imageUrl") or p.get("image")
        if not image:missing+=1
        title=str(p.get("title") or p.get("name") or "").casefold().strip()
        if not title or title.startswith("producto por confirmar") or re.match(r"^(jordan|nike|adidas|puma|reebok)\s+\d+$",title):suspicious+=1
    with connect() as c: jobs={r["status"]:r["n"] for r in c.execute("SELECT status,COUNT(*) n FROM scalability_jobs GROUP BY status")}
    return {"status":"ok","products":{"total":len(rows),"missingImage":missing,"suspiciousName":suspicious},
            "jobs":jobs,"memory":memory(),"trash":len(trash_list(500)),"database":database_path()}
