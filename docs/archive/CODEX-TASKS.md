# Codex Task Backlog — Video Studio App

> Generated: 2026-03-17 Session 17
> Revised: 2026-03-17 — CC review pass (scope/accuracy corrections per Codex audit)
> CC reviews all Codex output before merging.

---

## CX-1: Fix `render.ts` hardcoded "piper" audio provider

**Status**: DONE (CC applied directly, Session 18)
**Priority**: HIGH
**File**: `shared/contracts/render.ts` line 128
**Effort**: Trivial (1 line)

### Change Applied
```typescript
// Before
provider: audioKind === "native" ? route : "piper",
// After
provider: audioKind === "native" ? route : "edge-tts",
```

### Verification (passed)
- `npx tsc --noEmit` — passed
- Grep `"piper"` across `*.ts *.tsx *.py` — zero hits

---

## CX-2: Delete dead `select_provider()` and `estimate_project_cost()`

**Priority**: HIGH
**Scope**: Single file — `worker/media/provider_policy.py`
**Effort**: Small
**Prerequisite**: None

### Problem
`select_provider()` (lines 21-90) is dead code — no file in the project calls it.
`estimate_project_cost()` (lines 116-156) is also dead code — `model_router.py` has
its own `estimate_project_costs()` (plural) which calls `estimate_scene_cost()` directly.

The previous version of this task incorrectly stated:
- ~~`_pick_adapter_for_scene()` exists in runtime.py~~ — it does not exist
- ~~`estimate_project_cost()` is used via model_router.py~~ — model_router.py defines its own `estimate_project_costs()` (different function)
- ~~Option A (integrate) is a medium, single-file change~~ — integration would require bridge payload changes across 5+ files

### Change
Delete `select_provider()` (lines 21-90) and `estimate_project_cost()` (lines 116-156)
from `worker/media/provider_policy.py`. Keep:
- `estimate_scene_cost()` (lines 93-113) — actively used by `model_router.py`
- `DEFAULT_PREFERENCE` dict (lines 12-18) — useful reference, no harm

### Files Modified
- `worker/media/provider_policy.py` — remove 2 functions

### Verification
- `python -m compileall worker` must pass
- `grep -r "select_provider\|estimate_project_cost" worker/ --include="*.py"` — only the definition file should remain (now deleted)
- `grep -r "estimate_scene_cost" worker/ --include="*.py"` — must still show imports in `model_router.py`

---

## CX-3: Add SFX role to render pipeline (full vertical slice)

**Status**: DONE (CC implemented directly, Session 19)
**Priority**: MEDIUM
**Effort**: Large (multi-file)
**Prerequisite**: CC approval — this is a feature addition, not a standalone script task

### Problem (corrected)
The previous version stated "SFX scripts are missing so render silently skips SFX."
This was inaccurate. The real issue is deeper:

1. `RenderAssetRole` in `shared/contracts/render.ts:3` = `"visual" | "audio" | "subtitle"` — **no "sfx" role**
2. `compose.py:554-556` only looks up `visual`, `audio`, `subtitle` assets — **no SFX lookup**
3. `render_manifest.py` and `render.ts` `buildRenderManifest()` never create SFX assets

Creating adapter scripts alone (local_sfx.py, freesound_sfx.py) would produce files
that nothing in the pipeline consumes. The adapter configs in `adapters.py:145-162`
are forward declarations with no downstream wiring.

### Correct Scope (if we decide to implement)
1. **Contract**: Add `"sfx"` to `RenderAssetRole` in `shared/contracts/render.ts`
2. **Manifest builders**: Add SFX asset creation in both `render.ts:buildRenderManifest()` and `worker/render/render_manifest.py:build_render_manifest()`
3. **Compositor**: Add SFX asset lookup + audio mixing in `worker/render/compose.py`
4. **Adapter scripts**: Create `scripts/local_sfx.py` (local library) and optionally `scripts/freesound_sfx.py` (API, requires `FREESOUND_API_KEY`)
5. **Assets**: Create `assets/sfx/` directory with placeholder files

### Notes
- `freesound_sfx.py` requires `FREESOUND_API_KEY` env var — contradicts the old header claim of "no runtime/env dependency"
- `local_sfx.py` requires `assets/sfx/` test files
- This is NOT a Codex-suitable task in its current form — too many cross-layer changes.
  Split into sub-tasks or handle as CC task.

### Recommendation
**Defer** until the core pipeline is more stable. If needed sooner, CC should handle
the contract/compositor changes and only delegate the adapter scripts to Codex.

---

## CX-4: Set up Python test infrastructure + core unit tests

**Status**: DONE (CC implemented directly, Session 19 — 16 tests all passing)
**Priority**: MEDIUM
**Effort**: Medium
**Prerequisite**: **User approval for `pytest` dependency** (AGENTS.md rule 2: "Do not add or remove dependencies without explicit approval")

### Problem
Zero test coverage on the Python side. 18 adapters, 847-line renderer, 356-line planner — all untested.

### Corrected Scope (Python only)
The previous version included TypeScript/vitest tests referencing `app/ui/package.json`,
which does not exist. The actual package.json is at project root. TypeScript tests are
deferred to a separate task after path correction.

**Python side (pytest)**
1. Add `pytest` to a `requirements-dev.txt` (requires user approval per AGENTS.md)
2. Create `tests/` directory at project root
3. Write these unit tests:

```
tests/test_adapters.py
  - test_adapter_config_has_required_fields()
  - test_free_adapters_by_category_returns_correct_keys()
  - test_categories_constant_matches_config()

tests/test_provider_policy.py
  - test_estimate_scene_cost_image_free()
  - test_estimate_scene_cost_tts_paid()
  - test_estimate_scene_cost_zero_for_free_provider()

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

### Removed from scope
- ~~`test_select_provider_*`~~ — `select_provider()` is dead code (CX-2 deletes it)
- ~~`test_estimate_project_cost_total`~~ — function is dead code (CX-2 deletes it)
- ~~TypeScript/vitest tests~~ — deferred; `app/ui/package.json` path does not exist

### Verification
- `pytest tests/ -v` must pass all tests
- No test should depend on network calls or running services
- `python -m compileall worker` must still pass

---

## CX-5: Per-scene provider selection dropdown (full-stack feature)

**Status**: DONE (CC implemented directly, Session 19)
**Priority**: LOW (downgraded — depends on multiple prerequisites)
**Effort**: Large (5+ files)
**Prerequisites**:
- CX-2 must be resolved (dead code cleaned up)
- Bridge payload contract must be extended first

### Problem (corrected scope)
The previous version listed only 2 files (`StoryboardPanel.tsx`, `shared.ts`).
The actual change requires modifying the save/render request contract end-to-end:

### Full File List
1. **`app/ui/src/App.tsx`** — Add `providerSelections` state, pass to bridge calls (lines ~284, ~327)
2. **`app/ui/src/components/StoryboardPanel.tsx`** — Add provider dropdown per scene card
3. **`app/ui/src/components/shared.ts`** — Add cost display helpers
4. **`app/ui/src/lib/bridge.ts`** — Add `providerSelections` field to `saveProjectWithBridge` and `renderSmokeWithSSE` request types (lines ~200, ~242)
5. **`worker/bridge/server.py`** — Accept and forward `providerSelections` in `_handle_save_project` and `_handle_render_smoke` (lines ~152, ~192)
6. **`worker/render/compose.py`** or pipeline entry — Use `providerSelections` during asset generation

### Notes
- This is NOT a Codex-suitable task — too many cross-layer interface changes
- Should be implemented by CC as a coordinated feature
- UI portion (StoryboardPanel dropdown) could potentially be split out, but only
  after the bridge contract is extended

### Recommendation
**Defer or handle as CC task.** Not suitable for Codex delegation.

---

## Execution Priority (Revised)

```
CX-1  (trivial, HIGH)   → DONE ✓
CX-2  (small, HIGH)     → Codex-ready — single file, pure deletion
CX-3  (large, MEDIUM)   → DONE ✓ (CC Session 19)
CX-4  (medium, MEDIUM)  → DONE ✓ (CC Session 19 — 16 tests)
CX-5  (large, LOW)      → DONE ✓ (CC Session 19)
```

## Codex-Executable Summary
Only **CX-2** is immediately executable by Codex without prerequisites.
**CX-3**, **CX-4**, **CX-5** were completed by CC in Session 19.

## Notes
- CC reviews and merges all Codex output
- Run `python -m compileall worker scripts` and `npm run build` after each task
- Do NOT modify `.env` or `.env.example`
