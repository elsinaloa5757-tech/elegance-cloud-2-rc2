from __future__ import annotations

import csv, hashlib, io, json, mimetypes, re, shutil, sqlite3, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, ImageStat
from services.state_store import database_path, load_state, save_state
from services.elegance_studio import create_preview, decide
from services.cloud_storage import store_bytes
from services.public_catalog import sync_products, update_publication
from services.universal_products import classify as universal_classify, settings as automation_settings, queue_review, save_product_attributes

ROOT=Path(__file__).resolve().parents[1]
from services.runtime_config import data_dir
DATA=data_dir(); PRODUCT_DIR=DATA/'products'; ORIGINAL_DIR=PRODUCT_DIR/'originals'
DB=Path(database_path())

BRANDS=['Nike','Jordan','Adidas','Puma','New Balance','Converse','Vans','Reebok','Under Armour','Timberland','Gucci','Louis Vuitton','Dior','Balenciaga','Versace','Skechers','Crocs','Asics','Fila','Salomon','Hoka','On']
CATEGORY_WORDS={
 'Tenis':['tenis','sneaker','sneakers','jordan','air max','dunk','yeezy','gazelle','samba','forum','running'],
 'Calzado':['bota','botin','zapato','sandalia','mocasin','tacon'],
 'Ropa':['playera','camisa','sudadera','pantalon','short','chamarra','vestido'],
 'Accesorios':['gorra','bolsa','mochila','reloj','pulsera','cinturon','cartera'],
}
COLORS=['negro','blanco','azul','rojo','verde','gris','beige','cafe','marron','rosa','morado','amarillo','naranja','dorado','plateado']

def now()->str:return datetime.now(timezone.utc).isoformat()
def _db():
 c=sqlite3.connect(DB,timeout=30);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c

def migrate_sprint6()->dict:
 PRODUCT_DIR.mkdir(parents=True,exist_ok=True);ORIGINAL_DIR.mkdir(parents=True,exist_ok=True)
 with _db() as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS product_variants(
   id TEXT PRIMARY KEY,product_id TEXT NOT NULL,size TEXT NOT NULL DEFAULT '',color TEXT NOT NULL DEFAULT '',
   sku TEXT NOT NULL DEFAULT '',stock INTEGER NOT NULL DEFAULT 0,purchase_price REAL NOT NULL DEFAULT 0,
   sale_price REAL NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'available',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
   UNIQUE(product_id,size,color));
  CREATE TABLE IF NOT EXISTS inventory_movements(
   id TEXT PRIMARY KEY,product_id TEXT NOT NULL,variant_id TEXT NOT NULL DEFAULT '',movement_type TEXT NOT NULL,
   quantity INTEGER NOT NULL,before_stock INTEGER NOT NULL,after_stock INTEGER NOT NULL,note TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS product_image_hashes(
   sha256 TEXT PRIMARY KEY,product_id TEXT NOT NULL,original_path TEXT NOT NULL,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL);
  ''')
  c.execute("INSERT OR IGNORE INTO app_settings VALUES('hide_sold_out','1',?)",(now(),))
 return {'status':'ok','version':'6.0.0-rc1'}

def _products_state():
 s=load_state();
 if not isinstance(s,dict):s={}
 s.setdefault('products',[])
 return s,s['products']

def _slugish(v:str)->str:return re.sub(r'[^a-z0-9]+','-',v.lower()).strip('-')
def _safe_name(name:str)->str:
 ext=Path(name).suffix.lower()
 if ext not in {'.jpg','.jpeg','.png','.webp','.heic'}:ext='.jpg'
 return uuid.uuid4().hex+ext

def _image_hash(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def _existing_hash(digest:str)->dict|None:
 with _db() as c:r=c.execute('SELECT * FROM product_image_hashes WHERE sha256=?',(digest,)).fetchone()
 return dict(r) if r else None

def detect_metadata(filenames:list[str],manual:dict|None=None)->dict:
 manual=manual or {}; text=' '.join(filenames).lower().replace('_',' ').replace('-',' ')
 brand=next((b for b in BRANDS if b.lower() in text),'')
 category='Otros'
 for cat,words in CATEGORY_WORDS.items():
  if any(w in text for w in words):category=cat;break
 color=next((c.title() for c in COLORS if c in text),'')
 cleaned=re.sub(r'\.(jpg|jpeg|png|webp|heic)',' ',text)
 for b in BRANDS:cleaned=re.sub(re.escape(b.lower()),' ',cleaned)
 cleaned=re.sub(r'\b('+('|'.join(COLORS))+r')\b',' ',cleaned)
 cleaned=re.sub(r'\b(img|image|photo|foto|whatsapp|wa|received|screenshot|tenis|sneaker)\b',' ',cleaned)
 model=' '.join(dict.fromkeys(x for x in cleaned.split() if len(x)>1))[:80].title()
 return {'brand':manual.get('brand') or brand,'model':manual.get('model') or model,'category':manual.get('category') or category,'color':manual.get('color') or color,'type':manual.get('type') or category,'confidence':0.72 if brand else 0.35,'method':'local filename + library heuristics'}



def _dhash_image(img: Image.Image, size: int = 8) -> int:
 gray=ImageOps.exif_transpose(img).convert('L').resize((size+1,size),Image.Resampling.LANCZOS)
 px=list(gray.getdata());value=0;bit=0
 for y in range(size):
  row=y*(size+1)
  for x in range(size):
   if px[row+x]>px[row+x+1]:value|=1<<bit
   bit+=1
 return value

def _visual_signature(data:bytes)->tuple[int,list[float]]:
 img=Image.open(io.BytesIO(data));img.load();img=ImageOps.exif_transpose(img).convert('RGB')
 # Give the central product area more weight than the repeated WhatsApp/background frame.
 w,h=img.size;box=(int(w*.14),int(h*.12),int(w*.86),int(h*.88));crop=img.crop(box).resize((96,96),Image.Resampling.LANCZOS)
 hist=[]
 for channel in crop.split():
  raw=channel.histogram()
  hist.extend(sum(raw[i*16:(i+1)*16])/(96*96) for i in range(16))
 stat=ImageStat.Stat(crop);hist.extend(x/255 for x in stat.mean)
 norm=sum(x*x for x in hist)**.5 or 1
 return _dhash_image(crop),[x/norm for x in hist]

def _visual_groups(files:list[tuple[str,bytes]])->list[dict]:
 items=[]
 for i,(name,data) in enumerate(files):
  try:
   ph,feat=_visual_signature(data);items.append({'index':i,'filename':name,'ph':ph,'feat':feat})
  except Exception:
   items.append({'index':i,'filename':name,'ph':None,'feat':[]})
 groups=[]
 for item in items:
  placed=False
  for group in groups:
   compatible=False
   for other in group:
    if item['ph'] is None or other['ph'] is None:continue
    ham=(item['ph']^other['ph']).bit_count()
    cos=sum(a*b for a,b in zip(item['feat'],other['feat']))
    # Conservative by design: false separation is safer than mixing models.
    if ham<=13 and cos>=.982:
     compatible=True;break
   if compatible:
    group.append(item);placed=True;break
  if not placed:groups.append([item])
 return [{'group':n+1,'indices':[x['index'] for x in g],'filenames':[x['filename'] for x in g],'count':len(g)} for n,g in enumerate(groups)]

def analyze_uploads(files:list[tuple[str,bytes]])->dict:
 migrate_sprint6();dups=[]
 for name,data in files:
  hit=_existing_hash(_image_hash(data))
  if hit:dups.append({'filename':name,**hit})
 meta=detect_metadata([n for n,_ in files])
 s,products=_products_state();matches=[]
 for p in products:
  score=0
  if meta['brand'] and str(p.get('brand','')).lower()==meta['brand'].lower():score+=1
  if meta['model'] and str(p.get('model','')).lower()==meta['model'].lower():score+=2
  if score:matches.append({'id':p.get('id'),'title':p.get('title'),'brand':p.get('brand'),'model':p.get('model'),'colors':p.get('colors',[]),'sizes':p.get('sizes',[]),'score':score})
 matches.sort(key=lambda x:-x['score'])
 groups=_visual_groups(files)
 return {'status':'ok','suggestion':meta,'duplicateImages':dups,'possibleProducts':matches[:10],
         'groups':groups,'multipleProductsLikely':len(groups)>1,
         'classification':('duplicate' if dups else 'variant' if matches and matches[0]['score']>=3 else 'new')}

def _normalize_list(v:Any)->list[str]:
 if isinstance(v,list):return [str(x).strip() for x in v if str(x).strip()]
 return [x.strip() for x in re.split(r'[,;/|]+',str(v or '')) if x.strip()]

def create_product(payload:dict,files:list[tuple[str,bytes]],edited_files:list[tuple[str,bytes]]|None=None)->dict:
 migrate_sprint6()
 if not files:raise ValueError('Selecciona al menos una fotografía.')
 analysis=analyze_uploads(files)
 multi_mode=str(payload.get('multiProductMode') or 'protect').lower()
 groups=analysis.get('groups') or []
 if len(groups)>1 and multi_mode=='protect':
  raise ValueError(f'Se detectaron {len(groups)} productos visualmente diferentes. Selecciona “Crear un producto por grupo” para evitar mezclarlos en una sola ficha.')
 if len(groups)>1 and multi_mode=='separate':
  edited_by_name={name:data for name,data in (edited_files or [])}
  created=[]
  base_title=str(payload.get('title') or 'Producto por confirmar').strip()
  for pos,g in enumerate(groups,1):
   subset=[files[i] for i in g.get('indices',[]) if 0<=i<len(files)]
   subset_edited=[(name,edited_by_name[name]) for name,_ in subset if name in edited_by_name]
   child=dict(payload);child['multiProductMode']='same';child['existingProductId']='';child['publish']=False
   if len(groups)>1:child['title']=f'{base_title} {pos}'
   created.append(create_product(child,subset,subset_edited))
  return {'status':'ok','separated':True,'groupCount':len(created),'products':[x.get('product') for x in created],'results':created}
 duplicate_action=str(payload.get('duplicateAction','reject'))
 if analysis['duplicateImages'] and duplicate_action=='reject':raise ValueError('Una o más fotografías ya existen. Selecciona conservar como variante o reemplazar.')
 brand=str(payload.get('brand') or analysis['suggestion']['brand']).strip();model=str(payload.get('model') or analysis['suggestion']['model']).strip()
 category=str(payload.get('category') or analysis['suggestion']['category'] or 'Otros').strip();color=str(payload.get('color') or analysis['suggestion']['color']).strip()
 title=str(payload.get('title') or ' '.join(x for x in [brand,model,color] if x) or 'Producto Elegance').strip()
 sizes=_normalize_list(payload.get('sizes')); colors=_normalize_list(payload.get('colors') or color)
 stock=max(0,int(payload.get('quantity') or payload.get('stock') or 0));purchase=float(payload.get('purchasePrice') or 0);price=float(payload.get('salePrice') or payload.get('price') or 0)
 status=str(payload.get('status') or ('available' if stock>0 else 'sold_out'))
 existing_id=str(payload.get('existingProductId') or '').strip()
 s,products=_products_state();product=next((p for p in products if str(p.get('id'))==existing_id),None) if existing_id else None
 if product is None:
  pid='prd_'+uuid.uuid4().hex[:16]
  product={'id':pid,'title':title,'brand':brand,'model':model,'category':category,'subcategory':str(payload.get('subcategory') or ''),'type':str(payload.get('type') or category),'colors':colors,'sizes':sizes,'stock':0,'price':price,'purchasePrice':purchase,'status':status,'description':str(payload.get('description') or ''),'createdAt':now(),'updatedAt':now(),'originalImages':[],'approvedStudioImages':[],'variants':[]}
  products.append(product)
 else:
  pid=str(product['id']);product.update({'title':title or product.get('title'),'brand':brand or product.get('brand'),'model':model or product.get('model'),'category':category or product.get('category'),'subcategory':str(payload.get('subcategory') or product.get('subcategory') or ''),'type':str(payload.get('type') or product.get('type') or category),'description':str(payload.get('description') or product.get('description') or ''),'price':price or product.get('price',0),'purchasePrice':purchase or product.get('purchasePrice',0),'updatedAt':now()})
  product['colors']=sorted(set(_normalize_list(product.get('colors'))+colors));product['sizes']=sorted(set(_normalize_list(product.get('sizes'))+sizes))
 originals=[];approved=[]
 edited_map={name:data for name,data in (edited_files or [])}
 for file_index,(filename,data) in enumerate(files):
  digest=_image_hash(data);hit=_existing_hash(digest)
  if hit and duplicate_action=='skip':continue
  safe=_safe_name(filename);path=ORIGINAL_DIR/safe;path.write_bytes(data)
  stored=store_bytes(
   f'products/{pid}/originals/{safe}',
   data,
   mimetypes.guess_type(filename)[0] or 'application/octet-stream',
  )
  rel=str(stored['primary']['publicUrl']);originals.append(rel)
  try:
   from services.media_library import register_bytes
   register_bytes(data,filename,pid,'new-product','original',{'legacyUrl':rel})
  except Exception:
   pass
  process_data=edited_map.get(filename) or edited_map.get(str(file_index)) or data
  try:
   preview=create_preview(process_data,filename,pid,{'formats':['catalog','thumbnail','whatsapp'],'removeBackground':bool(payload.get('removeBackground',False)),'background':str(payload.get('background') or 'original'),'quality':88,'brightness':1.0,'contrast':1.0,'color':1.0,'sharpness':1.0})
   if preview.get('status')=='preview':
    result=decide(preview['versionId'],'approve');outs=result.get('outputs',{})
    for output_path in outs.values():
     local_output=ROOT/output_path
     if not local_output.exists():continue
     cloud_output=store_bytes(
      f'products/{pid}/studio/{local_output.name}',
      local_output.read_bytes(),
      mimetypes.guess_type(local_output.name)[0] or 'application/octet-stream',
     )
     approved.append(str(cloud_output['primary']['publicUrl']))
  except Exception:
   pass
  with _db() as c:c.execute('INSERT OR REPLACE INTO product_image_hashes VALUES(?,?,?,?)',(digest,pid,rel,now()))
 product['originalImages']=list(dict.fromkeys(product.get('originalImages',[])+originals));product['approvedStudioImages']=list(dict.fromkeys(product.get('approvedStudioImages',[])+approved))
 if approved:product['approvedStudioImage']=approved[0]
 elif originals:product['image']=originals[0]
 variant_id='var_'+uuid.uuid4().hex[:16];size_key=sizes[0] if len(sizes)==1 else ', '.join(sizes);color_key=colors[0] if len(colors)==1 else ', '.join(colors)
 with _db() as c:
  old=c.execute('SELECT * FROM product_variants WHERE product_id=? AND size=? AND color=?',(pid,size_key,color_key)).fetchone()
  before=int(old['stock']) if old else 0;after=before+stock
  if old:
   variant_id=old['id'];c.execute('UPDATE product_variants SET stock=?,purchase_price=?,sale_price=?,status=?,updated_at=? WHERE id=?',(after,purchase,price,status,now(),variant_id))
  else:c.execute('INSERT INTO product_variants VALUES(?,?,?,?,?,?,?,?,?,?,?)',(variant_id,pid,size_key,color_key,str(payload.get('sku') or ''),stock,purchase,price,status,now(),now()))
  c.execute('INSERT INTO inventory_movements VALUES(?,?,?,?,?,?,?,?,?)',('mov_'+uuid.uuid4().hex[:16],pid,variant_id,'entry',stock,before,after,'Alta desde Nuevo producto',now()))
 product['stock']=sum_variant_stock(pid);product['status']='available' if product['stock']>0 else 'sold_out'
 # Persist category-specific fields without altering the legacy product schema.
 attrs=payload.get('attributes') if isinstance(payload.get('attributes'),dict) else {}
 save_product_attributes(pid,attrs,'confirmed' if payload.get('classificationConfirmed') else 'manual')
 # Enforce reviewed mode: uncertain products are saved, but never published until confirmed.
 universal=universal_classify({'title':title,'brand':brand,'model':model,'description':product.get('description','')})
 mode=automation_settings().get('mode','reviewed')
 confirmed=bool(payload.get('classificationConfirmed'))
 queued=None
 publish_requested=bool(payload.get('publish'))
 can_publish=publish_requested and (mode!='reviewed' or confirmed) and not (mode=='automatic' and universal.get('needsReview'))
 if (universal.get('needsReview') or (mode=='reviewed' and not confirmed)):
  queued=queue_review({'product_id':pid,'source_name':title,'title':title,'brand':brand,'model':model,'description':product.get('description','')})
 product['category']=str(payload.get('category') or universal.get('category') or category)
 product['subcategory']=str(payload.get('subcategory') or universal.get('subcategory') or '')
 product['catalogPath']=f"{product['category']}/{product['subcategory']}/{brand or 'Sin identificar'}/{model or 'Modelo pendiente'}"
 save_state(s);sync_products()
 if can_publish:
  update_publication(pid,{'status':'published','publicTitle':title,'publicDescription':product.get('description',''),'hideWhenSoldOut':True})
 return {'status':'ok','product':product,'analysis':analysis,'universalClassification':universal,'review':queued,'created':not bool(existing_id),'published':can_publish,'publicationBlocked':publish_requested and not can_publish}

def sum_variant_stock(pid:str)->int:
 with _db() as c:return int(c.execute('SELECT COALESCE(SUM(stock),0) FROM product_variants WHERE product_id=?',(pid,)).fetchone()[0])

def list_inventory()->list[dict]:
 migrate_sprint6();s,products=_products_state();out=[]
 with _db() as c:
  for p in products:
   variants=[dict(x) for x in c.execute('SELECT * FROM product_variants WHERE product_id=? ORDER BY size,color',(str(p.get('id')),)).fetchall()]
   q=dict(p);q['variants']=variants;q['stock']=sum(int(v['stock']) for v in variants) if variants else int(p.get('stock') or 0);q['lowStock']=0<q['stock']<=2;out.append(q)
 return out

def adjust_stock(pid:str,variant_id:str,quantity:int,note:str='')->dict:
 if quantity==0:raise ValueError('La cantidad no puede ser cero.')
 with _db() as c:
  v=c.execute('SELECT * FROM product_variants WHERE id=? AND product_id=?',(variant_id,pid)).fetchone()
  if not v:raise ValueError('Variante no encontrada.')
  before=int(v['stock']);after=before+quantity
  if after<0:raise ValueError('La salida supera la existencia disponible.')
  c.execute('UPDATE product_variants SET stock=?,status=?,updated_at=? WHERE id=?',(after,'available' if after>0 else 'sold_out',now(),variant_id))
  c.execute('INSERT INTO inventory_movements VALUES(?,?,?,?,?,?,?,?,?)',('mov_'+uuid.uuid4().hex[:16],pid,variant_id,'entry' if quantity>0 else 'exit',quantity,before,after,note,now()))
 s,products=_products_state();p=next((x for x in products if str(x.get('id'))==pid),None)
 if p:p['stock']=sum_variant_stock(pid);p['status']='available' if p['stock']>0 else 'sold_out';p['updatedAt']=now();save_state(s)
 return {'status':'ok','productId':pid,'variantId':variant_id,'before':before,'after':after}

def movements(limit:int=200)->list[dict]:
 with _db() as c:return [dict(x) for x in c.execute('SELECT * FROM inventory_movements ORDER BY created_at DESC LIMIT ?',(min(max(limit,1),1000),)).fetchall()]

def exports_zip()->Path:
 folder=DATA/'exports';folder.mkdir(exist_ok=True);stamp=datetime.now().strftime('%Y%m%d_%H%M%S');target=folder/f'elegance_export_{stamp}.zip'
 inventory=list_inventory()
 with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
  for name,rows in [('inventario',inventory)]:
   buf=io.StringIO();fields=['id','title','brand','model','category','stock','price','purchasePrice','status'];w=csv.DictWriter(buf,fieldnames=fields);w.writeheader();w.writerows({k:r.get(k,'') for k in fields} for r in rows);z.writestr(name+'.csv',buf.getvalue().encode('utf-8-sig'))
  with _db() as c:
   for table in ['customers','orders','order_items','payments','inventory_movements','product_variants']:
    rows=[dict(x) for x in c.execute(f'SELECT * FROM {table}').fetchall()];buf=io.StringIO();
    if rows:
     w=csv.DictWriter(buf,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
    z.writestr(table+'.csv',buf.getvalue().encode('utf-8-sig'))
  z.write(DB,'elegance.sqlite3')
 return target
