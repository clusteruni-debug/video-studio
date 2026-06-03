"""ASS subtitle engine — RENDERING-SPEC.md compliant.

Generates ASS subtitle files with safe-zone-aware positioning,
6 style presets, karaoke word highlight, and hook title support.

Spec reference: docs/RENDERING-SPEC.md §1–§3
"""

from __future__ import annotations

import math
import re
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

CAPTION_LAYOUT_STYLES: list[str] = [
    "Style: CenterShort,Pretendard,70,&H00FFFFFF,&H0000FFFF,&H00000000,&H90000000,1,0,0,0,100,100,0.2,0,1,4,1.2,5,72,190,0,1",
    "Style: TopHook,Pretendard,82,&H00FFFFFF,&H0000FFFF,&H00000000,&H90000000,1,0,0,0,100,100,0.2,0,1,4.5,1.4,8,72,190,148,1",
    "Style: LowerInfo,Pretendard,60,&H00FFFFFF,&H0000FFFF,&H00000000,&H86000000,1,0,0,0,100,100,0,0,1,3.5,1,2,72,190,690,1",
    "Style: RankBadge,Pretendard,108,&H0000E6FF,&H0000FFFF,&H001A1A1A,&H80000000,1,0,0,0,100,100,0,0,1,5,1.2,7,78,170,164,1",
    "Style: RankTitle,Pretendard,58,&H00FFFFFF,&H0000FFFF,&H00202020,&HAA000000,1,0,0,0,100,100,0,0,3,14,0,7,190,170,174,1",
    "Style: FactChip,Pretendard,44,&H00FFFFFF,&H0000FFFF,&H00202020,&HAA000000,1,0,0,0,100,100,0,0,3,12,0,1,74,170,430,1",
    "Style: StoryHook,NanumMyeongjo,66,&H00F0F0F0,&H0000FFFF,&H00101010,&H90000000,0,0,0,0,100,100,1.2,0,1,3.5,1,8,92,170,188,1",
    "Style: StoryLower,NanumMyeongjo,48,&H00F4F4F4,&H0000FFFF,&H00101010,&H88000000,0,0,0,0,100,100,0.8,0,1,3,0.8,2,94,170,690,1",
    "Style: ChapterKicker,Pretendard,38,&H0000D4FF,&H0000FFFF,&H00202020,&HAA000000,1,0,0,0,100,100,1,0,3,10,0,7,74,170,150,1",
    "Style: ChapterTitle,Pretendard,62,&H00FFFFFF,&H0000FFFF,&H00101010,&H9A000000,1,0,0,0,100,100,0.4,0,3,12,0,7,74,170,218,1",
    "Style: StepChip,Pretendard,42,&H00FFFFFF,&H0000FFFF,&H00202020,&HAA000000,1,0,0,0,100,100,0.4,0,3,10,0,7,74,170,155,1",
    "Style: RoutineStep,Pretendard,44,&H0000D4FF,&H0000FFFF,&H00202020,&HAA000000,1,0,0,0,100,100,1,0,3,10,0,7,78,210,152,1",
    "Style: RoutineHook,Pretendard,94,&H00FFFFFF,&H0000FFFF,&H00101010,&HA0000000,1,0,0,0,100,100,0.2,0,1,5,1.4,7,78,210,220,1",
    "Style: RoutineLower,Pretendard,70,&H00FFFFFF,&H0000FFFF,&H00101010,&H90000000,1,0,0,0,100,100,0,0,1,4.2,1.1,1,78,210,690,1",
    "Style: RoutineDetail,Pretendard,46,&H00EAEAEA,&H0000FFFF,&H00101010,&H7A000000,0,0,0,0,100,100,0,0,1,2.8,0.8,1,78,210,405,1",
    "Style: GrokHook,Pretendard,84,&H00FFFFFF,&H0000FFFF,&H00101010,&H8E000000,1,0,0,0,100,100,0.2,0,1,4.8,1.2,7,78,220,220,1",
    "Style: GrokLower,Pretendard,64,&H00FFFFFF,&H0000FFFF,&H00101010,&H86000000,1,0,0,0,100,100,0,0,1,4,1.1,1,78,220,690,1",
    "Style: GrokContinuity,Pretendard,68,&H00FFFFFF,&H0000FFFF,&H00141414,&HA8000000,1,0,0,0,100,100,0.2,0,3,14,0,7,78,220,220,1",
    "Style: GrokProof,Pretendard,46,&H00FFFFFF,&H0000FFFF,&H00202020,&HAA000000,1,0,0,0,100,100,0.2,0,3,12,0,1,78,220,430,1",
]

_CAPTION_PRESET_TO_STYLE = {
    "center-short": "CenterShort",
    "top-hook": "TopHook",
    "lower-info": "LowerInfo",
}

_CAPTION_STYLE_MAX_DURATION = {
    "TopHook": 1.35,
    "CenterShort": 1.6,
    "LowerInfo": 1.8,
}

_CAPTION_STYLE_EFFECT = {
    "TopHook": r"{\fad(55,130)\t(0,120,\fscx112\fscy112)\t(120,240,\fscx100\fscy100)}",
    "CenterShort": r"{\fad(65,130)\t(0,120,\fscx108\fscy108)\t(120,240,\fscx100\fscy100)}",
    "LowerInfo": r"{\fad(70,150)\t(0,150,\fscx104\fscy104)\t(150,260,\fscx100\fscy100)}",
}

_RANKING_LAYOUT_VARIANTS = {
    "rank-countdown",
    "rank-card",
    "rank-proof",
    "rank-finale",
    "chapter-card",
    "one-question-three-answers",
}
_STORY_LAYOUT_VARIANTS = {"character-continuity", "object-mystery", "pov-diary", "ambient-routine"}
_GROK_FIRST_LAYOUT_VARIANTS = {"grok-first-hook", "grok-first-continuity", "grok-first-proof"}
_CHAPTER_LAYOUT_VARIANTS = {"chapter-evidence", "documentary-explainer", "timeline-brief", "headline-evidence"}
_ROUTINE_LAYOUT_VARIANTS = {"routine-top-hook", "routine-lower-info"}
_CHIP_LAYOUT_VARIANTS = {
    "hands-proof",
    "screen-walkthrough",
    "fan-process",
    "trend-recap",
    "speaker-first",
    "tts-commentary",
    "observed-interview",
    "tts-summary-doc",
    "route-recap",
    "fan-atmosphere",
}

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
    hard_newline = "\uE000"
    text = text.replace("\\N", hard_newline)
    escaped = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    return escaped.replace(hard_newline, "\\N")


def _normalize_layout_variant(value: object) -> str:
    return str(value or "").strip().lower().replace("_", "-")


_PRODUCTION_META_NOTE_RE = re.compile(
    r"(caption|subtitle|safe\s*zone|danger\s*zone|layout|tts|production|"
    r"review|checklist|lower\s*third|right\s*edge|uncluttered|"
    r"cover|above|below|clean|y\s*>|피사체|가리지|검수|의도)",
    re.IGNORECASE,
)


def _viewer_facing_note(value: object) -> str:
    """Return only notes that are safe to burn into the viewer-facing video."""
    note = str(value or "").strip()
    if not note:
        return ""
    if _PRODUCTION_META_NOTE_RE.search(note):
        return ""
    return note


def _same_viewer_text(left: str, right: str) -> bool:
    normalized_left = re.sub(r"[\W_]+", "", left, flags=re.UNICODE).lower()
    normalized_right = re.sub(r"[\W_]+", "", right, flags=re.UNICODE).lower()
    return bool(normalized_left and normalized_left == normalized_right)


def _clip_end(start: float, end: float, duration: float) -> float:
    return min(end, start + duration) if end > start else end


def _rank_parts(text: str, fallback_rank: int) -> tuple[str, str]:
    match = re.match(r"\s*(?:#\s*)?([0-9]{1,2}|[①②③④⑤])[\.\)\:\s-]*(.*)", text)
    if not match:
        return str(fallback_rank), text.strip()
    symbol = match.group(1)
    circled = {"①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5"}
    return circled.get(symbol, symbol), (match.group(2) or text).strip()


def _variant_dialogue(
    dialogues: list[str],
    *,
    layer: int,
    start: float,
    end: float,
    style: str,
    text: str,
    effect: str,
    max_chars: int,
) -> None:
    if end <= start or not text.strip():
        return
    wrapped = _wrap_text(text.strip(), max_chars)
    escaped = _ass_escape(wrapped)
    dialogues.append(
        f"Dialogue: {layer},{_format_ass_time(start)},{_format_ass_time(end)},{style},,0,0,0,,{effect}{escaped}"
    )


def _generate_layout_variant(
    entry: dict,
    dialogues: list[str],
    *,
    idx: int,
    start: float,
    end: float,
    text: str,
    max_chars: int,
) -> bool:
    """Generate visibly distinct template layout overlays when variant metadata exists."""
    variant = _normalize_layout_variant(
        entry.get("layout_variant_key")
        or entry.get("layoutVariantKey")
        or entry.get("layout_variant")
        or entry.get("layoutVariant")
    )
    if not variant:
        return False

    label = str(entry.get("layout_variant_label") or entry.get("layoutVariantLabel") or "").strip()
    title = str(entry.get("title") or entry.get("sceneTitle") or "").strip()
    display_text = text.strip() or title or label
    title_text = title or display_text

    if variant in _ROUTINE_LAYOUT_VARIANTS:
        headline = display_text or title_text
        detail = title_text if title_text and title_text != headline else ""
        note = _viewer_facing_note(entry.get("layout_variant_note") or entry.get("layoutVariantNote"))
        step_label = f"{idx + 1:02d}"
        if variant == "routine-top-hook":
            _variant_dialogue(
                dialogues,
                layer=3,
                start=start,
                end=_clip_end(start, end, 1.1),
                style="RoutineStep",
                text=step_label,
                effect=r"{\fad(35,95)\t(0,90,\fscx112\fscy112)\t(90,210,\fscx100\fscy100)}",
                max_chars=5,
            )
            _variant_dialogue(
                dialogues,
                layer=2,
                start=start + 0.08,
                end=_clip_end(start + 0.08, end, 1.62),
                style="RoutineHook",
                text=headline,
                effect=r"{\fad(55,140)\t(0,130,\fscx110\fscy110)\t(130,260,\fscx100\fscy100)}",
                max_chars=10,
            )
            if detail:
                _variant_dialogue(
                    dialogues,
                    layer=1,
                    start=start + 1.28,
                    end=_clip_end(start + 1.28, end, 1.22),
                    style="RoutineDetail",
                    text=detail,
                    effect=r"{\fad(80,160)}",
                    max_chars=16,
                )
            return True

        lower_text = display_text or headline
        _variant_dialogue(
            dialogues,
            layer=3,
            start=start,
            end=_clip_end(start, end, 1.05),
            style="RoutineStep",
            text=step_label,
            effect=r"{\fad(35,95)\t(0,90,\fscx110\fscy110)\t(90,200,\fscx100\fscy100)}",
            max_chars=5,
        )
        _variant_dialogue(
            dialogues,
            layer=2,
            start=start + 0.12,
            end=_clip_end(start + 0.12, end, 1.8),
            style="RoutineLower",
            text=lower_text,
            effect=r"{\fad(70,150)\t(0,150,\fscx106\fscy106)\t(150,270,\fscx100\fscy100)}",
            max_chars=15,
        )
        if title and title != lower_text:
            _variant_dialogue(
                dialogues,
                layer=1,
                start=start + 1.34,
                end=_clip_end(start + 1.34, end, 1.16),
                style="RoutineDetail",
                text=title,
                effect=r"{\fad(70,140)}",
                max_chars=16,
            )
        if note:
            _variant_dialogue(
                dialogues,
                layer=0,
                start=start + 2.05,
                end=_clip_end(start + 2.05, end, 1.05),
                style="RoutineDetail",
                text=note,
                effect=r"{\fad(100,160)}",
                max_chars=20,
            )
        return True

    if variant in _RANKING_LAYOUT_VARIANTS:
        rank_source = display_text
        if not re.match(r"\s*(?:#\s*)?([0-9]{1,2}|[①②③④⑤])[\.\)\:\s-]+", rank_source) and title_text:
            rank_source = title_text
        rank_num, rank_title = _rank_parts(rank_source, idx + 1)
        rank_title = rank_title or title_text
        _variant_dialogue(
            dialogues,
            layer=3,
            start=start,
            end=_clip_end(start, end, 1.35),
            style="RankBadge",
            text=f"#{rank_num}",
            effect=r"{\fad(50,120)\t(0,140,\fscx112\fscy112)\t(140,260,\fscx100\fscy100)}",
            max_chars=8,
        )
        _variant_dialogue(
            dialogues,
            layer=2,
            start=start + 0.08,
            end=_clip_end(start + 0.08, end, 1.85),
            style="RankTitle",
            text=rank_title,
            effect=r"{\fad(70,150)\t(0,180,\fscx104\fscy104)\t(180,300,\fscx100\fscy100)}",
            max_chars=17,
        )
        _variant_dialogue(
            dialogues,
            layer=1,
            start=start + 1.25,
            end=_clip_end(start + 1.25, end, 1.6),
            style="FactChip",
            text="증거로 확인",
            effect=r"{\fad(80,160)}",
            max_chars=18,
        )
        return True

    if variant in _STORY_LAYOUT_VARIANTS:
        hook = title_text if variant == "character-continuity" else display_text
        _variant_dialogue(
            dialogues,
            layer=2,
            start=start,
            end=_clip_end(start, end, 1.55),
            style="StoryHook",
            text=hook,
            effect=r"{\fad(130,180)\t(0,220,\fscx103\fscy103)\t(220,360,\fscx100\fscy100)}",
            max_chars=15,
        )
        if variant != "character-continuity":
            return True
        _variant_dialogue(
            dialogues,
            layer=1,
            start=start + 1.45,
            end=_clip_end(start + 1.45, end, 1.45),
            style="StoryLower",
            text=display_text,
            effect=r"{\fad(120,180)}",
            max_chars=20,
        )
        return True

    if variant in _GROK_FIRST_LAYOUT_VARIANTS:
        beat_label = f"{idx + 1:02d}"
        hook = title_text or display_text
        lower = display_text if display_text and not _same_viewer_text(display_text, hook) else ""
        note = ""
        _variant_dialogue(
            dialogues,
            layer=4,
            start=start,
            end=_clip_end(start, end, 1.05),
            style="ChapterKicker",
            text=beat_label,
            effect=r"{\fad(35,95)\t(0,90,\fscx112\fscy112)\t(90,200,\fscx100\fscy100)}",
            max_chars=4,
        )
        if variant == "grok-first-hook":
            hook = display_text or title_text
            _variant_dialogue(
                dialogues,
                layer=3,
                start=start + 0.06,
                end=_clip_end(start + 0.06, end, 1.35),
                style="GrokHook",
                text=hook,
                effect=r"{\fad(35,115)\t(0,110,\fscx114\fscy114)\t(110,240,\fscx100\fscy100)}",
                max_chars=12,
            )
            if note:
                _variant_dialogue(
                    dialogues,
                    layer=1,
                    start=start + 1.55,
                    end=_clip_end(start + 1.55, end, 1.15),
                    style="GrokProof",
                    text=note,
                    effect=r"{\fad(80,140)}",
                    max_chars=20,
                )
            return True

        if variant == "grok-first-proof":
            _variant_dialogue(
                dialogues,
                layer=2,
                start=start,
                end=_clip_end(start, end, 1.25),
                style="GrokProof",
                text=hook,
                effect=r"{\fad(45,120)\t(0,110,\fscx108\fscy108)\t(110,230,\fscx100\fscy100)}",
                max_chars=18,
            )
            if lower:
                _variant_dialogue(
                    dialogues,
                    layer=1,
                    start=start + 0.9,
                    end=_clip_end(start + 0.9, end, 1.55),
                    style="GrokLower",
                    text=lower,
                    effect=r"{\fad(70,150)}",
                    max_chars=18,
                )
            if note:
                _variant_dialogue(
                    dialogues,
                    layer=0,
                    start=start + 2.05,
                    end=_clip_end(start + 2.05, end, 1.05),
                    style="GrokProof",
                    text=note,
                    effect=r"{\fad(90,150)}",
                    max_chars=20,
                )
            return True

        _variant_dialogue(
            dialogues,
            layer=2,
            start=start + 0.06,
            end=_clip_end(start + 0.06, end, 1.35),
            style="GrokContinuity",
            text=hook,
            effect=r"{\fad(35,120)\t(0,110,\fscx110\fscy110)\t(110,240,\fscx100\fscy100)}",
            max_chars=13,
        )
        if lower:
            _variant_dialogue(
                dialogues,
                layer=1,
                start=start + 0.75,
                end=_clip_end(start + 0.75, end, 1.7),
                style="GrokLower",
                text=lower,
                effect=r"{\fad(70,150)\t(0,150,\fscx104\fscy104)\t(150,270,\fscx100\fscy100)}",
                max_chars=18,
            )
        if note:
            _variant_dialogue(
                dialogues,
                layer=0,
                start=start + 1.65,
                end=_clip_end(start + 1.65, end, 1.25),
                style="GrokProof",
                text=note,
                effect=r"{\fad(90,160)}",
                max_chars=20,
            )
        return True

    if variant in _CHAPTER_LAYOUT_VARIANTS:
        kicker = "챕터"
        _variant_dialogue(
            dialogues,
            layer=3,
            start=start,
            end=_clip_end(start, end, 1.25),
            style="ChapterKicker",
            text=kicker,
            effect=r"{\fad(60,130)}",
            max_chars=18,
        )
        _variant_dialogue(
            dialogues,
            layer=2,
            start=start + 0.12,
            end=_clip_end(start + 0.12, end, 1.9),
            style="ChapterTitle",
            text=title_text,
            effect=r"{\fad(80,160)\t(0,170,\fscx102\fscy102)\t(170,280,\fscx100\fscy100)}",
            max_chars=17,
        )
        _variant_dialogue(
            dialogues,
            layer=1,
            start=start + 1.65,
            end=_clip_end(start + 1.65, end, 1.45),
            style="FactChip",
            text=display_text,
            effect=r"{\fad(90,160)}",
            max_chars=20,
        )
        return True

    if variant in _CHIP_LAYOUT_VARIANTS:
        chip = title_text
        _variant_dialogue(
            dialogues,
            layer=2,
            start=start,
            end=_clip_end(start, end, 1.35),
            style="StepChip",
            text=chip,
            effect=r"{\fad(60,130)\t(0,140,\fscx104\fscy104)\t(140,240,\fscx100\fscy100)}",
            max_chars=18,
        )
        _variant_dialogue(
            dialogues,
            layer=1,
            start=start + 0.95,
            end=_clip_end(start + 0.95, end, 1.65),
            style="FactChip",
            text=display_text,
            effect=r"{\fad(90,170)}",
            max_chars=20,
        )
        return True

    return False

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
    for layout_style in CAPTION_LAYOUT_STYLES:
        style_name = layout_style.split(",", 1)[0].replace("Style: ", "")
        if not any(line.startswith(f"Style: {style_name},") for line in style_lines):
            style_lines.append(layout_style)

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
        caption_preset = entry.get("caption_preset") or entry.get("captionPreset")
        if caption_preset == "none":
            continue
        if _generate_layout_variant(
            entry,
            dialogues,
            idx=idx,
            start=start,
            end=end,
            text=text,
            max_chars=max_chars,
        ):
            continue
        style_name = _CAPTION_PRESET_TO_STYLE.get(str(caption_preset or ""), "Main")
        chars = 20 if style_name == "LowerInfo" else max_chars
        max_duration = _CAPTION_STYLE_MAX_DURATION.get(style_name)
        if max_duration and end > start:
            end = min(end, start + max_duration)

        wrapped = _wrap_text(text, chars)
        escaped = _ass_escape(wrapped)
        effect = _CAPTION_STYLE_EFFECT.get(style_name, r"{\fad(200,0)}")
        dialogues.append(
            f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(end)},{style_name},,0,0,0,,{effect}{escaped}"
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
