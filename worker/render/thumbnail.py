"""Thumbnail generation — extract a frame from video and optionally add text overlay."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _find_ffmpeg() -> str:
    """Resolve ffmpeg binary path."""
    for candidate in ("ffmpeg", r"C:\ffmpeg\bin\ffmpeg.exe"):
        try:
            subprocess.run(
                [candidate, "-version"],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
            )
            return candidate
        except FileNotFoundError:
            continue
    return "ffmpeg"


def generate_thumbnail(
    video_path: Path,
    output_path: Path,
    text: str = "",
    timestamp_sec: float = 1.5,
    size: str = "1080x1920",
    font: str = "Malgun Gothic",
    fontsize: int = 72,
    fontcolor: str = "white",
    borderw: int = 4,
    bordercolor: str = "black",
) -> bool:
    """Extract a single frame from *video_path* and save as PNG/JPG.

    If *text* is provided, it is overlaid using FFmpeg ``drawtext``.
    Returns ``True`` on success.
    """
    ffmpeg = _find_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    vf_parts = [f"scale={size}:force_original_aspect_ratio=increase"]
    w, h = size.split("x")
    vf_parts.append(f"crop={w}:{h}")

    if text:
        # FFmpeg drawtext requires escaping: \ % ' : and newlines
        safe_text = (
            text.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("'", "\u2019")  # replace with unicode right single quote
            .replace(":", "\\:")
            .replace("\n", " ")
        )
        safe_font = font.replace(":", "\\:")
        vf_parts.append(
            f"drawtext=text='{safe_text}'"
            f":font='{safe_font}'"
            f":fontsize={fontsize}"
            f":fontcolor={fontcolor}"
            f":borderw={borderw}"
            f":bordercolor={bordercolor}"
            f":x=(w-tw)/2"
            f":y=h*0.12"
        )

    vf = ",".join(vf_parts)

    cmd = [
        ffmpeg, "-y",
        "-ss", str(timestamp_sec),
        "-i", str(video_path),
        "-vframes", "1",
        "-vf", vf,
        str(output_path),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW,
    )

    return result.returncode == 0 and output_path.exists()


def generate_thumbnail_from_image(
    image_path: Path,
    output_path: Path,
    text: str = "",
    size: str = "1080x1920",
    font: str = "Malgun Gothic",
    fontsize: int = 72,
) -> bool:
    """Create a thumbnail from a still image with optional text overlay."""
    ffmpeg = _find_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    w, h = size.split("x")
    vf_parts = [
        f"scale={size}:force_original_aspect_ratio=increase",
        f"crop={w}:{h}",
    ]

    if text:
        safe_text = (
            text.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("'", "\u2019")
            .replace(":", "\\:")
            .replace("\n", " ")
        )
        safe_font = font.replace(":", "\\:")
        vf_parts.append(
            f"drawtext=text='{safe_text}'"
            f":font='{safe_font}'"
            f":fontsize={fontsize}"
            f":fontcolor=white:borderw=4:bordercolor=black"
            f":x=(w-tw)/2:y=h*0.12"
        )

    cmd = [
        ffmpeg, "-y",
        "-i", str(image_path),
        "-vframes", "1",
        "-vf", ",".join(vf_parts),
        str(output_path),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW,
    )

    return result.returncode == 0 and output_path.exists()
