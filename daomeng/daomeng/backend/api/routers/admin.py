from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from accounts.audit import record_admin_action
from accounts.database import get_db
from accounts.models import (
    AdminAuditLog,
    AuthSession,
    ProjectOwnership,
    SystemSetting,
    TaskOwnership,
    User,
)
from accounts.quotas import task_category, usage_today
from accounts.settings_store import MODEL_CONFIG_KEY
from api.auth_context import require_admin
from api.security_layer import AUTH_MODE, REGISTRATION_ENABLED, auth_is_configured
from config import Config, settings
from pipelines.queue_worker import WORKER_CONCURRENCY, WORKER_ENABLED, pipeline_queue
from pipelines.storage import update_task

router = APIRouter(prefix="/api/admin", tags=["Admin"])


class UserUpdateRequest(BaseModel):
    is_active: bool | None = None
    daily_llm_limit: int | None = Field(default=None, ge=0, le=10000)
    daily_image_limit: int | None = Field(default=None, ge=0, le=10000)
    daily_video_limit: int | None = Field(default=None, ge=0, le=1000)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _user_payload(db: Session, user: User) -> dict:
    project_count = db.scalar(
        select(func.count()).select_from(ProjectOwnership).where(ProjectOwnership.user_id == user.id)
    ) or 0
    task_count = db.scalar(
        select(func.count()).select_from(TaskOwnership).where(TaskOwnership.user_id == user.id)
    ) or 0
    last_login = db.scalar(
        select(func.max(AuthSession.last_used_at)).where(AuthSession.user_id == user.id)
    )
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "email_verified": user.email_verified,
        "created_at": _iso(user.created_at),
        "last_login_at": _iso(last_login),
        "project_count": project_count,
        "task_count": task_count,
        "usage_today": usage_today(db, user.id),
        "limits": {
            "llm": user.daily_llm_limit,
            "image": user.daily_image_limit,
            "video": user.daily_video_limit,
        },
    }


def _task_payload(owner: TaskOwnership, user: User | None) -> dict:
    payload = dict(owner.payload or {})
    input_data = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    title = (
        input_data.get("title")
        or input_data.get("goods_title")
        or input_data.get("text")
        or input_data.get("prompt_text")
        or owner.task_id
    )
    return {
        "task_id": owner.task_id,
        "task_kind": owner.task_kind,
        "category": task_category(owner),
        "status": owner.status,
        "user_id": owner.user_id,
        "user_email": user.email if user else "未知账号",
        "title": str(title)[:160],
        "pipeline": payload.get("pipeline"),
        "tool": payload.get("tool"),
        "model": payload.get("model"),
        "progress": int(payload.get("progress") or 0),
        "error": str(payload.get("error") or "")[:1000],
        "retry_count": int(payload.get("retry_count") or 0),
        "duration_seconds": payload.get("duration_seconds"),
        "created_at": _iso(owner.created_at),
        "updated_at": _iso(owner.updated_at),
    }


@router.get("/overview")
async def overview(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    today = _today_start()
    total_users = db.scalar(select(func.count()).select_from(User)) or 0
    active_users = db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0
    new_users_today = db.scalar(
        select(func.count()).select_from(User).where(User.created_at >= today)
    ) or 0
    total_projects = db.scalar(select(func.count()).select_from(ProjectOwnership)) or 0
    total_tasks = db.scalar(select(func.count()).select_from(TaskOwnership)) or 0
    running_tasks = db.scalar(
        select(func.count()).select_from(TaskOwnership).where(TaskOwnership.status == "running")
    ) or 0
    failed_tasks = db.scalar(
        select(func.count()).select_from(TaskOwnership).where(TaskOwnership.status == "failed")
    ) or 0
    completed_tasks = db.scalar(
        select(func.count()).select_from(TaskOwnership).where(TaskOwnership.status == "completed")
    ) or 0
    denominator = completed_tasks + failed_tasks
    today_tasks = db.scalars(select(TaskOwnership).where(TaskOwnership.created_at >= today)).all()
    usage = {"llm": 0, "image": 0, "video": 0, "other": 0}
    for task in today_tasks:
        usage[task_category(task)] += 1
    recent_failed = db.scalars(
        select(TaskOwnership)
        .where(TaskOwnership.status == "failed")
        .order_by(TaskOwnership.updated_at.desc())
        .limit(5)
    ).all()
    users = {item.id: item for item in db.scalars(select(User)).all()}
    return {
        "users": {"total": total_users, "active": active_users, "new_today": new_users_today},
        "projects": {"total": total_projects},
        "tasks": {
            "total": total_tasks,
            "running": running_tasks,
            "failed": failed_tasks,
            "completed": completed_tasks,
            "success_rate": round((completed_tasks / denominator) * 100, 1) if denominator else None,
        },
        "usage_today": usage,
        "recent_failed_tasks": [_task_payload(task, users.get(task.user_id)) for task in recent_failed],
    }


@router.get("/users")
async def users(
    request: Request,
    q: str = Query(default="", max_length=120),
    status: Literal["all", "active", "disabled"] = "all",
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    require_admin(request)
    statement = select(User)
    if q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(User.email.ilike(pattern), User.display_name.ilike(pattern))
        )
    if status == "active":
        statement = statement.where(User.is_active.is_(True))
    elif status == "disabled":
        statement = statement.where(User.is_active.is_(False))
    records = db.scalars(statement.order_by(User.created_at.desc()).limit(limit)).all()
    return {"users": [_user_payload(db, user) for user in records]}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    req: UserUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    actor_id = require_admin(request)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在。")
    values = req.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status_code=400, detail="没有需要更新的字段。")
    if user.id == actor_id and values.get("is_active") is False:
        raise HTTPException(status_code=400, detail="不能停用当前管理员账号。")
    before = {
        "is_active": user.is_active,
        "daily_llm_limit": user.daily_llm_limit,
        "daily_image_limit": user.daily_image_limit,
        "daily_video_limit": user.daily_video_limit,
    }
    for key, value in values.items():
        setattr(user, key, value)
    db.commit()
    record_admin_action(
        db,
        actor_id=actor_id,
        action="user.update",
        target_type="user",
        target_id=user.id,
        details={"email": user.email, "before": before, "after": values},
    )
    db.refresh(user)
    return {"user": _user_payload(db, user)}


@router.get("/tasks")
async def tasks(
    request: Request,
    status: str = Query(default="all", max_length=24),
    kind: str = Query(default="all", max_length=24),
    user_id: str = Query(default="", max_length=36),
    limit: int = Query(default=100, ge=1, le=300),
    db: Session = Depends(get_db),
):
    require_admin(request)
    statement = select(TaskOwnership)
    if status != "all":
        statement = statement.where(TaskOwnership.status == status)
    if kind != "all":
        statement = statement.where(TaskOwnership.task_kind == kind)
    if user_id:
        statement = statement.where(TaskOwnership.user_id == user_id)
    records = db.scalars(statement.order_by(TaskOwnership.created_at.desc()).limit(limit)).all()
    user_ids = {record.user_id for record in records}
    users_by_id = {
        user.id: user
        for user in db.scalars(select(User).where(User.id.in_(user_ids))).all()
    } if user_ids else {}
    return {"tasks": [_task_payload(task, users_by_id.get(task.user_id)) for task in records]}


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str, request: Request, db: Session = Depends(get_db)):
    actor_id = require_admin(request)
    owner = db.get(TaskOwnership, task_id)
    if not owner:
        raise HTTPException(status_code=404, detail="任务不存在。")
    if owner.task_kind != "pipeline":
        raise HTTPException(status_code=400, detail="临时工作台任务暂不支持后台重试。")
    if owner.status != "failed":
        raise HTTPException(status_code=400, detail="只有失败任务可以重新排队。")
    payload = update_task(
        task_id,
        status="pending",
        progress=0,
        message="Task queued by administrator",
        error=None,
        started_at=None,
        completed_at=None,
        retry_count=int(dict(owner.payload or {}).get("retry_count") or 0) + 1,
    )
    pipeline_queue.notify()
    record_admin_action(
        db,
        actor_id=actor_id,
        action="task.retry",
        target_type="task",
        target_id=task_id,
        details={"pipeline": payload.get("pipeline"), "owner_id": owner.user_id},
    )
    db.expire_all()
    updated_owner = db.get(TaskOwnership, task_id)
    return {"task": _task_payload(updated_owner, db.get(User, owner.user_id))}


@router.get("/models")
async def models(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    config = Config.as_dict()
    providers = []
    env_names = {
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "siliconflow": "SILICONFLOW_API_KEY",
        "dashscope": "DASHSCOPE_API_KEY",
        "ark": "ARK_API_KEY",
        "kling": "KLING_ACCESS_KEY",
    }
    for name, values in config.get("api_providers", {}).items():
        if name == "common" or not isinstance(values, dict):
            continue
        secret = str(values.get("api_key") or values.get("access_key") or "")
        from_environment = bool(os.getenv(env_names.get(name, ""), ""))
        providers.append(
            {
                "id": name,
                "configured": bool(secret),
                "credential_hint": f"••••{secret[-4:]}" if secret else "",
                "credential_source": "environment" if from_environment else "admin" if secret else "none",
                "base_url": values.get("base_url", ""),
            }
        )
    setting = db.get(SystemSetting, MODEL_CONFIG_KEY)
    return {
        "providers": providers,
        "assignments": config.get("models", {}),
        "config_updated_at": _iso(setting.updated_at) if setting else None,
    }


@router.get("/system")
async def system(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    pending = db.scalar(
        select(func.count()).select_from(TaskOwnership).where(TaskOwnership.status == "pending")
    ) or 0
    running = db.scalar(
        select(func.count()).select_from(TaskOwnership).where(TaskOwnership.status == "running")
    ) or 0
    return {
        "service": {"status": "ready", "version": "2.0.0"},
        "database": {"status": "ready"},
        "authentication": {
            "status": "ready" if auth_is_configured() else "not_ready",
            "mode": AUTH_MODE,
            "registration_enabled": AUTH_MODE == "users" and REGISTRATION_ENABLED,
        },
        "queue": {
            "enabled": WORKER_ENABLED,
            "running": pipeline_queue.is_running,
            "concurrency": WORKER_CONCURRENCY,
            "pending": pending,
            "active": running,
        },
        "storage": {
            "status": "ready" if os.access(settings.RUNTIME_DATA_DIR, os.W_OK) else "not_ready",
            "path": str(settings.RUNTIME_DATA_DIR),
        },
    }


@router.get("/audit")
async def audit(
    request: Request,
    limit: int = Query(default=100, ge=1, le=300),
    db: Session = Depends(get_db),
):
    require_admin(request)
    records = db.scalars(
        select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(limit)
    ).all()
    actor_ids = {record.actor_id for record in records}
    actors = {
        user.id: user.email
        for user in db.scalars(select(User).where(User.id.in_(actor_ids))).all()
    } if actor_ids else {}
    return {
        "logs": [
            {
                "id": record.id,
                "actor_id": record.actor_id,
                "actor_email": actors.get(record.actor_id, "未知管理员"),
                "action": record.action,
                "target_type": record.target_type,
                "target_id": record.target_id,
                "details": record.details,
                "created_at": _iso(record.created_at),
            }
            for record in records
        ]
    }
