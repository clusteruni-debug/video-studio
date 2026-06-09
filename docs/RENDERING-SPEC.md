# Video Studio App — RENDERING-SPEC.md

> This document is a **binding spec** for FFmpeg composition, subtitles, layout, and BGM.
> Not abstract descriptions — pixel values, ASS code, and FFmpeg commands are the standard.
> Claude Code MUST reference this document when modifying render-related code.

---

## 1. Canvas & Safe Zones

Output resolution: **1080 × 1920** (9:16), 30fps, H.264, AAC

### 1.1 Safe Zone Specs (px, 1080×1920)

| Zone | X Range | Y Range | Purpose |
|------|---------|---------|---------|
| Content safe zone | 60–950 | 100–1440 | All important content placed here |
| Danger: bottom | 0–1080 | 1536–1920 (bottom 20%) | YouTube channel name, title, ad UI |
| Danger: right | 950–1080 (right 12%) | 0–1536 | Like, comment, share buttons |
| Danger: top | 0–1080 | 0–100 | Status bar, time display |

### 1.2 Subtitle Placement Coordinates (ASS Alignment + MarginV)

| Subtitle Layer | ASS Alignment | MarginL | MarginR | MarginV | Approx Y Position |
|---------------|---------------|---------|---------|---------|-------------------|
| A: Hook title | 8 (top center) | 60 | 130 | 120 | y≈120–200 |
| B: Main narration | 5 (center) | 60 | 130 | 0 | y≈900–1100 |
| C: Supplementary info | 2 (bottom center) | 60 | 130 | 500 | y≈1300–1420 |

**Absolute prohibition**: Never place subtitles at y>1536 or x>950.

---

## 2. Subtitle Style Presets

### 2.1 ASS Style Definition (Common Header)

All subtitle files start with this header:

```ass
[Script Info]
Title: Video Studio Auto Subtitle
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
```

### 2.2 Style Lines per Preset

**default (standard SRT replacement)**
```
Style: Main,Pretendard,58,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,3,1.5,5,60,130,0,1
Style: Hook,Pretendard,68,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,2,0,1,4,2,8,60,130,120,1
```

**news (news/commentary)**
```
Style: Main,Pretendard,62,&H00FFFFFF,&H0000FFFF,&H00000000,&HC0000000,1,0,0,0,100,100,1.5,0,3,0,0,5,60,130,0,1
Style: Hook,Pretendard,72,&H0000D4FF,&H0000FFFF,&H00000000,&HC0000000,1,0,0,0,100,100,2,0,3,0,0,8,60,130,120,1
Style: Highlight,Pretendard,62,&H0000D4FF,&H0000FFFF,&H00000000,&HC0000000,1,0,0,0,100,100,1.5,0,3,0,0,5,60,130,0,1
```

**ranking (ranking/quiz)**
```
Style: Main,Pretendard,60,&H00FFFFFF,&H0000FFFF,&H00000000,&H99000000,1,0,0,0,100,100,1,0,3,0,0,5,60,130,0,1
Style: Hook,Pretendard,80,&H0000FFFF,&H0000FFFF,&H00191970,&H80000000,1,0,0,0,100,100,3,0,1,5,3,8,60,130,100,1
Style: Number,Pretendard,120,&H0000FFFF,&H0000FFFF,&H00191970,&H80000000,1,0,0,0,100,100,0,0,1,6,3,4,80,130,0,1
```

**impact (yellow highlight)**
```
Style: Main,Pretendard,62,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,4,2,5,60,130,0,1
Style: Hook,Pretendard,72,&H0000FFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,2,0,1,5,3,8,60,130,120,1
Style: Highlight,Pretendard,62,&H0000FFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,4,2,5,60,130,0,1
```

**story (narrative)**
```
Style: Main,NanumMyeongjo,56,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,0,0,0,0,100,100,1.5,0,1,3,1.5,5,80,130,0,1
Style: Hook,NanumMyeongjo,66,&H00E0E0E0,&H0000FFFF,&H00000000,&H80000000,0,0,0,0,100,100,2,0,1,4,2,8,80,130,120,1
```

**minimal**
```
Style: Main,Pretendard,54,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0.5,0,1,2,0,5,60,130,0,1
Style: Hook,Pretendard,60,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,1,0,0,0,100,100,1,0,1,3,0,8,60,130,120,1
```

**production caption layout overlays**
These are the scene-level layout presets used by the dashboard source switcher
and render manifest. They intentionally differ from the legacy `Main`/`Hook`
styles because the current quality bar requires larger, faster, safer captions
that read on mobile without covering the subject or the YouTube Shorts UI.
The current production default is restrained: captions should support the shot,
not become the shot. Use the larger impact/ranking presets only for templates
that explicitly require a title-card or ranking rhythm.

```
Style: CenterShort,Pretendard,64,&H00FFFFFF,&H0000FFFF,&H00000000,&H90000000,1,0,0,0,100,100,0.2,0,1,3.5,1,5,72,170,0,1
Style: TopHook,Pretendard,78,&H00FFFFFF,&H0000FFFF,&H00000000,&H92000000,1,0,0,0,100,100,0.2,0,1,4.2,1.1,8,72,170,150,1
Style: LowerInfo,Pretendard,58,&H00FFFFFF,&H0000FFFF,&H00000000,&H88000000,1,0,0,0,100,100,0,0,1,3.4,0.9,2,72,170,540,1
Style: RankBadge,Pretendard,108,&H0000E6FF,&H0000FFFF,&H001A1A1A,&H80000000,1,0,0,0,100,100,0,0,1,5,1.2,7,78,170,164,1
Style: RankTitle,Pretendard,58,&H00FFFFFF,&H0000FFFF,&H00202020,&HAA000000,1,0,0,0,100,100,0,0,3,14,0,7,190,170,174,1
Style: FactChip,Pretendard,44,&H00FFFFFF,&H0000FFFF,&H00202020,&HAA000000,1,0,0,0,100,100,0,0,3,12,0,1,74,170,430,1
Style: StoryHook,NanumMyeongjo,66,&H00F0F0F0,&H0000FFFF,&H00101010,&H90000000,0,0,0,0,100,100,1.2,0,1,3.5,1,8,92,170,188,1
Style: StoryLower,NanumMyeongjo,48,&H00F4F4F4,&H0000FFFF,&H00101010,&H88000000,0,0,0,0,100,100,0.8,0,1,3,0.8,2,94,170,690,1
Style: ChapterKicker,Pretendard,38,&H0000D4FF,&H0000FFFF,&H00202020,&HAA000000,1,0,0,0,100,100,1,0,3,10,0,7,74,170,150,1
Style: ChapterTitle,Pretendard,62,&H00FFFFFF,&H0000FFFF,&H00101010,&H9A000000,1,0,0,0,100,100,0.4,0,3,12,0,7,74,170,218,1
Style: StepChip,Pretendard,42,&H00FFFFFF,&H0000FFFF,&H00202020,&HAA000000,1,0,0,0,100,100,0.4,0,3,10,0,7,74,170,155,1
Style: RoutineStep,Pretendard,44,&H0000D4FF,&H0000FFFF,&H00202020,&HAA000000,1,0,0,0,100,100,1,0,3,10,0,7,78,210,152,1
Style: RoutineHook,Pretendard,84,&H00FFFFFF,&H0000FFFF,&H00101010,&H98000000,1,0,0,0,100,100,0.2,0,1,4.4,1.1,7,78,210,220,1
Style: RoutineLower,Pretendard,62,&H00FFFFFF,&H0000FFFF,&H00101010,&H88000000,1,0,0,0,100,100,0,0,1,3.8,0.9,1,78,210,690,1
Style: RoutineDetail,Pretendard,46,&H00EAEAEA,&H0000FFFF,&H00101010,&H7A000000,0,0,0,0,100,100,0,0,1,2.8,0.8,1,78,210,405,1
Style: GrokHook,Pretendard,84,&H00FFFFFF,&H0000FFFF,&H00101010,&H8E000000,1,0,0,0,100,100,0.2,0,1,4.8,1.2,7,78,220,220,1
Style: GrokLower,Pretendard,64,&H00FFFFFF,&H0000FFFF,&H00101010,&H86000000,1,0,0,0,100,100,0,0,1,4,1.1,1,78,220,690,1
Style: GrokContinuity,Pretendard,68,&H00FFFFFF,&H0000FFFF,&H00141414,&HA8000000,1,0,0,0,100,100,0.2,0,3,14,0,7,78,220,220,1
Style: GrokProof,Pretendard,46,&H00FFFFFF,&H0000FFFF,&H00202020,&HAA000000,1,0,0,0,100,100,0.2,0,3,12,0,1,78,220,430,1
```

Maximum display durations:
- `top-hook`: 1.35s
- `center-short`: 1.6s
- `lower-info`: 1.8s

Routine layouts must stay compact. `RoutineHook` and `RoutineLower` are not
hero-title replacements; they exist to label a physical action without covering
hands, phone screens, or object state changes. Increasing these sizes requires a
phone-sized contact-sheet review and a test update.

Template layout variants:
- `rank-countdown`, `one-question-three-answers`: render a left top rank badge,
  boxed rank title, and lower proof chip. Use for ranking/list Shorts where the
  viewer must see the list structure immediately.
- `character-continuity`, `object-mystery`, `pov-diary`, `ambient-routine`:
  render cinematic story hooks and restrained lower story captions. Use for
  persona/story or vlog-like edits where captions should not flatten the shot.
- `grok-first-hook`, `grok-first-continuity`, `grok-first-proof`: render a
  Grok/app-web MP4 as the hero footage with a short top hook or chip plus one
  restrained lower beat. Use when the scene source is a reviewed Grok/Wan/LTX/
  Hunyuan MP4; never burn production notes, prompt text, or model labels into
  viewer-facing captions.
- `chapter-evidence`, `documentary-explainer`, `timeline-brief`,
  `headline-evidence`: render chapter kicker/title plus a lower evidence chip.
  Use for long-form or explainer edits instead of Shorts-style center captions.
- `hands-proof`, `screen-walkthrough`, `route-recap`, `fan-atmosphere`, and
  related chip variants: render a compact top-left chip plus lower fact note.

For Korean template families that commonly look templated when repeated
(`ranking_list`, `tutorial_steps`, `persona_story`, `kculture_fandom`,
`longform_deep_dive`, `interview_documentary`, `live_recap`), missing
`layoutVariantKey` is a failed quality gate, not merely a warning.

### 2.3 Font Fallback Order

1. Pretendard (verify system installation)
2. Malgun Gothic (Windows default)
3. NanumGothic
4. Arial (final fallback)

For English-only channels: Inter → Arial

---

## 3. Karaoke Word Highlight

### 3.1 Pipeline

```
Edge TTS → WAV file
    ↓
faster-whisper (word_timestamps=True)
    ↓
[{word: "비트코인의", start: 0.24, end: 0.82}, ...]
    ↓
ASS karaoke generator
    ↓
subtitle.ass
    ↓
FFmpeg burn-in
```

### 3.2 ASS Karaoke Tag Usage

**Method A: Per-word color swap (recommended, compatible with all presets)**

In each Dialogue line, only the currently spoken word uses the Highlight style:

```ass
Dialogue: 0,0:00:01.00,0:00:03.50,Main,,0,0,0,,비트코인의 역사를 알아봅시다
Dialogue: 0,0:00:01.00,0:00:01.80,Highlight,,0,0,0,,{\pos(540,960)}비트코인의
Dialogue: 0,0:00:01.80,0:00:02.40,Highlight,,0,0,0,,{\pos(540,960)}역사를
Dialogue: 0,0:00:02.40,0:00:03.50,Highlight,,0,0,0,,{\pos(540,960)}알아봅시다
```

**Method B: \kf karaoke fill (advanced, smooth transitions)**

```ass
Dialogue: 0,0:00:01.00,0:00:03.50,Main,,0,0,0,,{\kf58}비트코인의 {\kf60}역사를 {\kf110}알아봅시다
```

`\kf` value = (word duration ms) / 10. Example: 0.58s = kf58

### 3.3 Python Generator Function Signature

```python
def generate_ass_subtitle(
    words: list[dict],          # [{word, start, end}, ...]
    style_preset: str,          # "default" | "news" | "ranking" | "impact" | "story" | "minimal"
    hook_text: str | None,      # Top hook title (None if absent)
    hook_duration: float = 3.0, # Hook display time (seconds)
    highlight_mode: str = "color_swap",  # "color_swap" | "karaoke_fill"
    max_chars_per_line: int = 16,  # Max characters per line
    output_path: str = "subtitle.ass",
) -> str:
    """Generate ASS subtitle file and return path."""
```

### 3.4 Line Break Rules

- Korean: max 16 chars per line (never break before particles/postpositions)
- English: max 35 chars per line (never break before prepositions/articles)
- Max 2 lines displayed
- Use `\N` tag for line breaks

---

## 4. BGM Auto-Matching

### 4.1 emotion → BGM Mapping Table

| scene.emotion | BGM mood | Example track folder |
|---------------|----------|---------------------|
| neutral | calm | assets/bgm/calm/ |
| shock, surprise | tense | assets/bgm/tense/ |
| funny, humor | upbeat | assets/bgm/upbeat/ |
| serious, sad | cinematic | assets/bgm/cinematic/ |
| excitement | upbeat | assets/bgm/upbeat/ |

### 4.2 BGM Volume Rules

- BGM preparation: base track is trimmed/looped with fade and a conservative
  initial level.
- Final MP4 mix: prepared BGM is gain-compensated and sidechain-ducked under
  narration so the bed is audible on speakers, not erased.
- Default render mix: `VIDEO_STUDIO_BGM_MIX_GAIN=1.55`,
  `VIDEO_STUDIO_BGM_DUCK_THRESHOLD=0.08`,
  `VIDEO_STUDIO_BGM_DUCK_RATIO=2.6`,
  `VIDEO_STUDIO_BGM_DUCK_RELEASE_MS=180`.
- Fade-in: first 0.5s
- Fade-out: last 1.0s

### 4.3 FFmpeg Audio Mixing Command

```bash
ffmpeg -i narration.wav -i bgm.wav \
  -filter_complex "[1:a]volume=-18dB[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[out]" \
  -map "[out]" mixed_audio.wav
```

Sidechain ducking (volume varies based on narration presence):
```bash
ffmpeg -i narration.wav -i bgm.wav \
  -filter_complex "[0:a]asplit=2[narr][sc];[sc]aformat=channel_layouts=mono,compand=attacks=0:decays=0.3:points=-80/-80|-45/-45|-27/-30|0/-30,aformat=channel_layouts=stereo[sidechain];[1:a]volume=1.55[bgm_in];[bgm_in][sidechain]sidechaincompress=threshold=0.08:ratio=2.6:attack=10:release=180:level_sc=1[bgm_ducked];[narr][bgm_ducked]amix=inputs=2:duration=first[out]" \
  -map "[out]" mixed_audio.wav
```

---

## 5. Background Material Priority

### 5.1 Image/Video Source Selection Order

```
1. User upload (scene._upload_preview)
2. Pexels video search (9:16, 10s+)  ← needs to be added
3. Pexels image + Ken Burns
4. Imagen 4 AI generated image + Ken Burns
5. Gradient title card (final fallback)
```

### 5.2 Pexels Video Search Parameters

```python
# GET https://api.pexels.com/videos/search
params = {
    "query": scene.image_prompt,
    "orientation": "portrait",  # 9:16 preferred
    "size": "medium",           # 1920x1080 or higher
    "per_page": 3,
}
```

Selection criteria:
- duration >= scene.duration (at least scene length)
- Prefer portrait ratio; apply crop-to-fill for landscape
- Select video_files with width >= 1080

### 5.3 Ken Burns Motion Presets (Image Fallback)

```python
MOTION_PRESETS = {
    "zoom_in":     "zoompan=z='min(zoom+0.001,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={dur}:s=1080x1920:fps=30",
    "zoom_out":    "zoompan=z='if(eq(on,1),1.3,max(zoom-0.001,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={dur}:s=1080x1920:fps=30",
    "pan_left":    "zoompan=z='1.1':x='iw*0.1+on*(iw*0.8-iw/zoom)/{dur}':y='ih/2-(ih/zoom/2)':d={dur}:s=1080x1920:fps=30",
    "pan_right":   "zoompan=z='1.1':x='iw*0.8-on*(iw*0.8-iw/zoom)/{dur}':y='ih/2-(ih/zoom/2)':d={dur}:s=1080x1920:fps=30",
}
```

Motion assignment: cycle by scene_num % 4, no same motion for 2 consecutive scenes.

---

## 6. FFmpeg Render Quality Floor

This section is the reusable render-quality standard. It is not a one-off
iteration note from a single candidate. A future render-quality change must
either preserve these values or record evidence for why the standard changed.

**Important**: Use `ass=` filter, NOT `subtitles=` filter, to fully apply ASS styles.

### 6.1 Encoder Floor

All scene clips and final composition encodes use this H.264 floor:

```bash
-c:v libx264 -preset medium -crf 18 -profile:v high -level 4.2 -pix_fmt yuv420p
```

Rules:
- Do not fall back to FFmpeg/libx264 defaults for final candidate renders.
- Do not raise CRF above 20 for a publish candidate unless the run records a
  file-size or runtime reason and keeps a visual comparison artifact.
- BGM mix and final loudness normalization may copy video streams after the
  polished encode; they must not re-encode at a lower quality.

### 6.2 Scene Clip Visual Filter

All source video or static-loop scene clips use this scale/crop/polish chain:

```text
fps=30,
scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,
crop=1080:1920,
unsharp=3:3:0.28:3:3:0.10,
eq=contrast=1.025:saturation=1.030:gamma=1.010,
format=yuv420p
```

Intent:
- Lanczos scaling preserves more edge detail than the default scale path.
- The scene polish is intentionally conservative. It should restore compression
  softness without making AI face/hand artifacts harsher.
- This filter cannot rescue a bad source. If the source looks stock-like,
  semantically wrong, static, or artifact-heavy, fix source acceptance before
  changing render filters.

### 6.3 Final Composition Visual Filter

For xfade/acrossfade composition, burn subtitles first, then apply the final
polish:

```text
[vmerged]ass=filename='captions.ass',
scale=1080:1920:flags=lanczos,
fps=30,
unsharp=3:3:0.18:3:3:0.06,
eq=contrast=1.010:saturation=1.010:gamma=1.005,
format=yuv420p[vout]
```

For simple concat, the final `-vf` chain is:

```text
ass=filename='captions.ass',
fps=30,
scale=1080:1920:flags=lanczos,
unsharp=3:3:0.18:3:3:0.06,
eq=contrast=1.010:saturation=1.010:gamma=1.005,
format=yuv420p
```

Rules:
- Subtitles are part of the final visual layer; they must be included in the
  final render-quality review.
- Do not apply a stronger final sharpen than the scene sharpen by default. A
  stronger final pass often makes subtitle edges and AI artifacts look cheap.
- Transition duration and polish are separate concerns. A bad cut rhythm is not
  fixed by increasing sharpness.

### 6.4 Reference FFmpeg Shape

The actual orchestrator may build `-filter_complex`, but the final candidate
must be equivalent to this shape:

```bash
ffmpeg -y \
  -i scene-01.segment.mp4 -i scene-02.segment.mp4 \
  -filter_complex "[0:v][1:v]xfade=transition=fade:duration=0.350:offset=2.850[vmerged];[vmerged]ass=filename='captions.ass',scale=1080:1920:flags=lanczos,fps=30,unsharp=3:3:0.18:3:3:0.06,eq=contrast=1.010:saturation=1.010:gamma=1.005,format=yuv420p[vout];[0:a][1:a]acrossfade=d=0.350:c1=tri:c2=tri[amerged]" \
  -map "[vout]" -map "[amerged]" \
  -c:v libx264 -preset medium -crf 18 -profile:v high -level 4.2 -pix_fmt yuv420p \
  -c:a aac -movflags +faststart \
  output.mp4
```

### 6.5 Quality-Lift Ladder

When a render feels low quality, use this order. Do not jump straight to a new
filter value.

1. Source acceptance: storyboard match, first-second physical action, no generic
   B-roll, no AI/stock mismatch, phone-sized source review.
2. Edit grammar: first-frame hook, 2-3s cut rhythm, no unjustified long hold,
   captions placed away from subject and platform UI.
3. Audio: zero-paid voice provider proof, natural rate/pitch, BGM not erased by
   ducking, final loudness normalization.
4. Caption layer: exact style lines, max display durations, no production meta
   text, no oversized routine overlays.
5. Render engine: encoder floor, Lanczos scale, scene/final polish filters.
6. Packet evidence: ffprobe, render-quality-report, quality-audit, publish
   packet, contact sheet, phone-sized full-watch proof when upload is claimed.

If steps 1-4 are weak, a render-engine change can only create a sharper bad
video. Record that limitation in the quality note instead of claiming success.

### 6.6 Quality Ratchet

The render-quality floor is only the minimum acceptable baseline. Repeated
video creation must raise the visible quality bar. A candidate that only repeats
the previous floor without improving a named weakness is not a quality-recovery
iteration.

Every quality iteration must record:
- `previousBaseline`: the exact prior candidate path, SHA-256, and decision.
- `rejectionCause`: the viewer-visible reason the prior candidate was weak,
  such as source mismatch, weak first-second action, caption occlusion, flat
  pacing, poor voice energy, BGM balance, compression softness, or AI artifact
  exposure.
- `changedLever`: the one or two levers changed in this iteration. Allowed
  levers are source, storyboard, edit rhythm, voice, BGM, caption layout, render
  engine, first-frame/thumbnail, and packet evidence.
- `expectedVisibleImprovement`: what a phone-sized viewer should notice within
  the first full watch.
- `actualProof`: render path, SHA-256, ffprobe, contact sheet or phone-sized
  screenshot, and the relevant audit/report path.
- `nextRatchet`: the next specific quality bar if the candidate is still weak.

Rules:
- At least one `changedLever` must affect the viewer-facing video. Re-running
  the same manifest through the same settings is not a quality iteration.
- Do not change more than two major levers in one ratchet unless the previous
  candidate was rejected as structurally unusable. Otherwise the team cannot
  tell which change helped.
- The next ratchet must be stricter than the previous one. Examples: stronger
  first-second physical action, fewer source mismatches, more legible captions
  at phone size, less TTS compression, cleaner source provenance, or a more
  decisive thumbnail frame.
- Automated artifact gates can certify the packet shape, but they cannot close
  the ratchet. Human or phone-sized review decides whether the visible quality
  actually improved.
- If no improvement is visible, record the iteration as rejected and move the
  next ratchet to source/storyboard or edit grammar before touching FFmpeg
  again.

Runtime enforcement:
- `worker/render/compose_ffmpeg.py::write_render_quality_report()` fails the
  `qualityRatchet` check whenever a manifest declares `qualityIteration` or
  `qualityRatchetRequired=true` without all six required fields.
- The same check requires `changedLever` to name at least one viewer-facing
  lever such as source, storyboard, caption, TTS/audio, layout, edit pacing, or
  render polish.
- Episode preproduction writes `qualityRatchetRequired=true` plus a
  `qualityRatchet` template into `preproduction-manifest.json`,
  `asset-candidate-review.json`, and `accepted-source-map.json`, so another
  session cannot start a new source/render loop without seeing the ratchet.

---

## 7. Verification Criteria

### 7.1 Automated Verification (Run After Render)

```python
def verify_render(output_path: str) -> list[str]:
    """Verify render output. Return failed items as string list."""
    errors = []

    # 1. Resolution check
    probe = ffprobe(output_path)
    if probe.width != 1080 or probe.height != 1920:
        errors.append(f"Resolution mismatch: {probe.width}x{probe.height}, expected: 1080x1920")

    # 2. Audio stream check
    if not probe.has_audio:
        errors.append("No audio stream")

    # 3. Duration check (±2s tolerance)
    expected = sum(scene.duration for scene in scenes)
    if abs(probe.duration - expected) > 2.0:
        errors.append(f"Duration mismatch: {probe.duration:.1f}s, expected: {expected:.1f}s (±2s)")

    # 4. ASS file existence check
    ass_path = output_path.replace(".mp4", ".ass")
    if not os.path.exists(ass_path):
        errors.append("ASS subtitle file not generated")

    return errors
```

### 7.2 Manual Verification Checklist

After render completion, verify these items:

- [ ] Subtitles display at screen center (y≈960)
- [ ] Subtitles do not overlap right button area (x>950)
- [ ] Subtitles are not placed in bottom 20% (y>1536)
- [ ] Hook title displays at top (y≈120~200)
- [ ] Karaoke highlight syncs with audio
- [ ] BGM ducks during narration segments
- [ ] BGM fades naturally in intro/outro
- [ ] Fonts render without corruption, Korean displays correctly

### 7.3 Render-Quality Change Evidence

Any change to `worker/render/compose.py`, `worker/render/compose_ffmpeg.py`,
`worker/render/transitions.py`, or `worker/render/subtitles.py` that claims
visual quality improvement must include:

- focused tests proving the expected FFmpeg args or ASS style lines
- `python -m pytest -q tests/test_manual_clip_pipeline.py`
- `npm run build` when UI/final-library behavior or published packet status is
  part of the claim
- one actual render using the changed path
- ffprobe proof for 1080x1920, 30fps, H.264, AAC, and duration
- a SHA-256 for the exact MP4
- log or test evidence that `flags=lanczos`, `unsharp`, `eq`, and `crf 18` were
  used
- contact-sheet or phone-sized screenshot review for subtitle placement
- final-library audit only as an artifact gate, never as upload approval

If there is no actual render, report the change as code-ready only. If there is
no phone-sized human full-watch, do not claim same-day upload readiness.

### 7.4 Production Quality-Loop Evidence

Prompt/source quality and render polish are not enough. Every candidate that
changes subtitles, layout, voice, BGM, edit rhythm, render settings, phone
review, or publish readiness must also update the active episode quality-loop
ledger.

The active standard is written by `POST /api/episodes/preproduction-plan` to:

- `storage/episodes/<episodeId>/preproduction/quality-loop-standard.json`
- `storage/episodes/<episodeId>/preproduction/quality-iteration-ledger.json`

The unified gate-system registry is `worker/quality_gate_system.py`. The same
`gateSystem.systemVersion` must appear on:

- `quality-loop-standard.json`
- episode `outputGate` / `promptOutputGate`
- `render-quality-report.json`
- final-library `goalReadiness`

The active system version is
`2026-06-08-unified-quality-gate-system-v1`. Treat `gateSystem` as the
cross-stage index for preproduction, episode output, quality iteration,
asset-source, render-quality, final-readiness, and post-publish analytics. The
detailed checks remain in their existing domain payloads, but every future gate
must be registered into this unified surface before it is considered part of
the production loop.

Every top-level `*Contract` in `quality-loop-standard.json` must also appear in
`contractRegistry`. Episode output gates iterate that registry dynamically, so a
new rendering, caption, audio, review, or publish standard is not active until
it is both written as a contract and registered there. Unregistered contracts
block output.

If the ledger says `nextRequiredAction.status=apply-next-mutation`, the next
iteration must resolve that exact iteration with `resolvesIterationId`,
`appliedMutation`, and mutation evidence. Repeating a pass/fail note without
applying the recorded mutation is not a valid loop.

Caption/layout failures must be recorded with:

- `stage`: `caption` or `layout`
- `status`: `fail`, `blocked`, or `needs-spec-change`
- `observedFailure`: what was wrong at phone size
- `changedLever`: includes `caption` or `layout`
- `nextMutation`: the next caption/layout edit, not a generic rerender
- `gateEvidencePaths`: contact sheet, phone screenshot, or render review path

Voice/audio failures must be recorded with:

- `stage`: `voice`, `audio`, or `bgm`
- `observedFailure`: pacing, pronunciation, energy, BGM ducking, or balance
- `changedLever`: includes `voice`, `audio`, `BGM`, or `scriptDensity`
- `nextMutation`: provider/rate/pitch/script-density/mix change
- `gateEvidencePaths`: audio review, render-quality report, or phone review

Edit-rhythm failures must be recorded with:

- `stage`: `edit-rhythm`
- `observedFailure`: weak first two seconds, long hold, or bad cut order
- `changedLever`: includes `edit rhythm`, `first frame`, `cut order`, or source
- `nextMutation`: cut-order/duration/first-frame/source change
- `gateEvidencePaths`: contact sheet, timeline review, or render report

Phone/publish failures must be recorded with:

- `stage`: `phone-review` or `publish`
- `observedFailure`: phone-sized viewer issue or upload readiness blocker
- `changedLever`: the layer to fix before another publish claim
- `nextMutation`: specific next production change
- `gateEvidencePaths`: phone-review JSON, publish packet, or platform proof path

Minimum evidence fields for a passing caption/layout iteration:

- `captionPreset`
- `layoutVariantKey`
- `safeZoneReview`
- `subjectOcclusionVerdict`
- `platformUiCollisionVerdict`
- `phoneContactSheetPath`
- `lineBreakReview`

Do not count a render as a quality improvement when subtitles still cover the
subject, phone screen, object state change, bottom 20%, or right-side platform
UI area. Fix the caption/layout layer first, then rerender a named candidate.

Do not count a candidate as upload-ready when voice/audio, edit rhythm,
phone-sized full-watch, fresh-source proof, or publish packet evidence is
missing. Those layers must either pass the ledger or record a failed iteration
with the next mutation before another candidate can be promoted.

---

## 8. CLAUDE.md Integration

This document's specs must be reflected in these files:

| File | Content |
|------|---------|
| `worker/render/compose.py` | §6 FFmpeg final composition and simple concat |
| `worker/render/compose_ffmpeg.py` | §4 BGM mixing, §5.3 Ken Burns, §6 scene clip render floor |
| `worker/render/transitions.py` | §6 xfade/acrossfade final visual polish |
| `worker/render/subtitles.py` | §2 ASS styles, §3 karaoke generation |
| `worker/media/adapters.py` | §5.2 Pexels video search addition |
| `app/ui/src/lib/constants.ts` | §2.2 Preset names synced with UI labels |
| `shared/contracts/plan.ts` | Add bgm_mood field to Scene type |

**When Claude Code modifies the above files, code that does not follow this document's values is rejected.**
