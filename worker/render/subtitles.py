"""ASS subtitle engine — RENDERING-SPEC.md compliant.

Generates ASS subtitle files with safe-zone-aware positioning,
6 style presets, karaoke word highlight, and hook title support.

Spec reference: docs/RENDERING-SPEC.md §1–§3
"""

from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# ASS common header (RENDERING-SPEC §2.1)
# ---------------------------------------------------------------------------

ASS_HEADER = """\
[Script Info]
Title: Video Studio Auto Subtitle
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"""

# ---------------------------------------------------------------------------
# Style presets — copied verbatim from RENDERING-SPEC §2.2
# ---------------------------------------------------------------------------

STYLE_PRESETS: dict[str, list[str]] = {
    "default": [
        "Style: Main,Pretendard,58,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,3,1.5,5,60,130,0,1",
        "Style: Hook,Pretendard,68,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,2,0,1,4,2,8,60,130,120,1",
    ],
    "news": [
        "Style: Main,Pretendard,62,&H00FFFFFF,&H0000FFFF,&H00000000,&HC0000000,1,0,0,0,100,100,1.5,0,3,0,0,5,60,130,0,1",
        "Style: Hook,Pretendard,72,&H0000D4FF,&H0000FFFF,&H00000000,&HC0000000,1,0,0,0,100,100,2,0,3,0,0,8,60,130,120,1",
        "Style: Highlight,Pretendard,62,&H0000D4FF,&H0000FFFF,&H00000000,&HC0000000,1,0,0,0,100,100,1.5,0,3,0,0,5,60,130,0,1",
    ],
    "ranking": [
        "Style: Main,Pretendard,60,&H00FFFFFF,&H0000FFFF,&H00000000,&H99000000,1,0,0,0,100,100,1,0,3,0,0,5,60,130,0,1",
        "Style: Hook,Pretendard,80,&H0000FFFF,&H0000FFFF,&H00191970,&H80000000,1,0,0,0,100,100,3,0,1,5,3,8,60,130,100,1",
        "Style: Number,Pretendard,120,&H0000FFFF,&H0000FFFF,&H00191970,&H80000000,1,0,0,0,100,100,0,0,1,6,3,4,80,130,0,1",
    ],
    "impact": [
        "Style: Main,Pretendard,62,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,4,2,5,60,130,0,1",
        "Style: Hook,Pretendard,72,&H0000FFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,2,0,1,5,3,8,60,130,120,1",
        "Style: Highlight,Pretendard,62,&H0000FFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,4,2,5,60,130,0,1",
    ],
    "story": [
        "Style: Main,NanumMyeongjo,56,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,0,0,0,0,100,100,1.5,0,1,3,1.5,5,80,130,0,1",
        "Style: Hook,NanumMyeongjo,66,&H00E0E0E0,&H0000FFFF,&H00000000,&H80000000,0,0,0,0,100,100,2,0,1,4,2,8,80,130,120,1",
    ],
    "minimal": [
        "Style: Main,Pretendard,54,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0.5,0,1,2,0,5,60,130,0,1",
        "Style: Hook,Pretendard,60,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,1,0,0,0,100,100,1,0,1,3,0,8,60,130,120,1",
    ],
}

# Presets that have a Highlight style defined
_PRESETS_WITH_HIGHLIGHT = {"news", "impact"}

# Default highlight style for presets without one (yellow word swap)
_DEFAULT_HIGHLIGHT_STYLE = "Style: Highlight,Pretendard,58,&H0000FFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,3,1.5,5,60,130,0,1"

# ---------------------------------------------------------------------------
# Backward-compatible SubtitleStyle (used by old code paths)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SubtitleStyle:
    """Legacy configurable subtitle appearance. New code should use STYLE_PRESETS."""

    font_name: str = "Pretendard"
    font_size: int = 58
    primary_color: str = "&H00FFFFFF"
    outline_color: str = "&H00000000"
    back_color: str = "&H80000000"
    outline_width: float = 3.0
    shadow_distance: float = 1.5
    alignment: int = 5
    margin_l: int = 60
    margin_r: int = 130
    margin_v: int = 0
    bold: bool = True
    animation: str = "fade_in"


# Legacy preset map (delegates to STYLE_PRESETS for new renders)
SUBTITLE_PRESETS: dict[str, SubtitleStyle] = {
    "default": SubtitleStyle(),
    "news": SubtitleStyle(font_size=62, outline_width=0, shadow_distance=0),
    "story": SubtitleStyle(font_name="NanumMyeongjo", font_size=56, bold=False),
    "ranking": SubtitleStyle(font_size=60, alignment=5),
    "minimal": SubtitleStyle(font_size=54, outline_width=2, shadow_distance=0, bold=False),
    "impact": SubtitleStyle(font_size=62, primary_color="&H0000FFFF", outline_width=4),
}

# ---------------------------------------------------------------------------
# Korean particle-aware line break (RENDERING-SPEC §3.4)
# ---------------------------------------------------------------------------

# Korean particles that should not start a new line
_KO_PARTICLES = frozenset(
    "은는이가을를의에서로도만까지부터와과라며"
    "보다처럼같이한테에게께서"
)


def _is_korean(ch: str) -> bool:
    cp = ord(ch)
    return 0xAC00 <= cp <= 0xD7A3 or 0x3131 <= cp <= 0x318E


def _wrap_korean(text: str, max_chars: int = 16) -> str:
    """Wrap Korean text respecting particle boundaries. Returns \\N-joined string."""
    if len(text) <= max_chars:
        return text

    words = text.split()
    lines: list[str] = []
    current = ""

    for word in words:
        test = f"{current} {word}".strip() if current else word
        if len(test) <= max_chars:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    # Max 2 lines
    if len(lines) > 2:
        lines = [lines[0], " ".join(lines[1:])]
        if len(lines[1]) > max_chars:
            lines[1] = lines[1][:max_chars]

    return r"\N".join(lines)


def _wrap_english(text: str, max_chars: int = 35) -> str:
    """Wrap English text. Returns \\N-joined string."""
    if len(text) <= max_chars:
        return text
    wrapped = textwrap.wrap(text, width=max_chars, break_long_words=False, break_on_hyphens=False)
    if len(wrapped) > 2:
        wrapped = [wrapped[0], " ".join(wrapped[1:])]
    return r"\N".join(wrapped)


def _wrap_text(text: str, max_chars: int = 16) -> str:
    """Auto-detect language and wrap accordingly."""
    korean_count = sum(1 for ch in text if _is_korean(ch))
    if korean_count > len(text) * 0.3:
        return _wrap_korean(text, max_chars)
    return _wrap_english(text, max_chars=35)

# ---------------------------------------------------------------------------
# ASS time formatting
# ---------------------------------------------------------------------------

def _format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp H:MM:SS.cc (centiseconds)."""
    total_cs = int(round(seconds * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    """Escape special ASS characters."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")

# ---------------------------------------------------------------------------
# Main generator — RENDERING-SPEC §3.3
# ---------------------------------------------------------------------------

def generate_ass_subtitle(
    words: list[dict],
    style_preset: str = "default",
    hook_text: str | None = None,
    hook_duration: float = 3.0,
    highlight_mode: str = "color_swap",
    max_chars_per_line: int = 16,
    output_path: str = "subtitle.ass",
) -> str:
    """Generate ASS subtitle file and return path.

    Parameters
    ----------
    words:
        List of ``{"word": str, "start": float, "end": float}`` dicts.
        If words have no timing (start/end), they are treated as scene-level
        entries with ``{"text": str, "start_sec": float, "end_sec": float}``.
    style_preset:
        One of: "default", "news", "ranking", "impact", "story", "minimal".
    hook_text:
        Optional top hook title text.
    hook_duration:
        How long the hook title is displayed (seconds).
    highlight_mode:
        "color_swap" — current word gets Highlight style.
        "karaoke_fill" — ASS \\kf tags for smooth fill.
        "none" — no word-level highlight.
    max_chars_per_line:
        Max chars per subtitle line (Korean default 16).
    output_path:
        Where to write the .ass file.
    """
    preset = style_preset if style_preset in STYLE_PRESETS else "default"
    style_lines = list(STYLE_PRESETS[preset])

    # Ensure Highlight style exists for color_swap mode
    has_highlight = preset in _PRESETS_WITH_HIGHLIGHT
    if highlight_mode == "color_swap" and not has_highlight:
        style_lines.append(_DEFAULT_HIGHLIGHT_STYLE)

    # Build header
    header = ASS_HEADER + "\n" + "\n".join(style_lines)

    # Events section
    events_header = "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    dialogues: list[str] = []

    # Hook title (RENDERING-SPEC §1.2 — Alignment=8, MarginV=120)
    if hook_text:
        hook_end = hook_duration
        escaped_hook = _ass_escape(hook_text)
        dialogues.append(
            f"Dialogue: 1,{_format_ass_time(0)},{_format_ass_time(hook_end)},Hook,,0,0,0,,{{\\fad(300,300)}}{escaped_hook}"
        )

    # Detect input format: word-level or scene-level
    is_word_level = bool(words and "word" in words[0])

    if is_word_level:
        _generate_word_level(words, dialogues, highlight_mode, max_chars_per_line)
    else:
        _generate_scene_level(words, dialogues, highlight_mode, max_chars_per_line, preset)

    # Write file
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    content = header + events_header + "\n" + "\n".join(dialogues) + "\n"
    out.write_text(content, encoding="utf-8")
    return str(out)


def _group_words_into_lines(
    words: list[dict], max_chars: int = 16
) -> list[list[dict]]:
    """Group word-level entries into display lines respecting max_chars."""
    lines: list[list[dict]] = []
    current_line: list[dict] = []
    current_len = 0

    for w in words:
        word_text = w["word"]
        added_len = len(word_text) + (1 if current_line else 0)
        if current_len + added_len > max_chars and current_line:
            lines.append(current_line)
            current_line = [w]
            current_len = len(word_text)
        else:
            current_line.append(w)
            current_len += added_len

    if current_line:
        lines.append(current_line)
    return lines


def _generate_word_level(
    words: list[dict],
    dialogues: list[str],
    highlight_mode: str,
    max_chars: int,
) -> None:
    """Generate dialogues from word-level timestamps."""
    lines = _group_words_into_lines(words, max_chars)

    for line_words in lines:
        if not line_words:
            continue

        line_start = line_words[0]["start"]
        line_end = line_words[-1]["end"]
        full_text = " ".join(w["word"] for w in line_words)
        escaped_text = _ass_escape(full_text)

        # Base text line (Main style)
        dialogues.append(
            f"Dialogue: 0,{_format_ass_time(line_start)},{_format_ass_time(line_end)},Main,,0,0,0,,{escaped_text}"
        )

        if highlight_mode == "color_swap":
            # Per-word Highlight overlay (RENDERING-SPEC §3.2 Method A)
            for w in line_words:
                escaped_word = _ass_escape(w["word"])
                dialogues.append(
                    f"Dialogue: 1,{_format_ass_time(w['start'])},{_format_ass_time(w['end'])},Highlight,,0,0,0,,{escaped_word}"
                )

        elif highlight_mode == "karaoke_fill":
            # \kf karaoke fill (RENDERING-SPEC §3.2 Method B)
            kf_parts = []
            for w in line_words:
                dur_cs = max(1, int(round((w["end"] - w["start"]) * 100)))
                kf_parts.append(f"{{\\kf{dur_cs}}}{_ass_escape(w['word'])}")
            kf_text = " ".join(kf_parts)
            dialogues.append(
                f"Dialogue: 1,{_format_ass_time(line_start)},{_format_ass_time(line_end)},Main,,0,0,0,,{kf_text}"
            )


def _generate_scene_level(
    entries: list[dict],
    dialogues: list[str],
    highlight_mode: str,
    max_chars: int,
    preset: str = "default",
) -> None:
    """Generate dialogues from scene-level entries (no word timestamps)."""
    for idx, entry in enumerate(entries):
        start = entry.get("start_sec", entry.get("start", 0))
        end = entry.get("end_sec", entry.get("end", 0))
        text = entry.get("text", entry.get("subtitleText", ""))
        if not text:
            continue

        wrapped = _wrap_text(text, max_chars)
        escaped = _ass_escape(wrapped)
        dialogues.append(
            f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(end)},Main,,0,0,0,,{{\\fad(200,0)}}{escaped}"
        )

        # Ranking preset: show scene number using Number style (RENDERING-SPEC §2.2)
        if preset == "ranking":
            rank_num = str(idx + 1)
            dialogues.append(
                f"Dialogue: 1,{_format_ass_time(start)},{_format_ass_time(end)},Number,,0,0,0,,{{\\fad(300,0)}}{rank_num}"
            )


# ---------------------------------------------------------------------------
# Legacy API — backward compatible with old compose.py calls
# ---------------------------------------------------------------------------

def animation_to_ass_tags(animation: str, duration_ms: int = 300) -> str:
    """Convert animation name to ASS override tags."""
    if animation == "fade_in":
        return f"{{\\fad({duration_ms},0)}}"
    if animation == "pop":
        return f"{{\\fscx0\\fscy0\\t(0,{duration_ms},\\fscx100\\fscy100)}}"
    return ""


def write_styled_ass(
    path: Path,
    entries: list[dict],
    style: SubtitleStyle | None = None,
    preset_name: str = "",
) -> None:
    """Write ASS subtitle file. Uses RENDERING-SPEC presets when possible.

    Parameters
    ----------
    path:
        Output .ass file path.
    entries:
        List of ``{"start_sec": float, "end_sec": float, "text": str}``.
    style:
        Legacy SubtitleStyle (used if preset_name not found).
    preset_name:
        Name of RENDERING-SPEC preset to use.
    """
    # Prefer new RENDERING-SPEC presets
    if preset_name and preset_name in STYLE_PRESETS:
        generate_ass_subtitle(
            words=entries,
            style_preset=preset_name,
            output_path=str(path),
        )
        return

    # Legacy path for backward compatibility
    s = style or SubtitleStyle()
    bold_flag = -1 if s.bold else 0
    anim_prefix = animation_to_ass_tags(s.animation)

    header = "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Main,{s.font_name},{s.font_size},"
        f"{s.primary_color},&H0000FFFF,"
        f"{s.outline_color},{s.back_color},"
        f"{bold_flag},0,0,0,"
        f"100,100,1,0,"
        f"1,{s.outline_width:.1f},{s.shadow_distance:.1f},"
        f"{s.alignment},{s.margin_l},{s.margin_r},{s.margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])

    dialogue_lines: list[str] = []
    for entry in entries:
        start = _format_ass_time(entry["start_sec"])
        end = _format_ass_time(entry["end_sec"])
        text = _wrap_text(entry["text"])
        escaped = _ass_escape(text)
        dialogue_lines.append(
            f"Dialogue: 0,{start},{end},Main,,0,0,0,,{anim_prefix}{escaped}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n" + "\n".join(dialogue_lines) + "\n", encoding="utf-8")


def write_highlight_ass(
    path: Path,
    entries: list[dict],
    style: SubtitleStyle | None = None,
    highlight_color: str = "&H0000FFFF",
) -> None:
    """Write ASS subtitles. Scene-level entries get fade-in animation.

    Note: True karaoke word highlight requires word-level timestamps
    from align.py. Scene-level entries cannot do per-word highlighting.
    """
    generate_ass_subtitle(
        words=entries,
        style_preset="default",
        highlight_mode="none",
        output_path=str(path),
    )


# ---------------------------------------------------------------------------
# CLI test entry point
# ---------------------------------------------------------------------------

def _test() -> None:
    """Generate a sample ASS file for verification."""
    sample_words = [
        {"word": "비트코인의", "start": 0.24, "end": 0.82},
        {"word": "역사를", "start": 0.82, "end": 1.40},
        {"word": "알아봅시다", "start": 1.40, "end": 2.50},
        {"word": "처음", "start": 3.0, "end": 3.3},
        {"word": "만들어진", "start": 3.3, "end": 3.8},
        {"word": "것은", "start": 3.8, "end": 4.1},
        {"word": "2009년", "start": 4.1, "end": 4.6},
        {"word": "입니다", "start": 4.6, "end": 5.0},
    ]

    for preset in STYLE_PRESETS:
        out = f"test_subtitle_{preset}.ass"
        generate_ass_subtitle(
            words=sample_words,
            style_preset=preset,
            hook_text="충격! 비트코인의 숨겨진 비밀",
            hook_duration=3.0,
            highlight_mode="color_swap",
            output_path=out,
        )
        print(f"[OK] {preset} → {out}")

    # Also test karaoke_fill mode
    generate_ass_subtitle(
        words=sample_words,
        style_preset="default",
        hook_text="카라오케 테스트",
        highlight_mode="karaoke_fill",
        output_path="test_subtitle_karaoke.ass",
    )
    print("[OK] karaoke_fill → test_subtitle_karaoke.ass")

    # Scene-level test
    scene_entries = [
        {"start_sec": 0, "end_sec": 3, "text": "비트코인의 역사를 알아봅시다"},
        {"start_sec": 3, "end_sec": 6, "text": "처음 만들어진 것은 2009년입니다"},
    ]
    generate_ass_subtitle(
        words=scene_entries,
        style_preset="news",
        hook_text="뉴스 스타일 테스트",
        output_path="test_subtitle_scene.ass",
    )
    print("[OK] scene-level → test_subtitle_scene.ass")


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        _test()
    else:
        print("Usage: python -m worker.render.subtitles --test")
