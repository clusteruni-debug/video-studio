"""
Bridge Server — prompt → Gemini script → TTS → VectCutAPI → CapCut draft.
Endpoints:
  GET  /api/health          — status of bridge, VectCutAPI, TTS providers
  POST /api/create-draft    — full pipeline: prompt → CapCut draft
  GET  /api/tts/<filename>  — serves generated TTS audio files
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from urllib import request as urllib_request

from dotenv import load_dotenv

load_dotenv(Path.cwd() / ".env", override=False)

from flask import Flask, jsonify, request as flask_request, send_from_directory
from flask_cors import CORS

from worker.tts.providers import generate_tts, available_providers
from worker.bridge.templates import TEMPLATE_TYPES
from worker.bridge.scene_generator import (
    TONE_PRESETS,
    generate_scenes_llm,
    wrap_narration,
)
from worker.bridge.batch import BatchManager
from worker.bridge.job_queue import JobQueue
from worker.bridge.image_router import route_image
from worker.bridge.cleanup import cleanup_storage, format_size
from worker.bridge.routes_media import media_bp, init_media_routes
from worker.bridge.routes_sources import sources_bp, init_source_routes
from worker.bridge.routes_admin import admin_bp, init_admin_routes

import random
from worker.bridge.layouts import (
    DEFAULT_TTS_RATE,
    DEFAULT_TTS_RATE_COMMENTARY,
    TEMPLATE_BGM_MOOD,
    SUBTITLE_STYLE_MAP,
    TEMPLATE_LAYOUTS,
    DEFAULT_LAYOUT,
)
from worker.usage.db import (
    init_db as _init_usage_db,
    SESSION_ID as _USAGE_SESSION_ID,
    get_session_stats,
    get_daily_stats,
    get_monthly_stats,
    get_hourly_stats,
    get_monthly_total_cost,
)
from worker.usage.limits import FREE_TIER_LIMITS

# VectCutAPI access is fully encapsulated in worker.bridge.vectcut_bridge
from worker.bridge.vectcut_bridge import (
    VECTCUT_DIR,
    create_capcut_draft,
    add_image as vb_add_image,
    add_subtitle as vb_add_subtitle,
    add_narration as vb_add_narration,
    add_bgm as vb_add_bgm,
    save_draft_to_capcut,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 5161
PROJECT_ROOT = Path.cwd()
TTS_DIR = PROJECT_ROOT / "storage" / "tts"
CAPCUT_DRAFT_DIR = Path(os.environ.get(
    "CAPCUT_DRAFT_DIR",
    str(Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"),
))
IMAGE_CACHE_DIR = PROJECT_ROOT / "storage" / "cache"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

app = Flask(__name__)
CORS(app)

batch_manager = BatchManager()
job_queue = JobQueue()


# Template layouts, subtitle styles, and BGM mood mapping are in layouts.py



import re as _re


def _split_sentences(text: str) -> list[str]:
    """Split Korean narration into display sentences for sequential subtitles."""
    # Split on newlines first, then on Korean sentence endings
    parts: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Split on sentence-ending patterns (요. 요! 요? 다. 다! 다? etc.)
        sents = _re.split(r'(?<=[.!?])\s+', line)
        for s in sents:
            s = s.strip()
            if s:
                parts.append(s)
    return parts if parts else [text]


# ---------------------------------------------------------------------------
# Audio duration — ffprobe
# ---------------------------------------------------------------------------
def _get_audio_duration(file_path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-print_format", "json", file_path],
            capture_output=True, text=True, timeout=10,
        )
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except Exception as e:
        print(f"[ffprobe] Failed for {file_path}: {e}")
        return 5.0  # fallback 5 seconds


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
    except Exception:
        pass
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


def _image_url_for_client(raw_url: str | None) -> str | None:
    """Convert local file paths to bridge-accessible URLs; pass through HTTP URLs."""
    if not raw_url:
        return None
    if raw_url.startswith(("http://", "https://")):
        return raw_url
    # Local file path (e.g. from Imagen) → serve via /api/images/
    try:
        p = Path(raw_url).resolve()
    except (OSError, ValueError):
        return None
    cache_root = IMAGE_CACHE_DIR.resolve()
    # Only serve files under storage/cache — use trailing sep to prevent prefix collision
    cache_prefix = str(cache_root) + os.sep
    if str(p).startswith(cache_prefix) or p.parent == cache_root:
        return f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/api/images/{p.name}"
    # File is outside cache — copy it in so the serve endpoint can find it
    if p.exists():
        import shutil
        dest = cache_root / p.name
        if not dest.exists():
            cache_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
        return f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/api/images/{p.name}"
    return None


def _safe_resolve(user_path: str, allowed_root: Path) -> Path | None:
    """Resolve *user_path* and verify it is under *allowed_root*."""
    try:
        resolved = Path(user_path).resolve()
    except (OSError, ValueError):
        return None
    if not str(resolved).startswith(str(allowed_root.resolve())):
        return None
    return resolved


@app.route("/api/thumbnail", methods=["POST"])
def generate_thumbnail_route():
    """Generate a thumbnail from a rendered video or image."""
    data = flask_request.get_json(silent=True) or {}
    source_path = data.get("source_path", "").strip()
    if not source_path:
        return jsonify({"ok": False, "error": "source_path is required"}), 400
    source = _safe_resolve(source_path, PROJECT_ROOT)
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


@app.route("/api/create-draft", methods=["POST"])
def create_draft_route():
    data = flask_request.get_json(silent=True) or {}
    topic = data.get("prompt", "").strip()
    if not topic:
        return jsonify({"ok": False, "error": "prompt is required"}), 400
    lang = data.get("lang", "ko")
    tts_provider = data.get("tts_provider", "edge")
    voice_gender = data.get("voice_gender", "female")
    template_type = data.get("template_type", "news_explainer")
    tone = data.get("tone", "casual_heyo")
    subtitle_style = data.get("subtitle_style", "")
    target_duration = data.get("target_duration", "30s")
    custom_instruction = data.get("custom_instruction", "")

    steps_log = []
    # ── Step 1: Generate script ──────────────────────────────────────────
    scenes, script_source = generate_scenes_llm(
        topic, lang, template_type, tone,
        target_duration=target_duration,
        custom_instruction=custom_instruction,
    )
    wrap_narration(scenes)
    steps_log.append(f"script: {len(scenes)} scenes ({script_source}, {template_type}, topic={topic[:30]})")

    # ── Step 2: Generate TTS for each scene ──────────────────────────────
    draft_ts = str(int(time.time()))
    tts_subdir = TTS_DIR / draft_ts
    tts_subdir.mkdir(parents=True, exist_ok=True)

    for scene in scenes:
        n = scene["scene_num"]
        audio_path = tts_subdir / f"scene_{n}.mp3"

        # Determine TTS tone based on scene metadata
        tts_rate = DEFAULT_TTS_RATE
        tts_pitch = "+0Hz"
        tts_text = scene["narration"]
        if scene.get("is_commentary"):
            tts_rate = DEFAULT_TTS_RATE_COMMENTARY
            tts_pitch = "+0Hz"
        if scene.get("rank") is not None and tts_text.strip():
            # Rank slides: add a brief text pause for dramatic effect
            # (SSML is NOT supported by edge-tts or ElevenLabs — use text ellipsis instead)
            tts_text = f"... {tts_text}"

        if not tts_text.strip():
            print(f"[tts] scene {n}: empty narration, skipping TTS")
            scene["_tts_path"] = None
            scene["_tts_duration"] = 3.0
            scene["_tts_url"] = None
            continue

        try:
            generate_tts(
                text=tts_text,
                lang=lang,
                gender=voice_gender,
                provider=tts_provider,
                output_path=audio_path,
                rate=tts_rate,
                pitch=tts_pitch,
            )
            scene["_tts_path"] = str(audio_path)
            scene["_tts_duration"] = _get_audio_duration(str(audio_path))
            scene["_tts_url"] = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/api/tts/{draft_ts}/scene_{n}.mp3"
        except Exception as e:
            print(f"[tts] scene {n} failed: {e}")
            scene["_tts_path"] = None
            scene["_tts_duration"] = 5.0
            scene["_tts_url"] = None
    steps_log.append(f"tts: {tts_provider}")

    # ── Step 3: Search images via emotion-based routing ─────────────────
    image_sources_used = set()
    for scene in scenes:
        img_url, used_source = route_image(scene)
        scene["_image_url"] = img_url
        if img_url and used_source:
            scene["image_source"] = _SOURCE_NORMALIZE.get(used_source, used_source)
            image_sources_used.add(used_source)
    has_images = any(s.get("_image_url") for s in scenes)
    steps_log.append(f"images: {'+'.join(sorted(image_sources_used)) if image_sources_used else 'none'}")

    # ── Step 4: Build CapCut draft via VectCutAPI (bridge module) ─────────
    try:
        script, draft_id = create_capcut_draft(1080, 1920)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    cumulative_time = 0.0
    layout = TEMPLATE_LAYOUTS.get(template_type, DEFAULT_LAYOUT)
    for scene in scenes:
        n = scene["scene_num"]
        dur = scene.get("_tts_duration", 5.0) + 0.5
        is_hook = (n == 1)
        is_rank_scene = scene.get("rank") is not None
        is_commentary = scene.get("is_commentary", False)

        # ── Background image with structural layout ──
        default_trans = layout.get("default_transition", "Dissolve")
        scene_transition = scene.get("transition", default_trans) if n > 1 else None
        if scene_transition == "none":
            scene_transition = None
        img_ref = scene.get("_image_url")
        if img_ref:
            if not img_ref.startswith(("http://", "https://")):
                img_ref = Path(img_ref).resolve().as_uri()
            img_cfg = layout.get("img", {})
            img_params = {
                "scale_x": img_cfg.get("scale_x", 1.3),
                "scale_y": img_cfg.get("scale_y", 1.3),
            }
            if img_cfg.get("background_blur"):
                img_params["background_blur"] = img_cfg["background_blur"]
            if img_cfg.get("transform_y") is not None:
                img_params["transform_y"] = img_cfg["transform_y"]
            if img_cfg.get("mask_type"):
                img_params["mask_type"] = img_cfg["mask_type"]
            vb_add_image(
                draft_id, img_ref, cumulative_time, cumulative_time + dur,
                transition=scene_transition, **img_params,
            )

        # ── Text narration with structural layout ──
        subtitle_text = scene["narration"]
        base_text = layout.get("text", {})
        text_params = {
            "font_color": base_text.get("font_color", "#FFFFFF"),
            "font_size": base_text.get("font_size", 13.0),
            "transform_y": base_text.get("transform_y", -0.35),
            "border_width": 0.12,
            "shadow_distance": base_text.get("shadow_distance", 5.0),
            "intro_animation": base_text.get("intro_animation", "Fade_In"),
        }
        if base_text.get("background_color"):
            text_params["background_color"] = base_text["background_color"]
            text_params["background_alpha"] = base_text.get("background_alpha", 0.5)

        # Hook scene overrides
        if is_hook:
            hook_cfg = layout.get("hook", {}).get("text", {})
            text_params.update({k: v for k, v in hook_cfg.items() if v is not None})
        # Rank scene overrides + badge layer
        elif is_rank_scene and layout.get("rank"):
            rank_cfg = layout["rank"]
            rank_text_ov = rank_cfg.get("text", {})
            text_params.update({k: v for k, v in rank_text_ov.items() if v is not None})
            # Add rank badge as separate text layer
            badge_cfg = rank_cfg.get("badge")
            if badge_cfg:
                rank_label = f"{scene['rank']}"
                if template_type == "tutorial_steps":
                    rank_label = f"Step {scene['rank']}"
                vb_add_subtitle(
                    draft_id, rank_label,
                    cumulative_time, cumulative_time + dur,
                    scene_num=n + 100,  # unique track offset
                    font_color=badge_cfg.get("font_color", "#FFD700"),
                    font_size=badge_cfg.get("font_size", 28.0),
                    transform_y=badge_cfg.get("transform_y", -0.08),
                    background_color=badge_cfg.get("background_color", ""),
                    background_alpha=badge_cfg.get("background_alpha", 0.0),
                    intro_animation=badge_cfg.get("intro_animation", "Fade_In"),
                )
        # Commentary scene overrides (reddit_translation)
        elif is_commentary and layout.get("commentary"):
            comm_text_ov = layout["commentary"].get("text", {})
            text_params.update({k: v for k, v in comm_text_ov.items() if v is not None})

        # Emotion-based label badge (before_after: "Before"/"After")
        emotion_labels = layout.get("emotion_labels")
        if emotion_labels and not is_hook:
            emotion = scene.get("emotion", "neutral")
            label_cfg = emotion_labels.get(emotion)
            if label_cfg:
                vb_add_subtitle(
                    draft_id, label_cfg["label"],
                    cumulative_time, cumulative_time + dur,
                    scene_num=n + 200,  # unique track offset
                    font_color=label_cfg.get("font_color", "#FFFFFF"),
                    font_size=22.0,
                    transform_y=0.35,
                    background_color=label_cfg.get("background_color", ""),
                    background_alpha=label_cfg.get("background_alpha", 0.0),
                    intro_animation="Fade_In",
                )

        # vs_comparison: A/B side labels on non-hook scenes
        side_labels = layout.get("side_labels")
        if side_labels and not is_hook:
            side_key = "odd" if (n % 2 == 1) else "even"
            side_cfg = side_labels.get(side_key)
            if side_cfg:
                vb_add_subtitle(
                    draft_id, side_cfg["label"],
                    cumulative_time, cumulative_time + dur,
                    scene_num=n + 300,
                    font_color=side_cfg.get("font_color", "#FFFFFF"),
                    font_size=26.0,
                    transform_y=0.38,
                    background_color=side_cfg.get("background_color", ""),
                    background_alpha=side_cfg.get("background_alpha", 0.0),
                    intro_animation="Slide_Left",
                )

        # myth_buster: verdict badge when narration contains verdict keywords
        verdict_map = layout.get("verdict_keywords")
        if verdict_map and not is_hook:
            narr_lower = scene.get("narration", "").lower()
            for kw, v_cfg in verdict_map.items():
                if kw in narr_lower:
                    vb_add_subtitle(
                        draft_id, v_cfg["label"],
                        cumulative_time, cumulative_time + dur,
                        scene_num=n + 400,
                        font_color=v_cfg.get("font_color", "#FFFFFF"),
                        font_size=36.0,
                        transform_y=0.0,
                        background_color=v_cfg.get("background_color", ""),
                        background_alpha=v_cfg.get("background_alpha", 0.0),
                        intro_animation="Zoom_In",
                    )
                    break

        # Subtitle style map overrides (user-selected in UI)
        style_overrides = SUBTITLE_STYLE_MAP.get(subtitle_style, {}).copy()
        text_params.update(style_overrides)

        # Split narration into sentences — show one at a time (sequential subtitles)
        sentences = _split_sentences(subtitle_text)
        if len(sentences) <= 1:
            vb_add_subtitle(draft_id, subtitle_text, cumulative_time, cumulative_time + dur, n, **text_params)
        else:
            total_chars = sum(len(s) for s in sentences)
            sent_offset = 0.0
            for si, sent in enumerate(sentences):
                # Proportional duration based on character count
                sent_dur = dur * (len(sent) / total_chars) if total_chars > 0 else dur / len(sentences)
                vb_add_subtitle(
                    draft_id, sent,
                    cumulative_time + sent_offset,
                    cumulative_time + sent_offset + sent_dur,
                    n * 10 + si,  # unique scene_num per sentence
                    **text_params,
                )
                sent_offset += sent_dur

        # Audio narration
        if scene.get("_tts_url"):
            vb_add_narration(draft_id, scene["_tts_url"], scene["_tts_duration"], cumulative_time, n)

        cumulative_time += dur

    # ── Step 4b: Add BGM track (mood-matched to template) ─────────────────
    bgm_dir = PROJECT_ROOT / "assets" / "bgm"
    bgm_file = None
    if bgm_dir.exists():
        # Try mood-matched subdirectory first
        mood = TEMPLATE_BGM_MOOD.get(template_type, "calm")
        mood_dir = bgm_dir / mood
        if mood_dir.is_dir():
            mood_candidates = [f for f in mood_dir.iterdir() if f.suffix in (".mp3", ".wav", ".m4a", ".ogg")]
            if mood_candidates:
                bgm_file = random.choice(mood_candidates)
        # Fallback to root bgm directory
        if not bgm_file:
            bgm_candidates = [f for f in bgm_dir.iterdir() if f.is_file() and f.suffix in (".mp3", ".wav", ".m4a", ".ogg")]
            if bgm_candidates:
                bgm_file = random.choice(bgm_candidates)
    if bgm_file:
        bgm_duration = _get_audio_duration(str(bgm_file))
        bgm_end = min(bgm_duration, cumulative_time)
        if vb_add_bgm(draft_id, str(bgm_file), bgm_end):
            steps_log.append(f"bgm: {bgm_file.name}")

    steps_log.append(f"draft: {draft_id}")

    # ── Step 5: Save draft to CapCut directory (bridge module) ───────────
    draft_path = None
    try:
        draft_path = save_draft_to_capcut(
            draft_id=draft_id,
            script=script,
            scenes=scenes,
            capcut_draft_dir=CAPCUT_DRAFT_DIR,
            has_images=has_images,
            bgm_path=str(bgm_file) if bgm_file else None,
        )
        if draft_path:
            steps_log.append("saved to CapCut")
    except Exception as e:
        print(f"[save] Failed: {e}")
        return jsonify({"ok": False, "error": f"Save failed: {e}"}), 500

    # ── Response ─────────────────────────────────────────────────────────
    return jsonify({
        "ok": True,
        "draft_id": draft_id,
        "draft_path": draft_path,
        "template_type": template_type,
        "scenes": [
            {
                "scene_num": s["scene_num"],
                "narration": s["narration"],
                "display_text": s.get("display_text", ""),
                "image_prompt": s.get("image_prompt", ""),
                "emotion": s.get("emotion", "neutral"),
                "duration": round(s["_tts_duration"], 1),
                "has_image": bool(s.get("_image_url")),
                "rank": s.get("rank"),
                "image_source": _SOURCE_NORMALIZE.get(s.get("image_source", ""), s.get("image_source", "")),
                "_tts_url": s.get("_tts_url"),
                "_image_url": _image_url_for_client(s.get("_image_url")),
            }
            for s in scenes
        ],
        "tts_provider": tts_provider,
        "total_duration": round(cumulative_time, 1),
        "steps": steps_log,
        "message": "Draft saved — open in CapCut" if draft_path else "Draft created",
    })


# ---------------------------------------------------------------------------
# Blueprint registration + helpers shared with route modules
# ---------------------------------------------------------------------------

def _execute_draft_via_test_client(payload: dict) -> dict:
    """Execute a create-draft request through the Flask test client."""
    with app.app_context():
        with app.test_client() as client:
            resp = client.post("/api/create-draft", json=payload, content_type="application/json")
            return resp.get_json()


init_media_routes(BRIDGE_HOST, BRIDGE_PORT, TTS_DIR, PROJECT_ROOT,
                  _get_audio_duration, _image_url_for_client, _safe_resolve)
init_source_routes(_execute_draft_via_test_client)
init_admin_routes(PROJECT_ROOT, CAPCUT_DRAFT_DIR, batch_manager, job_queue,
                  _execute_draft_via_test_client, _safe_resolve)

app.register_blueprint(media_bp)
app.register_blueprint(sources_bp)
app.register_blueprint(admin_bp)

job_queue.set_execute_fn(_execute_draft_via_test_client)


# OLD ROUTES REMOVED — now in routes_media.py, routes_sources.py, routes_admin.py
# (delete marker — everything between here and main() was moved to blueprint files)
_ROUTES_MOVED = True  # sentinel to prevent accidental re-addition


# Main
# ---------------------------------------------------------------------------
def main():
    _init_usage_db()
    print(f"Bridge server: http://{BRIDGE_HOST}:{BRIDGE_PORT}")
    print(f"  TTS providers : {available_providers()}")
    print(f"  Groq          : {'ready' if GROQ_API_KEY else 'no key'}")
    print(f"  Gemini        : {'ready' if GEMINI_API_KEY else 'no key'}")
    print(f"  Pexels        : {'ready' if os.environ.get('PEXELS_API_KEY', '') else 'no key (no stock images)'}")
    print(f"  Klipy         : {'ready' if os.environ.get('KLIPY_API_KEY', '') else 'no key (no meme/GIF)'}")
    print(f"  Templates     : {', '.join(TEMPLATE_TYPES)}")
    print(f"  VectCutAPI    : {VECTCUT_DIR}")
    print(f"  CapCut drafts : {CAPCUT_DRAFT_DIR}")

    # Auto-cleanup stale assets on startup (7+ days old)
    try:
        result = cleanup_storage(PROJECT_ROOT, CAPCUT_DRAFT_DIR, max_age_days=7)
        total_removed = sum(v.get("removed", 0) for v in result.values())
        total_freed = sum(v.get("freed_bytes", 0) for v in result.values())
        if total_removed > 0:
            print(f"  Cleanup       : {total_removed} stale items removed ({format_size(total_freed)} freed)")
        else:
            print(f"  Cleanup       : nothing to clean")
    except Exception as e:
        print(f"  Cleanup       : failed ({e})")

    app.run(host=BRIDGE_HOST, port=BRIDGE_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
