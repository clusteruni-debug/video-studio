# KR Curiosity Bottled Water Editorial Direction Plan

Date: 2026-06-21
Task: `VIDEO-STUDIO-EDITORIAL-DIRECTION-GATE-20260621-01`
Basis:
- `docs/reference/editorial-direction-gate.md`
- `docs/reference/external-edit-elements.md`
- `docs/reference/capcut-automation.md`
- `docs/QA/2026-06-18-kr-curiosity-bottled-water-quality-reference.md`

## Purpose

This plan tightens the next bottled-water edit before another render or CapCut
export attempt. The previous direction over-indexed on visible symbols, overlay
counts, CapCut draft ids, and keyframe counts. This plan treats those as tools,
not quality proof.

The goal is a directed short-form explainer that still works with HUD/effects
disabled: visible action first, short Korean captions second, TTS for context,
BGM/ambience for continuity, and only source-bound cues when a cue is truly
needed.

## Current Honest Baseline

Estimated current perceptual score: 58-62.

Reasons:
- Source continuity still has primary-subject scale drift across scenes.
- TTS and caption timing have previously desynced enough to undermine the
  numeric gate score.
- External edit layers have looked like pasted decoration rather than motivated
  direction.
- CapCut draft creation alone did not prove a better edit.

Do not label the next candidate 70+ unless the phone-sized full-watch review
and no-HUD comparison support that score.

## Editorial Direction Contract

The next render manifest or CapCut handoff must include
`postEditGoldenReference.editorialDirection` with these concrete values.

```json
{
  "required": true,
  "referenceBasis": [
    "YouTube Shorts timeline editing: text timing, audio, voiceover, and Shorts pacing",
    "CapCut caption and sound tools: editable captions plus sound effects matched to motion and scene changes",
    "Sound design research: SFX and foley must be synchronized to visible source events",
    "Short-form accessibility research: avoid dense on-screen text, rapid changes, and unrelated audio",
    "Continuity editing: match action, new information, diegetic sound, and viewer orientation across cuts"
  ],
  "evidence": {
    "directingPlanPath": "storage/qa/kr-curiosity-bottled-water-v6/editorial-direction-plan.json",
    "phoneReviewPath": "storage/qa/kr-curiosity-bottled-water-v6/editorial-phone-review.jpg",
    "referenceComparisonPath": "storage/qa/kr-curiosity-bottled-water-v6/editorial-reference-comparison.json",
    "noHudComparisonPath": "storage/qa/kr-curiosity-bottled-water-v6/editorial-no-hud-ab.jpg"
  },
  "topicSpecificCriteriaInGlobalGate": false
}
```

## Shot Intent Map

| Scene | Role | Viewer question/answer | Visible event required | Focus target | Caption role |
|---|---|---|---|---|---|
| 001 | Hook question | "Left in heat, is it still okay?" | A clear bottle is already visible in sunlight within 0.35s; no black/title/caption-only opening. | Bottle silhouette, cap, hand/surface scale. | One short top hook question. |
| 002 | Mechanism | "Heat changes the condition, not the sunlight word itself." | Hand/bottle state change or cap/water-line/condensation cue; not a static product shot. | Physical state cue. | Short proof chip, not TTS duplicate. |
| 003 | Evidence | "Smell/taste/condition decide caution." | Inspectable close-up or hand check action; same world/camera scale band. | Check action and bottle state. | Action chip. |
| 004 | Implication | "A hot car or long storage raises risk." | Car/shade/heat context that still belongs to the same source world. | Context cue, not random B-roll. | Caution chip. |
| 005 | Answer | "When unsure, do not drink it; replace or keep cool." | Calm resolution: bottle moved to shade/cooler or fresh replacement, not an abrupt blank end. | Final action and audio tail. | Answer chip. |

Hard rule: every scene must be readable with captions hidden. Captions may
name the beat, but they cannot invent the beat.

## Motivated Cut Plan

| Cut | Reason | Required bridge | Reject if |
|---|---|---|---|
| 001 -> 002 | `match-action` or `new-information` | Bottle/hand/object scale remains close enough that the cut feels like inspection progression. | Cut happens only because scene 001 duration ended. |
| 002 -> 003 | `new-information` | Mechanism cue becomes inspection cue. | Scene 003 looks like a separate stock/product world. |
| 003 -> 004 | `spatial-reorientation` | The edit deliberately widens from object check to storage context. | Car/shade context appears without visual bridge or caption role. |
| 004 -> 005 | `payoff` | Final action resolves caution and leaves at least 0.85s visual hold. | Final spoken/caption line cuts off or ends with a dangling phrase. |

No cut may have `unmotivatedHoldSec>0`.

## Caption Plan

Caption copy must be natural Korean and shorter than TTS. Avoid report-style
prose and awkward noun labels.

| Scene | Caption draft | Position | Timing | Notes |
|---|---|---|---|---|
| 001 | `차 안에 둔 물\\N마셔도 될까?` | top-left or top-center safe | 0.25s-1.45s | Question only. No black screen before it. |
| 002 | `뜨거웠다면\\N먼저 상태부터` | lower-mid | cut+0.25s to +1.7s | Do not repeat the exact TTS sentence. |
| 003 | `냄새·맛이 이상하면\\N멈추세요` | lower-mid | cut+0.25s to +1.8s | Action chip, not a warning sticker. |
| 004 | `오래 데운 물은\\N조심해야 해요` | upper-third or lower-mid | cut+0.25s to +1.8s | Avoid "햇빛 생수" phrasing. |
| 005 | `찜찜하면\\N새 물로 바꾸세요` | center-safe/lower-mid | cut+0.20s to +1.7s | Must leave final visual and BGM tail. |

Rejected copy:
- `햇빛 생수`
- `답은 보관 시간`
- `한 모금보다 보관 시간`
- Any caption that only repeats the TTS line.

## TTS Script Direction

Target: calm Korean, practical, not hosty. Edge TTS remains the default free
path unless a separate approved TTS replacement gate exists.

Draft:

1. `차 안에 오래 둔 물, 바로 마셔도 될까요?`
2. `중요한 건 햇빛 자체보다, 얼마나 뜨거운 곳에 있었는지예요.`
3. `냄새나 맛이 이상하거나 병이 뜨거웠다면, 마시지 않는 편이 낫습니다.`
4. `특히 차 안처럼 오래 달궈지는 곳은 더 조심해야 해요.`
5. `찜찜하면 버리고, 다음부터는 그늘이나 보냉 가방에 두세요.`

Rules:
- Voice must not continue after the scene cut.
- Captions must not advance before the corresponding voice beat.
- Final spoken line must complete before the last visual hold and BGM tail.
- Do not use over-friendly openings such as "여러분", "궁금하시죠", or
  "끝까지 보세요".

## Audio And Cue Plan

Use one restrained BGM/ambience bed across the full video.

Allowed cues:
- Soft transition bed or low thump only when a cut reveals new information.
- One tiny tactile cue on the inspection action if the visible action exists.
- No warning beep unless the frame shows a source event that justifies it.

Default: zero generated SFX is acceptable. If SFX is used, every cue must name:
`type`, `sourceEvent`, `bindingMode`, `startSec`, `syncOffsetSec`, `durationSec`,
and `decorativeOnly=false`.

Rejected:
- Random warning beeps.
- Whoosh on every cut.
- Meme audio.
- SFX used because the scene feels empty.

## External Edit Element Plan

Default mode: clean editorial, no generated symbols.

```json
{
  "externalEditElements": {
    "required": false,
    "cleanEditorialMode": true,
    "generatedVisualLayersAllowed": false,
    "generatedSfxAllowed": false,
    "manualExceptionOnly": true,
    "visualElementCount": 0,
    "audioCueCount": 0,
    "reasonNoGeneratedExternalElements": "The next version should prove the edit through visible source action, cut motivation, caption timing, BGM continuity, and CapCut keyframed motion before adding symbols.",
    "rejectionBasis": [
      "X/OK/check marks made earlier drafts feel crude.",
      "Random SFX did not bind to source events.",
      "Effect count inflated the gate score without improving comprehension."
    ]
  }
}
```

Manual exception:
- A small non-text cue may be added only if the phone review shows viewers miss
  a visible source event without it.
- Symbolic X/OK/check cues require explicit `manualExceptionApproved=true`.

## CapCut Handoff Direction

CapCut should be used as the editable timeline/export surface, not an automatic
effects engine.

Required:
- Source clips as editable video tracks.
- Caption timing editable in CapCut.
- BGM and TTS levels editable.
- Scene-directed keyframes for primary-subject scale continuity.
- No generated native effects in the default pass.
- No generated visual overlay or SFX unless the editorial direction contract
  has a source-event-bound exception.

Motion profiles must use generic primary-subject framing language. Do not put
bottled-water-specific logic in the global gate.

## Review And Score Gate

Before claiming improvement:

1. Save a no-HUD/no-effect comparison still or contact sheet.
2. Save a phone-sized review frame/contact sheet.
3. Save a reference comparison against at least two external references.
4. Re-score with evidence, not taste:
   - Source continuity
   - Shot intent readability
   - Motivated cuts
   - Caption performance
   - TTS/caption sync
   - Audio binding
   - Continuity map
   - Restraint/A-B comparison

Target for the next candidate:
- 65+ is plausible if edit direction, TTS sync, and captions improve while
  source continuity remains imperfect.
- 70+ requires source continuity to stop visibly fighting the edit.

Do not raise the score because a draft exists, because effects were added, or
because keyframe counts are high.
