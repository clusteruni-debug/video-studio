# Video Studio — Rendering Improvement Task Board

**Status**: ✅ COMPLETED — inline Status Tracker (bottom of doc) marks all 3 tasks DONE. Shipped in commit `2d43412 feat: ASS subtitle engine + karaoke alignment + BGM sidechain ducking`. Verified artifacts: `worker/render/align.py`, `worker/render/bgm.py`, `worker/bridge/server.py` `/api/align-tts` route, `bgmEnabled` in UI.

> Claude Code handoff document. Each task follows the 4-field structure: Background / Goal / Constraints / Deliverables.
> **Before execution, always read `docs/RENDERING-SPEC.md`.**

---

## TASK-1: ASS Subtitle Generator + Safe Zone Enforcement

**Background**
Current subtitles use SRT-based FFmpeg `subtitles=` filter with no position or style control.
YouTube Shorts UI covers the bottom 20% and right 12%, causing subtitles to be clipped.

**Goal**
- Create new `worker/render/subtitle.py`
- Implement `generate_ass_subtitle()` function (signature: RENDERING-SPEC.md §3.3)
- Define 6 preset styles (ASS Style lines: copy exactly from RENDERING-SPEC.md §2.2)
- Modify `worker/render/compose.py` to use ASS files instead of SRT
- Replace FFmpeg `subtitles=` → `ass=` filter
- Apply MarginR=130, Alignment=5 (center) to all main subtitles

**Constraints**
- Use exact pixel values from RENDERING-SPEC.md §1.2
- Font fallback: Pretendard → Malgun Gothic → Arial
- Line breaks: Korean 16 chars/line, max 2 lines
- Hook title: Alignment=8, MarginV=120
- Do not delete existing SRT code path — branch to ASS-first with SRT fallback

**Deliverables**
- `worker/render/subtitle.py` (function + preset dictionary)
- `worker/render/compose.py` modified (ass= filter usage)
- Verification: `python -m worker.render.subtitle --test` generates sample ASS, content verified

---

## TASK-2: Whisper Word Timing + Karaoke Highlight

**Background**
Once TASK-1 enables ASS subtitles, the next step is per-word highlighting.
Currently subtitle timing is only at scene level, making karaoke effects impossible.

**Goal**
- `pip install faster-whisper` (add to requirements.txt)
- Create new `worker/render/align.py`
- Implement `align_tts(wav_path) -> list[dict]`: extract word_timestamps via faster-whisper
- Bridge endpoint: `POST /api/align-tts` (input: WAV path, output: word array)
- When `generate_ass_subtitle()` receives words parameter, auto-apply karaoke highlight
- highlight_mode="color_swap" default: only current word uses Highlight style
- highlight_mode="karaoke_fill" option: use ASS `\kf` tags

**Constraints**
- faster-whisper model: `base` (speed priority, considering no-GPU environments)
- Korean word segmentation may be inaccurate → fallback to syllable-level
- Round when converting Whisper start/end to ASS timecodes (centiseconds)
- Follow ASS tag format from RENDERING-SPEC.md §3.2 exactly

**Deliverables**
- `worker/render/align.py`
- `worker/bridge/server.py` with `/api/align-tts` route added
- `worker/render/subtitle.py` modified (words parameter handling)
- requirements.txt with `faster-whisper>=1.0` added
- Verification: sample WAV → align → ASS generation → FFmpeg burn-in → word highlight sync confirmed

---

## TASK-3: BGM Auto-Matching + Audio Mixing

**Background**
Local BGM library (assets/bgm/) has 16 tracks but no auto-selection,
and no logic for mixing narration with BGM.

**Goal**
- Create new `worker/render/bgm.py`
- Implement `select_bgm(emotion: str) -> str`: emotion → mood mapping, random selection from folder
- Implement `mix_audio(narration_path, bgm_path, output_path)`: FFmpeg sidechain ducking
- `worker/render/compose.py` auto-selects BGM + applies mixing during render
- Add BGM on/off toggle to UI (Sidebar.tsx settings section)

**Constraints**
- BGM mapping table: use RENDERING-SPEC.md §4.1 exactly
- Narration segments: BGM -18dB
- Non-narration segments: BGM -8dB
- Fade-in 0.5s, fade-out 1.0s
- FFmpeg command: use sidechain ducking from RENDERING-SPEC.md §4.3
- If BGM shorter than video: loop (-stream_loop -1)
- If BGM longer than video: fade-out then cut

**Deliverables**
- `worker/render/bgm.py`
- `worker/render/compose.py` modified
- `app/ui/src/components/Sidebar.tsx` modified (BGM toggle)
- `app/ui/src/context/StudioContext.tsx` modified (bgmEnabled state)
- Verification: render output confirms BGM volume clearly decreases during narration segments (auditory check)

---

## Dependency Graph

```
TASK-1 (ASS subtitle generator)
    ↓
TASK-2 (Whisper alignment + karaoke)
    ↓ (TASK-2 depends on TASK-1's generate_ass_subtitle)
TASK-3 (BGM matching + mixing)
    ↑ (independent of TASK-1/2, can run in parallel with TASK-2)
```

**Recommended execution order**: TASK-1 → TASK-2 + TASK-3 (parallel)

---

## Status Tracker

| Task | Status | Notes |
|------|--------|-------|
| TASK-1: ASS Subtitles | DONE | subtitles.py rewritten, ass= filter applied |
| TASK-2: Karaoke Highlight | DONE | align.py + /api/align-tts + faster-whisper |
| TASK-3: BGM Auto-Match | DONE | bgm.py + sidechain ducking + UI toggle |
