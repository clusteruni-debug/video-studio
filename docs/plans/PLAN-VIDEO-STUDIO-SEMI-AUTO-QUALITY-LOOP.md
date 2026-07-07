---
plan_id: VIDEO-STUDIO-SEMI-AUTO-QUALITY-LOOP
project: video-studio
status: IN_PROGRESS
status_reason: "PROPOSED->IN_PROGRESS per WORKSPACE-AUDIT-V2 M2: 32/41 body items already done; PROPOSED no longer reflects reality"
milestones:
  - { id: M0, label: "Foundation — confirm canonical render path + narrow CRITICAL security guards + minimal hygiene prerequisites", done: false }
  - { id: M1, label: "Source & prompt quality FIRST — controlled camera/style lexicon, fix search-query seeds, one-click handoff, preregistered A/B vs manual Grok", done: false }
  - { id: M2, label: "Render hotfixes on the Grok-MP4 path (measured) — BGM gain from LUFS/true-peak, subtitle cue allocator; proven on an imported Grok MP4 render", done: false }
  - { id: M3, label: "Editorial acceptance gate — promote existing human review fields (hook/continuity/caption/thumbnail/audio) to PRIMARY sign-off gate", done: false }
  - { id: M4, label: "Perceptual QC floor — ffprobe/blackdetect/freeze/loudness module + 1 real render test, wired as a FLOOR beneath the editorial gate (not the gate)", done: false }
  - { id: M5, label: "Fallback-stills polish — Ken Burns upscale + motion presets, image branch ONLY (not the Grok-MP4 path); lower priority", done: false }
  - { id: M6, label: "Broad hygiene + rule-compliance + targeted refactor + lint gate + docs/IA (deferred after first quality proof)", done: false }
decisions_pending: []
blockers: []
depends_on: []
git_strategy: sub-repo
last_verified: 2026-07-05
ko_translation:
  status_reason_ko: "WORKSPACE-AUDIT-V2 M2에 따라 PROPOSED->IN_PROGRESS 전환: 본문 41개 항목 중 32개 이미 완료, PROPOSED는 더 이상 실상을 반영하지 않음"
  milestones_ko:
    - { id: M0, label_ko: "기반 — canonical 렌더경로 확정 + narrow CRITICAL 보안 가드 + 최소 위생 전제조건" }
    - { id: M1, label_ko: "소스/프롬프트 품질 먼저 — 통제된 카메라/스타일 사전, 검색쿼리 씨앗 수정, 원클릭 핸드오프, 수동 Grok 대비 사전등록 A/B" }
    - { id: M2, label_ko: "Grok-MP4 경로 렌더 핫픽스(측정 기반) — BGM 게인 LUFS/트루피크로 결정, 자막 cue allocator; 임포트 Grok MP4 렌더로 증명" }
    - { id: M3, label_ko: "창작 합격 게이트 — 이미 있는 human 리뷰 필드(훅/연속성/자막/썸네일/오디오)를 1급 사인오프 게이트로 승격" }
    - { id: M4, label_ko: "지각 QC 바닥 — ffprobe/blackdetect/freeze/loudness 모듈 + 실제 렌더 테스트 1개, 창작 게이트 아래 floor로 배선(게이트 아님)" }
    - { id: M5, label_ko: "fallback 스틸 마감 — Ken Burns 업스케일+모션 프리셋, image 브랜치 전용(Grok-MP4 경로 아님); 낮은 우선순위" }
    - { id: M6, label_ko: "광범위 위생 + 규칙준수 + 타깃 리팩터 + lint 게이트 + 문서/IA (첫 품질증명 뒤로 연기)" }
  decisions_pending_ko: []
  blockers_ko: []
---

# Plan — Semi-Auto Quality Loop

> **Goal (testable)**: A render produced through the dashboard's semi-auto path (app-generated
> high-quality Grok prompt → operator generates in Grok → import → render) wins or ties a
> **preregistered** eyes-on A/B against a manual-Grok render on the SAME locked topics, and passes
> the editorial sign-off gate. Mechanical probes (blackdetect/loudness) are a floor beneath that gate,
> never the acceptance signal.
> **Owner**: User (Decider + creative reviewer) + CC primary. M0 security guards require a separate reviewer (author≠reviewer).
> **Created**: 2026-07-04 · **Revised**: 2026-07-04 (triple adversarial review)

## Background

The user reports dashboard-produced videos are low quality — manually typing prompts into grok.com
beat the app pipeline. A 10-agent read-only audit (`docs/_video-studio-audit-topology-2026-07-04.md`)
found a compounding failure across 4 layers, none ever measured against the actual rendered video
(~77 quality gates + 674 tests, **0 perceptual checks**, 1 line of code opens a real media file).

**This plan was revised after a triple adversarial review (CC + agy + Codex, Codex code-verified).**
The review overturned the first draft's sequencing and retargeted several fixes. Key review findings
(all folded in below):

- **[Codex, code-verified] The first draft aimed render fixes at the wrong code branch.** `save_plan.py`
  maps Grok imports to video assets with `motionPreset: none`; `compose_ffmpeg.py:1973` gates zoompan
  behind `visual_kind == "image"`. **Imported Grok MP4 scenes never hit the Ken Burns branch** — so the
  draft's Ken Burns jitter fix would not touch the user's actual videos. Ken Burns is now demoted to a
  fallback-stills milestone (M5); render hotfixes that DO apply to Grok MP4 (BGM mix, subtitle burn) are
  M2 and must be proven on an imported-Grok-MP4 render.
- **[3-reviewer consensus] Sequencing was backwards.** For Grok-source-first, the dominant defect is
  source/prompt quality, not render polish. Source & prompt quality is now the FIRST quality milestone (M1).
- **[3-reviewer consensus] M4 mechanical QC would recreate "gate theater 2.0".** ffprobe/blackdetect/loudness
  detect broken files, not weak hooks / bad narration / wrong music mood. The **editorial acceptance gate is
  M3 and primary**; mechanical probes (M4) are a floor only.
- **[Codex, evidence] The editorial review fields already exist in code** (hook / artifact-free / continuity /
  caption-safety / thumbnail / audio / platform-comparison). The plan does not invent a creative QC — it
  **promotes existing human fields to primary acceptance**.
- **[3-reviewer] BGM 0.55→1.55 is an unsafe magic number** (limiter may hide clipping but can mask narration /
  crush native Grok audio). Gain must be chosen from measured LUFS / true-peak / speech-vs-BGM delta.
- **[3-reviewer] Naive subtitle multi-cue splitting causes flashing/voice-drift** (no word-level timing).
  Replace with a cue allocator (CPS limit + min cue duration + scene-boundary constraint).
- **[Codex] "Stop stripping style vocab" is naive** — the strip exists to force observable action; simply
  re-allowing "cinematic/mood/vibe" regresses to vague slop. Replace with a controlled camera/style lexicon
  tied to concrete subject/action/shot.
- **[3-reviewer] M5 local-video is a rabbit hole, not the user's current blocker** (user already does
  Grok-source-first, which bypasses "no AI video by default"). **Extracted to a separate opt-in plan.**
- **[Codex] The A/B acceptance is gameable** — preregister topics / take-budget / evaluator / rubric /
  preserve rejected takes.
- **[Codex + user] Security narrow guards go early** (browser handoff/import surface is actively used);
  broad hygiene/refactor is deferred after the first quality proof so it does not burn budget first.

User decisions (grill-me 2026-07-04): semi-auto Grok-source-first made smooth + high-quality is the
committed deliverable; hobby + revenue (quality investment justified, scope tight for the completion
bottleneck); local-video is a measured aspiration (now a separate plan); targeted refactor + lint gate;
security early. The milestone *ordering* was CC's draft, not a user commitment — the review-driven
reorder corrects the draft, it does not overturn a user decision.

## Approach

Vertical-slice milestones ordered so the **first quality proof is a better Grok-source render**, not
render polish on a branch the user never hits. Local-video is out (separate plan). Broad cleanup is last.

### M0 — Foundation: canonical render path + narrow security guards + minimal hygiene  (S)
- **Confirm the canonical render path**: the app has ≥2 final-video paths — `draft_executor.py`→CapCut/
  VectCutAPI and `draft_render.py`→`compose.py`/FFmpeg — and the UI triggers both (`apiCreateDraft`,
  `apiRenderSmoke`). Determine which path the user's actual uploaded videos come from; document it as
  canonical. **M2 render fixes target that path**; if CapCut is canonical, BGM/subtitle fixes must land in
  the CapCut handoff, not `compose_ffmpeg.py`. This gates whether any render fix reaches the user.
- **Narrow CRITICAL security guards** (browser handoff/import is actively exercised): `routes_grok.py:6222`
  `_launch_cdp_browser` executable allowlist; `routes_grok.py:12611` `bookmarklet-import` Downloads
  restriction + POST-not-GET; `content.js:670,614` route Grok fetch through the origin-guarded background.
  Separate reviewer pass (author≠reviewer, Rule #14) before merge. (Broad CORS/sender cleanup → M6.)
- **Minimal hygiene only** (low-risk, does not burn quality budget): `git rm --cached` the 178 MB tracked
  BGM; add `logs/` to `.gitignore`; delete root junk jpg. (Broad docs/lint/refactor → M6.)
- **Acceptance**: a one-line doc names the canonical render path with evidence (which endpoint the user's
  last real upload came from); a request with a non-allowlisted `browserExecutable` returns 4xx and spawns
  nothing (test asserts no `Popen`); `bookmarklet-import` outside Downloads returns 4xx; git-tracked size
  drops ≥170 MB. Security guards pass an independent reviewer.
- **Verify**: targeted pytest for the two route guards + companion test → then `/security-review` or `/codex:review`; `git ls-files` size delta.

### M1 — Source & prompt quality FIRST  (M — the dominant defect for Grok-source-first)
- Replace the style-vocab *strip* (`GROK_ABSTRACT_OR_META_PROMPT_TERMS`) with a **controlled camera/style
  lexicon** tied to concrete subject + action + shot constraints — not a blanket re-allow of "cinematic/mood/
  vibe" (which regresses to slop), and not the current blanket ban (which strips useful direction).
- Fix the 13/17 templates whose "visual seed" is a Google-image-search query (`image_prompt`) being fed
  verbatim into a video prompt — populate a real `visual_action` for video prompts.
- Fix `_prompt_join()` silent-drop past 500 chars → shorten-or-warn so camera/continuity never vanishes silently.
- One-click handoff: app produces the prompt + one-click copy; import auto-detects the returned MP4.
- **Preregistered A/B** (anti-cherry-pick): before running, LOCK topics (3), take-budget per topic, the exact
  manual-vs-app prompt inputs, the scoring rubric/dimensions, and preserve ALL accepted AND rejected takes.
- **Acceptance**: on the 3 preregistered topics, the app-generated Grok prompt (i) preserves camera/style
  direction via the controlled lexicon, (ii) contains no raw search-query seed, (iii) never silently drops a
  clause; and the app-prompt render wins or ties the manual-Grok render on the preregistered rubric, with all
  takes archived under `storage/qa/ab-<date>/`.
- **Verify**: extended `test_template_prompts.py` (no seed leakage, no silent truncation) + the preregistered A/B capture.

### M2 — Render hotfixes on the Grok-MP4 path (measured)  (M)
- **Only fixes that apply to imported Grok MP4** (per M0's canonical path). BGM mix + subtitle burn apply to
  video; Ken Burns does NOT (→ M5).
- **BGM**: choose the mix gain from measured before/after renders — LUFS, true-peak, speech-vs-BGM delta,
  listening check — NOT a hardcoded 1.55. Add/verify a limiter so no clip; confirm BGM is audible under
  narration without masking it.
- **Subtitle**: replace silent truncation with a **cue allocator** — CPS (chars-per-second) limit, minimum
  cue duration, scene-boundary constraint; keep same-cue `\N` 2-line wrap where no word-level timing exists
  (do NOT invent extra cues that desync from audio).
- **Acceptance**, proven ON AN IMPORTED GROK MP4 RENDER (not an image slideshow): measured BGM present under
  narration with true-peak below clip and no narration masking; a 40-char Korean subtitle displays fully,
  CPS-compliant, no mid-sentence cut, no flashing, synced to audio.
- **Verify**: render a project whose scenes are imported Grok MP4s → ffprobe loudness/true-peak + subtitle-frame capture under `storage/qa/`.

### M3 — Editorial acceptance gate (the REAL quality gate)  (M)
- Promote the **already-existing** human review fields (hook, artifact-free, continuity, caption-safety,
  thumbnail/first-frame, audio, platform-comparison) to a **primary sign-off gate** in the dashboard UI: a
  render is not "passed" until the operator signs off on visual appeal + narrative pacing + these fields.
- Add a short creative brief per project (hook formula, story arc, music-mood intent) so the sign-off has a
  reference. TTS voice naturalness exposed as a configurable lever here.
- **Acceptance**: the UI blocks "passed" without an explicit human editorial sign-off; the existing review
  fields are the primary gate, and the render-quality report shows them above the mechanical checks.
- **Verify**: attempt to mark a render passed without sign-off → blocked; sign-off recorded in the packet.

### M4 — Perceptual QC floor (measurement, NOT the gate)  (L)
- New `worker/render/media_probe.py`: real ffprobe/ffmpeg — loudness/true-peak, `blackdetect`,
  `freezedetect`, resolution, duration. Wire measured values in place of self-reported floats, **as a FLOOR
  beneath the M3 editorial gate** (a render must clear the floor to be eligible for editorial sign-off; the
  floor alone never marks "passed").
- One real end-to-end render test (`@pytest.mark.integration`), unmocked ffprobe; CI skips LOUDLY without ffmpeg.
- **Acceptance**: a black/muted render fails the floor (currently passes); the probe opens a real MP4 and
  returns non-fabricated values; the floor is explicitly documented as subordinate to the M3 editorial gate.
- **Verify**: `pytest -m integration`; feed a black-frame fixture → floor FAIL; confirm floor cannot mark "passed" alone.

### M5 — Fallback-stills polish (Ken Burns, image branch ONLY)  (M — lower priority)
- Ken Burns upscale pre-pass + spec-aligned motion presets + "no same motion 2× consecutive", scoped to the
  `visual_kind == "image"` fallback branch only (NOT the Grok-MP4 path — verified irrelevant there).
- **Acceptance**: a stills-fallback render shows no zoompan jitter; motion rotation implemented. Explicitly
  scoped so it does not claim to affect Grok-MP4 renders.
- **Verify**: render a stills-only fallback project → eyes-on motion + `storage/qa/` capture.

### M6 — Broad hygiene + rule-compliance + targeted refactor + lint gate + docs/IA  (M-L — deferred, user-requested scope kept)
- Design system: fix undefined CSS vars (`--danger`/`--bg-panel`, broken fail-state); 6 gradients → 1;
  35 font-sizes → ~9; hardcoded → tokens; delete ~1,000 dead CSS lines + dead `RenderReviewPanel` export +
  14 dead `bridge.ts` exports + dead scripts/adapters.
- `scripts/check-project-rules.py` lint gate (size/gradient/token/font-scale); advisory → hard-fail on cleaned files.
- Targeted splits of files edited in M1-M4 only (`grok_prompt_engine.py` out of routes_grok; gate code out of
  compose_ffmpeg; bridge.ts by domain). NOT a big-bang 8-file split.
- Broad security cleanup (CORS scope, 6 unguarded sender handlers, news.py quote_plus).
- Docs: fix `ARCHITECTURE.md` agent entry (real components + `worker/bridge/`); reconcile adapter count to 19;
  operator-doc precedence map; archive 2 stale docs; `.env.example` key names. IA: collapse redundant
  next-action/gate widgets; resolve `GatesPanel` dual-mount.
- **Acceptance**: `check-project-rules.py` 0 violations on touched files + wired as hard pre-commit; undefined-CSS-var == 0; `npm run build` + `tsc --noEmit` green; `ARCHITECTURE.md` references only real components.
- **Verify**: lint exit 0 on touched files; `npm run build` exit 0; grep undefined vars == 0.

> 2026-07-07 (gap-sweep): WORKSPACE-AUDIT-V2 `## P video-studio` (memory/reviews/workspace-audit-v2-findings-20260704.md, verdict "fold into SEMI-AUTO-QUALITY-LOOP") findings were never folded in — verified still open 2026-07-07. Absorb into M6 docs/hygiene scope:
> - [ ] [MED] Add an "Artifact-Quality Gates" pointer section to project CLAUDE.md/AGENTS.md linking `config/project-quality.json` + `worker/render/{golden_reference_gate,production_mode_gate,longform_minimum_release_gate}.py` (currently 0 mentions in either entry doc — verified).
> - [ ] [LOW] AGENTS.md:6 "Python 3.11" → 3.14 (.venv is 3.14.2).
> - [ ] [LOW] docs/IMPLEMENTATION-ROADMAP.md:132 drop "and Ollama" (resolver removed 2026-04) — verified still present.
> - [ ] [LOW] CLAUDE.md Rendering Rules blockquote (3 Korean lines) → English per doc-language rule.
> - [ ] M6 targeted-split candidate list should also weigh audit-verified god-files not named here: `tests/test_manual_clip_pipeline.py` (14.7k) and `worker/bridge/routes_media.py` (11.4k) — evaluate, still touched-files-only, not big-bang.
> (Board stale/superseded-row triage from the same audit is owned by WORKSPACE-AUDIT-V2 master M3, not this plan.)

> **Extracted**: local-video-model full-auto spike → separate opt-in plan `PLAN-VIDEO-STUDIO-LOCAL-VIDEO-SPIKE.md`
> (one model, one CLI/server run, one MP4 artifact, measured VRAM/time/quality, then decide). Kept out of this
> plan so the completion bottleneck does not strand the semi-auto quality win.

## Authoring Protocol

- [x] Context intake: project docs + RENDERING-SPEC + 10-agent audit + triple adversarial review (CC/agy/Codex).
- [x] Evidence baseline: audit grep-verified; Codex code-verified the Ken Burns branch bypass (`compose_ffmpeg.py:1973`, `save_plan.py motionPreset:none`); BGM gain + undefined CSS vars spot-verified.
- [x] PLAN vs ADR: multi-milestone execution → PLAN. Source-strategy + render-path-canonicalization are design decisions; extract to ADR if they solidify post-M0.
- [x] Split decision: single PLAN, 7 milestones + 1 extracted sibling plan (local-video). One owner (CC-direct) except M0 security reviewer pass.
- [x] Scope boundary: `projects/video-studio/**`. Non-goals below. No paid deps (zero-paid policy); no DB/schema; local-video is out.
- [x] Consumer/dependency check: no cross-project consumers. Internal order: M0 canonical-path gates M2; M3 editorial gate sits above M4 floor; M6 deferred after first quality proof (M1-M2).
- [x] Verification design: each milestone has a runtime signal + verify command; M2 proof REQUIRED on a Grok-MP4 render (not stills); M4 floor explicitly subordinate to M3 gate.
- [x] Review path: M0 security requires author≠reviewer. This plan itself was adversarially reviewed by agy + Codex (Codex outcome recorded in `memory/state/codex-review-ledger.jsonl`).

## Plan Quality Checklist

### Evidence And Scope
- [x] Problem stated with code-verified evidence (Ken Burns branch bypass, BGM gain, undefined vars).
- [x] Exact files/modules named per milestone.
- [x] Non-goals explicit (local-video extracted; broad cleanup deferred).
- [x] Open decisions resolved; frontmatter `decisions_pending` empty.

### Decomposition
- [x] Milestones independently reviewable; M1 (source/prompt) is the first quality proof.
- [x] Dependency order explicit (M0 canonical-path → M2 target; M3 gate > M4 floor).
- [x] Each milestone has done-when + verify command; M2 mandates proof on a Grok-MP4 render.
- [x] Security (M0) has an owner + reviewer gate.

### Acceptance And Proof
- [x] Acceptance measurable AND non-gameable (preregistered A/B; editorial sign-off primary; mechanical floor subordinate).
- [x] Static build confidence not presented as runtime validation (M2/M4 require real render).
- [x] Runtime validation names env (Windows bridge :5161 / UI :5160), fixture (imported-Grok-MP4 project), storage (`storage/qa/`).
- [x] Closeout evidence = `storage/qa/` + PLAN closeout note.

## Spec Gap Checklist

### Resolved Gaps
- Sequencing: source/prompt quality first, not render polish (3-reviewer consensus).
- Render fixes target the canonical Grok-MP4 path; Ken Burns is image-branch only (Codex code-verified).
- Editorial human sign-off is primary acceptance; mechanical probes are a floor (3-reviewer).
- Style vocab: controlled lexicon, not blanket re-allow or blanket ban (Codex).
- BGM/subtitle: measured (LUFS / CPS allocator), not magic numbers (3-reviewer).
- Local-video extracted; broad hygiene deferred after first quality proof (Codex + user scope kept).
- A/B preregistered (Codex anti-cherry-pick).

### Missing Questions
- [ ] M0: which endpoint does the user's actual last real upload come from — compose or CapCut? (Resolve at M0 start; gates M2 targeting.)
- [ ] M1: exact scoring rubric dimensions for the preregistered A/B (define with the user before running).

### Undefined Guardrails
- [x] No paid providers without opt-in; no DB/schema; local-video out of this plan.
- [x] M0 security cannot ship without an independent reviewer pass.
- [x] Mechanical QC (M4) can never mark a render "passed" alone — editorial gate (M3) required.
- [x] M2 acceptance is invalid unless proven on an imported-Grok-MP4 render.

### Scope Risks
- [x] Refactor sprawl → M6, touched-files-only, explicit "not a big-bang split".
- [x] Local-video rabbit hole → extracted to a disposable sibling plan.
- [x] Completion bottleneck → M1 (source/prompt) ships the first real quality win; M4-M6 deferrable.
- [x] "Cleaner bad video" risk → render polish (M2/M5) is downstream of source/prompt (M1) + editorial gate (M3).

### Unvalidated Assumptions
- [ ] The controlled camera/style lexicon improves Grok output vs both the current strip and a naive re-allow — validated by the M1 preregistered A/B.
- [ ] The canonical render path is compose (vs CapCut) — verified in M0, not assumed.

### Missing Acceptance Criteria
- [x] Each milestone measurable; A/B preregistered; editorial gate primary.

### Edge Cases
- [x] Imported Grok MP4 skips the zoompan branch (Codex-verified) — M2 proof must use such a render.
- [x] Korean subtitle >32 chars → cue allocator (CPS/min-duration), not truncation or naive multi-cue.
- [x] ffmpeg absent in CI → M4 loud skip.
- [x] Silent planner fallback (Gemini→Groq→template) → surface `plannerSource` in UI (fold into M1/M3).

## Acceptance Criteria (overall)

- [ ] On 3 preregistered topics, an app-prompt Grok-source render wins/ties the manual-Grok render on the locked rubric, with all takes archived; passes the M3 editorial sign-off.
- [ ] M2 render fixes are proven on an imported-Grok-MP4 render (not stills); BGM audible+unclipped, captions full+synced.
- [ ] The M4 mechanical floor cannot mark a render "passed" alone; the editorial gate is required.
- [ ] M0 documents the canonical render path with evidence; narrow CRITICAL security guards pass an independent reviewer.
- [ ] SLA: M0-M2 (foundation + source/prompt + render-on-right-path) land before M4-M6.
- [ ] Adoption: user confirms the next real production render is visibly better than the pre-plan baseline.

## References

- Audit + topology: `docs/_video-studio-audit-topology-2026-07-04.md` (10-agent full sweep)
- Adversarial review: agy (6 findings) + Codex (12 findings, code-verified) 2026-07-04; Codex outcome in `memory/state/codex-review-ledger.jsonl`
- Binding spec: `docs/RENDERING-SPEC.md`
- Sibling plan (extracted): `docs/plans/PLAN-VIDEO-STUDIO-LOCAL-VIDEO-SPIKE.md` (local-video full-auto spike)
- Related: `docs/plans/PLAN-VIDEO-STUDIO-LOCAL-GATE-HARDENING.md` (IN_PROGRESS — this plan supersedes its "gates as quality proof" premise via M3 editorial gate + M4 real measurement)
- Memory: `feedback/feedback_user_judgment_patterns.md` (ForFitter: prompt quality = center, mirrors M1), `reference/reference_user_profile.md` §7 (completion bottleneck → M1-first)

## Notes

> Generated by plan-new 2026-07-04; filled from grill-me; revised same day after triple adversarial review.
> Lint: `python scripts/parse-plan-frontmatter.py --lint <this-file>`
> Ready-to-implement gate: go-signal. M0 additionally gated on reviewer availability for the security guards.
