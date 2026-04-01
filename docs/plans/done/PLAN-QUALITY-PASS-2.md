# Video Studio Quality Pass 2 — User Feedback Sprint

## Context

Session 7+12 delivered pipeline overhaul (duration, grounding, Brand Kit, Imagen 4, ASS highlight, 3 TTS).
User tested the draft in CapCut and identified 6 remaining issues:

1. **BGM missing** — CapCut says "미디어를 못 찾겠다"
2. **Layout identical across templates** — Brand Kit params too subtle
3. **Subtitles too abbreviated** — display_text over-compressed, meaning unclear
4. **TTS speed** — still too slow for shorts pacing
5. **Images generic** — Pexels stock, Imagen 4 not triggered
6. **No user editing** — need scene-level image upload + text edit in UI

## Fixes

### F1: BGM Media Not Found (CRITICAL BUG)

**Root cause**: `server.py` passes absolute local path to `vb_add_bgm()`, but BGM file is never copied into `draft/assets/audio/`. CapCut can't find it.

**Fix**: In `save_draft_to_capcut()` (vectcut_bridge.py), copy BGM file into draft assets — same pattern as TTS audio copy at lines 274-282.

```python
# After TTS copy block, add BGM copy:
if bgm_path and Path(bgm_path).exists():
    bgm_material = f"audio_{_hash(bgm_path)}.{Path(bgm_path).suffix.lstrip('.')}"
    shutil.copy2(bgm_path, str(audio_dest / bgm_material))
```

Also need to pass `bgm_path` through to `save_draft_to_capcut()`.

**Files**: `worker/bridge/server.py`, `worker/bridge/vectcut_bridge.py`

### F2: Layout Needs Dramatic Differences

**Problem**: scale 1.3 vs 1.4 is invisible. Need structurally different layouts per template.

**Approach**: Instead of subtle parameter tweaks, create DISTINCT scene compositions:

| Template | Image Layout | Text Layout |
|----------|-------------|-------------|
| news_explainer | Full bg + blur(3) | Bottom bar, white on dark semi-transparent |
| hot_take | Full bg, high contrast | Center, large yellow text, red accent bg |
| ranking_list | Left 60% image | Right 40% rank number + text overlay |
| community_read | Top half image (post screenshot style) | Bottom half, speech bubble aesthetic |
| reddit_translation | Split: original top, translation bottom | Smaller text, two-tone |
| origin_story | Full cinematic, Ken Burns zoom | Centered serif-style, fade transitions |
| vs_comparison | Split screen (left vs right) | Labels on each side |
| myth_buster | Full bg, "X" or "O" overlay on verdict | Center, verdict reveal style |
| tutorial_steps | Screen recording style (smaller, centered) | Step counter top-left, instruction bottom |
| before_after | Split horizontal (before top, after bottom) | "Before"/"After" labels |

**Implementation**: Use VectCutAPI's capabilities:
- `transform_x/y` for positioning (not just centering)
- `mask_type=Rectangle` with offset for split layouts
- Multiple `add_text` calls per scene (title + body)
- Different `track_name` for layered elements

**Files**: `worker/bridge/server.py` (scene building loop), `worker/bridge/vectcut_bridge.py` (add helper functions for split layouts)

### F3: Subtitle = Full Narration (Not Abbreviated)

**Problem**: display_text extracts key phrase from narration → too compressed → meaning unclear.

**Fix**: Use narration directly as CapCut subtitle. display_text keeps its role for the FFmpeg render path only.

```python
# server.py, subtitle section:
subtitle_text = scene["narration"]  # was: scene.get("display_text") or scene["narration"]
```

For CapCut, full narration is better — users can shorten in CapCut if needed.
Keep display_text generation for the FFmpeg quick-render path where shorter text makes sense.

**Files**: `worker/bridge/server.py`

### F4: TTS Speed

**Current**: `+10%` rate. Shorts typically use `+25%` to `+35%`.

**Fix**: Increase default to `+25%`, commentary to `+15%`.

**Files**: `worker/bridge/server.py`

### F5: Imagen 4 Not Triggered

**Problem**: LLM outputs `image_source: "pexels"` for every scene → auto-route never reaches Imagen 4.

**Fix two-pronged**:
1. Remove `"image_source": "pexels"` from `_JSON_FORMAT` template — let auto-route decide
2. In auto-route: try Imagen 4 FIRST for all non-reaction scenes, Pexels as fallback

**Files**: `worker/bridge/templates.py`, `worker/bridge/image_router.py`

### F6: Scene-Level Editing UI (Frontend)

**New features needed in the React UI**:

1. **Scene image upload**: In SceneDetailPanel, add file input to upload custom image per scene
   - Store in StudioContext per-scene state
   - On save/render, upload to `storage/inputs/{project}/uploads/`
   - Pass to bridge as scene override

2. **Scene text editing**: Inline edit narration + display_text per scene
   - Already partially exists in StoryboardPanel (inline edit)
   - Extend to support narration editing (currently only scene title)
   - Changes should regenerate TTS for that scene

3. **Scene TTS preview**: Play button per scene to hear the TTS audio
   - Already have `_tts_url` — add audio player in scene card

4. **Image source toggle enhancement**:
   - Current: Pexels / FLUX toggle
   - Add: "Upload" option + "AI Generate" (Imagen 4)
   - Show image preview in scene card

**Files**:
- `app/ui/src/components/SceneDetailPanel.tsx`
- `app/ui/src/components/StoryboardPanel.tsx`
- `app/ui/src/context/StudioContext.tsx`
- `app/ui/src/lib/bridge.ts`
- `worker/bridge/server.py` (new endpoint: POST /api/regenerate-scene-tts)

## Priority Order

| # | Task | Type | Effort |
|---|------|------|--------|
| F1 | BGM file copy | Bug fix | 30 min |
| F3 | Subtitle = full narration | Config change | 5 min |
| F4 | TTS speed +25% | Config change | 5 min |
| F5 | Imagen 4 auto-route | Backend fix | 30 min |
| F2 | Layout structural differences | Backend | 2-3 hours |
| F6 | Scene editing UI | Frontend | 3-4 hours |

## Verification

After F1-F5:
1. Create draft → open in CapCut → BGM plays ✅
2. Each template type produces visibly different layout ✅
3. Subtitles match spoken audio word-for-word ✅
4. TTS pacing feels natural for shorts ✅
5. AI-generated images (not stock) appear in draft ✅

After F6:
1. Upload custom image for scene 3 → appears in CapCut draft ✅
2. Edit narration → TTS regenerates with new text ✅
3. Preview TTS audio per scene in browser ✅
