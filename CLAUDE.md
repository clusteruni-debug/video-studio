# Video Studio App

## Status
- Content automation tool with multi-provider media pipeline
- React + Vite + TypeScript UI using a shell + sidebar/canvas/bottom-bar flow with debug drawer and per-scene detail panel
- 18 provider adapters across 5 categories (image, video, tts, bgm, sfx)
- Free-first provider policy — zero-cost path works with Pexels (stock) + Edge TTS + local BGM; Imagen 4 ($0.02/img) for AI generation
- FFmpeg composition with Ken Burns motion, xfade transitions, gradient backgrounds, BGM mixing
- Local Python bridge with runtime tool probing, Ollama planning, scene-asset upload handling
- No DB or remote storage yet
- Windows-first desktop/web hybrid content production tool

## Target Stack
- UI: React + Vite (App shell + Sidebar/ImageCanvas/StoryboardPanel/BottomBar/DebugDrawer/SceneDetailPanel + shared utils)
- Desktop shell: Tauri 2 after the web UI stabilizes
- Planner: Gemini 2.5 Flash (primary) → hardcoded sample fallback. Ollama local LLM retired 2026-04.
- Image: Serper/Google Images (primary, $0.001/query), Gemini Flash (free AI, 500/day), Imagen 4 (AI fallback, $0.02/img), Pexels (free stock fallback), Klipy (free GIF/reaction)
- Video: local Wan (free), Veo 3 (Sora 2 retired 2026-04)
- TTS: Edge TTS (free default, +35% rate), ElevenLabs, OpenAI TTS
- BGM: Local mood-matched library (upbeat/tense/calm/cinematic, 16 tracks, MIT license)
- Composition: FFmpeg with motion presets + xfade transitions

## Runtime Model
- Windows default for local development and local model execution
- Optional WSL OpenClaw bridge for planning only; do not assume WSL can call the Windows app over localhost
- UI dev port: `5160`
- Local Python bridge port: `5161`

## Directory Map
- `app/ui/src/` — React frontend
  - `App.tsx` — state management shell
  - `components/Sidebar.tsx` — prompt, mode, engine, and history controls
  - `components/ImageCanvas.tsx` — generated-image gallery and batch progress
  - `components/StoryboardPanel.tsx` — scene cards + asset management
  - `components/BottomBar.tsx` — save/render/image action bar
  - `components/DebugDrawer.tsx` — bridge diagnostics, command previews, storage paths
  - `components/SceneDetailPanel.tsx` — selected-scene asset and provider override controls
  - `components/shared.ts` — shared types + utility functions
- `worker/planner/` — planning and routing adapters
  - `ollama_planner.py` — Gemini planner + sample fallback (filename historical; Ollama local LLM retired 2026-04)
- `worker/media/` — adapter registry, provider policy, cost estimation
  - `adapters.py` — 17 provider configs across 5 categories (Sora 2 retired 2026-04)
  - `provider_policy.py` — free-first selection + manual approval
  - `model_router.py` — per-scene cost breakdown
- `worker/render/` — FFmpeg composition
  - `compose.py` — orchestrator (compose_smoke_render + CLI)
  - `compose_ffmpeg.py` — FFmpeg primitives, subtitle writers, BGM/TTS helpers (split out 2026-04)
  - `motion.py` — Ken Burns zoompan presets
  - `transitions.py` — xfade + gradient background builders
- `scripts/` — provider adapter scripts (standalone, argparse-based)
- `shared/contracts/` — TypeScript/Python contract definitions
- `assets/bgm/` — local BGM library
- `storage/` — local generated inputs, cache, and renders

## Provider Adapter Scripts
- `scripts/pollinations_flux.py` — DEPRECATED (Pollinations dead since 2026-03, routes to Imagen 4)
- `scripts/edge_tts.py` — free cross-platform TTS
- `scripts/dalle3_image.py` — DALL-E 3 images
- `scripts/imagen3_image.py` — Imagen 3 images
- `scripts/veo3_video.py` — Veo 3 video
- `scripts/elevenlabs_tts.py` — ElevenLabs TTS
- `scripts/openai_tts.py` — OpenAI TTS
- `scripts/suno_bgm.py` — Suno BGM [UNCERTAIN API]
- `scripts/sora2_video.py` — REMOVED 2026-04 (Sora 2 retired; replacement research in `docs/VIDEO-PROVIDER-RESEARCH.md`)

## Usage Tracking
- Local SQLite DB at `worker/usage/usage.db` (gitignored) — tracks API calls, costs, tokens per session
- Image routing: Serper (Google Images) → Imagen 4 → Pexels fallback
- Usage stats endpoint: `GET /api/usage-stats` — session counts, limits, monthly cost totals
- Providers with no free tier (Imagen, Serper, Veo3, DALL-E, Sora) require confirmation dialog before use

## Current Constraints
- Package manager files are present; keep dependency changes explicit
- No DB or remote storage yet
- Required API keys: `GEMINI_API_KEY`, `PEXELS_API_KEY`, `SERPER_API_KEY`, `GROQ_API_KEY`
- FLUX/Wan default to `stub` mode until the operator sets command-backed adapter env vars
- Suno API adapter is marked [UNCERTAIN] — API surface may not be stable

## Logging
- Worker modules use ``logging.getLogger(__name__)`` (not ``print()``). Entry points (``worker.bridge.server``, ``worker.render.compose``) call ``logging.basicConfig`` honouring the ``LOG_LEVEL`` environment variable (default ``INFO``). CLI scripts under ``scripts/`` and ``_test()``/``main()`` JSON output paths keep ``print()`` so shell redirection and ``jq`` piping stay intact.
- Flask route handlers in ``worker/bridge/server.py``, ``routes_admin.py``, ``routes_media.py``, ``routes_sources.py`` keep broad ``except Exception`` with ``logger.warning`` + intent comment, because the handler must convert any downstream failure into a 500 response. ``image_router.py``, ``scene_generator.py``, ``translate.py`` narrow outbound HTTP+JSON errors via a shared ``_HTTP_ERRORS`` tuple.
- ``worker/bridge/vectcut_bridge.py`` is the single boundary to VectCutAPI. Its public wrappers (``add_image``, ``add_video``, ``add_subtitle`` …) intentionally catch broad ``Exception`` with ``logger.warning`` — see the module docstring for the rationale (VectCutAPI is an external project with an undocumented exception surface).

## Sora 2 Status (retired 2026-04)
Sora 2 was removed from the active provider pool following the ``memory/project-video-studio-ollama.md`` decision. The ``--sora2`` CLI flag on ``route_plan.py``/``save_plan.py``/``render_manifest.py`` and the ``ProviderAvailability.sora2`` field are retained as **deprecated no-ops** for backward compatibility with ``scripts/verify-*.ps1``, ``scripts/local-bridge.mjs``, and the ``app/ui/src/lib/planner.ts`` client-side planner. ``adapters.py`` no longer lists a ``sora2`` adapter, ``model_router.py`` no longer routes to ``"sora2"``, ``provider_policy.py`` video list excludes it, and ``runtime.py`` fallback chain is ``("wan", "veo3")``. ``scripts/sora2_video.py`` is deleted. Removing the UI, contracts, schema, and verify-script mentions is deferred to a coordinated React + TypeScript session.

## Verified Commands
```bash
npm run bridge
npm run dev
npm run build
npm run preview
python -m worker.planner.route_plan --prompt "sample prompt" --budget-mode free
python -m worker.planner.save_plan --prompt "sample prompt" --budget-mode standard
python -m worker.bridge.server
python -m worker.render.compose --project-id demo
python -m compileall worker
python -m compileall scripts
ffmpeg -version
ollama --version
```

## Local Run Flow
- Terminal 1: `npm run bridge`
- Terminal 2: `npm run dev`
- Browser: `http://127.0.0.1:5160`
- `npm run dev` runs the Vite HMR server on `127.0.0.1:5160`.
- Use `npm run build` followed by `npm run preview` when you need a static `dist/` check on port `4160`.
- Scene asset files are selected in the UI, held for the current browser session, and copied into `storage/inputs/<project-id>/uploads/` when the user saves or renders.

## Rendering Rules (MANDATORY)

> **`docs/RENDERING-SPEC.md`를 반드시 읽고 따른다.**
> render, subtitle, compose, bgm, layout 관련 코드를 작성하거나 수정할 때,
> RENDERING-SPEC.md의 수치와 다른 값을 사용하면 안 된다.

### Summary (details in RENDERING-SPEC.md)

**Safe Zones**
- Content safe zone: x=60~950, y=100~1440 (1080×1920 basis)
- Subtitle absolute prohibition: y>1536 (bottom 20%), x>950 (right 12%)
- Main subtitle position: Alignment=5 (center), MarginR=130

**Subtitles**
- ASS format, not SRT (FFmpeg `ass=` filter)
- Per-preset Style definitions: use RENDERING-SPEC.md §2.2 as-is
- Korean line break: max 16 chars/line, max 2 lines
- Karaoke highlight: faster-whisper word_timestamps → ASS color swap

**BGM**
- scene.emotion → BGM mood auto-matching (RENDERING-SPEC.md §4.1 table)
- Narration segments: BGM -18dB ducking
- Intro/outro: BGM -8dB + fade

**Background Material Priority**
1. User upload → 2. Pexels video → 3. Pexels image + Ken Burns → 4. Imagen → 5. Title card

**Verification**
- verify_render() must run after every render
- Check: resolution 1080×1920, audio stream exists, ASS file exists

## References
- `docs/ARCHITECTURE.md`
- `docs/MODEL-ROUTING.md`
- `docs/OPERATOR-CHECKLIST.md`
- `docs/RENDERING-SPEC.md`
