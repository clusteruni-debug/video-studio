"""Topic discovery gate for Video Studio production planning.

This gate decides whether a proposed topic is ready to enter storyboard,
source-prompt-bible, source generation, or longform dry-run work. It is not a
scraper. Callers must provide a durable research packet with source ledger,
candidate topics, and a selection matrix.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlparse


TOPIC_DISCOVERY_GATE_KEYS = (
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

TOPIC_SELECTION_MINIMUM_SCORE = 75

CURRENT_SOURCE_TYPES = {
    "community-forum",
    "google-search",
    "google-trends-kr",
    "korean-community",
    "korean-social",
    "manual-browser-search",
    "naver-datalab",
    "platform-analytics",
    "youtube-inspiration",
    "youtube-search",
    "youtube-analytics-trends",
    "agy-google-search",
    "agy-youtube-search",
}

COMMUNITY_SOURCE_TYPES = {"community-forum", "korean-community", "korean-social"}
SEARCH_SOURCE_TYPES = {"agy-google-search", "google-search", "manual-browser-search"}
SEARCH_TREND_SOURCE_TYPES = {"google-trends-kr", "naver-datalab", "platform-analytics"}
VIDEO_DISCOVERY_SOURCE_TYPES = {
    "agy-youtube-search",
    "youtube-analytics-trends",
    "youtube-inspiration",
    "youtube-search",
}
OFFICIAL_TREND_SOURCE_TYPES = {
    "google-trends-kr",
    "naver-datalab",
    "platform-analytics",
    "youtube-inspiration",
    "youtube-analytics-trends",
}
MAX_CURRENT_SOURCE_AGE_DAYS = 14
BLOCKED_URL_HOSTS = {"example.com", "example.org", "example.net", "localhost", "127.0.0.1", "0.0.0.0"}

UNSAFE_RISK_FLAGS = (
    "unverifiedRumor",
    "defamationRisk",
    "privacyRisk",
    "protectedClassAttack",
    "minorSafetyRisk",
)


def evaluate_topic_discovery_gate(packet: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether a topic-selection packet is ready for production."""

    report: dict[str, Any] = {
        "schema": "video-studio.topic-discovery-gate.v1",
        "status": "pass",
        "topicReady": False,
        "selectedTopicId": _selected_topic_id(packet),
        "selectedScore": 0,
        "minimumScore": TOPIC_SELECTION_MINIMUM_SCORE,
        "failedChecks": [],
        "checks": {},
        "computedScores": {},
    }

    source_ledger = _object_list(packet, "sourceLedger")
    candidates = _object_list(packet, "topicCandidates")
    selected = _selected_candidate(packet, candidates)
    sources_by_id = _source_by_id(source_ledger)

    _check_source_ledger(packet, report, source_ledger)
    _check_research_query_plan(packet, report)
    _check_source_authenticity(report, source_ledger)
    _check_community_signal_diversity(report, selected, sources_by_id)
    _check_trend_cross_check(report, selected, sources_by_id)
    _check_curiosity_angle(report, selected)
    _check_longform_topic_fit(packet, report, selected)
    _check_audience_retention_fit(packet, report, selected)
    _check_safety_originality(report, selected)
    _check_selection_matrix(report, packet, candidates, selected, sources_by_id)

    if report["failedChecks"]:
        report["status"] = "fail"
    else:
        report["topicReady"] = True
    return report


def compute_topic_candidate_score(
    candidate: dict[str, Any],
    sources_by_id: dict[str, dict[str, Any]] | None = None,
    *,
    target_format: str = "longform_10m",
) -> int:
    """Compute the selection score used by topicSelectionMatrixGate."""

    source_map = sources_by_id or {}
    score = 0
    community_signals = _community_signals(candidate, source_map)
    trend_evidence = _trend_evidence(candidate, source_map)
    evidence_count = _evidence_count(candidate)
    source_depth = _number(candidate.get("sourcePlan", {}), "primarySourceCount")
    source_depth = max(source_depth, evidence_count)
    longform_plan = candidate.get("longformPlan") if isinstance(candidate.get("longformPlan"), dict) else {}
    risk_review = candidate.get("riskReview") if isinstance(candidate.get("riskReview"), dict) else {}
    originality = candidate.get("originalityReview") if isinstance(candidate.get("originalityReview"), dict) else {}

    if len(community_signals) >= 2 and len({signal.get("sourceId") for signal in community_signals}) >= 2:
        score += 20
    elif len(community_signals) >= 1:
        score += 8

    if len(trend_evidence) >= 2 and _has_official_trend_source(trend_evidence, source_map):
        score += 15
    elif len(trend_evidence) >= 1:
        score += 6

    curiosity_fields = (
        "workingTitle",
        "centralQuestion",
        "knowledgeGap",
        "whyNow",
        "viewerPromise",
    )
    present_curiosity = sum(1 for key in curiosity_fields if _text(candidate.get(key)))
    score += min(15, present_curiosity * 3)

    score += min(20, source_depth * 4)

    chapter_count = _number(longform_plan, "chapterCount")
    segment_count = _number(longform_plan, "segmentCount")
    retention_hooks = _list_value(longform_plan.get("retentionHooks"))
    if str(target_format).strip().lower() == "longform_10m":
        if chapter_count >= 6 and segment_count >= 18 and len(retention_hooks) >= 3:
            score += 15
        elif chapter_count >= 3 and segment_count >= 9:
            score += 7
    elif _text(longform_plan.get("hook")) or len(retention_hooks) >= 1:
        score += 15

    if _risk_review_safe(risk_review) and _originality_review_safe(originality):
        score += 15
    elif _originality_review_safe(originality):
        score += 6

    return min(100, score)


def _check_source_ledger(packet: dict[str, Any], report: dict[str, Any], source_ledger: list[dict[str, Any]]) -> None:
    if len(source_ledger) < 5:
        return _fail(report, "topicSourceLedgerGate", "sourceLedger needs at least five current/reference entries.")

    evaluation_date = _date_value(packet.get("evaluationDate"))
    if evaluation_date is None:
        return _fail(report, "topicSourceLedgerGate", "evaluationDate must be an ISO date.")

    source_types: set[str] = set()
    for source in source_ledger:
        missing = [
            key
            for key in ("sourceId", "sourceType", "title", "url", "capturedAt", "observation")
            if not _text(source.get(key))
        ]
        if missing:
            return _fail(
                report,
                "topicSourceLedgerGate",
                f"sourceLedger entry missing required fields: {', '.join(missing)}.",
            )
        source_type = _text(source.get("sourceType")).lower()
        source_types.add(source_type)
        captured_at = _date_value(source.get("capturedAt"))
        if captured_at is None:
            return _fail(report, "topicSourceLedgerGate", "sourceLedger capturedAt must be an ISO date.")
        if source_type in CURRENT_SOURCE_TYPES:
            age = (evaluation_date - captured_at).days
            if age < 0 or age > MAX_CURRENT_SOURCE_AGE_DAYS:
                return _fail(
                    report,
                    "topicSourceLedgerGate",
                    f"current source {source.get('sourceId')} is outside the {MAX_CURRENT_SOURCE_AGE_DAYS}-day window.",
                )

    if not source_types.intersection(OFFICIAL_TREND_SOURCE_TYPES):
        return _fail(report, "topicSourceLedgerGate", "sourceLedger needs at least one official/search trend source.")
    if not source_types.intersection(COMMUNITY_SOURCE_TYPES):
        return _fail(report, "topicSourceLedgerGate", "sourceLedger needs at least one community/social source.")
    report["checks"]["topicSourceLedgerGate"] = _check(
        "pass",
        f"source ledger has {len(source_ledger)} entries across {len(source_types)} source types.",
    )
    return None


def _check_research_query_plan(packet: dict[str, Any], report: dict[str, Any]) -> None:
    plan = _object_list(packet, "researchQueryPlan") or _object_list(packet, "queryPlan")
    if len(plan) < 4:
        return _fail(report, "researchQueryPlanGate", "researchQueryPlan needs at least four planned/executed queries.")

    evaluation_date = _date_value(packet.get("evaluationDate"))
    if evaluation_date is None:
        return _fail(report, "researchQueryPlanGate", "evaluationDate must be an ISO date before query recency can be checked.")

    groups: set[str] = set()
    has_korean_query = False
    for item in plan:
        missing = [
            key
            for key in ("provider", "query", "intent", "capturedAt")
            if not _text(item.get(key))
        ]
        if missing:
            return _fail(report, "researchQueryPlanGate", f"query plan item missing fields: {', '.join(missing)}.")
        captured_at = _date_value(item.get("capturedAt"))
        if captured_at is None:
            return _fail(report, "researchQueryPlanGate", "query plan capturedAt must be an ISO date.")
        age = (evaluation_date - captured_at).days
        if age < 0 or age > MAX_CURRENT_SOURCE_AGE_DAYS:
            return _fail(report, "researchQueryPlanGate", "query plan items must be within the current-source window.")
        group = _research_surface_group(item)
        if group:
            groups.add(group)
        if _has_hangul(_text(item.get("query"))):
            has_korean_query = True

    required_groups = {"search", "trend", "video", "community"}
    missing_groups = sorted(required_groups - groups)
    if missing_groups:
        return _fail(report, "researchQueryPlanGate", "query plan missing research surfaces: " + ", ".join(missing_groups) + ".")
    target_locale = _text(packet.get("targetLocale") or packet.get("locale")).lower()
    if target_locale in {"ko", "ko-kr", "kr"} and not has_korean_query:
        return _fail(report, "researchQueryPlanGate", "ko-KR topic discovery needs at least one Korean-language query.")
    report["checks"]["researchQueryPlanGate"] = _check(
        "pass",
        f"{len(plan)} query-plan items cover search, trend, video, and community surfaces.",
    )
    return None


def _check_source_authenticity(report: dict[str, Any], source_ledger: list[dict[str, Any]]) -> None:
    source_ids = [_text(source.get("sourceId")) for source in source_ledger if _text(source.get("sourceId"))]
    if len(source_ids) != len(set(source_ids)):
        return _fail(report, "sourceAuthenticityGate", "sourceLedger sourceId values must be unique.")

    source_types = {_text(source.get("sourceType")).lower() for source in source_ledger}
    problems: list[str] = []
    for source in source_ledger:
        url = _text(source.get("url"))
        if not _valid_source_url(url):
            problems.append(f"{source.get('sourceId') or 'source'} has placeholder or invalid url")
    if len(source_types.intersection(COMMUNITY_SOURCE_TYPES)) < 2:
        problems.append("sourceLedger needs at least two distinct community/social source types")
    if len(source_types.intersection(SEARCH_TREND_SOURCE_TYPES)) < 2:
        problems.append("sourceLedger needs at least two distinct official/search trend source types")
    if not source_types.intersection(VIDEO_DISCOVERY_SOURCE_TYPES):
        problems.append("sourceLedger needs a YouTube/video discovery source")
    if not source_types.intersection(SEARCH_SOURCE_TYPES):
        problems.append("sourceLedger needs a general search source such as Google search or agy-google-search")
    if problems:
        return _fail(report, "sourceAuthenticityGate", "; ".join(problems[:6]))
    report["checks"]["sourceAuthenticityGate"] = _check("pass", "source IDs, URLs, and source-surface diversity are authentic.")
    return None


def _check_community_signal_diversity(
    report: dict[str, Any],
    selected: dict[str, Any],
    sources_by_id: dict[str, dict[str, Any]],
) -> None:
    if not selected:
        return _fail(report, "communitySignalDiversityGate", "selection.selectedTopicId must resolve to a candidate.")
    signals = _community_signals(selected, sources_by_id)
    source_ids = {signal.get("sourceId") for signal in signals if _text(signal.get("sourceId"))}
    if len(signals) < 2 or len(source_ids) < 2:
        return _fail(
            report,
            "communitySignalDiversityGate",
            "selected topic needs at least two valid community signals from distinct source IDs.",
        )
    report["checks"]["communitySignalDiversityGate"] = _check(
        "pass",
        f"selected topic has {len(signals)} community signals from {len(source_ids)} sources.",
    )
    return None


def _check_trend_cross_check(
    report: dict[str, Any],
    selected: dict[str, Any],
    sources_by_id: dict[str, dict[str, Any]],
) -> None:
    if not selected:
        return _fail(report, "trendCrossCheckGate", "selection.selectedTopicId must resolve to a candidate.")
    trend_evidence = _trend_evidence(selected, sources_by_id)
    if len(trend_evidence) < 2 or not _has_official_trend_source(trend_evidence, sources_by_id):
        return _fail(
            report,
            "trendCrossCheckGate",
            "selected topic needs at least two trend evidence items and one official/search trend source.",
        )
    trend_source_types = {
        _text(sources_by_id.get(_text(item.get("sourceId")), {}).get("sourceType")).lower()
        for item in trend_evidence
    }
    if len(trend_source_types) < 2 or not trend_source_types.intersection(SEARCH_TREND_SOURCE_TYPES):
        return _fail(
            report,
            "trendCrossCheckGate",
            "trend evidence needs at least two source types and one search trend source such as Google Trends KR or Naver DataLab.",
        )
    report["checks"]["trendCrossCheckGate"] = _check(
        "pass",
        f"selected topic has {len(trend_evidence)} trend cross-checks with official/search evidence.",
    )
    return None


def _check_curiosity_angle(report: dict[str, Any], selected: dict[str, Any]) -> None:
    if not selected:
        return _fail(report, "curiosityAngleGate", "selection.selectedTopicId must resolve to a candidate.")
    missing = [
        key
        for key in ("workingTitle", "centralQuestion", "knowledgeGap", "whyNow", "viewerPromise")
        if not _text(selected.get(key))
    ]
    if missing:
        return _fail(report, "curiosityAngleGate", f"selected topic missing curiosity fields: {', '.join(missing)}.")
    report["checks"]["curiosityAngleGate"] = _check("pass", "selected topic has question, gap, timing, and promise.")
    return None


def _check_longform_topic_fit(packet: dict[str, Any], report: dict[str, Any], selected: dict[str, Any]) -> None:
    if not selected:
        return _fail(report, "longformTopicFitGate", "selection.selectedTopicId must resolve to a candidate.")
    target_format = _text(packet.get("targetFormat")).lower()
    source_plan = selected.get("sourcePlan") if isinstance(selected.get("sourcePlan"), dict) else {}
    evidence_count = max(_evidence_count(selected), _number(source_plan, "primarySourceCount"))
    longform_plan = selected.get("longformPlan") if isinstance(selected.get("longformPlan"), dict) else {}
    if longform_plan.get("oneShotMemeOnly") is True:
        return _fail(report, "longformTopicFitGate", "one-shot meme topics cannot enter longform dry-run.")
    if target_format == "longform_10m":
        chapter_count = _number(longform_plan, "chapterCount")
        segment_count = _number(longform_plan, "segmentCount")
        retention_hooks = _list_value(longform_plan.get("retentionHooks"))
        if evidence_count < 5:
            return _fail(report, "longformTopicFitGate", "longform topic needs at least five planned evidence sources.")
        if chapter_count < 6 or segment_count < 18 or len(retention_hooks) < 3:
            return _fail(
                report,
                "longformTopicFitGate",
                "longform topic needs at least six chapters, 18 segments, and three retention hooks.",
            )
    elif evidence_count < 2:
        return _fail(report, "longformTopicFitGate", "topic needs at least two evidence references before production.")
    report["checks"]["longformTopicFitGate"] = _check("pass", "selected topic has enough depth for the target format.")
    return None


def _check_audience_retention_fit(packet: dict[str, Any], report: dict[str, Any], selected: dict[str, Any]) -> None:
    if not selected:
        return _fail(report, "audienceRetentionFitGate", "selection.selectedTopicId must resolve to a candidate.")
    target_format = _text(packet.get("targetFormat")).lower()
    longform_plan = selected.get("longformPlan") if isinstance(selected.get("longformPlan"), dict) else {}
    if target_format != "longform_10m":
        if _text(longform_plan.get("hook")) or _list_value(longform_plan.get("retentionHooks")):
            report["checks"]["audienceRetentionFitGate"] = _check("pass", "shortform topic has a hook/retention note.")
            return None
        return _fail(report, "audienceRetentionFitGate", "shortform topic needs a hook or retention note.")

    missing = [
        key
        for key in ("first30SecPromise", "titleThumbnailExpectation", "topMomentPreview")
        if not _text(longform_plan.get(key))
    ]
    dip_mitigations = _list_value(longform_plan.get("dipRiskMitigations"))
    broken_mitigations = [
        item
        for item in dip_mitigations
        if not isinstance(item, dict) or not _text(item.get("risk")) or not _text(item.get("mitigation"))
    ]
    chapter_promises = _list_value(longform_plan.get("chapterPromises"))
    if missing:
        return _fail(report, "audienceRetentionFitGate", "longformPlan missing retention fields: " + ", ".join(missing) + ".")
    if len(dip_mitigations) < 2 or broken_mitigations:
        return _fail(report, "audienceRetentionFitGate", "longformPlan needs at least two dipRiskMitigations with risk and mitigation.")
    if len(chapter_promises) < 6:
        return _fail(report, "audienceRetentionFitGate", "longformPlan needs chapterPromises for at least six chapters.")
    report["checks"]["audienceRetentionFitGate"] = _check(
        "pass",
        "first-30s promise, top moment, dip-risk plan, and chapter promises are present.",
    )
    return None


def _check_safety_originality(report: dict[str, Any], selected: dict[str, Any]) -> None:
    if not selected:
        return _fail(report, "safetyOriginalityGate", "selection.selectedTopicId must resolve to a candidate.")
    risk_review = selected.get("riskReview") if isinstance(selected.get("riskReview"), dict) else {}
    originality = selected.get("originalityReview") if isinstance(selected.get("originalityReview"), dict) else {}
    if not _risk_review_safe(risk_review):
        return _fail(report, "safetyOriginalityGate", "selected topic has unresolved safety, rumor, privacy, or high-stakes risk.")
    if not _originality_review_safe(originality):
        return _fail(report, "safetyOriginalityGate", "selected topic needs a transformative angle and attribution plan.")
    report["checks"]["safetyOriginalityGate"] = _check("pass", "selected topic passed safety and originality review.")
    return None


def _check_selection_matrix(
    report: dict[str, Any],
    packet: dict[str, Any],
    candidates: list[dict[str, Any]],
    selected: dict[str, Any],
    sources_by_id: dict[str, dict[str, Any]],
) -> None:
    if len(candidates) < 3:
        return _fail(report, "topicSelectionMatrixGate", "topicCandidates needs at least three competing candidates.")
    selected_topic_id = _selected_topic_id(packet)
    if not selected_topic_id or not selected:
        return _fail(report, "topicSelectionMatrixGate", "selection.selectedTopicId must match a topic candidate.")

    target_format = _text(packet.get("targetFormat")) or "longform_10m"
    scores = {
        _candidate_id(candidate): compute_topic_candidate_score(
            candidate,
            sources_by_id,
            target_format=target_format,
        )
        for candidate in candidates
        if _candidate_id(candidate)
    }
    report["computedScores"] = scores
    selected_score = int(scores.get(selected_topic_id, 0))
    report["selectedScore"] = selected_score

    for candidate in candidates:
        declared = candidate.get("declaredScore")
        if declared is not None and _int_or_none(declared) != scores.get(_candidate_id(candidate)):
            return _fail(report, "topicSelectionMatrixGate", "declaredScore must match the computed topic score.")

    if selected_score < TOPIC_SELECTION_MINIMUM_SCORE:
        return _fail(
            report,
            "topicSelectionMatrixGate",
            f"selected topic score {selected_score} is below {TOPIC_SELECTION_MINIMUM_SCORE}.",
        )
    top_score = max(scores.values() or [0])
    if selected_score < top_score:
        return _fail(report, "topicSelectionMatrixGate", "selected topic is not the highest-scoring candidate.")

    rejected_ids = {
        _text(rejection.get("topicId"))
        for rejection in _object_list(packet.get("selection") if isinstance(packet.get("selection"), dict) else {}, "rejections")
        if _text(rejection.get("topicId")) and _text(rejection.get("reason"))
    }
    non_selected_ids = {_candidate_id(candidate) for candidate in candidates if _candidate_id(candidate) != selected_topic_id}
    if not non_selected_ids.issubset(rejected_ids):
        return _fail(report, "topicSelectionMatrixGate", "every non-selected candidate needs a rejection reason.")

    report["checks"]["topicSelectionMatrixGate"] = _check(
        "pass",
        f"selected topic scored {selected_score}/{TOPIC_SELECTION_MINIMUM_SCORE}+ and beat {len(candidates) - 1} alternatives.",
    )
    return None


def _community_signals(
    candidate: dict[str, Any],
    sources_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    signals = []
    for signal in _object_list(candidate, "communitySignals"):
        source = sources_by_id.get(_text(signal.get("sourceId")))
        source_type = _text(source.get("sourceType") if source else "").lower()
        if source_type in COMMUNITY_SOURCE_TYPES and _text(signal.get("signalType")) and _text(signal.get("observation")):
            signals.append(signal)
    return signals


def _trend_evidence(
    candidate: dict[str, Any],
    sources_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence = []
    for item in _object_list(candidate, "trendEvidence"):
        if not (_text(item.get("sourceId")) and _text(item.get("trendDirection")) and _text(item.get("observation"))):
            continue
        if _text(item.get("sourceId")) not in sources_by_id:
            continue
        if not _text(item.get("metricLabel")):
            continue
        evidence.append(item)
    return evidence


def _has_official_trend_source(
    trend_evidence: list[dict[str, Any]],
    sources_by_id: dict[str, dict[str, Any]],
) -> bool:
    for item in trend_evidence:
        source = sources_by_id.get(_text(item.get("sourceId")))
        if _text(source.get("sourceType") if source else "").lower() in OFFICIAL_TREND_SOURCE_TYPES:
            return True
    return False


def _research_surface_group(item: dict[str, Any]) -> str:
    explicit_surface = " ".join(_text(item.get(key)).lower() for key in ("surface", "surfaceType"))
    if any(token in explicit_surface for token in ("community", "forum", "social")):
        return "community"
    if any(token in explicit_surface for token in ("video", "youtube", "inspiration", "creator")):
        return "video"
    if any(token in explicit_surface for token in ("trend", "datalab", "analytics")):
        return "trend"
    if any(token in explicit_surface for token in ("search", "google", "manual-browser")):
        return "search"

    value = " ".join(_text(item.get(key)).lower() for key in ("provider", "sourceType"))
    if any(token in value for token in ("dcinside", "theqoo", "fmkorea", "community", "forum", "social")):
        return "community"
    if any(token in value for token in ("youtube", "inspiration", "creator")):
        return "video"
    if any(token in value for token in ("trend", "datalab", "analytics")):
        return "trend"
    if any(token in value for token in ("google", "search", "agy-google", "manual-browser")):
        return "search"
    return ""


def _risk_review_safe(risk_review: dict[str, Any]) -> bool:
    if not isinstance(risk_review, dict):
        return False
    for key in UNSAFE_RISK_FLAGS:
        if risk_review.get(key) is True:
            return False
    if risk_review.get("medicalLegalFinancialHighStakes") is True and not _text(risk_review.get("expertSourcePlan")):
        return False
    return _text(risk_review.get("factCheckPlan")) != ""


def _originality_review_safe(originality: dict[str, Any]) -> bool:
    return (
        isinstance(originality, dict)
        and originality.get("notSinglePostCopy") is True
        and originality.get("transformativeAngle") is True
        and _text(originality.get("sourceAttributionPlan")) != ""
    )


def _evidence_count(candidate: dict[str, Any]) -> int:
    source_plan = candidate.get("sourcePlan") if isinstance(candidate.get("sourcePlan"), dict) else {}
    return len(_list_value(source_plan.get("evidenceRefs")))


def _selected_candidate(packet: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    selected_topic_id = _selected_topic_id(packet)
    for candidate in candidates:
        if _candidate_id(candidate) == selected_topic_id:
            return candidate
    return {}


def _selected_topic_id(packet: dict[str, Any]) -> str:
    selection = packet.get("selection") if isinstance(packet.get("selection"), dict) else {}
    return _text(selection.get("selectedTopicId") or packet.get("selectedTopicId"))


def _candidate_id(candidate: dict[str, Any]) -> str:
    return _text(candidate.get("topicId") or candidate.get("id"))


def _source_by_id(source_ledger: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_text(source.get("sourceId")): source for source in source_ledger if _text(source.get("sourceId"))}


def _object_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(payload: dict[str, Any], key: str) -> int:
    if not isinstance(payload, dict):
        return 0
    value = payload.get(key)
    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _date_value(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _valid_source_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if host in BLOCKED_URL_HOSTS or host.endswith(".example.com"):
        return False
    return True


def _has_hangul(value: str) -> bool:
    return any("\uac00" <= char <= "\ud7a3" for char in value)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _fail(report: dict[str, Any], key: str, detail: str) -> None:
    report.setdefault("checks", {})[key] = _check("fail", detail)
    failed = report.setdefault("failedChecks", [])
    if key not in failed:
        failed.append(key)
    return None


def _check(status: str, detail: str) -> dict[str, str]:
    return {"status": status, "detail": detail}
