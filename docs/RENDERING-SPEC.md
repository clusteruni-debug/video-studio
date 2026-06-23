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

### 5.4 Still Image Source Policy

Static web images are allowed as source material only when the still frame is
the viewer job itself. Valid primary still-image roles are:

- meme/reaction image
- screenshot, screen capture, source capture, or official/document capture
- evidence card, reference card, data card, chart, graph, or table source

For normal explainers, maker/process videos, science/object demos, and
Korea-first curiosity formats, a generic web still may support the edit but must
not be the primary visual source. Use Grok/Gemini/local MP4, direct footage,
rights-safe stock video, generated simulation, or screen/source capture for the
main proof. Ken Burns motion on a weak still does not satisfy this rule.

Runtime enforcement:
- `worker/render/compose_ffmpeg.py::write_render_quality_report()` emits
  `stillImageSourcePolicy`.
- Source-first/editorial or internet-source manifests fail this check when an
  internet still image is used as a primary visual without a meme/reaction,
  capture, or evidence/reference/data-card role.
- If a still is only support material, mark `stillImageSourceRole` or
  `imageSourceRole` as `support`, `evidence-card`, `reference-card`, or
  `data-card`.

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

### 6.7 Opening, BGM, Bridge, And Payoff Gate

Reference-styled renders must not start with a black screen, a title card, or a
caption-only frame. The first frame needs the real source object/action visible;
caption text may support the frame but cannot be the frame.

`worker/render/golden_reference_gate.py` enforces an
`openingAudioContinuity` manifest object before FFmpeg runs. Passing manifests
must provide:

- `coldOpen.firstFrameHasPrimaryVisual=true`.
- `coldOpen.firstFrameIsBlack=false`.
- `coldOpen.captionOnlyOpening=false` and
  `coldOpen.firstFrameHasOnlySubtitleOrText=false`.
- `coldOpen.blackScreenStartSec<=0.08`.
- `coldOpen.firstVisibleActionSec<=0.60`.
- `coldOpen.firstTwoSecReviewPath` pointing to local first-2s visual evidence.
- `audioBed.bgmPresent=true`, `bgmAudibleUnderVoice=true`,
  `introBgmAudible=true`, `outroBgmTailAudible=true`, and
  `bgmNonPlaceholder=true`.
- `audioBed.bgmMeanVolumeDb` between `-34.0` and `-10.0` dB for the BGM evidence
  layer. This is not final loudness; it proves the bed was not erased.
- `audioBed.audioMixEvidencePath` pointing to local mix evidence.
- `ttsAlignment.required=true` and `ttsAlignment.timelineReviewed=true`.
- `ttsAlignment.voiceQuality.required=true`. The default approved free provider
  is `edge-tts` with a Korean Neural voice such as `ko-KR-SunHiNeural` or
  `ko-KR-InJoonNeural`.
- `ttsAlignment.voiceQuality.voiceNaturalnessReviewed=true`,
  `speechRateReviewed=true`, `fallbackUsed=false`, and
  `perceivedRoboticOrSapi=false`.
- `ttsAlignment.voiceQuality.candidateComparisonPath` must point to local
  voice-candidate evidence. A self-claimed provider name is not enough.
- Azure Speech F0, MeloTTS, or human-recorded voice can replace `edge-tts` only
  when `candidateEvaluationStatus=approved` or an explicit provider exception
  is recorded. Otherwise the default remains `edge-tts`.
- Azure Speech F0 is explicit operator opt-in only, not a zero-paid default.
  The free neural-character allowance does not remove the Azure account,
  card/key, and pay-as-you-go management boundary.
- `ttsAlignment.voiceQuality.ratePercent` must stay within `-18` to `+12` for
  Korean reference narration unless a future spec revision records a better
  phone-review range.
- `ttsAlignment.timelineDurationSec` must be positive, and TTS duration/span
  must be provided by `narrationDurationSec`, `voiceTimelineSpanSec`, or a
  measurable local WAV path such as `narrationAudioPath`.
- TTS duration/span and `narrationEndSec` must not exceed the video timeline.
  A render like 26.09s of narration inside a 24.20s MP4 is an automatic fail,
  regardless of the claimed score.
- `ttsAlignment.allVoiceLinesComplete=true`,
  `finalSpokenLineComplete=true`, `finalCaptionCoversFinalVoiceLine=true`, and
  `captionsDoNotAdvanceBeforeVoice=true`.
- `ttsAlignment.voiceEndsBeforeVideoEndSec>=0.35`,
  `maxCaptionVoiceDesyncSec<=0.65`, and `maxSceneVoiceOverflowSec<=0.25`.
- `ttsAlignment.sceneTimings[]` must cover every scene with `sceneEndSec`,
  `voiceEndSec`, and `captionEndSec`. Voice cannot continue more than 0.25s
  after a scene cut, and captions cannot disappear more than 0.45s before the
  corresponding voice line ends.
- `audioBridges[]` with one bridge per scene transition. Each bridge must use
  `j-cut`, `l-cut`, `crossfade`, `acrossfade`, or `sound-bridge`, and
  `durationSec>=0.20`.
- `payoffTail.finalBeatHasVisualResolution=true`.
- `payoffTail.endingIsBlank=false`, `blankOutroSec<=0.15`,
  `finalVisualHoldSec>=0.60`, `finalBgmTailSec>=0.60`, and
  `finalAudioFadeSec>=0.50`.
- `payoffTail.finalTwoSecReviewPath` pointing to local ending evidence.

Forbidden shortcuts:

- A black frame with only subtitles at the start.
- A title-card or text-only first beat for object/process/curiosity videos.
- Lavfi/sine/noise/silent placeholder assets counted as BGM.
- Hard audio cuts between scenes when the video claims reference edit grammar.
- TTS that keeps speaking after the scene/caption has already moved on.
- Windows SAPI/Desktop voices, including `Microsoft Heami Desktop` and
  `System.Speech`, in any golden/reference render. They are allowed only for
  throwaway smoke checks and cannot satisfy `voiceQuality`.
- Final answer narration that is cut off or only partially captioned.
- Empty outro padding after the answer. The ending tail must hold the visible
  answer while the audio resolves.

### 6.8 Global Post-Edit Golden Reference Gate

This gate is global, not packet-specific. Any manifest that declares
`referenceStylePreset`, `goldenReferenceComplianceRequired=true`, or
`referenceComplianceRequired=true` must include a `postEditGoldenReference`
object before FFmpeg runs. Source quality remains mandatory, but post-edit
quality is a separate contract and cannot be waived by saying "better sources
will fix it."

Global gates must not encode topic-specific objects such as a specific product,
prop, location, body part, or incident. Project prompt bibles provide those
concrete anchors. The global gate only knows generic slots:
`primarySubject`, `actorOrManipulator`, `environment`, `primaryAction`,
`camera`, `lighting`, and `style`.

`worker/render/golden_reference_gate.py` enforces:

- `postEditGoldenReference.required=true`.
- Top-level `sourceSequenceContinuity.required=true` for multi-source renders.
  It must use generic continuity slots and score `entityContinuity`,
  `environmentContinuity`, `actionContinuity`, `cameraContinuity`,
  `lightingContinuity`, `styleContinuity`, and `repairability`.
- Every scene must include `sourceQualityRubric.required=true`. Its generic
  source-take dimensions are `promptIntentFit`, `primarySubjectIntegrity`,
  `actorOrManipulatorIntegrity`, `actionReadability`, `physicalPlausibility`,
  `cameraGrammar`, `lightingColorNaturalness`, `temporalStability`,
  `aiArtifactControl`, and `editability`.
- `sourceSequenceContinuity.topicSpecificCriteriaInGlobalGate=true` or
  `sourceQualityRubric.topicSpecificCriteriaInGlobalGate=true` is rejected.
- `referenceBasis[]` must include current reusable reference anchors:
  YouTube Shorts editing/tooling practice, TikTok Creative Center Top Ads or
  equivalent high-performing vertical examples, first-3s hook-period evidence,
  and short-form accessibility/cognitive-load evidence.
- `score.overall>=score.minOverall`; default minimum is `72`.
- `score.dimensions` must use the generic 10-part rubric:
  `sourceTakeQuality`, `sourceSequenceContinuity`, `hookClarity`,
  `storyPayoff`, `copyTtsQuality`, `captionAccessibility`, `editRhythm`,
  `audioMix`, `colorTechnicalQuality`, and `platformReferenceFit`.
- Each dimension must be at least `score.minDimension`; default minimum is `60`.
- Required evidence paths must exist:
  `firstThreeSecReviewPath`, `captionSafeZoneEvidencePath`,
  `audioMixEvidencePath`, `colorMatchEvidencePath`, `finalTwoSecReviewPath`,
  and `scoringReviewPath`.
- `scoringReviewPath` must use schema `video-studio.post-edit-score.v1`.
  Its `computedScore` and the manifest `score` must match the score derived by
  `worker/render/golden_reference_gate.py` from source take dimensions, source
  sequence continuity, hook, payoff, copy/TTS, captions, rhythm, audio, color,
  and platform reference checks. A manifest and evidence file that simply type
  the same inflated number fail when they do not match the gate-derived result.

Required subcontracts:

- `hook`: first 3 seconds must contain the primary visual, motion/action, an
  audible audio bed, and a clear viewer question. First caption must appear
  after source visibility and by `1.25s`.
- `captions`: max 2 lines, max 28 chars per caption, stable safe-zone system,
  no main-subject occlusion, timeline reviewed, and max screen area ratio
  `<=0.18`.
- `layoutHud`: web-referenced layout/HUD contract. It must include YouTube
  Shorts text/timeline/voiceover/filter references, TikTok Creative Center Top
  Ads reference, WCAG contrast/caption accessibility reference, and timed-text
  line treatment reference. Required values:
  - `safeZone.platformUiReviewed=true`, `subjectOcclusion=false`,
    `topReservedPx>=96`, `bottomReservedPx>=240`, and `rightReservedPx>=96`.
  - `typography.hookFontSizePx` between `54` and `74`;
    `typography.bodyFontSizePx` between `44` and `60`.
  - `typography.lineCountMax<=2`, `lineLengthMaxKorean<=16`,
    `textContrastRatio>=4.5`, and `boxOpacity` between `0.28` and `0.62`.
  - `hud.mode` must be `none`, `minimal-frame`, or `soft-frame`;
    `hud.opacity<=0.10`, `hud.screenAreaRatio<=0.025`, and no HUD text labels
    or debug marks.
  - `transitions.purposeDeclaredPerCut=true`, `beatAligned=true`,
    `decorativeOnlyTransitions=false`, and `maxTransitionDurationSec<=0.36`.
- `editorialDirection`: web-referenced post-source direction grammar. It is
  required before CapCut handoff, external edit elements, or final scoring can
  claim post-edit quality. Required values:
  - `required=true`.
  - `referenceBasis[]` must include YouTube Shorts, CapCut caption/sound tools,
    sound-design/SFX matching, short-form accessibility, and continuity-editing
    references.
  - `evidence.directingPlanPath` must be valid UTF-8 JSON with schema
    `video-studio.editorial-pass.v1` and pass/reviewed-pass status.
    It must include `shotIntentMap[]`, `motivatedCutPlan[]`,
    `captionPlan[]`, `ttsSegments[]`, and `audioCueSheet[]` evidence.
    The evidence arrays must match the manifest contract's scene IDs, cut
    fields, caption cues, TTS segments, and audio cue fields; stale or
    partially copied plan JSON is rejected.
  - `evidence.referenceComparisonPath` must be valid UTF-8 JSON with schema
    `video-studio.reference-comparison.v1`, at least two external references,
    `noHudAbReviewed=true`, and `editImprovesComprehensionOverNoHud=true`.
  - `phoneReviewPath` and `noHudComparisonPath` must be local image/video
    review evidence, not empty placeholder files.
  - `shotIntentMap[]` must exactly match `manifest.scenes[]` scene ID order and
    include `role`, `viewerQuestionOrAnswer`, `visibleEvent`, `focusTarget`,
    `sourceEventReadable=true`, `subjectProtected=true`, and
    `captionExplainsMissingVisual=false`.
  - `motivatedCutPlan[]` must cover every cut. Allowed `cutReason` values are
    `match-action`, `new-information`, `spatial-reorientation`, `payoff`,
    `rhythm`, `audio-bridge`, or `continuity-bridge`; `unmotivatedHoldSec`
    must be `0`. Each cut must include `fromSceneId`, `toSceneId`, and
    `cutAtSec` matching the adjacent manifest scene boundary.
  - `audioVisualBinding.everyCueBoundToVisibleEvent=true`,
    `unrelatedAudioCues=false`, `maxSyncOffsetSec<=0.20`, and
    `minimumSfxCueCount=0`. SFX/foley/transition hits must name the visible
    `sourceEvent` they support, bind to a manifest `sceneId`, include
    `startSec`, and include `auditOperationId` so the CapCut draft audit can
    prove the cue was realized.
  - `captionPerformance.notTtsDuplicate=true`, `timelineReviewed=true`,
    `safeZoneReviewed=true`, `subjectOcclusion=false`,
    `captionExplainsMissingVisual=false`, `maxLines<=2`, and
    `maxCharsPerCaption<=24`. It must include timed caption cues and matching
    TTS segments for every scene; caption/TTS start and end times must stay
    within `0.30s`, and caption text must not duplicate the TTS line.
  - `continuityMap.continuitySlots[]` must include `primarySubject`,
    `actorOrManipulator`, `environment`, `primaryAction`, `camera`,
    `lighting`, and `audio`; `adjacentContinuityPassRatio>=0.80`; subject
    identity drift, subject scale jumps, and unexplained camera-world jumps are
    false.
  - `restraintMode.effectsAreOptional=true`,
    `effectCountIsNotQuality=true`, `symbolCuesDefault=false`, and
    `noGeneratedStickerPresetSpray=true`.
  - `referenceComparison.comparedAgainstExternalReferences>=2`,
    `noHudAbReviewed=true`, and `editImprovesComprehensionOverNoHud=true`.
- `externalEditElements`: web-referenced external edit-element layer. It is
  separate from captions, HUD/frame, source quality, TTS, and BGM. Required
  values:
  - `required=true`.
  - `referenceBasis[]` must include YouTube Shorts, TikTok, motion-continuity,
    and WCAG anchors.
  - `layerPurpose.editorialFunctionDeclared=true`,
    `supportsNarrativeBeats=true`, `decorativeOnly=false`, and
    `sourceReplacementClaim=false`.
  - `elementTypes[]` must declare at least two allowed reusable types such as
    `keyword-emphasis`, `pointer-line`, `callout`, `motion-graphic`,
    `sticker`, `beat-sync`, `sfx-hit`, `match-cut-assist`, or
    `freeze-hold`.
  - `safety.platformSafeZoneReviewed=true`, `subjectOcclusion=false`,
    `debugOrEditorLabels=false`, `rapidFlashes=false`,
    `reducedMotionSafe=true`, and `templateLook=false`.
  - `safety.maxScreenAreaRatio<=0.14`, `maxOpacity<=0.78`, and
    `maxFlashPerSecond<=3`.
  - `perceptualSalience.recognizableSymbolRequired=false`,
    `semanticCueMatchesNarration=true`, `viewerCanNameCueAfterOneWatch=true`,
    `sourceEventBindingRequired=true`,
    `everyCueBoundToVisibleSourceEvent=true`,
    `effectCountIsNotQuality=true`, and `symbolCuesDefault=false`.
  - `perceptualSalience.minVisualCueScreenAreaRatio>=0.012` and
    `minCueOpacity>=0.50`.
  - When the layer declares `containsWarningOrNegativeAction=true`, it must
    also set `warningBeatSourceEventBound=true` and include a `warning-no`
    semantic role element bound to a visible source event.
  - When the layer declares `containsPositiveResolution=true`, it must set
    `positiveResolutionSourceEventBound=true` and include a `safe-resolution`
    semantic role element bound to a visible source event.
  - `perScenePlan[]` must cover every scene. At least two scenes must actively
    use external elements when the video has two or more scenes. The scene IDs
    and order must exactly match `manifest.scenes[]`, including clean
    editorial mode where every scene only records a no-element reason.
  - Each element must include `type`, `purpose`, `startSec`, `endSec`,
    `screenAreaRatio`, `opacity`, `semanticRole`, `sourceEvent`,
    `bindingMode`, `semanticCueMatchesNarration=true`,
    `subjectOcclusion=false`, and `decorativeOnly=false`.
  - Symbolic X/OK/check cues require `manualExceptionApproved=true`, a visible
    `sourceEvent`, and `whySymbolBeatsCleanerEdit`; they are never the default
    edit language.
  - Each element duration must stay `<=2.40s`.
  - `evidence.editElementPlanPath` and a phone/visual preview evidence path
    must exist locally before render.
- `capcutHandoff`: required for every golden/reference post-edit candidate.
  FFmpeg output is only a preview until a CapCut draft exists and is reviewed.
  Required values:
  - `required=true`, `draftRequired=true`, and
    `pipelineMode` is `capcut-draft-first` or `capcut-review-handoff`.
  - `referenceBasis[]` must include CapCut keyframes, CapCut captions, YouTube
    Shorts timeline editing, TikTok Top Ads reference comparison, easing/motion
    timing, CapCut native effects/templates/SFX references, and VectCutAPI draft
    automation.
  - `capcutIsPrimaryEditSurface=true`, `ffmpegPreviewOnly=true`, and
    `ffmpegOnlyAllowed=false`.
  - `manualExportRequired=true` and `humanReviewBeforeUpload=true`.
  - `editableTextAndTiming=true` so captions/timing can still be corrected in
    CapCut instead of being burned into a brittle FFmpeg-only render.
  - `motionDesignedEditElements=true`; raw debug-looking `drawbox`/`drawtext`
    overlays are not enough for high-quality candidates.
  - `automationSurface.tool` must be `VectCutAPI`, `pyJianYingDraft`, or an
    equivalent CapCut draft automation path. `targetEditor` must be CapCut,
    `draftFormat` must be `draft_content.json`, and local draft root, CapCut
    install, operator export, and FFmpeg-preview-only status must be verified.
  - `editModel` must keep the edit multitrack and editable: text/timing,
    captions, audio levels, and motion elements cannot be flattened before
    CapCut review. It must also set `nativeCapCutEffectsRequired=true`,
    `editElementsUseNonTextVisuals=true`, and `extraTextCalloutsAllowed=false`
    for final-quality edit layers; repeated subtitle-like callouts are not a
    valid effect pass.
  - `effectPass` is required. Default mode is
    `clean-editorial-no-canned-effects`: generated stock/native CapCut effects,
    generated visual overlays, random SFX hits, and preset spray are disabled.
    In this mode `usesNativeCapCutEffects=false`, `nativeEffectsDisabled=true`,
    `cannedEffectsRejected=true`, `effectTrackCount=0`, and
    `maxEffectTracks=0`.
  - Manually reviewed effects mode is a later explicit exception, not the
    default. If a human selects an effect preset, `effectPass` must describe the
    visual source-action/on-screen-cue/audio-hit binding and stay under a strict
    upper bound.
  - `motionDesign` must use keyframes, easing or speed curves, at least two
    keyframed elements, no raw `drawbox`/`drawtext` final overlays, and
    restrained short motion between `83ms` and `400ms`.
  - `mediaLinked.sourceVideoTracks`, `ttsTracks`, `bgmTrack`, and
    `captionTracks` must be true. `editElementTracks` and `effectTracks` are
    required only when the manifest declares active external edit elements or
    a manually reviewed effect pass. `sfxTracks` must be true when the
    editorial/audio plan declares SFX, foley, or transition-hit cues.
  - `draftPath`, `draftContentPath`, and `draftAuditPath` must exist locally.
    `draftContentPath` must be valid JSON. `draftAuditPath` must be valid JSON
    with schema `video-studio.capcut-draft-audit.v1`, an `operations[]` list,
    and keyframe/track counts that satisfy the manifest's motion and media
    claims.
    The gate parses `draft_content.json` and requires non-empty tracks,
    source-video segments, audio segments for TTS/BGM claims, text segments for
    caption claims, and exported video keyframes. Audit `trackCounts` and
    keyframe totals must match the draft JSON, and audit operations must back
    source motion, TTS, BGM, captions, and SFX claims.
  - In clean editorial mode, `effectTracks=0` and
    `editElementVisualLayers=0` must be proven by the draft audit. If active
    external edit elements are declared, `mediaLinked.editElementTracks=true`
    and the audit's `editElementVisualLayers` count must cover the planned
    elements.
  - `roundTripStatus` must be `draft-created`, `operator-review-required`, or
    `export-reviewed`.
- `rhythm`: action beats aligned to cuts, no hard jump without bridge,
  `minShotHoldSec>=1.10`, `maxDeadAirSec<=0.65`, and transition count covers
  every scene transition.
- `audio`: ducking applied, BGM continuous, source ambience or foley present,
  speech/BGM separation reviewed, and full mix mean between `-24dB` and `-12dB`.
- `color`: one grade applied to all scenes, no unmotivated flashes,
  `maxLumaDelta<=0.30`, and `maxSaturationDelta<=0.30`.
- `payoff`: final answer resolves the question, no new information in the last
  second, `finalVisualHoldSec>=1.00`, and `finalAudioTailSec>=0.70`.

### 6.9 Global Korean Copy, Caption, And TTS Naturalness Gate

This gate is global for Korean reference/golden renders. It is not specific to
any packet, topic, object, product, or location. Korean copy quality must pass
before later tuning of caption position, motion direction, font size, layout
variants, HUD, or frame overlays.

`worker/render/golden_reference_gate.py` enforces this inside each scene's
`copyTone` and `ttsScriptQuality` checks:

- Captions must read like natural Korean viewer copy, not literal keyword
  labels. Reject examples are language-smell seeds, not topic criteria:
  awkward compound labels, literal translated answer labels, broken condition
  phrases, and bare action nouns such as `답은 보관 시간` or `그냥 피하기`.
- Caption lines may be short, but they must carry a natural phrase, question,
  condition, or action. Bare noun-label lines are rejected even when the nouns
  are factually related to the topic.
- TTS scripts must read naturally when spoken aloud. They need Korean sentence
  endings such as `-요`, `-까요`, `-세요`, `-예요`, or equivalent natural spoken
  endings.
- TTS may add context, but it must not merely repeat the caption, sound like a
  report, or use over-friendly AI-host phrases.
- Korean copy review comes before layout/HUD review. A clean HUD cannot
  compensate for awkward Korean.

### 6.10 Global Caption Layout, Motion Direction, Size, And HUD Reference Gate

This gate locks the non-source visual treatment. It exists because source-level
unity is not enough: bad Korean captions, oversized boxes, arbitrary HUD labels,
and decorative transitions can make a usable source feel amateur.

Reference anchors consulted on 2026-06-20:

- YouTube Help, "Shorts editing tips":
  `https://support.google.com/youtube/answer/13380879`.
  Use sound, text, voiceover, filters, and timeline review deliberately; text
  can provide context through fast edits and the timeline must be checked before
  publishing.
- TikTok Creative Center Top Ads:
  `https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en`.
  Compare against high-performing vertical ad examples rather than internal
  taste.
- WCAG 2.2:
  `https://www.w3.org/TR/WCAG22/`. Text contrast needs a minimum 4.5:1 ratio
  for normal text, and captions are part of time-based media accessibility.
- Netflix timed text guidance:
  `https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide`.
  Maximum two lines, controlled line length, and reading speed constraints are
  the floor for caption readability.

The resulting production rule:

- Captions are editorial beats, not labels. One active caption block at a time.
- Caption boxes must be smaller than the previous V4.1 style and must not cover
  the primary subject, actor/manipulator, or primary action.
- The bottom platform/UI area remains clear; avoid putting captions into the
  bottom rail unless a scene-specific phone review proves it is safe.
- HUD/frame treatment is optional and must be nearly invisible. No `REC`, scene
  labels, debug marks, guide lines, or editor-like labels.
- Transitions need an editorial reason: condition shift, location shift, action
  answer, or payoff. Decorative wipes and big full-screen cards are not default
  grammar.

Use the score as a ratchet:

- `60-69`: reviewable but not golden; source or edit grammar still visibly weak.
- `70-79`: acceptable draft candidate; needs human full-watch before upload.
- `80-89`: strong channel candidate; only minor source/polish caveats remain.
- `90+`: gold sample candidate; reusable as future reference evidence.

### 6.11 Global External Edit Elements Layer Gate

This gate locks the extra editing layer beyond camera zooms, pans, captions,
TTS, BGM, and the minimal HUD/frame. It exists because a video can pass source
continuity but still feel empty, flat, or amateur when no editorial emphasis,
callout, beat cue, or continuity assist exists. It can also fail in the other
direction when stickers, debug labels, guide lines, or decorative motion cover
the source.

The gate is about implementation, not paperwork. A line that is too subtle for
the viewer to notice is a failure even if the manifest has a plan and a purpose
field. The viewer must be able to name the cue after one watch, for example
`red X`, `warning pulse`, `safe check`, `answer highlight`, or `beat marker`.

Reference history is persisted in
`docs/reference/external-edit-elements.md`. The current 2026-06-20 anchors are:

- YouTube Blog, "New creation tools coming to YouTube Shorts":
  `https://blog.youtube/news-and-events/new-creation-tools-youtube-shorts-2025/`.
  Use clip timing, timed text, music, beat sync, templates, effects, and
  stickers as edit tools, not random decoration.
- YouTube Help, "Shorts editing tips":
  `https://support.google.com/youtube/answer/13380879`.
  Text and timeline controls must guide viewers through fast edits and be
  reviewed before publishing.
- YouTube Help, "Enhance your Shorts":
  `https://support.google.com/youtube/answer/16215842`.
  Visual guides, stickers, text, timeline editor, beat sync, music, and
  voiceover all imply deliberate placement and timing.
- TikTok Creative Center Top Ads:
  `https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en`.
  External edit density should be compared with high-performing vertical
  examples, not internal taste alone.
- Microsoft Learn connected animation:
  `https://learn.microsoft.com/en-us/windows/apps/develop/motion/connected-animation`.
  Motion should maintain context and draw focus to shared content across a
  change.
- WCAG 2.2:
  `https://www.w3.org/TR/WCAG22/`.
  Flash and motion safety are hard constraints, not polish preferences.

Runtime enforcement:

- `worker/render/golden_reference_gate.py` fails golden/reference manifests
  without `postEditGoldenReference.editorialDirection`.
- `editorialDirection` must prove shot intent, motivated cuts, source-bound
  audio cues, caption performance, continuity, restraint, and reference
  comparison before CapCut handoff or external edit elements can be used as
  quality evidence.
- SFX/effect counts are not quality floors. A candidate with zero generated
  external effects can pass when the no-effect direction is intentional and
  evidenced; a candidate with many effects fails when they are not bound to
  visible source events.
- Symbolic X/OK/check cues are high-risk exceptions. The default gate rejects
  symbolic-cue defaults and requires manual exception evidence when a symbol is
  used.
- `worker/render/golden_reference_gate.py` fails golden/reference manifests
  without `postEditGoldenReference.externalEditElements`.
- External elements must be timed per scene and evidenced by both an edit plan
  artifact and a phone/visual preview artifact.
- External elements must include perceptual salience: narration/caption
  semantic match, viewer-nameable cue, source-event binding, and minimum
  visible area/opacity.
- Warning/negative-action and positive-resolution beats require visible
  source-event binding, not default symbolic marks.
- The gate is generic. It rejects
  `topicSpecificCriteriaInGlobalGate=true` so future topics do not overfit this
  bottled-water example.
- The layer is not allowed to claim source replacement. If source quality is
  weak, source acceptance must still fail or stay caveated.

### 6.12 CapCut Handoff Gate

FFmpeg-only rendering is useful for fast previews, automated contact sheets,
decode checks, and regression proof. It is not the default final-quality path
for Shorts/TikTok/Reels candidates that claim golden/reference post-edit
quality. The production path is:

1. Generate/import source clips, TTS, BGM, SFX, captions, and edit-element plan.
2. Build a CapCut draft with editable tracks.
3. Open/review the draft in CapCut.
4. Export from CapCut.
5. Run final MP4 verification on the exported file.

Reference history is persisted in
`docs/reference/capcut-automation.md`. The current 2026-06-20 anchors are:

- CapCut keyframe animation:
  `https://www.capcut.com/tools/keyframe-animation`.
  Motion must remain editable as keyframes with position, scale, rotation,
  opacity, color, and speed/easing controls.
- CapCut auto caption generator:
  `https://www.capcut.com/tools/auto-caption-generator`.
  Caption text, timing, style, and sync must remain editable in the editor.
- CapCut online video editor:
  `https://www.capcut.com/tools/online-video-editor`.
  Effects, transitions, filters, stickers, audio, and text are timeline-level
  edit surfaces; effect claims need editable timeline evidence.
- CapCut video effect and filter:
  `https://www.capcut.com/tools/video-effect-and-filter`.
  Effects, filters, transitions, and animations should be chosen by purpose:
  focus, warning, impact, atmosphere, or transition. For generated drafts, the
  default is no stock effects because canned presets can read as unrelated.
- CapCut effects templates:
  `https://www.capcut.com/template/effects`.
  Common reusable effect language includes flash, glitch, smooth motion, light
  leak, grain, and HUD-style overlays layered to beat and scene intent. These
  are not automatic quality markers; generated preset spray is rejected.
- CapCut sound effects:
  `https://www.capcut.com/tools/sound-effects`.
  SFX should match motion, transitions, scene changes, tone, and pacing. Random
  whooshes or beeps without a visible event are rejected.
- YouTube Help, "Enhance your Shorts":
  `https://support.google.com/youtube/answer/16215842`.
  Shorts editing is a timeline of video, text, stickers, music, voiceover,
  TTS, beat sync, and platform-safe placement.
- YouTube Help, "Shorts editing tips":
  `https://support.google.com/youtube/answer/13380879`.
  Sound and text guide fast edits; timeline review is part of quality.
- TikTok Creative Center Top Ads:
  `https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en`.
  Edit density and execution should be compared with high-performing vertical
  examples.
- Microsoft Learn connected animation and timing/easing:
  `https://learn.microsoft.com/en-us/windows/apps/develop/motion/connected-animation`
  and
  `https://learn.microsoft.com/en-us/windows/apps/design/motion/timing-and-easing`.
  Motion should preserve context, guide attention, and avoid raw linear motion.
- VectCutAPI:
  `https://github.com/sun-guannan/VectCutAPI`.
  The automation path must create editable CapCut/Jianying-style drafts, not
  only a flattened FFmpeg output.

Runtime enforcement:

- `worker/render/golden_reference_gate.py` fails golden/reference manifests
  without `postEditGoldenReference.capcutHandoff`.
- `ffmpegOnlyAllowed=true` is a hard failure.
- A candidate may still store FFmpeg preview MP4s, but it cannot be scored or
  presented as a final/upload candidate until the CapCut draft handoff exists.
- The CapCut draft must link source video, TTS, BGM, captions, and edit-element
  tracks when those layers are intentionally used. Clean editorial mode may
  have zero generated edit-element/effect/SFX tracks. This keeps the
  user-facing fix path editable inside CapCut instead of forcing another
  code-render loop for every caption, timing, sticker, SFX, or effect
  correction.
- The handoff must include web-backed `referenceBasis`, `automationSurface`,
  `editModel`, `motionDesign`, and `effectPass` objects. A draft folder without
  keyframed motion, easing, editable captions, editable audio, an explicit
  clean/effect-pass decision, and operator-export review is not enough.
- Raw FFmpeg `drawbox`/`drawtext` edit elements are preview aids only. They
  cannot be claimed as final-quality CapCut edit elements unless recreated as
  editable CapCut tracks.
- PNG/image overlays and native effect tracks are disabled by default for
  generated drafts. A clean editorial CapCut draft should lean on source
  keyframes, cut timing, editable captions, BGM balance, and operator review.
- Native effect tracks require manual selection and visual anchoring. Adding
  more effects, more families, or more template-looking presets is a negative
  signal when those effects do not match the source action, visible cue, or
  audio hit.

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
