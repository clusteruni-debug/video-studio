# Implementation Roadmap

## Phase 0 — Scaffold
- create the project folders
- document the architecture
- document operator setup steps
- define the planning and routing contract

## Phase 1 — Planner Contract
- add a small local UI shell
- add `shared/contracts/` types
- add a planner adapter that converts a prompt into `ProjectPlan`
- store plans as local JSON files under `storage/`

Milestone gate:
- planner can emit a valid `ProjectPlan` for three sample prompts

Current status:
- completed — Gemini 2.5 Flash is the primary planner with safe sample fallback (Ollama local LLM retired 2026-04)
- project drafts currently persist in browser localStorage
- local worker bridge now exists as both CLI handoff via `worker.planner.save_plan` and HTTP bridge via `worker.bridge.server`
- the UI can now call the bridge for route planning and project saves
- planner metadata now surfaces whether the machine used Gemini or the sample fallback
- next upgrade is replacing the remaining media-generation placeholders with real model-backed adapters

## Phase 2 — Local Free Path
- add local FLUX image generation adapter
- add local Wan video generation adapter
- add placeholder subtitle and voice job interfaces
- save all outputs into `storage/cache/` and `storage/renders/`

Milestone gate:
- one 15-second local-only 9:16 output renders successfully

Current status:
- partial
- render manifests now define per-scene visual/audio/subtitle assets and output paths
- `save_plan.py` now writes plan, routes, manifest, prompt text files, and uploaded scene assets into `storage/`
- the Python bridge now exposes those save operations over `127.0.0.1:5161`
- runtime health now resolves FFmpeg and Ollama from common Windows install locations and reports probe failures clearly
- the UI now lets the operator attach per-scene images/videos and audio files before save or render
- FLUX/Wan now have command-backed adapter skeletons that emit per-scene request JSON and can switch from placeholder fallback to real model execution through env-configured commands
- TTS now uses Edge TTS (previously Piper placeholder); Whisper job execution is still a placeholder

## Phase 3 — Composition
- add FFmpeg-driven assembly
- normalize scene durations
- add subtitles and voice placement
- add a single export action from the UI

Milestone gate:
- export a 30-second short with at least three scenes

Current status:
- partial
- FFmpeg command previews are now emitted in both the UI and Python render manifest output
- the bridge can now run a draft FFmpeg render that uses uploaded scene assets when present, otherwise tries the local FLUX/Wan adapter skeletons and falls back to scene cards plus local Windows TTS if those adapters stay in `stub` mode or fail
- save now writes `local-media-plan.json`, render now writes `local-media-report.json`, and the bridge/UI surface generated/uploaded/placeholder scene summaries
- real FLUX/Wan/Whisper-generated media still depends on the operator wiring actual adapter commands and model runtimes behind the new skeleton (TTS is now handled by Edge TTS)

## Phase 4 — Paid Premium Routing
- add per-scene Kling 3.0 / Veo 3 adapter (Sora 2 retired 2026-04; see `docs/VIDEO-PROVIDER-RESEARCH.md`)
- add budget and spend-cap controls
- show premium route approval before execution
- keep local fallback when the provider is disabled or rate-limited

Milestone gate:
- one project renders with one premium scene and local fallback support

## Phase 5 — Optional Secondary Premium
- add secondary premium provider if Kling 3.0 does not cover all use cases
- keep behind a separate provider toggle and budget limit

Milestone gate:
- route selection works across local, Kling 3.0, and fallback without manual file edits
