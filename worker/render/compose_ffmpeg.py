"""FFmpeg primitive operations for compose.py.

Extracted from compose.py to keep the orchestrator file under the 660-line limit.
Contains: FFmpeg command wrappers, scene clip construction, audio mixing,
subtitle writers, manifest helpers, and shared constants.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path

from worker.bridge.templates import operating_template_for
from worker.render.motion import zoompan_filter
from worker.render.transitions import gradient_source_filter
from worker.runtime.tools import probe_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared constants (RENDERING-SPEC)
# ---------------------------------------------------------------------------
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
FRAME_SIZE = "1080x1920"
FRAME_RATE = "30"
VIDEO_FILTER = "fps=30,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,format=yuv420p"
SCENE_COLORS = ["#183153", "#3f5c7a", "#7c4d3a", "#556b2f", "#5f4b8b", "#7b3f61"]
DEFAULT_MOTION_PRESET = "none"
DEFAULT_TRANSITION_TYPE = "fade"
DEFAULT_TRANSITION_DURATION = 0.5

BGM_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
BGM_VOLUME = float(os.environ.get("VIDEO_STUDIO_BGM_VOLUME", "0.35"))
BGM_MIX_GAIN = float(os.environ.get("VIDEO_STUDIO_BGM_MIX_GAIN", "1.55"))
BGM_DUCK_THRESHOLD = float(os.environ.get("VIDEO_STUDIO_BGM_DUCK_THRESHOLD", "0.08"))
BGM_DUCK_RATIO = float(os.environ.get("VIDEO_STUDIO_BGM_DUCK_RATIO", "2.6"))
BGM_DUCK_RELEASE_MS = int(os.environ.get("VIDEO_STUDIO_BGM_DUCK_RELEASE_MS", "180"))
SFX_VOLUME = 0.8  # SFX volume relative to narration
FINAL_AUDIO_LOUDNORM_ENABLED = os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_LOUDNORM", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
FINAL_AUDIO_TARGET_I = float(os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_TARGET_I", "-14.0"))
FINAL_AUDIO_TARGET_TP = float(os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_TARGET_TP", "-1.5"))
FINAL_AUDIO_TARGET_LRA = float(os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_TARGET_LRA", "11.0"))
FINAL_AUDIO_LIMITER_TP = float(
    os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_LIMITER_TP", "-4.0")
)
FINAL_AUDIO_LIMITER_ATTACK_MS = float(os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_LIMITER_ATTACK_MS", "5"))
FINAL_AUDIO_LIMITER_RELEASE_MS = float(os.environ.get("VIDEO_STUDIO_FINAL_AUDIO_LIMITER_RELEASE_MS", "50"))

FREE_STOCK_PROVIDERS = {"pexels-video", "pexels", "pixabay-video", "pixabay", "mixkit", "freesound", "klipy", "tenor"}
FREE_AUDIO_STOCK_PROVIDERS = {
    "local-bgm",
    "youtube-audio-library",
    "youtube-audio",
    "mixkit-audio",
    "mixkit",
    "pixabay-audio",
    "pixabay",
    "freesound",
    "local-sfx",
}
FREE_NARRATION_PROVIDERS = {"edge-tts", "windows-speech", "windows-tts", "edge"}
LOCAL_ORIGINAL_VIDEO_INTENTS = {"wan", "ltx-video", "hunyuan-video"}
GROK_SOURCE_PROVENANCE_ACCEPTABLE_STATUSES = {
    "browser-native-original-download",
    "local-mp4-download-unverified",
    "local-mp4-source-unverified",
}
GROK_SOURCE_CONFIRMATION_REQUIRED_STATUSES = {
    "local-mp4-download-unverified",
    "local-mp4-source-unverified",
}
GROK_PREVIEW_CAVEAT_TERMS = (
    "candidate preview only",
    "final grok-main approval still needs",
    "not a final publish packet",
    "needs extra original-download",
    "broader take curation",
    "two-take curation",
)
OWNED_UPLOAD_EVIDENCE_TERMS = (
    "owned phone footage",
    "operator-owned raw footage",
    "phone camera",
    "phone-camera",
    "camera footage",
    "raw camera",
    "raw-camera",
    "operator shot",
    "operator-shot",
    "operator filmed",
    "shot by operator",
    "filmed by operator",
    "screen recording",
    "screen-recorded",
    "direct capture",
    "direct recording",
    "original footage",
    "self-shot",
    "directly filmed",
    "직접 촬영",
    "본인 촬영",
    "직접 녹화",
    "소유 영상",
)
STOCK_REWRAPPED_UPLOAD_EVIDENCE_TERMS = (
    "pexels",
    "pixabay",
    "mixkit",
    "free stock",
    "stock footage",
    "stock video",
    "selected stock",
    "manual stock",
    "royalty-free stock",
    "rights-safe stock",
)
PROCEDURAL_PLACEHOLDER_EVIDENCE_TERMS = (
    "video-studio-local-render",
    "ffmpeg/direct motion",
    "ffmpeg direct motion",
    "local ffmpeg",
    "procedural motion",
    "procedural placeholder",
    "test pattern",
    "test-pattern",
    "color bar",
    "color bars",
    "colour bar",
    "colour bars",
    "colorbar",
    "smpte",
    "smptebars",
    "testsrc",
    "lavfi",
    "local/generated mp4 for video studio qa",
    "generated inside video studio",
)
SAFE_CAPTION_PRESETS = {"none", "center-short", "top-hook", "lower-info"}
CAPTION_LAYOUT_TERMS = (
    "caption", "subtitle", "safe", "occlusion", "subject", "top-safe", "lower",
    "center", "자막", "세이프", "가리지", "피사체", "하단", "상단",
)
SHORTS_CAPTION_SAFE_ZONE_POLICY = {
    "top-hook": "top-left safe area, short first-beat hook, away from right rail",
    "center-short": "center safe area, max two compact lines",
    "lower-info": "lower-mid safe area around 55-65 percent frame height, not bottom UI",
}
SHORTS_CAPTION_MAX_COMPACT_CHARS = {
    "top-hook": 24,
    "center-short": 22,
    "lower-info": 34,
}
PRODUCTION_META_HARD_TERMS = (
    "tts",
    "b-roll",
    "broll",
    "prompt",
    "render",
    "safe zone",
    "youtube ui",
    "프롬프트",
    "렌더",
    "세이프존",
    "safe-zone",
    "제작 기준",
    "다음 제작",
    "체크리스트",
    "소스 선택",
    "후보",
)
PRODUCTION_META_SOFT_TERMS = (
    "컷",
    "씬",
    "장면",
    "화면",
    "자막",
    "시청자",
    "제작",
    "영상",
    "레이아웃",
    "구성",
    "편집",
    "전환",
    "검수",
)
PRODUCTION_META_VIEWER_INTENT_PHRASES = (
    "이영상은",
    "이번영상은",
    "영상의의도",
    "어떤의도",
    "의도를설명",
    "의도를보여",
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
VISUAL_VERDICT_PASS_VALUES = {
    "pass",
    "passed",
    "approved",
    "ready",
    "upload-ready",
    "channel-ready",
    "publish-ready",
    "top-tier-ready",
    "ok",
    "safe",
}
VISUAL_VERDICT_FAIL_VALUES = {
    "fail",
    "failed",
    "blocked",
    "reject",
    "rejected",
    "needs-rework",
    "needs-review",
    "not-ready",
    "not-top-tier",
}

TEMPLATE_SOURCE_GUIDES: dict[str, dict[str, str]] = {
    "news_explainer": {
        "family": "Korean news/fact explainer",
        "sourceMix": "context stock cuts are acceptable only with source-fit rationale; first hook still needs clear motion",
        "freeAssetPlan": "Pexels/Pixabay/Wikimedia context video plus YouTube Audio Library or Mixkit BGM",
    },
    "ranking_list": {
        "family": "Korean ranking/list Shorts",
        "sourceMix": "one distinct clip per rank; repeated stock loops are not acceptable",
        "freeAssetPlan": "Pexels/Pixabay candidates per rank, with source URL/ID retained",
    },
    "tutorial_steps": {
        "family": "Korean tutorial/step Shorts",
        "sourceMix": "direct screen or hand footage should carry the instructional steps",
        "freeAssetPlan": "direct capture first; Pexels/Pixabay or CC0 icons only as support",
    },
    "authentic_vlog": {
        "family": "authentic Korean vlog",
        "sourceMix": "direct operator footage or reviewed Grok/local handoff MP4 should lead; stock is support B-roll",
        "freeAssetPlan": "operator/Grok/local MP4, Pexels/Pixabay support video, YouTube Audio Library or Mixkit BGM",
    },
    "persona_story": {
        "family": "AI persona/story Shorts",
        "sourceMix": "Grok app/web or local Wan/LTX/Hunyuan MP4 should provide the hero motion",
        "freeAssetPlan": "Grok/SuperGrok browser handoff, local model output, Pexels texture inserts",
    },
    "kculture_fandom": {
        "family": "K-culture fandom Shorts",
        "sourceMix": "copyright-safe substitute visuals; direct fan/event footage only when rights are clear",
        "freeAssetPlan": "direct event footage, CC/stock city-stage B-roll, YouTube Audio Library/Mixkit music",
    },
    "podcast_clip": {
        "family": "long-form/podcast clip",
        "sourceMix": "owned long-form clip or TTS summary with B-roll/chapter cards",
        "freeAssetPlan": "owned source clip, Freesound SFX, YouTube Audio Library bed",
    },
    "longform_deep_dive": {
        "family": "Korean long-form deep dive",
        "sourceMix": "chapter cards and source/data cards should carry the argument; stock clips are evidence support only",
        "freeAssetPlan": "operator-made charts, Wikimedia/Pexels/Pixabay evidence media, YouTube Audio Library or Mixkit BGM",
    },
    "interview_documentary": {
        "family": "Korean interview/documentary",
        "sourceMix": "owned interview/location footage should lead; TTS summary is acceptable only with explicit rights fallback",
        "freeAssetPlan": "direct interview/location MP4, Freesound ambience, Wikimedia/Pexels evidence B-roll",
    },
    "live_recap": {
        "family": "Korean live/event recap",
        "sourceMix": "direct event footage should lead; venue/city/stage-light stock only supports atmosphere",
        "freeAssetPlan": "direct phone footage, Mixkit/Pexels/Pixabay context clips, YouTube Audio Library BGM",
    },
}

LONGFORM_NARRATION_TEMPLATES = {
    "longform_deep_dive",
    "interview_documentary",
    "podcast_clip",
}
SHORTFORM_TIGHT_NARRATION_TEMPLATES = {
    "authentic_vlog",
    "ranking_list",
    "tutorial_steps",
    "persona_story",
    "kculture_fandom",
    "live_recap",
}
NO_VOICE_ALLOWED_TEMPLATES = {
    "authentic_vlog",
    "persona_story",
    "kculture_fandom",
    "live_recap",
}
UPLOAD_SOURCE_MIX_REQUIRED_TEMPLATES = {
    "authentic_vlog",
    "ranking_list",
    "tutorial_steps",
    "persona_story",
    "kculture_fandom",
    "live_recap",
}
VOICEOVER_REQUIRED_TEMPLATES = {
    "news_explainer",
    "ranking_list",
    "tutorial_steps",
    "myth_buster",
    "hot_take",
    "vs_comparison",
    "before_after",
    "community_read",
    "reddit_translation",
    "origin_story",
    "podcast_clip",
    "longform_deep_dive",
    "interview_documentary",
}
VISUAL_LED_NO_VOICE_APPROVAL_FIELDS = {
    "visualLedNoVoiceApproved",
    "visual_led_no_voice_approved",
    "humanApprovedNoVoice",
    "human_approved_no_voice",
}
NO_VOICE_AUDIO_MODES = {
    "no-voice",
    "no-narration",
    "music-first",
    "ambient-first",
    "native-audio",
}
VOICEOVER_AUDIO_MODES = {
    "voiceover",
    "narration",
    "tts",
    "full-narration",
}


# ---------------------------------------------------------------------------
# Manifest / path helpers
# ---------------------------------------------------------------------------
def load_manifest(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def safe_text(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _required_narration_chars(content_template: str, scene_id: str, first_scene_id: str) -> int:
    """Minimum compact narration length needed before TTS evidence is credible."""
    if content_template in LONGFORM_NARRATION_TEMPLATES:
        return 80
    if content_template in SHORTFORM_TIGHT_NARRATION_TEMPLATES:
        return 24
    if scene_id == first_scene_id:
        return 24
    return 40


def _normalized_audio_design_mode(value: object) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _scene_audio_design_mode(scene: dict, manifest_mode: str, content_template: str) -> str:
    raw = _normalized_audio_design_mode(
        scene.get("audioDesignMode")
        or scene.get("audio_design_mode")
        or scene.get("voiceMode")
        or scene.get("voice_mode")
        or manifest_mode
    )
    if raw in NO_VOICE_AUDIO_MODES:
        return "no-voice"
    if raw in VOICEOVER_AUDIO_MODES:
        return "voiceover"
    if content_template in NO_VOICE_ALLOWED_TEMPLATES and str(scene.get("narrationText") or "").strip() == "":
        return "no-voice"
    return "voiceover"


def _visual_led_no_voice_approved(scene: dict, manifest: dict) -> bool:
    for key in VISUAL_LED_NO_VOICE_APPROVAL_FIELDS:
        if scene.get(key) is True:
            return True
    approvals = manifest.get("visualLedNoVoiceApprovals")
    if isinstance(approvals, dict):
        scene_id = str(scene.get("sceneId") or "")
        if approvals.get(scene_id) is True:
            return True
    return False


def asset_lookup(manifest: dict, scene_id: str, role: str) -> dict:
    for asset in manifest["assets"]:
        if asset["sceneId"] == scene_id and asset["role"] == role:
            return asset
    raise KeyError(f"Missing asset for scene={scene_id} role={role}")


def sfx_asset_lookup(manifest: dict, scene_id: str) -> dict | None:
    """Soft lookup for SFX asset — returns None if not present."""
    for asset in manifest["assets"]:
        if asset["sceneId"] == scene_id and asset["role"] == "sfx":
            return asset
    return None


def resolve_relative_asset_path(project_root: Path, relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    candidate = project_root / relative_path
    return candidate if candidate.exists() else None


def get_manifest_transition(manifest: dict) -> tuple[str, float]:
    """Read transition settings from the manifest, with defaults."""
    transition_type = manifest.get("transitionType") or DEFAULT_TRANSITION_TYPE
    transition_duration = manifest.get("transitionDuration", DEFAULT_TRANSITION_DURATION)
    return transition_type, float(transition_duration)


def get_scene_motion_preset(scene: dict) -> str:
    """Read motionPreset from the scene dict, defaulting to none."""
    return scene.get("motionPreset") or DEFAULT_MOTION_PRESET


def write_concat_file(path: Path, clip_paths: list[Path]) -> None:
    lines = [f"file '{clip_path.resolve().as_posix()}'" for clip_path in clip_paths]
    write_text(path, "\n".join(lines) + "\n")


def ffmpeg_filter_path(path: Path) -> str:
    return path.resolve().as_posix().replace(":", r"\:")


def resolve_ffmpeg_executable(project_root: Path) -> tuple[str, dict]:
    ffmpeg = probe_tool("ffmpeg", project_root=project_root)
    executable = ffmpeg.resolvedPath or ffmpeg.path
    if not executable:
        raise RuntimeError(ffmpeg.detail or "FFmpeg is not available for local rendering")
    return executable, ffmpeg.to_dict()


def _run_ffprobe_json(project_root: Path, output_path: Path) -> tuple[dict | None, dict]:
    ffprobe = probe_tool("ffprobe", project_root=project_root)
    executable = ffprobe.resolvedPath or ffprobe.path
    if not executable or not output_path.exists():
        return None, ffprobe.to_dict()

    ffprobe_info = ffprobe.to_dict()
    completed = subprocess.run(
        [
            executable,
            "-v", "error",
            "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels,duration",
            "-show_entries", "format=duration",
            "-of", "json",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    if completed.returncode != 0:
        return {"error": completed.stderr.strip() or f"ffprobe exited {completed.returncode}"}, ffprobe_info
    try:
        ffprobe_info["ready"] = True
        return json.loads(completed.stdout or "{}"), ffprobe_info
    except json.JSONDecodeError as error:
        return {"error": f"ffprobe JSON parse failed: {error.msg}"}, ffprobe_info


def _resolve_source_motion_path(project_root: Path, asset: dict) -> Path | None:
    for key in ("sourcePath", "outputPath"):
        raw = str(asset.get(key) or "").strip()
        if not raw:
            continue
        candidate = Path(raw)
        paths = [candidate] if candidate.is_absolute() else [project_root / candidate]
        for path in paths:
            if path.exists() and path.is_file():
                return path
    return None


def _sum_freeze_duration(output: str, audited_seconds: float) -> float:
    durations: list[float] = []
    for match in re.finditer(r"freeze_duration:\s*([0-9.]+)", output):
        try:
            durations.append(float(match.group(1)))
        except ValueError:
            pass
    if durations:
        return round(sum(durations), 3)

    starts: list[float] = []
    for match in re.finditer(r"freeze_start:\s*([0-9.]+)", output):
        try:
            starts.append(float(match.group(1)))
        except ValueError:
            pass
    if starts:
        return round(max(0.0, audited_seconds - min(starts)), 3)
    return 0.0


def _build_source_motion_evidence(project_root: Path, manifest: dict) -> dict:
    video_assets = [
        asset
        for asset in manifest.get("assets", [])
        if asset.get("role") == "visual" and asset.get("kind") == "video"
    ]
    if not video_assets:
        return {
            "status": "fail",
            "detail": "No visual video source assets found.",
            "scenes": [],
            "lowMotionSceneIds": [],
            "unavailableSceneIds": [],
        }

    try:
        ffmpeg_executable, ffmpeg_info = resolve_ffmpeg_executable(project_root)
    except Exception as exc:
        return {
            "status": "unavailable",
            "detail": f"FFmpeg unavailable for source motion audit: {exc}",
            "tool": {},
            "scenes": [],
            "lowMotionSceneIds": [],
            "unavailableSceneIds": [str(asset.get("sceneId") or "") for asset in video_assets],
        }

    scenes: list[dict] = []
    low_motion_scene_ids: list[str] = []
    unavailable_scene_ids: list[str] = []
    for asset in video_assets:
        scene_id = str(asset.get("sceneId") or "")
        source_path = _resolve_source_motion_path(project_root, asset)
        if source_path is None:
            unavailable_scene_ids.append(scene_id)
            scenes.append({
                "sceneId": scene_id,
                "provider": asset.get("provider"),
                "status": "unavailable",
                "detail": "No readable sourcePath/outputPath for motion audit.",
            })
            continue

        try:
            requested_seconds = float(asset.get("durationSec") or 0)
        except (TypeError, ValueError):
            requested_seconds = 0.0
        audited_seconds = max(2.0, min(8.0, requested_seconds or 6.0))
        completed = subprocess.run(
            [
                ffmpeg_executable,
                "-hide_banner",
                "-nostats",
                "-t",
                f"{audited_seconds:.3f}",
                "-i",
                str(source_path),
                "-vf",
                "freezedetect=n=-50dB:d=1",
                "-an",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        output = f"{completed.stdout}\n{completed.stderr}"
        if completed.returncode != 0:
            unavailable_scene_ids.append(scene_id)
            scenes.append({
                "sceneId": scene_id,
                "provider": asset.get("provider"),
                "path": str(source_path),
                "status": "unavailable",
                "detail": (completed.stderr or completed.stdout or f"ffmpeg exited {completed.returncode}").strip()[:240],
            })
            continue

        freeze_seconds = _sum_freeze_duration(output, audited_seconds)
        freeze_ratio = min(1.0, freeze_seconds / audited_seconds) if audited_seconds > 0 else 1.0
        low_motion = audited_seconds >= 2.0 and freeze_ratio >= 0.85
        if low_motion:
            low_motion_scene_ids.append(scene_id)
        scenes.append({
            "sceneId": scene_id,
            "provider": asset.get("provider"),
            "path": str(source_path),
            "status": "low-motion" if low_motion else "pass",
            "auditedSeconds": round(audited_seconds, 3),
            "freezeDurationSeconds": freeze_seconds,
            "freezeRatio": round(freeze_ratio, 3),
            "detail": "near-frozen source video" if low_motion else "source video has frame-to-frame motion evidence",
        })

    audited_count = sum(1 for item in scenes if item.get("status") in {"pass", "low-motion"})
    if low_motion_scene_ids:
        status = "fail"
        detail = f"Low-motion source scenes: {low_motion_scene_ids}"
    elif audited_count > 0:
        status = "pass"
        detail = f"Audited {audited_count}/{len(video_assets)} visual video sources."
    else:
        status = "unavailable"
        detail = "No visual video source files could be audited."
    return {
        "status": status,
        "detail": detail,
        "tool": ffmpeg_info,
        "scenes": scenes,
        "lowMotionSceneIds": low_motion_scene_ids,
        "unavailableSceneIds": unavailable_scene_ids,
        "auditedCount": audited_count,
        "totalVideoSources": len(video_assets),
    }


def _rate_is_30fps(value: str | None) -> bool:
    if not value or "/" not in value:
        return False
    left, right = value.split("/", 1)
    try:
        denominator = float(right)
        return denominator > 0 and abs(float(left) / denominator - 30.0) < 0.02
    except ValueError:
        return False


def _check(status: str, detail: str) -> dict:
    return {"status": status, "detail": detail}


def _text_present(value: object) -> bool:
    return bool(str(value or "").strip())


def _visual_asset_for_scene(manifest: dict, scene_id: str) -> dict:
    for asset in manifest.get("assets", []):
        if asset.get("sceneId") == scene_id and asset.get("role") == "visual":
            return asset
    return {}


def _compact_text_length(value: object) -> int:
    return len(re.sub(r"\s+", "", str(value or "")))


def _production_meta_terms(value: object) -> list[str]:
    """Detect production notes that should not be spoken to viewers."""
    lowered = str(value or "").strip().lower()
    if not lowered:
        return []
    compact = re.sub(r"\s+", "", lowered)
    hits: list[str] = []
    for term in PRODUCTION_META_HARD_TERMS:
        if term in lowered:
            hits.append(term)
    for term in PRODUCTION_META_VIEWER_INTENT_PHRASES:
        if term in compact and term not in hits:
            hits.append(term)
    soft_hits = [term for term in PRODUCTION_META_SOFT_TERMS if term in lowered]
    if hits or len(set(soft_hits)) >= 2:
        hits.extend(term for term in soft_hits if term not in hits)
    return hits


def _scene_caption_duration(scene: dict) -> float:
    for key in ("captionDisplayDurationSec", "captionDurationSec", "caption_display_duration_sec", "caption_duration_sec"):
        try:
            value = float(scene.get(key) or 0)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    for key in ("durationSec", "duration_sec"):
        try:
            value = float(scene.get(key) or 0)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    try:
        start = float(scene.get("startSec") if scene.get("startSec") is not None else scene.get("start_sec") or 0)
        end = float(scene.get("endSec") if scene.get("endSec") is not None else scene.get("end_sec") or 0)
        return max(0.0, end - start)
    except (TypeError, ValueError):
        return 0.0


def _caption_layout_reviewed(caption_preset: str, quality_review_note: str) -> bool:
    if caption_preset == "none":
        return True
    lowered = quality_review_note.lower()
    return bool(quality_review_note) and any(term in lowered for term in CAPTION_LAYOUT_TERMS)


def _caption_density_issue(caption_preset: str, subtitle_text: str) -> str:
    """Return a publish-blocking reason when burned-in Shorts text is too dense."""
    preset = str(caption_preset or "").strip()
    if preset == "none" or not subtitle_text.strip():
        return ""
    visible_lines = [
        line.strip()
        for line in re.split(r"(?:\\N|\r?\n)+", subtitle_text)
        if line.strip()
    ]
    if len(visible_lines) > 2:
        return f"{preset} caption has too many lines ({len(visible_lines)}/2)"
    korean_count = sum(1 for char in subtitle_text if "\uac00" <= char <= "\ud7a3" or "\u3131" <= char <= "\u318e")
    if korean_count > len(subtitle_text) * 0.3:
        compact_length = _compact_text_length(subtitle_text)
        max_compact = SHORTS_CAPTION_MAX_COMPACT_CHARS.get(preset)
        if max_compact and compact_length > max_compact:
            return f"{preset} caption is too dense ({compact_length}/{max_compact} compact chars)"
    else:
        word_count = len(re.findall(r"[A-Za-z0-9']+", subtitle_text))
        max_words = {"top-hook": 9, "center-short": 8, "lower-info": 12}.get(preset)
        if max_words and word_count > max_words:
            return f"{preset} caption is too dense ({word_count}/{max_words} words)"
    return ""


def _manual_visual_verdict_status(value: object) -> str:
    """Require a controlled operator verdict; free-text notes are not enough."""
    raw = str(value or "").strip().lower()
    if not raw:
        return "missing"
    normalized = re.sub(r"[\s_]+", "-", raw)
    if normalized in VISUAL_VERDICT_PASS_VALUES:
        return "pass"
    if normalized in VISUAL_VERDICT_FAIL_VALUES or normalized.startswith("needs-"):
        return "fail"
    return "missing"


def _is_specific_source_url(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return False
    if lowered.startswith(("local-cache-", "local-cache-from-", "uploaded-", "manual-upload")):
        return False
    return bool(re.match(r"^[a-z][a-z0-9+.-]*://", lowered) or lowered.startswith("www."))


def _visual_asset_identity(asset: dict) -> str:
    provider = str(asset.get("provider") or "visual")
    source_external_id = str(asset.get("sourceExternalId") or "").strip()
    if source_external_id:
        return f"{provider}:external:{source_external_id}"

    source_url = str(asset.get("sourceUrl") or "").strip()
    if source_url and _is_specific_source_url(source_url):
        return f"{provider}:url:{source_url}"

    for key in ("sourcePath", "outputPath", "sourceLabel"):
        value = str(asset.get(key) or "").strip()
        if value:
            return f"{provider}:{key}:{value}"

    if source_url:
        return f"{provider}:source:{source_url}"
    prompt = str(asset.get("prompt") or "").strip()
    return f"{provider}:prompt:{prompt}" if prompt else ""


def _asset_has_license_provenance(asset: dict, *, require_license_note: bool = False) -> bool:
    source_present = any(
        str(asset.get(key) or "").strip()
        for key in ("sourceUrl", "sourceExternalId", "sourceLabel", "sourcePath", "outputPath")
    )
    license_present = any(
        str(asset.get(key) or "").strip()
        for key in ("sourceLicense", "license", "licenseUrl", "attribution", "sourceAttribution")
    )
    return source_present and (license_present if require_license_note else True)


def _asset_evidence_label(asset: dict) -> str:
    scene_id = str(asset.get("sceneId") or "global")
    provider = str(asset.get("provider") or "unknown")
    kind = str(asset.get("kind") or asset.get("role") or "asset")
    label = str(asset.get("sourceLabel") or asset.get("sourcePath") or asset.get("outputPath") or "").strip()
    return f"{scene_id}:{provider}:{kind}:{label}" if label else f"{scene_id}:{provider}:{kind}"


def _bgm_asset_quality_risk_reason(asset: dict) -> str:
    values = []
    for key in (
        "sourcePath",
        "sourceLabel",
        "sourceUrl",
        "sourceOrigin",
        "sourceProvider",
        "sourceLicense",
        "license",
        "attribution",
        "sourceAttribution",
        "prompt",
    ):
        value = asset.get(key)
        if value not in (None, ""):
            values.append(str(value))
    return _bgm_quality_risk_reason_from_text(" ".join(values))


def _truthy_metadata(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "required"}


def _compact_credit_part(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _positive_int_metadata(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _build_free_audio_credit(asset: dict) -> dict | None:
    role = str(asset.get("role") or "")
    provider = str(asset.get("provider") or "")
    kind = str(asset.get("kind") or role or "")
    if role not in {"audio", "sfx"} or provider not in FREE_AUDIO_STOCK_PROVIDERS:
        return None
    if provider in FREE_NARRATION_PROVIDERS or kind in {"voiceover", "native"}:
        return None

    source_provider = _compact_credit_part(asset.get("sourceProvider") or provider)
    title = _compact_credit_part(
        asset.get("sourceLabel")
        or asset.get("title")
        or asset.get("sourcePath")
        or asset.get("outputPath")
    )
    creator = _compact_credit_part(asset.get("artist") or asset.get("creator") or source_provider)
    source_url = _compact_credit_part(asset.get("sourceUrl"))
    license_label = _compact_credit_part(asset.get("sourceLicense") or asset.get("license") or asset.get("licenseUrl"))
    license_url = _compact_credit_part(asset.get("licenseUrl"))
    attribution = _compact_credit_part(asset.get("attribution") or asset.get("sourceAttribution"))
    attribution_required = _truthy_metadata(asset.get("attributionRequired"))

    missing_fields: list[str] = []
    if not title:
        missing_fields.append("title")
    if not source_url:
        missing_fields.append("sourceUrl")
    if not license_label:
        missing_fields.append("license")
    if attribution_required and not attribution:
        missing_fields.append("attribution")

    if attribution:
        description_line = attribution
    else:
        credit_source = creator or source_provider or provider
        description_line = f"{title} - {credit_source}".strip(" -")
        if license_label:
            description_line = f"{description_line} ({license_label})" if description_line else license_label
    if source_url:
        description_line = f"{description_line} Source: {source_url}".strip()
    if license_url and license_url != source_url and license_url not in description_line:
        description_line = f"{description_line} License: {license_url}".strip()

    return {
        "assetId": asset.get("id") or "",
        "sceneId": asset.get("sceneId") or "global",
        "role": role,
        "kind": kind,
        "provider": provider,
        "sourceProvider": source_provider,
        "title": title,
        "creator": creator,
        "sourceUrl": source_url,
        "sourceLicense": license_label,
        "licenseUrl": license_url,
        "attributionRequired": attribution_required,
        "attribution": attribution,
        "youtubeDescriptionLine": description_line,
        "missingFields": missing_fields,
        "evidenceLabel": _asset_evidence_label(asset),
    }


def _normalized_source_tag(value: object) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _uploaded_video_originality_status(scene: dict, visual_asset: dict, source_intent: str) -> tuple[bool, str]:
    """Decide whether an uploaded MP4 can count as channel-owned original footage.

    A local file path only proves that the operator imported a clip. It does not
    prove the clip was shot, owned, generated, or handed off from Grok/local AI.
    """
    provider = _normalized_source_tag(visual_asset.get("provider"))
    intent = _normalized_source_tag(source_intent)
    generator = _normalized_source_tag(visual_asset.get("sourceGenerator"))
    if provider == "upload" and intent == "grok":
        return True, "grok-handoff"
    if provider in LOCAL_ORIGINAL_VIDEO_INTENTS or intent in LOCAL_ORIGINAL_VIDEO_INTENTS or generator in LOCAL_ORIGINAL_VIDEO_INTENTS:
        return True, "local-model"

    proof_text = " ".join(
        str(value or "")
        for value in (
            scene.get("originalityEvidence"),
            scene.get("sourceRationale"),
            scene.get("continuityNote"),
            visual_asset.get("sourceOwnership"),
            visual_asset.get("sourceLabel"),
            visual_asset.get("sourceLicense"),
            visual_asset.get("sourceProvider"),
            visual_asset.get("sourceUrl"),
            visual_asset.get("sourcePath"),
            visual_asset.get("sourceGenerator"),
            visual_asset.get("sourceGeneratorCommand"),
        )
    ).lower()
    if any(term in proof_text for term in PROCEDURAL_PLACEHOLDER_EVIDENCE_TERMS):
        return False, "procedural-placeholder"
    if any(term in proof_text for term in STOCK_REWRAPPED_UPLOAD_EVIDENCE_TERMS):
        return False, "stock-rewrapped-upload"
    if any(term in proof_text for term in OWNED_UPLOAD_EVIDENCE_TERMS):
        return True, "owned-upload-proof"
    return False, "needs-owned-source-proof"


def _is_grok_handoff_visual(provider: str, source_origin: str, source_intent: str, visual_asset: dict) -> bool:
    generator = _normalized_source_tag(visual_asset.get("sourceGenerator"))
    source_path = str(visual_asset.get("sourcePath") or "").strip().lower().replace("\\", "/")
    return (
        provider == "upload"
        and (
            source_intent == "grok"
            or source_origin == "grok-handoff"
            or generator == "grok-app-web-handoff"
            or "storage/grok-handoffs/" in source_path
        )
    )


def _source_provenance_confirmation_required(source_provenance: dict) -> bool:
    status = str(source_provenance.get("status") or "").strip()
    return status in GROK_SOURCE_CONFIRMATION_REQUIRED_STATUSES


def _has_grok_preview_caveat(*values: object) -> bool:
    text = " ".join(str(value or "") for value in values).lower()
    return any(term in text for term in GROK_PREVIEW_CAVEAT_TERMS)


def _source_review_verdict_value(*containers: object) -> str:
    verdict_keys = (
        "sourceReviewVerdict",
        "sourceFitVerdict",
        "manualSourceFitVerdict",
        "operatorSourceReviewVerdict",
        "grokSourceReviewVerdict",
        "localCandidateReviewVerdict",
        "sourceRecoveryReviewVerdict",
        "reviewDecision",
        "reviewVerdict",
        "operatorReviewStatus",
        "sourceReviewStatus",
    )
    accepted_keys = (
        "accepted",
        "sourceAccepted",
        "sourceReviewAccepted",
        "operatorAccepted",
    )
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in verdict_keys:
            value = str(container.get(key) or "").strip()
            if value:
                return value
        for key in accepted_keys:
            if key in container and container.get(key) is False:
                return "rejected"
    return ""


def _build_template_source_review(production_review: dict) -> dict:
    summary = production_review.get("summary") or {}
    template = str(summary.get("contentTemplate") or "").strip()
    guide = TEMPLATE_SOURCE_GUIDES.get(template)
    layout_counts = summary.get("layoutVariantCounts") if isinstance(summary.get("layoutVariantCounts"), dict) else {}
    primary_layout_variant = ""
    if layout_counts:
        primary_layout_variant = sorted(
            ((str(key), int(value or 0)) for key, value in layout_counts.items()),
            key=lambda item: item[1],
            reverse=True,
        )[0][0]
    operating_template = operating_template_for(template, primary_layout_variant)
    total_scenes = int(summary.get("totalScenes", 0) or 0)
    uploaded = int(summary.get("uploadedVideoScenes", 0) or 0)
    grok = int(summary.get("grokHandoffScenes", 0) or 0)
    local_model = int(summary.get("localModelVideoScenes", 0) or 0)
    stock = int(summary.get("stockVideoScenes", 0) or 0)
    image_fallback = int(summary.get("imageFallbackScenes", 0) or 0)
    repeated = summary.get("repeatedVisualAssetScenes") or []
    missing_visual_provenance = summary.get("missingFreeAssetProvenanceScenes") or []
    missing_audio_provenance = summary.get("missingFreeAudioProvenanceAssets") or []
    missing_rationale = summary.get("missingRationaleScenes") or []
    missing_continuity = summary.get("missingContinuityScenes") or []
    layout_variant_scenes = summary.get("layoutVariantScenes") or []
    missing_layout_variant_scenes = summary.get("missingLayoutVariantScenes") or []
    caption_preset_counts = summary.get("captionPresetCounts") or {}
    production_meta_narration = summary.get("productionMetaNarrationScenes") or []
    production_meta_subtitles = summary.get("productionMetaSubtitleScenes") or []
    caption_sparse_plan = bool(summary.get("captionSparsePlan"))
    long_top_hook_scenes = summary.get("longTopHookScenes") or []
    first_hook_ready = summary.get("firstSceneHookReady") is True

    required_fixes: list[str] = []
    recommended_fixes: list[str] = []

    if not template:
        recommended_fixes.append("Choose a content template so source and layout expectations are explicit.")
    if repeated:
        required_fixes.append(f"Replace repeated visual assets: {repeated}.")
    if missing_visual_provenance or missing_audio_provenance:
        recommended_fixes.append(
            "Record free visual/audio source URL, ID, creator, license, and attribution evidence."
        )
    if image_fallback:
        recommended_fixes.append(
            f"Replace {image_fallback} still-image fallback scene(s) with moving MP4 unless the still is intentional."
        )
    if missing_rationale:
        recommended_fixes.append(f"Add source-selection rationale for scenes: {missing_rationale}.")
    if missing_continuity:
        recommended_fixes.append(f"Add color/subject/camera continuity notes for scenes: {missing_continuity}.")
    if missing_layout_variant_scenes:
        required_fixes.append(
            f"Select a visible template layout variant for scenes: {missing_layout_variant_scenes}."
        )
    if production_meta_narration or production_meta_subtitles:
        required_fixes.append(
            f"Rewrite production-meta viewer text: narration={production_meta_narration}, subtitles={production_meta_subtitles}."
        )
    if caption_sparse_plan:
        required_fixes.append(
            "Add a real caption layout plan; one long hook plus mostly no-caption scenes reads unfinished."
        )
    if long_top_hook_scenes:
        required_fixes.append(f"Shorten top-hook captions to the first two seconds: {long_top_hook_scenes}.")
    if total_scenes >= 4 and not layout_variant_scenes and len(caption_preset_counts) <= 1:
        required_fixes.append(
            "Multi-scene Korean templates need layout variation evidence; one repeated caption/layout pattern reads as templated filler."
        )
    if not first_hook_ready:
        recommended_fixes.append("Add a visible first-two-second hook note or top-hook treatment.")

    if template == "authentic_vlog" and uploaded + grok + local_model == 0:
        recommended_fixes.append(
            "This template should be led by direct operator footage or reviewed Grok/local handoff MP4; stock clips should only support the owned footage."
        )
    if template == "tutorial_steps" and uploaded == 0:
        recommended_fixes.append(
            "Tutorial templates should be led by direct screen or hand footage; stock clips should only support the owned footage."
        )
    if template == "persona_story" and grok + local_model == 0:
        recommended_fixes.append(
            "Persona/story templates need Grok app/web or local Wan/LTX/Hunyuan hero MP4 evidence to avoid slideshow output."
        )
    if template == "kculture_fandom" and uploaded + grok + local_model == 0:
        recommended_fixes.append(
            "Use copyright-safe direct/generated substitute footage; do not build the whole edit from generic stock."
        )
    if template == "podcast_clip" and uploaded == 0:
        recommended_fixes.append(
            "Podcast/long-form clips should use an owned source clip or explicitly document the TTS-summary fallback."
        )
    if template == "longform_deep_dive" and missing_rationale:
        recommended_fixes.append(
            "Long-form deep dives need source/data-card rationale per chapter so stock clips do not become generic filler."
        )
    if template == "interview_documentary" and uploaded == 0:
        recommended_fixes.append(
            "Interview/documentary templates should use owned interview/location footage or document the free TTS-summary fallback."
        )
    if template == "live_recap" and uploaded == 0:
        recommended_fixes.append(
            "Live/event recaps should be led by direct event footage; stock venue/city clips are support, not the whole edit."
        )
    if template == "ranking_list" and stock > 0 and missing_rationale:
        recommended_fixes.append("Each rank needs a distinct manually chosen source with candidate evidence.")
    if template == "news_explainer" and stock == total_scenes and not summary.get("curatedStockReady"):
        recommended_fixes.append("Stock-only explainers need complete curation proof before publish review.")

    if required_fixes:
        status = "fail"
    elif recommended_fixes:
        status = "warn"
    else:
        status = "pass"

    return {
        "status": status,
        "template": template,
        "family": (guide or {}).get("family") or template or "unspecified",
        "sourceMix": (guide or {}).get("sourceMix") or "no template-specific source mix registered",
        "freeAssetPlan": (guide or {}).get("freeAssetPlan") or "record source/license evidence for every free asset",
        "operatingTemplateKey": operating_template.get("key"),
        "operatingTemplate": operating_template,
        "counts": {
            "totalScenes": total_scenes,
            "uploadedVideoScenes": uploaded,
            "grokHandoffScenes": grok,
            "localModelVideoScenes": local_model,
            "stockVideoScenes": stock,
            "imageFallbackScenes": image_fallback,
            "layoutVariantScenes": len(layout_variant_scenes),
            "missingLayoutVariantScenes": len(missing_layout_variant_scenes),
            "productionMetaNarrationScenes": len(production_meta_narration),
            "captionSparsePlan": caption_sparse_plan,
            "longTopHookScenes": len(long_top_hook_scenes),
        },
        "requiredFixes": required_fixes,
        "recommendedFixes": recommended_fixes,
    }


def _build_production_review(manifest: dict, local_media: list[dict]) -> dict:
    """Summarize operator curation evidence and publish-readiness caveats."""
    local_media_by_scene = {
        str(item.get("sceneId")): item
        for item in local_media
        if item.get("sceneId")
    }
    scenes_payload: list[dict] = []
    missing_rationale: list[str] = []
    missing_continuity: list[str] = []
    missing_originality_evidence: list[str] = []
    missing_quality_review: list[str] = []
    originality_evidence_scenes: list[str] = []
    quality_review_scenes: list[str] = []
    stock_video_scenes = 0
    uploaded_video_scenes = 0
    grok_handoff_scenes = 0
    local_model_video_scenes = 0
    image_fallback_scenes = 0
    video_scenes = 0
    stock_video_scene_ids: list[str] = []
    uploaded_video_scene_ids: list[str] = []
    grok_handoff_scene_ids: list[str] = []
    local_model_video_scene_ids: list[str] = []
    original_clip_scene_ids: list[str] = []
    weak_uploaded_originality_scenes: list[str] = []
    procedural_placeholder_scenes: list[str] = []
    image_fallback_scene_ids: list[str] = []
    thumbnail_review_scenes: list[str] = []
    audio_mix_review_scenes: list[str] = []
    platform_comparison_scenes: list[str] = []
    visual_verdict_scenes: list[str] = []
    missing_visual_verdict_scenes: list[str] = []
    failed_visual_verdict_scenes: list[str] = []
    stock_ai_clip_fit_verdict_scenes: list[str] = []
    missing_stock_ai_clip_fit_verdict_scenes: list[str] = []
    failed_stock_ai_clip_fit_verdict_scenes: list[str] = []
    layout_variant_scenes: list[str] = []
    missing_layout_variant_scenes: list[str] = []
    narration_scenes: list[str] = []
    subtitle_only_narration_scenes: list[str] = []
    missing_narration_scenes: list[str] = []
    thin_narration_scenes: list[str] = []
    production_meta_narration_scenes: list[str] = []
    production_meta_subtitle_scenes: list[str] = []
    production_meta_terms_by_scene: dict[str, list[str]] = {}
    narration_min_chars_by_scene: dict[str, int] = {}
    no_voice_audio_design_scenes: list[str] = []
    voiceover_required_no_voice_scenes: list[str] = []
    visual_led_no_voice_approved_scenes: list[str] = []
    missing_no_voice_audio_scenes: list[str] = []
    missing_no_voice_audio_review_scenes: list[str] = []
    audio_design_modes_by_scene: dict[str, str] = {}
    captioned_scene_ids: list[str] = []
    long_top_hook_scenes: list[str] = []
    caption_density_issue_scenes: list[str] = []
    caption_density_issues_by_scene: dict[str, str] = {}
    caption_layout_review_scenes: list[str] = []
    missing_caption_layout_review_scenes: list[str] = []
    repeated_visual_asset_scenes: list[str] = []
    free_asset_provenance_scenes: list[str] = []
    missing_free_asset_provenance_scenes: list[str] = []
    free_audio_provenance_assets: list[str] = []
    missing_free_audio_provenance_assets: list[str] = []
    free_audio_credits: list[dict] = []
    free_audio_credit_missing_assets: list[str] = []
    bgm_selection_assets: list[str] = []
    weak_bgm_selection_assets: list[str] = []
    placeholder_bgm_assets: list[str] = []
    placeholder_bgm_asset_reasons: dict[str, str] = {}
    stock_candidate_curation_scenes: list[str] = []
    stock_candidate_curation_ready_scenes: list[str] = []
    missing_stock_candidate_curation_scenes: list[str] = []
    missing_stock_candidate_count_scenes: list[str] = []
    missing_stock_candidate_creator_scenes: list[str] = []
    missing_stock_candidate_source_scenes: list[str] = []
    missing_stock_selection_summary_scenes: list[str] = []
    stock_candidate_curation_issues_by_scene: dict[str, list[str]] = {}
    grok_source_curation_scenes: list[str] = []
    grok_source_curation_ready_scenes: list[str] = []
    missing_grok_source_curation_scenes: list[str] = []
    missing_grok_candidate_comparison_scenes: list[str] = []
    missing_grok_selected_file_scenes: list[str] = []
    missing_grok_source_provenance_scenes: list[str] = []
    unacceptable_grok_source_provenance_scenes: list[str] = []
    missing_grok_source_confirmation_scenes: list[str] = []
    grok_source_review_verdict_scenes: list[str] = []
    rejected_grok_source_review_scenes: list[str] = []
    grok_preview_caveat_scenes: list[str] = []
    visual_identity_first_seen: dict[str, str] = {}
    caption_preset_counts: dict[str, int] = {}
    layout_variant_counts: dict[str, int] = {}
    content_template = str(manifest.get("templateType") or manifest.get("template_type") or manifest.get("contentTemplate") or "")
    manifest_audio_design_mode = _normalized_audio_design_mode(
        manifest.get("audioDesignMode") or manifest.get("audio_design_mode")
    )
    global_audio_bed_available = False
    audio_bed_scene_ids: set[str] = set()

    for asset in manifest.get("assets", []):
        role = str(asset.get("role") or "")
        provider = str(asset.get("provider") or "")
        kind = str(asset.get("kind") or "")
        scene_id = str(asset.get("sceneId") or "").strip()
        is_fallback_audio = provider == "fallback-sine" or kind == "fallback-tone"
        is_narration_audio = provider in FREE_NARRATION_PROVIDERS or kind in {"voiceover"}
        is_audio_bed = (
            role in {"audio", "sfx"}
            and not is_fallback_audio
            and not is_narration_audio
            and (
                provider in FREE_AUDIO_STOCK_PROVIDERS
                or provider == "upload"
                or kind in {"bgm", "music", "ambient", "ambience", "native", "uploaded-audio", "sfx"}
            )
        )
        if is_audio_bed:
            if scene_id and scene_id not in {"global", "project"}:
                audio_bed_scene_ids.add(scene_id)
            else:
                global_audio_bed_available = True
        if role not in {"audio", "sfx"} or provider not in FREE_AUDIO_STOCK_PROVIDERS:
            continue
        if provider in FREE_NARRATION_PROVIDERS or kind in {"voiceover", "native"}:
            continue
        if role == "sfx" and not any(
            str(asset.get(key) or "").strip()
            for key in ("sourceOrigin", "sourcePath", "sourceUrl", "sourceExternalId", "sourceLabel")
        ):
            continue
        credit = _build_free_audio_credit(asset)
        if credit:
            free_audio_credits.append(credit)
            if credit["missingFields"]:
                free_audio_credit_missing_assets.append(
                    f"{credit['evidenceLabel']}:missing={','.join(credit['missingFields'])}"
                )
        evidence_label = _asset_evidence_label(asset)
        if _asset_has_license_provenance(asset, require_license_note=True):
            free_audio_provenance_assets.append(evidence_label)
        else:
            missing_free_audio_provenance_assets.append(evidence_label)
        if provider == "local-bgm" and kind == "bgm":
            try:
                candidate_count = int(asset.get("candidateCount") or 0)
            except (TypeError, ValueError):
                candidate_count = 0
            selection_method = str(asset.get("selectionMethod") or "").strip()
            selection_key = str(asset.get("selectionKey") or "").strip()
            operator_pinned = (
                selection_method == "operator-pinned"
                and selection_key
                and asset.get("operatorSelected") is True
            )
            bgm_quality_risk = _bgm_asset_quality_risk_reason(asset)
            if bgm_quality_risk:
                placeholder_bgm_assets.append(evidence_label)
                placeholder_bgm_asset_reasons[evidence_label] = bgm_quality_risk
            if (candidate_count >= 2 and selection_method == "stable-hash" and selection_key) or operator_pinned:
                bgm_selection_assets.append(evidence_label)
            else:
                weak_bgm_selection_assets.append(evidence_label)

    scenes = manifest.get("scenes", [])
    layout_variant_required_templates = {
        "ranking_list",
        "tutorial_steps",
        "persona_story",
        "kculture_fandom",
        "longform_deep_dive",
        "interview_documentary",
        "live_recap",
    }
    requires_layout_variant = bool(
        content_template
        and len(scenes) > 1
        and (
            content_template in layout_variant_required_templates
            or len(scenes) >= 4
        )
    )
    first_scene_id = str((scenes[0] if scenes else {}).get("sceneId") or "")
    for scene in scenes:
        scene_id = str(scene.get("sceneId") or "")
        visual_asset = _visual_asset_for_scene(manifest, scene_id)
        visual_kind = str(scene.get("visualKind") or visual_asset.get("kind") or "")
        provider = str(visual_asset.get("provider") or "")
        source_origin = str(visual_asset.get("sourceOrigin") or "")
        source_intent = str(scene.get("visualSourceIntent") or provider or "")
        rationale = str(scene.get("sourceRationale") or "").strip()
        continuity = str(scene.get("continuityNote") or "").strip()
        hook_note = str(scene.get("hookNote") or "").strip()
        narration_text = str(scene.get("narrationText") or "").strip()
        subtitle_text = str(scene.get("subtitleText") or "").strip()
        caption_preset = str(scene.get("captionPreset") or "lower-info")
        audio_design_mode = _scene_audio_design_mode(scene, manifest_audio_design_mode, content_template)
        originality_evidence = str(scene.get("originalityEvidence") or "").strip()
        quality_review_note = str(scene.get("qualityReviewNote") or "").strip()
        thumbnail_review_note = str(scene.get("thumbnailReviewNote") or "").strip()
        audio_mix_review_note = str(scene.get("audioMixReviewNote") or "").strip()
        platform_comparison_note = str(scene.get("platformComparisonNote") or "").strip()
        visual_led_no_voice_approved = _visual_led_no_voice_approved(scene, manifest)
        visual_quality_verdict = str(
            scene.get("visualQualityVerdict")
            or scene.get("qualityReviewVerdict")
            or scene.get("manualVisualVerdict")
            or scene.get("operatorVisualVerdict")
            or ""
        ).strip()
        visual_quality_verdict_status = _manual_visual_verdict_status(visual_quality_verdict)
        stock_ai_clip_fit_verdict = str(
            scene.get("stockAiClipFitVerdict")
            or scene.get("stockClipFitVerdict")
            or scene.get("sourceFitVerdict")
            or scene.get("manualStockFitVerdict")
            or ""
        ).strip()
        stock_ai_clip_fit_verdict_status = _manual_visual_verdict_status(stock_ai_clip_fit_verdict)
        layout_variant_key = str(scene.get("layoutVariantKey") or "").strip()
        layout_variant_label = str(scene.get("layoutVariantLabel") or "").strip()
        layout_variant_note = str(scene.get("layoutVariantNote") or "").strip()
        source_generator = str(visual_asset.get("sourceGenerator") or "").strip()
        source_generator_request_path = str(visual_asset.get("sourceGeneratorRequestPath") or "").strip()
        source_generator_prompt_path = str(visual_asset.get("sourceGeneratorPromptPath") or "").strip()
        source_generator_log_path = str(visual_asset.get("sourceGeneratorLogPath") or "").strip()
        source_generator_command = str(visual_asset.get("sourceGeneratorCommand") or "").strip()
        local_media_result = local_media_by_scene.get(scene_id, {})
        caveats: list[str] = []
        is_original_video = False
        upload_originality_status = ""
        caption_preset_counts[caption_preset] = caption_preset_counts.get(caption_preset, 0) + 1
        selected_candidate = scene.get("selectedCandidate") if isinstance(scene.get("selectedCandidate"), dict) else {}
        candidate_assets = visual_asset.get("candidateAssets") if isinstance(visual_asset.get("candidateAssets"), list) else []
        try:
            grok_candidate_count = int(visual_asset.get("candidateCount") or 0)
        except (TypeError, ValueError):
            grok_candidate_count = 0
        if grok_candidate_count <= 0 and candidate_assets:
            grok_candidate_count = len([item for item in candidate_assets if isinstance(item, dict)])
        if grok_candidate_count <= 0 and selected_candidate:
            grok_candidate_count = 1
        selected_file_name = str(
            scene.get("selectedFileName")
            or scene.get("selectedGrokFileName")
            or visual_asset.get("selectedFileName")
            or selected_candidate.get("fileName")
            or ""
        ).strip()
        selected_candidate_summary = str(scene.get("selectedCandidateSummary") or "").strip()
        source_provenance = (
            selected_candidate.get("sourceProvenance")
            if isinstance(selected_candidate.get("sourceProvenance"), dict)
            else visual_asset.get("sourceProvenance")
            if isinstance(visual_asset.get("sourceProvenance"), dict)
            else {}
        )
        source_provenance_status = str(source_provenance.get("status") or "").strip()
        source_provenance_confirmed = scene.get("sourceProvenanceConfirmed") is True
        source_provenance_note = str(scene.get("sourceProvenanceNote") or "").strip()
        source_provenance_requires_confirmation = _source_provenance_confirmation_required(source_provenance)
        grok_source_review_verdict = _source_review_verdict_value(
            scene,
            selected_candidate,
            visual_asset,
            source_provenance,
        )
        grok_source_review_verdict_status = _manual_visual_verdict_status(grok_source_review_verdict)
        is_grok_handoff_source = _is_grok_handoff_visual(
            _normalized_source_tag(provider),
            _normalized_source_tag(source_origin),
            _normalized_source_tag(source_intent),
            visual_asset,
        )
        grok_source_curation_issues: list[str] = []
        if is_grok_handoff_source:
            grok_source_curation_scenes.append(scene_id)
            if grok_candidate_count < 2:
                grok_source_curation_issues.append("candidateCount<2")
                missing_grok_candidate_comparison_scenes.append(scene_id)
            if not selected_file_name:
                grok_source_curation_issues.append("selectedFileName")
                missing_grok_selected_file_scenes.append(scene_id)
            if len(selected_candidate_summary) < 24:
                grok_source_curation_issues.append("selectedCandidateSummary")
                if scene_id not in missing_grok_candidate_comparison_scenes:
                    missing_grok_candidate_comparison_scenes.append(scene_id)
            if not source_provenance:
                grok_source_curation_issues.append("sourceProvenance")
                missing_grok_source_provenance_scenes.append(scene_id)
            else:
                source_accepts_grok_main = source_provenance.get("acceptAsGrokMainSource")
                if (
                    source_accepts_grok_main is False
                    or source_provenance_status not in GROK_SOURCE_PROVENANCE_ACCEPTABLE_STATUSES
                ):
                    grok_source_curation_issues.append("sourceProvenanceUnacceptable")
                    unacceptable_grok_source_provenance_scenes.append(scene_id)
                if source_provenance_requires_confirmation and (
                    source_provenance_confirmed is not True
                    or len(source_provenance_note) < 24
                ):
                    grok_source_curation_issues.append("sourceProvenanceConfirmation")
                    missing_grok_source_confirmation_scenes.append(scene_id)
            if grok_source_review_verdict_status == "pass":
                grok_source_review_verdict_scenes.append(scene_id)
            elif grok_source_review_verdict_status == "fail":
                grok_source_curation_issues.append("sourceReviewRejected")
                rejected_grok_source_review_scenes.append(scene_id)
            if _has_grok_preview_caveat(
                rationale,
                originality_evidence,
                quality_review_note,
                thumbnail_review_note,
                audio_mix_review_note,
                platform_comparison_note,
            ):
                grok_source_curation_issues.append("previewCaveat")
                grok_preview_caveat_scenes.append(scene_id)
            if grok_source_curation_issues:
                missing_grok_source_curation_scenes.append(scene_id)
                caveats.append(f"missing Grok-main curation evidence: {grok_source_curation_issues}")
            else:
                grok_source_curation_ready_scenes.append(scene_id)

        if visual_kind == "video":
            video_scenes += 1
            if provider == "pexels-video":
                stock_video_scenes += 1
                stock_video_scene_ids.append(scene_id)
                stock_candidate_curation_scenes.append(scene_id)
                stock_issues: list[str] = []
                stock_candidate_count = _positive_int_metadata(visual_asset.get("candidateCount"))
                stock_creator = str(
                    visual_asset.get("creator")
                    or visual_asset.get("artist")
                    or visual_asset.get("sourceAttribution")
                    or ""
                ).strip()
                stock_source = str(
                    visual_asset.get("sourcePageUrl")
                    or visual_asset.get("sourceExternalId")
                    or visual_asset.get("sourceLabel")
                    or visual_asset.get("sourceUrl")
                    or ""
                ).strip()
                stock_summary = str(
                    visual_asset.get("selectedCandidateSummary")
                    or visual_asset.get("selectionRationale")
                    or rationale
                    or ""
                ).strip()
                if stock_candidate_count < 2:
                    stock_issues.append("candidateCount<2")
                    missing_stock_candidate_count_scenes.append(scene_id)
                if not stock_creator:
                    stock_issues.append("creator")
                    missing_stock_candidate_creator_scenes.append(scene_id)
                if not stock_source:
                    stock_issues.append("sourceUrlOrId")
                    missing_stock_candidate_source_scenes.append(scene_id)
                if len(stock_summary) < 24:
                    stock_issues.append("selectionSummary")
                    missing_stock_selection_summary_scenes.append(scene_id)
                if stock_issues:
                    missing_stock_candidate_curation_scenes.append(scene_id)
                    stock_candidate_curation_issues_by_scene[scene_id] = stock_issues
                    caveats.append(f"missing selected stock candidate curation evidence: {stock_issues}")
                else:
                    stock_candidate_curation_ready_scenes.append(scene_id)
            elif provider == "upload" and source_intent == "grok":
                grok_handoff_scenes += 1
                grok_handoff_scene_ids.append(scene_id)
                upload_originality_status = "grok-handoff"
                is_original_video = True
            elif (
                provider in LOCAL_ORIGINAL_VIDEO_INTENTS
                or source_intent in LOCAL_ORIGINAL_VIDEO_INTENTS
            ):
                local_model_video_scenes += 1
                local_model_video_scene_ids.append(scene_id)
                upload_originality_status = "local-model"
                is_original_video = True
            elif provider == "upload":
                uploaded_video_scenes += 1
                uploaded_video_scene_ids.append(scene_id)
                is_original_video, upload_originality_status = _uploaded_video_originality_status(
                    scene,
                    visual_asset,
                    source_intent,
                )
                if not is_original_video:
                    weak_uploaded_originality_scenes.append(scene_id)
                    if upload_originality_status == "procedural-placeholder":
                        procedural_placeholder_scenes.append(scene_id)
                        caveats.append("uploaded MP4 appears to be procedural/test-pattern placeholder, not owned footage")
                    elif upload_originality_status == "stock-rewrapped-upload":
                        caveats.append("uploaded MP4 retains stock/free-source provenance, not owned footage")
                    else:
                        caveats.append("uploaded MP4 lacks owned/direct source proof")
        else:
            image_fallback_scenes += 1
            image_fallback_scene_ids.append(scene_id)
            caveats.append("image fallback")

        visual_identity = _visual_asset_identity(visual_asset)
        if visual_identity:
            first_seen_scene = visual_identity_first_seen.get(visual_identity)
            if first_seen_scene and first_seen_scene != scene_id:
                repeated_visual_asset_scenes.append(scene_id)
                caveats.append(f"reused visual asset from {first_seen_scene}")
            else:
                visual_identity_first_seen[visual_identity] = scene_id

        if provider in FREE_STOCK_PROVIDERS:
            if _asset_has_license_provenance(visual_asset):
                free_asset_provenance_scenes.append(scene_id)
            else:
                missing_free_asset_provenance_scenes.append(scene_id)
                caveats.append("missing free visual asset provenance")

        narration_length = _compact_text_length(narration_text)
        subtitle_length = _compact_text_length(subtitle_text)
        narration_meta_terms = _production_meta_terms(narration_text)
        subtitle_meta_terms = _production_meta_terms(subtitle_text)
        caption_duration = _scene_caption_duration(scene)
        min_chars = _required_narration_chars(content_template, scene_id, first_scene_id)
        narration_min_chars_by_scene[scene_id] = min_chars
        if narration_text and audio_design_mode == "no-voice":
            audio_design_mode = "voiceover"
        audio_design_modes_by_scene[scene_id] = audio_design_mode
        if narration_text:
            narration_scenes.append(scene_id)
            if narration_length < min_chars:
                thin_narration_scenes.append(scene_id)
                caveats.append(f"thin narration for TTS ({narration_length}/{min_chars})")
            if narration_meta_terms:
                production_meta_narration_scenes.append(scene_id)
                production_meta_terms_by_scene[scene_id] = narration_meta_terms
                caveats.append(f"viewer-facing narration contains production meta terms: {narration_meta_terms}")
        else:
            if audio_design_mode == "no-voice":
                no_voice_audio_design_scenes.append(scene_id)
                if content_template in VOICEOVER_REQUIRED_TEMPLATES and not visual_led_no_voice_approved:
                    voiceover_required_no_voice_scenes.append(scene_id)
                    caveats.append(
                        "information/ranking template requires viewer-facing TTS/voiceover unless visual-led no-voice is explicitly human-approved"
                    )
                elif visual_led_no_voice_approved:
                    visual_led_no_voice_approved_scenes.append(scene_id)
                if not (global_audio_bed_available or scene_id in audio_bed_scene_ids):
                    missing_no_voice_audio_scenes.append(scene_id)
                    caveats.append("no-voice audio design lacks BGM, ambience, native audio, or SFX bed")
                if not audio_mix_review_note:
                    missing_no_voice_audio_review_scenes.append(scene_id)
                    caveats.append("no-voice audio design needs an audio mix review note")
            else:
                missing_narration_scenes.append(scene_id)
                if subtitle_text:
                    subtitle_only_narration_scenes.append(scene_id)
                    caveats.append("subtitle text is not TTS narration evidence")
                else:
                    caveats.append("missing TTS narration")
        if subtitle_meta_terms:
            production_meta_subtitle_scenes.append(scene_id)
            existing_terms = production_meta_terms_by_scene.get(scene_id, [])
            production_meta_terms_by_scene[scene_id] = sorted(set(existing_terms + subtitle_meta_terms))
            caveats.append(f"display caption contains production meta terms: {subtitle_meta_terms}")

        if is_original_video:
            original_clip_scene_ids.append(scene_id)

        if not rationale:
            missing_rationale.append(scene_id)
            caveats.append("missing source rationale")
        if not continuity:
            missing_continuity.append(scene_id)
            caveats.append("missing continuity note")
        if is_original_video:
            if originality_evidence:
                originality_evidence_scenes.append(scene_id)
            else:
                missing_originality_evidence.append(scene_id)
                caveats.append("missing originality evidence")
        if quality_review_note:
            quality_review_scenes.append(scene_id)
        else:
            missing_quality_review.append(scene_id)
            caveats.append("missing channel quality review")
        if visual_quality_verdict_status == "pass":
            visual_verdict_scenes.append(scene_id)
        elif visual_quality_verdict_status == "fail":
            failed_visual_verdict_scenes.append(scene_id)
            caveats.append(f"manual visual verdict is {visual_quality_verdict}")
        else:
            missing_visual_verdict_scenes.append(scene_id)
            caveats.append("missing explicit pass/fail visual verdict")
        if _caption_layout_reviewed(caption_preset, quality_review_note):
            caption_layout_review_scenes.append(scene_id)
        else:
            missing_caption_layout_review_scenes.append(scene_id)
            caveats.append("missing caption layout review")
        stock_or_ai_fit_verdict_required = (
            provider in FREE_STOCK_PROVIDERS
            or "stock" in _normalized_source_tag(source_intent)
            or source_provenance.get("notOwnedFootage") is True
        )
        if stock_or_ai_fit_verdict_required:
            if stock_ai_clip_fit_verdict_status == "pass":
                stock_ai_clip_fit_verdict_scenes.append(scene_id)
            elif stock_ai_clip_fit_verdict_status == "fail":
                failed_stock_ai_clip_fit_verdict_scenes.append(scene_id)
                caveats.append(f"stock/AI clip fit verdict is {stock_ai_clip_fit_verdict}")
            else:
                missing_stock_ai_clip_fit_verdict_scenes.append(scene_id)
                caveats.append("missing explicit stock/AI clip fit verdict")
        if caption_preset != "none" and subtitle_text:
            captioned_scene_ids.append(scene_id)
            density_issue = _caption_density_issue(caption_preset, subtitle_text)
            if density_issue:
                caption_density_issue_scenes.append(scene_id)
                caption_density_issues_by_scene[scene_id] = density_issue
                caveats.append(density_issue)
            if caption_preset == "top-hook" and caption_duration > 2.6:
                long_top_hook_scenes.append(scene_id)
                caveats.append(f"top-hook caption runs too long ({caption_duration:.1f}s)")
        if thumbnail_review_note:
            thumbnail_review_scenes.append(scene_id)
        if audio_mix_review_note:
            audio_mix_review_scenes.append(scene_id)
        if platform_comparison_note:
            platform_comparison_scenes.append(scene_id)
        if layout_variant_key:
            layout_variant_scenes.append(scene_id)
            layout_variant_counts[layout_variant_key] = layout_variant_counts.get(layout_variant_key, 0) + 1
        elif requires_layout_variant:
            missing_layout_variant_scenes.append(scene_id)
            caveats.append("missing layout variant evidence")
        if local_media_result.get("status") == "placeholder":
            caveats.append("placeholder media")

        provenance = {
            "sourceGenerator": source_generator,
            "sourceGeneratorRequestPath": source_generator_request_path,
            "sourceGeneratorPromptPath": source_generator_prompt_path,
            "sourceGeneratorLogPath": source_generator_log_path,
            "sourceGeneratorCommand": source_generator_command,
        }
        if is_original_video and (
            source_generator
            or source_generator_request_path
            or source_generator_prompt_path
            or source_generator_log_path
        ):
            provenance["hasGeneratorProvenance"] = True
        else:
            provenance["hasGeneratorProvenance"] = False

        scenes_payload.append(
            {
                "sceneId": scene_id,
                "visualKind": visual_kind,
                "visualProvider": provider,
                "sourceOrigin": source_origin,
                "sourceIntent": source_intent,
                "sourceRationale": rationale,
                "continuityNote": continuity,
                "hookNote": hook_note,
                "narrationTextLength": narration_length,
                "subtitleTextLength": subtitle_length,
                "requiredNarrationTextLength": min_chars,
                "audioDesignMode": audio_design_mode,
                "voiceoverRequiredNoVoice": scene_id in voiceover_required_no_voice_scenes,
                "visualLedNoVoiceApproved": visual_led_no_voice_approved,
                "subtitleOnlyNarrationFallback": bool(
                    subtitle_text and not narration_text and audio_design_mode != "no-voice"
                ),
                "productionMetaNarrationTerms": narration_meta_terms,
                "productionMetaSubtitleTerms": subtitle_meta_terms,
                "captionPreset": caption_preset,
                "captionDurationSec": caption_duration,
                "originalityEvidence": originality_evidence,
                "qualityReviewNote": quality_review_note,
                "thumbnailReviewNote": thumbnail_review_note,
                "audioMixReviewNote": audio_mix_review_note,
                "platformComparisonNote": platform_comparison_note,
                "visualQualityVerdict": visual_quality_verdict,
                "visualQualityVerdictStatus": visual_quality_verdict_status,
                "stockAiClipFitVerdict": stock_ai_clip_fit_verdict,
                "stockAiClipFitVerdictStatus": stock_ai_clip_fit_verdict_status,
                "grokSourceReviewVerdict": grok_source_review_verdict,
                "grokSourceReviewVerdictStatus": grok_source_review_verdict_status,
                "layoutVariantKey": layout_variant_key,
                "layoutVariantLabel": layout_variant_label,
                "layoutVariantNote": layout_variant_note,
                "candidateCount": grok_candidate_count if is_grok_handoff_source else (
                    _positive_int_metadata(visual_asset.get("candidateCount"))
                    if provider == "pexels-video"
                    else 0
                ),
                "selectedFileName": selected_file_name,
                "selectedCandidateSummary": selected_candidate_summary
                or str(visual_asset.get("selectedCandidateSummary") or visual_asset.get("selectionRationale") or "").strip(),
                "sourceProvenanceStatus": source_provenance_status,
                "sourceProvenanceConfirmed": source_provenance_confirmed,
                "sourceProvenanceNote": source_provenance_note,
                "uploadOriginalityStatus": upload_originality_status,
                "localGenerationProvenance": provenance,
                "grokSourceCuration": {
                    "required": is_grok_handoff_source,
                    "ready": is_grok_handoff_source and not grok_source_curation_issues,
                    "candidateCount": grok_candidate_count,
                    "selectedFileName": selected_file_name,
                    "selectedCandidateSummaryReady": len(selected_candidate_summary) >= 24,
                    "sourceProvenanceStatus": source_provenance_status,
                    "sourceProvenanceAcceptable": bool(source_provenance)
                    and source_provenance.get("acceptAsGrokMainSource") is not False
                    and source_provenance_status in GROK_SOURCE_PROVENANCE_ACCEPTABLE_STATUSES,
                    "sourceProvenanceConfirmationRequired": source_provenance_requires_confirmation,
                    "sourceProvenanceConfirmed": source_provenance_confirmed,
                    "sourceProvenanceNoteReady": len(source_provenance_note) >= 24,
                    "sourceReviewVerdict": grok_source_review_verdict,
                    "sourceReviewVerdictStatus": grok_source_review_verdict_status,
                    "issues": grok_source_curation_issues,
                },
                "caveats": caveats,
            }
        )

    first_scene = scenes[0] if scenes else {}
    first_scene_hook_ready = (
        bool(scenes)
        and (
            _text_present(first_scene.get("hookNote"))
            or first_scene.get("captionPreset") == "top-hook"
        )
        and (_text_present(first_scene.get("title")) or _text_present(first_scene.get("subtitleText")))
    )
    stock_only = (
        bool(scenes)
        and stock_video_scenes == len(scenes)
        and uploaded_video_scenes == 0
        and grok_handoff_scenes == 0
        and local_model_video_scenes == 0
        and image_fallback_scenes == 0
    )
    curated_stock_ready = (
        stock_only
        and not missing_rationale
        and not missing_continuity
        and first_scene_hook_ready
    )
    caption_sparse_plan = (
        len(scenes) >= 4
        and len(captioned_scene_ids) <= 1
        and int(caption_preset_counts.get("none", 0) or 0) >= len(scenes) - 1
    )
    shorts_cut_density_ready = (
        len(scenes) < 4
        or (
            video_scenes >= 4
            and image_fallback_scenes == 0
            and not repeated_visual_asset_scenes
        )
    )
    first_scene_id = str(first_scene.get("sceneId") or "scene-01")
    thumbnail_first_frame_ready = first_scene_id in thumbnail_review_scenes and first_scene_hook_ready
    min_original_scene_count = 1 if len(scenes) <= 1 else max(2, (len(scenes) + 1) // 2)
    source_mix_required = len(scenes) > 1 and content_template in UPLOAD_SOURCE_MIX_REQUIRED_TEMPLATES
    original_source_mix_ready = len(set(original_clip_scene_ids)) >= min_original_scene_count
    stock_source_mix_gap_scene_ids = (
        list(stock_video_scene_ids)
        if source_mix_required and not original_source_mix_ready and stock_video_scenes > 0
        else []
    )
    ai_slop_visual_fit_status = (
        "fail"
        if failed_visual_verdict_scenes
        else "warn"
        if missing_visual_verdict_scenes
        else "pass"
    )
    stock_ai_clip_fit_status = (
        "fail"
        if (
            procedural_placeholder_scenes
            or failed_visual_verdict_scenes
            or stock_source_mix_gap_scene_ids
            or failed_stock_ai_clip_fit_verdict_scenes
            or missing_stock_ai_clip_fit_verdict_scenes
        )
        else "warn"
        if stock_only or weak_uploaded_originality_scenes or missing_visual_verdict_scenes
        else "pass"
    )

    return {
        "summary": {
            "totalScenes": len(scenes),
            "videoScenes": video_scenes,
            "stockVideoScenes": stock_video_scenes,
            "uploadedVideoScenes": uploaded_video_scenes,
            "grokHandoffScenes": grok_handoff_scenes,
            "localModelVideoScenes": local_model_video_scenes,
            "imageFallbackScenes": image_fallback_scenes,
            "stockVideoSceneIds": stock_video_scene_ids,
            "uploadedVideoSceneIds": uploaded_video_scene_ids,
            "grokHandoffSceneIds": grok_handoff_scene_ids,
            "localModelVideoSceneIds": local_model_video_scene_ids,
            "originalClipSceneIds": original_clip_scene_ids,
            "originalSourceMixRequired": source_mix_required,
            "originalSourceMixReady": original_source_mix_ready,
            "minOriginalScenesForSourceMix": min_original_scene_count,
            "stockSourceMixGapSceneIds": stock_source_mix_gap_scene_ids,
            "weakUploadedOriginalityScenes": weak_uploaded_originality_scenes,
            "proceduralPlaceholderScenes": procedural_placeholder_scenes,
            "imageFallbackSceneIds": image_fallback_scene_ids,
            "missingRationaleScenes": missing_rationale,
            "missingContinuityScenes": missing_continuity,
            "missingOriginalityEvidenceScenes": missing_originality_evidence,
            "missingQualityReviewScenes": missing_quality_review,
            "originalityEvidenceScenes": originality_evidence_scenes,
            "qualityReviewScenes": quality_review_scenes,
            "thumbnailReviewScenes": thumbnail_review_scenes,
            "audioMixReviewScenes": audio_mix_review_scenes,
            "platformComparisonScenes": platform_comparison_scenes,
            "visualVerdictScenes": visual_verdict_scenes,
            "missingVisualVerdictScenes": missing_visual_verdict_scenes,
            "failedVisualVerdictScenes": failed_visual_verdict_scenes,
            "stockAiClipFitVerdictScenes": stock_ai_clip_fit_verdict_scenes,
            "missingStockAiClipFitVerdictScenes": missing_stock_ai_clip_fit_verdict_scenes,
            "failedStockAiClipFitVerdictScenes": failed_stock_ai_clip_fit_verdict_scenes,
            "layoutVariantScenes": layout_variant_scenes,
            "missingLayoutVariantScenes": missing_layout_variant_scenes,
            "layoutVariantCounts": layout_variant_counts,
            "narrationScenes": narration_scenes,
            "subtitleOnlyNarrationScenes": subtitle_only_narration_scenes,
            "missingNarrationScenes": missing_narration_scenes,
            "thinNarrationScenes": thin_narration_scenes,
            "productionMetaNarrationScenes": production_meta_narration_scenes,
            "productionMetaSubtitleScenes": production_meta_subtitle_scenes,
            "productionMetaTermsByScene": production_meta_terms_by_scene,
            "narrationMinCharsByScene": narration_min_chars_by_scene,
            "noVoiceAudioDesignScenes": no_voice_audio_design_scenes,
            "voiceoverRequiredNoVoiceScenes": voiceover_required_no_voice_scenes,
            "visualLedNoVoiceApprovedScenes": visual_led_no_voice_approved_scenes,
            "missingNoVoiceAudioScenes": missing_no_voice_audio_scenes,
            "missingNoVoiceAudioReviewScenes": missing_no_voice_audio_review_scenes,
            "audioDesignModesByScene": audio_design_modes_by_scene,
            "captionedSceneIds": captioned_scene_ids,
            "captionSparsePlan": caption_sparse_plan,
            "longTopHookScenes": long_top_hook_scenes,
            "captionDensityIssueScenes": caption_density_issue_scenes,
            "captionDensityIssuesByScene": caption_density_issues_by_scene,
            "captionSafeZonePolicy": SHORTS_CAPTION_SAFE_ZONE_POLICY,
            "captionMaxCompactChars": SHORTS_CAPTION_MAX_COMPACT_CHARS,
            "captionLayoutReviewScenes": caption_layout_review_scenes,
            "missingCaptionLayoutReviewScenes": missing_caption_layout_review_scenes,
            "captionPresetCounts": caption_preset_counts,
            "repeatedVisualAssetScenes": repeated_visual_asset_scenes,
            "freeAssetProvenanceScenes": free_asset_provenance_scenes,
            "missingFreeAssetProvenanceScenes": missing_free_asset_provenance_scenes,
            "freeAudioProvenanceAssets": free_audio_provenance_assets,
            "missingFreeAudioProvenanceAssets": missing_free_audio_provenance_assets,
            "freeAudioCredits": free_audio_credits,
            "freeAudioCreditMissingAssets": free_audio_credit_missing_assets,
            "youtubeDescriptionAudioCredits": [
                credit["youtubeDescriptionLine"]
                for credit in free_audio_credits
                if credit.get("youtubeDescriptionLine")
            ],
            "bgmSelectionAssets": bgm_selection_assets,
            "weakBgmSelectionAssets": weak_bgm_selection_assets,
            "placeholderBgmAssets": placeholder_bgm_assets,
            "placeholderBgmAssetReasons": placeholder_bgm_asset_reasons,
            "stockCandidateCurationScenes": stock_candidate_curation_scenes,
            "stockCandidateCurationReadyScenes": stock_candidate_curation_ready_scenes,
            "missingStockCandidateCurationScenes": missing_stock_candidate_curation_scenes,
            "missingStockCandidateCountScenes": missing_stock_candidate_count_scenes,
            "missingStockCandidateCreatorScenes": missing_stock_candidate_creator_scenes,
            "missingStockCandidateSourceScenes": missing_stock_candidate_source_scenes,
            "missingStockSelectionSummaryScenes": missing_stock_selection_summary_scenes,
            "stockCandidateCurationIssuesByScene": stock_candidate_curation_issues_by_scene,
            "grokSourceCurationScenes": grok_source_curation_scenes,
            "grokSourceCurationReadyScenes": grok_source_curation_ready_scenes,
            "missingGrokSourceCurationScenes": missing_grok_source_curation_scenes,
            "missingGrokCandidateComparisonScenes": missing_grok_candidate_comparison_scenes,
            "missingGrokSelectedFileScenes": missing_grok_selected_file_scenes,
            "missingGrokSourceProvenanceScenes": missing_grok_source_provenance_scenes,
            "unacceptableGrokSourceProvenanceScenes": unacceptable_grok_source_provenance_scenes,
            "missingGrokSourceConfirmationScenes": missing_grok_source_confirmation_scenes,
            "grokSourceReviewVerdictScenes": grok_source_review_verdict_scenes,
            "rejectedGrokSourceReviewScenes": rejected_grok_source_review_scenes,
            "grokPreviewCaveatScenes": grok_preview_caveat_scenes,
            "firstSceneHookReady": first_scene_hook_ready,
            "shortsCutDensityReady": shorts_cut_density_ready,
            "thumbnailFirstFrameReady": thumbnail_first_frame_ready,
            "aiSlopVisualFitStatus": ai_slop_visual_fit_status,
            "stockAiClipFitStatus": stock_ai_clip_fit_status,
            "stockOnly": stock_only,
            "curatedStockReady": curated_stock_ready,
            "contentTemplate": content_template,
        },
        "scenes": scenes_payload,
    }


def _build_publish_readiness(
    checks: dict,
    production_review: dict,
    local_media_summary: dict,
) -> dict:
    """Convert low-level QA checks into an operator-facing publish gate."""
    production_summary = production_review.get("summary") or {}
    criteria: list[dict] = []
    required_fixes: list[str] = []
    recommended_fixes: list[str] = []
    strengths: list[str] = []

    def add_criterion(
        key: str,
        label: str,
        status: str,
        detail: str,
        fix: str,
        required: bool,
    ) -> None:
        criteria.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "detail": detail,
                "required": required,
            }
        )
        if status == "fail" and required:
            required_fixes.append(fix)
        elif status in {"fail", "warn"} and not required:
            recommended_fixes.append(fix)
        elif status == "pass":
            strengths.append(label)

    def check_status(key: str) -> str:
        return str((checks.get(key) or {}).get("status") or "warn")

    def check_detail(key: str) -> str:
        return str((checks.get(key) or {}).get("detail") or "")

    add_criterion(
        "outputSpec",
        "1080x1920 30fps audio output",
        check_status("outputSpec"),
        check_detail("outputSpec"),
        "Re-render to 1080x1920 at 30fps with an audio stream and positive duration.",
        True,
    )
    add_criterion(
        "noPlaceholders",
        "No placeholder media",
        check_status("noPlaceholders"),
        check_detail("noPlaceholders"),
        "Replace every placeholder with uploaded, Grok handoff, local-model, or curated stock video.",
        True,
    )
    procedural_placeholder_scenes = production_summary.get("proceduralPlaceholderScenes") or []
    add_criterion(
        "proceduralPlaceholderClips",
        "No procedural test-pattern clips",
        "fail" if procedural_placeholder_scenes else "pass",
        f"proceduralPlaceholderScenes={procedural_placeholder_scenes}",
        "Replace color-bar/test-pattern/procedural local-render clips with real uploaded, Grok handoff, local-model, or curated stock MP4s.",
        True,
    )
    add_criterion(
        "movingClipPriority",
        "Uses moving video clips",
        check_status("movingClipPriority"),
        check_detail("movingClipPriority"),
        "Add at least one real video clip before treating this as a finished Shorts/long-form render.",
        True,
    )
    add_criterion(
        "zeroPaidProviders",
        "Zero paid providers",
        check_status("zeroPaidProviders"),
        check_detail("zeroPaidProviders"),
        "Remove paid API/provider assets from the manifest before publishing.",
        True,
    )
    add_criterion(
        "captionSafePresets",
        "Caption safe-zone presets",
        check_status("captionSafePresets"),
        check_detail("captionSafePresets"),
        "Use only none, center-short, top-hook, or lower-info caption presets.",
        True,
    )
    add_criterion(
        "subtitleArtifact",
        "Subtitle artifact exists",
        check_status("subtitleArtifact"),
        check_detail("subtitleArtifact"),
        "Regenerate subtitles so the final render has a matching ASS or SRT artifact.",
        True,
    )
    add_criterion(
        "ttsNarrationEvidence",
        "Intentional audio design",
        check_status("ttsNarrationEvidence"),
        check_detail("ttsNarrationEvidence"),
        "Use natural viewer-facing narration only when it helps; for Grok-first raw footage, mark no-voice audio design and keep BGM/native audio plus mix review evidence.",
        True,
    )
    voiceover_required_no_voice = production_summary.get("voiceoverRequiredNoVoiceScenes") or []
    add_criterion(
        "voicePolicyCompliance",
        "Template voice policy compliance",
        "fail" if voiceover_required_no_voice else "pass",
        (
            f"voiceoverRequiredNoVoiceScenes={voiceover_required_no_voice}, "
            f"visualLedNoVoiceApprovedScenes={production_summary.get('visualLedNoVoiceApprovedScenes') or []}"
        ),
        "Add TTS/voiceover for information, ranking, and list templates, or record explicit human approval that the scene is visual-led no-voice.",
        True,
    )
    add_criterion(
        "captionLayoutReview",
        "Caption layout and subject-clear review",
        check_status("captionLayoutReview"),
        check_detail("captionLayoutReview"),
        "Choose no caption, top hook, center short caption, or lower info intentionally and record that captions do not cover the subject or Shorts UI.",
        True,
    )
    add_criterion(
        "captionDensityAndSafeZone",
        "Caption density and Shorts safe-zone fit",
        check_status("captionDensityAndSafeZone"),
        check_detail("captionDensityAndSafeZone"),
        "Shorten burned-in captions and keep lower captions in the lower-mid Shorts safe zone instead of the bottom UI area.",
        True,
    )
    add_criterion(
        "grokSourceCuration",
        "Grok-main selected take and source provenance",
        check_status("grokSourceCuration"),
        check_detail("grokSourceCuration"),
        "Before publish, every Grok-main scene must carry 2-take comparison, selected MP4 filename, direct-import or already-saved-local provenance, and no rejected source review verdict.",
        True,
    )

    image_fallback_scenes = int(production_summary.get("imageFallbackScenes", 0) or 0)
    stock_only = bool(production_summary.get("stockOnly"))
    curated_stock_ready = bool(production_summary.get("curatedStockReady"))
    missing_rationale = production_summary.get("missingRationaleScenes") or []
    missing_continuity = production_summary.get("missingContinuityScenes") or []
    originality_evidence_scenes = production_summary.get("originalityEvidenceScenes") or []
    quality_review_scenes = production_summary.get("qualityReviewScenes") or []
    missing_originality_evidence = production_summary.get("missingOriginalityEvidenceScenes") or []
    missing_quality_review = production_summary.get("missingQualityReviewScenes") or []
    first_hook_ready = bool(production_summary.get("firstSceneHookReady"))
    repeated_visual_asset_scenes = production_summary.get("repeatedVisualAssetScenes") or []
    missing_free_asset_provenance = production_summary.get("missingFreeAssetProvenanceScenes") or []
    missing_free_audio_provenance = production_summary.get("missingFreeAudioProvenanceAssets") or []
    missing_free_audio_credits = production_summary.get("freeAudioCreditMissingAssets") or []
    weak_bgm_selection_assets = production_summary.get("weakBgmSelectionAssets") or []
    placeholder_bgm_assets = production_summary.get("placeholderBgmAssets") or []
    placeholder_bgm_reasons = production_summary.get("placeholderBgmAssetReasons") or {}
    template_source_review = production_review.get("templateSourceReview") or {}
    cut_density_ready = production_summary.get("shortsCutDensityReady") is True
    ai_slop_status = check_status("aiSlopVisualFit")
    stock_ai_fit_status = check_status("stockAiClipFit")
    thumbnail_strength_status = check_status("thumbnailFirstFrameStrength")

    add_criterion(
        "imageFallback",
        "Video-first scene mix",
        "warn" if image_fallback_scenes else "pass",
        f"imageFallbackScenes={image_fallback_scenes}",
        "Replace static fallback scenes with short MP4 clips unless the still frame is intentional.",
        False,
    )
    add_criterion(
        "sourceAuthorship",
        "Creator-owned or generated source mix",
        "warn" if stock_only else "pass",
        f"stockOnly={stock_only}, curatedStockReady={curated_stock_ready}",
        "Keep stock-only curated exports as review drafts; add direct upload, Grok handoff, or local Wan/LTX/Hunyuan footage before marking the render publish-ready.",
        False,
    )
    add_criterion(
        "manualSelectionEvidence",
        "Manual source rationale",
        "warn" if missing_rationale else "pass",
        f"missingRationaleScenes={missing_rationale}",
        "Fill source-rationale notes for every scene so stock and generated clips have a selection reason.",
        False,
    )
    add_criterion(
        "continuityEvidence",
        "Scene continuity notes",
        "warn" if missing_continuity else "pass",
        f"missingContinuityScenes={missing_continuity}",
        "Add continuity notes for color, camera motion, subject, and prop consistency across scenes.",
        False,
    )
    add_criterion(
        "firstTwoSecondHook",
        "First two-second hook",
        "pass" if first_hook_ready else "warn",
        f"firstSceneHookReady={first_hook_ready}",
        "Strengthen the first scene with a visible hook note or top-hook caption and an immediate visual payoff.",
        False,
    )
    add_criterion(
        "cutDensityPacing",
        "Shorts cut density and pacing",
        "pass" if cut_density_ready else "warn",
        check_detail("cutDensityPacing"),
        "Use at least four distinct moving clips for short-form operating templates unless a slower visual-led edit is explicitly approved.",
        False,
    )
    add_criterion(
        "aiSlopVisualFit",
        "AI slop / visual artifact fit",
        "fail" if ai_slop_status == "fail" else "pass",
        check_detail("aiSlopVisualFit"),
        "Separate visual artifact, AI-slop, watermark, compression, and subject-fit failures from generic render success before upload review.",
        ai_slop_status == "fail",
    )
    add_criterion(
        "stockAiClipFit",
        "Stock/AI clip source fit",
        "fail" if stock_ai_fit_status == "fail" else "pass",
        check_detail("stockAiClipFit"),
        "Replace mismatched stock/AI clips or record why each clip fits the topic, motion, and continuity.",
        stock_ai_fit_status == "fail",
    )
    add_criterion(
        "thumbnailFirstFrameStrength",
        "Thumbnail / first-frame strength",
        "pass",
        check_detail("thumbnailFirstFrameStrength"),
        "Pick a strong first-frame or thumbnail candidate instead of assuming the render's first frame is channel-ready.",
        False,
    )
    add_criterion(
        "assetReuseDiversity",
        "No repeated visual asset reuse",
        "pass" if not repeated_visual_asset_scenes else "warn",
        f"repeatedVisualAssetScenes={repeated_visual_asset_scenes}",
        "Replace repeated visual assets with distinct free stock/direct/Grok/local clips so the result does not feel recycled.",
        False,
    )
    add_criterion(
        "freeAssetProvenance",
        "Free visual/audio source provenance",
        "pass" if not missing_free_asset_provenance and not missing_free_audio_provenance and not missing_free_audio_credits else "warn",
        (
            f"missingFreeAssetProvenanceScenes={missing_free_asset_provenance}, "
            f"missingFreeAudioProvenanceAssets={missing_free_audio_provenance}, "
            f"freeAudioCreditMissingAssets={missing_free_audio_credits}"
        ),
        "Keep source URL/ID/label for free stock assets and source/license/YouTube description credits for BGM/SFX before publishing.",
        False,
    )
    add_criterion(
        "bgmAssetRotation",
        "BGM selected from reusable free-library candidates",
        "pass" if not weak_bgm_selection_assets else "warn",
        f"weakBgmSelectionAssets={weak_bgm_selection_assets}",
        "Add at least two free/local BGM candidates per mood, or pin an operator-selected free BGM with source/license metadata for this project.",
        False,
    )
    add_criterion(
        "bgmSoundQuality",
        "BGM is not beep/test-tone/procedural",
        "fail" if placeholder_bgm_assets else "pass",
        f"placeholderBgmAssets={placeholder_bgm_assets}, reasons={placeholder_bgm_reasons}",
        "Replace procedural sine, beep, click, lavfi, or test-tone BGM with a real free music bed before upload review.",
        True,
    )
    add_criterion(
        "templateSourcePlan",
        "Template-specific source mix",
        check_status("templateSourcePlan"),
        check_detail("templateSourcePlan"),
        "Match the selected Korean YouTube template with an intentional source mix, free asset plan, and layout proof.",
        False,
    )

    passed = sum(1 for item in criteria if item["status"] == "pass")
    total = len(criteria)
    if required_fixes:
        status = "blocked"
    elif recommended_fixes:
        status = "needs-rework"
    else:
        status = "ready"

    return {
        "status": status,
        "score": {"passed": passed, "total": total},
        "requiredFixes": required_fixes,
        "recommendedFixes": recommended_fixes,
        "strengths": strengths[:6],
        "criteria": criteria,
        "summary": {
            "placeholderCount": int(local_media_summary.get("placeholder", 0) or 0),
            "imageFallbackScenes": image_fallback_scenes,
            "stockOnly": stock_only,
            "curatedStockReady": curated_stock_ready,
            "missingRationaleScenes": missing_rationale,
            "missingContinuityScenes": missing_continuity,
            "firstSceneHookReady": first_hook_ready,
            "repeatedVisualAssetScenes": repeated_visual_asset_scenes,
            "missingFreeAssetProvenanceScenes": missing_free_asset_provenance,
            "missingFreeAudioProvenanceAssets": missing_free_audio_provenance,
            "weakBgmSelectionAssets": weak_bgm_selection_assets,
            "placeholderBgmAssets": placeholder_bgm_assets,
            "placeholderBgmAssetReasons": placeholder_bgm_reasons,
            "proceduralPlaceholderScenes": procedural_placeholder_scenes,
            "missingGrokSourceCurationScenes": production_summary.get("missingGrokSourceCurationScenes") or [],
            "grokSourceCurationReadyScenes": production_summary.get("grokSourceCurationReadyScenes") or [],
            "rejectedGrokSourceReviewScenes": production_summary.get("rejectedGrokSourceReviewScenes") or [],
            "templateSourceReview": template_source_review,
        },
    }


def _audio_design_ready(production_summary: dict) -> bool:
    """Accept either real voiceover narration or explicit no-voice audio design."""
    return not (
        production_summary.get("missingNarrationScenes")
        or production_summary.get("thinNarrationScenes")
        or production_summary.get("productionMetaNarrationScenes")
        or production_summary.get("productionMetaSubtitleScenes")
        or production_summary.get("voiceoverRequiredNoVoiceScenes")
        or production_summary.get("missingNoVoiceAudioScenes")
        or production_summary.get("missingNoVoiceAudioReviewScenes")
    )


def _build_channel_readiness(
    publish_readiness: dict,
    production_review: dict,
    local_media_summary: dict,
) -> dict:
    """Grade whether a publish-ready render has enough original footage proof for channel use."""
    production_summary = production_review.get("summary") or {}
    publish_status = str(publish_readiness.get("status") or "needs-rework")
    criteria: list[dict] = []
    required_fixes: list[str] = []
    recommended_fixes: list[str] = []
    strengths: list[str] = []

    def add_criterion(
        key: str,
        label: str,
        status: str,
        detail: str,
        fix: str,
        required: bool,
    ) -> None:
        criteria.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "detail": detail,
                "required": required,
            }
        )
        if status == "fail" and required:
            required_fixes.append(fix)
        elif status in {"fail", "warn"} and not required:
            recommended_fixes.append(fix)
        elif status == "pass":
            strengths.append(label)

    uploaded_video_scenes = int(production_summary.get("uploadedVideoScenes", 0) or 0)
    grok_handoff_scenes = int(production_summary.get("grokHandoffScenes", 0) or 0)
    local_model_video_scenes = int(production_summary.get("localModelVideoScenes", 0) or 0)
    stock_video_scenes = int(production_summary.get("stockVideoScenes", 0) or 0)
    total_scenes = int(production_summary.get("totalScenes", 0) or 0)
    original_clip_scene_ids = [str(item) for item in production_summary.get("originalClipSceneIds") or []]
    original_clip_scenes = len(original_clip_scene_ids)
    ai_or_local_clip_scenes = grok_handoff_scenes + local_model_video_scenes
    review_scenes = production_review.get("scenes") or []
    first_scene_id = str((review_scenes[0] if review_scenes else {}).get("sceneId") or "scene-01")
    grok_handoff_scene_ids = [str(item) for item in production_summary.get("grokHandoffSceneIds") or []]
    local_model_video_scene_ids = [str(item) for item in production_summary.get("localModelVideoSceneIds") or []]
    weak_uploaded_originality_scenes = production_summary.get("weakUploadedOriginalityScenes") or []
    procedural_placeholder_scenes = production_summary.get("proceduralPlaceholderScenes") or []
    stock_only = bool(production_summary.get("stockOnly"))
    curated_stock_ready = bool(production_summary.get("curatedStockReady"))
    missing_rationale = production_summary.get("missingRationaleScenes") or []
    missing_continuity = production_summary.get("missingContinuityScenes") or []
    originality_evidence_scenes = production_summary.get("originalityEvidenceScenes") or []
    quality_review_scenes = production_summary.get("qualityReviewScenes") or []
    visual_verdict_scenes = production_summary.get("visualVerdictScenes") or []
    missing_originality_evidence = production_summary.get("missingOriginalityEvidenceScenes") or []
    missing_quality_review = production_summary.get("missingQualityReviewScenes") or []
    missing_visual_verdict = production_summary.get("missingVisualVerdictScenes") or []
    failed_visual_verdict = production_summary.get("failedVisualVerdictScenes") or []
    first_hook_ready = bool(production_summary.get("firstSceneHookReady"))
    narration_ready = _audio_design_ready(production_summary)
    caption_layout_ready = (
        not production_summary.get("missingCaptionLayoutReviewScenes")
        and not production_summary.get("captionSparsePlan")
        and not production_summary.get("longTopHookScenes")
    )
    visual_verdict_ready = total_scenes > 0 and len(visual_verdict_scenes) == total_scenes and not failed_visual_verdict
    asset_diversity_ready = not production_summary.get("repeatedVisualAssetScenes")
    free_asset_provenance_ready = (
        not production_summary.get("missingFreeAssetProvenanceScenes")
        and not production_summary.get("missingFreeAudioProvenanceAssets")
        and not production_summary.get("freeAudioCreditMissingAssets")
    )
    placeholder_bgm_assets = production_summary.get("placeholderBgmAssets") or []
    bgm_rotation_ready = not production_summary.get("weakBgmSelectionAssets") and not placeholder_bgm_assets
    template_source_review = production_review.get("templateSourceReview") or {}
    template_source_ready = template_source_review.get("status") == "pass"
    audio_mix_review_ready = bool(production_summary.get("audioMixReviewScenes"))
    platform_comparison_ready = bool(production_summary.get("platformComparisonScenes"))
    hero_original_clip_ready = first_scene_id in original_clip_scene_ids
    hero_originality_evidence_ready = first_scene_id in originality_evidence_scenes
    hero_ai_or_local_ready = first_scene_id in grok_handoff_scene_ids or first_scene_id in local_model_video_scene_ids

    add_criterion(
        "publishGate",
        "Publish gate already passed",
        "pass" if publish_status == "ready" else "fail",
        f"publishReadiness={publish_status}",
        "Resolve publishReadiness required and recommended fixes before channel-level review.",
        True,
    )
    add_criterion(
        "originalFootageMix",
        "Original or handoff MP4 present",
        "pass" if original_clip_scenes > 0 else "fail",
        (
            f"originalClipScenes={original_clip_scenes}, stockVideoScenes={stock_video_scenes}, "
            f"uploadedVideoScenes={uploaded_video_scenes}, totalScenes={total_scenes}, "
            f"weakUploadedOriginalityScenes={weak_uploaded_originality_scenes}, "
            f"proceduralPlaceholderScenes={procedural_placeholder_scenes}"
        ),
        "Add or prove at least one owned/direct upload, Grok app/web handoff, or local Wan/LTX/Hunyuan MP4 clip before treating this as channel-ready original work.",
        True,
    )
    add_criterion(
        "heroOriginalFootage",
        "First hook scene uses original MP4",
        "pass" if hero_original_clip_ready else "fail",
        f"firstSceneId={first_scene_id}, originalClipSceneIds={original_clip_scene_ids}",
        "Move a direct upload, Grok app/web handoff, or local Wan/LTX/Hunyuan MP4 into the first hook scene before channel upload.",
        True,
    )
    add_criterion(
        "heroOriginalityEvidence",
        "Hero clip originality evidence",
        "pass" if hero_originality_evidence_ready else "fail",
        (
            f"firstSceneId={first_scene_id}, "
            f"originalityEvidenceScenes={originality_evidence_scenes}, "
            f"missingOriginalityEvidenceScenes={missing_originality_evidence}, "
            f"weakUploadedOriginalityScenes={weak_uploaded_originality_scenes}, "
            f"proceduralPlaceholderScenes={procedural_placeholder_scenes}"
        ),
        "Add explicit evidence that the first hook MP4 is direct footage, a Grok app/web handoff, or a local Wan/LTX/Hunyuan generation, including prompt/source notes.",
        True,
    )
    add_criterion(
        "channelQualityReview",
        "Per-scene channel quality review",
        "pass" if total_scenes > 0 and len(quality_review_scenes) == total_scenes else "fail",
        f"qualityReviewScenes={quality_review_scenes}, missingQualityReviewScenes={missing_quality_review}",
        "Complete channel quality review notes for every scene: subject visibility, caption occlusion, watermark/compression, cut continuity, and platform fit.",
        True,
    )
    add_criterion(
        "manualVisualVerdict",
        "Explicit pass/fail visual verdict",
        "pass" if visual_verdict_ready else "fail",
        (
            f"visualVerdictScenes={visual_verdict_scenes}, "
            f"missingVisualVerdictScenes={missing_visual_verdict}, "
            f"failedVisualVerdictScenes={failed_visual_verdict}"
        ),
        "Watch the render/contact sheet and set an explicit visualQualityVerdict=pass per scene; free-text notes alone cannot mark a weak video channel-ready.",
        True,
    )
    add_criterion(
        "ttsNarrationEvidence",
        "Audio design or viewer-facing narration present",
        "pass" if narration_ready else "fail",
        (
            f"narrationScenes={production_summary.get('narrationScenes') or []}, "
            f"subtitleOnlyNarrationScenes={production_summary.get('subtitleOnlyNarrationScenes') or []}, "
            f"missingNarrationScenes={production_summary.get('missingNarrationScenes') or []}, "
            f"thinNarrationScenes={production_summary.get('thinNarrationScenes') or []}, "
            f"noVoiceAudioDesignScenes={production_summary.get('noVoiceAudioDesignScenes') or []}, "
            f"voiceoverRequiredNoVoiceScenes={production_summary.get('voiceoverRequiredNoVoiceScenes') or []}, "
            f"visualLedNoVoiceApprovedScenes={production_summary.get('visualLedNoVoiceApprovedScenes') or []}, "
            f"missingNoVoiceAudioScenes={production_summary.get('missingNoVoiceAudioScenes') or []}, "
            f"missingNoVoiceAudioReviewScenes={production_summary.get('missingNoVoiceAudioReviewScenes') or []}, "
            f"productionMetaNarrationScenes={production_summary.get('productionMetaNarrationScenes') or []}, "
            f"requiredChars={production_summary.get('narrationMinCharsByScene') or {}}"
        ),
        "Use viewer-facing Edge/Windows TTS only when narration helps; otherwise mark an intentional no-voice design with BGM/native audio and mix review evidence.",
        True,
    )
    add_criterion(
        "bgmSoundQuality",
        "BGM is not beep/test-tone/procedural",
        "pass" if not placeholder_bgm_assets else "fail",
        (
            f"placeholderBgmAssets={placeholder_bgm_assets}, "
            f"reasons={production_summary.get('placeholderBgmAssetReasons') or {}}"
        ),
        "Replace procedural sine, beep, click, lavfi, or test-tone BGM with a real free music bed before upload review.",
        True,
    )
    add_criterion(
        "captionLayoutReview",
        "Caption layout does not cover subject/UI",
        "pass" if caption_layout_ready else "fail",
        (
            f"missingCaptionLayoutReviewScenes={production_summary.get('missingCaptionLayoutReviewScenes') or []}, "
            f"captionSparsePlan={production_summary.get('captionSparsePlan')}, "
            f"longTopHookScenes={production_summary.get('longTopHookScenes') or []}"
        ),
        "Record caption layout review, avoid one long hook plus empty caption plan, and keep lower-info y<=1536 / right-side danger zone clear.",
        True,
    )
    add_criterion(
        "assetReuseDiversity",
        "Distinct visual assets across scenes",
        "pass" if asset_diversity_ready else "fail",
        f"repeatedVisualAssetScenes={production_summary.get('repeatedVisualAssetScenes') or []}",
        "Replace repeated clip/image reuse with distinct free stock, direct, Grok, or local-model assets.",
        True,
    )
    add_criterion(
        "freeAssetProvenance",
        "Free asset source/license provenance",
        "pass" if free_asset_provenance_ready else "fail",
        (
            f"missingFreeAssetProvenanceScenes={production_summary.get('missingFreeAssetProvenanceScenes') or []}, "
            f"missingFreeAudioProvenanceAssets={production_summary.get('missingFreeAudioProvenanceAssets') or []}, "
            f"freeAudioCreditMissingAssets={production_summary.get('freeAudioCreditMissingAssets') or []}"
        ),
        "Keep source URL/ID/label for each free stock scene and BGM/SFX source/license/description-credit notes so the operator can verify rights and avoid blind reuse.",
        True,
    )
    add_criterion(
        "bgmAssetRotation",
        "BGM rotation evidence",
        "pass" if bgm_rotation_ready else "warn",
        (
            f"weakBgmSelectionAssets={production_summary.get('weakBgmSelectionAssets') or []}, "
            f"placeholderBgmAssets={placeholder_bgm_assets}"
        ),
        "Use at least two free/local BGM candidates per mood, or keep an operator-pinned BGM choice with source/license metadata before final upload review.",
        False,
    )
    add_criterion(
        "aiOrLocalClipEvidence",
        "Grok or local AI clip evidence",
        "pass" if ai_or_local_clip_scenes > 0 else "warn",
        f"grokHandoffScenes={grok_handoff_scenes}, localModelVideoScenes={local_model_video_scenes}",
        "For top-tier AI-assisted Shorts/long-form, replace one hero scene with a Grok app/web MP4 or local Wan/LTX/Hunyuan output and keep its prompt/rationale.",
        False,
    )
    add_criterion(
        "heroAiOrLocalEvidence",
        "First hook has Grok/local AI option",
        "pass" if hero_ai_or_local_ready else "warn",
        (
            f"firstSceneId={first_scene_id}, grokHandoffSceneIds={grok_handoff_scene_ids}, "
            f"localModelVideoSceneIds={local_model_video_scene_ids}"
        ),
        "For AI-assisted channel targets, prefer the first hook scene as the Grok app/web or local Wan/LTX/Hunyuan MP4.",
        False,
    )
    add_criterion(
        "manualCurationEvidence",
        "Manual curation notes complete",
        "pass" if not missing_rationale and not missing_continuity else "warn",
        f"missingRationaleScenes={missing_rationale}, missingContinuityScenes={missing_continuity}",
        "Complete source rationale and continuity notes for every scene before channel release.",
        False,
    )
    add_criterion(
        "firstTwoSecondHook",
        "First two-second hook survives channel review",
        "pass" if first_hook_ready else "warn",
        f"firstSceneHookReady={first_hook_ready}",
        "Tighten the first two seconds with an immediate visual payoff and a safe-zone hook.",
        False,
    )
    add_criterion(
        "stockOnlyOriginality",
        "Not stock-only",
        "pass" if not stock_only else "warn",
        f"stockOnly={stock_only}, curatedStockReady={curated_stock_ready}",
        "Keep curated stock as support footage, but add original/direct/Grok/local footage for a channel-owned final.",
        False,
    )
    add_criterion(
        "audioMixReview",
        "Audio mix review recorded",
        "pass" if audio_mix_review_ready else "warn",
        f"audioMixReviewScenes={production_summary.get('audioMixReviewScenes') or []}",
        "Watch once with headphones and speakers; confirm BGM/native audio is audible, and confirm narration stays intelligible when voiceover is used.",
        False,
    )
    add_criterion(
        "platformComparison",
        "Korean YouTube reference comparison recorded",
        "pass" if platform_comparison_ready else "warn",
        f"platformComparisonScenes={production_summary.get('platformComparisonScenes') or []}",
        "Compare hook, pacing, caption scale, and asset fit against current Korean Shorts/long-form references before upload.",
        False,
    )

    recommended_fixes.append(
        "Before upload, review thumbnail/first-frame choice and audio mix against the final platform target."
    )

    passed = sum(1 for item in criteria if item["status"] == "pass")
    total = len(criteria)
    if publish_status == "blocked":
        status = "blocked"
    elif publish_status != "ready":
        status = "needs-publish-rework"
    elif original_clip_scenes == 0 and weak_uploaded_originality_scenes:
        status = "needs-originality-proof"
    elif original_clip_scenes == 0:
        status = "needs-original-footage"
    elif not hero_original_clip_ready:
        status = "needs-hero-original-footage"
    elif not hero_originality_evidence_ready:
        status = "needs-originality-proof"
    elif total_scenes <= 0 or len(quality_review_scenes) != total_scenes:
        status = "needs-quality-review"
    elif not visual_verdict_ready:
        status = "needs-visual-verdict"
    elif not narration_ready or not caption_layout_ready or not asset_diversity_ready or not free_asset_provenance_ready or not template_source_ready:
        status = "needs-top-tier-evidence"
    else:
        status = "channel-ready"

    return {
        "status": status,
        "score": {"passed": passed, "total": total},
        "requiredFixes": required_fixes,
        "recommendedFixes": recommended_fixes,
        "strengths": strengths[:6],
        "criteria": criteria,
        "summary": {
            "publishStatus": publish_status,
            "totalScenes": total_scenes,
            "originalClipScenes": original_clip_scenes,
            "firstSceneId": first_scene_id,
            "heroOriginalClipReady": hero_original_clip_ready,
            "heroOriginalityEvidenceReady": hero_originality_evidence_ready,
            "heroAiOrLocalReady": hero_ai_or_local_ready,
            "originalClipSceneIds": original_clip_scene_ids,
            "weakUploadedOriginalityScenes": weak_uploaded_originality_scenes,
            "proceduralPlaceholderScenes": procedural_placeholder_scenes,
            "grokHandoffSceneIds": grok_handoff_scene_ids,
            "localModelVideoSceneIds": local_model_video_scene_ids,
            "uploadedVideoScenes": uploaded_video_scenes,
            "grokHandoffScenes": grok_handoff_scenes,
            "localModelVideoScenes": local_model_video_scenes,
            "stockVideoScenes": stock_video_scenes,
            "stockOnly": stock_only,
            "curatedStockReady": curated_stock_ready,
            "missingRationaleScenes": missing_rationale,
            "missingContinuityScenes": missing_continuity,
            "missingOriginalityEvidenceScenes": missing_originality_evidence,
            "missingQualityReviewScenes": missing_quality_review,
            "missingVisualVerdictScenes": missing_visual_verdict,
            "failedVisualVerdictScenes": failed_visual_verdict,
            "originalityEvidenceScenes": originality_evidence_scenes,
            "qualityReviewScenes": quality_review_scenes,
            "visualVerdictScenes": visual_verdict_scenes,
            "firstSceneHookReady": first_hook_ready,
            "narrationReady": narration_ready,
            "captionLayoutReady": caption_layout_ready,
            "visualVerdictReady": visual_verdict_ready,
            "assetDiversityReady": asset_diversity_ready,
            "freeAssetProvenanceReady": free_asset_provenance_ready,
            "bgmSoundReady": not placeholder_bgm_assets,
            "placeholderBgmAssets": placeholder_bgm_assets,
            "bgmRotationReady": bgm_rotation_ready,
            "templateSourceReady": template_source_ready,
            "audioMixReviewReady": audio_mix_review_ready,
            "platformComparisonReady": platform_comparison_ready,
            "placeholderCount": int(local_media_summary.get("placeholder", 0) or 0),
        },
    }


def _build_upload_review(
    checks: dict,
    publish_readiness: dict,
    channel_readiness: dict,
    production_review: dict,
) -> dict:
    """Create a final human upload checklist for platform-facing review."""
    production_summary = production_review.get("summary") or {}
    channel_summary = channel_readiness.get("summary") or {}
    publish_status = str(publish_readiness.get("status") or "needs-rework")
    channel_status = str(channel_readiness.get("status") or "needs-review")
    criteria: list[dict] = []
    required_fixes: list[str] = []
    manual_reviews: list[str] = []
    strengths: list[str] = []

    def add_criterion(
        key: str,
        label: str,
        status: str,
        detail: str,
        fix: str,
        required: bool,
    ) -> None:
        criteria.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "detail": detail,
                "required": required,
            }
        )
        if status == "fail" and required:
            required_fixes.append(fix)
        elif status in {"fail", "warn"} and not required:
            manual_reviews.append(fix)
        elif status == "pass":
            strengths.append(label)

    def check_status(key: str) -> str:
        return str((checks.get(key) or {}).get("status") or "warn")

    def check_detail(key: str) -> str:
        return str((checks.get(key) or {}).get("detail") or "")

    first_scene_id = str(channel_summary.get("firstSceneId") or "scene-01")
    hero_original_ready = channel_summary.get("heroOriginalClipReady") is True
    hero_evidence_ready = channel_summary.get("heroOriginalityEvidenceReady") is True
    hero_ai_or_local_ready = channel_summary.get("heroAiOrLocalReady") is True
    total_scenes = int(production_summary.get("totalScenes", 0) or 0)
    content_template = str(
        production_summary.get("contentTemplate")
        or (production_review.get("templateSourceReview") or {}).get("template")
        or ""
    ).strip()
    uploaded_video_scenes = int(production_summary.get("uploadedVideoScenes", 0) or 0)
    grok_handoff_scenes = int(production_summary.get("grokHandoffScenes", 0) or 0)
    local_model_video_scenes = int(production_summary.get("localModelVideoScenes", 0) or 0)
    stock_video_scenes = int(production_summary.get("stockVideoScenes", 0) or 0)
    original_clip_scene_ids = [str(item) for item in production_summary.get("originalClipSceneIds") or []]
    original_clip_scenes = len(set(original_clip_scene_ids))
    min_original_scene_count = 1 if total_scenes <= 1 else max(2, (total_scenes + 1) // 2)
    source_mix_required = total_scenes > 1 and content_template in UPLOAD_SOURCE_MIX_REQUIRED_TEMPLATES
    original_source_mix_ready = original_clip_scenes >= min_original_scene_count
    quality_review_scenes = production_summary.get("qualityReviewScenes") or []
    visual_verdict_scenes = production_summary.get("visualVerdictScenes") or []
    missing_visual_verdict = production_summary.get("missingVisualVerdictScenes") or []
    failed_visual_verdict = production_summary.get("failedVisualVerdictScenes") or []
    first_hook_ready = production_summary.get("firstSceneHookReady") is True
    thumbnail_review_scenes = production_summary.get("thumbnailReviewScenes") or []
    audio_mix_review_scenes = production_summary.get("audioMixReviewScenes") or []
    platform_comparison_scenes = production_summary.get("platformComparisonScenes") or []
    thumbnail_review_ready = first_scene_id in thumbnail_review_scenes
    audio_mix_review_ready = bool(audio_mix_review_scenes)
    platform_comparison_ready = bool(platform_comparison_scenes)
    narration_ready = _audio_design_ready(production_summary)
    caption_layout_ready = (
        not production_summary.get("missingCaptionLayoutReviewScenes")
        and not production_summary.get("captionSparsePlan")
        and not production_summary.get("longTopHookScenes")
    )
    visual_verdict_ready = total_scenes > 0 and len(visual_verdict_scenes) == total_scenes and not failed_visual_verdict
    asset_diversity_ready = not production_summary.get("repeatedVisualAssetScenes")
    free_asset_provenance_ready = (
        not production_summary.get("missingFreeAssetProvenanceScenes")
        and not production_summary.get("missingFreeAudioProvenanceAssets")
        and not production_summary.get("freeAudioCreditMissingAssets")
    )
    placeholder_bgm_assets = production_summary.get("placeholderBgmAssets") or []
    bgm_rotation_ready = not production_summary.get("weakBgmSelectionAssets") and not placeholder_bgm_assets
    template_source_review = production_review.get("templateSourceReview") or {}
    template_source_ready = template_source_review.get("status") == "pass"

    add_criterion(
        "publishPacketReady",
        "Publish packet gate passed",
        "pass" if publish_status == "ready" else "fail",
        f"publishReadiness={publish_status}",
        "Resolve publishReadiness before creating an upload candidate.",
        True,
    )
    add_criterion(
        "channelPacketReady",
        "Channel originality gate passed",
        "pass" if channel_status == "channel-ready" else "fail",
        f"channelReadiness={channel_status}",
        "Create a channel-ready packet with first-scene original MP4 evidence before upload.",
        True,
    )
    add_criterion(
        "firstFrameHook",
        "First-frame / first 2s hook",
        "pass" if first_hook_ready and hero_original_ready else "fail",
        f"firstSceneId={first_scene_id}, firstSceneHookReady={first_hook_ready}, heroOriginalClipReady={hero_original_ready}",
        "Make the first scene the strongest original moving hook before choosing a thumbnail or first frame.",
        True,
    )
    add_criterion(
        "cutDensityPacing",
        "Cut density is short-form ready",
        "pass" if check_status("cutDensityPacing") == "pass" else "fail",
        check_detail("cutDensityPacing"),
        "Increase clip count or reduce repeated/static sections so the edit does not feel like a low-density slideshow.",
        True,
    )
    add_criterion(
        "aiSlopVisualFit",
        "AI slop / visual artifact fit",
        check_status("aiSlopVisualFit"),
        check_detail("aiSlopVisualFit"),
        "Block upload when visual verdicts flag AI slop, watermark/compression artifacts, subject mismatch, or weak source fit.",
        True,
    )
    add_criterion(
        "stockAiClipFit",
        "Stock/AI clip fit",
        check_status("stockAiClipFit"),
        check_detail("stockAiClipFit"),
        "Replace mismatched stock/AI clips or record stronger source-fit notes before upload.",
        True,
    )
    add_criterion(
        "heroOriginalityEvidence",
        "Hero originality evidence recorded",
        "pass" if hero_evidence_ready else "fail",
        f"heroOriginalityEvidenceReady={hero_evidence_ready}",
        "Record direct/Grok/local generation evidence for the first-scene hero clip.",
        True,
    )
    add_criterion(
        "captionSafeZone",
        "Caption safe-zone preset",
        check_status("captionSafePresets"),
        check_detail("captionSafePresets"),
        "Fix caption presets before upload so Shorts UI danger zones stay clear.",
        True,
    )
    add_criterion(
        "outputAudioSpec",
        "1080x1920 / 30fps / audio stream",
        check_status("outputSpec"),
        check_detail("outputSpec"),
        "Re-render with 1080x1920, 30fps, audio stream, and positive duration.",
        True,
    )
    add_criterion(
        "ttsNarrationEvidence",
        "Audio design is intentional",
        "pass" if narration_ready else "fail",
        (
            f"subtitleOnlyNarrationScenes={production_summary.get('subtitleOnlyNarrationScenes') or []}, "
            f"missingNarrationScenes={production_summary.get('missingNarrationScenes') or []}, "
            f"thinNarrationScenes={production_summary.get('thinNarrationScenes') or []}, "
            f"noVoiceAudioDesignScenes={production_summary.get('noVoiceAudioDesignScenes') or []}, "
            f"voiceoverRequiredNoVoiceScenes={production_summary.get('voiceoverRequiredNoVoiceScenes') or []}, "
            f"visualLedNoVoiceApprovedScenes={production_summary.get('visualLedNoVoiceApprovedScenes') or []}, "
            f"missingNoVoiceAudioScenes={production_summary.get('missingNoVoiceAudioScenes') or []}, "
            f"missingNoVoiceAudioReviewScenes={production_summary.get('missingNoVoiceAudioReviewScenes') or []}, "
            f"productionMetaNarrationScenes={production_summary.get('productionMetaNarrationScenes') or []}, "
            f"requiredChars={production_summary.get('narrationMinCharsByScene') or {}}"
        ),
        "Either use natural viewer-facing narration, or explicitly ship a no-voice edit with BGM/native audio and audio mix review proof.",
        True,
    )
    add_criterion(
        "bgmSoundQuality",
        "BGM is not beep/test-tone/procedural",
        "pass" if not placeholder_bgm_assets else "fail",
        (
            f"placeholderBgmAssets={placeholder_bgm_assets}, "
            f"reasons={production_summary.get('placeholderBgmAssetReasons') or {}}"
        ),
        "Replace procedural sine, beep, click, lavfi, or test-tone BGM with a real free music bed before upload.",
        True,
    )
    add_criterion(
        "sceneQualityReview",
        "Per-scene visual quality review",
        "pass" if total_scenes > 0 and len(quality_review_scenes) == total_scenes else "fail",
        f"qualityReviewScenes={quality_review_scenes}, totalScenes={total_scenes}",
        "Complete per-scene quality review for subject visibility, caption occlusion, watermark/compression, and cut continuity.",
        True,
    )
    add_criterion(
        "manualVisualVerdict",
        "Contact-sheet visual verdict",
        "pass" if visual_verdict_ready else "fail",
        (
            f"visualVerdictScenes={visual_verdict_scenes}, "
            f"missingVisualVerdictScenes={missing_visual_verdict}, "
            f"failedVisualVerdictScenes={failed_visual_verdict}"
        ),
        "Before upload, watch the final render/contact sheet and mark every scene with visualQualityVerdict=pass; review text alone is not upload evidence.",
        True,
    )
    add_criterion(
        "captionLayoutReview",
        "Caption placement reviewed",
        "pass" if caption_layout_ready else "fail",
        (
            f"missingCaptionLayoutReviewScenes={production_summary.get('missingCaptionLayoutReviewScenes') or []}, "
            f"captionSparsePlan={production_summary.get('captionSparsePlan')}, "
            f"longTopHookScenes={production_summary.get('longTopHookScenes') or []}"
        ),
        "Move, shorten, or disable captions intentionally; one slow hook plus no later captions is not an upload-ready layout.",
        True,
    )
    add_criterion(
        "assetReuseDiversity",
        "No repeated visual asset reuse",
        "pass" if asset_diversity_ready else "fail",
        f"repeatedVisualAssetScenes={production_summary.get('repeatedVisualAssetScenes') or []}",
        "Replace repeated assets before upload; repeated B-roll should be a deliberate callback, not a default fallback.",
        True,
    )
    add_criterion(
        "freeAssetProvenance",
        "Free asset provenance retained",
        "pass" if free_asset_provenance_ready else "fail",
        (
            f"missingFreeAssetProvenanceScenes={production_summary.get('missingFreeAssetProvenanceScenes') or []}, "
            f"missingFreeAudioProvenanceAssets={production_summary.get('missingFreeAudioProvenanceAssets') or []}, "
            f"freeAudioCreditMissingAssets={production_summary.get('freeAudioCreditMissingAssets') or []}"
        ),
        "Keep source URL/ID/label, license notes, and YouTube description credits for Pexels/Pixabay/Mixkit/Freesound/YouTube Audio Library assets.",
        True,
    )
    add_criterion(
        "bgmAssetRotation",
        "BGM is not default-reused",
        "pass" if bgm_rotation_ready else "warn",
        (
            f"weakBgmSelectionAssets={production_summary.get('weakBgmSelectionAssets') or []}, "
            f"placeholderBgmAssets={placeholder_bgm_assets}"
        ),
        "Before upload, add more free BGM candidates or pin a deliberate free BGM choice with provenance.",
        False,
    )
    add_criterion(
        "templateSourcePlan",
        "Template/source plan matches format",
        "pass" if template_source_ready else "warn",
        (
            f"template={template_source_review.get('template')}, "
            f"status={template_source_review.get('status')}, "
            f"counts={template_source_review.get('counts')}"
        ),
        "Fix the template source mix before upload: avoid repeated assets, document free sources, and use the right direct/Grok/local/stock mix.",
        False,
    )
    add_criterion(
        "grokOrLocalHero",
        "Direct/Grok/local original hero option",
        "pass" if hero_original_ready or hero_ai_or_local_ready else "warn",
        f"heroOriginalClipReady={hero_original_ready}, heroAiOrLocalReady={hero_ai_or_local_ready}",
        "For AI-assisted channel targets, prefer Grok app/web or local Wan/LTX/Hunyuan for the first hook, but direct original uploads are publishable.",
        False,
    )
    if source_mix_required:
        add_criterion(
            "originalSourceMix",
            "Live-channel original source mix",
            "pass" if original_source_mix_ready else "fail",
            (
                f"template={content_template}, originalClipScenes={original_clip_scenes}, "
                f"minOriginalScenes={min_original_scene_count}, stockVideoScenes={stock_video_scenes}, "
                f"uploadedVideoScenes={uploaded_video_scenes}, grokHandoffScenes={grok_handoff_scenes}, "
                f"localModelVideoScenes={local_model_video_scenes}, totalScenes={total_scenes}, "
                f"originalClipSceneIds={original_clip_scene_ids}"
            ),
            "For this live-channel template, rerender with at least half of scenes backed by reviewed Grok/local/direct/owned MP4 clips; stock B-roll can support but cannot carry the edit.",
            True,
        )
    add_criterion(
        "thumbnailFirstFrame",
        "Thumbnail / first-frame manual review",
        check_status("thumbnailFirstFrameStrength"),
        check_detail("thumbnailFirstFrameStrength"),
        "Pick or generate a thumbnail/first-frame candidate before publishing.",
        False,
    )
    add_criterion(
        "audioMixReview",
        "BGM/native/TTS volume manual review",
        "pass" if audio_mix_review_ready else "warn",
        f"audioMixReviewScenes={audio_mix_review_scenes}",
        "Confirm BGM/native/TTS balance on headphones and speakers before publishing.",
        False,
    )
    add_criterion(
        "platformComparison",
        "YouTube Shorts/long-form comparison",
        "pass" if platform_comparison_ready else "warn",
        f"platformComparisonScenes={platform_comparison_scenes}",
        "Record a final comparison pass against current channel references before upload.",
        False,
    )

    passed = sum(1 for item in criteria if item["status"] == "pass")
    total = len(criteria)
    if required_fixes:
        status = "blocked"
    elif manual_reviews:
        status = "needs-manual-review"
    else:
        status = "ready"

    return {
        "status": status,
        "score": {"passed": passed, "total": total},
        "requiredFixes": required_fixes,
        "manualReviewItems": manual_reviews,
        "strengths": strengths[:8],
        "criteria": criteria,
        "summary": {
            "publishStatus": publish_status,
            "channelStatus": channel_status,
            "contentTemplate": content_template,
            "firstSceneId": first_scene_id,
            "heroOriginalClipReady": hero_original_ready,
            "heroOriginalityEvidenceReady": hero_evidence_ready,
            "heroAiOrLocalReady": hero_ai_or_local_ready,
            "originalSourceMixRequired": source_mix_required,
            "originalSourceMixReady": original_source_mix_ready,
            "originalClipScenes": original_clip_scenes,
            "minOriginalScenes": min_original_scene_count,
            "stockVideoScenes": stock_video_scenes,
            "uploadedVideoScenes": uploaded_video_scenes,
            "grokHandoffScenes": grok_handoff_scenes,
            "localModelVideoScenes": local_model_video_scenes,
            "originalClipSceneIds": original_clip_scene_ids,
            "firstSceneHookReady": first_hook_ready,
            "qualityReviewScenes": quality_review_scenes,
            "visualVerdictScenes": visual_verdict_scenes,
            "missingVisualVerdictScenes": missing_visual_verdict,
            "failedVisualVerdictScenes": failed_visual_verdict,
            "thumbnailReviewScenes": thumbnail_review_scenes,
            "audioMixReviewScenes": audio_mix_review_scenes,
            "platformComparisonScenes": platform_comparison_scenes,
            "thumbnailReviewReady": thumbnail_review_ready,
            "audioMixReviewReady": audio_mix_review_ready,
            "platformComparisonReady": platform_comparison_ready,
            "narrationReady": narration_ready,
            "captionLayoutReady": caption_layout_ready,
            "visualVerdictReady": visual_verdict_ready,
            "assetDiversityReady": asset_diversity_ready,
            "freeAssetProvenanceReady": free_asset_provenance_ready,
            "bgmSoundReady": not placeholder_bgm_assets,
            "placeholderBgmAssets": placeholder_bgm_assets,
            "bgmRotationReady": bgm_rotation_ready,
            "templateSourceReady": template_source_ready,
            "totalScenes": total_scenes,
        },
    }


def _build_top_tier_readiness(
    checks: dict,
    publish_readiness: dict,
    channel_readiness: dict,
    upload_review: dict,
    production_review: dict,
) -> dict:
    """Grade the stricter Korean AI-assisted channel benchmark separately from upload readiness."""
    production_summary = production_review.get("summary") or {}
    channel_summary = channel_readiness.get("summary") or {}
    upload_summary = upload_review.get("summary") if isinstance(upload_review.get("summary"), dict) else {}
    template_source_review = production_review.get("templateSourceReview") or {}
    publish_status = str(publish_readiness.get("status") or "needs-rework")
    channel_status = str(channel_readiness.get("status") or "needs-review")
    upload_status = str(upload_review.get("status") or "needs-review")
    first_scene_id = str(channel_summary.get("firstSceneId") or "scene-01")
    total_scenes = int(production_summary.get("totalScenes", 0) or 0)
    uploaded_video_scenes = int(production_summary.get("uploadedVideoScenes", 0) or 0)
    grok_handoff_scenes = int(production_summary.get("grokHandoffScenes", 0) or 0)
    local_model_video_scenes = int(production_summary.get("localModelVideoScenes", 0) or 0)
    stock_video_scenes = int(production_summary.get("stockVideoScenes", 0) or 0)
    original_clip_scene_ids = [str(item) for item in production_summary.get("originalClipSceneIds") or []]
    original_clip_scenes = len(set(original_clip_scene_ids))
    min_original_scene_count = 1 if total_scenes <= 1 else max(2, (total_scenes + 1) // 2)
    original_source_mix_ready = original_clip_scenes >= min_original_scene_count
    hero_ai_or_local_ready = channel_summary.get("heroAiOrLocalReady") is True
    hero_original_ready = channel_summary.get("heroOriginalClipReady") is True
    hero_evidence_ready = channel_summary.get("heroOriginalityEvidenceReady") is True
    narration_ready = channel_summary.get("narrationReady") is True or upload_summary.get("narrationReady") is True
    caption_layout_ready = channel_summary.get("captionLayoutReady") is True or upload_summary.get("captionLayoutReady") is True
    visual_verdict_ready = channel_summary.get("visualVerdictReady") is True or upload_summary.get("visualVerdictReady") is True
    asset_diversity_ready = channel_summary.get("assetDiversityReady") is True or upload_summary.get("assetDiversityReady") is True
    free_asset_provenance_ready = (
        channel_summary.get("freeAssetProvenanceReady") is True
        or upload_summary.get("freeAssetProvenanceReady") is True
    )
    stock_candidate_curation_ready = not (production_summary.get("missingStockCandidateCurationScenes") or [])
    placeholder_bgm_assets = production_summary.get("placeholderBgmAssets") or []
    bgm_sound_ready = not placeholder_bgm_assets and (checks.get("bgmSoundQuality") or {}).get("status") == "pass"
    bgm_rotation_ready = (
        (channel_summary.get("bgmRotationReady") is True or upload_summary.get("bgmRotationReady") is True)
        and bgm_sound_ready
    )
    audio_mix_review_ready = channel_summary.get("audioMixReviewReady") is True or upload_summary.get("audioMixReviewReady") is True
    platform_comparison_ready = (
        channel_summary.get("platformComparisonReady") is True
        or upload_summary.get("platformComparisonReady") is True
    )
    template_source_ready = (
        channel_summary.get("templateSourceReady") is True
        or upload_summary.get("templateSourceReady") is True
        or template_source_review.get("status") == "pass"
    )
    first_hook_ready = production_summary.get("firstSceneHookReady") is True

    criteria: list[dict] = []
    required_fixes: list[str] = []
    strengths: list[str] = []

    def add_criterion(
        key: str,
        label: str,
        ok: bool,
        detail: str,
        fix: str,
    ) -> None:
        status = "pass" if ok else "fail"
        criteria.append({
            "key": key,
            "label": label,
            "status": status,
            "detail": detail,
            "required": True,
        })
        if ok:
            strengths.append(label)
        else:
            required_fixes.append(fix)

    add_criterion(
        "publishGate",
        "Publish gate passed",
        publish_status == "ready",
        f"publishReadiness={publish_status}",
        "Resolve publish-readiness before judging top-tier quality.",
    )
    add_criterion(
        "channelGate",
        "Channel gate passed",
        channel_status == "channel-ready",
        f"channelReadiness={channel_status}",
        "Create a channel-ready packet with reviewed original/direct/Grok/local first-scene evidence.",
    )
    add_criterion(
        "uploadReviewGate",
        "Upload review passed",
        upload_status == "ready",
        f"uploadReview={upload_status}",
        "Complete thumbnail, audio mix, caption layout, and platform upload review before top-tier claim.",
    )
    add_criterion(
        "firstHookOriginal",
        "First hook has original MP4",
        hero_original_ready and hero_evidence_ready and first_hook_ready,
        (
            f"firstSceneId={first_scene_id}, heroOriginalClipReady={hero_original_ready}, "
            f"heroOriginalityEvidenceReady={hero_evidence_ready}, firstSceneHookReady={first_hook_ready}"
        ),
        "Replace or review the first hook so it has original/direct/Grok/local MP4 evidence and an immediate visual payoff.",
    )
    add_criterion(
        "grokOrLocalHero",
        "First hook has Grok/local AI MP4",
        hero_ai_or_local_ready,
        (
            f"firstSceneId={first_scene_id}, grokHandoffScenes={grok_handoff_scenes}, "
            f"localModelVideoScenes={local_model_video_scenes}"
        ),
        "For top-tier AI-assisted output, replace the first hook with a reviewed Grok app/web or local Wan/LTX/Hunyuan MP4, not only direct upload or stock.",
    )
    add_criterion(
        "originalSourceMix",
        "Original/Grok/local/direct scenes outweigh stock",
        original_source_mix_ready,
        (
            f"originalClipScenes={original_clip_scenes}, minOriginalScenes={min_original_scene_count}, "
            f"stockVideoScenes={stock_video_scenes}, uploadedVideoScenes={uploaded_video_scenes}, "
            f"grokHandoffScenes={grok_handoff_scenes}, localModelVideoScenes={local_model_video_scenes}, "
            f"totalScenes={total_scenes}, originalClipSceneIds={original_clip_scene_ids}"
        ),
        "For top-tier output, at least half of scenes should be reviewed Grok/local/direct/owned MP4 clips; keep Pexels as support B-roll, not the main visual source.",
    )
    add_criterion(
        "audioDesign",
        "Intentional audio design",
        narration_ready and (checks.get("ttsNarrationEvidence") or {}).get("status") == "pass",
        (checks.get("ttsNarrationEvidence") or {}).get("detail") or f"narrationReady={narration_ready}",
        "Use viewer-facing voiceover for information/ranking/list output unless a visual-led no-voice edit is explicitly human-approved.",
    )
    add_criterion(
        "captionLayout",
        "Caption layout is subject-clear",
        caption_layout_ready and (checks.get("captionLayoutReview") or {}).get("status") == "pass",
        (checks.get("captionLayoutReview") or {}).get("detail") or f"captionLayoutReady={caption_layout_ready}",
        "Record per-scene caption placement review and keep captions out of subject and Shorts UI danger zones.",
    )
    add_criterion(
        "captionDensityAndSafeZone",
        "Caption density and safe zone fit Shorts",
        (checks.get("captionDensityAndSafeZone") or {}).get("status") == "pass",
        (checks.get("captionDensityAndSafeZone") or {}).get("detail") or "caption density check missing",
        "Shorten burned-in captions and keep lower captions in the lower-mid Shorts safe zone, not the bottom UI area.",
    )
    add_criterion(
        "manualVisualVerdict",
        "Contact-sheet visual verdict passed",
        visual_verdict_ready,
        (
            f"visualVerdictReady={visual_verdict_ready}, "
            f"visualVerdictScenes={production_summary.get('visualVerdictScenes') or []}, "
            f"missingVisualVerdictScenes={production_summary.get('missingVisualVerdictScenes') or []}, "
            f"failedVisualVerdictScenes={production_summary.get('failedVisualVerdictScenes') or []}"
        ),
        "Do a real visual review of the rendered frames/contact sheet and mark every scene visualQualityVerdict=pass before claiming top-tier quality.",
    )
    add_criterion(
        "cutDensityPacing",
        "Cut density fits short-form pacing",
        (checks.get("cutDensityPacing") or {}).get("status") == "pass",
        (checks.get("cutDensityPacing") or {}).get("detail") or "cut density check missing",
        "Increase the number of distinct moving clips or shorten static/reused sections before claiming top-tier short-form quality.",
    )
    add_criterion(
        "aiSlopVisualFit",
        "AI slop / visual artifact fit passed",
        (checks.get("aiSlopVisualFit") or {}).get("status") == "pass",
        (checks.get("aiSlopVisualFit") or {}).get("detail") or "AI slop and source-fit check missing",
        "Separate and resolve AI slop, watermark/compression artifacts, subject mismatch, or weak visual verdicts before top-tier review.",
    )
    add_criterion(
        "stockAiClipFit",
        "Stock/AI clip fit passed",
        (checks.get("stockAiClipFit") or {}).get("status") == "pass",
        (checks.get("stockAiClipFit") or {}).get("detail") or "Stock/AI source-fit check missing",
        "Resolve selected-stock/source-fit mismatch with an explicit pass verdict or replace the scene with accepted direct/Grok/local/owned footage.",
    )
    add_criterion(
        "thumbnailFirstFrameStrength",
        "Thumbnail / first frame is strong",
        (checks.get("thumbnailFirstFrameStrength") or {}).get("status") == "pass",
        (checks.get("thumbnailFirstFrameStrength") or {}).get("detail") or "thumbnail and first-frame check missing",
        "Select or generate a first-frame/thumbnail candidate strong enough for the channel feed before top-tier review.",
    )
    add_criterion(
        "assetDiversity",
        "Distinct visual assets",
        asset_diversity_ready and (checks.get("assetReuseDiversity") or {}).get("status") == "pass",
        (checks.get("assetReuseDiversity") or {}).get("detail") or f"assetDiversityReady={asset_diversity_ready}",
        "Replace repeated free clips/images or document a deliberate visual callback before claiming top-tier quality.",
    )
    add_criterion(
        "freeAssetProvenance",
        "Free asset provenance retained",
        free_asset_provenance_ready and (checks.get("freeAssetProvenance") or {}).get("status") == "pass",
        (checks.get("freeAssetProvenance") or {}).get("detail") or f"freeAssetProvenanceReady={free_asset_provenance_ready}",
        "Keep source URL/ID/license notes for free visual/audio assets so repeated or risky assets are traceable.",
    )
    add_criterion(
        "stockCandidateCuration",
        "Stock B-roll has candidate-pool proof",
        stock_candidate_curation_ready and (checks.get("stockCandidateCuration") or {}).get("status") == "pass",
        (checks.get("stockCandidateCuration") or {}).get("detail") or "stock candidate curation check missing",
        "For Pexels/Pixabay/Mixkit B-roll, select from 2+ candidates and retain creator/source URL or ID plus the manual selection summary.",
    )
    add_criterion(
        "bgmSoundQuality",
        "BGM is not beep/test-tone/procedural",
        bgm_sound_ready,
        (checks.get("bgmSoundQuality") or {}).get("detail") or f"placeholderBgmAssets={placeholder_bgm_assets}",
        "Replace procedural sine, beep, click, lavfi, or test-tone BGM with a real free music bed before top-tier review.",
    )
    add_criterion(
        "bgmRotation",
        "BGM rotation evidence",
        bgm_rotation_ready and (checks.get("bgmAssetRotation") or {}).get("status") == "pass",
        (checks.get("bgmAssetRotation") or {}).get("detail") or f"bgmRotationReady={bgm_rotation_ready}",
        "Use a reusable free/local BGM candidate pool and retain project/template selection evidence.",
    )
    add_criterion(
        "audioMixReview",
        "Audio mix reviewed",
        audio_mix_review_ready,
        f"audioMixReviewScenes={production_summary.get('audioMixReviewScenes') or []}",
        "Watch the full render and record that BGM/native audio supports the edit; if narration exists, confirm speech stays intelligible.",
    )
    add_criterion(
        "platformComparison",
        "Korean YouTube benchmark compared",
        platform_comparison_ready,
        f"platformComparisonScenes={production_summary.get('platformComparisonScenes') or []}",
        "Record a comparison against current Korean Shorts/long-form references for hook, pacing, layout, asset fit, and artifact level.",
    )
    add_criterion(
        "templateSourcePlan",
        "Template/source plan fits format",
        template_source_ready and (checks.get("templateSourcePlan") or {}).get("status") == "pass",
        (checks.get("templateSourcePlan") or {}).get("detail") or f"templateSourceReady={template_source_ready}",
        "Use the chosen template's intended source mix instead of one fixed layout or repeated stock/BGM pattern.",
    )

    passed = sum(1 for item in criteria if item["status"] == "pass")
    top_tier_ready = not required_fixes
    if top_tier_ready:
        status = "top-tier-ready"
    elif publish_status != "ready":
        status = "needs-publish-rework"
    elif channel_status != "channel-ready":
        status = "needs-channel-evidence"
    elif not visual_verdict_ready:
        status = "needs-visual-verdict"
    elif not hero_ai_or_local_ready:
        status = "needs-grok-local-hero"
    elif not original_source_mix_ready:
        status = "needs-original-source-mix"
    elif upload_status != "ready":
        status = "needs-upload-review"
    else:
        status = "needs-top-tier-review"

    return {
        "status": status,
        "score": {"passed": passed, "total": len(criteria)},
        "requiredFixes": required_fixes,
        "recommendedFixes": [],
        "strengths": strengths[:8],
        "criteria": criteria,
        "summary": {
            "publishStatus": publish_status,
            "channelStatus": channel_status,
            "uploadStatus": upload_status,
            "firstSceneId": first_scene_id,
            "grokOrLocalHeroReady": hero_ai_or_local_ready,
            "originalHeroReady": hero_original_ready,
            "heroOriginalityEvidenceReady": hero_evidence_ready,
            "originalSourceMixReady": original_source_mix_ready,
            "originalClipScenes": original_clip_scenes,
            "minOriginalScenes": min_original_scene_count,
            "stockVideoScenes": stock_video_scenes,
            "uploadedVideoScenes": uploaded_video_scenes,
            "grokHandoffScenes": grok_handoff_scenes,
            "localModelVideoScenes": local_model_video_scenes,
            "originalClipSceneIds": original_clip_scene_ids,
            "firstSceneHookReady": first_hook_ready,
            "narrationReady": narration_ready,
            "captionLayoutReady": caption_layout_ready,
            "visualVerdictReady": visual_verdict_ready,
            "cutDensityReady": (checks.get("cutDensityPacing") or {}).get("status") == "pass",
            "aiSlopVisualFitReady": (checks.get("aiSlopVisualFit") or {}).get("status") == "pass",
            "thumbnailFirstFrameReady": (checks.get("thumbnailFirstFrameStrength") or {}).get("status") == "pass",
            "assetDiversityReady": asset_diversity_ready,
            "freeAssetProvenanceReady": free_asset_provenance_ready,
            "stockCandidateCurationReady": stock_candidate_curation_ready,
            "bgmSoundReady": bgm_sound_ready,
            "bgmRotationReady": bgm_rotation_ready,
            "audioMixReviewReady": audio_mix_review_ready,
            "platformComparisonReady": platform_comparison_ready,
            "templateSourceReady": template_source_ready,
            "topTierEvidenceReady": top_tier_ready,
            "benchmarkGap": "none" if top_tier_ready else "; ".join(required_fixes[:4]),
        },
    }


def _audio_asset_has_narration_voice(asset: dict) -> bool:
    provider = str(asset.get("provider") or "").strip()
    kind = str(asset.get("kind") or "").strip()
    if provider in FREE_NARRATION_PROVIDERS:
        return kind != "fallback-tone"
    if provider == "upload" and kind in {"uploaded-audio", "voiceover", "native"}:
        return bool(str(asset.get("sourcePath") or asset.get("outputPath") or "").strip())
    return False


def _stream_duration_seconds(stream: dict) -> float | None:
    try:
        value = float(stream.get("duration"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _stream_duration_matches(stream_duration: float | None, format_duration: float | None) -> bool:
    if stream_duration is None or format_duration is None:
        return True
    return abs(stream_duration - format_duration) <= 0.75


def write_render_quality_report(
    render_dir: Path,
    manifest: dict,
    manifest_path: Path,
    output_path: Path,
    project_root: Path,
    local_media_summary: dict,
    local_media: list[dict],
    subtitle_file_path: Path,
) -> str:
    """Write a machine-readable render QA report next to the MP4."""
    ffprobe_payload, ffprobe_info = _run_ffprobe_json(project_root, output_path)
    streams = (ffprobe_payload or {}).get("streams", []) if isinstance(ffprobe_payload, dict) else []
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    duration = None
    try:
        duration = float(((ffprobe_payload or {}).get("format") or {}).get("duration"))
    except (TypeError, ValueError, AttributeError):
        duration = None

    width = video_stream.get("width")
    height = video_stream.get("height")
    fps = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")
    video_duration = _stream_duration_seconds(video_stream)
    audio_duration = _stream_duration_seconds(audio_stream)
    stream_duration_ok = (
        _stream_duration_matches(video_duration, duration)
        and _stream_duration_matches(audio_duration, duration)
    )
    output_spec_ok = (
        width == 1080
        and height == 1920
        and _rate_is_30fps(fps)
        and bool(audio_stream)
        and bool(duration and duration > 0)
        and stream_duration_ok
    )

    providers = sorted({
        str(asset.get("provider"))
        for asset in manifest.get("assets", [])
        if asset.get("provider")
    })
    try:
        from worker.media.provider_policy import is_paid_provider
        paid_providers = [provider for provider in providers if is_paid_provider(provider)]
    except Exception:
        paid_providers = []

    caption_presets = [
        {
            "sceneId": scene.get("sceneId"),
            "captionPreset": scene.get("captionPreset", "lower-info"),
        }
        for scene in manifest.get("scenes", [])
    ]
    unsafe_caption_scenes = [
        item["sceneId"]
        for item in caption_presets
        if item["captionPreset"] not in {"none", "center-short", "top-hook", "lower-info"}
    ]
    moving_scene_count = sum(
        1
        for scene in manifest.get("scenes", [])
        if scene.get("visualKind") == "video"
    )
    source_motion_evidence = _build_source_motion_evidence(project_root, manifest)
    source_motion_status = str(source_motion_evidence.get("status") or "unavailable")
    moving_clip_status = "pass" if moving_scene_count > 0 and source_motion_status != "fail" else "fail"
    production_review = _build_production_review(manifest, local_media)
    production_review["templateSourceReview"] = _build_template_source_review(production_review)
    production_summary = production_review["summary"]
    audio_assets = [
        asset
        for asset in manifest.get("assets", [])
        if asset.get("role") == "audio"
    ]
    audio_providers = sorted({
        str(asset.get("provider") or "")
        for asset in audio_assets
        if asset.get("provider")
    })
    narration_scene_ids = {
        str(scene_id)
        for scene_id in production_summary["narrationScenes"]
    }
    inferred_single_scene_id = next(iter(narration_scene_ids)) if len(narration_scene_ids) == 1 else ""

    def audio_scene_id(asset: dict) -> str:
        return str(asset.get("sceneId") or inferred_single_scene_id or "")

    narration_audio_scene_ids = {
        audio_scene_id(asset)
        for asset in audio_assets
        if audio_scene_id(asset) in narration_scene_ids and _audio_asset_has_narration_voice(asset)
    }
    fallback_tone_scene_ids = sorted({
        audio_scene_id(asset)
        for asset in audio_assets
        if str(asset.get("provider") or "") == "fallback-sine" or str(asset.get("kind") or "") == "fallback-tone"
    })
    missing_narration_audio_scenes = sorted(narration_scene_ids - narration_audio_scene_ids)
    narration_status = "pass"
    if production_summary["missingNarrationScenes"] or production_summary["thinNarrationScenes"]:
        narration_status = "fail"
    elif production_summary["productionMetaNarrationScenes"] or production_summary["productionMetaSubtitleScenes"]:
        narration_status = "fail"
    elif production_summary.get("voiceoverRequiredNoVoiceScenes"):
        narration_status = "fail"
    elif production_summary["missingNoVoiceAudioScenes"] or production_summary["missingNoVoiceAudioReviewScenes"]:
        narration_status = "fail"
    elif fallback_tone_scene_ids or missing_narration_audio_scenes:
        narration_status = "fail"
    caption_layout_status = (
        "pass"
        if not production_summary["missingCaptionLayoutReviewScenes"]
        and not production_summary["captionSparsePlan"]
        and not production_summary["longTopHookScenes"]
        else "fail"
    )
    caption_density_status = "pass" if not production_summary["captionDensityIssueScenes"] else "fail"
    asset_diversity_status = "pass" if not production_summary["repeatedVisualAssetScenes"] else "fail"
    free_asset_provenance_status = (
        "pass"
        if not production_summary["missingFreeAssetProvenanceScenes"]
        and not production_summary["missingFreeAudioProvenanceAssets"]
        and not production_summary["freeAudioCreditMissingAssets"]
        else "warn"
    )
    stock_candidate_curation_status = (
        "pass"
        if not production_summary["missingStockCandidateCurationScenes"]
        else "warn"
    )
    bgm_sound_status = "fail" if production_summary.get("placeholderBgmAssets") else "pass"
    bgm_rotation_status = (
        "fail"
        if production_summary.get("placeholderBgmAssets")
        else "pass"
        if not production_summary["weakBgmSelectionAssets"]
        else "warn"
    )
    grok_source_curation_status = (
        "pass"
        if not production_summary["missingGrokSourceCurationScenes"]
        else "fail"
    )

    checks = {
        "outputSpec": _check(
            "pass" if output_spec_ok else "fail",
            (
                f"{width}x{height}, fps={fps}, audio={audio_stream.get('codec_name')}, "
                f"duration={duration}, videoDuration={video_duration}, audioDuration={audio_duration}"
            ),
        ),
        "noPlaceholders": _check(
            "pass" if int(local_media_summary.get("placeholder", 0) or 0) == 0 else "fail",
            f"placeholder={local_media_summary.get('placeholder', 0)}",
        ),
        "movingClipPriority": _check(
            moving_clip_status,
            (
                f"videoScenes={moving_scene_count}/{len(manifest.get('scenes', []))}, "
                f"sourceMotion={source_motion_status}, "
                f"lowMotionScenes={source_motion_evidence.get('lowMotionSceneIds') or []}"
            ),
        ),
        "sourceMotionEvidence": _check(
            "pass" if source_motion_status == "pass" else ("fail" if source_motion_status == "fail" else "warn"),
            source_motion_evidence.get("detail") or "source motion audit unavailable",
        ),
        "zeroPaidProviders": _check(
            "pass" if not paid_providers else "fail",
            f"paidProviders={paid_providers}",
        ),
        "captionSafePresets": _check(
            "pass" if not unsafe_caption_scenes else "fail",
            f"unsafeCaptionScenes={unsafe_caption_scenes}",
        ),
        "subtitleArtifact": _check(
            "pass" if subtitle_file_path.with_suffix(".ass").exists() or subtitle_file_path.exists() else "fail",
            str(subtitle_file_path.with_suffix(".ass") if subtitle_file_path.with_suffix(".ass").exists() else subtitle_file_path),
        ),
        "manualSelectionEvidence": _check(
            "pass" if not production_summary["missingRationaleScenes"] else "warn",
            f"missingRationaleScenes={production_summary['missingRationaleScenes']}",
        ),
        "continuityEvidence": _check(
            "pass" if not production_summary["missingContinuityScenes"] else "warn",
            f"missingContinuityScenes={production_summary['missingContinuityScenes']}",
        ),
        "firstTwoSecondHook": _check(
            "pass" if production_summary["firstSceneHookReady"] else "warn",
            f"firstSceneHookReady={production_summary['firstSceneHookReady']}",
        ),
        "cutDensityPacing": _check(
            "pass" if production_summary.get("shortsCutDensityReady") else "warn",
            (
                f"shortsCutDensityReady={production_summary.get('shortsCutDensityReady')}, "
                f"totalScenes={production_summary.get('totalScenes')}, "
                f"videoScenes={production_summary.get('videoScenes')}, "
                f"imageFallbackScenes={production_summary.get('imageFallbackScenes')}, "
                f"repeatedVisualAssetScenes={production_summary.get('repeatedVisualAssetScenes') or []}"
            ),
        ),
        "aiSlopVisualFit": _check(
            production_summary.get("aiSlopVisualFitStatus") or "warn",
            (
                f"visualVerdictScenes={production_summary.get('visualVerdictScenes') or []}, "
                f"missingVisualVerdictScenes={production_summary.get('missingVisualVerdictScenes') or []}, "
                f"failedVisualVerdictScenes={production_summary.get('failedVisualVerdictScenes') or []}"
            ),
        ),
        "stockAiClipFit": _check(
            production_summary.get("stockAiClipFitStatus") or "warn",
            (
                f"stockOnly={production_summary.get('stockOnly')}, "
                f"originalSourceMixRequired={production_summary.get('originalSourceMixRequired')}, "
                f"originalSourceMixReady={production_summary.get('originalSourceMixReady')}, "
                f"minOriginalScenes={production_summary.get('minOriginalScenesForSourceMix')}, "
                f"stockSourceMixGapSceneIds={production_summary.get('stockSourceMixGapSceneIds') or []}, "
                f"weakUploadedOriginalityScenes={production_summary.get('weakUploadedOriginalityScenes') or []}, "
                f"proceduralPlaceholderScenes={production_summary.get('proceduralPlaceholderScenes') or []}, "
                f"failedVisualVerdictScenes={production_summary.get('failedVisualVerdictScenes') or []}, "
                f"stockAiClipFitVerdictScenes={production_summary.get('stockAiClipFitVerdictScenes') or []}, "
                f"missingStockAiClipFitVerdictScenes={production_summary.get('missingStockAiClipFitVerdictScenes') or []}, "
                f"failedStockAiClipFitVerdictScenes={production_summary.get('failedStockAiClipFitVerdictScenes') or []}"
            ),
        ),
        "thumbnailFirstFrameStrength": _check(
            "pass" if production_summary.get("thumbnailFirstFrameReady") else "warn",
            (
                f"thumbnailFirstFrameReady={production_summary.get('thumbnailFirstFrameReady')}, "
                f"firstSceneHookReady={production_summary.get('firstSceneHookReady')}, "
                f"thumbnailReviewScenes={production_summary.get('thumbnailReviewScenes') or []}"
            ),
        ),
        "grokSourceCuration": _check(
            grok_source_curation_status,
            (
                f"grokSourceCurationScenes={production_summary['grokSourceCurationScenes']}, "
                f"readyScenes={production_summary['grokSourceCurationReadyScenes']}, "
                f"missingScenes={production_summary['missingGrokSourceCurationScenes']}, "
                f"missingComparison={production_summary['missingGrokCandidateComparisonScenes']}, "
                f"missingSelectedFile={production_summary['missingGrokSelectedFileScenes']}, "
                f"missingSourceProvenance={production_summary['missingGrokSourceProvenanceScenes']}, "
                f"unacceptableSourceProvenance={production_summary['unacceptableGrokSourceProvenanceScenes']}, "
                f"missingSourceConfirmation={production_summary['missingGrokSourceConfirmationScenes']}, "
                f"sourceReviewVerdictScenes={production_summary['grokSourceReviewVerdictScenes']}, "
                f"rejectedSourceReviewScenes={production_summary['rejectedGrokSourceReviewScenes']}, "
                f"previewCaveats={production_summary['grokPreviewCaveatScenes']}"
            ),
        ),
        "stockOnlyCaveat": _check(
            "warn" if production_summary["stockOnly"] else "pass",
            (
                "all scenes use selected stock video; curated stock is a review draft until at least one creator-owned/Grok/local source is present"
                if production_summary["stockOnly"]
                else "source mix includes non-stock footage or image fallback"
            ),
        ),
        "ttsNarrationEvidence": _check(
            narration_status,
            (
                f"audioProviders={audio_providers}, "
                f"narrationScenes={production_summary['narrationScenes']}, "
                f"subtitleOnlyNarrationScenes={production_summary['subtitleOnlyNarrationScenes']}, "
                f"missingNarrationScenes={production_summary['missingNarrationScenes']}, "
                f"thinNarrationScenes={production_summary['thinNarrationScenes']}, "
                f"noVoiceAudioDesignScenes={production_summary['noVoiceAudioDesignScenes']}, "
                f"voiceoverRequiredNoVoiceScenes={production_summary.get('voiceoverRequiredNoVoiceScenes') or []}, "
                f"visualLedNoVoiceApprovedScenes={production_summary.get('visualLedNoVoiceApprovedScenes') or []}, "
                f"missingNoVoiceAudioScenes={production_summary['missingNoVoiceAudioScenes']}, "
                f"missingNoVoiceAudioReviewScenes={production_summary['missingNoVoiceAudioReviewScenes']}, "
                f"audioDesignModesByScene={production_summary['audioDesignModesByScene']}, "
                f"productionMetaNarrationScenes={production_summary['productionMetaNarrationScenes']}, "
                f"productionMetaSubtitleScenes={production_summary['productionMetaSubtitleScenes']}, "
                f"productionMetaTermsByScene={production_summary['productionMetaTermsByScene']}, "
                f"requiredChars={production_summary['narrationMinCharsByScene']}, "
                f"narrationAudioScenes={sorted(narration_audio_scene_ids)}, "
                f"missingNarrationAudioScenes={missing_narration_audio_scenes}, "
                f"fallbackToneScenes={fallback_tone_scene_ids}"
            ),
        ),
        "voicePolicyCompliance": _check(
            "pass" if not production_summary.get("voiceoverRequiredNoVoiceScenes") else "fail",
            (
                f"template={production_summary.get('contentTemplate')}, "
                f"voiceoverRequiredNoVoiceScenes={production_summary.get('voiceoverRequiredNoVoiceScenes') or []}, "
                f"visualLedNoVoiceApprovedScenes={production_summary.get('visualLedNoVoiceApprovedScenes') or []}"
            ),
        ),
        "captionLayoutReview": _check(
            caption_layout_status,
            (
                f"captionPresetCounts={production_summary['captionPresetCounts']}, "
                f"captionedScenes={production_summary['captionedSceneIds']}, "
                f"captionSparsePlan={production_summary['captionSparsePlan']}, "
                f"longTopHookScenes={production_summary['longTopHookScenes']}, "
                f"reviewed={production_summary['captionLayoutReviewScenes']}, "
                f"missing={production_summary['missingCaptionLayoutReviewScenes']}"
            ),
        ),
        "captionDensityAndSafeZone": _check(
            caption_density_status,
            (
                f"policy={production_summary['captionSafeZonePolicy']}, "
                f"maxCompactChars={production_summary['captionMaxCompactChars']}, "
                f"issues={production_summary['captionDensityIssuesByScene']}"
            ),
        ),
        "assetReuseDiversity": _check(
            asset_diversity_status,
            f"repeatedVisualAssetScenes={production_summary['repeatedVisualAssetScenes']}",
        ),
        "freeAssetProvenance": _check(
            free_asset_provenance_status,
            (
                f"freeAssetProvenanceScenes={production_summary['freeAssetProvenanceScenes']}, "
                f"missingFreeAssetProvenanceScenes={production_summary['missingFreeAssetProvenanceScenes']}, "
                f"freeAudioProvenanceAssets={production_summary['freeAudioProvenanceAssets']}, "
                f"missingFreeAudioProvenanceAssets={production_summary['missingFreeAudioProvenanceAssets']}, "
                f"freeAudioCreditMissingAssets={production_summary['freeAudioCreditMissingAssets']}"
            ),
        ),
        "stockCandidateCuration": _check(
            stock_candidate_curation_status,
            (
                f"stockCandidateCurationScenes={production_summary['stockCandidateCurationScenes']}, "
                f"readyScenes={production_summary['stockCandidateCurationReadyScenes']}, "
                f"missingScenes={production_summary['missingStockCandidateCurationScenes']}, "
                f"missingCandidateCount={production_summary['missingStockCandidateCountScenes']}, "
                f"missingCreator={production_summary['missingStockCandidateCreatorScenes']}, "
                f"missingSource={production_summary['missingStockCandidateSourceScenes']}, "
                f"missingSummary={production_summary['missingStockSelectionSummaryScenes']}, "
                f"issues={production_summary['stockCandidateCurationIssuesByScene']}"
            ),
        ),
        "freeAudioCreditsExport": _check(
            "pass" if not production_summary["freeAudioCreditMissingAssets"] else "warn",
            (
                f"youtubeDescriptionAudioCredits={production_summary['youtubeDescriptionAudioCredits']}, "
                f"missing={production_summary['freeAudioCreditMissingAssets']}"
            ),
        ),
        "bgmAssetRotation": _check(
            bgm_rotation_status,
            (
                f"bgmSelectionAssets={production_summary['bgmSelectionAssets']}, "
                f"weakBgmSelectionAssets={production_summary['weakBgmSelectionAssets']}, "
                f"placeholderBgmAssets={production_summary.get('placeholderBgmAssets') or []}"
            ),
        ),
        "bgmSoundQuality": _check(
            bgm_sound_status,
            (
                f"placeholderBgmAssets={production_summary.get('placeholderBgmAssets') or []}, "
                f"reasons={production_summary.get('placeholderBgmAssetReasons') or {}}"
            ),
        ),
        "templateSourcePlan": _check(
            production_review["templateSourceReview"]["status"],
            (
                f"template={production_review['templateSourceReview']['template']}, "
                f"sourceMix={production_review['templateSourceReview']['sourceMix']}, "
                f"counts={production_review['templateSourceReview']['counts']}, "
                f"required={production_review['templateSourceReview']['requiredFixes']}, "
                f"recommended={production_review['templateSourceReview']['recommendedFixes']}"
            ),
        ),
    }
    publish_readiness = _build_publish_readiness(checks, production_review, local_media_summary)
    channel_readiness = _build_channel_readiness(publish_readiness, production_review, local_media_summary)
    upload_review = _build_upload_review(checks, publish_readiness, channel_readiness, production_review)
    checks["publishReadinessGate"] = _check(
        "pass" if publish_readiness["status"] == "ready" else ("fail" if publish_readiness["status"] == "blocked" else "warn"),
        (
            f"status={publish_readiness['status']}, "
            f"required={len(publish_readiness['requiredFixes'])}, "
            f"recommended={len(publish_readiness['recommendedFixes'])}"
        ),
    )
    checks["channelReadinessGate"] = _check(
        "pass" if channel_readiness["status"] == "channel-ready" else ("fail" if channel_readiness["status"] == "blocked" else "warn"),
        (
            f"status={channel_readiness['status']}, "
            f"required={len(channel_readiness['requiredFixes'])}, "
            f"recommended={len(channel_readiness['recommendedFixes'])}"
        ),
    )
    checks["uploadReviewGate"] = _check(
        "pass" if upload_review["status"] == "ready" else ("fail" if upload_review["status"] == "blocked" else "warn"),
        (
            f"status={upload_review['status']}, "
            f"required={len(upload_review['requiredFixes'])}, "
            f"manual={len(upload_review['manualReviewItems'])}"
        ),
    )
    top_tier_readiness = _build_top_tier_readiness(
        checks,
        publish_readiness,
        channel_readiness,
        upload_review,
        production_review,
    )
    checks["topTierReadinessGate"] = _check(
        "pass" if top_tier_readiness["status"] == "top-tier-ready" else "warn",
        (
            f"status={top_tier_readiness['status']}, "
            f"required={len(top_tier_readiness['requiredFixes'])}"
        ),
    )

    report = {
        "projectId": manifest.get("projectId"),
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "manifestPath": str(manifest_path),
        "outputPath": str(output_path),
        "ffprobe": {
            "tool": ffprobe_info,
            "raw": ffprobe_payload,
        },
        "providers": providers,
        "captionPresets": caption_presets,
        "localMediaSummary": local_media_summary,
        "localMedia": local_media,
        "productionReview": production_review,
        "operatingTemplate": (production_review.get("templateSourceReview") or {}).get("operatingTemplate"),
        "sourceMotionEvidence": source_motion_evidence,
        "publishReadiness": publish_readiness,
        "channelReadiness": channel_readiness,
        "uploadReview": upload_review,
        "topTierReadiness": top_tier_readiness,
        "checks": checks,
    }
    report_path = render_dir / "render-quality-report.json"
    write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2))
    return str(report_path)


# ---------------------------------------------------------------------------
# ASS / SRT subtitle helpers
# ---------------------------------------------------------------------------
def format_srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _ass_escape(value: str) -> str:
    hard_newline = "\uE000"
    text = safe_text(value).replace(r"\N", hard_newline)
    escaped = text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
    return escaped.replace(hard_newline, r"\N")


def _wrap_ass_text(value: str, width: int) -> str:
    escaped = _ass_escape(value)
    wrapped = textwrap.wrap(escaped, width=width, break_long_words=False, break_on_hyphens=False)
    return r"\N".join(wrapped) if wrapped else escaped


def write_scene_card_ass(
    path: Path,
    scene_index: int,
    scene_title: str,
    prompt_text: str,
    subtitle_text: str,
    route_label: str,
) -> None:
    title = _wrap_ass_text(scene_title, 18)
    body = _wrap_ass_text(prompt_text, 26)
    caption = _wrap_ass_text(subtitle_text, 28)
    meta = _ass_escape(f"장면 {scene_index:02d} · {route_label}")
    content = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
            "Style: Meta,Malgun Gothic,26,&H00F5F0E8,&H000000FF,&H7F000000,&H28000000,-1,0,0,0,100,100,0,0,1,1,0,7,96,96,110,1",
            "Style: Title,Malgun Gothic,72,&H00FFF8F0,&H000000FF,&H6F000000,&H22000000,-1,0,0,0,100,100,0,0,1,2,0,7,92,92,208,1",
            "Style: Body,Malgun Gothic,30,&H00EFE7DA,&H000000FF,&H5F000000,&H22000000,0,0,0,0,100,100,0,0,1,1,0,7,98,98,430,1",
            "Style: Caption,Malgun Gothic,34,&H00FFF8F4,&H000000FF,&H76000000,&H22000000,-1,0,0,0,100,100,0,0,1,2,0,2,108,108,190,1",
            "",
            "[Events]",
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
            f"Dialogue: 0,0:00:00.00,0:00:20.00,Meta,,0,0,0,,{meta}",
            f"Dialogue: 0,0:00:00.00,0:00:20.00,Title,,0,0,0,,{title}",
            f"Dialogue: 0,0:00:00.00,0:00:20.00,Body,,0,0,0,,{body}",
            f"Dialogue: 0,0:00:00.00,0:00:20.00,Caption,,0,0,0,,{caption}",
        ]
    )
    write_text(path, content)


def write_scene_subtitle(path: Path, subtitle_text: str, duration_sec: float) -> None:
    write_text(
        path,
        "\n".join(
            [
                "1",
                f"00:00:00,000 --> {format_srt_timestamp(duration_sec)}",
                safe_text(subtitle_text),
                "",
            ]
        ),
    )


def write_project_subtitles(
    path: Path,
    scenes: list[dict],
    subtitle_style: str = "",
) -> None:
    from worker.render.subtitles import generate_ass_subtitle, STYLE_PRESETS

    entries = [
        {
            "start_sec": s["startSec"],
            "end_sec": s["endSec"],
            "title": s.get("title", ""),
            "text": s["subtitleText"],
            "caption_preset": s.get("captionPreset", "lower-info"),
            "layout_variant_key": s.get("layoutVariantKey", ""),
            "layout_variant_label": s.get("layoutVariantLabel", ""),
            "layout_variant_note": s.get("layoutVariantNote", ""),
        }
        for s in scenes
    ]

    # Always emit ASS (RENDERING-SPEC mandate)
    ass_path = path.with_suffix(".ass")
    preset = subtitle_style if subtitle_style in STYLE_PRESETS else "default"

    try:
        generate_ass_subtitle(
            words=entries,
            style_preset=preset,
            highlight_mode="none",  # Word-level highlight requires align.py timestamps
            output_path=str(ass_path),
        )
        return
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        # ASS generation can fail on font loading, malformed entries (missing
        # keys, non-string ``subtitleText``), or missing style presets — fall
        # back to SRT so the render still ships captioned output.
        logger.warning("ASS generation failed, falling back to SRT: %s", e)

    # SRT fallback (kept for resilience)
    lines: list[str] = []
    for index, scene in enumerate(scenes, start=1):
        lines.extend(
            [
                str(index),
                f"{format_srt_timestamp(scene['startSec'])} --> {format_srt_timestamp(scene['endSec'])}",
                safe_text(scene["subtitleText"]),
                "",
            ]
        )
    write_text(path, "\n".join(lines))


# ---------------------------------------------------------------------------
# FFmpeg execution primitives
# ---------------------------------------------------------------------------
def run_ffmpeg(ffmpeg_path: str, args: list[str], log_lines: list[str], cwd: Path | None = None) -> None:
    command = [ffmpeg_path, *args]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        cwd=str(cwd) if cwd else None,
        check=False,
    )
    log_lines.append("$ " + " ".join(command))
    if completed.stdout:
        log_lines.append(completed.stdout.strip())
    if completed.stderr:
        log_lines.append(completed.stderr.strip())
    log_lines.append("")
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"ffmpeg exited with code {completed.returncode}")


def create_scene_poster_gradient(
    ffmpeg_path: str,
    output_path: Path,
    ass_path: Path,
    color_index: int,
    log_lines: list[str],
) -> None:
    """Create a poster image with a gradient background + ASS text overlay."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gradient_src = gradient_source_filter(color_index, size=FRAME_SIZE)
    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-f", "lavfi",
            "-i", gradient_src,
            "-vf", f"ass='{ffmpeg_filter_path(ass_path)}'",
            "-frames:v", "1",
            str(output_path),
        ],
        log_lines,
    )


def create_visual_clip_from_poster(
    ffmpeg_path: str,
    poster_path: Path,
    output_path: Path,
    duration_sec: float,
    motion_preset: str = DEFAULT_MOTION_PRESET,
    log_lines: list[str] | None = None,
) -> None:
    """Create a video clip from a still poster, optionally with motion."""
    if log_lines is None:
        log_lines = []
    output_path.parent.mkdir(parents=True, exist_ok=True)

    motion_filter = zoompan_filter(
        preset=motion_preset,
        duration_sec=duration_sec,
        fps=int(FRAME_RATE),
        width=1080,
        height=1920,
    )

    if motion_filter:
        # zoompan produces video from a single image — no -loop needed
        vf = f"{motion_filter},format=yuv420p"
        run_ffmpeg(
            ffmpeg_path,
            [
                "-y",
                "-i", str(poster_path),
                "-vf", vf,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-an",
                str(output_path),
            ],
            log_lines,
        )
    else:
        run_ffmpeg(
            ffmpeg_path,
            [
                "-y",
                "-loop", "1",
                "-framerate", FRAME_RATE,
                "-t", f"{duration_sec:.2f}",
                "-i", str(poster_path),
                "-vf", VIDEO_FILTER,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-an",
                str(output_path),
            ],
            log_lines,
        )


def create_fallback_audio(
    ffmpeg_path: str,
    output_path: Path,
    duration_sec: float,
    frequency: int,
    log_lines: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-f", "lavfi",
            "-i", f"sine=frequency={frequency}:sample_rate=48000",
            "-t", f"{duration_sec:.2f}",
            "-c:a", "pcm_s16le",
            str(output_path),
        ],
        log_lines,
    )


def create_silent_audio(
    ffmpeg_path: str,
    output_path: Path,
    duration_sec: float,
    log_lines: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t", f"{duration_sec:.2f}",
            "-c:a", "pcm_s16le",
            str(output_path),
        ],
        log_lines,
    )


def _ffprobe_for_ffmpeg(ffmpeg_path: str) -> str:
    candidate = Path(ffmpeg_path)
    if candidate.name.lower().startswith("ffmpeg"):
        sibling = candidate.with_name(candidate.name.replace("ffmpeg", "ffprobe", 1))
        if os.path.lexists(str(sibling)):
            return str(sibling)
    return shutil.which("ffprobe") or "ffprobe"


def _audio_duration_seconds(ffmpeg_path: str, input_path: Path) -> float | None:
    try:
        completed = subprocess.run(
            [
                _ffprobe_for_ffmpeg(ffmpeg_path),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(input_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        duration = float((completed.stdout or "").strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def _atempo_filter_chain(speed: float) -> str:
    filters: list[str] = []
    remaining = max(speed, 0.01)
    while remaining > 2.0:
        filters.append("atempo=2.00000")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.50000")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.5f}")
    return ",".join(filters)


def normalize_audio_duration(
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    duration_sec: float,
    log_lines: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    input_duration = _audio_duration_seconds(ffmpeg_path, input_path)
    audio_filter = f"apad=pad_dur={duration_sec:.2f},atrim=0:{duration_sec:.2f}"
    if input_duration and input_duration > duration_sec + 0.12:
        speed = min(max(input_duration / duration_sec, 1.0), 4.0)
        audio_filter = f"{_atempo_filter_chain(speed)},{audio_filter}"
        log_lines.append(
            f"audio_duration_fit=input={input_duration:.2f}s target={duration_sec:.2f}s "
            f"speed={speed:.3f} mode=tempo-fit"
        )
    elif input_duration:
        log_lines.append(
            f"audio_duration_fit=input={input_duration:.2f}s target={duration_sec:.2f}s mode=pad-trim"
        )
    else:
        log_lines.append(f"audio_duration_fit=input=unknown target={duration_sec:.2f}s mode=pad-trim")
    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-i", str(input_path),
            "-af", audio_filter,
            "-ar", "48000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(output_path),
        ],
        log_lines,
    )


def mix_sfx_into_scene_audio(
    ffmpeg_path: str,
    audio_path: Path,
    sfx_path: Path,
    output_path: Path,
    volume: float,
    log_lines: list[str],
) -> None:
    """Mix SFX track into scene audio using amix, writing to output_path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-i", str(audio_path),
            "-i", str(sfx_path),
            "-filter_complex", f"[1:a]volume={volume}[sfx];[0:a][sfx]amix=inputs=2:duration=first[aout]",
            "-map", "[aout]",
            "-ar", "48000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(output_path),
        ],
        log_lines,
    )


def create_scene_clip(
    ffmpeg_path: str,
    visual_kind: str,
    visual_path: Path,
    audio_path: Path,
    clip_path: Path,
    duration_sec: float,
    motion_preset: str = DEFAULT_MOTION_PRESET,
    log_lines: list[str] | None = None,
) -> None:
    if log_lines is None:
        log_lines = []
    clip_path.parent.mkdir(parents=True, exist_ok=True)

    if visual_kind == "image":
        motion_filter = zoompan_filter(
            preset=motion_preset,
            duration_sec=duration_sec,
            fps=int(FRAME_RATE),
            width=1080,
            height=1920,
        )

        if motion_filter:
            # zoompan reads image once and produces video frames
            run_ffmpeg(
                ffmpeg_path,
                [
                    "-y",
                    "-i", str(visual_path),
                    "-i", str(audio_path),
                    "-vf", f"{motion_filter},format=yuv420p",
                    "-t", f"{duration_sec:.2f}",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    str(clip_path),
                ],
                log_lines,
            )
            return

        # Fallback: static loop (no motion)
        input_args = [
            "-loop", "1",
            "-framerate", FRAME_RATE,
            "-t", f"{duration_sec:.2f}",
            "-i", str(visual_path),
        ]
    else:
        input_args = ["-stream_loop", "-1", "-i", str(visual_path)]

    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            *input_args,
            "-i", str(audio_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-t", f"{duration_sec:.2f}",
            "-vf", VIDEO_FILTER,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(clip_path),
        ],
        log_lines,
    )


# ---------------------------------------------------------------------------
# BGM / TTS helpers
# ---------------------------------------------------------------------------
BGM_MOOD_FOLDER_ALIASES: dict[str, tuple[str, ...]] = {
    "calm": ("calm", "tech-house"),
    "upbeat": ("upbeat", "energetic", "tech-house"),
    "energetic": ("energetic", "upbeat", "tech-house"),
    "tense": ("tense", "cinematic"),
    "cinematic": ("cinematic",),
    "tech-house": ("tech-house", "upbeat", "energetic"),
}

BGM_REPETITION_RISK_TERMS = ("coffee", "cafe", "café", "espresso")
BGM_PLACEHOLDER_RISK_TERMS = (
    "procedural",
    "ffmpeg-procedural",
    "local://ffmpeg",
    "local://video-studio/procedural",
    "sine",
    "beep",
    "bleep",
    "click",
    "test-tone",
    "test tone",
    "fallback-tone",
    "lavfi",
)


def _normalized_bgm_mood(value: object) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _bgm_mood_dirs(bgm_dir: Path, mood: str | None) -> list[Path]:
    normalized = _normalized_bgm_mood(mood)
    if not normalized:
        return []
    candidates = BGM_MOOD_FOLDER_ALIASES.get(normalized, (normalized,))
    dirs: list[Path] = []
    seen: set[str] = set()
    for name in (normalized, *candidates):
        folder_name = _normalized_bgm_mood(name)
        if not folder_name or folder_name in seen:
            continue
        seen.add(folder_name)
        candidate = bgm_dir / folder_name
        if candidate.is_dir():
            dirs.append(candidate)
    return dirs


def _bgm_track_repetition_risk(track: Path) -> bool:
    label = " ".join((track.name, track.stem, track.parent.name)).lower()
    return any(term in label for term in BGM_REPETITION_RISK_TERMS)


def _bgm_quality_risk_reason_from_text(value: object) -> str:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return ""
    compact = re.sub(r"[\s_]+", "-", lowered)
    for term in BGM_PLACEHOLDER_RISK_TERMS:
        normalized = re.sub(r"[\s_]+", "-", term.lower())
        if term.lower() in lowered or normalized in compact:
            return term
    return ""


def _bgm_track_metadata(track: Path) -> dict:
    sidecar_candidates = (
        track.with_suffix(f"{track.suffix}.json"),
        track.with_suffix(".json"),
        track.parent / "sources.json",
        track.parent.parent / "sources.json",
    )
    for sidecar in sidecar_candidates:
        if not sidecar.exists():
            continue
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and track.name in payload and isinstance(payload[track.name], dict):
            return payload[track.name]
        if isinstance(payload, dict) and track.stem in payload and isinstance(payload[track.stem], dict):
            return payload[track.stem]
        if isinstance(payload, dict) and any(
            key in payload
            for key in ("sourceUrl", "sourceLicense", "license", "licenseUrl", "attribution", "sourceAttribution")
        ):
            return payload
    return {}


def _bgm_track_quality_risk_reason(track: Path) -> str:
    metadata = _bgm_track_metadata(track)
    values = [track.as_posix(), track.name, track.stem, track.parent.name]
    if metadata:
        values.extend(str(value) for value in metadata.values() if value not in (None, ""))
    return _bgm_quality_risk_reason_from_text(" ".join(values))


def _stable_bgm_choice(tracks: list[Path], selection_key: str | None) -> tuple[Path, str]:
    ordered_tracks = sorted(tracks, key=lambda item: item.as_posix().lower())
    if not ordered_tracks:
        raise ValueError("tracks must not be empty")
    if selection_key:
        digest = hashlib.sha256(selection_key.encode("utf-8")).hexdigest()
        index = int(digest[:12], 16) % len(ordered_tracks)
        return ordered_tracks[index], "stable-hash"
    return ordered_tracks[0], "stable-first"


def _bgm_track_has_provenance(track: Path) -> bool:
    payload = _bgm_track_metadata(track)
    return bool(
        payload
        and any(
            str(payload.get(key) or "").strip()
            for key in ("sourceUrl", "sourceLicense", "license", "licenseUrl", "attribution", "sourceAttribution")
        )
    )


def _bgm_selection_pool(tracks: list[Path]) -> tuple[list[Path], int]:
    provenance_ready = [track for track in tracks if _bgm_track_has_provenance(track)]
    clean_provenance_ready = [track for track in provenance_ready if not _bgm_track_quality_risk_reason(track)]
    clean_tracks = [track for track in tracks if not _bgm_track_quality_risk_reason(track)]
    if len(clean_provenance_ready) >= 2:
        low_repetition = [track for track in clean_provenance_ready if not _bgm_track_repetition_risk(track)]
        if len(low_repetition) >= 2:
            return low_repetition, len(provenance_ready)
        return clean_provenance_ready, len(provenance_ready)
    if len(clean_tracks) >= 2:
        low_repetition = [track for track in clean_tracks if not _bgm_track_repetition_risk(track)]
        return (low_repetition or clean_tracks), len(provenance_ready)
    if len(provenance_ready) >= 2:
        low_repetition = [track for track in provenance_ready if not _bgm_track_repetition_risk(track)]
        if len(low_repetition) >= 2:
            return low_repetition, len(provenance_ready)
        return provenance_ready, len(provenance_ready)
    low_repetition = [track for track in tracks if not _bgm_track_repetition_risk(track)]
    return (low_repetition or tracks), len(provenance_ready)


def select_bgm_track(
    project_root: Path,
    mood: str | None = None,
    emotion: str | None = None,
    selection_key: str | None = None,
) -> dict:
    """Select a BGM track with deterministic project/template-aware rotation evidence."""
    from worker.render.bgm import EMOTION_MOOD_MAP

    bgm_dir = project_root / "assets" / "bgm"
    if not bgm_dir.is_dir():
        return {"path": None, "candidateCount": 0, "mood": mood or "", "selectionMethod": "missing-library"}

    # Map emotion to mood if mood not directly specified
    if not mood and emotion:
        mood = EMOTION_MOOD_MAP.get(emotion.lower(), "calm")

    # If a mood is specified, look in that subfolder and its proven free-audio aliases first.
    if mood:
        requested_mood = _normalized_bgm_mood(mood)
        mood_dirs = _bgm_mood_dirs(bgm_dir, requested_mood)
        if mood_dirs:
            tracks = [
                f
                for mood_dir in mood_dirs
                for f in mood_dir.iterdir()
                if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS
            ]
            if tracks:
                selection_pool, provenance_count = _bgm_selection_pool(tracks)
                if provenance_count < 2:
                    all_tracks = [f for f in bgm_dir.rglob("*") if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS]
                    fallback_pool, fallback_provenance_count = _bgm_selection_pool(all_tracks)
                    if fallback_provenance_count >= 2:
                        path, method = _stable_bgm_choice(
                            fallback_pool,
                            f"{selection_key}|provenance-fallback" if selection_key else None,
                        )
                        return {
                            "path": path,
                            "candidateCount": len(all_tracks),
                            "provenanceReadyCandidateCount": fallback_provenance_count,
                            "mood": "provenance-fallback",
                            "requestedMood": requested_mood,
                            "selectionKey": selection_key or "",
                            "selectionMethod": method,
                        }
                path, method = _stable_bgm_choice(
                    selection_pool,
                    f"{selection_key}|{requested_mood}|mood-alias" if selection_key else None,
                )
                return {
                    "path": path,
                    "candidateCount": len(tracks),
                    "provenanceReadyCandidateCount": provenance_count,
                    "mood": path.parent.name,
                    "requestedMood": requested_mood,
                    "moodCandidateDirs": [item.name for item in mood_dirs],
                    "selectionKey": selection_key or "",
                    "selectionMethod": method,
                }
    # Collect all tracks from all subdirectories
    tracks = [f for f in bgm_dir.rglob("*") if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS]
    if not tracks:
        return {"path": None, "candidateCount": 0, "mood": mood or "", "selectionMethod": "empty-library"}
    selection_pool, provenance_count = _bgm_selection_pool(tracks)
    path, method = _stable_bgm_choice(selection_pool, f"{selection_key}|all" if selection_key else None)
    return {
        "path": path,
        "candidateCount": len(tracks),
        "provenanceReadyCandidateCount": provenance_count,
        "mood": mood or "all",
        "selectionKey": selection_key or "",
        "selectionMethod": method,
    }


def find_bgm_track(
    project_root: Path,
    mood: str | None = None,
    emotion: str | None = None,
    selection_key: str | None = None,
) -> Path | None:
    """Find a BGM track from the local assets/bgm/ library.

    Uses RENDERING-SPEC §4.1 emotion→mood mapping when emotion is provided.
    """
    selection = select_bgm_track(project_root, mood=mood, emotion=emotion, selection_key=selection_key)
    path = selection.get("path")
    return path if isinstance(path, Path) else None


def prepare_bgm_track(
    ffmpeg_path: str,
    bgm_source: Path,
    output_path: Path,
    duration_sec: float,
    volume: float,  # kept for backward compat but unused (RENDERING-SPEC mandates -8dB)
    log_lines: list[str],
) -> None:
    """Trim/loop BGM to duration with RENDERING-SPEC §4.2 volume rules.

    - Base volume: -8dB (non-narration segments)
    - Fade-in: 0.5s, Fade-out: 1.0s
    - Sidechain ducking to -18dB is handled in mix_bgm_into_output.
    """
    from worker.render.bgm import prepare_bgm_for_video
    try:
        prepare_bgm_for_video(
            bgm_path=str(bgm_source),
            output_path=str(output_path),
            duration_sec=duration_sec,
            ffmpeg_path=ffmpeg_path,
        )
    except RuntimeError as e:
        log_lines.append(f"bgm_prepare_error={e}")


def mix_bgm_into_output(
    ffmpeg_path: str,
    video_path: Path,
    bgm_path: Path,
    output_path: Path,
    log_lines: list[str],
) -> None:
    """Mix BGM into video with audible sidechain ducking (RENDERING-SPEC §4.3).

    Narration present: BGM is ducked under speech without disappearing.
    Narration absent: BGM at prepared volume (-8dB from prepare step).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Sidechain ducking: compress BGM when narration audio is present
    filter_complex = (
        "[0:a]asplit=2[narr][sc];"
        "[sc]aformat=channel_layouts=mono,"
        "compand=attacks=0:decays=0.3:"
        "points=-80/-80|-45/-45|-27/-30|0/-30,"
        "aformat=channel_layouts=stereo[sidechain];"
        f"[1:a]volume={BGM_MIX_GAIN:.3f}[bgm_in];"
        "[bgm_in][sidechain]sidechaincompress="
        f"threshold={BGM_DUCK_THRESHOLD:.3f}:ratio={BGM_DUCK_RATIO:.2f}:"
        f"attack=10:release={BGM_DUCK_RELEASE_MS}:level_sc=1[bgm_ducked];"
        "[narr][bgm_ducked]amix=inputs=2:duration=first[aout]"
    )
    run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-i", str(video_path),
            "-i", str(bgm_path),
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(output_path),
        ],
        log_lines,
    )


def normalize_final_audio_loudness(
    ffmpeg_path: str,
    video_path: Path,
    output_path: Path,
    log_lines: list[str],
) -> bool:
    """Normalize final render audio for Shorts-style playback loudness."""
    if not FINAL_AUDIO_LOUDNORM_ENABLED:
        log_lines.append("audio_loudnorm=disabled")
        return False
    if not video_path.exists():
        log_lines.append(f"audio_loudnorm=skipped missing_input={video_path}")
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    same_path = video_path.resolve() == output_path.resolve()
    source_path = video_path
    preserved_path = output_path.with_name(f"{output_path.stem}.pre-loudnorm{output_path.suffix}")
    temp_output = output_path.with_name(f"{output_path.stem}.loudnorm.tmp{output_path.suffix}")
    if same_path:
        shutil.copy2(output_path, preserved_path)
        source_path = preserved_path

    limiter_limit = max(0.0625, min(1.0, 10 ** (FINAL_AUDIO_LIMITER_TP / 20)))
    loudnorm_filter = (
        f"loudnorm=I={FINAL_AUDIO_TARGET_I:.1f}:"
        f"TP={FINAL_AUDIO_TARGET_TP:.1f}:"
        f"LRA={FINAL_AUDIO_TARGET_LRA:.1f}:print_format=summary,"
        f"alimiter=limit={limiter_limit:.3f}:"
        f"attack={FINAL_AUDIO_LIMITER_ATTACK_MS:.1f}:"
        f"release={FINAL_AUDIO_LIMITER_RELEASE_MS:.1f}:level=false"
    )
    try:
        run_ffmpeg(
            ffmpeg_path,
            [
                "-y",
                "-i", str(source_path),
                "-map", "0:v:0",
                "-map", "0:a:0",
                "-c:v", "copy",
                "-af", loudnorm_filter,
                "-ar", "48000",
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(temp_output),
            ],
            log_lines,
        )
        if temp_output.exists():
            os.replace(temp_output, output_path)
            log_lines.append(
                "audio_loudnorm=applied "
                f"I={FINAL_AUDIO_TARGET_I:.1f} TP={FINAL_AUDIO_TARGET_TP:.1f} LRA={FINAL_AUDIO_TARGET_LRA:.1f}"
            )
            log_lines.append(
                "audio_peak_limiter=applied "
                f"TP={FINAL_AUDIO_LIMITER_TP:.1f} limit={limiter_limit:.3f} "
                f"attack={FINAL_AUDIO_LIMITER_ATTACK_MS:.1f} release={FINAL_AUDIO_LIMITER_RELEASE_MS:.1f}"
            )
            return True
    except Exception as exc:
        log_lines.append(f"audio_loudnorm=failed error={exc}")
        logger.warning("Final audio loudness normalization failed: %s", exc)
    finally:
        if temp_output.exists():
            try:
                temp_output.unlink()
            except OSError:
                pass
    return False


def synthesize_edge_tts(
    text: str,
    output_path: Path,
    scene_cache_dir: Path,
    project_root: Path,
) -> bool:
    """Try Edge TTS adapter. Returns True if audio file was created."""
    from worker.media.adapters import AdapterExecutionContext, run_local_media_adapter

    prompt_file = scene_cache_dir / f"{output_path.stem}.tts-prompt.txt"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(text.strip(), encoding="utf-8")

    context = AdapterExecutionContext(
        adapterKey="edge-tts",
        sceneId=output_path.stem,
        sceneTitle="",
        prompt=text.strip(),
        durationSec=0,
        projectRoot=str(project_root),
        cacheDir=str(scene_cache_dir),
        route="edge-tts",
        manifestPath="",
        promptPath=str(prompt_file),
        outputPath=str(output_path),
        requestPath=str(scene_cache_dir / f"{output_path.stem}.tts-request.json"),
        logPath=str(scene_cache_dir / f"{output_path.stem}.tts-log.txt"),
    )
    result = run_local_media_adapter("edge-tts", context, project_root=project_root)
    return result.succeeded is True and output_path.exists()
