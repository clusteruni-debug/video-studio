# Video Studio App

## Status
- Content automation tool with multi-provider media pipeline
- React + Vite + TypeScript UI split into 4 components (App shell + 3 panels)
- 18 provider adapters across 5 categories (image, video, tts, bgm, sfx)
- Free-first provider policy — zero-cost path works with Pollinations + Edge TTS + local BGM
- FFmpeg composition with Ken Burns motion, xfade transitions, gradient backgrounds, BGM mixing
- Local Python bridge with runtime tool probing, Ollama planning, scene-asset upload handling
- No DB or remote storage yet
- Windows-first desktop/web hybrid content production tool

## Target Stack
- UI: React + Vite (split: App.tsx 428 LOC + 3 panels + shared utils)
- Desktop shell: Tauri 2 after the web UI stabilizes
- Planner: Ollama `qwen2.5:7b` local, browser-sample fallback
- Image: Pollinations FLUX (free default), DALL-E 3, Imagen 3
- Video: local Wan (free), Sora 2, Veo 3
- TTS: Edge TTS (free default), ElevenLabs, OpenAI TTS
- BGM: Local library (free), Suno
- Composition: FFmpeg with motion presets + xfade transitions

## Runtime Model
- Windows default for local development and local model execution
- Optional WSL OpenClaw bridge for planning only; do not assume WSL can call the Windows app over localhost
- UI dev port: `5160`
- Local Python bridge port: `5161`

## Directory Map
- `app/ui/src/` — React frontend
  - `App.tsx` — state management shell
  - `components/ComposerPanel.tsx` — prompt + budget controls
  - `components/StoryboardPanel.tsx` — scene cards + asset management
  - `components/ExecutionPanel.tsx` — render controls + diagnostics
  - `components/shared.ts` — shared types + utility functions
- `worker/planner/` — planning and routing adapters
- `worker/media/` — adapter registry, provider policy, cost estimation
  - `adapters.py` — 18 provider configs across 5 categories
  - `provider_policy.py` — free-first selection + manual approval
  - `model_router.py` — per-scene cost breakdown
- `worker/render/` — FFmpeg composition
  - `compose.py` — orchestrator
  - `motion.py` — Ken Burns zoompan presets
  - `transitions.py` — xfade + gradient background builders
- `scripts/` — provider adapter scripts (standalone, argparse-based)
- `shared/contracts/` — TypeScript/Python contract definitions
- `assets/bgm/` — local BGM library
- `storage/` — local generated inputs, cache, and renders

## Provider Adapter Scripts
- `scripts/pollinations_flux.py` — free image generation (existing)
- `scripts/edge_tts.py` — free cross-platform TTS
- `scripts/dalle3_image.py` — DALL-E 3 images
- `scripts/imagen3_image.py` — Imagen 3 images
- `scripts/sora2_video.py` — Sora 2 video
- `scripts/veo3_video.py` — Veo 3 video
- `scripts/elevenlabs_tts.py` — ElevenLabs TTS
- `scripts/openai_tts.py` — OpenAI TTS
- `scripts/suno_bgm.py` — Suno BGM [UNCERTAIN API]

## Current Constraints
- Package manager files are present; keep dependency changes explicit
- No DB or remote storage yet
- Free provider path (Pollinations + Edge TTS + local BGM) works with zero API keys
- Paid providers require env var API keys — see `.env.example`
- FLUX/Wan default to `stub` mode until the operator sets command-backed adapter env vars
- Suno API adapter is marked [UNCERTAIN] — API surface may not be stable

## Verified Commands
```bash
npm run bridge
npm run dev
npm run build
python -m worker.planner.route_plan --prompt "sample prompt" --budget-mode free
python -m worker.planner.save_plan --prompt "sample prompt" --budget-mode standard
python -m worker.bridge.server
python -m worker.render.compose --project-id demo
python -m compileall worker
python -m compileall scripts
ffmpeg -version
ollama --version
```

## Local Run Flow
- Terminal 1: `npm run bridge`
- Terminal 2: `npm run dev`
- Browser: `http://127.0.0.1:5160`
- `npm run dev` is a build-and-serve flow, not Vite HMR. Rerun it after UI code changes.
- Scene asset files are selected in the UI, held for the current browser session, and copied into `storage/inputs/<project-id>/uploads/` when the user saves or renders.

## References
- `docs/ARCHITECTURE.md`
- `docs/MODEL-ROUTING.md`
- `docs/OPERATOR-CHECKLIST.md`
