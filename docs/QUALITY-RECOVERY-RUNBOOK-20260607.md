# Video Studio Quality Recovery Runbook

Status: active execution plan
Created: 2026-06-07
Scope: Video Studio AI Web Companion, Grok/Gemini browser handoffs, prompt compiler, source recovery, zero-paid voice, and publish-quality gates
Policy: zero-paid by default; no xAI/Gemini paid API calls; no DB/schema/dependency changes without explicit approval

## Purpose

This runbook exists because the previous loop kept producing artifacts without proving that the operator-visible video quality improved.

The next work must not optimize for "a file was generated." It must prove a repeatable path from browser handoff to source import, prompt quality, voice quality, render quality, and human-review evidence.

## Non-Negotiable Outcomes

- The operator must not edit `sceneId` or `take` query parameters for normal operation.
- Grok prompt fill/generate must target `grok.com/imagine`, never `grok.com/c/*` chat threads.
- Gemini web image support remains prompt-fill/probe only until a provider-specific live surface is verified.
- Browser automation must not open native Chrome download/save/export prompts.
- Prompt text must be short positive shot direction, not QA narration, rejection history, or negative-prompt dumps.
- The old Korean office worker shoulder-release runway is not a quality baseline.
- Voice is required for information/ranking/list formats unless a human explicitly approves a visual-led no-voice exception.
- Upload readiness must require source proof, voice/BGM review, first-second hook review, visual artifact review, phone-sized watch evidence, and publish packet evidence.

## Current Failure Inventory

| Failure | Code or workflow evidence | Required correction |
| --- | --- | --- |
| Manual scene/take URL edits | Scene-specific command URLs include `sceneId=...&take=...` and were handed to the operator during debugging. | Keep scene/take URLs as debug-only. Default operator path must be a fixed queue command URL. |
| General Grok chat routing | Runtime events showed `prompt-fill` against `https://grok.com/c/...`; Grok returned chat text instead of a video generation surface. | Companion background, popup, and content scripts must require `/imagine` before fill/generate. |
| Content-script receiving-end failures | `Could not establish connection. Receiving end does not exist.` can occur after extension reloads or tabs opened before content script injection. | Add automatic content-script injection/retry or make live reload/reopen proof mandatory before claiming stability. |
| Native download prompt risk | Earlier Grok download paths opened or risked Chrome native download UI. | Use direct-import/pageAssets/uploadEndpoint or operator-owned already-saved MP4 upload only. |
| Prompt meta leakage | Existing Grok prompts include production intent, caption rules, rejection history, and anti-slop language. | Compile short shot instructions and move QA criteria into review gates. |
| Weak repeated concept | The shoulder-tension/office scene is subtle, stale, and already failed visual QA. | Start a new reference-backed test packet with large first-second motion. |
| Voice quality gap | Prior renders had voice/TTS that felt slow or unnatural, but voice absence also made videos feel worse. | Keep voice, but verify zero-paid provider source and add voice naturalness as a blocking review field. |
| Existing pipeline underuse | Grok/Gemini/browser handoff, import history, and review-decision assets exist but were bypassed by ad-hoc generation. | Inventory and route through existing handoff manifests, importHistory, reviewDecisions, and render payloads before creating new paths. |
| Proxy-success gates | Final MP4/audit pass/direct-import proof were treated as stronger than actual upload quality. | Gate by source acceptance, visual quality, voice, phone watch, dashboard smoke, and publish packet evidence. |

## Compatibility Boundaries

- No DB schema changes.
- No `.env` edits.
- No dependency add/remove.
- No paid provider enablement.
- No change to existing Grok render/import contracts unless coordinated through `worker/bridge/routes_grok.py` tests.
- Episode browser-handoff routes are additive and must not weaken Grok handoff/render behavior.
- Gemini web image support must stay additive: prompt fill and event proof only.
- Gemini/Veo video automation remains planned-only until separately verified and explicitly approved.
- Runway/Veo/xAI official API adapters are paid or paid-risk paths and are out of scope for the zero-paid recovery loop unless the operator explicitly changes policy.

## Execution Gates

Each gate must leave evidence. If a gate fails, the next step is to fix that gate, not to keep generating more clips.

### Gate 0: Worktree And Ownership Inventory

Goal: avoid overwriting parallel Codex work.

Code/doc surfaces:
- `AGENT_TASK_BOARD.md`
- `tools/chrome-grok-companion/*`
- `worker/bridge/routes_grok.py`
- `worker/bridge/routes_episodes.py`
- `tests/test_grok_handoff.py`
- `tests/test_episode_pipeline.py`
- current `git diff --stat`

Pass evidence:
- Active locks and review rows are identified.
- Parallel-session-owned code files are not overwritten.
- The next code task lists exact scope files before editing.

Failure action:
- Stop code edits and reconcile with the parallel session handoff.

### Gate 1: Companion Stability

Goal: the browser handoff can reliably talk to the intended page in the existing signed-in Chrome profile.

Code surfaces:
- `tools/chrome-grok-companion/manifest.json`
- `tools/chrome-grok-companion/background.js`
- `tools/chrome-grok-companion/popup.js`
- `tools/chrome-grok-companion/content.js`
- `tools/chrome-grok-companion/content_gemini.js`
- `tests/test_grok_handoff.py`
- `tests/test_episode_pipeline.py`

Required behavior:
- Grok fill/generate targets only `https://grok.com/imagine`.
- `/c/*`, `/imagine/post`, and non-Imagine surfaces are rejected before input or click.
- Content-script receiving-end failure either auto-recovers through `chrome.scripting.executeScript` or fails with a clear reload/reopen action and no false success.
- Live events include build markers so stale extension code is visible.
- Gemini supports only `probe` and `fill-prompt`.

Pass evidence:
- `node --check` passes for all extension scripts.
- Focused companion pytest passes.
- A live event proves current build tag in the logged-in Chrome profile.
- No event shows prompt fill/generate against `grok.com/c/*`.

Failure action:
- If `Receiving end does not exist` persists, implement or finish automatic content-script injection/retry. This requires `"scripting"` permission in the manifest and `chrome.scripting.executeScript(...)` in popup/background messaging.

### Gate 2: Operator Command URL Default

Goal: the operator uses one stable queue command URL; scene/take-specific URLs are debug-only.

Code surfaces:
- `worker/bridge/routes_grok.py`
- `tools/chrome-grok-companion/popup.html`
- `tools/chrome-grok-companion/popup.js`
- `tools/chrome-grok-companion/README.md`
- `tests/test_grok_handoff.py`

Required behavior:
- The default command URL has no `sceneId` or `take`.
- The server chooses the next missing/rejected/recommended scene.
- The popup labels scene/take-specific URLs as debug, not the normal path.
- `Next scene` uses the queue state, not manual URL editing.

Pass evidence:
- Tests prove `/extension-command?operatorApproved=true` returns the current next scene.
- Tests prove `sceneId/take` still work only as explicit debug overrides.
- Operator guide exposes the queue URL first.

Failure action:
- Stop live generation and repair queue selection/labeling before continuing.

### Gate 3: Prompt Compiler Repair

Goal: Grok receives a shot instruction, not a production memo.

Code surfaces:
- `worker/bridge/routes_grok.py`
  - `_scene_prompt_seed`
  - `_scene_prompt`
  - `_scene_take_prompts`
  - `_scene_retry_prompt`
  - `_scene_prompt_quality`
- `worker/bridge/templates.py`
- `tests/test_grok_handoff.py`

Prompt standard:
- 1 to 3 sentences.
- Prefer 220 to 500 characters.
- Names the subject, place, visible first-second action, camera style, duration/aspect.
- Uses the canonical code ruleset from `worker/bridge/routes_grok.py`: `GROK_GENERATION_PROMPT_RULESET_VERSION`, `GROK_OBSERVABLE_MOTION_TERMS`, `GROK_ABSTRACT_OR_META_PROMPT_TERMS`, `GROK_PROMPT_REPAIR_HINTS`, and `_scene_prompt_quality`.
- Contains one large observable physical change in the first second. Subtle posture, mood, tension-release, vibe, or production intent is not enough.
- Requests one continuous 4-6s vertical phone MP4, one primary action, concrete camera behavior, and a subject/prop/location/palette continuity anchor.
- No `Rejected because`, no local review artifact text, no long negative prompt list, no "AI slop" phrasing, no caption/layout checklist prose.
- Shortform preproduction prompts must not inherit long-form/persona scaffolding such as `Long-form Korean story raw footage` or `Character bible excerpt`.
- Storyboard-first episode handoffs must pass `visual_action`/`visual_prompt` into Grok. Grok prompt seed selection must prefer that concrete action over the full `grok_prompt` wrapper so generated takes do not start from production scaffolding.
- Recommended Take selection must prefer Take 2 only when Take 2 has `promptQuality.status=ready`; otherwise choose a ready take and block generation if no ready take exists.
- Prompt text must not contain broken fragments such as `Setting: ... with;`, `Keep Keep`, `slight.`, or `same key;`.
- Minimal negative text only when needed: "no visible text or watermark."

Pass evidence:
- Tests assert prompt length caps.
- Tests assert banned meta phrases are absent.
- Tests assert action, subject, place, concrete camera, continuity anchor, one continuous shot, and observable first-second physical motion are present.
- Tests assert storyboard-first Grok handoffs use the visual action seed, preserve guardrail text under the prompt length cap, and do not recommend a `needs-rewrite` take for normal generation.
- Prompt QA returns `rulesetVersion`, `repairHints`, `observableMotionTerms`, `abstractIntentTerms`, and `negativeInstructionCount`.
- Review packet displays QA criteria separately from the prompt.

Failure action:
- Rewrite the compiler before generating another candidate.
- If the prompt fails, use `promptQuality.repairHints` as the next prompt edit list before spending another Grok attempt.

### Gate 4: Fresh Concept And Reference Packet

Goal: stop repeating the failed shoulder-release scene.

Required behavior:
- Run pre-production before any Grok/Gemini generation: topic brief, why-now, viewer question, storyboard beats, and asset briefs must exist.
- Use `POST /api/episodes/preproduction-plan` to write `storage/episodes/<episodeId>/preproduction/{preproduction-manifest.json,storyboard.json,storyboard.md,asset-briefs.json,episode-plan-request.json}`.
- `preproduction-manifest.status` must be `ready` before Gemini image reference or Grok video handoff starts.
- After Gemini/Grok/operator source attempts, run `POST /api/episodes/<episodeId>/preproduction/asset-candidates`.
- If the source came through the existing Grok review packet, run `POST /api/episodes/<episodeId>/preproduction/sync-grok-candidates` with `operatorApproved=true`; add `phoneSizeWatchApproved=true` and `noGenericBrollApproved=true` only after that review actually happened.
- `asset-candidate-review.status` must be `ready-for-render` before any render manifest is treated as a real quality candidate.
- Create a new 3-scene probe with large visible motion in the first second.
- Each scene has a reference note, action beat, visual risk, voice requirement, and prompt.
- The old office shoulder-release runway remains backlog/rejected evidence, not the next quality benchmark.
- Gemini is used for storyboard/reference image prompts only; prompt fill/generate/save remains operator-owned unless separately approved.
- Grok is used for storyboard-matched raw MP4 generation only after the Gemini/reference review or operator-owned source decision.

Good scene actions:
- A hand opens a door and enters a real place.
- A person pours, picks up, folds, flips, taps, or passes a specific object.
- Camera follows a moving subject through a narrow space.
- A visible screen/object state changes without relying on tiny facial expression or subtle posture.

Pass evidence:
- A new pre-production packet has a timely why-now, viewer question, concrete editorial angle, and three storyboard beats.
- `asset-briefs.json` maps every beat to Gemini reference-image and Grok raw-video prompts, or to an operator-owned source.
- `episode-plan-request.json` can be promoted to the existing `/api/episodes/plan` route without changing Grok/Gemini contracts.
- `/api/episodes/plan` writes `output-gates.json`, and prompt/artifact output is blocked unless `outputGate.status=pass`.
- `/browser-handoffs/.../extension-command` rechecks the current quality-loop ledger before returning prompt text; if the ledger says `apply-next-mutation`, the endpoint returns 409 and no prompt.
- `asset-candidate-review.json` records accepted/rejected candidates with phone-size review, storyboard match, artifact check, source provenance, caption-safe review, and first-second action proof for motion sources.
- `accepted-source-map.json` has one accepted Grok/operator motion source per storyboard beat.
- A new packet has three concrete scene prompts that pass Gate 3.
- The packet declares why it is easier to judge than the old shoulder-release scene.

Failure action:
- Replace the concept before spending more Grok/Gemini attempts.
- If `preproduction-manifest.status=blocked`, do not generate assets; fix the topic/storyboard first.
- If `asset-candidate-review.status=blocked`, do not render; replace the failed source candidate or rewrite the beat/action.
- If Grok sync is blocked only by phone-size or no-generic-B-roll approval, watch the candidate on a phone-sized preview and record that judgement instead of bypassing the gate.

### Gate 5: Zero-Paid Voice Quality

Goal: keep voice, but do not accidentally route to paid Google AI Studio or paid TTS.

Code surfaces:
- `worker/media/runtime.py`
- `worker/media/adapters.py`
- `scripts/edge_tts.py`
- `worker/render/compose_ffmpeg.py`
- `tests/test_manual_clip_pipeline.py`
- `tests/test_bgm_catalog.py`

Required behavior:
- Information/ranking/list videos have voice unless a human visual-led exception is recorded.
- The selected voice provider is explicitly identified as zero-paid for this workflow before use.
- Google AI Studio paid TTS, OpenAI TTS, ElevenLabs, or other paid APIs are blocked unless the operator explicitly opts in.
- Voice review checks pacing, pronunciation, energy, and audio balance.

Pass evidence:
- Render or review packet records the voice provider and zero-paid status.
- Quality report includes voice policy pass/fail.
- Phone review keeps voice naturalness as a blocking field.

Failure action:
- Try a different zero-paid voice path or reduce narration density; do not ship no-voice information/ranking by default.

### Gate 6: Source Import And Selection Integrity

Goal: use the selected source, not stale or low-quality files.

Code surfaces:
- `worker/bridge/routes_grok.py`
- `worker/bridge/routes_media.py`
- `worker/media/runtime.py`
- `worker/render/render_manifest.py`
- `tests/test_grok_handoff.py`
- `tests/test_manual_clip_pipeline.py`

Required behavior:
- Imports are tied to `importHistory`, `reviewDecisions`, filename/path/SHA-256, and clip probe.
- Stale exact-name files cannot outrank the operator-selected candidate.
- Visible-video fallback below quality floor is proof-only, not source-ready.
- Episode-level preproduction has `accepted-source-map.status=ready-for-render`; no render is treated as a real quality candidate while any storyboard beat lacks an accepted motion source.
- Native Chrome download prompts remain forbidden for Codex automation.

Pass evidence:
- Selected candidate path and SHA-256 appear in the render payload.
- Review-decision acceptance requires first-second hook, artifact-free, continuity, caption-safe, provenance, and AI/stock fit pass.

Failure action:
- Fix source selection before render.

### Gate 7: Render And Publish Quality

Goal: the final output is judged as a video, not as an artifact bundle.

Code surfaces:
- `worker/render/compose_ffmpeg.py`
- `worker/render/compose.py`
- `worker/render/transitions.py`
- `worker/render/subtitles.py`
- `worker/bridge/routes_media.py`
- `app/ui/src/components/RenderReviewPanel.tsx`
- `tests/test_manual_clip_pipeline.py`
- `docs/RENDERING-SPEC.md`

Required behavior:
- Final MP4 is 1080x1920, H.264/AAC, usable frame rate, no placeholder audio.
- Render engine changes follow `docs/RENDERING-SPEC.md` §6: H.264 `preset=medium crf=18 profile=high level=4.2`, Lanczos scale/crop, conservative scene/final unsharp/eq polish, and final subtitle burn-in review.
- Captions are mobile-readable and do not collide with subject or platform UI.
- BGM is real free music or approved native audio, not procedural/test-tone/beep.
- First frame and first two seconds are separately reviewed.
- Publish packet has title candidates, description, hashtags, review frames, contact sheet, shortcomings, and next actions.
- Render polish is never used to override source acceptance. If the source is stock-like, semantically wrong, static, or artifact-heavy, return to Gate 4 or Gate 6 before tuning FFmpeg.

Pass evidence:
- ffprobe proof.
- FFmpeg log or focused test proof that the render-quality floor was applied (`flags=lanczos`, `unsharp`, `eq`, `crf 18`).
- render-quality-report.
- quality-audit.
- publish-packet.
- dashboard smoke.
- phone-review template or completed phone-review proof, depending on upload claim.
- contact-sheet or phone-sized screenshot review for subtitle placement.

Failure action:
- Record the failed field and feed it into the next prompt/source/render decision.
- If the failed field is source/storyboard/phone review, do not claim a render-engine fix as quality recovery.
- If the failed field is render softness, compression, or caption layer legibility, apply `docs/RENDERING-SPEC.md` §6-§7 and rerender a named candidate without overwriting the prior accepted packet.

### Gate 8: Continuous Quality Loop Standard

Goal: every session leaves a resume-ready production record, so the next
session improves the candidate or the standard instead of restarting from
memory or chat context.

Code surfaces:
- `worker/quality_gate_system.py`
- `worker/bridge/routes_episodes.py`
- `worker/render/compose_ffmpeg.py`
- `worker/bridge/routes_media.py`
- `tests/test_episode_pipeline.py`
- `storage/episodes/<episodeId>/preproduction/quality-loop-standard.json`
- `storage/episodes/<episodeId>/preproduction/quality-iteration-ledger.json`

Required behavior:
- `POST /api/episodes/preproduction-plan` writes `quality-loop-standard.json`
  and `quality-iteration-ledger.json` beside the storyboard and asset briefs.
- The active standard version is
  `2026-06-08-production-gate-quality-loop-v3`.
- `GET /api/episodes/<episodeId>/preproduction/quality-loop` returns the
  active standard, ledger, and `nextRequiredAction`.
- `POST /api/episodes/<episodeId>/preproduction/quality-loop` appends a
  normalized iteration.
- `quality-loop-standard.json` must contain `contractRegistry`; output gates
  iterate that registry and fail if any registered contract is missing.
- `quality-loop-standard.json`, episode `outputGate`,
  `render-quality-report.json`, and final-library `goalReadiness` must expose
  the shared `gateSystem.systemVersion=
  2026-06-08-unified-quality-gate-system-v1`.
- `gateSystem` is the canonical cross-stage index. It does not replace the
  detailed checks; it binds preproduction, episode output, quality iteration,
  asset-source, render-quality, final-readiness, and post-publish analytics
  into one repeatable system.
- Any top-level `*Contract` added to the standard but omitted from
  `contractRegistry` is treated as an unregistered standard and blocks output.
- A failed, blocked, or `needs-spec-change` iteration must include
  `observedFailure`, `changedLever`, and `nextMutation`.
- A passing iteration must include `passEvidence` or `gateEvidencePaths`.
- A `needs-spec-change` iteration must include a `specChangeProposal` with
  `currentRule`, `whyInsufficient`, `proposedRule`, and `verificationPlan`.
- `caption` or `layout` failures must include `gateEvidencePaths` pointing to
  a contact sheet, phone screenshot, or render review packet.
- The standard must include `captionLayoutContract` with safe-zone ranges,
  Korean line length, max line count, preset/variant requirements, and
  render-review evidence fields.
- The standard must also include `voiceAudioContract`,
  `editRhythmContract`, `renderReviewContract`, and
  `publishReviewContract`.
- Old quality-loop standards without those contracts block episode output gates
  until preproduction is regenerated.
- `voice`, `audio`, or `bgm` failures must include `gateEvidencePaths`
  pointing to an audio review, render report, or phone review path.
- `edit-rhythm` failures must include `gateEvidencePaths` pointing to a
  contact sheet, timeline review, or render report.
- `phone-review` or `publish` failures must include `gateEvidencePaths`
  pointing to a phone-review JSON, publish packet, or platform proof.
- The next session must read `quality-iteration-ledger.nextRequiredAction`
  before generating another candidate.
- If `nextRequiredAction.status=apply-next-mutation`, the next iteration must
  include `resolvesIterationId`, `appliedMutation`, and mutation evidence. A
  generic pass/fail iteration that does not resolve the pending mutation is
  rejected.
- Output gates block both `apply-next-mutation` and `continue-current-stage`
  states. New prompt/artifact output is allowed only after the pending mutation
  is resolved or the current stage is completed.

Pass evidence:
- Focused episode tests prove the two files are written with the
  `2026-06-08-production-gate-quality-loop-v3` standard.
- Tests prove a failed iteration without `nextMutation` is rejected.
- Tests prove a pending mutation cannot be bypassed without
  `resolvesIterationId` and `appliedMutation`.
- Tests prove unregistered `*Contract` additions block output until the
  registry is updated.
- Tests prove episode output, render QA, and final-library readiness report the
  same unified gate system version and phase naming.
- Tests prove a spec-change proposal is stored and becomes the next required
  action.
- Tests prove caption/layout failures require evidence paths.
- Tests prove voice/audio and edit-rhythm failures require or record evidence
  paths.
- Episode output gate includes `captionLayoutStandard=pass`,
  `voiceAudioStandard=pass`, `editRhythmStandard=pass`,
  `renderReviewStandard=pass`, and `publishReviewStandard=pass`.

Failure action:
- Do not continue generation from chat memory only.
- If the output fails, record the failed layer and the next mutation.
- If captions overlap the subject, phone screen, object state, bottom 20%, or
  right-side platform UI, record a `caption` or `layout` iteration before
  rerendering.
- If TTS sounds slow/unnatural, if BGM masks narration, if a cut holds too
  long, or if phone/publish proof is missing, record the corresponding
  `voice`/`audio`/`bgm`/`edit-rhythm`/`phone-review`/`publish` iteration before
  promoting or rerendering.
- If the current standard cannot catch the failure, record a spec-change
  proposal before attempting another unrelated prompt/source/render.

### Gate 9: One-Candidate Live Demonstration Loop

Goal: prove the loop improves when it fails. The run must satisfy the quality
ratchet in `docs/RENDERING-SPEC.md` §6.6, not merely produce another MP4.

Required sequence:
0. Read `quality-iteration-ledger.nextRequiredAction`.
1. Load queue command.
2. Fill prompt.
3. Generate or operator-generate on verified provider surface.
4. Direct import or operator-owned already-saved upload.
5. Review decision.
6. Render.
7. Audit.
8. Phone-sized review.
9. Record failure reasons.
10. Record the ratchet fields: previous baseline, rejection cause, changed lever, expected visible improvement, actual proof, and next ratchet.
11. Append a quality-loop iteration with pass/fail evidence.
12. Confirm the next prompt/source/render gate changed based on those reasons.

Pass evidence:
- One candidate completes the sequence or fails at a named gate with a changed next action.
- The iteration names at least one viewer-facing `changedLever` from source, storyboard, edit rhythm, voice, BGM, caption layout, render engine, first-frame/thumbnail, or packet evidence.
- The next candidate's required bar is stricter than the previous candidate's bar.
- If the candidate is rejected, the next ratchet moves to the failed layer instead of repeating the same render settings.
- `quality-iteration-ledger.nextRequiredAction` names the exact next mutation
  for the next session.
- `render-quality-report.json` has `checks.qualityRatchet.status=pass` for any manifest that declares `qualityIteration` or `qualityRatchetRequired=true`.
- Episode preproduction packets carry the same ratchet template through `preproduction-manifest.json`, `asset-candidate-review.json`, and `accepted-source-map.json` before render.

Failure action:
- Do not start a second unrelated generation until the named gate is fixed.
- Do not mark a candidate as quality recovery when it only passes the previous floor.

## Parallel Codex Session Guidance

Current parallel task: `VIDEO-STUDIO-BROWSER-HANDOFF-INFRA-20260607-01`.

The parallel session owns or recently touched:
- `worker/bridge/routes_grok.py`
- `worker/bridge/routes_episodes.py`
- `tests/test_grok_handoff.py`
- `tests/test_episode_pipeline.py`
- `tools/chrome-grok-companion/*`

It should continue as follows:

1. Treat the existing signed-in Chrome browser-control rail as the production rail.
2. Keep the companion extension as fallback/diagnostic only; extension reload proof is useful, but it is not the front gate for production generation.
3. Keep Gemini web image support at browser-control prompt-fill/probe/result-visible proof only unless a separate result-import adapter is designed and approved.
4. Do not implement Gemini result import until the live Gemini result surface is inspected and a separate adapter/review gate is designed.
5. For Grok, use the existing signed-in Chrome/Grok Imagine surface through browser-control; `/c/*` chat threads remain blockers.
6. Generate at least one scene MP4 candidate through browser-control, then let the operator download/save the MP4.
7. Import the operator-owned MP4 through Downloads import or batch upload.
8. Review the imported candidate for first-two-second hook, artifact-free visuals, continuity, caption-safe composition, source provenance, and shot-lock match.
9. Preserve the no-native-download rule. Codex automation must not click Grok Download/Save/Export or any Chrome native prompt.
10. Use extension-only events only to diagnose fallback behavior, not to claim production progress.

Important current gap:
- Extension-only recovery remains useful for diagnostics, but production progress is blocked by missing Grok browser-control MP4 generation/import proof, not by missing extension reload proof.

## Topic-To-Source Work Order 2026-06-22

The `Topic` dashboard stage now creates a candidate-specific verification
worklist before any storyboard, Grok, Gemini, or CapCut work starts.

1. Select a ranked topic candidate.
2. Open its search, trend, video, and community verification links.
3. Record operator-confirmed URLs and observations into `sourceLedger`; the
   research links alone are only a worklist.
4. Run the topic-discovery gate. If it passes, the dashboard prepares the
   longform dry-run packet from the same topic packet.
5. Run the longform dry-run gate before storyboard/source-prompt-bible work.
6. Only after both gates pass should Gemini reference-image prompts or Grok raw
   video prompts be generated.
7. CapCut remains an editable timeline/export surface, not proof of a better
   edit by itself. Automatic CapCut export still requires explicit dependency
   approval and a separate live UI automation proof.

This sequence is the safe path for the 12-item backlog: source evidence first,
longform readiness second, browser generation third, edit/export proof last.

## Code-Level Next Work Order

1. Finish Gate 0 and avoid parallel-session code collisions.
2. Keep browser-control primary in status, automation plan, UI copy, and handoff docs.
3. Fix prompt compiler false positives before any further Grok attempts.
4. Keep `quality-loop-standard.json` and `quality-iteration-ledger.json`
   current for every preproduction packet.
5. Align caption preset constants and tests with `RENDERING-SPEC.md`.
6. Generate one Grok candidate through existing signed-in Chrome browser-control.
7. Import and review the MP4 with source provenance and caption-safe evidence.
8. Render only after the imported source candidate passes review.

## Definition Of Done For This Recovery Plan

This plan is not done when a document exists.

It is done only when:
- Companion live proof exists for the provider being used.
- Operator command URLs no longer require manual scene/take edits.
- Grok prompts are short positive shot instructions with banned meta removed.
- A fresh non-shoulder concept packet exists and passes prompt QA.
- Voice provider/cost and quality are recorded.
- Source import/selection evidence binds the selected source to the render.
- A rendered candidate has quality audit, publish packet, dashboard smoke, and phone-sized review evidence.
- Any failed candidate changes the next prompt/source/render decision instead of repeating the same bad generation.
- The active episode has a quality-loop ledger whose `nextRequiredAction`
  can drive a new Codex/Claude session without relying on chat memory.
