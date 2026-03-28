"""Subtitle styling engine — ASS-based configurable subtitle rendering.

Provides ``SubtitleStyle`` dataclass with presets for different short-form
video genres.  The ``write_styled_ass()`` function emits an ASS file that
FFmpeg's ``subtitles=`` filter can consume directly (same as SRT, no code
change needed on the consumer side).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SubtitleStyle:
    """Configurable subtitle appearance for ASS output."""

    font_name: str = "Malgun Gothic"
    font_size: int = 44
    # ASS colours are in &HAABBGGRR format (alpha, blue, green, red)
    primary_color: str = "&H00FFFFFF"
    outline_color: str = "&H00000000"
    back_color: str = "&H80000000"
    outline_width: float = 3.0
    shadow_distance: float = 1.5
    # ASS alignment numpad: 1=bottom-left 2=bottom-center 5=middle-center 8=top-center
    alignment: int = 2
    margin_l: int = 80
    margin_r: int = 80
    margin_v: int = 120
    bold: bool = True
    animation: str = "none"  # "none" | "fade_in" | "pop"


# -- Presets for common Korean short-form genres --

SUBTITLE_PRESETS: dict[str, SubtitleStyle] = {
    "default": SubtitleStyle(),
    "news": SubtitleStyle(
        font_size=40,
        bold=True,
        alignment=2,
        margin_v=160,
        outline_width=3.5,
    ),
    "story": SubtitleStyle(
        font_size=48,
        outline_width=4.0,
        margin_v=100,
        shadow_distance=2.0,
    ),
    "ranking": SubtitleStyle(
        font_size=56,
        bold=True,
        alignment=5,
        margin_v=200,
    ),
    "minimal": SubtitleStyle(
        font_size=36,
        outline_width=1.5,
        shadow_distance=0,
        margin_v=80,
    ),
    "impact": SubtitleStyle(
        font_size=60,
        primary_color="&H0000FFFF",  # yellow (BGR)
        outline_color="&H00000000",
        outline_width=5.0,
        shadow_distance=2.5,
        bold=True,
    ),
}


def _ass_escape(text: str) -> str:
    """Escape special ASS characters and convert newlines to ASS line breaks."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp ``H:MM:SS.cc`` (centiseconds)."""
    total_cs = int(round(seconds * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def animation_to_ass_tags(animation: str, duration_ms: int = 300) -> str:
    """Convert animation name to ASS override tags prepended to dialogue text."""
    if animation == "fade_in":
        return f"{{\\fad({duration_ms},0)}}"
    if animation == "pop":
        return (
            f"{{\\fscx0\\fscy0\\t(0,{duration_ms},\\fscx100\\fscy100)}}"
        )
    return ""


def write_styled_ass(
    path: Path,
    entries: list[dict],
    style: SubtitleStyle | None = None,
) -> None:
    """Write an ASS subtitle file with configurable styling.

    Parameters
    ----------
    path:
        Output ``.ass`` file path.
    entries:
        List of ``{"start_sec": float, "end_sec": float, "text": str}``.
    style:
        Subtitle appearance.  Falls back to ``SubtitleStyle()`` defaults.
    """
    s = style or SubtitleStyle()
    bold_flag = -1 if s.bold else 0
    anim_prefix = animation_to_ass_tags(s.animation)

    header = "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
        "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
        "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding",
        f"Style: Sub,{s.font_name},{s.font_size},"
        f"{s.primary_color},&H000000FF,"
        f"{s.outline_color},{s.back_color},"
        f"{bold_flag},0,0,0,"
        f"100,100,0,0,"
        f"1,{s.outline_width:.1f},{s.shadow_distance:.1f},"
        f"{s.alignment},{s.margin_l},{s.margin_r},{s.margin_v},1",
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ])

    dialogues: list[str] = []
    for entry in entries:
        start = _format_ass_time(entry["start_sec"])
        end = _format_ass_time(entry["end_sec"])
        text = _ass_escape(entry["text"])
        dialogues.append(
            f"Dialogue: 0,{start},{end},Sub,,0,0,0,,{anim_prefix}{text}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n" + "\n".join(dialogues) + "\n", encoding="utf-8")


def _estimate_word_timings(text: str, duration_sec: float) -> list[dict]:
    """Estimate per-word timing proportionally by character count.

    Korean words have roughly uniform duration per character, so character-count
    proportional timing is a reasonable approximation.
    """
    if duration_sec <= 0:
        return []
    tokens = text.strip().split()
    if not tokens:
        return []
    total_chars = sum(len(w) for w in tokens)
    if total_chars == 0:
        return []

    result = []
    cursor = 0.0
    for word in tokens:
        word_dur = (len(word) / total_chars) * duration_sec
        result.append({"text": word, "start": cursor, "end": cursor + word_dur})
        cursor += word_dur
    return result


def write_highlight_ass(
    path: Path,
    entries: list[dict],
    style: SubtitleStyle | None = None,
    highlight_color: str = "&H0000FFFF",  # yellow in ASS BGR
) -> None:
    """Write ASS subtitles with karaoke-style word-by-word highlight.

    Each entry: ``{"start_sec": float, "end_sec": float, "text": str}``.
    Words are highlighted progressively using ASS ``\\k`` (karaoke) tags.
    """
    s = style or SubtitleStyle()
    bold_flag = -1 if s.bold else 0

    header = "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
        "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
        "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding",
        # PrimaryColour = highlight (karaoke target), SecondaryColour = pre-highlight
        f"Style: Highlight,{s.font_name},{s.font_size},"
        f"{highlight_color},{s.primary_color},"
        f"{s.outline_color},{s.back_color},"
        f"{bold_flag},0,0,0,"
        f"100,100,0,0,"
        f"1,{s.outline_width:.1f},{s.shadow_distance:.1f},"
        f"{s.alignment},{s.margin_l},{s.margin_r},{s.margin_v},1",
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ])

    dialogues: list[str] = []
    for entry in entries:
        start = _format_ass_time(entry["start_sec"])
        end = _format_ass_time(entry["end_sec"])
        duration = entry["end_sec"] - entry["start_sec"]
        words = _estimate_word_timings(entry["text"], duration)

        if not words:
            text = _ass_escape(entry["text"])
            dialogues.append(f"Dialogue: 0,{start},{end},Highlight,,0,0,0,,{text}")
            continue

        # Build karaoke line: \kN per word (N in centiseconds)
        # Include space INSIDE each \k tag (after first word) so highlight covers it
        karaoke_parts = []
        for i, w in enumerate(words):
            dur_cs = max(1, int(round((w["end"] - w["start"]) * 100)))
            prefix = " " if i > 0 else ""
            karaoke_parts.append(f"{{\\k{dur_cs}}}{prefix}{_ass_escape(w['text'])}")
        karaoke_text = "".join(karaoke_parts)
        dialogues.append(
            f"Dialogue: 0,{start},{end},Highlight,,0,0,0,,{karaoke_text}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n" + "\n".join(dialogues) + "\n", encoding="utf-8")
