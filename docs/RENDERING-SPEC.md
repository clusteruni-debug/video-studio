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

- Narration segments: BGM volume = **-18dB** (sidechain ducking)
- Non-narration segments (transitions, intro): BGM volume = **-8dB**
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
  -filter_complex "[0:a]asplit=2[narr][sc];[sc]aformat=channel_layouts=mono,compand=attacks=0:decays=0.3:points=-80/-80|-45/-45|-27/-30|0/-30,aformat=channel_layouts=stereo[sidechain];[1:a][sidechain]sidechaincompress=threshold=0.02:ratio=6:attack=10:release=300:level_sc=1[bgm_ducked];[narr][bgm_ducked]amix=inputs=2:duration=first[out]" \
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

## 6. FFmpeg Final Composition Command (Reference)

```bash
ffmpeg -y \
  -f concat -safe 0 -i scene_list.txt \
  -i mixed_audio.wav \
  -vf "ass=subtitle.ass" \
  -c:v libx264 -preset medium -crf 23 \
  -c:a aac -b:a 128k \
  -r 30 -s 1080x1920 \
  -movflags +faststart \
  output.mp4
```

**Important**: Use `ass=` filter, NOT `subtitles=` filter, to fully apply ASS styles.

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

---

## 8. CLAUDE.md Integration

This document's specs must be reflected in these files:

| File | Content |
|------|---------|
| `worker/render/compose.py` | §6 FFmpeg composition, §5.3 Ken Burns |
| `worker/render/subtitle.py` (new) | §2 ASS styles, §3 karaoke generation |
| `worker/render/bgm.py` (new) | §4 BGM matching + mixing |
| `worker/media/adapters.py` | §5.2 Pexels video search addition |
| `app/ui/src/lib/constants.ts` | §2.2 Preset names synced with UI labels |
| `shared/contracts/plan.ts` | Add bgm_mood field to Scene type |

**When Claude Code modifies the above files, code that does not follow this document's values is rejected.**
