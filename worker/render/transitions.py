"""FFmpeg xfade / acrossfade filter builders for scene transitions."""

from __future__ import annotations

from pathlib import Path

TRANSITION_TYPES = ("fade", "dissolve", "wipeleft", "none")
DEFAULT_TRANSITION_DURATION = 0.5


def build_xfade_filter_complex(
    clip_paths: list[Path],
    durations: list[float],
    transition_type: str = "fade",
    transition_duration: float = DEFAULT_TRANSITION_DURATION,
    subtitle_file: Path | None = None,
    output_scale: str = "1080:1920",
) -> tuple[list[str], str] | None:
    """Build a ``-filter_complex`` string that chains xfade + acrossfade.

    Returns ``(input_args, filter_complex_string)`` or ``None`` when the
    transition type is ``"none"`` or there are fewer than 2 clips (use simple
    concat instead).
    """
    if transition_type == "none" or not transition_type:
        return None
    if len(clip_paths) < 2:
        return None
    if transition_type not in TRANSITION_TYPES:
        transition_type = "fade"

    td = max(0.0, transition_duration)
    n = len(clip_paths)

    # ----- input args -----
    input_args: list[str] = []
    for clip in clip_paths:
        input_args.extend(["-i", str(clip)])

    # ----- video xfade chain -----
    video_parts: list[str] = []
    accumulated = 0.0

    for i in range(n - 1):
        if i == 0:
            src_label = "[0:v]"
        else:
            src_label = f"[v{i - 1}]"
        dst_label = f"[{i + 1}:v]"

        offset = accumulated + durations[i] - td
        if i < n - 2:
            out_label = f"[v{i}]"
        else:
            out_label = "[vmerged]"

        video_parts.append(
            f"{src_label}{dst_label}xfade=transition={transition_type}"
            f":duration={td:.3f}:offset={offset:.3f}{out_label}"
        )
        accumulated += durations[i] - td

    # ----- audio acrossfade chain -----
    audio_parts: list[str] = []
    for i in range(n - 1):
        if i == 0:
            src_label = "[0:a]"
        else:
            src_label = f"[a{i - 1}]"
        dst_label = f"[{i + 1}:a]"

        if i < n - 2:
            out_label = f"[a{i}]"
        else:
            out_label = "[amerged]"

        audio_parts.append(
            f"{src_label}{dst_label}acrossfade=d={td:.3f}:c1=tri:c2=tri{out_label}"
        )

    # ----- optional subtitle overlay + final scale -----
    final_video_filters: list[str] = []
    if subtitle_file:
        safe_path = subtitle_file.resolve().as_posix().replace(":", r"\:")
        final_video_filters.append(f"subtitles='{safe_path}'")
    final_video_filters.append(f"scale={output_scale}")
    final_video_filters.append("format=yuv420p")

    video_parts.append(
        f"[vmerged]{','.join(final_video_filters)}[vout]"
    )

    filter_complex = ";\n".join(video_parts + audio_parts)
    return input_args, filter_complex


def build_simple_concat_with_subtitles(
    concat_file: Path,
    subtitle_file: Path,
    output_scale: str = "1080:1920",
) -> list[str]:
    """Return FFmpeg args for simple concat (no transitions), preserving
    the existing behaviour as a fallback.
    """
    return [
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file.name,
        "-vf", f"subtitles={subtitle_file.name},scale={output_scale},format=yuv420p",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-movflags", "+faststart",
    ]


# ---------------------------------------------------------------------------
# Gradient background helpers (Phase 1d)
# ---------------------------------------------------------------------------

GRADIENT_PAIRS = [
    ("#183153", "#2c5f99"),
    ("#3f5c7a", "#1a3a4e"),
    ("#7c4d3a", "#4a2a1e"),
    ("#556b2f", "#2a3a18"),
    ("#5f4b8b", "#3a2d5e"),
    ("#7b3f61", "#4a2540"),
]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def gradient_source_filter(color_index: int, size: str = "1080x1920") -> str:
    """Return an FFmpeg lavfi source + vf chain that produces a vertical gradient.

    Uses ``color`` source with ``geq`` filter for maximum FFmpeg compatibility.
    """
    pair = GRADIENT_PAIRS[color_index % len(GRADIENT_PAIRS)]
    r1, g1, b1 = _hex_to_rgb(pair[0])
    r2, g2, b2 = _hex_to_rgb(pair[1])

    geq = (
        f"geq="
        f"r='{r1}+({r2}-{r1})*Y/H':"
        f"g='{g1}+({g2}-{g1})*Y/H':"
        f"b='{b1}+({b2}-{b1})*Y/H'"
    )
    return f"color=c=black:s={size},{geq}"
