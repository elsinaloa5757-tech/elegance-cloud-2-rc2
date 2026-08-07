from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from services.shoe_phase6_enterprise import (
    migrate_phase6_enterprise, stats, correct_name, remember, recognize,
    rebuild_dna, import_phase5_and_rebuild
)

router = APIRouter()

@router.get("/api/shoe-intelligence/phase6/stats")
def api_stats():
    migrate_phase6_enterprise()
    return stats()

@router.get("/api/shoe-intelligence/phase6/correct-name")
def api_correct_name(q:str=Query(default=""), brand:str=Query(default=""), category:str=Query(default=""), limit:int=Query(default=8,ge=1,le=25)):
    return correct_name(q,brand,category,limit)

@router.post("/api/shoe-intelligence/phase6/rebuild")
def api_rebuild():
    return rebuild_dna()

@router.post("/api/shoe-intelligence/phase6/import-phase5")
def api_import_phase5():
    return import_phase5_and_rebuild()

@router.post("/api/shoe-intelligence/phase6/remember")
async def api_remember(
    file:UploadFile=File(...), category:str=Form(default="Calzado"),
    brand:str=Form(...), model:str=Form(...), colorway:str=Form(default=""),
    subcategory:str=Form(default=""), family:str=Form(default="")
):
    try:
        return remember(await file.read(),category,brand,model,colorway,subcategory,family,file.filename or "")
    except Exception as e:
        raise HTTPException(status_code=400,detail=str(e)) from e

@router.post("/api/shoe-intelligence/phase6/recognize")
async def api_recognize(file:UploadFile=File(...), category:str=Form(default="Calzado")):
    try:
        return recognize(await file.read(),category)
    except Exception as e:
        raise HTTPException(status_code=400,detail=str(e)) from e

@router.get("/shoe-intelligence/phase6",response_class=HTMLResponse)
def page():
    return HTMLResponse(r"""<!doctype html><html lang=es><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Elegance Vision Enterprise RC2</title><style>
:root{--i:#66dcfb;--p:#091721;--l:#24566b;--g:#63ef9b;--y:#ffd166}*{box-sizing:border-box}body{margin:0;background:#02080c;color:#f5fbff;font:16px system-ui}
main{max-width:1160px;margin:auto;padding:24px}h1{font:52px cursive;color:var(--i);margin:0}.p{background:var(--p);border:1px solid #24566b88;border-radius:20px;padding:20px;margin:16px 0}
.s{display:grid;grid-template-columns:repeat(5,1fr);gap:9px}.c{border:1px solid var(--l);padding:14px;border-radius:14px}.n{font-size:28px;font-weight:900;color:var(--i)}
.r{display:flex;gap:9px;flex-wrap:wrap}input,select{flex:1;min-width:150px;background:#031018;color:#fff;border:1px solid var(--l);padding:12px;border-radius:10px}
button,a{background:#0785ae;color:#fff;border:0;border-radius:10px;padding:12px 15px;font-weight:800;text-decoration:none;cursor:pointer}.item{padding:15px 0;border-top:1px solid #1e4353}
.score{float:right;color:var(--g);font-size:22px;font-weight:900}.parts{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.chip{border:1px solid #244c5e;border-radius:9px;padding:6px 8px;font-size:12px;color:#b7d8e7}.muted{color:#9fc4d5}
@media(max-width:760px){.s{grid-template-columns:1fr 1fr}}</style></head><body><main>
<h1>elegance</h1><h2>Vision Enterprise · Fase 6 RC2 Integral</h2>
<p>Familias, piezas regionales, consenso multivista, corrección de nombres, colorways y arquitectura universal de moda.</p>
<div class=r><a href=/shoe-intelligence/phase5>← Fase 5</a><a href=/shoe-intelligence>Shoe Intelligence</a><a href=/catalog-admin>Catálogo</a></div>

<section class=p><h2>Estado Enterprise</h2><div class=s>
<div class=c>Base maestra<div id=master class=n>—</div></div><div class=c>Referencias<div id=refs class=n>—</div></div>
<div class=c>Modelos ADN<div id=models class=n>—</div></div><div class=c>Familias ADN<div id=families class=n>—</div></div>
<div class=c>Categorías<div id=cats class=n>—</div></div></div>
<p><button onclick=importP5()>Importar Fase 5 y construir ADN</button> <button onclick=rebuild()>Reconstruir ADN</button></p><p id=bmsg class=muted></p></section>

<section class=p><h2>Corrección automática de nombres</h2><div class=r><input id=nq placeholder="Ej. jordn 3 white sement"><input id=nb placeholder="Marca opcional"><button onclick=fixName()>Corregir</button></div><div id=nres></div></section>

<section class=p><h2>Aprender referencia</h2><div class=r>
<select id=tc><option>Calzado</option><option>Ropa</option><option>Bolsas</option><option>Accesorios</option></select>
<input id=tf type=file accept=image/*><input id=tb placeholder=Marca><input id=tm placeholder="Modelo"><input id=tcolor placeholder="Colorway opcional"><input id=tfam placeholder="Familia opcional">
<button onclick=train()>Aprender</button></div><p id=tmsg></p></section>

<section class=p><h2>Reconocimiento Enterprise</h2><div class=r>
<select id=qc><option>Calzado</option><option>Ropa</option><option>Bolsas</option><option>Accesorios</option></select>
<input id=qf type=file accept=image/*><button onclick=go()>Reconocer</button></div><h3 id=dec></h3><div id=res></div></section>

<script>
async function api(u,o={}){let r=await fetch(u,o),t=await r.text(),j={};try{j=JSON.parse(t)}catch{}if(!r.ok)throw Error(j.detail||'Error '+r.status);return j}const pct=v=>Math.round((v||0)*100);
async function load(){let x=await api('/api/shoe-intelligence/phase6/stats');master.textContent=x.masterItems;refs.textContent=x.visualReferences;models.textContent=x.dnaModels;families.textContent=x.dnaFamilies;cats.textContent=x.categories}
async function importP5(){bmsg.textContent='Importando y construyendo ADN…';try{let x=await api('/api/shoe-intelligence/phase6/import-phase5',{method:'POST'});bmsg.textContent=`Importadas ${x.importedPhase5}; ADN ${x.builtModels} modelos`;load()}catch(e){bmsg.textContent=e.message}}
async function rebuild(){bmsg.textContent='Reconstruyendo…';try{let x=await api('/api/shoe-intelligence/phase6/rebuild',{method:'POST'});bmsg.textContent=`ADN ${x.builtModels} modelos`;load()}catch(e){bmsg.textContent=e.message}}
async function fixName(){nres.textContent='Buscando…';try{let x=await api(`/api/shoe-intelligence/phase6/correct-name?q=${encodeURIComponent(nq.value)}&brand=${encodeURIComponent(nb.value)}`);nres.innerHTML=x.items.map(r=>`<div class=item><span class=score>${pct(r.confidence)}%</span><b>${r.normalizedName}</b><div class=muted>${r.category} · ${r.family}</div></div>`).join('')||'Sin coincidencias.'}catch(e){nres.textContent=e.message}}
async function train(){let f=tf.files[0];if(!f||!tb.value||!tm.value){tmsg.textContent='Falta foto, marca o modelo.';return}let d=new FormData();d.append('file',f);d.append('category',tc.value);d.append('brand',tb.value);d.append('model',tm.value);d.append('colorway',tcolor.value);d.append('family',tfam.value);tmsg.textContent='Aprendiendo y recalculando ADN…';try{let x=await api('/api/shoe-intelligence/phase6/remember',{method:'POST',body:d});tmsg.textContent=`Aprendido: ${x.category} · ${x.brand} ${x.model}${x.colorway?' · '+x.colorway:''}`;load()}catch(e){tmsg.textContent=e.message}}
async function go(){let f=qf.files[0];if(!f){res.textContent='Selecciona foto.';return}let d=new FormData();d.append('file',f);d.append('category',qc.value);res.textContent='Analizando ADN y piezas…';try{let x=await api('/api/shoe-intelligence/phase6/recognize',{method:'POST',body:d});let L={high_confidence:'Alta confianza',review:'Revisión recomendada',low_confidence:'Confianza baja',unknown:'Desconocido'};dec.textContent=`${L[x.decision]||x.decision} · margen ${pct(x.margin)}%`;res.innerHTML=x.items.map(r=>`<div class=item><span class=score>${pct(r.modelConfidence)}%</span><b>${r.brand} ${r.model}</b><div>${r.family} · ${r.references} vistas · ADN ${pct(r.dnaQuality)}%</div><div>${r.colorway?`Colorway: <b>${r.colorway}</b> ${pct(r.colorwayConfidence)}%`:'Sin colorway confirmado'}</div><div class=parts>${Object.entries(r.evidence.partScores).map(([k,v])=>`<span class=chip>${k} ${pct(v)}%</span>`).join('')}</div></div>`).join('')||x.message||'Sin coincidencias.'}catch(e){res.textContent=e.message}}
load();</script></main></body></html>""")
