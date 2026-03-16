# Model Routing

## Default Strategy
Use free local models by default. Upgrade only the scenes that justify the extra cost.

## Routing Table

| Scenario | Conditions | Image Model | Video Model | Route |
|---|---|---|---|---|
| Draft / internal preview | `budgetMode=free` or paid APIs disabled | Local FLUX.1-schnell | Local Wan2.1-T2V-1.3B | local |
| General explainer scene | no premium realism requirement, short B-roll acceptable | Local FLUX.1-schnell | Local Wan2.1-T2V-1.3B | local |
| Premium hero scene | high-value opening or closing scene, realism important | Local FLUX.1-schnell or prior approved still | Sora 2 | sora2 |
| Audio-critical premium scene | generated audio quality is part of the scene value | Local FLUX.1-schnell or prior approved still | Veo 3 | veo3 |
| Budget fallback | spend cap reached or provider unavailable | Local FLUX.1-schnell | Local Wan2.1-T2V-1.3B | local |

## Selection Rules

```ts
function chooseRoute(scene: SceneSpec, paidEnabled: { sora2: boolean; veo3: boolean }): "local" | "sora2" | "veo3" {
    if (scene.priority <= 3) {
        return "local";
    }

    if (scene.nativeAudioNeed >= 5 && paidEnabled.veo3) {
        return "veo3";
    }

    if (scene.humanRealism >= 4 && paidEnabled.sora2) {
        return "sora2";
    }

    return "local";
}
```

## Operator Notes
- Keep premium routing rare and explicit
- Start with one premium scene per project
- Track estimated and actual costs per scene
- Always keep a local fallback path for rerenders and revisions

## Current Reference Prices
- Sora 2: currently listed by OpenAI at `720p $0.10/sec`
- Veo 3 Fast: currently listed by Google at `$0.15/sec`
- Veo 3 Standard: currently listed by Google at `$0.40/sec`

See:
- https://openai.com/api/pricing/
- https://developers.openai.com/api/docs/models/sora-2
- https://ai.google.dev/gemini-api/docs/pricing
