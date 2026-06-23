from __future__ import annotations

from copy import deepcopy

from worker.render.topic_discovery_gate import (
    TOPIC_DISCOVERY_GATE_KEYS,
    TOPIC_SELECTION_MINIMUM_SCORE,
    compute_topic_candidate_score,
    evaluate_topic_discovery_gate,
)


def _source(source_id: str, source_type: str) -> dict:
    urls = {
        "google-search": "https://www.google.com/search?q=AI+%EA%B3%B5%EB%B6%80+%EC%9D%B8%EC%A6%9D",
        "google-trends-kr": "https://trends.google.com/trending?geo=KR",
        "naver-datalab": "https://datalab.naver.com/",
        "youtube-search": "https://www.youtube.com/results?search_query=AI+%EA%B3%B5%EB%B6%80+%EC%9D%B8%EC%A6%9D",
        "youtube-inspiration": "https://studio.youtube.com/",
        "dcinside-hot": "https://www.dcinside.com/",
        "theqoo-hot": "https://theqoo.net/",
        "fmkorea-best": "https://www.fmkorea.com/",
    }
    return {
        "sourceId": source_id,
        "sourceType": source_type,
        "title": f"{source_id} topic observation",
        "url": urls.get(source_id, f"https://www.google.com/search?q={source_id}"),
        "capturedAt": "2026-06-21",
        "observation": f"{source_id} shows a concrete topic signal.",
        "topicRefs": ["ai-study-proof"],
    }


def _safe_reviews() -> tuple[dict, dict]:
    return (
        {
            "unverifiedRumor": False,
            "defamationRisk": False,
            "privacyRisk": False,
            "protectedClassAttack": False,
            "medicalLegalFinancialHighStakes": False,
            "minorSafetyRisk": False,
            "factCheckPlan": "Verify every claim against durable sources before scripting.",
        },
        {
            "notSinglePostCopy": True,
            "transformativeAngle": True,
            "sourceAttributionPlan": "Attribute every cited source in the reference ledger.",
        },
    )


def _candidate(topic_id: str, *, strong: bool) -> dict:
    risk_review, originality_review = _safe_reviews()
    if strong:
        evidence_refs = [f"source-{index:02d}" for index in range(1, 7)]
        chapter_count = 6
        segment_count = 18
        retention_hooks = ["open-question", "midpoint-counterexample", "payoff-preview", "decision-rule"]
        community_signals = [
            {
                "sourceId": "dcinside-hot",
                "signalType": "repeat-question",
                "observation": "Multiple posts ask for practical verification rather than a simple opinion.",
                "capturedAt": "2026-06-21",
            },
            {
                "sourceId": "theqoo-hot",
                "signalType": "debate-thread",
                "observation": "Comments split around the same evidence gap.",
                "capturedAt": "2026-06-21",
            },
            {
                "sourceId": "fmkorea-best",
                "signalType": "best-comment-cluster",
                "observation": "High-engagement comments ask for a before/after comparison.",
                "capturedAt": "2026-06-21",
            },
        ]
        trend_evidence = [
            {
                "sourceId": "google-trends-kr",
                "trendDirection": "rising",
                "metricLabel": "Trending Now related query cluster",
                "observation": "Related query movement supports why-now timing.",
            },
            {
                "sourceId": "naver-datalab",
                "trendDirection": "stable-high",
                "metricLabel": "Search trend comparison",
                "observation": "Search interest holds across the recent period.",
            },
            {
                "sourceId": "youtube-inspiration",
                "trendDirection": "topic-fit",
                "metricLabel": "Creator idea surface",
                "observation": "Video idea surface suggests adjacent audience questions.",
            },
        ]
    else:
        evidence_refs = ["source-01", "source-02"]
        chapter_count = 3
        segment_count = 9
        retention_hooks = ["single-hook"]
        community_signals = [
            {
                "sourceId": "dcinside-hot",
                "signalType": "single-thread",
                "observation": "One community thread mentioned it.",
                "capturedAt": "2026-06-21",
            }
        ]
        trend_evidence = [
            {
                "sourceId": "google-trends-kr",
                "trendDirection": "unclear",
                "metricLabel": "Trending Now",
                "observation": "A related phrase appeared once.",
            }
        ]

    return {
        "topicId": topic_id,
        "workingTitle": f"{topic_id} working title",
        "centralQuestion": "What practical question should the viewer be able to answer?",
        "knowledgeGap": "Community discussion has attention but lacks a verified decision path.",
        "whyNow": "Recent Korean community and trend surfaces show renewed attention.",
        "viewerPromise": "The video will turn noisy attention into a clear evidence-based answer.",
        "communitySignals": community_signals,
        "trendEvidence": trend_evidence,
        "sourcePlan": {
            "primarySourceCount": len(evidence_refs),
            "evidenceRefs": evidence_refs,
        },
        "longformPlan": {
            "chapterCount": chapter_count,
            "segmentCount": segment_count,
            "retentionHooks": retention_hooks,
            "first30SecPromise": "Open with the strongest question, stakes, and visible payoff.",
            "titleThumbnailExpectation": "The opening answers the exact title/thumbnail curiosity.",
            "topMomentPreview": "Preview the strongest evidence before the first chapter break.",
            "dipRiskMitigations": [
                {"risk": "search evidence feels abstract", "mitigation": "cut to a concrete comparison beat"},
                {"risk": "community discussion gets repetitive", "mitigation": "introduce a counterexample chapter"},
            ],
            "chapterPromises": [
                {"chapterId": f"chapter-{index:02d}", "promise": f"Chapter {index} resolves one viewer question."}
                for index in range(1, chapter_count + 1)
            ],
        },
        "riskReview": risk_review,
        "originalityReview": originality_review,
    }


def _passing_packet() -> dict:
    selected = _candidate("ai-study-proof", strong=True)
    alternatives = [
        _candidate("summer-power-bill", strong=False),
        _candidate("commute-heat-map", strong=False),
    ]
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
            _source("google-search", "google-search"),
            _source("google-trends-kr", "google-trends-kr"),
            _source("naver-datalab", "naver-datalab"),
            _source("youtube-search", "youtube-search"),
            _source("youtube-inspiration", "youtube-inspiration"),
            _source("dcinside-hot", "korean-community"),
            _source("theqoo-hot", "korean-community"),
            _source("fmkorea-best", "community-forum"),
        ],
        "topicCandidates": [selected, *alternatives],
        "selection": {
            "selectedTopicId": "ai-study-proof",
            "rejections": [
                {"topicId": "summer-power-bill", "reason": "Too shallow for a 10-minute evidence chain."},
                {"topicId": "commute-heat-map", "reason": "Trend evidence is not cross-checked enough."},
            ],
        },
    }


def test_topic_discovery_gate_constants_define_managed_inventory():
    assert TOPIC_DISCOVERY_GATE_KEYS == (
        "topicSourceLedgerGate",
        "researchQueryPlanGate",
        "sourceAuthenticityGate",
        "communitySignalDiversityGate",
        "trendCrossCheckGate",
        "curiosityAngleGate",
        "longformTopicFitGate",
        "audienceRetentionFitGate",
        "safetyOriginalityGate",
        "topicSelectionMatrixGate",
    )
    assert TOPIC_SELECTION_MINIMUM_SCORE == 75


def test_topic_discovery_gate_passes_selected_topic():
    report = evaluate_topic_discovery_gate(_passing_packet())

    assert report["schema"] == "video-studio.topic-discovery-gate.v1"
    assert report["status"] == "pass"
    assert report["topicReady"] is True
    assert report["selectedTopicId"] == "ai-study-proof"
    assert report["selectedScore"] >= TOPIC_SELECTION_MINIMUM_SCORE
    assert report["failedChecks"] == []
    assert {key: report["checks"][key]["status"] for key in TOPIC_DISCOVERY_GATE_KEYS} == {
        key: "pass" for key in TOPIC_DISCOVERY_GATE_KEYS
    }


def test_topic_discovery_gate_rejects_stale_or_missing_current_source_ledger():
    packet = _passing_packet()
    packet["sourceLedger"][0]["capturedAt"] = "2026-05-01"

    report = evaluate_topic_discovery_gate(packet)

    assert report["topicReady"] is False
    assert "topicSourceLedgerGate" in report["failedChecks"]
    assert "14-day window" in report["checks"]["topicSourceLedgerGate"]["detail"]


def test_topic_discovery_gate_rejects_missing_search_video_community_query_plan():
    packet = _passing_packet()
    packet["researchQueryPlan"] = [
        {
            "provider": "google-trends-kr",
            "surface": "trend",
            "query": "AI 공부",
            "intent": "Only trend check.",
            "capturedAt": "2026-06-21",
        }
    ]

    report = evaluate_topic_discovery_gate(packet)

    assert report["topicReady"] is False
    assert "researchQueryPlanGate" in report["failedChecks"]


def test_topic_discovery_gate_rejects_placeholder_urls_and_weak_source_surface_mix():
    packet = _passing_packet()
    packet["sourceLedger"] = [
        source for source in packet["sourceLedger"] if source["sourceType"] not in {"google-search", "youtube-search"}
    ]
    packet["sourceLedger"][0]["url"] = "https://example.com/fake"

    report = evaluate_topic_discovery_gate(packet)

    assert report["topicReady"] is False
    assert "sourceAuthenticityGate" in report["failedChecks"]
    assert "placeholder or invalid url" in report["checks"]["sourceAuthenticityGate"]["detail"]


def test_topic_discovery_gate_rejects_single_community_source():
    packet = _passing_packet()
    selected = packet["topicCandidates"][0]
    selected["communitySignals"] = [selected["communitySignals"][0]]

    report = evaluate_topic_discovery_gate(packet)

    assert report["topicReady"] is False
    assert "communitySignalDiversityGate" in report["failedChecks"]


def test_topic_discovery_gate_rejects_trend_without_official_cross_check():
    packet = _passing_packet()
    selected = packet["topicCandidates"][0]
    selected["trendEvidence"] = [
        {
            "sourceId": "dcinside-hot",
            "trendDirection": "loud",
            "metricLabel": "comment count",
            "observation": "Community comments increased.",
        },
        {
            "sourceId": "theqoo-hot",
            "trendDirection": "loud",
            "metricLabel": "reply count",
            "observation": "Another community thread repeated it.",
        },
    ]

    report = evaluate_topic_discovery_gate(packet)

    assert report["topicReady"] is False
    assert "trendCrossCheckGate" in report["failedChecks"]


def test_topic_discovery_gate_rejects_weak_curiosity_angle():
    packet = _passing_packet()
    packet["topicCandidates"][0].pop("knowledgeGap")

    report = evaluate_topic_discovery_gate(packet)

    assert report["topicReady"] is False
    assert "curiosityAngleGate" in report["failedChecks"]
    assert "knowledgeGap" in report["checks"]["curiosityAngleGate"]["detail"]


def test_topic_discovery_gate_rejects_longform_topic_without_depth():
    packet = _passing_packet()
    selected = packet["topicCandidates"][0]
    selected["sourcePlan"]["primarySourceCount"] = 2
    selected["sourcePlan"]["evidenceRefs"] = ["source-01", "source-02"]

    report = evaluate_topic_discovery_gate(packet)

    assert report["topicReady"] is False
    assert "longformTopicFitGate" in report["failedChecks"]


def test_topic_discovery_gate_rejects_longform_topic_without_retention_fit():
    packet = _passing_packet()
    selected = packet["topicCandidates"][0]
    selected["longformPlan"].pop("first30SecPromise")

    report = evaluate_topic_discovery_gate(packet)

    assert report["topicReady"] is False
    assert "audienceRetentionFitGate" in report["failedChecks"]
    assert "first30SecPromise" in report["checks"]["audienceRetentionFitGate"]["detail"]


def test_topic_discovery_gate_rejects_safety_and_originality_risk():
    packet = _passing_packet()
    selected = packet["topicCandidates"][0]
    selected["riskReview"]["privacyRisk"] = True
    selected["originalityReview"]["notSinglePostCopy"] = False

    report = evaluate_topic_discovery_gate(packet)

    assert report["topicReady"] is False
    assert "safetyOriginalityGate" in report["failedChecks"]


def test_topic_discovery_gate_rejects_selected_topic_that_is_not_highest_score():
    packet = _passing_packet()
    packet["selection"]["selectedTopicId"] = "summer-power-bill"
    packet["selection"]["rejections"] = [
        {"topicId": "ai-study-proof", "reason": "Wrongly rejected stronger topic."},
        {"topicId": "commute-heat-map", "reason": "Trend evidence is not cross-checked enough."},
    ]

    report = evaluate_topic_discovery_gate(packet)

    assert report["topicReady"] is False
    assert "topicSelectionMatrixGate" in report["failedChecks"]
    assert "selected topic score" in report["checks"]["topicSelectionMatrixGate"]["detail"]


def test_topic_discovery_gate_rejects_declared_score_inflation():
    packet = _passing_packet()
    selected = packet["topicCandidates"][0]
    selected["declaredScore"] = compute_topic_candidate_score(selected, {}) + 1

    report = evaluate_topic_discovery_gate(packet)

    assert report["topicReady"] is False
    assert "topicSelectionMatrixGate" in report["failedChecks"]
    assert "declaredScore" in report["checks"]["topicSelectionMatrixGate"]["detail"]


def test_topic_discovery_gate_rejects_missing_rejection_reasons():
    packet = _passing_packet()
    packet["selection"]["rejections"] = [packet["selection"]["rejections"][0]]

    report = evaluate_topic_discovery_gate(packet)

    assert report["topicReady"] is False
    assert "topicSelectionMatrixGate" in report["failedChecks"]
    assert "rejection reason" in report["checks"]["topicSelectionMatrixGate"]["detail"]


def test_topic_discovery_gate_allows_shortform_with_smaller_depth_requirement():
    packet = _passing_packet()
    packet["targetFormat"] = "shortform_vertical"
    selected = packet["topicCandidates"][0]
    selected["sourcePlan"]["primarySourceCount"] = 2
    selected["sourcePlan"]["evidenceRefs"] = ["source-01", "source-02"]
    selected["longformPlan"] = {"hook": "one strong hook", "retentionHooks": ["open-loop"]}

    report = evaluate_topic_discovery_gate(deepcopy(packet))

    assert report["topicReady"] is True
