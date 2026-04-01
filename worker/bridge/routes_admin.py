"""Admin routes — storage, batch, jobs, draft delete, usage stats.

Extracted from server.py to keep the main bridge under the 660-line limit.
"""
from __future__ import annotations

import shutil
import threading
from pathlib import Path

from flask import Blueprint, jsonify, request as flask_request

from worker.bridge.cleanup import storage_status, cleanup_storage
from worker.usage.db import (
    SESSION_ID as _USAGE_SESSION_ID,
    get_session_stats,
    get_daily_stats,
    get_monthly_stats,
    get_hourly_stats,
    get_monthly_total_cost,
)
from worker.usage.limits import FREE_TIER_LIMITS

admin_bp = Blueprint("admin", __name__)

# Set by server.py at registration time
_project_root: Path = Path.cwd()
_capcut_draft_dir: Path = Path.home()
_batch_manager = None
_job_queue = None
_execute_draft_fn = None
_safe_resolve = None


def init_admin_routes(
    project_root: Path, capcut_draft_dir: Path,
    batch_manager, job_queue, execute_draft_fn, safe_resolve,
):
    global _project_root, _capcut_draft_dir
    global _batch_manager, _job_queue, _execute_draft_fn, _safe_resolve
    _project_root = project_root
    _capcut_draft_dir = capcut_draft_dir
    _batch_manager = batch_manager
    _job_queue = job_queue
    _execute_draft_fn = execute_draft_fn
    _safe_resolve = safe_resolve


# ---------------------------------------------------------------------------
# Storage management
# ---------------------------------------------------------------------------

@admin_bp.route("/api/storage/status", methods=["GET"])
def storage_status_route():
    return jsonify({"ok": True, **storage_status(_project_root, _capcut_draft_dir)})


_cleanup_lock = threading.Lock()


@admin_bp.route("/api/storage/cleanup", methods=["POST"])
def storage_cleanup_route():
    if not _cleanup_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Cleanup already in progress"}), 409
    try:
        data = flask_request.get_json(silent=True) or {}
        try:
            max_age = max(1, min(int(data.get("max_age_days", 7)), 90))
        except (ValueError, TypeError):
            max_age = 7
        dry_run = bool(data.get("dry_run", False))
        result = cleanup_storage(_project_root, _capcut_draft_dir, max_age_days=max_age, dry_run=dry_run)
        return jsonify({"ok": True, "dry_run": dry_run, "max_age_days": max_age, **result})
    finally:
        _cleanup_lock.release()


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------

@admin_bp.route("/api/batch/create", methods=["POST"])
def create_batch_route():
    data = flask_request.get_json(silent=True) or {}
    topic = data.get("prompt", "").strip()
    if not topic:
        return jsonify({"ok": False, "error": "prompt is required"}), 400
    try:
        variants = min(int(data.get("variants", 3)), 10)
    except (ValueError, TypeError):
        variants = 3

    batch_id = _batch_manager.create_batch(
        topic=topic,
        variants=variants,
        template_type=data.get("template_type", "news_explainer"),
        lang=data.get("lang", "ko"),
        tts_provider=data.get("tts_provider", "edge"),
        voice_gender=data.get("voice_gender", "female"),
        subtitle_style=data.get("subtitle_style", ""),
        tone=data.get("tone", "casual_heyo"),
        target_duration=data.get("target_duration", "30s"),
        custom_instruction=data.get("custom_instruction", ""),
    )
    thread = threading.Thread(
        target=_batch_manager.run_batch,
        args=(batch_id, _execute_draft_fn),
        daemon=True,
    )
    thread.start()
    return jsonify({"ok": True, "batch_id": batch_id}), 202


@admin_bp.route("/api/batch/<batch_id>", methods=["GET", "DELETE"])
def batch_detail_route(batch_id: str):
    if flask_request.method == "DELETE":
        if _batch_manager.delete_batch(batch_id):
            return jsonify({"ok": True})
        job = _batch_manager.get_status(batch_id)
        if job and job.status == "running":
            return jsonify({"ok": False, "error": "cannot delete running batch"}), 409
        return jsonify({"ok": False, "error": "batch not found"}), 404
    job = _batch_manager.get_status(batch_id)
    if not job:
        return jsonify({"ok": False, "error": "batch not found"}), 404
    return jsonify({"ok": True, **job.to_dict()})


@admin_bp.route("/api/batch", methods=["GET"])
def list_batches_route():
    return jsonify({"ok": True, "batches": _batch_manager.list_jobs()})


# ---------------------------------------------------------------------------
# Job queue
# ---------------------------------------------------------------------------

@admin_bp.route("/api/jobs", methods=["GET", "POST"])
def jobs_route():
    if flask_request.method == "POST":
        payload = flask_request.get_json(silent=True) or {}
        if not payload.get("prompt", "").strip():
            return jsonify({"ok": False, "error": "prompt is required"}), 400
        job_id = _job_queue.submit(payload)
        return jsonify({"ok": True, "job_id": job_id}), 202
    return jsonify({"ok": True, "jobs": _job_queue.list_jobs()})


@admin_bp.route("/api/jobs/<job_id>", methods=["GET", "DELETE"])
def job_detail_route(job_id: str):
    if flask_request.method == "DELETE":
        if _job_queue.delete_job(job_id):
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "job not found or still running"}), 404
    job = _job_queue.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404
    return jsonify({"ok": True, **job.to_dict()})


# ---------------------------------------------------------------------------
# Draft delete
# ---------------------------------------------------------------------------

@admin_bp.route("/api/draft/<draft_id>", methods=["DELETE"])
def delete_draft_route(draft_id: str):
    safe_path = _safe_resolve(str(_capcut_draft_dir / draft_id), _capcut_draft_dir)
    if not safe_path:
        return jsonify({"ok": False, "error": "invalid draft id"}), 400
    if safe_path.exists() and safe_path.is_dir():
        shutil.rmtree(safe_path, ignore_errors=True)
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "draft not found"}), 404


# ---------------------------------------------------------------------------
# Usage stats
# ---------------------------------------------------------------------------

@admin_bp.route("/api/usage-stats", methods=["GET"])
def usage_stats_route():
    session = get_session_stats()
    limits: dict = {}

    try:
        from worker.usage.limits import next_daily_reset_utc, next_hourly_reset_utc

        daily = get_daily_stats("gemini-2.5-flash")
        gemini_info = FREE_TIER_LIMITS.get("gemini-2.5-flash", {})
        gemini_used = daily["calls"]
        gemini_limit = gemini_info.get("rpd", 250)
        limits["gemini-2.5-flash"] = {
            "cycle": "daily",
            "used": gemini_used,
            "limit": gemini_limit,
            "remaining": max(0, gemini_limit - gemini_used),
            "reset_at": next_daily_reset_utc(),
        }

        pexels_hour = get_hourly_stats("pexels")
        pexels_month = get_monthly_stats("pexels")
        pexels_info = FREE_TIER_LIMITS.get("pexels", {})
        limits["pexels"] = {
            "cycle": "hourly+monthly",
            "used_hour": pexels_hour["calls"],
            "limit_hour": pexels_info.get("rph", 200),
            "used_month": pexels_month["calls"],
            "limit_month": pexels_info.get("rpm_month", 20_000),
            "reset_at_hour": next_hourly_reset_utc(),
        }

        tts_month = get_monthly_stats("google-tts")
        tts_info = FREE_TIER_LIMITS.get("google-tts", {})
        limits["google-tts"] = {
            "cycle": "monthly",
            "used_chars": int(tts_month["total_units"]),
            "limit_chars": tts_info.get("wavenet_chars", 1_000_000),
        }

        for prov in ("imagen", "serper", "veo3", "dalle3", "sora2"):
            prov_month = get_monthly_stats(prov)
            limits[prov] = {
                "cycle": "none",
                "total_calls": prov_month["calls"],
                "total_cost_usd": round(prov_month["cost_usd"], 4),
            }

        monthly_total = get_monthly_total_cost()
    except Exception as e:
        print(f"[usage] usage_stats_route failed: {e}")
        monthly_total = 0.0

    return jsonify({
        "ok": True,
        "session_id": _USAGE_SESSION_ID,
        "session": session,
        "limits": limits,
        "monthly_total_cost_usd": round(monthly_total, 4),
    })
