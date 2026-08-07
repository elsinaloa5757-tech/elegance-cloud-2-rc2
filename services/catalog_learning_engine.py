from __future__ import annotations
import json, re, sqlite3, threading, time, urllib.request, uuid
from datetime import datetime, timezone
from pathlib import Path

from services.state_store import database_path, load_state, save_state
from services.public_catalog import sync_products, update_publication
from services.shoe_phase4 import extract_phase4, _compare

SUSPICIOUS = re.compile(r"^(jordan|nike|tenis|sneaker|producto|par|zapato|calzado)\s*\d+\s*$", re.I)
_LOCK = threading.RLock()
_RUNNING: set[str] = set()

def _now(): return datetime.now(timezone.utc).isoformat()

def _db():
    c=sqlite3.connect(database_path(),timeout=60)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c

def migrate():
    with _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS catalog_learning_jobs(
          id TEXT PRIMARY KEY,
          source_product_id TEXT NOT NULL,
          source_snapshot TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'queued',
          total INTEGER NOT NULL DEFAULT 0,
          processed INTEGER NOT NULL DEFAULT 0,
          base_matches INTEGER NOT NULL DEFAULT 0,
          exact_matches INTEGER NOT NULL DEFAULT 0,
          error TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_learning_jobs_status ON catalog_learning_jobs(status,updated_at);
        CREATE TABLE IF NOT EXISTS catalog_learning_results(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          job_id TEXT NOT NULL,
          product_id TEXT NOT NULL,
          score REAL NOT NULL DEFAULT 0,
          match_level TEXT NOT NULL DEFAULT 'none',
          evidence_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_learning_results_job ON catalog_learning_results(job_id,match_level);
        CREATE TABLE IF NOT EXISTS catalog_learning_refs(
          source_product_id TEXT PRIMARY KEY,
          identity_json TEXT NOT NULL DEFAULT '{}',
          image_ref TEXT NOT NULL DEFAULT '',
          learned_at TEXT NOT NULL
        );
        """)
        c.commit()

def _title(p):
    return str(p.get("title") or p.get("name") or p.get("model") or "").strip()

def _protected(p):
    t=_title(p)
    return bool(t) and not SUSPICIOUS.match(t)

def _images(p):
    out=[]
    for k in ("catalogImage","image","imagePath"):
        v=p.get(k)
        if isinstance(v,str) and v.strip(): out.append(v.strip())
    for k in ("originalImages","images","editedImages","approvedStudioImages"):
        v=p.get(k)
        if isinstance(v,list):
            for it in v:
                x=it.get("path") if isinstance(it,dict) else it
                if isinstance(x,str) and x.strip(): out.append(x.strip())
    v=p.get("approvedStudioImage")
    if isinstance(v,str) and v.strip(): out.append(v.strip())
    seen=[]
    for x in out:
        if x not in seen:seen.append(x)
    return seen

def _read(ref):
    ref=str(ref or "").strip()
    if not ref:return b""
    try:
        if ref.startswith(("http://","https://")):
            req=urllib.request.Request(ref,headers={"User-Agent":"EleganceBrainRC4/1.0"})
            with urllib.request.urlopen(req,timeout=10) as r:
                return r.read(18*1024*1024)
        if ref.startswith("/media/"):
            rel=ref[7:]
            dbp=Path(database_path()).resolve()
            for p in (dbp.parent/rel, Path("/data")/rel, Path(rel)):
                if p.exists() and p.is_file():return p.read_bytes()
        p=Path(ref)
        if p.exists() and p.is_file():return p.read_bytes()
    except Exception:
        return b""
    return b""

def _identity(p):
    return {k:p.get(k) for k in
            ("title","brand","family","model","colorway","category","subcategory","color","description","keywords")
            if p.get(k) not in (None,"",[],{})}

def _generic_title(identity):
    family=str(identity.get("family") or "").strip()
    model=str(identity.get("model") or "").strip()
    brand=str(identity.get("brand") or "").strip()
    if family and model:
        if model.lower().startswith(family.lower()):return model
        return f"{family} {model}".strip()
    if brand and model:return f"{brand} {model}".strip()
    return str(identity.get("title") or model or brand).strip()

def _update_job(job_id, **vals):
    if not vals:return
    vals["updated_at"]=_now()
    cols=",".join(f"{k}=?" for k in vals)
    args=list(vals.values())+[job_id]
    with _db() as c:
        c.execute(f"UPDATE catalog_learning_jobs SET {cols} WHERE id=?",args)
        c.commit()

def enqueue(source_product_id):
    migrate()
    state=load_state()
    products=state.get("products",[]) if isinstance(state,dict) else []
    source=next((p for p in products if isinstance(p,dict) and str(p.get("id"))==str(source_product_id)),None)
    if not source:raise ValueError("Producto fuente no encontrado.")
    identity=_identity(source)
    if not identity.get("title") or not identity.get("brand"):
        raise ValueError("La referencia necesita al menos nombre y marca confirmados.")
    refs=_images(source)
    if not refs:raise ValueError("La referencia no tiene imagen utilizable.")
    jid="learn_"+uuid.uuid4().hex[:16]
    now=_now()
    with _db() as c:
        c.execute("""INSERT INTO catalog_learning_jobs
        (id,source_product_id,source_snapshot,status,total,processed,base_matches,exact_matches,error,created_at,updated_at)
        VALUES(?,?,?,'queued',?,0,0,0,'',?,?)""",
        (jid,str(source_product_id),json.dumps(identity,ensure_ascii=False),len(products),now,now))
        c.execute("""INSERT INTO catalog_learning_refs(source_product_id,identity_json,image_ref,learned_at)
        VALUES(?,?,?,?) ON CONFLICT(source_product_id) DO UPDATE SET
        identity_json=excluded.identity_json,image_ref=excluded.image_ref,learned_at=excluded.learned_at""",
        (str(source_product_id),json.dumps(identity,ensure_ascii=False),refs[0],now))
        c.commit()
    start(jid)
    return {"status":"queued","jobId":jid,"sourceProductId":source_product_id,"total":len(products)}

def _run(job_id):
    with _LOCK:
        if job_id in _RUNNING:return
        _RUNNING.add(job_id)
    try:
        migrate()
        with _db() as c:
            row=c.execute("SELECT * FROM catalog_learning_jobs WHERE id=?",(job_id,)).fetchone()
        if not row:return
        row=dict(row)
        source_id=row["source_product_id"]
        identity=json.loads(row["source_snapshot"] or "{}")
        state=load_state()
        products=state.get("products",[]) if isinstance(state,dict) else []
        source=next((p for p in products if isinstance(p,dict) and str(p.get("id"))==source_id),None)
        if not source:raise ValueError("Producto fuente desapareció.")
        refs=_images(source)
        raw=_read(refs[0] if refs else "")
        if not raw:raise ValueError("No se pudo leer la imagen de referencia.")
        source_feat,source_orb=extract_phase4(raw)

        _update_job(job_id,status="running",total=len(products),processed=0,base_matches=0,exact_matches=0,error="")
        processed=base=exact=0
        changed=False
        public_exact=[]

        for p in products:
            if not isinstance(p,dict):continue
            pid=str(p.get("id") or "")
            if not pid or pid==source_id:continue
            processed += 1
            level="none"; score=0.0; ev={}
            if not _protected(p):
                imgs=_images(p)
                if imgs:
                    data=_read(imgs[0])
                    if data:
                        try:
                            feat,orb=extract_phase4(data)
                            ev=_compare(source_feat,source_orb,feat,orb)
                            score=float(ev.get("score") or 0)
                            regions=float(ev.get("regions") or 0)
                            shape=float(ev.get("shape") or 0)
                            kp=float(ev.get("keypoints") or 0)
                            color=float(ev.get("color") or 0)

                            if score>=0.70 and regions>=0.70 and (kp>=0.14 or shape>=0.78):
                                level="base";base+=1
                                for k in ("brand","family","category","subcategory"):
                                    if identity.get(k):p[k]=identity[k]

                                if score>=0.75 and (kp>=0.18 or shape>=0.84) and identity.get("model"):
                                    p["model"]=identity["model"]
                                    gt=_generic_title(identity)
                                    if gt:
                                        p["title"]=gt;p["name"]=gt

                                if score>=0.82 and regions>=0.80 and color>=0.84 and (kp>=0.22 or shape>=0.88):
                                    level="exact";exact+=1
                                    for k in ("title","brand","family","model","colorway","category","subcategory","color","description","keywords"):
                                        if identity.get(k) not in (None,"",[],{}):p[k]=identity[k]
                                    if identity.get("title"):p["name"]=identity["title"]
                                    public_exact.append(pid)
                                changed=True
                        except Exception:
                            pass
            try:
                with _db() as c:
                    c.execute("""INSERT INTO catalog_learning_results(job_id,product_id,score,match_level,evidence_json,created_at)
                    VALUES(?,?,?,?,?,?)""",(job_id,pid,score,level,json.dumps(ev,ensure_ascii=False,default=float),_now()))
                    c.commit()
            except Exception:pass
            if processed%5==0:
                _update_job(job_id,processed=processed,base_matches=base,exact_matches=exact)
                time.sleep(0.03)

        if changed:
            save_state(state)
            sync_products()
            for pid in public_exact:
                try:update_publication(pid,{"title":str(identity.get("title") or "")})
                except Exception:pass

        _update_job(job_id,status="done",processed=processed,base_matches=base,exact_matches=exact)
    except Exception as e:
        _update_job(job_id,status="failed",error=str(e))
    finally:
        with _LOCK:_RUNNING.discard(job_id)

def start(job_id):
    with _LOCK:
        if job_id in _RUNNING:return False
    threading.Thread(target=_run,args=(job_id,),name="EleganceBrain-"+job_id[-6:],daemon=True).start()
    return True

def resume_pending():
    migrate()
    with _db() as c:
        rows=c.execute("SELECT id FROM catalog_learning_jobs WHERE status IN ('queued','running') ORDER BY created_at ASC LIMIT 3").fetchall()
    for r in rows:start(r["id"])
    return len(rows)

def stats():
    migrate()
    resume_pending()
    with _db() as c:
        counts={s:c.execute("SELECT COUNT(*) FROM catalog_learning_jobs WHERE status=?",(s,)).fetchone()[0]
                for s in ("queued","running","done","failed")}
        last=c.execute("SELECT * FROM catalog_learning_jobs ORDER BY created_at DESC LIMIT 1").fetchone()
    out={"status":"ok","jobs":counts}
    if last:
        d=dict(last)
        d["sourceSnapshot"]=json.loads(d.pop("source_snapshot") or "{}")
        out["lastJob"]=d
    return out

def job(job_id):
    migrate()
    with _db() as c:r=c.execute("SELECT * FROM catalog_learning_jobs WHERE id=?",(job_id,)).fetchone()
    if not r:raise ValueError("Trabajo no encontrado.")
    d=dict(r)
    d["sourceSnapshot"]=json.loads(d.pop("source_snapshot") or "{}")
    return d
