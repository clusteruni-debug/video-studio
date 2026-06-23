"""Scoped active production-packet lock for pre-render safety.

This lock is intentionally narrower than the golden-reference gate. It only
blocks manifests that match the operator's active approval packet scope, so
general smoke renders and unrelated experiments keep working.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from worker.render.longform_minimum_release_gate import evaluate_longform_minimum_release_gate
from worker.render.production_mode_gate import evaluate_production_mode_gate


ACTIVE_PACKET_POINTER_PATH = Path("storage/approval-packets/ACTIVE.json")
LONGFORM_RENDER_DURATION_FLOOR_SEC = 480

PRODUCTION_MODE_PACKET_PATH_KEYS = (
    "productionModePacketPath",
    "production_mode_packet_path",
    "productionModeGatePacketPath",
    "sourcePromptBiblePath",
    "sourcePromptBibleJsonPath",
    "productionPacketPath",
)

PRODUCTION_MODE_PACKET_OBJECT_KEYS = (
    "productionModePacket",
    "productionModeGatePacket",
    "sourcePromptBible",
    "productionPacket",
)

LONGFORM_MINIMUM_RELEASE_PACKET_PATH_KEYS = (
    "longformMinimumReleasePacketPath",
    "longformReleasePacketPath",
    "minimumReleasePacketPath",
    "releaseGatePacketPath",
)

LONGFORM_MINIMUM_RELEASE_PACKET_OBJECT_KEYS = (
    "longformMinimumReleasePacket",
    "longformReleasePacket",
    "minimumReleasePacket",
    "releaseGatePacket",
)


def evaluate_active_production_packet_lock(
    manifest: dict[str, Any],
    *,
    project_root: Path | str = ".",
    manifest_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return a deterministic pre-render lock report for the active packet."""

    root = Path(project_root).resolve()
    pointer_path = root / ACTIVE_PACKET_POINTER_PATH
    report: dict[str, Any] = {
        "schema": "video-studio.active-production-packet-lock.v1",
        "required": False,
        "renderAllowed": True,
        "status": "skipped",
        "activePointerPath": str(pointer_path),
        "packetPath": "",
        "packetId": "",
        "manifestPath": str(Path(manifest_path).resolve()) if manifest_path else "",
        "failedChecks": [],
        "checks": {},
    }

    _apply_longform_production_mode_gate(report, manifest, root)
    if report["renderAllowed"] is False:
        return report
    _apply_longform_minimum_release_gate(report, manifest, root)
    if report["renderAllowed"] is False:
        return report

    if not pointer_path.exists():
        report["checks"]["activePointer"] = _check("pass", "No ACTIVE production packet pointer; lock skipped.")
        if report["required"] is True:
            report["status"] = "pass"
        return report

    active, error = _load_json(pointer_path)
    if error:
        return _fail(report, "activePointer", f"ACTIVE production packet pointer is invalid JSON: {error}")
    if not isinstance(active, dict):
        return _fail(report, "activePointer", "ACTIVE production packet pointer must be a JSON object")

    status = str(active.get("status") or "").strip().lower()
    if status != "active":
        report["checks"]["activeStatus"] = _check("pass", f"ACTIVE production packet status is {status or 'unset'}; lock skipped.")
        if report["required"] is True:
            report["status"] = "pass"
        return report

    matched, match_detail = _manifest_matches_active_scope(manifest, active)
    report["checks"]["scopeMatch"] = _check("pass" if matched else "skip", match_detail)
    if not matched:
        if report["required"] is True:
            report["status"] = "pass"
        return report

    report["required"] = True
    report["status"] = "pass"

    packet_path_value = str(active.get("packetPath") or "").strip()
    if not packet_path_value:
        return _fail(report, "activePacketPath", "ACTIVE production packet needs packetPath")
    packet_path = _resolve_project_path(root, packet_path_value)
    report["packetPath"] = str(packet_path)
    if not packet_path.exists():
        return _fail(report, "activePacketPath", f"ACTIVE production packet file is missing: {packet_path_value}")

    packet, packet_error = _load_json(packet_path)
    if packet_error:
        return _fail(report, "activePacket", f"production packet is invalid JSON: {packet_error}")
    if not isinstance(packet, dict):
        return _fail(report, "activePacket", "production packet must be a JSON object")

    packet_id = str(packet.get("packetId") or active.get("packetId") or "").strip()
    report["packetId"] = packet_id
    if not packet_id:
        return _fail(report, "activePacket", "production packet needs packetId")

    manifest_packet_id = _manifest_approval_packet_id(manifest)
    if manifest_packet_id != packet_id:
        detail = (
            f"manifest approvalPacketId {manifest_packet_id!r} must match active packet {packet_id!r}"
            if manifest_packet_id
            else f"manifest approvalPacketId is required for active packet {packet_id!r}"
        )
        return _fail(report, "approvalPacketBinding", detail)
    report["checks"]["approvalPacketBinding"] = _check("pass", f"manifest is bound to active packet {packet_id}")

    if packet.get("approvedForRender") is not True:
        return _fail(report, "packetApproval", "active production packet approvedForRender must be true before render")
    report["checks"]["packetApproval"] = _check("pass", "active production packet is approved for render")

    return report


def _apply_longform_production_mode_gate(
    report: dict[str, Any],
    manifest: dict[str, Any],
    root: Path,
) -> None:
    required, reason = _manifest_requires_longform_production_mode_gate(manifest)
    if not required:
        report["checks"]["longformProductionModeGate"] = _check("skip", reason)
        return

    report["required"] = True
    report["status"] = "pass"
    packet, packet_path, error = _load_production_mode_packet(manifest, root)
    report["productionModePacketPath"] = str(packet_path) if packet_path else ""
    if error:
        _fail(report, "longformProductionModeGate", error)
        return

    gate_report = evaluate_production_mode_gate(packet)
    report["productionModeGate"] = gate_report
    if gate_report.get("renderAllowed") is False:
        failed = ", ".join(gate_report.get("failedChecks") or [])
        detail = f"{reason}; production mode gate failed: {failed or 'unknown'}"
        _fail(report, "longformProductionModeGate", detail)
        return

    report["checks"]["longformProductionModeGate"] = _check(
        "pass",
        f"{reason}; production mode gate passed for formatProfile={gate_report.get('formatProfile')}",
    )


def _apply_longform_minimum_release_gate(
    report: dict[str, Any],
    manifest: dict[str, Any],
    root: Path,
) -> None:
    required, reason = _manifest_requires_longform_minimum_release_gate(manifest)
    if not required:
        report["checks"]["longformMinimumReleaseGate"] = _check("skip", reason)
        return

    report["required"] = True
    report["status"] = "pass"
    packet, packet_path, error = _load_longform_minimum_release_packet(manifest, root)
    report["longformMinimumReleasePacketPath"] = str(packet_path) if packet_path else ""
    if error:
        _fail(report, "longformMinimumReleaseGate", error)
        return

    gate_report = evaluate_longform_minimum_release_gate(packet)
    report["longformMinimumReleaseGate"] = gate_report
    if gate_report.get("releaseAllowed") is not True:
        failed = ", ".join(gate_report.get("failedChecks") or [])
        detail = f"{reason}; minimum release gate failed: {failed or 'unknown'}"
        _fail(report, "longformMinimumReleaseGate", detail)
        return

    report["checks"]["longformMinimumReleaseGate"] = _check(
        "pass",
        f"{reason}; minimum release gate passed with computedScore={gate_report.get('computedScore')}",
    )


def _manifest_requires_longform_production_mode_gate(manifest: dict[str, Any]) -> tuple[bool, str]:
    profile = str(
        manifest.get("formatProfile")
        or manifest.get("format_profile")
        or manifest.get("productionMode")
        or ""
    ).strip()
    if profile == "longform_10m":
        return True, "formatProfile=longform_10m"

    duration = _manifest_duration_sec(manifest)
    if duration is not None and duration >= LONGFORM_RENDER_DURATION_FLOOR_SEC:
        return True, f"durationSec={duration:g} is longform-range"

    return False, "manifest is not longform-range; production mode gate skipped"


def _manifest_requires_longform_minimum_release_gate(manifest: dict[str, Any]) -> tuple[bool, str]:
    required, longform_reason = _manifest_requires_longform_production_mode_gate(manifest)
    if not required:
        return False, "manifest is not longform-range; minimum release gate skipped"
    if not _manifest_claims_longform_final_release(manifest):
        return False, f"{longform_reason}; no longform final/publish readiness claim"
    return True, f"{longform_reason}; final/publish readiness claim present"


def _load_production_mode_packet(
    manifest: dict[str, Any],
    root: Path,
) -> tuple[dict[str, Any], Path | None, str]:
    packet_path_value = ""
    for key in PRODUCTION_MODE_PACKET_PATH_KEYS:
        packet_path_value = str(manifest.get(key) or "").strip()
        if packet_path_value:
            break
    if packet_path_value:
        raw_packet_path = Path(packet_path_value)
        packet_path = raw_packet_path.resolve() if raw_packet_path.is_absolute() else (root / raw_packet_path).resolve()
        try:
            packet_path.relative_to(root)
        except ValueError:
            return {}, packet_path, f"production mode packet path must stay under project root: {packet_path_value}"
        if not packet_path.exists():
            return {}, packet_path, f"production mode packet file is missing: {packet_path_value}"
        packet, error = _load_json(packet_path)
        if error:
            return {}, packet_path, f"production mode packet is invalid JSON: {error}"
        if not isinstance(packet, dict):
            return {}, packet_path, "production mode packet must be a JSON object"
        return packet, packet_path, ""

    for key in PRODUCTION_MODE_PACKET_OBJECT_KEYS:
        value = manifest.get(key)
        if isinstance(value, dict):
            return value, None, ""

    accepted_keys = ", ".join((*PRODUCTION_MODE_PACKET_PATH_KEYS, *PRODUCTION_MODE_PACKET_OBJECT_KEYS))
    return {}, None, f"longform render requires an explicit production mode packet path/object ({accepted_keys})"


def _load_longform_minimum_release_packet(
    manifest: dict[str, Any],
    root: Path,
) -> tuple[dict[str, Any], Path | None, str]:
    packet_path_value = ""
    for key in LONGFORM_MINIMUM_RELEASE_PACKET_PATH_KEYS:
        packet_path_value = str(manifest.get(key) or "").strip()
        if packet_path_value:
            break
    if packet_path_value:
        raw_packet_path = Path(packet_path_value)
        packet_path = raw_packet_path.resolve() if raw_packet_path.is_absolute() else (root / raw_packet_path).resolve()
        try:
            packet_path.relative_to(root)
        except ValueError:
            return {}, packet_path, f"longform minimum release packet path must stay under project root: {packet_path_value}"
        if not packet_path.exists():
            return {}, packet_path, f"longform minimum release packet file is missing: {packet_path_value}"
        packet, error = _load_json(packet_path)
        if error:
            return {}, packet_path, f"longform minimum release packet is invalid JSON: {error}"
        if not isinstance(packet, dict):
            return {}, packet_path, "longform minimum release packet must be a JSON object"
        return packet, packet_path, ""

    for key in LONGFORM_MINIMUM_RELEASE_PACKET_OBJECT_KEYS:
        value = manifest.get(key)
        if isinstance(value, dict):
            return value, None, ""

    return {}, None, "longform final/publish readiness claims require a longform minimum release packet path/object"


def write_active_production_packet_lock_report(report: dict[str, Any], path: Path | str) -> str:
    """Persist an active-packet lock report and return the written path."""

    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(resolved)


def _manifest_matches_active_scope(manifest: dict[str, Any], active: dict[str, Any]) -> tuple[bool, str]:
    applies_to = active.get("appliesTo") if isinstance(active.get("appliesTo"), dict) else {}
    packet_ids = _string_set([
        active.get("packetId"),
        *(active.get("packetIds") or [] if isinstance(active.get("packetIds"), list) else []),
        *(applies_to.get("approvalPacketIds") or [] if isinstance(applies_to.get("approvalPacketIds"), list) else []),
    ])
    manifest_packet_id = _manifest_approval_packet_id(manifest)
    if manifest_packet_id and manifest_packet_id in packet_ids:
        return True, f"manifest approvalPacketId matches active packet {manifest_packet_id}"

    project_id = str(manifest.get("projectId") or manifest.get("project_id") or "").strip().lower()
    explicit_project_ids = _string_set(applies_to.get("projectIds") or [])
    if project_id and project_id in {item.lower() for item in explicit_project_ids}:
        return True, f"manifest projectId {project_id!r} is explicitly in active packet scope"

    prefixes = [item.lower() for item in _string_list(applies_to.get("projectIdPrefixes"))]
    if project_id and any(project_id.startswith(prefix) for prefix in prefixes):
        return True, f"manifest projectId {project_id!r} matches active packet projectIdPrefixes"

    if applies_to.get("matchReferenceAudiencePair") is True:
        preset = str(manifest.get("referenceStylePreset") or manifest.get("reference_style_preset") or "").strip()
        target = _target_audience(manifest)
        presets = _string_set(applies_to.get("referenceStylePresets") or [])
        audiences = _string_set(applies_to.get("targetAudiences") or [])
        if preset in presets and target in audiences:
            return True, "manifest referenceStylePreset and targetAudience match active packet scope"

    return False, "manifest is outside active production packet scope"


def _manifest_approval_packet_id(manifest: dict[str, Any]) -> str:
    return str(
        manifest.get("approvalPacketId")
        or manifest.get("productionApprovalPacketId")
        or _nested(manifest, "approvalPacket", "packetId")
        or ""
    ).strip()


def _target_audience(manifest: dict[str, Any]) -> str:
    value = manifest.get("targetAudience") or manifest.get("target_audience")
    if isinstance(value, dict):
        value = value.get("segment") or value.get("key") or value.get("id") or value.get("name")
    return str(value or "").strip()


def _manifest_duration_sec(manifest: dict[str, Any]) -> float | None:
    for key in ("durationSec", "duration_sec", "totalDurationSec", "targetDurationSec"):
        value = _number(manifest.get(key))
        if value is not None:
            return value
    scenes = manifest.get("scenes") if isinstance(manifest.get("scenes"), list) else []
    durations = [
        _number(scene.get("durationSec") or scene.get("duration"))
        for scene in scenes
        if isinstance(scene, dict)
    ]
    known = [value for value in durations if value is not None]
    if known:
        return sum(known)
    return None


def _manifest_claims_longform_final_release(manifest: dict[str, Any]) -> bool:
    if manifest.get("finalReadinessClaim") is True or manifest.get("releaseReadinessClaim") is True:
        return True
    if manifest.get("claimsFinalReady") is True or manifest.get("publishReadyClaim") is True:
        return True
    for key, ready_statuses in (
        ("publishReadiness", {"ready"}),
        ("channelReadiness", {"ready", "channel-ready"}),
        ("topTierReadiness", {"ready", "top-tier-ready"}),
    ):
        value = manifest.get(key)
        if isinstance(value, dict):
            status = str(value.get("status") or "").strip().lower()
            if status in ready_statuses:
                return True
    return False


def _resolve_project_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        try:
            path.resolve().relative_to(root)
        except ValueError:
            return root / "__outside_project__"
        return path.resolve()
    return (root / path).resolve()


def _load_json(path: Path) -> tuple[Any, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except Exception as exc:  # pragma: no cover - exact JSON errors vary by Python minor version.
        return None, str(exc)


def _fail(report: dict[str, Any], key: str, detail: str) -> dict[str, Any]:
    report["required"] = True
    report["renderAllowed"] = False
    report["status"] = "fail"
    report.setdefault("checks", {})[key] = _check("fail", detail)
    failed = report.setdefault("failedChecks", [])
    if key not in failed:
        failed.append(key)
    return report


def _check(status: str, detail: str) -> dict[str, str]:
    return {"status": status, "detail": detail}


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _string_set(value: Any) -> set[str]:
    return {item for item in _string_list(value) if item}


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
