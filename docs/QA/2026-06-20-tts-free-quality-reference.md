# Video Studio TTS Free Quality Reference

Last checked: 2026-06-20
Scope: reusable Korean reference/golden renders, not bottled-water-specific.

Durable reference ledger: `docs/reference/tts-providers.md`. This QA note keeps
the 2026-06-20 decision snapshot; future reusable source refreshes belong in
the reference ledger.

## Decision

Use `edge-tts` Korean Neural voice as the forced default for zero-paid
free/reference renders.

Do not use Azure Speech by default. Azure has a useful free neural-character
allowance, but it requires Azure account/card/key management and pay-as-you-go
awareness. It is explicit operator opt-in only.

Allowed default:

- Provider: `edge-tts`
- Candidate voices: `ko-KR-SunHiNeural`, `ko-KR-InJoonNeural`, then other
  Korean Neural voices only after a listening comparison.
- Required manifest evidence:
  - `ttsAlignment.voiceQuality.required=true`
  - `provider=edge-tts`
  - `voiceName=<Korean Neural voice>`
  - `voiceClass=neural`
  - `voiceNaturalnessReviewed=true`
  - `speechRateReviewed=true`
  - `fallbackUsed=false`
  - `perceivedRoboticOrSapi=false`
  - `candidateComparisonPath=<local evidence>`

Forbidden for golden/reference:

- Windows SAPI / Desktop TTS
- `Microsoft Heami Desktop`
- `System.Speech`
- Any fallback voice accepted only because it is locally available

## Candidate Evaluation

| Option | Verdict | Why | Procedure |
|---|---|---|---|
| 1. Edge TTS Neural | Use now, force as default | Immediate, no Azure signup, Korean Neural voices, works from Python/CLI. It is not the most official contract, so keep provider/voice evidence. | Install/use `edge-tts`, list voices, generate 2-3 Korean voice/rate takes, choose one by listening review, write `voiceQuality` evidence. |
| 2. Azure Speech F0 | Do not use by default; explicit opt-in only | Official Microsoft service and F0/free pages list 0.5M neural characters/month, but it requires Azure account/card/key management and pay-as-you-go awareness. Not a zero-paid default. | Use only if the operator explicitly accepts the billing/account caveat. Then create Azure account/resource, choose F0/free tier when available, set keys outside `.env`, generate Korean Neural candidates, and approve only after listening comparison. |
| 3. MeloTTS | Useful local fallback candidate | MIT-licensed multilingual TTS with Korean support and CPU real-time claim. Local install/Docker is heavier, and Korean voice quality must be checked on our scripts before replacing Edge. | Clone/install or run Docker, generate KR samples with `language='KR'`, compare against Edge/Azure, approve only if naturalness/rate/pronunciation beat Edge on phone review. |

## Azure Speech F0 Signup Notes

External reference basis:

- Azure Speech overview: `https://learn.microsoft.com/en-us/azure/ai-services/speech-service/overview`
- Azure Speech pricing: `https://azure.microsoft.com/en-us/pricing/details/speech/`
- Azure free account: `https://azure.microsoft.com/en-us/free/`
- Text-to-speech quickstart: `https://learn.microsoft.com/en-us/azure/ai-services/speech-service/get-started-text-to-speech`
- Azure voice/language support: `https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts`

Current explicit opt-in path:

1. Sign in or create an Azure account.
2. Create a Speech or AI Services Speech resource in Azure portal / Foundry.
3. Select the free/F0 tier when available. Current public pricing lists Neural
   TTS at 0.5 million characters free per month for F0.
4. Open the resource, copy key plus endpoint or region.
5. Set `SPEECH_KEY` and `ENDPOINT` or `SPEECH_REGION` manually in the shell or
   user environment. Do not write secrets into `.env` from Codex.
6. Stop if the operator does not want Azure account/billing management.
7. Generate at least three Korean voice/rate candidates and save a comparison
   artifact before marking `candidateEvaluationStatus=approved`.

Useful Korean voice candidates from current Azure language support include:

- `ko-KR-SunHiNeural`
- `ko-KR-InJoonNeural`
- `ko-KR-BongJinNeural`
- `ko-KR-GookMinNeural`
- `ko-KR-HyunsuNeural`
- `ko-KR-JiMinNeural`
- `ko-KR-SeoHyeonNeural`
- `ko-KR-SoonBokNeural`
- `ko-KR-YuJinNeural`

## MeloTTS Install Notes

External reference basis:

- MeloTTS repo: `https://github.com/myshell-ai/MeloTTS`
- Local install docs: `https://github.com/myshell-ai/MeloTTS/blob/main/docs/install.md`

Current local path:

1. Clone the repo.
2. Install editable package and run `python -m unidic download`, or use Docker
   on Windows to avoid compatibility drift.
3. Generate Korean sample with `TTS(language='KR')`.
4. Compare against Edge and Azure candidates on the same script.

Do not promote MeloTTS automatically. It becomes eligible only after local
sample generation, pronunciation review, speed review, and phone-sized full
watch.

## Gate Mapping

`worker/render/golden_reference_gate.py` enforces this through
`openingAudioContinuity.ttsAlignment.voiceQuality`.

Passing default example:

```json
{
  "required": true,
  "provider": "edge-tts",
  "voiceName": "ko-KR-SunHiNeural",
  "voiceClass": "neural",
  "ratePercent": -6,
  "voiceNaturalnessReviewed": true,
  "speechRateReviewed": true,
  "fallbackUsed": false,
  "perceivedRoboticOrSapi": false,
  "candidateComparisonPath": "storage/qa/tts-candidate-comparison.json"
}
```

Non-default example:

```json
{
  "required": true,
  "provider": "azure-speech-f0",
  "voiceName": "ko-KR-SunHiNeural",
  "voiceClass": "neural",
  "ratePercent": -6,
  "voiceNaturalnessReviewed": true,
  "speechRateReviewed": true,
  "fallbackUsed": false,
  "perceivedRoboticOrSapi": false,
  "candidateComparisonPath": "storage/qa/tts-candidate-comparison.json",
  "candidateEvaluationStatus": "approved"
}
```
