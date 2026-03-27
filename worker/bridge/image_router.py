"""
Image routing — emotion-based auto-selection between Pexels (stock) and Klipy (meme/GIF).
Klipy is a Tenor v2-compatible API (same endpoint structure, different base URL).
"""
from __future__ import annotations

import json
import os
from urllib import request as urllib_request

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
KLIPY_API_KEY = os.environ.get("KLIPY_API_KEY", "")

# Emotions that route to Klipy (reaction GIFs) vs Pexels (stock photos)
TENOR_EMOTIONS = {"funny", "shock", "anger"}


def search_pexels(query: str, orientation: str = "portrait") -> str | None:
    """Search Pexels for a stock image. Returns URL or None."""
    if not PEXELS_API_KEY:
        return None
    try:
        from urllib.parse import quote_plus
        safe_query = quote_plus(query)
        url = f"https://api.pexels.com/v1/search?query={safe_query}&orientation={orientation}&per_page=1"
        req = urllib_request.Request(url, headers={
            "Authorization": PEXELS_API_KEY,
            "User-Agent": "VideoStudio/1.0",
        })
        with urllib_request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            photos = data.get("photos", [])
            if photos:
                return photos[0]["src"]["portrait"]
    except Exception as e:
        print(f"[pexels] Search failed for '{query}': {e}")
    return None


def search_klipy(query: str, limit: int = 3) -> str | None:
    """Search Klipy (Tenor v2-compatible) for a GIF/MP4. Returns media URL or None."""
    if not KLIPY_API_KEY:
        return None
    try:
        from urllib.parse import quote_plus
        safe_query = quote_plus(query)
        url = (
            f"https://api.klipy.com/v2/search"
            f"?q={safe_query}&key={KLIPY_API_KEY}"
            f"&media_filter=mp4,gif&limit={limit}&contentfilter=medium"
        )
        req = urllib_request.Request(url, headers={"User-Agent": "VideoStudio/1.0"})
        with urllib_request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            results = data.get("results", [])
            if results:
                formats = results[0].get("media_formats", {})
                # Prefer mp4 over gif for smaller size
                if "mp4" in formats:
                    return formats["mp4"]["url"]
                if "gif" in formats:
                    return formats["gif"]["url"]
    except Exception as e:
        print(f"[klipy] Search failed for '{query}': {e}")
    return None


def route_image(scene: dict) -> tuple[str | None, str | None]:
    """Route image search based on emotion and image_source fields.
    Returns (resolved_image_url, source_name) tuple."""
    image_prompt = scene.get("image_prompt")
    if not image_prompt:
        return None, None

    source = scene.get("image_source", "")
    emotion = scene.get("emotion", "neutral")
    fallback = scene.get("fallback_prompt", "")

    # Explicit source override
    if source == "tenor":
        url = search_klipy(image_prompt)
        if not url and fallback:
            url = search_klipy(fallback)
        if url:
            return url, "tenor"
        # Fall through to Pexels if Tenor unconfigured/no results
        url = search_pexels(image_prompt)
        return (url, "pexels") if url else (None, None)
    if source == "pexels":
        url = search_pexels(image_prompt)
        if not url and fallback:
            url = search_pexels(fallback)
        return (url, "pexels") if url else (None, None)
    # dalle / pollinations are not yet wired in this pipeline
    if source in ("dalle", "pollinations"):
        url = search_pexels(image_prompt)
        return (url, "pexels") if url else (None, None)

    # Auto-route by emotion
    if emotion in TENOR_EMOTIONS:
        url = search_klipy(image_prompt)
        if url:
            return url, "tenor"
        if fallback:
            url = search_klipy(fallback)
            if url:
                return url, "tenor"

    # Default: Pexels
    url = search_pexels(image_prompt)
    if not url and fallback:
        url = search_pexels(fallback)
    return (url, "pexels") if url else (None, None)
