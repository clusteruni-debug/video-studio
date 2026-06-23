from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import re
import xml.etree.ElementTree as ET

from flask import Blueprint, jsonify, request

from worker.bridge.material_library import (
    append_gate_event,
    append_material_outcome,
    build_material_production_handoff,
    evaluate_material_quality,
    intake_material,
    library_stats,
    load_material_library,
    material_summary,
)
from worker.bridge.material_dryrun import latest_material_dryrun_summary, run_material_dryrun_preflight
from worker.render.longform_dryrun_readiness import evaluate_longform_dryrun_readiness
from worker.render.longform_minimum_release_gate import build_longform_publish_packet_template
from worker.render.production_gate_orchestrator import build_process_gate_audit, evaluate_production_gates
from worker.render.topic_discovery_gate import evaluate_topic_discovery_gate


gates_bp = Blueprint("gates", __name__)
HOT_DISCOVERY_SEED = "오늘 한국에서 가장 뜨거운 소재"
GOOGLE_NEWS_TOP_KR_RSS = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
GOOGLE_NEWS_SEARCH_KR_RSS = "https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
DISCOVERY_EVIDENCE_PLAN = ["Google News KR", "Google Trends KR", "YouTube 급상승", "한국 커뮤니티 반응"]
DISCOVERY_RESEARCH_SURFACES = [
    {
        "label": "Google 검색",
        "provider": "google-search",
        "surface": "search",
        "sourceType": "google-search",
        "intent": "반복 질문과 설명 후보 확인",
    },
    {
        "label": "트렌드 교차 확인",
        "provider": "google-trends-kr",
        "surface": "trend",
        "sourceType": "google-trends-kr",
        "intent": "현재성 교차 확인",
    },
    {
        "label": "YouTube 경쟁 영상",
        "provider": "youtube-search",
        "surface": "video",
        "sourceType": "youtube-search",
        "intent": "영상 경쟁과 댓글 질문 확인",
    },
    {
        "label": "한국 커뮤니티",
        "provider": "korean-community-scan",
        "surface": "community",
        "sourceType": "korean-community",
        "intent": "한국 커뮤니티 반복 질문과 논쟁 확인",
    },
]

CHECK_LABELS = {
    "researchQueryPlanGate": "검색 계획",
    "sourceAuthenticityGate": "실제 출처",
    "sourceSurfaceDiversityGate": "출처 표면 다양성",
    "communitySignalGate": "커뮤니티 신호",
    "trendCrossCheckGate": "트렌드 교차 확인",
    "topicCandidateMatrixGate": "소재 후보 비교",
    "candidateMatrixGate": "소재 후보 비교",
    "audienceRetentionFitGate": "시청 유지력",
    "longformRetentionFitGate": "롱폼 유지력",
    "riskReviewGate": "리스크 검토",
    "safetyGate": "안전성",
    "originalityGate": "독창성",
    "selectionGate": "최종 선택 근거",
    "dryrunTopicDiscoveryGate": "소재 검증",
    "dryrunWorkflowGate": "제작 순서",
    "dryrunProductionModeGate": "롱폼 제작 조건",
    "dryrunRenderPreflightGate": "렌더 전 점검",
    "dryrunMinimumReleaseGate": "최소 출시 기준",
    "dryrunFinalLibraryGate": "최종 라이브러리 검수",
}

CHECK_ACTIONS = {
    "researchQueryPlanGate": "검색, 트렌드, 영상, 커뮤니티 표면별 검색 계획을 채우세요.",
    "sourceAuthenticityGate": "placeholder가 아닌 실제 URL과 관찰 내용을 연결하세요.",
    "sourceSurfaceDiversityGate": "검색, 트렌드, 영상, 커뮤니티처럼 서로 다른 출처 표면을 섞으세요.",
    "communitySignalGate": "한국 커뮤니티에서 반복 질문이나 논쟁 신호를 최소 2개 이상 남기세요.",
    "trendCrossCheckGate": "Google Trends, Naver DataLab 같은 트렌드 표면으로 현재성을 교차 확인하세요.",
    "topicCandidateMatrixGate": "후보 소재를 여러 개 놓고 선택/탈락 이유를 분리해 적으세요.",
    "candidateMatrixGate": "후보 소재를 여러 개 놓고 선택/탈락 이유를 분리해 적으세요.",
    "audienceRetentionFitGate": "첫 30초 약속, 강한 장면 예고, 중간 이탈 방지 장치를 채우세요.",
    "longformRetentionFitGate": "첫 30초 약속, 강한 장면 예고, 중간 이탈 방지 장치를 채우세요.",
    "riskReviewGate": "루머, 명예훼손, 개인정보, 안전 리스크를 명시적으로 검토하세요.",
    "safetyGate": "안전 리스크와 사실 확인 계획을 먼저 채우세요.",
    "originalityGate": "단일 글 복붙이 아닌 변형 관점과 출처 표기 계획을 채우세요.",
    "selectionGate": "최종 선택한 소재와 탈락시킨 소재의 이유를 남기세요.",
    "dryrunTopicDiscoveryGate": "1단계 소재 검증 결과를 먼저 연결하세요.",
    "dryrunWorkflowGate": "롱폼 제작 순서, 단계별 증거, 개선 루프 데이터를 채우세요.",
    "dryrunProductionModeGate": "롱폼 제작 조건 데이터를 채우세요.",
    "dryrunRenderPreflightGate": "렌더 전 점검용 manifest를 연결하세요.",
    "dryrunMinimumReleaseGate": "최종/게시 단계에서는 최소 출시 기준 증거를 채우세요.",
    "dryrunFinalLibraryGate": "최종 라이브러리 검수 결과를 연결하세요.",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _korea_today() -> str:
    return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


def _slug(text: str) -> str:
    value = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", text.strip().lower()).strip("-")
    return value[:48] or "hot-topic"


def _strip_source_suffix(title: str) -> str:
    # Google News RSS titles often end with " - Publisher".
    return re.sub(r"\s+-\s+[^-]{2,40}$", "", title).strip() or title.strip()


def _research_url(surface: str, query: str) -> str:
    if surface == "trend":
        return f"https://trends.google.com/trends/explore?geo=KR&q={quote_plus(query)}"
    if surface == "video":
        return f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    if surface == "community":
        community_query = f"{query} site:dcinside.com OR site:fmkorea.com OR site:theqoo.net"
        return f"https://www.google.com/search?q={quote_plus(community_query)}"
    return f"https://www.google.com/search?q={quote_plus(query)}"


def _candidate_research_links(seed: str, *, captured_at: str, source_ref: str = "") -> list[dict[str, Any]]:
    basis = seed.strip() or HOT_DISCOVERY_SEED
    links: list[dict[str, Any]] = []
    for surface in DISCOVERY_RESEARCH_SURFACES:
        if surface["surface"] == "search":
            query = f"{basis} 왜 궁금한가 한국어"
        elif surface["surface"] == "video":
            query = f"{basis} 설명"
        elif surface["surface"] == "community":
            query = f"{basis} 후기 논란 왜"
        else:
            query = basis
        links.append(
            {
                **surface,
                "query": query,
                "url": _research_url(surface["surface"], query),
                "capturedAt": captured_at,
                "sourceRef": source_ref,
                "requiredForGate": surface["surface"] != "search",
                "ledgerAction": "이 표면을 열어 실제 관찰을 확인한 뒤 sourceLedger에 추가하세요.",
            }
        )
    return links


def _candidate_score_breakdown(*, index: int, live: bool, source_ref_count: int, link_count: int, base_score: int) -> dict[str, int]:
    freshness = max(8, (24 if live else 14) - index * 2)
    source_evidence = 18 if source_ref_count else 6
    surface_coverage = min(20, link_count * 5)
    longform_fit = min(22, max(12, base_score // 4))
    selection_priority = max(8, 20 - index * 3)
    return {
        "freshness": freshness,
        "sourceEvidence": source_evidence,
        "surfaceCoverage": surface_coverage,
        "longformFit": longform_fit,
        "selectionPriority": selection_priority,
    }


def _candidate_score(*, index: int, live: bool, source_ref_count: int, link_count: int, base_score: int) -> tuple[int, dict[str, int]]:
    breakdown = _candidate_score_breakdown(
        index=index,
        live=live,
        source_ref_count=source_ref_count,
        link_count=link_count,
        base_score=base_score,
    )
    return min(100, sum(breakdown.values())), breakdown


def _parse_rss_date(value: str) -> str:
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return _utc_now_iso()


def _fetch_google_news_items(seed: str, *, limit: int = 6, timeout: float = 4.0) -> tuple[list[dict[str, Any]], str]:
    seed = seed.strip()
    if seed:
        url = GOOGLE_NEWS_SEARCH_KR_RSS.format(query=quote_plus(seed))
        mode = "google-news-search-rss"
    else:
        url = GOOGLE_NEWS_TOP_KR_RSS
        mode = "google-news-top-rss"
    req = Request(url, headers={"User-Agent": "video-studio-topic-discovery/1.0"})
    with urlopen(req, timeout=timeout) as response:  # nosec B310 - fixed Google News RSS host.
        raw = response.read(1_000_000)
    root = ET.fromstring(raw)
    items: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        if not title or not link:
            continue
        items.append(
            {
                "title": title,
                "cleanTitle": _strip_source_suffix(title),
                "url": link,
                "publishedAt": _parse_rss_date(pub_date),
            }
        )
        if len(items) >= limit:
            break
    return items, mode


def _fallback_candidate(seed: str, index: int) -> dict[str, Any]:
    auto_hot = not seed.strip()
    if auto_hot:
        presets = [
            {
                "id": "hot-trend-why-now",
                "title": "오늘 갑자기 뜬 검색어의 이유",
                "centralQuestion": "왜 이 검색어가 오늘 갑자기 올라왔고, 사람들은 무엇을 확인하려고 하는가?",
                "whyHot": "급상승 검색은 현재성은 강하지만 맥락이 비어 있어 해설형 롱폼으로 확장하기 좋습니다.",
                "searchSeed": "오늘 한국 급상승 검색어 왜",
                "score": 84,
            },
            {
                "id": "community-split-issue",
                "title": "한국 커뮤니티에서 갈리는 생활형 논쟁",
                "centralQuestion": "사람들이 같은 이슈를 두고 왜 정반대로 해석하는가?",
                "whyHot": "댓글 논쟁은 훅과 반론 구조가 자연스럽고, 10분 영상에서 관점 비교로 유지력을 만들 수 있습니다.",
                "searchSeed": "오늘 한국 커뮤니티 논쟁 왜",
                "score": 79,
            },
            {
                "id": "youtube-comment-question",
                "title": "YouTube 급상승 댓글의 반복 질문",
                "centralQuestion": "인기 영상 댓글에서 반복되는 질문은 무엇이고, 답이 왜 부족한가?",
                "whyHot": "이미 영상 소비가 있는 소재라 제목/오프닝/댓글 반응을 롱폼 설계에 바로 연결할 수 있습니다.",
                "searchSeed": "YouTube 인기 급상승 댓글 질문 한국",
                "score": 74,
            },
        ]
        base = presets[index]
    else:
        base = {
            "id": f"keyword-{index + 1}",
            "title": f"{seed}이 지금 뜨는 이유" if index == 0 else f"{seed} 검증 후보 {index + 1}",
            "centralQuestion": f"{seed}은 왜 지금 관심을 받고 있고, 무엇을 확인해야 하는가?",
            "whyHot": "입력 키워드를 검색/트렌드/영상/커뮤니티 표면으로 검증합니다.",
            "searchSeed": f"{seed} 왜 지금",
            "score": 82 - index * 6,
        }
    research_links = _candidate_research_links(base["searchSeed"], captured_at=_korea_today())
    score, score_breakdown = _candidate_score(
        index=index,
        live=False,
        source_ref_count=0,
        link_count=len(research_links),
        base_score=base["score"],
    )
    return {
        **base,
        "label": f"{index + 1}순위",
        "viewerPromise": "흩어진 관심을 출처 기반 판단으로 정리합니다.",
        "first30SecPromise": "가장 큰 질문과 오해를 첫 30초에 먼저 보여준다.",
        "evidencePlan": DISCOVERY_EVIDENCE_PLAN,
        "researchLinks": research_links,
        "sourceRefs": [],
        "sourceStatus": "fallback-needs-live-source",
        "score": score,
        "scoreBreakdown": score_breakdown,
        "rankingReason": "fallback 후보라 실제 출처 점수는 낮게 잡고, 표면별 검증 링크를 채운 뒤 재평가해야 합니다.",
        "nextPipelineAction": "researchLinks를 열어 실제 URL과 관찰 메모를 sourceLedger에 반영하세요.",
    }


def _candidate_from_news_item(item: dict[str, Any], index: int, *, seed: str) -> dict[str, Any]:
    title = item["cleanTitle"]
    source_refs = [f"news-source-{index + 1:02d}"]
    research_links = _candidate_research_links(title, captured_at=_korea_today(), source_ref=source_refs[0])
    score, score_breakdown = _candidate_score(
        index=index,
        live=True,
        source_ref_count=len(source_refs),
        link_count=len(research_links),
        base_score=max(64, 88 - index * 5),
    )
    return {
        "id": f"news-{index + 1}-{_slug(title)}",
        "label": f"{index + 1}순위",
        "title": title,
        "centralQuestion": f"{title}은 왜 지금 주목받고 있고, 시청자가 확인해야 할 핵심은 무엇인가?",
        "whyHot": "Google News KR 현재 표면에 노출된 최신 기사 후보입니다. 트렌드/커뮤니티/영상 표면으로 교차 확인해야 합니다.",
        "viewerPromise": "뉴스 표면의 현재 이슈를 배경, 쟁점, 반론, 다음 질문 순서로 정리합니다.",
        "searchSeed": seed.strip() or title,
        "first30SecPromise": "현재 기사 제목의 핵심 질문을 먼저 보여주고 왜 볼 가치가 있는지 제시한다.",
        "score": score,
        "scoreBreakdown": score_breakdown,
        "rankingReason": "Google News KR 현재 후보에 표면별 검증 링크를 결합해 우선순위를 매겼습니다.",
        "nextPipelineAction": "트렌드, YouTube, 커뮤니티 관찰을 sourceLedger에 추가한 뒤 소재 게이트를 실행하세요.",
        "evidencePlan": DISCOVERY_EVIDENCE_PLAN,
        "researchLinks": research_links,
        "sourceRefs": source_refs,
        "sourceStatus": "live-news-seed",
        "sourceUrl": item["url"],
        "publishedAt": item["publishedAt"],
    }


def _source_ledger_from_news(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        ledger.append(
            {
                "sourceId": f"news-source-{index:02d}",
                "sourceType": "google-news-kr",
                "title": item["cleanTitle"],
                "url": item["url"],
                "capturedAt": _korea_today(),
                "observation": "Google News KR current RSS candidate; cross-check with trend, video, and community surfaces before validation.",
            }
        )
    return ledger


def _query_plan(seed: str, *, captured_at: str) -> list[dict[str, Any]]:
    basis = seed.strip() or HOT_DISCOVERY_SEED
    return [
        {"provider": "google-news-kr", "surface": "news", "query": basis, "intent": "현재 뉴스 표면 후보 확인", "capturedAt": captured_at},
        {"provider": "google-trends-kr", "surface": "trend", "query": basis, "intent": "급상승/현재성 교차 확인", "capturedAt": captured_at},
        {"provider": "youtube-search", "surface": "video", "query": basis, "intent": "영상 경쟁/댓글 질문 확인", "capturedAt": captured_at},
        {"provider": "korean-community-scan", "surface": "community", "query": basis, "intent": "한국 커뮤니티 반복 질문 확인", "capturedAt": captured_at},
    ]


def build_hot_topic_candidates(seed: str = "", *, limit: int = 3) -> dict[str, Any]:
    captured_at = _korea_today()
    try:
        items, source = _fetch_google_news_items(seed, limit=max(limit, 3))
    except Exception as exc:
        items = []
        source = "fallback-static"
        warning = f"live source unavailable: {exc.__class__.__name__}"
    else:
        warning = ""
    if items:
        candidates = [_candidate_from_news_item(item, index, seed=seed) for index, item in enumerate(items[:limit])]
        source_ledger = _source_ledger_from_news(items[:limit])
        live = True
    else:
        candidates = [_fallback_candidate(seed, index) for index in range(limit)]
        source_ledger = []
        live = False
    return {
        "ok": True,
        "mode": "keyword-filtered" if seed.strip() else "auto-hot-topic",
        "source": source,
        "live": live,
        "warning": warning,
        "seed": seed.strip() or HOT_DISCOVERY_SEED,
        "fetchedAt": _utc_now_iso(),
        "candidates": candidates,
        "rankedBy": ["freshness", "sourceEvidence", "surfaceCoverage", "longformFit", "selectionPriority"],
        "sourceLedger": source_ledger,
        "researchQueryPlan": _query_plan(seed, captured_at=captured_at),
        "nextPipeline": {
            "step": "source-ledger-draft",
            "action": "Open candidate researchLinks, record actual observations, then run topic-discovery gate.",
            "minimumSourceLedgerEntries": 5,
            "requiredSurfaces": ["search", "trend", "video", "community"],
        },
        "operatorWarning": (
            "뉴스 후보는 출발점입니다. 후보별 researchLinks를 열어 트렌드, YouTube, 커뮤니티 관찰을 sourceLedger에 추가해야 소재 게이트가 통과합니다."
            if live
            else "Fallback 후보입니다. 후보별 researchLinks를 열거나 실제 URL을 sourceLedger에 채운 뒤 검증하세요."
        ),
    }


def _packet_from_request(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    packet = data.get("packet")
    if isinstance(packet, dict):
        return packet
    return data


@gates_bp.route("/api/topic-discovery/hot-candidates", methods=["GET"])
def hot_topic_candidates_route():
    seed = str(request.args.get("seed", "") or "")
    try:
        limit = max(1, min(6, int(request.args.get("limit", "3"))))
    except ValueError:
        limit = 3
    return jsonify(build_hot_topic_candidates(seed, limit=limit))


def _library_response_payload() -> dict[str, Any]:
    library = load_material_library()
    materials = [item for item in library.get("materials", []) if isinstance(item, dict)]
    summaries = [material_summary(item) for item in materials]
    return {
        "ok": True,
        "schema": library.get("schema"),
        "stats": library_stats(materials),
        "materials": materials,
        "summaries": summaries,
        "dryrunPreflight": latest_material_dryrun_summary(),
    }


@gates_bp.route("/api/topic-library/materials", methods=["GET"])
def topic_library_materials_route():
    return jsonify(_library_response_payload())


@gates_bp.route("/api/topic-library/materials/intake", methods=["POST"])
def topic_library_material_intake_route():
    payload = request.get_json(silent=True) or {}
    result = intake_material(payload if isinstance(payload, dict) else {})
    gate_report = evaluate_production_gates(result["material"], packets={"topicGateResult": payload.get("topicGateResult")} if isinstance(payload, dict) else {})
    return jsonify(
        {
            "ok": True,
            **result,
            "productionGates": gate_report,
            "productionHandoff": build_material_production_handoff(result["material"]),
            "materialEvaluation": evaluate_material_quality(result["material"]),
        }
    )


@gates_bp.route("/api/topic-library/materials/<material_id>/production-handoff", methods=["GET"])
def topic_library_production_handoff_route(material_id: str):
    library = load_material_library()
    material = next(
        (
            item
            for item in library.get("materials", [])
            if isinstance(item, dict) and item.get("materialId") == material_id
        ),
        None,
    )
    if material is None:
        return jsonify({"ok": False, "error": "material-not-found", "materialId": material_id}), 404
    return jsonify({"ok": True, "productionHandoff": build_material_production_handoff(material)})


@gates_bp.route("/api/topic-library/materials/dryrun-preflight", methods=["GET"])
def topic_library_dryrun_preflight_status_route():
    return jsonify({"ok": True, "dryrunPreflight": latest_material_dryrun_summary()})


@gates_bp.route("/api/topic-library/materials/dryrun-preflight", methods=["POST"])
def topic_library_dryrun_preflight_route():
    payload = request.get_json(silent=True) or {}
    payload = payload if isinstance(payload, dict) else {}
    material_id = str(payload.get("materialId") or "").strip()
    target_stage = str(payload.get("targetStage") or "rough-cut").strip() or "rough-cut"
    try:
        result = run_material_dryrun_preflight(material_id=material_id, target_stage=target_stage)
    except KeyError:
        return jsonify({"ok": False, "error": "material-not-found", "materialId": material_id}), 404
    return jsonify(result)


@gates_bp.route("/api/topic-library/materials/<material_id>/gate-event", methods=["POST"])
def topic_library_gate_event_route(material_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        material = append_gate_event(material_id, payload if isinstance(payload, dict) else {})
    except KeyError:
        return jsonify({"ok": False, "error": "material-not-found", "materialId": material_id}), 404
    return jsonify({"ok": True, "material": material, "productionGates": evaluate_production_gates(material)})


@gates_bp.route("/api/topic-library/materials/<material_id>/outcome", methods=["POST"])
def topic_library_material_outcome_route(material_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        material = append_material_outcome(material_id, payload if isinstance(payload, dict) else {})
    except KeyError:
        return jsonify({"ok": False, "error": "material-not-found", "materialId": material_id}), 404
    library_payload = _library_response_payload()
    return jsonify(
        {
            "ok": True,
            "material": material,
            "summary": material_summary(material),
            "stats": library_payload["stats"],
        }
    )


@gates_bp.route("/api/production-gates/orchestrate", methods=["POST"])
def production_gates_orchestrate_route():
    payload = request.get_json(silent=True) or {}
    payload = payload if isinstance(payload, dict) else {}
    material = payload.get("material")
    if not isinstance(material, dict):
        material_id = str(payload.get("materialId", "") or "")
        library = load_material_library()
        material = next(
            (
                item
                for item in library.get("materials", [])
                if isinstance(item, dict) and item.get("materialId") == material_id
            ),
            None,
        )
        if material is None:
            return jsonify({"ok": False, "error": "material-not-found", "materialId": material_id}), 404
    return jsonify({"ok": True, "gateReport": evaluate_production_gates(material, packets=payload.get("packets"))})


@gates_bp.route("/api/production-gates/publish-packet-template", methods=["POST"])
def production_gates_publish_packet_template_route():
    payload = request.get_json(silent=True) or {}
    payload = payload if isinstance(payload, dict) else {}
    material = payload.get("material")
    if not isinstance(material, dict):
        material_id = str(payload.get("materialId", "") or "")
        library = load_material_library()
        material = next(
            (
                item
                for item in library.get("materials", [])
                if isinstance(item, dict) and item.get("materialId") == material_id
            ),
            None,
        )
        if material_id and material is None:
            return jsonify({"ok": False, "error": "material-not-found", "materialId": material_id}), 404
    release_packet = payload.get("releasePacket") if isinstance(payload.get("releasePacket"), dict) else {}
    return jsonify(
        {
            "ok": True,
            "publishPacketTemplate": build_longform_publish_packet_template(material, release_packet),
        }
    )


@gates_bp.route("/api/production-gates/process-audit", methods=["GET"])
def production_gates_process_audit_route():
    return jsonify({"ok": True, "audit": build_process_gate_audit()})


def _check_label(key: str) -> str:
    return CHECK_LABELS.get(key, key)


def _check_detail_ko(key: str, *, status: Any, raw_detail: Any) -> str:
    if status == "pass":
        return "기준을 충족했습니다."
    if status == "skip":
        return "이번 단계에서는 건너뜁니다."
    if key in CHECK_ACTIONS:
        return CHECK_ACTIONS[key]
    if isinstance(raw_detail, str) and raw_detail:
        return raw_detail
    return "필요한 데이터를 보완하세요."


def _check_summaries(report: dict[str, Any]) -> list[dict[str, Any]]:
    checks = report.get("checks")
    if not isinstance(checks, dict):
        return []
    summaries: list[dict[str, Any]] = []
    for key, value in checks.items():
        check = value if isinstance(value, dict) else {}
        status = check.get("status")
        raw_detail = check.get("detail")
        summaries.append(
            {
                "key": key,
                "label": _check_label(key),
                "status": status,
                "detail": _check_detail_ko(key, status=status, raw_detail=raw_detail),
                "rawDetail": raw_detail,
            }
        )
    return summaries


def _gate_ux(gate: str, *, ready: bool, report: dict[str, Any]) -> dict[str, Any]:
    failed = [item for item in report.get("failedChecks", []) if isinstance(item, str)]
    failed_labels = [{"key": key, "label": _check_label(key)} for key in failed]
    if gate == "topic-discovery":
        return {
            "title": "소재 검증",
            "statusLabel": "통과" if ready else "보완 필요",
            "primaryMessage": "소재 기준을 통과했습니다." if ready else "소재 기준에서 막힌 항목이 있습니다.",
            "nextAction": (
                "2단계 롱폼 제작 준비 검사를 실행하세요."
                if ready
                else "검색 계획, 실제 출처, 커뮤니티/트렌드 근거, 롱폼 유지력 항목을 먼저 보완하세요."
            ),
            "failedChecks": failed_labels,
            "checkSummaries": _check_summaries(report),
        }
    return {
        "title": "롱폼 준비 검증",
        "statusLabel": "통과" if ready else "보완 필요",
        "primaryMessage": "롱폼 사전 검사 기준을 통과했습니다." if ready else "롱폼 제작 준비에서 막힌 항목이 있습니다.",
        "nextAction": (
            "스토리보드와 소스 프롬프트 bible 생성 단계로 넘어가도 됩니다."
            if ready
            else "소재, 제작 순서, 롱폼 제작 조건, 렌더 전 점검 중 실패한 데이터를 먼저 채우세요."
        ),
        "failedChecks": failed_labels,
        "checkSummaries": _check_summaries(report),
    }


@gates_bp.route("/api/gates/topic-discovery/evaluate", methods=["POST"])
def topic_discovery_evaluate_route():
    packet = _packet_from_request(request.get_json(silent=True) or {})
    report = evaluate_topic_discovery_gate(packet)
    ready = report.get("topicReady") is True
    return jsonify(
        {
            "ok": True,
            "gate": "topic-discovery",
            "status": report.get("status"),
            "ready": ready,
            "failedChecks": report.get("failedChecks", []),
            "ux": _gate_ux("topic-discovery", ready=ready, report=report),
            "report": report,
        }
    )


@gates_bp.route("/api/gates/longform-dryrun/evaluate", methods=["POST"])
def longform_dryrun_evaluate_route():
    packet = _packet_from_request(request.get_json(silent=True) or {})
    report = evaluate_longform_dryrun_readiness(packet)
    ready = report.get("dryrunAllowed") is True
    return jsonify(
        {
            "ok": True,
            "gate": "longform-dryrun",
            "status": report.get("status"),
            "ready": ready,
            "finalReady": report.get("finalAllowed") is True,
            "failedChecks": report.get("failedChecks", []),
            "ux": _gate_ux("longform-dryrun", ready=ready, report=report),
            "report": report,
        }
    )
