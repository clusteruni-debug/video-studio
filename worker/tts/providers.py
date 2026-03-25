"""
TTS Providers — ElevenLabs / Google Cloud TTS / edge-tts (fallback)
Swap providers via tts_provider parameter. edge-tts is always available as free fallback.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from urllib import request, error

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
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(resp.read())
    return output_path.exists() and output_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# Google Cloud TTS
# ---------------------------------------------------------------------------
def generate_google_tts(text: str, lang: str, gender: str, output_path: Path) -> bool:
    api_key = os.environ.get("GOOGLE_TTS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_TTS_API_KEY not set")

    voice_cfg = VOICES["google"][_voice_key(lang, gender)]
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"

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
    })

    with request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
        audio_bytes = base64.b64decode(data["audioContent"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
    return output_path.exists() and output_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# edge-tts (free fallback)
# ---------------------------------------------------------------------------
def generate_edge_tts(text: str, lang: str, gender: str, output_path: Path) -> bool:
    import edge_tts

    voice = VOICES["edge"][_voice_key(lang, gender)]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async def _run():
        communicate = edge_tts.Communicate(text, voice)
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
) -> bool:
    """Generate TTS audio. Falls back to edge-tts on failure."""
    fn = PROVIDERS.get(provider)
    if fn and fn is not generate_edge_tts:
        try:
            return fn(text, lang, gender, output_path)
        except Exception as e:
            print(f"[tts] {provider} failed: {e}, falling back to edge-tts")

    return generate_edge_tts(text, lang, gender, output_path)


def available_providers() -> list[str]:
    """Return list of currently available providers based on env vars."""
    available = ["edge"]
    if os.environ.get("ELEVENLABS_API_KEY", "").strip():
        available.append("elevenlabs")
    if os.environ.get("GOOGLE_TTS_API_KEY", "").strip():
        available.append("google")
    return available
