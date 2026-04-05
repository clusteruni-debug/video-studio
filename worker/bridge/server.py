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
from worker.bridge.templates import TEMPLATE_TYPES
from worker.bridge.scene_generator import TONE_PRESETS
from worker.bridge.batch import BatchManager
from worker.bridge.job_queue import JobQueue
from worker.bridge.cleanup import cleanup_storage, format_size
from worker.bridge.routes_media import media_bp, init_media_routes
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

app = Flask(__name__)
CORS(app, origins=["http://127.0.0.1:5160", "http://localhost:5160"])

batch_manager = BatchManager()
job_queue = JobQueue()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
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
    return jsonify({
        "bridge": "ok",
        "vectcut": "library" if vectcut_ok else "missing",
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
        # faster-whisper not installed — use proportional fallback
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


# ---------------------------------------------------------------------------
# Blueprint registration + helpers shared with route modules
# ---------------------------------------------------------------------------

init_media_routes(
    BRIDGE_HOST, BRIDGE_PORT, TTS_DIR, PROJECT_ROOT,
    get_audio_duration, image_url_for_client, safe_resolve,
)
init_source_routes(execute_draft_core)
init_admin_routes(
    PROJECT_ROOT, CAPCUT_DRAFT_DIR, batch_manager, job_queue,
    execute_draft_core, safe_resolve,
)

app.register_blueprint(media_bp)
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
