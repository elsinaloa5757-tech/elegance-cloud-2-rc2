from __future__ import annotations

import os
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse

from api.routes import router
from api.library_routes import router as library_router, public_router as library_public_router
from services.fashion_library import initialize_library
from services.mobile_inbox import start_worker, stop_worker
from services.elegance_studio import migrate_studio
from services.commercial_automation import migrate_commercial
from services.public_catalog import migrate_public_catalog
from services.security_platform import migrate_security, is_public, session_user, setup_required, ensure_release_backup
from services.product_workflow import migrate_sprint6
from services.universal_products import migrate_universal_products
from services.batch_automation import migrate_batch_automation
from services.universal_intelligence import migrate_intelligence
from services.media_library import migrate_media_library, backfill_state_assets
from services.sales_manager import migrate_sales_manager
from services.elegance_brain import migrate_brain
from services.runtime_config import data_dir, require_production_configuration
from services.persistent_sqlite import PersistentSQLiteLease, should_sync
from services.product_media_flow import migrate_product_media
from services.home_server import start_backup_scheduler, stop_backup_scheduler



@asynccontextmanager
async def _lifespan(app: FastAPI):
    del app
    ensure_release_backup("2.2-rc1")
    initialize_library()
    migrate_studio()
    migrate_commercial()
    migrate_public_catalog()
    migrate_security()
    migrate_sprint6()
    migrate_universal_products()
    migrate_batch_automation()
    migrate_intelligence()
    migrate_media_library()
    migrate_sales_manager()
    migrate_brain()
    migrate_product_media()
    try:
        from services.state_store import load_state as _load_state
        backfill_state_assets(_load_state())
    except Exception:
        pass
    serverless = os.getenv("ELEGANCE_SERVERLESS", "").strip() == "1"
    if not serverless:
        start_worker()
        start_backup_scheduler()
    try:
        yield
    finally:
        if not serverless:
            stop_backup_scheduler()
            stop_worker()

def create_app() -> FastAPI:
    require_production_configuration()
    app = FastAPI(
        title="Elegance AI",
        version="Cloud 2.0",
        lifespan=_lifespan,
        description=(
            "Elegance Brain Enterprise: plataforma modular para comercio, comunicaciones, finanzas, compras, automatización, analítica y nube. "
            "de fotografías de sneakers. Flujo V26 controlado: catálogo automático, historial persistente y memoria local de correcciones."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[x.strip() for x in __import__("os").getenv("ELEGANCE_ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if x.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


    @app.middleware("http")
    async def secure_admin(request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or is_public(path):
            response = await call_next(request)
        else:
            token = request.cookies.get("elegance_session") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            user = session_user(token)
            if setup_required():
                if path.startswith("/api/"):
                    return JSONResponse({"detail": "Configuración inicial requerida.", "setup": "/setup"}, status_code=428)
                return RedirectResponse("/setup", status_code=303)
            if not user:
                if path.startswith("/api/"):
                    return JSONResponse({"detail": "Autenticación requerida."}, status_code=401)
                return RedirectResponse(f"/login?next={path}", status_code=303)
            request.state.user = user
            response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob: https:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        if __import__('os').getenv('ELEGANCE_ENV','development') == 'production':
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.middleware("http")
    async def persistent_database(request: Request, call_next):
        if not should_sync(request.url.path):
            return await call_next(request)
        with PersistentSQLiteLease() as lease:
            request.state.persistence = lease
            response = await call_next(request)
        response.headers.setdefault("X-Elegance-Persistence", "postgres")
        response.headers.setdefault("X-Elegance-Revision", str(lease.revision))
        return response

    app.mount('/assets', StaticFiles(directory=str(__import__('pathlib').Path(__file__).resolve().parents[1] / 'assets')), name='assets')
    app.mount('/media', StaticFiles(directory=str(data_dir())), name='media')
    @app.exception_handler(404)
    async def custom_not_found(request: Request, exc):
        if request.url.path.startswith('/api/'):
            return JSONResponse({'detail':'Recurso no encontrado.'},status_code=404)
        from services.premium_web import error_page
        return HTMLResponse(error_page(404,'Página no encontrada'),status_code=404)

    app.include_router(router)
    app.include_router(library_router)
    app.include_router(library_public_router)

    return app
