# Reference Style Gold Samples

Created: 2026-06-15
Project: `video-studio`
Task: `VIDEO-STUDIO-REFERENCE-STYLE-PRESETS-20260615-01`

## Purpose

This packet prevents the repeated failure mode where "find references" becomes
an undocumented taste note and the renderer later claims improvement without a
stable benchmark.

Every reference below must translate into:

1. A durable reference row with region, audience, URL, source type, and limits.
2. A style breakdown for layout, captions, edit rhythm, audio, and payoff.
3. A code preset that can be applied to a render manifest.
4. A gold-sample checklist before any future render can claim upload-grade
   quality.

This is not a claim that the listed videos are licensed source material. They
are benchmark references only. Reusable source footage still needs rights,
operator ownership, public-domain status, or a generated/stock replacement that
passes source review. Still-image web sources are not interchangeable with
reference footage: outside meme/reaction/screenshot/source-capture or
evidence/reference/data-card roles, they are support material only and cannot be
the primary visual source for an explainer render.

## Collection Method

- Public YouTube Shorts tabs and video pages were inspected on 2026-06-15.
- The first pass captured channel, video ID, title, duration metadata, and
  high-level format grammar.
- Frame-by-frame playback notes should be added before a candidate is promoted
  from "reference-coded" to "gold sample accepted".
- The target for the next Video Studio quality reset is Korea-first curiosity
  and maker/process content. Global visual-magic references are useful for
  ambition, but they are not the default automation target because they require
  actors, props, staged camera tricks, or VFX.

## Target Audiences

| Audience key | Primary region | Viewer | Best use in Video Studio | Avoid |
|---|---:|---|---|---|
| `kr_casual_curiosity_20_40` | KR | Korean casual Shorts viewers who like "why is this like that?" facts, object trivia, science, packaging, daily-life questions | Primary default for automatic source-first renders | Generic optical-illusion slideshows, vague hooks, unsupported facts |
| `kr_maker_science_15_40` | KR | Viewers who respond to real object/process, 3D pen, build, engineering, experiment proof | Best when the source is owned/direct or generated as a visible process | Static image sequences pretending to be process footage |
| `global_visual_magic_teen_adult` | Global | Non-verbal entertainment viewers who expect a visual trick in 7-15s | Ambition reference only; useful for Grok/local VFX prompt direction | Treating public-domain stills as equivalent to staged trick videos |
| `global_physical_demo_15_45` | Global | Curiosity/science viewers who want a real experiment or toy demonstration | Secondary default when a strong moving source is available | Overproduced narration without visible proof |

## Reference Matrix

### Korea

| Preset candidate | Reference videos | Target | First-second hook | Source type | Layout/caption grammar | Edit grammar | Replication verdict |
|---|---|---|---|---|---|---|---|
| `kr_fast_entertainment` | 김프로KIMPRO: [`Real or Fake`](https://www.youtube.com/shorts/lvhZbN3hePE) 19s, [`Funny door sound`](https://www.youtube.com/shorts/HJQu5JAj_JE) 15s | broad global/KR comedy | Human action or prop gag starts immediately | Actors, props, staged room, meme sound | Usually sparse or no explanatory captions; the action carries the video | 1-2s setup, immediate gag, repeat/escalate, fast payoff | Not default. Current pipeline lacks actors/props and should not fake this with stock clips. |
| `kr_maker_process` | 사나고: [`세상에서 제일 작은 요시 팝콘통`](https://www.youtube.com/shorts/pdDSjlhxpxg) 55s, [`진짜 이끼로 만든 잠만보`](https://www.youtube.com/shorts/8BDYu4o-SgQ) 47s | KR maker/process + global craft | Object state or hand process visible immediately | Direct process footage, hands, materials, object transformation | Captions support step/object, not full-screen explanation | Process progression: raw material -> build -> reveal | Strong target when source is owned/generated as process video. |
| `kr_maker_science` | 긱블: [`커피는 몸에 안 좋을까?`](https://www.youtube.com/shorts/F-bCF31t39U) 41s, [`퍼시픽림 실사판`](https://www.youtube.com/shorts/OGtEoCkYtC4) 58s | KR science/engineering casual viewers | Object, experiment, or absurd question in first frame | Real experiment/build/interview/event clip | Question/hook text can appear top; proof captions stay compact | Alternates host/object proof, quick explanation, reveal | Good target, but needs stronger real moving source than current public-domain illusion fixtures. |
| `kr_curiosity_explainer` | 사물궁이: [`햇빛에 노출된 페트병 생수`](https://www.youtube.com/shorts/mPWwMqDEiMo) 71s, [`눈알 스티커 붙인 트럭`](https://www.youtube.com/shorts/GgeZ8P3Ev7o) 76s | KR daily-life curiosity, 20-40 | Clear question title or visually odd object | Evidence cards, source notes, screen captures, simple graphics, and motion/generated footage | Top question + lower evidence fact; captions are readable but not giant | Hook question -> mechanism -> implication/answer | Primary default, but only when generic still images remain support cards and the main proof comes from motion, generated footage, or source captures. |
| `kr_micro_fact` | 1분만: [`일본 과자 포장의 비밀`](https://www.youtube.com/shorts/2CPpLbPAk8g) 28s, [`심각한 요즘 시장 바가지`](https://www.youtube.com/shorts/wQr9Lx_Mn8g) | KR quick-fact feed viewers | Direct claim or surprising object | Object/product/news image, quick narration | Bigger title-like captions accepted, but only if source remains visible | One idea, fast narration, punchy answer | Good for 20-30s facts; high risk of becoming text-card slideshow if sources are weak. |
| `kr_science_story` | 과학드림: [`캔맥 vs 병맥`](https://www.youtube.com/shorts/65anzKAFjGM) 43s, [`조개가 물고기를 닮은 이유`](https://www.youtube.com/shorts/2S4Xs-p7o8c) | KR science story viewers | Question/comparison anchored to a concrete object | Scientific example, nature/object footage, simple diagram | Explanation captions can be denser than comedy, but need source proof | Question -> evidence -> mechanism -> answer | Good for source-first explainers when citations and object footage exist. |
| `kr_longform_clip_bridge` | 언더스탠딩: [`스페이스X의 스타쉽 프로젝트`](https://www.youtube.com/shorts/PFvE-bPyZlQ), [`스페이스X 폭탄은 일론 머스크`](https://www.youtube.com/shorts/5YwR2Lt0Dw8) | KR long-form knowledge viewers | Quote/topic claim up front | Interview/audio clip, charts, B-roll | Chapter/quote captions, restrained lower facts | Clip hook -> context -> long-form bridge | Useful only when source audio/video rights are clear. |

### Global

| Preset candidate | Reference videos | Target | First-second hook | Source type | Layout/caption grammar | Edit grammar | Replication verdict |
|---|---|---|---|---|---|---|---|
| `global_visual_magic` | Zach King: [`The floating tree illusion`](https://www.youtube.com/shorts/tOIFZ8O6Ezk) 11s, [`Can you fly with a leaf blower?`](https://www.youtube.com/shorts/bJ1M8z-u-30) 13s | non-verbal global entertainment | Impossible visual state visible immediately | Actor, prop, locked camera, practical/VFX trick | Minimal captions; visual trick is the hook and payoff | Setup -> impossible moment -> reveal/reset | Ambition reference only. Do not score static illusion slides against this bar. |
| `global_physical_demo` | Mark Rober: [`Magnus Effect`](https://www.youtube.com/shorts/L0R-Ac1XRyk) 32s, [`Skyscraper From Falling Over`](https://www.youtube.com/shorts/3Y7o9IgliYk) 41s | global curiosity/science | Strong object demo or named experiment | Real experiment, engineered object, demonstration | Captions are proof labels and emphasis, not paragraphs | Object hook -> test -> slow/replay/explanation -> answer | Strong secondary target when real moving experiment source is available. |
| `global_toy_optical_demo` | Grand Illusions: [`Crushmetric Pen`](https://www.youtube.com/shorts/egS9iv1Vj0s) 59s, [`Heart Metamorphosis`](https://www.youtube.com/shorts/kQIWCcji03k) 53s | toy/illusion collectors, casual curiosity | Object shown close-up immediately | Hands + optical/mechanical object | Very sparse text; object stays centered and inspectable | Hold object, manipulate, repeat reveal angle | Most realistic global illusion target if the asset is a moving object demo, not a static old illustration. |
| `global_experiment_proof` | The Action Lab: [`Feather and cube fall`](https://www.youtube.com/shorts/-bThN0otPMI) 26s, [`Liquid nitrogen under water`](https://www.youtube.com/shorts/2w_uiLdmIXA) 59s | experiment/science viewers | Experiment state or outcome visible fast | Real lab/demo footage | Short proof captions; object and reaction dominate | Setup -> event -> replay/close-up -> explanation | Good source-first target, but only with rights-safe demo footage. |

## Style Breakdowns

### `kr_curiosity_explainer`

- Audience: `kr_casual_curiosity_20_40`.
- Active quality reference:
  `docs/QA/2026-06-18-kr-curiosity-bottled-water-quality-reference.md`.
  Any V3+ bottled-water candidate must compare against the V2 layout-polish
  baseline in that file before claiming visible quality improvement.
- Best templates: `news_explainer`, `myth_buster`, `tutorial_steps`,
  `hot_take` when the topic is fact/object-first.
- Layout:
  - Scene 1: top question/hook, `layoutVariantKey=headline-evidence`,
    `captionPreset=top-hook`.
  - Body: lower evidence facts, `layoutVariantKey=chapter-evidence` or
    `hands-proof`, `captionPreset=lower-info`.
  - Final: answer/implication chip, not a generic comment CTA.
- Captions:
  - Korean, max two lines, 8-14 chars per line for hook, 12-18 for lower facts.
  - Use concrete nouns/numbers: object, price, date, mechanism, source term.
  - Never burn production notes, "reference", "layout", or "safe zone" into the
    video.
- Edit rhythm:
  - First 1.0s: show the odd object/question.
  - 1-4s: name the problem.
  - 4-12s: prove mechanism with moving source, diagram, or screen capture.
  - Last beat: answer or "why it matters"; no empty "comment below" ending.
- Source requirement:
  - A real object, screen capture, data card, map, product, experiment, or
    sourced evidence card/video must be visible in every scene.
  - Generic web still images may support a claim, but they cannot be the main
    visual source for non-meme explainers.
  - If the scene is an object/process claim, use moving footage, a generated
    simulation, Grok/Gemini/local MP4, or source capture rather than treating a
    single still as proof.
  - Static public-domain illusion art is only acceptable if the whole format is
    explicitly an optical-demo analysis, not a general upload candidate.

#### Bottled-water V2/V3 quality addendum

- V2 layout polish is the current baseline, not an accepted "good" sample:
  `storage/final-videos/kr-curiosity-bottled-water-v2-20260618/kr-curiosity-bottled-water-v2-20260618.mp4`
  (`sha256=8E8FC4790F18C7615F2BD3E3B9F490A0B517C250D7CE891E74AC970FD327EFBB`).
- Visual unity does not have to mean HUD. Frame lines, HUD marks, and common
  mattes are only optional post-edit treatments. The preferred V3 quality
  ratchet is source-level continuity: same bottle identity, same hand scale,
  same camera distance, same daylight logic, and scene-to-scene physical action.
- A future candidate that only changes border/HUD/color treatment without
  improving source continuity is polish-only and must not be called a visible
  quality improvement.
- Use the active quality reference above as the comparison checklist for
  baseline contact sheet review, first-second hook, subject protection,
  platform safe-zone, source artifacts, one-package feel, and proof trail.

### `kr_maker_process`

- Audience: `kr_maker_science_15_40`.
- Best templates: `authentic_vlog`, `tutorial_steps`, `before_after`,
  `live_recap` when the source is process footage.
- Layout:
  - Scene 1: object/process already underway, `layoutVariantKey=routine-top-hook`.
  - Body: step/object chips, `layoutVariantKey=hands-proof` or
    `routine-lower-info`.
  - Final: completed object/reveal, `layoutVariantKey=grok-first-proof` if the
    source is generated or `hands-proof` if direct footage.
- Captions:
  - Sparse labels. The hand/object state must remain readable.
  - Avoid full-screen title cards unless used as a short chapter reset.
- Edit rhythm:
  - Start on motion, then cut by process state, not arbitrary duration.
  - Include one close-up proof beat and one final reveal.
- Source requirement:
  - Hands, material, tool, object state, or generated process continuity.
  - Reject slideshows that only describe a build without showing the build.

### `global_visual_magic`

- Audience: `global_visual_magic_teen_adult`.
- Best templates: `persona_story`, `authentic_vlog`, custom Grok-first packets.
- Layout:
  - Minimal captions or none. If used, `layoutVariantKey=grok-first-hook`.
  - Center action must not be covered.
- Edit rhythm:
  - 7-15s total.
  - Setup and impossible moment must be visible without narration.
  - Hidden cut/VFX/prop continuity is the quality bar.
- Source requirement:
  - Actor, prop, location, camera lock, and a real trick/reveal plan.
  - Current automated public-source pipeline cannot honestly meet this bar by
    cropping old images or GIF loops.

### `global_physical_demo`

- Audience: `global_physical_demo_15_45`.
- Best templates: `myth_buster`, `tutorial_steps`, `vs_comparison`.
- Layout:
  - Scene 1: object question, `layoutVariantKey=headline-evidence`.
  - Body: object proof labels, `layoutVariantKey=hands-proof`.
  - Replay/answer: `layoutVariantKey=grok-first-proof` or `chapter-evidence`.
- Captions:
  - Short proof labels, not long narration blocks.
  - Use slow/replay text only when the source actually shows a replay/close-up.
- Source requirement:
  - Real experiment footage, generated simulation that looks like a demo, or
    rights-safe lab/object footage.

### `global_toy_optical_demo`

- Audience: toy, illusion, and casual object-curiosity viewers.
- Best templates: `myth_buster`, `origin_story`, `tutorial_steps`.
- Layout:
  - Object centered, `layoutVariantKey=object-mystery` or `hands-proof`.
  - Captions stay away from the object and right-side platform UI.
- Edit rhythm:
  - Hold long enough to inspect the object.
  - Manipulate or rotate once, then repeat from another angle.
- Source requirement:
  - Moving object demonstration. A still image may support explanation but
    cannot be the whole video.

## Code Preset Contract

The executable version of this packet lives in
`worker/render/reference_style_presets.py`.

Each preset exposes:

- `key`
- `label`
- `region`
- `targetAudience`
- `referenceVideos`
- `templateTypes`
- `subtitleStyle`
- `captionPreset`
- `layoutVariantSequence`
- `sceneDurationSec`
- `editGrammar`
- `captionRules`
- `sourceRequirements`
- `goldSampleEvidence`

The helper `apply_reference_style_preset(manifest, preset_key)` returns a copied
manifest with:

- top-level `referenceStylePreset`
- top-level `referenceStyleSummary`
- top-level `subtitleStyle` when unset
- per-scene `captionPreset`
- per-scene `layoutVariantKey`
- per-scene `referenceEditRole`
- per-scene `referenceTimingSec`
- per-scene `referenceSourceRequirement`

This keeps the first implementation safe: it does not change the default render
path until a caller opts into a preset. Future integration should apply the
preset during preproduction or manifest save, then run a real render and phone
review before claiming visible quality improvement.

## Gold Sample Gate

A future candidate is not a gold sample unless all four layers exist:

1. Reference row:
   - Region and target audience are named.
   - At least two concrete reference URLs are linked.
   - Replication limits are recorded.
2. Style breakdown:
   - Layout, caption, edit rhythm, source requirement, audio policy, and payoff
     are specified.
   - The chosen reference family is realistic for the available source pipeline.
3. Code application:
   - Manifest has `referenceStylePreset`.
   - Scenes have `captionPreset`, `layoutVariantKey`, and reference edit roles.
   - The render-quality report or preproduction ledger points to the preset.
4. Human-visible proof:
   - Actual MP4 path and SHA-256.
   - Contact sheet or phone-sized screenshot.
   - If a topic-specific QA reference exists, side-by-side comparison against
     that baseline.
   - First-second hook pass.
   - Source/object proof pass.
   - `stillImageSourcePolicy` pass: generic web stills are support cards only,
     not the main source for non-meme explainers.
   - Caption safe-zone and subject-occlusion pass.
   - Audio/BGM/voice review pass when applicable.

If any layer is missing, the candidate can be "reference-coded" or
"render-proofed", but not "gold sample accepted".

## Immediate Recommendation

Use `kr_curiosity_explainer` as the next baseline for the Korean-first channel.
It is the closest match to the current source-first pipeline because it can use
object footage, sourced images, screen captures, simple diagrams, and Korean
TTS without requiring actors, props, or VFX. Treat sourced still images as
support/evidence cards unless the topic is explicitly a meme, reaction image,
screenshot/source capture, or data-card analysis.

Use `kr_maker_process` only when a moving process source is available. Use
`global_visual_magic` only as an ambition bar for Grok/local generated video,
not as the bar for public-domain still-image renders.
