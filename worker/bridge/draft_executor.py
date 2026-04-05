"""CapCut draft executor — pure orchestrator for the create-draft pipeline.

Extracted from :mod:`worker.bridge.server` to keep the Flask entry point
under the 660-line limit. No Flask imports here; ``execute_draft_core``
is a plain function the HTTP route, job queue, batch manager, and
source auto-generators all call.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from worker.bridge.image_router import route_image, search_sub_image
from worker.bridge.layouts import (
    DEFAULT_LAYOUT,
    DEFAULT_TTS_RATE,
    DEFAULT_TTS_RATE_COMMENTARY,
    SUBTITLE_STYLE_MAP,
    TEMPLATE_BGM_MOOD,
    TEMPLATE_LAYOUTS,
)
from worker.bridge.routes_media import _SOURCE_NORMALIZE
from worker.bridge.scene_generator import generate_scenes_llm, wrap_narration
from worker.bridge.vectcut_bridge import (
    add_bgm as vb_add_bgm,
    add_image as vb_add_image,
    add_narration as vb_add_narration,
    add_subtitle as vb_add_subtitle,
    add_video as vb_add_video,
    create_capcut_draft,
    save_draft_to_capcut,
)
from worker.tts.providers import generate_tts

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — derived from env/cwd so the module is self-contained.
# ---------------------------------------------------------------------------
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 5161
PROJECT_ROOT = Path.cwd()
TTS_DIR = PROJECT_ROOT / "storage" / "tts"
IMAGE_CACHE_DIR = PROJECT_ROOT / "storage" / "cache"
CAPCUT_DRAFT_DIR = Path(os.environ.get(
    "CAPCUT_DRAFT_DIR",
    str(Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"),
))


# ---------------------------------------------------------------------------
# Path helpers (also used by routes_media/routes_admin via init callbacks)
# ---------------------------------------------------------------------------
def image_url_for_client(raw_url: str | None) -> str | None:
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


def safe_resolve(user_path: str, allowed_root: Path) -> Path | None:
    """Resolve *user_path* and verify it is under *allowed_root*."""
    try:
        resolved = Path(user_path).resolve()
        root = allowed_root.resolve()
    except (OSError, ValueError):
        return None
    # Use is_relative_to for proper path-boundary check (no prefix collision)
    try:
        if not resolved.is_relative_to(root):
            return None
    except AttributeError:
        # Python < 3.9 fallback
        if not str(resolved).startswith(str(root) + os.sep) and resolved != root:
            return None
    return resolved

# Korean conjunction particles — natural break points for long sentences.
_KO_CONJUNCTIONS = re.compile(r'(지만|는데|거든|해서|니까|때문에|그래서|그런데|그리고)\s*')


def _enforce_max_chars(sentences: list[str], max_chars: int = 32) -> list[str]:
    """Split any sentence exceeding *max_chars* at natural Korean break points.
    RENDERING-SPEC: max 16 chars/line × 2 lines = 32 chars."""
    out: list[str] = []
    for s in sentences:
        if len(s) <= max_chars:
            out.append(s)
            continue
        # Try comma split first
        if "," in s:
            idx = s.index(",")
            if 4 < idx < len(s) - 4:
                out.extend(_enforce_max_chars([s[:idx + 1].strip(), s[idx + 1:].strip()], max_chars))
                continue
        # Try Korean conjunction split
        m = _KO_CONJUNCTIONS.search(s, 4)
        if m and m.end() < len(s) - 2:
            out.extend(_enforce_max_chars([s[:m.end()].strip(), s[m.end():].strip()], max_chars))
            continue
        # Last resort: split at space nearest midpoint
        mid = len(s) // 2
        best = -1
        for i in range(mid, -1, -1):
            if s[i] == " ":
                best = i
                break
        if best == -1:
            for i in range(mid, len(s)):
                if s[i] == " ":
                    best = i
                    break
        if best >= 1:
            parts = [p for p in [s[:best].strip(), s[best:].strip()] if p]
            out.extend(_enforce_max_chars(parts, max_chars))
        else:
            out.append(s)
    return [s for s in out if s]


def _split_sentences(text: str) -> list[str]:
    """Split Korean narration into display sentences for sequential subtitles."""
    parts: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Split on sentence-ending patterns (요. 요! 요? 다. 다! 다? etc.)
        sents = re.split(r'(?<=[.!?])\s+', line)
        for s in sents:
            s = s.strip()
            if s:
                parts.append(s)
    result = parts if parts else [text]
    return _enforce_max_chars(result)


def get_audio_duration(file_path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-print_format", "json", file_path],
            capture_output=True, text=True, timeout=10,
        )
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, ValueError, OSError) as e:
        logger.warning("ffprobe failed for %s: %s", file_path, e)
        return 5.0  # fallback 5 seconds


def execute_draft_core(data: dict) -> dict:
    """Core draft-creation logic — pure function, no Flask dependency.

    Accepts a dict payload and returns a dict result.
    Used by the HTTP route, job queue, batch manager, and source auto-generators.
    """
    import random

    topic = data.get("prompt", "").strip()
    if not topic:
        return {"ok": False, "error": "prompt is required"}
    lang = data.get("lang", "ko")
    tts_provider = data.get("tts_provider", "edge")
    voice_gender = data.get("voice_gender", "female")
    template_type = data.get("template_type", "news_explainer")
    tone = data.get("tone", "casual_heyo")
    subtitle_style = data.get("subtitle_style", "")
    bgm_enabled = data.get("bgm_enabled", True)
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
    draft_ts = f"{int(time.time())}_{os.getpid()}_{id(data) % 10000:04d}"
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
            logger.info("tts scene %s: empty narration, skipping TTS", n)
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
            scene["_tts_duration"] = get_audio_duration(str(audio_path))
            scene["_tts_url"] = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/api/tts/{draft_ts}/scene_{n}.mp3"
        except Exception as e:
            # generate_tts hides provider-specific exception types; keep broad
            # so a single scene failure does not abort the whole draft build.
            logger.warning("tts scene %s failed: %s", n, e)
            scene["_tts_path"] = None
            scene["_tts_duration"] = 5.0
            scene["_tts_url"] = None
    steps_log.append(f"tts: {tts_provider}")

    # ── Step 3: Search images via emotion-based routing ─────────────────
    image_sources_used = set()
    for scene in scenes:
        img_url, used_source = route_image(scene)
        scene["_image_url"] = img_url
        # Mark animated video sources (Klipy .mp4) so CapCut uses video material
        scene["_is_video"] = bool(
            img_url and img_url.endswith(".mp4")
        )
        if img_url and used_source:
            scene["image_source"] = _SOURCE_NORMALIZE.get(used_source, used_source)
            image_sources_used.add(used_source)
    has_images = any(s.get("_image_url") for s in scenes)
    steps_log.append(f"images: {'+'.join(sorted(image_sources_used)) if image_sources_used else 'none'}")

    # ── Step 3b: Pre-search sub-scene images for long scenes ──────────────
    # Scenes with ≥2 sentences get per-sentence images for visual variety.
    # Cap at 3 extra searches per scene to keep latency reasonable (~30s max).
    _MAX_SUB_SEARCHES = 3
    for scene in scenes:
        sentences = _split_sentences(scene.get("narration", ""))
        scene["_sentences"] = sentences  # cache for Step 4 timing reuse
        if len(sentences) < 2 or not scene.get("_image_url"):
            continue
        sub_images: list[dict] = []
        base_prompt = scene.get("image_prompt", "")
        searches_done = 0
        for si, sent in enumerate(sentences):
            if si == 0:
                # First sentence reuses the scene's main image
                sub_images.append({
                    "url": scene.get("_image_url"),
                    "is_video": scene.get("_is_video", False),
                })
                continue
            if searches_done < _MAX_SUB_SEARCHES:
                try:
                    query = f"{base_prompt}, {sent}" if base_prompt else sent
                    sub_url, sub_src = search_sub_image(query)
                except Exception as sub_err:
                    # Per-sentence sub-image search is best-effort visual variety;
                    # the main scene image is already set above, so a miss is safe.
                    logger.debug("sub-image search failed: %s", sub_err)
                    sub_url, sub_src = None, None
                searches_done += 1
                if sub_url:
                    image_sources_used.add(sub_src or "serper")
            else:
                sub_url = None
            sub_images.append({
                "url": sub_url or scene.get("_image_url"),
                "is_video": bool(sub_url and sub_url.endswith(".mp4")),
            })
        # Only use multi-image if at least one sub differs from main
        main_url = scene.get("_image_url")
        if any(s.get("url") and s["url"] != main_url for s in sub_images[1:]):
            scene["_sub_images"] = sub_images

    # ── Step 4: Build CapCut draft via VectCutAPI (bridge module) ─────────
    try:
        script, draft_id = create_capcut_draft(1080, 1920)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    cumulative_time = 0.0
    layout = TEMPLATE_LAYOUTS.get(template_type, DEFAULT_LAYOUT)
    for scene in scenes:
        n = scene["scene_num"]
        dur = scene.get("_tts_duration", 5.0) + 0.5
        is_hook = (n == 1)
        is_rank_scene = scene.get("rank") is not None
        is_commentary = scene.get("is_commentary", False)

        # ── Background image(s) with structural layout ──
        default_trans = layout.get("default_transition", "Dissolve")
        scene_transition = scene.get("transition", default_trans) if n > 1 else None
        if scene_transition == "none":
            scene_transition = None
        img_cfg = layout.get("img", {})
        img_base_params = {
            "scale_x": img_cfg.get("scale_x", 1.3),
            "scale_y": img_cfg.get("scale_y", 1.3),
        }
        if img_cfg.get("background_blur"):
            img_base_params["background_blur"] = img_cfg["background_blur"]
        if img_cfg.get("transform_y") is not None:
            img_base_params["transform_y"] = img_cfg["transform_y"]

        sub_images = scene.get("_sub_images")
        if sub_images and len(sub_images) >= 2:
            # Multi-image: one image per sentence segment
            sentences_for_timing = scene.get("_sentences") or _split_sentences(scene.get("narration", ""))
            total_chars = sum(len(s) for s in sentences_for_timing) or 1
            seg_offset = 0.0
            for si, sub in enumerate(sub_images):
                if si < len(sentences_for_timing):
                    seg_dur = dur * (len(sentences_for_timing[si]) / total_chars)
                else:
                    seg_dur = dur / len(sub_images)
                sub_url = sub.get("url")
                if not sub_url:
                    seg_offset += seg_dur
                    continue
                if not sub_url.startswith(("http://", "https://")):
                    sub_url = Path(sub_url).resolve().as_uri()
                trans = scene_transition if si == 0 else "Dissolve"
                if sub.get("is_video"):
                    vb_add_video(
                        draft_id, sub_url,
                        cumulative_time + seg_offset, cumulative_time + seg_offset + seg_dur,
                        transition=trans,
                        scale_x=img_base_params["scale_x"],
                        scale_y=img_base_params["scale_y"],
                        background_blur=img_base_params.get("background_blur"),
                    )
                else:
                    img_p = dict(img_base_params)
                    if img_cfg.get("mask_type"):
                        img_p["mask_type"] = img_cfg["mask_type"]
                    vb_add_image(
                        draft_id, sub_url,
                        cumulative_time + seg_offset, cumulative_time + seg_offset + seg_dur,
                        transition=trans, **img_p,
                    )
                seg_offset += seg_dur
        else:
            # Single image for the entire scene
            img_ref = scene.get("_image_url")
            if img_ref:
                is_video_asset = scene.get("_is_video", False)
                if not img_ref.startswith(("http://", "https://")):
                    img_ref = Path(img_ref).resolve().as_uri()
                if is_video_asset:
                    vb_add_video(
                        draft_id, img_ref, cumulative_time, cumulative_time + dur,
                        transition=scene_transition,
                        scale_x=img_base_params["scale_x"],
                        scale_y=img_base_params["scale_y"],
                        background_blur=img_base_params.get("background_blur"),
                    )
                else:
                    img_p = dict(img_base_params)
                    if img_cfg.get("mask_type"):
                        img_p["mask_type"] = img_cfg["mask_type"]
                    vb_add_image(
                        draft_id, img_ref, cumulative_time, cumulative_time + dur,
                        transition=scene_transition, **img_p,
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
        sentences = scene.get("_sentences") or _split_sentences(subtitle_text)
        if len(sentences) <= 1:
            # Use the split result (may be shorter than subtitle_text after _enforce_max_chars)
            display = sentences[0] if sentences else subtitle_text
            vb_add_subtitle(draft_id, display, cumulative_time, cumulative_time + dur, n, **text_params)
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
                    n * 1000 + si,  # unique track: no collision with badge offsets (n+100..400)
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
    if bgm_enabled and bgm_dir.exists():
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
        bgm_duration = get_audio_duration(str(bgm_file))
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
        # save_draft_to_capcut bridges into VectCutAPI; see vectcut_bridge.py
        # docstring for the broad-catch rationale.
        logger.error("save_draft_to_capcut failed: %s", e)
        return {"ok": False, "error": f"Save failed: {e}"}

    # ── Response ─────────────────────────────────────────────────────────
    _internal_scenes = [
        {
            "scene_num": s["scene_num"],
            "narration": s["narration"],
            "display_text": s.get("display_text", ""),
            "image_prompt": s.get("image_prompt", ""),
            "image_source": s.get("image_source", ""),
            "emotion": s.get("emotion", "neutral"),
            "_tts_duration": s.get("_tts_duration", 5.0),
            "_image_url": s.get("_image_url"),
            "_is_video": s.get("_is_video", False),
            "_sub_images": s.get("_sub_images"),
        }
        for s in scenes
    ]
    return {
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
                "_image_url": image_url_for_client(s.get("_image_url")),
            }
            for s in scenes
        ],
        "_internal_scenes": _internal_scenes,
        "tts_provider": tts_provider,
        "total_duration": round(cumulative_time, 1),
        "steps": steps_log,
        "message": "Draft saved — open in CapCut" if draft_path else "Draft created",
    }
