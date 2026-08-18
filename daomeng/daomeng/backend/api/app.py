import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from accounts.database import SessionLocal, init_database
from accounts.service import bootstrap_admin
from accounts.settings_store import load_runtime_config
from api.logging_config import setup_concurrent_logging
from api.observability import ObservabilityMiddleware
from api.security_layer import ALLOWED_ORIGINS, SecurityMiddleware
from config import settings
from pipelines.queue_worker import pipeline_queue

setup_concurrent_logging()

logger = logging.getLogger(__name__)

# Routers instantiate the workflow engine at import time, so database-backed
# snapshots must be available before importing api.routers.
init_database()
with SessionLocal() as db:
    bootstrap_admin(db)
    stored_config = load_runtime_config(db)
    if stored_config:
        settings.apply_runtime_config(stored_config)
        logger.info("Encrypted administrator model configuration loaded")

from api.routers import (
    auth_router,
    configuration_router,
    files_router,
    health_router,
    pipelines_router,
    sandbox_router,
    sessions_router,
    stages_router,
    workflow_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting 导梦 API")
    logger.info("Code directory mounted at /code: %s", settings.CODE_DIR)
    await pipeline_queue.start()
    try:
        yield
    finally:
        await pipeline_queue.stop()
        logger.info("导梦 API shutdown complete")


app = FastAPI(title="导梦", version="2.0.0", lifespan=lifespan)

app.add_middleware(SecurityMiddleware)
app.add_middleware(ObservabilityMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
logger.info("CORS enabled for origins: %s", ALLOWED_ORIGINS)

os.makedirs(settings.CODE_DIR, exist_ok=True)
app.mount("/code", StaticFiles(directory=settings.CODE_DIR), name="code")

app.include_router(health_router)
app.include_router(files_router)
app.include_router(workflow_router)
app.include_router(sessions_router)
app.include_router(stages_router)
app.include_router(sandbox_router)
app.include_router(pipelines_router)
app.include_router(configuration_router)
app.include_router(auth_router)
logger.info("API routers registered")


@app.get("/")
async def root():
    return {"service": "导梦", "version": "2.0.0", "health": "/api/health"}
