from __future__ import annotations

from sqlalchemy import select

from accounts.database import SessionLocal
from accounts.models import ProjectOwnership, TaskOwnership, utcnow

LEGACY_OWNER_ID = "legacy-shared"


def register_project(project_id: str, user_id: str) -> None:
    if user_id == LEGACY_OWNER_ID:
        return
    with SessionLocal.begin() as db:
        owner = db.get(ProjectOwnership, project_id)
        if owner:
            if owner.user_id != user_id:
                raise PermissionError("Project already belongs to another user.")
            return
        db.add(ProjectOwnership(project_id=project_id, user_id=user_id))


def save_project_payload(project_id: str, user_id: str, payload: dict) -> None:
    if user_id == LEGACY_OWNER_ID:
        return
    with SessionLocal.begin() as db:
        owner = db.get(ProjectOwnership, project_id)
        if not owner:
            owner = ProjectOwnership(project_id=project_id, user_id=user_id)
            db.add(owner)
        elif owner.user_id != user_id:
            raise PermissionError("Project belongs to another user.")
        owner.payload = payload


def load_project_payload(project_id: str) -> dict | None:
    with SessionLocal() as db:
        owner = db.get(ProjectOwnership, project_id)
        return dict(owner.payload) if owner and owner.payload else None


def all_project_payloads() -> list[dict]:
    with SessionLocal() as db:
        return [dict(payload) for payload in db.scalars(select(ProjectOwnership.payload)) if payload]


def project_owned_by(project_id: str, user_id: str) -> bool:
    with SessionLocal() as db:
        owner = db.get(ProjectOwnership, project_id)
        if owner:
            return owner.user_id == user_id
        return user_id == LEGACY_OWNER_ID


def project_ids_for_user(user_id: str) -> set[str]:
    with SessionLocal() as db:
        return set(db.scalars(select(ProjectOwnership.project_id).where(ProjectOwnership.user_id == user_id)))


def delete_project_ownership(project_id: str, user_id: str) -> None:
    if user_id == LEGACY_OWNER_ID:
        return
    with SessionLocal.begin() as db:
        owner = db.get(ProjectOwnership, project_id)
        if owner and owner.user_id == user_id:
            db.delete(owner)


def register_task(task_id: str, user_id: str, task_kind: str = "pipeline") -> None:
    if user_id == LEGACY_OWNER_ID:
        return
    with SessionLocal.begin() as db:
        owner = db.get(TaskOwnership, task_id)
        if owner:
            if owner.user_id != user_id:
                raise PermissionError("Task already belongs to another user.")
            return
        db.add(TaskOwnership(task_id=task_id, user_id=user_id, task_kind=task_kind))


def save_task_payload(task_id: str, user_id: str, payload: dict, task_kind: str = "pipeline") -> None:
    if user_id == LEGACY_OWNER_ID:
        return
    with SessionLocal.begin() as db:
        owner = db.get(TaskOwnership, task_id)
        if not owner:
            owner = TaskOwnership(
                task_id=task_id,
                user_id=user_id,
                task_kind=task_kind,
                status=str(payload.get("status") or "pending"),
            )
            db.add(owner)
        elif owner.user_id != user_id:
            raise PermissionError("Task belongs to another user.")
        owner.status = str(payload.get("status") or owner.status or "pending")
        owner.payload = payload
        owner.updated_at = utcnow()


def load_task_payload(task_id: str) -> dict | None:
    with SessionLocal() as db:
        owner = db.get(TaskOwnership, task_id)
        return dict(owner.payload) if owner and owner.payload else None


def task_payloads_for_user(user_id: str, task_kind: str = "pipeline") -> list[dict]:
    with SessionLocal() as db:
        statement = select(TaskOwnership.payload).where(
            TaskOwnership.user_id == user_id,
            TaskOwnership.task_kind == task_kind,
        )
        return [dict(payload) for payload in db.scalars(statement) if payload]


def task_owned_by(task_id: str, user_id: str) -> bool:
    with SessionLocal() as db:
        owner = db.get(TaskOwnership, task_id)
        if owner:
            return owner.user_id == user_id
        return user_id == LEGACY_OWNER_ID


def task_ids_for_user(user_id: str, task_kind: str | None = None) -> set[str]:
    with SessionLocal() as db:
        statement = select(TaskOwnership.task_id).where(TaskOwnership.user_id == user_id)
        if task_kind:
            statement = statement.where(TaskOwnership.task_kind == task_kind)
        return set(db.scalars(statement))


def delete_task_ownership(task_id: str, user_id: str) -> None:
    if user_id == LEGACY_OWNER_ID:
        return
    with SessionLocal.begin() as db:
        owner = db.get(TaskOwnership, task_id)
        if owner and owner.user_id == user_id:
            db.delete(owner)


def asset_path_owned_by(relative_path: str, user_id: str) -> bool:
    normalized = relative_path.replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part]
    if not parts or ".." in parts or parts[0] == "data":
        return False
    if user_id == LEGACY_OWNER_ID:
        return parts[0] == "result"
    if parts[0] != "result":
        return False
    if user_id in parts:
        return True

    owned_ids = project_ids_for_user(user_id) | task_ids_for_user(user_id)
    for owner_id in owned_ids:
        if any(
            part == owner_id
            or part == f"{owner_id}.json"
            or part.startswith(f"{owner_id}_")
            for part in parts
        ):
            return True
    return False
