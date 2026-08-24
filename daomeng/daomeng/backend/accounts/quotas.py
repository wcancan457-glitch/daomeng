from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from accounts.models import TaskOwnership, User


class DailyQuotaError(RuntimeError):
    pass


def _start_of_today() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def task_category(task: TaskOwnership) -> str:
    payload = dict(task.payload or {})
    if task.task_kind == "pipeline":
        return "video"
    tool = str(payload.get("tool") or "").lower()
    if tool in {"llm", "vlm"}:
        return "llm"
    if tool in {"t2i", "i2i"}:
        return "image"
    if tool == "video":
        return "video"
    return "other"


def usage_today(db: Session, user_id: str) -> dict[str, int]:
    records = db.scalars(
        select(TaskOwnership).where(
            TaskOwnership.user_id == user_id,
            TaskOwnership.created_at >= _start_of_today(),
        )
    ).all()
    usage = {"llm": 0, "image": 0, "video": 0, "other": 0}
    for record in records:
        usage[task_category(record)] += 1
    return usage


def enforce_daily_quota(db: Session, user_id: str, category: str) -> None:
    if user_id == "legacy-shared":
        return
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise DailyQuotaError("账号当前不可用。")
    if category not in {"llm", "image", "video"}:
        return
    used = usage_today(db, user_id)[category]
    limit = int(getattr(user, f"daily_{category}_limit"))
    if used >= limit:
        label = {"llm": "文本/视觉理解", "image": "图片生成", "video": "视频生成"}[category]
        raise DailyQuotaError(f"今日{label}测试额度已用完（{limit} 次），请联系管理员调整。")
