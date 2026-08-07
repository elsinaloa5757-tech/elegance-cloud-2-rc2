from __future__ import annotations
import inspect, json, re, sqlite3, threading, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from difflib import SequenceMatcher
from services import state_store
from services.public_catalog import sync_products, update_publication
from services.shoe_phase4 import remember_phase4, recognize_phase4
FIELDS=("title","brand","family","model","colorway","category","subcategory","color","sizes","description","keywords")
def _now(): return datetime.now(timezone.utc).isoformat()
def _norm(v): return re.sub(r"[^a-z0-9]+"," ",str(v or "").lower()).strip()
def _db():
    c=sqlite3.connect(state_store.database_path(),timeout=60); c.row_factory=sqlite3.Row; return c
def migrate_learning():
    with _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS catalog_confirmed_learning(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          product_id TEXT NOT NULL,
          title TEXT, brand TEXT, family TEXT, model TEXT, colorway TEXT,
          category TEXT, subcategory TEXT, color TEXT,
          snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_catalog_confirmed_learning_product
          ON catalog_confirmed_learning(product_id,created_at);
        """); c.commit()
def _extract_payload(args,kwargs,result):
    merged={}
    for obj in list(args)+list(kwargs.values())+[result]:
        if isinstance(obj,dict):
            for k in FIELDS:
                if obj.get(k) not in (None,"",[],{}): merged[k]=obj.get(k)
            for nested in ("proposal","data","product","fields","applied","after"):
                sub=obj.get(nested)
                if isinstance(sub,dict):
                    for k in FIELDS:
                        if sub.get(k) not in (None,"",[],{}): merged[k]=sub.get(k)
    return merged
def _extract_product_id(args,kwargs,result):
    for k in ("product_id","productId","id"):
        if kwargs.get(k): return str(kwargs[k])
    for obj in args:
        if isinstance(obj,str) and obj.startswith('prd_'): return obj
        if isinstance(obj,dict):
            for k in ("product_id","productId","id"):
                if obj.get(k): return str(obj[k])
    if isinstance(result,dict):
        for k in ("product_id","productId","id"):
            if result.get(k): return str(result[k])
    return ''
def _load_state():
    s=state_store.load_state(); return s if isinstance(s,dict) else {}
def _save_state(state):
    for name in ('save_state','write_state'):
        fn=getattr(state_store,name,None)
        if callable(fn): fn(state); return True
    return False
def _find_product(state,pid):
    for p in state.get('products',[]):
        if isinstance(p,dict) and (str(p.get('id') or '')==pid or str(p.get('product_id') or '')==pid): return p
    return None
def _canonical(p):
    return {k:p.get(k) for k in FIELDS if isinstance(p,dict) and p.get(k) not in (None,"",[],{})}
def _record(pid,data):
    migrate_learning()
    with _db() as c:
        c.execute("""INSERT INTO catalog_confirmed_learning
        (product_id,title,brand,family,model,colorway,category,subcategory,color,snapshot_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (pid,data.get('title'),data.get('brand'),data.get('family'),data.get('model'),data.get('colorway'),
         data.get('category'),data.get('subcategory'),data.get('color'),json.dumps(data,ensure_ascii=False),_now())); c.commit()
def _sim(a,b):
    a=_norm(a); b=_norm(b); return SequenceMatcher(None,a,b).ratio() if a and b else 0.0
def _propagate(state,source,pid):
    changed=0; src_model=source.get('model') or ''; src_family=source.get('family') or ''; src_brand=source.get('brand') or ''
    for p in state.get('products',[]):
        if not isinstance(p,dict) or str(p.get('id') or '')==pid: continue
        model_score=max(_sim(p.get('model'),src_model),_sim(p.get('title'),src_model))
        fam_score=max(_sim(p.get('family'),src_family),_sim(p.get('title'),src_family))
        brand_ok=(not p.get('brand')) or (_norm(p.get('brand'))==_norm(src_brand))
        if brand_ok and model_score>=0.92 and (fam_score>=0.70 or not src_family):
            for k in ('brand','family','model','category','subcategory'):
                if source.get(k) and (not p.get(k) or _norm(p.get(k)) in ('calzado','tenis')): p[k]=source[k]
            changed+=1
    return changed
def _notify(pid):
    called=[]
    for modname in ('services.shoe_intelligence','services.shoe_phase6_enterprise','services.catalog_brain'):
        try: mod=__import__(modname,fromlist=['*'])
        except Exception: continue
        for name in ('learn_product','learn_from_product','learn_from_catalog','learn_catalog'):
            fn=getattr(mod,name,None)
            if not callable(fn): continue
            try:
                sig=inspect.signature(fn)
                req=[p for p in sig.parameters.values() if p.default is inspect._empty and p.kind in (p.POSITIONAL_ONLY,p.POSITIONAL_OR_KEYWORD)]
                if len(req)==0: fn()
                elif len(req)==1: fn(pid)
                else: continue
                called.append(modname+'.'+name); break
            except Exception: continue
    return called
def sync_and_learn(product_id='',payload=None):
    migrate_learning(); state=_load_state(); p=_find_product(state,product_id) if product_id else None
    payload=payload if isinstance(payload,dict) else {}
    if p is not None:
        for k,v in payload.items():
            if k in FIELDS and v not in (None,"",[],{}): p[k]=v
    canonical=_canonical(p) if p else dict(payload)
    if product_id and canonical: _record(product_id,canonical)
    propagated=0
    if p is not None and canonical:
        propagated=_propagate(state,canonical,product_id); _save_state(state)
    public_updated=False
    try:
        sync_products()
        public_payload={}
        if canonical.get('title'):
            public_payload['title']=str(canonical['title']).strip()
        if canonical.get('description'):
            public_payload['description']=str(canonical['description']).strip()
        if product_id and public_payload:
            update_publication(product_id,public_payload)
            public_updated=True
        synced=True
    except Exception:
        synced=False
    visualQueued=start_visual_propagation(product_id) if product_id and canonical else False
    return {'status':'ok','productId':product_id,'synced':synced,'publicUpdated':public_updated,'learningSaved':bool(canonical),'similarUpdated':propagated,'visualPropagationQueued':visualQueued,'learners':_notify(product_id) if product_id else []}
def wrap_apply_function(original):
    if getattr(original,'_elegance_apply_learn_wrapped',False): return original
    def wrapped(*args,**kwargs):
        result=original(*args,**kwargs)
        try:
            extra=sync_and_learn(_extract_product_id(args,kwargs,result),_extract_payload(args,kwargs,result))
            if isinstance(result,dict): result={**result,'applyAndLearn':extra}
        except Exception as e:
            if isinstance(result,dict): result={**result,'applyAndLearnWarning':str(e)}
        return result
    wrapped.__name__=getattr(original,'__name__','apply_and_learn'); wrapped.__doc__=getattr(original,'__doc__',None); wrapped._elegance_apply_learn_wrapped=True
    return wrapped

# ELEGANCE_VISUAL_PROPAGATION_V2
_VISUAL_LOCK=threading.Lock()
_VISUAL_THREADS={}

def _image_candidates(p):
    out=[]
    for k in ("catalogImage","image","imagePath"):
        v=p.get(k) if isinstance(p,dict) else None
        if isinstance(v,str) and v.strip(): out.append(v.strip())
    for k in ("originalImages","images","editedImages","approvedStudioImages"):
        v=p.get(k) if isinstance(p,dict) else None
        if isinstance(v,list):
            for it in v:
                x=it.get("path") if isinstance(it,dict) else it
                if isinstance(x,str) and x.strip(): out.append(x.strip())
    seen=[]
    for x in out:
        if x not in seen: seen.append(x)
    return seen

def _read_image_bytes(ref):
    ref=str(ref or "").strip()
    if not ref:return b""
    try:
        if ref.startswith(("http://","https://")):
            req=urllib.request.Request(ref,headers={"User-Agent":"EleganceVision/1.0"})
            with urllib.request.urlopen(req,timeout=18) as r:
                return r.read(15*1024*1024)
        p=Path(ref)
        if p.exists() and p.is_file():
            return p.read_bytes()
    except Exception:
        return b""
    return b""

def _identity(source):
    return {
        "title":str(source.get("title") or source.get("name") or "").strip(),
        "brand":str(source.get("brand") or "").strip(),
        "family":str(source.get("family") or "").strip(),
        "model":str(source.get("model") or "").strip(),
        "colorway":str(source.get("colorway") or "").strip(),
        "category":str(source.get("category") or source.get("universalCategory") or "").strip(),
        "subcategory":str(source.get("subcategory") or "").strip(),
        "color":str(source.get("color") or source.get("primaryColor") or "").strip(),
    }

def _visual_job(source_pid):
    try:
        state=_load_state()
        source=_find_product(state,source_pid)
        if not source:return
        ident=_identity(source)
        if not ident["brand"] or not ident["model"]:return
        refs=_image_candidates(source)
        if not refs:return
        data=_read_image_bytes(refs[0])
        if not data:return

        try:
            remember_phase4(data,ident["brand"],ident["model"],source_product_id=source_pid,image_ref=refs[0])
        except Exception:
            pass

        changed_ids=[]
        exact_ids=[]
        for p in state.get("products",[]):
            if not isinstance(p,dict):continue
            pid=str(p.get("id") or "")
            if not pid or pid==source_pid:continue
            imgs=_image_candidates(p)
            if not imgs:continue
            b=_read_image_bytes(imgs[0])
            if not b:continue
            try:
                rec=recognize_phase4(b,limit=3)
                items=rec.get("items") or []
                if not items:continue
                top=items[0]
                score=float(top.get("confidence") or 0)
                if _norm(top.get("brand"))!=_norm(ident["brand"]) or _norm(top.get("model"))!=_norm(ident["model"]):
                    continue
                ev=top.get("evidence") or {}
                color=float(ev.get("color") or 0)
                regions=float(ev.get("regions") or 0)
                keypoints=float(ev.get("keypoints") or 0)

                if score>=0.76 and (regions>=0.72 or keypoints>=0.28):
                    for k in ("brand","family","model","category","subcategory"):
                        if ident.get(k):
                            p[k]=ident[k]
                    changed_ids.append(pid)

                    if score>=0.86 and color>=0.88 and regions>=0.82:
                        if ident.get("title"):
                            p["title"]=ident["title"]
                            p["name"]=ident["title"]
                        if ident.get("colorway"):p["colorway"]=ident["colorway"]
                        if ident.get("color"):p["color"]=ident["color"]
                        exact_ids.append(pid)
            except Exception:
                continue

        if changed_ids or exact_ids:
            _save_state(state)
            try:sync_products()
            except Exception:pass
            for pid in exact_ids:
                try:update_publication(pid,{"title":ident["title"]})
                except Exception:pass

        try:
            with _db() as c:
                c.execute("CREATE TABLE IF NOT EXISTS catalog_visual_propagation_log(id INTEGER PRIMARY KEY AUTOINCREMENT,source_product_id TEXT,base_matches INTEGER,exact_matches INTEGER,created_at TEXT)")
                c.execute("INSERT INTO catalog_visual_propagation_log(source_product_id,base_matches,exact_matches,created_at) VALUES(?,?,?,?)",
                          (source_pid,len(set(changed_ids)),len(set(exact_ids)),_now()))
                c.commit()
        except Exception:pass
    finally:
        with _VISUAL_LOCK:
            _VISUAL_THREADS.pop(source_pid,None)

def start_visual_propagation(source_pid):
    source_pid=str(source_pid or "")
    if not source_pid:return False
    with _VISUAL_LOCK:
        t=_VISUAL_THREADS.get(source_pid)
        if t and t.is_alive():return False
        t=threading.Thread(target=_visual_job,args=(source_pid,),name="elegance-visual-"+source_pid[-6:],daemon=True)
        _VISUAL_THREADS[source_pid]=t
        t.start()
    return True
