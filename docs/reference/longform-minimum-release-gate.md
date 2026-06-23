---
title: Longform Minimum Release Gate
last_verified: 2026-06-23
reliability: primary
sources:
  - projects/video-studio/worker/render/longform_minimum_release_gate.py
  - projects/video-studio/worker/render/production_packet_lock.py
  - projects/video-studio/tests/test_longform_minimum_release_gate.py
  - projects/video-studio/tests/test_production_packet_lock.py
  - projects/video-studio/config/gate-ontology.json
  - projects/video-studio/docs/reference/youtube-ai-disclosure-publish-gate.md
refresh_trigger: when changing longform final-readiness, minimum release score, source rights policy, publish disclosure policy, TTS/caption sync, full-watch review, or final render preflight
---

# Longform Minimum Release Gate

This gate is the longform equivalent of the shortform release/golden checks,
but it is not a replacement for them. Shortform keeps its scene/take,
golden-reference, post-edit, and final-readiness gates. Longform adds this
minimum release gate only when a `longform_10m` candidate claims final or
publish readiness.

The executable source is `worker/render/longform_minimum_release_gate.py`.
Pre-FFmpeg wiring lives in `worker/render/production_packet_lock.py`.

## When It Runs

The production packet lock requires this gate when both conditions are true:

1. The manifest is longform: `formatProfile=longform_10m` or duration is at
   least 480 seconds.
2. The manifest claims final or publish readiness, such as
   `finalReadinessClaim=true`, `releaseReadinessClaim=true`, or a ready
   publish/channel/top-tier status.

Longform rough-cut renders do not require this gate. They still require the
production-mode packet gate. This keeps iteration possible while preventing a
rough cut from being mislabeled as publishable.

## Required Gate Keys

`LONGFORM_MINIMUM_RELEASE_GATE_KEYS` is the managed inventory:

- `longformReleaseFormatGate`
- `longformReleaseRightsGate`
- `longformReleaseDisclosureGate`
- `longformReleaseSourceContinuityGate`
- `longformReleaseScriptTtsCaptionGate`
- `longformReleaseEditorialGate`
- `longformReleaseAudioGate`
- `longformReleaseFullWatchGate`
- `longformReleaseScoreGate`

Any new key must update the ontology, this document, and focused tests in the
same change.

## Scoring

The minimum release score is computed by code. A score typed into the manifest
or evidence packet is not trusted unless it matches the computed score.

Weights:

| Dimension | Points |
|---|---:|
| `storyPackage` | 12 |
| `evidenceRightsProviderSafety` | 13 |
| `publishDisclosureSafety` | 10 |
| `sourceVisualContinuity` | 18 |
| `scriptTtsCaptionSync` | 14 |
| `editorialDirectionLayout` | 13 |
| `audioBgmSfxMix` | 10 |
| `fullWatchDefectControl` | 10 |

Minimum release threshold: `72`.

This threshold means minimally publishable, not excellent. A hard-gate failure
sets `releaseAllowed=false` even if the computed score is high enough.

## Hard Rejects

Reject the longform final candidate when any of these are true:

- The packet is not `formatProfile=longform_10m`.
- Duration is outside 480-900 seconds.
- Fewer than 6 chapters or 18 planned segments are present.
- Any source/evidence item has missing, unclear, research-only,
  private-only, personal-use-only, non-commercial, unverified, or trial-only
  rights.
- Generic `creative-commons`/`cc` labeling is used without a specific
  release-compatible status (`cc0`, `cc-by`, `cc-by-sa`) or explicit
  `commercialUseAllowed=true` evidence.
- Non-commercial or no-derivatives CC statuses such as `cc-by-nc` or
  `cc-by-nd` are blocked for release even if a contradictory
  `commercialUseAllowed=true` flag appears.
- Dreamina/Seedance output is used without explicit
  `commercialUseAllowed=true`.
- `publishDisclosureReview.aiUseDecision` is not `yes` or `no`.
- Realistic altered/synthetic or GenAI-assisted media is present but the
  YouTube AI-use selection is not confirmed.
- Disclosure statement, content credentials status, viewer-mislead review, or
  inauthentic-risk proof is missing.
- The packet makes an inaccurate captured-with-camera/authenticity claim.
- Source continuity pass ratio is below `0.85`.
- Primary subject identity/scale/camera-world drift is unresolved.
- Accepted source coverage does not cover every chapter.
- Korean copy/TTS/caption review is not pass.
- TTS pace is outside 115-170 WPM.
- Caption/TTS drift exceeds `0.30s`.
- Captions duplicate TTS or explain missing visuals.
- Directed edit, motivated cuts, layout safe-zone review, source-bound cues, or
  no-HUD/baseline comparison are missing.
- Audio stream, narration ducking, chapter beds, visible-event cue binding, or
  loudness evidence is missing.
- Full-watch review is incomplete, does not cover the longform timeline, lacks
  reviewer evidence, has unresolved critical/major issues, exceeds
  `0.70` defects/minute, or misses chapter issue-log coverage.
- A declared score does not match the computed score.

## Minimal Packet Shape

```json
{
  "formatProfile": "longform_10m",
  "durationSec": 610,
  "chapters": [
    {
      "chapterId": "chapter-01",
      "title": "Opening question",
      "claim": "The viewer question is clear.",
      "segments": [{"segmentId": "chapter-01-seg-01"}],
      "evidence": [
        {
          "evidenceId": "evidence-01",
          "sourceUrl": "https://example.com/source",
          "rightsStatus": "operator-approved"
        }
      ]
    }
  ],
  "storyPackageReview": {
    "firstTenSecondExpectationMet": true,
    "titleThumbnailExpectationMet": true,
    "payoffPromiseResolved": true
  },
  "sourceReviewImport": {
    "chapterContinuityPassRatio": 0.9,
    "primarySubjectIdentityDrift": false,
    "primarySubjectScaleJump": false,
    "unresolvedSourceDefects": [],
    "acceptedChapterCount": 6,
    "acceptedSources": [
      {
        "sourceId": "source-001",
        "provider": "grok-web-video",
        "rightsStatus": "licensed",
        "commercialUseAllowed": true
      }
    ]
  },
  "publishDisclosureReview": {
    "aiUseDecision": "yes",
    "realisticGenAiOrAltered": true,
    "youtubeAiUseSelected": true,
    "disclosureStatement": "Contains realistic AI-assisted visuals created from operator-reviewed source prompts.",
    "contentCredentialsStatus": "not-applicable",
    "viewerMisleadRiskReviewed": true,
    "inaccurateAuthenticityClaim": false,
    "inauthenticRiskReview": {
      "massProducedTemplate": false,
      "originalInsightAdded": true,
      "substantiveVariation": true,
      "metadataTruthful": true,
      "reusedContentTransformative": true
    }
  },
  "scriptTtsCaptionReview": {
    "status": "pass",
    "voicePlan": {
      "provider": "edge-tts",
      "voiceId": "ko-KR-SunHiNeural",
      "targetWpm": 140
    },
    "maxCaptionTtsDriftSec": 0.18,
    "noDuplicateCaptionTts": true,
    "captionExplainsMissingVisual": false,
    "safeZoneReviewed": true
  },
  "editorialReleaseReview": {
    "directedEdit": true,
    "motivatedCutPassRatio": 0.9,
    "layoutSafeZoneReviewed": true,
    "noUnboundEffectCues": true,
    "noHudComparisonReviewed": true,
    "unresolvedEditorialIssues": []
  },
  "audioReleaseReview": {
    "audioStreamExists": true,
    "narrationDuckingEnabled": true,
    "chapterAudioBedsCovered": true,
    "everyCueBoundToVisibleEvent": true,
    "maxPeakDb": -4.0,
    "meanDb": -20.0
  },
  "fullWatchReview": {
    "completed": true,
    "durationSec": 610,
    "reviewerRole": "operator",
    "unresolvedCriticalIssues": 0,
    "unresolvedMajorIssues": 0,
    "defectDensityPerMinute": 0.2,
    "retentionDipMitigationsReviewed": true,
    "chapterIssueLog": [
      {"chapterId": "chapter-01", "issues": []}
    ]
  }
}
```

## Workflow Position

Before source generation:

1. Workflow stage gate passes through `source-prompt-bible`.
2. Production-mode gate passes storyboard, packaging, evidence, voice, edit,
   audio, and provider-role requirements.

Before rough-cut render:

1. Production-mode packet gate passes.
2. Minimum release gate is skipped unless the manifest claims final/publish
   readiness.

Before final render or publish-ready claim:

1. Production-mode packet gate passes.
2. Minimum release packet path/object passes this gate.
3. Final-library readiness, phone-sized review, and upload decision gates still
   run after render.

## Non-Goals

This gate does not:

- remove or weaken shortform gates
- replace shortform golden/reference preflight
- replace source prompt bible gates
- make a candidate excellent at 72 points
- approve rights when a provider's terms are unclear
- allow a rough cut to become a final candidate by changing wording
