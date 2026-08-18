import os
import time

from fastapi import APIRouter, Response
from sqlalchemy import text

from accounts.database import SessionLocal
from api.security_layer import auth_is_configured
from config import settings

router = APIRouter(tags=["Health"])


@router.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "daomeng-api", "timestamp": time.time()}


@router.get("/api/health/ready")
async def readiness_check(response: Response):
    checks = {"database": False, "storage": False, "authentication": auth_is_configured()}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False

    try:
        os.makedirs(settings.RUNTIME_DATA_DIR, exist_ok=True)
        checks["storage"] = os.access(settings.RUNTIME_DATA_DIR, os.W_OK)
    except OSError:
        checks["storage"] = False

    ready = all(checks.values())
    if not ready:
        response.status_code = 503
    return {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "timestamp": time.time(),
    }
