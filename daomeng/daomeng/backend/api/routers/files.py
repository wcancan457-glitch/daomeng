import logging
import os
import re
import shutil
import time
import uuid
import zipfile
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from PIL import Image, UnidentifiedImageError

from accounts.ownership import asset_path_owned_by
from api.auth_context import request_user_id, require_admin
from api.security_layer import MAX_UPLOAD_BYTES
from config import settings
from models.file_reader import FileReader

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Files"])


def _positive_env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default

DOCUMENT_EXTENSIONS = {".docx", ".doc", ".txt", ".md", ".pdf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
MEDIA_PARAM_KEYS = {
    "image_path",
    "video_path",
    "character_image_path",
    "goods_image_path",
    "image_asset",
    "video_asset",
    "character_asset",
    "goods_asset",
}
MAX_USER_TEMP_BYTES = _positive_env_int(
    "MAX_USER_TEMP_BYTES",
    250 * 1024 * 1024,
    MAX_UPLOAD_BYTES,
)


def _path_size(path: str) -> int:
    if os.path.isfile(path) or os.path.islink(path):
        return os.path.getsize(path)
    total = 0
    for root, dirs, files in os.walk(path):
        for name in files:
            item = os.path.join(root, name)
            try:
                total += os.path.getsize(item)
            except OSError:
                continue
        for name in dirs:
            item = os.path.join(root, name)
            if os.path.islink(item):
                try:
                    total += os.path.getsize(item)
                except OSError:
                    continue
    return total


def _safe_filename(filename: str, extension: str) -> str:
    stem = os.path.splitext(os.path.basename(filename))[0]
    stem = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", stem, flags=re.UNICODE).strip("_")
    return f"{(stem or 'upload')[:80]}{extension}"


async def _save_upload(file: UploadFile, destination: str, byte_limit: int = MAX_UPLOAD_BYTES) -> None:
    written = 0
    try:
        with open(destination, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > byte_limit:
                    raise HTTPException(status_code=413, detail="上传内容超过单文件或个人空间限制。")
                buffer.write(chunk)
    except Exception:
        if os.path.exists(destination):
            os.remove(destination)
        raise
    if written == 0:
        os.remove(destination)
        raise HTTPException(status_code=400, detail="上传文件不能为空。")


def _validate_document(path: str, extension: str) -> None:
    try:
        with open(path, "rb") as source:
            header = source.read(16)
        if extension == ".pdf" and not header.startswith(b"%PDF-"):
            raise ValueError("PDF 文件头无效")
        if extension == ".doc" and not header.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            raise ValueError("DOC 文件头无效")
        if extension == ".docx":
            if not zipfile.is_zipfile(path):
                raise ValueError("DOCX 压缩结构无效")
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise ValueError("DOCX 文档结构无效")
        if extension in {".txt", ".md"}:
            with open(path, "rb") as source:
                content = source.read()
            for encoding in ("utf-8-sig", "gb18030"):
                try:
                    content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError("文本编码不受支持")
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=400, detail=f"文件内容与扩展名不匹配：{exc}") from exc


def _validate_media(path: str, extension: str) -> None:
    try:
        if extension in IMAGE_EXTENSIONS:
            with Image.open(path) as image:
                image.verify()
            return
        with open(path, "rb") as source:
            header = source.read(16)
        valid = (
            extension in {".mp4", ".mov"} and len(header) >= 8 and header[4:8] == b"ftyp"
        ) or (
            extension == ".avi"
            and header.startswith(b"RIFF")
            and len(header) >= 12
            and header[8:12] == b"AVI "
        ) or (extension in {".mkv", ".webm"} and header.startswith(bytes.fromhex("1A45DFA3")))
        if not valid:
            raise ValueError("媒体文件头无效")
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise HTTPException(status_code=400, detail=f"媒体内容与扩展名不匹配：{exc}") from exc


def _user_temp_path(user_id: str, file_key: str) -> str:
    user_root = os.path.abspath(os.path.join(settings.TEMP_DIR, user_id))
    candidate = file_key
    if not os.path.isabs(candidate):
        candidate = os.path.join(settings.TEMP_DIR, candidate)
    candidate = os.path.abspath(candidate)
    if os.path.commonpath([candidate, user_root]) != user_root or not os.path.isfile(candidate):
        raise ValueError("上传媒体不存在或不属于当前用户。")
    return candidate


def resolve_user_media_path(file_key: str, user_id: str) -> str:
    value = str(file_key or "").strip()
    if not value:
        return value
    if value.startswith(("https://", "http://", "data:")):
        return value
    normalized = value.replace("\\", "/")
    if normalized.startswith("/code/"):
        normalized = normalized[len("/code/"):]
    if normalized.startswith("result/"):
        if not asset_path_owned_by(normalized, user_id):
            raise ValueError("生成媒体不存在或不属于当前用户。")
        candidate = os.path.abspath(os.path.join(settings.CODE_DIR, normalized))
        if os.path.commonpath([candidate, os.path.abspath(settings.CODE_DIR)]) != os.path.abspath(
            settings.CODE_DIR
        ) or not os.path.isfile(candidate):
            raise ValueError("生成媒体不存在或不属于当前用户。")
        return candidate
    return _user_temp_path(user_id, value)


def resolve_uploaded_media_params(params: dict, user_id: str) -> dict:
    resolved = dict(params)
    for key in MEDIA_PARAM_KEYS:
        if resolved.get(key):
            resolved[key] = resolve_user_media_path(str(resolved[key]), user_id)
    return resolved


@router.post("/api/upload_file")
async def upload_file(request: Request, file: UploadFile = File(...)):
    user_id = request_user_id(request)
    filename = os.path.basename(file.filename or "upload")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"仅支持 {', '.join(sorted(DOCUMENT_EXTENSIONS))} 格式的文件")

    user_temp_dir = os.path.join(settings.TEMP_DIR, user_id)
    os.makedirs(user_temp_dir, exist_ok=True)
    remaining_bytes = MAX_USER_TEMP_BYTES - _path_size(user_temp_dir)
    if remaining_bytes <= 0:
        raise HTTPException(status_code=413, detail="个人上传空间已满，请先删除不再使用的任务或联系管理员。")
    safe_filename = f"{int(time.time())}_{uuid.uuid4().hex[:10]}_{_safe_filename(filename, ext)}"
    file_path = os.path.join(user_temp_dir, safe_filename)
    try:
        await _save_upload(file, file_path, min(MAX_UPLOAD_BYTES, remaining_bytes))
        _validate_document(file_path, ext)
    except HTTPException:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise
    except Exception as e:
        logger.exception("保存上传文件失败")
        raise HTTPException(status_code=500, detail="文件保存失败。") from e

    return {"filename": filename, "file_path": f"{user_id}/{safe_filename}"}


@router.post("/api/upload_media")
async def upload_media(request: Request, file: UploadFile = File(...)):
    user_id = request_user_id(request)
    filename = os.path.basename(file.filename or "upload")
    ext = os.path.splitext(filename)[1].lower()
    allowed_extensions = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"仅支持 {', '.join(sorted(allowed_extensions))} 格式的媒体文件")

    user_temp_dir = os.path.join(settings.TEMP_DIR, user_id)
    os.makedirs(user_temp_dir, exist_ok=True)
    remaining_bytes = MAX_USER_TEMP_BYTES - _path_size(user_temp_dir)
    if remaining_bytes <= 0:
        raise HTTPException(status_code=413, detail="个人上传空间已满，请先删除不再使用的任务或联系管理员。")
    safe_filename = f"{int(time.time())}_{uuid.uuid4().hex[:10]}_{_safe_filename(filename, ext)}"
    file_path = os.path.join(user_temp_dir, safe_filename)
    try:
        await _save_upload(file, file_path, min(MAX_UPLOAD_BYTES, remaining_bytes))
        _validate_media(file_path, ext)
    except HTTPException:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise
    except Exception as e:
        logger.exception("保存上传媒体失败")
        raise HTTPException(status_code=500, detail="媒体保存失败。") from e

    return {
        "filename": filename,
        "file_path": f"{user_id}/{safe_filename}",
    }


@router.delete("/api/cache/temp")
async def clear_temp_cache(request: Request):
    require_admin(request)
    os.makedirs(settings.TEMP_DIR, exist_ok=True)
    deleted = 0
    freed_bytes = 0
    errors = []
    for entry in os.scandir(settings.TEMP_DIR):
        try:
            freed_bytes += _path_size(entry.path)
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.remove(entry.path)
            deleted += 1
        except Exception as exc:
            logger.warning("Failed to delete temp cache item: %s", entry.path, exc_info=True)
            errors.append({"path": entry.name, "error": str(exc)})
    return {
        "status": "ok",
        "deleted": deleted,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / 1024 / 1024, 2),
        "errors": errors,
    }


def merge_uploaded_file_into_idea(idea: str, file_path: Optional[str], user_id: str) -> str:
    if not file_path:
        return idea

    relative_path = os.path.normpath(file_path)
    expected_prefix = os.path.normpath(user_id) + os.sep
    if not relative_path.startswith(expected_prefix) or os.path.isabs(relative_path):
        raise ValueError("上传文件不属于当前用户。")
    full_path = os.path.abspath(os.path.join(settings.TEMP_DIR, relative_path))
    temp_root = os.path.abspath(settings.TEMP_DIR)
    if os.path.commonpath([full_path, temp_root]) != temp_root:
        raise ValueError("上传文件路径无效。")
    if not os.path.exists(full_path):
        logger.warning(f"上传的文件未找到: {full_path}")
        return idea

    content = FileReader.extract_text(full_path)
    if content:
        original_filename = "_".join(file_path.split("_")[1:])
        prompt_fragment = FileReader.format_as_prompt(original_filename, content)
        idea = f"{idea}\n\n{prompt_fragment}"
    logger.info(f"成功处理上传文件: {full_path}")
    logger.debug(f"文件内容预览:\n{content[:500]}")
    return idea
