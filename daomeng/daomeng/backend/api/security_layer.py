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


AUTH_REQUIRED = _env_bool("AUTH_REQUIRED", False)
ACCESS_PASSWORD = os.getenv("APP_ACCESS_PASSWORD", "")
TOKEN_TTL_SECONDS = _env_int("AUTH_TOKEN_TTL_SECONDS", 24 * 60 * 60, 300)
RATE_LIMIT_PER_MINUTE = _env_int("API_RATE_LIMIT_PER_MINUTE", 60, 5)
MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_BYTES", 25 * 1024 * 1024, 1024 * 1024)
ALLOWED_ORIGINS = _split_origins(
    os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
)

PUBLIC_API_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/status",
}


def auth_is_configured() -> bool:
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
    # Native EventSource cannot set request headers, so streaming endpoints may
    # pass the same short-lived token in the query string.
    return request.query_params.get("access_token", "")


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._requests: Dict[str, Deque[float]] = defaultdict(deque)

    def _rate_limited(self, request: Request) -> bool:
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return False
        client = request.client.host if request.client else "unknown"
        key = f"{client}:{request.url.path}"
        now = time.monotonic()
        bucket = self._requests[key]
        while bucket and bucket[0] <= now - 60:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_PER_MINUTE:
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

        needs_auth = path.startswith("/api/") and path not in PUBLIC_API_PATHS
        if AUTH_REQUIRED and needs_auth:
            if not auth_is_configured():
                return self._with_security_headers(
                    JSONResponse(
                        {"detail": "服务尚未配置访问密码，请联系管理员。"},
                        status_code=503,
                    )
                )
            if not verify_access_token(_request_token(request)):
                return self._with_security_headers(
                    JSONResponse({"detail": "登录已失效，请重新登录。"}, status_code=401)
                )

        return self._with_security_headers(await call_next(request))
