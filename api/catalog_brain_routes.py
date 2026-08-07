from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import HTMLResponse,JSONResponse
from services.catalog_brain import (
    migrate_catalog_brain,stats,build_candidates,prepare_research_packets,
    research_export,research_packet,cluster_duplicates,auto_propose,auto_propose_all
)
router=APIRouter()

@router.get("/api/catalog-brain/stats")
def api_stats():migrate_catalog_brain();return stats()

@router.post("/api/catalog-brain/build")
def api_build():return build_candidates()

@router.post("/api/catalog-brain/prepare-research")
def api_prepare():return prepare_research_packets()

@router.post("/api/catalog-brain/cluster-duplicates")
def api_clusters():return cluster_duplicates()

@router.post("/api/catalog-brain/auto-propose")
def api_auto_all():return auto_propose_all()

@router.post("/api/catalog-brain/auto-propose/{product_id}")
def api_auto_one(product_id:str):
    try:return auto_propose(product_id)
    except Exception as e:raise HTTPException(status_code=400,detail=str(e))

@router.get("/api/catalog-brain/research")
def api_research(offset:int=Query(default=0,ge=0),limit:int=Query(default=200,ge=1,le=500),onlyMissing:bool=Query(default=True)):
    return JSONResponse(research_export(offset,limit,onlyMissing))

@router.get("/api/catalog-brain/research/{product_id}")
def api_research_one(product_id:str):
    p=research_packet(product_id)
    if not p:raise HTTPException(status_code=404,detail="Paquete no encontrado.")
    return JSONResponse(p)

@router.get("/catalog-brain",response_class=HTMLResponse)
def page():
 return HTMLResponse(r"""<!doctype html><html lang=es><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Elegance Catalog Brain</title>
<style>:root{--i:#66dcfb;--p:#091721;--l:#24566b;--g:#63ef9b}*{box-sizing:border-box}body{margin:0;background:#02080c;color:#f5fbff;font:16px system-ui}main{max-width:1100px;margin:auto;padding:24px}h1{font:52px cursive;color:var(--i);margin:0}.p{background:var(--p);border:1px solid #24566b88;border-radius:20px;padding:20px;margin:16px 0}.s{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.c{border:1px solid var(--l);padding:14px;border-radius:13px}.n{font-size:28px;font-weight:900;color:var(--i)}button,a{background:#0785ae;color:white;border:0;border-radius:10px;padding:12px 15px;font-weight:800;text-decoration:none;cursor:pointer}.row{display:flex;gap:9px;flex-wrap:wrap}.ok{color:var(--g)}@media(max-width:700px){.s{grid-template-columns:1fr 1fr}}</style></head><body><main>
<h1>elegance</h1><h2>Catalog Brain</h2><p>Normalización, candidatos internos, duplicados y paquetes de investigación para enriquecer el catálogo real.</p>
<div class=row><a href=/catalog-intelligence>← Auditoría Maestra</a><a href=/catalog-admin>Catálogo</a><a href=/api/catalog-brain/research>Ver investigación JSON</a></div>
<section class=p><div class=s><div class=c>Candidatos<div id=cand class=n>—</div></div><div class=c>Fuertes<div id=strong class=n>—</div></div><div class=c>Paquetes<div id=pack class=n>—</div></div><div class=c>Clusters<div id=clus class=n>—</div></div></div></section>
<section class=p><h2>Preparación automática</h2><p><button onclick=build()>1. Construir candidatos</button> <button onclick=propose()>2. Crear propuestas seguras</button> <button onclick=research()>3. Preparar investigación</button> <button onclick=clusters()>4. Detectar duplicados</button></p><p id=msg></p></section>
<section class=p><h2>Qué hace esta etapa</h2><p>Usa la Base Maestra existente para sugerir nombres normalizados y crea un paquete con imágenes, campos faltantes y consultas de investigación por cada producto. Las propuestas internas no se autoaplican al catálogo real; pasan primero por Auditoría Maestra.</p></section>
<script>async function api(u,o={}){let r=await fetch(u,o),t=await r.text(),j={};try{j=JSON.parse(t)}catch{}if(!r.ok)throw Error(j.detail||'Error '+r.status);return j}
async function load(){let x=await api('/api/catalog-brain/stats');cand.textContent=x.candidates;strong.textContent=x.strongCandidates;pack.textContent=x.researchPackets;clus.textContent=x.clusters}
async function build(){msg.textContent='Construyendo candidatos…';let x=await api('/api/catalog-brain/build',{method:'POST'});msg.textContent=`${x.candidatesCreated} candidatos creados`;load()}
async function propose(){msg.textContent='Generando propuestas…';let x=await api('/api/catalog-brain/auto-propose',{method:'POST'});msg.textContent=`${x.proposals} propuestas seguras creadas`;load()}
async function research(){msg.textContent='Preparando investigación…';let x=await api('/api/catalog-brain/prepare-research',{method:'POST'});msg.textContent=`${x.packets} paquetes preparados`;load()}
async function clusters(){msg.textContent='Agrupando…';let x=await api('/api/catalog-brain/cluster-duplicates',{method:'POST'});msg.textContent=`${x.clusters} grupos potencialmente duplicados`;load()}load();</script></main></body></html>""")
