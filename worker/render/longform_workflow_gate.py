"""Longform workflow stage gate.

This gate validates the production order itself. It does not judge whether a
finished video is good; it prevents longform work from skipping the evidence,
review, and improvement stages that make later quality gates meaningful.
"""

from __future__ import annotations

from typing import Any


LONGFORM_WORKFLOW_STAGE_KEYS = (
    "reference-ledger",
    "packaging-premise",
    "storyboard",
    "script-tts",
    "source-prompt-bible",
    "source-generation",
    "source-review-import",
    "rough-cut",
    "render-preflight",
    "full-watch-review",
    "final-readiness",
    "derivative-clips",
)

LONGFORM_WORKFLOW_GATE_KEYS = (
    "longformWorkflowOrderGate",
    "longformWorkflowEvidenceGate",
    "longformWorkflowDependencyGate",
    "longformWorkflowImprovementLoopGate",
    "longformWorkflowSeededFailureGate",
)

PASS_STATUSES = {"pass", "passed", "complete", "completed", "approved"}
ACTIVE_STATUSES = {"active", "in_progress", "in-progress", "working"}
PENDING_STATUSES = {"pending", "todo", "not-started", "not_started"}
BLOCKING_STATUSES = {"blocked", "fail", "failed", "rejected"}
SKIP_STATUSES = {"skip", "skipped", "deferred"}


def evaluate_longform_workflow_gate(packet: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether a longform packet can advance through production stages."""

    stages = _workflow_stages(packet)
    report: dict[str, Any] = {
        "schema": "video-studio.longform-workflow-stage-gate.v1",
        "status": "pass",
        "generationAllowed": False,
        "renderAllowed": False,
        "finalAllowed": False,
        "stageOrder": [stage.get("stageKey") for stage in stages],
        "currentStage": _current_stage_key(stages),
        "nextStage": _next_stage_key(stages),
        "failedChecks": [],
        "checks": {},
        "improvementBacklog": _improvement_backlog(stages),
    }

    _check_stage_order(report, stages)
    _check_stage_evidence(report, stages)
    _check_stage_dependencies(report, stages)
    _check_improvement_loop(report, packet, stages)
    _check_seeded_failure_suite(report, packet)
    _set_allowed_flags(report, stages)

    if report["failedChecks"]:
        report["status"] = "fail"
        report["generationAllowed"] = False
        report["renderAllowed"] = False
        report["finalAllowed"] = False
    return report


def _check_stage_order(report: dict[str, Any], stages: list[dict[str, Any]]) -> None:
    keys = [_text(stage.get("stageKey")) for stage in stages]
    expected = list(LONGFORM_WORKFLOW_STAGE_KEYS)
    if keys != expected:
        missing = [key for key in expected if key not in keys]
        extra = [key for key in keys if key not in expected]
        detail = "workflowStages must match LONGFORM_WORKFLOW_STAGE_KEYS exactly."
        if missing:
            detail += " missing=" + ",".join(missing)
        if extra:
            detail += " extra=" + ",".join(extra)
        _fail(report, "longformWorkflowOrderGate", detail)
        return
    _set_check(report, "longformWorkflowOrderGate", "pass", "all longform workflow stages are registered in order.")


def _check_stage_evidence(report: dict[str, Any], stages: list[dict[str, Any]]) -> None:
    problems: list[str] = []
    for stage in stages:
        key = _text(stage.get("stageKey")) or "(missing-stage)"
        status = _stage_status(stage)
        if status not in PASS_STATUSES | ACTIVE_STATUSES | PENDING_STATUSES | BLOCKING_STATUSES | SKIP_STATUSES:
            problems.append(f"{key} has unknown status={status or 'missing'}")
        if not _text(stage.get("decisionRule") or stage.get("exitCriteria") or stage.get("acceptanceCriteria")):
            problems.append(f"{key} needs decisionRule or exitCriteria")
        if status in PASS_STATUSES and not _evidence_refs(stage):
            problems.append(f"{key} is pass without evidenceRefs")
        if status in PASS_STATUSES and not _text(stage.get("reviewerRole")):
            problems.append(f"{key} is pass without reviewerRole")
    if problems:
        _fail(report, "longformWorkflowEvidenceGate", "; ".join(problems[:6]))
        return
    _set_check(report, "longformWorkflowEvidenceGate", "pass", "stage exit criteria and passed-stage evidence are present.")


def _check_stage_dependencies(report: dict[str, Any], stages: list[dict[str, Any]]) -> None:
    problems: list[str] = []
    active_keys = [stage.get("stageKey") for stage in stages if _stage_status(stage) in ACTIVE_STATUSES]
    if len(active_keys) > 1:
        problems.append("only one workflow stage may be active at a time")

    seen_pass_only = True
    for stage in stages:
        key = _text(stage.get("stageKey"))
        status = _stage_status(stage)
        if status in SKIP_STATUSES:
            problems.append(f"{key} cannot be skipped in the required longform workflow")
        if status in PASS_STATUSES | ACTIVE_STATUSES | BLOCKING_STATUSES and not seen_pass_only:
            problems.append(f"{key} advanced before all previous stages passed")
        if status not in PASS_STATUSES:
            seen_pass_only = False

    status_by_key = {_text(stage.get("stageKey")): _stage_status(stage) for stage in stages}
    if status_by_key.get("final-readiness") in PASS_STATUSES and status_by_key.get("full-watch-review") not in PASS_STATUSES:
        problems.append("final-readiness cannot pass before full-watch-review passes")
    if status_by_key.get("derivative-clips") in PASS_STATUSES | ACTIVE_STATUSES and status_by_key.get("final-readiness") not in PASS_STATUSES:
        problems.append("derivative-clips cannot advance before final-readiness passes")

    if problems:
        _fail(report, "longformWorkflowDependencyGate", "; ".join(problems[:6]))
        return
    _set_check(report, "longformWorkflowDependencyGate", "pass", "stage dependencies are sequential and non-skipped.")


def _check_improvement_loop(report: dict[str, Any], packet: dict[str, Any], stages: list[dict[str, Any]]) -> None:
    policy = _improvement_policy(packet)
    problems: list[str] = []
    if not _text(policy.get("mutationLedgerPath") or policy.get("ledgerPath")):
        problems.append("workflowImprovementLoop.mutationLedgerPath is required")
    if not _text(policy.get("reviewCadence") or policy.get("cadence")):
        problems.append("workflowImprovementLoop.reviewCadence is required")

    for stage in stages:
        status = _stage_status(stage)
        if status not in BLOCKING_STATUSES:
            continue
        key = _text(stage.get("stageKey"))
        actions = _improvement_actions(stage)
        if not actions:
            problems.append(f"{key} is {status} without improvementActions")
            continue
        for action in actions:
            if not _text(action.get("owner")):
                problems.append(f"{key} improvement action needs owner")
            if not _text(action.get("nextMutation") or action.get("action")):
                problems.append(f"{key} improvement action needs nextMutation")
            if not _text(action.get("verificationCommand") or action.get("verificationEvidence")):
                problems.append(f"{key} improvement action needs verificationCommand or verificationEvidence")

    if problems:
        _fail(report, "longformWorkflowImprovementLoopGate", "; ".join(problems[:6]))
        return
    _set_check(report, "longformWorkflowImprovementLoopGate", "pass", "improvement policy and blocked-stage mutation actions are present.")


def _check_seeded_failure_suite(report: dict[str, Any], packet: dict[str, Any]) -> None:
    suite = _seeded_failure_suite(packet)
    required_gate_keys = set(LONGFORM_WORKFLOW_GATE_KEYS[:-1])
    covered_gate_keys: set[str] = set()
    problems: list[str] = []

    if len(suite) < 6:
        problems.append("seededFailureSuite needs at least 6 passing failure cases")

    for case in suite:
        case_id = _text(case.get("caseId") or case.get("id"))
        expected_key = _text(case.get("expectedGateKey"))
        if not case_id:
            problems.append("seeded failure case missing caseId")
        if not _text(case.get("failureMode")):
            problems.append(f"{case_id or '(missing-case)'} missing failureMode")
        if expected_key not in LONGFORM_WORKFLOW_GATE_KEYS:
            problems.append(f"{case_id or '(missing-case)'} expectedGateKey is not a workflow gate")
        else:
            covered_gate_keys.add(expected_key)
        if not _text(case.get("fixtureRef") or case.get("fixture")):
            problems.append(f"{case_id or '(missing-case)'} missing fixtureRef")
        if not _text(case.get("verificationCommand") or case.get("testName")):
            problems.append(f"{case_id or '(missing-case)'} missing verification command/testName")
        if _text(case.get("status")).lower() != "pass":
            problems.append(f"{case_id or '(missing-case)'} seeded failure status must be pass")

    missing_coverage = sorted(required_gate_keys - covered_gate_keys)
    if missing_coverage:
        problems.append("seededFailureSuite missing coverage for " + ",".join(missing_coverage))

    if problems:
        _fail(report, "longformWorkflowSeededFailureGate", "; ".join(problems[:6]))
        return
    _set_check(report, "longformWorkflowSeededFailureGate", "pass", "seeded failure suite covers workflow order, evidence, dependency, and improvement gates.")


def _set_allowed_flags(report: dict[str, Any], stages: list[dict[str, Any]]) -> None:
    status_by_key = {_text(stage.get("stageKey")): _stage_status(stage) for stage in stages}

    report["generationAllowed"] = all(
        status_by_key.get(key) in PASS_STATUSES
        for key in (
            "reference-ledger",
            "packaging-premise",
            "storyboard",
            "script-tts",
            "source-prompt-bible",
        )
    )
    report["renderAllowed"] = all(
        status_by_key.get(key) in PASS_STATUSES
        for key in (
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
    )
    report["finalAllowed"] = status_by_key.get("final-readiness") in PASS_STATUSES


def _workflow_stages(packet: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = (
        packet.get("workflowStages"),
        _nested(packet, "longformWorkflow", "stages"),
        _nested(packet, "workflow", "stages"),
    )
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _improvement_policy(packet: dict[str, Any]) -> dict[str, Any]:
    candidates = (
        packet.get("workflowImprovementLoop"),
        packet.get("improvementPolicy"),
        _nested(packet, "longformWorkflow", "workflowImprovementLoop"),
        _nested(packet, "longformWorkflow", "improvementPolicy"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def _seeded_failure_suite(packet: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = (
        packet.get("seededFailureSuite"),
        _nested(packet, "longformWorkflow", "seededFailureSuite"),
        _nested(packet, "qualityVerification", "seededFailureSuite"),
    )
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _nested(packet: dict[str, Any], key: str, nested_key: str) -> Any:
    value = packet.get(key)
    if isinstance(value, dict):
        return value.get(nested_key)
    return None


def _stage_status(stage: dict[str, Any]) -> str:
    return _text(stage.get("status")).lower()


def _evidence_refs(stage: dict[str, Any]) -> list[Any]:
    refs = stage.get("evidenceRefs") or stage.get("evidence") or stage.get("artifacts")
    if isinstance(refs, list):
        return [ref for ref in refs if _text(ref) or isinstance(ref, dict)]
    if _text(refs):
        return [refs]
    return []


def _improvement_actions(stage: dict[str, Any]) -> list[dict[str, Any]]:
    actions = stage.get("improvementActions") or stage.get("nextMutations")
    if isinstance(actions, list):
        return [action for action in actions if isinstance(action, dict)]
    return []


def _improvement_backlog(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    backlog: list[dict[str, Any]] = []
    for stage in stages:
        if _stage_status(stage) not in BLOCKING_STATUSES:
            continue
        backlog.append(
            {
                "stageKey": _text(stage.get("stageKey")),
                "status": _stage_status(stage),
                "actions": _improvement_actions(stage),
            }
        )
    return backlog


def _current_stage_key(stages: list[dict[str, Any]]) -> str | None:
    for stage in stages:
        if _stage_status(stage) in ACTIVE_STATUSES:
            return _text(stage.get("stageKey"))
    return _next_stage_key(stages)


def _next_stage_key(stages: list[dict[str, Any]]) -> str | None:
    for stage in stages:
        if _stage_status(stage) not in PASS_STATUSES:
            return _text(stage.get("stageKey"))
    return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _set_check(report: dict[str, Any], key: str, status: str, detail: str) -> None:
    report["checks"][key] = {"status": status, "detail": detail}


def _fail(report: dict[str, Any], key: str, detail: str) -> None:
    if key not in report["failedChecks"]:
        report["failedChecks"].append(key)
    _set_check(report, key, "fail", detail)
