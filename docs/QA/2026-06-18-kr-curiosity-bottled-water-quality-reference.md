# KR Curiosity Bottled Water Quality Reference

Date: 2026-06-18
Task: `VIDEO-STUDIO-KR-CURIOSITY-QUALITY-REFERENCE-20260618-01`
Packet: `storage/approval-packets/kr-curiosity-bottled-water-20260616/production-approval-packet.json`
Preset: `kr_curiosity_explainer`

## Purpose

This note converts the 2026-06-18 web/reference pass and V2 feedback into a
reusable quality benchmark. It is not a one-off taste note. Future V3+ work must
compare against this file before claiming that visible quality improved.

## Current Baseline

- Baseline render:
  `storage/final-videos/kr-curiosity-bottled-water-v2-20260618/kr-curiosity-bottled-water-v2-20260618.mp4`
- Baseline contact sheet:
  `storage/final-videos/kr-curiosity-bottled-water-v2-20260618/final-contact-sheet.jpg`
- SHA-256:
  `8E8FC4790F18C7615F2BD3E3B9F490A0B517C250D7CE891E74AC970FD327EFBB`
- Technical proof already passed: 1080x1920, 30 fps, H.264/AAC, 15.800 s,
  FFmpeg decode pass, JSON parse pass, golden reference gate tests pass, build
  pass.
- Editorial verdict: V2 is a layout improvement, not a final quality win. The
  remaining ceiling is source quality and source continuity, especially
  720p AI softness, inconsistent hand/bottle identity, and weak first-second
  physical action.

## Reference Direction From Web Pass

- YouTube Shorts creator guidance keeps the target mobile-first and edit-first:
  vertical phone capture, filters, captions, and timed caption snippets are
  native expectations.
  Source: https://www.youtube.com/creators/shorts/
- YouTube Shorts editing guidance makes cut order, clip trimming, text timing,
  visual guides, and beat sync first-class editing controls. That means Video
  Studio should treat cut cadence, caption entrance/duration, and safe-zone
  placement as structured manifest fields, not only subjective review notes.
  Source: https://support.google.com/youtube/answer/16215842
- YouTube Shorts templates define reusable structure through clip count/length,
  text, music, and effects. For Video Studio, a "golden reference" should be a
  reusable edit template: role sequence, cut timing, caption role, layout anchor,
  transition intent, and proof evidence.
  Source: https://support.google.com/youtube/answer/16738000
- TikTok in-feed specs reinforce 9:16 vertical delivery and safe-zone review.
  Captions, app UI, anchors, and device preview variance mean text cannot sit
  at arbitrary bottom/right positions.
  Source: https://ads.tiktok.com/help/article/tiktok-auction-in-feed-ads?lang=en&redirected=2
- Google DeepMind Veo guidance points to reference images, style references,
  character/object consistency, and scene extension as quality levers. For this
  packet, that translates to a source bible: same bottle, same cap/label
  behavior, same hand scale, same daylight, and adjacent camera grammar.
  Source: https://deepmind.google/models/veo/
- Google Flow/Veo updates emphasize "Ingredients to Video", first/last frame
  control, scene extension, richer audio, and more narrative control. For this
  packet, V3 should use reference ingredients or continuity anchors before
  relying on post-edit decoration.
  Source: https://blog.google/innovation-and-ai/products/veo-updates-flow/

## Source Prompt Web References (2026-06-19)

This pass is specifically about improving the AI-generated source clips. The
main lesson from the web references is that "better prompt" does not mean more
adjectives. It means a production bible that locks identity, camera, action,
audio, and edit continuity before any model generation happens.

| Reference | Quality clue | V4 application |
|---|---|---|
| Google DeepMind Veo prompt guide | Strong prompts specify shot framing/motion, style, lighting, character description, location, action, and dialogue. Complex motion should be directed as a play-by-play, and sound should be named explicitly. | Each scene prompt must include `shotFraming`, `cameraMotion`, `objectIdentity`, `locationContinuity`, `actionBeat`, `dialoguePolicy`, and `audioIntent`; no scene can be a generic "bottle in sun" prompt. |
| Google DeepMind Veo model page | Veo is positioned around prompt adherence, realism/physics, creative control, consistency, and native audio. The examples combine framing, background, camera push, ambient sound, score, and spoken line. | Judge generated clips on physics/action plausibility and audio/source ambience, not only visual prettiness. Prompt blocks must include the ambient sound bed even if final TTS/BGM is added later. |
| Google Flow | Flow's production model is ingredient-based: create or bring assets, reuse the same ingredients across clips, start a new shot from a scene image, control camera motion, and extend shots with continuous motion/consistent characters. | The next packet should use reference ingredients: the same clear bottle, cap/label behavior, hand, daylight surface, and at least one first-frame or last-frame bridge per adjacent scene. |
| Runway Gen-4 official page | Runway frames Gen-4 around world consistency: visual references plus instructions can keep characters, locations, objects, style, mood, and cinematography coherent across scenes. | If Grok/Gemini cannot accept reference images directly, emulate the same control by writing a strict reference-object bible and rejecting takes where the bottle/hand/world drifts. |
| Film continuity references | Continuity editing depends on temporal/spatial continuity, diegetic sound, match-on-action, establishing context, and viewer orientation. | Source prompts must define screen direction, object permanence, action handoff, and diegetic sound continuity before the cut-edit layer starts. |
| GEN3C research clue | Current video models can suffer from 3D/temporal inconsistency such as objects appearing or disappearing when camera control is weak. | Treat source drift as a model-limit risk. Use references, scene images, locked camera moves, and take comparison instead of assuming one text prompt will preserve the world. |

Sources:
- https://deepmind.google/models/veo/prompt-guide/
- https://deepmind.google/models/veo/
- https://blog.google/innovation-and-ai/products/google-flow-veo-ai-filmmaking-tool/
- https://runwayml.com/research/introducing-runway-gen-4
- https://en.wikipedia.org/wiki/Continuity_editing
- https://arxiv.org/abs/2503.03751

### V4 Source Prompt Bible Gate

Before another KR bottled-water render, the source prompt pack must include all
fields below. A render can be technically valid while still failing this gate.

| Field | Required content |
|---|---|
| `globalSourceContinuity` | One shared source world: outdoor summer daylight, one clear plastic water bottle, one believable hand scale, one camera personality, no random studio/product-ad scene. |
| `referenceIngredients` | Reference stills or text-locked visual bible for bottle silhouette, cap color, label/no-label policy, water level, condensation, hand, surface, car/shade context, and color grade. |
| `perSceneComposition` | For every scene: subject size, camera distance, angle, background, safe negative space, and what must stay visible after crop. |
| `actionContinuityChain` | Scene-to-scene physical progression: sun exposure -> pressure/heat cue -> cap/water-line cue -> car/shade implication -> answer/resolution. |
| `cameraContinuity` | Repeated focal-length feel, handheld amount, screen direction, and no unexplained jump from macro/product ad to cinematic stock shot. |
| `lightingContinuity` | Same daylight logic, shadow direction, warmth, contrast, and texture; color grade can polish only after this passes. |
| `audioIntent` | Source ambience expected per scene, plus whether model-native dialogue is forbidden, optional, or intentionally requested. |
| `negativeConstraints` | No burned-in English/Korean text, fake logos, extra bottles, warped hands, impossible cap/label changes, random people, or unrelated lab/diagram shots. |
| `takeMatrix` | Minimum two takes per scene, with selected/rejected reasons tied to source continuity, action clarity, object identity, and crop safety. |
| `sourceRejectRules` | Reject if object identity drifts, action is static, prompt produces a separate-world clip, first second lacks visible physical question, or post-edit frame/HUD is the only unity device. |

### Prompt Shape

Use this reusable structure for each generation prompt:

1. Global anchor: same bottle, same hand/world, same daylight, same camera
   grammar, same visual grade.
2. Scene role: hook/mechanism/evidence/implication/answer.
3. Shot description: frame size, angle, camera motion, subject position, safe
   crop area, and background continuity.
4. Action play-by-play: the visible physical event for the 6-8 second clip.
5. Audio note: ambient source sound, silence/dialogue policy, no model-generated
   narration unless explicitly requested.
6. Negative block: artifacts, unrelated objects, burned-in text, logo drift,
   and scene-world breaks.
7. Review target: what the contact sheet must prove before import.

## Presentation Grammar References

Source continuity is only one layer. V3 also needs a repeatable presentation
grammar so the edit does not feel like five source clips with captions pasted on
top. Use these reference directions for cut editing, caption performance, and
layout:

| Layer | Reference direction | V3 application |
|---|---|---|
| Cut editing | YouTube timeline editing and templates treat clip order, trim points, and clip count/length as reusable structure. | Define `editBeatNote`, role-specific `durationSec`, and a max unmotivated hold before render. |
| Beat sync | YouTube's beat-sync tool reflects a common Shorts expectation: cuts should feel paced, even when the audio is restrained. | Add a cut rhythm review: hook lands by 0.45 s, body captions land within 0.75 s, no unexplained hold over 3.2 s. |
| Caption staging | YouTube text tools allow multiple timed text messages, not one static paragraph. | Use short timed chips: one hook question, then body proof/action chips, then answer chip. |
| Safe layout | YouTube visual guides and TikTok safe zones both treat edge/right/bottom UI collisions as platform issues. | Keep right rail and bottom UI clear; require explicit `captionZone`, `mustNotCover`, and phone-sized review. |
| Reference templates | Shorts templates reuse clip length/count, text, music, and effects. | Store a `presentationGrammar` object per preset rather than copying one-off notes. |

### Golden Presentation Families

- `kr_curiosity_explainer`: best fit for bottled-water V3. The edit should feel
  like hook question -> mechanism -> evidence -> implication -> answer. Caption
  rhythm: one top hook, then lower proof/action chips. Layout rhythm: do not use
  the exact same lower chip position for every body scene unless the footage
  itself provides strong motion changes.
- `kr_micro_fact`: useful for stronger caption energy, but risky for this topic
  because it can become a text-card slideshow. Only borrow its punch if the
  bottle remains inspectable.
- `kr_maker_process`: useful for hand/object cut grammar. Borrow the process
  progression idea when V3 source clips show hand action, squeeze, move-to-shade,
  or car-window heat evidence.

## Code Application Plan

Compatibility boundary: branch-local render/preflight internals only. No DB
schema, external API, dependency, or exported cross-project contract is required
for the first implementation.

Recommended implementation path:

1. `worker/render/reference_style_presets.py`
   - Add `presentationGrammar` to each relevant preset.
   - Suggested shape:
     - `cutCadence`: `firstHookWindowSec`, `targetAverageCutSec`,
       `maxUnjustifiedHoldSec`, `sceneDurationSec`.
     - `captionPerformance`: `scene1Preset`, `bodyPreset`,
       `maxCompactChars`, `entranceSec`, `displayDurationSec`,
       `purposeSequence`.
     - `layoutRhythm`: `layoutVariantSequence`, `forbiddenRepeats`,
       `safeZoneRule`, `subjectProtectionRule`.
     - `transitionGrammar`: allowed transitions plus reason strings, such as
       `cut`, `fade`, `match-action`, `evidence-card-in`.
   - Extend `apply_reference_style_preset()` so it can write
     `captionPurpose`, `editBeatNote`, `layoutContract`, and
     `referencePresentationRole` when absent.
2. `worker/render/golden_reference_gate.py`
   - Add `_check_edit_presentation_contract()`.
   - Require structured cut/caption/layout fields for reference-styled renders,
     instead of accepting a generic "reference applied" note.
   - Fail if a scene exceeds the preset hold limit without `editBeatNote`, if
     caption entrance/duration is outside the reference range, or if body scenes
     repeat one layout without visible action justification.
3. `worker/render/compose_ffmpeg.py`
   - Reuse the existing `REFERENCE_EDIT_GRAMMAR_POLICY`,
     `_caption_density_issue()`, `_build_caption_system_review()`, and
     `_build_template_source_review()` surfaces.
   - Move the current note-grep style `referenceEditGrammarTerms` toward
     structured `presentationGrammar` checks so review evidence is deterministic.
4. `worker/render/subtitles.py`
   - Keep existing `TopHook` and `LowerInfo` as the baseline.
   - Add only if needed: narrower role variants such as `CuriosityHook`,
     `EvidenceChip`, and `AnswerChip`. Avoid introducing a new style family
     unless screenshots show the existing styles cannot carry the reference.
5. Tests
   - Extend `tests/test_reference_style_presets.py` to require
     `presentationGrammar`.
   - Extend `tests/test_golden_reference_gate.py` with rejection cases for:
     missing edit beat, long hold without justification, caption timing outside
     range, repeated layout without visible-action justification, and unsafe
     caption zone.

This keeps the change measurable: a future render either satisfies the same
cut/caption/layout grammar as the reference family, or it fails before we call it
a quality improvement.

## Visual Unity Is Not Limited To HUD

HUD, frame lines, and camera marks are acceptable only as a light post-edit
treatment. They are not the main quality lever. A future candidate can feel like
one video through any of these stronger continuity devices:

1. Source-level continuity: same bottle silhouette, cap color, label behavior,
   water level, hand scale, and daylight direction across all scenes.
2. Camera grammar: repeated close-up distance, handheld motion amount, focal
   length feel, and object-first framing.
3. Location logic: one believable environment progression, such as outdoor sun
   surface -> car window heat -> hand squeeze -> hot car -> shade/cooler bag.
4. Edit grammar: hook question -> mechanism -> evidence -> implication ->
   answer, with each scene adding a visible physical action.
5. Caption system: one Korean caption family, stable safe-zone anchor, no
   arbitrary position jumps, and no captions covering bottle/hands/water line.
6. Color and texture: one restrained warm daylight grade, matched contrast,
   matched noise/sharpening, and no scene that looks separately generated.
7. Audio continuity: consistent narration pace, room tone/BGM bed, and no
   per-scene audio identity jumps.
8. Proof-object continuity: the bottle must stay inspectable. Random B-roll,
   abstract diagrams, and source clips where the bottle is secondary should fail.

## Quality-Up Clues

- If V3 only adds a prettier border, HUD, glow, or matte over the same weak
  sources, reject it as polish-only.
- If the selected source clips still look like unrelated AI generations, reject
  it even when the final frame/caption treatment is consistent.
- If the first two seconds do not show a concrete physical question or action,
  the hook is not strong enough.
- If captions cover the bottle, hand action, water line, car heat context, or
  platform UI safe areas, treat the layout as a quality regression.
- If the source files stay at soft 720p and the object identity drifts between
  scenes, the render can be upload-formatted but should not be called "good".
- The next real ratchet is a V4 source-generation bible, not another FFmpeg-only
  pass: reference ingredients, same object identity, first/last frame continuity,
  and per-scene action constraints.

## V3 Acceptance Gate

Before accepting a V3 render as visibly better than V2, record evidence for each
gate below:

| Gate | Pass condition |
|---|---|
| Baseline comparison | V2 and V3 contact sheets are reviewed side by side from phone-sized distance. |
| First-second hook | Scene 1 shows a clear bottle/sunlight physical question before the viewer reads the full caption. |
| Cut rhythm | Scene durations and holds match the preset cadence; no body scene holds over 3.2 s without an edit-beat reason. |
| Caption performance | Captions enter within the role-specific timing window, stay compact, and disappear before they become static labels. |
| Layout rhythm | Layout anchors vary by scene role or are justified by visible motion; the edit does not repeat one caption layout mechanically. |
| Source continuity | Bottle, cap/label behavior, hand scale, daylight, and camera distance read as one source world. |
| Action continuity | Every scene adds visible action or state change, not only narration over a static object. |
| Subject protection | Captions and treatments never cover bottle, hands, water line, car heat cue, or shade action. |
| Platform safe zone | Text avoids bottom/right UI risk and remains readable in 9:16 mobile review. |
| Source artifact check | AI softness, warped hands, fake labels, and random object drift are lower than V2. |
| One-package feel | The video feels unified even with HUD/frame disabled. |
| Audio/narration | Pacing is calmer than generic AI host narration and adds context beyond captions. |
| Proof trail | Final path, contact sheet, render review, ffprobe/decode proof, and SHA-256 are recorded. |

## Rejection Rules

- Reject "quality improved" if the only improvement is a frame, HUD, border,
  glow, or color grade.
- Reject if source-level continuity fails, even when the edit has a common
  overlay.
- Reject if V3 only changes captions/layout positions without a better cut
  rhythm, clearer caption staging, or safer subject protection.
- Reject if the body scenes all reuse one caption/layout position and the source
  motion does not justify that repetition.
- Reject if a generated source clip contains burned-in text, fake logo text, or
  an object that no longer reads as bottled water.
- Reject if the first screen is primarily a caption card rather than a visible
  object/action.

## Next Production Step

Create a V4 source prompt bible before rendering again. It should define the
shared object bible, same-world camera grammar, scene-to-scene action continuity,
and reference-image or first/last-frame strategy. Only after source acceptance
passes should the post-edit treatment be applied.

## 2026-06-21 Editorial Direction Addendum

V5/V5.8 exposed a separate failure class: CapCut draft creation, keyframe
counts, and visible effect layers did not automatically create better
direction. Symbolic X/OK/check overlays and unrelated SFX made the edit feel
crude when they were not motivated by the screen.

Before the next render/export attempt, apply the reusable gate in
`docs/reference/editorial-direction-gate.md` and the episode-specific edit plan
in `docs/QA/2026-06-21-kr-curiosity-bottled-water-editorial-direction-plan.md`.

New ordering:

1. Source continuity gate.
2. Editorial direction gate: shot intent, motivated cuts, caption performance,
   audio/source-event binding, continuity map, restraint, and reference
   comparison.
3. Clean CapCut handoff.
4. Phone-sized review and no-HUD/no-effect A/B.
5. Final render/export decision.

Do not use effect count, SFX count, draft id, or keyframe count as score
evidence unless the editorial direction contract proves what each layer is
doing for the viewer.
