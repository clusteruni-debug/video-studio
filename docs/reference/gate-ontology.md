---
title: Video Studio Gate Ontology
last_verified: 2026-06-21
reliability: primary
sources:
  - projects/video-studio/config/gate-ontology.json
  - projects/video-studio/worker/quality_gate_system.py
  - projects/video-studio/worker/bridge/routes_grok.py
  - projects/video-studio/worker/bridge/routes_sources.py
  - projects/video-studio/worker/render/production_mode_gate.py
  - projects/video-studio/worker/render/longform_workflow_gate.py
  - projects/video-studio/worker/render/longform_minimum_release_gate.py
  - projects/video-studio/worker/render/longform_dryrun_readiness.py
  - projects/video-studio/worker/render/topic_discovery_gate.py
  - projects/video-studio/worker/render/production_packet_lock.py
  - projects/video-studio/worker/render/golden_reference_gate.py
  - projects/video-studio/docs/RENDERING-SPEC.md
  - projects/video-studio/docs/reference/editorial-direction-gate.md
  - projects/video-studio/docs/reference/external-edit-elements.md
  - projects/video-studio/docs/reference/capcut-automation.md
  - projects/video-studio/docs/reference/tts-providers.md
  - projects/video-studio/docs/reference/longform-production-mode.md
  - projects/video-studio/docs/reference/longform-storyboard-web-references.md
  - projects/video-studio/docs/reference/longform-power-user-production-references.md
  - projects/video-studio/docs/reference/longform-workflow-stage-gate.md
  - projects/video-studio/docs/reference/longform-minimum-release-gate.md
  - projects/video-studio/docs/reference/topic-discovery-community-signal.md
refresh_trigger: when adding, renaming, removing, weakening, or reclassifying a Video Studio gate, evidence schema, gate document, or gate test
---

# Video Studio Gate Ontology

This document is the human crosswalk for the Video Studio gate system. The
machine-readable source is `config/gate-ontology.json`; this document explains
how to use it. Do not duplicate full gate rules here. The detailed standards
remain in their original code and reference documents.

## Recommendation

Keep the ontology small and enforce it with tests. A prose-only master document
would become management overhead because it would drift from the code. A small
registry is useful because Video Studio now has multiple independent gate
surfaces:

- unified production phases in `worker/quality_gate_system.py`
- render-quality checks in `RENDER_QUALITY_CHECK_KEYS`
- final-readiness gates in `FINAL_READINESS_GATE_KEYS` plus the appended
  `broad-operating-goal`
- source acquisition gates in Grok/browser handoff render payloads
- source rights and operator-approved fetch gates for internet media
- active production packet locks before FFmpeg render starts
- format profile gates for shortform versus longform work
- Grok/Gemini provider role matrix gates
- topic-discovery gates for current/community/search-backed topic selection
  before storyboard or source generation
- longform production gates for 10-minute chapter/evidence workflows
- longform storyboard and web-reference gates before source generation
- longform power-user production workflow gates before source generation,
  rough-cut approval, derivative clips, or upload claims
- longform workflow stage gates that lock the work order, evidence, dependency,
  improvement loop, and seeded failure verification structure
- longform minimum release gates that keep a 10-minute final/publish claim from
  relying on self-scored quality or unresolved full-watch defects
- longform dry-run readiness gates that compose workflow, production-mode,
  render preflight, minimum release, and final-library evidence before E2E work
- golden-reference preflight checks in `worker/render/golden_reference_gate.py`
- post-edit subcontracts for editorial direction, CapCut handoff, external edit
  elements, layout/HUD, Korean copy/TTS, scoring, rhythm, audio, color, and
  payoff
- reference documents under `docs/reference/`

The ontology exists only to answer:

1. Which gate key exists?
2. Which layer owns it?
3. Which code path enforces it?
4. Which evidence surface proves it?
5. Which document explains it?
6. Which test catches drift?

If an entry cannot answer those questions, the gate is not considered managed.

## Source Of Truth

`config/gate-ontology.json` is the registry source. It must be updated in the
same change as any gate key change.

`tests/test_gate_ontology.py` enforces the registry against code and docs. It
checks that:

- every `GATE_PHASES[].phaseKey` is registered
- every `RENDER_QUALITY_CHECK_KEYS` value is covered by a render-quality group
- every `FINAL_READINESS_GATE_KEYS` value and `broad-operating-goal` are
  registered
- every source-acquisition gate section key is registered and tied to
  `routes_grok.py`
- every source-rights/fetch gate section key is registered and tied to
  `routes_sources.py`
- every active production packet lock report key is registered from
  `production_packet_lock.py`
- every production-mode gate constant in `production_mode_gate.py` is
  registered
- every topic-discovery gate constant in `topic_discovery_gate.py` is
  registered
- every longform storyboard gate constant in `production_mode_gate.py` is
  registered
- every longform power-user workflow gate constant in
  `production_mode_gate.py` is registered
- every longform workflow stage gate constant in `longform_workflow_gate.py`
  is registered
- every longform minimum release gate constant in
  `longform_minimum_release_gate.py` is registered
- every longform dry-run readiness gate constant in
  `longform_dryrun_readiness.py` is registered
- every operational golden-reference report check such as `required`, `preset`,
  and `sceneList` is registered
- every top-level `report["checks"][...]` golden-reference preflight key is
  registered
- every scene-level golden-reference check is registered
- every required `postEditGoldenReference.*` subcontract is registered
- every `video-studio.*.v1` evidence schema constant in the golden gate is
  registered
- every linked doc, code symbol, and test symbol exists

## Gate Layers

| Layer | Purpose | Primary code |
|---|---|---|
| `production-loop` | Preproduction, episode output, quality iteration, and loop state. | `worker/quality_gate_system.py`, episode routes |
| `format-profile` | Separates shortform scene/take work from longform chapter/evidence work. | `worker/render/production_mode_gate.py` |
| `provider-role-matrix` | Separates Grok motion, Gemini still/reference, and Gemini fallback video roles. | `worker/render/production_mode_gate.py` |
| `topic-discovery` | Current Korean/community/search-backed topic selection, candidate matrix, safety, originality, and longform topic fit. | `worker/render/topic_discovery_gate.py` |
| `longform-production` | 10-minute outline, evidence, voice, edit rhythm, audio bed, and full-watch gates. | `worker/render/production_mode_gate.py` |
| `longform-storyboard` | Storyboard-first, chapter marker, retention, visual-bible, and web-reference gates before source generation. | `worker/render/production_mode_gate.py` |
| `longform-power-user` | Packaging, feasibility, rough-cut retention map, review loop, derivative clip plan, and creator-case ledger. | `worker/render/production_mode_gate.py` |
| `longform-workflow` | Ordered longform production stages, stage evidence, dependency checks, improvement actions, and seeded failure verification. | `worker/render/longform_workflow_gate.py` |
| `longform-minimum-release` | Final/publish readiness for 10-minute candidates: rights, source continuity, Korean copy/TTS/captions, edit, audio, full-watch defects, and computed score. | `worker/render/longform_minimum_release_gate.py` |
| `longform-dryrun-readiness` | Single pre-E2E preflight that re-evaluates workflow, production-mode, render preflight, minimum release, and final-library evidence. | `worker/render/longform_dryrun_readiness.py` |
| `source-acquisition` | Grok/browser handoff source readiness and render payload readiness. | `worker/bridge/routes_grok.py` |
| `source-rights` | Editorial source rights, explicit fetch approval, and motion-source promotion. | `worker/bridge/routes_sources.py` |
| `source-quality` | Source acceptance, source continuity, artifact proof, source/take quality. | `worker/render/golden_reference_gate.py`, render-quality report |
| `copy-caption-layout` | Korean copy, caption contract, layout contract, caption/TTS direction. | `worker/render/golden_reference_gate.py`, `worker/render/subtitles.py` |
| `render-quality` | MP4 quality report, BGM/TTS/caption/render checks, publish gate checks. | `worker/render/compose_ffmpeg.py`, `worker/quality_gate_system.py` |
| `golden-preflight` | Reference/golden manifest checks before FFmpeg render. | `worker/render/golden_reference_gate.py` |
| `post-edit` | Editorial direction, scoring, rhythm, audio, color, payoff, external elements. | `worker/render/golden_reference_gate.py` |
| `capcut-handoff` | Editable CapCut draft, draft audit, keyframe/track parity. | `worker/render/capcut_handoff.py`, `worker/render/golden_reference_gate.py` |
| `production-packet-lock` | Active approval packet binding and approval before FFmpeg render. | `worker/render/production_packet_lock.py` |
| `final-readiness` | Final library readiness, phone review, source proof, analytics, broad goal. | `worker/quality_gate_system.py`, media routes |
| `post-publish` | Platform analytics loop and next improvement action. | final-library audit and analytics evidence |

## Coverage Inventory

### Production Phase Gates

The registry must match `GATE_PHASES` exactly:

- `preproduction`
- `episode-output`
- `quality-iteration`
- `asset-source`
- `render-quality`
- `final-readiness`
- `post-publish-loop`

### Render-Quality Groups

Individual render-quality keys are grouped to avoid one document per small
check. The grouped registry still covers every key exactly once.

| Group | Covered concern |
|---|---|
| `source-intake-and-visual-fit` | source motion, source fit, internet/Grok/stock intake, visual frame review, source loop rhythm, asset diversity |
| `story-copy-caption-voice-audio` | Korean copy, caption system, TTS pacing, ending, hook, cut density, BGM, reference edit grammar |
| `iteration-publish-and-provider-readiness` | zero-paid policy, quality ratchet, publish/channel/upload/top-tier readiness |

### Final Readiness Gates

The base registry in `worker/quality_gate_system.py` has six gates:

- `artifact-gate`
- `fresh-source-import-review`
- `fresh-source-proof`
- `phone-sized-human-review`
- `same-day-upload-decision`
- `platform-analytics-loop`

`build_final_readiness_gate_system()` also appends:

- `broad-operating-goal`

This appended gate is intentional. It separates artifact readiness from the
larger operating-system claim that the production loop is actually working.

### Source Acquisition Gates

The Grok/browser handoff route exposes render-payload blockers that must be
managed separately from final readiness:

- `assetQualityGate`
- `grokMainSourceGate`
- `grokRenderPayloadReadiness`

These gates catch the failure mode where files exist, but the selected sources
are not accepted, not main-source ready, or not ready for the render payload.

### Source Rights Gates

Internet/editorial sources must pass rights and operator-intent gates before
promotion:

- `editorialRightsGate`
- `operatorApprovedSourceFetch`
- `motionSourceReady`

These are generic media-source controls. They apply to any topic that uses
web/editorial media, not only one episode or object type.

### Active Production Packet Locks

Render startup must honor these pre-FFmpeg lock checks:

- `longformProductionModeGate`
- `longformMinimumReleaseGate`
- `activePointer`
- `activeStatus`
- `scopeMatch`
- `activePacketPath`
- `activePacket`
- `approvalPacketBinding`
- `packetApproval`

`longformProductionModeGate` applies even when no ACTIVE packet pointer exists:
a manifest with `formatProfile=longform_10m` or longform-range duration must
provide a production-mode packet path/object that passes
`video-studio.production-mode-gate.v1` before FFmpeg starts. The remaining
checks prevent a render from bypassing the currently approved packet, using an
unbound manifest, or rendering before the active packet is approved.

`longformMinimumReleaseGate` is narrower. It applies only when the longform
manifest also claims final or publish readiness. Rough-cut longform renders can
still iterate after the production-mode packet passes, but a final/publish
claim must provide a minimum release packet path/object that passes
`video-studio.longform-minimum-release-gate.v1`.

### Topic Discovery Gates

Topic discovery is a pre-storyboard source gate. It prevents a project from
entering storyboard, prompt-bible, Grok/Gemini generation, or longform dry-run
work because a topic merely felt current.

- `topicSourceLedgerGate`
- `researchQueryPlanGate`
- `sourceAuthenticityGate`
- `communitySignalDiversityGate`
- `trendCrossCheckGate`
- `curiosityAngleGate`
- `longformTopicFitGate`
- `audienceRetentionFitGate`
- `safetyOriginalityGate`
- `topicSelectionMatrixGate`

These gates require a durable source ledger, Korean/community signal diversity,
planned search/trend/video/community queries, real non-placeholder URLs, search
or trend cross-checking, a real question/gap/promise, enough depth for the
target format, retention fit before storyboard, safety/originality review, and
a computed candidate matrix. The detailed standard is maintained in
`docs/reference/topic-discovery-community-signal.md`.

### Longform Dry-Run Readiness Gates

The dry-run readiness preflight is the last code gate before a longform packet
enters operator-visible E2E work. It does not replace the underlying gates. It
re-evaluates their packet objects together so a dry run cannot start because one
summary flag happened to say ready.

- `dryrunTopicDiscoveryGate`
- `dryrunWorkflowGate`
- `dryrunProductionModeGate`
- `dryrunRenderPreflightGate`
- `dryrunMinimumReleaseGate`
- `dryrunFinalLibraryGate`

`dryrunMinimumReleaseGate` and `dryrunFinalLibraryGate` are skipped for rough-cut
targets. They are required when the target stage or render manifest claims final,
upload, channel-ready, top-tier, release, or publish readiness. The final-library
gate specifically rejects upload/channel/top-tier flags unless the audit also
shows `longformMinimumReleaseReady=true` and `longformMinimumReleaseStatus=pass`.

### Format Profile Gates

Production packets and source prompt bibles must declare a format profile:

- `formatProfileGate`

Current managed profiles:

- `shortform_vertical`
- `longform_10m`

The profile decides whether the work is scene/take based or chapter/evidence
based. A 10-minute target must not reuse Shorts caption, pacing, or source
acceptance assumptions.

### Provider Role Matrix Gates

Grok/Gemini roles are explicit before prompt generation:

- `providerRoleMatrixGate`
- `grokPrimaryMotionGate`
- `geminiReferenceGate`
- `geminiFallbackMotionGate`

Default role split: Grok is the preferred motion-source provider, Gemini image
is a reference-still/visual-bible provider, and Gemini video is a fallback
motion provider only with an explicit reason.

### Longform Production Gates

The `longform_10m` profile requires:

- `longformOutlineGate`
- `chapterContinuityGate`
- `evidenceDensityGate`
- `sourceRightsCitationGate`
- `longformVoiceConsistencyGate`
- `longformEditRhythmGate`
- `chapterAudioBedGate`
- `fullWatchReviewGate`

These gates are deliberately separate from Shorts gates. Longform quality
depends on chapter continuity, evidence density, voice consistency, audio beds,
and a full-watch review, not only on source clip quality.

### Longform Storyboard Gates

The `longform_10m` profile also requires storyboard-first gates before source
prompt generation:

- `longformStoryboardGate`
- `chapterMarkerGate`
- `retentionPlanGate`
- `storyboardBeatCoverageGate`
- `evidenceVisualBindingGate`
- `visualContinuityBibleGate`
- `webReferenceLedgerGate`

These gates block the failure mode where a longform render starts with only a
Shorts-style scene list. They require a central thesis, viewer promise, timed
beats, YouTube-compatible chapter markers, first-30-second retention plan,
chapter evidence bound to visual beats, a visual continuity bible, and a durable
web-reference ledger that maps external references to gate keys.

### Longform Power-User Gates

The `longform_10m` profile also requires power-user production workflow gates.
These gates are based on creator cases, industry analysis, and research papers
recorded in `docs/reference/longform-power-user-production-references.md`.

- `packagingPremiseGate`
- `productionFeasibilityGate`
- `roughCutRetentionMapGate`
- `creatorFeedbackLoopGate`
- `derivativeClipPlanGate`
- `powerUserCaseLedgerGate`

These gates block the failure mode where a longform piece has enough chapters
and sources but still lacks a real creator workflow. They require packaging
before source generation, explicit feasibility and kill criteria, minute-level
viewer question/payoff planning, script/rough-cut/final review decisions,
context-preserving derivative clips, and a reusable external-reference ledger.

### Longform Workflow Stage Gates

The longform workflow stage gate locks the order of work before source
generation, render, final readiness, or derivative clip claims:

- `longformWorkflowOrderGate`
- `longformWorkflowEvidenceGate`
- `longformWorkflowDependencyGate`
- `longformWorkflowImprovementLoopGate`
- `longformWorkflowSeededFailureGate`

These gates block the failure mode where a longform project has many quality
checks but still advances through them in an arbitrary order. They require a
registered stage order, exit criteria for every stage, evidence for passed
stages, sequential dependencies, actionable mutations for failed stages, and a
seeded failure suite proving that the gate catches its own expected failure
modes.

### Longform Minimum Release Gates

The minimum release gate applies after longform rough-cut review and before a
10-minute final/publish-ready claim:

- `longformReleaseFormatGate`
- `longformReleaseRightsGate`
- `longformReleaseDisclosureGate`
- `longformReleaseSourceContinuityGate`
- `longformReleaseScriptTtsCaptionGate`
- `longformReleaseEditorialGate`
- `longformReleaseAudioGate`
- `longformReleaseFullWatchGate`
- `longformReleaseScoreGate`

These gates are deliberately separate from shortform gates. They require the
candidate to prove a longform-specific minimum release packet: 480-900 seconds,
6+ chapters, 18+ segments, release-approved rights, chapter-wide source
continuity, platform AI disclosure, inauthentic-risk review, Korean
script/TTS/caption sync, directed editorial review, audible/ducked chapter
audio, full-watch defect control, and a computed score of at least 72. A
self-declared score that does not match the computed score is rejected.

### Golden Reference Operational Checks

The golden-reference report also has operational checks:

- `required`
- `preset`
- `sceneList`

These are not post-edit quality rules, but they are still registered so a
manifest cannot silently skip the golden-reference path, use an unknown preset,
or render with an empty scene list.

### Golden Reference Top-Level Gates

The top-level golden-reference checks are:

- `sourceContactSheet`
- `sourceSequenceContinuity`
- `visualUnityTreatment`
- `openingAudioContinuity`
- `postEditGoldenReference`

These run before a reference/golden FFmpeg render can be treated as valid.

### Golden Reference Scene Gates

Every scene in a reference/golden manifest is checked for:

- `sourceContract`
- `sourceQualityRubric`
- `sourceArtifact`
- `promptContract`
- `captionContract`
- `copyTone`
- `layoutContract`
- `captionDirection`
- `ttsScriptQuality`
- `referenceParity`

These are generic gates. They must not encode a specific product, topic,
object, incident, or episode.

### Post-Edit Subcontracts

`postEditGoldenReference` must manage these subcontracts:

- `score`
- `editorialDirection`
- `hook`
- `captions`
- `layoutHud`
- `capcutHandoff`
- `externalEditElements`
- `rhythm`
- `audio`
- `color`
- `payoff`

These subcontracts are separate because source quality alone cannot compensate
for weak direction, awkward Korean, bad caption layout, weak TTS pacing, missing
BGM, decorative effects, or fake CapCut handoff evidence.

### Evidence Schemas

The registry must cover the schema constants enforced by the golden-reference
gate:

- `video-studio.editorial-pass.v1`
- `video-studio.post-edit-score.v1`
- `video-studio.reference-comparison.v1`
- `video-studio.capcut-draft-audit.v1`

## Update Workflow

When adding or changing a gate:

1. Update the enforcing code first.
2. Update `config/gate-ontology.json`.
3. Link at least one existing or new reference document in `docPaths`.
4. Link code symbols in `codeAnchors`.
5. Link test symbols in `testAnchors`.
6. Add or update focused tests when no existing test can actually catch the
   gate drift.
7. Run `python -m pytest -q tests/test_gate_ontology.py`.
8. Run the focused gate tests that own the changed layer.
9. Run `npm run build` when UI, bridge summaries, final-library readiness, or
   generated reports are affected.

Do not mark a gate as covered only because it appears in a manifest template.
Coverage requires code enforcement and a test anchor.

## Anti-Overfit Rules

- Keep global gates generic. Episode prompt bibles can name the concrete
  object, person, place, or topic; this ontology cannot.
- Do not add a single-topic, single-project, or one-candidate criterion to the
  global gate registry.
- Do not split every render-quality key into a standalone document. Grouped
  coverage is acceptable when the group has code, docs, and tests.
- Do not count CapCut draft existence, effect count, SFX count, score parity, or
  self-written evidence as quality by itself. The linked gate must prove actual
  code/evidence parity.
- Do not use this document to weaken an existing gate. A weakening must be
  visible in code, docs, and tests.

## Verification Commands

Minimum ontology verification:

```powershell
python -m pytest -q tests\test_gate_ontology.py
```

Recommended full gate verification after ontology or gate changes:

```powershell
python -m py_compile worker\quality_gate_system.py worker\bridge\routes_grok.py worker\bridge\routes_sources.py worker\render\production_mode_gate.py worker\render\production_packet_lock.py worker\render\golden_reference_gate.py worker\render\capcut_handoff.py worker\render\compose_ffmpeg.py worker\bridge\routes_episodes.py worker\bridge\routes_media.py
python -m pytest -q tests\test_gate_ontology.py tests\test_production_mode_gate.py tests\test_grok_handoff.py tests\test_editorial_sources.py tests\test_production_packet_lock.py tests\test_golden_reference_gate.py tests\test_capcut_handoff.py tests\test_episode_pipeline.py tests\test_manual_clip_pipeline.py
npm run build
```
