---
title: Longform Production Mode Gate
last_verified: 2026-06-21
reliability: primary
sources:
  - projects/video-studio/worker/render/production_mode_gate.py
  - projects/video-studio/config/gate-ontology.json
  - projects/video-studio/tests/test_production_mode_gate.py
  - projects/video-studio/worker/render/longform_workflow_gate.py
  - projects/video-studio/worker/render/longform_dryrun_readiness.py
  - projects/video-studio/worker/render/topic_discovery_gate.py
  - projects/video-studio/docs/reference/topic-discovery-community-signal.md
  - projects/video-studio/docs/reference/longform-storyboard-web-references.md
  - projects/video-studio/docs/reference/longform-power-user-production-references.md
  - projects/video-studio/docs/reference/longform-workflow-stage-gate.md
  - projects/video-studio/docs/reference/longform-minimum-release-gate.md
refresh_trigger: when adding a production format, changing Grok/Gemini provider roles, or preparing a longform source prompt bible
---

# Longform Production Mode Gate

Video Studio must not stretch a Shorts workflow into a longform workflow. A
10-minute target uses chapter, segment, evidence, voice, audio, and full-watch
contracts before render or final-readiness claims.

The executable source is `worker/render/production_mode_gate.py`. The ontology
source is `config/gate-ontology.json`.

## Topic Discovery Before Storyboard

Longform planning starts before storyboard. A topic must pass topic-discovery
gates before reference-ledger, packaging, storyboard, source prompt bible,
Grok/Gemini generation, or longform dry-run work.

Required topic-discovery gates:

- `topicSourceLedgerGate`: source ledger has fresh current/search/community
  observations with URLs, timestamps, and observations.
- `researchQueryPlanGate`: research plan covers search, trend, video, and
  community surfaces with current queries before candidates are chosen.
- `sourceAuthenticityGate`: source IDs are unique, URLs are real non-placeholder
  HTTP(S) locations, and source surfaces include search/trend/video/community.
- `communitySignalDiversityGate`: the selected topic has at least two valid
  community/social signals from distinct source IDs.
- `trendCrossCheckGate`: the selected topic is cross-checked with search/trend
  evidence, including at least one official/search surface.
- `curiosityAngleGate`: the selected topic has a working title, central
  question, knowledge gap, why-now reason, and viewer promise.
- `longformTopicFitGate`: `longform_10m` topics have at least five evidence
  references, six chapters, 18 segments, and three retention hooks.
- `audienceRetentionFitGate`: `longform_10m` topics name the first-30-second
  promise, title/thumbnail expectation, top moment, dip-risk mitigations, and
  chapter promises before storyboard.
- `safetyOriginalityGate`: rumor, privacy, defamation, protected-class,
  minor-safety, high-stakes, copying, and attribution risks are reviewed.
- `topicSelectionMatrixGate`: at least three candidates are scored by code, the
  selected topic meets the threshold, and rejected alternatives have reasons.

The detailed standard and external reference basis are maintained in
`docs/reference/topic-discovery-community-signal.md`.

## Storyboard First

A longform packet must pass storyboard gates before source prompt generation.
This is intentionally stricter than shortform. A 10-minute piece needs a
chaptered argument, viewer promise, retention plan, and external reference
ledger before Grok/Gemini source generation starts.

Required longform storyboard gates:

- `longformStoryboardGate`: storyboard object has a thesis or central question,
  viewer promise, and at least 18 timed beats.
- `chapterMarkerGate`: chapter markers start at 0 seconds, ascend, use at least
  10-second sections, and have titles.
- `retentionPlanGate`: first 30 seconds, title/thumbnail expectation, top moment,
  and dip-risk mitigations are explicit.
- `storyboardBeatCoverageGate`: beats cover every chapter with timing, visual
  intent, audio/narration intent, and provider role.
- `evidenceVisualBindingGate`: every chapter has at least one visual beat bound
  to that chapter's evidence item.
- `visualContinuityBibleGate`: shot language, color, layout rules, style rules,
  and recurring visual assets are locked before generation.
- `webReferenceLedgerGate`: durable external references include official-platform
  and research sources, and each reference maps to the gate keys it supports.

The web basis for these requirements is maintained in
`docs/reference/longform-storyboard-web-references.md`.

## Power-User Production Workflow

A longform packet must also pass creator/power-user workflow gates before source
prompt generation. These gates do not require expensive gear, a studio team, or
high-stimulation editing. They require the planning artifacts that power users
consistently build before a longform piece can survive production and review.

Required longform power-user gates:

- `packagingPremiseGate`: packaging plan has a premise, target viewer,
  first-ten-second expectation, payoff promise, at least three title options,
  and at least two thumbnail briefs.
- `productionFeasibilityGate`: feasibility plan has at least three owned risks,
  at least two kill criteria, and a resource/fallback plan.
- `roughCutRetentionMapGate`: rough-cut retention map starts at 0 seconds,
  ascends through the timeline, and states viewer questions plus payoffs.
- `creatorFeedbackLoopGate`: script, rough-cut, and final review passes have
  reviewer roles, decision rules, and an iteration policy.
- `derivativeClipPlanGate`: derivative clips have cadence, quality control,
  source beat/chapter binding, and context-preservation rules.
- `powerUserCaseLedgerGate`: external creator/industry cases plus research
  sources are logged with takeaways and applied gate keys.

The case/research basis for these requirements is maintained in
`docs/reference/longform-power-user-production-references.md`.

## Workflow Stage Order

Production-mode gates answer whether the longform packet has the right
contracts. The workflow stage gate answers whether the project is allowed to
advance to the next stage.

Required workflow-stage gates:

- `longformWorkflowOrderGate`: all twelve longform stages are registered in the
  canonical order from reference ledger through derivative clips.
- `longformWorkflowEvidenceGate`: every stage has exit criteria, and passed
  stages have evidence and reviewer roles.
- `longformWorkflowDependencyGate`: later stages cannot pass or become active
  before previous stages pass.
- `longformWorkflowImprovementLoopGate`: blocked or failed stages include an
  owner, next mutation, and verification command/evidence.
- `longformWorkflowSeededFailureGate`: the gate packet includes passing seeded
  failure cases for order, evidence, dependency, and improvement failures.

The detailed order and packet shape are maintained in
`docs/reference/longform-workflow-stage-gate.md`.

## Minimum Release Gate

The minimum release gate is a longform-only final/publish readiness layer. It
does not replace shortform golden-reference, post-edit, render-quality, or
final-library gates. It prevents a 10-minute candidate from being called
publishable when the evidence only proves that a rough cut rendered.

Required minimum release gates:

- `longformReleaseFormatGate`: `longform_10m`, 480-900 seconds, at least 6
  chapters, and at least 18 planned segments.
- `longformReleaseRightsGate`: every generated/source/evidence item has a
  release-approved rights status; research-only or non-commercial sources are
  blocked. Dreamina/Seedance requires explicit `commercialUseAllowed=true`.
- `longformReleaseDisclosureGate`: publish packets must record the AI-use
  decision, YouTube AI-use selection when realistic altered/synthetic media is
  present, disclosure statement, content credentials status, viewer-mislead
  review, and inauthentic-risk proof.
- `longformReleaseSourceContinuityGate`: chapter continuity ratio, accepted
  chapter coverage, source defect counts, and subject/camera/scale drift are
  checked separately from story structure.
- `longformReleaseScriptTtsCaptionGate`: Korean copy review, one voice, 115-170
  WPM, `<=0.30s` caption/TTS drift, no duplicate caption/TTS wording, and
  safe-zone review.
- `longformReleaseEditorialGate`: directed edit, motivated cuts, safe
  layout/HUD, source-bound cues, and no-HUD/baseline comparison are required.
- `longformReleaseAudioGate`: audio stream, narration ducking, chapter audio
  beds, visible-event cue binding, peak, and mean loudness are required.
- `longformReleaseFullWatchGate`: full-watch review covers the timeline and
  every chapter with no unresolved critical/major issues.
- `longformReleaseScoreGate`: code computes the 100-point score and rejects
  self-asserted score inflation.

The threshold is `72/100`, which means minimally publishable, not excellent. A
hard-gate failure still sets `releaseAllowed=false`.

Detailed packet shape and score weights are maintained in
`docs/reference/longform-minimum-release-gate.md`.

## Dry-Run Readiness Preflight

Before a real longform E2E dry run, run the single readiness preflight instead
of checking the underlying gates one by one. The packet must include:

- `topicDiscoveryPacket`
- `workflowPacket`
- `productionModePacket`
- `renderManifest`
- `longformMinimumReleasePacket` when the target stage or render manifest claims
  final, upload, channel-ready, top-tier, release, or publish readiness
- `finalLibraryAudit` for final/publish dry runs

The executable source is `worker/render/longform_dryrun_readiness.py`. Its CLI
shape is:

```bash
python -m worker.render.longform_dryrun_readiness path/to/dryrun-readiness-packet.json --project-root .
```

The preflight returns `dryrunAllowed=false` unless these gates pass:

- `dryrunTopicDiscoveryGate`
- `dryrunWorkflowGate`
- `dryrunProductionModeGate`
- `dryrunRenderPreflightGate`
- `dryrunMinimumReleaseGate`
- `dryrunFinalLibraryGate`

For rough-cut targets, the minimum-release and final-library gates are skipped.
For final/publish targets, upload/channel/top-tier flags are not trusted by
themselves. The final-library audit must also prove
`longformMinimumReleaseReady=true` and `longformMinimumReleaseStatus=pass`.

## Format Profiles

`formatProfile` must be explicit before source prompt generation:

- `shortform_vertical`: scene/take first, 9:16, fast hook, short caption windows.
- `longform_10m`: chapter/segment/evidence first, 480-900 seconds, restrained
  lower-third or chapter captions.

The `formatProfileGate` blocks unknown or missing format profiles.

## Render Preflight Enforcement

Longform render manifests are blocked before FFmpeg by
`worker/render/production_packet_lock.py`, which is already called from the
render orchestrator. A manifest is treated as longform when it declares
`formatProfile=longform_10m` or has longform-range duration (`durationSec` or
summed scene duration at least 480 seconds).

Before render, the manifest must provide one of:

- `productionModePacketPath`
- `productionModeGatePacketPath`
- `sourcePromptBiblePath`
- `sourcePromptBibleJsonPath`
- `productionPacketPath`
- `productionModePacket`
- `productionModeGatePacket`
- `sourcePromptBible`
- `productionPacket`

The referenced object is re-evaluated with
`evaluate_production_mode_gate()`. A self-asserted pass report is not enough.
If the packet is missing, malformed, outside the project root, or fails any
longform production/storyboard/power-user gate, render startup returns
`renderAllowed=false` and writes `active-production-packet-lock.json` without
running FFmpeg.

The render manifest itself is not accepted as the production-mode packet. A
longform render must reference a durable packet path or provide an explicit
packet object under one of the keys above, so final manifests cannot silently
skip the production packet review boundary.

If the longform render manifest also claims final or publish readiness, the
render lock requires one of:

- `longformMinimumReleasePacketPath`
- `longformReleasePacketPath`
- `minimumReleasePacketPath`
- `releaseGatePacketPath`
- `longformMinimumReleasePacket`
- `longformReleasePacket`
- `minimumReleasePacket`
- `releaseGatePacket`

The referenced object is evaluated with
`evaluate_longform_minimum_release_gate()`. Rough-cut longform renders skip this
minimum release gate, but final/publish claims cannot skip it.

The source-generation routes must use the same packet before generating
Grok/Gemini sources. Route-level wiring is intentionally tracked separately
because the existing Grok/media routes may be locked by active production work,
but render cannot bypass this gate.

Rights evidence is conservative: `creative-commons` or `cc` by itself is
ambiguous and fails unless paired with explicit `commercialUseAllowed=true`.
Specific release-compatible statuses such as `cc0`, `cc-by`, `cc-by-sa`,
`owned`, `licensed`, `operator-approved`, or `commercial-approved` can pass.
Non-commercial/no-derivatives statuses such as `cc-by-nc` or `cc-by-nd` are
blocked rather than resolved by a contradictory commercial flag.

## Grok/Gemini Provider Roles

Provider role separation must be declared in `providerRoleMatrix` before
Grok/Gemini prompt generation.

Default roles:

| Role | Preferred provider | Rule |
|---|---|---|
| `primaryMotion` | `grok-web-video` | Use for motion source clips, especially first-hook action and physical scene beats. |
| `referenceStill` | `gemini-web-image` | Use for visual bible, diagram, style, continuity, or reference stills. It is not a motion source. |
| `fallbackMotion` | `gemini-web-video` | Use only with `when` or `reason`, usually when Grok fails motion/source continuity. |

Required provider-role gates:

- `providerRoleMatrixGate`
- `grokPrimaryMotionGate`
- `geminiReferenceGate`
- `geminiFallbackMotionGate`

This prevents a Gemini still from being treated as a motion source, or a Grok
MP4 from being used as a reference-still substitute.

## Longform 10m Gates

`longform_10m` requires these gates before render:

- `longformOutlineGate`: at least 6 chapters and 18 planned segments; each
  chapter has a title and claim.
- `chapterContinuityGate`: chapters have unique ids and bridge continuity.
- `evidenceDensityGate`: each chapter has at least one evidence item.
- `sourceRightsCitationGate`: every evidence item has citation/source URL plus
  acceptable rights status.
- `longformVoiceConsistencyGate`: one voice provider and voice id; narration
  pace stays in a longform range.
- `longformEditRhythmGate`: no Shorts-style giant center caption mode; static
  holds and average cuts are bounded.
- `chapterAudioBedGate`: narration ducking is enabled and every chapter has an
  audio bed.
- `fullWatchReviewGate`: required only when a longform candidate claims final
  readiness; sample review is not enough.

## Minimal Packet Shape

```json
{
  "formatProfile": "longform_10m",
  "providerRoleMatrix": {
    "primaryMotion": "grok-web-video",
    "referenceStill": "gemini-web-image",
    "fallbackMotion": {
      "provider": "gemini-web-video",
      "when": "only if Grok fails chapter action continuity"
    }
  },
  "storyboard": {
    "thesis": "A longform question answered through chaptered evidence.",
    "viewerPromise": "The viewer understands the decision path by the end.",
    "chapterMarkers": [
      {"chapterId": "chapter-01", "startSec": 0, "title": "Opening question"}
    ],
    "retentionPlan": {
      "first30SecPromise": "Open with the question and visible payoff.",
      "titleThumbnailExpectation": "The opening matches the title and thumbnail.",
      "topMomentPreview": "Preview the strongest evidence beat early.",
      "dipRiskMitigations": [
        {"risk": "dry evidence section", "mitigation": "cut to visual proof"}
      ]
    },
    "beats": [
      {
        "beatId": "chapter-01-seg-01-beat",
        "chapterId": "chapter-01",
        "startSec": 0,
        "durationSec": 24,
        "visualIntent": "Show the chapter setup as evidence-led action.",
        "narrationIntent": "State the viewer question in plain language.",
        "providerRole": "primaryMotion",
        "evidenceRef": "evidence-01-01"
      }
    ],
    "visualContinuityBible": {
      "shotLanguage": "calm documentary push-ins and evidence inserts",
      "colorTreatment": "neutral daylight grade",
      "layoutRules": "chapter lower thirds stay outside primary evidence",
      "styleRules": ["use one caption grid"],
      "recurringAssets": ["chapter marker lower-third"]
    },
    "webReferenceLedger": {
      "references": [
        {
          "title": "YouTube Help: Video Chapters",
          "url": "https://support.google.com/youtube/answer/9884579?hl=en",
          "sourceType": "official-platform",
          "retrievedAt": "2026-06-21",
          "takeaways": ["Use 0-second ascending chapter markers."],
          "appliedGateKeys": ["chapterMarkerGate"]
        }
      ]
    }
  },
  "powerUserProductionPlan": {
    "packagingPlan": {
      "premise": "A clear longform promise that can be understood before watching.",
      "targetViewer": "The intended viewer segment.",
      "firstTenSecondExpectation": "The opening states the question, stakes, and visual payoff.",
      "payoffPromise": "The ending resolves the original question.",
      "titleOptions": ["Option A", "Option B", "Option C"],
      "thumbnailBriefs": [
        {"visualHook": "single clear subject", "contrastPoint": "before versus after"},
        {"visualHook": "decision moment", "subject": "primary topic"}
      ]
    },
    "feasibilityPlan": {
      "risks": [
        {"risk": "source continuity breaks", "mitigation": "use continuity bible", "owner": "producer"}
      ],
      "killCriteria": ["no first-ten-second premise", "no source path for evidence"],
      "resourcePlan": {
        "owner": "producer",
        "sourceBudget": "declared budget or zero-paid path",
        "fallbackPath": "reference still or editorial source fallback"
      }
    },
    "roughCutRetentionMap": [
      {
        "startSec": 0,
        "viewerQuestion": "What decision are we resolving?",
        "payoff": "Show that the answer will arrive later.",
        "sourceBeatId": "chapter-01-seg-01-beat"
      }
    ],
    "feedbackLoop": {
      "iterationPolicy": "Revise until script, rough cut, and final passes have concrete decisions.",
      "reviewPasses": [
        {"stage": "script", "reviewerRole": "producer", "decisionRule": "central promise is clear"},
        {"stage": "roughCut", "reviewerRole": "editor", "decisionRule": "minute map has no dead section"},
        {"stage": "final", "reviewerRole": "operator", "decisionRule": "full watch has no unresolved dip"}
      ]
    },
    "derivativeClipPlan": {
      "cadence": "three clips after longform approval",
      "qualityControl": "clips preserve source context",
      "clips": [
        {
          "clipId": "clip-01",
          "sourceBeatId": "chapter-01-seg-01-beat",
          "platform": "shorts",
          "hook": "the core question in one sentence",
          "viewerPromise": "watch the full piece for the evidence chain",
          "contextPreserved": true
        }
      ]
    },
    "powerUserCaseLedger": {
      "references": [
        {
          "title": "Creator workflow reference",
          "url": "https://example.com/reference",
          "sourceType": "creator-case",
          "retrievedAt": "2026-06-21",
          "takeaways": ["Mapped to a reusable longform workflow gate."],
          "appliedGateKeys": ["packagingPremiseGate"]
        }
      ]
    }
  },
  "chapters": [
    {
      "chapterId": "chapter-01",
      "title": "Chapter title",
      "claim": "Chapter claim",
      "segments": [
        {"segmentId": "chapter-01-seg-01", "purpose": "setup"},
        {"segmentId": "chapter-01-seg-02", "purpose": "evidence"},
        {"segmentId": "chapter-01-seg-03", "purpose": "implication"}
      ],
      "evidence": [
        {
          "evidenceId": "evidence-01-01",
          "sourceUrl": "https://example.com/source",
          "rightsStatus": "operator-approved",
          "citation": "Source name"
        }
      ]
    }
  ],
  "voicePlan": {
    "provider": "edge-tts",
    "voiceId": "ko-KR-SunHiNeural",
    "targetWpm": 140
  },
  "editPlan": {
    "captionMode": "chapter-lower-third",
    "maxStaticHoldSec": 10,
    "averageCutSec": 9
  },
  "audioPlan": {
    "duckingEnabled": true,
    "chapterBeds": [
      {"chapterId": "chapter-01", "bedId": "bed-01"}
    ]
  }
}
```

This example is a shape reference only. A real longform packet must include all
chapters, all segments, all evidence items, and at least four durable
`webReferenceLedger.references` entries that include official-platform and
research-paper sources. It must also include a complete
`powerUserProductionPlan` with enough titles, thumbnail briefs, risks, kill
criteria, rough-cut retention entries, derivative clips, and external references
to satisfy the power-user gates above.

## Final Readiness

Longform final readiness requires a full-watch review:

```json
{
  "claimFinalReady": true,
  "fullWatchReview": {
    "completed": true,
    "durationSec": 610,
    "reviewer": "operator",
    "humanReviewNote": "Watched full render for pacing, BGM, captions, and source continuity."
  }
}
```

Do not mark a 10-minute candidate ready based on a contact sheet, a short sample,
or a few isolated frames.
