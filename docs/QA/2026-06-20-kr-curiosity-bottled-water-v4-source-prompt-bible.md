# KR Curiosity Bottled Water V4 Source Prompt Bible

Date: 2026-06-20
Task: `VIDEO-STUDIO-KR-CURIOSITY-V4-SOURCE-BIBLE-20260620-01`
Packet: `storage/approval-packets/kr-curiosity-bottled-water-20260616/production-approval-packet.json`
Quality reference: `docs/QA/2026-06-18-kr-curiosity-bottled-water-quality-reference.md`
Structured bible: `storage/approval-packets/kr-curiosity-bottled-water-20260616/v4-source-prompt-bible.json`
Prompt bundle: `storage/grok-handoffs/kr-curiosity-bottled-water-v4-source-bible-20260620/prompts/`
Source selection gate: `storage/approval-packets/kr-curiosity-bottled-water-20260616/v4-source-selection-gate.json`
Selected source contact sheet: `storage/approval-packets/kr-curiosity-bottled-water-20260616/source-contact-sheet.jpg`
Final render: `storage/final-videos/kr-curiosity-bottled-water-v4-source-unity-20260620/kr-curiosity-bottled-water-v4-source-unity-20260620.mp4`
Status: source bible complete; V4 sources generated/imported; V4 source-unity render complete

## Gate Basis

This bible was created after reading the prior QA reference sections
`Source Prompt Web References (2026-06-19)` and `V4 Source Prompt Bible Gate`.
The required production order is:

1. Build this source prompt bible and take matrix.
2. Generate at least two takes per scene in Grok/Gemini.
3. Reject source clips that break object, hand, light, camera, action, crop, or
   audio continuity.
4. Build a source contact sheet from accepted takes.
5. Only after source-level continuity passes, import selected sources and
   render with Video Studio post-edit treatment.

Post-edit HUD, frame, matte, and color grade are secondary. They cannot rescue
source clips that look like separate videos.

## Global Source Continuity

`globalSourceContinuity`: one everyday phone-shot world, not five product ads.
All source clips must look like the same person filmed one clear bottle around
one parked car on one hot summer day.

- Format: raw source footage for editing, vertical 9:16 MP4, 6-8 seconds,
  continuous single shot, no internal cuts.
- Bottle identity: same unlabeled clear 500 ml PET water bottle, light-blue cap,
  65 percent water fill, shallow vertical ridges, circular four-foot base, fine
  condensation beads, no brand label, no fake printed text.
- Hand identity: same adult right hand, light warm skin tone, short clean nails,
  beige cotton sleeve visible in action scenes. No random second person.
- Location logic: sunlit concrete driveway beside a parked compact car, then
  passenger-seat/window heat context, then shaded area with the same beige
  tote/cooler bag.
- Lighting: warm noon daylight from upper right, hard sun on the bottle, soft
  car-window reflections, same contrast and color temperature across clips.
- Camera personality: handheld phone, 26 mm equivalent feel, close object-first
  framing, slight 1-2 cm natural sway, no drone, no tripod product turntable,
  no cinematic stock montage.
- Color texture: restrained warm daylight, realistic phone sharpness, light
  sensor noise acceptable, no glossy commercial grade, no AI plastic glow.
- Audio source: natural ambient bed only if the model emits audio. No model
  dialogue, no built-in narration, no music baked into source clips.

## Reference Ingredients

If Grok/Gemini supports reference images or frame continuation, use this order:

1. Generate scene 001 takes from text lock.
2. Pick the best scene 001 take, export its last frame as the scene 002
   reference.
3. For each following scene, use the previous accepted take's last frame or a
   selected first/last bridge still as an ingredient.
4. If the surface does not accept reference images, paste the full object bible
   at the top of every prompt and reject harder during contact-sheet review.

The reference stills should show: bottle silhouette, light-blue cap, no label,
water level, condensation texture, right-hand scale, beige sleeve, concrete/car
environment, and warm daylight direction.

## Action Continuity Chain

| Scene | Role | First frame should read as | Action progression | Last frame bridge |
|---|---|---|---|---|
| 001 | hook question | same bottle standing on sunlit concrete | right hand enters, taps or steadies hot bottle; sunlight is the question | hand starts to lift or rotate bottle |
| 002 | mechanism | same hand holding same bottle beside car window | bottle turns in hand; cap, water line, and warm glare stay visible | bottle is near car glass, ready for squeeze/check |
| 003 | evidence | same bottle in both hands, close to camera | gentle squeeze shows subtle PET flex and water slosh | bottle remains in hand, car interior/shade edge visible |
| 004 | implication | same bottle set on passenger seat or dashboard | hand places or withdraws, leaving bottle in harsh car sun | hand reaches back toward bottle |
| 005 | answer | same hand retrieves same bottle from sun/car | hand moves bottle into shade beside beige tote/cooler | bottle rests in shade, cap and water line visible |

Every accepted clip must add a visible physical state change. Static beauty
shots fail even if they are pretty.

## Take Matrix

| Scene | Take | Provider target | Prompt file | Primary intent | Select only if | Reject if |
|---|---|---|---|---|---|---|
| 001 | 1 | Grok first, Gemini fallback | `scene-001.take-1.prompt.txt` | strongest hook: hot bottle on concrete with hand touch by 1s | bottle/cap/water level match bible; heat cue visible before captions | static product shot; cap missing; label appears; no hand/action |
| 001 | 2 | Gemini/Grok alternate | `scene-001.take-2.prompt.txt` | stronger lift bridge into scene 002 | hand begins lift/turn without covering bottle | bottle becomes glass/metal; extra bottle; background changes to studio |
| 002 | 1 | Grok first | `scene-002.take-1.prompt.txt` | hand turns same bottle near car window | car-window heat context and same hand are obvious | green cap, different bottle, person drinking, warning-card look |
| 002 | 2 | Gemini/Grok alternate | `scene-002.take-2.prompt.txt` | closer cap/water-line mechanism | cap and water line stay readable, lower frame is caption-safe | macro loses location; hand warps; bottle fills/empties |
| 003 | 1 | Grok first | `scene-003.take-1.prompt.txt` | subtle squeeze/flex evidence | PET flex is realistic, not melted or alarming | cartoon melting, lab diagram, red danger graphics, hand artifacts |
| 003 | 2 | Gemini/Grok alternate | `scene-003.take-2.prompt.txt` | water movement/slosh evidence | water motion visible and bottle remains same identity | bottle shape changes; water becomes cloudy; impossible deformation |
| 004 | 1 | Grok first | `scene-004.take-1.prompt.txt` | parked-car heat implication | same bottle on seat/dashboard, car sun reads clearly | generic car interior without bottle; driver drinks; text overlay |
| 004 | 2 | Gemini/Grok alternate | `scene-004.take-2.prompt.txt` | hand places same bottle in car sun | hand placement action starts by 1s, last frame reaches for bottle | scene becomes a new car/world; bottle scale changes |
| 005 | 1 | Grok first | `scene-005.take-1.prompt.txt` | resolution: move bottle into shade | hand movement and shade placement are clear | end card, subscribe prompt, empty background, new bottle |
| 005 | 2 | Gemini/Grok alternate | `scene-005.take-2.prompt.txt` | stronger cooler/tote final placement | same bottle rests in shade with cap/water line visible | bag dominates; bottle disappears; action starts too late |

## Copy-Paste Generation Prompts

Use these exactly as source generation prompts. Do not ask the model to add
captions, subtitles, graphics, voiceover, or music.

### Scene 001 Take 1

```text
Raw source footage for editing, not a finished social video. Vertical 9:16 MP4, 6-8 seconds, one continuous handheld phone shot. Preserve the same source world for a Korean everyday science short: one unlabeled clear 500 ml PET water bottle with a light-blue cap, 65 percent water fill, shallow vertical ridges, circular four-foot base, fine condensation beads, no brand label, no printed text; one adult right hand with light warm skin tone, short clean nails, beige cotton sleeve; warm noon daylight from upper right; sunlit concrete driveway beside a parked compact car; restrained phone-camera color, not a glossy product ad.

Scene role: hook question. The bottle is standing on hot sunlit concrete. In the first second, the right hand enters frame and lightly taps or steadies the bottle so the viewer immediately asks whether it is safe to drink. Subtle heat shimmer or harsh sun shadow is visible on the concrete. Camera is close, object-first, 26 mm phone feel, slight natural handheld push-in. Keep the bottle body, cap, water line, and ground heat cue visible with negative space near the upper-left and lower-middle for later Korean captions.

Source audio intent: natural outdoor room tone only if audio is generated; no speech, no narration, no music.

Negative constraints: no captions, no subtitles, no logos, no watermark, no UI, no title cards, no fake brand label, no extra bottles, no people posing, no drinking, no diagram, no warning sign, no studio/product turntable, no bottle material change, no cap color change, no warped hand.

Review target: first second must show the physical question before text is added; reject if it looks like a separate stock/product clip.
```

### Scene 001 Take 2

```text
Raw source footage for editing, not a finished social video. Vertical 9:16 MP4, 6-8 seconds, one continuous handheld phone shot. Same continuity bible as every scene: unlabeled clear 500 ml PET water bottle, light-blue cap, 65 percent water fill, shallow vertical ridges, circular four-foot base, condensation beads, same adult right hand with beige sleeve, warm noon sunlight from upper right, same concrete driveway beside parked compact car, restrained phone-camera color.

Scene role: hook question with bridge into the next shot. Start on the same bottle upright in direct sun. In the first second, the right hand reaches in from the lower-right, touches the cap and upper bottle, then begins a small lift or quarter-turn by the end of the clip. The motion should clearly connect to a later shot near a car window. Camera stays close and handheld, with a small push-in and no internal cuts. Keep cap, bottle silhouette, water line, and hand scale readable.

Source audio intent: quiet outdoor ambience only; no generated dialogue, no music.

Negative constraints: no burned-in text, no fake logo, no extra bottle, no glass bottle, no green cap, no studio background, no diagram, no medical symbol, no warped fingers, no dramatic melting.

Review target: accept only if the final frame can plausibly become scene 002, with the same bottle and hand.
```

### Scene 002 Take 1

```text
Raw source footage for editing, not a finished social video. Vertical 9:16 MP4, 6-8 seconds, one continuous handheld phone shot. Continue the exact same source world: unlabeled clear 500 ml PET bottle, light-blue cap, 65 percent water fill, shallow ridges, four-foot base, condensation beads, same adult right hand with beige sleeve, warm noon sunlight from upper right, same parked compact car beside the concrete driveway.

Scene role: mechanism. The same right hand holds and slowly turns the same warm bottle beside a sunlit passenger-side car window. In the first second the hand is already moving, rotating the bottle so the cap, water line, and bottle surface catch warm window glare. The car glass edge and dashboard/seat context should be visible enough to explain heat without becoming a separate car-ad shot. Camera is vertical macro close-up, handheld, slight sway, object-first framing. Leave lower-middle and right edge caption-safe without hiding the hand.

Source audio intent: faint car/interior room tone or outdoor ambience only; no dialogue, no narration, no music.

Negative constraints: no person drinking, no warning card, no text overlay, no health icon, no chart, no doctor, no fake label, no green cap, no different bottle shape, no random office/kitchen background, no warped hand.

Review target: the viewer should understand that time/heat exposure matters from the bottle turn and car-window heat cue.
```

### Scene 002 Take 2

```text
Raw source footage for editing, not a finished social video. Vertical 9:16 MP4, 6-8 seconds, one continuous handheld phone shot. Keep the same bottle, cap, water level, hand, beige sleeve, car, concrete, warm daylight, and phone-camera look from scene 001.

Scene role: mechanism close detail. Begin with the same hand holding the same bottle near the car window, cap and water line filling the center-left of frame. In the first second the thumb rolls the bottle slightly and the water line shifts a little. The sunlight through glass creates a warm highlight on the PET surface, but the bottle remains realistic and inspectable. Camera does a tiny handheld push toward the cap and water line, then settles. Keep the bottle body and hand out of the later caption zone.

Source audio intent: quiet ambient car/window sound only; no generated speech or music.

Negative constraints: no captions, no UI, no readable labels, no fake logo, no extra hands, no bottle becoming glass, no cap color shift, no lab/medical visual, no exaggerated steam, no impossible water level jump.

Review target: select only if the cap and water line match scene 001 and the location still reads as the same car/sun world.
```

### Scene 003 Take 1

```text
Raw source footage for editing, not a finished social video. Vertical 9:16 MP4, 6-8 seconds, one continuous handheld phone shot. Continue the same source world: same unlabeled clear 500 ml PET bottle with light-blue cap, 65 percent water fill, ridged body, four-foot base, condensation beads, same adult right hand and beige sleeve, same parked car and warm noon daylight from upper right.

Scene role: evidence. Both hands gently press the same warm plastic bottle close to the camera, showing a subtle realistic PET flex and small water movement. In the first second the pressure begins; by the middle of the clip the bottle flex is visible, but it never melts or collapses. The background can be the same car-window/seat area with warm daylight, softly out of focus. Camera stays locked close on hands and bottle with slight handheld breathing. Keep the water line, cap, and flex area visible, with safe negative space for lower captions.

Source audio intent: soft hand-on-plastic creak or neutral ambience only if generated; no speech, no narration, no music.

Negative constraints: no melting cartoon, no red danger graphic, no lab diagram, no flames, no plastic trash pile, no text overlay, no fake label, no distorted fingers, no extra bottle, no new hand identity.

Review target: accept only if the flex looks physically plausible and the bottle is still the same object from scenes 001-002.
```

### Scene 003 Take 2

```text
Raw source footage for editing, not a finished social video. Vertical 9:16 MP4, 6-8 seconds, one continuous handheld phone shot. Preserve continuity exactly: unlabeled clear PET bottle, light-blue cap, 65 percent water fill, ridged body, circular four-foot base, condensation beads, same right hand and beige sleeve, same car-window daylight world, warm restrained phone-camera grade.

Scene role: evidence with water movement. Start with the same hand holding the bottle upright near the car window. In the first second the fingers gently squeeze the lower middle of the bottle, causing a small realistic water slosh and a mild dent in the PET. The camera is close enough to read texture but wide enough to see both hands and the cap. End with the bottle still upright and inspectable, ready to be placed in the car in scene 004.

Source audio intent: quiet plastic-handling ambience only; no dialogue or music.

Negative constraints: no cloudy water, no large deformation, no missing cap, no cap color shift, no text or logo, no warning label, no microscope/lab, no medical characters, no surreal reflections, no warped thumbs.

Review target: select if water movement is readable without making the clip alarmist or visually fake.
```

### Scene 004 Take 1

```text
Raw source footage for editing, not a finished social video. Vertical 9:16 MP4, 6-8 seconds, one continuous handheld phone shot. Same source world: the exact same unlabeled clear 500 ml PET bottle, light-blue cap, 65 percent water fill, ridged body, four-foot base, condensation beads, same beige-sleeved adult right hand, same parked compact car, same warm noon sunlight from upper right.

Scene role: implication. The same bottle sits on the passenger seat or lower dashboard in harsh sunlight coming through the car window. In the first second the camera already shows the bottle in the car sun; then the hand briefly enters to steady or adjust it and withdraws, making the hot closed-car context obvious. Camera angle is from the passenger seat, vertical handheld, close but with enough car interior to read the location. Keep bottle, sunlight patch, and seat/dashboard context visible for later captions.

Source audio intent: muffled car interior ambience only; no speech, no narration, no music.

Negative constraints: no person drinking, no driver close-up, no generic car without bottle, no text card, no warning sign, no chart, no medical symbol, no fake logo, no extra bottle, no change to cap or bottle shape.

Review target: accept only if this feels like the same bottle after scene 003, now left in a hot car.
```

### Scene 004 Take 2

```text
Raw source footage for editing, not a finished social video. Vertical 9:16 MP4, 6-8 seconds, one continuous handheld phone shot. Lock continuity to the same bottle, hand, beige sleeve, car interior, warm noon light, restrained phone-camera look, and no-label light-blue-cap object identity from scenes 001-003.

Scene role: implication with placement action. In the first second, the same right hand places the same bottle onto the passenger seat where direct sunlight falls through the window. The hand releases the bottle, sunlight flashes on the cap and water line, and the camera makes a small handheld tilt to include the window glare. End with the hand reaching back toward the bottle, creating a bridge to the shade move in scene 005. Leave caption-safe space without covering the bottle.

Source audio intent: quiet car interior ambience only; no generated speech or music.

Negative constraints: no caption text, no UI, no dashboard warning display, no person drinking, no new car/location, no bottle scale change, no cap disappearing, no label appearing, no artificial danger overlay.

Review target: select if the hand placement starts immediately and the last frame can bridge into retrieval.
```

### Scene 005 Take 1

```text
Raw source footage for editing, not a finished social video. Vertical 9:16 MP4, 6-8 seconds, one continuous handheld phone shot. Continue the same source world and object identity: unlabeled clear 500 ml PET bottle, light-blue cap, 65 percent water fill, ridged body, four-foot base, condensation beads, same adult right hand with beige sleeve, same parked car beside concrete driveway, same warm daylight.

Scene role: answer/resolution. In the first second the same right hand picks up the same bottle from the sunlit car/driveway area and moves it into shade beside the same beige tote or cooler bag. The action should be concrete: sunlight to shade, final placement visible, cap and water line still readable. Camera follows the hand with a gentle close handheld move, then settles on the bottle resting in shade. Keep lower-middle caption space clear without hiding the hand or bottle.

Source audio intent: soft outdoor ambience and hand movement only if audio is generated; no dialogue, no narration, no music.

Negative constraints: no subscribe/end card, no call-to-action graphics, no caption text, no new bottle, no empty background, no product ad, no cooler brand logo, no random person, no medical warning.

Review target: accept only if the physical answer is visible without relying on captions: move the same bottle out of heat.
```

### Scene 005 Take 2

```text
Raw source footage for editing, not a finished social video. Vertical 9:16 MP4, 6-8 seconds, one continuous handheld phone shot. Preserve exact continuity from prior scenes: same unlabeled clear PET bottle, light-blue cap, 65 percent water fill, condensation beads, same right hand and beige sleeve, same compact car and concrete driveway, same warm noon daylight and phone-camera texture.

Scene role: answer/resolution with final shade proof. Start with the same bottle partly in sun at the edge of the car doorway. In the first second the hand grips the cap/neck and carries the bottle into shade next to a beige tote/cooler bag. End on a clean final placement in shade: bottle upright or gently laid down, cap, water line, and no-label identity visible. The motion is calm and practical, not a commercial hero shot.

Source audio intent: quiet outdoor shade ambience only; no generated speech or music.

Negative constraints: no text, no logo, no end screen, no second bottle, no person drinking, no new hand, no cap color shift, no bag dominating the frame, no blurry bottle disappearance, no artificial HUD.

Review target: choose this take only if it reads as the same hand making the practical answer: keep a new bottle in shade and avoid the long-heated one.
```

## TTS Script Plan

Voice: `ko-KR-SunHiNeural` or equivalent calm Korean female voice. Pace should be
slower than generic AI-host narration. TTS adds context beyond captions and must
not read the captions verbatim.

| Scene | Final duration target | TTS line |
|---|---:|---|
| 001 | 2.8s | `햇빛에 오래 둔 생수, 그냥 마셔도 될까요?` |
| 002 | 4.2s | `마신 양보다, 뜨거운 곳에 얼마나 있었는지가 더 중요합니다.` |
| 003 | 4.4s | `열이 오래 닿으면 병이 말랑해지고, 물과 닿는 조건도 달라져요.` |
| 004 | 4.2s | `특히 차 안처럼 갇힌 공간에 오래 있었다면 그냥 마시지 않는 쪽이 낫습니다.` |
| 005 | 3.4s | `짧게 데운 새 병은 그늘로 옮기고, 오래 뜨거웠던 병은 피하세요.` |

TTS reject rules:

- Reject over-friendly host phrases such as `여러분`, `궁금하시죠`, `끝까지 보세요`.
- Reject report prose and internal words such as `해당`, `필수`, `금지`, `소스`,
  `장면`, `레이아웃`.
- Reject a read that outruns the visible hand/bottle action.

## BGM And Ambience Intent

- BGM: restrained warm curiosity bed, light pulse or soft marimba/wood tone,
  no dramatic alarm, no comedy sting.
- Target mix: BGM low under narration, ducked around TTS, never louder than the
  hand/bottle ambience impression.
- Source ambience: outdoor concrete sun tone for scene 001, muffled car/window
  tone for scenes 002-004, softer shade/outdoor tone for scene 005.
- If model-native source audio contains voices, music, noisy artifacts, or
  inconsistent ambience, strip it and use Video Studio ambience/BGM only.
- Audio continuity pass condition: the five scenes should feel like one calm
  phone-shot observation, not five separately generated sound worlds.

## Subtitle And Layout Plan

No subtitles or text may be burned into Grok/Gemini source clips. Video Studio
adds captions in post.

| Scene | Caption text | Placement | Layout guard |
|---|---|---|---|
| 001 | `햇빛 생수\N마셔도 될까?` | top-left hook chip, x about 92, y about 170 | never cover cap, bottle shoulder, or heat shadow |
| 002 | `마신 양보다\N뜨거웠던 시간` | lower-mid chip, y about 1180 | never cover hand, cap, water line, or window edge |
| 003 | `병이 말랑하면\N조건이 바뀐 신호` | lower-left/lower-mid chip, y about 1160 | never cover squeeze point, fingers, or water slosh |
| 004 | `차 안에 오래면\N그냥 피하기` | lower-mid chip, y about 1180 | never cover bottle on seat/dashboard or sun patch |
| 005 | `오래 데웠다면\N새 병을 그늘에` | lower-mid answer chip, y about 1160 | never cover moving hand, shade placement, cap, or tote edge |

Global subtitle guard:

- Stay inside the rendering safe zone from `docs/RENDERING-SPEC.md`.
- Avoid bottom 20 percent and right-edge platform UI risk.
- Korean lines max 16 chars per line, max 2 lines.
- Use one caption family; scene-to-scene variation comes from role and footage,
  not arbitrary sticker placement.

## Source Reject Rules

Reject a generated take immediately if any of these appear:

1. Bottle identity drifts: cap color changes, label appears, glass bottle,
   different base, water level jump, bottle disappears, extra bottle.
2. Hand identity drifts: new person, different sleeve, warped fingers, random
   second hand, hand scale no longer fits the bottle.
3. World drifts: studio/product set, kitchen, beach, office, lab, new car,
   different daylight direction, commercial ad lighting.
4. Action fails: first second is static, no visible physical question, no hand
   movement, no scene-to-scene bridge, or body scene repeats the prior action.
5. Source is contaminated: burned-in text, logos, watermark, UI, title card,
   model narration, music, warning graphics, medical icons, diagram-only shot.
6. Physics fails: impossible melt, floating bottle, water behaving like gel,
   cap vanishing, bottle deformation too extreme, camera jump cuts inside clip.
7. Crop fails: bottle, cap, hand, water line, car heat cue, or shade action would
   be covered by planned captions or platform UI.
8. Unity fails: clip only works after adding HUD/frame/color grade. If the raw
   source contact sheet looks like a separate video, reject.

## Source Acceptance Checklist

Completed from generated Grok outputs on 2026-06-20 before render import.

| Scene | Take candidates reviewed | Selected take | Object continuity | Action clarity | Camera/light continuity | Crop safety | Audio/ambience | Verdict |
|---|---:|---|---|---|---|---|---|---|
| 001 | 2 | take 2 | PASS: clear PET bottle, light-blue cap, no label | PASS: hand enters and establishes pickup/open chain | PASS: warm concrete/car daylight | PASS: bottle/cap remain readable | PASS after source audio strip/post ambience | PASS |
| 002 | 2 | take 1 | PASS: same cap, bottle, water line | PASS: twist/open action reads | PASS: car-window sunlight continuity | PASS: hand/cap not blocked | PASS after source audio strip/post ambience | PASS |
| 003 | 2 | take 1 | PASS with caveat: bottle slightly fatter but cap/hand survive | PASS: squeeze/slosh action reads | PASS: warm interior light continuity | PASS: squeeze point visible | PASS after source audio strip/post ambience | PASS |
| 004 | 2 | take 1 | PASS: same bottle/cap in hot car setup | PASS: car-heat proof beat reads | PASS: sun patch/car interior continuity | PASS: bottle and seat/window cue visible | PASS after source audio strip/post ambience | PASS |
| 005 | 2 | take 1 | PASS: blue cap, ridges, tote/shade placement survive | PASS: move bottle toward tote/shade by 3.5s | PASS: warm concrete/shade continuity | PASS: cap, bottle, hand, tote remain readable | PASS after source audio strip/post ambience | PASS |

Pass condition: all five selected takes preserve the same bottle, hand, light,
camera, color, and action chain when viewed as raw source stills, before any
post-edit frame/HUD/matte is applied.

Rejected take notes:

- Scene 001 take 1 was compositionally close, but too static at 1s.
- Scene 002 take 2 shifted the cap toward white and introduced a
  reflection/extra-bottle risk.
- Scene 003 take 2 cropped the cap and distorted the lower bottle shape.
- Scene 004 take 2 lost the lower ridged bottle identity and became too smooth.
- Scene 005 take 2 was not accepted: the copied download matched the old packet
  source hash, its inspected frame lost the blue cap/opened the bottle, and the
  Grok post still showed generation/download disabled.

## Next Operational Step

Source-level continuity passed for V4. The V4 source-unity render used only the
selected imported packet sources:

- `scene-001.selected.mp4`: scene 001 take 2
- `scene-002.selected.mp4`: scene 002 take 1
- `scene-003.selected.mp4`: scene 003 take 1
- `scene-004.selected.mp4`: scene 004 take 1
- `scene-005.selected.mp4`: scene 005 take 1

Render should keep the post-edit HUD/frame secondary: restrained warm frame,
lower caption chips, Korean TTS, low BGM/ambience, and no editor-like labels.

## V4 Render Result

Final output:
`storage/final-videos/kr-curiosity-bottled-water-v4-source-unity-20260620/kr-curiosity-bottled-water-v4-source-unity-20260620.mp4`

Render review:
`storage/final-videos/kr-curiosity-bottled-water-v4-source-unity-20260620/render-review.md`

Verification:

- ffprobe PASS: 1080x1920, 30fps, H.264 video, AAC audio, duration 25.43s.
- Full decode PASS: ffmpeg completed with no decode errors.
- Audio level PASS: mean -19.2 dB, max -4.4 dB.
- Final contact sheet PASS:
  `storage/final-videos/kr-curiosity-bottled-water-v4-source-unity-20260620/final-contact-sheet.jpg`
- SHA-256:
  `0554DAB72B873DDBA7B51D9A429B0D708437F016559BEE649B38B1261DD71805`

Residual caveat: scene 003 has a slightly fuller bottle body than scenes 001
and 002, but cap, hand, and action continuity are stronger than the rejected
take. Scene 005 caption briefly overlaps the lower bottle body; cap,
tote/shade placement, hand, and answer beat remain readable.
