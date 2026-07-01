from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


SCHEMA = "video-studio.grok-browser-proof.v1"
IMAGINE_PATH = "/imagine"


def _text(value: Any) -> str:
    return str(value or "").strip()


def classify_grok_browser_surface(url: str, *, generation_observed: bool = False, asset_imported: bool = False) -> dict[str, Any]:
    value = _text(url)
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    is_grok = host in {"grok.com", "www.grok.com"} or host.endswith(".grok.com")
    is_imagine = is_grok and path == IMAGINE_PATH
    is_chat_redirect = is_grok and (path == "/c" or path.startswith("/c/"))
    surface_visible = is_imagine and not is_chat_redirect
    success = surface_visible and generation_observed and asset_imported

    if success:
        status = "success"
        reason = "imagine-generation-imported"
    elif is_chat_redirect:
        status = "blocked"
        reason = "grok-chat-redirect-not-imagine"
    elif surface_visible:
        status = "surface-visible"
        reason = "imagine-visible-generation-not-proven"
    elif is_grok:
        status = "blocked"
        reason = "unexpected-grok-surface"
    else:
        status = "blocked"
        reason = "not-grok"

    return {
        "schema": SCHEMA,
        "url": value,
        "host": host,
        "path": path,
        "isGrok": is_grok,
        "isImagineSurface": is_imagine,
        "isChatRedirect": is_chat_redirect,
        "surfaceVisible": surface_visible,
        "generationObserved": bool(generation_observed),
        "assetImported": bool(asset_imported),
        "status": status,
        "reason": reason,
        "success": success,
    }


def classify_grok_browser_proof(proof: dict[str, Any] | None) -> dict[str, Any]:
    proof = proof if isinstance(proof, dict) else {}
    return classify_grok_browser_surface(
        _text(proof.get("currentUrl") or proof.get("url")),
        generation_observed=proof.get("generationObserved") is True,
        asset_imported=proof.get("assetImported") is True or proof.get("imported") is True,
    )
