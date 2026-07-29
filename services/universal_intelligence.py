from __future__ import annotations

import html, json, re, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

import cv2
import numpy as np

from recognition.ocr_engine import read_text
from services.color import dominant_color
from services.state_store import database_path, load_state, save_state
from services.universal_products import classify, product_attributes, save_product_attributes, _product_bundle
from services.euiv import migrate_euiv, local_visual_candidates, infer_footwear_from_sizes, save_candidates

DB = Path(database_path())
from services.runtime_config import data_dir
DATA_DIR = data_dir()

DEFAULTS = {
    'web_enabled': 1,
    'auto_publish': 0,
    'learning_enabled': 1,
    'local_only': 0,
    'show_evidence': 1,
    'save_decisions': 1,
    'complete_confidence': 0.72,
    'publish_confidence': 0.90,
    'web_timeout_seconds': 10,
}

BRANDS = ['Nike','Jordan','Adidas','Puma','Reebok','New Balance','Vans','Converse','Timberland','Dior','Gucci','Louis Vuitton','Hugo Boss','New Era','Asics','Hoka','Under Armour','Balenciaga','Amiri','Crocs','Guess','Coach','Versace','Chanel']
COLORS = ['negro','blanco','gris','rojo','azul','verde','amarillo','naranja','rosa','morado','café','beige','dorado','plateado']
PLACEHOLDER_PATTERNS = [r'^producto por confirmar\b', r'^\d{4}[ _-]\d{2}[ _-]\d{2}', r'^img[_ -]?\d+', r'^dsc[_ -]?\d+']


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def migrate_intelligence() -> dict[str, Any]:
    with _db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS intelligence_settings(
          id INTEGER PRIMARY KEY CHECK(id=1), web_enabled INTEGER NOT NULL DEFAULT 1,
          auto_publish INTEGER NOT NULL DEFAULT 0, learning_enabled INTEGER NOT NULL DEFAULT 1,
          local_only INTEGER NOT NULL DEFAULT 0, show_evidence INTEGER NOT NULL DEFAULT 1,
          save_decisions INTEGER NOT NULL DEFAULT 1, complete_confidence REAL NOT NULL DEFAULT .72,
          publish_confidence REAL NOT NULL DEFAULT .90, web_timeout_seconds INTEGER NOT NULL DEFAULT 10,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS intelligence_decisions(
          id TEXT PRIMARY KEY, product_id TEXT NOT NULL DEFAULT '', review_id TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0, input_json TEXT NOT NULL DEFAULT '{}',
          result_json TEXT NOT NULL DEFAULT '{}', evidence_json TEXT NOT NULL DEFAULT '[]',
          action TEXT NOT NULL DEFAULT 'suggested', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS product_versions(
          id TEXT PRIMARY KEY, product_id TEXT NOT NULL, snapshot_json TEXT NOT NULL,
          reason TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'manual', user_name TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_intelligence_product ON intelligence_decisions(product_id,created_at);
        CREATE INDEX IF NOT EXISTS idx_product_versions ON product_versions(product_id,created_at);
        ''')
        c.execute('''INSERT OR IGNORE INTO intelligence_settings
        (id,web_enabled,auto_publish,learning_enabled,local_only,show_evidence,save_decisions,complete_confidence,publish_confidence,web_timeout_seconds,updated_at)
        VALUES(1,1,0,1,0,1,1,.72,.90,10,?)''', (_now(),))
    return {'status':'ok','database':str(DB)}


def settings() -> dict[str, Any]:
    migrate_intelligence(); migrate_euiv()
    with _db() as c:
        return dict(c.execute('SELECT * FROM intelligence_settings WHERE id=1').fetchone())


def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = settings(); values = {}
    for key in ('web_enabled','auto_publish','learning_enabled','local_only','show_evidence','save_decisions'):
        values[key] = 1 if bool(payload.get(key, current[key])) else 0
    values['complete_confidence'] = max(.50,min(.99,float(payload.get('complete_confidence',current['complete_confidence']))))
    values['publish_confidence'] = max(values['complete_confidence'],min(.99,float(payload.get('publish_confidence',current['publish_confidence']))))
    values['web_timeout_seconds'] = max(3,min(25,int(payload.get('web_timeout_seconds',current['web_timeout_seconds']))))
    with _db() as c:
        c.execute('''UPDATE intelligence_settings SET web_enabled=?,auto_publish=?,learning_enabled=?,local_only=?,show_evidence=?,save_decisions=?,complete_confidence=?,publish_confidence=?,web_timeout_seconds=?,updated_at=? WHERE id=1''',
                  (*[values[k] for k in ('web_enabled','auto_publish','learning_enabled','local_only','show_evidence','save_decisions','complete_confidence','publish_confidence','web_timeout_seconds')],_now()))
    return settings()


def _product(product_id: str) -> dict[str, Any] | None:
    state = load_state()
    return next((p for p in state.get('products',[]) if str(p.get('id')) == str(product_id)), None)


def snapshot_product(product_id: str, reason: str='', source: str='manual', user_name: str='') -> str:
    p = _product(product_id)
    if not p: raise KeyError('Producto no encontrado.')
    snapshot = {'product':p,'attributes':product_attributes(product_id)}
    vid = uuid.uuid4().hex
    with _db() as c:
        c.execute('INSERT INTO product_versions VALUES(?,?,?,?,?,?,?)',(vid,product_id,json.dumps(snapshot,ensure_ascii=False),reason,source,user_name,_now()))
    return vid


def list_versions(product_id: str, limit: int=50) -> list[dict[str,Any]]:
    migrate_intelligence()
    with _db() as c:
        rows=c.execute('SELECT id,product_id,reason,source,user_name,created_at FROM product_versions WHERE product_id=? ORDER BY created_at DESC LIMIT ?',(product_id,max(1,min(200,limit)))).fetchall()
    return [dict(r) for r in rows]


def restore_version(version_id: str, user_name: str='') -> dict[str,Any]:
    with _db() as c: row=c.execute('SELECT * FROM product_versions WHERE id=?',(version_id,)).fetchone()
    if not row: raise KeyError('Versión no encontrada.')
    snap=json.loads(row['snapshot_json']); pid=row['product_id']
    snapshot_product(pid,'Copia automática antes de restaurar','restore',user_name)
    state=load_state(); products=state.get('products',[])
    idx=next((i for i,p in enumerate(products) if str(p.get('id'))==str(pid)),None)
    if idx is None: raise KeyError('Producto no encontrado.')
    products[idx]=snap['product']; products[idx]['updatedAt']=_now(); save_state(state)
    attrs={k:(v.get('value','') if isinstance(v,dict) else v) for k,v in (snap.get('attributes') or {}).items()}
    save_product_attributes(pid,attrs,'restore')
    return {'status':'ok','productId':pid,'restoredVersion':version_id}


def _is_placeholder(value: Any) -> bool:
    text=str(value or '').strip().lower()
    if not text: return True
    return any(re.search(p,text,re.I) for p in PLACEHOLDER_PATTERNS)


def _image_path(value: str) -> Path | None:
    raw=str(value or '').split('?',1)[0].replace('\\','/')
    if raw.startswith('/media/'): raw=raw[7:]
    elif raw.startswith('media/'): raw=raw[6:]
    elif raw.startswith('data/'): raw=raw[5:]
    raw=raw.lstrip('./')
    candidate=(DATA_DIR/raw).resolve()
    try: candidate.relative_to(DATA_DIR.resolve())
    except ValueError: return None
    return candidate if candidate.is_file() else None


def _load_images(product_id: str) -> tuple[list[np.ndarray], list[str], list[str]]:
    bundle=_product_bundle(product_id); arrays=[]; names=[]; paths=[]
    for value in bundle.get('images',[])[:8]:
        path=_image_path(value)
        if not path: continue
        image=cv2.imread(str(path))
        if image is None: continue
        arrays.append(image); names.append(path.name); paths.append(str(value))
    return arrays,names,paths


def _detect_brand(text: str) -> tuple[str,float,list[str]]:
    low=' '+re.sub(r'\s+',' ',text.lower())+' '
    aliases={'jumpman':'Jordan','air jordan':'Jordan','swoosh':'Nike','newbalance':'New Balance','new era':'New Era','lv':'Louis Vuitton','tn air':'Nike','air max':'Nike','three stripes':'Adidas'}
    for brand in BRANDS:
        if re.search(r'\b'+re.escape(brand.lower())+r'\b',low): return brand,.96,[f'Marca leída en texto/OCR: {brand}']
    for token,brand in aliases.items():
        if token in low:return brand,.86,[f'Marca sugerida por evidencia textual: {token} → {brand}']
    return '',0,[]


def _detect_colors_text(text: str) -> tuple[list[str],float,list[str]]:
    found=[c for c in COLORS if re.search(r'\b'+re.escape(c)+r'\b',text.lower())]
    return found, (.92 if found else 0), ([f'Colores leídos en texto: {", ".join(found)}'] if found else [])


def _size_candidates(text: str) -> list[str]:
    candidates=[]
    patterns=[r'\b(?:talla|size|n[uú]mero|num\.?)[ :#-]*([2-9]\d(?:\.5)?)\b',r'\b([2-9]\d)\s*(?:al|a|-)\s*([2-9]\d)\b',r'\b(?:us|eu|mx)\s*([2-9]\d(?:\.5)?)\b']
    for pat in patterns:
        for m in re.finditer(pat,text,re.I):
            value=' al '.join(m.groups()) if len(m.groups())==2 else m.group(1)
            if value not in candidates:candidates.append(value)
    return candidates[:8]


def _learned_matches(text: str) -> dict[str,tuple[str,float,str]]:
    words={w for w in re.findall(r'[a-z0-9]{3,}',text.lower())}
    if not words:return {}
    best={}
    with _db() as c:
        rows=c.execute('SELECT category,subcategory,brand,model,attributes_json FROM recognition_corrections ORDER BY created_at DESC LIMIT 500').fetchall()
    for row in rows:
        corpus=' '.join(str(row[k] or '') for k in ('category','subcategory','brand','model'))+' '+str(row['attributes_json'] or '')
        tokens={w for w in re.findall(r'[a-z0-9]{3,}',corpus.lower())}
        overlap=len(words & tokens)
        if overlap<1:continue
        conf=min(.92,.62+.08*overlap)
        for key in ('category','subcategory','brand','model'):
            value=str(row[key] or '').strip()
            if value and (key not in best or conf>best[key][1]):best[key]=(value,conf,'Corrección aprendida similar')
    return best


def _local_analysis(product_id: str, product: dict[str,Any]) -> dict[str,Any]:
    images,filenames,image_refs=_load_images(product_id)
    ocr=read_text(images,filenames) if images or filenames else None
    ocr_text=ocr.text if ocr else ''
    base_parts=[]
    for key in ('title','brand','model','description','category','subcategory'):
        value=product.get(key)
        if value and not _is_placeholder(value):base_parts.append(str(value))
    text=' '.join(base_parts+[ocr_text])
    tax=classify({'title':text,'brand':product.get('brand',''),'model':product.get('model',''),'description':product.get('description',''),'ocr_text':ocr_text})
    brand,bconf,be=_detect_brand(text)
    text_colors,cconf,ce=_detect_colors_text(text)
    image_colors=[]; color_evidence=[]
    for image in images[:4]:
        try:
            name,rgb=dominant_color(image)
            if name!='Desconocido' and name.lower() not in image_colors:image_colors.append(name.lower())
            color_evidence.append(f'Color visual aproximado: {name} RGB {rgb}')
        except Exception: pass
    colors=text_colors or image_colors[:3]
    color_conf=cconf if text_colors else (.58 if image_colors else 0)
    sizes=_size_candidates(ocr_text)
    learned=_learned_matches(text)
    visual_candidates=local_visual_candidates(images)
    fields={}
    def add(key,value,confidence,source,evidence=''):
        if value not in ('',[],None):fields[key]={'value':value,'confidence':round(float(confidence),3),'source':source,'evidence':evidence}
    current_title=str(product.get('title') or '').strip()
    if not _is_placeholder(current_title):add('title',current_title,.97,'current','Nombre ya confirmado')
    add('brand',brand or (learned.get('brand') or ('',0,''))[0],bconf or (learned.get('brand') or ('',0,''))[1],'ocr/local', '; '.join(be))
    current_model=str(product.get('model') or '').strip()
    if not _is_placeholder(current_model):add('model',current_model,.94,'current','Modelo ya capturado')
    elif learned.get('model'):add('model',learned['model'][0],learned['model'][1],'learning',learned['model'][2])
    tax_conf=float(tax.get('confidence',0))
    if tax.get('evidence'):
        add('category',tax['category'],tax_conf,'local','Palabras de categoría: '+', '.join(tax['evidence']))
        add('subcategory',tax['subcategory'],tax_conf,'local','Palabras de subcategoría: '+', '.join(tax['evidence']))
    elif learned.get('category'):
        add('category',learned['category'][0],learned['category'][1],'learning',learned['category'][2])
        if learned.get('subcategory'):add('subcategory',learned['subcategory'][0],learned['subcategory'][1],'learning',learned['subcategory'][2])
    add('colors',colors,color_conf,'ocr/image','; '.join(ce+color_evidence[:2]))
    add('sizes',sizes,.98 if sizes else 0,'ocr',f'Talla detectada por OCR: {", ".join(sizes)}' if sizes else '')
    if ocr and ocr.sku_candidates:add('sku',ocr.sku_candidates[0],.96,'ocr','Código con formato SKU detectado en imagen')
    # A model is auto-filled from vision only when a confirmed local reference exceeds a strict threshold.
    if visual_candidates and visual_candidates[0].get('autoEligible'):
        vc=visual_candidates[0]
        add('brand',vc.get('brand',''),vc['confidence'],'visual-library','; '.join(vc.get('evidence',[])))
        add('model',vc.get('model',''),vc['confidence'],'visual-library','; '.join(vc.get('evidence',[])))
        add('title',vc.get('name',''),vc['confidence'],'visual-library','; '.join(vc.get('evidence',[])))
        add('category',vc.get('category',''),vc['confidence'],'visual-library','Producto confirmado previamente en Biblioteca Elegance')
        add('subcategory',vc.get('subcategory',''),vc['confidence'],'visual-library','Producto confirmado previamente en Biblioteca Elegance')
    for k,v in infer_footwear_from_sizes(sizes,str(product.get('category') or '')).items():
        if k not in fields or v['confidence']>fields[k]['confidence']: fields[k]=v
    scores=[v['confidence'] for v in fields.values() if v.get('source')!='current']
    confidence=sum(scores)/len(scores) if scores else .15
    useful_query=[]
    for key in ('brand','model','sku'):
        if fields.get(key):useful_query.append(str(fields[key]['value']))
    useful_query += [x for x in re.findall(r'[A-Za-z0-9-]{3,}',ocr_text) if not re.fullmatch(r'\d{4}',x)][:8]
    query=' '.join(dict.fromkeys(useful_query)).strip()
    evidence=[f'OCR: {ocr.engine if ocr else "sin motor"}',f'{len(images)} fotografía(s) analizada(s)']
    if ocr_text.strip(): evidence.append('Texto detectado: '+re.sub(r'\s+',' ',ocr_text)[:180])
    evidence += [x for x in (tax.get('evidence') or [])]+be+ce+color_evidence[:2]
    return {'source':'local','confidence':round(confidence,3),'fields':fields,'evidence':evidence,'query':query,'ocrText':ocr_text,'ocrEngine':ocr.engine if ocr else 'none','imageCount':len(images),'imageRefs':image_refs,'visualCandidates':visual_candidates}


def _strip_tags(value: str) -> str:
    return re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',value))).strip()


def _fetch(url: str, timeout: int) -> str:
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Elegance/2.1'})
    return urlopen(req,timeout=timeout).read().decode('utf-8','ignore')


def _web_search(query: str, timeout: int) -> list[dict[str,str]]:
    query=re.sub(r'\s+',' ',query).strip()
    if len(query)<3:return []
    results=[]
    engines=[('DuckDuckGo','https://html.duckduckgo.com/html/?q='+quote_plus(query)),('Bing','https://www.bing.com/search?q='+quote_plus(query))]
    errors=[]
    for engine,url in engines:
        try:
            raw=_fetch(url,timeout)
            if engine=='DuckDuckGo':
                links=re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',raw,re.S)
                snippets=re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>',raw,re.S)
            else:
                blocks=re.findall(r'<li class="b_algo".*?</li>',raw,re.S)
                links=[];snippets=[]
                for b in blocks:
                    m=re.search(r'<h2><a href="([^"]+)"[^>]*>(.*?)</a>',b,re.S)
                    if m:links.append((m.group(1),m.group(2)));snippets.append((re.search(r'<p>(.*?)</p>',b,re.S) or [None,''])[1])
            for i,(href,title) in enumerate(links[:8]):
                item={'title':_strip_tags(title),'url':html.unescape(href),'snippet':_strip_tags(snippets[i]) if i<len(snippets) else '','engine':engine}
                if item['title'] and not any(x['url']==item['url'] for x in results):results.append(item)
        except Exception as exc:errors.append(f'{engine}: {exc}')
    if not results and errors:raise RuntimeError(' | '.join(errors))
    return results[:12]


def _consensus(results: list[dict[str,str]], local: dict[str,Any]) -> dict[str,Any]:
    corpus=' '.join((x['title']+' '+x['snippet']) for x in results[:8])
    brand,bconf,be=_detect_brand(corpus)
    colors,cconf,ce=_detect_colors_text(corpus)
    tax=classify({'title':corpus})
    fields={}
    def add(key,value,confidence,evidence=''):
        if value not in ('',[],None):fields[key]={'value':value,'confidence':round(confidence,3),'source':'web','evidence':evidence}
    title_counts={}
    for r in results[:8]:
        clean=re.sub(r'\s*[-|–].*$','',r['title']).strip()
        if 5<=len(clean)<=120:title_counts[clean]=title_counts.get(clean,0)+1
    title=max(title_counts,key=lambda x:(title_counts[x],len(x))) if title_counts else ''
    title_support=title_counts.get(title,0)
    add('title',title,min(.90,.66+.06*title_support),f'{title_support} coincidencia(s) textual(es)')
    add('brand',brand,min(.92,bconf),'; '.join(be))
    if tax.get('evidence'):
        add('category',tax['category'],min(.88,tax['confidence']),'Consenso de resultados web')
        add('subcategory',tax['subcategory'],min(.88,tax['confidence']),'Consenso de resultados web')
    add('colors',colors,min(.82,cconf),'; '.join(ce))
    # Modelo: términos distintivos repetidos después de la marca.
    tokens=[t for t in re.findall(r'[A-Za-z0-9+.-]{2,}',corpus) if t.lower() not in {'amazon','mercado','libre','tenis','zapatos','hombre','mujer','original','mexico','para','the','and','with'}]
    freq={t.lower():tokens.count(t) for t in set(tokens)}
    distinctive=[t for t in tokens if freq.get(t.lower(),0)>=2 and (not brand or t.lower()!=brand.lower())]
    model=' '.join(list(dict.fromkeys(distinctive))[:5]).strip()
    if model:add('model',model,.70,'Términos repetidos en varias coincidencias web')
    scores=[v['confidence'] for v in fields.values()]
    evidence=[f'{r["engine"]}: {r["title"]}' for r in results[:5]]
    return {'source':'web','confidence':round(sum(scores)/len(scores),3) if scores else 0,'fields':fields,'evidence':evidence+be+ce,'results':results}


def _merge(local: dict[str,Any], web: dict[str,Any]|None, threshold: float) -> dict[str,Any]:
    fields={}; alternatives={}
    for source in [local,web or {}]:
        for key,candidate in source.get('fields',{}).items():
            if candidate.get('value') in ('',[],None) or float(candidate.get('confidence',0))<threshold:continue
            if key not in fields:fields[key]=candidate
            elif str(fields[key].get('value')).lower()!=str(candidate.get('value')).lower():
                alternatives.setdefault(key,[]).append(candidate)
                if candidate['confidence']>fields[key]['confidence']:alternatives[key].append(fields[key]);fields[key]=candidate
    evidence=local.get('evidence',[])+(web.get('evidence',[]) if web else [])
    scores=[float(x.get('confidence',0)) for x in fields.values()]
    return {'fields':fields,'alternatives':alternatives,'confidence':round(sum(scores)/len(scores),3) if scores else 0,'evidence':evidence,'webResults':web.get('results',[]) if web else []}


def analyze_product(product_id: str, review_id: str='', force_web: bool=False) -> dict[str,Any]:
    cfg=settings(); product=_product(product_id)
    if not product:raise KeyError('Producto no encontrado.')
    local=_local_analysis(product_id,product)
    # El botón de investigación web fuerza la consulta aunque el interruptor general esté apagado.
    use_web=not bool(cfg['local_only']) and (force_web or (bool(cfg['web_enabled']) and local['confidence']<float(cfg['complete_confidence'])))
    web=None; web_error=''
    if use_web:
        if not local.get('query'):
            web_error='No se obtuvo texto, marca, modelo o SKU suficiente para construir una búsqueda web confiable.'
            web={'source':'web','confidence':0,'fields':{},'evidence':[web_error],'results':[]}
        else:
            try:web=_consensus(_web_search(local['query'],int(cfg['web_timeout_seconds'])),local)
            except Exception as exc:
                web_error=str(exc);web={'source':'web','confidence':0,'fields':{},'evidence':[f'Investigación web no disponible: {exc}'],'results':[]}
    candidate_rows=list(local.get('visualCandidates') or [])
    if web:
        for r in web.get('results',[])[:8]:
            candidate_rows.append({'name':r.get('title',''),'brand':'','model':'','sku':'','category':'','subcategory':'','colors':'','description':r.get('snippet',''),'image':'','source':r.get('engine','Web'),'sourceUrl':r.get('url',''),'confidence':max(.35,float(web.get('confidence',0))-.08),'evidence':['Resultado textual externo; requiere selección y confirmación']})
    save_candidates(product_id,review_id,candidate_rows)
    merged=_merge(local,web,float(cfg['complete_confidence']))
    current={k:product.get(k,'') for k in ('title','brand','model','category','subcategory','description')}
    attrs={k:(v.get('value','') if isinstance(v,dict) else v) for k,v in product_attributes(product_id).items()}
    current.update({'colors':attrs.get('color',''),'sizes':attrs.get('size',''),'materials':attrs.get('material',''),'gender':attrs.get('gender',''),'type':attrs.get('type',''),'sku':attrs.get('sku','')})
    conflicts={}
    for key,candidate in merged['fields'].items():
        actual=current.get(key,'')
        if actual not in ('',None,[]) and not _is_placeholder(actual) and str(actual).lower()!=str(candidate['value']).lower():
            conflicts[key]={'current':actual,'suggested':candidate['value'],'confidence':candidate['confidence'],'source':candidate['source'],'evidence':candidate.get('evidence','')}
    action='suggested'
    # Solo autoaplica a la base cuando no existe información manual y la confianza es suficiente.
    auto_fields={k:v for k,v in merged['fields'].items() if k not in conflicts and (_is_placeholder(current.get(k,'')) or current.get(k,'') in ('',None,[]))}
    if auto_fields:
        snapshot_product(product_id,'Antes del autocompletado','intelligence')
        attr_map={'colors':'color','materials':'material','gender':'gender','type':'type','sizes':'size','sku':'sku'}; attr_values={}
        for key,candidate in auto_fields.items():
            value=candidate['value']
            if key in attr_map:attr_values[attr_map[key]]=', '.join(value) if isinstance(value,list) else str(value)
            elif key in ('title','brand','model','category','subcategory','description'):product[key]=value
        if attr_values:save_product_attributes(product_id,attr_values,'intelligence')
        state=load_state(); products=state.get('products',[]); idx=next(i for i,p in enumerate(products) if str(p.get('id'))==str(product_id)); product['updatedAt']=_now();products[idx]=product;save_state(state)
        action='completed'
    if bool(cfg['auto_publish']) and merged['confidence']>=float(cfg['publish_confidence']) and not conflicts:
        bundle=_product_bundle(product_id); required=[product.get('title'),product.get('brand'),product.get('model'),product.get('category'),product.get('subcategory')]
        ready=all(str(x or '').strip() and not _is_placeholder(x) for x in required) and float(product.get('price') or 0)>0 and bool(bundle.get('images')) and bool(bundle.get('variants'))
        if ready:
            from services.public_catalog import update_publication, sync_products
            sync_products();update_publication(product_id,{'status':'published','publicTitle':product.get('title',''),'publicDescription':product.get('description',''),'hideWhenSoldOut':True});action='published'
            if review_id:
                with _db() as c:c.execute("UPDATE recognition_reviews SET status='approved',updated_at=? WHERE id=?",(_now(),review_id))
        else:action='review_required'
    decision={'productId':product_id,'reviewId':review_id,'local':local,'web':web,'merged':merged,'conflicts':conflicts,'autoApplied':list(auto_fields),'usedWeb':use_web,'webError':web_error,'action':action,'settings':cfg,'candidates':candidate_rows}
    if cfg['save_decisions']:
        with _db() as c:c.execute('INSERT INTO intelligence_decisions VALUES(?,?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,product_id,review_id,'local+web' if use_web else 'local',merged['confidence'],json.dumps({'query':local.get('query',''),'images':local.get('imageRefs',[])},ensure_ascii=False),json.dumps(decision,ensure_ascii=False),json.dumps(merged['evidence'],ensure_ascii=False),action,_now()))
    return {'status':'ok',**decision}


def decisions(product_id: str, limit: int=50) -> list[dict[str,Any]]:
    migrate_intelligence()
    with _db() as c:rows=c.execute('SELECT * FROM intelligence_decisions WHERE product_id=? ORDER BY created_at DESC LIMIT ?',(product_id,max(1,min(200,limit)))).fetchall()
    out=[]
    for r in rows:
        x=dict(r);x['result']=json.loads(x.pop('result_json') or '{}');x['evidence']=json.loads(x.pop('evidence_json') or '[]');x.pop('input_json',None);out.append(x)
    return out
