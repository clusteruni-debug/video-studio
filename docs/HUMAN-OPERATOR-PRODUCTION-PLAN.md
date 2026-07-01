# Human Operator Production Plan

Status: implementation plan
Last verified: 2026-06-25
Audience: GitHub users, maintainers, and non-agent human operators

This document defines the work required to make Video Studio usable by a human
operator who does not have Claude Code, Codex, or another LLM coding agent
available. It is a project documentation plan, not a tracked workspace
`PLAN-*` frontmatter file.

## Purpose

Video Studio currently works best as an AI-agent-assisted production tool. A
human can run pieces of it, but an agent still absorbs too many hidden jobs:
reading task history, deciding the next blocker, interpreting JSON gates,
diagnosing local runtime drift, creating proof packets, and translating test
results into production actions.

The target is a human-operable local production tool:

1. A GitHub user can clone the project and reach a working local dashboard.
2. The first successful path does not require Claude Code, Codex, Grok, Gemini,
   CapCut automation, paid APIs, or hidden local state.
3. The dashboard explains the current production state, the next action, the
   missing proof, and the repair path without requiring source-code inspection.
4. Optional AI providers and browser handoffs are accelerators, not mandatory
   prerequisites.

## Current Reality

The product is already organized around a Windows-first local runtime:

- React/Vite dashboard on `127.0.0.1:5160`.
- Python bridge on `127.0.0.1:5161`.
- Local `storage/` folders for inputs, cache, renders, approval packets, and
  proof artifacts.
- FFmpeg composition for local 9:16 draft renders.
- Provider policy that blocks paid providers unless explicitly enabled.
- Canonical production read-model at `/api/production/status`.
- Thin-loop proof endpoint at `/api/production/thin-loop/status`.
- Publish readiness that now requires phone review proof.

The gap is not only missing code. The human workflow is still too dependent on
agent interpretation. A non-agent user needs a productized path through setup,
sample content, provider readiness, source import, rendering, review, and
publish readiness.

## Today: Agent-Assisted Flow

When Claude Code or Codex operates Video Studio, the practical flow is:

1. Read project rules, task board rows, diary entries, active approval packet,
   and recent source changes.
2. Infer the current blocker from stored packets, tests, runtime state, and
   source-code gates.
3. Run bridge/UI/tests in the correct environment.
4. Decide whether source proof is real or only preview evidence.
5. Create or repair production artifacts under `storage/`.
6. Explain why the render is blocked, pending, or reviewable.
7. Record verification and handoff notes for the next operator.

That is too much invisible work for a GitHub user. The dashboard and local
scripts must absorb these decisions.

## Target Human Flow

The default human flow should be:

1. **Install and open**
   - Clone the repository.
   - Run one setup check.
   - Start the bridge and dashboard.
   - See a first-run screen if anything critical is missing.
2. **Choose a mode**
   - `Demo Mode`: no keys, no external AI, no browser handoff.
   - `Manual Production`: local upload, manual notes, optional free providers.
   - `Provider-Assisted`: optional browser/API providers with explicit status.
3. **Create or select material**
   - Start from sample material, a typed idea, or a saved material packet.
   - See source requirements before planning.
4. **Plan the rough cut**
   - Use deterministic templates when no planner key exists.
   - Use Gemini/sample planner only when configured and disclosed.
5. **Acquire sources**
   - Prefer local upload or accepted local files.
   - Use browser handoff only when the UI can show the required proof state.
6. **Render a candidate**
   - Run a local draft render.
   - See FFmpeg/tool errors as repairable actions.
7. **Review on phone**
   - Complete full-watch review.
   - Record source fit, captions, audio, pacing, and disclosure decisions.
8. **Prepare publish packet**
   - Produce an upload packet only after required evidence exists.
   - Keep final upload as an operator-owned action.

## Tool Inventory And Required Product Features

| Surface | Human function | Current readiness | Required improvement |
|---|---|---|---|
| First-run setup check | Tells a new user what is installed, missing, or misconfigured | Partially covered by README and scripts | Add one dashboard/API setup wizard with Node, Python, FFmpeg, ports, storage, and provider checks |
| Dashboard home | Answers "what should I do next?" | `/api/production/status` exists and UI consumes it | Convert status into one primary next-action card with repair buttons and artifact links |
| Thin production loop | Enforces material -> dry-run -> source -> render -> phone review | Endpoint exists | Add human-readable UI copy and sample packets for each loop state |
| No-LLM demo path | Lets GitHub users prove the app works without AI accounts | Not yet productized | Add deterministic sample material, local assets, template plan, render manifest, and demo render action |
| Provider readiness matrix | Explains optional provider availability | Bridge has provider/tool diagnostics in several places | Normalize provider states as ready, config-required, manual-only, paid-opt-in, blocked, or unknown |
| Local source import | Lets users use their own media without browser automation | Upload/render paths exist | Add a simple accepted-source workflow with provenance, preview, and "use in scene" state |
| Browser handoff | Lets users use Grok/Gemini/CapCut manually | Existing code has handoff/proof rails, but blockers are complex | Productize manual proof states and never treat chat-thread redirects or previews as accepted source proof |
| Render/FFmpeg health | Makes render failures understandable | Render reports and logs exist | Add a render health panel with last command, output path, log excerpt, missing tool, and retry action |
| Phone review | Blocks publish until a human watches the result | Gate exists in source | Add a visible review form and persist review evidence beside the render candidate |
| Publish packet | Collects title, description, disclosure, and evidence | Existing gate/publish packet concepts exist | Add a human-facing packet viewer and "not upload-ready because..." states |
| GitHub onboarding | Helps users install and run without agent context | README is useful but still assumes operator familiarity | Add quickstart, troubleshooting, demo-mode screenshots, and exact environment expectations |
| CI/source checks | Prevents regressions for contributors | Focused tests exist | Add lightweight CI gates that avoid paid providers and heavy runtime assumptions |

## What The Product Must Take Over From Agents

The following tasks should become dashboard or script behavior:

- Interpret the active production state from `/api/production/status`.
- Detect stale bridge/UI builds and show a restart instruction.
- Explain missing material, source, render, review, and publish evidence.
- Distinguish accepted local files from browser previews.
- Distinguish Grok `/imagine` surface proof from `/c/*` redirect blockers.
- Record local proof artifacts without requiring users to know storage paths.
- Expose FFmpeg, Python, Node, and port problems in plain language.
- Make the first successful render path possible without external AI.
- Keep paid providers disabled unless the user explicitly opts in.
- Provide durable troubleshooting docs for common setup failures.

## Implementation Milestones

### M0. Human Mode Contract

Goal: define the product promise for non-agent users.

Work items:

- Add a short `Human Mode` definition to the dashboard copy and docs.
- Define three product modes: `Demo Mode`, `Manual Production`, and
  `Provider-Assisted`.
- Document that Claude Code/Codex are maintainer tools, not required runtime
  dependencies.
- Define the evidence boundary for local upload, browser proof, generated
  source, render candidate, phone review, and publish packet.

Probable files:

- `docs/HUMAN-OPERATOR-PRODUCTION-PLAN.md`
- `README.md`
- `docs/OPERATOR-CHECKLIST.md`
- `app/ui/src/components/*`

Done when:

- A new reader can explain which mode requires no AI accounts.
- The dashboard does not imply that Codex/Claude is required to run the app.

Verification:

- Documentation review.
- UI text contract test if the mode appears in the dashboard.

### M1. First-Run Setup Wizard

Goal: make install/runtime drift visible before a user hits broken features.

Work items:

- Add a bridge endpoint such as `/api/setup/status`.
- Check Python, Node/npm, FFmpeg, project root, writable `storage/`, configured
  ports, optional provider keys, and paid-provider opt-in.
- Add a dashboard first-run panel shown when critical checks fail.
- Add a one-command local script for Windows setup diagnostics.
- Keep `.env` manual-only; never write secrets from the app.

Probable files:

- `worker/bridge/routes_setup.py`
- `worker/bridge/server.py`
- `app/ui/src/components/SetupWizardPanel.tsx`
- `scripts/check-human-setup.ps1`
- `docs/GETTING-STARTED-HUMAN.md`

Done when:

- A fresh user sees exactly what is missing and what command or manual step
  fixes it.
- Missing optional providers do not block Demo Mode.

Verification:

- `python3 -m py_compile worker/bridge/routes_setup.py`
- Focused route tests for all setup states.
- TypeScript check for setup UI.
- Windows smoke: setup endpoint and first-run panel render.

### M2. No-LLM Demo Path

Goal: provide one complete local path that requires no provider account.

Work items:

- Add a bundled sample material packet.
- Add a deterministic template planner for the demo path.
- Add sample local visual/audio assets or generated title-card fallback data.
- Add a "Create demo project" dashboard action.
- Render a local MP4 candidate using only bundled/local inputs and FFmpeg.
- Store demo artifacts under a predictable project id.

Probable files:

- `worker/bridge/routes_demo.py`
- `worker/planner/template_planner.py`
- `assets/samples/human-demo/**`
- `app/ui/src/components/DemoModePanel.tsx`
- `tests/test_human_demo_flow.py`

Done when:

- A user can clone, run setup, click demo, and produce a draft render without
  Gemini, Grok, Claude, Codex, CapCut, or paid APIs.
- The resulting dashboard state still labels the result as a demo draft, not an
  upload-ready production candidate.

Verification:

- Focused demo route tests.
- Python compile checks.
- TypeScript check.
- Windows runtime smoke with bridge and dashboard.
- Optional `npm run build` when allowed by the operator.

### M3. Provider Readiness Matrix

Goal: make optional providers understandable and non-blocking.

Work items:

- Normalize all provider/tool status into a shared status model.
- Group providers by function: planning, image, video, TTS, BGM, SFX, edit,
  export.
- Label each provider as `ready`, `config-required`, `manual-only`,
  `paid-opt-in`, `blocked`, or `unknown`.
- Show whether a provider is needed for Demo Mode, Manual Production, or
  Provider-Assisted mode.
- Add repair copy for missing keys, missing commands, and paid opt-in.

Probable files:

- `worker/media/runtime.py`
- `worker/bridge/routes_health.py` or a new provider route
- `app/ui/src/components/ProviderReadinessPanel.tsx`
- `tests/test_provider_readiness.py`

Done when:

- The user can tell which tools are optional and which current workflow step is
  blocked.
- Paid providers cannot be mistaken for default required dependencies.

Verification:

- Provider status unit tests.
- UI contract tests for required labels.
- Manual smoke with no keys configured.

### M4. Dashboard Next-Action UX

Goal: turn production status into a human next step.

Work items:

- Promote `/api/production/status` to the only default Home source of truth.
- Add one primary next-action card with action, reason, blocker, and repair
  target.
- Convert workflow gate rows into stage-specific action buttons.
- Add stale bridge/build warning when the UI cannot see current bridge fields.
- Keep raw JSON under Advanced only.

Probable files:

- `app/ui/src/components/ProductionGateStatusPanel.tsx`
- `app/ui/src/components/ProductionWorkflowGatePanel.tsx`
- `app/ui/src/lib/bridge.ts`
- `tests/test_dashboard_ia_contract.py`

Done when:

- The first screen answers what the operator should do next.
- A blocked state includes a repair action, not only a failed check name.

Verification:

- Dashboard IA contract tests.
- TypeScript check.
- Browser smoke on Home, Sources, Edit, and Review.

### M5. Source Import And Proof Workflow

Goal: make accepted source evidence understandable and repeatable.

Work items:

- Add a local source intake panel for operator-owned files.
- Persist source provenance: local upload, generated browser proof, direct
  import, stock source, or placeholder.
- Add accepted/rejected review decisions per source.
- Productize browser handoff proof: surface proof is not generation proof, and
  generation proof is not accepted local MP4 proof.
- Keep Grok `/c/*` redirects blocked for source proof.
- Keep native download dialogs operator-owned; the app should not claim
  repeatable automation through them.

Probable files:

- `worker/bridge/routes_sources.py`
- `worker/bridge/grok_browser_proof.py`
- `worker/bridge/routes_grok.py`
- `app/ui/src/components/SourceReviewPanel.tsx`
- `tests/test_source_proof_workflow.py`

Done when:

- A user can upload a local file, preview it, accept it for a scene, and see the
  thin-loop source stage pass.
- Browser preview-only evidence never passes as accepted source.

Verification:

- Focused source route tests.
- Thin-loop tests.
- Manual upload smoke.

### M6. Render And FFmpeg Recovery

Goal: make local render failures repairable without agent diagnosis.

Work items:

- Add render status summary: last manifest, last command, output path, log path,
  FFmpeg availability, and failure category.
- Surface missing FFmpeg, missing source file, invalid manifest, subtitle
  errors, audio errors, and write-permission errors separately.
- Add a safe retry action that reuses the latest accepted manifest.
- Split oversized render helper modules only when tests first lock behavior.

Probable files:

- `worker/render/compose.py`
- `worker/render/compose_ffmpeg.py`
- `worker/render/render_status.py`
- `worker/bridge/routes_media.py`
- `app/ui/src/components/RenderHealthPanel.tsx`
- `tests/test_render_health.py`

Done when:

- A failed render tells the operator the concrete next repair step.
- The user can find the produced MP4 and log without reading source code.

Verification:

- Focused render health tests.
- FFmpeg missing-tool fixture.
- Windows smoke render after code changes.

### M7. Phone Review And Publish Packet UX

Goal: turn final readiness into an explicit human review workflow.

Work items:

- Add a phone review form for full-watch evidence.
- Persist review fields: device, reviewer, render id, watched duration,
  captions, source fit, audio, pacing, disclosure, decision, and notes.
- Add a publish packet viewer that shows title, description, hashtags,
  disclosure, source proof, render proof, and remaining blockers.
- Keep upload as an operator-owned action.

Probable files:

- `worker/render/production_gate_orchestrator.py`
- `worker/bridge/routes_review.py`
- `app/ui/src/components/PhoneReviewPanel.tsx`
- `app/ui/src/components/PublishPacketPanel.tsx`
- `tests/test_phone_review_publish_gate.py`

Done when:

- Publish readiness cannot pass without phone review evidence.
- The Review tab can explain exactly why a render is not upload-ready.

Verification:

- Publish gate tests.
- Thin-loop tests.
- Manual review packet smoke.

### M8. GitHub Onboarding Package

Goal: make the repository understandable without private workspace context.

Work items:

- Add a human quickstart document.
- Update README so the first path is Demo Mode, not agent-assisted production.
- Document ports, supported OS, required tools, optional provider keys, paid
  provider policy, storage folders, and cleanup expectations.
- Add troubleshooting for missing optional Rollup native package, missing
  Python packages, stale bridge, port collision, FFmpeg missing, and browser
  handoff limitations.
- Add screenshots or textual walkthrough once the UI path is stable.

Probable files:

- `README.md`
- `docs/GETTING-STARTED-HUMAN.md`
- `docs/TROUBLESHOOTING.md`
- `docs/OPERATOR-CHECKLIST.md`

Done when:

- A GitHub user can identify the supported first run path in under five
  minutes.
- The docs do not require reading the workspace diary or task board.

Verification:

- Docs review against a clean-clone checklist.
- Link/path check.
- Optional reader test with only the README and quickstart.

### M9. Infrastructure And Code Cleanup

Goal: make future human-mode work maintainable.

Work items:

- Keep canonical read-model logic in small modules.
- Split route files by user workflow, not by historical implementation pile-up.
- Split render helpers only after tests lock current output contracts.
- Add shared JSON contracts for status, setup, provider readiness, source proof,
  render status, phone review, and publish packet where useful.
- Avoid dependency changes until a milestone explicitly needs one and receives
  separate approval.

Probable files:

- `worker/bridge/production_status.py`
- `worker/bridge/thin_production_loop.py`
- `worker/bridge/routes_gates.py`
- `worker/bridge/routes_grok.py`
- `worker/bridge/routes_media.py`
- `worker/render/*`
- `shared/contracts/*`

Done when:

- Human-mode features can be changed without editing oversized route/render
  modules for every small UI state.
- Tests cover the behavior before and after each split.

Verification:

- Focused pytest for moved behavior.
- TypeScript check for changed contracts.
- `git diff --check`.

### M10. Verification And Contributor Gates

Goal: give maintainers proof without requiring paid services.

Work items:

- Define a lightweight source gate for PRs.
- Keep heavy render/runtime smoke as a manual or Windows-local gate.
- Add fixture-based tests for no-key/no-provider environments.
- Add dashboard contract tests for human-mode labels and next-action states.
- Document exactly which commands are required before claiming code complete.

Recommended gates:

- Python compile for changed worker files.
- Focused pytest for changed routes/gates/render helpers.
- `./node_modules/.bin/tsc --noEmit` for UI/contract changes.
- `npm run build` when allowed and when the local dependency state supports it.
- Windows runtime smoke for bridge, dashboard, demo render, and phone review
  before human-mode release.

Done when:

- Contributors can run a documented no-provider verification stack.
- Runtime verification remains clearly separate from source-only checks.

## MVP Delivery Order

P0:

1. First-run setup wizard.
2. No-LLM demo project.
3. Dashboard next-action card backed by `/api/production/status`.
4. Local source import with accepted-source proof.
5. Render health panel for the demo path.

Implementation update on 2026-06-25:

- P0 foundation is now partially implemented through `/api/human-operator/status`,
  `/api/human-operator/setup-status`, `/api/human-operator/demo/status`, and
  `/api/human-operator/demo/prepare`.
- The Home dashboard now includes a `Human operator P0` panel that surfaces
  first-run setup, no-LLM demo readiness, local source proof count, and render
  health.
- The demo endpoint prepares a deterministic render-smoke payload and material
  packet only. It does not run FFmpeg, does not create an upload candidate, and
  does not satisfy phone review or publish readiness.
- Remaining P0 work: execute and verify the demo render on Windows, add a
  fuller accepted-source review UI, and expand render failure categorization
  beyond FFmpeg readiness plus last render paths.

Implementation update on 2026-06-25, source-level MVP slice:

- Added `/api/human-operator/provider-readiness` to separate Demo Mode, Manual
  Production, and Provider-Assisted readiness without treating paid/API tools as
  defaults.
- Added `/api/human-operator/sources/status` and
  `/api/human-operator/sources/review` for accepted/rejected local source
  decisions. Browser surface-only proof and Grok `/c/*` redirects still do not
  pass accepted-source proof.
- Added `/api/human-operator/demo/render` as a wrapper around the existing local
  render-smoke pipeline. It records demo render result artifacts but does not
  turn a demo draft into an upload candidate.
- Added `/api/human-operator/render-health` with failure categories for
  FFmpeg, missing source files, manifest errors, subtitle errors, audio errors,
  write permissions, active approval locks, and unknown failures.
- Added `/api/human-operator/phone-review`, phone review status, and
  `/api/human-operator/publish-packet`. Publish readiness stays blocked without
  accepted source proof, render proof, and accepted full-watch phone review.
- Added `/api/human-operator/operator-blockers` so existing Grok, Gemini,
  CapCut, Chrome, and stale board blockers are visible as operator blockers
  rather than hidden agent context.
- Added `/api/human-operator/adapter-command-readiness` so Wan, Gemini Flash,
  Pexels, Edge TTS, local BGM, and Freesound command readiness can be inspected
  without running those providers.
- Added `/api/human-operator/worklist` so the remaining docs-plan work is
  visible as operator tasks with explicit `requiresRuntimeProof` boundaries.
- Added dashboard panels on Home, Sources, Edit, and Review plus
  `docs/GETTING-STARTED-HUMAN.md`, `docs/TROUBLESHOOTING.md`, and
  `scripts/check-human-setup.ps1`.

Implementation update on 2026-06-25, Auto Studio operator-handoff slice:

- Auto Studio providers now separate `auto-route`, `command`,
  `operator-handoff`, `manual-import`, and `api` execution modes.
- Grok and Gemini are operator handoffs, not automatic generators. Their
  provider records expose `canGenerateNow=false`, local import requirements,
  proof boundaries, and a development-only browser-control proof rail.
- Auto Studio runs now produce a scene-level `handoffQueue`; handoff scenes are
  not render-ready until a local imported PNG/MP4 is attached as a
  `SceneAssetPayload`.
- Scene Director gives the operator scene-level `Open Provider`, `Copy Prompt`,
  `Mark Generated`, `Import File`, and `Use Fallback` controls without becoming
  a full NLE.
- Windows proof recorded bridge/dashboard startup, provider/latest endpoints,
  a blank-seed Grok handoff draft, setup/readiness endpoints, fallback demo
  render, and ffprobe on the generated demo MP4. Proof files:
  `storage/proof/operator-handoff-runtime-proof-20260625-214333.json` and
  `storage/proof/operator-handoff-runtime-demo-proof-20260625-214823.json`.
- Still required before release claim: accepted-source review save, phone review
  save, publish packet inspection, Grok/Gemini live generate/import proof by a
  human operator, live-channel fresh-source proof, and bottled-water v6
  render/CapCut handoff proof.
- Still not complete by source changes alone: real Wan command execution,
  optional Gemini Flash image execution, Grok `/imagine` generate/import proof,
  live-channel fresh-source/phone/platform proof, and bottled-water v6
  render/CapCut handoff proof.

Implementation update on 2026-06-26, plan/docs sync and local-gate hardening:

- `PLAN-VIDEO-STUDIO-LOCAL-GATE-HARDENING` is the active plan for source-level
  local dashboard gate hardening. Its static M0-M4 scope is implemented, but the
  plan remains `IN_PROGRESS` until Windows runtime proof and the full build
  blocker are resolved.
- Local source proof, Auto Studio import proof, render artifact proof, phone
  review proof, publish packet blockers, and dashboard stale-status behavior now
  have source-level validation or focused regression coverage.
- This source-level pass does not close the release criteria below. Accepted
  source review save, phone full-watch review, publish packet inspection,
  signed-in Grok/Gemini generate/import proof, and platform/upload proof remain
  runtime/operator-owned gates.

P1:

1. Phone review form.
2. Publish packet viewer.
3. Provider readiness matrix.
4. Human quickstart and troubleshooting docs.

P2:

1. Browser handoff UX polish.
2. CapCut/manual export proof workflow.
3. Larger route/render module splits.
4. CI refinement and screenshot-based onboarding.

## Non-Goals For This Plan

- No new DB, Supabase, remote persistence, or account system.
- No direct `.env` editing from code.
- No paid provider enablement by default.
- No dependency add/remove without separate approval.
- No claim that browser automation can fully replace operator-owned actions.
- No automatic publish/upload to an external platform.
- No hidden requirement that the user run Claude Code, Codex, or another LLM
  operator.

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Windows setup drift | Users cannot start the app | First-run setup wizard and clear troubleshooting |
| Optional provider confusion | Users think paid/API tools are required | Provider readiness matrix and Demo Mode first path |
| Browser handoff overclaim | Preview/chat evidence gets treated as source proof | Explicit proof states and blocked `/c/*` redirects |
| FFmpeg error opacity | Users cannot repair failed renders | Render health panel and categorized errors |
| Dashboard overload | Users still need an agent to interpret gates | One primary next action plus Advanced-only raw details |
| Storage growth | Local artifacts become unmanageable | Add storage browser and cleanup guidance in a later slice |
| Runtime proof gap | Source tests pass but product is not usable | Require Windows local smoke before release claims |

## Release Criteria For Human-Operable MVP

The first human-operable release is ready only when all are true:

- Fresh clone documentation leads to a running dashboard.
- Demo Mode renders a local draft without provider accounts.
- `/api/production/status` drives Home next-action UX.
- Local source upload can satisfy accepted-source proof.
- Phone review evidence is required before publish readiness.
- Publish packet UI explains remaining blockers.
- Setup, render, and provider failures are visible as repair actions.
- README and troubleshooting do not assume task-board or diary knowledge.
- Verification results distinguish source checks from Windows runtime proof.
