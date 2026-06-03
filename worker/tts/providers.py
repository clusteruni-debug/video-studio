"""
TTS Providers — ElevenLabs / Google Cloud TTS / edge-tts (fallback)
Swap providers via tts_provider parameter. edge-tts is always available as free fallback.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from urllib import request, error

logger = logging.getLogger(__name__)

# Upper bound for TTS audio responses. ElevenLabs + Google Cloud TTS produce
# MP3/WAV at 128 kbps ≈ 16 KB/s; 10 MB covers > 10 minutes of narration which
# is well above any single-scene TTS request.
_MAX_TTS_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB
# Google Cloud TTS returns base64-encoded JSON, not raw audio bytes. The JSON
# envelope is typically under 5 MB for a 1000-character narration segment.
_MAX_TTS_JSON_BYTES = 5 * 1024 * 1024  # 5 MB

# ---------------------------------------------------------------------------
# Voice presets
# ---------------------------------------------------------------------------
VOICES = {
    "elevenlabs": {
        "ko-female": os.environ.get("ELEVENLABS_VOICE_KO_F", "pFZP5JQG7iQjIQuC4Bku"),  # Lily
        "ko-male": os.environ.get("ELEVENLABS_VOICE_KO_M", "TX3LPaxmHKxFdv7VOQHJ"),    # Liam
        "en-female": os.environ.get("ELEVENLABS_VOICE_EN_F", "pFZP5JQG7iQjIQuC4Bku"),
        "en-male": os.environ.get("ELEVENLABS_VOICE_EN_M", "TX3LPaxmHKxFdv7VOQHJ"),
    },
    "google": {
        "ko-female": {"name": "ko-KR-Wavenet-A", "lang": "ko-KR"},
        "ko-male": {"name": "ko-KR-Wavenet-C", "lang": "ko-KR"},
        "en-female": {"name": "en-US-Neural2-F", "lang": "en-US"},
        "en-male": {"name": "en-US-Neural2-D", "lang": "en-US"},
    },
    "edge": {
        "ko-female": "ko-KR-SunHiNeural",
        "ko-male": "ko-KR-InJoonNeural",
        "en-female": "en-US-AriaNeural",
        "en-male": "en-US-GuyNeural",
    },
}


def _voice_key(lang: str, gender: str) -> str:
    prefix = "en" if lang.startswith("en") else "ko"
    return f"{prefix}-{gender}"


# ---------------------------------------------------------------------------
# ElevenLabs
# ---------------------------------------------------------------------------
def generate_elevenlabs(text: str, lang: str, gender: str, output_path: Path) -> bool:
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")

    voice_id = VOICES["elevenlabs"][_voice_key(lang, gender)]
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    payload = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }).encode("utf-8")

    req = request.Request(url, data=payload, headers={
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    })

    with request.urlopen(req, timeout=30) as resp:
        # ElevenLabs returns 200 + audio/mpeg on success. A non-200 response
        # (429 quota, 5xx) carries a JSON or HTML error body — writing that
        # as .mp3 silently produces a corrupt output file downstream.
        if getattr(resp, "status", 200) != 200:
            logger.warning(
                "ElevenLabs returned status %s for voice %s",
                getattr(resp, "status", "unknown"), voice_id,
            )
            return False
        content_type = resp.headers.get("Content-Type", "")
        if not content_type.startswith(("audio/", "application/octet-stream")):
            logger.warning(
                "ElevenLabs returned non-audio content-type %r; dropping body",
                content_type,
            )
            return False
        body = resp.read(_MAX_TTS_RESPONSE_BYTES)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(body)
    return output_path.exists() and output_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# Google Cloud TTS
# ---------------------------------------------------------------------------
def generate_google_tts(text: str, lang: str, gender: str, output_path: Path) -> bool:
    api_key = os.environ.get("GOOGLE_TTS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_TTS_API_KEY not set")

    voice_cfg = VOICES["google"][_voice_key(lang, gender)]
    url = "https://texttospeech.googleapis.com/v1/text:synthesize"

    payload = json.dumps({
        "input": {"text": text},
        "voice": {
            "languageCode": voice_cfg["lang"],
            "name": voice_cfg["name"],
        },
        "audioConfig": {"audioEncoding": "MP3"},
    }).encode("utf-8")

    req = request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    })

    with request.urlopen(req, timeout=30) as resp:
        if getattr(resp, "status", 200) != 200:
            logger.warning(
                "Google TTS returned status %s", getattr(resp, "status", "unknown"),
            )
            return False
        data = json.loads(resp.read(_MAX_TTS_JSON_BYTES))
        audio_b64 = data.get("audioContent")
        if not audio_b64:
            logger.warning("Google TTS response missing audioContent field")
            return False
        audio_bytes = base64.b64decode(audio_b64)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
    success = output_path.exists() and output_path.stat().st_size > 0
    if success:
        try:
            from worker.usage.db import log_usage
            char_count = len(text)
            log_usage(
                provider="google-tts",
                category="tts",
                model=voice_cfg["name"],
                cost_usd=0.0,
                tokens_in=0,
                tokens_out=0,
                units=float(char_count),
                is_free=1,
                metadata={"lang": lang, "gender": gender},
            )
        except Exception as _log_err:
            # Usage log is diagnostic; failure must not abort the TTS call.
            logger.debug("google-tts usage log failed: %s", _log_err)
    return success


# ---------------------------------------------------------------------------
# edge-tts (free fallback)
# ---------------------------------------------------------------------------
def generate_edge_tts(
    text: str, lang: str, gender: str, output_path: Path,
    rate: str = "+0%", pitch: str = "+0Hz",
) -> bool:
    import edge_tts

    voice = VOICES["edge"][_voice_key(lang, gender)]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async def _run():
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(str(output_path))

    asyncio.run(_run())
    return output_path.exists() and output_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# Provider dispatcher
# ---------------------------------------------------------------------------
PROVIDERS = {
    "elevenlabs": generate_elevenlabs,
    "google": generate_google_tts,
    "edge": generate_edge_tts,
}


def generate_tts(
    text: str,
    lang: str = "ko",
    gender: str = "female",
    provider: str = "edge",
    output_path: Path = Path("output.mp3"),
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> bool:
    """Generate TTS audio. Falls back to edge-tts on failure.
    rate/pitch only apply to edge-tts (e.g. rate='-5%', pitch='-1Hz' for commentary tone)."""
    fn = PROVIDERS.get(provider)
    if fn and fn is not generate_edge_tts:
        if rate != "+0%" or pitch != "+0Hz":
            logger.info(
                "tts provider %s does not support rate/pitch — tone shift will only apply on edge-tts fallback",
                provider,
            )
        try:
            return fn(text, lang, gender, output_path)
        except Exception as e:
            logger.warning("tts provider %s failed: %s, falling back to edge-tts", provider, e)

    return generate_edge_tts(text, lang, gender, output_path, rate=rate, pitch=pitch)


def available_providers() -> list[str]:
    """Return list of currently available providers based on env vars."""
    available = ["edge"]
    if os.environ.get("ELEVENLABS_API_KEY", "").strip():
        available.append("elevenlabs")
    if os.environ.get("GOOGLE_TTS_API_KEY", "").strip():
        available.append("google")
    return available
