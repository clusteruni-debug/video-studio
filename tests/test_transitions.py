"""Tests for worker.render.transitions filter builders."""

from pathlib import Path

from worker.render.transitions import build_xfade_filter_complex, gradient_source_filter


def test_xfade_filter_returns_valid_string():
    clips = [Path("a.mp4"), Path("b.mp4"), Path("c.mp4")]
    durations = [5.0, 5.0, 5.0]
    result = build_xfade_filter_complex(
        clip_paths=clips,
        durations=durations,
        transition_type="fade",
        transition_duration=0.5,
    )
    assert result is not None
    input_args, filter_complex = result
    assert len(input_args) > 0
    assert "xfade" in filter_complex


def test_single_clip_returns_none():
    result = build_xfade_filter_complex(
        clip_paths=[Path("a.mp4")],
        durations=[5.0],
        transition_type="fade",
        transition_duration=0.5,
    )
    assert result is None


def test_gradient_background_returns_filter():
    result = gradient_source_filter(0, size="1080x1920")
    assert "geq=" in result
