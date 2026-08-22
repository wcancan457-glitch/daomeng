"""Low-cost provider credential and selected-model connectivity checks."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable

import httpx

from config import Config
from models.config_model import get_model_config


SUPPORTED_PROVIDERS = {"siliconflow", "dashscope", "ark"}

PROVIDER_LABELS = {
    "siliconflow": "硅基流动",
    "dashscope": "阿里云百炼 DashScope",
    "ark": "火山方舟 ARK",
}

PROVIDER_ENV_KEYS = {
    "siliconflow": "SILICONFLOW_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "ark": "ARK_API_KEY",
}

MODEL_FIELDS = (
    "llm",
    "vlm",
    "image_t2i",
    "image_it2i",
    "video_first_frame",
    "video_start_end",
    "video_reference",
)


def _selected_models(provider: str, config: Dict[str, Any]) -> list[str]:
    models = config.get("models", {})
    selected: list[str] = []
    for field in MODEL_FIELDS:
        model = str(models.get(field) or "").strip()
        if model and get_model_config(model).get("provider") == provider and model not in selected:
            selected.append(model)
    return selected


def _collect_model_ids(value: Any) -> set[str]:
    """Extract model IDs from OpenAI-style and provider-specific list payloads."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key in ("id", "model", "model_id", "model_name"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                found.add(candidate.strip())
        for key, child in value.items():
            if key not in {"id", "model", "model_id", "model_name"}:
                found.update(_collect_model_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_collect_model_ids(child))
    return found


def _failure_message(status_code: int) -> str:
    if status_code == 401:
        return "API Key 无效，或 API Key 与接口地域/计费类型不匹配。"
    if status_code == 403:
        return "API Key 已识别，但没有访问该供应商资源的权限。"
    if status_code == 404:
        return "接口地址无法提供模型列表，请检查 base_url 是否填写正确。"
    if status_code == 429:
        return "供应商请求过于频繁或账户额度受限，请稍后再试。"
    if status_code >= 500:
        return "供应商服务暂时不可用，请稍后再试。"
    return f"供应商返回 HTTP {status_code}，请检查 API Key 与接口地址。"


def _matched_models(selected: Iterable[str], available: set[str]) -> list[str]:
    available_lower = {model.lower() for model in available}
    return [model for model in selected if model.lower() in available_lower]


def check_provider(provider: str) -> Dict[str, Any]:
    """Validate one configured provider without running a paid generation job."""
    provider = provider.strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        return {
            "ok": False,
            "level": "error",
            "provider": provider,
            "message": "暂不支持检测该供应商。",
            "selected_models": [],
            "verified_models": [],
        }

    config = Config.as_dict()
    provider_config = config.get("api_providers", {}).get(provider, {})
    api_key = str(provider_config.get("api_key") or "").strip()
    base_url = str(provider_config.get("base_url") or "").strip().rstrip("/")
    selected = _selected_models(provider, config)
    source = "environment" if os.getenv(PROVIDER_ENV_KEYS[provider], "").strip() else "admin"

    base = {
        "provider": provider,
        "provider_label": PROVIDER_LABELS[provider],
        "configured": bool(api_key),
        "credential_source": source,
        "selected_models": selected,
        "verified_models": [],
    }

    if not api_key:
        return {
            **base,
            "ok": False,
            "level": "error",
            "message": f"尚未配置 {PROVIDER_LABELS[provider]} API Key。",
        }
    if not base_url:
        return {
            **base,
            "ok": False,
            "level": "error",
            "message": "接口地址为空，请先填写 base_url。",
        }

    models_url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    proxy = Config.provider_proxy(provider)

    try:
        client_kwargs: Dict[str, Any] = {"timeout": httpx.Timeout(20.0, connect=10.0)}
        if proxy:
            client_kwargs["proxy"] = proxy
        with httpx.Client(**client_kwargs) as client:
            response = client.get(models_url, headers=headers)
    except httpx.TimeoutException:
        return {
            **base,
            "ok": False,
            "level": "error",
            "message": "连接供应商超时，请检查接口地址、代理或网络。",
        }
    except httpx.HTTPError:
        return {
            **base,
            "ok": False,
            "level": "error",
            "message": "无法连接供应商，请检查接口地址、代理或网络。",
        }

    if response.status_code < 200 or response.status_code >= 300:
        return {
            **base,
            "ok": False,
            "level": "error",
            "http_status": response.status_code,
            "message": _failure_message(response.status_code),
        }

    try:
        available = _collect_model_ids(response.json())
    except ValueError:
        available = set()
    verified = _matched_models(selected, available)

    if selected and available and len(verified) != len(selected):
        missing = [model for model in selected if model not in verified]
        return {
            **base,
            "ok": True,
            "level": "warning",
            "verified_models": verified,
            "message": "API Key 连通正常，但以下已选模型未出现在可用列表：" + "、".join(missing),
        }

    if selected and not available:
        return {
            **base,
            "ok": True,
            "level": "warning",
            "message": "API Key 连通正常，但供应商未返回可核对的模型列表。",
        }

    return {
        **base,
        "ok": True,
        "level": "success",
        "verified_models": verified,
        "message": "API Key 与接口地址连通正常。" if not selected else "API Key 连通正常，当前模型已在可用列表中。",
    }
