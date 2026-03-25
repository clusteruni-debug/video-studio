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
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib import request as urllib_request

from dotenv import load_dotenv

load_dotenv(Path.cwd() / ".env", override=False)

from flask import Flask, jsonify, request as flask_request, send_from_directory
from flask_cors import CORS

from worker.tts.providers import generate_tts, available_providers

# Add VectCutAPI to Python path
VECTCUT_DIR = Path(os.environ.get("VECTCUT_DIR", str(Path.cwd().parent / "VectCutAPI")))
sys.path.insert(0, str(VECTCUT_DIR))

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
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

app = Flask(__name__)
CORS(app)


# ---------------------------------------------------------------------------
# Gemini — scene script generation
# ---------------------------------------------------------------------------
def _generate_scenes_llm(topic: str, lang: str) -> list[dict]:
    """Call Gemini 2.0 Flash to generate a structured scene script."""
    if not GEMINI_API_KEY:
        print("[script] No GEMINI_API_KEY, using template fallback")
        return _generate_scenes_fallback(topic, lang)

    lang_name = "Korean" if not lang.startswith("en") else "English"
    prompt = f"""You are a YouTube Shorts scriptwriter. Create a 5-scene narration script about: "{topic}"

Rules:
- Write narration in {lang_name}
- Scene 1: Hook/attention grabber
- Scene 2-4: Key information points
- Scene 5: Closing / call to action
- Each narration: ONE short sentence only, MAX 25 Korean characters (or 15 English words). This is critical — text must fit on screen in 1-2 lines.
- visual_description: ONE or TWO simple English words for stock photo search (e.g. "bitcoin", "city night", "ocean wave"). Keep it generic and searchable, NOT descriptive sentences.

Return ONLY a valid JSON array, no markdown fences:
[
  {{"scene_num": 1, "narration": "...", "visual_description": "..."}},
  {{"scene_num": 2, "narration": "...", "visual_description": "..."}},
  {{"scene_num": 3, "narration": "...", "visual_description": "..."}},
  {{"scene_num": 4, "narration": "...", "visual_description": "..."}},
  {{"scene_num": 5, "narration": "...", "visual_description": "..."}}
]"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
        },
    }).encode("utf-8")

    req = urllib_request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            gemini_data = json.loads(raw)
            text = gemini_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            # Strip markdown code fences
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                text = text.rsplit("```", 1)[0].strip()
            # Fix common JSON issues: trailing commas
            import re
            text = re.sub(r",\s*([}\]])", r"\1", text)
            scenes = json.loads(text)
            for s in scenes:
                s.setdefault("image_prompt", s.pop("visual_description", topic))
            return scenes
    except Exception as e:
        # Write to debug file since Flask swallows stdout
        with open(str(PROJECT_ROOT / "storage" / "gemini_debug.log"), "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] Gemini failed: {e}\n")
        return _generate_scenes_fallback(topic, lang)


def _generate_scenes_fallback(topic: str, lang: str) -> list[dict]:
    """Hardcoded template fallback."""
    templates = {
        "ko": [
            ("{topic}, 지금부터 알아보겠습니다.", "Title card about {topic}"),
            ("{topic}의 시작은 어디서부터일까요? 그 기원을 살펴봅니다.", "Origin history of {topic}"),
            ("{topic}이 세상에 가져온 변화는 놀랍습니다.", "Impact and changes from {topic}"),
            ("현재 {topic}은 어떤 모습일까요? 최신 트렌드를 확인합니다.", "Current state of {topic}"),
            ("{topic}의 미래는 무궁무진합니다. 함께 지켜봐 주세요.", "Future possibilities of {topic}"),
        ],
        "en": [
            ("Let's explore {topic}.", "Title card about {topic}"),
            ("Where did {topic} begin? Let's look at its origins.", "Origin history of {topic}"),
            ("The impact of {topic} has been remarkable.", "Impact and changes from {topic}"),
            ("What does {topic} look like today?", "Current state of {topic}"),
            ("The future of {topic} is full of possibilities.", "Future possibilities of {topic}"),
        ],
    }
    lang_key = "en" if lang.startswith("en") else "ko"
    return [
        {"scene_num": i + 1, "narration": n.format(topic=topic), "image_prompt": ip.format(topic=topic)}
        for i, (n, ip) in enumerate(templates[lang_key])
    ]


# ---------------------------------------------------------------------------
# Pexels — stock image search (optional)
# ---------------------------------------------------------------------------
def _search_pexels_image(query: str, orientation: str = "portrait") -> str | None:
    """Search Pexels for a stock image. Returns URL or None."""
    if not PEXELS_API_KEY:
        return None
    try:
        from urllib.parse import quote_plus
        safe_query = quote_plus(query)
        url = f"https://api.pexels.com/v1/search?query={safe_query}&orientation={orientation}&per_page=1"
        req = urllib_request.Request(url, headers={
            "Authorization": PEXELS_API_KEY,
            "User-Agent": "VideoStudio/1.0",
        })
        with urllib_request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            photos = data.get("photos", [])
            if photos:
                return photos[0]["src"]["portrait"]
    except Exception as e:
        print(f"[pexels] Search failed for '{query}': {e}")
    return None


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
        import pyJianYingDraft
        vectcut_ok = True
    except ImportError:
        pass
    return jsonify({
        "bridge": "ok",
        "vectcut": "library" if vectcut_ok else "missing",
        "tts_providers": available_providers(),
        "pexels": "ready" if PEXELS_API_KEY else "no_key",
        "gemini": "ready" if GEMINI_API_KEY else "no_key",
        "capcut_draft_dir": str(CAPCUT_DRAFT_DIR),
        "capcut_draft_dir_exists": CAPCUT_DRAFT_DIR.exists(),
    })


@app.route("/api/tts/<path:filename>", methods=["GET"])
def serve_tts(filename: str):
    return send_from_directory(str(TTS_DIR), filename)


@app.route("/api/create-draft", methods=["POST"])
def create_draft_route():
    data = flask_request.get_json(silent=True) or {}
    topic = data.get("prompt", "").strip() or "AI가 바꾸는 미래"
    lang = data.get("lang", "ko")
    tts_provider = data.get("tts_provider", "edge")
    voice_gender = data.get("voice_gender", "female")

    steps_log = []
    # ── Step 1: Generate script ──────────────────────────────────────────
    scenes = _generate_scenes_llm(topic, lang)
    is_gemini = any("Title card" not in s.get("image_prompt", "Title card") for s in scenes)
    # Force line-wrap long narrations so text doesn't overflow screen
    for s in scenes:
        narr = s.get("narration", "")
        if len(narr) > 20:
            mid = len(narr) // 2
            # Find nearest space or punctuation near the middle
            best = mid
            for offset in range(min(8, mid)):
                for pos in [mid + offset, mid - offset]:
                    if 0 < pos < len(narr) and narr[pos] in " ,，.。!！?？":
                        best = pos + 1
                        break
                else:
                    continue
                break
            s["narration"] = narr[:best].rstrip() + "\n" + narr[best:].lstrip()
    steps_log.append(f"script: {len(scenes)} scenes ({'gemini' if is_gemini else 'template'})")

    # ── Step 2: Generate TTS for each scene ──────────────────────────────
    draft_ts = str(int(time.time()))
    tts_subdir = TTS_DIR / draft_ts
    tts_subdir.mkdir(parents=True, exist_ok=True)

    for scene in scenes:
        n = scene["scene_num"]
        audio_path = tts_subdir / f"scene_{n}.mp3"
        try:
            generate_tts(
                text=scene["narration"],
                lang=lang,
                gender=voice_gender,
                provider=tts_provider,
                output_path=audio_path,
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

    # ── Step 3: Search stock images (optional) ───────────────────────────
    for scene in scenes:
        img_url = _search_pexels_image(scene.get("image_prompt", topic))
        scene["_image_url"] = img_url
    has_images = any(s.get("_image_url") for s in scenes)
    steps_log.append(f"images: {'pexels' if has_images else 'none'}")

    # ── Step 4: Build CapCut draft via VectCutAPI ────────────────────────
    try:
        from create_draft import create_draft as vectcut_create
        from add_text_impl import add_text_impl
        from add_audio_track import add_audio_track
        from add_image_impl import add_image_impl
    except ImportError as e:
        return jsonify({"ok": False, "error": f"VectCutAPI import failed: {e}"}), 500

    try:
        script, draft_id = vectcut_create(1080, 1920)
    except Exception as e:
        return jsonify({"ok": False, "error": f"create_draft failed: {e}"}), 500

    cumulative_time = 0.0
    for scene in scenes:
        n = scene["scene_num"]
        dur = scene["_tts_duration"] + 0.5  # add 0.5s padding

        # Background image FIRST (so it's behind text)
        if scene.get("_image_url"):
            try:
                add_image_impl(
                    image_url=scene["_image_url"],
                    width=1080, height=1920,
                    start=cumulative_time,
                    end=cumulative_time + dur,
                    draft_id=draft_id,
                    track_name="background",
                    scale_x=1.3,  # slightly oversized for Ken Burns room
                    scale_y=1.3,
                    relative_index=0,  # behind text
                    intro_animation="Fade_In",
                    intro_animation_duration=0.5,
                    transition="Dissolve" if n > 1 else None,
                    transition_duration=0.7,
                )
            except Exception as e:
                print(f"[vectcut] add_image scene {n}: {e}")

        # Text subtitle — bottom area, bold, readable over any background
        try:
            add_text_impl(
                text=scene["narration"],
                start=cumulative_time,
                end=cumulative_time + dur,
                draft_id=draft_id,
                font_color="#FFFFFF",
                font_size=12.0,
                track_name=f"text_{n}",
                width=1080, height=1920,
                transform_y=-0.75,  # near bottom of screen (-1.0 = very bottom)
                fixed_width=0.85,  # prevent overflow
                # Thick black stroke — key for readability
                border_width=0.12,
                border_color="#000000",
                border_alpha=1.0,
                # Strong shadow
                shadow_enabled=True,
                shadow_color="#000000",
                shadow_alpha=1.0,
                shadow_distance=5.0,
                # No background pill — stroke + shadow is cleaner for shorts
                background_alpha=0.0,
                # Fade-in animation
                intro_animation="Fade_In",
                intro_duration=0.3,
            )
        except Exception as e:
            print(f"[vectcut] add_text scene {n}: {e}")

        # Audio narration — do NOT pass draft_folder (VectCutAPI has C: drive bug)
        if scene.get("_tts_url"):
            try:
                add_audio_track(
                    audio_url=scene["_tts_url"],
                    start=0,
                    end=scene["_tts_duration"],
                    target_start=cumulative_time,
                    draft_id=draft_id,
                    track_name=f"audio_{n}",
                    volume=1.0,
                    duration=scene["_tts_duration"],
                )
            except Exception as e:
                print(f"[vectcut] add_audio scene {n}: {e}")

        cumulative_time += dur

    steps_log.append(f"draft: {draft_id}")

    # ── Step 5: Save draft to CapCut directory ───────────────────────────
    draft_path = None
    try:
        from util import url_to_hash
        from draft_cache import DRAFT_CACHE

        template_dir = VECTCUT_DIR / "template"
        dest = CAPCUT_DRAFT_DIR / draft_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(str(template_dir), str(dest))

        # Fix audio material paths — VectCutAPI's os.path.join("C:", ...) bug
        # produces "C:Users\..." instead of "C:\Users\...".
        # Must set replace_path (serializes as "path" in JSON).
        cached_script = DRAFT_CACHE.get(draft_id, script)
        if hasattr(cached_script, "materials") and hasattr(cached_script.materials, "audios"):
            for audio in cached_script.materials.audios:
                correct_path = str(dest / "assets" / "audio" / audio.material_name)
                audio.replace_path = correct_path

        # Fix image material paths if present
        if hasattr(cached_script, "materials") and hasattr(cached_script.materials, "videos"):
            for video in cached_script.materials.videos:
                if getattr(video, "material_type", "") == "photo":
                    correct_path = str(dest / "assets" / "image" / video.material_name)
                    video.replace_path = correct_path

        # Save project file — CapCut uses draft_content.json (not draft_info.json)
        cached_script.dump(str(dest / "draft_content.json"))

        # Fix draft_meta_info.json — update fold_path to actual location
        meta_path = dest / "draft_meta_info.json"
        if meta_path.exists():
            with open(str(meta_path), "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["draft_fold_path"] = str(dest).replace("\\", "/")
            meta["draft_name"] = draft_id
            meta["cloud_draft_cover"] = False
            meta["cloud_draft_sync"] = False
            with open(str(meta_path), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)

        # Copy TTS audio files into draft assets
        audio_dest = dest / "assets" / "audio"
        audio_dest.mkdir(parents=True, exist_ok=True)
        for scene in scenes:
            if scene.get("_tts_path") and Path(scene["_tts_path"]).exists():
                material_name = f"audio_{url_to_hash(scene['_tts_url'])}.mp3"
                shutil.copy2(scene["_tts_path"], str(audio_dest / material_name))

        # Download Pexels images into draft assets
        if has_images:
            image_dest = dest / "assets" / "image"
            image_dest.mkdir(parents=True, exist_ok=True)
            for scene in scenes:
                if scene.get("_image_url"):
                    material_name = f"image_{url_to_hash(scene['_image_url'])}.png"
                    img_path = image_dest / material_name
                    try:
                        req = urllib_request.Request(scene["_image_url"], headers={
                            "User-Agent": "VideoStudio/1.0",
                        })
                        with urllib_request.urlopen(req, timeout=15) as resp:
                            img_path.write_bytes(resp.read())
                    except Exception as e:
                        print(f"[download] Image failed: {e}")

        draft_path = str(dest)
        steps_log.append("saved to CapCut")
    except Exception as e:
        print(f"[save] Failed: {e}")
        return jsonify({"ok": False, "error": f"Save failed: {e}"}), 500

    # ── Response ─────────────────────────────────────────────────────────
    return jsonify({
        "ok": True,
        "draft_id": draft_id,
        "draft_path": draft_path,
        "scenes": [
            {
                "scene_num": s["scene_num"],
                "narration": s["narration"],
                "image_prompt": s.get("image_prompt", ""),
                "duration": round(s["_tts_duration"], 1),
                "has_image": bool(s.get("_image_url")),
            }
            for s in scenes
        ],
        "tts_provider": tts_provider,
        "total_duration": round(cumulative_time, 1),
        "steps": steps_log,
        "message": "CapCut에서 초안을 열 수 있습니다" if draft_path else "초안 생성됨",
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"Bridge server: http://{BRIDGE_HOST}:{BRIDGE_PORT}")
    print(f"  TTS providers : {available_providers()}")
    print(f"  Gemini        : {'ready' if GEMINI_API_KEY else 'no key (template fallback)'}")
    print(f"  Pexels        : {'ready' if PEXELS_API_KEY else 'no key (no images)'}")
    print(f"  VectCutAPI    : {VECTCUT_DIR}")
    print(f"  CapCut drafts : {CAPCUT_DRAFT_DIR}")
    app.run(host=BRIDGE_HOST, port=BRIDGE_PORT, debug=False)


if __name__ == "__main__":
    main()
