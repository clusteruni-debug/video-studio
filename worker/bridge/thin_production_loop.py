from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from worker.bridge.grok_browser_proof import classify_grok_browser_proof


SCHEMA = "video-studio.thin-production-loop.v1"

STAGES: list[dict[str, str]] = [
    {
        "stage": "material",
        "label": "소재 선택",
        "nextAction": "소재 DB에서 sourceLedger가 있는 소재를 선택하세요.",
    },
    {
        "stage": "rough-cut-dryrun",
        "label": "Rough-cut dry-run",
        "nextAction": "rough-cut targetStage로 dry-run readiness report를 저장하세요.",
    },
    {
        "stage": "source-accepted",
        "label": "소스 accepted",
        "nextAction": "장면별 source proof를 accepted로 남기세요.",
    },
    {
        "stage": "render-candidate",
        "label": "렌더 후보",
        "nextAction": "render manifest와 후보 MP4 경로를 연결하세요.",
    },
    {
        "stage": "phone-review",
        "label": "폰 화면 검수",
        "nextAction": "사람이 폰 비율로 full-watch 검수한 phone-review evidence를 남기세요.",
    },
]


def _now_kst() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "pass", "passed", "accepted", "approved", "ready"}
    return bool(value)


def _stage(stage: str, status: str, detail: str, failed_checks: list[str] | None = None) -> dict[str, Any]:
    definition = next(item for item in STAGES if item["stage"] == stage)
    return {
        "stage": stage,
        "label": definition["label"],
        "status": status,
        "detail": detail,
        "failedChecks": failed_checks or [],
        "nextAction": definition["nextAction"] if status != "pass" else "다음 thin-loop 단계로 진행하세요.",
    }


def _material_stage(packet: dict[str, Any]) -> dict[str, Any]:
    material = _as_dict(packet.get("material"))
    material_id = _text(packet.get("materialId") or material.get("materialId"))
    source_count = len(_as_list(material.get("sourceLedger")))
    if not material_id and not _text(material.get("title")):
        return _stage("material", "blocked", "소재 ID 또는 소재 제목이 없습니다.", ["material"])
    if source_count <= 0 and not _truthy(packet.get("sourceLedgerReady")):
        return _stage("material", "pending", "소재는 있지만 sourceLedger proof가 부족합니다.", ["sourceLedger"])
    return _stage("material", "pass", "소재와 sourceLedger가 thin-loop 입력으로 준비되었습니다.")


def _dryrun_stage(packet: dict[str, Any], prerequisite: str) -> dict[str, Any]:
    if prerequisite != "pass":
        return _stage("rough-cut-dryrun", "blocked", "소재 단계가 먼저 통과해야 합니다.", ["material"])
    dryrun = _as_dict(packet.get("dryrunPreflight") or packet.get("dryrun"))
    target_stage = _text(dryrun.get("targetStage"))
    allowed = dryrun.get("dryrunAllowed") is True
    if allowed and target_stage in {"", "rough-cut"}:
        return _stage("rough-cut-dryrun", "pass", "rough-cut dry-run readiness가 통과했습니다.")
    if target_stage == "final":
        return _stage("rough-cut-dryrun", "blocked", "thin-loop는 final probe가 아니라 rough-cut dry-run에서 시작해야 합니다.", ["targetStage"])
    return _stage("rough-cut-dryrun", "pending", "rough-cut dry-run readiness report가 필요합니다.", ["dryrunPreflight"])


def _source_stage(packet: dict[str, Any], prerequisite: str) -> dict[str, Any]:
    if prerequisite != "pass":
        return _stage("source-accepted", "blocked", "rough-cut dry-run이 먼저 통과해야 합니다.", ["rough-cut-dryrun"])
    source_review = _as_dict(packet.get("sourceReview") or packet.get("sourceAccepted"))
    accepted_sources = _as_list(source_review.get("acceptedSources") or packet.get("acceptedSources"))
    accepted_map = _as_dict(source_review.get("acceptedSourceMap") or packet.get("acceptedSourceMap"))
    browser_proof = classify_grok_browser_proof(_as_dict(source_review.get("browserProof") or packet.get("browserProof")))
    if accepted_sources or accepted_map or browser_proof["success"]:
        return _stage("source-accepted", "pass", "accepted source proof가 연결되었습니다.")
    if browser_proof["status"] == "surface-visible":
        return _stage("source-accepted", "pending", "Grok Imagine surface는 보였지만 생성/import proof가 없습니다.", ["browserProofImported"])
    if browser_proof["isChatRedirect"]:
        return _stage("source-accepted", "blocked", "Grok /c/* redirect는 Imagine source proof로 인정하지 않습니다.", ["grokImagineSurface"])
    return _stage("source-accepted", "pending", "장면별 accepted source proof가 필요합니다.", ["acceptedSources"])


def _render_stage(packet: dict[str, Any], prerequisite: str) -> dict[str, Any]:
    if prerequisite != "pass":
        return _stage("render-candidate", "blocked", "accepted source proof가 먼저 필요합니다.", ["source-accepted"])
    render = _as_dict(packet.get("renderCandidate") or packet.get("render"))
    manifest = _text(render.get("manifestPath") or packet.get("renderManifestPath"))
    output = _text(render.get("outputPath") or render.get("finalVideoPath") or packet.get("finalVideoPath"))
    if manifest and output:
        return _stage("render-candidate", "pass", "render manifest와 후보 MP4가 연결되었습니다.")
    return _stage("render-candidate", "pending", "render manifest와 후보 MP4 경로가 모두 필요합니다.", ["renderManifest", "candidateMp4"])


def _phone_review_stage(packet: dict[str, Any], prerequisite: str) -> dict[str, Any]:
    if prerequisite != "pass":
        return _stage("phone-review", "blocked", "렌더 후보가 먼저 필요합니다.", ["render-candidate"])
    review = _as_dict(packet.get("phoneReview"))
    decision = _text(review.get("reviewerDecision") or review.get("decision") or review.get("status")).lower()
    full_watch = review.get("fullWatchCompleted") is True
    phone_view = review.get("phoneViewport") is True or review.get("phoneSizedReview") is True
    artifacts = _as_dict(review.get("evidencePaths") or review.get("artifacts"))
    has_artifacts = bool(_text(review.get("reviewSnapshotPath")) or artifacts)
    if decision in {"accept", "accepted", "approve", "approved", "pass"} and full_watch and phone_view and has_artifacts:
        return _stage("phone-review", "pass", "phone full-watch review proof가 통과했습니다.")
    failed = []
    if decision in {"reject", "rejected", "fail", "failed"}:
        failed.append("reviewRejected")
    if not full_watch:
        failed.append("fullWatchCompleted")
    if not phone_view:
        failed.append("phoneViewport")
    if not has_artifacts:
        failed.append("reviewArtifacts")
    return _stage("phone-review", "pending" if not failed or failed == ["reviewArtifacts"] else "blocked", "phone full-watch evidence가 부족합니다.", failed)


def _publish_gate(phone_stage: dict[str, Any]) -> dict[str, Any]:
    if phone_stage["status"] == "pass":
        return {
            "status": "pending",
            "allowed": False,
            "reason": "phone-review-passed-publish-packet-required",
            "nextAction": "이제 publish disclosure, title/thumbnail/description, upload risk packet을 채우세요.",
        }
    return {
        "status": "blocked",
        "allowed": False,
        "reason": "phone-review-required-before-publish",
        "nextAction": "phone full-watch review proof 전에는 publish/final gate를 열지 않습니다.",
    }


def build_thin_loop_status(packet: dict[str, Any] | None = None) -> dict[str, Any]:
    packet = _as_dict(packet)
    stages: list[dict[str, Any]] = []
    material = _material_stage(packet)
    stages.append(material)
    dryrun = _dryrun_stage(packet, material["status"])
    stages.append(dryrun)
    source = _source_stage(packet, dryrun["status"])
    stages.append(source)
    render = _render_stage(packet, source["status"])
    stages.append(render)
    phone = _phone_review_stage(packet, render["status"])
    stages.append(phone)
    current = next((stage for stage in stages if stage["status"] != "pass"), stages[-1])
    overall = "pass" if all(stage["status"] == "pass" for stage in stages) else ("blocked" if any(stage["status"] == "blocked" for stage in stages) else "pending")
    return {
        "ok": True,
        "schema": SCHEMA,
        "generatedAt": _now_kst(),
        "overallStatus": overall,
        "currentStage": current["stage"],
        "nextAction": current["nextAction"],
        "stages": stages,
        "publishGate": _publish_gate(phone),
        "stageRegistry": STAGES,
    }
