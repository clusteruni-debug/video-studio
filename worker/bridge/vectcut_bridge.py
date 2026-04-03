"""VectCutAPI bridge — isolates all VectCutAPI imports and interactions.

This module is the ONLY place in the codebase that does ``sys.path``
manipulation and bare-module imports from VectCutAPI.  All other code
should import from here instead.

VectCutAPI is a flat script collection (no ``__init__.py``), so we
must add its directory to ``sys.path`` before importing.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from pathlib import Path
from urllib import request as urllib_request

# ---------------------------------------------------------------------------
# sys.path setup — runs ONCE at import time
# ---------------------------------------------------------------------------
VECTCUT_DIR = Path(os.environ.get("VECTCUT_DIR", str(Path.cwd().parent / "VectCutAPI")))
if str(VECTCUT_DIR) not in sys.path:
    sys.path.insert(0, str(VECTCUT_DIR))

# Version pin check — warn if VectCutAPI was updated since last verified commit
_PINNED = os.environ.get("VECTCUT_PINNED_COMMIT", "")
if _PINNED and VECTCUT_DIR.is_dir():
    try:
        import subprocess
        _head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=VECTCUT_DIR, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if _head and not _head.startswith(_PINNED):
            print(
                f"[vectcut_bridge] WARNING: VectCutAPI commit {_head} != pinned {_PINNED}. "
                f"If something breaks, run: cd {VECTCUT_DIR} && git checkout {_PINNED}"
            )
    except Exception:
        pass

_MAX_IMAGE_BYTES = 5 * 1024 * 1024   # 5 MB
_MAX_VIDEO_BYTES = 25 * 1024 * 1024  # 25 MB — Klipy GIFs regularly exceed 5 MB


# ---------------------------------------------------------------------------
# Lazy import helpers (defer until first call to catch ImportError cleanly)
# ---------------------------------------------------------------------------
from collections import namedtuple

VectCutModules = namedtuple("VectCutModules", ["create", "text", "audio", "image", "hash_url", "cache"])


def _import_vectcut() -> VectCutModules:
    """Import VectCutAPI modules.  Raises ``RuntimeError`` with a clear
    message if VectCutAPI is not found."""
    try:
        from create_draft import create_draft as _create
        from add_text_impl import add_text_impl as _text
        from add_audio_track import add_audio_track as _audio
        from add_image_impl import add_image_impl as _image
        from util import url_to_hash as _hash
        from draft_cache import DRAFT_CACHE as _cache
        return VectCutModules(_create, _text, _audio, _image, _hash, _cache)
    except ImportError as e:
        raise RuntimeError(
            f"VectCutAPI import failed (dir={VECTCUT_DIR}): {e}"
        ) from e


_video_track_fn = None
_video_track_fn_checked = False

def _get_video_track_fn():
    """Lazy import for add_video_track — requires imageio which may not be installed."""
    global _video_track_fn, _video_track_fn_checked
    if _video_track_fn_checked:
        return _video_track_fn
    _video_track_fn_checked = True
    try:
        from add_video_track import add_video_track
        _video_track_fn = add_video_track
    except ImportError as e:
        print(f"[vectcut] add_video_track unavailable: {e}")
    return _video_track_fn


# Cache after first successful import (thread-safe double-check)
_vectcut = None
_vectcut_lock = threading.Lock()


def _get_vectcut():
    global _vectcut
    if _vectcut is None:
        with _vectcut_lock:
            if _vectcut is None:
                _vectcut = _import_vectcut()
    return _vectcut


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_capcut_draft(width: int = 1080, height: int = 1920) -> tuple:
    """Create a new CapCut draft.  Returns ``(script, draft_id)``."""
    vectcut_create = _get_vectcut().create
    return vectcut_create(width, height)


def add_image(
    draft_id: str,
    image_url: str,
    start: float,
    end: float,
    *,
    track_name: str = "background",
    scale_x: float = 1.3,
    scale_y: float = 1.3,
    transform_y: float = 0,
    relative_index: int = 0,
    intro_animation: str = "Fade_In",
    intro_animation_duration: float = 0.5,
    transition: str | None = None,
    transition_duration: float = 0.7,
    background_blur: int | None = None,
    mask_type: str | None = None,
) -> bool:
    """Add a background image to the draft.  Returns True on success."""
    _image = _get_vectcut().image
    try:
        kwargs = dict(
            image_url=image_url,
            width=1080, height=1920,
            start=start, end=end,
            draft_id=draft_id,
            track_name=track_name,
            scale_x=scale_x, scale_y=scale_y,
            relative_index=relative_index,
            intro_animation=intro_animation,
            intro_animation_duration=intro_animation_duration,
            transition=transition,
            transition_duration=transition_duration,
        )
        if transform_y != 0:
            kwargs["transform_y"] = transform_y
        if background_blur is not None:
            kwargs["background_blur"] = background_blur
        if mask_type is not None:
            kwargs["mask_type"] = mask_type
        _image(**kwargs)
        return True
    except Exception as e:
        print(f"[vectcut] add_image: {e}")
        return False


def add_video(
    draft_id: str,
    video_url: str,
    start: float,
    end: float,
    *,
    track_name: str = "background",
    scale_x: float = 1.3,
    scale_y: float = 1.3,
    transform_y: float = 0,
    relative_index: int = 0,
    transition: str | None = None,
    transition_duration: float = 0.7,
    background_blur: int | None = None,
) -> bool:
    """Add an animated video (e.g. Klipy GIF .mp4) to the draft.  Returns True on success."""
    _video = _get_video_track_fn()
    if _video is None:
        # Fallback: add as image if video track unavailable
        return add_image(draft_id, video_url, start, end,
                         track_name=track_name, scale_x=scale_x, scale_y=scale_y,
                         transition=transition, background_blur=background_blur)
    try:
        duration = end - start
        kwargs = dict(
            video_url=video_url,
            width=1080, height=1920,
            start=0,
            end=None,
            target_start=start,
            draft_id=draft_id,
            track_name=track_name,
            scale_x=scale_x, scale_y=scale_y,
            relative_index=relative_index,
            duration=duration,
            volume=0.0,
        )
        if transform_y != 0:
            kwargs["transform_y"] = transform_y
        if background_blur is not None:
            kwargs["background_blur"] = background_blur
        if transition is not None:
            kwargs["transition"] = transition
            kwargs["transition_duration"] = transition_duration
        _video(**kwargs)
        return True
    except Exception as e:
        print(f"[vectcut] add_video: {e}")
        return False


def add_subtitle(
    draft_id: str,
    text: str,
    start: float,
    end: float,
    scene_num: int,
    *,
    font_color: str = "#FFFFFF",
    font_size: float = 12.0,
    transform_y: float = -0.35,
    border_width: float = 0.12,
    shadow_distance: float = 5.0,
    intro_animation: str = "Fade_In",
    intro_duration: float = 0.3,
    background_color: str = "",
    background_alpha: float = 0.0,
) -> bool:
    """Add a text subtitle overlay.  Returns True on success."""
    _text = _get_vectcut().text
    try:
        kwargs = dict(
            text=text,
            start=start, end=end,
            draft_id=draft_id,
            font_color=font_color,
            font_size=font_size,
            track_name=f"text_{scene_num}",
            width=1080, height=1920,
            transform_y=transform_y,
            fixed_width=0.85,
            border_width=border_width,
            border_color="#000000",
            border_alpha=1.0,
            shadow_enabled=True,
            shadow_color="#000000",
            shadow_alpha=1.0,
            shadow_distance=shadow_distance,
            background_alpha=background_alpha,
            intro_animation=intro_animation,
            intro_duration=intro_duration,
        )
        if background_color and background_alpha > 0:
            kwargs["background_color"] = background_color
        _text(**kwargs)
        return True
    except Exception as e:
        print(f"[vectcut] add_text scene {scene_num}: {e}")
        return False


def add_narration(
    draft_id: str,
    audio_url: str,
    duration: float,
    target_start: float,
    scene_num: int,
) -> bool:
    """Add narration audio for one scene.  Returns True on success."""
    _audio = _get_vectcut().audio
    try:
        _audio(
            audio_url=audio_url,
            start=0, end=duration,
            target_start=target_start,
            draft_id=draft_id,
            track_name=f"audio_{scene_num}",
            volume=1.0,
            duration=duration,
        )
        return True
    except Exception as e:
        print(f"[vectcut] add_audio scene {scene_num}: {e}")
        return False


def add_bgm(
    draft_id: str,
    audio_path: str,
    duration: float,
    volume: float = 0.12,
) -> bool:
    """Add background music track.  Uses local file path (not HTTP URL)."""
    _audio = _get_vectcut().audio
    try:
        _audio(
            audio_url=audio_path,
            start=0, end=duration,
            target_start=0,
            draft_id=draft_id,
            track_name="bgm",
            volume=volume,
            duration=duration,
        )
        return True
    except Exception as e:
        print(f"[vectcut] add_bgm: {e}")
        return False


def hash_url(url: str) -> str:
    """Hash a URL for material naming (delegates to VectCutAPI util)."""
    _hash = _get_vectcut().hash_url
    return _hash(url)


def save_draft_to_capcut(
    draft_id: str,
    script,
    scenes: list[dict],
    capcut_draft_dir: Path,
    has_images: bool,
    bgm_path: str | None = None,
) -> str | None:
    """Save the completed draft to CapCut's project directory.

    Handles: template copy, TTS audio copy, image download, material path
    fixup, and draft_meta_info.json patching.

    Returns the draft folder path on success, or ``None`` on failure.
    """
    vc = _get_vectcut()
    _hash, _cache = vc.hash_url, vc.cache

    template_dir = VECTCUT_DIR / "template"
    dest = capcut_draft_dir / draft_id
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(str(template_dir), str(dest))

    cached_script = _cache.get(draft_id, script)

    # -- Copy TTS audio into draft assets --
    audio_dest = dest / "assets" / "audio"
    audio_dest.mkdir(parents=True, exist_ok=True)
    for scene in scenes:
        tts_path = scene.get("_tts_path")
        tts_url = scene.get("_tts_url")
        if tts_path and tts_url and Path(tts_path).exists():
            material_name = f"audio_{_hash(tts_url)}.mp3"
            shutil.copy2(tts_path, str(audio_dest / material_name))

    # -- Copy BGM into draft assets --
    if bgm_path and Path(bgm_path).exists():
        bgm_hash = _hash(bgm_path)
        bgm_ext = Path(bgm_path).suffix.lstrip(".") or "mp3"
        bgm_material = f"audio_{bgm_hash}.{bgm_ext}"
        shutil.copy2(bgm_path, str(audio_dest / bgm_material))
        # VectCutAPI may register the material with .mp3 extension regardless of source format
        if bgm_ext != "mp3":
            shutil.copy2(bgm_path, str(audio_dest / f"audio_{bgm_hash}.mp3"))

    # -- Download/copy images into draft assets --
    image_dest = dest / "assets" / "image"
    image_dest.mkdir(parents=True, exist_ok=True)
    # Collect all unique image URLs (main + sub-images)
    _all_image_urls: list[str] = []
    if has_images:
        for scene in scenes:
            main_url = scene.get("_image_url")
            if main_url and not scene.get("_is_video"):
                _all_image_urls.append(main_url)
            for sub in scene.get("_sub_images", []):
                sub_url = sub.get("url")
                if sub_url and not sub.get("is_video"):
                    _all_image_urls.append(sub_url)
        _seen_urls: set[str] = set()
        for img_url in _all_image_urls:
            if img_url in _seen_urls:
                continue
            _seen_urls.add(img_url)
            try:
                # Local file path (from Imagen AI) — copy directly
                # Hash must match the file:// URI that server.py passes to VectCutAPI
                if not img_url.startswith(("http://", "https://", "file://")):
                    local_src = Path(img_url)
                    if local_src.exists():
                        # VectCutAPI received file:// URI, so hash that for material matching
                        file_uri = local_src.resolve().as_uri()
                        img_hash = _hash(file_uri)
                        ext = local_src.suffix or ".png"
                        img_path = image_dest / f"image_{img_hash}{ext}"
                        shutil.copy2(str(local_src), str(img_path))
                        # Also copy as .png alias for VectCutAPI material matching
                        if ext != ".png":
                            shutil.copy2(str(local_src), str(image_dest / f"image_{img_hash}.png"))
                    continue
                # file:// URI — convert to local path
                if img_url.startswith("file://"):
                    from urllib.parse import unquote
                    from urllib.request import url2pathname
                    img_hash = _hash(img_url)
                    local_path = Path(url2pathname(unquote(img_url[7:])))
                    if local_path.exists():
                        ext = local_path.suffix or ".png"
                        img_path = image_dest / f"image_{img_hash}{ext}"
                        shutil.copy2(str(local_path), str(img_path))
                    continue
                # HTTP URL — download
                img_hash = _hash(img_url)
                req = urllib_request.Request(img_url, headers={"User-Agent": "VideoStudio/1.0"})
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
                    oversized = False
                    with open(str(img_path), "wb") as fp:
                        total = 0
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            total += len(chunk)
                            if total > _MAX_IMAGE_BYTES:
                                oversized = True
                                break
                            fp.write(chunk)
                    if oversized:
                        img_path.unlink(missing_ok=True)
            except Exception as e:
                print(f"[download] Image failed: {e}")

    # -- Download/copy video assets (Klipy GIFs etc.) --
    video_dest = dest / "assets" / "video"
    video_dest.mkdir(parents=True, exist_ok=True)
    _all_video_urls: list[str] = []
    if has_images:
        for scene in scenes:
            main_url = scene.get("_image_url")
            if main_url and scene.get("_is_video"):
                _all_video_urls.append(main_url)
            for sub in scene.get("_sub_images", []):
                sub_url = sub.get("url")
                if sub_url and sub.get("is_video"):
                    _all_video_urls.append(sub_url)
        _seen_vid: set[str] = set()
        for vid_url in _all_video_urls:
            if vid_url in _seen_vid:
                continue
            _seen_vid.add(vid_url)
            try:
                vid_hash = _hash(vid_url)
                req = urllib_request.Request(vid_url, headers={"User-Agent": "VideoStudio/1.0"})
                with urllib_request.urlopen(req, timeout=30) as resp:
                    vid_path = video_dest / f"video_{vid_hash}.mp4"
                    oversized = False
                    with open(str(vid_path), "wb") as fp:
                        total = 0
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            total += len(chunk)
                            if total > _MAX_VIDEO_BYTES:
                                oversized = True
                                break
                            fp.write(chunk)
                    if oversized:
                        vid_path.unlink(missing_ok=True)
                        print(f"[download] Video oversized (>{_MAX_VIDEO_BYTES // 1024 // 1024}MB): {vid_url[:80]}")
            except Exception as e:
                print(f"[download] Video failed: {e}")

    # -- Fix material paths on VectCutAPI script object --
    actual_by_stem: dict[str, Path] = {}
    for fp in image_dest.iterdir():
        if fp.is_file():
            actual_by_stem[fp.stem] = fp

    video_by_stem: dict[str, Path] = {}
    for fp in video_dest.iterdir():
        if fp.is_file():
            video_by_stem[fp.stem] = fp

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
                        png_path = image_dest / video.material_name
                        if not png_path.exists() and actual_fp.suffix != ".png":
                            shutil.copy2(str(actual_fp), str(png_path))
                    video.replace_path = str(image_dest / video.material_name)
                elif getattr(video, "material_type", "") == "video":
                    stem = Path(video.material_name).stem
                    actual_fp = video_by_stem.get(stem)
                    if actual_fp:
                        video.replace_path = str(actual_fp)
                    else:
                        video.replace_path = str(video_dest / video.material_name)

    # -- Save project file --
    cached_script.dump(str(dest / "draft_content.json"))

    # -- Sync font_size: CapCut reads top-level font_size, VectCutAPI only sets styles.size --
    draft_json_path = dest / "draft_content.json"
    with open(str(draft_json_path), "r", encoding="utf-8") as f:
        draft_data = json.load(f)
    for text_mat in draft_data.get("materials", {}).get("texts", []):
        content = text_mat.get("content", "")
        if isinstance(content, str):
            try:
                c = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
        else:
            c = content
        styles = c.get("styles", [])
        if styles and "size" in styles[0]:
            text_mat["font_size"] = styles[0]["size"]
    with open(str(draft_json_path), "w", encoding="utf-8") as f:
        json.dump(draft_data, f, ensure_ascii=False)

    # -- Fix draft_meta_info.json --
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

    return str(dest)
