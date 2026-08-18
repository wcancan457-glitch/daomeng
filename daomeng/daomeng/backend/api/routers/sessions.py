from fastapi import APIRouter, HTTPException, Request

from accounts.ownership import delete_project_ownership, project_owned_by
from api.auth_context import request_user_id, require_admin
from api.dependencies import workflow_engine

router = APIRouter(tags=["Sessions"])


@router.get("/api/sessions")
async def list_sessions(request: Request):
    user_id = request_user_id(request)
    return {"sessions": workflow_engine.list_saved_sessions(user_id=user_id)}


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    user_id = request_user_id(request)
    if not project_owned_by(session_id, user_id):
        raise HTTPException(404, "Session not found")
    deleted = workflow_engine.delete_session(session_id)
    if not deleted:
        raise HTTPException(404, "Session not found")
    delete_project_ownership(session_id, user_id)
    return {"status": "deleted", "session_id": session_id}


@router.delete("/api/sessions")
async def cleanup_orphan_files(request: Request):
    """清理孤立结果文件；这是影响全局数据的管理员操作。"""
    require_admin(request)
    return workflow_engine.cleanup_orphan_results()
