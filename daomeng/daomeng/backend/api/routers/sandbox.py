import json
import logging
import os
import threading
import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from accounts.database import SessionLocal
from accounts.ownership import (
    delete_task_ownership,
    register_task,
    save_task_payload,
    task_payloads_for_user,
)
from accounts.quotas import DailyQuotaError, enforce_daily_quota
from api.auth_context import request_user_id
from api.routers.files import resolve_user_media_path
from api.schemas.sandbox import (
    SandboxI2IRequest,
    SandboxLLMRequest,
    SandboxT2IRequest,
    SandboxVideoRequest,
    SandboxVLMRequest,
)
from config import settings

router = APIRouter(tags=["Sandbox"])
logger = logging.getLogger(__name__)


SANDBOX_DIR = os.path.join(settings.CODE_DIR, "result", "sandbox")
SANDBOX_HISTORY_FILE = os.path.join(SANDBOX_DIR, "history.json")
SANDBOX_ACTIVE_TASKS: dict[str, dict] = {}
SANDBOX_LOCK = threading.RLock()

# 确保目录存在
os.makedirs(SANDBOX_DIR, exist_ok=True)


def _load_history(user_id: str | None = None) -> List[dict]:
    """加载历史记录"""
    with SANDBOX_LOCK:
        if user_id and user_id != "legacy-shared":
            records = task_payloads_for_user(user_id, task_kind="sandbox")
            records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
            return records
        if os.path.exists(SANDBOX_HISTORY_FILE):
            try:
                with open(SANDBOX_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    records = json.load(f)
                    if user_id:
                        return [
                            record
                            for record in records
                            if str(record.get("user_id") or "legacy-shared") == user_id
                        ]
                    return records
            except Exception:
                logger.warning("Failed to load sandbox history: %s", SANDBOX_HISTORY_FILE, exc_info=True)
                return []
        return []


def _save_history(history: List[dict]):
    """保存历史记录"""
    with SANDBOX_LOCK:
        tmp_path = f"{SANDBOX_HISTORY_FILE}.{uuid.uuid4().hex}.tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, SANDBOX_HISTORY_FILE)


def _normalize_path(path: str) -> str:
    """将绝对路径转换为相对路径格式 result/..."""
    if not path:
        return path
    # 如果已经是相对路径，直接返回
    if not path.startswith('/'):
        # 确保以 result/ 开头
        if not path.startswith('result/'):
            return f"result/{path}"
        return path
    # 绝对路径，提取相对于 CODE_DIR 的部分
    code_dir = settings.CODE_DIR
    if path.startswith(code_dir):
        relative = path[len(code_dir):].lstrip('/')
        # 直接返回 result/... 格式，因为 /code/ 会映射到 CODE_DIR
        return relative
    # 其他绝对路径，尝试提取文件名
    return path.split('/')[-1]


def _convert_output_paths(output_data: dict) -> dict:
    """转换 output 中的路径为相对路径格式"""
    if not output_data:
        return output_data
    converted = output_data.copy()
    # 转换 images
    if 'images' in converted and isinstance(converted['images'], list):
        converted['images'] = [_normalize_path(img) for img in converted['images']]
    # 转换 video_path
    if 'video_path' in converted and converted['video_path']:
        converted['video_path'] = _normalize_path(converted['video_path'])
    # 转换 input 中的 reference_image
    if 'reference_image' in converted.get('input', {}):
        input_copy = converted['input'].copy()
        input_copy['reference_image'] = _normalize_path(input_copy['reference_image'])
        converted['input'] = input_copy
    return converted


def _converted_result_list(paths: List[str] | None) -> List[str]:
    """Return generated image paths in the same format used by sandbox history."""
    converted = _convert_output_paths({"images": paths or []})
    return converted.get("images", [])


def _converted_video_path(path: str | None) -> str:
    """Return generated video path in the same format used by sandbox history."""
    converted = _convert_output_paths({"video_path": path or ""})
    return converted.get("video_path", "")


def _add_record(
    tool: str,
    model: str,
    input_data: dict,
    output_data: dict,
    files: List[str] = None,
    record_id: str | None = None,
    user_id: str = "legacy-shared",
) -> str:
    """添加历史记录"""
    with SANDBOX_LOCK:
        record_id = record_id or str(uuid.uuid4().hex[:8])
        # 转换路径为相对路径格式
        output_data = _convert_output_paths(output_data)
        record = {
            "id": record_id,
            "user_id": user_id,
            "tool": tool,
            "model": model,
            "input": input_data,
            "output": output_data,
            "files": files or [],
            "created_at": datetime.now().isoformat(),
            "status": "completed",
        }
        history = _load_history()
        history.insert(0, record)  # 最新记录放在最前面
        _save_history(history)
        save_task_payload(record_id, user_id, record, task_kind="sandbox")
        return record_id


def _start_active_task(tool: str, model: str, input_data: dict, user_id: str) -> str:
    with SANDBOX_LOCK:
        category = "llm" if tool in {"llm", "vlm"} else "image" if tool in {"t2i", "i2i"} else "video"
        with SessionLocal() as db:
            try:
                enforce_daily_quota(db, user_id, category)
            except DailyQuotaError as exc:
                raise HTTPException(status_code=429, detail=str(exc)) from exc
        task_id = str(uuid.uuid4().hex[:8])
        register_task(task_id, user_id, task_kind="sandbox")
        active_task = {
            "id": task_id,
            "user_id": user_id,
            "tool": tool,
            "model": model,
            "input": input_data,
            "status": "running",
            "progress": 1,
            "created_at": datetime.now().isoformat(),
        }
        SANDBOX_ACTIVE_TASKS[task_id] = active_task
        save_task_payload(task_id, user_id, active_task, task_kind="sandbox")
        return task_id


def _finish_active_task(task_id: str) -> None:
    with SANDBOX_LOCK:
        SANDBOX_ACTIVE_TASKS.pop(task_id, None)


def _delete_record_files(files: List[str]):
    """删除记录关联的文件"""
    for f in files:
        if f and os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                logger.warning("Failed to delete sandbox artifact: %s", f, exc_info=True)
                pass


# 请求模型
@router.get("/api/sandbox/history")
async def sandbox_get_history(request: Request):
    """获取历史记录列表"""
    history = _load_history(request_user_id(request))
    # 返回完整信息（包括 output）
    return {
        "success": True,
        "records": [
            {
                "id": r["id"],
                "tool": r["tool"],
                "model": r["model"],
                "input": r["input"],
                "output": r.get("output"),
                "created_at": r["created_at"],
            }
            for r in history
        ]
    }


@router.get("/api/sandbox/tasks")
async def sandbox_get_active_tasks(request: Request):
    """获取临时工作台正在执行的任务"""
    with SANDBOX_LOCK:
        user_id = request_user_id(request)
        tasks = [task for task in SANDBOX_ACTIVE_TASKS.values() if task["user_id"] == user_id]
    return {"success": True, "tasks": tasks}


@router.get("/api/sandbox/history/{record_id}")
async def sandbox_get_record(record_id: str, request: Request):
    """获取单条历史记录详情"""
    history = _load_history(request_user_id(request))
    for r in history:
        if r["id"] == record_id:
            return {"success": True, "record": r}
    return {"success": False, "error": "记录不存在"}


@router.delete("/api/sandbox/history/{record_id}")
async def sandbox_delete_record(record_id: str, request: Request):
    """删除历史记录"""
    with SANDBOX_LOCK:
        user_id = request_user_id(request)
        history = _load_history()
        record_to_delete = None
        new_history = []
        for r in history:
            owner_id = str(r.get("user_id") or "legacy-shared")
            if r["id"] == record_id and owner_id == user_id:
                record_to_delete = r
            else:
                new_history.append(r)

        if record_to_delete is None:
            return {"success": False, "error": "记录不存在"}

        _save_history(new_history)

    # 删除关联文件不需要占用历史锁。
    _delete_record_files(record_to_delete.get("files", []))
    delete_task_ownership(record_id, user_id)
    logger.info("Sandbox history deleted: record_id=%s", record_id)
    return {"success": True}


@router.post("/api/sandbox/llm")
async def sandbox_llm(req: SandboxLLMRequest, request: Request):
    """临时工作台 - LLM 文字生成"""
    from models.llm_client import LLM
    client = LLM()
    input_data = {"prompt": req.prompt, "web_search": req.web_search}
    user_id = request_user_id(request)
    task_id = _start_active_task("llm", req.model, input_data, user_id)
    try:
        logger.info("Sandbox LLM started: model=%s web_search=%s", req.model, req.web_search)
        result = await run_in_threadpool(
            client.query,
            req.prompt,
            model=req.model,
            web_search=req.web_search,
        )
        # ��存到历史记录
        record_id = _add_record(
            tool="llm",
            model=req.model,
            input_data=input_data,
            output_data={"response": result},
            record_id=task_id,
            user_id=user_id,
        )
        logger.info("Sandbox LLM completed: model=%s record_id=%s", req.model, record_id)
        return {"success": True, "result": result, "record_id": record_id}
    except Exception as e:
        logger.exception("Sandbox LLM failed: model=%s", req.model)
        return {"success": False, "error": str(e)}
    finally:
        _finish_active_task(task_id)


@router.post("/api/sandbox/vlm")
async def sandbox_vlm(req: SandboxVLMRequest, request: Request):
    """临时工作台 - VLM 图片理解"""
    from models.vlm_client import VLM
    client = VLM()
    user_id = request_user_id(request)
    try:
        resolved_images = [resolve_user_media_path(path, user_id) for path in req.images]
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    input_data = {"prompt": req.prompt, "images": req.images}
    task_id = _start_active_task("vlm", req.model, input_data, user_id)
    try:
        logger.info("Sandbox VLM started: model=%s images=%d", req.model, len(req.images or []))
        result = await run_in_threadpool(
            client.query,
            req.prompt,
            image_paths=resolved_images,
            model=req.model,
        )
        # 保存到历史记录
        record_id = _add_record(
            tool="vlm",
            model=req.model,
            input_data=input_data,
            output_data={"response": result},
            record_id=task_id,
            user_id=user_id,
        )
        logger.info("Sandbox VLM completed: model=%s record_id=%s", req.model, record_id)
        return {"success": True, "result": result, "record_id": record_id}
    except Exception as e:
        logger.exception("Sandbox VLM failed: model=%s", req.model)
        return {"success": False, "error": str(e)}
    finally:
        _finish_active_task(task_id)


@router.post("/api/sandbox/t2i")
async def sandbox_t2i(req: SandboxT2IRequest, request: Request):
    """临时工作台 - 文生图"""
    from models.image_client import ImageClient
    client = ImageClient()
    input_data = {"prompt": req.prompt, "style": req.style, "ratio": req.ratio}
    user_id = request_user_id(request)
    task_id = _start_active_task("t2i", req.model, input_data, user_id)
    try:
        logger.info("Sandbox T2I started: model=%s ratio=%s", req.model, req.ratio)
        result = await run_in_threadpool(
            client.generate_image,
            req.prompt,
            model=req.model,
            image_paths=None,
            save_dir=os.path.join(SANDBOX_DIR, user_id, task_id),
            session_id=task_id,
            video_ratio=req.ratio,
        )
        # result 是图片路径列表
        # 保存到历史记录
        record_id = _add_record(
            tool="t2i",
            model=req.model,
            input_data=input_data,
            output_data={"images": result},
            files=result if isinstance(result, list) else [],
            record_id=task_id,
            user_id=user_id,
        )
        logger.info(
            "Sandbox T2I completed: model=%s record_id=%s images=%d",
            req.model,
            record_id,
            len(result) if isinstance(result, list) else 0,
        )
        return {
            "success": True,
            "result": _converted_result_list(result if isinstance(result, list) else []),
            "record_id": record_id,
        }
    except Exception as e:
        logger.exception("Sandbox T2I failed: model=%s", req.model)
        return {"success": False, "error": str(e)}
    finally:
        _finish_active_task(task_id)


@router.post("/api/sandbox/i2i")
async def sandbox_i2i(req: SandboxI2IRequest, request: Request):
    """临时工作台 - 图生图"""
    from models.image_client import ImageClient
    client = ImageClient()
    user_id = request_user_id(request)
    try:
        resolved_image = resolve_user_media_path(req.image, user_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    input_data = {"prompt": req.prompt, "reference_image": req.image}
    task_id = _start_active_task("i2i", req.model, input_data, user_id)
    try:
        logger.info("Sandbox I2I started: model=%s ratio=%s", req.model, req.ratio)
        result = await run_in_threadpool(
            client.generate_image,
            req.prompt,
            image_paths=[resolved_image],
            model=req.model,
            save_dir=os.path.join(SANDBOX_DIR, user_id, task_id),
            session_id=task_id,
            video_ratio=req.ratio,
        )
        # 保存到历史记录
        record_id = _add_record(
            tool="i2i",
            model=req.model,
            input_data=input_data,
            output_data={"images": result},
            files=result if isinstance(result, list) else [],
            record_id=task_id,
            user_id=user_id,
        )
        logger.info(
            "Sandbox I2I completed: model=%s record_id=%s images=%d",
            req.model,
            record_id,
            len(result) if isinstance(result, list) else 0,
        )
        return {
            "success": True,
            "result": _converted_result_list(result if isinstance(result, list) else []),
            "record_id": record_id,
        }
    except Exception as e:
        logger.exception("Sandbox I2I failed: model=%s", req.model)
        return {"success": False, "error": str(e)}
    finally:
        _finish_active_task(task_id)


@router.post("/api/sandbox/video")
async def sandbox_video(req: SandboxVideoRequest, request: Request):
    """临时工作台 - 视频生成"""
    from models.video_client import VideoClient
    client = VideoClient()
    user_id = request_user_id(request)
    try:
        resolved_image = resolve_user_media_path(req.image, user_id) if req.image else ""
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    input_data = {"prompt": req.prompt, "reference_image": req.image}
    task_id = _start_active_task("video", req.model, input_data, user_id)
    try:
        # 生成唯一的保存路径
        save_dir = os.path.join(SANDBOX_DIR, user_id, task_id, "videos")
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, f"{uuid.uuid4().hex[:8]}.mp4")
        logger.info("Sandbox video started: model=%s image=%s", req.model, bool(req.image))

        result = await run_in_threadpool(
            client.generate_video,
            prompt=req.prompt,
            image_path=resolved_image,
            save_path=save_path,
            model=req.model,
            duration=5,
            shot_type="multi",
        )
        # 保存到历史记录
        record_id = _add_record(
            tool="video",
            model=req.model,
            input_data=input_data,
            output_data={"video": result, "video_path": save_path},
            files=[save_path],
            record_id=task_id,
            user_id=user_id,
        )
        logger.info("Sandbox video completed: model=%s record_id=%s video=%s", req.model, record_id, save_path)
        return {
            "success": True,
            "result": result,
            "video_path": _converted_video_path(save_path),
            "record_id": record_id,
        }
    except Exception as e:
        logger.exception("Sandbox video failed: model=%s", req.model)
        return {"success": False, "error": str(e)}
    finally:
        _finish_active_task(task_id)
