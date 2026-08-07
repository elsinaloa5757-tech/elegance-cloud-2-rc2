from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import HTMLResponse
from services.catalog_research_worker import (
    migrate_research_worker,stats,build_jobs,run_batch,research_product,result,list_results
)
router=APIRouter()

@router.get("/api/catalog-research/stats")
def api_stats():migrate_research_worker();return stats()

@router.post("/api/catalog-research/build-jobs")
def api_jobs():return build_jobs()

@router.post("/api/catalog-research/run")
def api_run(limit:int=Query(default=5,ge=1,le=50),web:bool=Query(default=True)):
    return run_batch(limit,web)

@router.post("/api/catalog-research/run/{product_id}")
def api_one(product_id:str,web:bool=Query(default=True)):
    try:return research_product(product_id,web)
    except Exception as e:raise HTTPException(status_code=400,detail=str(e))

@router.get("/api/catalog-research/result/{product_id}")
def api_result(product_id:str):
    r=result(product_id)
    if not r:raise HTTPException(status_code=404,detail="Sin investigación todavía.")
    return r

@router.get("/api/catalog-research/results")
def api_results(status:str=Query(default=""),offset:int=Query(default=0,ge=0),limit:int=Query(default=50,ge=1,le=200)):
    return list_results(status,offset,limit)

@router.get("/catalog-research",response_class=HTMLResponse)
def page():
 return HTMLResponse(r"""<!doctype html><html lang=es><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Elegance Catalog Research Worker</title>
<style>:root{--i:#66dcfb;--p:#091721;--l:#24566b;--g:#63ef9b;--y:#ffd166;--r:#ff737d}*{box-sizing:border-box}body{margin:0;background:#02080c;color:#f5fbff;font:15px system-ui}main{max-width:1120px;margin:auto;padding:24px}h1{font:50px cursive;color:var(--i);margin:0}.p{background:var(--p);border:1px solid #24566b88;border-radius:18px;padding:18px;margin:15px 0}.s{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}.c{border:1px solid var(--l);padding:12px;border-radius:12px}.n{font-size:25px;font-weight:900;color:var(--i)}button,a{background:#0785ae;color:#fff;border:0;border-radius:9px;padding:11px 14px;font-weight:800;text-decoration:none;cursor:pointer}.row{display:flex;gap:8px;flex-wrap:wrap}.item{padding:13px 0;border-top:1px solid #1d4050}.score{float:right;color:var(--g);font-weight:900;font-size:19px}.small{font-size:12px;color:#a8cbd9}@media(max-width:800px){.s{grid-template-columns:1fr 1fr}}</style></head><body><main>
<h1>elegance</h1><h2>Catalog Research Worker</h2><p>Imagen primero → Vision Enterprise → Base Maestra → corroboración web → Auditoría Maestra.</p>
<div class=row><a href=/catalog-brain>← Catalog Brain</a><a href=/catalog-intelligence>Auditoría Maestra</a><a href=/catalog-admin>Catálogo</a></div>
<section class=p><div class=s><div class=c>En cola<div id=q class=n>—</div></div><div class=c>Procesando<div id=p class=n>—</div></div><div class=c>Terminados<div id=d class=n>—</div></div><div class=c>Revisión<div id=r class=n>—</div></div><div class=c>Listos<div id=ready class=n>—</div></div><div class=c>Fallidos<div id=f class=n>—</div></div></div>
<p><button onclick=jobs()>1. Crear cola de 180</button> <button onclick=run(5)>2. Investigar 5</button> <button onclick=run(20)>Investigar 20</button> <span id=msg></span></p></section>
<section class=p><h2>Resultados</h2><div class=row><button onclick="loadResults('')">Todos</button><button onclick="loadResults('ready')">Listos</button><button onclick="loadResults('review')">Revisión</button></div><div id=list></div></section>
<script>const pct=v=>Math.round((v||0)*100);async function api(u,o={}){let x=await fetch(u,o),t=await x.text(),j={};try{j=JSON.parse(t)}catch{}if(!x.ok)throw Error(j.detail||'Error '+x.status);return j}
async function load(){let x=await api('/api/catalog-research/stats');q.textContent=x.queued;p.textContent=x.processing;d.textContent=x.done;r.textContent=x.review;ready.textContent=x.ready;f.textContent=x.failed}
async function jobs(){msg.textContent='Creando cola…';let x=await api('/api/catalog-research/build-jobs',{method:'POST'});msg.textContent=`${x.created} trabajos nuevos`;load()}
async function run(n){msg.textContent=`Investigando ${n}… puede tardar.`;try{let x=await api('/api/catalog-research/run?limit='+n+'&web=true',{method:'POST'});msg.textContent=`Procesados ${x.processed}; fallidos ${x.failed.length}`;load();loadResults('')}catch(e){msg.textContent=e.message}}
async function loadResults(st){let x=await api('/api/catalog-research/results?limit=60&status='+encodeURIComponent(st));list.innerHTML=x.items.map(i=>`<div class=item><span class=score>${pct(i.confidence)}%</span><b>${i.productId}</b> · ${i.status}<div>${[i.proposal.brand,i.proposal.model,i.proposal.colorway].filter(Boolean).join(' ')||'Sin resolver'}</div><div class=small>Margen ${pct(i.margin)}%${i.sources.length?' · '+i.sources.map(s=>s.title).join(' | '):''}</div></div>`).join('')||'Sin resultados.'}
load();loadResults('');</script></main></body></html>""")
