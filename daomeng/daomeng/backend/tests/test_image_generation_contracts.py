import asyncio

import pytest

from core.agents.character_agent import CharacterDesignerAgent
from core.agents.reference_agent import ReferenceGeneratorAgent
from core.agents.script_agent import ScriptWriterAgent
from core.agents.video_agent import VideoDirectorAgent
from models.image_seedream import supports_sequential_image_generation
from models.public_errors import is_retryable_media_error, public_image_error, public_video_error
from models.video_seedance import SeedanceVideoClient


def test_seedream_full_does_not_receive_unsupported_sequential_parameter() -> None:
    assert supports_sequential_image_generation("doubao-seedream-5-0-260128") is False
    assert supports_sequential_image_generation("doubao-seedream-5-0-lite-260128") is True
    assert supports_sequential_image_generation("doubao-seedream-4-5-251128") is True


def test_character_prompt_contains_production_ready_visual_constraints() -> None:
    prompt = CharacterDesignerAgent._char_prompt(
        "小雨",
        "16岁女生，椭圆脸，黑色长直发，白色衬衫配藏蓝百褶裙，身形匀称，黑色乐福鞋。",
        "写实电影风格",
        "人类",
    )
    assert "面部结构" in prompt
    assert "面料质感" in prompt
    assert "90度侧面全身" in prompt
    assert "鞋履和配饰完全一致" in prompt
    assert "物种：人类" in prompt
    assert ScriptWriterAgent._needs_visual_enrichment("16岁女生，黑色长发，白色学生制服。", True) is True
    assert ScriptWriterAgent._needs_visual_enrichment(
        "16岁女生，椭圆脸，眉形自然，鼻梁纤细，唇形清楚，黑色长直发自然垂落，肤色白皙且保留自然皮肤纹理，身高中等、体型匀称。白色棉质衬衫叠穿藏蓝针织背心，下身为藏蓝百褶裙，搭配白色短袜和黑色皮质乐福鞋，固定识别点为整齐的侧分长发与窄领结。",
        True,
    ) is False


def test_seedream_parameter_and_safety_errors_are_actionable() -> None:
    assert "不支持本次请求参数" in public_image_error(
        RuntimeError("InvalidParameter: unsupportedParameter sequential_image_generation"),
        "Seedream",
    )
    assert "内容安全策略" in public_image_error(
        RuntimeError("OutputImageSensitiveContentDetected"),
        "Seedream",
    )
    assert is_retryable_media_error(TimeoutError("request timed out")) is True
    assert is_retryable_media_error(RuntimeError("401 unauthorized")) is False


def test_paid_media_stages_prepare_before_generation() -> None:
    base = {
        "session_id": "prepare-contract",
        "style": "realistic",
        "llm_model": "Qwen/Qwen2.5-72B-Instruct",
        "vlm_model": "Qwen/Qwen2.5-VL-72B-Instruct",
        "image_t2i_model": "doubao-seedream-5-0-260128",
        "image_it2i_model": "doubao-seedream-5-0-260128",
        "video_generation_mode": "first_frame",
        "video_first_frame_model": "doubao-seedance-2-0-260128",
        "enable_concurrency": False,
    }
    script_artifact = {
        "characters": [{"character_id": "char_1", "name": "小雨", "description": "16岁女生", "species": "人类"}],
        "settings": [{"setting_id": "set_1", "name": "天台", "description": "学校天台"}],
    }
    character_input = {
        **base,
        "_session_artifacts": {
            "script_generation": script_artifact,
            "character_design": {
                "characters": [{"id": "char_1", "reference_images": ["code/reference.png"]}],
                "settings": [],
            },
        },
    }
    character_result = asyncio.run(CharacterDesignerAgent().process(character_input))
    assert character_result["requires_intervention"] is True
    assert character_result["payload"]["generation_started"] is False
    assert character_result["payload"]["characters"][0]["reference_images"] == ["code/reference.png"]

    storyboard = {
        "episodes": [{
            "episode_number": 1,
            "segments": [{
                "segment_id": "seg_01_01",
                "episode_number": 1,
                "segment_number": 1,
                "location": "天台",
                "characters": ["小雨"],
                "shots": [{"content": "小雨走向栏杆", "duration": 5}],
                "total_duration": 5,
            }],
        }],
    }
    generated_character_artifact = {
        "characters": [{"id": "char_1", "name": "小雨", "selected": "code/char.png"}],
        "settings": [{"id": "set_1", "name": "天台", "selected": "code/set.png"}],
    }
    reference_input = {
        **base,
        "_session_artifacts": {
            "script_generation": script_artifact,
            "character_design": generated_character_artifact,
            "storyboard": storyboard,
            "reference_generation": {"scenes": []},
        },
    }
    reference_result = asyncio.run(ReferenceGeneratorAgent().process(reference_input))
    assert reference_result["requires_intervention"] is True
    assert reference_result["payload"]["generation_started"] is False

    video_input = {
        **base,
        "_session_artifacts": {
            "storyboard": storyboard,
            "character_design": generated_character_artifact,
            "reference_generation": {
                "scenes": [{"id": "seg_01_01", "selected": "code/scene.png"}],
            },
            "video_generation": {"clips": []},
        },
    }
    video_result = asyncio.run(VideoDirectorAgent().process(video_input))
    assert video_result["requires_intervention"] is True
    assert video_result["payload"]["generation_started"] is False


def test_video_generation_failure_is_actionable_and_persisted(tmp_path) -> None:
    agent = VideoDirectorAgent()
    missing_frame = tmp_path / "missing-frame.png"

    with pytest.raises(FileNotFoundError) as exc_info:
        agent._generate_one(
            "failure-contract",
            "seg_01_01",
            "镜头缓慢推进",
            str(missing_frame),
            "doubao-seedance-2-0-260128",
            duration=5,
        )

    message = public_video_error(exc_info.value, "视频模型")
    assert "记录存在，但文件已失效" in message

    payload = agent._build_payload(
        "failure-contract",
        [{
            "segment_id": "seg_01_01",
            "episode_number": 1,
            "segment_number": 1,
            "shots": [],
            "total_duration": 5,
        }],
        errors={"seg_01_01": message},
    )
    assert payload["payload"]["clips"][0]["status"] == "failed"
    assert payload["payload"]["clips"][0]["error"] == message


def test_seedance_submit_payload_omits_null_optional_parameters() -> None:
    payload = SeedanceVideoClient._build_submit_payload(
        "镜头缓慢推进",
        "data:image/png;base64,AAAA",
        "doubao-seedance-2-0-260128",
        5,
        ratio="16:9",
        resolution="720p",
        seed=None,
        watermark=None,
        generate_audio=None,
    )
    assert "seed" not in payload
    assert "watermark" not in payload
    assert "generate_audio" not in payload

    explicit = SeedanceVideoClient._build_submit_payload(
        "镜头缓慢推进",
        "data:image/png;base64,AAAA",
        "doubao-seedance-2-0-260128",
        5,
        watermark=False,
        generate_audio=False,
    )
    assert explicit["watermark"] is False
    assert explicit["generate_audio"] is False
