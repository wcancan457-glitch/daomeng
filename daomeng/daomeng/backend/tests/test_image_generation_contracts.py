from core.agents.character_agent import CharacterDesignerAgent
from core.agents.script_agent import ScriptWriterAgent
from models.image_seedream import supports_sequential_image_generation
from models.public_errors import public_image_error


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
