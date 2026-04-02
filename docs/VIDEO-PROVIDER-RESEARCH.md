# Video Generation Provider Research (2026-04-02)

Research for replacing Sora 2 (OpenAI discontinuing) and Veo 3 (too expensive).

## Arena Leaderboard (Artificial Analysis, April 2026)

| Rank | Model | Elo | API Access | Cost/sec | Notes |
|------|-------|-----|------------|----------|-------|
| 1 | **Seedance 2.0** (ByteDance) | 1273 | Limited (CapCut) | ~$0.01/5sec | Best quality, limited API |
| 2 | SkyReels V4 | 1245 | ? | ? | |
| 3 | **Kling 3.0** Pro (Kuaishou) | 1242 | Official API | ~$0.07/sec | Best quality+API balance |
| 4 | Runway Gen-4.5 | 1247 | Official API | ~$0.12/sec | Premium tier |
| - | **Runway Gen-4 Turbo** | A-tier | **Best API docs** | ~$0.05/sec | Best developer experience |
| - | Veo 3.1 (Google) | A+ | Vertex AI | ~$0.15-0.40/sec | Complex GCP setup |

## Recommended Replacements

### Primary: Kling 3.0 (Quality + API)
- Official REST API at `app.klingai.com/global/dev/`
- S-tier quality (Elo 1242), strong in human realism and physics
- ~$0.07/sec, reasonable for premium scenes
- Web UI free tier: 66 credits/day (~6 videos)

### Budget: Runway Gen-4 Turbo (Cheapest premium)
- Already configured in `adapters.py` as "runway"
- Best API documentation in the industry
- $0.05/sec = 5-sec video for $0.25
- `docs.dev.runwayml.com`

### Future Watch: Seedance 2.0
- Currently #1 quality but API access limited to CapCut/Dreamina
- When official API opens, likely best price/quality ratio
- Monitor: `dreamina.capcut.com`

## Action Items

- [ ] Remove Sora 2 adapter, script, and routing code
- [ ] Update Runway adapter with Gen-4 Turbo model ID
- [ ] Add Kling 3.0 adapter config
- [ ] Create `scripts/kling_video.py` adapter script
- [ ] Update `model_router.py` Route type and cost constants
- [ ] Update provider_policy.py video preference order

## Current State (pre-cleanup)

- `sora2` adapter in adapters.py — TO REMOVE
- `veo3` adapter — KEEP (already configured, low priority)
- `runway` adapter — UPDATE to Gen-4 Turbo
- `wan` adapter — KEEP as free/local fallback (stub mode)
