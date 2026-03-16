# Video Studio App

## Status
- Scaffold plus dependency-free planner/routing worker code
- React + Vite + TypeScript UI shell is now part of the project
- Local file-save and render-manifest worker flow is now part of the project
- Local Python bridge is now part of the project
- Runtime tool probing and placeholder FFmpeg smoke rendering are now part of the project
- No DB or remote storage yet
- Planned as a Windows-first desktop/web hybrid video generation tool

## Target Stack
- UI: React + Vite
- Desktop shell: Tauri 2 after the web UI stabilizes
- Planner: OpenClaw + Codex for prompt-to-scene planning
- Local image generation: FLUX.1-schnell
- Local video generation: Wan2.1-T2V-1.3B-Diffusers
- Premium video upgrade: Sora 2, with Veo 3 optional for special cases
- Speech and render pipeline: Piper / Whisper.cpp / FFmpeg

## Runtime Model
- Windows default for local development and local model execution
- Optional WSL OpenClaw bridge for planning only; do not assume WSL can call the Windows app over localhost
- Proposed UI dev port: `5160`
- Local Python bridge port: `5161`

## Directory Map
- `app/ui/` — future React + Vite frontend
- `worker/planner/` — future planning and routing adapters
- `worker/media/` — future local generation and composition services
- `shared/contracts/` — future TypeScript/Python contract definitions
- `docs/` — architecture, routing, implementation, and operator notes
- `scripts/` — future bootstrap and verification helpers
- `assets/` — template and reference material
- `storage/` — local generated inputs, cache, and renders
- `config/` — future local config samples and defaults

## Current Constraints
- Package manager files are present; keep dependency changes explicit
- No DB or remote storage yet
- No API keys or environment files yet
- Keep the first implementation pass local-file based; add paid routing only after the local path is stable

## Future Verified Commands
```bash
npm run bridge
npm run dev
npm run build
npm run verify:phase2
npm run verify:bridge
python -m worker.planner.route_plan --prompt "sample prompt" --budget-mode free
python -m worker.planner.save_plan --prompt "sample prompt" --budget-mode standard
python -m worker.bridge.server
python -m worker.render.compose --project-id demo
python -m worker.render.render_manifest --prompt "sample prompt" --budget-mode standard --project-id demo
python -m compileall worker
powershell -ExecutionPolicy Bypass -File scripts/verify-phase1.ps1
powershell -ExecutionPolicy Bypass -File scripts/verify-phase2.ps1
powershell -ExecutionPolicy Bypass -File scripts/verify-bridge.ps1
powershell -ExecutionPolicy Bypass -File scripts/verify-render.ps1
ffmpeg -version
ollama --version
```

## Local Run Flow
- Terminal 1: `npm run bridge`
- Terminal 2: `npm run dev`
- Browser: `http://127.0.0.1:5160`

## References
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/MODEL-ROUTING.md`
- `docs/IMPLEMENTATION-ROADMAP.md`
- `docs/OPERATOR-CHECKLIST.md`
