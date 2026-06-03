# Model Routing

## Default Strategy

Video Studio is **zero-paid by default**. A provider that can create billable
usage is not selected unless the operator explicitly sets:

```powershell
VIDEO_STUDIO_ALLOW_PAID_PROVIDERS=1
```

The normal automation path is:

1. Plan scenes with Gemini when a free key is available, otherwise use the
   deterministic sample planner fallback.
2. Prefer uploaded visuals, Pexels/Klipy free stock, local Wan, or local
   placeholder cards.
3. Use Edge TTS first, then Windows Speech fallback.
4. Compose with local FFmpeg.

## Zero-Paid Provider Policy

`worker/media/provider_policy.py` owns the shared policy.

Default allowed preferences:

```text
image: gemini-flash
video: wan
tts:   edge-tts -> windows-tts
bgm:   local-bgm
sfx:   local-sfx -> freesound
```

Blocked by default:

```text
serper, imagen, veo3, runway, elevenlabs, openai-tts, suno
```

`/api/health` exposes:

- `zero_paid.mode`
- `zero_paid.paidProvidersAllowed`
- `provider_policy`
- per-adapter `media` diagnostics

## Provider Categories

### Image

| Provider | Key | Default | Notes |
|----------|-----|---------|-------|
| Gemini Flash Image | `gemini-flash` | allowed | Free-tier image generation when a free Google key is configured |
| Pexels Image | `pexels-image` | allowed as stock fallback | Free API key; stock, not AI generation |
| Klipy/Tenor-compatible GIF | `klipy` | allowed as reaction fallback | Free API key path |
| Serper Images | `serper` | blocked | Billable search API; opt-in only |
| Imagen 4 | `imagen` | blocked | Billable AI image generation; opt-in only |
| DALL-E 3 | `dalle3` | blocked | Billable AI image generation |

### Video

| Provider | Key | Default | Notes |
|----------|-----|---------|-------|
| Local Wan2.1 | `wan` | allowed | Local model adapter; command wiring is operator-owned |
| Pexels Video | `pexels-video` | allowed as stock fallback | Free API key; stock footage |
| Local LTX-Video | `ltx-video` | allowed | Local command adapter; useful for image/video-conditioned short clips |
| Local HunyuanVideo | `hunyuan-video` | allowed | Local command adapter; heavier open-source video path |
| Veo 3 | `veo3` | blocked | Billable AI video generation |
| Runway | `runway` | blocked | Billable AI video generation |

### Text-to-Speech

| Provider | Key | Default | Notes |
|----------|-----|---------|-------|
| Edge TTS | `edge-tts` | allowed | Free network TTS |
| Windows TTS | `windows-tts` | allowed | Local Windows fallback |
| ElevenLabs | `elevenlabs` | blocked | Billable TTS |
| OpenAI TTS | `openai-tts` | blocked | Billable TTS |

### Audio

| Provider | Key | Default | Notes |
|----------|-----|---------|-------|
| Local BGM | `local-bgm` | allowed | Files under `assets/bgm/` |
| Local SFX | `local-sfx` | allowed | Local library path |
| Freesound | `freesound` | allowed | Free API key path |
| Suno | `suno` | blocked | Billable/uncertain AI music path |

## Grok / Groq Clarification

- `GROQ_API_KEY` in this repo is **Groq**, an LLM API used by text helpers.
- xAI **Grok** video generation is not wired into this repo by API because the
  official Grok Imagine Video API is priced per generated second.
- If the operator wants Grok-created video while preserving this repo's
  zero-paid API posture, use the operator-approved browser handoff: export a
  dashboard handoff packet, open the generated worksheet, copy prompts into
  Grok Imagine with the signed-in browser session, then either save MP4s to the
  packet `incoming` folder or use the approval-gated Downloads-folder importer.
  Sync those files back as server-side scene assets.
- The dashboard can also run an approval-gated local browser prompt injector:
  `POST /api/grok-handoff/<projectId>/browser-automation` attaches to or
  launches Chrome/Edge with a local DevTools port, injects the selected scene
  prompt into Grok Imagine, and can request generation, click an explicit
  download control, watch the approved Downloads folder, and import MP4s only
  when the operator sends the separate `generatePromptApproved`,
  `downloadResultApproved`, and `watchDownloadsApproved` flags. Grok UI login,
  captcha, payment, or safety interstitials remain manual stop points. This
  keeps Video Studio responsible for subtitles, BGM, editing, render, and upload
  review without storing Grok API keys/passwords or calling the paid API. Any
  browser profile/cookie persistence requires explicit operator approval.

## Local Video Command Handoff

Wan/LTX/Hunyuan are exposed as local command adapters, not cloud APIs. The
dashboard scene panel can call:

```text
POST /api/local-video/generate-scene
```

with `operatorApproved=true`, a scene prompt, and provider `wan`, `ltx-video`,
or `hunyuan-video`. The bridge writes a per-scene prompt file, request JSON, and
command log under `storage/local-video/<project>/<scene>/`. If the operator has
configured `<PREFIX>_MODE=command` plus `<PREFIX>_COMMAND`, the command is run
and the generated MP4 is returned as a server-side scene asset. If the adapter
is still `stub` or misconfigured, the dashboard shows the request path and
diagnostic detail instead of silently falling back to a still-image slideshow.

For one-off local runs without editing `.env`, the same route accepts
`commandOverrideApproved=true` plus `commandTemplate` as a JSON string array.
The dashboard exposes this as a per-scene override box. The template supports
the same placeholders as env commands, including `{prompt_path}`,
`{output_path}`, `{request_path}`, `{scene_id}`, `{duration_sec}`, and
`{project_root}`. This is still zero-paid and local-only; it runs only after
the operator clicks the approved local generation button for that scene.

This keeps the no-paid default intact: Codex does not install model runtimes or
write `.env`; the operator owns local model setup and grants the per-run
approval from the dashboard.

## Verification

Use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-render.ps1
```

These checks confirm zero-paid health metadata, local route decisions,
project bundle save, local media reports, and FFmpeg MP4 output.
