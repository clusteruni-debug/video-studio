# Video Studio App Pivot Plan

> **ARCHIVED — 2026-03-17 Session 27 (CC review)**
>
> **Verdict**: Rejected. The "generation-first vs orchestration-first" framing is a false
> dichotomy — the current codebase already supports both paths (upload-first when assets
> exist, free generation when not, premium on explicit approval). This plan attempted to
> solve an infrastructure problem (Pollinations instability) through a product direction
> change, which is the wrong approach.
>
> **Actual next steps**: Windows runtime test (never done), then stabilize free image
> generation path or find alternative. See `docs/WINDOWS-TEST-CHECKLIST.md`.

Date: 2026-03-17
Status: ~~Draft for Claude Code review~~ **ARCHIVED — not implementing**
Owner: Codex

## 1. Decision Summary

Video Studio App should pivot from a "local AI generation-first studio" into a "low-cost orchestration and composition-first studio".

This is not a rewrite.
This is a priority correction that uses the existing planner, manifest, upload, bridge, and FFmpeg composition pipeline as the product core.

## 2. Pivot Purpose

The pivot exists to optimize for these outcomes:

- Produce usable short-form content with minimal API spend
- Reduce dependence on unstable local or free-generation paths as the default runtime
- Reuse uploaded assets, still images, template motion, subtitles, and voiceover as the normal path
- Reserve paid or external generation for a very small number of hero scenes
- Keep the final project state, render outputs, and orchestration logic inside Video Studio App

## 3. Why This Pivot Fits The Current Codebase

The current implementation already behaves more like an orchestrator than a standalone generator:

- The bridge already exposes plan, save, and render endpoints
- The save flow already writes plans, manifests, uploads, and local media planning metadata
- The render flow already composes scene clips, subtitles, audio, and final MP4 output
- The UI already supports per-scene uploaded visual and audio assets
- The system already tracks generated vs uploaded vs placeholder results

The weak point is not the orchestration architecture.
The weak point is that the default mental model and some routing defaults still assume generation-heavy execution.

## 4. Product Direction After Pivot

The product should behave as follows:

1. A user provides one brief
2. The planner breaks it into scenes
3. Each scene tries asset reuse first
4. If no asset exists, the system prefers still-image based composition
5. The renderer adds motion, timing, captions, and voiceover locally
6. Only explicitly approved hero scenes use external premium generation
7. Final export remains a local render owned by Video Studio App

## 5. Non-Goals

The pivot does not aim to do these things:

- Make local text-to-video the default path
- Compete directly with Higgsfield on raw generation quality
- Promise full local zero-cost cinematic generation
- Add database, cloud sync, or multi-user features in this phase
- Add new dependencies unless a task explicitly proves they are required

## 6. Success Criteria

The pivot is successful when all of these are true:

- A project can be completed without any premium scene generation
- The default path uses upload-first and still-first behavior
- Render fallback uses useful motion-backed assets rather than flat placeholder cards whenever possible
- Premium generation is opt-in, scene-limited, and visible in the UI
- Verification proves the low-cost path works even when FLUX/Wan command adapters are disabled

## 7. AI-Executable Task Plan

The tasks below are written so an AI coding agent can execute them directly.
No time estimates are used.

### Task Group A — Lock The New Product Policy

1. [USER] Approve this pivot statement:
   "Video Studio App is a low-cost content orchestration and composition tool, not a generation-first tool."
2. [USER] Approve these runtime defaults:
   upload-first, still-first, premium-last.
3. [CC] Update project docs so every product summary reflects the new policy.
   Files:
   `projects/video-studio/README.md`
   `projects/video-studio/CLAUDE.md`
   `projects/video-studio/docs/IMPLEMENTATION-ROADMAP.md`
   `projects/video-studio/docs/OPERATOR-CHECKLIST.md`
4. [CC] Remove or reduce wording that frames FLUX/Wan as the normal happy path.
5. [CC] Document premium generation as a hero-scene override instead of a baseline route.

Done criteria:

- All top-level docs describe the app as composition-first
- No operator-facing doc implies that local generation is required for a successful default workflow

### Task Group B — Change Routing Defaults

1. [CC] Update route selection rules so the default route remains local composition unless a scene explicitly justifies premium output.
2. [CC] Add a policy layer that classifies scenes into:
   reusable asset, still-based composition, motion-source composition, premium hero scene.
3. [CC] Update manifest generation so still-image scenes remain the default whenever a scene can be satisfied without native video generation.
4. [CC] Ensure premium routing is rare by default and never selected just because the model is available.
5. [CC] Keep cost estimation visible, but make "zero-cost viable path" the primary path.

Primary files:

- `projects/video-studio/worker/media/model_router.py`
- `projects/video-studio/shared/contracts/render.ts`
- `projects/video-studio/app/ui/src/lib/planner.ts`
- `projects/video-studio/worker/planner/ollama_planner.py`

Done criteria:

- Standard projects route mostly to local composition
- Premium scenes appear only when the planner marks them as explicit hero exceptions
- Manifest output prefers image-based visual assets over video generation whenever acceptable

### Task Group C — Replace Weak Fallbacks With Useful Composition

1. [CC] Replace flat placeholder-card usage with a more useful low-cost fallback ladder.
2. [CC] Add scene motion templates for still images:
   slow zoom-in, slow zoom-out, pan-left, pan-right, slight vertical drift.
3. [CC] Add simple transition templates between scenes:
   hard cut, fade, short dissolve.
4. [CC] Make uploaded still images and uploaded short videos the preferred render input when present.
5. [CC] If no uploaded visual exists, generate a motion-backed branded fallback instead of a static emergency card whenever possible.
6. [CC] Keep the existing render report, but expand it to show which composition template each scene used.

Primary files:

- `projects/video-studio/worker/render/compose.py`
- `projects/video-studio/worker/media/runtime.py`
- `projects/video-studio/shared/contracts/render.ts`

Done criteria:

- A still-image-only project renders as a motion-based short video
- Render reports identify whether each scene used upload, still-template, motion-source, premium output, or final emergency fallback

### Task Group D — Make Asset Reuse First-Class

1. [CC] Add a reusable asset preference before local generation attempts.
2. [CC] Define deterministic scene asset precedence:
   current-session upload -> previously saved upload -> reusable library asset -> generation path -> final fallback.
3. [CC] Add reusable asset metadata fields only if they fit the current local-file manifest model without introducing a database.
4. [CC] Allow the operator to mark a scene as "force reuse", "allow still template", or "allow premium".
5. [CC] Ensure these controls are visible before render, not buried in logs.

Primary files:

- `projects/video-studio/app/ui/src/App.tsx`
- `projects/video-studio/app/ui/src/lib/planner.ts`
- `projects/video-studio/worker/planner/save_plan.py`
- `projects/video-studio/worker/media/runtime.py`

Done criteria:

- Asset precedence is explicit and deterministic
- A user can complete a project by mostly attaching assets instead of requesting generation

### Task Group E — Reframe The UI Around Cost-Controlled Production

1. [CC] Rewrite the UI hero, section labels, and controls around "brief -> scene board -> asset attach -> draft render".
2. [CC] Move premium toggles out of the main happy path and into advanced controls.
3. [CC] Surface low-cost status metrics first:
   reused scenes, still-template scenes, uploaded scenes, premium scenes.
4. [CC] Show premium scenes as exceptions that require deliberate operator approval.
5. [CC] Show the likely output path before render:
   upload, still-template, motion-source, premium, emergency fallback.

Primary files:

- `projects/video-studio/app/ui/src/App.tsx`
- `projects/video-studio/app/ui/src/styles.css`

Done criteria:

- The default user journey no longer looks generation-first
- Operators can tell which scenes will incur cost before rendering

### Task Group F — Rebuild Verification Around The New Happy Path

1. [CC] Add verification coverage for "no adapters, still useful output".
2. [CC] Add verification coverage for "uploaded visual + auto TTS + motion template".
3. [CC] Add verification coverage for "one premium hero scene plus local fallback project".
4. [CC] Keep existing adapter diagnostics, but stop treating command-backed FLUX/Wan success as the only meaningful path.
5. [CC] Update operator guidance so the recommended first test is composition-first, not Pollinations-first.

Primary files:

- `projects/video-studio/scripts/verify-render.ps1`
- `projects/video-studio/scripts/verify-bridge.ps1`
- `projects/video-studio/README.md`
- `projects/video-studio/docs/OPERATOR-CHECKLIST.md`

Done criteria:

- The verification script passes with adapters disabled
- The verification script still supports optional adapter testing, but that path is no longer the main milestone

## 8. Recommended Execution Order

1. [USER] Approve pivot purpose, non-goals, and runtime defaults
2. [CC] Complete Task Group A
3. [CC] Complete Task Group B
4. [CC] Complete Task Group C
5. [CC] Complete Task Group D
6. [CC] Complete Task Group E
7. [CC] Complete Task Group F
8. [CC] Run project verification and update docs/handoff

## 9. Explicit Deferrals

These items should be deferred unless the pivot later proves they are required:

- Full Wan local video execution as the default route
- More work on anonymous Pollinations reliability as a core milestone
- New persistence infrastructure
- New premium provider integrations
- Mobile-specific UX polish

## 10. Claude Code Review Checklist

Claude Code should review this plan against these questions:

1. Does the plan preserve the existing bridge/manifest architecture instead of triggering a rewrite?
2. Are the new defaults correctly centered on upload-first and still-first behavior?
3. Is the render-layer work enough to make low-cost output visually acceptable?
4. Are any tasks hiding dependency or schema changes that should be split out for approval?
5. Is any task too broad and in need of another task split before implementation?
6. Are the verification gates aligned with the new happy path?
7. Should any part of Task Group C be moved ahead of Task Group B because render quality is the real blocker?

## 11. Implementation Gate

Do not start implementation until the user and Claude Code both agree on:

- Pivot statement
- Default routing policy
- Premium scene policy
- Verification definition of "success"
