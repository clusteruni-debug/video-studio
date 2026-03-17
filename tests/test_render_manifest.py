"""Tests for worker.render.render_manifest."""

from worker.media.model_router import ProviderAvailability, route_project_plan, summarize_cost
from worker.planner.sample_plan import build_sample_project_plan
from worker.render.render_manifest import build_render_manifest


def _make_manifest():
    plan = build_sample_project_plan("test prompt", budget_mode="free")
    decisions = route_project_plan(plan, ProviderAvailability())
    return build_render_manifest(
        plan=plan,
        decisions=decisions,
        project_id="test-project",
        estimated_cost_usd=summarize_cost(decisions),
    )


def test_build_render_manifest_sets_motion_preset():
    manifest = _make_manifest()
    for scene in manifest.scenes:
        if scene.visualKind == "image":
            assert scene.motionPreset == "random"
        else:
            assert scene.motionPreset == "none"


def test_build_render_manifest_sets_transition_type():
    manifest = _make_manifest()
    assert manifest.transitionType == "fade"


def test_manifest_audio_provider_is_edge_tts():
    manifest = _make_manifest()
    for asset in manifest.assets:
        if asset.role == "audio":
            assert asset.provider == "edge-tts"


def test_manifest_has_sfx_assets():
    manifest = _make_manifest()
    sfx_assets = [a for a in manifest.assets if a.role == "sfx"]
    assert len(sfx_assets) == len(manifest.scenes)
    for sfx in sfx_assets:
        assert sfx.provider == "local-sfx"
        assert sfx.kind == "sfx"
        assert sfx.outputPath.endswith(".sfx.wav")
