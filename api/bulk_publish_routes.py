from fastapi import APIRouter,Query
from fastapi.responses import HTMLResponse
from services.bulk_publish_optimizer import migrate_bulk_publish_optimizer,publish_all,queue_all,status,recent,set_paused
router=APIRouter()

@router.get("/api/bulk-publish/status")
def api_status():
    migrate_bulk_publish_optimizer()
    return status()

@router.get("/api/bulk-publish/recent")
def api_recent(limit:int=Query(default=80,ge=1,le=200)):
    return recent(limit)

@router.post("/api/bulk-publish/publish-all")
def api_publish_all(optimize:bool=Query(default=True)):
    return publish_all(optimize)

@router.post("/api/bulk-publish/queue-all")
def api_queue_all():
    return queue_all()

@router.post("/api/bulk-publish/pause")
def api_pause(paused:bool=Query(default=True)):
    return set_paused(paused)

@router.get("/bulk-publish",response_class=HTMLResponse)
def page():
 return HTMLResponse("""<!doctype html><html lang=es><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Elegance Bulk Publish</title>
<style>:root{--i:#66dcfb;--p:#091721;--l:#24566b;--g:#63ef9b;--y:#ffd166}*{box-sizing:border-box}body{margin:0;background:#02080c;color:#f5fbff;font:15px system-ui}main{max-width:1180px;margin:auto;padding:24px}h1{font:50px cursive;color:var(--i);margin:0}.p{background:var(--p);border:1px solid #24566b88;border-radius:18px;padding:19px;margin:15px 0}.s{display:grid;grid-template-columns:repeat(6,1fr);gap:9px}.c{border:1px solid var(--l);padding:12px;border-radius:12px}.n{font-size:27px;font-weight:900;color:var(--i)}button,a{background:#0785ae;color:#fff;border:0;border-radius:10px;padding:11px 14px;font-weight:800;text-decoration:none;cursor:pointer}.secondary{background:#173847}.row{display:flex;gap:8px;flex-wrap:wrap}.item{padding:12px 0;border-top:1px solid #1c4151}.ok{color:var(--g)}.warn{color:var(--y)}.bar{height:10px;background:#102a35;border-radius:10px;overflow:hidden}.bar div{height:100%;background:var(--i);width:0}@media(max-width:800px){.s{grid-template-columns:repeat(3,1fr)}}</style></head><body><main>
<h1>elegance</h1><h2>Publicar todo + Auto Optimize</h2><p>Publica el catálogo inmediatamente y deja que Elegance prepare la optimización interna en segundo plano.</p>
<div class=row><a href=/catalog-admin>← Catálogo</a><a href=/catalog-intelligence>Auditoría</a><a href=/catalog>Ver catálogo público</a></div>
<section class=p><div class=s><div class=c>Publicados<div id=pub class=n>—</div></div><div class=c>Borradores<div id=draft class=n>—</div></div><div class=c>Pendientes IA<div id=q class=n>—</div></div><div class=c>Procesando<div id=run class=n>—</div></div><div class=c>Revisión<div id=rev class=n>—</div></div><div class=c>Optimizados<div id=opt class=n>—</div></div></div><div class=bar><div id=bar></div></div><p id=msg></p>
<div class=row><button onclick=publishAll()>🚀 Publicar todo + optimizar</button><button class=secondary onclick=queueAll()>Optimizar catálogo existente</button><button class=secondary onclick=pause()>Pausar IA</button><button class=secondary onclick=resume()>Reanudar IA</button></div></section>
<section class=p><h2>Actividad reciente</h2><div id=list></div></section>
<script>
async function api(u,o={}){let r=await fetch(u,{credentials:'same-origin',...o}),t=await r.text(),j={};try{j=JSON.parse(t)}catch{}if(r.status===401){location.href='/login?next='+encodeURIComponent(location.pathname);throw Error('Sesión requerida')}if(!r.ok)throw Error(j.detail||'Error '+r.status);return j}
async function load(){let x=await api('/api/bulk-publish/status');pub.textContent=x.published;draft.textContent=x.drafts;q.textContent=x.queued;run.textContent=x.running;rev.textContent=x.review;opt.textContent=x.optimized;let total=x.total||0;bar.style.width=total?Math.round(((x.review+x.optimized)/total)*100)+'%':'0%';let y=await api('/api/bulk-publish/recent?limit=80');list.innerHTML=y.items.map(i=>`<div class=item><b>${i.product_id}</b> · ${i.status} · ${i.stage} <span class=${i.status==='optimized'?'ok':i.status==='review'?'warn':''}>${Math.round((i.confidence||0)*100)}%</span><div>${i.message||''}</div></div>`).join('')||'Sin trabajos todavía.'}
async function publishAll(){if(!confirm('¿Publicar todos los productos actuales y encolar su optimización?'))return;msg.textContent='Publicando…';try{let x=await api('/api/bulk-publish/publish-all?optimize=true',{method:'POST'});msg.textContent=`Publicados ${x.published} de ${x.products}. La IA continuará en segundo plano.`;load()}catch(e){msg.textContent=e.message}}
async function queueAll(){msg.textContent='Encolando catálogo…';try{await api('/api/bulk-publish/queue-all',{method:'POST'});msg.textContent='Catálogo encolado para optimización.';load()}catch(e){msg.textContent=e.message}}
async function pause(){await api('/api/bulk-publish/pause?paused=true',{method:'POST'});msg.textContent='Optimización pausada.';load()}
async function resume(){await api('/api/bulk-publish/pause?paused=false',{method:'POST'});msg.textContent='Optimización reanudada.';load()}
load();setInterval(()=>load().catch(()=>{}),5000)
</script></main></body></html>""")
