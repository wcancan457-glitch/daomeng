from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.security_layer import (
    AUTH_REQUIRED,
    TOKEN_TTL_SECONDS,
    auth_is_configured,
    create_access_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    password: str


@router.get("/status")
async def auth_status():
    return {"required": AUTH_REQUIRED, "configured": auth_is_configured()}


@router.post("/login")
async def login(req: LoginRequest):
    if not AUTH_REQUIRED:
        return {"access_token": "", "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS}
    if not auth_is_configured():
        raise HTTPException(status_code=503, detail="服务尚未配置访问密码，请联系管理员。")
    if not verify_password(req.password):
        raise HTTPException(status_code=401, detail="访问密码错误。")
    return {
        "access_token": create_access_token(),
        "token_type": "bearer",
        "expires_in": TOKEN_TTL_SECONDS,
    }
