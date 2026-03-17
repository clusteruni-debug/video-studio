"""Provider selection policy — free-first with manual approval for paid providers."""

from __future__ import annotations

from worker.media.adapters import (
    ADAPTER_CONFIG,
    MediaAdapterStatus,
    free_adapters_by_category,
)

# Default provider preference per category (first match wins)
DEFAULT_PREFERENCE = {
    "image": ["pollinations", "flux", "dalle3", "imagen3"],
    "video": ["wan", "sora2", "veo3", "runway"],
    "tts": ["edge-tts", "windows-tts", "elevenlabs", "openai-tts"],
    "bgm": ["local-bgm", "suno"],
    "sfx": ["local-sfx", "freesound"],
}


def select_provider(
    category: str,
    scene_id: str,
    adapters: dict[str, MediaAdapterStatus],
    budget_mode: str = "free",
    approvals: dict[str, dict[str, str]] | None = None,
) -> str | None:
    """Choose the best provider for *category* in a given scene.

    Parameters
    ----------
    category : str
        One of "image", "video", "tts", "bgm", "sfx".
    scene_id : str
        Scene identifier, used to look up per-scene approvals.
    adapters : dict
        Result of ``probe_local_media_adapters()`` (keyed by adapter key).
    budget_mode : str
        ``"free"`` forces free-only; ``"standard"``/``"premium"`` allow paid
        if explicitly approved.
    approvals : dict, optional
        ``{sceneId: {category: providerKey}}`` — explicit user approval for
        paid providers on specific scenes.

    Returns
    -------
    str or None
        The selected adapter key, or ``None`` if nothing is available.
    """
    approvals = approvals or {}
    preference = DEFAULT_PREFERENCE.get(category, [])

    # Check for explicit approval on this scene+category
    scene_approvals = approvals.get(scene_id, {})
    approved_key = scene_approvals.get(category)

    if approved_key and approved_key in ADAPTER_CONFIG:
        # User explicitly approved a (possibly paid) provider
        status = adapters.get(approved_key)
        if status and status.ready:
            return approved_key

    # Free-first: try all free providers in preference order
    free_keys = free_adapters_by_category(category)
    for key in preference:
        if key not in free_keys:
            continue
        status = adapters.get(key)
        if status and status.ready:
            return key

    # If budget allows paid and no free provider is ready, try paid providers
    if budget_mode != "free":
        for key in preference:
            if key in free_keys:
                continue
            config = ADAPTER_CONFIG.get(key, {})
            # Paid providers require explicit approval per scene
            if approved_key == key or budget_mode == "premium":
                status = adapters.get(key)
                if status and status.ready:
                    return key

    # Last resort: return the first provider in preference (even if not ready)
    # so the adapter system can generate a placeholder
    for key in preference:
        if key in ADAPTER_CONFIG:
            return key

    return None


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


def estimate_project_cost(
    scenes: list[dict],
    provider_selections: dict[str, dict[str, str]],
) -> dict:
    """Estimate total project cost from provider selections.

    Parameters
    ----------
    scenes : list of dict
        Scene dicts from the manifest.
    provider_selections : dict
        ``{sceneId: {category: providerKey}}``

    Returns
    -------
    dict
        ``{"total": float, "perScene": [{sceneId, costs: {category: cost}}], "breakdown": {category: total}}``
    """
    total = 0.0
    per_scene: list[dict] = []
    breakdown: dict[str, float] = {}

    for scene in scenes:
        scene_id = scene.get("sceneId", "")
        duration_sec = scene.get("durationSec", 5.0)
        selections = provider_selections.get(scene_id, {})
        scene_costs: dict[str, float] = {}

        for category, provider_key in selections.items():
            cost = estimate_scene_cost(category, provider_key, duration_sec=duration_sec)
            scene_costs[category] = cost
            total += cost
            breakdown[category] = breakdown.get(category, 0.0) + cost

        per_scene.append({"sceneId": scene_id, "costs": scene_costs})

    return {
        "total": round(total, 4),
        "perScene": per_scene,
        "breakdown": {k: round(v, 4) for k, v in breakdown.items()},
    }
