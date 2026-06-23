from __future__ import annotations

from typing import Any

from worker.render.longform_minimum_release_gate import evaluate_longform_minimum_release_gate


SCHEMA = "video-studio.production-gate-orchestrator.v1"

STAGE_REGISTRY: list[dict[str, Any]] = [
    {
        "stage": "material-intake",
        "label": "소재 입력",
        "nextAction": "소재 제목, 중심 질문, 탐색 seed를 먼저 저장하세요.",
    },
    {
        "stage": "source-ledger",
        "label": "외부 조사 축적",
        "nextAction": "검색, 트렌드, 영상, 커뮤니티 관찰 URL과 메모를 sourceLedger에 채우세요.",
    },
    {
        "stage": "topic-discovery",
        "label": "소재 검증",
        "nextAction": "소재 게이트를 실행하고 failed checks를 해결하세요.",
    },
    {
        "stage": "storyboard",
        "label": "스토리보드",
        "nextAction": "검증된 소재에서 챕터, 장면, 첫 30초 약속을 확정하세요.",
    },
    {
        "stage": "source-acquisition",
        "label": "소스 확보",
        "nextAction": "각 장면의 원본/생성 소스와 provenance를 확보하세요.",
    },
    {
        "stage": "prompt-quality",
        "label": "프롬프트 품질",
        "nextAction": "장면별 물리 동작, 카메라, 금지 요소, continuity 프롬프트를 검수하세요.",
    },
    {
        "stage": "asset-import-review",
        "label": "소스 import 검수",
        "nextAction": "확보한 이미지/영상이 장면 의도와 형식에 맞는지 accepted-source map으로 고르세요.",
    },
    {
        "stage": "edit-assembly",
        "label": "편집 조립",
        "nextAction": "컷 리듬, 자막, 오디오, 전환을 한 편의 후보로 조립하세요.",
    },
    {
        "stage": "render-preflight",
        "label": "렌더 전 점검",
        "nextAction": "render manifest, safe zone, 오디오/자막/해상도 조건을 확인하세요.",
    },
    {
        "stage": "quality-review",
        "label": "품질 검수",
        "nextAction": "폰 화면 기준 시청, QA 리포트, 실패 원인과 다음 mutation을 기록하세요.",
    },
    {
        "stage": "publish-readiness",
        "label": "게시 준비",
        "nextAction": "제목, 썸네일, 설명, 업로드 금지 리스크, 최종 승인 증거를 채우세요.",
    },
    {
        "stage": "post-publish-learning",
        "label": "게시 후 학습",
        "nextAction": "플랫폼 지표와 댓글 학습을 소재 라이브러리에 다시 쌓으세요.",
    },
]

PROCESS_AUDIT_SCHEMA = "video-studio.production-process-gate-audit.v1"

PROCESS_GATE_AUDIT_REGISTRY: list[dict[str, Any]] = [
    {
        "stage": "material-intake",
        "dashboardSurfaces": ["home", "topic"],
        "gateAnchors": ["worker/bridge/material_library.py:evaluate_material_quality"],
        "testAnchors": ["tests/test_material_library_routes.py"],
        "evidenceRequired": ["title", "centralQuestion", "searchSeed"],
    },
    {
        "stage": "source-ledger",
        "dashboardSurfaces": ["home", "topic", "sources"],
        "gateAnchors": ["worker/render/production_gate_orchestrator.py:_source_ledger_gate"],
        "testAnchors": ["tests/test_production_gate_orchestrator.py", "tests/test_topic_discovery_gate.py"],
        "evidenceRequired": ["search", "trend", "video", "community", "sourceLedger>=5"],
    },
    {
        "stage": "topic-discovery",
        "dashboardSurfaces": ["topic", "advanced"],
        "gateAnchors": ["worker/render/topic_discovery_gate.py:evaluate_topic_discovery_gate"],
        "testAnchors": ["tests/test_topic_discovery_gate.py", "tests/test_gate_routes.py"],
        "evidenceRequired": ["candidateMatrix", "communitySignals", "trendEvidence", "riskReview", "selection"],
    },
    {
        "stage": "storyboard",
        "dashboardSurfaces": ["home", "plan"],
        "gateAnchors": ["worker/render/longform_workflow_gate.py:evaluate_longform_workflow_gate"],
        "testAnchors": ["tests/test_longform_workflow_gate.py", "tests/test_dashboard_ia_contract.py"],
        "evidenceRequired": ["chapterPromises", "first30SecPromise", "scenePlan"],
    },
    {
        "stage": "source-acquisition",
        "dashboardSurfaces": ["sources", "edit"],
        "gateAnchors": ["worker/render/production_gate_orchestrator.py:_evidence_stage"],
        "testAnchors": ["tests/test_production_gate_orchestrator.py"],
        "evidenceRequired": ["sourceAcquisitionPacket", "sourceLibrary", "acceptedSourceMap"],
    },
    {
        "stage": "prompt-quality",
        "dashboardSurfaces": ["plan", "sources", "edit"],
        "gateAnchors": ["worker/render/production_mode_gate.py:evaluate_production_mode_gate"],
        "testAnchors": ["tests/test_production_mode_gate.py", "tests/test_dashboard_ia_contract.py"],
        "evidenceRequired": ["sourcePromptBible", "browserHandoffBatch", "scenePromptRules"],
    },
    {
        "stage": "asset-import-review",
        "dashboardSurfaces": ["sources", "review"],
        "gateAnchors": ["worker/render/production_gate_orchestrator.py:_evidence_stage"],
        "testAnchors": ["tests/test_production_gate_orchestrator.py"],
        "evidenceRequired": ["assetImportReview", "acceptedSourceMap", "assetCandidateReview"],
    },
    {
        "stage": "edit-assembly",
        "dashboardSurfaces": ["edit", "review"],
        "gateAnchors": ["worker/render/production_gate_orchestrator.py:_evidence_stage"],
        "testAnchors": ["tests/test_production_gate_orchestrator.py", "tests/test_dashboard_ia_contract.py"],
        "evidenceRequired": ["editAssembly", "roughCut", "renderCandidate"],
    },
    {
        "stage": "render-preflight",
        "dashboardSurfaces": ["edit", "review"],
        "gateAnchors": ["worker/render/longform_dryrun_readiness.py:_evaluate_render_preflight_gate"],
        "testAnchors": ["tests/test_longform_dryrun_readiness.py"],
        "evidenceRequired": ["renderManifest", "safeZone", "audioCaptionResolution"],
    },
    {
        "stage": "quality-review",
        "dashboardSurfaces": ["review"],
        "gateAnchors": ["worker/render/golden_reference_gate.py"],
        "testAnchors": ["tests/test_golden_reference_gate.py", "tests/test_dashboard_ia_contract.py"],
        "evidenceRequired": ["qualityReview", "qaReport", "phoneReview"],
    },
    {
        "stage": "publish-readiness",
        "dashboardSurfaces": ["review"],
        "gateAnchors": ["worker/render/longform_minimum_release_gate.py:evaluate_longform_minimum_release_gate"],
        "testAnchors": ["tests/test_longform_minimum_release_gate.py"],
        "evidenceRequired": ["publishReadiness", "releasePacket", "publishDisclosureReview", "uploadPacket"],
    },
    {
        "stage": "post-publish-learning",
        "dashboardSurfaces": ["advanced"],
        "gateAnchors": ["worker/render/production_gate_orchestrator.py:_evidence_stage"],
        "testAnchors": ["tests/test_production_gate_orchestrator.py"],
        "evidenceRequired": ["analyticsPacket", "platformMetrics", "postPublishLearning"],
    },
]

REQUIRED_SOURCE_SURFACES = {"search", "trend", "video", "community"}
STRUCTURED_PROOF_STAGES = {
    "source-acquisition",
    "asset-import-review",
    "edit-assembly",
    "quality-review",
    "post-publish-learning",
}
PROOF_GRADE_BY_STAGE = {
    "material-intake": "field-check",
    "source-ledger": "ledger-surface-check",
    "topic-discovery": "topic-validator",
    "storyboard": "workflow-validator",
    "source-acquisition": "structured-proof-required",
    "prompt-quality": "production-mode-validator",
    "asset-import-review": "structured-proof-required",
    "edit-assembly": "structured-proof-required",
    "render-preflight": "active-render-lock-validator",
    "quality-review": "structured-proof-required",
    "publish-readiness": "minimum-release-validator",
    "post-publish-learning": "structured-proof-required",
}
STAGE_PROOF_FIELD_HINTS = {
    "storyboard": ("beats", "chapters", "chapterPromises", "scenePlan", "storyboard"),
    "source-acquisition": ("assets", "sources", "sourceLibrary", "acceptedSources", "provenance", "sourceAcquisition"),
    "prompt-quality": ("prompts", "sourcePromptBible", "browserHandoffBatch", "scenePromptRules", "providerRoleMatrix"),
    "asset-import-review": ("accepted", "acceptedSources", "acceptedSourceMap", "assetCandidateReview", "reviewVerdict"),
    "edit-assembly": ("cuts", "roughCut", "renderCandidate", "renderManifest", "timeline", "ffprobe"),
    "render-preflight": ("manifest", "renderManifest", "safeZone", "audioCaptionResolution", "activeProductionPacketLock"),
    "quality-review": ("qa", "qaReport", "phoneReview", "qualityReport", "qualityAudit", "reviewVerdict"),
    "publish-readiness": ("release", "releasePacket", "publishReadiness", "publishDisclosureReview", "uploadPacket", "publishPacket"),
    "post-publish-learning": ("analytics", "analyticsPacket", "platformMetrics", "postPublishLearning", "learningNotes"),
}
FAIL_STATUSES = {"fail", "failed", "blocked", "reject", "rejected", "missing", "needs-proof"}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _latest_gate_event(material: dict[str, Any], stage: str) -> dict[str, Any]:
    for event in reversed(_as_list(material.get("gateHistory"))):
        if isinstance(event, dict) and event.get("stage") == stage:
            return event
    return {}


def _source_surface(entry: dict[str, Any]) -> str:
    surface = str(entry.get("surface") or entry.get("sourceType") or entry.get("provider") or "").lower()
    if "trend" in surface or "datalab" in surface:
        return "trend"
    if "youtube" in surface or "video" in surface:
        return "video"
    if "community" in surface or "dcinside" in surface or "fmkorea" in surface or "theqoo" in surface or "forum" in surface:
        return "community"
    return "search"


def _stage_result(stage: str, *, status: str, detail: str, failed_checks: list[str] | None = None) -> dict[str, Any]:
    definition = next(item for item in STAGE_REGISTRY if item["stage"] == stage)
    return {
        "stage": stage,
        "label": definition["label"],
        "status": status,
        "detail": detail,
        "failedChecks": failed_checks or [],
        "nextAction": definition["nextAction"] if status != "pass" else "다음 제작 게이트로 진행하세요.",
    }


def _packet_present(packets: dict[str, Any], *names: str) -> bool:
    return any(bool(packets.get(name)) for name in names)


def _meaningful(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return not isinstance(value, bool)
    if isinstance(value, list):
        return any(_meaningful(item) for item in value)
    if isinstance(value, dict):
        return any(_meaningful(item) for item in value.values())
    return True


def _first_packet(packets: dict[str, Any], *names: str) -> tuple[str, Any]:
    for name in names:
        if name in packets:
            return name, packets.get(name)
    return "", None


def _packet_has_production_proof(stage: str, payload: Any) -> tuple[bool, str]:
    if not _meaningful(payload):
        return False, "empty packet"
    if isinstance(payload, str):
        return True, "non-empty artifact reference"
    if isinstance(payload, list):
        return True, f"{len(payload)} evidence item(s)"
    if not isinstance(payload, dict):
        return True, "non-object evidence value"

    status = str(payload.get("status") or payload.get("verdict") or payload.get("reviewStatus") or "").strip().lower()
    if status in FAIL_STATUSES:
        return False, f"status={status}"

    hints = STAGE_PROOF_FIELD_HINTS.get(stage, ())
    present = [key for key in hints if _meaningful(payload.get(key))]
    if present:
        return True, "proof fields: " + ", ".join(present[:4])

    if _meaningful({key: value for key, value in payload.items() if key not in {"status", "verdict"}}):
        return True, "non-empty structured evidence"
    return False, "missing proof fields"


def _material_intake_gate(material: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in ["title", "centralQuestion", "searchSeed"] if not str(material.get(key) or "").strip()]
    if missing:
        return _stage_result("material-intake", status="blocked", detail="소재 기본 필드가 비어 있습니다.", failed_checks=missing)
    return _stage_result("material-intake", status="pass", detail="소재 기본 필드가 저장되었습니다.")


def _source_ledger_gate(material: dict[str, Any]) -> dict[str, Any]:
    source_ledger = [entry for entry in _as_list(material.get("sourceLedger")) if isinstance(entry, dict)]
    surfaces = {_source_surface(entry) for entry in source_ledger}
    missing_surfaces = sorted(REQUIRED_SOURCE_SURFACES - surfaces)
    failed = []
    if len(source_ledger) < 5:
        failed.append("minimumSourceLedgerEntries")
    failed.extend([f"missingSurface:{surface}" for surface in missing_surfaces])
    if failed:
        return _stage_result(
            "source-ledger",
            status="blocked",
            detail=f"sourceLedger {len(source_ledger)}개, 표면 {sorted(surfaces)} 상태입니다.",
            failed_checks=failed,
        )
    return _stage_result("source-ledger", status="pass", detail="검색/트렌드/영상/커뮤니티 표면이 모두 축적되었습니다.")


def _topic_discovery_gate(material: dict[str, Any], packets: dict[str, Any], source_status: str) -> dict[str, Any]:
    if source_status != "pass":
        return _stage_result("topic-discovery", status="blocked", detail="sourceLedger 게이트가 먼저 통과해야 합니다.", failed_checks=["sourceLedger"])
    gate_event = _latest_gate_event(material, "topic-discovery")
    topic_result = _as_dict(packets.get("topicGateResult") or packets.get("topicDiscoveryGate"))
    report = _as_dict(topic_result.get("report"))
    ready = gate_event.get("status") == "pass" or topic_result.get("ready") is True or report.get("topicReady") is True
    if ready:
        return _stage_result("topic-discovery", status="pass", detail="소재 검증 게이트가 통과되었습니다.")
    return _stage_result("topic-discovery", status="pending", detail="소재 게이트 통과 이벤트가 아직 없습니다.", failed_checks=["topicDiscoveryGate"])


def _evidence_stage(stage: str, packets: dict[str, Any], names: tuple[str, ...], prerequisite_status: str) -> dict[str, Any]:
    if prerequisite_status != "pass":
        return _stage_result(stage, status="blocked", detail="이전 제작 게이트가 먼저 통과해야 합니다.", failed_checks=["previousStage"])
    present = [(name, packets.get(name)) for name in names if name in packets]
    if present:
        insufficient: list[str] = []
        for name, payload in present:
            ok, detail = _packet_has_production_proof(stage, payload)
            if ok:
                return _stage_result(stage, status="pass", detail=f"{stage} 증거 packet이 검증되었습니다: {name} ({detail}).")
            insufficient.append(f"{name}:{detail}")
        return _stage_result(
            stage,
            status="pending",
            detail=f"{stage} packet은 있으나 proof 필드가 비어 있습니다.",
            failed_checks=[f"insufficientEvidence:{item}" for item in insufficient],
        )
    return _stage_result(stage, status="pending", detail=f"{stage} 증거 packet이 아직 없습니다.", failed_checks=[*names])


def _publish_readiness_stage(packets: dict[str, Any], prerequisite_status: str) -> dict[str, Any]:
    if prerequisite_status != "pass":
        return _stage_result("publish-readiness", status="blocked", detail="이전 제작 게이트가 먼저 통과해야 합니다.", failed_checks=["previousStage"])

    release_name, release_packet = _first_packet(
        packets,
        "longformMinimumReleasePacket",
        "longformReleasePacket",
        "minimumReleasePacket",
        "releaseGatePacket",
        "releasePacket",
    )
    if not release_name:
        return _stage_result(
            "publish-readiness",
            status="pending",
            detail="publish-readiness에는 최소 출시 기준 packet이 필요합니다.",
            failed_checks=["releasePacket"],
        )
    if not isinstance(release_packet, dict):
        return _stage_result(
            "publish-readiness",
            status="pending",
            detail="release packet은 JSON object여야 합니다.",
            failed_checks=[f"insufficientEvidence:{release_name}:not-object"],
        )

    release_report = evaluate_longform_minimum_release_gate(release_packet)
    if release_report.get("releaseAllowed") is not True:
        return _stage_result(
            "publish-readiness",
            status="blocked",
            detail="최소 출시 기준 gate가 실패했습니다.",
            failed_checks=["minimumReleaseGate", *_as_list(release_report.get("failedChecks"))],
        )

    packet_name, publish_packet = _first_packet(packets, "publishReadiness", "publishPacket", "uploadPacket")
    ok, detail = _packet_has_production_proof("publish-readiness", publish_packet)
    if not packet_name or not ok:
        failed = "publishPacket" if not packet_name else f"insufficientEvidence:{packet_name}:{detail}"
        return _stage_result(
            "publish-readiness",
            status="pending",
            detail="최소 출시 기준은 통과했지만 게시 packet 증거가 부족합니다.",
            failed_checks=[failed],
        )
    return _stage_result(
        "publish-readiness",
        status="pass",
        detail=f"최소 출시 기준과 게시 packet이 검증되었습니다: {release_name}, {packet_name}.",
    )


def evaluate_production_gates(material: dict[str, Any], packets: dict[str, Any] | None = None) -> dict[str, Any]:
    material = _as_dict(material)
    packets = _as_dict(packets)
    stages: list[dict[str, Any]] = []

    material_stage = _material_intake_gate(material)
    stages.append(material_stage)
    source_stage = _source_ledger_gate(material) if material_stage["status"] == "pass" else _stage_result(
        "source-ledger",
        status="blocked",
        detail="소재 입력이 먼저 필요합니다.",
        failed_checks=["material-intake"],
    )
    stages.append(source_stage)
    topic_stage = _topic_discovery_gate(material, packets, source_stage["status"])
    stages.append(topic_stage)

    rolling_status = topic_stage["status"]
    stage_packets = {
        "storyboard": ("storyboardPacket", "storyboard", "planPacket"),
        "source-acquisition": ("sourceAcquisitionPacket", "sourceLibrary", "acceptedSourceMap"),
        "prompt-quality": ("promptQualityPacket", "sourcePromptBible", "browserHandoffBatch"),
        "asset-import-review": ("assetImportReview", "assetCandidateReview", "acceptedSourceMap"),
        "edit-assembly": ("editAssembly", "renderCandidate", "roughCut"),
        "render-preflight": ("renderPreflight", "renderManifest"),
        "quality-review": ("qualityReview", "qaReport", "phoneReview"),
    }
    for stage, packet_names in stage_packets.items():
        stage_result = _evidence_stage(stage, packets, packet_names, rolling_status)
        stages.append(stage_result)
        rolling_status = stage_result["status"]
    publish_stage = _publish_readiness_stage(packets, rolling_status)
    stages.append(publish_stage)
    rolling_status = publish_stage["status"]
    post_publish_stage = _evidence_stage(
        "post-publish-learning",
        packets,
        ("postPublishLearning", "analyticsPacket", "platformMetrics"),
        rolling_status,
    )
    stages.append(post_publish_stage)

    current = next((stage for stage in stages if stage["status"] != "pass"), stages[-1])
    failed = [stage for stage in stages if stage["status"] in {"blocked", "fail"}]
    overall = "pass" if all(stage["status"] == "pass" for stage in stages) else ("blocked" if failed else "pending")
    return {
        "schema": SCHEMA,
        "materialId": material.get("materialId"),
        "title": material.get("title"),
        "overallStatus": overall,
        "currentStage": current["stage"],
        "blockedStage": failed[0]["stage"] if failed else None,
        "nextAction": current["nextAction"],
        "stages": stages,
        "registry": STAGE_REGISTRY,
        "proofGradeByStage": PROOF_GRADE_BY_STAGE,
    }


def build_process_gate_audit() -> dict[str, Any]:
    stage_ids = [item["stage"] for item in STAGE_REGISTRY]
    audit_rows: list[dict[str, Any]] = []
    for definition in STAGE_REGISTRY:
        row = next((item for item in PROCESS_GATE_AUDIT_REGISTRY if item["stage"] == definition["stage"]), {})
        missing: list[str] = []
        for key in ["dashboardSurfaces", "gateAnchors", "testAnchors", "evidenceRequired"]:
            if not _as_list(row.get(key)):
                missing.append(key)
        audit_rows.append(
            {
                "stage": definition["stage"],
                "label": definition["label"],
                "status": "covered" if not missing else "gap",
                "coverageStatus": "covered" if not missing else "gap",
                "proofGrade": PROOF_GRADE_BY_STAGE.get(definition["stage"], "unclassified"),
                "proofRequiresRuntimeEvidence": definition["stage"] in STRUCTURED_PROOF_STAGES,
                "missing": missing,
                "dashboardSurfaces": _as_list(row.get("dashboardSurfaces")),
                "gateAnchors": _as_list(row.get("gateAnchors")),
                "testAnchors": _as_list(row.get("testAnchors")),
                "evidenceRequired": _as_list(row.get("evidenceRequired")),
                "nextAction": definition["nextAction"],
            }
        )
    missing_registry = sorted(set(stage_ids) - {item["stage"] for item in PROCESS_GATE_AUDIT_REGISTRY})
    return {
        "schema": PROCESS_AUDIT_SCHEMA,
        "stageCount": len(stage_ids),
        "coveredStageCount": sum(1 for row in audit_rows if row["status"] == "covered"),
        "gapStageCount": sum(1 for row in audit_rows if row["status"] != "covered"),
        "proofValidatorStageCount": sum(1 for row in audit_rows if row["proofGrade"].endswith("validator")),
        "structuredProofStageCount": sum(1 for row in audit_rows if row["proofRequiresRuntimeEvidence"]),
        "missingRegistryStages": missing_registry,
        "rows": audit_rows,
        "coverageVerdict": "pass" if all(row["status"] == "covered" for row in audit_rows) and not missing_registry else "review",
        "proofVerdict": "review" if any(row["proofRequiresRuntimeEvidence"] for row in audit_rows) else "pass",
        "verdict": "review" if any(row["proofRequiresRuntimeEvidence"] for row in audit_rows) or missing_registry else "pass",
    }
