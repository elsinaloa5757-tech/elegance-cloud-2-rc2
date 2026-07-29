from __future__ import annotations

import copy, hashlib, json, re, sqlite3, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.smart_catalog import classify_brand, classify_colors, classify_gender, classify_season, plain
from services.state_store import load_state, save_state

from services.runtime_config import database_file
_DB = database_file()

MODEL_HINTS = {
    "Jordan": ["Air Jordan 1", "Air Jordan 3", "Air Jordan 4", "Air Jordan 11", "Jordan Retro"],
    "Nike": ["Air Force 1", "Dunk Low", "Air Max 90", "Air Max 270", "Blazer"],
    "Adidas": ["Samba", "Gazelle", "Superstar", "Campus", "Ultraboost"],
    "New Balance": ["530", "550", "574", "9060", "990"],
    "Timberland": ["6-Inch Premium", "Euro Sprint", "Chukka"],
    "Puma": ["Suede", "Palermo", "RS-X"],
    "Vans": ["Old Skool", "Sk8-Hi", "Authentic"],
    "Converse": ["Chuck Taylor", "Run Star Hike"],
}

def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(_DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS ai_suggestions(
      id TEXT PRIMARY KEY, product_id TEXT, payload TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
      confirmed_at TEXT, correction_payload TEXT
    );
    CREATE TABLE IF NOT EXISTS ai_learning(
      id INTEGER PRIMARY KEY AUTOINCREMENT, field_name TEXT NOT NULL,
      source_value TEXT, corrected_value TEXT NOT NULL, context TEXT,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_ai_suggestions_product ON ai_suggestions(product_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_ai_learning_field ON ai_learning(field_name, source_value);
    """)
    return c

def migrate_ai_schema() -> dict[str, Any]:
    with _connect() as c:
        count = c.execute("SELECT COUNT(*) FROM ai_suggestions").fetchone()[0]
    state = copy.deepcopy(load_state())
    state.setdefault("eleganceAI", {"version": "3.3", "mode": "local-first", "confirmationRequired": True})
    save_state(state)
    return {"status": "ok", "preservedProducts": len(state.get("products", [])), "suggestions": count}

def _product(product_id: str) -> dict[str, Any]:
    for p in load_state().get("products", []):
        if str(p.get("id")) == str(product_id): return copy.deepcopy(p)
    raise ValueError("Producto no encontrado")

def _learned(field: str, source: str) -> tuple[str | None, float]:
    with _connect() as c:
        row = c.execute("SELECT corrected_value, COUNT(*) n FROM ai_learning WHERE field_name=? AND source_value=? GROUP BY corrected_value ORDER BY n DESC LIMIT 1", (field, plain(source))).fetchone()
    return (row[0], min(.98, .72 + row[1] * .06)) if row else (None, 0.0)

def _model(product: dict[str, Any], brand: str) -> tuple[str, float, str]:
    existing = str(product.get("model") or "").strip()
    if existing: return existing, 1.0, "preserved"
    text = " ".join(str(product.get(k) or "") for k in ("title","notes","sku","description"))
    learned, conf = _learned("model", text)
    if learned: return learned, conf, "learned"
    norm = plain(text)
    for candidate in MODEL_HINTS.get(brand, []):
        if plain(candidate) in norm: return candidate, .92, "local-pattern"
    return "Modelo por confirmar", .35, "safe-fallback"

def _category(product: dict[str, Any], model: str) -> tuple[str,str,float]:
    cat = str(product.get("category") or "").strip(); sub = str(product.get("subcategory") or "").strip()
    if cat and sub: return cat, sub, 1.0
    t = plain(" ".join([str(product.get("title") or ""), model, str(product.get("notes") or "")]))
    if any(x in t for x in ("bota","boot","timberland")): return cat or "Calzado", sub or "Botas", .88
    if any(x in t for x in ("sandalia","slide")): return cat or "Calzado", sub or "Sandalias", .86
    if any(x in t for x in ("playera","camisa","hoodie","chamarra","pantalon","vestido")): return cat or "Ropa", sub or "Prenda", .80
    return cat or "Calzado", sub or "Tenis", .78

def _contradictions(p: dict[str, Any], proposed: dict[str, Any]) -> list[dict[str,str]]:
    out=[]
    for field in ("brand","model","category","subcategory","gender","color","season"):
        old=str(p.get(field) or "").strip(); new=str(proposed.get(field) or "").strip()
        if old and new and plain(old)!=plain(new): out.append({"field":field,"current":old,"suggested":new})
    if p.get("stock") is not None and int(p.get("stock") or 0)<0: out.append({"field":"stock","current":str(p.get('stock')),"suggested":"0 o mayor"})
    return out

def suggest(product_id: str) -> dict[str, Any]:
    p=_product(product_id)
    brand,bconf,bsource=classify_brand(p); model,mconf,msource=_model(p,brand)
    category,subcategory,cconf=_category(p,model); gender,gconf=classify_gender(p)
    color,secondary,colconf=classify_colors(p); season,sconf=classify_season(p)
    complete_name=" ".join(x for x in (brand, model, color if color!="Sin identificar" else "") if x and "confirmar" not in x).strip()
    description=(f"Descubre {complete_name or 'este producto seleccionado'}, una opción de {subcategory.lower()} con presencia elegante y versátil. "
                 f"Ideal para {season.lower()}, con color principal {color.lower()} y disponibilidad sujeta al inventario actual.")
    keywords=sorted({plain(x).replace(" ","-") for x in (brand,model,category,subcategory,gender,color,season) if x and "confirmar" not in x and "identificar" not in x})
    confidences={"brand":bconf,"model":mconf,"category":cconf,"gender":gconf,"color":colconf,"season":sconf}
    proposed={"brand":brand,"model":model,"title":complete_name or str(p.get("title") or "Producto por confirmar"),"category":category,"subcategory":subcategory,"gender":gender,"color":color,"primaryColor":color,"secondaryColors":secondary,"season":season,"description":description,"keywords":keywords,"tags":keywords}
    conflicts=_contradictions(p,proposed)
    overall=round(sum(confidences.values())/len(confidences),3)
    sid=hashlib.sha256(f"{product_id}|{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()[:20]
    payload={"suggestionId":sid,"productId":str(product_id),"proposed":proposed,"confidence":confidences,"overallConfidence":overall,"sources":{"brand":bsource,"model":msource},"contradictions":conflicts,"requiresConfirmation":True}
    with _connect() as c:
        c.execute("INSERT INTO ai_suggestions(id,product_id,payload,status,created_at) VALUES(?,?,?,?,?)",(sid,str(product_id),json.dumps(payload,ensure_ascii=False),"pending",datetime.now(timezone.utc).isoformat()))
        c.commit()
    return {"status":"ok",**payload}

def confirm(suggestion_id: str, corrections: dict[str,Any] | None, confirm: bool) -> dict[str,Any]:
    if not confirm: return {"status":"preview","saved":False,"message":"No se modificó ningún dato. Envíe confirm=true para guardar."}
    with _connect() as c:
        row=c.execute("SELECT * FROM ai_suggestions WHERE id=?",(suggestion_id,)).fetchone()
        if not row: raise ValueError("Sugerencia no encontrada")
        if row["status"]=="confirmed": raise ValueError("La sugerencia ya fue confirmada")
        payload=json.loads(row["payload"])
    state=copy.deepcopy(load_state()); products=state.get("products",[]); target=None
    for p in products:
        if str(p.get("id"))==str(payload["productId"]): target=p; break
    if target is None: raise ValueError("Producto no encontrado")
    final=copy.deepcopy(payload["proposed"]); corrections=corrections or {}; final.update(corrections)
    protected={k:copy.deepcopy(target.get(k)) for k in ("id","images","stock","price","sizes","notes","createdAt") if k in target}
    before=copy.deepcopy(target)
    target.update(final); target.update(protected); target["aiConfirmedAt"]=datetime.now(timezone.utc).isoformat(); target["aiSuggestionId"]=suggestion_id
    save_state(state)
    with _connect() as c:
        for field,value in corrections.items():
            source=str(payload["proposed"].get(field) or "")
            c.execute("INSERT INTO ai_learning(field_name,source_value,corrected_value,context,created_at) VALUES(?,?,?,?,?)",(field,plain(source),str(value),json.dumps({"productId":payload['productId']},ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
        c.execute("UPDATE ai_suggestions SET status='confirmed',confirmed_at=?,correction_payload=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),json.dumps(corrections,ensure_ascii=False),suggestion_id)); c.commit()
    return {"status":"ok","saved":True,"productId":payload["productId"],"protectedFields":list(protected),"changedFields":[k for k in final if before.get(k)!=target.get(k)]}

def history(product_id: str|None=None, limit:int=100)->list[dict[str,Any]]:
    q="SELECT * FROM ai_suggestions"; args=[]
    if product_id: q+=" WHERE product_id=?"; args.append(str(product_id))
    q+=" ORDER BY created_at DESC LIMIT ?"; args.append(max(1,min(limit,500)))
    with _connect() as c: rows=c.execute(q,args).fetchall()
    return [{"id":r["id"],"productId":r["product_id"],"status":r["status"],"createdAt":r["created_at"],"confirmedAt":r["confirmed_at"],"payload":json.loads(r["payload"]),"corrections":json.loads(r["correction_payload"] or "{}")} for r in rows]

# Cloud 1.5 Enterprise additions: deterministic, local-first image intelligence.
from statistics import median
try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
except Exception:  # pragma: no cover
    Image = None

_AI_DIR = Path(__file__).resolve().parents[1] / "data" / "ai_generated"
_AI_DIR.mkdir(parents=True, exist_ok=True)

def _image_path(product: dict[str, Any]) -> Path | None:
    candidates=[]
    for key in ("imagePath","image","coverImage","originalImage"):
        if product.get(key): candidates.append(product.get(key))
    for item in product.get("images",[]) or []:
        candidates.append(item.get("path") if isinstance(item,dict) else item)
    root=Path(__file__).resolve().parents[2]
    for raw in candidates:
        if not raw: continue
        p=Path(str(raw))
        for candidate in (p, root/p, Path(__file__).resolve().parents[1]/p):
            if candidate.exists() and candidate.is_file(): return candidate.resolve()
    return None

def _sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def _dhash(path: Path) -> str:
    if Image is None: return ""
    with Image.open(path) as im:
        im=ImageOps.exif_transpose(im).convert('L').resize((9,8))
        px=list(im.getdata()); bits=[]
        for y in range(8):
            row=px[y*9:(y+1)*9]
            bits.extend(row[x] > row[x+1] for x in range(8))
        return f"{sum((1 << i) for i,b in enumerate(bits) if b):016x}"

def _hamming(a:str,b:str)->int:
    if not a or not b: return 64
    return (int(a,16)^int(b,16)).bit_count()

def image_fingerprint(product_id:str)->dict[str,Any]:
    p=_product(product_id); path=_image_path(p)
    if not path: return {"status":"missing-image","productId":product_id}
    if Image is None: return {"status":"dependency-missing","detail":"Pillow no está instalado"}
    with Image.open(path) as im:
        w,h=im.size; mode=im.mode
    return {"status":"ok","productId":product_id,"path":str(path),"sha256":_sha256_file(path),"dhash":_dhash(path),"width":w,"height":h,"mode":mode}

def duplicate_scan(max_distance:int=6)->dict[str,Any]:
    rows=[]
    for p in load_state().get('products',[]):
        pid=str(p.get('id',''))
        if not pid: continue
        fp=image_fingerprint(pid)
        if fp.get('status')=='ok': rows.append(fp)
    exact=[]; visual=[]
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            if a['sha256']==b['sha256']:
                exact.append({"a":a['productId'],"b":b['productId'],"sha256":a['sha256']})
            else:
                d=_hamming(a['dhash'],b['dhash'])
                if d<=max(0,min(max_distance,16)):
                    visual.append({"a":a['productId'],"b":b['productId'],"distance":d,"similarity":round(1-d/64,4)})
    return {"status":"ok","scanned":len(rows),"exactDuplicates":exact,"visualCandidates":visual,"threshold":max_distance}

def suggest_price(product_id:str)->dict[str,Any]:
    p=_product(product_id); brand=plain(str(p.get('brand') or '')); category=plain(str(p.get('category') or ''))
    prices=[]
    for other in load_state().get('products',[]):
        try: price=float(other.get('price') or 0)
        except Exception: continue
        if price<=0: continue
        score=0
        if brand and plain(str(other.get('brand') or ''))==brand: score+=2
        if category and plain(str(other.get('category') or ''))==category: score+=1
        if score: prices.extend([price]*score)
    if not prices:
        prices=[float(x.get('price') or 0) for x in load_state().get('products',[]) if float(x.get('price') or 0)>0]
    if not prices: return {"status":"insufficient-data","productId":product_id,"suggestedPrice":None}
    base=median(prices); rounded=round(base/50)*50
    return {"status":"ok","productId":product_id,"suggestedPrice":rounded,"range":{"min":round(base*.85,2),"max":round(base*1.15,2)},"comparables":len(prices),"method":"mediana ponderada del catálogo local"}

def process_image(product_id:str, remove_background:bool=False, scenario_path:str|None=None)->dict[str,Any]:
    p=_product(product_id); src=_image_path(p)
    if not src: raise ValueError('El producto no tiene una imagen local accesible')
    if Image is None: raise RuntimeError('Pillow no está instalado')
    outdir=_AI_DIR/str(product_id); outdir.mkdir(parents=True,exist_ok=True)
    with Image.open(src) as original:
        im=ImageOps.exif_transpose(original).convert('RGBA')
        rgb=im.convert('RGB')
        rgb=ImageOps.autocontrast(rgb,cutoff=1)
        rgb=ImageEnhance.Contrast(rgb).enhance(1.06)
        rgb=ImageEnhance.Sharpness(rgb).enhance(1.12)
        rgba=rgb.convert('RGBA')
        bg_removed=False
        if remove_background:
            corner=rgba.getpixel((0,0))[:3]; data=[]
            for px in rgba.getdata():
                dist=sum(abs(px[i]-corner[i]) for i in range(3))
                data.append((px[0],px[1],px[2],0 if dist<42 else px[3]))
            rgba.putdata(data); bg_removed=True
        enhanced=outdir/'enhanced.webp'; rgba.convert('RGB').save(enhanced,'WEBP',quality=90,method=6)
        transparent=outdir/'transparent.png'
        if bg_removed: rgba.save(transparent,'PNG',optimize=True)
        composed=None
        if scenario_path:
            sp=Path(scenario_path)
            if sp.exists():
                with Image.open(sp) as scene:
                    canvas=ImageOps.fit(ImageOps.exif_transpose(scene).convert('RGBA'),(1600,1600))
                    product=rgba.copy(); product.thumbnail((1250,1250))
                    x=(canvas.width-product.width)//2; y=(canvas.height-product.height)//2
                    canvas.alpha_composite(product,(x,y)); composed=outdir/'scenario.webp'; canvas.convert('RGB').save(composed,'WEBP',quality=91,method=6)
    return {"status":"ok","productId":product_id,"source":str(src),"enhanced":str(enhanced),"transparent":str(transparent) if bg_removed else None,"scenario":str(composed) if composed else None,"backgroundMethod":"corner-color heuristic" if bg_removed else "not-requested"}

def enterprise_analyze(product_id:str)->dict[str,Any]:
    suggestion=suggest(product_id)
    fp=image_fingerprint(product_id)
    price=suggest_price(product_id)
    return {"status":"ok","version":"Cloud 1.5","productId":product_id,"catalogSuggestion":suggestion,"imageFingerprint":fp,"priceSuggestion":price,"limitations":["La identificación local usa reglas y aprendizaje confirmado; no inventa una marca cuando la evidencia es insuficiente.","La eliminación local de fondo es determinista y debe revisarse antes de publicar."]}

def batch_analyze(limit:int=100)->dict[str,Any]:
    results=[]; errors=[]
    for p in load_state().get('products',[])[:max(1,min(limit,500))]:
        pid=str(p.get('id',''))
        try: results.append(enterprise_analyze(pid))
        except Exception as e: errors.append({"productId":pid,"error":str(e)})
    return {"status":"ok","analyzed":len(results),"errors":errors,"results":results}
