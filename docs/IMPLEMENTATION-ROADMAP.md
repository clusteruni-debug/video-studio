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
- completed as a browser-local draft flow
- project drafts currently persist in browser localStorage
- local worker bridge now exists as both CLI handoff via `worker.planner.save_plan` and HTTP bridge via `worker.bridge.server`
- the UI can now call the bridge for route planning and project saves
- next upgrade is replacing sample-plan logic with real model-backed planning and generation adapters

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
- `save_plan.py` now writes plan, routes, manifest, and prompt text files into `storage/`
- the Python bridge now exposes those save operations over `127.0.0.1:5161`
- runtime health now resolves FFmpeg and Ollama from common Windows install locations and reports probe failures clearly
- FLUX, Wan, Piper, and Whisper job execution are still placeholders

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
- the bridge can now run a placeholder FFmpeg smoke render that generates per-scene assets, concat/subtitle files, and a final 9:16 MP4 under `storage/renders/`
- real FLUX/Wan/Piper/Whisper-generated media is still not wired into the composition stage

## Phase 4 — Paid Premium Routing
- add per-scene Sora 2 adapter
- add budget and spend-cap controls
- show premium route approval before execution
- keep local fallback when the provider is disabled or rate-limited

Milestone gate:
- one project renders with one premium scene and local fallback support

## Phase 5 — Optional Veo 3
- add Veo 3 only if Sora 2 does not cover the premium audio-first requirement
- keep Veo 3 behind a separate provider toggle and budget limit

Milestone gate:
- route selection works across local, Sora 2, and Veo 3 without manual file edits
