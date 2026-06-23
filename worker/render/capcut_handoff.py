"""Build editable CapCut handoff drafts from existing render manifests."""

from __future__ import annotations

import argparse
import json
import os
import struct
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from worker.bridge.vectcut_bridge import (
    add_audio_clip as vb_add_audio_clip,
    add_bgm as vb_add_bgm,
    add_effect as vb_add_effect,
    add_image as vb_add_image,
    add_narration as vb_add_narration,
    add_subtitle as vb_add_subtitle,
    add_video as vb_add_video,
    add_video_keyframes as vb_add_video_keyframes,
    create_capcut_draft,
    save_draft_to_capcut,
)
from worker.render.golden_reference_gate import (
    evaluate_golden_reference_compliance,
    write_golden_reference_preflight_report,
)


DEFAULT_CAPCUT_DRAFT_DIR = (
    Path.home()
    / "AppData"
    / "Local"
    / "CapCut"
    / "User Data"
    / "Projects"
    / "com.lveditor.draft"
)

DEFAULT_CAPCUT_EXE = Path.home() / "AppData" / "Local" / "CapCut" / "Apps" / "CapCut.exe"

CAPCUT_REFERENCE_BASIS = [
    "CapCut keyframe animation: keyframe motion, speed curves, and easing",
    "CapCut auto caption generator: caption timeline, sync, and style remain editable",
    "YouTube Shorts timeline: video, text, stickers, music, voiceover, and TTS",
    "TikTok Creative Center Top Ads: compare against high-performing vertical examples",
    "Microsoft timing/easing: restrained fast-out-slow-in motion",
    "CapCut effects/templates: native effect, transition, light leak, glitch, HUD, and filter layers",
    "CapCut sound effects: SFX must match motion, transition, scene change, tone, and pacing",
    "VectCutAPI CapCut draft automation creates draft_content.json tracks",
]

CALLOUT_MIN_DURATION_BY_ROLE = {
    "hook-question": 1.05,
    "mechanism-focus": 0.95,
    "risk-focus": 1.05,
    "warning-no": 1.35,
    "safe-resolution": 1.25,
}

CALLOUT_MIN_DURATION_BY_TYPE = {
    "keyword-emphasis": 1.05,
    "pointer-line": 0.95,
    "focus-pulse": 1.05,
    "warning-x": 1.35,
    "safe-check": 1.25,
}

GENERATED_SFX_BEATS_ALLOWED = False
GENERATED_VISUAL_OVERLAYS_ALLOWED = False
GENERATED_NATIVE_EFFECTS_ALLOWED = False

SFX_BEATS_BY_ROLE = {
    "warning-no": [
        {"beat": "hit", "path": "assets/sfx/error-02.mp3", "offsetSec": 0.00, "durationSec": 0.42, "volume": 0.76},
    ],
    "safe-resolution": [
        {"beat": "hit", "path": "assets/sfx/chime-03.mp3", "offsetSec": 0.00, "durationSec": 0.42, "volume": 0.68},
    ],
}

OVERLAY_ROLE_ASSET = {
    "warning-no": "warning_edge",
    "safe-resolution": "safe_edge",
}

CAPCUT_EFFECT_PRESETS_BY_ROLE = {
}


@dataclass(slots=True)
class CapCutHandoffResult:
    manifest_path: str
    draft_id: str
    draft_path: str
    draft_content_path: str
    draft_audit_path: str
    preflight_path: str
    preflight_status: str
    render_allowed: bool
    track_counts: dict[str, int]
    keyframed_elements: int
    sfx_tracks: int
    effect_tracks: int


def build_capcut_handoff(
    manifest_path: Path | str,
    *,
    project_root: Path | str = Path("."),
    capcut_draft_dir: Path | str | None = None,
    capcut_exe: Path | str | None = None,
    write_manifest: bool = True,
    preflight_path: Path | str | None = None,
) -> CapCutHandoffResult:
    """Create a CapCut draft from a render manifest and inject handoff evidence."""

    root = Path(project_root).resolve()
    manifest_file = _resolve_path(root, manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    render_dir = manifest_file.parent
    capcut_root = Path(capcut_draft_dir or os.environ.get("CAPCUT_DRAFT_DIR") or DEFAULT_CAPCUT_DRAFT_DIR)
    capcut_app = Path(capcut_exe or DEFAULT_CAPCUT_EXE)

    scenes = manifest.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("manifest.scenes must be a non-empty list")
    timing_by_scene = _scene_timing_map(manifest)

    script, draft_id = create_capcut_draft(1080, 1920)
    operations: list[dict[str, Any]] = []
    internal_scenes: list[dict[str, Any]] = []
    keyframed_elements = 0
    total_motion_keyframes = 0
    transition_count = 0
    editorial_motion_profiles: list[dict[str, Any]] = []
    caption_animation_profiles: list[dict[str, Any]] = []
    sfx_tracks = 0

    for idx, scene in enumerate(scenes, start=1):
        scene_id = str(scene.get("sceneId") or f"scene-{idx:03d}")
        timing = timing_by_scene.get(scene_id) or _fallback_timing(scenes, idx - 1)
        start = float(timing["sceneStartSec"])
        end = float(timing["sceneEndSec"])
        duration = max(0.1, end - start)
        scene_num = _scene_num(scene_id, idx)

        source_path = _resolve_path(root, scene.get("sourcePath"))
        _require_file(source_path, f"{scene_id} sourcePath")
        source_uri = source_path.as_uri()
        video_track = f"source_{scene_id.replace('-', '_')}"
        motion_profile = _scene_motion_profile(scene, idx=idx, start=start, end=end)
        transition_name = _transition_for_scene(idx, scene)
        transition_duration = 0.18 if transition_name else 0.0
        video_ok = vb_add_video(
            draft_id,
            source_uri,
            start,
            end,
            track_name=video_track,
            scale_x=float(motion_profile["initialScale"]),
            scale_y=float(motion_profile["initialScale"]),
            relative_index=0,
            transition=transition_name,
            transition_duration=transition_duration,
        )
        if transition_name:
            transition_count += 1
        operations.append(
            {
                "kind": "sourceVideo",
                "sceneId": scene_id,
                "ok": video_ok,
                "track": video_track,
                "transition": transition_name,
                "transitionDurationSec": transition_duration,
            }
        )
        if not video_ok:
            raise RuntimeError(f"failed to add CapCut source video for {scene_id}")

        keyframe_ok = vb_add_video_keyframes(
            draft_id,
            video_track,
            property_types=list(motion_profile["propertyTypes"]),
            times=list(motion_profile["times"]),
            values=list(motion_profile["values"]),
        )
        if keyframe_ok:
            keyframed_elements += 1
            total_motion_keyframes += int(motion_profile["keyframeCount"])
            editorial_motion_profiles.append(motion_profile)
        operations.append(
            {
                "kind": "sourceMotionProfile",
                "sceneId": scene_id,
                "ok": keyframe_ok,
                "track": video_track,
                "profile": motion_profile["profile"],
                "motionIntent": motion_profile["motionIntent"],
                "keyframeCount": motion_profile["keyframeCount"],
                "scaleDelta": motion_profile["scaleDelta"],
                "positionDelta": motion_profile["positionDelta"],
                "times": motion_profile["times"],
            }
        )
        if not keyframe_ok:
            raise RuntimeError(f"failed to add CapCut editorial motion keyframes for {scene_id}")

        caption_text = _caption_text(scene.get("subtitleText"))
        if caption_text:
            caption_start = float(timing.get("captionStartSec", start + 0.2))
            caption_end = float(timing.get("captionEndSec", end))
            caption_animation = _caption_animation_for_scene(scene, idx)
            caption_ok = vb_add_subtitle(
                draft_id,
                caption_text,
                caption_start,
                caption_end,
                scene_num,
                font_color="#FFFFFF",
                font_size=18.0 if idx == 1 else 15.0,
                transform_y=-0.62 if idx == 1 else -0.43,
                border_width=0.12,
                shadow_distance=4.0,
                intro_animation=caption_animation["introAnimation"],
                intro_duration=caption_animation["introDurationSec"],
                background_color="#111111",
                background_alpha=0.28,
            )
            caption_animation_profiles.append(
                {
                    "sceneId": scene_id,
                    "role": caption_animation["role"],
                    "introAnimation": caption_animation["introAnimation"],
                    "introDurationSec": caption_animation["introDurationSec"],
                    "captionStartSec": caption_start,
                    "captionEndSec": caption_end,
                }
            )
            operations.append(
                {
                    "kind": "caption",
                    "sceneId": scene_id,
                    "ok": caption_ok,
                    "introAnimation": caption_animation["introAnimation"],
                    "introDurationSec": caption_animation["introDurationSec"],
                }
            )

        tts_path = _tts_path_for_scene(root, render_dir, scene_id)
        _require_file(tts_path, f"{scene_id} TTS")
        tts_duration = float(timing.get("ttsDurationSec") or max(0.1, float(timing.get("voiceEndSec", end)) - float(timing.get("voiceStartSec", start))))
        voice_start = float(timing.get("voiceStartSec", start))
        tts_url = str(tts_path)
        tts_ok = vb_add_narration(draft_id, tts_url, tts_duration, voice_start, scene_num)
        operations.append({"kind": "tts", "sceneId": scene_id, "ok": tts_ok, "track": f"audio_{scene_num}"})

        internal_scenes.append(
            {
                "scene_num": scene_num,
                "sceneId": scene_id,
                "narration": scene.get("narrationText") or "",
                "display_text": caption_text,
                "_tts_path": str(tts_path),
                "_tts_url": tts_url,
                "_tts_duration": tts_duration,
                "_image_url": source_uri,
                "_is_video": True,
            }
        )

    total_duration = _timeline_duration(manifest, scenes)
    bgm_path = _resolve_path(root, manifest.get("openingAudioContinuity", {}).get("audioBed", {}).get("bgmSourcePath"))
    _require_file(bgm_path, "BGM source")
    bgm_ok = vb_add_bgm(draft_id, str(bgm_path), total_duration, volume=0.12)
    operations.append({"kind": "bgm", "ok": bgm_ok, "track": "bgm"})

    sfx_tracks = _add_external_sfx(root, draft_id, manifest, operations)
    effect_tracks = _add_capcut_effect_layers(draft_id, manifest, operations)
    edit_elements, overlay_urls = _add_external_edit_visual_layers(root, draft_id, manifest, operations)
    if overlay_urls and internal_scenes:
        internal_scenes[0].setdefault("_sub_images", [])
        for overlay_url in overlay_urls:
            internal_scenes[0]["_sub_images"].append({"url": overlay_url, "is_video": False})

    if keyframed_elements < 2:
        raise RuntimeError("CapCut draft did not receive at least two keyframed elements")

    draft_path = save_draft_to_capcut(
        draft_id=draft_id,
        script=script,
        scenes=internal_scenes,
        capcut_draft_dir=capcut_root,
        has_images=True,
        bgm_path=str(bgm_path),
        draft_display_name=f"Video Studio {manifest.get('projectId') or draft_id}",
    )
    if not draft_path:
        raise RuntimeError("save_draft_to_capcut returned no draft path")

    draft_dir = Path(draft_path)
    draft_content = draft_dir / "draft_content.json"
    _require_file(draft_content, "CapCut draft_content.json")
    draft_data = json.loads(draft_content.read_text(encoding="utf-8"))
    actual_motion_keyframes = _exported_video_keyframe_count(draft_data)
    if actual_motion_keyframes < total_motion_keyframes:
        raise RuntimeError(
            "CapCut draft missing exported video keyframes: "
            f"expected at least {total_motion_keyframes}, found {actual_motion_keyframes}"
        )

    audit_path = render_dir / "capcut-draft-audit.json"
    audit = _write_audit(
        audit_path,
        manifest_file=manifest_file,
        draft_id=draft_id,
        draft_dir=draft_dir,
        draft_content=draft_content,
        capcut_root=capcut_root,
        capcut_exe=capcut_app,
        operations=operations,
        keyframed_elements=keyframed_elements,
        planned_motion_keyframes=total_motion_keyframes,
        total_motion_keyframes=actual_motion_keyframes,
        transition_count=transition_count,
        editorial_motion_profiles=editorial_motion_profiles,
        caption_animation_profiles=caption_animation_profiles,
        sfx_tracks=sfx_tracks,
        effect_tracks=effect_tracks,
        visual_elements=edit_elements,
    )

    manifest.setdefault("postEditGoldenReference", {})["capcutHandoff"] = _handoff_contract(
        draft_dir=draft_dir,
        draft_content=draft_content,
        audit_path=audit_path,
        capcut_root=capcut_root,
        capcut_exe=capcut_app,
        keyframed_elements=keyframed_elements,
        total_motion_keyframes=actual_motion_keyframes,
        transition_count=transition_count,
        editorial_motion_profiles=editorial_motion_profiles,
        caption_animation_profiles=caption_animation_profiles,
        sfx_tracks=sfx_tracks,
        effect_tracks=effect_tracks,
        operations=operations,
    )

    if write_manifest:
        manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    preflight_file = Path(preflight_path) if preflight_path else render_dir / "golden-reference-preflight.json"
    report = evaluate_golden_reference_compliance(manifest, project_root=root)
    write_golden_reference_preflight_report(report, preflight_file)

    return CapCutHandoffResult(
        manifest_path=str(manifest_file),
        draft_id=draft_id,
        draft_path=str(draft_dir),
        draft_content_path=str(draft_content),
        draft_audit_path=str(audit_path),
        preflight_path=str(preflight_file),
        preflight_status=str(report.get("status")),
        render_allowed=bool(report.get("renderAllowed")),
        track_counts=audit["trackCounts"],
        keyframed_elements=keyframed_elements,
        sfx_tracks=sfx_tracks,
        effect_tracks=effect_tracks,
    )


def _add_external_edit_visual_layers(
    root: Path,
    draft_id: str,
    manifest: dict[str, Any],
    operations: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    if not GENERATED_VISUAL_OVERLAYS_ALLOWED:
        return 0, []
    plan = (
        manifest.get("postEditGoldenReference", {})
        .get("externalEditElements", {})
        .get("perScenePlan", [])
    )
    count = 0
    overlay_urls: list[str] = []
    for scene_idx, scene_plan in enumerate(plan, start=1):
        for element_idx, element in enumerate(scene_plan.get("elements") or [], start=1):
            start, end = _callout_window(element)
            overlay_path = _overlay_asset_for_element(root, element)
            if overlay_path is None:
                continue
            overlay_url = overlay_path.resolve().as_uri()
            ok = vb_add_image(
                draft_id,
                overlay_url,
                start,
                end,
                track_name=f"visual_cue_{scene_idx}_{element_idx}",
                scale_x=1.0,
                scale_y=1.0,
                transform_y=0.0,
                relative_index=30 + scene_idx,
                intro_animation="Fade_In",
                intro_animation_duration=0.12,
            )
            operations.append(
                {
                    "kind": "editElementVisualCue",
                    "sceneId": scene_plan.get("sceneId"),
                    "type": element.get("type"),
                    "semanticRole": element.get("semanticRole"),
                    "ok": ok,
                    "containsText": False,
                    "overlayPath": str(overlay_path),
                    "startSec": start,
                    "endSec": end,
                    "minHoldSec": round(end - start, 3),
                    "motionIntent": "non-text visual cue with pre-hit-hold-tail audio beat",
                }
            )
            if ok:
                count += 1
                overlay_urls.append(overlay_url)
    return count, overlay_urls


def _add_external_sfx(
    root: Path,
    draft_id: str,
    manifest: dict[str, Any],
    operations: list[dict[str, Any]],
) -> int:
    if not GENERATED_SFX_BEATS_ALLOWED:
        return 0
    plan = (
        manifest.get("postEditGoldenReference", {})
        .get("externalEditElements", {})
        .get("perScenePlan", [])
    )
    added = 0
    for scene_plan in plan:
        for element in scene_plan.get("elements") or []:
            role = str(element.get("semanticRole") or "")
            beats = _sfx_beats_for_element(element)
            if not beats:
                continue
            cue_start, cue_end = _callout_window(element)
            for beat in beats:
                sfx_path = _resolve_path(root, beat["path"])
                _require_file(sfx_path, f"SFX {role}:{beat['beat']}")
                start = max(0.0, cue_start + float(beat["offsetSec"]))
                duration = float(beat["durationSec"])
                track_name = f"sfx_{_track_slug(role)}_{beat['beat']}_{added + 1}"
                ok = vb_add_audio_clip(
                    draft_id,
                    str(sfx_path),
                    start,
                    duration,
                    track_name=track_name,
                    volume=float(beat["volume"]),
                )
                operations.append(
                    {
                        "kind": "sfxBeat",
                        "sceneId": scene_plan.get("sceneId"),
                        "semanticRole": role,
                        "beat": beat["beat"],
                        "ok": ok,
                        "track": track_name,
                        "path": str(sfx_path),
                        "startSec": start,
                        "durationSec": duration,
                        "cueStartSec": cue_start,
                        "cueEndSec": cue_end,
                        "volume": float(beat["volume"]),
                    }
                )
                if ok:
                    added += 1
    return added


def _add_capcut_effect_layers(
    draft_id: str,
    manifest: dict[str, Any],
    operations: list[dict[str, Any]],
) -> int:
    if not GENERATED_NATIVE_EFFECTS_ALLOWED:
        return 0
    plan = (
        manifest.get("postEditGoldenReference", {})
        .get("externalEditElements", {})
        .get("perScenePlan", [])
    )
    added = 0
    for scene_plan in plan:
        for element in scene_plan.get("elements") or []:
            role = str(element.get("semanticRole") or "")
            presets = CAPCUT_EFFECT_PRESETS_BY_ROLE.get(role) or []
            if not presets:
                continue
            cue_start, cue_end = _callout_window(element)
            for preset in presets:
                start = max(0.0, cue_start + float(preset["offsetSec"]))
                duration = float(preset["durationSec"])
                end = min(cue_end, start + duration)
                if end <= start:
                    continue
                track_name = f"effect_{_track_slug(role)}_{_track_slug(preset['family'])}_{added + 1}"
                ok = vb_add_effect(
                    draft_id,
                    str(preset["effectType"]),
                    start,
                    end,
                    track_name=track_name,
                    effect_category="scene",
                    params=list(preset.get("params") or []),
                )
                operations.append(
                    {
                        "kind": "capcutEffectLayer",
                        "sceneId": scene_plan.get("sceneId"),
                        "semanticRole": role,
                        "effectType": preset["effectType"],
                        "effectFamily": preset["family"],
                        "ok": ok,
                        "track": track_name,
                        "startSec": start,
                        "endSec": end,
                        "durationSec": round(end - start, 3),
                        "nativeCapCutEffect": True,
                        "visualBinding": "visible-overlay-and-audio-hit",
                        "bindingSourceType": element.get("type"),
                        "bindingPurpose": element.get("purpose"),
                    }
                )
                if ok:
                    added += 1
    return added


def _write_audit(
    audit_path: Path,
    *,
    manifest_file: Path,
    draft_id: str,
    draft_dir: Path,
    draft_content: Path,
    capcut_root: Path,
    capcut_exe: Path,
    operations: list[dict[str, Any]],
    keyframed_elements: int,
    planned_motion_keyframes: int,
    total_motion_keyframes: int,
    transition_count: int,
    editorial_motion_profiles: list[dict[str, Any]],
    caption_animation_profiles: list[dict[str, Any]],
    sfx_tracks: int,
    effect_tracks: int,
    visual_elements: int,
) -> dict[str, Any]:
    draft_data = json.loads(draft_content.read_text(encoding="utf-8"))
    track_counts = _track_counts(draft_data)
    audit = {
        "schema": "video-studio.capcut-draft-audit.v1",
        "manifestPath": str(manifest_file),
        "draftId": draft_id,
        "draftPath": str(draft_dir),
        "draftContentPath": str(draft_content),
        "capcutDraftRoot": str(capcut_root),
        "capcutDraftRootExists": capcut_root.exists(),
        "capcutExePath": str(capcut_exe),
        "capcutInstallVerified": capcut_exe.exists(),
        "tool": "VectCutAPI",
        "targetEditor": "CapCut desktop",
        "draftFormat": "draft_content.json",
        "trackCounts": track_counts,
        "keyframedElements": keyframed_elements,
        "plannedMotionKeyframes": planned_motion_keyframes,
        "totalMotionKeyframes": total_motion_keyframes,
        "actualVideoKeyframes": total_motion_keyframes,
        "transitionCount": transition_count,
        "editorialMotionProfiles": editorial_motion_profiles,
        "captionAnimationProfiles": caption_animation_profiles,
        "sfxTracks": sfx_tracks,
        "effectTracks": effect_tracks,
        "editElementTextLayers": 0,
        "editElementVisualLayers": visual_elements,
        "extraTextEditLayersAllowed": False,
        "operations": operations,
        "operatorActionRequired": "Open CapCut, review editable tracks/keyframes, then export manually.",
    }
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit


def _handoff_contract(
    *,
    draft_dir: Path,
    draft_content: Path,
    audit_path: Path,
    capcut_root: Path,
    capcut_exe: Path,
    keyframed_elements: int,
    total_motion_keyframes: int,
    transition_count: int,
    editorial_motion_profiles: list[dict[str, Any]],
    caption_animation_profiles: list[dict[str, Any]],
    sfx_tracks: int,
    effect_tracks: int,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    effect_ops = [op for op in operations if op.get("kind") == "capcutEffectLayer" and op.get("ok") is True]
    effect_families = sorted({str(op.get("effectFamily")) for op in effect_ops if op.get("effectFamily")})
    effect_types = sorted({str(op.get("effectType")) for op in effect_ops if op.get("effectType")})
    effect_roles = sorted({str(op.get("semanticRole")) for op in effect_ops if op.get("semanticRole")})
    return {
        "required": True,
        "draftRequired": True,
        "pipelineMode": "capcut-draft-first",
        "referenceBasis": CAPCUT_REFERENCE_BASIS,
        "capcutIsPrimaryEditSurface": True,
        "ffmpegPreviewOnly": True,
        "ffmpegOnlyAllowed": False,
        "manualExportRequired": True,
        "humanReviewBeforeUpload": True,
        "editableTextAndTiming": True,
        "motionDesignedEditElements": True,
        "automationSurface": {
            "tool": "VectCutAPI",
            "targetEditor": "CapCut desktop",
            "draftFormat": "draft_content.json",
            "localDraftRootExists": capcut_root.exists(),
            "capcutInstallVerified": capcut_exe.exists(),
            "finalExportByOperator": True,
            "ffmpegPreviewOnly": True,
        },
        "editModel": {
            "multitrackTimeline": True,
            "editableTextAndTiming": True,
            "editableCaptions": True,
            "editableAudioLevels": True,
            "editableMotionElements": True,
            "extraTextCalloutsAllowed": False,
            "editElementsUseNonTextVisuals": False,
            "nativeCapCutEffectsRequired": False,
            "generatedEffectLayersAllowed": False,
            "cleanEditorialMode": True,
        },
        "effectPass": {
            "required": True,
            "mode": "clean-editorial-no-canned-effects",
            "usesNativeCapCutEffects": False,
            "nativeEffectsDisabled": True,
            "generatedVisualEffectsDisabled": True,
            "forbidPngOnlyClaim": True,
            "manualPresetReviewRequired": True,
            "visualBindingRequired": True,
            "forbidUnanchoredEffects": True,
            "forbidPresetSpray": True,
            "cannedEffectsRejected": True,
            "effectTrackCount": effect_tracks,
            "minEffectTracks": 0,
            "maxEffectTracks": 0,
            "anchoredCueRoles": effect_roles,
            "requiredFamilies": effect_families,
            "candidateEffects": effect_types,
            "disallowedUnanchoredFamilies": [
                "atmosphere-light",
                "distortion",
                "scan-context",
                "impact-pulse",
            ],
            "referenceBasis": [
                "Generated CapCut stock effects are disabled by default because canned visual effects can make the edit look unrelated to the source screen.",
                "CapCut remains the editable timeline and operator export surface; source keyframes, captions, BGM, and clip timing carry the edit unless a human selects a preset.",
                "CapCut sound effects should match motion, transitions, scene changes, tone, and pacing; unrelated decorative hits are rejected.",
                "TikTok Creative Center Top Ads review requires creative triggers, curiosity, close-ups, and pacing to be evaluated externally.",
            ],
        },
        "motionDesign": {
            "usesKeyframes": True,
            "usesEasing": True,
            "usesSpeedCurvesOrEasing": True,
            "minKeyframedElements": keyframed_elements,
            "editorialMotionPass": _editorial_motion_pass_contract(
                editorial_motion_profiles=editorial_motion_profiles,
                caption_animation_profiles=caption_animation_profiles,
                transition_count=transition_count,
                total_motion_keyframes=total_motion_keyframes,
            ),
            "beatDesignedSfx": False,
            "sfxBeatsPerPrimaryCueMin": 0,
            "warningAndResolutionCueModel": "none-generated",
            "noRawDrawboxDrawtextFinal": True,
            "motionDurationMsMin": 83,
            "motionDurationMsMax": 400,
        },
        "roundTripStatus": "draft-created",
        "draftPath": str(draft_dir),
        "draftContentPath": str(draft_content),
        "draftAuditPath": str(audit_path),
        "mediaLinked": {
            "sourceVideoTracks": True,
            "ttsTracks": True,
            "bgmTrack": True,
            "sfxTracks": sfx_tracks > 0,
            "effectTracks": effect_tracks > 0,
            "captionTracks": True,
            "editElementTracks": False,
        },
        "topicSpecificCriteriaInGlobalGate": False,
    }


def _scene_motion_profile(scene: dict[str, Any], *, idx: int, start: float, end: float) -> dict[str, Any]:
    scene_id = str(scene.get("sceneId") or f"scene-{idx:03d}")
    role = _normalize_role(scene.get("referenceEditRole") or scene.get("captionPreset") or "")
    duration = max(0.4, end - start)
    peak = min(end - 0.16, start + max(0.42, min(0.90, duration * 0.38)))
    settle = max(peak + 0.10, end - max(0.12, min(0.32, duration * 0.08)))

    if "hook" in role:
        profile = "hook-size-normalized-push"
        motion_intent = "normalize the smaller opening subject closer to the later subject size before the curiosity push"
        scales = [1.280, 1.340, 1.310]
        xs = [0.000, 0.006, 0.003]
        ys = [-0.035, -0.055, -0.048]
    elif "mechanism" in role:
        profile = "mechanism-size-hold"
        motion_intent = "hold the already-large subject near the shared size band while adding only a restrained inspection drift"
        scales = [1.000, 1.060, 1.035]
        xs = [-0.010, 0.004, 0.006]
        ys = [-0.010, -0.022, -0.020]
    elif "evidence" in role or "risk" in role:
        profile = "evidence-size-match"
        motion_intent = "match the primary subject size to the mechanism shot and add a small tension push without changing scale class"
        scales = [1.130, 1.200, 1.165]
        xs = [0.006, -0.008, -0.006]
        ys = [-0.008, -0.030, -0.024]
    else:
        profile = "answer-size-stabilized-release"
        motion_intent = "keep the final primary subject in the same screen-size band and release tension with a small pullback"
        scales = [1.205, 1.155, 1.125]
        xs = [0.010, 0.000, -0.006]
        ys = [-0.026, -0.004, 0.004]

    times = [round(start, 3), round(peak, 3), round(settle, 3)]
    property_types: list[str] = []
    values: list[str] = []
    expanded_times: list[float] = []
    for time_value, scale, x, y in zip(times, scales, xs, ys):
        expanded_times.extend([time_value, time_value, time_value])
        property_types.extend(["uniform_scale", "position_x", "position_y"])
        values.extend([f"{scale:.3f}", f"{x:.3f}", f"{y:.3f}"])

    scale_delta = round(max(scales) - min(scales), 3)
    position_delta = round(max(max(xs) - min(xs), max(ys) - min(ys)), 3)
    return {
        "sceneId": scene_id,
        "role": role or "answer",
        "profile": profile,
        "motionIntent": motion_intent,
        "initialScale": scales[0],
        "times": expanded_times,
        "propertyTypes": property_types,
        "values": values,
        "keyframeCount": len(values),
        "scaleDelta": scale_delta,
        "positionDelta": position_delta,
        "framingNormalization": {
            "required": True,
            "priority": "primary-subject-screen-size-consistency",
            "target": "keep the primary subject in the same perceived size band across cuts",
            "rejectIf": "the primary subject jumps between small prop, hero close-up, and medium object scale across adjacent scenes",
        },
        "capcutEditable": True,
        "previewOnly": False,
    }


def _caption_animation_for_scene(scene: dict[str, Any], idx: int) -> dict[str, Any]:
    role = _normalize_role(scene.get("referenceEditRole") or scene.get("captionPreset") or "")
    if "hook" in role:
        animation = "Pop_Up"
        duration = 0.22
    elif "mechanism" in role:
        animation = "Wipe_Right"
        duration = 0.18
    elif "evidence" in role or "risk" in role:
        animation = "Slide_Up"
        duration = 0.18
    else:
        animation = "Mini_Zoom"
        duration = 0.20
    return {
        "role": role or f"scene-{idx}",
        "introAnimation": animation,
        "introDurationSec": duration,
    }


def _transition_for_scene(idx: int, scene: dict[str, Any]) -> str | None:
    if idx <= 1:
        return None
    role = _normalize_role(scene.get("referenceEditRole") or "")
    if "answer" in role:
        return "Dissolve"
    return "Mix_1"


def _editorial_motion_pass_contract(
    *,
    editorial_motion_profiles: list[dict[str, Any]],
    caption_animation_profiles: list[dict[str, Any]],
    transition_count: int,
    total_motion_keyframes: int,
) -> dict[str, Any]:
    scale_deltas = [float(profile.get("scaleDelta") or 0.0) for profile in editorial_motion_profiles]
    keyframes_per_scene = [int(profile.get("keyframeCount") or 0) for profile in editorial_motion_profiles]
    return {
        "required": True,
        "mode": "capcut-scene-directed-motion",
        "sceneDirectedMotion": True,
        "capcutKeyframesNotPreviewOnly": True,
        "motionProfiles": [
            {
                "sceneId": profile.get("sceneId"),
                "role": profile.get("role"),
                "profile": profile.get("profile"),
                "motionIntent": profile.get("motionIntent"),
                "keyframeCount": profile.get("keyframeCount"),
                "scaleDelta": profile.get("scaleDelta"),
                "positionDelta": profile.get("positionDelta"),
                "framingNormalization": profile.get("framingNormalization"),
            }
            for profile in editorial_motion_profiles
        ],
        "sceneMotionProfileCount": len(editorial_motion_profiles),
        "captionAnimationProfileCount": len(caption_animation_profiles),
        "captionAnimationDesigned": len(caption_animation_profiles) >= len(editorial_motion_profiles),
        "transitionCount": transition_count,
        "totalKeyframeCount": total_motion_keyframes,
        "minKeyframesPerScene": min(keyframes_per_scene) if keyframes_per_scene else 0,
        "minVisibleScaleDelta": min(scale_deltas) if scale_deltas else 0.0,
        "maxUnmotivatedMotionSec": 0,
        "referenceBasis": [
            "CapCut keyframe animation: scale and position keyframes create source-level editorial motion",
            "Short-form timeline editing should use motion to direct attention rather than decorative stickers",
            "Text animation must support the spoken beat while remaining readable and editable",
        ],
    }


def _normalize_role(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _track_counts(draft_data: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for track in draft_data.get("tracks") or []:
        track_type = str(track.get("type") or "unknown")
        counts[track_type] = counts.get(track_type, 0) + len(track.get("segments") or [])
    return counts


def _exported_video_keyframe_count(draft_data: dict[str, Any]) -> int:
    total = 0
    for track in draft_data.get("tracks") or []:
        if str(track.get("type") or "") != "video":
            continue
        for segment in track.get("segments") or []:
            for keyframes in segment.get("common_keyframes") or []:
                keyframe_list = keyframes.get("keyframe_list") if isinstance(keyframes, dict) else None
                if isinstance(keyframe_list, list):
                    total += len(keyframe_list)
    return total


def _scene_timing_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    timings = (
        manifest.get("openingAudioContinuity", {})
        .get("ttsAlignment", {})
        .get("sceneTimings", [])
    )
    return {str(item.get("sceneId")): item for item in timings if isinstance(item, dict) and item.get("sceneId")}


def _fallback_timing(scenes: list[dict[str, Any]], index: int) -> dict[str, float]:
    start = sum(float(scene.get("durationSec") or 0.0) for scene in scenes[:index])
    duration = float(scenes[index].get("durationSec") or 1.0)
    return {
        "sceneStartSec": start,
        "sceneEndSec": start + duration,
        "captionStartSec": start + 0.2,
        "captionEndSec": start + duration,
        "voiceStartSec": start,
        "voiceEndSec": start + duration,
        "ttsDurationSec": duration,
    }


def _timeline_duration(manifest: dict[str, Any], scenes: list[dict[str, Any]]) -> float:
    duration = (
        manifest.get("openingAudioContinuity", {})
        .get("ttsAlignment", {})
        .get("timelineDurationSec")
    )
    if duration:
        return float(duration)
    return sum(float(scene.get("durationSec") or 0.0) for scene in scenes)


def _tts_path_for_scene(root: Path, render_dir: Path, scene_id: str) -> Path:
    path = render_dir / f"{scene_id}.tts.mp3"
    if path.exists():
        return path
    compact = scene_id.replace("scene-", "scene-")
    path = render_dir / f"{compact}.tts.mp3"
    if path.exists():
        return path
    return _resolve_path(root, f"storage/renders/{render_dir.name}/{scene_id}.tts.mp3")


def _overlay_asset_for_element(root: Path, element: dict[str, Any]) -> Path | None:
    role = str(element.get("semanticRole") or "")
    asset_key = OVERLAY_ROLE_ASSET.get(role)
    if asset_key is None:
        return None
    overlay_dir = root / "assets" / "overlays" / "capcut-nontext"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    path = overlay_dir / f"{asset_key}.png"
    _write_overlay_png(path, asset_key)
    return path


def _write_overlay_png(path: Path, asset_key: str) -> None:
    width, height = 1080, 1920
    pixels = bytearray(width * height * 4)
    if asset_key == "warning_edge":
        _draw_frame(pixels, width, height, (215, 25, 32, 92), thickness=28)
        _draw_line(pixels, width, height, 830, 210, 1010, 390, (215, 25, 32, 170), 20)
        _draw_line(pixels, width, height, 800, 300, 980, 480, (215, 25, 32, 125), 12)
        _draw_line(pixels, width, height, 92, 1505, 275, 1688, (215, 25, 32, 130), 14)
    elif asset_key == "safe_edge":
        _draw_rect(pixels, width, height, 0, height - 42, width, height, (31, 143, 77, 115))
        _draw_rect(pixels, width, height, 0, 0, 24, height, (31, 143, 77, 78))
        _draw_line(pixels, width, height, 808, 1508, 872, 1570, (31, 143, 77, 160), 18)
        _draw_line(pixels, width, height, 866, 1570, 1016, 1384, (31, 143, 77, 160), 18)
    elif asset_key == "risk_pulse":
        _draw_frame(pixels, width, height, (255, 179, 64, 54), thickness=18)
        _draw_rect(pixels, width, height, 84, 760, 996, 778, (255, 179, 64, 95))
        _draw_rect(pixels, width, height, 84, 1142, 996, 1160, (255, 179, 64, 68))
        _draw_line(pixels, width, height, 210, 760, 145, 650, (255, 179, 64, 110), 12)
        _draw_line(pixels, width, height, 870, 1160, 935, 1270, (255, 179, 64, 80), 12)
    elif asset_key == "basis_scan":
        _draw_rect(pixels, width, height, width - 38, 350, width - 18, 1420, (255, 214, 10, 92))
        for y in (520, 700, 880, 1060):
            _draw_rect(pixels, width, height, width - 210, y, width - 52, y + 10, (255, 214, 10, 88))
    else:
        _draw_rect(pixels, width, height, 74, 220, 92, 760, (255, 214, 10, 108))
        _draw_rect(pixels, width, height, 74, 220, 392, 238, (255, 214, 10, 108))
        _draw_rect(pixels, width, height, 74, 742, 260, 760, (255, 214, 10, 76))
        _draw_line(pixels, width, height, 900, 250, 1005, 355, (255, 214, 10, 84), 12)
    _write_png(path, width, height, pixels)


def _draw_frame(
    pixels: bytearray,
    width: int,
    height: int,
    rgba: tuple[int, int, int, int],
    *,
    thickness: int,
) -> None:
    _draw_rect(pixels, width, height, 0, 0, width, thickness, rgba)
    _draw_rect(pixels, width, height, 0, height - thickness, width, height, rgba)
    _draw_rect(pixels, width, height, 0, 0, thickness, height, rgba)
    _draw_rect(pixels, width, height, width - thickness, 0, width, height, rgba)


def _draw_rect(
    pixels: bytearray,
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    rgba: tuple[int, int, int, int],
) -> None:
    x0 = max(0, min(width, x0))
    x1 = max(0, min(width, x1))
    y0 = max(0, min(height, y0))
    y1 = max(0, min(height, y1))
    for y in range(y0, y1):
        row = y * width * 4
        for x in range(x0, x1):
            i = row + x * 4
            pixels[i:i + 4] = bytes(rgba)


def _draw_line(
    pixels: bytearray,
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    rgba: tuple[int, int, int, int],
    thickness: int,
) -> None:
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    half = max(1, thickness // 2)
    for step in range(steps + 1):
        t = step / steps
        x = int(x0 + (x1 - x0) * t)
        y = int(y0 + (y1 - y0) * t)
        _draw_rect(pixels, width, height, x - half, y - half, x + half, y + half, rgba)


def _write_png(path: Path, width: int, height: int, rgba: bytearray) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    scanlines = bytearray()
    stride = width * 4
    for y in range(height):
        scanlines.append(0)
        start = y * stride
        scanlines.extend(rgba[start:start + stride])
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(scanlines), level=9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(data)


def _callout_window(element: dict[str, Any]) -> tuple[float, float]:
    role = str(element.get("semanticRole") or "")
    element_type = str(element.get("type") or "")
    start = max(0.0, float(element.get("startSec") or 0.0))
    raw_end = float(element.get("endSec") or start + 0.5)
    min_duration = CALLOUT_MIN_DURATION_BY_ROLE.get(
        role,
        CALLOUT_MIN_DURATION_BY_TYPE.get(element_type, 0.9),
    )
    return start, max(raw_end, start + min_duration)


def _sfx_beats_for_element(element: dict[str, Any]) -> list[dict[str, Any]]:
    role = str(element.get("semanticRole") or "")
    beats = SFX_BEATS_BY_ROLE.get(role)
    if beats:
        return [dict(beat) for beat in beats]
    if element.get("audibleCue") is True:
        return [
            {"beat": "pre", "path": "assets/sfx/whoosh-05.mp3", "offsetSec": -0.12, "durationSec": 0.18, "volume": 0.36},
            {"beat": "hit", "path": "assets/sfx/click-03.mp3", "offsetSec": 0.02, "durationSec": 0.16, "volume": 0.34},
        ]
    return []


def _track_slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in value.lower()).strip("_")
    return slug or "cue"


def _caption_text(value: Any) -> str:
    return str(value or "").replace("\\N", "\n").strip()


def _scene_num(scene_id: str, fallback: int) -> int:
    digits = "".join(ch for ch in scene_id if ch.isdigit())
    return int(digits) if digits else fallback


def _resolve_path(root: Path, raw: Any) -> Path:
    if raw is None:
        return Path("")
    path = Path(str(raw))
    if path.is_absolute():
        return path
    return root / path


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an editable CapCut handoff draft from a render manifest.")
    parser.add_argument("--manifest", required=True, help="Path to preflight/render manifest JSON.")
    parser.add_argument("--project-root", default=".", help="Video Studio project root.")
    parser.add_argument("--capcut-draft-dir", default="", help="CapCut com.lveditor.draft directory.")
    parser.add_argument("--preflight-path", default="", help="Path for regenerated golden-reference preflight JSON.")
    parser.add_argument("--no-write-manifest", action="store_true", help="Do not write capcutHandoff back into the manifest.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = build_capcut_handoff(
        args.manifest,
        project_root=args.project_root,
        capcut_draft_dir=args.capcut_draft_dir or None,
        write_manifest=not args.no_write_manifest,
        preflight_path=args.preflight_path or None,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
