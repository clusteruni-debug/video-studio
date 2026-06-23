"""Pre-render golden-reference compliance gate.

This gate compares a candidate manifest against the code-level grammar encoded
by ``reference_style_presets`` before the FFmpeg render path runs. It does not
trust manifest "pass" claims as evidence; it requires explicit scene contracts
and local source artifacts.
"""

from __future__ import annotations

import contextlib
import json
import wave
from pathlib import Path
from typing import Any

from worker.render.reference_style_presets import get_reference_style_preset


CAMERA_TERMS = {
    "camera",
    "close-up",
    "closeup",
    "handheld",
    "macro",
    "pov",
    "shot",
    "vertical",
    "zoom",
    "pan",
    "tilt",
    "세로",
    "카메라",
    "클로즈업",
    "핸드헬드",
}

ACTION_TERMS = {
    "show",
    "shows",
    "visible",
    "sitting",
    "holding",
    "held",
    "moving",
    "pour",
    "pouring",
    "walking",
    "turning",
    "opening",
    "object",
    "보이는",
    "움직",
    "놓인",
    "잡고",
    "따르는",
    "물체",
}

FORBIDDEN_INTERNAL_PROMPT_TERMS = {
    "existing-pipeline",
    "source-first",
    "render manifest",
    "reference style",
    "safe zone",
    "proof task",
    "internal",
    "scene-",
    "layout variant",
    "asset id",
}

FORBIDDEN_VIEWER_CAPTION_TERMS = {
    "reference",
    "safe zone",
    "source",
    "scene",
    "layout",
    "레퍼런스",
    "safe-zone",
    "소스",
    "씬",
    "장면",
    "레이아웃",
}

FORBIDDEN_OVERLAY_TERMS = {
    "bar",
    "stripe",
    "line",
    "heat-bar",
    "debug",
    "safe-zone",
    "vertical-marker",
    "세로막대",
    "흰선",
}

PLACEHOLDER_BGM_TERMS = {
    "placeholder",
    "synthetic",
    "lavfi",
    "sine",
    "anoisesrc",
    "noise-only",
    "silent",
    "silence",
    "tone-only",
    "test-tone",
}

POST_EDIT_REFERENCE_TERMS = {
    "youtube",
    "shorts",
    "tiktok",
    "top ads",
    "hook",
    "accessibility",
}

POST_EDIT_SCORE_DIMENSIONS = {
    "sourceTakeQuality",
    "sourceSequenceContinuity",
    "hookClarity",
    "storyPayoff",
    "copyTtsQuality",
    "captionAccessibility",
    "editRhythm",
    "audioMix",
    "colorTechnicalQuality",
    "platformReferenceFit",
}

EDITORIAL_DIRECTION_REFERENCE_TERMS = {
    "youtube",
    "shorts",
    "capcut",
    "sound",
    "accessibility",
    "continuity",
}

EDITORIAL_DIRECTION_CUT_REASONS = {
    "match-action",
    "new-information",
    "spatial-reorientation",
    "payoff",
    "rhythm",
    "audio-bridge",
    "continuity-bridge",
}

EDITORIAL_DIRECTION_AUDIO_BINDING_MODES = {
    "visible-action",
    "source-ambience",
    "transition",
    "cut",
    "bgm-bed",
    "voiceover",
    "silence",
}

EDITORIAL_DIRECTION_CONTINUITY_SLOTS = {
    "primarySubject",
    "actorOrManipulator",
    "environment",
    "primaryAction",
    "camera",
    "lighting",
    "audio",
}

EDITORIAL_PASS_SCHEMA = "video-studio.editorial-pass.v1"
POST_EDIT_SCORE_SCHEMA = "video-studio.post-edit-score.v1"
REFERENCE_COMPARISON_SCHEMA = "video-studio.reference-comparison.v1"
CAPCUT_DRAFT_AUDIT_SCHEMA = "video-studio.capcut-draft-audit.v1"

EXTERNAL_EDIT_REFERENCE_TERMS = {
    "youtube",
    "shorts",
    "tiktok",
    "motion",
    "wcag",
}

EXTERNAL_EDIT_ALLOWED_TYPES = {
    "beat-sync",
    "caption-emphasis",
    "callout",
    "focus-pulse",
    "freeze-hold",
    "keyword-emphasis",
    "mask-vignette",
    "match-cut-assist",
    "motion-graphic",
    "pointer-line",
    "progress-marker",
    "safe-check",
    "sfx-hit",
    "split-screen",
    "sticker",
    "warning-pulse",
    "warning-x",
}

EXTERNAL_EDIT_FORBIDDEN_LABEL_TERMS = {
    "debug",
    "editor",
    "guide",
    "layout",
    "rec",
    "safe zone",
    "safe-zone",
    "scene",
}

EXTERNAL_EDIT_ALLOWED_SEMANTIC_ROLES = {
    "answer-payoff",
    "hook-question",
    "mechanism-focus",
    "payoff",
    "risk-focus",
    "safe-resolution",
    "transition-continuity",
    "warning-no",
}

EXTERNAL_EDIT_ALLOWED_BINDING_MODES = {
    "visible-action",
    "source-state-change",
    "cut-bridge",
    "attention-guide",
    "payoff",
    "restraint",
}

SYMBOLIC_CUE_TERMS = {
    "check",
    "green check",
    "ok",
    "red x",
    "safe-check",
    "warning-x",
    "x",
}

CAPCUT_MEDIA_TRACK_FLAGS = {
    "sourceVideoTracks",
    "ttsTracks",
    "bgmTrack",
    "captionTracks",
    "editElementTracks",
    "effectTracks",
}

CAPCUT_REFERENCE_TERMS = {
    "capcut",
    "keyframe",
    "caption",
    "shorts",
    "timeline",
    "tiktok",
    "top ads",
    "easing",
    "effect",
    "vectcutapi",
}

CAPCUT_AUTOMATION_TOOL_TERMS = {
    "vectcutapi",
    "pyjianyingdraft",
    "capcut draft",
}

SOURCE_TAKE_SCORE_DIMENSIONS = {
    "promptIntentFit",
    "primarySubjectIntegrity",
    "actorOrManipulatorIntegrity",
    "actionReadability",
    "physicalPlausibility",
    "cameraGrammar",
    "lightingColorNaturalness",
    "temporalStability",
    "aiArtifactControl",
    "editability",
}

SOURCE_SEQUENCE_SCORE_DIMENSIONS = {
    "entityContinuity",
    "environmentContinuity",
    "actionContinuity",
    "cameraContinuity",
    "lightingContinuity",
    "styleContinuity",
    "repairability",
}

SOURCE_SEQUENCE_REQUIRED_SLOTS = {
    "primarySubject",
    "actorOrManipulator",
    "environment",
    "primaryAction",
    "camera",
    "lighting",
    "style",
}

AI_SLOP_COPY_PHRASES = {
    "let's dive in",
    "you won't believe",
    "shocking truth",
    "did you know",
    "여러분",
    "놀라운 사실",
    "충격적인",
    "믿기 어렵겠지만",
    "혹시 알고 계셨나요",
    "지금부터",
    "알아볼게요",
    "해볼게요",
    "함께 알아",
    "끝까지",
    "꼭 보세요",
    "대박",
    "꿀팁",
    "비밀",
    "친구",
    "궁금하시죠",
}

INSTRUCTION_COPY_PHRASES = {
    "write",
    "show this",
    "must show",
    "do not",
    "해야 함",
    "작성하세요",
    "사용하세요",
    "표시하세요",
    "넣는다",
    "보여준다",
    "금지",
    "필수",
}

REPORT_STYLE_PHRASES = {
    "입니다",
    "합니다",
    "됩니다",
    "의미합니다",
    "설명합니다",
    "확인됩니다",
    "나타납니다",
    "위험성이",
    "가능성이",
    "해당",
    "본 영상",
}

AWKWARD_KOREAN_COPY_PHRASES = {
    "답은 보관 시간",
    "한 모금보다 보관 시간",
    "정답은 조건",
    "그냥 피하기",
}

KOREAN_COPY_ACTION_MARKERS = {
    "걸까",
    "까요",
    "나요",
    "네요",
    "느냐",
    "다면",
    "둔",
    "두세요",
    "마셔",
    "마시",
    "말고",
    "버리",
    "보세요",
    "세요",
    "아니",
    "예요",
    "이에요",
    "있다",
    "있다면",
    "있었",
    "좋",
    "중요",
    "조심",
    "뜨거",
    "는지",
    "피하",
}

KOREAN_TTS_SENTENCE_ENDINGS = (
    "까요",
    "나요",
    "네요",
    "요",
    "다",
    "세요",
    "어요",
    "예요",
    "이에요",
    "죠",
    "지요",
    "해요",
)

OVERFRIENDLY_TTS_PHRASES = {
    "여러분",
    "친구",
    "자 그럼",
    "우리 같이",
    "함께 알아",
    "궁금하시죠",
    "알아볼게요",
    "해볼게요",
}

REFERENCE_TTS_DEFAULT_PROVIDER = "edge-tts"

REFERENCE_TTS_ALLOWED_PROVIDERS = {
    "edge-tts",
    "azure-speech",
    "azure-speech-f0",
    "melo-tts",
    "human-recorded",
    "studio-recorded",
}

REFERENCE_TTS_NON_DEFAULT_PROVIDERS = REFERENCE_TTS_ALLOWED_PROVIDERS - {REFERENCE_TTS_DEFAULT_PROVIDER}

REFERENCE_TTS_QUALITY_CLASSES = {
    "neural",
    "neural-hd",
    "local-neural",
    "human",
    "human-recorded",
    "studio-recorded",
}

FORBIDDEN_TTS_PROVIDER_TERMS = {
    "desktop",
    "heami",
    "microsoft heami desktop",
    "sapi",
    "system.speech",
    "windows-speech",
    "windows tts",
    "windows-tts",
}

APPROVED_TTS_PROVIDER_DECISIONS = {
    "approved",
    "approved-replacement",
    "pass",
    "reviewed-pass",
}


def evaluate_golden_reference_compliance(
    manifest: dict[str, Any],
    *,
    project_root: Path | str = ".",
    manifest_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return a deterministic pre-render compliance report."""
    root = Path(project_root).resolve()
    preset_key = _reference_preset_key(manifest)
    required = _is_gate_required(manifest, preset_key)
    report: dict[str, Any] = {
        "schema": "video-studio.golden-reference-preflight.v1",
        "required": required,
        "renderAllowed": True,
        "status": "skipped",
        "presetKey": preset_key,
        "manifestPath": str(Path(manifest_path).resolve()) if manifest_path else "",
        "failedChecks": [],
        "checks": {},
        "scenes": [],
    }
    if not required:
        report["checks"]["required"] = _check("pass", "No reference preset or explicit golden compliance requirement.")
        return report

    preset: dict[str, Any] | None = None
    try:
        preset = get_reference_style_preset(preset_key)
        report["checks"]["preset"] = _check("pass", f"known preset {preset_key}")
    except KeyError as exc:
        report["checks"]["preset"] = _check("fail", str(exc))

    scenes = manifest.get("scenes") if isinstance(manifest.get("scenes"), list) else []
    if not scenes:
        report["checks"]["sceneList"] = _check("fail", "manifest.scenes must be a non-empty list")
    else:
        report["checks"]["sceneList"] = _check("pass", f"{len(scenes)} scene(s)")

    report["checks"]["sourceContactSheet"] = _check_source_contact_sheet(manifest, root)
    report["checks"]["sourceSequenceContinuity"] = _check_source_sequence_continuity(
        manifest,
        scene_count=len(scenes),
    )
    report["checks"]["visualUnityTreatment"] = _check_visual_unity_treatment(manifest)
    report["checks"]["openingAudioContinuity"] = _check_opening_audio_continuity(
        manifest,
        root,
        scene_count=len(scenes),
    )
    report["checks"]["postEditGoldenReference"] = _check_post_edit_golden_reference(
        manifest,
        root,
        scenes=scenes,
    )

    if preset is not None:
        for idx, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                report["scenes"].append({
                    "sceneId": f"scene-{idx + 1:03d}",
                    "status": "fail",
                    "failedChecks": ["sceneShape"],
                    "checks": {"sceneShape": _check("fail", "scene must be an object")},
                })
                continue
            report["scenes"].append(_check_scene(scene, manifest, preset, idx, len(scenes), root))

    failed = _collect_failed(report)
    report["failedChecks"] = failed
    report["renderAllowed"] = not failed
    report["status"] = "pass" if not failed else "fail"
    return report


def write_golden_reference_preflight_report(report: dict[str, Any], path: Path | str) -> str:
    """Persist a preflight report and return the written path."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out)


def _is_gate_required(manifest: dict[str, Any], preset_key: str) -> bool:
    if manifest.get("goldenReferenceComplianceRequired") is True:
        return True
    if manifest.get("referenceComplianceRequired") is True:
        return True
    return bool(preset_key)


def _reference_preset_key(manifest: dict[str, Any]) -> str:
    direct = str(manifest.get("referenceStylePreset") or manifest.get("reference_style_preset") or "").strip()
    if direct:
        return direct
    summary = manifest.get("referenceStyleSummary")
    if isinstance(summary, dict):
        return str(summary.get("key") or "").strip()
    return ""


def _check_scene(
    scene: dict[str, Any],
    manifest: dict[str, Any],
    preset: dict[str, Any],
    idx: int,
    total: int,
    root: Path,
) -> dict[str, Any]:
    scene_id = str(scene.get("sceneId") or scene.get("id") or f"scene-{idx + 1:03d}")
    checks = {
        "sourceContract": _check_source_contract(scene),
        "sourceQualityRubric": _check_source_quality_rubric(scene),
        "sourceArtifact": _check_source_artifact(scene, manifest, root),
        "promptContract": _check_prompt_contract(scene, manifest),
        "captionContract": _check_caption_contract(scene, preset, idx, total),
        "copyTone": _check_caption_copy_tone(scene, preset, idx, total),
        "layoutContract": _check_layout_contract(scene, preset, idx),
        "captionDirection": _check_caption_direction(scene, preset, idx),
        "ttsScriptQuality": _check_tts_script_quality(scene, preset, idx, total),
        "referenceParity": _check_reference_parity(scene, preset, idx, total),
    }
    failed = [key for key, value in checks.items() if value["status"] == "fail"]
    return {
        "sceneId": scene_id,
        "status": "fail" if failed else "pass",
        "failedChecks": failed,
        "checks": checks,
    }


def _check_source_contact_sheet(manifest: dict[str, Any], root: Path) -> dict[str, str]:
    path = _artifact_path(
        manifest.get("sourceContactSheetPath")
        or _nested(manifest, "preflightArtifacts", "sourceContactSheetPath")
        or _nested(manifest, "goldenReferenceArtifacts", "sourceContactSheetPath")
    )
    if not path:
        if _nested(manifest, "visualFrameReview", "contactSheetPath"):
            return _check("fail", "post-render contact sheet is not pre-render source evidence")
        return _check("fail", "sourceContactSheetPath is required before reference-styled render")
    resolved = _resolve_artifact(root, path)
    if not resolved.exists():
        return _check("fail", f"source contact sheet missing: {path}")
    return _check("pass", f"source contact sheet exists: {path}")


def _check_source_sequence_continuity(manifest: dict[str, Any], *, scene_count: int) -> dict[str, str]:
    if scene_count <= 1:
        return _check("pass", "single-scene source sequence does not require cross-scene continuity scoring")
    contract = manifest.get("sourceSequenceContinuity") or manifest.get("sourceContinuityRubric")
    if not isinstance(contract, dict):
        return _check("fail", "sourceSequenceContinuity object is required for multi-source reference renders")
    if contract.get("required") is not True:
        return _check("fail", "sourceSequenceContinuity.required must be true")

    slots = set(_string_list(contract.get("continuitySlots") or contract.get("slotVocabulary")))
    missing_slots = sorted(SOURCE_SEQUENCE_REQUIRED_SLOTS - slots)
    if missing_slots:
        return _check(
            "fail",
            "sourceSequenceContinuity must define generic continuity slots: "
            + ", ".join(missing_slots),
        )

    min_dimension = _optional_float(contract.get("minDimension"), default=60.0)
    dimension_error = _score_dimension_error(
        contract.get("dimensions"),
        SOURCE_SEQUENCE_SCORE_DIMENSIONS,
        min_dimension,
        "sourceSequenceContinuity",
    )
    if dimension_error:
        return _check("fail", dimension_error)

    if contract.get("topicSpecificCriteriaInGlobalGate") is True:
        return _check("fail", "global source continuity gate must not use topic-specific criteria")
    return _check("pass", "source sequence continuity uses generic entity, environment, action, camera, lighting, style slots")


def _check_source_quality_rubric(scene: dict[str, Any]) -> dict[str, str]:
    contract = scene.get("sourceQualityRubric") or scene.get("sourceTakeQuality")
    if not isinstance(contract, dict):
        return _check("fail", "sourceQualityRubric object is required for every source take")
    if contract.get("required") is not True:
        return _check("fail", "sourceQualityRubric.required must be true")
    min_dimension = _optional_float(contract.get("minDimension"), default=60.0)
    dimension_error = _score_dimension_error(
        contract.get("dimensions"),
        SOURCE_TAKE_SCORE_DIMENSIONS,
        min_dimension,
        "sourceQualityRubric",
    )
    if dimension_error:
        return _check("fail", dimension_error)
    if contract.get("topicSpecificCriteriaInGlobalGate") is True:
        return _check("fail", "global source take gate must not use topic-specific criteria")
    return _check("pass", "source take quality uses generic prompt, subject, action, physics, camera, lighting, stability, artifact, editability dimensions")


def _check_visual_unity_treatment(manifest: dict[str, Any]) -> dict[str, str]:
    contract = manifest.get("visualUnityTreatment") or manifest.get("postEditUnityTreatment")
    if not isinstance(contract, dict):
        return _check("fail", "visualUnityTreatment object is required")
    if contract.get("required") is not True:
        return _check("fail", "visualUnityTreatment.required must be true")
    if contract.get("appliesToAllScenes") is not True:
        return _check("fail", "visualUnityTreatment must apply to all scenes")
    if contract.get("subjectSafe") is not True:
        return _check("fail", "visualUnityTreatment.subjectSafe must be true")
    treatment_terms = _string_list(contract.get("treatmentTypes") or contract.get("requiredElements"))
    if len(treatment_terms) < 2:
        return _check("fail", "visualUnityTreatment needs at least two shared treatment elements")
    normalized = " ".join(treatment_terms).lower()
    if not any(term in normalized for term in ("border", "frame", "matte", "hud", "color", "grade", "look")):
        return _check("fail", "visualUnityTreatment must declare a concrete shared frame/color/HUD treatment")
    checklist = _string_list(contract.get("reviewChecklist"))
    if len(checklist) < 3:
        return _check("fail", "visualUnityTreatment.reviewChecklist needs at least three review items")
    forbidden = _first_forbidden(" ".join(treatment_terms + checklist).lower(), {"debug", "safe-zone marker", "white vertical line"})
    if forbidden:
        return _check("fail", f"visualUnityTreatment contains forbidden overlay artifact: {forbidden}")
    return _check("pass", "shared post-edit treatment is required across all scenes")


def _check_opening_audio_continuity(
    manifest: dict[str, Any],
    root: Path,
    *,
    scene_count: int,
) -> dict[str, str]:
    contract = (
        manifest.get("openingAudioContinuity")
        or manifest.get("presentationContinuity")
        or manifest.get("editAudioContinuity")
    )
    if not isinstance(contract, dict):
        return _check("fail", "openingAudioContinuity object is required")

    cold_open = contract.get("coldOpen")
    if not isinstance(cold_open, dict):
        return _check("fail", "openingAudioContinuity.coldOpen object is required")
    if cold_open.get("firstFrameHasPrimaryVisual") is not True:
        return _check("fail", "first frame must show the primary visual, not a blank/title frame")
    if cold_open.get("firstFrameIsBlack") is True:
        return _check("fail", "black-screen opening is forbidden")
    if cold_open.get("captionOnlyOpening") is True or cold_open.get("firstFrameHasOnlySubtitleOrText") is True:
        return _check("fail", "caption-only opening is forbidden; physical source must be visible immediately")
    black_screen_sec = _optional_float(cold_open.get("blackScreenStartSec"), default=0.0)
    if black_screen_sec > 0.08:
        return _check("fail", "black-screen start must be <= 0.08s")
    first_action_sec = _optional_float(cold_open.get("firstVisibleActionSec"), default=99.0)
    if first_action_sec > 0.6:
        return _check("fail", "first visible object/action must land by 0.60s")

    first_evidence = _first_artifact_path(
        cold_open.get("firstTwoSecReviewPath"),
        cold_open.get("firstFrameEvidencePath"),
        contract.get("firstTwoSecReviewPath"),
    )
    if not first_evidence:
        return _check("fail", "first-two-seconds visual evidence path is required")
    if not _resolve_artifact(root, first_evidence).exists():
        return _check("fail", f"first-two-seconds visual evidence missing: {first_evidence}")

    audio_bed = contract.get("audioBed")
    if not isinstance(audio_bed, dict):
        return _check("fail", "openingAudioContinuity.audioBed object is required")
    if audio_bed.get("bgmPresent") is not True:
        return _check("fail", "BGM bed must be present")
    if audio_bed.get("bgmAudibleUnderVoice") is not True:
        return _check("fail", "BGM must remain audible under TTS, not erased by ducking")
    if audio_bed.get("introBgmAudible") is not True or audio_bed.get("outroBgmTailAudible") is not True:
        return _check("fail", "BGM must be audible in both intro and outro")
    if audio_bed.get("bgmNonPlaceholder") is not True:
        return _check("fail", "BGM must be a non-placeholder music/ambience asset")
    bgm_source = _normalize_text(
        " ".join(
            str(value or "")
            for value in (
                audio_bed.get("bgmSourcePath"),
                audio_bed.get("bgmSourceType"),
                audio_bed.get("bgmDescription"),
            )
        )
    )
    placeholder = _first_forbidden(bgm_source, PLACEHOLDER_BGM_TERMS)
    if placeholder:
        return _check("fail", f"BGM source appears placeholder/test-generated: {placeholder}")
    bgm_mean_db = _optional_float(audio_bed.get("bgmMeanVolumeDb"), default=-24.0)
    if bgm_mean_db < -34.0:
        return _check("fail", "BGM evidence level is too low to be considered audible")
    if bgm_mean_db > -10.0:
        return _check("fail", "BGM evidence level is too loud for narration-led Shorts")

    audio_evidence = _first_artifact_path(audio_bed.get("audioMixEvidencePath"), contract.get("audioMixEvidencePath"))
    if not audio_evidence:
        return _check("fail", "audio mix evidence path is required")
    if not _resolve_artifact(root, audio_evidence).exists():
        return _check("fail", f"audio mix evidence missing: {audio_evidence}")

    tts_alignment_check = _check_tts_alignment(contract, root, scene_count=scene_count)
    if tts_alignment_check["status"] == "fail":
        return tts_alignment_check

    required_bridges = max(0, scene_count - 1)
    bridges = contract.get("audioBridges") or contract.get("transitionBridges") or []
    if required_bridges and not isinstance(bridges, list):
        return _check("fail", "audioBridges must list one bridge per scene transition")
    if len(bridges) < required_bridges:
        return _check("fail", f"audioBridges needs at least {required_bridges} transition bridge(s)")
    for idx, bridge in enumerate(bridges[:required_bridges]):
        if not isinstance(bridge, dict):
            return _check("fail", f"audio bridge {idx + 1} must be an object")
        mode = str(bridge.get("mode") or "").strip().lower()
        if mode not in {"j-cut", "l-cut", "crossfade", "acrossfade", "sound-bridge"}:
            return _check("fail", f"audio bridge {idx + 1} mode is not a reference-safe bridge")
        duration_sec = _optional_float(bridge.get("durationSec"), default=0.0)
        if duration_sec < 0.2:
            return _check("fail", f"audio bridge {idx + 1} duration must be >= 0.20s")

    payoff_tail = contract.get("payoffTail")
    if not isinstance(payoff_tail, dict):
        return _check("fail", "openingAudioContinuity.payoffTail object is required")
    if payoff_tail.get("finalBeatHasVisualResolution") is not True:
        return _check("fail", "final beat must visibly resolve the hook")
    if payoff_tail.get("endingIsBlank") is True:
        return _check("fail", "blank ending tail is forbidden")
    if _optional_float(payoff_tail.get("blankOutroSec"), default=0.0) > 0.15:
        return _check("fail", "blank outro must be <= 0.15s")
    if _optional_float(payoff_tail.get("finalVisualHoldSec"), default=0.0) < 0.6:
        return _check("fail", "final visual answer needs at least 0.60s hold")
    if _optional_float(payoff_tail.get("finalBgmTailSec"), default=0.0) < 0.6:
        return _check("fail", "BGM tail needs at least 0.60s after the final answer")
    if _optional_float(payoff_tail.get("finalAudioFadeSec"), default=0.0) < 0.5:
        return _check("fail", "final audio fade must be at least 0.50s")
    final_evidence = _first_artifact_path(
        payoff_tail.get("finalTwoSecReviewPath"),
        payoff_tail.get("finalFrameEvidencePath"),
        contract.get("finalTwoSecReviewPath"),
    )
    if not final_evidence:
        return _check("fail", "final-two-seconds visual evidence path is required")
    if not _resolve_artifact(root, final_evidence).exists():
        return _check("fail", f"final-two-seconds visual evidence missing: {final_evidence}")

    return _check("pass", "cold open, audible BGM, audio bridges, and payoff tail are review-ready")


def _check_tts_alignment(contract: dict[str, Any], root: Path, *, scene_count: int) -> dict[str, str]:
    alignment = (
        contract.get("ttsAlignment")
        or contract.get("ttsSceneAlignment")
        or contract.get("voiceCaptionAlignment")
    )
    if not isinstance(alignment, dict):
        return _check("fail", "openingAudioContinuity.ttsAlignment object is required")
    if alignment.get("required") is not True:
        return _check("fail", "openingAudioContinuity.ttsAlignment.required must be true")
    if alignment.get("timelineReviewed") is not True:
        return _check("fail", "TTS/caption timeline review must be explicit")

    voice_quality_check = _check_tts_voice_quality(alignment, root)
    if voice_quality_check["status"] == "fail":
        return voice_quality_check

    if alignment.get("allVoiceLinesComplete") is not True or alignment.get("finalSpokenLineComplete") is not True:
        return _check("fail", "TTS must complete every spoken line, including the final answer")
    if alignment.get("finalCaptionCoversFinalVoiceLine") is not True:
        return _check("fail", "final caption must remain visible through the final spoken line")
    if alignment.get("captionsDoNotAdvanceBeforeVoice") is not True:
        return _check("fail", "captions must not advance while the previous voice line is still playing")

    timeline_duration = _optional_float(alignment.get("timelineDurationSec"), default=0.0)
    if timeline_duration <= 0:
        return _check("fail", "ttsAlignment.timelineDurationSec must be positive")

    narration_duration = _optional_float(alignment.get("narrationDurationSec"), default=0.0)
    voice_timeline_span = _optional_float(alignment.get("voiceTimelineSpanSec"), default=0.0)
    narration_path = _first_artifact_path(
        alignment.get("narrationAudioPath"),
        alignment.get("ttsSourcePath"),
        alignment.get("voiceoverPath"),
    )
    if narration_path:
        resolved = _resolve_artifact(root, narration_path)
        if not resolved.exists():
            return _check("fail", f"TTS narration audio missing: {narration_path}")
        measured = _audio_duration_seconds(resolved)
        if measured > 0:
            narration_duration = measured
    if narration_duration <= 0 and voice_timeline_span > 0:
        narration_duration = voice_timeline_span
    if narration_duration <= 0:
        return _check(
            "fail",
            "ttsAlignment.narrationDurationSec, voiceTimelineSpanSec, or measurable narrationAudioPath is required",
        )

    narration_start = _optional_float(alignment.get("narrationStartSec"), default=0.0)
    narration_end = _optional_float(alignment.get("narrationEndSec"), default=narration_start + narration_duration)
    if narration_duration > timeline_duration + 0.05:
        return _check(
            "fail",
            f"TTS duration {narration_duration:.2f}s exceeds video timeline {timeline_duration:.2f}s",
        )
    if narration_end > timeline_duration + 0.05:
        return _check(
            "fail",
            f"TTS end {narration_end:.2f}s exceeds video timeline {timeline_duration:.2f}s",
        )

    voice_tail = _optional_float(
        alignment.get("voiceEndsBeforeVideoEndSec"),
        default=timeline_duration - narration_end,
    )
    if voice_tail < 0.35:
        return _check("fail", "TTS must finish at least 0.35s before the video ends")
    max_desync = _optional_float(alignment.get("maxCaptionVoiceDesyncSec"), default=99.0)
    if max_desync > 0.65:
        return _check("fail", "caption/TTS desync must stay <= 0.65s")
    max_overflow = _optional_float(alignment.get("maxSceneVoiceOverflowSec"), default=99.0)
    if max_overflow > 0.25:
        return _check("fail", "voice must not overflow a scene by more than 0.25s")

    scenes = alignment.get("sceneTimings") or alignment.get("sceneAlignment") or []
    if not isinstance(scenes, list) or len(scenes) < scene_count:
        return _check("fail", "ttsAlignment.sceneTimings must cover every scene")
    for idx, scene in enumerate(scenes[:scene_count]):
        if not isinstance(scene, dict):
            return _check("fail", f"ttsAlignment.sceneTimings[{idx}] must be an object")
        scene_id = str(scene.get("sceneId") or f"scene-{idx + 1:03d}")
        scene_end = _optional_float(scene.get("sceneEndSec"), default=-1.0)
        voice_end = _optional_float(scene.get("voiceEndSec"), default=-1.0)
        caption_end = _optional_float(scene.get("captionEndSec"), default=-1.0)
        if scene_end < 0 or voice_end < 0 or caption_end < 0:
            return _check("fail", f"{scene_id} TTS timing must include sceneEndSec, voiceEndSec, and captionEndSec")
        if voice_end > scene_end + 0.25:
            return _check("fail", f"{scene_id} voice continues after the scene cut")
        if caption_end + 0.45 < voice_end:
            return _check("fail", f"{scene_id} caption disappears too early for the voice line")

    return _check("pass", "TTS voice quality, duration, scene timing, caption sync, and final spoken line are aligned")


def _check_tts_voice_quality(alignment: dict[str, Any], root: Path) -> dict[str, str]:
    contract = (
        alignment.get("voiceQuality")
        or alignment.get("ttsVoiceQuality")
        or alignment.get("voiceProviderQuality")
    )
    if not isinstance(contract, dict):
        return _check("fail", "ttsAlignment.voiceQuality object is required")
    if contract.get("required") is not True:
        return _check("fail", "ttsAlignment.voiceQuality.required must be true")

    provider = _tts_provider_key(
        contract.get("provider")
        or contract.get("providerKey")
        or contract.get("ttsProvider")
    )
    voice_name = str(contract.get("voiceName") or contract.get("voice") or "").strip()
    voice_class = _tts_provider_key(contract.get("voiceClass") or contract.get("qualityClass") or "")
    combined = _normalize_text(" ".join([provider, voice_name, voice_class]))
    forbidden = _first_forbidden(combined, FORBIDDEN_TTS_PROVIDER_TERMS)
    if forbidden:
        return _check(
            "fail",
            f"Windows SAPI/Desktop TTS cannot satisfy reference voice quality: {forbidden}",
        )

    if provider not in REFERENCE_TTS_ALLOWED_PROVIDERS:
        return _check(
            "fail",
            "reference TTS provider must be edge-tts by default, or approved Azure Speech/MeloTTS/human-recorded",
        )
    if not voice_name:
        return _check("fail", "ttsAlignment.voiceQuality.voiceName is required")

    neural_named = "neural" in _normalize_text(voice_name) or "mai-voice" in _normalize_text(voice_name)
    if voice_class not in REFERENCE_TTS_QUALITY_CLASSES and not neural_named:
        return _check("fail", "reference TTS voice must be neural, local-neural, or human-recorded quality")

    if provider in REFERENCE_TTS_NON_DEFAULT_PROVIDERS:
        decision = _tts_provider_key(
            contract.get("candidateEvaluationStatus")
            or contract.get("providerDecision")
            or contract.get("reviewStatus")
            or ""
        )
        if decision not in APPROVED_TTS_PROVIDER_DECISIONS and contract.get("providerExceptionApproved") is not True:
            return _check(
                "fail",
                "non-default TTS provider requires approved candidate evaluation before replacing edge-tts",
            )

    if contract.get("voiceNaturalnessReviewed") is not True:
        return _check("fail", "TTS voice naturalness review must be explicit")
    if contract.get("speechRateReviewed") is not True:
        return _check("fail", "TTS speech rate review must be explicit")
    rate_percent = _optional_float(
        contract.get("ratePercent")
        if contract.get("ratePercent") is not None
        else contract.get("speechRatePercent"),
        default=0.0,
    )
    if rate_percent < -18.0 or rate_percent > 12.0:
        return _check("fail", "TTS speech rate must stay within -18% to +12% for Korean reference narration")
    if contract.get("fallbackUsed") is True:
        return _check("fail", "TTS fallback voices are forbidden for golden/reference renders")
    if contract.get("perceivedRoboticOrSapi") is True:
        return _check("fail", "TTS perceived as robotic/SAPI cannot pass reference voice quality")

    evidence_path = _first_artifact_path(
        contract.get("candidateComparisonPath"),
        contract.get("voiceReviewPath"),
        contract.get("voiceNaturalnessEvidencePath"),
    )
    if not evidence_path:
        return _check("fail", "TTS voice candidate comparison evidence path is required")
    if not _resolve_artifact(root, evidence_path).exists():
        return _check("fail", f"TTS voice candidate evidence missing: {evidence_path}")

    return _check("pass", f"TTS provider {provider} uses reviewed neural/reference voice {voice_name}")


def _check_post_edit_golden_reference(
    manifest: dict[str, Any],
    root: Path,
    *,
    scenes: list[Any],
) -> dict[str, str]:
    scene_ids = _scene_ids_from_scenes(scenes)
    scene_count = len(scene_ids)
    contract = (
        manifest.get("postEditGoldenReference")
        or manifest.get("postEditGoldenReferenceGate")
        or manifest.get("postEditQualityGate")
    )
    if not isinstance(contract, dict):
        return _check("fail", "postEditGoldenReference object is required for every golden/reference render")
    if contract.get("required") is not True:
        return _check("fail", "postEditGoldenReference.required must be true")

    basis = _string_list(contract.get("referenceBasis") or contract.get("webReferenceBasis"))
    basis_text = _normalize_text(" ".join(basis))
    missing_basis = [term for term in POST_EDIT_REFERENCE_TERMS if term not in basis_text]
    if len(basis) < 4 or missing_basis:
        return _check(
            "fail",
            "postEditGoldenReference.referenceBasis must include YouTube Shorts, TikTok Top Ads, hook, and accessibility references",
        )

    score = contract.get("score")
    if not isinstance(score, dict):
        return _check("fail", "postEditGoldenReference.score object is required")
    min_overall = _optional_float(score.get("minOverall"), default=72.0)
    overall = _optional_float(score.get("overall"), default=-1.0)
    if overall < min_overall:
        return _check("fail", f"post-edit score {overall:.1f} is below minimum {min_overall:.1f}")
    dimensions = score.get("dimensions")
    min_dimension = _optional_float(score.get("minDimension"), default=60.0)
    dimension_error = _score_dimension_error(
        dimensions,
        POST_EDIT_SCORE_DIMENSIONS,
        min_dimension,
        "postEditGoldenReference.score",
    )
    if dimension_error:
        return _check("fail", dimension_error)

    evidence_paths = [
        contract.get("firstThreeSecReviewPath"),
        contract.get("captionSafeZoneEvidencePath"),
        contract.get("audioMixEvidencePath"),
        contract.get("colorMatchEvidencePath"),
        contract.get("finalTwoSecReviewPath"),
        contract.get("scoringReviewPath"),
    ]
    missing_evidence = [
        str(path or "").strip()
        for path in evidence_paths
        if not str(path or "").strip() or not _resolve_artifact(root, str(path).strip()).exists()
    ]
    if missing_evidence:
        return _check("fail", "post-edit evidence paths must all exist")

    editorial_direction = contract.get("editorialDirection") or contract.get("directingGrammar")
    if not isinstance(editorial_direction, dict):
        return _check("fail", "postEditGoldenReference.editorialDirection object is required")
    editorial_direction_check = _check_editorial_direction(
        editorial_direction,
        root,
        scenes=scenes,
    )
    if editorial_direction_check["status"] == "fail":
        return editorial_direction_check

    hook = contract.get("hook")
    if not isinstance(hook, dict):
        return _check("fail", "postEditGoldenReference.hook object is required")
    if hook.get("firstThreeSecHasPrimaryVisual") is not True:
        return _check("fail", "first 3s must contain primary visual, not only text/title")
    if hook.get("firstThreeSecHasMotionOrAction") is not True:
        return _check("fail", "first 3s must contain visible motion/action")
    if hook.get("firstThreeSecHasAudioBed") is not True:
        return _check("fail", "first 3s must contain audible audio bed")
    if hook.get("viewerQuestionClear") is not True:
        return _check("fail", "first 3s must establish a clear viewer question")
    first_caption_sec = _optional_float(hook.get("firstCaptionStartSec"), default=99.0)
    if first_caption_sec < 0.2 or first_caption_sec > 1.25:
        return _check("fail", "first caption must appear after source visibility and by 1.25s")

    captions = contract.get("captions")
    if not isinstance(captions, dict):
        return _check("fail", "postEditGoldenReference.captions object is required")
    if _optional_float(captions.get("maxLines"), default=99.0) > 2:
        return _check("fail", "captions.maxLines must be <= 2")
    if _optional_float(captions.get("maxCharsPerCaption"), default=99.0) > 28:
        return _check("fail", "captions.maxCharsPerCaption must be <= 28")
    if captions.get("stableSafeZone") is not True:
        return _check("fail", "captions must use a stable safe-zone system")
    if captions.get("mainSubjectOcclusion") is True:
        return _check("fail", "captions must not occlude the main subject")
    if captions.get("timelineReviewed") is not True:
        return _check("fail", "caption timeline review is required")
    if _optional_float(captions.get("maxScreenAreaRatio"), default=1.0) > 0.18:
        return _check("fail", "caption screen area must stay <= 18%")

    layout_hud = contract.get("layoutHud") or contract.get("layoutAndHud")
    if not isinstance(layout_hud, dict):
        return _check("fail", "postEditGoldenReference.layoutHud object is required")
    layout_check = _check_layout_hud_reference(layout_hud)
    if layout_check["status"] == "fail":
        return layout_check

    capcut_handoff = contract.get("capcutHandoff") or contract.get("capCutHandoff")
    if not isinstance(capcut_handoff, dict):
        return _check("fail", "postEditGoldenReference.capcutHandoff object is required")
    capcut_check = _check_capcut_handoff(capcut_handoff, root)
    if capcut_check["status"] == "fail":
        return capcut_check

    external_edit = contract.get("externalEditElements") or contract.get("editElementLayer")
    if not isinstance(external_edit, dict):
        return _check("fail", "postEditGoldenReference.externalEditElements object is required")
    external_edit_check = _check_external_edit_elements(
        external_edit,
        root,
        scene_ids=scene_ids,
        clean_editorial_mode=_is_clean_editorial_handoff(capcut_handoff),
    )
    if external_edit_check["status"] == "fail":
        return external_edit_check

    external_realization_check = _check_external_edit_realization(
        external_edit,
        capcut_handoff,
        root,
        clean_editorial_mode=_is_clean_editorial_handoff(capcut_handoff),
    )
    if external_realization_check["status"] == "fail":
        return external_realization_check

    audio_realization_check = _check_audio_visual_realization(editorial_direction, capcut_handoff, root)
    if audio_realization_check["status"] == "fail":
        return audio_realization_check

    rhythm = contract.get("rhythm")
    if not isinstance(rhythm, dict):
        return _check("fail", "postEditGoldenReference.rhythm object is required")
    if rhythm.get("actionBeatsAlignedToCuts") is not True:
        return _check("fail", "action beats must align to cuts")
    if rhythm.get("noHardJumpWithoutBridge") is not True:
        return _check("fail", "hard visual/audio jumps without bridge are forbidden")
    if _optional_float(rhythm.get("minShotHoldSec"), default=0.0) < 1.1:
        return _check("fail", "minShotHoldSec must be >= 1.10s")
    if _optional_float(rhythm.get("maxDeadAirSec"), default=99.0) > 0.65:
        return _check("fail", "dead air between action/information beats must be <= 0.65s")
    if _optional_float(rhythm.get("transitionCount"), default=-1.0) < max(0, scene_count - 1):
        return _check("fail", "rhythm.transitionCount must cover every scene transition")

    audio = contract.get("audio")
    if not isinstance(audio, dict):
        return _check("fail", "postEditGoldenReference.audio object is required")
    if audio.get("duckingApplied") is not True:
        return _check("fail", "audio ducking is required")
    if audio.get("bgmContinuous") is not True:
        return _check("fail", "BGM continuity across cuts is required")
    if audio.get("sourceAmbienceOrFoleyPresent") is not True:
        return _check("fail", "source ambience or foley layer is required")
    if audio.get("speechBgmSeparationReviewed") is not True:
        return _check("fail", "speech/BGM separation review is required")
    full_mix_mean = _optional_float(audio.get("fullMixMeanDb"), default=-99.0)
    if full_mix_mean < -24.0 or full_mix_mean > -12.0:
        return _check("fail", "full mix mean level must stay between -24dB and -12dB")

    color = contract.get("color")
    if not isinstance(color, dict):
        return _check("fail", "postEditGoldenReference.color object is required")
    if color.get("colorGradeAppliedToAllScenes") is not True:
        return _check("fail", "color grade must apply to all scenes")
    if color.get("noUnmotivatedFlashes") is not True:
        return _check("fail", "unmotivated flashes/exposure jumps are forbidden")
    if _optional_float(color.get("maxLumaDelta"), default=99.0) > 0.30:
        return _check("fail", "color.maxLumaDelta must be <= 0.30")
    if _optional_float(color.get("maxSaturationDelta"), default=99.0) > 0.30:
        return _check("fail", "color.maxSaturationDelta must be <= 0.30")

    payoff = contract.get("payoff")
    if not isinstance(payoff, dict):
        return _check("fail", "postEditGoldenReference.payoff object is required")
    if payoff.get("finalAnswerResolved") is not True:
        return _check("fail", "final beat must resolve the question")
    if payoff.get("noNewInfoInLastSecond") is not True:
        return _check("fail", "last second must not introduce new information")
    if _optional_float(payoff.get("finalVisualHoldSec"), default=0.0) < 1.0:
        return _check("fail", "final visual hold must be >= 1.00s")
    if _optional_float(payoff.get("finalAudioTailSec"), default=0.0) < 0.7:
        return _check("fail", "final audio tail must be >= 0.70s")

    derived_score, derived_score_error = _derive_post_edit_score(manifest, contract, scenes)
    if derived_score_error:
        return _check("fail", derived_score_error)
    score_evidence_check = _check_post_edit_score_evidence(
        contract,
        root,
        score,
        derived_score,
        min_overall=min_overall,
        min_dimension=min_dimension,
    )
    if score_evidence_check["status"] == "fail":
        return score_evidence_check

    return _check("pass", f"post-edit golden score {overall:.1f}/{min_overall:.1f} with required reference evidence")


def _check_editorial_direction(
    contract: dict[str, Any],
    root: Path,
    *,
    scenes: list[Any],
) -> dict[str, str]:
    scene_ids = _scene_ids_from_scenes(scenes)
    scene_count = len(scene_ids)
    timeline = _scene_timeline(scenes)
    if contract.get("required") is not True:
        return _check("fail", "editorialDirection.required must be true")
    if contract.get("topicSpecificCriteriaInGlobalGate") is True:
        return _check("fail", "editorialDirection gate must not use topic-specific criteria")

    basis = _string_list(contract.get("referenceBasis") or contract.get("webReferenceBasis"))
    basis_text = _normalize_text(" ".join(basis))
    missing_basis = [term for term in EDITORIAL_DIRECTION_REFERENCE_TERMS if term not in basis_text]
    if len(basis) < 5 or missing_basis:
        return _check(
            "fail",
            "editorialDirection.referenceBasis must include YouTube Shorts, CapCut, sound design, accessibility, and continuity references",
        )

    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    required_evidence = {
        "directingPlanPath": evidence.get("directingPlanPath") or contract.get("directingPlanPath"),
        "phoneReviewPath": evidence.get("phoneReviewPath") or contract.get("phoneReviewPath"),
        "referenceComparisonPath": evidence.get("referenceComparisonPath") or contract.get("referenceComparisonPath"),
        "noHudComparisonPath": evidence.get("noHudComparisonPath") or contract.get("noHudComparisonPath"),
    }
    for key, raw_path in required_evidence.items():
        path = str(raw_path or "").strip()
        if not path:
            return _check("fail", f"editorialDirection.evidence.{key} is required")
        if key in {"directingPlanPath", "referenceComparisonPath"}:
            schema = EDITORIAL_PASS_SCHEMA if key == "directingPlanPath" else REFERENCE_COMPARISON_SCHEMA
            evidence_payload, evidence_error = _read_json_object(root, path, f"editorialDirection.evidence.{key}", schema=schema)
            if evidence_error:
                return _check("fail", evidence_error)
            if evidence_payload.get("status") not in {"pass", "reviewed-pass"}:
                return _check("fail", f"editorialDirection.evidence.{key} must record pass/reviewed-pass status")
        else:
            media_error = _check_media_evidence_file(root, path, f"editorialDirection.evidence.{key}")
            if media_error:
                return _check("fail", media_error)

    directing_plan, directing_plan_error = _read_json_object(
        root,
        str(required_evidence["directingPlanPath"]),
        "editorialDirection.directingPlanPath",
        schema=EDITORIAL_PASS_SCHEMA,
    )
    if directing_plan_error:
        return _check("fail", directing_plan_error)
    comparison_evidence, comparison_error = _read_json_object(
        root,
        str(required_evidence["referenceComparisonPath"]),
        "editorialDirection.referenceComparisonPath",
        schema=REFERENCE_COMPARISON_SCHEMA,
    )
    if comparison_error:
        return _check("fail", comparison_error)
    if len(comparison_evidence.get("externalReferences") or []) < 2:
        return _check("fail", "editorialDirection reference comparison evidence must include at least two external references")
    if comparison_evidence.get("noHudAbReviewed") is not True:
        return _check("fail", "editorialDirection reference comparison evidence must include no-HUD/no-effect A/B review")
    if comparison_evidence.get("editImprovesComprehensionOverNoHud") is not True:
        return _check("fail", "editorialDirection evidence must prove edit improves comprehension over no-HUD baseline")

    shot_map = contract.get("shotIntentMap")
    if not isinstance(shot_map, list) or len(shot_map) != scene_count:
        return _check("fail", "editorialDirection.shotIntentMap must cover every scene")
    plan_shot_map = directing_plan.get("shotIntentMap")
    plan_shot_ids = _scene_id_list(plan_shot_map)
    if plan_shot_ids != scene_ids:
        return _check("fail", "editorialDirection directing plan shotIntentMap must match manifest scene order")
    for idx, shot in enumerate(shot_map[:scene_count]):
        if not isinstance(shot, dict):
            return _check("fail", f"editorialDirection.shotIntentMap[{idx}] must be an object")
        if str(shot.get("sceneId") or "").strip() != scene_ids[idx]:
            return _check("fail", "editorialDirection.shotIntentMap sceneId/order must match manifest.scenes")
        plan_shot = plan_shot_map[idx] if isinstance(plan_shot_map, list) and idx < len(plan_shot_map) else None
        if not isinstance(plan_shot, dict):
            return _check("fail", "editorialDirection directing plan shotIntentMap must match manifest fields")
        shot_mismatch = _dict_key_mismatch(
            shot,
            plan_shot,
            (
                "sceneId",
                "role",
                "viewerQuestionOrAnswer",
                "visibleEvent",
                "focusTarget",
                "sourceEventReadable",
                "subjectProtected",
                "captionExplainsMissingVisual",
            ),
        )
        if shot_mismatch:
            return _check("fail", f"editorialDirection directing plan shotIntentMap must match manifest fields: {shot_mismatch}")
        for key in ("sceneId", "role", "viewerQuestionOrAnswer", "visibleEvent", "focusTarget"):
            min_len = 3 if key == "role" else 8
            if len(str(shot.get(key) or "").strip()) < min_len:
                return _check("fail", f"editorialDirection.shotIntentMap[{idx}].{key} must be explicit")
        if shot.get("sourceEventReadable") is not True:
            return _check("fail", "editorialDirection shot visible event must be readable without captions")
        if shot.get("subjectProtected") is not True:
            return _check("fail", "editorialDirection shot must protect the primary subject/action")
        if shot.get("captionExplainsMissingVisual") is True:
            return _check("fail", "editorialDirection cannot use captions to explain a missing visual event")

    cut_plan = contract.get("motivatedCutPlan") or contract.get("cutPlan")
    required_cuts = max(0, scene_count - 1)
    if not isinstance(cut_plan, list) or len(cut_plan) != required_cuts:
        return _check("fail", "editorialDirection.motivatedCutPlan must cover every cut")
    plan_cut_plan = directing_plan.get("motivatedCutPlan") or directing_plan.get("cutPlan")
    plan_cut_pairs = _cut_pair_list(plan_cut_plan)
    expected_cut_pairs = [(scene_ids[idx], scene_ids[idx + 1]) for idx in range(required_cuts)]
    if plan_cut_pairs != expected_cut_pairs:
        return _check("fail", "editorialDirection directing plan motivatedCutPlan must match manifest adjacent cuts")
    for idx, cut in enumerate(cut_plan[:required_cuts]):
        if not isinstance(cut, dict):
            return _check("fail", f"editorialDirection.motivatedCutPlan[{idx}] must be an object")
        plan_cut = plan_cut_plan[idx] if isinstance(plan_cut_plan, list) and idx < len(plan_cut_plan) else None
        if not isinstance(plan_cut, dict):
            return _check("fail", "editorialDirection directing plan motivatedCutPlan must match manifest fields")
        cut_mismatch = _dict_key_mismatch(
            cut,
            plan_cut,
            (
                "fromSceneId",
                "toSceneId",
                "cutAtSec",
                "cutReason",
                "visibleContinuityBridge",
                "newInformationRevealed",
                "actionContinuesAcrossCut",
                "unmotivatedHoldSec",
            ),
        )
        if cut_mismatch:
            return _check("fail", f"editorialDirection directing plan motivatedCutPlan must match manifest fields: {cut_mismatch}")
        expected_from = scene_ids[idx]
        expected_to = scene_ids[idx + 1]
        if str(cut.get("fromSceneId") or "").strip() != expected_from:
            return _check("fail", "editorialDirection cut fromSceneId must match manifest scene order")
        if str(cut.get("toSceneId") or "").strip() != expected_to:
            return _check("fail", "editorialDirection cut toSceneId must match manifest scene order")
        cut_at = _optional_float(cut.get("cutAtSec"), default=-1.0)
        expected_cut_at = timeline.get(expected_from, {}).get("end", -1.0)
        if cut_at < 0:
            return _check("fail", "editorialDirection motivated cuts must include cutAtSec")
        if expected_cut_at >= 0 and abs(cut_at - expected_cut_at) > 0.35:
            return _check("fail", "editorialDirection cutAtSec must match the manifest scene boundary within 0.35s")
        reason = str(cut.get("cutReason") or cut.get("reason") or "").strip()
        if reason not in EDITORIAL_DIRECTION_CUT_REASONS:
            return _check("fail", f"editorialDirection cutReason {reason!r} is not allowed")
        has_bridge = (
            cut.get("visibleContinuityBridge") is True
            or cut.get("newInformationRevealed") is True
            or cut.get("actionContinuesAcrossCut") is True
        )
        if not has_bridge:
            return _check("fail", "editorialDirection cuts need visible continuity, new information, or action carry-through")
        if _optional_float(cut.get("unmotivatedHoldSec"), default=0.0) > 0.0:
            return _check("fail", "editorialDirection unmotivated hold must be 0")

    audio_binding = contract.get("audioVisualBinding")
    if not isinstance(audio_binding, dict):
        return _check("fail", "editorialDirection.audioVisualBinding object is required")
    if audio_binding.get("everyCueBoundToVisibleEvent") is not True:
        return _check("fail", "editorialDirection every audio/edit cue must bind to a visible source event")
    if audio_binding.get("unrelatedAudioCues") is True:
        return _check("fail", "editorialDirection unrelated audio cues are forbidden")
    if _optional_float(audio_binding.get("maxSyncOffsetSec"), default=99.0) > 0.20:
        return _check("fail", "editorialDirection audio cue sync offset must be <= 0.20s")
    if _optional_float(audio_binding.get("minimumSfxCueCount"), default=0.0) > 0.0:
        return _check("fail", "editorialDirection must not use SFX count as a quality floor")
    cues = audio_binding.get("cues") or []
    if not isinstance(cues, list):
        return _check("fail", "editorialDirection.audioVisualBinding.cues must be a list")
    plan_audio_cues = directing_plan.get("audioCueSheet") or []
    if not isinstance(plan_audio_cues, list):
        return _check("fail", "editorialDirection directing plan audioCueSheet must be a list")
    if len(plan_audio_cues) != len(cues):
        return _check("fail", "editorialDirection directing plan audioCueSheet must match manifest cues")
    max_sfx = _optional_float(audio_binding.get("maxSfxCueCount"), default=6.0)
    sfx_count = 0
    for idx, cue in enumerate(cues):
        if not isinstance(cue, dict):
            return _check("fail", f"editorialDirection.audioVisualBinding.cues[{idx}] must be an object")
        plan_cue = plan_audio_cues[idx] if idx < len(plan_audio_cues) else None
        if not isinstance(plan_cue, dict):
            return _check("fail", "editorialDirection directing plan audioCueSheet must match manifest cues")
        cue_mismatch = _dict_key_mismatch(
            cue,
            plan_cue,
            (
                "type",
                "kind",
                "sceneId",
                "startSec",
                "bindingMode",
                "sourceEvent",
                "syncOffsetSec",
                "assetPath",
                "auditOperationId",
                "decorativeOnly",
            ),
            ignore_missing=True,
        )
        if cue_mismatch:
            return _check("fail", f"editorialDirection directing plan audioCueSheet must match manifest cues: {cue_mismatch}")
        cue_type = _normalize_text(str(cue.get("type") or cue.get("kind") or ""))
        if cue_type in {"sfx", "foley", "transition-hit"}:
            sfx_count += 1
            if str(cue.get("sceneId") or "").strip() not in scene_ids:
                return _check("fail", "editorialDirection SFX/foley/transition cue must bind to a manifest sceneId")
            if _optional_float(cue.get("startSec"), default=-1.0) < 0:
                return _check("fail", "editorialDirection SFX/foley/transition cue must include startSec")
            asset_path = str(cue.get("assetPath") or "").strip()
            audit_operation_id = str(cue.get("auditOperationId") or "").strip()
            if not asset_path and not audit_operation_id:
                return _check("fail", "editorialDirection SFX/foley/transition cue must include assetPath or auditOperationId")
            if asset_path and not _resolve_artifact(root, asset_path).exists():
                return _check("fail", f"editorialDirection audio cue asset missing: {asset_path}")
        mode = str(cue.get("bindingMode") or "").strip()
        if mode not in EDITORIAL_DIRECTION_AUDIO_BINDING_MODES:
            return _check("fail", f"editorialDirection audio binding mode {mode!r} is not allowed")
        if cue.get("decorativeOnly") is True:
            return _check("fail", "editorialDirection decorative-only audio cues are forbidden")
        if cue_type in {"sfx", "foley", "transition-hit"} and len(str(cue.get("sourceEvent") or "").strip()) < 8:
            return _check("fail", "editorialDirection SFX/foley/transition cue must name the visible source event")
        if abs(_optional_float(cue.get("syncOffsetSec"), default=0.0)) > 0.20:
            return _check("fail", "editorialDirection audio cue syncOffsetSec must stay within +/-0.20s")
    if sfx_count > max_sfx:
        return _check("fail", "editorialDirection uses too many SFX cues for a restrained short-form edit")

    captions = contract.get("captionPerformance")
    if not isinstance(captions, dict):
        return _check("fail", "editorialDirection.captionPerformance object is required")
    if captions.get("notTtsDuplicate") is not True:
        return _check("fail", "editorialDirection captions must not merely duplicate TTS")
    if captions.get("timelineReviewed") is not True:
        return _check("fail", "editorialDirection caption timeline review is required")
    if captions.get("safeZoneReviewed") is not True:
        return _check("fail", "editorialDirection caption safe-zone review is required")
    if captions.get("subjectOcclusion") is True:
        return _check("fail", "editorialDirection captions must not occlude the subject/action")
    if captions.get("captionExplainsMissingVisual") is True:
        return _check("fail", "editorialDirection captions cannot explain a visual event the source does not show")
    if _optional_float(captions.get("maxLines"), default=99.0) > 2:
        return _check("fail", "editorialDirection captions.maxLines must be <= 2")
    if _optional_float(captions.get("maxCharsPerCaption"), default=99.0) > 24:
        return _check("fail", "editorialDirection captions.maxCharsPerCaption must be <= 24")
    caption_sync_error = _check_caption_tts_timeline(captions, directing_plan, scenes)
    if caption_sync_error:
        return _check("fail", caption_sync_error)

    continuity = contract.get("continuityMap")
    if not isinstance(continuity, dict):
        return _check("fail", "editorialDirection.continuityMap object is required")
    slots = set(_string_list(continuity.get("continuitySlots")))
    missing_slots = sorted(EDITORIAL_DIRECTION_CONTINUITY_SLOTS - slots)
    if missing_slots:
        return _check("fail", "editorialDirection continuityMap missing slots: " + ", ".join(missing_slots))
    if _optional_float(continuity.get("adjacentContinuityPassRatio"), default=0.0) < 0.80:
        return _check("fail", "editorialDirection adjacent continuity pass ratio must be >= 0.80")
    for flag in ("primarySubjectIdentityDrift", "primarySubjectScaleJump", "unexplainedCameraWorldJump"):
        if continuity.get(flag) is True:
            return _check("fail", f"editorialDirection continuityMap.{flag} must be false")

    restraint = contract.get("restraintMode")
    if not isinstance(restraint, dict):
        return _check("fail", "editorialDirection.restraintMode object is required")
    for flag in ("effectsAreOptional", "effectCountIsNotQuality", "noGeneratedStickerPresetSpray"):
        if restraint.get(flag) is not True:
            return _check("fail", f"editorialDirection.restraintMode.{flag} must be true")
    if restraint.get("symbolCuesDefault") is not False:
        return _check("fail", "editorialDirection symbol cues must not be the default edit language")

    comparison = contract.get("referenceComparison")
    if not isinstance(comparison, dict):
        return _check("fail", "editorialDirection.referenceComparison object is required")
    if _optional_float(comparison.get("comparedAgainstExternalReferences"), default=0.0) < 2.0:
        return _check("fail", "editorialDirection must compare against at least two external references")
    if comparison.get("noHudAbReviewed") is not True:
        return _check("fail", "editorialDirection requires no-HUD/no-effect A/B review")
    if comparison.get("editImprovesComprehensionOverNoHud") is not True:
        return _check("fail", "editorialDirection edit must improve comprehension over the no-HUD baseline")

    return _check("pass", "editorial direction binds shot intent, cuts, captions, audio, continuity, restraint, and reference comparison")


def _is_clean_editorial_handoff(contract: dict[str, Any]) -> bool:
    edit_model = contract.get("editModel") if isinstance(contract.get("editModel"), dict) else {}
    effect_pass = contract.get("effectPass") if isinstance(contract.get("effectPass"), dict) else {}
    return (
        edit_model.get("cleanEditorialMode") is True
        and edit_model.get("generatedEffectLayersAllowed") is False
        and edit_model.get("nativeCapCutEffectsRequired") is False
        and effect_pass.get("usesNativeCapCutEffects") is False
        and effect_pass.get("generatedVisualEffectsDisabled") is True
        and _optional_float(effect_pass.get("effectTrackCount"), default=-1.0) == 0
    )


def _check_capcut_handoff(contract: dict[str, Any], root: Path) -> dict[str, str]:
    if contract.get("required") is not True:
        return _check("fail", "capcutHandoff.required must be true")
    if contract.get("draftRequired") is not True:
        return _check("fail", "CapCut draft handoff is required for golden/reference post-edit candidates")
    if contract.get("ffmpegOnlyAllowed") is not False:
        return _check("fail", "FFmpeg-only final claims are forbidden; route through CapCut draft handoff")

    mode = str(contract.get("pipelineMode") or "").strip()
    if mode not in {"capcut-draft-first", "capcut-review-handoff"}:
        return _check("fail", "capcutHandoff.pipelineMode must be capcut-draft-first or capcut-review-handoff")
    if contract.get("capcutIsPrimaryEditSurface") is not True:
        return _check("fail", "CapCut must be declared as the primary edit surface")
    if contract.get("ffmpegPreviewOnly") is not True:
        return _check("fail", "FFmpeg render is preview-only until CapCut export review")
    if contract.get("manualExportRequired") is not True:
        return _check("fail", "CapCut manual/operator export must be required before upload")
    if contract.get("humanReviewBeforeUpload") is not True:
        return _check("fail", "CapCut export needs human review before upload")
    if contract.get("editableTextAndTiming") is not True:
        return _check("fail", "CapCut handoff must keep text/timing editable")
    if contract.get("motionDesignedEditElements") is not True:
        return _check("fail", "CapCut handoff must use motion-designed edit elements, not raw debug overlays")
    if contract.get("topicSpecificCriteriaInGlobalGate") is True:
        return _check("fail", "CapCut handoff gate must not use topic-specific criteria")

    basis = _string_list(contract.get("referenceBasis") or contract.get("webReferenceBasis"))
    basis_text = _normalize_text(" ".join(basis))
    missing_basis = [term for term in CAPCUT_REFERENCE_TERMS if term not in basis_text]
    if len(basis) < 5 or missing_basis:
        return _check(
            "fail",
            "capcutHandoff.referenceBasis must include CapCut keyframes, captions, Shorts timeline, TikTok Top Ads, easing, and VectCutAPI references",
        )

    automation = contract.get("automationSurface")
    if not isinstance(automation, dict):
        return _check("fail", "capcutHandoff.automationSurface object is required")
    tool_text = _normalize_text(f"{automation.get('tool') or ''} {automation.get('automationTool') or ''}")
    if not any(term in tool_text for term in CAPCUT_AUTOMATION_TOOL_TERMS):
        return _check("fail", "capcutHandoff.automationSurface.tool must be VectCutAPI, pyJianYingDraft, or CapCut draft automation")
    target_editor = _normalize_text(str(automation.get("targetEditor") or ""))
    if "capcut" not in target_editor:
        return _check("fail", "capcutHandoff.automationSurface.targetEditor must be CapCut")
    draft_format = _normalize_text(str(automation.get("draftFormat") or ""))
    if "draft_content.json" not in draft_format:
        return _check("fail", "capcutHandoff.automationSurface.draftFormat must be draft_content.json")
    automation_flags = {
        "localDraftRootExists": "local CapCut draft root must be verified",
        "capcutInstallVerified": "CapCut install must be verified before draft handoff",
        "finalExportByOperator": "final CapCut export must be operator-owned",
        "ffmpegPreviewOnly": "FFmpeg must remain preview-only in the CapCut automation surface",
    }
    for flag, message in automation_flags.items():
        if automation.get(flag) is not True:
            return _check("fail", f"capcutHandoff.automationSurface.{flag}: {message}")

    edit_model = contract.get("editModel")
    if not isinstance(edit_model, dict):
        return _check("fail", "capcutHandoff.editModel object is required")
    for flag in (
        "multitrackTimeline",
        "editableTextAndTiming",
        "editableCaptions",
        "editableAudioLevels",
        "editableMotionElements",
    ):
        if edit_model.get(flag) is not True:
            return _check("fail", f"capcutHandoff.editModel.{flag} must be true")
    if edit_model.get("extraTextCalloutsAllowed") is not False:
        return _check("fail", "capcutHandoff.editModel.extraTextCalloutsAllowed must be false")

    effect_pass = contract.get("effectPass")
    if not isinstance(effect_pass, dict):
        return _check("fail", "capcutHandoff.effectPass object is required")
    if effect_pass.get("required") is not True:
        return _check("fail", "capcutHandoff.effectPass.required must be true")
    clean_effect_mode = (
        str(effect_pass.get("mode") or "") == "clean-editorial-no-canned-effects"
        or effect_pass.get("nativeEffectsDisabled") is True
    )
    if clean_effect_mode:
        if effect_pass.get("usesNativeCapCutEffects") is not False:
            return _check("fail", "capcutHandoff.effectPass.usesNativeCapCutEffects must be false in clean editorial mode")
        for flag in (
            "nativeEffectsDisabled",
            "generatedVisualEffectsDisabled",
            "forbidUnanchoredEffects",
            "forbidPresetSpray",
            "cannedEffectsRejected",
        ):
            if effect_pass.get(flag) is not True:
                return _check("fail", f"capcutHandoff.effectPass.{flag} must be true")
        if edit_model.get("nativeCapCutEffectsRequired") is not False:
            return _check("fail", "capcutHandoff.editModel.nativeCapCutEffectsRequired must be false in clean editorial mode")
        if edit_model.get("generatedEffectLayersAllowed") is not False:
            return _check("fail", "capcutHandoff.editModel.generatedEffectLayersAllowed must be false")
        if edit_model.get("cleanEditorialMode") is not True:
            return _check("fail", "capcutHandoff.editModel.cleanEditorialMode must be true")
        if _optional_float(effect_pass.get("effectTrackCount"), default=0.0) != 0.0:
            return _check("fail", "capcutHandoff.effectPass.effectTrackCount must be 0 in clean editorial mode")
        if _optional_float(effect_pass.get("maxEffectTracks"), default=0.0) != 0.0:
            return _check("fail", "capcutHandoff.effectPass.maxEffectTracks must be 0 in clean editorial mode")
    else:
        if edit_model.get("editElementsUseNonTextVisuals") is not True:
            return _check("fail", "capcutHandoff.editModel.editElementsUseNonTextVisuals must be true")
        if edit_model.get("nativeCapCutEffectsRequired") is not True:
            return _check("fail", "capcutHandoff.editModel.nativeCapCutEffectsRequired must be true")
        for flag in (
            "usesNativeCapCutEffects",
            "forbidPngOnlyClaim",
            "manualPresetReviewRequired",
            "visualBindingRequired",
            "forbidUnanchoredEffects",
            "forbidPresetSpray",
        ):
            if effect_pass.get(flag) is not True:
                return _check("fail", f"capcutHandoff.effectPass.{flag} must be true")
        min_effect_tracks = _optional_float(effect_pass.get("minEffectTracks"), default=2.0)
        if min_effect_tracks < 2.0:
            return _check("fail", "capcutHandoff.effectPass.minEffectTracks must be >= 2")
        effect_track_count = _optional_float(effect_pass.get("effectTrackCount"), default=0.0)
        if effect_track_count < min_effect_tracks:
            return _check("fail", "capcutHandoff.effectPass.effectTrackCount must satisfy minEffectTracks")
        max_effect_tracks = _optional_float(effect_pass.get("maxEffectTracks"), default=8.0)
        if max_effect_tracks < min_effect_tracks:
            return _check("fail", "capcutHandoff.effectPass.maxEffectTracks must be >= minEffectTracks")
        if effect_track_count > max_effect_tracks:
            return _check("fail", "capcutHandoff.effectPass.effectTrackCount must not exceed maxEffectTracks")
        families = {_normalize_text(item) for item in _string_list(effect_pass.get("requiredFamilies"))}
        if len(families) < 2:
            return _check("fail", "capcutHandoff.effectPass.requiredFamilies must list anchored effect families")
        disallowed = {_normalize_text(item) for item in _string_list(effect_pass.get("disallowedUnanchoredFamilies"))}
        if not {"atmosphere-light", "distortion", "scan-context"}.issubset(disallowed):
            return _check("fail", "capcutHandoff.effectPass.disallowedUnanchoredFamilies must block atmosphere/distortion/scan preset spray")
        if families & disallowed:
            return _check("fail", "capcutHandoff.effectPass.requiredFamilies must not include disallowed unanchored families")
        if len(_string_list(effect_pass.get("anchoredCueRoles"))) < 1:
            return _check("fail", "capcutHandoff.effectPass.anchoredCueRoles must identify the visible cue roles")
        if len(_string_list(effect_pass.get("candidateEffects"))) < 2:
            return _check("fail", "capcutHandoff.effectPass.candidateEffects must list reusable CapCut effect presets")

    motion = contract.get("motionDesign")
    if not isinstance(motion, dict):
        return _check("fail", "capcutHandoff.motionDesign object is required")
    for flag in ("usesKeyframes", "usesEasing", "usesSpeedCurvesOrEasing", "noRawDrawboxDrawtextFinal"):
        if motion.get(flag) is not True:
            return _check("fail", f"capcutHandoff.motionDesign.{flag} must be true")
    if _optional_float(motion.get("minKeyframedElements"), default=0.0) < 2.0:
        return _check("fail", "capcutHandoff.motionDesign.minKeyframedElements must be >= 2")
    if _optional_float(motion.get("motionDurationMsMin"), default=0.0) < 83.0:
        return _check("fail", "capcutHandoff.motionDesign.motionDurationMsMin must be >= 83")
    if _optional_float(motion.get("motionDurationMsMax"), default=9999.0) > 400.0:
        return _check("fail", "capcutHandoff.motionDesign.motionDurationMsMax must be <= 400")
    editorial_motion = motion.get("editorialMotionPass")
    if not isinstance(editorial_motion, dict):
        return _check("fail", "capcutHandoff.motionDesign.editorialMotionPass object is required")
    if editorial_motion.get("required") is not True:
        return _check("fail", "capcutHandoff.motionDesign.editorialMotionPass.required must be true")
    if editorial_motion.get("mode") != "capcut-scene-directed-motion":
        return _check("fail", "capcutHandoff.motionDesign.editorialMotionPass.mode must be capcut-scene-directed-motion")
    for flag in ("sceneDirectedMotion", "capcutKeyframesNotPreviewOnly", "captionAnimationDesigned"):
        if editorial_motion.get(flag) is not True:
            return _check("fail", f"capcutHandoff.motionDesign.editorialMotionPass.{flag} must be true")
    scene_motion_count = _optional_float(editorial_motion.get("sceneMotionProfileCount"), default=0.0)
    if scene_motion_count < _optional_float(motion.get("minKeyframedElements"), default=2.0):
        return _check("fail", "capcutHandoff.motionDesign.editorialMotionPass.sceneMotionProfileCount must cover keyframed elements")
    if _optional_float(editorial_motion.get("minKeyframesPerScene"), default=0.0) < 6.0:
        return _check("fail", "capcutHandoff.motionDesign.editorialMotionPass.minKeyframesPerScene must be >= 6")
    if _optional_float(editorial_motion.get("totalKeyframeCount"), default=0.0) < scene_motion_count * 6.0:
        return _check("fail", "capcutHandoff.motionDesign.editorialMotionPass.totalKeyframeCount is too low")
    if _optional_float(editorial_motion.get("minVisibleScaleDelta"), default=0.0) < 0.05:
        return _check("fail", "capcutHandoff.motionDesign.editorialMotionPass.minVisibleScaleDelta must be >= 0.05")
    if _optional_float(editorial_motion.get("maxUnmotivatedMotionSec"), default=99.0) > 0.0:
        return _check("fail", "capcutHandoff.motionDesign.editorialMotionPass.maxUnmotivatedMotionSec must be 0")
    motion_profiles = editorial_motion.get("motionProfiles")
    if not isinstance(motion_profiles, list) or len(motion_profiles) < int(scene_motion_count):
        return _check("fail", "capcutHandoff.motionDesign.editorialMotionPass.motionProfiles must list every motion profile")

    media = contract.get("mediaLinked")
    if not isinstance(media, dict):
        return _check("fail", "capcutHandoff.mediaLinked object is required")
    media_required = set(CAPCUT_MEDIA_TRACK_FLAGS)
    if clean_effect_mode:
        media_required.discard("effectTracks")
        media_required.discard("editElementTracks")
    missing_tracks = sorted(flag for flag in media_required if media.get(flag) is not True)
    if missing_tracks:
        return _check("fail", f"CapCut draft must link required media track: {missing_tracks[0]}")
    if media.get("sfxTracks") is False and not clean_effect_mode:
        return _check("fail", "CapCut handoff must not explicitly drop SFX tracks")

    required_paths = {
        "draftPath": contract.get("draftPath"),
        "draftContentPath": contract.get("draftContentPath"),
        "draftAuditPath": contract.get("draftAuditPath"),
    }
    for key, raw_path in required_paths.items():
        path = str(raw_path or "").strip()
        if not path:
            return _check("fail", f"capcutHandoff.{key} is required")
        if not _resolve_artifact(root, path).exists():
            return _check("fail", f"CapCut handoff artifact missing: {path}")

    draft_content, draft_content_error = _read_json_object(
        root,
        str(required_paths["draftContentPath"]),
        "capcutHandoff.draftContentPath",
    )
    if draft_content_error:
        return _check("fail", draft_content_error)
    draft_audit, draft_audit_error = _read_json_object(
        root,
        str(required_paths["draftAuditPath"]),
        "capcutHandoff.draftAuditPath",
        schema=CAPCUT_DRAFT_AUDIT_SCHEMA,
    )
    if draft_audit_error:
        return _check("fail", draft_audit_error)
    if not isinstance(draft_audit.get("operations"), list):
        return _check("fail", "capcutHandoff.draftAuditPath must include operations list")
    draft_summary, draft_summary_error = _capcut_draft_summary(draft_content)
    if draft_summary_error:
        return _check("fail", draft_summary_error)
    track_counts = draft_audit.get("trackCounts") if isinstance(draft_audit.get("trackCounts"), dict) else {}
    if not track_counts:
        return _check("fail", "capcutHandoff draft audit must include trackCounts")
    segment_counts = draft_summary["segmentCounts"]
    for track_type in ("video", "audio", "text"):
        audit_count = _optional_float(track_counts.get(track_type), default=-1.0)
        if audit_count < 0:
            return _check("fail", f"capcutHandoff draft audit trackCounts.{track_type} is required")
        if abs(audit_count - segment_counts.get(track_type, 0)) > 0.01:
            return _check("fail", "capcutHandoff draft audit trackCounts must match draft_content segment counts")
    if "effect" in track_counts:
        audit_effect_count = _optional_float(track_counts.get("effect"), default=-1.0)
        if abs(audit_effect_count - segment_counts.get("effect", 0)) > 0.01:
            return _check("fail", "capcutHandoff draft audit trackCounts must match draft_content segment counts")
    elif segment_counts.get("effect", 0) > 0:
        return _check("fail", "capcutHandoff draft audit trackCounts.effect is required when draft_content has effect segments")
    if media.get("sourceVideoTracks") is True and segment_counts.get("video", 0) <= 0:
        return _check("fail", "capcutHandoff mediaLinked.sourceVideoTracks must be backed by draft_content video segments")
    required_audio_segments = int(media.get("ttsTracks") is True) + int(media.get("bgmTrack") is True)
    if required_audio_segments and segment_counts.get("audio", 0) < required_audio_segments:
        return _check("fail", "capcutHandoff mediaLinked audio tracks must be backed by draft_content audio segments")
    if media.get("captionTracks") is True and segment_counts.get("text", 0) <= 0:
        return _check("fail", "capcutHandoff mediaLinked.captionTracks must be backed by draft_content text segments")
    expected_keyframes = _optional_float(editorial_motion.get("totalKeyframeCount"), default=0.0)
    draft_keyframes = _optional_float(draft_summary.get("videoKeyframes"), default=0.0)
    if draft_keyframes < expected_keyframes:
        return _check("fail", "capcutHandoff draft_content keyframe count must satisfy motionDesign contract")
    actual_keyframe_value = draft_audit.get("actualVideoKeyframes")
    if actual_keyframe_value is None:
        actual_keyframe_value = draft_audit.get("totalMotionKeyframes")
    actual_keyframes = _optional_float(actual_keyframe_value, default=0.0)
    if abs(actual_keyframes - draft_keyframes) > 0.01:
        return _check("fail", "capcutHandoff draft audit keyframe count must match draft_content video keyframes")
    if actual_keyframes < expected_keyframes:
        return _check("fail", "capcutHandoff draft audit keyframe count must satisfy motionDesign contract")
    operations = draft_audit.get("operations") if isinstance(draft_audit.get("operations"), list) else []
    ok_operations = [
        operation
        for operation in operations
        if isinstance(operation, dict) and operation.get("ok") is True
    ]
    ok_operation_kinds = {_normalize_text(str(operation.get("kind") or "")) for operation in ok_operations}
    source_motion_ops = [
        operation for operation in ok_operations if _normalize_text(str(operation.get("kind") or "")) == "sourcemotionprofile"
    ]
    if len(source_motion_ops) < int(scene_motion_count):
        return _check("fail", "capcutHandoff draft audit sourceMotionProfile operations must cover scene motion profiles")
    if media.get("ttsTracks") is True and "tts" not in ok_operation_kinds:
        return _check("fail", "capcutHandoff mediaLinked.ttsTracks must be backed by draft audit tts operation")
    if media.get("bgmTrack") is True and "bgm" not in ok_operation_kinds:
        return _check("fail", "capcutHandoff mediaLinked.bgmTrack must be backed by draft audit bgm operation")
    if media.get("captionTracks") is True and "caption" not in ok_operation_kinds:
        return _check("fail", "capcutHandoff mediaLinked.captionTracks must be backed by draft audit caption operation")
    if clean_effect_mode:
        if _optional_float(draft_audit.get("effectTracks"), default=0.0) != 0.0:
            return _check("fail", "capcutHandoff clean editorial audit must have zero effectTracks")
        if _optional_float(draft_audit.get("editElementVisualLayers"), default=0.0) != 0.0:
            return _check("fail", "capcutHandoff clean editorial audit must have zero editElementVisualLayers")
    else:
        if media.get("effectTracks") is True and _optional_float(draft_audit.get("effectTracks"), default=0.0) <= 0.0:
            return _check("fail", "capcutHandoff mediaLinked.effectTracks must be backed by draft audit effectTracks")
        if media.get("editElementTracks") is True and _optional_float(draft_audit.get("editElementVisualLayers"), default=0.0) <= 0.0:
            return _check("fail", "capcutHandoff mediaLinked.editElementTracks must be backed by draft audit editElementVisualLayers")
    if media.get("sfxTracks") is True and _optional_float(draft_audit.get("sfxTracks"), default=0.0) <= 0.0:
        return _check("fail", "capcutHandoff mediaLinked.sfxTracks must be backed by draft audit sfxTracks")
    if media.get("sfxTracks") is True and "sfxbeat" not in ok_operation_kinds:
        return _check("fail", "capcutHandoff mediaLinked.sfxTracks must be backed by draft audit sfxBeat operation")

    status = str(contract.get("roundTripStatus") or "").strip()
    if status not in {"draft-created", "operator-review-required", "export-reviewed"}:
        return _check("fail", "capcutHandoff.roundTripStatus must show a created/reviewable CapCut draft")

    return _check("pass", f"CapCut handoff required via {mode}; FFmpeg is preview-only with draft audit evidence")


def _derive_post_edit_score(
    manifest: dict[str, Any],
    contract: dict[str, Any],
    scenes: list[Any],
) -> tuple[dict[str, Any], str]:
    source_take_quality = _average_scene_dimension_score(scenes, "sourceQualityRubric", "sourceTakeQuality")
    if source_take_quality is None:
        return {}, "gate-derived post-edit score requires sourceQualityRubric dimensions for every scene"
    source_sequence = manifest.get("sourceSequenceContinuity") or manifest.get("sourceContinuityRubric")
    source_sequence_continuity = _average_contract_dimension_score(source_sequence)
    if source_sequence_continuity is None:
        return {}, "gate-derived post-edit score requires sourceSequenceContinuity dimensions"

    hook = contract.get("hook") if isinstance(contract.get("hook"), dict) else {}
    captions = contract.get("captions") if isinstance(contract.get("captions"), dict) else {}
    layout_hud = contract.get("layoutHud") or contract.get("layoutAndHud") or {}
    rhythm = contract.get("rhythm") if isinstance(contract.get("rhythm"), dict) else {}
    audio = contract.get("audio") if isinstance(contract.get("audio"), dict) else {}
    color = contract.get("color") if isinstance(contract.get("color"), dict) else {}
    payoff = contract.get("payoff") if isinstance(contract.get("payoff"), dict) else {}
    editorial = contract.get("editorialDirection") if isinstance(contract.get("editorialDirection"), dict) else {}
    comparison = editorial.get("referenceComparison") if isinstance(editorial.get("referenceComparison"), dict) else {}
    opening_audio = manifest.get("openingAudioContinuity") if isinstance(manifest.get("openingAudioContinuity"), dict) else {}
    tts_alignment = opening_audio.get("ttsAlignment") if isinstance(opening_audio.get("ttsAlignment"), dict) else {}
    voice_quality = tts_alignment.get("voiceQuality") if isinstance(tts_alignment.get("voiceQuality"), dict) else {}

    hook_ok = (
        hook.get("firstThreeSecHasPrimaryVisual") is True
        and hook.get("firstThreeSecHasMotionOrAction") is True
        and hook.get("firstThreeSecHasAudioBed") is True
        and hook.get("viewerQuestionClear") is True
        and 0.2 <= _optional_float(hook.get("firstCaptionStartSec"), default=99.0) <= 1.25
    )
    payoff_ok = (
        payoff.get("finalAnswerResolved") is True
        and payoff.get("noNewInfoInLastSecond") is True
        and _optional_float(payoff.get("finalVisualHoldSec"), default=0.0) >= 1.0
        and _optional_float(payoff.get("finalAudioTailSec"), default=0.0) >= 0.7
    )
    copy_tts_ok = (
        tts_alignment.get("timelineReviewed") is True
        and voice_quality.get("voiceNaturalnessReviewed") is True
        and voice_quality.get("perceivedRoboticOrSapi") is False
        and tts_alignment.get("captionsDoNotAdvanceBeforeVoice") is True
    )
    caption_ok = (
        captions.get("stableSafeZone") is True
        and captions.get("mainSubjectOcclusion") is not True
        and captions.get("timelineReviewed") is True
        and _optional_float(captions.get("maxScreenAreaRatio"), default=1.0) <= 0.18
        and isinstance(layout_hud, dict)
    )
    rhythm_ok = (
        rhythm.get("actionBeatsAlignedToCuts") is True
        and rhythm.get("noHardJumpWithoutBridge") is True
        and _optional_float(rhythm.get("minShotHoldSec"), default=0.0) >= 1.1
        and _optional_float(rhythm.get("maxDeadAirSec"), default=99.0) <= 0.65
    )
    audio_ok = (
        audio.get("duckingApplied") is True
        and audio.get("bgmContinuous") is True
        and audio.get("sourceAmbienceOrFoleyPresent") is True
        and audio.get("speechBgmSeparationReviewed") is True
    )
    color_ok = (
        color.get("colorGradeAppliedToAllScenes") is True
        and color.get("noUnmotivatedFlashes") is True
        and _optional_float(color.get("maxLumaDelta"), default=99.0) <= 0.30
        and _optional_float(color.get("maxSaturationDelta"), default=99.0) <= 0.30
    )
    reference_ok = (
        _optional_float(comparison.get("comparedAgainstExternalReferences"), default=0.0) >= 2.0
        and comparison.get("noHudAbReviewed") is True
        and comparison.get("editImprovesComprehensionOverNoHud") is True
    )

    dimensions = {
        "sourceTakeQuality": _round_score(source_take_quality),
        "sourceSequenceContinuity": _round_score(source_sequence_continuity),
        "hookClarity": 76.0 if hook_ok else 0.0,
        "storyPayoff": 76.0 if payoff_ok else 0.0,
        "copyTtsQuality": 78.0 if copy_tts_ok else 0.0,
        "captionAccessibility": 73.0 if caption_ok else 0.0,
        "editRhythm": 72.0 if rhythm_ok else 0.0,
        "audioMix": 78.0 if audio_ok else 0.0,
        "colorTechnicalQuality": 70.0 if color_ok else 0.0,
        "platformReferenceFit": 74.0 if reference_ok else 0.0,
    }
    overall = _round_score(sum(dimensions.values()) / len(POST_EDIT_SCORE_DIMENSIONS))
    return {"overall": overall, "dimensions": dimensions}, ""


def _check_post_edit_score_evidence(
    contract: dict[str, Any],
    root: Path,
    manifest_score: dict[str, Any],
    derived_score: dict[str, Any],
    *,
    min_overall: float,
    min_dimension: float,
) -> dict[str, str]:
    scoring_path = str(contract.get("scoringReviewPath") or "").strip()
    if not scoring_path:
        return _check("fail", "postEditGoldenReference.scoringReviewPath is required")
    scoring, scoring_error = _read_json_object(
        root,
        scoring_path,
        "postEditGoldenReference.scoringReviewPath",
        schema=POST_EDIT_SCORE_SCHEMA,
    )
    if scoring_error:
        return _check("fail", scoring_error)
    if scoring.get("status") not in {"pass", "reviewed-pass"}:
        return _check("fail", "post-edit scoring evidence must record pass/reviewed-pass status")
    computed = scoring.get("computedScore")
    if not isinstance(computed, dict):
        return _check("fail", "post-edit scoring evidence must include computedScore")
    computed_overall = _optional_float(computed.get("overall"), default=-1.0)
    manifest_overall = _optional_float(manifest_score.get("overall"), default=-1.0)
    derived_overall = _optional_float(derived_score.get("overall"), default=-1.0)
    if computed_overall < min_overall:
        return _check("fail", f"computed post-edit score {computed_overall:.1f} is below minimum {min_overall:.1f}")
    if abs(computed_overall - manifest_overall) > 0.01:
        return _check("fail", "manifest post-edit score must match computed scoring evidence")
    if derived_overall < min_overall:
        return _check("fail", f"gate-derived post-edit score {derived_overall:.1f} is below minimum {min_overall:.1f}")
    if abs(computed_overall - derived_overall) > 0.01:
        return _check("fail", "computed scoring evidence must match gate-derived scoring result")
    if abs(manifest_overall - derived_overall) > 0.01:
        return _check("fail", "manifest post-edit score must match gate-derived scoring result")
    dimension_error = _score_dimension_error(
        computed.get("dimensions"),
        POST_EDIT_SCORE_DIMENSIONS,
        min_dimension,
        "postEditGoldenReference.scoringReviewPath.computedScore",
    )
    if dimension_error:
        return _check("fail", dimension_error)
    manifest_dimensions = manifest_score.get("dimensions") if isinstance(manifest_score.get("dimensions"), dict) else {}
    computed_dimensions = computed.get("dimensions") if isinstance(computed.get("dimensions"), dict) else {}
    derived_dimensions = derived_score.get("dimensions") if isinstance(derived_score.get("dimensions"), dict) else {}
    if _score_dimension_mismatch(computed_dimensions, manifest_dimensions, POST_EDIT_SCORE_DIMENSIONS):
        return _check("fail", "manifest post-edit score dimensions must match computed scoring evidence")
    if _score_dimension_mismatch(computed_dimensions, derived_dimensions, POST_EDIT_SCORE_DIMENSIONS):
        return _check("fail", "computed scoring evidence dimensions must match gate-derived scoring result")
    if _score_dimension_mismatch(manifest_dimensions, derived_dimensions, POST_EDIT_SCORE_DIMENSIONS):
        return _check("fail", "manifest post-edit score dimensions must match gate-derived scoring result")
    inputs = scoring.get("scoreInputs")
    if not isinstance(inputs, dict):
        return _check("fail", "post-edit scoring evidence must include scoreInputs")
    for key in ("shotIntentMap", "motivatedCutPlan", "captionPlan", "audioCueSheet", "capcutDraftAudit"):
        if inputs.get(key) is not True:
            return _check("fail", f"post-edit scoring evidence scoreInputs.{key} must be true")
    return _check("pass", "post-edit score is backed by computed scoring evidence")


def _check_external_edit_realization(
    contract: dict[str, Any],
    capcut_handoff: dict[str, Any],
    root: Path,
    *,
    clean_editorial_mode: bool,
) -> dict[str, str]:
    audit, audit_error = _capcut_audit_payload(capcut_handoff, root)
    if audit_error:
        return _check("fail", audit_error)
    active_element_count = _external_edit_element_count(contract)
    if clean_editorial_mode:
        if active_element_count > 0:
            return _check("fail", "clean editorial mode cannot claim active external edit elements")
        if _optional_float(audit.get("editElementVisualLayers"), default=0.0) != 0.0:
            return _check("fail", "clean editorial mode requires zero edit element visual layers in CapCut audit")
        if _optional_float(audit.get("effectTracks"), default=0.0) != 0.0:
            return _check("fail", "clean editorial mode requires zero effect tracks in CapCut audit")
        return _check("pass", "clean external edit plan matches CapCut audit")
    if active_element_count > 0:
        media = capcut_handoff.get("mediaLinked") if isinstance(capcut_handoff.get("mediaLinked"), dict) else {}
        audit_visual_layers = _optional_float(audit.get("editElementVisualLayers"), default=0.0)
        if media.get("editElementTracks") is not True:
            return _check("fail", "active external edit elements require capcutHandoff.mediaLinked.editElementTracks=true")
        if audit_visual_layers < active_element_count:
            return _check("fail", "active external edit elements must be realized as CapCut editElementVisualLayers")
    return _check("pass", "external edit element plan matches CapCut audit")


def _check_audio_visual_realization(
    editorial_direction: dict[str, Any],
    capcut_handoff: dict[str, Any],
    root: Path,
) -> dict[str, str]:
    audit, audit_error = _capcut_audit_payload(capcut_handoff, root)
    if audit_error:
        return _check("fail", audit_error)
    operations = audit.get("operations") if isinstance(audit.get("operations"), list) else []
    operations_by_id = {
        str(operation.get("id") or operation.get("operationId") or "").strip(): operation
        for operation in operations
        if isinstance(operation, dict) and str(operation.get("id") or operation.get("operationId") or "").strip()
    }
    cues = _nested(editorial_direction, "audioVisualBinding", "cues")
    if not isinstance(cues, list):
        return _check("fail", "editorialDirection.audioVisualBinding.cues must be a list")
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        cue_type = _normalize_text(str(cue.get("type") or cue.get("kind") or ""))
        if cue_type not in {"sfx", "foley", "transition-hit"}:
            continue
        operation_id = str(cue.get("auditOperationId") or "").strip()
        if not operation_id:
            return _check("fail", "editorialDirection SFX/foley/transition cue must include auditOperationId")
        operation = operations_by_id.get(operation_id)
        if not isinstance(operation, dict) or operation.get("ok") is not True:
            return _check("fail", f"editorialDirection audio cue audit operation missing or failed: {operation_id}")
    return _check("pass", "editorial audio/edit cues match CapCut draft audit")


def _check_external_edit_elements(
    contract: dict[str, Any],
    root: Path,
    *,
    scene_ids: list[str],
    clean_editorial_mode: bool = False,
) -> dict[str, str]:
    scene_count = len(scene_ids)
    if clean_editorial_mode and contract.get("required") is False:
        if contract.get("cleanEditorialMode") is not True:
            return _check("fail", "externalEditElements.cleanEditorialMode must be true when generated elements are disabled")
        if contract.get("generatedVisualLayersAllowed") is not False:
            return _check("fail", "externalEditElements.generatedVisualLayersAllowed must be false in clean editorial mode")
        if contract.get("generatedSfxAllowed") is not False:
            return _check("fail", "externalEditElements.generatedSfxAllowed must be false in clean editorial mode")
        if contract.get("manualExceptionOnly") is not True:
            return _check("fail", "externalEditElements.manualExceptionOnly must be true in clean editorial mode")
        if _optional_float(contract.get("visualElementCount"), default=-1.0) != 0:
            return _check("fail", "externalEditElements.visualElementCount must be 0 in clean editorial mode")
        if _optional_float(contract.get("audioCueCount"), default=-1.0) != 0:
            return _check("fail", "externalEditElements.audioCueCount must be 0 in clean editorial mode")
        reason = str(contract.get("reasonNoGeneratedExternalElements") or "").strip()
        if len(reason) < 24:
            return _check("fail", "externalEditElements.reasonNoGeneratedExternalElements must explain the clean editorial decision")
        rejection_basis = _string_list(contract.get("rejectionBasis") or contract.get("effectRejectionBasis"))
        if len(rejection_basis) < 3:
            return _check("fail", "externalEditElements.rejectionBasis must record why generated elements are rejected")
        if contract.get("topicSpecificCriteriaInGlobalGate") is True:
            return _check("fail", "external edit-elements gate must not use topic-specific criteria")
        per_scene = contract.get("perScenePlan") or []
        if not isinstance(per_scene, list) or len(per_scene) < scene_count:
            return _check("fail", "externalEditElements.perScenePlan must list each scene with a clean-mode reason")
        if _scene_id_list(per_scene) != scene_ids:
            return _check("fail", "externalEditElements.perScenePlan sceneId/order must match manifest scenes")
        for idx, scene_plan in enumerate(per_scene[:scene_count]):
            if not isinstance(scene_plan, dict):
                return _check("fail", f"externalEditElements.perScenePlan[{idx}] must be an object")
            if scene_plan.get("elements") not in ([], None):
                return _check("fail", "externalEditElements clean editorial mode forbids generated elements")
            if not str(scene_plan.get("reasonNoExternalElement") or "").strip():
                return _check(
                    "fail",
                    f"externalEditElements.perScenePlan[{idx}] needs reasonNoExternalElement in clean editorial mode",
                )
        return _check("pass", "external edit elements are disabled under clean editorial mode with recorded rejection basis")

    if contract.get("required") is not True:
        return _check("fail", "externalEditElements.required must be true")

    basis = _string_list(contract.get("referenceBasis") or contract.get("webReferenceBasis"))
    basis_text = _normalize_text(" ".join(basis))
    missing_basis = [term for term in EXTERNAL_EDIT_REFERENCE_TERMS if term not in basis_text]
    if len(basis) < 4 or missing_basis:
        return _check(
            "fail",
            "externalEditElements.referenceBasis must include YouTube Shorts, TikTok, motion continuity, and WCAG references",
        )
    if contract.get("topicSpecificCriteriaInGlobalGate") is True:
        return _check("fail", "external edit-elements gate must not use topic-specific criteria")

    purpose = contract.get("layerPurpose")
    if not isinstance(purpose, dict):
        return _check("fail", "externalEditElements.layerPurpose object is required")
    if purpose.get("editorialFunctionDeclared") is not True:
        return _check("fail", "external edit elements must declare an editorial function")
    if purpose.get("supportsNarrativeBeats") is not True:
        return _check("fail", "external edit elements must support narrative beats")
    if purpose.get("decorativeOnly") is True:
        return _check("fail", "decorative-only external edit elements are forbidden")
    if purpose.get("sourceReplacementClaim") is True:
        return _check("fail", "external edit elements cannot claim to replace weak source quality")

    declared_types = set(_string_list(contract.get("elementTypes") or contract.get("allowedElementTypes")))
    if len(declared_types) < 2:
        return _check("fail", "externalEditElements.elementTypes must declare at least two reusable element types")
    invalid_declared = sorted(declared_types - EXTERNAL_EDIT_ALLOWED_TYPES)
    if invalid_declared:
        return _check("fail", f"external edit element type is not allowed: {invalid_declared[0]}")

    safety = contract.get("safety")
    if not isinstance(safety, dict):
        return _check("fail", "externalEditElements.safety object is required")
    if safety.get("platformSafeZoneReviewed") is not True:
        return _check("fail", "external edit elements must review platform safe zones")
    if safety.get("subjectOcclusion") is True:
        return _check("fail", "external edit elements must not create subject occlusion")
    if safety.get("debugOrEditorLabels") is True:
        return _check("fail", "debug/editor labels are forbidden in external edit elements")
    if safety.get("rapidFlashes") is True:
        return _check("fail", "rapid flashes are forbidden in external edit elements")
    if safety.get("reducedMotionSafe") is not True:
        return _check("fail", "external edit elements must be reduced-motion safe")
    if safety.get("templateLook") is True:
        return _check("fail", "template-looking external edit stickers/graphics are forbidden")
    if _optional_float(safety.get("maxScreenAreaRatio"), default=1.0) > 0.14:
        return _check("fail", "external edit element screen area must stay <= 14%")
    if _optional_float(safety.get("maxOpacity"), default=1.0) > 0.78:
        return _check("fail", "external edit element opacity must stay <= 0.78")
    if _optional_float(safety.get("maxFlashPerSecond"), default=99.0) > 3.0:
        return _check("fail", "external edit elements must not flash more than 3 times per second")

    salience = contract.get("perceptualSalience")
    if not isinstance(salience, dict):
        return _check("fail", "externalEditElements.perceptualSalience object is required")
    if salience.get("recognizableSymbolRequired") is True:
        return _check("fail", "external edit gate must not require symbolic X/OK/check cues by default")
    if salience.get("semanticCueMatchesNarration") is not True:
        return _check("fail", "external edit cues must semantically match narration/caption beats")
    if salience.get("viewerCanNameCueAfterOneWatch") is not True:
        return _check("fail", "external edit cue must be nameable after one watch")
    if salience.get("sourceEventBindingRequired") is not True:
        return _check("fail", "external edit cues must require source-event binding")
    if salience.get("everyCueBoundToVisibleSourceEvent") is not True:
        return _check("fail", "external edit cues must bind to visible source events")
    if salience.get("effectCountIsNotQuality") is not True:
        return _check("fail", "external edit gate must reject effect-count inflation")
    if salience.get("symbolCuesDefault") is not False:
        return _check("fail", "external edit symbol cues must not be the default")
    min_salient_area = _optional_float(salience.get("minVisualCueScreenAreaRatio"), default=0.0)
    if min_salient_area < 0.012:
        return _check("fail", "external edit salience needs minVisualCueScreenAreaRatio >= 0.012")
    min_salient_opacity = _optional_float(salience.get("minCueOpacity"), default=0.0)
    if min_salient_opacity < 0.50:
        return _check("fail", "external edit salience needs minCueOpacity >= 0.50")

    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    plan_path = _first_artifact_path(
        evidence.get("editElementPlanPath"),
        evidence.get("editLayerPlanPath"),
        contract.get("editElementPlanPath"),
    )
    preview_path = _first_artifact_path(
        evidence.get("phonePreviewPath"),
        evidence.get("visualReviewPath"),
        evidence.get("editElementPreviewPath"),
        contract.get("phonePreviewPath"),
        contract.get("visualReviewPath"),
    )
    if not plan_path or not _resolve_artifact(root, plan_path).exists():
        return _check("fail", "external edit element plan evidence path is required")
    if not preview_path or not _resolve_artifact(root, preview_path).exists():
        return _check("fail", "external edit element phone/visual preview evidence path is required")

    per_scene = contract.get("perScenePlan") or contract.get("scenePlans")
    if not isinstance(per_scene, list):
        return _check("fail", "externalEditElements.perScenePlan must list every scene")
    if scene_count > 0 and len(per_scene) < scene_count:
        return _check("fail", "externalEditElements.perScenePlan must cover every scene")
    if _scene_id_list(per_scene) != scene_ids:
        return _check("fail", "externalEditElements.perScenePlan sceneId/order must match manifest scenes")

    used_types: set[str] = set()
    used_roles: set[str] = set()
    covered_scenes = 0
    total_elements = 0
    required_active_scenes = min(max(scene_count, 1), 2)
    for idx, scene_plan in enumerate(per_scene[: max(scene_count, len(per_scene))]):
        if not isinstance(scene_plan, dict):
            return _check("fail", f"externalEditElements.perScenePlan[{idx}] must be an object")
        elements = scene_plan.get("elements")
        if not isinstance(elements, list):
            return _check("fail", f"externalEditElements.perScenePlan[{idx}].elements must be a list")
        if not elements:
            if not str(scene_plan.get("reasonNoExternalElement") or "").strip():
                return _check(
                    "fail",
                    f"externalEditElements.perScenePlan[{idx}] needs elements or reasonNoExternalElement",
                )
            continue

        covered_scenes += 1
        for element_idx, element in enumerate(elements):
            if not isinstance(element, dict):
                return _check("fail", f"external edit element {idx + 1}.{element_idx + 1} must be an object")
            element_type = str(element.get("type") or "").strip()
            if element_type not in EXTERNAL_EDIT_ALLOWED_TYPES:
                return _check("fail", f"external edit element type {element_type!r} is not allowed")
            if element_type not in declared_types:
                return _check("fail", f"external edit element type {element_type!r} is not declared in elementTypes")

            purpose_text = str(element.get("purpose") or "").strip()
            if len(purpose_text) < 12:
                return _check("fail", "external edit element purpose must be explicit")
            if element.get("decorativeOnly") is True:
                return _check("fail", "decorative-only external edit element is forbidden")
            if element.get("subjectOcclusion") is True:
                return _check("fail", "external edit element must not create subject occlusion")
            if element.get("sourceReplacementClaim") is True:
                return _check("fail", "external edit element cannot replace weak source quality")

            semantic_role = str(element.get("semanticRole") or "").strip()
            if semantic_role not in EXTERNAL_EDIT_ALLOWED_SEMANTIC_ROLES:
                return _check("fail", "external edit element must declare an allowed semanticRole")
            if element.get("semanticCueMatchesNarration") is not True:
                return _check("fail", "external edit element must match the narration/caption beat")
            source_event = str(element.get("sourceEvent") or "").strip()
            if len(source_event) < 8:
                return _check("fail", "external edit element must name the visible sourceEvent it supports")
            binding_mode = str(element.get("bindingMode") or element.get("sourceEventBinding") or "").strip()
            if binding_mode not in EXTERNAL_EDIT_ALLOWED_BINDING_MODES:
                return _check("fail", f"external edit element bindingMode {binding_mode!r} is not allowed")

            symbol_text = _normalize_text(
                " ".join(
                    str(value or "")
                    for value in (
                        element.get("type"),
                        element.get("recognizableSymbol"),
                        element.get("symbolCue"),
                    )
                )
            )
            uses_symbolic_cue = bool(_first_forbidden(symbol_text, SYMBOLIC_CUE_TERMS))
            if uses_symbolic_cue and element.get("manualExceptionApproved") is not True:
                return _check("fail", "symbolic X/OK/check cues require a manual exception and source-event binding")
            if uses_symbolic_cue and len(str(element.get("whySymbolBeatsCleanerEdit") or "").strip()) < 20:
                return _check("fail", "symbolic cue exception must explain why it beats a cleaner edit")

            label_text = _normalize_text(
                " ".join(
                    str(value or "")
                    for value in (element.get("labelText"), element.get("debugLabel"), element.get("editorLabel"))
                )
            )
            forbidden_label = _first_forbidden(label_text, EXTERNAL_EDIT_FORBIDDEN_LABEL_TERMS)
            if forbidden_label:
                return _check("fail", f"external edit element contains forbidden editor/debug label: {forbidden_label}")

            start_sec = _optional_float(element.get("startSec"), default=-1.0)
            end_sec = _optional_float(element.get("endSec"), default=-1.0)
            if start_sec < 0 or end_sec <= start_sec:
                return _check("fail", "external edit element timing must include valid startSec/endSec")
            if end_sec - start_sec > 2.4:
                return _check("fail", "external edit element duration must stay <= 2.40s")
            if _optional_float(element.get("screenAreaRatio"), default=0.0) > 0.14:
                return _check("fail", "external edit element screen area must stay <= 14%")
            if _optional_float(element.get("opacity"), default=0.0) > 0.78:
                return _check("fail", "external edit element opacity must stay <= 0.78")
            if semantic_role in {"warning-no", "safe-resolution", "answer-payoff"}:
                if _optional_float(element.get("screenAreaRatio"), default=0.0) < min_salient_area:
                    return _check("fail", "semantic warning/safe cue is too small to be perceived")
                if _optional_float(element.get("opacity"), default=0.0) < min_salient_opacity:
                    return _check("fail", "semantic warning/safe cue opacity is too low to be perceived")

            used_types.add(element_type)
            used_roles.add(semantic_role)
            total_elements += 1

    if covered_scenes < required_active_scenes:
        return _check("fail", "external edit elements must actively support at least two scenes when available")
    if len(used_types) < 2:
        return _check("fail", "external edit elements must use at least two element types")

    declared_visual_count = _optional_float(contract.get("visualElementCount"), default=float(total_elements))
    if declared_visual_count < 1 or total_elements < 1:
        return _check("fail", "external edit layer must include at least one visual element")
    if salience.get("containsWarningOrNegativeAction") is True:
        if salience.get("warningBeatSourceEventBound") is not True:
            return _check("fail", "warning/negative action beat must bind to a visible source event")
        if "warning-no" not in used_roles:
            return _check("fail", "warning/negative action beat must include a warning-no semanticRole element")
    if salience.get("containsPositiveResolution") is True:
        if salience.get("positiveResolutionSourceEventBound") is not True:
            return _check("fail", "positive resolution beat must bind to a visible source event")
        if "safe-resolution" not in used_roles:
            return _check("fail", "positive resolution beat must include a safe-resolution semanticRole element")

    return _check("pass", "external edit elements are purposeful, salient, semantic, timed, safe, and evidenced")


def _check_layout_hud_reference(contract: dict[str, Any]) -> dict[str, str]:
    basis = _string_list(contract.get("referenceBasis"))
    basis_text = _normalize_text(" ".join(basis))
    for term in ("youtube", "tiktok", "wcag", "timed text"):
        if term not in basis_text:
            return _check("fail", "layoutHud.referenceBasis must include YouTube, TikTok, WCAG, and timed text references")

    safe_zone = contract.get("safeZone")
    if not isinstance(safe_zone, dict):
        return _check("fail", "layoutHud.safeZone object is required")
    if safe_zone.get("platformUiReviewed") is not True:
        return _check("fail", "layoutHud.safeZone.platformUiReviewed must be true")
    if safe_zone.get("subjectOcclusion") is True:
        return _check("fail", "layout/HUD must not cover the primary subject, actor/manipulator, or primary action")
    if _optional_float(safe_zone.get("topReservedPx"), default=0.0) < 96:
        return _check("fail", "layoutHud.safeZone.topReservedPx must be >= 96")
    if _optional_float(safe_zone.get("bottomReservedPx"), default=0.0) < 240:
        return _check("fail", "layoutHud.safeZone.bottomReservedPx must be >= 240")
    if _optional_float(safe_zone.get("rightReservedPx"), default=0.0) < 96:
        return _check("fail", "layoutHud.safeZone.rightReservedPx must be >= 96")

    typography = contract.get("typography")
    if not isinstance(typography, dict):
        return _check("fail", "layoutHud.typography object is required")
    hook_font = _optional_float(typography.get("hookFontSizePx"), default=0.0)
    body_font = _optional_float(typography.get("bodyFontSizePx"), default=0.0)
    if hook_font < 54 or hook_font > 74:
        return _check("fail", "layoutHud.typography.hookFontSizePx must stay 54-74")
    if body_font < 44 or body_font > 60:
        return _check("fail", "layoutHud.typography.bodyFontSizePx must stay 44-60")
    if _optional_float(typography.get("lineCountMax"), default=99.0) > 2:
        return _check("fail", "layoutHud.typography.lineCountMax must be <= 2")
    if _optional_float(typography.get("lineLengthMaxKorean"), default=99.0) > 16:
        return _check("fail", "layoutHud.typography.lineLengthMaxKorean must be <= 16")
    if _optional_float(typography.get("textContrastRatio"), default=0.0) < 4.5:
        return _check("fail", "layoutHud.typography.textContrastRatio must be >= 4.5")
    box_opacity = _optional_float(typography.get("boxOpacity"), default=0.0)
    if box_opacity < 0.28 or box_opacity > 0.62:
        return _check("fail", "layoutHud.typography.boxOpacity must stay 0.28-0.62")

    hud = contract.get("hud")
    if not isinstance(hud, dict):
        return _check("fail", "layoutHud.hud object is required")
    mode = str(hud.get("mode") or "").strip()
    if mode not in {"none", "minimal-frame", "soft-frame"}:
        return _check("fail", "layoutHud.hud.mode must be none, minimal-frame, or soft-frame")
    if hud.get("textLabels") is True or hud.get("debugMarks") is True:
        return _check("fail", "HUD text labels and debug marks are forbidden")
    if _optional_float(hud.get("opacity"), default=1.0) > 0.10:
        return _check("fail", "layoutHud.hud.opacity must be <= 0.10")
    if _optional_float(hud.get("screenAreaRatio"), default=1.0) > 0.025:
        return _check("fail", "layoutHud.hud.screenAreaRatio must be <= 0.025")

    transitions = contract.get("transitions")
    if not isinstance(transitions, dict):
        return _check("fail", "layoutHud.transitions object is required")
    if transitions.get("purposeDeclaredPerCut") is not True:
        return _check("fail", "every visible transition must have an editorial purpose")
    if transitions.get("beatAligned") is not True:
        return _check("fail", "transitions must align with audio/edit beats")
    if transitions.get("decorativeOnlyTransitions") is True:
        return _check("fail", "decorative-only transitions are forbidden")
    if _optional_float(transitions.get("maxTransitionDurationSec"), default=99.0) > 0.36:
        return _check("fail", "transition duration must stay <= 0.36s")

    return _check("pass", "layout/HUD follows golden reference safe-zone, typography, and transition constraints")


def _check_source_contract(scene: dict[str, Any]) -> dict[str, str]:
    contract = scene.get("sourceContract")
    if not isinstance(contract, dict):
        return _check("fail", "sourceContract object is required")
    required_object = str(contract.get("requiredObject") or "").strip()
    must_show = _string_list(contract.get("mustShow"))
    forbidden = _string_list(contract.get("forbidden"))
    if not required_object and not must_show:
        return _check("fail", "sourceContract must define requiredObject or mustShow")
    if not forbidden:
        return _check("fail", "sourceContract.forbidden must declare visual drift/artifact bans")
    return _check("pass", "source contract declares required visual object and forbidden drift")


def _check_source_artifact(scene: dict[str, Any], manifest: dict[str, Any], root: Path) -> dict[str, str]:
    source_path = _first_artifact_path(
        scene.get("sourcePath"),
        scene.get("selectedVideoPath"),
        scene.get("sourceLocalPath"),
        _nested(scene, "sourceAcquisition", "sourceLocalPath"),
        _nested(scene, "sourceAcquisition", "sourcePath"),
        _visual_asset_for_scene(manifest, scene).get("sourcePath"),
        _visual_asset_for_scene(manifest, scene).get("outputPath"),
    )
    if not source_path:
        return _check("fail", "local source artifact path is required")
    resolved = _resolve_artifact(root, source_path)
    if not resolved.exists():
        return _check("fail", f"local source artifact missing: {source_path}")
    source_kind = str(
        scene.get("sourceType")
        or scene.get("visualKind")
        or _visual_asset_for_scene(manifest, scene).get("kind")
        or ""
    ).lower()
    if source_kind == "image" and not _still_image_allowed(scene):
        return _check("fail", "primary still image needs explicit evidence/reference/data-card role")
    return _check("pass", f"source artifact exists: {source_path}")


def _check_prompt_contract(scene: dict[str, Any], manifest: dict[str, Any]) -> dict[str, str]:
    contract = scene.get("promptContract")
    if not isinstance(contract, dict):
        return _check("fail", "promptContract object is required")
    camera = str(contract.get("camera") or "").strip()
    action = str(contract.get("action") or "").strip()
    must_show = _string_list(contract.get("mustShow"))
    must_not_show = _string_list(contract.get("mustNotShow"))
    if not camera or not action or not must_show:
        return _check("fail", "promptContract needs camera, action, and mustShow")
    prompt_text = _prompt_text(scene, manifest)
    if len(prompt_text) < 64:
        return _check("fail", "generator prompt must be at least 64 chars")
    prompt_lower = prompt_text.lower()
    forbidden = _first_forbidden(prompt_lower, FORBIDDEN_INTERNAL_PROMPT_TERMS)
    if forbidden:
        return _check("fail", f"generator prompt contains internal term: {forbidden}")
    if not _contains_any(prompt_lower, CAMERA_TERMS):
        return _check("fail", "generator prompt lacks concrete camera language")
    if not _contains_any(prompt_lower, ACTION_TERMS):
        return _check("fail", "generator prompt lacks visible action/object language")
    must_not_hit = _first_forbidden(" ".join(must_not_show).lower(), {"caption text", "text overlay", "chart", "diagram"})
    if not must_not_hit:
        return _check("fail", "promptContract.mustNotShow must forbid text/diagram drift")
    return _check("pass", "prompt contract and generator prompt are actionable")


def _check_caption_contract(scene: dict[str, Any], preset: dict[str, Any], idx: int, total: int) -> dict[str, str]:
    contract = scene.get("captionContract")
    if not isinstance(contract, dict):
        return _check("fail", "captionContract object is required")
    role = str(contract.get("role") or "").strip()
    max_lines = int(contract.get("maxLines") or 0)
    tone = str(contract.get("tone") or "").strip()
    if not role or max_lines <= 0 or not tone:
        return _check("fail", "captionContract needs role, maxLines, and tone")
    if max_lines > 2:
        return _check("fail", "captionContract.maxLines must be <= 2")
    subtitle = str(scene.get("subtitleText") or scene.get("subtitle") or "").strip()
    if not subtitle:
        return _check("fail", "subtitleText is required")
    forbidden = _first_forbidden(subtitle.lower(), FORBIDDEN_VIEWER_CAPTION_TERMS)
    if forbidden:
        return _check("fail", f"viewer caption contains internal term: {forbidden}")
    lines = [line.strip() for line in subtitle.replace("\\N", "\n").splitlines() if line.strip()]
    if len(lines) > 2:
        return _check("fail", "viewer caption exceeds two lines")
    if any(len(line) > 16 and _has_korean(line) for line in lines):
        return _check("fail", "Korean caption line exceeds 16 chars")
    expected_role = _expected_scene_role(preset, idx, total)
    if role != expected_role:
        return _check("fail", f"caption role {role!r} does not match golden role {expected_role!r}")
    if idx == 0 and "question" in expected_role and not ("?" in subtitle or "까" in subtitle or "왜" in subtitle):
        return _check("fail", "hook-question caption must read as a question")
    return _check("pass", "caption contract matches golden role and line limits")


def _check_caption_copy_tone(scene: dict[str, Any], preset: dict[str, Any], idx: int, total: int) -> dict[str, str]:
    subtitle = str(scene.get("subtitleText") or scene.get("subtitle") or "").strip()
    if not subtitle:
        return _check("fail", "subtitleText is required for copy tone review")
    normalized = _normalize_text(subtitle)
    forbidden = _first_forbidden(normalized, AI_SLOP_COPY_PHRASES)
    if forbidden:
        return _check("fail", f"caption sounds AI-slop or over-friendly: {forbidden}")
    instruction = _first_forbidden(normalized, INSTRUCTION_COPY_PHRASES)
    if instruction:
        return _check("fail", f"caption reads like internal instruction copy: {instruction}")
    report_style = _first_forbidden(normalized, REPORT_STYLE_PHRASES)
    if report_style:
        return _check("fail", f"caption reads like report/explainer prose: {report_style}")
    korean_naturalness = _check_korean_caption_naturalness(subtitle)
    if korean_naturalness:
        return _check("fail", korean_naturalness)
    hangul_count = _hangul_count(subtitle)
    if hangul_count < 6:
        return _check("fail", "caption is too short to carry a viewer-facing beat")
    if hangul_count > 28 and idx != total - 1:
        return _check("fail", "caption is too dense for a short-form beat")
    expected_role = _expected_scene_role(preset, idx, total)
    if "question" in expected_role and not ("?" in subtitle or "까" in subtitle or "왜" in subtitle):
        return _check("fail", "hook caption must ask a viewer-facing question")
    if expected_role == "answer" and not any(term in subtitle for term in ("피", "하세요", "그늘", "답", "결론", "괜찮", "아니")):
        return _check("fail", "answer caption must resolve with a concrete viewer action or answer")
    return _check("pass", "caption copy avoids AI tone, report prose, and internal instructions")


def _check_layout_contract(scene: dict[str, Any], preset: dict[str, Any], idx: int) -> dict[str, str]:
    contract = scene.get("layoutContract")
    if not isinstance(contract, dict):
        return _check("fail", "layoutContract object is required")
    zone = str(contract.get("captionZone") or "").strip()
    must_not_cover = _string_list(contract.get("mustNotCover"))
    if not zone or not must_not_cover:
        return _check("fail", "layoutContract needs captionZone and mustNotCover")
    if contract.get("decorativeOverlayAllowed") is not False:
        return _check("fail", "decorativeOverlayAllowed must be false for golden preflight")
    overlay_text = " ".join(_string_list(scene.get("decorativeOverlays")) + _string_list(scene.get("overlayElements")))
    forbidden_overlay = _first_forbidden(overlay_text.lower(), FORBIDDEN_OVERLAY_TERMS)
    if forbidden_overlay:
        return _check("fail", f"forbidden overlay artifact declared: {forbidden_overlay}")
    expected_caption = _expected_caption_preset(preset, idx)
    actual_caption = str(scene.get("captionPreset") or scene.get("caption_preset") or "").strip()
    if actual_caption != expected_caption:
        return _check("fail", f"captionPreset {actual_caption!r} does not match golden {expected_caption!r}")
    return _check("pass", "layout contract matches golden caption placement")


def _check_caption_direction(scene: dict[str, Any], preset: dict[str, Any], idx: int) -> dict[str, str]:
    contract = scene.get("layoutContract")
    if not isinstance(contract, dict):
        return _check("fail", "layoutContract object is required for caption direction")
    caption_preset = _expected_caption_preset(preset, idx)
    zone = str(contract.get("captionZone") or "").strip()
    font_size = float(contract.get("fontSize") or contract.get("fontSizePx") or 0)
    max_width = float(contract.get("maxWidthPx") or contract.get("maxWidth") or 0)
    enter_timing = float(contract.get("enterTimingSec") if contract.get("enterTimingSec") is not None else -1)
    display_duration = float(
        contract.get("displayDurationSec") if contract.get("displayDurationSec") is not None else 0
    )
    if font_size <= 0 or max_width <= 0 or enter_timing < 0 or display_duration <= 0:
        return _check("fail", "caption direction needs fontSize, maxWidthPx, enterTimingSec, and displayDurationSec")
    if caption_preset == "top-hook":
        if zone not in {"top-left", "top-center", "top-hook"}:
            return _check("fail", f"top-hook captionZone {zone!r} is not reference-safe")
        if not 54 <= font_size <= 74:
            return _check("fail", f"top-hook fontSize {font_size:.0f}px is outside 54-74px")
        if enter_timing > 0.45:
            return _check("fail", "top-hook must land within the first 0.45s")
        if not 0.75 <= display_duration <= 1.85:
            return _check("fail", "top-hook displayDurationSec must stay 0.75-1.85s")
    else:
        if zone not in {"top-center", "upper-third", "lower-mid", "lower-info", "center-safe"}:
            return _check("fail", f"body captionZone {zone!r} is not reference-safe")
        if not 44 <= font_size <= 60:
            return _check("fail", f"body fontSize {font_size:.0f}px is outside 44-60px")
        if enter_timing > 0.75:
            return _check("fail", "body caption should land within 0.75s of the cut")
        if not 0.9 <= display_duration <= 2.05:
            return _check("fail", "body displayDurationSec must stay 0.9-2.05s")
    if max_width > 900:
        return _check("fail", "caption maxWidthPx must leave Shorts right-rail and subject room")
    return _check("pass", "caption direction sets reference-safe size, timing, and placement")


def _check_tts_script_quality(scene: dict[str, Any], preset: dict[str, Any], idx: int, total: int) -> dict[str, str]:
    contract = scene.get("ttsScriptContract")
    if not isinstance(contract, dict):
        return _check("fail", "ttsScriptContract object is required")
    narration = str(scene.get("narrationText") or scene.get("voiceoverText") or "").strip()
    if not narration:
        return _check("fail", "narrationText is required for TTS quality review")
    normalized = _normalize_text(narration)
    forbidden = _first_forbidden(normalized, FORBIDDEN_VIEWER_CAPTION_TERMS | FORBIDDEN_INTERNAL_PROMPT_TERMS)
    if forbidden:
        return _check("fail", f"TTS script contains internal term: {forbidden}")
    slop = _first_forbidden(normalized, AI_SLOP_COPY_PHRASES)
    if slop:
        return _check("fail", f"TTS script sounds AI-slop: {slop}")
    friendly = _first_forbidden(normalized, OVERFRIENDLY_TTS_PHRASES)
    if friendly:
        return _check("fail", f"TTS script is over-friendly: {friendly}")
    instruction = _first_forbidden(normalized, INSTRUCTION_COPY_PHRASES)
    if instruction:
        return _check("fail", f"TTS script reads like an instruction: {instruction}")
    report_style = _first_forbidden(normalized, {"본 영상", "설명합니다", "나타납니다", "해당", "가능성이"})
    if report_style:
        return _check("fail", f"TTS script reads like report prose: {report_style}")
    korean_naturalness = _check_korean_tts_naturalness(narration)
    if korean_naturalness:
        return _check("fail", korean_naturalness)
    role = str(contract.get("role") or "").strip()
    expected_role = _expected_scene_role(preset, idx, total)
    if role != expected_role:
        return _check("fail", f"TTS role {role!r} does not match golden role {expected_role!r}")
    duration = float(scene.get("durationSec") or scene.get("duration_sec") or 0)
    max_cps = float(contract.get("maxKoreanCharsPerSec") or 8.0)
    hangul_count = _hangul_count(narration)
    if hangul_count < 12:
        return _check("fail", "TTS script is too thin to carry the scene beat")
    if duration > 0 and hangul_count / duration > max_cps:
        return _check("fail", "TTS script is too dense for the scene duration")
    subtitle = str(scene.get("subtitleText") or "").strip()
    if _normalized_without_spacing(subtitle) and _normalized_without_spacing(subtitle) in _normalized_without_spacing(narration):
        return _check("fail", "TTS script merely repeats the caption instead of adding spoken context")
    if contract.get("avoidOverFriendlyTone") is not True:
        return _check("fail", "ttsScriptContract must explicitly avoid over-friendly AI tone")
    return _check("pass", "TTS script avoids AI slop, report prose, and over-friendly tone")


def _check_reference_parity(scene: dict[str, Any], preset: dict[str, Any], idx: int, total: int) -> dict[str, str]:
    expected_layout = _sequence_value(preset["layoutVariantSequence"], idx)
    actual_layout = str(scene.get("layoutVariantKey") or scene.get("layout_variant_key") or "").strip()
    if actual_layout != expected_layout:
        return _check("fail", f"layoutVariantKey {actual_layout!r} does not match golden {expected_layout!r}")
    expected_role = _expected_scene_role(preset, idx, total)
    actual_role = str(scene.get("referenceEditRole") or "").strip()
    if actual_role != expected_role:
        return _check("fail", f"referenceEditRole {actual_role!r} does not match golden {expected_role!r}")
    expected_sec = float(_sequence_value(preset["sceneDurationSec"], idx) or 0)
    duration = float(scene.get("durationSec") or scene.get("duration_sec") or 0)
    if duration <= 0:
        return _check("fail", "durationSec is required")
    if expected_sec and duration > max(expected_sec + 1.8, expected_sec * 1.85):
        return _check("fail", f"durationSec {duration:.2f}s drifts too far from golden {expected_sec:.2f}s")
    return _check("pass", "scene role/layout/duration match golden preset")


def _visual_asset_for_scene(manifest: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
    scene_id = str(scene.get("sceneId") or scene.get("id") or "")
    for asset in manifest.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("sceneId") or "") == scene_id and str(asset.get("role") or "").lower() == "visual":
            return asset
    return {}


def _prompt_text(scene: dict[str, Any], manifest: dict[str, Any]) -> str:
    asset = _visual_asset_for_scene(manifest, scene)
    values = [
        scene.get("sourcePrompt"),
        scene.get("grokPrompt"),
        scene.get("geminiPrompt"),
        scene.get("videoPrompt"),
        scene.get("visualPrompt"),
        scene.get("prompt"),
        _nested(scene, "promptContract", "prompt"),
        asset.get("prompt"),
        asset.get("sourcePrompt"),
        asset.get("requestPrompt"),
    ]
    return " ".join(str(value).strip() for value in values if str(value or "").strip())


def _still_image_allowed(scene: dict[str, Any]) -> bool:
    role = str(scene.get("stillImageSourceRole") or scene.get("imageSourceRole") or "").strip().lower()
    return role in {"meme", "reaction", "screenshot", "source-capture", "evidence-card", "reference-card", "data-card"}


def _expected_caption_preset(preset: dict[str, Any], idx: int) -> str:
    caption = preset.get("captionPreset") if isinstance(preset.get("captionPreset"), dict) else {}
    return str(caption.get("scene1") if idx == 0 else caption.get("body") or "").strip()


def _expected_scene_role(preset: dict[str, Any], idx: int, total: int) -> str:
    roles = _nested(preset, "editGrammar", "sceneRoles")
    if not isinstance(roles, list) or not roles:
        return ""
    if idx == 0:
        return str(roles[0])
    if idx == total - 1:
        return str(roles[-1])
    return str(roles[min(idx, len(roles) - 2)])


def _sequence_value(values: list[Any], idx: int) -> Any:
    if not values:
        return ""
    return values[min(idx, len(values) - 1)]


def _collect_failed(report: dict[str, Any]) -> list[str]:
    failed: list[str] = []
    for key, value in report.get("checks", {}).items():
        if isinstance(value, dict) and value.get("status") == "fail":
            failed.append(key)
    for scene in report.get("scenes", []):
        scene_id = str(scene.get("sceneId") or "scene")
        for key in scene.get("failedChecks") or []:
            failed.append(f"{scene_id}.{key}")
    return failed


def _check(status: str, detail: str) -> dict[str, str]:
    return {"status": status, "detail": detail}


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _read_json_object(
    root: Path,
    path: str,
    label: str,
    *,
    schema: str | None = None,
) -> tuple[dict[str, Any], str]:
    resolved = _resolve_artifact(root, path)
    if not resolved.exists():
        return {}, f"{label} evidence missing: {path}"
    try:
        if resolved.stat().st_size < 4:
            return {}, f"{label} evidence is empty or too small"
    except OSError:
        return {}, f"{label} evidence cannot be inspected"
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}, f"{label} must be valid UTF-8 JSON"
    if not isinstance(payload, dict):
        return {}, f"{label} must be a JSON object"
    if schema is not None and payload.get("schema") != schema:
        return {}, f"{label} must use schema {schema}"
    return payload, ""


def _check_media_evidence_file(root: Path, path: str, label: str) -> str:
    resolved = _resolve_artifact(root, path)
    if not resolved.exists():
        return f"{label} evidence missing: {path}"
    if resolved.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".mp4"}:
        return f"{label} must be image/video review evidence"
    try:
        if resolved.stat().st_size < 16:
            return f"{label} evidence is too small to be review proof"
    except OSError:
        return f"{label} evidence cannot be inspected"
    return ""


def _scene_ids_from_scenes(scenes: list[Any]) -> list[str]:
    scene_ids: list[str] = []
    for idx, scene in enumerate(scenes):
        if isinstance(scene, dict):
            scene_id = str(scene.get("sceneId") or scene.get("id") or "").strip()
        else:
            scene_id = ""
        scene_ids.append(scene_id or f"scene-{idx + 1:03d}")
    return scene_ids


def _scene_timeline(scenes: list[Any]) -> dict[str, dict[str, float]]:
    timeline: dict[str, dict[str, float]] = {}
    cursor = 0.0
    for scene_id, scene in zip(_scene_ids_from_scenes(scenes), scenes):
        duration = 0.0
        if isinstance(scene, dict):
            duration = _optional_float(scene.get("durationSec") or scene.get("duration_sec"), default=0.0)
        start = cursor
        end = start + max(0.0, duration)
        timeline[scene_id] = {"start": start, "end": end}
        cursor = end
    return timeline


def _scene_id_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item.get("sceneId") or item.get("id") or "").strip()
        for item in value
        if isinstance(item, dict)
    ]


def _cut_pair_list(value: Any) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    pairs: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        pairs.append((
            str(item.get("fromSceneId") or "").strip(),
            str(item.get("toSceneId") or "").strip(),
        ))
    return pairs


def _capcut_draft_summary(draft_content: dict[str, Any]) -> tuple[dict[str, Any], str]:
    tracks = draft_content.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        return {}, "capcutHandoff draft_content.tracks must be a non-empty list"
    segment_counts: dict[str, int] = {}
    track_counts: dict[str, int] = {}
    video_keyframes = 0
    for track_idx, track in enumerate(tracks):
        if not isinstance(track, dict):
            return {}, f"capcutHandoff draft_content.tracks[{track_idx}] must be an object"
        track_type = str(track.get("type") or "").strip()
        if not track_type:
            return {}, f"capcutHandoff draft_content.tracks[{track_idx}].type is required"
        segments = track.get("segments")
        if not isinstance(segments, list):
            return {}, f"capcutHandoff draft_content.tracks[{track_idx}].segments must be a list"
        track_counts[track_type] = track_counts.get(track_type, 0) + 1
        segment_counts[track_type] = segment_counts.get(track_type, 0) + len(segments)
        if track_type != "video":
            continue
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            keyframe_groups = segment.get("common_keyframes") or []
            if not isinstance(keyframe_groups, list):
                continue
            for keyframes in keyframe_groups:
                keyframe_list = keyframes.get("keyframe_list") if isinstance(keyframes, dict) else None
                if isinstance(keyframe_list, list):
                    video_keyframes += len(keyframe_list)
    return {
        "trackCounts": track_counts,
        "segmentCounts": segment_counts,
        "videoKeyframes": video_keyframes,
    }, ""


def _check_caption_tts_timeline(
    captions: dict[str, Any],
    directing_plan: dict[str, Any],
    scenes: list[Any],
) -> str:
    scene_ids = set(_scene_ids_from_scenes(scenes))
    caption_cues = captions.get("timelineCues") or captions.get("captionTimelineCues")
    plan_caption_cues = directing_plan.get("captionPlan")
    tts_segments = captions.get("ttsSegments")
    plan_tts_segments = directing_plan.get("ttsSegments")
    if not isinstance(caption_cues, list) or len(caption_cues) < len(scene_ids):
        return "editorialDirection manifest caption plan must include timed caption cues for every scene"
    if not isinstance(plan_caption_cues, list) or len(plan_caption_cues) != len(caption_cues):
        return "editorialDirection directing plan captionPlan must match manifest caption timeline"
    if not isinstance(tts_segments, list) or len(tts_segments) < len(scene_ids):
        return "editorialDirection manifest caption plan must include timed TTS segments for every scene"
    if not isinstance(plan_tts_segments, list) or len(plan_tts_segments) != len(tts_segments):
        return "editorialDirection directing plan ttsSegments must match manifest TTS timeline"
    for idx, cue in enumerate(caption_cues):
        plan_cue = plan_caption_cues[idx]
        if not isinstance(plan_cue, dict):
            return "editorialDirection directing plan captionPlan must match manifest caption timeline"
        cue_mismatch = _dict_key_mismatch(
            cue,
            plan_cue,
            ("sceneId", "startSec", "endSec", "text", "captionText"),
            ignore_missing=True,
        )
        if cue_mismatch:
            return f"editorialDirection directing plan captionPlan must match manifest caption timeline: {cue_mismatch}"
    for idx, segment in enumerate(tts_segments):
        plan_segment = plan_tts_segments[idx]
        if not isinstance(plan_segment, dict):
            return "editorialDirection directing plan ttsSegments must match manifest TTS timeline"
        segment_mismatch = _dict_key_mismatch(
            segment,
            plan_segment,
            ("sceneId", "startSec", "endSec", "text"),
        )
        if segment_mismatch:
            return f"editorialDirection directing plan ttsSegments must match manifest TTS timeline: {segment_mismatch}"
    tts_by_scene = {
        str(segment.get("sceneId") or "").strip(): segment
        for segment in tts_segments
        if isinstance(segment, dict)
    }
    seen_caption_scenes: set[str] = set()
    for idx, cue in enumerate(caption_cues):
        if not isinstance(cue, dict):
            return f"editorialDirection caption cue {idx} must be an object"
        scene_id = str(cue.get("sceneId") or "").strip()
        if scene_id not in scene_ids:
            return "editorialDirection caption cue sceneId must match manifest scenes"
        seen_caption_scenes.add(scene_id)
        start_sec = _optional_float(cue.get("startSec"), default=-1.0)
        end_sec = _optional_float(cue.get("endSec"), default=-1.0)
        if start_sec < 0 or end_sec <= start_sec:
            return "editorialDirection caption cues must include valid startSec/endSec"
        text = str(cue.get("text") or cue.get("captionText") or "").strip()
        if len(text) < 2:
            return "editorialDirection caption cue text is required"
        tts_segment = tts_by_scene.get(scene_id)
        if not isinstance(tts_segment, dict):
            return "editorialDirection each caption cue needs a matching TTS segment"
        tts_start = _optional_float(tts_segment.get("startSec"), default=-1.0)
        tts_end = _optional_float(tts_segment.get("endSec"), default=-1.0)
        if tts_start < 0 or tts_end <= tts_start:
            return "editorialDirection TTS segments must include valid startSec/endSec"
        if abs(start_sec - tts_start) > 0.30 or abs(end_sec - tts_end) > 0.30:
            return "editorialDirection caption/TTS timing must stay within 0.30s"
        tts_text = str(tts_segment.get("text") or cue.get("ttsText") or "").strip()
        if _texts_too_similar(text, tts_text):
            return "editorialDirection captions must not duplicate TTS text"
    if not scene_ids.issubset(seen_caption_scenes):
        return "editorialDirection caption cues must cover every manifest scene"
    return ""


def _dict_key_mismatch(
    left: dict[str, Any],
    right: dict[str, Any],
    keys: tuple[str, ...],
    *,
    ignore_missing: bool = False,
) -> str:
    for key in keys:
        if ignore_missing and key not in left and key not in right:
            continue
        if key not in left and key not in right:
            continue
        if not _values_equivalent(left.get(key), right.get(key)):
            return key
    return ""


def _values_equivalent(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    left_number = _maybe_float(left)
    right_number = _maybe_float(right)
    if left_number is not None and right_number is not None:
        return abs(left_number - right_number) <= 0.01
    return str(left or "").strip() == str(right or "").strip()


def _texts_too_similar(left: str, right: str) -> bool:
    left_norm = _normalized_without_spacing(left)
    right_norm = _normalized_without_spacing(right)
    if len(left_norm) < 6 or len(right_norm) < 6:
        return False
    if left_norm in right_norm or right_norm in left_norm:
        return True
    left_chars = set(left_norm)
    right_chars = set(right_norm)
    if not left_chars or not right_chars:
        return False
    overlap = len(left_chars & right_chars) / max(1, len(left_chars | right_chars))
    return overlap >= 0.85


def _capcut_audit_payload(contract: dict[str, Any], root: Path) -> tuple[dict[str, Any], str]:
    audit_path = str(contract.get("draftAuditPath") or "").strip()
    if not audit_path:
        return {}, "capcutHandoff.draftAuditPath is required"
    return _read_json_object(root, audit_path, "capcutHandoff.draftAuditPath", schema=CAPCUT_DRAFT_AUDIT_SCHEMA)


def _external_edit_element_count(contract: dict[str, Any]) -> int:
    per_scene = contract.get("perScenePlan") or contract.get("scenePlans")
    if not isinstance(per_scene, list):
        return 0
    total = 0
    for scene_plan in per_scene:
        if not isinstance(scene_plan, dict):
            continue
        elements = scene_plan.get("elements")
        if isinstance(elements, list):
            total += sum(1 for element in elements if isinstance(element, dict))
    return total


def _average_scene_dimension_score(
    scenes: list[Any],
    primary_key: str,
    fallback_key: str,
) -> float | None:
    values: list[float] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            return None
        contract = scene.get(primary_key) or scene.get(fallback_key)
        score = _average_contract_dimension_score(contract)
        if score is None:
            return None
        values.append(score)
    if not values:
        return None
    return sum(values) / len(values)


def _average_contract_dimension_score(contract: Any) -> float | None:
    if not isinstance(contract, dict):
        return None
    dimensions = contract.get("dimensions")
    if not isinstance(dimensions, dict):
        return None
    values = [_maybe_float(value) for value in dimensions.values()]
    numeric_values = [value for value in values if value is not None]
    if len(numeric_values) != len(dimensions) or not numeric_values:
        return None
    return sum(numeric_values) / len(numeric_values)


def _score_dimension_mismatch(left: Any, right: Any, required: set[str]) -> str:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return "dimensions"
    for key in sorted(required):
        if key not in left or key not in right:
            return key
        if not _values_equivalent(left.get(key), right.get(key)):
            return key
    return ""


def _score_dimension_error(
    dimensions: Any,
    required: set[str],
    min_dimension: float,
    label: str,
) -> str:
    if not isinstance(dimensions, dict):
        return f"{label}.dimensions object is required"
    missing_dimensions = sorted(required - set(dimensions.keys()))
    if missing_dimensions:
        return f"{label} missing generic dimensions: {', '.join(missing_dimensions)}"
    for key in sorted(required):
        value = _optional_float(dimensions.get(key), default=-1.0)
        if value < min_dimension:
            return f"{label} dimension {key}={value:.1f} is below minimum {min_dimension:.1f}"
    return ""


def _artifact_path(value: Any) -> str:
    return str(value or "").strip()


def _first_artifact_path(*values: Any) -> str:
    for value in values:
        path = _artifact_path(value)
        if path:
            return path
    return ""


def _resolve_artifact(root: Path, path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return root / candidate


def _audio_duration_seconds(path: Path) -> float:
    if path.suffix.lower() != ".wav":
        return 0.0
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            if rate <= 0:
                return 0.0
            return frames / float(rate)
    except (wave.Error, OSError, EOFError):
        return 0.0


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def _check_korean_caption_naturalness(text: str) -> str:
    if not _has_korean(text):
        return ""
    normalized = _normalize_text(text)
    awkward = _first_forbidden(normalized, AWKWARD_KOREAN_COPY_PHRASES)
    if awkward:
        return f"caption uses awkward Korean label/translation copy: {awkward}"
    lines = [line.strip() for line in text.replace("\\N", "\n").splitlines() if line.strip()]
    for line in lines:
        compact = _normalized_without_spacing(line)
        if _hangul_count(line) < 4:
            continue
        if "?" in line or "!" in line:
            continue
        if _contains_any(compact, KOREAN_COPY_ACTION_MARKERS):
            continue
        return f"caption line reads like a noun label, not natural Korean copy: {line}"
    return ""


def _check_korean_tts_naturalness(text: str) -> str:
    if not _has_korean(text):
        return ""
    normalized = _normalize_text(text)
    awkward = _first_forbidden(normalized, AWKWARD_KOREAN_COPY_PHRASES)
    if awkward:
        return f"TTS script uses awkward Korean label/translation copy: {awkward}"
    stripped = text.strip().rstrip(".?!… ")
    if not stripped:
        return "TTS script is empty after punctuation trimming"
    if not stripped.endswith(KOREAN_TTS_SENTENCE_ENDINGS):
        return "TTS script must read like spoken Korean with a natural sentence ending"
    return ""


def _first_forbidden(text: str, terms: set[str]) -> str:
    for term in sorted(terms):
        if term in text:
            return term
    return ""


def _has_korean(text: str) -> bool:
    return any("\uac00" <= char <= "\ud7a3" for char in text)


def _hangul_count(text: str) -> int:
    return sum(1 for char in text if "\uac00" <= char <= "\ud7a3")


def _optional_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _maybe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_score(value: float) -> float:
    return round(float(value) + 1e-9, 1)


def _normalize_text(text: str) -> str:
    return text.replace("\\N", " ").replace("\n", " ").strip().lower()


def _normalized_without_spacing(text: str) -> str:
    return "".join(_normalize_text(text).split())


def _tts_provider_key(value: Any) -> str:
    return _normalize_text(str(value or "")).replace("_", "-").replace(" ", "-")
