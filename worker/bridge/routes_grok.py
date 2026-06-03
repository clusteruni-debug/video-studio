"""Grok web handoff routes.

These routes intentionally do not call the paid xAI API. They create a local
handoff packet that an operator-approved browser automation runner can use:
scene prompts, expected MP4 filenames, an incoming download folder, and a sync
endpoint that attaches downloaded Grok clips back to Video Studio rendering.
"""
from __future__ import annotations

import json
import logging
import base64
import binascii
import math
import os
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

from flask import Blueprint, Response, jsonify, request as flask_request, send_from_directory

from worker.render.render_manifest import slugify

logger = logging.getLogger(__name__)

grok_bp = Blueprint("grok", __name__)

_bridge_host: str = "127.0.0.1"
_bridge_port: int = 5161
_project_root: Path = Path.cwd()
_safe_resolve = None
_manifest_io_lock = threading.RLock()
_background_automation_lock = threading.RLock()
_background_automation_threads: dict[str, threading.Thread] = {}
_manual_download_watch_lock = threading.RLock()
_manual_download_watch_threads: dict[str, threading.Thread] = {}
_manual_download_watch_cancel_events: dict[str, threading.Event] = {}

GROK_IMAGINE_URL = "https://grok.com/imagine"
GROK_PRODUCTION_QUEUE_VERSION = "take-ladder-v11-shot-lock-quality-floor"
MAX_OPERATOR_READY_WAIT_SECONDS = 7200.0
CHROME_DEFAULT_PROFILE_CDP_BLOCKER = "chrome-default-profile-not-supported"
CHROME_DEFAULT_PROFILE_CDP_GUIDANCE = (
    "Chrome 136+ does not allow --remote-debugging-port or --remote-debugging-pipe "
    "against the default Chrome data directory. Use the isolated Video Studio handoff "
    "profile, sign in to Grok/SuperGrok in that opened window once, then rerun the "
    "approved automation. Do not copy cookies or credentials."
)
CHROME_DEFAULT_PROFILE_ATTACH_BLOCKER = "default-chrome-cdp-attach-required"
CHROME_DEFAULT_PROFILE_SOCKET_ABORT_BLOCKER = "default-chrome-cdp-socket-aborted"
GROK_PROMPT_META_HARD_TERMS = (
    "tts",
    "voiceover",
    "narration",
    "subtitle plan",
    "caption plan",
    "layout plan",
    "safe zone",
    "checklist",
    "render",
    "production intent",
    "explain the intent",
    "explain why",
    "프롬프트",
    "렌더",
    "제작 기준",
    "체크리스트",
    "영상의 의도",
    "나레이션",
    "레이아웃",
)
GROK_PROMPT_META_COMPACT_PHRASES = (
    "이영상은",
    "이번영상은",
    "영상의의도",
    "어떤의도",
    "의도를설명",
    "영상의목적",
    "보는사람이",
    "영상을보는사람",
    "시청자가지금무엇을봐야",
    "시청자에게설명",
    "무엇을봐야",
    "화면은그대로",
    "나레이션으로설명",
    "자막으로설명",
    "티티에스",
)
GROK_VISUAL_LED_NO_VOICE_TEMPLATE_TYPES = frozenset({
    "authentic_vlog",
    "persona_story",
    "kculture_fandom",
    "live_recap",
})


def _default_chrome_attach_instruction(port: int | None = None) -> str:
    port_text = str(port or 9222)
    return (
        "Default Chrome/SuperGrok attach mode is attach-only. Video Studio will not "
        "launch the default Chrome profile, copy cookies, or store credentials. Start "
        "a local Chrome DevTools session yourself on 127.0.0.1:"
        f"{port_text}, then rerun the approved attach flow. On Chrome 136+ this usually "
        "requires a non-default operator profile that you sign in to manually; normal "
        "already-running Chrome will not expose CDP."
    )


def _default_chrome_policy_error(data: dict, port: int) -> str | None:
    if data.get("useDefaultChromeProfile") is not True:
        return None
    if data.get("launchBrowserApproved") is True:
        return CHROME_DEFAULT_PROFILE_CDP_GUIDANCE
    if data.get("attachDefaultChromeApproved") is not True:
        return (
            "attachDefaultChromeApproved=true is required before attaching to a "
            "user-launched logged-in Chrome/SuperGrok CDP session. "
            + _default_chrome_attach_instruction(port)
        )
    return None


def _automation_error_state(error_text: str, port: int | None = None) -> dict:
    socket_abort_error = (
        "WinError 10053" in error_text
        or "forcibly closed by the remote host" in error_text
        or "software in your host machine aborted" in error_text
        or "호스트 시스템" in error_text
    )
    chrome_default_launch_error = (
        CHROME_DEFAULT_PROFILE_CDP_GUIDANCE in error_text
        or "Chrome 136+" in error_text
        or "logged-in Chrome profile" in error_text
    )
    default_attach_error = (
        CHROME_DEFAULT_PROFILE_ATTACH_BLOCKER in error_text
        or "Default Chrome/SuperGrok attach mode" in error_text
        or "attachDefaultChromeApproved=true" in error_text
    )
    if default_attach_error:
        return {
            "requiresOperatorAction": True,
            "browserBlocker": CHROME_DEFAULT_PROFILE_ATTACH_BLOCKER,
            "operatorNextAction": _default_chrome_attach_instruction(port),
        }
    if socket_abort_error:
        return {
            "requiresOperatorAction": True,
            "browserBlocker": CHROME_DEFAULT_PROFILE_SOCKET_ABORT_BLOCKER,
            "operatorNextAction": (
                "The default Chrome CDP connection was aborted by the host/browser. "
                "Keep the existing signed-in Chrome profile open, load the Video Studio "
                "Grok Companion unpacked extension there, then use the companion Prep + "
                "Generate or Queue path for Grok-main MP4 import. Do not retry Edge/new "
                "profile CDP as the primary path."
            ),
        }
    if chrome_default_launch_error:
        return {
            "requiresOperatorAction": True,
            "browserBlocker": CHROME_DEFAULT_PROFILE_CDP_BLOCKER,
            "operatorNextAction": (
                "Use the isolated Video Studio Grok browser profile, complete "
                "Grok/SuperGrok login there once, then rerun approved automation."
            ),
        }
    return {"requiresOperatorAction": False}


def _is_grok_visual_led_no_voice_template(template_type: str, manifest: dict) -> bool:
    if template_type in GROK_VISUAL_LED_NO_VOICE_TEMPLATE_TYPES:
        return True
    production_context = manifest.get("productionContext")
    if isinstance(production_context, dict):
        family = str(production_context.get("family") or "").strip().lower().replace("_", "-")
        if family in {"authentic-vlog", "persona-story", "kculture-fandom", "live-recap"}:
            return True
    return False


def _has_explicit_grok_voiceover(scene: dict) -> bool:
    for key in ("voiceover", "voiceOver", "voice_over", "ownedVoiceover", "owned_voiceover"):
        if str(scene.get(key) or "").strip():
            return True
    return False


def _apply_grok_visual_led_no_voice_defaults(draft: dict) -> None:
    if _has_explicit_grok_voiceover(draft):
        return
    draft["narration"] = ""
    draft["narrationText"] = ""
    draft["audio_design_mode"] = "no-voice"
    draft["audioDesignMode"] = "no-voice"
    draft.setdefault(
        "audio_mix_review_note",
        "No-voice Grok-first edit: use selected free BGM/native ambience under the Grok MP4; do not synthesize explanatory TTS.",
    )
    draft.setdefault("audioMixReviewNote", draft["audio_mix_review_note"])


def init_grok_routes(bridge_host: str, bridge_port: int, project_root: Path, safe_resolve) -> None:
    global _bridge_host, _bridge_port, _project_root, _safe_resolve
    _bridge_host = bridge_host
    _bridge_port = bridge_port
    _project_root = project_root
    _safe_resolve = safe_resolve


def _handoff_base_dir() -> Path:
    return _project_root / "storage" / "grok-handoffs"


def _safe_project_id(value: object) -> str:
    candidate = slugify(str(value or "").strip())
    return candidate or f"grok-handoff-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _scene_id(item: dict, index: int) -> str:
    raw = str(item.get("sceneId") or item.get("scene_id") or "").strip()
    if raw:
        return slugify(raw)
    try:
        scene_num = int(item.get("scene_num", index + 1))
    except (TypeError, ValueError):
        scene_num = index + 1
    return f"scene-{scene_num:02d}"


def _short_text(value: object, fallback: str = "", limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return fallback
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _strip_prompt_orphan_tail(value: str) -> str:
    return re.sub(r"(?:[,;]\s*)?\b(?:no|without|avoid)\.?$", "", value, flags=re.IGNORECASE).rstrip(" ,;:-.")


def _prompt_excerpt(value: object, fallback: str = "", limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return fallback
    if len(text) <= limit:
        return text.rstrip(" .")
    cut = text[:limit].rsplit(" ", 1)[0].strip(" ,;:-.")
    cut = _strip_prompt_orphan_tail(cut)
    return cut or text[:limit].strip(" ,;:-.")


def _prompt_hard_limit(value: object, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].strip(" ,;:-.")
    return _strip_prompt_orphan_tail(cut)


def _grok_prompt_meta_terms(value: object) -> list[str]:
    """Detect production/meta instructions that should not seed Grok footage."""
    lowered = str(value or "").strip().lower()
    if not lowered:
        return []
    compact = re.sub(r"\s+", "", lowered)
    hits: list[str] = []
    for term in GROK_PROMPT_META_HARD_TERMS:
        if term in lowered:
            hits.append(term)
    for term in GROK_PROMPT_META_COMPACT_PHRASES:
        if term in compact and term not in hits:
            hits.append(term)
    return hits


def _scene_prompt_seed(item: dict) -> tuple[str, list[str]]:
    """Choose visual action text for Grok while surfacing meta narration leakage."""
    first_meta_text = ""
    first_meta_terms: list[str] = []
    for key in (
        "grok_prompt",
        "image_prompt",
        "visual_prompt",
        "shot_description",
        "title",
        "display_text",
        "narration",
        "narrationText",
        "subtitleText",
    ):
        text = _prompt_excerpt(item.get(key), limit=360)
        if not text:
            continue
        meta_terms = _grok_prompt_meta_terms(text)
        if not meta_terms:
            return text, []
        if not first_meta_text:
            first_meta_text = text
            first_meta_terms = meta_terms
    if first_meta_text:
        return "scene-specific visible action needed: show one concrete subject, place, prop, and camera move", first_meta_terms
    return "cinematic short-form scene with one concrete visible action", []


def _scene_beat_label(item: dict) -> str:
    seed, _ = _scene_prompt_seed(item)
    return _prompt_excerpt(seed or "scene beat", limit=90)


def _prompt_join(parts: list[object], *, max_chars: int = 1500) -> str:
    selected: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = re.sub(r"\s+", " ", str(part or "").strip())
        if not text:
            continue
        normalized = re.sub(r"[^a-z0-9가-힣]+", "", text.lower())
        if normalized in seen:
            continue
        candidate = text if text.endswith((".", "!", "?")) else f"{text}."
        joined = " ".join([*selected, candidate]).strip()
        if selected and len(joined) > max_chars:
            continue
        selected.append(candidate)
        seen.add(normalized)
    return " ".join(selected).strip()


def _scene_source_text(item: dict) -> str:
    seed, _ = _scene_prompt_seed(item)
    return _short_text(seed, limit=220)


def _grok_target_selection(draft_scenes: list[dict], source_mix_total_scenes: int, grok_main_required: bool) -> tuple[list[dict], dict]:
    explicit_targets: list[dict] = [
        item
        for item in draft_scenes
        if str(item.get("image_source") or "").strip() == "grok"
    ]
    min_required = _min_grok_main_scene_count(source_mix_total_scenes)
    target_scenes = list(explicit_targets)
    first_hook_scene_id = _scene_id(draft_scenes[0], 0) if draft_scenes else ""
    explicit_ids = {
        _scene_id(item, index)
        for index, item in enumerate(draft_scenes)
        if str(item.get("image_source") or "").strip() == "grok"
    }
    auto_expanded_ids: list[str] = []
    first_hook_auto_included = False

    if not target_scenes:
        target_scenes = list(draft_scenes)
        mode = "all-scenes-default"
    else:
        mode = "explicit-grok-scenes"
        if grok_main_required and first_hook_scene_id and first_hook_scene_id not in explicit_ids:
            expanded_first = dict(draft_scenes[0])
            expanded_first["image_source"] = "grok"
            expanded_first["grok_auto_expanded"] = True
            expanded_first["grok_first_hook_required"] = True
            expanded_first["original_image_source"] = draft_scenes[0].get("image_source") or ""
            target_scenes.insert(0, expanded_first)
            auto_expanded_ids.append(first_hook_scene_id)
            first_hook_auto_included = True
            mode = "explicit-plus-first-hook"
        if grok_main_required and len(target_scenes) < min_required:
            mode = "explicit-plus-first-hook-main-source-expansion" if first_hook_auto_included else "explicit-plus-main-source-expansion"
            for index, item in enumerate(draft_scenes):
                scene_id = _scene_id(item, index)
                if scene_id in explicit_ids or scene_id in auto_expanded_ids:
                    continue
                expanded = dict(item)
                expanded["image_source"] = "grok"
                expanded["grok_auto_expanded"] = True
                expanded["original_image_source"] = item.get("image_source") or ""
                target_scenes.append(expanded)
                auto_expanded_ids.append(scene_id)
                if len(target_scenes) >= min_required:
                    break

    target_ids = [
        _scene_id(item, index)
        for index, item in enumerate(target_scenes)
    ]
    return target_scenes, {
        "mode": mode,
        "grokMainSourceRequired": grok_main_required,
        "sourceMixTotalScenes": source_mix_total_scenes,
        "minGrokMainScenes": min_required,
        "explicitGrokSceneIds": sorted(explicit_ids),
        "autoExpandedSceneIds": auto_expanded_ids,
        "firstHookRequired": grok_main_required and bool(first_hook_scene_id),
        "firstHookSceneId": first_hook_scene_id,
        "firstHookAutoIncluded": first_hook_auto_included,
        "targetSceneIds": target_ids,
        "detail": (
            "Grok-main handoff auto-includes the first hook scene and expands non-Grok draft scenes "
            "until the minimum hero-source floor is reachable."
            if auto_expanded_ids
            else "Grok handoff uses the explicit Grok scene targets from the draft."
        ),
    }


def _production_profile(value: object, *, target_duration: object = "", tone: object = "", lang: object = "") -> dict:
    template_type = str(value or "news_explainer").strip() or "news_explainer"
    target = str(target_duration or "shorts").strip() or "shorts"
    normalized = template_type.lower().replace("-", "_")
    profiles = {
        "ranking_list": {
            "family": "ranking-or-list",
            "narrativeShape": "fast ranking with one concrete visual proof per rank",
            "hookFormula": "rank or result visible in the first second, then one motion beat",
            "layoutPlan": "stable rank chip near top-left plus lower-info caption only when useful",
            "captionPlan": "avoid center walls of text; use short rank labels and safe-zone lower facts",
            "cameraPlan": "repeat the same motion grammar for each rank so the edit feels intentional",
            "editRhythm": "3-5 second clips, no random micro-cuts inside a generated clip",
        },
        "tutorial_steps": {
            "family": "tutorial-or-process",
            "narrativeShape": "visible step action, then result",
            "hookFormula": "hands/action already moving in frame one",
            "layoutPlan": "top step label and lower-info detail, never covering hands or tools",
            "captionPlan": "captions explain the step, not the production intent",
            "cameraPlan": "locked or slow push on the action, no ornamental b-roll",
            "editRhythm": "one step per clip with a clean cut point",
        },
        "origin_story": {
            "family": "story-or-character",
            "narrativeShape": "specific character/place change across beats",
            "hookFormula": "character action or object reveal in the first second",
            "layoutPlan": "scene 1 top hook; later clips lower-info or no caption",
            "captionPlan": "minimal story beats, no oversized generic center captions",
            "cameraPlan": "consistent handheld or cinematic drift around the same subject",
            "editRhythm": "4-6 second clips with continuity of character, prop, and palette",
        },
        "authentic_vlog": {
            "family": "authentic-vlog",
            "narrativeShape": "phone-camera observational moment with a specific action",
            "hookFormula": "real motion starts immediately, not a static establishing shot",
            "layoutPlan": "full-frame motion, caption-safe lower third left open",
            "captionPlan": "no caption or compact lower-info only",
            "cameraPlan": "natural phone-camera realism, slight handheld drift, no glossy ad look",
            "editRhythm": "let the clip breathe for 4-6 seconds; avoid jumpy fake montage",
        },
        "podcast_clip": {
            "family": "talk-or-commentary",
            "narrativeShape": "speaker/listening reaction plus visual proof cutaway",
            "hookFormula": "speaker expression or proof object appears immediately",
            "layoutPlan": "speaker crop/chapter card with lower captions only when needed",
            "captionPlan": "small lower captions; avoid Shorts-style huge center subtitles",
            "cameraPlan": "stable crop or slow push, keep face and hands unobscured",
            "editRhythm": "longer hold, fewer cuts, chapter transitions instead of random effects",
        },
        "longform_deep_dive": {
            "family": "longform-explainer",
            "narrativeShape": "chaptered evidence, not a Shorts punchline loop",
            "hookFormula": "first clip establishes the question visually, then chapters unfold",
            "layoutPlan": "chapter/title card rhythm plus lower facts",
            "captionPlan": "chapter labels and necessary lower explanations only",
            "cameraPlan": "consistent documentary b-roll, restrained movement",
            "editRhythm": "slower clips with purposeful transitions and room for narration",
        },
    }
    if normalized in {"kculture_fandom", "live_recap"}:
        base = {
            "family": "fandom-or-live-recap",
            "narrativeShape": "recognizable fan/community moment with proof-like detail",
            "hookFormula": "crowd/object/reaction motion visible in the first second",
            "layoutPlan": "beat-friendly cuts and small safe-zone callouts",
            "captionPlan": "short reaction or context captions; avoid covering faces",
            "cameraPlan": "consistent event camera or phone-camera language",
            "editRhythm": "motion-led beats, no unrelated stock-looking filler",
        }
    else:
        base = profiles.get(normalized, {
            "family": "news-or-explainer",
            "narrativeShape": "hook, concrete evidence, implication",
            "hookFormula": "visual evidence appears in the first second",
            "layoutPlan": "top hook for scene one, lower-info facts for later scenes",
            "captionPlan": "captions carry information, not decoration; avoid center text blocks",
            "cameraPlan": "restrained documentary motion with one clear subject per clip",
            "editRhythm": "3-6 second clips with deliberate cut points",
        })
    return {
        "templateType": template_type,
        "targetDuration": target,
        "tone": str(tone or ""),
        "language": str(lang or ""),
        **base,
    }


def _build_shot_bible(draft_scenes: list[dict], source_prompt: object = "", production_context: dict | None = None) -> dict:
    production_context = production_context if isinstance(production_context, dict) else {}
    production_profile = _production_profile(
        production_context.get("templateType") or production_context.get("template_type"),
        target_duration=production_context.get("targetDuration") or production_context.get("target_duration"),
        tone=production_context.get("tone"),
        lang=production_context.get("lang"),
    )
    target_scenes = [
        item for item in draft_scenes
        if str(item.get("image_source") or "").strip() == "grok"
    ] or list(draft_scenes)
    first_scene = target_scenes[0] if target_scenes else {}
    continuity_notes = [
        _short_text(item.get("continuity_note"), limit=140)
        for item in target_scenes
        if _short_text(item.get("continuity_note"), limit=140)
    ]
    anchor = _short_text(source_prompt, limit=220) or _scene_source_text(first_scene)
    continuity_hint = "; ".join(continuity_notes[:3]) if continuity_notes else anchor
    scene_intents = [
        {
            "sceneId": _scene_id(item, index),
            "intent": _scene_source_text(item),
        }
        for index, item in enumerate(target_scenes)
    ]
    shot_locks: list[dict] = []
    for index, item in enumerate(target_scenes):
        scene_id = _scene_id(item, index)
        visible_action = _scene_source_text(item)
        first_second_motion = (
            _short_text(item.get("hook_note"), limit=130)
            or production_profile["hookFormula"]
        )
        continuity_detail = (
            _short_text(item.get("continuity_note"), limit=150)
            or continuity_hint
        )
        caption_preset = _short_text(item.get("caption_preset"), fallback="template-safe caption", limit=48)
        layout_note = _short_text(item.get("layout_variant_note"), limit=130)
        layout_lock = "; ".join(
            part for part in [
                f"later {caption_preset}",
                layout_note,
                "keep lower-third and right-side Shorts UI zones clean",
            ]
            if part
        )
        shot_locks.append({
            "sceneId": scene_id,
            "viewerResult": "Viewer understands the scene visually without narration about the production intent.",
            "actionLock": visible_action,
            "firstSecondMotionLock": first_second_motion,
            "identityLock": f"Same recurring subject/key prop/location as project anchor: {anchor}; {continuity_detail}",
            "cameraLock": production_profile["cameraPlan"],
            "layoutLock": layout_lock,
            "rejectIf": [
                "generic stock b-roll that only resembles the topic",
                "static poster or still image with fake zoom only",
                "random montage, glossy ad insert, or unrelated AI transition",
                "subject, prop, location, palette, or camera continuity drifts from this lock",
                "baked-in captions, readable text, watermark, logo, or UI overlay",
            ],
        })
    return {
        "visualContinuity": "Treat every clip as part of one edited film, not separate generations.",
        "subjectContinuity": f"Keep the same recurring subject, key prop, and scale from shot to shot: {anchor}",
        "locationContinuity": f"Keep one coherent location and production design across clips: {continuity_hint}",
        "palette": "Use one color grade and lighting direction across all clips; avoid random style, era, or weather changes.",
        "cameraLanguage": "Use restrained cinematic motion: one slow push, drift, pan, or locked macro move per clip; avoid chaotic zooms or random cuts inside a clip.",
        "productionProfile": production_profile,
        "layoutPlan": production_profile["layoutPlan"],
        "cinematicQualityFloor": (
            "Every Grok MP4 must feel like intentional raw footage selected for this exact scene: "
            "scene-specific visible action in the first two seconds, stable subject/prop/location/palette/camera, "
            "and no generic stock, glossy ad, or AI montage filler."
        ),
        "antiSlopDirectives": [
            "No generic stock b-roll or pretty filler merely related to the topic.",
            "No static portrait, poster, or product still with fake zoom only.",
            "No random montage/cutaway inside a 4-6s scene unless the template explicitly requires montage.",
            "No glossy ad-packshot or influencer reveal unless the scene action requires it.",
            "No over-smoothed AI camera drift, flicker, face/object morphing, or style jump.",
        ],
        "shotLocks": shot_locks,
        "captionSafePlan": (
            "Leave caption-safe lower third and right-side Shorts UI danger zone clean enough for Video Studio captions. "
            "Do not put the main face, hands, product, or key object in the lower 20% unless the scene is intentionally no-caption."
        ),
        "motionPlan": (
            f"{production_profile['hookFormula']}; {production_profile['cameraPlan']}; "
            "the first frame cannot be a static poster."
        ),
        "editRhythm": production_profile["editRhythm"],
        "negativePrompts": [
            "no captions",
            "no logos",
            "no watermark",
            "no baked-in text",
            "no explanatory title card",
            "no UI overlay",
            "no flicker",
            "no morphing faces or objects",
            "no random extra characters",
            "no unrelated stock-looking insert",
            "no ad-like product packshot unless the scene explicitly requires it",
        ],
        "promptAnchor": (
            "Continuity bible: same recurring subject/prop/location/palette/camera language across every scene; "
            "one clean 4-6s vertical 9:16 MP4 per scene; visible motion in the first second; "
            "leave lower-third/right-side caption safe space; no text, no logos, no watermark, no flicker, no morphing, no unrelated cutaways."
        ),
        "grokPromptRules": [
            "Describe the exact visible action, location, subject, prop, camera move, palette, and first-second motion.",
            "Never ask Grok to explain the video's intent or add text; Video Studio handles captions, BGM, TTS, and layout after import.",
            "Keep generated clips as raw footage with no baked-in captions, logos, watermarks, UI, or title cards.",
            "Prefer one continuous shot per scene; avoid asking for montage unless the template profile explicitly needs it.",
            "Preserve caption-safe framing so subtitles can be placed later without covering the subject.",
        ],
        "reviewChecklist": [
            "First frame and first two seconds clearly match the scene intent.",
            "Subject, key prop, location, palette, and camera language match the other clips.",
            "Clip contains real motion, not a still image with fake zoom only.",
            "Frame leaves usable lower/right safe-zone space for Video Studio captions.",
            "No captions, logos, watermark, UI, or baked-in text.",
            "No obvious AI artifacts: morphing, flicker, melted hands/faces, warped object continuity.",
            "Clip does not look like generic stock b-roll unrelated to the scene intent.",
            "The clip can cut naturally into the previous and next scene.",
        ],
        "hardRejectChecklist": [
            "static image with Ken Burns-like movement only",
            "generic stock b-roll that only resembles the topic",
            "unrelated stock-looking cutaway",
            "glossy ad-style montage or unrelated AI transition",
            "over-smoothed AI drift with no readable scene action",
            "center text/title burned into the clip",
            "subject covers caption danger zones without a no-caption plan",
            "face, hand, object, or scene continuity changes from the shot bible",
        ],
        "sceneIntents": scene_intents,
    }


def _scene_shot_lock(shot_bible: dict | None, scene_id: str) -> dict:
    if not isinstance(shot_bible, dict):
        return {}
    locks = shot_bible.get("shotLocks")
    if not isinstance(locks, list):
        return {}
    for item in locks:
        if isinstance(item, dict) and str(item.get("sceneId") or "") == scene_id:
            return item
    return {}


def _format_scene_shot_lock_text(shot_lock: dict) -> str:
    if not isinstance(shot_lock, dict) or not shot_lock:
        return ""
    rows = [
        ("Action", _prompt_excerpt(shot_lock.get("actionLock"), limit=190)),
        ("First-second motion", _prompt_excerpt(shot_lock.get("firstSecondMotionLock"), limit=150)),
        ("Identity", _prompt_excerpt(shot_lock.get("identityLock"), limit=220)),
        ("Camera", _prompt_excerpt(shot_lock.get("cameraLock"), limit=150)),
        ("Layout", _prompt_excerpt(shot_lock.get("layoutLock"), limit=170)),
    ]
    return "\n".join(f"- {label}: {value}" for label, value in rows if value)


def _shot_lock_prompt_lines(shot_bible: dict | None, scene_id: str) -> list[str]:
    shot_lock = _scene_shot_lock(shot_bible, scene_id)
    if not shot_lock:
        return []
    shot_lock_text = "; ".join(
        part for part in [
            "same recurring subject",
            f"action={_prompt_excerpt(shot_lock.get('actionLock'), limit=80)}",
            f"first={_prompt_excerpt(shot_lock.get('firstSecondMotionLock'), limit=42)}",
            f"cam={_prompt_excerpt(shot_lock.get('cameraLock'), limit=52)}",
            f"layout={_prompt_excerpt(shot_lock.get('layoutLock'), limit=46)}",
        ]
        if part and not part.endswith("=")
    )
    lines = [
        f"Shot lock: {shot_lock_text}; Reject generic stock/ad/AI montage look",
    ]
    return lines


def _request_production_context(data: dict) -> dict:
    nested = data.get("productionContext")
    if not isinstance(nested, dict):
        nested = data.get("production_context")
    if not isinstance(nested, dict):
        nested = {}
    return {
        "templateType": (
            data.get("templateType")
            or data.get("template_type")
            or nested.get("templateType")
            or nested.get("template_type")
        ),
        "targetDuration": (
            data.get("targetDuration")
            or data.get("target_duration")
            or nested.get("targetDuration")
            or nested.get("target_duration")
        ),
        "tone": data.get("tone") or nested.get("tone"),
        "lang": data.get("lang") or data.get("language") or nested.get("lang") or nested.get("language"),
        "subtitleStyle": (
            data.get("subtitleStyle")
            or data.get("subtitle_style")
            or nested.get("subtitleStyle")
            or nested.get("subtitle_style")
        ),
    }


def _scene_operator_checklist(scene_id: str, shot_bible: dict) -> list[str]:
    production_profile = shot_bible.get("productionProfile") if isinstance(shot_bible.get("productionProfile"), dict) else {}
    family = str(production_profile.get("family") or "template")
    return [
        f"{scene_id} begins with visible motion in the first 2 seconds.",
        "Matches the shot bible subject, location, palette, and camera language.",
        f"Matches the selected production family ({family}) instead of generic stock footage.",
        "Leaves lower-third and right-side safe zones usable for Video Studio captions/layout.",
        "No baked-in text, watermark, logo, UI overlay, or unrelated insert.",
        "Operator can explain why this exact MP4 was selected for the scene.",
    ]


def _grok_first_layout_default(scene_index: int, caption_preset: str) -> dict:
    """Choose a viewer-facing Grok MP4 layout, not an internal production label."""
    if scene_index == 0 or caption_preset == "top-hook":
        return {
            "key": "grok-first-hook",
            "label": "Grok-first hook",
            "note": "First 1.25s top hook, then a short lower beat only if it clarifies the motion; no center caption wall.",
        }
    if caption_preset == "center-short":
        return {
            "key": "grok-first-proof",
            "label": "Grok-first proof beat",
            "note": "Compact proof chip plus restrained lower beat so generated motion remains the hero.",
        }
    return {
        "key": "grok-first-continuity",
        "label": "Grok-first continuity beat",
        "note": "Top-safe scene beat plus short lower info; preserve face/hands/prop visibility and right-side Shorts UI.",
    }


def _scene_prompt_context(item: dict, index: int = 0, all_scenes: list[dict] | None = None) -> list[str]:
    all_scenes = all_scenes or []
    context: list[str] = []
    hook_note = _prompt_excerpt(item.get("hook_note"), limit=130)
    continuity_note = _prompt_excerpt(item.get("continuity_note"), limit=150)
    layout_label = _prompt_excerpt(item.get("layout_variant_label"), limit=80)
    layout_note = _prompt_excerpt(item.get("layout_variant_note"), limit=140)
    caption_preset = _prompt_excerpt(item.get("caption_preset"), limit=50)
    neighbors: list[str] = []
    if index > 0 and index - 1 < len(all_scenes):
        neighbors.append(f"previous beat '{_scene_beat_label(all_scenes[index - 1])}'")
    if index + 1 < len(all_scenes):
        neighbors.append(f"next beat '{_scene_beat_label(all_scenes[index + 1])}'")
    if neighbors:
        context.append(f"Edit continuity: {'; '.join(neighbors)}")
    if hook_note:
        context.append(f"First-second motion: {hook_note}")
    if caption_preset:
        context.append(f"Leave clean space for a later {caption_preset} caption; do not bake text into the clip.")
    if continuity_note:
        context.append(f"Continuity detail: {continuity_note}")
    if layout_label or layout_note:
        context.append(f"Composition note: {layout_label} {layout_note}".strip())
    return context


def _scene_prompt(item: dict, shot_bible: dict | None = None, index: int = 0, all_scenes: list[dict] | None = None) -> str:
    prompt, prompt_meta_terms = _scene_prompt_seed(item)
    scene_id = _scene_id(item, index)
    scene_context = _scene_prompt_context(item, index, all_scenes)
    production_profile = {}
    if isinstance(shot_bible, dict) and isinstance(shot_bible.get("productionProfile"), dict):
        production_profile = shot_bible["productionProfile"]
    suffix = [
        "raw footage for editing, not a finished social video; vertical 9:16 MP4, 4-6s continuous shot, visible motion first second.",
        "Keep the lower third and right edge caption-safe.",
        "No captions, no logos, no watermark, no UI, no text, no title cards, no narration, no unrelated cutaways.",
    ]
    if prompt_meta_terms:
        suffix.append(
            "Rewrite required before generation: replace production-meta wording with a concrete visible subject, action, place, prop, and camera move."
        )
    if shot_bible:
        suffix.append(f"Template family: {production_profile.get('family') or 'news-or-explainer'}.")
        if scene_context:
            suffix.extend(scene_context[:1])
        suffix.extend(_shot_lock_prompt_lines(shot_bible, scene_id))
        if scene_context:
            suffix.extend(scene_context[1:3])
        suffix.extend([
            "Continuity: same recurring subject, prop, location, palette, and camera.",
            f"Camera: {_prompt_excerpt(production_profile.get('cameraPlan') or 'restrained documentary movement', limit=64)}.",
        ])
    if scene_context:
        suffix.extend(scene_context[3:] if shot_bible else scene_context)
    if shot_bible:
        suffix.append(
            f"Layout: {_prompt_excerpt(shot_bible.get('layoutPlan') or production_profile.get('layoutPlan') or 'safe-zone lower captions only', limit=72)}."
        )
    return _prompt_join([prompt, *suffix], max_chars=1050)


def _scene_prompt_quality(prompt: str, scene: dict, shot_bible: dict | None = None) -> dict:
    text = str(prompt or "")
    lowered = text.lower()
    source_text, source_meta_terms = _scene_prompt_seed(scene)
    source_lowered = source_text.lower()
    source_words = re.findall(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣'-]*", source_text)
    source_word_count = len(source_words)
    source_action_terms = (
        r"\b(stands?|walks?|steps?|step(?:s|ping)? out|turns?|opens?|closes?|pours?|pouring|holds?|"
        r"reaches?|looks?|passes?|tightens?|loosens?|twists?|untwists?|"
        r"moves?|slides?|reveals?|rises?|rising|steams?|steaming|exhales?|runs?|drifts?|push(?:es|ing)?|"
        r"pans?|tilts?|handheld|motion|enters?|leaves?|lifts?|places?|types?|writes?|points?|"
        r"cuts?|stirs?|serves?|records?|films?|zooms?)\b"
    )
    korean_action_terms = (
        "걷", "돌", "열", "닫", "붓", "따르", "잡", "들", "놓", "밀", "당기", "움직",
        "드러", "비추", "보여", "흔들", "들어오", "나가", "타이핑", "기록", "촬영",
    )
    source_has_action = bool(re.search(source_action_terms, source_lowered)) or any(
        token in source_text for token in korean_action_terms
    )
    generic_source = source_word_count < 5 or source_lowered.strip(" .,!?:;") in {
        "hero",
        "first hero",
        "second hero",
        "cinematic hero",
        "cinematic coffee steam hero",
        "scene prompt",
        "product reveal",
        "cinematic product reveal",
    }
    requires_shot_lock = isinstance(shot_bible, dict) and bool(shot_bible.get("shotLocks"))
    checks = {
        "sceneSpecificIntent": not generic_source,
        "sourceActionCue": source_has_action,
        "specificAction": source_has_action,
        "verticalMp4": "9:16" in lowered and "mp4" in lowered,
        "firstSecondMotion": "first second" in lowered or "first 2" in lowered or "first two" in lowered,
        "captionSafe": "caption" in lowered and ("lower" in lowered or "right" in lowered or "safe" in lowered),
        "continuity": "continuity" in lowered or "same recurring" in lowered or "consistent subject" in lowered,
        "negativeText": all(token in lowered for token in ("no captions", "no logos", "no watermark")),
        "rawFootage": "raw footage" in lowered or "not a finished social video" in lowered,
        "templateAware": "template family" in lowered or "narrative shape" in lowered,
        "visualSeedNotMeta": not source_meta_terms,
        "shotLock": (not requires_shot_lock) or "shot lock" in lowered,
        "antiSlop": (not requires_shot_lock) or (
            "anti-slop" in lowered
            or "reject generic stock" in lowered
            or "generic stock/ad/ai montage" in lowered
        ),
    }
    weak_source = generic_source or not source_has_action or bool(source_meta_terms)
    missing = [name for name, ok in checks.items() if not ok]
    score = max(0, 100 - len(missing) * 8 - (12 if weak_source else 0))
    return {
        "score": score,
        "status": "ready" if score >= 85 and not missing and not weak_source else "needs-rewrite",
        "missing": missing,
        "weakSourcePrompt": weak_source,
        "productionMetaTerms": source_meta_terms,
        "sourceWordCount": source_word_count,
        "sourcePrompt": source_text,
        "checks": checks,
        "qualityFloor": (
            "Prompt source must name a scene-specific visible action before the shared production suffix. "
            "The packaged prompt must also define first-second motion, continuity, caption-safe framing, "
            "negative text/logo/watermark constraints, and a template-aware layout role. "
            "Production-intent, TTS, caption, layout, or checklist notes cannot be used as the visual seed."
        ),
        "operatorAction": (
            "Rewrite the scene Grok prompt with concrete subject + visible action + place/prop/camera cue "
            "and remove production-intent/TTS/caption meta wording "
            "before generating in Grok."
            if weak_source or missing
            else "Prompt is specific enough for Grok handoff; still reject weak MP4 output in the review packet."
        ),
    }


def _scene_take_prompts(scene: dict, source_scene: dict | None = None, shot_bible: dict | None = None) -> list[dict]:
    """Build deliberate Grok generation takes so operators can curate real MP4 candidates."""
    base_prompt = str(scene.get("prompt") or "").strip()
    scene_id = str(scene.get("sceneId") or "scene")
    source = source_scene if isinstance(source_scene, dict) else scene
    production_profile = {}
    if isinstance(shot_bible, dict) and isinstance(shot_bible.get("productionProfile"), dict):
        production_profile = shot_bible["productionProfile"]
    family = str(production_profile.get("family") or "short-form").strip() or "short-form"
    continuity_anchor = ""
    if isinstance(shot_bible, dict):
        continuity_anchor = _prompt_excerpt(shot_bible.get("promptAnchor"), limit=180)
    shot_lock_context = _prompt_hard_limit(" ".join(_shot_lock_prompt_lines(shot_bible, scene_id)), 520)
    specs = [
        {
            "takeNumber": 1,
            "label": "continuity-master",
            "focus": "Cleanest continuity take: use the exact scene action, subject, prop, location, palette, and camera language from the shot bible.",
        },
        {
            "takeNumber": 2,
            "label": "motion-first",
            "focus": "Alternate take focused on first-second motion: make the subject, prop, light, hand, or camera movement readable immediately without adding extra cuts.",
        },
        {
            "takeNumber": 3,
            "label": "caption-safe-composition",
            "focus": "Alternate take focused on layout: keep the important face, hands, prop, and motion above the lower third and away from the right-side Shorts UI danger zone.",
        },
    ]
    takes: list[dict] = []
    for spec in specs:
        take_number = int(spec["takeNumber"])
        if take_number == 1:
            prompt = base_prompt
        else:
            prompt = _prompt_join([
                base_prompt,
                f"Take {take_number} focus ({spec['label']}): {spec['focus']}",
                f"Keep the {family} template family and the same story beat; vary emphasis only.",
                continuity_anchor,
            ], max_chars=1240)
        takes.append({
            "takeNumber": take_number,
            "label": spec["label"],
            "focus": spec["focus"],
            "prompt": prompt,
            "promptQuality": _scene_prompt_quality(prompt, source, shot_bible),
        })
    return takes


def _select_take_prompt(scene: dict, take_number: object = None) -> dict | None:
    takes = scene.get("takePrompts") if isinstance(scene.get("takePrompts"), list) else []
    normalized_take = _normalize_take_number(take_number)
    for item in takes:
        if isinstance(item, dict) and _normalize_take_number(item.get("takeNumber")) == normalized_take:
            return item
    for item in takes:
        if isinstance(item, dict) and _normalize_take_number(item.get("takeNumber")) == 1:
            return item
    return takes[0] if takes and isinstance(takes[0], dict) else None


def _scene_review_decision(manifest: dict, scene_id: str) -> dict:
    review_decisions = manifest.get("reviewDecisions") if isinstance(manifest.get("reviewDecisions"), dict) else {}
    decision = review_decisions.get(scene_id)
    return decision if isinstance(decision, dict) else {}


def _scene_retry_attempt(decision: dict) -> int:
    if decision.get("accepted") is not False:
        return 1
    try:
        return max(2, int(decision.get("retryAttempt") or 2))
    except (TypeError, ValueError):
        return 2


def _scene_rejection_summary(decision: dict) -> str:
    issues: list[str] = []
    if decision.get("firstTwoSecondHook") is not True:
        issues.append("first two seconds did not prove a usable hook")
    if decision.get("artifactFree") is not True:
        issues.append("artifact/watermark/text/flicker risk was not cleared")
    if decision.get("continuityOk") is not True:
        issues.append("subject, prop, location, palette, or camera continuity drifted")
    if decision.get("captionSafe") is not True:
        issues.append("main subject may collide with caption-safe layout")
    for key in ("qualityReviewNote", "operatorNote"):
        note = _short_text(decision.get(key), limit=220)
        if note:
            issues.append(note)
    return "; ".join(dict.fromkeys(issues)) or "operator rejected the previous Grok clip"


def _scene_retry_prompt(scene: dict, shot_bible: dict | None, decision: dict) -> str:
    scene_id = str(scene.get("sceneId") or "scene")
    base_prompt = str(scene.get("prompt") or "").strip()
    attempt = _scene_retry_attempt(decision)
    rejection_summary = _scene_rejection_summary(decision)
    continuity_anchor = ""
    negative_prompts = ""
    if isinstance(shot_bible, dict):
        continuity_anchor = _short_text(shot_bible.get("promptAnchor"), limit=260)
        negative_prompts = ", ".join(str(item) for item in shot_bible.get("negativePrompts") or [])
    shot_lock_lines = _shot_lock_prompt_lines(shot_bible, scene_id)
    parts = [
        f"Regenerate attempt {attempt} for {scene_id}.",
        "Use the same scene intent, but fix the rejected Grok clip instead of repeating the same composition.",
        f"Original scene prompt: {base_prompt}",
        f"Rejected because: {rejection_summary}.",
        *shot_lock_lines,
        "Output one continuous 4-6 second vertical 9:16 MP4 with visible motion in the first two seconds.",
        "Keep the subject, key prop, location, lighting, palette, and camera language consistent with the other clips.",
        "Leave caption-safe space; do not place the main subject across the lower third or right-side Shorts UI danger zone.",
        "No captions, no logos, no watermark, no baked-in text, no UI, no flicker, no morphing, no random extra subjects.",
        "If the previous attempt looked static, generic, stock-like, or unrelated, change the camera move and framing while preserving continuity.",
    ]
    if continuity_anchor:
        parts.append(continuity_anchor)
    if negative_prompts:
        parts.append(f"Negative prompt list: {negative_prompts}.")
    return " ".join(part for part in parts if part)


def _handoff_dir(project_id: str) -> Path:
    return _handoff_base_dir() / _safe_project_id(project_id)


def _manifest_path(project_id: str) -> Path:
    return _handoff_dir(project_id) / "handoff.json"


def _automation_status_path(handoff_dir: Path) -> Path:
    return handoff_dir / "automation-status.json"


def _automation_request_path(handoff_dir: Path) -> Path:
    return handoff_dir / "automation-request.json"


def _automation_job_status_path(handoff_dir: Path) -> Path:
    return handoff_dir / "automation-job-status.json"


def _manual_download_watch_status_path(handoff_dir: Path) -> Path:
    return handoff_dir / "manual-download-watch-status.json"


def _manual_download_watch_cancelled(cancel_event: threading.Event | None) -> bool:
    return bool(cancel_event and cancel_event.is_set())


def _automation_cancel_path(handoff_dir: Path) -> Path:
    return handoff_dir / "automation-cancel.json"


def _load_manifest(project_id: str) -> tuple[Path, dict] | tuple[None, None]:
    handoff_dir = _handoff_dir(project_id)
    manifest_path = handoff_dir / "handoff.json"
    if not manifest_path.exists():
        return None, None
    for attempt in range(3):
        try:
            with _manifest_io_lock:
                return handoff_dir, json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            if attempt < 2:
                time.sleep(0.02)
                continue
            logger.warning("Unreadable Grok handoff manifest: %s", manifest_path)
            return None, None


def _pick_keys(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict):
        return {}
    return {key: value.get(key) for key in keys if key in value}


_AUTH_PROVIDER_ALIASES = {
    "x": "x",
    "twitter": "x",
    "google": "google",
    "email": "email",
    "e-mail": "email",
    "apple": "apple",
    "manual": "manual",
    "none": "manual",
    "": "manual",
}


def _normalize_auth_provider_preference(value: object, *, default: str = "x") -> str:
    key = str(value if value is not None else default).strip().lower()
    return _AUTH_PROVIDER_ALIASES.get(key, _AUTH_PROVIDER_ALIASES.get(default, "x"))


def _sanitize_operator_ready_wait(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    allowed = {
        "ready",
        "timedOut",
        "timeoutSeconds",
        "pollIntervalSeconds",
        "attempts",
        "elapsedSeconds",
        "requiresOperatorAction",
        "authRequired",
        "cookieChoiceRequired",
        "browserBlocker",
        "promptInputReady",
        "generateControlReady",
        "downloadControlReady",
        "operatorAuthStage",
        "operatorAuthStageLabel",
        "operatorNextAction",
        "authProviderPreference",
    }
    status = _pick_keys(value, allowed)
    preflight = _pick_keys(value.get("preflight"), {
        "ok",
        "url",
        "title",
        "authRequired",
        "cookieChoiceRequired",
        "promptInputReady",
        "generateControlReady",
        "downloadControlReady",
        "videoElementCount",
        "candidateLabels",
        "operatorAuthStage",
            "operatorAuthStageLabel",
            "operatorNextAction",
            "authProviderPreference",
        })
    if preflight:
        status["preflight"] = preflight
    for key in ("authKickoff", "authProviderKickoff", "cookieChoice"):
        nested = _pick_keys(value.get(key), {
            "ok",
            "clicked",
            "label",
            "action",
            "url",
            "title",
            "authRequired",
            "cookieChoiceRequired",
            "provider",
        })
        if nested:
            status[key] = nested
    return status


def _build_automation_status(project_id: str, scene: dict, result: dict, error: str | None = None) -> dict:
    allowed = {
        "browserAutomationMode",
        "remoteDebuggingPort",
        "filledSceneId",
        "preflightOnly",
        "promptInjected",
        "submitPromptRequested",
        "generatePromptRequested",
        "generateRequested",
        "generateAction",
        "downloadResultRequested",
        "downloadClickTimeoutSeconds",
        "watchDownloadsRequested",
        "watchTimeoutSeconds",
        "watchPollIntervalSeconds",
        "targetUrl",
        "targetTitle",
        "launched",
        "userDataDir",
        "useDefaultChromeProfile",
        "attachDefaultChromeApproved",
        "browserProfileMode",
        "browserProfileDirectory",
        "authProviderPreference",
        "authRequired",
        "cookieChoiceRequired",
        "browserBlocker",
        "requiresOperatorAction",
        "cancelled",
        "cancelReason",
        "operatorReadyTimedOut",
        "manualDownloadInstruction",
        "operatorNextAction",
        "operatorAuthStage",
        "operatorAuthStageLabel",
        "downloadDir",
        "readyScenes",
        "totalScenes",
        "allReady",
        "timedOut",
        "attempts",
        "elapsedSeconds",
    }
    status = _pick_keys(result, allowed)
    status.update({
        "projectId": project_id,
        "sceneId": scene.get("sceneId"),
        "expectedFileName": scene.get("expectedFileName"),
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    })
    if error:
        status["error"] = error
        status["status"] = "failed"
        status["detail"] = error
    elif result.get("cancelled"):
        status["status"] = "cancelled"
        status["detail"] = result.get("cancelReason") or "Background Grok job was superseded by a fresh operator-approved run."
    elif result.get("operatorReadyTimedOut") or result.get("requiresOperatorAction") or result.get("authRequired") or result.get("cookieChoiceRequired"):
        status["status"] = "needs-operator"
        status["detail"] = result.get("operatorNextAction") or "Complete Grok login/cookie/captcha/payment steps, then rerun approved automation."
    elif result.get("allReady"):
        status["status"] = "imported"
        status["detail"] = "Grok MP4 imported and render payload is ready."
    elif result.get("promptInjected"):
        status["status"] = "injected"
        status["detail"] = "Prompt was injected; generation/download may still need review or a rerun."
    elif result.get("preflightOnly"):
        status["status"] = "preflight"
        status["detail"] = "Browser preflight completed."
    else:
        status["status"] = "pending"
        status["detail"] = "Approved browser automation ran but did not reach prompt injection yet."

    operator_ready_wait = _sanitize_operator_ready_wait(result.get("operatorReadyWait"))
    if operator_ready_wait:
        status["operatorReadyWait"] = operator_ready_wait
    for key in ("preflight", "generateClick", "downloadClick"):
        nested = _pick_keys(result.get(key), {
            "ok",
            "clicked",
            "label",
            "action",
            "reason",
            "url",
            "title",
            "authRequired",
            "cookieChoiceRequired",
            "requiresOperatorAction",
            "browserBlocker",
            "operatorAuthStage",
            "operatorAuthStageLabel",
            "operatorNextAction",
            "authProviderPreference",
            "error",
        })
        if nested:
            status[key] = nested
    if isinstance(result.get("assets"), list):
        status["assets"] = result["assets"]
    if isinstance(result.get("imported"), list):
        status["imported"] = result["imported"]
    if isinstance(result.get("skipped"), list):
        status["skipped"] = result["skipped"]
    return status


def _write_automation_status(handoff_dir: Path, status: dict) -> None:
    _automation_status_path(handoff_dir).write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_automation_status(handoff_dir: Path) -> dict | None:
    path = _automation_status_path(handoff_dir)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable Grok automation status: %s", path)
        return None
    return value if isinstance(value, dict) else None


_AUTOMATION_REPLAY_FIELDS = {
    "sceneId",
    "launchBrowserApproved",
    "preflightOnly",
    "waitForOperatorReadyApproved",
    "authKickoffApproved",
    "authProviderKickoffApproved",
    "authProviderPreference",
    "useDefaultChromeProfile",
    "attachDefaultChromeApproved",
    "browserProfileMode",
    "browserProfileDirectory",
    "cookieRejectApproved",
    "operatorReadyTimeoutSeconds",
    "operatorReadyPollIntervalSeconds",
    "submitPromptApproved",
    "generatePromptApproved",
    "downloadResultApproved",
    "watchDownloadsApproved",
    "allowNewestFallback",
    "overwrite",
    "sinceHandoff",
    "downloadClickTimeoutSeconds",
    "watchTimeoutSeconds",
    "watchPollIntervalSeconds",
    "downloadDir",
    "remoteDebuggingPort",
}

_NATIVE_GROK_DOWNLOAD_PROMPT_BLOCKER = (
    "Chrome/Grok Download/Save/Export automation and Downloads watcher fallback are disabled. "
    "Native download prompts can stall until the operator clicks them; use Companion/pageAssets "
    "direct import or explicit local MP4 upload/import instead."
)


def _automation_replay_request(scene: dict, data: dict, download_dir: Path | None) -> dict:
    request = _pick_keys(data, _AUTOMATION_REPLAY_FIELDS)
    request["projectId"] = str(data.get("projectId") or "")
    request["sceneId"] = str(data.get("sceneId") or scene.get("sceneId") or "")
    request["expectedFileName"] = scene.get("expectedFileName")
    if download_dir is not None:
        request["downloadDir"] = str(download_dir)
    request["operatorApproved"] = False
    request["browserAutomationApproved"] = False
    request["profileApproved"] = False
    request["updatedAt"] = datetime.now().isoformat(timespec="seconds")
    request["note"] = "Replay requires fresh operatorApproved=true and browserAutomationApproved=true; credentials are not stored."
    return request


def _write_automation_request(handoff_dir: Path, request: dict) -> None:
    _automation_request_path(handoff_dir).write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_automation_request(handoff_dir: Path) -> dict | None:
    path = _automation_request_path(handoff_dir)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable Grok automation request: %s", path)
        return None
    return value if isinstance(value, dict) else None


def _write_background_cancel_request(handoff_dir: Path, job_id: str, reason: str) -> dict:
    request = {
        "jobId": str(job_id or ""),
        "reason": _short_text(reason, limit=220),
        "requestedAt": datetime.now().isoformat(timespec="seconds"),
    }
    _automation_cancel_path(handoff_dir).write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return request


def _read_background_cancel_request(handoff_dir: Path) -> dict | None:
    path = _automation_cancel_path(handoff_dir)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable Grok automation cancel request: %s", path)
        return None
    return value if isinstance(value, dict) else None


def _background_job_cancelled(handoff_dir: Path, job_id: str) -> bool:
    request = _read_background_cancel_request(handoff_dir)
    return bool(request and str(request.get("jobId") or "") == str(job_id or ""))


def _automation_replay_summary(request: dict | None) -> dict | None:
    if not request:
        return None
    summary = {
        "sceneId": request.get("sceneId"),
        "expectedFileName": request.get("expectedFileName"),
        "updatedAt": request.get("updatedAt"),
        "downloadDir": request.get("downloadDir"),
        "authKickoffApproved": request.get("authKickoffApproved") is True,
        "authProviderKickoffApproved": request.get("authProviderKickoffApproved") is True,
        "authProviderPreference": _normalize_auth_provider_preference(request.get("authProviderPreference"), default="x"),
        "useDefaultChromeProfile": request.get("useDefaultChromeProfile") is True,
        "attachDefaultChromeApproved": request.get("attachDefaultChromeApproved") is True,
        "browserProfileMode": request.get("browserProfileMode"),
        "browserProfileDirectory": request.get("browserProfileDirectory"),
        "cookieRejectApproved": request.get("cookieRejectApproved") is True,
        "generatePromptApproved": request.get("generatePromptApproved") is True,
        "downloadResultApproved": request.get("downloadResultApproved") is True,
        "watchDownloadsApproved": request.get("watchDownloadsApproved") is True,
        "waitForOperatorReadyApproved": request.get("waitForOperatorReadyApproved") is True,
        "resumeEndpoint": f"/api/grok-handoff/{request.get('projectId')}/resume-automation" if request.get("projectId") else None,
        "requiresFreshApproval": True,
    }
    for key in ("operatorReadyTimeoutSeconds", "operatorReadyPollIntervalSeconds"):
        if request.get(key) is not None:
            summary[key] = request.get(key)
    return summary


def _write_automation_job_status(handoff_dir: Path, status: dict) -> None:
    _automation_job_status_path(handoff_dir).write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_automation_job_status(handoff_dir: Path) -> dict | None:
    path = _automation_job_status_path(handoff_dir)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable Grok automation job status: %s", path)
        return None
    return value if isinstance(value, dict) else None


def _write_manual_download_watch_status(handoff_dir: Path, status: dict) -> None:
    _manual_download_watch_status_path(handoff_dir).write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_manual_download_watch_status(handoff_dir: Path) -> dict | None:
    path = _manual_download_watch_status_path(handoff_dir)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable Grok manual download watch status: %s", path)
        return None
    return value if isinstance(value, dict) else None


def _parse_iso_datetime(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None


def _background_job_liveness(project_key: str | None, summary: dict) -> dict:
    job_status = str(summary.get("status") or "")
    waiting = job_status in {"queued", "running"}
    active_thread = False
    if project_key:
        with _background_automation_lock:
            thread = _background_automation_threads.get(project_key)
            active_thread = bool(thread and thread.is_alive())
            if thread is not None and not active_thread:
                _background_automation_threads.pop(project_key, None)

    fields = {
        "activeThread": active_thread,
        "restartAvailable": waiting and not active_thread,
        "stale": waiting and not active_thread,
    }
    started_at = _parse_iso_datetime(summary.get("startedAt") or summary.get("createdAt"))
    if started_at:
        now = datetime.now(started_at.tzinfo) if started_at.tzinfo else datetime.now()
        elapsed_seconds = max(0.0, (now - started_at).total_seconds())
        fields["elapsedSeconds"] = round(elapsed_seconds, 3)
        replay = summary.get("automationReplay") if isinstance(summary.get("automationReplay"), dict) else {}
        try:
            timeout_seconds = float(replay.get("operatorReadyTimeoutSeconds"))
        except (TypeError, ValueError):
            timeout_seconds = None
        if waiting and timeout_seconds is not None and timeout_seconds >= 0:
            deadline = started_at + timedelta(seconds=timeout_seconds)
            remaining = max(0.0, (deadline - now).total_seconds())
            fields["operatorWaitDeadlineAt"] = deadline.isoformat(timespec="seconds")
            fields["operatorWaitRemainingSeconds"] = round(remaining, 3)
    return fields


def _automation_job_summary(status: dict | None, project_key: str | None = None, replay_request: dict | None = None) -> dict | None:
    if not status:
        return None
    allowed = {
        "jobId",
        "projectId",
        "sceneId",
        "expectedFileName",
        "status",
        "detail",
        "createdAt",
        "startedAt",
        "updatedAt",
        "finishedAt",
        "downloadDir",
        "automationReplay",
        "automationStatus",
        "readyScenes",
        "totalScenes",
        "allReady",
        "browserBlocker",
        "operatorNextAction",
        "error",
    }
    summary = _pick_keys(status, allowed)
    replay_summary = _automation_replay_summary(replay_request)
    if replay_summary:
        current_replay = summary.get("automationReplay") if isinstance(summary.get("automationReplay"), dict) else {}
        summary["automationReplay"] = {**replay_summary, **current_replay}
    if not isinstance(summary.get("automationReplay"), dict):
        summary.pop("automationReplay", None)
    if not isinstance(summary.get("automationStatus"), dict):
        summary.pop("automationStatus", None)
    summary.update(_background_job_liveness(project_key, summary))
    return summary


def _manual_download_watch_liveness(project_key: str | None, summary: dict) -> dict:
    job_status = str(summary.get("status") or "")
    waiting = job_status in {"queued", "running"}
    active_thread = False
    if project_key:
        with _manual_download_watch_lock:
            thread = _manual_download_watch_threads.get(project_key)
            active_thread = bool(thread and thread.is_alive())
            if thread is not None and not active_thread:
                _manual_download_watch_threads.pop(project_key, None)
                _manual_download_watch_cancel_events.pop(project_key, None)

    fields = {
        "activeThread": active_thread,
        "restartAvailable": waiting and not active_thread,
        "stale": waiting and not active_thread,
    }
    started_at = _parse_iso_datetime(summary.get("startedAt") or summary.get("createdAt"))
    if started_at:
        now = datetime.now(started_at.tzinfo) if started_at.tzinfo else datetime.now()
        elapsed_seconds = max(0.0, (now - started_at).total_seconds())
        fields["elapsedSeconds"] = round(elapsed_seconds, 3)
        try:
            timeout_seconds = float(summary.get("timeoutSeconds"))
        except (TypeError, ValueError):
            timeout_seconds = None
        if waiting and timeout_seconds is not None and timeout_seconds >= 0:
            deadline = started_at + timedelta(seconds=timeout_seconds)
            remaining = max(0.0, (deadline - now).total_seconds())
            fields["deadlineAt"] = deadline.isoformat(timespec="seconds")
            fields["remainingSeconds"] = round(remaining, 3)
    return fields


def _manual_download_watch_summary(status: dict | None, project_key: str | None = None) -> dict | None:
    if not status:
        return None
    allowed = {
        "jobId",
        "projectId",
        "sceneId",
        "expectedFileName",
        "status",
        "detail",
        "createdAt",
        "startedAt",
        "updatedAt",
        "finishedAt",
        "downloadDir",
        "downloadDirs",
        "timeoutSeconds",
        "pollIntervalSeconds",
        "allowNewestFallback",
        "sinceHandoff",
        "overwrite",
        "preserveCandidates",
        "stopOnImport",
        "sceneMappingMode",
        "sceneGroupedTakeSize",
        "sceneGroupedTakeTarget",
        "readyScenes",
        "totalScenes",
        "allReady",
        "attempts",
        "elapsedSeconds",
        "importedCount",
        "timedOut",
        "operatorNextAction",
        "error",
    }
    summary = _pick_keys(status, allowed)
    liveness = _manual_download_watch_liveness(project_key, summary)
    summary.update(liveness)
    if liveness.get("stale") is True:
        stored_status = str(summary.get("status") or "")
        summary["storedStatus"] = stored_status
        summary["status"] = "stale"
        summary["operatorNextAction"] = (
            "The previous Grok Downloads watcher is no longer active in this bridge process. "
            "Restart the Grok watch or use batch MP4 upload after downloading the native Grok clips."
        )
    return summary


def _effective_automation_status_for_active_job(automation_status: dict | None, automation_job: dict | None) -> dict | None:
    if not automation_status or not automation_job:
        return automation_status
    if automation_job.get("activeThread") is not True or str(automation_job.get("status") or "") not in {"queued", "running"}:
        return automation_status

    job_started = _parse_iso_datetime(automation_job.get("startedAt") or automation_job.get("createdAt"))
    status_updated = _parse_iso_datetime(automation_status.get("updatedAt"))
    operator_wait = automation_status.get("operatorReadyWait") if isinstance(automation_status.get("operatorReadyWait"), dict) else {}
    stale_timeout = automation_status.get("operatorReadyTimedOut") is True or operator_wait.get("timedOut") is True
    if not stale_timeout or not job_started or not status_updated or status_updated >= job_started:
        return automation_status

    replay = automation_job.get("automationReplay") if isinstance(automation_job.get("automationReplay"), dict) else {}
    effective = dict(automation_status)
    effective.update({
        "status": "waiting-for-operator",
        "detail": automation_job.get("detail") or "Active Grok background job is waiting for operator approval steps.",
        "activeBackgroundWait": True,
        "operatorReadyTimedOut": False,
        "projectId": automation_job.get("projectId") or automation_status.get("projectId"),
        "sceneId": automation_job.get("sceneId") or automation_status.get("sceneId"),
        "expectedFileName": automation_job.get("expectedFileName") or automation_status.get("expectedFileName"),
        "operatorWaitDeadlineAt": automation_job.get("operatorWaitDeadlineAt"),
        "operatorWaitRemainingSeconds": automation_job.get("operatorWaitRemainingSeconds"),
        "operatorNextAction": automation_job.get("operatorNextAction") or "Complete Grok login/captcha/payment/safety steps in the opened browser; the active background job will resume automatically.",
    })
    effective["operatorReadyWait"] = {
        "ready": False,
        "timedOut": False,
        "timeoutSeconds": replay.get("operatorReadyTimeoutSeconds"),
        "pollIntervalSeconds": replay.get("operatorReadyPollIntervalSeconds"),
        "elapsedSeconds": automation_job.get("elapsedSeconds"),
        "requiresOperatorAction": True,
        "activeBackgroundWait": True,
    }
    return effective


def _enrich_stale_automation_status_blocker(automation_status: dict | None, port: object = None) -> dict | None:
    """Backfill operator guidance for older failed status files written before blocker classification existed."""
    if not isinstance(automation_status, dict):
        return automation_status
    if automation_status.get("browserBlocker") or automation_status.get("operatorNextAction"):
        return automation_status
    error_text = str(automation_status.get("error") or automation_status.get("detail") or "")
    if not error_text:
        return automation_status
    try:
        remote_debugging_port = _bounded_int(port, default=9222, minimum=9000, maximum=65535)
    except Exception:
        remote_debugging_port = 9222
    error_state = _automation_error_state(error_text, remote_debugging_port)
    if error_state.get("requiresOperatorAction") is not True:
        return automation_status
    enriched = dict(automation_status)
    enriched.update(error_state)
    return enriched


def _automation_job_status(
    *,
    project_id: str,
    job_id: str,
    scene: dict,
    status: str,
    detail: str,
    download_dir: Path | None,
    replay_request: dict | None,
    created_at: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    result: dict | None = None,
    automation_status: dict | None = None,
    error: str | None = None,
) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    payload = {
        "jobId": job_id,
        "projectId": project_id,
        "sceneId": scene.get("sceneId"),
        "expectedFileName": scene.get("expectedFileName"),
        "status": status,
        "detail": detail,
        "createdAt": created_at,
        "updatedAt": now,
        "downloadDir": str(download_dir) if download_dir is not None else None,
        "automationReplay": _automation_replay_summary(replay_request),
    }
    if started_at:
        payload["startedAt"] = started_at
    if finished_at:
        payload["finishedAt"] = finished_at
    if automation_status:
        payload["automationStatus"] = automation_status
        for key in ("browserBlocker", "operatorNextAction", "readyScenes", "totalScenes", "allReady"):
            if key in automation_status:
                payload[key] = automation_status.get(key)
    if result:
        for key in ("browserBlocker", "operatorNextAction", "readyScenes", "totalScenes", "allReady"):
            if key in result:
                payload[key] = result.get(key)
    if error:
        payload["error"] = error
    return payload


def _manual_download_watch_status(
    *,
    project_id: str,
    job_id: str,
    scene: dict | None,
    status: str,
    detail: str,
    download_dir: Path,
    download_dirs: list[Path] | None = None,
    timeout_seconds: float,
    poll_interval_seconds: float,
    allow_newest_fallback: bool,
    since_handoff: bool,
    overwrite: bool,
    preserve_candidates: bool,
    stop_on_import: bool,
    created_at: str,
    scene_mapping_mode: str = "",
    scene_grouped_take_size: int = 0,
    started_at: str | None = None,
    finished_at: str | None = None,
    result: dict | None = None,
    error: str | None = None,
) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    watched_dirs = _normalized_download_dirs(download_dir, download_dirs)
    payload = {
        "jobId": job_id,
        "projectId": project_id,
        "sceneId": (scene or {}).get("sceneId") or "",
        "expectedFileName": (scene or {}).get("expectedFileName") or "",
        "status": status,
        "detail": detail,
        "createdAt": created_at,
        "updatedAt": now,
        "downloadDir": str(watched_dirs[0]),
        "downloadDirs": [str(item) for item in watched_dirs],
        "timeoutSeconds": timeout_seconds,
        "pollIntervalSeconds": poll_interval_seconds,
        "allowNewestFallback": allow_newest_fallback,
        "sinceHandoff": since_handoff,
        "overwrite": overwrite,
        "preserveCandidates": preserve_candidates,
        "stopOnImport": stop_on_import,
        "sceneMappingMode": scene_mapping_mode,
        "sceneGroupedTakeSize": scene_grouped_take_size,
        "operatorNextAction": (
            "Generate or download the Grok MP4 in the signed-in Grok app/web; "
            "Video Studio is watching the approved folder(s) and will import it as a scene candidate."
        ),
    }
    if started_at:
        payload["startedAt"] = started_at
    if finished_at:
        payload["finishedAt"] = finished_at
    if result:
        payload.update({
            "readyScenes": result.get("readyScenes"),
            "totalScenes": result.get("totalScenes"),
            "allReady": result.get("allReady"),
            "attempts": result.get("attempts"),
            "elapsedSeconds": result.get("elapsedSeconds"),
            "timedOut": result.get("timedOut"),
            "importedCount": len(result.get("imported") or []),
        })
        if result.get("sceneGroupedTakeTarget") is not None:
            payload["sceneGroupedTakeTarget"] = result.get("sceneGroupedTakeTarget")
        if result.get("imported"):
            payload["operatorNextAction"] = (
                "Grok MP4 imported. Open Grok 검수, compare candidates, then accept or reject before render."
            )
    if error:
        payload["error"] = error
    return payload


def _select_grok_scene(manifest: dict, requested_scene_id: str = "") -> dict | None:
    scenes = [scene for scene in manifest.get("scenes") or [] if isinstance(scene, dict)]
    if requested_scene_id:
        requested_slug = slugify(requested_scene_id)
        matched = next((item for item in scenes if slugify(str(item.get("sceneId") or "")) == requested_slug), None)
        if matched is not None:
            return matched
    return next(iter(scenes), None)


GROK_REPLACEMENT_GATE_STATUSES = {"technical-review", "source-review", "rejected"}


def _grok_candidate_int(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _grok_candidate_quality_rank(candidate: dict) -> tuple[int, int, int, int, int, int, str]:
    if not isinstance(candidate, dict):
        return (0, 0, 0, 0, 0, 0, "")
    probe = candidate.get("clipProbe") if isinstance(candidate.get("clipProbe"), dict) else {}
    source_provenance = (
        candidate.get("sourceProvenance")
        if isinstance(candidate.get("sourceProvenance"), dict)
        else {}
    )
    return (
        1 if probe.get("ok") is True else 0,
        _grok_candidate_int(probe.get("height")),
        _grok_candidate_int(probe.get("width")),
        1 if source_provenance.get("acceptAsGrokMainSource") is True else 0,
        1 if probe.get("motionOk") is True else 0,
        _grok_candidate_int(candidate.get("sizeBytes")),
        str(candidate.get("fileName") or ""),
    )


def _grok_best_candidate_record(candidate_records: list[dict]) -> dict | None:
    if not candidate_records:
        return None
    return max(candidate_records, key=_grok_candidate_quality_rank)


def _grok_asset_needs_replacement(asset: dict, manifest: dict | None = None) -> bool:
    if not isinstance(asset, dict) or asset.get("status") != "ready":
        return False
    gate = asset.get("qualityGate") if isinstance(asset.get("qualityGate"), dict) else {}
    if gate.get("status") == "rejected":
        return True
    strict_quality = bool(
        isinstance(manifest, dict)
        and (manifest.get("qualityGateRequired") is True or manifest.get("grokMainSourceRequired") is True)
    )
    return bool(
        strict_quality
        and (
            gate.get("status") in GROK_REPLACEMENT_GATE_STATUSES
            or gate.get("technicalOk") is False
            or gate.get("sourceAcceptable") is False
        )
    )


def _grok_status_ready_assets(manifest: dict, assets: list[dict]) -> list[dict]:
    """Assets to count as ready in operator-facing Grok-main status."""
    ready_assets = [
        item
        for item in assets
        if isinstance(item, dict) and item.get("status") == "ready" and item.get("sceneId")
    ]
    if manifest.get("grokMainSourceRequired") is not True:
        return ready_assets
    return [
        item
        for item in ready_assets
        if item.get("qualityGate", {}).get("status") == "accepted"
    ]


def _next_missing_or_rejected_scene(
    handoff_dir: Path,
    manifest: dict,
    assets: list[dict] | None = None,
) -> dict | None:
    assets = assets if assets is not None else _match_downloaded_assets(handoff_dir, manifest)
    ready_asset_by_scene_id = {
        str(item.get("sceneId")): item
        for item in assets
        if isinstance(item, dict) and item.get("status") == "ready" and item.get("sceneId")
    }
    review_decisions = manifest.get("reviewDecisions") if isinstance(manifest.get("reviewDecisions"), dict) else {}
    rejected_scene_ids = {
        str(scene_id)
        for scene_id, decision in review_decisions.items()
        if isinstance(decision, dict) and decision.get("accepted") is False
    }
    for scene in manifest.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("sceneId") or "")
        asset = ready_asset_by_scene_id.get(scene_id)
        if asset is None or scene_id in rejected_scene_ids or _grok_asset_needs_replacement(asset, manifest):
            return scene
    return None


def _scene_queue_status(
    handoff_dir: Path,
    manifest: dict,
    assets: list[dict] | None = None,
) -> dict:
    assets = assets if assets is not None else _match_downloaded_assets(handoff_dir, manifest)
    ready_scene_ids = {
        str(item.get("sceneId"))
        for item in assets
        if item.get("status") == "ready" and item.get("sceneId")
    }
    replacement_scene_ids = sorted(
        str(item.get("sceneId"))
        for item in assets
        if _grok_asset_needs_replacement(item, manifest)
    )
    review_decisions = manifest.get("reviewDecisions") if isinstance(manifest.get("reviewDecisions"), dict) else {}
    rejected_scene_ids = sorted(
        str(scene_id)
        for scene_id, decision in review_decisions.items()
        if isinstance(decision, dict) and decision.get("accepted") is False
    )
    scene_ids = [
        str(scene.get("sceneId") or f"scene-{index + 1:02d}")
        for index, scene in enumerate(manifest.get("scenes") or [])
        if isinstance(scene, dict)
    ]
    missing_scene_ids = sorted(scene_id for scene_id in scene_ids if scene_id not in ready_scene_ids)
    next_scene = _next_missing_or_rejected_scene(handoff_dir, manifest, assets)
    next_scene_id = next_scene.get("sceneId") if next_scene else None
    return {
        "missingSceneIds": missing_scene_ids,
        "replacementSceneIds": replacement_scene_ids,
        "rejectedSceneIds": rejected_scene_ids,
        "nextMissingSceneId": next_scene_id,
        "nextMissingExpectedFileName": next_scene.get("expectedFileName") if next_scene else None,
        "nextMissingReason": (
            "quality-replacement-required"
            if next_scene_id and str(next_scene_id) in replacement_scene_ids
            else "missing-mp4"
            if next_scene_id and str(next_scene_id) in missing_scene_ids
            else "review-rejected"
            if next_scene_id and str(next_scene_id) in rejected_scene_ids
            else ""
        ),
    }


def _asset_url(project_id: str, file_name: str) -> str:
    return f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/asset/{file_name}"


def _worksheet_url(project_id: str) -> str:
    return f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/worksheet"


def _production_queue_url(project_id: str) -> str:
    return f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/production-queue"


def _automation_plan_url(project_id: str) -> str:
    return f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/automation-plan"


def _review_packet_url(project_id: str) -> str:
    return f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/review-packet"


def _review_decision_url(project_id: str) -> str:
    return f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/review-decision"


def _chrome_companion_guide_url(project_id: str, scene_id: str | None = None) -> str:
    query = f"?sceneId={urllib.parse.quote(scene_id)}" if scene_id else ""
    return f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/chrome-extension{query}"


def _normalize_take_number(value: object, default: int = 1) -> int:
    try:
        return max(1, min(6, int(value or default)))
    except (TypeError, ValueError):
        return default


def _recommended_take_number(scene: dict | None) -> int:
    if not isinstance(scene, dict):
        return 1
    # Take 2 is the production default because it prioritizes first-second
    # visible motion, which is the strongest Grok-main quality signal.
    for preferred in (2, 1):
        if _select_take_prompt(scene, preferred):
            return preferred
    takes = scene.get("takePrompts") if isinstance(scene.get("takePrompts"), list) else []
    for item in takes:
        if isinstance(item, dict):
            return _normalize_take_number(item.get("takeNumber"))
    return 1


def _extension_command_url(project_id: str, scene_id: str | None = None, take_number: object = None) -> str:
    query = {"operatorApproved": "true"}
    if scene_id:
        query["sceneId"] = scene_id
    normalized_take = _normalize_take_number(take_number)
    if normalized_take > 1:
        query["take"] = str(normalized_take)
    return (
        f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/extension-command?"
        + urllib.parse.urlencode(query)
    )


def _extension_autostart_url(
    project_id: str,
    scene_id: str | None = None,
    action: str = "fill-prompt",
    take_number: object = None,
) -> str:
    """Open Grok in an existing Chrome profile and let the companion content script load a command."""
    normalized_action = action if action in {"fill-prompt", "prep-generate", "probe"} else "fill-prompt"
    query = {
        "operatorApproved": "true",
        "videoStudioGrokCommandUrl": _extension_command_url(project_id, scene_id, take_number),
        "videoStudioAction": normalized_action,
    }
    if normalized_action == "prep-generate":
        query["videoStudioAutoGenerate"] = "true"
    return f"{GROK_IMAGINE_URL}#{urllib.parse.urlencode(query)}"


def _extension_asset_autodownload_url(project_id: str, scene_id: str | None, asset_url: str) -> str:
    """Return the safe local runway instead of opening a direct MP4 asset tab."""
    return _observed_asset_manual_runway_url(project_id, scene_id)


def _extension_observed_post_autodownload_url(project_id: str, scene_id: str | None, post_url: str) -> str:
    """Open a Grok post page and let the companion recover the visible MP4 candidate."""
    cleaned_post_url = str(post_url or "").split("#", 1)[0].strip()
    if not cleaned_post_url:
        return ""
    query = {
        "operatorApproved": "true",
        "videoStudioGrokCommandUrl": _extension_command_url(project_id, scene_id),
        "videoStudioAction": "download-visible-video",
    }
    return f"{cleaned_post_url}#{urllib.parse.urlencode(query)}"


def _observed_asset_manual_runway_url(project_id: str, scene_id: str | None = None) -> str:
    query = {"operatorApproved": "true"}
    if scene_id:
        query["sceneId"] = scene_id
    return (
        f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/observed-asset-manual-runway?"
        + urllib.parse.urlencode(query)
    )


def _extension_event_url(project_id: str) -> str:
    return f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/extension-event"


def _bookmarklet_script_url(
    project_id: str,
    scene_id: str | None = None,
    auto_generate: bool = False,
    take_number: object = None,
) -> str:
    query = {"operatorApproved": "true"}
    if scene_id:
        query["sceneId"] = scene_id
    if auto_generate:
        query["autoGenerate"] = "true"
    normalized_take = _normalize_take_number(take_number)
    if normalized_take > 1:
        query["take"] = str(normalized_take)
    return (
        f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/bookmarklet.js?"
        + urllib.parse.urlencode(query)
    )


def _bookmarklet_queue_script_url(project_id: str, max_scenes: int = 5, wait_seconds: int = 180) -> str:
    query = {
        "operatorApproved": "true",
        "maxScenes": str(max(1, min(12, int(max_scenes or 5)))),
        "waitSeconds": str(max(20, min(600, int(wait_seconds or 180)))),
    }
    return (
        f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/bookmarklet-queue.js?"
        + urllib.parse.urlencode(query)
    )


def _bookmarklet_import_url(project_id: str) -> str:
    return f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/bookmarklet-import"


def _bookmarklet_event_url(project_id: str) -> str:
    return f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/bookmarklet-event"


def _bookmarklet_url(
    project_id: str,
    scene_id: str | None = None,
    auto_generate: bool = False,
    take_number: object = None,
) -> str:
    script_url = _bookmarklet_script_url(project_id, scene_id, auto_generate, take_number)
    js = (
        "(()=>{"
        "const s=document.createElement('script');"
        f"s.src={json.dumps(script_url)};"
        "s.async=true;"
        "s.onerror=()=>alert('Video Studio Grok fallback script failed to load from local bridge.');"
        "document.documentElement.appendChild(s);"
        "})()"
    )
    return "javascript:" + urllib.parse.quote(js, safe="()=;,:'.")


def _bookmarklet_queue_url(project_id: str, max_scenes: int = 5, wait_seconds: int = 180) -> str:
    script_url = _bookmarklet_queue_script_url(project_id, max_scenes=max_scenes, wait_seconds=wait_seconds)
    js = (
        "(()=>{"
        "const s=document.createElement('script');"
        f"s.src={json.dumps(script_url)};"
        "s.async=true;"
        "s.onerror=()=>alert('Video Studio Grok queue script failed to load from local bridge.');"
        "document.documentElement.appendChild(s);"
        "})()"
    )
    return "javascript:" + urllib.parse.quote(js, safe="()=;,:'.")


def _inline_bookmarklet_url(script: str) -> str:
    return "javascript:" + urllib.parse.quote(script.strip(), safe="()=;,:'.")


def _chrome_companion_extension_dir() -> Path:
    return _project_root / "tools" / "chrome-grok-companion"


def _chrome_profile_roots() -> list[Path]:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return [Path(local_app_data) / "Google" / "Chrome" / "User Data"]
    home = Path.home()
    return [
        home / "AppData" / "Local" / "Google" / "Chrome" / "User Data",
        home / "Library" / "Application Support" / "Google" / "Chrome",
        home / ".config" / "google-chrome",
        home / ".config" / "chromium",
    ]


def _chrome_profile_sort_key(profile_dir: Path) -> tuple[int, str]:
    name = profile_dir.name
    if name == "Default":
        return (0, name)
    match = re.match(r"Profile\s+(\d+)$", name)
    if match:
        return (1, f"{int(match.group(1)):06d}")
    return (2, name.lower())


def _chrome_profile_display_name(profile_dir: Path, preferences_text: str) -> str:
    try:
        payload = json.loads(preferences_text or "{}")
    except json.JSONDecodeError:
        return profile_dir.name
    if not isinstance(payload, dict):
        return profile_dir.name
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    name = str(profile.get("name") or "").strip()
    return name or profile_dir.name


def _read_chrome_preferences_text(path: Path) -> str:
    try:
        return path.read_bytes()[:2_000_000].decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _contains_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    folded = text.lower()
    return any(marker.lower() in folded for marker in markers if marker)


def _codex_chrome_native_host_probe() -> dict:
    host_name = "com.openai.codexextension"
    local_app_data = os.environ.get("LOCALAPPDATA")
    manifest_path = Path(local_app_data) / "OpenAI" / "extension" / f"{host_name}.json" if local_app_data else None
    manifest_data: dict = {}
    host_path = ""
    allowed_origins: list[str] = []
    if manifest_path and manifest_path.is_file():
        try:
            parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                manifest_data = parsed
        except (OSError, json.JSONDecodeError):
            manifest_data = {}
    if manifest_data:
        host_path = str(manifest_data.get("path") or "")
        raw_origins = manifest_data.get("allowed_origins")
        if isinstance(raw_origins, list):
            allowed_origins = [str(item) for item in raw_origins if item]
    manifest_exists = bool(manifest_path and manifest_path.is_file())
    host_exists = bool(host_path and Path(host_path).is_file())
    allowed_origin_registered = any("hehggadaopoacecdllhhajmbjkdcmajg" in item for item in allowed_origins)
    if manifest_exists and host_exists and allowed_origin_registered:
        status = "installed"
        operator_action = (
            "Codex Chrome native host is installed, but Video Studio does not use it as the Grok production bridge "
            "and this bridge process cannot drive the Codex Chrome plugin directly. Use the existing signed-in "
            "Chrome profile for Grok generation, then use the Video Studio Grok Companion, observed-post runner, "
            "Downloads watcher, or batch MP4 upload for this packet."
        )
    elif manifest_exists and not host_exists:
        status = "host-executable-missing"
        operator_action = "Codex Chrome native host manifest exists, but its host executable was not found."
    elif manifest_exists:
        status = "manifest-incomplete"
        operator_action = "Codex Chrome native host manifest exists, but the expected Codex extension origin was not registered."
    else:
        status = "manifest-missing"
        operator_action = "Codex Chrome native host manifest was not found in LOCALAPPDATA."
    return {
        "checked": True,
        "hostName": host_name,
        "manifestPath": str(manifest_path or ""),
        "manifestExists": manifest_exists,
        "hostExecutablePath": host_path,
        "hostExecutableExists": host_exists,
        "allowedOriginRegistered": allowed_origin_registered,
        "status": status,
        "usedByVideoStudioGrok": False,
        "videoStudioDirectControlAvailable": False,
        "controlSurfaceExposedToBridge": False,
        "requiredControlSurface": "Codex Chrome/node_repl browser runtime exposed to the current Codex session",
        "directControlReason": (
            "The installed native host belongs to the Codex Chrome extension. Video Studio can report that it exists, "
            "but cannot use it as a Grok MP4 acquisition bridge without the official Codex browser-control tool surface."
        ),
        "recommendedUse": "Use existing signed-in Chrome/Grok for generation; import native MP4s through the Video Studio watcher/upload path.",
        "operatorAction": operator_action,
    }


def _chrome_profile_companion_probe() -> dict:
    companion_dir = str(_chrome_companion_extension_dir())
    companion_markers = (
        "Video Studio Grok Companion",
        "chrome-grok-companion",
        "tools\\chrome-grok-companion",
        "tools/chrome-grok-companion",
        companion_dir,
        companion_dir.replace("\\", "/"),
    )
    codex_markers = (
        "hehggadaopoacecdllhhajmbjkdcmajg",
        "com.openai.codexextension",
        "Codex Extension",
    )
    checked_roots: list[str] = []
    profiles: list[dict] = []
    for root in _chrome_profile_roots():
        if not root.exists() or not root.is_dir():
            continue
        checked_roots.append(str(root))
        try:
            profile_dirs = [
                child
                for child in root.iterdir()
                if child.is_dir() and (child / "Preferences").is_file()
            ]
        except OSError:
            continue
        for profile_dir in sorted(profile_dirs, key=_chrome_profile_sort_key):
            preferences_path = profile_dir / "Preferences"
            preferences_text = _read_chrome_preferences_text(preferences_path)
            video_studio_companion = _contains_any_marker(preferences_text, companion_markers)
            codex_extension = _contains_any_marker(preferences_text, codex_markers)
            profiles.append({
                "profileDir": profile_dir.name,
                "profileName": _chrome_profile_display_name(profile_dir, preferences_text),
                "videoStudioCompanion": video_studio_companion,
                "codexExtension": codex_extension,
                "preferencesReadable": bool(preferences_text),
            })

    any_video_studio = any(profile.get("videoStudioCompanion") is True for profile in profiles)
    any_codex = any(profile.get("codexExtension") is True for profile in profiles)
    companion_profiles = [profile for profile in profiles if profile.get("videoStudioCompanion") is True]
    codex_profiles = [profile for profile in profiles if profile.get("codexExtension") is True]
    default_profile = next((profile for profile in profiles if profile.get("profileDir") == "Default"), None)
    recommended_profile = (
        companion_profiles[0]
        if companion_profiles
        else codex_profiles[0]
        if codex_profiles
        else default_profile
        if default_profile
        else profiles[0]
        if profiles
        else {}
    )
    recommended_profile_dir = str(recommended_profile.get("profileDir") or "")
    recommended_profile_name = str(recommended_profile.get("profileName") or "")
    recommended_profile_label = " ".join(
        item
        for item in (
            recommended_profile_dir,
            f"({recommended_profile_name})" if recommended_profile_name else "",
        )
        if item
    ) or "the signed-in Chrome profile"
    if any_video_studio:
        status = "video-studio-companion-seen"
        action = "Video Studio Grok Companion appears in a local Chrome profile. Use that signed-in profile for Grok generation and import."
    elif any_codex:
        status = "codex-extension-only"
        profile_hint = f" ({recommended_profile_name})" if recommended_profile_name else ""
        target = recommended_profile_dir or "the signed-in Chrome profile"
        action = (
            "Codex Chrome extension is not the Video Studio Grok Companion. "
            f"Use the existing Chrome profile {target}{profile_hint} for Grok app/web generation, then load the "
            "unpacked Video Studio companion extension there or save native Grok MP4s into the watched folders. "
            "Do not switch to Edge or a new Chrome profile for Grok-main."
        )
    elif checked_roots:
        status = "not-installed"
        action = "No Video Studio Grok Companion marker was found in local Chrome profile preferences. Load the unpacked extension in the signed-in Chrome profile."
    else:
        status = "chrome-profile-root-not-found"
        action = "Chrome profile root was not found from this runtime. Open the guide in the signed-in Chrome profile and load the unpacked companion extension there."
    return {
        "checked": bool(checked_roots),
        "status": status,
        "checkedRoots": checked_roots,
        "profiles": profiles,
        "anyVideoStudioCompanion": any_video_studio,
        "anyCodexExtension": any_codex,
        "recommendedProfileDirectory": recommended_profile_dir,
        "recommendedProfileName": recommended_profile_name,
        "recommendedProfileLabel": recommended_profile_label,
        "recommendedProfileReason": (
            "video-studio-companion-detected"
            if companion_profiles
            else "codex-extension-profile"
            if codex_profiles
            else "default-profile"
            if default_profile
            else "first-readable-profile"
            if profiles
            else "no-readable-profile"
        ),
        "videoStudioCompanionProfileDirectories": [
            str(profile.get("profileDir") or "") for profile in companion_profiles if profile.get("profileDir")
        ],
        "codexExtensionProfileDirectories": [
            str(profile.get("profileDir") or "") for profile in codex_profiles if profile.get("profileDir")
        ],
        "codexNativeHost": _codex_chrome_native_host_probe(),
        "codexExtensionCanDriveVideoStudioGrok": False,
        "codexExtensionIsNotCompanion": any_codex and not any_video_studio,
        "primaryOperatorProfileDirectory": recommended_profile_dir,
        "primaryOperatorProfileName": recommended_profile_name,
        "primaryOperatorProfileLabel": recommended_profile_label,
        "browserPolicy": "existing-signed-in-chrome-profile-only",
        "doNotOpenBrowsers": ["Microsoft Edge", "new Chrome profile"],
        "operatorAction": action,
    }


def _chrome_profile_probe_with_packet_context(handoff_dir: Path) -> dict:
    probe = _chrome_profile_companion_probe()
    replay_summary = _automation_replay_summary(_read_automation_request(handoff_dir))
    replay_profile = str((replay_summary or {}).get("browserProfileDirectory") or "").strip()
    recommended_profile = str(probe.get("recommendedProfileDirectory") or "").strip()
    if replay_profile:
        probe["automationReplayProfileDirectory"] = replay_profile
    mismatch = bool(
        replay_profile
        and recommended_profile
        and replay_profile != recommended_profile
        and probe.get("anyVideoStudioCompanion") is not True
    )
    probe["profileMismatch"] = mismatch
    primary_label = str(probe.get("primaryOperatorProfileLabel") or probe.get("recommendedProfileLabel") or recommended_profile or "").strip()
    do_not_open = list(probe.get("doNotOpenBrowsers") or ["Microsoft Edge", "new Chrome profile"])
    if mismatch and replay_profile and replay_profile not in do_not_open:
        do_not_open.append(f"{replay_profile} CDP replay as the primary Grok source")
    probe["profileAlignment"] = {
        "status": "mismatch" if mismatch else "aligned" if recommended_profile else "unknown",
        "primaryOperatorProfileDirectory": recommended_profile,
        "primaryOperatorProfileName": str(probe.get("recommendedProfileName") or "").strip(),
        "primaryOperatorProfileLabel": primary_label or "signed-in Chrome profile",
        "automationReplayProfileDirectory": replay_profile,
        "profileMismatch": mismatch,
        "codexExtensionProfileDirectories": probe.get("codexExtensionProfileDirectories") or [],
        "videoStudioCompanionProfileDirectories": probe.get("videoStudioCompanionProfileDirectories") or [],
        "controlRoute": "native-mp4-watcher-or-companion",
        "codexChromePluginRoute": "installed-but-not-bridge-control",
        "operatorAction": (
            f"Use existing Chrome profile {primary_label or recommended_profile or 'signed-in Chrome'} for Grok generation; "
            "save/export native MP4s into watched folders. Do not open Edge or a fresh Chrome profile for Grok-main."
        ),
        "doNotOpen": do_not_open,
    }
    if mismatch:
        profile_name = str(probe.get("recommendedProfileName") or "").strip()
        profile_hint = f" ({profile_name})" if profile_name else ""
        probe["operatorAction"] = (
            f"Saved Grok CDP replay points at Chrome profile {replay_profile}, but the usable signed-in/Codex-visible "
            f"profile appears to be {recommended_profile}{profile_hint}. Use existing Chrome profile "
            f"{recommended_profile}{profile_hint} for Grok app/web generation, not Edge or a new Chrome profile. "
            "Load the Video Studio Grok Companion there when possible, or save native MP4s into the watched folders. "
            "Treat CDP replay as secondary."
        )
        probe["profileAlignment"]["operatorAction"] = probe["operatorAction"]
    return probe


def _extension_event_log_path(handoff_dir: Path) -> Path:
    return handoff_dir / "extension-events.jsonl"


def _latest_extension_event(handoff_dir: Path) -> dict | None:
    path = _extension_event_log_path(handoff_dir)
    if not path.exists():
        return None
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            return event
    return None


def _latest_grok_source_event(handoff_dir: Path, scene_id: str, file_name: str, expected_file_name: str = "") -> dict:
    path = _extension_event_log_path(handoff_dir)
    if not path.exists():
        return {}
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return {}
    file_names = {Path(file_name).name}
    if expected_file_name:
        file_names.add(Path(expected_file_name).name)
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_scene_id = str(event.get("sceneId") or "")
        if event_scene_id and event_scene_id != scene_id:
            continue
        event_type = str(event.get("eventType") or "")
        event_file_name = Path(str(event.get("expectedFileName") or "")).name
        if (
            event_type == "codex-chrome-observation"
            and expected_file_name
            and Path(file_name).name != Path(expected_file_name).name
        ):
            continue
        if not event_file_name and expected_file_name and Path(file_name).name != Path(expected_file_name).name:
            continue
        if event_file_name and event_file_name not in file_names:
            continue
        if not any(event.get(key) for key in ("sourceKind", "qualityNote", "candidateUrl")):
            continue
        return event
    return {}


def _companion_connection_status(latest_event: dict | None) -> dict:
    if not latest_event:
        return {
            "status": "not-seen",
            "connected": False,
            "lastSeenAt": "",
            "eventType": "",
            "eventStatus": "",
            "secondsSinceLastSeen": None,
            "operatorAction": "Load the Video Studio Grok Companion extension in the signed-in Chrome profile, then load a scene command or use Hash+Generate.",
        }
    event_type = str(latest_event.get("eventType") or "")
    event_status = str(latest_event.get("status") or "")
    last_seen_at = str(latest_event.get("updatedAt") or "")
    seconds_since = None
    try:
        seconds_since = max(0, int((datetime.now() - datetime.fromisoformat(last_seen_at)).total_seconds()))
    except (TypeError, ValueError):
        seconds_since = None
    source = str(latest_event.get("source") or "")
    is_bookmarklet = source == "bookmarklet-fallback" or event_type.startswith("bookmarklet")
    if is_bookmarklet:
        status = "bookmarklet-only"
        connected = False
        action = "Bookmarklet fallback is working, but the Chrome companion extension has not reported a heartbeat. Load/reload the extension for automatic download import and queue advance."
    elif seconds_since is not None and seconds_since > 900:
        status = "stale"
        connected = False
        action = "Chrome companion was seen earlier but is stale. Open Grok in the signed-in Chrome profile, reload the companion extension if needed, then load the current scene command."
    else:
        status = "connected"
        connected = True
        action = "Chrome companion is connected. Use Prep + Generate or Queue mode, then download/review imported MP4s."
    return {
        "status": status,
        "connected": connected,
        "lastSeenAt": last_seen_at,
        "eventType": event_type,
        "eventStatus": event_status,
        "sceneId": str(latest_event.get("sceneId") or ""),
        "secondsSinceLastSeen": seconds_since,
        "detail": str(latest_event.get("detail") or ""),
        "operatorAction": action,
    }


def _sanitize_observed_grok_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"}:
        return ""
    host = parsed.netloc.lower()
    allowed = (
        host == "grok.com"
        or host.endswith(".grok.com")
        or host == "x.ai"
        or host.endswith(".x.ai")
    )
    if not allowed:
        return ""
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _latest_codex_chrome_observation(manifest: dict) -> dict | None:
    latest = manifest.get("latestCodexChromeObservation")
    if isinstance(latest, dict):
        return latest
    observations = manifest.get("codexChromeObservations")
    if isinstance(observations, list):
        for item in reversed(observations):
            if isinstance(item, dict):
                return item
    return None


def _parse_ratio(value: object) -> float | None:
    raw = str(value or "").strip()
    if not raw or raw == "0/0":
        return None
    if "/" in raw:
        left, right = raw.split("/", 1)
        try:
            denominator = float(right)
            if denominator == 0:
                return None
            return float(left) / denominator
        except (TypeError, ValueError):
            return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _probe_grok_motion(path: Path, duration_sec: float) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {
            "motionOk": False,
            "motionStatus": "tool-missing",
            "motionIssues": ["ffmpeg not found for motion evidence probe"],
        }

    width = 24
    height = 24
    frame_size = width * height
    sample_seconds = min(max(duration_sec or 3.0, 1.0), 4.0)
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                str(path),
                "-t",
                f"{sample_seconds:.3f}",
                "-vf",
                f"fps=2,scale={width}:{height},format=gray",
                "-an",
                "-f",
                "rawvideo",
                "-",
            ],
            check=False,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "motionOk": False,
            "motionStatus": "probe-error",
            "motionIssues": [f"motion probe failed: {exc}"],
        }
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
        return {
            "motionOk": False,
            "motionStatus": "probe-error",
            "motionIssues": [detail or f"ffmpeg motion probe exited {completed.returncode}"],
        }
    raw = completed.stdout or b""
    frame_count = len(raw) // frame_size
    if frame_count < 2:
        return {
            "motionOk": False,
            "motionStatus": "insufficient-frames",
            "motionFrameCount": frame_count,
            "motionIssues": ["not enough decoded frames for motion evidence"],
        }
    frames = [
        raw[index * frame_size:(index + 1) * frame_size]
        for index in range(frame_count)
    ]
    deltas: list[float] = []
    for left, right in zip(frames, frames[1:]):
        if len(left) != frame_size or len(right) != frame_size:
            continue
        deltas.append(sum(abs(a - b) for a, b in zip(left, right)) / frame_size)
    max_delta = max(deltas) if deltas else 0.0
    mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
    motion_ok = max_delta >= 1.25 and mean_delta >= 0.35
    issues = [] if motion_ok else [
        f"low motion evidence in sampled frames: max delta {max_delta:.2f}, mean delta {mean_delta:.2f}"
    ]
    return {
        "motionOk": motion_ok,
        "motionStatus": "ok" if motion_ok else "low-motion",
        "motionFrameCount": frame_count,
        "motionMaxFrameDelta": round(max_delta, 3),
        "motionMeanFrameDelta": round(mean_delta, 3),
        "motionIssues": issues,
    }


def _probe_grok_clip(path: Path) -> dict:
    """Return technical clip evidence for imported Grok MP4 review gates."""
    try:
        with path.open("rb") as handle:
            header = handle.read(4096)
    except OSError as exc:
        return {
            "ok": False,
            "status": "probe-error",
            "issues": [f"clip header read failed: {exc}"],
        }
    if b"ftyp" not in header:
        return {
            "ok": False,
            "status": "probe-error",
            "issues": ["not an MP4 container or missing ftyp signature"],
        }

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {
            "ok": False,
            "status": "tool-missing",
            "issues": ["ffprobe not found"],
        }
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "status": "probe-error",
            "issues": [str(exc)],
        }
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        return {
            "ok": False,
            "status": "probe-error",
            "issues": [stderr or stdout or f"ffprobe exited {completed.returncode}"],
        }
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "status": "probe-error",
            "issues": [f"ffprobe JSON parse failed: {exc.msg}"],
        }

    streams = payload.get("streams") if isinstance(payload, dict) else []
    if not isinstance(streams, list):
        streams = []
    video = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"), {})
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    fps = _parse_ratio(video.get("avg_frame_rate")) or _parse_ratio(video.get("r_frame_rate")) or 0.0
    duration = 0.0
    for candidate in (
        video.get("duration"),
        (payload.get("format") or {}).get("duration") if isinstance(payload, dict) else None,
    ):
        try:
            duration = float(candidate)
            break
        except (TypeError, ValueError):
            continue
    aspect = (width / height) if height else 0.0
    issues: list[str] = []
    if width <= 0 or height <= 0:
        issues.append("missing video dimensions")
    elif not (0.50 <= aspect <= 0.65):
        issues.append(f"not vertical 9:16-ish aspect ratio: {width}x{height}")
    if height and height < 960:
        issues.append(f"vertical height below review floor: {height}")
    if width and height and (width < 720 or height < 1280):
        issues.append(
            f"resolution below native Grok-main floor: {width}x{height}; "
            "require at least 720x1280 original vertical MP4"
        )
    if duration and not (2.0 <= duration <= 8.0):
        issues.append(f"duration outside short-clip review range: {duration:.2f}s")
    if fps and fps < 20:
        issues.append(f"fps below review floor: {fps:.2f}")
    motion = _probe_grok_motion(path, duration) if video else {
        "motionOk": False,
        "motionStatus": "no-video",
        "motionIssues": ["missing video stream for motion evidence"],
    }
    motion_issues = motion.get("motionIssues") if isinstance(motion.get("motionIssues"), list) else []
    issues.extend(str(item) for item in motion_issues)
    return {
        "ok": not issues and bool(video),
        "status": "ok" if not issues and bool(video) else "needs-review",
        "width": width,
        "height": height,
        "fps": round(fps, 3) if fps else None,
        "durationSec": round(duration, 3) if duration else None,
        "aspectRatio": round(aspect, 4) if aspect else None,
        "hasAudio": bool(audio),
        "issues": issues,
        **motion,
    }


def _asset_quality_gate(asset: dict, review_decisions: dict, manifest: dict) -> dict:
    scene_id = str(asset.get("sceneId") or "")
    status = str(asset.get("status") or "")
    decision = review_decisions.get(scene_id) if isinstance(review_decisions.get(scene_id), dict) else {}
    technical = asset.get("clipProbe") if isinstance(asset.get("clipProbe"), dict) else {}
    import_preflight = asset.get("importPreflight") if isinstance(asset.get("importPreflight"), dict) else {}
    source_provenance = asset.get("sourceProvenance") if isinstance(asset.get("sourceProvenance"), dict) else {}
    required = manifest.get("qualityGateRequired") is True
    main_evidence_missing = (
        _grok_main_review_evidence_missing(decision, source_provenance)
        if manifest.get("grokMainSourceRequired") is True and decision.get("accepted") is True
        else []
    )
    if status != "ready":
        gate_status = "missing"
    elif decision.get("accepted") is False:
        gate_status = "rejected"
    elif technical and technical.get("ok") is False:
        gate_status = "technical-review"
    elif import_preflight and import_preflight.get("readyForReview") is False:
        gate_status = "import-preflight"
    elif manifest.get("grokMainSourceRequired") is True and source_provenance.get("acceptAsGrokMainSource") is False:
        gate_status = "source-review"
    elif main_evidence_missing:
        gate_status = "shot-lock-review"
    elif decision.get("accepted") is True and all(
        decision.get(key) is True
        for key in ("firstTwoSecondHook", "artifactFree", "continuityOk", "captionSafe")
    ):
        gate_status = "accepted"
    elif required:
        gate_status = "pending-operator-review"
    else:
        gate_status = "review-recommended"
    return {
        "required": required,
        "status": gate_status,
        "accepted": decision.get("accepted") is True,
        "firstTwoSecondHook": decision.get("firstTwoSecondHook") is True,
        "artifactFree": decision.get("artifactFree") is True,
        "continuityOk": decision.get("continuityOk") is True,
        "captionSafe": decision.get("captionSafe") is True,
        "shotLockMatch": decision.get("shotLockMatch") is True,
        "sceneAssemblyOk": decision.get("sceneAssemblyOk") is True,
        "reviewEvidenceMissing": main_evidence_missing,
        "technicalOk": technical.get("ok") is True if technical else None,
        "technicalIssues": technical.get("issues") if isinstance(technical.get("issues"), list) else [],
        "selectedFileName": str(asset.get("fileName") or ""),
        "selectedSourcePath": str(asset.get("sourcePath") or ""),
        "sourceAcceptable": source_provenance.get("acceptAsGrokMainSource"),
        "sourceProvenanceConfirmationRequired": _grok_source_provenance_confirmation_required(source_provenance),
        "sourceProvenanceConfirmed": decision.get("sourceProvenanceConfirmed") is True,
        "sourceProvenanceNote": decision.get("sourceProvenanceNote") or "",
        "sourceIssues": (
            [source_provenance.get("operatorAction")]
            if source_provenance.get("acceptAsGrokMainSource") is False and source_provenance.get("operatorAction")
            else []
        ),
        "sourceProvenance": source_provenance,
        "reviewPacketUrl": manifest.get("reviewPacketUrl"),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl"),
    }


def _extension_scene(manifest: dict, scene_id: object = None) -> dict | None:
    requested_scene_id = str(scene_id or "").strip()
    if not requested_scene_id:
        return None
    return _select_grok_scene(manifest, requested_scene_id)


def _scene_take_commands(project_id: str, scene_id: str, scene: dict) -> list[dict]:
    take_prompts = scene.get("takePrompts") if isinstance(scene.get("takePrompts"), list) else []
    commands: list[dict] = []
    recommended_take_number = _recommended_take_number(scene)
    for item in take_prompts:
        if not isinstance(item, dict):
            continue
        take_number = _normalize_take_number(item.get("takeNumber"))
        command = {
            "ok": True,
            "projectId": project_id,
            "sceneId": scene_id,
            "sceneNum": scene.get("sceneNum"),
            "takeNumber": take_number,
            "takeLabel": str(item.get("label") or f"take-{take_number}"),
            "takeFocus": str(item.get("focus") or ""),
            "recommended": take_number == recommended_take_number,
            "recommendedTakeNumber": recommended_take_number,
            "label": str(item.get("label") or f"take-{take_number}"),
            "focus": str(item.get("focus") or ""),
            "prompt": str(item.get("prompt") or scene.get("prompt") or ""),
            "basePrompt": str(scene.get("prompt") or ""),
            "promptQuality": item.get("promptQuality") if isinstance(item.get("promptQuality"), dict) else {},
            "expectedFileName": str(scene.get("expectedFileName") or f"{scene_id}.grok.mp4"),
            "commandUrl": _extension_command_url(project_id, scene_id, take_number),
            "autostartUrl": _extension_autostart_url(project_id, scene_id, "fill-prompt", take_number),
            "prepGenerateAutostartUrl": _extension_autostart_url(project_id, scene_id, "prep-generate", take_number),
            "bookmarkletUrl": _bookmarklet_url(project_id, scene_id, False, take_number),
            "bookmarkletGenerateUrl": _bookmarklet_url(project_id, scene_id, True, take_number),
        }
        fill_script = _bookmarklet_javascript(project_id, _bookmarklet_runtime_command(command), False)
        generate_script = _bookmarklet_javascript(project_id, _bookmarklet_runtime_command(command), True)
        command.update({
            "bookmarkletInlineMode": "self-contained",
            "bookmarkletInlineUrl": _inline_bookmarklet_url(fill_script),
            "bookmarkletGenerateInlineUrl": _inline_bookmarklet_url(generate_script),
            "bookmarkletInlineConsoleSnippet": fill_script.strip(),
            "bookmarkletGenerateInlineConsoleSnippet": generate_script.strip(),
        })
        commands.append(command)
    return commands


def _extension_queue_payload(
    project_id: str,
    handoff_dir: Path,
    manifest: dict,
    *,
    assets: list[dict] | None = None,
    queue_status: dict | None = None,
) -> dict:
    queue_status = (
        queue_status
        if isinstance(queue_status, dict)
        else _scene_queue_status(handoff_dir, manifest, assets)
    )
    next_scene_id = str(queue_status.get("nextMissingSceneId") or "").strip()
    next_scene = _select_grok_scene(manifest, next_scene_id) if next_scene_id else None
    next_take_number = _recommended_take_number(next_scene)
    all_scene_commands = []
    for index, scene in enumerate(manifest.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("sceneId") or f"scene-{index + 1:02d}")
        recommended_take_number = _recommended_take_number(scene)
        take_commands = _scene_take_commands(project_id, scene_id, scene)
        recommended_take_label = next(
            (
                str(command.get("takeLabel") or f"take-{recommended_take_number}")
                for command in take_commands
                if command.get("takeNumber") == recommended_take_number
            ),
            f"take-{recommended_take_number}",
        )
        all_scene_commands.append({
            "sceneId": scene_id,
            "expectedFileName": str(scene.get("expectedFileName") or f"{scene_id}.grok.mp4"),
            "recommendedTakeNumber": recommended_take_number,
            "recommendedTakeLabel": recommended_take_label,
            "commandUrl": _extension_command_url(project_id, scene_id, recommended_take_number),
            "autostartUrl": _extension_autostart_url(project_id, scene_id, "fill-prompt", recommended_take_number),
            "prepGenerateAutostartUrl": _extension_autostart_url(project_id, scene_id, "prep-generate", recommended_take_number),
            "takeCommands": take_commands,
        })
    return {
        **queue_status,
        "queueCommandUrl": _extension_command_url(project_id),
        "nextRecommendedTakeNumber": next_take_number if next_scene_id else None,
        "nextCommandUrl": _extension_command_url(project_id, next_scene_id, next_take_number) if next_scene_id else "",
        "allSceneCommands": all_scene_commands,
    }


def _bookmarklet_runtime_command(command: dict) -> dict:
    keep_keys = (
        "ok",
        "projectId",
        "sceneId",
        "sceneNum",
        "takeNumber",
        "takeLabel",
        "takeFocus",
        "prompt",
        "basePrompt",
        "promptQuality",
        "retryPrompt",
        "isRetry",
        "attemptNumber",
        "retryReason",
        "expectedFileName",
        "incomingDir",
        "defaultDownloadDir",
        "reviewPacketUrl",
        "uploadEndpoint",
    )
    return {key: command.get(key) for key in keep_keys if key in command}


def _attach_inline_bookmarklet_payloads(
    payload: dict,
    project_id: str,
    *,
    max_scenes: int = 5,
    wait_seconds: int = 180,
) -> dict:
    runtime_command = _bookmarklet_runtime_command(payload)
    fill_script = _bookmarklet_javascript(project_id, runtime_command, False)
    generate_script = _bookmarklet_javascript(project_id, runtime_command, True)
    queue_script = _bookmarklet_queue_javascript(
        project_id,
        runtime_command,
        max_scenes=max_scenes,
        wait_seconds=wait_seconds,
        inline_mode=True,
    )
    payload.update({
        "bookmarkletInlineMode": "self-contained",
        "bookmarkletInlineUrl": _inline_bookmarklet_url(fill_script),
        "bookmarkletGenerateInlineUrl": _inline_bookmarklet_url(generate_script),
        "bookmarkletInlineConsoleSnippet": fill_script.strip(),
        "bookmarkletGenerateInlineConsoleSnippet": generate_script.strip(),
        "bookmarkletQueueInlineUrl": _inline_bookmarklet_url(queue_script),
        "bookmarkletQueueInlineConsoleSnippet": queue_script.strip(),
    })
    return payload


def _chrome_companion_summary(
    project_id: str,
    handoff_dir: Path,
    manifest: dict,
    scene_id: object = None,
    *,
    next_scene: dict | None = None,
    assets: list[dict] | None = None,
    scene_queue: dict | None = None,
) -> dict:
    scene = (
        _extension_scene(manifest, scene_id)
        or (next_scene if isinstance(next_scene, dict) else None)
        or _next_missing_or_rejected_scene(handoff_dir, manifest, assets)
    )
    selected_scene_id = str(scene.get("sceneId") or "") if isinstance(scene, dict) else None
    recommended_take_number = _recommended_take_number(scene)
    return {
        "mode": "existing-logged-in-chrome-extension",
        "usesPaidApi": False,
        "usesRemoteDebugging": False,
        "storesCredentials": False,
        "opensEdge": False,
        "purpose": "Use a manually loaded local Chrome extension inside the operator's already signed-in Chrome/SuperGrok profile.",
        "extensionDir": str(_chrome_companion_extension_dir()),
        "profileProbe": _chrome_profile_probe_with_packet_context(handoff_dir),
        "guideUrl": _chrome_companion_guide_url(project_id, selected_scene_id),
        "recommendedTakeNumber": recommended_take_number,
        "commandUrl": _extension_command_url(project_id, selected_scene_id, recommended_take_number),
        "autostartUrl": _extension_autostart_url(project_id, selected_scene_id, "fill-prompt", recommended_take_number),
        "prepGenerateAutostartUrl": _extension_autostart_url(project_id, selected_scene_id, "prep-generate", recommended_take_number),
        "bookmarkletUrl": _bookmarklet_url(project_id, selected_scene_id, False, recommended_take_number),
        "bookmarkletGenerateUrl": _bookmarklet_url(project_id, selected_scene_id, True, recommended_take_number),
        "bookmarkletScriptUrl": _bookmarklet_script_url(project_id, selected_scene_id, False, recommended_take_number),
        "bookmarkletGenerateScriptUrl": _bookmarklet_script_url(project_id, selected_scene_id, True, recommended_take_number),
        "bookmarkletQueueUrl": _bookmarklet_queue_url(project_id),
        "bookmarkletQueueScriptUrl": _bookmarklet_queue_script_url(project_id),
        "bookmarkletImportEndpoint": _bookmarklet_import_url(project_id),
        "eventEndpoint": _extension_event_url(project_id),
        "bookmarkletEventEndpoint": _bookmarklet_event_url(project_id),
        "sceneId": selected_scene_id,
        "takeCommands": _scene_take_commands(project_id, selected_scene_id, scene) if selected_scene_id and isinstance(scene, dict) else [],
        **_extension_queue_payload(project_id, handoff_dir, manifest, assets=assets, queue_status=scene_queue),
        "operatorStillDoes": [
            "Load the unpacked extension once in the existing Chrome profile.",
            "Open Grok Imagine in that same Chrome profile.",
            "Run the extension from the toolbar, then review the prompt before generation if Grok UI changes.",
            "If the extension is not loaded, use the bookmarklet/console fallback from the guide page in the current Grok tab.",
            "Confirm or download the generated MP4; Video Studio imports from Downloads/incoming afterward.",
        ],
    }


def _extension_command_payload(
    project_id: str,
    handoff_dir: Path,
    manifest: dict,
    scene: dict,
    take_number: object = None,
) -> dict:
    scene_id = str(scene.get("sceneId") or "")
    expected_file_name = str(scene.get("expectedFileName") or f"{scene_id}.grok.mp4")
    base_prompt = str(scene.get("prompt") or "")
    selected_take = _select_take_prompt(scene, take_number)
    selected_take_number = _normalize_take_number(selected_take.get("takeNumber") if selected_take else take_number)
    decision = _scene_review_decision(manifest, scene_id)
    retry_prompt = ""
    if decision.get("accepted") is False:
        shot_bible = manifest.get("shotBible") if isinstance(manifest.get("shotBible"), dict) else {}
        retry_prompt = _scene_retry_prompt(scene, shot_bible, decision)
    prompt = retry_prompt or str((selected_take or {}).get("prompt") or base_prompt)
    prompt_quality = _scene_prompt_quality(
        prompt,
        {**scene, "grok_prompt": prompt},
        manifest.get("shotBible") if isinstance(manifest.get("shotBible"), dict) else {},
    )
    payload = {
        "ok": True,
        "projectId": str(manifest.get("projectId") or project_id),
        "sceneId": scene_id,
        "sceneNum": scene.get("sceneNum"),
        "takeNumber": selected_take_number,
        "takeLabel": str((selected_take or {}).get("label") or f"take-{selected_take_number}"),
        "takeFocus": str((selected_take or {}).get("focus") or ""),
        "takePrompts": scene.get("takePrompts") if isinstance(scene.get("takePrompts"), list) else [],
        "takeCommands": _scene_take_commands(project_id, scene_id, scene),
        "prompt": prompt,
        "basePrompt": base_prompt,
        "promptQuality": prompt_quality,
        "retryPrompt": retry_prompt,
        "isRetry": bool(retry_prompt),
        "attemptNumber": _scene_retry_attempt(decision),
        "retryReason": _scene_rejection_summary(decision) if retry_prompt else "",
        "previousReviewDecision": decision if retry_prompt else {},
        "expectedFileName": expected_file_name,
        "commandUrl": _extension_command_url(project_id, scene_id, selected_take_number),
        "autostartUrl": _extension_autostart_url(project_id, scene_id, "fill-prompt", selected_take_number),
        "prepGenerateAutostartUrl": _extension_autostart_url(project_id, scene_id, "prep-generate", selected_take_number),
        "bookmarkletUrl": _bookmarklet_url(project_id, scene_id, False, selected_take_number),
        "bookmarkletGenerateUrl": _bookmarklet_url(project_id, scene_id, True, selected_take_number),
        "bookmarkletScriptUrl": _bookmarklet_script_url(project_id, scene_id, False, selected_take_number),
        "bookmarkletGenerateScriptUrl": _bookmarklet_script_url(project_id, scene_id, True, selected_take_number),
        "bookmarkletQueueUrl": _bookmarklet_queue_url(project_id),
        "bookmarkletQueueScriptUrl": _bookmarklet_queue_script_url(project_id),
        "bookmarkletImportEndpoint": _bookmarklet_import_url(project_id),
        "grokUrl": str(manifest.get("grokUrl") or GROK_IMAGINE_URL),
        "downloadInstruction": scene.get("downloadInstruction"),
        "operatorChecklist": scene.get("operatorChecklist") or [],
        "incomingDir": manifest.get("incomingDir") or str(handoff_dir / "incoming"),
        **_download_defaults_for_manifest(manifest),
        "importEndpoint": f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/import-downloads",
        "uploadEndpoint": f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/upload-mp4",
        "watchEndpoint": f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/watch-downloads",
        "eventEndpoint": _extension_event_url(project_id),
        "bookmarkletEventEndpoint": _bookmarklet_event_url(project_id),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        **_extension_queue_payload(project_id, handoff_dir, manifest),
        "guardrails": {
            "usesPaidApi": False,
            "storesCredentials": False,
            "usesRemoteDebugging": False,
            "requiresExistingChromeProfile": True,
            "operatorOwnsLoginCaptchaPayment": True,
        },
    }
    return _attach_inline_bookmarklet_payloads(payload, project_id)


def _bookmarklet_javascript(project_id: str, command: dict, auto_generate: bool) -> str:
    command_json = json.dumps(_bookmarklet_runtime_command(command), ensure_ascii=False)
    event_url_json = json.dumps(_bookmarklet_event_url(project_id))
    auto_generate_json = "true" if auto_generate else "false"
    return f"""(() => {{
  const command = {command_json};
  const eventUrl = {event_url_json};
  const autoGenerate = {auto_generate_json};
  const promptText = String(command.prompt || "");

  function report(eventType, status, detail) {{
    try {{
      const params = new URLSearchParams({{
        operatorApproved: "true",
        sceneId: String(command.sceneId || ""),
        eventType,
        status,
        detail: String(detail || "").slice(0, 360),
        currentUrl: location.href,
        expectedFileName: String(command.expectedFileName || "")
      }});
      const image = new Image();
      image.src = `${{eventUrl}}?${{params.toString()}}&t=${{Date.now()}}`;
    }} catch (_) {{}}
  }}

  function isVisible(element) {{
    if (!element || !(element instanceof Element)) return false;
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return rect.width > 20 && rect.height > 18 && style.visibility !== "hidden" && style.display !== "none";
  }}

  function textOf(element) {{
    return [
      element.innerText,
      element.textContent,
      element.getAttribute && element.getAttribute("aria-label"),
      element.getAttribute && element.getAttribute("title")
    ].filter(Boolean).join(" ").trim();
  }}

  function queryAllSafe(selector) {{
    try {{
      return Array.from(document.querySelectorAll(selector));
    }} catch (_) {{
      return [];
    }}
  }}

  function promptCandidates() {{
    const selectors = [
      "textarea",
      "[contenteditable='true']",
      "[role='textbox']",
      "div.ProseMirror",
      "[aria-label*='prompt' i]",
      "[placeholder*='prompt' i]",
      "[aria-label*='message' i]",
      "[placeholder*='message' i]",
      "[data-testid*='composer' i]"
    ];
    const seen = new Set();
    const candidates = [];
    for (const selector of selectors) {{
      for (const element of queryAllSafe(selector)) {{
        if (seen.has(element) || !isVisible(element)) continue;
        seen.add(element);
        candidates.push(element);
      }}
    }}
    return candidates.sort((a, b) => {{
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return br.bottom - ar.bottom || br.width * br.height - ar.width * ar.height;
    }});
  }}

  function setText(element, text) {{
    element.scrollIntoView({{ block: "center", inline: "nearest" }});
    element.focus();
    const proto = element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : element instanceof HTMLInputElement
        ? HTMLInputElement.prototype
        : null;
    const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, "value") : null;
    if (descriptor && descriptor.set) {{
      descriptor.set.call(element, text);
    }} else if (element.isContentEditable || element.getAttribute("contenteditable") === "true") {{
      element.textContent = "";
      document.execCommand("insertText", false, text);
      if (!element.textContent || element.textContent.trim() !== text.trim()) {{
        element.textContent = text;
      }}
    }} else {{
      element.textContent = text;
    }}
    element.dispatchEvent(new InputEvent("input", {{ bubbles: true, inputType: "insertText", data: text }}));
    element.dispatchEvent(new Event("change", {{ bubbles: true }}));
  }}

  function clickVideoMode() {{
    const controls = Array.from(document.querySelectorAll("button, [role='button'], [aria-pressed]")).filter(isVisible);
    const target = controls.find((element) => {{
      const label = textOf(element);
      return /video|animate|motion|동영상|영상|애니/i.test(label)
        && !/download|share|삭제|delete/i.test(label);
    }});
    if (!target) return "not-found";
    target.click();
    return textOf(target).slice(0, 120) || "video-mode-control";
  }}

  function clickGenerate(promptElement) {{
    const promptRect = promptElement ? promptElement.getBoundingClientRect() : null;
    const buttons = Array.from(document.querySelectorAll("button, [role='button']")).filter((element) => {{
      if (!isVisible(element)) return false;
      if (element.disabled || element.getAttribute("aria-disabled") === "true") return false;
      return !/download|share|copy|파일|첨부|attachment|upload|mic|microphone/i.test(textOf(element));
    }});
    let best = null;
    for (const element of buttons) {{
      const label = textOf(element);
      let score = 0;
      if (/generate|create|send|submit|go|생성|만들|보내기/i.test(label)) score += 80;
      if (/arrow|up|submit/i.test(label)) score += 25;
      const rect = element.getBoundingClientRect();
      if (promptRect) {{
        const dx = Math.abs((rect.left + rect.right) / 2 - promptRect.right);
        const dy = Math.abs((rect.top + rect.bottom) / 2 - promptRect.bottom);
        score += Math.max(0, 45 - (dx + dy) / 20);
      }}
      if (!best || score > best.score) best = {{ element, score, label }};
    }}
    if (!best || best.score < 10) return {{ ok: false, detail: "generate-control-not-found" }};
    best.element.click();
    return {{ ok: true, detail: best.label || "clicked nearby generate control" }};
  }}

  async function run() {{
    report("bookmarklet-start", "started", "Video Studio Grok bookmarklet fallback started.");
    if (!/\\bgrok\\.com$/i.test(location.hostname) && !/\\.grok\\.com$/i.test(location.hostname)) {{
      alert("Open this bookmarklet on grok.com/imagine, not on the guide page.");
      report("bookmarklet-start", "failed", "not-on-grok");
      return;
    }}
    if (!promptText.trim()) {{
      alert("Video Studio did not provide a prompt for this scene.");
      report("bookmarklet-fill", "failed", "missing-prompt");
      return;
    }}
    const mode = clickVideoMode();
    await new Promise((resolve) => setTimeout(resolve, 350));
    const target = promptCandidates()[0];
    if (!target) {{
      alert("Could not find Grok prompt input. Open Imagine/video composer, then run the bookmarklet again.");
      report("bookmarklet-fill", "failed", `prompt-input-not-found; mode=${{mode}}`);
      return;
    }}
    setText(target, promptText);
    report("bookmarklet-fill", "filled", `mode=${{mode}}; expected=${{command.expectedFileName || ""}}`);
    if (!autoGenerate) {{
      alert("Video Studio filled the Grok prompt. Review it, then press Generate.");
      return;
    }}
    await new Promise((resolve) => setTimeout(resolve, 650));
    const generated = clickGenerate(target);
    report("bookmarklet-generate", generated.ok ? "clicked" : "failed", generated.detail);
    if (!generated.ok) {{
      alert("Prompt was filled, but Video Studio could not find the Generate button. Press Generate manually.");
    }}
  }}

  run().catch((error) => {{
    report("bookmarklet", "failed", error && error.message ? error.message : String(error));
    alert(`Video Studio Grok fallback failed: ${{error && error.message ? error.message : error}}`);
  }});
}})();
"""


def _bookmarklet_queue_javascript(
    project_id: str,
    command: dict,
    max_scenes: int,
    wait_seconds: int,
    *,
    inline_mode: bool = False,
) -> str:
    command_json = json.dumps(_bookmarklet_runtime_command(command), ensure_ascii=False)
    event_url_json = json.dumps(_bookmarklet_event_url(project_id))
    import_url_json = json.dumps(_bookmarklet_import_url(project_id))
    next_script_url_json = json.dumps(
        ""
        if inline_mode
        else _bookmarklet_queue_script_url(project_id, max_scenes=max_scenes, wait_seconds=wait_seconds)
    )
    inline_mode_json = "true" if inline_mode else "false"
    max_scenes_json = json.dumps(max(1, min(12, int(max_scenes or 5))))
    wait_ms_json = json.dumps(max(20, min(600, int(wait_seconds or 180))) * 1000)
    script = r"""(() => {
  const command = __COMMAND_JSON__;
  const eventUrl = __EVENT_URL_JSON__;
  const importUrl = __IMPORT_URL_JSON__;
  const nextScriptUrl = __NEXT_SCRIPT_URL_JSON__;
  const inlineMode = __INLINE_MODE_JSON__;
  const maxScenes = __MAX_SCENES_JSON__;
  const waitMs = __WAIT_MS_JSON__;
  const promptText = String(command.prompt || "");
  const sceneId = String(command.sceneId || "");
  const storageKey = `videoStudioGrokQueue:${command.projectId || ""}`;

  function report(eventType, status, detail, candidateUrl = "", meta = {}) {
    try {
      const params = new URLSearchParams({
        operatorApproved: "true",
        sceneId,
        eventType,
        status,
        detail: String(detail || "").slice(0, 360),
        currentUrl: location.href,
        candidateUrl: String(candidateUrl || "").slice(0, 260),
        expectedFileName: String(command.expectedFileName || "")
      });
      for (const [key, value] of Object.entries(meta || {})) {
        if (value !== undefined && value !== null && value !== "") {
          params.set(key, String(value).slice(0, 160));
        }
      }
      const image = new Image();
      image.src = `${eventUrl}?${params.toString()}&t=${Date.now()}`;
    } catch (_) {}
  }

  function readState() {
    try {
      const value = JSON.parse(sessionStorage.getItem(storageKey) || "{}");
      if (value && Date.now() - Number(value.startedAt || 0) < 6 * 60 * 60 * 1000) return value;
    } catch (_) {}
    return { startedAt: Date.now(), count: 0, history: [] };
  }

  function writeState(state) {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(state));
    } catch (_) {}
  }

  function resetState() {
    try {
      sessionStorage.removeItem(storageKey);
    } catch (_) {}
  }

  function isVisible(element) {
    if (!element || !(element instanceof Element)) return false;
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return rect.width > 20 && rect.height > 18 && style.visibility !== "hidden" && style.display !== "none";
  }

  function textOf(element) {
    return [
      element.innerText,
      element.textContent,
      element.getAttribute && element.getAttribute("aria-label"),
      element.getAttribute && element.getAttribute("title"),
      element.getAttribute && element.getAttribute("download"),
      element.getAttribute && element.getAttribute("href")
    ].filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
  }

  function queryAllSafe(selector) {
    try {
      return Array.from(document.querySelectorAll(selector));
    } catch (_) {
      return [];
    }
  }

  function promptCandidates() {
    const selectors = [
      "textarea",
      "[contenteditable='true']",
      "[role='textbox']",
      "div.ProseMirror",
      "[aria-label*='prompt' i]",
      "[placeholder*='prompt' i]",
      "[aria-label*='message' i]",
      "[placeholder*='message' i]",
      "[data-testid*='composer' i]"
    ];
    const seen = new Set();
    const candidates = [];
    for (const selector of selectors) {
      for (const element of queryAllSafe(selector)) {
        if (seen.has(element) || !isVisible(element)) continue;
        seen.add(element);
        candidates.push(element);
      }
    }
    return candidates.sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return br.bottom - ar.bottom || br.width * br.height - ar.width * ar.height;
    });
  }

  function setText(element, text) {
    element.scrollIntoView({ block: "center", inline: "nearest" });
    element.focus();
    const proto = element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : element instanceof HTMLInputElement
        ? HTMLInputElement.prototype
        : null;
    const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, "value") : null;
    if (descriptor && descriptor.set) {
      descriptor.set.call(element, text);
    } else if (element.isContentEditable || element.getAttribute("contenteditable") === "true") {
      element.textContent = "";
      document.execCommand("insertText", false, text);
      if (!element.textContent || element.textContent.trim() !== text.trim()) {
        element.textContent = text;
      }
    } else {
      element.textContent = text;
    }
    element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function clickVideoMode() {
    const controls = Array.from(document.querySelectorAll("button, [role='button'], [aria-pressed]")).filter(isVisible);
    const target = controls.find((element) => {
      const label = textOf(element);
      return /video|animate|motion|동영상|영상|애니/i.test(label)
        && !/download|share|삭제|delete/i.test(label);
    });
    if (!target) return "not-found";
    target.click();
    return textOf(target).slice(0, 120) || "video-mode-control";
  }

  function clickGenerate(promptElement) {
    const promptRect = promptElement ? promptElement.getBoundingClientRect() : null;
    const buttons = Array.from(document.querySelectorAll("button, [role='button']")).filter((element) => {
      if (!isVisible(element)) return false;
      if (element.disabled || element.getAttribute("aria-disabled") === "true") return false;
      return !/download|share|copy|파일|첨부|attachment|upload|mic|microphone/i.test(textOf(element));
    });
    let best = null;
    for (const element of buttons) {
      const label = textOf(element);
      let score = 0;
      if (/generate|create|send|submit|go|생성|만들|보내기/i.test(label)) score += 80;
      if (/arrow|up|submit/i.test(label)) score += 25;
      const rect = element.getBoundingClientRect();
      if (promptRect) {
        const dx = Math.abs((rect.left + rect.right) / 2 - promptRect.right);
        const dy = Math.abs((rect.top + rect.bottom) / 2 - promptRect.bottom);
        score += Math.max(0, 45 - (dx + dy) / 20);
      }
      if (!best || score > best.score) best = { element, score, label };
    }
    if (!best || best.score < 10) return { ok: false, detail: "generate-control-not-found" };
    best.element.click();
    return { ok: true, detail: best.label || "clicked nearby generate control" };
  }

  function downloadControl() {
    const controls = Array.from(document.querySelectorAll("a, button, [role='button'], [aria-label], [title]")).filter(isVisible);
    const hasVideo = document.querySelectorAll("video").length > 0;
    let best = null;
    for (const element of controls) {
      const label = textOf(element);
      const href = element.getAttribute && String(element.getAttribute("href") || "");
      let score = 0;
      if (element.hasAttribute && element.hasAttribute("download")) score += 100;
      if (/\.mp4($|\?)/i.test(href) || href.startsWith("blob:")) score += 95;
      if (/\b(download|save video|save mp4|export)\b|다운로드|동영상 저장|비디오 저장|mp4 저장|내보내기/i.test(label)) score += 90;
      if (hasVideo && /\bsave\b|저장/i.test(label)) score += 65;
      if (/login|sign in|가입|로그인|settings?|설정|upload|업로드|cookie|쿠키/i.test(label)) score -= 140;
      if (!best || score > best.score) best = { element, score, label, href };
    }
    if (best && best.score >= 80) return best;
    const video = Array.from(document.querySelectorAll("video")).find((item) => item.currentSrc || item.src);
    if (video) {
      return { element: video, score: 70, label: "visible video element", href: video.currentSrc || video.src || "" };
    }
    return null;
  }

  async function waitForDownloadControl() {
    const deadline = Date.now() + waitMs;
    while (Date.now() < deadline) {
      const candidate = downloadControl();
      if (candidate) return candidate;
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
    return null;
  }

  function safeMp4Filename(value) {
    const name = String(value || `${sceneId || "scene"}.grok.mp4`)
      .split(/[\\/]/)
      .pop()
      .replace(/[^a-zA-Z0-9._ -]+/g, "-")
      .trim() || `${sceneId || "scene"}.grok.mp4`;
    return name.toLowerCase().endsWith(".mp4") ? name : `${name}.mp4`;
  }

  function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const chunkSize = 0x8000;
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
      const chunk = bytes.subarray(offset, offset + chunkSize);
      binary += String.fromCharCode.apply(null, chunk);
    }
    return btoa(binary);
  }

  async function directImportCandidate(candidate, label) {
    if (!command.uploadEndpoint) return { ok: false, fallback: true, detail: "uploadEndpoint missing" };
    const href = String(candidate && candidate.href || "");
    if (!href || !(/\.mp4($|\?)/i.test(href) || href.startsWith("blob:"))) {
      return { ok: false, fallback: true, detail: "candidate is not fetchable video URL" };
    }
    if (candidate.sourceKind === "visible-video-fallback" && candidate.qualityFloorMet !== true) {
      return { ok: false, fallback: true, detail: "visible video is below quality floor" };
    }
    const response = await fetch(href, {
      credentials: "include",
      cache: "no-store"
    });
    if (!response.ok) {
      throw new Error(`bookmarklet direct fetch failed: HTTP ${response.status}`);
    }
    const buffer = await response.arrayBuffer();
    if (!buffer.byteLength) {
      throw new Error("bookmarklet direct fetch returned an empty file");
    }
    const sourceKind = href.startsWith("blob:")
      ? "bookmarklet-blob-direct-fetch"
      : "bookmarklet-direct-video-fetch";
    const qualityNote = href.startsWith("blob:")
      ? `${candidate.qualityNote || "visible-video-floor-met"}; bookmarklet-blob-direct-fetch; no-browser-download-prompt`
      : `${candidate.qualityNote || "original-download-source"}; bookmarklet-direct-fetch; no-browser-download-prompt`;
    const uploadResponse = await fetch(command.uploadEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operatorApproved: true,
        bookmarkletApproved: true,
        directImportProof: true,
        eventType: "bookmarklet-direct-import",
        sceneId,
        fileName: safeMp4Filename(command.expectedFileName),
        fileBase64: arrayBufferToBase64(buffer),
        candidateUrl: href,
        sourceKind,
        videoWidth: candidate.videoWidth || "",
        videoHeight: candidate.videoHeight || "",
        qualityFloorMet: candidate.qualityFloorMet === true ? "true" : candidate.qualityFloorMet === false ? "false" : "",
        qualityNote,
        detail: `direct bridge import; bytes=${buffer.byteLength}; label=${label || "queue"}`,
        overwrite: false,
        preserveCandidates: true
      })
    });
    const data = await uploadResponse.json().catch(() => ({}));
    if (!uploadResponse.ok || data.ok === false) {
      throw new Error(data.error || `bookmarklet direct import failed: HTTP ${uploadResponse.status}`);
    }
    const imported = Array.isArray(data.imported) ? data.imported.length : 0;
    const meta = {
      sourceKind,
      videoWidth: candidate.videoWidth || "",
      videoHeight: candidate.videoHeight || "",
      qualityFloorMet: candidate.qualityFloorMet === true ? "true" : candidate.qualityFloorMet === false ? "false" : "",
      qualityNote
    };
    report(
      "bookmarklet-direct-import",
      imported ? "imported" : "no-match",
      `direct bridge import; bytes=${buffer.byteLength}; imported=${imported}; label=${label || "queue"}`,
      href,
      meta
    );
    return { ok: true, data, detail: `direct-import:${imported}`, candidateUrl: href, meta };
  }

  function continueQueue(reason) {
    report("bookmarklet-queue-advance", "injecting", reason);
    if (inlineMode || !nextScriptUrl) {
      alert(`Video Studio imported ${sceneId}. Copy/run Queue inline again from the dashboard or guide for the next missing Grok scene.`);
      return;
    }
    setTimeout(() => {
      const script = document.createElement("script");
      script.src = `${nextScriptUrl}&t=${Date.now()}`;
      script.async = true;
      script.onerror = () => alert("Video Studio Grok queue could not load the next scene from the local bridge.");
      document.documentElement.appendChild(script);
    }, 1200);
  }

  async function run() {
    report("bookmarklet-queue-start", "started", "Video Studio Grok queue bookmarklet started");
    if (!/\bgrok\.com$/i.test(location.hostname) && !/\.grok\.com$/i.test(location.hostname)) {
      alert("Open this queue bookmarklet on grok.com/imagine, not on the guide page.");
      report("bookmarklet-queue-start", "failed", "not-on-grok");
      return;
    }
    if (!sceneId || !promptText.trim()) {
      alert("Video Studio did not provide a Grok scene prompt.");
      report("bookmarklet-queue-start", "failed", "missing-scene-or-prompt");
      return;
    }
    const state = readState();
    if (state.count >= maxScenes) {
      alert(`Video Studio Grok queue stopped after ${state.count} scenes. Re-run the queue bookmarklet to continue.`);
      report("bookmarklet-queue-stop", "max-scenes", `count=${state.count}; max=${maxScenes}`);
      return;
    }
    const lastScene = Array.isArray(state.history) ? state.history[state.history.length - 1] : "";
    if (lastScene === sceneId && Date.now() - Number(state.lastAt || 0) < 15000) {
      alert(`Video Studio Grok queue is still waiting for ${sceneId}. Direct-import or manually upload that MP4 before advancing.`);
      report("bookmarklet-queue-stop", "same-scene", `scene=${sceneId}`);
      return;
    }
    state.count = Number(state.count || 0) + 1;
    state.lastAt = Date.now();
    state.history = Array.isArray(state.history) ? state.history.concat(sceneId).slice(-20) : [sceneId];
    writeState(state);

    const mode = clickVideoMode();
    await new Promise((resolve) => setTimeout(resolve, 350));
    const target = promptCandidates()[0];
    if (!target) {
      alert("Could not find Grok prompt input. Open Imagine/video composer, then run the queue bookmarklet again.");
      report("bookmarklet-queue-fill", "failed", `prompt-input-not-found; mode=${mode}`);
      return;
    }
    setText(target, promptText);
    report("bookmarklet-queue-fill", "filled", `mode=${mode}; expected=${command.expectedFileName || ""}`);
    await new Promise((resolve) => setTimeout(resolve, 700));
    const generated = clickGenerate(target);
    report("bookmarklet-queue-generate", generated.ok ? "clicked" : "failed", generated.detail);
    if (!generated.ok) {
      alert("Prompt was filled, but Video Studio could not find Generate. Press Generate manually, then use direct-import or the manual batch upload path before running queue again.");
      return;
    }

    const candidate = await waitForDownloadControl();
    let importResult = null;
    try {
      const directResult = await directImportCandidate(candidate, "queue");
      if (directResult.ok) {
        importResult = directResult.data;
        report("bookmarklet-queue-direct-import", "direct-imported", directResult.detail, directResult.candidateUrl, directResult.meta);
      }
    } catch (error) {
      report("bookmarklet-queue-direct-import", "direct-import-failed", error && error.message ? error.message : String(error), candidate && candidate.href || "");
    }
    if (!importResult) {
      report("bookmarklet-queue-direct-import", "stopped-no-download-fallback", "direct import did not complete; no Download/Save/Export or anchor download was clicked", candidate && candidate.href || "");
      alert(`Grok prompt was generated for ${sceneId}, but Video Studio did not direct-import the MP4. It did not click Download/Save/Export or open Chrome's approval dialog. Use Companion direct import or the no-extension batch upload path, then run queue again.`);
      return;
    }
    if (importResult.allReady) {
      resetState();
      alert("Video Studio imported the final queued Grok MP4. Open the review packet before render.");
      report("bookmarklet-queue-complete", "all-ready", "all scenes imported");
      return;
    }
    continueQueue(`next=${importResult.nextMissingSceneId || "unknown"}`);
  }

  run().catch((error) => {
    report("bookmarklet-queue", "failed", error && error.message ? error.message : String(error));
    alert(`Video Studio Grok queue failed: ${error && error.message ? error.message : error}`);
  });
})();
"""
    return (
        script
        .replace("__COMMAND_JSON__", command_json)
        .replace("__EVENT_URL_JSON__", event_url_json)
        .replace("__IMPORT_URL_JSON__", import_url_json)
        .replace("__NEXT_SCRIPT_URL_JSON__", next_script_url_json)
        .replace("__INLINE_MODE_JSON__", inline_mode_json)
        .replace("__MAX_SCENES_JSON__", max_scenes_json)
        .replace("__WAIT_MS_JSON__", wait_ms_json)
    )


def _observed_post_download_javascript(project_id: str, command: dict, wait_seconds: int = 90) -> str:
    """Self-contained Grok post MP4 direct import for stale-extension situations."""
    command_json = json.dumps(_bookmarklet_runtime_command(command), ensure_ascii=False)
    event_url_json = json.dumps(_bookmarklet_event_url(project_id))
    wait_ms_json = json.dumps(max(20, min(300, int(wait_seconds or 90))) * 1000)
    script = r"""(() => {
  const command = __COMMAND_JSON__;
  const eventUrl = __EVENT_URL_JSON__;
  const waitMs = __WAIT_MS_JSON__;
  const sceneId = String(command.sceneId || "");
  const expectedFileName = String(command.expectedFileName || `${sceneId || "scene"}.grok.mp4`);

  function report(eventType, status, detail, candidateUrl = "", meta = {}) {
    try {
      const params = new URLSearchParams({
        operatorApproved: "true",
        sceneId,
        eventType,
        status,
        detail: String(detail || "").slice(0, 360),
        currentUrl: location.href,
        candidateUrl: String(candidateUrl || "").slice(0, 260),
        expectedFileName
      });
      for (const [key, value] of Object.entries(meta || {})) {
        if (value !== undefined && value !== null && value !== "") {
          params.set(key, String(value).slice(0, 160));
        }
      }
      const image = new Image();
      image.src = `${eventUrl}?${params.toString()}&t=${Date.now()}`;
    } catch (_) {}
  }

  function isVisible(element) {
    if (!element || !(element instanceof Element)) return false;
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return rect.width > 20 && rect.height > 18 && style.visibility !== "hidden" && style.display !== "none";
  }

  function textOf(element) {
    return [
      element.innerText,
      element.textContent,
      element.getAttribute && element.getAttribute("aria-label"),
      element.getAttribute && element.getAttribute("title"),
      element.getAttribute && element.getAttribute("download"),
      element.getAttribute && element.getAttribute("href")
    ].filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
  }

  function queryAllSafe(selector) {
    try {
      return Array.from(document.querySelectorAll(selector));
    } catch (_) {
      return [];
    }
  }

  function candidateFromVideo(video) {
    const videoWidth = Number(video.videoWidth || 0);
    const videoHeight = Number(video.videoHeight || 0);
    const qualityFloorMet = videoWidth >= 720 && videoHeight >= 1280;
    const qualityNote = qualityFloorMet
      ? `visible-video-meets-floor:${videoWidth}x${videoHeight}`
      : `visible-video-below-floor:${videoWidth}x${videoHeight}`;
    const urls = [
      video.currentSrc,
      video.src,
      ...Array.from(video.querySelectorAll("source")).map((source) => source.src)
    ].filter(Boolean);
    return urls.map((url) => {
      const isBlob = String(url).startsWith("blob:");
      return {
        element: video,
        href: url,
        label: qualityFloorMet ? "visible video fallback" : "visible video fallback proof-only",
        sourceKind: "visible-video-fallback",
        videoWidth,
        videoHeight,
        qualityFloorMet,
        qualityNote,
        score: qualityFloorMet ? (isBlob ? 58 : 54) : (isBlob ? 38 : 34)
      };
    });
  }

  function downloadCandidates() {
    const candidates = [];
    for (const anchor of queryAllSafe("a[download], a[href*='.mp4'], a[href*='video'], a[href^='blob:']")) {
      const href = String(anchor.href || anchor.getAttribute("href") || "");
      if (!href) continue;
      candidates.push({
        element: anchor,
        href,
        label: textOf(anchor) || "direct video link",
        sourceKind: anchor.hasAttribute("download") ? "download-anchor" : "direct-video-anchor",
        qualityFloorMet: null,
        qualityNote: anchor.hasAttribute("download") ? "browser-native-download-anchor" : "direct-video-anchor",
        score: anchor.hasAttribute("download") ? 120 : /\.mp4($|\?)/i.test(href) ? 108 : 72
      });
    }
    for (const video of queryAllSafe("video").filter(isVisible)) {
      candidates.push(...candidateFromVideo(video));
    }
    for (const control of queryAllSafe("button, [role='button'], [aria-label], [title]").filter(isVisible)) {
      const label = textOf(control);
      let score = 0;
      if (/\b(download|save video|save mp4|export)\b|다운로드|동영상 저장|비디오 저장|mp4 저장|내보내기/i.test(label)) score += 90;
      if (document.querySelectorAll("video").length && /\bsave\b|저장/i.test(label)) score += 64;
      if (/login|sign in|가입|로그인|settings?|설정|upload|업로드|cookie|쿠키/i.test(label)) score -= 140;
      if (score >= 64) candidates.push({
        element: control,
        href: "",
        label: label || "download control",
        sourceKind: "download-control",
        qualityFloorMet: null,
        qualityNote: "browser-native-download-control",
        score: score >= 90 ? score + 16 : score
      });
    }
    const seen = new Set();
    return candidates
      .filter((item) => item.score > 0)
      .filter((item) => {
        const key = `${item.href || ""}:${item.label || ""}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .sort((a, b) => b.score - a.score);
  }

  async function waitForCandidate() {
    const deadline = Date.now() + waitMs;
    while (Date.now() < deadline) {
      const candidate = downloadCandidates()[0];
      if (candidate) return candidate;
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
    return null;
  }

  function safeMp4Filename(value) {
    const name = String(value || expectedFileName || `${sceneId || "scene"}.grok.mp4`)
      .split(/[\\/]/)
      .pop()
      .replace(/[^a-zA-Z0-9._ -]+/g, "-")
      .trim() || `${sceneId || "scene"}.grok.mp4`;
    return name.toLowerCase().endsWith(".mp4") ? name : `${name}.mp4`;
  }

  function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const chunkSize = 0x8000;
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
      const chunk = bytes.subarray(offset, offset + chunkSize);
      binary += String.fromCharCode.apply(null, chunk);
    }
    return btoa(binary);
  }

  async function directImportCandidate(candidate, label) {
    if (!command.uploadEndpoint) return { ok: false, fallback: true, detail: "uploadEndpoint missing" };
    const href = String(candidate && candidate.href || "");
    if (!href || !(/\.mp4($|\?)/i.test(href) || href.startsWith("blob:"))) {
      return { ok: false, fallback: true, detail: "candidate is not fetchable video URL" };
    }
    if (candidate.sourceKind === "visible-video-fallback" && candidate.qualityFloorMet !== true) {
      return { ok: false, fallback: true, detail: "visible video is below quality floor" };
    }
    const response = await fetch(href, {
      credentials: "include",
      cache: "no-store"
    });
    if (!response.ok) {
      throw new Error(`bookmarklet post direct fetch failed: HTTP ${response.status}`);
    }
    const buffer = await response.arrayBuffer();
    if (!buffer.byteLength) {
      throw new Error("bookmarklet post direct fetch returned an empty file");
    }
    const sourceKind = href.startsWith("blob:")
      ? "bookmarklet-post-blob-direct-fetch"
      : "bookmarklet-post-direct-video-fetch";
    const qualityNote = href.startsWith("blob:")
      ? `${candidate.qualityNote || "visible-video-floor-met"}; bookmarklet-post-blob-direct-fetch; no-browser-download-prompt`
      : `${candidate.qualityNote || "original-download-source"}; bookmarklet-post-direct-fetch; no-browser-download-prompt`;
    const uploadResponse = await fetch(command.uploadEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operatorApproved: true,
        bookmarkletApproved: true,
        directImportProof: true,
        eventType: "bookmarklet-post-direct-import",
        sceneId,
        fileName: safeMp4Filename(expectedFileName),
        fileBase64: arrayBufferToBase64(buffer),
        candidateUrl: href,
        sourceKind,
        videoWidth: candidate.videoWidth || "",
        videoHeight: candidate.videoHeight || "",
        qualityFloorMet: candidate.qualityFloorMet === true ? "true" : candidate.qualityFloorMet === false ? "false" : "",
        qualityNote,
        detail: `direct bridge import; bytes=${buffer.byteLength}; label=${label || "post-recovery"}`,
        overwrite: false,
        preserveCandidates: true
      })
    });
    const data = await uploadResponse.json().catch(() => ({}));
    if (!uploadResponse.ok || data.ok === false) {
      throw new Error(data.error || `bookmarklet post direct import failed: HTTP ${uploadResponse.status}`);
    }
    const imported = Array.isArray(data.imported) ? data.imported.length : 0;
    const meta = {
      sourceKind,
      videoWidth: candidate.videoWidth || "",
      videoHeight: candidate.videoHeight || "",
      qualityFloorMet: candidate.qualityFloorMet === true ? "true" : candidate.qualityFloorMet === false ? "false" : "",
      qualityNote
    };
    report(
      "bookmarklet-post-direct-import",
      imported ? "imported" : "no-match",
      `direct bridge import; bytes=${buffer.byteLength}; imported=${imported}; label=${label || "post-recovery"}`,
      href,
      meta
    );
    return { ok: true, data, detail: `direct-import:${imported}`, candidateUrl: href, meta };
  }

  async function run() {
    report("bookmarklet-post-download-start", "started", "Video Studio Grok post direct import started");
    if (!/\bgrok\.com$/i.test(location.hostname) && !/\.grok\.com$/i.test(location.hostname)) {
      alert("Open this direct-import snippet on the Grok post page, not on the Video Studio dashboard.");
      report("bookmarklet-post-download-start", "failed", "not-on-grok");
      return;
    }
    const candidate = await waitForCandidate();
    let importResult = null;
    try {
      const directResult = await directImportCandidate(candidate, "post-recovery");
      if (directResult.ok) {
        importResult = directResult.data;
        report("bookmarklet-post-download", "direct-imported", directResult.detail, directResult.candidateUrl, directResult.meta);
      } else {
        report("bookmarklet-post-download", "direct-import-unavailable", directResult.detail, candidate && candidate.href || "");
      }
    } catch (error) {
      report("bookmarklet-post-download", "direct-import-failed", error && error.message ? error.message : String(error), candidate && candidate.href || "");
    }
    if (!importResult) {
      report("bookmarklet-post-download", "stopped-no-download-fallback", "direct import did not complete; no browser download or save control was clicked", candidate && candidate.href || "");
      alert(`Video Studio did not direct-import ${sceneId}. It did not click Download/Save or open Chrome's approval dialog. Use the Companion direct import path or a separate manual upload if needed.`);
      return;
    }
    alert(`Video Studio imported or detected progress for ${sceneId}. Open the review packet before render.`);
  }

  run().catch((error) => {
    report("bookmarklet-post-download", "failed", error && error.message ? error.message : String(error));
    alert(`Video Studio Grok post recovery failed: ${error && error.message ? error.message : error}`);
  });
})();
"""
    return (
        script
        .replace("__COMMAND_JSON__", command_json)
        .replace("__EVENT_URL_JSON__", event_url_json)
        .replace("__WAIT_MS_JSON__", wait_ms_json)
    )


def _normalize_open_targets(value: object, default: tuple[str, ...]) -> list[str]:
    if isinstance(value, list):
        raw_targets = value
    elif isinstance(value, str) and value.strip():
        raw_targets = re.split(r"[,\s]+", value.strip())
    else:
        raw_targets = list(default)

    targets: list[str] = []
    for item in raw_targets:
        target = str(item or "").strip().lower()
        if target == "both":
            targets.extend(["worksheet", "grok"])
        elif target in {"companion-setup", "chrome-companion", "companion-guide-and-extensions"}:
            targets.extend(["companion-guide", "chrome-extensions"])
        elif target in {"companion-guide", "chrome-extension-guide"}:
            targets.append("companion-guide")
        elif target in {"chrome-extensions", "extensions"}:
            targets.append("chrome-extensions")
        elif target in {"grok-prep-generate", "prep-generate", "grok-autostart", "chrome-prep-generate"}:
            targets.append("grok-prep-generate")
        elif target in {"observed-post", "grok-observed-post", "codex-chrome-observed-post"}:
            targets.append("observed-post")
        elif target in {"observed-post-download", "grok-observed-post-download", "post-video-download"}:
            targets.append("observed-post-download")
        elif target in {"observed-asset", "grok-observed-asset", "codex-chrome-observed-asset"}:
            targets.append("observed-asset-manual-runway")
        elif target in {"observed-asset-manual-runway", "manual-observed-asset", "grok-manual-asset-runway"}:
            targets.append("observed-asset-manual-runway")
        elif target in {"observed-asset-runway", "asset-tab-runway", "grok-asset-runway"}:
            targets.extend(["chrome-extensions", "observed-post-download", "observed-asset-manual-runway"])
        elif target in {"worksheet", "grok"}:
            targets.append(target)

    unique: list[str] = []
    for target in targets:
        if target not in unique:
            unique.append(target)
    return unique or list(default)


def _normalize_browser_preference(value: object) -> str:
    raw = str(value or "default").strip().lower()
    if raw in {"chrome", "google-chrome", "logged-in-chrome", "existing-chrome"}:
        return "chrome"
    if raw in {"edge", "msedge", "microsoft-edge"}:
        return "edge"
    return "default"


def _find_preferred_browser_executable(browser_preference: str) -> str | None:
    env_candidates = [
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    ]
    names = {
        "chrome": [("Google", "Chrome", "Application", "chrome.exe")],
        "edge": [("Microsoft", "Edge", "Application", "msedge.exe")],
    }.get(browser_preference, [])
    for root in env_candidates:
        if not root:
            continue
        for parts in names:
            path = Path(root).joinpath(*parts)
            if path.exists():
                return str(path)
    return None


def _open_handoff_url(url: str, browser_preference: str) -> tuple[bool, str, str | None]:
    if browser_preference in {"chrome", "edge"}:
        executable = _find_preferred_browser_executable(browser_preference)
        if executable:
            subprocess.Popen([executable, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, browser_preference, executable
    return bool(webbrowser.open(url, new=2)), "default", None


def _open_handoff_targets(
    project_id: str,
    manifest: dict,
    targets: list[str],
    browser_preference: object = None,
    scene_id: object = None,
) -> dict:
    normalized_browser = _normalize_browser_preference(browser_preference)
    handoff_dir = _handoff_dir(project_id)
    requested_scene = _select_grok_scene(manifest, str(scene_id or "").strip()) if scene_id else None
    prep_scene = requested_scene or _next_missing_or_rejected_scene(handoff_dir, manifest)
    prep_scene_id = str((prep_scene or {}).get("sceneId") or "").strip()
    generation_observation = _latest_codex_chrome_observation(manifest)
    observed_post_url = str((generation_observation or {}).get("postUrl") or "").strip()
    observed_asset_url = str((generation_observation or {}).get("videoUrl") or "").strip()
    observed_post_autodownload_url = _extension_observed_post_autodownload_url(project_id, prep_scene_id or None, observed_post_url)
    observed_asset_autodownload_url = _extension_asset_autodownload_url(project_id, prep_scene_id or None, observed_asset_url)
    observed_asset_manual_runway_url = _observed_asset_manual_runway_url(project_id, prep_scene_id or None)
    urls = {
        "worksheet": _worksheet_url(project_id),
        "grok": str(manifest.get("grokUrl") or GROK_IMAGINE_URL),
        "observed-post": observed_post_url,
        "observed-post-download": observed_post_autodownload_url,
        "observed-asset": observed_asset_autodownload_url,
        "observed-asset-manual-runway": observed_asset_manual_runway_url,
        "companion-guide": _chrome_companion_guide_url(project_id, prep_scene_id or None),
        "chrome-extensions": "chrome://extensions",
        "grok-prep-generate": _extension_autostart_url(project_id, prep_scene_id or None, action="prep-generate"),
    }
    opened_targets = []
    errors = []
    for target in targets:
        url = urls.get(target)
        if not url:
            continue
        try:
            opened, opened_browser, executable = _open_handoff_url(url, normalized_browser)
        except Exception as exc:
            logger.warning("Opening Grok handoff target failed: %s", exc)
            opened = False
            opened_browser = normalized_browser
            executable = None
            errors.append({"target": target, "url": url, "error": str(exc)})
        opened_targets.append({
            "target": target,
            "url": url,
            "opened": opened,
            "browserPreference": normalized_browser,
            "openedBrowser": opened_browser,
            "browserExecutable": executable,
            **({
                "sceneId": prep_scene_id,
                "requiresCompanionExtension": True,
                "extensionDir": str(_chrome_companion_extension_dir()),
            } if target == "companion-guide" else {}),
            **({
                "requiresManualLoadUnpacked": True,
                "extensionDir": str(_chrome_companion_extension_dir()),
            } if target == "chrome-extensions" else {}),
            **({
                "sceneId": prep_scene_id,
                "requiresCompanionExtension": True,
                "autostartAction": "prep-generate",
            } if target == "grok-prep-generate" else {}),
            **({
                "sceneId": prep_scene_id,
                "requiresCompanionExtension": True,
                "requiresCompanionReload": True,
                "autostartAction": "download-visible-video",
                "expectedFileName": str((generation_observation or {}).get("expectedFileName") or ""),
                "postDownloadInstruction": (
                    "Reload the Video Studio Grok Companion in chrome://extensions, then keep "
                    "the observed Grok post tab active. The companion will look for the visible "
                    "video/currentSrc or a direct MP4 URL and post eligible bytes through the "
                    "local uploadEndpoint. It should not click Grok Download or open Chrome's "
                    "save prompt on this autostart path."
                ),
            } if target == "observed-post-download" else {}),
            **({
                "sceneId": prep_scene_id,
                "requiresCompanionExtension": False,
                "requiresCompanionReload": False,
                "autostartAction": "blocked-direct-asset",
                "blockedNativePromptRisk": True,
                "expectedFileName": str((generation_observation or {}).get("expectedFileName") or ""),
                "assetDownloadInstruction": (
                    "Direct MP4 asset tabs are blocked for Codex automation because opening the "
                    "asset URL can trigger Chrome's native download prompt. Use the observed post "
                    "direct-import path or the operator-owned local manual runway instead."
                ),
            } if target == "observed-asset" else {}),
            **({
                "sceneId": prep_scene_id,
                "requiresOperatorClick": True,
                "usesPaidApi": False,
                "storesCredentials": False,
                "expectedFileName": str((generation_observation or {}).get("expectedFileName") or ""),
                "manualRunwayInstruction": (
                    "Use the local runway page only as an operator-owned manual fallback when the "
                    "Chrome companion is stale. Codex automation must not click the observed Grok "
                    "MP4 link, Download, Save, Export, or any browser approval dialog."
                ),
            } if target == "observed-asset-manual-runway" else {}),
        })
    return {
        "opened": any(item.get("opened") for item in opened_targets),
        "openedTargets": opened_targets,
        "browserPreference": normalized_browser,
        "openErrors": errors,
    }


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _find_browser_executable(candidate: object = None) -> str | None:
    raw = str(candidate or "").strip().strip('"')
    if raw and Path(raw).exists():
        return raw
    env_candidates = [
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    ]
    paths = []
    for root in env_candidates:
        if not root:
            continue
        paths.extend([
            Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ])
    for path in paths:
        if path.exists():
            return str(path)
    return None


def _default_chrome_user_data_dir(browser_executable: str) -> Path | None:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    exe_name = Path(browser_executable).name.lower()
    if exe_name == "msedge.exe":
        return Path(local_appdata) / "Microsoft" / "Edge" / "User Data"
    return Path(local_appdata) / "Google" / "Chrome" / "User Data"


def _safe_profile_directory_name(value: object) -> str:
    raw = str(value or "Default").strip().strip('"')
    if not raw or any(sep in raw for sep in ("/", "\\")) or raw in {".", ".."}:
        return "Default"
    return raw[:80]


def _cdp_json(port: int, path: str, method: str = "GET") -> object:
    url = f"http://127.0.0.1:{port}{path}"
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=4) as response:
        return json.loads(response.read().decode("utf-8"))


def _cdp_text(port: int, path: str, method: str = "GET") -> str:
    url = f"http://127.0.0.1:{port}{path}"
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=4) as response:
        return response.read().decode("utf-8", errors="replace")


def _wait_for_cdp(port: int, timeout_seconds: float = 8.0) -> object:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return _cdp_json(port, "/json/version")
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"Chrome DevTools is not reachable on 127.0.0.1:{port}: {last_error}")


def _cdp_new_target(port: int, url: str) -> dict:
    path = "/json/new?" + urllib.parse.quote(url, safe="")
    try:
        data = _cdp_json(port, path, method="PUT")
    except urllib.error.HTTPError:
        data = _cdp_json(port, path, method="GET")
    if not isinstance(data, dict):
        raise RuntimeError("Chrome DevTools did not return a target object")
    return data


def _cdp_existing_grok_target(port: int) -> dict | None:
    data = _cdp_json(port, "/json/list")
    if not isinstance(data, list):
        return None
    candidates: list[tuple[int, dict]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        target_url = str(item.get("url") or "")
        title = str(item.get("title") or "").lower()
        if item.get("type") != "page" or not item.get("webSocketDebuggerUrl"):
            continue
        score = 0
        lower_url = target_url.lower()
        if "x.com/i/oauth2/authorize" in lower_url and "accounts.x.ai" in lower_url:
            score += 340
        elif "x.com/i/flow/login" in lower_url or "twitter.com/i/flow/login" in lower_url:
            score += 320
        if target_url.startswith(GROK_IMAGINE_URL):
            score += 300
        elif "grok.com/imagine" in target_url:
            score += 260
        elif "grok.com" in target_url:
            score += 220
        if "accounts.x.ai" in target_url and ("grok" in target_url or "return_to" in target_url):
            score += 180
        if "grok" in title:
            score += 20
        if "sign in" in title or "로그인" in title:
            score += 10
        if score > 0:
            candidates.append((score, item))
    if candidates:
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return candidates[0][1]
    for item in data:
        if isinstance(item, dict) and item.get("type") == "page" and item.get("webSocketDebuggerUrl"):
            return item
    return None


def _score_grok_operator_target(item: dict) -> tuple[int, str]:
    target_url = str(item.get("url") or "")
    title = str(item.get("title") or "")
    lower_url = target_url.lower()
    lower_title = title.lower()
    if (
        "grok.com" not in lower_url
        and "accounts.x.ai" not in lower_url
        and "x.com/i/oauth2/authorize" not in lower_url
        and "x.com/i/flow/login" not in lower_url
        and "twitter.com/i/flow/login" not in lower_url
    ):
        return 0, "page"
    score = 0
    kind = "page"
    if "x.com/i/oauth2/authorize" in lower_url:
        score += 360
        kind = "x-oauth"
    elif "x.com/i/flow/login" in lower_url or "twitter.com/i/flow/login" in lower_url:
        score += 340
        kind = "x-login"
    if lower_url.startswith(GROK_IMAGINE_URL):
        score += 320
        kind = "grok-imagine"
    elif "grok.com/imagine" in lower_url:
        score += 280
        kind = "grok-imagine"
    elif "grok.com" in lower_url:
        score += 220
        kind = "grok"
    if "accounts.x.ai" in lower_url and ("grok" in lower_url or "return_to" in lower_url):
        score += 260
        if kind != "x-oauth":
            kind = "grok-auth"
    elif "accounts.x.ai" in lower_url:
        score += 180
        if kind != "x-oauth":
            kind = "xai-auth"
    if "sign in" in lower_title or "로그인" in lower_title:
        score += 30
        if kind == "page":
            kind = "grok-auth"
    if "imagine" in lower_title:
        score += 20
    if "grok" in lower_title:
        score += 20
    return score, kind


def _cdp_grok_operator_targets(port: int, prefer_auth: bool = False, limit: int = 8) -> dict:
    data = _cdp_json(port, "/json/list")
    if not isinstance(data, list):
        raise RuntimeError("Chrome DevTools target list is not an array")
    targets: list[dict] = []
    page_count = 0
    grok_tab_count = 0
    sign_in_tab_count = 0
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "page":
            continue
        page_count += 1
        target_url = str(item.get("url") or "")
        lower_url = target_url.lower()
        if "grok.com" in lower_url:
            grok_tab_count += 1
        if "accounts.x.ai" in lower_url or "x.com/i/oauth2/authorize" in lower_url or "x.com/i/flow/login" in lower_url or "twitter.com/i/flow/login" in lower_url:
            sign_in_tab_count += 1
        score, kind = _score_grok_operator_target(item)
        if score <= 0:
            continue
        if prefer_auth and kind in {"grok-auth", "xai-auth", "x-oauth", "x-login"}:
            score += 500
        target_id = str(item.get("id") or "")
        targets.append({
            "targetId": target_id,
            "title": str(item.get("title") or ""),
            "url": target_url,
            "kind": kind,
            "score": score,
        })
    targets.sort(key=lambda target: int(target.get("score") or 0), reverse=True)
    best = targets[0] if targets else None
    return {
        "remoteDebuggingPort": port,
        "pageCount": page_count,
        "grokTabCount": grok_tab_count,
        "signInTabCount": sign_in_tab_count,
        "targets": targets[:max(1, min(100, int(limit)))],
        "bestTarget": best,
        "hasOperatorTarget": best is not None,
    }


def _cdp_activate_target(port: int, target_id: str) -> str:
    if not target_id:
        raise RuntimeError("No Chrome DevTools target id is available to activate")
    return _cdp_text(port, f"/json/activate/{urllib.parse.quote(target_id, safe='')}")


def _cdp_close_target(port: int, target_id: str) -> str:
    if not target_id:
        raise RuntimeError("No Chrome DevTools target id is available to close")
    return _cdp_text(port, f"/json/close/{urllib.parse.quote(target_id, safe='')}")


class _CdpWebSocket:
    def __init__(self, ws_url: str):
        parsed = urllib.parse.urlparse(ws_url)
        if parsed.scheme != "ws":
            raise RuntimeError("Only local ws:// Chrome DevTools URLs are supported")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        self._socket = socket.create_connection((host, port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._socket.sendall(request.encode("ascii"))
        response = self._read_until(b"\r\n\r\n")
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError("Chrome DevTools websocket upgrade failed")
        self._next_id = 0

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass

    def call(self, method: str, params: dict | None = None, timeout: float = 8.0) -> dict:
        self._next_id += 1
        call_id = self._next_id
        self._send_json({"id": call_id, "method": method, "params": params or {}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = self._recv_json(deadline - time.time())
            if message.get("id") == call_id:
                if "error" in message:
                    raise RuntimeError(json.dumps(message["error"], ensure_ascii=True))
                return message
        raise RuntimeError(f"Chrome DevTools call timed out: {method}")

    def _read_exact(self, count: int) -> bytes:
        chunks = []
        remaining = count
        while remaining > 0:
            chunk = self._socket.recv(remaining)
            if not chunk:
                raise RuntimeError("Chrome DevTools websocket closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_until(self, marker: bytes) -> bytes:
        data = b""
        while marker not in data:
            chunk = self._socket.recv(4096)
            if not chunk:
                raise RuntimeError("Chrome DevTools websocket closed during handshake")
            data += chunk
        return data

    def _send_json(self, payload: dict) -> None:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        header = bytearray([0x81])
        length = len(raw)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(raw[index] ^ mask[index % 4] for index in range(length))
        self._socket.sendall(bytes(header) + mask + masked)

    def _recv_json(self, timeout: float) -> dict:
        self._socket.settimeout(max(0.1, timeout))
        while True:
            first, second = self._read_exact(2)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length) if length else b""
            if masked:
                payload = bytes(payload[index] ^ mask[index % 4] for index in range(length))
            if opcode == 8:
                raise RuntimeError("Chrome DevTools websocket closed")
            if opcode in {1, 0}:
                return json.loads(payload.decode("utf-8"))


def _prompt_injection_script(prompt: str) -> str:
    prompt_json = json.dumps(prompt)
    return f"""
(async () => {{
  const prompt = {prompt_json};
  const visible = (el) => {{
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 20 && rect.height > 20;
  }};
  const collect = (root, out = []) => {{
    if (!root || !root.querySelectorAll) return out;
    root.querySelectorAll(
      'textarea, input[type="text"], input:not([type]), [contenteditable="true"], [contenteditable=""], [role="textbox"]'
    ).forEach((el) => out.push(el));
    root.querySelectorAll('*').forEach((el) => {{
      if (el.shadowRoot) collect(el.shadowRoot, out);
    }});
    return out;
  }};
  const findInput = () => {{
    const candidates = collect(document).filter((el) => visible(el) && !el.disabled && !el.readOnly);
    return candidates.find((el) => (el.getAttribute('aria-label') || '').toLowerCase().includes('prompt'))
      || candidates.find((el) => (el.getAttribute('placeholder') || '').toLowerCase().includes('prompt'))
      || candidates.find((el) => el.tagName === 'TEXTAREA')
      || candidates.find((el) => el.isContentEditable || el.getAttribute('role') === 'textbox')
      || candidates[0]
      || null;
  }};
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  let element = null;
  const deadline = Date.now() + 30000;
  while (!element && Date.now() < deadline) {{
    element = findInput();
    if (!element) await wait(500);
  }}
  if (!element) {{
    return {{
      ok: false,
      error: 'No editable Grok prompt input found after waiting',
      title: document.title,
      url: location.href,
      bodyText: (document.body && document.body.innerText || '').slice(0, 500)
    }};
  }}
  element.focus();
  element.click();
  if (element.isContentEditable || element.getAttribute('contenteditable') === 'true') {{
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, prompt);
  }} else {{
    const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value');
    if (descriptor && descriptor.set) {{
      descriptor.set.call(element, prompt);
    }} else {{
      element.value = prompt;
    }}
    element.dispatchEvent(new Event('input', {{ bubbles: true }}));
    element.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }}
  return {{
    ok: true,
    tagName: element.tagName,
    role: element.getAttribute('role') || '',
    placeholder: element.getAttribute('placeholder') || '',
    ariaLabel: element.getAttribute('aria-label') || '',
    contentEditable: Boolean(element.isContentEditable),
    promptLength: prompt.length,
    title: document.title,
    url: location.href
  }};
}})();
"""


def _generation_click_script() -> str:
    return """
(async () => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 16 && rect.height > 16;
  };
  const collect = (root, out = []) => {
    if (!root || !root.querySelectorAll) return out;
    root.querySelectorAll('button, [role="button"], [aria-label], [title]').forEach((el) => out.push(el));
    root.querySelectorAll('*').forEach((el) => {
      if (el.shadowRoot) collect(el.shadowRoot, out);
    });
    return out;
  };
  const labelFor = (el) => [
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || '',
    el.getAttribute('data-testid') || '',
    el.textContent || ''
  ].join(' ').replace(/\\s+/g, ' ').trim();
  const candidates = collect(document).filter((el) => visible(el) && !el.disabled);
  const candidateLabels = candidates.map((el) => labelFor(el)).filter(Boolean);
  const pageText = [
    document.title || '',
    document.body && document.body.innerText || '',
    candidateLabels.join(' ')
  ].join(' ').toLowerCase();
  const authRequired = /(login|log in|sign in|sign up|로그인|가입하기)/.test(pageText);
  const cookieChoiceRequired = /(cookie|cookies|쿠키|모든 쿠키 허용|모두 거부)/.test(pageText);
  const scored = candidates.map((el) => {
    const label = labelFor(el).toLowerCase();
    let score = 0;
    if (/\\b(generate|create|send|submit)\\b|동영상 만들기|비디오 만들기|영상 만들기|생성하기|만들기|제출/.test(label)) score += 80;
    if (/prompt|imagine|video/.test(label)) score += 15;
    if (/동영상|비디오|영상/.test(label)) score += 15;
    if (/로그인|가입하기|settings?|설정|업로드|upload|cookie|쿠키|허용|거부|canvas/.test(label)) score -= 120;
    if (el.tagName === 'BUTTON') score += 5;
    return { el, label: labelFor(el), score };
  }).filter((item) => item.score >= 80).sort((a, b) => b.score - a.score);
  const best = scored[0];
  if (!best) {
    return {
      ok: true,
      clicked: false,
      reason: 'No explicit Generate/Send button found',
      authRequired,
      cookieChoiceRequired,
      title: document.title,
      url: location.href,
      candidateLabels: candidateLabels.slice(0, 12)
    };
  }
  best.el.click();
  return {
    ok: true,
    clicked: true,
    action: 'button-click',
    label: best.label.slice(0, 160),
    authRequired,
    cookieChoiceRequired,
    title: document.title,
    url: location.href
  };
})();
"""


def _download_click_script(timeout_seconds: float) -> str:
    timeout_ms = int(max(0.0, timeout_seconds) * 1000)
    script = """
(() => ({
    ok: false,
    clicked: false,
    action: 'download-click-blocked',
    reason: 'native-download-prompt-disabled',
    detail: '__BLOCKER__',
    timeoutMs: __TIMEOUT_MS__,
    authRequired: false,
    cookieChoiceRequired: false,
    title: document.title,
    url: location.href
  }
))();
"""
    return (
        script
        .replace("__TIMEOUT_MS__", json.dumps(timeout_ms))
        .replace("__BLOCKER__", json.dumps(_NATIVE_GROK_DOWNLOAD_PROMPT_BLOCKER)[1:-1])
    )


def _browser_preflight_script() -> str:
    return """
(async () => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 16 && rect.height > 16;
  };
  const collect = (root, out = []) => {
    if (!root || !root.querySelectorAll) return out;
    root.querySelectorAll('textarea, input, a, button, [role="button"], [role="textbox"], [contenteditable="true"], [aria-label], [title]').forEach((el) => out.push(el));
    root.querySelectorAll('*').forEach((el) => {
      if (el.shadowRoot) collect(el.shadowRoot, out);
    });
    return out;
  };
  const labelFor = (el) => [
    el.getAttribute('aria-label') || '',
    el.getAttribute('placeholder') || '',
    el.getAttribute('title') || '',
    el.getAttribute('download') || '',
    el.getAttribute('href') || '',
    el.getAttribute('data-testid') || '',
    el.textContent || ''
  ].join(' ').replace(/\\s+/g, ' ').trim();
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const hasUsablePage = () => {
    const href = location.href || '';
    const bodyText = document.body && document.body.innerText || '';
    return href !== 'about:blank' && (bodyText.trim().length > 0 || collect(document).some((el) => visible(el)));
  };
  const deadline = Date.now() + 8000;
  while (!hasUsablePage() && Date.now() < deadline) {
    await wait(250);
  }
  const candidates = collect(document).filter((el) => visible(el) && !el.disabled);
  const labels = candidates.map((el) => labelFor(el)).filter(Boolean);
  const pageText = [
    document.title || '',
    document.body && document.body.innerText || '',
    labels.join(' ')
  ].join(' ').toLowerCase();
  const authRequired = /(login|log in|sign in|sign up|로그인|가입하기)/.test(pageText);
  const cookieChoiceRequired = /(cookie|cookies|쿠키|모든 쿠키 허용|모두 거부)/.test(pageText);
  const promptInputReady = candidates.some((el) => {
    const label = labelFor(el).toLowerCase();
    return (el.tagName === 'TEXTAREA' || el.isContentEditable || el.getAttribute('role') === 'textbox')
      && !/로그인|가입하기|cookie|쿠키/.test(label);
  });
  const generateControlReady = labels.some((label) => /\\b(generate|create|send|submit)\\b|동영상 만들기|비디오 만들기|영상 만들기|생성하기|만들기|제출/.test(label.toLowerCase()));
  const downloadControlReady = labels.some((label) => /\\b(download|save video|save mp4|export)\\b|다운로드|동영상 저장|비디오 저장|mp4 저장|내보내기/.test(label.toLowerCase()));
  return {
    ok: true,
    authRequired,
    cookieChoiceRequired,
    promptInputReady,
    generateControlReady,
    downloadControlReady,
    videoElementCount: document.querySelectorAll('video').length,
    title: document.title,
    url: location.href,
    candidateLabels: labels.slice(0, 16)
  };
})();
"""


def _auth_kickoff_script() -> str:
    return """
(() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 16 && rect.height > 16;
  };
  const collect = (root, out = []) => {
    if (!root || !root.querySelectorAll) return out;
    root.querySelectorAll('a, button, [role="button"], [aria-label], [title]').forEach((el) => out.push(el));
    root.querySelectorAll('*').forEach((el) => {
      if (el.shadowRoot) collect(el.shadowRoot, out);
    });
    return out;
  };
  const labelFor = (el) => [
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || '',
    el.getAttribute('href') || '',
    el.getAttribute('data-testid') || '',
    el.textContent || ''
  ].join(' ').replace(/\\s+/g, ' ').trim();
  const candidates = collect(document).filter((el) => visible(el) && !el.disabled);
  const loginCandidates = candidates.map((el) => {
    const label = labelFor(el).toLowerCase();
    let score = 0;
    if (/\\b(log in|login|sign in)\\b|로그인/.test(label)) score += 100;
    if (/sign up|signup|가입하기/.test(label)) score -= 150;
    if (/cookie|쿠키|settings?|설정|upload|업로드/.test(label)) score -= 100;
    return { el, label: labelFor(el), score };
  }).filter((item) => item.score > 0).sort((a, b) => b.score - a.score);
  const best = loginCandidates[0];
  if (!best) {
    return {
      ok: true,
      clicked: false,
      reason: 'No explicit login control found',
      title: document.title,
      url: location.href,
      candidateLabels: candidates.map((el) => labelFor(el)).filter(Boolean).slice(0, 12)
    };
  }
  best.el.click();
  return {
    ok: true,
    clicked: true,
    action: 'auth-login-click',
    label: best.label.slice(0, 160),
    title: document.title,
    url: location.href
  };
})();
"""


def _auth_provider_kickoff_script(provider_preference: object = "x") -> str:
    provider = _normalize_auth_provider_preference(provider_preference, default="x")
    provider_json = json.dumps(provider, ensure_ascii=True)
    return f"""
(() => {{
  const preferredProvider = {provider_json};
  const visible = (el) => {{
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 16 && rect.height > 16;
  }};
  const collect = (root, out = []) => {{
    if (!root || !root.querySelectorAll) return out;
    root.querySelectorAll('a, button, [role="button"], [aria-label], [title]').forEach((el) => out.push(el));
    root.querySelectorAll('*').forEach((el) => {{
      if (el.shadowRoot) collect(el.shadowRoot, out);
    }});
    return out;
  }};
  const labelFor = (el) => [
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || '',
    el.getAttribute('href') || '',
    el.getAttribute('data-testid') || '',
    el.textContent || ''
  ].join(' ').replace(/\\s+/g, ' ').trim();
  const providerScore = (label, href) => {{
    if (preferredProvider === 'manual') return 0;
    if (preferredProvider === 'google') {{
      return /\\bgoogle\\b|구글/.test(label) || href.includes('google.com') ? 260 : 0;
    }}
    if (preferredProvider === 'email') {{
      return /\\bemail\\b|e-mail|mail|메일|password|passkey/.test(label) ? 240 : 0;
    }}
    if (preferredProvider === 'apple') {{
      return /\\bapple\\b|애플/.test(label) || href.includes('apple.com') ? 240 : 0;
    }}
    if (/\\b(log in|login|sign in|continue) with\\s*(x|\\uD835\\uDD4F)(\\b|\\s|$)/.test(label)) return 260;
    if (/\\btwitter\\b/.test(label) || href.includes('x.com') || href.includes('twitter.com')) return 200;
    return 0;
  }};
  const candidates = collect(document).filter((el) => visible(el) && !el.disabled);
  if (preferredProvider === 'manual') {{
    return {{
      ok: true,
      clicked: false,
      reason: 'Manual sign-in provider selection requested',
      action: 'auth-provider-click',
      provider: preferredProvider,
      title: document.title,
      url: location.href,
      candidateLabels: candidates.map((el) => labelFor(el)).filter(Boolean).slice(0, 12)
    }};
  }}
  const providerCandidates = candidates.map((el) => {{
    const label = labelFor(el).toLowerCase();
    const href = (el.getAttribute('href') || '').toLowerCase();
    let score = providerScore(label, href);
    if (!score) score -= 240;
    if (/sign up|signup|가입/.test(label)) score -= 120;
    if (/cookie|쿠키|settings?|설정|upload|업로드/.test(label)) score -= 120;
    return {{ el, label: labelFor(el), score }};
  }}).filter((item) => item.score > 0).sort((a, b) => b.score - a.score);
  const best = providerCandidates[0];
  if (!best) {{
    return {{
      ok: true,
      clicked: false,
      reason: `No approved ${{preferredProvider}} sign-in provider control found`,
      action: 'auth-provider-click',
      provider: preferredProvider,
      title: document.title,
      url: location.href,
      candidateLabels: candidates.map((el) => labelFor(el)).filter(Boolean).slice(0, 12)
    }};
  }}
  best.el.click();
  return {{
    ok: true,
    clicked: true,
    action: 'auth-provider-click',
    provider: preferredProvider,
    label: best.label.slice(0, 160),
    title: document.title,
    url: location.href
  }};
}})();
"""


def _cookie_reject_script() -> str:
    return """
(() => {
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 16 && rect.height > 16;
  };
  const collect = (root, out = []) => {
    if (!root || !root.querySelectorAll) return out;
    root.querySelectorAll('button, [role="button"], [aria-label], [title]').forEach((el) => out.push(el));
    root.querySelectorAll('*').forEach((el) => {
      if (el.shadowRoot) collect(el.shadowRoot, out);
    });
    return out;
  };
  const labelFor = (el) => [
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || '',
    el.getAttribute('data-testid') || '',
    el.textContent || ''
  ].join(' ').replace(/\\s+/g, ' ').trim();
  const candidates = collect(document).filter((el) => visible(el) && !el.disabled);
  const rejectCandidates = candidates.map((el) => {
    const label = labelFor(el).toLowerCase();
    let score = 0;
    if (/reject all|decline all|deny all|necessary only|필수.*허용|모두 거부|전체 거부/.test(label)) score += 120;
    if (/\\breject\\b|\\bdecline\\b|\\bdeny\\b|거부/.test(label)) score += 80;
    if (/accept all|allow all|agree|동의|모든 쿠키 허용|모두 허용|허용/.test(label)) score -= 200;
    if (/settings?|설정|preferences?|기본 설정/.test(label)) score -= 100;
    return { el, label: labelFor(el), score };
  }).filter((item) => item.score > 0).sort((a, b) => b.score - a.score);
  const best = rejectCandidates[0];
  if (!best) {
    return {
      ok: true,
      clicked: false,
      reason: 'No reject/decline cookie control found',
      action: 'cookie-reject-click',
      title: document.title,
      url: location.href,
      candidateLabels: candidates.map((el) => labelFor(el)).filter(Boolean).slice(0, 12)
    };
  }
  best.el.click();
  return {
    ok: true,
    clicked: true,
    action: 'cookie-reject-click',
    label: best.label.slice(0, 160),
    title: document.title,
    url: location.href
  };
})();
"""


def _runtime_evaluate_value(evaluation: dict) -> dict:
    value = (((evaluation.get("result") or {}).get("result") or {}).get("value") or {})
    return value if isinstance(value, dict) else {"ok": False, "value": value}


def _evaluate_browser_preflight(ws: "_CdpWebSocket") -> dict:
    evaluation = None
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            evaluation = ws.call("Runtime.evaluate", {
                "expression": _browser_preflight_script(),
                "awaitPromise": True,
                "returnByValue": True,
            }, timeout=10)
            break
        except RuntimeError as exc:
            last_error = exc
            if "Execution context was destroyed" not in str(exc) and "Cannot find context" not in str(exc):
                raise
            time.sleep(1.0)
            try:
                ws.call("Runtime.enable", timeout=3)
                ws.call("Page.bringToFront", timeout=3)
            except Exception:
                pass
    if evaluation is None:
        raise RuntimeError(str(last_error or "Grok browser preflight evaluate failed"))
    return _runtime_evaluate_value(evaluation)


def _operator_auth_stage_from_action(action: dict | None) -> dict:
    if not isinstance(action, dict):
        return {}
    url = str(action.get("url") or "").lower()
    labels = " ".join(str(item or "") for item in action.get("candidateLabels") or []).lower()
    if "x.com/i/oauth2/authorize" in url:
        return {
            "operatorAuthStage": "x-oauth-consent",
            "operatorAuthStageLabel": "X OAuth consent/login",
            "operatorNextAction": "Use the focused X OAuth screen to log in or authorize xAI/Grok access; Video Studio will resume automatically.",
        }
    if "x.com/i/flow/login" in url or "twitter.com/i/flow/login" in url:
        return {
            "operatorAuthStage": "x-login",
            "operatorAuthStageLabel": "X login",
            "operatorNextAction": "Complete X login in the focused browser tab; Video Studio will resume automatically after xAI redirects back to Grok.",
        }
    if "accounts.x.ai" in url and "/sign-in" in url:
        if "login with" in labels or "oauth" in labels:
            return {
                "operatorAuthStage": "xai-sign-in",
                "operatorAuthStageLabel": "xAI sign-in method",
                "operatorNextAction": "Choose a sign-in method in the focused xAI tab, then complete any X/OAuth/captcha steps; Video Studio will resume automatically.",
            }
        return {
            "operatorAuthStage": "xai-sign-in",
            "operatorAuthStageLabel": "xAI sign-in",
            "operatorNextAction": "Complete xAI/Grok sign-in in the focused tab; Video Studio will resume automatically.",
        }
    if "grok.com/imagine" in url:
        return {
            "operatorAuthStage": "grok-imagine-login",
            "operatorAuthStageLabel": "Grok Imagine login gate",
            "operatorNextAction": "Click the Grok login control in the focused tab and complete the sign-in flow; Video Studio will resume automatically.",
        }
    if action.get("authRequired"):
        return {
            "operatorAuthStage": "auth-required",
            "operatorAuthStageLabel": "browser login gate",
            "operatorNextAction": "Complete the login, captcha, payment, or safety step in the focused browser tab; Video Studio will resume automatically.",
        }
    return {}


def _browser_state_from_actions(*actions: dict | None) -> dict:
    auth_required = any(bool(action and action.get("authRequired")) for action in actions)
    cookie_choice_required = any(bool(action and action.get("cookieChoiceRequired")) for action in actions)
    if auth_required and cookie_choice_required:
        blocker = "grok-auth-and-cookie"
    elif auth_required:
        blocker = "grok-auth-required"
    elif cookie_choice_required:
        blocker = "grok-cookie-choice-required"
    else:
        blocker = None
    auth_stage: dict = {}
    for action in actions:
        candidate = _operator_auth_stage_from_action(action)
        if candidate:
            auth_stage = candidate
            break
    return {
        "authRequired": auth_required,
        "cookieChoiceRequired": cookie_choice_required,
        "browserBlocker": blocker,
        "requiresOperatorAction": bool(blocker),
        **auth_stage,
    }


def _wait_for_operator_ready(ws: "_CdpWebSocket", data: dict) -> dict:
    timeout_seconds = _bounded_float(
        data.get("operatorReadyTimeoutSeconds"),
        default=600.0,
        minimum=0.0,
        maximum=MAX_OPERATOR_READY_WAIT_SECONDS,
    )
    poll_interval_seconds = _bounded_float(
        data.get("operatorReadyPollIntervalSeconds"),
        default=2.0,
        minimum=0.1,
        maximum=10.0,
    )
    started = time.monotonic()
    deadline = started + timeout_seconds
    attempts = 0
    auth_kickoff: dict | None = None
    auth_provider_kickoff: dict | None = None
    cookie_choice: dict | None = None
    auth_provider_preference = _normalize_auth_provider_preference(data.get("authProviderPreference"), default="x")

    last_preflight: dict = {}
    last_state: dict = _browser_state_from_actions()
    progress_callback = data.get("_operatorReadyProgress")
    should_cancel = data.get("_operatorReadyShouldCancel")

    def _emit_progress(
        *,
        prompt_ready: bool,
        generate_ready: bool,
        timed_out: bool = False,
        ready: bool = False,
    ) -> None:
        if not callable(progress_callback):
            return
        try:
            progress_callback({
                "ready": ready,
                "timedOut": timed_out,
                "attempts": attempts,
                "elapsedSeconds": round(time.monotonic() - started, 3),
                "timeoutSeconds": timeout_seconds,
                "pollIntervalSeconds": poll_interval_seconds,
                "promptInputReady": prompt_ready,
                "generateControlReady": generate_ready,
                "preflight": last_preflight,
                "authKickoff": auth_kickoff,
                "authProviderKickoff": auth_provider_kickoff,
                "authProviderPreference": auth_provider_preference,
                "cookieChoice": cookie_choice,
                **last_state,
            })
        except Exception as exc:
            logger.debug("Grok operator-ready progress callback failed: %s", exc)

    while True:
        if callable(should_cancel):
            try:
                if should_cancel():
                    return {
                        "ready": False,
                        "timedOut": False,
                        "cancelled": True,
                        "cancelReason": "Superseded by a fresh operator-approved Grok background run.",
                        "attempts": attempts,
                        "elapsedSeconds": round(time.monotonic() - started, 3),
                        "timeoutSeconds": timeout_seconds,
                        "pollIntervalSeconds": poll_interval_seconds,
                        "promptInputReady": False,
                        "generateControlReady": False,
                        "preflight": last_preflight,
                        "authKickoff": auth_kickoff,
                        "authProviderKickoff": auth_provider_kickoff,
                        "authProviderPreference": auth_provider_preference,
                        "cookieChoice": cookie_choice,
                        "browserBlocker": "grok-background-superseded",
                        "requiresOperatorAction": False,
                    }
            except Exception as exc:
                logger.debug("Grok operator-ready cancellation check failed: %s", exc)
        attempts += 1
        last_preflight = _evaluate_browser_preflight(ws)
        last_state = _browser_state_from_actions(last_preflight)
        if (
            auth_provider_kickoff is None
            and data.get("authProviderKickoffApproved") is True
            and last_state.get("operatorAuthStage") == "xai-sign-in"
        ):
            try:
                auth_provider_kickoff = _runtime_evaluate_value(ws.call("Runtime.evaluate", {
                    "expression": _auth_provider_kickoff_script(auth_provider_preference),
                    "awaitPromise": True,
                    "returnByValue": True,
                }, timeout=5))
            except Exception as exc:
                auth_provider_kickoff = {"ok": False, "clicked": False, "error": str(exc)}
            if auth_provider_kickoff.get("clicked"):
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
                continue
        if (
            auth_kickoff is None
            and data.get("authKickoffApproved") is True
            and last_state.get("authRequired")
            and last_state.get("operatorAuthStage") != "xai-sign-in"
        ):
            try:
                auth_kickoff = _runtime_evaluate_value(ws.call("Runtime.evaluate", {
                    "expression": _auth_kickoff_script(),
                    "awaitPromise": True,
                    "returnByValue": True,
                }, timeout=5))
            except Exception as exc:
                auth_kickoff = {"ok": False, "clicked": False, "error": str(exc)}
            if auth_kickoff.get("clicked"):
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
                continue
        if (
            cookie_choice is None
            and data.get("cookieRejectApproved") is True
            and last_state.get("cookieChoiceRequired")
        ):
            try:
                cookie_choice = _runtime_evaluate_value(ws.call("Runtime.evaluate", {
                    "expression": _cookie_reject_script(),
                    "awaitPromise": True,
                    "returnByValue": True,
                }, timeout=5))
            except Exception as exc:
                cookie_choice = {"ok": False, "clicked": False, "error": str(exc)}
            if cookie_choice.get("clicked"):
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
                continue
        prompt_ready = bool(last_preflight.get("promptInputReady"))
        generate_ready = bool(last_preflight.get("generateControlReady"))
        ready = prompt_ready and not last_state["requiresOperatorAction"]
        _emit_progress(prompt_ready=prompt_ready, generate_ready=generate_ready, ready=ready)
        if ready:
            return {
                "ready": True,
                "timedOut": False,
                "attempts": attempts,
                "elapsedSeconds": round(time.monotonic() - started, 3),
                "timeoutSeconds": timeout_seconds,
                "pollIntervalSeconds": poll_interval_seconds,
                "promptInputReady": prompt_ready,
                "generateControlReady": generate_ready,
                "preflight": last_preflight,
                "authKickoff": auth_kickoff,
                "authProviderKickoff": auth_provider_kickoff,
                "authProviderPreference": auth_provider_preference,
                "cookieChoice": cookie_choice,
                **last_state,
            }
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _emit_progress(prompt_ready=prompt_ready, generate_ready=generate_ready, timed_out=True)
            return {
                "ready": False,
                "timedOut": True,
                "attempts": attempts,
                "elapsedSeconds": round(time.monotonic() - started, 3),
                "timeoutSeconds": timeout_seconds,
                "pollIntervalSeconds": poll_interval_seconds,
                "promptInputReady": prompt_ready,
                "generateControlReady": generate_ready,
                "preflight": last_preflight,
                "authKickoff": auth_kickoff,
                "authProviderKickoff": auth_provider_kickoff,
                "authProviderPreference": auth_provider_preference,
                "cookieChoice": cookie_choice,
                **last_state,
            }
        time.sleep(min(poll_interval_seconds, remaining))


def _manual_download_instruction(scene: dict, download_dir: Path | None) -> str | None:
    if download_dir is None:
        return None
    expected_file_name = str(scene.get("expectedFileName") or f"{scene.get('sceneId')}.grok.mp4")
    return (
        f"If Grok shows the clip but the download button is not detected, "
        f"manually save the MP4 as {expected_file_name} in {download_dir}; "
        "the approved watcher/importer will attach it to this scene."
    )


def _default_download_dir() -> dict:
    candidate = Path.home() / "Downloads"
    return {
        "defaultDownloadDir": str(candidate),
        "defaultDownloadDirExists": candidate.is_dir(),
    }


def _download_defaults_for_manifest(manifest: dict) -> dict:
    defaults = _default_download_dir()
    value = str(manifest.get("defaultDownloadDir") or "").strip()
    if value:
        defaults["defaultDownloadDir"] = value
        defaults["defaultDownloadDirExists"] = Path(value).is_dir()
    return defaults


def _dispatch_enter_key(ws: "_CdpWebSocket") -> None:
    ws.call("Input.dispatchKeyEvent", {
        "type": "keyDown",
        "key": "Enter",
        "code": "Enter",
        "windowsVirtualKeyCode": 13,
        "nativeVirtualKeyCode": 13,
    }, timeout=3)
    ws.call("Input.dispatchKeyEvent", {
        "type": "keyUp",
        "key": "Enter",
        "code": "Enter",
        "windowsVirtualKeyCode": 13,
        "nativeVirtualKeyCode": 13,
    }, timeout=3)


def _launch_cdp_browser(data: dict, handoff_dir: Path, port: int) -> dict:
    if data.get("launchBrowserApproved") is not True:
        return {"launched": False}
    if data.get("profileApproved") is not True:
        raise RuntimeError("profileApproved=true is required before launching a remote-debugging browser profile")
    browser_executable = _find_browser_executable(data.get("browserExecutable"))
    if not browser_executable:
        raise RuntimeError("Chrome or Edge executable was not found; provide browserExecutable")
    use_default_profile = data.get("useDefaultChromeProfile") is True
    profile_directory = _safe_profile_directory_name(data.get("browserProfileDirectory"))
    if use_default_profile:
        raise RuntimeError(CHROME_DEFAULT_PROFILE_CDP_GUIDANCE)
    else:
        raw_profile_dir = str(data.get("userDataDir") or "").strip().strip('"')
        profile_dir = Path(raw_profile_dir) if raw_profile_dir else handoff_dir / "browser-profile"
        if not profile_dir.is_absolute():
            profile_dir = handoff_dir / profile_dir
        profile_dir.mkdir(parents=True, exist_ok=True)
    args = [
        browser_executable,
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        f"--profile-directory={profile_directory}",
        "--no-first-run",
        "--new-window",
        GROK_IMAGINE_URL,
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.0)
    return {
        "launched": True,
        "browserExecutable": browser_executable,
        "userDataDir": str(profile_dir),
        "useDefaultChromeProfile": use_default_profile,
        "browserProfileMode": "isolated-handoff-profile",
        "browserProfileDirectory": profile_directory,
    }


def _run_grok_browser_automation(handoff_dir: Path, manifest: dict, scene: dict, data: dict, download_dir: Path | None) -> dict:
    port = _bounded_int(data.get("remoteDebuggingPort"), default=9222, minimum=9000, maximum=65535)
    policy_error = _default_chrome_policy_error(data, port)
    if policy_error:
        raise RuntimeError(policy_error)
    use_default_profile = data.get("useDefaultChromeProfile") is True
    submit_prompt_approved = data.get("submitPromptApproved") is True
    generate_prompt_approved = data.get("generatePromptApproved") is True
    download_result_approved = data.get("downloadResultApproved") is True
    watch_downloads_approved = data.get("watchDownloadsApproved") is True
    if download_result_approved or watch_downloads_approved:
        raise RuntimeError(_NATIVE_GROK_DOWNLOAD_PROMPT_BLOCKER)
    auth_provider_preference = _normalize_auth_provider_preference(data.get("authProviderPreference"), default="x")
    download_click_timeout_seconds = _bounded_float(
        data.get("downloadClickTimeoutSeconds"),
        default=180.0,
        minimum=0.0,
        maximum=600.0,
    )
    watch_timeout_seconds = _bounded_float(
        data.get("watchTimeoutSeconds", data.get("timeoutSeconds")),
        default=120.0,
        minimum=0.0,
        maximum=600.0,
    )
    watch_poll_interval_seconds = _bounded_float(
        data.get("watchPollIntervalSeconds", data.get("pollIntervalSeconds")),
        default=2.0,
        minimum=0.1,
        maximum=10.0,
    )
    launch_result: dict = {
        "launched": False,
        "useDefaultChromeProfile": use_default_profile,
        "attachDefaultChromeApproved": data.get("attachDefaultChromeApproved") is True,
        "browserProfileMode": "default-chrome-cdp-attach" if use_default_profile else "existing-or-isolated-cdp",
        "browserProfileDirectory": _safe_profile_directory_name(data.get("browserProfileDirectory")),
    }
    try:
        _wait_for_cdp(port, timeout_seconds=1.0)
    except Exception:
        if use_default_profile:
            raise RuntimeError(
                f"{CHROME_DEFAULT_PROFILE_ATTACH_BLOCKER}: "
                + _default_chrome_attach_instruction(port)
            )
        launch_result = _launch_cdp_browser(data, handoff_dir, port)
        try:
            _wait_for_cdp(port, timeout_seconds=8.0)
        except Exception as exc:
            raise

    scene_id = str(scene.get("sceneId") or "")
    prompt = str(scene.get("prompt") or "")
    target: dict | None = None
    target_reused = False
    ws: _CdpWebSocket | None = None
    last_connect_error: Exception | None = None
    for attempt in range(2):
        try:
            target = _cdp_existing_grok_target(port)
        except Exception:
            target = None
        target_reused = target is not None
        if target is None:
            target = _cdp_new_target(port, str(manifest.get("grokUrl") or GROK_IMAGINE_URL))
        if not target or not target.get("webSocketDebuggerUrl"):
            raise RuntimeError("No Chrome DevTools Grok page target is available")
        candidate_ws = _CdpWebSocket(str(target["webSocketDebuggerUrl"]))
        try:
            try:
                candidate_ws.call("Page.bringToFront", timeout=3)
            except Exception:
                pass
            candidate_ws.call("Runtime.enable", timeout=5)
            candidate_ws.call("Page.enable", timeout=5)
            ws = candidate_ws
            break
        except Exception as exc:
            last_connect_error = exc
            try:
                candidate_ws.close()
            except Exception:
                pass
            if attempt == 0:
                time.sleep(0.5)
                continue
            raise RuntimeError(f"Grok browser target connection failed after retry: {exc}") from exc
    if ws is None:
        raise RuntimeError(f"Grok browser target connection failed: {last_connect_error}")
    try:
        if download_dir is not None:
            try:
                ws.call("Page.setDownloadBehavior", {
                    "behavior": "allow",
                    "downloadPath": str(download_dir),
                }, timeout=5)
            except Exception as exc:
                logger.warning("Grok browser download behavior could not be set: %s", exc)
        if data.get("preflightOnly") is True:
            preflight = _evaluate_browser_preflight(ws)
            browser_state = _browser_state_from_actions(preflight)
            return {
                "ok": True,
                "browserAutomationMode": "operator-approved-cdp-preflight",
                "remoteDebuggingPort": port,
                "filledSceneId": scene_id,
                "preflightOnly": True,
                "promptInjected": False,
                "generateRequested": False,
                "downloadResultRequested": False,
                "watchDownloadsRequested": False,
                "authProviderPreference": auth_provider_preference,
                "preflight": preflight,
                "targetUrl": preflight.get("url") or target.get("url"),
                "targetTitle": preflight.get("title") or target.get("title"),
                "targetReused": target_reused,
                **browser_state,
                **launch_result,
            }
        operator_ready_wait: dict | None = None
        if data.get("waitForOperatorReadyApproved") is True:
            operator_ready_wait = _wait_for_operator_ready(ws, data)
            if not operator_ready_wait.get("ready"):
                preflight = operator_ready_wait.get("preflight") if isinstance(operator_ready_wait.get("preflight"), dict) else {}
                browser_state = _browser_state_from_actions(preflight)
                if operator_ready_wait.get("cancelled"):
                    browser_state = {
                        **browser_state,
                        "browserBlocker": "grok-background-superseded",
                        "requiresOperatorAction": False,
                    }
                return {
                    "ok": True,
                    "browserAutomationMode": "operator-approved-cdp-wait-resume",
                    "remoteDebuggingPort": port,
                    "filledSceneId": scene_id,
                    "preflightOnly": False,
                    "promptInjected": False,
                    "submitPromptRequested": submit_prompt_approved,
                    "generatePromptRequested": generate_prompt_approved,
                    "generateRequested": False,
                    "downloadResultRequested": download_result_approved,
                    "watchDownloadsRequested": watch_downloads_approved,
                    "authProviderPreference": auth_provider_preference,
                    "operatorReadyWait": operator_ready_wait,
                    "operatorReadyTimedOut": operator_ready_wait.get("timedOut"),
                    "cancelled": operator_ready_wait.get("cancelled") is True,
                    "cancelReason": operator_ready_wait.get("cancelReason"),
                    "targetUrl": preflight.get("url") or target.get("url"),
                    "targetTitle": preflight.get("title") or target.get("title"),
                    "targetReused": target_reused,
                    "operatorNextAction": (
                        operator_ready_wait.get("cancelReason")
                        or "Complete Grok login/cookie/captcha/payment steps in the opened browser, "
                        "then rerun approval if the approved wait window already elapsed."
                    ),
                    **browser_state,
                    **launch_result,
                }
        evaluation = None
        last_evaluate_error: Exception | None = None
        for _attempt in range(3):
            try:
                evaluation = ws.call("Runtime.evaluate", {
                    "expression": _prompt_injection_script(prompt),
                    "awaitPromise": True,
                    "returnByValue": True,
                }, timeout=35)
                break
            except RuntimeError as exc:
                last_evaluate_error = exc
                if "Execution context was destroyed" not in str(exc) and "Cannot find context" not in str(exc):
                    raise
                time.sleep(2.0)
                try:
                    ws.call("Runtime.enable", timeout=3)
                    ws.call("Page.bringToFront", timeout=3)
                except Exception:
                    pass
        if evaluation is None:
            raise RuntimeError(str(last_evaluate_error or "Grok prompt injection evaluate failed"))
        value = _runtime_evaluate_value(evaluation)
        if not value.get("ok"):
            raise RuntimeError(json.dumps(value or {"error": "Grok prompt injection failed"}, ensure_ascii=True))
        generate_click: dict | None = None
        generate_action = None
        if generate_prompt_approved:
            try:
                generate_click = _runtime_evaluate_value(ws.call("Runtime.evaluate", {
                    "expression": _generation_click_script(),
                    "awaitPromise": True,
                    "returnByValue": True,
                }, timeout=8))
            except Exception as exc:
                generate_click = {"ok": False, "clicked": False, "error": str(exc)}
            if generate_click.get("clicked"):
                generate_action = "button-click"
            else:
                _dispatch_enter_key(ws)
                generate_action = "enter-key-fallback"
        elif submit_prompt_approved:
            _dispatch_enter_key(ws)
            generate_action = "enter-key"

        browser_state = _browser_state_from_actions(generate_click)

        download_click: dict | None = None
        if download_result_approved and not browser_state["requiresOperatorAction"]:
            try:
                download_evaluation = ws.call("Runtime.evaluate", {
                    "expression": _download_click_script(download_click_timeout_seconds),
                    "awaitPromise": True,
                    "returnByValue": True,
                }, timeout=download_click_timeout_seconds + 10.0)
                download_click = _runtime_evaluate_value(download_evaluation)
            except Exception as exc:
                download_click = {
                    "ok": False,
                    "clicked": False,
                    "action": "download-click",
                    "error": str(exc),
                    "authRequired": False,
                    "cookieChoiceRequired": False,
                }
            browser_state = _browser_state_from_actions(generate_click, download_click)

        watch_result: dict | None = None
        if watch_downloads_approved and not browser_state["requiresOperatorAction"]:
            if download_dir is None:
                raise RuntimeError("downloadDir is required before watchDownloadsApproved=true")
            watch_result = _watch_downloads(
                handoff_dir,
                manifest,
                download_dir,
                allow_newest_fallback=data.get("allowNewestFallback", True) is not False,
                overwrite=bool(data.get("overwrite")),
                since_handoff=data.get("sinceHandoff", True) is not False,
                timeout_seconds=watch_timeout_seconds,
                poll_interval_seconds=watch_poll_interval_seconds,
            )
            _write_review_packet(handoff_dir, manifest)

        result = {
            "ok": True,
            "browserAutomationMode": "operator-approved-cdp-generate-download-watch",
            "remoteDebuggingPort": port,
            "filledSceneId": scene_id,
            "promptInjected": True,
            "submitPromptRequested": submit_prompt_approved,
            "generatePromptRequested": generate_prompt_approved,
            "generateRequested": generate_prompt_approved or submit_prompt_approved,
            "generateAction": generate_action,
            "downloadResultRequested": download_result_approved,
            "watchDownloadsRequested": watch_downloads_approved,
            "authProviderPreference": auth_provider_preference,
            "targetUrl": value.get("url") or target.get("url"),
            "targetTitle": value.get("title") or target.get("title"),
            "targetReused": target_reused,
            **browser_state,
            **launch_result,
        }
        manual_instruction = None
        if generate_click is not None:
            result["generateClick"] = generate_click
        if operator_ready_wait is not None:
            result["operatorReadyWait"] = operator_ready_wait
            result["operatorReadyTimedOut"] = False
        if download_click is not None:
            result["downloadClick"] = download_click
            result["downloadClickTimeoutSeconds"] = download_click_timeout_seconds
            if not download_click.get("clicked") and watch_downloads_approved:
                manual_instruction = _manual_download_instruction(scene, download_dir)
        if manual_instruction:
            result["manualDownloadInstruction"] = manual_instruction
            result["operatorNextAction"] = manual_instruction
        if watch_result is not None:
            result.update(watch_result)
            result["watchTimeoutSeconds"] = watch_timeout_seconds
            result["watchPollIntervalSeconds"] = watch_poll_interval_seconds
            if watch_result.get("timedOut") and manual_instruction:
                result["operatorNextAction"] = (
                    f"{manual_instruction} Then click Downloads 가져오기 or 승인 생성+감시 again."
                )
        if download_dir is not None:
            result["downloadDir"] = str(download_dir)
        return result
    finally:
        ws.close()


def _prepare_background_automation_request(
    handoff_dir: Path,
    manifest: dict,
    project_id: str,
    data: dict,
) -> tuple[dict | None, dict | None, Path | None, str | None]:
    stored_request = _read_automation_request(handoff_dir) or {}
    replay_data = {
        key: stored_request.get(key)
        for key in _AUTOMATION_REPLAY_FIELDS
        if key in stored_request
    }
    for key in _AUTOMATION_REPLAY_FIELDS:
        if key in data:
            replay_data[key] = data.get(key)
    replay_data["projectId"] = str(manifest.get("projectId") or project_id)
    replay_data["operatorApproved"] = True
    replay_data["browserAutomationApproved"] = True
    replay_data["profileApproved"] = data.get("profileApproved") is True
    if "launchBrowserApproved" in data:
        replay_data["launchBrowserApproved"] = data.get("launchBrowserApproved") is True
    replay_data["preflightOnly"] = False

    requested_scene_id = str(replay_data.get("sceneId") or "")
    if slugify(requested_scene_id) in {"__next_missing__", "next-missing", "next_missing"}:
        scene = _next_missing_or_rejected_scene(handoff_dir, manifest)
        if scene is not None:
            replay_data["sceneId"] = str(scene.get("sceneId") or "")
    else:
        scene = _select_grok_scene(manifest, requested_scene_id)
    if scene is None:
        return None, None, None, "No Grok scene is available for background automation"

    download_dir = None
    if str(replay_data.get("downloadDir") or "").strip():
        download_dir, error = _download_dir_from_request(replay_data.get("downloadDir"))
        if error or download_dir is None:
            return scene, replay_data, None, error
    elif replay_data.get("downloadResultApproved") is True or replay_data.get("watchDownloadsApproved") is True:
        return scene, replay_data, None, "downloadDir is required before background download/watch automation"

    return scene, replay_data, download_dir, None


def _final_background_status_from_result(result: dict, automation_status: dict) -> tuple[str, str]:
    if result.get("cancelled"):
        return "cancelled", result.get("cancelReason") or "Background Grok job was superseded by a fresh operator-approved run."
    if result.get("allReady"):
        return "imported", "Background Grok job imported MP4s and render payload is ready."
    if (
        result.get("operatorReadyTimedOut")
        or result.get("requiresOperatorAction")
        or result.get("authRequired")
        or result.get("cookieChoiceRequired")
    ):
        return "needs-operator", result.get("operatorNextAction") or "Operator action is still required in Grok."
    if result.get("promptInjected"):
        return "completed", "Background Grok job injected the prompt and requested generation."
    return str(automation_status.get("status") or "completed"), str(automation_status.get("detail") or "Background Grok job completed.")


def _run_background_automation_job(
    job_id: str,
    project_key: str,
    handoff_dir: Path,
    manifest: dict,
    scene: dict,
    replay_data: dict,
    download_dir: Path | None,
    replay_request: dict,
    created_at: str,
) -> None:
    project_id = str(manifest.get("projectId") or project_key)
    started_at = datetime.now().isoformat(timespec="seconds")
    _write_automation_job_status(handoff_dir, _automation_job_status(
        project_id=project_id,
        job_id=job_id,
        scene=scene,
        status="running",
        detail="Background Grok job is waiting for operator login/cookie gates, then will resume generation/download/import.",
        download_dir=download_dir,
        replay_request=replay_request,
        created_at=created_at,
        started_at=started_at,
    ))

    def _record_operator_ready_progress(progress: dict) -> None:
        preflight = progress.get("preflight") if isinstance(progress.get("preflight"), dict) else {}
        browser_state = _browser_state_from_actions(preflight)
        ready = bool(progress.get("ready"))
        timed_out = bool(progress.get("timedOut"))
        next_action = (
            "Grok browser is ready; background job is continuing prompt injection, generation, download, and import."
            if ready
            else browser_state.get("operatorNextAction") or (
                "Complete Grok login/captcha/payment/safety steps in the opened browser; "
                "the active background job will resume automatically."
            )
        )
        progress_status = _build_automation_status(project_id, scene, {
            "browserAutomationMode": "operator-approved-cdp-background-wait-resume",
            "remoteDebuggingPort": replay_data.get("remoteDebuggingPort"),
            "filledSceneId": scene.get("sceneId"),
            "preflightOnly": False,
            "promptInjected": False,
            "submitPromptRequested": replay_data.get("submitPromptApproved") is True,
            "generatePromptRequested": replay_data.get("generatePromptApproved") is True,
            "generateRequested": False,
            "downloadResultRequested": replay_data.get("downloadResultApproved") is True,
            "watchDownloadsRequested": replay_data.get("watchDownloadsApproved") is True,
            "operatorReadyWait": progress,
            "operatorReadyTimedOut": timed_out,
            "targetUrl": preflight.get("url"),
            "targetTitle": preflight.get("title"),
            "operatorNextAction": next_action,
            **browser_state,
        })
        if not ready and not timed_out:
            progress_status["status"] = "waiting-for-operator"
            progress_status["detail"] = "Active Grok background job is waiting for operator browser approval steps."
            progress_status["activeBackgroundWait"] = True
        elif ready:
            progress_status["status"] = "running"
            progress_status["detail"] = "Grok browser is ready; background automation is continuing."
            progress_status["activeBackgroundWait"] = True
        _write_automation_status(handoff_dir, progress_status)
        _write_automation_job_status(handoff_dir, _automation_job_status(
            project_id=project_id,
            job_id=job_id,
            scene=scene,
            status="running",
            detail=str(progress_status.get("detail") or next_action),
            download_dir=download_dir,
            replay_request=replay_request,
            created_at=created_at,
            started_at=started_at,
            automation_status=progress_status,
        ))

    try:
        run_data = dict(replay_data)
        run_data["_operatorReadyProgress"] = _record_operator_ready_progress
        run_data["_operatorReadyShouldCancel"] = lambda: _background_job_cancelled(handoff_dir, job_id)
        result = _run_grok_browser_automation(handoff_dir, manifest, scene, run_data, download_dir)
        automation_status = _build_automation_status(project_id, scene, {
            **result,
            "browserAutomationMode": result.get("browserAutomationMode") or "operator-approved-cdp-background-generate-download-watch",
        })
        _write_automation_status(handoff_dir, automation_status)
        final_status, detail = _final_background_status_from_result(result, automation_status)
        _write_automation_job_status(handoff_dir, _automation_job_status(
            project_id=project_id,
            job_id=job_id,
            scene=scene,
            status=final_status,
            detail=detail,
            download_dir=download_dir,
            replay_request=replay_request,
            created_at=created_at,
            started_at=started_at,
            finished_at=datetime.now().isoformat(timespec="seconds"),
            result=result,
            automation_status=automation_status,
        ))
    except Exception as exc:
        logger.warning("Grok background automation failed: %s", exc)
        error_text = str(exc)
        error_state = _automation_error_state(error_text, _bounded_int(
            replay_data.get("remoteDebuggingPort"),
            default=9222,
            minimum=9000,
            maximum=65535,
        ))
        error_status = _build_automation_status(
            project_id,
            scene,
            {
                "browserAutomationMode": "operator-approved-cdp-background-generate-download-watch",
                **error_state,
            },
            error=error_text,
        )
        _write_automation_status(handoff_dir, error_status)
        _write_automation_job_status(handoff_dir, _automation_job_status(
            project_id=project_id,
            job_id=job_id,
            scene=scene,
            status="failed",
            detail=error_text,
            download_dir=download_dir,
            replay_request=replay_request,
            created_at=created_at,
            started_at=started_at,
            finished_at=datetime.now().isoformat(timespec="seconds"),
            automation_status=error_status,
            error=error_text,
        ))
    finally:
        with _background_automation_lock:
            current = _background_automation_threads.get(project_key)
            if current is threading.current_thread():
                _background_automation_threads.pop(project_key, None)


def _run_manual_download_watch_job(
    job_id: str,
    project_key: str,
    handoff_dir: Path,
    manifest: dict,
    scene: dict | None,
    download_dir: Path,
    download_dirs: list[Path] | None,
    timeout_seconds: float,
    poll_interval_seconds: float,
    allow_newest_fallback: bool,
    since_handoff: bool,
    overwrite: bool,
    preserve_candidates: bool,
    stop_on_import: bool,
    created_at: str,
    scene_mapping_mode: str = "",
    scene_grouped_take_size: int = 0,
    cancel_event: threading.Event | None = None,
) -> None:
    project_id = str(manifest.get("projectId") or project_key)
    scene_id_filter = str((scene or {}).get("sceneId") or "").strip() or None
    watched_dirs = _normalized_download_dirs(download_dir, download_dirs)
    started_at = datetime.now().isoformat(timespec="seconds")
    _write_manual_download_watch_status(handoff_dir, _manual_download_watch_status(
        project_id=project_id,
        job_id=job_id,
        scene=scene,
        status="running",
        detail="Watching the approved local folder(s) for Grok app/web MP4 output.",
        download_dir=download_dir,
        download_dirs=watched_dirs,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        allow_newest_fallback=allow_newest_fallback,
        since_handoff=since_handoff,
        overwrite=overwrite,
        preserve_candidates=preserve_candidates,
        stop_on_import=stop_on_import,
        scene_mapping_mode=scene_mapping_mode,
        scene_grouped_take_size=scene_grouped_take_size,
        created_at=created_at,
        started_at=started_at,
    ))
    try:
        result = _watch_downloads(
            handoff_dir,
            manifest,
            download_dir,
            download_dirs=watched_dirs,
            allow_newest_fallback=allow_newest_fallback,
            overwrite=overwrite,
            since_handoff=since_handoff,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            scene_id_filter=scene_id_filter,
            preserve_candidates=preserve_candidates,
            stop_on_import=stop_on_import,
            scene_mapping_mode=scene_mapping_mode,
            scene_grouped_take_size=scene_grouped_take_size,
            cancel_event=cancel_event,
        )
        _write_review_packet(handoff_dir, manifest)
        imported_count = len(result.get("imported") or [])
        final_status = (
            "cancelled"
            if result.get("cancelled")
            else "imported" if imported_count > 0
            else "timed-out" if result.get("timedOut")
            else "completed"
        )
        detail = (
            result.get("cancelReason")
            if result.get("cancelled")
            else
            f"Imported {imported_count} Grok MP4 candidate(s) from watched folder(s)."
            if imported_count > 0
            else "Manual Grok folder watch ended without a new MP4 import."
        )
        with _manual_download_watch_lock:
            current = _manual_download_watch_threads.get(project_key)
            still_current = current is threading.current_thread()
        if still_current:
            _write_manual_download_watch_status(handoff_dir, _manual_download_watch_status(
                project_id=project_id,
                job_id=job_id,
                scene=scene,
                status=final_status,
                detail=detail,
                download_dir=download_dir,
                download_dirs=watched_dirs,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                allow_newest_fallback=allow_newest_fallback,
                since_handoff=since_handoff,
                overwrite=overwrite,
                preserve_candidates=preserve_candidates,
                stop_on_import=stop_on_import,
                scene_mapping_mode=scene_mapping_mode,
                scene_grouped_take_size=scene_grouped_take_size,
                created_at=created_at,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                result=result,
            ))
    except Exception as exc:
        logger.warning("Grok manual download watch failed: %s", exc)
        with _manual_download_watch_lock:
            current = _manual_download_watch_threads.get(project_key)
            still_current = current is threading.current_thread()
        if still_current:
            _write_manual_download_watch_status(handoff_dir, _manual_download_watch_status(
                project_id=project_id,
                job_id=job_id,
                scene=scene,
                status="failed",
                detail=str(exc),
                download_dir=download_dir,
                download_dirs=watched_dirs,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                allow_newest_fallback=allow_newest_fallback,
                since_handoff=since_handoff,
                overwrite=overwrite,
                preserve_candidates=preserve_candidates,
                stop_on_import=stop_on_import,
                scene_mapping_mode=scene_mapping_mode,
                scene_grouped_take_size=scene_grouped_take_size,
                created_at=created_at,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                error=str(exc),
            ))
    finally:
        with _manual_download_watch_lock:
            current = _manual_download_watch_threads.get(project_key)
            if current is threading.current_thread():
                _manual_download_watch_threads.pop(project_key, None)
                _manual_download_watch_cancel_events.pop(project_key, None)


def _relative_project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(_project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _scene_match_tokens(scene: dict) -> set[str]:
    scene_id = str(scene.get("sceneId") or "").lower()
    tokens = {scene_id, scene_id.replace("-", "_")}
    number = re.search(r"(\d+)$", scene_id)
    if number:
        n = number.group(1)
        tokens.update({f"scene{n}", f"scene-{n}", f"scene_{n}"})
    return {token for token in tokens if token}


def _safe_draft_scenes(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    scenes: list[dict] = []
    for item in value:
        if isinstance(item, dict):
            scenes.append(dict(item))
    return scenes


def _write_production_queue(handoff_dir: Path, manifest: dict) -> Path:
    """Write a compact operator queue for producing all Grok MP4s in order."""
    project_id = str(manifest.get("projectId") or handoff_dir.name)
    scenes = [scene for scene in (manifest.get("scenes") or []) if isinstance(scene, dict)]
    shot_bible = manifest.get("shotBible") if isinstance(manifest.get("shotBible"), dict) else {}
    required_count = manifest.get("minGrokMainScenes") or max(1, (len(scenes) + 1) // 2)
    assets = _match_downloaded_assets(handoff_dir, manifest)
    scene_queue = _scene_queue_status(handoff_dir, manifest, assets)
    replacement_scene_ids = [
        str(item)
        for item in (scene_queue.get("replacementSceneIds") or [])
        if str(item).strip()
    ]
    replacement_scene_id = replacement_scene_ids[0] if replacement_scene_ids else ""
    replacement_asset = next(
        (
            item for item in assets
            if item.get("status") == "ready" and str(item.get("sceneId") or "") == replacement_scene_id
        ),
        {},
    )
    replacement_gate = (
        replacement_asset.get("qualityGate")
        if isinstance(replacement_asset.get("qualityGate"), dict)
        else {}
    )
    replacement_probe = (
        replacement_asset.get("clipProbe")
        if isinstance(replacement_asset.get("clipProbe"), dict)
        else {}
    )
    replacement_issues = [
        str(item)
        for item in [
            *(replacement_gate.get("technicalIssues") if isinstance(replacement_gate.get("technicalIssues"), list) else []),
            *(replacement_gate.get("sourceIssues") if isinstance(replacement_gate.get("sourceIssues"), list) else []),
        ]
        if str(item).strip()
    ]
    replacement_issue_items = "".join(f"<li>{escape(item)}</li>" for item in replacement_issues[:6])
    replacement_stop_panel = ""
    if replacement_scene_id:
        replacement_file = str(
            replacement_asset.get("fileName")
            or (replacement_asset.get("expectedFileName") if isinstance(replacement_asset, dict) else "")
            or f"{replacement_scene_id}.grok.mp4"
        )
        replacement_dimensions = ""
        if replacement_probe.get("width") and replacement_probe.get("height"):
            replacement_dimensions = (
                f"{replacement_probe.get('width')}x{replacement_probe.get('height')}"
                f" / {replacement_probe.get('fps') or '?'}fps"
            )
        replacement_stop_panel = f"""
    <section class="panel stop">
      <h2>Quality replacement stop</h2>
      <p><strong>Replace {escape(replacement_scene_id)} before later scenes.</strong> The current Grok-main candidate is not publishable enough to count as ready, so do not keep producing later scenes around it.</p>
      <div class="runway-grid">
        <div class="runway-card">
          <strong>Rejected candidate</strong>
          <span>{escape(replacement_file)}</span>
          <p class="muted">{escape(replacement_dimensions or "technical probe unavailable")}</p>
        </div>
        <div class="runway-card">
          <strong>Required next action</strong>
          <span>Generate two fresh Grok MP4 takes</span>
          <p class="muted">Use Companion/pageAssets direct import or operator-owned manual batch upload, not a browser-observed currentSrc/cache copy.</p>
        </div>
        <div class="runway-card">
          <strong>Review rule</strong>
          <span>Accept only after candidate comparison</span>
          <p class="muted">The chosen take must pass first-second motion, continuity, artifact, caption-safe, and source-provenance checks.</p>
        </div>
      </div>
      <ul>{replacement_issue_items or "<li>No detailed issue recorded; regenerate from original Grok export anyway.</li>"}</ul>
    </section>
        """
    next_scene = _next_missing_or_rejected_scene(handoff_dir, manifest, assets)
    next_scene_id = str((next_scene or {}).get("sceneId") or "").strip()
    next_expected = str((next_scene or {}).get("expectedFileName") or "").strip()
    next_take_number = _recommended_take_number(next_scene) if next_scene else 2
    queue_inline_url = _bookmarklet_queue_url(project_id)
    queue_console_snippet = (
        "(() => { "
        "const s = document.createElement('script'); "
        f"s.src = {json.dumps(_bookmarklet_queue_script_url(project_id))}; "
        "s.async = true; "
        "document.documentElement.appendChild(s); "
        "})();"
    )
    if next_scene:
        command_payload = _extension_command_payload(project_id, handoff_dir, manifest, next_scene, next_take_number)
        queue_inline_url = str(command_payload.get("bookmarkletQueueInlineUrl") or queue_inline_url)
        queue_console_snippet = str(command_payload.get("bookmarkletQueueInlineConsoleSnippet") or queue_console_snippet)
    companion_probe = _chrome_profile_probe_with_packet_context(handoff_dir)
    companion_ready = companion_probe.get("anyVideoStudioCompanion") is True
    codex_only = companion_probe.get("codexExtensionIsNotCompanion") is True
    companion_status = str(companion_probe.get("status") or "unknown")
    companion_profile = " ".join(
        item
        for item in (
            str(companion_probe.get("recommendedProfileDirectory") or "").strip(),
            f"({str(companion_probe.get('recommendedProfileName') or '').strip()})"
            if str(companion_probe.get("recommendedProfileName") or "").strip()
            else "",
        )
        if item
    ) or "signed-in Chrome profile"
    companion_action = str(companion_probe.get("operatorAction") or "")
    companion_class = "good" if companion_ready else "block" if codex_only else "warn"
    companion_label = (
        "Video Studio Companion detected"
        if companion_ready
        else "Codex extension only - load Video Studio Companion"
        if codex_only
        else "Video Studio Companion not detected"
    )
    companion_guide_url = _chrome_companion_guide_url(project_id, next_scene_id or (str(scenes[0].get("sceneId") or "scene-01") if scenes else "scene-01"))
    companion_dir = str(_chrome_companion_extension_dir())
    automation_status = _read_automation_status(handoff_dir) or {}
    cdp_blocker = str(automation_status.get("browserBlocker") or automation_status.get("error") or "").strip()
    cdp_profile_mode = str(automation_status.get("browserProfileMode") or "").strip()
    cdp_port = automation_status.get("remoteDebuggingPort") or 9222
    cdp_state = "blocked" if cdp_blocker else "not connected"
    cdp_class = "block" if cdp_blocker else "warn"
    manual_watch = _manual_download_watch_summary(_read_manual_download_watch_status(handoff_dir), project_id) or {}
    watch_status = str(manual_watch.get("status") or "not armed")
    watch_running = watch_status == "running" and manual_watch.get("activeThread") is True
    watch_class = "good" if watch_running else "warn"
    watch_detail = (
        f"{manual_watch.get('sceneMappingMode') or 'manual'}"
        f" / take size {manual_watch.get('sceneGroupedTakeSize') or '-'}"
    )
    watch_download_dirs = (
        manual_watch.get("downloadDirs")
        if isinstance(manual_watch.get("downloadDirs"), list)
        else []
    )
    if not watch_download_dirs and manual_watch.get("downloadDir"):
        watch_download_dirs = [manual_watch.get("downloadDir")]
    watch_download_dirs = [str(item) for item in watch_download_dirs if str(item or "").strip()]
    watch_folder_items = "".join(
        f"<li><code>{escape(item)}</code></li>" for item in watch_download_dirs
    ) or "<li><code>not armed</code></li>"
    watch_detail = f"{watch_detail} / {', '.join(watch_download_dirs) if watch_download_dirs else 'no watched folder'}"
    profile_alignment = (
        companion_probe.get("profileAlignment")
        if isinstance(companion_probe.get("profileAlignment"), dict)
        else {}
    )
    codex_native_host = (
        companion_probe.get("codexNativeHost")
        if isinstance(companion_probe.get("codexNativeHost"), dict)
        else {}
    )
    primary_operator_profile = str(
        profile_alignment.get("primaryOperatorProfileLabel")
        or companion_probe.get("primaryOperatorProfileLabel")
        or companion_profile
        or "signed-in Chrome profile"
    )
    replay_profile = str(profile_alignment.get("automationReplayProfileDirectory") or "").strip()
    profile_alignment_status = str(profile_alignment.get("status") or "unknown")
    profile_alignment_class = "block" if profile_alignment_status == "mismatch" else "good" if profile_alignment_status == "aligned" else "warn"
    codex_direct_control = codex_native_host.get("videoStudioDirectControlAvailable") is True
    direct_control_label = "available" if codex_direct_control else "not exposed to Video Studio bridge"
    do_not_open_items = "".join(
        f"<li>{escape(str(item))}</li>"
        for item in (profile_alignment.get("doNotOpen") or companion_probe.get("doNotOpenBrowsers") or [])
        if str(item).strip()
    ) or "<li>Microsoft Edge</li><li>new Chrome profile</li>"
    codex_profiles = ", ".join(str(item) for item in companion_probe.get("codexExtensionProfileDirectories") or []) or "none"
    companion_profiles = ", ".join(str(item) for item in companion_probe.get("videoStudioCompanionProfileDirectories") or []) or "none"
    chrome_profile_alignment_panel = f"""
    <section class="panel profile-align {escape(profile_alignment_class)}">
      <h2>Chrome profile alignment</h2>
      <p>Grok-main should run in the existing signed-in Chrome profile, then hand native MP4s to Video Studio. This page should not send the operator to Edge or a fresh browser profile.</p>
      <div class="runway-grid">
        <div class="runway-card">
          <strong>Primary Chrome profile</strong>
          <span>{escape(primary_operator_profile)}</span>
          <p class="muted">Use this profile for Grok app/web generation and SuperGrok access.</p>
        </div>
        <div class="runway-card">
          <strong>CDP/replay profile</strong>
          <span>{escape(replay_profile or "not recorded")}</span>
          <p class="muted">{escape("mismatch - secondary only" if profile_alignment_status == "mismatch" else "aligned or unused")}</p>
        </div>
        <div class="runway-card">
          <strong>Codex extension/native host</strong>
          <span>{escape(str(codex_native_host.get("status") or "unknown"))}</span>
          <p class="muted">Video Studio direct control: {escape(direct_control_label)}</p>
        </div>
      </div>
      <table>
        <tbody>
          <tr><th>Codex extension profiles</th><td>{escape(codex_profiles)}</td></tr>
          <tr><th>Video Studio companion profiles</th><td>{escape(companion_profiles)}</td></tr>
          <tr><th>Control route</th><td>{escape(str(profile_alignment.get("controlRoute") or "native-mp4-watcher-or-companion"))}</td></tr>
          <tr><th>Do not open</th><td><ul class="source-list">{do_not_open_items}</ul></td></tr>
        </tbody>
      </table>
      <p class="muted">{escape(str(profile_alignment.get("operatorAction") or companion_action or "Use the existing signed-in Chrome profile, save native Grok MP4s, then import through Video Studio."))}</p>
    </section>
    """
    native_blocker = "Generate the next Grok scene and save the native app/web MP4."
    if replacement_scene_id:
        native_blocker = (
            f"Replace {replacement_scene_id} with two fresh Grok MP4 takes through Companion/pageAssets direct import "
            "or operator-owned manual batch upload; the current local file is proof-only or below the source-quality floor."
        )
    elif next_scene_id:
        native_blocker = (
            f"Generate {next_scene_id} in Grok app/web, then save/export the MP4 into a watched folder "
            f"or batch-upload it as {next_expected or f'{next_scene_id}.grok.mp4'}."
        )
    grok_source_state_panel = f"""
    <section class="panel source-state">
      <h2>Grok source status</h2>
      <div class="runway-grid">
        <div class="runway-card">
          <strong>Model access</strong>
          <span>Not the blocker</span>
          <p class="muted">Use the signed-in Grok app/web or SuperGrok browser session. No xAI API key or paid video API is required by Video Studio.</p>
        </div>
        <div class="runway-card">
          <strong>Current blocker</strong>
          <span>{escape(native_blocker)}</span>
          <p class="muted">CDP/default-profile automation is secondary. Native local MP4 export/import is the main path.</p>
        </div>
        <div class="runway-card">
          <strong>Watched folders</strong>
          <ul class="source-list">{watch_folder_items}</ul>
        </div>
      </div>
    </section>
    """
    take_group_size = 2
    production_matrix_rows: list[str] = []
    file_order_items: list[str] = []
    for index, scene in enumerate(scenes):
        scene_id = str(scene.get("sceneId") or f"scene-{index + 1:02d}")
        expected = str(scene.get("expectedFileName") or f"{scene_id}.grok.mp4")
        take_prompts = scene.get("takePrompts") if isinstance(scene.get("takePrompts"), list) else []
        if not take_prompts:
            take_prompts = [{
                "takeNumber": 1,
                "label": "continuity-master",
                "focus": "Base Grok prompt.",
                "prompt": str(scene.get("prompt") or ""),
                "promptQuality": scene.get("promptQuality"),
            }]
        selected_takes = [take for take in take_prompts if isinstance(take, dict)][:take_group_size]
        while selected_takes and len(selected_takes) < take_group_size:
            selected_takes.append(selected_takes[-1])
        for take_index, take in enumerate(selected_takes, start=1):
            take_number = _normalize_take_number(take.get("takeNumber"), default=take_index)
            take_label = str(take.get("label") or f"take-{take_number}")
            take_focus = str(take.get("focus") or "")
            batch_slot = index * take_group_size + take_index
            take_name = f"{scene_id} take {take_index}"
            file_order_items.append(
                f"<li><code>{escape(take_name)}</code> "
                f"<span>{escape(expected)}</span> "
                f"<span>Take {take_number}: {escape(take_label)}</span></li>"
            )
            production_matrix_rows.append(f"""
              <tr>
                <td>{batch_slot}</td>
                <td><strong>{escape(scene_id)}</strong></td>
                <td>Take {take_number}: {escape(take_label)}</td>
                <td>{escape(take_focus)}</td>
                <td><code>{escape(expected)}</code> candidate {take_index}</td>
              </tr>
            """)
    hard_reject_rules = [
        str(item)
        for item in (shot_bible.get("hardRejectChecklist") if isinstance(shot_bible.get("hardRejectChecklist"), list) else [])
        if str(item).strip()
    ] or [
        "static image with fake zoom only",
        "baked captions, title text, watermark, UI overlay, or readable logo/text",
        "weak or static first two seconds",
        "subject, prop, location, or palette continuity drift",
        "main subject blocks the lower-third or right-side Shorts UI danger zone",
    ]
    hard_reject_html = "".join(f"<li>{escape(item)}</li>" for item in hard_reject_rules[:8])
    hard_reject_text = "\n".join(f"- {item}" for item in hard_reject_rules[:8])
    negative_prompt_text = ", ".join(
        str(item)
        for item in (shot_bible.get("negativePrompts") if isinstance(shot_bible.get("negativePrompts"), list) else [])
        if str(item).strip()
    )
    cinematic_quality_floor = str(
        shot_bible.get("cinematicQualityFloor")
        or "Each Grok MP4 must be intentional raw footage for the exact scene, not generic filler."
    )
    anti_slop_rules = [
        str(item)
        for item in (
            shot_bible.get("antiSlopDirectives")
            if isinstance(shot_bible.get("antiSlopDirectives"), list)
            else []
        )
        if str(item).strip()
    ] or [
        "No generic stock b-roll or pretty filler merely related to the topic.",
        "No static poster or still image with fake zoom only.",
        "No random ad-like montage or unrelated AI transition.",
    ]
    anti_slop_html = "".join(f"<li>{escape(item)}</li>" for item in anti_slop_rules[:8])
    anti_slop_text = "\n".join(f"- {item}" for item in anti_slop_rules[:8])
    shot_lock_board_rows: list[str] = []
    for index, scene in enumerate(scenes):
        scene_id = str(scene.get("sceneId") or f"scene-{index + 1:02d}")
        shot_lock = _scene_shot_lock(shot_bible, scene_id)
        if not shot_lock:
            continue
        shot_lock_board_rows.append(f"""
          <tr>
            <td><strong>{escape(scene_id)}</strong></td>
            <td>{escape(str(shot_lock.get("actionLock") or ""))}</td>
            <td>{escape(str(shot_lock.get("firstSecondMotionLock") or ""))}</td>
            <td>{escape(str(shot_lock.get("identityLock") or ""))}</td>
            <td>{escape(str(shot_lock.get("layoutLock") or ""))}</td>
          </tr>
        """)
    scene_rows: list[str] = []
    for index, scene in enumerate(scenes):
        scene_id = str(scene.get("sceneId") or f"scene-{index + 1:02d}")
        expected = str(scene.get("expectedFileName") or f"{scene_id}.grok.mp4")
        shot_lock = _scene_shot_lock(shot_bible, scene_id)
        shot_lock_text = _format_scene_shot_lock_text(shot_lock)
        take_prompts = scene.get("takePrompts") if isinstance(scene.get("takePrompts"), list) else []
        if not take_prompts:
            take_prompts = [{
                "takeNumber": 1,
                "label": "continuity-master",
                "focus": "Base Grok prompt.",
                "prompt": str(scene.get("prompt") or ""),
                "promptQuality": scene.get("promptQuality"),
            }]
        recommended_take = _select_take_prompt(scene, 2) or _select_take_prompt(scene, 1) or {}
        recommended_take_number = _normalize_take_number(
            recommended_take.get("takeNumber") if isinstance(recommended_take, dict) else 1
        )
        recommended_take_label = (
            str(recommended_take.get("label") or f"take-{recommended_take_number}")
            if isinstance(recommended_take, dict)
            else f"take-{recommended_take_number}"
        )
        operator_rules = [
            str(item)
            for item in (scene.get("operatorChecklist") if isinstance(scene.get("operatorChecklist"), list) else [])
            if str(item).strip()
        ]
        operator_rules_html = "".join(f"<li>{escape(item)}</li>" for item in operator_rules[:6])
        take_cards: list[str] = []
        for take in take_prompts:
            if not isinstance(take, dict):
                continue
            take_number = _normalize_take_number(take.get("takeNumber"))
            take_label = str(take.get("label") or f"take-{take_number}")
            take_focus = str(take.get("focus") or "")
            prompt = str(take.get("prompt") or scene.get("prompt") or "")
            prompt_quality = take.get("promptQuality") if isinstance(take.get("promptQuality"), dict) else scene.get("promptQuality")
            if not isinstance(prompt_quality, dict):
                prompt_quality = {}
            prompt_packet = "\n".join([
                f"Scene: {scene_id}",
                f"Take: {take_number} / {take_label}",
                f"Save/export target: {expected} (keep additional take candidates if Grok uses a generic filename)",
                "",
                "Cinematic quality floor:",
                cinematic_quality_floor,
                "",
                "Shot lock:",
                shot_lock_text or "- Use the exact scene visible action, continuity, camera, and caption-safe layout from this row.",
                "",
                "Anti-slop reject if:",
                anti_slop_text,
                "",
                "Grok prompt:",
                prompt,
                "",
                "Before import, reject if:",
                hard_reject_text,
                "",
                "After generation:",
                "- Use Companion/pageAssets direct import first; if that fails, use only operator-owned manual batch upload.",
                "- Keep at least two candidate MP4s for this scene before Video Studio approval.",
                "- Do not use a browser currentSrc/cache/proxy clip as the final Grok-main source.",
            ])
            if negative_prompt_text:
                prompt_packet = "\n".join([
                    prompt_packet,
                    "",
                    f"Negative constraints already included: {negative_prompt_text}",
                ])
            take_cards.append(f"""
            <section class="take-card">
              <div class="take-head">
                <strong>Take {take_number}: {escape(take_label)}</strong>
                <span>quality: {escape(str(prompt_quality.get("status") or "unknown"))} / {escape(str(prompt_quality.get("score") if prompt_quality.get("score") is not None else "?"))}</span>
              </div>
              <p>{escape(take_focus)}</p>
              <div class="row-actions">
                <a href="{escape(_extension_autostart_url(project_id, scene_id, 'prep-generate', take_number))}" target="_blank" rel="noreferrer">Open Grok + Take {take_number}</a>
                <button type="button" data-copy="{escape(prompt)}">Copy take prompt</button>
                <button type="button" data-copy="{escape(prompt_packet)}">Copy prompt packet</button>
              </div>
              <div class="reject-grid">
                <div>
                  <strong>Source import rule</strong>
                  <p class="muted">Use Companion/pageAssets direct import or operator-owned manual batch upload, then keep two takes as Video Studio candidates.</p>
                </div>
                <div>
                  <strong>Reject before import</strong>
                  <ul>{hard_reject_html}</ul>
                </div>
              </div>
              <textarea class="prompt-packet" readonly>{escape(prompt_packet)}</textarea>
              <textarea readonly>{escape(prompt)}</textarea>
            </section>
            """)
        scene_rows.append(f"""
        <section class="scene-row">
          <div class="scene-meta">
            <strong>{escape(scene_id)}</strong>
            <span>{escape(expected)}</span>
            <span>recommended first pass: Take {recommended_take_number} / {escape(recommended_take_label)}</span>
            <span>candidate floor: generate 2+ takes before accepting Grok-main</span>
          </div>
          <p>Produce candidate MP4s as raw footage, then import at least two viable takes for each Grok-main scene before approval.</p>
          <div class="scene-review-rules">
            <strong>Scene acceptance rule</strong>
            <ul>{operator_rules_html or "<li>Accept only if the MP4 has a strong first-two-second hook, visible motion, continuity, no artifacts, and caption-safe composition.</li>"}</ul>
          </div>
          <div class="scene-review-rules">
            <strong>Shot lock</strong>
            <textarea class="shot-lock" readonly>{escape(shot_lock_text or "No shot lock recorded.")}</textarea>
          </div>
          <div class="take-ladder">
            {''.join(take_cards)}
          </div>
          <label class="candidate-note-label" for="candidate-note-{escape(scene_id)}">Candidate comparison note</label>
          <textarea id="candidate-note-{escape(scene_id)}" class="candidate-note" readonly>After import, write this in the review packet: which take won, which take lost, and why the chosen MP4 fits first-second hook, continuity, artifact, and caption-safe checks.</textarea>
        </section>
        """)

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Grok Production Queue - {escape(project_id)}</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #0f1115; color: #f5f7fb; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: 26px; }}
    h2 {{ margin: 0 0 8px; font-size: 16px; }}
    p {{ color: #bac3d1; line-height: 1.5; }}
    .panel, .scene-row {{ border: 1px solid #2f3b4b; border-radius: 8px; background: #161b24; padding: 14px; margin-top: 14px; }}
    .scene-row {{ background: #121923; }}
    .scene-meta, .row-actions, .take-head {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .take-head {{ justify-content: space-between; }}
    .scene-meta span, code {{ border: 1px solid #2d3748; border-radius: 4px; background: #090d13; color: #dce5f2; padding: 4px 6px; }}
    .take-ladder {{ display: grid; gap: 10px; margin-top: 10px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid #273348; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ color: #dce5f2; background: #0d1420; }}
    .take-card {{ border: 1px solid #31435b; border-radius: 8px; background: #0d1420; padding: 12px; }}
    .readiness {{ border-color: #46606f; background: #101a22; }}
    .readiness-grid {{ display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin: 12px 0; }}
    .readiness-card {{ border: 1px solid #354254; border-radius: 8px; background: #0d1420; padding: 10px; }}
    .readiness-card.good {{ border-color: #1f7a4a; background: #0f1d17; }}
    .readiness-card.warn {{ border-color: #7a6325; background: #1d170b; }}
    .readiness-card.block {{ border-color: #8c3434; background: #221113; }}
    .readiness-card strong {{ display: block; color: #f7fafc; margin-bottom: 4px; }}
    .profile-align.good {{ border-color: #1f7a4a; background: #0f1d17; }}
    .profile-align.warn {{ border-color: #7a6325; background: #1d170b; }}
    .profile-align.block {{ border-color: #8c3434; background: #221113; }}
    .runway {{ border-color: #5b6d31; background: #141b11; }}
    .stop {{ border-color: #a33d3d; background: #251014; }}
    .stop h2 {{ color: #ffe0e0; }}
    .runway-grid {{ display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin: 12px 0; }}
    .runway-card {{ border: 1px solid #36451f; border-radius: 8px; background: #0d140b; padding: 10px; }}
    .runway-card strong {{ display: block; color: #f7fafc; margin-bottom: 4px; }}
    .muted {{ color: #aeb8c6; }}
    .source-state {{ border-color: #2f6271; background: #0f1b22; }}
    .source-list {{ margin: 6px 0 0; padding-left: 18px; color: #d5dde9; }}
    .source-list code {{ overflow-wrap: anywhere; }}
    .reject-grid {{ display: grid; gap: 10px; grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr); margin-top: 10px; }}
    .reject-grid > div, .scene-review-rules {{ border: 1px solid #31435b; border-radius: 6px; background: #111923; padding: 10px; }}
    .reject-grid ul, .scene-review-rules ul {{ margin: 6px 0 0 18px; padding: 0; color: #d5dde9; line-height: 1.4; }}
    .candidate-note-label {{ display: block; margin-top: 12px; color: #dce5f2; font-size: 13px; font-weight: 700; }}
    .candidate-note {{ min-height: 72px; }}
    textarea {{ width: 100%; min-height: 116px; box-sizing: border-box; margin-top: 10px; border: 1px solid #344155; border-radius: 6px; background: #090d13; color: #f7fafc; padding: 10px; line-height: 1.45; }}
    textarea.prompt-packet {{ min-height: 210px; border-color: #4f6f48; background: #08110a; }}
    button, a {{ border: 1px solid #52627a; border-radius: 6px; background: #2563eb; color: #fff; padding: 8px 10px; text-decoration: none; cursor: pointer; font-size: 14px; }}
    ol {{ color: #d5dde9; line-height: 1.6; }}
    li + li {{ margin-top: 4px; }}
  </style>
</head>
<body>
  <main data-production-queue-version="{escape(GROK_PRODUCTION_QUEUE_VERSION)}">
    <h1>Grok production queue</h1>
    <p>Project: {escape(project_id)}. Generate these clips in order in the signed-in Grok app/web session. Video Studio handles captions, BGM, TTS/no-voice audio design, candidate review, and render; do not bake text or explanatory intent into Grok clips.</p>
    <section class="panel readiness">
      <h2>Grok-main readiness</h2>
      <p>Grok can be the main footage source only when this queue can receive direct-imported or operator-uploaded Grok MP4 files. The Codex Chrome extension alone is not the Video Studio Grok Companion.</p>
      <div class="readiness-grid">
        <div class="readiness-card {escape(companion_class)}">
          <strong>Video Studio Companion</strong>
          <span>{escape(companion_label)}</span>
          <p class="muted">Profile: {escape(companion_profile)}</p>
        </div>
        <div class="readiness-card {escape(cdp_class)}">
          <strong>Chrome/CDP attach</strong>
          <span>{escape(cdp_state)}</span>
          <p class="muted">port {escape(str(cdp_port))}{' / ' + escape(cdp_profile_mode) if cdp_profile_mode else ''}{' / ' + escape(cdp_blocker) if cdp_blocker else ''}</p>
        </div>
        <div class="readiness-card {escape(watch_class)}">
          <strong>Downloads watcher</strong>
          <span>{escape(watch_status)}{' / active' if watch_running else ''}</span>
          <p class="muted">{escape(watch_detail)}</p>
        </div>
      </div>
      <div class="row-actions">
        <a href="{escape(companion_guide_url, quote=True)}" target="_blank" rel="noreferrer">Open Companion guide</a>
        <button type="button" data-copy="{escape(companion_dir)}">Copy Companion folder</button>
        <button type="button" data-copy="{escape(companion_action)}">Copy readiness action</button>
      </div>
      <p class="muted">{escape(companion_action or 'Load the Video Studio Grok Companion in the signed-in Chrome profile, or use the queue runner/bookmarklet fallback from the Grok tab.')}</p>
    </section>
    {grok_source_state_panel}
    {chrome_profile_alignment_panel}
    {replacement_stop_panel}
    <section class="panel runway">
      <h2>Grok-main runway</h2>
      <p>Use this page as the production lane for Grok hero footage. Grok should output raw vertical MP4 clips only; Video Studio owns captions, BGM, layout, review, and render. If the Chrome Companion is not connected, open the signed-in Grok tab and run the self-contained queue runner below.</p>
      <div class="runway-grid">
        <div class="runway-card">
          <strong>Next scene</strong>
          <span>{escape(next_scene_id or "none")}</span>
          <p class="muted">{escape(next_expected or "All Grok scenes imported or waiting for review.")}</p>
        </div>
        <div class="runway-card">
          <strong>Recommended take</strong>
          <span>Take {escape(str(next_take_number))} / motion-first</span>
          <p class="muted">Generate at least two takes before approval.</p>
        </div>
        <div class="runway-card">
          <strong>Main-source floor</strong>
          <span>{escape(str(required_count))}/{escape(str(len(scenes)))} accepted Grok MP4 scenes</span>
          <p class="muted">First hook scene must be Grok before publish-ready render. Preserve two imported MP4 takes per scene before moving to the next scene.</p>
        </div>
      </div>
      <div class="row-actions">
        <a href="{escape(queue_inline_url, quote=True)}">Queue Fill+Generate+Direct Import</a>
        <button type="button" data-copy="{escape(queue_console_snippet)}">Copy queue console runner</button>
      </div>
      <p class="muted">Run the queue from <strong>grok.com/imagine</strong>, not from this page. It fills the next missing scene prompt, tries Generate, then direct-imports a fetchable MP4/blob to the local uploadEndpoint. If direct import fails, it stops without clicking Download/Save/Export; manual batch upload remains operator-owned.</p>
    </section>
    <section class="panel">
      <h2>Run order</h2>
      <ol>
        <li>Open each row in order and generate at least two candidate 4-6 second vertical MP4 takes before accepting a Grok-main scene. Recommended first pass is <strong>Take 2 / motion-first</strong>.</li>
        <li>Keep the production rhythm as <strong>scene-grouped 2-take batches</strong>: scene-01 take A/B, scene-02 take A/B, and so on. The operator-owned manual batch upload/import path expects <code>sceneGroupedTakeSize=2</code>.</li>
        <li>If a row prompt reads like production intent, narration, TTS, caption, layout, or checklist notes, rewrite it into visible action before generating.</li>
        <li>Direct-import or manually batch-upload every viable candidate take, not only the first pass. Exact file names help but are not required.</li>
        <li>In Video Studio, select generated MP4 files with <strong>Grok MP4 일괄 반입</strong> grouped by scene row: all scene-01 takes first, then all scene-02 takes, and so on.</li>
        <li>In the review packet, record the candidate comparison note before approving. Accept at least {escape(str(required_count))}/{escape(str(len(scenes)))} Grok clips before rendering Grok-main.</li>
      </ol>
    </section>
    <section class="panel">
      <h2>Scene-grouped 2-take production matrix</h2>
      <p class="muted">Generate and save these MP4 candidates in this exact order when filenames are generic. This gives the review packet enough options to reject weak Grok output instead of accepting the first usable clip.</p>
      <table>
        <thead>
          <tr><th>Slot</th><th>Scene</th><th>Take</th><th>Generation focus</th><th>Import target</th></tr>
        </thead>
        <tbody>{''.join(production_matrix_rows)}</tbody>
      </table>
    </section>
    <section class="panel">
      <h2>Expected batch file order</h2>
      <ol>{''.join(file_order_items)}</ol>
    </section>
    <section class="panel">
      <h2>Grok cinematic quality floor</h2>
      <p>{escape(cinematic_quality_floor)}</p>
      <strong>Anti-slop reject if</strong>
      <ul>{anti_slop_html}</ul>
    </section>
    <section class="panel">
      <h2>Shot lock board</h2>
      <p class="muted">Each Grok generation must preserve the row action, first-second motion, identity, camera, and caption-safe layout. If a take misses this lock, reject it before import instead of compensating with captions.</p>
      <table>
        <thead><tr><th>Scene</th><th>Action</th><th>First second</th><th>Identity</th><th>Layout</th></tr></thead>
        <tbody>{''.join(shot_lock_board_rows)}</tbody>
      </table>
    </section>
    <section class="panel">
      <h2>Continuity guard</h2>
      <p>{escape(str(shot_bible.get("visualContinuity") or ""))}</p>
      <p>{escape(str(shot_bible.get("captionSafePlan") or ""))}</p>
    </section>
    {''.join(scene_rows)}
  </main>
  <script>
    document.querySelectorAll('[data-copy]').forEach((button) => {{
      button.addEventListener('click', async () => {{
        const value = button.getAttribute('data-copy') || '';
        try {{
          await navigator.clipboard.writeText(value);
          const original = button.textContent;
          button.textContent = 'Copied';
          setTimeout(() => {{ button.textContent = original || 'Copy prompt'; }}, 1000);
        }} catch {{
          const root = button.closest('.take-card') || button.closest('.scene-row') || document;
          const textarea = root.querySelector('textarea');
          if (textarea) {{
            textarea.focus();
            textarea.select();
          }}
        }}
      }});
    }});
  </script>
</body>
</html>
"""
    queue_path = handoff_dir / "production-queue.html"
    queue_path.write_text(html, encoding="utf-8")
    return queue_path


def _ensure_production_queue(
    handoff_dir: Path,
    manifest: dict,
    project_id: str,
    *,
    refresh_live: bool = True,
) -> tuple[dict, Path]:
    """Backfill production queue metadata for handoff packets created before the queue existed."""
    queue_path = Path(str(manifest.get("productionQueuePath") or handoff_dir / "production-queue.html"))
    changed = False
    # The queue page itself should be live, but status polling must stay light
    # enough to guide Grok generation without repeatedly probing local MP4s.
    if refresh_live:
        queue_needs_refresh = True
    else:
        queue_needs_refresh = False
        if not queue_path.exists():
            queue_needs_refresh = True
        elif manifest.get("productionQueueVersion") != GROK_PRODUCTION_QUEUE_VERSION:
            queue_needs_refresh = True
    if queue_needs_refresh:
        queue_path = _write_production_queue(handoff_dir, manifest)
        changed = True
    if manifest.get("productionQueueVersion") != GROK_PRODUCTION_QUEUE_VERSION:
        manifest["productionQueueVersion"] = GROK_PRODUCTION_QUEUE_VERSION
        changed = True
    queue_url = _production_queue_url(project_id)
    if manifest.get("productionQueuePath") != str(queue_path):
        manifest["productionQueuePath"] = str(queue_path)
        changed = True
    if manifest.get("productionQueueUrl") != queue_url:
        manifest["productionQueueUrl"] = queue_url
        changed = True
    if changed:
        _write_manifest(handoff_dir, manifest)
    return manifest, queue_path


def _write_operator_worksheet(handoff_dir: Path, manifest: dict) -> Path:
    project_id = str(manifest.get("projectId") or handoff_dir.name)
    incoming_dir = str(manifest.get("incomingDir") or handoff_dir / "incoming")
    grok_url = str(manifest.get("grokUrl") or GROK_IMAGINE_URL)
    shot_bible = manifest.get("shotBible") if isinstance(manifest.get("shotBible"), dict) else {}
    production_profile = shot_bible.get("productionProfile") if isinstance(shot_bible.get("productionProfile"), dict) else {}
    negative_prompts = ", ".join(str(item) for item in shot_bible.get("negativePrompts") or [])
    review_items = "".join(
        f"<li>{escape(str(item))}</li>"
        for item in shot_bible.get("reviewChecklist") or []
    )
    hard_reject_items = "".join(
        f"<li>{escape(str(item))}</li>"
        for item in shot_bible.get("hardRejectChecklist") or []
    )
    scene_intents = "".join(
        f"<li><strong>{escape(str(item.get('sceneId') or 'scene'))}</strong>: {escape(str(item.get('intent') or ''))}</li>"
        for item in shot_bible.get("sceneIntents") or []
        if isinstance(item, dict)
    )
    target_selection = manifest.get("grokTargetSelection") if isinstance(manifest.get("grokTargetSelection"), dict) else {}
    auto_expanded = ", ".join(str(item) for item in target_selection.get("autoExpandedSceneIds") or [])
    auto_expansion_note = (
        f"<p><strong>Auto-expanded Grok scenes:</strong> {escape(auto_expanded)}</p>"
        if auto_expanded
        else ""
    )
    scene_cards = []
    for scene in manifest.get("scenes") or []:
        scene_id_raw = str(scene.get("sceneId") or "scene")
        scene_id = escape(scene_id_raw)
        expected = escape(str(scene.get("expectedFileName") or f"{scene_id_raw}.grok.mp4"))
        auto_badge = " / auto-expanded from support source" if scene.get("grokAutoExpanded") is True else ""
        prompt_quality = scene.get("promptQuality") if isinstance(scene.get("promptQuality"), dict) else {}
        prompt_quality_text = escape(
            f"{prompt_quality.get('status') or 'unknown'} / score {prompt_quality.get('score') if prompt_quality.get('score') is not None else '?'}"
        )
        checklist = "".join(
            f"<li>{escape(str(item))}</li>"
            for item in scene.get("operatorChecklist") or []
        )
        take_prompts = scene.get("takePrompts") if isinstance(scene.get("takePrompts"), list) else []
        if not take_prompts:
            take_prompts = [{
                "takeNumber": 1,
                "label": "continuity-master",
                "focus": "Base Grok prompt.",
                "prompt": str(scene.get("prompt") or ""),
                "promptQuality": prompt_quality,
            }]
        take_cards = []
        for take in take_prompts:
            if not isinstance(take, dict):
                continue
            take_number = _normalize_take_number(take.get("takeNumber"))
            take_label = escape(str(take.get("label") or f"take-{take_number}"))
            take_focus = escape(str(take.get("focus") or ""))
            take_prompt = escape(str(take.get("prompt") or ""))
            take_quality = take.get("promptQuality") if isinstance(take.get("promptQuality"), dict) else {}
            take_quality_text = escape(
                f"{take_quality.get('status') or 'unknown'} / score {take_quality.get('score') if take_quality.get('score') is not None else '?'}"
            )
            take_cards.append(f"""
            <section class="take-card">
              <div class="take-head">
                <h3>Take {take_number}: {take_label}</h3>
                <a class="button" href="{escape(_extension_autostart_url(project_id, scene_id_raw, 'prep-generate', take_number))}" target="_blank" rel="noreferrer">Hash + Generate</a>
              </div>
              <p class="meta">{take_focus}</p>
              <textarea readonly data-prompt="{take_prompt}">{take_prompt}</textarea>
              <div class="actions">
                <button type="button" data-copy="{take_prompt}">Copy take prompt</button>
                <code>take {take_number}</code>
                <code>prompt quality: {take_quality_text}</code>
              </div>
            </section>
            """)
        scene_cards.append(f"""
        <section class="scene-card">
          <div class="scene-head">
            <h2>{scene_id}</h2>
            <a class="button" href="{escape(grok_url)}" target="_blank" rel="noreferrer">Open Grok Imagine</a>
          </div>
          <div class="take-ladder">
            <h3>Grok take ladder</h3>
            <p class="meta">Generate 2-3 distinct Grok takes for this scene, then import all MP4s with candidate preservation and accept only the best one in the review packet.</p>
            {''.join(take_cards)}
          </div>
          <div class="actions">
            <code>{expected}</code>
            <code>Grok target{escape(auto_badge)}</code>
            <code>prompt quality: {prompt_quality_text}</code>
          </div>
          <h3>Operator review before download</h3>
          <ul>{checklist}</ul>
        </section>
        """)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Grok Handoff - {escape(project_id)}</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #101214; color: #f3f4f6; }}
    main {{ max-width: 920px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    h3 {{ margin: 14px 0 6px; font-size: 13px; color: #d8dde6; text-transform: uppercase; letter-spacing: .04em; }}
    .meta {{ color: #aeb6c2; line-height: 1.5; overflow-wrap: anywhere; }}
    .scene-card {{ margin-top: 18px; padding: 16px; border: 1px solid #333a44; border-radius: 8px; background: #171b20; }}
    .scene-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
    .take-ladder {{ margin-top: 14px; }}
    .take-card {{ margin-top: 10px; padding: 12px; border: 1px solid #3f5368; border-radius: 8px; background: #101821; }}
    .take-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
    h2 {{ margin: 0; font-size: 18px; }}
    textarea {{ width: 100%; min-height: 130px; margin-top: 12px; box-sizing: border-box; background: #0b0d10; color: #f9fafb; border: 1px solid #3b4654; border-radius: 6px; padding: 10px; line-height: 1.45; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 10px; }}
    button, .button {{ appearance: none; border: 1px solid #4b5563; border-radius: 6px; background: #2563eb; color: white; padding: 8px 10px; font-size: 14px; text-decoration: none; cursor: pointer; }}
    code {{ color: #d1d5db; background: #0b0d10; border: 1px solid #30363f; border-radius: 4px; padding: 5px 7px; }}
    .contract {{ margin-top: 18px; padding: 12px; border: 1px solid #264653; border-radius: 6px; color: #b6d7e8; background: #10212a; }}
    .shot-bible {{ margin-top: 18px; padding: 16px; border: 1px solid #3f5368; border-radius: 8px; background: #151d27; }}
    .shot-bible p {{ margin: 8px 0; line-height: 1.5; }}
    ul {{ margin: 8px 0 0 18px; padding: 0; color: #cfd7e3; line-height: 1.45; }}
    li + li {{ margin-top: 4px; }}
  </style>
</head>
<body>
  <main>
    <h1>Grok handoff worksheet</h1>
    <p class="meta">Project: {escape(project_id)}<br />Save generated MP4 files into: {escape(incoming_dir)}</p>
    <div class="contract">No xAI API call and no credential storage. Browser control is approval-gated; remote debugging stays off unless explicitly approved. This worksheet keeps the default path on prompt copy, Grok generation, download-folder import, and render sync.</div>
    <section class="shot-bible">
      <h2>Shot bible</h2>
      <p><strong>Visual continuity:</strong> {escape(str(shot_bible.get("visualContinuity") or ""))}</p>
      <p><strong>Subject:</strong> {escape(str(shot_bible.get("subjectContinuity") or ""))}</p>
      <p><strong>Location:</strong> {escape(str(shot_bible.get("locationContinuity") or ""))}</p>
      <p><strong>Palette:</strong> {escape(str(shot_bible.get("palette") or ""))}</p>
      <p><strong>Camera:</strong> {escape(str(shot_bible.get("cameraLanguage") or ""))}</p>
      <p><strong>Production family:</strong> {escape(str(production_profile.get("family") or ""))}</p>
      <p><strong>Narrative shape:</strong> {escape(str(production_profile.get("narrativeShape") or ""))}</p>
      <p><strong>Layout plan:</strong> {escape(str(shot_bible.get("layoutPlan") or ""))}</p>
      <p><strong>Caption-safe plan:</strong> {escape(str(shot_bible.get("captionSafePlan") or ""))}</p>
      <p><strong>Motion plan:</strong> {escape(str(shot_bible.get("motionPlan") or ""))}</p>
      <p><strong>Negative prompts:</strong> {escape(negative_prompts)}</p>
      <p><strong>Grok target selection:</strong> {escape(str(target_selection.get("mode") or ""))} / minimum {escape(str(target_selection.get("minGrokMainScenes") or ""))}/{escape(str(target_selection.get("sourceMixTotalScenes") or ""))}</p>
      {auto_expansion_note}
      <h3>Scene intents</h3>
      <ul>{scene_intents}</ul>
      <h3>Global review checklist</h3>
      <ul>{review_items}</ul>
      <h3>Hard reject checklist</h3>
      <ul>{hard_reject_items}</ul>
    </section>
    {''.join(scene_cards)}
  </main>
  <script>
    document.querySelectorAll('[data-copy]').forEach((button) => {{
      button.addEventListener('click', async () => {{
        const value = button.getAttribute('data-copy') || '';
        try {{
          await navigator.clipboard.writeText(value);
          const originalText = button.textContent;
          button.textContent = 'Copied';
          setTimeout(() => {{ button.textContent = originalText || 'Copy take prompt'; }}, 1200);
        }} catch {{
          const textarea = button.closest('.scene-card').querySelector('textarea');
          textarea.focus();
          textarea.select();
          button.textContent = 'Select prompt';
        }}
      }});
    }});
  </script>
</body>
</html>
"""
    worksheet_path = handoff_dir / "operator-sheet.html"
    worksheet_path.write_text(html, encoding="utf-8")
    return worksheet_path


def _grok_candidate_curation_plan_for_asset(scene_id: str, expected_file_name: str, asset: dict, *, strict_main_source: bool) -> dict:
    candidate_assets = asset.get("candidateAssets") if isinstance(asset.get("candidateAssets"), list) else []
    if not candidate_assets and asset.get("status") == "ready":
        candidate_assets = [asset]

    def _as_int(value: object) -> int:
        try:
            return int(float(value)) if value is not None and value != "" else 0
        except (TypeError, ValueError):
            return 0

    candidate_items: list[dict] = []
    seen_files: set[str] = set()
    for candidate in candidate_assets:
        if not isinstance(candidate, dict):
            continue
        file_name = str(candidate.get("fileName") or "")
        if file_name and file_name in seen_files:
            continue
        if file_name:
            seen_files.add(file_name)
        probe = candidate.get("clipProbe") if isinstance(candidate.get("clipProbe"), dict) else {}
        provenance = candidate.get("sourceProvenance") if isinstance(candidate.get("sourceProvenance"), dict) else {}
        source_ok = provenance.get("acceptAsGrokMainSource") is True or not strict_main_source
        technical_ok = probe.get("ok") is True
        motion_ok = probe.get("motionOk") is True
        height = _as_int(probe.get("height"))
        width = _as_int(probe.get("width"))
        score = 0
        score += 40 if source_ok else 0
        score += 30 if technical_ok else 0
        score += 15 if height >= 1080 else max(0, min(10, height // 120))
        score += 10 if motion_ok else 0
        score += 5 if width and height else 0
        reject_reasons: list[str] = []
        if not source_ok:
            reject_reasons.append(
                str(provenance.get("operatorAction") or "source is not proven as browser-native/direct-imported or operator-uploaded Grok MP4")
            )
        if not technical_ok:
            reject_reasons.extend(str(item) for item in (probe.get("issues") or []) if item)
        if not motion_ok:
            reject_reasons.append(f"motion status: {probe.get('motionStatus') or 'unknown'}")
        candidate_items.append({
            "sceneId": scene_id,
            "fileName": file_name,
            "width": width or None,
            "height": height or None,
            "fps": probe.get("fps"),
            "durationSec": probe.get("durationSec"),
            "technicalOk": technical_ok,
            "motionOk": motion_ok,
            "sourceAcceptable": source_ok,
            "sourceStatus": str(provenance.get("status") or ""),
            "score": score,
            "selected": candidate.get("selected") is True,
            "rejectReasons": reject_reasons[:6],
        })
    candidate_items = sorted(
        candidate_items,
        key=lambda item: (
            1 if item.get("selected") else 0,
            int(item.get("score") or 0),
            int(item.get("height") or 0),
            int(item.get("width") or 0),
        ),
        reverse=True,
    )
    publishable_candidates = [
        item for item in candidate_items
        if item.get("technicalOk") is True and item.get("sourceAcceptable") is True and item.get("motionOk") is True
    ]
    if not candidate_items:
        recommendation = (
            f"Generate and import at least two native Grok MP4 takes for {scene_id}; "
            "candidate comparison cannot start from a post URL or placeholder."
        )
    elif len(candidate_items) < 2:
        recommendation = (
            "Import a second native Grok MP4 take before accepting the scene; single-candidate Grok-main approval "
            "does not meet the current quality bar."
        )
    elif not publishable_candidates:
        recommendation = (
            "Do not render from the current candidates. They are proof-only or below the technical/source floor; "
            "replace with two browser-native/direct-imported or operator-uploaded Grok MP4 takes."
        )
    else:
        recommendation = (
            "Compare the top two native candidates and accept only after layout, hook, continuity, artifact, "
            "audio-fit, and platform comparison notes are complete."
        )
    return {
        "required": strict_main_source,
        "targetSceneId": scene_id,
        "expectedFileName": expected_file_name,
        "candidateCount": len(candidate_items),
        "publishableCandidateCount": len(publishable_candidates),
        "minimumCandidates": 2,
        "selectedCandidate": candidate_items[0] if candidate_items else {},
        "candidates": candidate_items[:6],
        "recommendation": recommendation,
        "reviewReadiness": (
            "ready-for-operator-review"
            if len(publishable_candidates) >= 1 and len(candidate_items) >= 2
            else "needs-native-grok-takes"
        ),
        "selectionRule": (
            "Prefer browser-native/direct-imported or operator-uploaded Grok MP4 provenance first, then technical 9:16 quality, "
            "visible motion, continuity, caption-safe composition, and fewer artifacts. Never select browser cache/currentSrc proof as main footage."
        ),
    }


def _write_review_packet(handoff_dir: Path, manifest: dict) -> Path:
    """Write a local HTML review packet for synced Grok clips."""
    project_id = str(manifest.get("projectId") or handoff_dir.name)
    incoming_dir = str(manifest.get("incomingDir") or handoff_dir / "incoming")
    shot_bible = manifest.get("shotBible") if isinstance(manifest.get("shotBible"), dict) else {}
    production_profile = shot_bible.get("productionProfile") if isinstance(shot_bible.get("productionProfile"), dict) else {}
    assets = _match_downloaded_assets(handoff_dir, manifest)
    asset_by_scene = {
        str(item.get("sceneId")): item
        for item in assets
        if item.get("sceneId")
    }
    review_decisions = manifest.get("reviewDecisions") if isinstance(manifest.get("reviewDecisions"), dict) else {}
    review_items = "".join(
        f"<li>{escape(str(item))}</li>"
        for item in shot_bible.get("reviewChecklist") or []
    )
    target_selection = manifest.get("grokTargetSelection") if isinstance(manifest.get("grokTargetSelection"), dict) else {}
    auto_expanded = ", ".join(str(item) for item in target_selection.get("autoExpandedSceneIds") or [])
    auto_expansion_note = (
        f"<p><strong>Auto-expanded Grok scenes:</strong> {escape(auto_expanded)}</p>"
        if auto_expanded
        else ""
    )
    negative_prompts = ", ".join(str(item) for item in shot_bible.get("negativePrompts") or [])
    hard_reject_items = "".join(
        f"<li>{escape(str(item))}</li>"
        for item in shot_bible.get("hardRejectChecklist") or []
    )
    scene_cards: list[str] = []
    for index, scene in enumerate(manifest.get("scenes") or []):
        scene_id_raw = str(scene.get("sceneId") or f"scene-{index + 1:02d}")
        scene_id = escape(scene_id_raw)
        expected = escape(str(scene.get("expectedFileName") or f"{scene_id_raw}.grok.mp4"))
        auto_badge = " / auto-expanded from support source" if scene.get("grokAutoExpanded") is True else ""
        prompt = escape(str(scene.get("prompt") or ""))
        prompt_quality = scene.get("promptQuality") if isinstance(scene.get("promptQuality"), dict) else {}
        prompt_quality_missing = prompt_quality.get("missing") if isinstance(prompt_quality.get("missing"), list) else []
        prompt_quality_text = escape(
            f"{prompt_quality.get('status') or 'unknown'} / score {prompt_quality.get('score') if prompt_quality.get('score') is not None else '?'}"
        )
        prompt_missing_items = "".join(f"<li>{escape(str(item))}</li>" for item in prompt_quality_missing)
        prompt_source = escape(str(prompt_quality.get("sourcePrompt") or ""))
        prompt_source_words = prompt_quality.get("sourceWordCount")
        prompt_source_word_text = f" / words {prompt_source_words}" if prompt_source_words is not None else ""
        prompt_operator_action = escape(str(prompt_quality.get("operatorAction") or ""))
        prompt_operator_action_block = (
            f"<p class=\"meta\"><strong>Prompt action:</strong> {prompt_operator_action}</p>"
            if prompt_operator_action
            else ""
        )
        asset = asset_by_scene.get(scene_id_raw) or {"status": "missing"}
        decision = review_decisions.get(scene_id_raw) if isinstance(review_decisions.get(scene_id_raw), dict) else {}
        decision_status = "accepted" if decision.get("accepted") is True else "rejected" if decision.get("accepted") is False else "unreviewed"
        first_hook_checked = " checked" if decision.get("firstTwoSecondHook") is True else ""
        artifact_checked = " checked" if decision.get("artifactFree") is True else ""
        continuity_checked = " checked" if decision.get("continuityOk") is True else ""
        caption_checked = " checked" if decision.get("captionSafe") is True else ""
        source_rationale = escape(str(decision.get("sourceRationale") or ""))
        quality_review_note = escape(str(decision.get("qualityReviewNote") or ""))
        selected_candidate_summary = escape(str(decision.get("selectedCandidateSummary") or decision.get("singleCandidateJustification") or ""))
        operator_note = escape(str(decision.get("operatorNote") or ""))
        raw_visual_quality_verdict = decision.get("visualQualityVerdict") or ("pass" if decision.get("accepted") is True else "")
        visual_quality_verdict = escape(str(raw_visual_quality_verdict))
        caption_layout_review_note = escape(str(decision.get("captionLayoutReviewNote") or ""))
        shot_lock_checked = " checked" if decision.get("shotLockMatch") is True else ""
        scene_assembly_checked = " checked" if decision.get("sceneAssemblyOk") is True else ""
        shot_lock_evidence_note = escape(str(decision.get("shotLockEvidenceNote") or ""))
        scene_assembly_role_note = escape(str(decision.get("sceneAssemblyRoleNote") or ""))
        hook_note_value = escape(str(decision.get("hookNote") or scene.get("hookNote") or ""))
        continuity_note_value = escape(str(decision.get("continuityNote") or scene.get("continuityNote") or ""))
        layout_variant_key_value = escape(str(decision.get("layoutVariantKey") or scene.get("layoutVariantKey") or ""))
        layout_variant_label_value = escape(str(decision.get("layoutVariantLabel") or scene.get("layoutVariantLabel") or ""))
        layout_variant_note_value = escape(str(decision.get("layoutVariantNote") or scene.get("layoutVariantNote") or ""))
        thumbnail_review_note_value = escape(str(decision.get("thumbnailReviewNote") or ""))
        audio_mix_review_note_value = escape(str(decision.get("audioMixReviewNote") or ""))
        platform_comparison_note_value = escape(str(decision.get("platformComparisonNote") or ""))
        source_provenance_checked = " checked" if decision.get("sourceProvenanceConfirmed") is True else ""
        source_provenance_note_value = escape(str(decision.get("sourceProvenanceNote") or ""))
        retry_prompt_raw = _scene_retry_prompt(scene, shot_bible, decision) if decision.get("accepted") is False else ""
        retry_prompt = escape(retry_prompt_raw)
        retry_prompt_block = (
            f"""
          <details open class="retry-prompt">
            <summary>Next retry prompt for Grok</summary>
            <p class="meta">The Chrome companion will use this prompt for the next generation attempt because the previous clip was rejected.</p>
            <textarea readonly>{retry_prompt}</textarea>
          </details>
            """
            if retry_prompt_raw
            else ""
        )
        take_prompts = scene.get("takePrompts") if isinstance(scene.get("takePrompts"), list) else []
        take_rows = []
        for take in take_prompts:
            if not isinstance(take, dict):
                continue
            take_number = _normalize_take_number(take.get("takeNumber"))
            take_label = escape(str(take.get("label") or f"take-{take_number}"))
            take_focus = escape(str(take.get("focus") or ""))
            take_prompt_text = escape(str(take.get("prompt") or ""))
            take_rows.append(f"""
            <section class="take-card">
              <h3>Take {take_number}: {take_label}</h3>
              <p class="meta">{take_focus}</p>
              <textarea readonly>{take_prompt_text}</textarea>
            </section>
            """)
        take_prompt_block = (
            f"""
          <details class="take-ladder">
            <summary>Grok take ladder for candidate generation</summary>
            <p class="meta">Use these distinct takes to generate multiple MP4 candidates for the same scene before choosing one below.</p>
            {''.join(take_rows)}
          </details>
            """
            if take_rows
            else ""
        )
        status = escape(str(asset.get("status") or "missing"))
        gate = asset.get("qualityGate") if isinstance(asset.get("qualityGate"), dict) else {}
        clip_probe = asset.get("clipProbe") if isinstance(asset.get("clipProbe"), dict) else {}
        gate_status = escape(str(gate.get("status") or "missing"))
        gate_required = "required" if gate.get("required") is True else "recommended"
        gate_class = "pass" if gate.get("status") == "accepted" else "warn"
        source_provenance = asset.get("sourceProvenance") if isinstance(asset.get("sourceProvenance"), dict) else {}
        source_provenance_status = escape(str(source_provenance.get("status") or "unknown"))
        source_provenance_action = escape(str(source_provenance.get("operatorAction") or ""))
        candidate_assets = asset.get("candidateAssets") if isinstance(asset.get("candidateAssets"), list) else []
        selected_file_name = str(decision.get("selectedFileName") or asset.get("fileName") or "")
        candidate_rows = ""
        if candidate_assets:
            rows: list[str] = []
            for candidate_asset in candidate_assets:
                candidate_file = str(candidate_asset.get("fileName") or "")
                checked = " checked" if candidate_asset.get("selected") is True or candidate_file == selected_file_name else ""
                candidate_probe = candidate_asset.get("clipProbe") if isinstance(candidate_asset.get("clipProbe"), dict) else {}
                candidate_summary = (
                    f"{candidate_probe.get('width') or '?'}x{candidate_probe.get('height') or '?'}"
                    f" / fps {candidate_probe.get('fps') or '?'}"
                    f" / {candidate_probe.get('durationSec') or '?'}s"
                    f" / audio {'yes' if candidate_probe.get('hasAudio') else 'no'}"
                ) if candidate_probe else "not probed"
                candidate_preview = str(candidate_asset.get("previewUrl") or "")
                rows.append(f"""
                <label class="candidate-option">
                  <input type="radio" name="selectedFileName-{scene_id}" data-review-field="selectedFileName" value="{escape(candidate_file)}"{checked} />
                  <span>
                    <strong>{escape(candidate_file)}</strong>
                    <small>{escape(candidate_summary)}</small>
                  </span>
                  <video src="{escape(candidate_preview)}" controls muted playsinline preload="metadata"></video>
                </label>
                """)
            candidate_rows = f"""
            <div class="candidate-picker">
              <h3>Grok candidate selection</h3>
              <p class="meta">Pick the exact MP4 candidate to use for this scene before accepting. Rejected scenes keep all candidates for comparison.</p>
              <div class="candidate-grid">{''.join(rows)}</div>
            </div>
            """
        elif selected_file_name:
            candidate_rows = f'<input type="hidden" data-review-field="selectedFileName" value="{escape(selected_file_name)}" />'
        curation_plan = _grok_candidate_curation_plan_for_asset(
            scene_id_raw,
            str(scene.get("expectedFileName") or f"{scene_id_raw}.grok.mp4"),
            asset,
            strict_main_source=manifest.get("grokMainSourceRequired") is True,
        )
        curation_items: list[str] = []
        for item in curation_plan.get("candidates") or []:
            if not isinstance(item, dict):
                continue
            dimensions = (
                f"{item.get('width') or '?'}x{item.get('height') or '?'}"
                f" / fps {item.get('fps') or '?'}"
                f" / {item.get('durationSec') or '?'}s"
            )
            reject_reasons = "; ".join(str(reason) for reason in item.get("rejectReasons") or [])
            curation_items.append(
                "<li>"
                f"<strong>{escape(str(item.get('fileName') or 'candidate'))}</strong>: "
                f"score {escape(str(item.get('score') if item.get('score') is not None else '?'))}; "
                f"{escape(dimensions)}; "
                f"source {'ok' if item.get('sourceAcceptable') is True else 'reject'}; "
                f"technical {'ok' if item.get('technicalOk') is True else 'reject'}; "
                f"motion {'ok' if item.get('motionOk') is True else 'reject'}"
                f"{'; reject reasons: ' + escape(reject_reasons) if reject_reasons else ''}"
                "</li>"
            )
        selected_candidate = curation_plan.get("selectedCandidate") if isinstance(curation_plan.get("selectedCandidate"), dict) else {}
        selected_candidate_text = selected_candidate.get("fileName") or "none"
        curation_class = "pass" if curation_plan.get("reviewReadiness") == "ready-for-operator-review" else "warn"
        curation_accept_blocked = (
            manifest.get("grokMainSourceRequired") is True
            and (
                int(curation_plan.get("candidateCount") or 0) < int(curation_plan.get("minimumCandidates") or 2)
                or int(curation_plan.get("publishableCandidateCount") or 0) < 1
            )
        )
        curation_block = f"""
          <div class="curation-gate {curation_class}">
            <h3>Grok candidate curation</h3>
            <p><strong>Publishable candidates: {escape(str(curation_plan.get('publishableCandidateCount') or 0))}/{escape(str(curation_plan.get('candidateCount') or 0))}</strong> / minimum {escape(str(curation_plan.get('minimumCandidates') or 2))}</p>
            <p><strong>Selected candidate:</strong> {escape(str(selected_candidate_text))} / readiness: {escape(str(curation_plan.get('reviewReadiness') or 'unknown'))}</p>
            <p class="meta">{escape(str(curation_plan.get('recommendation') or ''))}</p>
            <p class="meta"><strong>Selection rule:</strong> {escape(str(curation_plan.get('selectionRule') or ''))}</p>
            <ul>{''.join(curation_items) or '<li>No imported Grok MP4 candidates yet.</li>'}</ul>
          </div>
        """
        technical_issues = gate.get("technicalIssues") if isinstance(gate.get("technicalIssues"), list) else []
        technical_issue_items = "".join(f"<li>{escape(str(item))}</li>" for item in technical_issues)
        technical_issue_block = (
            f"<ul>{technical_issue_items}</ul>"
            if technical_issue_items
            else "<p>No ffprobe technical issues recorded.</p>"
        )
        probe_summary = "Not probed yet"
        if clip_probe:
            probe_summary = (
                f"{clip_probe.get('width') or '?'}x{clip_probe.get('height') or '?'}"
                f" / fps {clip_probe.get('fps') or '?'}"
                f" / {clip_probe.get('durationSec') or '?'}s"
                f" / audio {'yes' if clip_probe.get('hasAudio') else 'no'}"
            )
        can_accept = asset.get("status") == "ready" and not curation_accept_blocked
        accept_disabled = "" if can_accept else " disabled"
        accept_block_reason = (
            "<p class=\"meta\"><strong>Accept blocked:</strong> Grok-main needs at least two candidates and at least one publishable browser-native/direct-imported or operator-uploaded Grok MP4. Regenerate or import replacement takes before accepting.</p>"
            if curation_accept_blocked
            else ""
        )
        source_path = escape(str(asset.get("sourcePath") or ""))
        preview_url = str(asset.get("previewUrl") or "")
        shot_lock = _scene_shot_lock(shot_bible, scene_id_raw)
        shot_lock_text = escape(_format_scene_shot_lock_text(shot_lock))
        shot_lock_reject_items = "".join(
            f"<li>{escape(str(item))}</li>"
            for item in (shot_lock.get("rejectIf") if isinstance(shot_lock, dict) else []) or []
        )
        shot_lock_block = (
            f"""
          <div class="quality-gate">
            <h3>Shot lock acceptance</h3>
            <pre class="shot-lock-text">{shot_lock_text}</pre>
            <p class="meta">Accept only if the selected Grok MP4 visibly matches this lock and has a clear role in the final edit.</p>
            <ul>{shot_lock_reject_items or '<li>No scene-specific reject list recorded.</li>'}</ul>
          </div>
            """
            if shot_lock_text
            else ""
        )
        if asset.get("status") == "ready" and preview_url:
            preview = f"""
            <video src="{escape(preview_url)}" controls muted playsinline preload="metadata"></video>
            <p class="path">{source_path}</p>
            """
        else:
            preview = f"""
            <div class="missing">
              Waiting for <code>{expected}</code> in the incoming folder.
            </div>
            """
        checklist = "".join(
            f"<li>{escape(str(item))}</li>"
            for item in scene.get("operatorChecklist") or []
        )
        scene_cards.append(f"""
        <section class="scene-card">
          <div class="scene-head">
            <div>
              <h2>{scene_id}</h2>
              <p class="meta">Expected: <code>{expected}</code> / Asset: <strong>{status}</strong> / Review: <strong data-review-label>{escape(decision_status)}</strong>{escape(auto_badge)}</p>
            </div>
          </div>
          <div class="preview">{preview}</div>
          <div class="quality-gate {gate_class}">
            <h3>Quality gate</h3>
            <p><strong>{gate_status}</strong> / {gate_required}</p>
            <p class="probe">Technical probe: {escape(probe_summary)}</p>
            <p class="meta">Source provenance: <strong>{source_provenance_status}</strong>{f' / {source_provenance_action}' if source_provenance_action else ''}</p>
            {technical_issue_block}
            <p class="meta">Accept is allowed only after the actual MP4 is present and the required review boxes below are true.</p>
          </div>
          <div class="quality-gate">
            <h3>Prompt production gate</h3>
            <p><strong>{prompt_quality_text}</strong></p>
            <p class="meta">This gate checks whether the Grok prompt contains concrete action, first-second motion, continuity, caption-safe framing, and template-aware layout intent.</p>
            <p class="meta">Source prompt: {prompt_source or 'missing'}{prompt_source_word_text}</p>
            {prompt_operator_action_block}
            <ul>{prompt_missing_items or '<li>Prompt covers the production minimum.</li>'}</ul>
          </div>
          <details>
            <summary>Prompt used for generation</summary>
            <textarea readonly>{prompt}</textarea>
          </details>
          {take_prompt_block}
          {retry_prompt_block}
          {curation_block}
          {shot_lock_block}
          <h3>Operator decision</h3>
          <div class="decision-form" data-review-scene="{scene_id}">
            {candidate_rows}
            <ul class="decision-list">
              <li><label><input type="checkbox" data-review-field="firstTwoSecondHook"{first_hook_checked} /> First 2 seconds contain visible motion and a usable hook.</label></li>
              <li><label><input type="checkbox" data-review-field="artifactFree"{artifact_checked} /> No watermark, logo, baked-in text, flicker, morphing, or random extra subjects.</label></li>
              <li><label><input type="checkbox" data-review-field="continuityOk"{continuity_checked} /> Matches the shot bible subject, location, palette, and camera language.</label></li>
              <li><label><input type="checkbox" data-review-field="captionSafe"{caption_checked} /> Caption-safe area is not blocked by the main subject.</label></li>
              <li><label><input type="checkbox" data-review-field="shotLockMatch"{shot_lock_checked} /> Selected take matches the scene shot lock: action, first-second motion, identity, camera, and layout.</label></li>
              <li><label><input type="checkbox" data-review-field="sceneAssemblyOk"{scene_assembly_checked} /> Selected take has a concrete final-edit role and will cut naturally with neighboring scenes.</label></li>
              <li><label><input type="checkbox" data-review-field="sourceProvenanceConfirmed"{source_provenance_checked} /> Local MP4 came from Companion/pageAssets direct import or operator-owned manual upload, not browser currentSrc/preview cache.</label></li>
            </ul>
            <textarea class="note" data-review-field="sourceRationale" placeholder="source_rationale for accepted clip">{source_rationale}</textarea>
            <textarea class="note" data-review-field="qualityReviewNote" placeholder="quality_review_note for accepted clip">{quality_review_note}</textarea>
            <textarea class="note" data-review-field="selectedCandidateSummary" placeholder="candidate comparison: why the selected Grok take beats the other imported take(s)">{selected_candidate_summary}</textarea>
            <textarea class="note" data-review-field="sourceProvenanceNote" placeholder="source provenance: direct-import/manual-upload path and selected take filename">{source_provenance_note_value}</textarea>
            <textarea class="note" data-review-field="shotLockEvidenceNote" placeholder="shot-lock evidence: exact action, first-second motion, subject/prop/location/camera/layout match">{shot_lock_evidence_note}</textarea>
            <textarea class="note" data-review-field="sceneAssemblyRoleNote" placeholder="scene assembly role: hook/build/proof/payoff and how it cuts with adjacent scenes">{scene_assembly_role_note}</textarea>
            <div class="field-grid">
              <label>Visual verdict<select data-review-field="visualQualityVerdict"><option value=""></option><option value="pass"{' selected' if visual_quality_verdict == 'pass' else ''}>pass</option><option value="fail"{' selected' if visual_quality_verdict == 'fail' else ''}>fail</option><option value="needs-retry"{' selected' if visual_quality_verdict == 'needs-retry' else ''}>needs-retry</option></select></label>
              <label>Layout variant key<input data-review-field="layoutVariantKey" value="{layout_variant_key_value}" placeholder="pov-diary / character-continuity / ..." /></label>
              <label>Layout variant label<input data-review-field="layoutVariantLabel" value="{layout_variant_label_value}" placeholder="human-readable layout label" /></label>
            </div>
            <textarea class="note" data-review-field="captionLayoutReviewNote" placeholder="caption/layout review: subject visible, caption-safe lower/right zone, no occlusion">{caption_layout_review_note}</textarea>
            <textarea class="note" data-review-field="hookNote" placeholder="first-two-second hook note">{hook_note_value}</textarea>
            <textarea class="note" data-review-field="continuityNote" placeholder="continuity note: same subject/prop/location/palette/camera">{continuity_note_value}</textarea>
            <textarea class="note" data-review-field="layoutVariantNote" placeholder="layout variant note">{layout_variant_note_value}</textarea>
            <textarea class="note" data-review-field="thumbnailReviewNote" placeholder="thumbnail/first-frame review note">{thumbnail_review_note_value}</textarea>
            <textarea class="note" data-review-field="audioMixReviewNote" placeholder="BGM/native-audio/SFX mix review note">{audio_mix_review_note_value}</textarea>
            <textarea class="note" data-review-field="platformComparisonNote" placeholder="YouTube/Korean Shorts benchmark comparison note">{platform_comparison_note_value}</textarea>
            <textarea class="note" data-review-field="operatorNote" placeholder="Reject/accept notes, artifact details, continuity caveats">{operator_note}</textarea>
            {accept_block_reason}
            <div class="actions">
              <button type="button" data-review-accepted="true"{accept_disabled}>Accept clip</button>
              <button type="button" data-review-accepted="false" class="danger">Reject clip</button>
              <span data-save-status></span>
            </div>
          </div>
          <h3>Scene checklist</h3>
          <ul>{checklist}</ul>
        </section>
        """)

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Grok Clip Review - {escape(project_id)}</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #111315; color: #f3f4f6; }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    h2 {{ margin: 0; font-size: 18px; }}
    h3 {{ margin: 14px 0 6px; font-size: 13px; color: #d8dde6; text-transform: uppercase; letter-spacing: .04em; }}
    .meta, .path {{ color: #aeb6c2; line-height: 1.5; overflow-wrap: anywhere; }}
    .contract, .shot-bible {{ margin-top: 18px; padding: 14px; border: 1px solid #3f5368; border-radius: 8px; background: #151d27; }}
    .contract {{ border-color: #264653; color: #b6d7e8; background: #10212a; }}
    .scene-card {{ margin-top: 18px; padding: 16px; border: 1px solid #333a44; border-radius: 8px; background: #171b20; }}
    .scene-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }}
    .preview {{ margin-top: 12px; }}
    .take-ladder {{ margin-top: 12px; }}
    .take-card {{ margin-top: 10px; padding: 12px; border: 1px solid #3f5368; border-radius: 8px; background: #101821; }}
    video {{ width: min(360px, 100%); aspect-ratio: 9 / 16; background: #050608; border: 1px solid #30363f; border-radius: 8px; object-fit: cover; }}
    .candidate-picker {{ margin-top: 12px; padding: 12px; border: 1px solid #3f5368; border-radius: 8px; background: #101821; }}
    .candidate-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-top: 10px; }}
    .candidate-option {{ display: grid; gap: 7px; padding: 10px; border: 1px solid #30363f; border-radius: 8px; background: #0d1117; }}
    .candidate-option span {{ display: grid; gap: 3px; overflow-wrap: anywhere; }}
    .candidate-option small {{ color: #aeb6c2; }}
    .candidate-option video {{ width: 100%; max-height: 260px; }}
    .missing {{ padding: 20px; border: 1px dashed #515c6b; border-radius: 8px; color: #cfd7e3; background: #0d1014; }}
    .quality-gate {{ margin-top: 12px; padding: 12px; border: 1px solid #3f5368; border-radius: 8px; background: #111827; }}
    .quality-gate.warn {{ border-color: #8a6d2d; background: #201a0d; }}
    .quality-gate.pass {{ border-color: #1f7a4a; background: #0e2118; }}
    .quality-gate p {{ margin: 6px 0; color: #d8dde6; }}
    .quality-gate .probe {{ color: #b6d7e8; }}
    .shot-lock-text {{ white-space: pre-wrap; margin: 8px 0; padding: 10px; border: 1px solid #30363f; border-radius: 8px; background: #0d1117; color: #dbe6f2; line-height: 1.5; }}
    .curation-gate {{ margin-top: 12px; padding: 12px; border: 1px solid #3f5368; border-radius: 8px; background: #111827; }}
    .curation-gate.warn {{ border-color: #b45309; background: #211609; }}
    .curation-gate.pass {{ border-color: #1f7a4a; background: #0e2118; }}
    .curation-gate p {{ margin: 6px 0; color: #d8dde6; }}
    textarea, input, select {{ width: 100%; margin-top: 6px; box-sizing: border-box; background: #0b0d10; color: #f9fafb; border: 1px solid #3b4654; border-radius: 6px; padding: 10px; line-height: 1.45; }}
    textarea {{ min-height: 100px; margin-top: 10px; }}
    textarea.note {{ min-height: 84px; }}
    .field-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-top: 10px; }}
    .field-grid label {{ color: #cfd7e3; font-size: 12px; }}
    .actions {{ display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 10px; }}
    button {{ appearance: none; border: 1px solid #4b5563; border-radius: 6px; background: #2563eb; color: white; padding: 8px 10px; font-size: 14px; cursor: pointer; }}
    button:disabled {{ cursor: not-allowed; opacity: .45; }}
    button.danger {{ background: #7f1d1d; border-color: #b91c1c; }}
    [data-save-status] {{ color: #aeb6c2; font-size: 13px; }}
    code {{ color: #d1d5db; background: #0b0d10; border: 1px solid #30363f; border-radius: 4px; padding: 4px 6px; }}
    ul {{ margin: 8px 0 0 18px; padding: 0; color: #cfd7e3; line-height: 1.45; }}
    li + li {{ margin-top: 5px; }}
    summary {{ margin-top: 12px; cursor: pointer; color: #d8dde6; }}
    input[type="checkbox"] {{ margin-right: 7px; }}
  </style>
</head>
<body>
  <main>
    <h1>Grok clip review packet</h1>
    <p class="meta">Project: {escape(project_id)}<br />Incoming folder: {escape(incoming_dir)}</p>
    <div class="contract">Automation direction: Video Studio can open the worksheet and Grok, watch an operator-approved Downloads folder, import MP4s, and prepare render payloads. The operator still approves browser access, Grok sign-in, generation/download actions, and final accept/reject decisions. No paid xAI API, no credential storage, no source download deletion.</div>
    <section class="shot-bible">
      <h2>Shot bible</h2>
      <p><strong>Visual continuity:</strong> {escape(str(shot_bible.get("visualContinuity") or ""))}</p>
      <p><strong>Subject:</strong> {escape(str(shot_bible.get("subjectContinuity") or ""))}</p>
      <p><strong>Location:</strong> {escape(str(shot_bible.get("locationContinuity") or ""))}</p>
      <p><strong>Palette:</strong> {escape(str(shot_bible.get("palette") or ""))}</p>
      <p><strong>Camera:</strong> {escape(str(shot_bible.get("cameraLanguage") or ""))}</p>
      <p><strong>Production family:</strong> {escape(str(production_profile.get("family") or ""))}</p>
      <p><strong>Narrative shape:</strong> {escape(str(production_profile.get("narrativeShape") or ""))}</p>
      <p><strong>Layout plan:</strong> {escape(str(shot_bible.get("layoutPlan") or ""))}</p>
      <p><strong>Caption-safe plan:</strong> {escape(str(shot_bible.get("captionSafePlan") or ""))}</p>
      <p><strong>Motion plan:</strong> {escape(str(shot_bible.get("motionPlan") or ""))}</p>
      <p><strong>Negative prompts:</strong> {escape(negative_prompts)}</p>
      <p><strong>Grok target selection:</strong> {escape(str(target_selection.get("mode") or ""))} / minimum {escape(str(target_selection.get("minGrokMainScenes") or ""))}/{escape(str(target_selection.get("sourceMixTotalScenes") or ""))}</p>
      {auto_expansion_note}
      <h3>Global review checklist</h3>
      <ul>{review_items}</ul>
      <h3>Hard reject checklist</h3>
      <ul>{hard_reject_items}</ul>
    </section>
    {''.join(scene_cards)}
  </main>
  <script>
    const projectId = {json.dumps(project_id)};
    document.querySelectorAll('[data-review-scene]').forEach((form) => {{
      form.querySelectorAll('[data-review-accepted]').forEach((button) => {{
        button.addEventListener('click', async () => {{
          const payload = {{
            sceneId: form.getAttribute('data-review-scene'),
            accepted: button.getAttribute('data-review-accepted') === 'true',
          }};
          form.querySelectorAll('[data-review-field]').forEach((field) => {{
            const name = field.getAttribute('data-review-field');
            if (!name) return;
            if (field.type === 'checkbox') {{
              payload[name] = field.checked;
            }} else if (field.type === 'radio') {{
              if (field.checked) payload[name] = field.value;
            }} else {{
              payload[name] = field.value;
            }}
          }});
          const status = form.querySelector('[data-save-status]');
          if (status) status.textContent = 'Saving...';
          try {{
            const response = await fetch(`/api/grok-handoff/${{projectId}}/review-decision`, {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify(payload),
            }});
            const data = await response.json();
            if (!response.ok || !data.ok) {{
              throw new Error(data.error || 'save failed');
            }}
            const label = form.closest('.scene-card')?.querySelector('[data-review-label]');
            if (label) label.textContent = payload.accepted ? 'accepted' : 'rejected';
            if (status) status.textContent = payload.accepted ? 'Accepted and saved' : 'Rejected and saved';
          }} catch (error) {{
            if (status) status.textContent = error instanceof Error ? error.message : 'Save failed';
          }}
        }});
      }});
    }});
  </script>
</body>
</html>
"""
    review_packet_path = handoff_dir / "review-packet.html"
    review_packet_path.write_text(html, encoding="utf-8")
    return review_packet_path


def _draft_scene_id(item: dict, index: int) -> str:
    return _scene_id(item, index)


def _fallback_draft_scenes(manifest: dict) -> list[dict]:
    scenes = []
    for index, scene in enumerate(manifest.get("scenes") or []):
        prompt = str(scene.get("prompt") or "")
        scenes.append({
            "sceneId": str(scene.get("sceneId") or f"scene-{index + 1:02d}"),
            "scene_num": index + 1,
            "title": prompt[:80] or f"Grok scene {index + 1}",
            "narration": "",
            "display_text": "",
            "image_prompt": prompt,
            "image_source": "grok",
            "upload_kind": "video",
            "duration": 5,
            "caption_preset": "none",
            "grok_prompt": prompt,
        })
    return scenes


def _min_grok_main_scene_count(total_scenes: int) -> int:
    if total_scenes <= 0:
        return 0
    if total_scenes == 1:
        return 1
    return max(2, (total_scenes + 1) // 2)


def _grok_main_source_gate(manifest: dict, assets: list[dict]) -> dict:
    scenes = [item for item in (manifest.get("scenes") or []) if isinstance(item, dict)]
    target_selection = manifest.get("grokTargetSelection") if isinstance(manifest.get("grokTargetSelection"), dict) else {}
    review_decisions = manifest.get("reviewDecisions") if isinstance(manifest.get("reviewDecisions"), dict) else {}
    draft_scenes = _safe_draft_scenes(manifest.get("draftScenes"))
    first_hook_scene_id = str(target_selection.get("firstHookSceneId") or "")
    if not first_hook_scene_id and draft_scenes:
        first_hook_scene_id = _draft_scene_id(draft_scenes[0], 0)
    if not first_hook_scene_id and scenes:
        first_hook_scene_id = str(scenes[0].get("sceneId") or "scene-01")
    planned_scene_ids = {
        str(scene.get("sceneId") or f"scene-{index + 1:02d}")
        for index, scene in enumerate(scenes)
    }
    try:
        source_mix_total_scenes = int(manifest.get("sourceMixTotalScenes") or 0)
    except (TypeError, ValueError):
        source_mix_total_scenes = 0
    if source_mix_total_scenes <= 0:
        source_mix_total_scenes = len(manifest.get("draftScenes") or []) or len(planned_scene_ids)
    min_required = _min_grok_main_scene_count(source_mix_total_scenes)
    try:
        configured_min = int(manifest.get("minGrokMainScenes") or 0)
    except (TypeError, ValueError):
        configured_min = 0
    if configured_min > 0:
        min_required = configured_min
    required = manifest.get("grokMainSourceRequired") is True
    local_ready_scene_ids = {
        str(item.get("sceneId"))
        for item in assets
        if item.get("status") == "ready" and item.get("sceneId")
    }
    replacement_scene_ids = {
        str(item.get("sceneId"))
        for item in assets
        if _grok_asset_needs_replacement(item, manifest)
    }
    ready_scene_ids = local_ready_scene_ids - replacement_scene_ids
    accepted_scene_ids = {
        str(item.get("sceneId"))
        for item in assets
        if item.get("status") == "ready"
        and item.get("sceneId")
        and item.get("qualityGate", {}).get("status") == "accepted"
    }
    review_accepted_scene_ids = {
        scene_id
        for scene_id in ready_scene_ids
        if isinstance(review_decisions.get(scene_id), dict)
        and review_decisions[scene_id].get("accepted") is True
    }
    pending_scene_ids = sorted(
        str(item.get("sceneId"))
        for item in assets
        if item.get("status") == "ready"
        and item.get("sceneId")
        and item.get("qualityGate", {}).get("status") in {"pending-operator-review", "review-recommended", "shot-lock-review"}
    )
    rejected_scene_ids = sorted(
        str(item.get("sceneId"))
        for item in assets
        if item.get("status") == "ready"
        and item.get("sceneId")
        and item.get("qualityGate", {}).get("status") == "rejected"
    )
    candidate_count_by_scene_id = {
        str(item.get("sceneId")): _grok_asset_candidate_count(item)
        for item in assets
        if item.get("status") == "ready" and item.get("sceneId")
    }
    asset_by_scene_id = {
        str(item.get("sceneId")): item
        for item in assets
        if item.get("status") == "ready" and item.get("sceneId")
    }
    candidate_curation_gap_scene_ids = sorted(
        scene_id
        for scene_id in review_accepted_scene_ids
        if candidate_count_by_scene_id.get(scene_id, 0) < 2
    )
    review_evidence_missing_by_scene_id = {
        scene_id: missing
        for scene_id, decision in review_decisions.items()
        if scene_id in ready_scene_ids
        for missing in [_grok_main_review_evidence_missing(
            decision,
            asset_by_scene_id.get(scene_id, {}).get("sourceProvenance")
            if isinstance(asset_by_scene_id.get(scene_id), dict)
            else None,
        )]
        if missing
    }
    review_evidence_gap_scene_ids = sorted(review_evidence_missing_by_scene_id)
    missing_scene_ids = sorted(planned_scene_ids - ready_scene_ids)
    additional_accepted_needed = max(0, min_required - len(accepted_scene_ids))
    additional_planned_needed = max(0, min_required - len(planned_scene_ids))
    first_hook_required = required and bool(first_hook_scene_id)
    first_hook_planned = bool(first_hook_scene_id and first_hook_scene_id in planned_scene_ids)
    first_hook_ready = bool(first_hook_scene_id and first_hook_scene_id in ready_scene_ids)
    first_hook_accepted = bool(first_hook_scene_id and first_hook_scene_id in accepted_scene_ids)
    if not required:
        status = "not-required"
    elif first_hook_required and not first_hook_planned:
        status = "needs-first-hook-grok-scene"
    elif additional_planned_needed:
        status = "needs-more-grok-scenes"
    elif candidate_curation_gap_scene_ids:
        status = "needs-candidate-curation"
    elif review_evidence_gap_scene_ids:
        status = "needs-shot-lock-review-evidence"
    elif first_hook_required and not first_hook_accepted:
        status = "needs-first-hook-grok-clip"
    elif additional_accepted_needed:
        status = "needs-accepted-grok-clips"
    elif rejected_scene_ids:
        status = "needs-replacement-clips"
    else:
        status = "ready"
    return {
        "required": required,
        "status": status,
        "allReady": (not required) or status == "ready",
        "sourceMixTotalScenes": source_mix_total_scenes,
        "plannedGrokScenes": len(planned_scene_ids),
        "minAcceptedScenes": min_required,
        "acceptedSceneIds": sorted(accepted_scene_ids),
        "readySceneIds": sorted(ready_scene_ids),
        "localReadySceneIds": sorted(local_ready_scene_ids),
        "replacementSceneIds": sorted(replacement_scene_ids),
        "pendingSceneIds": pending_scene_ids,
        "rejectedSceneIds": rejected_scene_ids,
        "missingSceneIds": missing_scene_ids,
        "firstHookRequired": first_hook_required,
        "firstHookSceneId": first_hook_scene_id,
        "firstHookPlanned": first_hook_planned,
        "firstHookReady": first_hook_ready,
        "firstHookAccepted": first_hook_accepted,
        "candidateCurationRequired": required,
        "candidateCurationGapSceneIds": candidate_curation_gap_scene_ids,
        "candidateCountBySceneId": candidate_count_by_scene_id,
        "reviewEvidenceGapSceneIds": review_evidence_gap_scene_ids,
        "reviewEvidenceMissingBySceneId": review_evidence_missing_by_scene_id,
        "additionalAcceptedScenesNeeded": additional_accepted_needed,
        "additionalPlannedScenesNeeded": additional_planned_needed,
        "plannedSceneIds": sorted(planned_scene_ids),
        "autoExpandedSceneIds": target_selection.get("autoExpandedSceneIds") or [],
        "targetSelectionMode": target_selection.get("mode") or "",
        "detail": (
            "Grok-main top-tier source mix requires reviewed Grok MP4s for at least "
            f"{min_required}/{source_mix_total_scenes} scenes; keep Pexels as support B-roll."
        ),
    }


def _secondary_automation_blocker(
    automation_status: dict | None,
    automation_job: dict | None,
) -> dict:
    surfaces = []
    for item in (automation_status, automation_job):
        if isinstance(item, dict):
            surfaces.append(item)
            nested = item.get("automationStatus")
            if isinstance(nested, dict):
                surfaces.append(nested)
    for surface in surfaces:
        browser_blocker = str(surface.get("browserBlocker") or "").strip()
        operator_next_action = str(surface.get("operatorNextAction") or "").strip()
        if browser_blocker:
            return {
                "blocker": browser_blocker,
                "operatorNextAction": operator_next_action,
                "status": str(surface.get("status") or ""),
                "detail": str(surface.get("detail") or surface.get("error") or ""),
            }
        error_text = str(surface.get("error") or surface.get("detail") or "").strip()
        if error_text:
            try:
                port = _bounded_int(surface.get("remoteDebuggingPort"), default=9222, minimum=9000, maximum=65535)
            except Exception:
                port = 9222
            error_state = _automation_error_state(error_text, port)
            if error_state.get("requiresOperatorAction") is True:
                return {
                    "blocker": str(error_state.get("browserBlocker") or ""),
                    "operatorNextAction": str(error_state.get("operatorNextAction") or operator_next_action),
                    "status": str(surface.get("status") or "failed"),
                    "detail": error_text,
                }
    return {}


def _observed_grok_post_import_plan(
    project_id: str,
    manifest: dict,
    next_scene: dict | None,
    generation_observation: dict | None,
) -> dict:
    if not isinstance(generation_observation, dict):
        return {}
    observation_status = str(generation_observation.get("status") or "").strip()
    if observation_status not in {"generated", "generated-export-pending", "post-created"}:
        return {}

    scene_id = str(
        generation_observation.get("sceneId")
        or (next_scene or {}).get("sceneId")
        or ""
    ).strip()
    expected_file = str(
        generation_observation.get("expectedFileName")
        or (next_scene or {}).get("expectedFileName")
        or f"{scene_id}.grok.mp4"
    ).strip()
    post_url = str(generation_observation.get("postUrl") or "").strip()
    download_defaults = _download_defaults_for_manifest(manifest)
    default_download_dir = str(download_defaults.get("defaultDownloadDir") or "").strip()
    ready = bool(scene_id and post_url and default_download_dir)
    disabled_reason = ""
    if not scene_id:
        disabled_reason = "observed sceneId is missing"
    elif not post_url:
        disabled_reason = "observed Grok post URL is missing"
    elif not default_download_dir:
        disabled_reason = "default Downloads folder is missing; enter a downloadDir first"

    upload_endpoint = f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/upload-mp4"
    post_download_command = {
        "ok": True,
        "projectId": project_id,
        "sceneId": scene_id,
        "expectedFileName": expected_file,
        "uploadEndpoint": upload_endpoint,
    }
    post_download_script = _observed_post_download_javascript(project_id, post_download_command)
    post_download_script_query = {"operatorApproved": "true"}
    if scene_id:
        post_download_script_query["sceneId"] = scene_id
    post_download_script_url = (
        f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/observed-post-download.js?"
        + urllib.parse.urlencode(post_download_script_query)
    )

    return {
        "available": True,
        "ready": ready,
        "mode": "observed-grok-post-direct-import-only",
        "usesPaidApi": False,
        "storesCredentials": False,
        "sceneId": scene_id,
        "expectedFileName": expected_file,
        "postUrl": post_url,
        "videoUrl": str(generation_observation.get("videoUrl") or "").strip(),
        "observedAssetManualRunwayUrl": _observed_asset_manual_runway_url(project_id, scene_id or None),
        "observedAssetManualRunwayEndpoint": f"/api/grok-handoff/{project_id}/observed-asset-manual-runway",
        "observedPostDownloadEndpoint": f"/api/grok-handoff/{project_id}/observed-post-download.js",
        "observedPostDownloadScriptUrl": post_download_script_url,
        "observedPostDownloadInlineUrl": _inline_bookmarklet_url(post_download_script),
        "observedPostDownloadConsoleSnippet": post_download_script.strip(),
        "uploadEndpoint": upload_endpoint,
        "downloadDir": default_download_dir,
        "manualWatchEndpoint": f"/api/grok-handoff/{project_id}/manual-download-watch",
        "importDownloadsEndpoint": f"/api/grok-handoff/{project_id}/import-downloads",
        "manualBatchUploadEndpoint": f"/api/grok-handoff/{project_id}/upload-mp4-batch",
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        "localMp4ImportRequired": True,
        "directAssetFetch": {
            "serverFetchSupported": False,
            "expectedFailure": "403-or-browser-session-bound",
            "reason": (
                "Observed Grok asset URLs can require the signed-in browser session. "
                "Video Studio should not curl or proxy those bytes with stored credentials; "
                "the browser-side recovery script fetches eligible MP4/blob candidates "
                "inside the signed-in Grok tab and posts them to the local uploadEndpoint."
            ),
            "approvedPath": "browser-side-fetch-to-local-uploadEndpoint-direct-import-only",
        },
        "manualWatchRequest": {
            "operatorApproved": True,
            "downloadDir": default_download_dir,
            "sceneId": scene_id,
            "allowNewestFallback": True,
            "sinceHandoff": True,
            "preserveCandidates": True,
            "stopOnImport": True,
            "timeoutSeconds": 7200,
            "pollIntervalSeconds": 2,
        },
        "disabledReason": disabled_reason,
        "operatorSteps": [
            "Open the observed Grok post in the existing signed-in Chrome profile.",
            "Run the observed-post direct-import console snippet from that Grok post tab.",
            "The snippet fetches an eligible MP4/blob candidate inside the signed-in Grok tab and uploads it to Video Studio without Chrome's download approval dialog.",
            "If direct import fails, the snippet stops and records status; it does not click Download, Save, Export, or an anchor download.",
            "Use separate manual batch upload or Downloads watch only after explicit human action outside this proof snippet.",
            "Review the imported candidate for motion, artifacts, continuity, safe caption framing, and first-two-second hook before render.",
        ],
        "qualityNote": (
            "Observed-post proof is direct-import only and never clicks Grok Download/Save/Export. "
            "Visible video/currentSrc fallback is proof only and must still pass the source-quality floor; "
            "treat the observed Grok clip as the main visual source candidate, not a finished asset. "
            "Video Studio still owns candidate review, captions, BGM, layout, and render."
        ),
    }


def _grok_main_path_status(
    project_id: str,
    handoff_dir: Path,
    manifest: dict,
    assets: list[dict],
    main_source_gate: dict,
    scene_queue: dict,
    next_scene: dict | None,
    manual_primary_path: dict,
    automation_status: dict | None = None,
    automation_job: dict | None = None,
    manual_download_watch_job: dict | None = None,
    companion_connection: dict | None = None,
    generation_observation: dict | None = None,
) -> dict:
    local_ready_assets = [item for item in assets if item.get("status") == "ready"]
    ready_assets = _grok_status_ready_assets(manifest, assets)
    asset_present_scene_ids = sorted(
        {
            str(item.get("sceneId"))
            for item in local_ready_assets
            if item.get("sceneId")
        }
    )
    ready_scene_ids = sorted(
        {
            str(item.get("sceneId"))
            for item in ready_assets
            if item.get("sceneId")
        }
    )
    gate_required = main_source_gate.get("required") is True
    gate_status = str(main_source_gate.get("status") or "")
    next_scene_id = str((next_scene or {}).get("sceneId") or scene_queue.get("nextMissingSceneId") or "").strip()
    expected_file = str((next_scene or {}).get("expectedFileName") or scene_queue.get("nextMissingExpectedFileName") or "").strip()
    current_scene = manual_primary_path.get("currentScene") if isinstance(manual_primary_path.get("currentScene"), dict) else {}
    if not next_scene_id:
        next_scene_id = str(current_scene.get("sceneId") or "").strip()
    if not expected_file:
        expected_file = str(current_scene.get("expectedFileName") or "").strip()
    recommended_take_number = current_scene.get("recommendedTakeNumber")
    recommended_take_label = str(current_scene.get("recommendedTakeLabel") or "").strip()

    if not gate_required:
        status = "not-required"
        blocker = ""
        summary = "Grok-main source mix is not required for this handoff."
    elif gate_status == "ready":
        status = "ready"
        blocker = ""
        summary = "Reviewed Grok app/web MP4 clips satisfy the Grok-main source gate."
    elif (
        not local_ready_assets
        and isinstance(generation_observation, dict)
        and str(generation_observation.get("status") or "") in {"generated", "generated-export-pending", "post-created"}
    ):
        status = "generated-export-pending"
        blocker = "grok-mp4-export-import-pending"
        summary = (
            "Grok generation succeeded in the logged-in Chrome/SuperGrok session; "
            "the remaining blocker is exporting/downloading that MP4 and importing it into Video Studio."
        )
    elif not local_ready_assets:
        status = "needs-first-grok-mp4"
        blocker = "first-grok-mp4-missing"
        summary = (
            "Grok is still viable as the main visual source; the current blocker is "
            "acquiring and importing the first Grok app/web MP4, not xAI API access."
        )
    elif gate_status == "needs-candidate-curation":
        status = "needs-candidate-curation"
        blocker = "grok-take-curation-missing"
        summary = "Imported Grok MP4s need multiple takes and an operator-selected best candidate before render."
    elif gate_status == "needs-first-hook-grok-clip" and main_source_gate.get("firstHookReady"):
        status = "needs-first-hook-review"
        blocker = "first-hook-grok-review-missing"
        summary = "The first hook Grok MP4 exists but still needs review acceptance."
    elif main_source_gate.get("replacementSceneIds"):
        status = "needs-replacement-grok-mp4s"
        blocker = "quality-replacement-grok-clips"
        summary = "Low-quality or source-unverified Grok clips need replacement takes before later scenes advance."
    elif main_source_gate.get("missingSceneIds"):
        status = "needs-more-grok-mp4s"
        blocker = "planned-grok-mp4s-missing"
        summary = "More planned Grok scene MP4s must be generated/imported before the source mix can render."
    elif main_source_gate.get("pendingSceneIds"):
        status = "needs-grok-review"
        blocker = "grok-review-missing"
        summary = "Imported Grok MP4s need quality review for hook, motion, continuity, artifacts, and caption-safe framing."
    elif main_source_gate.get("rejectedSceneIds"):
        status = "needs-replacement-grok-mp4s"
        blocker = "rejected-grok-clips"
        summary = "Rejected Grok clips need replacement takes before the source gate can pass."
    else:
        status = "needs-accepted-grok-clips"
        blocker = "accepted-grok-clips-missing"
        summary = "Grok MP4s are present or planned, but not enough have been accepted for the Grok-main source gate."

    blocked = status not in {"ready", "not-required"}
    if status == "generated-export-pending":
        observed_scene = str((generation_observation or {}).get("sceneId") or next_scene_id or "the current scene").strip()
        observed_file = str((generation_observation or {}).get("expectedFileName") or expected_file or "the Grok MP4").strip()
        post_url = str((generation_observation or {}).get("postUrl") or "").strip()
        primary_next_action = (
            f"Open the observed Grok post for {observed_scene}, download {observed_file}, "
            "then use Grok MP4 batch upload or Downloads import so Video Studio can review it."
        )
        if post_url:
            primary_next_action += f" Post: {post_url}"
    elif status == "needs-first-hook-review":
        first_hook_scene_id = str(main_source_gate.get("firstHookSceneId") or next_scene_id or "scene-01").strip()
        first_hook_asset = next(
            (
                item for item in local_ready_assets
                if str(item.get("sceneId") or "") == first_hook_scene_id
            ),
            {},
        )
        first_hook_gate = first_hook_asset.get("qualityGate") if isinstance(first_hook_asset.get("qualityGate"), dict) else {}
        technical_issues = first_hook_gate.get("technicalIssues") if isinstance(first_hook_gate.get("technicalIssues"), list) else []
        if first_hook_gate.get("technicalOk") is False or technical_issues:
            issue_text = "; ".join(str(item) for item in technical_issues if item) or "technical review failed"
            primary_next_action = (
                f"Replace {first_hook_scene_id} with a browser-native/direct-imported or operator-uploaded Grok MP4 before generating later scenes. "
                f"The current first hook is not acceptable for Grok-main ({issue_text})."
            )
        else:
            primary_next_action = (
                f"Open the review packet and accept or reject {first_hook_scene_id} before moving to later scenes; "
                "the first two seconds must carry the hook for the Grok-main cut."
            )
    elif status == "needs-replacement-grok-mp4s" and next_scene_id:
        replacement_asset = next(
            (
                item for item in local_ready_assets
                if str(item.get("sceneId") or "") == next_scene_id
            ),
            {},
        )
        replacement_gate = replacement_asset.get("qualityGate") if isinstance(replacement_asset.get("qualityGate"), dict) else {}
        technical_issues = replacement_gate.get("technicalIssues") if isinstance(replacement_gate.get("technicalIssues"), list) else []
        source_issues = replacement_gate.get("sourceIssues") if isinstance(replacement_gate.get("sourceIssues"), list) else []
        issue_text = "; ".join(str(item) for item in [*technical_issues, *source_issues] if item) or "quality/source gate failed"
        primary_next_action = (
            f"Replace {next_scene_id} with a browser-native/direct-imported or operator-uploaded Grok MP4 before generating later scenes. "
            f"The current Grok-main candidate is not acceptable ({issue_text})."
        )
    elif next_scene_id and status != "ready":
        take_text = f" Take {recommended_take_number}" if recommended_take_number else ""
        if recommended_take_label:
            take_text = f"{take_text} / {recommended_take_label}".strip()
        primary_next_action = (
            f"Generate {next_scene_id}{(' ' + take_text) if take_text else ''} in the signed-in Grok app/web, "
            f"download {expected_file or 'the MP4'}, then import/watch it as a Video Studio candidate."
        )
    elif status == "ready":
        primary_next_action = "Render the Grok-main cut from reviewed MP4 scene assets."
    else:
        primary_next_action = "Review accepted Grok clips, then render when the source gate is ready."

    secondary_blocker = _secondary_automation_blocker(automation_status, automation_job)
    manual_watch_active = bool(
        isinstance(manual_download_watch_job, dict)
        and str(manual_download_watch_job.get("status") or "") in {"queued", "running"}
    )
    observed_post_import_plan = _observed_grok_post_import_plan(
        project_id,
        manifest,
        next_scene,
        generation_observation,
    )
    asset_acquisition = _grok_asset_acquisition_status(
        status=status,
        ready_assets=local_ready_assets,
        next_scene_id=next_scene_id,
        expected_file=expected_file,
        generation_observation=generation_observation,
        observed_post_import_plan=observed_post_import_plan,
        manual_watch_active=manual_watch_active,
        companion_connection=companion_connection,
    )
    return {
        "mode": "grok-app-web-mp4-primary",
        "status": status,
        "blocked": blocked,
        "blocker": blocker,
        "summary": summary,
        "primaryPath": "signed-in-grok-app-web-mp4",
        "primaryPathDetail": (
            "Use the existing logged-in Chrome/SuperGrok app or grok.com session to create short raw MP4 clips; "
            "Video Studio handles import, candidate review, captions, BGM, layout, and render."
        ),
        "primaryNextAction": primary_next_action,
        "operatorNextAction": manual_primary_path.get("operatorNextAction"),
        "usesPaidApi": False,
        "paidApiPolicy": "Do not call Grok API or paid video APIs; only operator-owned Grok app/web MP4 exports are accepted.",
        "grokAppWebViable": True,
        "cdpPrimaryRecommended": False,
        "secondaryAutomationRole": "secondary-experimental",
        "secondaryAutomationBlocker": secondary_blocker.get("blocker") or "",
        "secondaryAutomationStatus": secondary_blocker.get("status") or str((automation_status or {}).get("status") or ""),
        "secondaryAutomationDetail": secondary_blocker.get("operatorNextAction") or secondary_blocker.get("detail") or "",
        "companionConnected": bool((companion_connection or {}).get("connected")),
        "companionConnectionStatus": str((companion_connection or {}).get("status") or ""),
        "manualWatchActive": manual_watch_active,
        "projectId": project_id,
        "handoffDir": str(handoff_dir),
        "incomingDir": manifest.get("incomingDir") or str(handoff_dir / "incoming"),
        "productionQueueUrl": manifest.get("productionQueueUrl") or _production_queue_url(project_id),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "nextSceneId": next_scene_id,
        "nextExpectedFileName": expected_file,
        "recommendedTakeNumber": recommended_take_number,
        "recommendedTakeLabel": recommended_take_label,
        "readyScenes": len(ready_assets),
        "readySceneIds": ready_scene_ids,
        "assetPresentScenes": len(asset_present_scene_ids),
        "assetPresentSceneIds": asset_present_scene_ids,
        "totalScenes": len(manifest.get("scenes") or []),
        "acceptedSceneIds": main_source_gate.get("acceptedSceneIds") or [],
        "requiredAcceptedScenes": main_source_gate.get("minAcceptedScenes") if gate_required else 0,
        "mainSourceGateStatus": gate_status,
        "generationObservation": generation_observation or {},
        "observedPostImportPlan": observed_post_import_plan,
        "assetAcquisition": asset_acquisition,
        "originalExportPlan": asset_acquisition.get("originalExportPlan") if isinstance(asset_acquisition, dict) else {},
        "notBlockedBy": [
            "xAI API pricing or quota is not required",
            "paid video APIs are not required",
            "render/caption/BGM pipeline can run after local MP4 import",
            *(
                ["logged-in Chrome/SuperGrok generation has been observed"]
                if generation_observation
                else []
            ),
        ],
        "proofPoints": [
            "usesPaidApi=false",
            f"readyScenes={len(ready_assets)}/{len(manifest.get('scenes') or [])}",
            f"assetPresentScenes={len(asset_present_scene_ids)}/{len(manifest.get('scenes') or [])}",
            f"mainSourceGate={gate_status or 'unknown'}",
            "CDP/default-profile automation is secondary, not the main production path",
            *(
                [
                    f"codexChromeObservation={generation_observation.get('status')}",
                    f"observedPost={generation_observation.get('postUrl') or 'none'}",
                ]
                if isinstance(generation_observation, dict)
                else []
            ),
        ],
    }


def _grok_asset_acquisition_status(
    *,
    status: str,
    ready_assets: list[dict],
    next_scene_id: str,
    expected_file: str,
    generation_observation: dict | None,
    observed_post_import_plan: dict,
    manual_watch_active: bool,
    companion_connection: dict | None,
) -> dict:
    observation_status = str((generation_observation or {}).get("status") or "").strip()
    clip_generated = observation_status in {"generated", "generated-export-pending", "post-created"}
    local_mp4_imported = bool(ready_assets)
    local_candidate_summaries: list[dict] = []
    quality_blockers: list[str] = []
    for asset in ready_assets:
        if not isinstance(asset, dict):
            continue
        scene_id = str(asset.get("sceneId") or "scene")
        candidates = asset.get("candidateAssets") if isinstance(asset.get("candidateAssets"), list) else []
        if not candidates:
            candidates = [asset]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            probe = candidate.get("clipProbe") if isinstance(candidate.get("clipProbe"), dict) else {}
            summary = {
                "sceneId": scene_id,
                "fileName": str(candidate.get("fileName") or asset.get("fileName") or ""),
                "width": probe.get("width"),
                "height": probe.get("height"),
                "fps": probe.get("fps"),
                "durationSec": probe.get("durationSec"),
                "technicalOk": probe.get("ok") is True,
                "motionOk": probe.get("motionOk") is True,
                "motionStatus": str(probe.get("motionStatus") or ""),
                "issues": probe.get("issues") if isinstance(probe.get("issues"), list) else [],
                "sourceProvenance": (
                    candidate.get("sourceProvenance")
                    if isinstance(candidate.get("sourceProvenance"), dict)
                    else {}
                ),
            }
            if summary["fileName"]:
                local_candidate_summaries.append(summary)
            source_provenance = summary["sourceProvenance"]
            if source_provenance.get("acceptAsGrokMainSource") is False:
                quality_blockers.append(
                    f"{scene_id}: {source_provenance.get('operatorAction') or 'source provenance requires original Grok MP4 replacement'}"
                )
        gate = asset.get("qualityGate") if isinstance(asset.get("qualityGate"), dict) else {}
        if gate.get("status") in {"technical-review", "source-review", "shot-lock-review"} or gate.get("technicalOk") is False:
            issues = gate.get("technicalIssues") if isinstance(gate.get("technicalIssues"), list) else []
            source_issues = gate.get("sourceIssues") if isinstance(gate.get("sourceIssues"), list) else []
            review_issues = gate.get("reviewEvidenceMissing") if isinstance(gate.get("reviewEvidenceMissing"), list) else []
            if issues:
                for issue in issues:
                    quality_blockers.append(f"{scene_id}: {issue}")
            elif source_issues:
                for issue in source_issues:
                    quality_blockers.append(f"{scene_id}: {issue}")
            elif review_issues:
                quality_blockers.append(f"{scene_id}: missing review evidence: {', '.join(str(item) for item in review_issues[:4])}")
            else:
                quality_blockers.append(f"{scene_id}: technical review required")
    best_local_candidate = None
    if local_candidate_summaries:
        best_local_candidate = sorted(
            local_candidate_summaries,
            key=lambda item: (
                1 if item.get("technicalOk") else 0,
                int(item.get("height") or 0),
                int(item.get("width") or 0),
            ),
            reverse=True,
        )[0]
    scene_label = next_scene_id or str((generation_observation or {}).get("sceneId") or "current scene")
    file_label = expected_file or str((generation_observation or {}).get("expectedFileName") or "scene Grok MP4")
    candidate_items: list[dict] = []
    for candidate in local_candidate_summaries:
        provenance = candidate.get("sourceProvenance") if isinstance(candidate.get("sourceProvenance"), dict) else {}
        source_ok = provenance.get("acceptAsGrokMainSource") is True
        technical_ok = candidate.get("technicalOk") is True
        motion_ok = candidate.get("motionOk") is True
        height = int(candidate.get("height") or 0)
        width = int(candidate.get("width") or 0)
        score = 0
        score += 40 if source_ok else 0
        score += 30 if technical_ok else 0
        score += 15 if height >= 1080 else max(0, min(10, height // 120))
        score += 10 if motion_ok else 0
        score += 5 if width and height else 0
        reject_reasons: list[str] = []
        if not source_ok:
            reject_reasons.append(
                str(provenance.get("operatorAction") or "source is not proven as browser-native/direct-imported or operator-uploaded Grok MP4")
            )
        if not technical_ok:
            reject_reasons.extend(str(item) for item in (candidate.get("issues") or []) if item)
        if not motion_ok:
            reject_reasons.append(f"motion status: {candidate.get('motionStatus') or 'unknown'}")
        candidate_items.append({
            "sceneId": candidate.get("sceneId"),
            "fileName": candidate.get("fileName"),
            "width": candidate.get("width"),
            "height": candidate.get("height"),
            "fps": candidate.get("fps"),
            "durationSec": candidate.get("durationSec"),
            "technicalOk": technical_ok,
            "motionOk": motion_ok,
            "sourceAcceptable": source_ok,
            "sourceStatus": str(provenance.get("status") or ""),
            "score": score,
            "rejectReasons": reject_reasons[:5],
        })
    candidate_items = sorted(
        candidate_items,
        key=lambda item: (
            int(item.get("score") or 0),
            int(item.get("height") or 0),
            int(item.get("width") or 0),
        ),
        reverse=True,
    )
    publishable_candidates = [
        item for item in candidate_items
        if item.get("technicalOk") is True and item.get("sourceAcceptable") is True and item.get("motionOk") is True
    ]
    if not candidate_items:
        curation_recommendation = (
            f"Generate and import at least two native Grok MP4 takes for {next_scene_id or scene_label}; "
            "candidate comparison cannot start from a post URL or placeholder."
        )
    elif len(candidate_items) < 2:
        curation_recommendation = (
            "Import a second native Grok MP4 take before accepting the scene; single-candidate Grok-main approval "
            "does not meet the current quality bar."
        )
    elif not publishable_candidates:
        curation_recommendation = (
            "Do not render from the current candidates. They are proof-only or below the technical/source floor; "
            "replace with two browser-native/direct-imported or operator-uploaded Grok MP4 takes."
        )
    else:
        curation_recommendation = (
            "Compare the top two native candidates in the review packet and accept only after layout, hook, "
            "continuity, artifact, audio-fit, and platform comparison notes are complete."
        )
    candidate_curation_plan = {
        "required": status not in {"ready", "not-required"},
        "targetSceneId": next_scene_id or scene_label,
        "expectedFileName": expected_file or file_label,
        "candidateCount": len(candidate_items),
        "publishableCandidateCount": len(publishable_candidates),
        "minimumCandidates": 2,
        "selectedCandidate": candidate_items[0] if candidate_items else {},
        "candidates": candidate_items[:6],
        "recommendation": curation_recommendation,
        "reviewReadiness": (
            "ready-for-operator-review"
            if len(publishable_candidates) >= 1 and len(candidate_items) >= 2
            else "needs-native-grok-takes"
        ),
        "selectionRule": (
            "Prefer browser-native/direct-imported or operator-uploaded Grok MP4 provenance first, then technical 9:16 quality, "
            "visible motion, continuity, caption-safe composition, and fewer artifacts. Never select browser cache/currentSrc proof as main footage."
        ),
    }
    quality_blocked = bool(quality_blockers)
    publish_ready_local_mp4 = local_mp4_imported and not quality_blocked
    companion_connected = bool((companion_connection or {}).get("connected"))
    observed_post_url = str((generation_observation or {}).get("postUrl") or observed_post_import_plan.get("postUrl") or "").strip()
    observed_asset_url = str((generation_observation or {}).get("videoUrl") or observed_post_import_plan.get("videoUrl") or "").strip()

    if local_mp4_imported:
        if quality_blocked:
            acquisition_state = "local-mp4-imported-needs-quality-replacement"
            blocker_scope = "source-quality"
            operator_actions = [
                "Treat the imported MP4 as recovery proof only; replace it with an original Grok download or batch-uploaded source before final render.",
                f"Open the Grok post/app for {scene_label}, export the highest available MP4, and import it as {file_label} or an additional candidate.",
                "Do not accept a cache/proxy clip whose technical review reports low height, low motion, bad aspect ratio, or decode issues.",
            ]
        else:
            acquisition_state = "local-mp4-imported"
            blocker_scope = ""
            operator_actions = [
                f"Open the Grok review packet and compare imported {scene_label} take candidates before acceptance.",
                "Reject the clip if the first two seconds are weak, captions would cover the subject, or visual artifacts are visible.",
            ]
    elif clip_generated:
        acquisition_state = "watching-downloads-for-generated-clip" if manual_watch_active else "generated-awaiting-local-mp4"
        blocker_scope = "asset-export-import-only"
        operator_actions = []
        if observed_asset_url:
            operator_actions.append(
                "Reload the Video Studio Grok Companion in the signed-in Chrome profile, activate the observed MP4 asset tab, and use uploadEndpoint direct-import only; do not click Grok Download/Save from Codex automation."
            )
        if observed_post_url:
            operator_actions.append(
                f"Open the observed Grok post for {scene_label}, prefer observed-post direct import to {file_label}; manual Grok Download/Save is operator fallback only."
            )
        operator_actions.extend([
            "Use Downloads watch only after an operator-confirmed manual download or batch upload fallback, not as an automatic Codex action.",
            "If browser download automation still fails, use Grok MP4 batch upload and map the file to the current scene.",
        ])
    else:
        acquisition_state = "needs-grok-generation"
        blocker_scope = "first-grok-generation-missing"
        operator_actions = [
            f"Generate {scene_label} in the signed-in Grok app/web using the recommended take prompt.",
            f"Download {file_label}, then import it as a Video Studio candidate before any publish-ready render.",
        ]

    original_export_required = status not in {"ready", "not-required"} and not publish_ready_local_mp4
    if quality_blocked:
        original_export_priority = "replace-existing-candidate"
        export_summary = (
            "Grok/SuperGrok is still the intended main source. The blocker is that the current local "
            "candidate is proof-only or below the source-quality floor, so a fresh native Grok MP4 export is required."
        )
        export_blocker = quality_blockers[0] if quality_blockers else "source-quality-floor"
    elif clip_generated and not local_mp4_imported:
        original_export_priority = "export-generated-clip"
        export_summary = (
            "Grok generation has been observed; the remaining gate is saving/downloading the browser-native MP4 "
            "from the signed-in Grok app/web session and importing it locally."
        )
        export_blocker = "generated-mp4-not-imported"
    elif not local_mp4_imported:
        original_export_priority = "generate-then-export"
        export_summary = (
            "Grok is available as the primary visual source, but this scene still needs a generated MP4 from the "
            "signed-in Grok app/web before Video Studio can review or render it."
        )
        export_blocker = "grok-generation-missing"
    else:
        original_export_priority = "review-imported-original"
        export_summary = "A local Grok MP4 exists; Video Studio should compare takes and review it before render."
        export_blocker = ""

    original_export_plan = {
        "required": original_export_required,
        "priority": original_export_priority,
        "modelBlocked": False,
        "accountBlocked": False,
        "paidApiRequired": False,
        "cdpPrimary": False,
        "summary": export_summary,
        "currentBlocker": export_blocker,
        "targetSceneId": scene_label,
        "expectedFileName": file_label,
        "nativeExportRequired": original_export_required,
        "reason": "Grok-main depends on operator-owned Grok app/web MP4 exports, not the Grok/xAI API or CDP.",
        "requiredActions": [
            f"Generate two fresh Grok takes for {scene_label} using the recommended motion-first prompt.",
            "Use Companion/pageAssets direct import first; if that fails, use only operator-owned manual batch upload.",
            f"Import the Grok MP4 as {file_label}, or use grouped batch order when the filename is not controllable.",
            "Keep both takes as candidates until Video Studio comparison selects one.",
            "Approve only after first-two-second hook, visible motion, continuity, artifact, caption-safe layout, and audio-fit review.",
        ],
        "rejectAsMainSource": [
            "browser currentSrc or cache copy",
            "visible preview capture",
            "low-resolution proxy or preview MP4",
            "clip with baked captions, logos, UI overlay, watermark, or production-intent text",
        ],
        "operatorProofNeeded": [
            "source is a local MP4 from Companion/pageAssets direct import or operator-owned manual upload",
            "candidate comparison note covers at least two takes",
            "review packet records layout, hook, continuity, artifact, audio, and platform-fit evidence",
        ],
    }

    return {
        "state": acquisition_state,
        "status": status,
        "clipGenerated": clip_generated,
        "localMp4Imported": local_mp4_imported,
        "publishReadyLocalMp4": publish_ready_local_mp4,
        "qualityBlocked": quality_blocked,
        "qualityBlockers": quality_blockers[:8],
        "bestLocalCandidate": best_local_candidate or {},
        "candidateCurationPlan": candidate_curation_plan,
        "originalExportPlan": original_export_plan,
        "sourceQualityFloor": (
            "Grok-main finalization requires original/downloaded local MP4s that pass technical review; "
            "low-resolution browser cache/proxy recovery clips are proof only until replaced or explicitly re-reviewed."
        ),
        "manualWatchActive": manual_watch_active,
        "companionConnected": companion_connected,
        "blockerScope": blocker_scope,
        "sceneId": scene_label,
        "expectedFileName": file_label,
        "observedPostUrl": observed_post_url,
        "observedAssetUrl": observed_asset_url,
        "directAssetFetchSupported": False if observed_asset_url else None,
        "downloadAuthority": "signed-in-browser-session" if observed_asset_url else "operator-local-file",
        "primaryBlocker": (
            "grok-source-proof-only"
            if any("Download/Save/Export" in item or "proof only" in item for item in quality_blockers)
            else "local-mp4-below-quality-floor"
            if quality_blocked
            else "local-mp4-file-not-yet-present"
            if clip_generated and not local_mp4_imported
            else ""
        ),
        "approvedImportPaths": [
            "signed-in Chrome/Grok Download or Save into the watched Downloads folder",
            "Grok MP4 batch upload mapped to the scene",
            "Chrome companion download only after the operator loads/reloads the companion in the active profile",
        ],
        "operatorActionPriority": operator_actions,
        "doNotDo": [
            "Do not call the Grok/xAI API or paid video APIs for this zero-paid path.",
            "Do not downgrade a Grok-main scene to Pexels/image slideshow just because export/import is pending.",
            "Do not treat a generated clip as final until Video Studio review accepts motion, continuity, artifacts, and caption-safe framing.",
        ],
        "qualityContract": [
            "Grok creates raw motion footage only; no baked captions, title cards, UI overlays, or narration-intent text.",
            "Video Studio owns candidate comparison, subtitle layout, BGM/audio mix, render, and final quality gate.",
            "A publish-ready Grok-main render requires accepted local MP4 scene assets, not only a Grok post URL.",
        ],
    }


def _grok_asset_candidate_count(asset: dict | None) -> int:
    if not isinstance(asset, dict) or asset.get("status") != "ready":
        return 0
    candidates = asset.get("candidateAssets") if isinstance(asset.get("candidateAssets"), list) else []
    return max(1, len([item for item in candidates if isinstance(item, dict)]))


def _grok_source_provenance_confirmation_required(source_provenance: object) -> bool:
    if not isinstance(source_provenance, dict):
        return False
    return str(source_provenance.get("status") or "").strip() in {
        "local-mp4-download-unverified",
        "local-mp4-source-unverified",
    }


def _grok_main_review_evidence_missing(decision: object, source_provenance: object = None) -> list[str]:
    if not isinstance(decision, dict) or decision.get("accepted") is not True:
        return []
    missing: list[str] = []
    for key in (
        "firstTwoSecondHook",
        "artifactFree",
        "continuityOk",
        "captionSafe",
        "shotLockMatch",
        "sceneAssemblyOk",
    ):
        if decision.get(key) is not True:
            missing.append(f"{key}=true")
    if str(decision.get("visualQualityVerdict") or "") != "pass":
        missing.append("visualQualityVerdict=pass")
    for key in (
        "sourceRationale",
        "qualityReviewNote",
        "selectedCandidateSummary",
        "captionLayoutReviewNote",
        "shotLockEvidenceNote",
        "sceneAssemblyRoleNote",
        "continuityNote",
        "hookNote",
        "layoutVariantNote",
        "thumbnailReviewNote",
        "audioMixReviewNote",
        "platformComparisonNote",
    ):
        if len(str(decision.get(key) or "").strip()) < 24:
            missing.append(key)
    if _grok_source_provenance_confirmation_required(source_provenance):
        if decision.get("sourceProvenanceConfirmed") is not True:
            missing.append("sourceProvenanceConfirmed=true")
        if len(str(decision.get("sourceProvenanceNote") or "").strip()) < 24:
            missing.append("sourceProvenanceNote")
    return missing


def _has_grok_single_candidate_justification(decision: object) -> bool:
    if not isinstance(decision, dict):
        return False
    text = str(decision.get("singleCandidateJustification") or decision.get("selectedCandidateSummary") or "").strip()
    return len(text) >= 32


def _render_payload_from_manifest(handoff_dir: Path, manifest: dict, preview_mode: bool = False) -> dict:
    assets = _match_downloaded_assets(handoff_dir, manifest)
    main_source_gate = _grok_main_source_gate(manifest, assets)
    review_decisions = manifest.get("reviewDecisions") if isinstance(manifest.get("reviewDecisions"), dict) else {}
    production_context = manifest.get("productionContext") if isinstance(manifest.get("productionContext"), dict) else {}
    template_type = str(production_context.get("templateType") or manifest.get("templateType") or "").strip()
    grok_visual_led_no_voice = _is_grok_visual_led_no_voice_template(template_type, manifest)
    quality_gate_required = manifest.get("qualityGateRequired") is True
    rejected_scene_ids = sorted(
        str(scene_id)
        for scene_id, decision in review_decisions.items()
        if isinstance(decision, dict) and decision.get("accepted") is False
    )
    rejected_scene_id_set = set(rejected_scene_ids)
    all_ready_assets = [item for item in assets if item.get("status") == "ready" and item.get("sceneId")]
    ready_scene_ids = {str(item.get("sceneId")) for item in all_ready_assets}
    ready_assets = [item for item in all_ready_assets if str(item.get("sceneId")) not in rejected_scene_id_set]
    target_scene_ids = {str(item.get("sceneId")) for item in manifest.get("scenes") or []}
    missing_scene_ids = sorted(target_scene_ids - ready_scene_ids)
    pending_quality_scene_ids = sorted(
        str(item.get("sceneId"))
        for item in ready_assets
        if item.get("qualityGate", {}).get("status") in {"pending-operator-review", "technical-review", "shot-lock-review"}
    )
    accepted_scene_ids = {
        str(item.get("sceneId"))
        for item in ready_assets
        if item.get("qualityGate", {}).get("status") == "accepted"
    }
    quality_ready = (
        not quality_gate_required
        or (bool(target_scene_ids) and accepted_scene_ids >= target_scene_ids and not pending_quality_scene_ids)
    )
    all_ready = (
        bool(target_scene_ids)
        and not missing_scene_ids
        and not rejected_scene_ids
        and quality_ready
        and main_source_gate.get("allReady") is True
    )

    draft_scenes = _safe_draft_scenes(manifest.get("draftScenes")) or _fallback_draft_scenes(manifest)
    target_by_scene_id = {str(item.get("sceneId")): item for item in manifest.get("scenes") or []}
    preview_scene_ids = {str(item.get("sceneId")) for item in ready_assets if item.get("sourcePath")}
    render_drafts: list[dict] = []
    for index, item in enumerate(draft_scenes):
        draft = dict(item)
        scene_id = _draft_scene_id(draft, index)
        if preview_mode and scene_id not in preview_scene_ids:
            continue
        if scene_id in target_scene_ids:
            target = target_by_scene_id.get(scene_id, {})
            decision = review_decisions.get(scene_id) if isinstance(review_decisions.get(scene_id), dict) else {}
            draft["sceneId"] = scene_id
            draft["image_source"] = "grok"
            draft["upload_kind"] = "video"
            draft["grok_prompt"] = draft.get("grok_prompt") or target.get("prompt") or draft.get("image_prompt") or ""
            draft["source_rationale"] = (
                decision.get("sourceRationale")
                or draft.get("source_rationale")
                or f"Operator-selected Grok web handoff MP4 for {scene_id}."
            )
            draft["originality_evidence"] = (
                draft.get("originality_evidence")
                or f"Grok Imagine web/app MP4 synced from handoff incoming folder for {scene_id}."
            )
            if decision.get("qualityReviewNote"):
                draft["quality_review_note"] = decision.get("qualityReviewNote")
                draft["qualityReviewNote"] = decision.get("qualityReviewNote")
            if decision.get("captionLayoutReviewNote"):
                draft["captionLayoutReviewNote"] = decision.get("captionLayoutReviewNote")
            if decision.get("visualQualityVerdict"):
                draft["visualQualityVerdict"] = decision.get("visualQualityVerdict")
            if decision.get("selectedCandidateSummary"):
                draft["selectedCandidateSummary"] = decision.get("selectedCandidateSummary")
            if decision.get("shotLockEvidenceNote"):
                draft["shotLockEvidenceNote"] = decision.get("shotLockEvidenceNote")
                draft["shot_lock_evidence_note"] = decision.get("shotLockEvidenceNote")
            if decision.get("sceneAssemblyRoleNote"):
                draft["sceneAssemblyRoleNote"] = decision.get("sceneAssemblyRoleNote")
                draft["scene_assembly_role_note"] = decision.get("sceneAssemblyRoleNote")
            if decision.get("sourceProvenanceNote"):
                draft["sourceProvenanceNote"] = decision.get("sourceProvenanceNote")
            if decision.get("sourceProvenanceConfirmed") is True:
                draft["sourceProvenanceConfirmed"] = True
            if isinstance(decision.get("selectedCandidate"), dict):
                draft["selectedCandidate"] = decision.get("selectedCandidate")
            if decision.get("continuityNote"):
                draft["continuity_note"] = decision.get("continuityNote")
                draft["continuityNote"] = decision.get("continuityNote")
            if decision.get("hookNote"):
                draft["hook_note"] = decision.get("hookNote")
                draft["hookNote"] = decision.get("hookNote")
            for decision_key, draft_key in (
                ("layoutVariantKey", "layoutVariantKey"),
                ("layoutVariantLabel", "layoutVariantLabel"),
                ("layoutVariantNote", "layoutVariantNote"),
                ("thumbnailReviewNote", "thumbnailReviewNote"),
                ("audioMixReviewNote", "audioMixReviewNote"),
                ("platformComparisonNote", "platformComparisonNote"),
            ):
                if decision.get(decision_key):
                    draft[draft_key] = decision.get(decision_key)
            if decision.get("operatorNote"):
                draft["grok_review_note"] = decision.get("operatorNote")
            if decision.get("accepted") is False:
                draft["quality_review_note"] = f"Rejected in Grok review packet: {decision.get('operatorNote') or 'operator marked this clip rejected.'}"
            if grok_visual_led_no_voice:
                _apply_grok_visual_led_no_voice_defaults(draft)
            preset = str(draft.get("caption_preset") or draft.get("captionPreset") or "lower-info")
            layout_default = _grok_first_layout_default(index, preset)
            if not draft.get("layout_variant_key") and not draft.get("layoutVariantKey"):
                draft["layout_variant_key"] = layout_default["key"]
                draft["layoutVariantKey"] = layout_default["key"]
            if not draft.get("layout_variant_label") and not draft.get("layoutVariantLabel"):
                draft["layout_variant_label"] = layout_default["label"]
                draft["layoutVariantLabel"] = layout_default["label"]
            if not draft.get("layout_variant_note") and not draft.get("layoutVariantNote"):
                draft["layout_variant_note"] = layout_default["note"]
                draft["layoutVariantNote"] = layout_default["note"]
        render_drafts.append(draft)

    scene_assets = [
        {
            "sceneId": str(item.get("sceneId")),
            "role": "visual",
            "fileName": str(item.get("fileName") or f"{item.get('sceneId')}.grok.mp4"),
            "mimeType": str(item.get("mimeType") or "video/mp4"),
            "sourcePath": str(item.get("sourcePath")),
            "provider": "upload",
            "sourceOrigin": "grok-handoff",
            "sourceIntent": "grok",
            "sourceGenerator": "grok-app-web-handoff",
            "selectedFileName": str(item.get("fileName") or ""),
            "candidateCount": len(item.get("candidateAssets") or []) if isinstance(item.get("candidateAssets"), list) else 1,
            "clipProbe": item.get("clipProbe") if isinstance(item.get("clipProbe"), dict) else {},
            "qualityGate": item.get("qualityGate") if isinstance(item.get("qualityGate"), dict) else {},
            "sourceProvenance": item.get("sourceProvenance") if isinstance(item.get("sourceProvenance"), dict) else {},
            "candidateAssets": item.get("candidateAssets") if isinstance(item.get("candidateAssets"), list) else [],
        }
        for item in ready_assets
        if item.get("sourcePath")
    ]
    project_id = str(manifest.get("projectId") or handoff_dir.name)
    provider_scene_ids = preview_scene_ids if preview_mode else target_scene_ids
    return {
        "projectId": f"{project_id}-render",
        "prompt": str(manifest.get("sourcePrompt") or f"Grok handoff render {project_id}"),
        "budgetMode": "free",
        "plannerMode": "sample",
        "templateType": template_type,
        "audioDesignMode": "ambient-first" if grok_visual_led_no_voice else "",
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        "draftScenes": render_drafts,
        "sceneAssets": scene_assets,
        "providerOverrides": {scene_id: "grok" for scene_id in provider_scene_ids},
        "selectedPexelsVideos": {},
        "readyScenes": len(ready_assets),
        "totalScenes": len(target_scene_ids),
        "allReady": all_ready,
        "previewMode": preview_mode,
        "previewReady": bool(scene_assets) if preview_mode else all_ready,
        "previewSceneIds": sorted(preview_scene_ids) if preview_mode else [],
        "renderPurpose": "grok-import-preview" if preview_mode else "grok-final-handoff",
        "missingSceneIds": missing_scene_ids,
        "rejectedSceneIds": rejected_scene_ids,
        "qualityGateRequired": quality_gate_required,
        "qualityGateReady": quality_ready,
        "mainSourceGate": main_source_gate,
        "grokTargetSelection": manifest.get("grokTargetSelection") if isinstance(manifest.get("grokTargetSelection"), dict) else {},
        "qualityPendingSceneIds": pending_quality_scene_ids,
        "reviewDecisions": review_decisions,
        "assets": assets,
    }


def _automation_plan_from_manifest(handoff_dir: Path, manifest: dict) -> dict:
    project_id = str(manifest.get("projectId") or handoff_dir.name)
    download_defaults = _download_defaults_for_manifest(manifest)
    stored_request = _read_automation_request(handoff_dir)
    replay_request = _automation_replay_summary(stored_request)
    assets = _match_downloaded_assets(handoff_dir, manifest)
    main_source_gate = _grok_main_source_gate(manifest, assets)
    scene_queue = _scene_queue_status(handoff_dir, manifest)
    next_scene = _select_grok_scene(manifest, str(scene_queue.get("nextMissingSceneId") or ""))
    automation_status = _read_automation_status(handoff_dir)
    automation_status = _enrich_stale_automation_status_blocker(
        automation_status,
        (stored_request or {}).get("remoteDebuggingPort") if isinstance(stored_request, dict) else None,
    )
    automation_job = _automation_job_summary(_read_automation_job_status(handoff_dir), project_id, stored_request)
    manual_download_watch_job = _manual_download_watch_summary(_read_manual_download_watch_status(handoff_dir), project_id)
    latest_extension_event = _latest_extension_event(handoff_dir)
    companion_connection = _companion_connection_status(latest_extension_event)
    manual_primary_path = _manual_primary_path(
        project_id,
        handoff_dir,
        manifest,
        next_scene,
        main_source_gate,
        automation_status,
        companion_connection,
    )
    main_path_status = _grok_main_path_status(
        project_id,
        handoff_dir,
        manifest,
        assets,
        main_source_gate,
        scene_queue,
        next_scene,
        manual_primary_path,
        automation_status,
        automation_job,
        manual_download_watch_job,
        companion_connection,
    )
    expected_files = [
        {
            "sceneId": str(scene.get("sceneId") or f"scene-{index + 1:02d}"),
            "expectedFileName": str(scene.get("expectedFileName") or f"scene-{index + 1:02d}.grok.mp4"),
            "promptPath": scene.get("promptPath"),
            "operatorChecklist": scene.get("operatorChecklist") or [],
        }
        for index, scene in enumerate(manifest.get("scenes") or [])
    ]
    shot_bible = manifest.get("shotBible") if isinstance(manifest.get("shotBible"), dict) else {}
    return {
        "ok": True,
        "projectId": project_id,
        "mode": "operator-approved-browser-download-import",
        "goal": "Automate the handoff around the signed-in Grok web/app session without calling the paid xAI API.",
        "grokUrl": str(manifest.get("grokUrl") or GROK_IMAGINE_URL),
        "worksheetUrl": manifest.get("worksheetUrl") or _worksheet_url(project_id),
        "productionQueueUrl": manifest.get("productionQueueUrl") or _production_queue_url(project_id),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        "incomingDir": manifest.get("incomingDir") or str(handoff_dir / "incoming"),
        **download_defaults,
        "shotBible": shot_bible,
        "reviewChecklist": shot_bible.get("reviewChecklist") or [],
        "mainSourceGate": main_source_gate,
        "grokTargetSelection": manifest.get("grokTargetSelection") if isinstance(manifest.get("grokTargetSelection"), dict) else {},
        "manualPrimaryPath": manual_primary_path,
        "mainPathStatus": main_path_status,
        "expectedFiles": expected_files,
        "approvalRequired": True,
        "automationBoundaries": {
            "usesPaidApi": False,
            "storesCredentials": False,
            "deletesSourceDownloads": False,
            "defaultRemoteDebugging": False,
            "defaultPersistentAutomationProfile": False,
            "fullBrowserControl": "available only after explicit operator, browser, generate, download, and watch approvals",
        },
        "downloadImport": {
            "endpoint": f"/api/grok-handoff/{project_id}/import-downloads",
            "watchEndpoint": f"/api/grok-handoff/{project_id}/watch-downloads",
            "manualUploadEndpoint": f"/api/grok-handoff/{project_id}/upload-mp4",
            "manualBatchUploadEndpoint": f"/api/grok-handoff/{project_id}/upload-mp4-batch",
            "requiresOperatorApprovedTrue": True,
            "input": {
                "downloadDir": "absolute local folder containing Grok MP4 downloads",
                **download_defaults,
                "operatorApproved": True,
                "fileBase64": "manualUploadEndpoint only; browser-selected Grok MP4 encoded by the dashboard",
                "fileName": "manualUploadEndpoint only; original .mp4 filename from the operator",
                "sceneId": "manualUploadEndpoint only; target Grok scene id",
                "files": "manualBatchUploadEndpoint only; array of {sceneId?, fileName, fileBase64}; missing sceneId maps by scene-XX filename or handoff order",
                "allowNewestFallback": "optional boolean; maps newest generated MP4s by scene order when filenames do not match",
                "overwrite": "optional boolean; defaults false",
                "timeoutSeconds": "watch endpoint only; capped at 120 seconds",
                "pollIntervalSeconds": "watch endpoint only; capped at 10 seconds",
            },
            "acceptedExtensions": [".mp4"],
            "copiesIntoIncomingDir": True,
            "returnsRenderPayloadWhenReady": True,
        },
        "operatorRun": {
            "endpoint": f"/api/grok-handoff/{project_id}/operator-run",
            "mode": "open-worksheet-and-grok-then-watch-downloads",
            "requiresOperatorApprovedTrue": True,
            "opensTargets": ["worksheet", "grok"],
            "maxTimeoutSeconds": 600,
            "returnsRenderPayloadWhenReady": True,
            "operatorStillDoes": [
                "approve the browser session",
                "sign in to Grok if prompted",
                "paste or use the worksheet prompt",
                "start generation and download each MP4",
            ],
        },
        "browserAutomation": {
            "endpoint": f"/api/grok-handoff/{project_id}/browser-automation",
            "resumeEndpoint": f"/api/grok-handoff/{project_id}/resume-automation",
            "mode": "operator-approved-local-cdp-generate-download-watch",
            "usesPaidApi": False,
            "requiresOperatorApprovedTrue": True,
            "requiresBrowserAutomationApprovedTrue": True,
            "defaultRemoteDebuggingPort": 9222,
            "canLaunchChromeOrEdge": True,
            "profileApprovalRequiredWhenLaunching": True,
            "optionalApprovalFlags": {
                "waitForOperatorReadyApproved": "wait for operator login/cookie completion, then automatically resume prompt injection",
                "authKickoffApproved": "click a likely Login/Sign in control only to open the operator-owned auth flow",
                "authProviderKickoffApproved": "when xAI asks for a sign-in method, click only the explicit authProviderPreference button; credentials/captcha remain operator-only",
                "authProviderPreference": "optional: google, x, email, apple, or manual. Dashboard defaults to google for a logged-in Google/SuperGrok operator profile.",
                "useDefaultChromeProfile": "attach-only request for an already-running operator-launched Chrome CDP session. Video Studio will not launch or copy the default profile; Chrome 136+ usually blocks normal default-profile CDP, so isolated handoff remains the reliable path.",
                "attachDefaultChromeApproved": "required together with useDefaultChromeProfile=true; confirms the operator already launched a local CDP Chrome/SuperGrok session and accepts attach-only automation",
                "browserProfileMode": "default-chrome-cdp-attach for operator-launched logged-in Chrome attach, isolated-handoff-profile for Video Studio-launched profile",
                "browserProfileDirectory": "profile directory name; for isolated handoff this is inside the handoff user-data-dir, usually Default",
                "cookieRejectApproved": "click a likely Reject/Decline cookie control; never clicks Accept all",
                "operatorReadyTimeoutSeconds": "approved wait window for login/cookie completion; capped at 7200 seconds",
                "generatePromptApproved": "click a likely Grok Generate/Send control, with Enter fallback",
                "downloadResultApproved": "disabled: Video Studio must not click Grok Download/Save/Export controls",
                "watchDownloadsApproved": "disabled: Downloads watcher fallback must not wait on native Chrome prompts",
                "supersedeActiveJobApproved": "cancel a currently running auth-wait background job before starting a fresh approved isolated-profile run",
                "remoteDebuggingPort": "use a local-only CDP port such as 9222 or 9333 for the isolated handoff profile",
            },
            "automates": [
                "open an isolated Chrome/Edge DevTools session, or attach to an already-running operator-launched Chrome CDP session when attachDefaultChromeApproved=true",
                "bring a Grok Imagine tab forward",
                "wait for the operator to finish login/cookie gates when waitForOperatorReadyApproved=true",
                "advance the approved xAI sign-in provider handoff when authProviderKickoffApproved=true and authProviderPreference is not manual",
                "inject the selected scene prompt into the first editable prompt field",
                "start generation only when generatePromptApproved=true or submitPromptApproved=true",
                "block Download/Save/Export click requests even when legacy approval flags are present",
                "leave source import to Companion/pageAssets direct import or explicit local MP4 upload/import",
            ],
            "operatorStillDoes": [
                "approve local browser control and sign in to Grok/SuperGrok inside the isolated handoff browser profile when prompted",
                "complete Grok login, captcha, safety, or payment interstitials manually",
                "complete Google/X/email/Apple credentials or OAuth consent manually after the approved provider handoff",
                "verify the prompt and generated clip if Grok UI selectors or safety gates change",
                "use direct import or explicit local MP4 upload/import when Grok hides the original asset",
                "reject bad MP4s in the review packet before channel render",
            ],
        },
        "chromeCompanionExtension": _chrome_companion_summary(project_id, handoff_dir, manifest),
        "automationReplay": {
            "endpoint": f"/api/grok-handoff/{project_id}/resume-automation",
            "mode": "replay-last-sanitized-generate-direct-import-request",
            "requiresOperatorApprovedTrue": True,
            "requiresBrowserAutomationApprovedTrue": True,
            "storesCredentials": False,
            "lastRequest": replay_request,
            "operatorStillDoes": [
                "finish Grok login/captcha/payment/safety steps in the opened browser",
                "approve replay after confirming the saved download folder and scene",
                "review imported MP4s before channel render",
            ],
        },
        "backgroundAutomation": {
            "endpoint": f"/api/grok-handoff/{project_id}/background-automation",
            "mode": "background-replay-last-approved-request",
            "requiresOperatorApprovedTrue": True,
            "requiresBrowserAutomationApprovedTrue": True,
            "storesCredentials": False,
            "writesStatus": "automation-job-status.json",
            "purpose": "Let the operator complete Grok login/captcha/payment in the opened browser while Video Studio keeps waiting and automatically resumes prompt generation only; source import remains direct-import or explicit local MP4 upload/import.",
            "operatorStillDoes": [
                "approve background browser control and any browser profile used for Grok sign-in",
                "finish Grok login/captcha/payment/safety steps in the opened browser",
                "review imported MP4s before channel render",
            ],
        },
        "manualDownloadWatch": {
            "endpoint": f"/api/grok-handoff/{project_id}/manual-download-watch",
            "mode": "nonblocking-grok-app-web-download-watch",
            "requiresOperatorApprovedTrue": True,
            "storesCredentials": False,
            "usesBrowserControl": False,
            "writesStatus": "manual-download-watch-status.json",
            "purpose": "Let the operator generate in the signed-in Grok app/web while Video Studio watches Downloads and imports the MP4 as the current scene candidate.",
            "operatorStillDoes": [
                "generate the selected scene take in Grok app/web",
                "download the MP4 into the approved Downloads folder",
                "review imported MP4s before channel render",
            ],
        },
        "postImportReview": {
            "endpoint": f"/api/grok-handoff/{project_id}/review-packet",
            "url": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
            "decisionEndpoint": f"/api/grok-handoff/{project_id}/review-decision",
            "mode": "local-html-video-preview-and-operator-acceptance-checklist",
            "purpose": "Review imported Grok MP4s against the shot bible before channel render/finalize.",
            "operatorStillDoes": [
                "reject clips with artifacts, flicker, watermark, baked-in text, or unrelated cutaways",
                "confirm first-2-second hook and motion",
                "confirm scene continuity before using the render payload",
                "write source_rationale and quality_review_note for accepted scenes",
            ],
        },
        "nextAutomationSlice": {
            "browserControl": "Current local CDP runner can inject, request generation, click an explicit download control, watch the approved folder, and import MP4s after separate approvals; Grok login/captcha/safety gates remain manual.",
            "guardrails": [
                "use only operator-approved local browser control",
                "do not store API keys or passwords",
                "do not call xAI API keys",
                "pause for captcha, payment, policy, or safety interstitials",
            ],
        },
    }


def _download_import_actions(project_id: str, manifest: dict, next_scene: dict | None = None) -> dict:
    download_defaults = _download_defaults_for_manifest(manifest)
    next_scene_id = str((next_scene or {}).get("sceneId") or "").strip()
    next_expected = str((next_scene or {}).get("expectedFileName") or "").strip()
    return {
        "endpoint": f"/api/grok-handoff/{project_id}/import-downloads",
        "watchEndpoint": f"/api/grok-handoff/{project_id}/watch-downloads",
        "manualWatchEndpoint": f"/api/grok-handoff/{project_id}/manual-download-watch",
        "manualUploadEndpoint": f"/api/grok-handoff/{project_id}/upload-mp4",
        "manualBatchUploadEndpoint": f"/api/grok-handoff/{project_id}/upload-mp4-batch",
        "operatorRunEndpoint": f"/api/grok-handoff/{project_id}/operator-run",
        "requiresOperatorApprovedTrue": True,
        "acceptedExtensions": [".mp4"],
        "copiesIntoIncomingDir": True,
        "returnsRenderPayloadWhenReady": True,
        "nextSceneId": next_scene_id,
        "nextExpectedFileName": next_expected,
        "input": {
            "downloadDir": "absolute local folder containing Grok MP4 downloads",
            **download_defaults,
            "operatorApproved": True,
            "sceneId": next_scene_id or "optional target Grok scene id",
            "allowNewestFallback": "optional boolean; maps newest generated MP4s by scene order when filenames do not match",
            "overwrite": "optional boolean; defaults false",
            "timeoutSeconds": "watch endpoint only; capped at 120 seconds",
            "manualWatchTimeoutSeconds": "manual watch job only; capped at 7200 seconds and returns immediately",
            "pollIntervalSeconds": "watch endpoint only; capped at 10 seconds",
        },
    }


def _operator_run_actions(project_id: str, manifest: dict, next_scene: dict | None = None) -> dict:
    download_defaults = _download_defaults_for_manifest(manifest)
    next_scene_id = str((next_scene or {}).get("sceneId") or "").strip()
    next_expected = str((next_scene or {}).get("expectedFileName") or "").strip()
    return {
        "endpoint": f"/api/grok-handoff/{project_id}/operator-run",
        "mode": "open-worksheet-and-grok-then-watch-downloads",
        "requiresOperatorApprovedTrue": True,
        "opensTargets": ["worksheet", "grok"],
        "maxTimeoutSeconds": 600,
        "returnsRenderPayloadWhenReady": True,
        "nextSceneId": next_scene_id,
        "nextExpectedFileName": next_expected,
        "input": {
            "downloadDir": "absolute local folder containing Grok MP4 downloads",
            **download_defaults,
            "operatorApproved": True,
            "sceneId": next_scene_id or "optional target Grok scene id",
            "openTargets": ["worksheet", "grok"],
            "allowNewestFallback": True,
            "timeoutSeconds": "watch timeout, capped at 600 seconds",
            "pollIntervalSeconds": "watch polling interval, capped at 10 seconds",
        },
        "operatorStillDoes": [
            "finish Grok login/captcha/payment/safety prompts if they appear",
            "start generation in Grok when the prompt is ready",
            "download the MP4 into the approved download folder",
            "review and accept the imported clip in Video Studio",
        ],
    }


def _manual_primary_path(
    project_id: str,
    handoff_dir: Path,
    manifest: dict,
    next_scene: dict | None,
    main_source_gate: dict,
    automation_status: dict | None = None,
    companion_connection: dict | None = None,
) -> dict:
    scenes = [scene for scene in (manifest.get("scenes") or []) if isinstance(scene, dict)]
    scene_index = None
    next_scene_id = str((next_scene or {}).get("sceneId") or "").strip()
    for index, scene in enumerate(scenes):
        scene_id = str(scene.get("sceneId") or f"scene-{index + 1:02d}")
        if next_scene_id and scene_id == next_scene_id:
            scene_index = index
            break
    selected_scene = next_scene if isinstance(next_scene, dict) else None
    if selected_scene is None and scenes:
        selected_scene = scenes[0]
        next_scene_id = str(selected_scene.get("sceneId") or "scene-01")
        scene_index = 0
    recommended_take_number = _recommended_take_number(selected_scene)
    recommended_take = _select_take_prompt(selected_scene or {}, recommended_take_number) if selected_scene else None
    recommended_take_label = (
        str((recommended_take or {}).get("label") or f"take-{recommended_take_number}")
        if next_scene_id
        else ""
    )
    recommended_take_focus = str((recommended_take or {}).get("focus") or "")
    base_prompt = str((selected_scene or {}).get("prompt") or (selected_scene or {}).get("grok_prompt") or "").strip()
    prompt = str((recommended_take or {}).get("prompt") or base_prompt).strip()
    expected_file = str((selected_scene or {}).get("expectedFileName") or (f"{next_scene_id}.grok.mp4" if next_scene_id else "")).strip()
    prompt_path = (selected_scene or {}).get("promptPath")
    take_commands = _scene_take_commands(project_id, next_scene_id, selected_scene) if next_scene_id and selected_scene else []
    recommended_command = next(
        (
            command for command in take_commands
            if _normalize_take_number(command.get("takeNumber")) == recommended_take_number
        ),
        None,
    )
    download_import = _download_import_actions(project_id, manifest, selected_scene)
    operator_run = _operator_run_actions(project_id, manifest, selected_scene)
    automation_status_value = str((automation_status or {}).get("status") or "").strip()
    companion_connected = bool((companion_connection or {}).get("connected"))
    if companion_connected:
        automation_state = "companion-available-secondary"
    elif automation_status_value in {"failed", "needs-operator", "waiting-for-operator"}:
        automation_state = "blocked-or-needs-operator-secondary"
    elif automation_status_value in {"queued", "running", "injected"}:
        automation_state = "running-secondary"
    else:
        automation_state = "not-running-secondary"
    gate_required = main_source_gate.get("required") is True
    additional_accepted = int(main_source_gate.get("additionalAcceptedScenesNeeded") or 0) if gate_required else 0
    accepted_scene_ids = main_source_gate.get("acceptedSceneIds") or []
    planned_scene_ids = main_source_gate.get("plannedSceneIds") or []
    if gate_required and additional_accepted <= 0 and main_source_gate.get("allReady") is True:
        next_action = "render-grok-main"
    elif next_scene_id:
        next_action = "generate-download-import-review"
    else:
        next_action = "review-accepted-grok-clips"
    if next_action == "render-grok-main":
        operator_next_action = "Render the Grok-main cut from the reviewed MP4 scene assets."
    elif next_scene_id:
        take_label = f"Take {recommended_take_number} / {recommended_take_label}" if recommended_take_label else f"Take {recommended_take_number}"
        if companion_connected:
            operator_next_action = (
                f"Use the Video Studio Grok Companion Prep + Generate flow for {next_scene_id} "
                f"with {take_label}, "
                f"download {expected_file or 'the Grok MP4'}, then import and review it."
            )
        else:
            operator_next_action = (
                f"Use the production queue or opened Grok prep URL in the signed-in Grok app/web "
                f"for {next_scene_id} with {take_label}, download {expected_file or 'the Grok MP4'}, then use "
                "Downloads import/watch or batch upload. Browser CDP automation is secondary."
            )
    else:
        operator_next_action = "Review accepted Grok clips and reject weak motion, artifacts, baked text, or continuity breaks before render."
    return {
        "mode": "manual-grok-app-web-primary",
        "primarySource": "grok-app-web-mp4",
        "usesPaidApi": False,
        "paidApiPolicy": "Grok API, paid video APIs, and credential automation are not used.",
        "browserAutomationRole": "secondary-experimental",
        "browserAutomationState": automation_state,
        "nextAction": next_action,
        "operatorNextAction": operator_next_action,
        "automationNextAction": (automation_status or {}).get("operatorNextAction"),
        "projectId": project_id,
        "incomingDir": manifest.get("incomingDir") or str(handoff_dir / "incoming"),
        "defaultDownloadDir": download_import.get("input", {}).get("defaultDownloadDir"),
        "defaultDownloadDirExists": download_import.get("input", {}).get("defaultDownloadDirExists"),
        "worksheetUrl": manifest.get("worksheetUrl") or _worksheet_url(project_id),
        "productionQueueUrl": manifest.get("productionQueueUrl") or _production_queue_url(project_id),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        "currentScene": {
            "sceneId": next_scene_id,
            "sceneNumber": (scene_index + 1) if scene_index is not None else None,
            "expectedFileName": expected_file,
            "promptPath": prompt_path,
            "basePrompt": base_prompt,
            "prompt": prompt,
            "promptExcerpt": _prompt_excerpt(prompt, limit=260),
            "recommendedTakeNumber": recommended_take_number if next_scene_id else None,
            "recommendedTakeLabel": recommended_take_label,
            "recommendedTakeFocus": recommended_take_focus,
            "commandUrl": (recommended_command or {}).get("commandUrl") or _extension_command_url(project_id, next_scene_id, recommended_take_number) if next_scene_id else "",
            "prepGenerateAutostartUrl": (recommended_command or {}).get("prepGenerateAutostartUrl") or _extension_autostart_url(project_id, next_scene_id, "prep-generate", recommended_take_number) if next_scene_id else "",
            "takeCommands": take_commands,
            "downloadInstruction": (selected_scene or {}).get("downloadInstruction")
            or (
                f"Download a Grok MP4 for {next_scene_id}. The safest name is {expected_file}, "
                "but batch upload also maps unnamed Grok downloads by scene-row take groups."
                if expected_file
                else "Direct-import or operator-upload the Grok MP4 into this handoff packet."
            ),
            "operatorChecklist": (selected_scene or {}).get("operatorChecklist") or [],
        },
        "orderedBatchUpload": {
            "supported": True,
            "selectionRule": (
                "When files are not named scene-XX, select MP4 files in scene order grouped by scene row: "
                "all scene-01 takes first, then all scene-02 takes. The batch uploader preserves them as candidates."
            ),
            "recommendedFileOrder": [
                {
                    "sceneId": str(scene.get("sceneId") or f"scene-{index + 1:02d}"),
                    "expectedFileName": str(scene.get("expectedFileName") or f"scene-{index + 1:02d}.grok.mp4"),
                }
                for index, scene in enumerate(scenes)
            ],
            "filenameStillAccepted": True,
        },
        "acceptedSceneIds": accepted_scene_ids,
        "plannedSceneIds": planned_scene_ids,
        "requiredAcceptedScenes": main_source_gate.get("minAcceptedScenes") if gate_required else 0,
        "additionalAcceptedScenesNeeded": additional_accepted,
        "mainSourceGate": main_source_gate,
        "endpoints": {
            "importDownloads": download_import.get("endpoint"),
            "watchDownloads": download_import.get("watchEndpoint"),
            "manualDownloadWatch": download_import.get("manualWatchEndpoint"),
            "manualUpload": download_import.get("manualUploadEndpoint"),
            "manualBatchUpload": download_import.get("manualBatchUploadEndpoint"),
            "operatorRun": operator_run.get("endpoint"),
            "productionQueue": f"/api/grok-handoff/{project_id}/production-queue",
            "reviewPacket": f"/api/grok-handoff/{project_id}/review-packet",
            "reviewDecision": f"/api/grok-handoff/{project_id}/review-decision",
            "renderPayload": f"/api/grok-handoff/{project_id}/render-payload",
        },
        "operatorSteps": [
            "Open the Grok production queue to generate all required scene MP4s in scene-row take groups.",
            "Open the signed-in Grok app/web session from the existing Chrome profile or phone app.",
            "Copy the current scene prompt from Video Studio and generate a short raw 9:16 MP4 in Grok.",
            "Download the result; naming it scene-XX.grok.mp4 helps, but it is not required.",
            "Batch-upload unnamed MP4 files grouped by scene row, or import from Downloads with newest-file fallback.",
            "Use the Grok review packet to reject artifacts, watermark, baked-in text, weak motion, or continuity breaks.",
            "Render only after enough accepted Grok MP4 scenes satisfy the Grok-main source gate.",
        ],
        "qualityRules": [
            "Grok MP4 should be the hero source, not a decorative fallback.",
            "Do not mark the final video top-tier while accepted Grok/local hero scenes are missing.",
            "Prefer multiple takes and select the least artificial take before render.",
            "Keep captions and layout handled by Video Studio, not baked into Grok outputs.",
        ],
    }


def _download_dir_from_request(value: object) -> tuple[Path | None, str | None]:
    raw = str(value or "").strip().strip('"')
    if not raw:
        return None, "downloadDir is required"
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        return None, "downloadDir must be an absolute local path"
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None, "downloadDir does not exist"
    if not resolved.is_dir():
        return None, "downloadDir must be a directory"
    return resolved, None


def _normalized_download_dirs(download_dir: Path, download_dirs: list[Path] | tuple[Path, ...] | None = None) -> list[Path]:
    normalized: list[Path] = []
    seen: set[str] = set()
    for item in [download_dir, *(download_dirs or [])]:
        try:
            resolved = item.resolve()
        except OSError:
            resolved = item
        key = str(resolved).lower() if os.name == "nt" else str(resolved)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(resolved)
    return normalized or [download_dir]


def _download_dirs_from_request(data: dict) -> tuple[list[Path] | None, str | None]:
    primary, error = _download_dir_from_request(data.get("downloadDir"))
    if error or primary is None:
        return None, error
    raw_extra = data.get("downloadDirs")
    if raw_extra is None:
        raw_extra = data.get("download_dirs")
    if raw_extra is None:
        raw_extra = []
    elif isinstance(raw_extra, str):
        raw_extra = [raw_extra]
    elif not isinstance(raw_extra, list):
        return None, "downloadDirs must be a list of absolute local folders"

    resolved_dirs = [primary]
    for item in raw_extra:
        resolved, item_error = _download_dir_from_request(item)
        if item_error or resolved is None:
            return None, item_error
        resolved_dirs.append(resolved)
    normalized = _normalized_download_dirs(primary, resolved_dirs)
    if len(normalized) > 6:
        return None, "downloadDirs is limited to 6 folders"
    return normalized, None


def _download_file_from_request(value: object, download_dir: Path) -> tuple[Path | None, str | None]:
    raw = str(value or "").strip().strip('"')
    if not raw:
        return None, None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = download_dir / raw
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None, "downloadFilePath does not exist"
    if not resolved.is_file():
        return None, "downloadFilePath must be a file"
    if resolved.suffix.lower() != ".mp4":
        return None, "downloadFilePath must point to an .mp4 file"
    try:
        resolved.relative_to(download_dir)
    except ValueError:
        return None, "downloadFilePath must stay inside downloadDir"
    return resolved, None


def _handoff_created_timestamp(manifest: dict) -> float | None:
    try:
        raw = str(manifest.get("createdAt") or "").strip()
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        created = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return created.timestamp()


def _handoff_created_cutoff(manifest: dict) -> float | None:
    created = _handoff_created_timestamp(manifest)
    if created is None:
        return None
    return created - 600


def _iso_from_timestamp(value: float | None) -> str:
    if value is None:
        return ""
    return datetime.fromtimestamp(value).isoformat(timespec="seconds")


def _grok_import_preflight(file_path: Path | None, manifest: dict, clip_probe: dict | None = None) -> dict:
    """Summarize whether an imported Grok MP4 is fresh and usable for review."""
    created_at = _handoff_created_timestamp(manifest)
    result = {
        "readyForReview": False,
        "status": "missing",
        "exists": False,
        "freshEnough": False,
        "usableVideoReady": False,
        "requiredModifiedAfter": _iso_from_timestamp(created_at),
        "modifiedAt": "",
        "issues": [],
    }
    if file_path is None:
        result["issues"] = ["imported MP4 is missing"]
        return result
    result["sourcePath"] = _relative_project_path(file_path)
    try:
        stat = file_path.stat()
    except OSError as exc:
        result["issues"] = [f"imported MP4 stat failed: {exc}"]
        return result

    result["exists"] = True
    result["modifiedAt"] = _iso_from_timestamp(stat.st_mtime)
    fresh_enough = created_at is None or stat.st_mtime >= created_at
    result["freshEnough"] = fresh_enough

    probe = clip_probe if isinstance(clip_probe, dict) else _probe_grok_clip(file_path)
    probe_issues = probe.get("issues") if isinstance(probe.get("issues"), list) else []
    usable = bool(probe) and (probe.get("ok") is True or (probe.get("status") == "ok" and probe.get("ok") is not False))
    result["usableVideoReady"] = usable
    result["clipProbeStatus"] = str(probe.get("status") or "")

    if not fresh_enough:
        result["status"] = "stale"
        result["issues"] = [
            "imported MP4 is older than this handoff and may be a stale exact-name candidate",
        ]
    elif not usable:
        result["status"] = "invalid-video"
        result["issues"] = [str(item) for item in probe_issues] or ["clipProbe did not confirm a usable MP4"]
    else:
        result["status"] = "ready"
        result["readyForReview"] = True
        result["issues"] = []
    return result


def _looks_like_mp4_container(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            header = handle.read(4096)
    except OSError:
        return False
    return b"ftyp" in header


def _stable_tmp_mp4_candidate(path: Path) -> bool:
    try:
        before = path.stat()
    except OSError:
        return False
    if before.st_size <= 0:
        return False
    time.sleep(0.05)
    try:
        after = path.stat()
    except OSError:
        return False
    return before.st_size == after.st_size and _looks_like_mp4_container(path)


def _download_candidates(
    download_dir: Path,
    manifest: dict,
    since_handoff: bool,
    modified_after: float | None = None,
) -> list[Path]:
    cutoff = _handoff_created_cutoff(manifest) if since_handoff else None
    if modified_after is not None:
        cutoff = max(cutoff or modified_after, modified_after)
    candidates: list[Path] = []
    for item in download_dir.iterdir():
        suffix = item.suffix.lower()
        if not item.is_file() or suffix not in {".mp4", ".tmp"}:
            continue
        try:
            stat = item.stat()
        except OSError:
            continue
        if stat.st_size <= 0:
            continue
        if cutoff is not None and stat.st_mtime < cutoff:
            continue
        if suffix == ".tmp" and not _stable_tmp_mp4_candidate(item):
            continue
        candidates.append(item)
    return sorted(candidates, key=lambda item: (item.stat().st_mtime, item.name.lower()))


def _candidate_destination(incoming_dir: Path, scene_id: str, expected_file_name: str, source: Path) -> Path:
    stem = slugify(source.stem)
    if scene_id not in stem:
        stem = f"{scene_id}-{stem or 'candidate'}"
    base = f"{stem}.mp4"
    if base.lower() == expected_file_name.lower():
        base = f"{scene_id}.candidate.grok.mp4"
    candidate = incoming_dir / base
    counter = 2
    while candidate.exists():
        candidate = incoming_dir / f"{Path(base).stem}-{counter}.mp4"
        counter += 1
    return candidate


def _copy_candidate_to_incoming(source: Path, dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != dest.resolve():
        shutil.copy2(source, dest)
    return {
        "fileName": dest.name,
        "sourcePath": _relative_project_path(dest),
        "originalPath": str(source),
        "sizeBytes": dest.stat().st_size,
    }


def _import_metadata_for_file(manifest: dict, file_name: str) -> dict:
    matched: dict = {}
    for history in manifest.get("importHistory") or []:
        if not isinstance(history, dict):
            continue
        history_import_mode = str(history.get("importMode") or history.get("sceneMappingMode") or "").strip()
        for item in history.get("imported") or []:
            if not isinstance(item, dict) or str(item.get("fileName") or "") != file_name:
                continue
            matched = {
                "importedAt": str(history.get("importedAt") or ""),
                "importMode": str(item.get("importMode") or history_import_mode or "").strip(),
                "historyImportMode": history_import_mode,
                "downloadDir": str(history.get("downloadDir") or ""),
                "downloadFilePath": str(history.get("downloadFilePath") or ""),
                "originalPath": str(item.get("originalPath") or ""),
                "uploadedFileName": str(history.get("uploadedFileName") or ""),
            }
    return matched


def _grok_source_provenance(import_metadata: dict, source_event: dict) -> dict:
    import_mode = str(import_metadata.get("importMode") or "").strip()
    original_path = str(import_metadata.get("originalPath") or import_metadata.get("downloadFilePath") or "").strip()
    source_kind = str(source_event.get("sourceKind") or "").strip()
    quality_note = str(source_event.get("qualityNote") or "").strip()
    event_type = str(source_event.get("eventType") or "").strip()
    detail = str(source_event.get("detail") or "").strip()
    candidate_url = str(source_event.get("candidateUrl") or "").strip()
    marker_blob = " ".join([source_kind, quality_note, event_type, detail]).lower()
    proof_only = (
        source_kind == "visible-video-fallback"
        or "visible-video-fallback" in marker_blob
        or "proof-only" in marker_blob
        or "below-quality-floor" in marker_blob
    )
    direct_import_original_like = (
        source_kind in {
            "companion-direct-fetch",
            "visible-video-blob-direct-fetch",
            "bookmarklet-direct-video-fetch",
            "bookmarklet-blob-direct-fetch",
            "bookmarklet-post-direct-video-fetch",
            "bookmarklet-post-blob-direct-fetch",
            "codex-chrome-page-assets-direct-fetch",
        }
        and event_type in {
            "companion-direct-import",
            "companion-blob-direct-import",
            "bookmarklet-direct-import",
            "bookmarklet-post-direct-import",
            "codex-chrome-page-assets-direct-import",
        }
        and "no-browser-download-prompt" in marker_blob
    )
    original_like = (
        source_kind in {"download-control", "download-anchor", "direct-video-anchor"}
        or direct_import_original_like
        or "browser-native-download" in marker_blob
        or "original-download-source" in marker_blob
        or "direct-video-anchor" in marker_blob
    )
    approved_local_import = import_mode in {
        "exact-download-file",
        "scene-grouped-takes-download",
        "manual-browser-upload",
        "manual-browser-upload-batch",
    }
    if proof_only:
        status = "visible-video-fallback-proof-only"
        label = "visible video fallback - proof only"
        accept_as_main = False
        operator_action = "Use Companion/pageAssets direct import or operator-owned manual batch upload before accepting this scene as Grok-main."
    elif original_like:
        status = "browser-native-original-download"
        label = "Grok browser-native download"
        accept_as_main = True
        operator_action = "Proceed to candidate comparison and manual review before accepting."
    elif approved_local_import:
        status = "local-mp4-download-unverified"
        label = "local Grok MP4 import - verify original download"
        accept_as_main = True
        operator_action = "Confirm in the review note that this file came from Companion/pageAssets direct import or operator-owned manual upload, not a browser cache/currentSrc fallback."
    elif event_type == "codex-chrome-observation" or (candidate_url and not import_mode):
        status = "browser-observed-source-unverified"
        label = "browser-observed Grok source unverified"
        accept_as_main = False
        operator_action = (
            "Use signed-in Grok direct import through the local uploadEndpoint (bookmarklet/console or Companion), "
            "or explicit manual batch upload, before accepting this browser-observed candidate as Grok-main."
        )
    else:
        status = "local-mp4-source-unverified"
        label = "local MP4 source unverified"
        accept_as_main = True
        operator_action = "Confirm this is an operator-owned Grok MP4 download before accepting."
    return {
        "status": status,
        "label": label,
        "acceptAsGrokMainSource": accept_as_main,
        "proofOnly": proof_only,
        "originalDownloadLikely": original_like,
        "importMode": import_mode,
        "originalPath": original_path,
        "sourceKind": source_kind,
        "qualityNote": quality_note,
        "eventType": event_type,
        "candidateUrl": candidate_url,
        "operatorAction": operator_action,
    }


def _import_status_payload(project_id: str, handoff_dir: Path, manifest: dict, imported: list[dict], skipped: list[dict]) -> dict:
    assets = _match_downloaded_assets(handoff_dir, manifest)
    local_ready_assets = [
        item for item in assets if item.get("status") == "ready" and item.get("sceneId")
    ]
    ready_assets = _grok_status_ready_assets(manifest, assets)
    quality_gate_required = manifest.get("qualityGateRequired") is True
    quality_gate = {
        "required": quality_gate_required,
        "readySceneIds": [
            str(item.get("sceneId"))
            for item in local_ready_assets
            if item.get("qualityGate", {}).get("status") == "accepted"
        ],
        "pendingSceneIds": [
            str(item.get("sceneId"))
            for item in local_ready_assets
            if item.get("qualityGate", {}).get("status") in {"pending-operator-review", "technical-review", "source-review", "shot-lock-review"}
        ],
        "rejectedSceneIds": [
            str(item.get("sceneId"))
            for item in local_ready_assets
            if item.get("qualityGate", {}).get("status") == "rejected"
        ],
        "replacementSceneIds": [
            str(item.get("sceneId"))
            for item in local_ready_assets
            if _grok_asset_needs_replacement(item, manifest)
        ],
    }
    quality_gate["allReady"] = (
        not quality_gate_required
        or (
            len(quality_gate["readySceneIds"]) >= len(manifest.get("scenes") or [])
            and not quality_gate["pendingSceneIds"]
            and not quality_gate["rejectedSceneIds"]
        )
    )
    main_source_gate = _grok_main_source_gate(manifest, assets)
    scene_count = len(manifest.get("scenes") or [])
    queue_status = (
        _extension_queue_payload(project_id, handoff_dir, manifest)
        if project_id
        else _scene_queue_status(handoff_dir, manifest)
    )
    return {
        "imported": imported,
        "skipped": skipped,
        "assets": assets,
        "readyScenes": len(ready_assets),
        "totalScenes": scene_count,
        "allReady": scene_count > 0 and len(ready_assets) >= scene_count,
        "qualityGate": quality_gate,
        "mainSourceGate": main_source_gate,
        **queue_status,
    }


def _write_manifest(handoff_dir: Path, manifest: dict) -> None:
    manifest_path = _manifest_path(str(manifest.get("projectId") or handoff_dir.name))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = manifest_path.with_name(f"{manifest_path.name}.{threading.get_ident()}.tmp")
    payload = json.dumps(manifest, ensure_ascii=False, indent=2)
    with _manifest_io_lock:
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, manifest_path)


def _import_downloads(
    handoff_dir: Path,
    manifest: dict,
    download_dir: Path,
    allow_newest_fallback: bool,
    overwrite: bool,
    since_handoff: bool,
    scene_id_filter: str | None = None,
    preserve_candidates: bool = False,
    record_history: bool = True,
    excluded_original_paths: set[str] | None = None,
    scene_mapping_mode: object = None,
    scene_grouped_take_size: int = 0,
    scene_grouped_take_offset: int = 0,
    modified_after: float | None = None,
) -> dict:
    incoming_dir = handoff_dir / "incoming"
    candidates = _download_candidates(download_dir, manifest, since_handoff, modified_after=modified_after)
    previous_originals = {
        str(item.get("originalPath") or "")
        for history in manifest.get("importHistory") or []
        if isinstance(history, dict)
        for item in history.get("imported") or []
        if isinstance(item, dict)
    }
    blocked_originals = previous_originals | set(excluded_original_paths or set())
    if preserve_candidates or blocked_originals:
        candidates = [candidate for candidate in candidates if str(candidate) not in blocked_originals]
    used: set[Path] = set()
    imported: list[dict] = []
    skipped: list[dict] = []
    normalized_scene_mapping_mode = _normalize_scene_mapping_mode(scene_mapping_mode)
    grouped_take_size = max(0, int(scene_grouped_take_size or 0))

    if normalized_scene_mapping_mode and grouped_take_size > 0 and not scene_id_filter:
        scene_ids = _batch_upload_scene_ids(manifest)
        scenes_by_id = {
            str(scene.get("sceneId") or f"scene-{index + 1:02d}"): scene
            for index, scene in enumerate(manifest.get("scenes") or [])
            if isinstance(scene, dict)
        }
        offset = max(0, int(scene_grouped_take_offset or 0))
        for candidate_index, matched in enumerate(candidates):
            grouped_index = offset + candidate_index
            scene_index = grouped_index // grouped_take_size
            if scene_index >= len(scene_ids):
                skipped.append({
                    "sceneId": "",
                    "fileName": matched.name,
                    "reason": "scene-grouped-takes-overflow",
                })
                continue
            scene_id = scene_ids[scene_index]
            scene = scenes_by_id.get(scene_id) or {}
            expected_file_name = str(scene.get("expectedFileName") or f"{scene_id}.grok.mp4")
            dest = incoming_dir / expected_file_name
            target_dest = dest
            if dest.exists() and preserve_candidates and matched.resolve() != dest.resolve():
                target_dest = _candidate_destination(incoming_dir, scene_id, expected_file_name, matched)
            elif dest.exists() and not overwrite:
                skipped.append({"sceneId": scene_id, "fileName": expected_file_name, "reason": "already-ready"})
                continue
            copied = _copy_candidate_to_incoming(matched, target_dest)
            imported.append({
                "sceneId": scene_id,
                "expectedFileName": expected_file_name,
                "importMode": "scene-grouped-takes-download",
                "sceneGroupedTakeIndex": (grouped_index % grouped_take_size) + 1,
                **copied,
            })

        if record_history:
            manifest.setdefault("importHistory", []).append({
                "importedAt": datetime.now().isoformat(timespec="seconds"),
                "downloadDir": str(download_dir),
                "sceneId": "",
                "allowNewestFallback": allow_newest_fallback,
                "overwrite": overwrite,
                "sinceHandoff": since_handoff,
                "preserveCandidates": preserve_candidates,
                "sceneMappingMode": "scene-grouped-takes",
                "sceneGroupedTakeSize": grouped_take_size,
                "sceneGroupedTakeOffset": offset,
                "imported": imported,
                "skipped": skipped,
            })
            _write_manifest(handoff_dir, manifest)
        return _import_status_payload(str(manifest.get("projectId") or ""), handoff_dir, manifest, imported, skipped)

    for index, scene in enumerate(manifest.get("scenes") or []):
        scene_id = str(scene.get("sceneId") or f"scene-{index + 1:02d}")
        if scene_id_filter and scene_id != scene_id_filter:
            continue
        expected_file_name = str(scene.get("expectedFileName") or f"{scene_id}.grok.mp4")
        dest = incoming_dir / expected_file_name

        tokens = _scene_match_tokens({"sceneId": scene_id})
        matched = next(
            (
                candidate for candidate in candidates
                if candidate not in used and candidate.name.lower() == expected_file_name.lower()
            ),
            None,
        )
        if matched is None:
            matched = next(
                (
                    candidate for candidate in candidates
                    if candidate not in used and any(token in candidate.stem.lower() for token in tokens)
                ),
                None,
            )
        if matched is None and allow_newest_fallback:
            matched = next((candidate for candidate in candidates if candidate not in used), None)
        if matched is None:
            skipped.append({"sceneId": scene_id, "fileName": expected_file_name, "reason": "no-matching-mp4"})
            continue

        target_dest = dest
        if dest.exists() and preserve_candidates and matched.resolve() != dest.resolve():
            target_dest = _candidate_destination(incoming_dir, scene_id, expected_file_name, matched)
        elif dest.exists() and not overwrite:
            skipped.append({"sceneId": scene_id, "fileName": expected_file_name, "reason": "already-ready"})
            continue

        used.add(matched)
        copied = _copy_candidate_to_incoming(matched, target_dest)
        imported.append({
            "sceneId": scene_id,
            "expectedFileName": expected_file_name,
            **copied,
        })

    if record_history:
        manifest.setdefault("importHistory", []).append({
            "importedAt": datetime.now().isoformat(timespec="seconds"),
            "downloadDir": str(download_dir),
            "sceneId": scene_id_filter or "",
            "allowNewestFallback": allow_newest_fallback,
            "overwrite": overwrite,
            "sinceHandoff": since_handoff,
            "preserveCandidates": preserve_candidates,
            "sceneMappingMode": normalized_scene_mapping_mode,
            "sceneGroupedTakeSize": grouped_take_size,
            "imported": imported,
            "skipped": skipped,
        })
        _write_manifest(handoff_dir, manifest)
    return _import_status_payload(str(manifest.get("projectId") or ""), handoff_dir, manifest, imported, skipped)


def _import_exact_download_file(
    handoff_dir: Path,
    manifest: dict,
    download_dir: Path,
    download_file: Path,
    scene_id_filter: str,
    overwrite: bool,
    preserve_candidates: bool,
) -> dict:
    scene = _select_grok_scene(manifest, scene_id_filter)
    if scene is None:
        return _import_status_payload(
            str(manifest.get("projectId") or ""),
            handoff_dir,
            manifest,
            [],
            [{"sceneId": scene_id_filter, "fileName": download_file.name, "reason": "unknown-scene"}],
        )
    incoming_dir = handoff_dir / "incoming"
    scene_id = str(scene.get("sceneId") or scene_id_filter)
    expected_file_name = str(scene.get("expectedFileName") or f"{scene_id}.grok.mp4")
    dest = incoming_dir / expected_file_name
    target_dest = dest
    imported: list[dict] = []
    skipped: list[dict] = []

    if dest.exists() and preserve_candidates and download_file.resolve() != dest.resolve():
        target_dest = _candidate_destination(incoming_dir, scene_id, expected_file_name, download_file)
    elif dest.exists() and not overwrite:
        skipped.append({"sceneId": scene_id, "fileName": expected_file_name, "reason": "already-ready"})
    if not skipped:
        copied = _copy_candidate_to_incoming(download_file, target_dest)
        imported.append({
            "sceneId": scene_id,
            "expectedFileName": expected_file_name,
            "importMode": "exact-download-file",
            **copied,
        })

    manifest.setdefault("importHistory", []).append({
        "importedAt": datetime.now().isoformat(timespec="seconds"),
        "downloadDir": str(download_dir),
        "downloadFilePath": str(download_file),
        "sceneId": scene_id,
        "allowNewestFallback": False,
        "overwrite": overwrite,
        "sinceHandoff": False,
        "preserveCandidates": preserve_candidates,
        "importMode": "exact-download-file",
        "imported": imported,
        "skipped": skipped,
    })
    _write_manifest(handoff_dir, manifest)
    return _import_status_payload(str(manifest.get("projectId") or ""), handoff_dir, manifest, imported, skipped)


def _decode_uploaded_mp4(data: dict) -> tuple[bytes | None, str, str | None]:
    encoded = str(data.get("fileBase64") or data.get("file_base64") or data.get("base64") or "").strip()
    file_name = Path(str(data.get("fileName") or data.get("file_name") or data.get("name") or "").strip()).name
    if not encoded:
        return None, file_name, "fileBase64 is required"
    if not file_name:
        return None, file_name, "fileName is required"
    if Path(file_name).suffix.lower() != ".mp4":
        return None, file_name, "fileName must end with .mp4"
    if encoded.lower().startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        return None, file_name, f"invalid fileBase64: {exc}"
    if not payload:
        return None, file_name, "fileBase64 decoded to an empty file"
    return payload, file_name, None


def _import_uploaded_grok_mp4(
    handoff_dir: Path,
    manifest: dict,
    scene_id_filter: str,
    file_name: str,
    file_bytes: bytes,
    overwrite: bool,
    preserve_candidates: bool,
) -> dict:
    scene = _select_grok_scene(manifest, scene_id_filter)
    if scene is None:
        return _import_status_payload(
            str(manifest.get("projectId") or ""),
            handoff_dir,
            manifest,
            [],
            [{"sceneId": scene_id_filter, "fileName": file_name, "reason": "unknown-scene"}],
        )
    incoming_dir = handoff_dir / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    scene_id = str(scene.get("sceneId") or scene_id_filter)
    expected_file_name = str(scene.get("expectedFileName") or f"{scene_id}.grok.mp4")
    expected_dest = incoming_dir / expected_file_name
    upload_source = Path(file_name)
    target_dest = expected_dest
    imported: list[dict] = []
    skipped: list[dict] = []

    if expected_dest.exists() and preserve_candidates:
        target_dest = _candidate_destination(incoming_dir, scene_id, expected_file_name, upload_source)
    elif expected_dest.exists() and not overwrite:
        skipped.append({"sceneId": scene_id, "fileName": expected_file_name, "reason": "already-ready"})

    if not skipped:
        target_dest.write_bytes(file_bytes)
        imported.append({
            "sceneId": scene_id,
            "expectedFileName": expected_file_name,
            "fileName": target_dest.name,
            "sourcePath": _relative_project_path(target_dest),
            "originalPath": f"browser-upload:{file_name}",
            "sizeBytes": target_dest.stat().st_size,
            "importMode": "manual-browser-upload",
        })

    manifest.setdefault("importHistory", []).append({
        "importedAt": datetime.now().isoformat(timespec="seconds"),
        "downloadDir": "",
        "sceneId": scene_id,
        "allowNewestFallback": False,
        "overwrite": overwrite,
        "sinceHandoff": False,
        "preserveCandidates": preserve_candidates,
        "importMode": "manual-browser-upload",
        "uploadedFileName": file_name,
        "imported": imported,
        "skipped": skipped,
    })
    _write_manifest(handoff_dir, manifest)
    return _import_status_payload(str(manifest.get("projectId") or ""), handoff_dir, manifest, imported, skipped)


_UPLOAD_DIRECT_IMPORT_EVENT_TYPES = {
    "companion-direct-fetch": "companion-direct-import",
    "visible-video-blob-direct-fetch": "companion-blob-direct-import",
    "bookmarklet-direct-video-fetch": "bookmarklet-direct-import",
    "bookmarklet-blob-direct-fetch": "bookmarklet-direct-import",
    "bookmarklet-post-direct-video-fetch": "bookmarklet-post-direct-import",
    "bookmarklet-post-blob-direct-fetch": "bookmarklet-post-direct-import",
    "codex-chrome-page-assets-direct-fetch": "codex-chrome-page-assets-direct-import",
}


def _record_upload_direct_import_event(
    handoff_dir: Path,
    manifest: dict,
    project_id: str,
    scene_id: str,
    file_name: str,
    data: dict,
    result: dict,
) -> dict | None:
    imported = result.get("imported") if isinstance(result.get("imported"), list) else []
    if not imported:
        return None
    direct_import_proof = data.get("directImportProof") is True or str(data.get("directImportProof") or "").lower() == "true"
    if not direct_import_proof:
        return None
    source_kind = _short_text(data.get("sourceKind") or data.get("directImportSourceKind"), limit=80)
    if source_kind not in _UPLOAD_DIRECT_IMPORT_EVENT_TYPES:
        return None
    event_type = _short_text(
        data.get("eventType") or data.get("directImportEventType"),
        fallback=_UPLOAD_DIRECT_IMPORT_EVENT_TYPES[source_kind],
        limit=80,
    )
    if event_type not in set(_UPLOAD_DIRECT_IMPORT_EVENT_TYPES.values()):
        event_type = _UPLOAD_DIRECT_IMPORT_EVENT_TYPES[source_kind]
    expected_file_name = _short_text(
        data.get("expectedFileName")
        or (imported[0].get("expectedFileName") if isinstance(imported[0], dict) else "")
        or file_name,
        limit=120,
    )
    quality_note = _short_text(
        data.get("qualityNote"),
        fallback=f"original-download-source; {source_kind}; no-browser-download-prompt",
        limit=160,
    )
    imported_count = len(imported)
    record = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "projectId": str(manifest.get("projectId") or project_id),
        "sceneId": _safe_project_id(scene_id or data.get("sceneId") or "unknown-scene"),
        "eventType": event_type,
        "status": "imported",
        "detail": _short_text(
            data.get("detail")
            or f"uploadEndpoint direct import; imported={imported_count}; file={file_name}",
            limit=400,
        ),
        "currentUrl": _short_text(data.get("currentUrl"), limit=260),
        "candidateUrl": _short_text(data.get("candidateUrl"), limit=260),
        "expectedFileName": expected_file_name,
        "sourceKind": source_kind,
        "videoWidth": _short_text(data.get("videoWidth"), limit=20),
        "videoHeight": _short_text(data.get("videoHeight"), limit=20),
        "qualityFloorMet": _short_text(data.get("qualityFloorMet"), limit=20),
        "qualityNote": quality_note,
        "directImportProof": True,
        "source": "uploadEndpoint-direct-import",
    }
    path = _extension_event_log_path(handoff_dir)
    path.write_text(
        (path.read_text(encoding="utf-8") if path.exists() else "")
        + json.dumps(record, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return record


def _scene_id_from_upload_name(file_name: str) -> str:
    match = re.search(r"scene[-_\s]?(\d{1,3})", file_name, flags=re.IGNORECASE)
    if not match:
        return ""
    return f"scene-{int(match.group(1)):02d}"


def _batch_upload_scene_ids(manifest: dict) -> list[str]:
    return [
        str(scene.get("sceneId") or f"scene-{scene_index + 1:02d}")
        for scene_index, scene in enumerate(manifest.get("scenes") or [])
        if isinstance(scene, dict)
    ]


def _batch_upload_uses_scene_order(manifest: dict, uploads: list[dict]) -> bool:
    scene_ids = _batch_upload_scene_ids(manifest)
    if not scene_ids or len(uploads) != len(scene_ids):
        return False
    for item in uploads:
        if not isinstance(item, dict):
            return False
        inferred = _scene_id_from_upload_name(str(item.get("fileName") or item.get("file_name") or item.get("name") or ""))
        if inferred in scene_ids:
            return False
    return True


def _batch_upload_grouped_take_size(manifest: dict, uploads: list[dict], requested_mode: object = None) -> int:
    scene_ids = _batch_upload_scene_ids(manifest)
    if not scene_ids or len(uploads) <= len(scene_ids):
        return 0
    mode = str(requested_mode or "").strip().lower().replace("_", "-")
    if mode not in {"scene-grouped-takes", "grouped-scene-takes", "scene-take-groups"}:
        return 0
    return max(1, math.ceil(len(uploads) / len(scene_ids)))


def _batch_upload_scene_id(
    manifest: dict,
    item: dict,
    index: int,
    use_scene_order: bool = False,
    grouped_take_size: int = 0,
) -> str:
    scene_ids = _batch_upload_scene_ids(manifest)
    if grouped_take_size > 0:
        scene_index = min(index // grouped_take_size, len(scene_ids) - 1)
        return scene_ids[scene_index] if scene_index >= 0 else ""
    if use_scene_order:
        return scene_ids[index] if index < len(scene_ids) else ""
    inferred = _scene_id_from_upload_name(str(item.get("fileName") or item.get("file_name") or item.get("name") or ""))
    if inferred in scene_ids:
        return inferred
    requested = str(item.get("sceneId") or item.get("scene_id") or "").strip()
    if requested:
        return requested
    return scene_ids[index] if index < len(scene_ids) else ""


def _normalize_scene_mapping_mode(value: object) -> str:
    mode = str(value or "").strip().lower().replace("_", "-")
    return mode if mode in {"scene-grouped-takes", "grouped-scene-takes", "scene-take-groups"} else ""


def _scene_grouped_take_size_from_request(data: dict, manifest: dict, *, default: int = 2) -> int:
    scene_ids = _batch_upload_scene_ids(manifest)
    if not scene_ids:
        return 0
    return _bounded_int(
        data.get("sceneGroupedTakeSize") or data.get("scene_grouped_take_size"),
        default=default,
        minimum=1,
        maximum=5,
    )


def _import_uploaded_grok_mp4_batch(
    handoff_dir: Path,
    manifest: dict,
    uploads: list[dict],
    overwrite: bool,
    preserve_candidates: bool,
    scene_mapping_mode: object = None,
) -> dict:
    project_id = str(manifest.get("projectId") or "")
    imported: list[dict] = []
    skipped: list[dict] = []
    history_items: list[dict] = []
    grouped_take_size = _batch_upload_grouped_take_size(manifest, uploads, scene_mapping_mode)
    use_scene_order = grouped_take_size <= 0 and _batch_upload_uses_scene_order(manifest, uploads)
    for index, item in enumerate(uploads):
        if not isinstance(item, dict):
            skipped.append({"sceneId": "", "fileName": "", "reason": "invalid-upload-item"})
            continue
        scene_id = _batch_upload_scene_id(
            manifest,
            item,
            index,
            use_scene_order=use_scene_order,
            grouped_take_size=grouped_take_size,
        )
        file_bytes, file_name, error = _decode_uploaded_mp4(item)
        if error or file_bytes is None:
            skipped.append({"sceneId": scene_id, "fileName": file_name, "reason": error or "invalid-upload"})
            continue
        if not scene_id:
            skipped.append({"sceneId": "", "fileName": file_name, "reason": "sceneId is required"})
            continue
        result = _import_uploaded_grok_mp4(
            handoff_dir,
            manifest,
            scene_id,
            file_name,
            file_bytes,
            overwrite=overwrite,
            preserve_candidates=preserve_candidates,
        )
        imported.extend(item for item in result.get("imported") or [] if isinstance(item, dict))
        skipped.extend(item for item in result.get("skipped") or [] if isinstance(item, dict))
        history_items.append({"sceneId": scene_id, "uploadedFileName": file_name})

    manifest.setdefault("importHistory", []).append({
        "importedAt": datetime.now().isoformat(timespec="seconds"),
        "downloadDir": "",
        "sceneId": "",
        "allowNewestFallback": False,
        "overwrite": overwrite,
        "sinceHandoff": False,
        "preserveCandidates": preserve_candidates,
        "importMode": "manual-browser-upload-batch",
        "sceneMappingMode": (
            "scene-grouped-takes"
            if grouped_take_size > 0
            else "scene-order-full-batch" if use_scene_order else "filename-or-requested-scene"
        ),
        "sceneGroupedTakeSize": grouped_take_size,
        "uploadedFiles": history_items,
        "imported": imported,
        "skipped": skipped,
    })
    _write_manifest(handoff_dir, manifest)
    return _import_status_payload(project_id, handoff_dir, manifest, imported, skipped)


def _bounded_float(value: object, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _watch_downloads(
    handoff_dir: Path,
    manifest: dict,
    download_dir: Path,
    allow_newest_fallback: bool,
    overwrite: bool,
    since_handoff: bool,
    timeout_seconds: float,
    poll_interval_seconds: float,
    download_dirs: list[Path] | None = None,
    scene_id_filter: str | None = None,
    preserve_candidates: bool = False,
    stop_on_import: bool = False,
    scene_mapping_mode: object = None,
    scene_grouped_take_size: int = 0,
    cancel_event: threading.Event | None = None,
) -> dict:
    start = time.monotonic()
    started_wall_time = time.time()
    deadline = start + timeout_seconds
    attempts = 0
    all_imported: list[dict] = []
    last_result: dict | None = None
    completed = False
    seen_original_paths: set[str] = set()
    normalized_scene_mapping_mode = _normalize_scene_mapping_mode(scene_mapping_mode)
    watched_dirs = _normalized_download_dirs(download_dir, download_dirs)
    grouped_take_size = max(0, int(scene_grouped_take_size or 0))
    grouped_take_target = (
        len(_batch_upload_scene_ids(manifest)) * grouped_take_size
        if normalized_scene_mapping_mode and grouped_take_size > 0 and not scene_id_filter
        else 0
    )

    cancelled = False
    while True:
        if _manual_download_watch_cancelled(cancel_event):
            cancelled = True
            break
        attempts += 1
        imported_items: list[dict] = []
        for current_download_dir in watched_dirs:
            result = _import_downloads(
                handoff_dir,
                manifest,
                current_download_dir,
                allow_newest_fallback=allow_newest_fallback,
                overwrite=overwrite,
                since_handoff=since_handoff,
                scene_id_filter=scene_id_filter,
                preserve_candidates=preserve_candidates,
                record_history=False,
                excluded_original_paths=seen_original_paths,
                scene_mapping_mode=normalized_scene_mapping_mode,
                scene_grouped_take_size=grouped_take_size,
                scene_grouped_take_offset=len(all_imported),
                modified_after=started_wall_time if since_handoff else None,
            )
            last_result = result
            current_imported_items = [item for item in result.get("imported") or [] if isinstance(item, dict)]
            if current_imported_items:
                imported_items.extend(current_imported_items)
                all_imported.extend(current_imported_items)
                seen_original_paths.update(
                    str(item.get("originalPath") or "")
                    for item in current_imported_items
                    if item.get("originalPath")
                )
        grouped_target_ready = not grouped_take_target or len(all_imported) >= grouped_take_target
        waiting_for_overwrite_import = overwrite and not all_imported and (scene_id_filter is not None or stop_on_import)
        if result.get("allReady") and grouped_target_ready and not waiting_for_overwrite_import:
            completed = True
            break
        if stop_on_import and imported_items:
            completed = True
            break
        if time.monotonic() >= deadline:
            break
        wait_seconds = min(poll_interval_seconds, max(0.0, deadline - time.monotonic()))
        if cancel_event and cancel_event.wait(wait_seconds):
            cancelled = True
            break

    elapsed = time.monotonic() - start
    payload = _render_payload_from_manifest(handoff_dir, manifest) if last_result and last_result.get("allReady") else None
    watch_record = {
        "watchedAt": datetime.now().isoformat(timespec="seconds"),
        "downloadDir": str(watched_dirs[0]),
        "downloadDirs": [str(item) for item in watched_dirs],
        "sceneId": scene_id_filter or "",
        "allowNewestFallback": allow_newest_fallback,
        "overwrite": overwrite,
        "sinceHandoff": since_handoff,
        "watchStartedAfterEpoch": round(started_wall_time, 3) if since_handoff else None,
        "preserveCandidates": preserve_candidates,
        "sceneMappingMode": normalized_scene_mapping_mode,
        "sceneGroupedTakeSize": grouped_take_size,
        "sceneGroupedTakeTarget": grouped_take_target,
        "timeoutSeconds": timeout_seconds,
        "pollIntervalSeconds": poll_interval_seconds,
        "stopOnImport": stop_on_import,
        "attempts": attempts,
        "elapsedSeconds": round(elapsed, 3),
        "allReady": bool(last_result and last_result.get("allReady")),
        "completed": completed,
        "cancelled": cancelled,
        "cancelReason": "Superseded by a newer Grok Downloads watch." if cancelled else "",
        "seenOriginalCount": len(seen_original_paths),
        "imported": all_imported,
    }
    manifest.setdefault("watchHistory", []).append(watch_record)
    _write_manifest(handoff_dir, manifest)

    return {
        **(last_result or {}),
        "imported": all_imported,
        "attempts": attempts,
        "elapsedSeconds": round(elapsed, 3),
        "timedOut": not completed and not cancelled,
        "completed": completed,
        "cancelled": cancelled,
        "cancelReason": "Superseded by a newer Grok Downloads watch." if cancelled else "",
        "sceneMappingMode": normalized_scene_mapping_mode,
        "sceneGroupedTakeSize": grouped_take_size,
        "sceneGroupedTakeTarget": grouped_take_target,
        "downloadDir": str(watched_dirs[0]),
        "downloadDirs": [str(item) for item in watched_dirs],
        "renderPayload": payload,
    }


def _match_downloaded_assets(handoff_dir: Path, manifest: dict) -> list[dict]:
    incoming_dir = handoff_dir / "incoming"
    files = sorted(
        incoming_dir.glob("*.mp4"),
        key=lambda item: (item.stat().st_mtime, item.name.lower()),
    )
    scenes = list(manifest.get("scenes") or [])
    review_decisions = manifest.get("reviewDecisions") if isinstance(manifest.get("reviewDecisions"), dict) else {}
    used_files: set[Path] = set()
    assets: list[dict] = []
    project_id = str(manifest.get("projectId") or handoff_dir.name)

    def _ready_asset(scene_id: str, file_path: Path, selected: bool, expected_file_name: str = "") -> dict:
        import_metadata = _import_metadata_for_file(manifest, file_path.name)
        source_event = _latest_grok_source_event(handoff_dir, scene_id, file_path.name, expected_file_name)
        clip_probe = _probe_grok_clip(file_path)
        return {
            "sceneId": scene_id,
            "fileName": file_path.name,
            "mimeType": "video/mp4",
            "sourcePath": _relative_project_path(file_path),
            "previewUrl": _asset_url(project_id, file_path.name),
            "sizeBytes": file_path.stat().st_size,
            "status": "ready",
            "selected": selected,
            "clipProbe": clip_probe,
            "importPreflight": _grok_import_preflight(file_path, manifest, clip_probe),
            "importMetadata": import_metadata,
            "sourceProvenance": _grok_source_provenance(import_metadata, source_event),
        }

    for index, scene in enumerate(scenes):
        scene_id = str(scene.get("sceneId") or f"scene-{index + 1:02d}")
        decision = review_decisions.get(scene_id) if isinstance(review_decisions.get(scene_id), dict) else {}
        selected_file_name = Path(str(decision.get("selectedFileName") or "")).name
        tokens = _scene_match_tokens(scene)
        expected_file_name = str(scene.get("expectedFileName") or f"{scene_id}.grok.mp4")
        candidate_files = [
            candidate
            for candidate in files
            if candidate not in used_files
            and (
                candidate.name.lower() == expected_file_name.lower()
                or any(token in candidate.stem.lower() for token in tokens)
            )
        ]
        candidate_files.sort(
            key=lambda item: (
                0 if item.name.lower() == expected_file_name.lower() else 1,
                item.stat().st_mtime,
                item.name.lower(),
            )
        )
        matched: Path | None = None
        if selected_file_name:
            matched = next((candidate for candidate in candidate_files if candidate.name == selected_file_name), None)
        if matched is None:
            matched = next(
                (candidate for candidate in candidate_files if candidate.name.lower() == expected_file_name.lower()),
                None,
            )
        if matched is None and candidate_files:
            matched = candidate_files[0]
        for candidate in files:
            if matched is not None or candidate_files or candidate in used_files:
                continue
            if len(files) == len(scenes):
                matched = candidate
                candidate_files = [candidate]
                break
        if matched is None and len(files) == len(scenes):
            for candidate in files:
                if candidate not in used_files:
                    matched = candidate
                    candidate_files = [candidate]
                    break
        if matched is None:
            missing_asset = {
                "sceneId": scene_id,
                "expectedFileName": scene.get("expectedFileName"),
                "status": "missing",
            }
            missing_asset["qualityGate"] = _asset_quality_gate(missing_asset, review_decisions, manifest)
            assets.append(missing_asset)
            continue

        if not candidate_files:
            candidate_files = [matched]
        candidate_records = [
            _ready_asset(scene_id, item, selected=False, expected_file_name=expected_file_name)
            for item in candidate_files
        ]
        used_files.update(candidate_files)
        default_record = next(
            (item for item in candidate_records if item.get("fileName") == matched.name),
            candidate_records[0],
        )
        if selected_file_name:
            selected_record = next(
                (item for item in candidate_records if item.get("fileName") == selected_file_name),
                default_record,
            )
        elif manifest.get("qualityGateRequired") is True or manifest.get("grokMainSourceRequired") is True:
            selected_record = _grok_best_candidate_record(candidate_records) or default_record
        else:
            selected_record = default_record
        for item in candidate_records:
            item["selected"] = item is selected_record
        ready_asset = dict(selected_record)
        ready_asset["candidateAssets"] = [dict(item) for item in candidate_records]
        ready_asset["qualityGate"] = _asset_quality_gate(ready_asset, review_decisions, manifest)
        assets.append(ready_asset)

    unmatched = [
        {
            "fileName": item.name,
            "sourcePath": _relative_project_path(item),
            "sizeBytes": item.stat().st_size,
            "status": "unmatched",
        }
        for item in files
        if item not in used_files
    ]
    return [*assets, *unmatched]


@grok_bp.route("/api/grok-handoff", methods=["POST"])
def create_grok_handoff_route():
    """Create a local Grok Imagine browser handoff packet for selected scenes."""
    data = flask_request.get_json(silent=True) or {}
    draft_scenes = data.get("draftScenes") or data.get("draft_scenes") or []
    if not isinstance(draft_scenes, list) or not draft_scenes:
        return jsonify({"ok": False, "error": "draftScenes is required"}), 400

    project_id = _safe_project_id(data.get("projectId") or data.get("project_id"))
    handoff_dir = _handoff_dir(project_id)
    incoming_dir = handoff_dir / "incoming"
    prompts_dir = handoff_dir / "prompts"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    source_mix_total_scenes = len(_safe_draft_scenes(draft_scenes)) or len(draft_scenes)
    min_grok_main_scenes = _min_grok_main_scene_count(source_mix_total_scenes)
    grok_main_required = data.get("grokMainSourceRequired") is True
    target_scenes, target_selection = _grok_target_selection(
        _safe_draft_scenes(draft_scenes),
        source_mix_total_scenes,
        grok_main_required,
    )
    source_prompt = data.get("prompt") or data.get("sourcePrompt") or ""
    production_context = _request_production_context(data)
    shot_bible = _build_shot_bible(target_scenes, source_prompt, production_context)
    scenes = []
    for index, item in enumerate(target_scenes):
        scene_id = _scene_id(item, index)
        prompt = _scene_prompt(item, shot_bible, index, target_scenes)
        prompt_quality = _scene_prompt_quality(prompt, item, shot_bible)
        expected_file_name = f"{scene_id}.grok.mp4"
        prompt_file = prompts_dir / f"{scene_id}.prompt.txt"
        prompt_file.write_text(prompt + "\n", encoding="utf-8")
        scene_record = {
            "sceneId": scene_id,
            "sceneNum": index + 1,
            "prompt": prompt,
            "promptQuality": prompt_quality,
            "promptPath": _relative_project_path(prompt_file),
            "expectedFileName": expected_file_name,
            "downloadInstruction": (
                f"Direct-import or operator-upload the Grok MP4 for {scene_id}. Naming it {expected_file_name} in {incoming_dir} "
                "is safest, but not required; batch upload maps unnamed Grok files by scene-row take groups."
            ),
            "operatorChecklist": _scene_operator_checklist(scene_id, shot_bible),
            "originalImageSource": item.get("original_image_source") or item.get("image_source") or "",
            "grokAutoExpanded": item.get("grok_auto_expanded") is True,
        }
        take_prompts = _scene_take_prompts(scene_record, {**item, "sceneId": scene_id}, shot_bible)
        for take in take_prompts:
            take_number = _normalize_take_number(take.get("takeNumber"))
            take_file = prompts_dir / f"{scene_id}.take-{take_number}.prompt.txt"
            take_file.write_text(str(take.get("prompt") or "").strip() + "\n", encoding="utf-8")
            take["promptPath"] = _relative_project_path(take_file)
        scene_record["takePrompts"] = take_prompts
        scenes.append(scene_record)

    manifest = {
        "projectId": project_id,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "mode": "operator-approved-grok-web-handoff",
        "grokUrl": GROK_IMAGINE_URL,
        "qualityGateRequired": data.get("qualityGateRequired") is True,
        "grokMainSourceRequired": grok_main_required,
        "sourceMixTotalScenes": source_mix_total_scenes,
        "minGrokMainScenes": min_grok_main_scenes,
        "grokTargetSelection": target_selection,
        **_default_download_dir(),
        "incomingDir": str(incoming_dir),
        "promptsDir": str(prompts_dir),
        "sourcePrompt": str(source_prompt),
        "productionContext": production_context,
        "draftScenes": _safe_draft_scenes(draft_scenes),
        "shotBible": shot_bible,
        "scenes": scenes,
        "automationContract": {
            "usesPaidApi": False,
            "storesCredentials": False,
            "usesRemoteDebugging": False,
            "usesPersistentAutomationProfile": False,
            "requiresOperatorBrowserSession": True,
            "remoteDebuggingAllowedWithExplicitApproval": True,
            "browserPromptInjection": f"POST /api/grok-handoff/{project_id}/browser-automation",
            "browserPromptInjectionRequires": [
                "operatorApproved=true",
                "browserAutomationApproved=true",
                "profileApproved=true when launching Chrome/Edge",
            ],
            "downloadFolderImport": f"POST /api/grok-handoff/{project_id}/import-downloads",
            "backgroundAutomation": f"POST /api/grok-handoff/{project_id}/background-automation",
            "chromeCompanionExtension": f"GET /api/grok-handoff/{project_id}/chrome-extension",
            "chromeCompanionCommand": f"GET /api/grok-handoff/{project_id}/extension-command?operatorApproved=true",
            "postImportReview": f"GET /api/grok-handoff/{project_id}/review-packet",
            "reviewDecisionPersist": f"POST /api/grok-handoff/{project_id}/review-decision",
            "downloadNaming": "scene-id based MP4 filenames, e.g. scene-01.grok.mp4",
            "syncAction": "GET /api/grok-handoff/<projectId>/status then render with server-side sceneAssets",
        },
    }
    worksheet_path = _write_operator_worksheet(handoff_dir, manifest)
    production_queue_path = _write_production_queue(handoff_dir, manifest)
    manifest["worksheetPath"] = str(worksheet_path)
    manifest["worksheetUrl"] = _worksheet_url(project_id)
    manifest["productionQueuePath"] = str(production_queue_path)
    manifest["productionQueueUrl"] = _production_queue_url(project_id)
    manifest["productionQueueVersion"] = GROK_PRODUCTION_QUEUE_VERSION
    manifest["automationPlanUrl"] = _automation_plan_url(project_id)
    manifest["reviewPacketUrl"] = _review_packet_url(project_id)
    manifest["reviewDecisionUrl"] = _review_decision_url(project_id)
    manifest["chromeCompanionExtension"] = _chrome_companion_summary(project_id, handoff_dir, manifest)
    review_packet_path = _write_review_packet(handoff_dir, manifest)
    manifest["reviewPacketPath"] = str(review_packet_path)
    manifest_path = _manifest_path(project_id)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    assets = _match_downloaded_assets(handoff_dir, manifest)
    main_source_gate = _grok_main_source_gate(manifest, assets)
    scene_queue = _scene_queue_status(handoff_dir, manifest)
    next_scene = _select_grok_scene(manifest, str(scene_queue.get("nextMissingSceneId") or ""))
    companion_connection = _companion_connection_status(_latest_extension_event(handoff_dir))
    generation_observation = _latest_codex_chrome_observation(manifest)
    manual_primary_path = _manual_primary_path(
        project_id,
        handoff_dir,
        manifest,
        next_scene,
        main_source_gate,
        None,
        companion_connection,
    )
    main_path_status = _grok_main_path_status(
        project_id,
        handoff_dir,
        manifest,
        assets,
        main_source_gate,
        scene_queue,
        next_scene,
        manual_primary_path,
        None,
        None,
        None,
        companion_connection,
        generation_observation,
    )

    return jsonify({
        "ok": True,
        "projectId": project_id,
        "handoffDir": str(handoff_dir),
        "manifestPath": str(manifest_path),
        "incomingDir": str(incoming_dir),
        "grokUrl": GROK_IMAGINE_URL,
        "defaultDownloadDir": manifest.get("defaultDownloadDir"),
        "defaultDownloadDirExists": manifest.get("defaultDownloadDirExists"),
        "worksheetPath": str(worksheet_path),
        "worksheetUrl": _worksheet_url(project_id),
        "productionQueuePath": str(production_queue_path),
        "productionQueueUrl": _production_queue_url(project_id),
        "productionQueueVersion": GROK_PRODUCTION_QUEUE_VERSION,
        "automationPlanUrl": _automation_plan_url(project_id),
        "reviewPacketPath": str(review_packet_path),
        "reviewPacketUrl": _review_packet_url(project_id),
        "reviewDecisionUrl": _review_decision_url(project_id),
        "chromeCompanionExtension": manifest["chromeCompanionExtension"],
        "mainSourceGate": main_source_gate,
        "manualPrimaryPath": manual_primary_path,
        "mainPathStatus": main_path_status,
        "observedPostImportPlan": main_path_status.get("observedPostImportPlan") or {},
        "codexChromeObservation": generation_observation,
        "grokTargetSelection": target_selection,
        "shotBible": shot_bible,
        "scenes": scenes,
    })


@grok_bp.route("/api/grok-handoff/<project_id>/open-browser", methods=["POST"])
def open_grok_handoff_route(project_id: str):
    """Open the no-session operator worksheet in the default browser."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    targets = _normalize_open_targets(data.get("openTargets") or data.get("target"), default=("worksheet",))
    open_result = _open_handoff_targets(
        project_id,
        manifest,
        targets,
        data.get("browserPreference"),
        data.get("sceneId") or data.get("scene_id"),
    )
    target = "both" if len(targets) > 1 else targets[0]
    download_defaults = _download_defaults_for_manifest(manifest)
    return jsonify({
        "ok": True,
        "projectId": manifest.get("projectId") or project_id,
        "grokUrl": manifest.get("grokUrl") or GROK_IMAGINE_URL,
        "worksheetUrl": _worksheet_url(project_id),
        "automationPlanUrl": manifest.get("automationPlanUrl") or _automation_plan_url(project_id),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        "target": target,
        "incomingDir": manifest.get("incomingDir"),
        **download_defaults,
        **open_result,
    })


@grok_bp.route("/api/grok-handoff/<project_id>/operator-focus", methods=["POST"])
def grok_handoff_operator_focus_route(project_id: str):
    """Focus the active Grok/xAI browser tab after explicit operator approval."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    if (
        data.get("operatorApproved") is not True
        or data.get("browserAutomationApproved") is not True
        or data.get("focusApproved") is not True
    ):
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true, browserAutomationApproved=true, and focusApproved=true are required before focusing local browser tabs",
        }), 403

    port = _bounded_int(data.get("remoteDebuggingPort"), default=9222, minimum=9000, maximum=65535)
    opened_target = None
    try:
        _wait_for_cdp(port, timeout_seconds=3)
        automation_status = _read_automation_status(handoff_dir)
        prefer_auth = (
            data.get("preferAuthTarget") is True
            or (
                isinstance(automation_status, dict)
                and (
                    automation_status.get("authRequired") is True
                    or automation_status.get("browserBlocker") == "grok-auth-required"
                )
            )
        )
        target_info = _cdp_grok_operator_targets(port, prefer_auth)
        if not target_info.get("bestTarget") and data.get("openGrokIfMissing") is True:
            created = _cdp_new_target(port, str(manifest.get("grokUrl") or GROK_IMAGINE_URL))
            opened_target = {
                "targetId": str(created.get("id") or ""),
                "title": str(created.get("title") or ""),
                "url": str(created.get("url") or manifest.get("grokUrl") or GROK_IMAGINE_URL),
                "kind": "grok-imagine",
                "score": 320,
            }
            target_info = _cdp_grok_operator_targets(port, prefer_auth)
            if not target_info.get("bestTarget"):
                target_info["bestTarget"] = opened_target
                target_info["targets"] = [opened_target, *(target_info.get("targets") or [])][:8]
        best_target = target_info.get("bestTarget") if isinstance(target_info.get("bestTarget"), dict) else None
        activated = False
        activation_result = None
        if best_target:
            activation_result = _cdp_activate_target(port, str(best_target.get("targetId") or ""))
            activated = True
        kind = str(best_target.get("kind") if best_target else "")
        if kind in {"grok-auth", "xai-auth", "x-oauth", "x-login"}:
            operator_next_action = "Complete Grok/xAI login, captcha, payment, or safety checks in the focused tab; the background job will resume."
        elif kind.startswith("grok"):
            operator_next_action = "Keep this Grok Imagine tab open; background automation will inject the prompt or continue generation when ready."
        else:
            operator_next_action = "No Grok operator tab was found; open Grok Imagine and rerun approved focus or background automation."
        return jsonify({
            "ok": True,
            "projectId": manifest.get("projectId") or project_id,
            "remoteDebuggingPort": port,
            "focused": activated,
            "activated": activated,
            "activationResult": activation_result,
            "openedTarget": opened_target,
            "operatorNextAction": operator_next_action,
            **target_info,
        })
    except Exception as exc:
        logger.warning("Grok operator focus failed: %s", exc)
        return jsonify({
            "ok": False,
            "projectId": manifest.get("projectId") or project_id,
            "remoteDebuggingPort": port,
            "error": str(exc),
            "operatorNextAction": "Start Chrome/Edge with --remote-debugging-port=9222, then rerun approved Grok operator focus.",
        }), 502


@grok_bp.route("/api/grok-handoff/<project_id>/operator-tabs/cleanup", methods=["POST"])
def grok_handoff_operator_tabs_cleanup_route(project_id: str):
    """Close duplicate Grok/xAI tabs after explicit operator approval."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    if (
        data.get("operatorApproved") is not True
        or data.get("browserAutomationApproved") is not True
        or data.get("closeDuplicatesApproved") is not True
    ):
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true, browserAutomationApproved=true, and closeDuplicatesApproved=true are required before closing local browser tabs",
        }), 403

    port = _bounded_int(data.get("remoteDebuggingPort"), default=9222, minimum=9000, maximum=65535)
    keep_count = _bounded_int(data.get("keepCount"), default=1, minimum=1, maximum=3)
    try:
        _wait_for_cdp(port, timeout_seconds=3)
        automation_status = _read_automation_status(handoff_dir)
        prefer_auth = (
            data.get("preferAuthTarget") is True
            or (
                isinstance(automation_status, dict)
                and (
                    automation_status.get("authRequired") is True
                    or automation_status.get("browserBlocker") == "grok-auth-required"
                )
            )
        )
        target_info = _cdp_grok_operator_targets(port, prefer_auth=prefer_auth, limit=100)
        targets = [item for item in target_info.get("targets") or [] if isinstance(item, dict)]
        keep_targets = targets[:keep_count]
        keep_ids = {str(item.get("targetId") or "") for item in keep_targets}
        close_targets = [item for item in targets if str(item.get("targetId") or "") and str(item.get("targetId") or "") not in keep_ids]
        closed = []
        failed = []
        for target in close_targets:
            target_id = str(target.get("targetId") or "")
            try:
                result = _cdp_close_target(port, target_id)
                closed.append({**target, "result": result})
            except Exception as exc:
                failed.append({**target, "error": str(exc)})
        refreshed = _cdp_grok_operator_targets(port, prefer_auth=prefer_auth, limit=12)
        best_target = refreshed.get("bestTarget") if isinstance(refreshed.get("bestTarget"), dict) else None
        if best_target:
            try:
                _cdp_activate_target(port, str(best_target.get("targetId") or ""))
            except Exception:
                pass
        operator_next_action = (
            "Complete Grok/xAI login in the remaining focused tab; the background job will resume."
            if prefer_auth
            else "Continue in the remaining Grok Imagine tab; the background job will resume when controls are ready."
        )
        return jsonify({
            "ok": True,
            "projectId": manifest.get("projectId") or project_id,
            "remoteDebuggingPort": port,
            "preferAuthTarget": prefer_auth,
            "keepCount": keep_count,
            "keptTargets": keep_targets,
            "closedTargets": closed,
            "failedTargets": failed,
            "closedCount": len(closed),
            "failedCount": len(failed),
            "operatorNextAction": operator_next_action,
            **refreshed,
        })
    except Exception as exc:
        logger.warning("Grok operator tab cleanup failed: %s", exc)
        return jsonify({
            "ok": False,
            "projectId": manifest.get("projectId") or project_id,
            "remoteDebuggingPort": port,
            "error": str(exc),
            "operatorNextAction": "Start Chrome/Edge with --remote-debugging-port=9222, then rerun approved Grok tab cleanup.",
        }), 502


@grok_bp.route("/api/grok-handoff/<project_id>/status", methods=["GET"])
def grok_handoff_status_route(project_id: str):
    """Scan the handoff incoming folder and return matched MP4 scene assets."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    manifest, _ = _ensure_production_queue(
        handoff_dir,
        manifest,
        str(manifest.get("projectId") or project_id),
        refresh_live=False,
    )
    assets = _match_downloaded_assets(handoff_dir, manifest)
    main_source_gate = _grok_main_source_gate(manifest, assets)
    local_ready_assets = [
        item for item in assets if item.get("status") == "ready" and item.get("sceneId")
    ]
    ready_assets = _grok_status_ready_assets(manifest, assets)
    quality_gate_required = manifest.get("qualityGateRequired") is True
    quality_gate = {
        "required": quality_gate_required,
        "readySceneIds": [
            str(item.get("sceneId"))
            for item in local_ready_assets
            if item.get("qualityGate", {}).get("status") == "accepted"
        ],
        "pendingSceneIds": [
            str(item.get("sceneId"))
            for item in local_ready_assets
            if item.get("qualityGate", {}).get("status") in {"pending-operator-review", "technical-review", "source-review", "shot-lock-review"}
        ],
        "rejectedSceneIds": [
            str(item.get("sceneId"))
            for item in local_ready_assets
            if item.get("qualityGate", {}).get("status") == "rejected"
        ],
        "replacementSceneIds": [
            str(item.get("sceneId"))
            for item in local_ready_assets
            if _grok_asset_needs_replacement(item, manifest)
        ],
    }
    quality_gate["allReady"] = (
        not quality_gate_required
        or (
            len(quality_gate["readySceneIds"]) >= len(manifest.get("scenes") or [])
            and not quality_gate["pendingSceneIds"]
            and not quality_gate["rejectedSceneIds"]
        )
    )
    scene_count = len(manifest.get("scenes") or [])
    scene_queue = _scene_queue_status(handoff_dir, manifest, assets)
    next_scene = _select_grok_scene(manifest, str(scene_queue.get("nextMissingSceneId") or ""))
    download_defaults = _download_defaults_for_manifest(manifest)
    project_key = str(manifest.get("projectId") or project_id)
    automation_status = _read_automation_status(handoff_dir)
    stored_request = _read_automation_request(handoff_dir)
    automation_replay = _automation_replay_summary(stored_request)
    automation_job = _automation_job_summary(_read_automation_job_status(handoff_dir), project_key, stored_request)
    manual_download_watch_job = _manual_download_watch_summary(_read_manual_download_watch_status(handoff_dir), project_key)
    automation_status = _effective_automation_status_for_active_job(automation_status, automation_job)
    automation_status = _enrich_stale_automation_status_blocker(
        automation_status,
        (stored_request or {}).get("remoteDebuggingPort") if isinstance(stored_request, dict) else None,
    )
    latest_extension_event = _latest_extension_event(handoff_dir)
    companion_connection = _companion_connection_status(latest_extension_event)
    generation_observation = _latest_codex_chrome_observation(manifest)
    manual_primary_path = _manual_primary_path(
        project_key,
        handoff_dir,
        manifest,
        next_scene,
        main_source_gate,
        automation_status,
        companion_connection,
    )
    main_path_status = _grok_main_path_status(
        project_key,
        handoff_dir,
        manifest,
        assets,
        main_source_gate,
        scene_queue,
        next_scene,
        manual_primary_path,
        automation_status,
        automation_job,
        manual_download_watch_job,
        companion_connection,
        generation_observation,
    )
    return jsonify({
        "ok": True,
        "projectId": project_key,
        "handoffDir": str(handoff_dir),
        "incomingDir": manifest.get("incomingDir"),
        "grokUrl": manifest.get("grokUrl") or GROK_IMAGINE_URL,
        **download_defaults,
        "worksheetUrl": manifest.get("worksheetUrl") or _worksheet_url(project_id),
        "productionQueueUrl": manifest.get("productionQueueUrl") or _production_queue_url(project_id),
        "productionQueueVersion": manifest.get("productionQueueVersion") or GROK_PRODUCTION_QUEUE_VERSION,
        "automationPlanUrl": manifest.get("automationPlanUrl") or _automation_plan_url(project_id),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        "downloadImport": _download_import_actions(project_key, manifest, next_scene),
        "operatorRun": _operator_run_actions(project_key, manifest, next_scene),
        "manualPrimaryPath": manual_primary_path,
        "mainPathStatus": main_path_status,
        "observedPostImportPlan": main_path_status.get("observedPostImportPlan") or {},
        "grokAssetAcquisition": main_path_status.get("assetAcquisition") or {},
        "grokMainSourceDiagnosis": {
            "modelBlocked": False,
            "generationObserved": bool((main_path_status.get("assetAcquisition") or {}).get("clipGenerated")),
            "localMp4Imported": bool((main_path_status.get("assetAcquisition") or {}).get("localMp4Imported")),
            "currentBlocker": (main_path_status.get("assetAcquisition") or {}).get("primaryBlocker")
            or main_path_status.get("blocker")
            or "",
            "recommendedPrimaryPath": "grok-app-web-generated-mp4-local-import",
            "doNotDowngradeToStockOnly": True,
        },
        "operatorNextAction": manual_primary_path.get("operatorNextAction"),
        "primaryOperatorNextAction": manual_primary_path.get("operatorNextAction"),
        "reviewDecisions": manifest.get("reviewDecisions") if isinstance(manifest.get("reviewDecisions"), dict) else {},
        "qualityGate": quality_gate,
        "mainSourceGate": main_source_gate,
        "grokTargetSelection": manifest.get("grokTargetSelection") if isinstance(manifest.get("grokTargetSelection"), dict) else {},
        "chromeCompanionExtension": _chrome_companion_summary(
            project_key,
            handoff_dir,
            manifest,
            scene_id=(next_scene or {}).get("sceneId") if isinstance(next_scene, dict) else None,
            next_scene=next_scene,
            assets=assets,
            scene_queue=scene_queue,
        ),
        "latestExtensionEvent": latest_extension_event,
        "codexChromeObservation": generation_observation,
        "companionConnection": companion_connection,
        "assets": assets,
        "readyScenes": len(ready_assets),
        "totalScenes": scene_count,
        "allReady": scene_count > 0 and len(ready_assets) >= scene_count,
        **scene_queue,
        **({"automationStatus": automation_status} if automation_status else {}),
        **({"automationReplay": automation_replay} if automation_replay else {}),
        **({"automationJob": automation_job} if automation_job else {}),
        **({"manualDownloadWatchJob": manual_download_watch_job} if manual_download_watch_job else {}),
    })


@grok_bp.route("/api/grok-handoff/<project_id>/render-payload", methods=["GET"])
def grok_handoff_render_payload_route(project_id: str):
    """Return a render-smoke payload from synced Grok handoff MP4s."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    payload = _render_payload_from_manifest(handoff_dir, manifest)
    if not payload["allReady"]:
        return jsonify({
            "ok": False,
            "error": "Grok handoff MP4s are not complete",
            **payload,
        }), 409
    return jsonify({"ok": True, **payload})


@grok_bp.route("/api/grok-handoff/<project_id>/render-preview-payload", methods=["GET"])
def grok_handoff_render_preview_payload_route(project_id: str):
    """Return a preview render-smoke payload from the imported Grok MP4s that are ready now."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    payload = _render_payload_from_manifest(handoff_dir, manifest, preview_mode=True)
    if not payload["previewReady"]:
        return jsonify({
            "ok": False,
            "error": "No imported Grok MP4 clips are ready for preview",
            **payload,
        }), 409
    return jsonify({"ok": True, **payload})


@grok_bp.route("/api/grok-handoff/<project_id>/automation-plan", methods=["GET"])
def grok_handoff_automation_plan_route(project_id: str):
    """Return the approval-gated browser/download automation plan for this handoff."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    manifest, _ = _ensure_production_queue(handoff_dir, manifest, str(manifest.get("projectId") or project_id))
    return jsonify(_automation_plan_from_manifest(handoff_dir, manifest))


@grok_bp.route("/api/grok-handoff/<project_id>/extension-command", methods=["GET"])
def grok_handoff_extension_command_route(project_id: str):
    """Return a scene command for the local Chrome companion extension."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    if str(flask_request.args.get("operatorApproved") or "").lower() != "true":
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true is required before the Chrome companion can read a Grok prompt",
        }), 403
    scene = _extension_scene(manifest, flask_request.args.get("sceneId")) or _next_missing_or_rejected_scene(handoff_dir, manifest)
    if scene is None:
        return jsonify({"ok": False, "error": "No Grok scene is available for the Chrome companion"}), 400
    requested_take = flask_request.args.get("take") or flask_request.args.get("takeNumber")
    take_number = (
        _normalize_take_number(requested_take)
        if requested_take is not None
        else _recommended_take_number(scene)
    )
    return jsonify(_extension_command_payload(project_id, handoff_dir, manifest, scene, take_number))


@grok_bp.route("/api/grok-handoff/<project_id>/extension-event", methods=["POST"])
def grok_handoff_extension_event_route(project_id: str):
    """Record local Chrome companion extension progress without storing credentials."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    if data.get("operatorApproved") is not True or data.get("extensionApproved") is not True:
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true and extensionApproved=true are required before extension events are accepted",
        }), 403
    scene_id = _safe_project_id(data.get("sceneId") or "unknown-scene")
    record = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "projectId": str(manifest.get("projectId") or project_id),
        "sceneId": scene_id,
        "eventType": _short_text(data.get("eventType"), fallback="extension-event", limit=80),
        "status": _short_text(data.get("status"), fallback="reported", limit=80),
        "detail": _short_text(data.get("detail") or data.get("message"), limit=400),
        "currentUrl": _short_text(data.get("currentUrl"), limit=260),
        "candidateUrl": _short_text(data.get("candidateUrl"), limit=260),
        "sourceKind": _short_text(data.get("sourceKind"), limit=80),
        "videoWidth": _short_text(data.get("videoWidth"), limit=20),
        "videoHeight": _short_text(data.get("videoHeight"), limit=20),
        "qualityFloorMet": _short_text(data.get("qualityFloorMet"), limit=20),
        "qualityNote": _short_text(data.get("qualityNote"), limit=160),
        "expectedFileName": _short_text(data.get("expectedFileName"), limit=120),
    }
    path = _extension_event_log_path(handoff_dir)
    path.write_text(
        (path.read_text(encoding="utf-8") if path.exists() else "")
        + json.dumps(record, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return jsonify({
        "ok": True,
        "projectId": str(manifest.get("projectId") or project_id),
        "latestExtensionEvent": record,
        "statusUrl": f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/status",
    })


@grok_bp.route("/api/grok-handoff/<project_id>/codex-chrome-observation", methods=["POST"])
def grok_handoff_codex_chrome_observation_route(project_id: str):
    """Record logged-in Codex Chrome Grok generation evidence without credentials."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    if data.get("operatorApproved") is not True or data.get("codexChromeApproved") is not True:
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true and codexChromeApproved=true are required before Codex Chrome observations are accepted",
        }), 403

    scene_queue = _scene_queue_status(handoff_dir, manifest)
    requested_scene_id = data.get("sceneId") or scene_queue.get("nextMissingSceneId")
    scene = _extension_scene(manifest, requested_scene_id) or _select_grok_scene(manifest, str(requested_scene_id or ""))
    scene_id = _safe_project_id((scene or {}).get("sceneId") or requested_scene_id or "unknown-scene")
    expected_file = str((scene or {}).get("expectedFileName") or f"{scene_id}.grok.mp4")
    post_url = _sanitize_observed_grok_url(data.get("postUrl") or data.get("currentUrl"))
    video_url = _sanitize_observed_grok_url(data.get("videoUrl") or data.get("candidateUrl"))
    duration_seconds = _bounded_float(
        data.get("durationSeconds") or data.get("durationSec") or data.get("duration"),
        default=0.0,
        minimum=0.0,
        maximum=120.0,
    )
    rendered_width = _bounded_int(
        data.get("renderedWidth") or data.get("videoWidth"),
        default=0,
        minimum=0,
        maximum=8192,
    )
    rendered_height = _bounded_int(
        data.get("renderedHeight") or data.get("videoHeight"),
        default=0,
        minimum=0,
        maximum=8192,
    )
    quality_floor_met = rendered_width >= 720 and rendered_height >= 1280
    upload_endpoint = f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/upload-mp4"
    status = _short_text(data.get("status"), fallback="generated-export-pending", limit=80)
    default_export_status = "pending-upload-endpoint-import" if video_url and quality_floor_met else "pending-download-import"
    export_status = _short_text(data.get("exportStatus"), fallback=default_export_status, limit=80)
    if video_url and quality_floor_met:
        operator_next_action = (
            f"Grok generated {scene_id} in the logged-in Chrome/SuperGrok session. "
            "Use the observed-post recovery console/bookmarklet or Video Studio Companion Import MP4 so the "
            f"720p+ visible MP4 is fetched inside the signed-in Grok tab and posted to the local uploadEndpoint at {upload_endpoint}; "
            "do not click Chrome Download if it opens a download approval dialog."
        )
    elif video_url:
        operator_next_action = (
            f"Grok generated {scene_id}, but the observed candidate is below the 720x1280 Grok-main floor. "
            "Generate a replacement or use direct import only after a 720p+ 9:16 MP4 candidate is visible."
        )
    else:
        operator_next_action = (
            f"Grok generated {scene_id} in the logged-in Chrome/SuperGrok session. "
            "Use the observed-post recovery console/bookmarklet or Video Studio Companion Import MP4 to post "
            f"{expected_file} to the local uploadEndpoint before falling back to Downloads import/watch."
        )
    record = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "projectId": str(manifest.get("projectId") or project_id),
        "sceneId": scene_id,
        "expectedFileName": expected_file,
        "source": "codex-chrome-extension",
        "status": status,
        "exportStatus": export_status,
        "exportBlocker": _short_text(data.get("exportBlocker"), limit=160),
        "postUrl": post_url,
        "videoUrl": video_url,
        "durationSeconds": duration_seconds,
        "renderedWidth": rendered_width,
        "renderedHeight": rendered_height,
        "qualityFloorMet": quality_floor_met,
        "directImportPreferred": bool(video_url and quality_floor_met),
        "uploadEndpoint": upload_endpoint,
        "detail": _short_text(data.get("detail") or data.get("message"), limit=400),
        "operatorNextAction": operator_next_action,
        "storesCredentials": False,
        "usesPaidApi": False,
    }
    observations = manifest.get("codexChromeObservations") if isinstance(manifest.get("codexChromeObservations"), list) else []
    observations = [item for item in observations if isinstance(item, dict)]
    observations.append(record)
    manifest["codexChromeObservations"] = observations[-50:]
    manifest["latestCodexChromeObservation"] = record
    _write_manifest(handoff_dir, manifest)
    path = _extension_event_log_path(handoff_dir)
    path.write_text(
        (path.read_text(encoding="utf-8") if path.exists() else "")
        + json.dumps({
            "updatedAt": record["updatedAt"],
            "projectId": record["projectId"],
            "sceneId": scene_id,
            "eventType": "codex-chrome-observation",
            "status": status,
            "detail": record["detail"],
            "currentUrl": post_url,
            "candidateUrl": video_url,
            "expectedFileName": expected_file,
            "videoWidth": rendered_width,
            "videoHeight": rendered_height,
            "qualityFloorMet": "true" if quality_floor_met else "false",
            "source": "codex-chrome-extension",
        }, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return jsonify({
        "ok": True,
        "projectId": str(manifest.get("projectId") or project_id),
        "codexChromeObservation": record,
        "statusUrl": f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/status",
        "manualBatchUploadEndpoint": f"/api/grok-handoff/{project_id}/upload-mp4-batch",
        "importDownloadsEndpoint": f"/api/grok-handoff/{project_id}/import-downloads",
    })


@grok_bp.route("/api/grok-handoff/<project_id>/observed-asset-manual-runway", methods=["GET"])
def grok_handoff_observed_asset_manual_runway_route(project_id: str):
    """Show a local operator runway without opening direct MP4 asset/download UI."""
    if str(flask_request.args.get("operatorApproved") or "").lower() != "true":
        return Response(
            "<!doctype html><title>Approval required</title><p>operatorApproved=true is required.</p>",
            status=403,
            mimetype="text/html",
        )

    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return Response(
            "<!doctype html><title>Not found</title><p>Grok handoff manifest not found.</p>",
            status=404,
            mimetype="text/html",
        )

    scene_queue = _scene_queue_status(handoff_dir, manifest)
    generation_observation = _latest_codex_chrome_observation(manifest) or {}
    requested_scene_id = str(
        flask_request.args.get("sceneId")
        or generation_observation.get("sceneId")
        or scene_queue.get("nextMissingSceneId")
        or ""
    ).strip()
    scene = _extension_scene(manifest, requested_scene_id) or _select_grok_scene(manifest, requested_scene_id)
    scene_id = str((scene or {}).get("sceneId") or requested_scene_id or "").strip()
    expected_file = str(
        generation_observation.get("expectedFileName")
        or (scene or {}).get("expectedFileName")
        or (f"{scene_id}.grok.mp4" if scene_id else "scene.grok.mp4")
    ).strip()
    video_url = _sanitize_observed_grok_url(generation_observation.get("videoUrl") or generation_observation.get("candidateUrl"))
    post_url = _sanitize_observed_grok_url(generation_observation.get("postUrl") or generation_observation.get("currentUrl"))
    status_endpoint = f"/api/grok-handoff/{project_id}/status"
    review_packet_url = str(manifest.get("reviewPacketUrl") or _review_packet_url(project_id))
    upload_endpoint = f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/upload-mp4"
    manual_batch_upload_endpoint = f"/api/grok-handoff/{project_id}/upload-mp4-batch"
    post_download_script_query = {"operatorApproved": "true"}
    if scene_id:
        post_download_script_query["sceneId"] = scene_id
    post_download_script_url = (
        f"/api/grok-handoff/{project_id}/observed-post-download.js?"
        + urllib.parse.urlencode(post_download_script_query)
    )
    post_download_script_absolute_url = f"http://{_bridge_host}:{_bridge_port}{post_download_script_url}"
    disabled_reason = ""
    if not scene_id:
        disabled_reason = "No sceneId is available for the observed Grok asset."
    elif not post_url:
        disabled_reason = "No observed Grok post URL is available yet."

    asset_block = (
        '<button class="primary" disabled>Direct MP4 asset open blocked</button>'
        if video_url
        else '<button class="primary" disabled>Observed MP4 unavailable</button>'
    )
    post_block = (
        f'<a class="secondary" href="{escape(post_url, quote=True)}" rel="noreferrer" target="_blank">Open Grok post</a>'
        if post_url
        else ""
    )
    post_recovery_block = (
        '<button class="secondary" id="copyPostRecovery">Copy post recovery console</button>'
        if post_url
        else ""
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Video Studio Grok MP4 runway</title>
  <style>
    :root {{ color-scheme: light dark; font-family: Inter, Segoe UI, Arial, sans-serif; }}
    body {{ margin: 0; padding: 32px; background: #101214; color: #f3f5f7; }}
    main {{ max-width: 920px; margin: 0 auto; }}
    h1 {{ font-size: 28px; margin: 0 0 8px; }}
    p {{ color: #c8ced6; line-height: 1.55; }}
    .panel {{ border: 1px solid #333a43; border-radius: 8px; padding: 20px; margin-top: 18px; background: #171b20; }}
    dl {{ display: grid; grid-template-columns: 180px 1fr; gap: 10px 16px; }}
    dt {{ color: #8fa0b4; }}
    dd {{ margin: 0; overflow-wrap: anywhere; }}
    code {{ background: #0b0d10; padding: 2px 6px; border-radius: 4px; }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }}
    button, a.primary, a.secondary {{ border: 0; border-radius: 6px; padding: 11px 14px; font-weight: 700; text-decoration: none; cursor: pointer; }}
    a.primary, button.primary {{ background: #4ade80; color: #07110b; }}
    a.secondary, button.secondary {{ background: #29313a; color: #f3f5f7; }}
    button:disabled {{ cursor: not-allowed; opacity: .48; }}
    .warning {{ color: #ffd166; }}
    .steps {{ margin: 14px 0 0 20px; color: #dce3eb; line-height: 1.55; }}
    .steps li {{ margin: 6px 0; }}
    .result {{ white-space: pre-wrap; background: #0b0d10; padding: 12px; border-radius: 6px; min-height: 80px; }}
  </style>
</head>
<body>
<main>
  <h1>Grok observed MP4 manual runway</h1>
  <p>This page keeps Grok as the main visual source without using paid API, CDP, stored credentials, native Chrome download prompts, or a Downloads watcher fallback.</p>
  <ol class="steps">
    <li>Use <strong>Open Grok post</strong>, then copy and run <strong>Copy post recovery console</strong> in that signed-in Grok post tab.</li>
    <li>The console path fetches the visible MP4/blob in the browser session and posts it to the local uploadEndpoint.</li>
    <li>If direct import fails, stop. Only use already-saved local MP4 batch upload when the operator explicitly owns that file.</li>
  </ol>
  <section class="panel">
    <dl>
      <dt>Project</dt><dd><code>{escape(str(manifest.get("projectId") or project_id))}</code></dd>
      <dt>Scene</dt><dd><code>{escape(scene_id or "unknown")}</code></dd>
      <dt>Expected filename</dt><dd><code id="expectedFileName">{escape(expected_file)}</code></dd>
      <dt>Upload endpoint</dt><dd><code>{escape(upload_endpoint)}</code></dd>
      <dt>Manual batch endpoint</dt><dd><code>{escape(manual_batch_upload_endpoint)}</code></dd>
      <dt>Observed MP4</dt><dd>{escape(video_url or "not available")}</dd>
      <dt>Grok post fallback</dt><dd>{escape(post_url or "not available")}</dd>
      <dt>Download prompt policy</dt><dd>Blocked for Codex automation. Do not open the direct MP4 asset URL from this page.</dd>
    </dl>
    {f'<p class="warning">{escape(disabled_reason)}</p>' if disabled_reason else ''}
    <div class="actions">
      {asset_block}
      <button class="secondary" id="copyName">Copy filename</button>
      {post_block}
      {post_recovery_block}
      <a class="secondary" href="{escape(review_packet_url, quote=True)}" target="_blank">Review packet</a>
    </div>
    <p>Direct MP4 asset navigation is blocked here because it can open Chrome's native download approval dialog and stall the operator. The Grok post recovery console path is the expected fallback because the asset can be browser-session bound.</p>
  </section>
  <section class="panel">
    <h2>Run result</h2>
    <pre class="result" id="result">Ready.</pre>
  </section>
</main>
<script>
const statusEndpoint = {json.dumps(status_endpoint)};
const postDownloadScriptUrl = {json.dumps(post_download_script_absolute_url)};
const expectedFileName = {json.dumps(expected_file)};
const result = document.getElementById("result");

function writeResult(label, data) {{
  result.textContent = label + "\\n" + JSON.stringify(data, null, 2);
}}

async function postJson(endpoint, body) {{
  const response = await fetch(endpoint, {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify(body)
  }});
  const data = await response.json();
  writeResult(endpoint + " -> " + response.status, data);
  return data;
}}

document.getElementById("copyName").addEventListener("click", async () => {{
  try {{
    await navigator.clipboard.writeText(expectedFileName);
    result.textContent = "Copied filename: " + expectedFileName;
  }} catch (error) {{
    result.textContent = "Copy failed. Filename: " + expectedFileName;
  }}
}});
const copyPostRecovery = document.getElementById("copyPostRecovery");
if (copyPostRecovery) {{
  copyPostRecovery.addEventListener("click", async () => {{
    const loader = `(() => {{
  const script = document.createElement("script");
  script.src = ${{JSON.stringify(postDownloadScriptUrl)}} + "&t=" + Date.now();
  script.async = true;
  script.onerror = () => alert("Video Studio Grok post recovery script failed to load from local bridge.");
  document.documentElement.appendChild(script);
}})();`;
    try {{
      await navigator.clipboard.writeText(loader);
      result.textContent = "Copied Grok post recovery console snippet. Open the Grok post tab and paste it into DevTools console; it direct-imports to the local uploadEndpoint without a Downloads watcher.";
    }} catch (error) {{
      result.textContent = "Copy failed. Console snippet:\\n" + loader;
    }}
  }});
}}
</script>
</body>
</html>
"""
    return Response(html, mimetype="text/html")


@grok_bp.route("/api/grok-handoff/<project_id>/observed-post-download.js", methods=["GET"])
def grok_handoff_observed_post_download_script_route(project_id: str):
    """Serve an operator-approved, extensionless Grok post MP4 recovery script."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    if str(flask_request.args.get("operatorApproved") or "").lower() != "true":
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true is required before serving the Grok post recovery script",
        }), 403
    generation_observation = _latest_codex_chrome_observation(manifest) or {}
    scene_queue = _scene_queue_status(handoff_dir, manifest)
    requested_scene_id = str(
        flask_request.args.get("sceneId")
        or generation_observation.get("sceneId")
        or scene_queue.get("nextMissingSceneId")
        or ""
    ).strip()
    scene = _extension_scene(manifest, requested_scene_id) or _select_grok_scene(manifest, requested_scene_id)
    scene_id = str((scene or {}).get("sceneId") or requested_scene_id or "").strip()
    if not scene_id:
        return jsonify({"ok": False, "error": "No Grok scene is available for the post recovery script"}), 400
    expected_file = str(
        generation_observation.get("expectedFileName")
        or (scene or {}).get("expectedFileName")
        or f"{scene_id}.grok.mp4"
    ).strip()
    command = {
        "ok": True,
        "projectId": project_id,
        "sceneId": scene_id,
        "expectedFileName": expected_file,
        "uploadEndpoint": f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/upload-mp4",
    }
    response = Response(_observed_post_download_javascript(project_id, command), mimetype="application/javascript")
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    response.headers["Cache-Control"] = "no-store"
    return response


@grok_bp.route("/api/grok-handoff/<project_id>/bookmarklet-event", methods=["GET"])
def grok_handoff_bookmarklet_event_route(project_id: str):
    """Record Grok bookmarklet fallback progress from an operator-approved Grok tab."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    if str(flask_request.args.get("operatorApproved") or "").lower() != "true":
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true is required before bookmarklet events are accepted",
        }), 403
    scene_id = _safe_project_id(flask_request.args.get("sceneId") or "unknown-scene")
    record = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "projectId": str(manifest.get("projectId") or project_id),
        "sceneId": scene_id,
        "eventType": _short_text(flask_request.args.get("eventType"), fallback="bookmarklet-event", limit=80),
        "status": _short_text(flask_request.args.get("status"), fallback="reported", limit=80),
        "detail": _short_text(flask_request.args.get("detail"), limit=400),
        "currentUrl": _short_text(flask_request.args.get("currentUrl"), limit=260),
        "candidateUrl": _short_text(flask_request.args.get("candidateUrl"), limit=260),
        "expectedFileName": _short_text(flask_request.args.get("expectedFileName"), limit=120),
        "sourceKind": _short_text(flask_request.args.get("sourceKind"), limit=80),
        "videoWidth": _short_text(flask_request.args.get("videoWidth"), limit=20),
        "videoHeight": _short_text(flask_request.args.get("videoHeight"), limit=20),
        "qualityFloorMet": _short_text(flask_request.args.get("qualityFloorMet"), limit=20),
        "qualityNote": _short_text(flask_request.args.get("qualityNote"), limit=160),
        "source": "bookmarklet-fallback",
    }
    path = _extension_event_log_path(handoff_dir)
    path.write_text(
        (path.read_text(encoding="utf-8") if path.exists() else "")
        + json.dumps(record, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return jsonify({
        "ok": True,
        "projectId": str(manifest.get("projectId") or project_id),
        "latestExtensionEvent": record,
        "statusUrl": f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/status",
    })


def _bookmarklet_json_response(payload: dict, status: int = 200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Cache-Control"] = "no-store"
    return response


@grok_bp.route("/api/grok-handoff/<project_id>/bookmarklet-import", methods=["GET", "OPTIONS"])
def grok_handoff_bookmarklet_import_route(project_id: str):
    """Import a just-downloaded Grok MP4 from Downloads for the bookmarklet queue fallback."""
    if flask_request.method == "OPTIONS":
        return _bookmarklet_json_response({"ok": True})
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return _bookmarklet_json_response({"ok": False, "error": "Grok handoff manifest not found"}, 404)
    if str(flask_request.args.get("operatorApproved") or "").lower() != "true":
        return _bookmarklet_json_response({
            "ok": False,
            "error": "operatorApproved=true is required before reading a local download folder",
        }, 403)

    defaults = _download_defaults_for_manifest(manifest)
    download_dir, error = _download_dir_from_request(
        flask_request.args.get("downloadDir") or defaults.get("defaultDownloadDir")
    )
    if error or download_dir is None:
        return _bookmarklet_json_response({"ok": False, "error": error}, 400)

    result = _import_downloads(
        handoff_dir,
        manifest,
        download_dir,
        allow_newest_fallback=str(flask_request.args.get("allowNewestFallback") or "true").lower() != "false",
        overwrite=str(flask_request.args.get("overwrite") or "").lower() == "true",
        since_handoff=str(flask_request.args.get("sinceHandoff") or "true").lower() != "false",
        scene_id_filter=str(flask_request.args.get("sceneId") or "").strip() or None,
        preserve_candidates=str(flask_request.args.get("preserveCandidates") or "true").lower() != "false",
    )
    _write_review_packet(handoff_dir, manifest)
    return _bookmarklet_json_response({
        "ok": True,
        "projectId": manifest.get("projectId") or project_id,
        "downloadDir": str(download_dir),
        "incomingDir": manifest.get("incomingDir"),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        **result,
    })


@grok_bp.route("/api/grok-handoff/<project_id>/bookmarklet.js", methods=["GET"])
def grok_handoff_bookmarklet_script_route(project_id: str):
    """Serve a one-shot Grok prompt fill/generate fallback for the current scene."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    if str(flask_request.args.get("operatorApproved") or "").lower() != "true":
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true is required before serving the Grok bookmarklet fallback",
        }), 403
    scene = _extension_scene(manifest, flask_request.args.get("sceneId")) or _next_missing_or_rejected_scene(handoff_dir, manifest)
    if scene is None:
        return jsonify({"ok": False, "error": "No Grok scene is available for the bookmarklet fallback"}), 400
    take_number = _normalize_take_number(flask_request.args.get("take") or flask_request.args.get("takeNumber"))
    command = _extension_command_payload(project_id, handoff_dir, manifest, scene, take_number)
    auto_generate = str(flask_request.args.get("autoGenerate") or "").lower() == "true"
    response = Response(_bookmarklet_javascript(project_id, command, auto_generate), mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@grok_bp.route("/api/grok-handoff/<project_id>/bookmarklet-queue.js", methods=["GET", "OPTIONS"])
def grok_handoff_bookmarklet_queue_script_route(project_id: str):
    """Serve an operator-approved Grok tab queue runner for missing/rejected scenes."""
    if flask_request.method == "OPTIONS":
        response = Response("", mimetype="application/javascript")
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["Cache-Control"] = "no-store"
        return response
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    if str(flask_request.args.get("operatorApproved") or "").lower() != "true":
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true is required before serving the Grok queue bookmarklet",
        }), 403
    scene = _extension_scene(manifest, flask_request.args.get("sceneId")) or _next_missing_or_rejected_scene(handoff_dir, manifest)
    max_scenes = _bounded_int(flask_request.args.get("maxScenes"), default=5, minimum=1, maximum=12)
    wait_seconds = _bounded_int(flask_request.args.get("waitSeconds"), default=180, minimum=20, maximum=600)
    if scene is None:
        complete_script = (
            "(() => {"
            f"sessionStorage.removeItem({json.dumps('videoStudioGrokQueue:' + str(manifest.get('projectId') or project_id))});"
            "alert('Video Studio Grok queue has no missing or rejected scenes. Open the review packet before render.');"
            "})()"
        )
        response = Response(complete_script, mimetype="application/javascript")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response
    command = _extension_command_payload(project_id, handoff_dir, manifest, scene)
    response = Response(
        _bookmarklet_queue_javascript(project_id, command, max_scenes=max_scenes, wait_seconds=wait_seconds),
        mimetype="application/javascript",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@grok_bp.route("/api/grok-handoff/<project_id>/direct-import-proof", methods=["GET"])
def grok_handoff_direct_import_proof_route(project_id: str):
    """Serve a one-screen operator monitor for live Grok direct-import proof."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    scene = _extension_scene(manifest, flask_request.args.get("sceneId")) or _next_missing_or_rejected_scene(handoff_dir, manifest)
    if scene is None:
        return jsonify({"ok": False, "error": "No Grok scene is available for direct import proof"}), 400

    scene_id = str(scene.get("sceneId") or "")
    command_payload = _extension_command_payload(project_id, handoff_dir, manifest, scene)
    generation_observation = _latest_codex_chrome_observation(manifest)
    observed_post_import_plan = _observed_grok_post_import_plan(project_id, manifest, scene, generation_observation)
    companion_summary = _chrome_companion_summary(project_id, handoff_dir, manifest, scene_id=scene_id, next_scene=scene)
    profile_probe = companion_summary.get("profileProbe") if isinstance(companion_summary.get("profileProbe"), dict) else {}
    guide_url = str(companion_summary.get("guideUrl") or _chrome_companion_guide_url(project_id, scene_id))
    upload_endpoint = str(command_payload.get("uploadEndpoint") or f"http://{_bridge_host}:{_bridge_port}/api/grok-handoff/{project_id}/upload-mp4")
    queue_console_snippet = str(command_payload.get("bookmarkletQueueInlineConsoleSnippet") or "")
    observed_console_snippet = str(observed_post_import_plan.get("observedPostDownloadConsoleSnippet") or "")
    observed_post_url = str(observed_post_import_plan.get("postUrl") or "")
    observed_bookmarklet = str(observed_post_import_plan.get("observedPostDownloadInlineUrl") or "")
    extension_dir = str(_chrome_companion_extension_dir())
    status_endpoint = f"/api/grok-handoff/{project_id}/status"
    audit_endpoint = "/api/final-video-library/audit?limit=5"

    observed_section = ""
    if observed_console_snippet or observed_post_url:
        observed_post_link = ""
        if observed_post_url:
            observed_post_link = (
                f'<a class="button" href="{escape(observed_post_url, quote=True)}" '
                'target="_blank" rel="noopener noreferrer">Open observed Grok post</a>'
            )
        observed_section = f"""
  <section>
    <h2>Observed Grok Post Direct Import</h2>
    <p>Use this path when the Grok post already shows a 720p+ vertical MP4 and Chrome Download opens an approval dialog. This proof snippet is direct-import only: if the browser-side fetch cannot post to the upload endpoint, it stops without clicking Download, Save, Export, or anchor downloads.</p>
    <p><strong>Observed post:</strong> <code>{escape(observed_post_url or "not recorded")}</code></p>
    <p><strong>Upload endpoint:</strong> <code>{escape(upload_endpoint)}</code></p>
    <p>
      {observed_post_link}
      <a class="button" href="{escape(observed_bookmarklet or "#", quote=True)}">Observed-post bookmarklet</a>
      <button class="button" type="button" data-copy-value="{escape(observed_console_snippet, quote=True)}">Copy observed-post console</button>
      <button class="button" type="button" data-copy-and-open="{escape(observed_console_snippet, quote=True)}" data-open-url="{escape(observed_post_url, quote=True)}">Copy console + open post</button>
      <button class="button" type="button" data-copy-value="{escape(upload_endpoint, quote=True)}">Copy upload endpoint</button>
    </p>
    <pre>{escape(observed_console_snippet)}</pre>
  </section>
"""

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Video Studio Grok Direct Import Proof Monitor</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 980px; margin: 28px auto; padding: 0 20px; line-height: 1.5; color: #111827; }}
    code, pre {{ background: #f3f4f6; border-radius: 6px; padding: 2px 6px; }}
    pre {{ padding: 12px; overflow: auto; white-space: pre-wrap; }}
    .button {{ display: inline-block; border: 1px solid #111827; border-radius: 6px; padding: 8px 12px; margin: 4px 8px 4px 0; color: #111827; text-decoration: none; font-weight: 700; background: #fff; }}
    .status {{ border-left: 4px solid #2563eb; padding: 10px 12px; background: #eff6ff; }}
    .warn {{ border-left-color: #d97706; background: #fffbeb; }}
    .ok {{ border-left-color: #059669; background: #ecfdf5; }}
    section {{ border-top: 1px solid #e5e7eb; padding-top: 18px; margin-top: 18px; }}
  </style>
</head>
<body>
  <h1>Direct Import Proof Monitor</h1>
  <p class="status warn">Goal proof is not complete until the live final-video audit reports <code>liveGrokDirectImportProven=true</code>. This page helps the operator run Companion/bookmarklet direct import without Chrome Download approval dialogs and watch the proof state update.</p>
  <section>
    <h2>Current Scene</h2>
    <p><strong>Project:</strong> <code>{escape(project_id)}</code></p>
    <p><strong>Scene:</strong> <code>{escape(scene_id)}</code> -> <code>{escape(str(scene.get("expectedFileName") or ""))}</code></p>
    <p><strong>Profile probe:</strong> <code>{escape(str(profile_probe.get("status") or "not checked"))}</code></p>
    <p><strong>Companion folder:</strong></p>
    <pre>{escape(extension_dir)}</pre>
    <p>
      <button class="button" type="button" data-copy-value="{escape(extension_dir, quote=True)}">Copy Companion folder</button>
      <a class="button" href="{escape(guide_url, quote=True)}">Open full Companion guide</a>
    </p>
    <p>Manual setup may require opening <code>chrome://extensions</code> yourself in the existing signed-in Chrome profile. This monitor does not open or automate Chrome extension settings.</p>
  </section>
  <section>
    <h2>Companion Command</h2>
    <p><strong>Command URL:</strong></p>
    <pre>{escape(str(command_payload.get("commandUrl") or ""))}</pre>
    <p><strong>Prep+Generate URL:</strong></p>
    <pre>{escape(str(command_payload.get("prepGenerateAutostartUrl") or ""))}</pre>
    <p><strong>Upload endpoint:</strong></p>
    <pre>{escape(upload_endpoint)}</pre>
    <p>
      <button class="button" type="button" data-copy-value="{escape(str(command_payload.get("commandUrl") or ""), quote=True)}">Copy command URL</button>
      <button class="button" type="button" data-copy-value="{escape(str(command_payload.get("prepGenerateAutostartUrl") or ""), quote=True)}">Copy Prep+Generate URL</button>
      <button class="button" type="button" data-copy-value="{escape(upload_endpoint, quote=True)}">Copy upload endpoint</button>
    </p>
  </section>
  <section>
    <h2>No-extension Queue Runner</h2>
    <p>Run this in the existing signed-in Grok tab if the Companion extension is not loaded. It direct-imports eligible MP4/blob candidates to the local uploadEndpoint before any browser download fallback.</p>
    <p>
      <a class="button" href="{escape(str(command_payload.get("bookmarkletQueueInlineUrl") or "#"), quote=True)}">Queue Fill+Generate+Direct Import bookmarklet</a>
      <button class="button" type="button" data-copy-value="{escape(queue_console_snippet, quote=True)}">Copy queue console runner</button>
    </p>
    <pre>{escape(queue_console_snippet)}</pre>
  </section>
  {observed_section}
  <section>
    <h2>Live Proof Status</h2>
    <p>
      <button class="button" type="button" id="vs-proof-refresh">Refresh proof status</button>
      <button class="button" type="button" data-copy-value="{escape(status_endpoint, quote=True)}">Copy status endpoint</button>
      <button class="button" type="button" data-copy-value="{escape(audit_endpoint, quote=True)}">Copy audit endpoint</button>
    </p>
    <pre id="vs-copy-status">Clipboard helper is ready.</pre>
    <pre id="vs-proof-status">Proof monitor polling has not run yet.</pre>
  </section>
  <script>
    (() => {{
      const statusEndpoint = {json.dumps(status_endpoint)};
      const auditEndpoint = {json.dumps(audit_endpoint)};
      const proofStatus = document.getElementById("vs-proof-status");
      const copyStatus = document.getElementById("vs-copy-status");

      async function jsonFrom(endpoint) {{
        const response = await fetch(endpoint, {{ cache: "no-store" }});
        if (!response.ok) throw new Error(`${{endpoint}} HTTP ${{response.status}}`);
        return response.json();
      }}

      async function refreshProofStatus() {{
        try {{
          const [status, audit] = await Promise.all([jsonFrom(statusEndpoint), jsonFrom(auditEndpoint)]);
          const companion = status.chromeCompanionExtension || {{}};
          const profile = companion.profileProbe || {{}};
          const proof = (audit.goalReadiness && audit.goalReadiness.liveGrokDirectImportProof) || {{}};
          const lines = [
            `liveGrokDirectImportProven=${{audit.goalReadiness && audit.goalReadiness.liveGrokDirectImportProven === true}}`,
            `goalComplete=${{audit.goalReadiness && audit.goalReadiness.goalComplete === true}}`,
            `companionProfileStatus=${{profile.status || "unknown"}}`,
            `latestExtensionEvent=${{(status.latestExtensionEvent && status.latestExtensionEvent.eventType) || ""}}/${{(status.latestExtensionEvent && status.latestExtensionEvent.status) || ""}}`,
            `proofSourceKind=${{proof.sourceKind || ""}}`,
            `proofImportMode=${{proof.importMode || ""}}`,
          ];
          proofStatus.textContent = lines.join("\\n");
          proofStatus.className = audit.goalReadiness && audit.goalReadiness.liveGrokDirectImportProven === true ? "ok" : "warn";
        }} catch (error) {{
          proofStatus.textContent = `Proof monitor refresh failed: ${{error && error.message ? error.message : error}}`;
          proofStatus.className = "warn";
        }}
      }}

      document.querySelectorAll("[data-copy-value]").forEach((button) => {{
        button.addEventListener("click", async () => {{
          const value = button.getAttribute("data-copy-value") || "";
          if (!value) return;
          try {{
            await navigator.clipboard.writeText(value);
            if (copyStatus) copyStatus.textContent = `Copied: ${{button.textContent || "value"}}`;
          }} catch (error) {{
            if (copyStatus) copyStatus.textContent = `Copy failed. Select the text manually. ${{error && error.message ? error.message : error}}`;
          }}
        }});
      }});
      document.querySelectorAll("[data-copy-and-open]").forEach((button) => {{
        button.addEventListener("click", async () => {{
          const value = button.getAttribute("data-copy-and-open") || "";
          const openUrl = button.getAttribute("data-open-url") || "";
          if (value) {{
            try {{
              await navigator.clipboard.writeText(value);
              if (copyStatus) copyStatus.textContent = `Copied: ${{button.textContent || "console snippet"}}`;
            }} catch (error) {{
              if (copyStatus) copyStatus.textContent = `Copy failed. Select the snippet manually. ${{error && error.message ? error.message : error}}`;
            }}
          }}
          if (openUrl) {{
            window.open(openUrl, "_blank", "noopener,noreferrer");
          }}
        }});
      }});
      document.getElementById("vs-proof-refresh")?.addEventListener("click", refreshProofStatus);
      refreshProofStatus();
      setInterval(refreshProofStatus, 5000);
    }})();
  </script>
</body>
</html>"""
    return html


@grok_bp.route("/api/grok-handoff/<project_id>/chrome-extension", methods=["GET"])
def grok_handoff_chrome_extension_guide_route(project_id: str):
    """Serve operator instructions for the existing Chrome companion path."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    scene = _extension_scene(manifest, flask_request.args.get("sceneId")) or _next_missing_or_rejected_scene(handoff_dir, manifest)
    if scene is None:
        return jsonify({"ok": False, "error": "No Grok scene is available for the Chrome companion"}), 400
    scene_id = str(scene.get("sceneId") or "")
    command_url = _extension_command_url(project_id, scene_id)
    autostart_url = _extension_autostart_url(project_id, scene_id)
    prep_generate_autostart_url = _extension_autostart_url(project_id, scene_id, "prep-generate")
    bookmarklet_url = _bookmarklet_url(project_id, scene_id)
    bookmarklet_generate_url = _bookmarklet_url(project_id, scene_id, True)
    bookmarklet_script_url = _bookmarklet_script_url(project_id, scene_id)
    bookmarklet_generate_script_url = _bookmarklet_script_url(project_id, scene_id, True)
    bookmarklet_queue_url = _bookmarklet_queue_url(project_id)
    bookmarklet_queue_script_url = _bookmarklet_queue_script_url(project_id)
    command_payload = _extension_command_payload(project_id, handoff_dir, manifest, scene)
    bookmarklet_inline_url = str(command_payload.get("bookmarkletInlineUrl") or bookmarklet_url)
    bookmarklet_generate_inline_url = str(command_payload.get("bookmarkletGenerateInlineUrl") or bookmarklet_generate_url)
    bookmarklet_queue_inline_url = str(command_payload.get("bookmarkletQueueInlineUrl") or bookmarklet_queue_url)
    generation_observation = _latest_codex_chrome_observation(manifest)
    observed_post_import_plan = _observed_grok_post_import_plan(project_id, manifest, scene, generation_observation)
    observed_post_section = ""
    if observed_post_import_plan:
        observed_steps = "\n".join(
            f"<li>{escape(str(step))}</li>"
            for step in observed_post_import_plan.get("operatorSteps", [])
        )
        if not observed_steps:
            observed_steps = (
                "<li>Open the observed Grok post in the existing signed-in Chrome profile, "
                "then run the console snippet below.</li>"
            )
        observed_post_url = str(observed_post_import_plan.get("postUrl") or "")
        observed_post_link = ""
        if observed_post_url:
            observed_post_link = (
                f'<a class="button" href="{escape(observed_post_url, quote=True)}" '
                'target="_blank" rel="noopener noreferrer">Open observed Grok post</a>'
            )
        observed_post_section = f"""
  <h2>Observed post direct import</h2>
  <p>Use this when a Grok post is already open and a 720p+ MP4 is visible, but the Chrome Download button opens an approval dialog. Run the snippet from the signed-in Grok post tab so Video Studio fetches the MP4 in that browser session and posts it to the local uploadEndpoint without Chrome Download approval dialog. The snippet is direct-import only and stops without clicking Download/Save/Export if direct fetch is unavailable.</p>
  <p><strong>Observed post:</strong> <code>{escape(str(observed_post_import_plan.get("postUrl") or "not recorded"))}</code></p>
  <p><strong>Upload endpoint:</strong> <code>{escape(str(observed_post_import_plan.get("uploadEndpoint") or ""))}</code></p>
  <p>
    {observed_post_link}
    <a class="button" href="{escape(str(observed_post_import_plan.get("observedPostDownloadInlineUrl") or "#"), quote=True)}">Observed post direct import bookmarklet</a>
  </p>
  <p>Console recovery snippet for the Grok post tab:</p>
  <pre>{escape(str(observed_post_import_plan.get("observedPostDownloadConsoleSnippet") or ""))}</pre>
  <p>
    <button class="button" type="button" data-copy-value="{escape(str(observed_post_import_plan.get("observedPostDownloadConsoleSnippet") or ""), quote=True)}">Copy observed-post console</button>
    <button class="button" type="button" data-copy-and-open="{escape(str(observed_post_import_plan.get("observedPostDownloadConsoleSnippet") or ""), quote=True)}" data-open-url="{escape(observed_post_url, quote=True)}">Copy console + open post</button>
    <button class="button" type="button" data-copy-value="{escape(str(observed_post_import_plan.get("uploadEndpoint") or ""), quote=True)}">Copy upload endpoint</button>
  </p>
  <ol>
    {observed_steps}
  </ol>
"""
    console_snippet = (
        "(() => { "
        "const s = document.createElement('script'); "
        f"s.src = {json.dumps(bookmarklet_generate_script_url)}; "
        "s.async = true; "
        "document.documentElement.appendChild(s); "
        "})();"
    )
    inline_console_snippet = str(
        command_payload.get("bookmarkletGenerateInlineConsoleSnippet") or console_snippet
    )
    queue_console_snippet = (
        "(() => { "
        "const s = document.createElement('script'); "
        f"s.src = {json.dumps(bookmarklet_queue_script_url)}; "
        "s.async = true; "
        "document.documentElement.appendChild(s); "
        "})();"
    )
    queue_inline_console_snippet = str(
        command_payload.get("bookmarkletQueueInlineConsoleSnippet") or queue_console_snippet
    )
    batch_upload_endpoint = f"/api/grok-handoff/{project_id}/upload-mp4-batch"
    batch_upload_script = """
  <script>
    (() => {
      const endpoint = __BATCH_UPLOAD_ENDPOINT__;
      const input = document.getElementById("vs-grok-batch-files");
      const button = document.getElementById("vs-grok-batch-upload");
      const status = document.getElementById("vs-grok-batch-status");
      const preflight = document.getElementById("vs-grok-batch-preflight");
      const mode = document.getElementById("vs-grok-batch-mode");
      const preserve = document.getElementById("vs-grok-preserve-candidates");
      const allowFlagged = document.getElementById("vs-grok-allow-flagged");
      const qualityFloor = {
        minShortEdge: 720,
        minLongEdge: 1280,
        minDurationSeconds: 3,
        maxDurationSeconds: 12,
        minBytes: 750000,
      };
      let latestAnalysis = [];

      function log(message) {
        if (status) status.textContent = message;
      }

      function renderPreflight(items) {
        latestAnalysis = items;
        if (!preflight) return;
        if (!items.length) {
          preflight.textContent = "Quality preflight: select native Grok MP4 files.";
          return;
        }
        preflight.textContent = items.map((item, index) => {
          const sizeMb = (item.size / 1048576).toFixed(2);
          const media = item.width && item.height && Number.isFinite(item.durationSeconds)
            ? `${item.width}x${item.height}, ${item.durationSeconds.toFixed(1)}s`
            : "metadata unavailable";
          const verdict = item.ok ? "PASS" : "FLAG";
          const reasons = item.reasons.length ? ` - ${item.reasons.join("; ")}` : "";
          return `${index + 1}. ${verdict} ${item.name} (${sizeMb} MB, ${media})${reasons}`;
        }).join("\\n");
      }

      function analyzeVideoFile(file) {
        return new Promise((resolve) => {
          const video = document.createElement("video");
          const objectUrl = URL.createObjectURL(file);
          let settled = false;
          const finish = (meta = {}) => {
            if (settled) return;
            settled = true;
            URL.revokeObjectURL(objectUrl);
            const width = Number(meta.width || 0);
            const height = Number(meta.height || 0);
            const durationSeconds = Number(meta.durationSeconds || 0);
            const shortEdge = Math.min(width || 0, height || 0);
            const longEdge = Math.max(width || 0, height || 0);
            const reasons = [];
            if (!file.name.toLowerCase().endsWith(".mp4")) reasons.push("not an .mp4 filename");
            if (file.size < qualityFloor.minBytes) reasons.push("file size below native-quality floor");
            if (!width || !height) reasons.push("resolution metadata unavailable");
            if (shortEdge && shortEdge < qualityFloor.minShortEdge) reasons.push("short edge below 720px");
            if (longEdge && longEdge < qualityFloor.minLongEdge) reasons.push("long edge below 1280px");
            if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) reasons.push("duration unavailable");
            if (durationSeconds && durationSeconds < qualityFloor.minDurationSeconds) reasons.push("duration below 3s");
            if (durationSeconds && durationSeconds > qualityFloor.maxDurationSeconds) reasons.push("duration above 12s for a short Grok take");
            resolve({
              name: file.name || "grok-video.mp4",
              size: file.size,
              width,
              height,
              durationSeconds,
              ok: reasons.length === 0,
              reasons,
            });
          };
          video.preload = "metadata";
          video.muted = true;
          video.onloadedmetadata = () => finish({
            width: video.videoWidth,
            height: video.videoHeight,
            durationSeconds: video.duration,
          });
          video.onerror = () => finish();
          setTimeout(() => finish(), 5000);
          video.src = objectUrl;
        });
      }

      async function analyzeSelectedFiles() {
        const files = Array.from(input?.files || []);
        if (!files.length) {
          renderPreflight([]);
          return [];
        }
        log(`Reading metadata for ${files.length} MP4 file(s)...`);
        const items = await Promise.all(files.map(analyzeVideoFile));
        renderPreflight(items);
        const flagged = items.filter((item) => !item.ok).length;
        log(flagged
          ? `${flagged} file(s) flagged before upload. Use only as proof-only candidates unless you deliberately override.`
          : "All selected files pass the browser-side native Grok MP4 preflight.");
        return items;
      }

      async function fileToBase64(file) {
        const bytes = new Uint8Array(await file.arrayBuffer());
        const chunkSize = 0x8000;
        let binary = "";
        for (let index = 0; index < bytes.length; index += chunkSize) {
          const chunk = bytes.subarray(index, index + chunkSize);
          binary += String.fromCharCode.apply(null, chunk);
        }
        return btoa(binary);
      }

      async function upload() {
        const files = Array.from(input?.files || []);
        if (!files.length) {
          log("Select one or more Grok MP4 files first.");
          return;
        }
        button.disabled = true;
        try {
          const analysis = latestAnalysis.length === files.length ? latestAnalysis : await analyzeSelectedFiles();
          const flagged = analysis.filter((item) => !item.ok);
          if (flagged.length && allowFlagged?.checked !== true) {
            log(`Upload blocked: ${flagged.length} file(s) failed quality preflight. Replace with native Grok MP4 or enable proof-only override.`);
            return;
          }
          log(`Encoding ${files.length} MP4 file(s)...`);
          const payloadFiles = [];
          for (const file of files) {
            payloadFiles.push({
              fileName: file.name || "grok-video.mp4",
              fileBase64: await fileToBase64(file),
            });
          }
          log("Uploading to the local Video Studio bridge...");
          const response = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              operatorApproved: true,
              preserveCandidates: preserve?.checked !== false,
              sceneMappingMode: mode?.value || "scene-grouped-takes",
              files: payloadFiles,
            }),
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok || data.ok === false) {
            throw new Error(data.error || `HTTP ${response.status}`);
          }
          const imported = Array.isArray(data.imported) ? data.imported : [];
          const importedText = imported.map((item) => `${item.sceneId || "scene"}:${item.fileName || "mp4"}`).join(", ");
          log(`Imported ${imported.length} Grok MP4 candidate(s). Ready ${data.readyScenes}/${data.totalScenes}. ${importedText}`);
        } catch (error) {
          log(`Upload failed: ${error && error.message ? error.message : error}`);
        } finally {
          button.disabled = false;
        }
      }

      input?.addEventListener("change", () => {
        analyzeSelectedFiles().catch((error) => log(`Preflight failed: ${error && error.message ? error.message : error}`));
      });
      allowFlagged?.addEventListener("change", () => renderPreflight(latestAnalysis));
      button?.addEventListener("click", upload);
      renderPreflight([]);
    })();
  </script>
""".replace("__BATCH_UPLOAD_ENDPOINT__", json.dumps(batch_upload_endpoint))
    extension_dir = _chrome_companion_extension_dir()
    profile_probe = _chrome_profile_companion_probe()
    codex_native_host = profile_probe.get("codexNativeHost") if isinstance(profile_probe.get("codexNativeHost"), dict) else {}
    profile_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(profile.get('profileDir') or ''))}</td>"
        f"<td>{escape(str(profile.get('profileName') or ''))}</td>"
        f"<td>{'yes' if profile.get('videoStudioCompanion') is True else 'no'}</td>"
        f"<td>{'yes' if profile.get('codexExtension') is True else 'no'}</td>"
        "</tr>"
        for profile in profile_probe.get("profiles", [])
        if isinstance(profile, dict)
    )
    if not profile_rows:
        profile_rows = (
            "<tr><td colspan=\"4\">No readable Chrome Preferences profiles were found from this runtime.</td></tr>"
        )
    scene_command_rows = "\n".join(
        "<li>"
        f"<strong>{escape(str(item.get('sceneId') or 'scene'))}</strong> "
        f"<code>{escape(str(item.get('expectedFileName') or 'scene.grok.mp4'))}</code>"
        f"<pre>{escape(_extension_command_url(project_id, str(item.get('sceneId') or '')))}</pre>"
        f"<p>Autostart fill: <code>{escape(_extension_autostart_url(project_id, str(item.get('sceneId') or '')))}</code></p>"
        "</li>"
        for item in (manifest.get("scenes") or [])
        if isinstance(item, dict)
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Video Studio Grok Chrome Companion</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 980px; margin: 32px auto; padding: 0 20px; line-height: 1.5; color: #141414; }}
    code, pre {{ background: #f3f4f6; border-radius: 6px; padding: 2px 6px; }}
    pre {{ padding: 12px; overflow: auto; white-space: pre-wrap; }}
    .pill {{ display: inline-block; border: 1px solid #d1d5db; border-radius: 999px; padding: 4px 10px; margin-right: 6px; }}
    .button {{ display: inline-block; border: 1px solid #111827; border-radius: 6px; padding: 8px 12px; margin: 4px 8px 4px 0; color: #111827; text-decoration: none; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f9fafb; }}
  </style>
</head>
<body>
  <h1>Video Studio Grok Chrome Companion</h1>
  <p><span class="pill">Existing Chrome profile</span><span class="pill">No xAI API</span><span class="pill">No CDP</span><span class="pill">No Edge</span></p>
  <h2>Local Chrome profile probe</h2>
  <p><strong>Status:</strong> {escape(str(profile_probe.get("status") or ""))}</p>
  <p>{escape(str(profile_probe.get("operatorAction") or ""))}</p>
  <table>
    <thead>
      <tr><th>Profile dir</th><th>Profile name</th><th>Video Studio Companion</th><th>Codex extension</th></tr>
    </thead>
    <tbody>
      {profile_rows}
    </tbody>
  </table>
  <p>The Codex Chrome extension does not control Grok for Video Studio. Grok-as-main-source needs the local Video Studio Grok Companion or the bookmarklet fallback in the signed-in Grok tab.</p>
  <p><strong>Codex native host:</strong> {escape(str(codex_native_host.get("status") or "not checked"))}. {escape(str(codex_native_host.get("operatorAction") or ""))}</p>
  <p>Load this unpacked extension in the Chrome profile where SuperGrok is already signed in:</p>
  <pre>{escape(str(extension_dir))}</pre>
  <p>
    <button class="button" type="button" data-copy-value="{escape(str(extension_dir), quote=True)}">Copy Companion folder</button>
    <button class="button" type="button" data-copy-value="{escape(command_url, quote=True)}">Copy command URL</button>
    <button class="button" type="button" data-copy-value="{escape(prep_generate_autostart_url, quote=True)}">Copy Prep+Generate URL</button>
  </p>
  <pre id="vs-copy-status">Clipboard helper is ready. Use the buttons above before Load unpacked or Companion command paste.</pre>
  <ol>
    <li>Open <code>chrome://extensions</code> in the existing logged-in Chrome profile.</li>
    <li>Enable Developer mode, click <strong>Load unpacked</strong>, and select the folder above.</li>
    <li>Open Grok Imagine in the same Chrome profile.</li>
    <li>Open the Video Studio Grok Companion toolbar popup and paste this command URL.</li>
    <li>Run Fill prompt, then Generate. Use Companion/pageAssets direct import; if that fails, stop and use the operator-owned batch upload path.</li>
    <li>Shortcut: open the autostart URL below in the same Chrome profile. The content script loads the command and fills the prompt without CDP.</li>
  </ol>
  <h2>Scene command URL</h2>
  <pre>{escape(command_url)}</pre>
  <h2>Autostart URL</h2>
  <pre>{escape(autostart_url)}</pre>
  <h2>Autostart + generate URL</h2>
  <pre>{escape(prep_generate_autostart_url)}</pre>
  <h2>Bookmarklet fallback</h2>
  <p>If the unpacked companion extension is not loaded in this Chrome profile, use the self-contained fallback in the current Grok tab. It embeds the prompt command directly instead of asking Grok to load a local script tag. Drag one of these links to the bookmarks bar, open Grok Imagine, then click the bookmarklet there. Clicking it on this guide page will not control Grok.</p>
  <p>
    <a class="button" href="{escape(bookmarklet_inline_url, quote=True)}">Fill Grok prompt</a>
    <a class="button" href="{escape(bookmarklet_generate_inline_url, quote=True)}">Fill + Generate</a>
  </p>
  <p>Script URL, useful for audit or legacy manual script injection:</p>
  <pre>{escape(bookmarklet_script_url)}</pre>
  <p>Console fallback (Inline console fallback, self-contained) for the Grok tab:</p>
  <pre>{escape(inline_console_snippet)}</pre>
  <p>Legacy console fallback that loads the local script URL:</p>
  <pre>{escape(console_snippet)}</pre>
  <h2>Queue Fill+Generate+Direct Import</h2>
  <p>Use this from the logged-in Grok tab when Grok MP4 should be the main video source. The self-contained runner fills the next missing or rejected scene, clicks Generate, then direct-imports a fetchable MP4/blob to the local uploadEndpoint. If direct import fails, it stops without clicking Download/Save/Export or anchor downloads. Re-run it after Companion direct import or operator-owned batch upload. Captcha, login, safety, and clip choice remain operator-owned. Legacy script URLs remain below for audit only.</p>
  <p>
    <a class="button" href="{escape(bookmarklet_queue_inline_url, quote=True)}">Queue Fill+Generate+Direct Import</a>
  </p>
  <p>Queue script URL:</p>
  <pre>{escape(bookmarklet_queue_script_url)}</pre>
  <p>Queue console fallback for the Grok tab:</p>
  <pre>{escape(queue_inline_console_snippet)}</pre>
  <p>
    <button class="button" type="button" data-copy-value="{escape(queue_inline_console_snippet, quote=True)}">Copy queue console runner</button>
  </p>
  <p>Legacy queue console fallback that loads the local script URL:</p>
  <pre>{escape(queue_console_snippet)}</pre>
  {observed_post_section}
  <h2>No-extension MP4 batch upload</h2>
  <p>If Companion heartbeat stays stale, keep using Grok app/web in the signed-in Chrome profile, then upload already-saved MP4 files here. This fallback is operator-owned and does not use the paid Grok API, CDP, cookies, or browser automation. For unnamed Grok files, select files grouped by scene row: all scene-01 takes first, then all scene-02 takes.</p>
  <p>
    <input id="vs-grok-batch-files" type="file" accept="video/mp4,video/*" multiple />
  </p>
  <pre id="vs-grok-batch-preflight">Quality preflight: select native Grok MP4 files.</pre>
  <p>
    <label>Mapping
      <select id="vs-grok-batch-mode">
        <option value="scene-grouped-takes" selected>scene grouped 2-take rows</option>
        <option value="scene-order-full-batch">one file per scene in order</option>
      </select>
    </label>
    <label style="margin-left: 12px;">
      <input id="vs-grok-preserve-candidates" type="checkbox" checked />
      preserve candidates
    </label>
    <label style="margin-left: 12px;">
      <input id="vs-grok-allow-flagged" type="checkbox" />
      allow proof-only flagged upload
    </label>
  </p>
  <p>
    <button class="button" type="button" id="vs-grok-batch-upload">Upload selected Grok MP4s to Video Studio</button>
  </p>
  <pre id="vs-grok-batch-status">Waiting for native Grok MP4 files.</pre>
  <h2>All scene command URLs</h2>
  <ol>
    {scene_command_rows}
  </ol>
  <h2>Scene</h2>
  <p><strong>{escape(scene_id)}</strong> -> <code>{escape(str(scene.get("expectedFileName") or ""))}</code></p>
  <h2>Guardrails</h2>
  <ul>
    <li>The extension reads only this local bridge command and the current Grok tab.</li>
    <li>It does not store passwords, cookies, API keys, or Grok credentials.</li>
    <li>It does not call paid xAI/Grok API endpoints.</li>
    <li>Captcha, login, safety, and payment prompts remain operator-owned.</li>
  </ul>
  <script>
    (() => {{
      const status = document.getElementById("vs-copy-status");
      document.querySelectorAll("[data-copy-value]").forEach((button) => {{
        button.addEventListener("click", async () => {{
          const value = button.getAttribute("data-copy-value") || "";
          if (!value) return;
          try {{
            await navigator.clipboard.writeText(value);
            if (status) status.textContent = `Copied: ${{button.textContent || "value"}}`;
          }} catch (error) {{
            if (status) status.textContent = `Copy failed. Select the text manually. ${{error && error.message ? error.message : error}}`;
          }}
        }});
      }});
      document.querySelectorAll("[data-copy-and-open]").forEach((button) => {{
        button.addEventListener("click", async () => {{
          const value = button.getAttribute("data-copy-and-open") || "";
          const openUrl = button.getAttribute("data-open-url") || "";
          if (value) {{
            try {{
              await navigator.clipboard.writeText(value);
              if (status) status.textContent = `Copied: ${{button.textContent || "console snippet"}}`;
            }} catch (error) {{
              if (status) status.textContent = `Copy failed. Select the snippet manually. ${{error && error.message ? error.message : error}}`;
            }}
          }}
          if (openUrl) {{
            window.open(openUrl, "_blank", "noopener,noreferrer");
          }}
        }});
      }});
    }})();
  </script>
{batch_upload_script}
</body>
</html>"""
    return html


@grok_bp.route("/api/grok-handoff/<project_id>/browser-automation", methods=["POST"])
def grok_handoff_browser_automation_route(project_id: str):
    """Inject the selected scene prompt into an operator-approved local Grok browser session."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    if data.get("operatorApproved") is not True or data.get("browserAutomationApproved") is not True:
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true and browserAutomationApproved=true are required before local browser control",
        }), 403

    requested_scene_id = str(data.get("sceneId") or "").strip()
    scene = _select_grok_scene(manifest, requested_scene_id)
    if scene is None:
        return jsonify({"ok": False, "error": "No Grok scene is available for browser automation"}), 400

    download_dir = None
    if str(data.get("downloadDir") or "").strip():
        download_dir, error = _download_dir_from_request(data.get("downloadDir"))
        if error or download_dir is None:
            return jsonify({"ok": False, "error": error}), 400
    elif data.get("downloadResultApproved") is True or data.get("watchDownloadsApproved") is True:
        return jsonify({
            "ok": False,
            "error": "downloadDir is required before downloadResultApproved=true or watchDownloadsApproved=true",
        }), 400

    replay_data = dict(data)
    replay_data["projectId"] = str(manifest.get("projectId") or project_id)
    replay_request = _automation_replay_request(scene, replay_data, download_dir)
    if data.get("preflightOnly") is not True:
        _write_automation_request(handoff_dir, replay_request)

    try:
        result = _run_grok_browser_automation(handoff_dir, manifest, scene, data, download_dir)
    except Exception as exc:
        logger.warning("Grok browser automation failed: %s", exc)
        port = _bounded_int(data.get("remoteDebuggingPort"), default=9222, minimum=9000, maximum=65535)
        error_state = _automation_error_state(str(exc), port)
        error_status = _build_automation_status(
            str(manifest.get("projectId") or project_id),
            scene,
            {
                "browserAutomationMode": "operator-approved-cdp-generate-download-watch",
                "remoteDebuggingPort": port,
                "useDefaultChromeProfile": data.get("useDefaultChromeProfile") is True,
                "attachDefaultChromeApproved": data.get("attachDefaultChromeApproved") is True,
                "browserProfileMode": (
                    "default-chrome-cdp-attach"
                    if data.get("useDefaultChromeProfile") is True
                    else "existing-or-isolated-cdp"
                ),
                **error_state,
            },
            error=str(exc),
        )
        _write_automation_status(handoff_dir, error_status)
        return jsonify({
            "ok": False,
            "projectId": manifest.get("projectId") or project_id,
            "sceneId": scene.get("sceneId"),
            "error": str(exc),
            "browserAutomationMode": "operator-approved-cdp-generate-download-watch",
            "automationStatus": error_status,
        }), 502

    automation_status = _build_automation_status(
        str(manifest.get("projectId") or project_id),
        scene,
        result,
    )
    _write_automation_status(handoff_dir, automation_status)
    return jsonify({
        "ok": True,
        "projectId": manifest.get("projectId") or project_id,
        "sceneId": scene.get("sceneId"),
        "expectedFileName": scene.get("expectedFileName"),
        "incomingDir": manifest.get("incomingDir"),
        "worksheetUrl": manifest.get("worksheetUrl") or _worksheet_url(project_id),
        "automationPlanUrl": manifest.get("automationPlanUrl") or _automation_plan_url(project_id),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
            "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
            "automationStatus": automation_status,
            "automationReplay": _automation_replay_summary(replay_request),
        **result,
    })


@grok_bp.route("/api/grok-handoff/<project_id>/resume-automation", methods=["POST"])
def grok_handoff_resume_automation_route(project_id: str):
    """Replay the last sanitized Grok browser automation request after fresh operator approval."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    if data.get("operatorApproved") is not True or data.get("browserAutomationApproved") is not True:
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true and browserAutomationApproved=true are required before replaying local browser control",
        }), 403

    stored_request = _read_automation_request(handoff_dir)
    if not stored_request:
        return jsonify({
            "ok": False,
            "error": "No previous Grok automation request is available to replay",
        }), 409

    replay_data = {key: stored_request.get(key) for key in _AUTOMATION_REPLAY_FIELDS if key in stored_request}
    for key in _AUTOMATION_REPLAY_FIELDS:
        if key in data:
            replay_data[key] = data.get(key)
    replay_data["projectId"] = str(manifest.get("projectId") or project_id)
    replay_data["operatorApproved"] = True
    replay_data["browserAutomationApproved"] = True
    replay_data["profileApproved"] = data.get("profileApproved") is True
    if "launchBrowserApproved" in data:
        replay_data["launchBrowserApproved"] = data.get("launchBrowserApproved") is True
    replay_data["preflightOnly"] = data.get("preflightOnly") is True

    scene = _select_grok_scene(manifest, str(replay_data.get("sceneId") or ""))
    if scene is None:
        return jsonify({"ok": False, "error": "No Grok scene is available for resume automation"}), 400

    download_dir = None
    if str(replay_data.get("downloadDir") or "").strip():
        download_dir, error = _download_dir_from_request(replay_data.get("downloadDir"))
        if error or download_dir is None:
            return jsonify({"ok": False, "error": error}), 400
    elif replay_data.get("downloadResultApproved") is True or replay_data.get("watchDownloadsApproved") is True:
        return jsonify({
            "ok": False,
            "error": "downloadDir is required before replaying downloadResultApproved=true or watchDownloadsApproved=true",
        }), 400

    replay_request = _automation_replay_request(scene, replay_data, download_dir)
    _write_automation_request(handoff_dir, replay_request)
    try:
        result = _run_grok_browser_automation(handoff_dir, manifest, scene, replay_data, download_dir)
    except Exception as exc:
        logger.warning("Grok resume automation failed: %s", exc)
        port = _bounded_int(replay_data.get("remoteDebuggingPort"), default=9222, minimum=9000, maximum=65535)
        error_state = _automation_error_state(str(exc), port)
        error_status = _build_automation_status(
            str(manifest.get("projectId") or project_id),
            scene,
            {
                "browserAutomationMode": "operator-approved-cdp-resume-generate-download-watch",
                "remoteDebuggingPort": port,
                "useDefaultChromeProfile": replay_data.get("useDefaultChromeProfile") is True,
                "attachDefaultChromeApproved": replay_data.get("attachDefaultChromeApproved") is True,
                "browserProfileMode": (
                    "default-chrome-cdp-attach"
                    if replay_data.get("useDefaultChromeProfile") is True
                    else "existing-or-isolated-cdp"
                ),
                **error_state,
            },
            error=str(exc),
        )
        _write_automation_status(handoff_dir, error_status)
        return jsonify({
            "ok": False,
            "projectId": manifest.get("projectId") or project_id,
            "sceneId": scene.get("sceneId"),
            "error": str(exc),
            "browserAutomationMode": "operator-approved-cdp-resume-generate-download-watch",
            "automationStatus": error_status,
            "automationReplay": _automation_replay_summary(replay_request),
        }), 502

    automation_status = _build_automation_status(
        str(manifest.get("projectId") or project_id),
        scene,
        {
            **result,
            "browserAutomationMode": result.get("browserAutomationMode") or "operator-approved-cdp-resume-generate-download-watch",
        },
    )
    _write_automation_status(handoff_dir, automation_status)
    return jsonify({
        "ok": True,
        "projectId": manifest.get("projectId") or project_id,
        "sceneId": scene.get("sceneId"),
        "expectedFileName": scene.get("expectedFileName"),
        "incomingDir": manifest.get("incomingDir"),
        "worksheetUrl": manifest.get("worksheetUrl") or _worksheet_url(project_id),
        "automationPlanUrl": manifest.get("automationPlanUrl") or _automation_plan_url(project_id),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        "automationStatus": automation_status,
        "automationReplay": _automation_replay_summary(replay_request),
        **result,
    })


@grok_bp.route("/api/grok-handoff/<project_id>/background-automation", methods=["POST"])
def grok_handoff_background_automation_route(project_id: str):
    """Start the last approved Grok automation request in a background thread."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    if data.get("operatorApproved") is not True or data.get("browserAutomationApproved") is not True:
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true and browserAutomationApproved=true are required before starting background browser control",
        }), 403

    scene, replay_data, download_dir, error = _prepare_background_automation_request(
        handoff_dir,
        manifest,
        project_id,
        data,
    )
    if error:
        status_code = 400 if scene is not None else 409
        return jsonify({"ok": False, "error": error}), status_code
    assert scene is not None
    assert replay_data is not None

    replay_request = _automation_replay_request(scene, replay_data, download_dir)
    project_key = str(manifest.get("projectId") or project_id)
    job_id = f"grok-bg-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{threading.get_ident()}"
    created_at = datetime.now().isoformat(timespec="seconds")
    initial_status = _automation_job_status(
        project_id=project_key,
        job_id=job_id,
        scene=scene,
        status="queued",
        detail="Background Grok automation queued; browser/login wait will continue without holding the dashboard request.",
        download_dir=download_dir,
        replay_request=replay_request,
        created_at=created_at,
    )

    superseded_job = None
    supersede_requested = data.get("supersedeActiveJobApproved") is True
    with _background_automation_lock:
        active_thread = _background_automation_threads.get(project_key)
        if active_thread and active_thread.is_alive():
            stored_request = _read_automation_request(handoff_dir)
            existing = _automation_job_summary(_read_automation_job_status(handoff_dir), project_key, stored_request) or {}
            if not supersede_requested:
                return jsonify({
                    "ok": True,
                    "alreadyRunning": True,
                    "projectId": project_key,
                    "sceneId": existing.get("sceneId") or scene.get("sceneId"),
                    "expectedFileName": existing.get("expectedFileName") or scene.get("expectedFileName"),
                    "incomingDir": manifest.get("incomingDir"),
                    "worksheetUrl": manifest.get("worksheetUrl") or _worksheet_url(project_id),
                    "automationPlanUrl": manifest.get("automationPlanUrl") or _automation_plan_url(project_id),
                    "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
                    "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
                    "automationReplay": existing.get("automationReplay") or _automation_replay_summary(stored_request),
                    "automationJob": existing,
                })
            cancel_request = _write_background_cancel_request(
                handoff_dir,
                str(existing.get("jobId") or ""),
                "Superseded by operator-approved isolated Grok login profile restart.",
            )
            superseded_job = {
                "previousJob": existing,
                "cancelRequest": cancel_request,
            }
        else:
            active_thread = None

    if active_thread and active_thread.is_alive() and supersede_requested:
        active_thread.join(timeout=8.0)
        with _background_automation_lock:
            if active_thread.is_alive() and _background_automation_threads.get(project_key) is active_thread:
                stored_request = _read_automation_request(handoff_dir)
                existing = _automation_job_summary(_read_automation_job_status(handoff_dir), project_key, stored_request) or {}
                return jsonify({
                    "ok": False,
                    "projectId": project_key,
                    "sceneId": existing.get("sceneId") or scene.get("sceneId"),
                    "expectedFileName": existing.get("expectedFileName") or scene.get("expectedFileName"),
                    "error": "Previous Grok background job has not acknowledged the supersede cancel request yet.",
                    "cancelPending": True,
                    "supersededJob": superseded_job,
                    "automationJob": existing,
                    "operatorNextAction": "Wait a few seconds, then press isolated profile restart again. Do not close the browser tab.",
                }), 409
            if _background_automation_threads.get(project_key) is active_thread:
                _background_automation_threads.pop(project_key, None)

    with _background_automation_lock:
        active_thread = _background_automation_threads.get(project_key)
        if active_thread and active_thread.is_alive():
            stored_request = _read_automation_request(handoff_dir)
            existing = _automation_job_summary(_read_automation_job_status(handoff_dir), project_key, stored_request) or {}
            return jsonify({
                "ok": True,
                "alreadyRunning": True,
                "projectId": project_key,
                "sceneId": existing.get("sceneId") or scene.get("sceneId"),
                "expectedFileName": existing.get("expectedFileName") or scene.get("expectedFileName"),
                "incomingDir": manifest.get("incomingDir"),
                "worksheetUrl": manifest.get("worksheetUrl") or _worksheet_url(project_id),
                "automationPlanUrl": manifest.get("automationPlanUrl") or _automation_plan_url(project_id),
                "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
                "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
                "automationReplay": existing.get("automationReplay") or _automation_replay_summary(stored_request),
                "automationJob": existing,
            })
        _write_automation_request(handoff_dir, replay_request)
        _write_automation_job_status(handoff_dir, initial_status)
        thread = threading.Thread(
            target=_run_background_automation_job,
            args=(
                job_id,
                project_key,
                handoff_dir,
                manifest,
                scene,
                replay_data,
                download_dir,
                replay_request,
                created_at,
            ),
            daemon=True,
            name=f"grok-bg-{project_key}",
        )
        _background_automation_threads[project_key] = thread
        thread.start()

    return jsonify({
        "ok": True,
        "projectId": project_key,
        "sceneId": scene.get("sceneId"),
        "expectedFileName": scene.get("expectedFileName"),
        "incomingDir": manifest.get("incomingDir"),
        "worksheetUrl": manifest.get("worksheetUrl") or _worksheet_url(project_id),
        "automationPlanUrl": manifest.get("automationPlanUrl") or _automation_plan_url(project_id),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        "automationReplay": _automation_replay_summary(replay_request),
        "automationJob": _automation_job_summary(initial_status, project_key, replay_request),
        **({"supersededJob": superseded_job} if superseded_job else {}),
    })


@grok_bp.route("/api/grok-handoff/<project_id>/import-downloads", methods=["POST"])
def grok_handoff_import_downloads_route(project_id: str):
    """Copy operator-approved Grok MP4 downloads into the handoff incoming folder."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    if data.get("operatorApproved") is not True:
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true is required before reading a local download folder",
        }), 403
    download_dirs, error = _download_dirs_from_request(data)
    if error or not download_dirs:
        return jsonify({"ok": False, "error": error}), 400
    download_dir = download_dirs[0]
    exact_file_value = data.get("downloadFilePath") or data.get("downloadFileName")
    exact_file, exact_file_error = _download_file_from_request(exact_file_value, download_dir)
    if exact_file_error:
        return jsonify({"ok": False, "error": exact_file_error}), 400
    scene_id_filter = str(data.get("sceneId") or "").strip()
    scene_mapping_mode = _normalize_scene_mapping_mode(data.get("sceneMappingMode") or data.get("scene_mapping_mode"))
    scene_grouped_take_size = (
        _scene_grouped_take_size_from_request(data, manifest, default=2)
        if scene_mapping_mode
        else 0
    )
    scene_grouped_take_offset = _bounded_int(
        data.get("sceneGroupedTakeOffset") or data.get("scene_grouped_take_offset"),
        default=0,
        minimum=0,
        maximum=500,
    )
    if exact_file is not None:
        if data.get("extensionApproved") is not True:
            return jsonify({
                "ok": False,
                "error": "extensionApproved=true is required before importing an exact completed Chrome download",
            }), 403
        if not scene_id_filter:
            return jsonify({"ok": False, "error": "sceneId is required with downloadFilePath"}), 400
        result = _import_exact_download_file(
            handoff_dir,
            manifest,
            download_dir,
            exact_file,
            scene_id_filter,
            overwrite=bool(data.get("overwrite")),
            preserve_candidates=data.get("preserveCandidates") is True,
        )
    else:
        result = _import_downloads(
            handoff_dir,
            manifest,
            download_dir,
            allow_newest_fallback=bool(data.get("allowNewestFallback")),
            overwrite=bool(data.get("overwrite")),
            since_handoff=data.get("sinceHandoff", True) is not False,
            scene_id_filter=scene_id_filter or None,
            preserve_candidates=data.get("preserveCandidates") is True,
            scene_mapping_mode=scene_mapping_mode,
            scene_grouped_take_size=scene_grouped_take_size,
            scene_grouped_take_offset=scene_grouped_take_offset,
        )
    _write_review_packet(handoff_dir, manifest)
    return jsonify({
        "ok": True,
        "projectId": manifest.get("projectId") or project_id,
        "downloadDir": str(download_dir),
        "incomingDir": manifest.get("incomingDir"),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        **result,
    })


@grok_bp.route("/api/grok-handoff/<project_id>/manual-download-watch", methods=["GET", "POST"])
def grok_handoff_manual_download_watch_route(project_id: str):
    """Run a nonblocking Grok app/web Downloads watcher without browser control."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    project_key = str(manifest.get("projectId") or project_id)
    if flask_request.method == "GET":
        return jsonify({
            "ok": True,
            "projectId": project_key,
            "incomingDir": manifest.get("incomingDir"),
            "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
            "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
            "manualDownloadWatchJob": _manual_download_watch_summary(
                _read_manual_download_watch_status(handoff_dir),
                project_key,
            ),
        })

    data = flask_request.get_json(silent=True) or {}
    if data.get("operatorApproved") is not True:
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true is required before watching a local download folder",
        }), 403
    download_dirs, error = _download_dirs_from_request(data)
    if error or not download_dirs:
        return jsonify({"ok": False, "error": error}), 400
    download_dir = download_dirs[0]

    watch_all_scenes = data.get("watchAllScenes") is True
    scene_queue = _scene_queue_status(handoff_dir, manifest)
    requested_scene_id = str(data.get("sceneId") or "").strip()
    if not requested_scene_id and not watch_all_scenes:
        requested_scene_id = str(scene_queue.get("nextMissingSceneId") or "").strip()
    scene = None if watch_all_scenes else _select_grok_scene(manifest, requested_scene_id)
    if not watch_all_scenes and scene is None:
        return jsonify({"ok": False, "error": "sceneId is required or no Grok scene is available"}), 400

    timeout_seconds = _bounded_float(data.get("timeoutSeconds"), default=900.0, minimum=0.5, maximum=7200.0)
    poll_interval_seconds = _bounded_float(data.get("pollIntervalSeconds"), default=2.0, minimum=0.5, maximum=30.0)
    allow_newest_fallback = data.get("allowNewestFallback", True) is not False
    since_handoff = data.get("sinceHandoff", True) is not False
    overwrite = data.get("overwrite") is True
    preserve_candidates = data.get("preserveCandidates", not watch_all_scenes) is not False
    if overwrite and "preserveCandidates" not in data:
        preserve_candidates = False
    stop_on_import = data.get("stopOnImport", not watch_all_scenes) is not False
    replace_existing = data.get("replaceExisting") is True
    scene_mapping_mode = _normalize_scene_mapping_mode(data.get("sceneMappingMode") or data.get("scene_mapping_mode"))
    scene_grouped_take_size = 0
    if watch_all_scenes and scene_mapping_mode:
        scene_grouped_take_size = _scene_grouped_take_size_from_request(data, manifest, default=2)
        preserve_candidates = True
        stop_on_import = False
    job_id = f"grok-manual-watch-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{threading.get_ident()}"
    created_at = datetime.now().isoformat(timespec="seconds")
    initial_status = _manual_download_watch_status(
        project_id=project_key,
        job_id=job_id,
        scene=scene,
        status="queued",
        detail="Manual Grok folder watch queued for an operator-owned local MP4; Codex automation must not press Grok Download/Save/Export or wait on a native Chrome prompt.",
        download_dir=download_dir,
        download_dirs=download_dirs,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        allow_newest_fallback=allow_newest_fallback,
        since_handoff=since_handoff,
        overwrite=overwrite,
        preserve_candidates=preserve_candidates,
        stop_on_import=stop_on_import,
        scene_mapping_mode=scene_mapping_mode,
        scene_grouped_take_size=scene_grouped_take_size,
        created_at=created_at,
    )

    with _manual_download_watch_lock:
        active_thread = _manual_download_watch_threads.get(project_key)
        if active_thread and active_thread.is_alive():
            if replace_existing:
                previous_status = _manual_download_watch_summary(
                    _read_manual_download_watch_status(handoff_dir),
                    project_key,
                ) or {}
                cancel_event = _manual_download_watch_cancel_events.get(project_key)
                if cancel_event is not None:
                    cancel_event.set()
                _write_manual_download_watch_status(handoff_dir, {
                    **previous_status,
                    "status": "superseded",
                    "detail": "Superseded by a newer Grok Downloads watch.",
                    "supersededAt": datetime.now().isoformat(timespec="seconds"),
                    "restartAvailable": False,
                    "stale": False,
                    "activeThread": True,
                })
            else:
                existing = _manual_download_watch_summary(
                    _read_manual_download_watch_status(handoff_dir),
                    project_key,
                ) or {}
                return jsonify({
                    "ok": True,
                    "alreadyRunning": True,
                    "replaceAvailable": True,
                    "projectId": project_key,
                    "incomingDir": manifest.get("incomingDir"),
                    "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
                    "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
                    "manualDownloadWatchJob": existing,
                })
        cancel_event = threading.Event()
        _write_manual_download_watch_status(handoff_dir, initial_status)
        thread = threading.Thread(
            target=_run_manual_download_watch_job,
            args=(
                job_id,
                project_key,
                handoff_dir,
                manifest,
                scene,
                download_dir,
                download_dirs,
                timeout_seconds,
                poll_interval_seconds,
                allow_newest_fallback,
                since_handoff,
                overwrite,
                preserve_candidates,
                stop_on_import,
                created_at,
                scene_mapping_mode,
                scene_grouped_take_size,
                cancel_event,
            ),
            daemon=True,
            name=f"grok-manual-watch-{project_key}",
        )
        _manual_download_watch_threads[project_key] = thread
        _manual_download_watch_cancel_events[project_key] = cancel_event
        thread.start()

    return jsonify({
        "ok": True,
        "replacedExisting": replace_existing and bool(active_thread and active_thread.is_alive()),
        "projectId": project_key,
        "sceneId": (scene or {}).get("sceneId") or "",
        "expectedFileName": (scene or {}).get("expectedFileName") or "",
        "downloadDir": str(download_dir),
        "downloadDirs": [str(item) for item in download_dirs],
        "incomingDir": manifest.get("incomingDir"),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        "manualDownloadWatchJob": _manual_download_watch_summary(initial_status, project_key),
    })


@grok_bp.route("/api/grok-handoff/<project_id>/upload-mp4", methods=["POST", "OPTIONS"])
def grok_handoff_upload_mp4_route(project_id: str):
    """Import a browser-selected Grok MP4 directly into one handoff scene."""
    if flask_request.method == "OPTIONS":
        return _bookmarklet_json_response({"ok": True})
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return _bookmarklet_json_response({"ok": False, "error": "Grok handoff manifest not found"}, 404)
    data = flask_request.get_json(silent=True) or {}
    if data.get("operatorApproved") is not True:
        return _bookmarklet_json_response({
            "ok": False,
            "error": "operatorApproved=true is required before importing a browser-selected Grok MP4",
        }, 403)
    scene_id = str(data.get("sceneId") or "").strip()
    if not scene_id:
        return _bookmarklet_json_response({"ok": False, "error": "sceneId is required"}, 400)
    file_bytes, file_name, error = _decode_uploaded_mp4(data)
    if error or file_bytes is None:
        return _bookmarklet_json_response({"ok": False, "error": error}, 400)
    result = _import_uploaded_grok_mp4(
        handoff_dir,
        manifest,
        scene_id,
        file_name,
        file_bytes,
        overwrite=bool(data.get("overwrite")),
        preserve_candidates=data.get("preserveCandidates", True) is not False,
    )
    direct_import_event = _record_upload_direct_import_event(
        handoff_dir,
        manifest,
        project_id,
        scene_id,
        file_name,
        data,
        result,
    )
    _write_review_packet(handoff_dir, manifest)
    return _bookmarklet_json_response({
        "ok": True,
        "projectId": manifest.get("projectId") or project_id,
        "sceneId": scene_id,
        "incomingDir": manifest.get("incomingDir"),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        **({"directImportProofEvent": direct_import_event} if direct_import_event else {}),
        **result,
    })


@grok_bp.route("/api/grok-handoff/<project_id>/upload-mp4-batch", methods=["POST"])
def grok_handoff_upload_mp4_batch_route(project_id: str):
    """Import multiple browser-selected Grok MP4 files into handoff scenes."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    if data.get("operatorApproved") is not True:
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true is required before importing browser-selected Grok MP4s",
        }), 403
    uploads = data.get("files") or data.get("uploads") or []
    if not isinstance(uploads, list) or not uploads:
        return jsonify({"ok": False, "error": "files must include at least one MP4 upload"}), 400
    if len(uploads) > 20:
        return jsonify({"ok": False, "error": "files is limited to 20 MP4 uploads per request"}), 400
    result = _import_uploaded_grok_mp4_batch(
        handoff_dir,
        manifest,
        uploads,
        overwrite=bool(data.get("overwrite")),
        preserve_candidates=data.get("preserveCandidates", True) is not False,
        scene_mapping_mode=data.get("sceneMappingMode") or data.get("scene_mapping_mode"),
    )
    _write_review_packet(handoff_dir, manifest)
    return jsonify({
        "ok": True,
        "projectId": manifest.get("projectId") or project_id,
        "incomingDir": manifest.get("incomingDir"),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        **result,
    })


@grok_bp.route("/api/grok-handoff/<project_id>/watch-downloads", methods=["POST"])
def grok_handoff_watch_downloads_route(project_id: str):
    """Poll an operator-approved Downloads folder until Grok MP4s are ready."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    if data.get("operatorApproved") is not True:
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true is required before watching a local download folder",
        }), 403
    download_dirs, error = _download_dirs_from_request(data)
    if error or not download_dirs:
        return jsonify({"ok": False, "error": error}), 400
    download_dir = download_dirs[0]

    timeout_seconds = _bounded_float(data.get("timeoutSeconds"), default=45.0, minimum=0.0, maximum=120.0)
    poll_interval_seconds = _bounded_float(data.get("pollIntervalSeconds"), default=2.0, minimum=0.1, maximum=10.0)
    result = _watch_downloads(
        handoff_dir,
        manifest,
        download_dir,
        allow_newest_fallback=bool(data.get("allowNewestFallback")),
        overwrite=bool(data.get("overwrite")),
        since_handoff=data.get("sinceHandoff", True) is not False,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        download_dirs=download_dirs,
        scene_id_filter=str(data.get("sceneId") or "").strip() or None,
        preserve_candidates=data.get("preserveCandidates") is True,
        stop_on_import=data.get("stopOnImport") is True,
    )
    _write_review_packet(handoff_dir, manifest)
    return jsonify({
        "ok": True,
        "projectId": manifest.get("projectId") or project_id,
        "downloadDir": str(download_dir),
        "downloadDirs": [str(item) for item in download_dirs],
        "incomingDir": manifest.get("incomingDir"),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        "timeoutSeconds": timeout_seconds,
        "pollIntervalSeconds": poll_interval_seconds,
        **result,
    })


@grok_bp.route("/api/grok-handoff/<project_id>/operator-run", methods=["POST"])
def grok_handoff_operator_run_route(project_id: str):
    """Open the approved Grok handoff surfaces and watch Downloads until clips are ready."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    if data.get("operatorApproved") is not True:
        return jsonify({
            "ok": False,
            "error": "operatorApproved=true is required before opening Grok and watching a local download folder",
        }), 403
    download_dirs, error = _download_dirs_from_request(data)
    if error or not download_dirs:
        return jsonify({"ok": False, "error": error}), 400
    download_dir = download_dirs[0]

    open_targets = _normalize_open_targets(
        data.get("openTargets") or data.get("openTarget") or data.get("target"),
        default=("worksheet", "grok"),
    )
    open_result = _open_handoff_targets(project_id, manifest, open_targets, data.get("browserPreference"))
    timeout_seconds = _bounded_float(data.get("timeoutSeconds"), default=240.0, minimum=0.0, maximum=600.0)
    poll_interval_seconds = _bounded_float(data.get("pollIntervalSeconds"), default=2.0, minimum=0.1, maximum=10.0)
    result = _watch_downloads(
        handoff_dir,
        manifest,
        download_dir,
        allow_newest_fallback=data.get("allowNewestFallback", True) is not False,
        overwrite=bool(data.get("overwrite")),
        since_handoff=data.get("sinceHandoff", True) is not False,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        download_dirs=download_dirs,
        scene_id_filter=str(data.get("sceneId") or "").strip() or None,
        preserve_candidates=data.get("preserveCandidates") is True,
        stop_on_import=data.get("stopOnImport") is True,
    )
    _write_review_packet(handoff_dir, manifest)
    return jsonify({
        "ok": True,
        "projectId": manifest.get("projectId") or project_id,
        "automationMode": "operator-approved-open-watch-import-render",
        "downloadDir": str(download_dir),
        "downloadDirs": [str(item) for item in download_dirs],
        "incomingDir": manifest.get("incomingDir"),
        "reviewPacketUrl": manifest.get("reviewPacketUrl") or _review_packet_url(project_id),
        "reviewDecisionUrl": manifest.get("reviewDecisionUrl") or _review_decision_url(project_id),
        "timeoutSeconds": timeout_seconds,
        "pollIntervalSeconds": poll_interval_seconds,
        **open_result,
        **result,
    })


@grok_bp.route("/api/grok-handoff/<project_id>/worksheet", methods=["GET"])
def serve_grok_worksheet_route(project_id: str):
    """Serve the local operator worksheet for prompt copy/open/save workflow."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    worksheet_path = handoff_dir / "operator-sheet.html"
    if not worksheet_path.exists():
        worksheet_path = _write_operator_worksheet(handoff_dir, manifest)
    return send_from_directory(str(worksheet_path.parent), worksheet_path.name, mimetype="text/html")


@grok_bp.route("/api/grok-handoff/<project_id>/production-queue", methods=["GET"])
def serve_grok_production_queue_route(project_id: str):
    """Serve a compact scene-order queue for producing Grok MP4s."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    _, queue_path = _ensure_production_queue(handoff_dir, manifest, str(manifest.get("projectId") or project_id))
    return send_from_directory(str(queue_path.parent), queue_path.name, mimetype="text/html")


@grok_bp.route("/api/grok-handoff/<project_id>/review-packet", methods=["GET"])
def serve_grok_review_packet_route(project_id: str):
    """Serve the post-import Grok clip review packet with video previews."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    review_packet_path = _write_review_packet(handoff_dir, manifest)
    manifest["reviewPacketPath"] = str(review_packet_path)
    manifest["reviewPacketUrl"] = manifest.get("reviewPacketUrl") or _review_packet_url(project_id)
    _write_manifest(handoff_dir, manifest)
    return send_from_directory(str(review_packet_path.parent), review_packet_path.name, mimetype="text/html")


@grok_bp.route("/api/grok-handoff/<project_id>/review-decision", methods=["POST"])
def grok_handoff_review_decision_route(project_id: str):
    """Persist an operator accept/reject decision from the review packet."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    data = flask_request.get_json(silent=True) or {}
    scene_id = str(data.get("sceneId") or "").strip()
    scene_ids = {
        str(scene.get("sceneId") or f"scene-{index + 1:02d}")
        for index, scene in enumerate(manifest.get("scenes") or [])
    }
    if not scene_id or scene_id not in scene_ids:
        return jsonify({"ok": False, "error": "sceneId is not part of this Grok handoff"}), 400
    if not isinstance(data.get("accepted"), bool):
        return jsonify({"ok": False, "error": "accepted must be true or false"}), 400
    scenes = [scene for scene in manifest.get("scenes") or [] if isinstance(scene, dict)]
    scene = next((item for item in scenes if str(item.get("sceneId") or "") == scene_id), {})
    selected_file_name = Path(str(data.get("selectedFileName") or "")).name
    selected_asset: dict | None = None
    selected_source_provenance: dict = {}
    if selected_file_name:
        assets = _match_downloaded_assets(handoff_dir, manifest)
        scene_asset = next((item for item in assets if str(item.get("sceneId") or "") == scene_id), None)
        candidate_pool = []
        if isinstance(scene_asset, dict):
            if scene_asset.get("status") == "ready":
                candidate_pool.append(scene_asset)
            candidate_pool.extend(
                item for item in scene_asset.get("candidateAssets") or []
                if isinstance(item, dict)
            )
        selected_asset = next((item for item in candidate_pool if item.get("fileName") == selected_file_name), None)
        if selected_asset is None:
            return jsonify({
                "ok": False,
                "error": "selectedFileName is not an imported Grok candidate for this scene",
            }), 400
    if data.get("accepted") is True and manifest.get("qualityGateRequired") is True:
        assets = _match_downloaded_assets(handoff_dir, manifest)
        if selected_asset is None:
            selected_asset = next((item for item in assets if str(item.get("sceneId") or "") == scene_id), None)
        if not selected_asset or selected_asset.get("status") != "ready":
            return jsonify({
                "ok": False,
                "error": "accepted=true requires an imported MP4 asset for this scene",
            }), 400
        probe = selected_asset.get("clipProbe") if isinstance(selected_asset.get("clipProbe"), dict) else {}
        if probe and probe.get("ok") is False:
            return jsonify({
                "ok": False,
                "error": "accepted=true requires passing clipProbe technical evidence",
                "clipProbe": probe,
            }), 400
        import_preflight = (
            selected_asset.get("importPreflight")
            if isinstance(selected_asset.get("importPreflight"), dict)
            else {}
        )
        if import_preflight and import_preflight.get("readyForReview") is False:
            return jsonify({
                "ok": False,
                "error": "accepted=true requires fresh usable Grok MP4 import preflight",
                "importPreflight": import_preflight,
            }), 400
        selected_source_provenance = (
            selected_asset.get("sourceProvenance")
            if isinstance(selected_asset.get("sourceProvenance"), dict)
            else {}
        )
        if manifest.get("grokMainSourceRequired") is True and selected_source_provenance.get("acceptAsGrokMainSource") is False:
            return jsonify({
                "ok": False,
                "error": "accepted=true for Grok-main requires browser-native/direct-imported or operator-uploaded Grok MP4 proof; visible-video/currentSrc fallback is proof-only",
                "sourceProvenance": selected_source_provenance,
            }), 400
    if data.get("accepted") is True and not all(
        data.get(key) is True
        for key in ("firstTwoSecondHook", "artifactFree", "continuityOk", "captionSafe")
    ):
        return jsonify({
            "ok": False,
            "error": "accepted=true requires firstTwoSecondHook=true, artifactFree=true, continuityOk=true, and captionSafe=true",
        }), 400

    def _clean_text(key: str, limit: int = 1200) -> str:
        return str(data.get(key) or "").strip()[:limit]

    source_rationale = _clean_text("sourceRationale")
    quality_review_note = _clean_text("qualityReviewNote")
    caption_layout_review_note = _clean_text("captionLayoutReviewNote")
    selected_candidate_summary = _clean_text("selectedCandidateSummary")
    single_candidate_justification = _clean_text("singleCandidateJustification")
    visual_quality_verdict = _clean_text("visualQualityVerdict", 80)
    shot_lock_evidence_note = _clean_text("shotLockEvidenceNote")
    scene_assembly_role_note = _clean_text("sceneAssemblyRoleNote")
    continuity_note = _clean_text("continuityNote")
    hook_note = _clean_text("hookNote")
    layout_variant_note = _clean_text("layoutVariantNote")
    thumbnail_review_note = _clean_text("thumbnailReviewNote")
    audio_mix_review_note = _clean_text("audioMixReviewNote")
    platform_comparison_note = _clean_text("platformComparisonNote")
    source_provenance_confirmed = data.get("sourceProvenanceConfirmed") is True
    source_provenance_note = _clean_text("sourceProvenanceNote")
    if data.get("accepted") is True and (len(source_rationale) < 24 or len(quality_review_note) < 24):
        return jsonify({
            "ok": False,
            "error": "accepted=true requires sourceRationale and qualityReviewNote with concrete manual selection evidence",
        }), 400
    if data.get("accepted") is True and manifest.get("grokMainSourceRequired") is True:
        curation_assets = _match_downloaded_assets(handoff_dir, manifest)
        scene_asset = next((item for item in curation_assets if str(item.get("sceneId") or "") == scene_id), None)
        candidate_count = _grok_asset_candidate_count(scene_asset)
        if candidate_count < 2:
            return jsonify({
                "ok": False,
                "error": "accepted=true for Grok-main requires at least two imported Grok MP4 take candidates before approval",
                "candidateCount": candidate_count,
            }), 400
        if candidate_count >= 2 and not selected_file_name:
            candidate_file_names = [
                str(item.get("fileName") or "")
                for item in (
                    scene_asset.get("candidateAssets")
                    if isinstance(scene_asset, dict) and isinstance(scene_asset.get("candidateAssets"), list)
                    else []
                )
                if isinstance(item, dict) and str(item.get("fileName") or "").strip()
            ]
            return jsonify({
                "ok": False,
                "error": "accepted=true for Grok-main requires selectedFileName so the operator explicitly chooses one imported take",
                "candidateCount": candidate_count,
                "candidateFileNames": candidate_file_names,
            }), 400
        if candidate_count >= 2 and len(selected_candidate_summary) < 24:
            return jsonify({
                "ok": False,
                "error": "accepted=true for Grok-main requires selectedCandidateSummary comparing the imported candidates",
                "candidateCount": candidate_count,
            }), 400
        detailed_missing = []
        if visual_quality_verdict != "pass":
            detailed_missing.append("visualQualityVerdict=pass")
        if data.get("shotLockMatch") is not True:
            detailed_missing.append("shotLockMatch=true")
        if data.get("sceneAssemblyOk") is not True:
            detailed_missing.append("sceneAssemblyOk=true")
        if _grok_source_provenance_confirmation_required(selected_source_provenance):
            if source_provenance_confirmed is not True:
                detailed_missing.append("sourceProvenanceConfirmed=true")
            if len(source_provenance_note) < 24:
                detailed_missing.append("sourceProvenanceNote")
        for key, value in (
            ("captionLayoutReviewNote", caption_layout_review_note),
            ("shotLockEvidenceNote", shot_lock_evidence_note),
            ("sceneAssemblyRoleNote", scene_assembly_role_note),
            ("continuityNote", continuity_note),
            ("hookNote", hook_note),
            ("layoutVariantNote", layout_variant_note),
            ("thumbnailReviewNote", thumbnail_review_note),
            ("audioMixReviewNote", audio_mix_review_note),
            ("platformComparisonNote", platform_comparison_note),
        ):
            if len(value) < 24:
                detailed_missing.append(key)
        if detailed_missing:
            return jsonify({
                "ok": False,
                "error": "accepted=true for Grok-main requires explicit shot-lock/scene-assembly/visual/layout/audio/platform quality evidence",
                "missingFields": detailed_missing,
                "sourceProvenance": selected_source_provenance,
            }), 400
    if caption_layout_review_note and caption_layout_review_note not in quality_review_note:
        quality_review_note = f"{quality_review_note} Caption/layout review: {caption_layout_review_note}".strip()

    decision = {
        "sceneId": scene_id,
        "accepted": data.get("accepted") is True,
        "firstTwoSecondHook": data.get("firstTwoSecondHook") is True,
        "artifactFree": data.get("artifactFree") is True,
        "continuityOk": data.get("continuityOk") is True,
        "captionSafe": data.get("captionSafe") is True,
        "shotLockMatch": data.get("shotLockMatch") is True,
        "sceneAssemblyOk": data.get("sceneAssemblyOk") is True,
        "sourceRationale": source_rationale,
        "qualityReviewNote": quality_review_note,
        "captionLayoutReviewNote": caption_layout_review_note,
        "visualQualityVerdict": visual_quality_verdict or ("needs-retry" if data.get("accepted") is False else ""),
        "shotLockEvidenceNote": shot_lock_evidence_note,
        "sceneAssemblyRoleNote": scene_assembly_role_note,
        "continuityNote": continuity_note,
        "hookNote": hook_note,
        "layoutVariantKey": _clean_text("layoutVariantKey", 120),
        "layoutVariantLabel": _clean_text("layoutVariantLabel", 160),
        "layoutVariantNote": layout_variant_note,
        "thumbnailReviewNote": thumbnail_review_note,
        "audioMixReviewNote": audio_mix_review_note,
        "platformComparisonNote": platform_comparison_note,
        "sourceProvenanceConfirmed": source_provenance_confirmed,
        "sourceProvenanceNote": source_provenance_note,
        "sourceProvenanceStatus": str(selected_source_provenance.get("status") or "").strip(),
        "selectedCandidateSummary": selected_candidate_summary,
        "singleCandidateJustification": single_candidate_justification,
        "operatorNote": _clean_text("operatorNote"),
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    if selected_asset:
        decision["selectedCandidate"] = {
            "fileName": selected_asset.get("fileName"),
            "sourcePath": selected_asset.get("sourcePath"),
            "sizeBytes": selected_asset.get("sizeBytes"),
            "clipProbe": selected_asset.get("clipProbe") if isinstance(selected_asset.get("clipProbe"), dict) else {},
            "importPreflight": (
                selected_asset.get("importPreflight")
                if isinstance(selected_asset.get("importPreflight"), dict)
                else {}
            ),
            "sourceProvenance": (
                selected_asset.get("sourceProvenance")
                if isinstance(selected_asset.get("sourceProvenance"), dict)
                else {}
            ),
        }
    if selected_file_name:
        decision["selectedFileName"] = selected_file_name
    elif selected_asset and selected_asset.get("fileName"):
        decision["selectedFileName"] = selected_asset.get("fileName")
    if decision["accepted"] is False:
        previous = _scene_review_decision(manifest, scene_id)
        decision["retryAttempt"] = _scene_retry_attempt(previous) + 1 if previous.get("accepted") is False else 2
        shot_bible = manifest.get("shotBible") if isinstance(manifest.get("shotBible"), dict) else {}
        decision["nextRetryPrompt"] = _scene_retry_prompt(scene, shot_bible, decision)
    manifest.setdefault("reviewDecisions", {})[scene_id] = decision
    review_packet_path = _write_review_packet(handoff_dir, manifest)
    manifest["reviewPacketPath"] = str(review_packet_path)
    manifest["reviewPacketUrl"] = manifest.get("reviewPacketUrl") or _review_packet_url(project_id)
    manifest["reviewDecisionUrl"] = manifest.get("reviewDecisionUrl") or _review_decision_url(project_id)
    _write_manifest(handoff_dir, manifest)
    render_payload = _render_payload_from_manifest(handoff_dir, manifest)
    return jsonify({
        "ok": True,
        "projectId": manifest.get("projectId") or project_id,
        "reviewPacketUrl": manifest["reviewPacketUrl"],
        "reviewDecisionUrl": manifest["reviewDecisionUrl"],
        "reviewDecision": decision,
        "renderPayload": render_payload,
    })


@grok_bp.route("/api/grok-handoff/<project_id>/asset/<path:file_name>", methods=["GET"])
def serve_grok_asset_route(project_id: str, file_name: str):
    """Serve downloaded Grok MP4 previews from the handoff incoming folder."""
    handoff_dir, manifest = _load_manifest(project_id)
    if not handoff_dir or not manifest:
        return jsonify({"ok": False, "error": "Grok handoff manifest not found"}), 404
    incoming_dir = (handoff_dir / "incoming").resolve()
    requested = (incoming_dir / Path(file_name).name).resolve()
    if requested.parent != incoming_dir or requested.suffix.lower() != ".mp4" or not requested.exists():
        return jsonify({"ok": False, "error": "asset not found"}), 404
    return send_from_directory(str(incoming_dir), requested.name, mimetype="video/mp4")
