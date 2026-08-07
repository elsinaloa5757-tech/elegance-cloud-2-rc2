from __future__ import annotations
import base64, json, math, sqlite3, uuid
from datetime import datetime, timezone
from typing import Any
import cv2
import numpy as np
from services.state_store import database_path
from services.shoe_intelligence import remember_visual

def _now(): return datetime.now(timezone.utc).isoformat()
def _connect():
    c=sqlite3.connect(database_path(),timeout=60); c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); return c

def migrate_phase4():
    with _connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS shoe_visual_features_v4(
          id TEXT PRIMARY KEY, brand TEXT NOT NULL, model TEXT NOT NULL,
          source_product_id TEXT NOT NULL DEFAULT '', image_ref TEXT NOT NULL DEFAULT '',
          feature_json TEXT NOT NULL, orb_b64 TEXT NOT NULL DEFAULT '',
          orb_rows INTEGER NOT NULL DEFAULT 0, confirmed INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_visual_v4_brand_model ON shoe_visual_features_v4(brand,model);
        """); c.commit()
    return phase4_stats()

def phase4_stats():
    with _connect() as c:
        total=c.execute("SELECT COUNT(*) FROM shoe_visual_features_v4 WHERE confirmed=1").fetchone()[0]
        models=c.execute("SELECT COUNT(DISTINCT lower(brand)||'|'||lower(model)) FROM shoe_visual_features_v4 WHERE confirmed=1").fetchone()[0]
    return {"status":"ok","references":total,"models":models}

def _decode(data:bytes):
    img=cv2.imdecode(np.frombuffer(data,dtype=np.uint8),cv2.IMREAD_COLOR)
    if img is None: raise ValueError("No se pudo leer la imagen.")
    h,w=img.shape[:2]
    if max(h,w)>900:
        s=900/max(h,w); img=cv2.resize(img,(int(w*s),int(h*s)),interpolation=cv2.INTER_AREA)
    return img

def _foreground(img):
    h,w=img.shape[:2]; mx=max(2,int(w*.035)); my=max(2,int(h*.035))
    mask=np.zeros((h,w),np.uint8); bg=np.zeros((1,65),np.float64); fg=np.zeros((1,65),np.float64)
    try:
        cv2.grabCut(img,mask,(mx,my,w-2*mx,h-2*my),bg,fg,3,cv2.GC_INIT_WITH_RECT)
        binary=np.where((mask==cv2.GC_FGD)|(mask==cv2.GC_PR_FGD),255,0).astype("uint8")
    except Exception:
        binary=np.zeros((h,w),np.uint8); binary[int(h*.12):int(h*.88),int(w*.08):int(w*.92)]=255
    k=np.ones((5,5),np.uint8)
    binary=cv2.morphologyEx(binary,cv2.MORPH_CLOSE,k,iterations=2)
    binary=cv2.morphologyEx(binary,cv2.MORPH_OPEN,k,iterations=1)
    contours,_=cv2.findContours(binary,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        ct=max(contours,key=cv2.contourArea); x,y,bw,bh=cv2.boundingRect(ct)
        if bw*bh>=h*w*.08:
            comp=np.zeros_like(binary); cv2.drawContours(comp,[ct],-1,255,-1)
            px=int(bw*.05); py=int(bh*.06)
            x0=max(0,x-px); y0=max(0,y-py); x1=min(w,x+bw+px); y1=min(h,y+bh+py)
            return img[y0:y1,x0:x1],comp[y0:y1,x0:x1],[x0,y0,x1,y1]
    x0,y0,x1,y1=int(w*.08),int(h*.12),int(w*.92),int(h*.88)
    return img[y0:y1,x0:x1],binary[y0:y1,x0:x1],[x0,y0,x1,y1]

def _norm(v):
    v=np.asarray(v,dtype=np.float32).reshape(-1); n=float(np.linalg.norm(v))
    if n>1e-9: v=v/n
    return [round(float(x),6) for x in v]

def _hist(img,mask=None):
    hsv=cv2.cvtColor(img,cv2.COLOR_BGR2HSV)
    return _norm(np.concatenate([
        cv2.calcHist([hsv],[0],mask,[18],[0,180]).reshape(-1),
        cv2.calcHist([hsv],[1],mask,[8],[0,256]).reshape(-1),
        cv2.calcHist([hsv],[2],mask,[8],[0,256]).reshape(-1)]))

def _edge(gray,mask):
    e=cv2.Canny(gray,60,150); e=cv2.bitwise_and(e,e,mask=mask)
    e=cv2.resize(e,(32,32),interpolation=cv2.INTER_AREA).astype(np.float32)/255
    return _norm(np.concatenate([e.mean(axis=1),e.mean(axis=0)]))

def _hu(mask):
    vals=cv2.HuMoments(cv2.moments(mask,True)).flatten(); out=[]
    for x in vals:
        x=float(x); out.append(0.0 if abs(x)<1e-30 else round(-math.copysign(1,x)*math.log10(abs(x)),6))
    return out

def _regions(crop,mask):
    h,w=crop.shape[:2]
    boxes={"heel":(0,0,max(1,int(w*.34)),h),"mid":(int(w*.27),0,max(int(w*.28)+1,int(w*.73)),h),
           "toe":(int(w*.66),0,w,h),"upper":(0,0,w,max(1,int(h*.62))),"sole":(0,int(h*.58),w,h)}
    out={}
    for name,(x0,y0,x1,y1) in boxes.items():
        r=crop[y0:y1,x0:x1]; m=mask[y0:y1,x0:x1]
        out[name]=_hist(r,m) if r.size else []
    return out

def _orb(gray,mask):
    orb=cv2.ORB_create(nfeatures=220,scaleFactor=1.2,nlevels=6,edgeThreshold=15)
    _,d=orb.detectAndCompute(gray,mask)
    return np.empty((0,32),np.uint8) if d is None else d[:180].astype(np.uint8)

def _encode_orb(d):
    return ("",0) if d.size==0 else (base64.b64encode(d.tobytes()).decode("ascii"),int(d.shape[0]))
def _decode_orb(s,rows):
    if not s or rows<=0:return np.empty((0,32),np.uint8)
    a=np.frombuffer(base64.b64decode(s),dtype=np.uint8)
    return a[:rows*32].reshape((rows,32)) if a.size>=rows*32 else np.empty((0,32),np.uint8)

def extract_phase4(data):
    img=_decode(data); crop,mask,bbox=_foreground(img); gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
    h,w=crop.shape[:2]
    f={"version":4,"bbox":bbox,"aspect":round(w/max(h,1),6),"fill":round(np.count_nonzero(mask)/(mask.size or 1),6),
       "hu":_hu(mask),"globalColor":_hist(crop,mask),"edge":_edge(gray,mask),"regions":_regions(crop,mask)}
    return f,_orb(gray,mask)

def _cos(a,b):
    if not a or not b:return 0.0
    n=min(len(a),len(b)); av=np.asarray(a[:n],np.float32); bv=np.asarray(b[:n],np.float32)
    na=float(np.linalg.norm(av)); nb=float(np.linalg.norm(bv))
    return 0.0 if na<1e-9 or nb<1e-9 else float(np.dot(av,bv)/(na*nb))

def _shape(a,b):
    ar=max(0,1-abs(a.get("aspect",0)-b.get("aspect",0))/1.5)
    fill=max(0,1-abs(a.get("fill",0)-b.get("fill",0))*2)
    ah=a.get("hu") or []; bh=b.get("hu") or []
    hu=0
    if ah and bh:
        d=sum(min(5,abs(float(x)-float(y))) for x,y in zip(ah,bh))/len(ah); hu=max(0,1-d/4)
    return ar*.25+fill*.15+hu*.60

def _region(a,b):
    ra=a.get("regions") or {}; rb=b.get("regions") or {}; names=("heel","mid","toe","upper","sole")
    direct={n:_cos(ra.get(n,[]),rb.get(n,[])) for n in names}; swapped=dict(direct)
    swapped["heel"]=_cos(ra.get("heel",[]),rb.get("toe",[])); swapped["toe"]=_cos(ra.get("toe",[]),rb.get("heel",[]))
    sd=sum(direct.values())/5; ss=sum(swapped.values())/5
    return (ss,swapped) if ss>sd else (sd,direct)

def _orbscore(a,b):
    if a.size==0 or b.size==0:return 0.0
    pairs=cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(a,b,k=2); good=valid=0
    for p in pairs:
        if len(p)<2:continue
        valid+=1; m,n=p
        if m.distance<.72*n.distance:good+=1
    return 0.0 if not valid else min(1,good/max(8,min(len(a),len(b))*.45))

def _compare(q,qo,r,ro):
    shape=_shape(q,r); color=_cos(q.get("globalColor",[]),r.get("globalColor",[])); edge=_cos(q.get("edge",[]),r.get("edge",[]))
    reg,parts=_region(q,r); orb=_orbscore(qo,ro); total=shape*.23+reg*.25+edge*.16+orb*.25+color*.11
    return {"score":max(0,min(1,total)),"shape":shape,"regions":reg,"edge":edge,"keypoints":orb,"color":color,"parts":parts}

def remember_phase4(data,brand,model,source_product_id="",image_ref=""):
    migrate_phase4(); brand=brand.strip(); model=model.strip()
    if not brand or not model:raise ValueError("Marca y modelo son obligatorios.")
    feat,orb=extract_phase4(data); enc,rows=_encode_orb(orb); rid=uuid.uuid4().hex
    with _connect() as c:
        c.execute("""INSERT INTO shoe_visual_features_v4(id,brand,model,source_product_id,image_ref,feature_json,orb_b64,orb_rows,confirmed,created_at)
                     VALUES(?,?,?,?,?,?,?,?,1,?)""",(rid,brand,model,source_product_id,image_ref,json.dumps(feat,separators=(",",":")),enc,rows,_now())); c.commit()
    try: remember_visual(data,brand,model,source_product_id=source_product_id,image_ref=image_ref)
    except Exception: pass
    return {"status":"ok","referenceId":rid,"brand":brand,"model":model,"keypoints":rows}

def recognize_phase4(data,limit=8):
    migrate_phase4(); q,qo=extract_phase4(data)
    with _connect() as c: rows=[dict(r) for r in c.execute("SELECT * FROM shoe_visual_features_v4 WHERE confirmed=1").fetchall()]
    best={}
    for row in rows:
        try: ev=_compare(q,qo,json.loads(row["feature_json"]),_decode_orb(row.get("orb_b64") or "",int(row.get("orb_rows") or 0)))
        except Exception: continue
        k=(row["brand"],row["model"])
        if k not in best or ev["score"]>best[k]["confidence"]:best[k]={"brand":row["brand"],"model":row["model"],"confidence":ev["score"],"evidence":ev}
    items=sorted(best.values(),key=lambda x:x["confidence"],reverse=True)
    for item in items:
        item["confidence"]=round(float(item["confidence"]),4); ev=item["evidence"]
        for k in ("shape","regions","edge","keypoints","color","score"):ev[k]=round(float(ev[k]),4)
        ev["parts"]={k:round(float(v),4) for k,v in ev["parts"].items()}
    return {"status":"ok","engine":"phase4-object-regional","references":len(rows),"queryKeypoints":int(qo.shape[0]),
            "items":items[:max(1,min(int(limit),25))],
            "message":"Fase 4 necesita referencias confirmadas para reconocer modelos." if not rows else ""}
