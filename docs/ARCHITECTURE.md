# Architecture

## Objective
Build a Windows-first short-form video tool that accepts a user prompt and produces a rendered 9:16 video by combining:
- planning and scene decomposition
- local image and video generation
- optional premium paid scene generation
- subtitle, voice, and soundtrack composition

## Core Principle
Separate planning from media generation and separate media generation from final rendering.

## System Layers

### 1. UI Layer
- collects the user prompt
- exposes project settings
- previews scene plans, costs, and generated assets
- triggers scene regeneration and final export

### 2. Planner Layer
- powered by OpenClaw + Codex
- converts the prompt into a structured `ProjectPlan`
- assigns scene priorities and generation requirements
- emits model routing hints instead of generating pixels directly

### 3. Routing Layer
- reads scene requirements and budget mode
- decides whether a scene should use:
  - local FLUX + Wan
  - premium Sora 2
  - optional Veo 3
- enforces cost ceilings and fallback behavior

### 4. Media Layer
- local image generation: FLUX.1-schnell
- local video generation: Wan2.1-T2V-1.3B-Diffusers
- paid video adapters: Sora 2 and optional Veo 3
- voice, subtitle, and soundtrack helpers live here as well

### 5. Composition Layer
- normalizes scene durations
- merges generated clips, stills, voice, subtitles, and music
- exports the final MP4 through FFmpeg

## Planning Contract

```ts
type BudgetMode = "free" | "standard" | "premium";

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

type ProjectPlan = {
    title: string;
    aspectRatio: "9:16";
    budgetMode: BudgetMode;
    monthlyCapUsd: number;
    scenes: SceneSpec[];
};
```

## First Implementation Boundary
- No database
- No cloud sync
- No multi-user auth
- Local folder storage only
- Local render pipeline first, premium API routing second

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
