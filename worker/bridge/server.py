"""
Bridge Server — prompt → Gemini script → TTS → VectCutAPI → CapCut draft.
Endpoints:
  GET  /api/health          — status of bridge, VectCutAPI, TTS providers
  POST /api/create-draft    — full pipeline: prompt → CapCut draft
  GET  /api/tts/<filename>  — serves generated TTS audio files

Pipeline orchestration lives in :mod:`worker.bridge.draft_executor`. This
file wires the Flask app, route handlers, and startup logging only.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.cwd() / ".env", override=False)

logger = logging.getLogger(__name__)

from flask import Flask, jsonify, request as flask_request, send_from_directory
from flask_cors import CORS

from worker.tts.providers import available_providers
from worker.media.adapters import probe_local_media_adapters
from worker.media.provider_policy import allowed_preference
from worker.bridge.image_router import zero_paid_policy_status
from worker.bridge.templates import TEMPLATE_TYPES
from worker.bridge.scene_generator import TONE_PRESETS
from worker.bridge.batch import BatchManager
from worker.bridge.job_queue import JobQueue
from worker.bridge.cleanup import cleanup_storage, format_size
from worker.bridge.routes_media import media_bp, init_media_routes
from worker.bridge.routes_grok import grok_bp, init_grok_routes
from worker.bridge.routes_sources import sources_bp, init_source_routes
from worker.bridge.routes_admin import admin_bp, init_admin_routes
from worker.bridge.draft_executor import (
    BRIDGE_HOST,
    BRIDGE_PORT,
    CAPCUT_DRAFT_DIR,
    IMAGE_CACHE_DIR,
    PROJECT_ROOT,
    TTS_DIR,
    execute_draft_core,
    get_audio_duration,
    image_url_for_client,
    safe_resolve,
)
from worker.usage.db import init_db as _init_usage_db

# VectCutAPI access is fully encapsulated in worker.bridge.vectcut_bridge
from worker.bridge.vectcut_bridge import VECTCUT_DIR

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

UI_DEV_CORS_ORIGINS = [
    "http://127.0.0.1:5160",
    "http://localhost:5160",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4160",
    "http://localhost:4160",
]

app = Flask(__name__)
CORS(app, origins=UI_DEV_CORS_ORIGINS)

batch_manager = BatchManager()
job_queue = JobQueue()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def _bridge_availability(data: dict):
    from worker.media.model_router import ProviderAvailability

    availability_data = data.get("availability") or {}
    return ProviderAvailability(
        veo3=bool(availability_data.get("veo3", False)),
        premium_enabled=bool(
            availability_data.get("premiumEnabled", availability_data.get("premium_enabled", False))
        ),
    )


@app.route("/api/health", methods=["GET"])
def health():
    vectcut_ok = False
    try:
        from worker.bridge.vectcut_bridge import _get_vectcut
        _get_vectcut()
        vectcut_ok = True
    except (ImportError, RuntimeError) as vc_err:
        # Health endpoint should report missing-but-not-crashed state.
        logger.debug("vectcut health check failed: %s", vc_err)
    adapters = probe_local_media_adapters(PROJECT_ROOT)
    zero_paid = zero_paid_policy_status()
    planner_backend = "gemini" if GEMINI_API_KEY else "sample"
    return jsonify({
        "bridge": "ok",
        "vectcut": "library" if vectcut_ok else "missing",
        "planner": {
            "backend": planner_backend,
            "model": "gemini-2.5-flash" if GEMINI_API_KEY else "sample-local",
            "fallbackUsed": not bool(GEMINI_API_KEY),
        },
        "zero_paid": zero_paid,
        "provider_policy": {
            "image": allowed_preference("image"),
            "video": allowed_preference("video"),
            "tts": allowed_preference("tts"),
            "bgm": allowed_preference("bgm"),
            "sfx": allowed_preference("sfx"),
        },
        "media": {key: status.to_dict() for key, status in adapters.items()},
        "tts_providers": available_providers(),
        "pexels": "ready" if os.environ.get("PEXELS_API_KEY", "") else "no_key",
        "klipy": "ready" if os.environ.get("KLIPY_API_KEY", "") else "no_key",
        "groq": "ready" if GROQ_API_KEY else "no_key",
        "gemini": "ready" if GEMINI_API_KEY else "no_key",
        "template_types": list(TEMPLATE_TYPES),
        "tone_presets": {k: v["label"] for k, v in TONE_PRESETS.items()},
        "capcut_draft_dir": str(CAPCUT_DRAFT_DIR),
        "capcut_draft_dir_exists": CAPCUT_DRAFT_DIR.exists(),
    })


@app.route("/api/route-plan", methods=["POST"])
def route_plan_route():
    """Compatibility route for planner verification and local automation."""
    data = flask_request.get_json(silent=True) or {}
    prompt = str(data.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"ok": False, "error": "prompt is required"}), 400

    try:
        from worker.media.model_router import route_project_plan, summarize_cost
        from worker.planner.ollama_planner import build_project_plan

        plan, planner = build_project_plan(
            prompt,
            budget_mode=data.get("budgetMode", "free"),
            planner_mode=data.get("plannerMode", "auto"),
        )
        decisions = route_project_plan(plan, _bridge_availability(data))
    except Exception as exc:
        logger.warning("route_plan_route failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({
        "ok": True,
        "plan": plan.to_dict(),
        "planner": planner.to_dict(),
        "routes": [decision.to_dict() for decision in decisions],
        "estimatedTotalCostUsd": summarize_cost(decisions),
    })


@app.route("/api/save-project", methods=["POST"])
def save_project_route():
    """Compatibility route for saving a planned project bundle under storage/."""
    data = flask_request.get_json(silent=True) or {}
    prompt = str(data.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"ok": False, "error": "prompt is required"}), 400

    try:
        from worker.planner.save_plan import save_project_bundle

        payload = save_project_bundle(
            prompt=prompt,
            budget_mode=data.get("budgetMode", "free"),
            availability=_bridge_availability(data),
            planner_mode=data.get("plannerMode", "auto"),
            project_id=data.get("projectId"),
            project_root=PROJECT_ROOT,
            scene_assets=data.get("sceneAssets"),
            provider_overrides=data.get("providerOverrides"),
            draft_scenes=data.get("draftScenes"),
            selected_pexels_videos=data.get("selectedPexelsVideos"),
            subtitle_style=data.get("subtitleStyle", ""),
            bgm_enabled=bool(data.get("bgmEnabled", True)),
            bgm_asset=data.get("bgmAsset") or data.get("selectedBgmAsset"),
            template_type=str(data.get("templateType") or data.get("template_type") or ""),
        )
    except Exception as exc:
        logger.warning("save_project_route failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    payload["ok"] = True
    return jsonify(payload)


@app.route("/api/tts/<path:filename>", methods=["GET"])
def serve_tts(filename: str):
    return send_from_directory(str(TTS_DIR), filename)


@app.route("/api/bgm/<path:filename>", methods=["GET"])
def serve_bgm(filename: str):
    return send_from_directory(str(PROJECT_ROOT / "assets" / "bgm"), filename)


@app.route("/api/images/<path:filename>", methods=["GET"])
def serve_image(filename: str):
    """Serve generated images from storage/cache (e.g. Imagen results)."""
    return send_from_directory(str(IMAGE_CACHE_DIR), filename)


@app.route("/api/thumbnail", methods=["POST"])
def generate_thumbnail_route():
    """Generate a thumbnail from a rendered video or image."""
    data = flask_request.get_json(silent=True) or {}
    source_path = data.get("source_path", "").strip()
    if not source_path:
        return jsonify({"ok": False, "error": "source_path is required"}), 400
    source = safe_resolve(source_path, PROJECT_ROOT)
    if not source or not source.exists():
        return jsonify({"ok": False, "error": "File not found or path not allowed"}), 400

    text = data.get("text", "")
    try:
        timestamp = float(data.get("timestamp_sec", 1.5))
    except (TypeError, ValueError):
        timestamp = 1.5
    output_dir = PROJECT_ROOT / "storage" / "thumbnails"
    output_path = output_dir / f"{source.stem}_thumb.png"

    from worker.render.thumbnail import generate_thumbnail, generate_thumbnail_from_image

    is_video = source.suffix.lower() in {".mp4", ".mov", ".webm", ".avi", ".mkv"}
    if is_video:
        ok = generate_thumbnail(source, output_path, text=text, timestamp_sec=timestamp)
    else:
        ok = generate_thumbnail_from_image(source, output_path, text=text)

    if ok:
        return jsonify({"ok": True, "thumbnail_path": str(output_path)})
    return jsonify({"ok": False, "error": "Thumbnail generation failed"}), 500


@app.route("/api/align-tts", methods=["POST"])
def align_tts_route():
    """Extract per-word timestamps from a WAV file using faster-whisper.

    Input JSON: {"wav_path": str, "language": "ko"|"en", "text": str (optional fallback)}
    Output JSON: {"ok": true, "words": [{"word": str, "start": float, "end": float}, ...]}
    """
    data = flask_request.get_json(silent=True) or {}
    wav_path = data.get("wav_path", "").strip()
    language = data.get("language", "ko")
    fallback_text = data.get("text", "")
    try:
        fallback_duration = float(data.get("duration_sec", 0))
    except (TypeError, ValueError):
        fallback_duration = 0.0

    if not wav_path:
        return jsonify({"ok": False, "error": "wav_path is required"}), 400

    resolved = safe_resolve(wav_path, PROJECT_ROOT)
    if not resolved or not resolved.exists():
        return jsonify({"ok": False, "error": "WAV file not found or path not allowed"}), 400

    from worker.render.align import align_tts, align_tts_fallback

    try:
        words = align_tts(str(resolved), language=language)
    except ImportError:
        # faster-whisper not installed — use proportional fallback.
        # Note: this branch is only reachable on the FIRST call to align_tts
        # in the process lifetime. After that, faster-whisper is cached in
        # ``sys.modules`` and a subsequent ImportError cannot fire. Keep the
        # branch for the initial-boot window; the broader ``except Exception``
        # below handles post-import runtime failures (CUDA DLL missing, model
        # download errors, etc.).
        if fallback_text and fallback_duration > 0:
            words = align_tts_fallback(fallback_text, fallback_duration)
        else:
            return jsonify({
                "ok": False,
                "error": "faster-whisper not installed and no fallback text/duration provided",
            }), 500
    except Exception as e:
        # faster-whisper raises a handful of model-load/runtime errors that
        # vary by backend (CTranslate2, CUDA, etc.); catch broadly so we can
        # still fall back to proportional alignment and log the failure.
        logger.warning("align_tts failed, trying fallback: %s", e)
        if fallback_text and fallback_duration > 0:
            words = align_tts_fallback(fallback_text, fallback_duration)
        else:
            return jsonify({"ok": False, "error": f"Alignment failed: {e}"}), 500

    return jsonify({"ok": True, "words": words})


@app.route("/api/create-draft", methods=["POST"])
def create_draft_route():
    data = flask_request.get_json(silent=True) or {}
    try:
        result = execute_draft_core(data)
    except Exception as e:
        # Flask route handler: broad catch required to convert any downstream
        # failure into a 500 response; log for observability.
        logger.warning("create_draft_route failed: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500
    if not result.get("ok"):
        status = 400 if result.get("error") == "prompt is required" else 500
        return jsonify(result), status
    return jsonify(result)


# ---------------------------------------------------------------------------
# POST /api/render-mp4 — convert create-draft scenes → FFmpeg MP4 via compose
# ---------------------------------------------------------------------------

@app.route("/api/render-mp4", methods=["POST"])
def render_mp4_route():
    """Render MP4 from pre-built scene data.
    Requires {"draft_scenes": [...], "prompt": "..."} — call /api/create-draft first,
    then pass the _internal_scenes array here."""
    from worker.bridge.draft_render import prepare_and_render

    data = flask_request.get_json(silent=True) or {}
    scenes = data.get("draft_scenes")
    if not scenes:
        return jsonify({"ok": False, "error": "draft_scenes is required. Call /api/create-draft first."}), 400

    topic = data.get("prompt", "Untitled")
    render_result = prepare_and_render(scenes, topic)
    return jsonify(render_result)


@app.route("/api/render-smoke", methods=["POST"])
def render_smoke_route():
    """Save a zero-paid project bundle and render it through the FFmpeg smoke path."""
    data = flask_request.get_json(silent=True) or {}
    prompt = str(data.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"ok": False, "error": "prompt is required"}), 400

    try:
        from worker.planner.save_plan import save_project_bundle
        from worker.render.compose import compose_smoke_render

        payload = save_project_bundle(
            prompt=prompt,
            budget_mode=data.get("budgetMode", "free"),
            availability=_bridge_availability(data),
            planner_mode=data.get("plannerMode", "auto"),
            project_id=data.get("projectId"),
            project_root=PROJECT_ROOT,
            scene_assets=data.get("sceneAssets"),
            provider_overrides=data.get("providerOverrides"),
            draft_scenes=data.get("draftScenes"),
            selected_pexels_videos=data.get("selectedPexelsVideos"),
            subtitle_style=data.get("subtitleStyle", ""),
            bgm_enabled=bool(data.get("bgmEnabled", True)),
            bgm_asset=data.get("bgmAsset") or data.get("selectedBgmAsset"),
            template_type=str(data.get("templateType") or data.get("template_type") or ""),
        )
        render_result = compose_smoke_render(
            payload["saveResult"]["manifestPath"],
            project_root=PROJECT_ROOT,
        )
    except Exception as exc:
        logger.warning("render_smoke_route failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    payload["ok"] = bool(render_result.ok)
    payload["renderResult"] = render_result.to_dict()
    status = 200 if render_result.ok else 500
    return jsonify(payload), status


# ---------------------------------------------------------------------------
# Blueprint registration + helpers shared with route modules
# ---------------------------------------------------------------------------

init_media_routes(
    BRIDGE_HOST, BRIDGE_PORT, TTS_DIR, PROJECT_ROOT,
    get_audio_duration, image_url_for_client, safe_resolve,
)
init_grok_routes(BRIDGE_HOST, BRIDGE_PORT, PROJECT_ROOT, safe_resolve)
init_source_routes(execute_draft_core)
init_admin_routes(
    PROJECT_ROOT, CAPCUT_DRAFT_DIR, batch_manager, job_queue,
    execute_draft_core, safe_resolve,
)

app.register_blueprint(media_bp)
app.register_blueprint(grok_bp)
app.register_blueprint(sources_bp)
app.register_blueprint(admin_bp)

job_queue.set_execute_fn(execute_draft_core)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _init_usage_db()
    logger.info("Bridge server: http://%s:%d", BRIDGE_HOST, BRIDGE_PORT)
    logger.info("  TTS providers : %s", available_providers())
    logger.info("  Groq          : %s", 'ready' if GROQ_API_KEY else 'no key')
    logger.info("  Gemini        : %s", 'ready' if GEMINI_API_KEY else 'no key')
    logger.info("  Pexels        : %s", 'ready' if os.environ.get('PEXELS_API_KEY', '') else 'no key (no stock images)')
    logger.info("  Klipy         : %s", 'ready' if os.environ.get('KLIPY_API_KEY', '') else 'no key (no meme/GIF)')
    logger.info("  Templates     : %s", ', '.join(TEMPLATE_TYPES))
    logger.info("  VectCutAPI    : %s", VECTCUT_DIR)
    logger.info("  CapCut drafts : %s", CAPCUT_DRAFT_DIR)

    # Auto-cleanup stale assets on startup (7+ days old)
    try:
        result = cleanup_storage(PROJECT_ROOT, CAPCUT_DRAFT_DIR, max_age_days=7)
        total_removed = sum(v.get("removed", 0) for v in result.values())
        total_freed = sum(v.get("freed_bytes", 0) for v in result.values())
        if total_removed > 0:
            logger.info("  Cleanup       : %d stale items removed (%s freed)", total_removed, format_size(total_freed))
        else:
            logger.info("  Cleanup       : nothing to clean")
    except Exception as e:
        # cleanup_storage walks the filesystem and may hit permissions,
        # stale-NFS, or missing dirs; keep broad so startup never blocks.
        logger.warning("  Cleanup       : failed (%s)", e)

    app.run(host=BRIDGE_HOST, port=BRIDGE_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
