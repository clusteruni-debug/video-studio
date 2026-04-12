# Model Routing

## Default Strategy
Use free providers by default. Upgrade only the scenes that justify the extra cost, with manual approval required.

## Provider Categories

### Image Generation

| Provider | Key | Cost Tier | Cost/Unit | API Key Required |
|----------|-----|-----------|-----------|------------------|
| Pollinations FLUX | `pollinations` | free | $0.00 | No |
| Local FLUX.1-schnell | `flux` | free | $0.00 | No |
| DALL-E 3 | `dalle3` | premium | ~$0.04/image | `OPENAI_API_KEY` |
| Imagen 3 | `imagen3` | premium | ~$0.02/image | `GOOGLE_API_KEY` |

### Video Generation

| Provider | Key | Cost Tier | Cost/Unit | API Key Required |
|----------|-----|-----------|-----------|------------------|
| Local Wan2.1 | `wan` | free | $0.00 | No |
| Sora 2 | `sora2` | premium | ~$0.10/sec | `OPENAI_API_KEY` |
| Veo 3 | `veo3` | premium | ~$0.15/sec | `GOOGLE_API_KEY` |
| Runway Gen-3 | `runway` | premium | ~$0.05/sec | `RUNWAY_API_KEY` |

### Text-to-Speech

| Provider | Key | Cost Tier | Cost/Unit | API Key Required |
|----------|-----|-----------|-----------|------------------|
| Edge TTS | `edge-tts` | free | $0.00 | No |
| Windows TTS | `windows-tts` | free | $0.00 | No (Windows only) |
| ElevenLabs | `elevenlabs` | cheap | ~$0.003/sec | `ELEVENLABS_API_KEY` |
| OpenAI TTS | `openai-tts` | cheap | ~$0.015/1K chars | `OPENAI_API_KEY` |

### Background Music

| Provider | Key | Cost Tier | Cost/Unit | API Key Required |
|----------|-----|-----------|-----------|------------------|
| Local library | `local-bgm` | free | $0.00 | No |
| Suno | `suno` | premium | ~$0.05/track | `SUNO_API_KEY` |

### Sound Effects

| Provider | Key | Cost Tier | Cost/Unit | API Key Required |
|----------|-----|-----------|-----------|------------------|
| Local library | `local-sfx` | free | $0.00 | No |
| Freesound | `freesound` | free | $0.00 | `FREESOUND_API_KEY` |

## Provider Selection Rules

Provider selection follows a free-first preference order defined in
`worker/media/provider_policy.py` (`DEFAULT_PREFERENCE`):

```
image: pollinations → flux → dalle3 → imagen3
video: wan → sora2 → veo3 → runway
tts:   edge-tts → windows-tts → elevenlabs → openai-tts
bgm:   local-bgm → suno
sfx:   local-sfx → freesound
```

The compose pipeline (`worker/render/compose.py`) currently uses a hardcoded
fallback chain for TTS (Edge TTS → Windows Speech → sine tone) rather than
dynamic dispatch via provider selection. Per-scene provider selection UI is
planned but not yet implemented (see `docs/archive/CODEX-TASKS.md` CX-5).

## Video Route Selection (Legacy)

| Scenario | Conditions | Route |
|---|---|---|
| Draft / internal preview | `budgetMode=free` or paid APIs disabled | local |
| General explainer scene | priority <= 3 | local |
| Premium hero scene | priority >= 4, humanRealism >= 4 | sora2 |
| Audio-critical premium scene | priority >= 4, nativeAudioNeed >= 5 | veo3 |
| Budget fallback | spend cap reached or provider unavailable | local |

## Operator Notes
- Keep premium routing rare and explicit
- Start with one premium scene per project
- Track estimated and actual costs per scene
- Always keep a local fallback path for rerenders and revisions
- Edge TTS is the recommended default TTS — cross-platform, free, good Korean support

## Reference Prices
- Sora 2: `720p $0.10/sec` (OpenAI)
- Veo 3 Fast: `$0.15/sec` (Google)
- Veo 3 Standard: `$0.40/sec` (Google)
- DALL-E 3: `$0.040/image` at 1024x1024
- ElevenLabs: `~$0.003/sec` (pay-as-you-go)
- OpenAI TTS: `$15/1M chars` (tts-1)

[UNCERTAIN] Suno API pricing — unofficial API, may require separate subscription.
