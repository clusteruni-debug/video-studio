"""Unified quality gate registry for Video Studio.

This module keeps gate naming and status summaries consistent across
preproduction, episode handoffs, render QA, and final-library readiness.
It does not replace the existing domain checks; it makes them report through
one shared system surface.
"""
from __future__ import annotations

from typing import Any


GATE_SYSTEM_VERSION = "2026-06-08-unified-quality-gate-system-v1"

GATE_PHASES = (
    {
        "phaseKey": "preproduction",
        "label": "Preproduction story standard",
        "source": "preproduction/preproduction-manifest.json",
        "purpose": "Block generic generation until a timely topic, viewer question, storyboard, script, visual action, and asset brief exist.",
    },
    {
        "phaseKey": "episode-output",
        "label": "Episode output gate",
        "source": "output-gates.json",
        "purpose": "Block prompt, browser handoff, or episode artifacts when shot sync or quality-loop contracts are not satisfied.",
    },
    {
        "phaseKey": "quality-iteration",
        "label": "Quality iteration ledger",
        "source": "preproduction/quality-iteration-ledger.json",
        "purpose": "Force each failed candidate to record the failure, changed lever, next mutation, and mutation evidence.",
    },
    {
        "phaseKey": "asset-source",
        "label": "Asset candidate and accepted source map",
        "source": "preproduction/asset-candidate-review.json",
        "purpose": "Block render candidates until every storyboard beat has an accepted local motion source and review evidence.",
    },
    {
        "phaseKey": "render-quality",
        "label": "Render quality report",
        "source": "render-quality-report.json",
        "purpose": "Audit rendered MP4 quality, audio, captions, source fit, pacing, publish readiness, and top-tier readiness.",
    },
    {
        "phaseKey": "final-readiness",
        "label": "Final library readiness",
        "source": "/api/final-video-library/audit",
        "purpose": "Separate artifact readiness from same-day upload and broad operating-system completion.",
    },
    {
        "phaseKey": "post-publish-loop",
        "label": "Post-publish analytics loop",
        "source": "platform-analytics.json",
        "purpose": "Keep the system open until live platform analytics produce the next improvement action.",
    },
)

RENDER_QUALITY_CHECK_KEYS = (
    "outputSpec",
    "noPlaceholders",
    "movingClipPriority",
    "sourceMotionEvidence",
    "zeroPaidProviders",
    "captionSafePresets",
    "providerConsistency",
    "antiAiNaturalness",
    "captionSystem",
    "viewerTakeaway",
    "sourceEditorialLayout",
    "sourceEditorialImageContext",
    "internetSourceAcquisition",
    "internetSourceContext",
    "internetSourceEditorialIntegration",
    "topicHookPayoffStructure",
    "audienceInterestSourceFit",
    "sceneSourceIntentBinding",
    "visualFrameReviewEvidence",
    "conversationalCopyStyle",
    "ttsPacingAlignment",
    "sourceLoopRhythm",
    "endingPayoff",
    "endingTailPacing",
    "subtitleArtifact",
    "manualSelectionEvidence",
    "continuityEvidence",
    "firstTwoSecondHook",
    "cutDensityPacing",
    "aiSlopVisualFit",
    "stockAiClipFit",
    "thumbnailFirstFrameStrength",
    "grokSourceCuration",
    "sourceFirstSourceGate",
    "stockOnlyCaveat",
    "ttsNarrationEvidence",
    "voicePolicyCompliance",
    "captionLayoutReview",
    "captionDensityAndSafeZone",
    "referenceEditGrammar",
    "assetReuseDiversity",
    "freeAssetProvenance",
    "stockCandidateCuration",
    "freeAudioCreditsExport",
    "bgmAssetRotation",
    "bgmSoundQuality",
    "templateSourcePlan",
    "qualitySampleSet",
    "qualityRatchet",
    "publishReadinessGate",
    "channelReadinessGate",
    "uploadReviewGate",
    "topTierReadinessGate",
)

FINAL_READINESS_GATE_KEYS = (
    "artifact-gate",
    "fresh-source-import-review",
    "fresh-source-proof",
    "phone-sized-human-review",
    "same-day-upload-decision",
    "platform-analytics-loop",
)


def gate_system_registry(contract_registry: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema": "video-studio.unified-quality-gate-system.v1",
        "systemVersion": GATE_SYSTEM_VERSION,
        "phases": list(GATE_PHASES),
        "qualityLoopContracts": contract_registry or [],
        "renderQualityCheckKeys": list(RENDER_QUALITY_CHECK_KEYS),
        "finalReadinessGateKeys": list(FINAL_READINESS_GATE_KEYS),
    }


def _status_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _phase_state(
    phase_key: str,
    status: str,
    detail: str,
    *,
    source: str = "",
    blocking: bool = False,
    checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    checks = checks or []
    return {
        "phaseKey": phase_key,
        "status": status,
        "blocking": blocking,
        "detail": detail,
        "source": source,
        "checkCount": len(checks),
        "statusCounts": _status_counts(checks),
    }


def build_episode_gate_system(
    *,
    output_status: str,
    checks: list[dict[str, Any]],
    contract_registry: list[dict[str, Any]],
    next_action_status: str,
    quality_loop_required: bool,
) -> dict[str, Any]:
    contract_keys = [
        str(item.get("contractKey") or "")
        for item in contract_registry
        if isinstance(item, dict) and item.get("contractKey")
    ]
    blocking = [item for item in checks if item.get("required") and item.get("status") != "pass"]
    iteration_blocked = quality_loop_required and next_action_status in {"apply-next-mutation", "continue-current-stage"}
    return {
        **gate_system_registry(contract_registry),
        "surface": "episode-output",
        "status": "blocked" if output_status == "blocked" else "pass",
        "blockingPhaseKey": "quality-iteration" if iteration_blocked else "episode-output" if blocking else "",
        "phaseStates": [
            _phase_state(
                "episode-output",
                output_status,
                f"blockingChecks={len(blocking)}",
                source="output-gates.json",
                blocking=bool(blocking),
                checks=checks,
            ),
            _phase_state(
                "quality-iteration",
                "blocked" if iteration_blocked else "pass" if quality_loop_required else "not-required",
                f"nextRequiredAction={next_action_status or 'not-required'}",
                source="preproduction/quality-iteration-ledger.json",
                blocking=iteration_blocked,
            ),
        ],
        "contractSummary": {
            "requiredContractCount": len(contract_keys),
            "requiredContractKeys": contract_keys,
        },
    }


def build_quality_loop_gate_system(
    *,
    standard: dict[str, Any],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    contract_registry = (
        standard.get("contractRegistry")
        if isinstance(standard.get("contractRegistry"), list)
        else []
    )
    contract_keys = [
        str(item.get("contractKey") or "")
        for item in contract_registry
        if isinstance(item, dict) and item.get("contractKey")
    ]
    iterations = ledger.get("iterations") if isinstance(ledger.get("iterations"), list) else []
    next_action = ledger.get("nextRequiredAction") if isinstance(ledger.get("nextRequiredAction"), dict) else {}
    next_action_status = str(next_action.get("status") or "unknown")
    latest = iterations[-1] if iterations and isinstance(iterations[-1], dict) else {}
    blocking = next_action_status in {"apply-next-mutation", "continue-current-stage"}
    phase_status = (
        "blocked"
        if blocking
        else "needs-action"
        if next_action_status == "awaiting-first-iteration"
        else "pass"
        if next_action_status == "advance-next-gate"
        else "needs-review"
    )
    changed_lever = latest.get("changedLever") if isinstance(latest.get("changedLever"), list) else []
    evidence_paths = latest.get("gateEvidencePaths") if isinstance(latest.get("gateEvidencePaths"), list) else []
    return {
        **gate_system_registry(contract_registry),
        "surface": "quality-loop",
        "status": "blocked" if blocking else phase_status,
        "blockingPhaseKey": "quality-iteration" if blocking else "",
        "phaseStates": [
            _phase_state(
                "quality-iteration",
                phase_status,
                f"nextRequiredAction={next_action_status}, iterations={len(iterations)}",
                source="preproduction/quality-iteration-ledger.json",
                blocking=blocking,
            ),
        ],
        "contractSummary": {
            "requiredContractCount": len(contract_keys),
            "requiredContractKeys": contract_keys,
        },
        "qualityIterationSummary": {
            "iterationCount": len(iterations),
            "nextRequiredActionStatus": next_action_status,
            "nextRequiredActionSummary": str(next_action.get("summary") or ""),
            "latestIterationId": str(latest.get("iterationId") or "") if latest else "",
            "latestStage": str(latest.get("stage") or "") if latest else "",
            "latestStatus": str(latest.get("status") or "") if latest else "",
            "changedLever": [str(item) for item in changed_lever],
            "observedFailure": str(latest.get("observedFailure") or "") if latest else "",
            "nextMutation": latest.get("nextMutation") if isinstance(latest.get("nextMutation"), dict) else {},
            "appliedMutation": latest.get("appliedMutation") if isinstance(latest.get("appliedMutation"), dict) else {},
            "evidencePaths": [str(item) for item in evidence_paths],
            "requiresMutationResolution": next_action_status == "apply-next-mutation",
        },
    }


def build_render_gate_system(checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    items = [
        {"key": key, **(checks.get(key) or {"status": "missing", "detail": "check missing"})}
        for key in RENDER_QUALITY_CHECK_KEYS
    ]
    failed = [item for item in items if item.get("status") in {"fail", "missing"}]
    warned = [item for item in items if item.get("status") == "warn"]
    status = "blocked" if failed else "needs-review" if warned else "pass"
    return {
        **gate_system_registry(),
        "surface": "render-quality-report",
        "status": status,
        "blockingPhaseKey": "render-quality" if failed else "",
        "phaseStates": [
            _phase_state(
                "render-quality",
                status,
                f"failOrMissing={len(failed)}, warn={len(warned)}",
                source="render-quality-report.json",
                blocking=bool(failed),
                checks=items,
            )
        ],
        "renderQualitySummary": {
            "checkCount": len(items),
            "failedOrMissingKeys": [item["key"] for item in failed],
            "warnKeys": [item["key"] for item in warned],
        },
    }


def build_final_readiness_gate_system(goal_readiness: dict[str, Any]) -> dict[str, Any]:
    runway_items = goal_readiness.get("operatingRunwayChecklist")
    runway_items = runway_items if isinstance(runway_items, list) else []
    runway_by_key = {
        str(item.get("key") or ""): item
        for item in runway_items
        if isinstance(item, dict)
    }
    states = []
    for key in FINAL_READINESS_GATE_KEYS:
        item = runway_by_key.get(key) or {}
        status = str(item.get("status") or "missing")
        states.append(_phase_state(
            key,
            status,
            str(item.get("detail") or item.get("operatorAction") or ""),
            source="goalReadiness.operatingRunwayChecklist",
            blocking=status not in {"pass", "ready", "upload", "complete"},
        ))
    broad_status = "pass" if goal_readiness.get("goalComplete") is True else "blocked"
    states.append(_phase_state(
        "broad-operating-goal",
        broad_status,
        str(goal_readiness.get("completionPolicy") or ""),
        source="goalReadiness",
        blocking=broad_status != "pass",
    ))
    blocking = [item for item in states if item.get("blocking")]
    return {
        **gate_system_registry(),
        "surface": "final-video-library",
        "status": "blocked" if blocking else "pass",
        "blockingPhaseKey": str((blocking[0] or {}).get("phaseKey") or "") if blocking else "",
        "phaseStates": states,
        "finalReadinessSummary": {
            "gateCount": len(states),
            "blockingGateKeys": [item["phaseKey"] for item in blocking],
            "goalComplete": goal_readiness.get("goalComplete") is True,
            "preUploadReady": goal_readiness.get("preUploadReady") is True,
        },
    }
