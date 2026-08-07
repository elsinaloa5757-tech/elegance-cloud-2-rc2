from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from services.batch_automation import cancel_job, create_job, get_job, list_jobs, retry_job

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
function renderJob(j){const done=Number(j.processed_files||0),total=Number(j.total_files||0);return `<article class="job"><b>${j.id}</b><span>Estado: ${j.status} · Etapa: ${j.stage} · ${done}/${total} · ${pct(j.progress)}%</span>${j.error?`<p class="warn">${j.error}</p>`:''}<div class="progress"><span style="width:${pct(j.progress)}%"></span></div><div class="actions">${['failed','recoverable','cancelled'].includes(j.status)?`<button onclick="retryJob('${j.id}')">Reanudar</button>`:''}${['queued','running'].includes(j.status)?`<button onclick="cancelJob('${j.id}')">Cancelar</button>`:''}<button onclick="watch('${j.id}')">Ver progreso</button></div></article>`}
async function loadJobs(){try{const j=await api('/api/integral/batches?limit=30');$('jobs').innerHTML=(j.jobs||[]).map(renderJob).join('')||'<p>No hay lotes todavía.</p>'}catch(e){$('jobs').textContent=e.message}}
async function watch(id){clearInterval(timer);timer=setInterval(async()=>{try{const j=await api('/api/integral/batches/'+id);$('message').textContent=`${j.stage}: ${j.processed_files}/${j.total_files} · ${j.progress}%`;$('bar').style.width=pct(j.progress)+'%';if(['completed','failed','cancelled'].includes(j.status)){clearInterval(timer);loadJobs()}}catch(e){$('message').textContent=e.message}},1200)}
async function retryJob(id){await api('/api/integral/batches/'+id+'/retry',{method:'POST'});watch(id);loadJobs()}
async function cancelJob(id){await api('/api/integral/batches/'+id+'/cancel',{method:'POST'});loadJobs()}
window.retryJob=retryJob;window.cancelJob=cancelJob;window.watch=watch;
$('start').onclick=async()=>{const fs=[...$('files').files];if(!fs.length)return $('message').textContent='Selecciona imágenes.';$('start').disabled=true;try{const fd=new FormData();fs.forEach(f=>fd.append('files',f));fd.append('options_json',JSON.stringify({groupSimilarity:Number($('similarity').value),after:$('after').value}));$('message').textContent=`Guardando ${fs.length} imágenes…`;const j=await api('/api/integral/batches',{method:'POST',body:fd});$('message').textContent=`Lote ${j.jobId} creado. Ya puedes cerrar esta página.`;watch(j.jobId);loadJobs()}catch(e){$('message').textContent=e.message}finally{$('start').disabled=false}};
$('refresh').onclick=loadJobs;loadJobs();
</script></body></html>""")
