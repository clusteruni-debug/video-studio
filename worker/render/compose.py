from __future__ import annotations

import argparse
import json
import os
import subprocess
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path

from worker.media.adapters import AdapterExecutionContext, run_local_media_adapter
from worker.media.runtime import (
    generate_local_visual_asset,
    summarize_generation_results,
    write_local_media_plan,
    write_local_media_report,
)
from worker.render.motion import zoompan_filter
from worker.render.transitions import (
    build_xfade_filter_complex,
    gradient_source_filter,
)
from worker.runtime.tools import probe_tool
from worker.runtime.windows_tts import synthesize_windows_voiceover

BGM_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
BGM_VOLUME = 0.12  # BGM volume relative to narration
SFX_VOLUME = 0.8  # SFX volume relative to narration

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
FRAME_SIZE = "1080x1920"
FRAME_RATE = "30"
VIDEO_FILTER = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,format=yuv420p"
SCENE_COLORS = ["#183153", "#3f5c7a", "#7c4d3a", "#556b2f", "#5f4b8b", "#7b3f61"]
DEFAULT_MOTION_PRESET = "random"
DEFAULT_TRANSITION_TYPE = "fade"
DEFAULT_TRANSITION_DURATION = 0.5


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
    localMediaSummary: dict
    localMedia: list[dict]
    ttsBackends: list[str] | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _load_manifest(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _run_ffmpeg(ffmpeg_path: str, args: list[str], log_lines: list[str], cwd: Path | None = None) -> None:
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


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _safe_text(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _asset_lookup(manifest: dict, scene_id: str, role: str) -> dict:
    for asset in manifest["assets"]:
        if asset["sceneId"] == scene_id and asset["role"] == role:
            return asset
    raise KeyError(f"Missing asset for scene={scene_id} role={role}")


def _sfx_asset_lookup(manifest: dict, scene_id: str) -> dict | None:
    """Soft lookup for SFX asset — returns None if not present."""
    for asset in manifest["assets"]:
        if asset["sceneId"] == scene_id and asset["role"] == "sfx":
            return asset
    return None


def _resolved_manifest_path(project_root: Path, relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    candidate = project_root / relative_path
    return candidate if candidate.exists() else None


def _ffmpeg_filter_path(path: Path) -> str:
    return path.resolve().as_posix().replace(":", r"\:")


def _ass_escape(value: str) -> str:
    return _safe_text(value).replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _wrap_ass_text(value: str, width: int) -> str:
    escaped = _ass_escape(value)
    wrapped = textwrap.wrap(escaped, width=width, break_long_words=False, break_on_hyphens=False)
    return r"\N".join(wrapped) if wrapped else escaped


def _write_scene_card_ass(
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
    _write_text(path, content)


def _create_scene_poster_gradient(
    ffmpeg_path: str,
    output_path: Path,
    ass_path: Path,
    color_index: int,
    log_lines: list[str],
) -> None:
    """Create a poster image with a gradient background + ASS text overlay."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gradient_src = gradient_source_filter(color_index, size=FRAME_SIZE)
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-f", "lavfi",
            "-i", gradient_src,
            "-vf", f"subtitles='{_ffmpeg_filter_path(ass_path)}'",
            "-frames:v", "1",
            str(output_path),
        ],
        log_lines,
    )


def _create_visual_clip_from_poster(
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
        _run_ffmpeg(
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
        _run_ffmpeg(
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


def _create_fallback_audio(
    ffmpeg_path: str,
    output_path: Path,
    duration_sec: float,
    frequency: int,
    log_lines: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
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


def _normalize_audio_duration(
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    duration_sec: float,
    log_lines: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-i", str(input_path),
            "-af", f"apad=pad_dur={duration_sec:.2f},atrim=0:{duration_sec:.2f}",
            "-ar", "48000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(output_path),
        ],
        log_lines,
    )


def _mix_sfx_into_scene_audio(
    ffmpeg_path: str,
    audio_path: Path,
    sfx_path: Path,
    output_path: Path,
    volume: float,
    log_lines: list[str],
) -> None:
    """Mix SFX track into scene audio using amix, writing to output_path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
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


def _create_scene_clip(
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
            _run_ffmpeg(
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
        input_args = ["-i", str(visual_path)]

    _run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            *input_args,
            "-i", str(audio_path),
            "-t", f"{duration_sec:.2f}",
            "-vf", VIDEO_FILTER,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(clip_path),
        ],
        log_lines,
    )


def _write_scene_subtitle(path: Path, subtitle_text: str, duration_sec: float) -> None:
    _write_text(
        path,
        "\n".join(
            [
                "1",
                f"00:00:00,000 --> {_format_srt_timestamp(duration_sec)}",
                _safe_text(subtitle_text),
                "",
            ]
        ),
    )


def _write_project_subtitles(
    path: Path,
    scenes: list[dict],
    subtitle_style: str = "",
) -> None:
    # If a subtitle style preset is requested, emit ASS instead of SRT
    if subtitle_style:
        from worker.render.subtitles import SUBTITLE_PRESETS, write_styled_ass
        style = SUBTITLE_PRESETS.get(subtitle_style)
        if style:
            ass_path = path.with_suffix(".ass")
            entries = [
                {
                    "start_sec": s["startSec"],
                    "end_sec": s["endSec"],
                    "text": s["subtitleText"],
                }
                for s in scenes
            ]
            write_styled_ass(ass_path, entries, style)
            return

    # Default: SRT output (backwards compatible)
    lines: list[str] = []
    for index, scene in enumerate(scenes, start=1):
        lines.extend(
            [
                str(index),
                f"{_format_srt_timestamp(scene['startSec'])} --> {_format_srt_timestamp(scene['endSec'])}",
                _safe_text(scene["subtitleText"]),
                "",
            ]
        )
    _write_text(path, "\n".join(lines))


def _write_concat_file(path: Path, clip_paths: list[Path]) -> None:
    lines = [f"file '{clip_path.resolve().as_posix()}'" for clip_path in clip_paths]
    _write_text(path, "\n".join(lines) + "\n")


def _resolve_ffmpeg_executable(project_root: Path) -> tuple[str, dict]:
    ffmpeg = probe_tool("ffmpeg", project_root=project_root)
    executable = ffmpeg.resolvedPath or ffmpeg.path
    if not executable:
        raise RuntimeError(ffmpeg.detail or "FFmpeg is not available for local rendering")
    return executable, ffmpeg.to_dict()


def _get_scene_motion_preset(scene: dict) -> str:
    """Read motionPreset from the scene dict, defaulting to random."""
    return scene.get("motionPreset") or DEFAULT_MOTION_PRESET


def _find_bgm_track(project_root: Path) -> Path | None:
    """Find a BGM track from the local assets/bgm/ library."""
    import random as _random
    bgm_dir = project_root / "assets" / "bgm"
    if not bgm_dir.is_dir():
        return None
    tracks = [f for f in bgm_dir.iterdir() if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS]
    if not tracks:
        return None
    return _random.choice(tracks)


def _prepare_bgm_track(
    ffmpeg_path: str,
    bgm_source: Path,
    output_path: Path,
    duration_sec: float,
    volume: float,
    log_lines: list[str],
) -> None:
    """Trim BGM to duration and lower volume, output as WAV for mixing."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-i", str(bgm_source),
            "-af", f"volume={volume},aloop=loop=-1:size=2000000000,atrim=0:{duration_sec:.2f},afade=t=out:st={max(0, duration_sec - 2):.2f}:d=2",
            "-ar", "48000",
            "-ac", "2",
            "-c:a", "pcm_s16le",
            "-t", f"{duration_sec:.2f}",
            str(output_path),
        ],
        log_lines,
    )


def _mix_bgm_into_output(
    ffmpeg_path: str,
    video_path: Path,
    bgm_path: Path,
    output_path: Path,
    log_lines: list[str],
) -> None:
    """Mix BGM track into the final video at lower volume."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-i", str(video_path),
            "-i", str(bgm_path),
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(output_path),
        ],
        log_lines,
    )


def _synthesize_edge_tts(
    text: str,
    output_path: Path,
    scene_cache_dir: Path,
    project_root: Path,
) -> bool:
    """Try Edge TTS adapter. Returns True if audio file was created."""
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


def _get_manifest_transition(manifest: dict) -> tuple[str, float]:
    """Read transition settings from the manifest, with defaults."""
    transition_type = manifest.get("transitionType") or DEFAULT_TRANSITION_TYPE
    transition_duration = manifest.get("transitionDuration", DEFAULT_TRANSITION_DURATION)
    return transition_type, float(transition_duration)


def compose_smoke_render(
    manifest_path: Path | str,
    project_root: Path | str = ".",
    progress_callback=None,
) -> SmokeRenderResult:
    resolved_project_root = Path(project_root).resolve()
    resolved_manifest_path = Path(manifest_path).resolve()
    manifest = _load_manifest(resolved_manifest_path)
    local_media_plan = write_local_media_plan(
        manifest=manifest,
        manifest_path=resolved_manifest_path,
        project_root=resolved_project_root,
    )

    ffmpeg_path, ffmpeg_info = _resolve_ffmpeg_executable(resolved_project_root)

    render_dir = resolved_project_root / manifest["renderDir"]
    render_dir.mkdir(parents=True, exist_ok=True)
    subtitle_file_path = resolved_project_root / manifest["subtitleFilePath"]
    concat_file_path = resolved_project_root / manifest["concatFilePath"]
    output_path = resolved_project_root / manifest["outputPath"]
    log_path = render_dir / "ffmpeg-smoke.log"

    transition_type, transition_duration = _get_manifest_transition(manifest)

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

    for index, scene in enumerate(manifest["scenes"]):
        scene_id = scene["sceneId"]
        if progress_callback:
            try:
                progress_callback(index, scene_id)
            except Exception:
                pass  # SSE write errors should not abort render
        scene_cache_dir = resolved_project_root / scene["cacheDir"]
        scene_cache_dir.mkdir(parents=True, exist_ok=True)
        visual_asset = _asset_lookup(manifest, scene_id, "visual")
        audio_asset = _asset_lookup(manifest, scene_id, "audio")
        subtitle_asset = _asset_lookup(manifest, scene_id, "subtitle")

        visual_path = resolved_project_root / visual_asset["outputPath"]
        audio_path = resolved_project_root / audio_asset["outputPath"]
        subtitle_path = resolved_project_root / subtitle_asset["outputPath"]
        source_audio_path = _resolved_manifest_path(resolved_project_root, audio_asset.get("sourcePath"))
        clip_path = scene_cache_dir / f"{scene_id}.segment.mp4"
        poster_path = visual_path if scene["visualKind"] == "image" else scene_cache_dir / f"{scene_id}.poster.png"
        ass_path = scene_cache_dir / f"{scene_id}.card.ass"
        raw_tts_path = scene_cache_dir / f"{scene_id}.tts.raw.wav"

        visual_input_path: Path = poster_path  # safe default for all branches
        motion_preset = _get_scene_motion_preset(scene)
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
            log_lines.append(f"visual_source=uploaded path={visual_input_path}")
            log_lines.append("")
        elif local_media_result.status == "generated":
            visual_input_path = Path(local_media_result.outputPath)
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
            _write_scene_card_ass(
                path=ass_path,
                scene_index=index + 1,
                scene_title=scene["title"],
                prompt_text=visual_asset["prompt"],
                subtitle_text=scene["subtitleText"],
                route_label=scene["route"].upper(),
            )
            # Use gradient background instead of flat color
            _create_scene_poster_gradient(
                ffmpeg_path=ffmpeg_path,
                output_path=poster_path,
                ass_path=ass_path,
                color_index=index,
                log_lines=log_lines,
            )

            if scene["visualKind"] == "video":
                _create_visual_clip_from_poster(
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
            _normalize_audio_duration(
                ffmpeg_path=ffmpeg_path,
                input_path=source_audio_path,
                output_path=audio_path,
                duration_sec=scene["durationSec"],
                log_lines=log_lines,
            )
        else:
            tts_ok = False
            tts_backend = "none"

            # 1. Try Edge TTS (cross-platform, free)
            edge_tts_raw = scene_cache_dir / f"{scene_id}.edge-tts.mp3"
            edge_ok = _synthesize_edge_tts(
                text=scene["subtitleText"],
                output_path=edge_tts_raw,
                scene_cache_dir=scene_cache_dir,
                project_root=resolved_project_root,
            )
            if edge_ok:
                tts_ok = True
                tts_backend = "edge-tts"
                raw_tts_path = edge_tts_raw
                log_lines.append(f"tts_backend=edge-tts ok=True")
                log_lines.append("")

            # 2. Fallback: Windows Speech (Windows-only)
            if not tts_ok:
                tts_result = synthesize_windows_voiceover(
                    text=scene["subtitleText"],
                    output_path=raw_tts_path,
                    working_dir=scene_cache_dir,
                )
                if tts_result.ok and raw_tts_path.exists():
                    tts_ok = True
                    tts_backend = "windows-speech"
                log_lines.append(f"tts_backend=windows-speech ok={tts_result.ok} voice={tts_result.voiceName} detail={tts_result.detail}")
                log_lines.append("")

            tts_backends_used.add(tts_backend)
            if tts_ok:
                _normalize_audio_duration(
                    ffmpeg_path=ffmpeg_path,
                    input_path=raw_tts_path,
                    output_path=audio_path,
                    duration_sec=scene["durationSec"],
                    log_lines=log_lines,
                )
            else:
                log_lines.append("tts_backend=fallback-sine (all TTS failed)")
                log_lines.append("")
                render_warnings.append(f"장면 {scene_id}: 음성 합성 실패 — 사인톤으로 대체됨")
                _create_fallback_audio(
                    ffmpeg_path=ffmpeg_path,
                    output_path=audio_path,
                    duration_sec=scene["durationSec"],
                    frequency=frequency,
                    log_lines=log_lines,
                )

        # SFX mixing: if a SFX file exists on disk, mix into scene audio
        sfx_asset = _sfx_asset_lookup(manifest, scene_id)
        if sfx_asset:
            sfx_source = _resolved_manifest_path(resolved_project_root, sfx_asset.get("sourcePath"))
            sfx_file = sfx_source if sfx_source else (resolved_project_root / sfx_asset["outputPath"])
            if sfx_file.exists():
                import shutil
                audio_pre_sfx = scene_cache_dir / f"{scene_id}.pre-sfx.wav"
                shutil.copy2(audio_path, audio_pre_sfx)
                try:
                    _mix_sfx_into_scene_audio(
                        ffmpeg_path=ffmpeg_path,
                        audio_path=audio_pre_sfx,
                        sfx_path=sfx_file,
                        output_path=audio_path,
                        volume=SFX_VOLUME,
                        log_lines=log_lines,
                    )
                    log_lines.append(f"sfx_status=mixed source={sfx_file}")
                except Exception as sfx_err:
                    shutil.copy2(audio_pre_sfx, audio_path)
                    log_lines.append(f"sfx_status=failed error={sfx_err}")
                log_lines.append("")
            else:
                log_lines.append(f"sfx_status=skipped (file not found: {sfx_file})")
                log_lines.append("")

        _write_scene_subtitle(
            path=subtitle_path,
            subtitle_text=scene["subtitleText"],
            duration_sec=scene["durationSec"],
        )
        _create_scene_clip(
            ffmpeg_path=ffmpeg_path,
            visual_kind=scene["visualKind"],
            visual_path=visual_input_path,
            audio_path=audio_path,
            clip_path=clip_path,
            duration_sec=scene["durationSec"],
            motion_preset=motion_preset,
            log_lines=log_lines,
        )
        scene_clip_paths.append(clip_path)
        scene_durations.append(scene["durationSec"])

    _write_project_subtitles(
        subtitle_file_path,
        manifest["scenes"],
        subtitle_style=manifest.get("subtitleStyle", ""),
    )
    # When ASS subtitles are written, the actual file has .ass suffix
    actual_subtitle_path = subtitle_file_path
    if manifest.get("subtitleStyle"):
        ass_candidate = subtitle_file_path.with_suffix(".ass")
        if ass_candidate.exists():
            actual_subtitle_path = ass_candidate

    _write_concat_file(concat_file_path, scene_clip_paths)

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
        _run_ffmpeg(
            ffmpeg_path,
            [
                "-y",
                *input_args,
                "-filter_complex", filter_complex,
                "-map", "[vout]",
                "-map", "[amerged]",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(output_path),
            ],
            log_lines,
        )
    else:
        log_lines.append("concatenation=simple-concat (no transitions)")
        log_lines.append("")
        _run_ffmpeg(
            ffmpeg_path,
            [
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file_path.name,
                "-vf", f"subtitles={subtitle_file_path.name},scale=1080:1920,format=yuv420p",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-movflags", "+faststart",
                output_path.name,
            ],
            log_lines,
            cwd=render_dir,
        )

    # BGM mixing: find a local track and mix it under the narration
    bgm_track = _find_bgm_track(resolved_project_root)
    if bgm_track:
        bgm_prepared = render_dir / "bgm-prepared.wav"
        total_duration = manifest.get("totalDurationSec", sum(scene_durations))
        log_lines.append(f"bgm_source={bgm_track}")
        _prepare_bgm_track(
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
                _mix_bgm_into_output(
                    ffmpeg_path=ffmpeg_path,
                    video_path=video_without_bgm,
                    bgm_path=bgm_prepared,
                    output_path=output_path,
                    log_lines=log_lines,
                )
                log_lines.append("bgm_status=mixed")
            except Exception as bgm_err:
                shutil.copy2(video_without_bgm, output_path)
                log_lines.append(f"bgm_status=failed error={bgm_err}")
        else:
            log_lines.append("bgm_status=skipped (preparation failed)")
    else:
        log_lines.append("bgm_status=none (no tracks in assets/bgm/)")
    log_lines.append("")

    _write_text(log_path, "\n".join(log_lines))
    local_media_summary = summarize_generation_results(local_media_results)
    local_media_report_path = write_local_media_report(
        render_dir=render_dir,
        plan=local_media_plan,
        results=local_media_results,
    )

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
        localMediaSummary=local_media_summary,
        localMedia=[result.to_dict() for result in local_media_results],
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
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
