# Codex Task Backlog — Video Studio App

> Generated: 2026-03-17 Session 17
> These tasks are suitable for Codex (pure code changes, no runtime/env dependency).
> CC reviews all Codex output before merging.

---

## CX-1: Fix `render.ts` hardcoded "piper" audio provider

**Priority**: HIGH
**File**: `shared/contracts/render.ts` line 128
**Effort**: Trivial (1 line)

### Problem
The TypeScript manifest builder still hardcodes `"piper"` as the audio provider name.
The Python side (`worker/render/render_manifest.py`) was already fixed to use `"edge-tts"`.
This means browser-built manifests and bridge-built manifests disagree on the TTS provider field.

### Change
```typescript
// Before (line 128)
provider: audioKind === "native" ? route : "piper",

// After
provider: audioKind === "native" ? route : "edge-tts",
```

### Verification
- `npx tsc --noEmit` must pass
- `npm run build` must pass
- Grep the entire project for `"piper"` — should return zero hits

---

## CX-2: Wire `select_provider()` into the render pipeline or delete it

**Priority**: HIGH
**File**: `worker/media/provider_policy.py` (lines 21-90)
**Effort**: Medium

### Problem
`select_provider()` is a well-designed function that picks the best adapter per category
with free-first logic and manual approval support. However, it is **dead code** — no file
in the project calls it.

Currently, provider selection in the render pipeline happens via:
- `worker/media/runtime.py` → `_pick_adapter_for_scene()` (simple preference-list fallback)
- `worker/media/model_router.py` → `choose_route()` (sora2/veo3/local routing only)

### Option A: Integrate (Recommended)
Replace `_pick_adapter_for_scene()` in `runtime.py` with a call to `select_provider()`.
This gives the pipeline free-first logic + per-scene manual approval support.

Steps:
1. In `worker/media/runtime.py`, import `select_provider` from `provider_policy`
2. In `generate_local_visual_asset()` (or its caller), replace the existing adapter
   selection logic with `select_provider(category, scene_id, adapters, budget_mode, approvals)`
3. Pass `budget_mode` and `approvals` through from the bridge request payload
4. Ensure `compose_smoke_render()` passes these parameters down

### Option B: Delete
If integration is too complex, delete `select_provider()` and the dead code around it.
Keep `estimate_scene_cost()` and `estimate_project_cost()` (these ARE used via model_router.py).

### Verification
- `python -m compileall worker` must pass
- If Option A: add a simple unit test that calls `select_provider("image", "s01", adapters, "free")`
  and confirms it returns `"pollinations"` when that adapter is ready

---

## CX-3: Create SFX adapter scripts

**Priority**: MEDIUM
**Files**: New files `scripts/local_sfx.py` and `scripts/freesound_sfx.py`
**Effort**: Medium

### Problem
`worker/media/adapters.py` registers two SFX adapters:
- `local-sfx` (line 154): `costTier: "free"`, expects a command adapter
- `freesound` (line 145): `costTier: "free"`, expects a command adapter

Neither script file exists. The adapter config references them but render will skip SFX silently.

### Requirements

**`scripts/local_sfx.py`**
Follow the same pattern as `scripts/edge_tts.py`:
- `argparse` with `--prompt-path` and `--output-path`
- Read prompt text from `--prompt-path` (contains scene mood/description)
- Scan `assets/sfx/` directory for `.wav`/`.mp3` files
- Pick a file by keyword match against the prompt, or random if no match
- Copy the selected file to `--output-path`
- Exit 0 on success, non-zero on failure
- Print selected filename to stderr for logging

**`scripts/freesound_sfx.py`**
Follow the same pattern as `scripts/dalle3_image.py`:
- `argparse` with `--prompt-path` and `--output-path`
- Read prompt text from `--prompt-path`
- Call Freesound API: `https://freesound.org/apiv2/search/text/?query=...&token=...`
- Requires `FREESOUND_API_KEY` env var
- Download the first matching sound preview
- Write to `--output-path`
- Retry/backoff pattern from `pollinations_flux.py` (simplified: 2 attempts max)
- Exit 0 on success, non-zero on failure

### Reference Files
- `scripts/edge_tts.py` — local adapter pattern
- `scripts/pollinations_flux.py` — API adapter pattern with retry
- `scripts/dalle3_image.py` — paid API adapter pattern

### Verification
- `python -m py_compile scripts/local_sfx.py` must pass
- `python -m py_compile scripts/freesound_sfx.py` must pass
- Create `assets/sfx/` directory with at least one placeholder `.wav` file
- Run: `python scripts/local_sfx.py --prompt-path test-prompt.txt --output-path test-out.wav`
  → should copy a file from assets/sfx/ to test-out.wav

---

## CX-4: Set up test infrastructure + core unit tests

**Priority**: MEDIUM
**Files**: New test files, `pyproject.toml` or `pytest.ini`, `vitest.config.ts`
**Effort**: Large

### Problem
The project has **zero test coverage**. No test framework is installed on either the
Python or TypeScript side. 18 adapters, 847-line renderer, 356-line planner — all untested.

### Requirements

**Python side (pytest)**
1. Add `pytest` to requirements or install in venv
2. Create `tests/` directory at project root
3. Write these unit tests:

```
tests/test_adapters.py
  - test_probe_returns_all_18_adapters()
  - test_free_adapters_by_category_returns_correct_keys()
  - test_adapter_config_has_required_fields()

tests/test_provider_policy.py
  - test_select_provider_free_mode_returns_free_adapter()
  - test_select_provider_with_approval_returns_approved()
  - test_estimate_scene_cost_image()
  - test_estimate_scene_cost_tts()
  - test_estimate_project_cost_total()

tests/test_render_manifest.py
  - test_build_render_manifest_sets_motion_preset()
  - test_build_render_manifest_sets_transition_type()
  - test_manifest_audio_provider_is_edge_tts()

tests/test_motion.py
  - test_all_presets_return_valid_filter_string()
  - test_random_preset_returns_one_of_known()

tests/test_transitions.py
  - test_xfade_filter_returns_valid_string()
  - test_gradient_background_returns_filter()
```

**TypeScript side (vitest)**
1. Add `vitest` as devDependency in `app/ui/package.json`
2. Create `app/ui/src/__tests__/` directory
3. Write these tests:

```
app/ui/src/__tests__/shared.test.ts
  - test mediaAdapterTitle returns Korean name for all 16 known keys
  - test mediaAdapterTitle returns fallback for unknown key
  - test budgetModeLabel returns correct Korean for each mode
  - test routeLabel returns correct names
  - test formatUsd formats correctly

app/ui/src/__tests__/planner.test.ts
  - test buildStudioProjectRecord returns valid record
  - test record has correct number of scenes
  - test routes match budget mode
```

### Verification
- `pytest tests/ -v` must pass all tests
- `npx vitest run` must pass all tests
- No test should depend on network calls or running services

---

## CX-5: Per-scene provider selection dropdown in StoryboardPanel

**Priority**: MEDIUM
**Files**: `app/ui/src/components/StoryboardPanel.tsx`, `app/ui/src/components/shared.ts`
**Effort**: Medium-Large

### Problem
The plan (Phase 5b) calls for per-scene provider selection dropdowns in the storyboard,
but the current `StoryboardPanel.tsx` only shows scene cards with asset upload slots.
There is no way for users to choose which provider generates each scene's image/video/TTS.

### Requirements

1. **Add provider dropdown per scene card** for these categories:
   - Image: show available image providers with cost
   - TTS: show available TTS providers with cost
   - Video: show available video providers with cost (only if video route)

2. **Dropdown options format**:
   ```
   Pollinations FLUX (무료)        ← free, default selected
   DALL-E 3 ($0.04/장)            ← paid, grayed unless API key configured
   Imagen 3 ($0.02/장)            ← paid, grayed unless API key configured
   ```

3. **State management**:
   - Add `providerSelections: Record<string, Record<string, string>>` state to App.tsx
     - Key: `{sceneId}`, Value: `{category: providerKey}`
   - Pass down to StoryboardPanel as prop
   - On dropdown change, update the selections state
   - Pass selections to bridge on save/render

4. **Cost preview**:
   - Use `estimate_scene_cost()` values from `shared/contracts/render.ts` or hardcode
     the cost table from `adapters.py` ADAPTER_CONFIG
   - Show per-scene cost badge: "₩0" or "$0.04"
   - Show total cost in ExecutionPanel summary bar

5. **Styling**:
   - Use existing `styles.css` patterns (`.scene-card` class)
   - Dropdown: native `<select>` is fine, no need for custom component
   - Disabled/grayed options for providers without API keys

### Reference
- `adapterTitles` in `shared.ts` — Korean display names for all 16 providers
- `ADAPTER_CONFIG` in `worker/media/adapters.py` — costPerUnit values
- `estimate_scene_cost()` in `worker/media/provider_policy.py` — cost calculation logic

### Verification
- `npm run build` must pass
- Dropdown must show at least 1 option per category
- Selecting a paid provider should show non-zero cost badge
- Default selection should always be the free provider

---

## Execution Priority

```
CX-1  (trivial, HIGH)   → do first, 1 line fix
CX-2  (medium, HIGH)    → wire select_provider or delete dead code
CX-4  (large, MEDIUM)   → test infra — biggest long-term value
CX-3  (medium, MEDIUM)  → SFX scripts — extends adapter coverage
CX-5  (large, MEDIUM)   → UI feature — depends on CX-2 being resolved first
```

## Notes
- All tasks are pure code changes — no runtime environment or API keys needed
- CC will review and merge all Codex output
- Run `python -m compileall worker scripts` and `npm run build` after each task
- Do NOT modify `.env` or `.env.example` unless adding new env var keys for SFX
