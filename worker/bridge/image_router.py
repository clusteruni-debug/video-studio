"""
Image routing — emotion-based auto-selection between Imagen 4 (AI), Pexels (stock), and Klipy (meme/GIF).
Klipy is a Tenor v2-compatible API (same endpoint structure, different base URL).
Gemini prompts emit "tenor" as image_source — this is a routing token that maps to Klipy.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from urllib import request as urllib_request


def _get_key(name: str) -> str:
    """Read API key from env at call time (not import time) so load_dotenv works."""
    return os.environ.get(name, "")


# Emotions that route to Klipy (reaction GIFs) vs Pexels (stock photos)
REACTION_EMOTIONS = {"funny", "shock", "anger"}


def generate_imagen(prompt: str, output_dir: str | None = None, aspect_ratio: str = "9:16") -> str | None:
    """Generate image via Google Imagen 4 API. Returns local file path or None."""
    api_key = _get_key("GEMINI_API_KEY") or _get_key("GOOGLE_API_KEY")
    if not api_key:
        return None
    model = "imagen-4.0-fast-generate-001"
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict?key={api_key}"
        payload = json.dumps({
            "instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": 1, "aspectRatio": aspect_ratio},
        }).encode("utf-8")
        req = urllib_request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib_request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        b64_data = body["predictions"][0]["bytesBase64Encoded"]
        image_bytes = base64.b64decode(b64_data)

        # Save to temp file and return path
        save_dir = Path(output_dir) if output_dir else Path("storage/cache")
        save_dir.mkdir(parents=True, exist_ok=True)
        name_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        save_path = save_dir / f"imagen_{name_hash}.png"
        save_path.write_bytes(image_bytes)
        print(f"[imagen] Generated {len(image_bytes)} bytes → {save_path}")
        return str(save_path)
    except Exception as e:
        print(f"[imagen] Failed for '{prompt[:50]}': {e}")
        return None


def search_pexels(query: str, orientation: str = "portrait") -> str | None:
    """Search Pexels for a stock image. Returns URL or None."""
    api_key = _get_key("PEXELS_API_KEY")
    if not api_key:
        return None
    try:
        from urllib.parse import quote_plus
        safe_query = quote_plus(query)
        url = f"https://api.pexels.com/v1/search?query={safe_query}&orientation={orientation}&per_page=5"
        req = urllib_request.Request(url, headers={
            "Authorization": api_key,
            "User-Agent": "VideoStudio/1.0",
        })
        with urllib_request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            photos = data.get("photos", [])
            if photos:
                # Prefer portrait-oriented photos
                for p in photos:
                    if p.get("height", 0) > p.get("width", 0):
                        return p["src"]["portrait"]
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


def _log_image_usage(provider: str, prompt: str) -> None:
    """Log image usage to the usage DB. Never raises."""
    try:
        from worker.usage.db import log_usage
        is_free = 0 if provider == "imagen" else 1
        cost = 0.02 if provider == "imagen" else 0.0
        log_usage(
            provider=provider,
            category="image",
            model="imagen-4.0-fast-generate-001" if provider == "imagen" else None,
            cost_usd=cost,
            tokens_in=0,
            tokens_out=0,
            units=1.0,
            is_free=is_free,
            metadata={"prompt": prompt[:100]},
        )
    except Exception as _log_err:
        print(f"[usage] image log failed: {_log_err}")


def route_image(scene: dict) -> tuple[str | None, str | None]:
    """Route image search based on emotion and image_source fields.
    Returns (resolved_image_url, source_name) tuple.
    source_name is "imagen", "pexels", or "klipy".
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
            _log_image_usage("klipy", image_prompt)
            return url, "klipy"
        url = search_pexels(image_prompt)
        if url:
            _log_image_usage("pexels", image_prompt)
            return url, "pexels"
        return None, None
    if source == "pexels":
        url = search_pexels(image_prompt)
        if not url and fallback:
            url = search_pexels(fallback)
        if url:
            _log_image_usage("pexels", image_prompt)
            return url, "pexels"
        return None, None
    # FLUX / Pollinations — dead (401, paid-only since 2026-03). Route to Imagen 4.
    if source in ("flux", "pollinations", "imagen"):
        ai_path = generate_imagen(image_prompt)
        if ai_path:
            _log_image_usage("imagen", image_prompt)
            return str(Path(ai_path).resolve()), "imagen"
        url = search_pexels(image_prompt)
        if url:
            _log_image_usage("pexels", image_prompt)
            return url, "pexels"
        return None, None
    if source == "dalle":
        url = search_pexels(image_prompt)
        if url:
            _log_image_usage("pexels", image_prompt)
            return url, "pexels"
        return None, None

    # Auto-route by emotion
    if emotion in REACTION_EMOTIONS:
        url = search_klipy(image_prompt)
        if url:
            _log_image_usage("klipy", image_prompt)
            return url, "klipy"
        if fallback:
            url = search_klipy(fallback)
            if url:
                _log_image_usage("klipy", fallback)
                return url, "klipy"

    # Default: Imagen 4 AI generation (better visuals than stock)
    ai_path = generate_imagen(image_prompt)
    if ai_path:
        _log_image_usage("imagen", image_prompt)
        return str(Path(ai_path).resolve()), "imagen"

    # Fallback: Pexels stock
    url = search_pexels(image_prompt)
    if not url and fallback:
        url = search_pexels(fallback)
    if url:
        _log_image_usage("pexels", image_prompt)
        return url, "pexels"
    return None, None
