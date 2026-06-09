"""Episode routes for long-form shot planning infrastructure.

This module is intentionally additive. It creates local episode planning
artifacts under storage/episodes and prepares Grok handoff batch payloads
without changing the existing Grok, render, or final-library contracts.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request as flask_request

from worker.quality_gate_system import build_episode_gate_system, build_quality_loop_gate_system, gate_system_registry
from worker.render.render_manifest import slugify

episodes_bp = Blueprint("episodes", __name__)

_project_root: Path = Path.cwd()
_safe_resolve = None
_bridge_host: str = "127.0.0.1"
_bridge_port: int = 5161


class OutputGateBlocked(ValueError):
    def __init__(self, message: str, output_gate: dict[str, Any]):
        super().__init__(message)
        self.output_gate = output_gate


DEFAULT_BATCH_SIZE = 6
GEMINI_WEB_URL = "https://gemini.google.com/app"
GROK_WEB_URL = "https://grok.com/imagine"
PHASE_LIMITS = {
    "phase1": {"maxCuts": 24, "recommendedCuts": "12", "label": "12-cut / 2-minute pilot"},
    "phase2": {"maxCuts": 48, "recommendedCuts": "30-40", "label": "30-40-cut / 5-7-minute segment"},
    "phase3": {"maxCuts": 120, "recommendedCuts": "80-100", "label": "80-100-cut / 12-15-minute build"},
    "phase4": {"maxCuts": 280, "recommendedCuts": "180-250", "label": "180-250-cut / 30-minute production"},
}
CUT_ROLES = {"a_roll", "b_roll", "transition", "establishing", "reaction", "exclude"}
SOURCE_STATUSES = {"planned", "prompt_ready", "source_generating", "source_review", "accepted", "regenerate_needed", "excluded"}
SYNC_STATUSES = {"planned", "sync_ready", "segment_rendered", "final_packet_ready"}
PREPRODUCTION_BEAT_ROLES = {
    "hook",
    "context",
    "evidence",
    "action",
    "contrast",
    "payoff",
    "cta",
}
PREPRODUCTION_ASSET_PROVIDERS = {"gemini-web-image", "grok-web-video", "operator-owned-source"}
PREPRODUCTION_MOTION_SOURCE_PROVIDERS = {"grok-web-video", "operator-owned-source"}
PREPRODUCTION_IMAGE_REFERENCE_PROVIDERS = {"gemini-web-image"}
ASSET_REVIEW_REQUIRED_FLAGS = {
    "storyboardMatch": "candidate must match the storyboard beat",
    "artifactFree": "candidate must be free of obvious AI artifacts",
    "captionSafe": "candidate must leave room for the planned caption layout",
    "phoneSizeWatch": "candidate must be reviewed at phone size",
    "sourceProvenanceOk": "candidate needs operator-visible source provenance",
}
MOTION_REVIEW_REQUIRED_FLAGS = {
    "firstSecondAction": "motion source must show the storyboard action in the first second",
    "noGenericBroll": "motion source must not be generic filler B-roll",
}
QUALITY_RATCHET_REQUIRED_FIELDS = (
    "previousBaseline",
    "rejectionCause",
    "changedLever",
    "expectedVisibleImprovement",
    "actualProof",
    "nextRatchet",
)
QUALITY_LOOP_STANDARD_VERSION = "2026-06-08-production-gate-quality-loop-v3"
QUALITY_LOOP_REQUIRED_CONTRACTS = (
    {"contractKey": "policy", "gateKey": "policyStandard", "label": "Policy standard exists", "stage": "policy"},
    {"contractKey": "topicContract", "gateKey": "topicStandard", "label": "Topic standard exists", "stage": "topic"},
    {"contractKey": "promptContract", "gateKey": "promptStandard", "label": "Prompt standard exists", "stage": "prompt"},
    {"contractKey": "outputContract", "gateKey": "outputStandard", "label": "Output standard exists", "stage": "source"},
    {"contractKey": "captionLayoutContract", "gateKey": "captionLayoutStandard", "label": "Caption and layout standard exists", "stage": "caption-layout"},
    {"contractKey": "voiceAudioContract", "gateKey": "voiceAudioStandard", "label": "Voice and audio standard exists", "stage": "voice-audio"},
    {"contractKey": "editRhythmContract", "gateKey": "editRhythmStandard", "label": "Edit rhythm standard exists", "stage": "edit-rhythm"},
    {"contractKey": "renderReviewContract", "gateKey": "renderReviewStandard", "label": "Render review standard exists", "stage": "render-review"},
    {"contractKey": "publishReviewContract", "gateKey": "publishReviewStandard", "label": "Phone and publish review standard exists", "stage": "publish"},
    {"contractKey": "iterationContract", "gateKey": "iterationStandard", "label": "Iteration standard exists", "stage": "iteration"},
    {"contractKey": "resumeContract", "gateKey": "resumeStandard", "label": "Resume standard exists", "stage": "resume"},
)
QUALITY_LOOP_STAGES = {
    "topic",
    "storyboard",
    "prompt",
    "reference-image",
    "motion-source",
    "asset-review",
    "render",
    "voice",
    "audio",
    "bgm",
    "edit-rhythm",
    "caption",
    "layout",
    "render-review",
    "phone-review",
    "publish",
}
QUALITY_LOOP_STATUSES = {"planned", "pass", "fail", "blocked", "needs-spec-change"}
QUALITY_LOOP_FAILURE_STATUSES = {"fail", "blocked", "needs-spec-change"}
GENERIC_TOPIC_TERMS = {
    "routine",
    "reset",
    "motivation",
    "productivity",
    "healing",
    "vibe",
    "office worker",
    "korean office worker",
    "한국 사무실 직장인",
    "퇴근 후 루틴",
}


def init_episode_routes(project_root: Path, safe_resolve, bridge_host: str = "127.0.0.1", bridge_port: int = 5161) -> None:
    global _project_root, _safe_resolve, _bridge_host, _bridge_port
    _project_root = project_root
    _safe_resolve = safe_resolve
    _bridge_host = bridge_host
    _bridge_port = int(bridge_port)


def _utc_now() -> str:
    return datetime.now().astimezone().isoformat()


def _episode_base_dir() -> Path:
    return _project_root / "storage" / "episodes"


def _episode_id(value: object) -> str:
    candidate = slugify(str(value or "").strip())
    return candidate or f"episode-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _episode_dir(episode_id: str) -> Path:
    return _episode_base_dir() / _episode_id(episode_id)


def _duration(value: object, fallback: float = 8.0) -> float:
    try:
        return round(max(1.0, min(float(value), 60.0)), 2)
    except (TypeError, ValueError):
        return fallback


def _text(value: object, fallback: str = "") -> str:
    return str(value if value is not None else fallback).strip()


def _short_text(value: object, fallback: str = "", limit: int = 240) -> str:
    text = str(value if value is not None else fallback).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _prompt_fragment(value: object, fallback: str = "", limit: int = 180) -> str:
    text = str(value if value is not None else fallback).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].strip(" ,;:-.")
    return text.strip().rstrip(".!?。？！")


def _list(value: object) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _planned_text_card(value: object) -> dict[str, Any]:
    def card_mode(raw: object) -> str:
        mode = _text(raw, "full-card").lower().replace("_", "-").strip()
        aliases = {
            "chapter-card": "full-card",
            "text-card": "full-card",
            "hard-card": "full-card",
            "micro": "micro-transition",
            "transition": "micro-transition",
            "transition-overlay": "overlay",
            "overlay-chip": "overlay",
        }
        mode = aliases.get(mode, mode)
        if mode not in {"full-card", "overlay", "micro-transition"}:
            return "full-card"
        return mode

    def card_duration(raw: object, mode: str) -> float:
        fallback = 0.24 if mode in {"overlay", "micro-transition"} else 0.62
        if raw in (None, ""):
            return fallback
        try:
            return round(max(0.2, min(float(raw), 5.0)), 2)
        except (TypeError, ValueError):
            return fallback

    if isinstance(value, dict):
        text = _text(value.get("text") or value.get("displayText") or value.get("display_text"))
        if not text:
            return {}
        mode = card_mode(value.get("mode") or value.get("cardMode") or value.get("transitionMode"))
        return {
            "text": text,
            "durationSec": card_duration(value.get("durationSec") or value.get("duration_sec"), mode),
            "mode": mode,
            "audioPolicy": _text(
                value.get("audioPolicy") or value.get("audio_policy") or value.get("soundPolicy"),
                "continuous-bgm-bed" if mode in {"overlay", "micro-transition"} else "editor-managed-audio-bed",
            ),
            "purpose": _text(value.get("purpose"), "planned edit-rhythm transition cue"),
            "placement": _text(value.get("placement"), "between-this-beat-and-next-source-clip"),
        }
    text = _text(value)
    if not text:
        return {}
    return {
        "text": text,
        "durationSec": 0.62,
        "mode": "full-card",
        "audioPolicy": "editor-managed-audio-bed",
        "purpose": "planned edit-rhythm transition cue",
        "placement": "between-this-beat-and-next-source-clip",
    }


def _planned_text_card_clause(card: dict[str, Any]) -> str:
    if not card:
        return ""
    mode = _text(card.get("mode"), "full-card")
    duration = card.get("durationSec", 0.24 if mode in {"overlay", "micro-transition"} else 0.62)
    card_text = _prompt_fragment(card.get("text"), limit=80)
    audio_policy = _prompt_fragment(card.get("audioPolicy"), "continuous-bgm-bed", limit=80)
    if mode in {"overlay", "micro-transition"}:
        label = "overlay chapter cue" if mode == "overlay" else "micro-transition chapter cue"
        return (
            "Edit rhythm: after this source clip, the editor will add a "
            f"{duration}s {label} reading \"{card_text}\" while the BGM/audio bed continues uninterrupted "
            f"(audio policy: {audio_policy}). "
            "Keep this source clip self-contained, end on a clean object or action state, "
            "and leave simple negative space for an editor overlay. "
            "Do not render that chapter-card text inside the source clip."
        )
    return (
        "Edit rhythm: after this source clip, the editor will insert a "
        f"{duration}s text-only chapter card reading "
        f"\"{card_text}\" (audio policy: {audio_policy}). "
        "Keep this source clip self-contained and end on a clean object or action state. "
        "Do not render that chapter-card text inside the source clip."
    )


def _sync_asset_plan_text_card(asset_plan: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    clause = _planned_text_card_clause(card)
    if not clause:
        return asset_plan
    stale_clause = re.compile(
        r"\s*Edit rhythm: after this source clip, the editor will (?:insert|add) a .*?"
        r"Do not render that chapter-card text inside the source clip\.",
        re.DOTALL,
    )
    for provider_key in ("geminiWebImage", "grokWebVideo"):
        provider_plan = asset_plan.get(provider_key)
        if not isinstance(provider_plan, dict):
            continue
        prompt = _text(provider_plan.get("prompt"))
        prompt = stale_clause.sub("", prompt).strip()
        provider_plan["prompt"] = f"{prompt} {clause}".strip()
    return asset_plan


def _script_blocks(data: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = data.get("scriptBlocks") or data.get("script_blocks") or []
    if not isinstance(blocks, list):
        blocks = []
    normalized: list[dict[str, Any]] = []
    for index, block in enumerate(blocks, start=1):
        if not isinstance(block, dict):
            block = {"text": str(block)}
        block_id = _text(block.get("blockId") or block.get("block_id"), f"B{index:02d}")
        normalized.append({
            "blockId": block_id,
            "title": _text(block.get("title"), block_id),
            "text": _text(block.get("text") or block.get("script") or block.get("narration")),
            "targetDurationSec": _duration(
                block.get("targetDurationSec") or block.get("target_duration_sec"),
                0.0,
            ),
        })
    return normalized


def _character_bible_markdown(data: dict[str, Any]) -> str:
    value = data.get("characterBible") or data.get("character_bible") or data.get("characters") or ""
    if isinstance(value, str):
        return value.strip() or "# Character Bible\n\n- Define recurring characters before generating shots.\n"
    if isinstance(value, list):
        lines = ["# Character Bible", ""]
        for item in value:
            if isinstance(item, dict):
                name = _text(item.get("name") or item.get("id"), "Character")
                lines.append(f"## {name}")
                for key, entry in item.items():
                    if key in {"name", "id"}:
                        continue
                    lines.append(f"- {key}: {entry}")
                lines.append("")
            else:
                lines.append(f"- {item}")
        return "\n".join(lines).strip() + "\n"
    if isinstance(value, dict):
        lines = ["# Character Bible", ""]
        for key, entry in value.items():
            lines.append(f"## {key}")
            if isinstance(entry, dict):
                for field, field_value in entry.items():
                    lines.append(f"- {field}: {field_value}")
            else:
                lines.append(f"- {entry}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"
    return "# Character Bible\n\n- Define recurring characters before generating shots.\n"


def _shot_source(data: dict[str, Any]) -> list[dict[str, Any]]:
    shots = data.get("shots") or data.get("shotPlan") or data.get("shot_plan") or data.get("draftScenes")
    return shots if isinstance(shots, list) else []


def _fallback_script(blocks: list[dict[str, Any]], index: int) -> tuple[str, str]:
    if not blocks:
        return "B01", ""
    block = blocks[min(index, len(blocks) - 1)]
    return str(block["blockId"]), str(block.get("text") or "")


def _normalize_shots(data: dict[str, Any], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    shots = _shot_source(data)
    normalized: list[dict[str, Any]] = []
    for zero_index, item in enumerate(shots):
        if not isinstance(item, dict):
            item = {"scene": str(item)}
        index = zero_index + 1
        cut_id = _text(item.get("cutId") or item.get("cut_id"), f"cut_{index:03d}")
        scene_id = _text(item.get("sceneId") or item.get("scene_id"), f"scene-{index:03d}")
        block_id, fallback_script = _fallback_script(blocks, zero_index)
        assigned_script = _text(
            item.get("assignedScript")
            or item.get("assigned_script")
            or item.get("narration")
            or item.get("subtitleText")
            or item.get("script"),
            fallback_script,
        )
        planned_duration = _duration(
            item.get("plannedDurationSec")
            or item.get("planned_duration_sec")
            or item.get("durationSec")
            or item.get("duration"),
            8.0,
        )
        role = _text(item.get("role") or item.get("status"), "a_roll").lower()
        if role not in CUT_ROLES:
            role = "a_roll"
        source_status = _text(item.get("sourceStatus") or item.get("source_status"), "planned").lower()
        if source_status not in SOURCE_STATUSES:
            source_status = "planned"
        sync_status = _text(item.get("syncStatus") or item.get("sync_status"), "planned").lower()
        if sync_status not in SYNC_STATUSES:
            sync_status = "planned"
        normalized.append({
            "cutId": cut_id,
            "sceneId": scene_id,
            "blockId": _text(item.get("blockId") or item.get("block_id"), block_id),
            "role": role,
            "scene": _text(item.get("scene") or item.get("title") or item.get("scenePurpose")),
            "characters": _list(item.get("characters") or item.get("characterRefs") or item.get("character_refs")),
            "allowedLocation": _text(item.get("allowedLocation") or item.get("allowed_location")),
            "forbiddenLocations": _list(item.get("forbiddenLocations") or item.get("forbidden_locations")),
            "plannedDurationSec": planned_duration,
            "assignedScript": assigned_script,
            "imagePrompt": _text(item.get("imagePrompt") or item.get("image_prompt")),
            "grokPrompt": _text(item.get("grokPrompt") or item.get("grok_prompt") or item.get("prompt")),
            "promptProfile": _text(item.get("promptProfile") or item.get("prompt_profile")),
            "visualAction": _text(item.get("visualAction") or item.get("visual_action")),
            "sourceNeed": _text(item.get("sourceNeed") or item.get("source_need")),
            "topicAngle": _text(item.get("topicAngle") or item.get("topic_angle")),
            "audience": _text(item.get("audience")),
            "whyNow": _text(item.get("whyNow") or item.get("why_now")),
            "hookNote": _text(item.get("hookNote") or item.get("hook_note")),
            "continuityNote": _text(item.get("continuityNote") or item.get("continuity_note")),
            "layoutVariantNote": _text(item.get("layoutVariantNote") or item.get("layout_variant_note")),
            "plannedTextCardAfter": _planned_text_card(
                item.get("plannedTextCardAfter")
                or item.get("planned_text_card_after")
                or item.get("plannedTransitionAfter")
                or item.get("planned_transition_after")
                or item.get("transitionCueAfter")
                or item.get("transition_cue_after")
                or item.get("textCardAfter")
                or item.get("chapterCardAfter")
            ),
            "captionPreset": _text(item.get("captionPreset") or item.get("caption_preset"), "lower-info"),
            "sourceStatus": source_status,
            "syncStatus": sync_status,
            "stableCutImageName": f"{cut_id}.png",
            "stableCutVideoName": f"{cut_id}.mp4",
            "grokExpectedFileName": f"{scene_id}.grok.mp4",
            "ttsSegmentId": f"seg_{index:03d}",
            "reviewFlags": _list(item.get("reviewFlags") or item.get("review_flags")),
        })
    return normalized


def _shortform_grok_prompt(cut: dict[str, Any]) -> str:
    action = cut.get("visualAction") or cut.get("grokPrompt") or cut.get("scene") or cut.get("assignedScript")
    allowed = cut.get("allowedLocation") or "a real location matching the topic"
    audience = cut.get("audience") or "the intended viewer"
    purpose = cut.get("sourceNeed") or cut.get("topicAngle") or cut.get("hookNote") or "make the beat visible"
    text_card_clause = _planned_text_card_clause(cut.get("plannedTextCardAfter") or {})
    parts = [
        "Raw vertical 9:16 phone-camera MP4, 4-6 seconds.",
        f"First second: {_prompt_fragment(action, limit=180)}.",
        f"Setting: {_prompt_fragment(allowed, limit=110)}.",
        f"Subject: {_prompt_fragment(audience, limit=90)}.",
        f"Purpose: {_prompt_fragment(purpose, limit=150)}.",
        "One continuous handheld shot, natural light, imperfect real-world framing.",
    ]
    if text_card_clause:
        parts.append(text_card_clause)
    parts.append(
        "No montage, no glossy commercial lighting, no readable text, logo, watermark, or subtitle.",
    )
    return " ".join(parts)


def _default_grok_prompt(cut: dict[str, Any], character_bible: str) -> str:
    if cut.get("promptProfile") == "storyboard-first-shortform":
        return _shortform_grok_prompt(cut)
    base = cut.get("grokPrompt") or cut.get("imagePrompt") or cut.get("scene") or cut.get("assignedScript")
    continuity = cut.get("continuityNote") or "preserve the same recurring character, props, location, palette, and camera language"
    allowed = cut.get("allowedLocation") or "the planned location only"
    forbidden = ", ".join(str(item) for item in cut.get("forbiddenLocations") or [])
    parts = [
        "Long-form Korean story raw footage for editing.",
        str(base).strip(),
        f"Location lock: {allowed}.",
        f"Continuity lock: {continuity}.",
        "Preserve character identity, hair, clothing, age, props, and room.",
        "Slow cinematic movement only. No scene cut. No readable text, logo, watermark, or subtitle.",
    ]
    if forbidden:
        parts.append(f"Do not add or switch to: {forbidden}.")
    if character_bible.strip():
        excerpt = " ".join(character_bible.strip().split())[:360]
        parts.append(f"Character bible excerpt: {excerpt}")
    return " ".join(part for part in parts if part)


def _shortform_image_prompt(cut: dict[str, Any]) -> str:
    action = cut.get("visualAction") or cut.get("imagePrompt") or cut.get("scene") or cut.get("assignedScript")
    allowed = cut.get("allowedLocation") or "a real location matching the topic"
    audience = cut.get("audience") or "the intended viewer"
    angle = cut.get("topicAngle") or cut.get("sourceNeed") or cut.get("hookNote") or "storyboard reference"
    text_card_clause = _planned_text_card_clause(cut.get("plannedTextCardAfter") or {})
    parts = [
        "Vertical 9:16 reference image for a short-form video storyboard.",
        f"Moment: {_prompt_fragment(action, limit=180)}.",
        f"Setting: {_prompt_fragment(allowed, limit=110)}.",
        f"Subject: {_prompt_fragment(audience, limit=90)}.",
        f"Editorial angle: {_prompt_fragment(angle, limit=150)}.",
        "Natural phone-photo realism with caption-safe lower and right-side space.",
    ]
    if text_card_clause:
        parts.append(text_card_clause)
    parts.append(
        "No readable text, logo, watermark, or subtitle.",
    )
    return " ".join(parts)


def _default_image_prompt(cut: dict[str, Any], character_bible: str) -> str:
    if cut.get("promptProfile") == "storyboard-first-shortform":
        return _shortform_image_prompt(cut)
    base = cut.get("imagePrompt") or cut.get("scene") or cut.get("assignedScript")
    allowed = cut.get("allowedLocation") or "the planned location only"
    forbidden = ", ".join(str(item) for item in cut.get("forbiddenLocations") or [])
    parts = [
        "Reference image for a long-form Korean story video cut.",
        str(base).strip(),
        f"Location lock: {allowed}.",
        "Keep the same recurring character identity, age, hair, clothing, props, lens, and lighting.",
        "Vertical 9:16 composition, realistic still frame, no readable text, logo, watermark, or subtitles.",
    ]
    if forbidden:
        parts.append(f"Do not add or switch to: {forbidden}.")
    if character_bible.strip():
        excerpt = " ".join(character_bible.strip().split())[:360]
        parts.append(f"Character bible excerpt: {excerpt}")
    return " ".join(part for part in parts if part)


def _cut_number(value: object, fallback: int) -> int:
    matches = re.findall(r"\d+", str(value or ""))
    if not matches:
        return fallback
    return max(1, int(matches[-1]))


def _batch_manifests(
    episode_id: str,
    cuts: list[dict[str, Any]],
    batch_size: int,
    template_type: str,
    character_bible: str,
) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    batch_size = max(1, min(batch_size, 12))
    for index in range(0, len(cuts), batch_size):
        batch_number = len(batches) + 1
        batch_id = f"batch-{batch_number:03d}"
        batch_cuts = cuts[index:index + batch_size]
        draft_scenes: list[dict[str, Any]] = []
        for cut in batch_cuts:
            scene_num = _cut_number(cut["cutId"], len(draft_scenes) + 1)
            draft_scenes.append({
                "sceneId": cut["sceneId"],
                "scene_num": scene_num,
                "title": cut["scene"] or cut["cutId"],
                "display_text": cut["scene"] or cut["assignedScript"][:40],
                "narration": cut["assignedScript"],
                "image_source": "grok",
                "grok_prompt": _default_grok_prompt(cut, character_bible),
                "visual_prompt": cut.get("visualAction") or "",
                "visual_action": cut.get("visualAction") or "",
                "hook_note": cut.get("hookNote") or "visible action begins in the first two seconds",
                "continuity_note": cut.get("continuityNote") or "same character/place/prop continuity as the episode bible",
                "layout_variant_note": cut.get("layoutVariantNote") or "leave caption-safe lower third and right-side platform UI zone clear",
                "planned_text_card_after": cut.get("plannedTextCardAfter") or {},
                "caption_preset": cut.get("captionPreset") or "lower-info",
                "duration": cut["plannedDurationSec"],
            })
        batches.append({
            "batchId": batch_id,
            "cutIds": [cut["cutId"] for cut in batch_cuts],
            "sceneIds": [cut["sceneId"] for cut in batch_cuts],
            "plannedDurationSec": round(sum(float(cut["plannedDurationSec"]) for cut in batch_cuts), 2),
            "handoffProjectId": f"{episode_id}-{batch_id}",
            "handoffRequest": {
                "projectId": f"{episode_id}-{batch_id}",
                "templateType": template_type,
                "targetDuration": f"{round(sum(float(cut['plannedDurationSec']) for cut in batch_cuts), 1)}s",
                "qualityGateRequired": True,
                "grokMainSourceRequired": True,
                "draftScenes": draft_scenes,
            },
        })
    return batches


def _gemini_image_handoff_batches(
    episode_dir: Path,
    episode_id: str,
    cuts: list[dict[str, Any]],
    batch_size: int,
    character_bible: str,
    output_gate: dict[str, Any],
) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    batch_size = max(1, min(batch_size, 12))
    for index in range(0, len(cuts), batch_size):
        batch_number = len(batches) + 1
        batch_id = f"batch-{batch_number:03d}"
        batch_cuts = cuts[index:index + batch_size]
        batches.append({
            "schema": "video-studio.browser-handoff.gemini-image.v1",
            "provider": "gemini-web-image",
            "stage": "image-reference",
            "mode": "browser-extension-semi-auto",
            "usesApi": False,
            "usesPaidApi": False,
            "requiresOperatorBrowserSession": True,
            "targetUrl": GEMINI_WEB_URL,
            "browserControlPolicy": _browser_control_policy("gemini-web-image"),
            "companion": {
                "extension": "Video Studio AI Web Companion",
                "extensionDir": "tools/chrome-grok-companion",
                "providerAdapter": "gemini-web-image",
                "canFillPrompt": True,
                "canClickGenerate": False,
                "canImportResult": False,
                "eventEndpoint": _episode_extension_event_url(episode_id),
                "operatorAction": "Open the autostartUrl in the signed-in Gemini Chrome profile, then review and manually generate/save the image.",
            },
            "batchId": batch_id,
            "episodeId": episode_id,
            "outputDir": str(episode_dir / "images_gemini"),
            "reviewGate": "image-review-before-grok-video",
            "promptOutputGate": output_gate,
            "operatorChecklist": [
                "Use the existing signed-in browser session; do not configure API keys for this handoff.",
                "Generate images in small batches, then save or upload them with the expected cut file names.",
                "Reject character, clothing, location, logo/text, or forbidden-location drift before video generation.",
            ],
            "cuts": [
                (
                    lambda command_url: {
                        "cutId": cut["cutId"],
                        "sceneId": cut["sceneId"],
                        "expectedFileName": cut["stableCutImageName"],
                        "prompt": _default_image_prompt(cut, character_bible),
                        "allowedLocation": cut.get("allowedLocation") or "",
                        "forbiddenLocations": cut.get("forbiddenLocations") or [],
                        "plannedTextCardAfter": cut.get("plannedTextCardAfter") or {},
                        "reviewStatus": "pending-image-review",
                        "promptOutputGate": output_gate,
                        "extensionCommandUrl": command_url,
                        "autostartUrl": _gemini_autostart_url(command_url),
                    }
                )(_gemini_extension_command_url(episode_id, batch_id, cut["cutId"]))
                for cut in batch_cuts
            ],
        })
    return batches


def _browser_handoff_plan(
    episode_dir: Path,
    episode_id: str,
    cuts: list[dict[str, Any]],
    grok_batches: list[dict[str, Any]],
    batch_size: int,
    character_bible: str,
    output_gate: dict[str, Any],
) -> dict[str, Any]:
    gemini_batches = _gemini_image_handoff_batches(
        episode_dir,
        episode_id,
        cuts,
        batch_size,
        character_bible,
        output_gate,
    )
    grok_video_batches = [
        {
            "schema": "video-studio.browser-handoff.grok-video.v1",
            "provider": "grok-web-video",
            "stage": "image-to-video-or-text-to-video",
            "mode": "browser-extension-semi-auto",
            "usesApi": False,
            "usesPaidApi": False,
            "requiresOperatorBrowserSession": True,
            "targetUrl": GROK_WEB_URL,
            "browserControlPolicy": _browser_control_policy("grok-web-video"),
            "batchId": batch["batchId"],
            "episodeId": episode_id,
            "handoffProjectId": batch["handoffProjectId"],
            "handoffRequest": batch["handoffRequest"],
            "reviewGate": "mp4-direct-import-review-before-render",
            "promptOutputGate": output_gate,
            "operatorChecklist": [
                "Use the Video Studio Grok Companion or bookmarklet from the existing signed-in Chrome profile.",
                "Open Grok Imagine, not a normal chat thread, before Prep + Generate.",
                "Direct-import or manually batch-upload generated MP4s, then accept/reject each cut before render.",
            ],
        }
        for batch in grok_batches
    ]
    return {
        "schema": "video-studio.episode-browser-handoffs.v1",
        "episodeId": episode_id,
        "mode": "codex-browser-extension-semi-auto",
        "usesApi": False,
        "usesPaidApi": False,
        "requiresOperatorBrowserSession": True,
        "outputGate": output_gate,
        "browserControlPolicy": {
            "geminiWebImage": _browser_control_policy("gemini-web-image"),
            "grokWebVideo": _browser_control_policy("grok-web-video"),
        },
        "stages": [
            "gemini-web-image-reference",
            "image-review",
            "grok-web-video-generation",
            "mp4-direct-import-review",
            "shot-sync-render",
        ],
        "providers": {
            "geminiWebImage": {
                "provider": "gemini-web-image",
                "status": "queue-ready",
                "extensionCommandReady": True,
                "canFillPrompt": True,
                "canClickGenerate": False,
                "browserControlPolicy": _browser_control_policy("gemini-web-image"),
                "eventLogPath": str(episode_dir / "browser-handoffs" / "extension-events.jsonl"),
                "batchCount": len(gemini_batches),
                "batches": [
                    {
                        "batchId": batch["batchId"],
                        "provider": batch["provider"],
                        "cutIds": [cut["cutId"] for cut in batch["cuts"]],
                        "handoffPath": str(episode_dir / "browser-handoffs" / "gemini-web-image" / f"{batch['batchId']}.json"),
                    }
                    for batch in gemini_batches
                ],
            },
            "grokWebVideo": {
                "provider": "grok-web-video",
                "status": "queue-ready",
                "browserControlPolicy": _browser_control_policy("grok-web-video"),
                "batchCount": len(grok_video_batches),
                "batches": [
                    {
                        "batchId": batch["batchId"],
                        "provider": batch["provider"],
                        "handoffProjectId": batch["handoffProjectId"],
                        "sceneIds": [scene.get("sceneId") for scene in batch["handoffRequest"].get("draftScenes") or []],
                        "handoffPath": str(episode_dir / "browser-handoffs" / "grok-web-video" / f"{batch['batchId']}.json"),
                    }
                    for batch in grok_video_batches
                ],
            },
            "geminiWebVideo": {
                "provider": "gemini-web-video",
                "status": "planned-only",
                "reason": "Gemini/Veo browser video handoff must stay operator-owned and separate from paid API adapters until a provider-specific extension surface is verified. The shared web companion may fill prompt text only after a provider adapter is added; it must not click paid/video generation controls by default.",
                "usesApi": False,
                "usesPaidApi": False,
            },
        },
        "batches": {
            "geminiWebImage": gemini_batches,
            "grokWebVideo": grok_video_batches,
        },
    }


def _validate_sync_map(sync_map: dict[str, Any]) -> dict[str, Any]:
    cuts = sync_map.get("cuts") if isinstance(sync_map.get("cuts"), list) else []
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    cut_ids: set[str] = set()
    scene_ids: set[str] = set()
    block_durations: dict[str, float] = {}

    for index, cut in enumerate(cuts, start=1):
        cut_id = str(cut.get("cutId") or "")
        scene_id = str(cut.get("sceneId") or "")
        if not cut_id:
            errors.append({"cut": str(index), "field": "cutId", "message": "cutId is required"})
        if not scene_id:
            errors.append({"cut": cut_id or str(index), "field": "sceneId", "message": "sceneId is required"})
        if cut_id in cut_ids:
            errors.append({"cut": cut_id, "field": "cutId", "message": "duplicate cutId"})
        if scene_id in scene_ids:
            errors.append({"cut": cut_id, "field": "sceneId", "message": "duplicate sceneId"})
        cut_ids.add(cut_id)
        scene_ids.add(scene_id)

        duration = _duration(cut.get("plannedDurationSec"), 0.0)
        if duration < 6.0 and cut.get("role") not in {"transition", "exclude"}:
            warnings.append({"cut": cut_id, "field": "plannedDurationSec", "message": "long-form A/B-roll cuts should usually be at least 6 seconds"})
        if not _text(cut.get("assignedScript")) and cut.get("role") != "exclude":
            warnings.append({"cut": cut_id, "field": "assignedScript", "message": "cut has no assigned script text"})
        if not _text(cut.get("allowedLocation")):
            warnings.append({"cut": cut_id, "field": "allowedLocation", "message": "location lock is missing"})
        if not cut.get("characters"):
            warnings.append({"cut": cut_id, "field": "characters", "message": "character references are missing"})
        if _text(cut.get("sourceStatus")) == "accepted" and not _text(cut.get("selectedVideoPath")):
            warnings.append({"cut": cut_id, "field": "selectedVideoPath", "message": "accepted source should bind selectedVideoPath"})
        block_id = _text(cut.get("blockId"), "B01")
        block_durations[block_id] = round(block_durations.get(block_id, 0.0) + duration, 2)

    return {
        "ok": not errors,
        "errorCount": len(errors),
        "warningCount": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "cutCount": len(cuts),
            "estimatedDurationSec": round(sum(block_durations.values()), 2),
            "blockDurationsSec": block_durations,
        },
    }


def _output_gate_check(
    key: str,
    label: str,
    status: str,
    detail: str,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
        "required": required,
    }


def _episode_output_gate(
    episode_id: str,
    validation: dict[str, Any],
    data: dict[str, Any] | None = None,
    gate_kind: str = "episode-artifact-output",
) -> dict[str, Any]:
    data = data or {}
    preproduction = _load_episode_file(episode_id, "preproduction/preproduction-manifest.json")
    quality_loop_required = (
        data.get("qualityLoopRequired") is True
        or data.get("promptOutputGateRequired") is True
        or data.get("artifactOutputGateRequired") is True
        or (isinstance(preproduction, dict) and preproduction.get("qualityLoopRequired") is True)
    )
    paths = _quality_loop_paths(episode_id)
    standard = _read_json_path(paths["standard"])
    ledger = _read_json_path(paths["ledger"])
    contract_registry = standard.get("contractRegistry") if isinstance(standard, dict) and isinstance(standard.get("contractRegistry"), list) else []
    registered_contract_keys = {
        _text(item.get("contractKey"))
        for item in contract_registry
        if isinstance(item, dict) and _text(item.get("contractKey"))
    }
    standard_contract_keys = {
        key
        for key in (standard or {})
        if key == "policy" or key.endswith("Contract")
    } if isinstance(standard, dict) else set()
    unregistered_contracts = sorted(standard_contract_keys - registered_contract_keys)
    missing_registry_contracts = sorted(registered_contract_keys - standard_contract_keys)
    next_action = ledger.get("nextRequiredAction") if isinstance(ledger, dict) else {}
    next_action_status = _text((next_action or {}).get("status"))
    checks = [
        _output_gate_check(
            "shotSyncValidation",
            "Shot sync validation passed",
            "pass" if validation.get("ok") else "fail",
            f"errors={validation.get('errorCount', 0)}, warnings={validation.get('warningCount', 0)}",
        ),
        _output_gate_check(
            "zeroPaidBrowserRail",
            "Zero-paid browser rail",
            "pass",
            "episode prompts use browser handoff only; no paid API provider call is made",
        ),
        _output_gate_check(
            "qualityLoopStandard",
            "Quality loop standard exists",
            "pass" if not quality_loop_required or (standard is not None and ledger is not None) else "fail",
            (
                f"required={quality_loop_required}, "
                f"standardExists={standard is not None}, ledgerExists={ledger is not None}"
            ),
            quality_loop_required,
        ),
        _output_gate_check(
            "qualityLoopContractRegistry",
            "Quality loop contract registry is complete",
            "pass" if not quality_loop_required or (bool(contract_registry) and not unregistered_contracts and not missing_registry_contracts) else "fail",
            (
                f"registered={len(contract_registry)}, "
                f"unregisteredContracts={','.join(unregistered_contracts) or 'none'}, "
                f"missingRegistryContracts={','.join(missing_registry_contracts) or 'none'}"
            ),
            quality_loop_required,
        ),
        _output_gate_check(
            "qualityLoopNextAction",
            "Quality loop next action allows output",
            "fail" if quality_loop_required and next_action_status in {"apply-next-mutation", "continue-current-stage"} else "pass",
            f"nextRequiredAction={next_action_status or 'not-required'}",
            quality_loop_required,
        ),
    ]
    if quality_loop_required and contract_registry:
        for item in contract_registry:
            if not isinstance(item, dict):
                continue
            contract_key = _text(item.get("contractKey"))
            if not contract_key or item.get("requiredForOutput") is False:
                continue
            checks.append(_output_gate_check(
                _text(item.get("gateKey"), f"{contract_key}Standard"),
                _text(item.get("label"), f"{contract_key} exists"),
                "pass" if _quality_loop_has_value((standard or {}).get(contract_key)) else "fail",
                f"contractKey={contract_key}, exists={_quality_loop_has_value((standard or {}).get(contract_key))}",
                True,
            ))
    blocking = [
        check
        for check in checks
        if check["required"] and check["status"] != "pass"
    ]
    status = "blocked" if blocking else "pass"
    return {
        "schema": "video-studio.output-gate.v1",
        "episodeId": _episode_id(episode_id),
        "gateKind": gate_kind,
        "status": status,
        "promptOutputAllowed": status == "pass",
        "artifactOutputAllowed": status == "pass",
        "qualityLoopRequired": quality_loop_required,
        "qualityLoopStandardPath": str(paths["standard"]),
        "qualityIterationLedgerPath": str(paths["ledger"]),
        "nextRequiredAction": next_action or {},
        "checks": checks,
        "blockingChecks": blocking,
        "gateSystem": build_episode_gate_system(
            output_status=status,
            checks=checks,
            contract_registry=contract_registry,
            next_action_status=next_action_status,
            quality_loop_required=quality_loop_required,
        ),
    }


def _output_gate_error(gate: dict[str, Any]) -> str:
    blocking = gate.get("blockingChecks") if isinstance(gate.get("blockingChecks"), list) else []
    if not blocking:
        return "output gate blocked"
    return "; ".join(
        f"{item.get('key')}: {item.get('detail')}"
        for item in blocking
    )


def _current_episode_output_gate(episode_id: str, gate_kind: str = "prompt-output") -> dict[str, Any]:
    sync_map = _load_episode_file(episode_id, "shot-sync-map.json")
    if sync_map is None:
        validation = {
            "ok": False,
            "errorCount": 1,
            "warningCount": 0,
            "errors": [{"field": "shot-sync-map", "message": "shot-sync-map not found"}],
            "warnings": [],
        }
    else:
        validation = _validate_sync_map(sync_map)
    return _episode_output_gate(episode_id, validation, {}, gate_kind)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (path.read_text(encoding="utf-8") if path.exists() else "")
        + json.dumps(payload, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


def _bridge_url(path: str) -> str:
    return f"http://{_bridge_host}:{_bridge_port}{path}"


def _episode_extension_event_url(episode_id: str) -> str:
    return _bridge_url(f"/api/episodes/{_episode_id(episode_id)}/browser-handoffs/extension-event")


def _gemini_extension_command_url(episode_id: str, batch_id: str, cut_id: str) -> str:
    query = urllib.parse.urlencode({"operatorApproved": "true", "cutId": cut_id})
    return _bridge_url(
        f"/api/episodes/{_episode_id(episode_id)}/browser-handoffs/gemini-web-image/{batch_id}/extension-command?{query}"
    )


def _gemini_autostart_url(command_url: str) -> str:
    query = urllib.parse.urlencode({
        "operatorApproved": "true",
        "videoStudioProvider": "gemini-web-image",
        "videoStudioAction": "fill-prompt",
        "videoStudioCommandUrl": command_url,
    })
    return f"{GEMINI_WEB_URL}#{query}"


def _browser_control_policy(provider: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "primaryRail": "existing-signed-in-chrome-browser-control",
        "mode": "existing-signed-in-chrome-browser-control-primary",
        "requiresExistingSignedInChromeProfile": True,
        "forbidNewChromeProfile": True,
        "forbidNewChromeWindowAsProof": True,
        "forbidEdgeFallback": True,
        "usesApi": False,
        "usesPaidApi": False,
        "companionExtensionRole": "fallback-diagnostic-only",
        "autoNativeDownloadPromptAllowed": False,
        "paidApiAllowed": False,
    }
    if provider == "gemini-web-image":
        base.update({
            "provider": "gemini-web-image",
            "canFillPrompt": True,
            "canClickGenerate": False,
            "canImportResult": False,
            "generateAuthority": "operator-owned-manual-generate-or-explicit-browser-control-check-only",
            "resultAuthority": "operator-owned-manual-download-or-upload",
            "proofEvents": ["gemini-prompt-fill", "gemini-result-visible"],
        })
    elif provider == "grok-web-video":
        base.update({
            "provider": "grok-web-video",
            "surfaceGuard": "grok-imagine-only",
            "forbidChatThreadSuccess": True,
            "generationProofRequired": True,
            "downloadAuthority": "operator-owned-manual-download-or-local-upload",
            "localMp4ImportRequired": True,
            "successSurface": GROK_WEB_URL,
        })
    return base


def _topic_brief(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("topicBrief") or data.get("topic_brief") or data.get("topic") or {}
    if isinstance(raw, str):
        raw = {"angle": raw}
    if not isinstance(raw, dict):
        raw = {}
    title = _text(data.get("title") or raw.get("title") or data.get("episodeId"))
    return {
        "title": title,
        "format": _text(raw.get("format") or data.get("format"), "shortform"),
        "trendAnchor": _text(raw.get("trendAnchor") or raw.get("trend_anchor") or raw.get("sourceAnchor")),
        "whyNow": _text(raw.get("whyNow") or raw.get("why_now") or raw.get("timeliness")),
        "audience": _text(raw.get("audience") or raw.get("targetAudience")),
        "viewerQuestion": _text(raw.get("viewerQuestion") or raw.get("viewer_question") or raw.get("question")),
        "angle": _text(raw.get("angle") or raw.get("takeaway") or raw.get("position")),
        "evidenceNotes": [
            _text(item)
            for item in _list(raw.get("evidenceNotes") or raw.get("evidence_notes") or raw.get("sources"))
            if _text(item)
        ],
    }


def _storyboard_source(data: dict[str, Any]) -> list:
    beats = data.get("storyboardBeats") or data.get("storyboard_beats") or data.get("storyboard") or data.get("beats")
    return beats if isinstance(beats, list) else []


def _default_asset_brief(beat: dict[str, Any], topic: dict[str, Any]) -> dict[str, Any]:
    visual_action = _text(beat.get("visualAction") or beat.get("visual_action") or beat.get("scene"))
    proof = _text(beat.get("proofPoint") or beat.get("proof_point") or topic.get("angle"))
    location = _text(beat.get("allowedLocation") or beat.get("allowed_location"), "topic-matched real-world setting")
    subject = _text(beat.get("subject") or topic.get("audience") or "viewer-relevant subject")
    text_card_clause = _planned_text_card_clause(
        beat.get("plannedTextCardAfter")
        or beat.get("planned_text_card_after")
        or beat.get("textCardAfter")
        or beat.get("chapterCardAfter")
        or {}
    )
    gemini_prompt = _text(beat.get("geminiPrompt") or beat.get("imagePrompt") or beat.get("image_prompt"))
    if not gemini_prompt:
        gemini_prompt = (
            "Reference image for a Korean short-form video storyboard. "
            f"Subject: {subject}. Moment: {visual_action}. Context: {proof}. "
            f"Location: {location}. Realistic vertical 9:16 frame, natural light, no readable text, logo, or subtitle."
        )
    if text_card_clause:
        gemini_prompt = f"{gemini_prompt} {text_card_clause}"
    grok_prompt = _text(beat.get("grokPrompt") or beat.get("grok_prompt") or beat.get("videoPrompt") or beat.get("video_prompt"))
    if not grok_prompt:
        grok_prompt = (
            "Raw vertical 9:16 phone-camera MP4 for editing. "
            f"First second shows this visible action clearly: {visual_action}. "
            f"Keep the scene in {location}; show {subject}; one continuous 4-6 second shot, natural handheld camera, "
            "no montage, no readable text, no watermark."
        )
    if text_card_clause:
        grok_prompt = f"{grok_prompt} {text_card_clause}"
    return {
        "providers": ["gemini-web-image", "grok-web-video"],
        "geminiWebImage": {
            "stage": "reference-image",
            "prompt": gemini_prompt,
            "reviewGate": "image-reference-must-match-storyboard-before-video",
        },
        "grokWebVideo": {
            "stage": "raw-video",
            "prompt": grok_prompt,
            "reviewGate": "mp4-must-match-storyboard-and-reference-before-render",
        },
        "operatorOwnedSource": {
            "allowed": True,
            "note": "Prefer direct/operator-owned source when it better matches the storyboard than generated media.",
        },
    }


def _quality_ratchet_template(
    data: dict[str, Any],
    episode_id: str,
    topic: dict[str, Any],
    beats: list[dict[str, Any]],
) -> dict[str, Any]:
    raw = data.get("qualityRatchet") or data.get("quality_ratchet") or {}
    if not isinstance(raw, dict):
        raw = {}

    def field(camel: str, snake: str, fallback: Any = "") -> Any:
        return raw.get(camel) or raw.get(snake) or data.get(camel) or data.get(snake) or fallback

    changed_lever = field("changedLever", "changed_lever", ["storyboard", "source"])
    if isinstance(changed_lever, str):
        changed_lever = [changed_lever]
    if not isinstance(changed_lever, list):
        changed_lever = ["storyboard", "source"]

    return {
        "schema": "video-studio.quality-ratchet.v1",
        "episodeId": episode_id,
        "required": True,
        "status": "pending-proof",
        "requiredFields": list(QUALITY_RATCHET_REQUIRED_FIELDS),
        "previousBaseline": field("previousBaseline", "previous_baseline"),
        "rejectionCause": field("rejectionCause", "rejection_cause"),
        "changedLever": changed_lever,
        "expectedVisibleImprovement": field(
            "expectedVisibleImprovement",
            "expected_visible_improvement",
            f"Storyboard-first source replacement should make {len(beats)} beats visibly match the viewer question.",
        ),
        "actualProof": field("actualProof", "actual_proof", {}),
        "nextRatchet": field("nextRatchet", "next_ratchet"),
        "appliesTo": [
            "preproduction-manifest",
            "asset-candidate-review",
            "accepted-source-map",
            "render-manifest",
            "render-quality-report",
        ],
        "operatorRule": (
            "A quality candidate cannot pass by repeating the previous floor; render QA must record visible improvement proof."
        ),
        "topicAnchor": {
            "viewerQuestion": topic.get("viewerQuestion"),
            "angle": topic.get("angle"),
        },
    }


def _quality_loop_paths(episode_id: str) -> dict[str, Path]:
    preproduction_dir = _episode_dir(episode_id) / "preproduction"
    return {
        "standard": preproduction_dir / "quality-loop-standard.json",
        "ledger": preproduction_dir / "quality-iteration-ledger.json",
    }


def _read_json_path(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _quality_loop_has_value(value: object) -> bool:
    if isinstance(value, dict):
        return any(_quality_loop_has_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_quality_loop_has_value(item) for item in value)
    return bool(_text(value))


def _quality_loop_standard(
    episode_id: str,
    topic: dict[str, Any],
    beats: list[dict[str, Any]],
    quality_ratchet: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    contract_registry = [
        {
            **contract,
            "requiredForOutput": True,
        }
        for contract in QUALITY_LOOP_REQUIRED_CONTRACTS
    ]
    return {
        "schema": "video-studio.quality-loop-standard.v1",
        "standardVersion": QUALITY_LOOP_STANDARD_VERSION,
        "episodeId": episode_id,
        "updatedAt": now,
        "required": True,
        "policy": {
            "usesApi": False,
            "usesPaidApi": False,
            "providerGenerationRail": "existing-signed-in-browser-control-or-operator-owned-manual-action",
            "nativeDownloadAutomationAllowed": False,
            "singleArtifactCannotCloseLoop": True,
            "failureMustNameNextMutation": True,
        },
        "gateSystem": gate_system_registry(contract_registry),
        "contractRegistry": contract_registry,
        "topicContract": {
            "requiresWhyNow": True,
            "requiresViewerQuestion": True,
            "requiresSpecificAudience": True,
            "requiresEditorialAngle": True,
            "rejectGenericRoutineWithoutTimelyAnchor": True,
        },
        "promptContract": {
            "sourceOrder": [
                "topicBrief",
                "storyboardBeat",
                "visualAction",
                "sourceNeed",
                "providerPrompt",
            ],
            "grokShotInstruction": {
                "sentences": "1-3",
                "preferredCharacters": "220-500",
                "mustInclude": [
                    "subject",
                    "place",
                    "visible first-second physical action",
                    "one continuous 4-6s vertical phone MP4",
                    "camera behavior",
                    "continuity anchor",
                    "planned transition cue context when present",
                ],
                "mustAvoid": [
                    "QA narration",
                    "rejection history",
                    "AI slop wording",
                    "long negative-prompt dumps",
                    "caption/layout checklist prose",
                    "rendering editor-only transition cue words inside source video",
                ],
            },
            "geminiReferenceInstruction": {
                "role": "reference-image-only",
                "mustMatchStoryboardBeforeGrok": True,
                "generateAndSaveAuthority": "operator-owned-unless-separately-approved",
            },
            "recommendedTakeRule": "use a ready promptQuality take; never recommend needs-rewrite for normal generation",
        },
        "outputContract": {
            "sourceGate": "accepted-source-map.status must be ready-for-render before render quality claims",
            "voiceGate": "information/list formats require zero-paid voice review unless human exception is recorded",
            "captionGate": "caption layout must pass the captionLayoutContract, not just exist",
            "renderGate": "render quality floor is minimum baseline, not quality recovery by itself",
            "phoneReviewGate": "human phone-sized review decides upload readiness",
        },
        "captionLayoutContract": {
            "renderingSpec": "docs/RENDERING-SPEC.md sections 1, 2, 7.2, and 7.4",
            "canvas": {
                "width": 1080,
                "height": 1920,
                "contentSafeZone": {"x": [60, 950], "y": [100, 1440]},
                "bottomDangerZone": {"y": [1536, 1920]},
                "rightDangerZone": {"x": [950, 1080]},
                "topDangerZone": {"y": [0, 100]},
            },
            "subtitlePlacement": {
                "hookTitle": {"alignment": 8, "marginL": 60, "marginR": 130, "marginV": 120, "approxY": "120-200"},
                "mainNarration": {"alignment": 5, "marginL": 60, "marginR": 130, "marginV": 0, "approxY": "900-1100"},
                "supplementaryInfo": {"alignment": 2, "marginL": 60, "marginR": 130, "marginV": 500, "approxY": "1300-1420"},
                "absoluteProhibition": ["subtitle y > 1536", "subtitle x > 950"],
            },
            "textDensity": {
                "koreanMaxCharsPerLine": 16,
                "maxLines": 2,
                "topHookMaxDisplaySec": 1.35,
                "centerShortMaxDisplaySec": 1.6,
                "lowerInfoMaxDisplaySec": 1.8,
            },
            "layoutVariantRequired": True,
            "requiredPerBeatFields": [
                "onScreenText",
                "captionPreset",
                "layoutVariantKey",
                "layoutVariantNote",
            ],
            "renderReviewEvidenceRequired": [
                "captionPreset",
                "layoutVariantKey",
                "safeZoneReview",
                "subjectOcclusionVerdict",
                "platformUiCollisionVerdict",
                "phoneContactSheetPath",
                "lineBreakReview",
            ],
            "forbidden": [
                "burn production notes into viewer captions",
                "place subtitles in bottom 20 percent",
                "cover hands, phone screens, or object state changes",
                "use oversized routine overlays without phone-sized contact-sheet review",
            ],
        },
        "voiceAudioContract": {
            "renderingSpec": "docs/RENDERING-SPEC.md sections 4, 6.6, 7.2, and 7.5",
            "zeroPaidDefault": True,
            "voiceRequiredUnlessHumanException": True,
            "paidProvidersBlockedUnlessOptIn": [
                "google-ai-studio-tts",
                "openai-tts",
                "elevenlabs",
            ],
            "allowedZeroPaidProviders": [
                "edge-tts",
                "windows-tts",
                "operator-owned-recorded-voice",
            ],
            "requiredEvidence": [
                "voiceProvider",
                "zeroPaidStatus",
                "voiceRate",
                "voicePitch",
                "rawTtsDurationSec",
                "sceneDurationSec",
                "pronunciationReview",
                "pacingReview",
                "energyReview",
                "bgmDuckReview",
                "audioBalanceReview",
            ],
            "failureMustChangeOneOf": [
                "voiceProvider",
                "voiceRate",
                "scriptDensity",
                "lineBreak",
                "bgmDuckSettings",
                "mixLevel",
            ],
            "forbidden": [
                "ship information/list/ranking format with no voice unless human exception is recorded",
                "use paid TTS without explicit opt-in",
                "force slow raw TTS into shorter scene duration without shortening script",
                "let BGM erase narration",
            ],
        },
        "editRhythmContract": {
            "renderingSpec": "docs/RENDERING-SPEC.md sections 6.6, 7.2, and 7.5",
            "transitionCueDecision": {
                "defaultMode": "none",
                "allowedModes": [
                    "none",
                    "straight-cut",
                    "crossfade",
                    "overlay",
                    "micro-transition",
                    "full-card",
                ],
                "selectionRule": "Choose the transition cue by format, genre, audio tempo, source continuity, and viewer comprehension; do not make cards the default.",
                "fullCardIsException": True,
                "fullCardAllowedOnlyWhen": [
                    "the format has enough runtime headroom",
                    "audio can continue as a deliberate bed or the pause is stylistically motivated",
                    "the source clips would otherwise fake one continuous scene",
                ],
                "shortformTwelveSecondPreference": [
                    "none",
                    "straight-cut",
                    "crossfade",
                    "overlay",
                    "micro-transition",
                ],
                "audioContinuityRule": "For music-led 12s shorts, BGM must remain continuous unless a human review explicitly approves a rhythmic stop.",
            },
            "plannedTextCardBreaks": {
                "optionalPerBeatField": "plannedTextCardAfter",
                "backCompatOnly": True,
                "defaultMode": "none",
                "defaultDurationSec": None,
                "fullCardFallbackDurationSec": 0.62,
                "sourceClipRule": "source clip must be self-contained and must not render editor-only transition cue text",
                "promptRule": "Grok/Gemini prompt names the planned transition cue only when a cue is selected so the beat can end cleanly for the editor",
            },
            "requiredEvidence": [
                "sceneDurationSec",
                "averageCutDurationSec",
                "firstTwoSecondHookReview",
                "longHoldReview",
                "actionBeatVisible",
                "cutRhythmRationale",
            ],
            "defaultShortformTargets": {
                "firstTwoSecondHookRequired": True,
                "averageCutDurationSecMax": 4.5,
                "longHoldRequiresRationale": True,
            },
            "failureMustChangeOneOf": [
                "sceneDuration",
                "cutOrder",
                "sourceSelection",
                "firstFrame",
                "transitionCueMode",
                "audioContinuityPolicy",
                "captionDensity",
                "voiceScriptDensity",
            ],
        },
        "renderReviewContract": {
            "renderingSpec": "docs/RENDERING-SPEC.md sections 6, 7.2, 7.3, and 7.5",
            "requiredEvidence": [
                "renderManifestPath",
                "finalMp4Path",
                "sha256",
                "ffprobe1080x1920",
                "audioStreamPresent",
                "assSubtitlePath",
                "renderQualityReportPath",
                "contactSheetPath",
                "renderFloorApplied",
            ],
            "renderFloorAppliedRequires": [
                "h264-crf18-or-better",
                "lanczos-scale",
                "unsharp",
                "eq-polish",
                "aac-audio",
            ],
        },
        "publishReviewContract": {
            "renderingSpec": "docs/RENDERING-SPEC.md sections 7.2 and 7.5",
            "uploadReadinessRequires": [
                "phoneSizedFullWatch",
                "humanUploadDecision",
                "freshSourceProof",
                "platformAnalyticsPlanOrResult",
                "publishPacket",
                "shortcomingsAndNextActions",
            ],
            "phoneReviewEvidence": [
                "finalVideoPath",
                "reviewerDecision",
                "voiceoverPolicyPass",
                "stockAiClipFitPass",
                "captionLayoutPass",
                "sameDayUploadApproval",
            ],
            "cannotBeSatisfiedBy": [
                "final MP4 existence alone",
                "automated artifact gate alone",
                "dashboard ready badge without phone review",
                "old mismatched phone-review proof",
            ],
        },
        "iterationContract": {
            "allowedStages": sorted(QUALITY_LOOP_STAGES),
            "allowedStatuses": sorted(QUALITY_LOOP_STATUSES),
            "failedIterationRequires": [
                "observedFailure",
                "nextMutation",
                "changedLever",
            ],
            "passIterationRequires": [
                "passEvidence or gateEvidencePaths",
            ],
            "specChangeProposalRequires": [
                "currentRule",
                "whyInsufficient",
                "proposedRule",
                "verificationPlan",
            ],
            "qualityRatchetFields": list(QUALITY_RATCHET_REQUIRED_FIELDS),
            "captionLayoutFailureRequires": [
                "stage=caption or stage=layout",
                "observedFailure",
                "nextMutation",
                "gateEvidencePaths with contact sheet or render review path",
            ],
            "voiceAudioFailureRequires": [
                "stage=voice, audio, or bgm",
                "observedFailure",
                "nextMutation",
                "gateEvidencePaths with audio review, render report, or phone review path",
            ],
            "editRhythmFailureRequires": [
                "stage=edit-rhythm",
                "observedFailure",
                "nextMutation",
                "gateEvidencePaths with contact sheet, render report, or timeline review path",
            ],
            "publishFailureRequires": [
                "stage=phone-review or publish",
                "observedFailure",
                "nextMutation",
                "gateEvidencePaths with phone-review or publish-packet path",
            ],
            "pendingMutationResolutionRequires": [
                "resolvesIterationId matching quality-iteration-ledger.nextRequiredAction.fromIterationId",
                "appliedMutation",
                "mutationEvidence or gateEvidencePaths or passEvidence",
            ],
            "qualityRatchet": quality_ratchet,
        },
        "resumeContract": {
            "nextSessionMustRead": [
                "preproduction/preproduction-manifest.json",
                "preproduction/quality-loop-standard.json",
                "preproduction/quality-iteration-ledger.json",
                "preproduction/asset-candidate-review.json if present",
                "preproduction/accepted-source-map.json if present",
            ],
            "cannotStopWithoutOneOf": [
                "passing iteration with passEvidence",
                "failed or blocked iteration with observedFailure and nextMutation",
                "needs-spec-change iteration with specChangeProposal and verificationPlan",
            ],
            "nextActionSource": "quality-iteration-ledger.nextRequiredAction",
        },
        "storyboardSnapshot": [
            {
                "beatId": beat.get("beatId"),
                "sceneId": beat.get("sceneId"),
                "role": beat.get("role"),
                "onScreenText": beat.get("onScreenText"),
                "captionPreset": beat.get("captionPreset"),
                "layoutVariantKey": beat.get("layoutVariantKey"),
                "visualAction": beat.get("visualAction"),
                "sourceNeed": beat.get("sourceNeed"),
                "plannedTextCardAfter": beat.get("plannedTextCardAfter") or {},
            }
            for beat in beats
        ],
        "topicAnchor": {
            "viewerQuestion": topic.get("viewerQuestion"),
            "whyNow": topic.get("whyNow") or topic.get("trendAnchor"),
            "angle": topic.get("angle"),
        },
    }


def _quality_loop_next_required_action(iterations: list[dict[str, Any]]) -> dict[str, Any]:
    if not iterations:
        return {
            "status": "awaiting-first-iteration",
            "summary": "Run the next quality gate and append a quality-loop iteration before ending the session.",
        }
    last = iterations[-1]
    status = _text(last.get("status"), "planned")
    if status in QUALITY_LOOP_FAILURE_STATUSES:
        mutation = last.get("nextMutation") if isinstance(last.get("nextMutation"), dict) else {}
        return {
            "status": "apply-next-mutation",
            "fromIterationId": last.get("iterationId"),
            "stage": last.get("stage"),
            "summary": _text(
                mutation.get("summary")
                or mutation.get("promptChange")
                or mutation.get("sourceChange")
                or mutation.get("renderChange"),
                "Apply the recorded nextMutation before generating another unrelated candidate.",
            ),
        }
    if status == "pass":
        return {
            "status": "advance-next-gate",
            "fromIterationId": last.get("iterationId"),
            "stage": last.get("stage"),
            "summary": "Advance to the next production gate and record its evidence in the ledger.",
        }
    return {
        "status": "continue-current-stage",
        "fromIterationId": last.get("iterationId"),
        "stage": last.get("stage"),
        "summary": "Complete the current planned quality iteration and record pass/fail evidence.",
    }


def _quality_iteration_ledger(
    episode_id: str,
    standard: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    existing = _read_json_path(_quality_loop_paths(episode_id)["ledger"])
    iterations = existing.get("iterations") if isinstance(existing, dict) and isinstance(existing.get("iterations"), list) else []
    return {
        "schema": "video-studio.quality-iteration-ledger.v1",
        "episodeId": episode_id,
        "standardVersion": standard["standardVersion"],
        "updatedAt": now,
        "status": "iterating" if iterations else "awaiting-first-iteration",
        "iterations": iterations,
        "nextRequiredAction": _quality_loop_next_required_action(iterations),
    }


def _normalize_next_mutation(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if _text(value):
        return {"summary": _text(value)}
    return {}


def _normalize_spec_change_proposal(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_applied_mutation(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if _text(value):
        return {"summary": _text(value)}
    return {}


def _quality_iteration_error_text(errors: list[str]) -> str:
    return "; ".join(errors)


def _normalize_quality_iteration(
    data: dict[str, Any],
    next_index: int,
    pending_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stage = _text(data.get("stage") or data.get("gate"), "").lower().replace("_", "-")
    status = _text(data.get("status"), "").lower().replace("_", "-")
    changed_lever = [
        _text(item)
        for item in _list(data.get("changedLever") or data.get("changed_lever"))
        if _text(item)
    ]
    observed_failure = _text(data.get("observedFailure") or data.get("observed_failure"))
    pass_evidence = data.get("passEvidence") or data.get("pass_evidence") or {}
    gate_evidence_paths = [
        _text(item)
        for item in _list(data.get("gateEvidencePaths") or data.get("gate_evidence_paths"))
        if _text(item)
    ]
    next_mutation = _normalize_next_mutation(data.get("nextMutation") or data.get("next_mutation"))
    spec_change_proposal = _normalize_spec_change_proposal(
        data.get("specChangeProposal") or data.get("spec_change_proposal")
    )
    resolves_iteration_id = _text(data.get("resolvesIterationId") or data.get("resolves_iteration_id"))
    applied_mutation = _normalize_applied_mutation(data.get("appliedMutation") or data.get("applied_mutation"))
    mutation_evidence = data.get("mutationEvidence") or data.get("mutation_evidence") or {}
    pending_action = pending_action or {}
    pending_status = _text(pending_action.get("status"))
    pending_iteration_id = _text(pending_action.get("fromIterationId"))

    errors: list[str] = []
    if stage not in QUALITY_LOOP_STAGES:
        errors.append(f"stage must be one of {', '.join(sorted(QUALITY_LOOP_STAGES))}")
    if status not in QUALITY_LOOP_STATUSES:
        errors.append(f"status must be one of {', '.join(sorted(QUALITY_LOOP_STATUSES))}")
    if status in QUALITY_LOOP_FAILURE_STATUSES:
        if len(observed_failure) < 8:
            errors.append("observedFailure is required for failed, blocked, or needs-spec-change iterations")
        if not _quality_loop_has_value(next_mutation):
            errors.append("nextMutation is required for failed, blocked, or needs-spec-change iterations")
        if not changed_lever:
            errors.append("changedLever is required for failed, blocked, or needs-spec-change iterations")
        if stage in {"caption", "layout"} and not gate_evidence_paths:
            errors.append("gateEvidencePaths is required for caption or layout failures")
        if stage in {"voice", "audio", "bgm"} and not gate_evidence_paths:
            errors.append("gateEvidencePaths is required for voice or audio failures")
        if stage == "edit-rhythm" and not gate_evidence_paths:
            errors.append("gateEvidencePaths is required for edit-rhythm failures")
        if stage in {"phone-review", "publish"} and not gate_evidence_paths:
            errors.append("gateEvidencePaths is required for phone-review or publish failures")
    if status == "pass" and not (_quality_loop_has_value(pass_evidence) or gate_evidence_paths):
        errors.append("passEvidence or gateEvidencePaths is required for pass iterations")
    if pending_status == "apply-next-mutation":
        if not pending_iteration_id or resolves_iteration_id != pending_iteration_id:
            errors.append("resolvesIterationId must match the pending nextRequiredAction.fromIterationId")
        if not _quality_loop_has_value(applied_mutation):
            errors.append("appliedMutation is required before recording work after a failed iteration")
        if not (_quality_loop_has_value(mutation_evidence) or gate_evidence_paths or _quality_loop_has_value(pass_evidence)):
            errors.append("mutationEvidence, gateEvidencePaths, or passEvidence is required when resolving a pending mutation")
    if status == "needs-spec-change" and not spec_change_proposal:
        errors.append("specChangeProposal is required when status is needs-spec-change")
    if spec_change_proposal:
        missing = [
            field
            for field in ("currentRule", "whyInsufficient", "proposedRule", "verificationPlan")
            if len(_text(spec_change_proposal.get(field))) < 8
        ]
        if missing:
            errors.append("specChangeProposal is missing required fields: " + ", ".join(missing))
    if errors:
        raise ValueError(_quality_iteration_error_text(errors))

    return {
        "iterationId": _text(data.get("iterationId") or data.get("iteration_id"), f"iteration-{next_index:03d}"),
        "createdAt": _utc_now(),
        "stage": stage,
        "status": status,
        "changedLever": changed_lever,
        "observedFailure": observed_failure,
        "passEvidence": pass_evidence if isinstance(pass_evidence, dict) else {"summary": _text(pass_evidence)},
        "gateEvidencePaths": gate_evidence_paths,
        "nextMutation": next_mutation,
        "resolvesIterationId": resolves_iteration_id,
        "appliedMutation": applied_mutation,
        "mutationEvidence": mutation_evidence if isinstance(mutation_evidence, dict) else {"summary": _text(mutation_evidence)},
        "specChangeProposal": spec_change_proposal,
        "notes": _text(data.get("notes")),
    }


def _write_quality_loop_iteration(episode_id_value: str, data: dict[str, Any]) -> dict[str, Any]:
    episode_id = _episode_id(episode_id_value)
    paths = _quality_loop_paths(episode_id)
    standard = _read_json_path(paths["standard"])
    ledger = _read_json_path(paths["ledger"])
    if standard is None or ledger is None:
        raise ValueError("quality loop standard and ledger are required before recording iterations")
    iterations = ledger.get("iterations") if isinstance(ledger.get("iterations"), list) else []
    pending_action = ledger.get("nextRequiredAction") if isinstance(ledger.get("nextRequiredAction"), dict) else {}
    iteration = _normalize_quality_iteration(data, len(iterations) + 1, pending_action)
    iterations.append(iteration)
    now = _utc_now()
    ledger.update({
        "updatedAt": now,
        "status": "iterating",
        "iterations": iterations,
        "nextRequiredAction": _quality_loop_next_required_action(iterations),
    })
    if iteration["specChangeProposal"]:
        standard["updatedAt"] = now
        standard["pendingSpecChangeProposal"] = iteration["specChangeProposal"]
    _write_json(paths["standard"], standard)
    _write_json(paths["ledger"], ledger)
    payload = _quality_loop_response_payload(episode_id, standard, ledger, paths)
    payload.update({
        "ok": True,
        "iteration": iteration,
        "ledger": ledger,
        "standard": standard,
    })
    return payload


def _quality_loop_response_payload(
    episode_id: str,
    standard: dict[str, Any],
    ledger: dict[str, Any],
    paths: dict[str, Path],
) -> dict[str, Any]:
    gate_system = build_quality_loop_gate_system(standard=standard, ledger=ledger)
    loop_summary = dict(gate_system.get("qualityIterationSummary") or {})
    loop_summary["nextRequiredAction"] = ledger.get("nextRequiredAction") if isinstance(ledger.get("nextRequiredAction"), dict) else {}
    return {
        "ok": True,
        "episodeId": _episode_id(episode_id),
        "qualityLoopStandard": standard,
        "qualityIterationLedger": ledger,
        "qualityLoopStandardPath": str(paths["standard"]),
        "qualityIterationLedgerPath": str(paths["ledger"]),
        "gateSystem": gate_system,
        "blockingPhaseKey": gate_system.get("blockingPhaseKey") or "",
        "phaseStates": gate_system.get("phaseStates") or [],
        "contractSummary": gate_system.get("contractSummary") or {},
        "loopSummary": loop_summary,
    }


def _normalize_storyboard_beats(data: dict[str, Any], topic: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for zero_index, item in enumerate(_storyboard_source(data)):
        if not isinstance(item, dict):
            item = {"storyPurpose": str(item)}
        index = zero_index + 1
        beat_id = _text(item.get("beatId") or item.get("beat_id"), f"beat-{index:03d}")
        role = _text(item.get("role"), "context").lower().replace("-", "_")
        role = role.replace("_", "-")
        if role not in PREPRODUCTION_BEAT_ROLES:
            role = "context"
        visual_action = _text(item.get("visualAction") or item.get("visual_action") or item.get("action") or item.get("scene"))
        beat = {
            "beatId": beat_id,
            "sceneId": _text(item.get("sceneId") or item.get("scene_id"), f"scene-{index:03d}"),
            "cutId": _text(item.get("cutId") or item.get("cut_id"), f"cut_{index:03d}"),
            "role": role,
            "storyPurpose": _text(item.get("storyPurpose") or item.get("story_purpose") or item.get("purpose") or item.get("scene")),
            "viewerQuestion": _text(item.get("viewerQuestion") or item.get("viewer_question") or topic.get("viewerQuestion")),
            "audienceProblem": _text(item.get("audienceProblem") or item.get("audience_problem") or item.get("problem")),
            "proofPoint": _text(item.get("proofPoint") or item.get("proof_point") or item.get("evidence")),
            "onScreenText": _text(item.get("onScreenText") or item.get("on_screen_text") or item.get("subtitleText")),
            "narrationLine": _text(item.get("narrationLine") or item.get("narration_line") or item.get("narration") or item.get("ttsLine")),
            "visualAction": visual_action,
            "allowedLocation": _text(item.get("allowedLocation") or item.get("allowed_location")),
            "forbiddenLocations": _list(item.get("forbiddenLocations") or item.get("forbidden_locations")),
            "characters": _list(item.get("characters") or item.get("characterRefs") or item.get("character_refs")),
            "captionPreset": _text(item.get("captionPreset") or item.get("caption_preset"), "lower-info"),
            "layoutVariantKey": _text(item.get("layoutVariantKey") or item.get("layout_variant_key"), "routine-lower-info"),
            "layoutVariantNote": _text(item.get("layoutVariantNote") or item.get("layout_variant_note") or item.get("layoutNote")),
            "plannedTextCardAfter": _planned_text_card(
                item.get("plannedTextCardAfter")
                or item.get("planned_text_card_after")
                or item.get("plannedTransitionAfter")
                or item.get("planned_transition_after")
                or item.get("transitionCueAfter")
                or item.get("transition_cue_after")
                or item.get("textCardAfter")
                or item.get("chapterCardAfter")
            ),
            "sourceNeed": _text(item.get("sourceNeed") or item.get("source_need") or item.get("whyThisVisual")),
            "plannedDurationSec": _duration(item.get("plannedDurationSec") or item.get("durationSec") or item.get("duration"), 6.0),
        }
        asset_plan = item.get("assetPlan") or item.get("asset_plan")
        if not isinstance(asset_plan, dict):
            asset_plan = _default_asset_brief({**item, **beat}, topic)
        else:
            default_plan = _default_asset_brief({**item, **beat}, topic)
            asset_plan = {
                **default_plan,
                **asset_plan,
                "providers": [
                    provider
                    for provider in _list(asset_plan.get("providers") or default_plan["providers"])
                    if _text(provider) in PREPRODUCTION_ASSET_PROVIDERS
                ] or default_plan["providers"],
            }
        asset_plan = _sync_asset_plan_text_card(asset_plan, beat.get("plannedTextCardAfter") or {})
        beat["assetPlan"] = asset_plan
        normalized.append(beat)
    return normalized


def _validate_preproduction(topic: dict[str, Any], beats: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if len(_text(topic.get("whyNow") or topic.get("trendAnchor"))) < 12:
        errors.append({"field": "topicBrief.whyNow", "message": "preproduction needs a timely why-now or trend anchor before asset generation"})
    if len(_text(topic.get("viewerQuestion"))) < 8:
        errors.append({"field": "topicBrief.viewerQuestion", "message": "viewer question is required before writing Grok/Gemini prompts"})
    if len(_text(topic.get("audience"))) < 4:
        errors.append({"field": "topicBrief.audience", "message": "target audience is required"})
    if len(_text(topic.get("angle"))) < 10:
        errors.append({"field": "topicBrief.angle", "message": "specific editorial angle is required"})
    topic_blob = " ".join(str(topic.get(key) or "") for key in ("title", "angle", "viewerQuestion")).lower()
    if any(term.lower() in topic_blob for term in GENERIC_TOPIC_TERMS) and len(_text(topic.get("whyNow"))) < 20:
        errors.append({"field": "topicBrief", "message": "generic routine/reset topics need a concrete timely reason or should not enter production"})
    if len(beats) < 3:
        errors.append({"field": "storyboardBeats", "message": "at least three storyboard beats are required: hook, proof/action, payoff"})
    roles = {beat.get("role") for beat in beats}
    if "hook" not in roles:
        errors.append({"field": "storyboardBeats.role", "message": "a hook beat is required"})
    if not ({"payoff", "cta", "action"} & roles):
        errors.append({"field": "storyboardBeats.role", "message": "a payoff/action beat is required"})
    for index, beat in enumerate(beats, start=1):
        prefix = f"storyboardBeats[{index}]"
        if len(_text(beat.get("storyPurpose"))) < 10:
            errors.append({"field": f"{prefix}.storyPurpose", "message": "story purpose must explain why this beat exists"})
        if len(_text(beat.get("onScreenText"))) < 4:
            errors.append({"field": f"{prefix}.onScreenText", "message": "viewer-facing caption text is required"})
        if len(_text(beat.get("narrationLine"))) < 8:
            errors.append({"field": f"{prefix}.narrationLine", "message": "TTS line must be written before source generation"})
        if len(_text(beat.get("visualAction"))) < 12:
            errors.append({"field": f"{prefix}.visualAction", "message": "visual action must be concrete enough for a first-second shot"})
        if len(_text(beat.get("sourceNeed"))) < 12:
            warnings.append({"field": f"{prefix}.sourceNeed", "message": "record why this source is necessary instead of using generic B-roll"})
        providers = set(beat.get("assetPlan", {}).get("providers") or [])
        if "gemini-web-image" not in providers:
            warnings.append({"field": f"{prefix}.assetPlan.providers", "message": "Gemini reference image is recommended before Grok video"})
        if "grok-web-video" not in providers and "operator-owned-source" not in providers:
            errors.append({"field": f"{prefix}.assetPlan.providers", "message": "Grok video or operator-owned source is required for each beat"})
    return {
        "ok": not errors,
        "status": "ready" if not errors else "blocked",
        "errorCount": len(errors),
        "warningCount": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def _storyboard_markdown(topic: dict[str, Any], beats: list[dict[str, Any]], validation: dict[str, Any]) -> str:
    lines = [
        f"# {_text(topic.get('title'), 'Preproduction Storyboard')}",
        "",
        f"- Status: {validation['status']}",
        f"- Why now: {_text(topic.get('whyNow') or topic.get('trendAnchor'))}",
        f"- Audience: {_text(topic.get('audience'))}",
        f"- Viewer question: {_text(topic.get('viewerQuestion'))}",
        f"- Angle: {_text(topic.get('angle'))}",
        "",
        "## Beats",
        "",
    ]
    for beat in beats:
        lines.extend([
            f"### {beat['beatId']} - {beat['role']}",
            f"- Purpose: {beat['storyPurpose']}",
            f"- On-screen: {beat['onScreenText']}",
            f"- TTS: {beat['narrationLine']}",
            f"- Visible action: {beat['visualAction']}",
            f"- Source need: {beat['sourceNeed']}",
            f"- Planned transition cue after: {beat['plannedTextCardAfter'].get('text', '') if beat.get('plannedTextCardAfter') else ''}",
            f"- Gemini prompt: {beat['assetPlan']['geminiWebImage']['prompt']}",
            f"- Grok prompt: {beat['assetPlan']['grokWebVideo']['prompt']}",
            "",
        ])
    return "\n".join(lines).strip() + "\n"


def _beat_continuity_note(beat: dict[str, Any]) -> str:
    characters = ", ".join(str(item).strip() for item in beat.get("characters") or [] if str(item).strip())
    location = _text(beat.get("allowedLocation"))
    anchors = [
        characters or "hands or subject",
        location or "real-world setting",
        "same key prop",
        "natural phone-camera light",
    ]
    return f"same {', '.join(anchors)}"


def _preproduction_to_episode_payload(
    data: dict[str, Any],
    episode_id: str,
    topic: dict[str, Any],
    beats: list[dict[str, Any]],
) -> dict[str, Any]:
    script_text = " ".join(beat["narrationLine"] for beat in beats if beat.get("narrationLine"))
    shots: list[dict[str, Any]] = []
    for beat in beats:
        asset_plan = beat.get("assetPlan") or {}
        shots.append({
            "cutId": beat["cutId"],
            "sceneId": beat["sceneId"],
            "blockId": "B01",
            "role": "a_roll",
            "scene": beat["storyPurpose"],
            "characters": beat["characters"] or [_text(topic.get("audience"), "viewer")],
            "allowedLocation": beat["allowedLocation"] or "topic-matched real-world setting",
            "forbiddenLocations": beat["forbiddenLocations"] or ["generic office filler", "abstract montage"],
            "plannedDurationSec": beat["plannedDurationSec"],
            "assignedScript": beat["narrationLine"],
            "subtitleText": beat["onScreenText"],
            "imagePrompt": asset_plan.get("geminiWebImage", {}).get("prompt", ""),
            "grokPrompt": asset_plan.get("grokWebVideo", {}).get("prompt", ""),
            "promptProfile": "storyboard-first-shortform",
            "visualAction": beat["visualAction"],
            "sourceNeed": beat["sourceNeed"],
            "topicAngle": _text(topic.get("angle")),
            "audience": _text(topic.get("audience")),
            "whyNow": _text(topic.get("whyNow") or topic.get("trendAnchor")),
            "hookNote": beat["visualAction"],
            "continuityNote": _beat_continuity_note(beat),
            "layoutVariantNote": beat.get("layoutVariantNote") or beat.get("sourceNeed") or "caption-safe, subject-visible, no generic filler",
            "plannedTextCardAfter": beat.get("plannedTextCardAfter") or {},
            "captionPreset": beat.get("captionPreset") or "lower-info",
        })
    return {
        "episodeId": episode_id,
        "title": _text(data.get("title") or topic.get("title"), episode_id),
        "targetPhase": _text(data.get("targetPhase") or data.get("target_phase"), "phase1"),
        "templateType": _text(data.get("templateType") or data.get("template_type"), "authentic_vlog"),
        "batchSize": int(_duration(data.get("batchSize") or data.get("batch_size"), DEFAULT_BATCH_SIZE)),
        "qualityLoopRequired": True,
        "promptOutputGateRequired": True,
        "artifactOutputGateRequired": True,
        "characterBible": {
            "topic": {
                "whyNow": topic.get("whyNow") or topic.get("trendAnchor"),
                "audience": topic.get("audience"),
                "viewerQuestion": topic.get("viewerQuestion"),
                "angle": topic.get("angle"),
            }
        },
        "scriptBlocks": [
            {
                "blockId": "B01",
                "title": _text(topic.get("title"), episode_id),
                "text": script_text,
                "targetDurationSec": round(sum(float(beat["plannedDurationSec"]) for beat in beats), 2),
            }
        ],
        "shots": shots,
    }


def _write_preproduction(data: dict[str, Any]) -> dict[str, Any]:
    episode_id = _episode_id(data.get("episodeId") or data.get("projectId") or data.get("title"))
    episode_dir = _episode_dir(episode_id)
    preproduction_dir = episode_dir / "preproduction"
    now = _utc_now()
    topic = _topic_brief(data)
    beats = _normalize_storyboard_beats(data, topic)
    validation = _validate_preproduction(topic, beats)
    quality_ratchet = _quality_ratchet_template(data, episode_id, topic, beats)
    quality_loop_standard = _quality_loop_standard(episode_id, topic, beats, quality_ratchet, now)
    quality_iteration_ledger = _quality_iteration_ledger(episode_id, quality_loop_standard, now)
    quality_loop_paths = _quality_loop_paths(episode_id)
    asset_briefs = {
        "schema": "video-studio.preproduction-asset-briefs.v1",
        "episodeId": episode_id,
        "createdAt": now,
        "policy": {
            "usesApi": False,
            "usesPaidApi": False,
            "geminiWebImage": "prompt-fill/reference image only; generate/save remains operator-owned",
            "grokWebVideo": "existing signed-in Grok Imagine browser handoff; local MP4 import/review required",
            "qualityRatchetRequired": True,
            "qualityRatchetFields": list(QUALITY_RATCHET_REQUIRED_FIELDS),
        },
        "beats": [
            {
                "beatId": beat["beatId"],
                "sceneId": beat["sceneId"],
                "cutId": beat["cutId"],
                "role": beat["role"],
                "onScreenText": beat["onScreenText"],
                "narrationLine": beat["narrationLine"],
                "visualAction": beat["visualAction"],
                "plannedTextCardAfter": beat.get("plannedTextCardAfter") or {},
                "assetPlan": beat["assetPlan"],
            }
            for beat in beats
        ],
    }
    episode_payload = _preproduction_to_episode_payload(data, episode_id, topic, beats)
    manifest = {
        "schema": "video-studio.preproduction-plan.v1",
        "episodeId": episode_id,
        "title": _text(data.get("title") or topic.get("title"), episode_id),
        "createdAt": now,
        "updatedAt": now,
        "status": validation["status"],
        "qualityRatchetRequired": True,
        "qualityRatchet": quality_ratchet,
        "qualityLoopRequired": True,
        "qualityLoopStandardVersion": QUALITY_LOOP_STANDARD_VERSION,
        "topicBrief": topic,
        "counts": {
            "beats": len(beats),
            "assetBriefs": len(asset_briefs["beats"]),
            "estimatedDurationSec": round(sum(float(beat["plannedDurationSec"]) for beat in beats), 2),
        },
        "paths": {
            "preproductionDir": str(preproduction_dir),
            "storyboard": str(preproduction_dir / "storyboard.json"),
            "storyboardMarkdown": str(preproduction_dir / "storyboard.md"),
            "assetBriefs": str(preproduction_dir / "asset-briefs.json"),
            "episodePlanRequest": str(preproduction_dir / "episode-plan-request.json"),
            "qualityLoopStandard": str(quality_loop_paths["standard"]),
            "qualityIterationLedger": str(quality_loop_paths["ledger"]),
        },
        "compatibility": {
            "usesExistingEpisodePlan": True,
            "usesExistingGrokHandoff": True,
            "usesGeminiWebImageHandoff": True,
            "usesApiProviders": False,
            "usesPaidApiProviders": False,
            "changesExistingGrokContract": False,
            "changesRenderContract": False,
            "databaseRequired": False,
        },
        "gate": {
            "name": "preproduction-before-browser-handoff",
            "requiredBefore": [
                "gemini-web-image-reference",
                "grok-web-video-generation",
                "quality-ratchet-before-render",
                "quality-loop-iteration-ledger",
                "render",
            ],
            "status": validation["status"],
        },
    }
    preproduction_dir.mkdir(parents=True, exist_ok=True)
    _write_json(preproduction_dir / "topic-brief.json", {"schema": "video-studio.topic-brief.v1", "episodeId": episode_id, **topic})
    _write_json(preproduction_dir / "storyboard.json", {"schema": "video-studio.storyboard.v1", "episodeId": episode_id, "beats": beats})
    (preproduction_dir / "storyboard.md").write_text(_storyboard_markdown(topic, beats, validation), encoding="utf-8")
    _write_json(preproduction_dir / "asset-briefs.json", asset_briefs)
    _write_json(preproduction_dir / "episode-plan-request.json", episode_payload)
    _write_json(quality_loop_paths["standard"], quality_loop_standard)
    _write_json(quality_loop_paths["ledger"], quality_iteration_ledger)
    _write_json(preproduction_dir / "preproduction-manifest.json", manifest)
    _write_json(preproduction_dir / "validation.json", {"schema": "video-studio.preproduction-validation.v1", **validation})

    episode_plan = None
    create_episode_plan = data.get("createEpisodePlan") is True or data.get("create_episode_plan") is True
    if create_episode_plan and validation["ok"]:
        episode_plan = _write_episode(episode_payload)

    return {
        "ok": validation["ok"],
        "episodeId": episode_id,
        "status": validation["status"],
        "manifestPath": str(preproduction_dir / "preproduction-manifest.json"),
        "storyboardPath": str(preproduction_dir / "storyboard.json"),
        "storyboardMarkdownPath": str(preproduction_dir / "storyboard.md"),
        "assetBriefsPath": str(preproduction_dir / "asset-briefs.json"),
        "episodePlanRequestPath": str(preproduction_dir / "episode-plan-request.json"),
        "qualityLoopStandardPath": str(quality_loop_paths["standard"]),
        "qualityIterationLedgerPath": str(quality_loop_paths["ledger"]),
        "manifest": manifest,
        "validation": validation,
        "topicBrief": topic,
        "storyboard": {"beats": beats},
        "assetBriefs": asset_briefs,
        "qualityLoopStandard": quality_loop_standard,
        "qualityIterationLedger": quality_iteration_ledger,
        "episodePlan": episode_plan,
    }


def _candidate_source_check(source_path: object, provider: str) -> dict[str, Any]:
    raw_path = _text(source_path)
    if not raw_path:
        return {
            "sourcePath": "",
            "resolvedPath": "",
            "exists": False,
            "withinProject": False,
            "extensionOk": False,
        }
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = _project_root / candidate
    try:
        resolved = candidate.resolve(strict=False)
        root = _project_root.resolve(strict=False)
    except OSError:
        resolved = candidate
        root = _project_root
    try:
        within_project = resolved == root or root in resolved.parents
    except RuntimeError:
        within_project = False
    suffix = resolved.suffix.lower()
    expected_suffixes = {".mp4", ".mov", ".m4v"} if provider in PREPRODUCTION_MOTION_SOURCE_PROVIDERS else {".png", ".jpg", ".jpeg", ".webp"}
    return {
        "sourcePath": raw_path,
        "resolvedPath": str(resolved),
        "exists": resolved.exists(),
        "withinProject": within_project,
        "extensionOk": suffix in expected_suffixes,
        "expectedExtensions": sorted(expected_suffixes),
    }


def _candidate_review_source(data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = data.get("candidates") or data.get("assetCandidates") or data.get("asset_candidates") or []
    return candidates if isinstance(candidates, list) else []


def _normalize_asset_candidate_reviews(data: dict[str, Any], beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    beats_by_id = {str(beat.get("beatId") or ""): beat for beat in beats}
    beats_by_scene = {str(beat.get("sceneId") or ""): beat for beat in beats}
    counters: dict[str, int] = {}
    normalized: list[dict[str, Any]] = []
    for item in _candidate_review_source(data):
        if not isinstance(item, dict):
            continue
        beat_id = _text(item.get("beatId") or item.get("beat_id"))
        scene_id = _text(item.get("sceneId") or item.get("scene_id"))
        beat = beats_by_id.get(beat_id) or beats_by_scene.get(scene_id)
        if beat:
            beat_id = str(beat["beatId"])
            scene_id = str(beat["sceneId"])
        provider = _text(item.get("provider"), "grok-web-video").lower().replace("_", "-")
        if provider not in PREPRODUCTION_ASSET_PROVIDERS:
            provider = "operator-owned-source"
        counters[beat_id] = counters.get(beat_id, 0) + 1
        candidate_id = _text(
            item.get("candidateId") or item.get("candidate_id"),
            f"{beat_id or scene_id or 'beat'}-{provider}-{counters[beat_id]:02d}",
        )
        review = item.get("review") if isinstance(item.get("review"), dict) else {}
        accepted = item.get("accepted")
        if accepted is None:
            accepted = review.get("accepted")
        normalized_review = {
            "accepted": accepted is True,
            "storyboardMatch": review.get("storyboardMatch") is True or item.get("storyboardMatch") is True,
            "firstSecondAction": review.get("firstSecondAction") is True or item.get("firstSecondAction") is True,
            "artifactFree": review.get("artifactFree") is True or item.get("artifactFree") is True,
            "captionSafe": review.get("captionSafe") is True or item.get("captionSafe") is True,
            "phoneSizeWatch": review.get("phoneSizeWatch") is True or item.get("phoneSizeWatch") is True,
            "sourceProvenanceOk": review.get("sourceProvenanceOk") is True or item.get("sourceProvenanceOk") is True,
            "noGenericBroll": review.get("noGenericBroll") is True or item.get("noGenericBroll") is True,
            "qualityReviewNote": _text(review.get("qualityReviewNote") or item.get("qualityReviewNote")),
            "sourceRationale": _text(review.get("sourceRationale") or item.get("sourceRationale")),
            "rejectionReason": _text(review.get("rejectionReason") or item.get("rejectionReason")),
        }
        source_path = item.get("sourcePath") or item.get("source_path") or item.get("localPath") or item.get("local_path")
        normalized.append({
            "candidateId": candidate_id,
            "beatId": beat_id,
            "sceneId": scene_id,
            "cutId": _text(item.get("cutId") or item.get("cut_id") or (beat or {}).get("cutId")),
            "provider": provider,
            "assetKind": "motion-source" if provider in PREPRODUCTION_MOTION_SOURCE_PROVIDERS else "image-reference",
            "sourcePath": _text(source_path),
            "sourceUrl": _text(item.get("sourceUrl") or item.get("source_url") or item.get("resultUrl") or item.get("result_url")),
            "fileName": _text(item.get("fileName") or item.get("file_name") or Path(_text(source_path) or candidate_id).name),
            "prompt": _text(item.get("prompt")),
            "review": normalized_review,
            "sourceCheck": _candidate_source_check(source_path, provider),
        })
    return normalized


def _validate_asset_candidate_reviews(
    preproduction: dict[str, Any],
    beats: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if preproduction.get("status") != "ready":
        errors.append({"field": "preproduction.status", "message": "preproduction must be ready before asset candidate review"})
    beats_by_id = {str(beat.get("beatId") or ""): beat for beat in beats}
    accepted_references: dict[str, list[dict[str, Any]]] = {beat_id: [] for beat_id in beats_by_id}
    accepted_motion: dict[str, list[dict[str, Any]]] = {beat_id: [] for beat_id in beats_by_id}
    for index, candidate in enumerate(candidates, start=1):
        prefix = f"candidates[{index}]"
        beat_id = str(candidate.get("beatId") or "")
        provider = str(candidate.get("provider") or "")
        review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
        source_check = candidate.get("sourceCheck") if isinstance(candidate.get("sourceCheck"), dict) else {}
        if beat_id not in beats_by_id:
            errors.append({"field": f"{prefix}.beatId", "message": "candidate must reference a storyboard beatId"})
            continue
        if not review.get("accepted"):
            if len(_text(review.get("rejectionReason"))) < 12:
                warnings.append({"field": f"{prefix}.review.rejectionReason", "message": "rejected candidates should record why they failed"})
            continue
        required_flags = dict(ASSET_REVIEW_REQUIRED_FLAGS)
        if provider in PREPRODUCTION_MOTION_SOURCE_PROVIDERS:
            required_flags.update(MOTION_REVIEW_REQUIRED_FLAGS)
        for field, message in required_flags.items():
            if review.get(field) is not True:
                errors.append({"field": f"{prefix}.review.{field}", "message": message})
        if len(_text(review.get("qualityReviewNote"))) < 24:
            errors.append({"field": f"{prefix}.review.qualityReviewNote", "message": "accepted candidates need concrete manual quality evidence"})
        if len(_text(review.get("sourceRationale"))) < 16:
            errors.append({"field": f"{prefix}.review.sourceRationale", "message": "accepted candidates need a source rationale tied to the storyboard"})
        if provider in PREPRODUCTION_MOTION_SOURCE_PROVIDERS:
            if not source_check.get("sourcePath"):
                errors.append({"field": f"{prefix}.sourcePath", "message": "accepted motion source requires a local MP4 path"})
            elif not source_check.get("exists"):
                errors.append({"field": f"{prefix}.sourcePath", "message": "accepted motion source local file does not exist"})
            elif not source_check.get("withinProject"):
                errors.append({"field": f"{prefix}.sourcePath", "message": "accepted motion source must stay inside the project workspace"})
            elif not source_check.get("extensionOk"):
                errors.append({"field": f"{prefix}.sourcePath", "message": "accepted motion source must be an MP4/MOV/M4V file"})
            accepted_motion[beat_id].append(candidate)
        elif provider in PREPRODUCTION_IMAGE_REFERENCE_PROVIDERS:
            if not (source_check.get("exists") or candidate.get("sourceUrl")):
                errors.append({"field": f"{prefix}.sourcePath", "message": "accepted Gemini reference needs a saved local image or visible result URL"})
            elif source_check.get("sourcePath") and not source_check.get("extensionOk"):
                errors.append({"field": f"{prefix}.sourcePath", "message": "accepted Gemini reference must be an image file"})
            accepted_references[beat_id].append(candidate)
    for beat_id, beat in beats_by_id.items():
        if not accepted_references.get(beat_id):
            warnings.append({"field": f"{beat_id}.geminiReference", "message": "Gemini reference image is not accepted yet; Grok generation may drift from the storyboard"})
        if not accepted_motion.get(beat_id):
            errors.append({"field": f"{beat_id}.motionSource", "message": "each storyboard beat needs one accepted Grok/operator motion source before render"})
    return {
        "ok": not errors,
        "status": "ready-for-render" if not errors else "blocked",
        "readyForRender": not errors,
        "readyBeatCount": sum(1 for beat_id in beats_by_id if accepted_motion.get(beat_id)),
        "totalBeatCount": len(beats_by_id),
        "acceptedReferenceCount": sum(len(items) for items in accepted_references.values()),
        "acceptedMotionCount": sum(len(items) for items in accepted_motion.values()),
        "errorCount": len(errors),
        "warningCount": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def _accepted_source_map(
    episode_id: str,
    beats: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    quality_ratchet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    accepted_motion = [
        candidate
        for candidate in candidates
        if candidate.get("provider") in PREPRODUCTION_MOTION_SOURCE_PROVIDERS and candidate.get("review", {}).get("accepted") is True
    ]
    accepted_by_beat: dict[str, dict[str, Any]] = {}
    for candidate in accepted_motion:
        accepted_by_beat.setdefault(str(candidate.get("beatId") or ""), candidate)
    scenes: list[dict[str, Any]] = []
    for beat in beats:
        candidate = accepted_by_beat.get(str(beat.get("beatId") or ""))
        scenes.append({
            "beatId": beat.get("beatId"),
            "sceneId": beat.get("sceneId"),
            "cutId": beat.get("cutId"),
            "onScreenText": beat.get("onScreenText"),
            "narrationLine": beat.get("narrationLine"),
            "visualAction": beat.get("visualAction"),
            "plannedTextCardAfter": beat.get("plannedTextCardAfter") or {},
            "accepted": candidate is not None,
            "acceptedCandidate": candidate,
        })
    return {
        "schema": "video-studio.accepted-source-map.v1",
        "episodeId": episode_id,
        "createdAt": _utc_now(),
        "status": "ready-for-render" if all(scene["accepted"] for scene in scenes) else "blocked",
        "qualityRatchetRequired": True,
        "qualityRatchet": quality_ratchet or {},
        "scenes": scenes,
    }


def _write_asset_candidate_review(episode_id_value: str, data: dict[str, Any]) -> dict[str, Any]:
    episode_id = _episode_id(episode_id_value)
    preproduction = _load_episode_file(episode_id, "preproduction/preproduction-manifest.json")
    storyboard = _load_episode_file(episode_id, "preproduction/storyboard.json")
    asset_briefs = _load_episode_file(episode_id, "preproduction/asset-briefs.json")
    if preproduction is None or storyboard is None or asset_briefs is None:
        raise ValueError("preproduction manifest, storyboard, and asset briefs are required before asset candidate review")
    beats = storyboard.get("beats") if isinstance(storyboard.get("beats"), list) else []
    candidates = _normalize_asset_candidate_reviews(data, beats)
    validation = _validate_asset_candidate_reviews(preproduction, beats, candidates)
    preproduction_dir = _episode_dir(episode_id) / "preproduction"
    now = _utc_now()
    quality_ratchet = preproduction.get("qualityRatchet") if isinstance(preproduction.get("qualityRatchet"), dict) else {}
    source_map = _accepted_source_map(episode_id, beats, candidates, quality_ratchet)
    packet = {
        "schema": "video-studio.preproduction-asset-candidate-review.v1",
        "episodeId": episode_id,
        "createdAt": now,
        "updatedAt": now,
        "status": validation["status"],
        "qualityRatchetRequired": preproduction.get("qualityRatchetRequired") is True,
        "qualityRatchet": quality_ratchet,
        "policy": {
            "renderRequiresAcceptedMotionSourcePerBeat": True,
            "acceptedMotionProviders": sorted(PREPRODUCTION_MOTION_SOURCE_PROVIDERS),
            "acceptedImageReferenceProviders": sorted(PREPRODUCTION_IMAGE_REFERENCE_PROVIDERS),
            "usesApi": False,
            "usesPaidApi": False,
        },
        "validation": validation,
        "candidates": candidates,
        "acceptedSourceMapPath": str(preproduction_dir / "accepted-source-map.json"),
    }
    _write_json(preproduction_dir / "asset-candidate-review.json", packet)
    _write_json(preproduction_dir / "accepted-source-map.json", source_map)
    return {
        "ok": validation["ok"],
        "episodeId": episode_id,
        "status": validation["status"],
        "validation": validation,
        "candidateReviewPath": str(preproduction_dir / "asset-candidate-review.json"),
        "acceptedSourceMapPath": str(preproduction_dir / "accepted-source-map.json"),
        "candidateReview": packet,
        "acceptedSourceMap": source_map,
    }


def _grok_handoff_manifest_path(project_id: str) -> Path:
    return _project_root / "storage" / "grok-handoffs" / _episode_id(project_id) / "handoff.json"


def _grok_source_path(project_id: str, decision: dict[str, Any]) -> str:
    selected = decision.get("selectedCandidate") if isinstance(decision.get("selectedCandidate"), dict) else {}
    source_path = _text(selected.get("sourcePath"))
    if source_path:
        return source_path
    file_name = Path(_text(decision.get("selectedFileName"))).name
    if not file_name:
        return ""
    return str(Path("storage") / "grok-handoffs" / _episode_id(project_id) / "incoming" / file_name)


def _load_episode_grok_review_candidates(
    episode_id: str,
    beats: list[dict[str, Any]],
    data: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    handoffs = _load_episode_file(episode_id, "browser-handoffs/browser-handoffs.json")
    if handoffs is None:
        raise ValueError("episode browser handoffs are required before syncing Grok candidates")
    beats_by_scene = {str(beat.get("sceneId") or ""): beat for beat in beats}
    global_phone_size = data.get("phoneSizeWatchApproved") is True
    global_no_generic = data.get("noGenericBrollApproved") is True
    scene_overrides = data.get("sceneOverrides") if isinstance(data.get("sceneOverrides"), dict) else {}
    candidates: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for batch in handoffs.get("batches", {}).get("grokWebVideo") or []:
        if not isinstance(batch, dict):
            continue
        project_id = _text(batch.get("handoffProjectId") or batch.get("handoff_project_id"))
        if not project_id:
            continue
        manifest_path = _grok_handoff_manifest_path(project_id)
        if not manifest_path.exists():
            warnings.append({"field": project_id, "message": "Grok handoff manifest not found"})
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        decisions = manifest.get("reviewDecisions") if isinstance(manifest.get("reviewDecisions"), dict) else {}
        for scene_id, decision in decisions.items():
            if not isinstance(decision, dict) or decision.get("accepted") is not True:
                continue
            beat = beats_by_scene.get(str(scene_id))
            if not beat:
                warnings.append({"field": str(scene_id), "message": "accepted Grok scene is not in the storyboard"})
                continue
            selected = decision.get("selectedCandidate") if isinstance(decision.get("selectedCandidate"), dict) else {}
            override = scene_overrides.get(str(scene_id)) if isinstance(scene_overrides.get(str(scene_id)), dict) else {}
            phone_size = (
                decision.get("phoneSizeWatch") is True
                or override.get("phoneSizeWatchApproved") is True
                or global_phone_size
            )
            no_generic = (
                decision.get("noGenericBroll") is True
                or override.get("noGenericBrollApproved") is True
                or global_no_generic
            )
            source_provenance = (
                selected.get("sourceProvenance")
                if isinstance(selected.get("sourceProvenance"), dict)
                else {}
            )
            source_provenance_ok = (
                decision.get("sourceProvenanceConfirmed") is True
                or source_provenance.get("acceptAsGrokMainSource") is True
                or source_provenance.get("status") in {"direct-imported-grok-mp4", "operator-uploaded-grok-mp4"}
            )
            candidates.append({
                "candidateId": f"{beat['beatId']}-grok-review-{_episode_id(project_id)}",
                "beatId": beat["beatId"],
                "sceneId": beat["sceneId"],
                "cutId": beat["cutId"],
                "provider": "grok-web-video",
                "sourcePath": _grok_source_path(project_id, decision),
                "fileName": _text(decision.get("selectedFileName") or selected.get("fileName")),
                "sourceUrl": _text(source_provenance.get("sourceUrl") or source_provenance.get("eventUrl")),
                "prompt": _text(next(
                    (
                        scene.get("grok_prompt") or scene.get("prompt")
                        for scene in manifest.get("scenes") or []
                        if isinstance(scene, dict) and str(scene.get("sceneId") or "") == str(scene_id)
                    ),
                    "",
                )),
                "review": {
                    "accepted": True,
                    "storyboardMatch": decision.get("shotLockMatch") is True and decision.get("sceneAssemblyOk") is True,
                    "firstSecondAction": decision.get("firstTwoSecondHook") is True,
                    "artifactFree": decision.get("artifactFree") is True and _text(decision.get("visualQualityVerdict")) == "pass",
                    "captionSafe": decision.get("captionSafe") is True,
                    "phoneSizeWatch": phone_size,
                    "sourceProvenanceOk": source_provenance_ok,
                    "noGenericBroll": no_generic,
                    "qualityReviewNote": _text(decision.get("qualityReviewNote")),
                    "sourceRationale": _text(decision.get("sourceRationale")),
                },
            })
    return candidates, warnings


def _merge_asset_candidates(existing: list[dict[str, Any]], synced: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replace_keys = {
        (str(item.get("beatId") or ""), str(item.get("provider") or ""))
        for item in synced
    }
    kept = [
        item for item in existing
        if (str(item.get("beatId") or ""), str(item.get("provider") or "")) not in replace_keys
    ]
    return [*kept, *synced]


def _sync_grok_asset_candidates(episode_id_value: str, data: dict[str, Any]) -> dict[str, Any]:
    episode_id = _episode_id(episode_id_value)
    storyboard = _load_episode_file(episode_id, "preproduction/storyboard.json")
    if storyboard is None:
        raise ValueError("preproduction storyboard is required before syncing Grok candidates")
    beats = storyboard.get("beats") if isinstance(storyboard.get("beats"), list) else []
    synced_candidates, warnings = _load_episode_grok_review_candidates(episode_id, beats, data)
    existing_review = _load_episode_file(episode_id, "preproduction/asset-candidate-review.json")
    existing_candidates = (
        existing_review.get("candidates")
        if isinstance(existing_review, dict) and isinstance(existing_review.get("candidates"), list)
        else []
    )
    preserve_existing = data.get("preserveExisting") is not False
    candidates = _merge_asset_candidates(existing_candidates, synced_candidates) if preserve_existing else synced_candidates
    result = _write_asset_candidate_review(episode_id, {"candidates": candidates})
    result["syncedCandidateCount"] = len(synced_candidates)
    result["syncWarnings"] = warnings
    result["grokReviewSync"] = {
        "schema": "video-studio.grok-review-sync.v1",
        "episodeId": episode_id,
        "syncedCandidateCount": len(synced_candidates),
        "warningCount": len(warnings),
        "requiresPhoneSizeWatchApproval": not (data.get("phoneSizeWatchApproved") is True),
        "requiresNoGenericBrollApproval": not (data.get("noGenericBrollApproved") is True),
    }
    _write_json(_episode_dir(episode_id) / "preproduction" / "grok-review-sync.json", result["grokReviewSync"])
    return result


def _write_episode(data: dict[str, Any]) -> dict[str, Any]:
    episode_id = _episode_id(data.get("episodeId") or data.get("projectId") or data.get("title"))
    target_phase = _text(data.get("targetPhase") or data.get("target_phase"), "phase1").lower()
    if target_phase not in PHASE_LIMITS:
        target_phase = "phase1"
    template_type = _text(data.get("templateType") or data.get("template_type"), "persona_story")
    batch_size = int(_duration(data.get("batchSize") or data.get("batch_size"), DEFAULT_BATCH_SIZE))
    blocks = _script_blocks(data)
    character_bible = _character_bible_markdown(data)
    cuts = _normalize_shots(data, blocks)
    if not cuts:
        raise ValueError("shots, shotPlan, or draftScenes are required")

    limit = PHASE_LIMITS[target_phase]["maxCuts"]
    if len(cuts) > limit:
        raise ValueError(f"{target_phase} accepts at most {limit} cuts for this infrastructure slice")

    now = _utc_now()
    episode_dir = _episode_dir(episode_id)
    batches = _batch_manifests(episode_id, cuts, batch_size, template_type, character_bible)
    sync_map = {
        "schema": "video-studio.shot-sync-map.v1",
        "episodeId": episode_id,
        "createdAt": now,
        "updatedAt": now,
        "statusModel": {
            "sourceStatuses": sorted(SOURCE_STATUSES),
            "syncStatuses": sorted(SYNC_STATUSES),
        },
        "cuts": cuts,
    }
    validation = _validate_sync_map(sync_map)
    output_gate = _episode_output_gate(episode_id, validation, data, "episode-artifact-output")
    if output_gate["status"] != "pass":
        raise OutputGateBlocked("episode output gate blocked: " + _output_gate_error(output_gate), output_gate)
    browser_handoffs = _browser_handoff_plan(
        episode_dir,
        episode_id,
        cuts,
        batches,
        batch_size,
        character_bible,
        output_gate,
    )

    manifest = {
        "schema": "video-studio.episode-manifest.v1",
        "episodeId": episode_id,
        "title": _text(data.get("title"), episode_id),
        "targetPhase": target_phase,
        "phaseLabel": PHASE_LIMITS[target_phase]["label"],
        "templateType": template_type,
        "createdAt": now,
        "updatedAt": now,
        "paths": {
            "episodeDir": str(episode_dir),
            "characterBible": str(episode_dir / "character-bible.md"),
            "scriptBlocks": str(episode_dir / "script-blocks.json"),
            "shotPlan": str(episode_dir / "shot-plan.json"),
            "shotSyncMap": str(episode_dir / "shot-sync-map.json"),
            "storySyncAudit": str(episode_dir / "story-sync-audit" / "sync-report.json"),
            "browserHandoffs": str(episode_dir / "browser-handoffs" / "browser-handoffs.json"),
            "outputGate": str(episode_dir / "output-gates.json"),
        },
        "counts": {
            "scriptBlocks": len(blocks),
            "cuts": len(cuts),
            "batches": len(batches),
            "geminiImageBatches": len(browser_handoffs["batches"]["geminiWebImage"]),
            "grokVideoBatches": len(browser_handoffs["batches"]["grokWebVideo"]),
            "estimatedDurationSec": round(sum(float(cut["plannedDurationSec"]) for cut in cuts), 2),
        },
        "batchSize": max(1, min(batch_size, 12)),
        "outputGate": output_gate,
        "batches": [
            {
                "batchId": batch["batchId"],
                "handoffProjectId": batch["handoffProjectId"],
                "cutIds": batch["cutIds"],
                "sceneIds": batch["sceneIds"],
                "plannedDurationSec": batch["plannedDurationSec"],
                "batchManifestPath": str(episode_dir / "batches" / batch["batchId"] / "batch-manifest.json"),
            }
            for batch in batches
        ],
        "compatibility": {
            "usesExistingGrokHandoff": True,
            "usesBrowserExtensionHandoff": True,
            "usesApiProviders": False,
            "changesExistingGrokContract": False,
            "changesRenderContract": False,
            "databaseRequired": False,
            "paidProviderRequired": False,
        },
    }
    sync_report = {
        "schema": "video-studio.story-sync-audit.v1",
        "episodeId": episode_id,
        "generatedAt": now,
        "validation": validation,
        "outputGate": output_gate,
        "nextActions": _next_actions(validation, batches),
    }

    episode_dir.mkdir(parents=True, exist_ok=True)
    (episode_dir / "character-bible.md").write_text(character_bible, encoding="utf-8")
    _write_json(episode_dir / "script-blocks.json", {"schema": "video-studio.script-blocks.v1", "episodeId": episode_id, "blocks": blocks})
    _write_json(episode_dir / "shot-plan.json", {"schema": "video-studio.shot-plan.v1", "episodeId": episode_id, "cuts": cuts})
    _write_json(episode_dir / "shot-sync-map.json", sync_map)
    _write_json(episode_dir / "episode-manifest.json", manifest)
    _write_json(episode_dir / "output-gates.json", output_gate)
    _write_json(episode_dir / "story-sync-audit" / "sync-report.json", sync_report)
    _write_json(episode_dir / "browser-handoffs" / "browser-handoffs.json", browser_handoffs)
    for batch in browser_handoffs["batches"]["geminiWebImage"]:
        _write_json(
            episode_dir / "browser-handoffs" / "gemini-web-image" / f"{batch['batchId']}.json",
            batch,
        )
    for batch in browser_handoffs["batches"]["grokWebVideo"]:
        _write_json(
            episode_dir / "browser-handoffs" / "grok-web-video" / f"{batch['batchId']}.json",
            batch,
        )
    for batch in batches:
        _write_json(episode_dir / "batches" / batch["batchId"] / "batch-manifest.json", {
            "schema": "video-studio.episode-batch-manifest.v1",
            "episodeId": episode_id,
            **batch,
        })

    return {
        "ok": True,
        "episodeId": episode_id,
        "manifestPath": str(episode_dir / "episode-manifest.json"),
        "shotSyncMapPath": str(episode_dir / "shot-sync-map.json"),
        "storySyncAuditPath": str(episode_dir / "story-sync-audit" / "sync-report.json"),
        "browserHandoffsPath": str(episode_dir / "browser-handoffs" / "browser-handoffs.json"),
        "outputGatePath": str(episode_dir / "output-gates.json"),
        "outputGate": output_gate,
        "manifest": manifest,
        "validation": validation,
        "batches": manifest["batches"],
        "browserHandoffs": {
            "mode": browser_handoffs["mode"],
            "usesApi": browser_handoffs["usesApi"],
            "providers": browser_handoffs["providers"],
        },
    }


def _next_actions(validation: dict[str, Any], batches: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if validation["errors"]:
        actions.append("Fix shot-sync-map errors before creating Grok handoff batches.")
    if validation["warnings"]:
        actions.append("Review warnings for duration, character, location, and script locks.")
    actions.append("Run Gemini web image handoff batches first, then review image continuity before Grok video generation.")
    if batches:
        actions.append("POST each batch handoffRequest to /api/grok-handoff after operator approval.")
    actions.append("Review imported MP4s by cut before segment render; do not promote template-only proof.")
    return actions


def _load_episode_file(episode_id: str, name: str) -> dict[str, Any] | None:
    path = _episode_dir(episode_id) / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@episodes_bp.route("/api/episodes/preproduction-plan", methods=["POST"])
def create_preproduction_plan_route():
    data = flask_request.get_json(silent=True) or {}
    try:
        payload = _write_preproduction(data)
    except OutputGateBlocked as exc:
        return jsonify({"ok": False, "error": str(exc), "outputGate": exc.output_gate}), 400
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify(payload), 200 if payload["ok"] else 400


@episodes_bp.route("/api/episodes/<episode_id>/preproduction", methods=["GET"])
def episode_preproduction_route(episode_id: str):
    manifest = _load_episode_file(episode_id, "preproduction/preproduction-manifest.json")
    if manifest is None:
        return jsonify({"ok": False, "error": "preproduction manifest not found"}), 404
    storyboard = _load_episode_file(episode_id, "preproduction/storyboard.json")
    asset_briefs = _load_episode_file(episode_id, "preproduction/asset-briefs.json")
    validation = _load_episode_file(episode_id, "preproduction/validation.json")
    quality_loop_standard = _load_episode_file(episode_id, "preproduction/quality-loop-standard.json")
    quality_iteration_ledger = _load_episode_file(episode_id, "preproduction/quality-iteration-ledger.json")
    return jsonify({
        "ok": manifest.get("status") == "ready",
        "episodeId": manifest["episodeId"],
        "preproduction": manifest,
        "storyboard": storyboard,
        "assetBriefs": asset_briefs,
        "validation": validation,
        "qualityLoopStandard": quality_loop_standard,
        "qualityIterationLedger": quality_iteration_ledger,
    })


@episodes_bp.route("/api/episodes/<episode_id>/preproduction/quality-loop", methods=["GET", "POST"])
def episode_preproduction_quality_loop_route(episode_id: str):
    if flask_request.method == "POST":
        data = flask_request.get_json(silent=True) or {}
        try:
            payload = _write_quality_loop_iteration(episode_id, data)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        return jsonify(payload), 200
    paths = _quality_loop_paths(episode_id)
    standard = _read_json_path(paths["standard"])
    ledger = _read_json_path(paths["ledger"])
    if standard is None or ledger is None:
        return jsonify({"ok": False, "error": "quality loop standard and ledger not found"}), 404
    return jsonify(_quality_loop_response_payload(episode_id, standard, ledger, paths))


@episodes_bp.route("/api/episodes/<episode_id>/preproduction/asset-candidates", methods=["GET", "POST"])
def episode_preproduction_asset_candidates_route(episode_id: str):
    if flask_request.method == "POST":
        data = flask_request.get_json(silent=True) or {}
        try:
            payload = _write_asset_candidate_review(episode_id, data)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        return jsonify(payload), 200 if payload["ok"] else 400
    review = _load_episode_file(episode_id, "preproduction/asset-candidate-review.json")
    source_map = _load_episode_file(episode_id, "preproduction/accepted-source-map.json")
    if review is None:
        return jsonify({"ok": False, "error": "asset candidate review not found"}), 404
    return jsonify({
        "ok": review.get("status") == "ready-for-render",
        "episodeId": _episode_id(episode_id),
        "candidateReview": review,
        "acceptedSourceMap": source_map,
    })


@episodes_bp.route("/api/episodes/<episode_id>/preproduction/sync-grok-candidates", methods=["POST"])
def episode_preproduction_sync_grok_candidates_route(episode_id: str):
    data = flask_request.get_json(silent=True) or {}
    if data.get("operatorApproved") is not True:
        return jsonify({"ok": False, "error": "operatorApproved=true is required before syncing Grok review candidates"}), 400
    try:
        payload = _sync_grok_asset_candidates(episode_id, data)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify(payload), 200 if payload["ok"] else 400


@episodes_bp.route("/api/episodes", methods=["POST"])
@episodes_bp.route("/api/episodes/plan", methods=["POST"])
def create_episode_route():
    data = flask_request.get_json(silent=True) or {}
    try:
        payload = _write_episode(data)
    except OutputGateBlocked as exc:
        return jsonify({"ok": False, "error": str(exc), "outputGate": exc.output_gate}), 400
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify(payload)


@episodes_bp.route("/api/episodes/<episode_id>/manifest", methods=["GET"])
def episode_manifest_route(episode_id: str):
    manifest = _load_episode_file(episode_id, "episode-manifest.json")
    if manifest is None:
        return jsonify({"ok": False, "error": "episode manifest not found"}), 404
    return jsonify({"ok": True, "manifest": manifest})


@episodes_bp.route("/api/episodes/<episode_id>/shot-sync-map", methods=["GET"])
def episode_shot_sync_route(episode_id: str):
    sync_map = _load_episode_file(episode_id, "shot-sync-map.json")
    if sync_map is None:
        return jsonify({"ok": False, "error": "shot-sync-map not found"}), 404
    return jsonify({"ok": True, "shotSyncMap": sync_map})


@episodes_bp.route("/api/episodes/<episode_id>/validate", methods=["GET", "POST"])
def episode_validate_route(episode_id: str):
    sync_map = _load_episode_file(episode_id, "shot-sync-map.json")
    if sync_map is None:
        return jsonify({"ok": False, "error": "shot-sync-map not found"}), 404
    validation = _validate_sync_map(sync_map)
    return jsonify({"ok": validation["ok"], "validation": validation})


@episodes_bp.route("/api/episodes/<episode_id>/grok-batches", methods=["GET"])
def episode_grok_batches_route(episode_id: str):
    manifest = _load_episode_file(episode_id, "episode-manifest.json")
    if manifest is None:
        return jsonify({"ok": False, "error": "episode manifest not found"}), 404
    batches = []
    for batch in manifest.get("batches") or []:
        batch_path = Path(batch.get("batchManifestPath") or "")
        if batch_path.exists():
            batches.append(json.loads(batch_path.read_text(encoding="utf-8")))
    return jsonify({"ok": True, "episodeId": manifest["episodeId"], "batches": batches})


@episodes_bp.route("/api/episodes/<episode_id>/browser-handoffs", methods=["GET"])
def episode_browser_handoffs_route(episode_id: str):
    handoffs = _load_episode_file(episode_id, "browser-handoffs/browser-handoffs.json")
    if handoffs is None:
        return jsonify({"ok": False, "error": "episode browser handoffs not found"}), 404
    return jsonify({"ok": True, "episodeId": handoffs["episodeId"], "browserHandoffs": handoffs})


@episodes_bp.route(
    "/api/episodes/<episode_id>/browser-handoffs/gemini-web-image/<batch_id>/extension-command",
    methods=["GET"],
)
def episode_gemini_image_extension_command_route(episode_id: str, batch_id: str):
    if str(flask_request.args.get("operatorApproved") or "").lower() != "true":
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true is required before the Chrome companion can read a Gemini prompt",
        }), 403
    normalized_batch_id = _episode_id(batch_id)
    batch = _load_episode_file(episode_id, f"browser-handoffs/gemini-web-image/{normalized_batch_id}.json")
    if batch is None:
        return jsonify({"ok": False, "error": "Gemini image handoff batch not found"}), 404
    output_gate = _current_episode_output_gate(episode_id, "prompt-output")
    if output_gate["status"] != "pass":
        return jsonify({
            "ok": False,
            "error": "prompt output gate blocked: " + _output_gate_error(output_gate),
            "promptOutputGate": output_gate,
        }), 409
    cuts = batch.get("cuts") if isinstance(batch.get("cuts"), list) else []
    requested_cut_id = _text(flask_request.args.get("cutId"))
    selected = None
    if requested_cut_id:
        selected = next((cut for cut in cuts if str(cut.get("cutId")) == requested_cut_id), None)
    selected = selected or next((cut for cut in cuts if str(cut.get("reviewStatus") or "").startswith("pending")), None)
    selected = selected or (cuts[0] if cuts else None)
    if not selected:
        return jsonify({"ok": False, "error": "No Gemini image cut is available for the Chrome companion"}), 400
    cut_id = _text(selected.get("cutId"))
    command_url = _gemini_extension_command_url(episode_id, normalized_batch_id, cut_id)
    payload = {
        "ok": True,
        "provider": "gemini-web-image",
        "commandKind": "image-prompt-fill",
        "stage": "image-reference",
        "promptOutputGate": output_gate,
        "usesApi": False,
        "usesPaidApi": False,
        "requiresOperatorBrowserSession": True,
        "canFillPrompt": True,
        "canClickGenerate": False,
        "canImportResult": False,
        "episodeId": _episode_id(episode_id),
        "batchId": normalized_batch_id,
        "cutId": cut_id,
        "sceneId": _text(selected.get("sceneId")),
        "expectedFileName": _text(selected.get("expectedFileName")),
        "prompt": _text(selected.get("prompt")),
        "targetUrl": GEMINI_WEB_URL,
        "commandUrl": command_url,
        "autostartUrl": _gemini_autostart_url(command_url),
        "eventEndpoint": _episode_extension_event_url(episode_id),
        "statusUrl": _bridge_url(f"/api/episodes/{_episode_id(episode_id)}/browser-handoffs"),
        "operatorAction": "Review the filled Gemini prompt, manually generate the image, then save/upload it with the expected cut file name.",
    }
    return jsonify(payload)


@episodes_bp.route("/api/episodes/<episode_id>/browser-handoffs/extension-event", methods=["POST"])
def episode_browser_handoff_extension_event_route(episode_id: str):
    episode_dir = _episode_dir(episode_id)
    if not (episode_dir / "browser-handoffs" / "browser-handoffs.json").exists():
        return jsonify({"ok": False, "error": "episode browser handoffs not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    browser_control_approved = data.get("browserControlApproved") is True
    extension_approved = data.get("extensionApproved") is True
    if data.get("operatorApproved") is not True or not (extension_approved or browser_control_approved):
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true and extensionApproved=true or browserControlApproved=true are required before browser handoff events are accepted",
        }), 403
    provider = _short_text(data.get("provider"), fallback="unknown-provider", limit=80)
    if provider not in {"gemini-web-image", "gemini-web-video", "grok-web-video"}:
        return jsonify({"ok": False, "error": "unsupported browser handoff provider"}), 400
    record = {
        "updatedAt": _utc_now(),
        "episodeId": _episode_id(episode_id),
        "provider": provider,
        "batchId": _short_text(data.get("batchId"), limit=80),
        "cutId": _short_text(data.get("cutId"), limit=80),
        "sceneId": _short_text(data.get("sceneId"), limit=80),
        "expectedFileName": _short_text(data.get("expectedFileName"), limit=140),
        "eventType": _short_text(data.get("eventType"), fallback="extension-event", limit=80),
        "status": _short_text(data.get("status"), fallback="reported", limit=80),
        "source": _short_text(data.get("source"), limit=120),
        "proofMode": _short_text(data.get("proofMode"), fallback="browser-control" if browser_control_approved else "extension", limit=80),
        "browserControlApproved": browser_control_approved,
        "extensionApproved": extension_approved,
        "detail": _short_text(data.get("detail") or data.get("message"), limit=400),
        "currentUrl": _short_text(data.get("currentUrl"), limit=260),
        "build": _short_text(data.get("build"), limit=80),
    }
    event_path = episode_dir / "browser-handoffs" / "extension-events.jsonl"
    _append_jsonl(event_path, record)
    return jsonify({
        "ok": True,
        "episodeId": _episode_id(episode_id),
        "latestExtensionEvent": record,
        "eventLogPath": str(event_path),
        "statusUrl": _bridge_url(f"/api/episodes/{_episode_id(episode_id)}/browser-handoffs"),
    })
