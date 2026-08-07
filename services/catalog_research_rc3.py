from __future__ import annotations
import html,json,re,sqlite3,time,urllib.parse,urllib.request,uuid
from datetime import datetime,timezone
from services.state_store import database_path
from services.catalog_brain import research_packet
from services.catalog_intelligence import save_proposal
from services.catalog_research_worker import _fetch_bytes,_search_web,_source_support,_vision,_merge_candidates,_db as worker_db,_now as worker_now
from services.shoe_phase6_enterprise import _extract,_compare

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150 Safari/537.36"

def _now(): return datetime.now(timezone.utc).isoformat()
def _db():
    c=sqlite3.connect(database_path(),timeout=60);c.row_factory=sqlite3.Row;c.execute("PRAGMA journal_mode=WAL");return c

def migrate_rc3():
    with _db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS catalog_visual_provider_events(
          id TEXT PRIMARY KEY,product_id TEXT NOT NULL,provider TEXT NOT NULL,
          query_url TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT '',
          candidates_json TEXT NOT NULL DEFAULT '[]',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS catalog_external_visual_refs(
          id TEXT PRIMARY KEY,product_id TEXT NOT NULL,candidate_key TEXT NOT NULL,
          source_url TEXT NOT NULL DEFAULT '',image_url TEXT NOT NULL DEFAULT '',
          visual_score REAL NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_external_visual_product
          ON catalog_external_visual_refs(product_id,visual_score DESC);
        ''');c.commit()
    return stats()

def stats():
    with _db() as c:
        e=c.execute("SELECT COUNT(*) FROM catalog_visual_provider_events").fetchone()[0]
        r=c.execute("SELECT COUNT(*) FROM catalog_external_visual_refs").fetchone()[0]
        u=c.execute("SELECT COUNT(*) FROM catalog_external_visual_refs WHERE visual_score>=.60").fetchone()[0]
    return {"status":"ok","providerEvents":e,"externalRefs":r,"usefulRefs":u}

def _http(url,timeout=16,max_bytes=1800000):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"text/html,*/*","Accept-Language":"es-MX,es;q=.9,en;q=.7"})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read(max_bytes).decode("utf-8","ignore")

def _plain(x):
    x=html.unescape(str(x or ""))
    x=re.sub(r"<script\\b[^>]*>.*?</script>"," ",x,flags=re.I|re.S)
    x=re.sub(r"<style\\b[^>]*>.*?</style>"," ",x,flags=re.I|re.S)
    return " ".join(re.sub(r"<[^>]+>"," ",x).split())

def _master():
    with _db() as c:
        try: rows=[dict(r) for r in c.execute("SELECT category,subcategory,brand,family,model,colorway,aliases_json FROM fashion_master_v6 WHERE active=1").fetchall()]
        except Exception: rows=[]
    for r in rows:
        try:r["aliases"]=json.loads(r.pop("aliases_json") or "[]")
        except:r["aliases"]=[]
    return rows

def _master_from_text(text,limit=18):
    txt=" "+re.sub(r"[^a-z0-9]+"," ",text.casefold())+" ";toks=set(txt.split());out=[]
    for r in _master():
        mt=set(re.findall(r"[a-z0-9]+",str(r.get("model") or "").casefold()))
        bt=set(re.findall(r"[a-z0-9]+",str(r.get("brand") or "").casefold()))
        if not mt:continue
        mh=len(mt&toks)/len(mt);bh=len(bt&toks)/max(1,len(bt))
        exact=1.0 if (" "+re.sub(r"[^a-z0-9]+"," ",str(r.get("model") or "").casefold()).strip()+" ") in txt else 0
        alias=0
        for a in r.get("aliases") or []:
            av=re.sub(r"[^a-z0-9]+"," ",str(a).casefold()).strip()
            if av and (" "+av+" ") in txt:alias=1;break
        score=mh*.62+bh*.15+exact*.18+alias*.05
        if score>=.48:
            out.append({"brand":r.get("brand",""),"family":r.get("family",""),"model":r.get("model",""),
                        "colorway":r.get("colorway",""),"category":r.get("category","Calzado"),
                        "subcategory":r.get("subcategory","Tenis"),"providerTextScore":round(min(1,score),4)})
    out.sort(key=lambda x:x["providerTextScore"],reverse=True)
    seen=set();uniq=[]
    for x in out:
        k=(x["brand"].casefold(),x["model"].casefold(),x["colorway"].casefold())
        if k not in seen:seen.add(k);uniq.append(x)
    return uniq[:limit]

def reverse_candidates(pid,image_url):
    enc=urllib.parse.quote(image_url,safe="")
    providers=[
      ("google_lens",f"https://lens.google.com/uploadbyurl?url={enc}&hl=es"),
      ("bing_visual","https://www.bing.com/images/searchbyimage?"+urllib.parse.urlencode({"cbir":"sbi","imgurl":image_url,"iss":"sbiupload","FORM":"SBIIDP"}))
    ]
    allc=[];events=[]
    for name,url in providers:
        try:
            txt=_plain(_http(url,18));cs=_master_from_text(txt);st="ok"
        except Exception as e:
            cs=[];st="error:"+type(e).__name__
        events.append({"provider":name,"status":st,"candidates":cs[:8]});allc.extend(cs)
        with _db() as c:
            c.execute("INSERT INTO catalog_visual_provider_events VALUES(?,?,?,?,?,?,?)",
                      (uuid.uuid4().hex,pid,name,url,st,json.dumps(cs,ensure_ascii=False),_now()));c.commit()
    merged={}
    for x in allc:
        k=(x["brand"].casefold(),x["model"].casefold(),x["colorway"].casefold())
        d=merged.setdefault(k,dict(x,providerHits=0,vals=[]));d["providerHits"]+=1;d["vals"].append(x["providerTextScore"])
    items=[]
    for d in merged.values():
        d["reverseVisual"]=round(min(1,max(d["vals"])+(.08 if d["providerHits"]>1 else 0)),4);d.pop("vals");items.append(d)
    items.sort(key=lambda x:(x["reverseVisual"],x["providerHits"]),reverse=True)
    return {"events":events,"items":items[:20]}

def _images(page,base):
    out=[]
    pats=[
      r'<meta[^>]+property=["\\\']og:image[^"\\\']*["\\\'][^>]+content=["\\\']([^"\\\']+)',
      r'<meta[^>]+content=["\\\']([^"\\\']+)["\\\'][^>]+property=["\\\']og:image',
      r'<img[^>]+(?:src|data-src)=["\\\']([^"\\\']+)'
    ]
    for p in pats:
        for m in re.finditer(p,page,re.I):
            u=html.unescape(m.group(1)).strip()
            if u.startswith("//"):u="https:"+u
            elif u.startswith("/"):u=urllib.parse.urljoin(base,u)
            if u.startswith("http") and u not in out:out.append(u)
            if len(out)>=20:return out
    return out

def _sim(a,b,cat):
    try:return float(_compare(_extract(a,cat),_extract(b,cat),cat).get("identity") or 0)
    except Exception:return 0.0

def corroborate(pid,qbytes,cand,cat):
    q=" ".join(str(cand.get(k) or "") for k in ("brand","model","colorway")).strip()
    pages=_search_web(q+" sneakers",4) if q else [];refs=[];checked=0
    for pg in pages:
        try:imgs=_images(_http(pg.get("url",""),12,1200000),pg.get("url",""))
        except:continue
        for iu in imgs[:4]:
            if checked>=8:break
            checked+=1
            try:s=_sim(qbytes,_fetch_bytes(iu,12),cat)
            except:continue
            if s>=.25:
                refs.append({"sourceUrl":pg.get("url",""),"title":pg.get("title",""),"imageUrl":iu,"visualScore":round(s,4)})
                with _db() as c:
                    c.execute("INSERT INTO catalog_external_visual_refs VALUES(?,?,?,?,?,?,?)",
                              (uuid.uuid4().hex,pid,f"{cand.get('brand','')}|{cand.get('model','')}|{cand.get('colorway','')}",
                               pg.get("url",""),iu,s,_now()));c.commit()
        if checked>=8:break
    refs.sort(key=lambda x:x["visualScore"],reverse=True)
    top=[x["visualScore"] for x in refs[:3]]
    return {"best":max(top) if top else 0,"consensus":sum(top)/len(top) if top else 0,"refs":refs[:6]}

def research_rc3(pid):
    migrate_rc3();packet=research_packet(pid)
    if not packet:raise ValueError("Sin paquete de investigación.")
    imgs=packet.get("images") or []
    if not imgs:raise ValueError("Producto sin imagen pública.")
    qbytes=_fetch_bytes(imgs[0],18);cat=str((packet.get("current") or {}).get("category") or "Calzado")
    local=_vision(packet);pool=_merge_candidates(packet,local);rev=reverse_candidates(pid,imgs[0])
    combined={}
    for d in pool:
        c=d["candidate"];k=(str(c.get("brand","")).casefold(),str(c.get("model","")).casefold(),str(c.get("colorway","")).casefold())
        combined[k]={"candidate":dict(c),"internal":float(d.get("internal") or 0),"local":float(d.get("vision") or 0),"reverse":0.0,"hits":0}
    for c in rev["items"]:
        k=(str(c.get("brand","")).casefold(),str(c.get("model","")).casefold(),str(c.get("colorway","")).casefold())
        d=combined.setdefault(k,{"candidate":dict(c),"internal":0.0,"local":0.0,"reverse":0.0,"hits":0})
        d["reverse"]=max(d["reverse"],float(c.get("reverseVisual") or 0));d["hits"]=max(d["hits"],int(c.get("providerHits") or 0))
    seeds=sorted(combined.values(),key=lambda d:d["reverse"]*.65+d["local"]*.25+d["internal"]*.10,reverse=True)[:7]
    ranked=[]
    for d in seeds:
        ext=corroborate(pid,qbytes,d["candidate"],cat)
        ws=_source_support(d["candidate"],_search_web(" ".join(str(d["candidate"].get(k) or "") for k in ("brand","model","colorway")),4))
        ev=float(ext["consensus"])
        score=ev*.50+d["reverse"]*.28+d["local"]*.12+ws*.07+d["internal"]*.03
        ranked.append({"candidate":d["candidate"],"confidence":round(score,4),"externalVisual":round(ev,4),
                       "reverseVisual":round(d["reverse"],4),"localVision":round(d["local"],4),
                       "providerHits":d["hits"],"references":ext["refs"]})
        time.sleep(.08)
    ranked.sort(key=lambda x:x["confidence"],reverse=True)
    top=ranked[0] if ranked else None;second=ranked[1]["confidence"] if len(ranked)>1 else 0
    margin=(top["confidence"]-second) if top else 0;decision="unresolved";proposal={};conf=0
    if top:
        conf=float(top["confidence"])
        if conf>=.86 and margin>=.08 and top["externalVisual"]>=.72 and top["reverseVisual"]>=.55:
            decision="ready";proposal=dict(top["candidate"])
        elif conf>=.68 and margin>=.05 and (top["externalVisual"]>=.58 or (top["reverseVisual"]>=.70 and top["providerHits"]>=2)):
            decision="review";proposal=dict(top["candidate"])
        elif margin<.04:decision="ambiguous_external"
        else:decision="insufficient_external_evidence"
    result={"status":"ok","productId":pid,"decision":decision,"confidence":round(conf,4),"margin":round(margin,4),
            "proposal":proposal,"reverseVisual":rev,"candidates":ranked[:7],
            "notes":"RC3 exige evidencia visual externa; no fuerza identificación."}
    stamp=_now()
    with worker_db() as c:
        c.execute('''INSERT INTO catalog_research_results(product_id,result_json,confidence,status,created_at,updated_at)
          VALUES(?,?,?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET result_json=excluded.result_json,
          confidence=excluded.confidence,status=excluded.status,updated_at=excluded.updated_at''',
          (pid,json.dumps(result,ensure_ascii=False),conf,decision,stamp,stamp))
        c.execute("UPDATE catalog_research_jobs SET status='done',last_error='',updated_at=? WHERE product_id=?",(stamp,pid));c.commit()
    if decision=="ready":
        src="; ".join(x.get("sourceUrl","") for x in top.get("references",[])[:3])
        save_proposal(pid,{"proposal":proposal,"confidence":conf,
                          "evidence":f"RC3 visual externo {top['externalVisual']:.0%}; reverse {top['reverseVisual']:.0%}; margen {margin:.0%}. {src}",
                          "status":"ready"})
    return result

def requeue():
    weak=("ambiguous","low_confidence","insufficient_visual_evidence","unresolved","ambiguous_external","insufficient_external_evidence")
    with worker_db() as c:
        rows=c.execute("SELECT product_id FROM catalog_research_results WHERE status IN (?,?,?,?,?,?)",weak).fetchall()
        ids=[str(x["product_id"]) for x in rows]
        for pid in ids:c.execute("UPDATE catalog_research_jobs SET status='queued',last_error='',updated_at=? WHERE product_id=?",(worker_now(),pid))
        c.commit()
    return {"status":"ok","requeued":len(ids)}

def run_batch(limit=5):
    limit=max(1,min(int(limit),8))
    with worker_db() as c:
        rows=[dict(r) for r in c.execute("SELECT * FROM catalog_research_jobs WHERE status IN ('queued','failed') ORDER BY priority DESC,created_at LIMIT ?",(limit,)).fetchall()]
    done=[];failed=[]
    for row in rows:
        pid=row["product_id"]
        try:
            with worker_db() as c:
                c.execute("UPDATE catalog_research_jobs SET status='processing',attempts=attempts+1,updated_at=? WHERE product_id=?",(worker_now(),pid));c.commit()
            x=research_rc3(pid);done.append({"productId":pid,"decision":x["decision"],"confidence":x["confidence"]})
        except Exception as e:
            with worker_db() as c:
                c.execute("UPDATE catalog_research_jobs SET status='failed',last_error=?,updated_at=? WHERE product_id=?",(str(e)[:800],worker_now(),pid));c.commit()
            failed.append({"productId":pid,"error":str(e)})
    return {"status":"ok","processed":len(rows),"done":done,"failed":failed}
