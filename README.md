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
- Dependency-free worker planning and routing scaffold is present
- Local file export scaffolding now writes `project-plan.json`, `routes.json`, and `render-manifest.json` under `storage/`
- Local Python bridge on `127.0.0.1:5161` can now route plans, save project bundles, inspect local tool readiness, and trigger a placeholder FFmpeg smoke render from the UI
- FFmpeg and Ollama are now resolved from common Windows install locations instead of PATH-only detection
- No DB or remote persistence yet

## Working Model
- OpenClaw + Codex plans the video
- Local models generate the default assets
- Paid APIs are used only for high-value scenes
- FFmpeg composes the final 9:16 output

## Folder Map
- `app/ui/` — React frontend source
- `worker/planner/` — sample plan builder and route-plan CLI scaffold
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
3. Add local FLUX + Wan generation path
4. Add FFmpeg composition path
5. Add premium scene routing to Sora 2
6. Add Veo 3 only if a premium audio-first path is still required

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
- `powershell -ExecutionPolicy Bypass -File scripts/verify-bridge.ps1`
  - starts the local Python bridge
  - verifies `/api/health`, `/api/route-plan`, and `/api/save-project`
- `powershell -ExecutionPolicy Bypass -File scripts/verify-render.ps1`
  - starts the local Python bridge
  - verifies `/api/health` with resolved tool diagnostics
  - runs `/api/render-smoke`
  - confirms a placeholder 9:16 MP4 and FFmpeg log are written under `storage/renders/`
- `npm run build`
  - validates the React/Vite UI shell and shared TypeScript contracts

Note:
- In constrained shells, Vite may print an `esbuild spawn EPERM` warning during dependency scan. If the `Local: http://127.0.0.1:5160/` line appears, the UI server is still up and usable.

## References
- `docs/ARCHITECTURE.md`
- `docs/MODEL-ROUTING.md`
- `docs/IMPLEMENTATION-ROADMAP.md`
- `docs/OPERATOR-CHECKLIST.md`
