from __future__ import annotations

import hashlib, io, json, math, shutil, sqlite3, threading, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, ImageStat, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
from services.runtime_config import data_dir
DATA = data_dir()
DB = DATA / "elegance.sqlite3"
STORE = DATA / "automation_batches"
EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="elegance-batch")
LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript('''
    CREATE TABLE IF NOT EXISTS automation_jobs(
      id TEXT PRIMARY KEY, status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
      stage TEXT NOT NULL DEFAULT 'queued', total_files INTEGER NOT NULL DEFAULT 0,
      processed_files INTEGER NOT NULL DEFAULT 0, options_json TEXT NOT NULL DEFAULT '{}',
      result_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
      cancel_requested INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS automation_files(
      id TEXT PRIMARY KEY, job_id TEXT NOT NULL, filename TEXT NOT NULL,
      original_path TEXT NOT NULL, sha256 TEXT NOT NULL, perceptual_hash TEXT,
      status TEXT NOT NULL DEFAULT 'queued', duplicate_of TEXT, group_no INTEGER,
      metadata_json TEXT NOT NULL DEFAULT '{}', outputs_json TEXT NOT NULL DEFAULT '{}',
      error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
      FOREIGN KEY(job_id) REFERENCES automation_jobs(id)
    );
    CREATE INDEX IF NOT EXISTS idx_automation_jobs_status ON automation_jobs(status,created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_automation_files_job ON automation_files(job_id);
    CREATE INDEX IF NOT EXISTS idx_automation_files_sha ON automation_files(sha256);
    CREATE TABLE IF NOT EXISTS automation_groups(
      job_id TEXT NOT NULL, group_no INTEGER NOT NULL, cover_file_id TEXT,
      category TEXT NOT NULL DEFAULT '', subcategory TEXT NOT NULL DEFAULT '',
      brand TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
      confidence REAL NOT NULL DEFAULT 0, explanation TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'review', updated_at TEXT NOT NULL,
      PRIMARY KEY(job_id,group_no)
    );
    CREATE INDEX IF NOT EXISTS idx_automation_groups_job ON automation_groups(job_id,group_no);
    ''')
    return c


def migrate_batch_automation() -> dict[str, Any]:
    STORE.mkdir(parents=True, exist_ok=True)
    with _connect() as c:
        # Interrupted work is recoverable instead of silently being marked complete.
        c.execute("UPDATE automation_jobs SET status='recoverable',stage='interrupted',updated_at=? WHERE status='running'", (_now(),))
        jobs = c.execute("SELECT COUNT(*) FROM automation_jobs").fetchone()[0]
    return {"status": "ok", "jobs": jobs, "recovery": True}


def _dhash(img: Image.Image, size: int = 8) -> str:
    gray = ImageOps.exif_transpose(img).convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = list(gray.getdata())
    bits = []
    for y in range(size):
        row = y * (size + 1)
        for x in range(size):
            bits.append(px[row + x] > px[row + x + 1])
    value = sum((1 << i) for i, bit in enumerate(bits) if bit)
    return f"{value:0{size*size//4}x}"


def _ham(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def _feature(img: Image.Image) -> list[float]:
    rgb_full = ImageOps.exif_transpose(img).convert("RGB")
    w, h = rgb_full.size
    left, top = int(w * 0.12), int(h * 0.10)
    right, bottom = int(w * 0.88), int(h * 0.78)
    crop = rgb_full.crop((left, top, right, bottom)) if right > left and bottom > top else rgb_full
    rgb = crop.resize((96, 96), Image.Resampling.LANCZOS)

    feat: list[float] = []
    for gy in range(2):
        for gx in range(2):
            block = rgb.crop((gx*48, gy*48, (gx+1)*48, (gy+1)*48))
            area = 48 * 48
            for channel in block.split():
                hist = channel.histogram()
                for i in range(8):
                    feat.append(sum(hist[i*32:(i+1)*32]) / area)

    gray = rgb.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    ep = list(edges.getdata())
    for ybin in range(12):
        y0, y1 = ybin*8, (ybin+1)*8
        feat.append(sum(ep[yy*96 + x] for yy in range(y0, y1) for x in range(96)) / (8*96*255))
    for xbin in range(12):
        x0, x1 = xbin*8, (xbin+1)*8
        feat.append(sum(ep[y*96 + xx] for y in range(96) for xx in range(x0, x1)) / (8*96*255))

    stat = ImageStat.Stat(rgb)
    feat.extend([w / max(h, 1), *(x / 255 for x in stat.mean)])
    norm = math.sqrt(sum(x*x for x in feat)) or 1.0
    return [x / norm for x in feat]

def _cos(a: list[float], b: list[float]) -> float:
    return sum(x*y for x, y in zip(a, b))


def _quality_metrics(img: Image.Image) -> dict[str, float]:
    """Cheap deterministic quality assessment for cover selection."""
    rgb = ImageOps.exif_transpose(img).convert("RGB")
    sample = rgb.copy(); sample.thumbnail((720, 720), Image.Resampling.LANCZOS)
    gray = sample.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_stat = ImageStat.Stat(edges)
    sharpness = min(100.0, float(edge_stat.var[0]) ** 0.5 * 2.2)
    lum = float(ImageStat.Stat(gray).mean[0])
    exposure = max(0.0, 100.0 - abs(lum - 132.0) * 0.72)
    w, h = sample.size
    area_score = min(100.0, (w*h) / (900*900) * 100.0)
    aspect = w / max(h, 1)
    aspect_score = max(20.0, 100.0 - abs(aspect - 1.0) * 55.0)
    score = round(sharpness*0.45 + exposure*0.25 + area_score*0.15 + aspect_score*0.15, 2)
    return {"sharpness": round(sharpness,2), "exposure": round(exposure,2), "resolution": round(area_score,2), "aspect": round(aspect_score,2), "coverScore": score}


def _ensure_group_rows(job_id: str) -> None:
    with _connect() as c:
        groups=c.execute("SELECT DISTINCT group_no FROM automation_files WHERE job_id=? AND group_no IS NOT NULL ORDER BY group_no",(job_id,)).fetchall()
        for r in groups:
            g=int(r[0]); rows=c.execute("SELECT id,metadata_json FROM automation_files WHERE job_id=? AND group_no=? AND status NOT IN ('deleted','duplicate','near_duplicate')",(job_id,g)).fetchall()
            best=None; best_score=-1.0
            for row in rows:
                try: score=float(json.loads(row['metadata_json'] or '{}').get('quality',{}).get('coverScore',0))
                except Exception: score=0
                if score>best_score: best,best_score=row['id'],score
            count=len(rows)
            confidence = 0.50 if count == 1 else min(0.82, 0.58 + min(count,4)*0.05)
            explanation=f"Agrupación visual conservadora; {count} vista(s). Portada elegida por nitidez, exposición y resolución."
            c.execute("INSERT INTO automation_groups(job_id,group_no,cover_file_id,confidence,explanation,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(job_id,group_no) DO UPDATE SET cover_file_id=COALESCE(automation_groups.cover_file_id,excluded.cover_file_id),confidence=excluded.confidence,explanation=excluded.explanation,updated_at=excluded.updated_at",(job_id,g,best,confidence,explanation,_now()))
        c.commit()


def _renumber_groups(job_id: str) -> None:
    with _connect() as c:
        nums=[int(r[0]) for r in c.execute("SELECT DISTINCT group_no FROM automation_files WHERE job_id=? AND group_no IS NOT NULL AND status!='deleted' ORDER BY group_no",(job_id,)).fetchall()]
        mapping={old:i+1 for i,old in enumerate(nums)}
        offset=1000000
        c.execute("UPDATE automation_files SET group_no=group_no+? WHERE job_id=? AND group_no IS NOT NULL",(offset,job_id))
        c.execute("UPDATE automation_groups SET group_no=group_no+? WHERE job_id=?",(offset,job_id))
        for old,new_no in mapping.items():
            c.execute("UPDATE automation_files SET group_no=? WHERE job_id=? AND group_no=?",(new_no,job_id,old+offset))
            c.execute("UPDATE automation_groups SET group_no=? WHERE job_id=? AND group_no=?",(new_no,job_id,old+offset))
        c.execute("DELETE FROM automation_groups WHERE job_id=? AND group_no>=?",(job_id,offset))
        c.commit()
    _ensure_group_rows(job_id)


def _set_job(job_id: str, **values: Any) -> None:
    values["updated_at"] = _now()
    cols = ",".join(f"{k}=?" for k in values)
    with _connect() as c:
        c.execute(f"UPDATE automation_jobs SET {cols} WHERE id=?", [*values.values(), job_id])
        c.commit()


def create_job(files: list[tuple[str, bytes]], options: dict[str, Any] | None = None) -> dict[str, Any]:
    migrate_batch_automation()
    if not files:
        raise ValueError("Selecciona al menos una imagen.")
    job_id = uuid.uuid4().hex
    folder = STORE / job_id / "originals"
    folder.mkdir(parents=True, exist_ok=True)
    now = _now()
    with _connect() as c:
        c.execute("INSERT INTO automation_jobs(id,status,progress,stage,total_files,options_json,result_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (job_id, "queued", 0, "queued", len(files), json.dumps(options or {}, ensure_ascii=False), "{}", now, now))
        for filename, data in files:
            if not data:
                continue
            fid = uuid.uuid4().hex
            ext = Path(filename).suffix.lower() or ".jpg"
            path = folder / f"{fid}{ext}"
            path.write_bytes(data)
            sha = hashlib.sha256(data).hexdigest()
            c.execute("INSERT INTO automation_files(id,job_id,filename,original_path,sha256,created_at) VALUES(?,?,?,?,?,?)",
                      (fid, job_id, filename, str(path), sha, now))
        c.commit()
    EXECUTOR.submit(_run_job, job_id)
    return {"status": "queued", "jobId": job_id, "total": len(files)}


def _cancelled(job_id: str) -> bool:
    with _connect() as c:
        row = c.execute("SELECT cancel_requested FROM automation_jobs WHERE id=?", (job_id,)).fetchone()
    return bool(row and row[0])


def _run_job(job_id: str) -> None:
    try:
        _set_job(job_id, status="running", stage="reading", progress=2, attempts=_attempts(job_id)+1, error="")
        with _connect() as c:
            rows = c.execute("SELECT * FROM automation_files WHERE job_id=? ORDER BY created_at,id", (job_id,)).fetchall()
        items = []
        exact: dict[str, str] = {}
        for idx, row in enumerate(rows):
            if _cancelled(job_id):
                _set_job(job_id, status="cancelled", stage="cancelled")
                return
            stored_path = Path(row["original_path"])
            path = stored_path if stored_path.is_absolute() else ROOT / stored_path
            try:
                img = Image.open(path)
                img.load()
                ph = _dhash(img)
                feat = _feature(img)
                duplicate_of = exact.get(row["sha256"])
                if duplicate_of is None:
                    exact[row["sha256"]] = row["id"]
                meta = {"width": img.width, "height": img.height, "format": img.format, "visualFeature": "color-histogram+dHash", "quality": _quality_metrics(img)}
                with _connect() as c:
                    c.execute("UPDATE automation_files SET perceptual_hash=?,status=?,duplicate_of=?,metadata_json=? WHERE id=?",
                              (ph, "duplicate" if duplicate_of else "analyzed", duplicate_of, json.dumps(meta), row["id"]))
                    c.commit()
                items.append({"id": row["id"], "filename": row["filename"], "path": path, "sha": row["sha256"], "ph": ph, "feat": feat, "duplicate_of": duplicate_of, "meta": meta})
            except Exception as exc:
                with _connect() as c:
                    c.execute("UPDATE automation_files SET status='failed',error=? WHERE id=?", (str(exc), row["id"]))
                    c.commit()
            _set_job(job_id, processed_files=idx+1, progress=min(45, 5 + int(40*(idx+1)/max(len(rows),1))), stage="analyzing")

        unique = [x for x in items if not x["duplicate_of"]]
        # Near-duplicate detection is conservative: dHash <= 3. Different angles remain available.
        for i, item in enumerate(unique):
            for prev in unique[:i]:
                if _ham(item["ph"], prev["ph"]) <= 3:
                    item["duplicate_of"] = prev["id"]
                    with _connect() as c:
                        c.execute("UPDATE automation_files SET status='near_duplicate',duplicate_of=? WHERE id=?", (prev["id"], item["id"]))
                        c.commit()
                    break
        candidates = [x for x in unique if not x["duplicate_of"]]
        groups: list[list[dict[str, Any]]] = []
        raw_threshold = float(_options(job_id).get("groupSimilarity", 0.965))
        feature_threshold = 0.982 if raw_threshold >= 0.975 else (0.974 if raw_threshold >= 0.965 else 0.965)
        hash_limit = 11 if raw_threshold >= 0.975 else (14 if raw_threshold >= 0.965 else 17)
        for item in candidates:
            best_group = None
            best_score = -1.0
            for group in groups:
                comparisons = []
                for other in group:
                    visual = _cos(item["feat"], other["feat"])
                    hdist = _ham(item["ph"], other["ph"])
                    comparisons.append((visual, hdist))
                rep_visual, rep_hash = comparisons[0]
                mean_visual = sum(v for v, _ in comparisons) / len(comparisons)
                worst_hash = max(h for _, h in comparisons)
                min_visual = min(v for v, _ in comparisons)
                passes = (
                    rep_visual >= feature_threshold
                    and mean_visual >= feature_threshold - 0.004
                    and min_visual >= feature_threshold - 0.010
                    and rep_hash <= hash_limit
                    and worst_hash <= hash_limit + 4
                )
                score = mean_visual - (worst_hash / 64.0) * 0.12
                if passes and score > best_score:
                    best_group, best_score = group, score
            if best_group is not None:
                best_group.append(item)
            else:
                groups.append([item])
        _set_job(job_id, stage="grouping", progress=60)

        # Generate lightweight, non-destructive derivatives.
        thumbs = STORE / job_id / "thumbnails"; webps = STORE / job_id / "webp"
        thumbs.mkdir(parents=True, exist_ok=True); webps.mkdir(parents=True, exist_ok=True)
        processed = 0
        for group_no, group in enumerate(groups, 1):
            for item in group:
                if _cancelled(job_id):
                    _set_job(job_id, status="cancelled", stage="cancelled")
                    return
                img = ImageOps.exif_transpose(Image.open(item["path"])).convert("RGB")
                thumb = img.copy(); thumb.thumbnail((420,420), Image.Resampling.LANCZOS)
                tp = thumbs / f"{item['id']}.webp"; thumb.save(tp, "WEBP", quality=82, method=6)
                full = img.copy(); full.thumbnail((1800,1800), Image.Resampling.LANCZOS)
                wp = webps / f"{item['id']}.webp"; full.save(wp, "WEBP", quality=88, method=6)
                outputs = {
                    "thumbnail": str(tp),
                    "webp": str(wp),
                    "thumbnailUrl": f"/api/integral/media/{job_id}/thumbnails/{tp.name}",
                    "webpUrl": f"/api/integral/media/{job_id}/webp/{wp.name}",
                }
                with _connect() as c:
                    c.execute("UPDATE automation_files SET status='ready',group_no=?,outputs_json=? WHERE id=?", (group_no, json.dumps(outputs), item["id"]))
                    c.commit()
                processed += 1
                _set_job(job_id, stage="derivatives", progress=min(92, 62 + int(30*processed/max(len(candidates),1))))

        _ensure_group_rows(job_id)
        result = {
            "groups": [{"group": n, "files": [x["id"] for x in g], "count": len(g)} for n,g in enumerate(groups,1)],
            "groupCount": len(groups),
            "exactDuplicates": sum(1 for x in items if x["duplicate_of"]),
            "uniqueReady": processed,
            "recognition": {"semantic": False, "method": "low-level visual grouping; existing OCR/catalog classifier remains available during review"},
            "originalsPreserved": True,
        }
        _set_job(job_id, status="completed", stage="completed", progress=100, result_json=json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        _set_job(job_id, status="failed", stage="failed", error=str(exc))


def _attempts(job_id: str) -> int:
    with _connect() as c:
        row = c.execute("SELECT attempts FROM automation_jobs WHERE id=?", (job_id,)).fetchone()
    return int(row[0]) if row else 0


def _options(job_id: str) -> dict[str, Any]:
    with _connect() as c:
        row = c.execute("SELECT options_json FROM automation_jobs WHERE id=?", (job_id,)).fetchone()
    try: return json.loads(row[0]) if row else {}
    except Exception: return {}


def get_job(job_id: str) -> dict[str, Any]:
    with _connect() as c:
        job = c.execute("SELECT * FROM automation_jobs WHERE id=?", (job_id,)).fetchone()
        files = c.execute("SELECT * FROM automation_files WHERE job_id=? ORDER BY group_no,created_at,id", (job_id,)).fetchall()
    if not job: raise KeyError(job_id)
    data = dict(job)
    for key in ("options_json", "result_json"):
        try: data[key[:-5]] = json.loads(data.pop(key))
        except Exception: data[key[:-5]] = {}
    data["files"] = []
    for row in files:
        f = dict(row)
        for key in ("metadata_json", "outputs_json"):
            try: f[key[:-5]] = json.loads(f.pop(key))
            except Exception: f[key[:-5]] = {}
        data["files"].append(f)
    with _connect() as c:
        grows=c.execute("SELECT * FROM automation_groups WHERE job_id=? ORDER BY group_no",(job_id,)).fetchall()
    data["groups"]=[dict(r) for r in grows]
    return data


def list_jobs(limit: int = 30) -> list[dict[str, Any]]:
    with _connect() as c:
        rows = c.execute("SELECT * FROM automation_jobs ORDER BY created_at DESC LIMIT ?", (max(1,min(limit,100)),)).fetchall()
    return [{k:v for k,v in dict(r).items() if k not in {"options_json","result_json"}} for r in rows]


def move_file(job_id: str, file_id: str, target_group: int) -> dict[str, Any]:
    if target_group < 1: raise ValueError("Grupo destino inválido.")
    with _connect() as c:
        row=c.execute("SELECT id FROM automation_files WHERE job_id=? AND id=?",(job_id,file_id)).fetchone()
        if not row: raise KeyError(file_id)
        c.execute("UPDATE automation_files SET group_no=?,status=CASE WHEN status='deleted' THEN 'ready' ELSE status END WHERE job_id=? AND id=?",(target_group,job_id,file_id)); c.commit()
    _renumber_groups(job_id); return get_job(job_id)


def merge_groups(job_id: str, source_groups: list[int], target_group: int | None=None) -> dict[str, Any]:
    nums=sorted({int(x) for x in source_groups if int(x)>0})
    if len(nums)<2: raise ValueError("Selecciona al menos dos grupos.")
    target=int(target_group or nums[0])
    with _connect() as c:
        for g in nums:
            if g!=target: c.execute("UPDATE automation_files SET group_no=? WHERE job_id=? AND group_no=?",(target,job_id,g))
        c.execute("DELETE FROM automation_groups WHERE job_id=? AND group_no IN (%s)" % ','.join('?'*len(nums)),[job_id,*nums]); c.commit()
    _renumber_groups(job_id); return get_job(job_id)


def split_group(job_id: str, file_ids: list[str]) -> dict[str, Any]:
    ids=[str(x) for x in file_ids if x]
    if not ids: raise ValueError("Selecciona fotografías para separar.")
    with _connect() as c:
        row=c.execute("SELECT COALESCE(MAX(group_no),0)+1 FROM automation_files WHERE job_id=?",(job_id,)).fetchone(); new_group=int(row[0])
        marks=','.join('?'*len(ids)); c.execute(f"UPDATE automation_files SET group_no=? WHERE job_id=? AND id IN ({marks})",[new_group,job_id,*ids]); c.commit()
    _renumber_groups(job_id); return get_job(job_id)


def set_cover(job_id: str, group_no: int, file_id: str) -> dict[str, Any]:
    with _connect() as c:
        row=c.execute("SELECT 1 FROM automation_files WHERE job_id=? AND group_no=? AND id=? AND status!='deleted'",(job_id,group_no,file_id)).fetchone()
        if not row: raise ValueError("La fotografía no pertenece al grupo.")
        c.execute("INSERT INTO automation_groups(job_id,group_no,cover_file_id,updated_at) VALUES(?,?,?,?) ON CONFLICT(job_id,group_no) DO UPDATE SET cover_file_id=excluded.cover_file_id,updated_at=excluded.updated_at",(job_id,group_no,file_id,_now())); c.commit()
    return get_job(job_id)


def delete_file(job_id: str, file_id: str) -> dict[str, Any]:
    with _connect() as c:
        row=c.execute("SELECT outputs_json FROM automation_files WHERE job_id=? AND id=?",(job_id,file_id)).fetchone()
        if not row: raise KeyError(file_id)
        c.execute("UPDATE automation_files SET status='deleted',group_no=NULL WHERE job_id=? AND id=?",(job_id,file_id)); c.commit()
    _renumber_groups(job_id); return get_job(job_id)


def update_group(job_id: str, group_no: int, payload: dict[str, Any]) -> dict[str, Any]:
    allowed=['category','subcategory','brand','model','status']; fields=[]; vals=[]
    for k in allowed:
        if k in payload: fields.append(f"{k}=?"); vals.append(str(payload.get(k) or '').strip())
    if not fields: return get_job(job_id)
    fields.append('updated_at=?'); vals.append(_now()); vals.extend([job_id,group_no])
    with _connect() as c:
        c.execute("INSERT OR IGNORE INTO automation_groups(job_id,group_no,updated_at) VALUES(?,?,?)",(job_id,group_no,_now()))
        c.execute(f"UPDATE automation_groups SET {','.join(fields)} WHERE job_id=? AND group_no=?",vals); c.commit()
    return get_job(job_id)


def cancel_job(job_id: str) -> dict[str, Any]:
    _set_job(job_id, cancel_requested=1, stage="cancelling")
    return {"status":"cancelling","jobId":job_id}


def retry_job(job_id: str) -> dict[str, Any]:
    with _connect() as c:
        if not c.execute("SELECT 1 FROM automation_jobs WHERE id=?", (job_id,)).fetchone(): raise KeyError(job_id)
        c.execute("UPDATE automation_files SET status='queued',duplicate_of=NULL,group_no=NULL,outputs_json='{}',error='' WHERE job_id=?", (job_id,))
        c.execute("UPDATE automation_jobs SET status='queued',progress=0,stage='queued',processed_files=0,cancel_requested=0,error='',updated_at=? WHERE id=?", (_now(),job_id))
        c.commit()
    EXECUTOR.submit(_run_job, job_id)
    return {"status":"queued","jobId":job_id}


def resolve_batch_media(job_id: str, kind: str, filename: str) -> Path:
    if kind not in {"originals", "thumbnails", "webp"}:
        raise ValueError("Tipo de archivo inválido.")
    safe_name = Path(filename).name
    path = STORE / job_id / kind / safe_name
    if not path.exists():
        raise FileNotFoundError(path)
    return path

def regroup_job(job_id: str, similarity: float | None = None) -> dict[str, Any]:
    with _connect() as c:
        job = c.execute("SELECT * FROM automation_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise KeyError(job_id)
        rows = c.execute(
            "SELECT * FROM automation_files WHERE job_id=? AND status NOT IN ('deleted','duplicate','near_duplicate','failed') ORDER BY created_at,id",
            (job_id,),
        ).fetchall()

    items = []
    fallback_ids = []
    for row in rows:
        candidates = []
        stored = Path(row["original_path"])
        candidates.append(stored if stored.is_absolute() else ROOT / stored)

        try:
            outputs = json.loads(row["outputs_json"] or "{}")
        except Exception:
            outputs = {}

        for key in ("webp", "thumbnail"):
            value = outputs.get(key)
            if value:
                p = Path(value)
                candidates.append(p if p.is_absolute() else ROOT / p)

        loaded = None
        for candidate in candidates:
            try:
                if candidate.exists():
                    img = Image.open(candidate)
                    img.load()
                    loaded = img
                    break
            except Exception:
                continue

        if loaded is None:
            fallback_ids.append(row["id"])
            continue

        items.append({
            "id": row["id"],
            "feat": _feature(loaded),
            "ph": row["perceptual_hash"] or _dhash(loaded),
        })

    opts = _options(job_id)
    raw = float(similarity if similarity is not None else opts.get("groupSimilarity", 0.965))
    feature_threshold = 0.982 if raw >= 0.975 else (0.974 if raw >= 0.965 else 0.965)
    hash_limit = 11 if raw >= 0.975 else (14 if raw >= 0.965 else 17)

    groups: list[list[dict[str, Any]]] = []
    for item in items:
        best_group = None
        best_score = -1.0
        for group in groups:
            comparisons = []
            for other in group:
                visual = _cos(item["feat"], other["feat"])
                hdist = _ham(item["ph"], other["ph"])
                comparisons.append((visual, hdist))
            rep_visual, rep_hash = comparisons[0]
            mean_visual = sum(v for v, _ in comparisons) / len(comparisons)
            min_visual = min(v for v, _ in comparisons)
            worst_hash = max(h for _, h in comparisons)
            passes = (
                rep_visual >= feature_threshold
                and mean_visual >= feature_threshold - 0.004
                and min_visual >= feature_threshold - 0.010
                and rep_hash <= hash_limit
                and worst_hash <= hash_limit + 4
            )
            score = mean_visual - (worst_hash / 64.0) * 0.12
            if passes and score > best_score:
                best_group, best_score = group, score
        if best_group is not None:
            best_group.append(item)
        else:
            groups.append([item])

    with _connect() as c:
        c.execute("DELETE FROM automation_groups WHERE job_id=?", (job_id,))
        c.execute(
            "UPDATE automation_files SET group_no=NULL WHERE job_id=? AND status NOT IN ('deleted','duplicate','near_duplicate','failed')",
            (job_id,),
        )
        next_group = 1
        for group in groups:
            for item in group:
                c.execute(
                    "UPDATE automation_files SET group_no=? WHERE job_id=? AND id=?",
                    (next_group, job_id, item["id"]),
                )
            next_group += 1

        for file_id in fallback_ids:
            c.execute(
                "UPDATE automation_files SET group_no=? WHERE job_id=? AND id=?",
                (next_group, job_id, file_id),
            )
            next_group += 1

        orphan_rows = c.execute(
            "SELECT id FROM automation_files WHERE job_id=? AND group_no IS NULL "
            "AND status NOT IN ('deleted','duplicate','near_duplicate','failed') "
            "ORDER BY created_at,id",
            (job_id,),
        ).fetchall()
        for orphan in orphan_rows:
            c.execute(
                "UPDATE automation_files SET group_no=? WHERE job_id=? AND id=?",
                (next_group, job_id, orphan["id"]),
            )
            next_group += 1

        c.execute(
            "UPDATE automation_jobs SET stage='completed',status='completed',progress=100,updated_at=? WHERE id=?",
            (_now(), job_id),
        )
        c.commit()

    _ensure_group_rows(job_id)
    return get_job(job_id)
