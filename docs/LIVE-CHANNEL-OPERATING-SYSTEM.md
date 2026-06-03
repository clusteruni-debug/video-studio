# Video Studio Live-Channel Operating System

Status: operational baseline for Shorts/Reels/TikTok repeat production  
Updated: 2026-05-31  
Policy: zero-paid sources only; no paid AI/API; manual Grok handoff stays Chrome-based.

## Baseline Re-Audit

Baseline final:
`storage/final-videos/grok-final-publish-gate-20260528-01/20-grok-final-publish-gate-candidate.mp4`

Gate-pass evidence:
- Output is 1080x1920, 30 fps, H.264/AAC, 15.8 seconds.
- Quality audit passes output spec, no placeholders, moving clip priority, zero-paid providers, caption safe presets, Grok source curation, BGM rotation, and top-tier readiness.
- The first scene has a visible motion hook and no-voice BGM/native-audio design.

Audit pass but still weak for a live channel:
- First two seconds are acceptable, but the first frame still needs a separate thumbnail/scroll-stop comparison before upload.
- Retention density is calm; five scenes in 15.8 seconds works for a routine/vlog post, but repeat channel use needs B/C templates with stronger information/list pacing.
- Caption placement is safe, but the prior output relies on one top hook plus repeated lower-info treatment; operators need template-aware layout variation.
- The video is publishable as one candidate, not a repeatable production system by itself.
- Grok/direct source provenance is recorded, but local downloaded Grok MP4s still require manual operator confirmation because the source is not an API-authenticated asset record.
- AI artifact risk is acceptable in audit, but live-channel operation still needs a human check for face/hand drift, temporal warping, and generic "AI lifestyle" feel before every upload.
- No platform analytics exist yet, so upload timing, title style, and hook wording are still experimental.

2026-05-31 reset-01 rejection:
- `live-channel-ops-info-reset-20260531-01` and `live-channel-ops-ranking-reset-20260531-01` are no longer counted as live-channel-ready samples.
- They proved the pipeline could finalize, but the actual output had no TTS for information/ranking formats, weak no-voice audio design, procedural/beep-like BGM risk, and captions/layouts that felt too default.
- Current gates now block information/ranking/list templates when they use no-voice without explicit human visual-led approval, and they fail procedural/sine/beep/click/test-tone BGM.

## Shortform Operating Templates

The reusable structures are implemented in `worker/bridge/templates.py` and exposed by `GET /api/live-channel/templates`.

### A. Authentic Vlog / No-Voice + BGM

- Caption preset: scene 1 `top-hook`; body `lower-info` or `none`.
- Safe zone: content x=60-950, y=100-1440; avoid bottom y>1536 and right x>950.
- Hook text position: top center safe-zone for scene 1 only.
- BGM/voice policy: no-voice by default; free/local BGM, native room tone, and subtle SFX.
- Cut transition: 0.35-0.50s fade/dissolve, handheld continuity.
- Thumbnail/first-frame rule: real action or object state, no baked-in title, watermark, UI, or generic beauty shot.
- Scene count/duration: 4-6 scenes, 2.8-4.0 seconds each, total 12-22 seconds.

### B. Information / Top-Hook + Lower-Info Captions

- Caption preset: scene 1 `top-hook`; body `lower-info`.
- Safe zone: top hook y~150; lower facts y~1300-1420; keep the right rail clear.
- Hook text position: top center with the payoff visible in the underlying clip within two seconds.
- BGM/voice policy: voice-first. Use TTS/voiceover for the viewer-facing explanation. No-voice requires explicit human visual-led approval plus BGM/native-audio review.
- Cut transition: fast hard cut or short dissolve between evidence beats.
- Thumbnail/first-frame rule: strongest evidence frame; title candidates live in the publish packet, not burned into video.
- Scene count/duration: 4-7 scenes, 2.5-4.5 seconds each.

### C. Ranking/List / Chapter-Card + Compact Captions

- Caption preset: scene 1 `top-hook` or rank title; body chapter-card plus compact lower-info.
- Safe zone: rank badge/title left-top safe; proof chip lower-mid; right/bottom UI clear.
- Hook text position: scene 1 announces the list promise; each rank gets one badge and one proof phrase.
- BGM/voice policy: voiceover required by default for ranking/list. No-voice requires explicit human visual-led approval; BGM must be real free music, not beep/click/test-tone/procedural audio.
- Cut transition: crisp item-to-item cuts with intentional structure repetition.
- Thumbnail/first-frame rule: communicate the list promise or a strong ranked visual.
- Scene count/duration: 3-6 ranked beats, 2.5-4.0 seconds each.

### Long-Form / 16:9 Extension

- Caption preset: chapter title, chapter evidence, and lower facts.
- Safe zone: keep essential subjects inside the central 80%; do not overload lower thirds.
- Hook text position: cold-open visual first, then a chapter card.
- BGM/voice policy: owned interview or voice audio first; BGM is only a bed.
- Cut transition: slower chapter transitions with evidence B-roll.
- Thumbnail/first-frame rule: separate thumbnail candidate from a real evidence frame.
- Scene count/duration: 6-12 scenes for a 2-5 minute segment; Shorts cutdowns reuse the strongest 4-6 beats.

## Repeat Workflow

1. Topic input: choose template type and platform target.
2. Scene plan: create 4-7 short beats with caption preset, safe-zone note, hook note, audio policy, and duration.
3. Candidate collection: use Grok Chrome handoff, direct/local uploads, local model clips, or free stock support. Paid APIs stay disabled.
4. Candidate selection: record candidate count, selected file name, selection reason, source provenance, and whether the source is accepted as main Grok/local/direct evidence.
5. Render: stitch moving clips through FFmpeg at 1080x1920, 30 fps, H.264/AAC.
6. Quality audit: require publish readiness, channel readiness, source motion evidence, safe captions, BGM/voice review, and top-tier readiness.
7. Publish packet: final MP4, first-frame/review frames, title candidates, description, hashtags, upload checklist, shortcomings, and next improvement actions.
8. Final library audit: dashboard scans `storage/final-videos` and surfaces upload/channel/top-tier/packet counts.

## Artifact Gate vs Operating Goal

The final-library audit has two different meanings:

- `artifactGateComplete`: a current candidate packet has the expected artifact evidence: final MP4, publish packet, quality audit, upload/channel/top-tier readiness, zero-paid policy, safe captions, source motion proof, and paired Grok/direct-import proof when required.
- `goalReadiness.preUploadDecision`: the same-day upload decision. It requires artifact gate completion plus explicit fresh Grok/manual Chrome source proof in `fresh-source-proof.json` and explicit `phone-review.json` pass evidence. It does not require platform analytics because those are recorded after upload, and it does not complete the broad Goal by itself.
- `goalComplete`: the broader live-channel operating-system Goal. This must stay false unless repeatability evidence also exists across a fresh source run, phone-sized human pre-upload review, and live platform analytics.
- `goalReadiness.operatorDecision`: the broad operating decision shown in the dashboard. It may be `수정 필요` even when the best packet-level decision is `업로드 가능`, because artifact readiness is not the same as repeatable live-channel operation readiness.

Do not close the broad Video Studio Goal from a final MP4, final-library audit pass, or Grok direct-import proof alone. Those can make an artifact upload candidate ready, but they do not prove the system can be repeatedly operated for a live Shorts/Reels/TikTok channel.

Dashboard decision hierarchy:

1. `today upload decision`: primary same-day Shorts/TikTok/Reels upload judgment. If this is `수정 필요` or `재렌더 필요`, the operator should not upload even when an artifact packet is technically complete.
2. `live-channel decision`: broad operating-system judgment. This stays `수정 필요` until fresh-source repeatability, phone review, and platform analytics prove the repeatable loop.
3. `artifact packet decision`: local packet evidence only. This can be `업로드 가능` while the actual same-day upload decision remains `수정 필요`.

## Fresh-Source Repeatability Evidence

Fresh source proof is a local artifact bound to the current best final MP4:

`storage/final-videos/<project-id>/fresh-source-proof.json`

Required fields:

- `recordedAt`, `sourceFlow`, `topic`
- `finalVideoPath`
- `handoffProjectId`, `renderedProjectId`
- `importedSceneCount`, `acceptedSceneCount`
- `differentTopic`, `movingClipStitching`, `sourceProvenanceReviewed`
- `qualityAuditPass`, `publishPacketComplete`, `dashboardSmokePass`

`importedSceneCount` and `acceptedSceneCount` must each be at least 3, and `finalVideoPath` must match the audited final MP4 path. Summary flags such as `freshGrokBatchProof` or `freshManualChromeSourceFlowProof` are treated as `summary-only`; they are not enough for repeatable live-channel operation and they cannot satisfy `preUploadReady`.

The audit also exposes `storage/final-videos/<project-id>/fresh-source-proof.template.json` as a safe fill-in draft. The dashboard `증거 템플릿 저장` action can materialize that worksheet through `POST /api/final-video-library/evidence-templates`. The draft can prefill packet-local evidence paths and SHA-256 digests for existing render/audit/publish artifacts, and it points `dashboardSmokePath` at packet-local `dashboard-smoke.json`. `dashboardSmokeSha256` is prefilled only when that JSON already records browser-rendered final-library evidence (`browserRendered=true`, bridge connected, final-library panel visible, rendered project text, and `today upload decision` visible text); API-only smoke remains unresolved. The worksheet is not a proof artifact and does not satisfy fresh-source repeatability.

Use the dashboard `Dashboard smoke 저장` action after the final-library panel is visibly rendered. It posts the panel's rendered text to `POST /api/final-video-library/dashboard-smoke`, writes packet-local `dashboard-smoke.json`, and refreshes the fresh-source worksheet. A valid capture can prefill `dashboardSmokeSha256`, but it still does not create `fresh-source-proof.json` or approve same-day upload by itself. A failed capture is stored as failed smoke evidence so the operator can see why the browser surface is not yet acceptable.

Use the dashboard `Fresh proof evidence 준비` action only after a best packet has a render manifest. It posts to `POST /api/final-video-library/fresh-source-evidence`, writes packet-local `fresh-source-handoff.template.json` and `fresh-source-review.template.json`, and refreshes `fresh-source-proof.template.json` with those draft paths and digests. The drafts include per-scene `proofBlockers` plus the current source-recovery acceptance gate, so reviewable render-manifest rows cannot be mistaken for fresh-source proof-ready scenes when `source-recovery-acceptance.json` is missing, template-only, or incomplete. This is evidence prep only: the review stays `needs-operator-review`, accepted scene count stays `0`, no `fresh-source-proof.json` is created, and upload approval still requires accepted source review plus the completed proof artifact.

The dashboard `Fresh intake 저장` action writes `storage/grok-handoffs/<handoff-id>/fresh-source-intake.template.json` through `POST /api/final-video-library/fresh-source-intake`. For rejected fresh-source scenes, that worksheet now includes `sourceRecoveryPlan` and `sourceRecoveryExecutionChecklist` with the recommended lane, local-review evidence, selected-stock rewrite candidates, expanded Pexels rewrite triage, direct-import URLs, forbidden native-download actions, and per-scene acceptance criteria. This is execution prep only: it does not satisfy `fresh-source-proof.json`, does not allow direct render, and does not approve upload until every rejected scene is replaced, accepted, rerendered, finalized, audited, dashboard-smoked, and recorded as proof.

The dashboard `Recovery review 준비` action writes `storage/grok-handoffs/<handoff-id>/source-recovery-acceptance.template.json` through `POST /api/final-video-library/source-recovery-acceptance`. This worksheet expands rejected recovery scenes into operator acceptance rows with render/proof blockers, required acceptance fields, lane-specific inputs, and a blank operator decision template. It is not `fresh-source-proof.json`, does not mark any scene accepted, does not allow direct render, and keeps upload approval blocked until accepted replacement sources are reviewed, rerendered, finalized, audited, dashboard-smoked, and recorded as proof.

The final-library audit now also checks `storage/grok-handoffs/<handoff-id>/source-recovery-acceptance.json` as the actual operator-filled acceptance artifact. The `.template.json` file is reported as `template-only-not-accepted`; an actual JSON remains incomplete until every recovery scene records an accepted replacement filename/path/SHA-256, reviewer, accepted timestamp, first-two-second hook pass, motion density pass, AI/stock fit pass, caption safe-zone pass, provenance confirmation, phone first-frame review pass, and continuity pass. The verifier also binds the accepted replacement filename to the path basename, requires the SHA-256 to match the exact local file, requires `acceptedAt` to be ISO-8601 with a timezone offset, and requires the local replacement to be a usable portrait MP4 video source. A fully accepted source-recovery artifact only clears the recovery acceptance gate for rerender; it still does not create `fresh-source-proof.json`, does not satisfy phone review or analytics, and does not approve upload.

Use `POST /api/final-video-library/source-recovery-rerender-plan` only after the actual `source-recovery-acceptance.json` status is `accepted-replacements-ready-for-rerender`. Before that, the route returns `blocked-by-source-recovery-acceptance` and does not write `source-recovery-rerender-plan.template.json`. After acceptance passes, it writes a template-only rerender worksheet containing the accepted replacement scene mapping, replacement source SHA-256 values, and the acceptance artifact SHA-256 so the rerender input can be reproduced. This worksheet is not a render, not `fresh-source-proof.json`, not phone review, not platform analytics, and not upload approval; it only preserves the exact source overrides to carry into rerender/finalize/audit/dashboard-smoke.

The operating runway checklist folds this verifier into `fresh-source-import-review`. When rejected scenes exist, that checklist item must show the acceptance gate status, accepted/incomplete scene counts, required `source-recovery-acceptance.json` path, and the next action to fill or use the accepted replacement source before rerender. This keeps the primary blocker pointed at the next concrete operator artifact instead of a generic "replace rejected scenes" instruction.

## Phone-Sized Human Review Evidence

Broad operating readiness now requires an explicit review artifact beside the best final-video packet:

`storage/final-videos/<project-id>/phone-review.json`

Required fields:

- `reviewedAt`, `deviceClass`, `finalVideoPath`, `reviewerDecision`
- `fullWatchCompleted`, `headphonesUsed`
- `captionSafeZonePass`, `mobileReadabilityPass`
- `voiceoverPolicyPass` for info/ranking/list formats. Set this true only when required TTS/voiceover is present, or when a visual-led no-voice exception was explicitly approved and recorded.
- `bgmVoiceBalancePass`, `bgmNonPlaceholderPass`
- `firstTwoSecondHookPass`, `cutDensityPass`
- `aiSlopVisualFitPass`, `stockAiClipFitPass`, `thumbnailFirstFramePass`

Set `reviewerDecision` to `pass` only after a full phone-sized watch with headphones. The `finalVideoPath` must match the audited final MP4 path, so copied or stale phone-review proof from another packet fails the gate. If the file is missing, incomplete, or bound to a different MP4, final-library audit keeps `phoneSizedHumanReviewReady=false`, and the dashboard shows broad `live-channel decision: 수정 필요` even when the current best packet-level decision is `업로드 가능`.

The audit also exposes `storage/final-videos/<project-id>/phone-review.template.json` as a safe fill-in draft. The dashboard `증거 템플릿 저장` action can materialize that worksheet through `POST /api/final-video-library/evidence-templates`. The draft defaults to `reviewerDecision=needs-review`; it is not a proof artifact and does not satisfy phone review readiness.

Use the dashboard `Phone evidence 준비` action before the human phone watch. It calls `POST /api/final-video-library/phone-review-evidence`, extracts packet-local phone review image evidence (`phone-review-snapshot.jpg`, `phone-caption-safe-zone.jpg`, `phone-thumbnail-first-frame.jpg`), writes an operator-review-required `phone-audio-mix-evidence.json`, and refreshes `phone-review.template.json`. Valid image evidence can prefill the corresponding SHA-256 fields, while the audio evidence digest remains unresolved until a real headphone review records pass evidence. This route never creates `phone-review.json` and never approves upload by itself.

## Platform Analytics Evidence

After an actual upload, record the live platform loop beside the final-video packet:

`storage/final-videos/<project-id>/platform-analytics.json`

Required fields:

- `recordedAt`, `platform`, `publishUrl`, `publishedAt`, `metricSource`, `finalVideoPath`
- `sampleWindowHours`, `views`
- `twoSecondHoldRate`, `fiveSecondHoldRate`, `averageViewDurationSeconds`
- `rewatchRate`, `swipeAwayRate`
- `decision`, `nextImprovementAction`

Valid `decision` values include `recorded`, `iterate`, `pass`, `scale`, and `archive`. Use `iterate` when the first live sample underperforms but still produced usable learning for the next hook/title/caption/source experiment. The `finalVideoPath` must match the audited final MP4 path, so analytics copied from another upload or packet cannot satisfy the loop. If the file is missing, incomplete, or bound to a different MP4, final-library audit keeps `platformAnalyticsRecorded=false`, and the dashboard shows broad `live-channel decision: 수정 필요`.

The audit also exposes `storage/final-videos/<project-id>/platform-analytics.template.json` as a safe fill-in draft. The dashboard `증거 템플릿 저장` action can materialize that worksheet through `POST /api/final-video-library/evidence-templates`. The draft defaults to `decision=missing`; it is not live analytics proof and does not satisfy the analytics loop.

## New Sample Candidates

Information template:
- Project: `live-channel-ops-info-voiceover-20260531-02`
- Final MP4: `storage/final-videos/live-channel-ops-info-voiceover-20260531-02/15-2-hook-tts-lower-info-grok-mp4-stitching-sho.mp4`
- Template: information / top-hook + lower-info captions.
- Result: publish ready, channel ready, upload ready, top-tier ready, quality-audit 22/22, publish packet exists.
- Key fixes: Edge TTS narration on all scenes, Mixkit BGM, voice policy pass, BGM sound quality pass.

Ranking template:
- Project: `live-channel-ops-ranking-voiceover-20260531-02`
- Final MP4: `storage/final-videos/live-channel-ops-ranking-voiceover-20260531-02/top-5-rank-card-layout-tts-compact-captions-grok.mp4`
- Template: ranking/list / chapter-card + compact captions.
- Result: publish ready, channel ready, upload ready, top-tier ready, quality-audit 22/22, publish packet exists.
- Key fixes: Edge TTS narration on all scenes, rank-card/rank-proof/rank-finale subtitle layouts, Mixkit BGM, no procedural/beep BGM.

Repeat-system candidate:
- Project: `live-channel-repeat-system-20260531-01`
- Topic: `퇴근 후 눈 피로 15초 리셋` ranking/list Shorts.
- Final MP4: `storage/final-videos/live-channel-repeat-system-20260531-01/15-5-shorts-grok-manual-mp4-clip-stit.mp4`
- Template: ranking/list / chapter-card + compact captions.
- Layout structure: scene 1 `top-hook` + `rank-card-compact`; body scenes `lower-info` + `rank-proof-chip`/`rank-final-proof`.
- Source flow: existing free/manual Chrome Grok retained MP4 pool, stitched as five moving clips. This is not a fresh Grok batch; provenance is recorded as `local-mp4-source-unverified` with operator confirmation and should be replaced by a fresh batch in the next operating experiment.
- Audio: Edge TTS on all scenes plus Mixkit `Swish Swed` BGM with source/license metadata; no fallback sine/test-tone/beep/click/procedural BGM.
- Result: publish ready, channel ready, upload ready, top-tier ready; quality audit 20/20; publish packet and first-frame/contact-sheet artifacts exist.
- Dashboard result: final-library best packet shows `operator decision: 업로드 가능`, upload/channel/top-tier counts, and Grok direct-import readiness.
- Gate additions from this run: `cutDensityPacing`, `aiSlopVisualFit`, `stockAiClipFit`, and `thumbnailFirstFrameStrength` are now separate quality/failure-review fields so automatic pass is not confused with live upload judgment.
- Remaining human check: watch the full MP4 on an actual phone-sized preview before upload; the automated audit cannot prove subjective BGM taste, face/hand drift, or scroll-stop strength by itself.

Fresh source runway:
- Project: `live-channel-fresh-source-runway-20260531-01`
- Topic: `퇴근 전 20초 집중력 회복 루틴` ranking/list Shorts.
- Status: source-acquisition runway only; no final MP4 yet.
- Handoff manifest: `storage/grok-handoffs/live-channel-fresh-source-runway-20260531-01/handoff.json`
- Worksheet: `http://127.0.0.1:5161/api/grok-handoff/live-channel-fresh-source-runway-20260531-01/worksheet`
- Production queue: `http://127.0.0.1:5161/api/grok-handoff/live-channel-fresh-source-runway-20260531-01/production-queue`
- Review packet: `http://127.0.0.1:5161/api/grok-handoff/live-channel-fresh-source-runway-20260531-01/review-packet`
- Source plan: five Grok/manual Chrome scenes, Take 2 `motion-first` recommended for each scene, expected files `scene-01.grok.mp4` through `scene-05.grok.mp4`.
- Prompt QA: all five scene prompts are `ready` after moving the anti-slop phrase into the source prompt itself. The prompts explicitly reject generic stock/ad/AI montage look and require real phone-camera motion in the first second.
- Dashboard freshness guard: final-library audit now exposes `sourcePipelineStatus.grok.latestHandoff`. It reports handoff status, imported/accepted counts, missing scenes, Downloads freshness, and `importPreflight`/`importPreflightSummary` with ready/present/missing/stale/invalid scene counts so a missing-import runway never displays a null preflight state.
- Handoff selection guard: final-library audit also exposes `sourcePipelineStatus.grok.handoffSelection`. A newer toy/smoke handoff does not replace a live-channel, quality-gated, multi-scene production runway solely because its `handoff.json` mtime is newer; the dashboard shows when a lower-score latest-by-mtime handoff was ignored.
- Browser-generation proof guard: `storage/grok-handoffs/live-channel-fresh-source-runway-20260531-01/browser-generation-proof.json` can record signed-in Chrome/Grok Imagine posts that were generated and playable in the browser. This is provenance only. It does not satisfy `fresh-source-proof.json`, does not count as native MP4 import, and does not allow render/upload until the MP4 files exist in `incoming` and pass import preflight.
- Operator decision guard: `latestHandoff.operatorDecision` reports `수정 필요` for this runway because fresh Grok MP4 imports are missing. A fully imported and accepted handoff should move to `재렌더 필요`, not `업로드 가능`, until a fresh final MP4, quality audit, publish packet, ffprobe, dashboard smoke, and phone-sized review exist.
- Live-channel decision guard: dashboard now shows broad `live-channel decision: 수정 필요` while retaining packet-level `operator decision: 업로드 가능`. This keeps operators from treating an artifact audit pass as proof that the repeatable channel operating system is ready.
- Pre-upload decision guard: dashboard now shows `pre-upload decision: 수정 필요` when the best packet is artifact-ready but still lacks fresh-source proof or phone-sized human review. This is the actual "can this go out today?" lane and remains separate from both packet readiness and broad post-upload operating completion.
- Operating runway checklist guard: final-library audit now exposes `goalReadiness.operatingRunwayChecklist` and `runwayChecklistSummary`, and the dashboard shows `runway next` in the operating proof surface. Current runtime sequence is `artifact-gate:pass`, `fresh-source-import-review:missing`, `fresh-source-proof:missing`, `phone-sized-human-review:missing`, `same-day-upload-decision:edit`, and `platform-analytics-loop:missing`, so the primary blocker is fresh source import/review rather than upload/archive.
- Source recovery blocker detail guard: the fresh-source runway checklist detail includes rejected scene IDs, live fail categories, and source-recovery lane counts. Imported `5/5` with accepted `2/5` must read as rejected-scene recovery work, not as source acquisition completion.
- Fresh-source proof guard: dashboard now shows `fresh-source repeatability: missing|summary-only|fail|pass`, the expected `fresh-source-proof.json` path, and missing/failed fields. Summary-only fresh-source claims are not enough for the broad operating Goal or pre-upload approval.
- Fresh-source final-video binding guard: `fresh-source-proof.json` must include `finalVideoPath` matching the current best final MP4, imported/accepted moving clip counts, and dashboard smoke proof for a different-topic source run. Mismatched proof stays `failedFields=["finalVideoPath"]`.
- Phone-review guard: dashboard now shows `phone-sized human review: missing`, the expected `phone-review.json` path, and missing fields. Summary-only phone review claims are not enough for the broad operating Goal.
- Platform analytics guard: dashboard now shows `platform analytics: missing`, the expected `platform-analytics.json` path, and missing fields. Summary-only analytics claims are not enough for the broad operating Goal.
- Final-video binding guard: `phone-review.json` and `platform-analytics.json` must include `finalVideoPath` matching the current best final MP4. Mismatched proof stays `failedFields=["finalVideoPath"]` and does not satisfy pre-upload or analytics readiness.
- Proof-template guard: dashboard now shows `fresh-source-proof.template.json`, `phone-review.template.json`, and `platform-analytics.template.json` draft paths. These are operator fill-in helpers only; they do not count as source, phone review, or analytics proof, and broad `goalComplete` remains false.
- Template materialization guard: `POST /api/final-video-library/evidence-templates` and the dashboard `증거 템플릿 저장` action write only `.template.json` worksheets. Runtime audit after materialization still reports `freshSourceRepeatability.status=missing`, `phoneSizedHumanReview.status=missing`, `platformAnalytics.status=missing`, and `goalComplete=false`; no `fresh-source-proof.json`, `phone-review.json`, or `platform-analytics.json` proof file is created.
- The six existing `grok-video-*.mp4` files in Downloads are all older than this handoff, so they are excluded from fresh-source repeatability proof. They must not be used to complete this runway unless deliberately re-imported as retained-source caveat material, which would still not satisfy the fresh-source Goal gap.
- Current Chrome/Grok result: scene-01 through scene-05 were generated in the signed-in Grok Imagine web session as 720x1280, 6.041667s videos, with post URLs recorded in `browser-generation-proof.json`. The five native MP4 files were later acquired by observing Chrome Grok `currentSrc` MP4 URLs and fetching those URLs locally, then recording bridge `directImportProof=true` import events.
- Native import update 2026-06-02: `incoming/scene-01.grok.mp4` through `incoming/scene-05.grok.mp4` exist and map to the correct scenes after the scene-match fix in `routes_grok.py`. This proves native file acquisition, but it does not prove upload readiness.
- Visual QA update 2026-06-02: the runway is stopped before render. `scene-02` has semantically wrong phone/timer UI, `scene-03` is too static/stock-like and does not read as shoulder-release motion in the first two seconds, and `scene-05` has a large baked-in timer overlay. `scene-01` and `scene-04` are candidates, but not enough for the full ranking/list structure.
- Current status: imported `5/5`, accepted `2/5` (`scene-02`, `scene-04`), rejected `3/5` (`scene-01`, `scene-03`, `scene-05`), fresh final MP4 `0`, publish packet `0`, phone review `0`, platform analytics `0`. Bridge/API status correctly keeps `allReady=false`; render remains blocked because the opening, shoulder-release, and final-return beats are not upload-grade.
- Dashboard blocker update 2026-06-02: fixed the local dashboard CORS failure. The bridge now allows the configured dev UI `5160`, stale/default dev UI `5173`, and preview `4160` origins. After bridge restart, Chrome dashboard smoke on both `http://127.0.0.1:5160/` and `http://127.0.0.1:5173/` shows no `Bridge connection failed` and surfaces `today upload decision: 수정 필요`, fresh runway `needs-review`, imported `5/5`, accepted `2/5`, and `live-channel decision: 수정 필요`.
- Fresh retry update 2026-06-03: generated simplified no-face Grok retries for scene-01, scene-03, and scene-05. Recovered native source candidates for scene-03 and scene-05 into `incoming/scene-03-v4-20260603-grok.mp4` and `incoming/scene-05-v3-20260603-grok.mp4`, with 720x1280/24fps/audio ffprobe and contact sheets under `storage/qa/live-channel-fresh-source-runway-20260531-01/`. The retry did not recover a clean scene-01 native MP4, scene-03 still shows hand/finger AI deformation, and the visible Grok Download path opened native Chrome download UI / blocked asset behavior. Treat this as an operating-flow blocker, not an upload candidate.
- Current decision after 2026-06-03 retry: dashboard/final-library still show `today upload decision: 수정 필요`, fresh runway `needs-review`, accepted `2/5`, `preUploadReady=false`, and `goalComplete=false`. The existing best packet remains an artifact candidate, but the fresh-source repeatability loop is not proven.
- Native download dialog guard 2026-06-03: the Chrome companion `download-asset` autostart path is now direct-import-only when a local `uploadEndpoint` exists and blocks instead of clicking a temporary download link when `uploadEndpoint` is missing. Bridge/dashboard copy now tells operators that Codex automation must not press Grok Download/Save/Export; manual download remains an operator-owned fallback.
- Fresh-source intake guidance guard 2026-06-03: `fresh-source-intake.template.json` now treats Companion/pageAssets `uploadEndpoint` direct import or operator-owned manual batch upload as the allowed source-acquisition path and lists Codex automation pressing Grok Download/Save/Export as disallowed. The worksheet is still not proof and does not change the runway status by itself.
- Rejected-source backlog guard 2026-06-03: final-library audit now surfaces imported-but-rejected fresh-source scenes with `rejectedScenes`, `rejectedSceneIds`, `liveFailCategories`, and `replacementBacklog`. The dashboard shows rejected scene count plus fail categories such as weak first-2s hook, weak first frame, AI/stock mismatch, caption-safe-zone risk, continuity mismatch, and source-provenance gaps so imported `5/5` cannot be mistaken for upload readiness when accepted remains `2/5`.
- Local replacement candidate backlog guard 2026-06-03: after the native Chrome download dialog risk, Codex automation must not press Grok Download/Save/Export or open Grok asset/download UI. The final-library audit and dashboard now expose local `incoming/<sceneId>*.mp4` candidates for rejected scenes before generating or downloading more clips. Current runtime shows scene-01 `1/2`, scene-03 `4/5`, and scene-05 `3/4` unreviewed local replacement candidates, with operator action to review them for first-2s hook, AI-slop/source-fit, caption-safe framing, and scene assembly before render.
- Direct-import-only hard stop 2026-06-03: the Companion content script, background script, popup, and bookmarklet/production queue must not start Chrome browser downloads, temporary anchor downloads, Grok Download clicks, Save clicks, or Export clicks. If an `uploadEndpoint` is available they direct-import the MP4/blob into Video Studio; if not, they stop with a no-download-fallback/manual-upload message. Any already-open native Chrome download dialog is outside Codex control and must be closed by the operator.
- Local visual-review decision 2026-06-03: contact-sheet review selected and rejected `scene-01-f1a0c2c7-fbc6-42e6-8caf-2441de1723d4.mp4`, `scene-03-v4-20260603-grok.mp4`, and `scene-05-v3-20260603-grok.mp4`. Scene-01 keeps a weak/unsafe first hook and lower safe-zone risk, scene-03 has shoulder-action mismatch plus hand/finger AI risk, and scene-05 is the best local candidate but silently changes the payoff shot to hands-only. Do not render this runway from the current local candidates.
- Free Pexels replacement research 2026-06-03: to avoid native Chrome download dialogs, the current fallback experiment used only existing free Pexels search/direct-video URLs and local file review. Three candidates were downloaded under `storage/qa/live-channel-fresh-source-runway-20260531-01/free-pexels-replacement-research/downloads/`, with provenance in `selected-pexels-downloads.json` and verdicts in `replacement-review-20260603.md`. This is source triage only: scene-01 is a conditional staged-stock fallback, scene-03 is a conditional neck-tension rewrite fallback, and scene-05 fails direct use because the vertical frame leaves too much empty lower area. These clips are not fresh Grok proof, not upload-ready evidence, and still require accepted source review plus TTS/voiceover, real BGM, caption safe-zone proof, first-frame/thumbnail candidates, publish packet, ffprobe, dashboard smoke, and phone-sized review before render/upload.
- Pexels fallback dashboard boundary 2026-06-03: `sourcePipelineStatus.pexels.replacementResearch` now surfaces the structured `replacement-review-20260603.json` verdict in the final-library audit and dashboard. Operators see `Pexels fallback not upload-ready`, total/conditional/fail/upload-ready counts, no-audio count, scene verdicts, and `not proof for` fields. Current runtime remains `goalComplete=false`, `preUploadDecision=수정 필요`, and Pexels fallback `uploadReadyCandidates=0`.
- Native prompt policy update 2026-06-03: source acquisition that requires Grok Download/Save/Export, Chrome native download prompts, or Downloads watcher fallback is `blocked-repeatability-fail` because it waits on operator clicks and cannot be canceled repeatably. `sourcePipelineStatus.grok.nativeDownloadPromptPolicy` and the final-library dashboard now expose this boundary separately from direct-import readiness.
- Scene-05 Pexels reframe update 2026-06-03: `scene-05-reframe-smoke-20260603.json` corrects the earlier lower-empty-frame concern as a contact-sheet artifact. The full-frame 1080x1920/30fps smoke can be a selected-stock fallback only after rewriting the payoff beat to generic laptop focus; the top crop is too tight, and the current same-worker/phone/timer/eyes-return scene still fails direct use.
- Source recovery plan update 2026-06-03: `sourcePipelineStatus.sourceRecoveryPlan` combines rejected Grok backlog, local replacement candidates, and Pexels fallback research into a scene-by-scene operator lane. The current runway is `needs-source-recovery`: scene-01/03/05 are still rejected recovery scenes, local review remains upload-blocked, selected-stock rewrite lanes are available but not direct render approval, and direct-import regeneration remains the fallback if review/rewrite fails. Each recovery scene now carries `renderBlockers`/`freshSourceProofBlockers`, aggregate blocker counts, and scene ids blocking render/proof so source triage cannot be mistaken for an accepted rerender input. Dashboard smoke confirms `render blocked` and `수정 필요`.
- Next action: do not use visible Grok Download/Save/Export or any native browser download prompt as an import path. Use a bridge direct-import/upload or Companion/pageAssets route that does not open native download UI, regenerate or replace scene-01/03/05 with cleaner moving clips, then rerun review-decision. Only after enough source clips pass should the runway proceed to render with TTS/voiceover, real non-placeholder BGM, caption safe zones, publish packet, ffprobe final MP4, dashboard smoke, and phone-sized watch.

## Remaining Live Experiments

- A/B test first-frame choices against actual Shorts/Reels/TikTok mobile preview crops.
- Complete `live-channel-fresh-source-runway-20260531-01` with actual fresh Grok/manual Chrome MP4 imports, then carry it through render, audit, publish packet, and dashboard smoke.
- Run one fresh Grok batch per template instead of reusing the same retained routine source pool.
- Add real platform analytics after upload: 2-second hold, 5-second hold, average view duration, rewatch rate, and swipe-away rate.
- Compare no-voice BGM candidates per series so repeated uploads do not sound identical.
- Add a human visual review note after watching the final MP4 on a phone-sized viewport, not only through automated gates.
- Improve automatic title/description generation beyond the two routine templates; current Korean candidates are acceptable for the reset-routine samples but not yet a general copywriting system.

## Local Candidate Review Evidence Update 2026-06-03

- `source-recovery-review-20260603.json` records that local MP4/contact-sheet review is complete for scene-01/03/05 and upload-ready local candidates remain `0/3`.
- The dashboard now shows `local evidence all-local-candidates-reviewed-upload-blocked`, reviewed `3`, failed `3`, and rewrite lanes for all three scenes.
- This moves the next operator step from "review local candidates" to "rewrite selected-stock fallback with caveats or regenerate through direct import". It still does not authorize render or upload.

## Selected-Stock Rewrite Render Packet 2026-06-03

- New draft project: `live-channel-fresh-source-rewrite-20260603-01`.
- Final MP4: `storage/final-videos/live-channel-fresh-source-rewrite-20260603-01/20-ranking-list-shorts-selected-stock-rewrite-dr.mp4`.
- Structure: ranking/list template with 5 moving MP4 clips, scene-01 top hook, scene-02/03/04 compact rank proof chips, scene-05 final proof. All scenes use viewer-facing TTS/voiceover and Mixkit `Swish Swed` BGM.
- Source mix: scene-02 and scene-04 use accepted Grok handoff MP4s. Scene-01/03/05 use local Pexels selected-stock rewrite fallbacks with source/license/candidate evidence. They are not owned source, not fresh Grok proof, and not acceptable as the first hook for upload approval.
- Publish packet exists and is content-complete, but decision is `needs-edit`. Runtime audit shows `publishStatus=ready`, `channelStatus=needs-hero-original-footage`, `uploadStatus=blocked`, `readyForUpload=false`.
- Operator meaning: dashboard/final-library can now distinguish "render/publish packet exists" from "uploadable today". This packet should be used to inspect cadence, TTS/BGM/caption layout, and packet completeness, not to upload.
- Browser/download boundary: do not use visible Grok Download/Save/Export or any native Chrome download prompt. Local Playwright was unavailable and Chrome CLI attached to the existing user browser session, so UI screenshot smoke was stopped. API readiness smoke is recorded at `storage/renders/live-channel-fresh-source-rewrite-20260603-01/dashboard-readiness-api-smoke-20260603.json`.
- Direct-import next-action update: final-library next actions now say to use Companion/pageAssets `uploadEndpoint` direct import or operator-owned already-saved MP4 batch upload. Runtime evidence is recorded at `storage/renders/live-channel-fresh-source-rewrite-20260603-01/dashboard-readiness-api-smoke-20260603-direct-import-wording.json`; it confirms stale `generate and download` / `generate/download` wording is absent and native Chrome/Grok download prompts are explicitly forbidden. In-app Browser was unavailable and the only browser backend was the user's Chrome extension, so Codex did not use Chrome for a visual UI smoke.
- Publish-packet source-flow audit update: `publish-packet.json` and `.md` for this packet were corrected to the same no-native-download guidance. The final-library publish-packet content audit now treats unsafe `nextImprovementActions` wording such as `generate and download` or `generate/download` as missing `nextImprovementActions.safeSourceFlowGuidance`, so a stale packet cannot be surfaced as upload-ready only because the final MP4 and quality audit exist. Evidence is recorded at `storage/renders/live-channel-fresh-source-rewrite-20260603-01/publish-packet-safe-source-guidance-smoke-20260603.json`; it confirms `readyForUpload=false`, `uploadStatus=blocked`, direct-import guidance present, already-saved batch import present, and stale generate/download wording absent from next actions and publish packet JSON/MD.

## Native Prompt Hard Stop and Grok Hero Swap Trial 2026-06-03

- User-facing failure mode: if Chrome/Grok opens a native download prompt, Codex cannot reliably cancel or complete it without waiting for the operator. This is a repeatability failure, not a fallback.
- Route hard stop: `observed-asset` and `observed-asset-runway` no longer open direct `assets.grok.com/...mp4` asset tabs. They route to the local manual runway, and the manual runway no longer creates a direct MP4 download link or auto-arms a Downloads watcher.
- Dashboard copy: the Scene detail Grok panel now labels direct MP4 asset tabs as blocked for Codex automation and opens only the local operator runway. It does not present `MP4 asset runway` as an automation action.
- Trial project: `live-channel-grok-hero-swap-trial-20260603-01`.
- Render MP4, not final: `storage/renders/live-channel-grok-hero-swap-trial-20260603-01/20-ranking-list-shorts-grok-hero-swap-trial.mp4`.
- Structure: `ranking_list`; scene-01 `top-hook`; scenes 02-04 `rank-proof-chip + lower-info`; scene-05 `final-proof + lower-info`.
- Source flow: scene-01 was swapped to the already-local `scene-01.grok.mp4` direct-import file. No Chrome/Grok Download, Save, Export, direct MP4 asset-tab open, native prompt, paid API, or Downloads watcher was used for this trial.
- Quality result: ffprobe passes 1080x1920, 30/1 fps, H.264 video, AAC audio; TTS/voiceover, non-placeholder Mixkit BGM, caption safe-zone, moving clips, and Grok source curation pass.
- Upload result: blocked. Hero source proof now passes (`heroOriginalClipReady=true`, `heroAiOrLocalReady=true`), but `scene-01` visual verdict fails because the phone UI/screen dominates the first hook and weakens first-frame safety. `publishStatus=blocked`, `channelStatus=blocked`, `uploadStatus=blocked`, `topTierStatus=needs-publish-rework`.
- Evidence: `render-quality-report.json`, `blocked-quality-audit.json`, `first-frame-candidate.jpg`, `contact-sheet.jpg`, `grok-hero-swap-trial-readiness-20260603.json`, and `dashboard-readiness-api-smoke-20260603.json` under `storage/renders/live-channel-grok-hero-swap-trial-20260603-01/`.
- Operator meaning: this trial proves the system can distinguish "Grok/direct-import hero exists" from "upload-grade first hook exists." Do not finalize or upload this render. The next real source experiment needs a cleaner original/direct/Grok/local first hook before any final MP4 promotion.

## Grok Timer Hook Resequence Trial 2026-06-03

- Prompt-policy update: native Chrome/Grok download prompts are not a recoverable Codex automation state. Any already-open native prompt is operator-owned; Codex must not wait on it, trigger it again, or use Downloads watcher fallback.
- Trial project: `live-channel-grok-timer-hook-resequence-20260603-01`.
- Render MP4 candidate, not final promotion: `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/20-ranking-list-shorts-grok-timer-hook-resequence.mp4`.
- Template/layout: `ranking_list`; scene-01 `top-hook`; scenes 02-04 `rank-proof-chip + lower-info`; scene-05 `final-proof + lower-info`.
- Source flow: local-only. Scene-01 uses the accepted Grok/direct-import timer clip promoted to first hook; scene-04 remains accepted Grok/direct-import notebook action; scenes 02/03/05 remain selected-stock Pexels support/rewrite beats. No Chrome/Grok Download, Save, Export, direct MP4 asset-tab open, native prompt, paid API, or Downloads watcher was used.
- PASS: render completed; ffprobe confirms H.264 1080x1920, 30/1 fps video and AAC 48kHz mono audio. TTS/voiceover, non-placeholder Mixkit BGM, caption safe-zone presets, moving clips, source motion, first-two-second hook, and Grok source curation pass.
- FAIL for live upload: `finalize-render` with `requireTopTier=true` returns 409 and writes `blocked-quality-audit.json`. The first hook is better than the UI-heavy opener, but `stockAiClipFit=fail`; original/Grok/local/direct source mix is only 2/5 while the top-tier/live-channel threshold is 3/5. Stock scenes 02/03/05 also create visible subject/location mismatch.
- Blocked publish packet: `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/blocked-publish-packet.json` and `.md` contain the MP4 candidate, first-frame/contact-sheet candidates, title candidates, description, hashtags, checklist, shortcomings, and next improvement actions.
- Dashboard/API evidence: `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/dashboard-readiness-api-smoke-20260603.json` records `uploadDecision=blocked`, operator surface `수정 필요 / 재렌더 필요`, and `doNotSurfaceAs=업로드 가능`.
- Operator meaning: this trial proves the local direct-import-only resequence can improve the first hook without native prompts, but it is still not a live-channel upload candidate. Replace at least scene-03 and scene-05 with accepted Grok/local/direct/owned moving clips, rerender, run `requireTopTier=true`, then do phone-sized full-watch review before upload.

## Native Prompt Hard Block 2026-06-03

- Chrome/Grok native download prompts are now a hard stop, not a fallback. If a prompt is already visible, it is operator-owned and Codex must not wait on it, cancel it, click through it, or trigger another one.
- Grok browser automation is allowed only for prompt fill/generate. It sends `downloadResultApproved=false` and `watchDownloadsApproved=false`.
- CDP download/watch execution now fail-fast blocks legacy approval flags before touching Grok Download/Save/Export controls.
- Scene dashboard watch/operator-run CTAs are disabled and labeled as blocked. Active source routes are:
  - Companion/pageAssets `uploadEndpoint` direct import.
  - Bookmarklet or console direct fetch that posts to the local upload endpoint.
  - Explicit local MP4 upload/import when the operator already owns the saved file.
- Dashboard must not show `Downloads watcher` or `Download/Save/Export` as an active Codex route for live-channel source recovery.
- This is a repeatability fix only. It does not make any current render uploadable; the active timer-hook candidate remains blocked by source mix 2/5, stock mismatch, missing phone review, missing fresh-source-proof, and missing platform analytics.

## Source-Mix Upload Gate Correction 2026-06-03

- User-facing blocker reaffirmed: if Chrome/Grok opens a native download dialog, Codex cannot safely cancel or complete it repeatably. This continuation used no Chrome/Grok Download, Save, Export, direct MP4 asset-tab open, native prompt, paid API, or Downloads watcher fallback.
- Gate fix: `worker/render/compose_ffmpeg.py` now treats multi-scene live-channel templates (`ranking_list`, `tutorial_steps`, `authentic_vlog`, `persona_story`, `kculture_fandom`, `live_recap`) as upload-blocked when reviewed Grok/local/direct/owned MP4 clips are below the source-mix threshold. The same stock-heavy source-mix gap is also surfaced as `stockAiClipFit=fail` so stock/AI clip mismatch is a distinct fail reason, not just a generic top-tier warning.
- Runtime result for `live-channel-grok-timer-hook-resequence-20260603-01`: `stockAiClipFit=fail`, `publishReadiness=blocked`, `channelReadiness=blocked`, `uploadReview=blocked`, `uploadReviewGate=fail`, `topTierReadiness=needs-publish-rework`, original/Grok/local/direct `2/5`, minimum `3/5`, stock gap scenes `scene-02`, `scene-03`, `scene-05`.
- Evidence refreshed:
  - `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/render-quality-report.json`
  - `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/blocked-quality-audit.json`
  - `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/blocked-publish-packet.json`
  - `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/blocked-publish-packet.md`
  - `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/dashboard-readiness-api-smoke-20260603.json`
- Operator meaning: this render can be used to review cadence, TTS/BGM/caption safety, and first-hook improvement, but the dashboard must surface it as `수정 필요 / 재렌더 필요`, never `업로드 가능`. At least one of scene-02/03/05 must be replaced with accepted Grok/local/direct/owned moving footage before another publish/channel/upload/top-tier finalize attempt.

## Source-Mix Next Action Surface 2026-06-03

- User-facing blocker restated: a native Chrome/Grok download prompt is operator-owned once visible. Codex automation must not wait on it, click through it, or rely on Downloads watcher recovery.
- Bridge/dashboard fix: blocked `finalize-render` payloads now emit `fix-original-source-mix` when `topTierReadiness=needs-original-source-mix`, `originalSourceMixReady=false`, or the `originalSourceMix` criterion fails.
- Runtime result for `live-channel-grok-timer-hook-resequence-20260603-01`: the first blocked action says original/direct/Grok/local scenes are `2/3`, stock scenes are `scene-02`, `scene-03`, and `scene-05`, and at least one stock/support scene must be replaced.
- Safe source-flow action: the operator action now allows Companion/pageAssets `uploadEndpoint` direct import, bookmarklet/direct fetch, or operator-owned already-saved MP4 batch import only. It explicitly forbids Grok Download/Save/Export, direct MP4 asset tabs, Chrome native download prompts, and Downloads watcher fallback.
- Evidence: `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/blocked-quality-audit.json` and `dashboard-readiness-api-smoke-20260603-source-mix-next-action.json`.
- Operator meaning: dashboard/API readiness can now show the exact rerender reason without treating publish/channel readiness as upload approval. This still does not create a final-videos promotion, phone-sized review, fresh-source-proof, or platform analytics.

## Dashboard Source-Mix Label Correction 2026-06-03

- UI fix: `RenderReviewPanel` now labels `topTierReadiness.status=needs-original-source-mix` as `needs original source mix` instead of falling through to `needs Grok/local hero`.
- UI severity: the same source-mix status now uses the blocking/fail class in the top-tier gate, matching `uploadReview=blocked` and the source-mix next action.
- Evidence: `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/dashboard-ui-source-mix-label-smoke-20260603.json` records `topTierStatus=needs-original-source-mix`, `uploadStatus=blocked`, `uiLabelSourcePresent=true`, `uiFailClassSourcePresent=true`, and `firstBlockedAction.key=fix-original-source-mix`.
- Browser boundary: this smoke is static/API evidence only. Codex did not use the user's Chrome session because native download prompts are an operator-owned blocker. The operating dashboard remains expected to show `수정 필요 / 재렌더 필요`, not `업로드 가능`.

## Companion Native Download Non-Starter Guard 2026-06-03

- User-facing blocker restated: if a native Chrome/Grok download prompt is already open, Codex cannot make it repeatable by waiting on it or canceling it. The production system must avoid creating that prompt in the first place.
- Companion code guard: `content.js` now reports a URL candidate as `direct-imported` only when the background import returns `directImport=true`. Any non-direct-import outcome is reported as `blocked`, not `started`, and throws a blocked/direct-import failure.
- Popup guard: `popup.js` no longer emits `downloadStarted` or `downloadId`; the only success state for visible MP4 import is direct import through the loaded `uploadEndpoint`.
- Documentation guard: `tools/chrome-grok-companion/README.md` now states that the companion never starts a Chrome browser download. Its `chrome.downloads` listener only observes a completed operator-owned manual download.
- Queue/manual-watch copy guard: the Grok production queue now says direct-imported or operator-uploaded MP4s only, and the manual folder watch is described as operator-owned local MP4 observation. It explicitly says Codex automation must not press Grok Download/Save/Export or wait on a native Chrome prompt.
- Evidence:
  - `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/native-download-prompt-code-guard-20260603.json`
  - `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/blocked-publish-packet.json`
  - `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/dashboard-readiness-api-smoke-20260603-source-mix-next-action.json`
  - `storage/renders/live-channel-grok-timer-hook-resequence-20260603-01/dashboard-ui-source-mix-label-smoke-20260603.json`
- Operator meaning: this reduces repeatability risk in the source pipeline, but it does not make the current render uploadable. Source mix remains 2/5 original/Grok/local/direct against a 3/5 threshold, stock mismatch remains, and phone review/fresh-source-proof/platform analytics are still missing.

## Scene-05 Source-Mix Trial 2026-06-03

- User-facing blocker restated: an already-visible Chrome/Grok native download prompt is operator-owned. Codex did not click, cancel, wait on, or recover through that prompt, and did not use Grok Download/Save/Export, direct MP4 asset tabs, paid APIs, or Downloads watcher fallback.
- Trial project: `live-channel-grok-scene05-source-mix-20260603-01`.
- Render MP4 candidate, not final promotion: `storage/renders/live-channel-grok-scene05-source-mix-20260603-01/20-ranking-list-shorts-grok-scene05-source-mix.mp4`.
- Template/layout: `ranking_list`; scene-01 `top-hook`; scenes 02-04 `rank-proof-chip + lower-info`; scene-05 `final-proof + lower-info`. The edit remains 5 moving stitched clips with Edge TTS voiceover and Mixkit `Swish Swed` non-placeholder BGM.
- Source flow: scene-05 now uses the already-local, direct-import-proven Grok v2 MP4 `scene-05-v2-ae5127b2-9bf5-46b9-bfba-c1add37214e6.mp4`, copied into the new local input as `scene-05-grok-v2-payoff.mp4`. Proof remains in `storage/grok-handoffs/live-channel-fresh-source-runway-20260531-01/extension-events.jsonl` with `directImportProof=true`.
- PASS: render completed; ffprobe confirms H.264 1080x1920, 30/1 fps video and AAC 48kHz mono audio. TTS/voiceover, non-placeholder BGM, moving clips, first-two-second hook, cut density, source provenance, and original/Grok/direct source mix now pass at 3/5 against a 3/5 minimum.
- FAIL for live upload: source-mix count is no longer the first blocker, but `scene-03` remains a visible stock/person/location mismatch and has `visualQualityVerdict=fail`. `captionLayoutReview=fail` because scene-03 and scene-05 still need explicit phone-sized caption placement review. `stockAiClipFit=fail`, `aiSlopVisualFit=fail`, `publishReadiness=blocked`, `channelReadiness=blocked`, `uploadReview=blocked`, and `topTierReadiness=needs-publish-rework`.
- Evidence:
  - `storage/renders/live-channel-grok-scene05-source-mix-20260603-01/render-quality-report.json`
  - `storage/renders/live-channel-grok-scene05-source-mix-20260603-01/blocked-quality-audit.json`
  - `storage/renders/live-channel-grok-scene05-source-mix-20260603-01/blocked-publish-packet.json`
  - `storage/renders/live-channel-grok-scene05-source-mix-20260603-01/blocked-publish-packet.md`
  - `storage/renders/live-channel-grok-scene05-source-mix-20260603-01/first-frame-candidate.jpg`
  - `storage/renders/live-channel-grok-scene05-source-mix-20260603-01/contact-sheet.jpg`
  - `storage/renders/live-channel-grok-scene05-source-mix-20260603-01/dashboard-readiness-api-smoke-20260603-scene05-source-mix.json`
- Dashboard meaning: the operator surface must remain `수정 필요 / 재렌더 필요`, never `업로드 가능`. The first blocked action is now `fix-visual-fit-failures`, followed by `fix-caption-layout`; replace or rewrite scene-03, add caption layout review for scene-03/05, rerender, and run `finalize-render requireTopTier=true` again before any upload decision.
- Broad Goal boundary: this is a repeatability improvement and a new local-only operating-template trial, not live-channel completion. There is still no final-videos promotion, no phone-sized full-watch proof, no fresh-source-proof bound to a final MP4, and no platform analytics loop.

## Visual-Fit First Blocked Action 2026-06-03

- User-facing blocker restated: a Chrome/Grok native download prompt can remain modal until the operator clicks it, so Codex must not use Download/Save/Export, direct MP4 asset tabs, or Downloads watcher fallback as a recovery route.
- API/dashboard fix: blocked `finalize-render` payloads now emit `fix-visual-fit-failures` before generic `complete-top-tier-gate` when `failedVisualVerdictScenes`, missing visual verdicts, `stockAiClipFit=fail`, or `aiSlopVisualFit=fail` are present.
- Caption review ordering: missing caption layout review now appears as `fix-caption-layout` before the generic top-tier/upload review actions, so the operator sees the concrete mobile-readability fix first.
- Runtime result for `live-channel-grok-scene05-source-mix-20260603-01`: refreshed `blocked-quality-audit.json` reports next actions in this order: `fix-visual-fit-failures`, `fix-caption-layout`, `complete-top-tier-gate`, `complete-upload-review`.
- Dashboard smoke evidence: `storage/renders/live-channel-grok-scene05-source-mix-20260603-01/dashboard-readiness-api-smoke-20260603-visual-fit-first-action.json` confirms the first blocked action is `fix-visual-fit-failures`, while `blocked-publish-packet.json` remains `uploadDecision=blocked`.
- Operator meaning: the dashboard should now say "replace the mismatched stock/AI visual" before it says "complete top-tier evidence." This is still `수정 필요 / 재렌더 필요`, not `업로드 가능`.

## Visual-Fit Source Recovery Lane 2026-06-03

- Runtime blocker: `scene-03` is still the visual-fit failure in `live-channel-grok-scene05-source-mix-20260603-01`.
- Dashboard/API improvement: `fix-visual-fit-failures` now carries `sourceRecovery` scene detail. For `scene-03`, the current lane is `rewrite-selected-stock-fallback`, local review verdict is `fail-upload-grade`, and the conditional Pexels candidate is `scene-03-pexels-27430390-neck-pain.mp4`.
- Guardrail: that Pexels candidate remains `conditional-fallback`, not direct upload approval. It requires script rewrite, phone-sized first-frame/caption/source-fit review, rerender, and another `finalize-render requireTopTier=true` pass before any upload decision.
- Evidence: `storage/renders/live-channel-grok-scene05-source-mix-20260603-01/dashboard-readiness-api-smoke-20260603-visual-recovery-lane.json` confirms first action `fix-visual-fit-failures`, scene-03 lane `rewrite-selected-stock-fallback`, `uploadDecision=blocked`, and no Chrome/Grok Download/Save/Export/native prompt/Downloads watcher use.
- Operator meaning: do not regenerate through visible Grok Download or accept the stock clip unchanged. Either rewrite the scene to honestly match the Pexels neck-pain visual and review it on phone, or replace it with accepted Grok/local/direct/owned moving footage through direct import/local MP4 only.

## Selected-Stock Rewrite Comparison 2026-06-03

- Native prompt boundary: Codex must not attempt to cancel, click through, wait on, or recover from a visible Chrome/Grok native download prompt. The only repeatable source routes remain uploadEndpoint direct import, bookmarklet/direct fetch into the local bridge, or operator-owned already-saved MP4 import.
- Dashboard/API improvement: `sourcePipelineStatus.selectedStockRewriteComparison` now discovers the latest selected-stock rewrite draft and attaches a scene-level `selectedStockRewriteCandidate` to matching visual-fit recovery items.
- Current comparison draft: `live-channel-fresh-source-rewrite-20260603-01` shows scene-03 visual/caption progress (`visualVerdictPass=true`, `captionLayoutReviewed=true`) and is useful as rewrite evidence.
- Upload guardrail: that draft is comparison-only, not upload-ready. It has original/direct/Grok/local source mix `2/3` against a `3` minimum, stock scenes `3`, `heroOriginalReady=false`, and `uploadReady=false`. It must not override source-mix, first-hook originality, phone review, fresh-source-proof, platform analytics, or final-videos gates.
- Evidence:
  - `storage/renders/live-channel-grok-scene05-source-mix-20260603-01/blocked-quality-audit.json`
  - `storage/renders/live-channel-grok-scene05-source-mix-20260603-01/dashboard-readiness-api-smoke-20260603-rewrite-comparison.json`
- Operator meaning: the selected-stock rewrite can guide a script/layout fix for scene-03, but the current scene05 source-mix candidate remains `수정 필요 / 재렌더 필요`, not `업로드 가능`.

## Stock/AI Clip Fit Verdict Gate 2026-06-03

- Native prompt boundary restated: an already-visible Chrome/Grok native download prompt is operator-owned. Codex did not click, cancel, wait on, recover through Downloads watcher, open direct MP4 asset tabs, or use Grok Download/Save/Export in this trial.
- Render gate change: `visualQualityVerdict=pass` no longer implies selected-stock/free-stock/not-owned footage is source-fit safe. Such scenes now need an explicit `stockAiClipFitVerdict`, `stockClipFitVerdict`, `sourceFitVerdict`, or `manualStockFitVerdict`.
- Upload/top-tier rule: missing or failed stock/source-fit verdicts make `checks.stockAiClipFit=fail`, add a required `uploadReview` blocker, and block `topTierReadiness` as `needs-publish-rework`.
- Regression coverage: `tests/test_manual_clip_pipeline.py` now covers a ranking/list source mix that otherwise passes original/Grok/direct source count, visual verdict, and caption layout, but is still blocked because `scene-03` lacks or fails stock/source-fit proof.
- Local-only operating-template trial: `live-channel-grok-scene03-stock-fit-gate-20260603-01`.
- Template/layout: `ranking_list`; scene-01 `top-hook`; scenes 02-04 `rank-proof-chip + lower-info`; scene-05 `final-proof + lower-info`. The candidate remains five stitched moving clips with Edge TTS voiceover and Mixkit `Swish Swed` BGM.
- Candidate MP4, not final promotion: `storage/renders/live-channel-grok-scene03-stock-fit-gate-20260603-01/20-ranking-list-shorts-scene03-stock-fit-gate.mp4`.
- PASS evidence: ffprobe confirms H.264 1080x1920, 30/1 fps video and AAC 48kHz mono audio. TTS/voiceover, non-placeholder BGM, moving clips, first hook, cut density, caption layout review, source provenance, original/Grok/direct source mix `3/5`, and `aiSlopVisualFit` pass.
- FAIL for live upload: `scene-03` has explicit `stockAiClipFitVerdict=fail` because the selected-stock neck-pain/person/location/prop continuity does not match the Grok timer/notebook source family. `publishReadiness=blocked`, `uploadReview=blocked`, `topTierReadiness=needs-publish-rework`, and no final-videos promotion was made.
- Publish packet evidence:
  - `storage/renders/live-channel-grok-scene03-stock-fit-gate-20260603-01/render-quality-report.json`
  - `storage/renders/live-channel-grok-scene03-stock-fit-gate-20260603-01/blocked-quality-audit.json`
  - `storage/renders/live-channel-grok-scene03-stock-fit-gate-20260603-01/blocked-publish-packet.json`
  - `storage/renders/live-channel-grok-scene03-stock-fit-gate-20260603-01/blocked-publish-packet.md`
  - `storage/renders/live-channel-grok-scene03-stock-fit-gate-20260603-01/first-frame-candidate.jpg`
  - `storage/renders/live-channel-grok-scene03-stock-fit-gate-20260603-01/contact-sheet.jpg`
  - `storage/renders/live-channel-grok-scene03-stock-fit-gate-20260603-01/dashboard-readiness-api-smoke-20260603-stock-fit-gate.json`
- Dashboard meaning: the operator must see `수정 필요 / 재렌더 필요`, never `업로드 가능`. The next action is to replace `scene-03` with accepted direct/Grok/local/owned moving MP4 through uploadEndpoint/direct fetch/operator-owned already-saved MP4 only, or prove source fit with phone-sized review before rerender/finalize.
- Broad Goal boundary: this is a repeatability and gate-quality improvement, not live-channel completion. Phone-sized full-watch review, fresh-source-proof bound to the final MP4, platform analytics, and final-videos promotion are still absent.

## Rejected Grok Source Review Gate 2026-06-03

- Local review result: existing `scene-03` Grok replacement takes under `storage/grok-handoffs/live-channel-fresh-source-runway-20260531-01/incoming/` were rechecked from contact sheets. v2 has the best motion but keeps AI/stock-like human artifact risk, v3 has neck/back/hand proportion drift, v4 is a hands-only insert and does not show the shoulder-release beat. None should be promoted as upload-grade scene-03 footage.
- Render gate change: `worker/render/compose_ffmpeg.py` now reads source-review verdict fields from the scene, selected candidate, visual asset, and source provenance (`sourceReviewVerdict`, `sourceFitVerdict`, `operatorSourceReviewVerdict`, `grokSourceReviewVerdict`, `localCandidateReviewVerdict`, `sourceRecoveryReviewVerdict`, `reviewDecision`, `reviewVerdict`, `operatorReviewStatus`, `sourceReviewStatus`, plus explicit accepted=false flags).
- A Grok handoff scene with a failing/rejected source-review verdict now adds `sourceReviewRejected`, appears in `rejectedGrokSourceReviewScenes`, and makes `checks.grokSourceCuration=fail` even if candidate count, selected filename, and provenance are otherwise present.
- Operator-facing copy now asks for direct-import or already-saved-local provenance and no rejected source review verdict. It no longer tells operators to satisfy the curation gate via Grok Download/Save/Export evidence.
- Regression coverage: `test_render_quality_report_blocks_rejected_grok_source_review` proves a technically complete Grok-main source fixture is still blocked when its selected candidate review decision is `rejected`.
- Operator meaning: already-reviewed local Grok files can be reused only if their source review is explicitly pass. A rejected Grok take is not a stock-fit escape hatch for scene-03 and must not move a packet to `업로드 가능`.

## Source Recovery Direct-Import Runway 2026-06-03

- Dashboard/API improvement: `sourcePipelineStatus.sourceRecoveryPlan.scenes[]` now includes a `directImportRunway` packet for each rejected recovery scene. The packet carries `expectedFileName`, recovery prompt text/path, `uploadEndpoint`, scene-specific proof monitor URL, observed Grok post URL when available, and the `observed-post-download.js?operatorApproved=true&sceneId=...` console-import script URL.
- UI improvement: `RenderReviewPanel` now surfaces the scene-level direct-import runway under Source recovery plan, with prompt copy, Grok post open, console direct-import copy, and proof monitor actions. This reuses the existing direct-import component and does not expose a Download/Save/Export route.
- Safety boundary: `directImportRunway` is not render approval. `directRenderAllowed=false`, `uploadReady=false`, native Chrome/Grok Download/Save/Export, direct MP4 asset tabs, and Downloads watcher fallback remain forbidden.
- Operator meaning: a blocked scene such as `scene-03` can now move directly from recovery review to a repeatable source-acquisition packet: generate or open the signed-in Grok post, run console/direct-import into the local uploadEndpoint, verify the expected MP4 in the proof monitor, then review/accept the scene before rerender/finalize.

## Scene-03 Expanded Pexels Search 2026-06-03

- Source acquisition result: six direct-URL Pexels candidates were downloaded and contact-sheeted under `storage/qa/live-channel-fresh-source-runway-20260531-01/scene-03-pexels-expanded-search-20260603/` without Chrome/Grok Download/Save/Export, native prompts, direct MP4 asset tabs, or Downloads watcher fallback.
- Review result: no candidate is upload-ready for the current scene-03 script. `8926991` and `35332008` are the only rewrite-only candidates; `12894322`, `12893573`, `12896411`, and `12908966` are rejected because they lack the shoulder/neck reset action or read as generic B-roll.
- Dashboard/API improvement: `sourcePipelineStatus.pexels.expandedSearch` and `sourceRecoveryPlan.scenes[].expandedPexelsSearch` now expose reviewed candidate counts, top candidates, contact-sheet paths, and the review/search artifact paths.
- Safety boundary: expanded Pexels search is source triage only. It does not satisfy fresh-source proof, current-script stock/source-fit pass, final MP4, publish packet, phone-sized review, or platform analytics.
- Operator meaning: if Pexels is used for scene-03, branch a rewrite around `8926991` or `35332008`, then rerender and rerun stock/source-fit, caption, phone review, publish packet, and final-library audit before any upload decision.
