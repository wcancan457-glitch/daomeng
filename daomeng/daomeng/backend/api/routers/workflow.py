import time
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from accounts.ownership import project_owned_by, register_project
from api.auth_context import request_user_id
from api.dependencies import workflow_engine
from api.routers.files import merge_uploaded_file_into_idea
from api.schemas.project import InterventionRequest, ProjectStartRequest
from api.services.project_helpers import (
    make_cancellation,
    make_progress_channel,
    stream_workflow_task,
)
from config import settings

router = APIRouter(tags=["Workflow"])

REQUIRED_MODEL_FIELDS = (
    "llm_model",
    "vlm_model",
    "image_t2i_model",
    "image_it2i_model",
)

VIDEO_MODE_TO_MODEL_FIELD = {
    "first_frame": "video_first_frame_model",
    "start_end_frame": "video_start_end_model",
    "reference": "video_reference_model",
}


def _active_video_model(values: dict) -> str:
    mode = values.get("video_generation_mode") or "first_frame"
    model_field = VIDEO_MODE_TO_MODEL_FIELD.get(mode, "video_first_frame_model")
    default_attr = {
        "video_first_frame_model": "VIDEO_FIRST_FRAME_MODEL",
        "video_start_end_model": "VIDEO_START_END_MODEL",
        "video_reference_model": "VIDEO_REFERENCE_MODEL",
    }.get(model_field, "VIDEO_MODEL")
    # Legacy session compatibility: fall back to the old single video_model field when mode-specific fields are absent.
    return values.get(model_field) or values.get("video_model") or getattr(settings, default_attr, "") or ""


def _require_model_fields(values: dict) -> None:
    missing = [field for field in REQUIRED_MODEL_FIELDS if not values.get(field)]
    if not _active_video_model(values):
        missing.append("video_model")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required model configuration: {', '.join(missing)}",
        )


def _require_project_access(request: Request, session_id: str) -> str:
    user_id = request_user_id(request)
    if not project_owned_by(session_id, user_id):
        raise HTTPException(404, "Session not found")
    return user_id


@router.post("/api/project/start")
async def start_project(req: ProjectStartRequest, request: Request):
    user_id = request_user_id(request)
    try:
        final_idea = merge_uploaded_file_into_idea(req.idea, req.file_path, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _require_model_fields(req.model_dump())

    session_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    meta = {
        "idea": final_idea,
        "user_textbox_input": req.idea,
        "style": req.style or getattr(settings, "STYLE", None) or "realistic",
        "video_ratio": req.video_ratio or "9:16",
        "video_resolution": req.video_resolution or "720P",
        "expand_idea": req.expand_idea if req.expand_idea is not None else True,
        "llm_model": req.llm_model,
        "vlm_model": req.vlm_model,
        "image_t2i_model": req.image_t2i_model,
        "image_it2i_model": req.image_it2i_model,
        # Legacy request/session compatibility: clients created before the split only send video_model.
        "video_first_frame_model": req.video_first_frame_model or req.video_model or getattr(settings, "VIDEO_FIRST_FRAME_MODEL", ""),
        "video_start_end_model": req.video_start_end_model or getattr(settings, "VIDEO_START_END_MODEL", ""),
        "video_reference_model": req.video_reference_model or getattr(settings, "VIDEO_REFERENCE_MODEL", ""),
        "video_generation_mode": req.video_generation_mode or getattr(settings, "VIDEO_GENERATION_MODE", "first_frame"),
        "video_model": req.video_model,
        "enable_concurrency": req.enable_concurrency if req.enable_concurrency is not None else False,
        "web_search": req.web_search if req.web_search is not None else False,
        "episodes": 1 if req.creation_mode == "trial" else (req.episodes if req.episodes is not None else 4),
        "creation_mode": "trial" if req.creation_mode == "trial" else "full",
        "trial_duration_seconds": max(2, min(15, req.trial_duration_seconds or 15)),
        "trial_status": "generating" if req.creation_mode == "trial" else None,
        "user_id": user_id,
    }
    meta["video_model"] = _active_video_model(meta)
    session = workflow_engine.create_session(session_id, meta)
    register_project(session_id, user_id)

    return {
        "session_id": session_id,
        "status": session["status"],
        "params": {
            "idea": final_idea,
            "file_path": req.file_path,
            "style": req.style,
            "llm_model": meta["llm_model"],
            "vlm_model": meta["vlm_model"],
            "image_t2i_model": meta["image_t2i_model"],
            "image_it2i_model": meta["image_it2i_model"],
            "video_first_frame_model": meta["video_first_frame_model"],
            "video_start_end_model": meta["video_start_end_model"],
            "video_reference_model": meta["video_reference_model"],
            "video_generation_mode": meta["video_generation_mode"],
            "video_model": meta["video_model"],
            "episodes": meta["episodes"],
            "video_ratio": meta["video_ratio"],
            "video_resolution": meta["video_resolution"],
            "creation_mode": meta["creation_mode"],
            "trial_duration_seconds": meta["trial_duration_seconds"],
        }
    }


@router.post("/api/project/{session_id}/expand-trial")
async def expand_trial(session_id: str, request: Request):
    """Turn an approved trial into one complete episode in the same workflow session."""
    _require_project_access(request, session_id)
    try:
        return workflow_engine.expand_trial_session(session_id)
    except KeyError:
        raise HTTPException(404, "Session not found")
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.post("/api/project/{session_id}/execute/{stage}")
async def execute_stage(session_id: str, stage: str, request: Request):
    _require_project_access(request, session_id)
    try:
        body = await request.json()
    except Exception:
        body = {}

    state, input_data = workflow_engine.prepare_stage_execution(session_id, stage, body)
    _require_model_fields(input_data)

    cancellation_check, on_disconnect = make_cancellation(workflow_engine, session_id)
    progress_events, event_trigger, progress_callback = make_progress_channel()

    return StreamingResponse(
        stream_workflow_task(
            request=request,
            workflow_engine=workflow_engine,
            state=state,
            stage=stage,
            input_data=input_data,
            cancellation_check=cancellation_check,
            progress_callback=progress_callback,
            progress_events=progress_events,
            event_trigger=event_trigger,
            include_payload_summary=True,
            on_disconnect=on_disconnect,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/api/project/{session_id}/status")
async def get_project_status(session_id: str, request: Request):
    _require_project_access(request, session_id)
    snapshot = workflow_engine.get_status_snapshot(session_id)
    if not snapshot:
        raise HTTPException(404, "Session not found")
    return snapshot


@router.get("/api/project/{session_id}/status/from_disk")
async def get_project_status_from_disk(session_id: str, request: Request):
    _require_project_access(request, session_id)
    # 兼容旧前端路由名；实际读取统一走 WorkflowEngine 的内存状态入口。
    snapshot = workflow_engine.get_status_snapshot(session_id)
    if not snapshot:
        raise HTTPException(404, "Session not found")
    return snapshot


@router.get("/api/project/{session_id}/artifact/{stage}")
async def get_artifact(session_id: str, stage: str, request: Request):
    _require_project_access(request, session_id)
    try:
        artifact = workflow_engine.get_artifact_snapshot(session_id, stage)
    except KeyError:
        raise HTTPException(404, "Session not found")

    if artifact is not None:
        return {"stage": stage, "artifact": artifact}

    raise HTTPException(404, f"Artifact for stage '{stage}' not found")


@router.patch("/api/project/{session_id}/models")
async def update_models(session_id: str, request: Request):
    _require_project_access(request, session_id)
    body = await request.json()
    allowed_keys = (
        "llm_model",
        "vlm_model",
        "image_t2i_model",
        "image_it2i_model",
        "video_model",
        "video_first_frame_model",
        "video_start_end_model",
        "video_reference_model",
        "video_generation_mode",
        "video_ratio",
        "video_resolution",
        "style",
        "enable_concurrency",
    )
    try:
        return workflow_engine.update_session_meta(session_id, body if isinstance(body, dict) else {}, allowed_keys)
    except KeyError:
        raise HTTPException(404, "Session not found")


@router.post("/api/project/{session_id}/artifact/{stage}/upload_image")
async def upload_artifact_image(
    session_id: str,
    stage: str,
    request: Request,
    item_type: str = Form(...),
    item_id: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload a user-provided image into a stage artifact and persist the session."""
    _require_project_access(request, session_id)
    try:
        return workflow_engine.upload_artifact_image(
            session_id=session_id,
            stage=stage,
            item_type=item_type,
            item_id=item_id,
            file_obj=file.file,
            filename=file.filename or "",
        )
    except KeyError:
        raise HTTPException(404, "Session not found")
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(500, detail=str(exc)) from exc


@router.patch("/api/project/{session_id}/artifact/{stage}")
async def update_artifact(session_id: str, stage: str, request: Request):
    """保存用户在某阶段的选择/修改，同时更新内存状态和磁盘快照。"""
    _require_project_access(request, session_id)
    body = await request.json()
    try:
        return workflow_engine.update_artifact(session_id, stage, body if isinstance(body, dict) else {})
    except KeyError:
        raise HTTPException(404, "Session not found")




@router.post("/api/project/{session_id}/intervene")
async def intervene(session_id: str, req: InterventionRequest, request: Request):
    _require_project_access(request, session_id)
    try:
        state, input_data = workflow_engine.prepare_intervention_execution(
            session_id=session_id,
            stage=req.stage,
            modifications=req.modifications,
        )
    except KeyError:
        raise HTTPException(404, "Session not found")

    cancellation_check, on_disconnect = make_cancellation(workflow_engine, session_id)
    progress_events, event_trigger, progress_callback = make_progress_channel()

    return StreamingResponse(
        stream_workflow_task(
            request=request,
            workflow_engine=workflow_engine,
            state=state,
            stage=req.stage,
            input_data=input_data,
            cancellation_check=cancellation_check,
            progress_callback=progress_callback,
            progress_events=progress_events,
            event_trigger=event_trigger,
            intervention=req.modifications,
            on_disconnect=on_disconnect,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/api/project/{session_id}/continue")
async def continue_workflow(session_id: str, request: Request):
    _require_project_access(request, session_id)
    if not workflow_engine.get_status_snapshot(session_id):
        raise HTTPException(404, "Session not found")
    return await workflow_engine.continue_workflow(session_id)


@router.post("/api/project/{session_id}/stop")
async def stop_project(session_id: str, request: Request):
    _require_project_access(request, session_id)
    workflow_engine.stop_session(session_id)
    return {"status": "stopped", "session_id": session_id}


@router.get("/api/project/{session_id}/scene/{scene_number}/assets")
async def check_scene_assets(session_id: str, scene_number: int, request: Request):
    _require_project_access(request, session_id)
    try:
        return workflow_engine.get_scene_asset_counts(session_id, scene_number)
    except KeyError:
        raise HTTPException(404, "Session not found")
