from __future__ import annotations

import base64
import json
from typing import Annotated

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from models.schemas import AnalyzeResponse, HealthResponse
from services.analyzer import AnalyzerService
from services.composer import compose_product
from services.state_store import database_path, load_state, save_state
from services.cloud_database import check_cloud_database
from services.deployment_readiness import deployment_readiness
from services.cloud_storage import storage_status as cloud_storage_status, store_bytes
from services.home_server import server_status as home_server_status, run_scheduled_backup, copy_backup_external
from services.server_installation import installation_report as block8_installation_report
from services.mobile_command_center import (mobile_status, register_device, heartbeat as mobile_heartbeat, list_devices as mobile_devices, disable_device, create_emergency_snapshot, list_emergency_snapshots, snapshot_path)

from services.product_media_flow import (
    upload_batch as media_upload_batch, list_assets as product_media_list_assets, set_cover as media_set_cover,
    assign_variant as media_assign_variant, retry_asset as media_retry_asset, delete_asset as media_delete_asset,
)
from services.catalog_organizer import organize_state, normalize_brand
from services.image_io import decode_image
from recognition.learning_store import save_sample, sample_count
from services.universal_products import taxonomy_payload, settings as automation_settings, update_settings as set_automation_settings, classify as universal_classify, queue_review, list_reviews, resolve_review, review_detail, save_review_draft, set_review_cover, remove_review_image, save_product_attributes
from services.universal_intelligence import settings as intelligence_settings, update_settings as update_intelligence_settings, analyze_product as intelligence_analyze, decisions as intelligence_decisions, list_versions as intelligence_versions, restore_version as intelligence_restore, snapshot_product
from services.euiv import list_candidates as euiv_list_candidates, accept_candidate as euiv_accept_candidate, learn_reference as euiv_learn_reference
from services.visual_search_assistant import create_session as visual_search_create, register_result as visual_search_register, mark_applied as visual_search_mark_applied
from services.history_store import (
    capture_state_changes, correction_suggestions, memory_summary, recent_history
)

router = APIRouter()
analyzer = AnalyzerService()


@router.get("/health", response_model=HealthResponse)
@router.get("/api/health", response_model=HealthResponse, include_in_schema=False)
def health() -> HealthResponse:
    info = analyzer.health()
    return HealthResponse(**info)


@router.get("/api/system/cloud-database")
def cloud_database_status() -> dict:
    return {"status": "ok", "database": check_cloud_database().as_dict()}

@router.get("/api/system/deployment-readiness")
def deployment_readiness_status(check_database: bool = Query(True, alias="checkDatabase")) -> dict:
    return deployment_readiness(check_database=check_database)


@router.get("/api/system/storage")
def system_storage_status(check_remote: bool = Query(False, alias="checkRemote")) -> dict:
    return {"status": "ok", "storage": cloud_storage_status(check_remote=check_remote)}




@router.get("/api/system/home-server")
def home_server_public_status() -> dict:
    status = home_server_status()
    # Public diagnosis omits local filesystem paths and hostname.
    return {
        "status": status["status"],
        "server": {"mode": status["server"]["mode"], "schedulerRunning": status["server"]["schedulerRunning"]},
        "database": {"engine": status["database"]["engine"], "exists": status["database"]["exists"]},
        "storage": {"free": status["storage"]["free"], "freePercent": status["storage"]["freePercent"]},
        "backup": {"count": status["backup"]["count"], "latest": status["backup"]["latest"], "lastError": status["backup"]["lastError"]},
        "publicAccess": status["publicAccess"],
    }

@router.get("/api/admin/home-server")
def home_server_admin_status(request: Request) -> dict:
    _permit(request, "backups")
    return home_server_status()

@router.post("/api/admin/home-server/backups/run")
def home_server_run_backup(request: Request, kind: str = Query("daily")) -> dict:
    _permit(request, "backups")
    if kind not in {"daily", "weekly"}:
        raise HTTPException(status_code=400, detail="kind debe ser daily o weekly")
    return run_scheduled_backup(kind)

@router.post("/api/admin/home-server/backups/{name}/copy-external")
def home_server_copy_backup(name: str, request: Request) -> dict:
    _permit(request, "backups")
    try:
        return copy_backup_external(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Respaldo no encontrado") from exc



@router.get("/api/admin/server-installation")
def server_installation_status(request: Request, check_database: bool = Query(True, alias="checkDatabase")) -> dict:
    _permit(request, "backups")
    return block8_installation_report(check_database=check_database)

@router.get("/api/admin/mobile-command-center")
def mobile_command_center_status(request: Request) -> dict:
    _permit(request, "backups")
    return mobile_status()

@router.post("/api/admin/mobile-command-center/devices")
def mobile_register_device(request: Request, payload: dict = Body(...)) -> dict:
    _permit(request, "backups")
    return register_device(str(payload.get("name") or "S26 Ultra"), str(payload.get("platform") or "android"))

@router.post("/api/admin/mobile-command-center/devices/{device_id}/heartbeat")
def mobile_device_heartbeat(device_id: str, request: Request) -> dict:
    _permit(request, "backups")
    try:
        return mobile_heartbeat(device_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.delete("/api/admin/mobile-command-center/devices/{device_id}")
def mobile_disable_registered_device(device_id: str, request: Request) -> dict:
    _permit(request, "backups")
    try:
        return disable_device(device_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.get("/api/admin/mobile-command-center/snapshots")
def mobile_snapshot_list(request: Request) -> dict:
    _permit(request, "backups")
    return {"status": "ok", "snapshots": list_emergency_snapshots()}

@router.post("/api/admin/mobile-command-center/snapshots")
def mobile_snapshot_create(request: Request, include_database: bool = Query(True, alias="includeDatabase")) -> dict:
    _permit(request, "backups")
    return create_emergency_snapshot(include_database=include_database)

@router.get("/api/admin/mobile-command-center/snapshots/{name}/download")
def mobile_snapshot_download(name: str, request: Request) -> FileResponse:
    _permit(request, "backups")
    try:
        path = snapshot_path(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Copia de emergencia no encontrada") from exc
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.get("/api/public/config")
def public_runtime_config() -> dict:
    import os
    return {
        "status": "ok",
        "app": {
            "name": "Elegance",
            "version": "Cloud 2 RC2",
            "publicUrl": os.getenv("ELEGANCE_PUBLIC_URL", "").strip(),
            "catalogUrl": "/catalog",
            "apiBaseUrl": "/api",
        },
        "features": {
            "publicCatalog": True,
            "mobileUpload": True,
            "cloudStorage": cloud_storage_status(check_remote=False)["mode"] in {"supabase", "mirror"},
        },
        "limits": {"maxUploadMb": cloud_storage_status(check_remote=False)["maxUploadMb"]},
    }


@router.post("/api/storage/upload")
async def storage_upload(
    file: Annotated[UploadFile, File(...)],
    folder: Annotated[str, Form()] = "products/inbox",
) -> dict:
    data = await file.read()
    filename = file.filename or "upload.bin"
    try:
        return store_bytes(f"{folder}/{filename}", data, file.content_type or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/routes")
@router.get("/api/routes", include_in_schema=False)
def routes_status() -> dict:
    return {
        "status": "ok",
        "version": "Cloud 1.5",
        "endpoints": ["/automation", "/api/automation/batches", "/group", "/compose", "/auto-process", "/api/state", "/api/catalog/reorganize", "/api/catalog/categories", "/api/inventory/health", "/api/inventory/duplicates", "/api/inventory/merge", "/api/inventory/audit", "/api/library/search", "/library", "/studio", "/api/studio/preview", "/api/studio/batch", "/api/studio/history", "/commercial", "/api/customers", "/api/orders", "/api/commercial/dashboard", "/catalog", "/catalog-admin", "/api/public/products", "/api/public/requests"],
        "workflow": "exact duplicates -> local grouping -> local identification -> automatic catalog/inventory/publications",
        "paid_api_required": False,
        "recognition_samples": sample_count(),
        "recognition": "brand-first + multi-view + OCR + learned references",
        "database": database_path(),
    }


@router.get("/api/state")
def get_application_state() -> dict:
    return {"status": "ok", "state": load_state(), "database": database_path()}


@router.post("/api/state")
def set_application_state(payload: dict = Body(...)) -> dict:
    state = payload.get("state", payload)
    if not isinstance(state, dict):
        raise HTTPException(status_code=400, detail="El estado debe ser un objeto JSON.")
    state.pop("openAiKey", None)
    state.pop("googleVisionKey", None)
    previous = load_state()
    organized = organize_state(state, move_files=True)
    organized["state"] = migrate_inventory_state(organized["state"])
    changes = capture_state_changes(previous, organized["state"])
    save_state(organized["state"])
    return {
        "status": "ok",
        "database": database_path(),
        "catalog": {k: v for k, v in organized.items() if k != "state"},
        "history": changes,
        "memory": memory_summary(),
    }


@router.get("/api/history")
def history(product_id: str = "", limit: int = 100) -> dict:
    return {"status": "ok", "events": recent_history(product_id=product_id, limit=limit)}


@router.get("/api/memory/summary")
def get_memory_summary() -> dict:
    return {"status": "ok", **memory_summary(), "recognition_samples": sample_count()}


@router.get("/api/memory/suggestions")
def get_memory_suggestions(brand: str = "", model: str = "", limit: int = 20) -> dict:
    return {
        "status": "ok",
        "suggestions": correction_suggestions(brand=brand, model=model, limit=limit),
    }


@router.post("/api/catalog/reorganize")
def reorganize_catalog() -> dict:
    state = load_state()
    organized = organize_state(state, move_files=True)
    organized["state"] = migrate_inventory_state(organized["state"])
    save_state(organized["state"])
    return {"status": "ok", **{k: v for k, v in organized.items() if k != "state"}}


@router.get("/api/catalog/categories")
def catalog_categories() -> dict:
    organized = organize_state(load_state(), move_files=False)
    return {"status": "ok", "categories": organized["categories"]}


@router.post("/api/recognition/learn")
def learn_recognition(payload: dict = Body(...)) -> dict:
    image_b64 = str(payload.get("image_base64", "")).strip()
    brand = str(payload.get("brand", "")).strip()
    model = str(payload.get("model", "")).strip()
    title = str(payload.get("title", "")).strip()
    sku = str(payload.get("sku", "")).strip()
    if not image_b64 or not brand or not model or not title:
        raise HTTPException(status_code=400, detail="Faltan imagen, marca, modelo o título.")
    try:
        data = base64.b64decode(image_b64)
        decoded = decode_image(data)
        embedding = analyzer.engine.encode_multiview([decoded.pil])[0]
        save_sample(brand=brand, model=model, title=title, sku=sku, embedding=embedding)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo guardar el aprendizaje: {exc}") from exc
    return {"status": "ok", "samples": sample_count()}


@router.post("/group", response_model=AnalyzeResponse)
@router.post("/api/group", response_model=AnalyzeResponse, include_in_schema=False)
async def group_images(
    files: Annotated[list[UploadFile], File(...)],
    eps: Annotated[float, Query(ge=0.05, le=1.0)] = 0.10,
    min_samples: Annotated[int, Query(ge=1, le=10)] = 1,
) -> AnalyzeResponse:
    return await _analyze(files, eps=eps, min_samples=min_samples)


@router.post("/analyze", response_model=AnalyzeResponse)
@router.post("/api/analyze", response_model=AnalyzeResponse, include_in_schema=False)
async def analyze_images(
    files: Annotated[list[UploadFile], File(...)],
    eps: Annotated[float, Query(ge=0.05, le=1.0)] = 0.10,
    min_samples: Annotated[int, Query(ge=1, le=10)] = 1,
) -> AnalyzeResponse:
    return await _analyze(files, eps=eps, min_samples=min_samples)


@router.post("/compose")
@router.post("/api/compose", include_in_schema=False)
async def compose_image(
    file: Annotated[UploadFile, File(...)],
    brand_theme: Annotated[str, Form()] = "Automático",
) -> Response:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="La imagen está vacía.")
    try:
        output = compose_product(data, brand_theme=brand_theme)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(content=output, media_type="image/png")


@router.post("/compose-generative")
@router.post("/api/compose-generative", include_in_schema=False)
async def compose_generative_image(
    file: Annotated[UploadFile, File(...)],
    brand_theme: Annotated[str, Form()] = "Automático",
    product_name: Annotated[str, Form()] = "",
) -> Response:
    """Compatibilidad V23: compositor local gratuito, sin APIs de pago."""
    del product_name
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="La imagen está vacía.")
    try:
        output = compose_product(data, brand_theme=brand_theme)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(
        content=output,
        media_type="image/png",
        headers={"X-Elegance-Visual-Engine": "local-free"},
    )


@router.post("/auto-process")
@router.post("/api/auto-process", include_in_schema=False)
@router.post("/pipeline", include_in_schema=False)
async def auto_process_image(
    file: Annotated[UploadFile, File(...)],
    local_brand: Annotated[str, Form()] = "",
    local_model: Annotated[str, Form()] = "",
    color: Annotated[str, Form()] = "",
) -> JSONResponse:
    """Flujo local V23: identifica sin pago y nunca bloquea el catálogo por no conocer el modelo."""
    del local_brand, local_model, color
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="La imagen está vacía.")
    try:
        analyzed = await analyzer.analyze(
            [UploadFile(filename=file.filename or "producto.jpg", file=__import__("io").BytesIO(data))],
            eps=0.075,
            min_samples=1,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not analyzed.groups:
        raise HTTPException(status_code=400, detail="No se detectó un producto utilizable.")
    group = analyzed.groups[0]
    return JSONResponse({
        "status": "ok",
        "brand": group.brand,
        "model": group.model_family,
        "title": group.suggested_title,
        "brand_confidence": group.brand_confidence,
        "model_confidence": group.model_confidence,
        "needs_review": group.needs_manual_review,
        "publishable": True,
        "catalog_action": "created",
        "verification_provider": "local-free",
        "identification_engine": group.identification_method,
        "evidence": group.identification_evidence,
        "sku": group.sku,
        "scenario_applied": False,
        "visual_engine": "original-optimized",
        "visual_note": "V23 conserva la fotografía original. La edición generativa no es requisito para publicar.",
        "final_image_base64": base64.b64encode(data).decode("ascii"),
    })


async def _analyze(files: list[UploadFile], *, eps: float, min_samples: int) -> AnalyzeResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No se recibieron imágenes.")
    if len(files) > 250:
        raise HTTPException(status_code=400, detail="Máximo 250 imágenes por lote.")
    try:
        return await analyzer.analyze(files, eps=eps, min_samples=min_samples)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc



# Sprint 3 RC2: Inventario Inteligente
from services.inventory_intelligence import (
    inventory_report, migrate_inventory_state, merge_products, recent_audit
)

@router.get("/api/inventory/health")
def inventory_health(low_stock: int = 2) -> dict:
    state = migrate_inventory_state(load_state())
    return {"status": "ok", **inventory_report(state, low_stock=max(0, low_stock))}

@router.get("/api/inventory/duplicates")
def inventory_duplicates() -> dict:
    report = inventory_report(load_state())
    return {"status": "ok", "groups": report["duplicates"], "count": report["duplicateGroups"]}

@router.post("/api/inventory/migrate")
def inventory_migrate() -> dict:
    previous = load_state()
    migrated = migrate_inventory_state(previous)
    save_state(migrated)
    return {"status": "ok", "preservedProducts": len(migrated.get("products", [])), **inventory_report(migrated)}

@router.post("/api/inventory/merge")
def inventory_merge(payload: dict = Body(...)) -> dict:
    try:
        return merge_products(str(payload.get("primaryId", "")), [str(x) for x in payload.get("duplicateIds", [])], bool(payload.get("confirm", False)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/api/inventory/audit")
def inventory_audit(limit: int = 100) -> dict:
    return {"status": "ok", "events": recent_audit(limit)}

# ---------------------------------------------------------------------------
# Sprint 2: Bandeja móvil + QR + PWA. Todo local y gratuito.
# ---------------------------------------------------------------------------
from fastapi import Request
from fastapi.responses import HTMLResponse
from services.premium_web import home_page as premium_home_page, catalog_page as premium_catalog_page, product_page as premium_product_page, admin_page as premium_admin_page, login_page as premium_login_page, setup_page as premium_setup_page, catalog_admin_page as premium_catalog_admin_page
from services.mobile_inbox import (
    batch_status as mobile_batch_status,
    create_batch as create_mobile_batch,
    mobile_url as get_mobile_url,
    recent_batches as get_recent_mobile_batches,
    save_upload as save_mobile_upload,
)
from services.mobile_ui import install_html, mobile_html


@router.get("/connect", response_class=HTMLResponse)
def connect_phone_page(request: Request) -> HTMLResponse:
    url = get_mobile_url()
    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='theme-color' content='#02070b'><link rel='manifest' href='/manifest.webmanifest'><meta property='og:title' content='Elegance móvil'><meta property='og:description' content='Conecta tu teléfono con Elegance'><style>body{{margin:0;background:#02080c;color:white;font-family:system-ui;display:grid;place-items:center;min-height:100vh}}.c{{text-align:center;background:#0a1620;border:1px solid #277da355;padding:30px;border-radius:25px;max-width:520px}}img{{background:white;padding:14px;border-radius:18px;width:280px}}h1{{color:#65d9ff;font-family:cursive;font-size:46px;margin:0}}a{{color:#65d9ff;word-break:break-all}}</style><div class='c'><h1>elegance</h1><h2>Conectar S26 Ultra</h2><img src='/connect/qr.png' alt='QR'><p>Escanea con la cámara de tu teléfono.</p><a href='{url}'>{url}</a><p>La PC y el S26 deben estar en el mismo Wi-Fi.</p></div>""")


@router.get("/connect/qr.png")
def connect_phone_qr() -> Response:
    try:
        import qrcode
        image = qrcode.make(get_mobile_url())
        buffer = __import__("io").BytesIO()
        image.save(buffer, format="PNG")
        return Response(buffer.getvalue(), media_type="image/png")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo generar QR: {exc}") from exc


@router.get("/mobile", response_class=HTMLResponse)
def mobile_uploader_page() -> HTMLResponse:
    return HTMLResponse(mobile_html())


@router.get("/mobile/install", response_class=HTMLResponse)
def mobile_install_page() -> HTMLResponse:
    return HTMLResponse(install_html())


@router.get("/mobile/manifest.webmanifest")
def mobile_manifest() -> JSONResponse:
    return JSONResponse({
        "name": "elegance móvil",
        "short_name": "elegance",
        "id": "/mobile",
        "start_url": "/mobile",
        "scope": "/mobile",
        "display": "standalone",
        "background_color": "#02080c",
        "theme_color": "#02080c",
        "icons": [{
            "src": "/pwa-icon.svg",
            "sizes": "any",
            "type": "image/svg+xml",
            "purpose": "any maskable",
        }],
    }, media_type="application/manifest+json")


@router.get("/mobile/sw.js")
def mobile_service_worker() -> Response:
    script = (
        "const C='elegance-mobile-v2';"
        "self.addEventListener('install',e=>e.waitUntil("
        "caches.open(C).then(c=>c.addAll(['/mobile','/mobile/install','/mobile/manifest.webmanifest','/pwa-icon.svg']))"
        ".then(()=>self.skipWaiting())));"
        "self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));"
        "self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;"
        "e.respondWith(fetch(e.request).then(r=>{const copy=r.clone();"
        "caches.open(C).then(c=>c.put(e.request,copy));return r})"
        ".catch(()=>caches.match(e.request).then(r=>r||caches.match('/mobile'))))});"
    )
    return Response(script, media_type="application/javascript")


@router.post("/api/mobile/batches")
def create_phone_batch(payload: dict = Body(...)) -> dict:
    return create_mobile_batch(str(payload.get("device_name", "S26 Ultra")), int(payload.get("total", 0)))


@router.post("/api/mobile/batches/{batch_id}/files")
async def upload_phone_file(batch_id: str, file: Annotated[UploadFile, File(...)]) -> dict:
    try:
        return await save_mobile_upload(batch_id, file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/mobile/batches/{batch_id}")
def phone_batch_status(batch_id: str) -> dict:
    try:
        return mobile_batch_status(batch_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Lote no encontrado") from exc


@router.get("/api/mobile/batches")
def phone_recent_batches() -> dict:
    return {"batches": get_recent_mobile_batches(), "mobile_url": get_mobile_url()}

# Sprint 3 RC3: Elegance AI local-first, suggestions never auto-save.
from services.elegance_ai import (migrate_ai_schema, suggest as ai_suggest, confirm as ai_confirm, history as ai_history,
    enterprise_analyze as ai_enterprise_analyze, batch_analyze as ai_batch_analyze,
    duplicate_scan as ai_duplicate_scan, process_image as ai_process_image,
    suggest_price as ai_suggest_price, image_fingerprint as ai_image_fingerprint)

@router.post("/api/ai/migrate")
def elegance_ai_migrate() -> dict:
    return migrate_ai_schema()

@router.post("/api/ai/suggest/{product_id}")
def elegance_ai_suggest(product_id: str) -> dict:
    try: return ai_suggest(product_id)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/api/ai/confirm")
def elegance_ai_confirm(payload: dict = Body(...)) -> dict:
    try: return ai_confirm(str(payload.get("suggestionId", "")), payload.get("corrections") or {}, bool(payload.get("confirm", False)))
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/api/ai/history")
def elegance_ai_history(product_id: str | None = None, limit: int = 100) -> dict:
    return {"status":"ok","events":ai_history(product_id,limit)}

@router.get("/ai", response_class=HTMLResponse)
def elegance_ai_page() -> HTMLResponse:
    return HTMLResponse("""<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{margin:0;background:#02080c;color:#eefaff;font:16px system-ui}.w{max-width:1050px;margin:auto;padding:22px}h1{font-family:cursive;color:#65d9ff;font-size:48px;margin:0}.card{background:#0a1620;border:1px solid #277da355;border-radius:20px;padding:18px;margin:14px 0}input,button,textarea{box-sizing:border-box;width:100%;padding:13px;margin:7px 0;border-radius:12px;border:1px solid #277da3;background:#071018;color:white}button{background:#087ea4;font-weight:800;cursor:pointer}.warn{color:#ffd166}.ok{color:#63ffa6}pre{white-space:pre-wrap;word-break:break-word}@media(min-width:800px){.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}}</style><div class='w'><h1>elegance AI</h1><p>Identificación y publicación asistida, local-first. Nada se guarda sin tu confirmación.</p><div class='grid'><div class='card'><h2>1. Sugerir</h2><input id='pid' placeholder='ID del producto'><button onclick='suggest()'>Analizar producto</button><pre id='out'>Esperando producto…</pre></div><div class='card'><h2>2. Revisar y confirmar</h2><input id='sid' placeholder='ID de sugerencia'><textarea id='cor' rows='8' placeholder='Correcciones JSON, por ejemplo {"model":"Air Jordan 4"}'></textarea><button onclick='confirmSuggestion()'>Confirmar y guardar</button><p class='warn'>Se preservan ID, imágenes, stock, precio, tallas, notas y fecha.</p><pre id='saved'></pre></div></div></div><script>async function suggest(){let r=await fetch('/api/ai/suggest/'+encodeURIComponent(pid.value),{method:'POST'});let j=await r.json();out.textContent=JSON.stringify(j,null,2);if(j.suggestionId)sid.value=j.suggestionId}async function confirmSuggestion(){let corrections={};try{corrections=cor.value?JSON.parse(cor.value):{}}catch(e){saved.textContent='JSON inválido';return}let r=await fetch('/api/ai/confirm',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({suggestionId:sid.value,corrections,confirm:true})});saved.textContent=JSON.stringify(await r.json(),null,2)}</script>""")

# Sprint 3 RC4: Elegance Studio. Originals are immutable; previews require approval.
from services.elegance_studio import create_preview as studio_preview, decide as studio_decide, restore as studio_restore, history as studio_history, migrate_studio

@router.post('/api/studio/migrate')
def studio_migrate() -> dict:
    return migrate_studio()

@router.post('/api/studio/preview')
async def studio_create_preview(file: Annotated[UploadFile, File(...)], product_id: Annotated[str, Form()] = '', options_json: Annotated[str, Form()] = '{}') -> dict:
    try:
        options=json.loads(options_json or '{}')
        return studio_preview(await file.read(),file.filename or 'producto.jpg',product_id or None,options)
    except (ValueError,json.JSONDecodeError) as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.post('/api/studio/decide/{version_id}')
def studio_decision(version_id: str, payload: dict = Body(...)) -> dict:
    try: return studio_decide(version_id,str(payload.get('action','')))
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.post('/api/studio/restore/{version_id}')
def studio_restore_version(version_id: str) -> dict:
    try: return studio_restore(version_id)
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/studio/history')
def studio_get_history(product_id: str|None=None, limit:int=100) -> dict:
    return {'status':'ok','events':studio_history(product_id,limit)}

@router.post('/api/studio/batch')
async def studio_batch(files: list[UploadFile] = File(...), product_id: Annotated[str,Form()]='', options_json: Annotated[str,Form()]='{}') -> dict:
    options=json.loads(options_json or '{}'); results=[]
    for f in files[:100]:
        try: results.append(studio_preview(await f.read(),f.filename or 'producto.jpg',product_id or None,options))
        except Exception as exc: results.append({'status':'error','filename':f.filename,'detail':str(exc)})
    return {'status':'ok','processed':len(results),'results':results}

@router.get('/studio', response_class=HTMLResponse)
def studio_page() -> HTMLResponse:
    return HTMLResponse("""<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{margin:0;background:#02080c;color:#eefaff;font:16px system-ui}.w{max-width:1100px;margin:auto;padding:20px}h1{font:54px cursive;color:#69ddff;margin:0}.card{background:#091620;border:1px solid #287b9e66;border-radius:22px;padding:18px;margin:15px 0}input,select,button{width:100%;box-sizing:border-box;padding:13px;margin:6px 0;border-radius:12px;border:1px solid #2783aa;background:#061018;color:white}button{background:#087ea4;font-weight:800}.grid{display:grid;gap:14px}@media(min-width:800px){.grid{grid-template-columns:1fr 1fr}}pre{white-space:pre-wrap;word-break:break-word}.warn{color:#ffd166}</style><div class='w'><h1>elegance Studio</h1><p>Procesamiento local y reversible. La imagen original nunca se reemplaza.</p><div class='grid'><div class='card'><h2>Crear vista previa</h2><input id='file' type='file' accept='image/*'><input id='pid' placeholder='ID del producto (opcional)'><select id='bg'><option value='premium'>Fondo premium Elegance</option><option value='original'>Conservar fondo</option><option value='transparent'>Transparente</option></select><button onclick='preview()'>Procesar sin guardar</button></div><div class='card'><h2>Aprobar o rechazar</h2><input id='vid' placeholder='ID de versión'><button onclick='decide("approve")'>Aprobar versión</button><button onclick='decide("reject")'>Rechazar versión</button><p class='warn'>Solo aprobar publica los archivos procesados.</p></div></div><div class='card'><pre id='out'>Esperando imagen…</pre></div></div><script>async function preview(){let f=file.files[0];if(!f)return;let d=new FormData();d.append('file',f);d.append('product_id',pid.value);d.append('options_json',JSON.stringify({background:bg.value,removeBackground:bg.value!='original',outputFormat:'webp',quality:88}));let r=await fetch('/api/studio/preview',{method:'POST',body:d});let j=await r.json();out.textContent=JSON.stringify(j,null,2);if(j.versionId)vid.value=j.versionId}async function decide(a){let r=await fetch('/api/studio/decide/'+vid.value,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action:a})});out.textContent=JSON.stringify(await r.json(),null,2)}</script>""")

# Sprint 4 RC1: Commercial automation, stock-safe orders and WhatsApp deep links.
from services.commercial_automation import (
    migrate_commercial, upsert_customer, search_customers, create_order, get_order,
    update_status, add_payment, list_orders, dashboard as commercial_dashboard,
    whatsapp as commercial_whatsapp, receipt as commercial_receipt, audit as commercial_audit
)

@router.post('/api/commercial/migrate')
def commercial_migrate() -> dict: return migrate_commercial()

@router.post('/api/customers')
def commercial_customer_save(payload: dict = Body(...)) -> dict:
    try: return {'status':'ok','customer':upsert_customer(payload)}
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/customers')
def commercial_customer_search(q: str='', limit:int=50) -> dict: return {'status':'ok','customers':search_customers(q,limit)}

@router.post('/api/orders')
def commercial_order_create(payload: dict = Body(...)) -> dict:
    try: return {'status':'ok','order':create_order(payload)}
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/orders')
def commercial_orders(status:str='',customerId:str='',deliveryType:str='',paymentMethod:str='',dateFrom:str='',dateTo:str='',limit:int=100)->dict:
    return {'status':'ok','orders':list_orders(locals())}

@router.get('/api/orders/{order_id}')
def commercial_order_get(order_id:str)->dict:
    try: return {'status':'ok','order':get_order(order_id)}
    except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.post('/api/orders/{order_id}/status')
def commercial_order_status(order_id:str,payload:dict=Body(...))->dict:
    try: return {'status':'ok','order':update_status(order_id,str(payload.get('status','')))}
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.post('/api/orders/{order_id}/payments')
def commercial_payment(order_id:str,payload:dict=Body(...))->dict:
    try: return {'status':'ok','order':add_payment(order_id,payload)}
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/orders/{order_id}/receipt')
def commercial_receipt_endpoint(order_id:str)->dict:
    try: return commercial_receipt(order_id)
    except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.get('/api/orders/{order_id}/whatsapp')
def commercial_whatsapp_endpoint(order_id:str,kind:str='confirmation')->dict:
    try: return commercial_whatsapp(order_id,kind)
    except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.get('/api/commercial/dashboard')
def commercial_dashboard_endpoint()->dict: return commercial_dashboard()

@router.get('/api/commercial/audit')
def commercial_audit_endpoint(limit:int=100)->dict: return {'status':'ok','events':commercial_audit(limit)}

@router.get('/commercial', response_class=HTMLResponse)
def commercial_page()->HTMLResponse:
    return HTMLResponse("""<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{margin:0;background:#02080c;color:#eefaff;font:16px system-ui}.w{max-width:1150px;margin:auto;padding:18px}h1{font:52px cursive;color:#69ddff;margin:0}.grid{display:grid;gap:14px}.card{background:#091620;border:1px solid #2b85aa66;border-radius:22px;padding:17px}input,select,textarea,button{width:100%;box-sizing:border-box;padding:12px;margin:5px 0;border-radius:12px;border:1px solid #287da3;background:#061018;color:white}button{background:#087ea4;font-weight:800}.pill{display:inline-block;padding:7px 11px;background:#102936;border-radius:99px;margin:4px}pre{white-space:pre-wrap;word-break:break-word}@media(min-width:800px){.grid{grid-template-columns:1fr 1fr}}</style><div class='w'><h1>elegance Comercial</h1><p>Clientes, pedidos, apartados, pagos, inventario y WhatsApp sin API de pago.</p><div id='dash' class='card'>Cargando panel…</div><div class='grid'><div class='card'><h2>Cliente</h2><input id='cn' placeholder='Nombre'><input id='cw' placeholder='WhatsApp'><input id='ca' placeholder='Dirección'><button onclick='client()'>Guardar cliente</button></div><div class='card'><h2>Pedido rápido</h2><input id='cid' placeholder='ID cliente'><input id='pid' placeholder='ID producto'><input id='qty' type='number' value='1'><select id='st'><option value='draft'>Borrador</option><option value='pending'>Pendiente</option><option value='layaway'>Apartado</option><option value='paid'>Pagado</option></select><button onclick='order()'>Crear pedido</button></div></div><div class='card'><h2>Resultado</h2><pre id='out'></pre></div></div><script>async function refresh(){let j=await(await fetch('/api/commercial/dashboard')).json();dash.innerHTML=Object.entries(j).filter(x=>typeof x[1]!='object').map(x=>`<span class=pill>${x[0]}: ${x[1]}</span>`).join('')}async function client(){let j=await(await fetch('/api/customers',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:cn.value,whatsapp:cw.value,address:ca.value})})).json();out.textContent=JSON.stringify(j,null,2);if(j.customer)cid.value=j.customer.id}async function order(){let j=await(await fetch('/api/orders',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({customerId:cid.value,status:st.value,items:[{productId:pid.value,quantity:+qty.value}]})})).json();out.textContent=JSON.stringify(j,null,2);refresh()}refresh()</script>""")

# Sprint 4 RC2: public storefront, persistent client cart and stock-safe sales requests.
from pathlib import Path as _Path
from fastapi.responses import FileResponse
from services.cloud_sync import (load_cloud_config, save_cloud_config, ping_cloud, sync_public_products as cloud_sync_products, queue_status as cloud_queue_status, process_queue as cloud_process_queue, retry_failed as cloud_retry_failed, sync_history as cloud_sync_history, list_backups as cloud_list_backups, restore_backup as cloud_restore_backup)
from services.storage_manager import (prepare_product_images as storage_prepare_product, upload_pending as storage_upload_pending, storage_status, safe_to_delete as storage_safe_to_delete, restore_object as storage_restore_object, inventory_cloud as storage_inventory_cloud, cleanup_orphans as storage_cleanup_orphans, history as storage_history)
from services.public_catalog import (
    migrate_public_catalog, sync_products as public_sync_products,
    list_public_products, get_public_product, update_publication, bulk_publish,
    track_event, create_sales_request, get_sales_request, list_requests,
    confirm_request, reject_request, dashboard as public_dashboard
)

@router.post('/api/public/migrate')
def public_catalog_migrate()->dict: return migrate_public_catalog()

@router.post('/api/public/sync')
def public_catalog_sync()->dict: return public_sync_products()

@router.get('/api/public/products')
def public_products(q:str='',category:str='',subcategory:str='',brand:str='',size:str='',color:str='',available:str='',featured:str='')->dict:
    return {'status':'ok','products':list_public_products(locals(),admin=False)}

@router.get('/api/public/products/{identifier}')
def public_product(identifier:str)->dict:
    try: return {'status':'ok','product':get_public_product(identifier)}
    except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.get('/api/admin/publications')
def admin_publications(q:str='',category:str='',brand:str='')->dict:
    return {'status':'ok','products':list_public_products(locals(),admin=True)}

@router.patch('/api/admin/publications/{product_id}')
def admin_publication_update(product_id:str,payload:dict=Body(...))->dict:
    try:
        product=update_publication(product_id,payload)
        cloud=None
        if str(payload.get('status') or '')=='published' and load_cloud_config().get('auto_sync',True):
            storage=storage_prepare_product(product)
            storage_upload=storage_upload_pending(50)
            cloud=cloud_sync_products([product])
        else:
            storage=None; storage_upload=None
        return {'status':'ok','product':product,'cloud':cloud,'storage':storage,'storageUpload':storage_upload}
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.post('/api/admin/publications/bulk')
def admin_publication_bulk(payload:dict=Body(...))->dict:
    try:
        result=bulk_publish(payload.get('productIds') or [],str(payload.get('status') or 'draft'))
        cloud=None
        if str(payload.get('status') or '')=='published' and load_cloud_config().get('auto_sync',True):
            published=[x['product'] for x in result.get('results',[]) if x.get('product') and x['product'].get('status')=='published']
            storage=[]
            for item in published:
                storage.append(storage_prepare_product(item))
            storage_upload=storage_upload_pending(100) if published else {'ok':True,'processed':0}
            cloud=cloud_sync_products(published) if published else {'ok':True,'count':0}
        else:
            storage=[]; storage_upload=None
        result['cloud']=cloud
        result['storage']=storage
        result['storageUpload']=storage_upload
        return result
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc


@router.get('/api/cloud/config')
def cloud_config()->dict:
    cfg=load_cloud_config().copy()
    if cfg.get('sync_key'): cfg['sync_key']='••••••••configurada'
    return {'status':'ok','config':cfg}

@router.put('/api/cloud/config')
def cloud_config_update(payload:dict=Body(...))->dict:
    cfg=save_cloud_config(payload)
    safe=cfg.copy()
    if safe.get('sync_key'): safe['sync_key']='••••••••configurada'
    return {'status':'ok','config':safe}

@router.get('/api/cloud/status')
def cloud_status()->dict:
    return {'status':'ok','cloud':ping_cloud(),'publicUrl':load_cloud_config().get('public_catalog_url')}

@router.post('/api/cloud/sync')
def cloud_sync(payload:dict=Body(default={})) -> dict:
    ids={str(x) for x in (payload.get('productIds') or [])}
    products=list_public_products({},admin=True)
    published=[p for p in products if p.get('status')=='published' and (not ids or str(p.get('id')) in ids)]
    return {'status':'ok','selected':len(published),'cloud':cloud_sync_products(published, force=bool(payload.get('force',False)))}

@router.get('/api/cloud/queue')
def cloud_queue(limit:int=100)->dict:
    return {'status':'ok',**cloud_queue_status(limit)}

@router.post('/api/cloud/queue/process')
def cloud_queue_process(payload:dict=Body(default={}))->dict:
    return {'status':'ok','result':cloud_process_queue(int(payload.get('limit') or 10))}

@router.post('/api/cloud/queue/retry')
def cloud_queue_retry(payload:dict=Body(default={}))->dict:
    return {'status':'ok','result':cloud_retry_failed([str(x) for x in payload.get('queueIds') or []] or None)}

@router.get('/api/cloud/history')
def cloud_history(limit:int=100)->dict:
    return {'status':'ok','events':cloud_sync_history(limit)}

@router.get('/api/cloud/backups')
def cloud_backups(limit:int=30)->dict:
    return {'status':'ok','backups':cloud_list_backups(limit)}

@router.post('/api/cloud/backups/{backup_id}/restore')
def cloud_backup_restore(backup_id:str)->dict:
    try: return {'status':'ok','restore':cloud_restore_backup(backup_id)}
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.post('/api/storage/prepare')
def storage_prepare(payload:dict=Body(...))->dict:
    ids={str(x) for x in payload.get('productIds') or []}
    products=list_public_products({},admin=True)
    selected=[p for p in products if not ids or str(p.get('id')) in ids]
    prepared=[]
    for product in selected: prepared.append(storage_prepare_product(product))
    return {'status':'ok','selected':len(selected),'prepared':prepared}

@router.post('/api/storage/upload')
def storage_upload(payload:dict=Body(default={})) -> dict:
    return {'status':'ok','result':storage_upload_pending(int(payload.get('limit') or 25))}

@router.get('/api/storage/status')
def storage_get_status(limit:int=200)->dict:
    return {'status':'ok',**storage_status(limit)}

@router.get('/api/storage/safe-delete')
def storage_delete_check(product_id:str='',source_path:str='')->dict:
    return {'status':'ok',**storage_safe_to_delete(product_id or None,source_path or None)}

@router.post('/api/storage/restore/{object_id}')
def storage_restore(object_id:str,payload:dict=Body(default={}))->dict:
    try: return {'status':'ok','restore':storage_restore_object(object_id,payload.get('targetFolder'))}
    except (ValueError,RuntimeError) as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/storage/cloud-inventory')
def storage_cloud_inventory()->dict:
    try: return {'status':'ok','inventory':storage_inventory_cloud()}
    except RuntimeError as exc: raise HTTPException(status_code=502,detail=str(exc)) from exc

@router.post('/api/storage/cleanup-orphans')
def storage_orphans_cleanup(payload:dict=Body(default={}))->dict:
    try: return {'status':'ok','result':storage_cleanup_orphans(bool(payload.get('dryRun',True)))}
    except RuntimeError as exc: raise HTTPException(status_code=502,detail=str(exc)) from exc

@router.get('/api/storage/history')
def storage_get_history(limit:int=200)->dict:
    return {'status':'ok','events':storage_history(limit)}

@router.post('/api/public/events')
def public_event(payload:dict=Body(...))->dict:
    try: return track_event(payload)
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.post('/api/public/requests')
def public_request_create(payload:dict=Body(...))->dict:
    try: return {'status':'ok','request':create_sales_request(payload)}
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/public/requests/{identifier}')
def public_request_get(identifier:str)->dict:
    try: return {'status':'ok','request':get_sales_request(identifier)}
    except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.get('/api/admin/requests')
def admin_requests(status:str='',source:str='',limit:int=100)->dict: return {'status':'ok','requests':list_requests(status,source,limit)}

@router.post('/api/admin/requests/{identifier}/confirm')
def admin_request_confirm(identifier:str)->dict:
    try: return confirm_request(identifier)
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.post('/api/admin/requests/{identifier}/reject')
def admin_request_reject(identifier:str)->dict:
    try: return {'status':'ok','request':reject_request(identifier)}
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/public/dashboard')
def public_catalog_dashboard()->dict: return public_dashboard()

@router.get('/catalog',response_class=HTMLResponse)
def public_catalog_page()->HTMLResponse:
    return HTMLResponse(premium_catalog_page())

@router.get('/catalog/product/{slug}',response_class=HTMLResponse)
def public_product_page(slug:str)->HTMLResponse:
    try: p=get_public_product(slug)
    except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    return HTMLResponse(premium_product_page(p))

@router.get('/catalog-admin',response_class=HTMLResponse)
def public_catalog_admin_page()->HTMLResponse:
    return HTMLResponse(premium_catalog_admin_page())

# Sprint 4 RC3: secure publication, users, backups and installable public PWA.
from urllib.parse import quote
from fastapi.responses import RedirectResponse
from services.security_platform import (
    migrate_security, setup_required, create_owner, login as auth_login,
    logout as auth_logout, session_user, change_password, create_user,
    list_users, list_audit as security_audit, backup_database, restore_database,
    list_backups, system_status, has_permission
)

def _token(request: Request)->str:
    return request.cookies.get('elegance_session') or request.headers.get('authorization','').removeprefix('Bearer ').strip()

def _current(request: Request)->dict:
    user=getattr(request.state,'user',None) or session_user(_token(request))
    if not user: raise HTTPException(status_code=401,detail='Autenticación requerida.')
    return user

def _permit(request: Request,module:str)->dict:
    user=_current(request)
    if not has_permission(user,module): raise HTTPException(status_code=403,detail='Tu rol no tiene permiso para esta acción.')
    return user

@router.get('/',response_class=HTMLResponse)
def root_page()->HTMLResponse:
    return HTMLResponse(premium_home_page())

@router.get('/api/auth/status')
def auth_status(request:Request)->dict:
    user=session_user(_token(request))
    return {'status':'ok','setupRequired':setup_required(),'authenticated':bool(user),'user':({'id':user['id'],'username':user['username'],'displayName':user['display_name'],'role':user['role']} if user else None)}


@router.get('/system-check',response_class=HTMLResponse)
def system_check_page_route(request:Request)->HTMLResponse:
    _current(request)
    from services.premium_web import system_check_page
    return HTMLResponse(system_check_page())

@router.get('/api/admin/system-check')
def system_check_api(request:Request)->dict:
    _current(request)
    from services.system_check import system_check
    return system_check()

@router.get('/setup',response_class=HTMLResponse)
def setup_page()->HTMLResponse:
    if not setup_required(): return RedirectResponse('/login',303)
    return HTMLResponse(premium_setup_page())

@router.post('/api/auth/setup')
def auth_setup(payload:dict=Body(...))->dict:
    try:return {'status':'ok','user':create_owner(str(payload.get('username','')),str(payload.get('password','')),str(payload.get('displayName','Propietario')))}
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/login',response_class=HTMLResponse)
def login_page(next:str='/admin')->HTMLResponse:
    if setup_required(): return RedirectResponse('/setup',303)
    safe=next if next.startswith('/') and not next.startswith('//') else '/admin'
    return HTMLResponse(premium_login_page(safe))

@router.post('/api/auth/login')
def auth_login_endpoint(request:Request,payload:dict=Body(...))->Response:
    try:r=auth_login(str(payload.get('username','')),str(payload.get('password','')),request.client.host if request.client else '',request.headers.get('user-agent',''))
    except ValueError as exc:raise HTTPException(status_code=401,detail=str(exc)) from exc
    response=JSONResponse({'status':'ok','user':r['user'],'expiresAt':r['expiresAt']})
    response.set_cookie('elegance_session',r['token'],max_age=8*3600,httponly=True,samesite='lax',secure=__import__('os').getenv('ELEGANCE_ENV')=='production',path='/')
    return response

@router.post('/api/auth/logout')
def auth_logout_endpoint(request:Request)->Response:
    user=session_user(_token(request));auth_logout(_token(request),user)
    response=JSONResponse({'status':'ok'});response.delete_cookie('elegance_session',path='/');return response

@router.post('/api/auth/change-password')
def auth_change_password(request:Request,payload:dict=Body(...))->dict:
    try:change_password(_current(request),str(payload.get('currentPassword','')),str(payload.get('newPassword','')))
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc
    return {'status':'ok','reauthenticationRequired':True}

@router.get('/api/admin/users')
def auth_users(request:Request)->dict:
    _permit(request,'users');return {'status':'ok','users':list_users()}

@router.post('/api/admin/users')
def auth_user_create(request:Request,payload:dict=Body(...))->dict:
    try:return {'status':'ok','user':create_user(payload,_permit(request,'users'))}
    except (ValueError,PermissionError) as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/admin/security/audit')
def auth_audit_endpoint(request:Request,limit:int=100)->dict:
    _permit(request,'users');return {'status':'ok','events':security_audit(limit)}

@router.post('/api/admin/backups')
def backup_create_endpoint(request:Request)->dict:
    _permit(request,'backups');return backup_database('manual')

@router.get('/api/admin/backups')
def backup_list_endpoint(request:Request)->dict:
    _permit(request,'backups');return {'status':'ok','backups':list_backups()}

@router.post('/api/admin/backups/{name}/restore')
def backup_restore_endpoint(name:str,request:Request,payload:dict=Body(...))->dict:
    _permit(request,'backups')
    try:return restore_database(name,bool(payload.get('confirm')))
    except (ValueError,RuntimeError) as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/system/status')
def system_status_endpoint()->dict:return system_status()

from services.database_diagnostics import database_diagnostics, database_fingerprint

@router.get('/api/admin/database/diagnostics')
def database_diagnostics_endpoint(request:Request)->dict:
    _permit(request,'backups')
    return database_diagnostics()

@router.get('/api/admin/database/fingerprint')
def database_fingerprint_endpoint(request:Request)->dict:
    _permit(request,'backups')
    return {'status':'ok', **database_fingerprint()}

@router.get('/admin',response_class=HTMLResponse)
def admin_home(request:Request)->HTMLResponse:
    return HTMLResponse(premium_admin_page(_current(request)))

@router.get('/database-diagnostics',response_class=HTMLResponse)
def database_diagnostics_page(request:Request)->HTMLResponse:
    _permit(request,'backups')
    return HTMLResponse((__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'database-diagnostics.html').read_text(encoding='utf-8'))


@router.get('/robots.txt')
def robots_txt()->Response:
    return Response('User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/admin\nDisallow: /commercial\nDisallow: /studio\nDisallow: /ai\nSitemap: /sitemap.xml\n', media_type='text/plain')

@router.get('/sitemap.xml')
def sitemap_xml(request:Request)->Response:
    base=str(request.base_url).rstrip('/')
    urls=[base+'/',base+'/catalog']+[base+'/catalog/product/'+p['slug'] for p in list_public_products({},admin=False)]
    xml='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>{u}</loc></url>' for u in urls)+'</urlset>'
    return Response(xml,media_type='application/xml')

@router.get('/system-status',response_class=HTMLResponse)
def system_status_page()->HTMLResponse:
    return HTMLResponse("""<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><link rel=stylesheet href='/assets/web/elegance.css'><body class=error-page><main><div class=brand><span>elegance</span><small>ESTADO</small></div><h1>Sistema operativo</h1><p id=s>Comprobando servicios…</p><a class='btn primary' href='/catalog'>Abrir catálogo</a><script>fetch('/api/system/status').then(r=>r.json()).then(j=>s.textContent=j.status==='ok'?'Todos los servicios esenciales están disponibles.':'El sistema requiere atención.').catch(()=>s.textContent='No fue posible consultar el estado.')</script></main>""")

@router.get('/manifest.webmanifest')
def pwa_manifest()->JSONResponse:
    return JSONResponse({'name':'Elegance — Catálogo Premium','short_name':'Elegance','description':'Catálogo premium de Elegance','start_url':'/catalog?source=pwa','scope':'/','display':'standalone','orientation':'portrait-primary','background_color':'#02070b','theme_color':'#07131b','categories':['shopping','lifestyle'],'icons':[{'src':'/pwa-icon.svg','sizes':'any','type':'image/svg+xml','purpose':'any maskable'}]},media_type='application/manifest+json')

@router.get('/pwa-icon.svg')
def pwa_icon()->Response:
    return Response("""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512'><rect width='512' height='512' rx='110' fill='#02070b'/><circle cx='256' cy='256' r='190' fill='none' stroke='#6ee4ff' stroke-width='14'/><text x='256' y='305' text-anchor='middle' font-size='245' font-family='serif' fill='#6ee4ff'>E</text></svg>""",media_type='image/svg+xml')

@router.get('/offline',response_class=HTMLResponse)
def offline_page()->HTMLResponse:return HTMLResponse("""<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><style>body{background:#02070b;color:white;font:18px system-ui;display:grid;place-items:center;min-height:100vh;text-align:center}h1{font:55px cursive;color:#6ee4ff}</style><main><h1>elegance</h1><h2>Sin conexión</h2><p>Tu carrito sigue guardado. Se sincronizará cuando vuelva internet.</p><button onclick=location.reload()>Reintentar</button></main>""")

@router.get('/sw.js')
def pwa_sw()->Response:
    script="""const CACHE='elegance-s5rc1-v1',CORE=['/','/catalog','/offline','/manifest.webmanifest','/pwa-icon.svg','/assets/web/elegance.css','/assets/web/elegance.js'];self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(CORE)).then(()=>self.skipWaiting())));self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(xs=>Promise.all(xs.filter(x=>x!==CACHE).map(x=>caches.delete(x)))).then(()=>self.clients.claim())));self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;e.respondWith(fetch(e.request).then(r=>{let copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy));return r}).catch(()=>caches.match(e.request).then(r=>r||caches.match('/offline'))))});"""
    return Response(script,media_type='application/javascript',headers={'Service-Worker-Allowed':'/'})

# Sprint 6 RC1: flujo operativo unificado de producto, inventario y exportación.
from fastapi.responses import FileResponse
from services.product_workflow import (
    migrate_sprint6, analyze_uploads as s6_analyze_uploads, create_product as s6_create_product,
    list_inventory as s6_list_inventory, adjust_stock as s6_adjust_stock,
    movements as s6_movements, exports_zip as s6_exports_zip
)

@router.get('/new-product', response_class=HTMLResponse)
def sprint6_new_product_page()->HTMLResponse:
    return HTMLResponse((__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'new-product.html').read_text(encoding='utf-8'))

@router.post('/api/products/analyze')
async def sprint6_analyze(files: Annotated[list[UploadFile], File(...)])->dict:
    import io
    payload=[]
    for f in files:
        payload.append((f.filename or 'producto.jpg',await f.read()))
    fallback=s6_analyze_uploads(payload)
    try:
        visual_files=[UploadFile(filename=name,file=io.BytesIO(data)) for name,data in payload]
        visual=await analyzer.analyze(visual_files,eps=0.075,min_samples=1)
        dump=visual.model_dump() if hasattr(visual,'model_dump') else visual.dict()
        groups=dump.get('groups') or []
        if groups:
            first=groups[0]
            brand=str(first.get('brand') or '').strip()
            model=str(first.get('model_family') or '').strip()
            if brand in {'Sin identificar','Unknown'}: brand=''
            suggestion={
                'brand':brand,
                'model':model,
                'category':'Tenis' if str(first.get('shoe_type') or '').lower() not in {'boot','bota'} else 'Calzado',
                'color':str(first.get('dominant_color') or ''),
                'type':str(first.get('shoe_type') or 'Tenis'),
                'title':str(first.get('suggested_title') or ''),
                'confidence':round((float(first.get('brand_confidence') or 0)+float(first.get('model_confidence') or 0))/2,4),
                'brandConfidence':float(first.get('brand_confidence') or 0),
                'modelConfidence':float(first.get('model_confidence') or 0),
                'needsReview':bool(first.get('needs_manual_review',True)),
                'method':str(first.get('identification_method') or 'visual-local'),
                'evidence':first.get('identification_evidence') or [],
            }
            fallback.update({'suggestion':suggestion,'visualAnalysis':dump,'groups':groups,'classification':'grouped' if len(groups)>1 else fallback.get('classification','new')})
        else:
            fallback['visualWarning']='No se detectaron grupos visuales.'
    except Exception as exc:
        fallback['visualWarning']=f'Reconocimiento visual opcional no disponible: {exc}'
        fallback['suggestion']['model']=''
        fallback['suggestion']['brand']=''
        fallback['suggestion']['confidence']=0.0
        fallback['suggestion']['method']='pendiente de modelo visual local'
    try:
        text_payload={
            'title':fallback.get('suggestion',{}).get('title',''),
            'brand':fallback.get('suggestion',{}).get('brand',''),
            'model':fallback.get('suggestion',{}).get('model',''),
            'description':' '.join(str(x.get('suggested_title','')) for x in fallback.get('groups',[]) if isinstance(x,dict))
        }
        universal=universal_classify(text_payload)
        fallback['universal']=universal
        # Universal taxonomy is authoritative for category routing when evidence exists.
        if universal.get('evidence'):
            fallback['suggestion']['category']=universal.get('category','Otros')
            fallback['suggestion']['subcategory']=universal.get('subcategory','')
        fallback['suggestion']['requiredFields']=universal.get('requiredFields',[])
        fallback['suggestion']['catalogPath']=universal.get('catalogPath','')
        fallback['suggestion']['needsReview']=bool(fallback['suggestion'].get('needsReview') or universal.get('needsReview'))
    except Exception as exc:
        fallback['universalWarning']=str(exc)
    return fallback

@router.post('/api/products/create')
async def sprint6_create(
    files: Annotated[list[UploadFile], File(...)],
    payload_json: Annotated[str, Form()]='{}',
    edited_files: Annotated[list[UploadFile] | None, File()] = None
)->dict:
    try:
        payload=json.loads(payload_json or '{}')
        incoming=[]
        for f in files: incoming.append((f.filename or 'producto.jpg',await f.read()))
        edited=[]
        for index,f in enumerate(edited_files or []): edited.append((f.filename or str(index),await f.read()))
        return s6_create_product(payload,incoming,edited)
    except (ValueError,json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/inventory', response_class=HTMLResponse)
def sprint6_inventory_page()->HTMLResponse:
    return HTMLResponse((__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'inventory.html').read_text(encoding='utf-8'))

@router.get('/api/inventory/products')
def sprint6_inventory_products()->dict:
    return {'status':'ok','products':s6_list_inventory()}

@router.post('/api/inventory/adjust')
def sprint6_inventory_adjust(payload:dict=Body(...))->dict:
    try:return s6_adjust_stock(str(payload.get('productId','')),str(payload.get('variantId','')),int(payload.get('quantity') or 0),str(payload.get('note') or ''))
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/inventory/movements')
def sprint6_inventory_movements(limit:int=200)->dict:
    return {'status':'ok','movements':s6_movements(limit)}

@router.get('/mobile-center', response_class=HTMLResponse)
def mobile_center_page()->HTMLResponse:
    return HTMLResponse((__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'mobile-center.html').read_text(encoding='utf-8'))

@router.get('/mobile-manifest.webmanifest')
def mobile_manifest()->JSONResponse:
    return JSONResponse({"name":"Elegance Centro de Operaciones","short_name":"Elegance","start_url":"/mobile-center","display":"standalone","background_color":"#05070a","theme_color":"#9de9ff","icons":[]}, media_type='application/manifest+json')

@router.get('/server-status', response_class=HTMLResponse)
def home_server_status_page()->HTMLResponse:
    return HTMLResponse((__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'server-status.html').read_text(encoding='utf-8'))

@router.get('/backups', response_class=HTMLResponse)
def sprint6_backups_page()->HTMLResponse:
    return HTMLResponse((__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'backups.html').read_text(encoding='utf-8'))


from services.full_backup import create_full_backup, list_full_backups, restore_full_backup

@router.post('/api/admin/full-backups')
def full_backup_create(request:Request)->dict:
    _permit(request,'backups');return create_full_backup('manual')

@router.get('/api/admin/full-backups')
def full_backup_list(request:Request)->dict:
    _permit(request,'backups');return {'status':'ok','backups':list_full_backups()}

@router.post('/api/admin/full-backups/{name}/restore')
def full_backup_restore(name:str,request:Request,payload:dict=Body(...))->dict:
    _permit(request,'backups')
    try:return restore_full_backup(name,bool(payload.get('confirm')))
    except (ValueError,RuntimeError) as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/admin/export')
def sprint6_export(request:Request)->FileResponse:
    _permit(request,'backups');path=s6_exports_zip();return FileResponse(path,filename=path.name,media_type='application/zip')


@router.get('/product-reviews', response_class=HTMLResponse)
def universal_reviews_page()->HTMLResponse:
    return HTMLResponse((__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'product-reviews.html').read_text(encoding='utf-8'))

@router.get("/api/universal/taxonomy")
def universal_taxonomy(): return {"status":"ok",**taxonomy_payload()}
@router.get("/api/automation/settings")
def get_automation_settings(): return {"status":"ok","settings":automation_settings()}
@router.put("/api/automation/settings")
def put_automation_settings(payload:dict=Body(...)):
    try:return {"status":"ok","settings":set_automation_settings(payload)}
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc))
@router.post("/api/universal/classify")
def classify_universal_product(payload:dict=Body(...)):return {"status":"ok",**universal_classify(payload)}
@router.post("/api/universal/reviews")
def create_universal_review(payload:dict=Body(...)):return queue_review(payload)
@router.get("/api/universal/reviews")
def get_universal_reviews(status:str="pending",limit:int=100):return {"status":"ok","reviews":list_reviews(status,limit)}

@router.get("/api/universal/reviews/{review_id}")
def get_universal_review_detail(review_id:str):
    try:return {"status":"ok","review":review_detail(review_id)}
    except KeyError as exc:raise HTTPException(status_code=404,detail=str(exc))

@router.put("/api/universal/reviews/{review_id}/draft")
def save_universal_review_draft(review_id:str,payload:dict=Body(...)):
    try:return save_review_draft(review_id,payload,False)
    except (KeyError,ValueError) as exc:raise HTTPException(status_code=400,detail=str(exc))

@router.post("/api/universal/reviews/{review_id}/publish")
def publish_universal_review(review_id:str,payload:dict=Body(...)):
    try:return save_review_draft(review_id,payload,True)
    except (KeyError,ValueError) as exc:raise HTTPException(status_code=400,detail=str(exc))

@router.post("/api/universal/reviews/{review_id}/cover")
def cover_universal_review(review_id:str,payload:dict=Body(...)):
    try:return set_review_cover(review_id,str(payload.get("image") or ""))
    except (KeyError,ValueError) as exc:raise HTTPException(status_code=400,detail=str(exc))

@router.delete("/api/universal/reviews/{review_id}/images")
def delete_universal_review_image(review_id:str,image:str=Query(...)):
    try:return remove_review_image(review_id,image)
    except (KeyError,ValueError) as exc:raise HTTPException(status_code=400,detail=str(exc))
@router.post("/api/universal/reviews/{review_id}/resolve")
def resolve_universal_review(review_id:str,payload:dict=Body(...)):
    try:return resolve_review(review_id,payload)
    except KeyError as exc:raise HTTPException(status_code=404,detail=str(exc))
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc))



@router.get("/intelligence", response_class=HTMLResponse)
def intelligence_page()->HTMLResponse:
    return HTMLResponse((__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'intelligence.html').read_text(encoding='utf-8'))

@router.get("/api/intelligence/settings")
def get_intelligence_settings(): return {"status":"ok","settings":intelligence_settings()}

@router.put("/api/intelligence/settings")
def put_intelligence_settings(payload:dict=Body(...)):
    try:return {"status":"ok","settings":update_intelligence_settings(payload)}
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc))

@router.post("/api/intelligence/products/{product_id}/analyze")
def analyze_intelligence_product(product_id:str,payload:dict=Body(default={})):
    try:return intelligence_analyze(product_id,str(payload.get('reviewId') or ''),bool(payload.get('forceWeb',False)))
    except KeyError as exc:raise HTTPException(status_code=404,detail=str(exc))

@router.get("/api/intelligence/products/{product_id}/decisions")
def get_intelligence_decisions(product_id:str,limit:int=50):return {"status":"ok","decisions":intelligence_decisions(product_id,limit)}


@router.get("/api/euiv/products/{product_id}/candidates")
def get_euiv_candidates(product_id:str,limit:int=20):
    return {"status":"ok","candidates":euiv_list_candidates(product_id,limit)}

@router.post("/api/euiv/candidates/{candidate_id}/accept")
def accept_euiv_candidate(candidate_id:str,payload:dict=Body(default={})):
    try:
        item=euiv_accept_candidate(candidate_id)
        pid=item['product_id']; product=next((p for p in load_state().get('products',[]) if str(p.get('id'))==str(pid)),None)
        if not product: raise KeyError('Producto no encontrado.')
        snapshot_product(pid,'Antes de aceptar coincidencia EUIV','euiv')
        for src,dst in [('name','title'),('brand','brand'),('model','model'),('category','category'),('subcategory','subcategory'),('description','description')]:
            if item.get(src): product[dst]=item[src]
        state=load_state(); products=state.get('products',[]); idx=next(i for i,p in enumerate(products) if str(p.get('id'))==str(pid)); products[idx]=product; save_state(state)
        attrs={}
        if item.get('colors'): attrs['color']=item['colors']
        if item.get('sku'): attrs['sku']=item['sku']
        if attrs: save_product_attributes(pid,attrs,'euiv-candidate')
        return {"status":"ok","candidate":item,"product":product,"attributes":attrs}
    except Exception as exc: raise HTTPException(400,str(exc))


# Elegance Platform 2.2 RC1: biblioteca permanente y centro de publicación.
from services.media_library import list_assets as library_media_list_assets, archive_asset as media_archive_asset, settings as publication_settings, update_settings as update_publication_settings, backfill_state_assets

@router.get('/media-library', response_class=HTMLResponse)
def media_library_page()->HTMLResponse:
    return HTMLResponse((__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'media-library.html').read_text(encoding='utf-8'))

@router.get('/publication-center', response_class=HTMLResponse)
def publication_center_page()->HTMLResponse:
    return HTMLResponse((__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'publication-center.html').read_text(encoding='utf-8'))

@router.get('/api/media/assets')
def api_media_assets(status:str='active',product_id:str='',limit:int=500)->dict:
    return {'status':'ok','assets':library_media_list_assets(status,product_id,limit)}

@router.post('/api/media/assets/{asset_id}/status')
def api_media_asset_status(asset_id:str,payload:dict=Body(...))->dict:
    try:return media_archive_asset(asset_id,str(payload.get('status') or 'archived'))
    except (KeyError,ValueError) as exc:raise HTTPException(status_code=400,detail=str(exc))

@router.post('/api/media/backfill')
def api_media_backfill()->dict:
    return {'status':'ok',**backfill_state_assets(load_state())}

@router.get('/api/publication/settings')
def api_publication_settings()->dict:return {'status':'ok','settings':publication_settings()}

@router.put('/api/publication/settings')
def api_publication_settings_update(payload:dict=Body(...))->dict:return {'status':'ok','settings':update_publication_settings(payload)}

@router.post('/api/publication/sync-all')
def api_publication_sync_all()->dict:
    from services.public_catalog import sync_products, list_public_products
    result=sync_products()
    published_products=list_public_products({},admin=False)
    cloud=cloud_sync_products(published_products)
    return {'status':'ok','sync':result,'cloud':cloud,'published':len(published_products),'adminProducts':len(list_public_products({},admin=True))}

@router.post("/api/visual-search/products/{product_id}/sessions")
def create_visual_search_session(product_id:str,payload:dict=Body(default={})):
    image_ref=str(payload.get('image_ref') or '')
    if not image_ref: raise HTTPException(400,'Selecciona una fotografía antes de abrir Google Lens.')
    return {"status":"ok","session":visual_search_create(product_id,str(payload.get('review_id') or ''),image_ref),"lens_url":"https://lens.google.com/"}

@router.post("/api/visual-search/sessions/{session_id}/register")
def register_visual_search_result(session_id:str,payload:dict=Body(...)):
    try:return {"status":"ok",**visual_search_register(session_id,payload)}
    except KeyError as exc:raise HTTPException(404,str(exc))

@router.post("/api/visual-search/sessions/{session_id}/apply")
def apply_visual_search_result(session_id:str,payload:dict=Body(...)):
    # Applying remains explicit in the review UI; this endpoint records the confirmed evidence.
    visual_search_mark_applied(session_id)
    return {"status":"ok","applied":payload}

@router.get("/api/intelligence/products/{product_id}/versions")
def get_intelligence_versions(product_id:str,limit:int=50):return {"status":"ok","versions":intelligence_versions(product_id,limit)}

@router.post("/api/intelligence/versions/{version_id}/restore")
def restore_intelligence_version(version_id:str,request:Request):
    try:return intelligence_restore(version_id,getattr(request.state,'user',{}).get('name','') if isinstance(getattr(request.state,'user',{}),dict) else '')
    except KeyError as exc:raise HTTPException(status_code=404,detail=str(exc))

# Elegance Platform 2.0 RC3: persistent, recoverable batch automation.
from services.batch_automation import create_job as create_automation_job, get_job as get_automation_job, list_jobs as list_automation_jobs, cancel_job as cancel_automation_job, retry_job as retry_automation_job, move_file as move_automation_file, merge_groups as merge_automation_groups, split_group as split_automation_group, set_cover as set_automation_cover, delete_file as delete_automation_file, update_group as update_automation_group

@router.post('/api/automation/batches')
async def automation_batch_create(files: Annotated[list[UploadFile], File(...)], options_json: Annotated[str, Form()]='{}') -> dict:
    try:
        options=json.loads(options_json or '{}')
        loaded=[]
        for f in files:
            loaded.append((f.filename or 'imagen.jpg', await f.read()))
        return create_automation_job(loaded,options)
    except (ValueError,json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/automation/batches')
def automation_batch_list(limit:int=30) -> dict:
    return {'status':'ok','jobs':list_automation_jobs(limit)}

@router.get('/api/automation/batches/{job_id}')
def automation_batch_status(job_id:str) -> dict:
    try:return {'status':'ok','job':get_automation_job(job_id)}
    except KeyError as exc:raise HTTPException(status_code=404,detail='Lote no encontrado.') from exc

@router.post('/api/automation/batches/{job_id}/cancel')
def automation_batch_cancel(job_id:str) -> dict:
    try:return cancel_automation_job(job_id)
    except KeyError as exc:raise HTTPException(status_code=404,detail='Lote no encontrado.') from exc

@router.post('/api/automation/batches/{job_id}/retry')
def automation_batch_retry(job_id:str) -> dict:
    try:return retry_automation_job(job_id)
    except KeyError as exc:raise HTTPException(status_code=404,detail='Lote no encontrado.') from exc


@router.post('/api/automation/batches/{job_id}/files/{file_id}/move')
def automation_file_move(job_id:str,file_id:str,payload:dict=Body(...))->dict:
    try:return {'status':'ok','job':move_automation_file(job_id,file_id,int(payload.get('targetGroup') or 0))}
    except (ValueError,KeyError) as exc:raise HTTPException(status_code=400,detail=str(exc))

@router.post('/api/automation/batches/{job_id}/groups/merge')
def automation_groups_merge(job_id:str,payload:dict=Body(...))->dict:
    try:return {'status':'ok','job':merge_automation_groups(job_id,payload.get('groups') or [],payload.get('targetGroup'))}
    except (ValueError,KeyError) as exc:raise HTTPException(status_code=400,detail=str(exc))

@router.post('/api/automation/batches/{job_id}/groups/split')
def automation_group_split(job_id:str,payload:dict=Body(...))->dict:
    try:return {'status':'ok','job':split_automation_group(job_id,payload.get('fileIds') or [])}
    except (ValueError,KeyError) as exc:raise HTTPException(status_code=400,detail=str(exc))

@router.put('/api/automation/batches/{job_id}/groups/{group_no}')
def automation_group_update(job_id:str,group_no:int,payload:dict=Body(...))->dict:
    try:return {'status':'ok','job':update_automation_group(job_id,group_no,payload)}
    except (ValueError,KeyError) as exc:raise HTTPException(status_code=400,detail=str(exc))

@router.post('/api/automation/batches/{job_id}/groups/{group_no}/cover')
def automation_group_cover(job_id:str,group_no:int,payload:dict=Body(...))->dict:
    try:return {'status':'ok','job':set_automation_cover(job_id,group_no,str(payload.get('fileId') or ''))}
    except (ValueError,KeyError) as exc:raise HTTPException(status_code=400,detail=str(exc))

@router.delete('/api/automation/batches/{job_id}/files/{file_id}')
def automation_file_delete(job_id:str,file_id:str)->dict:
    try:return {'status':'ok','job':delete_automation_file(job_id,file_id)}
    except (ValueError,KeyError) as exc:raise HTTPException(status_code=400,detail=str(exc))

@router.get('/automation', response_class=HTMLResponse)
def automation_page() -> HTMLResponse:
    return HTMLResponse((__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'automation.html').read_text(encoding='utf-8'))


# Cloud 1.3: Clientes, Pedidos, Ventas, Envíos, Notificaciones y Analítica
from services.sales_manager import (
    migrate_sales_manager, save_shipment, get_shipment, list_shipments,
    create_notification, get_notification, list_notifications,
    advanced_search, statistics as sales_statistics, report_csv,
    sync_queue as sales_sync_queue, record_status_history, queue_sync
)

@router.post('/api/cloud13/migrate')
def cloud13_migrate() -> dict:
    return migrate_sales_manager()

@router.post('/api/shipments')
def shipment_save(payload: dict = Body(...)) -> dict:
    try:
        return {'status':'ok','shipment':save_shipment(str(payload.get('orderId') or ''),payload)}
    except ValueError as exc:
        raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/shipments')
def shipments_list(status: str='', q: str='', limit: int=100) -> dict:
    return {'status':'ok','shipments':list_shipments(status,q,limit)}

@router.get('/api/shipments/{shipment_id}')
def shipment_get(shipment_id: str) -> dict:
    try: return {'status':'ok','shipment':get_shipment(shipment_id)}
    except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.post('/api/notifications')
def notification_create(payload: dict = Body(...)) -> dict:
    try: return {'status':'ok','notification':create_notification(payload)}
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/notifications')
def notifications_list(status: str='', limit: int=100) -> dict:
    return {'status':'ok','notifications':list_notifications(status,limit)}

@router.get('/api/notifications/{notification_id}')
def notification_get(notification_id: str) -> dict:
    try: return {'status':'ok','notification':get_notification(notification_id)}
    except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.get('/api/commercial/search')
def commercial_advanced_search(q: str='', status: str='', dateFrom: str='', dateTo: str='', limit: int=100) -> dict:
    return advanced_search(q,status,dateFrom,dateTo,limit)

@router.get('/api/commercial/statistics')
def commercial_statistics(days: int=30) -> dict:
    return sales_statistics(days)

@router.get('/api/commercial/reports/{kind}.csv')
def commercial_report(kind: str, days: int=30) -> Response:
    if kind not in {'sales','products','customers'}:
        raise HTTPException(status_code=400,detail='Reporte inválido.')
    return Response(report_csv(kind,days),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename=elegance_{kind}_{days}d.csv'})

@router.get('/api/commercial/sync-queue')
def commercial_sync_queue(status: str='', limit: int=100) -> dict:
    return {'status':'ok','queue':sales_sync_queue(status,limit)}

@router.post('/api/orders/{order_id}/status-tracked')
def commercial_order_status_tracked(order_id: str,payload:dict=Body(...))->dict:
    try:
        old=get_order(order_id)['status']; new=str(payload.get('status') or '')
        updated=update_status(order_id,new)
        record_status_history(updated['id'],old,new,str(payload.get('note') or ''))
        queue_sync('order',updated['id'],'upsert',updated)
        return {'status':'ok','order':updated}
    except ValueError as exc:
        raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/commercial-cloud')
def commercial_cloud_page()->HTMLResponse:
    return HTMLResponse("""<!doctype html><html lang='es'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Elegance Cloud 1.3</title><style>body{margin:0;background:#02090e;color:#edfaff;font:15px system-ui}.w{max-width:1200px;margin:auto;padding:22px}h1{font:48px cursive;color:#7de6ff}.g{display:grid;gap:14px}.c{background:#071823;border:1px solid #276f8e;border-radius:20px;padding:16px}.k{font-size:28px;font-weight:800}input,select,button{padding:11px;border-radius:11px;border:1px solid #2b7898;background:#06121a;color:white}button{background:#087da6;font-weight:800}@media(min-width:800px){.g{grid-template-columns:repeat(3,1fr)}}</style><div class='w'><h1>elegance Cloud 1.3</h1><p>Clientes · Pedidos · Ventas · Apartados · Envíos · Reportes · Trazabilidad</p><div id='cards' class='g'></div><div class='c' style='margin-top:14px'><h2>Búsqueda avanzada</h2><input id='q' placeholder='Folio, cliente, WhatsApp, producto o guía'><button onclick='search()'>Buscar</button><pre id='out'></pre></div></div><script>async function load(){let j=await(await fetch('/api/commercial/statistics?days=30')).json();cards.innerHTML=`<div class=c><div class=k>${j.salesCount||0}</div>ventas 30 días</div><div class=c><div class=k>$${Number(j.revenue||0).toLocaleString()}</div>ingresos</div><div class=c><div class=k>$${Number(j.averageTicket||0).toLocaleString()}</div>ticket promedio</div>`}async function search(){let j=await(await fetch('/api/commercial/search?q='+encodeURIComponent(q.value))).json();out.textContent=JSON.stringify(j,null,2)}load()</script></html>""")

# Cloud 1.4: unified responsive administrative panel.
from services.admin_dashboard import executive_dashboard, global_search

@router.get('/api/admin/dashboard')
def cloud14_dashboard(request: Request, days: int=30) -> dict:
    _permit(request,'dashboard')
    return executive_dashboard(days)

@router.get('/api/admin/search')
def cloud14_search(request: Request, q: str='', limit: int=40) -> dict:
    _permit(request,'dashboard')
    return global_search(q,limit)

@router.get('/cloud-admin', response_class=HTMLResponse)
def cloud14_admin_page(request: Request) -> HTMLResponse:
    _permit(request,'dashboard')
    page=(__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'cloud-admin.html')
    return HTMLResponse(page.read_text(encoding='utf-8'))


@router.get("/api/ai-enterprise/analyze/{product_id}")
def ai_enterprise_analyze_route(product_id: str) -> dict:
    try: return ai_enterprise_analyze(product_id)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc))

@router.post("/api/ai-enterprise/batch")
def ai_enterprise_batch_route(payload: dict = Body(default={})) -> dict:
    return ai_batch_analyze(int(payload.get("limit",100)))

@router.get("/api/ai-enterprise/duplicates")
def ai_enterprise_duplicates_route(max_distance: int = Query(6, ge=0, le=16)) -> dict:
    return ai_duplicate_scan(max_distance)

@router.get("/api/ai-enterprise/fingerprint/{product_id}")
def ai_enterprise_fingerprint_route(product_id: str) -> dict:
    return ai_image_fingerprint(product_id)

@router.get("/api/ai-enterprise/price/{product_id}")
def ai_enterprise_price_route(product_id: str) -> dict:
    return ai_suggest_price(product_id)

@router.post("/api/ai-enterprise/process-image/{product_id}")
def ai_enterprise_process_route(product_id: str, payload: dict = Body(default={})) -> dict:
    try:
        return ai_process_image(product_id, bool(payload.get("removeBackground",False)), payload.get("scenarioPath"))
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc))

@router.get("/ai-enterprise", response_class=HTMLResponse)
def ai_enterprise_page() -> HTMLResponse:
    page=(__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'ai-enterprise.html')
    return HTMLResponse(page.read_text(encoding='utf-8'))


# Cloud 2.0: Elegance Brain Enterprise modular core.
from services.elegance_brain import (migrate_brain,upsert_supplier,list_suppliers,create_purchase,get_purchase,add_cash_movement,finance_summary,open_conversation,queue_message,upsert_rule,run_event,predictive_analytics,brain_dashboard,integrity_report)

@router.post('/api/brain/migrate')
def brain_migrate(): return migrate_brain()

@router.get('/api/brain/dashboard')
def brain_dashboard_route(days:int=30): return brain_dashboard(days)

@router.get('/api/brain/integrity')
def brain_integrity_route(): return integrity_report()

@router.post('/api/brain/suppliers')
def brain_supplier_save(payload:dict=Body(...)):
    try:return {'status':'ok','supplier':upsert_supplier(payload)}
    except ValueError as exc:raise HTTPException(400,str(exc))

@router.get('/api/brain/suppliers')
def brain_supplier_list(q:str='',limit:int=100): return {'status':'ok','suppliers':list_suppliers(q,limit)}

@router.post('/api/brain/purchases')
def brain_purchase_create(payload:dict=Body(...)):
    try:return {'status':'ok','purchase':create_purchase(payload)}
    except ValueError as exc:raise HTTPException(400,str(exc))

@router.get('/api/brain/purchases/{purchase_id}')
def brain_purchase_get(purchase_id:str):
    try:return {'status':'ok','purchase':get_purchase(purchase_id)}
    except ValueError as exc:raise HTTPException(404,str(exc))

@router.post('/api/brain/finance/movements')
def brain_finance_movement(payload:dict=Body(...)):
    try:return {'status':'ok','movement':add_cash_movement(payload)}
    except ValueError as exc:raise HTTPException(400,str(exc))

@router.get('/api/brain/finance/summary')
def brain_finance_summary(days:int=30): return finance_summary(days)

@router.post('/api/brain/whatsapp/conversations')
def brain_whatsapp_open(payload:dict=Body(...)):
    try:return {'status':'ok','conversation':open_conversation(payload)}
    except ValueError as exc:raise HTTPException(400,str(exc))

@router.post('/api/brain/whatsapp/conversations/{conversation_id}/messages')
def brain_whatsapp_message(conversation_id:str,payload:dict=Body(...)):
    try:return {'status':'ok','message':queue_message(conversation_id,payload)}
    except ValueError as exc:raise HTTPException(400,str(exc))

@router.post('/api/brain/automation/rules')
def brain_rule_save(payload:dict=Body(...)):
    try:return {'status':'ok','rule':upsert_rule(payload)}
    except ValueError as exc:raise HTTPException(400,str(exc))

@router.post('/api/brain/automation/events/{event_name}')
def brain_event_run(event_name:str,payload:dict=Body(default={})): return run_event(event_name,payload)

@router.get('/api/brain/analytics/predictive')
def brain_predictive(days:int=90): return predictive_analytics(days)

@router.get('/brain',response_class=HTMLResponse)
def brain_page():
    page=(__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'brain.html')
    return HTMLResponse(page.read_text(encoding='utf-8'))

# Bloque 5 RC2: catálogo administrativo CRUD, filtros y deduplicación.
from services.catalog_crud import (
    create_product as catalog_create_product, get_product as catalog_get_product,
    update_product as catalog_update_product, delete_product as catalog_delete_product,
    list_products as catalog_list_products, duplicate_report as catalog_duplicate_report,
)

@router.get('/api/admin/catalog/products')
def block5_catalog_products(q:str='',category:str='',brand:str='',status:str='',size:str='',color:str='')->dict:
    return {'status':'ok', **catalog_list_products(locals())}

@router.post('/api/admin/catalog/products')
def block5_catalog_create(payload:dict=Body(...))->dict:
    try:return {'status':'ok', **catalog_create_product(payload)}
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/admin/catalog/products/{product_id}')
def block5_catalog_detail(product_id:str)->dict:
    try:return {'status':'ok','product':catalog_get_product(product_id)}
    except KeyError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.put('/api/admin/catalog/products/{product_id}')
def block5_catalog_update(product_id:str,payload:dict=Body(...))->dict:
    try:return {'status':'ok', **catalog_update_product(product_id,payload)}
    except KeyError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.delete('/api/admin/catalog/products/{product_id}')
def block5_catalog_delete(product_id:str,confirm:bool=False)->dict:
    try:return {'status':'ok', **catalog_delete_product(product_id,confirm)}
    except KeyError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc

@router.get('/api/admin/catalog/duplicates')
def block5_catalog_duplicates()->dict:
    return {'status':'ok', **catalog_duplicate_report()}


@router.post("/api/admin/catalog/products/{product_id}/images/batch")
async def product_images_batch(
    product_id: str,
    files: list[UploadFile] = File(...),
    variant_id: str = Form(""),
) -> dict:
    payload = [(f.filename or "image", await f.read(), f.content_type or "") for f in files]
    try:
        return media_upload_batch(product_id, payload, variant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/admin/catalog/products/{product_id}/images")
def product_images_list(product_id: str) -> dict:
    return product_media_list_assets(product_id)


@router.put("/api/admin/catalog/products/{product_id}/images/{asset_id}/cover")
def product_image_cover(product_id: str, asset_id: str) -> dict:
    try:
        return media_set_cover(product_id, asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/api/admin/catalog/products/{product_id}/images/{asset_id}/variant")
def product_image_variant(product_id: str, asset_id: str, payload: dict = Body(default={})) -> dict:
    try:
        return media_assign_variant(product_id, asset_id, str(payload.get("variantId") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/admin/catalog/images/{asset_id}/retry")
def product_image_retry(asset_id: str) -> dict:
    try:
        return media_retry_asset(asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/admin/catalog/products/{product_id}/images/{asset_id}")
def product_image_delete(product_id: str, asset_id: str, confirm: bool = Query(False)) -> dict:
    try:
        return media_delete_asset(product_id, asset_id, confirm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Bloque 12 RC2: recuperación integral y reconstrucción segura.
from services.legacy_recovery import recovery_report, recover_empty_business_data

@router.get('/api/admin/recovery/report')
def recovery_report_api()->dict:
    return recovery_report()

@router.post('/api/admin/recovery/apply')
def recovery_apply_api()->dict:
    return recover_empty_business_data()

@router.get('/recovery-center', response_class=HTMLResponse)
def recovery_center_page()->HTMLResponse:
    return HTMLResponse("""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Recuperación integral | Elegance</title><style>body{margin:0;background:#071018;color:#eef8ff;font-family:Arial,sans-serif}.wrap{max-width:1000px;margin:auto;padding:28px}.card{background:#0c1721;border:1px solid #263b49;border-radius:18px;padding:20px;margin:16px 0}button{background:#67d6f5;border:0;border-radius:999px;padding:14px 22px;font-weight:800;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;color:#bdeeff}.muted{color:#a7bac7}</style></head><body><div class='wrap'><h1>Recuperación integral Elegance</h1><p class='muted'>Analiza bases anteriores y recupera únicamente tablas de negocio que estén vacías en la base activa. Antes de aplicar crea un respaldo preventivo.</p><div class='card'><button onclick='loadReport()'>Analizar fuentes</button> <button onclick='applyRecovery()'>Recuperar datos vacíos</button></div><div class='card'><pre id='out'>Cargando análisis…</pre></div></div><script>async function loadReport(){let r=await fetch('/api/admin/recovery/report');document.getElementById('out').textContent=JSON.stringify(await r.json(),null,2)}async function applyRecovery(){if(!confirm('Se creará un respaldo y solo se llenarán tablas actualmente vacías. ¿Continuar?'))return;let r=await fetch('/api/admin/recovery/apply',{method:'POST'});document.getElementById('out').textContent=JSON.stringify(await r.json(),null,2)}loadReport()</script></body></html>""")
