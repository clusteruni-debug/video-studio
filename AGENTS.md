# Video Studio App — AGENTS.md

> Global rules: see root AGENTS.md (role definitions, delegation, git permissions)

## Overview
- **Stack**: React + Vite UI, future Tauri 2 shell, Python 3.11 local AI worker, FFmpeg compositor
- **Role**: Windows-first short-form video generation and editing app with hybrid local/API model routing
- **Runtime**: Windows app runtime by default; optional OpenClaw planning bridge must respect the Windows/WSL boundary
- **Scope**: Only files inside `projects/video-studio-app/`

## Core Rules
1. Keep this project Windows-first unless a WSL worker is explicitly required and documented
2. Do not add or remove dependencies without explicit approval
3. Do not add DB schema, Supabase, or external persistence until explicitly approved
4. `.env*` values are manual-only; never place API keys, tokens, or secrets in source files
5. If OpenClaw planning is added, keep OpenClaw in the inference/orchestration role only; the app owns source-of-truth state and render outputs
6. Treat `storage/` as local working data, not durable product storage

## High-Risk Areas
- `worker/**` — model routing, local GPU usage, and paid API adapter boundaries
- `shared/contracts/**` — planner/compositor contract changes can break multiple layers at once
- `scripts/**` — install/bootstrap helpers must not hardcode secrets or machine-specific paths
- `storage/**` — generated assets can grow quickly; avoid committing large runtime artifacts

## Verification
- Docs/scaffold-only changes: confirm folder layout matches `README.md`
- UI implementation later: `npm run build`
- Worker implementation later: `python -m compileall worker`
- Integration implementation later: run a local smoke render on a short 9:16 sample project

## References
- `CLAUDE.md` — runtime model and directory map
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/MODEL-ROUTING.md`
- `docs/OPERATOR-CHECKLIST.md`
