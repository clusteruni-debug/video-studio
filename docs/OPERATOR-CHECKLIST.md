# Operator Checklist

## What Codex Can Do
- scaffold the project
- write the UI, worker, and routing code
- prepare local scripts and config samples
- wire together local and zero-paid provider adapters
- add verification commands and smoke checks

## What You Must Do Manually
- install local tools on the machine
- create free provider accounts if you want optional stock/API fallbacks
- store API keys in local environment variables
- decide whether any paid provider is allowed; default is no

## Step-by-Step

### 0. Human-Mode First Run

Start with Demo Mode before configuring optional providers.

- Run `npm run bridge`.
- Run `npm run dev`.
- Open `http://127.0.0.1:5160`.
- On Home, check `Human operator P0`.
- Confirm `GET /api/human-operator/status` reports setup, demo, provider,
  source, render, phone review, publish packet, and operator blocker summaries.
- Prepare the no-LLM demo packet.
- Run the demo render from Edit.
- Accept source proof from Sources.
- Record phone review from Review.
- Inspect the publish packet blockers before any upload.

Claude Code, Codex, Gemini, Grok, CapCut automation, and paid providers are not
runtime requirements for this first path.

### 1. Machine Prep
- install or keep Python 3.14 x64
- install FFmpeg and ensure `ffmpeg -version` works
- keep enough free disk space for model weights and cache

For this project, "installed" is not enough. The tools must also be callable from the shell that runs the app. Verify:
- `npm run bridge`
- `ffmpeg -version`

If `ffmpeg` is installed via WinGet, the bridge may resolve it from the WinGet link location even when a plain shell `where ffmpeg` result is inconsistent. Trust the bridge health output over PATH-only checks.

### 2. Zero-Paid Quick Start
Do not set `VIDEO_STUDIO_ALLOW_PAID_PROVIDERS`.

With only local tools, the tool can render through:
- uploaded visuals or placeholder scene cards
- Edge TTS / Windows TTS narration
- local BGM from `assets/bgm/`
- FFmpeg composition with xfade transitions

With optional free keys, it can also use:
- Gemini Flash Image for free-tier image generation
- Pexels/Klipy/Freesound stock fallbacks

Provider readiness is visible at:

```text
GET /api/human-operator/provider-readiness
GET /api/human-operator/adapter-command-readiness
GET /api/human-operator/worklist
```

Optional providers must not block Demo Mode.

Set these in your environment or `.env`:
```
VIDEO_STUDIO_GEMINI_FLASH_MODE=command
VIDEO_STUDIO_GEMINI_FLASH_COMMAND=["python", "scripts/gemini_flash_image.py", "--prompt-path", "{prompt_path}", "--output-path", "{output_path}"]
VIDEO_STUDIO_EDGE_TTS_MODE=command
VIDEO_STUDIO_LOCAL_BGM_MODE=command
```

See `.env.example` for full command templates.

### 3. Provider Setup by Category

#### Image Providers
| Provider | Env Var | Setup |
|----------|---------|-------|
| Gemini Flash Image | `GEMINI_API_KEY` | Optional free-key image generation |
| Pexels/Klipy | provider API key | Optional free stock fallback |
| Imagen 4 | `GEMINI_API_KEY` + `VIDEO_STUDIO_ALLOW_PAID_PROVIDERS=1` | Paid; blocked by default |
| DALL-E 3 | OpenAI key + paid opt-in | Paid; blocked by default |

#### Video Providers
| Provider | Env Var | Setup |
|----------|---------|-------|
| Local Wan2.1 | `VIDEO_STUDIO_WAN_MODE=command` | Requires HF model download |
| Local LTX-Video | `VIDEO_STUDIO_LTX_VIDEO_MODE=command` | Requires local LTX runtime or ComfyUI workflow |
| Local HunyuanVideo | `VIDEO_STUDIO_HUNYUAN_VIDEO_MODE=command` | Requires local Hunyuan runtime; expect heavier GPU needs |
| Pexels Video | `PEXELS_API_KEY` | Optional free stock fallback |
| Veo 3 / Runway | provider key + paid opt-in | Paid; blocked by default |

#### TTS Providers
| Provider | Env Var | Setup |
|----------|---------|-------|
| Edge TTS | (none needed) | `pip install edge-tts`, free |
| Windows TTS | (none needed) | Windows only, built-in |
| ElevenLabs | `ELEVENLABS_API_KEY` + paid opt-in | Paid; blocked by default |
| OpenAI TTS | `OPENAI_API_KEY` + paid opt-in | Paid; blocked by default |

#### BGM Providers
| Provider | Env Var | Setup |
|----------|---------|-------|
| Local library | (none needed) | Place .mp3/.wav in `assets/bgm/` |
| Suno | `SUNO_API_KEY` + paid opt-in | [UNCERTAIN] Paid/unstable API; blocked by default |

### 4. Cost Management
- Default mode is zero-paid. Billable routes are not selected.
- Paid routes require `VIDEO_STUDIO_ALLOW_PAID_PROVIDERS=1`.
- Keep `.env` edits manual-only; Codex does not write secrets.
- `/api/health` should show `zero_paid.paidProvidersAllowed=false`.

### 4-a. Grok Non-API Handoff
- `GROQ_API_KEY` is Groq, not xAI Grok.
- Do not wire xAI Grok Imagine Video by API for this objective; the official
  video API is paid per generated second.
- To use Grok UI output without paid API integration: create a Grok handoff
  packet from the dashboard, open the generated operator worksheet, copy each
  prompt into Grok Imagine in the operator-approved browser session, generate
  per-scene clips, then either save the MP4s into the packet `incoming` folder
  or confirm the dashboard's prefilled local Downloads folder path and click
  `Downloads 가져오기`.
  The importer copies approved `.mp4` files into `incoming` with scene-stable
  names, then `MP4 동기화` attaches those files as scene assets for
  subtitle/BGM/render.
- For stronger automation, click `승인 생성+감시` only after approving local
  browser control and confirming an absolute Downloads folder path. This uses a
  local Chrome/Edge DevTools session on `127.0.0.1`, injects the selected scene
  prompt into Grok Imagine, then uses separate approvals to request generation,
  click an explicit video download control, watch the folder, and import MP4s.
  The dashboard also sends an approved login/cookie wait window. It may click
  the login entrypoint and a likely cookie reject/decline control, but it does
  not click "accept all" and does not handle credentials. If Grok shows login,
  captcha, payment, or safety screens, keep the opened browser in front and
  complete that operator-owned step. Video Studio will keep checking readiness
  during the approved wait window, up to 7200 seconds when explicitly approved,
  and resumes prompt injection automatically when the prompt field is ready.
  If Video Studio has to launch Chrome/Edge, `profileApproved=true` is required
  because that browser profile may persist the Grok sign-in session. Grok login,
  captcha, payment, or safety gates still require operator intervention.
- `로그인 Chrome attach` is intentionally attach-only. Use it only after you
  have already started a local Chrome/SuperGrok DevTools session on
  `127.0.0.1:9222`. Video Studio will not launch the default Chrome profile,
  copy cookies, or store credentials. On Chrome 136+ a normal already-running
  default profile usually will not expose CDP; if attach fails, use the
  isolated Video Studio Grok profile and sign in to the same Google/SuperGrok
  account there once.
- `기존 Chrome 열기` is the default path when the operator already has
  SuperGrok available in their normal Chrome profile. It does not use CDP or
  launch Edge; it opens `grok.com/imagine` with Chrome, copies the scene prompt
  to the clipboard, then relies on `Downloads 가져오기` / `감시+채널 패킷` to
  import the MP4 after the operator generates and downloads it.
- For manual batch upload, exact file names are helpful but not required. If
  Grok downloads generic file names, select the MP4 files together in scene
  order; Video Studio maps unnamed batch uploads by selected file order and
  still preserves each file as a candidate for operator review.
- `Chrome 확장 안내` is the stronger logged-in Chrome automation path. It
  opens `/api/grok-handoff/<projectId>/chrome-extension`, copies the current
  scene command URL, and points the operator to
  `tools/chrome-grok-companion`. Load that folder as an unpacked extension in
  the already signed-in Chrome profile, then use the extension popup to fetch
  the scene prompt, fill Grok Imagine, click Generate, and report/download
  candidates back to the local bridge. This avoids Edge, new browser profiles,
  paid xAI API calls, default-profile CDP, copied cookies, and credential
  storage. Login/captcha/payment/safety prompts and final clip choice remain
  operator-owned.
- If the companion status stays `not-seen`, run
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\grok-companion-prepare.ps1 -ProjectId <project-id> -SceneId <scene-id> -OpenGuide -CopyToClipboard`.
  The script only opens the existing Chrome profile's guide/extension pages and
  copies the extension path plus Prep+Generate URL. To relaunch Chrome with the
  unpacked extension, the operator must explicitly add
  `-RelaunchChromeWithCompanion -CloseChromeApproved`; the script attempts a
  graceful close and refuses to force-close Chrome.
- If `-StartCdpChrome` is used and Video Studio shows a Google login screen
  even though normal Chrome is already signed in, inspect the Chrome process
  path first. The signed-in profile path must remain `Google\Chrome\User Data`;
  a broken launch that splits the space into `Google\Chrome\User` plus a stray
  `Data` argument is a separate empty profile. The prep script now refuses that
  stale CDP session unless the operator explicitly approves relaunch with
  `-CloseChromeApproved`.
- The handoff stores prompts, expected file names, and local MP4 paths only. It
  does not store Grok API keys or passwords and does not call the paid xAI API.
  Any browser profile/cookie persistence is explicit operator-approved browser
  state, not an API credential.

### 5. Local Paths to Prepare
- choose a stable model cache root, for example `C:\AI\models`
- render outputs go to `storage/renders/<project-id>/`
- scene asset files selected in the browser are copied into `storage/inputs/<project-id>/uploads/` when save/render triggers
- save writes `storage/cache/<project-id>/local-media-plan.json`
- render writes `storage/renders/<project-id>/local-media-report.json`
- local model scene runs write prompt/request/log/output packets under `storage/local-video/<project-id>/<scene-id>/`
- final packet save writes `storage/final-videos/<project-id>/` with the MP4, `publish-checklist.md`,
  `quality-checklist.md`, `quality-audit.json`, review frames/contact sheet when FFmpeg can extract them,
  and audio-level evidence when FFmpeg can measure it.
- If final packet save is rejected because publish/channel gates fail, Video
  Studio does not copy the MP4 into `final-videos`; it writes
  `blocked-quality-audit.json` beside the render output so the operator can
  inspect the exact required fixes and evidence that prevented promotion.
- Render QA also writes `sourceMotionEvidence` by running FFmpeg freeze detection
  against readable source MP4s. If a scene source is detected as near-frozen,
  `movingClipPriority` fails so a still-image/slideshow-looking MP4 cannot pass
  the production gate just because it has a `.mp4` extension.
- The render review panel separates `Publish gate`, `Channel gate`, and
  `Top-tier AI-assisted gate`. A stock-only or direct-upload packet can be
  publish-ready, but it is not top-tier AI-assisted ready until the first hook
  has reviewed Grok app/web or local Wan/LTX/Hunyuan MP4 evidence.

### 5-a. Approved Automation Direction
- Preferred Grok path is approval-gated automation, not a purely manual copy/paste loop.
- The operator approves local browser control, profile persistence, login/cookie wait, generation click,
  download click, and folder watch/import separately from inside the dashboard.
- Video Studio may automate prompt injection, Grok Imagine generate/download controls, local Downloads
  watch, scene MP4 import, scene asset sync, render, and final packet QA.
- Grok CDP automation reuses an existing Grok Imagine or Grok sign-in browser
  tab before opening a new one, so repeated approved retries should not keep
  stacking duplicate login tabs.
- Video Studio must stop at account login, captcha, payment, safety, or other identity/consent screens.
  Complete those in the opened Grok browser session, then let the approved wait/resume flow continue.
- The final packet's `quality-audit.json` records whether the result is merely upload-ready or has Grok/local
  AI hero evidence strong enough to claim a higher YouTube AI-assisted production tier.
- Each approved Grok browser run writes `automation-status.json` in the handoff packet. If login/captcha/payment
  interrupts the run, the dashboard status survives reload and tells the operator to finish that browser step,
  then rerun the same approved generate/download/watch flow.
- Non-preflight Grok browser runs also write `automation-request.json` with sanitized replay settings such as
  scene id, timeouts, approvals requested, and the local Downloads path. It never stores credentials and still
  requires fresh operator/browser approval before `승인 재개` or `/resume-automation` replays the request.
- The dashboard `작업 시트`, `Grok 열기`, and `승인 자동 생성`
  controls now auto-create the local handoff packet when needed. The operator
  can approve automation from the scene panel without first completing a
  separate manual packet step.
- When `grokMainSourceRequired=true`, the handoff packet auto-expands support
  scenes into Grok generation targets until the Grok-main accepted-scene floor
  is reachable. This prevents a stock-heavy draft from blocking immediately
  just because only one scene was originally marked `grok`; the operator still
  has to import, review, and accept the generated MP4s before render.
- For longer Grok login windows, use `승인 자동 생성` or
  `POST /api/grok-handoff/<projectId>/background-automation`. It starts the
  saved generate/download/watch replay in a background thread, writes
  `automation-job-status.json`, and keeps polling while the operator completes
  Grok login/captcha/payment/safety steps in the opened browser. When the
  prompt input becomes available, Video Studio resumes prompt injection,
  generation, download watch, and MP4 import without another dashboard click.
  If the operator clicks the background action again while that wait is still
  active, the bridge returns the existing job instead of treating the click as
  a hard failure. The status surface includes worker liveness, elapsed wait
  time, remaining approved auth wait, and whether restart is available.
  Multi-scene Grok packets also expose `nextMissingSceneId`,
  `missingSceneIds`, and `rejectedSceneIds`; use `다음 씬 자동 생성` to queue
  the next missing or rejected Grok scene without manually hunting through the
  storyboard.
  The dashboard polls queued/running background jobs every few seconds; once
  imported MP4s appear in the handoff status, it syncs them into the scene
  asset state automatically so the next operator step is clip review and
  channel render, not another manual `MP4 동기화` click.

### 5-b. Local Video Command Automation
- Pick `Wan`, `LTX`, or `Hunyuan` in the scene source switcher.
- Edit the handoff prompt so it describes camera motion, subject continuity,
  lighting, and the no-text/no-logo/no-watermark constraints.
- Click `승인 로컬 생성`. The bridge requires that click as the operator
  approval before running any configured local command.
- To run a local model without editing `.env`, paste a one-time command JSON
  array into the scene's command override box before clicking `승인 로컬 생성`.
  Example shape: `["python","scripts/run_wan.py","--prompt-path","{prompt_path}","--output-path","{output_path}"]`.
  The bridge requires `commandOverrideApproved=true` internally and writes the
  command preview/request/log as provenance for the generated MP4.
- If the adapter is ready, the MP4 is attached to the scene as a server-side
  asset and can be previewed before render.
- If it is still `stub`, use the shown prompt/request/log paths to wire the
  local command, then rerun the same scene.

### 5-c. Korean YouTube Template Families
Use template variety deliberately. A finished channel packet should name one
template family and keep the visual/audio choices consistent instead of reusing
one generic slideshow layout.

| Template | Best source mix | Layout rule | Free asset path |
|----------|-----------------|-------------|-----------------|
| `authentic_vlog` | direct upload first, Pexels/Pixabay support B-roll | full-frame motion, lower-info or no caption, ambient-first pacing | operator footage, Pexels/Pixabay video, YouTube Audio Library or Mixkit BGM |
| `persona_story` | Grok app/web MP4 or local Wan/LTX/Hunyuan hero | same character/place/prop bible, top hook only for first beat | Grok/SuperGrok browser handoff, local model output, Pexels texture inserts |
| `kculture_fandom` | copyright-safe substitutes, fan/event footage only when rights are clear | beat-friendly safe-zone callouts, no oversized center captions | direct event footage, CC/stock city/stage B-roll, YouTube Audio Library/Mixkit/Pixabay music |
| `podcast_clip` | owned long-form audio/video or TTS summary | speaker crop/waveform/chapter-card, lower captions only when needed | owned source clip, generated chapter card, Freesound SFX, YouTube Audio Library bed |
| `longform_deep_dive` | chapter cards, operator-made data/source cards, evidence B-roll | slower chapter/title rhythm, lower facts, no Shorts-style giant captions | direct graphics, Wikimedia/Pexels/Pixabay evidence media, YouTube Audio Library/Mixkit BGM |
| `interview_documentary` | owned interview/location footage first, TTS summary only when audio rights are absent | speaker/hands/location proof, compact lower captions away from faces | direct interview MP4, Freesound ambience, Wikimedia/Pexels context |
| `live_recap` | direct event footage first, rights-safe venue/city/stage-light B-roll | route/point chapter chips, small safe-zone callouts | direct phone MP4, Mixkit/Pexels/Pixabay context, YouTube Audio Library BGM |
| `news_explainer` | Pexels/Pixabay/Wikimedia context cuts plus original narration | top hook then small lower facts, no stock-only hero claim | Pexels/Pixabay/Wikimedia Commons with source URL/ID/license note |
| `ranking_list` | distinct clip per rank, no repeated stock loop | stable rank label, quick but not random cuts | Pexels/Pixabay candidates, direct screenshots only with rights/permission |
| `tutorial_steps` | direct screen/hand footage preferred | step label at top, lower-info only for detail | direct capture/upload, CC0 icons/images only when provenance is stored |

For Korean Shorts, default to a visible first-two-second payoff, restrained
caption scale, and scene-specific movement. For long-form, avoid Shorts-style
giant captions: use chapter/title cards, lower explanations, and captions only
where they carry meaning.

Reference anchors used by the `Free asset packet` output:
- YouTube Korea Shorts workshop: Shorts can support richer multi-scene stories
  up to 3 minutes and tools such as timeline/sound-sync; do not treat a Short
  as a static image carousel.
- YouTube Korea 2025 trends: authenticity, K-culture context, and creator-led
  multi-format storytelling are stronger references than generic stock montage.
- YouTube Shorts editing tips: text and audio should clarify story/mood and
  accessibility, not become decorative center overlays.
- YouTube Audio Library: use Studio Audio Library as the safest default BGM/SFX
  source for YouTube uploads, with attribution copied when required.
- Pexels/Pixabay/Wikimedia/Mixkit/Freesound: use as manually reviewed free
  candidates with source URL, creator, license/attribution, and selection
  rationale captured per scene or audio asset.
- xAI Imagine docs/pricing: Grok API video generation is a paid path, so this
  repo only accepts operator-owned Grok app/web MP4 handoff.
- Wan/LTX/Hunyuan official repos: local/open-source video models are allowed
  as original-motion substitutes when hardware and local setup are available.

### 5-d. Free Asset Sourcing Rules
- Use the dashboard `Free asset packet` action before collecting clips. It
  writes both `storage/asset-packets/<projectId>/free-asset-sourcing-packet.json`
  and `storage/asset-packets/<projectId>/free-asset-sourcing-worksheet.md` so
  search URLs, chosen source proof, BGM sidecar checks, and repeat guards remain
  with the project instead of only living in the UI.
- Pexels Video: use candidate search, manually choose the scene-fit clip, and
  keep `sourceUrl`/ID/creator label. Do not auto-accept top-1.
- Pixabay: usable for images, videos, and music when the source URL and license
  evidence are stored with the packet.
- Mixkit: usable for free stock video/music/SFX, but keep the asset page/license
  note because some items have use limits by category.
- YouTube Audio Library: safest default BGM bed for YouTube uploads; record
  title/artist/attribution requirement in the operator notes.
- Freesound: use for short SFX only after checking the specific file license
  and attribution requirement.
- Free audio collection targets for Korean vlog/reset-routine edits:
  YouTube Audio Library (`calm`, `bright`, `lo-fi`, `ambient`, attribution not
  required), Mixkit (`vlog`, `lofi`, `chill`, `morning`, `ambient`), Pixabay
  Music/SFX (`city pop`, `night drive`, `light percussion`, `kitchen`, `city
  ambience`), Freesound (`kitchen room tone`, `subway station`, `soft
  footsteps`), ZapSplat (`apartment`, `city night`, `cloth`, `typing`), plus
  CC BY libraries such as Scott Buckley/Incompetech only when attribution is
  stored. Avoid BBC Sound Effects for monetized Shorts unless a commercial
  license is obtained.
- Audio loudness target: final Shorts renders should land near `-14` to
  `-16 LUFS` integrated with true peak at or below `-1 dBTP`; if `volumedetect`
  shows a very low max/mean after render, rerender with final loudness
  normalization before visual review.
- Local BGM library: every file in `assets/bgm/` must have a sidecar
  (`track.mp3.json`, `track.json`, or folder `sources.json`) with provider,
  source URL, and license/attribution text. Without this, the render quality
  report flags BGM provenance as incomplete.
- BGM rotation: each production mood should have at least two provenance-ready
  tracks. The render manifest records `candidateCount`, `selectionMood`,
  `selectionMethod`, and `selectionKey`; the final checklist flags weak
  `bgmAssetRotation` evidence when the pipeline would otherwise reuse a single
  default track.
- Wikimedia Commons: use only when the exact file license is compatible; record
  file URL, author, license, and required attribution.
- Reusing the same free asset in multiple scenes is a fail unless it is a
  documented visual callback. The render quality report now flags repeated
  visual identity from source URL, source ID, source path, output path, or prompt.
- Avoid copyrighted K-pop, drama, anime, broadcast, or music-video footage/music
  unless the operator owns rights. Use substitutes: original reaction footage,
  copyright-safe stage-light/city/fan-prop B-roll, CC-licensed stills, or local
  model/Grok-generated scenes.

### 5-e. Raised Quality Gate
- Previous smoke MP4s are not final-quality evidence. A final packet must have
  intentional audio design: natural viewer-facing narration when the format
  needs it, or an explicit no-voice / music-first plan for Grok/direct raw
  footage. Do not add explanatory TTS just to satisfy a gate.
- Every captioned scene needs a layout review note: subject visible, right/bottom
  Shorts UI danger zone clear, and lower-info kept within the safe zone.
- Every free stock scene and every BGM/SFX asset needs provenance, and repeated
  visual assets are flagged.
- Channel-ready is separate from top-tier AI-assisted. Top-tier evidence now
  requires Grok/local hero proof, audio-design proof, caption layout proof, asset
  diversity, free asset provenance, audio mix review, and Korean YouTube
  benchmark notes.

### 6. Verification Commands
```
npm run bridge          # start local Python bridge on port 5161
npm run dev             # build and serve UI on port 5160
ffmpeg -version         # confirm FFmpeg
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-render.ps1
```

### 7. Decisions to Send Back
Reply with status values only:
- `Python314`: done / not done
- `FFmpeg`: done / not done
- `Edge TTS`: done / not done
- `Wan local command`: done / not done
- `Optional free keys`: Pexels / Klipy / Gemini / Freesound
- `Paid providers`: no / yes
- `Priority`: speed / cost / quality

## Recommended First Budget Rule
- default mode: zero-paid only
- paid allowance: none
- Grok: operator-approved browser handoff, approval-gated generate/download/watch/import, and local MP4 sync only, not API integration
