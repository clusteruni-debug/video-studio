from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, jsonify, request

from worker.bridge.auto_studio import (
    build_asset_provider_registry,
    import_auto_studio_asset,
    load_latest_auto_studio,
    run_auto_studio,
    update_handoff_task_status,
)

logger = logging.getLogger(__name__)

auto_studio_bp = Blueprint("auto_studio", __name__)
PROJECT_ROOT = Path.cwd()


def init_auto_studio_routes(project_root: str | Path) -> None:
    global PROJECT_ROOT
    PROJECT_ROOT = Path(project_root).resolve()


@auto_studio_bp.route("/api/auto-studio/providers", methods=["GET"])
def auto_studio_providers_route():
    return jsonify(build_asset_provider_registry(PROJECT_ROOT))


@auto_studio_bp.route("/api/auto-studio/latest", methods=["GET"])
def auto_studio_latest_route():
    payload = load_latest_auto_studio(PROJECT_ROOT)
    status = 200 if payload.get("ok") else 500
    return jsonify(payload), status


@auto_studio_bp.route("/api/auto-studio/status", methods=["GET"])
def auto_studio_status_route():
    payload = load_latest_auto_studio(PROJECT_ROOT)
    if not payload.get("ok"):
        return jsonify(payload), 500
    run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
    return jsonify(
        {
            "ok": True,
            "schema": "video-studio.auto-studio.status.v1",
            "hasRun": bool(run),
            "runId": run.get("runId"),
            "status": run.get("status") if run else "idle",
            "selectedCandidate": run.get("selectedCandidate") if run else None,
            "assetPipeline": run.get("assetPipeline") if run else None,
            "nextActions": run.get("nextActions") if run else ["Run /api/auto-studio/run to create a draft."],
            "latest": payload.get("latest"),
        }
    )


@auto_studio_bp.route("/api/auto-studio/run", methods=["POST"])
def auto_studio_run_route():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = run_auto_studio(payload, PROJECT_ROOT)
    except Exception as exc:
        logger.warning("auto_studio_run_route failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify(result)


@auto_studio_bp.route("/api/auto-studio/handoff-task", methods=["POST"])
def auto_studio_handoff_task_route():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    result = update_handoff_task_status(payload, PROJECT_ROOT)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@auto_studio_bp.route("/api/auto-studio/import-asset", methods=["POST"])
def auto_studio_import_asset_route():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    result = import_auto_studio_asset(payload, PROJECT_ROOT)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status
