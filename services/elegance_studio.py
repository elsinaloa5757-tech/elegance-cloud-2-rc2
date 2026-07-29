from __future__ import annotations

import hashlib, io, json, shutil, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[1]
from services.runtime_config import data_dir
DATA = data_dir()
STORE = DATA / 'studio'
ORIGINALS = STORE / 'originals'
PREVIEWS = STORE / 'previews'
APPROVED = STORE / 'approved'
DB = DATA / 'elegance.sqlite3'

FORMATS = {
    'catalog': (1400, 1400), 'thumbnail': (420, 420), 'whatsapp': (1080, 1080),
    'facebook': (1200, 1500), 'instagram_square': (1080, 1080),
    'instagram_story': (1080, 1920), 'marketplace': (1200, 1200),
    'horizontal': (1600, 900), 'vertical': (1200, 1500),
}

def _now() -> str: return datetime.now(timezone.utc).isoformat()

def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB, timeout=30); c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA foreign_keys=ON')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS studio_assets(
      id TEXT PRIMARY KEY, product_id TEXT, original_path TEXT NOT NULL,
      original_sha256 TEXT NOT NULL, original_name TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS studio_versions(
      id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, product_id TEXT, status TEXT NOT NULL,
      preset TEXT NOT NULL, options_json TEXT NOT NULL, outputs_json TEXT NOT NULL,
      created_at TEXT NOT NULL, decided_at TEXT, restored_from TEXT,
      FOREIGN KEY(asset_id) REFERENCES studio_assets(id)
    );
    CREATE INDEX IF NOT EXISTS idx_studio_assets_hash ON studio_assets(original_sha256);
    CREATE INDEX IF NOT EXISTS idx_studio_versions_product ON studio_versions(product_id,created_at DESC);
    '''); return c

def migrate_studio() -> dict[str, Any]:
    for p in (ORIGINALS, PREVIEWS, APPROVED): p.mkdir(parents=True, exist_ok=True)
    with _connect() as c:
        a=c.execute('SELECT COUNT(*) FROM studio_assets').fetchone()[0]
        v=c.execute('SELECT COUNT(*) FROM studio_versions').fetchone()[0]
    return {'status':'ok','assets':a,'versions':v,'originalsPreserved':True}

def _remove_background(img: Image.Image) -> Image.Image:
    # rembg is optional. A deterministic local fallback removes only near-uniform edge colors.
    try:
        from rembg import remove
        out = remove(img.convert('RGBA'))
        return out if isinstance(out, Image.Image) else Image.open(io.BytesIO(out)).convert('RGBA')
    except Exception:
        rgba=img.convert('RGBA'); px=rgba.load(); w,h=rgba.size
        edge=[px[x,0][:3] for x in range(0,w,max(1,w//20))]+[px[x,h-1][:3] for x in range(0,w,max(1,w//20))]
        bg=tuple(sum(c[i] for c in edge)//len(edge) for i in range(3))
        for y in range(h):
            for x in range(w):
                r,g,b,a=px[x,y]; d=abs(r-bg[0])+abs(g-bg[1])+abs(b-bg[2])
                if d < 42: px[x,y]=(r,g,b,0)
                elif d < 95: px[x,y]=(r,g,b,int(a*(d-42)/53))
        return rgba

def _trim(img: Image.Image) -> Image.Image:
    rgba=img.convert('RGBA'); box=rgba.getchannel('A').getbbox()
    return rgba.crop(box) if box else rgba

def _premium_bg(size: tuple[int,int], theme: str) -> Image.Image:
    w,h=size; base=Image.new('RGB',size,(3,10,15)); p=base.load()
    # elegant ice-blue radial gradient, generated locally and brand-neutral
    for y in range(h):
        for x in range(w):
            dx=(x-w*.52)/max(w,1); dy=(y-h*.42)/max(h,1); glow=max(0,1-(dx*dx+dy*dy)*5)
            p[x,y]=(int(3+8*glow),int(10+35*glow),int(15+54*glow))
    return base.filter(ImageFilter.GaussianBlur(radius=max(1,w//180)))

def _canvas(product: Image.Image, size: tuple[int,int], background: str, theme: str) -> Image.Image:
    w,h=size; pad=.12
    product.thumbnail((int(w*(1-2*pad)),int(h*(1-2*pad))),Image.Resampling.LANCZOS)
    if background=='transparent': canvas=Image.new('RGBA',size,(0,0,0,0))
    elif background=='original':
        canvas=ImageOps.fit(product.convert('RGB'),size,Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(22)).convert('RGBA')
    else: canvas=_premium_bg(size,theme).convert('RGBA')
    x=(w-product.width)//2; y=(h-product.height)//2
    # restrained contact shadow
    if background!='transparent':
        shadow=Image.new('RGBA',size,(0,0,0,0)); mask=Image.new('L',(max(1,int(product.width*.72)),max(1,int(product.height*.09))),90).filter(ImageFilter.GaussianBlur(18))
        shadow.paste((0,0,0,100),(x+product.width//7,min(h-1,y+product.height-int(product.height*.04))),mask)
        canvas=Image.alpha_composite(canvas,shadow)
    canvas.alpha_composite(product,(x,y)); return canvas

def _save_outputs(img: Image.Image, version_id: str, options: dict[str,Any], target: Path) -> dict[str,str]:
    target.mkdir(parents=True,exist_ok=True); outputs={}
    requested=options.get('formats') or ['catalog','thumbnail','whatsapp','facebook','instagram_square','instagram_story','marketplace']
    ext=str(options.get('outputFormat','webp')).lower(); ext=ext if ext in {'webp','jpg','jpeg','png'} else 'webp'
    for name in requested:
        if name not in FORMATS: continue
        out=_canvas(img.copy(),FORMATS[name],str(options.get('background','premium')),str(options.get('theme','elegance-ice')))
        path=target/f'{version_id}_{name}.{ext.replace("jpeg","jpg")}'
        save=out if ext=='png' else out.convert('RGB')
        kwargs={'optimize':True};
        if ext in {'webp','jpg','jpeg'}: kwargs['quality']=int(options.get('quality',88))
        save.save(path,format=('JPEG' if ext in {'jpg','jpeg'} else ext.upper()),**kwargs)
        outputs[name]=str(path.relative_to(ROOT)).replace('\\','/')
    return outputs

def create_preview(data: bytes, filename: str, product_id: str|None=None, options: dict[str,Any]|None=None) -> dict[str,Any]:
    migrate_studio(); options=options or {}; digest=hashlib.sha256(data).hexdigest()
    with _connect() as c:
        duplicate=c.execute('SELECT * FROM studio_assets WHERE original_sha256=? LIMIT 1',(digest,)).fetchone()
    if duplicate and not options.get('processDuplicate',False):
        return {'status':'duplicate','duplicate':True,'assetId':duplicate['id'],'originalPreserved':True}
    asset_id=uuid.uuid4().hex; ext=Path(filename or 'image.jpg').suffix.lower() or '.jpg'
    original=ORIGINALS/f'{asset_id}{ext}'; original.write_bytes(data)
    try: img=Image.open(io.BytesIO(data)); img=ImageOps.exif_transpose(img).convert('RGBA')
    except Exception as exc: original.unlink(missing_ok=True); raise ValueError(f'Imagen no válida: {exc}')
    if options.get('removeBackground',True): img=_remove_background(img)
    img=_trim(img)
    img=ImageEnhance.Brightness(img).enhance(float(options.get('brightness',1.04)))
    img=ImageEnhance.Contrast(img).enhance(float(options.get('contrast',1.06)))
    img=ImageEnhance.Color(img).enhance(float(options.get('color',1.02)))
    img=ImageEnhance.Sharpness(img).enhance(float(options.get('sharpness',1.12)))
    version_id=uuid.uuid4().hex
    outputs=_save_outputs(img,version_id,options,PREVIEWS/version_id)
    with _connect() as c:
        c.execute('INSERT INTO studio_assets VALUES(?,?,?,?,?,?)',(asset_id,product_id,str(original.relative_to(ROOT)),digest,filename,_now()))
        c.execute('INSERT INTO studio_versions VALUES(?,?,?,?,?,?,?,?,?,?)',(version_id,asset_id,product_id,'pending',str(options.get('preset','automatic')),json.dumps(options,ensure_ascii=False),json.dumps(outputs,ensure_ascii=False),_now(),None,None)); c.commit()
    return {'status':'preview','duplicate':False,'assetId':asset_id,'versionId':version_id,'outputs':outputs,'original':str(original.relative_to(ROOT)),'originalPreserved':True,'requiresApproval':True}

def decide(version_id: str, action: str) -> dict[str,Any]:
    if action not in {'approve','reject'}: raise ValueError('Acción inválida')
    with _connect() as c:
        r=c.execute('SELECT * FROM studio_versions WHERE id=?',(version_id,)).fetchone()
        if not r: raise ValueError('Versión no encontrada')
        outputs=json.loads(r['outputs_json']); status='approved' if action=='approve' else 'rejected'
        if action=='approve':
            dst=APPROVED/version_id; dst.mkdir(parents=True,exist_ok=True)
            new={}
            for k,rel in outputs.items():
                src=ROOT/rel
                if src.exists(): shutil.copy2(src,dst/src.name); new[k]=str((dst/src.name).relative_to(ROOT)).replace('\\','/')
            outputs=new
        c.execute('UPDATE studio_versions SET status=?,outputs_json=?,decided_at=? WHERE id=?',(status,json.dumps(outputs,ensure_ascii=False),_now(),version_id)); c.commit()
    return {'status':status,'versionId':version_id,'outputs':outputs,'originalPreserved':True}

def restore(version_id: str) -> dict[str,Any]:
    with _connect() as c:
        r=c.execute('SELECT * FROM studio_versions WHERE id=?',(version_id,)).fetchone()
        if not r: raise ValueError('Versión no encontrada')
        if r['status']!='approved': raise ValueError('Solo se pueden restaurar versiones aprobadas')
        new_id=uuid.uuid4().hex
        c.execute('INSERT INTO studio_versions VALUES(?,?,?,?,?,?,?,?,?,?)',(new_id,r['asset_id'],r['product_id'],'approved','restored',r['options_json'],r['outputs_json'],_now(),_now(),version_id)); c.commit()
    return {'status':'restored','versionId':new_id,'restoredFrom':version_id,'outputs':json.loads(r['outputs_json'])}

def history(product_id: str|None=None, limit:int=100)->list[dict[str,Any]]:
    q='SELECT v.*,a.original_path,a.original_name,a.original_sha256 FROM studio_versions v JOIN studio_assets a ON a.id=v.asset_id'; args=[]
    if product_id: q+=' WHERE v.product_id=?'; args.append(product_id)
    q+=' ORDER BY v.created_at DESC LIMIT ?'; args.append(max(1,min(limit,500)))
    with _connect() as c: rows=c.execute(q,args).fetchall()
    return [{**dict(r),'options':json.loads(r['options_json']),'outputs':json.loads(r['outputs_json'])} for r in rows]
