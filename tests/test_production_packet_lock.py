from __future__ import annotations

import json

from worker.render.compose import compose_smoke_render
from worker.render.production_packet_lock import evaluate_active_production_packet_lock


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_active_pointer(root, *, packet_path="storage/approval-packets/packet.json", status="active"):
    _write_json(
        root / "storage/approval-packets/ACTIVE.json",
        {
            "schema": "video-studio.active-production-packet.v1",
            "status": status,
            "packetId": "kr-curiosity-bottled-water-20260616",
            "packetPath": packet_path,
            "appliesTo": {
                "approvalPacketIds": ["kr-curiosity-bottled-water-20260616"],
                "projectIdPrefixes": ["kr-curiosity", "kr_curiosity"],
                "projectIds": [],
                "referenceStylePresets": ["kr_curiosity_explainer"],
                "targetAudiences": ["kr_casual_curiosity_20_40"],
                "matchReferenceAudiencePair": False,
            },
        },
    )


def _write_packet(root, *, approved=False):
    _write_json(
        root / "storage/approval-packets/packet.json",
        {
            "schema": "video-studio.production-approval-packet.v1",
            "packetId": "kr-curiosity-bottled-water-20260616",
            "approvedForRender": approved,
        },
    )


def _longform_packet() -> dict:
    chapters = []
    beats = []
    for chapter_index in range(1, 7):
        chapter_id = f"chapter-{chapter_index:02d}"
        evidence_id = f"evidence-{chapter_index:02d}"
        segments = []
        for segment_index in range(1, 4):
            segment_id = f"{chapter_id}-segment-{segment_index:02d}"
            segments.append({"segmentId": segment_id, "purpose": "planned longform beat"})
            beats.append(
                {
                    "beatId": f"{segment_id}-beat",
                    "chapterId": chapter_id,
                    "startSec": ((chapter_index - 1) * 90) + ((segment_index - 1) * 30),
                    "durationSec": 24,
                    "visualIntent": "evidence-led documentary visual",
                    "narrationIntent": "plain longform narration",
                    "providerRole": "primaryMotion" if segment_index != 2 else "referenceStill",
                    "evidenceRef": evidence_id,
                }
            )
        chapters.append(
            {
                "chapterId": chapter_id,
                "title": f"Chapter {chapter_index}",
                "claim": f"Claim {chapter_index}",
                "bridgeFromPrevious": "connects previous chapter" if chapter_index > 1 else "",
                "segments": segments,
                "evidence": [
                    {
                        "evidenceId": evidence_id,
                        "sourceUrl": f"https://example.com/evidence-{chapter_index}",
                        "rightsStatus": "operator-approved",
                        "citation": f"Evidence {chapter_index}",
                    }
                ],
            }
        )

    beat_ids = [beat["beatId"] for beat in beats]
    return {
        "formatProfile": "longform_10m",
        "templateType": "longform_deep_dive",
        "durationSec": 610,
        "providerRoleMatrix": {
            "primaryMotion": "grok-web-video",
            "referenceStill": "gemini-web-image",
            "fallbackMotion": {"provider": "gemini-web-video", "when": "Grok motion continuity fails"},
        },
        "chapters": chapters,
        "chapterContinuityPlan": {
            "bridges": [
                {"from": f"chapter-{index:02d}", "to": f"chapter-{index + 1:02d}"}
                for index in range(1, 6)
            ]
        },
        "storyboard": {
            "thesis": "A longform question answered through evidence.",
            "viewerPromise": "The viewer gets a complete answer.",
            "chapterMarkers": [
                {"chapterId": chapter["chapterId"], "startSec": (index - 1) * 90, "title": chapter["title"]}
                for index, chapter in enumerate(chapters, start=1)
            ],
            "retentionPlan": {
                "first30SecPromise": "Open with the question and payoff.",
                "titleThumbnailExpectation": "The opening matches the package.",
                "topMomentPreview": "Preview the strongest proof.",
                "dipRiskMitigations": [{"risk": "slow chapter", "mitigation": "cut to proof"}],
            },
            "beats": beats,
            "visualContinuityBible": {
                "shotLanguage": "documentary push-ins",
                "colorTreatment": "neutral grade",
                "layoutRules": "chapter lower thirds only",
                "styleRules": ["one caption grid"],
                "recurringAssets": ["chapter lower third"],
            },
            "webReferenceLedger": {
                "references": [
                    {
                        "title": "YouTube chapters",
                        "url": "https://support.google.com/youtube/answer/9884579",
                        "sourceType": "official-platform",
                        "retrievedAt": "2026-06-21",
                        "takeaways": ["Chapter markers need a structured timeline."],
                        "appliedGateKeys": ["longformStoryboardGate", "chapterMarkerGate"],
                    },
                    {
                        "title": "YouTube retention",
                        "url": "https://support.google.com/youtube/answer/9314415",
                        "sourceType": "official-platform",
                        "retrievedAt": "2026-06-21",
                        "takeaways": ["Retention plans need top moments and dips."],
                        "appliedGateKeys": ["retentionPlanGate", "storyboardBeatCoverageGate"],
                    },
                    {
                        "title": "VidChapters",
                        "url": "https://arxiv.org/abs/2309.13952",
                        "sourceType": "research-paper",
                        "retrievedAt": "2026-06-21",
                        "takeaways": ["Long videos need chapter grounding."],
                        "appliedGateKeys": ["evidenceVisualBindingGate"],
                    },
                    {
                        "title": "Long-video consistency",
                        "url": "https://arxiv.org/abs/2507.07202",
                        "sourceType": "research-paper",
                        "retrievedAt": "2026-06-21",
                        "takeaways": ["Long videos need continuity planning."],
                        "appliedGateKeys": ["visualContinuityBibleGate"],
                    },
                ]
            },
        },
        "powerUserProductionPlan": {
            "packagingPlan": {
                "premise": "A clear evidence-led longform promise.",
                "targetViewer": "Curious viewers",
                "firstTenSecondExpectation": "The opening states the question and payoff.",
                "payoffPromise": "The ending resolves the question.",
                "titleOptions": ["Title A", "Title B", "Title C"],
                "thumbnailBriefs": [
                    {"visualHook": "main subject", "contrastPoint": "before after"},
                    {"visualHook": "decision moment", "subject": "primary topic"},
                ],
            },
            "feasibilityPlan": {
                "risks": [
                    {"risk": "source continuity", "mitigation": "use visual bible", "owner": "producer"},
                    {"risk": "static evidence", "mitigation": "bind proof to beats", "owner": "editor"},
                    {"risk": "fallback source", "mitigation": "use reference stills", "owner": "source lead"},
                ],
                "killCriteria": ["no opening premise", "no chapter evidence"],
                "resourcePlan": {
                    "owner": "producer",
                    "sourceBudget": "zero-paid",
                    "fallbackPath": "reference still fallback",
                },
            },
            "roughCutRetentionMap": [
                {"startSec": 0, "viewerQuestion": "What is the question?", "payoff": "open the loop", "sourceBeatId": beat_ids[0]},
                {"startSec": 90, "viewerQuestion": "What is the first proof?", "payoff": "show proof", "sourceBeatId": beat_ids[3]},
                {"startSec": 180, "viewerQuestion": "What is the risk?", "payoff": "show risk", "sourceBeatId": beat_ids[6]},
                {"startSec": 270, "viewerQuestion": "What is the exception?", "payoff": "show exception", "sourceBeatId": beat_ids[9]},
                {"startSec": 360, "viewerQuestion": "What should change?", "payoff": "show rule", "sourceBeatId": beat_ids[12]},
                {"startSec": 510, "viewerQuestion": "Was it answered?", "payoff": "close loop", "sourceBeatId": beat_ids[15]},
            ],
            "feedbackLoop": {
                "iterationPolicy": "Revise until each pass has a decision.",
                "reviewPasses": [
                    {"stage": "script", "reviewerRole": "producer", "decisionRule": "promise is clear"},
                    {"stage": "roughCut", "reviewerRole": "editor", "decisionRule": "minute map works"},
                    {"stage": "final", "reviewerRole": "operator", "decisionRule": "full watch has no unresolved issue"},
                ],
            },
            "derivativeClipPlan": {
                "cadence": "three clips after approval",
                "qualityControl": "preserve context",
                "clips": [
                    {"clipId": "clip-01", "sourceBeatId": beat_ids[0], "platform": "shorts", "hook": "question", "viewerPromise": "full evidence", "contextPreserved": True},
                    {"clipId": "clip-02", "sourceBeatId": beat_ids[6], "platform": "reels", "hook": "risk", "viewerPromise": "full answer", "contextPreserved": True},
                    {"clipId": "clip-03", "sourceBeatId": beat_ids[15], "platform": "tiktok", "hook": "rule", "viewerPromise": "full reason", "noMisleadingContext": True},
                ],
            },
            "powerUserCaseLedger": {
                "references": [
                    {"title": "Creator case", "url": "https://example.com/case", "sourceType": "creator-case", "retrievedAt": "2026-06-21", "takeaways": ["Packaging and retention"], "appliedGateKeys": ["packagingPremiseGate", "roughCutRetentionMapGate"]},
                    {"title": "Creator interview", "url": "https://example.com/interview", "sourceType": "creator-interview", "retrievedAt": "2026-06-21", "takeaways": ["Feasibility"], "appliedGateKeys": ["productionFeasibilityGate"]},
                    {"title": "Industry case", "url": "https://example.com/industry", "sourceType": "industry-case", "retrievedAt": "2026-06-21", "takeaways": ["Derivative clips"], "appliedGateKeys": ["derivativeClipPlanGate"]},
                    {"title": "Research paper", "url": "https://arxiv.org/abs/2311.05867", "sourceType": "research-paper", "retrievedAt": "2026-06-21", "takeaways": ["Feedback loop"], "appliedGateKeys": ["creatorFeedbackLoopGate"]},
                    {"title": "Research paper two", "url": "https://arxiv.org/abs/2503.03134", "sourceType": "research-paper", "retrievedAt": "2026-06-21", "takeaways": ["Production workflow"], "appliedGateKeys": ["productionFeasibilityGate"]},
                ]
            },
        },
        "voicePlan": {"provider": "edge-tts", "voiceId": "ko-KR-SunHiNeural", "targetWpm": 140},
        "editPlan": {"captionMode": "chapter-lower-third", "maxStaticHoldSec": 10, "averageCutSec": 9},
        "audioPlan": {
            "duckingEnabled": True,
            "chapterBeds": [
                {"chapterId": chapter["chapterId"], "bedId": f"bed-{index:02d}"}
                for index, chapter in enumerate(chapters, start=1)
            ],
        },
    }


def _write_longform_packet(root):
    packet_path = root / "storage/inputs/longform/production-mode-packet.json"
    _write_json(packet_path, _longform_packet())
    return packet_path


def _longform_release_packet() -> dict:
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
            "chapterIssueLog": [
                {"chapterId": f"chapter-{index:02d}", "issues": []}
                for index in range(1, 7)
            ],
        },
    }


def _write_longform_release_packet(root):
    packet_path = root / "storage/inputs/longform/minimum-release-packet.json"
    _write_json(packet_path, _longform_release_packet())
    return packet_path


def test_active_packet_lock_skips_when_pointer_missing(tmp_path):
    report = evaluate_active_production_packet_lock({"projectId": "kr-curiosity-proof"}, project_root=tmp_path)

    assert report["status"] == "skipped"
    assert report["required"] is False
    assert report["renderAllowed"] is True


def test_active_packet_lock_skips_unrelated_manifest(tmp_path):
    _write_active_pointer(tmp_path)
    manifest = {
        "projectId": "manual-smoke-render",
        "referenceStylePreset": "kr_curiosity_explainer",
        "targetAudience": "kr_casual_curiosity_20_40",
    }

    report = evaluate_active_production_packet_lock(manifest, project_root=tmp_path)

    assert report["status"] == "skipped"
    assert report["required"] is False
    assert report["renderAllowed"] is True
    assert report["checks"]["scopeMatch"]["status"] == "skip"


def test_active_packet_lock_blocks_matching_manifest_without_packet_binding(tmp_path):
    _write_active_pointer(tmp_path)
    _write_packet(tmp_path, approved=False)
    manifest = {"projectId": "kr-curiosity-proof"}

    report = evaluate_active_production_packet_lock(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert report["required"] is True
    assert report["renderAllowed"] is False
    assert report["failedChecks"] == ["approvalPacketBinding"]


def test_active_packet_lock_blocks_matching_manifest_until_packet_is_approved(tmp_path):
    _write_active_pointer(tmp_path)
    _write_packet(tmp_path, approved=False)
    manifest = {
        "projectId": "kr-curiosity-proof",
        "approvalPacketId": "kr-curiosity-bottled-water-20260616",
    }

    report = evaluate_active_production_packet_lock(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert report["required"] is True
    assert report["renderAllowed"] is False
    assert report["failedChecks"] == ["packetApproval"]


def test_active_packet_lock_allows_bound_manifest_after_packet_approval(tmp_path):
    _write_active_pointer(tmp_path)
    _write_packet(tmp_path, approved=True)
    manifest = {
        "projectId": "kr-curiosity-proof",
        "approvalPacketId": "kr-curiosity-bottled-water-20260616",
    }

    report = evaluate_active_production_packet_lock(manifest, project_root=tmp_path)

    assert report["status"] == "pass"
    assert report["required"] is True
    assert report["renderAllowed"] is True
    assert report["failedChecks"] == []


def test_longform_manifest_blocks_render_without_production_mode_packet(tmp_path):
    manifest = {
        "projectId": "longform-proof",
        "formatProfile": "longform_10m",
        "durationSec": 610,
    }

    report = evaluate_active_production_packet_lock(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert report["required"] is True
    assert report["renderAllowed"] is False
    assert report["failedChecks"] == ["longformProductionModeGate"]
    assert report["checks"]["longformProductionModeGate"]["status"] == "fail"
    assert "explicit production mode packet path/object" in report["checks"]["longformProductionModeGate"]["detail"]
    assert "productionModeGate" not in report


def test_longform_manifest_inline_fields_do_not_replace_production_mode_packet(tmp_path):
    manifest = _longform_packet()
    manifest["projectId"] = "longform-proof"

    report = evaluate_active_production_packet_lock(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert report["renderAllowed"] is False
    assert report["failedChecks"] == ["longformProductionModeGate"]
    assert "explicit production mode packet path/object" in report["checks"]["longformProductionModeGate"]["detail"]
    assert "productionModeGate" not in report


def test_longform_manifest_allows_render_with_passing_production_mode_packet_path(tmp_path):
    packet_path = _write_longform_packet(tmp_path)
    manifest = {
        "projectId": "longform-proof",
        "formatProfile": "longform_10m",
        "durationSec": 610,
        "productionModePacketPath": packet_path.relative_to(tmp_path).as_posix(),
    }

    report = evaluate_active_production_packet_lock(manifest, project_root=tmp_path)

    assert report["status"] == "pass"
    assert report["required"] is True
    assert report["renderAllowed"] is True
    assert report["failedChecks"] == []
    assert report["checks"]["longformProductionModeGate"]["status"] == "pass"
    assert report["productionModeGate"]["status"] == "pass"
    assert report["checks"]["longformMinimumReleaseGate"]["status"] == "skip"


def test_longform_final_claim_blocks_without_minimum_release_packet(tmp_path):
    packet_path = _write_longform_packet(tmp_path)
    manifest = {
        "projectId": "longform-proof",
        "formatProfile": "longform_10m",
        "durationSec": 610,
        "finalReadinessClaim": True,
        "productionModePacketPath": packet_path.relative_to(tmp_path).as_posix(),
    }

    report = evaluate_active_production_packet_lock(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert report["renderAllowed"] is False
    assert report["failedChecks"] == ["longformMinimumReleaseGate"]
    assert "minimum release packet" in report["checks"]["longformMinimumReleaseGate"]["detail"]


def test_longform_final_claim_allows_with_passing_minimum_release_packet(tmp_path):
    production_packet_path = _write_longform_packet(tmp_path)
    release_packet_path = _write_longform_release_packet(tmp_path)
    manifest = {
        "projectId": "longform-proof",
        "formatProfile": "longform_10m",
        "durationSec": 610,
        "finalReadinessClaim": True,
        "productionModePacketPath": production_packet_path.relative_to(tmp_path).as_posix(),
        "longformMinimumReleasePacketPath": release_packet_path.relative_to(tmp_path).as_posix(),
    }

    report = evaluate_active_production_packet_lock(manifest, project_root=tmp_path)

    assert report["status"] == "pass"
    assert report["renderAllowed"] is True
    assert report["failedChecks"] == []
    assert report["checks"]["longformMinimumReleaseGate"]["status"] == "pass"
    assert report["longformMinimumReleaseGate"]["computedScore"] == 100


def test_longform_duration_infers_production_mode_gate_even_without_profile(tmp_path):
    manifest = {
        "projectId": "longform-proof",
        "durationSec": 610,
    }

    report = evaluate_active_production_packet_lock(manifest, project_root=tmp_path)

    assert report["status"] == "fail"
    assert report["renderAllowed"] is False
    assert report["failedChecks"] == ["longformProductionModeGate"]
    assert "explicit production mode packet path/object" in report["checks"]["longformProductionModeGate"]["detail"]
    assert "productionModeGate" not in report


def test_compose_blocks_matching_manifest_before_ffmpeg_when_active_packet_unbound(tmp_path):
    _write_active_pointer(tmp_path)
    _write_packet(tmp_path, approved=True)
    manifest_dir = tmp_path / "storage/inputs/kr-curiosity-active-lock"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "render-manifest.json"
    manifest = {
        "projectId": "kr-curiosity-active-lock",
        "renderDir": "storage/renders/kr-curiosity-active-lock",
        "subtitleFilePath": "storage/renders/kr-curiosity-active-lock/subtitles.ass",
        "concatFilePath": "storage/renders/kr-curiosity-active-lock/concat.txt",
        "outputPath": "storage/renders/kr-curiosity-active-lock/out.mp4",
        "scenes": [
            {
                "sceneId": "scene-001",
                "durationSec": 1.0,
                "subtitleText": "테스트",
            }
        ],
    }
    _write_json(manifest_path, manifest)

    result = compose_smoke_render(manifest_path=manifest_path, project_root=tmp_path)

    assert result.ok is False
    assert result.sceneClipPaths == []
    assert result.qualityReport is None
    assert result.activeProductionPacketLock is not None
    assert result.activeProductionPacketLock["failedChecks"] == ["approvalPacketBinding"]
    assert (tmp_path / "storage/renders/kr-curiosity-active-lock/active-production-packet-lock.json").exists()
    assert not (tmp_path / "storage/renders/kr-curiosity-active-lock/out.mp4").exists()


def test_compose_blocks_longform_manifest_before_ffmpeg_without_production_mode_packet(tmp_path):
    manifest_dir = tmp_path / "storage/inputs/longform-active-lock"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "render-manifest.json"
    manifest = {
        "projectId": "longform-active-lock",
        "formatProfile": "longform_10m",
        "durationSec": 610,
        "renderDir": "storage/renders/longform-active-lock",
        "subtitleFilePath": "storage/renders/longform-active-lock/subtitles.ass",
        "concatFilePath": "storage/renders/longform-active-lock/concat.txt",
        "outputPath": "storage/renders/longform-active-lock/out.mp4",
        "scenes": [
            {
                "sceneId": "scene-001",
                "durationSec": 1.0,
                "subtitleText": "테스트",
            }
        ],
    }
    _write_json(manifest_path, manifest)

    result = compose_smoke_render(manifest_path=manifest_path, project_root=tmp_path)

    assert result.ok is False
    assert result.sceneClipPaths == []
    assert result.qualityReport is None
    assert result.activeProductionPacketLock is not None
    assert result.activeProductionPacketLock["failedChecks"] == ["longformProductionModeGate"]
    assert (tmp_path / "storage/renders/longform-active-lock/active-production-packet-lock.json").exists()
    assert not (tmp_path / "storage/renders/longform-active-lock/out.mp4").exists()
