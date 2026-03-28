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
import threading
import time
from pathlib import Path
from urllib import request as urllib_request

from dotenv import load_dotenv

load_dotenv(Path.cwd() / ".env", override=False)

from flask import Flask, jsonify, request as flask_request, send_from_directory
from flask_cors import CORS

from worker.tts.providers import generate_tts, available_providers
from worker.bridge.templates import TEMPLATE_TYPES, build_template_prompt
from worker.bridge.batch import BatchManager
from worker.bridge.job_queue import JobQueue
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
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

app = Flask(__name__)
CORS(app)

batch_manager = BatchManager()
job_queue = JobQueue()


# ---------------------------------------------------------------------------
# Gemini — scene script generation
# ---------------------------------------------------------------------------
_TEMPLATE_HINTS = {
    "community_read": "커뮤니티 글 읽어주기",
    "news_explainer": "뉴스 해설",
    "reddit_translation": "해외 글 번역",
    "ranking_list": "Top N 랭킹",
    "origin_story": "기원/역사 스토리",
    "vs_comparison": "A vs B 비교",
    "myth_buster": "팩트체크",
    "tutorial_steps": "단계별 튜토리얼",
    "before_after": "비포/애프터",
    "hot_take": "핫테이크/논쟁",
}


_SCENE_JSON_HINT = 'JSON 배열로 반환. 각 원소: {{"scene_num":N,"narration":"한국어 나레이션","display_text":"한국어 자막 2줄 이내","image_prompt":"구체적 영어 이미지 검색어","emotion":"neutral","image_source":"pexels","transition":"Dissolve"}}'

# --- Tone presets (종결어미) — independent from template ---
TONE_PRESETS = {
    "casual_heyo": {
        "label": "해요체 (캐주얼)",
        "rule": '종결어미: "~이에요", "~거든요", "~인데요", "~하더라고요" 체만 사용.',
        "example_endings": ["~이에요", "~거든요", "~인데요"],
    },
    "commentary": {
        "label": "해설체",
        "rule": '종결어미: "~인 거죠", "~한 셈이죠", "~라고 하죠" 체만 사용.',
        "example_endings": ["~인 거죠", "~한 셈이죠", "~라고 하죠"],
    },
    "banmal": {
        "label": "반말",
        "rule": '종결어미: "~임", "~인데", "~거든", "~한 거지" 체만 사용.',
        "example_endings": ["~임", "~인데", "~거든"],
    },
    "story": {
        "label": "이야기체",
        "rule": '종결어미: "~였는데요", "~했대요", "~이래요" 체만 사용.',
        "example_endings": ["~였는데요", "~했대요", "~이래요"],
    },
    "formal_soft": {
        "label": "존댓말 (부드러운)",
        "rule": '종결어미: "~합니다", "~인데요", "~이죠" 체만 사용.',
        "example_endings": ["~합니다", "~인데요", "~이죠"],
    },
}

# --- Template structure (구조만, 말투 없음) ---
_TEMPLATE_PROMPTS = {
    "community_read": (
        '유튜브 쇼츠 커뮤니티 글 읽어주기. 5~8개 씬으로 분할. '
        'emotion: 놀라운 부분 "shock", 웃긴 부분 "funny". '
    ),
    "news_explainer": (
        '유튜브 쇼츠 뉴스 해설. 8개 씬. '
        '구조: 충격(1) → 배경(2-3) → 핵심 숫자(4-5) → 전망(6-7) → 질문(8). '
        '숫자는 display_text에 크게. 씬1 emotion "shock". '
    ),
    "reddit_translation": (
        '해외 글 번역 읽어주기 유튜브 쇼츠. 6~8개 씬. 문화차이 괄호 설명. '
        'emotion: 리액션 "funny"/"shock". '
    ),
    "ranking_list": (
        'Top N 랭킹 유튜브 쇼츠. 구조: 인트로(1) → 항목(2씬씩) → 아웃트로. '
        '순위 씬에 "rank": N 필드 추가. '
    ),
    "origin_story": (
        '탄생 비화 유튜브 쇼츠. 8개 씬. '
        '구조: 의외(1) → 기원(2-3) → 전환(4-5) → 현재(6-7) → 정리(8). '
    ),
    "vs_comparison": (
        'A vs B 비교 유튜브 쇼츠. 8개 씬. '
        '구조: 훅(1) → A(2-3) → B(4-5) → 비교(6-7) → 결론(8). '
    ),
    "myth_buster": (
        '팩트체크 유튜브 쇼츠. 8개 씬. '
        '구조: 질문(1) → 통념(2) → 찬성(3-4) → 반대(5-6) → 판정(7) → 마무리(8). 판정 emotion "shock". '
    ),
    "tutorial_steps": (
        '단계별 튜토리얼 유튜브 쇼츠. 8개 씬. '
        '구조: 문제(1) → Step1(2-3) → Step2(4-5) → Step3(6-7) → 완성(8). Step에 "rank": N. '
    ),
    "before_after": (
        '비포/애프터 유튜브 쇼츠. 8개 씬. '
        '구조: Before(1-3) → 전환(4) → After(5-6) → 임팩트(7) → 마무리(8). '
        'Before "sad", 전환 "shock", After "funny". '
    ),
    "hot_take": (
        '핫테이크 유튜브 쇼츠. 8개 씬. '
        '구조: 주장(1) → 배경(2-3) → 찬성(4-5) → 반론(6) → 결론(7) → 댓글(8). 씬1 emotion "shock". '
    ),
}


def _build_scene_prompt(topic: str, template_type: str, tone: str = "casual_heyo") -> str:
    structure = _TEMPLATE_PROMPTS.get(template_type, _TEMPLATE_PROMPTS["news_explainer"])
    tone_preset = TONE_PRESETS.get(tone, TONE_PRESETS["casual_heyo"])
    tone_rule = tone_preset["rule"]
    examples = tone_preset["example_endings"]
    return (
        f'주제: {topic}\n\n'
        f'{structure}\n'
        f'★ 말투 통일 (절대 규칙): {tone_rule} 다른 종결어미 절대 섞지 마.\n'
        f'나레이션 예시 톤: "{examples[0]}", "{examples[1]}", "{examples[2]}"\n\n'
        f'추가 규칙:\n'
        f'- 나레이션 한 문장 최대 25자.\n'
        f'- 자막(display_text)은 핵심만, 2줄 이내.\n'
        f'- image_prompt는 "{topic}" 직접 관련 영어. 일반적 표현 금지.\n'
        f'- emotion 다양하게: shock, serious, funny, neutral.\n\n'
        f'{_SCENE_JSON_HINT}'
    )


# Templates where the hook optimisation should NOT alter scene 1
_HOOK_EXEMPT_TEMPLATES = frozenset({"reddit_translation", "ranking_list", "tutorial_steps"})


def _normalize_scenes(scenes: list[dict], topic: str, template_type: str = "") -> list[dict]:
    for s in scenes:
        s.setdefault("image_prompt", s.pop("visual_description", topic))
        s.setdefault("display_text", "")
        s.setdefault("emotion", "neutral")
        s.setdefault("image_source", "")
        s.setdefault("fallback_prompt", "")
        s.setdefault("transition", "Dissolve")
        s.setdefault("is_commentary", False)
        s.setdefault("rank", None)

    # Hook optimisation: ensure scene 1 grabs attention in the first 3 seconds
    # Exempt templates where scene 1 has a structural role (intro/rank/commentary)
    if scenes and template_type not in _HOOK_EXEMPT_TEMPLATES:
        hook = scenes[0]
        hook["transition"] = "Fade_In"
        if hook.get("emotion") == "neutral":
            hook["emotion"] = "shock"
        narr = hook.get("narration", "")
        if len(narr) > 30:
            for delim in (".", "!", "?", "。", "！", "？"):
                idx = narr.find(delim)
                if 0 < idx < 30:
                    hook["narration"] = narr[: idx + 1]
                    break

    return scenes


def _parse_scenes_json(text: str) -> list[dict] | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()
    text = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return v
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    return None


def _call_groq(prompt: str) -> str | None:
    if not GROQ_API_KEY:
        return None
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib_request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "User-Agent": "VideoStudio/1.0",
        },
    )
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[groq] Failed: {e}")
        return None


def _call_gemini(prompt: str) -> str | None:
    if not GEMINI_API_KEY:
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096, "responseMimeType": "application/json"},
    }).encode("utf-8")
    req = urllib_request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib_request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read())
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[gemini] Failed: {e}")
        return None


def _generate_scenes_llm(topic: str, lang: str, template_type: str = "news_explainer", tone: str = "casual_heyo") -> tuple[list[dict], str]:
    """Generate scene script. Groq first (topic-faithful), Gemini fallback, then template."""
    lang_name = "Korean" if not lang.startswith("en") else "English"
    if template_type not in TEMPLATE_TYPES:
        template_type = "news_explainer"
    if tone not in TONE_PRESETS:
        tone = "casual_heyo"
    short_prompt = _build_scene_prompt(topic, template_type, tone)
    rich_prompt = build_template_prompt(topic, lang_name, template_type)

    # Try Groq first (free, fast, topic-faithful) with short Korean prompt
    text = _call_groq(short_prompt)
    if text:
        scenes = _parse_scenes_json(text)
        if scenes:
            return _normalize_scenes(scenes, topic, template_type), "groq"

    # Fallback to Gemini with rich template prompt (structured instructions)
    text = _call_gemini(rich_prompt)
    if text:
        scenes = _parse_scenes_json(text)
        if scenes:
            return _normalize_scenes(scenes, topic, template_type), "gemini"

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

    steps_log = []
    # ── Step 1: Generate script ──────────────────────────────────────────
    scenes, script_source = _generate_scenes_llm(topic, lang, template_type, tone)
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
        bgm_duration = _get_audio_duration(str(bgm_file))
        bgm_end = min(bgm_duration, cumulative_time)
        try:
            # Pass local file path directly — HTTP self-reference deadlocks Flask
            add_audio_track(
                audio_url=str(bgm_file),
                start=0,
                end=bgm_end,
                target_start=0,
                draft_id=draft_id,
                track_name="bgm",
                volume=0.12,
                duration=bgm_end,
            )
            steps_log.append(f"bgm: {bgm_file.name}")
        except Exception as e:
            import traceback
            err_msg = f"[vectcut] add_bgm failed: {e}\n{traceback.format_exc()}"
            print(err_msg)
            with open(str(PROJECT_ROOT / "storage" / "bgm_error.log"), "w") as ef:
                ef.write(err_msg)

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
                        # Stream download in 64 KB chunks with 5 MB hard cap
                        max_bytes = 5 * 1024 * 1024
                        with open(str(img_path), "wb") as fp:
                            total = 0
                            while True:
                                chunk = resp.read(65536)
                                if not chunk:
                                    break
                                total += len(chunk)
                                if total > max_bytes:
                                    break
                                fp.write(chunk)
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
    )
    thread = threading.Thread(
        target=batch_manager.run_batch,
        args=(batch_id, _execute_draft_via_test_client),
        daemon=True,
    )
    thread.start()
    return jsonify({"ok": True, "batch_id": batch_id}), 202


@app.route("/api/batch/<batch_id>", methods=["GET"])
def get_batch_status_route(batch_id: str):
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


@app.route("/api/jobs/<job_id>", methods=["GET"])
def get_job_route(job_id: str):
    job = job_queue.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404
    return jsonify({"ok": True, **job.to_dict()})


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
