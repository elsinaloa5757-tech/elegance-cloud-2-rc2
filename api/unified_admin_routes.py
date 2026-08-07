from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router=APIRouter()

@router.get("/elegance",response_class=HTMLResponse)
@router.get("/admin",response_class=HTMLResponse)
def unified_admin():
    return HTMLResponse('''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Elegance · Administración</title>
<style>
:root{--bg:#02080c;--panel:#091721;--line:#173a49;--ice:#67dbfa;--text:#f5fbff;--muted:#91adba}
*{box-sizing:border-box}html,body{height:100%;margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,sans-serif}
body{display:flex;flex-direction:column;overflow:hidden}
header{flex:0 0 auto;padding:12px 14px;border-bottom:1px solid var(--line);background:#030a0f}
.brand{font:38px cursive;color:var(--ice);line-height:1;margin-bottom:8px}
nav{display:flex;gap:7px;overflow-x:auto;padding-bottom:2px}
button,a{border:0;border-radius:10px;background:#123343;color:white;padding:11px 14px;font-weight:800;white-space:nowrap;text-decoration:none}
button.active{background:#078bb6}
a.store{background:#174252;margin-left:auto}
main{flex:1;min-height:0;position:relative}
.panel{position:absolute;inset:0;display:none}
.panel.active{display:block}
iframe{border:0;width:100%;height:100%;background:#02080c}
#loading{position:absolute;right:14px;bottom:14px;background:#0a2632;border:1px solid var(--line);border-radius:999px;padding:8px 12px;color:var(--muted);font-size:12px;display:none}
@media(max-width:700px){header{padding:9px}.brand{font-size:32px}button,a{padding:10px 11px;font-size:13px}.store{margin-left:0}}
</style>
</head>
<body>
<header>
<div class="brand">elegance</div>
<nav>
<button data-tab="upload" class="active">1. Subir</button>
<button data-tab="edit">2. Editar y aprender</button>
<button data-tab="publish">3. Publicar</button>
<button data-tab="products">4. Productos</button>
<a class="store" href="/catalog" target="_blank">Ver tienda ↗</a>
</nav>
</header>
<main>
<div id="upload" class="panel active"><iframe data-src="/integral-upload" title="Subir mercancía"></iframe></div>
<div id="edit" class="panel"><iframe data-src="/catalog-intelligence" title="Editar y aprender"></iframe></div>
<div id="publish" class="panel"><iframe data-src="/bulk-publish" title="Publicar"></iframe></div>
<div id="products" class="panel"><iframe data-src="/catalog-admin" title="Productos"></iframe></div>
<div id="loading">Cargando…</div>
</main>
<script>
const panels=[...document.querySelectorAll('.panel')];
const buttons=[...document.querySelectorAll('button[data-tab]')];
const loading=document.getElementById('loading');
function openTab(id){
  panels.forEach(p=>p.classList.toggle('active',p.id===id));
  buttons.forEach(b=>b.classList.toggle('active',b.dataset.tab===id));
  const p=document.getElementById(id);
  const frame=p.querySelector('iframe');
  if(!frame.src){
    loading.style.display='block';
    frame.onload=()=>loading.style.display='none';
    frame.src=frame.dataset.src;
  }
  history.replaceState(null,'','#'+id);
}
buttons.forEach(b=>b.onclick=()=>openTab(b.dataset.tab));
const initial=(location.hash||'#upload').slice(1);
openTab(['upload','edit','publish','products'].includes(initial)?initial:'upload');
</script>
</body></html>''')
