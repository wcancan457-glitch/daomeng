"""Small, dependency-free security layer for the public API deployment."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from accounts.database import SessionLocal
from accounts.ownership import asset_path_owned_by
from accounts.service import validate_session
from accounts.tokens import TokenError, decode_access_token, tokens_configured


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _split_origins(value: str) -> list[str]:
    return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]


_legacy_auth_required = _env_bool("AUTH_REQUIRED", False)
AUTH_MODE = os.getenv("AUTH_MODE", "shared" if _legacy_auth_required else "disabled").strip().lower()
if AUTH_MODE not in {"disabled", "shared", "users"}:
    AUTH_MODE = "shared" if _legacy_auth_required else "disabled"
AUTH_REQUIRED = AUTH_MODE != "disabled"
ACCESS_PASSWORD = os.getenv("APP_ACCESS_PASSWORD", "")
REGISTRATION_ENABLED = _env_bool("REGISTRATION_ENABLED", True)
TOKEN_TTL_SECONDS = _env_int("AUTH_TOKEN_TTL_SECONDS", 24 * 60 * 60, 300)
RATE_LIMIT_PER_MINUTE = _env_int("API_RATE_LIMIT_PER_MINUTE", 60, 5)
AUTH_RATE_LIMIT_PER_MINUTE = _env_int("AUTH_RATE_LIMIT_PER_MINUTE", 10, 3)
MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_BYTES", 25 * 1024 * 1024, 1024 * 1024)
ALLOWED_ORIGINS = _split_origins(
    os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
)

PUBLIC_API_PATHS = {
    "/api/health",
    "/api/health/ready",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/refresh",
    "/api/auth/register",
    "/api/auth/status",
}


def auth_is_configured() -> bool:
    if AUTH_MODE == "disabled":
        return True
    if AUTH_MODE == "users":
        return tokens_configured()
    return bool(ACCESS_PASSWORD)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(payload: str) -> str:
    key = hashlib.sha256(ACCESS_PASSWORD.encode("utf-8")).digest()
    return _b64encode(hmac.new(key, payload.encode("ascii"), hashlib.sha256).digest())


def verify_password(candidate: str) -> bool:
    if not ACCESS_PASSWORD:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), ACCESS_PASSWORD.encode("utf-8"))


def create_access_token() -> str:
    now = int(time.time())
    payload = _b64encode(
        json.dumps(
            {"iat": now, "exp": now + TOKEN_TTL_SECONDS, "nonce": secrets.token_hex(8)},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return f"{payload}.{_sign(payload)}"


def verify_access_token(token: str) -> bool:
    if not token or not ACCESS_PASSWORD:
        return False
    try:
        payload, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, _sign(payload)):
            return False
        claims = json.loads(_b64decode(payload))
        return int(claims.get("exp", 0)) > int(time.time())
    except (ValueError, TypeError, json.JSONDecodeError):
        return False


def _request_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    cookie_token = request.cookies.get("daomeng_access", "")
    if cookie_token:
        return cookie_token
    # Native EventSource cannot set request headers, so streaming endpoints may
    # temporarily retain compatibility with older clients that used a query token.
    return request.query_params.get("access_token", "")


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._requests: Dict[str, Deque[float]] = defaultdict(deque)

    def _rate_limited(self, request: Request) -> bool:
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return False
        client = request.client.host if request.client else "unknown"
        is_auth_attempt = request.url.path in {
            "/api/auth/login",
            "/api/auth/register",
            "/api/auth/refresh",
        }
        limit = AUTH_RATE_LIMIT_PER_MINUTE if is_auth_attempt else RATE_LIMIT_PER_MINUTE
        key = f"{client}:{'auth' if is_auth_attempt else 'mutation'}"
        now = time.monotonic()
        bucket = self._requests[key]
        while bucket and bucket[0] <= now - 60:
            bucket.popleft()
        if len(bucket) >= limit:
            return True
        bucket.append(now)
        return False

    @staticmethod
    def _with_security_headers(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        if request.method == "OPTIONS":
            return self._with_security_headers(await call_next(request))

        if path.startswith("/api/") and self._rate_limited(request):
            return self._with_security_headers(
                JSONResponse({"detail": "请求过于频繁，请稍后再试。"}, status_code=429)
            )

        if request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > MAX_UPLOAD_BYTES:
                        return self._with_security_headers(
                            JSONResponse({"detail": "上传内容超过大小限制。"}, status_code=413)
                        )
                except ValueError:
                    pass

        protected_path = path.startswith("/api/") or path.startswith("/code/")
        needs_auth = protected_path and path not in PUBLIC_API_PATHS
        if AUTH_REQUIRED and needs_auth:
            if not auth_is_configured():
                return self._with_security_headers(
                    JSONResponse(
                        {"detail": "服务尚未配置访问密码，请联系管理员。"},
                        status_code=503,
                    )
                )
            token = _request_token(request)
            if AUTH_MODE == "shared":
                if not verify_access_token(token):
                    return self._with_security_headers(
                        JSONResponse({"detail": "登录已失效，请重新登录。"}, status_code=401)
                    )
            elif AUTH_MODE == "users":
                try:
                    claims = decode_access_token(token)
                    user_id = str(claims.get("sub") or "")
                    session_id = str(claims.get("sid") or "")
                    with SessionLocal() as db:
                        user = validate_session(db, session_id, user_id)
                    if not user:
                        raise TokenError("Session is no longer active.")
                    if path.startswith("/code/") and not asset_path_owned_by(
                        path[len("/code/"):], user.id
                    ):
                        return self._with_security_headers(
                            JSONResponse({"detail": "资源不存在。"}, status_code=404)
                        )
                    request.state.user_id = user.id
                    request.state.user_role = user.role
                    request.state.auth_session_id = session_id
                except (TokenError, ValueError, TypeError):
                    return self._with_security_headers(
                        JSONResponse({"detail": "登录已失效，请重新登录。"}, status_code=401)
                    )

        return self._with_security_headers(await call_next(request))
