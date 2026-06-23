from __future__ import annotations

from worker.render.production_gate_orchestrator import build_process_gate_audit, evaluate_production_gates


def _source(source_id: str, source_type: str) -> dict:
    return {
        "sourceId": source_id,
        "sourceType": source_type,
        "url": f"https://example.com/{source_id}",
        "observation": "Concrete observation.",
    }


def _material(*, topic_pass: bool = False, source_complete: bool = True) -> dict:
    source_ledger = [
        _source("search-01", "google-search"),
        _source("trend-01", "google-trends-kr"),
        _source("trend-02", "naver-datalab"),
        _source("video-01", "youtube-search"),
        _source("community-01", "korean-community"),
    ] if source_complete else [_source("search-01", "google-search")]
    gate_history = [{"stage": "material-intake", "status": "pass"}]
    if topic_pass:
        gate_history.append({"stage": "topic-discovery", "status": "pass"})
    return {
        "materialId": "mat-test",
        "title": "테스트 소재",
        "centralQuestion": "왜 지금 이 소재가 필요한가?",
        "searchSeed": "테스트 소재",
        "sourceLedger": source_ledger,
        "gateHistory": gate_history,
    }


def _chapter(index: int) -> dict:
    chapter_id = f"chapter-{index:02d}"
    return {
        "chapterId": chapter_id,
        "title": f"Chapter {index}",
        "claim": f"Claim {index}",
        "segments": [
            {"segmentId": f"{chapter_id}-seg-01"},
            {"segmentId": f"{chapter_id}-seg-02"},
            {"segmentId": f"{chapter_id}-seg-03"},
        ],
        "evidence": [
            {
                "evidenceId": f"evidence-{index:02d}",
                "sourceUrl": f"https://example.com/source-{index}",
                "rightsStatus": "operator-approved",
            }
        ],
    }


def _release_packet() -> dict:
    chapters = [_chapter(index) for index in range(1, 7)]
    return {
        "formatProfile": "longform_10m",
        "durationSec": 610,
        "chapters": chapters,
        "storyPackageReview": {
            "firstTenSecondExpectationMet": True,
            "titleThumbnailExpectationMet": True,
            "payoffPromiseResolved": True,
        },
        "sourceReviewImport": {
            "chapterContinuityPassRatio": 0.92,
            "primarySubjectIdentityDrift": False,
            "primarySubjectScaleJump": False,
            "unexplainedCameraWorldJump": False,
            "unresolvedSourceDefects": [],
            "acceptedChapterCount": 6,
            "acceptedSources": [
                {
                    "sourceId": "source-001",
                    "provider": "grok-web-video",
                    "rightsStatus": "licensed",
                    "commercialUseAllowed": True,
                }
            ],
        },
        "scriptTtsCaptionReview": {
            "status": "pass",
            "voicePlan": {"provider": "edge-tts", "voiceId": "ko-KR-SunHiNeural", "targetWpm": 140},
            "maxCaptionTtsDriftSec": 0.18,
            "noDuplicateCaptionTts": True,
            "captionExplainsMissingVisual": False,
            "safeZoneReviewed": True,
        },
        "editorialReleaseReview": {
            "directedEdit": True,
            "motivatedCutPassRatio": 0.9,
            "layoutSafeZoneReviewed": True,
            "noUnboundEffectCues": True,
            "noHudComparisonReviewed": True,
            "unresolvedEditorialIssues": [],
        },
        "audioReleaseReview": {
            "audioStreamExists": True,
            "narrationDuckingEnabled": True,
            "chapterAudioBedsCovered": True,
            "everyCueBoundToVisibleEvent": True,
            "maxPeakDb": -4.0,
            "meanDb": -20.0,
        },
        "fullWatchReview": {
            "completed": True,
            "durationSec": 610,
            "reviewerRole": "operator",
            "unresolvedCriticalIssues": 0,
            "unresolvedMajorIssues": 0,
            "defectDensityPerMinute": 0.2,
            "retentionDipMitigationsReviewed": True,
            "chapterIssueLog": [{"chapterId": f"chapter-{index:02d}", "issues": []} for index in range(1, 7)],
        },
    }


def _proof_packets() -> dict:
    return {
        "storyboardPacket": {"beats": [{"beatId": "beat-01"}]},
        "sourceAcquisitionPacket": {
            "assets": [{"assetId": "asset-01", "provenance": {"proofMode": "browser-control"}}]
        },
        "promptQualityPacket": {"prompts": [{"sceneId": "scene-01", "prompt": "source-bound prompt"}]},
        "assetImportReview": {"acceptedSources": [{"sourceId": "asset-01"}], "reviewVerdict": "pass"},
        "editAssembly": {"cuts": [{"cutId": "cut-01"}], "renderManifest": {"projectId": "proof-render"}},
        "renderPreflight": {"manifest": {"projectId": "proof-render"}, "safeZone": {"status": "pass"}},
        "qualityReview": {"qaReport": {"status": "pass"}, "phoneReview": {"status": "pass"}},
        "releasePacket": _release_packet(),
        "publishPacket": {"publishReadiness": {"status": "pass"}, "uploadPacket": {"status": "ready"}},
        "postPublishLearning": {"analyticsPacket": {"views": 1}, "learningNotes": ["first learning loop"]},
    }


def test_orchestrator_lists_all_video_production_gates_and_blocks_next_missing_evidence():
    report = evaluate_production_gates(_material(topic_pass=True), packets={})

    assert report["schema"] == "video-studio.production-gate-orchestrator.v1"
    assert [stage["stage"] for stage in report["stages"]] == [
        "material-intake",
        "source-ledger",
        "topic-discovery",
        "storyboard",
        "source-acquisition",
        "prompt-quality",
        "asset-import-review",
        "edit-assembly",
        "render-preflight",
        "quality-review",
        "publish-readiness",
        "post-publish-learning",
    ]
    assert report["currentStage"] == "storyboard"
    assert report["blockedStage"] == "source-acquisition"
    assert report["stages"][0]["status"] == "pass"
    assert report["stages"][1]["status"] == "pass"
    assert report["stages"][2]["status"] == "pass"
    assert report["stages"][3]["status"] == "pending"
    assert report["stages"][4]["status"] == "blocked"


def test_orchestrator_blocks_topic_gate_until_source_ledger_is_complete():
    report = evaluate_production_gates(_material(topic_pass=True, source_complete=False), packets={})

    assert report["currentStage"] == "source-ledger"
    assert report["blockedStage"] == "source-ledger"
    source_stage = report["stages"][1]
    assert source_stage["status"] == "blocked"
    assert "minimumSourceLedgerEntries" in source_stage["failedChecks"]
    assert "missingSurface:community" in source_stage["failedChecks"]
    assert report["stages"][2]["failedChecks"] == ["sourceLedger"]


def test_orchestrator_rejects_empty_evidence_packets():
    packets = {
        "storyboardPacket": {"beats": []},
        "sourceAcquisitionPacket": {"assets": []},
        "promptQualityPacket": {"prompts": []},
        "assetImportReview": {"accepted": []},
        "editAssembly": {"cuts": []},
        "renderPreflight": {"manifest": {}},
        "qualityReview": {"qa": {}},
        "publishReadiness": {"release": {}},
        "postPublishLearning": {"metrics": {}},
    }

    report = evaluate_production_gates(_material(topic_pass=True), packets=packets)

    assert report["overallStatus"] == "blocked"
    assert report["currentStage"] == "storyboard"
    assert report["blockedStage"] == "source-acquisition"
    assert report["stages"][3]["status"] == "pending"
    assert report["stages"][3]["failedChecks"][0].startswith("insufficientEvidence:")


def test_orchestrator_passes_when_every_stage_has_proof_packet():
    report = evaluate_production_gates(_material(topic_pass=True), packets=_proof_packets())

    assert report["overallStatus"] == "pass"
    assert all(stage["status"] == "pass" for stage in report["stages"])
    assert report["currentStage"] == "post-publish-learning"


def test_process_gate_audit_maps_every_stage_to_dashboard_code_tests_and_evidence():
    audit = build_process_gate_audit()

    assert audit["schema"] == "video-studio.production-process-gate-audit.v1"
    assert audit["stageCount"] == 12
    assert audit["coveredStageCount"] == 12
    assert audit["gapStageCount"] == 0
    assert audit["coverageVerdict"] == "pass"
    assert audit["proofVerdict"] == "review"
    assert audit["verdict"] == "review"
    assert audit["structuredProofStageCount"] >= 5
    for row in audit["rows"]:
        assert row["dashboardSurfaces"]
        assert row["gateAnchors"]
        assert row["testAnchors"]
        assert row["evidenceRequired"]
        assert row["proofGrade"]
