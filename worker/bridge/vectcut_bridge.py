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

_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


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
    relative_index: int = 0,
    intro_animation: str = "Fade_In",
    intro_animation_duration: float = 0.5,
    transition: str | None = None,
    transition_duration: float = 0.7,
) -> bool:
    """Add a background image to the draft.  Returns True on success."""
    _image = _get_vectcut().image
    try:
        _image(
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
        return True
    except Exception as e:
        print(f"[vectcut] add_image: {e}")
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
) -> bool:
    """Add a text subtitle overlay.  Returns True on success."""
    _text = _get_vectcut().text
    try:
        _text(
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
            background_alpha=0.0,
            intro_animation="Fade_In",
            intro_duration=0.3,
        )
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

    # -- Download images into draft assets --
    image_dest = dest / "assets" / "image"
    image_dest.mkdir(parents=True, exist_ok=True)
    if has_images:
        for scene in scenes:
            img_url = scene.get("_image_url")
            if not img_url:
                continue
            img_hash = _hash(img_url)
            try:
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

    # -- Fix material paths on VectCutAPI script object --
    actual_by_stem: dict[str, Path] = {}
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
                        png_path = image_dest / video.material_name
                        if not png_path.exists() and actual_fp.suffix != ".png":
                            shutil.copy2(str(actual_fp), str(png_path))
                    video.replace_path = str(image_dest / video.material_name)

    # -- Save project file --
    cached_script.dump(str(dest / "draft_content.json"))

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
