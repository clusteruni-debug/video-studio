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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

app = Flask(__name__)
CORS(app)

batch_manager = BatchManager()
job_queue = JobQueue()



# --- Subtitle style overrides for add_text_impl ---
_SUBTITLE_STYLE_MAP: dict[str, dict] = {
    "": {},
    "default": {},
    "news": {"font_size": 14.0, "transform_y": -0.30},
    "story": {"font_size": 16.0, "border_width": 0.15},
    "ranking": {"font_size": 18.0, "transform_y": -0.20},
    "minimal": {"font_size": 10.0, "border_width": 0.06, "shadow_distance": 2.0},
    "impact": {"font_size": 20.0, "font_color": "#FFFF00", "border_width": 0.18},
}



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
        tts_rate = "+40%"
        tts_pitch = "+0Hz"
        tts_text = scene["narration"]
        if scene.get("is_commentary"):
            # Commentary slides: slightly slower than default fast pace
            tts_rate = "+30%"
            tts_pitch = "+0Hz"
        if scene.get("rank") is not None and tts_text.strip():
            # Rank slides: SSML pause before rank number for dramatic effect
            tts_text = f'<speak><break time="500ms"/>{tts_text}</speak>'

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
            image_sources_used.add(used_source)
    has_images = any(s.get("_image_url") for s in scenes)
    steps_log.append(f"images: {'+'.join(sorted(image_sources_used)) if image_sources_used else 'none'}")

    # ── Step 4: Build CapCut draft via VectCutAPI (bridge module) ─────────
    try:
        script, draft_id = create_capcut_draft(1080, 1920)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    cumulative_time = 0.0
    for scene in scenes:
        n = scene["scene_num"]
        dur = scene["_tts_duration"] + 0.5

        # Background image
        scene_transition = scene.get("transition", "Dissolve") if n > 1 else None
        if scene_transition == "none":
            scene_transition = None
        if scene.get("_image_url"):
            vb_add_image(
                draft_id, scene["_image_url"], cumulative_time, cumulative_time + dur,
                transition=scene_transition,
            )

        # Text subtitle with style overrides
        subtitle_text = scene.get("display_text") or scene["narration"]
        is_rank_scene = scene.get("rank") is not None
        text_params = {
            "font_color": "#FFFFFF",
            "font_size": 18.0 if is_rank_scene else 12.0,
            "transform_y": -0.2 if is_rank_scene else -0.35,
            "border_width": 0.12,
            "shadow_distance": 5.0,
        }
        style_overrides = _SUBTITLE_STYLE_MAP.get(subtitle_style, {}).copy()
        if is_rank_scene:
            # Rank scenes keep their own font_size and position — don't override
            style_overrides.pop("font_size", None)
            style_overrides.pop("transform_y", None)
        text_params.update(style_overrides)
        vb_add_subtitle(draft_id, subtitle_text, cumulative_time, cumulative_time + dur, n, **text_params)

        # Audio narration
        if scene.get("_tts_url"):
            vb_add_narration(draft_id, scene["_tts_url"], scene["_tts_duration"], cumulative_time, n)

        cumulative_time += dur

    # ── Step 4b: Add BGM track ───────────────────────────────────────────
    bgm_dir = PROJECT_ROOT / "assets" / "bgm"
    bgm_file = None
    if bgm_dir.exists():
        bgm_candidates = [f for f in bgm_dir.iterdir() if f.suffix in (".mp3", ".wav", ".m4a", ".ogg")]
        if bgm_candidates:
            bgm_file = bgm_candidates[0]
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
                "image_source": s.get("image_source", ""),
                "_tts_url": s.get("_tts_url"),
            }
            for s in scenes
        ],
        "tts_provider": tts_provider,
        "total_duration": round(cumulative_time, 1),
        "steps": steps_log,
        "message": "CapCut에서 초안을 열 수 있습니다" if draft_path else "초안 생성됨",
    })


# ---------------------------------------------------------------------------
# Translation / Dubbing
# ---------------------------------------------------------------------------

@app.route("/api/dub", methods=["POST"])
def dub_route():
    """Transcribe + translate + generate TTS for a foreign-language audio file."""
    data = flask_request.get_json(silent=True) or {}
    source_path = data.get("source_path", "").strip()
    if not source_path:
        return jsonify({"ok": False, "error": "source_path is required"}), 400
    source = _safe_resolve(source_path, PROJECT_ROOT)
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


# ---------------------------------------------------------------------------
# Content Sourcing
# ---------------------------------------------------------------------------

@app.route("/api/sources/reddit", methods=["GET"])
def reddit_posts_route():
    """Fetch popular Reddit posts from a subreddit."""
    subreddit = flask_request.args.get("subreddit", "todayilearned")
    sort = flask_request.args.get("sort", "hot")
    try:
        limit = min(int(flask_request.args.get("limit", "10")), 25)
    except (ValueError, TypeError):
        limit = 10
    try:
        from worker.sources.reddit import fetch_reddit_posts
        posts = fetch_reddit_posts(subreddit, sort=sort, limit=limit)
        return jsonify({"ok": True, "posts": posts})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/sources/reddit/auto", methods=["POST"])
def reddit_auto_generate_route():
    """Auto-select best Reddit post and generate a draft using reddit_translation."""
    data = flask_request.get_json(silent=True) or {}
    subreddit = data.get("subreddit", "todayilearned")
    try:
        from worker.sources.reddit import fetch_reddit_posts, select_best_post, post_to_prompt
        posts = fetch_reddit_posts(subreddit, limit=15)
        best = select_best_post(posts)
        if not best:
            return jsonify({"ok": False, "error": "No suitable posts found"}), 404

        prompt = post_to_prompt(best)
        result = _execute_draft_via_test_client({
            "prompt": prompt,
            "lang": data.get("lang", "ko"),
            "tts_provider": data.get("tts_provider", "edge"),
            "voice_gender": data.get("voice_gender", "female"),
            "template_type": "reddit_translation",
            "tone": data.get("tone", "casual_heyo"),
            "subtitle_style": data.get("subtitle_style", ""),
            "target_duration": data.get("target_duration", "30s"),
            "custom_instruction": data.get("custom_instruction", ""),
        })

        result["source_post"] = {
            "title": best["title"],
            "subreddit": best["subreddit"],
            "score": best["score"],
            "url": best["url"],
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/sources/news", methods=["GET"])
def news_headlines_route():
    """Fetch news headlines (requires NEWSAPI_KEY)."""
    query = flask_request.args.get("q", "")
    country = flask_request.args.get("country", "kr")
    category = flask_request.args.get("category", "general")
    try:
        from worker.sources.news import fetch_news_headlines
        articles = fetch_news_headlines(query=query, country=country, category=category)
        return jsonify({"ok": True, "articles": articles})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/sources/news/auto", methods=["POST"])
def news_auto_generate_route():
    """Auto-select top news headline and generate a draft using news_explainer."""
    data = flask_request.get_json(silent=True) or {}
    query = data.get("q", "")
    country = data.get("country", "kr")
    category = data.get("category", "general")
    try:
        from worker.sources.news import fetch_news_headlines, headline_to_prompt
        articles = fetch_news_headlines(query=query, country=country, category=category, page_size=5)
        if not articles:
            return jsonify({"ok": False, "error": "No headlines found"}), 404

        best = articles[0]  # Top headline
        prompt = headline_to_prompt(best)
        result = _execute_draft_via_test_client({
            "prompt": prompt,
            "lang": data.get("lang", "ko"),
            "tts_provider": data.get("tts_provider", "edge"),
            "voice_gender": data.get("voice_gender", "female"),
            "template_type": "news_explainer",
            "tone": data.get("tone", "casual_heyo"),
            "subtitle_style": data.get("subtitle_style", ""),
            "target_duration": data.get("target_duration", "30s"),
            "custom_instruction": data.get("custom_instruction", ""),
        })
        result["source_article"] = {
            "title": best["title"],
            "source": best["source"],
            "url": best["url"],
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Batch generation & async job queue (imports at top of section; classes in batch.py / job_queue.py)
# ---------------------------------------------------------------------------


def _execute_draft_via_test_client(payload: dict) -> dict:
    """Execute a create-draft request through the Flask test client.

    Pushes an app context so this works from background threads (batch/job_queue).
    """
    with app.app_context():
        with app.test_client() as client:
            resp = client.post(
                "/api/create-draft",
                json=payload,
                content_type="application/json",
            )
            return resp.get_json()


job_queue.set_execute_fn(_execute_draft_via_test_client)


@app.route("/api/batch/create", methods=["POST"])
def create_batch_route():
    data = flask_request.get_json(silent=True) or {}
    topic = data.get("prompt", "").strip()
    if not topic:
        return jsonify({"ok": False, "error": "prompt is required"}), 400
    try:
        variants = min(int(data.get("variants", 3)), 10)
    except (ValueError, TypeError):
        variants = 3

    batch_id = batch_manager.create_batch(
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
        target=batch_manager.run_batch,
        args=(batch_id, _execute_draft_via_test_client),
        daemon=True,
    )
    thread.start()
    return jsonify({"ok": True, "batch_id": batch_id}), 202


@app.route("/api/batch/<batch_id>", methods=["GET", "DELETE"])
def batch_detail_route(batch_id: str):
    if flask_request.method == "DELETE":
        if batch_manager.delete_batch(batch_id):
            return jsonify({"ok": True})
        job = batch_manager.get_status(batch_id)
        if job and job.status == "running":
            return jsonify({"ok": False, "error": "cannot delete running batch"}), 409
        return jsonify({"ok": False, "error": "batch not found"}), 404
    job = batch_manager.get_status(batch_id)
    if not job:
        return jsonify({"ok": False, "error": "batch not found"}), 404
    return jsonify({"ok": True, **job.to_dict()})


@app.route("/api/batch", methods=["GET"])
def list_batches_route():
    return jsonify({"ok": True, "batches": batch_manager.list_jobs()})


@app.route("/api/jobs", methods=["GET", "POST"])
def jobs_route():
    if flask_request.method == "POST":
        payload = flask_request.get_json(silent=True) or {}
        if not payload.get("prompt", "").strip():
            return jsonify({"ok": False, "error": "prompt is required"}), 400
        job_id = job_queue.submit(payload)
        return jsonify({"ok": True, "job_id": job_id}), 202
    # GET — list recent jobs
    return jsonify({"ok": True, "jobs": job_queue.list_jobs()})


@app.route("/api/jobs/<job_id>", methods=["GET", "DELETE"])
def job_detail_route(job_id: str):
    if flask_request.method == "DELETE":
        if job_queue.delete_job(job_id):
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "job not found or still running"}), 404
    job = job_queue.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404
    return jsonify({"ok": True, **job.to_dict()})


@app.route("/api/draft/<draft_id>", methods=["DELETE"])
def delete_draft_route(draft_id: str):
    import shutil
    safe_path = _safe_resolve(str(CAPCUT_DRAFT_DIR / draft_id), CAPCUT_DRAFT_DIR)
    if not safe_path:
        return jsonify({"ok": False, "error": "invalid draft id"}), 400
    if safe_path.exists() and safe_path.is_dir():
        shutil.rmtree(safe_path, ignore_errors=True)
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "draft not found"}), 404


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"Bridge server: http://{BRIDGE_HOST}:{BRIDGE_PORT}")
    print(f"  TTS providers : {available_providers()}")
    print(f"  Groq          : {'ready' if GROQ_API_KEY else 'no key'}")
    print(f"  Gemini        : {'ready' if GEMINI_API_KEY else 'no key'}")
    print(f"  Pexels        : {'ready' if os.environ.get('PEXELS_API_KEY', '') else 'no key (no stock images)'}")
    print(f"  Klipy         : {'ready' if os.environ.get('KLIPY_API_KEY', '') else 'no key (no meme/GIF)'}")
    print(f"  Templates     : {', '.join(TEMPLATE_TYPES)}")
    print(f"  VectCutAPI    : {VECTCUT_DIR}")
    print(f"  CapCut drafts : {CAPCUT_DRAFT_DIR}")
    app.run(host=BRIDGE_HOST, port=BRIDGE_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
