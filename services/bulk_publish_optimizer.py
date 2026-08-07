from __future__ import annotations
import sqlite3, threading
from datetime import datetime, timezone

from services.state_store import database_path, load_state
from services.public_catalog import sync_products, bulk_publish, list_public_products
from services.catalog_brain import auto_propose

LOCK=threading.RLock()
STOP=threading.Event()
THREAD=None

def _now(): return datetime.now(timezone.utc).isoformat()

def _db():
    c=sqlite3.connect(database_path(),timeout=60)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c

def migrate_bulk_publish_optimizer():
    with _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS bulk_opt_queue(
          product_id TEXT PRIMARY KEY,
          status TEXT NOT NULL DEFAULT 'queued',
          stage TEXT NOT NULL DEFAULT 'pending_ai',
          attempts INTEGER NOT NULL DEFAULT 0,
          confidence REAL NOT NULL DEFAULT 0,
          message TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_bulk_opt_queue_status ON bulk_opt_queue(status,updated_at);
        CREATE TABLE IF NOT EXISTS bulk_opt_settings(
          id INTEGER PRIMARY KEY CHECK(id=1),
          paused INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL
        );
        INSERT OR IGNORE INTO bulk_opt_settings(id,paused,updated_at) VALUES(1,0,'');
        """)
        c.execute("UPDATE bulk_opt_queue SET status='queued',stage='resume_after_restart',updated_at=? WHERE status='running'",(_now(),))
        c.commit()
    return status()

def _products():
    s=load_state()
    raw=s.get("products",[]) if isinstance(s,dict) else []
    return [p for p in raw if isinstance(p,dict) and str(p.get("id") or "").strip()]

def _paused():
    with _db() as c:r=c.execute("SELECT paused FROM bulk_opt_settings WHERE id=1").fetchone()
    return bool(r and r[0])

def set_paused(paused:bool):
    with _db() as c:
        c.execute("UPDATE bulk_opt_settings SET paused=?,updated_at=? WHERE id=1",(1 if paused else 0,_now()))
        c.commit()
    return status()

def enqueue_products(ids):
    now=_now();added=0
    with _db() as c:
        for pid in ids:
            pid=str(pid).strip()
            if not pid: continue
            row=c.execute("SELECT status FROM bulk_opt_queue WHERE product_id=?",(pid,)).fetchone()
            if row:
                if row["status"]!="optimized":
                    c.execute("UPDATE bulk_opt_queue SET status='queued',stage='pending_ai',updated_at=? WHERE product_id=?",(now,pid))
            else:
                c.execute("INSERT INTO bulk_opt_queue VALUES(?,'queued','pending_ai',0,0,'',?,?)",(pid,now,now))
                added+=1
        c.commit()
    return {"status":"ok","added":added,"queued":len(ids)}

def publish_all(queue_optimization:bool=True):
    migrate_bulk_publish_optimizer()
    sync_products()
    ids=[str(p.get("id")) for p in _products()]
    updated=0;errors=[]
    for i in range(0,len(ids),500):
        out=bulk_publish(ids[i:i+500],"published")
        updated+=int(out.get("updated") or 0)
        errors.extend([x for x in out.get("results",[]) if x.get("error")])
    if queue_optimization: enqueue_products(ids)
    return {"status":"ok","products":len(ids),"published":updated,"errors":errors[:100],
            "optimizationQueued":queue_optimization,**status()}

def queue_all():
    ids=[str(p.get("id")) for p in _products()]
    enqueue_products(ids)
    return {"status":"ok",**status()}

def _next():
    with _db() as c:
        r=c.execute("SELECT product_id FROM bulk_opt_queue WHERE status IN ('queued','retry') ORDER BY updated_at ASC LIMIT 1").fetchone()
        if not r:return None
        pid=r["product_id"]
        c.execute("UPDATE bulk_opt_queue SET status='running',stage='internal_ai',attempts=attempts+1,updated_at=? WHERE product_id=?",(_now(),pid))
        c.commit()
        return pid

def _process(pid):
    try:
        result=auto_propose(pid,minimum=.70)
        confidence=float(result.get("confidence") or 0)
        if result.get("applied"):
            st="optimized" if confidence>=.90 else "review"
            stage="proposal_ready"
            msg="Propuesta preparada para Auditoría Maestra."
        else:
            st="review";stage="needs_deep_research"
            msg=str(result.get("message") or "Requiere investigación profunda.")
        with _db() as c:
            c.execute("UPDATE bulk_opt_queue SET status=?,stage=?,confidence=?,message=?,updated_at=? WHERE product_id=?",
                      (st,stage,confidence,msg,_now(),pid));c.commit()
    except Exception as e:
        with _db() as c:
            c.execute("UPDATE bulk_opt_queue SET status='retry',stage='error',message=?,updated_at=? WHERE product_id=?",
                      (str(e)[:800],_now(),pid));c.commit()

def _loop():
    while not STOP.is_set():
        if _paused():
            STOP.wait(2);continue
        pid=_next()
        if not pid:
            STOP.wait(3);continue
        _process(pid)
        STOP.wait(.25)

def start_worker():
    global THREAD
    migrate_bulk_publish_optimizer()
    with LOCK:
        if THREAD and THREAD.is_alive():return
        STOP.clear()
        THREAD=threading.Thread(target=_loop,name="elegance-bulk-opt",daemon=True)
        THREAD.start()

def stop_worker():
    STOP.set()

def status():
    try:
        with _db() as c:
            total=c.execute("SELECT COUNT(*) FROM bulk_opt_queue").fetchone()[0]
            queued=c.execute("SELECT COUNT(*) FROM bulk_opt_queue WHERE status IN ('queued','retry')").fetchone()[0]
            running=c.execute("SELECT COUNT(*) FROM bulk_opt_queue WHERE status='running'").fetchone()[0]
            review=c.execute("SELECT COUNT(*) FROM bulk_opt_queue WHERE status='review'").fetchone()[0]
            optimized=c.execute("SELECT COUNT(*) FROM bulk_opt_queue WHERE status='optimized'").fetchone()[0]
            paused=bool(c.execute("SELECT paused FROM bulk_opt_settings WHERE id=1").fetchone()[0])
    except sqlite3.OperationalError:
        return {"status":"uninitialized","total":0,"queued":0,"running":0,"review":0,"optimized":0,"paused":False,"published":0,"drafts":0}
    try:
        admin=list_public_products(admin=True)
        published=sum(1 for x in admin if x.get("status")=="published")
        drafts=sum(1 for x in admin if x.get("status")=="draft")
    except Exception:
        published=drafts=0
    return {"status":"ok","total":total,"queued":queued,"running":running,"review":review,
            "optimized":optimized,"paused":paused,"published":published,"drafts":drafts}

def recent(limit=80):
    with _db() as c:
        rows=[dict(r) for r in c.execute("SELECT * FROM bulk_opt_queue ORDER BY updated_at DESC LIMIT ?",(max(1,min(limit,200)),)).fetchall()]
    return {"status":"ok","items":rows}
