# Architecture

## Objective
Build a Windows-first short-form video content automation tool that accepts a user prompt and produces a rendered 9:16 video by combining:
- planning and scene decomposition
- local and cloud image/video generation with multi-provider support
- TTS narration (free Edge TTS or premium providers)
- background music (local library or AI-generated)
- Ken Burns motion effects, scene transitions, and FFmpeg composition

## Core Principle
Separate planning from media generation and separate media generation from final rendering.
Free-first provider selection with manual approval for paid APIs.

## System Layers

### 1. UI Layer (`app/ui/src/`)
- `App.tsx` — state management and layout shell (428 lines)
- `components/ComposerPanel.tsx` — prompt input, budget controls, bridge status
- `components/StoryboardPanel.tsx` — scene cards, asset management, cost preview
- `components/ExecutionPanel.tsx` — render controls, project history, collapsible diagnostics
- `components/shared.ts` — shared types and utility functions

### 2. Planner Layer (`worker/planner/`)
- powered by Ollama (local) or browser-sample fallback
- converts the prompt into a structured `ProjectPlan`
- assigns scene priorities and generation requirements
- emits model routing hints instead of generating pixels directly

### 3. Routing Layer (`worker/media/`)
- reads scene requirements and budget mode
- **provider policy** (`provider_policy.py`) — free-first selection with manual approval for paid
- **adapter registry** (`adapters.py`) — 18 providers across 5 categories
- **cost estimator** (`model_router.py`) — per-scene and per-project cost breakdown
- decides provider per category: image, video, tts, bgm, sfx

### 4. Media Layer (5 categories)

| Category | Free Providers | Premium Providers |
|----------|---------------|-------------------|
| Image | Pollinations FLUX, local FLUX | DALL-E 3, Imagen 3 |
| Video | local Wan | Sora 2, Veo 3, Runway |
| TTS | Edge TTS, Windows TTS | ElevenLabs, OpenAI TTS |
| BGM | Local library | Suno |
| SFX | Local library, Freesound | — |

Each provider is a standalone script in `scripts/` following the command-template pattern:
- `--prompt-path` input, `--output-path` output
- Configured via `VIDEO_STUDIO_{KEY}_MODE` and `VIDEO_STUDIO_{KEY}_COMMAND` env vars

### 5. Composition Layer (`worker/render/`)
- `compose.py` — orchestrator (imports from motion.py, transitions.py)
- `motion.py` — Ken Burns zoompan filter presets (zoom_in/out, pan, drift)
- `transitions.py` — xfade filter builders, gradient background generators
- Applies motion effects to still images (zoompan)
- Cross-fades between scenes (xfade + acrossfade)
- Gradient backgrounds instead of flat solid-color fallback cards
- BGM mixing under narration at reduced volume
- Exports final MP4 through FFmpeg

## Planning Contract

```ts
type BudgetMode = "free" | "standard" | "premium";
type MotionPreset = "none" | "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "drift_up" | "drift_down" | "random";
type TransitionType = "none" | "fade" | "dissolve" | "wipeleft";

type SceneSpec = {
    id: string;
    prompt: string;
    durationSec: number;
    priority: 1 | 2 | 3 | 4 | 5;
    humanRealism: 1 | 2 | 3 | 4 | 5;
    nativeAudioNeed: 1 | 2 | 3 | 4 | 5;
    canUseStillImage: boolean;
    subtitleText: string;
    routeHint: "local" | "sora2" | "veo3";
};
```

## Provider Selection Policy
1. Always prefer free providers when no explicit approval is given
2. Paid providers require per-scene manual approval in the UI
3. Fallback chain: if selected provider fails → try next free → placeholder
4. Cost estimation shown before render execution

## First Implementation Boundary
- No database
- No cloud sync
- No multi-user auth
- Local folder storage only
- Free provider path works end-to-end with zero API keys

## OpenClaw Role
- prompt understanding
- scene planning
- route hints
- copy generation

OpenClaw does **not** own:
- the final source-of-truth project file
- render outputs
- long-term storage
- paid API keys
