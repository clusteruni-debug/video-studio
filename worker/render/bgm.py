"""BGM auto-matching and audio mixing with sidechain ducking.

Spec reference: docs/RENDERING-SPEC.md §4
"""

from __future__ import annotations

import os
import random
import subprocess
from pathlib import Path

BGM_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}

# RENDERING-SPEC §4.1 — emotion → BGM mood mapping
EMOTION_MOOD_MAP: dict[str, str] = {
    "neutral": "calm",
    "shock": "tense",
    "surprise": "tense",
    "funny": "upbeat",
    "humor": "upbeat",
    "serious": "cinematic",
    "sad": "cinematic",
    "excitement": "upbeat",
}

# All valid mood subdirectories
VALID_MOODS = {"calm", "tense", "upbeat", "cinematic"}

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def select_bgm(emotion: str, project_root: Path | str = ".") -> str | None:
    """Select a BGM track based on scene emotion.

    Parameters
    ----------
    emotion:
        Scene emotion string (e.g., "neutral", "shock", "funny").
    project_root:
        Project root directory containing assets/bgm/.

    Returns
    -------
    Path to the selected BGM track, or None if no tracks available.
    """
    root = Path(project_root)
    bgm_dir = root / "assets" / "bgm"
    if not bgm_dir.is_dir():
        return None

    # Map emotion to mood
    mood = EMOTION_MOOD_MAP.get(emotion.lower(), "calm")

    # Try mood-specific folder first
    mood_dir = bgm_dir / mood
    if mood_dir.is_dir():
        tracks = [f for f in mood_dir.iterdir() if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS]
        if tracks:
            return str(random.choice(tracks))

    # Fallback: any track from any mood folder
    all_tracks = [
        f for f in bgm_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS
    ]
    if all_tracks:
        return str(random.choice(all_tracks))

    return None


def mix_audio(
    narration_path: str,
    bgm_path: str,
    output_path: str,
    ffmpeg_path: str = "ffmpeg",
    ducking: bool = True,
) -> None:
    """Mix narration and BGM audio with sidechain ducking.

    RENDERING-SPEC §4.2–§4.3:
    - Narration segments: BGM -18dB
    - Non-narration segments: BGM -8dB
    - Fade-in: 0.5s, Fade-out: 1.0s

    Parameters
    ----------
    narration_path:
        Path to narration WAV/audio file.
    bgm_path:
        Path to BGM audio file.
    output_path:
        Where to write the mixed audio.
    ffmpeg_path:
        FFmpeg executable path.
    ducking:
        If True, use sidechain ducking. If False, use simple volume mixing.
    """
    narr = Path(narration_path)
    bgm = Path(bgm_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if not narr.exists():
        raise FileNotFoundError(f"Narration file not found: {narration_path}")
    if not bgm.exists():
        raise FileNotFoundError(f"BGM file not found: {bgm_path}")

    # Get narration duration for fade-out timing
    duration = _get_audio_duration(str(narr), ffmpeg_path)

    if ducking:
        # Sidechain ducking (RENDERING-SPEC §4.3)
        filter_complex = (
            "[0:a]asplit=2[narr][sc];"
            "[sc]aformat=channel_layouts=mono,"
            "compand=attacks=0:decays=0.3:"
            "points=-80/-80|-45/-45|-27/-30|0/-30,"
            "aformat=channel_layouts=stereo[sidechain];"
            f"[1:a]afade=t=in:d=0.5,afade=t=out:st={max(0, duration - 1.0):.2f}:d=1.0[bgm_faded];"
            "[bgm_faded][sidechain]sidechaincompress="
            "threshold=0.02:ratio=6:attack=10:release=300:level_sc=1[bgm_ducked];"
            "[narr][bgm_ducked]amix=inputs=2:duration=first[out]"
        )
    else:
        # Simple mixing: BGM at -18dB (RENDERING-SPEC §4.2)
        filter_complex = (
            f"[1:a]volume=-18dB,"
            f"afade=t=in:d=0.5,afade=t=out:st={max(0, duration - 1.0):.2f}:d=1.0[bgm];"
            "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[out]"
        )

    cmd = [
        ffmpeg_path, "-y",
        "-i", str(narr),
        "-stream_loop", "-1",  # Loop BGM if shorter than narration
        "-i", str(bgm),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-ar", "48000",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        str(out),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg mix failed: {result.stderr[:500]}")


def prepare_bgm_for_video(
    bgm_path: str,
    output_path: str,
    duration_sec: float,
    ffmpeg_path: str = "ffmpeg",
) -> None:
    """Prepare a BGM track for video mixing: loop/trim + fade.

    RENDERING-SPEC §4.2:
    - Non-narration volume: -8dB
    - Fade-in: 0.5s, Fade-out: 1.0s
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    fade_out_start = max(0, duration_sec - 1.0)

    cmd = [
        ffmpeg_path, "-y",
        "-stream_loop", "-1",
        "-i", str(bgm_path),
        "-af", (
            f"volume=-8dB,"
            f"afade=t=in:d=0.5,"
            f"afade=t=out:st={fade_out_start:.2f}:d=1.0"
        ),
        "-ar", "48000",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        "-t", f"{duration_sec:.2f}",
        str(out),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg BGM prep failed: {result.stderr[:500]}")


def _get_audio_duration(audio_path: str, ffmpeg_path: str = "ffmpeg") -> float:
    """Get audio duration in seconds using ffprobe."""
    ffprobe_path = str(Path(ffmpeg_path).with_name(
        Path(ffmpeg_path).name.replace("ffmpeg", "ffprobe")
    ))
    try:
        result = subprocess.run(
            [ffprobe_path, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        return float(result.stdout.strip())
    except (ValueError, OSError):
        return 60.0  # Safe default
