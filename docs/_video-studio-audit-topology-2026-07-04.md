# Video Studio — Full Audit + Topology (2026-07-04)

> **Durable audit reference** (per `audit-topology-first.md` rule). Written BEFORE any
> improvement decision so the findings survive session boundaries. Source: 10 parallel
> read-only code-review agents over ~130K LOC (128 .py + 39 .ts/tsx + 4 companion .js +
> 50 .md). This file is the decision reference for the improvement PLAN + grill-me.
>
> Scope: `projects/video-studio/`. Stack: React 19 + Vite 7 + TS 5.9 (UI :5160) /
> Python 3.14 Flask bridge (:5161) + FFmpeg / Chrome companion extension (manual Grok/Gemini handoff).

## §0 — Sources (10 audits, all read-only, grep-verified)

| # | Area | Files read | Verdict |
|---|---|---|---|
| A | routes_grok + prompt templates | routes_grok.py (14,443), templates.py, scene_generator.py | prompt flattening confirmed + 2 security CRITICAL |
| B | bridge server + API routes | server.py, routes_media.py (11,362), routes_episodes, gates, human_operator, sources, admin | 99 endpoints; error-handling + size debt |
| C | FFmpeg render | compose_ffmpeg.py (9,596), compose, subtitles, bgm, motion, transitions, capcut | 2 render CRITICAL (BGM, caption) + spec divergence |
| D | quality gates | golden_reference_gate.py (3,140) + 9 more gate files | **0 perceptual checks across ~77 gate keys** |
| E | planner + provider routing | ollama_planner, save_plan, adapters, auto_studio, human_operator_mvp, image_router... | **no real AI-video generation by default** |
| F | React UI + state | bridge.ts (4,330), SceneDetailPanel (3,729), RenderReviewPanel (3,008), StudioContext (2,538) + 25 more | dead export ~1,280 lines, god-context |
| G | CSS + design system | styles.css (5,279), DESIGN.md | 2 undefined vars (broken), 6 gradients, 35 font-sizes |
| H | test suite | tests/*.py (35,446 LOC, 674 tests) | only 3 tests run real ffmpeg; ffprobe mocked 69× |
| I | docs drift (4-axis) | 50 .md | agent cold-start doc is fiction; adapter count 3-way mismatch |
| J | companion + scripts + deps + hygiene | tools/chrome-grok-companion/*, scripts/*, deps, storage | SSRF bypass on Grok path; 178MB BGM git-tracked |

---

## §1 — CENTRAL FINDING (the quality mystery, solved)

**The user's complaint** ("dashboard videos are low quality; manually typing prompts into Grok was
better") is **structurally explained and evidence-backed**. Two compounding root truths:

1. **Nothing in the pipeline ever looks at the actual video.** Across ~77 quality-gate checks
   (audit D) and 674 tests (audit H), exactly **one** line of code opens a real media file to
   measure anything (`golden_reference_gate._audio_duration_seconds`, a WAV duration read). Every
   dB / loudness / continuity / motion number the gates validate is a **float the manifest author
   wrote by hand**. "38/38 pass" = "the JSON has every required field and the self-declared numbers
   clear their thresholds" — never "a human or model confirmed the video is good." A black,
   garbled, or muted render passes every gate and every test.

2. **The quality loss happens in ≥4 independent layers**, each real, each grep-confirmed (§2).

**Determining variable (Rule #15 branch — not a contradiction, a workflow split):** which loss layer
dominates depends on the user's actual workflow:
- **App-generated stills workflow** → Layer 1 dominates (no AI video at all; Ken Burns slideshow).
- **Grok-source-first workflow (what the user actually does)** → Layer 1 is bypassed (source *is*
  Grok video), so Layers 2 (prompt flattening) + 3 (render defects) dominate. This is exactly why
  "manual Grok prompt beat the app" — the app strips the creative language that helps (Layer 2).

---

## §2 — QUALITY-LOSS CHAIN (4 layers, headline finding)

### Layer 1 — No real AI-video generation by default  (audit E)
- Video adapters `wan` / `ltx-video` / `hunyuan-video` / `veo3` / `runway` in `worker/media/adapters.py`
  are **generic command-shell stubs** (`_normalize_mode` defaults to `"stub"`, ~L271-276). No built-in
  HTTP/generation client. Out of the box every "video" is a **still image/GIF + Ken Burns pan + TTS +
  subtitles** — categorically lower fidelity than native Grok Imagine video.
- `route_image()` only ever returns a still (Gemini-Flash-Image / Imagen / Pexels / Klipy). The scene
  "visual" step never calls a video model unless the operator hand-wires an external command.
- **Silent degradation**: when a scene downgrades to a still, no UI warning. Adapter `status`
  (`"placeholder"` vs `"generated"`) is never surfaced.

### Layer 2 — Grok prompt flattening  (audit A — confirms user hypothesis)
- `routes_grok._scene_prompt()` (L1205-1220) emits the **identical rigid English 3-clause template
  for every scene**, capped at `GROK_GENERATION_PROMPT_MAX_CHARS = 500`:
  `"{action}; first second: {motion}" / "Vertical 9:16 phone MP4, 4-6 seconds, one continuous shot, {camera}" / "{continuity}; leave an uncluttered lower-right background; no visible text or watermark"`.
- `_scene_prompt_quality()` (210-line gate) **actively strips** style vocabulary a human would use:
  `GROK_ABSTRACT_OR_META_PROMPT_TERMS` bans `"beautiful", "cinematic quality", "mood", "naturalistic",
  "vibe", "production", "tension"`; repair hint literally says *"Remove mood, intent, quality, AI-slop,
  and production-language phrasing."* This is an **anti-quality constraint vs manual Grok use**.
- For **13 of 17 template types**, the "visual seed" falls back to `image_prompt`, which templates.py
  documents as *"used for Google Image Search... write it like a search query, NOT an art prompt"*
  (e.g. `"Samsung 3nm chip wafer factory"`) — a search query wrapped verbatim into a video-gen prompt.
- `_prompt_join()` **silently drops trailing clauses** when >500 chars (no warning) — camera/continuity
  direction can vanish with no operator signal.

### Layer 3 — Render defects  (audit C — real FFmpeg bugs, affect ALL renders incl. Grok source)
- 🔴 **BGM near-inaudible**: `compose_ffmpeg.py:9470` `BGM_MIX_GAIN` default **0.55** vs
  `RENDERING-SPEC.md:250` mandated **1.55** — ~9 dB too quiet. (Spot-verified 2026-07-04.)
- 🔴 **Captions silently truncated mid-sentence**: `subtitles.py:191-218` `_wrap_korean` on >2-line
  overflow does `lines[1][:max_chars]` — any Korean TTS sentence >32 chars (typical) gets cut off in
  the actual production burn-in path.
- 🟡 **Ken Burns jitter**: zoompan applied to source image at native res with no upscale pre-pass
  (`compose_ffmpeg.py:8801-8823`, `9133-9157`) — the best-documented zoompan stutter cause.
- 🟡 Motion presets diverge from spec §5.3 (zoom rates/limits); spec's "no same motion 2× consecutive"
  rule has **no implementing code**. `_KO_PARTICLES` (particle-aware wrap) is **dead code** — masquerades
  as implemented.

### Layer 4 — Validation theater  (audits D + H — why nobody caught Layers 1-3)
- **Gates (D)**: ~77 named checks — **[MECH] ≈28, [PROXY] ≈49, [PERCEPTUAL] = 0**. Circular score
  derivation (manifest score == evidence score == derived score, all from the same self-authored
  booleans). `_check_media_evidence_file` = "extension + size ≥16 bytes" as "phone-review proof."
- **Tests (H)**: 674 tests, **0 `@pytest.mark.parametrize`** (→ copy-paste-per-scenario made a single
  14,697-line test file). ffprobe monkeypatched in **69** sites; only **3** tests run real ffmpeg (and
  they `pytest.skip` silently if ffmpeg absent). No test would catch a bad render, a silent sample-plan
  fallback, or a broken subtitle position.

---

## §3 — TOPOLOGY: file inventory + size-rule compliance

Workspace thresholds: **component 500 / service 660 / CSS 800** lines.

### Oversized files (the code-structure debt the user flagged as weakest)
| File | Lines | × over cap | Note |
|---|---|---|---|
| worker/bridge/routes_grok.py | 14,443 | **22×** | 77% is module-level helpers; 33 routes at tail; embedded 900-line JS blobs + hand-rolled CDP client |
| worker/bridge/routes_media.py | 11,362 | **17×** | full business modules inlined instead of `services/` |
| worker/render/compose_ffmpeg.py | 9,596 | **14×** | **~75% is misplaced gate/review code**, not FFmpeg |
| app/ui/src/lib/bridge.ts | 4,330 | 6.6× | 72 exported fns (14 dead) + ~155 types in one file |
| app/ui/src/components/SceneDetailPanel.tsx | 3,729 | 7.5× | **57 useState in one component** |
| worker/bridge/routes_episodes.py | 3,400 | 5× | 7 silent broad-excepts (convention violation) |
| worker/render/golden_reference_gate.py | 3,140 | 4.8× | 476 `fail` branches |
| app/ui/src/components/RenderReviewPanel.tsx | 3,008 | 6× | default export ~1,280 lines is **dead code** |
| app/ui/src/context/StudioContext.tsx | 2,538 | 3.8× | god-context, 21 consumers, full re-render blast radius |
| app/ui/src/styles.css | 5,279 | 6.6× | ~1,000 dead lines, 6 gradients, 35 font-sizes |
| + ~10 more py files 660-1,128 lines | | | subtitles, capcut_handoff, production_mode_gate, auto_studio, human_operator_mvp, save_plan... |

### Structural duplication (중복)
- **3 parallel scene-orchestrators**: `draft_executor.py` (CapCut) / `auto_studio.py` (ProjectPlan+handoff)
  / `human_operator_mvp.py` (demo path) — same "prompt→scenes→assets→save/render" shape reimplemented
  3×, no shared abstraction (~25-30% conceptual overlap).
- **3 parallel provider-readiness taxonomies** with different vocab (`ready`/`config-required`/`manual-only`
  vs `renderableNow`/`canGenerateNow`) — `ADAPTER_CONFIG` (19) vs `auto_studio.build_asset_provider_registry`
  (7) vs `human_operator_mvp.build_provider_readiness` — kept in sync by hand.
- **Path-containment check reimplemented 3×** (draft_executor / routes_media / routes_episodes) — security-relevant drift risk.
- **SSRF redirect-guard duplicated** (image_router / editorial) — extract to `worker/net/safe_fetch.py`.
- **`BRIDGE_URL` redefined in 7 files**; 6 components bypass typed `bridge.ts` + `_apiFetch` and raw-`fetch()` (no timeout).
- **Gate primitives (`_check`/`_fail`/`_text`/`_number`...) reimplemented 32× across 8 gate files.**
- Grok prompt template string re-authored in 2 places; BGM mixer duplicated (bgm.py `mix_audio` dead + different constants).

### Dead code (부족→delete)
- `RenderReviewPanel` default export (~1,280 lines, 0 importers).
- 14/72 `bridge.ts` exports (0 callers).
- `dalle3` adapter (registered, never selectable). `SceneSpec.routeHint` (computed, never read by router).
- 7 dead scripts (`local-bridge.mjs`, `verify-bridge.mjs`, `download-flux*.py`, `grok_video.py`, `flux-test.py`).
- 6 confirmed-dead CSS selector blocks (~sampled 20% dead ratio → ~1,000 lines extrapolated).
- Dead endpoints: `/api/route-plan`, `/api/save-project`, `/api/align-tts`, `/api/render-mp4` (0 callers repo-wide).
- Pipeline B (`ProjectPlan`/`ollama_planner` thin planner) unreachable from dashboard — CLI-only.

---

## §4 — SECURITY FINDINGS (highest priority — local HTTP surface)

| Sev | Location | Issue |
|---|---|---|
| 🔴 CRITICAL | routes_grok.py:6222-6245 `_launch_cdp_browser` | `browserExecutable` from request body → `subprocess.Popen(args)` gated only by client-supplied booleans. Arbitrary local executable launch. |
| 🔴 CRITICAL | routes_grok.py:12611 `bookmarklet-import` (GET, side-effecting) | Accepts any absolute dir + guessable `operatorApproved=true` + wildcard CORS → CSRF-reachable arbitrary local-directory file copy. |
| 🟡 HIGH | tools/chrome-grok-companion/content.js:670, 614 | **Prior SSRF fix's blind spot** — Grok content-script path bypasses the origin guard (Gemini + background paths are guarded). Handoff payload exfil to arbitrary origin; only gate is `commandUrl.includes("operatorApproved=true")`. |
| 🟡 HIGH | routes_grok.py (11 sites, 6 routes) | `Access-Control-Allow-Origin: *` + `Allow-Private-Network: true` — bypasses server.py's scoped CORS; opens local bridge to any web origin. |
| 🟡 MED | background.js | 6/9 message handlers skip `sender.id` validation; 3 accept caller-supplied `command` with endpoints. |
| 🟡 MED | worker/sources/news.py:32-35 | Query params concatenated into URL without `quote_plus` (param injection into upstream). |
| 🟡 MED | bridge.ts:3255 `_apiFetch`, storage.ts:16, GatesPanel.tsx:699 | `as T` at external boundary, no runtime shape validation. |

> All CRITICALs are auth-domain (subprocess/user-input) → **mandatory separate reviewer pass** per Rule #14
> before any fix ships. This audit is READ-ONLY; nothing was changed.

---

## §5 — WORKSPACE-RULE COMPLIANCE SCORECARD  (user-flagged as likely weakest — CONFIRMED)

The user's instinct is correct: **rule adherence is empirically the weakest dimension.** Data:

| Rule (workspace CLAUDE.md) | Limit | Actual | Verdict |
|---|---|---|---|
| Component file size | ≤500 | 4 files 3,008-3,729; +1 marginal | ❌ 4-7× over |
| Service file size | ≤660 | 8 py files 677-14,443 | ❌ up to 22× over |
| CSS file size | ≤800 | styles.css 5,279 | ❌ 6.6× over |
| Max 1 gradient / project | 1 | **6 distinct gradients** | ❌ 6× over |
| CSS variables, never hardcoded color | 100% | 2 raw hex + ~117 rgba literals + 6 inline-TSX colors | ❌ ~14% hardcoded |
| **CSS vars must be defined** | — | `--danger`, `--bg-panel` used but **never declared** (3 sites) | ❌ **broken fail-state render** (spot-verified) |
| Hover = bg/border only (no transform/scale/shadow) | — | 0 violations | ✅ |
| lucide-react icons, no inline `<svg>` | — | 0 inline svg | ✅ |
| Type scale discipline | ~9 roles (DESIGN.md) | **35 distinct font-size values** | ❌ no scale |
| Error handling (broad except + logger + intent comment) | — | 7 silent broad-excepts in routes_episodes.py + 2 in media | ❌ convention drift |
| Docs in English (except diary) | — | CLAUDE-IN-CHROME-HANDOFF.md is Korean | ❌ 1 doc |

**Why this dimension rots hardest (structural, not laziness):** the workspace has no CI/stylelint gate
inside this sub-repo, so size/gradient/token rules are enforced only by periodic manual audits like this
one. Between audits, every session adds one more panel / one more gradient / one more oversized route file,
and nothing fails. **The durable fix is a repo-local lint gate, not another cleanup pass** — otherwise this
scorecard regenerates in 2 months.

---

## §6 — DOCS + HYGIENE  (user-requested workstream)

### Docs drift (audit I) — 50 docs: 38 current / 8 update / 2 archive
- 🔴 **Agent cold-start entry is fiction**: `docs/ARCHITECTURE.md` UI layer references `ComposerPanel.tsx`
  / `ExecutionPanel.tsx` (don't exist), `App.tsx "428 lines"` (actual 67), omits the entire `worker/bridge/`
  layer (the largest code mass). CLAUDE.md References lists ARCHITECTURE.md **first** → an agent reading the
  documented order internalizes a nonexistent app before touching the real 14K-line route files.
- 🟡 **Adapter count 3-way mismatch**: CLAUDE.md "17" / ARCHITECTURE.md "18" / actual `ADAPTER_CONFIG` **19**.
- 🟡 CLAUDE.md Directory Map describes the original 7-component app; README run-mode contradicts package.json
  (`dev: vite` HMR vs "builds + serves dist/"); AGENTS.md "Python 3.11" vs venv 3.14.2.
- 🟡 Operator guidance is **5-way fragmented** (~175K across LIVE-CHANNEL-OPERATING-SYSTEM 70K, RENDERING-SPEC
  59K, QUALITY-RECOVERY-RUNBOOK 31K, HUMAN-OPERATOR-PRODUCTION-PLAN 26K, OPERATOR-CHECKLIST 24K) with no
  precedence note; dated filenames falsely signal "stale snapshot."

### Repo hygiene (audit J)
- 🔴 **178 MB BGM mp3 (43 files) still git-tracked** despite `.gitignore` rule (already-committed → needs
  `git rm --cached`). = 178 MB of the 267 MB tracked repo. **Dominant hygiene issue.**
- `storage/` 4.5 GB (correctly gitignored). Root junk `HEdbg0vaEAASMCQ.jpg` 462KB (untracked, delete).
- `logs/` not in `.gitignore` (gap). `.env.example` missing 7 real key names (GROQ etc.). stale `sora2_video.pyc`.
- `vite.config.ts` hardcodes `C:/vibe/projects/video-studio` (junction-safe but non-portable).

---

## §7 — PROPOSED WORKSTREAMS (input to grill-me + PLAN — NOT yet decided)

Ordered by the user's stated goal (**video quality first**), then their two explicit asks (doc hygiene,
rule-compliance). Scope tags S/M/L/XL. These are candidates to interrogate in grill-me, not commitments.

| WS | Theme | Core moves | Scope | Moves the quality needle? |
|---|---|---|---|---|
| **WS1** | **Real perceptual QC** | Add ONE ffprobe/ffmpeg measurement module (loudness, black/freeze detect, duration, resolution) + wire into gate + 1 real end-to-end render test. Replace self-reported dB/continuity with measured. | L | ✅✅ closes the "nobody looks at the video" root |
| **WS2** | **Grok prompt quality** | Stop stripping style vocab; stop forcing search-query seeds into video prompts; raise/soften the 500-char drop; let operator pass rich prompt through (or make manual-prompt a first-class path). | M | ✅✅ directly fixes the user's #1 observation |
| **WS3** | **Render defect fixes** | BGM gain 0.55→1.55; caption wrap→timed multi-cue instead of truncate; zoompan upscale pre-pass; align motion presets to spec. | M | ✅✅ visible quality per render |
| **WS4** | **Security hardening** | 2 CRITICAL (subprocess exec, CSRF file-copy) + Grok SSRF guard + CORS scope + sender validation. Separate reviewer pass mandatory. | M | ➖ (safety, not quality) |
| **WS5** | **Rule-compliance + code-structure** | Split the 8 oversized files (routes_grok, routes_media, compose_ffmpeg, bridge.ts, SceneDetail, RenderReview, StudioContext, golden_reference); delete dead code; **+ add a repo-local lint gate** (size/gradient/token/font-scale) so it stays fixed. | XL | ➖ (maintainability; enables everything else) |
| **WS6** | **Design system cleanup** | Fix 2 undefined vars (broken); 6→1 gradient; 35→~9 font-scale; hardcoded→tokens; ~1,000 dead CSS lines. | M | ➖ (UI polish + rule compliance) |
| **WS7** | **IA de-sprawl** | Collapse the 3+ redundant "what's next"/gate widgets per screen into one; resolve GatesPanel dual-mount. | M | ➖ (operator UX) |
| **WS8** | **Docs + hygiene** | Fix ARCHITECTURE.md agent-entry; reconcile adapter count; doc precedence map; `git rm --cached` 178MB BGM; gitignore gaps; delete junk; archive 2 stale docs. | S-M | ➖ (onboarding + repo weight) |

**Open decisions for grill-me** (the questions the PLAN must answer):
1. What is the user's *actual* production workflow today — app-generated stills, or Grok-source-first import?
   (Determines whether Layer 1 matters or WS2+WS3 are the whole game.)
2. Is video-studio a **revenue-direct** asset (channel/upload goal) or a **hobby tool**? (Per user-profile,
   this changes the metric — shipping vs enjoyment — and how much WS5/XL refactor is justified.)
3. Sequencing: quality-first (WS1-3) vs safety-first (WS4) vs foundation-first (WS5)? Interdependencies exist
   (WS5 refactor churns the same files WS1-3 touch → order matters).
4. Refactor appetite: full XL structural split, or targeted "split only what we're already editing"?
5. Lint-gate adoption: is a repo-local CI/pre-commit gate wanted (the durable fix), or one-time cleanup?

---

*Findings are read-only observations, grep-verified where marked. No code was modified during this audit.
Next: `/grill-me` to resolve §7 open decisions → then the improvement PLAN.*
