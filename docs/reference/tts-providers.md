---
last_verified: 2026-06-20
reliability: vendor-doc
sources:
  - Microsoft Azure Speech overview
  - Microsoft Azure Speech pricing
  - Microsoft Azure free account
  - Microsoft Azure Speech language and voice support
  - Microsoft Azure Speech text-to-speech quickstart
  - edge-tts GitHub
  - MeloTTS GitHub
refresh_trigger: when changing Video Studio TTS provider defaults, signup guidance, free-tier assumptions, Korean voice list, or golden/reference voice-quality gates
---

# TTS Provider Reference

This is the reusable Video Studio TTS provider reference. Use it before
repeating web research for Edge TTS, Azure Speech F0, MeloTTS, Korean neural
voices, or zero-paid TTS policy.

## Current Policy

The default zero-paid provider for Korean golden/reference renders is
`edge-tts` with a Korean Neural voice.

Azure Speech F0 is not a default or recommended zero-paid provider for this
workspace. It has an attractive free neural-character allowance, but it also
requires an Azure account, card verification/account management, keys, and
pay-as-you-go awareness. Treat it as explicit operator opt-in only.

MeloTTS is a candidate local provider, not an automatic replacement.

Golden/reference renders must reject:

- Windows SAPI / Desktop TTS.
- `Microsoft Heami Desktop`.
- `System.Speech`.
- Any fallback voice accepted only because it is locally available.

`worker/render/golden_reference_gate.py` enforces this through
`openingAudioContinuity.ttsAlignment.voiceQuality`.

## Source Links

- Azure Speech overview:
  `https://learn.microsoft.com/en-us/azure/ai-services/speech-service/overview`
- Azure Speech pricing:
  `https://azure.microsoft.com/en-us/pricing/details/speech/`
- Azure free account:
  `https://azure.microsoft.com/en-us/free/`
- Azure Speech text-to-speech quickstart:
  `https://learn.microsoft.com/en-us/azure/ai-services/speech-service/get-started-text-to-speech`
- Azure Speech language and voice support:
  `https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts`
- edge-tts GitHub:
  `https://github.com/rany2/edge-tts`
- MeloTTS GitHub:
  `https://github.com/myshell-ai/MeloTTS`
- MeloTTS local install docs:
  `https://github.com/myshell-ai/MeloTTS/blob/main/docs/install.md`

## Azure Speech F0

Verdict: do not use by default. Keep only as explicit operator opt-in.

Reference facts from the 2026-06-20 check:

- Azure Speech text-to-speech converts text into humanlike synthesized speech
  and supports neural voices plus SSML tuning for pitch, pronunciation, rate,
  and volume.
- Azure pricing listed Free F0 Text to Speech Neural at 0.5 million characters
  free per month.
- Azure free-account material listed Azure Speech in Foundry Tools as always
  free up to 0.5 million neural characters per month.
- Azure account material also describes a free-account path with 30-day credit,
  a move to pay-as-you-go pricing to continue beyond 30 days or after credit is
  used, and possible temporary card authorization during signup.
- Azure language support listed Korean `ko-KR` and multiple Korean Neural
  voice candidates.
- Azure quickstart requires an Azure subscription, Speech/AI Services Speech
  resource, and key plus endpoint or region environment variables.

Operational policy:

- Do not use Azure Speech for routine Video Studio renders.
- Do not ask the operator to sign up for Azure just to improve TTS.
- Do not promote Azure as "free" without also mentioning the account,
  card/verification, and pay-as-you-go management boundary.
- Do not write Azure keys into `.env`.
- Use Azure only when the operator explicitly chooses it after seeing the
  billing/account-management caveat.

Useful Korean voice candidates from the current Azure voice table:

- `ko-KR-SunHiNeural`
- `ko-KR-InJoonNeural`
- `ko-KR-BongJinNeural`
- `ko-KR-GookMinNeural`
- `ko-KR-HyunsuNeural`
- `ko-KR-JiMinNeural`
- `ko-KR-SeoHyeonNeural`
- `ko-KR-SoonBokNeural`
- `ko-KR-YuJinNeural`

Explicit opt-in procedure:

1. User signs in to Azure or creates an Azure account.
2. User creates a Speech or AI Services Speech resource in Azure portal or
   Foundry.
3. User selects the free/F0 tier when available.
4. User opens the resource and copies key plus endpoint or region.
5. User sets `SPEECH_KEY` and `ENDPOINT` or `SPEECH_REGION` in the shell or
   user environment. Codex must not write secrets into `.env`.
6. Generate at least three Korean voice/rate candidates.
7. Save the listening comparison artifact and set
   `candidateEvaluationStatus=approved` only after phone/full-watch review.

Gate example:

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

## Edge TTS

Verdict: current default for zero-paid Korean reference renders.

Use procedure:

1. Use `edge-tts --list-voices` or the Python API to identify Korean Neural
   candidates.
2. Generate at least two voice/rate takes for the same Korean script.
3. Pick the best take by listening review.
4. Record `voiceQuality` evidence in the render manifest.

Gate example:

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

## MeloTTS

Verdict: useful local/free candidate, but requires local install/model proof
and listening review before replacing Edge.

Reference facts from the 2026-06-20 check:

- MeloTTS describes itself as a high-quality multilingual TTS library with
  Korean support.
- The repo lists MIT license.
- The docs include local install and Docker paths. For Windows, Docker is the
  safer evaluation path.

Evaluation procedure:

1. Clone/install MeloTTS or run Docker.
2. Generate KR samples with `TTS(language='KR')`.
3. Compare against Edge and Azure on the same script.
4. Promote only if Korean pronunciation, speed, and naturalness beat the Edge
   baseline in review.

## Refresh Rules

Refresh this reference before changing:

- default TTS provider;
- Azure free-tier/free-account guidance;
- Korean voice candidate list;
- manifest `voiceQuality` gate semantics;
- install instructions for MeloTTS or other local neural TTS;
- paid/free provider boundary.
