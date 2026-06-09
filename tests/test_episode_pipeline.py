"""Episode infrastructure tests."""

import json
from pathlib import Path

from flask import Flask

from worker.bridge.draft_executor import safe_resolve
from worker.bridge.routes_episodes import episodes_bp, init_episode_routes


def _episode_client(project_root: Path):
    init_episode_routes(project_root, safe_resolve)
    app = Flask(__name__)
    app.register_blueprint(episodes_bp)
    return app.test_client()


def _pilot_payload():
    return {
        "episodeId": "grandma-hospital-pilot",
        "title": "Grandma Hospital Pilot",
        "targetPhase": "phase1",
        "templateType": "persona_story",
        "batchSize": 2,
        "characterBible": {
            "grandmother": {
                "age": 72,
                "hair": "short gray perm",
                "clothing": "beige cardigan, purple blouse, navy pants",
                "prop": "purple bankbook pouch",
            }
        },
        "scriptBlocks": [
            {
                "blockId": "B01",
                "title": "Hospital diagnosis",
                "text": "며칠 뒤 딸은 할머니를 병원으로 데려갔습니다.",
                "targetDurationSec": 16,
            }
        ],
        "shots": [
            {
                "cutId": "cut_001",
                "blockId": "B01",
                "role": "a_roll",
                "scene": "Grandmother and daughter enter the hospital exam room.",
                "characters": ["grandmother", "daughter"],
                "allowedLocation": "hospital exam room",
                "forbiddenLocations": ["salon", "bank", "home living room"],
                "plannedDurationSec": 8,
                "assignedScript": "며칠 뒤 딸은 할머니를 병원으로 데려갔습니다.",
                "grokPrompt": "Korean grandmother and daughter enter a quiet hospital exam room.",
            },
            {
                "cutId": "cut_002",
                "blockId": "B01",
                "role": "a_roll",
                "scene": "Doctor explains diagnosis while the grandmother holds the pouch.",
                "characters": ["grandmother", "daughter", "doctor"],
                "allowedLocation": "hospital exam room",
                "forbiddenLocations": ["salon", "bank", "office"],
                "plannedDurationSec": 8.5,
                "assignedScript": "의사는 조심스럽게 검사 결과를 설명했습니다.",
                "grokPrompt": "Doctor gently explains diagnosis to the same grandmother and daughter.",
            },
        ],
    }


def _preproduction_payload(create_episode_plan: bool = False):
    return {
        "episodeId": "world-cup-opener-check",
        "title": "World Cup opener checklist",
        "templateType": "authentic_vlog",
        "batchSize": 3,
        "createEpisodePlan": create_episode_plan,
        "topicBrief": {
            "format": "shortform",
            "trendAnchor": "2026 FIFA World Cup opening week",
            "whyNow": "The tournament starts this week, so Korean viewers need a quick schedule and format check before kickoff.",
            "audience": "Korean football viewers",
            "viewerQuestion": "What should I check before the first World Cup match?",
            "angle": "Make the opening-week schedule and new expanded format feel simple enough to save before match day.",
            "evidenceNotes": [
                "Opening match timing",
                "Expanded 48-team format",
                "Korea viewer time-zone confusion",
            ],
        },
        "storyboardBeats": [
            {
                "beatId": "beat-001",
                "role": "hook",
                "storyPurpose": "Stop the viewer before they assume the old World Cup rhythm still applies.",
                "viewerQuestion": "What changed before the first match?",
                "onScreenText": "개막 전 이것만",
                "narrationLine": "월드컵, 이번엔 날짜부터 헷갈립니다.",
                "visualAction": "A hand circles the opening date on a printed football calendar in the first second.",
                "sourceNeed": "Calendar action makes the schedule problem visible instead of using generic football B-roll.",
                "allowedLocation": "desk with printed football schedule",
                "characters": ["host hands"],
                "captionPreset": "top-hook",
                "layoutVariantKey": "routine-top-hook",
                "layoutVariantNote": "top hook stays clear of the calendar hand action",
                "plannedTransitionAfter": {
                    "text": "도착했으면\\N끊고 들어가기",
                    "durationSec": 0.24,
                    "mode": "overlay",
                    "audioPolicy": "continuous-bgm-bed",
                    "purpose": "add a short chapter cue without stopping the music bed",
                },
                "plannedDurationSec": 6,
            },
            {
                "beatId": "beat-002",
                "role": "evidence",
                "storyPurpose": "Show that the tournament format is bigger than casual viewers remember.",
                "onScreenText": "48팀, 104경기",
                "narrationLine": "이번 대회는 48팀, 총 104경기입니다.",
                "visualAction": "A phone screen scrolls past a simple match list while a finger pauses on the total match count.",
                "sourceNeed": "A scrolling schedule shows scale without relying on a talking-head explanation.",
                "allowedLocation": "handheld phone schedule view at a desk",
                "characters": ["host hands"],
                "captionPreset": "lower-info",
                "layoutVariantKey": "routine-lower-info",
                "layoutVariantNote": "lower info must not cover the phone schedule list",
                "plannedTransitionAfter": {
                    "text": "방해 요소는\\N화면 밖으로",
                    "durationSec": 0.22,
                    "mode": "micro-transition",
                    "audioPolicy": "continuous-bgm-bed",
                    "purpose": "separate the proof beat from the reminder payoff without a hard card",
                },
                "plannedDurationSec": 6,
            },
            {
                "beatId": "beat-003",
                "role": "payoff",
                "storyPurpose": "Give the viewer a concrete next action before leaving the clip.",
                "onScreenText": "첫 경기 알림 켜기",
                "narrationLine": "첫 경기 알림부터 켜두면 놓칠 확률이 줄어듭니다.",
                "visualAction": "A thumb turns on a match reminder toggle and the phone is placed beside the calendar.",
                "sourceNeed": "The reminder toggle is the saveable action that makes the clip useful.",
                "allowedLocation": "desk with phone and printed football calendar",
                "characters": ["host hands"],
                "captionPreset": "lower-info",
                "layoutVariantKey": "routine-lower-info",
                "plannedDurationSec": 6,
            },
        ],
    }


def test_episode_plan_writes_manifest_sync_map_and_grok_batches(tmp_path):
    client = _episode_client(tmp_path)

    response = client.post("/api/episodes/plan", json=_pilot_payload())

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["episodeId"] == "grandma-hospital-pilot"
    assert data["manifest"]["compatibility"]["changesExistingGrokContract"] is False
    assert data["manifest"]["compatibility"]["usesBrowserExtensionHandoff"] is True
    assert data["manifest"]["compatibility"]["usesApiProviders"] is False
    assert data["manifest"]["counts"]["cuts"] == 2
    assert data["manifest"]["counts"]["geminiImageBatches"] == 1
    assert data["manifest"]["counts"]["grokVideoBatches"] == 1
    assert data["manifest"]["outputGate"]["status"] == "pass"
    assert data["outputGate"]["promptOutputAllowed"] is True
    assert data["validation"]["ok"] is True
    assert data["validation"]["warningCount"] == 0

    manifest_path = Path(data["manifestPath"])
    sync_path = Path(data["shotSyncMapPath"])
    audit_path = Path(data["storySyncAuditPath"])
    output_gate_path = Path(data["outputGatePath"])
    assert manifest_path.exists()
    assert sync_path.exists()
    assert audit_path.exists()
    assert output_gate_path.exists()
    assert Path(data["browserHandoffsPath"]).exists()
    assert (manifest_path.parent / "character-bible.md").exists()

    sync_map = json.loads(sync_path.read_text(encoding="utf-8"))
    first_cut = sync_map["cuts"][0]
    assert first_cut["cutId"] == "cut_001"
    assert first_cut["sceneId"] == "scene-001"
    assert first_cut["stableCutVideoName"] == "cut_001.mp4"
    assert first_cut["grokExpectedFileName"] == "scene-001.grok.mp4"
    assert first_cut["ttsSegmentId"] == "seg_001"

    batch_response = client.get("/api/episodes/grandma-hospital-pilot/grok-batches")
    assert batch_response.status_code == 200
    batches = batch_response.get_json()["batches"]
    assert len(batches) == 1
    request = batches[0]["handoffRequest"]
    assert request["projectId"] == "grandma-hospital-pilot-batch-001"
    assert request["templateType"] == "persona_story"
    assert request["draftScenes"][0]["sceneId"] == "scene-001"
    assert "Character bible excerpt" in request["draftScenes"][0]["grok_prompt"]

    handoffs_response = client.get("/api/episodes/grandma-hospital-pilot/browser-handoffs")
    assert handoffs_response.status_code == 200
    handoffs = handoffs_response.get_json()["browserHandoffs"]
    assert handoffs["mode"] == "codex-browser-extension-semi-auto"
    assert handoffs["usesApi"] is False
    assert handoffs["outputGate"]["status"] == "pass"
    assert handoffs["outputGate"]["promptOutputAllowed"] is True
    assert handoffs["browserControlPolicy"]["geminiWebImage"]["primaryRail"] == "existing-signed-in-chrome-browser-control"
    assert handoffs["browserControlPolicy"]["geminiWebImage"]["forbidNewChromeProfile"] is True
    assert handoffs["browserControlPolicy"]["grokWebVideo"]["surfaceGuard"] == "grok-imagine-only"
    assert handoffs["browserControlPolicy"]["grokWebVideo"]["forbidChatThreadSuccess"] is True
    assert handoffs["providers"]["geminiWebImage"]["status"] == "queue-ready"
    assert handoffs["providers"]["geminiWebImage"]["extensionCommandReady"] is True
    assert handoffs["providers"]["geminiWebImage"]["canFillPrompt"] is True
    assert handoffs["providers"]["geminiWebImage"]["canClickGenerate"] is False
    assert handoffs["providers"]["geminiWebImage"]["browserControlPolicy"]["canClickGenerate"] is False
    assert handoffs["providers"]["grokWebVideo"]["status"] == "queue-ready"
    assert handoffs["providers"]["grokWebVideo"]["browserControlPolicy"]["localMp4ImportRequired"] is True
    assert handoffs["providers"]["geminiWebVideo"]["status"] == "planned-only"
    image_batch = handoffs["batches"]["geminiWebImage"][0]
    assert image_batch["targetUrl"] == "https://gemini.google.com/app"
    assert image_batch["usesApi"] is False
    assert image_batch["promptOutputGate"]["status"] == "pass"
    assert image_batch["browserControlPolicy"]["companionExtensionRole"] == "fallback-diagnostic-only"
    assert image_batch["browserControlPolicy"]["canImportResult"] is False
    assert image_batch["companion"]["providerAdapter"] == "gemini-web-image"
    assert image_batch["companion"]["canFillPrompt"] is True
    assert image_batch["companion"]["canClickGenerate"] is False
    video_batch = handoffs["batches"]["grokWebVideo"][0]
    assert video_batch["browserControlPolicy"]["successSurface"] == "https://grok.com/imagine"
    assert video_batch["browserControlPolicy"]["downloadAuthority"] == "operator-owned-manual-download-or-local-upload"
    assert image_batch["cuts"][0]["expectedFileName"] == "cut_001.png"
    assert "Character bible excerpt" in image_batch["cuts"][0]["prompt"]
    assert image_batch["cuts"][0]["promptOutputGate"]["status"] == "pass"
    assert image_batch["cuts"][0]["extensionCommandUrl"].endswith(
        "/api/episodes/grandma-hospital-pilot/browser-handoffs/gemini-web-image/batch-001/extension-command?operatorApproved=true&cutId=cut_001"
    )
    assert image_batch["cuts"][0]["autostartUrl"].startswith("https://gemini.google.com/app#")
    assert "videoStudioProvider=gemini-web-image" in image_batch["cuts"][0]["autostartUrl"]
    assert "image-review-before-grok-video" == image_batch["reviewGate"]

    command_response = client.get(
        "/api/episodes/grandma-hospital-pilot/browser-handoffs/gemini-web-image/batch-001/extension-command"
        "?operatorApproved=true&cutId=cut_001"
    )
    assert command_response.status_code == 200
    command = command_response.get_json()
    assert command["provider"] == "gemini-web-image"
    assert command["commandKind"] == "image-prompt-fill"
    assert command["canFillPrompt"] is True
    assert command["canClickGenerate"] is False
    assert command["promptOutputGate"]["status"] == "pass"
    assert command["promptOutputGate"]["gateKind"] == "prompt-output"
    assert command["prompt"] == image_batch["cuts"][0]["prompt"]
    assert command["eventEndpoint"].endswith("/api/episodes/grandma-hospital-pilot/browser-handoffs/extension-event")

    event_response = client.post(
        "/api/episodes/grandma-hospital-pilot/browser-handoffs/extension-event",
        json={
            "operatorApproved": True,
            "extensionApproved": True,
            "provider": "gemini-web-image",
            "batchId": "batch-001",
            "cutId": "cut_001",
            "sceneId": "scene-001",
            "expectedFileName": "cut_001.png",
            "eventType": "gemini-prompt-fill",
            "status": "filled",
            "detail": "filledLength=120; generate remains operator-owned",
            "currentUrl": "https://gemini.google.com/app",
            "build": "20260607-gemini-image-handoff",
        },
    )
    assert event_response.status_code == 200
    event_path = manifest_path.parent / "browser-handoffs" / "extension-events.jsonl"
    assert event_path.exists()
    latest_event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[-1])
    assert latest_event["provider"] == "gemini-web-image"
    assert latest_event["status"] == "filled"
    assert latest_event["proofMode"] == "extension"
    assert latest_event["extensionApproved"] is True
    assert latest_event["browserControlApproved"] is False

    browser_control_event = client.post(
        "/api/episodes/grandma-hospital-pilot/browser-handoffs/extension-event",
        json={
            "operatorApproved": True,
            "browserControlApproved": True,
            "provider": "gemini-web-image",
            "batchId": "batch-001",
            "cutId": "cut_001",
            "sceneId": "scene-001",
            "expectedFileName": "cut_001.png",
            "eventType": "gemini-prompt-fill",
            "status": "filled",
            "source": "codex-chrome-browser-control",
            "proofMode": "browser-control",
            "detail": "filledLength=120; generate remains operator-owned",
            "currentUrl": "https://gemini.google.com/app",
            "build": "20260607-gemini-image-handoff",
        },
    )
    assert browser_control_event.status_code == 200
    browser_event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[-1])
    assert browser_event["provider"] == "gemini-web-image"
    assert browser_event["status"] == "filled"
    assert browser_event["source"] == "codex-chrome-browser-control"
    assert browser_event["proofMode"] == "browser-control"
    assert browser_event["browserControlApproved"] is True
    assert browser_event["extensionApproved"] is False


def test_preproduction_plan_writes_storyboard_asset_briefs_and_episode_handoff(tmp_path):
    client = _episode_client(tmp_path)

    response = client.post("/api/episodes/preproduction-plan", json=_preproduction_payload(create_episode_plan=True))

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["status"] == "ready"
    assert data["manifest"]["gate"]["requiredBefore"] == [
        "gemini-web-image-reference",
        "grok-web-video-generation",
        "quality-ratchet-before-render",
        "quality-loop-iteration-ledger",
        "render",
    ]
    assert data["manifest"]["compatibility"]["usesApiProviders"] is False
    assert data["manifest"]["compatibility"]["usesPaidApiProviders"] is False
    assert data["manifest"]["qualityRatchetRequired"] is True
    assert data["manifest"]["qualityRatchet"]["requiredFields"] == [
        "previousBaseline",
        "rejectionCause",
        "changedLever",
        "expectedVisibleImprovement",
        "actualProof",
        "nextRatchet",
    ]
    assert data["manifest"]["qualityRatchet"]["status"] == "pending-proof"
    assert "source" in data["manifest"]["qualityRatchet"]["changedLever"]
    assert data["manifest"]["qualityLoopRequired"] is True
    assert data["manifest"]["qualityLoopStandardVersion"] == "2026-06-08-production-gate-quality-loop-v3"
    assert data["validation"]["errorCount"] == 0

    storyboard_path = Path(data["storyboardPath"])
    asset_briefs_path = Path(data["assetBriefsPath"])
    episode_request_path = Path(data["episodePlanRequestPath"])
    quality_loop_standard_path = Path(data["qualityLoopStandardPath"])
    quality_iteration_ledger_path = Path(data["qualityIterationLedgerPath"])
    assert storyboard_path.exists()
    assert asset_briefs_path.exists()
    assert episode_request_path.exists()
    assert Path(data["storyboardMarkdownPath"]).exists()
    assert quality_loop_standard_path.exists()
    assert quality_iteration_ledger_path.exists()
    assert data["manifest"]["paths"]["qualityLoopStandard"] == str(quality_loop_standard_path)
    assert data["manifest"]["paths"]["qualityIterationLedger"] == str(quality_iteration_ledger_path)

    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    first_beat = storyboard["beats"][0]
    third_beat = storyboard["beats"][2]
    assert first_beat["role"] == "hook"
    assert first_beat["onScreenText"] == "개막 전 이것만"
    assert "gemini-web-image" in first_beat["assetPlan"]["providers"]
    assert "grok-web-video" in first_beat["assetPlan"]["providers"]
    assert "printed football calendar" in first_beat["assetPlan"]["grokWebVideo"]["prompt"]
    assert first_beat["plannedTextCardAfter"]["text"] == "도착했으면\\N끊고 들어가기"
    assert first_beat["plannedTextCardAfter"]["durationSec"] == 0.24
    assert first_beat["plannedTextCardAfter"]["mode"] == "overlay"
    assert first_beat["plannedTextCardAfter"]["audioPolicy"] == "continuous-bgm-bed"
    assert "overlay chapter cue" in first_beat["assetPlan"]["grokWebVideo"]["prompt"]
    assert "BGM/audio bed continues uninterrupted" in first_beat["assetPlan"]["grokWebVideo"]["prompt"]
    assert "Do not render that chapter-card text" in first_beat["assetPlan"]["grokWebVideo"]["prompt"]
    assert third_beat["plannedTextCardAfter"] == {}
    assert "chapter cue" not in third_beat["assetPlan"]["grokWebVideo"]["prompt"]

    asset_briefs = json.loads(asset_briefs_path.read_text(encoding="utf-8"))
    assert asset_briefs["policy"]["usesApi"] is False
    assert asset_briefs["policy"]["usesPaidApi"] is False
    assert asset_briefs["policy"]["qualityRatchetRequired"] is True
    assert asset_briefs["beats"][0]["assetPlan"]["geminiWebImage"]["reviewGate"] == "image-reference-must-match-storyboard-before-video"
    assert asset_briefs["beats"][0]["plannedTextCardAfter"]["text"] == "도착했으면\\N끊고 들어가기"

    quality_loop_standard = json.loads(quality_loop_standard_path.read_text(encoding="utf-8"))
    assert quality_loop_standard["schema"] == "video-studio.quality-loop-standard.v1"
    assert quality_loop_standard["standardVersion"] == "2026-06-08-production-gate-quality-loop-v3"
    registry_keys = {item["contractKey"] for item in quality_loop_standard["contractRegistry"]}
    expected_contract_keys = {
        "policy",
        "topicContract",
        "promptContract",
        "outputContract",
        "captionLayoutContract",
        "voiceAudioContract",
        "editRhythmContract",
        "renderReviewContract",
        "publishReviewContract",
        "iterationContract",
        "resumeContract",
    }
    assert registry_keys == expected_contract_keys
    assert all(item["requiredForOutput"] is True for item in quality_loop_standard["contractRegistry"])
    assert quality_loop_standard["gateSystem"]["systemVersion"] == "2026-06-08-unified-quality-gate-system-v1"
    phase_keys = {item["phaseKey"] for item in quality_loop_standard["gateSystem"]["phases"]}
    assert {"preproduction", "episode-output", "render-quality", "final-readiness", "post-publish-loop"} <= phase_keys
    assert set(quality_loop_standard["gateSystem"]["qualityLoopContracts"][0]) >= {
        "contractKey",
        "gateKey",
        "requiredForOutput",
    }
    assert quality_loop_standard["policy"]["failureMustNameNextMutation"] is True
    assert "visible first-second physical action" in quality_loop_standard["promptContract"]["grokShotInstruction"]["mustInclude"]
    assert "planned transition cue context when present" in quality_loop_standard["promptContract"]["grokShotInstruction"]["mustInclude"]
    assert "rendering editor-only transition cue words inside source video" in quality_loop_standard["promptContract"]["grokShotInstruction"]["mustAvoid"]
    assert "layout" in quality_loop_standard["iterationContract"]["allowedStages"]
    assert "audio" in quality_loop_standard["iterationContract"]["allowedStages"]
    assert "bgm" in quality_loop_standard["iterationContract"]["allowedStages"]
    assert "edit-rhythm" in quality_loop_standard["iterationContract"]["allowedStages"]
    assert "render-review" in quality_loop_standard["iterationContract"]["allowedStages"]
    assert quality_loop_standard["captionLayoutContract"]["canvas"]["contentSafeZone"] == {"x": [60, 950], "y": [100, 1440]}
    assert quality_loop_standard["captionLayoutContract"]["textDensity"]["koreanMaxCharsPerLine"] == 16
    assert quality_loop_standard["captionLayoutContract"]["textDensity"]["maxLines"] == 2
    assert "phoneContactSheetPath" in quality_loop_standard["captionLayoutContract"]["renderReviewEvidenceRequired"]
    assert "subjectOcclusionVerdict" in quality_loop_standard["captionLayoutContract"]["renderReviewEvidenceRequired"]
    assert "stage=caption or stage=layout" in quality_loop_standard["iterationContract"]["captionLayoutFailureRequires"]
    assert (
        "gateEvidencePaths with contact sheet or render review path"
        in quality_loop_standard["iterationContract"]["captionLayoutFailureRequires"]
    )
    assert quality_loop_standard["voiceAudioContract"]["zeroPaidDefault"] is True
    assert "edge-tts" in quality_loop_standard["voiceAudioContract"]["allowedZeroPaidProviders"]
    assert "rawTtsDurationSec" in quality_loop_standard["voiceAudioContract"]["requiredEvidence"]
    assert "bgmDuckReview" in quality_loop_standard["voiceAudioContract"]["requiredEvidence"]
    assert quality_loop_standard["editRhythmContract"]["defaultShortformTargets"]["firstTwoSecondHookRequired"] is True
    assert quality_loop_standard["editRhythmContract"]["transitionCueDecision"]["defaultMode"] == "none"
    assert quality_loop_standard["editRhythmContract"]["transitionCueDecision"]["fullCardIsException"] is True
    assert "overlay" in quality_loop_standard["editRhythmContract"]["transitionCueDecision"]["shortformTwelveSecondPreference"]
    assert quality_loop_standard["editRhythmContract"]["plannedTextCardBreaks"]["optionalPerBeatField"] == "plannedTextCardAfter"
    assert quality_loop_standard["editRhythmContract"]["plannedTextCardBreaks"]["backCompatOnly"] is True
    assert "averageCutDurationSec" in quality_loop_standard["editRhythmContract"]["requiredEvidence"]
    assert "sha256" in quality_loop_standard["renderReviewContract"]["requiredEvidence"]
    assert "renderQualityReportPath" in quality_loop_standard["renderReviewContract"]["requiredEvidence"]
    assert "phoneSizedFullWatch" in quality_loop_standard["publishReviewContract"]["uploadReadinessRequires"]
    assert "sameDayUploadApproval" in quality_loop_standard["publishReviewContract"]["phoneReviewEvidence"]
    assert first_beat["layoutVariantKey"] == "routine-top-hook"
    assert quality_loop_standard["storyboardSnapshot"][0]["layoutVariantKey"] == "routine-top-hook"
    assert quality_loop_standard["storyboardSnapshot"][0]["captionPreset"] == "top-hook"
    assert quality_loop_standard["storyboardSnapshot"][0]["plannedTextCardAfter"]["text"] == "도착했으면\\N끊고 들어가기"
    assert "quality-iteration-ledger.json" in quality_loop_standard["resumeContract"]["nextSessionMustRead"][2]
    assert quality_loop_standard["iterationContract"]["failedIterationRequires"] == [
        "observedFailure",
        "nextMutation",
        "changedLever",
    ]
    quality_iteration_ledger = json.loads(quality_iteration_ledger_path.read_text(encoding="utf-8"))
    assert quality_iteration_ledger["schema"] == "video-studio.quality-iteration-ledger.v1"
    assert quality_iteration_ledger["status"] == "awaiting-first-iteration"
    assert quality_iteration_ledger["iterations"] == []
    assert quality_iteration_ledger["nextRequiredAction"]["status"] == "awaiting-first-iteration"

    episode_plan = data["episodePlan"]
    assert episode_plan["ok"] is True
    assert episode_plan["validation"]["ok"] is True
    assert episode_plan["outputGate"]["status"] == "pass"
    assert episode_plan["outputGate"]["qualityLoopRequired"] is True
    assert episode_plan["outputGate"]["gateSystem"]["systemVersion"] == "2026-06-08-unified-quality-gate-system-v1"
    assert episode_plan["outputGate"]["gateSystem"]["surface"] == "episode-output"
    assert episode_plan["outputGate"]["gateSystem"]["contractSummary"]["requiredContractCount"] == 11
    output_checks = {item["key"]: item for item in episode_plan["outputGate"]["checks"]}
    assert output_checks["captionLayoutStandard"]["status"] == "pass"
    assert output_checks["voiceAudioStandard"]["status"] == "pass"
    assert output_checks["editRhythmStandard"]["status"] == "pass"
    assert output_checks["renderReviewStandard"]["status"] == "pass"
    assert output_checks["publishReviewStandard"]["status"] == "pass"
    assert output_checks["iterationStandard"]["status"] == "pass"
    assert output_checks["resumeStandard"]["status"] == "pass"
    assert episode_plan["manifest"]["counts"]["cuts"] == 3
    assert Path(episode_plan["browserHandoffsPath"]).exists()

    handoffs_response = client.get("/api/episodes/world-cup-opener-check/browser-handoffs")
    assert handoffs_response.status_code == 200
    handoffs = handoffs_response.get_json()["browserHandoffs"]
    assert handoffs["outputGate"]["status"] == "pass"
    assert handoffs["outputGate"]["qualityLoopRequired"] is True
    image_cut = handoffs["batches"]["geminiWebImage"][0]["cuts"][0]
    assert image_cut["promptOutputGate"]["status"] == "pass"
    assert image_cut["reviewStatus"] == "pending-image-review"
    assert "World Cup" in image_cut["prompt"] or "football" in image_cut["prompt"]
    assert image_cut["plannedTextCardAfter"]["text"] == "도착했으면\\N끊고 들어가기"
    assert image_cut["plannedTextCardAfter"]["mode"] == "overlay"
    assert "overlay chapter cue" in image_cut["prompt"]
    assert "BGM/audio bed continues uninterrupted" in image_cut["prompt"]
    assert "Do not render that chapter-card text" in image_cut["prompt"]
    assert "Reference image for a long-form Korean story video cut" not in image_cut["prompt"]
    assert "Character bible excerpt" not in image_cut["prompt"]
    assert "Vertical 9:16 reference image for a short-form video storyboard" in image_cut["prompt"]
    assert handoffs["providers"]["grokWebVideo"]["status"] == "queue-ready"
    grok_scene = handoffs["batches"]["grokWebVideo"][0]["handoffRequest"]["draftScenes"][0]
    assert "Long-form Korean story raw footage" not in grok_scene["grok_prompt"]
    assert "Character bible excerpt" not in grok_scene["grok_prompt"]
    assert "Raw vertical 9:16 phone-camera MP4" in grok_scene["grok_prompt"]
    assert "First second:" in grok_scene["grok_prompt"]
    assert grok_scene["planned_text_card_after"]["text"] == "도착했으면\\N끊고 들어가기"
    assert grok_scene["planned_text_card_after"]["mode"] == "overlay"
    assert "overlay chapter cue" in grok_scene["grok_prompt"]
    assert "BGM/audio bed continues uninterrupted" in grok_scene["grok_prompt"]
    assert "Do not render that chapter-card text" in grok_scene["grok_prompt"]
    assert grok_scene["visual_prompt"].startswith("A hand circles the opening date")
    assert grok_scene["hook_note"].startswith("A hand circles the opening date")
    assert not grok_scene["continuity_note"].startswith("Keep ")
    assert "host hands" in grok_scene["continuity_note"]

    preproduction_get = client.get("/api/episodes/world-cup-opener-check/preproduction")
    assert preproduction_get.status_code == 200
    preproduction_payload = preproduction_get.get_json()
    assert preproduction_payload["preproduction"]["status"] == "ready"
    assert preproduction_payload["qualityLoopStandard"]["standardVersion"] == "2026-06-08-production-gate-quality-loop-v3"
    assert preproduction_payload["qualityIterationLedger"]["nextRequiredAction"]["status"] == "awaiting-first-iteration"


def test_preproduction_regeneration_refreshes_stale_text_card_prompt(tmp_path):
    client = _episode_client(tmp_path)
    payload = _preproduction_payload(create_episode_plan=True)
    stale_clause = (
        "Edit rhythm: after this source clip, the editor will insert a 1.0s text-only "
        "chapter card reading \"old\". Keep this source clip self-contained and end on a "
        "clean object or action state. Do not render that chapter-card text inside the source clip."
    )
    payload["storyboardBeats"][0]["assetPlan"] = {
        "providers": ["gemini-web-image", "grok-web-video"],
        "geminiWebImage": {
            "prompt": f"Old Gemini prompt. {stale_clause}",
        },
        "grokWebVideo": {
            "prompt": f"Old Grok prompt. {stale_clause}",
        },
    }

    response = client.post("/api/episodes/preproduction-plan", json=payload)

    assert response.status_code == 200
    data = response.get_json()
    storyboard = json.loads(Path(data["storyboardPath"]).read_text(encoding="utf-8"))
    first_beat = storyboard["beats"][0]
    gemini_prompt = first_beat["assetPlan"]["geminiWebImage"]["prompt"]
    grok_prompt = first_beat["assetPlan"]["grokWebVideo"]["prompt"]
    assert "0.24s overlay chapter cue" in gemini_prompt
    assert "0.24s overlay chapter cue" in grok_prompt
    assert "BGM/audio bed continues uninterrupted" in gemini_prompt
    assert "BGM/audio bed continues uninterrupted" in grok_prompt
    assert "1.0s text-only chapter card" not in gemini_prompt
    assert "1.0s text-only chapter card" not in grok_prompt


def test_episode_output_gate_blocks_unregistered_quality_contracts(tmp_path):
    client = _episode_client(tmp_path)
    plan = client.post("/api/episodes/preproduction-plan", json=_preproduction_payload(create_episode_plan=False)).get_json()
    standard_path = Path(plan["qualityLoopStandardPath"])
    standard = json.loads(standard_path.read_text(encoding="utf-8"))
    standard["thumbnailReviewContract"] = {
        "requiredEvidence": ["firstFramePath", "thumbnailContactSheetPath"],
    }
    standard_path.write_text(json.dumps(standard, ensure_ascii=False), encoding="utf-8")
    episode_request = json.loads(Path(plan["episodePlanRequestPath"]).read_text(encoding="utf-8"))

    response = client.post("/api/episodes/plan", json=episode_request)

    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    assert data["outputGate"]["status"] == "blocked"
    registry_check = next(
        item
        for item in data["outputGate"]["checks"]
        if item["key"] == "qualityLoopContractRegistry"
    )
    assert registry_check["status"] == "fail"
    assert "thumbnailReviewContract" in registry_check["detail"]


def test_preproduction_quality_loop_requires_next_mutation_for_failed_iterations(tmp_path):
    client = _episode_client(tmp_path)
    client.post("/api/episodes/preproduction-plan", json=_preproduction_payload(create_episode_plan=True))

    response = client.post(
        "/api/episodes/world-cup-opener-check/preproduction/quality-loop",
        json={
            "stage": "prompt",
            "status": "fail",
            "observedFailure": "Prompt still feels like production memo.",
            "changedLever": ["prompt"],
        },
    )

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert "nextMutation is required" in response.get_json()["error"]


def test_preproduction_quality_loop_requires_pending_mutation_resolution(tmp_path):
    client = _episode_client(tmp_path)
    client.post("/api/episodes/preproduction-plan", json=_preproduction_payload(create_episode_plan=True))
    failed = client.post(
        "/api/episodes/world-cup-opener-check/preproduction/quality-loop",
        json={
            "stage": "prompt",
            "status": "fail",
            "observedFailure": "Prompt still reads like a production memo.",
            "changedLever": ["prompt"],
            "nextMutation": {
                "summary": "Rewrite the hook prompt around a single object-state change.",
                "promptChange": "Lead with the hand circling the date and remove meta text.",
            },
            "gateEvidencePaths": ["storage/qa/world-cup-opener-check/prompt-review.json"],
        },
    )
    assert failed.status_code == 200
    failed_data = failed.get_json()
    pending_id = failed_data["iteration"]["iterationId"]
    assert failed_data["gateSystem"]["surface"] == "quality-loop"
    assert failed_data["gateSystem"]["blockingPhaseKey"] == "quality-iteration"
    assert failed_data["blockingPhaseKey"] == "quality-iteration"
    assert failed_data["loopSummary"]["nextRequiredAction"]["status"] == "apply-next-mutation"
    assert failed_data["loopSummary"]["requiresMutationResolution"] is True

    blocked = client.post(
        "/api/episodes/world-cup-opener-check/preproduction/quality-loop",
        json={
            "stage": "prompt",
            "status": "pass",
            "changedLever": ["prompt"],
            "passEvidence": {"promptQuality": "ready"},
        },
    )

    assert blocked.status_code == 400
    blocked_error = blocked.get_json()["error"]
    assert "resolvesIterationId must match" in blocked_error
    assert "appliedMutation is required" in blocked_error

    resolved = client.post(
        "/api/episodes/world-cup-opener-check/preproduction/quality-loop",
        json={
            "stage": "prompt",
            "status": "pass",
            "changedLever": ["prompt"],
            "resolvesIterationId": pending_id,
            "appliedMutation": {
                "summary": "Rewrote the prompt around the hand circling the opening date.",
                "promptChange": "Removed meta text and started with the object-state change.",
            },
            "mutationEvidence": {"promptDiff": "visual_action seed now leads the Grok prompt"},
            "passEvidence": {"promptQuality": "ready"},
        },
    )

    assert resolved.status_code == 200
    data = resolved.get_json()
    assert data["iteration"]["resolvesIterationId"] == pending_id
    assert data["iteration"]["appliedMutation"]["promptChange"].startswith("Removed meta")
    assert data["ledger"]["nextRequiredAction"]["status"] == "advance-next-gate"
    assert data["gateSystem"]["blockingPhaseKey"] == ""
    assert data["gateSystem"]["qualityIterationSummary"]["nextRequiredActionStatus"] == "advance-next-gate"


def test_preproduction_quality_loop_requires_evidence_for_caption_layout_failures(tmp_path):
    client = _episode_client(tmp_path)
    client.post("/api/episodes/preproduction-plan", json=_preproduction_payload(create_episode_plan=True))

    response = client.post(
        "/api/episodes/world-cup-opener-check/preproduction/quality-loop",
        json={
            "stage": "layout",
            "status": "fail",
            "observedFailure": "Lower caption covers the phone reminder toggle at phone size.",
            "changedLever": ["layout", "caption"],
            "nextMutation": {
                "summary": "Move the lower-info caption to a compact top-left chip and shorten the line break.",
                "layoutChange": "Switch from routine-lower-info to hands-proof for the affected beat.",
            },
        },
    )

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert "gateEvidencePaths is required for caption or layout failures" in response.get_json()["error"]


def test_preproduction_quality_loop_records_caption_layout_failure_with_evidence(tmp_path):
    client = _episode_client(tmp_path)
    client.post("/api/episodes/preproduction-plan", json=_preproduction_payload(create_episode_plan=True))

    response = client.post(
        "/api/episodes/world-cup-opener-check/preproduction/quality-loop",
        json={
            "stage": "layout",
            "status": "fail",
            "observedFailure": "Top hook and lower caption make the phone screen unreadable in the first two seconds.",
            "changedLever": ["layout", "caption"],
            "nextMutation": {
                "summary": "Use one compact top-left chip, shorten Korean caption to two 16-char lines, and rerender a contact sheet.",
                "captionChange": "Break the hook into two short Korean lines and remove the lower duplicate.",
                "layoutChange": "Use hands-proof instead of routine-top-hook on the phone-screen beat.",
            },
            "gateEvidencePaths": [
                "storage/qa/world-cup-opener-check/layout-contact-sheet.jpg",
                "storage/renders/world-cup-opener-check/render-quality-report.json",
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["iteration"]["stage"] == "layout"
    assert data["iteration"]["nextMutation"]["captionChange"].startswith("Break the hook")
    assert data["ledger"]["nextRequiredAction"]["status"] == "apply-next-mutation"
    assert data["gateSystem"]["blockingPhaseKey"] == "quality-iteration"
    assert data["loopSummary"]["observedFailure"].startswith("Top hook")
    assert "storage/qa/world-cup-opener-check/layout-contact-sheet.jpg" in data["loopSummary"]["evidencePaths"]


def test_preproduction_quality_loop_requires_evidence_for_voice_audio_failures(tmp_path):
    client = _episode_client(tmp_path)
    client.post("/api/episodes/preproduction-plan", json=_preproduction_payload(create_episode_plan=True))

    response = client.post(
        "/api/episodes/world-cup-opener-check/preproduction/quality-loop",
        json={
            "stage": "voice",
            "status": "fail",
            "observedFailure": "Zero-paid TTS sounded slow and was compressed into the scene duration.",
            "changedLever": ["voice", "audio"],
            "nextMutation": {
                "summary": "Shorten narration density and regenerate Edge TTS with a faster approved voice candidate.",
                "voiceChange": "Try a different zero-paid Korean voice and record raw duration before render.",
            },
        },
    )

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert "gateEvidencePaths is required for voice or audio failures" in response.get_json()["error"]


def test_preproduction_quality_loop_records_edit_rhythm_failure_with_evidence(tmp_path):
    client = _episode_client(tmp_path)
    client.post("/api/episodes/preproduction-plan", json=_preproduction_payload(create_episode_plan=True))

    response = client.post(
        "/api/episodes/world-cup-opener-check/preproduction/quality-loop",
        json={
            "stage": "edit-rhythm",
            "status": "fail",
            "observedFailure": "The hook is visible but the second cut holds too long and loses the phone viewer.",
            "changedLever": ["edit rhythm", "first frame"],
            "nextMutation": {
                "summary": "Move the reminder-toggle beat earlier and cap the average cut duration under 4.5 seconds.",
                "editChange": "Reorder scene-003 before scene-002 and shorten the long hold.",
            },
            "gateEvidencePaths": [
                "storage/qa/world-cup-opener-check/edit-rhythm-contact-sheet.jpg",
                "storage/renders/world-cup-opener-check/render-quality-report.json",
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["iteration"]["stage"] == "edit-rhythm"
    assert data["iteration"]["nextMutation"]["editChange"].startswith("Reorder")
    assert data["ledger"]["nextRequiredAction"]["summary"].startswith("Move the reminder-toggle")


def test_preproduction_quality_loop_records_failure_and_spec_change(tmp_path):
    client = _episode_client(tmp_path)
    plan = client.post("/api/episodes/preproduction-plan", json=_preproduction_payload(create_episode_plan=True)).get_json()

    response = client.post(
        "/api/episodes/world-cup-opener-check/preproduction/quality-loop",
        json={
            "stage": "motion-source",
            "status": "needs-spec-change",
            "changedLever": ["source", "storyboard"],
            "observedFailure": "Grok source matched the words but looked like generic AI desk montage.",
            "nextMutation": {
                "summary": "Replace the beat with one large prop state change and require a reference still before the next Grok attempt.",
                "promptChange": "Start with the physical state change, then subject and setting.",
                "sourceChange": "Generate or import a reference image before motion generation.",
            },
            "specChangeProposal": {
                "currentRule": "Prompt requires a first-second action.",
                "whyInsufficient": "The action can still be interpreted as tiny desk activity that reads generic.",
                "proposedRule": "First-second action must visibly change object state or subject position at phone size.",
                "verificationPlan": "Focused pytest must reject a failed iteration without nextMutation and accept the stronger spec proposal.",
            },
            "gateEvidencePaths": [plan["qualityLoopStandardPath"]],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["iteration"]["status"] == "needs-spec-change"
    assert data["ledger"]["nextRequiredAction"]["status"] == "apply-next-mutation"
    assert data["ledger"]["nextRequiredAction"]["summary"].startswith("Replace the beat")
    assert data["standard"]["pendingSpecChangeProposal"]["proposedRule"].startswith("First-second action")
    assert data["gateSystem"]["surface"] == "quality-loop"
    assert data["gateSystem"]["contractSummary"]["requiredContractCount"] == 11
    assert data["gateSystem"]["blockingPhaseKey"] == "quality-iteration"
    assert data["phaseStates"][0]["phaseKey"] == "quality-iteration"
    assert data["loopSummary"]["nextMutation"]["sourceChange"].startswith("Generate or import")

    ledger = json.loads(Path(data["qualityIterationLedgerPath"]).read_text(encoding="utf-8"))
    assert ledger["iterations"][0]["stage"] == "motion-source"
    assert ledger["iterations"][0]["nextMutation"]["sourceChange"].startswith("Generate or import")

    get_response = client.get("/api/episodes/world-cup-opener-check/preproduction/quality-loop")
    assert get_response.status_code == 200
    get_data = get_response.get_json()
    assert get_data["qualityIterationLedger"]["nextRequiredAction"]["status"] == "apply-next-mutation"
    assert get_data["gateSystem"]["blockingPhaseKey"] == "quality-iteration"
    assert get_data["loopSummary"]["nextRequiredAction"]["status"] == "apply-next-mutation"


def test_preproduction_prompt_output_blocks_until_failed_iteration_mutation_is_applied(tmp_path):
    client = _episode_client(tmp_path)
    client.post("/api/episodes/preproduction-plan", json=_preproduction_payload(create_episode_plan=True))
    client.post(
        "/api/episodes/world-cup-opener-check/preproduction/quality-loop",
        json={
            "stage": "prompt",
            "status": "fail",
            "changedLever": ["prompt", "storyboard"],
            "observedFailure": "Prompt produced another generic production memo instead of a shot instruction.",
            "nextMutation": {
                "summary": "Rewrite the first beat around one visible object-state change before returning another prompt.",
                "promptChange": "Start with the physical object-state change and remove review prose.",
            },
        },
    )

    response = client.get(
        "/api/episodes/world-cup-opener-check/browser-handoffs/gemini-web-image/batch-001/extension-command"
        "?operatorApproved=true&cutId=cut_001"
    )

    assert response.status_code == 409
    data = response.get_json()
    assert data["ok"] is False
    assert "prompt output gate blocked" in data["error"]
    assert data["promptOutputGate"]["status"] == "blocked"
    assert data["promptOutputGate"]["nextRequiredAction"]["status"] == "apply-next-mutation"
    assert "prompt" not in data


def test_preproduction_asset_candidate_review_requires_accepted_motion_sources(tmp_path):
    client = _episode_client(tmp_path)
    client.post("/api/episodes/preproduction-plan", json=_preproduction_payload(create_episode_plan=True))
    source_dir = tmp_path / "storage" / "episodes" / "world-cup-opener-check" / "sources"
    source_dir.mkdir(parents=True)

    candidates = []
    for index, beat in enumerate(_preproduction_payload()["storyboardBeats"], start=1):
        beat_id = beat["beatId"]
        scene_id = f"scene-{index:03d}"
        mp4 = source_dir / f"{scene_id}.grok.mp4"
        mp4.write_bytes(b"fake mp4 bytes for local source proof")
        base_review = {
            "accepted": True,
            "storyboardMatch": True,
            "artifactFree": True,
            "captionSafe": True,
            "phoneSizeWatch": True,
            "sourceProvenanceOk": True,
            "qualityReviewNote": "Phone-size review shows the beat action clearly and avoids the rejected generic montage look.",
            "sourceRationale": "Chosen because it makes the storyboard action visible instead of using filler.",
        }
        candidates.append({
            "beatId": beat_id,
            "sceneId": scene_id,
            "provider": "gemini-web-image",
            "sourceUrl": f"https://gemini.google.com/app/result/{beat_id}",
            "review": base_review,
        })
        candidates.append({
            "beatId": beat_id,
            "sceneId": scene_id,
            "provider": "grok-web-video",
            "sourcePath": str(mp4.relative_to(tmp_path)),
            "review": {
                **base_review,
                "firstSecondAction": True,
                "noGenericBroll": True,
            },
        })

    response = client.post(
        "/api/episodes/world-cup-opener-check/preproduction/asset-candidates",
        json={"candidates": candidates},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["status"] == "ready-for-render"
    assert data["validation"]["readyBeatCount"] == 3
    assert data["validation"]["acceptedMotionCount"] == 3
    assert data["validation"]["acceptedReferenceCount"] == 3
    source_map_path = Path(data["acceptedSourceMapPath"])
    assert source_map_path.exists()
    source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
    assert source_map["status"] == "ready-for-render"
    assert source_map["qualityRatchetRequired"] is True
    assert source_map["qualityRatchet"]["status"] == "pending-proof"
    assert all(scene["accepted"] for scene in source_map["scenes"])
    assert source_map["scenes"][0]["acceptedCandidate"]["sourceCheck"]["exists"] is True

    get_response = client.get("/api/episodes/world-cup-opener-check/preproduction/asset-candidates")
    assert get_response.status_code == 200
    candidate_review = get_response.get_json()["candidateReview"]
    assert candidate_review["status"] == "ready-for-render"
    assert candidate_review["qualityRatchetRequired"] is True
    assert candidate_review["qualityRatchet"]["requiredFields"]


def test_preproduction_asset_candidate_review_blocks_without_motion_sources(tmp_path):
    client = _episode_client(tmp_path)
    client.post("/api/episodes/preproduction-plan", json=_preproduction_payload(create_episode_plan=True))

    response = client.post(
        "/api/episodes/world-cup-opener-check/preproduction/asset-candidates",
        json={"candidates": []},
    )

    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    assert data["status"] == "blocked"
    messages = [item["message"] for item in data["validation"]["errors"]]
    assert messages.count("each storyboard beat needs one accepted Grok/operator motion source before render") == 3
    assert Path(data["candidateReviewPath"]).exists()


def test_preproduction_syncs_accepted_grok_review_candidates_into_source_gate(tmp_path):
    client = _episode_client(tmp_path)
    client.post("/api/episodes/preproduction-plan", json=_preproduction_payload(create_episode_plan=True))
    handoff_id = "world-cup-opener-check-batch-001"
    handoff_dir = tmp_path / "storage" / "grok-handoffs" / handoff_id
    incoming_dir = handoff_dir / "incoming"
    incoming_dir.mkdir(parents=True)
    review_decisions = {}
    scenes = []
    for index, beat in enumerate(_preproduction_payload()["storyboardBeats"], start=1):
        scene_id = f"scene-{index:03d}"
        file_name = f"{scene_id}.grok.mp4"
        source_file = incoming_dir / file_name
        source_file.write_bytes(b"fake mp4 bytes for synced grok source")
        scenes.append({
            "sceneId": scene_id,
            "grok_prompt": f"Raw vertical 9:16 phone-camera MP4 for {scene_id}",
        })
        review_decisions[scene_id] = {
            "sceneId": scene_id,
            "accepted": True,
            "selectedFileName": file_name,
            "firstTwoSecondHook": True,
            "artifactFree": True,
            "continuityOk": True,
            "captionSafe": True,
            "shotLockMatch": True,
            "sceneAssemblyOk": True,
            "visualQualityVerdict": "pass",
            "sourceProvenanceConfirmed": True,
            "sourceRationale": "The selected Grok take shows the storyboard action instead of a generic filler shot.",
            "qualityReviewNote": "Manual review confirms the first-second action, stable subject, clean frame, and no visible artifacts.",
            "selectedCandidate": {
                "fileName": file_name,
                "sourcePath": str(source_file.relative_to(tmp_path)),
                "sourceProvenance": {
                    "status": "operator-uploaded-grok-mp4",
                    "acceptAsGrokMainSource": True,
                },
            },
        }
    (handoff_dir / "handoff.json").write_text(json.dumps({
        "projectId": handoff_id,
        "scenes": scenes,
        "reviewDecisions": review_decisions,
    }, ensure_ascii=False), encoding="utf-8")

    blocked = client.post(
        "/api/episodes/world-cup-opener-check/preproduction/sync-grok-candidates",
        json={"operatorApproved": True},
    )

    assert blocked.status_code == 400
    blocked_data = blocked.get_json()
    assert blocked_data["syncedCandidateCount"] == 3
    blocked_messages = [item["message"] for item in blocked_data["validation"]["errors"]]
    assert blocked_messages.count("candidate must be reviewed at phone size") == 3
    assert blocked_messages.count("motion source must not be generic filler B-roll") == 3

    ready = client.post(
        "/api/episodes/world-cup-opener-check/preproduction/sync-grok-candidates",
        json={
            "operatorApproved": True,
            "phoneSizeWatchApproved": True,
            "noGenericBrollApproved": True,
        },
    )

    assert ready.status_code == 200
    data = ready.get_json()
    assert data["ok"] is True
    assert data["status"] == "ready-for-render"
    assert data["syncedCandidateCount"] == 3
    assert data["validation"]["acceptedMotionCount"] == 3
    source_map = json.loads(Path(data["acceptedSourceMapPath"]).read_text(encoding="utf-8"))
    assert source_map["status"] == "ready-for-render"
    assert source_map["scenes"][0]["acceptedCandidate"]["provider"] == "grok-web-video"


def test_preproduction_plan_blocks_generic_story_without_why_now(tmp_path):
    client = _episode_client(tmp_path)
    payload = _preproduction_payload()
    payload["episodeId"] = "generic-reset"
    payload["title"] = "퇴근 후 루틴"
    payload["topicBrief"]["trendAnchor"] = ""
    payload["topicBrief"]["whyNow"] = ""
    payload["topicBrief"]["viewerQuestion"] = "퇴근 후 루틴?"
    payload["topicBrief"]["angle"] = "퇴근 후 루틴을 편하게 보여준다"

    response = client.post("/api/episodes/preproduction-plan", json=payload)

    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    assert data["status"] == "blocked"
    messages = [item["message"] for item in data["validation"]["errors"]]
    assert any("timely why-now" in message for message in messages)
    assert any("generic routine/reset topics" in message for message in messages)


def test_episode_validation_reports_duplicate_cut_errors_and_duration_warnings(tmp_path):
    client = _episode_client(tmp_path)
    payload = _pilot_payload()
    payload["shots"][1]["cutId"] = "cut_001"
    payload["shots"][0]["plannedDurationSec"] = 3
    payload["shots"][0]["characters"] = []

    response = client.post("/api/episodes", json=payload)

    assert response.status_code == 400
    data = response.get_json()
    assert data["ok"] is False
    assert "episode output gate blocked" in data["error"]
    assert "shotSyncValidation" in data["error"]

    validate = client.get("/api/episodes/grandma-hospital-pilot/validate")
    assert validate.status_code == 404


def test_episode_plan_rejects_missing_shots(tmp_path):
    client = _episode_client(tmp_path)

    response = client.post("/api/episodes/plan", json={"episodeId": "empty"})

    assert response.status_code == 400
    assert "shots" in response.get_json()["error"]


def test_episode_batches_accept_cut_id_prefix_variants(tmp_path):
    client = _episode_client(tmp_path)
    payload = _pilot_payload()
    payload["episodeId"] = "cut-id-prefix-variants"
    payload["shots"][0]["cutId"] = "CUT-041"
    payload["shots"][1]["cutId"] = "hospital_cut_042"

    response = client.post("/api/episodes/plan", json=payload)

    assert response.status_code == 200
    batch_response = client.get("/api/episodes/cut-id-prefix-variants/grok-batches")
    scenes = batch_response.get_json()["batches"][0]["handoffRequest"]["draftScenes"]
    assert [scene["scene_num"] for scene in scenes] == [41, 42]


def test_ai_web_companion_manifest_includes_gemini_adapter():
    extension_dir = Path(__file__).resolve().parents[1] / "tools" / "chrome-grok-companion"
    manifest = json.loads((extension_dir / "manifest.json").read_text(encoding="utf-8"))
    background = (extension_dir / "background.js").read_text(encoding="utf-8")
    gemini_content = (extension_dir / "content_gemini.js").read_text(encoding="utf-8")

    assert manifest["name"] == "Video Studio AI Web Companion"
    assert "https://gemini.google.com/*" in manifest["host_permissions"]
    assert "https://gemini.google-b197145817.com/*" in manifest["host_permissions"]
    gemini_scripts = [item for item in manifest["content_scripts"] if "content_gemini.js" in item.get("js", [])]
    assert gemini_scripts
    assert "https://gemini.google-b197145817.com/*" in gemini_scripts[0]["matches"]
    assert "provider: event.provider || command.provider" in background
    assert "20260607-gemini-image-handoff" in gemini_content
    assert "gemini-web-image" in gemini_content
    assert "function isGeminiHost" in gemini_content
    assert "gemini\\.google-[a-z0-9-]+\\.com" in gemini_content
    assert "postBridgeEvent" in gemini_content
    assert "bridge-post-event" in gemini_content
    assert "load-command-url" in gemini_content
    assert "fetch(request.commandUrl)" not in gemini_content
    assert "function postBridgeEvent" in background
    assert "PROVIDER_CAPABILITIES" in gemini_content
    assert "canClickGenerate: false" in gemini_content
    assert "canImportResult: false" in gemini_content
    assert "gemini-content-ready" in gemini_content
    assert "gemini-command-loaded" in gemini_content
    assert "gemini-command-load-failed" in gemini_content
    assert "gemini-prompt-target-found" in gemini_content
    assert "gemini-prompt-target-missing" in gemini_content
    assert "Gemini companion supports fill-prompt/probe only" in gemini_content
    assert "generate remains operator-owned" in gemini_content
