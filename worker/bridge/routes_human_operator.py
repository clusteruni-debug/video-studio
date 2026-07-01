from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request as flask_request

from worker.bridge.human_operator_mvp import (
    build_adapter_command_readiness,
    build_human_mode_worklist,
    build_operator_blockers,
    build_phone_review_status,
    build_provider_readiness,
    build_publish_packet,
    build_render_health,
    build_source_workflow_status,
    run_demo_render,
    save_phone_review,
    save_source_review,
)
from worker.media.provider_policy import paid_providers_allowed
from worker.runtime.tools import probe_tool


human_operator_bp = Blueprint("human_operator", __name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_PROJECT_ID = "human-operator-local-demo-p0"
DEMO_SCHEMA = "video-studio.human-operator-demo.v1"
STATUS_SCHEMA = "video-studio.human-operator-status.v1"


def init_human_operator_routes(project_root: Path | str) -> None:
    global PROJECT_ROOT
    PROJECT_ROOT = Path(project_root).resolve()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_status(ready: bool, *, optional: bool = False) -> str:
    if ready:
        return "ready"
    return "optional-missing" if optional else "missing"


def _command_probe(command: str) -> dict[str, Any]:
    path = shutil.which(command)
    if not path:
        return {
            "name": command,
            "ready": False,
            "path": None,
            "version": None,
            "detail": "not found on PATH",
        }
    try:
        completed = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "name": command,
            "ready": False,
            "path": path,
            "version": None,
            "detail": str(exc),
        }
    output = (completed.stdout or completed.stderr or "").strip()
    return {
        "name": command,
        "ready": completed.returncode == 0,
        "path": path,
        "version": output.splitlines()[0].strip() if output else None,
        "detail": "ok" if completed.returncode == 0 else f"probe exited {completed.returncode}",
    }


def _path_check(path: Path, *, key: str, label: str, required: bool = True) -> dict[str, Any]:
    exists = path.exists()
    writable = exists and os.access(path, os.W_OK)
    ready = exists and (writable if path.is_dir() else True)
    return {
        "key": key,
        "label": label,
        "status": _as_status(ready, optional=not required),
        "ready": ready,
        "required": required,
        "detail": str(path),
        "repairAction": (
            "Create the folder or fix write permissions."
            if not ready and path.is_dir()
            else "Confirm the path exists."
        ),
    }


def _tool_check(key: str, label: str, probe: dict[str, Any], *, required: bool = True) -> dict[str, Any]:
    ready = bool(probe.get("ready"))
    return {
        "key": key,
        "label": label,
        "status": _as_status(ready, optional=not required),
        "ready": ready,
        "required": required,
        "detail": probe.get("version") or probe.get("detail") or "not checked",
        "path": probe.get("path") or probe.get("resolvedPath"),
        "repairAction": "Install or expose this tool to the shell that starts Video Studio.",
    }


def _provider_state(key: str, label: str, *, category: str, ready: bool, state: str, detail: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "category": category,
        "state": "ready" if ready else state,
        "ready": ready,
        "detail": detail,
    }


def build_setup_status(project_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(project_root or PROJECT_ROOT).resolve()
    storage_dir = root / "storage"
    ffmpeg = probe_tool("ffmpeg", project_root=root).to_dict()
    node = _command_probe("node")
    npm = _command_probe("npm")
    python_ready = bool(sys.executable)

    checks = [
        {
            "key": "python",
            "label": "Python",
            "status": "ready" if python_ready else "missing",
            "ready": python_ready,
            "required": True,
            "detail": sys.version.split()[0] if python_ready else "python executable not resolved",
            "path": sys.executable if python_ready else None,
            "repairAction": "Install Python and run the bridge from the project environment.",
        },
        _tool_check("node", "Node.js", node),
        _tool_check("npm", "npm", npm),
        _tool_check("ffmpeg", "FFmpeg", ffmpeg),
        _path_check(root, key="project-root", label="Project root"),
        _path_check(storage_dir, key="storage", label="Writable storage folder"),
    ]

    optional_keys = [
        ("GEMINI_API_KEY", "Gemini", "planning/image"),
        ("PEXELS_API_KEY", "Pexels", "stock"),
        ("KLIPY_API_KEY", "Klipy", "stock"),
        ("FREESOUND_API_KEY", "Freesound", "sfx"),
    ]
    providers = [
        _provider_state(
            "demo-template",
            "No-LLM template planner",
            category="planning",
            ready=True,
            state="ready",
            detail="bundled deterministic demo path",
        ),
        _provider_state(
            "local-title-card-render",
            "Local title-card render fallback",
            category="render",
            ready=bool(ffmpeg.get("ready")),
            state="config-required",
            detail="requires FFmpeg only; no external provider account",
        ),
    ]
    for env_name, label, category in optional_keys:
        ready = bool(os.environ.get(env_name, "").strip())
        providers.append(
            _provider_state(
                env_name.lower(),
                label,
                category=category,
                ready=ready,
                state="config-required",
                detail=f"optional env var {env_name}",
            )
        )
    paid_allowed = paid_providers_allowed()
    providers.append(
        _provider_state(
            "paid-providers",
            "Paid providers",
            category="policy",
            ready=paid_allowed,
            state="blocked",
            detail="blocked unless VIDEO_STUDIO_ALLOW_PAID_PROVIDERS=1",
        )
    )

    blocking = [check for check in checks if check["required"] and not check["ready"]]
    return {
        "ok": True,
        "schema": "video-studio.human-operator-setup-status.v1",
        "generatedAt": _now_iso(),
        "mode": "human-operator",
        "criticalReady": not blocking,
        "demoModeReady": not blocking and bool(ffmpeg.get("ready")),
        "blockingChecks": [item["key"] for item in blocking],
        "checks": checks,
        "providerMatrix": providers,
        "nextAction": (
            {
                "status": "ready",
                "label": "No-LLM demo can be prepared",
                "message": "Create the bundled demo packet, then run the existing render-smoke path when ready.",
                "tab": "home",
            }
            if not blocking
            else {
                "status": "blocked",
                "label": "Fix first-run setup",
                "message": f"{blocking[0]['label']} is missing or unavailable.",
                "detail": blocking[0]["repairAction"],
                "tab": "home",
            }
        ),
    }


def _demo_dir(project_root: Path | str | None = None) -> Path:
    return Path(project_root or PROJECT_ROOT).resolve() / "storage" / "human-operator-demo" / DEMO_PROJECT_ID


def _demo_scenes() -> list[dict[str, Any]]:
    return [
        {
            "scene_num": 1,
            "sceneId": "scene-01",
            "display_text": "No-LLM demo",
            "narration": "This local demo proves the editing path without any AI account.",
            "subtitleText": "No-LLM local demo",
            "narrationText": "This local demo proves the editing path without any AI account.",
            "duration": 5,
            "image_prompt": "clean vertical title card showing a local video production checklist",
            "visualKind": "image",
            "image_source": "title-card",
            "source_rationale": "Bundled title-card fallback; no provider account required.",
            "continuity_note": "Introduces the demo proof path.",
        },
        {
            "scene_num": 2,
            "sceneId": "scene-02",
            "display_text": "Local tools only",
            "narration": "The bridge checks Python, Node, storage, and FFmpeg before a render.",
            "subtitleText": "Local tools only",
            "narrationText": "The bridge checks Python, Node, storage, and FFmpeg before a render.",
            "duration": 5,
            "image_prompt": "vertical checklist of python node storage and ffmpeg",
            "visualKind": "image",
            "image_source": "title-card",
            "source_rationale": "Local status card generated by the render fallback.",
            "continuity_note": "Shows the first-run setup boundary.",
        },
        {
            "scene_num": 3,
            "sceneId": "scene-03",
            "display_text": "Ready for manual sources",
            "narration": "After the demo works, add operator-owned video files and review them before publish.",
            "subtitleText": "Add local sources next",
            "narrationText": "After the demo works, add operator-owned video files and review them before publish.",
            "duration": 5,
            "image_prompt": "vertical upload folder and phone review checklist",
            "visualKind": "image",
            "image_source": "title-card",
            "source_rationale": "Explains manual source proof without browser automation.",
            "continuity_note": "Ends with the next human-owned production step.",
        },
    ]


def _demo_payload() -> dict[str, Any]:
    return {
        "prompt": "No-LLM local demo for Video Studio human operator mode",
        "budgetMode": "free",
        "plannerMode": "sample",
        "projectId": DEMO_PROJECT_ID,
        "templateType": "news_explainer",
        "bgmEnabled": True,
        "draftScenes": _demo_scenes(),
        "providerOverrides": {},
        "selectedPexelsVideos": {},
        "sceneAssets": [],
        "humanMode": {
            "mode": "Demo Mode",
            "requiresExternalAi": False,
            "requiresPaidProvider": False,
            "requiresBrowserHandoff": False,
        },
    }


def build_demo_status(project_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(project_root or PROJECT_ROOT).resolve()
    demo_dir = _demo_dir(root)
    summary_path = demo_dir / "summary.json"
    payload_path = demo_dir / "render-smoke-payload.json"
    prepared = summary_path.exists() and payload_path.exists()
    return {
        "ok": True,
        "schema": DEMO_SCHEMA,
        "projectId": DEMO_PROJECT_ID,
        "prepared": prepared,
        "demoDir": str(demo_dir),
        "summaryPath": str(summary_path) if prepared else "",
        "renderSmokePayloadPath": str(payload_path) if prepared else "",
        "renderEndpoint": "/api/render-smoke",
        "requiresExternalAi": False,
        "requiresPaidProvider": False,
        "requiresBrowserHandoff": False,
        "nextAction": (
            "Run render-smoke with the prepared payload when FFmpeg is ready."
            if prepared
            else "Prepare the bundled no-LLM demo packet."
        ),
    }


def prepare_demo_packet(project_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(project_root or PROJECT_ROOT).resolve()
    demo_dir = _demo_dir(root)
    demo_dir.mkdir(parents=True, exist_ok=True)
    payload = _demo_payload()
    material = {
        "schema": "video-studio.human-demo-material.v1",
        "projectId": DEMO_PROJECT_ID,
        "title": "No-LLM local demo",
        "centralQuestion": "Can a new operator prove Video Studio runs without any AI account?",
        "sourceLedger": [
            {
                "sourceId": "local-demo-contract",
                "sourceType": "bundled-demo",
                "title": "Bundled deterministic demo packet",
                "url": "local://video-studio/human-operator-demo",
                "capturedAt": _now_iso(),
                "observation": "This is a deterministic local demo path; it is not publish evidence.",
            }
        ],
    }
    summary = {
        "ok": True,
        "schema": DEMO_SCHEMA,
        "projectId": DEMO_PROJECT_ID,
        "preparedAt": _now_iso(),
        "mode": "Demo Mode",
        "sceneCount": len(payload["draftScenes"]),
        "renderEndpoint": "/api/render-smoke",
        "renderSmokePayloadPath": str(demo_dir / "render-smoke-payload.json"),
        "materialPath": str(demo_dir / "material.json"),
        "releaseBoundary": "Demo draft only; phone review and publish packet remain required before upload claims.",
    }
    (demo_dir / "material.json").write_text(json.dumps(material, ensure_ascii=False, indent=2), encoding="utf-8")
    (demo_dir / "render-smoke-payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (demo_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**build_demo_status(root), "summary": summary, "renderSmokePayload": payload}


def build_human_operator_status(project_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(project_root or PROJECT_ROOT).resolve()
    setup = build_setup_status(root)
    demo = build_demo_status(root)
    provider_readiness = build_provider_readiness(root, setup)
    source_workflow = build_source_workflow_status(root)
    render_health = build_render_health(root, setup)
    phone_review = build_phone_review_status(root)
    publish_packet = build_publish_packet(root)
    operator_blockers = build_operator_blockers(root)
    adapter_readiness = build_adapter_command_readiness(root)
    worklist = build_human_mode_worklist(root)
    if not setup["criticalReady"]:
        next_action = setup["nextAction"]
    elif not demo["prepared"]:
        next_action = {
            "status": "pending",
            "label": "Prepare no-LLM demo",
            "message": "Create the bundled demo packet before external providers or browser handoffs.",
            "tab": "home",
        }
    elif render_health["status"] != "ready":
        next_action = {
            "status": "ready",
            "label": "Run no-LLM demo render",
            "message": "Render the prepared demo packet locally, then review the result on a phone viewport.",
            "tab": "edit",
        }
    elif source_workflow["acceptedCount"] <= 0:
        next_action = {
            "status": "pending",
            "label": "Accept local source proof",
            "message": "Mark at least one operator-owned local source as accepted before production claims.",
            "tab": "sources",
        }
    elif phone_review["status"] != "pass":
        next_action = {
            "status": "pending",
            "label": "Record phone review",
            "message": "Publish readiness stays blocked until full-watch phone review evidence is accepted.",
            "tab": "review",
        }
    else:
        next_action = {
            "status": "ready",
            "label": "Inspect publish packet",
            "message": "Review title, description, disclosure, source proof, render proof, and upload blockers.",
            "tab": "review",
        }
    return {
        "ok": True,
        "schema": STATUS_SCHEMA,
        "generatedAt": _now_iso(),
        "setup": setup,
        "demo": demo,
        "providerReadiness": provider_readiness,
        "adapterCommandReadiness": adapter_readiness,
        "sourceWorkflow": source_workflow,
        "phoneReview": phone_review,
        "publishPacket": {
            "uploadAllowed": publish_packet["uploadAllowed"],
            "blockers": publish_packet["blockers"],
            "decision": publish_packet["decision"],
        },
        "operatorBlockers": operator_blockers,
        "worklist": {
            "counts": worklist["counts"],
            "releaseBoundary": worklist["releaseBoundary"],
        },
        "localSourceWorkflow": {
            "status": source_workflow["status"],
            "label": "Local upload source proof",
            "message": source_workflow["nextAction"],
            "repairAction": "Open Sources, upload a local MP4/image, then review it before render.",
        },
        "renderHealth": {
            "status": render_health["status"],
            "label": "Render health",
            "message": render_health["nextAction"],
            "failureCategory": render_health["failureCategory"],
            "outputPath": render_health["outputPath"],
            "logPath": render_health["logPath"],
            "ffmpeg": next((item for item in setup["checks"] if item["key"] == "ffmpeg"), {}),
        },
        "nextAction": next_action,
    }


@human_operator_bp.route("/api/human-operator/setup-status", methods=["GET"])
def human_operator_setup_status_route():
    return jsonify(build_setup_status())


@human_operator_bp.route("/api/human-operator/demo/status", methods=["GET"])
def human_operator_demo_status_route():
    return jsonify(build_demo_status())


@human_operator_bp.route("/api/human-operator/demo/prepare", methods=["POST"])
def human_operator_demo_prepare_route():
    return jsonify(prepare_demo_packet())


@human_operator_bp.route("/api/human-operator/demo/render", methods=["POST"])
def human_operator_demo_render_route():
    payload = run_demo_render(PROJECT_ROOT)
    status = int(payload.pop("statusCode", 200 if payload.get("ok") else 500))
    return jsonify(payload), status


@human_operator_bp.route("/api/human-operator/provider-readiness", methods=["GET"])
def human_operator_provider_readiness_route():
    setup = build_setup_status()
    return jsonify(build_provider_readiness(PROJECT_ROOT, setup))


@human_operator_bp.route("/api/human-operator/adapter-command-readiness", methods=["GET"])
def human_operator_adapter_command_readiness_route():
    return jsonify(build_adapter_command_readiness(PROJECT_ROOT))


@human_operator_bp.route("/api/human-operator/worklist", methods=["GET"])
def human_operator_worklist_route():
    return jsonify(build_human_mode_worklist(PROJECT_ROOT))


@human_operator_bp.route("/api/human-operator/sources/status", methods=["GET"])
def human_operator_source_status_route():
    return jsonify(build_source_workflow_status(PROJECT_ROOT))


@human_operator_bp.route("/api/human-operator/sources/review", methods=["POST"])
def human_operator_source_review_route():
    payload = save_source_review(PROJECT_ROOT, flask_request.get_json(silent=True) or {})
    status = int(payload.pop("statusCode", 200 if payload.get("ok") else 500))
    return jsonify(payload), status


@human_operator_bp.route("/api/human-operator/render-health", methods=["GET"])
def human_operator_render_health_route():
    setup = build_setup_status()
    return jsonify(build_render_health(PROJECT_ROOT, setup))


@human_operator_bp.route("/api/human-operator/phone-review/status", methods=["GET"])
def human_operator_phone_review_status_route():
    return jsonify(build_phone_review_status(PROJECT_ROOT))


@human_operator_bp.route("/api/human-operator/phone-review", methods=["POST"])
def human_operator_phone_review_route():
    payload = save_phone_review(PROJECT_ROOT, flask_request.get_json(silent=True) or {})
    status = int(payload.pop("statusCode", 200 if payload.get("ok") else 500))
    return jsonify(payload), status


@human_operator_bp.route("/api/human-operator/publish-packet", methods=["GET"])
def human_operator_publish_packet_route():
    return jsonify(build_publish_packet(PROJECT_ROOT))


@human_operator_bp.route("/api/human-operator/operator-blockers", methods=["GET"])
def human_operator_operator_blockers_route():
    return jsonify(build_operator_blockers(PROJECT_ROOT))


@human_operator_bp.route("/api/human-operator/status", methods=["GET"])
def human_operator_status_route():
    return jsonify(build_human_operator_status())
