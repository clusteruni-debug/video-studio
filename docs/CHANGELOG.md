# Video Studio Changelog

## 2026-06-15

- Added Navigator-style project documentation surfaces for workspace-wide standardization.
- Current default verification remains `npm run build`; Python worker changes should also run focused `pytest` or `compileall` checks as appropriate.
- Added `agent_docs/domain-map.md` to separate UI, bridge routes, worker rendering, source acquisition, storage artifacts, and quality-gate ownership.
- Added `agent_docs/test-scenarios.md` for render quality, source-first proof, bridge/API, UI review, and upload-candidate smoke checks.
- Added `docs/deploy.md` to document the local worker/UI runtime and operator smoke sequence.
- This documentation pass is intentionally separate from ongoing render-pipeline work already tracked by active video-studio tasks.
- Future media-source policy or upload-readiness changes should update scenario docs together with tests so evidence remains queryable by both Claude Code and Codex.
