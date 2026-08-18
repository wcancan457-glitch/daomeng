import os
import tempfile
from io import BytesIO
from pathlib import Path

_test_dir = Path(tempfile.mkdtemp(prefix="daomeng-auth-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_test_dir / 'auth.db').as_posix()}"
os.environ["RUNTIME_DATA_DIR"] = str(_test_dir / "runtime")
os.environ["AUTH_MODE"] = "users"
os.environ["AUTH_TOKEN_SECRET"] = "test-only-secret-that-is-longer-than-thirty-two-characters"
os.environ["SETTINGS_ENCRYPTION_KEY"] = "test-only-settings-encryption-key"
os.environ["AUTH_COOKIE_SECURE"] = "false"
os.environ["REGISTRATION_ENABLED"] = "true"
os.environ["PIPELINE_WORKER_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

from accounts.database import SessionLocal  # noqa: E402
from accounts.models import SystemSetting, User  # noqa: E402
from api.app import app  # noqa: E402
from core.orchestrator import WorkflowEngine  # noqa: E402
from pipelines.storage import (  # noqa: E402
    claim_next_pending_task,
    create_task,
    load_task,
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

        with SessionLocal() as db:
            record = db.get(SystemSetting, "model_gateway_config_v1")
            assert record is not None
            assert "sf-test-secret" not in record.encrypted_value
            assert "ark-test-secret" not in record.encrypted_value


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
