from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from accounts.database import get_db
from accounts.models import User
from accounts.service import (
    AccountError,
    AuthenticationError,
    DuplicateEmailError,
    authenticate_user,
    create_user,
    issue_session,
    revoke_session,
    rotate_session,
    serialize_user,
)
from accounts.tokens import ACCESS_TOKEN_TTL_SECONDS, REFRESH_TOKEN_TTL_SECONDS
from api.security_layer import (
    AUTH_MODE,
    AUTH_REQUIRED,
    REGISTRATION_ENABLED,
    TOKEN_TTL_SECONDS,
    auth_is_configured,
    verify_password,
)
from api.security_layer import (
    create_access_token as create_shared_access_token,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

REFRESH_COOKIE_NAME = "daomeng_refresh"
ACCESS_COOKIE_NAME = "daomeng_access"
COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes", "on"}
if "AUTH_COOKIE_SECURE" not in os.environ:
    COOKIE_SECURE = os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes", "on"}


class LoginRequest(BaseModel):
    email: Optional[EmailStr] = None
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    display_name: str = Field(default="", max_length=80)


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=REFRESH_TOKEN_TTL_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/api/auth",
    )


def _set_access_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/api/auth",
    )
    response.delete_cookie(
        key=ACCESS_COOKIE_NAME,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def _user_session_payload(access_token: str, user: User) -> dict:
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_TTL_SECONDS,
        "user": serialize_user(user),
    }


@router.get("/status")
async def auth_status():
    return {
        "required": AUTH_REQUIRED,
        "configured": auth_is_configured(),
        "mode": AUTH_MODE,
        "registration_enabled": AUTH_MODE == "users" and REGISTRATION_ENABLED,
    }


@router.post("/register", status_code=201)
async def register(
    req: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    if AUTH_MODE != "users" or not REGISTRATION_ENABLED:
        raise HTTPException(status_code=404, detail="当前未开放注册。")
    if not auth_is_configured():
        raise HTTPException(status_code=503, detail="用户登录服务尚未配置完成。")
    try:
        user = create_user(db, str(req.email), req.password, req.display_name)
        access_token, refresh_token, _ = issue_session(db, user)
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_refresh_cookie(response, refresh_token)
    _set_access_cookie(response, access_token, ACCESS_TOKEN_TTL_SECONDS)
    return _user_session_payload(access_token, user)


@router.post("/login")
async def login(
    req: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    if AUTH_MODE == "disabled":
        return {"access_token": "", "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS}

    if not auth_is_configured():
        raise HTTPException(status_code=503, detail="登录服务尚未配置完成。")

    if AUTH_MODE == "shared":
        if not verify_password(req.password):
            raise HTTPException(status_code=401, detail="访问密码错误。")
        access_token = create_shared_access_token()
        _set_access_cookie(response, access_token, TOKEN_TTL_SECONDS)
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": TOKEN_TTL_SECONDS,
        }

    if not req.email:
        raise HTTPException(status_code=422, detail="请输入邮箱。")
    try:
        user = authenticate_user(db, str(req.email), req.password)
        access_token, refresh_token, _ = issue_session(db, user)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_refresh_cookie(response, refresh_token)
    _set_access_cookie(response, access_token, ACCESS_TOKEN_TTL_SECONDS)
    return _user_session_payload(access_token, user)


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    if AUTH_MODE != "users":
        raise HTTPException(status_code=404, detail="当前登录模式不支持刷新会话。")
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME, "")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录。")
    try:
        access_token, next_refresh, user, _ = rotate_session(db, refresh_token)
    except AuthenticationError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_refresh_cookie(response, next_refresh)
    _set_access_cookie(response, access_token, ACCESS_TOKEN_TTL_SECONDS)
    return _user_session_payload(access_token, user)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME, "")
    if AUTH_MODE == "users" and refresh_token:
        revoke_session(db, refresh_token=refresh_token)
    _clear_refresh_cookie(response)
    response.status_code = 204


@router.get("/me")
async def current_user(request: Request, db: Session = Depends(get_db)):
    if AUTH_MODE != "users":
        raise HTTPException(status_code=404, detail="当前登录模式没有用户资料。")
    user_id = str(getattr(request.state, "user_id", ""))
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不可用。")
    return {"user": serialize_user(user)}
