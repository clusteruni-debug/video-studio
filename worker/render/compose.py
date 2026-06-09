"""Draft render orchestrator — reads a manifest and produces a single MP4.

FFmpeg primitives, subtitle writers, and BGM/TTS helpers live in
``compose_ffmpeg.py``. This file is intentionally an orchestrator +
CLI entry point only.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from worker.media.runtime import (
    generate_local_visual_asset,
    summarize_generation_results,
    write_local_media_plan,
    write_local_media_report,
)
from worker.render.compose_ffmpeg import (
    BGM_EXTENSIONS,
    BGM_VOLUME,
    FINAL_VISUAL_POLISH_FILTER,
    H264_RENDER_ARGS,
    SFX_VOLUME,
    _production_meta_terms,
    asset_lookup,
    create_fallback_audio,
    create_scene_clip,
    create_scene_poster_gradient,
    create_silent_audio,
    create_visual_clip_from_poster,
    ffmpeg_filter_path,
    get_manifest_transition,
    get_scene_motion_preset,
    load_manifest,
    mix_bgm_into_output,
    mix_sfx_into_scene_audio,
    normalize_final_audio_loudness,
    normalize_audio_duration,
    prepare_bgm_track,
    resolve_ffmpeg_executable,
    resolve_relative_asset_path,
    run_ffmpeg,
    sfx_asset_lookup,
    select_bgm_track,
    synthesize_edge_tts,
    write_concat_file,
    write_project_subtitles,
    write_render_quality_report,
    write_scene_card_ass,
    write_scene_subtitle,
    write_text,
)
from worker.render.foley import (
    create_procedural_foley,
    infer_procedural_foley_pattern,
    procedural_foley_metadata,
)
from worker.render.transitions import build_xfade_filter_complex
from worker.runtime.windows_tts import synthesize_windows_voiceover

logger = logging.getLogger(__name__)

NO_VOICE_AUDIO_MODES = {
    "no-voice",
    "no-narration",
    "music-first",
    "ambient-first",
    "native-audio",
}


def _tts_narration_text_for_scene(scene: dict) -> tuple[str, str]:
    """Return viewer-facing narration text, never production notes or captions."""
    narration_text = str(scene.get("narrationText") or "").strip()
    subtitle_text = str(scene.get("subtitleText") or "").strip()
    if narration_text:
        terms = _production_meta_terms(narration_text)
        if terms:
            return "", f"production-meta-narration:{','.join(terms)}"
        return narration_text, ""
    if subtitle_text:
        terms = _production_meta_terms(subtitle_text)
        if terms:
            return "", f"production-meta-subtitle:{','.join(terms)}"
        return "", "subtitle-only-not-viewer-narration"
    return "", "missing-narration"


def _is_no_voice_scene(scene: dict, manifest: dict) -> bool:
    raw = (
        scene.get("audioDesignMode")
        or scene.get("audio_design_mode")
        or scene.get("voiceMode")
        or scene.get("voice_mode")
        or manifest.get("audioDesignMode")
        or manifest.get("audio_design_mode")
    )
    return str(raw or "").strip().lower().replace("_", "-") in NO_VOICE_AUDIO_MODES


@dataclass(slots=True)
class SmokeRenderResult:
    ok: bool
    projectId: str
    manifestPath: str
    outputPath: str
    concatFilePath: str
    subtitleFilePath: str
    logPath: str
    ffmpeg: dict
    sceneClipPaths: list[str]
    localMediaPlanPath: str
    localMediaReportPath: str
    qualityReportPath: str
    qualityReport: dict | None
    localMediaSummary: dict
    localMedia: list[dict]
    ttsBackends: list[str] | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root).as_posix()
    except ValueError:
        return str(path)


def _read_bgm_sidecar(bgm_track: Path) -> dict:
    """Read optional source/license metadata for a local BGM file."""
    sidecar_candidates = [
        bgm_track.with_suffix(f"{bgm_track.suffix}.json"),
        bgm_track.with_suffix(".json"),
        bgm_track.parent / "sources.json",
        bgm_track.parent.parent / "sources.json",
    ]
    for sidecar in sidecar_candidates:
        if not sidecar.exists():
            continue
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Unreadable BGM metadata sidecar: %s", sidecar)
            continue
        if isinstance(payload, dict) and bgm_track.name in payload and isinstance(payload[bgm_track.name], dict):
            return payload[bgm_track.name]
        if isinstance(payload, dict) and bgm_track.stem in payload and isinstance(payload[bgm_track.stem], dict):
            return payload[bgm_track.stem]
        if isinstance(payload, dict) and any(key in payload for key in ("sourceUrl", "sourceLicense", "license", "attribution")):
            return payload
    return {}


def _resolve_operator_bgm_selection(
    manifest: dict,
    project_root: Path,
    mood: str | None = None,
) -> dict | None:
    """Resolve an operator-pinned BGM asset from the render manifest."""
    bgm_asset = manifest.get("bgmAsset") or manifest.get("selectedBgmAsset")
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
        resolved.relative_to(project_root.resolve())
    except (OSError, ValueError):
        return None
    if not resolved.is_file() or resolved.suffix.lower() not in BGM_EXTENSIONS:
        return None
    selection_key = str(
        bgm_asset.get("candidateId")
        or bgm_asset.get("selectionKey")
        or bgm_asset.get("sourcePath")
        or raw_path
    ).strip()
    return {
        "path": resolved,
        "candidateCount": int(bgm_asset.get("candidateCount") or 1),
        "mood": bgm_asset.get("mood") or mood or "",
        "selectionMethod": "operator-pinned",
        "selectionKey": f"operator-pinned:{selection_key}",
        "operatorSelected": True,
        "operatorSelectionReason": "dashboard-free-audio-import",
    }


def _append_bgm_asset(
    manifest: dict,
    *,
    bgm_track: Path,
    prepared_path: Path,
    project_root: Path,
    mood: str | None,
    duration_sec: float,
    selection: dict | None = None,
) -> None:
    metadata = _read_bgm_sidecar(bgm_track)
    selection = selection or {}
    source_provider = str(metadata.get("sourceProvider") or metadata.get("provider") or "").strip()
    asset = {
        "id": "global-bgm",
        "sceneId": "global",
        "role": "audio",
        "provider": "local-bgm",
        "kind": "bgm",
        "prompt": mood or "auto-matched local BGM",
        "durationSec": round(duration_sec, 2),
        "outputPath": _relative_to_project(prepared_path, project_root),
        "sourceOrigin": "local-library",
        "sourcePath": _relative_to_project(bgm_track, project_root),
        "sourceLabel": metadata.get("title") or metadata.get("sourceLabel") or bgm_track.name,
        "candidateCount": int(selection.get("candidateCount") or 0),
        "selectionMood": selection.get("mood") or mood or "",
        "selectionMethod": selection.get("selectionMethod") or "",
        "selectionKey": selection.get("selectionKey") or "",
    }
    if selection.get("operatorSelected"):
        asset["operatorSelected"] = True
    if selection.get("operatorSelectionReason"):
        asset["operatorSelectionReason"] = selection.get("operatorSelectionReason")
    if source_provider:
        asset["sourceProvider"] = source_provider
    for key in (
        "sourceUrl",
        "sourceExternalId",
        "sourceLicense",
        "license",
        "licenseUrl",
        "attribution",
        "sourceAttribution",
        "artist",
        "creator",
        "downloadDate",
        "attributionRequired",
    ):
        if key in metadata and metadata.get(key) not in (None, ""):
            value = metadata.get(key)
            asset[key] = value
    assets = manifest.setdefault("assets", [])
    assets[:] = [
        item for item in assets
        if not (item.get("id") == "global-bgm" and item.get("role") == "audio")
    ]
    assets.append(asset)


def _record_scene_audio_render(
    audio_asset: dict,
    *,
    provider: str,
    kind: str,
    output_path: Path,
    project_root: Path,
    source_origin: str,
    source_label: str,
    render_detail: str = "",
) -> None:
    audio_asset["provider"] = provider
    audio_asset["kind"] = kind
    audio_asset["outputPath"] = _relative_to_project(output_path, project_root)
    audio_asset["sourceOrigin"] = source_origin
    audio_asset["sourceLabel"] = source_label
    if render_detail:
        audio_asset["renderDetail"] = render_detail


def _sfx_output_path(sfx_asset: dict, scene_cache_dir: Path, scene_id: str, project_root: Path) -> Path:
    output_path = str(sfx_asset.get("outputPath") or "").strip()
    if output_path:
        return project_root / output_path
    return scene_cache_dir / f"{scene_id}.sfx.wav"


def _has_operator_sfx_source(sfx_asset: dict) -> bool:
    if str(sfx_asset.get("sourceOrigin") or "") == "generated-procedural-local":
        return False
    return any(
        str(sfx_asset.get(key) or "").strip()
        for key in ("sourcePath", "sourceUrl", "sourceExternalId")
    )


def _is_procedural_foley_asset(sfx_asset: dict) -> bool:
    return str(sfx_asset.get("sourceOrigin") or "") == "generated-procedural-local"


def compose_smoke_render(
    manifest_path: Path | str,
    project_root: Path | str = ".",
    progress_callback=None,
) -> SmokeRenderResult:
    resolved_project_root = Path(project_root).resolve()
    resolved_manifest_path = Path(manifest_path).resolve()
    manifest = load_manifest(resolved_manifest_path)
    local_media_plan = write_local_media_plan(
        manifest=manifest,
        manifest_path=resolved_manifest_path,
        project_root=resolved_project_root,
    )

    ffmpeg_path, ffmpeg_info = resolve_ffmpeg_executable(resolved_project_root)

    render_dir = resolved_project_root / manifest["renderDir"]
    render_dir.mkdir(parents=True, exist_ok=True)
    subtitle_file_path = resolved_project_root / manifest["subtitleFilePath"]
    concat_file_path = resolved_project_root / manifest["concatFilePath"]
    output_path = resolved_project_root / manifest["outputPath"]
    log_path = render_dir / "ffmpeg-smoke.log"

    transition_type, transition_duration = get_manifest_transition(manifest)

    log_lines: list[str] = [
        f"project_id={manifest['projectId']}",
        f"manifest={resolved_manifest_path}",
        f"transition_type={transition_type}",
        f"transition_duration={transition_duration}",
        "",
    ]
    scene_clip_paths: list[Path] = []
    scene_durations: list[float] = []
    local_media_results = []
    tts_backends_used: set[str] = set()
    render_warnings: list[str] = []
    manifest_dirty = False

    for index, scene in enumerate(manifest["scenes"]):
        scene_id = scene["sceneId"]
        if progress_callback:
            try:
                progress_callback(index, scene_id)
            except Exception as cb_err:
                # SSE write errors should not abort render
                logger.debug("progress_callback failed for scene %s: %s", scene_id, cb_err)
        scene_cache_dir = resolved_project_root / scene["cacheDir"]
        scene_cache_dir.mkdir(parents=True, exist_ok=True)
        visual_asset = asset_lookup(manifest, scene_id, "visual")
        audio_asset = asset_lookup(manifest, scene_id, "audio")
        subtitle_asset = asset_lookup(manifest, scene_id, "subtitle")

        visual_path = resolved_project_root / visual_asset["outputPath"]
        audio_path = resolved_project_root / audio_asset["outputPath"]
        subtitle_path = resolved_project_root / subtitle_asset["outputPath"]
        source_audio_path = resolve_relative_asset_path(resolved_project_root, audio_asset.get("sourcePath"))
        clip_path = scene_cache_dir / f"{scene_id}.segment.mp4"
        poster_path = visual_path if scene["visualKind"] == "image" else scene_cache_dir / f"{scene_id}.poster.png"
        ass_path = scene_cache_dir / f"{scene_id}.card.ass"
        raw_tts_path = scene_cache_dir / f"{scene_id}.tts.raw.wav"

        visual_input_path: Path = poster_path  # safe default for all branches
        clip_visual_kind = scene["visualKind"]
        motion_preset = get_scene_motion_preset(scene)
        # Hook optimisation: scene 1 always zooms in for visual impact
        if index == 0 and motion_preset == "random":
            motion_preset = "zoom_in"
        frequency = 440 + (index * 70)

        local_media_result = generate_local_visual_asset(
            manifest=manifest,
            manifest_path=resolved_manifest_path,
            scene=scene,
            project_root=resolved_project_root,
            adapters=local_media_plan.adapters,
            provider_override=visual_asset.get("provider"),
        )
        local_media_results.append(local_media_result)

        if local_media_result.status == "uploaded":
            visual_input_path = Path(local_media_result.outputPath)
            clip_visual_kind = local_media_result.outputKind
            log_lines.append(f"visual_source=uploaded path={visual_input_path}")
            log_lines.append("")
        elif local_media_result.status == "generated":
            visual_input_path = Path(local_media_result.outputPath)
            clip_visual_kind = local_media_result.outputKind
            log_lines.append(
                f"visual_source=generated adapter={local_media_result.adapterKey} path={visual_input_path}"
            )
            if local_media_result.logPath:
                log_lines.append(f"visual_log={local_media_result.logPath}")
            log_lines.append("")
        else:
            log_lines.append(
                f"visual_source=placeholder adapter={local_media_result.adapterKey} detail={local_media_result.detail}"
            )
            if local_media_result.logPath:
                log_lines.append(f"visual_log={local_media_result.logPath}")
            log_lines.append("")

            # RENDERING-SPEC §5.1 step 2: Try Pexels video before gradient fallback
            pexels_video_used = False
            try:
                from worker.bridge.image_router import search_pexels_video, download_pexels_video
                pexels_result = search_pexels_video(
                    query=visual_asset.get("prompt", scene["title"]),
                    min_duration=scene["durationSec"],
                )
                if pexels_result:
                    pexels_dl_path = scene_cache_dir / f"{scene_id}.pexels.mp4"
                    if download_pexels_video(pexels_result["url"], str(pexels_dl_path)):
                        visual_input_path = pexels_dl_path
                        clip_visual_kind = "video"
                        pexels_video_used = True
                        log_lines.append(
                            f"visual_source=pexels-video id={pexels_result.get('pexels_id')} "
                            f"dur={pexels_result['duration']}s {pexels_result['width']}x{pexels_result['height']}"
                        )
                        log_lines.append("")
            except Exception as e:
                # Any failure here (network, API, import) must fall through to
                # the gradient poster below — never block the render pipeline.
                logger.debug("pexels video fallback failed for scene %s: %s", scene_id, e)
                log_lines.append(f"pexels_video_fallback_error={e}")

            if not pexels_video_used:
                write_scene_card_ass(
                    path=ass_path,
                    scene_index=index + 1,
                    scene_title=scene["title"],
                    prompt_text=visual_asset["prompt"],
                    subtitle_text=scene["subtitleText"],
                    route_label=scene["route"].upper(),
                )
                # Use gradient background instead of flat color
                create_scene_poster_gradient(
                    ffmpeg_path=ffmpeg_path,
                    output_path=poster_path,
                    ass_path=ass_path,
                    color_index=index,
                    log_lines=log_lines,
                )

                if scene["visualKind"] == "video":
                    create_visual_clip_from_poster(
                        ffmpeg_path=ffmpeg_path,
                        poster_path=poster_path,
                        output_path=visual_path,
                        duration_sec=scene["durationSec"],
                        motion_preset=motion_preset,
                        log_lines=log_lines,
                    )

                    visual_input_path = visual_path
                else:
                    visual_input_path = poster_path

        if source_audio_path and source_audio_path.exists():
            log_lines.append(f"audio_source=uploaded path={source_audio_path}")
            log_lines.append("")
            normalize_audio_duration(
                ffmpeg_path=ffmpeg_path,
                input_path=source_audio_path,
                output_path=audio_path,
                duration_sec=scene["durationSec"],
                log_lines=log_lines,
            )
            _record_scene_audio_render(
                audio_asset,
                provider=str(audio_asset.get("provider") or "upload"),
                kind=str(audio_asset.get("kind") or "uploaded-audio"),
                output_path=audio_path,
                project_root=resolved_project_root,
                source_origin=str(audio_asset.get("sourceOrigin") or "uploaded"),
                source_label=str(audio_asset.get("sourceLabel") or source_audio_path.name),
                render_detail="normalized uploaded/source narration audio",
            )
            manifest_dirty = True
        else:
            if _is_no_voice_scene(scene, manifest):
                log_lines.append("audio_design=no-voice tts_skipped=True")
                log_lines.append("")
                create_silent_audio(
                    ffmpeg_path=ffmpeg_path,
                    output_path=audio_path,
                    duration_sec=scene["durationSec"],
                    log_lines=log_lines,
                )
                _record_scene_audio_render(
                    audio_asset,
                    provider="local-silence",
                    kind="silent-bed",
                    output_path=audio_path,
                    project_root=resolved_project_root,
                    source_origin="generated-silence",
                    source_label="Intentional no-voice bed",
                    render_detail="no-voice scene; BGM/native audio carries the edit instead of explanatory TTS",
                )
                manifest_dirty = True
                tts_backends_used.add("no-voice")
            else:
                tts_ok = False
                tts_backend = "none"

                narration_text, tts_skip_reason = _tts_narration_text_for_scene(scene)
                if not narration_text:
                    log_lines.append(f"tts_skipped=True reason={tts_skip_reason}")
                    log_lines.append("")
                    create_silent_audio(
                        ffmpeg_path=ffmpeg_path,
                        output_path=audio_path,
                        duration_sec=scene["durationSec"],
                        log_lines=log_lines,
                    )
                    _record_scene_audio_render(
                        audio_asset,
                        provider="local-silence",
                        kind="silent-bed",
                        output_path=audio_path,
                        project_root=resolved_project_root,
                        source_origin="generated-silence",
                        source_label="TTS skipped",
                        render_detail=f"TTS skipped before synthesis: {tts_skip_reason}",
                    )
                    manifest_dirty = True
                    tts_backends_used.add("tts-skipped")
                    render_warnings.append(f"장면 {scene_id}: TTS 생략 — {tts_skip_reason}")
                else:
                    # 1. Try Edge TTS (cross-platform, free)
                    edge_tts_raw = scene_cache_dir / f"{scene_id}.edge-tts.mp3"
                    edge_ok = synthesize_edge_tts(
                        text=narration_text,
                        output_path=edge_tts_raw,
                        scene_cache_dir=scene_cache_dir,
                        project_root=resolved_project_root,
                    )
                    if edge_ok:
                        tts_ok = True
                        tts_backend = "edge-tts"
                        raw_tts_path = edge_tts_raw
                        log_lines.append("tts_backend=edge-tts ok=True")
                        log_lines.append("")

                    # 2. Fallback: Windows Speech (Windows-only)
                    if not tts_ok:
                        tts_result = synthesize_windows_voiceover(
                            text=narration_text,
                            output_path=raw_tts_path,
                            working_dir=scene_cache_dir,
                        )
                        if tts_result.ok and raw_tts_path.exists():
                            tts_ok = True
                            tts_backend = "windows-speech"
                        log_lines.append(
                            f"tts_backend=windows-speech ok={tts_result.ok} "
                            f"voice={tts_result.voiceName} detail={tts_result.detail}"
                        )
                        log_lines.append("")

                    tts_backends_used.add(tts_backend)
                    if tts_ok:
                        normalize_audio_duration(
                            ffmpeg_path=ffmpeg_path,
                            input_path=raw_tts_path,
                            output_path=audio_path,
                            duration_sec=scene["durationSec"],
                            log_lines=log_lines,
                        )
                        _record_scene_audio_render(
                            audio_asset,
                            provider=tts_backend,
                            kind="voiceover",
                            output_path=audio_path,
                            project_root=resolved_project_root,
                            source_origin="generated-local-tts",
                            source_label="Edge TTS" if tts_backend == "edge-tts" else "Windows Speech",
                            render_detail=f"{tts_backend} synthesized scene narration",
                        )
                        manifest_dirty = True
                    else:
                        log_lines.append("tts_backend=fallback-sine (all TTS failed)")
                        log_lines.append("")
                        render_warnings.append(f"장면 {scene_id}: 음성 합성 실패 — 사인톤으로 대체됨")
                        create_fallback_audio(
                            ffmpeg_path=ffmpeg_path,
                            output_path=audio_path,
                            duration_sec=scene["durationSec"],
                            frequency=frequency,
                            log_lines=log_lines,
                        )
                        _record_scene_audio_render(
                            audio_asset,
                            provider="fallback-sine",
                            kind="fallback-tone",
                            output_path=audio_path,
                            project_root=resolved_project_root,
                            source_origin="generated-fallback",
                            source_label="FFmpeg sine fallback, not narration",
                            render_detail="all free TTS backends failed; this must block publishing",
                        )
                        manifest_dirty = True

        # SFX mixing: if a SFX file exists on disk, mix into scene audio
        sfx_asset = sfx_asset_lookup(manifest, scene_id)
        if sfx_asset:
            sfx_source = resolve_relative_asset_path(resolved_project_root, sfx_asset.get("sourcePath"))
            sfx_file = sfx_source if sfx_source else _sfx_output_path(
                sfx_asset,
                scene_cache_dir,
                scene_id,
                resolved_project_root,
            )
            if (
                (not sfx_file.exists() or _is_procedural_foley_asset(sfx_asset))
                and _is_no_voice_scene(scene, manifest)
                and not _has_operator_sfx_source(sfx_asset)
            ):
                foley_pattern = infer_procedural_foley_pattern(scene)
                try:
                    create_procedural_foley(
                        ffmpeg_path=ffmpeg_path,
                        output_path=sfx_file,
                        duration_sec=scene["durationSec"],
                        pattern=foley_pattern,
                        log_lines=log_lines,
                    )
                    sfx_asset.update(
                        procedural_foley_metadata(
                            pattern=foley_pattern,
                            output_path=sfx_file,
                            project_root=resolved_project_root,
                        )
                    )
                    manifest_dirty = True
                    log_lines.append(f"sfx_status=generated-procedural pattern={foley_pattern}")
                except Exception as foley_err:
                    logger.warning("procedural foley generation failed for scene %s: %s", scene_id, foley_err)
                    log_lines.append(f"sfx_status=procedural-generation-failed error={foley_err}")
            if sfx_file.exists():
                import shutil
                audio_pre_sfx = scene_cache_dir / f"{scene_id}.pre-sfx.wav"
                shutil.copy2(audio_path, audio_pre_sfx)
                try:
                    mix_sfx_into_scene_audio(
                        ffmpeg_path=ffmpeg_path,
                        audio_path=audio_pre_sfx,
                        sfx_path=sfx_file,
                        output_path=audio_path,
                        volume=SFX_VOLUME,
                        log_lines=log_lines,
                    )
                    log_lines.append(f"sfx_status=mixed source={sfx_file}")
                except Exception as sfx_err:
                    # SFX mix failure must roll back to the un-mixed audio
                    # so the render continues with the plain narration.
                    logger.warning("sfx mix failed for scene %s: %s", scene_id, sfx_err)
                    shutil.copy2(audio_pre_sfx, audio_path)
                    log_lines.append(f"sfx_status=failed error={sfx_err}")
                log_lines.append("")
            else:
                log_lines.append(f"sfx_status=skipped (file not found: {sfx_file})")
                log_lines.append("")

        write_scene_subtitle(
            path=subtitle_path,
            subtitle_text=scene["subtitleText"],
            duration_sec=scene["durationSec"],
        )
        create_scene_clip(
            ffmpeg_path=ffmpeg_path,
            visual_kind=clip_visual_kind,
            visual_path=visual_input_path,
            audio_path=audio_path,
            clip_path=clip_path,
            duration_sec=scene["durationSec"],
            motion_preset=motion_preset,
            log_lines=log_lines,
        )
        scene_clip_paths.append(clip_path)
        scene_durations.append(scene["durationSec"])

    write_project_subtitles(
        subtitle_file_path,
        manifest["scenes"],
        subtitle_style=manifest.get("subtitleStyle", ""),
    )
    # When ASS subtitles are written (styled or default highlight), the actual file has .ass suffix
    actual_subtitle_path = subtitle_file_path
    ass_candidate = subtitle_file_path.with_suffix(".ass")
    if ass_candidate.exists():
        actual_subtitle_path = ass_candidate

    write_concat_file(concat_file_path, scene_clip_paths)

    # Final concatenation: use xfade transitions or simple concat
    xfade_result = build_xfade_filter_complex(
        clip_paths=scene_clip_paths,
        durations=scene_durations,
        transition_type=transition_type,
        transition_duration=transition_duration,
        subtitle_file=actual_subtitle_path,
        output_scale="1080:1920",
    )

    if xfade_result:
        input_args, filter_complex = xfade_result
        log_lines.append(f"concatenation=xfade transition={transition_type} duration={transition_duration}")
        log_lines.append("")
        run_ffmpeg(
            ffmpeg_path,
            [
                "-y",
                *input_args,
                "-filter_complex", filter_complex,
                "-map", "[vout]",
                "-map", "[amerged]",
                *H264_RENDER_ARGS,
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(output_path),
            ],
            log_lines,
        )
    else:
        log_lines.append("concatenation=simple-concat (no transitions)")
        log_lines.append("")
        subtitle_filter = "ass" if actual_subtitle_path.suffix == ".ass" else "subtitles"
        subtitle_filter_arg = f"{subtitle_filter}=filename='{ffmpeg_filter_path(actual_subtitle_path)}'"
        run_ffmpeg(
            ffmpeg_path,
            [
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file_path.name,
                "-vf",
                f"{subtitle_filter_arg},{FINAL_VISUAL_POLISH_FILTER}",
                *H264_RENDER_ARGS,
                "-c:a", "aac",
                "-movflags", "+faststart",
                output_path.name,
            ],
            log_lines,
            cwd=render_dir,
        )

    # BGM mixing: find a local track and mix it under the narration
    bgm_enabled = manifest.get("bgmEnabled", True)
    bgm_mood = None
    if bgm_enabled:
        plan_path = resolved_project_root / "storage" / "inputs" / manifest.get("projectId", "") / "project-plan.json"
        if plan_path.exists():
            try:
                plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
                bgm_mood = plan_data.get("bgmMood")
            except (OSError, json.JSONDecodeError) as e:
                log_lines.append(f"bgm_plan_read_error={e}")
    if bgm_enabled:
        bgm_selection = _resolve_operator_bgm_selection(manifest, resolved_project_root, bgm_mood) or select_bgm_track(
            resolved_project_root,
            mood=bgm_mood,
            selection_key=f"{manifest.get('projectId', '')}:{manifest.get('templateType') or manifest.get('contentTemplate') or ''}",
        )
    else:
        bgm_selection = {"path": None}
    bgm_track = bgm_selection.get("path") if isinstance(bgm_selection.get("path"), Path) else None
    if bgm_track:
        bgm_prepared = render_dir / "bgm-prepared.wav"
        total_duration = manifest.get("totalDurationSec", sum(scene_durations))
        log_lines.append(f"bgm_source={bgm_track}")
        log_lines.append(
            "bgm_selection="
            f"mood={bgm_selection.get('mood')} "
            f"candidate_count={bgm_selection.get('candidateCount')} "
            f"method={bgm_selection.get('selectionMethod')}"
        )
        prepare_bgm_track(
            ffmpeg_path=ffmpeg_path,
            bgm_source=bgm_track,
            output_path=bgm_prepared,
            duration_sec=total_duration,
            volume=BGM_VOLUME,
            log_lines=log_lines,
        )
        if bgm_prepared.exists():
            import shutil
            video_without_bgm = render_dir / "pre-bgm.mp4"
            shutil.copy2(output_path, video_without_bgm)
            try:
                mix_bgm_into_output(
                    ffmpeg_path=ffmpeg_path,
                    video_path=video_without_bgm,
                    bgm_path=bgm_prepared,
                    output_path=output_path,
                    log_lines=log_lines,
                )
                _append_bgm_asset(
                    manifest,
                    bgm_track=bgm_track,
                    prepared_path=bgm_prepared,
                    project_root=resolved_project_root,
                    mood=bgm_mood,
                    duration_sec=total_duration,
                    selection=bgm_selection,
                )
                write_text(resolved_manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
                manifest_dirty = False
                log_lines.append("bgm_status=mixed")
            except Exception as bgm_err:
                # BGM mix failure must roll back to the pre-BGM video so the
                # render still produces a playable MP4.
                logger.warning("bgm mix failed: %s", bgm_err)
                shutil.copy2(video_without_bgm, output_path)
                log_lines.append(f"bgm_status=failed error={bgm_err}")
        else:
            log_lines.append("bgm_status=skipped (preparation failed)")
    else:
        log_lines.append("bgm_status=none (no tracks in assets/bgm/)")
    normalize_final_audio_loudness(
        ffmpeg_path=ffmpeg_path,
        video_path=output_path,
        output_path=output_path,
        log_lines=log_lines,
    )
    log_lines.append("")

    if manifest_dirty:
        write_text(resolved_manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))

    write_text(log_path, "\n".join(log_lines))
    local_media_summary = summarize_generation_results(local_media_results)
    local_media_report_path = write_local_media_report(
        render_dir=render_dir,
        plan=local_media_plan,
        results=local_media_results,
    )
    local_media_payload = [result.to_dict() for result in local_media_results]
    quality_report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=resolved_manifest_path,
        output_path=output_path,
        project_root=resolved_project_root,
        local_media_summary=local_media_summary,
        local_media=local_media_payload,
        subtitle_file_path=subtitle_file_path,
    )
    try:
        quality_report = json.loads(Path(quality_report_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        quality_report = None

    return SmokeRenderResult(
        ok=True,
        projectId=manifest["projectId"],
        manifestPath=str(resolved_manifest_path),
        outputPath=str(output_path),
        concatFilePath=str(concat_file_path),
        subtitleFilePath=str(subtitle_file_path),
        logPath=str(log_path),
        ffmpeg=ffmpeg_info,
        sceneClipPaths=[str(path) for path in scene_clip_paths],
        localMediaPlanPath=local_media_plan.planPath,
        localMediaReportPath=local_media_report_path,
        qualityReportPath=quality_report_path,
        qualityReport=quality_report,
        localMediaSummary=local_media_summary,
        localMedia=local_media_payload,
        ttsBackends=sorted(tts_backends_used) if tts_backends_used else None,
        warnings=render_warnings if render_warnings else None,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local draft render for a saved project bundle.")
    parser.add_argument("--project-id", required=True, help="Project id under storage/inputs/<project-id>")
    parser.add_argument("--project-root", default=".", help="Project root where storage/ lives")
    parser.add_argument("--manifest-path", help="Optional explicit manifest path")
    return parser


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = _build_parser()
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

    # Load .env so adapter env vars (VIDEO_STUDIO_*) are available
    env_file = project_root / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file, override=False)
        except ImportError:
            pass
    manifest_path = (
        Path(args.manifest_path).resolve()
        if args.manifest_path
        else project_root / "storage" / "inputs" / args.project_id / "render-manifest.json"
    )
    result = compose_smoke_render(manifest_path=manifest_path, project_root=project_root)
    # CLI stdout contract: JSON-only output so shell callers can pipe into jq.
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
