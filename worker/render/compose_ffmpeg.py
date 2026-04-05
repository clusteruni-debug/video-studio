"""FFmpeg primitive operations for compose.py.

Extracted from compose.py to keep the orchestrator file under the 660-line limit.
Contains: FFmpeg command wrappers, scene clip construction, audio mixing,
subtitle writers, manifest helpers, and shared constants.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import textwrap
from pathlib import Path

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
VIDEO_FILTER = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,format=yuv420p"
SCENE_COLORS = ["#183153", "#3f5c7a", "#7c4d3a", "#556b2f", "#5f4b8b", "#7b3f61"]
DEFAULT_MOTION_PRESET = "none"
DEFAULT_TRANSITION_TYPE = "fade"
DEFAULT_TRANSITION_DURATION = 0.5

BGM_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
BGM_VOLUME = float(os.environ.get("VIDEO_STUDIO_BGM_VOLUME", "0.35"))
SFX_VOLUME = 0.8  # SFX volume relative to narration


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
    return safe_text(value).replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


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
            "text": s["subtitleText"],
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


def normalize_audio_duration(
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    duration_sec: float,
    log_lines: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
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
        input_args = ["-i", str(visual_path)]

    run_ffmpeg(
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


# ---------------------------------------------------------------------------
# BGM / TTS helpers
# ---------------------------------------------------------------------------
def find_bgm_track(project_root: Path, mood: str | None = None, emotion: str | None = None) -> Path | None:
    """Find a BGM track from the local assets/bgm/ library.

    Uses RENDERING-SPEC §4.1 emotion→mood mapping when emotion is provided.
    """
    import random as _random
    from worker.render.bgm import EMOTION_MOOD_MAP

    bgm_dir = project_root / "assets" / "bgm"
    if not bgm_dir.is_dir():
        return None

    # Map emotion to mood if mood not directly specified
    if not mood and emotion:
        mood = EMOTION_MOOD_MAP.get(emotion.lower(), "calm")

    # If a mood is specified, look in that subfolder first
    if mood:
        mood_dir = bgm_dir / mood
        if mood_dir.is_dir():
            tracks = [f for f in mood_dir.iterdir() if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS]
            if tracks:
                return _random.choice(tracks)
    # Collect all tracks from all subdirectories
    tracks = [f for f in bgm_dir.rglob("*") if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS]
    if not tracks:
        return None
    return _random.choice(tracks)


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
    """Mix BGM into video with sidechain ducking (RENDERING-SPEC §4.3).

    Narration present: BGM at ~-18dB (sidechaincompress).
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
        "[1:a][sidechain]sidechaincompress="
        "threshold=0.02:ratio=6:attack=10:release=300:level_sc=1[bgm_ducked];"
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
