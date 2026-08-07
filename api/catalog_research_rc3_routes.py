from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import HTMLResponse
from services.catalog_research_rc3 import migrate_rc3,stats,research_rc3,requeue,run_batch

router=APIRouter()

@router.get("/catalog-research/rc3/stats")
def public_stats():
    migrate_rc3()
    return stats()

@router.get("/api/catalog-research/rc3/stats")
def api_stats():
    migrate_rc3()
    return stats()

@router.post("/api/catalog-research/rc3/requeue")
def api_requeue():
    return requeue()

@router.post("/api/catalog-research/rc3/run")
def api_run(limit:int=Query(default=5,ge=1,le=8)):
    return run_batch(limit)

@router.post("/api/catalog-research/rc3/run/{product_id}")
def api_one(product_id:str):
    try:
        return research_rc3(product_id)
    except Exception as e:
        raise HTTPException(status_code=400,detail=str(e))

def _page_html():
    return """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Elegance Research RC3</title>
<style>:root{--i:#66dcfb;--p:#091721;--l:#24566b;--g:#63ef9b;--y:#ffd166}*{box-sizing:border-box}body{margin:0;background:#02080c;color:#f6fbff;font:16px system-ui}main{max-width:1080px;margin:auto;padding:24px}h1{font:50px cursive;color:var(--i);margin:0}.p{background:var(--p);border:1px solid #24566b88;border-radius:18px;padding:20px;margin:16px 0}.s{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.c{border:1px solid var(--l);padding:14px;border-radius:12px}.n{font-size:28px;color:var(--i);font-weight:900}button,a{background:#0785ae;color:#fff;border:0;border-radius:10px;padding:12px 15px;font-weight:800;text-decoration:none;cursor:pointer}.row{display:flex;gap:9px;flex-wrap:wrap}.item{border-top:1px solid #1d4050;padding:13px 0}.ok{color:var(--g)}.warn{color:var(--y)}</style></head>
<body><main><h1>elegance</h1><h2>Catalog Research Worker · RC3</h2>
<p>Reverse visual → Base Maestra → referencias externas → comparación visual → Auditoría.</p>
<div class="row"><a href="/catalog-research">← RC2</a><a href="/catalog-intelligence">Auditoría</a><a href="/catalog-admin">Catálogo</a></div>
<section class="p"><div class="s"><div class="c">Consultas visuales<div id="e" class="n">—</div></div><div class="c">Referencias externas<div id="r" class="n">—</div></div><div class="c">Referencias útiles<div id="u" class="n">—</div></div></div>
<p><button onclick="rq()">1. Reencolar ambiguos</button> <button onclick="run5()">2. Investigar 5 con RC3</button> <span id="m"></span></p></section>
<section class="p"><h2>Resultado</h2><div id="list">Sin ejecutar.</div></section>
<script>
const pct=x=>Math.round((x||0)*100);
async function api(u,o={}){let r=await fetch(u,o),t=await r.text(),j={};try{j=JSON.parse(t)}catch{}if(!r.ok)throw Error(j.detail||"Error "+r.status);return j}
async function load(){try{let x=await api("/catalog-research/rc3/stats");e.textContent=x.providerEvents;r.textContent=x.externalRefs;u.textContent=x.usefulRefs}catch(err){m.innerHTML='<span class="warn">No se pudieron cargar estadísticas: '+err.message+'</span>'}}
async function rq(){try{let x=await api("/api/catalog-research/rc3/requeue",{method:"POST"});m.textContent=x.requeued+" ambiguos reencolados"}catch(err){m.textContent=err.message}}
async function run5(){m.textContent="Investigando visualmente…";try{let x=await api("/api/catalog-research/rc3/run?limit=5",{method:"POST"});m.textContent="Procesados "+x.processed+"; fallidos "+(x.failed||[]).length;list.innerHTML=(x.done||[]).map(i=>'<div class="item"><b>'+i.productId+'</b> · '+i.decision+' <span class="ok">'+pct(i.confidence)+'%</span></div>').join("")||"Sin resultados.";load()}catch(err){m.textContent=err.message}}
load()
</script></main></body></html>"""

@router.get("/catalog-research/rc3",response_class=HTMLResponse)
def page():
    return HTMLResponse(_page_html())

@router.get("/catalog/rc3-research",response_class=HTMLResponse)
def page_alias():
    return HTMLResponse(_page_html())
