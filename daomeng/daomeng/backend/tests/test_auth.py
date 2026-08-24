import os
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

_test_dir = Path(tempfile.mkdtemp(prefix="daomeng-auth-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_test_dir / 'auth.db').as_posix()}"
os.environ["RUNTIME_DATA_DIR"] = str(_test_dir / "runtime")
os.environ["AUTH_MODE"] = "users"
os.environ["AUTH_TOKEN_SECRET"] = "test-only-secret-that-is-longer-than-thirty-two-characters"
os.environ["SETTINGS_ENCRYPTION_KEY"] = "test-only-settings-encryption-key"
os.environ["AUTH_COOKIE_SECURE"] = "false"
os.environ["REGISTRATION_ENABLED"] = "true"
os.environ["AUTH_RATE_LIMIT_PER_MINUTE"] = "1000"
os.environ["PIPELINE_WORKER_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

from accounts.database import SessionLocal  # noqa: E402
from accounts.models import AdminAuditLog, ProjectMediaAsset, SystemSetting, User  # noqa: E402
from api.app import app  # noqa: E402
from api.dependencies import workflow_engine  # noqa: E402
from config import settings  # noqa: E402
from core.orchestrator import WorkflowEngine, WorkflowStage  # noqa: E402
from pipelines.storage import (  # noqa: E402
    TaskQuotaError,
    claim_next_pending_task,
    create_task,
    delete_task,
    load_task,
    mark_failed,
    recover_interrupted_tasks,
)


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_interrupted_workflow_stage_is_recoverable() -> None:
    state = WorkflowEngine._state_from_snapshot(
        {
            "session_id": "recover-me",
            "current_stage": "script_generation",
            "status": {"script_generation": "running"},
            "stage_progress": {"script_generation": {"step": "生成中"}},
        }
    )
    assert state.status["script_generation"] == "pending"
    assert "服务重启" in state.stage_progress["script_generation"]["message"]


def test_register_login_refresh_and_logout() -> None:
    with TestClient(app) as client:
        status = client.get("/api/auth/status")
        assert status.status_code == 200
        assert status.json() == {
            "required": True,
            "configured": True,
            "mode": "users",
            "registration_enabled": True,
        }
        readiness = client.get("/api/health/ready")
        assert readiness.status_code == 200
        assert readiness.json()["status"] == "ready"
        assert readiness.headers["x-request-id"]
        assert readiness.headers["server-timing"].startswith("app;dur=")

        registered = client.post(
            "/api/auth/register",
            json={
                "email": "creator@example.com",
                "password": "correct horse battery staple",
                "display_name": "创作者",
            },
        )
        assert registered.status_code == 201
        registered_payload = registered.json()
        assert registered_payload["user"]["email"] == "creator@example.com"
        assert registered_payload["user"]["display_name"] == "创作者"
        first_access_token = registered_payload["access_token"]

        current = client.get("/api/auth/me", headers=auth_header(first_access_token))
        assert current.status_code == 200
        assert current.json()["user"]["email"] == "creator@example.com"

        forbidden_admin = client.get("/api/admin/overview", headers=auth_header(first_access_token))
        assert forbidden_admin.status_code == 403

        visible_config = client.get("/api/config", headers=auth_header(first_access_token))
        assert visible_config.status_code == 200
        assert set(visible_config.json()["config"]) == {"project_name", "models", "generation"}
        forbidden_config_update = client.put(
            "/api/config",
            headers=auth_header(first_access_token),
            json={"values": {"generation": {"style": "anime"}}},
        )
        assert forbidden_config_update.status_code == 403

        duplicate = client.post(
            "/api/auth/register",
            json={
                "email": "CREATOR@example.com",
                "password": "another secure password",
            },
        )
        assert duplicate.status_code == 409

        wrong_password = client.post(
            "/api/auth/login",
            json={"email": "creator@example.com", "password": "wrong password"},
        )
        assert wrong_password.status_code == 401

        logged_in = client.post(
            "/api/auth/login",
            json={
                "email": "creator@example.com",
                "password": "correct horse battery staple",
            },
        )
        assert logged_in.status_code == 200
        assert logged_in.json()["access_token"]

        refreshed = client.post("/api/auth/refresh")
        assert refreshed.status_code == 200
        refreshed_access_token = refreshed.json()["access_token"]
        assert refreshed_access_token != logged_in.json()["access_token"]

        logged_out = client.post("/api/auth/logout")
        assert logged_out.status_code == 204

        revoked = client.get("/api/auth/me", headers=auth_header(refreshed_access_token))
        assert revoked.status_code == 401


def test_admin_can_save_encrypted_model_credentials() -> None:
    email = "model-admin@example.com"
    password = "admin model gateway password"
    with TestClient(app) as client:
        registered = client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "display_name": "模型管理员"},
        )
        assert registered.status_code == 201
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.normalized_email == email))
            assert admin is not None
            admin.role = "admin"
            db.commit()

        login = client.post("/api/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = auth_header(token)

        updated = client.put(
            "/api/config",
            headers=headers,
            json={
                "values": {
                    "api_providers": {
                        "siliconflow": {"api_key": "sf-test-secret"},
                        "ark": {"api_key": "ark-test-secret"},
                        "dashscope": {"api_key": "dashscope-test-secret"},
                    },
                    "models": {
                        "llm": "Qwen/Qwen2.5-72B-Instruct",
                        "vlm": "Qwen/Qwen2.5-VL-72B-Instruct",
                        "image_t2i": "doubao-seedream-5-0-260128",
                        "image_it2i": "doubao-seedream-5-0-260128",
                        "video_first_frame": "wan2.7-i2v",
                    },
                }
            },
        )
        assert updated.status_code == 200
        payload = updated.json()
        assert payload["configured_secrets"]["api_providers.siliconflow.api_key"] is True
        assert payload["config"]["api_providers"]["siliconflow"]["api_key"] == ""
        assert payload["config"]["models"]["llm"] == "Qwen/Qwen2.5-72B-Instruct"
        assert payload["config"]["models"]["image_t2i"] == "doubao-seedream-5-0-260128"
        assert payload["config"]["models"]["video_first_frame"] == "wan2.7-i2v"

        preserved = client.put(
            "/api/config",
            headers=headers,
            json={"values": {"api_providers": {"siliconflow": {"api_key": ""}}}},
        )
        assert preserved.status_code == 200
        assert preserved.json()["configured_secrets"]["api_providers.siliconflow.api_key"] is True

        model_list_response = Mock()
        model_list_response.status_code = 200
        model_list_response.json.return_value = {
            "data": [{"id": "doubao-seedream-5-0-260128"}]
        }
        with patch("api.provider_checks.httpx.Client") as client_class:
            client_class.return_value.__enter__.return_value.get.return_value = model_list_response
            provider_test = client.post(
                "/api/config/test-provider",
                headers=headers,
                json={"provider": "ark"},
            )
        assert provider_test.status_code == 200
        assert provider_test.json()["ok"] is True
        assert provider_test.json()["level"] == "success"
        assert provider_test.json()["verified_models"] == ["doubao-seedream-5-0-260128"]

        unauthorized_response = Mock()
        unauthorized_response.status_code = 401
        with patch("api.provider_checks.httpx.Client") as client_class:
            client_class.return_value.__enter__.return_value.get.return_value = unauthorized_response
            invalid_provider_test = client.post(
                "/api/config/test-provider",
                headers=headers,
                json={"provider": "ark"},
            )
        assert invalid_provider_test.status_code == 200
        assert invalid_provider_test.json()["ok"] is False
        assert "API Key 无效" in invalid_provider_test.json()["message"]

        with SessionLocal() as db:
            record = db.get(SystemSetting, "model_gateway_config_v1")
            assert record is not None
            assert "sf-test-secret" not in record.encrypted_value
            assert "ark-test-secret" not in record.encrypted_value


def test_admin_console_controls_users_tasks_and_quotas() -> None:
    admin_email = "console-admin@example.com"
    admin_password = "console admin secure password"
    managed_email = "managed-user@example.com"
    with TestClient(app) as client:
        admin_registration = client.post(
            "/api/auth/register",
            json={"email": admin_email, "password": admin_password, "display_name": "运营管理员"},
        )
        assert admin_registration.status_code == 201
        managed_registration = client.post(
            "/api/auth/register",
            json={"email": managed_email, "password": "managed user secure password"},
        )
        assert managed_registration.status_code == 201
        managed_user_id = managed_registration.json()["user"]["id"]

        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.normalized_email == admin_email))
            assert admin is not None
            admin.role = "admin"
            db.commit()

        login = client.post(
            "/api/auth/login",
            json={"email": admin_email, "password": admin_password},
        )
        headers = auth_header(login.json()["access_token"])

        overview = client.get("/api/admin/overview", headers=headers)
        assert overview.status_code == 200
        assert overview.json()["users"]["total"] >= 2

        users = client.get("/api/admin/users?q=managed-user", headers=headers)
        assert users.status_code == 200
        assert [item["email"] for item in users.json()["users"]] == [managed_email]

        limited = client.patch(
            f"/api/admin/users/{managed_user_id}",
            headers=headers,
            json={"daily_llm_limit": 5, "daily_image_limit": 3, "daily_video_limit": 0},
        )
        assert limited.status_code == 200
        assert limited.json()["user"]["limits"] == {"llm": 5, "image": 3, "video": 0}
        with pytest.raises(TaskQuotaError, match="额度已用完"):
            create_task("standard", {"text": "blocked"}, user_id=managed_user_id)

        enabled = client.patch(
            f"/api/admin/users/{managed_user_id}",
            headers=headers,
            json={"daily_video_limit": 2},
        )
        assert enabled.status_code == 200
        task = create_task("standard", {"text": "retry me"}, user_id=managed_user_id)
        mark_failed(task["task_id"], "provider unavailable")

        tasks = client.get("/api/admin/tasks?status=failed", headers=headers)
        assert tasks.status_code == 200
        assert task["task_id"] in {item["task_id"] for item in tasks.json()["tasks"]}
        retried = client.post(f"/api/admin/tasks/{task['task_id']}/retry", headers=headers)
        assert retried.status_code == 200
        assert retried.json()["task"]["status"] == "pending"

        models = client.get("/api/admin/models", headers=headers)
        assert models.status_code == 200
        assert "llm" in models.json()["assignments"]
        assert all("api_key" not in item for item in models.json()["providers"])

        system = client.get("/api/admin/system", headers=headers)
        assert system.status_code == 200
        assert system.json()["database"]["status"] == "ready"

        audit = client.get("/api/admin/audit", headers=headers)
        assert audit.status_code == 200
        assert {item["action"] for item in audit.json()["logs"]} >= {"user.update", "task.retry"}
        with SessionLocal() as db:
            assert db.scalar(select(AdminAuditLog)) is not None
        assert delete_task(task["task_id"], user_id=managed_user_id) is True


def test_projects_and_tasks_are_isolated_by_user() -> None:
    with TestClient(app) as client:
        first = client.post(
            "/api/auth/register",
            json={
                "email": "owner-a@example.com",
                "password": "owner a secure password",
                "display_name": "用户 A",
            },
        )
        second = client.post(
            "/api/auth/register",
            json={
                "email": "owner-b@example.com",
                "password": "owner b secure password",
                "display_name": "用户 B",
            },
        )
        assert first.status_code == 201
        assert second.status_code == 201
        first_token = first.json()["access_token"]
        second_token = second.json()["access_token"]
        first_user_id = first.json()["user"]["id"]

        invalid_image = client.post(
            "/api/upload_media",
            headers=auth_header(first_token),
            files={"file": ("fake.png", b"not an image", "image/png")},
        )
        assert invalid_image.status_code == 400

        image_buffer = BytesIO()
        Image.new("RGB", (2, 2), color=(20, 30, 40)).save(image_buffer, format="PNG")
        uploaded_image = client.post(
            "/api/upload_media",
            headers=auth_header(first_token),
            files={"file": ("avatar.png", image_buffer.getvalue(), "image/png")},
        )
        assert uploaded_image.status_code == 200
        uploaded_key = uploaded_image.json()["file_path"]
        assert uploaded_key.startswith(f"{first_user_id}/")

        stolen_upload = client.post(
            "/api/pipelines/action_transfer/tasks",
            headers=auth_header(second_token),
            json={
                "prompt_text": "test",
                "image_path": uploaded_key,
                "video_path": uploaded_key,
                "video_model": "test-video",
            },
        )
        assert stolen_upload.status_code == 400

        project = client.post(
            "/api/project/start",
            headers=auth_header(first_token),
            json={
                "idea": "只属于用户 A 的项目",
                "llm_model": "test-llm",
                "vlm_model": "test-vlm",
                "image_t2i_model": "test-t2i",
                "image_it2i_model": "test-i2i",
                "video_first_frame_model": "test-video",
            },
        )
        assert project.status_code == 200
        project_id = project.json()["session_id"]

        traversal_upload = client.post(
            f"/api/project/{project_id}/artifact/character_design/upload_image",
            headers=auth_header(first_token),
            data={"item_type": "characters", "item_id": "../../escape"},
            files={"file": ("avatar.png", image_buffer.getvalue(), "image/png")},
        )
        assert traversal_upload.status_code == 400
        invalid_artifact_image = client.post(
            f"/api/project/{project_id}/artifact/character_design/upload_image",
            headers=auth_header(first_token),
            data={"item_type": "characters", "item_id": "char_safe"},
            files={"file": ("avatar.png", b"not an image", "image/png")},
        )
        assert invalid_artifact_image.status_code == 400

        reference_upload = client.post(
            f"/api/project/{project_id}/artifact/character_design/upload_image",
            headers=auth_header(first_token),
            data={"item_type": "characters", "item_id": "char_safe"},
            files={"file": ("reference.png", image_buffer.getvalue(), "image/png")},
        )
        assert reference_upload.status_code == 200
        uploaded_artifact = reference_upload.json()["artifact"]
        uploaded_character = next(item for item in uploaded_artifact["characters"] if item["id"] == "char_safe")
        assert uploaded_character.get("selected", "") == ""
        assert len(uploaded_character["reference_images"]) == 1
        assert "ReferenceInputs" in uploaded_character["reference_images"][0]

        # Render-style ephemeral filesystem recovery: session media is stored
        # durably in the database and rehydrated before the artifact is used.
        stored_reference = uploaded_character["reference_images"][0].replace("\\", "/")
        relative_reference = stored_reference[len("code/"):] if stored_reference.startswith("code/") else stored_reference
        absolute_reference = Path(settings.CODE_DIR) / relative_reference
        assert absolute_reference.is_file()
        with SessionLocal() as db:
            durable_asset = db.get(ProjectMediaAsset, (project_id, relative_reference))
            assert durable_asset is not None
            assert durable_asset.size_bytes == absolute_reference.stat().st_size
        absolute_reference.unlink()
        assert not absolute_reference.exists()

        # A browser image request does not first call the artifact endpoint.
        # The /code route must therefore restore the durable file on demand.
        client.cookies.set("daomeng_access", first_token)
        direct_media = client.get(f"/code/{relative_reference}")
        assert direct_media.status_code == 200
        assert direct_media.content == image_buffer.getvalue()
        assert absolute_reference.is_file()

        absolute_reference.unlink()
        assert not absolute_reference.exists()

        restored_artifact = client.get(
            f"/api/project/{project_id}/artifact/character_design",
            headers=auth_header(first_token),
        )
        assert restored_artifact.status_code == 200
        assert absolute_reference.is_file()

        project_state = workflow_engine.get_state(project_id)
        assert project_state is not None

        # A succeeded Ark task can be recovered into the original clip without
        # submitting another paid generation request.
        project_state.meta.update({
            "video_generation_mode": "first_frame",
            "video_first_frame_model": "doubao-seedance-2-0-260128",
        })
        project_state.artifacts["reference_generation"] = {
            "scenes": [{
                "id": "seg_01_01",
                "name": "第1集-片段1",
                "selected": "code/result/image/missing-first-frame.png",
                "versions": ["code/result/image/missing-first-frame.png"],
                "status": "done",
            }],
        }
        project_state.artifacts["video_generation"] = {
            "clips": [
                {
                    "id": "seg_01_01",
                    "name": "第1集-片段1",
                    "duration": 5,
                    "description": "人物回头",
                    "selected": "",
                    "versions": [],
                    "status": "failed",
                    "error": "视频模型：首帧参考图记录存在，但文件已失效。",
                },
                {
                    "id": "seg_01_02",
                    "name": "第1集-片段2",
                    "duration": 7,
                    "description": "镜头缓慢推进",
                    "selected": "",
                    "versions": [],
                    "status": "failed",
                },
            ],
        }
        workflow_engine.save_session_to_disk(project_id)

        # A broken legacy first-frame path can be replaced directly from the
        # video stage without rerunning reference generation.
        first_frame_upload = client.post(
            f"/api/project/{project_id}/video/seg_01_01/first-frame",
            headers=auth_header(first_token),
            files={"file": ("first-frame.png", image_buffer.getvalue(), "image/png")},
        )
        assert first_frame_upload.status_code == 200
        first_frame_payload = first_frame_upload.json()
        assert first_frame_payload["path"]
        repaired_clip = next(
            item for item in first_frame_payload["artifact"]["clips"] if item["id"] == "seg_01_01"
        )
        repaired_scene = next(
            item for item in first_frame_payload["reference_artifact"]["scenes"] if item["id"] == "seg_01_01"
        )
        assert repaired_clip["status"] == "pending"
        assert "error" not in repaired_clip
        assert repaired_scene["selected"] == first_frame_payload["path"]
        assert repaired_scene["source"] == "video_stage_upload"

        denied_first_frame_upload = client.post(
            f"/api/project/{project_id}/video/seg_01_01/first-frame",
            headers=auth_header(second_token),
            files={"file": ("first-frame.png", image_buffer.getvalue(), "image/png")},
        )
        assert denied_first_frame_upload.status_code == 404

        def fake_download_task_result(_self, task_id, save_path, expected_model=None, expected_duration=None):
            assert task_id == "cgt-test-recovery-123"
            assert expected_model == "doubao-seedance-2-0-260128"
            assert expected_duration == 7
            Path(save_path).write_bytes(b"test-video-content")
            return {
                "id": task_id,
                "status": "succeeded",
                "model": expected_model,
                "duration": expected_duration,
                "created_at": 100,
                "updated_at": 287,
            }

        with patch(
            "models.video_seedance.SeedanceVideoClient.download_task_result",
            new=fake_download_task_result,
        ):
            recovered_video = client.post(
                f"/api/project/{project_id}/video/seg_01_02/recover",
                headers=auth_header(first_token),
                json={"task_id": "cgt-test-recovery-123"},
            )
        assert recovered_video.status_code == 200
        recovered_clip = next(
            item for item in recovered_video.json()["artifact"]["clips"] if item["id"] == "seg_01_02"
        )
        assert recovered_clip["status"] == "done"
        assert recovered_clip["provider_task_id"] == "cgt-test-recovery-123"
        assert recovered_clip["elapsed_seconds"] == 187
        assert Path(recovered_clip["selected"]).is_file()

        denied_recovery = client.post(
            f"/api/project/{project_id}/video/seg_01_02/recover",
            headers=auth_header(second_token),
            json={"task_id": "cgt-test-recovery-123"},
        )
        assert denied_recovery.status_code == 404

        duplicate_recovery = client.post(
            f"/api/project/{project_id}/video/seg_01_01/recover",
            headers=auth_header(first_token),
            json={"task_id": "cgt-test-recovery-123"},
        )
        assert duplicate_recovery.status_code == 400
        assert "已经恢复到" in duplicate_recovery.json()["detail"]

        project_state.current_stage = WorkflowStage.CHARACTER_DESIGN
        project_state.status[WorkflowStage.CHARACTER_DESIGN.value] = "waiting"
        blocked_continue = client.post(
            f"/api/project/{project_id}/continue",
            headers=auth_header(first_token),
        )
        assert blocked_continue.status_code == 200
        assert blocked_continue.json()["status"] == "waiting"
        assert "next_stage" not in blocked_continue.json()

        first_sessions = client.get("/api/sessions", headers=auth_header(first_token))
        second_sessions = client.get("/api/sessions", headers=auth_header(second_token))
        assert project_id in {item["id"] for item in first_sessions.json()["sessions"]}
        assert project_id not in {item["id"] for item in second_sessions.json()["sessions"]}

        denied_project = client.get(
            f"/api/project/{project_id}/status",
            headers=auth_header(second_token),
        )
        assert denied_project.status_code == 404

        task = create_task("standard", {"text": "用户 A 的任务"}, user_id=first_user_id)
        task_id = task["task_id"]
        claimed = claim_next_pending_task()
        assert claimed and claimed["task_id"] == task_id
        assert load_task(task_id, user_id=first_user_id)["status"] == "running"
        assert recover_interrupted_tasks() == 1
        assert load_task(task_id, user_id=first_user_id)["status"] == "pending"
        first_tasks = client.get("/api/tasks", headers=auth_header(first_token))
        second_tasks = client.get("/api/tasks", headers=auth_header(second_token))
        assert task_id in {item["task_id"] for item in first_tasks.json()["tasks"]}
        assert task_id not in {item["task_id"] for item in second_tasks.json()["tasks"]}

        denied_task = client.get(f"/api/tasks/{task_id}", headers=auth_header(second_token))
        assert denied_task.status_code == 404

        preview_file = Path(task["output_dir"]) / "preview.txt"
        preview_file.write_text("private asset", encoding="utf-8")
        asset_url = f"/code/result/task/{task_id}/preview.txt"
        own_asset = client.get(asset_url, headers=auth_header(first_token))
        other_asset = client.get(asset_url, headers=auth_header(second_token))
        assert own_asset.status_code == 200
        assert own_asset.text == "private asset"
        assert other_asset.status_code == 404

        with TestClient(app) as anonymous:
            unauthenticated_asset = anonymous.get(asset_url)
            assert unauthenticated_asset.status_code == 401

        deleted_task = client.delete(f"/api/tasks/{task_id}", headers=auth_header(first_token))
        assert deleted_task.status_code == 200
        deleted_project = client.delete(
            f"/api/sessions/{project_id}",
            headers=auth_header(first_token),
        )
        assert deleted_project.status_code == 200
