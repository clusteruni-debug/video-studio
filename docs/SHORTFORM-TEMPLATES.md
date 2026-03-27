# Shortform Video Templates

> VectCutAPI (pyJianYingDraft) pipeline templates for automated CapCut draft generation.
> Each template specializes the Gemini scene-script prompt by content type.
> Ref: `worker/bridge/server.py` for the working pipeline.

---

## Pipeline Overview

```
User Prompt + template_type
  |
  v
Gemini 2.0 Flash (or template fallback)
  | template-specific system prompt
  v
Scene Script JSON  <-- this doc defines the schema
  |
  +---> TTS (Edge TTS / ElevenLabs / Google Cloud)
  |       -> ffprobe duration
  |
  +---> Image Router (emotion-based)
  |       Pexels   <- neutral, serious, sad
  |       Tenor    <- funny, shock, anger (GIF/MP4)
  |       DALL-E   <- origin_story (style-unified AI art)
  |       Pollinations FLUX <- fallback / free AI generation
  |
  v
VectCutAPI (pyJianYingDraft)
  | create_draft(1080, 1920)
  | add_image_impl per scene
  | add_text_impl per scene (display_text)
  | add_audio_track per scene (TTS)
  v
CapCut draft saved to ~/AppData/Local/CapCut/.../com.lveditor.draft/
  -> User opens CapCut, edits, exports
```

---

## Scene Script Schema

Gemini (or Claude) generates this JSON. The bridge server (`server.py`) consumes it.

```jsonc
{
  "template_type": "community_read | news_explainer | reddit_translation | ranking_list | origin_story",
  "topic": "original prompt or subject",
  "lang": "ko",
  "tts": {
    "provider": "edge",                // matches providers.py PROVIDERS key
    "voice": "ko-KR-SunHiNeural",     // matches providers.py VOICES["edge"]
    "speed": 1.05
  },
  "bgm_style": "lo-fi | tense | upbeat",
  "scenes": [
    {
      "scene_num": 1,
      "narration": "TTS reads this. Natural spoken sentence.",
      "display_text": "Screen subtitle.\nShort, bold, max 4 lines.",
      "image_prompt": "search query for Pexels/Tenor/DALL-E",
      "image_source": "pexels | tenor | dalle | pollinations",
      "emotion": "neutral | funny | serious | shock | sad | anger",
      "fallback_prompt": "alternate search query if primary fails",
      "transition": "Dissolve | Fade_In | none",
      "rank": null,
      "is_commentary": false
    }
  ]
}
```

### Field Reference

| Field | Source | Consumed By | Notes |
|-------|--------|------------|-------|
| `scene_num` | existing | server.py loop | Unchanged from current pipeline |
| `narration` | existing | `generate_tts()` | TTS input text |
| `display_text` | **new** | `add_text_impl(text=)` | If absent, falls back to `narration` |
| `image_prompt` | existing | `_search_pexels_image()` / Tenor / DALL-E | Search query |
| `image_source` | **new** | image router | Auto-set by emotion if omitted |
| `emotion` | **new** | image router | Determines source + search query style |
| `fallback_prompt` | **new** | image router | Tried when primary `image_prompt` returns no results |
| `transition` | **new** | `add_image_impl(transition=)` | VectCutAPI transition name |
| `rank` | **new** | ranking_list only | Integer rank number for display |
| `is_commentary` | **new** | reddit_translation only | Marks [commentary] slides for TTS tone shift |

### What the Schema Does NOT Include (and Why)

| Omitted | Reason |
|---------|--------|
| `duration_sec` | Computed at runtime: `ffprobe(tts_audio) + 0.5s` (server.py:288) |
| `aspect_ratio` | Always 9:16. Hardcoded in `create_draft(1080, 1920)` |
| `pause_between_slides_ms` | Controlled by `cumulative_time += dur` in server.py |
| `metadata` wrapper | Flat structure is simpler; bgm_style is top-level |

---

## TTS Engine Selection

Based on `worker/tts/providers.py` actual implementations.

| Provider | Key | Cost | Korean Quality | Best For |
|----------|-----|------|---------------|----------|
| Edge TTS | `edge` | Free | High | Default for all information-driven content |
| Google Cloud TTS | `google` | ~$4/1M chars | High (Wavenet) | Alternative free-tier-like option |
| ElevenLabs | `elevenlabs` | ~$0.003/sec | Good (slight accent) | Storytelling, emotional delivery |
| OpenAI TTS | `openai-tts` | ~$15/1M chars | Moderate | English-heavy content |

### Korean Voice Presets (Edge TTS)

| Voice ID | Gender | Tone | Recommended Template |
|----------|--------|------|---------------------|
| `ko-KR-SunHiNeural` | Female | News anchor, clear | community_read, ranking_list, reddit_translation |
| `ko-KR-InJoonNeural` | Male | Calm narrator | origin_story |
| `ko-KR-HyunsuNeural` | Male | Deep, authoritative | news_explainer |

---

## Image Source Routing

### Emotion-Based Auto-Routing

When `image_source` is omitted, the router selects based on `emotion`:

| Emotion | Primary Source | Search Strategy | Example Query |
|---------|---------------|-----------------|---------------|
| `neutral` | Pexels | Subject-related stock photo | `"office meeting room"` |
| `funny` | **Tenor** | Reaction GIF/MP4 | `"funny reaction meme"` |
| `serious` | Pexels | Dark-tone stock | `"storm clouds city"` |
| `shock` | **Tenor** | Surprised reaction | `"shocked reaction oh no"` |
| `sad` | Pexels | Melancholy stock | `"rain window alone"` |
| `anger` | **Tenor** | Frustrated reaction | `"angry reaction frustrated"` |

### Explicit Source Override

When `image_source` is specified:

| Source | API | Key Required | Format | Use Case |
|--------|-----|-------------|--------|----------|
| `pexels` | Pexels v1 | `PEXELS_API_KEY` | JPG | Stock photos, backgrounds, locations |
| `tenor` | Tenor v2 (Google) | `TENOR_API_KEY` | GIF/MP4 | Memes, reactions, humor |
| `dalle` | DALL-E 3 | `OPENAI_API_KEY` | PNG | Style-unified AI art (origin_story) |
| `pollinations` | Pollinations FLUX | None | PNG | Free AI generation fallback |

### Tenor Integration Notes

```
GET https://tenor.googleapis.com/v2/search
  ?q=shocked+reaction
  &key=TENOR_API_KEY
  &media_filter=mp4,gif
  &limit=3
  &contentfilter=medium
```

- Returns MP4 in `media_formats.mp4.url` — directly usable in VectCutAPI
- Korean keyword search supported: `q=놀란+반응` works
- Free tier: ~50 req/sec, no daily cap
- For video pipeline: prefer `mp4` format (smaller, no decoding overhead)
- GIF fallback: `media_formats.gif.url` if MP4 unavailable

### Image Prompt Generation Rules

These rules apply when Gemini/Claude generates `image_prompt` per scene:

1. **Named entity** (company, product, place) -> direct name search
   - `"삼성전자 본사"` -> `"Samsung Electronics headquarters building"`
2. **Action/situation** (meeting, commute, coding) -> situation stock
   - `"야근하는 직장인"` -> `"office worker late night overtime"`
3. **Emotion/reaction** (shock, disappointment, laughter) -> Tenor reaction search
   - `"충격받은 표정"` -> `"shocked face reaction"` (Tenor)
4. **Abstract concept** (growth, crisis, opportunity) -> metaphor image
   - `"경제 위기"` -> `"stock market crash graph red"`
5. **Historical scene** (origin_story template) -> DALL-E with style prompt
   - `"1980년대 일본 편의점"` -> DALL-E prompt with era-specific details

### DALL-E Prompt Convention (origin_story template)

When `image_source: "dalle"`, append this suffix to maintain visual consistency:

```
{image_prompt}, watercolor illustration style, clean background,
centered composition, no text, no letters, no words in image
```

Pick ONE style per video and apply to all scenes:
- `watercolor illustration style` — warm, storytelling feel
- `vintage photograph style, sepia tone` — historical/documentary
- `flat design infographic style, dark background` — tech/data topics

---

## Template 1: Community Post Reader

**Reference channels:** 아이반, 모르면손해, 오늘의이슈
**Platform:** YouTube Shorts, TikTok, Instagram Reels

### Gemini System Prompt

```
You are a Korean YouTube Shorts scriptwriter. Convert a community post into a narrated slideshow.

[Input]
- Original post text (title + body)
- Source platform (블라인드/에펨코리아/디시 etc.)

[Rules]

1. Text Splitting:
   Split the post into slides by meaning (3-5 lines each).
   - display_text: max 4 lines, max 12 chars per line. Screen subtitle.
   - narration: expand display_text into natural spoken Korean.
     Convert: "~음" -> "~습니다", remove "ㅋㅋ", "ㄹㅇ" -> "정말"
   Example:
     display_text: "넥슨도 신입 안 뽑는다는\n소문이 돌고 있음"
     narration: "넥슨도 신입을 안 뽑는다는 소문이 돌고 있습니다."

2. Image Selection:
   Set emotion per slide and generate image_prompt accordingly.
   - Company/brand mention -> company logo or building (Pexels)
   - Emotion expression -> reaction GIF (Tenor): emotion=funny/shock/anger
   - Abstract concept -> metaphor stock photo (Pexels): emotion=neutral/serious
   - Person reference -> occupation stock photo (never use real person photos)
   - Short transition sentence -> no image needed (image_prompt: null)

3. Output:
   Return JSON array of scenes. scene_num starts at 1.
   Each scene: { scene_num, narration, display_text, image_prompt, image_source, emotion, fallback_prompt, transition }
   - transition: "Dissolve" for all except first scene (use "Fade_In")
```

**TTS config:**
- voice: `ko-KR-SunHiNeural` (female) or `ko-KR-InJoonNeural` (male)
- speed: 1.05 (slightly fast for shorts retention)
- bgm_style: `lo-fi`

---

## Template 2: News/Fact Explainer

**Reference channels:** 슈카월드 shorts, 삼프로TV clips, 지식인사이드
**Platform:** YouTube Shorts, TikTok

### Gemini System Prompt

```
You are a Korean news explainer for YouTube Shorts. Structure one news topic into a clear 5-act breakdown.

[Input]
- News URL or summary text
- Tone: calm_analysis | urgent_warning | casual_explainer

[Rules]

1. Script Structure (strict 5-act):
   - Hook (scene 1): Shocking fact or question. "알고 계셨나요?"
   - Context (scenes 2-3): Background explanation
   - Core (scenes 4-5): Key facts, data, numbers
   - Implication (scene 6-7): Impact, future outlook
   - CTA (scene 8): "어떻게 생각하시나요?" + follow prompt

   display_text rules:
   - Key numbers/keywords on separate line (large font in CapCut)
   - Max 3 lines per slide
   - One sentence max 15 chars per line

2. Image Selection:
   - Hook: Strong subject image, emotion=shock or serious
     e.g. "stock market crash graph red arrow" (Pexels)
   - Context: Institution buildings, maps, infographic-style
     e.g. "korean central bank building" (Pexels)
   - Core: Data visualization or DALL-E generated
     DALL-E prompt: "minimalist infographic, dark background, showing [concept], flat design, no text"
   - Implication: Future/outlook imagery
     e.g. "futuristic city skyline" (Pexels)
   - CTA: Channel-related or subscribe prompt image

3. SSML Enhancement:
   Insert pause before emphasis words in narration:
   "[0.3초 pause] 무려 30조 원입니다."
   -> The bridge should convert this to edge-tts SSML <break time="300ms"/>

4. Output: JSON array of scenes with emotion tags.
```

**TTS config:**
- voice: `ko-KR-HyunsuNeural` (male, authoritative)
- speed: 1.0 (explainer needs trust-building pace)
- bgm_style: `tense`

---

## Template 3: Foreign Community Translation Reader

**Reference channels:** 영미권사건사고, 레딧읽어주는남자, 해외반응
**Platform:** YouTube (Shorts + mid-form 5-10min)

### Gemini System Prompt

```
You are a Korean translator for foreign community posts (Reddit, Quora, 2ch, X).
Translate and structure into a narrated slideshow with cultural commentary.

[Input]
- Original text (English/Japanese/etc.) or URL
- Source platform (Reddit, Quora, 2ch, X)
- Translation tone: faithful | liberal_with_commentary | humor_emphasis

[Rules]

1. Translation + Slide Splitting:
   - Translate naturally (no literal translation)
   - Insert [commentary] slides where cultural context is needed
     Example:
       Original: "Karen at the HOA meeting"
       -> Translation slide: "동네 입주자 대표 회의에서 한 아줌마가"
       -> [Commentary] slide:
          display_text: "참고: 미국 HOA는\n한국 입주자대표회의\n비슷한 건데\n규제가 훨씬 강함"
          narration: "참고로 미국에서 HOA는 한국의 입주자대표회의 비슷한 건데, 규제가 훨씬 강해서 잔디 색깔까지 간섭합니다."
          is_commentary: true

   - Replace Reddit jargon with Korean explanations:
     "NTA" -> "넌 잘못 없음", "YTA" -> "넌 잘못", "AITA" -> "내가 잘못한 건가요?"

2. Image Selection:
   - Story slides: Situation-relevant stock (Pexels)
     e.g. "suburban neighborhood houses" for HOA stories
   - Reaction slides: English-language reaction GIF (Tenor)
     e.g. "this is fine meme", "facepalm reaction"
   - [Commentary] slides: Real photo of the subject being explained
     e.g. HOA explanation -> "american suburban front yard lawn" (Pexels)

3. Scene Fields:
   [Commentary] slides must set is_commentary: true
   This triggers TTS tone shift: speed 0.95, pitch adjustment

4. Narration style: "~인데요", "~거든요" conversational endings.

5. Output: JSON array of scenes. is_commentary field required.
```

**TTS config:**
- voice: `ko-KR-SunHiNeural` (female)
- speed: 1.0 (normal slides), 0.95 (commentary slides)
- bgm_style: `lo-fi`

---

## Template 4: Top-N Ranking / List

**Reference channels:** 알아두면쓸모있는, 지식브런치, 랭킹스쿨
**Platform:** YouTube Shorts, TikTok

### Gemini System Prompt

```
You are a Korean YouTube Shorts writer for ranking/list content.
Structure a "Top N" or "N가지 ~" format video.

[Input]
- Topic: e.g. "직장인이 모르면 손해보는 정부 지원금 5가지"
- Items: list of (name + 1-2 line description)
- Sort direction: ascending (5->1) or descending (1->5)

[Rules]

1. Script Structure:
   - Intro (1 scene): Hook question + topic
     "직장인인데 이거 모르면 진짜 손해입니다."
   - Per item (2 scenes each):
     Scene A: Rank number + item name (large text, rank field set)
       display_text: "3위\n청년 주거 지원금"
       rank: 3
     Scene B: Key explanation (max 3 lines)
       display_text: "월 최대 20만원\n만 19~34세\n소득 기준 충족 시"
   - Outro (1 scene): Summary or "저장해두세요" CTA

2. Image Selection:
   - Rank number scenes: Representative image of that item
     e.g. "apartment keys young person" for housing support (Pexels)
   - Explanation scenes: Specific detail image
     e.g. "korean government document form" (Pexels)
   - Intro: Topic-wide representative image
   - Outro: Checklist/completion imagery

3. SSML Enhancement:
   Pause before rank numbers in narration:
   "[0.5초 pause] 3위. [0.3초 pause] 청년 주거 지원금입니다."

4. Output: JSON array. rank field required on rank-number scenes.
   transition: "Slide_Left" for rank transitions.
```

**TTS config:**
- voice: `ko-KR-SunHiNeural` (female)
- speed: 1.1 (list format benefits from slightly faster tempo)
- bgm_style: `upbeat`

---

## Template 5: Origin / History Storytelling

**Reference channels:** 설명왕침착맨 shorts, 별별역사, 피식대학 AI clips
**Platform:** YouTube Shorts, TikTok

### Gemini System Prompt

```
You are a Korean storyteller for origin/history short-form videos.
Structure a "birth story" or "why is X like this?" narrative.

[Input]
- Topic: e.g. "편의점 삼각김밥이 처음 등장한 이유"
- Key timeline (3-5 events with years)
- Tone: serious_documentary | casual_trivia | twist_humor

[Rules]

1. Script Structure (narrative arc):
   - Hook (scene 1): Unexpected fact to spark curiosity
     "삼각김밥은 원래 일본 편의점에서 만든 게 아닙니다."
   - Origin (scenes 2-3): How it began
   - Turning Point (scenes 4-5): The pivotal change
   - Now (scenes 6-7): Current state
   - Punchline (scene 8): Closing insight or humor

   Narration style: storytelling ("~였는데요", "~했다고 합니다")

2. Image Selection (DALL-E primary):
   All scenes use image_source: "dalle" with unified style.
   Pick ONE style for entire video:
   - "watercolor illustration style" (warm storytelling)
   - "vintage photograph style, sepia tone" (historical)

   DALL-E prompt rules:
   - Always end with: "clean background, centered composition, no text, no letters"
   - Reflect era in clothing/setting: "1980s Japanese convenience store interior, warm lighting"
   - Single subject, simple composition

   Example prompts:
   Hook: "watercolor illustration, surprised person looking at triangular rice ball, clean background, no text"
   Origin: "watercolor illustration, 1980s Japanese convenience store interior, warm lighting, vintage feel, no text"
   Turning Point: "watercolor illustration, Korean businessman examining food product, 1990s office, no text"

3. Output: JSON array. All scenes should have image_source: "dalle".
   transition: "Dissolve" (story continuity).
```

**TTS config:**
- voice: `ko-KR-InJoonNeural` (male storyteller)
- speed: 0.95 (storytelling needs breathing room)
- bgm_style: `lo-fi` (serious) or `upbeat` (casual)

---

## Image Search Module

Shared logic across all templates. Implemented as a function in the bridge server.

### Input
- `image_prompt`: search query from scene
- `emotion`: emotion tag from scene
- `image_source`: explicit source override (optional)
- `fallback_prompt`: alternate query

### Routing Logic

```
if image_source is explicitly set:
    use that source directly
else:
    if emotion in (funny, shock, anger):
        source = tenor
    elif emotion in (neutral, serious, sad):
        source = pexels
    else:
        source = pexels
```

### Search Priority per Source

**Pexels** (stock photos):
1. Search `image_prompt` with `orientation=portrait`
2. If no results, search `fallback_prompt`
3. If still no results, return None (scene gets text-only card)

**Tenor** (meme/reaction GIF):
1. Search `image_prompt` with `media_filter=mp4,gif&limit=3`
2. Pick first result, prefer `mp4` format
3. If no results, search `fallback_prompt`
4. If still no results, fall back to Pexels with same query

**DALL-E** (AI art):
1. Append style suffix to `image_prompt`
2. Generate at 1024x1024
3. On API failure, fall back to Pollinations FLUX with same prompt

**Pollinations FLUX** (free AI fallback):
1. Generate from `image_prompt`
2. Rate-limited (~90s between requests, see `pollinations-rate-limit.json`)
3. Last resort before text-only card

### Quality Filters
- Minimum resolution: 900x900 (for 9:16 crop)
- Pexels: request `portrait` orientation for better 9:16 fit
- Tenor: prefer `mp4` over `gif` (smaller size, better for VectCutAPI)

---

## VectCutAPI Integration Map

How the scene schema maps to actual VectCutAPI calls in `server.py`:

| Scene Field | VectCutAPI Call | Parameter |
|-------------|----------------|-----------|
| image (resolved URL) | `add_image_impl()` | `image_url`, `start`, `end` |
| display_text | `add_text_impl()` | `text`, `transform_y=-0.75` |
| narration (TTS audio) | `add_audio_track()` | `audio_url`, `target_start` |
| transition | `add_image_impl()` | `transition=`, `transition_duration=0.7` |
| rank (display) | `add_text_impl()` | `font_size=18.0` (larger for rank number) |

### Scene Assembly Order (per scene)

```python
# 1. Background image FIRST (behind text)
add_image_impl(
    image_url=resolved_image_url,
    width=1080, height=1920,
    start=cumulative_time,
    end=cumulative_time + dur,
    scale_x=1.3, scale_y=1.3,      # room for Ken Burns
    relative_index=0,                # behind text
    intro_animation="Fade_In",
    transition=scene["transition"],  # "Dissolve" / "Fade_In" / None
    transition_duration=0.7,
)

# 2. Text subtitle (bottom area)
add_text_impl(
    text=scene.get("display_text") or scene["narration"],
    start=cumulative_time,
    end=cumulative_time + dur,
    font_size=12.0,                  # 18.0 for rank numbers
    transform_y=-0.75,               # near bottom
    fixed_width=0.85,
    border_width=0.12,               # black stroke for readability
    intro_animation="Fade_In",
)

# 3. Audio narration
add_audio_track(
    audio_url=tts_url,
    target_start=cumulative_time,
    duration=tts_duration,
)

cumulative_time += tts_duration + 0.5  # 0.5s padding
```

---

## Cost Estimation per Template

Assuming 8-scene video, free-tier defaults:

| Template | TTS | Image | Total |
|----------|-----|-------|-------|
| community_read | Free (Edge) | Free (Pexels + Tenor) | **$0** |
| news_explainer | Free (Edge) | Free (Pexels) + ~2 DALL-E ($0.08) | **~$0.08** |
| reddit_translation | Free (Edge) | Free (Pexels + Tenor) | **$0** |
| ranking_list | Free (Edge) | Free (Pexels) | **$0** |
| origin_story | Free (Edge) | 8x DALL-E ($0.32) | **~$0.32** |

With premium TTS (ElevenLabs, ~45sec total):
- Add ~$0.14 per video

Monthly estimate (30 videos):
- All-free templates: **$0/month**
- origin_story daily: **~$9.60/month** (DALL-E)
- Mixed (20 free + 10 origin_story): **~$3.20/month**
