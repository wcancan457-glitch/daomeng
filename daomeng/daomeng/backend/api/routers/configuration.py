import copy
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from accounts.audit import record_admin_action
from accounts.database import get_db
from accounts.settings_store import save_runtime_config
from api.auth_context import request_user_role, require_admin
from api.logging_config import apply_access_log_setting, apply_log_level_setting
from api.provider_checks import check_provider
from config import Config

router = APIRouter(tags=["Configuration"])

SECRET_KEYS = {"api_key", "access_key", "secret_key"}


class ConfigUpdateRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


class ProviderTestRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)



def _redact_secrets(values: Dict[str, Any]) -> Dict[str, Any]:
    clean = copy.deepcopy(values)
    for key, value in clean.items():
        if key in SECRET_KEYS:
            clean[key] = ""
        elif isinstance(value, dict):
            clean[key] = _redact_secrets(value)
    return clean


def _configured_secrets(values: Dict[str, Any], prefix: str = "") -> Dict[str, bool]:
    result: Dict[str, bool] = {}
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else key
        if key in SECRET_KEYS:
            result[path] = bool(value)
        elif isinstance(value, dict):
            result.update(_configured_secrets(value, path))
    return result


def _merge_secret_updates(current: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(current)
    for key, value in updates.items():
        if key in SECRET_KEYS:
            # A redacted/blank field means "keep the saved value". A new
            # non-empty value explicitly replaces it.
            if isinstance(value, str) and value.strip():
                merged[key] = value.strip()
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_secret_updates(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _response(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "config": _redact_secrets(config),
        "configured_secrets": _configured_secrets(config),
        "path": "backend/config.yaml",
    }

@router.get("/api/config")
async def get_config(request: Request):
    if request_user_role(request) != "admin":
        config = Config.as_dict()
        return {
            "config": {
                "project_name": config.get("project_name", "导梦"),
                "models": config.get("models", {}),
                "generation": config.get("generation", {}),
            }
        }
    return _response(Config.as_dict())


@router.put("/api/config")
async def update_config(
    req: ConfigUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    actor_id = require_admin(request)
    values = _merge_secret_updates(Config.as_dict(), req.values)
    save_runtime_config(db, values, actor_id)
    record_admin_action(
        db,
        actor_id=actor_id,
        action="config.update",
        target_type="model_config",
        target_id="model_gateway_config_v1",
        details={"sections": sorted(req.values.keys())},
    )
    config = Config.apply_runtime_config(values)
    apply_log_level_setting()
    apply_access_log_setting()
    return _response(config)


@router.post("/api/config/test-provider")
async def test_provider(req: ProviderTestRequest, request: Request):
    require_admin(request)
    return await run_in_threadpool(check_provider, req.provider)
