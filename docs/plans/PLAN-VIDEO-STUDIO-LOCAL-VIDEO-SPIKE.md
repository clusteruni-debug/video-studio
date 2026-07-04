---
plan_id: VIDEO-STUDIO-LOCAL-VIDEO-SPIKE
project: video-studio
status: PROPOSED
status_reason: Extracted from PLAN-VIDEO-STUDIO-SEMI-AUTO-QUALITY-LOOP as a disposable, opt-in spike — deferred until the semi-auto quality baseline ships; do NOT start before that plan's M1-M3
milestones:
  - { id: S1, label: "Disposable spike — run ONE local video model once, produce ONE MP4, measure VRAM/time/quality, then decide whether an integration path exists", done: false }
decisions_pending:
  - "Which model to try first on the 12GB+ GPU — Wan 2.1 vs LTX-Video vs HunyuanVideo (decide at spike start by VRAM/quality match)"
blockers:
  - "Gated on PLAN-VIDEO-STUDIO-SEMI-AUTO-QUALITY-LOOP shipping M1-M3 first (completion-bottleneck guard — do not start this until the semi-auto win is real)"
depends_on: [VIDEO-STUDIO-SEMI-AUTO-QUALITY-LOOP]
git_strategy: sub-repo
last_verified: 2026-07-04
ko_translation:
  status_reason_ko: "PLAN-VIDEO-STUDIO-SEMI-AUTO-QUALITY-LOOP에서 분리한 disposable opt-in 스파이크 — 반자동 품질 baseline 출시 후로 연기; 그 plan의 M1-M3 전엔 시작 금지"
  milestones_ko:
    - { id: S1, label_ko: "일회용 스파이크 — 로컬 비디오 모델 1개를 1회 실행해 MP4 1개 생성, VRAM/시간/품질 측정 후 통합 경로 존재 여부 결정" }
  decisions_pending_ko:
    - "12GB+ GPU에서 먼저 시도할 모델 — Wan 2.1 vs LTX-Video vs HunyuanVideo (스파이크 시작 시 VRAM/품질 매칭으로 결정)"
  blockers_ko:
    - "PLAN-VIDEO-STUDIO-SEMI-AUTO-QUALITY-LOOP의 M1-M3 출시가 선행 조건 (완성 병목 가드 — 반자동 win이 실제로 나오기 전엔 시작 금지)"
---

# Plan — Local Video Spike (disposable)

> **Goal (testable)**: Determine, with ONE measured artifact, whether a local free video model on the
> user's 12GB+ GPU can produce a clip that clears the semi-auto plan's M4 perceptual floor AND the M3
> editorial gate — WITHOUT building an integration. Output is a go/no-go decision, not a feature.
> **Owner**: User (Decider) + CC. **Created**: 2026-07-04

## Background

The 10-agent audit found the app's video adapters (`wan`/`ltx-video`/`hunyuan-video`/`veo3`/`runway`) are
command-shell stubs; the default render is a still + Ken Burns slideshow (Layer 1). The user has a 12GB+
NVIDIA GPU, so a local free video model is *viable in principle*.

**Why this is a separate, deferred plan (triple adversarial review, 2026-07-04):** all three reviewers
(CC, agy, Codex) flagged that (a) the user already does Grok-source-first, so "no AI video by default" is
NOT the user's current blocker — local video is future automation, not baseline repair; and (b) wiring a
local model is a notorious rabbit hole, not a small "spike", and a 12GB card does not prove installability,
speed, or quality. Given the user's documented completion bottleneck, embedding this in the quality plan
risked stranding it. So it is extracted here, gated behind the semi-auto quality baseline, and framed as
disposable: one run, one artifact, one decision.

## Approach

### S1 — Disposable spike (do NOT integrate)  (time-boxed)
- Pick ONE model (Wan 2.1 / LTX-Video / HunyuanVideo) by VRAM/quality match to the 12GB+ card.
- Run it ONCE via its own CLI/server (NOT wired into `route_image` — that is a still-image flow; do not
  touch the app). Produce ONE ~4-6s 9:16 MP4 from a single realistic prompt.
- Measure: peak VRAM, wall-clock per clip, and run the artifact through the semi-auto plan's M4 media_probe
  floor + a user eyes-on against a Grok clip of the same subject.
- **Decision (the only deliverable)**: record go/no-go. GO = the clip clears the M4 floor and the user judges
  it competitive with Grok → THEN (and only then) open a follow-up integration plan. NO-GO = record the
  measured gap (quality/time/VRAM) and stop; semi-auto stays the baseline.
- **Acceptance**: one MP4 artifact under `storage/qa/local-video-spike/` + a recorded go/no-go with the three
  measurements (VRAM, time, M4 floor result) and the user's eyes-on verdict. No app code changed.
- **Verify**: the artifact exists + the M4 probe report + a one-paragraph decision note in this plan's closeout.

## Authoring Protocol
- [x] Context intake: parent plan + 10-agent audit + triple review.
- [x] Evidence baseline: adapters are stubs (audit E); user GPU 12GB+ (grill-me).
- [x] PLAN vs ADR: execution spike → PLAN (single milestone). Integration decision, if GO, becomes a new plan.
- [x] Scope boundary: NO app integration; NO `route_image` change; artifact + measurement + decision only.
- [x] Consumer/dependency: `depends_on` the semi-auto plan (must ship M1-M3 first).
- [x] Verification design: one artifact + M4 floor + eyes-on = the go/no-go.
- [x] Review path: CC-direct spike; if GO, the integration follow-up gets its own review.

## Plan Quality Checklist
### Evidence And Scope
- [x] Problem + evidence stated (stub adapters, viable GPU).
- [x] Files/scope: none touched — external CLI/server only.
- [x] Non-goal explicit: NO integration in this plan.
- [x] Blocker mirrored in frontmatter (gated on parent M1-M3).
### Decomposition
- [x] Single disposable milestone.
- [x] Dependency explicit (`depends_on` parent).
- [x] Done-when = one artifact + go/no-go note.
- [x] No security/schema surface (external run only).
### Acceptance And Proof
- [x] Measurable: artifact + 3 measurements + verdict.
- [x] Not presented as integration.
- [x] Runtime named: local GPU run, `storage/qa/local-video-spike/`.
- [x] Closeout = decision note in this file.

## Spec Gap Checklist
### Resolved Gaps
- Framed disposable, gated behind the semi-auto baseline (triple-review consensus).
### Missing Questions
- [ ] Which model first (frontmatter decision).
### Undefined Guardrails
- [x] No app integration in this plan; no paid providers.
### Scope Risks
- [x] Rabbit hole → hard-capped to one run + one artifact + a decision.
### Unvalidated Assumptions
- [ ] 12GB is enough for competitive quality — measured, not assumed.
### Missing Acceptance Criteria
- [x] One artifact + go/no-go with 3 measurements.
### Edge Cases
- [x] Install/VRAM failure = a valid NO-GO outcome (record and stop, not a rabbit hole).

## Acceptance Criteria (overall)
- [ ] One MP4 artifact + M4 floor result + VRAM/time measurements + user eyes-on verdict recorded.
- [ ] A go/no-go decision written to this plan's closeout; no app code changed.
- [ ] Not started before the parent plan's M1-M3 ship.

## References
- Parent: `docs/plans/PLAN-VIDEO-STUDIO-SEMI-AUTO-QUALITY-LOOP.md`
- Audit: `docs/_video-studio-audit-topology-2026-07-04.md` (Layer 1, adapter stubs)

## Notes
> Extracted from the semi-auto quality plan 2026-07-04 per triple adversarial review. Disposable spike — one run, one decision.
