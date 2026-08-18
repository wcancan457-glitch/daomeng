from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from accounts.models import AuthSession, User
from accounts.tokens import (
    REFRESH_TOKEN_TTL_SECONDS,
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
)

password_hasher = PasswordHasher()


def _positive_env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


MAX_SESSIONS_PER_USER = _positive_env_int("MAX_SESSIONS_PER_USER", 10)


class AccountError(ValueError):
    pass


class DuplicateEmailError(AccountError):
    pass


class AuthenticationError(AccountError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "email_verified": user.email_verified,
        "created_at": user.created_at.isoformat(),
    }


def create_user(db: Session, email: str, password: str, display_name: str = "") -> User:
    normalized = normalize_email(email)
    if len(password) < 10:
        raise AccountError("密码至少需要 10 个字符。")
    if db.scalar(select(User).where(User.normalized_email == normalized)):
        raise DuplicateEmailError("该邮箱已注册。")
    user = User(
        email=email.strip(),
        normalized_email=normalized,
        password_hash=password_hasher.hash(password),
        display_name=display_name.strip()[:80],
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateEmailError("该邮箱已注册。") from exc
    db.refresh(user)
    return user


def bootstrap_admin(db: Session) -> Optional[User]:
    email = os.getenv("ADMIN_EMAIL", "").strip()
    password = os.getenv("APP_ACCESS_PASSWORD", "")
    if not email or not password:
        return None
    normalized = normalize_email(email)
    user = db.scalar(select(User).where(User.normalized_email == normalized))
    if user:
        changed = False
        if user.role != "admin":
            user.role = "admin"
            changed = True
        if not user.email_verified:
            user.email_verified = True
            changed = True
        if changed:
            db.commit()
        return user
    user = User(
        email=email,
        normalized_email=normalized,
        password_hash=password_hasher.hash(password),
        display_name="管理员",
        role="admin",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.normalized_email == normalize_email(email)))
    if not user or not user.is_active:
        raise AuthenticationError("邮箱或密码不正确。")
    try:
        password_hasher.verify(user.password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        raise AuthenticationError("邮箱或密码不正确。")
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = password_hasher.hash(password)
        db.commit()
    return user


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def issue_session(db: Session, user: User) -> Tuple[str, str, AuthSession]:
    active_sessions = db.scalars(
        select(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now_utc(),
        )
        .order_by(AuthSession.created_at.desc())
    ).all()
    for stale_session in active_sessions[MAX_SESSIONS_PER_USER - 1:]:
        stale_session.revoked_at = now_utc()

    refresh_token = create_refresh_token()
    auth_session = AuthSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        expires_at=now_utc() + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS),
    )
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    access_token = create_access_token(user.id, auth_session.id, user.role)
    return access_token, refresh_token, auth_session


def rotate_session(db: Session, refresh_token: str) -> Tuple[str, str, User, AuthSession]:
    auth_session = db.scalar(
        select(AuthSession)
        .where(AuthSession.refresh_token_hash == hash_refresh_token(refresh_token))
        .with_for_update()
    )
    if (
        not auth_session
        or auth_session.revoked_at is not None
        or _aware(auth_session.expires_at) <= now_utc()
    ):
        raise AuthenticationError("登录已过期，请重新登录。")
    user = db.get(User, auth_session.user_id)
    if not user or not user.is_active:
        raise AuthenticationError("账号不可用。")

    next_refresh = create_refresh_token()
    auth_session.refresh_token_hash = hash_refresh_token(next_refresh)
    auth_session.last_used_at = now_utc()
    db.commit()
    access_token = create_access_token(user.id, auth_session.id, user.role)
    return access_token, next_refresh, user, auth_session


def revoke_session(
    db: Session,
    *,
    refresh_token: str = "",
    session_id: str = "",
) -> None:
    auth_session: Optional[AuthSession] = None
    if refresh_token:
        auth_session = db.scalar(
            select(AuthSession).where(AuthSession.refresh_token_hash == hash_refresh_token(refresh_token))
        )
    elif session_id:
        auth_session = db.get(AuthSession, session_id)
    if auth_session and auth_session.revoked_at is None:
        auth_session.revoked_at = now_utc()
        db.commit()


def validate_session(db: Session, session_id: str, user_id: str) -> Optional[User]:
    auth_session = db.get(AuthSession, session_id)
    if (
        not auth_session
        or auth_session.user_id != user_id
        or auth_session.revoked_at is not None
        or _aware(auth_session.expires_at) <= now_utc()
    ):
        return None
    user = db.get(User, user_id)
    return user if user and user.is_active else None
