from __future__ import annotations

from flask import Flask

from worker.bridge.grok_browser_proof import classify_grok_browser_surface
from worker.bridge.routes_gates import gates_bp
from worker.bridge.thin_production_loop import build_thin_loop_status


def _base_packet() -> dict:
    return {
        "material": {
            "materialId": "mat-thin-loop",
            "title": "AI 영상 제작 dry-run에서 막히는 지점",
            "sourceLedger": [
                {"sourceId": "search-01", "sourceType": "google-search", "url": "https://example.com/search"}
            ],
        },
        "dryrunPreflight": {"targetStage": "rough-cut", "dryrunAllowed": True},
    }


def _complete_packet() -> dict:
    packet = _base_packet()
    packet.update(
        {
            "sourceReview": {"acceptedSources": [{"sceneId": "scene-01", "assetPath": "storage/source.mp4"}]},
            "renderCandidate": {
                "manifestPath": "storage/renders/demo/manifest.json",
                "outputPath": "storage/renders/demo/demo.mp4",
            },
            "phoneReview": {
                "reviewerDecision": "accepted",
                "fullWatchCompleted": True,
                "phoneViewport": True,
                "reviewSnapshotPath": "storage/final-videos/demo/phone-review.jpg",
            },
        }
    )
    return packet


def test_grok_browser_proof_rejects_chat_redirect_as_success():
    redirect = classify_grok_browser_surface(
        "https://grok.com/c/123",
        generation_observed=True,
        asset_imported=True,
    )
    imagine_visible = classify_grok_browser_surface("https://grok.com/imagine")
    success = classify_grok_browser_surface(
        "https://grok.com/imagine",
        generation_observed=True,
        asset_imported=True,
    )

    assert redirect["status"] == "blocked"
    assert redirect["isChatRedirect"] is True
    assert redirect["success"] is False
    assert imagine_visible["status"] == "surface-visible"
    assert imagine_visible["success"] is False
    assert success["status"] == "success"
    assert success["success"] is True


def test_thin_loop_requires_source_render_and_phone_review_before_publish():
    status = build_thin_loop_status(_base_packet())

    assert status["schema"] == "video-studio.thin-production-loop.v1"
    assert status["currentStage"] == "source-accepted"
    assert status["publishGate"]["status"] == "blocked"
    assert status["publishGate"]["reason"] == "phone-review-required-before-publish"


def test_thin_loop_rejects_grok_chat_redirect_source_proof():
    packet = _base_packet()
    packet["sourceReview"] = {
        "browserProof": {
            "currentUrl": "https://grok.com/c/abc",
            "generationObserved": True,
            "assetImported": True,
        }
    }

    status = build_thin_loop_status(packet)

    source_stage = next(stage for stage in status["stages"] if stage["stage"] == "source-accepted")
    assert source_stage["status"] == "blocked"
    assert "grokImagineSurface" in source_stage["failedChecks"]


def test_thin_loop_passes_after_phone_full_watch_but_still_requires_publish_packet():
    status = build_thin_loop_status(_complete_packet())

    assert status["overallStatus"] == "pass"
    assert status["currentStage"] == "phone-review"
    assert status["publishGate"]["status"] == "pending"
    assert status["publishGate"]["allowed"] is False
    assert status["publishGate"]["reason"] == "phone-review-passed-publish-packet-required"


def test_thin_loop_route_evaluates_posted_packet():
    app = Flask(__name__)
    app.register_blueprint(gates_bp)
    response = app.test_client().post("/api/production/thin-loop/status", json=_complete_packet())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["thinLoop"]["overallStatus"] == "pass"
