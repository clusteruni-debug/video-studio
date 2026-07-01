from __future__ import annotations

import json

from flask import Flask

from worker.bridge import routes_human_operator
from worker.bridge.routes_human_operator import human_operator_bp


def _ready_probe(name: str) -> dict:
    return {
        "name": name,
        "ready": True,
        "path": f"/usr/bin/{name}",
        "version": f"{name} test-version",
        "detail": "ok",
    }


def _client(tmp_path, monkeypatch, *, ffmpeg_ready: bool = True):
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(routes_human_operator, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(routes_human_operator, "_command_probe", _ready_probe)
    monkeypatch.setattr(
        routes_human_operator,
        "probe_tool",
        lambda name, project_root: type(
            "Probe",
            (),
            {
                "to_dict": lambda self: {
                    "name": name,
                    "ready": ffmpeg_ready,
                    "path": f"/usr/bin/{name}" if ffmpeg_ready else None,
                    "resolvedPath": f"/usr/bin/{name}" if ffmpeg_ready else None,
                    "version": f"{name} test-version" if ffmpeg_ready else None,
                    "detail": "ok" if ffmpeg_ready else "tool not found",
                }
            },
        )(),
    )
    monkeypatch.delenv("VIDEO_STUDIO_ALLOW_PAID_PROVIDERS", raising=False)
    app = Flask(__name__)
    app.register_blueprint(human_operator_bp)
    return app.test_client()


def test_human_operator_setup_status_is_no_llm_ready_when_local_tools_exist(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).get("/api/human-operator/setup-status")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["schema"] == "video-studio.human-operator-setup-status.v1"
    assert payload["criticalReady"] is True
    assert payload["demoModeReady"] is True
    assert payload["blockingChecks"] == []
    assert any(item["key"] == "demo-template" and item["state"] == "ready" for item in payload["providerMatrix"])
    assert any(item["key"] == "paid-providers" and item["state"] == "blocked" for item in payload["providerMatrix"])


def test_human_operator_status_blocks_demo_when_ffmpeg_missing(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch, ffmpeg_ready=False).get("/api/human-operator/status")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["schema"] == "video-studio.human-operator-status.v1"
    assert payload["setup"]["criticalReady"] is False
    assert "ffmpeg" in payload["setup"]["blockingChecks"]
    assert payload["renderHealth"]["status"] == "blocked"
    assert payload["nextAction"]["label"] == "Fix first-run setup"
    assert payload["adapterCommandReadiness"]["schema"] == "video-studio.human-operator.adapter-command-readiness.v1"
    assert payload["worklist"]["counts"]["requiresRuntimeProof"] >= 1


def test_human_operator_demo_prepare_writes_payload_without_external_ai(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post("/api/human-operator/demo/prepare")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["prepared"] is True
    assert payload["requiresExternalAi"] is False
    assert payload["requiresPaidProvider"] is False
    assert payload["requiresBrowserHandoff"] is False
    render_payload_path = tmp_path / "storage" / "human-operator-demo" / "human-operator-local-demo-p0" / "render-smoke-payload.json"
    summary_path = tmp_path / "storage" / "human-operator-demo" / "human-operator-local-demo-p0" / "summary.json"
    assert render_payload_path.exists()
    assert summary_path.exists()
    render_payload = json.loads(render_payload_path.read_text(encoding="utf-8"))
    assert render_payload["plannerMode"] == "sample"
    assert render_payload["humanMode"]["requiresExternalAi"] is False
    assert len(render_payload["draftScenes"]) == 3


def test_human_operator_demo_render_requires_prepared_packet(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).post("/api/human-operator/demo/render")

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"] == "demo packet is not prepared"
    assert payload["nextAction"] == "Call /api/human-operator/demo/prepare first."


def test_provider_readiness_separates_demo_from_paid_and_manual_tools(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).get("/api/human-operator/provider-readiness")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["schema"] == "video-studio.human-operator.provider-readiness.v1"
    assert payload["demoModeReady"] is True
    providers = {item["key"]: item for item in payload["providers"]}
    assert providers["demo-template"]["requiredForDemo"] is True
    assert providers["paid-providers"]["state"] == "blocked"
    assert providers["grok-browser"]["state"] == "manual-only"
    assert "Provider-Assisted" in providers["gemini"]["modes"]
    assert providers["wan-command"]["requiredForDemo"] is False
    assert payload["adapterCommandReadiness"]["schema"] == "video-studio.human-operator.adapter-command-readiness.v1"


def test_adapter_command_readiness_reports_wan_and_gemini_without_running_them(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).get("/api/human-operator/adapter-command-readiness")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["schema"] == "video-studio.human-operator.adapter-command-readiness.v1"
    assert "does not run Wan" in payload["executionBoundary"]
    adapters = {item["key"]: item for item in payload["adapters"]}
    assert adapters["wan"]["requiredForDemo"] is False
    assert adapters["wan"]["state"] in {"ready", "config-required", "blocked", "unknown"}
    assert adapters["gemini-flash"]["optionalForProviderAssisted"] is True


def test_human_mode_worklist_keeps_runtime_proof_separate_from_source_work(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).get("/api/human-operator/worklist")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["schema"] == "video-studio.human-operator.worklist.v1"
    assert "Source-level worklist only" in payload["releaseBoundary"]
    items = {item["key"]: item for item in payload["items"]}
    assert items["human-mode-release-proof"]["requiresRuntimeProof"] is True
    assert items["grok-ui-handoff-proof"]["status"] == "blocked-external-proof"
    assert items["windows-test-checklist"]["status"] == "doc-refresh"


def test_source_review_accepts_local_proof_and_rejects_surface_only_browser_proof(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    local_source = tmp_path / "storage" / "inputs" / "demo" / "scene-01.mp4"
    local_source.parent.mkdir(parents=True)
    local_source.write_bytes(b"local source mp4")

    accepted = client.post(
        "/api/human-operator/sources/review",
        json={
            "sourceId": "scene-01-local",
            "sceneId": "scene-01",
            "sourcePath": "storage/inputs/demo/scene-01.mp4",
            "proofKind": "local-upload",
            "decision": "accepted",
        },
    )
    assert accepted.status_code == 200
    accepted_payload = accepted.get_json()
    assert accepted_payload["acceptedCount"] == 1
    assert accepted_payload["status"] == "ready"

    rejected = client.post(
        "/api/human-operator/sources/review",
        json={
            "sourceId": "scene-02-browser",
            "proofKind": "browser-proof",
            "decision": "accepted",
            "browserProof": {
                "currentUrl": "https://grok.com/imagine",
                "generationObserved": False,
                "assetImported": False,
            },
        },
    )
    assert rejected.status_code == 400
    assert "generation/import proof" in rejected.get_json()["error"]

    native_prompt = client.post(
        "/api/human-operator/sources/review",
        json={
            "sourceId": "scene-03-browser",
            "proofKind": "browser-proof",
            "decision": "accepted",
            "browserProof": {
                "currentUrl": "https://grok.com/imagine",
                "generationObserved": True,
                "assetImported": True,
                "nativeDownloadPromptOpened": True,
            },
        },
    )
    assert native_prompt.status_code == 400
    assert "native Chrome Download" in native_prompt.get_json()["error"]

    missing_local = client.post(
        "/api/human-operator/sources/review",
        json={
            "sourceId": "scene-04-local",
            "sourcePath": "storage/inputs/demo/missing.mp4",
            "proofKind": "local-upload",
            "decision": "accepted",
        },
    )
    assert missing_local.status_code == 400
    missing_payload = missing_local.get_json()
    assert "existing non-empty media file" in missing_payload["error"]
    assert missing_payload["localProof"]["status"] == "source-missing"

    local_source.unlink()
    status_after_delete = client.get("/api/human-operator/sources/status")
    assert status_after_delete.status_code == 200
    deleted_payload = status_after_delete.get_json()
    assert deleted_payload["status"] == "pending"
    assert deleted_payload["acceptedCount"] == 0
    assert deleted_payload["unvalidatedAcceptedCount"] == 1


def test_render_health_categorizes_last_demo_error(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    demo_dir = tmp_path / "storage" / "human-operator-demo" / "human-operator-local-demo-p0"
    demo_dir.mkdir(parents=True)
    (demo_dir / "demo-render-result.json").write_text(
        json.dumps({
            "ok": False,
            "error": "ffmpeg not found on PATH",
        }),
        encoding="utf-8",
    )

    response = client.get("/api/human-operator/render-health")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["schema"] == "video-studio.human-operator.render-health.v1"
    assert payload["status"] == "blocked"
    assert payload["failureCategory"] == "missing-ffmpeg"
    assert "Install FFmpeg" in payload["repairActions"]["missing-ffmpeg"]


def test_phone_review_and_publish_packet_require_render_source_and_phone_evidence(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    initial = client.get("/api/human-operator/publish-packet").get_json()
    assert initial["uploadAllowed"] is False
    assert initial["blockers"] == [
        "render-candidate-required",
        "accepted-source-required",
        "phone-review-required",
    ]

    local_source = tmp_path / "storage" / "inputs" / "demo" / "scene-01.mp4"
    local_source.parent.mkdir(parents=True, exist_ok=True)
    local_source.write_bytes(b"local source mp4")

    source = client.post(
        "/api/human-operator/sources/review",
        json={
            "sourceId": "scene-01-local",
            "sourcePath": "storage/inputs/demo/scene-01.mp4",
            "decision": "accepted",
        },
    )
    assert source.status_code == 200

    render_output = tmp_path / "storage" / "renders" / "human-operator-local-demo-p0" / "final.mp4"
    render_output.parent.mkdir(parents=True, exist_ok=True)
    render_output.write_bytes(b"render mp4")
    demo_dir = tmp_path / "storage" / "human-operator-demo" / "human-operator-local-demo-p0"
    demo_dir.mkdir(parents=True, exist_ok=True)
    (demo_dir / "demo-render-result.json").write_text(
        json.dumps({
            "ok": True,
            "renderResult": {
                "ok": True,
                "outputPath": "storage/renders/human-operator-local-demo-p0/final.mp4",
                "logPath": "storage/renders/human-operator-local-demo-p0/render.log",
                "manifestPath": "storage/inputs/human-operator-local-demo-p0/render-manifest.json",
            },
        }),
        encoding="utf-8",
    )

    mismatched_review = client.post(
        "/api/human-operator/phone-review",
        json={
            "renderId": "storage/renders/human-operator-local-demo-p0/missing.mp4",
            "watchedDurationSec": 30,
            "fullWatchCompleted": True,
            "captionsOk": True,
            "sourceFitOk": True,
            "audioOk": True,
            "pacingOk": True,
            "disclosureOk": True,
            "decision": "accepted",
        },
    )
    assert mismatched_review.status_code == 400
    assert "current render artifact" in mismatched_review.get_json()["error"]

    review = client.post(
        "/api/human-operator/phone-review",
        json={
            "renderId": "storage/renders/human-operator-local-demo-p0/final.mp4",
            "watchedDurationSec": 30,
            "fullWatchCompleted": True,
            "captionsOk": True,
            "sourceFitOk": True,
            "audioOk": True,
            "pacingOk": True,
            "disclosureOk": True,
            "decision": "accepted",
        },
    )
    assert review.status_code == 200
    assert review.get_json()["acceptedForPublishPacket"] is True

    packet = client.get("/api/human-operator/publish-packet").get_json()
    assert packet["uploadAllowed"] is True
    assert packet["blockers"] == []
    assert packet["operatorBoundary"] == "The app prepares evidence; upload remains an operator-owned action."
