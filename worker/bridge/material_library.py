from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import re


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATERIAL_LIBRARY_PATH = PROJECT_ROOT / "storage" / "topic-library" / "materials.json"
SCHEMA = "video-studio.topic-material-library.v1"
HANDOFF_SCHEMA = "video-studio.material-production-handoff.v1"
MATERIAL_EVALUATION_SCHEMA = "video-studio.material-evaluation-gate.v1"
MATERIAL_OUTCOME_SCHEMA = "video-studio.material-outcome.v1"


def _now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")


def _today_slug() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _numeric(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tokens(value: str) -> list[str]:
    return re.findall(r"[0-9A-Za-z가-힣]+", value.lower())


def _slug(value: str) -> str:
    slug = "-".join(_tokens(value))
    return slug[:64] or "material"


def _dedupe_key(title: str, central_question: str, search_seed: str) -> str:
    basis = " ".join(_tokens(f"{title} {central_question} {search_seed}"))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _is_worklist_source(entry: dict[str, Any]) -> bool:
    title = _text(entry.get("title")).lower()
    observation = _text(entry.get("observation")).lower()
    source_id = _text(entry.get("sourceId")).lower()
    return (
        "worklist" in title
        or "worklist" in observation
        or "operator observation can replace this note" in observation
        or source_id.endswith("-worklist")
    )


def _new_material_id(title: str, dedupe_key: str) -> str:
    return f"mat-{_today_slug()}-{_slug(title)}-{dedupe_key[:8]}"


def _empty_library() -> dict[str, Any]:
    return {"schema": SCHEMA, "materials": []}


def _library_path(path: Path | None = None) -> Path:
    return path or MATERIAL_LIBRARY_PATH


def load_material_library(path: Path | None = None) -> dict[str, Any]:
    target = _library_path(path)
    if not target.exists():
        return _empty_library()
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return _empty_library()
    materials = data.get("materials")
    if not isinstance(materials, list):
        data["materials"] = []
    return data


def save_material_library(library: dict[str, Any], path: Path | None = None) -> None:
    target = _library_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": SCHEMA, "materials": _as_list(library.get("materials"))}
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


def _selected_topic(topic_packet: dict[str, Any]) -> dict[str, Any]:
    candidates = [item for item in _as_list(topic_packet.get("topicCandidates")) if isinstance(item, dict)]
    selected_id = _text(_as_dict(topic_packet.get("selection")).get("selectedTopicId"))
    for candidate in candidates:
        if _text(candidate.get("topicId")) == selected_id:
            return candidate
    return candidates[0] if candidates else {}


def _merge_source_ledger(existing: list[Any], incoming: list[Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for raw_entry in [*existing, *incoming]:
        if not isinstance(raw_entry, dict):
            continue
        key = _text(raw_entry.get("sourceId")) or _text(raw_entry.get("url")) or hashlib.sha1(
            json.dumps(raw_entry, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        current = merged.get(key, {})
        merged[key] = {**current, **raw_entry}
    return list(merged.values())


def _merge_research_plan(existing: list[Any], incoming: list[Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for raw_entry in [*existing, *incoming]:
        if not isinstance(raw_entry, dict):
            continue
        key = "|".join([_text(raw_entry.get("provider")), _text(raw_entry.get("surface")), _text(raw_entry.get("query"))])
        merged[key or hashlib.sha1(json.dumps(raw_entry, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]] = raw_entry
    return list(merged.values())


def _quality_from_payload(candidate: dict[str, Any], topic_packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "latestScore": candidate.get("score", 0),
        "scoreBreakdown": _as_dict(candidate.get("scoreBreakdown")),
        "rankingReason": _text(candidate.get("rankingReason")),
        "nextPipelineAction": _text(candidate.get("nextPipelineAction")) or _text(topic_packet.get("operatorTodo")),
        "rankedBy": _as_list(candidate.get("rankedBy")),
    }


def _gate_event_from_topic_result(topic_gate_result: dict[str, Any]) -> dict[str, Any] | None:
    if not topic_gate_result:
        return None
    ready = topic_gate_result.get("ready") is True or _as_dict(topic_gate_result.get("report")).get("topicReady") is True
    status = "pass" if ready else "blocked"
    return {
        "stage": "topic-discovery",
        "status": status,
        "capturedAt": _now_iso(),
        "failedChecks": _as_list(topic_gate_result.get("failedChecks")),
        "evidenceRef": "dashboard-topic-gate",
    }


def _duplicate_candidates(materials: list[Any], dedupe_key: str, title: str, central_question: str) -> list[dict[str, Any]]:
    basis_tokens = set(_tokens(f"{title} {central_question}"))
    matches: list[dict[str, Any]] = []
    for material in materials:
        if not isinstance(material, dict):
            continue
        reason = ""
        score = 0.0
        if material.get("dedupeKey") == dedupe_key:
            reason = "exact-dedupe-key"
            score = 1.0
        else:
            other_tokens = set(_tokens(f"{material.get('title', '')} {material.get('centralQuestion', '')}"))
            if basis_tokens and other_tokens:
                score = len(basis_tokens & other_tokens) / max(1, len(basis_tokens | other_tokens))
                if score >= 0.55:
                    reason = "token-overlap"
        if reason:
            matches.append(
                {
                    "materialId": material.get("materialId"),
                    "title": material.get("title"),
                    "status": material.get("status", "unused"),
                    "reason": reason,
                    "similarity": round(score, 3),
                }
            )
    return sorted(matches, key=lambda item: item["similarity"], reverse=True)[:5]


def _build_material(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = _as_dict(payload.get("candidate"))
    topic_packet = _as_dict(payload.get("topicPacket") or payload.get("topicDiscoveryPacket"))
    selected_topic = _selected_topic(topic_packet)
    title = _text(candidate.get("title")) or _text(selected_topic.get("workingTitle")) or _text(payload.get("title"))
    central_question = (
        _text(candidate.get("centralQuestion"))
        or _text(selected_topic.get("centralQuestion"))
        or _text(payload.get("centralQuestion"))
    )
    search_seed = _text(candidate.get("searchSeed")) or _text(topic_packet.get("discoverySeed")) or title
    dedupe_key = _dedupe_key(title, central_question, search_seed)
    source_ledger = _as_list(payload.get("sourceLedger")) or _as_list(topic_packet.get("sourceLedger"))
    research_query_plan = _as_list(payload.get("researchQueryPlan")) or _as_list(topic_packet.get("researchQueryPlan"))
    now = _now_iso()
    material = {
        "materialId": _new_material_id(title, dedupe_key),
        "dedupeKey": dedupe_key,
        "title": title,
        "centralQuestion": central_question,
        "searchSeed": search_seed,
        "status": "unused",
        "formatFit": ["shortform", "longform"],
        "createdAt": now,
        "updatedAt": now,
        "lastUsedAt": None,
        "sourceLedger": _merge_source_ledger([], source_ledger),
        "researchQueryPlan": _merge_research_plan([], research_query_plan),
        "topicCandidates": _as_list(topic_packet.get("topicCandidates")),
        "selection": _as_dict(topic_packet.get("selection")),
        "quality": _quality_from_payload(candidate, topic_packet),
        "gateHistory": [
            {
                "stage": "material-intake",
                "status": "pass" if title and central_question and search_seed else "blocked",
                "capturedAt": now,
                "failedChecks": [] if title and central_question and search_seed else ["title", "centralQuestion", "searchSeed"],
            }
        ],
        "qualityNotes": [],
    }
    gate_event = _gate_event_from_topic_result(_as_dict(payload.get("topicGateResult") or payload.get("gateResult")))
    if gate_event:
        material["gateHistory"].append(gate_event)
    return material


def intake_material(payload: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    library = load_material_library(path)
    materials = _as_list(library.get("materials"))
    material = _build_material(_as_dict(payload))
    duplicates = _duplicate_candidates(materials, material["dedupeKey"], material["title"], material["centralQuestion"])
    existing = next((item for item in materials if isinstance(item, dict) and item.get("dedupeKey") == material["dedupeKey"]), None)
    if existing:
        existing["updatedAt"] = _now_iso()
        existing["sourceLedger"] = _merge_source_ledger(_as_list(existing.get("sourceLedger")), material["sourceLedger"])
        existing["researchQueryPlan"] = _merge_research_plan(_as_list(existing.get("researchQueryPlan")), material["researchQueryPlan"])
        existing["topicCandidates"] = material["topicCandidates"] or existing.get("topicCandidates", [])
        existing["selection"] = material["selection"] or existing.get("selection", {})
        existing["quality"] = {**_as_dict(existing.get("quality")), **_as_dict(material.get("quality"))}
        existing["gateHistory"] = [*_as_list(existing.get("gateHistory")), *material["gateHistory"]]
        target_material = existing
        created = False
    else:
        materials.append(material)
        target_material = material
        created = True
    library["materials"] = materials
    save_material_library(library, path)
    return {
        "schema": SCHEMA,
        "created": created,
        "material": target_material,
        "duplicateCandidates": duplicates,
        "stats": library_stats(materials),
    }


def append_gate_event(material_id: str, event: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    library = load_material_library(path)
    materials = _as_list(library.get("materials"))
    target = next((item for item in materials if isinstance(item, dict) and item.get("materialId") == material_id), None)
    if not target:
        raise KeyError(material_id)
    captured_at = _text(event.get("capturedAt")) or _now_iso()
    gate_event = {
        "stage": _text(event.get("stage")),
        "status": _text(event.get("status")) or "pending",
        "capturedAt": captured_at,
        "failedChecks": _as_list(event.get("failedChecks")),
        "evidenceRef": _text(event.get("evidenceRef")),
    }
    target["gateHistory"] = [*_as_list(target.get("gateHistory")), gate_event]
    target["updatedAt"] = captured_at
    save_material_library(library, path)
    return target


def append_material_outcome(material_id: str, outcome: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    library = load_material_library(path)
    materials = _as_list(library.get("materials"))
    target = next((item for item in materials if isinstance(item, dict) and item.get("materialId") == material_id), None)
    if not target:
        raise KeyError(material_id)
    captured_at = _text(outcome.get("capturedAt")) or _now_iso()
    status = _text(outcome.get("status") or outcome.get("outcomeStatus") or "review")
    normalized = {
        "schema": MATERIAL_OUTCOME_SCHEMA,
        "stage": _text(outcome.get("stage") or "post-production"),
        "status": status,
        "capturedAt": captured_at,
        "artifactRef": _text(outcome.get("artifactRef") or outcome.get("artifactPath")),
        "platform": _text(outcome.get("platform")),
        "qualityScore": _numeric(outcome.get("qualityScore")),
        "watchRetentionPct": _numeric(outcome.get("watchRetentionPct")),
        "reuseRecommended": outcome.get("reuseRecommended") is True,
        "learningNotes": _text(outcome.get("learningNotes") or outcome.get("note")),
        "failureReasons": [_text(item) for item in _as_list(outcome.get("failureReasons")) if _text(item)],
        "successSignals": [_text(item) for item in _as_list(outcome.get("successSignals")) if _text(item)],
    }
    target["outcomeHistory"] = [*_as_list(target.get("outcomeHistory")), normalized]
    target["updatedAt"] = captured_at
    if normalized["stage"] in {"publish", "uploaded", "post-publish", "final"}:
        target["lastUsedAt"] = captured_at
    if normalized["reuseRecommended"]:
        target["status"] = "reusable"
    elif status.lower() in {"fail", "failed", "blocked", "rejected"}:
        target["status"] = "needs-rework"
    save_material_library(library, path)
    return target


def library_stats(materials: list[Any]) -> dict[str, Any]:
    valid = [item for item in materials if isinstance(item, dict)]
    evaluations = [evaluate_material_quality(item) for item in valid]
    learning = material_learning_summary(valid)
    return {
        "total": len(valid),
        "unused": sum(1 for item in valid if item.get("status", "unused") == "unused"),
        "reusable": sum(1 for item in valid if item.get("status") == "reusable"),
        "withSourceLedger": sum(1 for item in valid if _as_list(item.get("sourceLedger"))),
        "withObservedSourceReady": sum(
            1
            for evaluation in evaluations
            if _as_dict(evaluation.get("sourceCounts")).get("observed", 0) >= 5
        ),
        "withTopicPass": sum(
            1
            for item in valid
            if any(
                isinstance(event, dict)
                and event.get("stage") == "topic-discovery"
                and event.get("status") == "pass"
                for event in _as_list(item.get("gateHistory"))
            )
        ),
        "withOutcomes": sum(1 for item in valid if _as_list(item.get("outcomeHistory"))),
        "learning": learning,
    }


def material_learning_summary(materials: list[Any]) -> dict[str, Any]:
    valid = [item for item in materials if isinstance(item, dict)]
    outcomes = [
        outcome
        for material in valid
        for outcome in _as_list(material.get("outcomeHistory"))
        if isinstance(outcome, dict)
    ]
    successful = [
        item
        for item in outcomes
        if _text(item.get("status")).lower() in {"pass", "success", "published", "uploaded", "reusable"}
    ]
    failed = [
        item
        for item in outcomes
        if _text(item.get("status")).lower() in {"fail", "failed", "blocked", "rejected"}
    ]
    reusable = [
        item
        for item in valid
        if any(isinstance(outcome, dict) and outcome.get("reuseRecommended") is True for outcome in _as_list(item.get("outcomeHistory")))
    ]
    scores = [
        score
        for outcome in outcomes
        if (score := _numeric(outcome.get("qualityScore"))) is not None
    ]
    return {
        "materialCount": len(valid),
        "outcomeCount": len(outcomes),
        "successfulOutcomeCount": len(successful),
        "failedOutcomeCount": len(failed),
        "reuseRecommendedCount": len(reusable),
        "averageQualityScore": round(sum(scores) / len(scores), 2) if scores else None,
        "topReusableMaterialIds": [item.get("materialId") for item in reusable[:5]],
        "needsMoreSamples": len(outcomes) < 3,
    }


def material_summary(material: dict[str, Any]) -> dict[str, Any]:
    source_ledger = _as_list(material.get("sourceLedger"))
    gate_history = _as_list(material.get("gateHistory"))
    outcome_history = [item for item in _as_list(material.get("outcomeHistory")) if isinstance(item, dict)]
    evaluation = evaluate_material_quality(material)
    return {
        "materialId": material.get("materialId"),
        "title": material.get("title"),
        "status": material.get("status", "unused"),
        "sourceCount": len(source_ledger),
        "outcomeCount": len(outcome_history),
        "latestOutcome": outcome_history[-1] if outcome_history else None,
        "latestScore": _as_dict(material.get("quality")).get("latestScore", 0),
        "lastGate": gate_history[-1] if gate_history else None,
        "updatedAt": material.get("updatedAt"),
        "evaluation": {
            "score": evaluation["score"],
            "verdict": evaluation["verdict"],
            "blockedChecks": evaluation["blockedChecks"],
            "pendingChecks": evaluation["pendingChecks"],
            "sourceCounts": evaluation["sourceCounts"],
        },
        "learningSignals": _material_learning_signals(material),
    }


def _material_learning_signals(material: dict[str, Any]) -> dict[str, Any]:
    outcomes = [item for item in _as_list(material.get("outcomeHistory")) if isinstance(item, dict)]
    failures = [
        _text(reason)
        for outcome in outcomes
        for reason in _as_list(outcome.get("failureReasons"))
        if _text(reason)
    ]
    successes = [
        _text(signal)
        for outcome in outcomes
        for signal in _as_list(outcome.get("successSignals"))
        if _text(signal)
    ]
    return {
        "outcomeCount": len(outcomes),
        "reuseRecommended": any(outcome.get("reuseRecommended") is True for outcome in outcomes),
        "failureReasons": failures[-5:],
        "successSignals": successes[-5:],
    }


def _evaluation_check(key: str, label: str, status: str, detail: str, next_action: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
        "nextAction": next_action if status != "pass" else "다음 소재 게이트로 진행하세요.",
    }


def evaluate_material_quality(material: dict[str, Any]) -> dict[str, Any]:
    material = _as_dict(material)
    source_refs = _source_refs(material)
    usable_source_refs = [
        ref
        for ref in source_refs
        if _text(ref.get("url")) and _text(ref.get("observation"))
    ]
    observed_source_refs = [
        ref
        for ref in usable_source_refs
        if not _is_worklist_source(ref)
    ]
    research_surfaces = set(_research_surfaces(material))
    selected_topic = _selected_material_topic(material)
    quality = _as_dict(material.get("quality"))
    gate_history = _as_list(material.get("gateHistory"))
    has_topic_pass = any(
        isinstance(event, dict)
        and event.get("stage") == "topic-discovery"
        and event.get("status") == "pass"
        for event in gate_history
    )
    basic_ready = all(_text(material.get(key)) for key in ["title", "centralQuestion", "searchSeed"])
    source_ready = len(usable_source_refs) >= 5
    observed_source_ready = len(observed_source_refs) >= 5
    surface_ready = {"search", "trend", "video", "community"}.issubset(research_surfaces) or len(research_surfaces) >= 4
    topic_ready = bool(selected_topic)
    score_ready = int(quality.get("latestScore") or 0) >= 70

    checks = [
        _evaluation_check(
            "basicFields",
            "기본 소재 필드",
            "pass" if basic_ready else "blocked",
            "제목, 중심 질문, 검색 seed가 있습니다." if basic_ready else "제목, 중심 질문, 검색 seed 중 비어 있는 값이 있습니다.",
            "소재 제목, 중심 질문, 검색 seed를 먼저 채우세요.",
        ),
        _evaluation_check(
            "sourceLedgerDepth",
            "출처 깊이",
            "pass" if source_ready else "blocked",
            f"usable sourceLedger {len(usable_source_refs)}개입니다.",
            "실제 URL과 관찰 메모가 있는 sourceLedger를 5개 이상 채우세요.",
        ),
        _evaluation_check(
            "observedSourceDepth",
            "실제 관찰 출처",
            "pass" if observed_source_ready else "pending",
            f"worklist가 아닌 관찰 출처 {len(observed_source_refs)}개입니다.",
            "검색 worklist URL이 아니라 실제로 확인한 관찰/제품/문서/커뮤니티 출처를 5개 이상 채우세요.",
        ),
        _evaluation_check(
            "researchSurfaceDiversity",
            "조사 표면 다양성",
            "pass" if surface_ready else "blocked",
            f"조사 표면: {sorted(research_surfaces)}",
            "검색, 트렌드, 영상, 커뮤니티 표면을 모두 포함하세요.",
        ),
        _evaluation_check(
            "selectedTopic",
            "선택 소재 구조",
            "pass" if topic_ready else "blocked",
            "선택된 topic candidate가 있습니다." if topic_ready else "선택된 topic candidate가 없습니다.",
            "후보 소재를 만들고 선택/탈락 이유를 저장하세요.",
        ),
        _evaluation_check(
            "candidateScore",
            "후보 점수 근거",
            "pass" if score_ready else "pending",
            f"latestScore {quality.get('latestScore', 0)}입니다.",
            "freshness, source evidence, surface coverage, longform fit 근거를 채우세요.",
        ),
        _evaluation_check(
            "topicGatePass",
            "소재 검증 게이트",
            "pass" if has_topic_pass else "pending",
            "topic-discovery pass 이력이 있습니다." if has_topic_pass else "topic-discovery pass 이력이 아직 없습니다.",
            "소재 게이트를 실행하고 실패 항목을 해결하세요.",
        ),
    ]
    weights = {
        "basicFields": 15,
        "sourceLedgerDepth": 20,
        "observedSourceDepth": 15,
        "researchSurfaceDiversity": 15,
        "selectedTopic": 15,
        "candidateScore": 10,
        "topicGatePass": 10,
    }
    score = sum(weights[check["key"]] for check in checks if check["status"] == "pass")
    blocked = [check["key"] for check in checks if check["status"] == "blocked"]
    pending = [check["key"] for check in checks if check["status"] == "pending"]
    if blocked:
        verdict = "blocked"
    elif pending or score < 85:
        verdict = "review"
    else:
        verdict = "pass"
    return {
        "schema": MATERIAL_EVALUATION_SCHEMA,
        "materialId": material.get("materialId"),
        "title": material.get("title"),
        "score": score,
        "verdict": verdict,
        "blockedChecks": blocked,
        "pendingChecks": pending,
        "sourceCounts": {
            "total": len(source_refs),
            "usable": len(usable_source_refs),
            "observed": len(observed_source_refs),
            "worklist": len(usable_source_refs) - len(observed_source_refs),
        },
        "checks": checks,
        "nextAction": next(
            (check["nextAction"] for check in checks if check["status"] != "pass"),
            "스토리보드와 소스 프롬프트 bible로 넘기세요.",
        ),
    }


def _selected_material_topic(material: dict[str, Any]) -> dict[str, Any]:
    selected_id = _text(_as_dict(material.get("selection")).get("selectedTopicId"))
    candidates = [item for item in _as_list(material.get("topicCandidates")) if isinstance(item, dict)]
    for candidate in candidates:
        if _text(candidate.get("topicId")) == selected_id:
            return candidate
    return candidates[0] if candidates else {}


def _chapter_prompts(material: dict[str, Any], selected_topic: dict[str, Any]) -> list[dict[str, Any]]:
    longform_plan = _as_dict(selected_topic.get("longformPlan"))
    chapter_promises = [
        item for item in _as_list(longform_plan.get("chapterPromises")) if isinstance(item, dict)
    ]
    if not chapter_promises:
        title = _text(material.get("title")) or "선택 소재"
        central_question = _text(material.get("centralQuestion")) or "시청자가 끝까지 볼 질문"
        return [
            {"chapterId": "chapter-01", "promise": f"{title}을 지금 봐야 하는 이유를 연다."},
            {"chapterId": "chapter-02", "promise": f"{central_question}에 필요한 핵심 배경을 정리한다."},
            {"chapterId": "chapter-03", "promise": "출처별로 확인된 사실과 아직 비어 있는 주장을 분리한다."},
            {"chapterId": "chapter-04", "promise": "댓글/커뮤니티 반응에서 갈리는 지점을 비교한다."},
            {"chapterId": "chapter-05", "promise": "영상화할 수 있는 장면 단위 증거를 정리한다."},
            {"chapterId": "chapter-06", "promise": "시청자가 가져갈 결론과 다음 확인 질문을 닫는다."},
        ]
    return [
        {
            "chapterId": _text(item.get("chapterId")) or f"chapter-{index + 1:02d}",
            "promise": _text(item.get("promise")) or "챕터 약속을 구체화하세요.",
        }
        for index, item in enumerate(chapter_promises)
    ]


def _source_refs(material: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, entry in enumerate(_as_list(material.get("sourceLedger")), start=1):
        if not isinstance(entry, dict):
            continue
        refs.append(
            {
                "sourceId": _text(entry.get("sourceId")) or f"source-{index:02d}",
                "title": _text(entry.get("title")) or _text(entry.get("url")) or "source",
                "sourceType": _text(entry.get("sourceType")) or "unknown",
                "url": _text(entry.get("url")),
                "observation": _text(entry.get("observation")),
            }
        )
    return refs


def _research_surfaces(material: dict[str, Any]) -> list[str]:
    surfaces: list[str] = []
    for entry in _as_list(material.get("researchQueryPlan")):
        if isinstance(entry, dict):
            surface = _text(entry.get("surface")) or _text(entry.get("provider"))
            if surface and surface not in surfaces:
                surfaces.append(surface)
    return surfaces


def _prompt_memo(material: dict[str, Any], source_refs: list[dict[str, Any]], chapter_prompts: list[dict[str, Any]]) -> str:
    title = _text(material.get("title")) or "선택 소재"
    central_question = _text(material.get("centralQuestion")) or "핵심 질문 미정"
    search_seed = _text(material.get("searchSeed")) or title
    source_lines = "\n".join(
        f"- {ref['sourceId']}: {ref['title']} ({ref['sourceType']})"
        for ref in source_refs[:6]
    ) or "- sourceLedger가 비어 있습니다. 실제 URL과 관찰 메모를 먼저 채우세요."
    chapter_lines = "\n".join(
        f"- {item['chapterId']}: {item['promise']}"
        for item in chapter_prompts[:8]
    )
    return (
        f"소재: {title}\n"
        f"핵심 질문: {central_question}\n"
        f"검색 시드: {search_seed}\n\n"
        "영상 목표:\n"
        "- 첫 30초 안에 질문, 현재성, 볼 이유를 먼저 보여준다.\n"
        "- 모든 강한 주장은 sourceLedger 출처와 연결한다.\n"
        "- 단일 글 복붙이 아니라 배경, 반론, 확인 기준을 재구성한다.\n\n"
        f"출처 메모:\n{source_lines}\n\n"
        f"챕터 초안:\n{chapter_lines}\n\n"
        "다음 작업:\n"
        "1. 빈 출처와 관찰 메모를 채운다.\n"
        "2. 스토리보드에서 챕터 약속을 장면 단위로 쪼갠다.\n"
        "3. 소스 프롬프트 bible에서 동일 인물/장소/톤 연속성을 고정한다."
    )


def build_material_production_handoff(material: dict[str, Any]) -> dict[str, Any]:
    selected_topic = _selected_material_topic(material)
    source_refs = _source_refs(material)
    chapter_prompts = _chapter_prompts(material, selected_topic)
    surfaces = _research_surfaces(material)
    missing: list[str] = []
    if not source_refs:
        missing.append("sourceLedger")
    if not surfaces:
        missing.append("researchQueryPlan")
    if not _text(material.get("centralQuestion")):
        missing.append("centralQuestion")
    return {
        "schema": HANDOFF_SCHEMA,
        "materialId": material.get("materialId"),
        "title": material.get("title"),
        "centralQuestion": material.get("centralQuestion"),
        "searchSeed": material.get("searchSeed"),
        "promptMemo": _prompt_memo(material, source_refs, chapter_prompts),
        "storyboardSeed": {
            "title": material.get("title"),
            "centralQuestion": material.get("centralQuestion"),
            "openingPromise": _text(_as_dict(selected_topic.get("longformPlan")).get("first30SecPromise"))
            or "핵심 질문과 볼 이유를 첫 30초 안에 제시한다.",
            "chapterPrompts": chapter_prompts,
            "sourceLedgerRefs": [ref["sourceId"] for ref in source_refs],
            "requiredNextPackets": ["storyboardPacket", "sourcePromptBible", "renderPreflightPacket"],
        },
        "sourcePromptBibleSeed": {
            "formatProfile": "longform_10m",
            "visualContinuity": "같은 소재의 인물, 장소, 시간대, 색감, 카메라 톤을 장면마다 고정한다.",
            "researchSurfaces": surfaces,
            "sourceLedgerRefs": source_refs,
            "promptRules": [
                "출처가 없는 장면은 설명용 B-roll로만 쓰고 사실 주장처럼 연출하지 않는다.",
                "첫 장면은 제목/썸네일의 질문을 즉시 보여준다.",
                "중반에는 반론 또는 오해를 장면 전환 기준으로 사용한다.",
            ],
        },
        "nextDashboardAction": {
            "tab": "plan",
            "label": "기획 초안 만들기",
            "blockedUntil": missing,
        },
    }
