from __future__ import annotations

from worker.render.longform_workflow_gate import (
    LONGFORM_WORKFLOW_GATE_KEYS,
    LONGFORM_WORKFLOW_STAGE_KEYS,
    evaluate_longform_workflow_gate,
)


def _seeded_failure_suite():
    return [
        {
            "caseId": "order-swap",
            "failureMode": "workflow stages are swapped",
            "expectedGateKey": "longformWorkflowOrderGate",
            "fixtureRef": "tests/fixtures/longform-workflow/order-swap.json",
            "testName": "test_longform_workflow_gate_blocks_out_of_order_source_generation",
            "status": "pass",
        },
        {
            "caseId": "missing-stage-evidence",
            "failureMode": "passed stage has no evidenceRefs",
            "expectedGateKey": "longformWorkflowEvidenceGate",
            "fixtureRef": "tests/fixtures/longform-workflow/missing-evidence.json",
            "testName": "test_longform_workflow_gate_requires_evidence_for_passed_stages",
            "status": "pass",
        },
        {
            "caseId": "skipped-source-generation",
            "failureMode": "later stage advances before source-generation passes",
            "expectedGateKey": "longformWorkflowDependencyGate",
            "fixtureRef": "tests/fixtures/longform-workflow/skipped-source-generation.json",
            "testName": "test_longform_workflow_gate_blocks_dependency_skips",
            "status": "pass",
        },
        {
            "caseId": "blocked-without-mutation",
            "failureMode": "blocked stage has no improvement action",
            "expectedGateKey": "longformWorkflowImprovementLoopGate",
            "fixtureRef": "tests/fixtures/longform-workflow/blocked-without-mutation.json",
            "testName": "test_longform_workflow_gate_requires_improvement_actions_for_failed_stage",
            "status": "pass",
        },
        {
            "caseId": "missing-seeded-suite",
            "failureMode": "workflow gate has no seeded failure suite",
            "expectedGateKey": "longformWorkflowSeededFailureGate",
            "fixtureRef": "tests/fixtures/longform-workflow/missing-seeded-suite.json",
            "testName": "test_longform_workflow_gate_requires_seeded_failure_suite",
            "status": "pass",
        },
        {
            "caseId": "derivative-before-final",
            "failureMode": "derivative clips advance before final readiness passes",
            "expectedGateKey": "longformWorkflowDependencyGate",
            "fixtureRef": "tests/fixtures/longform-workflow/derivative-before-final.json",
            "testName": "test_longform_workflow_gate_blocks_derivative_clips_before_final_readiness",
            "status": "pass",
        },
    ]


def _stage(stage_key: str, status: str = "pending", evidence: bool = True):
    stage = {
        "stageKey": stage_key,
        "status": status,
        "decisionRule": f"{stage_key} must meet its exit checklist before the next stage advances.",
        "reviewerRole": "producer-reviewer",
    }
    if evidence:
        stage["evidenceRefs"] = [f"storage/longform-workflow/{stage_key}/evidence.json"]
    return stage


def _packet(status_by_stage=None):
    status_by_stage = status_by_stage or {}
    return {
        "formatProfile": "longform_10m",
        "workflowStages": [
            _stage(stage_key, status_by_stage.get(stage_key, "pending"))
            for stage_key in LONGFORM_WORKFLOW_STAGE_KEYS
        ],
        "workflowImprovementLoop": {
            "mutationLedgerPath": "storage/longform-workflow/mutation-ledger.json",
            "reviewCadence": "after every blocked, failed, or rough-cut review stage",
        },
        "seededFailureSuite": _seeded_failure_suite(),
    }


def test_longform_workflow_gate_passes_ordered_planning_packet():
    packet = _packet(
        {
            "reference-ledger": "pass",
            "packaging-premise": "pass",
            "storyboard": "pass",
            "script-tts": "pass",
            "source-prompt-bible": "pass",
            "source-generation": "in_progress",
        }
    )

    report = evaluate_longform_workflow_gate(packet)

    assert report["schema"] == "video-studio.longform-workflow-stage-gate.v1"
    assert report["status"] == "pass"
    assert report["failedChecks"] == []
    assert report["generationAllowed"] is True
    assert report["renderAllowed"] is False
    assert report["finalAllowed"] is False
    assert report["currentStage"] == "source-generation"
    assert report["checks"]["longformWorkflowSeededFailureGate"]["status"] == "pass"


def test_longform_workflow_gate_allows_render_and_final_only_after_required_stages_pass():
    report = evaluate_longform_workflow_gate(
        _packet({stage_key: "pass" for stage_key in LONGFORM_WORKFLOW_STAGE_KEYS})
    )

    assert report["status"] == "pass"
    assert report["generationAllowed"] is True
    assert report["renderAllowed"] is True
    assert report["finalAllowed"] is True
    assert report["nextStage"] is None


def test_longform_workflow_gate_blocks_out_of_order_source_generation():
    packet = _packet()
    packet["workflowStages"][1], packet["workflowStages"][2] = (
        packet["workflowStages"][2],
        packet["workflowStages"][1],
    )

    report = evaluate_longform_workflow_gate(packet)

    assert report["status"] == "fail"
    assert "longformWorkflowOrderGate" in report["failedChecks"]
    assert report["generationAllowed"] is False


def test_longform_workflow_gate_requires_evidence_for_passed_stages():
    packet = _packet(
        {
            "reference-ledger": "pass",
            "packaging-premise": "pass",
            "storyboard": "pass",
        }
    )
    packet["workflowStages"][2].pop("evidenceRefs")

    report = evaluate_longform_workflow_gate(packet)

    assert report["status"] == "fail"
    assert "longformWorkflowEvidenceGate" in report["failedChecks"]
    assert "storyboard is pass without evidenceRefs" in report["checks"]["longformWorkflowEvidenceGate"]["detail"]


def test_longform_workflow_gate_blocks_dependency_skips():
    packet = _packet(
        {
            "reference-ledger": "pass",
            "packaging-premise": "pass",
            "storyboard": "pass",
            "script-tts": "pass",
            "source-prompt-bible": "pass",
            "source-review-import": "in_progress",
        }
    )

    report = evaluate_longform_workflow_gate(packet)

    assert report["status"] == "fail"
    assert "longformWorkflowDependencyGate" in report["failedChecks"]
    assert "source-review-import advanced before all previous stages passed" in report["checks"]["longformWorkflowDependencyGate"]["detail"]


def test_longform_workflow_gate_requires_improvement_actions_for_failed_stage():
    packet = _packet(
        {
            "reference-ledger": "pass",
            "packaging-premise": "pass",
            "storyboard": "blocked",
        }
    )

    report = evaluate_longform_workflow_gate(packet)

    assert report["status"] == "fail"
    assert "longformWorkflowImprovementLoopGate" in report["failedChecks"]
    assert report["improvementBacklog"][0]["stageKey"] == "storyboard"


def test_longform_workflow_gate_accepts_failed_stage_with_actionable_mutation():
    packet = _packet(
        {
            "reference-ledger": "pass",
            "packaging-premise": "pass",
            "storyboard": "blocked",
        }
    )
    packet["workflowStages"][2]["improvementActions"] = [
        {
            "owner": "codex",
            "nextMutation": "replace weak storyboard beats with evidence-bound beats",
            "verificationCommand": "python -B -m pytest -q tests/test_longform_workflow_gate.py",
        }
    ]

    report = evaluate_longform_workflow_gate(packet)

    assert "longformWorkflowImprovementLoopGate" not in report["failedChecks"]
    assert report["checks"]["longformWorkflowImprovementLoopGate"]["status"] == "pass"


def test_longform_workflow_gate_requires_seeded_failure_suite():
    packet = _packet(
        {
            "reference-ledger": "pass",
            "packaging-premise": "pass",
            "storyboard": "pass",
        }
    )
    packet["seededFailureSuite"] = []

    report = evaluate_longform_workflow_gate(packet)

    assert report["status"] == "fail"
    assert "longformWorkflowSeededFailureGate" in report["failedChecks"]


def test_longform_workflow_gate_blocks_derivative_clips_before_final_readiness():
    packet = _packet(
        {
            "reference-ledger": "pass",
            "packaging-premise": "pass",
            "storyboard": "pass",
            "script-tts": "pass",
            "source-prompt-bible": "pass",
            "source-generation": "pass",
            "source-review-import": "pass",
            "rough-cut": "pass",
            "render-preflight": "pass",
            "full-watch-review": "pass",
            "derivative-clips": "in_progress",
        }
    )

    report = evaluate_longform_workflow_gate(packet)

    assert report["status"] == "fail"
    assert "longformWorkflowDependencyGate" in report["failedChecks"]


def test_longform_workflow_gate_constants_define_managed_inventory():
    assert LONGFORM_WORKFLOW_GATE_KEYS == (
        "longformWorkflowOrderGate",
        "longformWorkflowEvidenceGate",
        "longformWorkflowDependencyGate",
        "longformWorkflowImprovementLoopGate",
        "longformWorkflowSeededFailureGate",
    )
    assert LONGFORM_WORKFLOW_STAGE_KEYS[0] == "reference-ledger"
    assert LONGFORM_WORKFLOW_STAGE_KEYS[-1] == "derivative-clips"
