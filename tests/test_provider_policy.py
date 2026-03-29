"""Tests for worker.media.provider_policy cost estimation."""

from worker.media.provider_policy import estimate_scene_cost


def test_estimate_scene_cost_image_cheap():
    cost = estimate_scene_cost("image", "imagen", duration_sec=5.0)
    assert cost > 0


def test_estimate_scene_cost_tts_paid():
    cost = estimate_scene_cost("tts", "elevenlabs", duration_sec=5.0)
    assert cost > 0


def test_estimate_scene_cost_zero_for_free_provider():
    free_providers = [
        ("tts", "edge-tts"),
        ("tts", "windows-tts"),
        ("video", "wan"),
        ("bgm", "local-bgm"),
        ("sfx", "local-sfx"),
        ("sfx", "freesound"),
    ]
    for category, provider in free_providers:
        cost = estimate_scene_cost(category, provider, duration_sec=10.0)
        assert cost == 0.0, f"{category}/{provider} should be free but got {cost}"
