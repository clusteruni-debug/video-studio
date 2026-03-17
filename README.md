# Video Studio App

Windows-first short-form video generation workspace scaffold.

## Current Goal
- Plan and build a hybrid video tool that can:
  - generate short videos from text
  - combine image + voice + subtitles
  - upgrade selected scenes to premium paid video models when quality matters

## Current State
- React + Vite + TypeScript UI shell added
- Local browser storage for project drafts added
- Ollama `qwen2.5:7b` planning is now verified through the worker bridge
- Local file export scaffolding now writes `project-plan.json`, `routes.json`, and `render-manifest.json` under `storage/`
- Local Python bridge on `127.0.0.1:5161` can now route plans, save project bundles, inspect local tool readiness, report FLUX/Wan adapter readiness, accept per-scene uploaded assets, and trigger a real draft FFmpeg render from the UI
- Save/render now write `storage/cache/<project-id>/local-media-plan.json` and `storage/renders/<project-id>/local-media-report.json` so the operator can see which scenes were uploaded, generated, or placeholder-backed
- FFmpeg and Ollama are now resolved from common Windows install locations instead of PATH-only detection
- Draft render now supports:
  - scene title-card fallback visuals
  - uploaded per-scene images or videos
  - uploaded per-scene audio
  - command-backed FLUX/Wan adapters via environment configuration
  - Windows local narration fallback
  - subtitle burn-in and final 9:16 MP4 export
- No DB or remote persistence yet

## Working Model
- OpenClaw + Codex plans the video
- Local models generate the default assets
- Paid APIs are used only for high-value scenes
- FFmpeg composes the final 9:16 output

## Folder Map
- `app/ui/` — React frontend source
- `worker/planner/` — Ollama-backed planner, sample fallback, and route-plan/save-plan CLIs
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
3. Install the local Ollama planner model with `ollama pull qwen2.5:7b`
4. Configure FLUX + Wan adapter commands
5. Add FFmpeg composition path
6. Add premium scene routing to Sora 2
7. Add Veo 3 only if a premium audio-first path is still required

## FLUX Runtime Choices
- Pollinations cloud wrapper:
  - use this first on the current 16 GB Windows machine if you want prompt-only image generation working immediately
  - no API key and no extra Python packages are required
  - in `--endpoint-mode auto`, the wrapper now uses the legacy Pollinations endpoint for anonymous runs, switches to the unified endpoint first when `VIDEO_STUDIO_POLLINATIONS_API_KEY` is set, and retries retryable `429` and `5xx` responses with backoff and jitter
  - the wrapper can also throttle the next FLUX scene request so one job has time to clear before the next image prompt starts
  - if you manually set `VIDEO_STUDIO_POLLINATIONS_API_KEY`, the wrapper forwards it as a Bearer header so backend-authenticated runs can avoid the anonymous path without leaking the key into command logs
  - anonymous usage is still rate-limited, so repeated queue saturation or upstream timeouts can still end in placeholder fallback even after retries
  - copy the sample values from `.env.example` or run `powershell -ExecutionPolicy Bypass -File scripts/verify-render.ps1 -UsePollinationsFlux`
- Local FLUX weights:
  - keep this as the long-term fully local path after gated model downloads are stable
  - expect higher disk pressure, longer setup, and stricter VRAM/runtime constraints than the Pollinations wrapper
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
  - warns if `ffmpeg`, `ollama`, or `hf` are not visible on PATH in the current shell
- `powershell -ExecutionPolicy Bypass -File scripts/verify-phase2.ps1`
  - compiles the worker package
  - saves a sample project into `storage/inputs/verify-project-save`
  - emits a sample render manifest with storage/cache/render paths
- `powershell -ExecutionPolicy Bypass -File scripts/verify-planner.ps1`
  - runs the worker CLI planner directly
  - confirms planner metadata is emitted
  - shows whether the current machine used Ollama or the sample fallback
- `powershell -ExecutionPolicy Bypass -File scripts/verify-bridge.ps1`
  - starts the local Python bridge
  - verifies `/api/health`, `/api/route-plan`, and `/api/save-project`
  - confirms planner runtime metadata and local media adapter metadata are present in health
  - confirms save responses now emit `localMediaPlanPath` and `localMediaSummary`
- `powershell -ExecutionPolicy Bypass -File scripts/verify-render.ps1`
  - starts the local Python bridge
  - verifies `/api/health` with resolved tool diagnostics
  - confirms the planner backend is real Ollama
  - posts sample per-scene uploaded image/audio assets
  - runs `/api/render-smoke`
  - confirms `local-media-plan.json` and `local-media-report.json` are written
  - confirms the render response reports generated/uploaded/placeholder scene counts
  - confirms a draft 9:16 MP4 and FFmpeg log are written under `storage/renders/`
  - add `-UsePollinationsFlux` to force the FLUX command path through `scripts/pollinations_flux.py` and confirm the adapter was attempted before placeholder fallback
- `npm run build`
  - validates the React/Vite UI shell and shared TypeScript contracts

Note:
- `npm run dev` now builds the React app and serves `dist/` through Python on port `5160`
- this avoids the TSX/JSX blank-screen issue that appeared when the app was served without the React transform
- after code changes, rerun `npm run dev` so the build output is refreshed
- the default planner model is `qwen2.5:7b`; if it is missing, the app falls back to the local sample planner and shows that state in the UI
- uploaded scene files are held in the current browser session and copied into `storage/inputs/<project-id>/uploads/` on save or render
- `.env.example` now shows the keyless Pollinations FLUX command example for immediate image generation and a commented local-FLUX alternative
- `.env.example` also shows the optional Pollinations key/endpoint tuning variables if you want to move the same wrapper from anonymous mode to a backend-authenticated run later
- FLUX/Wan stay in `stub` mode until the operator sets `VIDEO_STUDIO_FLUX_COMMAND` and `VIDEO_STUDIO_WAN_COMMAND`; until then render uses the existing placeholder-card fallback and reports that state explicitly

## References
- `docs/ARCHITECTURE.md`
- `docs/MODEL-ROUTING.md`
- `docs/IMPLEMENTATION-ROADMAP.md`
- `docs/OPERATOR-CHECKLIST.md`
