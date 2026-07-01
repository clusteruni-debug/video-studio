from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from worker.bridge.grok_browser_proof import classify_grok_browser_proof
from worker.media.adapters import ADAPTER_CONFIG, MediaAdapterStatus, probe_local_media_adapter
from worker.media.model_router import ProviderAvailability
from worker.media.provider_policy import is_paid_provider, paid_providers_allowed


SCHEMA_PREFIX = "video-studio.human-operator"
DEMO_PROJECT_ID = "human-operator-local-demo-p0"
SOURCE_PROOF_ALLOWED_SUFFIXES = {".mp4", ".mov", ".m4v", ".png", ".jpg", ".jpeg", ".webp"}
RENDER_ARTIFACT_ALLOWED_SUFFIXES = {".mp4", ".mov", ".m4v"}
LOCAL_PROOF_ALLOWED_ROOTS = {"storage"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _storage_dir(project_root: Path | str) -> Path:
    return Path(project_root).resolve() / "storage" / "human-operator"


def _demo_dir(project_root: Path | str) -> Path:
    return Path(project_root).resolve() / "storage" / "human-operator-demo" / DEMO_PROJECT_ID


def _project_file_status(
    project_root: Path | str,
    raw_path: str,
    *,
    allowed_suffixes: set[str],
    allowed_roots: set[str] | None = None,
    label: str = "file",
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    raw = _text(raw_path)
    if not raw:
        return {
            "valid": False,
            "status": f"missing-{label}-path",
            "reason": f"{label} path is required",
            "sourcePath": raw,
        }
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "valid": False,
            "status": f"invalid-{label}-path",
            "reason": f"{label} path could not be resolved: {type(exc).__name__}",
            "sourcePath": raw,
        }
    try:
        relative = resolved.relative_to(root)
        under_project = True
    except ValueError:
        relative = None
        under_project = False
    suffix = resolved.suffix.lower()
    exists = resolved.is_file()
    size = 0
    if exists:
        try:
            size = resolved.stat().st_size
        except OSError:
            size = 0
    allowed_root = True
    if allowed_roots is not None:
        allowed_root = bool(relative and relative.parts and relative.parts[0] in allowed_roots)
    extension_ok = suffix in allowed_suffixes
    non_empty = exists and size > 0
    checks = {
        "underProject": under_project,
        "allowedRoot": allowed_root,
        "exists": exists,
        "extensionOk": extension_ok,
        "nonEmpty": non_empty,
    }
    if not under_project:
        status = f"{label}-outside-project"
    elif not allowed_root:
        status = f"{label}-outside-allowed-root"
    elif not exists:
        status = f"{label}-missing"
    elif not extension_ok:
        status = f"{label}-unsupported-extension"
    elif not non_empty:
        status = f"{label}-empty"
    else:
        status = "pass"
    relative_path = relative.as_posix() if relative is not None else ""
    return {
        "valid": status == "pass",
        "status": status,
        "reason": "validated" if status == "pass" else status.replace("-", " "),
        "sourcePath": raw,
        "relativePath": relative_path,
        "resolvedPath": str(resolved) if under_project else "",
        "suffix": suffix,
        "sizeBytes": size,
        **checks,
    }


def _validate_local_source_proof(project_root: Path | str, data: dict[str, Any]) -> dict[str, Any]:
    raw_path = _text(data.get("sourcePath") or data.get("localPath") or data.get("path"))
    proof = _project_file_status(
        project_root,
        raw_path,
        allowed_suffixes=SOURCE_PROOF_ALLOWED_SUFFIXES,
        allowed_roots=LOCAL_PROOF_ALLOWED_ROOTS,
        label="source",
    )
    proof["proofKind"] = _text(data.get("proofKind") or data.get("sourceType") or "local-upload")
    return proof


def _validate_render_artifact(project_root: Path | str, raw_path: str, *, expected_path: str = "") -> dict[str, Any]:
    proof = _project_file_status(
        project_root,
        raw_path,
        allowed_suffixes=RENDER_ARTIFACT_ALLOWED_SUFFIXES,
        allowed_roots=LOCAL_PROOF_ALLOWED_ROOTS,
        label="render-artifact",
    )
    expected = _text(expected_path)
    if expected:
        expected_proof = _project_file_status(
            project_root,
            expected,
            allowed_suffixes=RENDER_ARTIFACT_ALLOWED_SUFFIXES,
            allowed_roots=LOCAL_PROOF_ALLOWED_ROOTS,
            label="expected-render-artifact",
        )
        proof["expectedPath"] = expected
        proof["expectedRelativePath"] = expected_proof.get("relativePath", "")
        same_artifact = bool(proof.get("relativePath") and proof.get("relativePath") == expected_proof.get("relativePath"))
        proof["matchesCurrentRender"] = same_artifact
        if proof.get("valid") and not same_artifact:
            proof["valid"] = False
            proof["status"] = "render-artifact-mismatch"
            proof["reason"] = "phone review must reference the current render artifact"
    else:
        proof["expectedPath"] = ""
        proof["expectedRelativePath"] = ""
        proof["matchesCurrentRender"] = False
    return proof


def _read_json(path: Path, fallback: Any | None = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {} if fallback is None else fallback


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _status(state: str) -> str:
    if state == "ready":
        return "ready"
    if state in {"paid-opt-in", "manual-only", "config-required"}:
        return "optional"
    if state == "blocked":
        return "blocked"
    return "unknown"


def _adapter_state(status: MediaAdapterStatus) -> str:
    if status.ready:
        return "ready"
    if status.mode == "off":
        return "blocked"
    if status.mode in {"stub", "command"}:
        return "config-required"
    return "unknown"


def _adapter_operator_action(key: str, status: MediaAdapterStatus) -> str:
    if status.ready:
        return "Command adapter is ready; run a render to prove output on Windows."
    config = ADAPTER_CONFIG.get(key, {})
    env_prefix = str(config.get("envPrefix") or "").strip()
    if status.mode == "off":
        return f"Set {env_prefix}_MODE=command manually if this adapter should run."
    if key == "wan":
        return "Wire local Wan by setting VIDEO_STUDIO_WAN_MODE=command and VIDEO_STUDIO_WAN_COMMAND as a JSON string array."
    if key == "gemini-flash":
        return "Optional: set VIDEO_STUDIO_GEMINI_FLASH_MODE=command and VIDEO_STUDIO_GEMINI_FLASH_COMMAND, or keep local uploads/Pexels/title-card fallback."
    return f"Configure {env_prefix}_MODE=command and {env_prefix}_COMMAND if this adapter is needed."


def build_adapter_command_readiness(project_root: Path | str) -> dict[str, Any]:
    """Expose command-adapter readiness without executing providers."""
    adapter_keys = ["wan", "gemini-flash", "pexels-video", "edge-tts", "local-bgm", "freesound"]
    paid_allowed = paid_providers_allowed()
    rows: list[dict[str, Any]] = []
    for key in adapter_keys:
        config = ADAPTER_CONFIG.get(key, {})
        try:
            status = probe_local_media_adapter(key, project_root=project_root)
        except Exception as exc:
            rows.append({
                "key": key,
                "label": str(config.get("label") or key),
                "category": str(config.get("category") or "unknown"),
                "state": "unknown",
                "status": "unknown",
                "ready": False,
                "mode": "unknown",
                "requiredForDemo": False,
                "requiredForManualProduction": key in {"edge-tts", "local-bgm"},
                "commandPreview": None,
                "entryPoint": None,
                "detail": f"adapter probe failed: {type(exc).__name__}",
                "operatorAction": "Check adapter configuration and rerun provider readiness.",
            })
            continue
        state = _adapter_state(status)
        cost_tier = str(config.get("costTier") or "unknown")
        if is_paid_provider(key) and not paid_allowed:
            state = "blocked"
        rows.append({
            "key": key,
            "label": status.label,
            "category": str(config.get("category") or status.outputKind),
            "state": state,
            "status": _status(state),
            "ready": status.ready,
            "mode": status.mode,
            "model": status.model,
            "costTier": cost_tier,
            "requiredForDemo": False,
            "requiredForManualProduction": key in {"edge-tts", "local-bgm"},
            "optionalForProviderAssisted": key in {"wan", "gemini-flash", "pexels-video", "freesound"},
            "envPrefix": str(config.get("envPrefix") or ""),
            "commandPreview": status.commandPreview,
            "entryPoint": status.entryPoint,
            "detail": status.detail,
            "operatorAction": _adapter_operator_action(key, status),
        })
    return {
        "ok": True,
        "schema": f"{SCHEMA_PREFIX}.adapter-command-readiness.v1",
        "generatedAt": _now_iso(),
        "executionBoundary": "This endpoint probes command readiness only; it does not run Wan, Gemini, Pexels, Edge TTS, or any browser provider.",
        "counts": {
            "ready": sum(1 for row in rows if row["state"] == "ready"),
            "configRequired": sum(1 for row in rows if row["state"] == "config-required"),
            "blocked": sum(1 for row in rows if row["state"] == "blocked"),
            "unknown": sum(1 for row in rows if row["state"] == "unknown"),
        },
        "adapters": rows,
    }


def build_provider_readiness(project_root: Path | str, setup_status: dict[str, Any]) -> dict[str, Any]:
    matrix = _as_list(setup_status.get("providerMatrix"))
    by_key = {str(item.get("key")): item for item in matrix if isinstance(item, dict)}

    adapter_readiness = build_adapter_command_readiness(project_root)
    adapter_by_key = {item["key"]: item for item in _as_list(adapter_readiness.get("adapters")) if isinstance(item, dict)}
    wan_state = _text(_as_dict(adapter_by_key.get("wan")).get("state")) or "config-required"
    gemini_flash_state = _text(_as_dict(adapter_by_key.get("gemini-flash")).get("state")) or "config-required"

    rows = [
        {
            "key": "demo-template",
            "label": "No-LLM template planner",
            "function": "planning",
            "state": "ready",
            "modes": ["Demo Mode", "Manual Production"],
            "requiredForDemo": True,
            "repairAction": "Bundled with the repository.",
        },
        {
            "key": "local-title-card-render",
            "label": "Local title-card render",
            "function": "visual fallback",
            "state": "ready" if _as_dict(by_key.get("local-title-card-render")).get("ready") else "config-required",
            "modes": ["Demo Mode", "Manual Production"],
            "requiredForDemo": True,
            "repairAction": "Install FFmpeg and restart the bridge.",
        },
        {
            "key": "edge-tts",
            "label": "Edge/Windows TTS",
            "function": "tts",
            "state": "manual-only",
            "modes": ["Manual Production"],
            "requiredForDemo": False,
            "repairAction": "Use the local TTS path when available; demo can fall back to silent/title-card proof.",
        },
        {
            "key": "pexels",
            "label": "Pexels",
            "function": "stock video/image",
            "state": "ready" if os.environ.get("PEXELS_API_KEY", "").strip() else "config-required",
            "modes": ["Provider-Assisted"],
            "requiredForDemo": False,
            "repairAction": "Set PEXELS_API_KEY manually if stock search is needed.",
        },
        {
            "key": "gemini",
            "label": "Gemini",
            "function": "planning/image",
            "state": "ready" if os.environ.get("GEMINI_API_KEY", "").strip() or gemini_flash_state == "ready" else "config-required",
            "modes": ["Provider-Assisted"],
            "requiredForDemo": False,
            "repairAction": "Set GEMINI_API_KEY manually or configure the Gemini Flash command adapter; not required for Demo Mode.",
        },
        {
            "key": "wan-command",
            "label": "Wan local command adapter",
            "function": "video generation",
            "state": wan_state,
            "modes": ["Provider-Assisted", "Manual Production"],
            "requiredForDemo": False,
            "repairAction": _as_dict(adapter_by_key.get("wan")).get("operatorAction") or "Configure the local Wan command adapter manually.",
        },
        {
            "key": "grok-browser",
            "label": "Grok browser handoff",
            "function": "video source generation",
            "state": "manual-only",
            "modes": ["Provider-Assisted"],
            "requiredForDemo": False,
            "repairAction": "Use the existing signed-in Chrome profile and record generation/import proof; /c/* redirects remain blockers.",
        },
        {
            "key": "capcut-export",
            "label": "CapCut export",
            "function": "manual edit/export",
            "state": "manual-only",
            "modes": ["Manual Production"],
            "requiredForDemo": False,
            "repairAction": "Operator exports manually; no dependency or UI automation is enabled by default.",
        },
        {
            "key": "paid-providers",
            "label": "Paid providers",
            "function": "premium generation",
            "state": "paid-opt-in" if os.environ.get("VIDEO_STUDIO_ALLOW_PAID_PROVIDERS") == "1" else "blocked",
            "modes": ["Provider-Assisted"],
            "requiredForDemo": False,
            "repairAction": "Requires explicit VIDEO_STUDIO_ALLOW_PAID_PROVIDERS=1 and manual API keys.",
        },
    ]
    counts = {
        "ready": sum(1 for row in rows if row["state"] == "ready"),
        "configRequired": sum(1 for row in rows if row["state"] == "config-required"),
        "manualOnly": sum(1 for row in rows if row["state"] == "manual-only"),
        "paidOptIn": sum(1 for row in rows if row["state"] == "paid-opt-in"),
        "blocked": sum(1 for row in rows if row["state"] == "blocked"),
    }
    demo_blockers = [row for row in rows if row["requiredForDemo"] and row["state"] not in {"ready", "manual-only"}]
    return {
        "ok": True,
        "schema": f"{SCHEMA_PREFIX}.provider-readiness.v1",
        "generatedAt": _now_iso(),
        "modeDefinitions": [
            {"mode": "Demo Mode", "requiresExternalAi": False, "description": "Bundled sample path for local setup and render proof."},
            {"mode": "Manual Production", "requiresExternalAi": False, "description": "Operator-owned files, local tools, phone review, and publish packet."},
            {"mode": "Provider-Assisted", "requiresExternalAi": True, "description": "Optional API/browser providers with explicit evidence boundaries."},
        ],
        "counts": counts,
        "demoModeReady": not demo_blockers and bool(setup_status.get("criticalReady")),
        "demoBlockers": [row["key"] for row in demo_blockers],
        "providers": [{**row, "status": _status(row["state"])} for row in rows],
        "adapterCommandReadiness": adapter_readiness,
    }


def _source_reviews_path(project_root: Path | str) -> Path:
    return _storage_dir(project_root) / "source-reviews.json"


def load_source_reviews(project_root: Path | str) -> dict[str, Any]:
    payload = _read_json(_source_reviews_path(project_root), {"reviews": []})
    reviews = [item for item in _as_list(_as_dict(payload).get("reviews")) if isinstance(item, dict)]
    return {
        "schema": f"{SCHEMA_PREFIX}.source-reviews.v1",
        "updatedAt": _text(_as_dict(payload).get("updatedAt")),
        "reviews": reviews,
    }


def save_source_review(project_root: Path | str, data: dict[str, Any]) -> dict[str, Any]:
    decision = _text(data.get("decision")).lower()
    if decision not in {"accepted", "rejected"}:
        return {"ok": False, "error": "decision must be accepted or rejected", "statusCode": 400}
    source_id = _text(data.get("sourceId") or data.get("sourcePath") or data.get("url"))
    if not source_id:
        return {"ok": False, "error": "sourceId, sourcePath, or url is required", "statusCode": 400}
    proof_kind = _text(data.get("proofKind") or data.get("sourceType") or "local-upload")
    raw_browser_proof = _as_dict(data.get("browserProof"))
    browser_proof = classify_grok_browser_proof(raw_browser_proof)
    native_download_prompt = raw_browser_proof.get("nativeDownloadPromptOpened") is True or raw_browser_proof.get("nativeDownloadPrompt") is True
    local_proof = None if proof_kind == "browser-proof" else _validate_local_source_proof(project_root, data)
    if proof_kind == "browser-proof" and decision == "accepted" and native_download_prompt:
        return {
            "ok": False,
            "error": "browser-proof acceptance cannot rely on native Chrome Download/Save/Export prompts",
            "statusCode": 400,
            "browserProof": {**browser_proof, "nativeDownloadPromptOpened": True},
        }
    if proof_kind == "browser-proof" and decision == "accepted" and not browser_proof["success"]:
        return {
            "ok": False,
            "error": "browser-proof acceptance requires generation/import proof; surface-only or /c/* redirect is not accepted",
            "statusCode": 400,
            "browserProof": browser_proof,
        }
    if proof_kind != "browser-proof" and decision == "accepted" and not _as_dict(local_proof).get("valid"):
        return {
            "ok": False,
            "error": "local/direct source acceptance requires an existing non-empty media file inside project storage",
            "statusCode": 400,
            "localProof": local_proof,
        }

    existing = load_source_reviews(project_root)
    reviews = existing["reviews"]
    review = {
        "sourceId": source_id,
        "sceneId": _text(data.get("sceneId")),
        "decision": decision,
        "proofKind": proof_kind,
        "sourcePath": _as_dict(local_proof).get("relativePath") or _text(data.get("sourcePath")),
        "url": _text(data.get("url")),
        "notes": _text(data.get("notes")),
        "reviewer": _text(data.get("reviewer")) or "human-operator",
        "reviewedAt": _now_iso(),
        "browserProof": ({**browser_proof, "nativeDownloadPromptOpened": native_download_prompt} if data.get("browserProof") else None),
        "localProof": local_proof,
        "proofState": _source_proof_state(proof_kind, decision, browser_proof, native_download_prompt, local_proof),
    }
    reviews = [item for item in reviews if item.get("sourceId") != source_id]
    reviews.append(review)
    payload = {
        "schema": f"{SCHEMA_PREFIX}.source-reviews.v1",
        "updatedAt": _now_iso(),
        "reviews": reviews,
    }
    _write_json(_source_reviews_path(project_root), payload)
    return {**build_source_workflow_status(project_root), "review": review}


def build_source_workflow_status(project_root: Path | str) -> dict[str, Any]:
    reviews = load_source_reviews(project_root)["reviews"]
    accepted_candidates = [item for item in reviews if item.get("decision") == "accepted"]
    accepted = [item for item in accepted_candidates if _source_review_verified(project_root, item)]
    unvalidated = [item for item in accepted_candidates if not _source_review_verified(project_root, item)]
    rejected = [item for item in reviews if item.get("decision") == "rejected"]
    browser_blockers = [
        item for item in reviews
        if (
            _as_dict(item.get("browserProof")).get("isChatRedirect")
            or _as_dict(item.get("browserProof")).get("status") == "surface-visible"
            or _as_dict(item.get("browserProof")).get("nativeDownloadPromptOpened")
        )
    ]
    next_action = "Render can use accepted local sources."
    if not accepted and unvalidated:
        next_action = "Repair unvalidated accepted sources by importing files into project storage and accepting them again."
    elif not accepted:
        next_action = "Upload or import an operator-owned file and mark it accepted before production render claims."
    return {
        "ok": True,
        "schema": f"{SCHEMA_PREFIX}.source-workflow.v1",
        "generatedAt": _now_iso(),
        "status": "ready" if accepted else "pending",
        "acceptedCount": len(accepted),
        "unvalidatedAcceptedCount": len(unvalidated),
        "rejectedCount": len(rejected),
        "browserBlockerCount": len(browser_blockers),
        "sourceProofBlockerCount": len(browser_blockers) + len(unvalidated),
        "acceptedSources": accepted,
        "unvalidatedAcceptedSources": unvalidated,
        "rejectedSources": rejected,
        "proofBoundary": {
            "localUploadAccepted": "passes only after a non-empty media file exists inside project storage",
            "browserSurfaceOnly": "does not pass source proof",
            "browserGeneratedImported": "can pass only when generation and local import proof are present",
            "grokChatRedirect": "blocked",
            "legacyAcceptedRows": "treated as unvalidated until repaired",
        },
        "nextAction": next_action,
    }


def _source_proof_state(
    proof_kind: str,
    decision: str,
    browser_proof: dict[str, Any],
    native_download_prompt: bool,
    local_proof: dict[str, Any] | None = None,
) -> str:
    if decision != "accepted":
        return "rejected"
    if proof_kind != "browser-proof":
        return "accepted-local-validated" if _as_dict(local_proof).get("valid") else "blocked-local-source-proof"
    if native_download_prompt:
        return "blocked-native-download-prompt"
    if browser_proof.get("success"):
        return "accepted-browser-generation-import"
    if browser_proof.get("isChatRedirect"):
        return "blocked-grok-chat-redirect"
    if browser_proof.get("surfaceVisible"):
        return "surface-only-not-source-proof"
    return "blocked-browser-proof"


def _source_review_verified(project_root: Path | str, review: dict[str, Any]) -> bool:
    if review.get("decision") != "accepted":
        return False
    proof_kind = _text(review.get("proofKind"))
    proof_state = _text(review.get("proofState"))
    if proof_kind == "browser-proof":
        return proof_state == "accepted-browser-generation-import"
    if proof_state != "accepted-local-validated":
        return False
    local_proof = _as_dict(review.get("localProof"))
    source_path = _text(local_proof.get("relativePath") or review.get("sourcePath") or local_proof.get("sourcePath"))
    return bool(_validate_local_source_proof(project_root, {"sourcePath": source_path, "proofKind": proof_kind}).get("valid"))


def categorize_render_failure(message: str) -> str:
    text = message.lower()
    if "ffmpeg" in text and ("not found" in text or "missing" in text or "no such file" in text):
        return "missing-ffmpeg"
    if "no such file" in text or "does not exist" in text or "missing source" in text:
        return "missing-source-file"
    if "manifest" in text or "json" in text:
        return "invalid-manifest"
    if "subtitle" in text or ".ass" in text or ".srt" in text:
        return "subtitle-error"
    if "audio" in text or "wav" in text or "tts" in text:
        return "audio-error"
    if "permission" in text or "access is denied" in text:
        return "write-permission"
    if "approval packet" in text or "approvedforrender" in text:
        return "active-approval-lock"
    return "unknown"


def _demo_render_result_path(project_root: Path | str) -> Path:
    return _demo_dir(project_root) / "demo-render-result.json"


def _current_demo_render_output(project_root: Path | str) -> str:
    result = _as_dict(_read_json(_demo_render_result_path(project_root), {}))
    render = _as_dict(result.get("renderResult"))
    return _text(render.get("outputPath"))


def build_render_health(project_root: Path | str, setup_status: dict[str, Any]) -> dict[str, Any]:
    result = _as_dict(_read_json(_demo_render_result_path(project_root), {}))
    last_error = _text(result.get("error"))
    render_result = _as_dict(result.get("renderResult"))
    output_path = _text(render_result.get("outputPath"))
    log_path = _text(render_result.get("logPath"))
    ffmpeg_check = next((item for item in _as_list(setup_status.get("checks")) if _as_dict(item).get("key") == "ffmpeg"), {})
    ffmpeg_ready = bool(_as_dict(ffmpeg_check).get("ready"))
    render_proof = _validate_render_artifact(project_root, output_path) if output_path else {"valid": False, "status": "render-candidate-required"}
    if output_path and render_proof.get("valid"):
        status = "ready"
        category = "render-produced"
        next_action = "Open Review, complete phone review, then inspect the publish packet."
    elif output_path:
        status = "blocked"
        category = "render-artifact-unverified"
        next_action = "Recreate the render artifact or rerun the demo render before phone review."
    elif not ffmpeg_ready:
        status = "blocked"
        category = "missing-ffmpeg"
        next_action = "Install FFmpeg and restart the bridge."
    elif last_error:
        status = "blocked"
        category = categorize_render_failure(last_error)
        next_action = "Use the failure category repair action, then retry the demo render."
    else:
        status = "pending"
        category = "not-run"
        next_action = "Prepare and run the no-LLM demo render."
    return {
        "ok": True,
        "schema": f"{SCHEMA_PREFIX}.render-health.v1",
        "generatedAt": _now_iso(),
        "status": status,
        "failureCategory": category,
        "lastRender": result,
        "outputPath": output_path,
        "logPath": log_path,
        "ffmpeg": ffmpeg_check,
        "repairActions": {
            "missing-ffmpeg": "Install FFmpeg and expose it to the bridge process PATH.",
            "missing-source-file": "Recreate or relink the accepted source file before retrying.",
            "invalid-manifest": "Regenerate the demo packet or render manifest.",
            "subtitle-error": "Check ASS subtitle generation and Korean line length.",
            "audio-error": "Check TTS/BGM assets or rerun with local fallback audio disabled.",
            "write-permission": "Fix storage folder permissions.",
            "active-approval-lock": "Use an unrelated demo project id or resolve the active approval packet deliberately.",
            "render-artifact-unverified": "Rerun the render so the output MP4 exists in project storage before review.",
            "unknown": "Open the log path and inspect the FFmpeg/bridge exception.",
        },
        "renderProof": render_proof,
        "nextAction": next_action,
    }


def run_demo_render(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    payload_path = _demo_dir(root) / "render-smoke-payload.json"
    payload = _as_dict(_read_json(payload_path, {}))
    if not payload:
        return {
            "ok": False,
            "error": "demo packet is not prepared",
            "statusCode": 400,
            "nextAction": "Call /api/human-operator/demo/prepare first.",
        }
    try:
        from worker.planner.save_plan import save_project_bundle
        from worker.render.compose import compose_smoke_render

        bundle = save_project_bundle(
            prompt=_text(payload.get("prompt")) or "No-LLM local demo",
            budget_mode=_text(payload.get("budgetMode")) or "free",
            availability=ProviderAvailability(),
            planner_mode=_text(payload.get("plannerMode")) or "sample",
            project_id=_text(payload.get("projectId")) or DEMO_PROJECT_ID,
            project_root=root,
            scene_assets=_as_list(payload.get("sceneAssets")),
            provider_overrides=_as_dict(payload.get("providerOverrides")),
            draft_scenes=_as_list(payload.get("draftScenes")),
            selected_pexels_videos=_as_dict(payload.get("selectedPexelsVideos")),
            subtitle_style=_text(payload.get("subtitleStyle")),
            bgm_enabled=payload.get("bgmEnabled") is not False,
            bgm_asset=_as_dict(payload.get("bgmAsset") or payload.get("selectedBgmAsset")),
            template_type=_text(payload.get("templateType") or payload.get("template_type")),
        )
        render_result = compose_smoke_render(bundle["saveResult"]["manifestPath"], project_root=root)
        result = {
            "ok": bool(render_result.ok),
            "schema": f"{SCHEMA_PREFIX}.demo-render.v1",
            "renderedAt": _now_iso(),
            "saveResult": bundle.get("saveResult"),
            "renderResult": render_result.to_dict(),
            "releaseBoundary": "Demo draft only; phone review and publish packet remain required before upload claims.",
        }
        if not render_result.ok:
            result["error"] = _text(render_result.to_dict().get("error")) or "demo render failed"
    except Exception as exc:
        result = {
            "ok": False,
            "schema": f"{SCHEMA_PREFIX}.demo-render.v1",
            "renderedAt": _now_iso(),
            "error": str(exc),
            "failureCategory": categorize_render_failure(str(exc)),
            "releaseBoundary": "No publish or upload claim is made from a failed demo render.",
        }
    _write_json(_demo_render_result_path(root), result)
    return result


def _phone_review_path(project_root: Path | str) -> Path:
    return _storage_dir(project_root) / "phone-review.json"


def load_phone_review(project_root: Path | str) -> dict[str, Any]:
    return _as_dict(_read_json(_phone_review_path(project_root), {}))


def save_phone_review(project_root: Path | str, data: dict[str, Any]) -> dict[str, Any]:
    render_id = _text(data.get("renderId") or data.get("renderPath") or data.get("outputPath"))
    if not render_id:
        return {"ok": False, "error": "renderId, renderPath, or outputPath is required", "statusCode": 400}
    duration = data.get("watchedDurationSec", data.get("watchedDuration"))
    try:
        watched_duration = max(0, int(duration))
    except (TypeError, ValueError):
        watched_duration = 0
    decision = _text(data.get("decision")).lower()
    if decision not in {"accepted", "rejected", "needs-fix"}:
        return {"ok": False, "error": "decision must be accepted, rejected, or needs-fix", "statusCode": 400}
    current_render = _current_demo_render_output(project_root)
    render_proof = _validate_render_artifact(project_root, render_id, expected_path=current_render) if current_render else {
        "valid": False,
        "status": "current-render-artifact-required",
        "reason": "accepted phone review requires a current render result",
        "sourcePath": render_id,
        "expectedPath": "",
        "matchesCurrentRender": False,
    }
    if decision == "accepted" and not render_proof.get("valid"):
        return {
            "ok": False,
            "error": "accepted phone review requires the current render artifact to exist inside project storage",
            "statusCode": 400,
            "renderProof": render_proof,
        }
    checks = {
        "captions": data.get("captionsOk") is True,
        "sourceFit": data.get("sourceFitOk") is True,
        "audio": data.get("audioOk") is True,
        "pacing": data.get("pacingOk") is True,
        "disclosure": data.get("disclosureOk") is True,
    }
    full_watch = data.get("fullWatchCompleted") is True and watched_duration > 0
    accepted = decision == "accepted" and full_watch and all(checks.values()) and bool(render_proof.get("valid"))
    review = {
        "ok": True,
        "schema": f"{SCHEMA_PREFIX}.phone-review.v1",
        "reviewedAt": _now_iso(),
        "renderId": render_id,
        "renderPath": render_proof.get("relativePath") or render_id,
        "device": _text(data.get("device")) or "phone",
        "reviewer": _text(data.get("reviewer")) or "human-operator",
        "watchedDurationSec": watched_duration,
        "fullWatchCompleted": full_watch,
        "checks": checks,
        "decision": decision,
        "acceptedForPublishPacket": accepted,
        "renderProof": render_proof,
        "notes": _text(data.get("notes")),
    }
    _write_json(_phone_review_path(project_root), review)
    return review


def build_phone_review_status(project_root: Path | str) -> dict[str, Any]:
    review = load_phone_review(project_root)
    render_proof = None
    if review:
        current_render = _current_demo_render_output(project_root)
        render_path = _text(review.get("renderPath") or review.get("renderId"))
        render_proof = _validate_render_artifact(project_root, render_path, expected_path=current_render) if current_render else {
            "valid": False,
            "status": "current-render-artifact-required",
            "reason": "current render result is missing",
            "sourcePath": render_path,
            "expectedPath": "",
            "matchesCurrentRender": False,
        }
    if not review:
        status = "pending"
        next_action = "Watch the render on a phone-sized viewport and record the review."
    elif review.get("acceptedForPublishPacket") and _as_dict(render_proof).get("valid"):
        status = "pass"
        next_action = "Inspect the publish packet and remaining blockers before upload."
    else:
        status = "blocked"
        next_action = "Fix the review failures or record a new accepted full-watch phone review tied to the current render artifact."
    return {
        "ok": True,
        "schema": f"{SCHEMA_PREFIX}.phone-review-status.v1",
        "generatedAt": _now_iso(),
        "status": status,
        "review": review or None,
        "renderProof": render_proof,
        "nextAction": next_action,
    }


def build_publish_packet(project_root: Path | str) -> dict[str, Any]:
    render_result = _as_dict(_read_json(_demo_render_result_path(project_root), {}))
    phone = build_phone_review_status(project_root)
    source = build_source_workflow_status(project_root)
    render = _as_dict(render_result.get("renderResult"))
    output_path = _text(render.get("outputPath"))
    render_proof = _validate_render_artifact(project_root, output_path) if output_path else {"valid": False, "status": "render-candidate-required"}
    blockers: list[str] = []
    if not output_path:
        blockers.append("render-candidate-required")
    elif not render_proof.get("valid"):
        blockers.append("render-artifact-unverified")
    if source["acceptedCount"] <= 0:
        blockers.append("accepted-source-unvalidated" if source.get("unvalidatedAcceptedCount", 0) > 0 else "accepted-source-required")
    if phone["status"] != "pass":
        blockers.append("phone-review-required")
    upload_allowed = not blockers
    return {
        "ok": True,
        "schema": f"{SCHEMA_PREFIX}.publish-packet.v1",
        "generatedAt": _now_iso(),
        "projectId": DEMO_PROJECT_ID,
        "uploadAllowed": upload_allowed,
        "decision": "operator-review-required" if blockers else "ready-for-operator-upload",
        "blockers": blockers,
        "title": "Video Studio No-LLM Demo Draft",
        "description": "Local demo render produced without external AI accounts. Operator review required before any upload.",
        "hashtags": ["#VideoStudio", "#NoLLMDemo"],
        "aiDisclosure": "No external generative AI provider was required for this demo packet; title-card fallback and local rendering were used.",
        "sourceProof": source,
        "renderProof": {**render_result, "artifact": render_proof} if render_result else {"artifact": render_proof},
        "phoneReview": phone,
        "operatorBoundary": "The app prepares evidence; upload remains an operator-owned action.",
    }


def _work_item(
    key: str,
    title: str,
    status: str,
    doc_path: str,
    next_action: str,
    *,
    category: str,
    requires_runtime_proof: bool = False,
    details: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "category": category,
        "status": status,
        "docPath": doc_path,
        "requiresRuntimeProof": requires_runtime_proof,
        "nextAction": next_action,
        "details": details or [],
    }


def build_human_mode_worklist(project_root: Path | str) -> dict[str, Any]:
    """Summarize docs-plan residuals as operator-visible work, not proof claims."""
    adapter = build_adapter_command_readiness(project_root)
    adapter_by_key = {item["key"]: item for item in _as_list(adapter.get("adapters")) if isinstance(item, dict)}
    wan = _as_dict(adapter_by_key.get("wan"))
    gemini_flash = _as_dict(adapter_by_key.get("gemini-flash"))
    source = build_source_workflow_status(project_root)
    render = _as_dict(_read_json(_demo_render_result_path(project_root), {}))
    phone = build_phone_review_status(project_root)
    publish = build_publish_packet(project_root)
    operator_blockers = build_operator_blockers(project_root)

    items = [
        _work_item(
            "human-mode-release-proof",
            "Human-mode MVP release proof",
            "pending-runtime-proof",
            "docs/HUMAN-OPERATOR-PRODUCTION-PLAN.md",
            "Run the Windows bridge/dashboard/demo/source-review/phone-review/publish-packet smoke before claiming release.",
            category="release",
            requires_runtime_proof=True,
            details=[
                "setup proof must come from live /api/human-operator/setup-status in the Windows bridge session",
                f"demo render ok: {bool(render.get('ok')) if render else 'not run'}",
                f"phone review status: {phone.get('status')}",
                f"publish blockers: {', '.join(publish.get('blockers') or []) or 'none'}",
            ],
        ),
        _work_item(
            "wan-command-adapter",
            "Real local Wan command adapter",
            "source-ready" if wan.get("state") == "ready" else "config-required",
            "docs/IMPLEMENTATION-ROADMAP.md",
            str(wan.get("operatorAction") or "Wire local Wan command settings manually."),
            category="provider",
            requires_runtime_proof=wan.get("state") == "ready",
            details=[str(wan.get("detail") or ""), str(wan.get("commandPreview") or "")],
        ),
        _work_item(
            "gemini-flash-command-adapter",
            "Optional Gemini Flash Image command adapter",
            "source-ready" if gemini_flash.get("state") == "ready" else "optional-config",
            "docs/IMPLEMENTATION-ROADMAP.md",
            str(gemini_flash.get("operatorAction") or "Keep uploads/Pexels/title-card fallback unless Gemini image output is needed."),
            category="provider",
            requires_runtime_proof=gemini_flash.get("state") == "ready",
            details=[str(gemini_flash.get("detail") or ""), str(gemini_flash.get("commandPreview") or "")],
        ),
        _work_item(
            "grok-ui-handoff-proof",
            "Grok UI handoff/export workflow proof",
            "blocked-external-proof",
            "docs/QUALITY-RECOVERY-RUNBOOK-20260607.md",
            "Use signed-in Chrome/Grok Imagine, generate/import a local MP4, and reject /c/* redirects or native download prompt claims.",
            category="browser-handoff",
            requires_runtime_proof=True,
            details=[
                "Browser surface proof alone is not source proof.",
                "Direct import or operator-owned local upload is required before acceptance.",
            ],
        ),
        _work_item(
            "repeatable-source-import",
            "Repeatable source import without native prompts",
            "source-ready" if source.get("acceptedCount", 0) > 0 else "pending-source-proof",
            "docs/QUALITY-RECOVERY-RUNBOOK-20260607.md",
            source.get("nextAction") or "Accept at least one local/direct-import source.",
            category="source-proof",
            requires_runtime_proof=True,
            details=[
                f"accepted: {source.get('acceptedCount', 0)}",
                f"browser blockers: {source.get('browserBlockerCount', 0)}",
            ],
        ),
        _work_item(
            "live-channel-readiness",
            "Live-channel upload readiness",
            "blocked-runtime-proof",
            "docs/LIVE-CHANNEL-OPERATING-SYSTEM.md",
            "Do not upload until fresh-source proof, phone review, publish packet, dashboard smoke, and platform analytics are recorded.",
            category="publish-readiness",
            requires_runtime_proof=True,
            details=[
                "Existing candidates remain blocked by fresh-source/phone/platform evidence gaps.",
                f"operator blocker external count: {_as_dict(operator_blockers.get('counts')).get('externalDependency', 0)}",
            ],
        ),
        _work_item(
            "bottled-water-v6",
            "KR curiosity bottled-water next render/CapCut handoff",
            "pending-render-proof",
            "docs/QA/2026-06-21-kr-curiosity-bottled-water-editorial-direction-plan.md",
            "Use the editorial direction contract for the next candidate; do not claim final upload readiness before phone review.",
            category="editorial-candidate",
            requires_runtime_proof=True,
            details=[
                "No render or CapCut export is performed by this source-only pass.",
                "Editorial evidence paths must be created by the next runtime candidate.",
            ],
        ),
        _work_item(
            "windows-test-checklist",
            "Windows runtime checklist refresh",
            "doc-refresh",
            "docs/WINDOWS-TEST-CHECKLIST.md",
            "Use human-mode checks instead of retired Ollama/qwen assumptions.",
            category="docs",
            requires_runtime_proof=False,
        ),
    ]
    return {
        "ok": True,
        "schema": f"{SCHEMA_PREFIX}.worklist.v1",
        "generatedAt": _now_iso(),
        "releaseBoundary": "Source-level worklist only; Windows runtime, browser provider, phone watch, and platform analytics proof remain operator-run.",
        "counts": {
            "total": len(items),
            "requiresRuntimeProof": sum(1 for item in items if item["requiresRuntimeProof"]),
            "blocked": sum(1 for item in items if str(item["status"]).startswith("blocked")),
            "sourceReady": sum(1 for item in items if item["status"] == "source-ready"),
            "docRefresh": sum(1 for item in items if item["status"] == "doc-refresh"),
        },
        "items": items,
    }


def build_operator_blockers(project_root: Path | str) -> dict[str, Any]:
    board_path = Path(project_root).resolve() / "AGENT_TASK_BOARD.md"
    text = board_path.read_text(encoding="utf-8") if board_path.exists() else ""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("| VIDEO-STUDIO-"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 6:
            continue
        task_id, owner, status, scope, notes, change_type = cells[:6]
        if status not in {"blocked", "in_progress", "review"}:
            continue
        external = any(token in f"{task_id} {notes}".lower() for token in ["grok", "gemini", "capcut", "chrome", "browser", "download", "429"])
        stale = bool(re.search(r"202605|2026060[1-9]|2026061[0-9]", task_id))
        rows.append({
            "taskId": task_id,
            "owner": owner,
            "status": status,
            "scope": scope,
            "changeType": change_type,
            "externalDependency": external,
            "staleCandidate": stale and status == "in_progress",
            "summary": notes[:220],
        })
    return {
        "ok": True,
        "schema": f"{SCHEMA_PREFIX}.operator-blockers.v1",
        "generatedAt": _now_iso(),
        "counts": {
            "blocked": sum(1 for row in rows if row["status"] == "blocked"),
            "inProgress": sum(1 for row in rows if row["status"] == "in_progress"),
            "review": sum(1 for row in rows if row["status"] == "review"),
            "externalDependency": sum(1 for row in rows if row["externalDependency"]),
            "staleCandidates": sum(1 for row in rows if row["staleCandidate"]),
        },
        "blockers": rows,
        "policy": {
            "capcutAutomation": "blocked until dependency/UI automation approval",
            "geminiQuota": "blocked by provider quota/credentials when 429 is returned",
            "grokProof": "requires existing signed-in Chrome proof; /c/* redirect is failure",
            "nativeDownloads": "operator-owned; no automatic success claim",
        },
    }
