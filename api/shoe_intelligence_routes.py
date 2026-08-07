from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from services.shoe_intelligence import learn_from_catalog, migrate_shoe_intelligence, search_candidates, stats, upsert_model

router = APIRouter()


@router.get("/api/shoe-intelligence/stats")
def shoe_intelligence_stats():
    migrate_shoe_intelligence()
    return stats()


@router.get("/api/shoe-intelligence/search")
def shoe_intelligence_search(q: str = Query(default=""), brand: str = Query(default=""), limit: int = Query(default=12, ge=1, le=50)):
    return search_candidates(q, brand=brand, limit=limit)


@router.post("/api/shoe-intelligence/learn-catalog")
def shoe_intelligence_learn_catalog():
    return learn_from_catalog()


@router.post("/api/shoe-intelligence/models")
def shoe_intelligence_upsert(payload: dict):
    try:
        return upsert_model(payload, source="manual")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/shoe-intelligence", response_class=HTMLResponse)
def shoe_intelligence_page():
    return HTMLResponse(r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Elegance Shoe Intelligence</title>
<style>
:root{--ice:#66dcfb;--panel:#091721;--line:#23566c}*{box-sizing:border-box}body{margin:0;background:#02080c;color:#f2fbff;font:16px system-ui}
main{max-width:1100px;margin:auto;padding:24px}h1{font:52px cursive;color:var(--ice);margin:0}.panel{background:var(--panel);border:1px solid #22566c80;border-radius:20px;padding:20px;margin:16px 0}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.stat{padding:18px;border:1px solid var(--line);border-radius:16px}.n{font-size:34px;font-weight:900;color:var(--ice)}
.row{display:flex;gap:10px;flex-wrap:wrap}input{flex:1;min-width:220px;background:#031018;color:white;border:1px solid var(--line);padding:13px;border-radius:11px}
button,a{background:#0785ae;color:white;border:0;border-radius:11px;padding:12px 16px;font-weight:800;text-decoration:none;cursor:pointer}.result{padding:14px;border-top:1px solid #1f4353}
small{color:#9ac4d6}.score{float:right;color:#63ef9b;font-weight:900}@media(max-width:650px){.stats{grid-template-columns:1fr}}
</style></head><body><main><h1>elegance</h1><h2>Shoe Intelligence</h2>
<div class="row"><a href="/catalog-admin">← Catálogo</a><a href="/diagnostics">Diagnóstico</a></div>
<section class="panel"><h2>Base Maestra</h2><div class="stats"><div class="stat">Modelos<div id="models" class="n">—</div></div><div class="stat">Marcas<div id="brands" class="n">—</div></div><div class="stat">Aprendidos de tu catálogo<div id="learned" class="n">—</div></div></div>
<p><button onclick="learn()">Aprender del catálogo actual</button></p><div id="learnmsg"></div></section>
<section class="panel"><h2>Buscar candidatos</h2><div class="row"><input id="q" placeholder="Ej. Jordan 4, Samba, 9060, Air Max 95"><input id="brand" placeholder="Marca opcional"><button onclick="searchModels()">Buscar</button></div><div id="results"></div></section>
<script>
async function api(url,opt={}){const r=await fetch(url,opt);const t=await r.text();let j={};try{j=JSON.parse(t)}catch{}if(!r.ok)throw Error(j.detail||`Error ${r.status}`);return j}
async function load(){const s=await api('/api/shoe-intelligence/stats');models.textContent=s.models;brands.textContent=s.brands;learned.textContent=s.learnedFromCatalog}
async function learn(){learnmsg.textContent='Aprendiendo…';try{const x=await api('/api/shoe-intelligence/learn-catalog',{method:'POST'});learnmsg.textContent=`Aprendidos: ${x.learned}. Omitidos: ${x.skipped}.`;await load()}catch(e){learnmsg.textContent=e.message}}
async function searchModels(){const qv=q.value.trim(),bv=brand.value.trim();results.innerHTML='Buscando…';try{const x=await api(`/api/shoe-intelligence/search?q=${encodeURIComponent(qv)}&brand=${encodeURIComponent(bv)}`);results.innerHTML=x.items.map(r=>`<div class=result><span class=score>${Math.round(r.score*100)}%</span><b>${r.brand} ${r.model}</b><br><small>${r.family||''}${r.sku?' · '+r.sku:''}${r.source?' · '+r.source:''}</small></div>`).join('')||'Sin candidatos.'}catch(e){results.textContent=e.message}}
load();
</script></main></body></html>""")
