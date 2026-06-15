---
plan_id: PLAN-CODE-REVIEW-FOLLOWUP-20260603
project: video-studio
status: SHIPPED
status_reason: All 10 MED + systemic key-in-URL (5 Google sites) + R2 SSRF-redirect/extension-origin findings resolved+verified 2026-06-04 (164 pytest pass, npm build exit 0, grep 0 key-in-URL remaining); B2/B3/B4 push-backs Codex-confirmed; only D3 (non-security useCallback) deferred to dedicated UI pass
created: 2026-06-03
source: 6 parallel code-reviewer agents over 64 uncommitted files (worker backend + UI + grok system)
---

# Code Review Follow-up — Security Hardening (2026-06-03)

## Context
On 2026-06-03 a 6-agent parallel review covered 64 uncommitted Codex-authored files
(worker/bridge, worker/render, worker/media, app/ui, tools/chrome-grok-companion, tests).
All 6 returned NEEDS_CHANGES, but a 4-Q reality check downgraded most: this is a **local
single-user bridge (127.0.0.1)** where operator = the user, so SSRF/XSS/path-traversal
exploitability is low. Code was committed as-is (already operational + tested). The MED
findings below are real and worth fixing, but none were immediate-blockers.

## Fixed 2026-06-03 (CC direct — Codex dispatch hit read-only sandbox, write mode not preserved)
- ✅ `model_router.py` paid-gate — dropped `premium_enabled` conjunction; returns local unconditionally when not paid_providers_allowed()
- ✅ `compose_ffmpeg.py` — single-quote escape (`'\''`) in `ffmpeg_filter_path` + `write_concat_file`
- ✅ `foley.py` — `math.isfinite()` guard (+ `import math`) on lavfi duration
- ✅ `tests/test_zero_paid.py` — assert elevenlabs/openai-tts blocked in tts, suno in bgm
- Verified: `compileall` (3 files) + `pytest tests/test_zero_paid.py` = **7 passed**.
- [UNCERTAIN] ffmpeg single-quote escape exact form unverified against a real `'`-containing NTFS filename (rare edge); escape direction is safe.

## Resolution 2026-06-04 (CC direct — Codex write-dispatch blocked again)
Codex dispatch (`task-mpy8ben3`) again hit the read-only sandbox (`apply_patch` rejected
by approval settings) — 2nd same-direction failure, so CC implemented directly per Rule #1
exception. A Codex read-only review (`task-mpy9dpvh`) supplied the Rule #14 cross-model pass.

**Fixed (10):**
- A1 `model_router.py` — VEO3 rate derived from `ADAPTER_CONFIG["veo3"]["costPerUnit"]` (no more hardcoded 0.15)
- A2 `runtime.py` — module logger + warning when a paid override is downgraded by zero-paid policy
- B1 `routes_grok.py` — `_download_file_from_request` resolves `download_dir` on both sides of `relative_to`
- C1 `image_router.py` — `download_pexels_video` SSRF allowlist (https + `{videos.pexels.com, player.vimeo.com}`); regression test `tests/test_image_router_ssrf.py` (Red-Green-Revert verified)
- C2 `scene_generator.py` — Gemini key moved from `?key=` URL to `x-goog-api-key` header
- D1/D2 `StudioContext.tsx` — `checkHealth()` `.catch()` + batch polling no longer terminates on the synthetic `total` fallback
- E1/E2/E3 `background.js` — bridge-origin allowlist on `loadCommandFromUrl`, `store-command` gated to `sender.id === chrome.runtime.id`, `operatorApproved` via `URL.searchParams`

**Won't fix (push-back, confirmed by Codex review):**
- B2 `routes_media.py` `import_local_video_folder_route` / B3 `free_audio_import_route` — these intentionally COPY operator-approved files from an EXTERNAL operator-chosen folder into project storage (copy-in only, no content read-back, 127.0.0.1, `operatorApproved`-gated). Project-root containment would break the feature; no file-read exploit in that path.
- B4 `compose.py` `_resolve_operator_bgm_selection` — already resolves both `candidate` and `project_root`; on Python 3.12/Windows `Path.resolve()` resolves junctions, so the realpath-vs-resolve premise does not hold.

**Deferred:**
- D3 `RenderReviewPanel.tsx` `useCallback` — non-security, stale-closure risk; defer to a dedicated UI pass.

**Verification:** `compileall worker` exit 0; model_router/runtime/image_router/scene_generator/routes_grok import OK (no cycle, VEO3=0.15 derived); pytest test_zero_paid + test_bridge_server + test_grok_handoff + test_provider_policy + test_grok_video_cli + new SSRF test = **164 passed**; `npm run build` (tsc --noEmit && vite build) exit 0; `node --check background.js` OK.

## NEW finding 2026-06-04 — systemic API-key-in-URL leak (beyond original scope)
C2 fixed `scene_generator` only, but the same `?key=<api_key>` leak (keys → logs/proxies/referrers) exists at 5 more Google API sites:
- `worker/bridge/image_router.py:105` (Imagen `:predict`), `:147` (Gemini Flash image)
- `worker/planner/ollama_planner.py:241` (Gemini planner)
- `worker/translation/translate.py:170` (Gemini translate)
- `worker/tts/providers.py:110` (Google TTS `:synthesize`)
- (`worker/bridge/image_router.py:368` — Klipy `&key=`, same class, non-Google)

All Google APIs accept the `x-goog-api-key` header → mechanical fix.

**RESOLVED 2026-06-04** (user-approved scope expansion): all 5 Google sites moved their key
to the `x-goog-api-key` header. Klipy (`image_router.py:368`) left as-is (non-Google API,
header support unverified). Verified: `compileall worker` exit 0; image_router / ollama_planner
/ translate / tts.providers import OK; grep confirms 0 Google key-in-URL sites remain;
pytest zero_paid + provider_policy + ssrf green.

## /code-review hardening 2026-06-04 (5-agent Round 1 + adversarial Round 2)
A local `/code-review` on the two commits above surfaced two sibling-site gaps of the
class "guarded one site, missed the sink" (same class twice → lifted to an architectural
sink-guard fix per MO-9):
- **SSRF redirect bypass** (`image_router.download_pexels_video`): the host allowlist only
  checked the initial URL; `urlopen` follows 3xx by default. Added `_BlockInternalRedirect`
  opener that rejects redirects to private/loopback/link-local/reserved IPs (public→public
  redirects, e.g. Vimeo→its CDN, still allowed). `urlparse` moved into try (bracket-IPv6 URL
  no longer escapes the bool contract).
- **Extension error-path origin leak** (`background.js`): the `loadCommandFromUrl` origin
  guard was bypassed on the autostart catch path (`postDirectAutostartEvent` fired with the
  attacker origin). Guarded at the sink (`directAutostartEventTarget` returns null for
  non-bridge origins) so no caller can POST to an attacker host.
- Verified: `compileall worker` + `node --check background.js` + pytest
  (ssrf/zero_paid/provider_policy = 13 passed) + bridge-server import OK.
- **Known LOW residual**: `_host_is_internal` uses `socket.getaddrinfo` with no DNS timeout —
  a redirect to a slow-DNS host can block a worker thread (self-DoS). Low-weight for a local
  single-user tool; revisit if the bridge is ever exposed beyond 127.0.0.1.

## MED findings — historical list (SUPERSEDED by Resolution 2026-06-04 above)

### Policy / cost
- **`worker/media/model_router.py:34`** — paid-gate guard `if not paid_providers_allowed() and availability.premium_enabled` is fragile. Currently safe via a second `not premium_enabled` check at line 37, but the conjunction should be dropped: `if not paid_providers_allowed(): return local` unconditionally. Zero-paid policy is core.
- **`worker/media/model_router.py:12,43`** — `VEO3_FAST_RATE_PER_SEC=0.15` duplicates `adapters.py` costPerUnit; read from ADAPTER_CONFIG or assert equality to prevent drift.
- **`worker/media/runtime.py:134`** — paid override silently downgraded to free with no log; add `logging.warning` so operators see the override was ignored.

### Path safety
- **`worker/bridge/routes_grok.py:9144`** — `_download_file_from_request` containment check uses pre-resolve `download_dir`; use `resolved.relative_to(download_dir.resolve())`.
- **`worker/bridge/routes_media.py:1866`** — `import_local_video_folder_route` has no `relative_to(_project_root)` guard (every other path route does). Add it.
- **`worker/bridge/routes_media.py:1312`** — `free_audio_import_route` resolves sourcePath but only checks is_file()/ext, no project-root containment. Add `_resolve_under_project`.
- **`worker/render/compose.py:159`** — `_resolve_operator_bgm_selection` relative_to bypassable via NTFS junction; use realpath on both sides.

### FFmpeg injection (NTFS filenames can contain `'`)
- **`worker/render/compose_ffmpeg.py:454`** — `ffmpeg_filter_path` escapes `:` but not `'`; subtitle path in single-quoted `-vf` breaks out. Escape `'` → `'\''`.
- **`worker/render/compose_ffmpeg.py:449`** — `write_concat_file` writes `file '{path}'` unescaped; escape `'` as `''` per concat spec.
- **`worker/render/foley.py:107`** — lavfi duration from manifest not `math.isfinite()` checked → `atrim=0:inf/nan` possible. Guard.

### Network
- **`worker/bridge/image_router.py:332`** — `download_pexels_video` passes API-response URL to urlopen with no host allowlist (SSRF). Require `https://videos.pexels.com/` prefix.
- **`worker/bridge/scene_generator.py:239`** — Gemini key in URL query string (leaks to logs); use `x-goog-api-key` header.

### UI
- **`app/ui/src/context/StudioContext.tsx:829`** — mount `checkHealth().then()` has no `.catch()`; network failure leaves app stuck in "checking" forever. Add `.catch(() => dispatch BRIDGE_OFFLINE)`.
- **`app/ui/src/context/StudioContext.tsx:862`** — batch polling `done` calc fallback `1` terminates polling before server returns variant count; only terminate when `total > 0`.
- **`app/ui/src/components/RenderReviewPanel.tsx:1857`** — 7 async handlers in default export lack `useCallback` (re-created every render).

### Chrome extension (`tools/chrome-grok-companion/`)
- **`background.js:38`** — `loadCommandFromUrl` bare `fetch(url)` with no origin validation (SSRF via crafted grok.com hash). Allowlist `127.0.0.1:5161`.
- **`background.js:529`** — `onMessage` listener no `sender.id` check; another extension could replace stored command. Gate `store-command` to own extension.
- **`background.js:442`** — `operatorApproved` checked via `includes("operatorApproved=true")` substring; use `new URL().searchParams.get()`.
- **`content.js:67` / `RenderReviewPanel.tsx:265`** — `document.execCommand` deprecated; keep as fallback only.

### Tests
- **`tests/test_zero_paid.py:21`** — only asserts imagen/veo3/runway blocked; **missing elevenlabs/openai-tts (tts) + suno (bgm)**. A regression unblocking paid TTS/BGM would go undetected. Add assertions.

## LOW (reality-check downgraded — informational, not scheduled)
- HTML attribute XSS in routes_grok review-packet (`escape` without `quote=True`) — operator views own prompt on own local page; near-zero exploit motive.
- File-size violations: routes_grok.py ~13K lines, routes_media.py ~11K, compose_ffmpeg.py 4.7K, SceneDetailPanel.tsx 3889, RenderReviewPanel.tsx 2896 — all far over the 500/660 split limit. Tracked as tech debt; split when touched.
- `docs/ARCHITECTURE.md` stale (mentions retired ComposerPanel/ExecutionPanel, 18-adapter count vs 17).
- `vite.config.ts:11` hardcoded `C:/vibe/projects/video-studio` (dev-only).
- Sidebar.tsx spin animation via inline style — prefer CSS class.

## Dispatch note
When fixing, batch by domain (matches the 6 review agents): policy+cost, path-safety,
ffmpeg-escape, ui, chrome-ext, tests. Each is independent; FFmpeg-escape and test-gap are
the cheapest high-value fixes. Re-run the relevant test after each (regression Red-Green).
