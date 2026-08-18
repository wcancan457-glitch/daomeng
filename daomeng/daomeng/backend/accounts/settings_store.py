from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from accounts.models import SystemSetting

logger = logging.getLogger(__name__)

MODEL_CONFIG_KEY = "model_gateway_config_v1"


def _local_key_path() -> Path:
    backend_dir = Path(__file__).resolve().parents[1]
    data_root = Path(os.getenv("RUNTIME_DATA_DIR", str(backend_dir))).resolve()
    return data_root / "data" / ".settings-key"


def _key_material() -> str:
    for name in (
        "SETTINGS_ENCRYPTION_KEY",
        "AUTH_TOKEN_SECRET",
        "AUTH_SECRET_KEY",
        "APP_ACCESS_PASSWORD",
    ):
        value = os.getenv(name, "").strip()
        if value:
            return f"{name}:{value}"

    key_path = _local_key_path()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key_path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        try:
            key_path.chmod(0o600)
        except OSError:
            logger.warning("Could not restrict local settings key permissions: %s", key_path)
    return f"local:{key_path.read_text(encoding='utf-8').strip()}"


def _fernet() -> Fernet:
    digest = hashlib.sha256(_key_material().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def load_runtime_config(db: Session) -> dict[str, Any] | None:
    record = db.get(SystemSetting, MODEL_CONFIG_KEY)
    if not record:
        return None
    try:
        plaintext = _fernet().decrypt(record.encrypted_value.encode("ascii"))
        values = json.loads(plaintext.decode("utf-8"))
        return values if isinstance(values, dict) else None
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        logger.exception("Stored model gateway configuration could not be decrypted")
        return None


def save_runtime_config(db: Session, values: dict[str, Any], actor_id: str) -> None:
    plaintext = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encrypted = _fernet().encrypt(plaintext).decode("ascii")
    record = db.get(SystemSetting, MODEL_CONFIG_KEY)
    if record:
        record.encrypted_value = encrypted
        record.updated_by = actor_id
    else:
        db.add(
            SystemSetting(
                key=MODEL_CONFIG_KEY,
                encrypted_value=encrypted,
                updated_by=actor_id,
            )
        )
    db.commit()
