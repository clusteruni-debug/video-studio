---
title: Editorial Direction Gate Reference
last_verified: 2026-06-21
sources:
  - YouTube Help Shorts editing tips
  - YouTube Help Enhance your Shorts
  - CapCut auto caption generator
  - CapCut sound effects
  - Soundify sound-effects-to-video research
  - Short-form accessibility research
  - Continuity editing and cutting-on-action references
reliability: vendor-doc
refresh_trigger: when changing post-edit golden gates, CapCut draft defaults, external edit-element policy, SFX binding rules, caption timing rules, or editorial scoring
---

# Editorial Direction Gate Reference

This is the durable Video Studio reference for post-source editorial direction.
It is intentionally above CapCut-specific automation. CapCut, FFmpeg, and any
future editor are implementation surfaces; the reusable quality contract is:
the edit must direct viewer attention through visible source events, motivated
cuts, caption timing, audio binding, continuity, and restraint.

## Reference History

Checked on 2026-06-21.

| Source | URL | Reusable finding | Video Studio application |
|---|---|---|---|
| YouTube Help, "Shorts editing tips" | `https://support.google.com/youtube/answer/13380879` | Sound sets tone; on-screen text should guide viewers through fast edits; the timeline controls when text appears, disappears, and layers front-to-back. | Captions and sound must have timed roles. A static repeated subtitle or untimed callout is not an edit. |
| YouTube Help, "Enhance your Shorts" | `https://support.google.com/youtube/answer/16215842` | Shorts editing includes audio-level adjustment, beat sync, visual guides, text timeline control, and safe placement warnings. | Every cut, caption, overlay, and audio change needs safe-zone and timeline review. |
| CapCut auto caption generator | `https://www.capcut.com/tools/auto-caption-generator` | Captions can be restyled and animated; style, font, color, effects, and motion are editable. | Caption performance must remain editable and timed; captions must not merely duplicate TTS. |
| CapCut sound effects | `https://www.capcut.com/tools/sound-effects` | Contextual audio matching analyzes motion, transitions, scene changes, tone, and pacing. | SFX and foley require a visible event, cut, transition, or ambience binding; random whooshes/beeps are rejected. |
| Soundify | `https://arxiv.org/abs/2112.09726` | Matching sound effects to video helps editors align sound categories to visual content. | Audio cues should be selected by visible source event and sync window, not by desired excitement. |
| Short-form accessibility research | `https://arxiv.org/abs/2402.10382` | Rapid visual changes, dense on-screen text, and music or meme-audio overlays can make short-form videos inaccessible and skippable. | The gate penalizes clutter, unrelated audio, and captions that try to replace missing visual information. |
| Continuity editing | `https://en.wikipedia.org/wiki/Continuity_editing` | Continuity editing connects shots across time, space, action, and diegetic sound to direct viewer attention. | Adjacent shots require continuity slots and no unexplained subject, camera, lighting, or audio jumps. |
| Cutting on action | `https://en.wikipedia.org/wiki/Cutting_on_action` | A cut can hide discontinuity when a subject begins an action in one shot and carries it through the next. | `motivatedCutPlan` allows match-action/action-carry-through cuts and rejects duration-ended cuts. |

## Gate Contract

Every golden/reference post-edit candidate must include:

```json
{
  "postEditGoldenReference": {
    "editorialDirection": {
      "required": true,
      "referenceBasis": [
        "YouTube Shorts timeline editing: text timing, audio, voiceover, and Shorts pacing",
        "CapCut caption and sound tools: editable captions plus sound effects matched to motion and scene changes",
        "Sound design research: SFX and foley must be synchronized to visible source events",
        "Short-form accessibility research: avoid dense on-screen text, rapid changes, and unrelated audio",
        "Continuity editing: match action, new information, diegetic sound, and viewer orientation across cuts"
      ],
      "evidence": {
        "directingPlanPath": "storage/qa/editorial-direction-plan.json",
        "phoneReviewPath": "storage/qa/editorial-phone-review.jpg",
        "referenceComparisonPath": "storage/qa/editorial-reference-comparison.json",
        "noHudComparisonPath": "storage/qa/editorial-no-hud-ab.jpg"
      },
      "shotIntentMap": [
        {
          "sceneId": "scene-001",
          "role": "hook-question",
          "viewerQuestionOrAnswer": "the viewer question or answer this shot carries",
          "visibleEvent": "the physical event visible in the source clip",
          "focusTarget": "what the viewer should inspect first",
          "sourceEventReadable": true,
          "subjectProtected": true,
          "captionExplainsMissingVisual": false
        }
      ],
      "motivatedCutPlan": [
        {
          "fromSceneId": "scene-001",
          "toSceneId": "scene-002",
          "cutAtSec": 1.35,
          "cutReason": "match-action",
          "visibleContinuityBridge": true,
          "newInformationRevealed": false,
          "actionContinuesAcrossCut": true,
          "unmotivatedHoldSec": 0
        }
      ],
      "audioVisualBinding": {
        "everyCueBoundToVisibleEvent": true,
        "unrelatedAudioCues": false,
        "maxSyncOffsetSec": 0.2,
        "minimumSfxCueCount": 0,
        "maxSfxCueCount": 6,
        "cues": []
      },
      "captionPerformance": {
        "notTtsDuplicate": true,
        "timelineReviewed": true,
        "safeZoneReviewed": true,
        "subjectOcclusion": false,
        "captionExplainsMissingVisual": false,
        "maxLines": 2,
        "maxCharsPerCaption": 24,
        "timelineCues": [
          {
            "sceneId": "scene-001",
            "startSec": 0.45,
            "endSec": 1.15,
            "text": "viewer-facing caption beat"
          }
        ],
        "ttsSegments": [
          {
            "sceneId": "scene-001",
            "startSec": 0.48,
            "endSec": 1.18,
            "text": "spoken context that does not duplicate the caption"
          }
        ]
      },
      "continuityMap": {
        "continuitySlots": [
          "primarySubject",
          "actorOrManipulator",
          "environment",
          "primaryAction",
          "camera",
          "lighting",
          "audio"
        ],
        "adjacentContinuityPassRatio": 0.8,
        "primarySubjectIdentityDrift": false,
        "primarySubjectScaleJump": false,
        "unexplainedCameraWorldJump": false
      },
      "restraintMode": {
        "effectsAreOptional": true,
        "effectCountIsNotQuality": true,
        "symbolCuesDefault": false,
        "noGeneratedStickerPresetSpray": true
      },
      "referenceComparison": {
        "comparedAgainstExternalReferences": 2,
        "noHudAbReviewed": true,
        "editImprovesComprehensionOverNoHud": true
      },
      "topicSpecificCriteriaInGlobalGate": false
    }
  }
}
```

Evidence is validated, not just checked for existence:

- `directingPlanPath` must be valid UTF-8 JSON with schema
  `video-studio.editorial-pass.v1` and pass/reviewed-pass status. It must carry
  `shotIntentMap[]`, `motivatedCutPlan[]`, `captionPlan[]`, `ttsSegments[]`,
  and `audioCueSheet[]`.
- `directingPlanPath` is not allowed to drift from the manifest contract. The
  gate compares shot-intent fields, cut fields, caption cues, TTS segments, and
  audio cue fields against the manifest, not just scene IDs.
- `referenceComparisonPath` must be valid UTF-8 JSON with schema
  `video-studio.reference-comparison.v1`, at least two external references,
  `noHudAbReviewed=true`, and `editImprovesComprehensionOverNoHud=true`.
- Phone/no-HUD review evidence must be non-empty image/video evidence, not a
  placeholder path.
- `shotIntentMap[]` scene IDs and order must exactly match `manifest.scenes[]`.
- `motivatedCutPlan[]` must match adjacent manifest scene pairs and `cutAtSec`
  must align with the manifest scene boundary.
- Timed caption cues and TTS segments must cover every scene, stay within
  `0.30s`, and avoid duplicate caption/TTS wording.
- SFX/foley/transition-hit cues must include `sceneId`, `startSec`,
  `sourceEvent`, and `auditOperationId`; the CapCut draft audit must contain a
  successful matching operation.

## Reject Rules

- Reject if `editorialDirection` is absent in a golden/reference post-edit
  candidate.
- Reject if any shot lacks a visible event, focus target, viewer
  question/answer, or subject-protection decision.
- Reject if any visible event only exists in the caption or TTS.
- Reject cuts whose reason is only duration, convenience, or "looks cool".
- Reject cuts without match-action, new information, payoff, spatial
  reorientation, rhythm, audio bridge, or continuity bridge intent.
- Reject SFX, foley, transition hits, whooshes, beeps, risers, or stingers that
  do not name a visible source event and sync within `+/-0.20s`.
- Reject any gate that uses a minimum SFX/effect count as a quality floor.
- Reject captions that merely repeat TTS or explain what the source does not
  show.
- Reject fake/empty evidence JSON, evidence without the expected schema, or
  review-image placeholders too small to prove a real phone/no-HUD review.
- Reject shot intent or cut plans whose scene IDs do not match manifest order.
- Reject stale evidence where the directing plan has the right schema but does
  not match the manifest's shot intent, cut, caption, TTS, or audio cue fields.
- Reject cuts whose `cutAtSec` does not match the adjacent manifest scene
  boundary.
- Reject caption/TTS timing drift greater than `0.30s`.
- Reject SFX/foley/transition-hit cues that are not realized in the CapCut
  draft audit.
- Reject subject identity, scale, camera-world, lighting, or audio jumps that
  are not acknowledged and solved in the continuity map.
- Reject symbolic X/OK/check cues as a default style. A symbolic cue is an
  exception only when a cleaner source-bound cue cannot carry the beat and the
  exception is manually approved.
- Reject a candidate that does not compare the directed edit against a no-HUD
  or no-effect baseline.

## Scoring Implication

The post-edit score is not a free-form opinion score. The score dimensions map
to this contract:

- `hookClarity`: first shot intent, first visible event, first caption timing.
- `storyPayoff`: motivated cut plan and final resolved answer.
- `captionAccessibility`: caption performance plus safe-zone evidence.
- `editRhythm`: motivated cuts, no unmotivated holds, and beat pacing.
- `audioMix`: BGM continuity plus source-event-bound audio cues.
- `platformReferenceFit`: external reference comparison plus phone review.

The manifest score must also match a computed scoring evidence artifact with
schema `video-studio.post-edit-score.v1`. The evidence must include
`computedScore` and `scoreInputs` proving shot intent, motivated cuts, caption
plan, audio cue sheet, and CapCut draft audit were used. The gate also derives
the expected post-edit score from source-take dimensions, source-sequence
continuity, hook, payoff, copy/TTS, captions, rhythm, audio, color, and
platform-reference checks. A higher number typed into both the manifest and the
evidence JSON is rejected when it does not match that gate-derived score.

Source quality remains a separate gate. A directed edit can improve
comprehension, but it cannot pass a video whose source clips do not show the
claimed action.
