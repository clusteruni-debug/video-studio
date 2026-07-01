# Video Studio Changelog

## 2026-06-25

- Added `/api/production/status` as the canonical server read-model for Home and shared workflow gate panels.
- Added `/api/production/thin-loop/status` and `thin_production_loop.py` to lock the minimal material -> rough-cut dry-run -> accepted source -> render candidate -> phone review contract.
- Added `grok_browser_proof.py` so Grok `/imagine` surface proof and `/c/*` redirect blockers are classified consistently outside the oversized Grok route module.
- Tightened production-gate publish readiness so phone review proof is required before publish/final readiness can advance.
- Added the first P0 human-operator surface: `/api/human-operator/status`, setup status, no-LLM demo packet preparation, local source proof summary, render health summary, and a Home dashboard panel.
- Expanded the human-operator MVP surface with provider readiness, accepted-source review, demo render wrapper, categorized render health, phone review evidence, publish packet blockers, operator blocker summary, and workflow panels on Sources/Edit/Review.
- Added human-mode residual worklist and adapter command readiness surfaces so Wan/Gemini setup gaps, Grok proof gaps, live-channel evidence gaps, and bottled-water v6 render proof stay visible without claiming runtime completion.
- Hardened accepted-source review so browser proof cannot be accepted when it depends on surface-only evidence, Grok `/c/*` redirects, or native Chrome Download/Save/Export prompts.
- Added Auto Studio MVP routes and Home UI: `/api/auto-studio/providers`, `/api/auto-studio/run`, `/api/auto-studio/status`, and `/api/auto-studio/latest` now connect topic discovery, prompt compilation, editable scene drafts, optional smoke render, and a provider registry with Grok as a manual handoff provider plus Seedance/custom external slots.
- Added GitHub-facing human quickstart and troubleshooting docs for no-provider Demo Mode.
- Verification for this pass intentionally excludes `npm run build`; use focused pytest, py_compile, and TypeScript checks before Windows runtime smoke.

## 2026-06-15

- Added Navigator-style project documentation surfaces for workspace-wide standardization.
- Current default verification remains `npm run build`; Python worker changes should also run focused `pytest` or `compileall` checks as appropriate.
- Added `agent_docs/domain-map.md` to separate UI, bridge routes, worker rendering, source acquisition, storage artifacts, and quality-gate ownership.
- Added `agent_docs/test-scenarios.md` for render quality, source-first proof, bridge/API, UI review, and upload-candidate smoke checks.
- Added `docs/deploy.md` to document the local worker/UI runtime and operator smoke sequence.
- This documentation pass is intentionally separate from ongoing render-pipeline work already tracked by active video-studio tasks.
- Future media-source policy or upload-readiness changes should update scenario docs together with tests so evidence remains queryable by both Claude Code and Codex.
