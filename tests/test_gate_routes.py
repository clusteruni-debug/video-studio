from __future__ import annotations

from datetime import datetime, timezone

from flask import Flask

from worker.bridge import routes_gates
from worker.bridge.routes_gates import gates_bp


def _client():
    app = Flask(__name__)
    app.register_blueprint(gates_bp)
    return app.test_client()


def _topic_packet() -> dict:
    return {
        "evaluationDate": "2026-06-22",
        "targetLocale": "ko-KR",
        "targetFormat": "longform_10m",
        "researchQueryPlan": [
            {"provider": "google-search", "surface": "search", "query": "AI 공부 인증 효과", "intent": "General search", "capturedAt": "2026-06-22"},
            {"provider": "google-trends-kr", "surface": "trend", "query": "AI 공부", "intent": "Trend check", "capturedAt": "2026-06-22"},
            {"provider": "youtube-search", "surface": "video", "query": "AI 공부 인증", "intent": "Video competition", "capturedAt": "2026-06-22"},
            {"provider": "korean-community-scan", "surface": "community", "query": "AI 공부 인증 후기", "intent": "Community objections", "capturedAt": "2026-06-22"},
        ],
        "sourceLedger": [
            _source("google-search", "google-search", "https://www.google.com/search?q=AI+study"),
            _source("google-trends-kr", "google-trends-kr", "https://trends.google.com/trending?geo=KR"),
            _source("naver-datalab", "naver-datalab", "https://datalab.naver.com/"),
            _source("youtube-search", "youtube-search", "https://www.youtube.com/results?search_query=AI+study"),
            _source("dcinside-hot", "korean-community", "https://www.dcinside.com/"),
            _source("fmkorea-best", "community-forum", "https://www.fmkorea.com/"),
        ],
        "topicCandidates": [
            _candidate("selected-topic", strong=True),
            _candidate("thin-topic-a", strong=False),
            _candidate("thin-topic-b", strong=False),
        ],
        "selection": {
            "selectedTopicId": "selected-topic",
            "rejections": [
                {"topicId": "thin-topic-a", "reason": "Not enough evidence depth."},
                {"topicId": "thin-topic-b", "reason": "Weak trend cross-check."},
            ],
        },
    }


def _source(source_id: str, source_type: str, url: str) -> dict:
    return {
        "sourceId": source_id,
        "sourceType": source_type,
        "title": f"{source_id} observation",
        "url": url,
        "capturedAt": "2026-06-22",
        "observation": "Concrete current topic signal.",
    }


def _candidate(topic_id: str, *, strong: bool) -> dict:
    chapter_count = 6 if strong else 3
    segment_count = 18 if strong else 9
    evidence_refs = [f"source-{index:02d}" for index in range(1, (6 if strong else 3) + 1)]
    return {
        "topicId": topic_id,
        "workingTitle": f"{topic_id} working title",
        "centralQuestion": "What practical question should the viewer answer?",
        "knowledgeGap": "Community attention lacks a verified decision path.",
        "whyNow": "Recent Korean search and community surfaces show renewed attention.",
        "viewerPromise": "Turn noisy attention into a clear answer.",
        "communitySignals": [
            {"sourceId": "dcinside-hot", "signalType": "repeat-question", "observation": "Repeated question."},
            {"sourceId": "fmkorea-best" if strong else "dcinside-hot", "signalType": "debate-thread", "observation": "Repeated objection."},
        ],
        "trendEvidence": [
            {"sourceId": "google-trends-kr", "trendDirection": "rising", "metricLabel": "Trending Now", "observation": "Related query movement."},
            {"sourceId": "naver-datalab" if strong else "google-trends-kr", "trendDirection": "stable", "metricLabel": "Search trend", "observation": "Search interest holds."},
        ],
        "sourcePlan": {"primarySourceCount": len(evidence_refs), "evidenceRefs": evidence_refs},
        "longformPlan": {
            "chapterCount": chapter_count,
            "segmentCount": segment_count,
            "retentionHooks": ["open-question", "midpoint-counterexample", "payoff-preview"] if strong else ["single-hook"],
            "first30SecPromise": "Open with the strongest question.",
            "titleThumbnailExpectation": "Opening matches the title promise.",
            "topMomentPreview": "Preview the strongest evidence.",
            "dipRiskMitigations": [
                {"risk": "abstract evidence", "mitigation": "use a concrete comparison"},
                {"risk": "repetition", "mitigation": "add a counterexample"},
            ],
            "chapterPromises": [
                {"chapterId": f"chapter-{index:02d}", "promise": f"Resolve viewer question {index}."}
                for index in range(1, chapter_count + 1)
            ],
        },
        "riskReview": {
            "unverifiedRumor": False,
            "defamationRisk": False,
            "privacyRisk": False,
            "protectedClassAttack": False,
            "minorSafetyRisk": False,
            "factCheckPlan": "Verify against durable sources.",
        },
        "originalityReview": {
            "notSinglePostCopy": True,
            "transformativeAngle": True,
            "sourceAttributionPlan": "Attribute cited sources.",
        },
    }


def test_topic_discovery_gate_route_returns_report():
    response = _client().post("/api/gates/topic-discovery/evaluate", json={"packet": _topic_packet()})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["ready"] is True
    assert payload["report"]["schema"] == "video-studio.topic-discovery-gate.v1"
    assert payload["failedChecks"] == []
    assert payload["ux"]["title"] == "소재 검증"
    assert payload["ux"]["statusLabel"] == "통과"
    assert "2단계" in payload["ux"]["nextAction"]


def test_longform_dryrun_gate_route_surfaces_blocking_report():
    response = _client().post("/api/gates/longform-dryrun/evaluate", json={"packet": {"targetStage": "rough-cut"}})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["ready"] is False
    assert "dryrunTopicDiscoveryGate" in payload["failedChecks"]
    assert payload["ux"]["title"] == "롱폼 준비 검증"
    assert payload["ux"]["statusLabel"] == "보완 필요"
    assert {"key": "dryrunTopicDiscoveryGate", "label": "소재 검증"} in payload["ux"]["failedChecks"]
    assert payload["ux"]["checkSummaries"][0]["detail"] == "1단계 소재 검증 결과를 먼저 연결하세요."
    assert "topicDiscoveryPacket object is required" in payload["ux"]["checkSummaries"][0]["rawDetail"]


def test_hot_topic_candidates_route_returns_live_seed_when_news_available(monkeypatch):
    def fake_fetch(seed: str, *, limit: int = 6, timeout: float = 4.0):
        assert seed == ""
        return (
            [
                {
                    "title": "테스트 급상승 이슈 - Test News",
                    "cleanTitle": "테스트 급상승 이슈",
                    "url": "https://news.google.com/rss/articles/test",
                    "publishedAt": "2026-06-22T00:00:00+00:00",
                }
            ],
            "google-news-top-rss",
        )

    monkeypatch.setattr(routes_gates, "_fetch_google_news_items", fake_fetch)

    response = _client().get("/api/topic-discovery/hot-candidates?limit=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["mode"] == "auto-hot-topic"
    assert payload["source"] == "google-news-top-rss"
    assert payload["live"] is True
    assert payload["candidates"][0]["sourceStatus"] == "live-news-seed"
    assert payload["candidates"][0]["sourceRefs"] == ["news-source-01"]
    assert payload["rankedBy"] == ["freshness", "sourceEvidence", "surfaceCoverage", "longformFit", "selectionPriority"]
    assert payload["nextPipeline"]["step"] == "source-ledger-draft"
    assert payload["candidates"][0]["scoreBreakdown"]["sourceEvidence"] == 18
    assert "Google News KR" in payload["candidates"][0]["rankingReason"]
    assert "sourceLedger" in payload["candidates"][0]["nextPipelineAction"]
    research_links = payload["candidates"][0]["researchLinks"]
    assert [item["surface"] for item in research_links] == ["search", "trend", "video", "community"]
    assert research_links[1]["sourceType"] == "google-trends-kr"
    assert research_links[2]["url"].startswith("https://www.youtube.com/results?")
    assert research_links[3]["requiredForGate"] is True
    assert research_links[3]["sourceRef"] == "news-source-01"
    assert payload["sourceLedger"][0]["sourceType"] == "google-news-kr"
    assert "researchLinks" in payload["operatorWarning"]


def test_hot_topic_candidate_capture_dates_use_korea_day(monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(2026, 6, 21, 16, 30, tzinfo=timezone.utc)
            return base.astimezone(tz) if tz else base.replace(tzinfo=None)

    monkeypatch.setattr(routes_gates, "datetime", FrozenDateTime)
    monkeypatch.setattr(
        routes_gates,
        "_fetch_google_news_items",
        lambda seed, *, limit=6, timeout=4.0: (
            [
                {
                    "title": "한국 시간 날짜 검증 - Test News",
                    "cleanTitle": "한국 시간 날짜 검증",
                    "url": "https://news.google.com/rss/articles/date-test",
                    "publishedAt": "2026-06-21T16:00:00+00:00",
                }
            ],
            "google-news-top-rss",
        ),
    )

    payload = routes_gates.build_hot_topic_candidates("", limit=1)

    assert payload["researchQueryPlan"][0]["capturedAt"] == "2026-06-22"
    assert payload["sourceLedger"][0]["capturedAt"] == "2026-06-22"
    assert payload["candidates"][0]["researchLinks"][0]["capturedAt"] == "2026-06-22"


def test_hot_topic_candidates_route_falls_back_without_live_source(monkeypatch):
    def fake_fetch(seed: str, *, limit: int = 6, timeout: float = 4.0):
        raise TimeoutError("offline")

    monkeypatch.setattr(routes_gates, "_fetch_google_news_items", fake_fetch)

    response = _client().get("/api/topic-discovery/hot-candidates?seed=AI%20%EA%B3%B5%EB%B6%80&limit=2")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["mode"] == "keyword-filtered"
    assert payload["source"] == "fallback-static"
    assert payload["live"] is False
    assert len(payload["candidates"]) == 2
    assert payload["sourceLedger"] == []
    assert payload["candidates"][0]["scoreBreakdown"]["sourceEvidence"] == 6
    assert "실제 출처 점수는 낮게" in payload["candidates"][0]["rankingReason"]
    assert payload["candidates"][0]["researchLinks"][0]["surface"] == "search"
    assert payload["candidates"][0]["researchLinks"][2]["sourceType"] == "youtube-search"
    assert "researchLinks" in payload["operatorWarning"]
