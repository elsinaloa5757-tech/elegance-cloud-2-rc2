from __future__ import annotations
import inspect, json, re, sqlite3
from datetime import datetime, timezone
from difflib import SequenceMatcher
from services import state_store
from services.public_catalog import sync_products
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
            for nested in ("proposal","data","product","fields","applied"):
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
    try: sync_products(); synced=True
    except Exception: synced=False
    return {'status':'ok','productId':product_id,'synced':synced,'learningSaved':bool(canonical),'similarUpdated':propagated,'learners':_notify(product_id) if product_id else []}
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
