from fastapi import HTTPException, Request

from api.security_layer import AUTH_MODE

LEGACY_OWNER_ID = "legacy-shared"


def request_user_id(request: Request) -> str:
    if AUTH_MODE != "users":
        return LEGACY_OWNER_ID
    user_id = str(getattr(request.state, "user_id", ""))
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录。")
    return user_id


def request_user_role(request: Request) -> str:
    if AUTH_MODE != "users":
        return "admin"
    return str(getattr(request.state, "user_role", "user"))


def require_admin(request: Request) -> str:
    user_id = request_user_id(request)
    if request_user_role(request) != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以执行此操作。")
    return user_id

