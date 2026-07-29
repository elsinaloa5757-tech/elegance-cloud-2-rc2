from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import HTMLResponse

from services.fashion_library import (
    category_tree, changes_since, initialize_library, list_brands,
    search, stats, upsert_entity,
)

router = APIRouter(prefix="/api/library", tags=["Biblioteca Mundial de Moda"])

@router.get("/health")
def library_health() -> dict:
    return {"status":"ok", **stats(), "paid_api_required":False, "update_mode":"incremental"}

@router.get("/stats")
def library_stats() -> dict:
    return {"status":"ok", **stats()}

@router.get("/categories")
def library_categories() -> dict:
    return {"status":"ok", "categories":category_tree()}

@router.get("/brands")
def library_brands(category: str="", q: str="", limit: int=100, offset: int=0) -> dict:
    return {"status":"ok", **list_brands(category=category,q=q,limit=limit,offset=offset)}

@router.get("/search")
def library_search(q: str=Query(...,min_length=1), entity: str="all", limit: int=30, offset: int=0) -> dict:
    return {"status":"ok", **search(q,entity=entity,limit=limit,offset=offset)}

@router.get("/changes")
def library_changes(since_id: int=0, limit: int=500) -> dict:
    return {"status":"ok", **changes_since(since_id,limit)}

@router.post("/{entity}")
def library_upsert(entity: str, payload: dict=Body(...)) -> dict:
    try:
        return {"status":"ok", "entity":entity, "item":upsert_entity(entity,payload)}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.post("/maintenance/initialize")
def library_initialize() -> dict:
    return {"status":"ok", "message":"Biblioteca verificada e inicializada sin borrar datos existentes.", **initialize_library()}

public_router = APIRouter()

@public_router.get("/library", response_class=HTMLResponse)
def library_page() -> HTMLResponse:
    return HTMLResponse("""<!doctype html><html lang='es'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Biblioteca Mundial de Moda</title><style>body{margin:0;background:#05090d;color:#eef8ff;font-family:system-ui}.wrap{max-width:1100px;margin:auto;padding:28px}h1{font-family:cursive;color:#72dcff;font-size:44px;margin:0}.card{background:#0b141c;border:1px solid #2f6d8955;border-radius:18px;padding:18px;margin-top:18px}input,select{background:#071019;color:white;border:1px solid #3b7894;border-radius:12px;padding:12px;font-size:16px}input{width:min(560px,70%)}button{padding:12px 18px;border:0;border-radius:12px;background:#70d9ff;color:#041017;font-weight:800}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.item{padding:13px;background:#071019;border-radius:12px}.muted{color:#9db1bd}a{color:#72dcff}</style><div class='wrap'><h1>elegance</h1><h2>Biblioteca Mundial de Moda</h2><p class='muted'>Módulo local, universal, incremental y sin costo mensual obligatorio.</p><div class='card' id='stats'>Cargando estadísticas…</div><div class='card'><input id='q' placeholder='Buscar marca, familia o modelo'><select id='entity'><option value='all'>Todo</option><option value='brand'>Marcas</option><option value='family'>Familias</option><option value='model'>Modelos</option></select> <button onclick='go()'>Buscar</button><div id='results' class='grid' style='margin-top:16px'></div></div><div class='card'><h3>Categorías universales</h3><div id='cats' class='grid'></div></div></div><script>async function load(){let s=await fetch('/api/library/stats').then(r=>r.json());stats.innerHTML=`<b>Versión:</b> ${s.library_version} · <b>Categorías:</b> ${s.categories} · <b>Marcas:</b> ${s.brands} · <b>Familias:</b> ${s.families} · <b>Modelos:</b> ${s.models}`;let c=await fetch('/api/library/categories').then(r=>r.json());cats.innerHTML=c.categories.map(x=>`<div class='item'><b>${x.name}</b><div class='muted'>${x.children.map(y=>y.name).join(' · ')}</div></div>`).join('')}async function go(){let v=q.value.trim();if(!v)return;let d=await fetch('/api/library/search?q='+encodeURIComponent(v)+'&entity='+entity.value).then(r=>r.json());results.innerHTML=d.items.map(x=>`<div class='item'><b>${x.name}</b><div class='muted'>${x.entity_type} ${x.brand? '· '+x.brand:''} ${x.family?'· '+x.family:''}</div></div>`).join('')||'<p>Sin resultados.</p>'}q.addEventListener('keydown',e=>{if(e.key==='Enter')go()});load()</script></html>""")
