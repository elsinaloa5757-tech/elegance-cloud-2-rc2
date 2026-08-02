from fastapi import APIRouter,Body,HTTPException,Query
from fastapi.responses import HTMLResponse
from services.scalability_platform import *
router=APIRouter()

@router.get("/api/scalability/diagnostics")
def diag():return diagnostics()

@router.get("/api/scalability/products")
def page(page:int=1,pageSize:int=30,q:str="",category:str="",brand:str="",status:str=""):
    return paginate(page,pageSize,q,category,brand,status)

@router.get("/api/scalability/jobs")
def jobs(limit:int=50):return {"status":"ok","jobs":list_jobs(limit)}

@router.post("/api/scalability/jobs")
def add_job(p:dict=Body(...)):return create_job(str(p.get("kind") or "generic"),int(p.get("total") or 0),p.get("payload") or {})

@router.post("/api/scalability/jobs/{jid}/{action}")
def act(jid:str,action:str):
    if action not in {"cancel","resume"}:raise HTTPException(400,"Acción inválida")
    try:return job_action(jid,action)
    except KeyError as e:raise HTTPException(404,"Lote no encontrado") from e

@router.get("/api/scalability/memory")
def mem():return memory()

@router.post("/api/scalability/memory")
def mem_add(p:dict=Body(...)):
    try:return remember(p)
    except ValueError as e:raise HTTPException(400,str(e)) from e

@router.get("/api/scalability/trash")
def trash(limit:int=100):return {"status":"ok","items":trash_list(limit)}

@router.post("/api/scalability/trash/{pid}")
def trash_add(pid:str,p:dict=Body(default={})):
    try:return trash_product(pid,str(p.get("reason") or ""),int(p.get("days") or 30))
    except KeyError as e:raise HTTPException(404,"Producto no encontrado") from e

@router.post("/api/scalability/trash/{tid}/restore")
def trash_restore(tid:str):
    try:return restore(tid)
    except KeyError as e:raise HTTPException(404,"Elemento no encontrado") from e

@router.get("/diagnostics",response_class=HTMLResponse)
def page_diag():
    return HTMLResponse("""<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>Diagnóstico Elegance</title><style>body{margin:0;background:#02080c;color:#eefaff;font:16px system-ui}.w{max-width:1100px;margin:auto;padding:24px}h1{color:#65d9ff;font-size:44px}.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}.c{background:#091620;border:1px solid #277da355;border-radius:18px;padding:18px}.c b{font-size:34px;display:block}button{padding:12px 18px;background:#087ea4;color:white;border:0;border-radius:12px;font-weight:800}pre{white-space:pre-wrap;background:#061018;padding:16px;border-radius:16px}</style>
<div class=w><h1>Elegance Diagnóstico</h1><button onclick=load()>Actualizar</button><div class=g>
<div class=c>Productos<b id=p>—</b><small id=pd></small></div><div class=c>Cola activa<b id=j>—</b></div>
<div class=c>Memoria visual<b id=m>—</b></div><div class=c>Papelera<b id=t>—</b></div></div><pre id=r>Cargando…</pre></div>
<script>async function load(){let x=await fetch('/api/scalability/diagnostics').then(r=>r.json());p.textContent=x.products.total;pd.textContent='Sin imagen: '+x.products.missingImage+' · Nombre pendiente: '+x.products.suspiciousName;j.textContent=(x.jobs.queued||0)+(x.jobs.running||0)+(x.jobs.recoverable||0);m.textContent=x.memory.confirmed;t.textContent=x.trash;r.textContent=JSON.stringify(x,null,2)}load()</script>""")
