"""Turn provider exceptions into actionable messages without leaking secrets."""

from __future__ import annotations


def public_image_error(exc: Exception, provider: str = "图片模型") -> str:
    text = str(exc or "").strip()
    lower = text.lower()
    prefix = f"{provider}："

    if "api_key not set" in lower or "api key not set" in lower or "missing api_key" in lower:
        return prefix + "尚未配置 API Key，请先在管理端保存密钥。"
    if "401" in lower or "unauthorized" in lower or "authentication" in lower or "invalidapi" in lower:
        return prefix + "API Key 无效，或密钥与接口地域/计费类型不匹配。"
    if "403" in lower or "forbidden" in lower or "permission" in lower:
        return prefix + "当前 API Key 没有调用所选模型的权限。"
    if "429" in lower or "rate limit" in lower or "ratelimit" in lower or "quota" in lower:
        return prefix + "请求过于频繁或账户额度不足，请稍后重试并检查余额。"
    if "timeout" in lower or "timed out" in lower:
        return prefix + "模型服务响应超时，请检查网络、代理或稍后重试。"
    if "download" in lower:
        return prefix + "模型已经返回结果，但服务器下载图片失败。"
    if "not found" in lower or "404" in lower:
        return prefix + "接口地址或模型 ID 不存在，请检查 base_url 与模型选择。"
    if "content" in lower and ("policy" in lower or "safety" in lower or "risk" in lower):
        return prefix + "提示词触发了供应商的内容安全策略。"
    return prefix + "调用失败，请到管理端运行连通性检测后重试。"
