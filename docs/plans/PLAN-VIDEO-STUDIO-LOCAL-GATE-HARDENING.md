---
plan_id: VIDEO-STUDIO-LOCAL-GATE-HARDENING
project: video-studio
status: IN_PROGRESS
status_reason: Static local dashboard gate hardening and full Vite build are verified; Windows runtime proof remains pending.
milestones:
  - { id: M0, label: "Static bypass audit and red-test map", done: true }
  - { id: M1, label: "Source and import proof validation hardening", done: true }
  - { id: M2, label: "Render, phone review, and publish lineage gate", done: true }
  - { id: M3, label: "Dashboard truth-source and stale-state repair", done: true }
  - { id: M4, label: "Static quality gate suite and GitHub-local checklist", done: true }
decisions_pending: []
blockers:
  - Windows-local bridge/dashboard runtime proof was not run.
depends_on: []
git_strategy: sub-repo
last_verified: 2026-06-26
ko_translation:
  status_reason_ko: "로컬 대시보드 게이트 정적 강화와 전체 Vite 빌드는 검증됐고, Windows 런타임 증명은 대기로 남는다."
  milestones_ko:
    - { id: M0, label_ko: "정적 우회 감사와 실패 테스트 맵" }
    - { id: M1, label_ko: "소스 및 가져오기 증거 검증 강화" }
    - { id: M2, label_ko: "렌더, 폰 리뷰, publish 계보 게이트" }
    - { id: M3, label_ko: "대시보드 truth-source 및 stale 상태 수정" }
    - { id: M4, label_ko: "정적 품질 게이트 묶음과 GitHub 로컬 체크리스트" }
  decisions_pending_ko: []
  blockers_ko:
    - "Windows 로컬 bridge/dashboard 런타임 증명은 실행하지 못했다."
---

# Plan — Local Gate Hardening

> **Goal (testable)**: Local dashboard gates must not be passable by arbitrary form values or stale UI state. Without starting the local dashboard, static tests must prove the main source, render, phone-review, and publish bypass cases fail.
> **Owner**: User (Decider) + Codex executor for this scoped slice; Claude Code or user handles final push/review as usual.
> **Created**: 2026-06-26

## Background

The recent Video Studio work tightened production gates around the server production read-model, thin-loop status, Grok browser proof classification, phone review, and publish packet requirements. That direction is correct, but a local dashboard quality gate is only valuable if the code cannot be bypassed by filling loose fields, trusting stale client state, or treating an unverified local path as production proof.

This plan covers work that can be done before a local dashboard runtime is available: source inspection, route-level validators, focused tests, TypeScript checks, and documentation/checklist alignment. It deliberately separates static proof from runtime proof. Windows-local bridge/UI smoke, signed-in Grok/Gemini proof, phone review, and upload/platform evidence remain later runtime gates.

## Compatibility Decision

- No DB schema, dependency, `.env`, paid-provider, external upload, or git push changes are in scope.
- `/api/human-operator/*`, `/api/auto-studio/*`, `/api/production/status`, and `/api/production/thin-loop/status` are local dashboard contracts. Tighten validation while preserving response shapes where practical.
- Persisted local JSON/storage entries are not deleted. Legacy accepted evidence should be surfaced as `unvalidated` or blocked with a repair action instead of being silently trusted.
- If implementation requires route response shape removal, exported-name removal, dependency add/remove, or live runtime contract changes, stop for explicit approval.

## Approach

### Phase M0 — Static Bypass Audit and Red-Test Map

- Re-check the current gate sources around source review, import proof, render result, phone review, publish packet, production status, thin-loop, and dashboard refresh/fallback behavior.
- Convert each bypass concern into a focused failing test target before changing production logic.
- **Acceptance**: A short implementation checklist exists in the test names or test comments, covering arbitrary source path, Grok `/c/*`, nonexistent render path, stale production status, and publish-without-lineage cases.

### Phase M1 — Source and Import Proof Validation Hardening

- Add shared local proof validation for source review and Auto Studio imports: allowed storage/import roots, file existence, extension, MIME or magic-byte where cheap, size cap, provenance, and browser-proof classification.
- Keep `/c/*` Grok routes blocked; accept browser proof only when generation and import evidence is present.
- **Acceptance**: Source review cannot pass with an arbitrary local path, missing file, unsafe extension, oversized import, native-download/browser prompt proof, or Grok `/c/*` page.

### Phase M2 — Render, Phone Review, and Publish Lineage Gate

- Bind phone review to a known render artifact instead of trusting only `renderId`, `renderPath`, or checked booleans.
- Require publish packet `uploadAllowed=true` to be derived from validated source proof, validated render artifact, accepted phone review, and publish metadata/disclosure gates.
- Preserve legacy evidence by flagging it as repairable, not by deleting it.
- **Acceptance**: Publish readiness stays blocked when render output is missing, source proof is unvalidated, phone review points at another artifact, or metadata/disclosure is incomplete.

### Phase M3 — Dashboard Truth-Source and Stale-State Repair

- Make the server production read-model the primary truth source for gate panels.
- Refresh production status after gate-affecting actions and mark stale/fallback UI state explicitly when the bridge fetch fails.
- Avoid showing an old `nextAction` as current after `/api/production/status` fails.
- **Acceptance**: UI tests or static contract tests prove fallback/stale state is visible and does not look like a clean pass.

### Phase M4 — Static Quality Gate Suite and GitHub-Local Checklist

- Add or update focused pytest and TypeScript checks for the new validators and dashboard contract.
- Document the static-vs-runtime boundary in the Windows/GitHub checklist: what contributors can verify without providers, and what remains local runtime proof.
- Consider a lightweight local static gate command only if it reuses existing dependencies; do not add dependencies in this plan.
- **Acceptance**: The static command list is copyable for a GitHub user, avoids paid providers, and does not claim runtime readiness.

## Implementation Gap Status

The original spec-gap checklist is resolved into the implementation status below.
This plan remains open only for runtime/build proof blockers, not for additional
static gate coding.

### Resolved Static Scope

- [x] Loose local evidence is not deleted. Legacy accepted rows are treated as
  unvalidated until repaired.
- [x] No dependencies were added. The checker and validators use the existing
  Python/pytest stack and standard library where possible.
- [x] No package-level npm script was added. The Windows checklist keeps raw
  copyable commands, and `scripts/check-project-plan-sync.py` covers plan/docs
  drift.
- [x] Auto Studio local import size is capped at 200 MB.
- [x] Import proof uses cheap local magic-byte checks for PNG and MP4; no
  network probing is involved.
- [x] Demo Mode was preserved by focused route tests and explicit render-proof
  boundaries.
- [x] UI stale-state repair is limited to the production gate/status panels.
- [x] Persisted legacy JSON is not destructively migrated.
- [x] Each hardened gate has a focused negative test or source-level contract
  assertion.
- [x] Final handoff labels runtime proof as not run unless Windows local servers
  are actually started.

### Remaining Runtime Or Environment Blockers

- [ ] Windows-local bridge/dashboard runtime proof must still be run by the
  operator.
- [ ] Signed-in Grok/Gemini generate/import proof remains operator-owned runtime
  proof.
- [ ] Phone full-watch review, publish packet inspection, and upload/platform
  evidence remain release blockers.

### Resolved Environment Checks

- [x] `npm run build` passed on WSL after restoring the missing Rollup Linux
  optional native package in the current `node_modules`.

### Edge Cases Covered By Static Validators

- Paths outside project storage, missing files, zero-byte files, unsupported
  extensions, stale local source proof after file deletion, surface-only browser
  proof, Grok `/c/*` redirects, native download prompts, render artifact
  mismatch, and stale server production status are blocked or surfaced as
  repairable states.

## Implementation Status — 2026-06-26

Static implementation is complete for this slice. The source review gate now revalidates local proof files at status-read time, Auto Studio imports reject invalid magic bytes and oversized payloads, render/phone/publish readiness is bound to an existing current render artifact, and dashboard panels clear stale server truth when `/api/production/status` fails.

Verification evidence:

- `python3 -m py_compile ...` passed for the bridge/render gate modules.
- `pytest -q tests/test_human_operator_p0_routes.py tests/test_auto_studio_routes.py tests/test_dashboard_ia_contract.py` passed: 22 tests.
- `pytest -q tests/test_production_status_routes.py tests/test_thin_production_loop.py tests/test_production_gate_orchestrator.py` passed: 14 tests.
- `./node_modules/.bin/tsc --noEmit` passed.
- `npm run build` passed after restoring Rollup's optional native package `@rollup/rollup-linux-x64-gnu` in current `node_modules`.
- Windows-local bridge/dashboard runtime proof was not run.

## Acceptance Criteria (overall)

- [x] Arbitrary local/direct source proof cannot mark source workflow ready.
- [x] Grok `/c/*` and surface-only browser proof remain blocked or pending, never accepted.
- [x] Phone review cannot pass unless it references a known render artifact.
- [x] Publish packet cannot allow upload unless source, render, phone review, and publish metadata are all validated.
- [x] Dashboard gate panels do not silently show stale server status as current truth.
- [x] Focused `py_compile`, pytest, and TypeScript checks pass or blockers are reported precisely.
- [x] Runtime proof is not claimed until Windows-local dashboard and bridge are started and smoked.

## Verification Plan

Static-only verification before local runtime is available:

```bash
python3 -m py_compile worker/bridge/human_operator_mvp.py worker/bridge/routes_human_operator.py worker/bridge/auto_studio.py worker/bridge/routes_auto_studio.py worker/bridge/production_status.py worker/bridge/routes_gates.py worker/bridge/thin_production_loop.py worker/bridge/grok_browser_proof.py worker/render/production_gate_orchestrator.py
pytest -q tests/test_human_operator_p0_routes.py tests/test_auto_studio_routes.py tests/test_production_status_routes.py tests/test_thin_production_loop.py tests/test_production_gate_orchestrator.py tests/test_dashboard_ia_contract.py
./node_modules/.bin/tsc --noEmit
git diff --check -- AGENT_TASK_BOARD.md docs/plans/PLAN-VIDEO-STUDIO-LOCAL-GATE-HARDENING.md worker app tests docs
```

Attempt only if dependencies are already usable in the current environment:

```bash
npm run build
```

Runtime verification remains separate and must not be claimed in this static slice:

```text
Windows Terminal 1: npm run bridge
Windows Terminal 2: npm run dev
Browser: http://127.0.0.1:5160
Smoke: /api/health, /api/production/status, dashboard gate panels, Demo Mode render, source review, phone review, publish packet
```

## References

- `projects/video-studio/AGENT_TASK_BOARD.md`
- `projects/video-studio/docs/WINDOWS-TEST-CHECKLIST.md`
- `projects/video-studio/docs/HUMAN-OPERATOR-PRODUCTION-PLAN.md`
- `projects/video-studio/docs/reference/dashboard-ux-ia.md`
- `projects/video-studio/worker/bridge/human_operator_mvp.py`
- `projects/video-studio/worker/bridge/auto_studio.py`
- `projects/video-studio/worker/bridge/production_status.py`
- `projects/video-studio/worker/bridge/thin_production_loop.py`
- `projects/video-studio/worker/bridge/grok_browser_proof.py`
- `projects/video-studio/worker/render/production_gate_orchestrator.py`

## Notes

> Generated by `/plan-new video-studio local-gate-hardening` on 2026-06-26, then filled by Codex in the same PLAN-classified turn.
> Lint command: `python scripts/parse-plan-frontmatter.py --lint projects/video-studio/docs/plans/PLAN-VIDEO-STUDIO-LOCAL-GATE-HARDENING.md`
> Update fields atomically after implementation: `python scripts/frontmatter-write.py projects/video-studio/docs/plans/PLAN-VIDEO-STUDIO-LOCAL-GATE-HARDENING.md --status SHIPPED --reason "..."`
