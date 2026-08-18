import copy
from typing import Any, Dict

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api.auth_context import request_user_role, require_admin
from api.logging_config import apply_access_log_setting, apply_log_level_setting
from config import Config

router = APIRouter(tags=["Configuration"])

SECRET_KEYS = {"api_key", "access_key", "secret_key"}


class ConfigUpdateRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)



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


def _merge_without_secrets(current: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(current)
    for key, value in updates.items():
        if key in SECRET_KEYS:
            merged[key] = ""
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_without_secrets(merged[key], value)
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
async def update_config(req: ConfigUpdateRequest, request: Request):
    require_admin(request)
    config = Config.update_config(_merge_without_secrets(Config.as_dict(), req.values))
    apply_log_level_setting()
    apply_access_log_setting()
    return _response(config)
