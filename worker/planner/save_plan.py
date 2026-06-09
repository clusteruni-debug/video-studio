from __future__ import annotations

import argparse
import base64
import json
import logging
import mimetypes
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from worker.media.runtime import write_local_media_plan
from worker.media.model_router import ProviderAvailability, route_project_plan, summarize_cost
from worker.bridge.layouts import TEMPLATE_BGM_MOOD
from worker.planner.ollama_planner import build_project_plan
from worker.planner.sample_plan import BudgetMode, ProjectPlan, SceneSpec
from worker.render.render_manifest import build_render_manifest, slugify


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Save a planned project and render manifest under storage/.")
    parser.add_argument("--prompt", required=True, help="Prompt to convert into a project plan")
    parser.add_argument(
        "--budget-mode",
        default="free",
        choices=["free", "standard", "premium"],
        help="Budget mode to apply to the project plan",
    )
    parser.add_argument(
        "--planner-mode",
        default="auto",
        choices=["auto", "gemini", "sample"],
        help="Planner backend preference. auto uses Gemini first and falls back safely.",
    )
    parser.add_argument("--veo3", action="store_true", help="Enable Veo 3 premium routing")
    parser.add_argument(
        "--project-id",
        help="Optional explicit project id to reuse an existing storage target",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root directory where storage/ lives",
    )
    return parser


def _asset_by_scene_and_role(manifest, scene_id: str, role: str):
    for asset in manifest.assets:
        if asset.sceneId == scene_id and asset.role == role:
            return asset
    raise KeyError(f"Missing manifest asset for scene={scene_id} role={role}")


def _scene_by_id(manifest, scene_id: str):
    for scene in manifest.scenes:
        if scene.sceneId == scene_id:
            return scene
    raise KeyError(f"Missing manifest scene for scene={scene_id}")


def _safe_upload_filename(file_name: str, role: str) -> str:
    original = Path(file_name or f"{role}-asset").name
    suffix = Path(original).suffix.lower()
    stem = slugify(Path(original).stem or f"{role}-asset")
    fallback_suffix = ".png" if role == "visual" else ".wav"
    return f"{stem or f'{role}-asset'}{suffix or fallback_suffix}"


def _guess_visual_kind(file_name: str, mime_type: str | None) -> str:
    mime = (mime_type or mimetypes.guess_type(file_name)[0] or "").lower()
    suffix = Path(file_name).suffix.lower()
    if mime.startswith("video/") or suffix in {".mp4", ".mov", ".webm", ".mkv"}:
        return "video"
    return "image"


def _is_local_video_handoff(source_intent: str, visual_kind: str) -> bool:
    return visual_kind == "video" and source_intent in {"wan", "ltx-video", "hunyuan-video"}


def _safe_caption_preset(value: str | None) -> str:
    candidate = str(value or "lower-info").strip()
    if candidate in {"none", "center-short", "top-hook", "lower-info"}:
        return candidate
    return "lower-info"


_NO_VOICE_AUDIO_MODES = {
    "no-voice",
    "no-narration",
    "music-first",
    "ambient-first",
    "native-audio",
}
_VOICEOVER_AUDIO_MODES = {
    "voiceover",
    "narration",
    "tts",
    "full-narration",
}


def _safe_audio_design_mode(value: object) -> str:
    candidate = str(value or "").strip().lower().replace("_", "-")
    if candidate in _NO_VOICE_AUDIO_MODES:
        return "no-voice"
    if candidate in _VOICEOVER_AUDIO_MODES:
        return "voiceover"
    return ""


def _draft_explicit_narration(item: dict) -> str | None:
    for key in ("narration", "narrationText", "narration_text"):
        if key in item:
            return _safe_note(item.get(key), max_chars=1200)
    return None


def _caption_display_duration_sec(caption_preset: str, duration_sec: float, item: dict) -> float:
    for key in ("captionDisplayDurationSec", "captionDurationSec", "caption_display_duration_sec", "caption_duration_sec"):
        try:
            explicit = float(item.get(key) or 0)
        except (TypeError, ValueError):
            explicit = 0.0
        if explicit > 0:
            return round(max(0.0, min(explicit, duration_sec)), 2)
    if caption_preset == "none":
        return 0.0
    if caption_preset == "top-hook":
        return round(min(duration_sec, 1.35), 2)
    if caption_preset == "center-short":
        return round(min(duration_sec, 1.6), 2)
    return round(min(duration_sec, 1.8), 2)


def _safe_note(value: object, max_chars: int = 500) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[:max_chars]


def _scene_asset_text(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return _safe_note(value, max_chars=1000)
    return ""


def _scene_asset_bool(item: dict, *keys: str) -> bool | None:
    for key in keys:
        if key not in item or item.get(key) in (None, ""):
            continue
        value = item.get(key)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
    return None


def _scene_asset_positive_int(item: dict, *keys: str) -> int | None:
    for key in keys:
        if key not in item or item.get(key) in (None, ""):
            continue
        try:
            value = int(item.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _apply_asset_source_metadata(asset, item: dict) -> None:
    for attr, keys in {
        "sourceProvider": ("sourceProvider", "source_provider"),
        "sourceUrl": ("sourceUrl", "source_url"),
        "sourceExternalId": ("sourceExternalId", "source_external_id", "sourceId", "source_id"),
        "sourceLicense": ("sourceLicense", "source_license"),
        "license": ("license",),
        "licenseUrl": ("licenseUrl", "license_url"),
        "attribution": ("attribution",),
        "sourceAttribution": ("sourceAttribution", "source_attribution", "attribution"),
        "artist": ("artist",),
        "creator": ("creator", "artist"),
        "sourcePageUrl": ("sourcePageUrl", "source_page_url"),
        "selectionMethod": ("selectionMethod", "selection_method"),
        "selectionKey": ("selectionKey", "selection_key"),
        "selectedCandidateSummary": ("selectedCandidateSummary", "selected_candidate_summary", "selectionRationale", "selection_rationale"),
        "downloadDate": ("downloadDate", "download_date"),
        "sourceOrigin": ("sourceOrigin", "source_origin"),
        "kind": ("kind",),
        "sourceRecoveryRerenderPlanPath": ("sourceRecoveryRerenderPlanPath", "source_recovery_rerender_plan_path"),
        "sourceRecoveryAcceptanceArtifactPath": (
            "sourceRecoveryAcceptanceArtifactPath",
            "source_recovery_acceptance_artifact_path",
        ),
        "sourceRecoveryAcceptanceSha256": (
            "sourceRecoveryAcceptanceSha256",
            "source_recovery_acceptance_sha256",
        ),
        "acceptedReplacementSha256": ("acceptedReplacementSha256", "accepted_replacement_sha256"),
    }.items():
        value = _scene_asset_text(item, *keys)
        if value:
            setattr(asset, attr, value)
    candidate_count = _scene_asset_positive_int(item, "candidateCount", "candidate_count")
    if candidate_count is not None:
        asset.candidateCount = candidate_count
    attribution_required = _scene_asset_bool(item, "attributionRequired", "attribution_required")
    if attribution_required is not None:
        asset.attributionRequired = attribution_required
    operator_owned = _scene_asset_bool(item, "operatorOwned", "operator_owned")
    if operator_owned is not None:
        asset.operatorOwned = operator_owned
    source_recovery_replacement = _scene_asset_bool(
        item,
        "sourceRecoveryReplacement",
        "source_recovery_replacement",
    )
    if source_recovery_replacement is not None:
        asset.sourceRecoveryReplacement = source_recovery_replacement
    source_provenance = item.get("sourceProvenance") or item.get("source_provenance")
    if isinstance(source_provenance, dict):
        asset.sourceProvenance = source_provenance


def _draft_scene_id(item: dict, index: int) -> str:
    candidate = str(item.get("sceneId") or item.get("scene_id") or "").strip()
    if candidate:
        return candidate
    raw_num = item.get("scene_num", index + 1)
    try:
        scene_num = int(raw_num)
    except (TypeError, ValueError):
        scene_num = index + 1
    return f"scene-{scene_num:02d}"


def _duration_from_draft(item: dict) -> float:
    try:
        return max(1.0, min(float(item.get("duration", 4.0)), 30.0))
    except (TypeError, ValueError):
        return 4.0


_BGM_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
_BGM_ASSET_TEXT_FIELDS = (
    "sidecarPath",
    "provider",
    "sourceProvider",
    "sourceUrl",
    "sourceLicense",
    "license",
    "licenseUrl",
    "attribution",
    "sourceAttribution",
    "sourceLabel",
    "title",
    "artist",
    "mood",
    "kind",
    "candidateId",
)


def _normalize_bgm_asset(bgm_asset: dict | None, project_root: Path) -> dict | None:
    if not isinstance(bgm_asset, dict):
        return None
    raw_path = str(
        bgm_asset.get("path")
        or bgm_asset.get("sourcePath")
        or bgm_asset.get("outputPath")
        or ""
    ).strip()
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    try:
        resolved = candidate.resolve()
        relative_path = resolved.relative_to(project_root.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    if not resolved.is_file() or resolved.suffix.lower() not in _BGM_AUDIO_EXTENSIONS:
        return None

    normalized: dict[str, object] = {
        "role": "bgm",
        "path": relative_path,
        "sourcePath": relative_path,
        "sourceOrigin": "operator-pinned",
        "operatorSelected": True,
    }
    for key in _BGM_ASSET_TEXT_FIELDS:
        value = bgm_asset.get(key)
        if value not in (None, ""):
            normalized[key] = value
    if "sidecarPath" in normalized:
        sidecar = Path(str(normalized["sidecarPath"]))
        if not sidecar.is_absolute():
            sidecar = project_root / sidecar
        try:
            normalized["sidecarPath"] = sidecar.resolve().relative_to(project_root.resolve()).as_posix()
        except (OSError, ValueError):
            normalized.pop("sidecarPath", None)
    return normalized


def _bgm_mood_for_template(template_type: str | None) -> str:
    return TEMPLATE_BGM_MOOD.get(str(template_type or "").strip(), "upbeat")


def _build_plan_from_draft(
    prompt: str,
    budget_mode: BudgetMode,
    draft_scenes: list[dict],
    template_type: str = "",
) -> tuple[ProjectPlan, dict[str, str]]:
    scenes: list[SceneSpec] = []
    caption_presets: dict[str, str] = {}
    for index, item in enumerate(draft_scenes):
        scene_id = _draft_scene_id(item, index)
        image_source = str(item.get("image_source") or "pexels-video")
        upload_kind = str(item.get("upload_kind") or "")
        title = str(item.get("title") or item.get("display_text") or f"Scene {index + 1}").strip()
        audio_design_mode = _safe_audio_design_mode(
            item.get("audio_design_mode") or item.get("audioDesignMode") or item.get("voice_mode") or item.get("voiceMode")
        )
        explicit_narration = _draft_explicit_narration(item)
        narration = explicit_narration if explicit_narration is not None else (
            "" if audio_design_mode == "no-voice" else str(item.get("display_text") or "").strip()
        )
        display_text = str(item.get("display_text") or narration).strip()
        image_prompt = str(item.get("image_prompt") or display_text or narration or prompt).strip()
        visual_requires_video = image_source in {
            "upload",
            "grok",
            "pexels-video",
            "wan",
            "ltx-video",
            "hunyuan-video",
        } and upload_kind != "image"
        scenes.append(
            SceneSpec(
                id=scene_id,
                title=title[:80] or f"Scene {index + 1}",
                prompt=image_prompt,
                durationSec=round(_duration_from_draft(item), 2),
                priority=5 if index == 0 else 3,
                humanRealism=4,
                nativeAudioNeed=1,
                canUseStillImage=not visual_requires_video,
                subtitleText=display_text or narration or title,
                routeHint="local",
                narrationText=narration,
            )
        )
        caption_presets[scene_id] = _safe_caption_preset(item.get("caption_preset"))

    return (
        ProjectPlan(
            version=1,
            title=(prompt.strip() or "Manual Video Studio Render")[:80],
            sourcePrompt=prompt.strip(),
            aspectRatio="9:16",
            budgetMode=budget_mode,
            monthlyCapUsd=0.0 if budget_mode == "free" else 30.0,
            scenes=scenes,
            bgmMood=_bgm_mood_for_template(template_type),
        ),
        caption_presets,
    )


def _apply_scene_directives(
    manifest,
    draft_scenes: list[dict] | None,
    selected_pexels_videos: dict[str, dict] | None,
    template_type: str = "",
) -> None:
    if not draft_scenes and not selected_pexels_videos:
        return

    drafts_by_scene_id = {
        _draft_scene_id(item, index): item
        for index, item in enumerate(draft_scenes or [])
    }
    selected_pexels_videos = selected_pexels_videos or {}

    for scene in manifest.scenes:
        draft = drafts_by_scene_id.get(scene.sceneId, {})
        visual_asset = _asset_by_scene_and_role(manifest, scene.sceneId, "visual")
        audio_asset = _asset_by_scene_and_role(manifest, scene.sceneId, "audio")
        image_source = str(draft.get("image_source") or "").strip()
        scene.captionPreset = _safe_caption_preset(draft.get("caption_preset") or scene.captionPreset)
        explicit_narration = _draft_explicit_narration(draft)
        audio_design_mode = _safe_audio_design_mode(
            draft.get("audio_design_mode") or draft.get("audioDesignMode") or draft.get("voice_mode") or draft.get("voiceMode")
        )
        if (
            not audio_design_mode
            and str(template_type or "").strip() == "authentic_vlog"
            and image_source == "grok"
            and explicit_narration in (None, "")
        ):
            audio_design_mode = "no-voice"
        scene.audioDesignMode = audio_design_mode
        if audio_design_mode == "no-voice" and explicit_narration in (None, ""):
            scene.narrationText = ""
            audio_asset.provider = "local-silence"
            audio_asset.kind = "silent-bed"
            audio_asset.prompt = "Intentional no-voice scene audio bed; BGM/native audio carries the edit."
        else:
            scene.narrationText = explicit_narration if explicit_narration is not None else scene.narrationText or scene.subtitleText
        scene.captionDisplayDurationSec = _caption_display_duration_sec(scene.captionPreset, scene.durationSec, draft)
        scene.sourceRationale = _safe_note(draft.get("source_rationale") or draft.get("sourceRationale"))
        scene.continuityNote = _safe_note(draft.get("continuity_note") or draft.get("continuityNote"))
        scene.hookNote = _safe_note(draft.get("hook_note") or draft.get("hookNote"))
        scene.originalityEvidence = _safe_note(draft.get("originality_evidence") or draft.get("originalityEvidence"))
        scene.qualityReviewNote = _safe_note(draft.get("quality_review_note") or draft.get("qualityReviewNote"))
        scene.visualQualityVerdict = _safe_note(
            draft.get("visual_quality_verdict") or draft.get("visualQualityVerdict"),
            max_chars=80,
        )
        scene.thumbnailReviewNote = _safe_note(draft.get("thumbnail_review_note") or draft.get("thumbnailReviewNote"))
        scene.audioMixReviewNote = _safe_note(draft.get("audio_mix_review_note") or draft.get("audioMixReviewNote"))
        scene.platformComparisonNote = _safe_note(draft.get("platform_comparison_note") or draft.get("platformComparisonNote"))
        scene.layoutVariantKey = _safe_note(draft.get("layout_variant_key") or draft.get("layoutVariantKey"), max_chars=80)
        scene.layoutVariantLabel = _safe_note(draft.get("layout_variant_label") or draft.get("layoutVariantLabel"), max_chars=160)
        scene.layoutVariantNote = _safe_note(draft.get("layout_variant_note") or draft.get("layoutVariantNote"), max_chars=500)
        scene.visualSourceIntent = image_source
        scene.grokPrompt = _safe_note(draft.get("grok_prompt"), max_chars=800)
        scene.selectedFileName = _safe_note(draft.get("selected_file_name") or draft.get("selectedFileName"), max_chars=240)
        scene.selectedCandidateSummary = _safe_note(
            draft.get("selected_candidate_summary")
            or draft.get("selectedCandidateSummary")
            or draft.get("selection_rationale")
            or draft.get("selectionRationale"),
            max_chars=500,
        )
        provenance_confirmed = _scene_asset_bool(
            draft,
            "source_provenance_confirmed",
            "sourceProvenanceConfirmed",
            "acceptAsGrokMainSource",
        )
        if provenance_confirmed is not None:
            scene.sourceProvenanceConfirmed = provenance_confirmed
        scene.sourceProvenanceNote = _safe_note(
            draft.get("source_provenance_note") or draft.get("sourceProvenanceNote"),
            max_chars=500,
        )
        selected_candidate = draft.get("selectedCandidate") or draft.get("selected_candidate")
        source_provenance = draft.get("sourceProvenance") or draft.get("source_provenance")
        if isinstance(selected_candidate, dict):
            scene.selectedCandidate = selected_candidate
        elif isinstance(source_provenance, dict):
            scene.selectedCandidate = {"sourceProvenance": source_provenance}

        selected = (
            selected_pexels_videos.get(scene.sceneId)
            or draft.get("selected_pexels_video")
            or draft.get("_selected_pexels_video")
        )
        if selected:
            source_url = str(selected.get("url") or "").strip()
            if source_url:
                candidate_count = _scene_asset_positive_int(selected, "candidateCount", "candidate_count")
                selected_id = str(selected.get("id") or selected.get("pexels_id") or "")
                source_page_url = str(selected.get("sourceUrl") or selected.get("source_url") or "").strip()
                author = str(selected.get("author") or selected.get("creator") or "").strip()
                visual_asset.provider = "pexels-video"
                visual_asset.kind = "video"
                visual_asset.sourceOrigin = "selected-stock"
                visual_asset.sourceProvider = "pexels-video"
                visual_asset.sourceUrl = source_url
                visual_asset.sourceExternalId = selected_id
                visual_asset.sourceLabel = source_page_url or author or "Pexels selected video"
                visual_asset.sourcePageUrl = source_page_url
                visual_asset.creator = author
                visual_asset.sourceAttribution = author
                visual_asset.candidateCount = candidate_count
                visual_asset.selectionMethod = str(
                    selected.get("selectionMethod")
                    or selected.get("selection_method")
                    or "operator-selected-from-candidates"
                )
                visual_asset.selectionKey = str(
                    selected.get("selectionKey")
                    or selected.get("selection_key")
                    or f"{scene.sceneId}:{selected_id or source_url}"
                )
                visual_asset.selectedCandidateSummary = _safe_note(
                    selected.get("selectedCandidateSummary")
                    or selected.get("selected_candidate_summary")
                    or selected.get("selectionRationale")
                    or selected.get("selection_rationale")
                    or scene.sourceRationale,
                    max_chars=500,
                )
                visual_asset.sourceMimeType = "video/mp4"
                visual_asset.outputPath = f"{scene.cacheDir}/{scene.sceneId}.pexels-selected.mp4"
                scene.visualKind = "video"
                scene.motionPreset = "none"
                continue

        if image_source in {"wan", "ltx-video", "hunyuan-video"}:
            provider_key = image_source
            visual_asset.provider = provider_key
            visual_asset.kind = "video"
            visual_asset.outputPath = f"{scene.cacheDir}/{scene.sceneId}.mp4"
            scene.visualKind = "video"
            scene.motionPreset = "none"
        elif image_source == "grok":
            visual_asset.provider = "upload"
            visual_asset.kind = "video"
            scene.visualKind = "video"
            scene.motionPreset = "none"


def _apply_scene_assets(
    manifest,
    scene_assets: list[dict] | None,
    project_root: Path,
    input_dir: Path,
) -> list[dict]:
    saved_uploads: list[dict] = []

    for item in scene_assets or []:
        scene_id = str(item.get("sceneId", "")).strip()
        role = str(item.get("role", "")).strip()
        encoded = str(item.get("base64", "")).strip()
        source_path_raw = str(item.get("sourcePath", "")).strip()
        file_name = str(item.get("fileName", "") or Path(source_path_raw).name).strip()
        mime_type = str(item.get("mimeType", "")).strip() or None
        source_generator = str(item.get("sourceGenerator", "")).strip() or None
        source_generator_request_path = str(item.get("sourceGeneratorRequestPath", "")).strip() or None
        source_generator_prompt_path = str(item.get("sourceGeneratorPromptPath", "")).strip() or None
        source_generator_log_path = str(item.get("sourceGeneratorLogPath", "")).strip() or None
        source_generator_command = str(item.get("sourceGeneratorCommand", "")).strip() or None
        item_provider = _scene_asset_text(item, "provider")
        item_source_provider = _scene_asset_text(item, "sourceProvider", "source_provider")
        item_source_label = _scene_asset_text(item, "sourceLabel", "source_label", "title")

        if not scene_id or role not in {"visual", "audio", "sfx"} or not file_name:
            continue
        if not encoded and not source_path_raw:
            continue

        source_file: Path | None = None
        if source_path_raw:
            candidate = Path(source_path_raw)
            if not candidate.is_absolute():
                candidate = project_root / candidate
            try:
                resolved = candidate.resolve()
                resolved.relative_to(project_root.resolve())
            except (OSError, ValueError):
                continue
            if not resolved.exists() or not resolved.is_file():
                continue
            source_file = resolved

        if not source_file and not encoded:
            continue

        asset = _asset_by_scene_and_role(manifest, scene_id, role)
        scene = _scene_by_id(manifest, scene_id)

        upload_dir = input_dir / "uploads" / scene_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        target_file = upload_dir / _safe_upload_filename(file_name, role)
        if source_file:
            shutil.copy2(source_file, target_file)
        else:
            target_file.write_bytes(base64.b64decode(encoded))
        relative_path = target_file.relative_to(project_root).as_posix()

        asset.provider = "upload"
        asset.sourceOrigin = "uploaded"
        asset.sourcePath = relative_path
        asset.sourceLabel = file_name
        asset.sourceMimeType = mime_type
        asset.sourceGenerator = source_generator
        asset.sourceGeneratorRequestPath = source_generator_request_path
        asset.sourceGeneratorPromptPath = source_generator_prompt_path
        asset.sourceGeneratorLogPath = source_generator_log_path
        asset.sourceGeneratorCommand = source_generator_command
        _apply_asset_source_metadata(asset, item)

        if role == "visual":
            visual_kind = _guess_visual_kind(file_name, mime_type)
            source_intent = str(getattr(scene, "visualSourceIntent", "") or "").strip()
            asset.kind = visual_kind
            asset.prompt = f"Uploaded visual asset: {file_name}"
            asset.outputPath = relative_path
            scene.visualKind = visual_kind
            if _is_local_video_handoff(source_intent, visual_kind):
                asset.provider = source_intent
                asset.sourceLabel = f"{source_intent} local-model handoff: {file_name}"
                asset.sourceGenerator = source_generator or source_intent
                scene.motionPreset = "none"
        elif role == "sfx":
            source_provider = item_source_provider or item_provider
            asset.provider = "local-sfx"
            asset.kind = "sfx"
            asset.sourceOrigin = _scene_asset_text(item, "sourceOrigin", "source_origin") or "local-library"
            asset.sourceLabel = item_source_label or file_name
            if source_provider and source_provider != "local-sfx":
                asset.sourceProvider = source_provider
            asset.prompt = f"Scene SFX asset: {asset.sourceLabel}"
            asset.outputPath = relative_path
        else:
            audio_kind = _scene_asset_text(item, "kind") or "uploaded-audio"
            asset.kind = audio_kind
            asset.sourceOrigin = _scene_asset_text(item, "sourceOrigin", "source_origin") or "uploaded"
            asset.sourceLabel = item_source_label or file_name
            if item_provider:
                asset.provider = item_provider
            asset.prompt = f"Uploaded audio asset: {asset.sourceLabel}"
            scene.audioKind = "voiceover" if audio_kind == "voiceover" else "native"

        saved_uploads.append(
            {
                "sceneId": scene_id,
                "role": role,
                "fileName": file_name,
                "storedPath": relative_path,
                "mimeType": mime_type,
            }
        )

    return saved_uploads


def save_project_bundle(
    prompt: str,
    budget_mode: str,
    availability: ProviderAvailability,
    planner_mode: str = "auto",
    project_id: str | None = None,
    project_root: str | Path = ".",
    scene_assets: list[dict] | None = None,
    provider_overrides: dict[str, str] | None = None,
    draft_scenes: list[dict] | None = None,
    selected_pexels_videos: dict[str, dict] | None = None,
    subtitle_style: str = "",
    bgm_enabled: bool = True,
    bgm_asset: dict | None = None,
    template_type: str = "",
) -> dict:
    if draft_scenes:
        plan, caption_presets = _build_plan_from_draft(prompt, budget_mode, draft_scenes, template_type)
        planner = type("PlannerInfo", (), {
            "backend": "ui-draft",
            "model": "manual-scenes",
            "detail": "rendered from edited dashboard scenes",
            "to_dict": lambda self: {
                "backend": self.backend,
                "model": self.model,
                "detail": self.detail,
                "fallbackUsed": False,
            },
        })()
    else:
        plan, planner = build_project_plan(
            prompt,
            budget_mode=budget_mode,
            planner_mode=planner_mode,
        )
        caption_presets = {}
    decisions = route_project_plan(plan, availability)
    estimated_cost = summarize_cost(decisions)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    resolved_project_id = project_id or f"{timestamp}-{slugify(plan.title)}"
    resolved_project_root = Path(project_root).resolve()
    normalized_bgm_asset = _normalize_bgm_asset(bgm_asset, resolved_project_root)
    manifest = build_render_manifest(
        plan=plan,
        decisions=decisions,
        project_id=resolved_project_id,
        estimated_cost_usd=estimated_cost,
        provider_overrides=provider_overrides,
        scene_caption_presets=caption_presets,
        subtitle_style=subtitle_style,
        bgm_enabled=bgm_enabled,
        bgm_asset=normalized_bgm_asset,
        template_type=template_type,
    )

    input_dir = resolved_project_root / manifest.inputDir
    cache_dir = resolved_project_root / manifest.cacheDir
    render_dir = resolved_project_root / manifest.renderDir
    input_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    render_dir.mkdir(parents=True, exist_ok=True)

    _apply_scene_directives(
        manifest=manifest,
        draft_scenes=draft_scenes,
        selected_pexels_videos=selected_pexels_videos,
        template_type=template_type,
    )
    saved_uploads = _apply_scene_assets(
        manifest=manifest,
        scene_assets=scene_assets,
        project_root=resolved_project_root,
        input_dir=input_dir,
    )

    for scene in plan.scenes:
        scene_dir = cache_dir / scene.id
        scene_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = input_dir / f"{scene.id}.prompt.txt"
        prompt_file.write_text(
            f"{scene.title}\n\n{scene.prompt}\n\nSubtitle: {scene.subtitleText}\n",
            encoding="utf-8",
        )

    plan_path = input_dir / "project-plan.json"
    routes_path = input_dir / "routes.json"
    manifest_path = input_dir / "render-manifest.json"
    notes_path = input_dir / "operator-notes.txt"

    plan_dict = plan.to_dict()
    routes_dict = [decision.to_dict() for decision in decisions]
    manifest_dict = manifest.to_dict()

    plan_path.write_text(json.dumps(plan_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    routes_path.write_text(
        json.dumps(routes_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest_path.write_text(json.dumps(manifest_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    local_media_plan = write_local_media_plan(
        manifest=manifest_dict,
        manifest_path=manifest_path,
        project_root=resolved_project_root,
    )
    notes_path.write_text(
        "\n".join(
            [
                f"project_id: {resolved_project_id}",
                f"input_dir: {input_dir}",
                f"cache_dir: {cache_dir}",
                f"render_dir: {render_dir}",
                f"planner_backend: {planner.backend}",
                f"planner_model: {planner.model}",
                f"planner_detail: {planner.detail}",
                f"compose_command: {manifest.composeCommandPreview}",
                f"uploaded_assets: {len(saved_uploads)}",
                f"local_media_plan: {local_media_plan.planPath}",
                f"local_media_generation_required: {local_media_plan.summary.generationRequired}",
            ]
        ),
        encoding="utf-8",
    )

    payload = {
        "projectId": resolved_project_id,
        "inputDir": str(input_dir),
        "cacheDir": str(cache_dir),
        "renderDir": str(render_dir),
        "planPath": str(plan_path),
        "routesPath": str(routes_path),
        "manifestPath": str(manifest_path),
        "notesPath": str(notes_path),
        "estimatedTotalCostUsd": estimated_cost,
        "uploadedAssets": saved_uploads,
        "localMediaPlanPath": local_media_plan.planPath,
        "localMediaSummary": local_media_plan.summary.to_dict(),
    }
    return {
        "saveResult": payload,
        "planner": planner.to_dict(),
        "plan": plan_dict,
        "routes": routes_dict,
        "manifest": manifest_dict,
    }


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,  # keep stdout clean for JSON payload
    )
    parser = _build_parser()
    args = parser.parse_args()

    availability = ProviderAvailability(
        veo3=args.veo3,
        premium_enabled=bool(args.veo3),
    )
    payload = save_project_bundle(
        prompt=args.prompt,
        budget_mode=args.budget_mode,
        availability=availability,
        planner_mode=args.planner_mode,
        project_id=args.project_id,
        project_root=args.project_root,
    )
    print(json.dumps(payload["saveResult"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
