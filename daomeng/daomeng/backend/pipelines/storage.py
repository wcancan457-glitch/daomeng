import json
import logging
import os
import shutil
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import func, select

from accounts.database import SessionLocal
from accounts.models import TaskOwnership, utcnow
from accounts.ownership import (
    delete_task_ownership,
    load_task_payload,
    register_task,
    save_task_payload,
    task_payloads_for_user,
)
from accounts.quotas import DailyQuotaError, enforce_daily_quota
from config import settings

from .events import publish_task_event

logger = logging.getLogger(__name__)
_task_store_lock = threading.RLock()


def _positive_env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


MAX_PENDING_TASKS_PER_USER = _positive_env_int("MAX_PENDING_TASKS_PER_USER", 10)
MAX_CONCURRENT_TASKS_PER_USER = _positive_env_int("MAX_CONCURRENT_TASKS_PER_USER", 1)

TASK_DATA_DIR = os.path.join(settings.CODE_DIR, "data", "tasks")
TASK_RESULT_DIR = os.path.join(settings.RESULT_DIR, "task")


def ensure_task_dirs() -> None:
    os.makedirs(TASK_DATA_DIR, exist_ok=True)
    os.makedirs(TASK_RESULT_DIR, exist_ok=True)


def new_task_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def task_metadata_path(task_id: str) -> str:
    return os.path.join(TASK_DATA_DIR, f"{task_id}.json")


def task_output_dir(task_id: str) -> str:
    return os.path.join(TASK_RESULT_DIR, task_id)


def now_iso() -> str:
    return datetime.now().isoformat()


class TaskQuotaError(RuntimeError):
    pass


def _write_task_file(metadata: Dict[str, Any]) -> None:
    ensure_task_dirs()
    path = task_metadata_path(metadata["task_id"])
    tmp_path = f"{path}.{uuid.uuid4().hex}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def save_task(metadata: Dict[str, Any]) -> None:
    with _task_store_lock:
        _write_task_file(metadata)
        save_task_payload(
            metadata["task_id"],
            str(metadata.get("user_id") or "legacy-shared"),
            metadata,
            task_kind="pipeline",
        )


def load_task(task_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _task_store_lock:
        metadata = load_task_payload(task_id)
        if not metadata:
            path = task_metadata_path(task_id)
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        owner_id = str(metadata.get("user_id") or "legacy-shared")
        if user_id and owner_id != user_id:
            return None
        return metadata


def delete_task(task_id: str, user_id: Optional[str] = None) -> bool:
    with _task_store_lock:
        metadata = load_task(task_id, user_id=user_id)
        if not metadata:
            return False

        metadata_path = task_metadata_path(task_id)
        output_dir = metadata.get("output_dir") or task_output_dir(task_id)
        if os.path.exists(metadata_path):
            os.remove(metadata_path)
        if output_dir and os.path.exists(output_dir):
            shutil.rmtree(output_dir)
    if user_id:
        delete_task_ownership(task_id, user_id)
    logger.info("Deleted pipeline task: task_id=%s output_dir=%s", task_id, output_dir)
    return True


def list_tasks(limit: int = 100, user_id: Optional[str] = None) -> list[Dict[str, Any]]:
    with _task_store_lock:
        ensure_task_dirs()
        if user_id and user_id != "legacy-shared":
            records = task_payloads_for_user(user_id, task_kind="pipeline")
            records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
            return records[:limit]
        records = []
        for filename in os.listdir(TASK_DATA_DIR):
            if not filename.endswith(".json"):
                continue
            try:
                with open(os.path.join(TASK_DATA_DIR, filename), "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                owner_id = str(metadata.get("user_id") or "legacy-shared")
                if not user_id or owner_id == user_id:
                    records.append(metadata)
            except Exception:
                continue
        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return records[:limit]


def create_task(
    pipeline: str,
    input_params: Dict[str, Any],
    user_id: str = "legacy-shared",
) -> Dict[str, Any]:
    with _task_store_lock:
        if user_id != "legacy-shared":
            with SessionLocal() as db:
                try:
                    enforce_daily_quota(db, user_id, "video")
                except DailyQuotaError as exc:
                    raise TaskQuotaError(str(exc)) from exc
                pending_count = db.scalar(
                    select(func.count())
                    .select_from(TaskOwnership)
                    .where(
                        TaskOwnership.user_id == user_id,
                        TaskOwnership.task_kind == "pipeline",
                        TaskOwnership.status == "pending",
                    )
                ) or 0
            if pending_count >= MAX_PENDING_TASKS_PER_USER:
                raise TaskQuotaError(
                    f"待处理任务已达到上限（{MAX_PENDING_TASKS_PER_USER} 个），请等待现有任务完成。"
                )
        ensure_task_dirs()
        task_id = new_task_id()
        output_dir = task_output_dir(task_id)
        os.makedirs(output_dir, exist_ok=True)
        metadata = {
            "task_id": task_id,
            "pipeline": pipeline,
            "user_id": user_id,
            "status": "pending",
            "progress": 0,
            "message": "Task created",
            "input": input_params,
            "output": {},
            "artifacts": [],
            "error": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
            "output_dir": output_dir,
        }
        save_task(metadata)
        register_task(task_id, user_id, task_kind="pipeline")
    logger.info("Created pipeline task: task_id=%s pipeline=%s output_dir=%s", task_id, pipeline, output_dir)
    return metadata


def claim_next_pending_task() -> Optional[Dict[str, Any]]:
    """Atomically claim one queued pipeline task for a worker."""
    claimed: Optional[Dict[str, Any]] = None
    with SessionLocal.begin() as db:
        running_counts = dict(
            db.execute(
                select(TaskOwnership.user_id, func.count())
                .where(
                    TaskOwnership.task_kind == "pipeline",
                    TaskOwnership.status == "running",
                )
                .group_by(TaskOwnership.user_id)
            ).all()
        )
        candidates = db.scalars(
            select(TaskOwnership)
            .where(
                TaskOwnership.task_kind == "pipeline",
                TaskOwnership.status == "pending",
            )
            .order_by(TaskOwnership.created_at.asc())
            .with_for_update(skip_locked=True)
        ).all()
        for owner in candidates:
            if running_counts.get(owner.user_id, 0) >= MAX_CONCURRENT_TASKS_PER_USER:
                continue
            claimed = dict(owner.payload or {})
            claimed.update(
                status="running",
                progress=max(1, int(claimed.get("progress") or 0)),
                message="Task running",
                started_at=claimed.get("started_at") or now_iso(),
                updated_at=now_iso(),
            )
            owner.status = "running"
            owner.payload = claimed
            owner.updated_at = utcnow()
            break
    if claimed:
        with _task_store_lock:
            _write_task_file(claimed)
    return claimed


def recover_interrupted_tasks() -> int:
    """Return tasks left running by a stopped process to the durable queue."""
    recovered: list[Dict[str, Any]] = []
    with SessionLocal.begin() as db:
        owners = db.scalars(
            select(TaskOwnership).where(
                TaskOwnership.task_kind == "pipeline",
                TaskOwnership.status == "running",
            )
        ).all()
        for owner in owners:
            payload = dict(owner.payload or {})
            payload.update(
                status="pending",
                progress=0,
                message="Task recovered after service restart",
                started_at=None,
                updated_at=now_iso(),
                retry_count=int(payload.get("retry_count") or 0) + 1,
            )
            owner.status = "pending"
            owner.payload = payload
            owner.updated_at = utcnow()
            recovered.append(payload)
    with _task_store_lock:
        for metadata in recovered:
            _write_task_file(metadata)
    return len(recovered)


def update_task(task_id: str, **updates: Any) -> Dict[str, Any]:
    with _task_store_lock:
        metadata = load_task(task_id)
        if not metadata:
            raise FileNotFoundError(f"Task not found: {task_id}")
        metadata.update(updates)
        metadata["updated_at"] = now_iso()
        save_task(metadata)
    if "progress" in updates or "status" in updates:
        logger.info(
            "Task update: task_id=%s status=%s progress=%s message=%s",
            task_id,
            metadata.get("status"),
            metadata.get("progress"),
            metadata.get("message"),
        )
    publish_task_event(task_id, {
        "type": "progress",
        "status": metadata.get("status"),
        "progress": metadata.get("progress", 0),
    })
    return metadata


def append_artifact(task_id: str, new_artifact: Dict[str, Any]) -> Dict[str, Any]:
    with _task_store_lock:
        metadata = load_task(task_id)
        if not metadata:
            raise FileNotFoundError(f"Task not found: {task_id}")

        if not new_artifact.get("created_at"):
            new_artifact = {**new_artifact, "created_at": now_iso()}

        artifacts = list(metadata.get("artifacts") or [])
        key = (new_artifact.get("kind"), new_artifact.get("name"), new_artifact.get("path"))
        if not any((item.get("kind"), item.get("name"), item.get("path")) == key for item in artifacts):
            artifacts.append(new_artifact)
            logger.info(
                "Task artifact: task_id=%s kind=%s name=%s path=%s",
                task_id,
                new_artifact.get("kind"),
                new_artifact.get("name"),
                new_artifact.get("path"),
            )
        metadata["artifacts"] = artifacts
        metadata["updated_at"] = now_iso()
        save_task(metadata)
    publish_task_event(task_id, {
        "type": "artifact",
        "status": metadata.get("status"),
        "progress": metadata.get("progress", 0),
        "artifact": new_artifact,
    })
    return metadata


def mark_running(task_id: str) -> Dict[str, Any]:
    return update_task(task_id, status="running", progress=1, message="Task running", started_at=now_iso())


def mark_completed(task_id: str, output: Dict[str, Any], artifacts: list[Dict[str, Any]]) -> Dict[str, Any]:
    metadata = load_task(task_id) or {"task_id": task_id}
    started_at = metadata.get("started_at")
    duration = None
    if started_at:
        try:
            duration = time.time() - datetime.fromisoformat(started_at).timestamp()
        except Exception:
            duration = None
    existing_artifacts = list(metadata.get("artifacts") or [])
    merged_artifacts = list(existing_artifacts)
    seen = {
        (item.get("kind"), item.get("name"), item.get("path"))
        for item in merged_artifacts
    }
    for item in artifacts or []:
        key = (item.get("kind"), item.get("name"), item.get("path"))
        if key in seen:
            continue
        merged_artifacts.append({**item, "created_at": item.get("created_at") or now_iso()})
        seen.add(key)

    metadata = update_task(
        task_id,
        status="completed",
        progress=100,
        message="Task completed",
        output=output,
        artifacts=merged_artifacts,
        error=None,
        completed_at=now_iso(),
        duration_seconds=duration,
    )
    publish_task_event(task_id, {
        "type": "completed",
        "status": "completed",
        "progress": 100,
    })
    return metadata


def mark_failed(task_id: str, error: str) -> Dict[str, Any]:
    metadata = update_task(
        task_id,
        status="failed",
        message="Task failed",
        error=error,
        completed_at=now_iso(),
    )
    publish_task_event(task_id, {
        "type": "failed",
        "status": "failed",
        "progress": metadata.get("progress", 0),
    })
    return metadata
