from __future__ import annotations

import pytest

from worker.render.reference_style_presets import (
    REFERENCE_STYLE_PRESETS,
    apply_reference_style_preset,
    choose_reference_style_preset,
    get_reference_style_preset,
)


def test_reference_style_presets_have_code_application_contract():
    required = {
        "key",
        "label",
        "region",
        "targetAudience",
        "templateTypes",
        "subtitleStyle",
        "captionPreset",
        "layoutVariantSequence",
        "sceneDurationSec",
        "referenceVideos",
        "editGrammar",
        "captionRules",
        "sourceRequirements",
        "goldSampleEvidence",
    }

    assert "kr_curiosity_explainer" in REFERENCE_STYLE_PRESETS
    assert "global_visual_magic" in REFERENCE_STYLE_PRESETS

    for key, preset in REFERENCE_STYLE_PRESETS.items():
        assert required <= set(preset), key
        assert preset["key"] == key
        assert preset["referenceVideos"], key
        assert all(item["url"].startswith("https://www.youtube.com/shorts/") for item in preset["referenceVideos"])
        assert preset["captionPreset"]["scene1"]
        assert preset["captionPreset"]["body"]
        assert preset["layoutVariantSequence"]
        assert preset["sceneDurationSec"]
        assert preset["editGrammar"]["firstSecond"]
        assert preset["editGrammar"]["payoff"]


def test_choose_reference_style_preset_prefers_explicit_audience():
    assert choose_reference_style_preset("persona_story", "kr_casual_curiosity_20_40") == "kr_curiosity_explainer"
    assert choose_reference_style_preset("news_explainer", "kr_maker_science_15_40") == "kr_maker_process"
    assert choose_reference_style_preset("vs_comparison", "") == "global_physical_demo"
    assert choose_reference_style_preset("unknown", "") == "kr_curiosity_explainer"


def test_apply_reference_style_preset_annotates_manifest_without_mutating_original():
    manifest = {
        "templateType": "news_explainer",
        "scenes": [
            {"title": "Hook", "subtitleText": "Why does this happen?"},
            {"title": "Evidence", "subtitleText": "The bottle changes under light."},
            {"title": "Answer", "subtitleText": "Heat and material explain it."},
        ],
    }

    styled = apply_reference_style_preset(manifest, "kr_curiosity_explainer")

    assert "referenceStylePreset" not in manifest
    assert "captionPreset" not in manifest["scenes"][0]

    assert styled["referenceStylePreset"] == "kr_curiosity_explainer"
    assert styled["targetAudience"] == "kr_casual_curiosity_20_40"
    assert styled["subtitleStyle"] == "news"
    assert styled["referenceStyleSummary"]["referenceUrls"]
    assert styled["referenceStyleSummary"]["goldSampleEvidence"]

    first, middle, last = styled["scenes"]
    assert first["captionPreset"] == "top-hook"
    assert first["caption_preset"] == "top-hook"
    assert first["layoutVariantKey"] == "headline-evidence"
    assert first["referenceEditRole"] == "hook-question"
    assert first["referenceTimingSec"] == 1.35

    assert middle["captionPreset"] == "lower-info"
    assert middle["layoutVariantKey"] == "chapter-evidence"
    assert middle["referenceEditRole"] == "mechanism"

    assert last["referenceEditRole"] == "answer"
    assert last["referenceSourceRequirement"]
    assert last["referenceCaptionRule"]


def test_apply_reference_style_preset_preserves_existing_fields_unless_overwrite():
    manifest = {
        "templateType": "news_explainer",
        "subtitleStyle": "minimal",
        "scenes": [
            {
                "captionPreset": "none",
                "caption_preset": "none",
                "layoutVariantKey": "custom-layout",
                "layout_variant_key": "custom-layout",
            }
        ],
    }

    preserved = apply_reference_style_preset(manifest, "kr_curiosity_explainer")
    assert preserved["subtitleStyle"] == "minimal"
    assert preserved["scenes"][0]["captionPreset"] == "none"
    assert preserved["scenes"][0]["layoutVariantKey"] == "custom-layout"

    overwritten = apply_reference_style_preset(manifest, "kr_curiosity_explainer", overwrite=True)
    assert overwritten["subtitleStyle"] == "news"
    assert overwritten["scenes"][0]["captionPreset"] == "top-hook"
    assert overwritten["scenes"][0]["layoutVariantKey"] == "headline-evidence"


def test_unknown_reference_style_preset_raises_with_known_keys():
    with pytest.raises(KeyError) as error:
        get_reference_style_preset("missing")

    assert "Unknown reference style preset" in str(error.value)
    assert "kr_curiosity_explainer" in str(error.value)
