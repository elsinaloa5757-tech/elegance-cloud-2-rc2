from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from services.shoe_phase5 import migrate_phase5, phase5_stats, recognize_phase5, remember_phase5

router=APIRouter()


@router.get("/api/shoe-intelligence/phase5/stats")
def stats():
    migrate_phase5()
    return phase5_stats()


@router.post("/api/shoe-intelligence/phase5/remember")
async def remember(
    file:UploadFile=File(...),
    brand:str=Form(...),
    model:str=Form(...),
    colorway:str=Form(default=""),
):
    try:
        return remember_phase5(await file.read(),brand,model,colorway=colorway,image_ref=file.filename or "")
    except Exception as exc:
        raise HTTPException(status_code=400,detail=str(exc)) from exc


@router.post("/api/shoe-intelligence/phase5/recognize")
async def recognize(file:UploadFile=File(...)):
    try:
        return recognize_phase5(await file.read())
    except Exception as exc:
        raise HTTPException(status_code=400,detail=str(exc)) from exc


@router.get("/shoe-intelligence/phase5",response_class=HTMLResponse)
def page():
    return HTMLResponse(r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Elegance Visual Intelligence Fase 5</title>
<style>
:root{--ice:#66dcfb;--p:#091721;--l:#24566b;--g:#63ef9b}*{box-sizing:border-box}
body{margin:0;background:#02080c;color:#f5fbff;font:16px system-ui}main{max-width:1100px;margin:auto;padding:24px}
h1{font:52px cursive;color:var(--ice);margin:0}.panel{background:var(--p);border:1px solid #24566b88;border-radius:20px;padding:20px;margin:16px 0}
.row{display:flex;gap:10px;flex-wrap:wrap}input{flex:1;min-width:180px;background:#031018;color:#fff;border:1px solid var(--l);padding:13px;border-radius:11px}
button,a{background:#0785ae;color:#fff;border:0;border-radius:11px;padding:12px 16px;font-weight:800;text-decoration:none;cursor:pointer}
.result{padding:16px 0;border-top:1px solid #1e4353}.score{float:right;color:var(--g);font-size:22px;font-weight:900}
.metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:7px;margin-top:10px}.chip{padding:7px;border:1px solid #244c5e;border-radius:9px;font-size:12px;color:#abd5e6}
.variant{margin-top:7px;color:#c7e5f1}.warn{color:#ffd166}@media(max-width:750px){.metrics{grid-template-columns:1fr 1fr}}
</style></head><body><main><h1>elegance</h1><h2>Visual Intelligence · Fase 5</h2>
<p>Reconocimiento jerárquico: primero identifica la silueta/modelo y después evalúa la variante o colorway.</p>
<div class=row><a href="/shoe-intelligence/phase4">← Fase 4</a><a href="/shoe-intelligence">Shoe Intelligence</a><a href="/catalog-admin">Catálogo</a></div>

<section class=panel><h2>Estado</h2><p><b id=refs>—</b> referencias · <b id=models>—</b> modelos · <b id=variants>—</b> variantes</p></section>

<section class=panel><h2>Enseñar referencia</h2><div class=row>
<input id=trainFile type=file accept="image/*"><input id=trainBrand placeholder="Marca"><input id=trainModel placeholder="Modelo base"><input id=trainColorway placeholder="Colorway opcional">
<button onclick="train()">Confirmar y aprender</button></div><p id=trainMsg></p></section>

<section class=panel><h2>Reconocer fotografía</h2><div class=row><input id=testFile type=file accept="image/*"><button onclick="recognize()">Analizar</button></div><div id=results></div></section>

<script>
async function api(u,o={}){const r=await fetch(u,o),t=await r.text();let j={};try{j=JSON.parse(t)}catch{}if(!r.ok)throw Error(j.detail||`Error ${r.status}`);return j}
const pct=v=>Math.round((v||0)*100);
async function load(){const x=await api('/api/shoe-intelligence/phase5/stats');refs.textContent=x.references;models.textContent=x.models;variants.textContent=x.variants}
async function train(){const f=trainFile.files[0];if(!f||!trainBrand.value.trim()||!trainModel.value.trim()){trainMsg.textContent='Selecciona imagen, marca y modelo.';return}
trainMsg.textContent='Aprendiendo modelo y variante…';const fd=new FormData();fd.append('file',f);fd.append('brand',trainBrand.value);fd.append('model',trainModel.value);fd.append('colorway',trainColorway.value);
try{const x=await api('/api/shoe-intelligence/phase5/remember',{method:'POST',body:fd});trainMsg.textContent=`Aprendido: ${x.brand} ${x.model}${x.colorway?' · '+x.colorway:''}`;load()}catch(e){trainMsg.textContent=e.message}}
async function recognize(){const f=testFile.files[0];if(!f){results.textContent='Selecciona una fotografía.';return}
results.textContent='Analizando silueta y variante…';const fd=new FormData();fd.append('file',f);
try{const x=await api('/api/shoe-intelligence/phase5/recognize',{method:'POST',body:fd});results.innerHTML=x.items.map(r=>`<div class=result><span class=score>${pct(r.modelConfidence)}% modelo</span><b>${r.brand} ${r.model}</b><div class=variant>${r.colorway?`Variante sugerida: <b>${r.colorway}</b> · ${pct(r.colorwayConfidence)}%`:'Sin colorway aprendido todavía'}</div><div class=metrics><span class=chip>Forma ${pct(r.evidence.shape)}%</span><span class=chip>Regiones ${pct(r.evidence.regions)}%</span><span class=chip>HOG ${pct(r.evidence.hog)}%</span><span class=chip>Bordes ${pct(r.evidence.edge)}%</span><span class=chip>Puntos ${pct(r.evidence.local)}%</span><span class=chip>Color ${pct(r.evidence.color)}%</span></div></div>`).join('')||x.message||'Sin coincidencias.'}catch(e){results.textContent=e.message}}
load();</script></main></body></html>""")
