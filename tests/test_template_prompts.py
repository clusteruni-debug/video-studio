from worker.bridge.scene_generator import normalize_scenes
from worker.bridge.templates import build_template_prompt


def test_authentic_vlog_prompt_is_visual_led_no_voice_contract():
    prompt = build_template_prompt(
        "퇴근 후 저녁 루틴",
        "Korean",
        "authentic_vlog",
        scene_count=5,
    )

    assert "visual_action" in prompt
    assert '"audio_design_mode": "no-voice"' in prompt
    assert "Default audio_design_mode MUST be \"no-voice\"" in prompt
    assert "full spoken text for TTS" not in prompt
    assert "Every narration MUST contain" not in prompt
    assert "첫 번째 컷은 입구가 아니라" not in prompt
    assert "observational voiceover" not in prompt


def test_persona_story_prompt_keeps_grok_continuity_without_production_notes():
    prompt = build_template_prompt(
        "직장인 캐릭터의 퇴근 루틴",
        "Korean",
        "persona_story",
        scene_count=5,
    )

    assert "same character, outfit, place, and prop continuity" in prompt
    assert "display_text/viewer_caption" in prompt
    assert "no explanatory TTS" in prompt
    assert "중요한 건 캐릭터가 매번" not in prompt
    assert "human narrator connection" not in prompt


def test_visual_led_normalization_maps_scene_fields_to_pipeline_contract():
    scenes = [{
        "scene_num": 1,
        "narration": "이 영상은 루틴을 조용하게 보여주려는 의도입니다.",
        "viewer_caption": "잠깐만\\n보자",
        "visual_action": "Same office persona pauses at the meeting-room door; hand motion starts immediately.",
        "emotion": "neutral",
    }]

    normalized = normalize_scenes(scenes, "직장인 캐릭터", "persona_story")
    scene = normalized[0]

    assert scene["narration"] == ""
    assert scene["display_text"] == "잠깐만\\n보자"
    assert scene["image_prompt"].startswith("Same office persona pauses")
    assert scene["audio_design_mode"] == "no-voice"
    assert scene["audioDesignMode"] == "no-voice"
    assert scene["caption_preset"] == "top-hook"
    assert scene["transition"] == "Dissolve"


def test_news_prompt_keeps_tts_script_contract():
    prompt = build_template_prompt(
        "삼성전자 실적 발표",
        "Korean",
        "news_explainer",
        scene_count=6,
    )

    assert "full spoken text for TTS" in prompt
    assert "Every narration MUST contain" in prompt
    assert "visual_action" in prompt
    assert "English image search query for Google Images" in prompt
    assert "image_prompt is used for Google Image Search" in prompt
    assert "Never feed a raw Google image search query into visual_action." in prompt
    assert "CONTROLLED CAMERA/STYLE LEXICON" in prompt


def test_normalize_scenes_adds_visual_action_without_overwriting_search_prompt():
    image_query = "Nike Air Max 1/97 Sean Wotherspoon sneaker"
    scenes = [{
        "scene_num": 1,
        "narration": "출시가가 16만원이었는데 지금 리셀가는 500만원을 넘겼어요.",
        "display_text": "500만원",
        "image_prompt": image_query,
    }]

    normalized = normalize_scenes(scenes, "세계에서 가장 비싼 운동화", "news_explainer")
    scene = normalized[0]

    assert scene["image_prompt"] == image_query
    assert scene["visual_action"]
    assert "first second motion" in scene["visual_action"]
    assert "phone-camera" in scene["visual_action"]
    assert image_query not in scene["visual_action"]
