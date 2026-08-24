"""Turn provider exceptions into actionable messages without leaking secrets."""

from __future__ import annotations


def is_retryable_media_error(exc: Exception) -> bool:
    """Return whether a provider failure is safe to retry once."""
    lower = str(exc or "").lower()
    return any(
        marker in lower
        for marker in (
            "timeout",
            "timed out",
            "connection reset",
            "connection aborted",
            "temporarily unavailable",
            "502",
            "503",
            "504",
        )
    )


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
    if "sensitivecontentdetected" in lower or (
        "content" in lower and ("policy" in lower or "safety" in lower or "risk" in lower or "sensitive" in lower)
    ):
        return prefix + "提示词触发了供应商的内容安全策略。"
    if "invalidparameter" in lower or "unsupportedparameter" in lower or "unknown parameter" in lower:
        return prefix + "当前模型不支持本次请求参数，请检查模型版本或生成配置。"
    return prefix + "调用失败，请到管理端运行连通性检测后重试。"


def public_video_error(exc: Exception, provider: str = "视频模型") -> str:
    lower = str(exc or "").strip().lower()
    prefix = f"{provider}："
    if "api_key not set" in lower or "api key not set" in lower:
        return prefix + "尚未配置 API Key，请先在管理端保存密钥。"
    if "401" in lower or "unauthorized" in lower or "authentication" in lower:
        return prefix + "API Key 无效，或密钥与接口地域不匹配。"
    if "403" in lower or "forbidden" in lower or "permission" in lower:
        return prefix + "当前 API Key 没有所选视频模型的调用权限。"
    if "429" in lower or "rate limit" in lower or "quota" in lower:
        return prefix + "请求过于频繁或账户额度不足，请稍后重试并检查余额。"
    if "timeout" in lower or "timed out" in lower or "超时" in lower:
        return prefix + "生成任务响应超时，请稍后重试。"
    if "任务尚未成功" in str(exc):
        return prefix + str(exc).split("Seedance", 1)[-1].strip(" ：:")
    if "任务模型不匹配" in str(exc) or "任务时长不匹配" in str(exc):
        return prefix + str(exc).split("Seedance", 1)[-1].strip(" ：:")
    if "not found" in lower or "404" in lower or "尚未在项目中注册" in lower:
        return prefix + "模型 ID 不存在或尚未接入当前项目。"
    if "invalidparameter" in lower or "invalid parameter" in lower or "unsupportedparameter" in lower:
        return prefix + "提交参数不被当前模型接受，请检查模型版本、时长、分辨率和可选参数。"
    if "输入图片不存在" in str(exc):
        return prefix + "首帧参考图记录存在，但文件已失效。请在当前视频片段上传一张新首帧后重试。"
    if "first_frame" in lower:
        return prefix + "缺少可用的首帧参考图，请在当前视频片段上传一张首帧后重试。"
    if "sensitive" in lower or "safety" in lower or "policy" in lower:
        return prefix + "提示词或参考素材触发了供应商内容安全策略。"
    if "服务器没有获得可用的视频文件" in str(exc) or "download" in lower:
        return prefix + "模型任务可能已完成，但服务器下载结果失败，请稍后重试。"
    return prefix + "生成失败，请在管理端核对模型与 API 配置后重试。"
