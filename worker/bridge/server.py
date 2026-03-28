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
import re
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
from worker.bridge.templates import TEMPLATE_TYPES, build_template_prompt
from worker.bridge.image_router import route_image

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

app = Flask(__name__)
CORS(app)


# ---------------------------------------------------------------------------
# Gemini — scene script generation
# ---------------------------------------------------------------------------
def _generate_scenes_llm(topic: str, lang: str, template_type: str = "news_explainer") -> tuple[list[dict], str]:
    """Call Gemini 2.0 Flash to generate a structured scene script.
    Returns (scenes, source) where source is 'gemini' or 'template'."""
    if not GEMINI_API_KEY:
        print("[script] No GEMINI_API_KEY, using template fallback")
        return _generate_scenes_fallback(topic, lang), "template"

    lang_name = "Korean" if not lang.startswith("en") else "English"
    if template_type not in TEMPLATE_TYPES:
        template_type = "news_explainer"
    prompt = build_template_prompt(topic, lang_name, template_type)

    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={GEMINI_API_KEY}"

    # Minimal Korean prompt — JSON format rules cause Gemini to lose topic focus
    template_hint = {
        "community_read": "커뮤니티 글 읽어주기",
        "news_explainer": "뉴스 해설",
        "reddit_translation": "해외 글 번역",
        "ranking_list": "Top N 랭킹",
        "origin_story": "기원/역사 스토리",
    }.get(template_type, "뉴스 해설")
    phase1_prompt = f'{topic}에 대해 유튜브 쇼츠 {template_hint} 영상 스크립트를 만들어줘. 8개 씬. 각 씬마다 나레이션과 영어 이미지 검색어를 포함해줘. JSON 배열로 반환: [{{"scene_num":1,"narration":"나레이션","image_prompt":"english image query"}}]'

    payload = json.dumps({
        "contents": [{"parts": [{"text": phase1_prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        },
    }).encode("utf-8")

    # Debug: save actual prompt being sent
    with open(str(PROJECT_ROOT / "storage" / "last_prompt.txt"), "w", encoding="utf-8") as dpf:
        dpf.write(phase1_prompt)

    req = urllib_request.Request(gemini_url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib_request.urlopen(req, timeout=45) as resp:
            raw = resp.read()
            gemini_data = json.loads(raw)
            text = gemini_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            # Strip markdown code fences
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                text = text.rsplit("```", 1)[0].strip()
            # Fix common JSON issues: trailing commas
            text = re.sub(r",\s*([}\]])", r"\1", text)
            scenes = json.loads(text)
            for s in scenes:
                # Normalize: visual_description -> image_prompt (backward compat)
                s.setdefault("image_prompt", s.pop("visual_description", topic))
                s.setdefault("display_text", "")
                s.setdefault("emotion", "neutral")
                s.setdefault("image_source", "")
                s.setdefault("fallback_prompt", "")
                s.setdefault("transition", "Dissolve")
                s.setdefault("is_commentary", False)
                s.setdefault("rank", None)
            return scenes, "gemini"
    except Exception as e:
        with open(str(PROJECT_ROOT / "storage" / "gemini_debug.log"), "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] Gemini failed ({template_type}): {e}\n")
        return _generate_scenes_fallback(topic, lang), "template"


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
        {
            "scene_num": i + 1,
            "narration": n.format(topic=topic),
            "image_prompt": ip.format(topic=topic),
            "display_text": "",
            "emotion": "neutral",
            "image_source": "",
            "fallback_prompt": "",
            "transition": "Fade_In" if i == 0 else "Dissolve",
            "is_commentary": False,
            "rank": None,
        }
        for i, (n, ip) in enumerate(templates[lang_key])
    ]


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
        "pexels": "ready" if os.environ.get("PEXELS_API_KEY", "") else "no_key",
        "klipy": "ready" if os.environ.get("KLIPY_API_KEY", "") else "no_key",
        "gemini": "ready" if GEMINI_API_KEY else "no_key",
        "template_types": list(TEMPLATE_TYPES),
        "capcut_draft_dir": str(CAPCUT_DRAFT_DIR),
        "capcut_draft_dir_exists": CAPCUT_DRAFT_DIR.exists(),
    })


@app.route("/api/tts/<path:filename>", methods=["GET"])
def serve_tts(filename: str):
    return send_from_directory(str(TTS_DIR), filename)


@app.route("/api/bgm/<path:filename>", methods=["GET"])
def serve_bgm(filename: str):
    return send_from_directory(str(PROJECT_ROOT / "assets" / "bgm"), filename)


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

    steps_log = []
    # ── Step 1: Generate script ──────────────────────────────────────────
    scenes, script_source = _generate_scenes_llm(topic, lang, template_type)
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
    steps_log.append(f"script: {len(scenes)} scenes ({script_source}, {template_type}, topic={topic[:30]})")

    # ── Step 2: Generate TTS for each scene ──────────────────────────────
    draft_ts = str(int(time.time()))
    tts_subdir = TTS_DIR / draft_ts
    tts_subdir.mkdir(parents=True, exist_ok=True)

    for scene in scenes:
        n = scene["scene_num"]
        audio_path = tts_subdir / f"scene_{n}.mp3"

        # Determine TTS tone based on scene metadata
        tts_rate = "+0%"
        tts_pitch = "+0Hz"
        tts_text = scene["narration"]
        if scene.get("is_commentary"):
            # Commentary slides: slower, slightly lower pitch for "explainer" feel
            tts_rate = "-5%"
            tts_pitch = "-1Hz"
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
        scene_transition = scene.get("transition", "Dissolve") if n > 1 else None
        if scene_transition == "none":
            scene_transition = None
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
                    transition=scene_transition,
                    transition_duration=0.7,
                )
            except Exception as e:
                print(f"[vectcut] add_image scene {n}: {e}")

        # Text subtitle — use display_text if available, fallback to narration
        subtitle_text = scene.get("display_text") or scene["narration"]
        is_rank_scene = scene.get("rank") is not None
        try:
            add_text_impl(
                text=subtitle_text,
                start=cumulative_time,
                end=cumulative_time + dur,
                draft_id=draft_id,
                font_color="#FFFFFF",
                font_size=18.0 if is_rank_scene else 12.0,
                track_name=f"text_{n}",
                width=1080, height=1920,
                transform_y=-0.2 if is_rank_scene else -0.35,
                fixed_width=0.85,
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

    # ── Step 4b: Add BGM track ───────────────────────────────────────────
    bgm_dir = PROJECT_ROOT / "assets" / "bgm"
    bgm_style = scenes[0].get("bgm_style", "lo-fi") if scenes else "lo-fi"
    bgm_file = None
    if bgm_dir.exists():
        bgm_candidates = [f for f in bgm_dir.iterdir() if f.suffix in (".mp3", ".wav", ".m4a", ".ogg")]
        if bgm_candidates:
            # Pick first available (future: match bgm_style)
            bgm_file = bgm_candidates[0]
    if bgm_file:
        bgm_url = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/api/bgm/{bgm_file.name}"
        try:
            add_audio_track(
                audio_url=bgm_url,
                start=0,
                end=cumulative_time,
                target_start=0,
                draft_id=draft_id,
                track_name="bgm",
                volume=0.12,
                duration=cumulative_time,
            )
            steps_log.append(f"bgm: {bgm_file.name}")
        except Exception as e:
            print(f"[vectcut] add_bgm failed: {e}")

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

        cached_script = DRAFT_CACHE.get(draft_id, script)

        # ── Step 5a: Copy TTS audio into draft assets ─────────────────────
        audio_dest = dest / "assets" / "audio"
        audio_dest.mkdir(parents=True, exist_ok=True)
        for scene in scenes:
            if scene.get("_tts_path") and Path(scene["_tts_path"]).exists():
                material_name = f"audio_{url_to_hash(scene['_tts_url'])}.mp3"
                shutil.copy2(scene["_tts_path"], str(audio_dest / material_name))

        # ── Step 5b: Download images into draft assets ────────────────────
        image_dest = dest / "assets" / "image"
        image_dest.mkdir(parents=True, exist_ok=True)
        if has_images:
            for scene in scenes:
                img_url = scene.get("_image_url")
                if not img_url:
                    continue
                img_hash = url_to_hash(img_url)
                try:
                    req = urllib_request.Request(img_url, headers={
                        "User-Agent": "VideoStudio/1.0",
                    })
                    with urllib_request.urlopen(req, timeout=15) as resp:
                        ct = resp.headers.get("Content-Type", "").split(";")[0].strip()
                        ext = ".jpg"
                        if ct == "video/mp4":
                            ext = ".mp4"
                        elif ct == "image/gif":
                            ext = ".gif"
                        elif ct == "image/png":
                            ext = ".png"
                        img_path = image_dest / f"image_{img_hash}{ext}"
                        img_path.write_bytes(resp.read(20 * 1024 * 1024))
                except Exception as e:
                    print(f"[download] Image failed: {e}")

        # ── Step 5c: Set correct paths on VectCutAPI materials ─────────────
        # VectCutAPI registers as .png, but actual files are .jpg/.mp4.
        # Point replace_path to the ACTUAL file on disk (not .png).
        actual_by_stem = {}
        for fp in image_dest.iterdir():
            if fp.is_file():
                actual_by_stem[fp.stem] = fp

        if hasattr(cached_script, "materials"):
            if hasattr(cached_script.materials, "audios"):
                for audio in cached_script.materials.audios:
                    audio.replace_path = str(audio_dest / audio.material_name)
            if hasattr(cached_script.materials, "videos"):
                for video in cached_script.materials.videos:
                    if getattr(video, "material_type", "") == "photo":
                        stem = Path(video.material_name).stem
                        actual_fp = actual_by_stem.get(stem)
                        if actual_fp:
                            # Copy actual file to .png name that VectCutAPI expects
                            png_path = image_dest / video.material_name  # image_xxx.png
                            if not png_path.exists() and actual_fp.suffix != ".png":
                                shutil.copy2(str(actual_fp), str(png_path))
                        video.replace_path = str(image_dest / video.material_name)

        # ── Step 5d: Save project file ────────────────────────────────────
        cached_script.dump(str(dest / "draft_content.json"))

        # Fix draft_meta_info.json
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
    print(f"  Pexels        : {'ready' if os.environ.get('PEXELS_API_KEY', '') else 'no key (no stock images)'}")
    print(f"  Klipy         : {'ready' if os.environ.get('KLIPY_API_KEY', '') else 'no key (no meme/GIF)'}")
    print(f"  Templates     : {', '.join(TEMPLATE_TYPES)}")
    print(f"  VectCutAPI    : {VECTCUT_DIR}")
    print(f"  CapCut drafts : {CAPCUT_DRAFT_DIR}")
    app.run(host=BRIDGE_HOST, port=BRIDGE_PORT, debug=False)


if __name__ == "__main__":
    main()
