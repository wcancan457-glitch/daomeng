from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, select

from accounts.database import SessionLocal
from accounts.models import ProjectMediaAsset

logger = logging.getLogger(__name__)

MEDIA_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".mp4",
    ".mov",
    ".webm",
    ".mp3",
    ".wav",
    ".m4a",
}


def _positive_env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


MAX_FILE_BYTES = _positive_env_int("DATABASE_MEDIA_MAX_FILE_BYTES", 100 * 1024 * 1024)
MAX_PROJECT_BYTES = _positive_env_int("DATABASE_MEDIA_MAX_PROJECT_BYTES", 500 * 1024 * 1024)


def _enabled() -> bool:
    return os.getenv("MEDIA_PERSISTENCE_MODE", "database").strip().lower() == "database"


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_strings(item)


def _relative_media_path(value: str, project_id: str) -> str | None:
    from config import settings

    raw = str(value or "").strip()
    if not raw or raw.startswith(("http://", "https://", "data:", "blob:")):
        return None

    normalized = raw.replace("\\", "/")
    lower = normalized.lower()
    marker = lower.rfind("/code/")
    if marker >= 0:
        normalized = normalized[marker + len("/code/"):]
    elif lower.startswith("code/"):
        normalized = normalized[len("code/"):]
    elif os.path.isabs(raw):
        try:
            normalized = os.path.relpath(os.path.abspath(raw), settings.CODE_DIR).replace("\\", "/")
        except ValueError:
            return None

    normalized = normalized.lstrip("/")
    parts = [part for part in normalized.split("/") if part]
    if not parts or parts[0] != "result" or ".." in parts:
        return None
    if project_id not in parts and not any(part.startswith(f"{project_id}.") for part in parts):
        return None
    if Path(normalized).suffix.lower() not in MEDIA_EXTENSIONS:
        return None
    return "/".join(parts)


def _absolute_media_path(relative_path: str) -> str:
    from config import settings

    candidate = os.path.abspath(os.path.join(settings.CODE_DIR, relative_path.replace("/", os.sep)))
    code_root = os.path.abspath(settings.CODE_DIR)
    if os.path.commonpath([candidate, code_root]) != code_root:
        raise ValueError("媒体路径超出运行目录。")
    return candidate


def artifact_media_paths(project_id: str, payload: Any) -> set[str]:
    return {
        relative
        for value in _iter_strings(payload)
        if (relative := _relative_media_path(value, project_id))
    }


def persist_project_media(project_id: str, payload: Any) -> dict[str, int]:
    if not _enabled():
        return {"persisted": 0, "skipped": 0}

    persisted = 0
    skipped = 0
    paths = artifact_media_paths(project_id, payload)
    with SessionLocal.begin() as db:
        current_total = int(
            db.scalar(
                select(func.coalesce(func.sum(ProjectMediaAsset.size_bytes), 0)).where(
                    ProjectMediaAsset.project_id == project_id
                )
            )
            or 0
        )
        for relative_path in sorted(paths):
            absolute_path = _absolute_media_path(relative_path)
            if not os.path.isfile(absolute_path):
                continue
            size = os.path.getsize(absolute_path)
            if size <= 0 or size > MAX_FILE_BYTES:
                logger.warning("Media persistence skipped by file limit: %s (%s bytes)", relative_path, size)
                skipped += 1
                continue

            existing = db.get(ProjectMediaAsset, (project_id, relative_path))
            if existing and existing.size_bytes == size:
                continue
            previous_size = existing.size_bytes if existing else 0
            if current_total - previous_size + size > MAX_PROJECT_BYTES:
                logger.warning("Media persistence skipped by project limit: %s", relative_path)
                skipped += 1
                continue

            with open(absolute_path, "rb") as source:
                content = source.read()
            digest = hashlib.sha256(content).hexdigest()
            if existing and existing.sha256 == digest:
                existing.size_bytes = size
                continue

            content_type = mimetypes.guess_type(relative_path)[0] or "application/octet-stream"
            if existing:
                existing.content = content
                existing.content_type = content_type
                existing.size_bytes = size
                existing.sha256 = digest
            else:
                db.add(ProjectMediaAsset(
                    project_id=project_id,
                    relative_path=relative_path,
                    content_type=content_type,
                    size_bytes=size,
                    sha256=digest,
                    content=content,
                ))
            current_total = current_total - previous_size + size
            persisted += 1
    return {"persisted": persisted, "skipped": skipped}


def restore_project_media(project_id: str, payload: Any) -> dict[str, Any]:
    paths = artifact_media_paths(project_id, payload)
    missing = []
    restored = 0
    if not paths:
        return {"restored": 0, "missing": []}

    absent_paths = []
    for relative_path in sorted(paths):
        if not os.path.isfile(_absolute_media_path(relative_path)):
            absent_paths.append(relative_path)
    if not absent_paths:
        return {"restored": 0, "missing": []}
    if not _enabled():
        return {"restored": 0, "missing": absent_paths}

    with SessionLocal() as db:
        records = {
            record.relative_path: record
            for record in db.scalars(
                select(ProjectMediaAsset).where(
                    ProjectMediaAsset.project_id == project_id,
                    ProjectMediaAsset.relative_path.in_(absent_paths),
                )
            )
        }
        for relative_path in absent_paths:
            record = records.get(relative_path)
            if not record:
                missing.append(relative_path)
                continue
            absolute_path = _absolute_media_path(relative_path)
            os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
            fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(absolute_path), suffix=".restore")
            try:
                with os.fdopen(fd, "wb") as destination:
                    destination.write(record.content)
                os.replace(temp_path, absolute_path)
                restored += 1
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
    return {"restored": restored, "missing": missing}


def restore_media_path(relative_path: str) -> str | None:
    """Restore one authenticated generated asset on demand after an ephemeral-disk restart."""
    normalized = str(relative_path or "").replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part]
    if not parts or parts[0] != "result" or ".." in parts:
        return None

    absolute_path = _absolute_media_path(normalized)
    if os.path.isfile(absolute_path):
        return absolute_path
    if Path(normalized).suffix.lower() not in MEDIA_EXTENSIONS:
        return None
    if not _enabled():
        return None

    with SessionLocal() as db:
        record = db.scalar(
            select(ProjectMediaAsset).where(ProjectMediaAsset.relative_path == normalized)
        )
        if not record or not record.content:
            return None
        content = bytes(record.content)

    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(absolute_path), suffix=".restore")
    try:
        with os.fdopen(fd, "wb") as destination:
            destination.write(content)
        os.replace(temp_path, absolute_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return absolute_path


def resolve_media_file(value: str) -> str | None:
    """Resolve a persisted artifact path across local and container layouts.

    Old workflow snapshots can contain absolute paths from an earlier Render
    runtime. Prefer an existing path, then map anything after ``/code/`` into
    the current runtime and finally rehydrate the file from database storage.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith(("http://", "https://", "data:")):
        return raw

    normalized = raw.replace("\\", "/")
    candidates: list[str] = []
    relative_path = ""
    if os.path.isabs(raw):
        candidates.append(os.path.abspath(raw))

    lower = normalized.lower()
    marker = lower.rfind("/code/")
    if marker >= 0:
        relative_path = normalized[marker + len("/code/"):].lstrip("/")
    elif lower.startswith("code/"):
        relative_path = normalized[len("code/"):].lstrip("/")
    elif lower.startswith("result/"):
        relative_path = normalized.lstrip("/")
    elif not os.path.isabs(raw):
        candidates.append(os.path.abspath(raw))

    if relative_path:
        candidates.append(_absolute_media_path(relative_path))

    for candidate in dict.fromkeys(candidates):
        if os.path.isfile(candidate):
            return candidate

    if relative_path:
        return restore_media_path(relative_path)
    return None
