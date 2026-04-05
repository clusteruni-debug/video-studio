"""Provider selection policy — free-first with manual approval for paid providers."""

from __future__ import annotations

from worker.media.adapters import ADAPTER_CONFIG

# Default provider preference per category (first match wins)
DEFAULT_PREFERENCE = {
    "image": ["gemini-flash"],  # free-only: Gemini Flash (free AI gen). Pexels/Serper handled separately in bridge image_router
    "video": ["wan", "veo3", "runway"],  # Sora 2 retired 2026-04; removed from adapters.py registry.
    "tts": ["edge-tts", "windows-tts", "elevenlabs", "openai-tts"],
    "bgm": ["local-bgm", "suno"],
    "sfx": ["local-sfx", "freesound"],
}

def estimate_scene_cost(
    category: str,
    provider_key: str,
    duration_sec: float = 0.0,
    count: int = 1,
) -> float:
    """Estimate cost for using a provider on one scene.

    For images: cost = costPerUnit * count
    For audio/video: cost = costPerUnit * duration_sec
    For BGM: cost = costPerUnit per track
    """
    config = ADAPTER_CONFIG.get(provider_key, {})
    cost_per_unit = config.get("costPerUnit", 0.0)

    if category == "image":
        return round(cost_per_unit * count, 4)
    if category in ("video", "tts"):
        return round(cost_per_unit * duration_sec, 4)
    # bgm, sfx — per track
    return round(cost_per_unit * count, 4)
