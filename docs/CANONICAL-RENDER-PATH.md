# Video Studio Canonical Render Path

Status: M0 evidence note for `PLAN-VIDEO-STUDIO-SEMI-AUTO-QUALITY-LOOP`
Updated: 2026-07-09

## Decision

Video Studio currently has two active final-video paths:

- `/api/create-draft` routes through `worker.bridge.draft_executor.execute_draft_core`, which creates a CapCut/VectCutAPI draft.
- `/api/render-smoke` routes through `worker.planner.save_plan.save_project_bundle` and `worker.render.compose.compose_smoke_render`, which renders an FFmpeg MP4 from the saved manifest.

For the semi-auto Grok-source quality loop, M2 render hotfixes must target the path used by the selected production packet:

- Generic dashboard Grok-source FFmpeg proof: target `/api/render-smoke` and `worker/render/compose*.py`.
- `kr-curiosity-bottled-water-20260616` active packet: treat CapCut as the current production attempt because `storage/approval-packets/ACTIVE.json` points to a CapCut draft and sets `capcutHandoffRequired=true`.

Do not assume a compose/FFmpeg fix reaches the CapCut draft path. If the operator continues the active `kr-curiosity` packet, BGM/subtitle fixes must be implemented in the CapCut handoff path or the packet must be deliberately cleared/superseded before rendering through FFmpeg.

## Evidence

- `worker/bridge/server.py` exposes `POST /api/create-draft` and delegates to `execute_draft_core`.
- `worker/bridge/server.py` exposes `POST /api/render-smoke` and delegates to `compose_smoke_render`.
- `app/ui/src/lib/bridge.ts` exposes both `createDraft()` and `renderSmoke()`.
- `storage/approval-packets/ACTIVE.json` is active for `kr-curiosity-bottled-water-20260616`, reports `capcutHandoffRequired=true`, `capcutDraftCreated=true`, and `ffmpegOnlyFinalAllowed=false`.
- The active packet's `latestRenderPath` is an FFmpeg preview estimate, but the latest production attempt is the CapCut size-normalized draft whose automatic export is blocked by CapCut UIA exposure.

## M2 Targeting Rule

Before changing BGM or subtitle behavior, identify the packet/render command being exercised:

1. If the request uses `/api/render-smoke` or a Grok render payload that calls `compose_smoke_render`, target `worker/render/compose.py` and `worker/render/compose_ffmpeg.py`.
2. If the request uses `/api/create-draft` or a CapCut draft path, target `worker/bridge/draft_executor.py`, `worker/bridge/vectcut_bridge.py`, and `worker/render/capcut_handoff.py`.
3. If `storage/approval-packets/ACTIVE.json` is active and matches the project, do not bypass it by changing project ids, reference presets, or target audience values.

