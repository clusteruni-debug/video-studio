"""Reference-derived style presets for Video Studio render manifests.

These presets are intentionally opt-in. They codify benchmark grammar from
current Shorts references without changing the default render path.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

Preset = dict[str, Any]


REFERENCE_STYLE_PRESETS: dict[str, Preset] = {
    "kr_curiosity_explainer": {
        "key": "kr_curiosity_explainer",
        "label": "KR curiosity explainer",
        "region": "KR",
        "targetAudience": "kr_casual_curiosity_20_40",
        "templateTypes": ["news_explainer", "myth_buster", "tutorial_steps", "hot_take"],
        "subtitleStyle": "news",
        "captionPreset": {"scene1": "top-hook", "body": "lower-info"},
        "layoutVariantSequence": [
            "headline-evidence",
            "chapter-evidence",
            "hands-proof",
            "chapter-evidence",
            "grok-first-proof",
        ],
        "sceneDurationSec": [1.35, 3.2, 3.4, 3.2, 2.4],
        "referenceVideos": [
            {
                "label": "sagung-bottled-water-sunlight",
                "url": "https://www.youtube.com/shorts/mPWwMqDEiMo",
                "durationSec": 71,
            },
            {
                "label": "sagung-truck-eye-stickers",
                "url": "https://www.youtube.com/shorts/GgeZ8P3Ev7o",
                "durationSec": 76,
            },
            {
                "label": "just1min-japanese-snack-packaging",
                "url": "https://www.youtube.com/shorts/2CPpLbPAk8g",
                "durationSec": 28,
            },
        ],
        "editGrammar": {
            "sceneRoles": ["hook-question", "mechanism", "evidence", "implication", "answer"],
            "firstSecond": "Odd object or question is visible before explanation.",
            "payoff": "Answer the hook with a mechanism or implication, not a generic comment CTA.",
        },
        "captionRules": [
            "Korean viewer-facing text only.",
            "Top hook is 8-14 chars per line, max two lines.",
            "Body facts are lower-info chips with concrete nouns, numbers, or source terms.",
            "Never burn production notes or safe-zone wording into viewer captions.",
        ],
        "sourceRequirements": [
            "Every scene needs an object, source image/video, screen capture, map, data card, or diagram.",
            "Static public-domain illusion art is support material only unless the topic is explicitly optical-demo analysis.",
            "Prefer moving source or screen-capture proof over abstract stock backgrounds.",
        ],
        "goldSampleEvidence": [
            "reference row with at least two concrete URLs",
            "manifest referenceStylePreset",
            "first-second object/question proof",
            "caption safe-zone and subject occlusion proof",
            "contact sheet or phone-sized screenshot",
            "MP4 SHA-256 and ffprobe",
        ],
    },
    "kr_maker_process": {
        "key": "kr_maker_process",
        "label": "KR maker/process",
        "region": "KR",
        "targetAudience": "kr_maker_science_15_40",
        "templateTypes": ["authentic_vlog", "tutorial_steps", "before_after", "live_recap"],
        "subtitleStyle": "minimal",
        "captionPreset": {"scene1": "top-hook", "body": "lower-info"},
        "layoutVariantSequence": [
            "routine-top-hook",
            "hands-proof",
            "routine-lower-info",
            "hands-proof",
            "grok-first-proof",
        ],
        "sceneDurationSec": [1.35, 3.6, 3.6, 3.4, 2.6],
        "referenceVideos": [
            {
                "label": "sanago-small-popcorn-bucket",
                "url": "https://www.youtube.com/shorts/pdDSjlhxpxg",
                "durationSec": 55,
            },
            {
                "label": "sanago-moss-figure",
                "url": "https://www.youtube.com/shorts/8BDYu4o-SgQ",
                "durationSec": 47,
            },
            {
                "label": "geekble-practical-build",
                "url": "https://www.youtube.com/shorts/OGtEoCkYtC4",
                "durationSec": 58,
            },
        ],
        "editGrammar": {
            "sceneRoles": ["process-start", "material", "close-proof", "state-change", "reveal"],
            "firstSecond": "A hand, tool, material, or object-state change is already moving.",
            "payoff": "Show the finished state or a clear before/after reveal.",
        },
        "captionRules": [
            "Sparse labels only; the object and hands must remain readable.",
            "Use step chips or lower-info captions, not giant center text.",
            "Do not hide a phone screen, tool, hand, or object-state change.",
        ],
        "sourceRequirements": [
            "Direct footage, owned footage, or generated process continuity with visible hands/material/object state.",
            "Reject static slideshows that describe a build without showing process motion.",
        ],
        "goldSampleEvidence": [
            "process source proof",
            "close-up proof beat",
            "final reveal frame",
            "caption occlusion review",
            "contact sheet or phone-sized screenshot",
        ],
    },
    "kr_fast_entertainment": {
        "key": "kr_fast_entertainment",
        "label": "KR fast entertainment",
        "region": "KR",
        "targetAudience": "global_and_kr_comedy_feed",
        "templateTypes": ["persona_story", "authentic_vlog"],
        "subtitleStyle": "minimal",
        "captionPreset": {"scene1": "top-hook", "body": "none"},
        "layoutVariantSequence": [
            "grok-first-hook",
            "grok-first-continuity",
            "grok-first-proof",
        ],
        "sceneDurationSec": [1.2, 2.0, 1.8],
        "referenceVideos": [
            {
                "label": "kimpro-real-or-fake",
                "url": "https://www.youtube.com/shorts/lvhZbN3hePE",
                "durationSec": 19,
            },
            {
                "label": "kimpro-door-sound",
                "url": "https://www.youtube.com/shorts/HJQu5JAj_JE",
                "durationSec": 15,
            },
        ],
        "editGrammar": {
            "sceneRoles": ["action-hook", "escalation", "payoff"],
            "firstSecond": "Human action or prop gag starts immediately.",
            "payoff": "The gag must resolve visually without narration.",
        },
        "captionRules": [
            "Use no captions or one short hook only.",
            "The action carries the video; explanatory text is a failure.",
        ],
        "sourceRequirements": [
            "Actors, props, staged room, timing, and clean sound cue.",
            "Do not fake this with generic stock footage.",
        ],
        "goldSampleEvidence": [
            "action source proof",
            "sound cue proof",
            "visual payoff proof",
        ],
    },
    "global_visual_magic": {
        "key": "global_visual_magic",
        "label": "Global visual magic",
        "region": "Global",
        "targetAudience": "global_visual_magic_teen_adult",
        "templateTypes": ["persona_story", "authentic_vlog"],
        "subtitleStyle": "minimal",
        "captionPreset": {"scene1": "top-hook", "body": "none"},
        "layoutVariantSequence": [
            "grok-first-hook",
            "grok-first-continuity",
            "grok-first-proof",
        ],
        "sceneDurationSec": [1.1, 2.5, 2.0, 1.4],
        "referenceVideos": [
            {
                "label": "zach-king-floating-tree",
                "url": "https://www.youtube.com/shorts/tOIFZ8O6Ezk",
                "durationSec": 11,
            },
            {
                "label": "zach-king-leaf-blower",
                "url": "https://www.youtube.com/shorts/bJ1M8z-u-30",
                "durationSec": 13,
            },
        ],
        "editGrammar": {
            "sceneRoles": ["impossible-state", "setup", "trick", "reset"],
            "firstSecond": "The impossible visual state is visible immediately.",
            "payoff": "Reveal or reset must be visual, not narrated.",
        },
        "captionRules": [
            "Minimal captions or none.",
            "Never cover the actor, prop, or trick action.",
        ],
        "sourceRequirements": [
            "Actor, prop, location, camera plan, and hidden edit or VFX continuity.",
            "Static illusions and GIF loops cannot satisfy this preset.",
        ],
        "goldSampleEvidence": [
            "staged source plan",
            "camera continuity proof",
            "visual reveal proof",
        ],
    },
    "global_physical_demo": {
        "key": "global_physical_demo",
        "label": "Global physical demo",
        "region": "Global",
        "targetAudience": "global_physical_demo_15_45",
        "templateTypes": ["myth_buster", "tutorial_steps", "vs_comparison"],
        "subtitleStyle": "impact",
        "captionPreset": {"scene1": "top-hook", "body": "lower-info"},
        "layoutVariantSequence": [
            "headline-evidence",
            "hands-proof",
            "grok-first-proof",
            "chapter-evidence",
        ],
        "sceneDurationSec": [1.35, 3.0, 3.0, 2.2],
        "referenceVideos": [
            {
                "label": "mark-rober-magnus-effect",
                "url": "https://www.youtube.com/shorts/L0R-Ac1XRyk",
                "durationSec": 32,
            },
            {
                "label": "mark-rober-skyscraper-stability",
                "url": "https://www.youtube.com/shorts/3Y7o9IgliYk",
                "durationSec": 41,
            },
            {
                "label": "action-lab-feather-cube-fall",
                "url": "https://www.youtube.com/shorts/-bThN0otPMI",
                "durationSec": 26,
            },
        ],
        "editGrammar": {
            "sceneRoles": ["demo-question", "test", "replay-or-closeup", "answer"],
            "firstSecond": "The object, experiment, or result state is visible fast.",
            "payoff": "Show the measured outcome or visible mechanism.",
        },
        "captionRules": [
            "Use proof labels and short emphasis captions.",
            "Do not use paragraph narration over the experiment.",
        ],
        "sourceRequirements": [
            "Real experiment footage, generated simulation, or rights-safe lab/object demo footage.",
            "Replay or close-up labels require a real replay or close-up source.",
        ],
        "goldSampleEvidence": [
            "experiment source proof",
            "visible outcome proof",
            "replay or close-up proof",
            "caption occlusion review",
        ],
    },
    "global_toy_optical_demo": {
        "key": "global_toy_optical_demo",
        "label": "Global object optical demo",
        "region": "Global",
        "targetAudience": "toy_optical_curiosity",
        "templateTypes": ["myth_buster", "origin_story", "tutorial_steps"],
        "subtitleStyle": "minimal",
        "captionPreset": {"scene1": "top-hook", "body": "lower-info"},
        "layoutVariantSequence": [
            "object-mystery",
            "hands-proof",
            "grok-first-proof",
            "hands-proof",
        ],
        "sceneDurationSec": [1.35, 4.0, 3.5, 2.5],
        "referenceVideos": [
            {
                "label": "grand-illusions-shape-changing-pen",
                "url": "https://www.youtube.com/shorts/egS9iv1Vj0s",
                "durationSec": 59,
            },
            {
                "label": "grand-illusions-heart-metamorphosis",
                "url": "https://www.youtube.com/shorts/kQIWCcji03k",
                "durationSec": 53,
            },
        ],
        "editGrammar": {
            "sceneRoles": ["object-hook", "manipulation", "repeat-angle", "explanation"],
            "firstSecond": "The object is centered and inspectable immediately.",
            "payoff": "Repeat the transformation or reveal from a second angle.",
        },
        "captionRules": [
            "Captions stay sparse and away from the object.",
            "Hold long enough for inspection before cutting.",
        ],
        "sourceRequirements": [
            "Moving object demonstration with hands, rotation, or manipulation.",
            "Still images may support explanation but cannot be the whole video.",
        ],
        "goldSampleEvidence": [
            "object demo source proof",
            "second angle or repeat proof",
            "caption occlusion review",
        ],
    },
}


TEMPLATE_TYPE_DEFAULT_PRESETS: dict[str, str] = {
    "news_explainer": "kr_curiosity_explainer",
    "myth_buster": "kr_curiosity_explainer",
    "hot_take": "kr_curiosity_explainer",
    "podcast_clip": "kr_curiosity_explainer",
    "tutorial_steps": "kr_curiosity_explainer",
    "authentic_vlog": "kr_maker_process",
    "before_after": "kr_maker_process",
    "live_recap": "kr_maker_process",
    "persona_story": "global_visual_magic",
    "vs_comparison": "global_physical_demo",
    "origin_story": "global_toy_optical_demo",
}

AUDIENCE_DEFAULT_PRESETS: dict[str, str] = {
    "kr_casual_curiosity_20_40": "kr_curiosity_explainer",
    "korean_curiosity": "kr_curiosity_explainer",
    "kr_maker_science_15_40": "kr_maker_process",
    "korean_maker": "kr_maker_process",
    "global_visual_magic_teen_adult": "global_visual_magic",
    "visual_magic": "global_visual_magic",
    "global_physical_demo_15_45": "global_physical_demo",
    "physical_demo": "global_physical_demo",
    "toy_optical_curiosity": "global_toy_optical_demo",
}


def get_reference_style_presets() -> dict[str, Preset]:
    """Return all reference style presets as a copy."""
    return deepcopy(REFERENCE_STYLE_PRESETS)


def get_reference_style_preset(key: str) -> Preset:
    """Return one preset by key.

    Raises
    ------
    KeyError
        If the key is not registered.
    """
    normalized = _normalize_key(key)
    if normalized not in REFERENCE_STYLE_PRESETS:
        known = ", ".join(sorted(REFERENCE_STYLE_PRESETS))
        raise KeyError(f"Unknown reference style preset: {key!r}. Known presets: {known}")
    return deepcopy(REFERENCE_STYLE_PRESETS[normalized])


def choose_reference_style_preset(template_type: str = "", target_audience: str = "") -> str:
    """Choose the conservative default preset for a template/audience pair."""
    audience_key = _normalize_key(target_audience)
    if audience_key in AUDIENCE_DEFAULT_PRESETS:
        return AUDIENCE_DEFAULT_PRESETS[audience_key]

    template_key = _normalize_key(template_type)
    return TEMPLATE_TYPE_DEFAULT_PRESETS.get(template_key, "kr_curiosity_explainer")


def apply_reference_style_preset(
    manifest: dict[str, Any],
    preset_key: str = "",
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Return a copied manifest annotated with a reference style preset.

    The helper only fills missing style fields by default. Use ``overwrite=True``
    when a human explicitly wants to re-template an existing manifest.
    """
    styled = deepcopy(manifest)
    selected_key = preset_key or choose_reference_style_preset(
        str(styled.get("templateType") or styled.get("template_type") or ""),
        str(styled.get("targetAudience") or styled.get("target_audience") or ""),
    )
    preset = get_reference_style_preset(selected_key)

    _set_if_missing(styled, "referenceStylePreset", preset["key"], overwrite)
    _set_if_missing(styled, "targetAudience", preset["targetAudience"], overwrite)
    _set_if_missing(styled, "subtitleStyle", preset["subtitleStyle"], overwrite)
    styled["referenceStyleSummary"] = _summary_for_manifest(preset)

    scenes = styled.get("scenes")
    if not isinstance(scenes, list):
        return styled

    total = len(scenes)
    for idx, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        _apply_scene_reference_style(scene, preset, idx=idx, total=total, overwrite=overwrite)

    return styled


def _apply_scene_reference_style(
    scene: dict[str, Any],
    preset: Preset,
    *,
    idx: int,
    total: int,
    overwrite: bool,
) -> None:
    caption_preset = _caption_for_scene(preset, idx)
    layout_key = _sequence_value(preset["layoutVariantSequence"], idx)
    role = _scene_role(preset, idx, total)
    duration = _sequence_value(preset["sceneDurationSec"], idx)

    _set_if_missing(scene, "captionPreset", caption_preset, overwrite)
    _set_if_missing(scene, "caption_preset", caption_preset, overwrite)
    _set_if_missing(scene, "layoutVariantKey", layout_key, overwrite)
    _set_if_missing(scene, "layout_variant_key", layout_key, overwrite)
    _set_if_missing(scene, "referenceEditRole", role, overwrite)
    _set_if_missing(scene, "referenceTimingSec", duration, overwrite)
    _set_if_missing(scene, "referenceSourceRequirement", preset["sourceRequirements"][0], overwrite)
    _set_if_missing(scene, "referenceCaptionRule", preset["captionRules"][0], overwrite)


def _summary_for_manifest(preset: Preset) -> dict[str, Any]:
    return {
        "key": preset["key"],
        "label": preset["label"],
        "region": preset["region"],
        "targetAudience": preset["targetAudience"],
        "referenceUrls": [item["url"] for item in preset["referenceVideos"]],
        "firstSecondRule": preset["editGrammar"]["firstSecond"],
        "payoffRule": preset["editGrammar"]["payoff"],
        "sourceRequirements": list(preset["sourceRequirements"]),
        "goldSampleEvidence": list(preset["goldSampleEvidence"]),
    }


def _caption_for_scene(preset: Preset, idx: int) -> str:
    caption = preset["captionPreset"]
    if idx == 0:
        return str(caption.get("scene1") or "top-hook")
    body = str(caption.get("body") or "lower-info")
    if "none" in body and "lower-info" not in body:
        return "none"
    if "lower-info" in body:
        return "lower-info"
    return body.split()[0] if body.split() else "lower-info"


def _scene_role(preset: Preset, idx: int, total: int) -> str:
    roles = list(preset["editGrammar"].get("sceneRoles") or [])
    if not roles:
        return "scene"
    if idx == 0:
        return roles[0]
    if total > 1 and idx == total - 1:
        return roles[-1]
    middle = roles[1:-1] or roles[1:] or roles
    return str(_sequence_value(middle, max(0, idx - 1)))


def _sequence_value(values: list[Any], idx: int) -> Any:
    if not values:
        return None
    if idx < len(values):
        return values[idx]
    return values[-1]


def _set_if_missing(target: dict[str, Any], key: str, value: Any, overwrite: bool) -> None:
    if overwrite or not target.get(key):
        target[key] = value


def _normalize_key(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
