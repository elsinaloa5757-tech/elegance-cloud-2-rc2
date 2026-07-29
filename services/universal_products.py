from __future__ import annotations
import json, re, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from services.state_store import database_path, load_state, save_state

DB=Path(database_path()); MODES={'automatic','reviewed','manual_assisted'}; DEFAULT_MODE='reviewed'
TAXONOMY={
'Calzado':{'Tenis':['tenis','sneaker','dunk','jordan','air max','running'],'Botas':['bota','boot','timberland'],'Botines':['botin','chelsea'],'Zapatos':['zapato','oxford','mocasin','loafer'],'Sandalias':['sandalia','slide'],'Tacones':['tacon','heel']},
'Ropa':{'Playeras':['playera','camiseta','tee','t-shirt'],'Camisas':['camisa','shirt'],'Sudaderas':['sudadera','hoodie'],'Chamarras':['chamarra','chaqueta','jacket'],'Pantalones':['pantalon','pants'],'Jeans':['jeans','denim'],'Shorts':['short'],'Vestidos':['vestido','dress'],'Faldas':['falda','skirt'],'Ropa interior':['ropa interior','boxer','brasier','panty','lenceria']},
'Perfumería':{'Fragancias':['perfume','fragancia','eau de parfum','eau de toilette','edp','edt','colonia'],'Sets':['set perfume','estuche perfume'],'Cuidado personal':['desodorante','body spray']},
'Bolsas':{'Bolsos':['bolso','bolsa','handbag'],'Mochilas':['mochila','backpack'],'Crossbody':['crossbody'],'Tote':['tote'],'Carteras':['cartera','wallet']},
'Accesorios':{'Gorras':['gorra','cap'],'Cinturones':['cinturon','belt'],'Lentes':['lentes','gafas','sunglasses'],'Bufandas':['bufanda','scarf'],'Guantes':['guante','glove'],'Llaveros':['llavero','keychain']},
'Joyería':{'Relojes':['reloj','watch'],'Pulseras':['pulsera','bracelet'],'Collares':['collar','necklace'],'Anillos':['anillo','ring'],'Aretes':['arete','earring']},
'Otros':{'Coleccionables':['coleccionable'],'Cuidado del producto':['limpiador','protector','care kit'],'Empaque':['empaque','caja']}}
FIELDS={'Calzado':['size','number','material','color','gender'],'Ropa':['size','fit','material','color','gender','season'],'Perfumería':['milliliters','concentration','fragrance_name','presentation','olfactory_family','gender'],'Bolsas':['dimensions','material','color','capacity'],'Accesorios':['dimensions','material','color','compatibility','type'],'Joyería':['dimensions','material','color','size'],'Otros':['type','material','color']}

def _now(): return datetime.now(timezone.utc).isoformat()
def _db():
 c=sqlite3.connect(DB,timeout=30); c.row_factory=sqlite3.Row; return c

def migrate_universal_products():
 with _db() as c:
  c.executescript("""
  CREATE TABLE IF NOT EXISTS automation_settings(id INTEGER PRIMARY KEY CHECK(id=1),mode TEXT NOT NULL DEFAULT 'reviewed',publish_confidence REAL NOT NULL DEFAULT .90,classify_confidence REAL NOT NULL DEFAULT .62,updated_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS recognition_reviews(id TEXT PRIMARY KEY,product_id TEXT NOT NULL DEFAULT '',source_name TEXT NOT NULL DEFAULT '',proposed_category TEXT NOT NULL DEFAULT '',proposed_subcategory TEXT NOT NULL DEFAULT '',proposed_brand TEXT NOT NULL DEFAULT '',proposed_model TEXT NOT NULL DEFAULT '',confidence REAL NOT NULL DEFAULT 0,evidence_json TEXT NOT NULL DEFAULT '[]',status TEXT NOT NULL DEFAULT 'pending',correction_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS product_attributes(id TEXT PRIMARY KEY,product_id TEXT NOT NULL,attribute_key TEXT NOT NULL,attribute_value TEXT NOT NULL DEFAULT '',source TEXT NOT NULL DEFAULT 'manual',confidence REAL NOT NULL DEFAULT 1,updated_at TEXT NOT NULL,UNIQUE(product_id,attribute_key));
  CREATE TABLE IF NOT EXISTS recognition_corrections(id TEXT PRIMARY KEY,review_id TEXT NOT NULL DEFAULT '',product_id TEXT NOT NULL DEFAULT '',category TEXT NOT NULL DEFAULT '',subcategory TEXT NOT NULL DEFAULT '',brand TEXT NOT NULL DEFAULT '',model TEXT NOT NULL DEFAULT '',attributes_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL);
  """)
  c.execute("INSERT OR IGNORE INTO automation_settings VALUES(1,'reviewed',.90,.62,?)",(_now(),))
 return {'status':'ok','database':str(DB)}

def settings():
 migrate_universal_products()
 with _db() as c:return dict(c.execute('SELECT * FROM automation_settings WHERE id=1').fetchone())

def update_settings(p):
 mode=str(p.get('mode',DEFAULT_MODE))
 if mode not in MODES: raise ValueError('Modo de automatización no válido.')
 pub=max(.5,min(.99,float(p.get('publish_confidence',.9)))); cls=max(.3,min(.99,float(p.get('classify_confidence',.62))))
 with _db() as c:c.execute('UPDATE automation_settings SET mode=?,publish_confidence=?,classify_confidence=?,updated_at=? WHERE id=1',(mode,pub,cls,_now()))
 return settings()

def classify(p):
 text=' '.join(str(p.get(k,'') or '') for k in ('title','name','description','brand','model','ocr_text','notes')).lower(); text=re.sub(r'\s+',' ',text)
 best=('Otros','Coleccionables',0,[])
 for cat,subs in TAXONOMY.items():
  for sub,words in subs.items():
   hits=[w for w in words if w in text]
   if len(hits)>best[2]:best=(cat,sub,len(hits),hits)
 cat,sub,score,hits=best; confidence=.35 if score==0 else min(.98,.58+.11*score)
 return {'category':cat,'subcategory':sub,'confidence':round(confidence,3),'evidence':hits,'needsReview':confidence<float(settings()['classify_confidence']),'requiredFields':FIELDS.get(cat,[]),'catalogPath':f"{cat}/{sub}/{p.get('brand') or 'Sin identificar'}/{p.get('model') or 'Modelo pendiente'}"}

def queue_review(p):
 result=classify(p); rid=uuid.uuid4().hex; stamp=_now()
 with _db() as c:c.execute("INSERT INTO recognition_reviews(id,product_id,source_name,proposed_category,proposed_subcategory,proposed_brand,proposed_model,confidence,evidence_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'pending',?,?)",(rid,str(p.get('product_id','')),str(p.get('source_name','')),result['category'],result['subcategory'],str(p.get('brand','')),str(p.get('model','')),result['confidence'],json.dumps(result['evidence'],ensure_ascii=False),stamp,stamp))
 return {'status':'ok','reviewId':rid,**result}

def list_reviews(status='pending',limit=100):
 migrate_universal_products()
 with _db() as c:rows=c.execute('SELECT * FROM recognition_reviews WHERE status=? ORDER BY created_at DESC LIMIT ?',(status,max(1,min(500,int(limit))))).fetchall()
 out=[]
 for row in rows:
  x=dict(row);x['evidence']=json.loads(x.pop('evidence_json') or '[]');x['correction']=json.loads(x.pop('correction_json') or '{}');out.append(x)
 return out

def resolve_review(rid,p):
 action=str(p.get('action','approve')).lower()
 if action not in {'approve','correct','reject'}:raise ValueError('Acción no válida.')
 with _db() as c:
  row=c.execute('SELECT * FROM recognition_reviews WHERE id=?',(rid,)).fetchone()
  if not row:raise KeyError('Revisión no encontrada.')
  corr={k:p.get(k) for k in ('category','subcategory','brand','model','attributes') if k in p}; status={'approve':'approved','correct':'corrected','reject':'rejected'}[action]
  c.execute('UPDATE recognition_reviews SET status=?,correction_json=?,updated_at=? WHERE id=?',(status,json.dumps(corr,ensure_ascii=False),_now(),rid))
  if action=='correct':c.execute('INSERT INTO recognition_corrections VALUES(?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,rid,row['product_id'],str(p.get('category',row['proposed_category'])),str(p.get('subcategory',row['proposed_subcategory'])),str(p.get('brand',row['proposed_brand'])),str(p.get('model',row['proposed_model'])),json.dumps(p.get('attributes',{}),ensure_ascii=False),_now()))
 return {'status':'ok','reviewId':rid,'reviewStatus':status,'correction':corr}

def taxonomy_payload():return {'taxonomy':TAXONOMY,'fieldsByCategory':FIELDS,'modes':sorted(MODES),'defaultMode':DEFAULT_MODE}


def save_product_attributes(product_id:str, attributes:dict, source:str='manual')->dict:
 migrate_universal_products()
 stamp=_now(); saved=0
 with _db() as c:
  for key,value in (attributes or {}).items():
   if value is None or str(value).strip()=='': continue
   c.execute("INSERT INTO product_attributes(id,product_id,attribute_key,attribute_value,source,confidence,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(product_id,attribute_key) DO UPDATE SET attribute_value=excluded.attribute_value,source=excluded.source,confidence=excluded.confidence,updated_at=excluded.updated_at",(uuid.uuid4().hex,product_id,str(key),str(value).strip(),source,1.0,stamp));saved+=1
 return {'status':'ok','productId':product_id,'saved':saved}

def product_attributes(product_id:str)->dict:
 migrate_universal_products()
 with _db() as c: rows=c.execute('SELECT attribute_key,attribute_value,source,confidence,updated_at FROM product_attributes WHERE product_id=? ORDER BY attribute_key',(product_id,)).fetchall()
 return {r['attribute_key']:{'value':r['attribute_value'],'source':r['source'],'confidence':r['confidence'],'updatedAt':r['updated_at']} for r in rows}


def _product_bundle(product_id:str)->dict:
 state=load_state(); products=state.get('products',[]) if isinstance(state,dict) else []
 product=next((x for x in products if str(x.get('id'))==str(product_id)),None)
 if not product:return {}
 images=[]
 for key in ('catalogImage','image','imagePath'):
  v=product.get(key)
  if isinstance(v,str) and v and v not in images:images.append(v)
 for key in ('originalImages','images','approvedStudioImages'):
  for v in product.get(key,[]) if isinstance(product.get(key),list) else []:
   v=v.get('path') if isinstance(v,dict) else v
   if isinstance(v,str) and v and v not in images:images.append(v)
 attrs={k:v.get('value','') for k,v in product_attributes(product_id).items()}
 with _db() as c:
  variants=[dict(r) for r in c.execute('SELECT * FROM product_variants WHERE product_id=? ORDER BY size,color',(product_id,)).fetchall()]
 return {'product':product,'images':images,'attributes':attrs,'variants':variants}

def review_detail(rid:str)->dict:
 migrate_universal_products()
 with _db() as c: row=c.execute('SELECT * FROM recognition_reviews WHERE id=?',(rid,)).fetchone()
 if not row: raise KeyError('Revisión no encontrada.')
 x=dict(row);x['evidence']=json.loads(x.pop('evidence_json') or '[]');x['correction']=json.loads(x.pop('correction_json') or '{}');x.update(_product_bundle(x.get('product_id','')))
 return x

def save_review_draft(rid:str,p:dict,publish:bool=False)->dict:
 r=review_detail(rid); pid=str(r.get('product_id') or '')
 if not pid: raise ValueError('La revisión no está vinculada a un producto guardado.')
 state=load_state(); products=state.get('products',[]) if isinstance(state,dict) else []
 product=next((x for x in products if str(x.get('id'))==pid),None)
 if not product: raise ValueError('Producto no encontrado.')
 try:
  from services.universal_intelligence import snapshot_product
  snapshot_product(pid,'Antes de publicar' if publish else 'Antes de guardar borrador','review')
 except Exception:
  pass
 for key in ('title','brand','model','category','subcategory','description','supplier'):
  if key in p: product[key]=str(p.get(key) or '').strip()
 for key in ('price','purchasePrice'):
  if key in p: product[key]=max(0,float(p.get(key) or 0))
 cover=str(p.get('catalogImage') or '').strip()
 if cover: product['catalogImage']=cover
 attrs=p.get('attributes') if isinstance(p.get('attributes'),dict) else {}
 save_product_attributes(pid,attrs,'review')
 variants=p.get('variants') if isinstance(p.get('variants'),list) else None
 if variants is not None:
  with _db() as c:
   c.execute('DELETE FROM product_variants WHERE product_id=?',(pid,))
   for v in variants:
    size=str(v.get('size') or '').strip(); color=str(v.get('color') or '').strip(); stock=max(0,int(v.get('stock') or 0)); sale=max(0,float(v.get('sale_price',product.get('price',0)) or 0)); purchase=max(0,float(v.get('purchase_price',product.get('purchasePrice',0)) or 0))
    c.execute('INSERT INTO product_variants VALUES(?,?,?,?,?,?,?,?,?,?,?)',('var_'+uuid.uuid4().hex[:16],pid,size,color,str(v.get('sku') or ''),stock,purchase,sale,'available' if stock>0 else 'sold_out',_now(),_now()))
  product['sizes']=sorted({str(v.get('size') or '').strip() for v in variants if str(v.get('size') or '').strip()}); product['colors']=sorted({str(v.get('color') or '').strip() for v in variants if str(v.get('color') or '').strip()}); product['stock']=sum(max(0,int(v.get('stock') or 0)) for v in variants)
 product['updatedAt']=_now(); save_state(state)
 corr={'title':product.get('title',''),'category':product.get('category',''),'subcategory':product.get('subcategory',''),'brand':product.get('brand',''),'model':product.get('model',''),'attributes':attrs}
 with _db() as c:c.execute('UPDATE recognition_reviews SET correction_json=?,updated_at=? WHERE id=?',(json.dumps(corr,ensure_ascii=False),_now(),rid))
 if publish:
  missing=[]
  for key,label in [('title','Nombre'),('category','Categoría'),('subcategory','Subcategoría'),('brand','Marca'),('model','Modelo')]:
   if not str(product.get(key) or '').strip(): missing.append(label)
  if not _product_bundle(pid).get('images'): missing.append('Fotografía')
  if float(product.get('price') or 0)<=0: missing.append('Precio de venta')
  if not variants: missing.append('Al menos una variante')
  if missing: raise ValueError('Completa antes de publicar: '+', '.join(missing)+'.')
  from services.public_catalog import update_publication, sync_products
  sync_products(); update_publication(pid,{'status':'published','publicTitle':product.get('title',''),'publicDescription':product.get('description',''),'hideWhenSoldOut':True})
  # Learn a reusable visual reference only after explicit publication/confirmation.
  try:
   import cv2
   from services.universal_intelligence import _image_path
   from services.euiv import learn_reference
   bundle=_product_bundle(pid); refs=bundle.get('images',[])[:3]
   for ref in refs:
    path=_image_path(ref)
    image=cv2.imread(str(path)) if path else None
    if image is not None:
     learn_reference(pid,str(ref),image,{'title':product.get('title',''),'brand':product.get('brand',''),'model':product.get('model',''),'category':product.get('category',''),'subcategory':product.get('subcategory',''),'colors':', '.join(product.get('colors') or []),'sku':attrs.get('sku','')},'confirmed',['Producto confirmado y publicado por el usuario'])
  except Exception:
   pass
  resolve_review(rid,{'action':'correct',**corr}); return {'status':'ok','published':True,'review':review_detail(rid)}
 return {'status':'ok','published':False,'review':review_detail(rid)}

def set_review_cover(rid:str,image_path:str)->dict:
 return save_review_draft(rid,{'catalogImage':image_path},False)

def remove_review_image(rid:str,image_path:str)->dict:
 r=review_detail(rid);pid=str(r.get('product_id') or '');state=load_state();products=state.get('products',[]) if isinstance(state,dict) else [];product=next((x for x in products if str(x.get('id'))==pid),None)
 if not product:raise ValueError('Producto no encontrado.')
 for key in ('originalImages','images','approvedStudioImages'):
  if isinstance(product.get(key),list): product[key]=[x for x in product[key] if (x.get('path') if isinstance(x,dict) else x)!=image_path]
 for key in ('catalogImage','image','imagePath','approvedStudioImage'):
  if product.get(key)==image_path: product.pop(key,None)
 save_state(state);return {'status':'ok','review':review_detail(rid)}
