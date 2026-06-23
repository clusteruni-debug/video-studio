from __future__ import annotations

from copy import deepcopy

from worker.render.longform_dryrun_readiness import (
    LONGFORM_DRYRUN_READINESS_GATE_KEYS,
    evaluate_longform_dryrun_readiness,
)
from worker.render.longform_workflow_gate import LONGFORM_WORKFLOW_STAGE_KEYS


def _topic_discovery_packet() -> dict:
    return {
        "evaluationDate": "2026-06-21",
        "targetLocale": "ko-KR",
        "targetFormat": "longform_10m",
        "researchQueryPlan": [
            {
                "provider": "google-search",
                "surface": "search",
                "query": "AI 공부 인증 진짜 효과",
                "intent": "Find general Korean web questions and competing explanations.",
                "capturedAt": "2026-06-21",
            },
            {
                "provider": "google-trends-kr",
                "surface": "trend",
                "query": "AI 공부",
                "intent": "Check current search attention in South Korea.",
                "capturedAt": "2026-06-21",
            },
            {
                "provider": "youtube-search",
                "surface": "video",
                "query": "AI 공부 인증",
                "intent": "Check video-format competition and viewer promise patterns.",
                "capturedAt": "2026-06-21",
            },
            {
                "provider": "korean-community-scan",
                "surface": "community",
                "query": "AI 공부 인증 후기",
                "intent": "Check Korean community questions and objections.",
                "capturedAt": "2026-06-21",
            },
            {
                "provider": "naver-datalab",
                "surface": "trend",
                "query": "AI 공부, 공부 인증",
                "intent": "Cross-check Korean search demand with Naver.",
                "capturedAt": "2026-06-21",
            },
        ],
        "sourceLedger": [
            {
                "sourceId": source_id,
                "sourceType": source_type,
                "title": f"{source_id} current topic source",
                "url": {
                    "google-search": "https://www.google.com/search?q=AI+%EA%B3%B5%EB%B6%80+%EC%9D%B8%EC%A6%9D",
                    "google-trends-kr": "https://trends.google.com/trending?geo=KR",
                    "naver-datalab": "https://datalab.naver.com/",
                    "youtube-search": "https://www.youtube.com/results?search_query=AI+%EA%B3%B5%EB%B6%80+%EC%9D%B8%EC%A6%9D",
                    "youtube-inspiration": "https://studio.youtube.com/",
                    "dcinside-hot": "https://www.dcinside.com/",
                    "theqoo-hot": "https://theqoo.net/",
                    "fmkorea-best": "https://www.fmkorea.com/",
                }[source_id],
                "capturedAt": "2026-06-21",
                "observation": f"{source_id} supports a timely topic decision.",
                "topicRefs": ["ai-study-proof"],
            }
            for source_id, source_type in (
                ("google-search", "google-search"),
                ("google-trends-kr", "google-trends-kr"),
                ("naver-datalab", "naver-datalab"),
                ("youtube-search", "youtube-search"),
                ("youtube-inspiration", "youtube-inspiration"),
                ("dcinside-hot", "korean-community"),
                ("theqoo-hot", "korean-community"),
                ("fmkorea-best", "community-forum"),
            )
        ],
        "topicCandidates": [
            _topic_candidate("ai-study-proof", strong=True),
            _topic_candidate("summer-power-bill", strong=False),
            _topic_candidate("commute-heat-map", strong=False),
        ],
        "selection": {
            "selectedTopicId": "ai-study-proof",
            "rejections": [
                {"topicId": "summer-power-bill", "reason": "Too shallow for a 10-minute evidence chain."},
                {"topicId": "commute-heat-map", "reason": "Trend evidence is not cross-checked enough."},
            ],
        },
    }


def _topic_candidate(topic_id: str, *, strong: bool) -> dict:
    evidence_refs = [f"source-{index:02d}" for index in range(1, 7 if strong else 3)]
    return {
        "topicId": topic_id,
        "workingTitle": f"{topic_id} working title",
        "centralQuestion": "What practical question should the viewer be able to answer?",
        "knowledgeGap": "Community attention lacks a verified decision path.",
        "whyNow": "Recent Korean community and trend surfaces show renewed attention.",
        "viewerPromise": "Turn noisy attention into a clear evidence-based answer.",
        "communitySignals": [
            {
                "sourceId": "dcinside-hot",
                "signalType": "repeat-question",
                "observation": "Multiple posts ask for practical verification.",
                "capturedAt": "2026-06-21",
            },
            {
                "sourceId": "theqoo-hot" if strong else "dcinside-hot",
                "signalType": "debate-thread",
                "observation": "Comments split around the same evidence gap.",
                "capturedAt": "2026-06-21",
            },
        ],
        "trendEvidence": [
            {
                "sourceId": "google-trends-kr",
                "trendDirection": "rising",
                "metricLabel": "Trending Now related query cluster",
                "observation": "Related query movement supports why-now timing.",
            },
            {
                "sourceId": "naver-datalab" if strong else "google-trends-kr",
                "trendDirection": "stable-high",
                "metricLabel": "Search trend comparison",
                "observation": "Search interest holds across the recent period.",
            },
        ],
        "sourcePlan": {
            "primarySourceCount": len(evidence_refs),
            "evidenceRefs": evidence_refs,
        },
        "longformPlan": {
            "chapterCount": 6 if strong else 3,
            "segmentCount": 18 if strong else 9,
            "retentionHooks": ["open-question", "midpoint-counterexample", "payoff-preview"] if strong else ["single-hook"],
            "first30SecPromise": "Open with the strongest question, stakes, and visible payoff.",
            "titleThumbnailExpectation": "The opening answers the exact title/thumbnail curiosity.",
            "topMomentPreview": "Preview the strongest evidence before the first chapter break.",
            "dipRiskMitigations": [
                {"risk": "search evidence feels abstract", "mitigation": "cut to a concrete comparison beat"},
                {"risk": "community discussion gets repetitive", "mitigation": "introduce a counterexample chapter"},
            ],
            "chapterPromises": [
                {"chapterId": f"chapter-{index:02d}", "promise": f"Chapter {index} resolves one viewer question."}
                for index in range(1, (6 if strong else 3) + 1)
            ],
        },
        "riskReview": {
            "unverifiedRumor": False,
            "defamationRisk": False,
            "privacyRisk": False,
            "protectedClassAttack": False,
            "medicalLegalFinancialHighStakes": False,
            "minorSafetyRisk": False,
            "factCheckPlan": "Verify every claim against durable sources before scripting.",
        },
        "originalityReview": {
            "notSinglePostCopy": True,
            "transformativeAngle": True,
            "sourceAttributionPlan": "Attribute every cited source in the reference ledger.",
        },
    }


def _workflow_seeded_failure_suite():
    return [
        {
            "caseId": "order-swap",
            "failureMode": "workflow stages are swapped",
            "expectedGateKey": "longformWorkflowOrderGate",
            "fixtureRef": "tests/fixtures/longform-workflow/order-swap.json",
            "testName": "test_longform_workflow_gate_blocks_out_of_order_source_generation",
            "status": "pass",
        },
        {
            "caseId": "missing-stage-evidence",
            "failureMode": "passed stage has no evidenceRefs",
            "expectedGateKey": "longformWorkflowEvidenceGate",
            "fixtureRef": "tests/fixtures/longform-workflow/missing-evidence.json",
            "testName": "test_longform_workflow_gate_requires_evidence_for_passed_stages",
            "status": "pass",
        },
        {
            "caseId": "skipped-source-generation",
            "failureMode": "later stage advances before source-generation passes",
            "expectedGateKey": "longformWorkflowDependencyGate",
            "fixtureRef": "tests/fixtures/longform-workflow/skipped-source-generation.json",
            "testName": "test_longform_workflow_gate_blocks_dependency_skips",
            "status": "pass",
        },
        {
            "caseId": "blocked-without-mutation",
            "failureMode": "blocked stage has no improvement action",
            "expectedGateKey": "longformWorkflowImprovementLoopGate",
            "fixtureRef": "tests/fixtures/longform-workflow/blocked-without-mutation.json",
            "testName": "test_longform_workflow_gate_requires_improvement_actions_for_failed_stage",
            "status": "pass",
        },
        {
            "caseId": "missing-seeded-suite",
            "failureMode": "workflow gate has no seeded failure suite",
            "expectedGateKey": "longformWorkflowSeededFailureGate",
            "fixtureRef": "tests/fixtures/longform-workflow/missing-seeded-suite.json",
            "testName": "test_longform_workflow_gate_requires_seeded_failure_suite",
            "status": "pass",
        },
        {
            "caseId": "derivative-before-final",
            "failureMode": "derivative clips advance before final readiness passes",
            "expectedGateKey": "longformWorkflowDependencyGate",
            "fixtureRef": "tests/fixtures/longform-workflow/derivative-before-final.json",
            "testName": "test_longform_workflow_gate_blocks_derivative_clips_before_final_readiness",
            "status": "pass",
        },
    ]


def _workflow_packet(status_by_stage: dict[str, str]) -> dict:
    return {
        "formatProfile": "longform_10m",
        "workflowStages": [
            {
                "stageKey": stage_key,
                "status": status_by_stage.get(stage_key, "pending"),
                "decisionRule": f"{stage_key} must pass before the next stage advances.",
                "reviewerRole": "producer-reviewer",
                "evidenceRefs": [f"storage/longform-workflow/{stage_key}/evidence.json"],
            }
            for stage_key in LONGFORM_WORKFLOW_STAGE_KEYS
        ],
        "workflowImprovementLoop": {
            "mutationLedgerPath": "storage/longform-workflow/mutation-ledger.json",
            "reviewCadence": "after every blocked, failed, or rough-cut review stage",
        },
        "seededFailureSuite": _workflow_seeded_failure_suite(),
    }


def _workflow_packet_for_publish() -> dict:
    return _workflow_packet({stage_key: "pass" for stage_key in LONGFORM_WORKFLOW_STAGE_KEYS})


def _workflow_packet_for_rough_cut() -> dict:
    statuses = {
        stage_key: "pass"
        for stage_key in (
            "reference-ledger",
            "packaging-premise",
            "storyboard",
            "script-tts",
            "source-prompt-bible",
            "source-generation",
            "source-review-import",
            "rough-cut",
            "render-preflight",
        )
    }
    statuses["full-watch-review"] = "pending"
    statuses["final-readiness"] = "pending"
    statuses["derivative-clips"] = "pending"
    return _workflow_packet(statuses)


def _chapter(index: int) -> dict:
    chapter_id = f"chapter-{index:02d}"
    return {
        "chapterId": chapter_id,
        "title": f"Chapter {index}",
        "claim": f"Claim {index}",
        "bridgeFromPrevious": "connects the previous chapter" if index > 1 else "",
        "segments": [
            {"segmentId": f"{chapter_id}-seg-01", "purpose": "setup"},
            {"segmentId": f"{chapter_id}-seg-02", "purpose": "evidence"},
            {"segmentId": f"{chapter_id}-seg-03", "purpose": "implication"},
        ],
        "evidence": [
            {
                "evidenceId": f"evidence-{index:02d}",
                "sourceUrl": f"https://example.com/evidence-{index}",
                "rightsStatus": "operator-approved",
                "citation": f"Example source {index}",
            }
        ],
    }


def _storyboard(chapters: list[dict]) -> dict:
    beats = []
    for chapter_index, chapter in enumerate(chapters, start=1):
        for segment_index, segment in enumerate(chapter["segments"], start=1):
            beats.append(
                {
                    "beatId": f"{segment['segmentId']}-beat",
                    "chapterId": chapter["chapterId"],
                    "startSec": ((chapter_index - 1) * 90) + ((segment_index - 1) * 30),
                    "durationSec": 24,
                    "visualIntent": f"Show {segment['purpose']}",
                    "narrationIntent": f"Narrate {segment['purpose']}",
                    "providerRole": "primaryMotion" if segment_index != 2 else "referenceStill",
                    "evidenceRef": chapter["evidence"][0]["evidenceId"],
                }
            )
    return {
        "thesis": "A longform question answered through chaptered evidence.",
        "viewerPromise": "The viewer understands the decision path by the end.",
        "chapterMarkers": [
            {"chapterId": chapter["chapterId"], "startSec": (index - 1) * 90, "title": chapter["title"]}
            for index, chapter in enumerate(chapters, start=1)
        ],
        "retentionPlan": {
            "first30SecPromise": "Open with the central question and visible payoff.",
            "titleThumbnailExpectation": "The opening matches the title and thumbnail promise.",
            "topMomentPreview": "Preview the strongest evidence before chapter one ends.",
            "dipRiskMitigations": [{"risk": "static proof", "mitigation": "cut to visual evidence"}],
        },
        "beats": beats,
        "visualContinuityBible": {
            "shotLanguage": "calm documentary push-ins and evidence inserts",
            "colorTreatment": "neutral daylight grade with consistent contrast",
            "layoutRules": "chapter lower thirds stay outside primary evidence",
            "styleRules": ["use one caption grid", "avoid center-caption overload"],
            "recurringAssets": ["chapter marker", "evidence insert"],
        },
        "webReferenceLedger": {
            "references": [
                {
                    "title": "Platform chapter reference",
                    "url": "https://example.com/platform-chapters",
                    "sourceType": "official-platform",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Chapter markers need ordered timing."],
                    "appliedGateKeys": ["chapterMarkerGate", "retentionPlanGate"],
                },
                {
                    "title": "Long-video segmentation research",
                    "url": "https://example.com/research-segmentation",
                    "sourceType": "research-paper",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Long videos need temporal segmentation."],
                    "appliedGateKeys": ["storyboardBeatCoverageGate", "evidenceVisualBindingGate"],
                },
                {
                    "title": "Continuity research",
                    "url": "https://example.com/research-continuity",
                    "sourceType": "research-paper",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Continuity needs explicit visual rules."],
                    "appliedGateKeys": ["visualContinuityBibleGate"],
                },
                {
                    "title": "Storyboard reference",
                    "url": "https://example.com/storyboard-reference",
                    "sourceType": "creator-case",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["The premise must be clear before production."],
                    "appliedGateKeys": ["longformStoryboardGate"],
                },
            ]
        },
    }


def _power_user_plan(storyboard: dict) -> dict:
    beat_ids = [beat["beatId"] for beat in storyboard["beats"]]
    return {
        "packagingPlan": {
            "premise": "A clear longform promise that can be understood before watching.",
            "targetViewer": "Curious viewers who want evidence before a decision.",
            "firstTenSecondExpectation": "The opening states the question, stakes, and visual payoff.",
            "payoffPromise": "The ending resolves the original question.",
            "titleOptions": ["Decision rule", "Evidence chain", "What actually matters"],
            "thumbnailBriefs": [
                {"visualHook": "clear subject plus question", "contrastPoint": "choice A versus B"},
                {"visualHook": "split outcome", "subject": "primary decision object"},
            ],
        },
        "feasibilityPlan": {
            "risks": [
                {"risk": "source continuity breaks", "mitigation": "use continuity bible", "owner": "producer"},
                {"risk": "evidence becomes static", "mitigation": "bind motion beats", "owner": "editor"},
                {"risk": "AI visual source fails", "mitigation": "fallback to still/reference", "owner": "source lead"},
            ],
            "killCriteria": ["no clear opening premise", "no source path for evidence"],
            "resourcePlan": {
                "owner": "producer",
                "sourceBudget": "zero-paid browser/manual generation only",
                "fallbackPath": "reference still plus editorial B-roll",
            },
        },
        "roughCutRetentionMap": [
            {
                "label": label,
                "startSec": start_sec,
                "viewerQuestion": f"Question at {label}",
                "payoff": f"Payoff at {label}",
                "sourceBeatId": beat_ids[index],
            }
            for index, (label, start_sec) in enumerate(
                [
                    ("open-loop", 0),
                    ("first-proof", 90),
                    ("risk-turn", 180),
                    ("counterexample", 270),
                    ("decision", 360),
                    ("final-payoff", 510),
                ]
            )
        ],
        "feedbackLoop": {
            "iterationPolicy": "Revise until script, rough cut, and final pass concrete decisions.",
            "reviewPasses": [
                {"stage": "script", "reviewerRole": "producer", "decisionRule": "promise is clear"},
                {"stage": "roughCut", "reviewerRole": "editor", "decisionRule": "minute map has no dead section"},
                {"stage": "final", "reviewerRole": "operator", "decisionRule": "full watch has no unresolved dip"},
            ],
        },
        "derivativeClipPlan": {
            "cadence": "three clips after longform approval",
            "qualityControl": "clips preserve context and never invert the claim",
            "clips": [
                {
                    "clipId": "clip-01",
                    "sourceBeatId": beat_ids[0],
                    "platform": "shorts",
                    "hook": "core question",
                    "viewerPromise": "full piece has the evidence chain",
                    "contextPreserved": True,
                },
                {
                    "clipId": "clip-02",
                    "sourceBeatId": beat_ids[6],
                    "platform": "reels",
                    "hook": "risk turn",
                    "viewerPromise": "full answer includes the exception",
                    "contextPreserved": True,
                },
                {
                    "clipId": "clip-03",
                    "sourceBeatId": beat_ids[15],
                    "platform": "tiktok",
                    "hook": "final rule",
                    "viewerPromise": "longform explains why",
                    "noMisleadingContext": True,
                },
            ],
        },
        "powerUserCaseLedger": {
            "references": [
                {
                    "title": "Creator production case",
                    "url": "https://example.com/creator-case",
                    "sourceType": "creator-case",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Packaging starts before edit."],
                    "appliedGateKeys": ["packagingPremiseGate", "productionFeasibilityGate"],
                },
                {
                    "title": "Creator interview",
                    "url": "https://example.com/creator-interview",
                    "sourceType": "creator-interview",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Rough cuts need viewer retention logic."],
                    "appliedGateKeys": ["roughCutRetentionMapGate"],
                },
                {
                    "title": "Clip economy case",
                    "url": "https://example.com/clip-economy",
                    "sourceType": "industry-case",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Derivative clips need context control."],
                    "appliedGateKeys": ["derivativeClipPlanGate"],
                },
                {
                    "title": "Production workflow research",
                    "url": "https://example.com/research-workflow",
                    "sourceType": "research-paper",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Feedback loops improve cohesion."],
                    "appliedGateKeys": ["creatorFeedbackLoopGate"],
                },
                {
                    "title": "Longform creator case",
                    "url": "https://example.com/longform-case",
                    "sourceType": "industry-analysis",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Long videos need depth and retention planning."],
                    "appliedGateKeys": ["packagingPremiseGate", "roughCutRetentionMapGate"],
                },
            ]
        },
    }


def _production_mode_packet(*, final: bool = True) -> dict:
    chapters = [_chapter(index) for index in range(1, 7)]
    storyboard = _storyboard(chapters)
    packet = {
        "formatProfile": "longform_10m",
        "templateType": "longform_deep_dive",
        "durationSec": 610,
        "providerRoleMatrix": {
            "primaryMotion": "grok-web-video",
            "referenceStill": "gemini-web-image",
            "fallbackMotion": {"provider": "gemini-web-video", "when": "only if Grok fails"},
        },
        "storyboard": storyboard,
        "powerUserProductionPlan": _power_user_plan(storyboard),
        "chapters": chapters,
        "chapterContinuityPlan": {
            "bridges": [
                {"from": f"chapter-{index:02d}", "to": f"chapter-{index + 1:02d}"}
                for index in range(1, 6)
            ]
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
    if final:
        packet.update(
            {
                "publishReadyClaim": True,
                "fullWatchReview": {
                    "completed": True,
                    "durationSec": 610,
                    "reviewer": "operator",
                    "humanReviewNote": "Full timeline watched without unresolved critical defects.",
                },
            }
        )
    return packet


def _minimum_release_packet() -> dict:
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
            "aiUseDecision": "yes",
            "realisticGenAiOrAltered": True,
            "youtubeAiUseSelected": True,
            "disclosureStatement": "Contains realistic AI-assisted visuals created from operator-reviewed source prompts.",
            "contentCredentialsStatus": "not-applicable",
            "viewerMisleadRiskReviewed": True,
            "inaccurateAuthenticityClaim": False,
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


def _final_library_audit(*, release_ready: bool = True) -> dict:
    return {
        "longformMinimumRelease": {
            "required": True,
            "ready": release_ready,
            "status": "pass" if release_ready else "fail",
        },
        "summary": {
            "longformMinimumReleaseRequired": True,
            "longformMinimumReleaseReady": release_ready,
            "longformMinimumReleaseStatus": "pass" if release_ready else "fail",
            "uploadReady": True,
            "channelReady": True,
            "topTierReady": True,
            "publishPacketContentReady": True,
        },
    }


def _publish_packet() -> dict:
    production_packet = _production_mode_packet(final=True)
    release_packet = _minimum_release_packet()
    return {
        "targetStage": "publish",
        "topicDiscoveryPacket": _topic_discovery_packet(),
        "workflowPacket": _workflow_packet_for_publish(),
        "productionModePacket": production_packet,
        "longformMinimumReleasePacket": release_packet,
        "renderManifest": {
            "projectId": "longform-dryrun-fixture",
            "formatProfile": "longform_10m",
            "durationSec": 610,
            "publishReadyClaim": True,
            "productionModePacket": production_packet,
            "longformMinimumReleasePacket": release_packet,
        },
        "finalLibraryAudit": _final_library_audit(release_ready=True),
    }


def test_longform_dryrun_readiness_constants_define_managed_inventory():
    assert LONGFORM_DRYRUN_READINESS_GATE_KEYS == (
        "dryrunTopicDiscoveryGate",
        "dryrunWorkflowGate",
        "dryrunProductionModeGate",
        "dryrunRenderPreflightGate",
        "dryrunMinimumReleaseGate",
        "dryrunFinalLibraryGate",
    )


def test_longform_dryrun_readiness_passes_full_publish_packet(tmp_path):
    report = evaluate_longform_dryrun_readiness(_publish_packet(), project_root=tmp_path)

    assert report["schema"] == "video-studio.longform-dryrun-readiness.v1"
    assert report["status"] == "pass"
    assert report["dryrunAllowed"] is True
    assert report["generationAllowed"] is True
    assert report["renderAllowed"] is True
    assert report["finalAllowed"] is True
    assert report["failedChecks"] == []
    assert {key: report["checks"][key]["status"] for key in LONGFORM_DRYRUN_READINESS_GATE_KEYS} == {
        "dryrunTopicDiscoveryGate": "pass",
        "dryrunWorkflowGate": "pass",
        "dryrunProductionModeGate": "pass",
        "dryrunRenderPreflightGate": "pass",
        "dryrunMinimumReleaseGate": "pass",
        "dryrunFinalLibraryGate": "pass",
    }


def test_longform_dryrun_readiness_requires_topic_discovery_packet(tmp_path):
    packet = _publish_packet()
    packet.pop("topicDiscoveryPacket")

    report = evaluate_longform_dryrun_readiness(packet, project_root=tmp_path)

    assert report["dryrunAllowed"] is False
    assert report["generationAllowed"] is False
    assert "dryrunTopicDiscoveryGate" in report["failedChecks"]


def test_longform_dryrun_readiness_rejects_failed_topic_discovery_packet(tmp_path):
    packet = _publish_packet()
    packet["topicDiscoveryPacket"]["topicCandidates"][0]["communitySignals"] = []

    report = evaluate_longform_dryrun_readiness(packet, project_root=tmp_path)

    assert report["dryrunAllowed"] is False
    assert report["renderAllowed"] is False
    assert "dryrunTopicDiscoveryGate" in report["failedChecks"]
    assert "communitySignalDiversityGate" in report["topicDiscoveryGate"]["failedChecks"]


def test_longform_dryrun_readiness_requires_workflow_packet(tmp_path):
    packet = _publish_packet()
    packet.pop("workflowPacket")

    report = evaluate_longform_dryrun_readiness(packet, project_root=tmp_path)

    assert report["dryrunAllowed"] is False
    assert report["generationAllowed"] is False
    assert "dryrunWorkflowGate" in report["failedChecks"]


def test_longform_dryrun_readiness_rejects_failed_production_mode_packet(tmp_path):
    packet = _publish_packet()
    packet["productionModePacket"]["voicePlan"]["targetWpm"] = 240

    report = evaluate_longform_dryrun_readiness(packet, project_root=tmp_path)

    assert report["dryrunAllowed"] is False
    assert report["renderAllowed"] is False
    assert "dryrunProductionModeGate" in report["failedChecks"]
    assert "longformVoiceConsistencyGate" in report["productionModeGate"]["failedChecks"]


def test_longform_dryrun_readiness_requires_manifest_bound_production_packet(tmp_path):
    packet = _publish_packet()
    packet["renderManifest"].pop("productionModePacket")

    report = evaluate_longform_dryrun_readiness(packet, project_root=tmp_path)

    assert report["dryrunAllowed"] is False
    assert "dryrunRenderPreflightGate" in report["failedChecks"]
    assert "longformProductionModeGate" in report["renderPreflightGate"]["failedChecks"]


def test_longform_dryrun_readiness_rejects_final_target_without_minimum_release_packet(tmp_path):
    packet = _publish_packet()
    packet.pop("longformMinimumReleasePacket")
    packet["renderManifest"].pop("longformMinimumReleasePacket")

    report = evaluate_longform_dryrun_readiness(packet, project_root=tmp_path)

    assert report["dryrunAllowed"] is False
    assert "dryrunRenderPreflightGate" in report["failedChecks"]
    assert "dryrunMinimumReleaseGate" in report["failedChecks"]


def test_longform_dryrun_readiness_rejects_upload_flags_without_release_ready_audit(tmp_path):
    packet = _publish_packet()
    packet["finalLibraryAudit"] = _final_library_audit(release_ready=False)

    report = evaluate_longform_dryrun_readiness(packet, project_root=tmp_path)

    assert report["dryrunAllowed"] is False
    assert report["finalAllowed"] is False
    assert "dryrunFinalLibraryGate" in report["failedChecks"]
    assert "Self-asserted publish flags" in report["checks"]["dryrunFinalLibraryGate"]["detail"]


def test_longform_dryrun_readiness_allows_rough_cut_without_release_or_final_library(tmp_path):
    production_packet = _production_mode_packet(final=False)
    packet = {
        "targetStage": "rough-cut",
        "topicDiscoveryPacket": _topic_discovery_packet(),
        "workflowPacket": _workflow_packet_for_rough_cut(),
        "productionModePacket": production_packet,
        "renderManifest": {
            "projectId": "longform-rough-cut-fixture",
            "formatProfile": "longform_10m",
            "durationSec": 610,
            "productionModePacket": production_packet,
        },
    }

    report = evaluate_longform_dryrun_readiness(deepcopy(packet), project_root=tmp_path)

    assert report["dryrunAllowed"] is True
    assert report["generationAllowed"] is True
    assert report["renderAllowed"] is True
    assert report["finalAllowed"] is False
    assert report["checks"]["dryrunMinimumReleaseGate"]["status"] == "skip"
    assert report["checks"]["dryrunFinalLibraryGate"]["status"] == "skip"
