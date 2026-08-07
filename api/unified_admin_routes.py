from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/elegance", response_class=HTMLResponse)
@router.get("/admin", response_class=HTMLResponse)
def unified_admin():
    return HTMLResponse(r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Elegance · Administración</title>
<style>
:root{--bg:#02080c;--panel:#091721;--line:#173a49;--ice:#67dbfa;--text:#f5fbff;--muted:#95aeb9}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:1080px;margin:auto;padding:18px}
.brand{font:52px cursive;color:var(--ice);line-height:1;margin:8px 0 4px}
.sub{color:var(--muted);margin:0 0 22px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.card{display:block;background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:22px;color:var(--text);text-decoration:none;min-height:150px}
.card:hover{border-color:var(--ice);transform:translateY(-1px)}
.n{font-size:13px;font-weight:900;letter-spacing:.14em;color:var(--ice);text-transform:uppercase}
h2{margin:8px 0 8px;font-size:26px}
p{color:var(--muted);line-height:1.45}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}
.actions a{background:#0b8eb9;color:white;padding:12px 15px;border-radius:10px;text-decoration:none;font-weight:800}
.actions a.secondary{background:#123343}
.brain{margin-top:16px;background:#07131b;border:1px solid var(--line);border-radius:14px;padding:14px}
#brain{color:var(--muted)}
@media(max-width:700px){.grid{grid-template-columns:1fr}.brand{font-size:42px}.wrap{padding:12px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="brand">elegance</div>
  <p class="sub">Administración central</p>

  <div class="grid">
    <a class="card" href="/integral-upload">
      <div class="n">Paso 1</div><h2>Subir mercancía</h2>
      <p>Carga imágenes y crea productos en lote.</p>
    </a>
    <a class="card" href="/catalog-intelligence">
      <div class="n">Paso 2</div><h2>Editar y aprender</h2>
      <p>Corrige una referencia y enseña a Elegance Brain RC4.</p>
    </a>
    <a class="card" href="/bulk-publish">
      <div class="n">Paso 3</div><h2>Publicar</h2>
      <p>Publica borradores y envía el catálogo a optimización.</p>
    </a>
    <a class="card" href="/catalog-admin">
      <div class="n">Paso 4</div><h2>Productos</h2>
      <p>Administra inventario y revisa todos los productos.</p>
    </a>
  </div>

  <div class="brain">
    <b>Elegance Brain RC4</b>
    <div id="brain">Consultando estado…</div>
  </div>

  <div class="actions">
    <a href="/catalog">Ver tienda</a>
    <a class="secondary" href="/elegance">Inicio administración</a>
  </div>
</div>
<script>
(async()=>{
  const el=document.getElementById('brain');
  try{
    const r=await fetch('/api/catalog-learning/stats',{cache:'no-store'});
    const x=await r.json();
    if(!r.ok) throw new Error(x.detail||('Error '+r.status));
    const j=x.jobs||{};
    const l=x.lastJob||null;
    let s=`En cola ${j.queued||0} · Procesando ${j.running||0} · Terminados ${j.done||0} · Fallidos ${j.failed||0}`;
    if(l){
      s += ` · Último: ${l.status} ${l.processed||0}/${l.total||0}`;
      if(l.base_matches!=null) s += ` · Similares ${l.base_matches}`;
      if(l.exact_matches!=null) s += ` · Exactos ${l.exact_matches}`;
    }
    el.textContent=s;
  }catch(e){el.textContent='Brain disponible, pero no se pudo leer el estado: '+e.message}
})();
</script>
</body></html>""")
