"""Tests for worker.render.motion zoompan filter presets."""

from worker.render.motion import MOTION_PRESETS, zoompan_filter


def test_all_presets_return_valid_filter_string():
    for preset in MOTION_PRESETS:
        result = zoompan_filter(preset=preset, duration_sec=5.0, fps=30, width=1080, height=1920)
        assert result is not None, f"preset '{preset}' returned None"
        assert "zoompan" in result, f"preset '{preset}' missing zoompan"


def test_random_preset_returns_one_of_known():
    result = zoompan_filter(preset="random", duration_sec=5.0, fps=30, width=1080, height=1920)
    assert result is not None
    assert "zoompan" in result


def test_none_preset_returns_none():
    result = zoompan_filter(preset="none", duration_sec=5.0, fps=30, width=1080, height=1920)
    assert result is None
