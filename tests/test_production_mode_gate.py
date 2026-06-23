from __future__ import annotations

from worker.render.production_mode_gate import (
    FORMAT_PROFILE_GATE_KEYS,
    FORMAT_PROFILES,
    LONGFORM_POWER_USER_GATE_KEYS,
    LONGFORM_PRODUCTION_GATE_KEYS,
    LONGFORM_STORYBOARD_GATE_KEYS,
    PROVIDER_ROLE_MATRIX_GATE_KEYS,
    evaluate_production_mode_gate,
    evaluate_provider_role_matrix,
)


def _chapter(index: int) -> dict:
    return {
        "chapterId": f"chapter-{index:02d}",
        "title": f"Chapter {index}",
        "claim": f"Claim {index}",
        "bridgeFromPrevious": "connects the previous chapter" if index > 1 else "",
        "segments": [
            {"segmentId": f"chapter-{index:02d}-seg-01", "purpose": "chapter setup"},
            {"segmentId": f"chapter-{index:02d}-seg-02", "purpose": "evidence beat"},
            {"segmentId": f"chapter-{index:02d}-seg-03", "purpose": "implication beat"},
        ],
        "evidence": [
            {
                "evidenceId": f"evidence-{index:02d}-01",
                "sourceUrl": f"https://example.com/source-{index}",
                "rightsStatus": "operator-approved",
                "citation": f"Example source {index}",
            }
        ],
    }


def _storyboard(chapters: list[dict]) -> dict:
    beats = []
    for chapter_index, chapter in enumerate(chapters, start=1):
        for segment_index, segment in enumerate(chapter["segments"], start=1):
            start_sec = ((chapter_index - 1) * 90) + ((segment_index - 1) * 30)
            beats.append(
                {
                    "beatId": f"{segment['segmentId']}-beat",
                    "chapterId": chapter["chapterId"],
                    "startSec": start_sec,
                    "durationSec": 24,
                    "visualIntent": f"Visualize {segment['purpose']}",
                    "narrationIntent": f"Narrate {segment['purpose']}",
                    "providerRole": "primaryMotion" if segment_index != 2 else "referenceStill",
                    "evidenceRef": chapter["evidence"][0]["evidenceId"],
                }
            )

    return {
        "thesis": "A longform question answered through chaptered evidence.",
        "viewerPromise": "The viewer will understand the decision path by the end.",
        "chapterMarkers": [
            {"chapterId": chapter["chapterId"], "startSec": (index - 1) * 90, "title": chapter["title"]}
            for index, chapter in enumerate(chapters, start=1)
        ],
        "retentionPlan": {
            "first30SecPromise": "Open with the central question and the visible payoff.",
            "titleThumbnailExpectation": "The first 30 seconds match the title and thumbnail promise.",
            "topMomentPreview": "Preview the strongest evidence beat before the first chapter turn.",
            "dipRiskMitigations": [
                {"risk": "dry evidence section", "mitigation": "cut to visual proof before explanation"}
            ],
        },
        "beats": beats,
        "visualContinuityBible": {
            "shotLanguage": "calm documentary push-ins and evidence inserts",
            "colorTreatment": "neutral daylight grade with consistent contrast",
            "layoutRules": "chapter lower thirds stay outside primary visual evidence",
            "styleRules": ["use one caption grid", "avoid Shorts-style center text"],
            "recurringAssets": ["chapter marker lower-third", "evidence insert frame"],
        },
        "webReferenceLedger": {
            "references": [
                {
                    "title": "YouTube Help: Video Chapters",
                    "url": "https://support.google.com/youtube/answer/9884579?hl=en",
                    "sourceType": "official-platform",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Chapter markers start at 00:00, ascend, and use at least 10s sections."],
                    "appliedGateKeys": ["chapterMarkerGate", "longformStoryboardGate"],
                },
                {
                    "title": "YouTube Help: Audience Retention",
                    "url": "https://support.google.com/youtube/answer/9314415?hl=en",
                    "sourceType": "official-platform",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["First 30 seconds, top moments, dips, and spikes shape retention review."],
                    "appliedGateKeys": ["retentionPlanGate", "storyboardBeatCoverageGate"],
                },
                {
                    "title": "VidChapters-7M",
                    "url": "https://arxiv.org/abs/2309.13952",
                    "sourceType": "research-paper",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Long videos need temporal segmentation and chapter title grounding."],
                    "appliedGateKeys": ["chapterMarkerGate", "evidenceVisualBindingGate"],
                },
                {
                    "title": "Long-Video Storytelling Generation Survey",
                    "url": "https://arxiv.org/abs/2507.07202",
                    "sourceType": "research-paper",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Long generated videos struggle with scene consistency and motion coherence."],
                    "appliedGateKeys": ["visualContinuityBibleGate"],
                },
            ]
        },
    }


def _power_user_production_plan(storyboard: dict) -> dict:
    beat_ids = [beat["beatId"] for beat in storyboard["beats"]]
    return {
        "packagingPlan": {
            "premise": "A clear longform promise that can be understood before watching.",
            "targetViewer": "Curious Korean viewers who want evidence before a decision.",
            "firstTenSecondExpectation": "The opening states the question, stakes, and visual payoff immediately.",
            "payoffPromise": "The ending resolves the original question with a practical answer.",
            "titleOptions": [
                "The hidden rule behind this everyday decision",
                "I tested the question people keep getting wrong",
                "What actually matters before you decide",
            ],
            "thumbnailBriefs": [
                {"visualHook": "single clear object plus question mark", "contrastPoint": "safe vs unsafe choice"},
                {"visualHook": "split visual outcome", "subject": "primary decision object"},
            ],
        },
        "feasibilityPlan": {
            "risks": [
                {"risk": "source continuity breaks across generated clips", "mitigation": "use continuity bible", "owner": "producer"},
                {"risk": "evidence section becomes static", "mitigation": "bind each evidence beat to motion", "owner": "editor"},
                {"risk": "AI visual source fails", "mitigation": "fallback to diagram/reference still", "owner": "source lead"},
            ],
            "killCriteria": [
                "no clear first ten second premise",
                "no source path for a chapter-level evidence beat",
            ],
            "resourcePlan": {
                "owner": "producer",
                "sourceBudget": "zero-paid browser/manual generation only",
                "fallbackPath": "Gemini reference still plus editorial B-roll if Grok motion fails",
            },
        },
        "roughCutRetentionMap": [
            {
                "label": "open-loop",
                "startSec": 0,
                "viewerQuestion": "What decision are we resolving?",
                "payoff": "show the final answer will arrive later",
                "sourceBeatId": beat_ids[0],
            },
            {
                "label": "first-proof",
                "startSec": 90,
                "viewerQuestion": "What is the first real proof?",
                "payoff": "visual evidence replaces setup",
                "sourceBeatId": beat_ids[3],
            },
            {
                "label": "risk-turn",
                "startSec": 180,
                "viewerQuestion": "What goes wrong if we guess?",
                "payoff": "show the consequence beat",
                "sourceBeatId": beat_ids[6],
            },
            {
                "label": "counterexample",
                "startSec": 270,
                "viewerQuestion": "What exception changes the rule?",
                "payoff": "introduce the counterexample",
                "sourceBeatId": beat_ids[9],
            },
            {
                "label": "decision",
                "startSec": 360,
                "viewerQuestion": "What should the viewer do now?",
                "payoff": "assemble the decision rule",
                "sourceBeatId": beat_ids[12],
            },
            {
                "label": "final-payoff",
                "startSec": 510,
                "viewerQuestion": "Was the original promise answered?",
                "payoff": "close the loop with the answer",
                "sourceBeatId": beat_ids[15],
            },
        ],
        "feedbackLoop": {
            "iterationPolicy": "Revise the packet until script, rough cut, and final passes all have concrete decisions.",
            "reviewPasses": [
                {"stage": "script", "reviewerRole": "producer", "decisionRule": "central promise and chapter logic are clear"},
                {"stage": "roughCut", "reviewerRole": "editor", "decisionRule": "minute map has no dead section"},
                {"stage": "final", "reviewerRole": "operator", "decisionRule": "full watch review has no unresolved dip"},
            ],
        },
        "derivativeClipPlan": {
            "cadence": "three clips after longform approval",
            "qualityControl": "clips must preserve the longform context and never invert the claim",
            "clips": [
                {
                    "clipId": "clip-01",
                    "sourceBeatId": beat_ids[0],
                    "platform": "shorts",
                    "hook": "the core question in one sentence",
                    "viewerPromise": "watch the full piece for the evidence chain",
                    "contextPreserved": True,
                },
                {
                    "clipId": "clip-02",
                    "sourceBeatId": beat_ids[6],
                    "platform": "reels",
                    "hook": "the surprising risk turn",
                    "viewerPromise": "the full answer has the exception",
                    "contextPreserved": True,
                },
                {
                    "clipId": "clip-03",
                    "sourceBeatId": beat_ids[15],
                    "platform": "tiktok",
                    "hook": "the final rule",
                    "viewerPromise": "the longform explains why",
                    "noMisleadingContext": True,
                },
            ],
        },
        "powerUserCaseLedger": {
            "references": [
                {
                    "title": "Business Insider: MrBeast production process",
                    "url": "https://www.businessinsider.com/mrbeast-how-production-team-makes-youtube-videos-2025-8",
                    "sourceType": "creator-case",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Power-user workflow starts with title/thumbnail, feasibility, rough cuts, retention analytics, and derivatives."],
                    "appliedGateKeys": [
                        "packagingPremiseGate",
                        "productionFeasibilityGate",
                        "roughCutRetentionMapGate",
                        "derivativeClipPlanGate",
                    ],
                },
                {
                    "title": "WIRED: Marques Brownlee creator tips",
                    "url": "https://www.wired.com/story/marques-brownlee-interview-mkbhd-video-creator-tips/",
                    "sourceType": "creator-interview",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Visual quality, audience trust, and authentic subject fit matter more than raw gear escalation."],
                    "appliedGateKeys": ["packagingPremiseGate"],
                },
                {
                    "title": "The Atlantic: clip economy",
                    "url": "https://www.theatlantic.com/podcasts/2026/04/how-short-form-clips-took-over-the-internet/686922/",
                    "sourceType": "industry-case",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Longform work needs a controlled derivative clip cadence, not accidental cutdowns."],
                    "appliedGateKeys": ["derivativeClipPlanGate"],
                },
                {
                    "title": "PodReels",
                    "url": "https://arxiv.org/abs/2311.05867",
                    "sourceType": "research-paper",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Creator interviews show teaser selection and cohesive editing require explicit workflow support."],
                    "appliedGateKeys": ["creatorFeedbackLoopGate", "derivativeClipPlanGate"],
                },
                {
                    "title": "Making AI-Enhanced Videos",
                    "url": "https://arxiv.org/abs/2503.03134",
                    "sourceType": "research-paper",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Creators use GenAI across planning, scripting, prompts, visual/audio generation, editing, titles, and subtitles."],
                    "appliedGateKeys": ["creatorFeedbackLoopGate", "productionFeasibilityGate"],
                },
                {
                    "title": "WIRED: multi-hour video essays",
                    "url": "https://www.wired.com/story/youtube-5-hour-icarly-analysis-videos/",
                    "sourceType": "creator-case",
                    "retrievedAt": "2026-06-21",
                    "takeaways": ["Long videos can work when depth, steady retention, and return viewing are planned instead of assumed."],
                    "appliedGateKeys": ["roughCutRetentionMapGate"],
                },
            ]
        },
    }


def _valid_longform_packet() -> dict:
    chapters = [_chapter(index) for index in range(1, 7)]
    storyboard = _storyboard(chapters)
    return {
        "formatProfile": "longform_10m",
        "templateType": "longform_deep_dive",
        "durationSec": 610,
        "providerRoleMatrix": {
            "primaryMotion": "grok-web-video",
            "referenceStill": "gemini-web-image",
            "fallbackMotion": {
                "provider": "gemini-web-video",
                "when": "only if Grok fails chapter action continuity",
            },
        },
        "storyboard": storyboard,
        "powerUserProductionPlan": _power_user_production_plan(storyboard),
        "chapters": chapters,
        "chapterContinuityPlan": {
            "bridges": [
                {"from": "chapter-01", "to": "chapter-02"},
                {"from": "chapter-02", "to": "chapter-03"},
                {"from": "chapter-03", "to": "chapter-04"},
                {"from": "chapter-04", "to": "chapter-05"},
                {"from": "chapter-05", "to": "chapter-06"},
            ]
        },
        "voicePlan": {
            "provider": "edge-tts",
            "voiceId": "ko-KR-SunHiNeural",
            "targetWpm": 140,
        },
        "editPlan": {
            "captionMode": "chapter-lower-third",
            "maxStaticHoldSec": 10,
            "averageCutSec": 9,
        },
        "audioPlan": {
            "duckingEnabled": True,
            "chapterBeds": [
                {"chapterId": chapter["chapterId"], "bedId": f"bed-{index:02d}"}
                for index, chapter in enumerate(chapters, start=1)
            ],
        },
    }


def test_production_mode_gate_constants_define_longform_contract_inventory():
    assert FORMAT_PROFILE_GATE_KEYS == ("formatProfileGate",)
    assert PROVIDER_ROLE_MATRIX_GATE_KEYS == (
        "providerRoleMatrixGate",
        "grokPrimaryMotionGate",
        "geminiReferenceGate",
        "geminiFallbackMotionGate",
    )
    assert LONGFORM_PRODUCTION_GATE_KEYS == (
        "longformOutlineGate",
        "chapterContinuityGate",
        "evidenceDensityGate",
        "sourceRightsCitationGate",
        "longformVoiceConsistencyGate",
        "longformEditRhythmGate",
        "chapterAudioBedGate",
        "fullWatchReviewGate",
    )
    assert LONGFORM_STORYBOARD_GATE_KEYS == (
        "longformStoryboardGate",
        "chapterMarkerGate",
        "retentionPlanGate",
        "storyboardBeatCoverageGate",
        "evidenceVisualBindingGate",
        "visualContinuityBibleGate",
        "webReferenceLedgerGate",
    )
    assert LONGFORM_POWER_USER_GATE_KEYS == (
        "packagingPremiseGate",
        "productionFeasibilityGate",
        "roughCutRetentionMapGate",
        "creatorFeedbackLoopGate",
        "derivativeClipPlanGate",
        "powerUserCaseLedgerGate",
    )
    assert FORMAT_PROFILES["longform_10m"]["primaryUnit"] == "chapter"
    assert FORMAT_PROFILES["shortform_vertical"]["primaryUnit"] == "scene"


def test_longform_10m_packet_passes_chapter_provider_audio_contract():
    report = evaluate_production_mode_gate(_valid_longform_packet())

    assert report["status"] == "pass"
    assert report["renderAllowed"] is True
    assert report["checks"]["formatProfileGate"]["status"] == "pass"
    assert report["checks"]["providerRoleMatrixGate"]["status"] == "pass"
    assert report["checks"]["longformOutlineGate"]["status"] == "pass"
    assert report["checks"]["longformStoryboardGate"]["status"] == "pass"
    assert report["checks"]["webReferenceLedgerGate"]["status"] == "pass"
    assert report["checks"]["packagingPremiseGate"]["status"] == "pass"
    assert report["checks"]["powerUserCaseLedgerGate"]["status"] == "pass"
    assert report["checks"]["chapterAudioBedGate"]["status"] == "pass"


def test_longform_source_rights_rejects_ambiguous_creative_commons_without_commercial_flag():
    packet = _valid_longform_packet()
    packet["chapters"][0]["evidence"][0]["rightsStatus"] = "creative-commons"

    report = evaluate_production_mode_gate(packet)

    assert report["status"] == "fail"
    assert "sourceRightsCitationGate" in report["failedChecks"]
    assert "requires explicit commercialUseAllowed=true" in report["checks"]["sourceRightsCitationGate"]["detail"]


def test_longform_source_rights_allows_specific_release_compatible_cc_status():
    packet = _valid_longform_packet()
    packet["chapters"][0]["evidence"][0]["rightsStatus"] = "cc-by"

    report = evaluate_production_mode_gate(packet)

    assert report["status"] == "pass"
    assert report["checks"]["sourceRightsCitationGate"]["status"] == "pass"


def test_longform_source_rights_rejects_noncommercial_cc_even_with_commercial_flag():
    packet = _valid_longform_packet()
    packet["chapters"][0]["evidence"][0].update(
        {
            "rightsStatus": "cc-by-nc",
            "commercialUseAllowed": True,
        }
    )

    report = evaluate_production_mode_gate(packet)

    assert report["status"] == "fail"
    assert "sourceRightsCitationGate" in report["failedChecks"]
    assert "blocked for release" in report["checks"]["sourceRightsCitationGate"]["detail"]
    assert report["checks"]["fullWatchReviewGate"]["status"] == "skip"


def test_longform_final_publish_claim_aliases_require_full_watch_review():
    claim_variants = [
        {"claimFinalReady": True},
        {"finalReadinessClaim": True},
        {"releaseReadinessClaim": True},
        {"claimsFinalReady": True},
        {"publishReadyClaim": True},
        {"candidateEvaluationStatus": "approved"},
        {"publishReadiness": {"status": "ready"}},
        {"channelReadiness": {"status": "channel-ready"}},
        {"topTierReadiness": {"status": "top-tier-ready"}},
    ]
    for variant in claim_variants:
        packet = _valid_longform_packet()
        packet.update(variant)

        report = evaluate_production_mode_gate(packet)

        assert report["status"] == "fail", variant
        assert "fullWatchReviewGate" in report["failedChecks"], variant
        assert report["checks"]["fullWatchReviewGate"]["status"] == "fail", variant


def test_longform_10m_blocks_thin_outline_and_missing_evidence():
    packet = _valid_longform_packet()
    packet["chapters"] = packet["chapters"][:3]
    packet["chapters"][0]["evidence"] = []

    report = evaluate_production_mode_gate(packet)

    assert report["status"] == "fail"
    assert "longformOutlineGate" in report["failedChecks"]
    assert "evidenceDensityGate" in report["failedChecks"]
    assert report["renderAllowed"] is False


def test_provider_role_matrix_blocks_grok_reference_and_gemini_image_motion():
    report = evaluate_provider_role_matrix(
        {
            "primaryMotion": "gemini-web-image",
            "referenceStill": "grok-web-video",
            "fallbackMotion": {"provider": "gemini-web-video"},
        }
    )

    assert report["status"] == "fail"
    assert "grokPrimaryMotionGate" in report["failedChecks"]
    assert "geminiReferenceGate" in report["failedChecks"]
    assert "geminiFallbackMotionGate" in report["failedChecks"]


def test_longform_final_readiness_requires_full_watch_review():
    packet = _valid_longform_packet()
    packet["claimFinalReady"] = True

    report = evaluate_production_mode_gate(packet)

    assert report["status"] == "fail"
    assert "fullWatchReviewGate" in report["failedChecks"]

    packet["fullWatchReview"] = {
        "completed": True,
        "durationSec": 610,
        "reviewer": "operator",
        "humanReviewNote": "Watched full longform render for pacing, BGM, captions, and source continuity.",
    }
    passed = evaluate_production_mode_gate(packet)
    assert passed["status"] == "pass"
    assert passed["checks"]["fullWatchReviewGate"]["status"] == "pass"


def test_longform_10m_blocks_shortform_caption_pacing_and_missing_audio_beds():
    packet = _valid_longform_packet()
    packet["editPlan"]["captionMode"] = "shorts-karaoke"
    packet["audioPlan"]["chapterBeds"] = []

    report = evaluate_production_mode_gate(packet)

    assert report["status"] == "fail"
    assert "longformEditRhythmGate" in report["failedChecks"]
    assert "chapterAudioBedGate" in report["failedChecks"]


def test_longform_storyboard_gate_requires_chapter_markers_and_retention_plan():
    packet = _valid_longform_packet()
    packet["storyboard"]["chapterMarkers"] = [{"chapterId": "chapter-01", "startSec": 0, "title": "Only"}]
    packet["storyboard"]["retentionPlan"] = {}

    report = evaluate_production_mode_gate(packet)

    assert report["status"] == "fail"
    assert "chapterMarkerGate" in report["failedChecks"]
    assert "retentionPlanGate" in report["failedChecks"]


def test_longform_storyboard_gate_blocks_unbound_evidence_and_missing_visual_bible():
    packet = _valid_longform_packet()
    for beat in packet["storyboard"]["beats"]:
        beat.pop("evidenceRef", None)
    packet["storyboard"]["visualContinuityBible"] = {}

    report = evaluate_production_mode_gate(packet)

    assert report["status"] == "fail"
    assert "evidenceVisualBindingGate" in report["failedChecks"]
    assert "visualContinuityBibleGate" in report["failedChecks"]


def test_web_reference_ledger_gate_requires_official_and_research_refs():
    packet = _valid_longform_packet()
    packet["storyboard"]["webReferenceLedger"]["references"] = [
        {
            "title": "Industry commentary",
            "url": "https://example.com/commentary",
            "sourceType": "industry-analysis",
            "retrievedAt": "2026-06-21",
            "takeaways": ["Useful but not enough for a hard gate."],
            "appliedGateKeys": ["chapterMarkerGate"],
        }
    ]

    report = evaluate_production_mode_gate(packet)

    assert report["status"] == "fail"
    assert "webReferenceLedgerGate" in report["failedChecks"]


def test_power_user_gates_require_packaging_and_feasibility():
    packet = _valid_longform_packet()
    packet["powerUserProductionPlan"]["packagingPlan"]["titleOptions"] = ["single"]
    packet["powerUserProductionPlan"]["feasibilityPlan"]["risks"] = [
        {"risk": "unowned risk", "mitigation": "too vague"}
    ]

    report = evaluate_production_mode_gate(packet)

    assert report["status"] == "fail"
    assert "packagingPremiseGate" in report["failedChecks"]
    assert "productionFeasibilityGate" in report["failedChecks"]


def test_power_user_gates_require_retention_feedback_and_clip_plan():
    packet = _valid_longform_packet()
    packet["powerUserProductionPlan"]["roughCutRetentionMap"] = []
    packet["powerUserProductionPlan"]["feedbackLoop"]["reviewPasses"] = [
        {"stage": "script", "reviewerRole": "producer", "decisionRule": "clear"}
    ]
    packet["powerUserProductionPlan"]["derivativeClipPlan"]["clips"] = []

    report = evaluate_production_mode_gate(packet)

    assert report["status"] == "fail"
    assert "roughCutRetentionMapGate" in report["failedChecks"]
    assert "creatorFeedbackLoopGate" in report["failedChecks"]
    assert "derivativeClipPlanGate" in report["failedChecks"]


def test_power_user_case_ledger_requires_creator_cases_and_research_basis():
    packet = _valid_longform_packet()
    packet["powerUserProductionPlan"]["powerUserCaseLedger"]["references"] = [
        {
            "title": "Generic blog",
            "url": "https://example.com/blog",
            "sourceType": "secondary",
            "retrievedAt": "2026-06-21",
            "takeaways": ["Not enough to enforce creator workflow gates."],
            "appliedGateKeys": ["packagingPremiseGate"],
        }
    ]

    report = evaluate_production_mode_gate(packet)

    assert report["status"] == "fail"
    assert "powerUserCaseLedgerGate" in report["failedChecks"]
