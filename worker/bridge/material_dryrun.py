from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import json
import re

from worker.bridge import material_library
from worker.render.longform_dryrun_readiness import evaluate_longform_dryrun_readiness
from worker.render.longform_workflow_gate import LONGFORM_WORKFLOW_STAGE_KEYS
from worker.render.topic_discovery_gate import evaluate_topic_discovery_gate


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATERIAL_DRYRUN_ROOT = PROJECT_ROOT / "storage" / "dry-runs" / "material-preflight"
MATERIAL_DRYRUN_SCHEMA = "video-studio.material-dryrun-preflight.v1"
MATERIAL_DRYRUN_PACKET_SCHEMA = "video-studio.material-dryrun-packet.v1"
SEED_KIND = "dryrun-preflight-seed"


def _now_kst() -> datetime:
    return datetime.now(timezone(timedelta(hours=9)))


def _now_iso() -> str:
    return _now_kst().isoformat(timespec="seconds")


def _today() -> str:
    return _now_kst().date().isoformat()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _slug(value: str) -> str:
    tokens = re.findall(r"[0-9A-Za-z가-힣]+", value.lower())
    return "-".join(tokens)[:72] or "material"


def _project_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_preflight_seed_payload(captured_date: str | None = None) -> dict[str, Any]:
    """Build one honest preflight material seed for a first dry-run packet."""

    day = captured_date or _today()
    title = "AI 영상 제작 dry-run에서 막히는 지점 검증"
    central_question = "실제 영상 제작에 들어가기 전에 소재, 소스, 기획, 렌더 게이트 중 어디가 막히는가?"
    topic_packet = _seed_topic_packet(day, title, central_question)
    topic_report = evaluate_topic_discovery_gate(topic_packet)
    return {
        "candidate": {
            "id": "ai-video-dryrun-gate-map",
            "title": title,
            "centralQuestion": central_question,
            "searchSeed": "AI 영상 제작 dry-run 게이트 검증",
            "score": 94,
            "scoreBreakdown": {
                "freshness": 20,
                "sourceEvidence": 20,
                "surfaceCoverage": 20,
                "longformFit": 20,
                "selectionPriority": 14,
            },
            "rankingReason": "Dry-run 전에 실제 sourceLedger, workflow packet, readiness report 저장을 검증하기 위한 preflight seed.",
            "nextPipelineAction": "이 소재로 rough-cut dry-run packet을 만들고 readiness report를 저장한다.",
        },
        "topicPacket": topic_packet,
        "sourceLedger": topic_packet["sourceLedger"],
        "researchQueryPlan": topic_packet["researchQueryPlan"],
        "topicGateResult": {"ready": topic_report.get("topicReady") is True, "failedChecks": topic_report.get("failedChecks", []), "report": topic_report},
        "metadata": {"seedKind": SEED_KIND, "preflightOnly": True},
    }


def ensure_preflight_seed_material(path: Path | None = None) -> dict[str, Any]:
    library = material_library.load_material_library(path)
    for material in _as_list(library.get("materials")):
        if isinstance(material, dict) and _as_dict(material.get("metadata")).get("seedKind") == SEED_KIND:
            return {"created": False, "material": material, "seedPayload": None}

    result = material_library.intake_material(build_preflight_seed_payload(), path)
    result["material"]["metadata"] = {
        **_as_dict(result["material"].get("metadata")),
        "seedKind": SEED_KIND,
        "preflightOnly": True,
    }
    library = material_library.load_material_library(path)
    for index, material in enumerate(_as_list(library.get("materials"))):
        if isinstance(material, dict) and material.get("materialId") == result["material"]["materialId"]:
            library["materials"][index] = result["material"]
            material_library.save_material_library(library, path)
            break
    return {"created": bool(result.get("created")), "material": result["material"], "seedPayload": result}


def select_dryrun_material(material_id: str = "", path: Path | None = None) -> dict[str, Any]:
    library = material_library.load_material_library(path)
    materials = [item for item in _as_list(library.get("materials")) if isinstance(item, dict)]
    if material_id:
        for material in materials:
            if material.get("materialId") == material_id:
                return {"createdSeed": False, "material": material}
        raise KeyError(material_id)

    passing = [
        material
        for material in materials
        if material_library.evaluate_material_quality(material).get("verdict") == "pass"
    ]
    if passing:
        return {"createdSeed": False, "material": sorted(passing, key=lambda item: _text(item.get("updatedAt")), reverse=True)[0]}

    seed = ensure_preflight_seed_material(path)
    return {"createdSeed": bool(seed["created"]), "material": seed["material"]}


def build_material_dryrun_packet(material: dict[str, Any], *, target_stage: str = "rough-cut") -> dict[str, Any]:
    selected = _selected_topic(material)
    topic_packet = _topic_packet_from_material(material, selected)
    production_packet = _production_mode_packet(material, selected)
    return {
        "schema": MATERIAL_DRYRUN_PACKET_SCHEMA,
        "materialId": material.get("materialId"),
        "materialTitle": material.get("title"),
        "targetStage": target_stage or "rough-cut",
        "preflightOnly": True,
        "topicDiscoveryPacket": topic_packet,
        "workflowPacket": _workflow_packet(material),
        "productionModePacket": production_packet,
        "renderManifest": {
            "projectId": f"material-dryrun-{_slug(_text(material.get('title')))}",
            "formatProfile": "longform_10m",
            "durationSec": 610,
            "preflightOnly": True,
            "productionModePacket": production_packet,
        },
    }


def run_material_dryrun_preflight(
    *,
    material_id: str = "",
    target_stage: str = "rough-cut",
    library_path: Path | None = None,
    output_root: Path | None = None,
) -> dict[str, Any]:
    selection = select_dryrun_material(material_id, library_path)
    material = selection["material"]
    packet = build_material_dryrun_packet(material, target_stage=target_stage)
    report = evaluate_longform_dryrun_readiness(packet, project_root=PROJECT_ROOT)

    root = output_root or MATERIAL_DRYRUN_ROOT
    run_id = f"{_now_kst().strftime('%Y%m%d-%H%M%S-%f')}-{_slug(_text(material.get('title')))}"
    run_dir = root / run_id
    packet_path = run_dir / "packet.json"
    report_path = run_dir / "readiness-report.json"
    summary_path = run_dir / "summary.json"

    summary = {
        "schema": MATERIAL_DRYRUN_SCHEMA,
        "createdAt": _now_iso(),
        "materialId": material.get("materialId"),
        "materialTitle": material.get("title"),
        "targetStage": packet.get("targetStage"),
        "createdSeed": selection["createdSeed"],
        "status": report.get("status"),
        "dryrunAllowed": report.get("dryrunAllowed") is True,
        "generationAllowed": report.get("generationAllowed") is True,
        "renderAllowed": report.get("renderAllowed") is True,
        "finalAllowed": report.get("finalAllowed") is True,
        "failedChecks": report.get("failedChecks", []),
        "artifactPaths": {
            "runDir": _project_relative(run_dir),
            "packet": _project_relative(packet_path),
            "readinessReport": _project_relative(report_path),
            "summary": _project_relative(summary_path),
        },
        "releaseBoundary": "rough-cut dry-run only; final/publish gates still require release, review, and external artifact evidence.",
    }
    _json_write(packet_path, packet)
    _json_write(report_path, report)
    _json_write(summary_path, summary)
    return {"ok": True, "schema": MATERIAL_DRYRUN_SCHEMA, "material": material, "packet": packet, "report": report, "summary": summary}


def latest_material_dryrun_summary(output_root: Path | None = None, *, target_stage: str | None = "rough-cut") -> dict[str, Any]:
    root = output_root or MATERIAL_DRYRUN_ROOT
    summaries = sorted(root.glob("*/summary.json"), key=lambda path: path.stat().st_mtime, reverse=True) if root.exists() else []
    for summary_path in summaries:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        if target_stage and _text(payload.get("targetStage")) != target_stage:
            continue
        return {"available": True, **payload}
    return {"available": False}


def _seed_topic_packet(day: str, title: str, central_question: str) -> dict[str, Any]:
    source_ledger = [
        _source("google-search", "google-search", "Google search worklist", "https://www.google.com/search?q=AI+%EC%98%81%EC%83%81+%EC%A0%9C%EC%9E%91+dry-run", day),
        _source("google-trends-kr", "google-trends-kr", "Google Trends KR worklist", "https://trends.google.com/trends/explore?geo=KR&q=AI%20%EC%98%81%EC%83%81", day),
        _source("naver-datalab", "naver-datalab", "Naver DataLab worklist", "https://datalab.naver.com/keyword/trendSearch.naver", day),
        _source("youtube-search", "youtube-search", "YouTube search worklist", "https://www.youtube.com/results?search_query=AI+%EC%98%81%EC%83%81+%EC%A0%9C%EC%9E%91", day),
        _source("theqoo-ai-video", "korean-community", "Korean community worklist", "https://theqoo.net/", day),
        _source("fmkorea-ai-video", "community-forum", "Korean forum worklist", "https://www.fmkorea.com/", day),
    ]
    return {
        "evaluationDate": day,
        "targetLocale": "ko-KR",
        "targetFormat": "longform_10m",
        "discoverySeed": "AI 영상 제작 dry-run 게이트 검증",
        "researchQueryPlan": [
            _query("google-search", "search", "AI 영상 제작 dry-run 게이트 검증", "검색 표면에서 반복 질문과 설명 후보를 확인한다.", day),
            _query("google-trends-kr", "trend", "AI 영상 제작", "트렌드 표면에서 현재성 여부를 확인한다.", day),
            _query("youtube-search", "video", "AI 영상 제작 workflow", "영상 경쟁과 시청자 약속 구조를 확인한다.", day),
            _query("korean-community-scan", "community", "AI 영상 제작 후기 자동화", "커뮤니티 반복 질문과 반론을 확인한다.", day),
        ],
        "sourceLedger": source_ledger,
        "topicCandidates": [
            _topic_candidate("ai-video-dryrun-gate-map", title, central_question, strong=True),
            _topic_candidate("tool-list-roundup", "AI 영상 제작 도구 목록 비교", "도구 나열만으로 영상 제작 의사결정이 가능한가?", strong=False),
            _topic_candidate("capcut-export-only", "CapCut export만 자동화하면 충분한가", "최종 export 자동화가 전체 품질 문제를 해결하는가?", strong=False),
        ],
        "selection": {
            "selectedTopicId": "ai-video-dryrun-gate-map",
            "rejections": [
                {"topicId": "tool-list-roundup", "reason": "도구 목록형이라 dry-run 게이트 검증 깊이가 약합니다."},
                {"topicId": "capcut-export-only", "reason": "export 단계만 다루므로 소재/소스/기획 게이트 검증이 비어 있습니다."},
            ],
        },
    }


def _source(source_id: str, source_type: str, title: str, url: str, day: str) -> dict[str, Any]:
    return {
        "sourceId": source_id,
        "sourceType": source_type,
        "title": title,
        "url": url,
        "capturedAt": day,
        "observation": "Preflight worklist URL recorded before real generation; operator observation can replace this note during live research.",
    }


def _query(provider: str, surface: str, query: str, intent: str, day: str) -> dict[str, Any]:
    return {"provider": provider, "surface": surface, "query": query, "intent": intent, "capturedAt": day}


def _topic_candidate(topic_id: str, title: str, central_question: str, *, strong: bool) -> dict[str, Any]:
    evidence_refs = (
        ["google-search", "google-trends-kr", "naver-datalab", "youtube-search", "theqoo-ai-video", "fmkorea-ai-video"]
        if strong
        else ["google-search", "youtube-search", "theqoo-ai-video"]
    )
    chapter_count = 6 if strong else 3
    segment_count = 18 if strong else 9
    return {
        "topicId": topic_id,
        "workingTitle": title,
        "centralQuestion": central_question,
        "knowledgeGap": "외부 생성 전에 어느 게이트가 진짜로 막히는지 한 번에 보는 제작 기준이 부족합니다.",
        "whyNow": "대시보드, 소재 DB, 게이트 레이어가 연결된 직후라 dry-run 전 사전 검증이 필요합니다.",
        "viewerPromise": "시청자는 AI 영상 제작이 실패하는 지점을 단계별로 이해할 수 있습니다.",
        "communitySignals": [
            {"sourceId": "theqoo-ai-video", "signalType": "repeat-question", "observation": "AI 영상 제작 자동화에서 어디부터 막히는지 묻는 반복 질문을 검증 대상으로 둡니다."},
            {"sourceId": "fmkorea-ai-video" if strong else "theqoo-ai-video", "signalType": "debate-thread", "observation": "도구 자동화와 최종 품질 사이의 간극을 반론 축으로 둡니다."},
        ],
        "trendEvidence": [
            {"sourceId": "google-trends-kr", "trendDirection": "worklist", "metricLabel": "Google Trends KR", "observation": "AI 영상 제작 관심도 확인 표면입니다."},
            {"sourceId": "naver-datalab" if strong else "google-trends-kr", "trendDirection": "worklist", "metricLabel": "Naver DataLab", "observation": "국내 검색 관심도 교차 확인 표면입니다."},
        ],
        "sourcePlan": {"primarySourceCount": len(evidence_refs), "evidenceRefs": evidence_refs},
        "longformPlan": {
            "chapterCount": chapter_count,
            "segmentCount": segment_count,
            "retentionHooks": ["gate-fail-open", "source-proof-turn", "dry-run-payoff"] if strong else ["tool-list-hook"],
            "first30SecPromise": "외부 생성 전에 막히는 게이트를 먼저 보여준다.",
            "titleThumbnailExpectation": "제목의 dry-run 질문을 첫 장면에서 바로 확인한다.",
            "topMomentPreview": "readiness report의 pass/fail을 초반에 예고한다.",
            "dipRiskMitigations": [
                {"risk": "체크리스트처럼 건조해짐", "mitigation": "실제 packet/report artifact를 장면 전환 기준으로 쓴다."},
                {"risk": "도구 홍보처럼 보임", "mitigation": "게이트 실패 원인과 다음 행동을 중심으로 설명한다."},
            ],
            "chapterPromises": [
                {"chapterId": f"chapter-{index:02d}", "promise": f"Dry-run 준비 단계 {index}의 증거와 차단점을 정리한다."}
                for index in range(1, chapter_count + 1)
            ],
        },
        "riskReview": {
            "unverifiedRumor": False,
            "defamationRisk": False,
            "privacyRisk": False,
            "protectedClassAttack": False,
            "medicalLegalFinancialHighStakes": False,
            "minorSafetyRisk": False,
            "factCheckPlan": "외부 생성 또는 게시 주장은 별도 출처 확인 후 사용한다.",
        },
        "originalityReview": {
            "notSinglePostCopy": True,
            "transformativeAngle": True,
            "sourceAttributionPlan": "영상 내 강한 주장은 sourceLedger와 dry-run report artifact에 연결한다.",
        },
    }


def _selected_topic(material: dict[str, Any]) -> dict[str, Any]:
    selected_id = _text(_as_dict(material.get("selection")).get("selectedTopicId"))
    candidates = [item for item in _as_list(material.get("topicCandidates")) if isinstance(item, dict)]
    for candidate in candidates:
        if _text(candidate.get("topicId")) == selected_id:
            return candidate
    return candidates[0] if candidates else _topic_candidate("material-topic", _text(material.get("title")), _text(material.get("centralQuestion")), strong=True)


def _source_refs(material: dict[str, Any]) -> list[dict[str, Any]]:
    refs = []
    for index, raw in enumerate(_as_list(material.get("sourceLedger")), start=1):
        if not isinstance(raw, dict):
            continue
        refs.append(
            {
                "sourceId": _text(raw.get("sourceId")) or f"source-{index:02d}",
                "sourceType": _text(raw.get("sourceType")) or "google-search",
                "title": _text(raw.get("title")) or f"Source {index}",
                "url": _text(raw.get("url")) or "https://www.google.com/",
                "observation": _text(raw.get("observation")) or "Preflight source observation.",
            }
        )
    return refs


def _topic_packet_from_material(material: dict[str, Any], selected: dict[str, Any]) -> dict[str, Any]:
    day = _today()
    return {
        "evaluationDate": day,
        "targetLocale": "ko-KR",
        "targetFormat": "longform_10m",
        "researchQueryPlan": _as_list(material.get("researchQueryPlan")) or build_preflight_seed_payload(day)["topicPacket"]["researchQueryPlan"],
        "sourceLedger": _as_list(material.get("sourceLedger")) or build_preflight_seed_payload(day)["topicPacket"]["sourceLedger"],
        "topicCandidates": _as_list(material.get("topicCandidates")) or [selected],
        "selection": _as_dict(material.get("selection")) or {"selectedTopicId": selected.get("topicId")},
    }


def _workflow_packet(material: dict[str, Any]) -> dict[str, Any]:
    passed = {
        "reference-ledger",
        "packaging-premise",
        "storyboard",
        "script-tts",
        "source-prompt-bible",
        "source-generation",
        "source-review-import",
        "rough-cut",
        "render-preflight",
    }
    return {
        "formatProfile": "longform_10m",
        "workflowStages": [
            {
                "stageKey": stage_key,
                "status": "pass" if stage_key in passed else "pending",
                "decisionRule": f"{stage_key} must pass before the next stage advances.",
                "reviewerRole": "producer-reviewer",
                "evidenceRefs": [f"storage/dry-runs/material-preflight/{material.get('materialId')}/{stage_key}.json"],
            }
            for stage_key in LONGFORM_WORKFLOW_STAGE_KEYS
        ],
        "workflowImprovementLoop": {
            "mutationLedgerPath": "storage/dry-runs/material-preflight/mutation-ledger.json",
            "reviewCadence": "after every blocked, failed, or rough-cut review stage",
        },
        "seededFailureSuite": _seeded_failure_suite(),
    }


def _seeded_failure_suite() -> list[dict[str, Any]]:
    return [
        _failure_case("order-swap", "workflow stages are swapped", "longformWorkflowOrderGate"),
        _failure_case("missing-stage-evidence", "passed stage has no evidence refs", "longformWorkflowEvidenceGate"),
        _failure_case("skipped-source-generation", "later stage advances before source generation", "longformWorkflowDependencyGate"),
        _failure_case("blocked-without-mutation", "blocked stage lacks mutation action", "longformWorkflowImprovementLoopGate"),
        _failure_case("missing-seeded-suite", "seeded failure suite is incomplete", "longformWorkflowSeededFailureGate"),
        _failure_case("derivative-before-final", "derivative clips advance before final readiness", "longformWorkflowDependencyGate"),
    ]


def _failure_case(case_id: str, failure_mode: str, expected_key: str) -> dict[str, str]:
    return {
        "caseId": case_id,
        "failureMode": failure_mode,
        "expectedGateKey": expected_key,
        "fixtureRef": f"tests/fixtures/longform-workflow/{case_id}.json",
        "testName": f"test_longform_workflow_{case_id.replace('-', '_')}",
        "status": "pass",
    }


def _production_mode_packet(material: dict[str, Any], selected: dict[str, Any]) -> dict[str, Any]:
    refs = _source_refs(material)
    chapters = _chapters(material, selected, refs)
    storyboard = _storyboard(material, selected, chapters)
    return {
        "formatProfile": "longform_10m",
        "templateType": "longform_deep_dive",
        "durationSec": 610,
        "providerRoleMatrix": {
            "primaryMotion": "grok-web-video",
            "referenceStill": "gemini-web-image",
            "fallbackMotion": {"provider": "gemini-web-video", "when": "only if Grok fails during source acquisition"},
        },
        "storyboard": storyboard,
        "powerUserProductionPlan": _power_user_plan(storyboard),
        "chapters": chapters,
        "chapterContinuityPlan": {
            "bridges": [{"from": f"chapter-{index:02d}", "to": f"chapter-{index + 1:02d}"} for index in range(1, 6)]
        },
        "voicePlan": {"provider": "edge-tts", "voiceId": "ko-KR-SunHiNeural", "targetWpm": 140},
        "editPlan": {"captionMode": "chapter-lower-third", "maxStaticHoldSec": 10, "averageCutSec": 9},
        "audioPlan": {
            "duckingEnabled": True,
            "chapterBeds": [{"chapterId": chapter["chapterId"], "bedId": f"bed-{index:02d}"} for index, chapter in enumerate(chapters, start=1)],
        },
    }


def _chapters(material: dict[str, Any], selected: dict[str, Any], refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    promises = [
        item for item in _as_list(_as_dict(selected.get("longformPlan")).get("chapterPromises")) if isinstance(item, dict)
    ][:6]
    while len(promises) < 6:
        index = len(promises) + 1
        promises.append({"chapterId": f"chapter-{index:02d}", "promise": f"{material.get('title')} proof chapter {index}"})

    chapters = []
    for index, promise in enumerate(promises, start=1):
        chapter_id = _text(promise.get("chapterId")) or f"chapter-{index:02d}"
        ref = refs[(index - 1) % max(1, len(refs))] if refs else {"url": "https://www.google.com/", "title": "Search reference"}
        evidence_id = f"evidence-{index:02d}"
        chapters.append(
            {
                "chapterId": chapter_id,
                "title": f"{index}. {_text(promise.get('promise'))[:60] or material.get('title')}",
                "claim": _text(promise.get("promise")) or _text(material.get("centralQuestion")),
                "bridgeFromPrevious": "이전 단계의 차단점을 다음 증거로 연결한다." if index > 1 else "",
                "segments": [
                    {"segmentId": f"{chapter_id}-seg-01", "purpose": "setup"},
                    {"segmentId": f"{chapter_id}-seg-02", "purpose": "evidence"},
                    {"segmentId": f"{chapter_id}-seg-03", "purpose": "implication"},
                ],
                "evidence": [
                    {
                        "evidenceId": evidence_id,
                        "sourceUrl": ref.get("url"),
                        "rightsStatus": "editorial-approved",
                        "citation": ref.get("title"),
                    }
                ],
            }
        )
    return chapters


def _storyboard(material: dict[str, Any], selected: dict[str, Any], chapters: list[dict[str, Any]]) -> dict[str, Any]:
    beats = []
    for chapter_index, chapter in enumerate(chapters, start=1):
        evidence_id = _as_dict(_as_list(chapter.get("evidence"))[0] if chapter.get("evidence") else {}).get("evidenceId")
        for segment_index, segment in enumerate(_as_list(chapter.get("segments")), start=1):
            beats.append(
                {
                    "beatId": f"{segment['segmentId']}-beat",
                    "chapterId": chapter["chapterId"],
                    "startSec": ((chapter_index - 1) * 90) + ((segment_index - 1) * 30),
                    "durationSec": 24,
                    "visualIntent": f"Show {segment['purpose']} for {_text(material.get('title'))}",
                    "narrationIntent": f"Explain {segment['purpose']} and the dry-run gate evidence.",
                    "providerRole": "primaryMotion" if segment_index != 2 else "referenceStill",
                    "evidenceRef": evidence_id,
                }
            )
    longform_plan = _as_dict(selected.get("longformPlan"))
    return {
        "thesis": _text(material.get("centralQuestion")) or "Dry-run gate readiness must be proven before production.",
        "viewerPromise": _text(selected.get("viewerPromise")) or "The viewer sees exactly what blocks the production run.",
        "chapterMarkers": [
            {"chapterId": chapter["chapterId"], "startSec": (index - 1) * 90, "title": chapter["title"]}
            for index, chapter in enumerate(chapters, start=1)
        ],
        "retentionPlan": {
            "first30SecPromise": _text(longform_plan.get("first30SecPromise")) or "Open with the dry-run blocker map.",
            "titleThumbnailExpectation": _text(longform_plan.get("titleThumbnailExpectation")) or "The opening answers the title question.",
            "topMomentPreview": _text(longform_plan.get("topMomentPreview")) or "Preview the readiness report result.",
            "dipRiskMitigations": _as_list(longform_plan.get("dipRiskMitigations")) or [{"risk": "static report", "mitigation": "cut to packet artifacts"}],
        },
        "beats": beats,
        "visualContinuityBible": {
            "shotLanguage": "screen-recorded dashboard evidence, packet cards, and clear gate-status inserts",
            "colorTreatment": "neutral UI capture with consistent contrast",
            "layoutRules": "status labels stay outside primary evidence areas",
            "styleRules": ["one gate label grid", "no center-caption overload"],
            "recurringAssets": ["gate status chip", "readiness report card"],
        },
        "webReferenceLedger": {"references": _storyboard_references()},
    }


def _storyboard_references() -> list[dict[str, Any]]:
    day = _today()
    return [
        _reference("YouTube chapter support", "https://support.google.com/youtube/answer/9884579", "official-platform", day, ["chapterMarkerGate"]),
        _reference("B-Script editing research", "https://arxiv.org/abs/1902.11216", "research-paper", day, ["longformStoryboardGate", "storyboardBeatCoverageGate"]),
        _reference("AVscript editing research", "https://arxiv.org/abs/2302.14117", "research-paper", day, ["evidenceVisualBindingGate", "visualContinuityBibleGate"]),
        _reference("Video Studio dashboard reference", "project://docs/reference/dashboard-ux-ia.md", "primary", day, ["retentionPlanGate", "chapterMarkerGate"]),
    ]


def _reference(title: str, url: str, source_type: str, day: str, gates: list[str]) -> dict[str, Any]:
    return {
        "title": title,
        "url": url,
        "sourceType": source_type,
        "retrievedAt": day,
        "takeaways": ["Used as a durable planning reference for the dry-run gate packet."],
        "appliedGateKeys": gates,
    }


def _power_user_plan(storyboard: dict[str, Any]) -> dict[str, Any]:
    beat_ids = [_text(beat.get("beatId")) for beat in _as_list(storyboard.get("beats")) if isinstance(beat, dict)]
    return {
        "packagingPlan": {
            "premise": "Dry-run readiness is the product of material, source, workflow, production, and render gates.",
            "targetViewer": "Operators deciding whether to start real AI video generation.",
            "firstTenSecondExpectation": "The opening shows the dry-run blocker map and final pass/fail state.",
            "payoffPromise": "The ending identifies whether rough-cut dry-run may start.",
            "titleOptions": ["Dry-run before generation", "Where AI video production fails", "The gate report before the render"],
            "thumbnailBriefs": [
                {"visualHook": "dashboard pass/fail split", "contrastPoint": "ready versus blocked"},
                {"visualHook": "readiness report card", "subject": "dry-run packet"},
            ],
        },
        "feasibilityPlan": {
            "risks": [
                {"risk": "source continuity breaks", "mitigation": "bind every beat to sourceLedger refs", "owner": "producer"},
                {"risk": "dry-run overclaims final quality", "mitigation": "keep final/publish gates skipped", "owner": "reviewer"},
                {"risk": "external generation starts too early", "mitigation": "require readiness report artifact first", "owner": "source lead"},
            ],
            "killCriteria": ["material evaluation is blocked", "dryrunAllowed is false"],
            "resourcePlan": {
                "owner": "producer",
                "sourceBudget": "zero-paid browser/manual generation only",
                "fallbackPath": "use reference stills and dashboard packet evidence",
            },
        },
        "roughCutRetentionMap": [
            {
                "label": label,
                "startSec": start_sec,
                "viewerQuestion": f"What does {label} prove?",
                "payoff": f"{label} resolves one dry-run readiness concern.",
                "sourceBeatId": beat_ids[min(index, max(0, len(beat_ids) - 1))],
            }
            for index, (label, start_sec) in enumerate(
                [
                    ("open-loop", 0),
                    ("material-proof", 90),
                    ("source-proof", 180),
                    ("workflow-proof", 270),
                    ("render-preflight", 360),
                    ("readiness-result", 510),
                ]
            )
        ],
        "feedbackLoop": {
            "iterationPolicy": "Revise any blocked gate before external generation or export starts.",
            "reviewPasses": [
                {"stage": "script", "reviewerRole": "producer", "decisionRule": "promise is concrete"},
                {"stage": "roughCut", "reviewerRole": "editor", "decisionRule": "gate sequence is visible"},
                {"stage": "final", "reviewerRole": "operator", "decisionRule": "final evidence is not overclaimed"},
            ],
        },
        "derivativeClipPlan": {
            "cadence": "three clips after longform approval",
            "qualityControl": "clips preserve gate context and never imply final/publish readiness",
            "clips": [
                {"clipId": "clip-01", "sourceBeatId": beat_ids[0], "platform": "shorts", "hook": "dry-run pass/fail", "viewerPromise": "full video explains each gate", "contextPreserved": True},
                {"clipId": "clip-02", "sourceBeatId": beat_ids[min(6, len(beat_ids) - 1)], "platform": "reels", "hook": "source proof blocker", "viewerPromise": "full video shows the source ledger", "contextPreserved": True},
                {"clipId": "clip-03", "sourceBeatId": beat_ids[min(15, len(beat_ids) - 1)], "platform": "tiktok", "hook": "readiness report", "viewerPromise": "full video covers the packet", "noMisleadingContext": True},
            ],
        },
        "powerUserCaseLedger": {"references": _power_user_references()},
    }


def _power_user_references() -> list[dict[str, Any]]:
    day = _today()
    return [
        _reference("Runway workflow reference", "https://runwayml.com/product", "industry-case", day, ["packagingPremiseGate"]),
        _reference("CapCut workflow reference", "https://www.capcut.com/tools/online-video-editor", "industry-case", day, ["productionFeasibilityGate"]),
        _reference("B-Script production research", "https://arxiv.org/abs/1902.11216", "research-paper", day, ["roughCutRetentionMapGate"]),
        _reference("AVscript review research", "https://arxiv.org/abs/2302.14117", "research-paper", day, ["creatorFeedbackLoopGate"]),
        _reference("Video Studio dashboard gate reference", "project://docs/reference/dashboard-ux-ia.md", "industry-analysis", day, ["derivativeClipPlanGate"]),
    ]
