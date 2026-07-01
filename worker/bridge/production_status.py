from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import json

from worker.bridge.material_dryrun import latest_material_dryrun_summary
from worker.bridge.material_library import library_stats, load_material_library, material_summary
from worker.bridge.thin_production_loop import build_thin_loop_status
from worker.render.production_gate_orchestrator import evaluate_production_gates


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_APPROVAL_PACKET_PATH = PROJECT_ROOT / "storage" / "approval-packets" / "ACTIVE.json"
SCHEMA = "video-studio.production-status-readmodel.v1"

STAGE_TAB = {
    "material-intake": "topic",
    "source-ledger": "topic",
    "topic-discovery": "topic",
    "storyboard": "plan",
    "source-acquisition": "sources",
    "prompt-quality": "plan",
    "asset-import-review": "sources",
    "edit-assembly": "edit",
    "render-preflight": "edit",
    "quality-review": "review",
    "publish-readiness": "review",
    "post-publish-learning": "advanced",
}


def _now_kst() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _latest_material(materials: list[dict[str, Any]]) -> dict[str, Any]:
    def key(material: dict[str, Any]) -> str:
        return _text(material.get("updatedAt")) or _text(material.get("createdAt"))

    return sorted(materials, key=key, reverse=True)[0] if materials else {}


def _active_packet_summary(path: Path | None = None) -> dict[str, Any]:
    packet = _read_json(path or ACTIVE_APPROVAL_PACKET_PATH)
    if not packet:
        return {"available": False}

    next_required = _as_dict(packet.get("nextRequiredAction"))
    capcut = _as_dict(packet.get("capcut") or packet.get("capCut"))
    status = _text(packet.get("status")) or "unknown"
    next_status = _text(next_required.get("status"))
    capcut_required = packet.get("capcutHandoffRequired") is True
    ffmpeg_only_allowed = packet.get("ffmpegOnlyFinalAllowed") is True
    capcut_exported = bool(
        packet.get("capcutExportPath")
        or packet.get("capcutExportedMp4")
        or capcut.get("exportPath")
        or capcut.get("exportedMp4")
    )
    blocked = status == "active" and capcut_required and not ffmpeg_only_allowed and not capcut_exported
    if "blocked" in next_status:
        blocked = True

    return {
        "available": True,
        "packetId": packet.get("packetId") or packet.get("id"),
        "taskId": packet.get("taskId"),
        "status": status,
        "nextRequiredAction": next_required,
        "capcutHandoffRequired": capcut_required,
        "ffmpegOnlyFinalAllowed": ffmpeg_only_allowed,
        "capcutExported": capcut_exported,
        "blocked": blocked,
        "previewPath": packet.get("previewPath") or packet.get("ffmpegPreviewPath") or packet.get("latestPreviewPath"),
    }


def _counts(stages: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(stages),
        "pass": sum(1 for stage in stages if stage.get("status") == "pass"),
        "pending": sum(1 for stage in stages if stage.get("status") == "pending"),
        "blocked": sum(1 for stage in stages if stage.get("status") == "blocked"),
    }


def _gate_next_action(gate_report: dict[str, Any]) -> dict[str, Any]:
    current_stage = _text(gate_report.get("currentStage")) or "material-intake"
    current = next(
        (stage for stage in _as_list(gate_report.get("stages")) if isinstance(stage, dict) and stage.get("stage") == current_stage),
        {},
    )
    return {
        "status": _text(current.get("status")) or _text(gate_report.get("overallStatus")) or "blocked",
        "stage": current_stage,
        "label": _text(current.get("label")) or current_stage,
        "message": _text(current.get("nextAction")) or _text(gate_report.get("nextAction")),
        "detail": _text(current.get("detail")),
        "tab": STAGE_TAB.get(current_stage, "home"),
        "source": "production-gates",
    }


def _active_packet_action(active_packet: dict[str, Any]) -> dict[str, Any]:
    next_required = _as_dict(active_packet.get("nextRequiredAction"))
    status = _text(next_required.get("status")) or "capcut-export-blocked"
    return {
        "status": "blocked",
        "stage": "asset-import-review",
        "label": "CapCut export blocker",
        "message": _text(next_required.get("operatorAction"))
        or _text(next_required.get("message"))
        or "CapCut draft는 있지만 CapCut-exported MP4 proof가 없습니다.",
        "detail": status,
        "tab": "review",
        "source": "active-approval-packet",
    }


def build_production_status(*, active_packet_path: Path | None = None) -> dict[str, Any]:
    library = load_material_library()
    materials = [item for item in _as_list(library.get("materials")) if isinstance(item, dict)]
    latest_material = _latest_material(materials)
    summaries = [material_summary(item) for item in materials]
    dryrun = latest_material_dryrun_summary()
    active_packet = _active_packet_summary(active_packet_path)
    gate_report = evaluate_production_gates(latest_material) if latest_material else {}
    thin_loop = build_thin_loop_status({"material": latest_material, "dryrunPreflight": dryrun})
    stages = [stage for stage in _as_list(gate_report.get("stages")) if isinstance(stage, dict)]
    next_action = _active_packet_action(active_packet) if active_packet.get("blocked") else _gate_next_action(gate_report)

    if not latest_material:
        next_action = {
            "status": "blocked",
            "stage": "material-intake",
            "label": "소재 입력",
            "message": "먼저 소재 탭에서 후보를 찾고 sourceLedger를 저장하세요.",
            "detail": "material-library-empty",
            "tab": "topic",
            "source": "material-library",
        }

    return {
        "ok": True,
        "schema": SCHEMA,
        "generatedAt": _now_kst(),
        "truthSource": "server-production-readmodel",
        "materialLibrary": {
            "schema": library.get("schema"),
            "stats": library_stats(materials),
            "latest": material_summary(latest_material) if latest_material else None,
            "summaries": summaries,
        },
        "dryrunPreflight": dryrun,
        "activePacket": active_packet,
        "gateReport": gate_report or None,
        "thinLoop": thin_loop,
        "workflowGates": stages,
        "counts": _counts(stages),
        "nextAction": next_action,
    }
