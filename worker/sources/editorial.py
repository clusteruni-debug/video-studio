"""Source-first editorial planning for reference-led videos.

This module does not scrape pages. It can, after an explicit operator approval,
download direct media URLs into the project source-acquisition area and attach
the local path/hash evidence to the rights-aware source plan.
"""
from __future__ import annotations

import ipaddress
import json
import hashlib
import mimetypes
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


SCHEMA = "video-studio.editorial-source-plan.v1"
MAX_DIRECT_ASSET_BYTES = 30 * 1024 * 1024
SOURCE_FETCH_PASS_STATUSES = {"fetched", "downloaded", "pass", "ok", "ready", "saved"}
SOURCE_FETCH_MEDIA_KINDS = {"gif", "image", "video"}
# Content-types that carry no media-type signal — fall back to the URL suffix.
_GENERIC_CONTENT_TYPES = {"application/octet-stream", "binary/octet-stream"}

FORMAT_SOURCE_NEEDS: dict[str, list[dict]] = {
    "ranking": [
        {"role": "fact-proof", "sourceTypes": ["official-page", "official-document"], "required": True},
        {"role": "comparison", "sourceTypes": ["official-page", "news-article"], "required": True},
        {"role": "visual-proof", "sourceTypes": ["press-image", "original-video", "cc-video"], "required": False},
    ],
    "explainer": [
        {"role": "fact-proof", "sourceTypes": ["official-page", "official-document", "news-article"], "required": True},
        {"role": "visual-proof", "sourceTypes": ["original-video", "press-image", "public-domain", "cc-video"], "required": True},
        {"role": "cutaway", "sourceTypes": ["ai-generated", "stock-video"], "required": False},
    ],
    "commentary": [
        {"role": "commentary-target", "sourceTypes": ["original-video", "creator-video", "social-video"], "required": True},
        {"role": "fact-proof", "sourceTypes": ["official-page", "news-article"], "required": False},
        {"role": "cutaway", "sourceTypes": ["ai-generated", "stock-video"], "required": False},
    ],
    "tutorial": [
        {"role": "fact-proof", "sourceTypes": ["official-document", "official-page"], "required": True},
        {"role": "visual-proof", "sourceTypes": ["creator-owned", "press-image", "cc-video"], "required": True},
        {"role": "cutaway", "sourceTypes": ["ai-generated"], "required": False},
    ],
}

OFFICIAL_DOMAINS = {
    "youtube.com",
    "youtu.be",
    "support.google.com",
    "blog.youtube",
    "tiktok.com",
    "newsroom.tiktok.com",
    "ads.tiktok.com",
    "instagram.com",
    "about.fb.com",
}

CC_TERMS = ("creative commons", "cc-by", "cc by", "cc0", "public domain", "wikimedia")
DOWNLOAD_EDIT_TERMS = ("owned", "operator-owned", "download-edit", "licensed", "media kit", "press kit")
COMMUNITY_IMAGE_SOURCE_TYPES = {
    "community-image",
    "forum-image",
    "meme-image",
    "social-image",
    "reaction-image",
    "web-image",
}
INTERNET_ASSET_SOURCE_TYPES = {
    *COMMUNITY_IMAGE_SOURCE_TYPES,
    "internet-image",
    "web-image",
    "cc-image",
    "public-domain-image",
    "wikimedia-image",
    "community-gif",
    "meme-gif",
    "reaction-gif",
    "internet-gif",
    "web-gif",
    "cc-gif",
    "public-domain-gif",
}
INTERNET_MOTION_SOURCE_TYPES = {
    "community-gif",
    "meme-gif",
    "reaction-gif",
    "internet-gif",
    "web-gif",
    "cc-gif",
    "public-domain-gif",
    "cc-video",
    "public-domain",
}
COMMUNITY_HOST_HINTS = {
    "reddit.com",
    "x.com",
    "twitter.com",
    "threads.net",
    "instagram.com",
    "tiktok.com",
    "dcinside.com",
    "fmkorea.com",
    "theqoo.net",
    "instiz.net",
    "ruliweb.com",
    "clien.net",
    "ppomppu.co.kr",
    "mlbpark.donga.com",
    "imgflip.com",
    "tenor.com",
    "giphy.com",
    "knowyourmeme.com",
    "programmerhumor.io",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: object, fallback: str = "") -> str:
    return " ".join(str(value or fallback).replace("\r", " ").replace("\n", " ").split()).strip()


def _slug(value: object, fallback: str = "source-first-editorial-pilot") -> str:
    raw = _clean_text(value, fallback).lower()
    raw = re.sub(r"[^a-z0-9가-힣._-]+", "-", raw).strip(".-")
    return raw[:80] or fallback


def _safe_filename(value: object, fallback: str = "source") -> str:
    safe = re.sub(r"[^a-zA-Z0-9가-힣._-]+", "-", _clean_text(value, fallback)).strip(".-")
    return safe[:96] or fallback


def _host(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _project_relative(project_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _host_is_public(host: str) -> bool:
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False
    return True


class _BlockInternalRedirect(HTTPRedirectHandler):
    """Block 3xx redirects whose target host is not public.

    The initial host is validated by _host_is_public, but urlopen follows redirects
    by default, so a CDN open-redirect or a spoofed response could point at an
    internal address (SSRF). Public->public redirects stay allowed; an internal
    target returns None, so urllib raises HTTPError and the caller converts it to a
    ValueError. This mirrors worker.bridge.image_router._BlockInternalRedirect.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _host_is_public(urlparse(newurl).hostname or ""):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_SOURCE_OPENER = build_opener(_BlockInternalRedirect())


def _media_kind(content_type: object = "", suffix: object = "") -> str:
    content = _clean_text(content_type).lower().split(";", 1)[0]
    ext = _clean_text(suffix).lower()
    # Trust the URL suffix only when the content-type does not contradict it.
    # Allowlist (not denylist): a present, specific, non-media content-type
    # (text/html, application/pdf, application/zip, ...) overrides a media-looking
    # suffix, so a ".gif" URL that actually serves a non-media body is rejected.
    # Empty or generic (application/octet-stream) content-types fall back to suffix.
    if content and content not in _GENERIC_CONTENT_TYPES and not (
        content.startswith("image/") or content.startswith("video/")
    ):
        return ""
    if content == "image/gif" or ext == ".gif":
        return "gif"
    if content.startswith("video/") or ext in {".mp4", ".webm", ".mov", ".m4v"}:
        return "video"
    if content.startswith("image/") or ext in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    return ""


def _extension_for_asset(url: str, content_type: str) -> str:
    parsed_suffix = Path(urlparse(url).path).suffix.lower()
    if parsed_suffix in {".gif", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".mov", ".m4v"}:
        return parsed_suffix
    guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip().lower())
    if guessed == ".jpe":
        return ".jpg"
    return guessed or ".bin"


def _positive_int(value: object) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _source_id(candidate: dict, index: int) -> str:
    seed = "|".join([
        _clean_text(candidate.get("url")),
        _clean_text(candidate.get("title")),
        _clean_text(candidate.get("sourceType")),
        str(index),
    ])
    return f"src_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:10]}"


def infer_source_type(candidate: dict) -> str:
    explicit = _clean_text(candidate.get("sourceType") or candidate.get("type")).lower().replace("_", "-")
    if explicit:
        return explicit
    url = _clean_text(candidate.get("url"))
    host = _host(url)
    label = " ".join([
        host,
        _clean_text(candidate.get("title")),
        _clean_text(candidate.get("license")),
        _clean_text(candidate.get("notes")),
    ]).lower()
    if any(term in label for term in ("press kit", "media kit", "newsroom")):
        return "press-image"
    if any(host == domain or host.endswith(f".{domain}") for domain in COMMUNITY_HOST_HINTS):
        if any(term in label for term in ("meme", "reaction", "짤", "밈")):
            return "meme-image"
        return "community-image"
    if ".gif" in label or " gif" in label or "animated" in label:
        if any(term in label for term in ("meme", "reaction", "짤", "밈")):
            return "meme-gif"
        return "internet-gif"
    if any(term in label for term in ("creative commons", "cc-by", "cc0", "wikimedia")):
        if ".gif" in label or " gif" in label:
            return "cc-gif"
        return "cc-video" if any(term in label for term in ("video", ".mp4", "clip")) else "cc-image"
    if "youtube.com" in host or "youtu.be" in host:
        return "original-video"
    if "tiktok.com" in host or "instagram.com" in host:
        return "social-video"
    if host in OFFICIAL_DOMAINS or any(host.endswith(f".{domain}") for domain in OFFICIAL_DOMAINS):
        return "official-page"
    if "ai" in explicit or candidate.get("generated") is True:
        return "ai-generated"
    return "web-page" if url else "unknown"


def _license_text(candidate: dict) -> str:
    return " ".join([
        _clean_text(candidate.get("license")),
        _clean_text(candidate.get("allowedUse")),
        _clean_text(candidate.get("usageRights")),
        _clean_text(candidate.get("notes")),
    ]).lower()


def _community_fit_review(candidate: dict, source_type: str) -> dict:
    """Review whether a web/community image is actually fit for the target edit.

    This is not a downloader. It records the operator/search evidence needed
    before a "community meme/image" can be trusted as a visual choice.
    """
    required = source_type in COMMUNITY_IMAGE_SOURCE_TYPES
    market = _clean_text(candidate.get("targetMarket") or candidate.get("languageMarket") or candidate.get("market"))
    surface = _clean_text(candidate.get("communitySurface") or candidate.get("sourceCommunity") or candidate.get("surface"))
    meme_context = _clean_text(candidate.get("memeContext") or candidate.get("communityContext") or candidate.get("whyThisMemeFits"))
    audience = _clean_text(candidate.get("targetAudience") or candidate.get("audience"))
    freshness = _clean_text(candidate.get("freshnessEvidence") or candidate.get("trendEvidence") or candidate.get("recencyEvidence"))
    layout_fit = _clean_text(candidate.get("layoutFit") or candidate.get("imageLayoutFit") or candidate.get("captionSafeZoneFit"))
    verdict = _clean_text(candidate.get("communityFitVerdict") or candidate.get("audienceFitVerdict")).lower()
    url = _clean_text(candidate.get("url"))
    host = _host(url)
    generated_by_operator = any(
        term in " ".join([
            _clean_text(candidate.get("sourceType")),
            _clean_text(candidate.get("type")),
            _clean_text(candidate.get("owner")),
            _clean_text(candidate.get("source")),
            _clean_text(candidate.get("notes")),
            _clean_text(candidate.get("provenance")),
        ]).lower()
        for term in ("operator-generated", "internal-card", "generated-card", "made-by-operator", "codex-generated")
    )
    if verdict in {"ok", "approved", "good", "fit"}:
        verdict = "pass"
    missing: list[str] = []
    if required:
        if not url:
            missing.append("sourceUrl")
        if generated_by_operator:
            missing.append("realCommunitySourceUrl")
        if host and not any(host == domain or host.endswith(f".{domain}") for domain in COMMUNITY_HOST_HINTS):
            missing.append("recognizedCommunitySurface")
        if market.lower() not in {"kr", "korea", "korean", "us", "usa", "america", "american", "global"}:
            missing.append("targetMarket=KR/US/global")
        if len(surface) < 3:
            missing.append("communitySurface")
        if len(meme_context) < 32:
            missing.append("memeContext>=32")
        if len(audience) < 12:
            missing.append("targetAudience>=12")
        if len(freshness) < 12:
            missing.append("freshnessEvidence>=12")
        if len(layout_fit) < 16:
            missing.append("layoutFit>=16")
        if verdict != "pass":
            missing.append("communityFitVerdict=pass")
    status = "pass" if required and not missing else ("needs-review" if required else "not-required")
    return {
        "required": required,
        "status": status,
        "targetMarket": market,
        "communitySurface": surface,
        "targetAudience": audience,
        "sourceUrl": url,
        "host": host,
        "operatorGenerated": generated_by_operator,
        "memeContext": meme_context,
        "freshnessEvidence": freshness,
        "layoutFit": layout_fit,
        "verdict": verdict,
        "missingFields": missing,
    }


def _source_fetch_review(candidate: dict, source_type: str) -> dict:
    payload = candidate.get("sourceFetch") if isinstance(candidate.get("sourceFetch"), dict) else {}
    source_url = _clean_text(
        payload.get("sourceUrl")
        or payload.get("downloadUrl")
        or candidate.get("sourceUrl")
        or candidate.get("downloadUrl")
        or candidate.get("assetUrl")
        or candidate.get("url")
    )
    local_path = _clean_text(
        payload.get("localPath")
        or payload.get("sourceLocalPath")
        or payload.get("fetchedPath")
        or candidate.get("localPath")
        or candidate.get("sourceLocalPath")
        or candidate.get("fetchedPath")
        or candidate.get("sourcePath")
    )
    sha256 = _clean_text(
        payload.get("sha256")
        or payload.get("sourceSha256")
        or candidate.get("sha256")
        or candidate.get("sourceSha256")
    )
    size_bytes = _positive_int(
        payload.get("sizeBytes")
        or payload.get("bytes")
        or candidate.get("sizeBytes")
        or candidate.get("sourceBytes")
    )
    content_type = _clean_text(payload.get("contentType") or candidate.get("contentType"))
    media_kind = _clean_text(
        payload.get("mediaKind")
        or payload.get("sourceMediaKind")
        or candidate.get("mediaKind")
        or candidate.get("sourceMediaKind")
        or _media_kind(content_type, Path(local_path or source_url).suffix)
    ).lower()
    fetch_status = _clean_text(
        payload.get("status")
        or payload.get("fetchStatus")
        or candidate.get("sourceFetchStatus")
        or candidate.get("fetchStatus")
    ).lower()
    verdict = _clean_text(
        payload.get("verdict")
        or candidate.get("sourceFetchVerdict")
        or candidate.get("sourceAcquisitionVerdict")
    ).lower()
    review = _clean_text(
        payload.get("review")
        or candidate.get("sourceFetchReview")
        or candidate.get("sourceAcquisitionReview")
    )
    required = (
        candidate.get("sourceFetchRequired") is True
        or source_type in INTERNET_ASSET_SOURCE_TYPES
        or bool(payload)
        or bool(local_path or sha256)
    )
    missing: list[str] = []
    if required:
        if not source_url:
            missing.append("sourceUrl")
        if fetch_status not in SOURCE_FETCH_PASS_STATUSES:
            missing.append("sourceFetchStatus=fetched")
        if not local_path:
            missing.append("localPath")
        if len(sha256) < 12:
            missing.append("sha256")
        if size_bytes <= 0:
            missing.append("sizeBytes")
        if media_kind not in SOURCE_FETCH_MEDIA_KINDS:
            missing.append("mediaKind")
        if source_type in INTERNET_MOTION_SOURCE_TYPES and media_kind not in {"gif", "video"}:
            missing.append("motionMediaKind=gif/video")
        if verdict not in {"pass", "approved", "ok", "ready"}:
            missing.append("sourceFetchVerdict=pass")
        if len(review) < 32:
            missing.append("sourceFetchReview>=32")
    status = "pass" if required and not missing else ("needs-fetch" if required else "not-required")
    return {
        "required": required,
        "status": status,
        "sourceUrl": source_url,
        "localPath": local_path,
        "sha256": sha256,
        "sizeBytes": size_bytes,
        "contentType": content_type,
        "mediaKind": media_kind,
        "fetchStatus": fetch_status,
        "verdict": verdict,
        "review": review,
        "motionReady": status == "pass" and media_kind in {"gif", "video"},
        "missingFields": missing,
    }


def _source_context_review(candidate: dict, source_type: str, source_fetch: dict) -> dict:
    context = candidate.get("sourceContext") if isinstance(candidate.get("sourceContext"), dict) else {}
    media_kind = _clean_text(
        context.get("mediaKind")
        or source_fetch.get("mediaKind")
        or candidate.get("mediaKind")
        or candidate.get("sourceMediaKind")
    ).lower()
    required = (
        source_fetch.get("required") is True
        or source_type in {"internet-image", "web-image", "cc-image", "public-domain-image", "wikimedia-image"}
    )
    topic = _clean_text(context.get("topic") or candidate.get("topic") or candidate.get("projectTopic"))
    scene_purpose = _clean_text(
        context.get("scenePurpose")
        or context.get("storyBeat")
        or candidate.get("scenePurpose")
        or candidate.get("storyBeat")
        or candidate.get("evidenceRole")
    )
    viewer_job = _clean_text(
        context.get("viewerJob")
        or context.get("sourceJob")
        or candidate.get("viewerJob")
        or candidate.get("sourceJob")
    )
    intent_role = _clean_text(
        context.get("intentRole")
        or context.get("sceneIntentRole")
        or context.get("sourceIntentRole")
        or candidate.get("intentRole")
        or candidate.get("sceneIntentRole")
        or candidate.get("sourceIntentRole")
    ).lower()
    proof_claim = _clean_text(
        context.get("proofClaim")
        or context.get("sourceProofClaim")
        or context.get("visualProofClaim")
        or candidate.get("proofClaim")
        or candidate.get("sourceProofClaim")
        or candidate.get("visualProofClaim")
    )
    selection_rationale = _clean_text(
        context.get("selectionRationale")
        or context.get("sourceRationale")
        or candidate.get("selectionRationale")
        or candidate.get("sourceRationale")
        or candidate.get("whyUseful")
        or candidate.get("memeContext")
    )
    media_choice = _clean_text(
        context.get("mediaChoiceRationale")
        or context.get("whyGifOrImage")
        or candidate.get("mediaChoiceRationale")
        or candidate.get("whyGifOrImage")
    )
    motion_fit = _clean_text(
        context.get("motionFit")
        or context.get("whyMotionFits")
        or candidate.get("motionFit")
        or candidate.get("whyMotionFits")
    )
    still_fit = _clean_text(
        context.get("stillFit")
        or context.get("whyStillImageFits")
        or candidate.get("stillFit")
        or candidate.get("whyStillImageFits")
    )
    verdict = _clean_text(
        context.get("verdict")
        or context.get("sourceFitVerdict")
        or candidate.get("sourceFitVerdict")
        or candidate.get("contextFitVerdict")
    ).lower()
    if verdict in {"ok", "approved", "good", "fit", "ready"}:
        verdict = "pass"
    missing: list[str] = []
    if required:
        if len(topic) < 8:
            missing.append("sourceContext.topic>=8")
        if len(scene_purpose) < 12:
            missing.append("sourceContext.scenePurpose>=12")
        if len(viewer_job) < 16:
            missing.append("sourceContext.viewerJob>=16")
        if intent_role not in {
            "hook",
            "setup",
            "context",
            "proof",
            "closeup",
            "replay",
            "payoff",
            "callback",
            "contrast",
            "reaction",
        }:
            missing.append("sourceContext.intentRole")
        if len(proof_claim) < 24:
            missing.append("sourceContext.proofClaim>=24")
        if len(selection_rationale) < 40:
            missing.append("sourceContext.selectionRationale>=40")
        if len(media_choice) < 32:
            missing.append("sourceContext.mediaChoiceRationale>=32")
        if media_kind in {"gif", "video"} and len(motion_fit) < 24:
            missing.append("sourceContext.motionFit>=24")
        if media_kind == "image" and len(still_fit) < 24:
            missing.append("sourceContext.stillFit>=24")
        if verdict != "pass":
            missing.append("sourceContext.verdict=pass")
    status = "pass" if required and not missing else ("needs-context" if required else "not-required")
    return {
        "required": required,
        "status": status,
        "topic": topic,
        "scenePurpose": scene_purpose,
        "viewerJob": viewer_job,
        "intentRole": intent_role,
        "proofClaim": proof_claim,
        "selectionRationale": selection_rationale,
        "mediaChoiceRationale": media_choice,
        "motionFit": motion_fit,
        "stillFit": still_fit,
        "mediaKind": media_kind,
        "verdict": verdict,
        "missingFields": missing,
    }


def classify_candidate(candidate: dict, index: int) -> dict:
    source_type = infer_source_type(candidate)
    url = _clean_text(candidate.get("url"))
    role = _clean_text(candidate.get("evidenceRole") or candidate.get("role") or _default_role(source_type))
    license_text = _license_text(candidate)
    provided_allowed = _clean_text(candidate.get("allowedUse")).lower().replace("_", "-")

    risk = "medium"
    allowed_use = "reference-only"
    blockers: list[str] = []
    required_review: list[str] = []

    if provided_allowed:
        allowed_use = provided_allowed
    elif source_type in {"creator-owned", "operator-owned"}:
        allowed_use = "download-edit"
        risk = "low"
    elif source_type in {"public-domain", "cc-video", "cc-image"} or any(term in license_text for term in CC_TERMS):
        allowed_use = "download-edit"
        risk = "low"
        required_review.append("preserve license and attribution in final packet")
    elif source_type in {"official-page", "official-document", "press-image"}:
        allowed_use = "reference-capture"
        risk = "low" if source_type != "press-image" else "medium"
        required_review.append("do not imply download/edit rights unless license says so")
    elif source_type in COMMUNITY_IMAGE_SOURCE_TYPES:
        allowed_use = "community-reference"
        risk = "medium"
        required_review.extend([
            "confirm target-market/community fit before using as a visual beat",
            "use as commentary/context unless license or operator rights allow download-edit",
            "check 9:16 frame fit and caption safe-zone before render",
        ])
    elif source_type in INTERNET_ASSET_SOURCE_TYPES:
        allowed_use = "render-proof-source"
        risk = "medium"
        required_review.extend([
            "verify direct media URL was fetched locally with sha256 before render",
            "treat as source-first proof unless license/owner review upgrades it for upload",
            "keep attribution and source URL in the final source packet",
        ])
    elif source_type in {"original-video", "creator-video", "social-video"}:
        if role in {"commentary-target", "analysis-target", "comparison"}:
            allowed_use = "commentary-reference"
            risk = "medium"
            required_review.append("TTS/commentary must add a clear argument, critique, explanation, or comparison")
        else:
            allowed_use = "reference-only"
            risk = "high"
            blockers.append("third-party video cannot be used as B-roll without commentary/permission")
    elif source_type == "ai-generated":
        allowed_use = "ai-fill"
        risk = "medium"
        if role in {"fact-proof", "visual-proof", "commentary-target"}:
            blockers.append("AI-generated source cannot be the factual/original evidence source")
    else:
        required_review.append("operator must confirm source owner, license, and usable role")

    if any(term in license_text for term in DOWNLOAD_EDIT_TERMS):
        allowed_use = "download-edit"
        risk = "low" if not blockers else risk

    community_fit = _community_fit_review(candidate, source_type)
    source_fetch = _source_fetch_review(candidate, source_type)
    source_context = _source_context_review(candidate, source_type, source_fetch)
    can_become_visual_asset = allowed_use in {"download-edit", "ai-fill"} and not blockers
    if community_fit["required"] and community_fit["status"] == "pass" and allowed_use in {"community-reference", "download-edit"}:
        can_become_visual_asset = allowed_use == "download-edit" and not community_fit["operatorGenerated"]
    can_become_context_asset = (
        community_fit["required"]
        and community_fit["status"] == "pass"
        and not community_fit["operatorGenerated"]
    ) or (source_fetch["status"] == "pass" and source_context["status"] == "pass")
    can_become_render_source_asset = (
        source_fetch["status"] == "pass"
        and source_context["status"] == "pass"
        and not community_fit["operatorGenerated"]
    )

    return {
        "sourceId": _source_id(candidate, index),
        "type": source_type,
        "url": url,
        "title": _clean_text(candidate.get("title"), f"Source {index + 1}"),
        "owner": _clean_text(candidate.get("owner") or candidate.get("source") or _host(url)),
        "license": _clean_text(candidate.get("license") or candidate.get("usageRights") or "unknown"),
        "allowedUse": allowed_use,
        "evidenceRole": role,
        "risk": risk,
        "whyUseful": _clean_text(candidate.get("whyUseful") or candidate.get("summary") or candidate.get("notes")),
        "requiresReview": required_review,
        "blockers": blockers,
        "communityFit": community_fit,
        "sourceFetch": source_fetch,
        "sourceContextFit": source_context,
        "canBecomeVisualAsset": can_become_visual_asset,
        "canBecomeContextAsset": can_become_context_asset,
        "canBecomeRenderSourceAsset": can_become_render_source_asset,
        "canBecomeMotionSourceAsset": can_become_render_source_asset and source_fetch["motionReady"],
        "canBecomeEvidence": role in {"fact-proof", "visual-proof", "commentary-target", "analysis-target", "comparison"} and source_type != "ai-generated",
    }


def _default_role(source_type: str) -> str:
    if source_type in {"official-page", "official-document", "news-article", "web-page"}:
        return "fact-proof"
    if source_type in {"original-video", "creator-video", "social-video"}:
        return "commentary-target"
    if source_type in {"press-image", "cc-video", "public-domain", "creator-owned", "cc-gif", "public-domain-gif"}:
        return "visual-proof"
    if source_type in INTERNET_ASSET_SOURCE_TYPES:
        return "cutaway"
    if source_type == "ai-generated":
        return "cutaway"
    return "reference"


def _source_needs(format_type: str) -> list[dict]:
    return FORMAT_SOURCE_NEEDS.get(format_type, FORMAT_SOURCE_NEEDS["explainer"])


def _search_queries(topic: str, format_type: str) -> list[dict]:
    topic = topic or "topic"
    return [
        {"rail": "official", "query": f"{topic} official site press release facts"},
        {"rail": "original-video", "query": f"{topic} original video interview clip source"},
        {"rail": "rights-safe-media", "query": f"{topic} press kit media kit creative commons video image"},
        {"rail": "internet-meme-gif", "query": f"{topic} reaction meme gif public domain creative commons wikimedia"},
        {"rail": "kr-community-image", "query": f"{topic} 한국 커뮤니티 짤 반응 밈 디시 더쿠 에펨코리아"},
        {"rail": "us-community-image", "query": f"{topic} reddit meme reaction image community context"},
        {"rail": "context", "query": f"{topic} explainer timeline ranking comparison source"},
        {"rail": "format-reference", "query": f"{format_type} Shorts reference voiceover source commentary {topic}"},
    ]


def _rights_gate(candidates: list[dict]) -> dict:
    blockers = []
    warnings = []
    evidence = [item for item in candidates if item["canBecomeEvidence"]]
    visual = [item for item in candidates if item["canBecomeVisualAsset"]]
    context_visual = [item for item in candidates if item.get("canBecomeContextAsset")]
    render_source = [item for item in candidates if item.get("canBecomeRenderSourceAsset")]
    motion_source = [item for item in candidates if item.get("canBecomeMotionSourceAsset")]
    commentary = [item for item in candidates if item["allowedUse"] == "commentary-reference"]
    fact = [item for item in candidates if item["evidenceRole"] == "fact-proof" and item["canBecomeEvidence"]]
    for item in candidates:
        blockers.extend(f"{item['sourceId']}: {blocker}" for blocker in item["blockers"])
        if item["risk"] == "high":
            warnings.append(f"{item['sourceId']}: high-rights-risk reference only")
    if not evidence:
        blockers.append("no usable evidence source; collect official/news/original commentary target before storyboard")
    if not (visual or commentary or render_source):
        blockers.append("no visual/editable/commentary source; collect owned/CC/public-domain media or commentary target")
    if not fact:
        warnings.append("no fact-proof source yet; TTS must not make unsupported claims")
    status = "blocked" if blockers else "pilot-ready"
    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "counts": {
            "total": len(candidates),
            "evidenceReady": len(evidence),
            "visualAssetReady": len(visual),
            "contextAssetReady": len(context_visual),
            "renderSourceReady": len(render_source),
            "motionSourceReady": len(motion_source),
            "commentaryReference": len(commentary),
            "factProof": len(fact),
            "highRisk": sum(1 for item in candidates if item["risk"] == "high"),
        },
    }


def _download_direct_asset(url: str, *, max_bytes: int = MAX_DIRECT_ASSET_BYTES, timeout: int = 20) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source URL must be http(s) with a host")
    host = _host(url)
    if not _host_is_public(host):
        raise ValueError("source URL host must resolve to a public address")
    request = Request(
        url,
        headers={
            "User-Agent": "VideoStudioSourceFetcher/1.0 (+https://local.video-studio)",
            "Accept": "image/gif,image/*,video/*,*/*;q=0.2",
        },
    )
    try:
        # urlopen follows 3xx by default; _SOURCE_OPENER re-checks every redirect
        # host so a CDN/open-redirect cannot reach an internal address (SSRF).
        with _SOURCE_OPENER.open(request, timeout=timeout) as response:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"source asset exceeds {max_bytes} bytes")
                chunks.append(chunk)
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            final_url = str(getattr(response, "url", url) or url)
    except HTTPError as exc:
        exc.close()  # HTTPError is a file-like response; close it so a failed fetch doesn't leak the handle
        raise ValueError(f"source URL returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"source URL fetch failed: {exc.reason}") from exc
    data = b"".join(chunks)
    if not data:
        raise ValueError("source URL returned an empty body")
    media_kind = _media_kind(content_type, Path(urlparse(final_url).path).suffix)
    if media_kind not in SOURCE_FETCH_MEDIA_KINDS:
        raise ValueError(f"unsupported source content type: {content_type or 'unknown'}")
    return {
        "bytes": data,
        "contentType": content_type,
        "finalUrl": final_url,
        "mediaKind": media_kind,
    }


def _candidate_download_url(candidate: dict) -> str:
    return _clean_text(candidate.get("downloadUrl") or candidate.get("assetUrl") or candidate.get("sourceUrl") or candidate.get("url"))


def _source_fetch_error(candidate: dict, message: str) -> dict:
    candidate["sourceFetch"] = {
        "required": True,
        "status": "failed",
        "verdict": "fail",
        "error": message,
        "sourceUrl": _candidate_download_url(candidate),
        "missingFields": [message],
    }
    candidate["sourceFetchStatus"] = "failed"
    candidate["sourceFetchVerdict"] = "fail"
    return candidate


def fetch_editorial_source_assets(payload: dict, project_root: Path | str) -> dict:
    """Fetch operator-approved direct media URLs and return a classified source plan."""
    root = Path(project_root)
    project_id = _slug(payload.get("projectId") or payload.get("topic") or "internet-meme-gif-proof")
    acquisition_dir = root / "storage" / "source-acquisition" / project_id
    raw_dir = acquisition_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    raw_candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    operator_approved = payload.get("operatorApprovedSourceFetch") is True
    fetched_candidates: list[dict] = []
    ledger_items: list[dict] = []

    for index, raw_candidate in enumerate(raw_candidates):
        candidate = dict(raw_candidate) if isinstance(raw_candidate, dict) else {"url": str(raw_candidate)}
        candidate["sourceFetchRequired"] = True
        url = _candidate_download_url(candidate)
        source_id = _source_id(candidate, index)
        if not (operator_approved or candidate.get("operatorApprovedSourceFetch") is True):
            fetched_candidates.append(_source_fetch_error(candidate, "operatorApprovedSourceFetch=true"))
            continue
        if not url:
            fetched_candidates.append(_source_fetch_error(candidate, "downloadUrl/sourceUrl"))
            continue
        try:
            downloaded = _download_direct_asset(url)
            content_type = downloaded["contentType"]
            final_url = downloaded["finalUrl"]
            media_kind = downloaded["mediaKind"]
            suffix = _extension_for_asset(final_url, content_type)
            file_name = f"{index + 1:02d}-{_safe_filename(candidate.get('title') or source_id)}{suffix}"
            target_path = raw_dir / file_name
            data = downloaded["bytes"]
            target_path.write_bytes(data)
            sha256 = hashlib.sha256(data).hexdigest()
            relative_path = _project_relative(root, target_path)
            review = (
                "Operator-approved direct internet media fetch saved the local source file, "
                "sha256, byte size, content type, and original URL before render."
            )
            source_fetch = {
                "required": True,
                "status": "fetched",
                "verdict": "pass",
                "sourceUrl": url,
                "finalUrl": final_url,
                "localPath": relative_path,
                "sha256": sha256,
                "sizeBytes": len(data),
                "contentType": content_type,
                "mediaKind": media_kind,
                "fetchedAt": _utc_now(),
                "review": review,
            }
            candidate.update({
                "sourceFetch": source_fetch,
                "sourceFetchStatus": "fetched",
                "sourceFetchVerdict": "pass",
                "sourceFetchReview": review,
                "sourceLocalPath": relative_path,
                "localPath": relative_path,
                "sourcePath": relative_path,
                "sourceSha256": sha256,
                "sha256": sha256,
                "sourceBytes": len(data),
                "sizeBytes": len(data),
                "contentType": content_type,
                "sourceMediaKind": media_kind,
                "mediaKind": media_kind,
            })
            ledger_items.append({
                "sourceId": source_id,
                "title": _clean_text(candidate.get("title"), source_id),
                "sourceUrl": url,
                "finalUrl": final_url,
                "localPath": relative_path,
                "sha256": sha256,
                "sizeBytes": len(data),
                "contentType": content_type,
                "mediaKind": media_kind,
                "status": "fetched",
            })
        except Exception as exc:
            fetched_candidates.append(_source_fetch_error(candidate, str(exc)))
            ledger_items.append({
                "sourceId": source_id,
                "title": _clean_text(candidate.get("title"), source_id),
                "sourceUrl": url,
                "status": "failed",
                "error": str(exc),
            })
            continue
        fetched_candidates.append(candidate)

    plan_payload = dict(payload)
    plan_payload["projectId"] = project_id
    plan_payload["candidates"] = fetched_candidates
    plan = build_editorial_source_plan(plan_payload)
    ledger = {
        "schema": "video-studio.editorial-source-fetch-ledger.v1",
        "projectId": project_id,
        "createdAt": _utc_now(),
        "operatorApprovedSourceFetch": operator_approved,
        "summary": {
            "candidateCount": len(raw_candidates),
            "fetchedCount": sum(1 for item in ledger_items if item.get("status") == "fetched"),
            "failedCount": sum(1 for item in ledger_items if item.get("status") == "failed"),
        },
        "items": ledger_items,
    }
    ledger_path = acquisition_dir / "source-fetch-ledger.json"
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    plan["sourceFetchLedger"] = ledger
    plan["sourceFetchLedgerPath"] = _project_relative(root, ledger_path)
    return plan


def _storyboard_bindings(candidates: list[dict], format_type: str) -> list[dict]:
    fact = [item for item in candidates if item["evidenceRole"] == "fact-proof" and item["canBecomeEvidence"]]
    commentary = [item for item in candidates if item["allowedUse"] == "commentary-reference"]
    visual = [item for item in candidates if item["canBecomeVisualAsset"] and item["type"] != "ai-generated"]
    render_source = [item for item in candidates if item.get("canBecomeRenderSourceAsset")]
    ai_fill = [item for item in candidates if item["allowedUse"] == "ai-fill"]
    bindings = [
        {
            "sceneId": "scene-001",
            "purpose": "hook-context",
            "sourceRole": "evidence-source",
            "candidateSourceIds": [item["sourceId"] for item in (fact or commentary)[:2]],
            "ttsJob": "state what the viewer is about to learn and cite the evidence source, not a generic advice line",
            "captionJob": "one compact hook only",
        },
        {
            "sceneId": "scene-002",
            "purpose": "original-or-official-proof",
            "sourceRole": "visual-source",
            "candidateSourceIds": [item["sourceId"] for item in (commentary or visual or render_source or fact)[:2]],
            "ttsJob": "explain what the source shows and why it matters",
            "captionJob": "label the evidence, not the whole sentence",
        },
        {
            "sceneId": "scene-003",
            "purpose": "comparison-or-ranking",
            "sourceRole": "analysis-source",
            "candidateSourceIds": [item["sourceId"] for item in (fact + visual + render_source + commentary)[:3]],
            "ttsJob": "add the creator's comparison, ranking reason, or interpretation",
            "captionJob": "show the comparison term or number only",
        },
        {
            "sceneId": "scene-004",
            "purpose": "takeaway",
            "sourceRole": "ai-fill" if ai_fill else "evidence-recap",
            "candidateSourceIds": [item["sourceId"] for item in (ai_fill or fact or visual)[:2]],
            "ttsJob": "leave one concrete takeaway from the sources",
            "captionJob": "short payoff, optional",
        },
    ]
    if format_type == "commentary":
        bindings[1]["sourceRole"] = "commentary-target"
    return bindings


def build_editorial_source_plan(payload: dict) -> dict:
    topic = _clean_text(payload.get("topic") or payload.get("prompt"), "Untitled source-first video")
    format_type = _clean_text(payload.get("format") or payload.get("templateType"), "explainer").lower().replace("_", "-")
    if format_type not in FORMAT_SOURCE_NEEDS:
        format_type = "explainer"
    project_id = _slug(payload.get("projectId") or topic)
    raw_candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    candidates = [classify_candidate(item if isinstance(item, dict) else {"url": str(item)}, idx) for idx, item in enumerate(raw_candidates)]
    rights_gate = _rights_gate(candidates)
    return {
        "schema": SCHEMA,
        "projectId": project_id,
        "createdAt": _utc_now(),
        "topic": topic,
        "format": format_type,
        "sourceBrief": {
            "goal": "Build the storyboard from evidence/original sources first; use AI only as cutaway/fill unless explicitly styled as AI.",
            "needs": _source_needs(format_type),
            "uploadCandidateRule": "source-loop proof is not upload readiness; upload candidates require rights-safe sources, clear commentary, and source-role bindings.",
        },
        "searchRail": _search_queries(topic, format_type),
        "candidates": candidates,
        "rightsGate": rights_gate,
        "storyboardBindings": _storyboard_bindings(candidates, format_type),
        "sourceLibraryPromotionPlan": {
            "target": "episode source-library after operator import/review",
            "steps": [
                "collect official/fact-proof URLs and rights-safe visual candidates",
                "save local files only when license/ownership allows download-edit or when operator owns the file",
                "import eligible media into episode source-library with provenance",
                "bind accepted source IDs to storyboard scenes before render",
            ],
            "notAllowed": [
                "treating a URL list as accepted source assets",
                "using third-party social clips as B-roll without commentary/permission",
                "using AI-generated media as factual proof",
            ],
        },
        "renderRolePolicy": {
            "evidence-source": "official/news/original source carries the factual claim",
            "visual-source": "owned/CC/public-domain/press-safe media carries the visible proof",
            "commentary-target": "third-party original can appear only with clear TTS commentary/analysis and rights review",
            "ai-fill": "AI media can bridge mood/cutaway but cannot pretend to be original evidence",
        },
    }
