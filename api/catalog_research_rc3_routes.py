from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import HTMLResponse,RedirectResponse
from services.catalog_research_rc3 import migrate_rc3,stats,research_rc3,requeue,run_batch
from services.catalog_research_worker import list_results

router=APIRouter()

@router.get("/api/catalog-research/rc3/stats")
def api_stats():
    migrate_rc3()
    return stats()

@router.get("/api/catalog-research/rc3/results")
def api_results(
    status:str=Query(default=""),
    offset:int=Query(default=0,ge=0),
    limit:int=Query(default=50,ge=1,le=200)
):
    return list_results(status,offset,limit)

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
    return """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Elegance Research Center RC3</title>
<style>
:root{--ice:#66dcfb;--panel:#091721;--line:#24566b;--green:#63ef9b;--yellow:#ffd166;--red:#ff737d}
*{box-sizing:border-box}
body{margin:0;background:#02080c;color:#f6fbff;font:15px system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1180px;margin:auto;padding:26px}
h1{font:52px cursive;color:var(--ice);margin:0 0 4px}
h2{margin:8px 0 4px}.muted{color:#9bc4d5}
.panel{background:var(--panel);border:1px solid #24566b88;border-radius:18px;padding:20px;margin:16px 0}
.stats{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
.card{border:1px solid var(--line);padding:13px;border-radius:12px;min-width:0}
.num{font-size:27px;color:var(--ice);font-weight:900}
.row{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
button,a{background:#0785ae;color:#fff;border:0;border-radius:10px;padding:11px 14px;font-weight:800;text-decoration:none;cursor:pointer}
button.secondary{background:#173847}
.item{border-top:1px solid #1d4050;padding:13px 0}
.score{float:right;font-size:19px;font-weight:900;color:var(--green)}
.small{font-size:12px;color:#99bdcb}
.ready{color:var(--green)}.review{color:var(--yellow)}.bad{color:var(--red)}
.progress{height:10px;background:#102b37;border-radius:999px;overflow:hidden;margin-top:8px}
.progress>div{height:100%;width:0;background:var(--ice);transition:width .3s}
#msg{min-height:22px}
@media(max-width:900px){.stats{grid-template-columns:repeat(3,1fr)}}
@media(max-width:600px){.stats{grid-template-columns:1fr 1fr}main{padding:15px}}
</style>
</head>
<body>
<main>
<h1>elegance</h1>
<h2>Research Center · RC3 Final</h2>
<p class="muted">Consola privada: reverse visual → Base Maestra → referencias externas → comparación visual → Auditoría.</p>

<div class="row">
<a href="/catalog-research">RC2</a>
<a href="/catalog-brain">Catalog Brain</a>
<a href="/catalog-intelligence">Auditoría</a>
<a href="/catalog-admin">Catálogo</a>
</div>

<section class="panel">
<div class="stats">
<div class="card">Consultas visuales<div id="events" class="num">—</div></div>
<div class="card">Referencias externas<div id="refs" class="num">—</div></div>
<div class="card">Referencias útiles<div id="useful" class="num">—</div></div>
<div class="card">Listos<div id="ready" class="num">—</div></div>
<div class="card">Revisión<div id="review" class="num">—</div></div>
<div class="card">Fallidos<div id="failed" class="num">—</div></div>
</div>
<div class="progress"><div id="bar"></div></div>
<p id="msg"></p>
<div class="row">
<button onclick="requeueWeak()">1. Reencolar ambiguos</button>
<button onclick="runBatch(5)">2. Investigar 5</button>
<button class="secondary" onclick="runBatch(8)">Investigar 8</button>
<button class="secondary" onclick="refreshAll()">Actualizar</button>
</div>
</section>

<section class="panel">
<h2>Resultados RC3</h2>
<div class="row">
<button class="secondary" onclick="loadResults('')">Todos</button>
<button class="secondary" onclick="loadResults('ready')">Listos</button>
<button class="secondary" onclick="loadResults('review')">Revisión</button>
</div>
<div id="results">Cargando…</div>
</section>

<script>
const pct=x=>Math.round((Number(x)||0)*100);

async function api(url,options={}){
  const r=await fetch(url,{credentials:"same-origin",...options});
  let txt=await r.text(), data={};
  try{data=JSON.parse(txt)}catch{}
  if(r.status===401){
    location.href="/login?next="+encodeURIComponent(location.pathname);
    throw new Error("Sesión requerida");
  }
  if(!r.ok) throw new Error(data.detail||("Error "+r.status));
  return data;
}

async function loadStats(){
  const x=await api("/api/catalog-research/rc3/stats");
  events.textContent=x.providerEvents??0;
  refs.textContent=x.externalRefs??0;
  useful.textContent=x.usefulRefs??0;

  const y=await api("/api/catalog-research/stats");
  ready.textContent=y.ready??0;
  review.textContent=y.review??0;
  failed.textContent=y.failed??0;

  const total=(y.queued??0)+(y.processing??0)+(y.done??0);
  bar.style.width=total?Math.round((y.done??0)*100/total)+"%":"0%";
}

async function requeueWeak(){
  msg.textContent="Reencolando casos ambiguos…";
  try{
    const x=await api("/api/catalog-research/rc3/requeue",{method:"POST"});
    msg.textContent=(x.requeued??0)+" casos reencolados.";
    await refreshAll();
  }catch(e){msg.textContent=e.message}
}

async function runBatch(n){
  msg.textContent="RC3 está investigando "+n+" productos. Puede tardar por la búsqueda visual externa…";
  try{
    const x=await api("/api/catalog-research/rc3/run?limit="+n,{method:"POST"});
    msg.textContent="Procesados "+(x.processed??0)+" · fallidos "+((x.failed||[]).length);
    await refreshAll();
  }catch(e){msg.textContent=e.message}
}

function labelClass(s){
  if(s==="ready") return "ready";
  if(s==="review") return "review";
  return "bad";
}

async function loadResults(status=""){
  const x=await api("/api/catalog-research/rc3/results?limit=80&status="+encodeURIComponent(status));
  results.innerHTML=(x.items||[]).map(i=>{
    const p=i.proposal||{};
    const name=[p.brand,p.model,p.colorway].filter(Boolean).join(" ")||"Sin resolver";
    return `<div class="item">
      <span class="score">${pct(i.confidence)}%</span>
      <b>${i.productId}</b> · <span class="${labelClass(i.status)}">${i.status}</span>
      <div>${name}</div>
      <div class="small">Margen ${pct(i.margin)}%</div>
    </div>`;
  }).join("")||"Sin resultados.";
}

async function refreshAll(){
  await loadStats();
  await loadResults("");
}

refreshAll().catch(e=>msg.textContent=e.message);
</script>
</main>
</body>
</html>"""

@router.get("/research-center/rc3",response_class=HTMLResponse)
def private_page():
    return HTMLResponse(_page_html())

@router.get("/catalog-research/rc3")
def old_page_redirect():
    return RedirectResponse("/research-center/rc3",status_code=307)

@router.get("/catalog/rc3-research")
def old_alias_redirect():
    return RedirectResponse("/research-center/rc3",status_code=307)
