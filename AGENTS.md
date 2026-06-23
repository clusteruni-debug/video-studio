# Video Studio App — AGENTS.md

> Global rules: see root AGENTS.md (role definitions, delegation, git permissions)

## Overview
- **Stack**: React + Vite UI, future Tauri 2 shell, Python 3.11 local AI worker, FFmpeg compositor
- **Role**: Windows-first short-form video generation and editing app with hybrid local/API model routing
- **Runtime**: Windows app runtime by default; optional OpenClaw planning bridge must respect the Windows/WSL boundary
- **Scope**: Only files inside `projects/video-studio/`

## Core Rules
1. Keep this project Windows-first unless a WSL worker is explicitly required and documented
2. Do not add or remove dependencies without explicit approval
3. Do not add DB schema, Supabase, or external persistence until explicitly approved
4. `.env*` values are manual-only; never place API keys, tokens, or secrets in source files
5. If OpenClaw planning is added, keep OpenClaw in the inference/orchestration role only; the app owns source-of-truth state and render outputs
6. Treat `storage/` as local working data, not durable product storage
7. Before any video-production, source-generation, or render-continuation work, check `storage/approval-packets/ACTIVE.json` if it exists. If its status is `active`, read the referenced production packet before rendering or generating a replacement manifest. If the packet has `approvedForRender=false`, continue with the packet's required source artifacts/contact sheet/review steps instead of rendering.

## Active Production Packet Lock
- `storage/approval-packets/ACTIVE.json` is a local operator pointer, not product storage. It may force the next session to resume a specific approval packet without requiring a long user prompt.
- The render path may block only manifests that match the active pointer scope (`approvalPacketId`, explicit project id, project id prefix, or an explicitly enabled reference/audience pair). Unrelated smoke renders and experiments must remain unaffected.
- A matching manifest must include `approvalPacketId`/`productionApprovalPacketId` equal to the active packet id, and the referenced packet must have `approvedForRender=true` before FFmpeg runs.
- Do not bypass this lock by renaming the project id or removing the approval packet fields. Clear or inactivate `ACTIVE.json` deliberately when the operator wants to leave the packet workflow.

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
