# Video Studio Windows Human-Mode Runtime Checklist

Status: partially executed on Windows for the Auto Studio operator-handoff slice
Updated: 2026-06-26
Audience: human operators running Video Studio on Windows

This checklist replaces the old Ollama/qwen-era runtime checklist. The current
first proof path is Human Mode:

- bridge on `127.0.0.1:5161`
- dashboard on `127.0.0.1:5160`
- no-LLM Demo Mode first
- optional providers only after Demo Mode works
- phone review and publish packet before any upload claim

Do not mark Human Mode released until this checklist has been run on Windows.

## 1. Environment Check

- [ ] `cd C:\vibe\projects\video-studio`
- [ ] Activate the project Python environment if one is used.
- [ ] `node --version`
- [ ] `npm --version`
- [ ] `python --version`
- [ ] `ffmpeg -version`
- [ ] Confirm `storage\` is writable.
- [ ] Optional only: confirm provider keys or command adapters if needed.

Expected:

- Node/npm, Python, and FFmpeg are visible to the same shell that starts the
  bridge.
- Missing Gemini, Pexels, Grok, CapCut, or paid-provider credentials do not
  block Demo Mode.
- No `.env` file is edited by the app.

## 2. Source-Level Gate

- [ ] Python compile for changed worker files.
- [ ] Focused route/gate tests for changed behavior.
- [ ] TypeScript check for UI/contract changes.
- [ ] `npm run build` only when the operator allows it.

Current source-only session boundary:

- 2026-06-25 Codex Windows source gates passed:
  - `python -m py_compile worker\bridge\auto_studio.py worker\bridge\routes_auto_studio.py tests\test_auto_studio_routes.py tests\test_dashboard_ia_contract.py`
  - `.\.venv\Scripts\python.exe -m pytest -q tests\test_auto_studio_routes.py tests\test_dashboard_ia_contract.py`
  - `.\node_modules\.bin\tsc --noEmit`
  - `npm run build`
- `node --check app\ui\src\components\SceneDirectorPanel.tsx` is not a valid
  TSX verifier and returned `ERR_UNKNOWN_FILE_EXTENSION`; TypeScript verification
  is covered by `tsc --noEmit` and `npm run build`.
2026-06-26 plan-sync boundary:

- Project plan inventory is synced through `docs/IMPLEMENTATION-ROADMAP.md` and
  `docs/plans/PLAN-VIDEO-STUDIO-LOCAL-GATE-HARDENING.md`.
- Static local-gate proof passed, but this checklist still owns the Windows
  runtime proof: source accept in the dashboard, render health, phone review,
  publish packet, signed-in Grok/Gemini import, and platform/upload evidence.
- 2026-06-26 Codex restored the Rollup optional native package in current
  `node_modules` and reran `npm run build`; the build passed in WSL. Windows
  bridge/dashboard runtime proof still remains operator-owned.

## 3. Bridge Server

- [ ] Start the bridge with the project-supported command, usually
  `npm run bridge`.
- [ ] Open `http://127.0.0.1:5161/api/health`.
- [ ] Open `http://127.0.0.1:5161/api/human-operator/setup-status`.
- [ ] Open `http://127.0.0.1:5161/api/human-operator/status`.
- [ ] Open `http://127.0.0.1:5161/api/human-operator/provider-readiness`.
- [ ] Open `http://127.0.0.1:5161/api/human-operator/adapter-command-readiness`.
- [ ] Open `http://127.0.0.1:5161/api/human-operator/worklist`.

Expected:

- `setup-status.criticalReady=true`.
- `setup-status.demoModeReady=true`.
- Provider readiness separates Demo Mode from Provider-Assisted mode.
- Adapter readiness reports Wan/Gemini command state without running them.
- Worklist labels runtime proof as pending, not complete.

2026-06-25 Codex Windows result:

- Bridge started on `http://127.0.0.1:5161`.
- `/api/human-operator/setup-status` reported `criticalReady=true`,
  `demoModeReady=true`, and checks `python:ready`, `node:ready`, `npm:ready`,
  `ffmpeg:ready`, `project-root:ready`, `storage:ready`.
- `/api/human-operator/adapter-command-readiness` reported `edge-tts:ready`;
  Wan, Gemini Flash, Pexels, local BGM, and Freesound remain optional.
- Proof JSON:
  `storage/proof/operator-handoff-runtime-demo-proof-20260625-214823.json`.

## 4. Dashboard

- [ ] Start the dashboard with `npm run dev`.
- [ ] Open `http://127.0.0.1:5160`.
- [ ] Home shows `Human operator P0`.
- [ ] Home shows Provider readiness.
- [ ] Home shows Human-mode remaining work.
- [ ] Raw JSON remains under Advanced-only surfaces.

Expected:

- The first screen answers the next human action.
- A user without Claude Code, Codex, Grok, Gemini, CapCut, or paid APIs can
  still follow Demo Mode.

2026-06-25 Codex Windows result:

- Dashboard started on `http://127.0.0.1:5160` and returned HTTP 200.

## 5. No-LLM Demo Path

- [ ] Click or call `POST /api/human-operator/demo/prepare`.
- [ ] Confirm `storage\human-operator-demo\human-operator-local-demo-p0\`
  contains `summary.json`, `material.json`, and `render-smoke-payload.json`.
- [ ] Run `POST /api/human-operator/demo/render` from the dashboard or bridge.
- [ ] Confirm a render result is written to
  `demo-render-result.json`.

Expected:

- The demo does not require Gemini, Grok, Claude, Codex, CapCut, or paid APIs.
- A successful demo render is still labeled as a demo draft, not an upload
  candidate.

2026-06-25 Codex Windows result:

- `POST /api/human-operator/demo/prepare` wrote the demo packet.
- `POST /api/human-operator/demo/render` completed through fallback smoke render.
- Output MP4:
  `storage/renders/human-operator-local-demo-p0/no-llm-local-demo-for-video-studio-human-operato.mp4`.
- Render reports:
  `storage/renders/human-operator-local-demo-p0/render-quality-report.json` and
  `storage/renders/human-operator-local-demo-p0/local-media-report.json`.
- ffprobe confirmed H.264 video, 1080x1920, 30/1 fps, AAC mono audio, duration
  14.1 seconds, size 7,782,212 bytes.
- This is demo/fallback runtime proof only. It is not source acceptance, phone
  review, or upload readiness.

## 5a. Auto Studio Operator Handoff

- [x] `GET /api/auto-studio/providers`.
- [x] `POST /api/auto-studio/run` with blank seed, `assetProvider=grok`, and
  draft render mode.
- [x] `GET /api/auto-studio/latest`.
- [ ] Human operator opens Grok/Gemini in signed-in Chrome, generates a real
  PNG/MP4, downloads it, and imports it through Scene Director.

2026-06-25 Codex Windows result:

- Provider registry returned 7 providers.
- Grok and Gemini reported `executionMode=operator-handoff` and
  `canGenerateNow=false`.
- Blank-seed Grok draft returned `status=manual-handoff-required`,
  `handoffQueueCount=5`, `renderReady=false`, and `publishReady=false`.
- Auto-image smoke through `/api/auto-studio/run` was attempted but blocked by
  a 120-second HTTP timeout during the generated draft/render path. The
  fallback demo smoke render above is the completed MP4 proof for this slice.

## 6. Local Source Review

- [ ] Open the Sources tab.
- [ ] Add or reference an operator-owned local source.
- [ ] Save an accepted source review.
- [ ] Confirm `GET /api/human-operator/sources/status` reports
  `acceptedCount>=1`.
- [ ] Try a browser-proof payload with only Grok `/imagine` surface-visible
  evidence and confirm it is rejected.
- [ ] Try any `/c/*` redirect or native Chrome Download/Save/Export prompt
  proof and confirm it is rejected.

Expected:

- Local upload or direct import can satisfy accepted-source proof after human
  acceptance.
- Browser surface-only evidence never satisfies accepted-source proof.
- Native download prompts remain operator-owned and are never automation proof.

## 7. Render Health

- [ ] Open the Edit tab.
- [ ] Check `GET /api/human-operator/render-health`.
- [ ] If render fails, confirm the failure category is one of:
  `missing-ffmpeg`, `missing-source-file`, `invalid-manifest`,
  `subtitle-error`, `audio-error`, `write-permission`,
  `active-approval-lock`, or `unknown`.
- [ ] Confirm the UI shows output/log paths when present.

Expected:

- Render failures produce repair actions.
- The operator does not need source-code inspection to find the next repair.

## 8. Phone Review And Publish Packet

- [ ] Open the Review tab.
- [ ] Save a phone review only after a real full-watch pass.
- [ ] Confirm `GET /api/human-operator/phone-review/status`.
- [ ] Confirm `GET /api/human-operator/publish-packet`.

Expected:

- Publish readiness is blocked without render proof, accepted source proof, and
  accepted phone review proof.
- Upload remains an operator-owned action.

## 9. Optional Provider-Assisted Checks

Run only after Demo Mode works:

- [ ] Wan command adapter: configure `VIDEO_STUDIO_WAN_MODE=command` and
  `VIDEO_STUDIO_WAN_COMMAND` manually, then inspect
  `adapter-command-readiness`.
- [ ] Gemini Flash Image command adapter: configure
  `VIDEO_STUDIO_GEMINI_FLASH_MODE=command` and
  `VIDEO_STUDIO_GEMINI_FLASH_COMMAND` manually only if image generation is
  needed.
- [ ] Grok: use the existing signed-in Chrome/Grok Imagine surface; `/c/*`
  redirects are failure.
- [ ] CapCut: export manually unless a separate dependency/UI automation plan is
  approved.

Expected:

- Optional providers accelerate production but are not required for first-run
  proof.
- Paid providers stay blocked unless
  `VIDEO_STUDIO_ALLOW_PAID_PROVIDERS=1` is explicitly set.

## 10. Release Decision

Human-mode MVP release can be claimed only when all are true:

- [ ] Fresh clone docs lead to a running bridge and dashboard.
- [ ] Demo Mode renders a local draft without provider accounts.
- [ ] Accepted-source review can be saved.
- [ ] Render health explains success or failure.
- [ ] Phone review can be saved.
- [ ] Publish packet shows blockers or ready-for-operator-upload state.
- [ ] No docs imply Codex/Claude is required to run the app.
- [ ] Verification notes distinguish source checks from Windows runtime proof.

If any item above is not executed, keep release status as
`runtime proof pending`.

2026-06-25 release decision:

- Keep release status below upload-ready. Source implementation and fallback
  runtime proof exist, but accepted-source review, phone review, Grok/Gemini
  live import proof, publish packet review, and platform/upload evidence are
  not complete.


## Static Local Gate Hardening Checks

Run these before claiming the local dashboard gates are meaningful, even when the dashboard is not currently started:

```bash
python3 -m py_compile worker/bridge/human_operator_mvp.py worker/bridge/routes_human_operator.py worker/bridge/auto_studio.py worker/bridge/routes_auto_studio.py worker/bridge/production_status.py worker/bridge/routes_gates.py worker/bridge/thin_production_loop.py worker/bridge/grok_browser_proof.py worker/render/production_gate_orchestrator.py
pytest -q tests/test_human_operator_p0_routes.py tests/test_auto_studio_routes.py tests/test_production_status_routes.py tests/test_thin_production_loop.py tests/test_production_gate_orchestrator.py tests/test_dashboard_ia_contract.py
./node_modules/.bin/tsc --noEmit
```

Static pass means source/import proof, render artifact binding, phone review, publish packet, and stale production-status handling have source-level regression coverage. It does **not** prove the Windows bridge, dashboard, signed-in Grok/Gemini browser flow, phone watch, or upload/platform evidence. Those remain runtime checklist items below.

2026-06-26 Codex static result:

- PASS: bridge/render `py_compile` gate.
- PASS: focused pytest gates for human-operator, Auto Studio, dashboard contract, production status, thin loop, and render orchestrator.
- PASS: `./node_modules/.bin/tsc --noEmit`.
- PASS: `npm run build` after restoring Rollup optional native package `@rollup/rollup-linux-x64-gnu` in current `node_modules`.
- NOT RUN: Windows-local bridge/dashboard runtime proof, signed-in Grok/Gemini flow, phone-watch proof, and platform upload proof.
