# Video Studio App

Windows-first short-form video generation workspace scaffold.

## Current Goal
- Plan and build a hybrid video tool that can:
  - generate short videos from text
  - combine image + voice + subtitles
  - run as a zero-paid automation pipeline by default

## Current State
- React + Vite + TypeScript UI shell added
- Local browser storage for project drafts added
- Gemini/sample planning is verified through the worker bridge; Ollama is retired
- Local file export scaffolding now writes `project-plan.json`, `routes.json`, and `render-manifest.json` under `storage/`
- Local Python bridge on `127.0.0.1:5161` can now route plans, save project bundles, inspect zero-paid provider readiness, accept per-scene uploaded assets, and trigger a real FFmpeg smoke render
- Save/render now write `storage/cache/<project-id>/local-media-plan.json` and `storage/renders/<project-id>/local-media-report.json` so the operator can see which scenes were uploaded, generated, or placeholder-backed
- FFmpeg is resolved from common Windows install locations instead of PATH-only detection
- Draft render now supports:
  - scene title-card fallback visuals
  - uploaded per-scene images or videos
  - uploaded per-scene audio
  - command-backed Wan adapters via environment configuration
  - Windows local narration fallback
  - subtitle burn-in and final 9:16 MP4 export
- No DB or remote persistence yet

## Working Model
- OpenClaw + Codex plans the video
- Local/free providers generate the default assets
- Paid APIs are blocked unless the operator explicitly opts in
- FFmpeg composes the final 9:16 output

## Folder Map
- `app/ui/` — React frontend source
- `worker/planner/` — Gemini planner, sample fallback, and route-plan/save-plan CLIs
- `worker/media/` — model routing and cost-estimation helpers
- `shared/contracts/` — TypeScript plan contracts and JSON schema
- `docs/` — architecture, routing logic, implementation plan, operator checklist
- `scripts/` — setup and verification scripts
- `assets/templates/` — reusable scene and subtitle templates
- `assets/refs/` — reference prompts, style boards, and example material
- `storage/inputs/` — imported user assets
- `storage/renders/` — rendered outputs
- `storage/cache/` — model and job cache
- `config/` — local config samples

## Recommended Build Sequence
1. Complete the operator checklist in `docs/OPERATOR-CHECKLIST.md`
2. Implement the planner and contract layer first
3. Configure local Wan adapter commands if you want generated video beyond stock/placeholder output
4. Keep `VIDEO_STUDIO_ALLOW_PAID_PROVIDERS` unset unless you intentionally allow paid providers
5. Add FFmpeg composition path
6. Add Grok UI handoff only as browser/manual import, not paid API wiring

## Zero-Paid Runtime Choices
- Uploaded visual/audio assets:
  - most deterministic path for operator-provided clips and voiceover
  - used directly in the FFmpeg smoke render
- Free stock fallback:
  - Pexels/Klipy/Freesound are optional free-key paths
  - Pexels video is normalized to 30fps before xfade composition
- Free-key image generation:
  - Gemini Flash Image can be wired as a command adapter when the operator has a free key
- Grok:
  - use browser/UI handoff only; do not wire the paid xAI video API for this goal
- Wan:
  - still follows the same command-adapter contract, but remains a local/stub choice until a Windows runner is prepared

## Current Verification
- Manual local run:
  - terminal 1: `npm run bridge`
  - terminal 2: `npm run dev`
  - browser: `http://127.0.0.1:5160`
- `npm run bridge`
  - starts the local Python bridge on `127.0.0.1:5161`
- `powershell -ExecutionPolicy Bypass -File scripts/verify-phase1.ps1`
  - verifies the local Python 3.14 venv
  - compiles the worker package
  - emits sample free and premium route payloads
  - warns if local runtime tools are not visible on PATH in the current shell
- `powershell -ExecutionPolicy Bypass -File scripts/verify-phase2.ps1`
  - compiles the worker package
  - saves a sample project into `storage/inputs/verify-project-save`
  - emits a sample render manifest with storage/cache/render paths
- `powershell -ExecutionPolicy Bypass -File scripts/verify-planner.ps1`
  - runs the worker CLI planner directly
  - confirms planner metadata is emitted
  - shows whether the current machine used Gemini or the sample fallback
- `powershell -ExecutionPolicy Bypass -File scripts/verify-bridge.ps1`
  - starts the local Python bridge
  - verifies `/api/health`, `/api/route-plan`, and `/api/save-project`
  - confirms planner runtime metadata, zero-paid status, and local media adapter metadata are present in health
  - confirms save responses now emit `localMediaPlanPath` and `localMediaSummary`
- `powershell -ExecutionPolicy Bypass -File scripts/verify-render.ps1`
  - starts the local Python bridge
  - verifies `/api/health` with resolved tool diagnostics
  - confirms the planner backend is Gemini or sample fallback
  - posts sample per-scene uploaded image/audio assets
  - runs `/api/render-smoke`
  - confirms `local-media-plan.json` and `local-media-report.json` are written
  - confirms the render response reports generated/uploaded/placeholder scene counts
  - confirms a draft 9:16 MP4 and FFmpeg log are written under `storage/renders/`
- `npm run build`
  - validates the React/Vite UI shell and shared TypeScript contracts

Note:
- `npm run dev` now builds the React app and serves `dist/` through Python on port `5160`
- this avoids the TSX/JSX blank-screen issue that appeared when the app was served without the React transform
- after code changes, rerun `npm run dev` so the build output is refreshed
- the default planner is Gemini when a key is available; otherwise the app falls back to the local sample planner and shows that state in the UI
- uploaded scene files are held in the current browser session and copied into `storage/inputs/<project-id>/uploads/` on save or render
- Wan stays in `stub` mode until the operator sets `VIDEO_STUDIO_WAN_COMMAND`; until then render uses uploaded assets, free stock, and placeholder-card fallback and reports that state explicitly

## References
- `docs/ARCHITECTURE.md`
- `docs/MODEL-ROUTING.md`
- `docs/IMPLEMENTATION-ROADMAP.md`
- `docs/OPERATOR-CHECKLIST.md`
