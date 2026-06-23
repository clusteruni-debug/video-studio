"""Longform dry-run readiness preflight.

This module composes the existing longform gates into one final preflight for
the operator-visible dry run. It intentionally re-evaluates packet objects
instead of trusting summary flags from previous reports.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from worker.render.longform_minimum_release_gate import evaluate_longform_minimum_release_gate
from worker.render.longform_workflow_gate import evaluate_longform_workflow_gate
from worker.render.production_mode_gate import evaluate_production_mode_gate
from worker.render.production_packet_lock import evaluate_active_production_packet_lock
from worker.render.topic_discovery_gate import evaluate_topic_discovery_gate


LONGFORM_DRYRUN_READINESS_GATE_KEYS = (
    "dryrunTopicDiscoveryGate",
    "dryrunWorkflowGate",
    "dryrunProductionModeGate",
    "dryrunRenderPreflightGate",
    "dryrunMinimumReleaseGate",
    "dryrunFinalLibraryGate",
)

FINAL_TARGET_STAGES = {
    "final",
    "final-readiness",
    "publish",
    "upload",
    "channel-ready",
    "top-tier",
    "release",
    "operator-upload",
}


def evaluate_longform_dryrun_readiness(
    packet: dict[str, Any],
    *,
    project_root: Path | str = ".",
    manifest_path: Path | str | None = None,
) -> dict[str, Any]:
    """Evaluate whether a longform packet may enter a real dry-run/E2E pass."""

    manifest = _object_from(packet, "renderManifest", "manifest")
    requires_final = _requires_final_release(packet, manifest)
    report: dict[str, Any] = {
        "schema": "video-studio.longform-dryrun-readiness.v1",
        "status": "pass",
        "targetStage": _target_stage(packet),
        "generationAllowed": False,
        "renderAllowed": False,
        "finalAllowed": False,
        "dryrunAllowed": False,
        "minimumReleaseRequired": requires_final,
        "finalLibraryRequired": requires_final,
        "failedChecks": [],
        "checks": {},
    }

    topic_report = _evaluate_topic_discovery_gate(packet, report)
    workflow_report = _evaluate_workflow_gate(packet, report)
    production_report = _evaluate_production_mode_gate(packet, report)
    render_report = _evaluate_render_preflight_gate(packet, report, project_root, manifest_path)
    minimum_report = _evaluate_minimum_release_gate(packet, report, manifest, requires_final)
    final_library_report = _evaluate_final_library_gate(packet, report, requires_final)

    report["topicDiscoveryGate"] = topic_report
    report["workflowGate"] = workflow_report
    report["productionModeGate"] = production_report
    report["renderPreflightGate"] = render_report
    report["minimumReleaseGate"] = minimum_report
    report["finalLibraryGate"] = final_library_report

    topic_ok = _check_passed(report, "dryrunTopicDiscoveryGate")
    workflow_ok = _check_passed(report, "dryrunWorkflowGate")
    production_ok = _check_passed(report, "dryrunProductionModeGate")
    render_ok = _check_passed(report, "dryrunRenderPreflightGate")
    minimum_ok = _check_passed(report, "dryrunMinimumReleaseGate")
    final_library_ok = _check_passed(report, "dryrunFinalLibraryGate")

    report["generationAllowed"] = bool(
        topic_ok
        and workflow_report.get("generationAllowed") is True
        and workflow_ok
    )
    report["renderAllowed"] = bool(
        topic_ok
        and workflow_report.get("renderAllowed") is True
        and workflow_ok
        and production_ok
        and render_ok
    )
    report["finalAllowed"] = bool(
        report["renderAllowed"]
        and workflow_report.get("finalAllowed") is True
        and minimum_ok
        and final_library_ok
    )
    report["dryrunAllowed"] = bool(
        topic_ok
        and workflow_ok
        and production_ok
        and render_ok
        and (not requires_final or (minimum_ok and final_library_ok))
    )
    if report["failedChecks"]:
        report["status"] = "fail"
    return report


def _evaluate_topic_discovery_gate(packet: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    topic_packet = _object_from(
        packet,
        "topicDiscoveryPacket",
        "topicDiscoveryGatePacket",
        "topicPacket",
        "topicResearchPacket",
    )
    if not topic_packet:
        return _fail(report, "dryrunTopicDiscoveryGate", "topicDiscoveryPacket object is required before longform dry-run.")

    gate_report = evaluate_topic_discovery_gate(topic_packet)
    if gate_report.get("topicReady") is not True:
        failed = ", ".join(gate_report.get("failedChecks") or [])
        _fail(report, "dryrunTopicDiscoveryGate", f"topic discovery gate failed: {failed or 'unknown'}")
        return gate_report
    report["checks"]["dryrunTopicDiscoveryGate"] = _check(
        "pass",
        f"topic discovery gate passed for selectedTopicId={gate_report.get('selectedTopicId')}.",
    )
    return gate_report


def _evaluate_workflow_gate(packet: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    workflow_packet = _object_from(
        packet,
        "workflowPacket",
        "workflowStagePacket",
        "longformWorkflowPacket",
        "workflowGatePacket",
    )
    if not workflow_packet:
        return _fail(report, "dryrunWorkflowGate", "workflowPacket object is required before dry-run.")

    gate_report = evaluate_longform_workflow_gate(workflow_packet)
    if gate_report.get("status") != "pass":
        failed = ", ".join(gate_report.get("failedChecks") or [])
        _fail(report, "dryrunWorkflowGate", f"workflow gate failed: {failed or 'unknown'}")
        return gate_report
    report["checks"]["dryrunWorkflowGate"] = _check("pass", "workflow gate passed from source generation through final stages.")
    return gate_report


def _evaluate_production_mode_gate(packet: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    production_packet = _object_from(
        packet,
        "productionModePacket",
        "productionModeGatePacket",
        "sourcePromptBible",
        "productionPacket",
    )
    if not production_packet:
        return _fail(report, "dryrunProductionModeGate", "productionModePacket object is required before dry-run.")

    gate_report = evaluate_production_mode_gate(production_packet)
    if gate_report.get("renderAllowed") is not True:
        failed = ", ".join(gate_report.get("failedChecks") or [])
        _fail(report, "dryrunProductionModeGate", f"production mode gate failed: {failed or 'unknown'}")
        return gate_report
    report["checks"]["dryrunProductionModeGate"] = _check("pass", "production mode gate passed for the dry-run packet.")
    return gate_report


def _evaluate_render_preflight_gate(
    packet: dict[str, Any],
    report: dict[str, Any],
    project_root: Path | str,
    manifest_path: Path | str | None,
) -> dict[str, Any]:
    manifest = _object_from(packet, "renderManifest", "manifest")
    if not manifest:
        return _fail(report, "dryrunRenderPreflightGate", "renderManifest object is required before dry-run.")

    gate_report = evaluate_active_production_packet_lock(
        manifest,
        project_root=project_root,
        manifest_path=manifest_path,
    )
    if gate_report.get("renderAllowed") is not True:
        failed = ", ".join(gate_report.get("failedChecks") or [])
        _fail(report, "dryrunRenderPreflightGate", f"render preflight failed: {failed or 'unknown'}")
        return gate_report
    report["checks"]["dryrunRenderPreflightGate"] = _check(
        "pass",
        "render manifest passed active production packet and longform pre-render locks.",
    )
    return gate_report


def _evaluate_minimum_release_gate(
    packet: dict[str, Any],
    report: dict[str, Any],
    manifest: dict[str, Any],
    required: bool,
) -> dict[str, Any]:
    if not required:
        skipped = _check("skip", "target stage is not final/publish; minimum release gate skipped.")
        report["checks"]["dryrunMinimumReleaseGate"] = skipped
        return skipped

    release_packet = _object_from(
        packet,
        "longformMinimumReleasePacket",
        "longformReleasePacket",
        "minimumReleasePacket",
        "releaseGatePacket",
    ) or _object_from(
        manifest,
        "longformMinimumReleasePacket",
        "longformReleasePacket",
        "minimumReleasePacket",
        "releaseGatePacket",
    )
    if not release_packet:
        return _fail(
            report,
            "dryrunMinimumReleaseGate",
            "final/publish dry-run requires a longform minimum release packet object.",
        )

    gate_report = evaluate_longform_minimum_release_gate(release_packet)
    if gate_report.get("releaseAllowed") is not True:
        failed = ", ".join(gate_report.get("failedChecks") or [])
        _fail(report, "dryrunMinimumReleaseGate", f"minimum release gate failed: {failed or 'unknown'}")
        return gate_report
    report["checks"]["dryrunMinimumReleaseGate"] = _check(
        "pass",
        f"minimum release gate passed with computedScore={gate_report.get('computedScore')}.",
    )
    return gate_report


def _evaluate_final_library_gate(packet: dict[str, Any], report: dict[str, Any], required: bool) -> dict[str, Any]:
    if not required:
        skipped = _check("skip", "target stage is not final/publish; final-library gate skipped.")
        report["checks"]["dryrunFinalLibraryGate"] = skipped
        return skipped

    audit = _object_from(
        packet,
        "finalLibraryAudit",
        "finalVideoLibraryAudit",
        "finalLibraryPacket",
        "finalLibraryReport",
    )
    if not audit:
        return _fail(report, "dryrunFinalLibraryGate", "finalLibraryAudit object is required before final dry-run.")

    summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    longform_release = audit.get("longformMinimumRelease") if isinstance(audit.get("longformMinimumRelease"), dict) else {}
    release_ready = (
        summary.get("longformMinimumReleaseReady") is True
        and str(summary.get("longformMinimumReleaseStatus") or "").strip().lower() == "pass"
    ) or (
        longform_release.get("ready") is True
        and str(longform_release.get("status") or "").strip().lower() == "pass"
    )
    publish_flags = [
        key
        for key in ("uploadReady", "channelReady", "topTierReady", "publishPacketContentReady")
        if summary.get(key) is True
    ]
    if not release_ready:
        suffix = f" Self-asserted publish flags present: {', '.join(publish_flags)}." if publish_flags else ""
        _fail(
            report,
            "dryrunFinalLibraryGate",
            "final-library audit must show longformMinimumReleaseReady=true and status=pass." + suffix,
        )
        return audit

    if summary.get("publishPacketContentReady") is False:
        _fail(report, "dryrunFinalLibraryGate", "publish packet content is not ready in final-library audit.")
        return audit
    if summary.get("uploadReady") is False:
        _fail(report, "dryrunFinalLibraryGate", "uploadReady=false in final-library audit.")
        return audit

    report["checks"]["dryrunFinalLibraryGate"] = _check(
        "pass",
        "final-library audit passed with longform minimum release evidence.",
    )
    return audit


def _requires_final_release(packet: dict[str, Any], manifest: dict[str, Any]) -> bool:
    target_stage = _target_stage(packet)
    if target_stage in FINAL_TARGET_STAGES:
        return True
    return _claims_final_release(packet) or _claims_final_release(manifest)


def _target_stage(packet: dict[str, Any]) -> str:
    return str(
        packet.get("targetStage")
        or packet.get("target_stage")
        or packet.get("dryrunTargetStage")
        or packet.get("stage")
        or "render"
    ).strip().lower()


def _claims_final_release(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in (
        "claimFinalReady",
        "finalReadinessClaim",
        "releaseReadinessClaim",
        "claimsFinalReady",
        "publishReadyClaim",
    ):
        if payload.get(key) is True:
            return True
    for key, ready_statuses in (
        ("publishReadiness", {"ready"}),
        ("channelReadiness", {"ready", "channel-ready"}),
        ("topTierReadiness", {"ready", "top-tier-ready"}),
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            status = str(value.get("status") or "").strip().lower()
            if status in ready_statuses:
                return True
    return False


def _object_from(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _check_passed(report: dict[str, Any], key: str) -> bool:
    check = report.get("checks", {}).get(key)
    return isinstance(check, dict) and check.get("status") in {"pass", "skip"}


def _fail(report: dict[str, Any], key: str, detail: str) -> dict[str, Any]:
    report.setdefault("checks", {})[key] = _check("fail", detail)
    failed = report.setdefault("failedChecks", [])
    if key not in failed:
        failed.append(key)
    return {"status": "fail", "detail": detail, "failedChecks": [key]}


def _check(status: str, detail: str) -> dict[str, str]:
    return {"status": status, "detail": detail}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"preflight packet must be a JSON object: {path}")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a longform dry-run readiness packet.")
    parser.add_argument("packet", type=Path, help="Path to a longform dry-run readiness packet JSON.")
    parser.add_argument("--project-root", type=Path, default=Path("."), help="Project root for render preflight paths.")
    parser.add_argument("--manifest-path", type=Path, default=None, help="Optional render manifest path label.")
    args = parser.parse_args(argv)

    report = evaluate_longform_dryrun_readiness(
        _load_json(args.packet),
        project_root=args.project_root,
        manifest_path=args.manifest_path,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("dryrunAllowed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
