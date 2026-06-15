import json
from pathlib import Path

from worker.bridge.server import app
from worker.sources.editorial import build_editorial_source_plan, fetch_editorial_source_assets


def test_editorial_source_plan_separates_official_original_and_ai_roles():
    plan = build_editorial_source_plan({
        "projectId": "source-first-pilot",
        "topic": "AI-generated Shorts quality pipeline",
        "format": "explainer",
        "candidates": [
            {
                "type": "official-page",
                "url": "https://support.google.com/youtube/answer/1311392",
                "title": "YouTube monetization policies",
                "evidenceRole": "fact-proof",
                "whyUseful": "Defines original/authentic and reused content risk.",
            },
            {
                "type": "original-video",
                "url": "https://youtube.com/watch?v=example",
                "title": "Reference creator clip",
                "evidenceRole": "commentary-target",
                "whyUseful": "A clip to explain, not raw B-roll.",
            },
            {
                "type": "ai-generated",
                "title": "AI transition cutaway",
                "evidenceRole": "cutaway",
                "whyUseful": "Only fills mood between proof sources.",
            },
        ],
    })

    assert plan["schema"] == "video-studio.editorial-source-plan.v1"
    assert plan["rightsGate"]["status"] == "pilot-ready"
    official, original, ai_fill = plan["candidates"]
    assert official["allowedUse"] == "reference-capture"
    assert official["canBecomeEvidence"] is True
    assert original["allowedUse"] == "commentary-reference"
    assert original["canBecomeVisualAsset"] is False
    assert ai_fill["allowedUse"] == "ai-fill"
    assert ai_fill["canBecomeEvidence"] is False
    assert any(item["sourceRole"] == "visual-source" for item in plan["storyboardBindings"])
    assert plan["sourceLibraryPromotionPlan"]["target"] == "episode source-library after operator import/review"


def test_editorial_source_plan_blocks_social_broll_without_commentary():
    plan = build_editorial_source_plan({
        "topic": "desk routine",
        "format": "explainer",
        "candidates": [
            {
                "type": "social-video",
                "url": "https://www.tiktok.com/@creator/video/123",
                "title": "Routine clip",
                "evidenceRole": "visual-proof",
            }
        ],
    })

    assert plan["rightsGate"]["status"] == "blocked"
    assert "third-party video cannot be used as B-roll" in " ".join(plan["rightsGate"]["blockers"])
    assert plan["candidates"][0]["allowedUse"] == "reference-only"
    assert plan["candidates"][0]["risk"] == "high"


def test_editorial_source_plan_requires_community_image_fit_review():
    plan = build_editorial_source_plan({
        "topic": "AI Shorts feel fake",
        "format": "explainer",
        "candidates": [
            {
                "type": "meme-image",
                "url": "https://www.reddit.com/r/example/comments/123/reaction_image",
                "title": "Reaction image",
                "evidenceRole": "cutaway",
            },
            {
                "type": "community-image",
                "url": "https://www.reddit.com/r/example/comments/456/viewer_context",
                "title": "Viewer context image",
                "evidenceRole": "cutaway",
                "targetMarket": "US",
                "communitySurface": "Reddit creator and social-media discussion threads",
                "targetAudience": "Short-form creators comparing AI-only videos with source-led edits",
                "memeContext": "The image represents the viewer's actual scrolling context, so it supports the argument instead of acting as random decoration.",
                "freshnessEvidence": "Operator/web-search review found it inside current community discussion for this topic.",
                "layoutFit": "Subject sits above the lower caption band and can be staged safely in a 9:16 crop.",
                "communityFitVerdict": "pass",
            },
        ],
    })

    missing, ready = plan["candidates"]
    assert missing["communityFit"]["required"] is True
    assert missing["communityFit"]["status"] == "needs-review"
    assert "communityFitVerdict=pass" in missing["communityFit"]["missingFields"]
    assert ready["communityFit"]["status"] == "pass"
    assert ready["canBecomeContextAsset"] is True
    assert any(item["rail"] == "kr-community-image" for item in plan["searchRail"])
    assert any(item["rail"] == "us-community-image" for item in plan["searchRail"])


def test_editorial_source_plan_rejects_operator_generated_fake_meme_as_context_asset():
    plan = build_editorial_source_plan({
        "topic": "AI Shorts feel fake",
        "format": "explainer",
        "candidates": [
            {
                "type": "meme-image",
                "title": "Internally drawn reaction card",
                "owner": "operator-generated",
                "evidenceRole": "cutaway",
                "targetMarket": "US",
                "communitySurface": "Internal render card",
                "targetAudience": "Short-form creators comparing AI-only videos with source-led edits",
                "memeContext": "This claims to represent a meme beat but was not found from an actual community surface.",
                "freshnessEvidence": "No web/community source was found; the operator made a substitute card.",
                "layoutFit": "The card would fit the 9:16 frame but it is not a real community image.",
                "communityFitVerdict": "pass",
            },
            {
                "type": "meme-image",
                "url": "https://programmerhumor.io/artificial-intelligence-memes/ai-slop-everywhere/",
                "title": "AI slop everywhere",
                "evidenceRole": "cutaway",
                "targetMarket": "US",
                "communitySurface": "ProgrammerHumor AI meme page",
                "targetAudience": "Short-form creators and viewers reacting to generic AI-generated content",
                "memeContext": "The image directly maps to a beat about viewers recognizing low-effort AI slop instead of useful source-led content.",
                "freshnessEvidence": "Web-search candidate from a live AI meme page; operator still needs rights review before render use.",
                "layoutFit": "The image needs a contained 9:16 crop and should not sit under lower captions.",
                "communityFitVerdict": "pass",
            },
        ],
    })

    fake, real = plan["candidates"]
    assert fake["communityFit"]["status"] == "needs-review"
    assert "sourceUrl" in fake["communityFit"]["missingFields"]
    assert "realCommunitySourceUrl" in fake["communityFit"]["missingFields"]
    assert fake["canBecomeContextAsset"] is False
    assert real["communityFit"]["status"] == "pass"
    assert real["canBecomeContextAsset"] is True
    assert real["canBecomeVisualAsset"] is False


def test_editorial_source_route_persists_pilot_plan(tmp_path, monkeypatch):
    from worker.bridge import routes_sources

    monkeypatch.setattr(routes_sources, "_project_root", tmp_path)
    response = app.test_client().post(
        "/api/sources/editorial/pilot",
        json={
            "projectId": "route-source-first-pilot",
            "topic": "creator commentary format",
            "format": "commentary",
            "candidates": [
                {
                    "type": "original-video",
                    "url": "https://youtube.com/watch?v=abc",
                    "title": "Original clip",
                    "evidenceRole": "commentary-target",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["sourcePlan"]["rightsGate"]["status"] == "pilot-ready"
    plan_path = tmp_path / payload["sourcePlanPath"]
    assert plan_path.exists()
    saved = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    assert saved["projectId"] == "route-source-first-pilot"
    assert saved["storyboardBindings"][1]["sourceRole"] == "commentary-target"


def test_editorial_source_fetch_downloads_direct_gif_with_ledger(tmp_path, monkeypatch):
    from worker.sources import editorial

    monkeypatch.setattr(
        editorial,
        "_download_direct_asset",
        lambda _url: {
            "bytes": b"GIF89a-test-motion-bytes",
            "contentType": "image/gif",
            "finalUrl": "https://upload.wikimedia.org/example/reaction.gif",
            "mediaKind": "gif",
        },
    )

    plan = fetch_editorial_source_assets(
        {
            "projectId": "route-internet-gif-proof",
            "topic": "AI slop reaction GIF",
            "format": "explainer",
            "operatorApprovedSourceFetch": True,
            "candidates": [
                {
                    "type": "meme-gif",
                    "url": "https://upload.wikimedia.org/example/reaction.gif",
                    "title": "Public domain reaction GIF",
                    "license": "Public domain",
                    "evidenceRole": "cutaway",
                    "targetMarket": "global",
                    "communitySurface": "Wikimedia Commons direct media",
                    "targetAudience": "Creators comparing source-led edits with generic AI output",
                    "memeContext": "The animated reaction beat gives the viewer a real source object instead of an internal substitute card.",
                    "freshnessEvidence": "Operator selected this direct media URL during source acquisition review.",
                    "layoutFit": "The moving subject can be center-cropped safely while captions stay in the top or lower safe zone.",
                    "communityFitVerdict": "pass",
                    "sourceContext": {
                        "topic": "AI slop reaction GIF",
                        "scenePurpose": "show the viewer reaction to generic AI-only Shorts",
                        "viewerJob": "make the fake-card problem immediately visible before the explanation",
                        "intentRole": "reaction",
                        "proofClaim": "The GIF motion proves the viewer rejection beat more clearly than a static substitute card.",
                        "selectionRationale": "The fetched GIF is used only for the reaction beat because the motion makes the viewer's rejection legible.",
                        "mediaChoiceRationale": "A GIF is selected here because the moving reaction is the evidence; a still image would weaken the beat.",
                        "motionFit": "The looped reaction motion carries the joke and the critique.",
                        "verdict": "pass",
                    },
                }
            ],
        },
        tmp_path,
    )

    candidate = plan["candidates"][0]
    assert candidate["sourceFetch"]["status"] == "pass"
    assert candidate["sourceFetch"]["mediaKind"] == "gif"
    assert candidate["sourceContextFit"]["status"] == "pass"
    assert candidate["canBecomeRenderSourceAsset"] is True
    assert candidate["canBecomeMotionSourceAsset"] is True
    assert plan["rightsGate"]["counts"]["motionSourceReady"] == 1
    ledger_path = tmp_path / plan["sourceFetchLedgerPath"]
    assert ledger_path.exists()
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["summary"]["fetchedCount"] == 1
    assert (tmp_path / candidate["sourceFetch"]["localPath"]).exists()


def test_editorial_source_fetch_requires_scene_context_before_render_promotion(tmp_path, monkeypatch):
    from worker.sources import editorial

    monkeypatch.setattr(
        editorial,
        "_download_direct_asset",
        lambda _url: {
            "bytes": b"GIF89a-test-motion-bytes",
            "contentType": "image/gif",
            "finalUrl": "https://upload.wikimedia.org/example/random.gif",
            "mediaKind": "gif",
        },
    )

    plan = fetch_editorial_source_assets(
        {
            "projectId": "route-internet-gif-no-context",
            "topic": "AI slop reaction GIF",
            "operatorApprovedSourceFetch": True,
            "candidates": [
                {
                    "type": "meme-gif",
                    "url": "https://upload.wikimedia.org/example/random.gif",
                    "title": "Random fetched GIF",
                    "license": "Public domain",
                    "evidenceRole": "cutaway",
                }
            ],
        },
        tmp_path,
    )

    candidate = plan["candidates"][0]
    assert candidate["sourceFetch"]["status"] == "pass"
    assert candidate["sourceContextFit"]["status"] == "needs-context"
    assert "sourceContext.scenePurpose>=12" in candidate["sourceContextFit"]["missingFields"]
    assert candidate["canBecomeRenderSourceAsset"] is False
    assert plan["rightsGate"]["counts"]["motionSourceReady"] == 0


def test_editorial_source_fetch_route_requires_approval(tmp_path, monkeypatch):
    from worker.bridge import routes_sources

    monkeypatch.setattr(routes_sources, "_project_root", tmp_path)
    response = app.test_client().post(
        "/api/sources/editorial/fetch",
        json={
            "projectId": "fetch-without-approval",
            "candidates": [{"type": "meme-gif", "url": "https://example.com/reaction.gif"}],
        },
    )

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_source_download_blocks_redirect_to_internal_host():
    """Regression: a direct-asset fetch must not follow a 3xx redirect to an
    internal address. urlopen follows redirects by default, so _SOURCE_OPENER's
    handler re-checks every hop — an open-redirect/spoofed response cannot reach
    a loopback or cloud-metadata service (SSRF). Numeric IPs keep this offline."""
    from http.client import HTTPMessage
    from urllib.request import Request

    from worker.sources.editorial import _BlockInternalRedirect

    handler = _BlockInternalRedirect()
    req = Request("https://start.example.com/asset.gif")

    # Loopback and cloud-metadata link-local redirect targets → blocked (None).
    assert handler.redirect_request(req, None, 302, "Found", HTTPMessage(), "http://127.0.0.1:5161/admin") is None
    assert handler.redirect_request(req, None, 302, "Found", HTTPMessage(), "http://169.254.169.254/latest/meta-data") is None

    # Public redirect target → delegated to the default handler (not blocked).
    allowed = handler.redirect_request(req, None, 302, "Found", HTTPMessage(), "https://1.1.1.1/asset.gif")
    assert allowed is not None


def test_media_kind_rejects_non_media_content_type_at_media_suffix():
    """Regression: a `.gif` URL that responds with text/html must NOT be classified
    as a gif (fail-open). An explicit non-media content-type overrides a media-looking
    suffix; generic content-types still fall back to the suffix so legit CDNs work."""
    from worker.sources.editorial import _media_kind

    # Explicit non-media content-type at a media suffix → rejected (empty kind).
    assert _media_kind("text/html", ".gif") == ""
    assert _media_kind("text/html; charset=utf-8", ".mp4") == ""
    assert _media_kind("application/json", ".gif") == ""
    assert _media_kind("application/xhtml+xml", ".png") == ""
    # Allowlist (not denylist): any specific non-media type is rejected, not just text/*.
    assert _media_kind("application/pdf", ".gif") == ""
    assert _media_kind("application/zip", ".mp4") == ""

    # Legit media content-type → classified.
    assert _media_kind("image/gif", ".gif") == "gif"
    assert _media_kind("video/mp4", ".mp4") == "video"
    assert _media_kind("image/png", ".png") == "image"

    # Generic/empty content-type + good suffix → still trusted (no false reject).
    assert _media_kind("application/octet-stream", ".gif") == "gif"
    assert _media_kind("", ".mp4") == "video"


def test_source_fetch_rejects_weak_operator_approved_flag(tmp_path, monkeypatch):
    """Regression: the engine gate must require explicit operatorApprovedSourceFetch.
    A candidate carrying only the weak generic `operatorApproved` flag (which other
    flows set for unrelated review purposes) must NOT trigger a download. We spy on
    _download_direct_asset: if the gate is reverted to honor the weak flag, it gets
    called → AssertionError → test fails (genuine red-green, no network)."""
    import worker.sources.editorial as editorial

    # Record calls instead of raising — the engine wraps the download in a broad
    # try/except, which would swallow an AssertionError raised here. Asserting on
    # the recorded calls OUTSIDE the function is the real red-green signal.
    calls = []

    def _spy(url, **_kwargs):
        calls.append(url)
        raise RuntimeError("download blocked by test spy")

    monkeypatch.setattr(editorial, "_download_direct_asset", _spy)

    plan = editorial.fetch_editorial_source_assets(
        {
            "projectId": "weak-flag-gate-test",
            # NOTE: no top-level operatorApprovedSourceFetch.
            "candidates": [
                {"type": "meme-gif", "url": "https://example.com/x.gif", "operatorApproved": True},
            ],
        },
        tmp_path,
    )
    # Gate must reject the weak-flag-only candidate BEFORE any download is attempted.
    assert calls == []
    assert plan["candidates"][0]["canBecomeRenderSourceAsset"] is False


def test_source_opener_has_internal_redirect_block_wired():
    """The actual download path (_download_direct_asset opens via _SOURCE_OPENER) must
    have the SSRF redirect guard installed — not just the handler class existing in
    isolation. Guards against the opener being rebuilt without the handler."""
    from worker.sources.editorial import _SOURCE_OPENER, _BlockInternalRedirect

    assert any(isinstance(h, _BlockInternalRedirect) for h in _SOURCE_OPENER.handlers)
