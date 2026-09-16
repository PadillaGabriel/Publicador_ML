import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.accounts.router import router as accounts_router
from app.catalog.router import router as catalog_router
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging
from app.core.static_frontend import mount_static_frontend
from app.drafts.router import router as drafts_router
from app.jobs import router as jobs_router
from app.persistence import ProductImage
from app.pricing.router import router as pricing_router
from app.products.router import router as products_router
from app.publication.router import router as publication_router
from app.title_intelligence.router import router as title_intelligence_router
from app.technical_attributes.router import router as technical_attributes_router

configure_logging()
settings = get_settings()

app = FastAPI(
    title="Mercado Libre Enterprise Publisher",
    version="0.2.0",
    description="Metadata-driven publisher with OAuth-ready accounts, commercial plans, drafts, jobs and auditability.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts_router)
app.include_router(catalog_router)
app.include_router(products_router)
app.include_router(pricing_router)
app.include_router(drafts_router)
app.include_router(publication_router)
app.include_router(jobs_router)
app.include_router(title_intelligence_router)
app.include_router(technical_attributes_router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "environment": settings.app_env,
        "live_publication_enabled": settings.ml_live_publication_enabled,
    }


@app.get("/uploads/{image_id}", name="serve_upload")
def serve_upload(image_id: uuid.UUID):
    with SessionLocal() as db:
        image = db.get(ProductImage, image_id)
        if not image:
            raise HTTPException(status_code=404, detail="Image not found.")
        storage_path = str(image.storage_path or "").strip()
        if not storage_path:
            raise HTTPException(status_code=404, detail="Stored image file not found.")
        path = Path(storage_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Stored image file not found.")
        return FileResponse(path, media_type=image.mime_type)


mount_static_frontend(app, settings.frontend_dist_dir)
