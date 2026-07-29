const $ = (id) => document.getElementById(id);
let state = {products: [], facets: {}, selected: null};

function money(value){return new Intl.NumberFormat('es-MX',{style:'currency',currency:'MXN'}).format(Number(value||0));}
function esc(value){return String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
async function api(url, options={}){
  const headers={...(options.headers||{})}; if(!(options.body instanceof FormData)) headers['content-type']='application/json';
  const response = await fetch(url,{...options,headers});
  const data = await response.json().catch(()=>({detail:'Respuesta inválida'}));
  if(!response.ok) throw new Error(data.detail||'No se pudo completar la operación.');
  return data;
}
function query(){const p=new URLSearchParams();['q','category','brand','status'].forEach(k=>{const el=$(k);if(el?.value)p.set(k,el.value)});return p.toString();}
async function load(){
  const data=await api('/api/admin/catalog/products?'+query());state.products=data.products;state.facets=data.facets;renderFilters();render();
  const pubs=await api('/api/admin/publications');
  $('publishedCount').textContent=pubs.products.filter(x=>x.status==='published').length;
  $('draftCount').textContent=pubs.products.filter(x=>x.status==='draft').length;
  $('soldCount').textContent=state.products.filter(x=>Number(x.stock||0)<=0).length;
  try{const req=await api('/api/public/requests?status=new');$('requestCount').textContent=(req.requests||[]).length}catch{$('requestCount').textContent='—'}
}
function renderFilters(){
  const fill=(id,items,label)=>{const el=$(id);const current=el.value;el.innerHTML=`<option value="">${label}</option>`+(items||[]).map(x=>`<option ${x===current?'selected':''}>${esc(x)}</option>`).join('')};
  fill('category',state.facets.categories,'Todas las categorías');fill('brand',state.facets.brands,'Todas las marcas');fill('status',state.facets.statuses,'Todos los estados');
}
function render(){
  $('adminProducts').innerHTML=state.products.length?state.products.map(p=>`<button class="product-row" onclick="editProduct('${esc(p.id)}')"><span><b>${esc(p.title||'Sin nombre')}</b><small>${esc([p.brand,p.model,p.category].filter(Boolean).join(' · '))}</small></span><span><b>${money(p.price)}</b><small>${Number(p.stock||0)} disponibles</small></span></button>`).join(''):'<p class="empty">No hay productos con estos filtros.</p>';
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
async function removeProduct(){const id=$('productId').value;if(!id||!confirm('¿Eliminar definitivamente este producto y sus variantes?'))return;try{await api('/api/admin/catalog/products/'+id+'?confirm=true',{method:'DELETE'});closeEditor();await load();}catch(e){$('notice').textContent=e.message;}}
async function duplicates(){const d=await api('/api/admin/catalog/duplicates');alert(`Hashes de imagen: ${d.imageHashCount}\nGrupos probables duplicados: ${d.probableGroupCount}`);}
['q','category','brand','status'].forEach(id=>$(id)?.addEventListener(id==='q'?'input':'change',()=>{clearTimeout(window._f);window._f=setTimeout(load,180)}));
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
