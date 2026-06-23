"""
Image routing — zero-paid by default, with Gemini Flash/free stock providers first.
Serper and Imagen 4 are billable routes and only run when paid providers are
explicitly enabled by the operator.
Klipy is a Tenor v2-compatible API (same endpoint structure, different base URL).
Gemini prompts emit "tenor" as image_source — this is a routing token that maps to Klipy.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import http.client
import ipaddress
import json
import logging
import os
import socket
from pathlib import Path
from urllib import request as urllib_request
from urllib.error import URLError
from urllib.parse import urlparse

from worker.media.provider_policy import paid_providers_allowed

logger = logging.getLogger(__name__)

# Shared exception tuple for outbound HTTP+JSON helpers.
# Note: ``http.client.HTTPException`` covers ``IncompleteRead`` / ``BadStatusLine``
# / ``RemoteDisconnected`` etc. which are NOT ``OSError`` subclasses and would
# otherwise crash the Flask thread when a provider closes the connection
# mid-body (common with Imagen / Gemini Flash on large image responses).
_HTTP_ERRORS: tuple[type[BaseException], ...] = (
    URLError, OSError, TimeoutError, http.client.HTTPException,
    json.JSONDecodeError, KeyError, ValueError, UnicodeDecodeError,
    binascii.Error,
)


def _get_key(name: str) -> str:
    """Read API key from env at call time (not import time) so load_dotenv works."""
    return os.environ.get(name, "")


def zero_paid_policy_status() -> dict:
    """Machine-readable policy status for health checks and operator tooling."""
    allow_paid = paid_providers_allowed()
    return {
        "mode": "paid-enabled" if allow_paid else "zero-paid",
        "paidProvidersAllowed": allow_paid,
        "paidProviderEnv": "VIDEO_STUDIO_ALLOW_PAID_PROVIDERS",
        "blockedByDefault": ["serper", "imagen", "veo3", "runway", "elevenlabs", "openai-tts", "suno"],
    }


# Emotions that route to Klipy (reaction GIFs) vs web search (product photos)
REACTION_EMOTIONS = {"funny", "shock", "anger"}


def search_serper(query: str) -> str | None:
    """Search Google Images via Serper API. Returns image URL or None."""
    api_key = _get_key("SERPER_API_KEY")
    if not api_key:
        return None
    try:
        payload = json.dumps({"q": query, "num": 5}).encode("utf-8")
        req = urllib_request.Request(
            "https://google.serper.dev/images",
            data=payload,
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
        )
        with urllib_request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read(524288))  # 512KB cap
            images = data.get("images", [])
            if images:
                # Prefer larger images (portrait-friendly for 9:16)
                for img in images:
                    url = img.get("imageUrl", "")
                    h = img.get("imageHeight", 0)
                    w = img.get("imageWidth", 0)
                    if url and h > w:  # Portrait
                        return url
                # Fallback: first image regardless of aspect
                return images[0].get("imageUrl")
    except _HTTP_ERRORS as e:
        logger.warning("serper image search failed for %r: %s", query[:50], e)
    return None


def search_serper_if_allowed(query: str) -> str | None:
    if not paid_providers_allowed():
        logger.info("serper skipped because paid providers are disabled")
        return None
    return search_serper(query)


def generate_imagen(prompt: str, output_dir: str | None = None, aspect_ratio: str = "9:16") -> str | None:
    """Generate image via Google Imagen 4 API. Returns local file path or None."""
    api_key = _get_key("GEMINI_API_KEY") or _get_key("GOOGLE_API_KEY")
    if not api_key:
        return None
    model = "imagen-4.0-fast-generate-001"
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict"
        payload = json.dumps({
            "instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": 1, "aspectRatio": aspect_ratio},
        }).encode("utf-8")
        req = urllib_request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        )
        with urllib_request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read(16_777_216).decode("utf-8"))
        b64_data = body["predictions"][0]["bytesBase64Encoded"]
        image_bytes = base64.b64decode(b64_data)

        # Save to temp file and return path
        save_dir = Path(output_dir) if output_dir else Path("storage/cache")
        save_dir.mkdir(parents=True, exist_ok=True)
        name_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        save_path = save_dir / f"imagen_{name_hash}.png"
        save_path.write_bytes(image_bytes)
        logger.info("imagen generated %d bytes → %s", len(image_bytes), save_path)
        return str(save_path)
    except _HTTP_ERRORS as e:
        logger.warning("imagen failed: %s", type(e).__name__)
        return None


def generate_imagen_if_allowed(
    prompt: str,
    output_dir: str | None = None,
    aspect_ratio: str = "9:16",
) -> str | None:
    if not paid_providers_allowed():
        logger.info("imagen skipped because paid providers are disabled")
        return None
    return generate_imagen(prompt, output_dir=output_dir, aspect_ratio=aspect_ratio)


def generate_gemini_flash(prompt: str, output_dir: str | None = None) -> str | None:
    """Generate image via Gemini Flash Image/Nano Banana. Returns local file path or None."""
    api_key = _get_key("GEMINI_API_KEY") or _get_key("GOOGLE_API_KEY")
    if not api_key:
        return None
    models = ("gemini-3.1-flash-image", "gemini-2.5-flash-image")
    last_error: BaseException | None = None
    for model in models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent"
            payload = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
            }).encode("utf-8")
            req = urllib_request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            )
            with urllib_request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read(16_777_216).decode("utf-8"))
            candidates = body.get("candidates", [])
            if not candidates:
                continue
            parts = candidates[0].get("content", {}).get("parts", [])
            b64_data = None
            for part in parts:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    b64_data = inline["data"]
                    break
            if not b64_data:
                continue
            image_bytes = base64.b64decode(b64_data)

            save_dir = Path(output_dir) if output_dir else Path("storage/cache")
            save_dir.mkdir(parents=True, exist_ok=True)
            name_hash = hashlib.sha256(f"{model}:{prompt}".encode()).hexdigest()[:16]
            save_path = save_dir / f"gemini_flash_{name_hash}.png"
            save_path.write_bytes(image_bytes)
            logger.info(
                "gemini-flash generated via %s: %d bytes -> %s",
                model,
                len(image_bytes),
                save_path,
            )
            return str(save_path)
        except _HTTP_ERRORS as e:
            last_error = e
            status = getattr(e, "code", None)
            logger.warning(
                "gemini-flash model %s failed: %s%s",
                model,
                type(e).__name__,
                f" status={status}" if status else "",
            )
    if last_error is not None:
        logger.warning("gemini-flash failed after model fallback: %s", type(last_error).__name__)
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
            data = json.loads(resp.read(524288))  # 512KB cap
            photos = data.get("photos", [])
            if photos:
                # Prefer portrait-oriented photos
                for p in photos:
                    if p.get("height", 0) > p.get("width", 0):
                        return p["src"]["portrait"]
                return photos[0]["src"]["portrait"]
    except _HTTP_ERRORS as e:
        logger.warning("pexels search failed for %r: %s", query, e)
    return None


_VALID_ORIENTATIONS = {"portrait", "landscape", "square"}


def search_pexels_video(
    query: str,
    orientation: str = "portrait",
    min_duration: float = 0,
    per_page: int = 3,
) -> dict | None:
    """Search Pexels for a stock video. Returns the first candidate or None.

    RENDERING-SPEC §5.2:
    - orientation: "portrait" (9:16 preferred)
    - duration >= scene.duration
    - video_files with width >= 1080

    Returns: {"url": str, "width": int, "height": int, "duration": float} or None.
    """
    candidates = search_pexels_video_candidates(
        query=query,
        orientation=orientation,
        min_duration=min_duration,
        per_page=per_page,
    )
    return candidates[0] if candidates else None


def search_pexels_video_candidates(
    query: str,
    orientation: str = "portrait",
    min_duration: float = 0,
    per_page: int = 8,
) -> list[dict]:
    """Search Pexels for multiple operator-curatable video candidates."""
    api_key = _get_key("PEXELS_API_KEY")
    if not api_key:
        return []
    if orientation not in _VALID_ORIENTATIONS:
        orientation = "portrait"
    per_page = max(1, min(int(per_page or 8), 20))
    try:
        from urllib.parse import quote_plus
        safe_query = quote_plus(query)
        url = (
            f"https://api.pexels.com/videos/search"
            f"?query={safe_query}&orientation={orientation}"
            f"&size=medium&per_page={per_page}"
        )
        req = urllib_request.Request(url, headers={
            "Authorization": api_key,
            "User-Agent": "VideoStudio/1.0",
        })
        with urllib_request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read(524288))
            videos = data.get("videos", [])
            skipped_duration = 0
            candidates: list[dict] = []
            for video in videos:
                duration = video.get("duration", 0)
                if min_duration > 0 and duration < min_duration:
                    skipped_duration += 1
                    continue
                best_file = _select_best_video_file(video.get("video_files", []))
                if best_file:
                    file_url = best_file.get("link")
                    if not file_url:
                        continue
                    candidates.append({
                        "id": str(video.get("id") or file_url),
                        "url": file_url,
                        "width": best_file.get("width", 0),
                        "height": best_file.get("height", 0),
                        "duration": duration,
                        "pexels_id": video.get("id"),
                        "sourceUrl": video.get("url"),
                        "thumbnailUrl": video.get("image"),
                        "author": (video.get("user") or {}).get("name"),
                    })
            if candidates:
                _log_image_usage("pexels", query)
                return candidates
            if skipped_duration and skipped_duration == len(videos):
                logger.info(
                    "pexels-video %d results for %r all shorter than %ss",
                    len(videos), query, min_duration,
                )
            elif not videos:
                logger.info("pexels-video no results for %r", query)
    except _HTTP_ERRORS as e:
        logger.warning("pexels-video search failed for %r: %s", query, e)
    return []


def _select_best_video_file(video_files: list[dict]) -> dict | None:
    """Select the best video file from Pexels video_files array.

    Priority: portrait (height > width) with width >= 1080, then landscape with width >= 1080.
    For portrait, prefer highest height (closest to 9:16).
    """
    portrait_candidates = []
    landscape_candidates = []

    for vf in video_files:
        w = vf.get("width", 0)
        h = vf.get("height", 0)
        if w < 1080:
            continue
        if h > w:
            portrait_candidates.append(vf)
        else:
            landscape_candidates.append(vf)

    # Prefer portrait — sort by height for best 9:16 fit
    if portrait_candidates:
        return max(portrait_candidates, key=lambda f: f.get("height", 0))
    # Landscape fallback (will be crop-to-fill in compose)
    if landscape_candidates:
        return max(landscape_candidates, key=lambda f: f.get("width", 0))
    # Last resort: prefer portrait-like aspect ratio
    if video_files:
        return max(video_files, key=lambda f: f.get("height", 0))
    return None


_PEXELS_VIDEO_HOSTS = frozenset({"videos.pexels.com", "player.vimeo.com"})


def _host_is_internal(host: str | None) -> bool:
    """True if host is missing or resolves to a private/loopback/link-local/reserved IP."""
    if not host:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True  # unresolvable → treat as unsafe
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return True
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return True
    return False


class _BlockInternalRedirect(urllib_request.HTTPRedirectHandler):
    """Block 3xx redirects to internal hosts.

    The initial host is allowlisted, but urlopen follows redirects by default, so a
    CDN open-redirect (or a spoofed response) could point at an internal address
    (SSRF). Public→public redirects (e.g. Vimeo → its file CDN) stay allowed.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _host_is_internal(urlparse(newurl).hostname):
            logger.warning("pexels-video redirect to internal host blocked: %r", newurl)
            return None  # urllib raises HTTPError → caught by caller → returns False
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_PEXELS_OPENER = urllib_request.build_opener(_BlockInternalRedirect())


def download_pexels_video(video_url: str, output_path: str, timeout: int = 60) -> bool:
    """Download a Pexels video file to a local path. Returns True on success."""
    try:
        parsed = urlparse(video_url)
    except ValueError:
        logger.warning("pexels-video download rejected unparseable URL")
        return False
    # SSRF guard: video_url comes from a Pexels API response. Pexels serves video
    # files from its own CDN and from Vimeo's player CDN (per the Pexels API docs);
    # allow only those over https, never an arbitrary or internal host. Redirects are
    # re-checked by _BlockInternalRedirect (urlopen follows 3xx by default).
    if parsed.scheme != "https" or parsed.hostname not in _PEXELS_VIDEO_HOSTS:
        logger.warning("pexels-video download rejected non-allowlisted host: %r", parsed.hostname)
        return False
    try:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        req = urllib_request.Request(video_url, headers={"User-Agent": "VideoStudio/1.0"})
        with _PEXELS_OPENER.open(req, timeout=timeout) as resp:
            with open(out, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        return out.exists() and out.stat().st_size > 0
    except (URLError, OSError, TimeoutError) as e:
        logger.warning("pexels-video download failed: %s", e)
        return False


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
            data = json.loads(resp.read(524288))  # 512KB cap
            results = data.get("results", [])
            if results:
                formats = results[0].get("media_formats", {})
                mp4 = formats.get("mp4")
                if mp4 and mp4.get("url"):
                    return mp4["url"]
                gif = formats.get("gif")
                if gif and gif.get("url"):
                    return gif["url"]
    except _HTTP_ERRORS as e:
        logger.warning("klipy search failed for %r: %s", query, e)
    return None


def _log_image_usage(provider: str, prompt: str) -> None:
    """Log image usage to the usage DB. Never raises."""
    try:
        from worker.usage.db import log_usage
        _COST = {"imagen": 0.02, "serper": 0.001}
        _MODEL = {
            "imagen": "imagen-4.0-fast-generate-001",
            "gemini-flash": "gemini-2.5-flash-image",
        }
        is_free = 1 if provider in ("pexels", "klipy", "gemini-flash") else 0
        cost = _COST.get(provider, 0.0)
        log_usage(
            provider=provider,
            category="image",
            model=_MODEL.get(provider),
            cost_usd=cost,
            tokens_in=0,
            tokens_out=0,
            units=1.0,
            is_free=is_free,
            metadata={"prompt": prompt[:100]},
        )
    except Exception as _log_err:
        # Usage DB is non-critical diagnostics; a failed insert must never
        # break the image-routing hot path.
        logger.debug("image usage log failed: %s", _log_err)


def route_image(scene: dict) -> tuple[str | None, str | None]:
    """Route image search based on emotion and image_source fields.
    Returns (resolved_image_url, source_name) tuple.
    source_name is "serper", "gemini-flash", "imagen", "pexels", or "klipy".
    Auto-route in zero-paid mode: Gemini Flash → Pexels/Klipy.
    Paid opt-in mode may add Serper and Imagen 4 fallbacks.
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
    # FLUX / Pollinations — dead (401, paid-only since 2026-03). Route to
    # Gemini Flash first and only call Imagen when paid providers are enabled.
    if source in ("flux", "pollinations", "imagen"):
        ai_path = generate_gemini_flash(image_prompt)
        if ai_path:
            _log_image_usage("gemini-flash", image_prompt)
            return str(Path(ai_path).resolve()), "gemini-flash"
        ai_path = generate_imagen_if_allowed(image_prompt)
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

    # Default: Gemini Flash/free stock. Serper is billable and opt-in only.
    url = search_serper_if_allowed(image_prompt)
    if url:
        _log_image_usage("serper", image_prompt)
        return url, "serper"

    # Fallback 1: Gemini Flash (free AI generation, 500/day)
    ai_path = generate_gemini_flash(image_prompt)
    if ai_path:
        _log_image_usage("gemini-flash", image_prompt)
        return str(Path(ai_path).resolve()), "gemini-flash"

    # Fallback 2: Imagen 4 when paid providers are explicitly enabled.
    ai_path = generate_imagen_if_allowed(image_prompt)
    if ai_path:
        _log_image_usage("imagen", image_prompt)
        return str(Path(ai_path).resolve()), "imagen"

    # Fallback 3: Pexels stock
    url = search_pexels(image_prompt)
    if not url and fallback:
        url = search_pexels(fallback)
    if url:
        _log_image_usage("pexels", image_prompt)
        return url, "pexels"
    return None, None


def search_sub_image(query: str) -> tuple[str | None, str | None]:
    """Fast sub-scene image search (paid-enabled Serper → Pexels, no AI gen).
    Used to add visual variety within long scenes."""
    url = search_serper_if_allowed(query)
    if url:
        return url, "serper"
    url = search_pexels(query)
    if url:
        return url, "pexels"
    return None, None
