# Video Studio AI Web Companion

Local Chrome extension for Video Studio's operator-approved Grok and Gemini
web handoffs. The extension is no longer the primary Grok production rail:
the default rail is Codex/Claude browser-control against the existing signed-in
Chrome/Grok tab, followed by operator-owned MP4 download/save and local
Video Studio import/upload.

Use it only in the Chrome profile where the operator is already signed in to
SuperGrok or Gemini. It avoids xAI/Gemini API calls, Chrome DevTools/CDP,
copied cookies, password storage, and Edge/new-profile launches.

Important Chrome 137+ note:

- Regular Google Chrome branded builds no longer reliably support loading
  unpacked extensions from the `--load-extension` command-line flag.
- For the existing signed-in Chrome profile, install this companion once through
  `chrome://extensions` with Developer mode enabled and `Load unpacked`.
- The command-line relaunch path is not the production path for SuperGrok. It
  can open Grok/guide pages, but it must not be treated as proof that the
  companion is active. Trust the Video Studio `companionConnection=connected`
  heartbeat before running Grok as the main source.
- Chrome for Testing or Chromium may still support `--load-extension`, but those
  are separate profiles and do not inherit the operator's SuperGrok login.

Grok video workflow:

1. In Video Studio, create a Grok handoff packet.
2. Use Codex/Claude browser-control in the existing signed-in Chrome profile.
   Do not switch to Edge, Chrome for Testing, or a new Chrome profile for
   production Grok generation.
3. Open the real Grok Imagine/generation surface in that same profile. A
   `https://grok.com/c/*` chat thread is not a successful generation surface.
4. Fill the Video Studio prompt and generate the raw 9:16 MP4 through the web
   UI. Login, captcha, safety, payment, and final clip choice remain manual.
5. The operator downloads/saves the MP4. Video Studio then imports from
   Downloads or explicit batch upload. Codex automation must not click Grok
   Download, Save, Export, or any Chrome native approval prompt.
6. Use the extension only as a fallback/diagnostic helper when browser-control
   is unavailable. Paste/load the command URL in the extension popup, then use
   `Prep + Generate` only after confirming the active tab is the real Grok
   Imagine composer.
   After a command has been loaded once, any Grok tab where the content script
   loads reports a companion heartbeat with the stored command, so Video Studio
   can distinguish "extension installed but idle" from "extension not connected".
   The background worker also sends a stored-command keepalive about once per
   minute, so a multi-minute Grok generation wait does not make the dashboard
   look disconnected while the signed-in Chrome path is still the main source.
7. If the fallback extension is used, `Import MP4` can be pressed after Grok
   finishes. When the companion can see a direct
   Grok `.mp4` URL from the page, a direct media tab, or the visible video's
   `currentSrc`, it fetches that MP4 inside the signed-in Chrome extension
   context and uploads it straight to the local Video Studio bridge. When Grok
   exposes only a visible high-resolution `blob:` video, the content script
   fetches that blob in the page context and uploads it to the same local
   `uploadEndpoint`. Both direct-import paths avoid Chrome's "ask where to save
   each file" download approval dialog.
   When the loaded command exposes a local `uploadEndpoint`, the primary
   `Import MP4` action does not automatically click Grok's page-level
   Download/Save/Export button if no direct `.mp4` URL is visible. It reports
   that manual fallback is required, so Chrome's save prompt is not opened by
   surprise.
   If Grok exposes only a low-resolution/proof-only on-page `blob:` video or
   direct import is not available, the extension stops and reports that manual
   batch upload is required. It does not click a temporary download anchor or
   open Chrome's download approval dialog.
   If Video Studio opens a direct `assets.grok.com/.../*.mp4#...` asset tab
   with the `download-asset` autostart hash, the companion background worker
   direct-imports through `uploadEndpoint` when available so direct media-document
   tabs do not depend on content-script injection. If the content script also
   sees the `download-asset` hash, it defers to the same background direct-import
   path and does not click a temporary `<a download>` link. Commands without a
   local `uploadEndpoint` are blocked on that content-script autostart path so
   Chrome's save prompt is not opened by surprise; explicit popup fallback still
   requires the operator to press `Import MP4`. If Chrome blocks the autostart
   path, make the asset tab active and press the companion `Import MP4` button;
   the companion treats the current MP4 tab URL as the import candidate even when
   the page has no inspectable video DOM.
8. Manual Downloads import/watch and batch upload are the production import
   path from Video Studio itself. The companion extension does not start browser
   downloads for Codex automation.
9. Optional: enable `Auto-prep next scene after MP4 import`. After each imported
   MP4 advances the queue, the extension loads the next missing scene command in
   the same signed-in Chrome profile and runs the same fill/generate action.
   The operator still owns final Grok clip choice, login/captcha/safety prompts,
   and the download action.

Guardrails:

- No paid xAI/Grok API integration.
- No credential, cookie, or token storage.
- No CDP or remote debugging against the default Chrome profile.
- Browser-control generation proof must use the existing signed-in Chrome
  profile. New profiles and Edge launches are not production proof.
- Auto-import reads only the completed Chrome download path and calls the local
  `127.0.0.1:5161` bridge with the current scene id and exact file path; the
  bridge rejects files outside the approved Downloads folder and does not upload
  the file to any external service.
- Direct MP4 import only posts the fetched video bytes to the local
  `127.0.0.1:5161` bridge for the already-loaded scene command. It does not
  call xAI APIs, store credentials, or write outside the handoff incoming
  folder.
- The companion never starts a Chrome browser download. Its `chrome.downloads`
  listener is only for observing an operator-owned manual download that has
  already completed outside Codex automation, so a native save/download prompt
  is not something the extension tries to create, wait on, or cancel.
- High-resolution blob-video direct import only reacts to the operator pressing
  the extension `Import MP4` button or an operator-approved autostart
  command. It fetches the visible `blob:` URL in the Grok tab context and posts
  the bytes only to the local Video Studio bridge.
- Blob-video download assist is disabled for low-resolution/proof-only
  candidates or commands without a local `uploadEndpoint`. The operator may
  still use manual batch upload outside the extension.
- Auto-queue is opt-in and only runs after a completed MP4 has been imported for
  the current scene. It does not call paid APIs, does not use Edge/new profiles,
  and does not bypass Grok UI prompts.
- Keepalive only reports the already-loaded local command back to the
  `127.0.0.1:5161` bridge. It does not inspect Grok content, click controls, or
  upload files; it exists so long Grok renders stay visible as an active
  operator-approved handoff rather than a stale connection.
- Login, captcha, safety, payment, and final clip selection remain manual.
- Video/animate mode detection is a best-effort UI heuristic. If the popup
  reports `mode=not-found`, set Grok to video generation manually before
  pressing Generate.

Quality operating rule:

- Treat Grok as the main visual source only after each imported/uploaded MP4 passes
  scene continuity review: same subject/prop/location/palette, visible motion in
  the first two seconds, no baked-in text/logo/watermark/UI, and no face/hand/body
  morphing. Reject weak clips in Video Studio instead of rendering around them.

Gemini image workflow:

1. Create an episode plan in Video Studio and open
   `/api/episodes/<episodeId>/browser-handoffs`.
2. Use each `gemini-web-image` cut `autostartUrl` in the same signed-in Chrome
   profile where this unpacked extension is loaded.
3. The Gemini content adapter loads the local command, fills the prompt, and
   records `gemini-prompt-fill` with `build=20260607-gemini-image-handoff`.
4. Generation, safety prompts, image choice, saving, and upload/review remain
   operator-owned. The Gemini adapter deliberately does not click Generate and
   does not import images until a provider-specific result surface is verified.

Gemini guardrails:

- No Gemini API integration, API key setup, copied cookies, or credential
  storage.
- The current Gemini adapter supports `fill-prompt` and `probe` only.
- Gemini/Veo video handoff remains `planned-only` until the browser surface and
  result import path are verified separately from paid API adapters.
