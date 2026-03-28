"""
Image routing — emotion-based auto-selection between Pexels (stock) and Klipy (meme/GIF).
Klipy is a Tenor v2-compatible API (same endpoint structure, different base URL).
Gemini prompts emit "tenor" as image_source — this is a routing token that maps to Klipy.
"""
from __future__ import annotations

import json
import os
from urllib import request as urllib_request


def _get_key(name: str) -> str:
    """Read API key from env at call time (not import time) so load_dotenv works."""
    return os.environ.get(name, "")


# Emotions that route to Klipy (reaction GIFs) vs Pexels (stock photos)
REACTION_EMOTIONS = {"funny", "shock", "anger"}


def search_pexels(query: str, orientation: str = "portrait") -> str | None:
    """Search Pexels for a stock image. Returns URL or None."""
    api_key = _get_key("PEXELS_API_KEY")
    if not api_key:
        return None
    try:
        from urllib.parse import quote_plus
        safe_query = quote_plus(query)
        url = f"https://api.pexels.com/v1/search?query={safe_query}&orientation={orientation}&per_page=1"
        req = urllib_request.Request(url, headers={
            "Authorization": api_key,
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
    api_key = _get_key("KLIPY_API_KEY")
    if not api_key:
        return None
    try:
        from urllib.parse import quote_plus
        safe_query = quote_plus(query)
        url = (
            f"https://api.klipy.com/v2/search"
            f"?q={safe_query}&key={api_key}"
            f"&media_filter=mp4,gif&limit={limit}&contentfilter=medium"
        )
        req = urllib_request.Request(url, headers={"User-Agent": "VideoStudio/1.0"})
        with urllib_request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            results = data.get("results", [])
            if results:
                formats = results[0].get("media_formats", {})
                mp4 = formats.get("mp4")
                if mp4 and mp4.get("url"):
                    return mp4["url"]
                gif = formats.get("gif")
                if gif and gif.get("url"):
                    return gif["url"]
    except Exception as e:
        print(f"[klipy] Search failed for '{query}': {e}")
    return None


def _generate_pollinations(prompt: str, width: int = 1080, height: int = 1920) -> str | None:
    """Generate image via Pollinations FLUX (free). Returns image URL or None."""
    try:
        from urllib.parse import quote_plus
        safe_prompt = quote_plus(prompt)
        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width={width}&height={height}&nologo=true"
        # Verify the URL resolves (Pollinations redirects to generated image)
        req = urllib_request.Request(url, method="HEAD", headers={"User-Agent": "VideoStudio/1.0"})
        with urllib_request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                return resp.url  # Final redirect URL
    except Exception as e:
        print(f"[pollinations] Generation failed for '{prompt[:40]}': {e}")
    return None


def route_image(scene: dict) -> tuple[str | None, str | None]:
    """Route image search based on emotion and image_source fields.
    Returns (resolved_image_url, source_name) tuple.
    Note: Gemini emits "tenor" as image_source — this maps to Klipy."""
    image_prompt = scene.get("image_prompt")
    if not image_prompt:
        return None, None

    source = scene.get("image_source", "")
    emotion = scene.get("emotion", "neutral")
    fallback = scene.get("fallback_prompt", "")

    # Explicit source override ("tenor" from Gemini → Klipy)
    if source == "tenor":
        url = search_klipy(image_prompt)
        if not url and fallback:
            url = search_klipy(fallback)
        if url:
            return url, "klipy"
        # Fall through to Pexels if Klipy unconfigured/no results
        url = search_pexels(image_prompt)
        return (url, "pexels") if url else (None, None)
    if source == "pexels":
        url = search_pexels(image_prompt)
        if not url and fallback:
            url = search_pexels(fallback)
        return (url, "pexels") if url else (None, None)
    # FLUX / Pollinations — use the Pollinations FLUX endpoint
    if source in ("flux", "pollinations"):
        url = _generate_pollinations(image_prompt)
        if url:
            return url, "flux"
        # Fall back to Pexels if generation fails
        url = search_pexels(image_prompt)
        return (url, "pexels") if url else (None, None)
    if source == "dalle":
        url = search_pexels(image_prompt)
        return (url, "pexels") if url else (None, None)

    # Auto-route by emotion
    if emotion in REACTION_EMOTIONS:
        url = search_klipy(image_prompt)
        if url:
            return url, "klipy"
        if fallback:
            url = search_klipy(fallback)
            if url:
                return url, "klipy"

    # Default: Pexels
    url = search_pexels(image_prompt)
    if not url and fallback:
        url = search_pexels(fallback)
    return (url, "pexels") if url else (None, None)
