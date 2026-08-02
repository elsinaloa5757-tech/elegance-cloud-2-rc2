const $ = (id) => document.getElementById(id);
let state = {products: [], facets: {}, selected: null, page: 1, pageSize: 30, total: 0, pages: 1};

function money(value){return new Intl.NumberFormat('es-MX',{style:'currency',currency:'MXN'}).format(Number(value||0));}
function esc(value){return String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
async function api(url, options={}){
  const headers={...(options.headers||{})}; if(!(options.body instanceof FormData)) headers['content-type']='application/json';
  const response = await fetch(url,{...options,headers});
  const data = await response.json().catch(()=>({detail:'Respuesta inválida'}));
  if(!response.ok) throw new Error(data.detail||'No se pudo completar la operación.');
  return data;
}
function query(){
  const p=new URLSearchParams({page:String(state.page),pageSize:String(state.pageSize)});
  ['q','category','brand','status'].forEach(k=>{const el=$(k);if(el?.value)p.set(k,el.value)});
  return p.toString();
}
async function load(){
  $('adminProducts').textContent='Cargando productos…';
  const catalogPromise=api('/api/scalability/products?'+query());
  const publicationsPromise=api('/api/admin/publications').catch(()=>({products:[]}));
  const requestsPromise=api('/api/public/requests?status=new').catch(()=>({requests:[]}));
  const data=await catalogPromise;
  state.products=data.items||[];
  state.facets=data.facets||{};
  state.total=Number(data.total||0);
  state.pages=Math.max(1,Number(data.pages||1));
  state.page=Math.min(Math.max(1,Number(data.page||1)),state.pages);
  renderFilters();
  render();
  renderPagination();
  const [pubs,req]=await Promise.all([publicationsPromise,requestsPromise]);
  $('publishedCount').textContent=(pubs.products||[]).filter(x=>x.status==='published').length;
  $('draftCount').textContent=(pubs.products||[]).filter(x=>x.status==='draft').length;
  $('soldCount').textContent=state.products.filter(x=>Number(x.stock||0)<=0).length;
  $('requestCount').textContent=(req.requests||[]).length;
}
function renderFilters(){
  const fill=(id,items,label)=>{const el=$(id);const current=el.value;el.innerHTML=`<option value="">${label}</option>`+(items||[]).map(x=>`<option ${x===current?'selected':''}>${esc(x)}</option>`).join('')};
  fill('category',state.facets.categories,'Todas las categorías');fill('brand',state.facets.brands,'Todas las marcas');fill('status',state.facets.statuses,'Todos los estados');
}
function render(){
  $('adminProducts').innerHTML=state.products.length?state.products.map(p=>`<button class="product-row" onclick="editProduct('${esc(p.id)}')">${p.thumbnailUrl?`<img class="product-thumb" src="${esc(p.thumbnailUrl)}" alt="" loading="lazy" decoding="async">`:'<span class="product-thumb placeholder" aria-hidden="true">e</span>'}<span class="product-main"><b>${esc(p.title||'Sin nombre')}</b><small>${esc([p.brand,p.model,p.category].filter(Boolean).join(' · '))}</small></span><span class="product-price"><b>${money(p.price)}</b><small>${Number(p.stock||0)} disponibles</small></span></button>`).join(''):'<p class="empty">No hay productos con estos filtros.</p>';
}
function renderPagination(){
  const start=state.total?((state.page-1)*state.pageSize)+1:0;
  const end=Math.min(state.page*state.pageSize,state.total);
  $('pageStatus').textContent=`Página ${state.page} de ${state.pages} · ${start}-${end} de ${state.total}`;
  $('previousPage').disabled=state.page<=1;
  $('nextPage').disabled=state.page>=state.pages;
  $('pageSize').value=String(state.pageSize);
}
function variantsFromProduct(p){return (p.variants||[]).map(v=>({id:v.id,size:v.size,color:v.color,stock:v.stock,salePrice:v.sale_price,purchasePrice:v.purchase_price,sku:v.sku}));}
function openEditor(p={}){
  state.selected=p.id||null;$('editorTitle').textContent=p.id?'Editar producto':'Nuevo producto';
  $('productId').value=p.id||'';$('title').value=p.title||'';$('editBrand').value=p.brand||'';$('model').value=p.model||'';$('editCategory').value=p.category||'';$('subcategory').value=p.subcategory||'';$('price').value=p.price||0;$('purchasePrice').value=p.purchasePrice||0;$('description').value=p.description||'';$('sizes').value=(p.sizes||[]).join(', ');$('colors').value=(p.colors||[]).join(', ');$('publicationStatus').value='';
  $('variants').value=JSON.stringify(variantsFromProduct(p),null,2);$('editor').classList.add('open');
  $('mediaPanel').hidden=!p.id; renderVariantOptions(p); if(p.id) loadMedia(p.id);
}
async function editProduct(id){const data=await api('/api/admin/catalog/products/'+id);openEditor(data.product);}
function closeEditor(){$('editor').classList.remove('open');}
function payload(){
  let variants=[];try{variants=JSON.parse($('variants').value||'[]')}catch{throw new Error('Las variantes deben estar en formato JSON válido.');}
  return {title:$('title').value,brand:$('editBrand').value,model:$('model').value,category:$('editCategory').value,subcategory:$('subcategory').value,price:Number($('price').value||0),purchasePrice:Number($('purchasePrice').value||0),description:$('description').value,sizes:$('sizes').value,colors:$('colors').value,variants,publicationStatus:$('publicationStatus').value||undefined};
}
async function saveProduct(){try{const id=$('productId').value;const data=await api(id?'/api/admin/catalog/products/'+id:'/api/admin/catalog/products',{method:id?'PUT':'POST',body:JSON.stringify(payload())});$('notice').textContent='Producto guardado correctamente.';openEditor(data.product);await load();}catch(e){$('notice').textContent=e.message;}}
async function removeProduct(){
  const id=$('productId').value;
  if(!id||!confirm('¿Enviar este producto a la papelera? Podrás restaurarlo después.'))return;
  try{
    await api('/api/scalability/trash/'+encodeURIComponent(id),{
      method:'POST',
      body:JSON.stringify({reason:'Eliminado desde catálogo administrativo',days:30})
    });
    closeEditor();
    if(state.products.length===1&&state.page>1)state.page--;
    await load();
  }catch(e){$('notice').textContent=e.message;}
}
async function duplicates(){const d=await api('/api/admin/catalog/duplicates');alert(`Hashes de imagen: ${d.imageHashCount}\nGrupos probables duplicados: ${d.probableGroupCount}`);}
['q','category','brand','status'].forEach(id=>$(id)?.addEventListener(id==='q'?'input':'change',()=>{
  clearTimeout(window._f);
  state.page=1;
  window._f=setTimeout(load,180);
}));
$('newProduct')?.addEventListener('click',()=>openEditor({}));$('closeEditor')?.addEventListener('click',closeEditor);$('saveProduct')?.addEventListener('click',saveProduct);$('deleteProduct')?.addEventListener('click',removeProduct);$('duplicatesButton')?.addEventListener('click',duplicates);load().catch(e=>$('adminProducts').textContent=e.message);

function renderVariantOptions(p){
  const el=$('mediaVariant'); if(!el)return;
  const current=el.value; const variants=variantsFromProduct(p);
  el.innerHTML='<option value="">Producto general</option>'+variants.map(v=>`<option value="${esc(v.id||'')}">${esc([v.size,v.color,v.sku].filter(Boolean).join(' · ')||'Variante')}</option>`).join('');
  el.value=current;
}
async function loadMedia(productId){
  $('mediaStatus').textContent='Cargando…';
  try{
    const data=await api(`/api/admin/catalog/products/${productId}/images`);
    $('mediaStatus').textContent=`${data.count} imagen${data.count===1?'':'es'}`;
    $('mediaGrid').innerHTML=data.items.length?data.items.map(mediaCard).join(''):'<p class="empty">Todavía no hay fotografías.</p>';
  }catch(e){$('mediaStatus').textContent=e.message;}
}
function mediaCard(item){
  const image=item.preferred?.thumbnail?.public_url||item.preferred?.catalog?.public_url||item.preferred?.original?.public_url||'';
  const stateLabel={ready:'Lista',processing:'Procesando',queued:'En cola',failed:'Falló'}[item.status]||item.status;
  return `<article class="media-card ${item.isCover?'cover':''}"><img src="${esc(image)}" alt="${esc(item.sourceName)}"><b>${item.isCover?'Portada · ':''}${esc(stateLabel)}</b><small>${esc(item.sourceName)}</small><small>${Math.round(Number(item.byteSize||0)/1024)} KB · intento ${item.attempts}</small>${item.error?`<small>${esc(item.error)}</small>`:''}<div class="actions">${!item.isCover&&item.status==='ready'?`<button type="button" onclick="setMediaCover('${esc(item.id)}')">Portada</button>`:''}${item.status==='failed'?`<button type="button" onclick="retryMedia('${esc(item.id)}')">Reintentar</button>`:''}<button type="button" class="danger" onclick="deleteMedia('${esc(item.id)}')">Eliminar</button></div></article>`;
}
async function uploadMedia(){
  const productId=$('productId').value; const files=[...$('mediaFiles').files];
  if(!productId){$('notice').textContent='Guarda primero el producto.';return;} if(!files.length){$('notice').textContent='Selecciona una o más imágenes.';return;}
  const form=new FormData(); files.forEach(file=>form.append('files',file)); form.append('variant_id',$('mediaVariant').value||'');
  $('mediaStatus').textContent=`Subiendo ${files.length}…`;
  try{const data=await api(`/api/admin/catalog/products/${productId}/images/batch`,{method:'POST',body:form}); $('notice').textContent=`${data.summary.accepted} guardadas, ${data.summary.duplicates} repetidas, ${data.summary.failed} fallidas.`; $('mediaFiles').value=''; await loadMedia(productId); await load();}
  catch(e){$('notice').textContent=e.message;$('mediaStatus').textContent='Error';}
}
async function setMediaCover(assetId){try{await api(`/api/admin/catalog/products/${$('productId').value}/images/${assetId}/cover`,{method:'PUT',body:'{}'});await loadMedia($('productId').value);await load();}catch(e){$('notice').textContent=e.message;}}
async function retryMedia(assetId){try{await api(`/api/admin/catalog/images/${assetId}/retry`,{method:'POST',body:'{}'});await loadMedia($('productId').value);}catch(e){$('notice').textContent=e.message;}}
async function deleteMedia(assetId){if(!confirm('¿Eliminar esta fotografía del producto?'))return;try{await api(`/api/admin/catalog/products/${$('productId').value}/images/${assetId}?confirm=true`,{method:'DELETE'});await loadMedia($('productId').value);}catch(e){$('notice').textContent=e.message;}}
$('uploadMedia')?.addEventListener('click',uploadMedia);
$('previousPage')?.addEventListener('click',()=>{if(state.page>1){state.page--;load();}});
$('nextPage')?.addEventListener('click',()=>{if(state.page<state.pages){state.page++;load();}});
$('pageSize')?.addEventListener('change',()=>{state.pageSize=Number($('pageSize').value||30);state.page=1;load();});
$('openTrash')?.addEventListener('click',()=>{$('trashPanel').classList.add('open');loadTrash();});
$('closeTrash')?.addEventListener('click',()=>$('trashPanel').classList.remove('open'));

async function loadTrash(){
  $('trashStatus').textContent='Cargando papelera…';
  try{
    const data=await api('/api/scalability/trash?limit=200');
    const items=data.items||[];
    $('trashStatus').textContent=`${items.length} producto(s) recuperable(s).`;
    $('trashItems').innerHTML=items.length?items.map(item=>{
      let snapshot={};try{snapshot=JSON.parse(item.snapshot_json||'{}')}catch{}
      const title=snapshot.title||snapshot.name||item.product_id||'Producto';
      return `<article class="product-row" style="cursor:default"><span class="product-thumb placeholder">↺</span><span><b>${esc(title)}</b><small>Eliminado: ${esc(item.deleted_at||'')}</small><small>${esc(item.reason||'Sin motivo')}</small></span><span class="actions"><button type="button" onclick="restoreTrash('${esc(item.id)}')">Restaurar</button></span></article>`;
    }).join(''):'<p class="empty">La papelera está vacía.</p>';
  }catch(e){$('trashStatus').textContent=e.message;}
}
async function restoreTrash(id){
  try{
    await api('/api/scalability/trash/'+encodeURIComponent(id)+'/restore',{method:'POST',body:'{}'});
    await loadTrash();
    state.page=1;
    await load();
  }catch(e){$('trashStatus').textContent=e.message;}
}
window.restoreTrash=restoreTrash;
