"""Provider selection policy: zero-paid by default, opt-in for paid providers."""

from __future__ import annotations

import os

from worker.media.adapters import ADAPTER_CONFIG

# Default provider preference per category (first match wins)
DEFAULT_PREFERENCE = {
    "image": ["gemini-flash", "imagen"],  # Pexels/Klipy are handled separately in bridge image_router.
    "video": ["wan", "ltx-video", "hunyuan-video", "pexels-video", "veo3", "runway"],
    "tts": ["edge-tts", "windows-tts", "elevenlabs", "openai-tts"],
    "bgm": ["local-bgm", "suno"],
    "sfx": ["local-sfx", "freesound"],
}

_TRUTHY = {"1", "true", "yes", "y", "on"}
PAID_COST_TIERS = {"cheap", "premium"}


def paid_providers_allowed() -> bool:
    """Return True only when the operator explicitly enables paid providers."""
    raw = (
        os.environ.get("VIDEO_STUDIO_ALLOW_PAID_PROVIDERS")
        or os.environ.get("VIDEO_STUDIO_ALLOW_PAID")
        or ""
    )
    return raw.strip().lower() in _TRUTHY


def is_paid_provider(provider_key: str) -> bool:
    """Return whether an adapter can create billable usage."""
    config = ADAPTER_CONFIG.get(provider_key, {})
    return (
        config.get("costTier") in PAID_COST_TIERS
        or float(config.get("costPerUnit", 0.0) or 0.0) > 0
    )


def allowed_preference(category: str) -> list[str]:
    """Return provider preference after applying the zero-paid gate."""
    preference = DEFAULT_PREFERENCE.get(category, [])
    if paid_providers_allowed():
        return list(preference)
    return [provider for provider in preference if not is_paid_provider(provider)]


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
