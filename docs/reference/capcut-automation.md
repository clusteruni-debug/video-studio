---
title: CapCut Automation Reference
last_verified: 2026-06-20
reliability: vendor-doc
sources:
  - Editorial Direction Gate Reference
  - CapCut keyframe animation
  - CapCut auto caption generator
  - CapCut online video editor
  - CapCut video effect and filter
  - CapCut effects templates
  - CapCut sound effects
  - YouTube Help Enhance your Shorts
  - YouTube Help Shorts editing tips
  - TikTok Creative Center Top Ads
  - Microsoft Learn connected animation
  - Microsoft Learn timing and easing
  - VectCutAPI GitHub
refresh_trigger: when changing CapCut draft automation, handoff gate, VectCutAPI integration, edit-layer defaults, or final render policy
---

# CapCut Automation Reference

This ledger converts external references into a reusable CapCut automation
contract for Video Studio. It is intentionally generic: do not encode topic,
object, product, or episode-specific checks here.

## Source Reference History

| Source | URL | Reusable finding |
|---|---|---|
| Editorial Direction Gate Reference | `projects/video-studio/docs/reference/editorial-direction-gate.md` | CapCut draft creation is not a quality proof by itself. A candidate must first bind shot intent, cuts, captions, audio cues, continuity, restraint, and reference comparison in `postEditGoldenReference.editorialDirection`. |
| CapCut keyframe animation | https://www.capcut.com/tools/keyframe-animation | CapCut treats motion as editable keyframes with position, scale, rotation, opacity, color, and speed/easing controls. A high-quality handoff must preserve motion as editable objects, not only baked FFmpeg pixels. |
| CapCut auto caption generator | https://www.capcut.com/tools/auto-caption-generator | Captions are generated, edited, styled, synced, and exported inside the editor. A final-quality workflow must keep caption text/timing editable in CapCut. |
| CapCut online video editor | https://www.capcut.com/tools/online-video-editor | CapCut presents editing as a timeline with audio, text, stickers, effects, transitions, and filters. Effects are first-class layers, not an afterthought or static overlay claim. |
| CapCut video effect and filter | https://www.capcut.com/tools/video-effect-and-filter | Effects, filters, transitions, and animations are available in the editor timeline, but availability is not a quality signal. Generated drafts must not add stock effects by default; effect presets require explicit human selection and review. |
| CapCut effects templates | https://www.capcut.com/template/effects | Reusable effect language includes slow motion, glitch, flash, split, smooth, light leak, grain, and HUD-style overlays. These are high-risk canned looks for explainers; use none by default unless a human-selected preset is visibly anchored to source action, an on-screen cue, or an audio hit. |
| CapCut sound effects | https://www.capcut.com/tools/sound-effects | Sound effects should match motion, transitions, scene changes, tone, and pacing. Visual effect beats need paired or intentionally withheld SFX; arbitrary whooshes/beeps are rejected. |
| YouTube Help, Enhance your Shorts | https://support.google.com/youtube/answer/16215842 | Shorts editing is a multitrack timeline: video, text, stickers, music, voiceover, TTS, beat sync, and safe placement guides are reviewed together. |
| YouTube Help, Shorts editing tips | https://support.google.com/youtube/answer/13380879 | Sound and text guide fast edits and context; timeline review is part of publishing quality. |
| TikTok Creative Center Top Ads | https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en | Compare edit density and execution against high-performing vertical references instead of internal taste only. |
| Microsoft Learn, connected animation | https://learn.microsoft.com/en-us/windows/apps/develop/motion/connected-animation | Motion should preserve context and focus attention on the related content across a change. |
| Microsoft Learn, timing and easing | https://learn.microsoft.com/en-us/windows/apps/design/motion/timing-and-easing | Short UI motion commonly uses restrained durations and easing; linear/raw movement reads mechanical. |
| VectCutAPI GitHub | https://github.com/sun-guannan/VectCutAPI | Python automation can create CapCut/Jianying-style drafts with video, audio, image, text, subtitles, effects, stickers, and keyframes before operator review/export. |

## Golden Contract

Every golden/reference post-edit candidate must declare
`postEditGoldenReference.capcutHandoff`. The object is not a paperwork claim:
it must prove that CapCut is the primary final editing surface and that FFmpeg
output is only a preview until operator export/review.

CapCut handoff is still downstream of `postEditGoldenReference.editorialDirection`.
Do not treat a draft id, keyframe count, transition count, SFX count, or effect
track count as quality proof unless the editorial direction contract explains
the visible event, cut reason, caption role, audio binding, and reference
comparison that those tracks implement.

Minimum required shape:

```json
{
  "capcutHandoff": {
    "required": true,
    "draftRequired": true,
    "pipelineMode": "capcut-draft-first",
    "referenceBasis": [
      "CapCut keyframe animation: editable keyframes, speed curves, and easing",
      "CapCut auto caption generator: editable synced captions and style",
      "CapCut effects/filter tools: native effect layers, filters, transitions, and animations",
      "CapCut effects templates: flash, glitch, light leak, grain, HUD, and beat-layered effect grammar",
      "CapCut sound effects: SFX matched to motion, transition, scene change, tone, and pacing",
      "YouTube Shorts timeline: video, text, stickers, music, voiceover, and TTS",
      "TikTok Creative Center Top Ads: high-performing vertical reference review",
      "Microsoft timing/easing: restrained fast-out-slow-in motion",
      "VectCutAPI: generated CapCut/Jianying draft_content.json with tracks"
    ],
    "automationSurface": {
      "tool": "VectCutAPI",
      "targetEditor": "CapCut desktop",
      "draftFormat": "draft_content.json",
      "localDraftRootExists": true,
      "capcutInstallVerified": true,
      "finalExportByOperator": true,
      "ffmpegPreviewOnly": true
    },
    "editModel": {
      "multitrackTimeline": true,
      "editableTextAndTiming": true,
      "editableCaptions": true,
      "editableAudioLevels": true,
      "editableMotionElements": true,
      "nativeCapCutEffectsRequired": true,
      "editElementsUseNonTextVisuals": true,
      "extraTextCalloutsAllowed": false
    },
    "motionDesign": {
      "usesKeyframes": true,
      "usesEasing": true,
      "usesSpeedCurvesOrEasing": true,
      "minKeyframedElements": 2,
      "noRawDrawboxDrawtextFinal": true,
      "motionDurationMsMin": 83,
      "motionDurationMsMax": 400
    },
    "mediaLinked": {
      "sourceVideoTracks": true,
      "ttsTracks": true,
      "bgmTrack": true,
      "sfxTracks": true,
      "captionTracks": true,
      "editElementTracks": true,
      "effectTracks": true
    },
    "effectPass": {
      "required": true,
      "mode": "clean-editorial-no-canned-effects",
      "usesNativeCapCutEffects": false,
      "nativeEffectsDisabled": true,
      "generatedVisualEffectsDisabled": true,
      "forbidPngOnlyClaim": true,
      "manualPresetReviewRequired": true,
      "visualBindingRequired": true,
      "forbidUnanchoredEffects": true,
      "forbidPresetSpray": true,
      "cannedEffectsRejected": true,
      "effectTrackCount": 0,
      "minEffectTracks": 0,
      "maxEffectTracks": 0,
      "anchoredCueRoles": [],
      "requiredFamilies": [],
      "disallowedUnanchoredFamilies": [
        "atmosphere-light",
        "distortion",
        "scan-context",
        "impact-pulse"
      ],
      "candidateEffects": []
    },
    "draftPath": "storage/qa/capcut-draft",
    "draftContentPath": "storage/qa/capcut-draft/draft_content.json",
    "draftAuditPath": "storage/qa/capcut-draft-audit.json",
    "roundTripStatus": "draft-created"
  }
}
```

## Reject Rules

- Reject any golden/reference candidate that is FFmpeg-only final output.
- Reject a CapCut handoff without external reference basis covering CapCut,
  captions, Shorts timeline, TikTok reference comparison, motion/easing, and
  VectCutAPI-style draft automation.
- Reject burned-in final-only text, stickers, warning marks, or SFX when the
  CapCut draft does not preserve editable tracks.
- Reject generated stock/native effect tracks by default. CapCut is the editable
  timeline and operator export surface first; it is not an automatic effects
  engine.
- Reject "external effects" claims that are only PNG/image overlays. Generated
  overlays are disabled by default unless a later human-approved style system
  proves they are not template-looking.
- Reject a CapCut handoff without `effectPass` explicitly declaring whether the
  draft is clean-editorial/no-canned-effects or manually reviewed effects mode.
- Reject unanchored preset spray: atmosphere, scan, distortion, pulse, glitch,
  or light-leak effects are failures when they do not bind to a visible source
  action, on-screen cue, or audio hit.
- Reject effect-count inflation. More effect tracks are not better; clean
  editorial drafts should have `maxEffectTracks=0`.
- Reject raw `drawbox`/`drawtext` overlays as final-quality edit elements. They
  may exist in preview renders only.
- Reject CapCut drafts that are only a container for the existing video without
  an `editorialDirection` contract and evidence.
- Reject drafts where motion profiles contain topic-specific assumptions in the
  global gate. The handoff must speak in generic terms such as primary subject,
  source event, actor/manipulator, camera, lighting, and audio.
- Reject linear/mechanical motion with no keyframes, easing, or speed curve
  evidence.
- Reject a handoff that cannot prove local draft artifacts exist before review.
- Reject final/upload claims unless the operator has reviewed/exported the
  CapCut draft or the status is explicitly blocked at draft review.

## Pipeline Implication

The default order for final-quality Shorts/TikTok/Reels candidates is:

1. Generate or import source clips, TTS, BGM, SFX, captions, and edit-element
   plan.
2. Build a CapCut draft with editable multitrack assets.
3. Open the draft in CapCut for operator review.
4. Export from CapCut.
5. Run final MP4 verification on the exported file.

FFmpeg remains valid for preview, regression proof, contact sheets, and
machine checks. It is not allowed to claim final golden/reference post-edit
quality by itself.
