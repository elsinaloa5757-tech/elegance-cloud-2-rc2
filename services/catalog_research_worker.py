from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

from services.state_store import database_path
from services.catalog_brain import research_export, research_packet, migrate_catalog_brain
from services.catalog_intelligence import save_proposal
from services.shoe_phase6_enterprise import recognize as vision_recognize

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 EleganceResearch/1.0"

def _now(): return datetime.now(timezone.utc).isoformat()

def _db():
    c=sqlite3.connect(database_path(),timeout=60)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c

def migrate_research_worker():
    migrate_catalog_brain()
    with _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS catalog_research_jobs(
          id TEXT PRIMARY KEY,
          product_id TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL DEFAULT 'queued',
          priority INTEGER NOT NULL DEFAULT 0,
          attempts INTEGER NOT NULL DEFAULT 0,
          last_error TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_catalog_research_jobs_status
          ON catalog_research_jobs(status,priority DESC,created_at);

        CREATE TABLE IF NOT EXISTS catalog_research_results(
          product_id TEXT PRIMARY KEY,
          result_json TEXT NOT NULL DEFAULT '{}',
          confidence REAL NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'review',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS catalog_research_sources(
          id TEXT PRIMARY KEY,
          product_id TEXT NOT NULL,
          url TEXT NOT NULL DEFAULT '',
          title TEXT NOT NULL DEFAULT '',
          snippet TEXT NOT NULL DEFAULT '',
          query_text TEXT NOT NULL DEFAULT '',
          score REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_catalog_research_sources_product
          ON catalog_research_sources(product_id,score DESC);
        """)
        c.commit()
    return stats()

def stats():
    with _db() as c:
        q=c.execute("SELECT COUNT(*) FROM catalog_research_jobs WHERE status='queued'").fetchone()[0]
        p=c.execute("SELECT COUNT(*) FROM catalog_research_jobs WHERE status='processing'").fetchone()[0]
        d=c.execute("SELECT COUNT(*) FROM catalog_research_jobs WHERE status='done'").fetchone()[0]
        r=c.execute("SELECT COUNT(*) FROM catalog_research_results WHERE status='review'").fetchone()[0]
        ready=c.execute("SELECT COUNT(*) FROM catalog_research_results WHERE status='ready'").fetchone()[0]
        failed=c.execute("SELECT COUNT(*) FROM catalog_research_jobs WHERE status='failed'").fetchone()[0]
    return {"status":"ok","queued":q,"processing":p,"done":d,"review":r,"ready":ready,"failed":failed}

def build_jobs():
    migrate_research_worker()
    packets=research_export(0,10000,False).get("items",[])
    stamp=_now();created=0
    with _db() as c:
        for p in packets:
            pid=str(p.get("id") or "")
            if not pid: continue
            missing=len(p.get("missing") or [])
            images=len(p.get("images") or [])
            generic=1 if re.match(r"^(jordan|nike|tenis|producto|par)\s*\d+$",str((p.get("current") or {}).get("title") or ""),re.I) else 0
            priority=missing*10 + min(images,5)*3 + generic*8
            exists=c.execute("SELECT 1 FROM catalog_research_jobs WHERE product_id=?",(pid,)).fetchone()
            if exists:
                c.execute("UPDATE catalog_research_jobs SET priority=?,updated_at=? WHERE product_id=?",(priority,stamp,pid))
            else:
                c.execute("""INSERT INTO catalog_research_jobs
                (id,product_id,status,priority,attempts,last_error,created_at,updated_at)
                VALUES(?,?,'queued',?,0,'',?,?)""",(uuid.uuid4().hex,pid,priority,stamp,stamp))
                created+=1
        c.commit()
    return {"status":"ok","packets":len(packets),"created":created,**stats()}

def _fetch_bytes(url:str,timeout=18)->bytes:
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"image/avif,image/webp,image/apng,image/*,*/*;q=0.8"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        data=r.read(12*1024*1024)
        if not data: raise ValueError("Imagen vacía.")
        return data

def _clean_text(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>"," ",str(s or ""))).split())

def _search_web(query:str,limit=5)->list[dict[str,str]]:
    # Lightweight search adapter. If a provider blocks HTML search, the job continues with visual/internal evidence.
    url="https://html.duckduckgo.com/html/?"+urllib.parse.urlencode({"q":query})
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"text/html"})
    try:
        with urllib.request.urlopen(req,timeout=12) as r:
            txt=r.read(1500000).decode("utf-8","ignore")
    except Exception:
        return []
    items=[]
    # DuckDuckGo result anchors and snippets; intentionally tolerant to markup changes.
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',txt,re.I|re.S):
        href=html.unescape(m.group(1)); title=_clean_text(m.group(2))
        if href.startswith("//"): href="https:"+href
        if "uddg=" in href:
            try:
                qs=urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                href=urllib.parse.unquote(qs.get("uddg",[href])[0])
            except Exception: pass
        tail=txt[m.end():m.end()+1800]
        sm=re.search(r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>',tail,re.I|re.S)
        snippet=_clean_text(sm.group(1)) if sm else ""
        if href and title:
            items.append({"url":href,"title":title,"snippet":snippet,"query":query})
        if len(items)>=limit:break
    return items

def _tokenize(s:str)->set[str]:
    return set(re.findall(r"[a-z0-9]+",str(s or "").casefold()))

def _candidate_text(c:dict[str,Any])->str:
    return " ".join(str(c.get(k) or "") for k in ("brand","family","model","colorway","title"))

def _source_support(candidate:dict[str,Any],sources:list[dict[str,Any]])->float:
    ct=_tokenize(_candidate_text(candidate))
    if not ct or not sources:return 0.0
    brand=_tokenize(candidate.get("brand",""))
    model=_tokenize(candidate.get("model",""))
    cw=_tokenize(candidate.get("colorway",""))
    best=0.0
    for s in sources:
        st=_tokenize((s.get("title") or "")+" "+(s.get("snippet") or ""))
        if not st:continue
        model_hit=len(model & st)/max(1,len(model)) if model else 0
        brand_hit=len(brand & st)/max(1,len(brand)) if brand else 0
        cw_hit=len(cw & st)/max(1,len(cw)) if cw else 0
        overlap=len(ct & st)/max(1,len(ct))
        score=model_hit*.45+brand_hit*.22+cw_hit*.18+overlap*.15
        best=max(best,score)
    return max(0,min(1,best))

def _vision(packet:dict[str,Any])->dict[str,Any]:
    images=packet.get("images") or []
    category=str((packet.get("current") or {}).get("category") or "Calzado")
    outcomes=[]
    for url in images[:3]:
        try:
            data=_fetch_bytes(url)
            x=vision_recognize(data,category,8)
            outcomes.append({"image":url,"decision":x.get("decision"),"margin":x.get("margin",0),"items":x.get("items",[])})
        except Exception as e:
            outcomes.append({"image":url,"error":str(e)})
    agg={}
    for out in outcomes:
        for rank,it in enumerate(out.get("items") or []):
            key=(str(it.get("brand") or "").casefold(),str(it.get("model") or "").casefold())
            if not key[1]:continue
            weight=max(.25,1-rank*.10)
            score=float(it.get("modelConfidence") or 0)*weight
            d=agg.setdefault(key,{"brand":it.get("brand",""),"family":it.get("family",""),"model":it.get("model",""),
                                  "colorway":it.get("colorway",""),"scores":[],"colorScores":[]})
            d["scores"].append(score)
            if it.get("colorway"):
                d["colorway"]=it.get("colorway","")
                d["colorScores"].append(float(it.get("colorwayConfidence") or 0))
    candidates=[]
    for d in agg.values():
        avg=sum(d["scores"])/len(d["scores"])
        consistency=min(1.0,len(d["scores"])/max(1,min(3,len(images))))
        conf=avg*.82+consistency*.18
        candidates.append({**{k:d[k] for k in ("brand","family","model","colorway")},
                           "visionConfidence":round(conf,4),
                           "colorwayConfidence":round(sum(d["colorScores"])/len(d["colorScores"]),4) if d["colorScores"] else 0})
    candidates.sort(key=lambda x:x["visionConfidence"],reverse=True)
    return {"outcomes":outcomes,"candidates":candidates[:8]}

def _merge_candidates(packet,vision):
    pool={}
    for x in packet.get("internalCandidates") or []:
        c=x.get("candidate") or {}
        key=(str(c.get("brand") or "").casefold(),str(c.get("model") or "").casefold())
        if not key[1]:continue
        d=pool.setdefault(key,{"candidate":dict(c),"internal":0.0,"vision":0.0})
        d["internal"]=max(d["internal"],float(x.get("score") or 0))
    for c in vision.get("candidates") or []:
        key=(str(c.get("brand") or "").casefold(),str(c.get("model") or "").casefold())
        if not key[1]:continue
        d=pool.setdefault(key,{"candidate":dict(c),"internal":0.0,"vision":0.0})
        for k in ("brand","family","model","colorway"):
            if c.get(k):d["candidate"][k]=c[k]
        d["candidate"]["title"]=" ".join(str(d["candidate"].get(k) or "") for k in ("brand","model","colorway")).strip()
        d["vision"]=max(d["vision"],float(c.get("visionConfidence") or 0))
        d["colorwayConfidence"]=float(c.get("colorwayConfidence") or 0)
    return list(pool.values())

def research_product(product_id:str,allow_web=True):
    migrate_research_worker()
    packet=research_packet(product_id)
    if not packet: raise ValueError("No existe paquete de investigación.")
    vision=_vision(packet)
    pool=_merge_candidates(packet,vision)

    queries=[]
    # Image/vision candidates have priority in external verification.
    for d in sorted(pool,key=lambda x:x["vision"],reverse=True)[:4]:
        c=d["candidate"]
        q=" ".join(str(c.get(k) or "") for k in ("brand","model","colorway")).strip()
        if q and q not in queries:queries.append(q)
    for q in packet.get("researchQueries") or []:
        if q not in queries:queries.append(q)

    sources=[]
    if allow_web and os.getenv("ELEGANCE_RESEARCH_DISABLE_WEB","0")!="1":
        for q in queries[:6]:
            sources.extend(_search_web(q,4))
            if len(sources)>=16:break
            time.sleep(.15)

    ranked=[]
    for d in pool:
        support=_source_support(d["candidate"],sources)
        visual=float(d["vision"]); internal=float(d["internal"])
        # Image is primary. Web corroborates. Generic old text has deliberately small influence.
        final=visual*.62 + support*.28 + internal*.10
        if visual==0:
            final=support*.55+internal*.45
        ranked.append({**d,"webSupport":round(support,4),"confidence":round(max(0,min(1,final)),4)})
    ranked.sort(key=lambda x:x["confidence"],reverse=True)

    top=ranked[0] if ranked else None
    second=ranked[1]["confidence"] if len(ranked)>1 else 0
    margin=(top["confidence"]-second) if top else 0
    proposed={}
    confidence=0.0
    decision="unresolved"
    if top:
        confidence=float(top["confidence"])
        visual_support=float(top.get("vision") or 0)

        # RC2: never show a generic textual fallback as a real identification.
        if confidence>=.92 and margin>=.08 and visual_support>=.72:
            proposed=dict(top["candidate"])
            decision="ready"
        elif confidence>=.72 and margin>=.04 and visual_support>=.45:
            proposed=dict(top["candidate"])
            decision="review"
        elif margin<.04:
            decision="ambiguous"
        elif visual_support<.45:
            decision="insufficient_visual_evidence"
        else:
            decision="low_confidence"

    result={
      "productId":product_id,"decision":decision,"confidence":round(confidence,4),"margin":round(margin,4),
      "proposal":proposed,"vision":vision,"rankedCandidates":ranked[:10],
      "sources":sources[:20],
      "notes":"La imagen tiene prioridad; nombre anterior solo aporta evidencia secundaria. No se fuerza identificación si no hay consenso."
    }
    stamp=_now()
    with _db() as c:
        c.execute("DELETE FROM catalog_research_sources WHERE product_id=?",(product_id,))
        for s in sources[:30]:
            score=_source_support(proposed,sources) if proposed else 0
            c.execute("""INSERT INTO catalog_research_sources
            (id,product_id,url,title,snippet,query_text,score,created_at) VALUES(?,?,?,?,?,?,?,?)""",
            (uuid.uuid4().hex,product_id,s.get("url",""),s.get("title",""),s.get("snippet",""),s.get("query",""),score,stamp))
        c.execute("""INSERT INTO catalog_research_results(product_id,result_json,confidence,status,created_at,updated_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(product_id) DO UPDATE SET result_json=excluded.result_json,confidence=excluded.confidence,
        status=excluded.status,updated_at=excluded.updated_at""",
        (product_id,json.dumps(result,ensure_ascii=False),confidence,decision,stamp,stamp))
        c.execute("UPDATE catalog_research_jobs SET status='done',last_error='',updated_at=? WHERE product_id=?",(stamp,product_id))
        c.commit()

    # Only place a ready proposal into Auditoría; never apply it to the product automatically.
    if decision=="ready":
        evidence="Catalog Research Worker. Visual %.0f%%; web %.0f%%; margen %.0f%%. Fuentes: %s" % (
            top["vision"]*100,top["webSupport"]*100,margin*100,
            "; ".join(s.get("url","") for s in sources[:3] if s.get("url"))
        )
        save_proposal(product_id,{"proposal":proposed,"confidence":confidence,"evidence":evidence,"status":"ready"})
    return result

def run_batch(limit=10,allow_web=True):
    migrate_research_worker()
    limit=max(1,min(int(limit),50))
    with _db() as c:
        rows=[dict(r) for r in c.execute("""
          SELECT * FROM catalog_research_jobs WHERE status IN ('queued','failed')
          ORDER BY priority DESC,created_at LIMIT ?
        """,(limit,)).fetchall()]
    done=[];failed=[]
    for row in rows:
        pid=row["product_id"]
        with _db() as c:
            c.execute("UPDATE catalog_research_jobs SET status='processing',attempts=attempts+1,updated_at=? WHERE product_id=?",(_now(),pid))
            c.commit()
        try:
            r=research_product(pid,allow_web)
            done.append({"productId":pid,"decision":r["decision"],"confidence":r["confidence"]})
        except Exception as e:
            with _db() as c:
                c.execute("UPDATE catalog_research_jobs SET status='failed',last_error=?,updated_at=? WHERE product_id=?",(str(e)[:1000],_now(),pid))
                c.commit()
            failed.append({"productId":pid,"error":str(e)})
    return {"status":"ok","processed":len(rows),"done":done,"failed":failed,**stats()}


def requeue_unresolved():
    migrate_research_worker()
    weak=("low_confidence","ambiguous","insufficient_visual_evidence","unresolved")
    with _db() as c:
        rows=c.execute(
            "SELECT product_id FROM catalog_research_results WHERE status IN (?,?,?,?)",
            weak
        ).fetchall()
        ids=[str(r["product_id"]) for r in rows]
        for pid in ids:
            c.execute(
                "UPDATE catalog_research_jobs SET status='queued',last_error='',updated_at=? WHERE product_id=?",
                (_now(),pid)
            )
        c.commit()
    return {"status":"ok","requeued":len(ids),**stats()}

def result(product_id):
    with _db() as c:r=c.execute("SELECT * FROM catalog_research_results WHERE product_id=?",(product_id,)).fetchone()
    if not r:return None
    d=dict(r)
    try:d["result"]=json.loads(d.pop("result_json") or "{}")
    except:d["result"]={}
    return d

def list_results(status="",offset=0,limit=50):
    with _db() as c:
        if status:
            rows=[dict(r) for r in c.execute("SELECT * FROM catalog_research_results WHERE status=? ORDER BY confidence DESC LIMIT ? OFFSET ?",(status,limit,offset)).fetchall()]
            total=c.execute("SELECT COUNT(*) FROM catalog_research_results WHERE status=?",(status,)).fetchone()[0]
        else:
            rows=[dict(r) for r in c.execute("SELECT * FROM catalog_research_results ORDER BY confidence DESC LIMIT ? OFFSET ?",(limit,offset)).fetchall()]
            total=c.execute("SELECT COUNT(*) FROM catalog_research_results").fetchone()[0]
    items=[]
    for d in rows:
        try:r=json.loads(d["result_json"])
        except:r={}
        items.append({"productId":d["product_id"],"confidence":d["confidence"],"status":d["status"],
                      "proposal":r.get("proposal",{}),"margin":r.get("margin",0),
                      "sources":r.get("sources",[])[:3]})
    return {"status":"ok","total":total,"offset":offset,"limit":limit,"items":items}
