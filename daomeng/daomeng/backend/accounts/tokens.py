from __future__ import annotations

import hashlib
import os
import secrets
import time
import uuid
from typing import Any, Dict

import jwt

ACCESS_TOKEN_TTL_SECONDS = max(300, int(os.getenv("AUTH_ACCESS_TOKEN_TTL_SECONDS", "900")))
REFRESH_TOKEN_TTL_SECONDS = max(3600, int(os.getenv("AUTH_REFRESH_TOKEN_TTL_SECONDS", str(30 * 86400))))
AUTH_TOKEN_SECRET = os.getenv("AUTH_TOKEN_SECRET", "").strip()
TOKEN_ISSUER = "daomeng-api"
TOKEN_AUDIENCE = "daomeng-web"


class TokenError(ValueError):
    pass


def tokens_configured() -> bool:
    return len(AUTH_TOKEN_SECRET) >= 32


def create_access_token(user_id: str, session_id: str, role: str) -> str:
    if not tokens_configured():
        raise RuntimeError("AUTH_TOKEN_SECRET must contain at least 32 characters.")
    now = int(time.time())
    payload = {
        "sub": user_id,
        "sid": session_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL_SECONDS,
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, AUTH_TOKEN_SECRET, algorithm="HS256")


def decode_access_token(token: str) -> Dict[str, Any]:
    if not tokens_configured():
        raise TokenError("Authentication is not configured.")
    try:
        claims = jwt.decode(
            token,
            AUTH_TOKEN_SECRET,
            algorithms=["HS256"],
            audience=TOKEN_AUDIENCE,
            issuer=TOKEN_ISSUER,
            options={"require": ["exp", "iat", "sub", "sid", "type"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired access token.") from exc
    if claims.get("type") != "access":
        raise TokenError("Invalid token type.")
    return claims


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

