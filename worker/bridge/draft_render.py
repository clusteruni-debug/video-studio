"""Bridge: convert create-draft output → render-manifest.json → compose.py MP4.

This module reuses the existing compose_smoke_render pipeline.
It converts the scene list from create-draft into the RenderManifest format,
pre-placing TTS audio and downloaded images so compose.py skips re-generation.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib import request as urllib_request

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path.cwd()


def draft_to_manifest(
    scenes: list[dict],
    topic: str,
    bgm_file: str | None = None,
) -> dict:
    """Convert create-draft scene list into a render-manifest dict."""
    ts = str(int(time.time()))
    project_id = f"draft-{ts}"
    storage = "storage"
    input_dir = f"{storage}/inputs/{project_id}"
    cache_dir = f"{storage}/cache/{project_id}"
    render_dir = f"{storage}/renders/{project_id}"

    manifest_scenes = []
    manifest_assets = []
    cumulative = 0.0

    for scene in scenes:
        n = scene["scene_num"]
        scene_id = f"scene-{n:02d}"
        dur = scene.get("_tts_duration", 5.0) + 0.5
        narration = scene.get("narration", "").replace("\n", " ").strip()
        img_url = scene.get("_image_url")
        is_video = scene.get("_is_video", False)

        scene_cache = f"{cache_dir}/{scene_id}"
        visual_kind = "video" if is_video else "image"
        visual_ext = ".mp4" if is_video else ".png"

        manifest_scenes.append({
            "sceneId": scene_id,
            "title": scene.get("display_text", f"Scene {n}"),
            "startSec": round(cumulative, 2),
            "endSec": round(cumulative + dur, 2),
            "durationSec": round(dur, 2),
            "route": "local",
            "visualKind": visual_kind,
            "audioKind": "voiceover",
            "subtitleText": narration,
            "cacheDir": scene_cache,
            "assetIds": [
                f"{scene_id}-visual",
                f"{scene_id}-audio",
                f"{scene_id}-subtitle",
            ],
            "motionPreset": "zoom_in",
        })

        # Visual asset — mark as "uploaded" so compose.py skips adapter generation
        visual_output = f"{scene_cache}/{scene_id}{visual_ext}"
        manifest_assets.append({
            "id": f"{scene_id}-visual",
            "sceneId": scene_id,
            "role": "visual",
            "provider": scene.get("image_source", "local"),
            "kind": visual_kind,
            "prompt": scene.get("image_prompt", narration[:60]),
            "durationSec": round(dur, 2),
            "outputPath": visual_output,
            "sourceOrigin": "uploaded" if img_url else None,
            "sourcePath": visual_output if img_url else None,
        })

        # Audio asset — sourcePath points to existing TTS file
        tts_path = scene.get("_tts_path")
        manifest_assets.append({
            "id": f"{scene_id}-audio",
            "sceneId": scene_id,
            "role": "audio",
            "provider": "edge-tts",
            "kind": "voiceover",
            "prompt": narration,
            "durationSec": round(dur, 2),
            "outputPath": f"{scene_cache}/{scene_id}.wav",
            "sourcePath": tts_path,
        })

        # Subtitle asset
        manifest_assets.append({
            "id": f"{scene_id}-subtitle",
            "sceneId": scene_id,
            "role": "subtitle",
            "provider": "local",
            "kind": "srt-line",
            "prompt": narration,
            "durationSec": round(dur, 2),
            "outputPath": f"{scene_cache}/{scene_id}.srt",
        })

        cumulative += dur

    total_dur = round(cumulative, 2)
    slug = f"draft-{ts}"

    return {
        "version": 1,
        "projectId": project_id,
        "title": topic[:60],
        "aspectRatio": "9:16",
        "storageRoot": storage,
        "inputDir": input_dir,
        "cacheDir": cache_dir,
        "renderDir": render_dir,
        "concatFilePath": f"{render_dir}/concat.txt",
        "subtitleFilePath": f"{render_dir}/captions.srt",
        "outputPath": f"{render_dir}/{slug}.mp4",
        "totalDurationSec": total_dur,
        "estimatedCostUsd": 0.0,
        "scenes": manifest_scenes,
        "assets": manifest_assets,
        "composeCommandPreview": f"python -m worker.render.compose --project-id {project_id}",
        "transitionType": "none",
        "transitionDuration": 0.0,
    }


_VALID_MEDIA_TYPES = {"image/", "video/", "application/octet-stream"}

def _download_to(url: str, dest: Path, timeout: int = 20) -> bool:
    """Download URL to local path. Returns True on success."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib_request.Request(url, headers={
            "User-Agent": "VideoStudio/1.0",
            "Accept": "image/*,video/*,*/*;q=0.1",
        })
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            ct = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            if ct and not any(ct.startswith(t) for t in _VALID_MEDIA_TYPES):
                logger.warning("invalid content-type %s for %s", ct, url[:60])
                return False
            with open(str(dest), "wb") as fp:
                total = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 30 * 1024 * 1024:  # 30MB cap
                        dest.unlink(missing_ok=True)
                        return False
                    fp.write(chunk)
        return True
    except Exception as e:
        logger.warning("download failed %s: %s", url[:60], e)
        dest.unlink(missing_ok=True)
        return False


_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _ffmpeg(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run ffmpeg with Windows-safe flags."""
    return subprocess.run(
        ["ffmpeg", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=_CREATE_NO_WINDOW, cwd=str(cwd) if cwd else None, check=False,
    )


def prepare_and_render(
    scenes: list[dict],
    topic: str,
    bgm_file: str | None = None,
) -> dict:
    """Direct FFmpeg render: image + TTS + subtitle → scene clips → concat → MP4."""
    ts = str(int(time.time()))
    project_id = f"draft-{ts}"
    render_dir = PROJECT_ROOT / "storage" / "renders" / project_id
    cache_dir = PROJECT_ROOT / "storage" / "cache" / project_id
    render_dir.mkdir(parents=True, exist_ok=True)

    scene_clips: list[Path] = []
    log_lines: list[str] = [f"project_id={project_id}", ""]

    for scene in scenes:
        n = scene["scene_num"]
        dur = scene.get("_tts_duration", 5.0) + 0.5
        narration = scene.get("narration", "").replace("\n", " ").strip()
        img_url = scene.get("_image_url")
        tts_path = scene.get("_tts_path")

        scene_dir = cache_dir / f"scene-{n:02d}"
        scene_dir.mkdir(parents=True, exist_ok=True)
        clip_path = scene_dir / f"scene-{n:02d}.mp4"

        # Download image
        img_path = scene_dir / f"scene-{n:02d}.png"
        if img_url:
            if img_url.startswith(("http://", "https://")):
                if not _download_to(img_url, img_path):
                    img_path = None
            else:
                src = Path(img_url)
                if src.exists():
                    shutil.copy2(str(src), str(img_path))
                else:
                    img_path = None
        else:
            img_path = None

        # Build FFmpeg command for this scene
        # zoompan z= uses FFmpeg expr syntax: 'zoom' is a built-in variable (current zoom level).
        # Single quotes inside f-string are safe — subprocess.run passes list args directly, no shell.
        if img_path and img_path.exists() and tts_path and Path(tts_path).exists():
            # Image + TTS audio → video clip with Ken Burns zoom
            r = _ffmpeg([
                "-y", "-loop", "1", "-i", str(img_path),
                "-i", str(tts_path),
                "-vf", f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                       f"zoompan=z='min(zoom+0.001,1.15)':d={int(dur*30)}:s=1080x1920:fps=30,"
                       f"format=yuv420p",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-t", str(dur),
                str(clip_path),
            ])
            log_lines.append(f"scene {n}: image+tts ok={r.returncode == 0}")
        elif img_path and img_path.exists():
            # Image only (no TTS) → silent video clip
            r = _ffmpeg([
                "-y", "-loop", "1", "-i", str(img_path),
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                "-vf", f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                       f"zoompan=z='min(zoom+0.001,1.15)':d={int(dur*30)}:s=1080x1920:fps=30,"
                       f"format=yuv420p",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-shortest", "-t", str(dur),
                str(clip_path),
            ])
            log_lines.append(f"scene {n}: image-only ok={r.returncode == 0}")
        elif tts_path and Path(tts_path).exists():
            # TTS only → gradient background + audio
            r = _ffmpeg([
                "-y", "-f", "lavfi",
                "-i", f"color=c=#183153:s=1080x1920:d={dur}:r=30",
                "-i", str(tts_path),
                "-vf", "format=yuv420p",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-t", str(dur),
                str(clip_path),
            ])
            log_lines.append(f"scene {n}: tts-only ok={r.returncode == 0}")
        else:
            # Placeholder: gradient + silence
            r = _ffmpeg([
                "-y", "-f", "lavfi",
                "-i", f"color=c=#183153:s=1080x1920:d={dur}:r=30",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                "-vf", "format=yuv420p",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-shortest", "-t", str(dur),
                str(clip_path),
            ])
            log_lines.append(f"scene {n}: placeholder ok={r.returncode == 0}")

        if r.returncode != 0:
            log_lines.append(f"  stderr: {r.stderr[:300]}")
            clip_path.unlink(missing_ok=True)

        if r.returncode == 0 and clip_path.exists():
            scene_clips.append(clip_path)

    if not scene_clips:
        return {"ok": False, "projectId": project_id, "error": "No scene clips generated"}

    # Concat all clips
    concat_file = render_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{c.as_posix()}'" for c in scene_clips),
        encoding="utf-8",
    )
    output_path = render_dir / f"{project_id}.mp4"
    r = _ffmpeg([
        "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ])
    log_lines.append(f"concat: ok={r.returncode == 0}")
    if r.returncode != 0:
        log_lines.append(f"  stderr: {r.stderr[:300]}")

    # Write log
    (render_dir / "render.log").write_text("\n".join(log_lines), encoding="utf-8")

    if output_path.exists():
        return {
            "ok": True,
            "projectId": project_id,
            "outputPath": str(output_path),
        }
    return {"ok": False, "projectId": project_id, "error": "concat failed"}
