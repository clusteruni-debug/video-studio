from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from worker.runtime.tools import ToolResolution, probe_tool

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
FRAME_SIZE = "1080x1920"
FRAME_RATE = "30"
SCENE_COLORS = ["#183153", "#3f5c7a", "#7c4d3a", "#556b2f", "#5f4b8b", "#7b3f61"]


@dataclass(slots=True)
class SmokeRenderResult:
    ok: bool
    projectId: str
    manifestPath: str
    outputPath: str
    concatFilePath: str
    subtitleFilePath: str
    logPath: str
    ffmpeg: dict
    sceneClipPaths: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _load_manifest(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _run_ffmpeg(ffmpeg_path: str, args: list[str], log_lines: list[str], cwd: Path | None = None) -> None:
    command = [ffmpeg_path, *args]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW,
        cwd=str(cwd) if cwd else None,
        check=False,
    )
    log_lines.append("$ " + " ".join(command))
    if completed.stdout:
        log_lines.append(completed.stdout.strip())
    if completed.stderr:
        log_lines.append(completed.stderr.strip())
    log_lines.append("")
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"ffmpeg exited with code {completed.returncode}")


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _safe_text(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _asset_lookup(manifest: dict, scene_id: str, role: str) -> dict:
    for asset in manifest["assets"]:
        if asset["sceneId"] == scene_id and asset["role"] == role:
            return asset
    raise KeyError(f"Missing asset for scene={scene_id} role={role}")


def _create_visual_asset(
    ffmpeg_path: str,
    visual_kind: str,
    output_path: Path,
    duration_sec: float,
    color: str,
    log_lines: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if visual_kind == "image":
        _run_ffmpeg(
            ffmpeg_path,
            [
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={FRAME_SIZE}",
                "-frames:v",
                "1",
                str(output_path),
            ],
            log_lines,
        )
        return

    _run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={FRAME_SIZE}:r={FRAME_RATE}",
            "-t",
            f"{duration_sec:.2f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(output_path),
        ],
        log_lines,
    )


def _create_audio_asset(
    ffmpeg_path: str,
    output_path: Path,
    duration_sec: float,
    frequency: int,
    log_lines: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=48000",
            "-t",
            f"{duration_sec:.2f}",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        log_lines,
    )


def _create_scene_clip(
    ffmpeg_path: str,
    visual_kind: str,
    visual_path: Path,
    audio_path: Path,
    clip_path: Path,
    duration_sec: float,
    log_lines: list[str],
) -> None:
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    if visual_kind == "image":
        input_args = [
            "-loop",
            "1",
            "-framerate",
            FRAME_RATE,
            "-t",
            f"{duration_sec:.2f}",
            "-i",
            str(visual_path),
        ]
    else:
        input_args = ["-i", str(visual_path)]

    _run_ffmpeg(
        ffmpeg_path,
        [
            "-y",
            *input_args,
            "-i",
            str(audio_path),
            "-vf",
            "scale=1080:1920,format=yuv420p",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(clip_path),
        ],
        log_lines,
    )


def _write_scene_subtitle(path: Path, subtitle_text: str, duration_sec: float) -> None:
    _write_text(
        path,
        "\n".join(
            [
                "1",
                f"00:00:00,000 --> {_format_srt_timestamp(duration_sec)}",
                _safe_text(subtitle_text),
                "",
            ]
        ),
    )


def _write_project_subtitles(path: Path, scenes: list[dict]) -> None:
    lines: list[str] = []
    for index, scene in enumerate(scenes, start=1):
        lines.extend(
            [
                str(index),
                f"{_format_srt_timestamp(scene['startSec'])} --> {_format_srt_timestamp(scene['endSec'])}",
                _safe_text(scene["subtitleText"]),
                "",
            ]
        )
    _write_text(path, "\n".join(lines))


def _write_concat_file(path: Path, clip_paths: list[Path]) -> None:
    lines = [f"file '{clip_path.resolve().as_posix()}'" for clip_path in clip_paths]
    _write_text(path, "\n".join(lines) + "\n")


def compose_smoke_render(manifest_path: Path | str, project_root: Path | str = ".") -> SmokeRenderResult:
    resolved_project_root = Path(project_root).resolve()
    resolved_manifest_path = Path(manifest_path).resolve()
    manifest = _load_manifest(resolved_manifest_path)

    ffmpeg = probe_tool("ffmpeg", project_root=resolved_project_root)
    if not ffmpeg.path or not ffmpeg.ready:
        raise RuntimeError(ffmpeg.detail or "FFmpeg is not ready for local rendering")

    render_dir = resolved_project_root / manifest["renderDir"]
    render_dir.mkdir(parents=True, exist_ok=True)
    subtitle_file_path = resolved_project_root / manifest["subtitleFilePath"]
    concat_file_path = resolved_project_root / manifest["concatFilePath"]
    output_path = resolved_project_root / manifest["outputPath"]
    log_path = render_dir / "ffmpeg-smoke.log"

    log_lines: list[str] = [f"project_id={manifest['projectId']}", f"manifest={resolved_manifest_path}", ""]
    scene_clip_paths: list[Path] = []

    for index, scene in enumerate(manifest["scenes"]):
        scene_id = scene["sceneId"]
        scene_cache_dir = resolved_project_root / scene["cacheDir"]
        scene_cache_dir.mkdir(parents=True, exist_ok=True)
        visual_asset = _asset_lookup(manifest, scene_id, "visual")
        audio_asset = _asset_lookup(manifest, scene_id, "audio")
        subtitle_asset = _asset_lookup(manifest, scene_id, "subtitle")

        visual_path = resolved_project_root / visual_asset["outputPath"]
        audio_path = resolved_project_root / audio_asset["outputPath"]
        subtitle_path = resolved_project_root / subtitle_asset["outputPath"]
        clip_path = scene_cache_dir / f"{scene_id}.segment.mp4"

        color = SCENE_COLORS[index % len(SCENE_COLORS)]
        frequency = 440 + (index * 70)

        _create_visual_asset(
            ffmpeg_path=ffmpeg.path,
            visual_kind=scene["visualKind"],
            output_path=visual_path,
            duration_sec=scene["durationSec"],
            color=color,
            log_lines=log_lines,
        )
        _create_audio_asset(
            ffmpeg_path=ffmpeg.path,
            output_path=audio_path,
            duration_sec=scene["durationSec"],
            frequency=frequency,
            log_lines=log_lines,
        )
        _write_scene_subtitle(
            path=subtitle_path,
            subtitle_text=scene["subtitleText"],
            duration_sec=scene["durationSec"],
        )
        _create_scene_clip(
            ffmpeg_path=ffmpeg.path,
            visual_kind=scene["visualKind"],
            visual_path=visual_path,
            audio_path=audio_path,
            clip_path=clip_path,
            duration_sec=scene["durationSec"],
            log_lines=log_lines,
        )
        scene_clip_paths.append(clip_path)

    _write_project_subtitles(subtitle_file_path, manifest["scenes"])
    _write_concat_file(concat_file_path, scene_clip_paths)

    _run_ffmpeg(
        ffmpeg.path,
        [
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_file_path.name,
            "-vf",
            f"subtitles={subtitle_file_path.name},scale=1080:1920,format=yuv420p",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            output_path.name,
        ],
        log_lines,
        cwd=render_dir,
    )

    _write_text(log_path, "\n".join(log_lines))

    return SmokeRenderResult(
        ok=True,
        projectId=manifest["projectId"],
        manifestPath=str(resolved_manifest_path),
        outputPath=str(output_path),
        concatFilePath=str(concat_file_path),
        subtitleFilePath=str(subtitle_file_path),
        logPath=str(log_path),
        ffmpeg=ffmpeg.to_dict(),
        sceneClipPaths=[str(path) for path in scene_clip_paths],
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a placeholder FFmpeg smoke render for a saved project bundle.")
    parser.add_argument("--project-id", required=True, help="Project id under storage/inputs/<project-id>")
    parser.add_argument("--project-root", default=".", help="Project root where storage/ lives")
    parser.add_argument("--manifest-path", help="Optional explicit manifest path")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    manifest_path = (
        Path(args.manifest_path).resolve()
        if args.manifest_path
        else project_root / "storage" / "inputs" / args.project_id / "render-manifest.json"
    )
    result = compose_smoke_render(manifest_path=manifest_path, project_root=project_root)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
