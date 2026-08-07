from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from services.batch_automation import (
    cancel_job, create_job, delete_file, get_job, list_jobs, merge_groups,
    move_file, regroup_job, retry_job, resolve_batch_media, set_cover, split_group, update_group,
)
from services.scalability_platform import remember

router = APIRouter()


@router.post("/api/integral/batches")
async def create_integral_batch(
    files: Annotated[list[UploadFile], File(...)],
    options_json: Annotated[str, Form()] = "{}",
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="Selecciona al menos una imagen.")
    if len(files) > 500:
        raise HTTPException(status_code=400, detail="Máximo 500 imágenes por lote.")
    try:
        options = json.loads(options_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Opciones JSON inválidas.") from exc

    payload: list[tuple[str, bytes]] = []
    for file in files:
        data = await file.read()
        if data:
            payload.append((file.filename or "producto.jpg", data))
    if not payload:
        raise HTTPException(status_code=400, detail="Las imágenes recibidas están vacías.")
    try:
        return create_job(payload, options)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/integral/batches")
def integral_batches(limit: int = 30) -> dict:
    return {"status": "ok", "jobs": list_jobs(limit)}


@router.get("/api/integral/batches/{job_id}")
def integral_batch(job_id: str) -> dict:
    try:
        return get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Lote no encontrado.") from exc


@router.post("/api/integral/batches/{job_id}/cancel")
def integral_cancel(job_id: str) -> dict:
    return cancel_job(job_id)


@router.post("/api/integral/batches/{job_id}/retry")
def integral_retry(job_id: str) -> dict:
    try:
        return retry_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Lote no encontrado.") from exc


@router.get("/api/integral/media/{job_id}/{kind}/{filename}")
def integral_media(job_id: str, kind: str, filename: str):
    try:
        path = resolve_batch_media(job_id, kind, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Archivo no encontrado.") from exc
    media_type = "image/webp" if path.suffix.lower() == ".webp" else None
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )



@router.post("/api/integral/batches/{job_id}/regroup")
def integral_regroup(job_id: str, payload: dict = {}) -> dict:
    try:
        value = payload.get("similarity")
        return regroup_job(job_id, float(value) if value is not None else None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Lote no encontrado.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/integral/batches/{job_id}/groups/{group_no}")
def integral_update_group(job_id: str, group_no: int, payload: dict) -> dict:
    try:
        return update_group(job_id, group_no, payload)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/integral/batches/{job_id}/groups/{group_no}/cover/{file_id}")
def integral_set_cover(job_id: str, group_no: int, file_id: str) -> dict:
    try:
        return set_cover(job_id, group_no, file_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/integral/batches/{job_id}/move/{file_id}/{target_group}")
def integral_move_file(job_id: str, file_id: str, target_group: int) -> dict:
    try:
        return move_file(job_id, file_id, target_group)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/integral/batches/{job_id}/merge")
def integral_merge(job_id: str, payload: dict) -> dict:
    try:
        return merge_groups(job_id, payload.get("groups") or [], payload.get("targetGroup"))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/integral/batches/{job_id}/split")
def integral_split(job_id: str, payload: dict) -> dict:
    try:
        return split_group(job_id, payload.get("fileIds") or [])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/integral/batches/{job_id}/files/{file_id}/delete")
def integral_delete_file(job_id: str, file_id: str) -> dict:
    try:
        return delete_file(job_id, file_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Fotografía no encontrada.") from exc


@router.post("/api/integral/batches/{job_id}/groups/{group_no}/confirm")
def integral_confirm_group(job_id: str, group_no: int, payload: dict) -> dict:
    brand = str(payload.get("brand") or "").strip()
    model = str(payload.get("model") or "").strip()
    category = str(payload.get("category") or "Calzado").strip()
    subcategory = str(payload.get("subcategory") or "Tenis").strip()
    if not brand or not model:
        raise HTTPException(status_code=400, detail="Confirma marca y modelo antes de aprender.")
    update_group(job_id, group_no, {
        "brand": brand, "model": model, "category": category,
        "subcategory": subcategory, "status": "confirmed",
    })
    job = get_job(job_id)
    group = next((g for g in job.get("groups", []) if int(g.get("group_no") or 0) == group_no), None)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado.")
    cover_id = group.get("cover_file_id")
    cover = next((f for f in job.get("files", []) if f.get("id") == cover_id), None)
    if not cover:
        cover = next((f for f in job.get("files", []) if int(f.get("group_no") or 0) == group_no and f.get("status") == "ready"), None)
    if cover:
        outputs = cover.get("outputs") or {}
        remember({
            "productId": f"batch:{job_id}:{group_no}",
            "title": f"{brand} {model}".strip(),
            "brand": brand,
            "model": model,
            "imageUrl": outputs.get("webpUrl") or outputs.get("thumbnailUrl") or "",
            "exactHash": cover.get("sha256") or "",
            "perceptualHash": cover.get("perceptual_hash") or "",
            "confirmed": True,
        })
    return {"status": "confirmed", "job": get_job(job_id)}


@router.get("/integral-review/{job_id}", response_class=HTMLResponse)
def integral_review_page(job_id: str) -> HTMLResponse:
    return HTMLResponse(r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Revisión de lote | Elegance</title>
<style>
:root{--ice:#68dcfb;--panel:#091620;--line:#2a637c;--danger:#88343d}*{box-sizing:border-box}
body{margin:0;background:#02080c;color:#eefaff;font:16px system-ui}.wrap{max-width:1250px;margin:auto;padding:20px}
h1{font:48px cursive;color:var(--ice);margin:0}.top,.actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
a,button{padding:11px 14px;border-radius:11px;border:1px solid var(--line);background:#087ea4;color:white;font-weight:800;text-decoration:none;cursor:pointer}
button.danger{background:var(--danger)}.summary,.group{background:var(--panel);border:1px solid #277da355;border-radius:20px;padding:18px;margin:14px 0}
.group.confirmed{border-color:#3ee58a}.photos{display:flex;gap:10px;overflow-x:auto;padding:8px 0}.photo{min-width:150px;max-width:150px;background:#051018;border-radius:14px;padding:8px}
.photo img{width:134px;height:134px;object-fit:cover;border-radius:10px}.photo.cover{outline:3px solid var(--ice)}
.photo small{display:block;overflow:hidden;text-overflow:ellipsis}.fields{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:12px 0}
input{width:100%;padding:11px;border:1px solid var(--line);border-radius:10px;background:#061018;color:white}
.badge{display:inline-block;padding:5px 9px;border-radius:999px;background:#123343;margin-right:6px}.muted{color:#9fc2d1}
@media(max-width:800px){.fields{grid-template-columns:1fr 1fr}h1{font-size:38px}}@media(max-width:520px){.fields{grid-template-columns:1fr}}
</style></head><body><main class="wrap"><h1>elegance</h1>
<div class="top"><a href="/integral-upload">← Lotes</a><a href="/catalog-admin">Catálogo</a><a href="/diagnostics">Diagnóstico</a><button onclick="load()">Actualizar</button><button onclick="regroup()">Reagrupar lote</button></div>
<section class="summary"><h2>Revisión visual del lote</h2><div id="summary">Cargando…</div></section>
<div id="groups"></div></main>
<script>
const JOB=location.pathname.split('/').pop(),$=id=>document.getElementById(id);let state=null;
async function api(url,opt={}){const r=await fetch(url,{headers:{'Content-Type':'application/json',...(opt.headers||{})},...opt});const t=await r.text();let j={};try{j=JSON.parse(t)}catch{}if(!r.ok)throw Error(j.detail||`Error ${r.status}`);return j}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function filesFor(g){return (state.files||[]).filter(f=>Number(f.group_no)===Number(g.group_no)&&f.status!=='deleted')}
function render(){
 const groups=state.groups||[], dup=(state.files||[]).filter(f=>['duplicate','near_duplicate'].includes(f.status)).length;
 $('summary').innerHTML=`<span class=badge>${groups.length} grupo(s)</span><span class=badge>${state.total_files||0} imágenes</span><span class=badge>${dup} duplicado(s)</span><span class=badge>${state.status}</span>`;
 $('groups').innerHTML=groups.map(g=>{const fs=filesFor(g),confirmed=g.status==='confirmed';return `<section class="group ${confirmed?'confirmed':''}" id="g${g.group_no}">
 <h2>Grupo ${g.group_no} <span class=muted>· ${fs.length} foto(s) · confianza de agrupación ${Math.round(Number(g.confidence||0)*100)}%</span></h2>
 <p class=muted>${esc(g.explanation||'')}</p><div class=photos>${fs.map(f=>{const o=f.outputs||{},url=o.thumbnailUrl||o.webpUrl||f.originalUrl||'';return `<div class="photo ${f.id===g.cover_file_id?'cover':''}">${url?`<img src="${esc(url)}" loading="lazy" onerror="this.onerror=null;this.src='${esc(f.originalUrl||'')}'">`:'<div style="height:134px">Imagen no disponible</div>'}<small>${esc(f.filename)}</small><button onclick="cover(${g.group_no},'${f.id}')">Portada</button><button class=danger onclick="delFile('${f.id}')">Quitar</button></div>`}).join('')}</div>
 <div class=fields><input id="cat${g.group_no}" value="${esc(g.category||'Calzado')}" placeholder="Categoría"><input id="sub${g.group_no}" value="${esc(g.subcategory||'Tenis')}" placeholder="Subcategoría"><input id="brand${g.group_no}" value="${esc(g.brand||'')}" placeholder="Marca"><input id="model${g.group_no}" value="${esc(g.model||'')}" placeholder="Modelo"></div>
 <div class=actions><button onclick="saveGroup(${g.group_no})">Guardar datos</button><button onclick="confirmGroup(${g.group_no})">${confirmed?'Confirmado ✓':'Confirmar y aprender'}</button><button onclick="mergePrompt(${g.group_no})">Unir con otro grupo</button></div></section>`}).join('')||'<p>No se generaron grupos.</p>';
}
async function load(){try{state=await api('/api/integral/batches/'+JOB);render()}catch(e){$('summary').textContent=e.message}}
async function regroup(){
 if(!confirm('¿Reagrupar este lote con el algoritmo visual mejorado? No se borrarán fotografías.'))return;
 $('summary').textContent='Reagrupando…';
 try{
   state=await api(`/api/integral/batches/${JOB}/regroup`,{method:'POST',body:JSON.stringify({similarity:0.975})});
   render();
 }catch(e){$('summary').textContent=e.message}
}
function payload(n){return {category:$('cat'+n).value,subcategory:$('sub'+n).value,brand:$('brand'+n).value,model:$('model'+n).value}}
async function saveGroup(n){await api(`/api/integral/batches/${JOB}/groups/${n}`,{method:'POST',body:JSON.stringify(payload(n))});await load()}
async function confirmGroup(n){await api(`/api/integral/batches/${JOB}/groups/${n}/confirm`,{method:'POST',body:JSON.stringify(payload(n))});await load()}
async function cover(n,id){await api(`/api/integral/batches/${JOB}/groups/${n}/cover/${id}`,{method:'POST',body:'{}'});await load()}
async function delFile(id){if(confirm('¿Quitar esta fotografía del grupo?')){await api(`/api/integral/batches/${JOB}/files/${id}/delete`,{method:'POST',body:'{}'});await load()}}
async function mergePrompt(n){const other=Number(prompt('Número del grupo que quieres unir con el grupo '+n+':'));if(!other||other===n)return;await api(`/api/integral/batches/${JOB}/merge`,{method:'POST',body:JSON.stringify({groups:[n,other],targetGroup:n})});await load()}
load();
</script></body></html>""")


@router.get("/integral-upload", response_class=HTMLResponse)
def integral_upload_page() -> HTMLResponse:
    return HTMLResponse(r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Carga masiva | Elegance</title>
<style>
:root{--ice:#68dcfb;--panel:#091620;--line:#2a637c}*{box-sizing:border-box}body{margin:0;background:#02080c;color:#eefaff;font:16px system-ui}.wrap{max-width:1100px;margin:auto;padding:20px}h1{font:48px cursive;color:var(--ice);margin:0}.card{background:var(--panel);border:1px solid #277da355;border-radius:20px;padding:18px;margin:14px 0}input,button,select{width:100%;padding:13px;border-radius:12px;border:1px solid var(--line);background:#061018;color:white}button{background:#087ea4;font-weight:800;cursor:pointer}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.progress{height:14px;background:#132631;border-radius:999px;overflow:hidden}.progress span{display:block;height:100%;width:0;background:var(--ice);transition:.25s}.job{padding:14px;border-bottom:1px solid #277da344}.job b{display:block}.actions{display:flex;gap:8px;flex-wrap:wrap}.actions button{width:auto}.warn{color:#ffd166}@media(max-width:700px){.grid{grid-template-columns:1fr}h1{font-size:40px}}
</style></head><body><main class="wrap"><h1>elegance</h1><p>Carga masiva persistente. Puedes cerrar esta pantalla y volver después.</p>
<section class="card"><h2>Nuevo lote</h2><input id="files" type="file" accept="image/*" multiple>
<div class="grid"><label>Similitud de agrupación<select id="similarity"><option value="0.975">Muy estricta</option><option value="0.965" selected>Equilibrada</option><option value="0.95">Más flexible</option></select></label><label>Acción tras procesar<select id="after"><option value="review">Enviar a revisión</option><option value="draft">Guardar como borrador</option></select></label></div>
<button id="start">Guardar y procesar en segundo plano</button><p id="message">Esperando imágenes.</p><div class="progress"><span id="bar"></span></div></section>
<section class="card"><div class="actions"><button id="refresh">Actualizar lotes</button><a href="/catalog-admin" style="color:#68dcfb;padding:12px">Volver al catálogo</a><a href="/diagnostics" style="color:#68dcfb;padding:12px">Diagnóstico</a></div><div id="jobs">Cargando…</div></section></main>
<script>
const $=id=>document.getElementById(id);let timer=null;
async function api(url,opt={}){const r=await fetch(url,opt);const text=await r.text();let j={};try{j=JSON.parse(text)}catch{}if(!r.ok)throw Error(j.detail||`Error ${r.status}`);return j}
function pct(v){return Math.max(0,Math.min(100,Number(v||0)))}
function renderJob(j){const done=Number(j.processed_files||0),total=Number(j.total_files||0);return `<article class="job"><b>${j.id}</b><span>Estado: ${j.status} · Etapa: ${j.stage} · ${done}/${total} · ${pct(j.progress)}%</span>${j.error?`<p class="warn">${j.error}</p>`:''}<div class="progress"><span style="width:${pct(j.progress)}%"></span></div><div class="actions">${['failed','recoverable','cancelled'].includes(j.status)?`<button onclick="retryJob('${j.id}')">Reanudar</button>`:''}${['queued','running'].includes(j.status)?`<button onclick="cancelJob('${j.id}')">Cancelar</button>`:''}<button onclick="watch('${j.id}')">Ver progreso</button>${j.status==='completed'?`<a href="/integral-review/${j.id}">Revisar resultado</a>`:''}</div></article>`}
async function loadJobs(){try{const j=await api('/api/integral/batches?limit=30');$('jobs').innerHTML=(j.jobs||[]).map(renderJob).join('')||'<p>No hay lotes todavía.</p>'}catch(e){$('jobs').textContent=e.message}}
async function watch(id){clearInterval(timer);timer=setInterval(async()=>{try{const j=await api('/api/integral/batches/'+id);$('message').textContent=`${j.stage}: ${j.processed_files}/${j.total_files} · ${j.progress}%`;$('bar').style.width=pct(j.progress)+'%';if(['completed','failed','cancelled'].includes(j.status)){clearInterval(timer);loadJobs()}}catch(e){$('message').textContent=e.message}},1200)}
async function retryJob(id){await api('/api/integral/batches/'+id+'/retry',{method:'POST'});watch(id);loadJobs()}
async function cancelJob(id){await api('/api/integral/batches/'+id+'/cancel',{method:'POST'});loadJobs()}
window.retryJob=retryJob;window.cancelJob=cancelJob;window.watch=watch;
$('start').onclick=async()=>{const fs=[...$('files').files];if(!fs.length)return $('message').textContent='Selecciona imágenes.';$('start').disabled=true;try{const fd=new FormData();fs.forEach(f=>fd.append('files',f));fd.append('options_json',JSON.stringify({groupSimilarity:Number($('similarity').value),after:$('after').value}));$('message').textContent=`Guardando ${fs.length} imágenes…`;const j=await api('/api/integral/batches',{method:'POST',body:fd});$('message').textContent=`Lote ${j.jobId} creado. Ya puedes cerrar esta página.`;watch(j.jobId);loadJobs()}catch(e){$('message').textContent=e.message}finally{$('start').disabled=false}};
$('refresh').onclick=loadJobs;loadJobs();
</script></body></html>""")
