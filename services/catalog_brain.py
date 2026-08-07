from __future__ import annotations

import difflib
import json
import re
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any

from services.state_store import database_path
from services.catalog_intelligence import (
    _products, _images, _missing, _title, _norm, _db as audit_db,
    save_proposal, migrate_catalog_intelligence
)

def _now(): return datetime.now(timezone.utc).isoformat()

def _db():
    c=sqlite3.connect(database_path(),timeout=60)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c

def _norm2(v):
    s=unicodedata.normalize("NFKD",str(v or "").casefold())
    s="".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9+#.-]+"," ",s).split())

def migrate_catalog_brain():
    migrate_catalog_intelligence()
    with _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS catalog_brain_candidates(
          id TEXT PRIMARY KEY,
          product_id TEXT NOT NULL,
          candidate_json TEXT NOT NULL,
          score REAL NOT NULL DEFAULT 0,
          evidence_json TEXT NOT NULL DEFAULT '{}',
          source TEXT NOT NULL DEFAULT 'internal_master',
          status TEXT NOT NULL DEFAULT 'candidate',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_catalog_brain_product
          ON catalog_brain_candidates(product_id,score DESC);

        CREATE TABLE IF NOT EXISTS catalog_brain_research(
          product_id TEXT PRIMARY KEY,
          packet_json TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS catalog_brain_clusters(
          cluster_id TEXT NOT NULL,
          product_id TEXT NOT NULL,
          reason TEXT NOT NULL DEFAULT '',
          confidence REAL NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(cluster_id,product_id)
        );
        """)
        c.commit()
    return stats()

def _master_rows():
    with _db() as c:
        rows=[]
        try:
            rows += [dict(r) for r in c.execute("""
              SELECT category,subcategory,brand,family,model,colorway,aliases_json,source,confidence
              FROM fashion_master_v6 WHERE active=1
            """).fetchall()]
        except Exception:
            pass
        try:
            rows += [dict(r) for r in c.execute("""
              SELECT category,subcategory,brand,family,model,colorway,aliases_json,source,confidence
              FROM shoe_master_models WHERE active=1
            """).fetchall()]
        except Exception:
            pass
    uniq={}
    for r in rows:
        key=tuple(_norm2(r.get(k)) for k in ("category","brand","model","colorway"))
        uniq[key]=r
    return list(uniq.values())

def _aliases(row):
    out=[]
    try:
        a=json.loads(row.get("aliases_json") or "[]")
        if isinstance(a,list):out.extend(str(x) for x in a if str(x).strip())
    except Exception:pass
    for x in (row.get("brand"),row.get("family"),row.get("model"),row.get("colorway")):
        if str(x or "").strip():out.append(str(x))
    return out

def _tokens(s): return set(_norm2(s).split())

def _score_product_master(p,row):
    text=" ".join(str(x or "") for x in (
        _title(p),p.get("brand"),p.get("model"),p.get("family"),p.get("colorway"),
        p.get("category"),p.get("subcategory"),p.get("description")
    ))
    q=_norm2(text)
    if not q:return 0.0,{}
    qt=_tokens(q)
    best=0.0;best_alias=""
    for a in _aliases(row):
        v=_norm2(a)
        if not v:continue
        vt=_tokens(v)
        ratio=difflib.SequenceMatcher(None,q,v).ratio()
        jac=len(qt & vt)/max(1,len(qt | vt))
        contain=1.0 if v in q or q in v else 0.0
        s=ratio*.35+jac*.42+contain*.23
        qnums=set(re.findall(r"\d+",q));vnums=set(re.findall(r"\d+",v))
        if qnums and vnums and not (qnums & vnums):s-=.25
        if s>best:best=s;best_alias=a
    brand_bonus=0.0
    pb=_norm2(p.get("brand"))
    rb=_norm2(row.get("brand"))
    if pb and rb:
        brand_bonus=.12 if pb==rb else -.12
    category_bonus=0.0
    pc=_norm2(p.get("category") or p.get("universalCategory"))
    rc=_norm2(row.get("category"))
    if pc and rc and pc==rc:category_bonus=.06
    final=max(0,min(1,best+brand_bonus+category_bonus))
    return final,{"matchedAlias":best_alias,"textScore":round(best,4),"brandBonus":brand_bonus,"categoryBonus":category_bonus}

def build_candidates(product_id="",limit_per_product=8):
    migrate_catalog_brain()
    masters=_master_rows()
    ps=[p for p in _products() if not product_id or str(p.get("id"))==str(product_id)]
    stamp=_now();made=0
    with _db() as c:
        for p in ps:
            pid=str(p.get("id") or "")
            if not pid:continue
            scored=[]
            for r in masters:
                s,ev=_score_product_master(p,r)
                if s<.22:continue
                cand={k:r.get(k) or "" for k in ("category","subcategory","brand","family","model","colorway")}
                cand["title"]=" ".join(x for x in (cand["brand"],cand["model"],cand["colorway"]) if x).strip()
                scored.append((s,cand,ev,r.get("source") or "master"))
            scored.sort(key=lambda x:x[0],reverse=True)
            c.execute("DELETE FROM catalog_brain_candidates WHERE product_id=? AND source='internal_master'",(pid,))
            for s,cand,ev,src in scored[:max(1,min(limit_per_product,20))]:
                c.execute("""INSERT INTO catalog_brain_candidates
                  (id,product_id,candidate_json,score,evidence_json,source,status,created_at,updated_at)
                  VALUES(?,?,?,?,?,?, 'candidate',?,?)""",
                  (uuid.uuid4().hex,pid,json.dumps(cand,ensure_ascii=False),
                   float(s),json.dumps(ev,ensure_ascii=False),f"internal_master:{src}",stamp,stamp))
                made+=1
        c.commit()
    return {"status":"ok","products":len(ps),"candidatesCreated":made}

def _candidate_rows(pid):
    with _db() as c:
        rows=[dict(r) for r in c.execute("""
          SELECT * FROM catalog_brain_candidates WHERE product_id=?
          ORDER BY score DESC LIMIT 20
        """,(str(pid),)).fetchall()]
    for r in rows:
        try:r["candidate"]=json.loads(r.pop("candidate_json"))
        except:r["candidate"]={}
        try:r["evidence"]=json.loads(r.pop("evidence_json"))
        except:r["evidence"]={}
    return rows

def prepare_research_packets():
    migrate_catalog_brain()
    ps=_products();stamp=_now();count=0
    with _db() as c:
        for p in ps:
            pid=str(p.get("id") or "")
            if not pid:continue
            miss=_missing(p)
            candidates=_candidate_rows(pid)[:5]
            packet={
              "id":pid,"current":{"title":_title(p),"brand":p.get("brand") or "",
              "family":p.get("family") or "","model":p.get("model") or "",
              "colorway":p.get("colorway") or "","category":p.get("category") or p.get("universalCategory") or "",
              "subcategory":p.get("subcategory") or "","color":p.get("color") or p.get("primaryColor") or "",
              "sizes":p.get("sizes") or p.get("size") or [],"price":p.get("price")},
              "images":_images(p),"missing":miss,
              "internalCandidates":[{"score":round(float(x["score"]),4),"candidate":x["candidate"],
                                     "evidence":x["evidence"],"source":x["source"]} for x in candidates],
              "researchQueries":_research_queries(p,candidates),
              "desiredFields":["title","brand","family","model","colorway","category","subcategory","color","sizes","keywords","description"],
              "rule":"No aplicar automáticamente investigación externa sin evidencia suficiente. >=0.92 puede marcarse lista; inferior requiere revisión."
            }
            c.execute("""INSERT INTO catalog_brain_research(product_id,packet_json,status,updated_at)
              VALUES(?,?,'pending',?)
              ON CONFLICT(product_id) DO UPDATE SET packet_json=excluded.packet_json,updated_at=excluded.updated_at""",
              (pid,json.dumps(packet,ensure_ascii=False),stamp))
            count+=1
        c.commit()
    return {"status":"ok","packets":count}

def _research_queries(p,candidates):
    q=[]
    title=_title(p)
    if title and not re.match(r"^(jordan|nike|tenis|producto|par)\s*\d+$",title,re.I):
        q.append(title+" sneakers model")
    for x in candidates[:3]:
        c=x.get("candidate") or {}
        text=" ".join(str(c.get(k) or "") for k in ("brand","model","colorway")).strip()
        if text and text not in q:q.append(text)
    brand=str(p.get("brand") or "").strip()
    if brand and title:q.append(f'{brand} "{title}"')
    return q[:6]

def research_packet(product_id):
    migrate_catalog_brain()
    with _db() as c:r=c.execute("SELECT * FROM catalog_brain_research WHERE product_id=?",(str(product_id),)).fetchone()
    if not r:return None
    try:return json.loads(r["packet_json"])
    except:return None

def research_export(offset=0,limit=200,only_missing=True):
    migrate_catalog_brain()
    with _db() as c:rows=[dict(r) for r in c.execute("SELECT * FROM catalog_brain_research ORDER BY product_id").fetchall()]
    items=[]
    for r in rows:
        try:p=json.loads(r["packet_json"])
        except:continue
        if only_missing and not p.get("missing"):continue
        items.append(p)
    return {"status":"ok","total":len(items),"offset":offset,"limit":limit,
            "items":items[offset:offset+limit]}

def stats():
    with _db() as c:
        cand=c.execute("SELECT COUNT(*) FROM catalog_brain_candidates").fetchone()[0]
        packets=c.execute("SELECT COUNT(*) FROM catalog_brain_research").fetchone()[0]
        clusters=c.execute("SELECT COUNT(DISTINCT cluster_id) FROM catalog_brain_clusters").fetchone()[0]
        strong=c.execute("SELECT COUNT(*) FROM catalog_brain_candidates WHERE score>=.90").fetchone()[0]
    return {"status":"ok","candidates":cand,"researchPackets":packets,"clusters":clusters,"strongCandidates":strong}

def cluster_duplicates():
    migrate_catalog_brain()
    ps=_products()
    buckets={}
    for p in ps:
        pid=str(p.get("id") or "")
        if not pid:continue
        key=_norm2(" ".join(str(p.get(k) or "") for k in ("brand","family","model","colorway")))
        if not key or len(key)<4:
            key=_norm2(_title(p))
        if key:buckets.setdefault(key,[]).append(p)
    stamp=_now();clusters=0
    with _db() as c:
        c.execute("DELETE FROM catalog_brain_clusters")
        for key,items in buckets.items():
            if len(items)<2:continue
            cid=uuid.uuid4().hex;clusters+=1
            for p in items:
                c.execute("INSERT INTO catalog_brain_clusters VALUES(?,?,?,?,?)",
                          (cid,str(p.get("id")),f"Identidad normalizada: {key}",.88,stamp))
        c.commit()
    return {"status":"ok","clusters":clusters}

def auto_propose(product_id,minimum=.70):
    rows=_candidate_rows(product_id)
    if not rows: build_candidates(product_id); rows=_candidate_rows(product_id)
    if not rows:return {"status":"ok","applied":False,"message":"Sin candidatos internos."}
    top=rows[0]; second=rows[1]["score"] if len(rows)>1 else 0
    margin=float(top["score"])-float(second)
    score=float(top["score"])
    if score<minimum or margin<.08:
        return {"status":"ok","applied":False,"candidate":top["candidate"],"confidence":round(score,4),"margin":round(margin,4),
                "message":"Candidato insuficiente para propuesta automática."}
    confidence=min(.91,score*.92 + min(.08,margin*.25))
    ev=f"Catalog Brain: coincidencia con Base Maestra; score {score:.2f}; margen {margin:.2f}; fuente {top['source']}."
    saved=save_proposal(product_id,{"proposal":top["candidate"],"confidence":confidence,"evidence":ev,"status":"ready"})
    return {"status":"ok","applied":True,"proposal":saved,"confidence":round(confidence,4),"margin":round(margin,4)}

def auto_propose_all():
    build_candidates()
    out=[]
    for p in _products():
        pid=str(p.get("id") or "")
        if not pid:continue
        try:out.append(auto_propose(pid))
        except Exception as e:out.append({"productId":pid,"error":str(e)})
    prepare_research_packets()
    return {"status":"ok","products":len(out),"proposals":sum(1 for x in out if x.get("applied"))}
