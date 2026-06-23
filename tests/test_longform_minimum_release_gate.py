from __future__ import annotations

from copy import deepcopy

from worker.render.longform_minimum_release_gate import (
    LONGFORM_MINIMUM_RELEASE_GATE_KEYS,
    build_longform_publish_packet_template,
    evaluate_longform_minimum_release_gate,
)


def _passing_packet() -> dict:
    chapters = []
    for index in range(1, 7):
        chapter_id = f"chapter-{index:02d}"
        chapters.append(
            {
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
                        "sourceUrl": f"https://example.com/evidence-{index}",
                        "rightsStatus": "operator-approved",
                    }
                ],
            }
        )

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
        "publishDisclosureReview": {
            "platform": "youtube",
            "aiUseDecision": "yes",
            "realisticGenAiOrAltered": True,
            "aiUseDisclosureRequired": True,
            "youtubeAiUseSelected": True,
            "disclosureStatement": "This longform candidate uses realistic AI-generated video and will be disclosed in YouTube Studio.",
            "contentCredentialsStatus": "not-present",
            "viewerMisleadRiskReviewed": True,
            "inaccurateAuthenticityClaim": False,
            "capturedWithCameraClaim": False,
            "inauthenticRiskReview": {
                "massProducedTemplate": False,
                "originalInsightAdded": True,
                "substantiveVariation": True,
                "metadataTruthful": True,
                "reusedContentTransformative": True,
            },
        },
        "scriptTtsCaptionReview": {
            "status": "pass",
            "voicePlan": {
                "provider": "edge-tts",
                "voiceId": "ko-KR-SunHiNeural",
                "targetWpm": 140,
            },
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
            "chapterIssueLog": [
                {"chapterId": f"chapter-{index:02d}", "issues": []}
                for index in range(1, 7)
            ],
        },
    }


def test_longform_minimum_release_gate_passes_objective_evidence_packet():
    report = evaluate_longform_minimum_release_gate(_passing_packet())

    assert report["status"] == "pass"
    assert report["releaseAllowed"] is True
    assert report["computedScore"] == 100
    assert report["minimumScore"] == 72
    assert report["failedChecks"] == []


def test_longform_minimum_release_gate_rejects_shortform_packet():
    packet = _passing_packet()
    packet["formatProfile"] = "shortform_vertical"
    packet["durationSec"] = 30

    report = evaluate_longform_minimum_release_gate(packet)

    assert report["status"] == "fail"
    assert report["releaseAllowed"] is False
    assert "longformReleaseFormatGate" in report["failedChecks"]


def test_longform_minimum_release_gate_rejects_research_only_seedance_source():
    packet = _passing_packet()
    packet["sourceReviewImport"]["acceptedSources"][0].update(
        {
            "provider": "dreamina-seedance-2-mini",
            "rightsStatus": "research-only",
            "commercialUseAllowed": False,
        }
    )

    report = evaluate_longform_minimum_release_gate(packet)

    assert report["status"] == "fail"
    assert "longformReleaseRightsGate" in report["failedChecks"]
    assert "research-only" in report["checks"]["longformReleaseRightsGate"]["detail"]


def test_longform_minimum_release_gate_rejects_ambiguous_creative_commons_without_commercial_flag():
    packet = _passing_packet()
    packet["sourceReviewImport"]["acceptedSources"][0].update(
        {
            "rightsStatus": "creative-commons",
            "commercialUseAllowed": False,
        }
    )

    report = evaluate_longform_minimum_release_gate(packet)

    assert report["status"] == "fail"
    assert "longformReleaseRightsGate" in report["failedChecks"]
    assert "requires explicit commercialUseAllowed=true" in report["checks"]["longformReleaseRightsGate"]["detail"]


def test_longform_minimum_release_gate_allows_specific_release_compatible_cc_status():
    packet = _passing_packet()
    packet["sourceReviewImport"]["acceptedSources"][0]["rightsStatus"] = "cc-by"

    report = evaluate_longform_minimum_release_gate(packet)

    assert report["status"] == "pass"
    assert report["checks"]["longformReleaseRightsGate"]["status"] == "pass"


def test_longform_minimum_release_gate_rejects_missing_ai_disclosure_decision():
    packet = _passing_packet()
    packet.pop("publishDisclosureReview")

    report = evaluate_longform_minimum_release_gate(packet)

    assert report["status"] == "fail"
    assert "longformReleaseDisclosureGate" in report["failedChecks"]
    assert "aiUseDecision" in report["checks"]["longformReleaseDisclosureGate"]["detail"]


def test_longform_minimum_release_gate_rejects_realistic_ai_without_youtube_selection():
    packet = _passing_packet()
    packet["publishDisclosureReview"]["youtubeAiUseSelected"] = False

    report = evaluate_longform_minimum_release_gate(packet)

    assert report["status"] == "fail"
    assert "longformReleaseDisclosureGate" in report["failedChecks"]
    assert "YouTube Studio AI use" in report["checks"]["longformReleaseDisclosureGate"]["detail"]


def test_longform_publish_packet_template_defaults_to_blocking_disclosure_fields():
    template = build_longform_publish_packet_template(
        {"materialId": "mat-001", "title": "소재", "centralQuestion": "왜?", "searchSeed": "seed"},
        {},
    )

    assert template["schema"] == "video-studio.longform-publish-packet-template.v1"
    assert template["materialId"] == "mat-001"
    assert template["publishDisclosureReview"]["realisticGenAiOrAltered"] is True
    assert template["publishDisclosureReview"]["youtubeAiUseSelected"] is False
    assert "publishDisclosureReview.aiUseDecision" in template["requiredBeforePublish"]


def test_longform_minimum_release_gate_rejects_noncommercial_cc_even_with_commercial_flag():
    packet = _passing_packet()
    packet["sourceReviewImport"]["acceptedSources"][0].update(
        {
            "rightsStatus": "cc-by-nc",
            "commercialUseAllowed": True,
        }
    )

    report = evaluate_longform_minimum_release_gate(packet)

    assert report["status"] == "fail"
    assert "longformReleaseRightsGate" in report["failedChecks"]
    assert "blocked for release" in report["checks"]["longformReleaseRightsGate"]["detail"]


def test_longform_minimum_release_gate_rejects_tts_caption_drift_and_duplicates():
    packet = _passing_packet()
    packet["scriptTtsCaptionReview"]["maxCaptionTtsDriftSec"] = 0.41
    packet["scriptTtsCaptionReview"]["noDuplicateCaptionTts"] = False

    report = evaluate_longform_minimum_release_gate(packet)

    assert report["status"] == "fail"
    assert "longformReleaseScriptTtsCaptionGate" in report["failedChecks"]
    assert "drift" in report["checks"]["longformReleaseScriptTtsCaptionGate"]["detail"]


def test_longform_minimum_release_gate_rejects_source_continuity_drift():
    packet = _passing_packet()
    packet["sourceReviewImport"]["chapterContinuityPassRatio"] = 0.7
    packet["sourceReviewImport"]["primarySubjectScaleJump"] = True

    report = evaluate_longform_minimum_release_gate(packet)

    assert report["status"] == "fail"
    assert "longformReleaseSourceContinuityGate" in report["failedChecks"]
    assert "continuity pass ratio" in report["checks"]["longformReleaseSourceContinuityGate"]["detail"]


def test_longform_minimum_release_gate_rejects_weak_editorial_direction():
    packet = _passing_packet()
    packet["editorialReleaseReview"]["motivatedCutPassRatio"] = 0.55
    packet["editorialReleaseReview"]["noUnboundEffectCues"] = False

    report = evaluate_longform_minimum_release_gate(packet)

    assert report["status"] == "fail"
    assert "longformReleaseEditorialGate" in report["failedChecks"]
    assert "motivated cut" in report["checks"]["longformReleaseEditorialGate"]["detail"]


def test_longform_minimum_release_gate_rejects_missing_audio_mix_evidence():
    packet = _passing_packet()
    packet["audioReleaseReview"]["audioStreamExists"] = False
    packet["audioReleaseReview"]["everyCueBoundToVisibleEvent"] = False

    report = evaluate_longform_minimum_release_gate(packet)

    assert report["status"] == "fail"
    assert "longformReleaseAudioGate" in report["failedChecks"]
    assert "audio stream" in report["checks"]["longformReleaseAudioGate"]["detail"]


def test_longform_minimum_release_gate_rejects_unresolved_full_watch_issues():
    packet = _passing_packet()
    packet["fullWatchReview"]["unresolvedMajorIssues"] = 1
    packet["fullWatchReview"]["chapterIssueLog"] = packet["fullWatchReview"]["chapterIssueLog"][:3]

    report = evaluate_longform_minimum_release_gate(packet)

    assert report["status"] == "fail"
    assert "longformReleaseFullWatchGate" in report["failedChecks"]
    assert "critical/major" in report["checks"]["longformReleaseFullWatchGate"]["detail"]


def test_longform_minimum_release_gate_rejects_self_asserted_score_inflation():
    packet = _passing_packet()
    packet["releaseScoreEvidence"] = {"computedScore": 74}

    report = evaluate_longform_minimum_release_gate(packet)

    assert report["status"] == "fail"
    assert "longformReleaseScoreGate" in report["failedChecks"]
    assert "does not match computed score" in report["checks"]["longformReleaseScoreGate"]["detail"]


def test_longform_minimum_release_gate_constants_define_managed_inventory():
    assert LONGFORM_MINIMUM_RELEASE_GATE_KEYS == (
        "longformReleaseFormatGate",
        "longformReleaseRightsGate",
        "longformReleaseDisclosureGate",
        "longformReleaseSourceContinuityGate",
        "longformReleaseScriptTtsCaptionGate",
        "longformReleaseEditorialGate",
        "longformReleaseAudioGate",
        "longformReleaseFullWatchGate",
        "longformReleaseScoreGate",
    )


def test_longform_minimum_release_gate_report_is_not_mutated_by_caller_after_eval():
    packet = _passing_packet()
    report = evaluate_longform_minimum_release_gate(packet)
    mutated = deepcopy(packet)
    mutated["sourceReviewImport"]["chapterContinuityPassRatio"] = 0.1

    assert report["computedScore"] == 100
