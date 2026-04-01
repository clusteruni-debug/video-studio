"""Media routes — scene-level TTS regeneration, image generation, dubbing.

Extracted from server.py to keep the main bridge under the 660-line limit.
"""
from __future__ import annotations

import time
from pathlib import Path

from flask import Blueprint, jsonify, request as flask_request

from worker.tts.providers import generate_tts
from worker.bridge.image_router import route_image
from worker.bridge.layouts import DEFAULT_TTS_RATE

media_bp = Blueprint("media", __name__)

# These are set by server.py at registration time
_bridge_host: str = "127.0.0.1"
_bridge_port: int = 5161
_tts_dir: Path = Path("storage/tts")
_project_root: Path = Path.cwd()
_get_audio_duration = None
_image_url_for_client = None
_safe_resolve = None

# Normalize source names so round-trip regeneration works:
# route_image returns "klipy" but expects "tenor" as input.
_SOURCE_NORMALIZE: dict[str, str] = {"imagen3": "imagen", "klipy": "tenor"}


def init_media_routes(
    bridge_host: str, bridge_port: int, tts_dir: Path, project_root: Path,
    get_audio_duration, image_url_for_client, safe_resolve,
):
    global _bridge_host, _bridge_port, _tts_dir, _project_root
    global _get_audio_duration, _image_url_for_client, _safe_resolve
    _bridge_host = bridge_host
    _bridge_port = bridge_port
    _tts_dir = tts_dir
    _project_root = project_root
    _get_audio_duration = get_audio_duration
    _image_url_for_client = image_url_for_client
    _safe_resolve = safe_resolve


# ---------------------------------------------------------------------------
# Scene-level TTS regeneration
# ---------------------------------------------------------------------------

@media_bp.route("/api/regenerate-scene-tts", methods=["POST"])
def regenerate_scene_tts_route():
    """Regenerate TTS for a single scene after narration edit."""
    data = flask_request.get_json(silent=True) or {}
    narration = data.get("narration", "").strip()
    if not narration:
        return jsonify({"ok": False, "error": "narration is required"}), 400
    try:
        scene_num = max(1, min(int(data.get("scene_num", 1)), 100))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "invalid scene_num"}), 400
    lang = data.get("lang", "ko")
    tts_provider = data.get("tts_provider", "edge")
    voice_gender = data.get("voice_gender", "female")

    regen_ts = str(int(time.time()))
    regen_dir = _tts_dir / regen_ts
    regen_dir.mkdir(parents=True, exist_ok=True)
    audio_path = regen_dir / f"scene_{scene_num}.mp3"

    try:
        generate_tts(
            text=narration, lang=lang, gender=voice_gender,
            provider=tts_provider, output_path=audio_path,
            rate=DEFAULT_TTS_RATE, pitch="+0Hz",
        )
        duration = _get_audio_duration(str(audio_path))
        tts_url = f"http://{_bridge_host}:{_bridge_port}/api/tts/{regen_ts}/scene_{scene_num}.mp3"
        return jsonify({"ok": True, "_tts_url": tts_url, "duration": round(duration, 1)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Image generation / search (single scene)
# ---------------------------------------------------------------------------

@media_bp.route("/api/generate-image", methods=["POST"])
def generate_image_route():
    """Generate or search for an image using the server-side route_image pipeline."""
    data = flask_request.get_json(silent=True) or {}
    image_prompt = data.get("image_prompt", "").strip()
    if not image_prompt:
        return jsonify({"ok": False, "error": "image_prompt is required"}), 400

    raw_source = data.get("image_source", "")
    normalized_source = _SOURCE_NORMALIZE.get(raw_source, raw_source)

    scene = {
        "image_prompt": image_prompt,
        "image_source": normalized_source,
        "emotion": data.get("emotion", "neutral"),
        "fallback_prompt": data.get("fallback_prompt", ""),
    }
    try:
        raw_url, source = route_image(scene)
        client_url = _image_url_for_client(raw_url)
        display_source = _SOURCE_NORMALIZE.get(source, source) if source else source
        if client_url:
            return jsonify({"ok": True, "image_url": client_url, "source": display_source})
        return jsonify({"ok": False, "error": "No image found for this prompt"}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Translation / Dubbing
# ---------------------------------------------------------------------------

@media_bp.route("/api/dub", methods=["POST"])
def dub_route():
    """Transcribe + translate + generate TTS for a foreign-language audio file."""
    data = flask_request.get_json(silent=True) or {}
    source_path = data.get("source_path", "").strip()
    if not source_path:
        return jsonify({"ok": False, "error": "source_path is required"}), 400
    source = _safe_resolve(source_path, _project_root)
    if not source or not source.exists():
        return jsonify({"ok": False, "error": "File not found or path not allowed"}), 400

    target_lang = data.get("target_lang", "ko")
    tts_provider = data.get("tts_provider", "edge")
    voice_gender = data.get("voice_gender", "female")
    whisper_model = data.get("whisper_model", "base")
    style = data.get("style", "natural")

    try:
        from worker.translation.dubbing import dub_audio
        result = dub_audio(
            source_audio=source,
            target_lang=target_lang,
            tts_provider=tts_provider,
            voice_gender=voice_gender,
            whisper_model=whisper_model,
            translation_style=style,
        )
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
