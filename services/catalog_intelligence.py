from __future__ import annotations
import json, re, sqlite3, unicodedata, uuid
from datetime import datetime, timezone
from typing import Any
from services.state_store import database_path, load_state, save_state

SUSPICIOUS_NAME=re.compile(r"^(jordan|nike|tenis|sneaker|producto|par|zapato|calzado)\s*\d+\s*$",re.I)
FIELDS=("title","brand","family","model","colorway","category","subcategory","gender","color","sizes","description","keywords")

def _now(): return datetime.now(timezone.utc).isoformat()
def _db():
    c=sqlite3.connect(database_path(),timeout=60); c.row_factory=sqlite3.Row; c.execute("PRAGMA journal_mode=WAL"); return c
def _norm(v):
    s=unicodedata.normalize("NFKD",str(v or "").casefold()); s="".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+"," ",s).split())
def _title(p): return str(p.get("title") or p.get("name") or p.get("model") or p.get("id") or "Producto")
def _public_image(v):
    v=str(v or "").strip().replace("\\","/")
    if not v:return ""
    if v.startswith(("http://","https://","data:","/")):return v
    if v.startswith("data/"):return "/media/"+v[5:]
    return "/media/"+v.lstrip("./")
def _images(p):
    out=[]
    for k in ("catalogImage","image","imagePath"):
        v=p.get(k)
        if isinstance(v,str) and v and v not in out:out.append(_public_image(v))
    for k in ("originalImages","images","editedImages","approvedStudioImages"):
        v=p.get(k)
        if isinstance(v,list):
            for it in v:
                path=it.get("path") if isinstance(it,dict) else it
                if isinstance(path,str) and path and path not in out:out.append(_public_image(path))
    return out
def _products():
    s=load_state(); x=s.get("products",[]) if isinstance(s,dict) else []
    return [p for p in x if isinstance(p,dict)]
def _missing(p):
    m=[]; t=_title(p).strip()
    if not t or SUSPICIOUS_NAME.match(t):m.append("title")
    if not str(p.get("brand") or "").strip():m.append("brand")
    mv=str(p.get("model") or "")
    if not mv.strip() or SUSPICIOUS_NAME.match(mv):m.append("model")
    if not str(p.get("category") or p.get("universalCategory") or "").strip():m.append("category")
    if not str(p.get("subcategory") or "").strip():m.append("subcategory")
    if not str(p.get("color") or p.get("primaryColor") or "").strip():m.append("color")
    if not (p.get("sizes") or p.get("size")):m.append("sizes")
    return m

def migrate_catalog_intelligence():
    with _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS catalog_ai_proposals(
          product_id TEXT PRIMARY KEY,current_title TEXT NOT NULL DEFAULT '',
          proposal_json TEXT NOT NULL DEFAULT '{}',confidence REAL NOT NULL DEFAULT 0,
          evidence TEXT NOT NULL DEFAULT '',source TEXT NOT NULL DEFAULT 'catalog_audit',
          status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_catalog_ai_status ON catalog_ai_proposals(status,confidence);
        CREATE TABLE IF NOT EXISTS catalog_ai_audit_runs(
          id TEXT PRIMARY KEY,total_products INTEGER NOT NULL DEFAULT 0,
          suspicious_products INTEGER NOT NULL DEFAULT 0,missing_fields INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL);
        """); c.commit()
    return audit_stats()

def _row(pid):
    with _db() as c:r=c.execute("SELECT * FROM catalog_ai_proposals WHERE product_id=?",(pid,)).fetchone()
    if not r:return None
    d=dict(r)
    try:d["proposal"]=json.loads(d.pop("proposal_json") or "{}")
    except:d["proposal"]={}
    return d

def audit_catalog():
    migrate_catalog_intelligence(); ps=_products(); missn=0;susp=0;stamp=_now()
    with _db() as c:
        for p in ps:
            pid=str(p.get("id") or "").strip()
            if not pid:continue
            miss=_missing(p);missn+=len(miss);susp+=1 if miss else 0
            if not c.execute("SELECT 1 FROM catalog_ai_proposals WHERE product_id=?",(pid,)).fetchone():
                init={}
                if "category" in miss:init["category"]="Calzado"
                if "subcategory" in miss:init["subcategory"]="Tenis"
                c.execute("""INSERT INTO catalog_ai_proposals
                (product_id,current_title,proposal_json,confidence,evidence,source,status,created_at,updated_at)
                VALUES(?,?,?,?,?,'catalog_audit','pending',?,?)""",
                (pid,_title(p),json.dumps(init,ensure_ascii=False),0.0,"Campos faltantes: "+", ".join(miss),stamp,stamp))
        rid=uuid.uuid4().hex
        c.execute("INSERT INTO catalog_ai_audit_runs VALUES(?,?,?,?,?)",(rid,len(ps),susp,missn,stamp));c.commit()
    return {"status":"ok","runId":rid,"total":len(ps),"suspicious":susp,"missingFields":missn}

def audit_stats():
    ps=_products()
    with _db() as c:
        total=c.execute("SELECT COUNT(*) FROM catalog_ai_proposals").fetchone()[0]
        pending=c.execute("SELECT COUNT(*) FROM catalog_ai_proposals WHERE status='pending'").fetchone()[0]
        ready=c.execute("SELECT COUNT(*) FROM catalog_ai_proposals WHERE status='ready'").fetchone()[0]
        applied=c.execute("SELECT COUNT(*) FROM catalog_ai_proposals WHERE status='applied'").fetchone()[0]
        high=c.execute("SELECT COUNT(*) FROM catalog_ai_proposals WHERE status IN ('pending','ready') AND confidence>=.92").fetchone()[0]
    return {"status":"ok","products":len(ps),"proposals":total,"pending":pending,"ready":ready,"applied":applied,"highConfidence":high}

def list_audit(status="",q="",missing_only=False,offset=0,limit=40):
    migrate_catalog_intelligence(); props={}
    with _db() as c:rows=c.execute("SELECT * FROM catalog_ai_proposals").fetchall()
    for r in rows:
        d=dict(r)
        try:d["proposal"]=json.loads(d.pop("proposal_json") or "{}")
        except:d["proposal"]={}
        props[d["product_id"]]=d
    qn=_norm(q);items=[]
    for p in _products():
        pid=str(p.get("id") or "");pr=props.get(pid);miss=_missing(p);title=_title(p)
        if status and (not pr or pr.get("status")!=status):continue
        if missing_only and not miss:continue
        if qn and qn not in _norm(" ".join(map(str,[title,p.get("brand",""),p.get("model",""),p.get("category",""),pid]))):continue
        items.append({"id":pid,"title":title,"brand":str(p.get("brand") or ""),"model":str(p.get("model") or ""),
        "family":str(p.get("family") or ""),"colorway":str(p.get("colorway") or ""),
        "category":str(p.get("category") or p.get("universalCategory") or ""),"subcategory":str(p.get("subcategory") or ""),
        "color":str(p.get("color") or p.get("primaryColor") or ""),"sizes":p.get("sizes") or p.get("size") or [],
        "price":p.get("price"),"images":_images(p),"missing":miss,"proposal":(pr or {}).get("proposal",{}),
        "confidence":float((pr or {}).get("confidence") or 0),"status":(pr or {}).get("status","none"),"evidence":(pr or {}).get("evidence","")})
    items.sort(key=lambda x:(not bool(x["missing"]),x["title"].lower()));total=len(items)
    return {"status":"ok","total":total,"offset":offset,"limit":limit,"items":items[offset:offset+limit]}

def save_proposal(pid,payload):
    migrate_catalog_intelligence()
    if not any(str(p.get("id"))==str(pid) for p in _products()):raise ValueError("Producto no encontrado.")
    prop=payload.get("proposal") if isinstance(payload.get("proposal"),dict) else payload
    clean={k:prop[k] for k in FIELDS if k in prop}
    conf=max(0,min(1,float(payload.get("confidence",prop.get("confidence",0)) or 0)))
    ev=str(payload.get("evidence") or prop.get("evidence") or "").strip()
    st=str(payload.get("status") or "ready").lower()
    if st not in {"pending","ready","rejected","applied"}:st="ready"
    p=next(p for p in _products() if str(p.get("id"))==str(pid))
    with _db() as c:
        c.execute("""INSERT INTO catalog_ai_proposals
        (product_id,current_title,proposal_json,confidence,evidence,source,status,created_at,updated_at)
        VALUES(?,?,?,?,?,'manual_review',?,?,?)
        ON CONFLICT(product_id) DO UPDATE SET proposal_json=excluded.proposal_json,confidence=excluded.confidence,
        evidence=excluded.evidence,status=excluded.status,source=excluded.source,updated_at=excluded.updated_at""",
        (str(pid),_title(p),json.dumps(clean,ensure_ascii=False),conf,ev,st,_now(),_now()));c.commit()
    return _row(str(pid))

def _apply(p,prop):
    if prop.get("title"):p["title"]=str(prop["title"]).strip();p["name"]=str(prop["title"]).strip()
    for k in ("brand","family","model","colorway","category","subcategory","gender","color","description"):
        if k in prop and str(prop[k] or "").strip():p[k]=prop[k]
    if prop.get("sizes"):p["sizes"]=prop["sizes"]
    if prop.get("keywords"):p["keywords"]=prop["keywords"]

def apply_proposal(pid,force=False):
    r=_row(str(pid))
    if not r:raise ValueError("No existe propuesta.")
    if not force and float(r.get("confidence") or 0)<.92:raise ValueError("La propuesta no alcanza 92% de confianza.")
    prop=r.get("proposal") or {}
    if not prop:raise ValueError("La propuesta está vacía.")
    s=load_state();ps=s.get("products",[]) if isinstance(s,dict) else []
    p=next((x for x in ps if isinstance(x,dict) and str(x.get("id"))==str(pid)),None)
    if not p:raise ValueError("Producto no encontrado.")
    before={k:p.get(k) for k in FIELDS};_apply(p,prop);save_state(s)
    with _db() as c:c.execute("UPDATE catalog_ai_proposals SET status='applied',updated_at=? WHERE product_id=?",(_now(),str(pid)));c.commit()
    return {"status":"ok","productId":pid,"before":before,"after":{k:p.get(k) for k in FIELDS}}

def bulk_apply_high_confidence(threshold=.92):
    threshold=max(.80,min(1,float(threshold)))
    with _db() as c:rows=c.execute("SELECT product_id FROM catalog_ai_proposals WHERE status IN ('pending','ready') AND confidence>=? ORDER BY confidence DESC",(threshold,)).fetchall()
    out=[]
    for r in rows[:500]:
        try:out.append(apply_proposal(r["product_id"],True))
        except Exception as e:out.append({"productId":r["product_id"],"error":str(e)})
    return {"status":"ok","threshold":threshold,"applied":sum(1 for x in out if x.get("status")=="ok"),"results":out}

def export_audit():
    d=list_audit(limit=10000)
    return {"status":"ok","generatedAt":_now(),"total":d["total"],"instructions":{"purpose":"Identificar y enriquecer catálogo real sin modificar originales hasta confirmar.","desiredFields":["title","brand","family","model","colorway","category","subcategory","color","sizes","keywords"],"confidenceRule":"Autoaplicar solo >=0.92; lo demás requiere revisión."},"items":d["items"]}
