"""Grok web handoff tests for Video Studio."""

import base64
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import pytest
from flask import Flask

from worker.bridge import routes_grok
from worker.bridge.draft_executor import safe_resolve
from worker.bridge.routes_grok import grok_bp, init_grok_routes
from worker.media.model_router import ProviderAvailability
from worker.planner.save_plan import save_project_bundle


def _grok_test_client(project_root: Path):
    init_grok_routes("127.0.0.1", 5161, project_root, safe_resolve)
    app = Flask(__name__)
    app.register_blueprint(grok_bp)
    return app.test_client()


def _load_live_proof_runner():
    script_path = Path(__file__).resolve().parents[1] / "tools" / "chrome-grok-companion" / "live_proof_runner.py"
    spec = importlib.util.spec_from_file_location("video_studio_live_proof_runner", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_probe_fixture_mp4(path: Path, source: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is required for Grok motion probe fixture generation")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            source,
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )


def _grok_main_quality_fields(**overrides):
    fields = {
        "visualQualityVerdict": "pass",
        "shotLockMatch": True,
        "sceneAssemblyOk": True,
        "captionLayoutReviewNote": "Subject remains clear with lower captions and right-side Shorts UI avoided.",
        "shotLockEvidenceNote": "The selected take matches the locked action, first-second motion, recurring subject, camera move, and caption-safe layout.",
        "sceneAssemblyRoleNote": "This take works as the scene's hook/build beat and cuts cleanly into the next visual beat.",
        "continuityNote": "Same subject, location, palette, and prop continuity are preserved across the clip.",
        "hookNote": "Visible action starts inside the first two seconds and reads without narration.",
        "layoutVariantNote": "Use restrained lower-info or no-caption layout so the clip stays visual-first.",
        "thumbnailReviewNote": "First frame has readable action and no baked-in UI or text overlay clutter.",
        "audioMixReviewNote": "Native audio can be muted or kept under BGM without fighting the final mix.",
        "platformComparisonNote": "Closer to Korean Shorts hero footage than stock filler or generic AI montage.",
        "sourceProvenanceConfirmed": True,
        "sourceProvenanceNote": "Operator confirms this MP4 came from operator-owned download/import or manual upload, not browser preview currentSrc.",
    }
    fields.update(overrides)
    return fields


def test_grok_handoff_creates_prompt_packet_and_matches_downloaded_mp4(tmp_path):
    client = _grok_test_client(tmp_path)

    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "grok-test",
            "templateType": "authentic_vlog",
            "tone": "casual_heyo",
            "lang": "ko",
            "targetDuration": "30s",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "A barista in a warm cafe counter slowly tilts the same white ceramic cup as coffee steam rises in front of the lens.",
                    "hook_note": "steam already moving across the cup in the first second",
                    "continuity_note": "same white cup, wooden counter, warm cafe lighting",
                    "layout_variant_note": "keep cup and hands above lower captions",
                    "caption_preset": "lower-info",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "pexels-video",
                    "image_prompt": "barista working",
                    "duration": 4,
                },
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["projectId"] == "grok-test"
    assert len(data["scenes"]) == 1
    assert data["scenes"][0]["expectedFileName"] == "scene-01.grok.mp4"
    assert data["defaultDownloadDir"]
    assert isinstance(data["defaultDownloadDirExists"], bool)

    assert data["worksheetUrl"].endswith("/api/grok-handoff/grok-test/worksheet")
    assert data["productionQueueUrl"].endswith("/api/grok-handoff/grok-test/production-queue")
    assert data["reviewPacketUrl"].endswith("/api/grok-handoff/grok-test/review-packet")
    manifest_path = Path(data["manifestPath"])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["automationContract"]["usesPaidApi"] is False
    assert manifest["automationContract"]["usesRemoteDebugging"] is False
    assert manifest["automationContract"]["usesPersistentAutomationProfile"] is False
    assert manifest["automationContract"]["requiresOperatorBrowserSession"] is True
    assert manifest["automationContract"]["postImportReview"] == "GET /api/grok-handoff/grok-test/review-packet"
    assert manifest["defaultDownloadDir"] == data["defaultDownloadDir"]
    assert manifest["reviewPacketUrl"].endswith("/api/grok-handoff/grok-test/review-packet")
    assert manifest["shotBible"]["visualContinuity"].startswith("Treat every clip")
    assert manifest["shotBible"]["productionProfile"]["templateType"] == "authentic_vlog"
    assert manifest["shotBible"]["productionProfile"]["family"] == "authentic-vlog"
    assert manifest["shotBible"]["promptRulesetVersion"] == routes_grok.GROK_GENERATION_PROMPT_RULESET_VERSION
    assert "caption-safe" in manifest["shotBible"]["captionSafePlan"]
    assert "intentional raw footage" in manifest["shotBible"]["cinematicQualityFloor"]
    assert any("generic stock b-roll" in item for item in manifest["shotBible"]["antiSlopDirectives"])
    assert manifest["shotBible"]["shotLocks"][0]["sceneId"] == "scene-01"
    assert "barista" in manifest["shotBible"]["shotLocks"][0]["actionLock"]
    assert "steam already moving" in manifest["shotBible"]["shotLocks"][0]["firstSecondMotionLock"]
    assert "static image with Ken Burns-like movement only" in manifest["shotBible"]["hardRejectChecklist"]
    assert "generic stock b-roll that only resembles the topic" in manifest["shotBible"]["hardRejectChecklist"]
    assert any("raw footage" in item for item in manifest["shotBible"]["grokPromptRules"])
    assert "first second:" in manifest["scenes"][0]["prompt"]
    assert "Vertical 9:16 phone MP4" in manifest["scenes"][0]["prompt"]
    assert "uncluttered lower-right background" in manifest["scenes"][0]["prompt"]
    assert "no visible text or watermark" in manifest["scenes"][0]["prompt"]
    assert "Shot lock:" not in manifest["scenes"][0]["prompt"]
    assert "Reject generic stock/ad/AI montage look" not in manifest["scenes"][0]["prompt"]
    assert "Reject before download" not in manifest["scenes"][0]["prompt"]
    assert "raw footage for editing" not in manifest["scenes"][0]["prompt"]
    assert "caption-safe" not in manifest["scenes"][0]["prompt"]
    take_prompts = manifest["scenes"][0]["takePrompts"]
    assert [item["takeNumber"] for item in take_prompts] == [1, 2, 3]
    assert take_prompts[0]["label"] == "continuity-master"
    assert take_prompts[1]["label"] == "motion-first"
    assert take_prompts[2]["label"] == "clean-composition"
    assert "Motion-first take" in take_prompts[1]["prompt"]
    assert "Shot lock:" not in take_prompts[1]["prompt"]
    assert "Composition take" in take_prompts[2]["prompt"]
    assert "caption-safe" not in take_prompts[2]["prompt"]
    assert "Shot lock:" not in take_prompts[2]["prompt"]
    assert "promptQuality" in take_prompts[1]
    for take in take_prompts:
        assert "no text, no logos, no." not in take["prompt"]
        assert not take["prompt"].rstrip().lower().endswith((" no", " no."))
        assert take["promptQuality"]["status"] == "ready"
        assert take["promptQuality"]["brokenPromptFragments"] == []
        assert take["promptQuality"]["checks"]["completeSentences"] is True
        assert (tmp_path / take["promptPath"]).exists()
    assert manifest["scenes"][0]["promptQuality"]["status"] == "ready"
    assert manifest["scenes"][0]["promptQuality"]["score"] >= 80
    assert "captionSafe" in manifest["scenes"][0]["promptQuality"]["checks"]
    assert manifest["scenes"][0]["promptQuality"]["checks"]["sceneSpecificIntent"] is True
    assert manifest["scenes"][0]["promptQuality"]["checks"]["sourceActionCue"] is True
    assert manifest["scenes"][0]["promptQuality"]["checks"]["positiveShotInstruction"] is True
    assert manifest["scenes"][0]["promptQuality"]["standard"] == "concise-positive-shot-v1"
    assert manifest["scenes"][0]["promptQuality"]["rulesetVersion"] == routes_grok.GROK_GENERATION_PROMPT_RULESET_VERSION
    assert manifest["scenes"][0]["promptQuality"]["bannedPromptTerms"] == []
    assert manifest["scenes"][0]["promptQuality"]["checks"]["shotLock"] is True
    assert manifest["scenes"][0]["promptQuality"]["checks"]["antiSlop"] is True
    assert manifest["scenes"][0]["promptQuality"]["checks"]["largePhysicalMotion"] is True
    assert manifest["scenes"][0]["promptQuality"]["checks"]["observableFirstSecondChange"] is True
    assert manifest["scenes"][0]["promptQuality"]["checks"]["singleContinuousShot"] is True
    assert manifest["scenes"][0]["promptQuality"]["checks"]["cameraConcrete"] is True
    assert manifest["scenes"][0]["promptQuality"]["checks"]["propContinuityAnchor"] is True
    assert manifest["scenes"][0]["promptQuality"]["checks"]["minimalNegativeOnly"] is True
    assert manifest["scenes"][0]["promptQuality"]["repairHints"] == {}
    assert "Matches the shot bible" in manifest["scenes"][0]["operatorChecklist"][1]
    assert "caption" in manifest["scenes"][0]["operatorChecklist"][3].lower()
    worksheet_path = Path(data["worksheetPath"])
    assert worksheet_path.exists()
    worksheet = worksheet_path.read_text(encoding="utf-8")
    assert "Shot bible" in worksheet
    assert "Production family" in worksheet
    assert "Hard reject checklist" in worksheet
    assert "prompt quality" in worksheet
    assert "Grok take ladder" in worksheet
    assert "Take 2: motion-first" in worksheet
    assert "Hash + Generate" in worksheet
    assert "Global review checklist" in worksheet
    assert "Copy take prompt" in worksheet
    assert "scene-01.grok.mp4" in worksheet
    assert "remote debugging" in worksheet
    production_queue_path = Path(data["productionQueuePath"])
    assert production_queue_path.exists()
    assert data["productionQueueVersion"] == routes_grok.GROK_PRODUCTION_QUEUE_VERSION
    production_queue = production_queue_path.read_text(encoding="utf-8")
    assert "Grok production queue" in production_queue
    assert routes_grok.GROK_PRODUCTION_QUEUE_VERSION in production_queue
    assert "Grok cinematic quality floor" in production_queue
    assert "Shot lock board" in production_queue
    assert "Anti-slop reject if" in production_queue
    assert "generic stock b-roll" in production_queue
    assert "barista" in production_queue
    assert "Grok-main readiness" in production_queue
    assert "browser-control generation proof is followed by operator-owned local MP4 import" in production_queue
    assert "Video Studio Companion" not in production_queue
    assert "Chrome/CDP attach" in production_queue
    assert "Downloads watcher" in production_queue
    assert "Copy Companion folder" not in production_queue
    assert "Grok-main runway" in production_queue
    assert "Queue Fill+Generate fallback" in production_queue
    assert "Copy queue console runner" in production_queue
    assert "Grok source status" in production_queue
    assert "Model access" in production_queue
    assert "Not the blocker" in production_queue
    assert "Existing signed-in Chrome browser-control plus local MP4 import is the main path" in production_queue
    assert "First hook scene must be Grok before publish-ready render." in production_queue
    assert "Take 2 / motion-first" in production_queue
    assert "candidate floor: generate 2+ takes before accepting Grok-main" in production_queue
    assert "Take 1: continuity-master" in production_queue
    assert "Take 2: motion-first" in production_queue
    assert "Take 3: clean-composition" in production_queue
    assert "Copy prompt packet" in production_queue
    assert "Before import, reject if:" in production_queue
    assert "Source import rule" in production_queue
    assert "Do not use a browser currentSrc/cache/proxy clip as the final Grok-main source." in production_queue
    assert "Candidate comparison note" in production_queue
    assert "which take won, which take lost" in production_queue
    assert "Scene-grouped 2-take production matrix" in production_queue
    assert "Generate/save two MP4s per scene before moving to the next scene." not in production_queue
    assert "Preserve two imported MP4 takes per scene before moving to the next scene." in production_queue
    assert "Manually import or batch-upload every viable candidate take" in production_queue
    assert "sceneGroupedTakeSize=2" in production_queue
    assert "scene-01 take 1" in production_queue
    assert "scene-01 take 2" in production_queue
    assert "Expected batch file order" in production_queue
    assert "Grok MP4 일괄 반입" in production_queue
    assert "Open Grok + Take 2" in production_queue
    assert Path(data["reviewPacketPath"]).exists()

    production_queue_response = client.get("/api/grok-handoff/grok-test/production-queue")
    assert production_queue_response.status_code == 200
    assert "Grok production queue" in production_queue_response.get_data(as_text=True)

    command = client.get("/api/grok-handoff/grok-test/extension-command?operatorApproved=true&sceneId=scene-01&take=2")
    assert command.status_code == 200
    command_data = command.get_json()
    assert command_data["takeNumber"] == 2
    assert command_data["takeLabel"] == "motion-first"
    assert command_data["prompt"] == take_prompts[1]["prompt"]
    assert command_data["promptQuality"]["status"] == "ready"
    assert "take=2" in urllib.parse.unquote(command_data["commandUrl"])
    assert "take=2" in urllib.parse.unquote(command_data["prepGenerateAutostartUrl"])
    assert command_data["uploadEndpoint"].endswith("/api/grok-handoff/grok-test/upload-mp4")
    assert [item["takeNumber"] for item in command_data["takeCommands"]] == [1, 2, 3]
    take_command = command_data["takeCommands"][1]
    assert take_command["takeLabel"] == "motion-first"
    assert take_command["bookmarkletInlineMode"] == "self-contained"
    assert take_command["bookmarkletGenerateInlineUrl"].startswith("javascript:")
    decoded_take_bookmarklet = urllib.parse.unquote(take_command["bookmarkletGenerateInlineUrl"])
    assert "/bookmarklet.js?" not in decoded_take_bookmarklet
    assert take_prompts[1]["prompt"] in decoded_take_bookmarklet

    initial_status = client.get("/api/grok-handoff/grok-test/status").get_json()
    assert initial_status["downloadImport"]["watchEndpoint"] == "/api/grok-handoff/grok-test/watch-downloads"
    assert initial_status["downloadImport"]["operatorRunEndpoint"] == "/api/grok-handoff/grok-test/operator-run"
    assert initial_status["downloadImport"]["nextSceneId"] == "scene-01"
    assert initial_status["downloadImport"]["nextExpectedFileName"] == "scene-01.grok.mp4"
    assert initial_status["productionQueueUrl"].endswith("/api/grok-handoff/grok-test/production-queue")
    assert initial_status["operatorRun"]["endpoint"] == "/api/grok-handoff/grok-test/operator-run"
    assert initial_status["operatorRun"]["input"]["sceneId"] == "scene-01"
    manual_primary = initial_status["manualPrimaryPath"]
    assert manual_primary["mode"] == "manual-grok-app-web-primary"
    assert manual_primary["browserControlRail"] == "existing-signed-in-chrome-browser-control-primary"
    assert manual_primary["primarySource"] == "grok-app-web-mp4"
    assert manual_primary["usesPaidApi"] is False
    assert manual_primary["browserAutomationRole"] == "browser-control-primary; isolated-cdp-and-bookmarklet-fallback-only"
    assert manual_primary["currentScene"]["sceneId"] == "scene-01"
    assert manual_primary["currentScene"]["expectedFileName"] == "scene-01.grok.mp4"
    assert manual_primary["currentScene"]["recommendedTakeNumber"] == 2
    assert manual_primary["currentScene"]["recommendedTakeLabel"] == "motion-first"
    assert "Motion-first take" in manual_primary["currentScene"]["prompt"]
    assert "take=2" in manual_primary["currentScene"]["commandUrl"]
    assert "take=2" in urllib.parse.unquote(manual_primary["currentScene"]["prepGenerateAutostartUrl"])
    assert "Take 2 / motion-first" in manual_primary["operatorNextAction"]
    assert manual_primary["endpoints"]["importDownloads"] == "/api/grok-handoff/grok-test/import-downloads"
    assert manual_primary["endpoints"]["manualBatchUpload"] == "/api/grok-handoff/grok-test/upload-mp4-batch"
    assert manual_primary["endpoints"]["productionQueue"] == "/api/grok-handoff/grok-test/production-queue"
    assert manual_primary["endpoints"]["reviewPacket"] == "/api/grok-handoff/grok-test/review-packet"
    assert manual_primary["orderedBatchUpload"]["supported"] is True
    assert manual_primary["orderedBatchUpload"]["filenameStillAccepted"] is True
    assert "not required" in manual_primary["currentScene"]["downloadInstruction"]
    assert "browser-control" in manual_primary["operatorSteps"][0]
    assert "existing signed-in Chrome" in manual_primary["operatorSteps"][1]
    assert "top-tier" in " ".join(manual_primary["qualityRules"])

    incoming = Path(data["incomingDir"])
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / "scene-01.grok.mp4").write_bytes(b"fake mp4 bytes")

    status = client.get("/api/grok-handoff/grok-test/status")

    assert status.status_code == 200
    status_data = status.get_json()
    assert status_data["ok"] is True
    assert status_data["defaultDownloadDir"] == data["defaultDownloadDir"]
    assert isinstance(status_data["defaultDownloadDirExists"], bool)
    assert status_data["readyScenes"] == 1
    assert status_data["allReady"] is True
    assert status_data["downloadImport"]["watchEndpoint"] == "/api/grok-handoff/grok-test/watch-downloads"
    assert status_data["downloadImport"]["operatorRunEndpoint"] == "/api/grok-handoff/grok-test/operator-run"
    assert status_data["operatorRun"]["endpoint"] == "/api/grok-handoff/grok-test/operator-run"
    assert status_data["operatorRun"]["returnsRenderPayloadWhenReady"] is True
    assert status_data["manualPrimaryPath"]["currentScene"]["sceneId"] == "scene-01"
    assert status_data["manualPrimaryPath"]["endpoints"]["renderPayload"] == "/api/grok-handoff/grok-test/render-payload"
    asset = status_data["assets"][0]
    assert asset["sceneId"] == "scene-01"
    assert asset["status"] == "ready"
    assert asset["sourcePath"].endswith("storage/grok-handoffs/grok-test/incoming/scene-01.grok.mp4")
    assert asset["previewUrl"].endswith("/api/grok-handoff/grok-test/asset/scene-01.grok.mp4")
    assert status_data["reviewPacketUrl"].endswith("/api/grok-handoff/grok-test/review-packet")


def test_grok_handoff_recommends_ready_take_when_motion_take_fails(tmp_path):
    client = _grok_test_client(tmp_path)

    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "ready-take-fallback",
            "templateType": "authentic_vlog",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "A barista in a warm cafe counter slowly tilts the same white ceramic cup as coffee steam rises in front of the lens.",
                    "hook_note": "steam already moving across the cup in the first second",
                    "continuity_note": "same white cup, wooden counter, warm cafe lighting",
                    "layout_variant_note": "keep cup and hands above lower captions",
                    "caption_preset": "lower-info",
                    "duration": 4,
                },
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    manifest_path = Path(data["manifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scene = manifest["scenes"][0]
    assert scene["takePrompts"][1]["takeNumber"] == 2
    assert scene["takePrompts"][2]["takeNumber"] == 3
    assert scene["takePrompts"][2]["promptQuality"]["status"] == "ready"
    scene["takePrompts"][1]["promptQuality"] = {
        "status": "needs-rewrite",
        "score": 72,
        "missing": ["largePhysicalMotion", "observableFirstSecondChange"],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    command = client.get(
        "/api/grok-handoff/ready-take-fallback/extension-command"
        "?operatorApproved=true&sceneId=scene-01"
    )

    assert command.status_code == 200
    command_data = command.get_json()
    assert command_data["takeNumber"] == 3
    assert command_data["takeLabel"] == "clean-composition"
    assert command_data["promptQuality"]["status"] == "ready"
    assert command_data["takeCommands"][1]["recommended"] is False
    assert command_data["takeCommands"][2]["recommended"] is True
    assert command_data["allSceneCommands"][0]["recommendedTakeNumber"] == 3
    assert command_data["allSceneCommands"][0]["recommendedTakeLabel"] == "clean-composition"
    assert "take=3" in urllib.parse.unquote(command_data["commandUrl"])

    status_data = client.get("/api/grok-handoff/ready-take-fallback/status").get_json()
    manual_primary = status_data["manualPrimaryPath"]
    assert manual_primary["currentScene"]["recommendedTakeNumber"] == 3
    assert manual_primary["currentScene"]["recommendedTakeLabel"] == "clean-composition"
    assert "Take 3 / clean-composition" in manual_primary["operatorNextAction"]


def test_grok_handoff_uses_visual_action_seed_for_preproduction_prompt(tmp_path):
    client = _grok_test_client(tmp_path)

    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "preproduction-visual-seed",
            "templateType": "authentic_vlog",
            "draftScenes": [
                {
                    "sceneId": "scene-001",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": (
                        "Raw vertical 9:16 phone-camera MP4, 4-6 seconds. First second: "
                        "A hand circles the opening date on a printed football calendar in the first second. "
                        "Setting: desk with printed football schedule. Subject: Korean football viewers. "
                        "Purpose: Calendar action makes the schedule problem visible."
                    ),
                    "visual_prompt": "A hand circles the opening date on a printed football calendar in the first second.",
                    "hook_note": "A hand circles the opening date on a printed football calendar in the first second.",
                    "continuity_note": "same host hands, desk with printed football schedule, same key prop, natural phone-camera light",
                    "layout_variant_note": "keep lower-right background open for later captions",
                    "caption_preset": "top-hook",
                    "duration": 6,
                },
            ],
        },
    )

    assert response.status_code == 200
    scene = response.get_json()["scenes"][0]
    assert scene["prompt"].startswith("A hand circles the opening date")
    assert "Setting: desk with;" not in scene["prompt"]
    assert "Keep Keep" not in scene["prompt"]
    assert "slight." not in scene["prompt"]
    assert "same key;" not in scene["prompt"]
    assert scene["promptQuality"]["status"] == "ready"
    assert scene["promptQuality"]["checks"]["largePhysicalMotion"] is True
    assert scene["promptQuality"]["checks"]["observableFirstSecondChange"] is True
    take_two = scene["takePrompts"][1]
    assert take_two["takeNumber"] == 2
    assert take_two["promptQuality"]["status"] == "ready"
    assert "Keep Keep" not in take_two["prompt"]
    assert "slight." not in take_two["prompt"]
    assert "same key;" not in take_two["prompt"]


def test_grok_prompt_join_truncates_without_dropping_late_context():
    joined = routes_grok._prompt_join([
        "A hand opens the same red notebook on a cafe counter; first second: cover moves upward",
        (
            "Vertical 9:16 phone MP4, 4-6 seconds, one continuous shot, handheld phone camera "
            "with a deliberately long camera description that would otherwise consume the whole "
            "prompt budget before the continuity clause can be written"
        ),
        (
            "Keep same red notebook, same hand, same cafe counter, warm practical light, and "
            "matching palette; leave an uncluttered lower-right background; no visible text or watermark"
        ),
    ], max_chars=260)

    assert len(joined) <= 260
    assert "Vertical 9:16 phone MP4" in joined
    assert "Keep same red notebook" in joined
    assert "..." in joined
    assert not joined.rstrip().lower().endswith((" no", " no."))


def test_grok_handoff_does_not_use_raw_search_query_image_prompt_as_video_seed(tmp_path):
    client = _grok_test_client(tmp_path)
    raw_query = "Nike Air Max 1/97 Sean Wotherspoon sneaker"

    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "raw-image-query-seed",
            "templateType": "ranking_list",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "image_prompt": raw_query,
                    "display_text": "500만원",
                    "narration": "출시가가 16만원이었는데 지금 리셀가는 500만원을 넘겼어요.",
                    "duration": 4,
                }
            ],
        },
    )

    assert response.status_code == 200
    scene = response.get_json()["scenes"][0]
    assert raw_query not in scene["prompt"]
    assert scene["promptQuality"]["sourcePrompt"] != raw_query
    assert scene["promptQuality"]["status"] == "needs-rewrite"


def test_grok_handoff_records_codex_chrome_generation_observation(tmp_path):
    client = _grok_test_client(tmp_path)

    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "codex-chrome-observed",
            "grokMainSourceRequired": True,
            "qualityGateRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "display_text": "퇴근길 지하철에서 루틴을 다시 잡는 직장인",
                    "narration": "",
                    "duration": 6,
                }
            ],
        },
    )
    assert created.status_code == 200

    denied = client.post(
        "/api/grok-handoff/codex-chrome-observed/codex-chrome-observation",
        json={"sceneId": "scene-01", "status": "generated"},
    )
    assert denied.status_code == 403

    observed = client.post(
        "/api/grok-handoff/codex-chrome-observed/codex-chrome-observation",
        json={
            "operatorApproved": True,
            "codexChromeApproved": True,
            "sceneId": "scene-01",
            "status": "generated",
            "exportStatus": "pending-download-import",
            "postUrl": "https://grok.com/imagine/post/cd0ac4b6-efcb-4c5a-a91b-fcd04533910d?utm=drop",
            "videoUrl": "https://assets.grok.com/users/user/generated/cd0/generated_video.mp4?token=secret",
            "durationSeconds": 6.041667,
            "renderedWidth": 419,
            "renderedHeight": 744,
            "exportBlocker": "download event did not produce a local MP4 yet",
        },
    )
    assert observed.status_code == 200
    observation = observed.get_json()["codexChromeObservation"]
    assert observation["source"] == "codex-chrome-extension"
    assert observation["postUrl"] == "https://grok.com/imagine/post/cd0ac4b6-efcb-4c5a-a91b-fcd04533910d"
    assert observation["videoUrl"] == "https://assets.grok.com/users/user/generated/cd0/generated_video.mp4"
    assert observation["storesCredentials"] is False
    assert observation["usesPaidApi"] is False

    status = client.get("/api/grok-handoff/codex-chrome-observed/status").get_json()
    assert status["codexChromeObservation"]["status"] == "generated"
    assert status["mainPathStatus"]["status"] == "generated-export-pending"
    assert status["mainPathStatus"]["blocker"] == "grok-mp4-export-import-pending"
    assert status["mainPathStatus"]["generationObservation"]["expectedFileName"] == "scene-01.grok.mp4"
    assert status["observedPostImportPlan"]["mode"] == "observed-grok-post-direct-import-only"
    assert status["observedPostImportPlan"]["postUrl"] == "https://grok.com/imagine/post/cd0ac4b6-efcb-4c5a-a91b-fcd04533910d"
    assert status["observedPostImportPlan"]["sceneId"] == "scene-01"
    assert status["observedPostImportPlan"]["expectedFileName"] == "scene-01.grok.mp4"
    assert status["observedPostImportPlan"]["manualWatchEndpoint"] == "/api/grok-handoff/codex-chrome-observed/manual-download-watch"
    assert status["observedPostImportPlan"]["observedPostDownloadEndpoint"] == "/api/grok-handoff/codex-chrome-observed/observed-post-download.js"
    assert status["observedPostImportPlan"]["observedPostDownloadScriptUrl"].endswith(
        "/api/grok-handoff/codex-chrome-observed/observed-post-download.js?operatorApproved=true&sceneId=scene-01"
    )
    assert status["observedPostImportPlan"]["observedPostDownloadInlineUrl"].startswith("javascript:")
    assert status["observedPostImportPlan"]["uploadEndpoint"].endswith(
        "/api/grok-handoff/codex-chrome-observed/upload-mp4"
    )
    decoded_post_recovery = urllib.parse.unquote(status["observedPostImportPlan"]["observedPostDownloadInlineUrl"])
    assert "Video Studio Grok post direct import started" in decoded_post_recovery
    assert "uploadEndpoint" in decoded_post_recovery
    assert "/api/grok-handoff/codex-chrome-observed/upload-mp4" in decoded_post_recovery
    assert "bookmarklet-post-download" in status["observedPostImportPlan"]["observedPostDownloadConsoleSnippet"]
    assert "scene-01.grok.mp4" in status["observedPostImportPlan"]["observedPostDownloadConsoleSnippet"]
    assert "uploadEndpoint" in status["observedPostImportPlan"]["observedPostDownloadConsoleSnippet"]
    assert status["observedPostImportPlan"]["manualWatchRequest"]["sceneId"] == "scene-01"
    assert status["observedPostImportPlan"]["manualWatchRequest"]["preserveCandidates"] is True
    assert status["observedPostImportPlan"]["manualWatchRequest"]["timeoutSeconds"] == 7200
    assert status["observedPostImportPlan"]["localMp4ImportRequired"] is True
    assert status["observedPostImportPlan"]["directAssetFetch"]["serverFetchSupported"] is False
    assert status["observedPostImportPlan"]["directAssetFetch"]["expectedFailure"] == "403-or-browser-session-bound"
    assert "signed-in browser session" in status["observedPostImportPlan"]["directAssetFetch"]["reason"]
    assert "local uploadEndpoint" in status["observedPostImportPlan"]["directAssetFetch"]["reason"]
    assert status["observedPostImportPlan"]["directAssetFetch"]["approvedPath"] == (
        "browser-side-fetch-to-local-uploadEndpoint-direct-import-only"
    )
    assert status["observedPostImportPlan"]["operatorSteps"][1].startswith("Run the observed-post direct-import")
    assert any("without Chrome's download approval dialog" in step for step in status["observedPostImportPlan"]["operatorSteps"])
    assert any("does not click Download" in step for step in status["observedPostImportPlan"]["operatorSteps"])
    assert any("direct-import console" in step for step in status["observedPostImportPlan"]["operatorSteps"])
    assert status["mainPathStatus"]["observedPostImportPlan"]["manualWatchRequest"]["timeoutSeconds"] == 7200
    denied_recovery_script = client.get("/api/grok-handoff/codex-chrome-observed/observed-post-download.js?sceneId=scene-01")
    assert denied_recovery_script.status_code == 403
    recovery_script = client.get(
        "/api/grok-handoff/codex-chrome-observed/observed-post-download.js"
        "?operatorApproved=true&sceneId=scene-01"
    )
    assert recovery_script.status_code == 200
    recovery_script_text = recovery_script.get_data(as_text=True)
    assert "Video Studio Grok post direct import started" in recovery_script_text
    assert "scene-01.grok.mp4" in recovery_script_text
    assert "bookmarklet-import" not in recovery_script_text
    assert "clickOrSave(candidate)" not in recovery_script_text
    acquisition = status["mainPathStatus"]["assetAcquisition"]
    assert status["grokAssetAcquisition"] == acquisition
    assert status["grokMainSourceDiagnosis"]["modelBlocked"] is False
    assert status["grokMainSourceDiagnosis"]["generationObserved"] is True
    assert status["grokMainSourceDiagnosis"]["currentBlocker"] == "local-mp4-file-not-yet-present"
    assert status["grokMainSourceDiagnosis"]["recommendedPrimaryPath"] == "existing-signed-in-chrome-browser-control-plus-operator-download-import"
    assert "companionExtensionRole" not in status["grokMainSourceDiagnosis"]
    assert status["grokMainSourceDiagnosis"]["downloadAuthority"] == "operator-owned-manual-download-or-local-upload"
    assert status["grokMainSourceDiagnosis"]["doNotDowngradeToStockOnly"] is True
    rail = status["browserControlPrimaryRail"]
    assert rail["mode"] == "existing-signed-in-chrome-browser-control-primary"
    assert rail["generationObserved"] is True
    assert rail["observedPostUrl"].startswith("https://grok.com/imagine/post/")
    assert rail["autoNativeDownloadPromptAllowed"] is False
    assert rail["automaticDownloadClickAllowed"] is False
    assert "operator-owned" in rail["downloadAuthority"]
    assert acquisition["state"] == "generated-awaiting-local-mp4"
    assert acquisition["clipGenerated"] is True
    assert acquisition["localMp4Imported"] is False
    assert acquisition["blockerScope"] == "asset-export-import-only"
    assert acquisition["directAssetFetchSupported"] is False
    assert acquisition["downloadAuthority"] == "signed-in-browser-session"
    assert acquisition["primaryBlocker"] == "local-mp4-file-not-yet-present"
    assert acquisition["observedPostUrl"] == "https://grok.com/imagine/post/cd0ac4b6-efcb-4c5a-a91b-fcd04533910d"
    assert acquisition["observedAssetUrl"] == "https://assets.grok.com/users/user/generated/cd0/generated_video.mp4"
    assert any("Grok MP4 batch upload" in item for item in acquisition["approvedImportPaths"])
    assert any("batch upload" in item for item in acquisition["operatorActionPriority"])
    assert any("Do not downgrade" in item for item in acquisition["doNotDo"])
    assert any("Video Studio owns" in item for item in acquisition["qualityContract"])
    assert "Grok generation succeeded" in status["mainPathStatus"]["summary"]
    assert "logged-in Chrome/SuperGrok generation has been observed" in status["mainPathStatus"]["notBlockedBy"]
    assert any(item.startswith("observedPost=https://grok.com/imagine/post/") for item in status["mainPathStatus"]["proofPoints"])


def test_grok_handoff_rejects_surface_only_codex_chrome_observation(tmp_path):
    client = _grok_test_client(tmp_path)

    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "codex-chrome-surface-only",
            "grokMainSourceRequired": True,
            "qualityGateRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "display_text": "퇴근길 지하철에서 루틴을 다시 잡는 직장인",
                    "narration": "",
                    "duration": 6,
                }
            ],
        },
    )
    assert created.status_code == 200

    surface_only = client.post(
        "/api/grok-handoff/codex-chrome-surface-only/codex-chrome-observation",
        json={
            "operatorApproved": True,
            "codexChromeApproved": True,
            "sceneId": "scene-01",
            "status": "surface-visible-only",
            "currentUrl": "https://grok.com/imagine",
            "detail": "Imagine surface visible, but prompt fill/generate was not proven.",
        },
    )

    assert surface_only.status_code == 400
    payload = surface_only.get_json()
    assert payload["generationObserved"] is False
    assert payload["surfaceProofEndpoint"] == "/api/grok-handoff/codex-chrome-surface-only/extension-event"
    assert "requires generated Grok proof" in payload["error"]

    status = client.get("/api/grok-handoff/codex-chrome-surface-only/status").get_json()
    assert status["codexChromeObservation"] is None
    assert status["grokMainSourceDiagnosis"]["generationObserved"] is False
    assert status["mainPathStatus"]["status"] == "needs-first-grok-mp4"
    assert "codexChromeObservation=surface-visible-only" not in status["mainPathStatus"]["proofPoints"]


def test_grok_handoff_direct_import_proof_monitor_prefers_upload_endpoint_for_720p_candidate(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "Downloads").mkdir()
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "codex-chrome-720p-observed",
            "grokMainSourceRequired": True,
            "qualityGateRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "display_text": "퇴근길 지하철에서 루틴을 다시 잡는 직장인",
                    "duration": 6,
                }
            ],
        },
    )

    observed = client.post(
        "/api/grok-handoff/codex-chrome-720p-observed/codex-chrome-observation",
        json={
            "operatorApproved": True,
            "codexChromeApproved": True,
            "sceneId": "scene-01",
            "postUrl": "https://grok.com/imagine/post/2ba3c820-c228-4e5b-9b97-b967dd568809",
            "videoUrl": "https://assets.grok.com/users/user/generated/2ba3/generated_video.mp4?cache=1",
            "durationSec": 6.041667,
            "videoWidth": 720,
            "videoHeight": 1280,
        },
    )
    assert observed.status_code == 200
    observation = observed.get_json()["codexChromeObservation"]
    assert observation["durationSeconds"] == pytest.approx(6.041667)
    assert observation["renderedWidth"] == 720
    assert observation["renderedHeight"] == 1280
    assert observation["qualityFloorMet"] is True
    assert observation["directImportPreferred"] is False
    assert observation["exportStatus"] == "pending-download-import"
    assert observation["uploadEndpoint"].endswith("/api/grok-handoff/codex-chrome-720p-observed/upload-mp4")
    assert "operator-owned MP4 download/save" in observation["operatorNextAction"]
    assert "native Chrome download dialog" in observation["operatorNextAction"]

    status = client.get("/api/grok-handoff/codex-chrome-720p-observed/status").get_json()
    assert status["codexChromeObservation"]["directImportPreferred"] is False
    assert "latestExtensionEvent" not in status
    assert status["observedPostImportPlan"]["uploadEndpoint"].endswith(
        "/api/grok-handoff/codex-chrome-720p-observed/upload-mp4"
    )

    guide = client.get("/api/grok-handoff/codex-chrome-720p-observed/chrome-extension?sceneId=scene-01")
    assert guide.status_code == 200
    html = guide.get_data(as_text=True)
    assert "Observed post direct import" in html
    assert "without Chrome Download approval dialog" in html
    assert "/api/grok-handoff/codex-chrome-720p-observed/upload-mp4" in html
    assert "bookmarklet-post-download" in html
    assert "scene-01.grok.mp4" in html
    assert "Video Studio Grok post direct import started" in html
    assert "Open observed Grok post" in html
    assert "Copy observed-post console" in html
    assert "Copy console + open post" in html
    assert "Copy upload endpoint" in html
    assert "data-copy-and-open" in html
    assert "data-open-url" in html
    assert 'id="vs-copy-status"' in html
    assert 'document.querySelectorAll("[data-copy-value]")' in html
    assert 'document.querySelectorAll("[data-copy-and-open]")' in html
    assert "window.open(openUrl" in html
    assert "navigator.clipboard.writeText" in html

    monitor = client.get("/api/grok-handoff/codex-chrome-720p-observed/direct-import-proof?sceneId=scene-01")
    assert monitor.status_code == 200
    proof_html = monitor.get_data(as_text=True)
    assert "Grok Proof Monitor" in proof_html
    assert "operator-owned local MP4 import" in proof_html
    assert "surface-only proof" in proof_html
    assert "Copy Companion folder" not in proof_html
    assert "Open observed Grok post" in proof_html
    assert "Copy observed-post console" in proof_html
    assert "Copy console + open post" in proof_html
    assert "Copy queue console runner" in proof_html
    assert "Refresh proof status" in proof_html
    assert "/api/final-video-library/audit?limit=5" in proof_html
    assert "/api/grok-handoff/codex-chrome-720p-observed/status" in proof_html
    assert "refreshProofStatus" in proof_html
    assert 'document.querySelectorAll("[data-copy-value]")' in proof_html
    assert 'document.querySelectorAll("[data-copy-and-open]")' in proof_html
    assert "window.open(openUrl" in proof_html
    assert "navigator.clipboard.writeText" in proof_html
    assert 'window.open("chrome://extensions' not in proof_html
    assert 'location.href = "chrome://extensions' not in proof_html


def test_grok_handoff_observed_post_download_priority_prefers_original_controls(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "Downloads").mkdir()
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "observed-post-priority",
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same Korean office worker crosses a rainy subway platform, vertical raw MP4.",
                    "duration": 6,
                }
            ],
        },
    )
    client.post(
        "/api/grok-handoff/observed-post-priority/codex-chrome-observation",
        json={
            "operatorApproved": True,
            "codexChromeApproved": True,
            "sceneId": "scene-01",
            "status": "generated",
            "postUrl": "https://grok.com/imagine/post/cd0",
            "videoUrl": "https://assets.grok.com/users/user/generated/cd0/generated_video.mp4?token=drop",
        },
    )

    status = client.get("/api/grok-handoff/observed-post-priority/status").get_json()
    plan = status["observedPostImportPlan"]
    assert plan["uploadEndpoint"].endswith("/api/grok-handoff/observed-post-priority/upload-mp4")
    assert "Download/Save/Export" in plan["qualityNote"]
    assert "Visible video/currentSrc fallback is proof only" in plan["qualityNote"]
    assert any("without Chrome's download approval dialog" in step for step in plan["operatorSteps"])
    assert any("does not click Download" in step for step in plan["operatorSteps"])
    assert any("If direct import fails" in step for step in plan["operatorSteps"])

    recovery_script = client.get(
        "/api/grok-handoff/observed-post-priority/observed-post-download.js"
        "?operatorApproved=true&sceneId=scene-01"
    )
    assert recovery_script.status_code == 200
    script = recovery_script.get_data(as_text=True)
    assert 'sourceKind: anchor.hasAttribute("download") ? "download-anchor" : "direct-video-anchor"' in script
    assert 'sourceKind: "download-control"' in script
    assert 'sourceKind: "visible-video-fallback"' in script
    assert "video.videoHeight" in script
    assert "videoWidth >= 720 && videoHeight >= 1280" in script
    assert "qualityFloorMet" in script
    assert "visible-video-below-floor" in script
    assert "command.uploadEndpoint" in script
    assert "directImportProof: true" in script
    assert 'eventType: "bookmarklet-post-direct-import"' in script
    assert "candidateUrl: href" in script
    assert 'detail: `direct bridge import; bytes=${buffer.byteLength}; label=${label || "post-recovery"}`' in script
    assert 'directImportCandidate(candidate, "post-recovery")' in script
    assert "bookmarklet-post-blob-direct-fetch" in script
    assert "bookmarklet-post-direct-fetch" in script
    assert "no-browser-download-prompt" in script
    assert "stopped-no-download-fallback" in script
    assert "clickOrSave(candidate)" not in script
    assert "anchor.click()" not in script
    assert "allowNewestFallback" not in script

    event = client.get(
        "/api/grok-handoff/observed-post-priority/bookmarklet-event",
        query_string={
            "operatorApproved": "true",
            "sceneId": "scene-01",
            "eventType": "bookmarklet-post-download",
            "status": "clicked",
            "detail": "visible-video-fallback-proof-only:visible video fallback proof-only",
            "sourceKind": "visible-video-fallback",
            "videoWidth": "416",
            "videoHeight": "752",
            "qualityFloorMet": "false",
            "qualityNote": "visible-video-below-floor:416x752",
        },
    )
    assert event.status_code == 200
    latest = event.get_json()["latestExtensionEvent"]
    assert latest["sourceKind"] == "visible-video-fallback"
    assert latest["videoWidth"] == "416"
    assert latest["videoHeight"] == "752"
    assert latest["qualityFloorMet"] == "false"
    assert latest["qualityNote"] == "visible-video-below-floor:416x752"


def test_grok_handoff_flags_production_meta_prompt_seed(tmp_path):
    client = _grok_test_client(tmp_path)

    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "grok-meta-prompt",
            "templateType": "persona_story",
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "display_text": "이번 영상은 조용한 루틴의 의도를 설명합니다.",
                    "narration": "시청자가 지금 무엇을 봐야 하는지 TTS로 짧게 짚고 화면은 그대로 둡니다.",
                    "duration": 4,
                }
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    scene = data["scenes"][0]
    assert scene["promptQuality"]["status"] == "needs-rewrite"
    assert scene["promptQuality"]["checks"]["visualSeedNotMeta"] is False
    assert "이번영상은" in scene["promptQuality"]["productionMetaTerms"]
    assert "이번 영상은 조용한 루틴의 의도를 설명합니다" not in scene["prompt"]
    assert "Rewrite required before generation" not in scene["prompt"]
    assert scene["promptQuality"]["standard"] == "concise-positive-shot-v1"
    assert scene["promptQuality"]["rulesetVersion"] == routes_grok.GROK_GENERATION_PROMPT_RULESET_VERSION
    assert scene["promptQuality"]["checks"]["largePhysicalMotion"] is False
    assert "largePhysicalMotion" in scene["promptQuality"]["missing"]
    assert "largePhysicalMotion" in scene["promptQuality"]["repairHints"]
    assert "one large first-second physical action" in scene["promptQuality"]["operatorAction"]
    take_two = scene["takePrompts"][1]
    assert take_two["promptQuality"]["status"] == "needs-rewrite"
    assert take_two["promptQuality"]["checks"]["visualSeedNotMeta"] is False
    queue_html = Path(data["productionQueuePath"]).read_text(encoding="utf-8")
    assert routes_grok.GROK_PRODUCTION_QUEUE_VERSION == "take-ladder-v11-shot-lock-quality-floor"
    assert "production intent, narration, TTS, caption, layout, or checklist notes" in queue_html
    assert "do not bake text or explanatory intent into Grok clips" in queue_html


def test_grok_handoff_accepts_nested_production_context(tmp_path):
    client = _grok_test_client(tmp_path)

    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "nested-production-context",
            "prompt": "Korean after-work reset routine with the same worker, room, and warm lamp.",
            "productionContext": {
                "templateType": "authentic_vlog",
                "targetDuration": "21s",
                "tone": "casual_heyo",
                "lang": "ko",
                "subtitleStyle": "shorts",
            },
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Korean office worker in navy coat stops walking on a subway platform while train lights move behind them.",
                    "hook_note": "Train light motion and the worker slowing down are visible immediately.",
                    "continuity_note": "Same worker, navy coat, small black backpack, teal-and-warm night lighting.",
                    "layout_variant_note": "Keep lower third and right edge clean.",
                    "caption_preset": "top-hook",
                    "duration": 4,
                }
            ],
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
        },
    )

    assert response.status_code == 200
    manifest = json.loads(Path(response.get_json()["manifestPath"]).read_text(encoding="utf-8"))
    assert manifest["productionContext"]["templateType"] == "authentic_vlog"
    assert manifest["productionContext"]["targetDuration"] == "21s"
    assert manifest["productionContext"]["tone"] == "casual_heyo"
    assert manifest["productionContext"]["lang"] == "ko"
    assert manifest["productionContext"]["subtitleStyle"] == "shorts"
    assert manifest["shotBible"]["productionProfile"]["templateType"] == "authentic_vlog"
    assert manifest["shotBible"]["productionProfile"]["family"] == "authentic-vlog"
    scene_prompt = manifest["scenes"][0]["prompt"]
    assert "Template family: authentic-vlog" not in scene_prompt
    assert "phone-camera realism" in scene_prompt
    assert "glossy ad" not in scene_prompt
    assert "news-or-explainer" not in scene_prompt
    assert manifest["scenes"][0]["promptQuality"]["status"] == "ready"


def test_grok_handoff_status_backfills_production_queue_for_legacy_packet(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "legacy-production-queue",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same worker opens the studio door after work.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Same worker turns on a warm desk lamp.",
                    "duration": 4,
                },
            ],
        },
    )
    data = created.get_json()
    handoff_dir = Path(data["handoffDir"])
    manifest_path = Path(data["manifestPath"])
    queue_path = Path(data["productionQueuePath"])
    assert queue_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("productionQueuePath", None)
    manifest.pop("productionQueueUrl", None)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    queue_path.unlink()

    status = client.get("/api/grok-handoff/legacy-production-queue/status")

    assert status.status_code == 200
    status_data = status.get_json()
    assert status_data["productionQueueUrl"].endswith("/api/grok-handoff/legacy-production-queue/production-queue")
    assert status_data["productionQueueVersion"] == routes_grok.GROK_PRODUCTION_QUEUE_VERSION
    backfilled = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert backfilled["productionQueueUrl"] == status_data["productionQueueUrl"]
    assert backfilled["productionQueueVersion"] == routes_grok.GROK_PRODUCTION_QUEUE_VERSION
    assert Path(backfilled["productionQueuePath"]).exists()
    assert Path(backfilled["productionQueuePath"]).parent == handoff_dir

    automation_plan = client.get("/api/grok-handoff/legacy-production-queue/automation-plan").get_json()
    assert automation_plan["productionQueueUrl"] == status_data["productionQueueUrl"]
    assert automation_plan["manualPrimaryPath"]["productionQueueUrl"] == status_data["productionQueueUrl"]


def test_grok_handoff_status_refreshes_legacy_production_queue_version(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "legacy-production-queue-version",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same worker checks a quiet kitchen timer.",
                    "duration": 4,
                },
            ],
        },
    )
    data = created.get_json()
    manifest_path = Path(data["manifestPath"])
    queue_path = Path(data["productionQueuePath"])
    queue_path.write_text("<html><body>old one-prompt queue</body></html>", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("productionQueueVersion", None)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    status = client.get("/api/grok-handoff/legacy-production-queue-version/status")

    assert status.status_code == 200
    refreshed = queue_path.read_text(encoding="utf-8")
    assert routes_grok.GROK_PRODUCTION_QUEUE_VERSION in refreshed
    assert "candidate floor: generate 2+ takes before accepting Grok-main" in refreshed
    assert "Grok-main readiness" in refreshed
    assert "Downloads watcher" in refreshed
    updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated_manifest["productionQueueVersion"] == routes_grok.GROK_PRODUCTION_QUEUE_VERSION


def test_grok_handoff_status_keeps_current_queue_without_live_rewrite(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "current-production-queue",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same worker lifts a backpack strap while platform lights move behind them.",
                    "duration": 4,
                },
            ],
        },
    )
    data = created.get_json()
    assert Path(data["productionQueuePath"]).exists()

    def fail_live_queue_write(handoff_dir, manifest):  # pragma: no cover - must not run
        raise AssertionError("status polling should not rewrite a current production queue")

    monkeypatch.setattr(routes_grok, "_write_production_queue", fail_live_queue_write)

    status = client.get("/api/grok-handoff/current-production-queue/status")

    assert status.status_code == 200
    status_data = status.get_json()
    assert status_data["productionQueueVersion"] == routes_grok.GROK_PRODUCTION_QUEUE_VERSION
    assert status_data["productionQueueUrl"].endswith("/api/grok-handoff/current-production-queue/production-queue")


def test_grok_handoff_status_reuses_single_asset_scan(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "status-single-scan",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same worker pauses on a Seoul subway platform as train lights slide behind them.",
                    "duration": 4,
                },
            ],
        },
    )
    calls = {"count": 0}

    def fake_match_downloaded_assets(handoff_dir, manifest):
        calls["count"] += 1
        return [
            {
                "sceneId": "scene-01",
                "expectedFileName": "scene-01.grok.mp4",
                "status": "missing",
                "qualityGate": {"status": "missing"},
            }
        ]

    monkeypatch.setattr(routes_grok, "_match_downloaded_assets", fake_match_downloaded_assets)

    status = client.get("/api/grok-handoff/status-single-scan/status")

    assert status.status_code == 200
    assert calls["count"] == 1


def test_grok_handoff_packages_concise_prompts_without_truncated_neighbor_intents(tmp_path):
    client = _grok_test_client(tmp_path)

    long_room_prompt = (
        "Late-20s Korean office worker in a navy coat enters the same small Seoul studio room, "
        "places a black backpack on the chair, lowers a warm desk lamp, and opens a notebook while "
        "teal city light moves across the wall; keep the shot handheld, observational, and ordinary."
    )
    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "concise-grok-prompts",
            "templateType": "authentic_vlog",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": (
                        "Late-20s Korean office worker in a navy coat stands on a Seoul subway platform "
                        "as train lights slide past, then loosens the same black backpack strap and exhales."
                    ),
                    "hook_note": "train light movement and strap loosening start immediately",
                    "continuity_note": "same navy coat, black backpack, teal shadows, warm practical light",
                    "caption_preset": "lower-info",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": long_room_prompt,
                    "hook_note": "lamp movement begins in the first second",
                    "continuity_note": "same worker, same backpack, same teal and warm night palette",
                    "caption_preset": "lower-info",
                    "duration": 4,
                },
            ],
        },
    )

    assert response.status_code == 200
    manifest = json.loads(Path(response.get_json()["manifestPath"]).read_text(encoding="utf-8"))
    for scene in manifest["scenes"]:
        prompt = scene["prompt"]
        assert len(prompt) <= 520
        assert "Next scene intent" not in prompt
        assert "Previous scene intent" not in prompt
        assert "Reject before download" not in prompt
        assert "..." not in prompt
        assert "raw footage for editing" not in prompt
        assert "Shot lock:" not in prompt
        assert "caption-safe" not in prompt
        assert scene["promptQuality"]["standard"] == "concise-positive-shot-v1"
        assert scene["promptQuality"]["rulesetVersion"] == routes_grok.GROK_GENERATION_PROMPT_RULESET_VERSION
        assert scene["promptQuality"]["status"] == "ready"
        assert scene["promptQuality"]["checks"]["largePhysicalMotion"] is True
        assert scene["promptQuality"]["checks"]["observableFirstSecondChange"] is True
        assert scene["promptQuality"]["checks"]["singleContinuousShot"] is True
        assert scene["promptQuality"]["checks"]["cameraConcrete"] is True
        assert scene["promptQuality"]["checks"]["propContinuityAnchor"] is True
        assert scene["promptQuality"]["repairHints"] == {}
        for take in scene["takePrompts"]:
            assert len(take["prompt"]) <= 520
            assert "Grok candidate take" not in take["prompt"]
            assert "Take 2 focus" not in take["prompt"]
            assert "Shot lock:" not in take["prompt"]
            assert "..." not in take["prompt"]
            assert "Vertical 9:16 phone MP4" in take["prompt"]
            assert "4-6 seconds" in take["prompt"]
            assert "in the first." not in take["prompt"]
            assert "; first." not in take["prompt"]
            assert take["promptQuality"]["brokenPromptFragments"] == []
            assert take["promptQuality"]["checks"]["completeSentences"] is True
            assert take["promptQuality"]["rulesetVersion"] == routes_grok.GROK_GENERATION_PROMPT_RULESET_VERSION
            assert take["promptQuality"]["checks"]["largePhysicalMotion"] is True
            assert take["promptQuality"]["checks"]["observableFirstSecondChange"] is True
            assert take["promptQuality"]["status"] == "ready"
    assert "Motion-first take" in manifest["scenes"][0]["takePrompts"][1]["prompt"]
    assert "next beat" not in manifest["scenes"][0]["prompt"]
    assert "previous beat" not in manifest["scenes"][1]["prompt"]

    command = client.get(
        "/api/grok-handoff/concise-grok-prompts/extension-command?operatorApproved=true&sceneId=scene-02&take=2"
    )
    assert command.status_code == 200
    command_data = command.get_json()
    assert command_data["takeNumber"] == 2
    assert command_data["takeLabel"] == "motion-first"
    assert command_data["promptQuality"]["status"] == "ready"
    assert "Vertical 9:16 phone MP4" in command_data["prompt"]
    assert "4-6 seconds" in command_data["prompt"]
    assert "in the first." not in command_data["prompt"]
    assert "; first." not in command_data["prompt"]
    assert command_data["promptQuality"]["brokenPromptFragments"] == []
    assert command_data["promptQuality"]["rulesetVersion"] == routes_grok.GROK_GENERATION_PROMPT_RULESET_VERSION
    assert command_data["promptQuality"]["checks"]["largePhysicalMotion"] is True


def test_grok_handoff_marks_weak_generic_source_prompts_for_rewrite(tmp_path):
    client = _grok_test_client(tmp_path)

    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "weak-grok-prompt",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                }
            ],
        },
    )

    assert response.status_code == 200
    scene = response.get_json()["scenes"][0]
    assert scene["promptQuality"]["status"] == "needs-rewrite"
    assert scene["promptQuality"]["weakSourcePrompt"] is True
    assert "sceneSpecificIntent" in scene["promptQuality"]["missing"]
    assert scene["promptQuality"]["rulesetVersion"] == routes_grok.GROK_GENERATION_PROMPT_RULESET_VERSION
    worksheet = Path(response.get_json()["worksheetPath"]).read_text(encoding="utf-8")
    assert "prompt quality: needs-rewrite" in worksheet


def test_grok_handoff_prompt_quality_rejects_generic_source_prompt(tmp_path):
    client = _grok_test_client(tmp_path)

    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "weak-prompt-quality",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Hero.",
                    "duration": 4,
                },
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    scene = data["scenes"][0]
    assert scene["promptQuality"]["status"] == "needs-rewrite"
    assert scene["promptQuality"]["weakSourcePrompt"] is True
    assert "sceneSpecificIntent" in scene["promptQuality"]["missing"]
    assert "sourceActionCue" in scene["promptQuality"]["missing"]
    assert "largePhysicalMotion" in scene["promptQuality"]["missing"]
    assert scene["promptQuality"]["checks"]["largePhysicalMotion"] is False
    assert "largePhysicalMotion" in scene["promptQuality"]["repairHints"]
    assert scene["promptQuality"]["operatorAction"].startswith("Rewrite the scene Grok prompt")


def test_grok_handoff_blocks_weak_prompt_extension_command_before_generation(tmp_path):
    client = _grok_test_client(tmp_path)

    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "weak-prompt-command-block",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Hero.",
                    "duration": 4,
                },
            ],
        },
    )
    assert created.status_code == 200
    scene = created.get_json()["scenes"][0]
    assert scene["promptQuality"]["status"] == "needs-rewrite"

    blocked = client.get(
        "/api/grok-handoff/weak-prompt-command-block/extension-command"
        "?operatorApproved=true&sceneId=scene-01&take=2"
    )

    assert blocked.status_code == 409
    payload = blocked.get_json()
    assert payload["ok"] is False
    assert payload["status"] == "blocked-prompt-quality"
    assert payload["promptQuality"]["status"] == "needs-rewrite"
    assert "largePhysicalMotion" in payload["promptQuality"]["missing"]
    assert "Rewrite the scene Grok prompt" in payload["operatorAction"]
    assert "allowWeakPrompt=true" in payload["debugOverride"]

    bookmarklet = client.get(
        "/api/grok-handoff/weak-prompt-command-block/bookmarklet.js"
        "?operatorApproved=true&sceneId=scene-01&take=2&autoGenerate=true"
    )
    assert bookmarklet.status_code == 409
    assert bookmarklet.get_json()["status"] == "blocked-prompt-quality"

    debug = client.get(
        "/api/grok-handoff/weak-prompt-command-block/extension-command"
        "?operatorApproved=true&sceneId=scene-01&take=2&allowWeakPrompt=true"
    )
    assert debug.status_code == 200
    assert debug.get_json()["promptQuality"]["status"] == "needs-rewrite"


def test_grok_handoff_accepts_physical_action_source_prompt(tmp_path):
    client = _grok_test_client(tmp_path)

    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "physical-action-prompt",
            "templateType": "authentic_vlog",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": (
                        "Late-20s Korean office worker in a navy coat on a Seoul subway platform "
                        "tightens then loosens the same black backpack strap while train light streaks pass behind them."
                    ),
                    "hook_note": "backpack strap motion and train lights start immediately",
                    "continuity_note": "same navy coat, black backpack, teal subway shadows",
                    "layout_variant_note": "subject face and backpack stay upper-middle; lower-left third remains clean",
                    "caption_preset": "lower-info",
                    "duration": 4,
                }
            ],
        },
    )

    assert response.status_code == 200
    scene = response.get_json()["scenes"][0]
    assert scene["promptQuality"]["status"] == "ready"
    assert scene["promptQuality"]["weakSourcePrompt"] is False
    assert scene["promptQuality"]["checks"]["sourceActionCue"] is True
    assert scene["promptQuality"]["checks"]["specificAction"] is True
    assert scene["promptQuality"]["checks"]["largePhysicalMotion"] is True
    assert scene["promptQuality"]["checks"]["observableFirstSecondChange"] is True
    assert scene["promptQuality"]["checks"]["singleContinuousShot"] is True
    assert scene["promptQuality"]["checks"]["cameraConcrete"] is True
    assert scene["promptQuality"]["checks"]["controlledCameraStyle"] is True
    assert scene["promptQuality"]["controlledCameraStyleTerms"]
    assert scene["promptQuality"]["checks"]["propContinuityAnchor"] is True
    assert scene["promptQuality"]["repairHints"] == {}


def test_grok_handoff_fresh_concept_packet_preserves_reference_action_voice_and_risk(tmp_path):
    client = _grok_test_client(tmp_path)

    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "fresh-concept-packet",
            "templateType": "ranking_list",
            "freshConceptRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": (
                        "A Korean night-market vendor pulls up a metal shutter, warm stall lights switch on, "
                        "and steam rolls across stacked paper cups in the first second."
                    ),
                    "hook_note": "metal shutter lift and steam movement start immediately",
                    "continuity_note": "same red stall awning, paper cups, stainless counter, warm sodium light",
                    "reference_note": "phone-shot Korean night market stall opening, handheld close distance",
                    "action_beat": "vendor lifts the shutter and reveals the lit stall in one continuous motion",
                    "visual_risk": "reject if it becomes generic food b-roll without the shutter movement",
                    "voice_requirement": "voice required; short zero-paid or operator-owned narration explains rank one",
                    "quality_rationale": "large shutter movement and steam make the first-second hook easy to judge",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": (
                        "The same vendor pours bright sauce from a squeeze bottle onto skewers while a gloved hand "
                        "turns the tray under warm stall lighting."
                    ),
                    "hook_note": "sauce pour and tray turn begin in the first second",
                    "continuity_note": "same red awning, stainless counter, paper cups, warm night-market light",
                    "reference_note": "raw phone-camera food stall prep shot, close hands and tray",
                    "action_beat": "sauce pour and tray turn create clear visible motion",
                    "visual_risk": "reject if hands melt or the tray changes shape between frames",
                    "voice_required": True,
                    "quality_rationale": "pouring sauce and hand rotation are larger motion than subtle posture changes",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-03",
                    "scene_num": 3,
                    "image_source": "grok",
                    "grok_prompt": (
                        "A customer slides a transit card across the counter, the same vendor places a wrapped paper cup "
                        "beside it, and steam drifts upward."
                    ),
                    "hook_note": "card slide and cup placement start immediately",
                    "continuity_note": "same stall counter, paper cup, red awning, warm sodium light",
                    "reference_note": "close counter exchange at a Korean food stall, phone camera height",
                    "action_beat": "card slide and cup placement make the payoff readable without tiny expressions",
                    "visual_risk": "reject if the exchange turns into a glossy product ad or unreadable montage",
                    "voice_requirement": "voice required; one natural spoken payoff line after source acceptance",
                    "quality_rationale": "object exchange gives an obvious before/after state for review",
                    "duration": 4,
                },
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    packet = data["freshConceptPacket"]
    assert packet["required"] is True
    assert packet["status"] == "ready"
    assert packet["sceneCount"] == 3
    assert packet["missing"] == []
    assert packet["oldShoulderReleaseRisk"] is False
    assert [item["sceneId"] for item in packet["scenes"]] == ["scene-01", "scene-02", "scene-03"]
    assert all(item["complete"] is True for item in packet["scenes"])
    assert all(item["promptQualityStatus"] == "ready" for item in packet["scenes"])
    assert data["scenes"][0]["freshConcept"]["referenceNote"].startswith("phone-shot Korean night market")
    assert "voice required" in data["scenes"][1]["freshConcept"]["voiceRequirement"]
    assert data["scenes"][2]["actionBeat"].startswith("card slide")
    assert data["scenes"][0]["promptQuality"]["standard"] == "concise-positive-shot-v1"
    assert data["scenes"][0]["promptQuality"]["rulesetVersion"] == routes_grok.GROK_GENERATION_PROMPT_RULESET_VERSION
    assert all(scene["promptQuality"]["checks"]["largePhysicalMotion"] is True for scene in data["scenes"])
    assert all(scene["promptQuality"]["checks"]["observableFirstSecondChange"] is True for scene in data["scenes"])

    manifest = json.loads(Path(data["manifestPath"]).read_text(encoding="utf-8"))
    assert manifest["freshConceptPacket"]["status"] == "ready"
    assert manifest["shotBible"]["promptRulesetVersion"] == routes_grok.GROK_GENERATION_PROMPT_RULESET_VERSION
    worksheet = Path(data["worksheetPath"]).read_text(encoding="utf-8")
    assert "Fresh concept packet" in worksheet
    assert "Fresh concept notes" in worksheet
    assert "vendor lifts the shutter" in worksheet
    review_html = Path(data["reviewPacketPath"]).read_text(encoding="utf-8")
    assert "Fresh concept packet" in review_html
    assert "Fresh concept notes" in review_html
    assert "object exchange gives an obvious before/after state" in review_html
    queue_html = Path(data["productionQueuePath"]).read_text(encoding="utf-8")
    assert "Fresh concept notes" in queue_html
    assert "reject if it becomes generic food b-roll" in queue_html

    status = client.get("/api/grok-handoff/fresh-concept-packet/status")
    assert status.status_code == 200
    assert status.get_json()["freshConceptPacket"]["status"] == "ready"


def test_grok_handoff_ab_preregistration_packet_surfaces_locked_rubric_and_take_budget(tmp_path):
    client = _grok_test_client(tmp_path)

    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "ab-prereg-ready",
            "templateType": "authentic_vlog",
            "abPreregistration": {
                "topicCountRequired": 3,
                "lockedTopics": [
                    {
                        "id": "topic-reset-routine",
                        "label": "퇴근 후 20분 리셋 루틴",
                        "appPromptInput": "Video Studio prompt uses visible timer, bag drop, and desk reset motion.",
                        "manualPrompt": "Manual Grok baseline: office worker starts a realistic after-work reset routine.",
                        "acceptanceNote": "Winner must make the first action readable without captions.",
                    },
                    {
                        "id": "topic-popup-recap",
                        "label": "성수 팝업 현장 5분 요약",
                        "appPromptInput": "Video Studio prompt locks line movement, product handoff, and storefront context.",
                        "manualPrompt": "Manual Grok baseline: busy Seoul popup store recap with crowd movement.",
                        "acceptanceNote": "Winner must avoid generic shopping b-roll.",
                    },
                    {
                        "id": "topic-sneaker-ranking",
                        "label": "비싼 운동화 Top 3",
                        "appPromptInput": "Video Studio prompt locks shoe-box opening, receipt reveal, and hand motion.",
                        "manualPrompt": "Manual Grok baseline: premium sneaker ranking hero shot.",
                        "acceptanceNote": "Winner must keep object continuity and no baked text.",
                    },
                ],
                "takeBudget": {
                    "appPromptTakesPerTopic": 2,
                    "manualPromptTakesPerTopic": 2,
                    "minimumImportedTakesPerScene": 2,
                },
                "rubric": {
                    "winRule": "App prompt wins only if total score ties or beats manual with no hard-fail dimension.",
                    "dimensions": [
                        {"id": "hook", "label": "Hook clarity", "weight": 30, "passRule": "Action reads in the first second."},
                        {"id": "source-fit", "label": "Source fit", "weight": 25, "passRule": "Clip fits the locked topic exactly."},
                        {"id": "artifacts", "label": "Artifact control", "weight": 25, "passRule": "No morphing, watermark, or baked text."},
                        {"id": "composition", "label": "Caption-safe composition", "weight": 20, "passRule": "Main action stays clear for captions."},
                    ],
                },
                "archivePath": "storage/qa/ab-20260710/",
            },
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": (
                        "A Korean office worker in a navy jacket drops a black work bag onto a chair, "
                        "starts a red kitchen timer, and slides a notebook open as desk light moves across the wall."
                    ),
                    "hook_note": "bag drop, timer press, and notebook slide begin immediately",
                    "continuity_note": "same navy jacket, black work bag, red timer, small desk lamp",
                    "layout_variant_note": "hands and timer stay upper-middle while lower third remains clean",
                    "caption_preset": "lower-info",
                    "duration": 4,
                }
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    packet = data["abPreregistration"]
    assert packet["schema"] == "video-studio.grok-ab-preregistration.v1"
    assert packet["required"] is True
    assert packet["status"] == "ready"
    assert packet["topicCount"] == 3
    assert packet["topicCountRequired"] == 3
    assert packet["missing"] == []
    assert packet["manualPromptInputsComplete"] is True
    assert packet["appPromptInputsComplete"] is True
    assert packet["takeBudget"]["appPromptTakesPerTopic"] == 2
    assert packet["takeBudget"]["manualPromptTakesPerTopic"] == 2
    assert packet["takeBudget"]["minimumImportedTakesPerScene"] == 2
    assert packet["takeBudget"]["preserveRejectedTakes"] is True
    assert packet["archivePlan"]["preserveRejectedTakes"] is True
    assert packet["archivePlan"]["targetPath"] == "storage/qa/ab-20260710/"
    assert [arm["id"] for arm in packet["comparisonArms"]] == ["app-prompt", "manual-grok"]
    assert packet["comparisonArms"][0]["promptInputsLocked"] is True
    assert packet["comparisonArms"][1]["promptInputsLocked"] is True
    assert packet["rubric"]["winRule"].startswith("App prompt wins")
    assert packet["rubric"]["totalWeight"] == 100
    assert packet["rubric"]["dimensions"][0]["label"] == "Hook clarity"
    assert "퇴근 후 20분 리셋 루틴" in packet["lockedTopics"][0]["label"]

    manifest = json.loads(Path(data["manifestPath"]).read_text(encoding="utf-8"))
    assert manifest["abPreregistration"]["status"] == "ready"
    assert manifest["abPreregistration"]["takeBudget"]["preserveRejectedTakes"] is True
    assert data["manualPrimaryPath"]["abPreregistration"]["status"] == "ready"
    assert any("A/B preregistration packet" in item for item in data["manualPrimaryPath"]["operatorSteps"])

    worksheet = Path(data["worksheetPath"]).read_text(encoding="utf-8")
    assert "A/B preregistration" in worksheet
    assert "퇴근 후 20분 리셋 루틴" in worksheet
    assert "preserve rejected takes: True" in worksheet
    queue_html = Path(data["productionQueuePath"]).read_text(encoding="utf-8")
    assert "A/B preregistration" in queue_html
    assert "storage/qa/ab-20260710/" in queue_html
    assert "Preserve rejected takes: True" in queue_html
    review_html = Path(data["reviewPacketPath"]).read_text(encoding="utf-8")
    assert "A/B preregistration" in review_html
    assert "Hook clarity" in review_html

    status = client.get("/api/grok-handoff/ab-prereg-ready/status")
    assert status.status_code == 200
    status_packet = status.get_json()["abPreregistration"]
    assert status_packet["status"] == "ready"
    assert status_packet["archivePlan"]["preserveRejectedTakes"] is True

    extension_command = client.get(
        "/api/grok-handoff/ab-prereg-ready/extension-command?operatorApproved=true&sceneId=scene-01&take=2"
    )
    assert extension_command.status_code == 200
    command_payload = extension_command.get_json()
    assert command_payload["abPreregistration"]["status"] == "ready"
    assert command_payload["abPreregistration"]["takeBudget"]["minimumImportedTakesPerScene"] == 2


def test_grok_handoff_fresh_concept_packet_rejects_old_shoulder_release_benchmark(tmp_path):
    client = _grok_test_client(tmp_path)

    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "old-shoulder-concept",
            "templateType": "authentic_vlog",
            "freshConceptRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Korean office worker at a desk rolls tense shoulders and slowly releases the tension.",
                    "hook_note": "shoulder release starts in the first second",
                    "continuity_note": "same office desk and muted wall light",
                    "reference_note": "old office shoulder-release attempt",
                    "action_beat": "shoulders tense then relax",
                    "visual_risk": "subtle posture change is hard to judge and already failed",
                    "voice_requirement": "voice required if this were an information format",
                    "quality_rationale": "this intentionally repeats the rejected baseline",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "image_source": "grok",
                    "grok_prompt": "The same office worker opens a notebook and moves a pen across the desk.",
                    "hook_note": "notebook opening starts immediately",
                    "continuity_note": "same office desk and muted wall light",
                    "reference_note": "office continuation",
                    "action_beat": "notebook opens and pen moves",
                    "visual_risk": "too close to the stale office runway",
                    "voice_requirement": "voice required",
                    "quality_rationale": "included only to prove stale packet rejection",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-03",
                    "image_source": "grok",
                    "grok_prompt": "The same worker places a mug beside the notebook while desk light moves across the wall.",
                    "hook_note": "mug placement starts immediately",
                    "continuity_note": "same office desk and muted wall light",
                    "reference_note": "office payoff",
                    "action_beat": "mug placement creates a small object change",
                    "visual_risk": "office context keeps the stale benchmark alive",
                    "voice_requirement": "voice required",
                    "quality_rationale": "included only to prove stale packet rejection",
                    "duration": 4,
                },
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    packet = data["freshConceptPacket"]
    assert packet["status"] == "needs-rewrite"
    assert "oldShoulderReleaseConcept" in packet["missing"]
    assert packet["oldShoulderReleaseRisk"] is True
    assert packet["oldShoulderReleaseSceneIds"] == ["scene-01"]
    assert packet["scenes"][0]["oldShoulderReleaseRisk"] is True
    assert packet["scenes"][0]["complete"] is False
    stale_scene_quality = data["scenes"][0]["promptQuality"]
    assert stale_scene_quality["status"] == "needs-rewrite"
    assert stale_scene_quality["checks"]["largePhysicalMotion"] is False
    assert "largePhysicalMotion" in stale_scene_quality["missing"]
    assert "largePhysicalMotion" in stale_scene_quality["repairHints"]


def test_grok_handoff_review_packet_previews_imported_mp4s_and_operator_checks(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "review-packet-case",
            "prompt": "Warm cafe continuity reel with the same white cup.",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "title": "Steam hook",
                    "image_source": "grok",
                    "grok_prompt": "Macro steam rising from the same white ceramic cup.",
                    "continuity_note": "Same white cup, same wooden counter, warm amber light.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"review packet mp4")

    response = client.get("/api/grok-handoff/review-packet-case/review-packet")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Grok clip review packet" in html
    assert "Automation direction" in html
    assert "Shot bible" in html
    assert "Production family" in html
    assert "Prompt production gate" in html
    assert "Grok take ladder for candidate generation" in html
    assert "Take 2: motion-first" in html
    assert "Hard reject checklist" in html
    assert "same white cup" in html
    assert "<video" in html
    assert "/api/grok-handoff/review-packet-case/asset/scene-01.grok.mp4" in html
    assert "Operator decision" in html
    assert "First 2 seconds contain visible motion" in html
    assert "data-review-scene=\"scene-01\"" in html
    assert "/review-decision" in html
    assert "Accept clip" in html
    assert "Reject clip" in html
    assert "source_rationale" in html
    assert "quality_review_note" in html
    assert "caption/layout review" in html
    assert "Visual verdict" in html
    assert "Shot lock acceptance" in html
    assert "shot-lock evidence" in html
    assert "scene assembly role" in html
    assert "Grok candidate curation" in html
    assert "Selection rule" in html
    assert "YouTube/Korean Shorts benchmark comparison note" in html


def test_grok_handoff_review_packet_returns_404_for_missing_manifest(tmp_path):
    client = _grok_test_client(tmp_path)

    response = client.get("/api/grok-handoff/not-created/review-packet")

    assert response.status_code == 404
    assert response.get_json()["ok"] is False


def test_grok_handoff_review_decision_persists_and_feeds_render_payload(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "review-accept",
            "prompt": "Grok accepted review reel",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"accepted grok mp4")

    decision = client.post(
        "/api/grok-handoff/review-accept/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Operator accepted Grok clip because it keeps the same cup and warm light.",
            "qualityReviewNote": "No watermark, no baked-in text, stable motion, subject remains caption-safe.",
            "operatorNote": "Approved after review packet preview.",
        },
    )

    assert decision.status_code == 200
    decision_data = decision.get_json()
    assert decision_data["ok"] is True
    assert decision_data["reviewDecision"]["accepted"] is True
    assert decision_data["renderPayload"]["allReady"] is True
    draft = decision_data["renderPayload"]["draftScenes"][0]
    assert draft["source_rationale"].startswith("Operator accepted Grok clip")
    assert draft["quality_review_note"].startswith("No watermark")
    assert draft["grok_review_note"] == "Approved after review packet preview."
    manifest = json.loads((tmp_path / "storage" / "grok-handoffs" / "review-accept" / "handoff.json").read_text(encoding="utf-8"))
    assert manifest["reviewDecisions"]["scene-01"]["accepted"] is True
    assert manifest["reviewDecisions"]["scene-01"]["firstTwoSecondHook"] is True


def test_grok_handoff_visual_led_persona_story_defaults_to_no_voice(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "visual-led-no-voice",
            "templateType": "persona_story",
            "grokMainSourceRequired": True,
            "prompt": "Recurring office persona visual story",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Recurring office persona pauses at a meeting room door.",
                    "narration": "이 영상은 AI 티가 안 나도록 같은 인물을 유지하는 의도로 만들었습니다.",
                    "narrationText": "시청자에게 이 장면의 제작 의도를 TTS로 설명합니다.",
                    "display_text": "잠깐만\n보자",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"persona story grok mp4")
    (incoming / "scene-01-alt.grok.mp4").write_bytes(b"alternate persona story grok mp4")

    decision = client.post(
        "/api/grok-handoff/visual-led-no-voice/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "selectedFileName": "scene-01.grok.mp4",
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Operator selected the Grok take because it keeps the same persona and door action.",
            "qualityReviewNote": "No watermark, no baked-in text, stable motion, subject remains caption-safe.",
            "selectedCandidateSummary": "Take 1 preserves the door pause better than take 2 while keeping the same persona.",
            "operatorNote": "Approved as a visual-led persona story take.",
            **_grok_main_quality_fields(),
        },
    )

    assert decision.status_code == 200
    render_payload = decision.get_json()["renderPayload"]
    draft = render_payload["draftScenes"][0]
    assert draft["narration"] == ""
    assert draft["narrationText"] == ""
    assert draft["audio_design_mode"] == "no-voice"
    assert draft["audioDesignMode"] == "no-voice"
    assert "No-voice Grok-first edit" in draft["audio_mix_review_note"]
    assert render_payload["audioDesignMode"] == "ambient-first"


def test_grok_handoff_review_decision_reject_blocks_render_payload(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "review-reject",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"rejected grok mp4")

    decision = client.post(
        "/api/grok-handoff/review-reject/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": False,
            "operatorNote": "Rejected: flicker and random extra cup appear in the first second.",
        },
    )
    payload = client.get("/api/grok-handoff/review-reject/render-payload")

    assert decision.status_code == 200
    decision_data = decision.get_json()
    assert decision_data["renderPayload"]["allReady"] is False
    assert decision_data["renderPayload"]["rejectedSceneIds"] == ["scene-01"]
    assert decision_data["renderPayload"]["sceneAssets"] == []
    assert payload.status_code == 409
    payload_data = payload.get_json()
    assert payload_data["ok"] is False
    assert payload_data["rejectedSceneIds"] == ["scene-01"]
    assert payload_data["draftScenes"][0]["quality_review_note"].startswith("Rejected in Grok review packet")


def test_grok_handoff_review_decision_validates_scene_and_boolean(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "review-validate",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                }
            ],
        },
    )

    wrong_scene = client.post(
        "/api/grok-handoff/review-validate/review-decision",
        json={"sceneId": "scene-99", "accepted": True},
    )
    wrong_type = client.post(
        "/api/grok-handoff/review-validate/review-decision",
        json={"sceneId": "scene-01", "accepted": "yes"},
    )

    assert wrong_scene.status_code == 400
    assert "sceneId" in wrong_scene.get_json()["error"]
    assert wrong_type.status_code == 400
    assert "accepted" in wrong_type.get_json()["error"]


def test_grok_handoff_quality_gate_requires_operator_acceptance_when_enabled(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "durationSec": 4.2,
        "aspectRatio": 0.5625,
        "hasAudio": False,
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "quality-gated",
            "qualityGateRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same character night routine hero.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"quality gated grok mp4")

    status = client.get("/api/grok-handoff/quality-gated/status").get_json()
    assert status["readyScenes"] == 1
    assert status["allReady"] is True
    assert status["qualityGate"]["required"] is True
    assert status["qualityGate"]["allReady"] is False
    assert status["qualityGate"]["pendingSceneIds"] == ["scene-01"]
    assert status["assets"][0]["clipProbe"]["ok"] is True
    assert status["assets"][0]["qualityGate"]["status"] == "pending-operator-review"

    payload = client.get("/api/grok-handoff/quality-gated/render-payload")
    assert payload.status_code == 409
    payload_data = payload.get_json()
    assert payload_data["qualityGateRequired"] is True
    assert payload_data["qualityGateReady"] is False
    assert payload_data["qualityPendingSceneIds"] == ["scene-01"]

    weak_accept = client.post(
        "/api/grok-handoff/quality-gated/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "firstTwoSecondHook": True,
            "artifactFree": False,
            "continuityOk": True,
        },
    )
    assert weak_accept.status_code == 400
    assert "accepted=true requires" in weak_accept.get_json()["error"]

    missing_evidence = client.post(
        "/api/grok-handoff/quality-gated/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
        },
    )
    assert missing_evidence.status_code == 400
    assert "sourceRationale" in missing_evidence.get_json()["error"]
    assert "qualityReviewNote" in missing_evidence.get_json()["error"]

    accepted = client.post(
        "/api/grok-handoff/quality-gated/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Selected because the same worker and backpack continuity are clear.",
            "qualityReviewNote": "Visible motion starts immediately; no text, watermark, or morphing.",
        },
    )
    assert accepted.status_code == 200
    accepted_data = accepted.get_json()
    assert accepted_data["renderPayload"]["allReady"] is True
    assert accepted_data["renderPayload"]["qualityGateReady"] is True
    accepted_status = client.get("/api/grok-handoff/quality-gated/status").get_json()
    assert accepted_status["qualityGate"]["allReady"] is True
    assert accepted_status["assets"][0]["qualityGate"]["status"] == "accepted"


def test_grok_handoff_review_decision_rejects_stale_import_preflight(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "durationSec": 4.2,
        "aspectRatio": 0.5625,
        "hasAudio": False,
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "stale-import-preflight",
            "qualityGateRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same character night routine hero.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    stale_file = incoming / "scene-01.grok.mp4"
    stale_file.write_bytes(b"stale grok exact-name mp4")
    old_timestamp = time.time() - 3600
    os.utime(stale_file, (old_timestamp, old_timestamp))

    status = client.get("/api/grok-handoff/stale-import-preflight/status").get_json()
    assert status["readyScenes"] == 1
    assert status["assets"][0]["importPreflight"]["status"] == "stale"
    assert status["assets"][0]["qualityGate"]["status"] == "import-preflight"

    accepted = client.post(
        "/api/grok-handoff/stale-import-preflight/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Selected because the same worker and backpack continuity are clear.",
            "qualityReviewNote": "Visible motion starts immediately; no text, watermark, or morphing.",
        },
    )

    assert accepted.status_code == 400
    accepted_data = accepted.get_json()
    assert "fresh usable Grok MP4 import preflight" in accepted_data["error"]
    assert accepted_data["importPreflight"]["status"] == "stale"
    manifest = json.loads(
        (
            tmp_path
            / "storage"
            / "grok-handoffs"
            / "stale-import-preflight"
            / "handoff.json"
        ).read_text(encoding="utf-8")
    )
    assert "scene-01" not in manifest.get("reviewDecisions", {})


def test_grok_handoff_acquisition_flags_low_resolution_import_as_replacement_required(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": False,
        "status": "needs-review",
        "width": 416,
        "height": 752,
        "fps": 24,
        "durationSec": 6.04,
        "aspectRatio": 0.5532,
        "hasAudio": True,
        "issues": ["vertical height below review floor: 752"],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "quality-blocker-status",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": (
                        "Late-20s Korean office worker on a subway platform at night, "
                        "train lights moving behind them, raw vertical MP4 footage."
                    ),
                    "duration": 6,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"low resolution cache recovery grok mp4")
    (incoming / "scene-01-alt.grok.mp4").write_bytes(b"second low resolution cache recovery grok mp4")

    status = client.get("/api/grok-handoff/quality-blocker-status/status").get_json()

    assert status["readyScenes"] == 0
    assert status["allReady"] is False
    assert status["nextMissingSceneId"] == "scene-01"
    assert status["nextMissingReason"] == "quality-replacement-required"
    assert status["replacementSceneIds"] == ["scene-01"]
    assert status["assets"][0]["qualityGate"]["status"] == "technical-review"
    assert status["mainSourceGate"]["replacementSceneIds"] == ["scene-01"]
    acquisition = status["grokAssetAcquisition"]
    assert acquisition["state"] == "local-mp4-imported-needs-quality-replacement"
    assert acquisition["localMp4Imported"] is True
    assert acquisition["publishReadyLocalMp4"] is False
    assert acquisition["qualityBlocked"] is True
    assert acquisition["primaryBlocker"] == "local-mp4-below-quality-floor"
    assert acquisition["bestLocalCandidate"]["height"] == 752
    assert any("vertical height below review floor" in item for item in acquisition["qualityBlockers"])
    assert any("recovery proof only" in item for item in acquisition["operatorActionPriority"])
    curation = acquisition["candidateCurationPlan"]
    assert curation["required"] is True
    assert curation["candidateCount"] == 2
    assert curation["publishableCandidateCount"] == 0
    assert curation["reviewReadiness"] == "needs-native-grok-takes"
    assert "Do not render" in curation["recommendation"]
    assert curation["selectedCandidate"]["fileName"] == "scene-01.grok.mp4"
    assert curation["selectedCandidate"]["technicalOk"] is False
    export_plan = acquisition["originalExportPlan"]
    assert export_plan["required"] is True
    assert export_plan["modelBlocked"] is False
    assert export_plan["accountBlocked"] is False
    assert export_plan["paidApiRequired"] is False
    assert export_plan["cdpPrimary"] is False
    assert export_plan["priority"] == "replace-existing-candidate"
    assert export_plan["targetSceneId"] == "scene-01"
    assert export_plan["expectedFileName"] == "scene-01.grok.mp4"
    assert "native Grok MP4 export" in export_plan["summary"]
    assert any("operator-owned manual download/import" in item for item in export_plan["requiredActions"])
    assert "browser currentSrc or cache copy" in export_plan["rejectAsMainSource"]
    review_packet = client.get("/api/grok-handoff/quality-blocker-status/review-packet")
    assert review_packet.status_code == 200
    html = review_packet.get_data(as_text=True)
    assert "Grok candidate curation" in html
    assert "Publishable candidates: 0/2" in html
    assert "Selected candidate:" in html
    assert "scene-01.grok.mp4" in html
    assert "Do not render from the current candidates" in html
    assert "replace with two browser-native/direct-imported or operator-uploaded Grok MP4 takes" in html
    assert "vertical height below review floor: 752" in html
    assert "Accept blocked:" in html


def test_grok_clip_probe_blocks_static_mp4_motion_slop(tmp_path):
    static_clip = tmp_path / "static-grok.mp4"
    _write_probe_fixture_mp4(static_clip, "color=c=black:s=1080x1920:r=30:d=3")

    probe = routes_grok._probe_grok_clip(static_clip)

    assert probe["ok"] is False
    assert probe["motionOk"] is False
    assert probe["motionStatus"] == "low-motion"
    assert any("low motion evidence" in issue for issue in probe["issues"])


def test_grok_clip_probe_accepts_moving_vertical_mp4(tmp_path):
    moving_clip = tmp_path / "moving-grok.mp4"
    _write_probe_fixture_mp4(moving_clip, "testsrc2=s=1080x1920:r=30:d=3")

    probe = routes_grok._probe_grok_clip(moving_clip)

    assert probe["ok"] is True
    assert probe["motionOk"] is True
    assert probe["motionFrameCount"] >= 2
    assert probe["width"] == 1080
    assert probe["height"] == 1920
    assert probe["durationSec"] >= 2.0


def test_grok_clip_probe_rejects_low_resolution_vertical_mp4(tmp_path):
    low_res_clip = tmp_path / "low-res-grok.mp4"
    _write_probe_fixture_mp4(low_res_clip, "testsrc2=s=540x960:r=30:d=3")

    probe = routes_grok._probe_grok_clip(low_res_clip)

    assert probe["ok"] is False
    assert probe["motionOk"] is True
    assert probe["width"] == 540
    assert probe["height"] == 960
    assert any("resolution below native Grok-main floor" in issue for issue in probe["issues"])


def test_grok_main_source_gate_blocks_stock_heavy_handoff_before_render(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "durationSec": 4.2,
        "aspectRatio": 0.5625,
        "hasAudio": False,
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "grok-main-source",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same character night routine hero.",
                    "duration": 4,
                },
                {"sceneId": "scene-02", "scene_num": 2, "image_source": "pexels-video", "duration": 4},
                {"sceneId": "scene-03", "scene_num": 3, "image_source": "pexels-video", "duration": 4},
                {"sceneId": "scene-04", "scene_num": 4, "image_source": "pexels-video", "duration": 4},
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    created_data = created.get_json()
    assert created_data["grokTargetSelection"]["mode"] == "explicit-plus-main-source-expansion"
    assert created_data["grokTargetSelection"]["explicitGrokSceneIds"] == ["scene-01"]
    assert created_data["grokTargetSelection"]["autoExpandedSceneIds"] == ["scene-02"]
    assert [scene["sceneId"] for scene in created_data["scenes"]] == ["scene-01", "scene-02"]
    assert created_data["scenes"][1]["grokAutoExpanded"] is True
    assert created_data["scenes"][1]["originalImageSource"] == "pexels-video"
    (incoming / "scene-01.grok.mp4").write_bytes(b"first grok hero mp4")
    (incoming / "scene-01-grok-take-2.mp4").write_bytes(b"second grok hero mp4")

    accepted = client.post(
        "/api/grok-handoff/grok-main-source/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "selectedFileName": "scene-01-grok-take-2.mp4",
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "The hero has the intended same subject and location.",
            "qualityReviewNote": "Motion starts immediately and the frame is caption-safe.",
            "selectedCandidateSummary": "Take 2 has cleaner hero motion and fewer visible artifacts than the first imported Grok candidate.",
            **_grok_main_quality_fields(),
        },
    )
    assert accepted.status_code == 200
    accepted_payload = accepted.get_json()["renderPayload"]
    assert accepted_payload["allReady"] is False
    assert accepted_payload["mainSourceGate"]["required"] is True
    assert accepted_payload["mainSourceGate"]["status"] == "needs-accepted-grok-clips"
    assert accepted_payload["mainSourceGate"]["sourceMixTotalScenes"] == 4
    assert accepted_payload["mainSourceGate"]["plannedGrokScenes"] == 2
    assert accepted_payload["mainSourceGate"]["minAcceptedScenes"] == 2
    assert accepted_payload["mainSourceGate"]["acceptedSceneIds"] == ["scene-01"]
    assert accepted_payload["mainSourceGate"]["autoExpandedSceneIds"] == ["scene-02"]
    assert accepted_payload["mainSourceGate"]["additionalPlannedScenesNeeded"] == 0
    assert accepted_payload["mainSourceGate"]["additionalAcceptedScenesNeeded"] == 1
    assert accepted_payload["grokTargetSelection"]["autoExpandedSceneIds"] == ["scene-02"]

    status = client.get("/api/grok-handoff/grok-main-source/status").get_json()
    assert status["mainSourceGate"]["allReady"] is False
    assert status["mainSourceGate"]["status"] == "needs-accepted-grok-clips"
    assert status["mainSourceGate"]["missingSceneIds"] == ["scene-02"]
    assert status["grokTargetSelection"]["autoExpandedSceneIds"] == ["scene-02"]

    render_payload = client.get("/api/grok-handoff/grok-main-source/render-payload")
    assert render_payload.status_code == 409
    assert render_payload.get_json()["mainSourceGate"]["status"] == "needs-accepted-grok-clips"


def test_grok_main_source_gate_requires_first_hook_grok_clip(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "durationSec": 4.2,
        "aspectRatio": 0.5625,
        "hasAudio": False,
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "grok-main-first-hook",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {"sceneId": "scene-01", "scene_num": 1, "image_source": "pexels-video", "duration": 4},
                {"sceneId": "scene-02", "scene_num": 2, "image_source": "grok", "grok_prompt": "Mid beat.", "duration": 4},
                {"sceneId": "scene-03", "scene_num": 3, "image_source": "grok", "grok_prompt": "Second mid beat.", "duration": 4},
                {"sceneId": "scene-04", "scene_num": 4, "image_source": "pexels-video", "duration": 4},
            ],
        },
    )
    created_data = created.get_json()
    incoming = Path(created_data["incomingDir"])
    assert created_data["grokTargetSelection"]["mode"] == "explicit-plus-first-hook"
    assert created_data["grokTargetSelection"]["firstHookRequired"] is True
    assert created_data["grokTargetSelection"]["firstHookSceneId"] == "scene-01"
    assert created_data["grokTargetSelection"]["firstHookAutoIncluded"] is True
    assert created_data["grokTargetSelection"]["autoExpandedSceneIds"] == ["scene-01"]
    assert [scene["sceneId"] for scene in created_data["scenes"]] == ["scene-01", "scene-02", "scene-03"]
    assert created_data["scenes"][0]["grokAutoExpanded"] is True
    assert created_data["scenes"][0]["originalImageSource"] == "pexels-video"

    (incoming / "scene-02.grok.mp4").write_bytes(b"grok scene two")
    (incoming / "scene-02-grok-take-2.mp4").write_bytes(b"grok scene two alternate")
    (incoming / "scene-03.grok.mp4").write_bytes(b"grok scene three")
    (incoming / "scene-03-grok-take-2.mp4").write_bytes(b"grok scene three alternate")
    for scene_id in ("scene-02", "scene-03"):
        accepted = client.post(
            "/api/grok-handoff/grok-main-first-hook/review-decision",
            json={
                "sceneId": scene_id,
                "accepted": True,
                "selectedFileName": f"{scene_id}-grok-take-2.mp4",
                "firstTwoSecondHook": True,
                "artifactFree": True,
                "continuityOk": True,
                "captionSafe": True,
                "sourceRationale": f"{scene_id} keeps the same room and subject continuity.",
                "qualityReviewNote": "Natural motion, no watermark, and captions have safe framing.",
                "selectedCandidateSummary": f"{scene_id} take 2 is cleaner than take 1 while preserving continuity and room tone.",
                **_grok_main_quality_fields(),
            },
        )
        assert accepted.status_code == 200

    blocked = client.get("/api/grok-handoff/grok-main-first-hook/render-payload")
    blocked_data = blocked.get_json()
    assert blocked.status_code == 409
    assert blocked_data["mainSourceGate"]["status"] == "needs-first-hook-grok-clip"
    assert blocked_data["mainSourceGate"]["firstHookSceneId"] == "scene-01"
    assert blocked_data["mainSourceGate"]["firstHookPlanned"] is True
    assert blocked_data["mainSourceGate"]["firstHookAccepted"] is False
    assert blocked_data["mainSourceGate"]["missingSceneIds"] == ["scene-01"]

    (incoming / "scene-01.grok.mp4").write_bytes(b"grok first hook")
    (incoming / "scene-01-grok-take-2.mp4").write_bytes(b"grok first hook alternate")
    first_hook_accepted = client.post(
        "/api/grok-handoff/grok-main-first-hook/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "selectedFileName": "scene-01-grok-take-2.mp4",
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Selected because the Grok clip carries the first visible action instead of stock filler.",
            "qualityReviewNote": "First-second motion is readable; no text artifacts, watermark, or subject drift.",
            "selectedCandidateSummary": "Take 2 gives a clearer first-hook action than take 1 and avoids stock-looking filler.",
            **_grok_main_quality_fields(),
        },
    )
    assert first_hook_accepted.status_code == 200

    ready = client.get("/api/grok-handoff/grok-main-first-hook/render-payload")
    ready_data = ready.get_json()
    assert ready.status_code == 200
    assert ready_data["allReady"] is True
    assert ready_data["mainSourceGate"]["status"] == "ready"
    assert ready_data["mainSourceGate"]["firstHookAccepted"] is True


def test_grok_main_status_prioritizes_replacing_failed_first_hook_before_later_scenes(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": False,
        "status": "needs-review",
        "width": 416,
        "height": 752,
        "fps": 24,
        "durationSec": 6.0,
        "aspectRatio": 0.553,
        "hasAudio": True,
        "issues": ["vertical height below review floor: 752"],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "grok-first-hook-replace-priority",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {"sceneId": "scene-01", "scene_num": 1, "image_source": "pexels-video", "duration": 4},
                {"sceneId": "scene-02", "scene_num": 2, "image_source": "grok", "grok_prompt": "Second scene action.", "duration": 4},
                {"sceneId": "scene-03", "scene_num": 3, "image_source": "grok", "grok_prompt": "Third scene action.", "duration": 4},
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"low resolution first hook cache")

    status = client.get("/api/grok-handoff/grok-first-hook-replace-priority/status").get_json()
    assert status["readyScenes"] == 0
    assert status["nextMissingSceneId"] == "scene-01"
    assert status["nextMissingReason"] == "quality-replacement-required"
    assert status["mainPathStatus"]["status"] == "needs-replacement-grok-mp4s"
    assert status["mainPathStatus"]["blocker"] == "quality-replacement-grok-clips"
    assert status["mainPathStatus"]["readyScenes"] == 0
    assert status["mainPathStatus"]["readySceneIds"] == []
    assert status["mainPathStatus"]["assetPresentScenes"] == 1
    assert status["mainPathStatus"]["assetPresentSceneIds"] == ["scene-01"]
    assert "readyScenes=0/3" in status["mainPathStatus"]["proofPoints"]
    assert "assetPresentScenes=1/3" in status["mainPathStatus"]["proofPoints"]
    assert status["grokAssetAcquisition"]["primaryBlocker"] == "local-mp4-below-quality-floor"
    assert status["mainPathStatus"]["originalExportPlan"]["priority"] == "replace-existing-candidate"
    assert status["mainPathStatus"]["originalExportPlan"]["modelBlocked"] is False
    assert status["mainPathStatus"]["originalExportPlan"]["currentBlocker"].startswith("scene-01:")
    curation = status["grokAssetAcquisition"]["candidateCurationPlan"]
    assert curation["candidateCount"] == 1
    assert curation["publishableCandidateCount"] == 0
    assert curation["selectedCandidate"]["height"] == 752
    next_action = status["mainPathStatus"]["primaryNextAction"]
    assert "Replace scene-01" in next_action
    assert "vertical height below review floor: 752" in next_action
    assert "Generate scene-02" not in next_action

    production_queue = client.get("/api/grok-handoff/grok-first-hook-replace-priority/production-queue")
    assert production_queue.status_code == 200
    production_queue_html = production_queue.data.decode("utf-8")
    assert routes_grok.GROK_PRODUCTION_QUEUE_VERSION in production_queue_html
    assert "Quality replacement stop" in production_queue_html
    assert "Replace scene-01 before later scenes" in production_queue_html
    assert "scene-01.grok.mp4" in production_queue_html
    assert "416x752 / 24fps" in production_queue_html
    assert "Generate two fresh Grok MP4 takes" in production_queue_html
    assert "existing signed-in Chrome browser-control" in production_queue_html
    assert "vertical height below review floor: 752" in production_queue_html
    assert "Grok source status" in production_queue_html
    assert "Replace scene-01 with two fresh Grok MP4 takes through existing signed-in Chrome browser-control" in production_queue_html
    assert "Copy prompt packet" in production_queue_html


def test_grok_main_source_requires_candidate_curation_evidence(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "durationSec": 4.2,
        "aspectRatio": 0.5625,
        "hasAudio": False,
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "grok-candidate-curation",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "A clear first-hook Grok scene with immediate motion.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"single grok candidate")

    weak_accept = client.post(
        "/api/grok-handoff/grok-candidate-curation/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "The first hook shows the intended subject and motion clearly.",
            "qualityReviewNote": "No watermark, no UI text, stable motion, and safe caption space.",
        },
    )
    assert weak_accept.status_code == 400
    assert "at least two imported Grok MP4 take candidates" in weak_accept.get_json()["error"]

    manifest_path = tmp_path / "storage" / "grok-handoffs" / "grok-candidate-curation" / "handoff.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["reviewDecisions"] = {
        "scene-01": {
            "sceneId": "scene-01",
            "accepted": True,
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Legacy accepted Grok clip before candidate evidence existed.",
            "qualityReviewNote": "Legacy quality note says the clip is technically clean.",
        }
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    legacy_payload = client.get("/api/grok-handoff/grok-candidate-curation/render-payload")
    legacy_data = legacy_payload.get_json()
    assert legacy_payload.status_code == 409
    assert legacy_data["mainSourceGate"]["status"] == "needs-candidate-curation"
    assert legacy_data["mainSourceGate"]["candidateCurationGapSceneIds"] == ["scene-01"]
    assert legacy_data["mainSourceGate"]["candidateCountBySceneId"]["scene-01"] == 1

    (incoming / "scene-01-grok-take-2.mp4").write_bytes(b"second grok candidate")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["reviewDecisions"]["scene-01"].update({
        "selectedCandidateSummary": "Take 2 has a clearer hook than take 1, but this is still a legacy review record.",
        "visualQualityVerdict": "pass",
        "captionLayoutReviewNote": "Subject remains visible above the caption-safe lower third.",
        "continuityNote": "Same subject and palette are visible.",
        "hookNote": "Motion starts inside the first two seconds.",
        "layoutVariantNote": "Use lower-info captions without covering the subject.",
        "thumbnailReviewNote": "First frame is usable without baked text.",
        "audioMixReviewNote": "Use BGM under the native clip without explanatory TTS.",
        "platformComparisonNote": "Closer to Korean Shorts footage than generic stock filler.",
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    legacy_two_take_payload = client.get("/api/grok-handoff/grok-candidate-curation/render-payload")
    legacy_two_take_data = legacy_two_take_payload.get_json()
    assert legacy_two_take_payload.status_code == 409
    assert legacy_two_take_data["mainSourceGate"]["status"] == "needs-shot-lock-review-evidence"
    assert legacy_two_take_data["mainSourceGate"]["reviewEvidenceGapSceneIds"] == ["scene-01"]
    assert "shotLockMatch=true" in legacy_two_take_data["mainSourceGate"]["reviewEvidenceMissingBySceneId"]["scene-01"]
    assert "shotLockEvidenceNote" in legacy_two_take_data["mainSourceGate"]["reviewEvidenceMissingBySceneId"]["scene-01"]

    accepted = client.post(
        "/api/grok-handoff/grok-candidate-curation/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "selectedFileName": "scene-01-grok-take-2.mp4",
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "The first hook shows the intended subject and motion clearly.",
            "qualityReviewNote": "No watermark, no UI text, stable motion, and safe caption space.",
            "selectedCandidateSummary": "Take 2 has a clearer hook and fewer artifacts than take 1, so it is the selected Grok candidate.",
            **_grok_main_quality_fields(),
        },
    )
    assert accepted.status_code == 200
    accepted_data = accepted.get_json()
    assert accepted_data["renderPayload"]["allReady"] is True
    assert accepted_data["renderPayload"]["mainSourceGate"]["status"] == "ready"


def test_grok_main_rejects_visible_video_fallback_as_main_source(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "durationSec": 4.2,
        "aspectRatio": 0.5625,
        "hasAudio": False,
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "grok-visible-fallback-proof-only",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "A Grok hook scene that must come from the original MP4 download.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"visible browser video fallback")
    (incoming / "scene-01-grok-take-2.mp4").write_bytes(b"alternate grok candidate")
    event = client.post(
        "/api/grok-handoff/grok-visible-fallback-proof-only/extension-event",
        json={
            "operatorApproved": True,
            "extensionApproved": True,
            "sceneId": "scene-01",
            "expectedFileName": "scene-01.grok.mp4",
            "eventType": "observed-post-download",
            "status": "saved",
            "sourceKind": "visible-video-fallback",
            "qualityNote": "visible-video-fallback-proof-only",
            "detail": "visible-video-fallback-proof-only: use operator-owned download/import or manual upload for original MP4",
        },
    )
    assert event.status_code == 200

    status = client.get("/api/grok-handoff/grok-visible-fallback-proof-only/status").get_json()
    candidate = status["assets"][0]["candidateAssets"][0]
    assert candidate["sourceProvenance"]["status"] == "visible-video-fallback-proof-only"
    assert candidate["sourceProvenance"]["acceptAsGrokMainSource"] is False
    assert status["assets"][0]["qualityGate"]["status"] == "source-review"

    rejected = client.post(
        "/api/grok-handoff/grok-visible-fallback-proof-only/review-decision",
        json={
            "sceneId": "scene-01",
            "selectedFileName": "scene-01.grok.mp4",
            "accepted": True,
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Selected only if it is a real Grok download, not a browser preview source.",
            "qualityReviewNote": "The clip is technically clean, but provenance still decides whether it can be Grok-main.",
            "selectedCandidateSummary": "Take 1 is more stable than take 2, but it came from the visible video fallback.",
            **_grok_main_quality_fields(),
        },
    )
    assert rejected.status_code == 400
    payload = rejected.get_json()
    assert "browser-native/direct-imported or operator-uploaded Grok MP4 proof" in payload["error"]
    assert payload["sourceProvenance"]["proofOnly"] is True


def test_grok_main_rejects_browser_observed_mp4_without_original_download_provenance(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "durationSec": 4.2,
        "aspectRatio": 0.5625,
        "hasAudio": False,
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "grok-local-unverified-source",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "A Grok scene that must use a browser-native original MP4.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"browser observed local mp4")
    observation = client.post(
        "/api/grok-handoff/grok-local-unverified-source/codex-chrome-observation",
        json={
            "operatorApproved": True,
            "codexChromeApproved": True,
            "sceneId": "scene-01",
            "status": "generated",
            "postUrl": "https://grok.com/imagine/post/cd0",
            "videoUrl": "https://assets.grok.com/users/user/generated/cd0/generated_video.mp4",
            "detail": "Observed through logged-in Chrome, but no browser-native download was imported.",
        },
    )
    assert observation.status_code == 200

    status = client.get("/api/grok-handoff/grok-local-unverified-source/status").get_json()
    provenance = status["assets"][0]["sourceProvenance"]
    assert provenance["status"] == "browser-observed-source-unverified"
    assert provenance["acceptAsGrokMainSource"] is False
    assert "operator-owned manual download/import" in provenance["operatorAction"]
    assert "manual batch upload" in provenance["operatorAction"]
    assert status["assets"][0]["qualityGate"]["status"] == "source-review"

    rejected = client.post(
        "/api/grok-handoff/grok-local-unverified-source/review-decision",
        json={
            "sceneId": "scene-01",
            "selectedFileName": "scene-01.grok.mp4",
            "accepted": True,
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "This file came from a browser observation, not a verified direct import or manual upload.",
            "qualityReviewNote": "The clip probe is clean, but browser-observed provenance is still ambiguous and must block acceptance.",
            "selectedCandidateSummary": "Single browser-observed candidate with no direct import or approved manual-upload provenance.",
            **_grok_main_quality_fields(),
        },
    )
    assert rejected.status_code == 400
    payload = rejected.get_json()
    assert "browser-native/direct-imported or operator-uploaded Grok MP4 proof" in payload["error"]
    assert payload["sourceProvenance"]["status"] == "browser-observed-source-unverified"


def test_grok_main_selected_download_candidate_overrides_lowres_expected_file_and_stale_observation(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)

    def fake_probe(path):
        name = Path(path).name
        if name == "scene-01.grok.mp4":
            return {
                "ok": False,
                "status": "needs-review",
                "width": 416,
                "height": 752,
                "fps": 24,
                "durationSec": 6.04,
                "aspectRatio": 0.5532,
                "hasAudio": True,
                "motionOk": True,
                "motionStatus": "ok",
                "issues": ["vertical height below review floor: 752"],
            }
        return {
            "ok": True,
            "status": "ok",
            "width": 720,
            "height": 1280,
            "fps": 24,
            "durationSec": 6.04,
            "aspectRatio": 0.5625,
            "hasAudio": True,
            "motionOk": True,
            "motionStatus": "ok",
            "issues": [],
        }

    monkeypatch.setattr(routes_grok, "_probe_grok_clip", fake_probe)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "grok-selected-download-candidate",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "A Grok hook scene that must use the operator-downloaded MP4 candidate.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"old low resolution cache recovery mp4")

    observation = client.post(
        "/api/grok-handoff/grok-selected-download-candidate/codex-chrome-observation",
        json={
            "operatorApproved": True,
            "codexChromeApproved": True,
            "sceneId": "scene-01",
            "status": "generated",
            "postUrl": "https://grok.com/imagine/post/selected",
            "videoUrl": "https://assets.grok.com/users/user/generated/selected/generated_video.mp4",
            "detail": "Stale browser observation should not override the later Downloads import metadata.",
        },
    )
    assert observation.status_code == 200

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    downloaded = downloads / "grok-video-selected-720p.mp4"
    downloaded.write_bytes(b"operator downloaded 720p grok mp4")

    imported = client.post(
        "/api/grok-handoff/grok-selected-download-candidate/import-downloads",
        json={
            "downloadDir": str(downloads),
            "operatorApproved": True,
            "allowNewestFallback": True,
            "sinceHandoff": False,
            "overwrite": True,
            "preserveCandidates": True,
            "sceneMappingMode": "scene-grouped-takes",
            "sceneGroupedTakeSize": 1,
        },
    )
    assert imported.status_code == 200
    selected_name = imported.get_json()["assets"][0]["fileName"]
    assert selected_name == "scene-01-grok-video-selected-720p.mp4"

    status = client.get("/api/grok-handoff/grok-selected-download-candidate/status").get_json()
    asset = status["assets"][0]
    assert asset["fileName"] == selected_name
    assert asset["clipProbe"]["height"] == 1280
    assert asset["sourceProvenance"]["status"] == "local-mp4-download-unverified"
    assert asset["sourceProvenance"]["acceptAsGrokMainSource"] is True
    assert asset["qualityGate"]["status"] == "pending-operator-review"
    assert status["qualityGate"]["replacementSceneIds"] == []

    accepted = client.post(
        "/api/grok-handoff/grok-selected-download-candidate/review-decision",
        json={
            "sceneId": "scene-01",
            "selectedFileName": selected_name,
            "accepted": True,
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Selected the operator-downloaded 720p Grok MP4 candidate over the old cache recovery file.",
            "qualityReviewNote": "The selected candidate is vertical 720p+, has immediate motion, no watermark, and safe caption framing.",
            "selectedCandidateSummary": "The downloaded 720p take beats the stale low-resolution exact-name file and is the render source.",
            **_grok_main_quality_fields(),
        },
    )
    assert accepted.status_code == 200
    payload = accepted.get_json()["renderPayload"]
    assert payload["allReady"] is True
    assert payload["sceneAssets"][0]["fileName"] == selected_name
    assert payload["sceneAssets"][0]["clipProbe"]["height"] == 1280
    assert payload["sceneAssets"][0]["sourceProvenance"]["status"] == "local-mp4-download-unverified"
    assert payload["sceneAssets"][0]["qualityGate"]["selectedFileName"] == selected_name


def test_grok_main_review_requires_explicit_visual_layout_audio_platform_evidence(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "durationSec": 4.2,
        "aspectRatio": 0.5625,
        "hasAudio": False,
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "grok-main-detailed-review",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "A clear Grok hero scene with immediate visible action.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"detailed grok candidate")
    (incoming / "scene-01-grok-take-2.mp4").write_bytes(b"detailed grok candidate alternate")

    missing_detail = client.post(
        "/api/grok-handoff/grok-main-detailed-review/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "selectedFileName": "scene-01-grok-take-2.mp4",
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Selected because the Grok clip carries the first visible action.",
            "qualityReviewNote": "No watermark, no UI text, stable motion, and safe caption space.",
            "selectedCandidateSummary": "Take 2 is stronger than take 1, pending the detailed visual layout audio review fields.",
        },
    )

    assert missing_detail.status_code == 400
    missing_payload = missing_detail.get_json()
    assert "visual/layout/audio/platform" in missing_payload["error"]
    assert "visualQualityVerdict=pass" in missing_payload["missingFields"]
    assert "shotLockMatch=true" in missing_payload["missingFields"]
    assert "sceneAssemblyOk=true" in missing_payload["missingFields"]
    assert "sourceProvenanceConfirmed=true" in missing_payload["missingFields"]
    assert "sourceProvenanceNote" in missing_payload["missingFields"]
    assert "captionLayoutReviewNote" in missing_payload["missingFields"]
    assert "shotLockEvidenceNote" in missing_payload["missingFields"]
    assert "sceneAssemblyRoleNote" in missing_payload["missingFields"]
    assert "audioMixReviewNote" in missing_payload["missingFields"]
    assert "platformComparisonNote" in missing_payload["missingFields"]

    accepted = client.post(
        "/api/grok-handoff/grok-main-detailed-review/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "selectedFileName": "scene-01-grok-take-2.mp4",
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Selected because the Grok clip carries the first visible action.",
            "qualityReviewNote": "No watermark, no UI text, stable motion, and safe caption space.",
            "selectedCandidateSummary": "Take 2 has cleaner movement than take 1 and detailed review confirms it beats stock fallback.",
            **_grok_main_quality_fields(),
        },
    )

    assert accepted.status_code == 200
    decision = accepted.get_json()["reviewDecision"]
    assert decision["visualQualityVerdict"] == "pass"
    assert decision["shotLockMatch"] is True
    assert decision["sceneAssemblyOk"] is True
    assert decision["shotLockEvidenceNote"].startswith("The selected take")
    assert decision["sceneAssemblyRoleNote"].startswith("This take works")
    assert decision["sourceProvenanceConfirmed"] is True
    assert decision["sourceProvenanceStatus"] == "local-mp4-source-unverified"
    assert decision["audioMixReviewNote"].startswith("Native audio")
    assert decision["platformComparisonNote"].startswith("Closer to Korean")


def test_grok_main_review_requires_local_mp4_source_provenance_confirmation(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "durationSec": 4.2,
        "aspectRatio": 0.5625,
        "hasAudio": False,
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "grok-main-source-provenance-confirmation",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "A clear Grok hero scene with immediate visible action.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"local grok mp4 candidate")
    (incoming / "scene-01-grok-take-2.mp4").write_bytes(b"local grok mp4 candidate alternate")

    missing_provenance = client.post(
        "/api/grok-handoff/grok-main-source-provenance-confirmation/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "selectedFileName": "scene-01-grok-take-2.mp4",
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Selected because the second Grok take has stronger first-second action.",
            "qualityReviewNote": "No watermark, no UI text, stable motion, and safe caption space.",
            "selectedCandidateSummary": "Take 2 has cleaner movement than take 1 and is the better Grok-main candidate.",
            **_grok_main_quality_fields(sourceProvenanceConfirmed=False, sourceProvenanceNote=""),
        },
    )

    assert missing_provenance.status_code == 400
    payload = missing_provenance.get_json()
    assert "visual/layout/audio/platform" in payload["error"]
    assert payload["sourceProvenance"]["status"] == "local-mp4-source-unverified"
    assert "sourceProvenanceConfirmed=true" in payload["missingFields"]
    assert "sourceProvenanceNote" in payload["missingFields"]

    accepted = client.post(
        "/api/grok-handoff/grok-main-source-provenance-confirmation/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "selectedFileName": "scene-01-grok-take-2.mp4",
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Selected because the second Grok take has stronger first-second action.",
            "qualityReviewNote": "No watermark, no UI text, stable motion, and safe caption space.",
            "selectedCandidateSummary": "Take 2 has cleaner movement than take 1 and is the better Grok-main candidate.",
            **_grok_main_quality_fields(),
        },
    )

    assert accepted.status_code == 200
    decision = accepted.get_json()["reviewDecision"]
    assert decision["sourceProvenanceConfirmed"] is True
    assert decision["sourceProvenanceNote"].startswith("Operator confirms")
    assert decision["sourceProvenanceStatus"] == "local-mp4-source-unverified"


def test_grok_main_review_requires_explicit_selected_candidate_file_for_multi_take(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "durationSec": 4.2,
        "aspectRatio": 0.5625,
        "hasAudio": False,
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "grok-main-explicit-selection",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "A clear Grok hero scene with immediate visible action.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"explicit selection first candidate")
    (incoming / "scene-01-grok-take-2.mp4").write_bytes(b"explicit selection second candidate")

    rejected = client.post(
        "/api/grok-handoff/grok-main-explicit-selection/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Selected because the Grok clip carries the first visible action.",
            "qualityReviewNote": "No watermark, no UI text, stable motion, and safe caption space.",
            "selectedCandidateSummary": "Take 2 has cleaner movement than take 1 and beats the fallback.",
            **_grok_main_quality_fields(),
        },
    )

    assert rejected.status_code == 400
    payload = rejected.get_json()
    assert "selectedFileName" in payload["error"]
    assert payload["candidateCount"] == 2
    assert payload["candidateFileNames"] == ["scene-01.grok.mp4", "scene-01-grok-take-2.mp4"]


def test_grok_main_source_gate_accepts_half_scene_grok_mix(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "durationSec": 4.2,
        "aspectRatio": 0.5625,
        "hasAudio": False,
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "grok-main-source-ready",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {"sceneId": "scene-01", "scene_num": 1, "image_source": "grok", "grok_prompt": "Hero.", "duration": 4},
                {"sceneId": "scene-02", "scene_num": 2, "image_source": "grok", "grok_prompt": "Follow-up.", "duration": 4},
                {"sceneId": "scene-03", "scene_num": 3, "image_source": "pexels-video", "duration": 4},
                {"sceneId": "scene-04", "scene_num": 4, "image_source": "pexels-video", "duration": 4},
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"grok scene one")
    (incoming / "scene-01-grok-take-2.mp4").write_bytes(b"grok scene one alternate")
    (incoming / "scene-02.grok.mp4").write_bytes(b"grok scene two")
    (incoming / "scene-02-grok-take-2.mp4").write_bytes(b"grok scene two alternate")

    for scene_id in ("scene-01", "scene-02"):
        accepted = client.post(
            "/api/grok-handoff/grok-main-source-ready/review-decision",
            json={
                "sceneId": scene_id,
                "accepted": True,
                "selectedFileName": f"{scene_id}-grok-take-2.mp4",
                "firstTwoSecondHook": True,
                "artifactFree": True,
                "continuityOk": True,
                "captionSafe": True,
                "sourceRationale": f"{scene_id} preserves the shot bible.",
                "qualityReviewNote": "Natural motion, no watermark, no UI text.",
                "selectedCandidateSummary": f"{scene_id} take 2 beats take 1 on motion clarity while clearing the shot bible checks.",
                **_grok_main_quality_fields(),
            },
        )
        assert accepted.status_code == 200

    payload = client.get("/api/grok-handoff/grok-main-source-ready/render-payload")
    assert payload.status_code == 200
    data = payload.get_json()
    assert data["allReady"] is True
    assert data["mainSourceGate"]["status"] == "ready"
    assert data["mainSourceGate"]["acceptedSceneIds"] == ["scene-01", "scene-02"]
    assert data["mainSourceGate"]["minAcceptedScenes"] == 2


def test_grok_handoff_quality_gate_blocks_accept_before_import(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "quality-gated-missing",
            "qualityGateRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same character night routine hero.",
                    "duration": 4,
                }
            ],
        },
    )

    accepted = client.post(
        "/api/grok-handoff/quality-gated-missing/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
        },
    )
    review_packet = client.get("/api/grok-handoff/quality-gated-missing/review-packet")

    assert accepted.status_code == 400
    assert "imported MP4 asset" in accepted.get_json()["error"]
    html = review_packet.get_data(as_text=True)
    assert "Quality gate" in html
    assert "Accept is allowed only after the actual MP4 is present" in html
    assert "data-review-accepted=\"true\" disabled" in html


def test_grok_handoff_open_route_uses_worksheet_not_browser_profile(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "worksheet-test",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )
    opened_urls: list[str] = []
    monkeypatch.setattr(routes_grok.webbrowser, "open", lambda url, new=0: opened_urls.append(url) or True)

    response = client.post("/api/grok-handoff/worksheet-test/open-browser", json={})

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["target"] == "worksheet"
    assert data["worksheetUrl"].endswith("/api/grok-handoff/worksheet-test/worksheet")
    assert opened_urls == [data["worksheetUrl"]]
    assert "--remote-debugging-port" not in json.dumps(data)
    assert "profile" not in json.dumps(data).lower()


def test_grok_handoff_open_route_can_force_existing_chrome_without_cdp_profile(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "existing-chrome",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Logged-in Chrome handoff prompt.",
                    "duration": 4,
                }
            ],
        },
    )
    opened_args: list[list[str]] = []

    monkeypatch.setattr(routes_grok, "_find_preferred_browser_executable", lambda preference: "C:\\Chrome\\chrome.exe")
    monkeypatch.setattr(routes_grok.webbrowser, "open", lambda url, new=0: (_ for _ in ()).throw(AssertionError("default browser should not be used")))
    monkeypatch.setattr(routes_grok.subprocess, "Popen", lambda args, **kwargs: opened_args.append(list(args)) or object())

    response = client.post(
        "/api/grok-handoff/existing-chrome/open-browser",
        json={"target": "grok", "browserPreference": "chrome"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["browserPreference"] == "chrome"
    assert data["openedTargets"][0]["openedBrowser"] == "chrome"
    assert data["openedTargets"][0]["browserExecutable"] == "C:\\Chrome\\chrome.exe"
    assert opened_args == [["C:\\Chrome\\chrome.exe", routes_grok.GROK_IMAGINE_URL]]
    assert "--remote-debugging-port" not in json.dumps(data)
    assert "--user-data-dir" not in json.dumps(data)


def test_grok_handoff_open_route_can_force_chrome_prep_generate_autostart(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "chrome-prep-generate",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "First Grok handoff prompt.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "image_source": "grok",
                    "grok_prompt": "Second Grok handoff prompt.",
                    "duration": 4,
                },
            ],
        },
    )
    opened_args: list[list[str]] = []

    monkeypatch.setattr(routes_grok, "_find_preferred_browser_executable", lambda preference: "C:\\Chrome\\chrome.exe")
    monkeypatch.setattr(routes_grok.webbrowser, "open", lambda url, new=0: (_ for _ in ()).throw(AssertionError("default browser should not be used")))
    monkeypatch.setattr(routes_grok.subprocess, "Popen", lambda args, **kwargs: opened_args.append(list(args)) or object())

    response = client.post(
        "/api/grok-handoff/chrome-prep-generate/open-browser",
        json={"target": "grok-prep-generate", "browserPreference": "chrome", "sceneId": "scene-02"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["target"] == "grok-prep-generate"
    opened = data["openedTargets"][0]
    assert opened["target"] == "grok-prep-generate"
    assert opened["openedBrowser"] == "chrome"
    assert opened["browserExecutable"] == "C:\\Chrome\\chrome.exe"
    assert opened["sceneId"] == "scene-02"
    assert opened["requiresCompanionExtension"] is True
    assert opened["autostartAction"] == "prep-generate"
    assert opened_args[0][0] == "C:\\Chrome\\chrome.exe"
    autostart_url = opened_args[0][1]
    assert autostart_url.startswith("https://grok.com/imagine#")
    decoded = urllib.parse.unquote(autostart_url)
    assert "videoStudioAction=prep-generate" in decoded
    assert "videoStudioAutoGenerate=true" in decoded
    assert "sceneId=scene-02" in decoded
    assert "--remote-debugging-port" not in json.dumps(data)
    assert "--user-data-dir" not in json.dumps(data)


def test_grok_handoff_open_route_can_force_companion_setup_in_chrome(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "companion-setup",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Grok companion setup prompt.",
                    "duration": 4,
                },
            ],
        },
    )
    opened_args: list[list[str]] = []

    monkeypatch.setattr(routes_grok, "_find_preferred_browser_executable", lambda preference: "C:\\Chrome\\chrome.exe")
    monkeypatch.setattr(routes_grok.webbrowser, "open", lambda url, new=0: (_ for _ in ()).throw(AssertionError("default browser should not be used")))
    monkeypatch.setattr(routes_grok.subprocess, "Popen", lambda args, **kwargs: opened_args.append(list(args)) or object())

    response = client.post(
        "/api/grok-handoff/companion-setup/open-browser",
        json={"target": "companion-setup", "browserPreference": "chrome", "sceneId": "scene-01"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["browserPreference"] == "chrome"
    assert [item["target"] for item in data["openedTargets"]] == ["companion-guide", "chrome-extensions"]
    assert all(item["openedBrowser"] == "chrome" for item in data["openedTargets"])
    assert opened_args[0][0] == "C:\\Chrome\\chrome.exe"
    assert opened_args[0][1].endswith("/api/grok-handoff/companion-setup/chrome-extension?sceneId=scene-01")
    assert opened_args[1] == ["C:\\Chrome\\chrome.exe", "chrome://extensions"]
    assert data["openedTargets"][0]["requiresCompanionExtension"] is True
    assert data["openedTargets"][1]["requiresManualLoadUnpacked"] is True
    assert data["openedTargets"][1]["extensionDir"].endswith("tools\\chrome-grok-companion")
    assert "--remote-debugging-port" not in json.dumps(data)
    assert "--user-data-dir" not in json.dumps(data)


def test_grok_handoff_open_route_can_open_observed_asset_runway_in_chrome(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "observed-asset-runway",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Observed Grok asset tab prompt.",
                    "duration": 4,
                },
            ],
        },
    )
    client.post(
        "/api/grok-handoff/observed-asset-runway/codex-chrome-observation",
        json={
            "operatorApproved": True,
            "codexChromeApproved": True,
            "sceneId": "scene-01",
            "status": "generated",
            "postUrl": "https://grok.com/imagine/post/cd0",
            "videoUrl": "https://assets.grok.com/users/user/generated/cd0/generated_video.mp4?token=drop",
        },
    )
    opened_args: list[list[str]] = []

    monkeypatch.setattr(routes_grok, "_find_preferred_browser_executable", lambda preference: "C:\\Chrome\\chrome.exe")
    monkeypatch.setattr(routes_grok.webbrowser, "open", lambda url, new=0: (_ for _ in ()).throw(AssertionError("default browser should not be used")))
    monkeypatch.setattr(routes_grok.subprocess, "Popen", lambda args, **kwargs: opened_args.append(list(args)) or object())

    response = client.post(
        "/api/grok-handoff/observed-asset-runway/open-browser",
        json={"target": "observed-asset-runway", "browserPreference": "chrome", "sceneId": "scene-01"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert [item["target"] for item in data["openedTargets"]] == [
        "observed-post",
        "observed-asset-manual-runway",
    ]
    assert len(opened_args) == 2
    assert opened_args[0][0] == "C:\\Chrome\\chrome.exe"
    post_url = opened_args[0][1]
    assert post_url == "https://grok.com/imagine/post/cd0"
    observed_post = data["openedTargets"][0]
    assert observed_post["requiresCompanionExtension"] is False
    assert observed_post["requiresExistingSignedInChrome"] is True
    assert observed_post["browserControlPrimary"] is True
    assert observed_post["autostartAction"] == "none"
    assert observed_post["expectedFileName"] == "scene-01.grok.mp4"
    assert "browser-control" in observed_post["postInstruction"]
    assert "Download/Save/Export" in observed_post["postInstruction"]
    assert opened_args[1][0] == "C:\\Chrome\\chrome.exe"
    asset_url = opened_args[1][1]
    assert asset_url.startswith("http://127.0.0.1:5161/api/grok-handoff/observed-asset-runway/observed-asset-manual-runway?")
    decoded_asset_url = urllib.parse.unquote(asset_url)
    assert "operatorApproved=true" in decoded_asset_url
    assert "sceneId=scene-01" in decoded_asset_url
    assert "https://assets.grok.com" not in "\n".join(arg[1] for arg in opened_args)
    observed_asset = data["openedTargets"][1]
    assert observed_asset["requiresOperatorClick"] is True
    assert observed_asset["requiresCompanionExtension"] is False
    assert observed_asset["browserControlPrimary"] is True
    assert "must not click the observed Grok MP4 link" in observed_asset["manualRunwayInstruction"]
    assert "--remote-debugging-port" not in json.dumps(data)
    assert "--user-data-dir" not in json.dumps(data)


def test_grok_handoff_open_route_can_open_observed_asset_manual_runway(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "observed-asset-manual-runway",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Observed Grok manual asset runway prompt.",
                    "duration": 4,
                },
            ],
        },
    )
    client.post(
        "/api/grok-handoff/observed-asset-manual-runway/codex-chrome-observation",
        json={
            "operatorApproved": True,
            "codexChromeApproved": True,
            "sceneId": "scene-01",
            "status": "generated",
            "postUrl": "https://grok.com/imagine/post/cd0",
            "videoUrl": "https://assets.grok.com/users/user/generated/cd0/generated_video.mp4?token=drop",
        },
    )
    opened_args: list[list[str]] = []

    monkeypatch.setattr(routes_grok, "_find_preferred_browser_executable", lambda preference: "C:\\Chrome\\chrome.exe")
    monkeypatch.setattr(routes_grok.webbrowser, "open", lambda url, new=0: (_ for _ in ()).throw(AssertionError("default browser should not be used")))
    monkeypatch.setattr(routes_grok.subprocess, "Popen", lambda args, **kwargs: opened_args.append(list(args)) or object())

    response = client.post(
        "/api/grok-handoff/observed-asset-manual-runway/open-browser",
        json={"target": "observed-asset-manual-runway", "browserPreference": "chrome", "sceneId": "scene-01"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert [item["target"] for item in data["openedTargets"]] == ["observed-asset-manual-runway"]
    assert len(opened_args) == 1
    opened_url = opened_args[0][1]
    assert opened_url.startswith("http://127.0.0.1:5161/api/grok-handoff/observed-asset-manual-runway/observed-asset-manual-runway?")
    decoded_url = urllib.parse.unquote(opened_url)
    assert "operatorApproved=true" in decoded_url
    assert "sceneId=scene-01" in decoded_url
    target = data["openedTargets"][0]
    assert target["requiresOperatorClick"] is True
    assert target["browserControlPrimary"] is True
    assert target["requiresCompanionExtension"] is False
    assert target["usesPaidApi"] is False
    assert target["storesCredentials"] is False
    assert target["expectedFileName"] == "scene-01.grok.mp4"
    assert "browser-control" in target["manualRunwayInstruction"]
    assert "--remote-debugging-port" not in json.dumps(data)
    assert "--user-data-dir" not in json.dumps(data)


def test_grok_handoff_observed_asset_manual_runway_page_blocks_native_download_prompt(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "observed-asset-manual-page",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Observed Grok manual page prompt.",
                    "duration": 4,
                },
            ],
        },
    )
    client.post(
        "/api/grok-handoff/observed-asset-manual-page/codex-chrome-observation",
        json={
            "operatorApproved": True,
            "codexChromeApproved": True,
            "sceneId": "scene-01",
            "status": "generated",
            "postUrl": "https://grok.com/imagine/post/cd0?token=drop",
            "videoUrl": "https://assets.grok.com/users/user/generated/cd0/generated_video.mp4?token=drop",
        },
    )

    denied = client.get("/api/grok-handoff/observed-asset-manual-page/observed-asset-manual-runway?sceneId=scene-01")
    assert denied.status_code == 403

    response = client.get(
        "/api/grok-handoff/observed-asset-manual-page/observed-asset-manual-runway?operatorApproved=true&sceneId=scene-01"
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Grok observed MP4 manual runway" in html
    assert "scene-01.grok.mp4" in html
    assert "https://assets.grok.com/users/user/generated/cd0/generated_video.mp4" in html
    assert "token=drop" not in html
    assert "download=\"scene-01.grok.mp4\"" not in html
    assert "Direct MP4 asset open blocked" in html
    assert "native Chrome download prompts" in html
    assert "Grok post fallback" in html
    assert "Copy post recovery console" in html
    assert "observed-post-download.js?operatorApproved=true" in html
    assert "sceneId=scene-01" in html
    assert "asset navigation is blocked" in html
    assert "/api/grok-handoff/observed-asset-manual-page/manual-download-watch" not in html
    assert "/api/grok-handoff/observed-asset-manual-page/import-downloads" not in html
    assert '"timeoutSeconds": 7200' not in html
    assert "autoArmSceneWatch" not in html
    assert "manualWatchEndpoint" not in html
    assert "postJson(manualWatchEndpoint" not in html
    assert "Download prompt policy</dt><dd>Blocked for Codex automation" in html
    assert "without using paid API" in html


def test_grok_handoff_chrome_companion_extension_command_and_events(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "Downloads").mkdir()
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "chrome-companion",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Existing signed-in Chrome extension prompt.",
                    "duration": 4,
                }
            ],
        },
    )

    denied = client.get("/api/grok-handoff/chrome-companion/extension-command?sceneId=scene-01")
    assert denied.status_code == 403

    command = client.get(
        "/api/grok-handoff/chrome-companion/extension-command?sceneId=scene-01&operatorApproved=true&allowWeakPrompt=true"
    )
    assert command.status_code == 200
    command_data = command.get_json()
    assert command_data["ok"] is True
    assert command_data["sceneId"] == "scene-01"
    assert command_data["takeNumber"] == 2
    assert command_data["takeLabel"] == "motion-first"
    assert command_data["expectedFileName"] == "scene-01.grok.mp4"
    assert "take=2" in urllib.parse.unquote(command_data["commandUrl"])
    assert command_data["queueCommandUrl"].endswith(
        "/api/grok-handoff/chrome-companion/extension-command?operatorApproved=true"
    )
    assert command_data["autostartUrl"].startswith(routes_grok.GROK_IMAGINE_URL + "#")
    assert "videoStudioGrokCommandUrl=" in command_data["autostartUrl"]
    assert "videoStudioAction=fill-prompt" in command_data["autostartUrl"]
    assert "videoStudioAutoGenerate=true" in command_data["prepGenerateAutostartUrl"]
    assert command_data["bookmarkletUrl"].startswith("javascript:")
    assert "/bookmarklet.js?" in command_data["bookmarkletScriptUrl"]
    assert "autoGenerate=true" in command_data["bookmarkletGenerateScriptUrl"]
    assert command_data["bookmarkletQueueUrl"].startswith("javascript:")
    assert "/bookmarklet-queue.js?" in command_data["bookmarkletQueueScriptUrl"]
    assert command_data["bookmarkletInlineMode"] == "self-contained"
    assert command_data["bookmarkletInlineUrl"].startswith("javascript:")
    assert command_data["bookmarkletGenerateInlineUrl"].startswith("javascript:")
    assert "/bookmarklet.js?" not in urllib.parse.unquote(command_data["bookmarkletGenerateInlineUrl"])
    assert "Video Studio Grok bookmarklet fallback started" in urllib.parse.unquote(command_data["bookmarkletGenerateInlineUrl"])
    assert command_data["prompt"] in command_data["bookmarkletGenerateInlineConsoleSnippet"]
    assert "document.createElement('script')" not in command_data["bookmarkletGenerateInlineConsoleSnippet"]
    assert command_data["bookmarkletQueueInlineUrl"].startswith("javascript:")
    assert "/bookmarklet-queue.js?" not in urllib.parse.unquote(command_data["bookmarkletQueueInlineUrl"])
    assert "Video Studio Grok queue bookmarklet started" in urllib.parse.unquote(command_data["bookmarkletQueueInlineUrl"])
    assert command_data["bookmarkletImportEndpoint"].endswith("/api/grok-handoff/chrome-companion/bookmarklet-import")
    assert command_data["allSceneCommands"][0]["sceneId"] == "scene-01"
    assert command_data["allSceneCommands"][0]["recommendedTakeNumber"] == 2
    assert "take=2" in urllib.parse.unquote(command_data["allSceneCommands"][0]["commandUrl"])
    assert command_data["allSceneCommands"][0]["autostartUrl"].startswith(routes_grok.GROK_IMAGINE_URL + "#")
    assert command_data["guardrails"]["usesPaidApi"] is False
    assert command_data["guardrails"]["usesRemoteDebugging"] is False
    assert command_data["guardrails"]["requiresExistingChromeProfile"] is True
    assert command_data["eventEndpoint"].endswith("/api/grok-handoff/chrome-companion/extension-event")

    rejected_event = client.post(
        "/api/grok-handoff/chrome-companion/extension-event",
        json={"sceneId": "scene-01", "eventType": "prompt-fill"},
    )
    assert rejected_event.status_code == 403

    event = client.post(
        "/api/grok-handoff/chrome-companion/extension-event",
        json={
            "operatorApproved": True,
            "extensionApproved": True,
            "sceneId": "scene-01",
            "eventType": "prompt-fill",
            "status": "filled",
            "detail": "Prompt filled from existing Chrome extension.",
            "currentUrl": "https://grok.com/imagine",
            "sourceKind": "download-control",
            "videoWidth": "1080",
            "videoHeight": "1920",
            "qualityFloorMet": "true",
            "qualityNote": "original-download-source",
        },
    )
    assert event.status_code == 200
    event_data = event.get_json()
    assert event_data["ok"] is True
    assert event_data["latestExtensionEvent"]["status"] == "filled"
    assert event_data["latestExtensionEvent"]["sourceKind"] == "download-control"
    assert event_data["latestExtensionEvent"]["videoHeight"] == "1920"
    assert event_data["latestExtensionEvent"]["qualityFloorMet"] == "true"
    assert event_data["latestExtensionEvent"]["qualityNote"] == "original-download-source"

    status = client.get("/api/grok-handoff/chrome-companion/status").get_json()
    assert "chromeCompanionExtension" not in status
    assert "latestExtensionEvent" not in status
    assert "companionConnection" not in status
    assert status["browserControlPrimaryRail"]["extensionRequiredForGeneration"] is False
    assert status["browserControlPrimaryRail"]["mode"] == "existing-signed-in-chrome-browser-control-primary"

    guide = client.get("/api/grok-handoff/chrome-companion/chrome-extension?sceneId=scene-01")
    assert guide.status_code == 200
    html = guide.get_data(as_text=True)
    assert "Existing Chrome profile" in html
    assert "No CDP" in html
    assert "Queue autostart URL" in html
    assert "Copy Companion folder" in html
    assert "Copy queue command URL" in html
    assert "Copy queue Prep+Generate URL" in html
    assert "Queue command URL - operator default" in html
    assert "Do not edit <code>sceneId</code> or <code>take</code>" in html
    assert "Selected scene debug URLs" in html
    assert "Clipboard helper is ready" in html
    assert 'id="vs-copy-status"' in html
    assert 'document.querySelectorAll("[data-copy-value]")' in html
    assert "navigator.clipboard.writeText" in html
    assert "Copy failed. Select the text manually." in html
    assert "Bookmarklet fallback" in html
    assert "Console fallback" in html
    assert "self-contained fallback" in html
    assert "Inline console fallback" in html
    assert "Fill + Generate" in html
    assert "Queue Fill+Generate+Direct Import" in html
    assert "Copy queue console runner" in html
    assert "No-extension MP4 batch upload" in html
    assert 'id="vs-grok-batch-files"' in html
    assert 'accept="video/mp4,video/*"' in html
    assert "Quality preflight" in html
    assert "vs-grok-batch-preflight" in html
    assert "vs-grok-allow-flagged" in html
    assert "allow proof-only flagged upload" in html
    assert "duration above 12s for a short Grok take" in html
    assert "Upload blocked" in html
    assert "/api/grok-handoff/chrome-companion/upload-mp4-batch" in html
    assert "scene-grouped-takes" in html
    assert "operatorApproved: true" in html
    assert "videoStudioGrokCommandUrl" in html
    assert "/bookmarklet.js?" in html
    assert "/bookmarklet-queue.js?" in html
    assert "tools\\chrome-grok-companion" in html or "tools/chrome-grok-companion" in html
    assert 'window.open("chrome://extensions' not in html
    assert "location.href = \"chrome://extensions" not in html

    denied_script = client.get("/api/grok-handoff/chrome-companion/bookmarklet.js?sceneId=scene-01")
    assert denied_script.status_code == 403

    script = client.get(
        "/api/grok-handoff/chrome-companion/bookmarklet.js?sceneId=scene-01&operatorApproved=true&autoGenerate=true&allowWeakPrompt=true"
    )
    assert script.status_code == 200
    assert script.mimetype == "application/javascript"
    script_text = script.get_data(as_text=True)
    assert "Video Studio Grok bookmarklet fallback started" in script_text
    assert "Existing signed-in Chrome extension prompt" in script_text
    assert "Vertical 9:16 phone MP4" in script_text
    assert "no visible text or watermark" in script_text
    assert "bookmarklet-generate" in script_text
    assert "operatorApproved" in script_text

    denied_queue_script = client.get("/api/grok-handoff/chrome-companion/bookmarklet-queue.js")
    assert denied_queue_script.status_code == 403

    queue_script = client.get(
        "/api/grok-handoff/chrome-companion/bookmarklet-queue.js?operatorApproved=true&maxScenes=3&waitSeconds=30&allowWeakPrompt=true"
    )
    assert queue_script.status_code == 200
    assert queue_script.mimetype == "application/javascript"
    queue_script_text = queue_script.get_data(as_text=True)
    assert "Video Studio Grok queue bookmarklet started" in queue_script_text
    assert "Existing signed-in Chrome extension prompt" in queue_script_text
    assert "Vertical 9:16 phone MP4" in queue_script_text
    assert "no visible text or watermark" in queue_script_text
    assert "bookmarklet-queue-direct-import" in queue_script_text
    assert "maxScenes = 3" in queue_script_text
    assert "command.uploadEndpoint" in queue_script_text
    assert "directImportProof: true" in queue_script_text
    assert 'eventType: "bookmarklet-direct-import"' in queue_script_text
    assert "candidateUrl: href" in queue_script_text
    assert 'detail: `direct bridge import; bytes=${buffer.byteLength}; label=${label || "queue"}`' in queue_script_text
    assert 'directImportCandidate(candidate, "queue")' in queue_script_text
    assert "bookmarklet-blob-direct-fetch" in queue_script_text
    assert "no-browser-download-prompt" in queue_script_text
    assert "clickOrSave(candidate)" not in queue_script_text
    assert "stopped-no-download-fallback" in queue_script_text

    denied_bookmarklet_event = client.get("/api/grok-handoff/chrome-companion/bookmarklet-event")
    assert denied_bookmarklet_event.status_code == 403

    bookmarklet_event = client.get(
        "/api/grok-handoff/chrome-companion/bookmarklet-event"
        "?operatorApproved=true&sceneId=scene-01&eventType=bookmarklet-fill&status=filled"
        "&detail=Prompt%20filled%20from%20fallback&expectedFileName=scene-01.grok.mp4"
    )
    assert bookmarklet_event.status_code == 200
    bookmarklet_event_data = bookmarklet_event.get_json()
    assert bookmarklet_event_data["latestExtensionEvent"]["source"] == "bookmarklet-fallback"
    assert bookmarklet_event_data["latestExtensionEvent"]["status"] == "filled"
    bookmarklet_status = client.get("/api/grok-handoff/chrome-companion/status").get_json()
    assert "companionConnection" not in bookmarklet_status
    assert "latestExtensionEvent" not in bookmarklet_status

    denied_bookmarklet_import = client.get("/api/grok-handoff/chrome-companion/bookmarklet-import")
    assert denied_bookmarklet_import.status_code == 405

    downloads_dir = tmp_path / "Downloads"
    captured_import = {}

    def fake_import_downloads(
        handoff_dir,
        manifest,
        download_dir,
        allow_newest_fallback,
        overwrite,
        since_handoff,
        scene_id_filter=None,
        preserve_candidates=False,
        record_history=True,
    ):
        captured_import.update({
            "handoffDir": str(handoff_dir),
            "projectId": manifest.get("projectId"),
            "downloadDir": str(download_dir),
            "allowNewestFallback": allow_newest_fallback,
            "overwrite": overwrite,
            "sinceHandoff": since_handoff,
            "sceneIdFilter": scene_id_filter,
            "preserveCandidates": preserve_candidates,
            "recordHistory": record_history,
        })
        return {
            "imported": [{"sceneId": scene_id_filter, "expectedFileName": "scene-01.grok.mp4"}],
            "skipped": [],
            "assets": [],
            "readyScenes": 1,
            "totalScenes": 1,
            "allReady": True,
            "missingSceneIds": [],
            "rejectedSceneIds": [],
            "nextMissingSceneId": None,
            "nextMissingExpectedFileName": None,
        }

    monkeypatch.setattr(routes_grok, "_import_downloads", fake_import_downloads)
    monkeypatch.setattr(routes_grok, "_write_review_packet", lambda handoff_dir, manifest: handoff_dir / "review.html")
    denied_post_import = client.post(
        "/api/grok-handoff/chrome-companion/bookmarklet-import",
        json={"downloadDir": str(downloads_dir)},
    )
    assert denied_post_import.status_code == 403

    outside_download_dir = tmp_path / "outside"
    outside_download_dir.mkdir()
    outside_post_import = client.post(
        "/api/grok-handoff/chrome-companion/bookmarklet-import",
        json={"operatorApproved": True, "downloadDir": str(outside_download_dir)},
    )
    assert outside_post_import.status_code == 400
    assert "default Downloads" in outside_post_import.get_json()["error"]

    bookmarklet_import = client.post(
        "/api/grok-handoff/chrome-companion/bookmarklet-import",
        json={"operatorApproved": True, "sceneId": "scene-01", "downloadDir": str(downloads_dir)},
    )
    assert bookmarklet_import.status_code == 200
    bookmarklet_import_data = bookmarklet_import.get_json()
    assert bookmarklet_import_data["ok"] is True
    assert bookmarklet_import_data["allReady"] is True
    assert captured_import["projectId"] == "chrome-companion"
    assert captured_import["sceneIdFilter"] == "scene-01"
    assert captured_import["allowNewestFallback"] is True
    assert captured_import["preserveCandidates"] is True
    assert captured_import["sinceHandoff"] is True

    plan = client.get("/api/grok-handoff/chrome-companion/automation-plan").get_json()
    assert "chromeCompanionExtension" not in plan
    assert plan["browserControlPrimaryRail"]["mode"] == "existing-signed-in-chrome-browser-control-primary"
    assert plan["browserControlPrimaryRail"]["extensionRequiredForGeneration"] is False
    assert plan["automationBoundaries"]["primaryProductionRail"] == "existing signed-in Chrome browser-control plus operator-owned manual download/import"


def test_grok_companion_profile_probe_distinguishes_codex_extension(tmp_path, monkeypatch):
    local_app_data = tmp_path / "LocalAppData"
    chrome_root = local_app_data / "Google" / "Chrome" / "User Data"
    default_profile = chrome_root / "Default"
    default_profile.mkdir(parents=True)
    default_preferences = {
        "profile": {"name": "Default"},
        "extensions": {
            "settings": {
                "hehggadaopoacecdllhhajmbjkdcmajg": {
                    "manifest": {"name": "Codex Extension"},
                    "path": "C:\\Users\\operator\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\Extensions\\hehggadaopoacecdllhhajmbjkdcmajg",
                }
            }
        },
    }
    (default_profile / "Preferences").write_text(json.dumps(default_preferences), encoding="utf-8")
    native_host_dir = local_app_data / "OpenAI" / "extension"
    native_host_dir.mkdir(parents=True)
    native_host_exe = native_host_dir / "extension-host.exe"
    native_host_exe.write_text("stub", encoding="utf-8")
    (native_host_dir / "com.openai.codexextension.json").write_text(
        json.dumps({
            "allowed_origins": ["chrome-extension://hehggadaopoacecdllhhajmbjkdcmajg/"],
            "name": "com.openai.codexextension",
            "path": str(native_host_exe),
            "type": "stdio",
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "profile-probe",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Same presenter raises a red notebook beside a window.",
                    "duration": 4,
                }
            ],
        },
    )

    status = client.get("/api/grok-handoff/profile-probe/status").get_json()
    assert "chromeCompanionExtension" not in status
    assert status["browserControlPrimaryRail"]["requiresExistingSignedInChromeProfile"] is True
    assert status["browserControlPrimaryRail"]["forbidEdgeFallback"] is True
    assert status["browserControlPrimaryRail"]["extensionRequiredForGeneration"] is False

    handoff_dir = tmp_path / "storage" / "grok-handoffs" / "profile-probe"
    (handoff_dir / "automation-request.json").write_text(
        json.dumps({
            "projectId": "profile-probe",
            "sceneId": "scene-01",
            "browserProfileDirectory": "Profile 1",
            "browserProfileMode": "default-chrome-cdp-attach",
        }),
        encoding="utf-8",
    )
    mismatch_status = client.get("/api/grok-handoff/profile-probe/status").get_json()
    assert "chromeCompanionExtension" not in mismatch_status
    assert mismatch_status["browserControlPrimaryRail"]["forbidNewChromeProfile"] is True

    production_queue = client.get("/api/grok-handoff/profile-probe/production-queue").get_data(as_text=True)
    assert "Chrome profile alignment" in production_queue
    assert "Default (Default)" in production_queue
    assert "Codex extension/native host" in production_queue
    assert "Video Studio direct control: not exposed to Video Studio bridge" in production_queue
    assert "Do not open" in production_queue
    assert "Microsoft Edge" in production_queue

    guide = client.get("/api/grok-handoff/profile-probe/chrome-extension?sceneId=scene-01")
    guide_html = guide.get_data(as_text=True)
    assert "codex-extension-only" in guide_html
    assert "Codex Chrome extension does not control Grok for Video Studio" in guide_html
    assert "Codex native host:" in guide_html
    assert "Video Studio does not use it as the Grok production bridge" in guide_html

    companion_profile = chrome_root / "Profile 1"
    companion_profile.mkdir()
    companion_preferences = {
        "profile": {"name": "SuperGrok"},
        "extensions": {
            "settings": {
                "local-video-studio-companion": {
                    "manifest": {"name": "Video Studio Grok Companion"},
                    "path": str(routes_grok._chrome_companion_extension_dir()),
                }
            }
        },
    }
    (companion_profile / "Preferences").write_text(json.dumps(companion_preferences), encoding="utf-8")

    updated = client.get("/api/grok-handoff/profile-probe/status").get_json()
    assert "chromeCompanionExtension" not in updated
    assert updated["browserControlPrimaryRail"]["source"] == "codex-or-claude-chrome-browser-control"


def test_grok_companion_heartbeat_status_marks_extension_connected(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "companion-heartbeat",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Same presenter opens a red notebook beside a window.",
                    "duration": 4,
                }
            ],
        },
    )

    initial = client.get("/api/grok-handoff/companion-heartbeat/status").get_json()
    assert "companionConnection" not in initial
    assert "latestExtensionEvent" not in initial

    event = client.post(
        "/api/grok-handoff/companion-heartbeat/extension-event",
        json={
            "operatorApproved": True,
            "extensionApproved": True,
            "sceneId": "scene-01",
            "eventType": "companion-heartbeat",
            "status": "connected",
            "detail": "Command stored in companion. version=0.1.0",
            "currentUrl": "https://grok.com/imagine",
        },
    )
    assert event.status_code == 200
    event_data = event.get_json()
    assert event_data["latestExtensionEvent"]["eventType"] == "companion-heartbeat"

    status = client.get("/api/grok-handoff/companion-heartbeat/status").get_json()
    assert "latestExtensionEvent" not in status
    assert "companionConnection" not in status
    assert "companionRunReadiness" not in status
    assert status["browserControlPrimaryRail"]["extensionRequiredForGeneration"] is False


def test_grok_companion_run_readiness_preserves_latest_control_failure_after_heartbeat(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "companion-control-failure",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Same presenter opens a red notebook beside a window.",
                    "duration": 4,
                }
            ],
        },
    )

    for payload in [
        {
            "eventType": "companion-heartbeat",
            "status": "connected",
            "detail": "Command stored in companion. version=0.1.0",
        },
        {
            "eventType": "background-autostart-fill",
            "status": "failed",
            "detail": "Could not establish connection. Receiving end does not exist.",
        },
        {
            "eventType": "companion-heartbeat",
            "status": "connected",
            "detail": "Companion keepalive while Grok generation is pending.",
        },
    ]:
        event = client.post(
            "/api/grok-handoff/companion-control-failure/extension-event",
            json={
                "operatorApproved": True,
                "extensionApproved": True,
                "sceneId": "scene-01",
                "currentUrl": "https://grok.com/imagine",
                **payload,
            },
        )
        assert event.status_code == 200

    status = client.get("/api/grok-handoff/companion-control-failure/status").get_json()
    assert "companionConnection" not in status
    assert "companionRunReadiness" not in status
    assert "chromeCompanionExtension" not in status
    assert status["browserControlPrimaryRail"]["extensionRequiredForGeneration"] is False


def test_grok_handoff_companion_summary_surfaces_imagine_redirect_to_chat(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "companion-imagine-redirect",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Vendor lifts a shutter as steam starts moving across stacked cups.",
                    "duration": 4,
                }
            ],
        },
    )

    event = client.post(
        "/api/grok-handoff/companion-imagine-redirect/extension-event",
        json={
            "operatorApproved": True,
            "extensionApproved": True,
            "sceneId": "scene-01",
            "eventType": "background-autostart-fill",
            "status": "failed",
            "detail": "video-mode-control-not-confirmed",
            "currentUrl": "https://grok.com/c/0c72180f-fe46-4a49-a9cd-80d914322c49",
        },
    )
    assert event.status_code == 200
    event_data = event.get_json()
    assert event_data["latestExtensionEvent"]["eventType"] == "background-autostart-fill"

    status = client.get("/api/grok-handoff/companion-imagine-redirect/status").get_json()
    assert "companionLiveEventSummary" not in status
    assert "chromeCompanionExtension" not in status
    assert status["browserControlPrimaryRail"]["forbidEdgeFallback"] is True


def test_grok_companion_imports_exact_completed_chrome_download(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "exact-chrome-download",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Same presenter opens a small red notebook in a Seoul studio.",
                    "duration": 4,
                }
            ],
        },
    ).get_json()
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    exact_file = downloads_dir / "grok-random-filename.mp4"
    unrelated_newer = downloads_dir / "unrelated-newer.mp4"
    exact_file.write_bytes(b"exact grok chrome download")
    unrelated_newer.write_bytes(b"wrong newest download")
    outside_file = tmp_path / "outside.mp4"
    outside_file.write_bytes(b"outside")

    denied = client.post(
        "/api/grok-handoff/exact-chrome-download/import-downloads",
        json={
            "operatorApproved": True,
            "sceneId": "scene-01",
            "downloadDir": str(downloads_dir),
            "downloadFilePath": str(exact_file),
        },
    )
    assert denied.status_code == 403
    assert "extensionApproved=true" in denied.get_json()["error"]

    outside = client.post(
        "/api/grok-handoff/exact-chrome-download/import-downloads",
        json={
            "operatorApproved": True,
            "extensionApproved": True,
            "sceneId": "scene-01",
            "downloadDir": str(downloads_dir),
            "downloadFilePath": str(outside_file),
        },
    )
    assert outside.status_code == 400
    assert "inside downloadDir" in outside.get_json()["error"]

    imported = client.post(
        "/api/grok-handoff/exact-chrome-download/import-downloads",
        json={
            "operatorApproved": True,
            "extensionApproved": True,
            "sceneId": "scene-01",
            "downloadDir": str(downloads_dir),
            "downloadFilePath": str(exact_file),
            "allowNewestFallback": True,
            "overwrite": True,
            "preserveCandidates": True,
        },
    )

    assert imported.status_code == 200
    data = imported.get_json()
    assert data["ok"] is True
    assert data["imported"][0]["importMode"] == "exact-download-file"
    assert data["imported"][0]["originalPath"] == str(exact_file)
    scene_file = Path(created["incomingDir"]) / "scene-01.grok.mp4"
    assert scene_file.read_bytes() == b"exact grok chrome download"
    assert data["assets"][0]["fileName"] == "scene-01.grok.mp4"
    manifest = json.loads((tmp_path / "storage" / "grok-handoffs" / "exact-chrome-download" / "handoff.json").read_text(encoding="utf-8"))
    assert manifest["importHistory"][-1]["importMode"] == "exact-download-file"
    assert manifest["importHistory"][-1]["downloadFilePath"] == str(exact_file)


def test_grok_companion_autoqueue_is_opt_in_and_existing_chrome_only():
    extension_dir = Path(__file__).resolve().parents[1] / "tools" / "chrome-grok-companion"
    manifest = json.loads((extension_dir / "manifest.json").read_text(encoding="utf-8"))
    background = (extension_dir / "background.js").read_text(encoding="utf-8")
    popup = (extension_dir / "popup.html").read_text(encoding="utf-8")
    popup_js = (extension_dir / "popup.js").read_text(encoding="utf-8")
    readme = (extension_dir / "README.md").read_text(encoding="utf-8")

    assert "tabs" in manifest["permissions"]
    assert "downloads" in manifest["permissions"]
    assert "alarms" in manifest["permissions"]
    assert "scripting" in manifest["permissions"]
    assert "videoStudioGrokAutoQueueEnabled" in background
    assert "videoStudioGrokCompanionKeepalive" in background
    assert "KEEPALIVE_PERIOD_MINUTES" in background
    assert "chrome.alarms.create" in background
    assert "chrome.alarms.onAlarm" in background
    assert "postStoredHeartbeat" in background
    assert "prepGenerateNextScene" in background
    assert "set-auto-queue" in background
    assert "get-auto-queue" in background
    assert "companion-heartbeat" in background
    assert "postHeartbeat" in background
    assert "chrome.scripting.executeScript" in background
    assert "sendToGrokTabWithInjection" in background
    assert "EXTENSION_BUILD_TAG" in background
    assert "build=${EXTENSION_BUILD_TAG}" in background
    assert "content-ready" in background
    assert "isImagineTabUrl" in background
    assert "tabs.find((item) => isImagineTabUrl(item.url))" in background
    assert "imagine-surface-required-background-autostart" in background
    assert "imagine-surface-required-background-autoqueue" in background
    assert "Grok tab content script loaded with stored command." in background
    assert "extensionApproved: true" in background
    assert "downloadFilePath: filename" in background
    content_js = (extension_dir / "content.js").read_text(encoding="utf-8")
    assert "content-ready" in content_js
    assert "EXTENSION_BUILD_TAG" in content_js
    assert "build=${EXTENSION_BUILD_TAG}" in content_js
    assert "Auto-prep next scene after MP4 import" in popup
    assert "set-auto-queue" in popup_js
    assert "isImagineTabUrl" in popup_js
    assert "chrome.scripting.executeScript" in popup_js
    assert "sendMessageWithInjection" in popup_js
    assert "requireImagine: true" in popup_js
    assert "tabs.find((item) => isImagineTabUrl(item.url))" in popup_js
    assert "Auto-queue is opt-in" in readme
    assert "keepalive about once per" in readme
    assert "does not inspect Grok content" in readme
    assert "extension installed but idle" in readme
    assert "The companion never starts a Chrome browser download" in readme
    assert "No paid xAI/Grok API integration" in readme


def test_ai_web_companion_live_proof_harness_is_provider_gated():
    extension_dir = Path(__file__).resolve().parents[1] / "tools" / "chrome-grok-companion"
    background = (extension_dir / "background.js").read_text(encoding="utf-8")
    content = (extension_dir / "content.js").read_text(encoding="utf-8")
    gemini_content = (extension_dir / "content_gemini.js").read_text(encoding="utf-8")
    popup_js = (extension_dir / "popup.js").read_text(encoding="utf-8")
    runner = (extension_dir / "live_proof_runner.py").read_text(encoding="utf-8")

    assert "PROVIDER_CAPABILITIES" in background
    assert '"gemini-web-image"' in background
    assert "canClickGenerate: false" in background
    assert "assertProviderAction(command, request.action)" in background
    assert "PROVIDER_CAPABILITIES" in content
    assert "grok-prompt-target-found" in content
    assert "grok-prompt-target-missing" in content
    assert "capabilities=probe,fill-prompt,generate,direct-import" in content
    assert "PROVIDER_CAPABILITIES" in gemini_content
    assert "function isGeminiHost" in gemini_content
    assert "gemini\\.google-[a-z0-9-]+\\.com" in gemini_content
    assert "load-command-url" in content
    assert "bridge-post-event" in content
    assert "fetch(request.commandUrl)" not in content
    assert 'searchParams.get("operatorApproved") !== "true"' in content
    assert 'includes("operatorApproved=true")' not in content
    assert "bridge-post-event" in gemini_content
    assert "load-command-url" in gemini_content
    assert "fetch(request.commandUrl)" not in gemini_content
    assert "function postBridgeEvent" in background
    assert "load-command-url sender not allowed" in background
    assert "bridge-post-event sender not allowed" in background
    assert "gemini-content-ready" in gemini_content
    assert "gemini-command-loaded" in gemini_content
    assert "gemini-command-load-failed" in gemini_content
    assert "gemini-prompt-target-found" in gemini_content
    assert "gemini-prompt-target-missing" in gemini_content
    assert "Gemini companion supports fill-prompt/probe only" in gemini_content
    assert "Popup controls are Grok-only for now" in popup_js
    assert "Gemini Generate/import remains operator-owned" in popup_js
    assert "canUsePopupControls: false" in popup_js
    assert 'chrome.runtime.sendMessage({ type: "store-command", command, commandUrl: url })' in popup_js
    assert "Prep + Generate will not auto-open /imagine" in popup_js
    assert "Grok left Imagine after loading" in popup_js
    assert "pathname.startsWith(\"/imagine\")" in popup_js
    assert "!pathname.startsWith(\"/imagine/post\")" in popup_js
    assert "fallbackTab" not in background
    assert "currentUrl: tab.url || url" in background
    assert "function isGeminiTabHost" in background
    assert "function isGeminiTabHost" in popup_js
    assert "chrome.downloads.download" not in runner
    assert "--load-extension" in runner
    assert "--extension-dir" in runner
    assert "DisableLoadExtensionCommandLineSwitch" in runner
    assert "extension_load_status" in runner
    assert "extensionLoadStatus" in runner
    assert "extensionTargetCount" in runner
    assert "signed-in live proof must use the operator's existing Chrome profile" in runner
    assert "--user-data-dir" in runner
    assert "classify_gemini_events" in runner
    assert "classify_grok_events" in runner
    assert "browser-control proof" in runner
    assert "GEMINI_BUILD_TAG" in runner
    assert "GROK_BUILD_TAG" in runner


def test_live_proof_runner_classifies_gemini_and_grok_evidence(tmp_path):
    runner = _load_live_proof_runner()
    gemini_log = tmp_path / "gemini-events.jsonl"
    grok_log = tmp_path / "grok-events.jsonl"

    gemini_log.write_text(
        json.dumps({
            "eventType": "gemini-content-ready",
            "status": "hash-detected",
            "build": runner.GEMINI_BUILD_TAG,
        }) + "\n"
        + json.dumps({
            "eventType": "gemini-prompt-fill",
            "status": "filled",
            "build": runner.GEMINI_BUILD_TAG,
            "proofMode": "browser-control",
            "source": "codex-chrome-browser-control",
            "detail": "filledLength=120; generate remains operator-owned",
        }) + "\n",
        encoding="utf-8",
    )
    gemini_result = runner.classify_events("gemini-web-image", gemini_log)
    assert gemini_result.status == "pass"
    assert gemini_result.marker_seen is True
    assert gemini_result.last_event["eventType"] == "gemini-prompt-fill"
    assert "browser-control proof" in gemini_result.detail

    grok_log.write_text(
        json.dumps({
            "eventType": "content-script-ready",
            "status": "ready",
            "detail": f"version=0.1.0 build={runner.GROK_BUILD_TAG}",
            "currentUrl": "https://grok.com/imagine",
        }) + "\n"
        + json.dumps({
            "eventType": "background-autostart-fill",
            "status": "failed",
            "detail": "video-mode-control-not-confirmed",
            "currentUrl": "https://grok.com/imagine/templates/example",
        }) + "\n",
        encoding="utf-8",
    )
    grok_result = runner.classify_events("grok-web-video", grok_log)
    assert grok_result.status == "pass"
    assert grok_result.marker_seen is True

    grok_log.write_text(
        json.dumps({
            "eventType": "background-autostart-fill",
            "status": "filled",
            "detail": f"version=0.1.0 build={runner.GROK_BUILD_TAG}",
            "currentUrl": "https://grok.com/c/unsafe-chat-thread",
        }) + "\n",
        encoding="utf-8",
    )
    unsafe_result = runner.classify_events("grok-web-video", grok_log)
    assert unsafe_result.status == "fail"
    assert "/c/" in unsafe_result.last_event["currentUrl"]

    missing_result = runner.classify_events("gemini-web-image", tmp_path / "missing.jsonl")
    assert missing_result.status == "blocked"
    assert missing_result.marker_seen is False


def test_grok_companion_background_downloads_direct_asset_autostart():
    extension_dir = Path(__file__).resolve().parents[1] / "tools" / "chrome-grok-companion"
    background = (extension_dir / "background.js").read_text(encoding="utf-8")
    readme = (extension_dir / "README.md").read_text(encoding="utf-8")

    assert "downloadAssetFromCurrentTab" in background
    assert "mp4AssetCandidateFromUrl" in background
    assert "request.action === \"download-asset\"" in background
    assert "chrome.downloads.download" not in background
    assert "background-autostart-download" in background
    assert "native browser download fallback disabled" in background
    assert "download-asset action requires the current tab URL to be a direct .mp4 asset" in background
    normalized_readme = " ".join(readme.split())
    assert "direct media-document tabs do not depend on content-script injection" in normalized_readme
    assert "does not click a temporary `<a download>` link" in readme
    assert "Chrome's save prompt is not opened by surprise" in normalized_readme


def test_grok_companion_content_download_asset_autostart_does_not_click_anchor():
    extension_dir = Path(__file__).resolve().parents[1] / "tools" / "chrome-grok-companion"
    content = (extension_dir / "content.js").read_text(encoding="utf-8")

    download_asset_block = content.split('if (request.action === "download-asset") {', 1)[1].split(
        'if (isVisibleVideoDownloadAction(request.action))',
        1,
    )[0]
    assert "runVisibleVideoDownload(command)" in download_asset_block
    assert "download-asset direct import requires uploadEndpoint" in download_asset_block
    assert "native browser download fallback disabled" in download_asset_block
    assert "clickDownloadAnchor" not in download_asset_block
    assert "downloadClicked" not in download_asset_block


def test_grok_companion_blob_video_direct_import_avoids_save_prompt_when_upload_endpoint_exists():
    extension_dir = Path(__file__).resolve().parents[1] / "tools" / "chrome-grok-companion"
    content = (extension_dir / "content.js").read_text(encoding="utf-8")
    background = (extension_dir / "background.js").read_text(encoding="utf-8")
    popup_js = (extension_dir / "popup.js").read_text(encoding="utf-8")
    readme = (extension_dir / "README.md").read_text(encoding="utf-8")

    direct_import_guard = content.split("if (command?.uploadEndpoint)", 1)[1].split(
        "return {\n      ok: videos.length > 0,",
        1,
    )[0]
    assert "importBlobCandidate(command, blobVideo, location.href)" in direct_import_guard
    assert "clickDownloadAnchor" not in direct_import_guard
    assert "directImportProof: true" in content
    assert 'eventType: "companion-blob-direct-import"' in content
    assert "currentUrl," in content
    assert "candidateUrl: candidate.url" in content
    assert "visible-video-blob-direct-fetch" in content
    assert "companion-blob-direct-fetch; no-browser-download-prompt" in content
    assert 'type: "direct-import-complete"' in content
    assert 'message?.type === "direct-import-complete"' in background
    assert "advanceToNextScene(command, imported)" in background
    assert "result?.directImport" in popup_js
    assert "direct-imported" in popup_js
    assert "visible high-resolution `blob:` video" in readme
    assert "avoid Chrome's \"ask where to save" in " ".join(readme.split())


def test_grok_companion_blob_video_download_assist_disabled_without_upload_endpoint():
    extension_dir = Path(__file__).resolve().parents[1] / "tools" / "chrome-grok-companion"
    content = (extension_dir / "content.js").read_text(encoding="utf-8")
    readme = (extension_dir / "README.md").read_text(encoding="utf-8")

    assert "clickDownloadAnchor" not in content
    assert "button.element.click()" in content
    assert "downloadKind: \"blob-anchor\"" not in content
    assert "uploadEndpoint-required-no-browser-download-fallback" in content
    assert "command.expectedFileName" in content
    assert "clickDownload(message.command || {})" in content
    assert "blob:" in readme
    assert "Blob-video download assist is disabled" in readme
    assert "manual batch upload" in readme


def test_grok_companion_primary_import_avoids_browser_download_prompt():
    extension_dir = Path(__file__).resolve().parents[1] / "tools" / "chrome-grok-companion"
    content = (extension_dir / "content.js").read_text(encoding="utf-8")
    popup = (extension_dir / "popup.html").read_text(encoding="utf-8")
    popup_js = (extension_dir / "popup.js").read_text(encoding="utf-8")
    readme = (extension_dir / "README.md").read_text(encoding="utf-8")

    direct_import_guard = content.split("if (command?.uploadEndpoint)", 1)[1].split(
        "return {\n      ok: videos.length > 0,",
        1,
    )[0]
    assert '>Import MP4<' in popup
    assert "importBlobCandidate(command, blobVideo, location.href)" in direct_import_guard
    assert "directImportOnly: true" in direct_import_guard
    assert "direct-import-url-not-found" in direct_import_guard
    assert "button.element.click()" not in direct_import_guard
    assert "clickDownloadAnchor" not in direct_import_guard
    assert "manual-fallback-required" in popup_js
    assert "do not auto-click browser download" in popup_js
    assert "does not automatically click Grok's page-level" in readme
    assert "Chrome's save prompt is not opened by surprise" in " ".join(readme.split())


def test_grok_companion_visible_mp4_direct_import_uses_upload_endpoint():
    extension_dir = Path(__file__).resolve().parents[1] / "tools" / "chrome-grok-companion"
    content = (extension_dir / "content.js").read_text(encoding="utf-8")
    popup_js = (extension_dir / "popup.js").read_text(encoding="utf-8")
    readme = (extension_dir / "README.md").read_text(encoding="utf-8")

    direct_import_guard = content.split("if (command?.uploadEndpoint)", 1)[1].split(
        "return {\n      ok: videos.length > 0,",
        1,
    )[0]
    assert "directImportableMp4VideoCandidate" in content
    assert "const mp4Video = videos.map(directImportableMp4VideoCandidate).find(Boolean);" in direct_import_guard
    assert "videoCandidates: [mp4Video]" in direct_import_guard
    assert "directImportCandidate: true" in direct_import_guard
    assert direct_import_guard.index("const mp4Video =") < direct_import_guard.index("directImportOnly: true")
    assert 'sourceKind: "companion-direct-fetch"' in content
    assert '"original-download-source"' in content
    assert '"no-browser-download-prompt"' in content
    assert 'type: "download-candidate"' in popup_js
    assert 'result.directImport ? "direct-imported"' in popup_js
    assert "downloadStarted" not in popup_js
    assert "downloadId" not in popup_js
    assert "background download started" not in content
    assert "visible video's" in readme
    assert "`currentSrc`" in readme


def test_grok_dashboard_copy_prioritizes_import_mp4_direct_import():
    scene_panel = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "ui"
        / "src"
        / "components"
        / "SceneDetailPanel.tsx"
    ).read_text(encoding="utf-8")

    assert "기본 경로는 기존 signed-in Chrome/Grok 탭에서 browser-control로 생성 proof를 확보" in scene_panel
    assert "Chrome/Grok Download/Save/Export 자동 클릭과 native prompt 자동화는 차단" in scene_panel
    assert "Chrome 확장 안내" not in scene_panel
    assert "로컬 MP4 fallback" in scene_panel
    assert "감시 차단" in scene_panel
    assert "nativeGrokDownloadFallbackBlocked" in scene_panel
    assert "explicit manual upload" in scene_panel
    assert "visible-video/currentSrc fallback is proof-only" in scene_panel
    assert "writeGrokFallbackClipboard" in scene_panel
    assert "document.execCommand(\"copy\")" in scene_panel
    assert "handleCopyObservedPostRecoveryConsoleAndOpen" in scene_panel
    assert "Observed Grok post MP4 recovery console + post" in scene_panel
    assert "Console+post 열기" in scene_panel
    assert "Chrome Download 승인창을 누르지 않고" in scene_panel


def test_grok_companion_original_download_priority_metadata():
    extension_dir = Path(__file__).resolve().parents[1] / "tools" / "chrome-grok-companion"
    content = (extension_dir / "content.js").read_text(encoding="utf-8")
    background = (extension_dir / "background.js").read_text(encoding="utf-8")
    popup_js = (extension_dir / "popup.js").read_text(encoding="utf-8")
    route_source = Path(routes_grok.__file__).read_text(encoding="utf-8")

    assert 'sourceKind: "direct-mp4-asset-tab"' in content
    assert 'sourceKind: anchor.hasAttribute("download") ? "download-anchor" : "direct-video-anchor"' in content
    assert 'sourceKind: "download-control"' not in content
    assert 'sourceKind: "visible-video-fallback"' in content
    assert 'sourceKind = "visible-video-blob-direct-fetch"' in content
    assert "video?.videoHeight" in content
    assert "videoWidth >= 720 && videoHeight >= 1280" in content
    assert "visible-video-fallback-proof-only" in content
    assert "visible-video-fallback-below-quality-floor" in content
    assert "use operator-owned download/import or manual upload for original MP4" in content
    assert "sourceKind: message.sourceKind" in background
    assert "qualityFloorMet: event.qualityFloorMet" in background
    assert "qualityNote: event.qualityNote" in background
    assert "directImportProof: true" in background
    assert "candidateUrl: cleanCandidateUrl" in background
    assert "sourceKind," in background
    assert "no-browser-download-prompt" in background
    assert "lowQualityVisibleFallback" in popup_js
    assert "visible-video-fallback-proof-only" in popup_js
    assert 'data.get("directImportProof") is True' in route_source
    assert 'source_kind = _short_text(data.get("sourceKind") or data.get("directImportSourceKind"), limit=80)' in route_source
    assert '"qualityNote": quality_note' in route_source


def test_grok_companion_prepare_preserves_chrome_user_data_path_with_spaces():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "grok-companion-prepare.ps1"
    script = script_path.read_text(encoding="utf-8")
    start_cdp_section = script.split("function Start-CdpChromeProfile", 1)[1].split("function Write-HandoffText", 1)[0]

    assert "[System.Diagnostics.ProcessStartInfo]::new()" in script
    assert ".ArgumentList.Add($argument)" in script
    assert "ConvertTo-ProcessArgumentString" in script
    assert "Quote-ProcessArgument" in script
    assert "Get-UserDataDirFromCommandLine" in script
    assert "--user-data-dir=$userDataDir" in start_cdp_section
    assert "Start-Process -FilePath" not in start_cdp_section
    assert "instead of '$userDataDir'" in start_cdp_section
    assert "Chrome 136+ default-profile remote-debugging restrictions" in start_cdp_section
    assert "Fallback route A - self-contained bookmarklet" in script
    assert "$command.bookmarkletGenerateInlineUrl" in script
    assert "Fallback route B - queue bookmarklet" in script
    assert "$command.bookmarkletQueueInlineUrl" in script
    assert "$observedPostPlan = $status.observedPostImportPlan" in script
    assert "Fallback route C - observed-post direct import" in script
    assert "$observedPostPlan.observedPostDownloadConsoleSnippet" in script
    assert "[switch]$OpenObservedPost" in script
    assert "[switch]$CopyObservedPostConsole" in script
    assert "[switch]$OpenProofMonitor" in script
    assert "$proofMonitorUrl = \"$base/api/grok-handoff/$ProjectId/direct-import-proof?sceneId=$SceneId\"" in script
    assert "Copied observed-post direct-import console snippet to clipboard." in script
    assert "Opened observed Grok post in Chrome" in script
    assert "Opened the direct import proof monitor in Chrome." in script
    assert "local uploadEndpoint without Chrome Download approval dialog" in script
    assert "Generate at least two takes for the scene" in script
    assert "recommended Chrome profile" in script
    assert "saved CDP replay profile" in script


def test_grok_companion_content_supports_hash_autostart():
    extension_dir = Path(__file__).resolve().parents[1] / "tools" / "chrome-grok-companion"
    content = (extension_dir / "content.js").read_text(encoding="utf-8")

    assert "autostartRequestFromHash" in content
    assert "videoStudioGrokCommandUrl" in content
    assert "videoStudioAutoGenerate" in content
    assert "reportAutostartRequest" in content
    assert "operatorApproved: true" in content
    assert "extensionApproved: true" in content
    assert "content-script-ready" in content
    assert "content-script-command-loaded" in content
    assert "__VIDEO_STUDIO_GROK_COMPANION_LOADED__" in content
    assert "videoStudioGrokCompanion" in content
    assert "autostart-fill" in content
    assert "autostart-generate" in content
    assert "download-asset" in content
    assert "autostart-download" in content
    assert "direct-mp4-asset-tab" in content
    assert "operatorApproved=true is required" in content
    assert "imagineSurfaceStatus" in content
    assert "imagine-surface-required-general-chat-thread" in content
    assert "imagine-composer-required-not-post" in content
    assert "chatComposerTextPattern" in content
    assert "imagine-prompt-input-not-found-or-chat-composer" in content
    assert "requireWordMatch" in content
    assert "video-mode-control-not-confirmed" in content
    generate_words_block = content.split("async function clickGenerate()", 1)[1].split(
        "const button = buttonCandidates",
        1,
    )[0]
    assert '"submit"' not in generate_words_block
    assert '"send"' not in generate_words_block
    assert '"제출"' not in generate_words_block
    generate_button_options = content.split("const button = buttonCandidates", 1)[1].split("})[0]", 1)[0]
    assert "allowIconButtons: false" in generate_button_options
    assert "requireWordMatch: true" in generate_button_options
    assert 'pathname.startsWith("/c/")' in content


def test_grok_handoff_chrome_companion_queue_advances_to_next_missing_scene(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "chrome-queue",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "First Grok scene prompt.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "image_source": "grok",
                    "grok_prompt": "Second Grok scene prompt.",
                    "duration": 4,
                },
            ],
        },
    ).get_json()

    queue_command = client.get("/api/grok-handoff/chrome-queue/extension-command?operatorApproved=true&allowWeakPrompt=true")
    assert queue_command.status_code == 200
    queue_data = queue_command.get_json()
    assert queue_data["sceneId"] == "scene-01"
    assert queue_data["takeNumber"] == 2
    assert queue_data["takeLabel"] == "motion-first"
    assert queue_data["nextMissingSceneId"] == "scene-01"
    assert queue_data["nextRecommendedTakeNumber"] == 2
    assert [item["sceneId"] for item in queue_data["allSceneCommands"]] == ["scene-01", "scene-02"]
    assert all(item["recommendedTakeNumber"] == 2 for item in queue_data["allSceneCommands"])

    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "scene-01.grok.mp4").write_bytes(b"scene one")
    imported = client.post(
        "/api/grok-handoff/chrome-queue/import-downloads",
        json={
            "operatorApproved": True,
            "sceneId": "scene-01",
            "downloadDir": str(downloads),
            "sinceHandoff": False,
            "overwrite": True,
        },
    )

    assert imported.status_code == 200
    import_data = imported.get_json()
    assert import_data["readyScenes"] == 1
    assert import_data["nextMissingSceneId"] == "scene-02"
    assert "sceneId=scene-02" in import_data["nextCommandUrl"]
    assert "take=2" in import_data["nextCommandUrl"]
    assert import_data["nextRecommendedTakeNumber"] == 2

    next_command = client.get(
        import_data["queueCommandUrl"].replace("http://127.0.0.1:5161", "") + "&allowWeakPrompt=true"
    )
    assert next_command.status_code == 200
    next_data = next_command.get_json()
    assert next_data["sceneId"] == "scene-02"
    assert next_data["takeNumber"] == 2
    assert next_data["takeLabel"] == "motion-first"
    assert next_data["expectedFileName"] == "scene-02.grok.mp4"
    assert "Second Grok scene prompt" in next_data["prompt"]

    status = client.get("/api/grok-handoff/chrome-queue/status").get_json()
    assert "chromeCompanionExtension" not in status
    assert status["missingSceneIds"] == ["scene-02"]


def test_grok_handoff_rejected_scene_command_uses_review_retry_prompt(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "retry-prompt",
            "prompt": "One coherent night routine reel with the same desk and lamp.",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Slow push-in on the same desk lamp, phone, and notebook.",
                    "duration": 4,
                },
            ],
        },
    )

    first_command = client.get("/api/grok-handoff/retry-prompt/extension-command?operatorApproved=true&allowWeakPrompt=true")
    assert first_command.status_code == 200
    first_data = first_command.get_json()
    assert first_data["isRetry"] is False
    assert first_data["attemptNumber"] == 1
    assert first_data["takeNumber"] == 2
    assert first_data["takeLabel"] == "motion-first"
    assert first_data["prompt"].startswith("Slow push-in on the same desk lamp")
    assert first_data["basePrompt"] != first_data["prompt"]
    assert "Motion-first take" in first_data["prompt"]

    rejected = client.post(
        "/api/grok-handoff/retry-prompt/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": False,
            "firstTwoSecondHook": False,
            "artifactFree": False,
            "continuityOk": False,
            "captionSafe": False,
            "operatorNote": "Previous output drifted to a random cafe and the lamp morphed.",
        },
    )
    assert rejected.status_code == 200
    decision = rejected.get_json()["reviewDecision"]
    assert decision["retryAttempt"] == 2
    assert len(decision["nextRetryPrompt"]) <= 520
    assert "Fresh retry: first second" in decision["nextRetryPrompt"]
    assert "Vertical 9:16 phone MP4" in decision["nextRetryPrompt"]
    assert "Rejected because:" not in decision["nextRetryPrompt"]
    assert "random cafe" not in decision["nextRetryPrompt"]
    assert "caption-safe" not in decision["nextRetryPrompt"]

    retry_command = client.get("/api/grok-handoff/retry-prompt/extension-command?operatorApproved=true&allowWeakPrompt=true")
    assert retry_command.status_code == 200
    retry_data = retry_command.get_json()
    assert retry_data["sceneId"] == "scene-01"
    assert retry_data["isRetry"] is True
    assert retry_data["attemptNumber"] == 2
    assert retry_data["prompt"] == retry_data["retryPrompt"]
    assert retry_data["basePrompt"] != retry_data["prompt"]
    assert "Rejected because:" not in retry_data["prompt"]
    assert "random cafe" not in retry_data["prompt"]
    assert "uncluttered lower-right background" in retry_data["prompt"]

    review_packet = client.get("/api/grok-handoff/retry-prompt/review-packet")
    assert review_packet.status_code == 200
    html = review_packet.get_data(as_text=True)
    assert "Next retry prompt for Grok" in html
    assert "Fresh retry: first second" in html


def test_grok_handoff_render_payload_requires_complete_mp4s(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "render-missing",
            "prompt": "Grok cafe reel",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                }
            ],
        },
    )

    response = client.get("/api/grok-handoff/render-missing/render-payload")

    assert response.status_code == 409
    data = response.get_json()
    assert data["ok"] is False
    assert data["missingSceneIds"] == ["scene-01"]
    assert data["sceneAssets"] == []


def test_grok_handoff_preview_payload_renders_ready_subset_without_final_gate(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "render-preview-subset",
            "prompt": "Grok cafe reel",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                    "caption_preset": "top-hook",
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Same cup, slow pour continuation.",
                    "duration": 4,
                    "caption_preset": "lower-info",
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / "scene-01.grok.mp4").write_bytes(b"first grok preview mp4")

    full_response = client.get("/api/grok-handoff/render-preview-subset/render-payload")
    assert full_response.status_code == 409
    assert full_response.get_json()["missingSceneIds"] == ["scene-02"]

    preview_response = client.get("/api/grok-handoff/render-preview-subset/render-preview-payload")

    assert preview_response.status_code == 200
    data = preview_response.get_json()
    assert data["ok"] is True
    assert data["previewMode"] is True
    assert data["previewReady"] is True
    assert data["allReady"] is False
    assert data["renderPurpose"] == "grok-import-preview"
    assert data["readyScenes"] == 1
    assert data["totalScenes"] == 2
    assert data["previewSceneIds"] == ["scene-01"]
    assert data["missingSceneIds"] == ["scene-02"]
    assert data["providerOverrides"] == {"scene-01": "grok"}
    assert [scene["sceneId"] for scene in data["draftScenes"]] == ["scene-01"]
    assert data["draftScenes"][0]["image_source"] == "grok"
    assert data["draftScenes"][0]["upload_kind"] == "video"
    assert [asset["sceneId"] for asset in data["sceneAssets"]] == ["scene-01"]
    assert data["sceneAssets"][0]["sourcePath"].endswith(
        "storage/grok-handoffs/render-preview-subset/incoming/scene-01.grok.mp4"
    )


def test_grok_handoff_automation_plan_exposes_approval_gated_import(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "automation-plan",
            "grokMainSourceRequired": True,
            "minGrokMainScenes": 1,
            "sourceMixTotalScenes": 1,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                }
            ],
        },
    )

    response = client.get("/api/grok-handoff/automation-plan/automation-plan")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["approvalRequired"] is True
    assert data["automationBoundaries"]["usesPaidApi"] is False
    assert data["automationBoundaries"]["storesCredentials"] is False
    assert data["reviewPacketUrl"].endswith("/api/grok-handoff/automation-plan/review-packet")
    assert data["defaultDownloadDir"]
    assert isinstance(data["defaultDownloadDirExists"], bool)
    assert data["downloadImport"]["endpoint"] == "/api/grok-handoff/automation-plan/import-downloads"
    assert data["downloadImport"]["watchEndpoint"] == "/api/grok-handoff/automation-plan/watch-downloads"
    assert data["downloadImport"]["requiresOperatorApprovedTrue"] is True
    assert data["downloadImport"]["input"]["defaultDownloadDir"] == data["defaultDownloadDir"]
    assert data["downloadImport"]["input"]["defaultDownloadDirExists"] == data["defaultDownloadDirExists"]
    assert data["downloadImport"]["returnsRenderPayloadWhenReady"] is True
    assert data["mainPathStatus"]["mode"] == "grok-app-web-mp4-primary"
    assert data["mainPathStatus"]["status"] == "needs-first-grok-mp4"
    assert data["mainPathStatus"]["blocker"] == "first-grok-mp4-missing"
    assert data["mainPathStatus"]["primaryPath"] == "signed-in-grok-app-web-mp4"
    assert data["mainPathStatus"]["usesPaidApi"] is False
    assert data["mainPathStatus"]["cdpPrimaryRecommended"] is False
    assert data["mainPathStatus"]["secondaryAutomationRole"] == "isolated-cdp-and-bookmarklet-fallback-only"
    assert data["mainPathStatus"]["nextSceneId"] == "scene-01"
    assert "scene-01.grok.mp4" in data["mainPathStatus"]["primaryNextAction"]
    rail = data["browserControlPrimaryRail"]
    assert rail["mode"] == "existing-signed-in-chrome-browser-control-primary"
    assert rail["primary"] is True
    assert rail["extensionRequiredForGeneration"] is False
    assert "companionExtensionRole" not in rail
    assert rail["downloadAuthority"] == "operator-owned-manual-download-or-local-upload"
    assert rail["autoNativeDownloadPromptAllowed"] is False
    assert rail["sceneId"] == "scene-01"
    assert "new Chrome profile" in " ".join(rail["doNotUse"])
    assert data["manualPrimaryPath"]["mode"] == "manual-grok-app-web-primary"
    assert data["manualPrimaryPath"]["browserControlRail"] == "existing-signed-in-chrome-browser-control-primary"
    assert "companionExtensionRole" not in data["manualPrimaryPath"]
    assert data["manualPrimaryPath"]["currentScene"]["sceneId"] == "scene-01"
    assert data["manualPrimaryPath"]["currentScene"]["expectedFileName"] == "scene-01.grok.mp4"
    assert data["manualPrimaryPath"]["endpoints"]["importDownloads"] == "/api/grok-handoff/automation-plan/import-downloads"
    assert data["manualPrimaryPath"]["endpoints"]["manualBatchUpload"] == "/api/grok-handoff/automation-plan/upload-mp4-batch"
    assert data["manualPrimaryPath"]["endpoints"]["productionQueue"] == "/api/grok-handoff/automation-plan/production-queue"
    assert data["manualPrimaryPath"]["orderedBatchUpload"]["supported"] is True
    assert "scene order" in data["manualPrimaryPath"]["orderedBatchUpload"]["selectionRule"]
    assert data["manualPrimaryPath"]["orderedBatchUpload"]["recommendedFileOrder"][0]["sceneId"] == "scene-01"
    assert data["manualPrimaryPath"]["browserAutomationRole"] == "browser-control-primary; isolated-cdp-and-bookmarklet-fallback-only"
    assert "direct browser-control" in data["manualPrimaryPath"]["operatorNextAction"]
    assert "scene-01.grok.mp4" in data["manualPrimaryPath"]["operatorNextAction"]
    assert data["manualPrimaryPath"]["operatorSteps"][0].startswith("Use Codex/Claude browser-control")
    assert data["manualPrimaryPath"]["operatorSteps"][2].startswith("Fill the current scene prompt")
    assert "downloads/saves" in data["manualPrimaryPath"]["operatorSteps"][3]
    assert "extensionIsPrimary" not in data["automationBoundaries"]
    assert "existing signed-in Chrome browser-control" in data["automationBoundaries"]["primaryProductionRail"]
    assert data["operatorRun"]["endpoint"] == "/api/grok-handoff/automation-plan/operator-run"
    assert data["operatorRun"]["requiresOperatorApprovedTrue"] is True
    assert data["operatorRun"]["opensTargets"] == ["worksheet", "grok"]
    assert data["operatorRun"]["returnsRenderPayloadWhenReady"] is True
    assert data["browserAutomation"]["endpoint"] == "/api/grok-handoff/automation-plan/browser-automation"
    assert data["browserAutomation"]["mode"] == "operator-approved-local-cdp-generate-download-watch"
    assert data["browserAutomation"]["requiresBrowserAutomationApprovedTrue"] is True
    assert data["browserAutomation"]["profileApprovalRequiredWhenLaunching"] is True
    assert "waitForOperatorReadyApproved" in data["browserAutomation"]["optionalApprovalFlags"]
    assert data["browserAutomation"]["optionalApprovalFlags"]["generatePromptApproved"].startswith("click")
    automation_steps = " ".join(data["browserAutomation"]["automates"])
    assert "watch/import" not in automation_steps
    assert "block Download/Save/Export click requests" in automation_steps
    assert "browser-control/manual download" in automation_steps
    assert "explicit local MP4 upload/import" in automation_steps
    assert data["shotBible"]["promptAnchor"].startswith("Continuity bible:")
    assert "No captions" not in data["reviewChecklist"][0]
    assert data["expectedFiles"][0]["expectedFileName"] == "scene-01.grok.mp4"
    assert data["expectedFiles"][0]["operatorChecklist"]
    assert data["postImportReview"]["endpoint"] == "/api/grok-handoff/automation-plan/review-packet"
    assert data["postImportReview"]["decisionEndpoint"] == "/api/grok-handoff/automation-plan/review-decision"
    assert data["postImportReview"]["mode"] == "local-html-video-preview-and-operator-acceptance-checklist"


def test_grok_main_path_status_keeps_cdp_failure_secondary(tmp_path):
    client = _grok_test_client(tmp_path)
    create_response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "main-path-status",
            "grokMainSourceRequired": True,
            "minGrokMainScenes": 2,
            "sourceMixTotalScenes": 2,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Korean office worker lowers their pace on a subway platform at night.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "The same worker starts a simple dinner prep in a small warm kitchen.",
                    "duration": 4,
                },
            ],
        },
    )
    handoff_dir = Path(create_response.get_json()["handoffDir"])
    (handoff_dir / "automation-status.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "detail": "[WinError 10053] 현재 연결은 사용자의 호스트 시스템의 소프트웨어의 의해 중단되었습니다",
                "error": "[WinError 10053] 현재 연결은 사용자의 호스트 시스템의 소프트웨어의 의해 중단되었습니다",
                "remoteDebuggingPort": 9222,
            }
        ),
        encoding="utf-8",
    )

    status_response = client.get("/api/grok-handoff/main-path-status/status")

    assert status_response.status_code == 200
    data = status_response.get_json()
    main_path = data["mainPathStatus"]
    assert main_path["status"] == "needs-first-grok-mp4"
    assert main_path["blocker"] == "first-grok-mp4-missing"
    assert main_path["grokAppWebViable"] is True
    assert main_path["usesPaidApi"] is False
    assert main_path["cdpPrimaryRecommended"] is False
    assert main_path["secondaryAutomationRole"] == "isolated-cdp-and-bookmarklet-fallback-only"
    assert main_path["secondaryAutomationBlocker"] == routes_grok.CHROME_DEFAULT_PROFILE_SOCKET_ABORT_BLOCKER
    assert "existing signed-in Chrome profile" in main_path["secondaryAutomationDetail"]
    assert "saves/downloads the MP4" in main_path["secondaryAutomationDetail"]
    assert "Companion" not in main_path["secondaryAutomationDetail"]
    assert main_path["nextSceneId"] == "scene-01"
    assert main_path["nextExpectedFileName"] == "scene-01.grok.mp4"
    assert "scene-01" in main_path["primaryNextAction"]
    assert "mp4" in main_path["primaryNextAction"].lower()
    assert "xAI API pricing or quota is not required" in main_path["notBlockedBy"]
    assert data["manualPrimaryPath"]["browserAutomationRole"] == "browser-control-primary; isolated-cdp-and-bookmarklet-fallback-only"
    assert data["browserControlPrimaryRail"]["primary"] is True


def test_grok_browser_automation_requires_explicit_approval(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "browser-approval",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                }
            ],
        },
    )

    response = client.post(
        "/api/grok-handoff/browser-approval/browser-automation",
        json={"sceneId": "scene-01", "operatorApproved": True},
    )

    assert response.status_code == 403
    data = response.get_json()
    assert data["ok"] is False
    assert "browserAutomationApproved=true" in data["error"]


def test_grok_cdp_launch_rejects_default_chrome_profile_on_chrome_136(tmp_path, monkeypatch):
    local_appdata = tmp_path / "LocalAppData"
    user_data_dir = local_appdata / "Google" / "Chrome" / "User Data"
    user_data_dir.mkdir(parents=True)
    chrome_path = tmp_path / "chrome.exe"
    chrome_path.write_text("fake chrome", encoding="utf-8")

    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(routes_grok, "_find_browser_executable", lambda _value=None: str(chrome_path))

    try:
        routes_grok._launch_cdp_browser(
            {
                "launchBrowserApproved": True,
                "profileApproved": True,
                "useDefaultChromeProfile": True,
                "browserProfileDirectory": "Profile 1",
            },
            tmp_path / "handoff",
            9333,
        )
    except RuntimeError as exc:
        assert "Chrome 136+" in str(exc)
        assert "isolated Video Studio handoff profile" in str(exc)
    else:
        raise AssertionError("default Chrome profile CDP launch should be blocked")


def test_grok_cdp_launch_rejects_non_browser_executable(tmp_path, monkeypatch):
    bad_path = tmp_path / "notepad.exe"
    bad_path.write_text("fake executable", encoding="utf-8")
    opened_args: list[list[str]] = []

    monkeypatch.setattr(routes_grok.subprocess, "Popen", lambda args, **kwargs: opened_args.append(list(args)) or object())

    try:
        routes_grok._launch_cdp_browser(
            {
                "launchBrowserApproved": True,
                "profileApproved": True,
                "browserExecutable": str(bad_path),
            },
            tmp_path / "handoff",
            9333,
        )
    except RuntimeError as exc:
        assert "Chrome or Edge executable" in str(exc)
    else:
        raise AssertionError("non-browser executable should be blocked before Popen")

    assert opened_args == []


def test_grok_cdp_launch_uses_isolated_handoff_profile(tmp_path, monkeypatch):
    chrome_path = tmp_path / "chrome.exe"
    chrome_path.write_text("fake chrome", encoding="utf-8")
    launched: dict[str, list[str]] = {}

    class FakeProcess:
        pass

    def fake_popen(args, stdout=None, stderr=None):
        launched["args"] = list(args)
        launched["stdout"] = stdout
        launched["stderr"] = stderr
        return FakeProcess()

    monkeypatch.setattr(routes_grok, "_find_browser_executable", lambda _value=None: str(chrome_path))
    monkeypatch.setattr(routes_grok.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(routes_grok.time, "sleep", lambda _seconds: None)

    handoff_dir = tmp_path / "handoff"
    result = routes_grok._launch_cdp_browser(
        {
            "launchBrowserApproved": True,
            "profileApproved": True,
            "useDefaultChromeProfile": False,
            "browserProfileDirectory": "Default",
        },
        handoff_dir,
        9333,
    )

    expected_profile_dir = handoff_dir / "browser-profile"
    assert result["launched"] is True
    assert result["useDefaultChromeProfile"] is False
    assert result["browserProfileDirectory"] == "Default"
    assert result["userDataDir"] == str(expected_profile_dir)
    assert f"--user-data-dir={expected_profile_dir}" in launched["args"]
    assert "--profile-directory=Default" in launched["args"]
    assert "--remote-debugging-address=127.0.0.1" in launched["args"]
    assert "--remote-debugging-port=9333" in launched["args"]


def test_grok_default_chrome_attach_requires_explicit_operator_approval(tmp_path):
    try:
        routes_grok._run_grok_browser_automation(
            tmp_path,
            {"projectId": "default-attach", "grokUrl": "https://grok.com/imagine"},
            {"sceneId": "scene-01", "prompt": "Cinematic coffee steam.", "expectedFileName": "scene-01.grok.mp4"},
            {
                "remoteDebuggingPort": 9222,
                "useDefaultChromeProfile": True,
                "launchBrowserApproved": False,
            },
            None,
        )
    except RuntimeError as exc:
        assert "attachDefaultChromeApproved=true" in str(exc)
        assert "attach-only" in str(exc)
    else:
        raise AssertionError("default Chrome attach should require explicit attach approval")


def test_grok_default_chrome_attach_only_never_launches_default_profile(tmp_path, monkeypatch):
    class FakeAttachWs:
        def __init__(self, _url):
            self.closed = False

        def call(self, method, payload=None, timeout=None):
            if method == "Runtime.evaluate":
                return _cdp_evaluation({
                    "ok": True,
                    "title": "Imagine - Grok",
                    "url": "https://grok.com/imagine",
                    "authRequired": False,
                    "cookieChoiceRequired": False,
                    "promptInputReady": True,
                    "generateControlReady": True,
                })
            return _cdp_evaluation({"ok": True})

        def close(self):
            self.closed = True

    monkeypatch.setattr(routes_grok, "_wait_for_cdp", lambda _port, timeout_seconds=8.0: {"ok": True})
    monkeypatch.setattr(routes_grok, "_launch_cdp_browser", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("default Chrome attach must not launch a browser")
    ))
    monkeypatch.setattr(routes_grok, "_cdp_existing_grok_target", lambda _port: {
        "id": "existing-grok",
        "type": "page",
        "url": "https://grok.com/imagine",
        "title": "Imagine - Grok",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/existing-grok",
    })
    monkeypatch.setattr(routes_grok, "_cdp_new_target", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("default Chrome attach should reuse the operator-launched Grok tab")
    ))
    monkeypatch.setattr(routes_grok, "_CdpWebSocket", FakeAttachWs)

    result = routes_grok._run_grok_browser_automation(
        tmp_path,
        {"projectId": "default-attach", "grokUrl": "https://grok.com/imagine"},
        {"sceneId": "scene-01", "prompt": "Cinematic coffee steam.", "expectedFileName": "scene-01.grok.mp4"},
        {
            "remoteDebuggingPort": 9222,
            "useDefaultChromeProfile": True,
            "attachDefaultChromeApproved": True,
            "launchBrowserApproved": False,
            "preflightOnly": True,
        },
        None,
    )

    assert result["ok"] is True
    assert result["preflightOnly"] is True
    assert result["launched"] is False
    assert result["useDefaultChromeProfile"] is True
    assert result["attachDefaultChromeApproved"] is True
    assert result["browserProfileMode"] == "default-chrome-cdp-attach"
    assert result["targetReused"] is True


def test_grok_default_chrome_attach_reports_missing_cdp_without_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_grok, "_wait_for_cdp", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("cdp unavailable")
    ))
    monkeypatch.setattr(routes_grok, "_launch_cdp_browser", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("missing default Chrome CDP should not trigger a launch")
    ))

    try:
        routes_grok._run_grok_browser_automation(
            tmp_path,
            {"projectId": "default-attach", "grokUrl": "https://grok.com/imagine"},
            {"sceneId": "scene-01", "prompt": "Cinematic coffee steam.", "expectedFileName": "scene-01.grok.mp4"},
            {
                "remoteDebuggingPort": 9222,
                "useDefaultChromeProfile": True,
                "attachDefaultChromeApproved": True,
                "launchBrowserApproved": False,
            },
            None,
        )
    except RuntimeError as exc:
        assert routes_grok.CHROME_DEFAULT_PROFILE_ATTACH_BLOCKER in str(exc)
        assert "will not launch the default Chrome profile" in str(exc)
    else:
        raise AssertionError("missing CDP should surface attach guidance")


def test_grok_browser_prompt_script_waits_and_scans_shadow_dom():
    script = routes_grok._prompt_injection_script("test prompt")

    assert "Date.now() + 30000" in script
    assert "shadowRoot" in script
    assert "No editable Grok prompt input found after waiting" in script
    assert "bodyText" in script


def _cdp_evaluation(value: dict) -> dict:
    return {"result": {"result": {"value": value}}}


class _FakePreflightWs:
    def __init__(self, preflights: list[dict]):
        self.preflights = list(preflights)
        self.last_preflight = dict(preflights[-1])
        self.auth_kickoff_calls = 0
        self.auth_provider_kickoff_calls = 0
        self.cookie_choice_calls = 0

    def call(self, method, payload=None, timeout=None):
        expression = str((payload or {}).get("expression") or "")
        if "auth-provider-click" in expression:
            self.auth_provider_kickoff_calls += 1
            if 'preferredProvider = "manual"' in expression:
                return _cdp_evaluation({
                    "ok": True,
                    "clicked": False,
                    "action": "auth-provider-click",
                    "provider": "manual",
                    "reason": "Manual sign-in provider selection requested",
                })
            if 'preferredProvider = "google"' in expression:
                return _cdp_evaluation({
                    "ok": True,
                    "clicked": True,
                    "action": "auth-provider-click",
                    "provider": "google",
                    "label": "Login with Google",
                })
            return _cdp_evaluation({
                "ok": True,
                "clicked": True,
                "action": "auth-provider-click",
                "provider": "x",
                "label": "Login with X",
            })
        if "auth-login-click" in expression:
            self.auth_kickoff_calls += 1
            return _cdp_evaluation({"ok": True, "clicked": True, "action": "auth-login-click"})
        if "cookie-reject-click" in expression:
            self.cookie_choice_calls += 1
            return _cdp_evaluation({"ok": True, "clicked": True, "action": "cookie-reject-click", "label": "모두 거부"})
        if "promptInputReady" in expression:
            if self.preflights:
                self.last_preflight = self.preflights.pop(0)
            return _cdp_evaluation(self.last_preflight)
        return _cdp_evaluation({"ok": True})


def test_grok_operator_ready_wait_resumes_after_auth_clears():
    ws = _FakePreflightWs([
        {
            "ok": True,
            "authRequired": True,
            "cookieChoiceRequired": False,
            "promptInputReady": False,
            "generateControlReady": False,
            "title": "Imagine - Grok",
            "url": "https://grok.com/imagine",
        },
        {
            "ok": True,
            "authRequired": False,
            "cookieChoiceRequired": False,
            "promptInputReady": True,
            "generateControlReady": True,
            "title": "Imagine - Grok",
            "url": "https://grok.com/imagine",
        },
    ])

    result = routes_grok._wait_for_operator_ready(ws, {
        "authKickoffApproved": True,
        "operatorReadyTimeoutSeconds": 1,
        "operatorReadyPollIntervalSeconds": 0.1,
    })

    assert result["ready"] is True
    assert result["timedOut"] is False
    assert result["attempts"] == 2
    assert result["authKickoff"]["clicked"] is True
    assert ws.auth_kickoff_calls == 1


def test_grok_operator_ready_wait_kicks_off_xai_x_provider():
    ws = _FakePreflightWs([
        {
            "ok": True,
            "authRequired": True,
            "cookieChoiceRequired": False,
            "promptInputReady": False,
            "generateControlReady": False,
            "candidateLabels": ["xAI account home link /", "Login with X", "Login with email", "Login with Google"],
            "title": "Sign In to Your Grok Account | Grok",
            "url": "https://accounts.x.ai/sign-in?redirect=grok-com&return_to=%2Fimagine",
        },
        {
            "ok": True,
            "authRequired": False,
            "cookieChoiceRequired": False,
            "promptInputReady": True,
            "generateControlReady": True,
            "title": "Imagine - Grok",
            "url": "https://grok.com/imagine",
        },
    ])

    result = routes_grok._wait_for_operator_ready(ws, {
        "authKickoffApproved": True,
        "authProviderKickoffApproved": True,
        "operatorReadyTimeoutSeconds": 1,
        "operatorReadyPollIntervalSeconds": 0.1,
    })

    assert result["ready"] is True
    assert result["authProviderKickoff"]["clicked"] is True
    assert result["authProviderKickoff"]["action"] == "auth-provider-click"
    assert result["authProviderKickoff"]["provider"] == "x"
    assert ws.auth_provider_kickoff_calls == 1
    assert ws.auth_kickoff_calls == 0


def test_grok_operator_ready_wait_kicks_off_xai_google_provider():
    ws = _FakePreflightWs([
        {
            "ok": True,
            "authRequired": True,
            "cookieChoiceRequired": False,
            "promptInputReady": False,
            "generateControlReady": False,
            "candidateLabels": ["Login with X", "Login with email", "Login with Google"],
            "title": "Sign In to Your Grok Account | Grok",
            "url": "https://accounts.x.ai/sign-in?redirect=grok-com&return_to=%2Fimagine",
        },
        {
            "ok": True,
            "authRequired": False,
            "cookieChoiceRequired": False,
            "promptInputReady": True,
            "generateControlReady": True,
            "title": "Imagine - Grok",
            "url": "https://grok.com/imagine",
        },
    ])

    result = routes_grok._wait_for_operator_ready(ws, {
        "authKickoffApproved": True,
        "authProviderKickoffApproved": True,
        "authProviderPreference": "google",
        "operatorReadyTimeoutSeconds": 1,
        "operatorReadyPollIntervalSeconds": 0.1,
    })

    assert result["ready"] is True
    assert result["authProviderPreference"] == "google"
    assert result["authProviderKickoff"]["clicked"] is True
    assert result["authProviderKickoff"]["provider"] == "google"
    assert result["authProviderKickoff"]["label"] == "Login with Google"
    assert ws.auth_provider_kickoff_calls == 1
    assert ws.auth_kickoff_calls == 0


def test_grok_operator_ready_wait_manual_provider_does_not_click_provider():
    ws = _FakePreflightWs([
        {
            "ok": True,
            "authRequired": True,
            "cookieChoiceRequired": False,
            "promptInputReady": False,
            "generateControlReady": False,
            "candidateLabels": ["Login with X", "Login with email", "Login with Google"],
            "title": "Sign In to Your Grok Account | Grok",
            "url": "https://accounts.x.ai/sign-in?redirect=grok-com&return_to=%2Fimagine",
        },
    ])

    result = routes_grok._wait_for_operator_ready(ws, {
        "authKickoffApproved": True,
        "authProviderKickoffApproved": True,
        "authProviderPreference": "manual",
        "operatorReadyTimeoutSeconds": 0.01,
        "operatorReadyPollIntervalSeconds": 0.01,
    })

    assert result["ready"] is False
    assert result["authProviderPreference"] == "manual"
    assert result["authProviderKickoff"]["clicked"] is False
    assert result["authProviderKickoff"]["provider"] == "manual"
    assert ws.auth_provider_kickoff_calls == 1
    assert ws.auth_kickoff_calls == 0


def test_grok_existing_cdp_target_prefers_grok_page_over_iframes_and_auth(monkeypatch):
    def fake_cdp_json(_port, path, method="GET"):
        assert path == "/json/list"
        assert method == "GET"
        return [
            {
                "id": "stripe-frame",
                "type": "iframe",
                "url": "https://js.stripe.com/v3/m-outer.html#url=https%3A%2F%2Fgrok.com%2Fimagine",
                "title": "Stripe frame",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/stripe-frame",
            },
            {
                "id": "auth",
                "type": "page",
                "url": "https://accounts.x.ai/sign-in?redirect=grok-com&return_to=%2Fimagine",
                "title": "Sign In to Your Grok Account | Grok",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/auth",
            },
            {
                "id": "grok",
                "type": "page",
                "url": "https://grok.com/imagine",
                "title": "Imagine - Grok",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/grok",
            },
        ]

    monkeypatch.setattr(routes_grok, "_cdp_json", fake_cdp_json)

    target = routes_grok._cdp_existing_grok_target(9222)

    assert target["id"] == "grok"


def test_grok_existing_cdp_target_prefers_x_oauth_over_xai_sign_in(monkeypatch):
    def fake_cdp_json(_port, path, method="GET"):
        assert path == "/json/list"
        assert method == "GET"
        return [
            {
                "id": "xai-sign-in",
                "type": "page",
                "url": "https://accounts.x.ai/sign-in?redirect=grok-com&return_to=%2Fimagine",
                "title": "Sign In to Your Grok Account | Grok",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/xai-sign-in",
            },
            {
                "id": "x-oauth",
                "type": "page",
                "url": "https://x.com/i/oauth2/authorize?redirect_uri=https%3A%2F%2Faccounts.x.ai%2Fexchange-token%2F",
                "title": "Authorize xAI",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/x-oauth",
            },
        ]

    monkeypatch.setattr(routes_grok, "_cdp_json", fake_cdp_json)

    target = routes_grok._cdp_existing_grok_target(9222)

    assert target["id"] == "x-oauth"


def test_grok_browser_automation_reuses_existing_target_before_new_tab(tmp_path, monkeypatch):
    class FakeAutomationWs:
        def __init__(self, _url):
            self.closed = False

        def call(self, method, payload=None, timeout=None):
            if method == "Runtime.evaluate":
                return _cdp_evaluation({
                    "ok": True,
                    "title": "Imagine - Grok",
                    "url": "https://grok.com/imagine",
                })
            return _cdp_evaluation({"ok": True})

        def close(self):
            self.closed = True

    monkeypatch.setattr(routes_grok, "_wait_for_cdp", lambda _port, timeout_seconds=8.0: {"ok": True})
    monkeypatch.setattr(routes_grok, "_cdp_existing_grok_target", lambda _port: {
        "id": "existing-grok",
        "type": "page",
        "url": "https://grok.com/imagine",
        "title": "Imagine - Grok",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/existing-grok",
    })
    monkeypatch.setattr(routes_grok, "_cdp_new_target", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("new Grok tab should not be opened when an existing target is available")
    ))
    monkeypatch.setattr(routes_grok, "_CdpWebSocket", FakeAutomationWs)

    result = routes_grok._run_grok_browser_automation(
        tmp_path,
        {"projectId": "reuse-target", "grokUrl": "https://grok.com/imagine"},
        {"sceneId": "scene-01", "prompt": "Cinematic coffee steam.", "expectedFileName": "scene-01.grok.mp4"},
        {"remoteDebuggingPort": 9222},
        None,
    )

    assert result["ok"] is True
    assert result["promptInjected"] is True
    assert result["targetReused"] is True
    assert result["targetUrl"] == "https://grok.com/imagine"


def test_grok_operator_ready_wait_caps_approved_long_wait_at_two_hours():
    ws = _FakePreflightWs([
        {
            "ok": True,
            "authRequired": False,
            "cookieChoiceRequired": False,
            "promptInputReady": True,
            "generateControlReady": True,
            "title": "Imagine - Grok",
            "url": "https://grok.com/imagine",
        },
    ])

    result = routes_grok._wait_for_operator_ready(ws, {
        "operatorReadyTimeoutSeconds": 9999,
        "operatorReadyPollIntervalSeconds": 0.1,
    })

    assert result["ready"] is True
    assert result["timeoutSeconds"] == 7200.0


def test_grok_status_uses_active_background_wait_over_stale_timeout():
    stale_status = {
        "projectId": "long-wait",
        "sceneId": "scene-01",
        "expectedFileName": "scene-01.grok.mp4",
        "status": "needs-operator",
        "operatorReadyTimedOut": True,
        "updatedAt": "2026-05-25T09:00:00",
        "operatorReadyWait": {
            "timedOut": True,
            "timeoutSeconds": 1800.0,
        },
    }
    active_job = {
        "projectId": "long-wait",
        "sceneId": "scene-01",
        "expectedFileName": "scene-01.grok.mp4",
        "status": "running",
        "activeThread": True,
        "createdAt": "2026-05-25T09:26:00",
        "startedAt": "2026-05-25T09:26:00",
        "elapsedSeconds": 12.5,
        "operatorWaitDeadlineAt": "2026-05-25T11:26:00",
        "operatorWaitRemainingSeconds": 7187.5,
        "automationReplay": {
            "operatorReadyTimeoutSeconds": 7200,
            "operatorReadyPollIntervalSeconds": 2,
        },
    }

    result = routes_grok._effective_automation_status_for_active_job(stale_status, active_job)

    assert result["status"] == "waiting-for-operator"
    assert result["activeBackgroundWait"] is True
    assert result["operatorReadyTimedOut"] is False
    assert result["operatorReadyWait"]["timedOut"] is False
    assert result["operatorReadyWait"]["timeoutSeconds"] == 7200


def test_grok_operator_ready_wait_times_out_with_auth_blocker():
    ws = _FakePreflightWs([
        {
            "ok": True,
            "authRequired": True,
            "cookieChoiceRequired": False,
            "promptInputReady": False,
            "generateControlReady": False,
            "title": "Imagine - Grok",
            "url": "https://grok.com/imagine",
        },
    ])

    result = routes_grok._wait_for_operator_ready(ws, {
        "operatorReadyTimeoutSeconds": 0.12,
        "operatorReadyPollIntervalSeconds": 0.1,
    })

    assert result["ready"] is False
    assert result["timedOut"] is True
    assert result["browserBlocker"] == "grok-auth-required"
    assert result["requiresOperatorAction"] is True


def test_grok_operator_ready_wait_can_reject_cookie_overlay():
    ws = _FakePreflightWs([
        {
            "ok": True,
            "authRequired": False,
            "cookieChoiceRequired": True,
            "promptInputReady": False,
            "generateControlReady": False,
            "title": "Imagine - Grok",
            "url": "https://grok.com/imagine",
        },
        {
            "ok": True,
            "authRequired": False,
            "cookieChoiceRequired": False,
            "promptInputReady": True,
            "generateControlReady": True,
            "title": "Imagine - Grok",
            "url": "https://grok.com/imagine",
        },
    ])

    result = routes_grok._wait_for_operator_ready(ws, {
        "cookieRejectApproved": True,
        "operatorReadyTimeoutSeconds": 1,
        "operatorReadyPollIntervalSeconds": 0.1,
    })

    assert result["ready"] is True
    assert result["cookieChoice"]["clicked"] is True
    assert result["cookieChoice"]["label"] == "모두 거부"
    assert ws.cookie_choice_calls == 1


def test_grok_browser_automation_uses_selected_scene_prompt(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "browser-auto",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "First scene prompt.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Second scene prompt for Grok.",
                    "duration": 4,
                },
            ],
        },
    )
    captured = {}

    def fake_browser_automation(handoff_dir, manifest, scene, data, download_dir):
        captured["handoffDir"] = handoff_dir
        captured["scene"] = scene
        captured["data"] = data
        captured["downloadDir"] = download_dir
        return {
            "ok": True,
            "browserAutomationMode": "fake-cdp",
            "filledSceneId": scene["sceneId"],
            "promptInjected": True,
            "remoteDebuggingPort": 9222,
        }

    monkeypatch.setattr(routes_grok, "_run_grok_browser_automation", fake_browser_automation)

    response = client.post(
        "/api/grok-handoff/browser-auto/browser-automation",
        json={
            "sceneId": "scene-02",
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "waitForOperatorReadyApproved": True,
            "authKickoffApproved": True,
            "cookieRejectApproved": True,
            "operatorReadyTimeoutSeconds": 600,
            "operatorReadyPollIntervalSeconds": 2,
            "downloadDir": str(downloads),
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["sceneId"] == "scene-02"
    assert data["expectedFileName"] == "scene-02.grok.mp4"
    assert data["browserAutomationMode"] == "fake-cdp"
    assert data["promptInjected"] is True
    assert captured["scene"]["prompt"].startswith("Second scene prompt")
    assert captured["downloadDir"] == downloads.resolve()
    assert captured["data"]["browserAutomationApproved"] is True
    assert captured["data"]["waitForOperatorReadyApproved"] is True
    assert captured["data"]["authKickoffApproved"] is True
    assert captured["data"]["cookieRejectApproved"] is True
    assert captured["data"]["operatorReadyTimeoutSeconds"] == 600
    status = client.get("/api/grok-handoff/browser-auto/status").get_json()
    assert status["automationStatus"]["status"] == "injected"
    assert status["automationStatus"]["sceneId"] == "scene-02"
    assert status["automationStatus"]["promptInjected"] is True
    assert (tmp_path / "storage" / "grok-handoffs" / "browser-auto" / "automation-status.json").exists()


def test_grok_browser_automation_persists_auth_blocker_for_resume(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "browser-auth-status",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )

    def fake_browser_automation(_handoff_dir, _manifest, scene, _data, _download_dir):
        return {
            "ok": True,
            "browserAutomationMode": "operator-approved-cdp-wait-resume",
            "filledSceneId": scene["sceneId"],
            "promptInjected": False,
            "generatePromptRequested": True,
            "downloadResultRequested": True,
            "watchDownloadsRequested": True,
            "authRequired": True,
            "browserBlocker": "grok-auth-required",
            "requiresOperatorAction": True,
            "operatorReadyTimedOut": True,
            "operatorReadyWait": {
                "ready": False,
                "timedOut": True,
                "attempts": 3,
                "elapsedSeconds": 6,
                "authRequired": True,
                "browserBlocker": "grok-auth-required",
                "preflight": {
                    "title": "Sign In to Your Grok Account | Grok",
                    "url": "https://accounts.x.ai/sign-in",
                    "authRequired": True,
                    "promptInputReady": False,
                },
            },
            "operatorNextAction": "Complete Grok login, then rerun approved automation.",
            "targetUrl": "https://accounts.x.ai/sign-in",
            "targetTitle": "Sign In to Your Grok Account | Grok",
        }

    monkeypatch.setattr(routes_grok, "_run_grok_browser_automation", fake_browser_automation)

    response = client.post(
        "/api/grok-handoff/browser-auth-status/browser-automation",
        json={
            "sceneId": "scene-01",
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "generatePromptApproved": True,
            "downloadResultApproved": True,
            "watchDownloadsApproved": True,
            "downloadDir": str(tmp_path),
        },
    )
    status = client.get("/api/grok-handoff/browser-auth-status/status")

    assert response.status_code == 200
    data = response.get_json()
    assert data["automationStatus"]["status"] == "needs-operator"
    assert data["automationStatus"]["browserBlocker"] == "grok-auth-required"
    assert data["automationStatus"]["operatorReadyWait"]["preflight"]["authRequired"] is True
    status_data = status.get_json()
    assert status_data["automationStatus"]["status"] == "needs-operator"
    assert status_data["automationStatus"]["operatorNextAction"].startswith("Complete Grok login")
    assert status_data["automationReplay"]["sceneId"] == "scene-01"
    assert status_data["automationReplay"]["requiresFreshApproval"] is True


def test_grok_resume_automation_requires_fresh_approval(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "resume-approval",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )

    response = client.post("/api/grok-handoff/resume-approval/resume-automation", json={})

    assert response.status_code == 403
    assert "operatorApproved=true" in response.get_json()["error"]


def test_grok_operator_focus_requires_explicit_focus_approval(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "focus-approval",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )

    response = client.post(
        "/api/grok-handoff/focus-approval/operator-focus",
        json={"operatorApproved": True, "browserAutomationApproved": True},
    )

    assert response.status_code == 403
    assert "focusApproved=true" in response.get_json()["error"]


def test_grok_operator_focus_activates_login_tab_and_reports_counts(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "focus-login",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )
    activated = []

    monkeypatch.setattr(routes_grok, "_wait_for_cdp", lambda _port, timeout_seconds=3: {"ok": True})
    monkeypatch.setattr(
        routes_grok,
        "_cdp_grok_operator_targets",
        lambda _port, _prefer_auth=False: {
            "remoteDebuggingPort": 9222,
            "pageCount": 4,
            "grokTabCount": 1,
            "signInTabCount": 2,
            "hasOperatorTarget": True,
            "bestTarget": {
                "targetId": "target-auth",
                "title": "Sign In to Your Grok Account | Grok",
                "url": "https://accounts.x.ai/sign-in?return_to=%2Fimagine",
                "kind": "grok-auth",
                "score": 290,
            },
            "targets": [
                {
                    "targetId": "target-auth",
                    "title": "Sign In to Your Grok Account | Grok",
                    "url": "https://accounts.x.ai/sign-in?return_to=%2Fimagine",
                    "kind": "grok-auth",
                    "score": 290,
                }
            ],
        },
    )
    monkeypatch.setattr(routes_grok, "_cdp_activate_target", lambda _port, target_id: activated.append(target_id) or "Target activated")

    response = client.post(
        "/api/grok-handoff/focus-login/operator-focus",
        json={
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "focusApproved": True,
            "remoteDebuggingPort": 9222,
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["focused"] is True
    assert data["signInTabCount"] == 2
    assert data["bestTarget"]["kind"] == "grok-auth"
    assert data["operatorNextAction"].startswith("Complete Grok/xAI login")
    assert activated == ["target-auth"]


def test_grok_operator_target_scoring_ignores_non_grok_login_pages():
    score, kind = routes_grok._score_grok_operator_target({
        "title": "Chrome에 로그인하세요",
        "url": "chrome://intro/",
    })

    assert score == 0
    assert kind == "page"


def test_grok_operator_auth_stage_detects_x_oauth_consent():
    state = routes_grok._browser_state_from_actions({
        "authRequired": True,
        "url": "https://x.com/i/oauth2/authorize?redirect_uri=https%3A%2F%2Faccounts.x.ai%2Fexchange-token%2F",
        "candidateLabels": ["OAuth_Consent_Log_In_Button 로그인"],
    })

    assert state["browserBlocker"] == "grok-auth-required"
    assert state["operatorAuthStage"] == "x-oauth-consent"
    assert state["operatorAuthStageLabel"] == "X OAuth consent/login"
    assert state["operatorNextAction"].startswith("Use the focused X OAuth screen")


def test_grok_operator_target_scoring_keeps_x_oauth_target():
    score, kind = routes_grok._score_grok_operator_target({
        "title": "",
        "url": "https://x.com/i/oauth2/authorize?redirect_uri=https%3A%2F%2Faccounts.x.ai%2Fexchange-token%2F",
    })

    assert score > 0
    assert kind == "x-oauth"


def test_grok_operator_tab_cleanup_requires_close_approval(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "cleanup-approval",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )

    response = client.post(
        "/api/grok-handoff/cleanup-approval/operator-tabs/cleanup",
        json={"operatorApproved": True, "browserAutomationApproved": True},
    )

    assert response.status_code == 403
    assert "closeDuplicatesApproved=true" in response.get_json()["error"]


def test_grok_operator_tab_cleanup_closes_duplicates_and_keeps_best_auth_tab(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "cleanup-tabs",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )
    status_dir = tmp_path / "storage" / "grok-handoffs" / "cleanup-tabs"
    (status_dir / "automation-status.json").write_text(
        json.dumps({"authRequired": True, "browserBlocker": "grok-auth-required"}),
        encoding="utf-8",
    )
    closed = []
    activated = []
    target_sets = [
        {
            "remoteDebuggingPort": 9222,
            "pageCount": 4,
            "grokTabCount": 2,
            "signInTabCount": 2,
            "hasOperatorTarget": True,
            "bestTarget": {"targetId": "auth-keep", "title": "Sign In", "url": "https://accounts.x.ai/sign-in", "kind": "grok-auth", "score": 810},
            "targets": [
                {"targetId": "auth-keep", "title": "Sign In", "url": "https://accounts.x.ai/sign-in", "kind": "grok-auth", "score": 810},
                {"targetId": "auth-close", "title": "Sign In", "url": "https://accounts.x.ai/sign-in", "kind": "grok-auth", "score": 810},
                {"targetId": "grok-close", "title": "Imagine - Grok", "url": "https://grok.com/imagine", "kind": "grok-imagine", "score": 360},
            ],
        },
        {
            "remoteDebuggingPort": 9222,
            "pageCount": 2,
            "grokTabCount": 0,
            "signInTabCount": 1,
            "hasOperatorTarget": True,
            "bestTarget": {"targetId": "auth-keep", "title": "Sign In", "url": "https://accounts.x.ai/sign-in", "kind": "grok-auth", "score": 810},
            "targets": [
                {"targetId": "auth-keep", "title": "Sign In", "url": "https://accounts.x.ai/sign-in", "kind": "grok-auth", "score": 810},
            ],
        },
    ]

    monkeypatch.setattr(routes_grok, "_wait_for_cdp", lambda _port, timeout_seconds=3: {"ok": True})
    monkeypatch.setattr(routes_grok, "_cdp_grok_operator_targets", lambda _port, prefer_auth=False, limit=8: target_sets.pop(0))
    monkeypatch.setattr(routes_grok, "_cdp_close_target", lambda _port, target_id: closed.append(target_id) or "Target is closing")
    monkeypatch.setattr(routes_grok, "_cdp_activate_target", lambda _port, target_id: activated.append(target_id) or "Target activated")

    response = client.post(
        "/api/grok-handoff/cleanup-tabs/operator-tabs/cleanup",
        json={
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "closeDuplicatesApproved": True,
            "remoteDebuggingPort": 9222,
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["preferAuthTarget"] is True
    assert data["closedCount"] == 2
    assert data["bestTarget"]["targetId"] == "auth-keep"
    assert closed == ["auth-close", "grok-close"]
    assert activated == ["auth-keep"]


def test_grok_resume_automation_replays_last_sanitized_request(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "resume-replay",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )
    calls = []

    def fake_browser_automation(_handoff_dir, _manifest, scene, data, download_dir):
        calls.append({"scene": scene, "data": data, "downloadDir": download_dir})
        return {
            "ok": True,
            "browserAutomationMode": "fake-resume",
            "filledSceneId": scene["sceneId"],
            "promptInjected": True,
            "generatePromptRequested": data["generatePromptApproved"],
            "generateRequested": True,
            "downloadResultRequested": data["downloadResultApproved"],
            "watchDownloadsRequested": data["watchDownloadsApproved"],
            "readyScenes": 0,
            "totalScenes": 1,
            "allReady": False,
        }

    monkeypatch.setattr(routes_grok, "_run_grok_browser_automation", fake_browser_automation)

    first = client.post(
        "/api/grok-handoff/resume-replay/browser-automation",
        json={
            "sceneId": "scene-01",
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "waitForOperatorReadyApproved": True,
            "generatePromptApproved": True,
            "downloadResultApproved": True,
            "watchDownloadsApproved": True,
            "downloadDir": str(downloads),
            "operatorReadyTimeoutSeconds": 600,
        },
    )
    second = client.post(
        "/api/grok-handoff/resume-replay/resume-automation",
        json={
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "profileApproved": True,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    data = second.get_json()
    assert data["ok"] is True
    assert data["automationReplay"]["downloadDir"] == str(downloads.resolve())
    assert data["automationReplay"]["generatePromptApproved"] is True
    assert data["automationReplay"]["watchDownloadsApproved"] is True
    assert len(calls) == 2
    assert calls[1]["data"]["operatorApproved"] is True
    assert calls[1]["data"]["browserAutomationApproved"] is True
    assert calls[1]["data"]["generatePromptApproved"] is True
    assert calls[1]["downloadDir"] == downloads.resolve()
    request_path = tmp_path / "storage" / "grok-handoffs" / "resume-replay" / "automation-request.json"
    request_json = json.loads(request_path.read_text(encoding="utf-8"))
    assert request_json["operatorApproved"] is False
    assert request_json["browserAutomationApproved"] is False
    assert request_json["profileApproved"] is False


def test_grok_resume_automation_allows_fresh_auth_kickoff_approval(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "resume-auth-kickoff",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )
    calls = []

    def fake_browser_automation(_handoff_dir, _manifest, scene, data, download_dir):
        calls.append({"scene": scene, "data": data, "downloadDir": download_dir})
        return {
            "ok": True,
            "browserAutomationMode": "fake-resume-auth",
            "filledSceneId": scene["sceneId"],
            "promptInjected": False,
            "generatePromptRequested": data["generatePromptApproved"],
            "generateRequested": False,
            "downloadResultRequested": data["downloadResultApproved"],
            "watchDownloadsRequested": data["watchDownloadsApproved"],
            "authRequired": True,
            "browserBlocker": "grok-auth-required",
            "requiresOperatorAction": True,
            "operatorReadyTimedOut": False,
            "readyScenes": 0,
            "totalScenes": 1,
            "allReady": False,
        }

    monkeypatch.setattr(routes_grok, "_run_grok_browser_automation", fake_browser_automation)

    first = client.post(
        "/api/grok-handoff/resume-auth-kickoff/browser-automation",
        json={
            "sceneId": "scene-01",
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "waitForOperatorReadyApproved": True,
            "generatePromptApproved": True,
            "downloadResultApproved": True,
            "watchDownloadsApproved": True,
            "downloadDir": str(downloads),
            "operatorReadyTimeoutSeconds": 600,
        },
    )
    second = client.post(
        "/api/grok-handoff/resume-auth-kickoff/resume-automation",
        json={
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "profileApproved": True,
            "waitForOperatorReadyApproved": True,
            "authKickoffApproved": True,
            "cookieRejectApproved": True,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    data = second.get_json()
    assert data["automationReplay"]["authKickoffApproved"] is True
    assert data["automationReplay"]["cookieRejectApproved"] is True
    assert data["automationReplay"]["waitForOperatorReadyApproved"] is True
    assert data["automationReplay"]["downloadResultApproved"] is True
    assert calls[1]["data"]["authKickoffApproved"] is True
    assert calls[1]["data"]["cookieRejectApproved"] is True
    assert calls[1]["data"]["generatePromptApproved"] is True
    assert calls[1]["downloadDir"] == downloads.resolve()

    request_path = tmp_path / "storage" / "grok-handoffs" / "resume-auth-kickoff" / "automation-request.json"
    request_json = json.loads(request_path.read_text(encoding="utf-8"))
    assert request_json["authKickoffApproved"] is True
    assert request_json["cookieRejectApproved"] is True
    assert request_json["operatorApproved"] is False
    assert request_json["browserAutomationApproved"] is False
    assert request_json["profileApproved"] is False


def test_grok_background_automation_starts_job_and_persists_status(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "background-job",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )
    calls = []

    def fake_browser_automation(_handoff_dir, _manifest, scene, data, download_dir):
        calls.append({"scene": scene, "data": data, "downloadDir": download_dir})
        return {
            "ok": True,
            "browserAutomationMode": "fake-background",
            "filledSceneId": scene["sceneId"],
            "promptInjected": True,
            "generatePromptRequested": data["generatePromptApproved"],
            "generateRequested": True,
            "downloadResultRequested": data["downloadResultApproved"],
            "watchDownloadsRequested": data["watchDownloadsApproved"],
            "readyScenes": 0,
            "totalScenes": 1,
            "allReady": False,
        }

    monkeypatch.setattr(routes_grok, "_run_grok_browser_automation", fake_browser_automation)

    response = client.post(
        "/api/grok-handoff/background-job/background-automation",
        json={
            "sceneId": "scene-01",
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "launchBrowserApproved": True,
            "profileApproved": True,
            "waitForOperatorReadyApproved": True,
            "generatePromptApproved": True,
            "downloadResultApproved": True,
            "watchDownloadsApproved": True,
            "downloadDir": str(downloads),
            "operatorReadyTimeoutSeconds": 600,
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["automationJob"]["status"] == "queued"
    assert data["automationReplay"]["requiresFreshApproval"] is True

    status_data = None
    for _ in range(50):
        status_data = client.get("/api/grok-handoff/background-job/status").get_json()
        if status_data.get("automationJob", {}).get("status") == "completed":
            break
        time.sleep(0.02)

    assert calls
    assert calls[0]["data"]["operatorApproved"] is True
    assert calls[0]["data"]["browserAutomationApproved"] is True
    assert calls[0]["data"]["profileApproved"] is True
    assert calls[0]["data"]["generatePromptApproved"] is True
    assert calls[0]["downloadDir"] == downloads.resolve()
    assert status_data["automationJob"]["status"] == "completed"
    assert status_data["automationJob"]["automationStatus"]["status"] == "injected"
    assert status_data["automationStatus"]["status"] == "injected"

    request_path = tmp_path / "storage" / "grok-handoffs" / "background-job" / "automation-request.json"
    request_json = json.loads(request_path.read_text(encoding="utf-8"))
    assert request_json["operatorApproved"] is False
    assert request_json["browserAutomationApproved"] is False
    assert request_json["profileApproved"] is False


def test_grok_background_automation_exposes_live_operator_wait_progress(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "background-live-wait",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )
    progress_written = threading.Event()
    release = threading.Event()

    def fake_browser_automation(_handoff_dir, _manifest, scene, data, download_dir):
        progress_callback = data.get("_operatorReadyProgress")
        assert callable(progress_callback)
        progress_callback({
            "ready": False,
            "timedOut": False,
            "attempts": 3,
            "elapsedSeconds": 4.2,
            "timeoutSeconds": 600,
            "pollIntervalSeconds": 2,
            "promptInputReady": False,
            "generateControlReady": False,
            "preflight": {
                "ok": True,
                "url": "https://accounts.x.ai/sign-in",
                "title": "Sign in - xAI",
                "authRequired": True,
                "cookieChoiceRequired": False,
                "promptInputReady": False,
                "generateControlReady": False,
            },
            "authRequired": True,
            "cookieChoiceRequired": False,
            "browserBlocker": "grok-auth-required",
            "requiresOperatorAction": True,
        })
        progress_written.set()
        release.wait(timeout=2)
        return {
            "ok": True,
            "browserAutomationMode": "fake-background",
            "filledSceneId": scene["sceneId"],
            "promptInjected": True,
            "generatePromptRequested": data["generatePromptApproved"],
            "generateRequested": True,
            "downloadResultRequested": data["downloadResultApproved"],
            "watchDownloadsRequested": data["watchDownloadsApproved"],
            "readyScenes": 0,
            "totalScenes": 1,
            "allReady": False,
        }

    monkeypatch.setattr(routes_grok, "_run_grok_browser_automation", fake_browser_automation)

    response = client.post(
        "/api/grok-handoff/background-live-wait/background-automation",
        json={
            "sceneId": "scene-01",
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "launchBrowserApproved": True,
            "profileApproved": True,
            "waitForOperatorReadyApproved": True,
            "authKickoffApproved": True,
            "generatePromptApproved": True,
            "downloadResultApproved": True,
            "watchDownloadsApproved": True,
            "downloadDir": str(downloads),
            "operatorReadyTimeoutSeconds": 600,
        },
    )

    try:
        assert response.status_code == 200
        assert progress_written.wait(timeout=1)
        status_data = client.get("/api/grok-handoff/background-live-wait/status").get_json()
        assert status_data["automationStatus"]["status"] == "waiting-for-operator"
        assert status_data["automationStatus"]["activeBackgroundWait"] is True
        assert status_data["automationStatus"]["authRequired"] is True
        assert status_data["automationStatus"]["browserBlocker"] == "grok-auth-required"
        assert "resume automatically" in status_data["automationStatus"]["operatorNextAction"]
        wait_status = status_data["automationStatus"]["operatorReadyWait"]
        assert wait_status["attempts"] == 3
        assert wait_status["preflight"]["authRequired"] is True
        assert status_data["automationJob"]["status"] == "running"
        assert status_data["automationJob"]["activeThread"] is True
        assert status_data["automationJob"]["automationStatus"]["status"] == "waiting-for-operator"
    finally:
        release.set()


def test_grok_background_automation_duplicate_start_returns_running_job(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "background-duplicate",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )
    started = threading.Event()
    release = threading.Event()

    def fake_browser_automation(_handoff_dir, _manifest, scene, data, download_dir):
        started.set()
        release.wait(timeout=2)
        return {
            "ok": True,
            "browserAutomationMode": "fake-background",
            "filledSceneId": scene["sceneId"],
            "promptInjected": True,
            "generatePromptRequested": data["generatePromptApproved"],
            "generateRequested": True,
            "downloadResultRequested": data["downloadResultApproved"],
            "watchDownloadsRequested": data["watchDownloadsApproved"],
            "readyScenes": 0,
            "totalScenes": 1,
            "allReady": False,
        }

    monkeypatch.setattr(routes_grok, "_run_grok_browser_automation", fake_browser_automation)
    request = {
        "sceneId": "scene-01",
        "operatorApproved": True,
        "browserAutomationApproved": True,
        "launchBrowserApproved": True,
        "profileApproved": True,
        "waitForOperatorReadyApproved": True,
        "generatePromptApproved": True,
        "downloadResultApproved": True,
        "watchDownloadsApproved": True,
        "downloadDir": str(downloads),
        "operatorReadyTimeoutSeconds": 600,
    }

    first = client.post("/api/grok-handoff/background-duplicate/background-automation", json=request)
    assert first.status_code == 200
    assert first.get_json()["ok"] is True
    assert started.wait(timeout=1)

    second = client.post("/api/grok-handoff/background-duplicate/background-automation", json=request)
    assert second.status_code == 200
    second_data = second.get_json()
    assert second_data["ok"] is True
    assert second_data["alreadyRunning"] is True
    assert second_data["automationJob"]["activeThread"] is True
    assert second_data["automationJob"]["restartAvailable"] is False
    assert second_data["automationJob"]["automationReplay"]["operatorReadyTimeoutSeconds"] == 600
    assert "operatorWaitRemainingSeconds" in second_data["automationJob"]

    status_data = client.get("/api/grok-handoff/background-duplicate/status").get_json()
    assert status_data["automationJob"]["activeThread"] is True
    assert status_data["automationJob"]["restartAvailable"] is False
    assert status_data["automationJob"]["automationReplay"]["operatorReadyTimeoutSeconds"] == 600

    release.set()
    for _ in range(50):
        status_data = client.get("/api/grok-handoff/background-duplicate/status").get_json()
        if status_data.get("automationJob", {}).get("status") == "completed":
            break
        time.sleep(0.02)
    assert status_data["automationJob"]["status"] == "completed"


def test_grok_background_automation_can_supersede_active_job_for_isolated_profile(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "background-supersede",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )
    first_started = threading.Event()
    first_cancelled = threading.Event()
    calls = []

    def fake_browser_automation(_handoff_dir, _manifest, scene, data, download_dir):
        calls.append({"scene": scene, "data": data, "downloadDir": download_dir})
        if len(calls) == 1:
            first_started.set()
            deadline = time.time() + 2
            while time.time() < deadline:
                should_cancel = data.get("_operatorReadyShouldCancel")
                if callable(should_cancel) and should_cancel():
                    first_cancelled.set()
                    return {
                        "ok": True,
                        "browserAutomationMode": "fake-background",
                        "filledSceneId": scene["sceneId"],
                        "cancelled": True,
                        "cancelReason": "Superseded by a fresh operator-approved Grok background run.",
                        "promptInjected": False,
                        "generatePromptRequested": data["generatePromptApproved"],
                        "generateRequested": False,
                        "downloadResultRequested": data["downloadResultApproved"],
                        "watchDownloadsRequested": data["watchDownloadsApproved"],
                        "readyScenes": 0,
                        "totalScenes": 1,
                        "allReady": False,
                    }
                time.sleep(0.02)
            raise AssertionError("supersede cancellation was not observed")
        return {
            "ok": True,
            "browserAutomationMode": "fake-background",
            "filledSceneId": scene["sceneId"],
            "promptInjected": True,
            "generatePromptRequested": data["generatePromptApproved"],
            "generateRequested": True,
            "downloadResultRequested": data["downloadResultApproved"],
            "watchDownloadsRequested": data["watchDownloadsApproved"],
            "readyScenes": 0,
            "totalScenes": 1,
            "allReady": False,
            "useDefaultChromeProfile": data.get("useDefaultChromeProfile") is True,
            "browserProfileDirectory": data.get("browserProfileDirectory"),
        }

    monkeypatch.setattr(routes_grok, "_run_grok_browser_automation", fake_browser_automation)
    stale_request = {
        "sceneId": "scene-01",
        "operatorApproved": True,
        "browserAutomationApproved": True,
        "launchBrowserApproved": True,
        "profileApproved": True,
        "useDefaultChromeProfile": False,
        "waitForOperatorReadyApproved": True,
        "generatePromptApproved": True,
        "downloadResultApproved": True,
        "watchDownloadsApproved": True,
        "downloadDir": str(downloads),
        "operatorReadyTimeoutSeconds": 600,
    }
    first = client.post("/api/grok-handoff/background-supersede/background-automation", json=stale_request)
    assert first.status_code == 200
    assert first_started.wait(timeout=1)

    restart_request = {
        **stale_request,
        "useDefaultChromeProfile": False,
        "browserProfileDirectory": "Default",
        "supersedeActiveJobApproved": True,
    }
    second = client.post("/api/grok-handoff/background-supersede/background-automation", json=restart_request)
    assert second.status_code == 200
    data = second.get_json()
    assert data["ok"] is True
    assert data["supersededJob"]["cancelRequest"]["jobId"]
    assert data["automationReplay"]["useDefaultChromeProfile"] is False
    assert first_cancelled.is_set()

    status_data = None
    for _ in range(50):
        status_data = client.get("/api/grok-handoff/background-supersede/status").get_json()
        if status_data.get("automationJob", {}).get("status") == "completed":
            break
        time.sleep(0.02)
    assert len(calls) >= 2
    assert calls[0]["data"]["useDefaultChromeProfile"] is False
    assert calls[1]["data"]["useDefaultChromeProfile"] is False
    assert calls[1]["data"]["browserProfileDirectory"] == "Default"
    assert status_data["automationStatus"]["useDefaultChromeProfile"] is False
    assert status_data["automationJob"]["automationReplay"]["useDefaultChromeProfile"] is False


def test_grok_background_error_marks_default_chrome_profile_not_supported():
    status = routes_grok._build_automation_status(
        "debug-required",
        {"sceneId": "scene-01", "expectedFileName": "scene-01.grok.mp4"},
        {
            "browserAutomationMode": "operator-approved-cdp-background-generate-download-watch",
            "requiresOperatorAction": True,
            "browserBlocker": routes_grok.CHROME_DEFAULT_PROFILE_CDP_BLOCKER,
            "operatorNextAction": "Use the isolated Video Studio Grok browser profile.",
        },
        error=routes_grok.CHROME_DEFAULT_PROFILE_CDP_GUIDANCE,
    )

    assert status["status"] == "failed"
    assert status["requiresOperatorAction"] is True
    assert status["browserBlocker"] == routes_grok.CHROME_DEFAULT_PROFILE_CDP_BLOCKER
    assert "isolated" in status["operatorNextAction"]


def test_grok_background_error_routes_socket_abort_to_companion_path():
    error_state = routes_grok._automation_error_state(
        "[WinError 10053] 현재 연결은 사용자의 호스트 시스템의 소프트웨어의 의해 중단되었습니다",
        port=9222,
    )
    status = routes_grok._build_automation_status(
        "socket-abort",
        {"sceneId": "scene-01", "expectedFileName": "scene-01.grok.mp4"},
        {
            "browserAutomationMode": "operator-approved-cdp-background-generate-download-watch",
            "remoteDebuggingPort": 9222,
            "useDefaultChromeProfile": True,
            "attachDefaultChromeApproved": True,
            **error_state,
        },
        error="[WinError 10053] 현재 연결은 사용자의 호스트 시스템의 소프트웨어의 의해 중단되었습니다",
    )

    assert status["status"] == "failed"
    assert status["requiresOperatorAction"] is True
    assert status["browserBlocker"] == routes_grok.CHROME_DEFAULT_PROFILE_SOCKET_ABORT_BLOCKER
    assert "existing signed-in Chrome profile" in status["operatorNextAction"]
    assert "operator then saves/downloads the MP4" in status["operatorNextAction"]
    assert "Edge/new profile" in status["operatorNextAction"]


def test_grok_status_enriches_stale_socket_abort_status(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "stale-socket-abort",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Same presenter steps into a Seoul subway platform as train lights move behind them.",
                    "duration": 4,
                }
            ],
        },
    )
    handoff_dir = tmp_path / "storage" / "grok-handoffs" / "stale-socket-abort"
    (handoff_dir / "automation-status.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "sceneId": "scene-01",
                "expectedFileName": "scene-01.grok.mp4",
                "error": "[WinError 10053] 현재 연결은 사용자의 호스트 시스템의 소프트웨어의 의해 중단되었습니다",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (handoff_dir / "automation-request.json").write_text(
        json.dumps(
            {
                "projectId": "stale-socket-abort",
                "sceneId": "scene-01",
                "remoteDebuggingPort": 9222,
                "useDefaultChromeProfile": True,
            }
        ),
        encoding="utf-8",
    )

    status = client.get("/api/grok-handoff/stale-socket-abort/status").get_json()

    assert status["automationStatus"]["status"] == "failed"
    assert status["automationStatus"]["requiresOperatorAction"] is True
    assert status["automationStatus"]["browserBlocker"] == routes_grok.CHROME_DEFAULT_PROFILE_SOCKET_ABORT_BLOCKER
    assert "existing signed-in Chrome profile" in status["automationStatus"]["operatorNextAction"]
    assert "operator then saves/downloads the MP4" in status["automationStatus"]["operatorNextAction"]
    assert status["operatorNextAction"] == status["manualPrimaryPath"]["operatorNextAction"]
    assert "direct browser-control" in status["operatorNextAction"]
    assert "Downloads import or batch upload" in status["operatorNextAction"]
    assert status["browserControlPrimaryRail"]["mode"] == "existing-signed-in-chrome-browser-control-primary"
    assert status["manualPrimaryPath"]["automationNextAction"] == status["automationStatus"]["operatorNextAction"]


def test_grok_background_automation_can_target_next_missing_scene(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "background-next",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "First Grok scene.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Second Grok scene.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = tmp_path / "storage" / "grok-handoffs" / "background-next" / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / "scene-01.grok.mp4").write_bytes(b"fake scene one")

    status_response = client.get("/api/grok-handoff/background-next/status")
    status_data = status_response.get_json()
    assert status_data["missingSceneIds"] == ["scene-02"]
    assert status_data["nextMissingSceneId"] == "scene-02"
    assert status_data["nextMissingExpectedFileName"] == "scene-02.grok.mp4"

    calls = []

    def fake_browser_automation(_handoff_dir, _manifest, scene, data, download_dir):
        calls.append({"scene": scene, "data": data, "downloadDir": download_dir})
        return {
            "ok": True,
            "browserAutomationMode": "fake-background",
            "filledSceneId": scene["sceneId"],
            "promptInjected": True,
            "generatePromptRequested": data["generatePromptApproved"],
            "generateRequested": True,
            "downloadResultRequested": data["downloadResultApproved"],
            "watchDownloadsRequested": data["watchDownloadsApproved"],
            "readyScenes": 1,
            "totalScenes": 2,
            "allReady": False,
        }

    monkeypatch.setattr(routes_grok, "_run_grok_browser_automation", fake_browser_automation)
    response = client.post(
        "/api/grok-handoff/background-next/background-automation",
        json={
            "sceneId": "__next_missing__",
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "launchBrowserApproved": True,
            "profileApproved": True,
            "waitForOperatorReadyApproved": True,
            "generatePromptApproved": True,
            "downloadResultApproved": True,
            "watchDownloadsApproved": True,
            "downloadDir": str(downloads),
            "operatorReadyTimeoutSeconds": 600,
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["sceneId"] == "scene-02"
    assert data["automationReplay"]["sceneId"] == "scene-02"

    for _ in range(50):
        status_data = client.get("/api/grok-handoff/background-next/status").get_json()
        if status_data.get("automationJob", {}).get("status") == "completed":
            break
        time.sleep(0.02)
    assert calls
    assert calls[0]["scene"]["sceneId"] == "scene-02"
    assert status_data["automationJob"]["sceneId"] == "scene-02"


def test_grok_background_automation_requires_approval(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "background-approval",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )

    response = client.post("/api/grok-handoff/background-approval/background-automation", json={})

    assert response.status_code == 403
    assert "operatorApproved=true" in response.get_json()["error"]


def test_grok_browser_automation_requires_download_dir_for_download_or_watch(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "browser-download-dir",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Scene prompt.",
                    "duration": 4,
                }
            ],
        },
    )

    called = False

    def fake_browser_automation(*args, **kwargs):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr(routes_grok, "_run_grok_browser_automation", fake_browser_automation)

    response = client.post(
        "/api/grok-handoff/browser-download-dir/browser-automation",
        json={
            "sceneId": "scene-01",
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "downloadResultApproved": True,
        },
    )

    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    assert "downloadDir is required" in data["error"]
    assert called is False


def test_grok_browser_automation_passes_generate_download_watch_approvals(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "browser-generate-watch",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )
    captured = {}

    def fake_browser_automation(handoff_dir, manifest, scene, data, download_dir):
        captured["data"] = data
        captured["downloadDir"] = download_dir
        return {
            "ok": True,
            "browserAutomationMode": "fake-generate-download-watch",
            "filledSceneId": scene["sceneId"],
            "promptInjected": True,
            "generatePromptRequested": data["generatePromptApproved"],
            "generateRequested": True,
            "generateAction": "button-click",
            "downloadResultRequested": data["downloadResultApproved"],
            "downloadClick": {"clicked": True, "action": "download-click"},
            "watchDownloadsRequested": data["watchDownloadsApproved"],
            "manualDownloadInstruction": None,
            "imported": [{"sceneId": "scene-01", "fileName": "scene-01.grok.mp4"}],
            "assets": [{"sceneId": "scene-01", "status": "ready"}],
            "readyScenes": 1,
            "totalScenes": 1,
            "allReady": True,
            "renderPayload": {"ok": True, "allReady": True},
        }

    monkeypatch.setattr(routes_grok, "_run_grok_browser_automation", fake_browser_automation)

    response = client.post(
        "/api/grok-handoff/browser-generate-watch/browser-automation",
        json={
            "sceneId": "scene-01",
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "generatePromptApproved": True,
            "downloadResultApproved": True,
            "watchDownloadsApproved": True,
            "downloadClickTimeoutSeconds": 90,
            "watchTimeoutSeconds": 120,
            "watchPollIntervalSeconds": 2,
            "downloadDir": str(downloads),
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["generateRequested"] is True
    assert data["downloadClick"]["clicked"] is True
    assert data["watchDownloadsRequested"] is True
    assert data["renderPayload"]["allReady"] is True
    assert captured["data"]["generatePromptApproved"] is True
    assert captured["data"]["downloadResultApproved"] is True
    assert captured["data"]["watchDownloadsApproved"] is True
    assert captured["downloadDir"] == downloads.resolve()


def test_grok_manual_download_instruction_names_expected_file(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    instruction = routes_grok._manual_download_instruction(
        {"sceneId": "scene-03", "expectedFileName": "scene-03.grok.mp4"},
        downloads,
    )

    assert "scene-03.grok.mp4" in instruction
    assert str(downloads) in instruction
    assert "watcher/importer" in instruction


def test_grok_browser_automation_surfaces_manual_download_fallback(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "browser-fallback",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic product reveal.",
                    "duration": 4,
                }
            ],
        },
    )

    def fake_browser_automation(handoff_dir, manifest, scene, data, download_dir):
        instruction = routes_grok._manual_download_instruction(scene, download_dir)
        return {
            "ok": True,
            "browserAutomationMode": "fake-generate-download-watch",
            "filledSceneId": scene["sceneId"],
            "promptInjected": True,
            "generateRequested": True,
            "downloadResultRequested": True,
            "downloadClick": {
                "clicked": False,
                "reason": "No explicit video download control found before timeout",
                "authRequired": False,
                "cookieChoiceRequired": False,
            },
            "watchDownloadsRequested": True,
            "timedOut": True,
            "readyScenes": 0,
            "totalScenes": 1,
            "allReady": False,
            "manualDownloadInstruction": instruction,
            "operatorNextAction": f"{instruction} Then click Downloads 가져오기 or 승인 생성+감시 again.",
        }

    monkeypatch.setattr(routes_grok, "_run_grok_browser_automation", fake_browser_automation)

    response = client.post(
        "/api/grok-handoff/browser-fallback/browser-automation",
        json={
            "sceneId": "scene-01",
            "operatorApproved": True,
            "browserAutomationApproved": True,
            "generatePromptApproved": True,
            "downloadResultApproved": True,
            "watchDownloadsApproved": True,
            "downloadDir": str(downloads),
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["downloadClick"]["clicked"] is False
    assert "No explicit video download control" in data["downloadClick"]["reason"]
    assert "scene-01.grok.mp4" in data["manualDownloadInstruction"]
    assert "Downloads" in data["operatorNextAction"]


def test_grok_browser_state_from_actions_surfaces_operator_blockers():
    state = routes_grok._browser_state_from_actions(
        {"authRequired": True, "cookieChoiceRequired": False},
        {"authRequired": False, "cookieChoiceRequired": True},
    )

    assert state["authRequired"] is True
    assert state["cookieChoiceRequired"] is True
    assert state["browserBlocker"] == "grok-auth-and-cookie"
    assert state["requiresOperatorAction"] is True


def test_grok_browser_state_from_actions_allows_ready_browser():
    state = routes_grok._browser_state_from_actions(
        {"authRequired": False, "cookieChoiceRequired": False},
    )

    assert state["authRequired"] is False
    assert state["cookieChoiceRequired"] is False
    assert state["browserBlocker"] is None
    assert state["requiresOperatorAction"] is False


def test_grok_browser_preflight_script_reports_ready_and_blocker_fields():
    script = routes_grok._browser_preflight_script()

    assert "promptInputReady" in script
    assert "Date.now() + 8000" in script
    assert "about:blank" in script
    assert "generateControlReady" in script
    assert "downloadControlReady" in script
    assert "authRequired" in script
    assert "cookieChoiceRequired" in script
    assert "동영상 만들기" in script
    assert "동영상 저장" in script


def test_grok_browser_generation_download_scripts_are_guarded_actions():
    generation_script = routes_grok._generation_click_script()
    download_script = routes_grok._download_click_script(1.5)

    assert "No explicit Generate/Send button found" in generation_script
    assert "enter-key" not in generation_script
    assert "동영상 만들기" in generation_script
    assert "authRequired" in generation_script
    assert "cookieChoiceRequired" in generation_script
    assert "native-download-prompt-disabled" in download_script
    assert "download-click-blocked" in download_script
    assert "Download/Save/Export automation and Downloads watcher fallback are disabled" in download_script
    assert ".click()" not in download_script
    assert "1500" in download_script


def test_grok_browser_automation_rejects_download_prompt_flags(tmp_path):
    with pytest.raises(RuntimeError, match="Download/Save/Export automation"):
        routes_grok._run_grok_browser_automation(
            tmp_path,
            {"projectId": "download-prompt-block"},
            {"sceneId": "scene-01", "prompt": "Scene prompt"},
            {"downloadResultApproved": True, "watchDownloadsApproved": True},
            tmp_path,
        )


def test_grok_handoff_shot_bible_keeps_multi_scene_continuity(tmp_path):
    client = _grok_test_client(tmp_path)

    response = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "shot-bible",
            "prompt": "One premium cafe ritual with warm amber light and the same white ceramic cup.",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "title": "Steam hero",
                    "image_source": "grok",
                    "grok_prompt": "Macro espresso steam rising from a white ceramic cup.",
                    "continuity_note": "Same white cup, same wooden counter, same warm amber morning light.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "title": "Pour continuation",
                    "image_source": "grok",
                    "grok_prompt": "Close-up latte pour into the same white ceramic cup.",
                    "continuity_note": "Same cup and counter; match the macro lens and warm amber light.",
                    "duration": 4,
                },
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    for scene in data["scenes"]:
        assert scene["promptQuality"]["status"] == "ready"
        for take in scene["takePrompts"]:
            assert take["promptQuality"]["status"] == "ready"
            assert take["promptQuality"]["brokenPromptFragments"] == []
            assert take["promptQuality"]["checks"]["completeSentences"] is True
    manifest = json.loads(Path(data["manifestPath"]).read_text(encoding="utf-8"))
    shot_bible = manifest["shotBible"]
    assert "same white ceramic cup" in shot_bible["subjectContinuity"]
    assert "warm amber" in shot_bible["locationContinuity"]
    assert shot_bible["negativePrompts"] == [
        "no captions",
        "no logos",
        "no watermark",
        "no baked-in text",
        "no explanatory title card",
        "no UI overlay",
        "no flicker",
        "no morphing faces or objects",
        "no random extra characters",
        "no unrelated stock-looking insert",
        "no ad-like product packshot unless the scene explicitly requires it",
    ]
    assert len(shot_bible["sceneIntents"]) == 2
    for scene in manifest["scenes"]:
        assert "first second:" in scene["prompt"]
        assert "Vertical 9:16 phone MP4" in scene["prompt"]
        assert "uncluttered lower-right background" in scene["prompt"]
        assert "no visible text or watermark" in scene["prompt"]
        assert "same recurring subject" not in scene["prompt"]
        assert "no unrelated cutaways" not in scene["prompt"]
        assert any(item.startswith("Operator can explain") for item in scene["operatorChecklist"])
        assert any("safe zones" in item for item in scene["operatorChecklist"])
    worksheet = Path(data["worksheetPath"]).read_text(encoding="utf-8")
    assert "Scene intents" in worksheet
    assert "scene-02.grok.mp4" in worksheet


def test_grok_handoff_import_downloads_requires_operator_approval(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "import-approval",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                }
            ],
        },
    )
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    assert created.status_code == 200

    response = client.post(
        "/api/grok-handoff/import-approval/import-downloads",
        json={"downloadDir": str(downloads)},
    )

    assert response.status_code == 403
    data = response.get_json()
    assert data["ok"] is False
    assert "operatorApproved" in data["error"]


def test_grok_handoff_import_downloads_copies_newest_mp4s_into_incoming(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "import-downloads",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic latte pour continuation.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    first = downloads / "grok-random-a.mp4"
    second = downloads / "grok-random-b.mp4"
    first.write_bytes(b"first grok mp4")
    second.write_bytes(b"second grok mp4")
    os.utime(first, (1000, 1000))
    os.utime(second, (1001, 1001))

    response = client.post(
        "/api/grok-handoff/import-downloads/import-downloads",
        json={
            "downloadDir": str(downloads),
            "operatorApproved": True,
            "allowNewestFallback": True,
            "sinceHandoff": False,
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["allReady"] is True
    assert data["reviewPacketUrl"].endswith("/api/grok-handoff/import-downloads/review-packet")
    assert [item["sceneId"] for item in data["imported"]] == ["scene-01", "scene-02"]
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"first grok mp4"
    assert (incoming / "scene-02.grok.mp4").read_bytes() == b"second grok mp4"
    manifest = json.loads((tmp_path / "storage" / "grok-handoffs" / "import-downloads" / "handoff.json").read_text(encoding="utf-8"))
    assert manifest["importHistory"][0]["downloadDir"] == str(downloads)
    assert manifest["importHistory"][0]["allowNewestFallback"] is True


def test_grok_handoff_import_downloads_can_target_one_scene(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "import-one-scene",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "First hero.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Second hero.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    candidate = downloads / "grok-random-scene-two.mp4"
    candidate.write_bytes(b"second scene only")

    response = client.post(
        "/api/grok-handoff/import-one-scene/import-downloads",
        json={
            "sceneId": "scene-02",
            "downloadDir": str(downloads),
            "operatorApproved": True,
            "allowNewestFallback": True,
            "sinceHandoff": False,
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert [item["sceneId"] for item in data["imported"]] == ["scene-02"]
    assert not (incoming / "scene-01.grok.mp4").exists()
    assert (incoming / "scene-02.grok.mp4").read_bytes() == b"second scene only"
    manifest = json.loads((tmp_path / "storage" / "grok-handoffs" / "import-one-scene" / "handoff.json").read_text(encoding="utf-8"))
    assert manifest["importHistory"][0]["sceneId"] == "scene-02"


def test_grok_handoff_upload_mp4_imports_browser_selected_scene_candidate(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-upload",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same worker opens a red notebook beside a window.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Same worker closes the red notebook and leaves frame.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])

    denied = client.post(
        "/api/grok-handoff/manual-upload/upload-mp4",
        json={
            "sceneId": "scene-01",
            "fileName": "scene-01-from-grok.mp4",
            "fileBase64": base64.b64encode(b"manual grok mp4").decode("ascii"),
        },
    )
    assert denied.status_code == 403

    response = client.post(
        "/api/grok-handoff/manual-upload/upload-mp4",
        json={
            "operatorApproved": True,
            "sceneId": "scene-01",
            "fileName": "scene-01-from-grok.mp4",
            "fileBase64": base64.b64encode(b"manual grok mp4").decode("ascii"),
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["readyScenes"] == 1
    assert data["totalScenes"] == 2
    assert data["imported"][0]["sceneId"] == "scene-01"
    assert data["imported"][0]["fileName"] == "scene-01.grok.mp4"
    assert data["imported"][0]["importMode"] == "manual-browser-upload"
    assert data["assets"][0]["status"] == "ready"
    assert data["assets"][0]["candidateAssets"][0]["fileName"] == "scene-01.grok.mp4"
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"manual grok mp4"
    manifest = json.loads((tmp_path / "storage" / "grok-handoffs" / "manual-upload" / "handoff.json").read_text(encoding="utf-8"))
    assert manifest["importHistory"][0]["importMode"] == "manual-browser-upload"
    assert manifest["importHistory"][0]["uploadedFileName"] == "scene-01-from-grok.mp4"

    second = client.post(
        "/api/grok-handoff/manual-upload/upload-mp4",
        json={
            "operatorApproved": True,
            "sceneId": "scene-01",
            "fileName": "better take.mp4",
            "fileBase64": base64.b64encode(b"better manual grok mp4").decode("ascii"),
            "preserveCandidates": True,
        },
    )
    assert second.status_code == 200
    second_data = second.get_json()
    imported_file = second_data["imported"][0]["fileName"]
    assert imported_file != "scene-01.grok.mp4"
    assert (incoming / imported_file).read_bytes() == b"better manual grok mp4"
    assert [item["fileName"] for item in second_data["assets"][0]["candidateAssets"]] == [
        "scene-01.grok.mp4",
        imported_file,
    ]


def test_grok_handoff_direct_import_bridge_smoke_uses_upload_endpoint_without_download_prompt(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "durationSec": 5.2,
        "aspectRatio": 0.5625,
        "hasAudio": True,
        "motionOk": True,
        "motionStatus": "ok",
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "direct-import-bridge-smoke",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same worker opens the reset routine with a clear moving hook.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Same worker continues the action without changing outfit or room.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])

    command = client.get(
        "/api/grok-handoff/direct-import-bridge-smoke/extension-command"
        "?operatorApproved=true&sceneId=scene-01&take=2"
    )
    assert command.status_code == 200
    command_data = command.get_json()
    assert command_data["sceneId"] == "scene-01"
    assert command_data["expectedFileName"] == "scene-01.grok.mp4"
    assert command_data["uploadEndpoint"].endswith("/api/grok-handoff/direct-import-bridge-smoke/upload-mp4")
    assert command_data["eventEndpoint"].endswith("/api/grok-handoff/direct-import-bridge-smoke/extension-event")

    upload_path = urllib.parse.urlparse(command_data["uploadEndpoint"]).path
    upload_preflight = client.open(upload_path, method="OPTIONS")
    assert upload_preflight.status_code == 200
    assert upload_preflight.headers["Access-Control-Allow-Origin"] == "*"
    assert "POST" in upload_preflight.headers["Access-Control-Allow-Methods"]
    assert "Content-Type" in upload_preflight.headers["Access-Control-Allow-Headers"]

    uploaded = client.post(
        upload_path,
        json={
            "operatorApproved": True,
            "extensionApproved": True,
            "directImportProof": True,
            "eventType": "companion-direct-import",
            "sceneId": command_data["sceneId"],
            "expectedFileName": command_data["expectedFileName"],
            "fileName": command_data["expectedFileName"],
            "fileBase64": base64.b64encode(b"direct companion original grok mp4 bytes").decode("ascii"),
            "currentUrl": "https://grok.com/imagine",
            "candidateUrl": "https://assets.grok.com/users/user/generated/direct/generated_video.mp4",
            "sourceKind": "companion-direct-fetch",
            "videoWidth": "1080",
            "videoHeight": "1920",
            "qualityFloorMet": "true",
            "qualityNote": "original-download-source; companion-direct-fetch; no-browser-download-prompt",
            "detail": "direct bridge import; browser download manager not used",
            "overwrite": False,
            "preserveCandidates": True,
        },
    )
    assert uploaded.status_code == 200
    uploaded_data = uploaded.get_json()
    assert uploaded_data["ok"] is True
    assert uploaded_data["imported"][0]["sceneId"] == "scene-01"
    assert uploaded_data["imported"][0]["fileName"] == "scene-01.grok.mp4"
    assert uploaded_data["imported"][0]["importMode"] == "manual-browser-upload"
    assert uploaded_data["nextMissingSceneId"] == "scene-02"
    direct_event = uploaded_data["directImportProofEvent"]
    assert direct_event["eventType"] == "companion-direct-import"
    assert direct_event["status"] == "imported"
    assert direct_event["sourceKind"] == "companion-direct-fetch"
    assert direct_event["qualityNote"] == "original-download-source; companion-direct-fetch; no-browser-download-prompt"
    assert direct_event["directImportProof"] is True
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"direct companion original grok mp4 bytes"

    event_path = urllib.parse.urlparse(command_data["eventEndpoint"]).path
    event_log_path = tmp_path / "storage" / "grok-handoffs" / "direct-import-bridge-smoke" / "extension-events.jsonl"
    atomic_events = [
        json.loads(line)
        for line in event_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert atomic_events[-1]["eventType"] == "companion-direct-import"
    assert atomic_events[-1]["source"] == "uploadEndpoint-direct-import"
    assert atomic_events[-1]["expectedFileName"] == "scene-01.grok.mp4"
    assert atomic_events[-1]["candidateUrl"].endswith("/generated/direct/generated_video.mp4")

    status_after_upload = client.get("/api/grok-handoff/direct-import-bridge-smoke/status").get_json()
    assert "latestExtensionEvent" not in status_after_upload
    assert "companionConnection" not in status_after_upload

    event = client.post(
        event_path,
        json={
            "operatorApproved": True,
            "extensionApproved": True,
            "sceneId": command_data["sceneId"],
            "expectedFileName": command_data["expectedFileName"],
            "eventType": "companion-direct-import",
            "status": "imported",
            "detail": "direct bridge import; browser download manager not used",
            "currentUrl": "https://grok.com/imagine",
            "candidateUrl": "https://assets.grok.com/users/user/generated/direct/generated_video.mp4",
            "sourceKind": "companion-direct-fetch",
            "videoWidth": "1080",
            "videoHeight": "1920",
            "qualityFloorMet": "true",
            "qualityNote": "original-download-source; companion-direct-fetch; no-browser-download-prompt",
        },
    )
    assert event.status_code == 200

    status = client.get("/api/grok-handoff/direct-import-bridge-smoke/status").get_json()
    assert "latestExtensionEvent" not in status
    assert "companionConnection" not in status
    assert status["downloadImport"]["nextSceneId"] == "scene-02"
    asset = status["assets"][0]
    provenance = asset["sourceProvenance"]
    assert asset["fileName"] == "scene-01.grok.mp4"
    assert asset["candidateAssets"][0]["sourceProvenance"]["sourceKind"] == "companion-direct-fetch"
    assert provenance["status"] == "browser-native-original-download"
    assert provenance["originalDownloadLikely"] is True
    assert provenance["acceptAsGrokMainSource"] is True
    assert provenance["sourceKind"] == "companion-direct-fetch"
    assert provenance["qualityNote"] == "original-download-source; companion-direct-fetch; no-browser-download-prompt"
    assert asset["qualityGate"]["status"] == "pending-operator-review"

    manifest = json.loads(
        (tmp_path / "storage" / "grok-handoffs" / "direct-import-bridge-smoke" / "handoff.json").read_text(
            encoding="utf-8"
        )
    )
    history = manifest["importHistory"][-1]
    assert history["importMode"] == "manual-browser-upload"
    assert history["downloadDir"] == ""
    assert history["uploadedFileName"] == "scene-01.grok.mp4"


def test_grok_handoff_upload_mp4_records_companion_blob_direct_import_proof(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "durationSec": 6.0,
        "aspectRatio": 0.5625,
        "hasAudio": True,
        "motionOk": True,
        "motionStatus": "ok",
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "companion-blob-direct-import",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same worker opens the reset routine with a clear moving hook.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])

    uploaded = client.post(
        "/api/grok-handoff/companion-blob-direct-import/upload-mp4",
        json={
            "operatorApproved": True,
            "extensionApproved": True,
            "directImportProof": True,
            "eventType": "companion-blob-direct-import",
            "sceneId": "scene-01",
            "expectedFileName": "scene-01.grok.mp4",
            "fileName": "scene-01.grok.mp4",
            "fileBase64": base64.b64encode(b"companion blob grok mp4 bytes").decode("ascii"),
            "currentUrl": "https://grok.com/imagine/post/live-blob",
            "candidateUrl": "blob:https://grok.com/visible-video-candidate",
            "sourceKind": "visible-video-blob-direct-fetch",
            "videoWidth": "720",
            "videoHeight": "1280",
            "qualityFloorMet": "true",
            "qualityNote": "visible-video-floor-met:720x1280; companion-blob-direct-fetch; no-browser-download-prompt",
            "detail": "content blob direct bridge import; bytes=31",
            "overwrite": False,
            "preserveCandidates": True,
        },
    )

    assert uploaded.status_code == 200
    uploaded_data = uploaded.get_json()
    assert uploaded_data["ok"] is True
    assert uploaded_data["imported"][0]["sceneId"] == "scene-01"
    assert uploaded_data["imported"][0]["fileName"] == "scene-01.grok.mp4"
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"companion blob grok mp4 bytes"
    direct_event = uploaded_data["directImportProofEvent"]
    assert direct_event["eventType"] == "companion-blob-direct-import"
    assert direct_event["sourceKind"] == "visible-video-blob-direct-fetch"
    assert direct_event["qualityNote"] == "visible-video-floor-met:720x1280; companion-blob-direct-fetch; no-browser-download-prompt"
    assert direct_event["candidateUrl"].startswith("blob:https://grok.com/")

    status = client.get("/api/grok-handoff/companion-blob-direct-import/status").get_json()
    assert "latestExtensionEvent" not in status
    provenance = status["assets"][0]["sourceProvenance"]
    assert provenance["status"] == "browser-native-original-download"
    assert provenance["acceptAsGrokMainSource"] is True
    assert provenance["sourceKind"] == "visible-video-blob-direct-fetch"


def test_grok_handoff_upload_mp4_records_chrome_pageassets_direct_import_proof(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "durationSec": 6.0,
        "aspectRatio": 0.5625,
        "hasAudio": True,
        "motionOk": True,
        "motionStatus": "ok",
        "issues": [],
    })
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "chrome-pageassets-direct-import",
            "qualityGateRequired": True,
            "grokMainSourceRequired": True,
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same worker opens the reset routine with a clear moving hook.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])

    uploaded = client.post(
        "/api/grok-handoff/chrome-pageassets-direct-import/upload-mp4",
        json={
            "operatorApproved": True,
            "directImportProof": True,
            "eventType": "codex-chrome-page-assets-direct-import",
            "sceneId": "scene-01",
            "expectedFileName": "scene-01.grok.mp4",
            "fileName": "2ba3c820-c228-4e5b-9b97-b967dd568809.mp4",
            "fileBase64": base64.b64encode(b"chrome page assets grok mp4 bytes").decode("ascii"),
            "currentUrl": "https://grok.com/imagine/post/2ba3c820-c228-4e5b-9b97-b967dd568809",
            "candidateUrl": "https://imagine-public.x.ai/imagine-public/share-videos/2ba3c820-c228-4e5b-9b97-b967dd568809.mp4",
            "sourceKind": "codex-chrome-page-assets-direct-fetch",
            "videoWidth": "720",
            "videoHeight": "1280",
            "qualityFloorMet": "true",
            "qualityNote": "original-download-source; codex-chrome-page-assets-direct-fetch; no-browser-download-prompt",
            "detail": "Chrome pageAssets bundle imported the rendered Grok post MP4 without Chrome Download UI",
            "overwrite": True,
            "preserveCandidates": False,
        },
    )

    assert uploaded.status_code == 200
    uploaded_data = uploaded.get_json()
    assert uploaded_data["ok"] is True
    assert uploaded_data["imported"][0]["sceneId"] == "scene-01"
    assert uploaded_data["imported"][0]["fileName"] == "scene-01.grok.mp4"
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"chrome page assets grok mp4 bytes"
    direct_event = uploaded_data["directImportProofEvent"]
    assert direct_event["eventType"] == "codex-chrome-page-assets-direct-import"
    assert direct_event["sourceKind"] == "codex-chrome-page-assets-direct-fetch"
    assert direct_event["qualityNote"] == "original-download-source; codex-chrome-page-assets-direct-fetch; no-browser-download-prompt"
    assert direct_event["candidateUrl"].startswith("https://imagine-public.x.ai/")

    status = client.get("/api/grok-handoff/chrome-pageassets-direct-import/status").get_json()
    assert "latestExtensionEvent" not in status
    provenance = status["assets"][0]["sourceProvenance"]
    assert provenance["status"] == "browser-native-original-download"
    assert provenance["acceptAsGrokMainSource"] is True
    assert provenance["sourceKind"] == "codex-chrome-page-assets-direct-fetch"


def test_grok_handoff_upload_mp4_batch_maps_multiple_scene_files(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-upload-batch",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same worker starts the morning reset.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Same worker pours water into a glass.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-03",
                    "scene_num": 3,
                    "image_source": "grok",
                    "grok_prompt": "Same worker closes the laptop.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])

    denied = client.post(
        "/api/grok-handoff/manual-upload-batch/upload-mp4-batch",
        json={"files": []},
    )
    assert denied.status_code == 403

    response = client.post(
        "/api/grok-handoff/manual-upload-batch/upload-mp4-batch",
        json={
            "operatorApproved": True,
            "files": [
                {
                    "fileName": "scene-01-supergrok.mp4",
                    "fileBase64": base64.b64encode(b"scene one grok").decode("ascii"),
                },
                {
                    "sceneId": "scene-03",
                    "fileName": "alternate take.mp4",
                    "fileBase64": base64.b64encode(b"scene three grok").decode("ascii"),
                },
                {
                    "fileName": "scene-02-supergrok.mp4",
                    "fileBase64": base64.b64encode(b"scene two grok").decode("ascii"),
                },
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["readyScenes"] == 3
    assert data["allReady"] is True
    assert [item["sceneId"] for item in data["imported"]] == ["scene-01", "scene-03", "scene-02"]
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"scene one grok"
    assert (incoming / "scene-02.grok.mp4").read_bytes() == b"scene two grok"
    assert (incoming / "scene-03.grok.mp4").read_bytes() == b"scene three grok"
    manifest = json.loads((tmp_path / "storage" / "grok-handoffs" / "manual-upload-batch" / "handoff.json").read_text(encoding="utf-8"))
    assert manifest["importHistory"][-1]["importMode"] == "manual-browser-upload-batch"
    assert [item["sceneId"] for item in manifest["importHistory"][-1]["uploadedFiles"]] == ["scene-01", "scene-03", "scene-02"]


def test_grok_handoff_upload_mp4_batch_prefers_scene_order_for_generic_full_batch(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-upload-generic-full-batch",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same worker steps out of the subway.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Same worker unlocks a studio room.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-03",
                    "scene_num": 3,
                    "image_source": "grok",
                    "grok_prompt": "Same worker turns on a warm desk lamp.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])

    response = client.post(
        "/api/grok-handoff/manual-upload-generic-full-batch/upload-mp4-batch",
        json={
            "operatorApproved": True,
            "files": [
                {
                    "sceneId": "scene-03",
                    "fileName": "Grok Download 1.mp4",
                    "fileBase64": base64.b64encode(b"scene one generic grok").decode("ascii"),
                },
                {
                    "sceneId": "scene-01",
                    "fileName": "Grok Download 2.mp4",
                    "fileBase64": base64.b64encode(b"scene two generic grok").decode("ascii"),
                },
                {
                    "sceneId": "scene-02",
                    "fileName": "Grok Download 3.mp4",
                    "fileBase64": base64.b64encode(b"scene three generic grok").decode("ascii"),
                },
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert [item["sceneId"] for item in data["imported"]] == ["scene-01", "scene-02", "scene-03"]
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"scene one generic grok"
    assert (incoming / "scene-02.grok.mp4").read_bytes() == b"scene two generic grok"
    assert (incoming / "scene-03.grok.mp4").read_bytes() == b"scene three generic grok"
    manifest = json.loads(
        (tmp_path / "storage" / "grok-handoffs" / "manual-upload-generic-full-batch" / "handoff.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["importHistory"][-1]["sceneMappingMode"] == "scene-order-full-batch"
    assert [item["sceneId"] for item in manifest["importHistory"][-1]["uploadedFiles"]] == [
        "scene-01",
        "scene-02",
        "scene-03",
    ]


def test_grok_handoff_upload_mp4_batch_groups_generic_take_candidates_by_scene(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-upload-generic-take-groups",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same worker opens the apartment door at night.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Same worker sets a warm desk lamp beside a notebook.",
                    "duration": 4,
                },
            ],
        },
    )

    response = client.post(
        "/api/grok-handoff/manual-upload-generic-take-groups/upload-mp4-batch",
        json={
            "operatorApproved": True,
            "preserveCandidates": True,
            "sceneMappingMode": "scene-grouped-takes",
            "files": [
                {
                    "fileName": "Grok Imagine.mp4",
                    "fileBase64": base64.b64encode(b"scene one take one").decode("ascii"),
                },
                {
                    "fileName": "Grok Imagine (1).mp4",
                    "fileBase64": base64.b64encode(b"scene one take two").decode("ascii"),
                },
                {
                    "fileName": "Grok Imagine (2).mp4",
                    "fileBase64": base64.b64encode(b"scene two take one").decode("ascii"),
                },
                {
                    "fileName": "Grok Imagine (3).mp4",
                    "fileBase64": base64.b64encode(b"scene two take two").decode("ascii"),
                },
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert [item["sceneId"] for item in data["imported"]] == ["scene-01", "scene-01", "scene-02", "scene-02"]
    assets = {item["sceneId"]: item for item in data["assets"]}
    assert [item["fileName"] for item in assets["scene-01"]["candidateAssets"]] == [
        "scene-01.grok.mp4",
        "scene-01-grok-imagine-1.mp4",
    ]
    assert [item["fileName"] for item in assets["scene-02"]["candidateAssets"]] == [
        "scene-02.grok.mp4",
        "scene-02-grok-imagine-3.mp4",
    ]
    manifest = json.loads(
        (
            tmp_path
            / "storage"
            / "grok-handoffs"
            / "manual-upload-generic-take-groups"
            / "handoff.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["importHistory"][-1]["sceneMappingMode"] == "scene-grouped-takes"
    assert manifest["importHistory"][-1]["sceneGroupedTakeSize"] == 2


def test_grok_handoff_preserves_and_selects_multiple_scene_candidates(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "candidate-select",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Same worker enters the room at night.",
                    "duration": 4,
                },
            ],
        },
    )

    downloads = tmp_path / "downloads"
    downloads.mkdir()
    first = downloads / "scene-01.grok.mp4"
    first.write_bytes(b"first candidate")
    first_import = client.post(
        "/api/grok-handoff/candidate-select/import-downloads",
        json={
            "operatorApproved": True,
            "sceneId": "scene-01",
            "downloadDir": str(downloads),
            "sinceHandoff": False,
            "overwrite": True,
            "preserveCandidates": True,
        },
    )
    assert first_import.status_code == 200

    second = downloads / "scene-01.grok (1).mp4"
    second.write_bytes(b"second candidate")
    second_import = client.post(
        "/api/grok-handoff/candidate-select/import-downloads",
        json={
            "operatorApproved": True,
            "sceneId": "scene-01",
            "downloadDir": str(downloads),
            "sinceHandoff": False,
            "overwrite": True,
            "preserveCandidates": True,
        },
    )
    assert second_import.status_code == 200
    imported_files = [item["fileName"] for item in second_import.get_json()["imported"]]
    assert imported_files == ["scene-01-grok-1.mp4"]

    status = client.get("/api/grok-handoff/candidate-select/status").get_json()
    asset = status["assets"][0]
    candidate_names = [item["fileName"] for item in asset["candidateAssets"]]
    assert candidate_names == ["scene-01.grok.mp4", "scene-01-grok-1.mp4"]

    review_packet = client.get("/api/grok-handoff/candidate-select/review-packet")
    html = review_packet.get_data(as_text=True)
    assert "Grok candidate selection" in html
    assert "scene-01-grok-1.mp4" in html

    accepted = client.post(
        "/api/grok-handoff/candidate-select/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "selectedFileName": "scene-01-grok-1.mp4",
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "sourceRationale": "Selected the second Grok take because the motion reads better.",
            "qualityReviewNote": "The chosen take has immediate motion, no watermark, no baked-in text, and safe lower framing.",
            "visualQualityVerdict": "pass",
            "captionLayoutReviewNote": "Subject stays above the lower caption-safe zone and away from the right Shorts UI.",
            "continuityNote": "Same worker, same room, same night palette.",
            "hookNote": "The door motion starts in the first two seconds.",
            "layoutVariantKey": "pov-diary",
            "layoutVariantLabel": "POV diary",
            "layoutVariantNote": "Use restrained lower-info or no caption over the selected take.",
            "thumbnailReviewNote": "First frame has a readable doorway action without text overlays.",
            "audioMixReviewNote": "Music-first no-voice bed should sit under native room ambience.",
            "platformComparisonNote": "Closer to Korean routine Shorts than generic stock montage.",
            "selectedCandidateSummary": "Candidate 2 has better motion and fewer artifacts than candidate 1.",
        },
    )
    assert accepted.status_code == 200
    data = accepted.get_json()
    assert data["reviewDecision"]["selectedFileName"] == "scene-01-grok-1.mp4"
    assert data["reviewDecision"]["visualQualityVerdict"] == "pass"
    assert data["reviewDecision"]["selectedCandidate"]["fileName"] == "scene-01-grok-1.mp4"
    assert data["renderPayload"]["sceneAssets"][0]["fileName"] == "scene-01-grok-1.mp4"
    assert data["renderPayload"]["sceneAssets"][0]["sourceOrigin"] == "grok-handoff"
    assert data["renderPayload"]["sceneAssets"][0]["sourceGenerator"] == "grok-app-web-handoff"
    assert data["renderPayload"]["sceneAssets"][0]["candidateCount"] == 2
    rendered_scene = data["renderPayload"]["draftScenes"][0]
    assert rendered_scene["visualQualityVerdict"] == "pass"
    assert rendered_scene["captionLayoutReviewNote"].startswith("Subject stays")
    assert rendered_scene["continuityNote"].startswith("Same worker")
    assert rendered_scene["hookNote"].startswith("The door motion")
    assert rendered_scene["layoutVariantKey"] == "pov-diary"
    assert rendered_scene["thumbnailReviewNote"].startswith("First frame")
    assert rendered_scene["audioMixReviewNote"].startswith("Music-first")
    assert rendered_scene["platformComparisonNote"].startswith("Closer to Korean")
    assert rendered_scene["selectedCandidateSummary"].startswith("Candidate 2")

    selected_status = client.get("/api/grok-handoff/candidate-select/status").get_json()
    selected_asset = selected_status["assets"][0]
    assert selected_asset["fileName"] == "scene-01-grok-1.mp4"
    assert [item["selected"] for item in selected_asset["candidateAssets"]] == [False, True]


def test_grok_handoff_review_decision_rejects_unknown_candidate_file(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "candidate-validate",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "image_source": "grok",
                    "grok_prompt": "Same worker enters the room at night.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = tmp_path / "storage" / "grok-handoffs" / "candidate-validate" / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / "scene-01.grok.mp4").write_bytes(b"first candidate")

    response = client.post(
        "/api/grok-handoff/candidate-validate/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": True,
            "selectedFileName": "not-imported.mp4",
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
        },
    )

    assert response.status_code == 400
    assert "selectedFileName" in response.get_json()["error"]


def test_grok_handoff_watch_downloads_waits_and_returns_render_payload(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "watch-downloads",
            "prompt": "Grok watched reel",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "title": "Steam hero",
                    "narration": "The first generated clip carries the hook.",
                    "display_text": "Steam first",
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                    "caption_preset": "top-hook",
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    def delayed_download() -> None:
        time.sleep(0.15)
        (downloads / "scene-01.grok.mp4").write_bytes(b"watched grok mp4")

    thread = threading.Thread(target=delayed_download)
    thread.start()
    try:
        response = client.post(
            "/api/grok-handoff/watch-downloads/watch-downloads",
            json={
                "downloadDir": str(downloads),
                "operatorApproved": True,
                "timeoutSeconds": 2,
                "pollIntervalSeconds": 0.05,
            },
        )
    finally:
        thread.join(timeout=2)

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["allReady"] is True
    assert data["timedOut"] is False
    assert data["reviewPacketUrl"].endswith("/api/grok-handoff/watch-downloads/review-packet")
    assert data["attempts"] >= 2
    assert data["renderPayload"]["allReady"] is True
    scene_asset = data["renderPayload"]["sceneAssets"][0]
    assert scene_asset["sceneId"] == "scene-01"
    assert scene_asset["role"] == "visual"
    assert scene_asset["fileName"] == "scene-01.grok.mp4"
    assert scene_asset["mimeType"] == "video/mp4"
    assert scene_asset["sourcePath"] == "storage/grok-handoffs/watch-downloads/incoming/scene-01.grok.mp4"
    assert scene_asset["sourceOrigin"] == "grok-handoff"
    assert scene_asset["sourceGenerator"] == "grok-app-web-handoff"
    assert scene_asset["candidateCount"] == 1
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"watched grok mp4"
    manifest = json.loads((tmp_path / "storage" / "grok-handoffs" / "watch-downloads" / "handoff.json").read_text(encoding="utf-8"))
    assert manifest["watchHistory"][0]["allReady"] is True
    assert manifest["watchHistory"][0]["attempts"] >= 2


def test_grok_handoff_watch_downloads_can_target_one_scene(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "watch-one-scene",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "First hero.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Second hero.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    def delayed_download() -> None:
        time.sleep(0.15)
        (downloads / "grok-random-download.mp4").write_bytes(b"second scene watched")

    thread = threading.Thread(target=delayed_download)
    thread.start()
    try:
        response = client.post(
            "/api/grok-handoff/watch-one-scene/watch-downloads",
            json={
                "sceneId": "scene-02",
                "downloadDir": str(downloads),
                "operatorApproved": True,
                "allowNewestFallback": True,
                "sinceHandoff": False,
                "timeoutSeconds": 2,
                "pollIntervalSeconds": 0.05,
            },
        )
    finally:
        thread.join(timeout=2)

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert [item["sceneId"] for item in data["imported"]] == ["scene-02"]
    assert data["allReady"] is False
    assert not (incoming / "scene-01.grok.mp4").exists()
    assert (incoming / "scene-02.grok.mp4").read_bytes() == b"second scene watched"
    manifest = json.loads((tmp_path / "storage" / "grok-handoffs" / "watch-one-scene" / "handoff.json").read_text(encoding="utf-8"))
    assert manifest["watchHistory"][0]["sceneId"] == "scene-02"


def test_grok_handoff_watch_downloads_requires_operator_approval(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "watch-approval",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                }
            ],
        },
    )
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    response = client.post(
        "/api/grok-handoff/watch-approval/watch-downloads",
        json={"downloadDir": str(downloads)},
    )

    assert response.status_code == 403
    data = response.get_json()
    assert data["ok"] is False
    assert "operatorApproved" in data["error"]


def test_grok_handoff_manual_download_watch_job_imports_current_scene(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-watch-job",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "First Grok hero.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Second Grok hero.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    def delayed_download() -> None:
        time.sleep(0.15)
        (downloads / "grok-download-random-name.mp4").write_bytes(b"manual grok scene 02 mp4")

    thread = threading.Thread(target=delayed_download)
    thread.start()
    try:
        response = client.post(
            "/api/grok-handoff/manual-watch-job/manual-download-watch",
            json={
                "sceneId": "scene-02",
                "downloadDir": str(downloads),
                "operatorApproved": True,
                "allowNewestFallback": True,
                "sinceHandoff": False,
                "timeoutSeconds": 2,
                "pollIntervalSeconds": 0.05,
                "stopOnImport": True,
            },
        )
        assert response.status_code == 200
        start_data = response.get_json()
        assert start_data["ok"] is True
        assert start_data["manualDownloadWatchJob"]["status"] in {"queued", "running"}

        final_job = None
        deadline = time.time() + 3
        while time.time() < deadline:
            status_response = client.get("/api/grok-handoff/manual-watch-job/manual-download-watch")
            assert status_response.status_code == 200
            final_job = status_response.get_json()["manualDownloadWatchJob"]
            if final_job and final_job["status"] in {"imported", "timed-out", "failed"}:
                break
            time.sleep(0.05)
    finally:
        thread.join(timeout=2)

    assert final_job is not None
    assert final_job["status"] == "imported"
    assert final_job["sceneId"] == "scene-02"
    assert final_job["importedCount"] == 1
    assert final_job["timedOut"] is False
    assert not (incoming / "scene-01.grok.mp4").exists()
    assert (incoming / "scene-02.grok.mp4").read_bytes() == b"manual grok scene 02 mp4"

    status_data = client.get("/api/grok-handoff/manual-watch-job/status").get_json()
    assert status_data["manualDownloadWatchJob"]["status"] == "imported"
    assert status_data["assets"][1]["sceneId"] == "scene-02"
    assert status_data["assets"][1]["status"] == "ready"


def test_grok_handoff_manual_download_watch_ignores_files_before_start(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-watch-start-cutoff",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "First Grok hero.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "old-grok-export.mp4").write_bytes(b"stale pre-watch mp4")

    def delayed_download() -> None:
        time.sleep(0.15)
        (downloads / "fresh-grok-export.mp4").write_bytes(b"fresh post-watch mp4")

    thread = threading.Thread(target=delayed_download)
    thread.start()
    try:
        response = client.post(
            "/api/grok-handoff/manual-watch-start-cutoff/manual-download-watch",
            json={
                "sceneId": "scene-01",
                "downloadDir": str(downloads),
                "operatorApproved": True,
                "allowNewestFallback": True,
                "timeoutSeconds": 2,
                "pollIntervalSeconds": 0.05,
                "stopOnImport": True,
            },
        )
        assert response.status_code == 200

        final_job = None
        deadline = time.time() + 3
        while time.time() < deadline:
            status_response = client.get("/api/grok-handoff/manual-watch-start-cutoff/manual-download-watch")
            assert status_response.status_code == 200
            final_job = status_response.get_json()["manualDownloadWatchJob"]
            if final_job and final_job["status"] in {"imported", "timed-out", "failed"}:
                break
            time.sleep(0.05)
    finally:
        thread.join(timeout=2)

    assert final_job is not None
    assert final_job["status"] == "imported"
    assert final_job["importedCount"] == 1
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"fresh post-watch mp4"
    manifest = json.loads((tmp_path / "storage" / "grok-handoffs" / "manual-watch-start-cutoff" / "handoff.json").read_text(encoding="utf-8"))
    assert manifest["watchHistory"][-1]["watchStartedAfterEpoch"] is not None
    assert manifest["watchHistory"][-1]["imported"][0]["originalPath"].endswith("fresh-grok-export.mp4")


def test_grok_handoff_manual_download_watch_imports_stable_tmp_mp4(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-watch-tmp-mp4",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Grok saved as a temporary Chrome file.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    tmp_payload = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"grok tmp mp4"

    def delayed_tmp_download() -> None:
        time.sleep(0.15)
        (downloads / "baea48be-062f-4b77-ab07-2dec1a2a5bf1.tmp").write_bytes(tmp_payload)

    thread = threading.Thread(target=delayed_tmp_download)
    thread.start()
    try:
        response = client.post(
            "/api/grok-handoff/manual-watch-tmp-mp4/manual-download-watch",
            json={
                "sceneId": "scene-01",
                "downloadDir": str(downloads),
                "operatorApproved": True,
                "allowNewestFallback": True,
                "timeoutSeconds": 2,
                "pollIntervalSeconds": 0.05,
                "stopOnImport": True,
            },
        )
        assert response.status_code == 200

        final_job = None
        deadline = time.time() + 3
        while time.time() < deadline:
            status_response = client.get("/api/grok-handoff/manual-watch-tmp-mp4/manual-download-watch")
            assert status_response.status_code == 200
            final_job = status_response.get_json()["manualDownloadWatchJob"]
            if final_job and final_job["status"] in {"imported", "timed-out", "failed"}:
                break
            time.sleep(0.05)
    finally:
        thread.join(timeout=2)

    assert final_job is not None
    assert final_job["status"] == "imported"
    assert final_job["importedCount"] == 1
    assert (incoming / "scene-01.grok.mp4").read_bytes() == tmp_payload
    manifest = json.loads((tmp_path / "storage" / "grok-handoffs" / "manual-watch-tmp-mp4" / "handoff.json").read_text(encoding="utf-8"))
    assert manifest["watchHistory"][-1]["imported"][0]["originalPath"].endswith(".tmp")


def test_grok_handoff_manual_download_watch_overwrites_existing_scene_when_requested(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-watch-overwrite-existing",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Replace stale Grok output with a new download.",
                    "duration": 4,
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (incoming / "scene-01.grok.mp4").write_bytes(b"stale imported grok mp4")

    def delayed_download() -> None:
        time.sleep(0.15)
        (downloads / "fresh-scene-one-grok.mp4").write_bytes(b"fresh replacement grok mp4")

    thread = threading.Thread(target=delayed_download)
    thread.start()
    try:
        response = client.post(
            "/api/grok-handoff/manual-watch-overwrite-existing/manual-download-watch",
            json={
                "sceneId": "scene-01",
                "downloadDir": str(downloads),
                "operatorApproved": True,
                "allowNewestFallback": True,
                "overwrite": True,
                "timeoutSeconds": 2,
                "pollIntervalSeconds": 0.05,
                "stopOnImport": True,
            },
        )
        assert response.status_code == 200
        assert response.get_json()["manualDownloadWatchJob"]["overwrite"] is True

        final_job = None
        deadline = time.time() + 3
        while time.time() < deadline:
            status_response = client.get("/api/grok-handoff/manual-watch-overwrite-existing/manual-download-watch")
            assert status_response.status_code == 200
            final_job = status_response.get_json()["manualDownloadWatchJob"]
            if final_job and final_job["status"] in {"imported", "timed-out", "failed"}:
                break
            time.sleep(0.05)
    finally:
        thread.join(timeout=2)

    assert final_job is not None
    assert final_job["status"] == "imported"
    assert final_job["overwrite"] is True
    assert final_job["importedCount"] == 1
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"fresh replacement grok mp4"
    manifest = json.loads((tmp_path / "storage" / "grok-handoffs" / "manual-watch-overwrite-existing" / "handoff.json").read_text(encoding="utf-8"))
    assert manifest["watchHistory"][-1]["overwrite"] is True
    assert manifest["watchHistory"][-1]["imported"][0]["originalPath"].endswith("fresh-scene-one-grok.mp4")


def test_grok_handoff_manual_download_watch_summary_marks_dead_running_job_stale(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-watch-stale",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "First Grok hero.",
                    "duration": 4,
                }
            ],
        },
    )
    handoff_dir = Path(created.get_json()["handoffDir"])
    routes_grok._write_manual_download_watch_status(
        handoff_dir,
        {
            "jobId": "watch-stale",
            "projectId": "manual-watch-stale",
            "sceneId": "scene-01",
            "status": "running",
            "startedAt": datetime.now().isoformat(timespec="seconds"),
            "downloadDir": str(tmp_path / "Downloads"),
            "timeoutSeconds": 7200,
            "operatorNextAction": "Watching Downloads.",
        },
    )

    data = client.get("/api/grok-handoff/manual-watch-stale/status").get_json()

    assert data["manualDownloadWatchJob"]["status"] == "stale"
    assert data["manualDownloadWatchJob"]["storedStatus"] == "running"
    assert data["manualDownloadWatchJob"]["activeThread"] is False
    assert data["manualDownloadWatchJob"]["restartAvailable"] is True
    assert data["manualDownloadWatchJob"]["stale"] is True
    assert "Restart the Grok watch" in data["manualDownloadWatchJob"]["operatorNextAction"]
    assert data["mainPathStatus"]["manualWatchActive"] is False


def test_grok_handoff_manual_download_watch_all_scenes_maps_new_downloads_once(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-watch-all-scenes",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "First Grok hero.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Second Grok hero.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    def delayed_downloads() -> None:
        time.sleep(0.12)
        (downloads / "grok-unnamed-first.mp4").write_bytes(b"first unnamed grok mp4")
        time.sleep(0.22)
        (downloads / "grok-unnamed-second.mp4").write_bytes(b"second unnamed grok mp4")

    thread = threading.Thread(target=delayed_downloads)
    thread.start()
    try:
        response = client.post(
            "/api/grok-handoff/manual-watch-all-scenes/manual-download-watch",
            json={
                "watchAllScenes": True,
                "downloadDir": str(downloads),
                "operatorApproved": True,
                "allowNewestFallback": True,
                "sinceHandoff": False,
                "preserveCandidates": False,
                "timeoutSeconds": 3,
                "pollIntervalSeconds": 0.05,
                "stopOnImport": False,
            },
        )
        assert response.status_code == 200

        final_job = None
        deadline = time.time() + 8
        while time.time() < deadline:
            status_response = client.get("/api/grok-handoff/manual-watch-all-scenes/manual-download-watch")
            assert status_response.status_code == 200
            final_job = status_response.get_json()["manualDownloadWatchJob"]
            if final_job and final_job["status"] in {"imported", "timed-out", "failed"}:
                break
            time.sleep(0.05)
    finally:
        thread.join(timeout=2)

    assert final_job is not None
    assert final_job["status"] == "imported"
    assert final_job["sceneId"] == ""
    assert final_job["allReady"] is True
    assert final_job["importedCount"] == 2
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"first unnamed grok mp4"
    assert (incoming / "scene-02.grok.mp4").read_bytes() == b"second unnamed grok mp4"
    assert not list(incoming.glob("scene-01-*.mp4"))

    status_data = client.get("/api/grok-handoff/manual-watch-all-scenes/status").get_json()
    assert status_data["readyScenes"] == 2
    assert [item["sceneId"] for item in status_data["assets"]] == ["scene-01", "scene-02"]
    assert all(item["status"] == "ready" for item in status_data["assets"])


def test_grok_handoff_manual_download_watch_can_scan_save_as_sibling_folders(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-watch-multi-dir",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Grok hero take one.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Grok hero take two.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    downloads = tmp_path / "Downloads"
    desktop = tmp_path / "Desktop"
    downloads.mkdir()
    desktop.mkdir()

    def delayed_save_as_files() -> None:
        time.sleep(0.12)
        (desktop / "Grok Save As 01.mp4").write_bytes(b"desktop grok scene one")
        time.sleep(0.12)
        (desktop / "Grok Save As 02.mp4").write_bytes(b"desktop grok scene two")

    thread = threading.Thread(target=delayed_save_as_files)
    thread.start()
    try:
        response = client.post(
            "/api/grok-handoff/manual-watch-multi-dir/manual-download-watch",
            json={
                "watchAllScenes": True,
                "downloadDir": str(downloads),
                "downloadDirs": [str(downloads), str(desktop)],
                "operatorApproved": True,
                "allowNewestFallback": True,
                "sinceHandoff": False,
                "preserveCandidates": False,
                "timeoutSeconds": 3,
                "pollIntervalSeconds": 0.05,
                "stopOnImport": False,
            },
        )
        assert response.status_code == 200
        start_data = response.get_json()
        assert start_data["downloadDir"] == str(downloads.resolve())
        assert start_data["downloadDirs"] == [str(downloads.resolve()), str(desktop.resolve())]
        assert start_data["manualDownloadWatchJob"]["downloadDirs"] == [
            str(downloads.resolve()),
            str(desktop.resolve()),
        ]

        final_job = None
        deadline = time.time() + 8
        while time.time() < deadline:
            status_response = client.get("/api/grok-handoff/manual-watch-multi-dir/manual-download-watch")
            assert status_response.status_code == 200
            final_job = status_response.get_json()["manualDownloadWatchJob"]
            if final_job and final_job["status"] in {"imported", "timed-out", "failed"}:
                break
            time.sleep(0.05)
    finally:
        thread.join(timeout=2)

    assert final_job is not None
    assert final_job["status"] == "imported"
    assert final_job["downloadDirs"] == [str(downloads.resolve()), str(desktop.resolve())]
    assert final_job["importedCount"] == 2
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"desktop grok scene one"
    assert (incoming / "scene-02.grok.mp4").read_bytes() == b"desktop grok scene two"

    _, manifest = routes_grok._load_manifest("manual-watch-multi-dir")
    assert manifest["watchHistory"][-1]["downloadDirs"] == [str(downloads.resolve()), str(desktop.resolve())]
    assert all(str(desktop) in item["originalPath"] for item in manifest["watchHistory"][-1]["imported"])
    queue_response = client.get("/api/grok-handoff/manual-watch-multi-dir/production-queue")
    assert queue_response.status_code == 200
    queue_html = queue_response.data.decode("utf-8")
    assert "Watched folders" in queue_html
    assert str(downloads.resolve()) in queue_html
    assert str(desktop.resolve()) in queue_html


def test_grok_handoff_manual_download_watch_groups_take_candidates_by_scene(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-watch-take-groups",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same presenter places a red notebook beside a cafe window.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Same presenter lifts the same notebook toward morning light.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    def delayed_downloads() -> None:
        for file_name, payload in [
            ("Grok Imagine.mp4", b"scene one take one"),
            ("Grok Imagine (1).mp4", b"scene one take two"),
            ("Grok Imagine (2).mp4", b"scene two take one"),
            ("Grok Imagine (3).mp4", b"scene two take two"),
        ]:
            time.sleep(0.08)
            (downloads / file_name).write_bytes(payload)

    thread = threading.Thread(target=delayed_downloads)
    thread.start()
    try:
        response = client.post(
            "/api/grok-handoff/manual-watch-take-groups/manual-download-watch",
            json={
                "watchAllScenes": True,
                "downloadDir": str(downloads),
                "operatorApproved": True,
                "allowNewestFallback": True,
                "sinceHandoff": False,
                "preserveCandidates": True,
                "sceneMappingMode": "scene-grouped-takes",
                "sceneGroupedTakeSize": 2,
                "timeoutSeconds": 4,
                "pollIntervalSeconds": 0.05,
                "stopOnImport": False,
            },
        )
        assert response.status_code == 200

        final_job = None
        deadline = time.time() + 8
        while time.time() < deadline:
            status_response = client.get("/api/grok-handoff/manual-watch-take-groups/manual-download-watch")
            assert status_response.status_code == 200
            final_job = status_response.get_json()["manualDownloadWatchJob"]
            if final_job and final_job["status"] in {"imported", "timed-out", "failed"}:
                break
            time.sleep(0.05)
    finally:
        thread.join(timeout=2)

    assert final_job is not None
    assert final_job["status"] == "imported"
    assert final_job["sceneId"] == ""
    assert final_job["sceneMappingMode"] == "scene-grouped-takes"
    assert final_job["sceneGroupedTakeSize"] == 2
    assert final_job["sceneGroupedTakeTarget"] == 4
    assert final_job["importedCount"] == 4
    assert final_job["allReady"] is True
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"scene one take one"
    assert (incoming / "scene-02.grok.mp4").read_bytes() == b"scene two take one"
    scene_one_candidates = sorted(incoming.glob("scene-01-*.mp4"))
    scene_two_candidates = sorted(incoming.glob("scene-02-*.mp4"))
    assert len(scene_one_candidates) == 1
    assert len(scene_two_candidates) == 1
    assert scene_one_candidates[0].read_bytes() == b"scene one take two"
    assert scene_two_candidates[0].read_bytes() == b"scene two take two"

    status_data = client.get("/api/grok-handoff/manual-watch-take-groups/status").get_json()
    assets = {item["sceneId"]: item for item in status_data["assets"]}
    assert [item["fileName"] for item in assets["scene-01"]["candidateAssets"]] == [
        "scene-01.grok.mp4",
        scene_one_candidates[0].name,
    ]
    assert [item["fileName"] for item in assets["scene-02"]["candidateAssets"]] == [
        "scene-02.grok.mp4",
        scene_two_candidates[0].name,
    ]


def test_grok_handoff_manual_download_watch_can_replace_single_scene_with_grouped_batch(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-watch-replace-single",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Same worker enters the subway platform at night.",
                    "duration": 4,
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "image_source": "grok",
                    "grok_prompt": "Same worker starts cooking under warm kitchen light.",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    first = client.post(
        "/api/grok-handoff/manual-watch-replace-single/manual-download-watch",
        json={
            "sceneId": "scene-01",
            "downloadDir": str(downloads),
            "operatorApproved": True,
            "allowNewestFallback": True,
            "sinceHandoff": False,
            "timeoutSeconds": 4,
            "pollIntervalSeconds": 0.05,
            "stopOnImport": True,
        },
    )
    assert first.status_code == 200
    assert first.get_json()["manualDownloadWatchJob"]["status"] in {"queued", "running"}

    def delayed_downloads() -> None:
        for file_name, payload in [
            ("Grok Imagine.mp4", b"scene one first take"),
            ("Grok Imagine (1).mp4", b"scene one second take"),
            ("Grok Imagine (2).mp4", b"scene two first take"),
            ("Grok Imagine (3).mp4", b"scene two second take"),
        ]:
            time.sleep(0.08)
            (downloads / file_name).write_bytes(payload)

    thread = threading.Thread(target=delayed_downloads)
    thread.start()
    try:
        replacement = client.post(
            "/api/grok-handoff/manual-watch-replace-single/manual-download-watch",
            json={
                "watchAllScenes": True,
                "downloadDir": str(downloads),
                "operatorApproved": True,
                "allowNewestFallback": True,
                "sinceHandoff": False,
                "preserveCandidates": True,
                "sceneMappingMode": "scene-grouped-takes",
                "sceneGroupedTakeSize": 2,
                "timeoutSeconds": 4,
                "pollIntervalSeconds": 0.05,
                "stopOnImport": False,
                "replaceExisting": True,
            },
        )
        assert replacement.status_code == 200
        replacement_data = replacement.get_json()
        assert replacement_data["ok"] is True
        assert replacement_data["replacedExisting"] is True
        assert replacement_data.get("alreadyRunning") is not True

        final_job = None
        deadline = time.time() + 8
        while time.time() < deadline:
            status_response = client.get("/api/grok-handoff/manual-watch-replace-single/manual-download-watch")
            assert status_response.status_code == 200
            final_job = status_response.get_json()["manualDownloadWatchJob"]
            if final_job and final_job["status"] in {"imported", "timed-out", "failed"}:
                break
            time.sleep(0.05)
    finally:
        thread.join(timeout=2)

    assert final_job is not None
    assert final_job["status"] == "imported"
    assert final_job["sceneMappingMode"] == "scene-grouped-takes"
    assert final_job["sceneGroupedTakeTarget"] == 4
    assert final_job["importedCount"] == 4
    assert (incoming / "scene-01.grok.mp4").read_bytes() == b"scene one first take"
    assert (incoming / "scene-02.grok.mp4").read_bytes() == b"scene two first take"


def test_grok_handoff_manual_download_watch_requires_operator_approval(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "manual-watch-approval",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Manual watch approval scene.",
                    "duration": 4,
                }
            ],
        },
    )
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    response = client.post(
        "/api/grok-handoff/manual-watch-approval/manual-download-watch",
        json={"downloadDir": str(downloads)},
    )

    assert response.status_code == 403
    data = response.get_json()
    assert data["ok"] is False
    assert "operatorApproved" in data["error"]


def test_grok_handoff_operator_run_opens_grok_and_returns_render_payload(tmp_path, monkeypatch):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "operator-run",
            "prompt": "Grok operator run",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                }
            ],
        },
    )
    opened_urls: list[str] = []
    monkeypatch.setattr(routes_grok.webbrowser, "open", lambda url, new=0: opened_urls.append(url) or True)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    def delayed_download() -> None:
        time.sleep(0.15)
        (downloads / "scene-01.grok.mp4").write_bytes(b"operator grok mp4")

    thread = threading.Thread(target=delayed_download)
    thread.start()
    try:
        response = client.post(
            "/api/grok-handoff/operator-run/operator-run",
            json={
                "downloadDir": str(downloads),
                "operatorApproved": True,
                "openTargets": ["worksheet", "grok"],
                "timeoutSeconds": 2,
                "pollIntervalSeconds": 0.05,
            },
        )
    finally:
        thread.join(timeout=2)

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["automationMode"] == "operator-approved-open-watch-import-render"
    assert [item["target"] for item in data["openedTargets"]] == ["worksheet", "grok"]
    assert opened_urls == [created.get_json()["worksheetUrl"], routes_grok.GROK_IMAGINE_URL]
    assert data["reviewPacketUrl"].endswith("/api/grok-handoff/operator-run/review-packet")
    assert data["allReady"] is True
    assert data["renderPayload"]["allReady"] is True
    assert data["renderPayload"]["sceneAssets"][0]["sourcePath"] == (
        "storage/grok-handoffs/operator-run/incoming/scene-01.grok.mp4"
    )


def test_grok_handoff_operator_run_requires_operator_approval(tmp_path):
    client = _grok_test_client(tmp_path)
    client.post(
        "/api/grok-handoff",
        json={
            "projectId": "operator-approval",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                }
            ],
        },
    )
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    response = client.post(
        "/api/grok-handoff/operator-approval/operator-run",
        json={"downloadDir": str(downloads)},
    )

    assert response.status_code == 403
    data = response.get_json()
    assert data["ok"] is False
    assert "operatorApproved" in data["error"]


def test_grok_handoff_render_payload_maps_ready_mp4_to_scene_asset(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "render-ready",
            "prompt": "Grok cafe reel",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "title": "Steam hero",
                    "narration": "The first frame sells the mood.",
                    "display_text": "Steam first",
                    "image_prompt": "Coffee steam hero",
                    "image_source": "grok",
                    "grok_prompt": "Cinematic coffee steam hero.",
                    "duration": 4,
                    "caption_preset": "top-hook",
                    "quality_review_note": "Operator checked no watermark, no baked-in text, and subject remains visible.",
                },
                {
                    "sceneId": "scene-02",
                    "scene_num": 2,
                    "title": "Support cut",
                    "narration": "The pour continues the same warm tone.",
                    "display_text": "Warm pour",
                    "image_prompt": "barista slow pour",
                    "image_source": "pexels-video",
                    "duration": 4,
                },
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / "scene-01.grok.mp4").write_bytes(b"fake mp4 bytes")

    response = client.get("/api/grok-handoff/render-ready/render-payload")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["allReady"] is True
    assert data["projectId"] == "render-ready-render"
    assert data["prompt"] == "Grok cafe reel"
    scene_asset = data["sceneAssets"][0]
    assert scene_asset["sceneId"] == "scene-01"
    assert scene_asset["role"] == "visual"
    assert scene_asset["fileName"] == "scene-01.grok.mp4"
    assert scene_asset["mimeType"] == "video/mp4"
    assert scene_asset["sourcePath"] == "storage/grok-handoffs/render-ready/incoming/scene-01.grok.mp4"
    assert scene_asset["sourceOrigin"] == "grok-handoff"
    assert scene_asset["sourceGenerator"] == "grok-app-web-handoff"
    assert scene_asset["candidateCount"] == 1
    assert data["providerOverrides"] == {"scene-01": "grok"}
    grok_scene = data["draftScenes"][0]
    assert grok_scene["image_source"] == "grok"
    assert grok_scene["upload_kind"] == "video"
    assert grok_scene["originality_evidence"].startswith("Grok Imagine web/app MP4")
    assert grok_scene["quality_review_note"].startswith("Operator checked")
    assert grok_scene["layout_variant_key"] == "grok-first-hook"
    assert grok_scene["layoutVariantLabel"] == "Grok-first hook"
    assert data["draftScenes"][1]["image_source"] == "pexels-video"


def test_grok_handoff_render_payload_uses_source_recovery_replacement_for_rejected_scene(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "render-recovery",
            "prompt": "Recovered Grok reel",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "title": "Hook reset",
                    "narration": "The first action makes the reset readable.",
                    "display_text": "Reset first",
                    "image_prompt": "Korean office worker flips a phone face down",
                    "image_source": "grok",
                    "grok_prompt": "Korean office worker flips a phone face down in the first second.",
                    "duration": 4,
                    "caption_preset": "top-hook",
                }
            ],
        },
    )
    assert created.status_code == 200
    rejected = client.post(
        "/api/grok-handoff/render-recovery/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": False,
            "operatorNote": "Original local candidate had visible phone UI and weak caption-safe framing.",
        },
    )
    assert rejected.status_code == 200

    replacement = tmp_path / "storage" / "source-recovery" / "render-recovery" / "scene-01-fixed.mp4"
    replacement.parent.mkdir(parents=True, exist_ok=True)
    replacement_bytes = b"accepted source recovery replacement mp4"
    replacement.write_bytes(replacement_bytes)
    replacement_sha = hashlib.sha256(replacement_bytes).hexdigest()
    handoff_dir = tmp_path / "storage" / "grok-handoffs" / "render-recovery"
    acceptance_path = handoff_dir / "source-recovery-acceptance.json"
    acceptance_path.write_text(
        json.dumps(
            {
                "schema": "video-studio.source-recovery-acceptance.v1",
                "projectId": "render-recovery",
                "templateOnly": False,
                "acceptanceScenes": [
                    {
                        "sceneId": "scene-01",
                        "operatorDecision": {
                            "accepted": True,
                            "reviewStatus": "accepted",
                            "acceptedReplacementFileName": replacement.name,
                            "acceptedReplacementPath": str(replacement),
                            "acceptedReplacementSha256": replacement_sha,
                            "reviewerId": "operator-test",
                            "acceptedAt": "2026-06-06T12:00:00+09:00",
                            "firstTwoSecondHookPass": True,
                            "motionDensityPass": True,
                            "aiSlopVisualFitPass": True,
                            "stockAiClipFitPass": True,
                            "captionSafeZonePass": True,
                            "sourceProvenanceConfirmed": True,
                            "phoneFirstFrameReviewPass": True,
                            "continuityReviewPass": True,
                        },
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    acceptance_sha = hashlib.sha256(acceptance_path.read_bytes()).hexdigest()
    rerender_plan = {
        "schema": "video-studio.source-recovery-rerender-plan.v1",
        "projectId": "render-recovery",
        "templateOnly": True,
        "doNotSubmitAsProof": True,
        "sourceRecoveryAcceptanceCleared": True,
        "rerenderInputReady": True,
        "sourceRecoveryAcceptanceArtifactPath": str(acceptance_path),
        "sourceRecoveryAcceptanceSha256": "0" * 64,
        "sceneReplacements": [
            {
                "sceneId": "scene-01",
                "acceptedReplacementFileName": replacement.name,
                "acceptedReplacementPath": str(replacement),
                "acceptedReplacementSha256": replacement_sha,
                "acceptedReplacementPathCheck": {
                    "ok": True,
                    "actualSha256": replacement_sha,
                    "expectedSha256": replacement_sha,
                },
                "renderInputOverride": {
                    "sceneId": "scene-01",
                    "sourcePath": str(replacement),
                    "sourceFileName": replacement.name,
                    "sourceKind": "source-recovery-accepted-replacement",
                },
            }
        ],
    }
    (handoff_dir / "source-recovery-rerender-plan.template.json").write_text(
        json.dumps(rerender_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    mismatch_status_response = client.get("/api/grok-handoff/render-recovery/status")
    assert mismatch_status_response.status_code == 200
    mismatch_status_data = mismatch_status_response.get_json()
    assert mismatch_status_data["allReady"] is False
    assert mismatch_status_data["rejectedSceneIds"] == ["scene-01"]

    rerender_plan["sourceRecoveryAcceptanceSha256"] = acceptance_sha
    (handoff_dir / "source-recovery-rerender-plan.template.json").write_text(
        json.dumps(rerender_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    status_response = client.get("/api/grok-handoff/render-recovery/status")
    assert status_response.status_code == 200
    status_data = status_response.get_json()
    assert status_data["allReady"] is True
    assert status_data["rejectedSceneIds"] == []
    assert status_data["assets"][0]["sourceRecoveryReplacement"] is True

    response = client.get("/api/grok-handoff/render-recovery/render-payload")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["allReady"] is True
    assert data["rejectedSceneIds"] == []
    scene_asset = data["sceneAssets"][0]
    assert scene_asset["sceneId"] == "scene-01"
    assert scene_asset["sourcePath"] == "storage/source-recovery/render-recovery/scene-01-fixed.mp4"
    assert scene_asset["sourceRecoveryReplacement"] is True
    assert scene_asset["sourceRecoveryRerenderPlanPath"] == (
        "storage/grok-handoffs/render-recovery/source-recovery-rerender-plan.template.json"
    )
    assert scene_asset["sourceRecoveryAcceptanceSha256"] == acceptance_sha
    assert scene_asset["acceptedReplacementSha256"] == replacement_sha
    assert scene_asset["candidateCount"] == 1
    assert scene_asset["selectedCandidateSummary"].startswith("Source recovery acceptance selected")
    assert scene_asset["sourceProvenance"]["sourceKind"] == "source-recovery-accepted-replacement"
    assert data["draftScenes"][0]["sourceRecoveryReplacement"] is True
    assert data["draftScenes"][0]["sourceProvenanceConfirmed"] is True
    assert data["draftScenes"][0]["selectedFileName"] == replacement.name
    assert data["draftScenes"][0]["visualQualityVerdict"] == "pass"
    assert "Source recovery replacement accepted" in data["draftScenes"][0]["quality_review_note"]


def test_source_recovery_rerender_plan_blocks_false_phone_review_acceptance(tmp_path):
    client = _grok_test_client(tmp_path)

    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "render-recovery-phone-gate",
            "templateType": "authentic_vlog",
            "tone": "casual_heyo",
            "lang": "ko",
            "targetDuration": "10s",
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "image_prompt": "Korean office worker flips a phone face down",
                    "image_source": "grok",
                    "grok_prompt": "Korean office worker flips a phone face down in the first second.",
                    "duration": 4,
                    "caption_preset": "top-hook",
                }
            ],
        },
    )
    assert created.status_code == 200
    rejected = client.post(
        "/api/grok-handoff/render-recovery-phone-gate/review-decision",
        json={
            "sceneId": "scene-01",
            "accepted": False,
            "operatorNote": "Original candidate fails phone-size first-frame review.",
        },
    )
    assert rejected.status_code == 200

    replacement = tmp_path / "storage" / "source-recovery" / "render-recovery-phone-gate" / "scene-01-fixed.mp4"
    replacement.parent.mkdir(parents=True, exist_ok=True)
    replacement_bytes = b"accepted source recovery replacement mp4"
    replacement.write_bytes(replacement_bytes)
    replacement_sha = hashlib.sha256(replacement_bytes).hexdigest()
    handoff_dir = tmp_path / "storage" / "grok-handoffs" / "render-recovery-phone-gate"
    acceptance_path = handoff_dir / "source-recovery-acceptance.json"

    acceptance_payload = {
        "schema": "video-studio.source-recovery-acceptance.v1",
        "projectId": "render-recovery-phone-gate",
        "templateOnly": False,
        "acceptanceScenes": [
            {
                "sceneId": "scene-01",
                "operatorDecision": {
                    "accepted": True,
                    "reviewStatus": "accepted",
                    "acceptedReplacementFileName": replacement.name,
                    "acceptedReplacementPath": str(replacement),
                    "acceptedReplacementSha256": replacement_sha,
                    "reviewerId": "operator-test",
                    "acceptedAt": "2026-06-06T12:00:00+09:00",
                    "firstTwoSecondHookPass": True,
                    "motionDensityPass": True,
                    "aiSlopVisualFitPass": True,
                    "stockAiClipFitPass": True,
                    "captionSafeZonePass": True,
                    "sourceProvenanceConfirmed": True,
                    "phoneFirstFrameReviewPass": False,
                    "continuityReviewPass": True,
                },
            }
        ],
    }
    acceptance_path.write_text(json.dumps(acceptance_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    acceptance_sha = hashlib.sha256(acceptance_path.read_bytes()).hexdigest()
    rerender_plan = {
        "schema": "video-studio.source-recovery-rerender-plan.v1",
        "projectId": "render-recovery-phone-gate",
        "templateOnly": True,
        "doNotSubmitAsProof": True,
        "sourceRecoveryAcceptanceCleared": True,
        "rerenderInputReady": True,
        "sourceRecoveryAcceptanceArtifactPath": str(acceptance_path),
        "sourceRecoveryAcceptanceSha256": acceptance_sha,
        "sceneReplacements": [
            {
                "sceneId": "scene-01",
                "acceptedReplacementFileName": replacement.name,
                "acceptedReplacementPath": str(replacement),
                "acceptedReplacementSha256": replacement_sha,
                "acceptedReplacementPathCheck": {
                    "ok": True,
                    "actualSha256": replacement_sha,
                    "expectedSha256": replacement_sha,
                },
                "renderInputOverride": {
                    "sceneId": "scene-01",
                    "sourcePath": str(replacement),
                    "sourceFileName": replacement.name,
                    "sourceKind": "source-recovery-accepted-replacement",
                },
            }
        ],
    }
    (handoff_dir / "source-recovery-rerender-plan.template.json").write_text(
        json.dumps(rerender_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    status_response = client.get("/api/grok-handoff/render-recovery-phone-gate/status")

    assert status_response.status_code == 200
    status_data = status_response.get_json()
    assert status_data["allReady"] is False
    assert status_data["rejectedSceneIds"] == ["scene-01"]
    assert all(item.get("sourceRecoveryReplacement") is not True for item in status_data["assets"])


def test_save_project_bundle_preserves_source_recovery_replacement_metadata(tmp_path):
    source = tmp_path / "storage" / "source-recovery" / "bundle" / "scene-01-fixed.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"source recovery replacement")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()

    result = save_project_bundle(
        prompt="Recovered source render",
        budget_mode="free",
        availability=ProviderAvailability(),
        planner_mode="sample",
        project_id="bundle-recovery",
        project_root=tmp_path,
        draft_scenes=[
            {
                "sceneId": "scene-01",
                "scene_num": 1,
                "title": "Recovered hook",
                "narration": "",
                "display_text": "Recovered hook",
                "image_prompt": "Korean office worker starts a focus reset.",
                "image_source": "grok",
                "duration": 4,
                "selectedFileName": source.name,
                "selectedCandidateSummary": "Source recovery acceptance selected this replacement after phone/source review.",
                "sourceProvenanceConfirmed": True,
                "sourceProvenanceNote": "Source recovery acceptance recorded replacement path and sha256 before rerender.",
                "visualQualityVerdict": "pass",
            }
        ],
        scene_assets=[
            {
                "sceneId": "scene-01",
                "role": "visual",
                "fileName": source.name,
                "mimeType": "video/mp4",
                "sourcePath": str(source),
                "provider": "upload",
                "sourceOrigin": "grok-handoff",
                "sourceIntent": "grok",
                "sourceGenerator": "grok-app-web-handoff",
                "candidateCount": 1,
                "selectedCandidateSummary": "Source recovery acceptance selected this replacement after phone/source review.",
                "sourceRecoveryReplacement": True,
                "sourceRecoveryRerenderPlanPath": "storage/grok-handoffs/bundle/source-recovery-rerender-plan.template.json",
                "sourceRecoveryAcceptanceArtifactPath": "storage/grok-handoffs/bundle/source-recovery-acceptance.json",
                "sourceRecoveryAcceptanceSha256": "acceptance-sha",
                "acceptedReplacementSha256": source_sha,
                "sourceProvenance": {
                    "status": "local-mp4-source-unverified",
                    "acceptAsGrokMainSource": True,
                    "sourceKind": "source-recovery-accepted-replacement",
                },
            }
        ],
    )

    manifest = result["manifest"]
    scene = manifest["scenes"][0]
    visual_asset = next(asset for asset in manifest["assets"] if asset["role"] == "visual")
    assert scene["selectedFileName"] == source.name
    assert scene["sourceProvenanceConfirmed"] is True
    assert visual_asset["sourceRecoveryReplacement"] is True
    assert visual_asset["sourceRecoveryAcceptanceSha256"] == "acceptance-sha"
    assert visual_asset["acceptedReplacementSha256"] == source_sha
    assert visual_asset["selectedCandidateSummary"].startswith("Source recovery acceptance selected")
    assert visual_asset["sourceProvenance"]["sourceKind"] == "source-recovery-accepted-replacement"


def test_grok_render_payload_marks_authentic_vlog_as_no_voice_by_default(tmp_path):
    client = _grok_test_client(tmp_path)
    created = client.post(
        "/api/grok-handoff",
        json={
            "projectId": "auth-vlog-payload",
            "prompt": "퇴근 후 20분 리셋 루틴",
            "productionContext": {"templateType": "authentic_vlog"},
            "draftScenes": [
                {
                    "sceneId": "scene-01",
                    "scene_num": 1,
                    "title": "퇴근길 속도 낮추기",
                    "display_text": "퇴근길, 속도부터 낮추기",
                    "image_source": "grok",
                    "grok_prompt": "Same Korean office worker slows down on a subway platform at night.",
                    "duration": 4,
                    "caption_preset": "top-hook",
                }
            ],
        },
    )
    incoming = Path(created.get_json()["incomingDir"])
    (incoming / "scene-01.grok.mp4").write_bytes(b"fake grok mp4 bytes")

    response = client.get("/api/grok-handoff/auth-vlog-payload/render-payload")

    assert response.status_code == 200
    data = response.get_json()
    assert data["templateType"] == "authentic_vlog"
    assert data["audioDesignMode"] == "ambient-first"
    scene = data["draftScenes"][0]
    assert scene["narration"] == ""
    assert scene["narrationText"] == ""
    assert scene["audio_design_mode"] == "no-voice"
    assert scene["audioDesignMode"] == "no-voice"
    assert scene["layout_variant_key"] == "grok-first-hook"
    assert scene["layoutVariantKey"] == "grok-first-hook"
    assert scene["layout_variant_note"].startswith("First 1.25s top hook")


def test_server_side_grok_asset_source_path_flows_into_render_manifest(tmp_path):
    source = tmp_path / "storage" / "grok-handoffs" / "grok-test" / "incoming" / "scene-01.grok.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"fake mp4 bytes")

    payload = save_project_bundle(
        prompt="grok handoff render",
        budget_mode="free",
        availability=ProviderAvailability(),
        planner_mode="sample",
        project_id="grok-render-test",
        project_root=tmp_path,
        draft_scenes=[
            {
                "sceneId": "scene-01",
                "scene_num": 1,
                "title": "Steam hook",
                "narration": "Steam rises before the first sip.",
                "display_text": "First sip",
                "image_prompt": "close coffee steam shot",
                "image_source": "grok",
                "upload_kind": "video",
                "duration": 4,
                "caption_preset": "top-hook",
                "grok_prompt": "Close coffee steam reveal, no baked-in text.",
                "source_rationale": "Operator-approved Grok web MP4 was synced for the hero hook.",
                "originality_evidence": "Grok Imagine web output downloaded through local handoff folder.",
                "quality_review_note": "No watermark, no baked-in text, moving hero clip.",
            },
        ],
        scene_assets=[
            {
                "sceneId": "scene-01",
                "role": "visual",
                "fileName": "scene-01.grok.mp4",
                "mimeType": "video/mp4",
                "sourcePath": "storage/grok-handoffs/grok-test/incoming/scene-01.grok.mp4",
            }
        ],
    )

    uploaded = Path(payload["saveResult"]["uploadedAssets"][0]["storedPath"])
    assert uploaded.as_posix().endswith("storage/inputs/grok-render-test/uploads/scene-01/scene-01-grok.mp4")
    assert (tmp_path / uploaded).read_bytes() == b"fake mp4 bytes"

    visual_asset = next(item for item in payload["manifest"]["assets"] if item["role"] == "visual")
    scene = payload["manifest"]["scenes"][0]
    assert visual_asset["provider"] == "upload"
    assert visual_asset["sourceOrigin"] == "uploaded"
    assert visual_asset["sourcePath"].endswith("uploads/scene-01/scene-01-grok.mp4")
    assert scene["visualSourceIntent"] == "grok"
    assert scene["visualKind"] == "video"


def test_grok_authentic_vlog_payload_preserves_no_voice_grok_main_contract(tmp_path):
    source = tmp_path / "storage" / "grok-handoffs" / "grok-auth" / "incoming" / "scene-01.grok.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"fake grok mp4 bytes")

    payload = save_project_bundle(
        prompt="퇴근 후 20분 리셋 루틴",
        budget_mode="free",
        availability=ProviderAvailability(),
        planner_mode="sample",
        project_id="grok-auth-render-test",
        project_root=tmp_path,
        template_type="authentic_vlog",
        draft_scenes=[
            {
                "sceneId": "scene-01",
                "scene_num": 1,
                "title": "퇴근길 속도 낮추기",
                "display_text": "퇴근길, 속도부터 낮추기",
                "image_prompt": "Korean office worker slows down on Seoul subway platform at night",
                "image_source": "grok",
                "upload_kind": "video",
                "duration": 4,
                "caption_preset": "top-hook",
                "audio_design_mode": "no-voice",
                "grok_prompt": "Raw vertical Grok MP4 footage with visible first-second motion and no baked-in text.",
                "source_rationale": "Operator-selected Grok web MP4 is the main visual, not stock b-roll.",
                "originality_evidence": "Grok Imagine web output downloaded through local handoff folder.",
                "quality_review_note": "Caption-safe top hook, no watermark, no baked-in text, and subject remains visible.",
                "visualQualityVerdict": "pass",
                "audioMixReviewNote": "BGM-first no-voice edit; do not synthesize explanatory TTS.",
                "layoutVariantKey": "routine-top-hook",
            },
        ],
        scene_assets=[
            {
                "sceneId": "scene-01",
                "role": "visual",
                "fileName": "scene-01.grok.mp4",
                "mimeType": "video/mp4",
                "sourcePath": "storage/grok-handoffs/grok-auth/incoming/scene-01.grok.mp4",
            }
        ],
    )

    scene = payload["manifest"]["scenes"][0]
    audio_asset = next(item for item in payload["manifest"]["assets"] if item["role"] == "audio")
    assert scene["narrationText"] == ""
    assert scene["subtitleText"] == "퇴근길, 속도부터 낮추기"
    assert scene["audioDesignMode"] == "no-voice"
    assert scene["captionPreset"] == "top-hook"
    assert scene["captionDisplayDurationSec"] == 1.35
    assert scene["layoutVariantKey"] == "routine-top-hook"
    assert audio_asset["provider"] == "local-silence"
    assert audio_asset["kind"] == "silent-bed"


def test_grok_handoff_matching_ignores_bare_scene_number_inside_uuid(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_grok, "_project_root", tmp_path)
    monkeypatch.setattr(routes_grok, "_probe_grok_clip", lambda _path: {
        "ok": True,
        "status": "ok",
        "width": 720,
        "height": 1280,
        "fps": 24.0,
        "durationSec": 6.0,
        "hasAudio": True,
        "motionOk": True,
        "motionStatus": "ok",
        "issues": [],
    })
    handoff_dir = tmp_path / "storage" / "grok-handoffs" / "uuid-number-match"
    incoming_dir = handoff_dir / "incoming"
    incoming_dir.mkdir(parents=True)
    (incoming_dir / "scene-03.grok.mp4").write_bytes(b"ftyp smaller scene 03")
    (incoming_dir / "scene-05-e3a3f3d8-3af8-416b-b2e2-eb39c7dfe403.mp4").write_bytes(
        b"ftyp larger wrong scene 05" * 8
    )

    assets = routes_grok._match_downloaded_assets(
        handoff_dir,
        {
            "projectId": "uuid-number-match",
            "createdAt": "2026-01-01T00:00:00",
            "qualityGateRequired": True,
            "scenes": [
                {
                    "sceneId": "scene-03",
                    "expectedFileName": "scene-03.grok.mp4",
                },
            ],
        },
    )

    ready = next(item for item in assets if item.get("sceneId") == "scene-03")
    assert ready["fileName"] == "scene-03.grok.mp4"
    assert [item["fileName"] for item in ready["candidateAssets"]] == ["scene-03.grok.mp4"]
    assert any(
        item.get("status") == "unmatched"
        and item.get("fileName") == "scene-05-e3a3f3d8-3af8-416b-b2e2-eb39c7dfe403.mp4"
        for item in assets
    )
