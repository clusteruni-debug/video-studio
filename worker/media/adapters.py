from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DEFAULT_TIMEOUT_SEC = 900

ADAPTER_CONFIG = {
    # ----- image providers -----
    # Note: "pollinations" and "flux" adapters removed — Pollinations API
    # went paid-only (401) in 2026-03. All image gen routes through Imagen 4.
    "dalle3": {
        "label": "DALL-E 3 (OpenAI)",
        "category": "image",
        "model": "dall-e-3",
        "outputKind": "image",
        "envPrefix": "VIDEO_STUDIO_DALLE3",
        "costTier": "premium",
        "costPerUnit": 0.04,
    },
    "gemini-flash": {
        "label": "Gemini 2.5 Flash Image (Google, free)",
        "category": "image",
        "model": "gemini-2.5-flash-image",
        "outputKind": "image",
        "envPrefix": "VIDEO_STUDIO_GEMINI_FLASH",
        "costTier": "free",
        "costPerUnit": 0.0,
    },
    "imagen": {
        "label": "Imagen 4 (Google)",
        "category": "image",
        "model": "imagen-4.0-fast-generate-001",
        "outputKind": "image",
        "envPrefix": "VIDEO_STUDIO_IMAGEN",
        "costTier": "cheap",
        "costPerUnit": 0.02,
    },
    "pexels-image": {
        "label": "Pexels Stock Image (free)",
        "category": "image",
        "model": "pexels-api-v1",
        "outputKind": "image",
        "envPrefix": "VIDEO_STUDIO_PEXELS",
        "costTier": "free",
        "costPerUnit": 0.0,
    },
    # ----- video providers -----
    "pexels-video": {
        "label": "Pexels Stock Video (free)",
        "category": "video",
        "model": "pexels-api-videos",
        "outputKind": "video",
        "envPrefix": "VIDEO_STUDIO_PEXELS_VIDEO",
        "costTier": "free",
        "costPerUnit": 0.0,
    },
    "wan": {
        "label": "Wan video adapter (local)",
        "category": "video",
        "model": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        "outputKind": "video",
        "envPrefix": "VIDEO_STUDIO_WAN",
        "costTier": "free",
        "costPerUnit": 0.0,
    },
    "sora2": {
        "label": "Sora 2 (OpenAI)",
        "category": "video",
        "model": "sora-2",
        "outputKind": "video",
        "envPrefix": "VIDEO_STUDIO_SORA2",
        "costTier": "premium",
        "costPerUnit": 0.10,
    },
    "veo3": {
        "label": "Veo 3 (Google)",
        "category": "video",
        "model": "veo-3",
        "outputKind": "video",
        "envPrefix": "VIDEO_STUDIO_VEO3",
        "costTier": "premium",
        "costPerUnit": 0.15,
    },
    "runway": {
        "label": "Runway Gen-3",
        "category": "video",
        "model": "gen-3-alpha",
        "outputKind": "video",
        "envPrefix": "VIDEO_STUDIO_RUNWAY",
        "costTier": "premium",
        "costPerUnit": 0.05,
    },
    # ----- TTS providers -----
    "edge-tts": {
        "label": "Edge TTS (free, cross-platform)",
        "category": "tts",
        "model": "edge-tts",
        "outputKind": "audio",
        "envPrefix": "VIDEO_STUDIO_EDGE_TTS",
        "costTier": "free",
        "costPerUnit": 0.0,
    },
    "windows-tts": {
        "label": "Windows Speech (local)",
        "category": "tts",
        "model": "windows-speech",
        "outputKind": "audio",
        "envPrefix": "VIDEO_STUDIO_WINDOWS_TTS",
        "costTier": "free",
        "costPerUnit": 0.0,
    },
    "elevenlabs": {
        "label": "ElevenLabs TTS",
        "category": "tts",
        "model": "eleven_multilingual_v2",
        "outputKind": "audio",
        "envPrefix": "VIDEO_STUDIO_ELEVENLABS",
        "costTier": "premium",
        "costPerUnit": 0.003,
    },
    "openai-tts": {
        "label": "OpenAI TTS",
        "category": "tts",
        "model": "tts-1",
        "outputKind": "audio",
        "envPrefix": "VIDEO_STUDIO_OPENAI_TTS",
        "costTier": "cheap",
        "costPerUnit": 0.015,
    },
    # ----- BGM providers -----
    "local-bgm": {
        "label": "Local BGM library",
        "category": "bgm",
        "model": "local-library",
        "outputKind": "audio",
        "envPrefix": "VIDEO_STUDIO_LOCAL_BGM",
        "costTier": "free",
        "costPerUnit": 0.0,
    },
    "suno": {
        "label": "Suno AI BGM",
        "category": "bgm",
        "model": "suno-v4",
        "outputKind": "audio",
        "envPrefix": "VIDEO_STUDIO_SUNO",
        "costTier": "premium",
        "costPerUnit": 0.05,
    },
    # ----- SFX providers -----
    "freesound": {
        "label": "Freesound SFX",
        "category": "sfx",
        "model": "freesound-api",
        "outputKind": "audio",
        "envPrefix": "VIDEO_STUDIO_FREESOUND",
        "costTier": "free",
        "costPerUnit": 0.0,
    },
    "local-sfx": {
        "label": "Local SFX library",
        "category": "sfx",
        "model": "local-library",
        "outputKind": "audio",
        "envPrefix": "VIDEO_STUDIO_LOCAL_SFX",
        "costTier": "free",
        "costPerUnit": 0.0,
    },
}

# Category helpers
CATEGORIES = ("image", "video", "tts", "bgm", "sfx")


def adapters_by_category(category: str) -> dict[str, dict]:
    """Return adapter configs filtered by category."""
    return {k: v for k, v in ADAPTER_CONFIG.items() if v.get("category") == category}


def free_adapters_by_category(category: str) -> list[str]:
    """Return adapter keys for free providers in a category, ordered by preference."""
    return [k for k, v in ADAPTER_CONFIG.items()
            if v.get("category") == category and v.get("costTier") == "free"]


@dataclass(slots=True)
class MediaAdapterStatus:
    key: str
    label: str
    mode: str
    outputKind: str
    model: str
    ready: bool
    fallbackAvailable: bool
    entryPoint: str | None
    commandPreview: str | None
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class AdapterExecutionContext:
    adapterKey: str
    sceneId: str
    sceneTitle: str
    prompt: str
    durationSec: float
    projectRoot: str
    cacheDir: str
    route: str
    manifestPath: str
    promptPath: str
    requestPath: str
    logPath: str
    outputPath: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class MediaGenerationResult:
    sceneId: str
    sceneTitle: str
    adapterKey: str | None
    mode: str
    outputKind: str
    status: str
    outputPath: str
    detail: str
    attempted: bool
    succeeded: bool | None
    commandPreview: str | None = None
    requestPath: str | None = None
    logPath: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_mode(value: str | None) -> str:
    candidate = (value or "stub").strip().lower()
    if candidate in {"off", "stub", "command"}:
        return candidate
    return "stub"


def _replace_placeholders(value: str, replacements: dict[str, str]) -> str:
    resolved = value
    for key, replacement in replacements.items():
        resolved = resolved.replace(f"{{{key}}}", replacement)
    return resolved


def _parse_command_template(env_name: str) -> tuple[list[str] | None, str | None]:
    raw = os.environ.get(env_name)
    if not raw:
        return None, f"{env_name} is not set"

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        return None, f"{env_name} must be a JSON string array: {error.msg}"

    if not isinstance(parsed, list) or not parsed:
        return None, f"{env_name} must be a non-empty JSON string array"

    if any(not isinstance(item, str) or not item.strip() for item in parsed):
        return None, f"{env_name} entries must be non-empty strings"

    return parsed, None


def _resolve_entry_point(command_template: list[str], project_root: Path) -> tuple[str | None, str | None]:
    first_token = _replace_placeholders(command_template[0], {"project_root": str(project_root)})
    if not first_token:
        return None, None

    candidate = Path(first_token)
    if candidate.is_absolute() or candidate.anchor:
        if os.path.lexists(str(candidate)):
            try:
                return str(candidate.resolve(strict=False)), str(candidate.resolve(strict=False))
            except OSError:
                return str(candidate), str(candidate)
        return None, str(candidate)

    relative_candidate = (project_root / candidate).resolve()
    if os.path.lexists(str(relative_candidate)):
        return str(relative_candidate), str(relative_candidate)

    which_candidate = shutil.which(first_token)
    if which_candidate:
        return which_candidate, which_candidate

    return None, first_token


def _command_preview(command_template: list[str], project_root: Path) -> str:
    preview_tokens = [
        _replace_placeholders(token, {"project_root": str(project_root)})
        for token in command_template
    ]
    return subprocess.list2cmdline(preview_tokens)


def _timeout_seconds() -> int:
    raw = os.environ.get("VIDEO_STUDIO_MEDIA_TIMEOUT_SEC", str(DEFAULT_TIMEOUT_SEC)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SEC
    return max(1, value)


def probe_local_media_adapter(key: str, project_root: Path | str = ".") -> MediaAdapterStatus:
    if key not in ADAPTER_CONFIG:
        raise KeyError(f"Unknown local media adapter: {key}")

    config = ADAPTER_CONFIG[key]
    resolved_project_root = Path(project_root).resolve()
    env_prefix = config["envPrefix"]
    mode = _normalize_mode(os.environ.get(f"{env_prefix}_MODE"))

    if mode == "off":
        return MediaAdapterStatus(
            key=key,
            label=config["label"],
            mode=mode,
            outputKind=config["outputKind"],
            model=config["model"],
            ready=False,
            fallbackAvailable=True,
            entryPoint=None,
            commandPreview=None,
            detail=f"{env_prefix}_MODE=off; the adapter is disabled and render uses placeholder fallback",
        )

    if mode == "stub":
        return MediaAdapterStatus(
            key=key,
            label=config["label"],
            mode=mode,
            outputKind=config["outputKind"],
            model=config["model"],
            ready=False,
            fallbackAvailable=True,
            entryPoint=None,
            commandPreview=None,
            detail=f"{env_prefix}_MODE=stub; configure {env_prefix}_COMMAND to switch from placeholder fallback to model execution",
        )

    command_template, parse_error = _parse_command_template(f"{env_prefix}_COMMAND")
    if parse_error or not command_template:
        return MediaAdapterStatus(
            key=key,
            label=config["label"],
            mode=mode,
            outputKind=config["outputKind"],
            model=config["model"],
            ready=False,
            fallbackAvailable=True,
            entryPoint=None,
            commandPreview=None,
            detail=parse_error or f"{env_prefix}_COMMAND is not configured",
        )

    entry_point, resolved_probe = _resolve_entry_point(command_template, resolved_project_root)
    return MediaAdapterStatus(
        key=key,
        label=config["label"],
        mode=mode,
        outputKind=config["outputKind"],
        model=config["model"],
        ready=bool(entry_point),
        fallbackAvailable=True,
        entryPoint=entry_point,
        commandPreview=_command_preview(command_template, resolved_project_root),
        detail=(
            "command adapter ready"
            if entry_point
            else f"command entrypoint not found: {resolved_probe}"
        ),
    )


def probe_local_media_adapters(project_root: Path | str = ".") -> dict[str, MediaAdapterStatus]:
    return {
        key: probe_local_media_adapter(key, project_root=project_root)
        for key in ADAPTER_CONFIG
    }


def run_local_media_adapter(
    key: str,
    context: AdapterExecutionContext,
    project_root: Path | str = ".",
) -> MediaGenerationResult:
    status = probe_local_media_adapter(key, project_root=project_root)
    output_path = Path(context.outputPath)
    request_path = Path(context.requestPath)
    log_path = Path(context.logPath)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if status.mode != "command" or not status.ready:
        return MediaGenerationResult(
            sceneId=context.sceneId,
            sceneTitle=context.sceneTitle,
            adapterKey=key,
            mode=status.mode,
            outputKind=status.outputKind,
            status="placeholder",
            outputPath=str(output_path),
            detail=status.detail,
            attempted=False,
            succeeded=None,
            commandPreview=status.commandPreview,
            requestPath=str(request_path),
            logPath=str(log_path),
        )

    command_template, parse_error = _parse_command_template(f"{ADAPTER_CONFIG[key]['envPrefix']}_COMMAND")
    if parse_error or not command_template:
        return MediaGenerationResult(
            sceneId=context.sceneId,
            sceneTitle=context.sceneTitle,
            adapterKey=key,
            mode=status.mode,
            outputKind=status.outputKind,
            status="placeholder",
            outputPath=str(output_path),
            detail=parse_error or "command template missing",
            attempted=False,
            succeeded=None,
            commandPreview=status.commandPreview,
            requestPath=str(request_path),
            logPath=str(log_path),
        )

    replacements = {
        "project_root": context.projectRoot,
        "scene_id": context.sceneId,
        "job_path": context.requestPath,
        "request_path": context.requestPath,
        "prompt_path": context.promptPath,
        "log_path": context.logPath,
        "output_path": context.outputPath,
        "duration_sec": f"{context.durationSec:.2f}",
        "route": context.route,
    }
    command = [_replace_placeholders(token, replacements) for token in command_template]
    command_preview = subprocess.list2cmdline(command)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=context.projectRoot,
            timeout=_timeout_seconds(),
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        log_path.write_text(
            "\n".join(
                [
                    f"command={command_preview}",
                    f"exit_code={completed.returncode}",
                    "",
                    "[stdout]",
                    completed.stdout.strip(),
                    "",
                    "[stderr]",
                    completed.stderr.strip(),
                    "",
                ]
            ),
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired as error:
        log_path.write_text(
            "\n".join(
                [
                    f"command={command_preview}",
                    f"timeout_seconds={_timeout_seconds()}",
                    "",
                    "[stdout]",
                    (error.stdout or "").strip(),
                    "",
                    "[stderr]",
                    (error.stderr or "").strip(),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return MediaGenerationResult(
            sceneId=context.sceneId,
            sceneTitle=context.sceneTitle,
            adapterKey=key,
            mode=status.mode,
            outputKind=status.outputKind,
            status="placeholder",
            outputPath=str(output_path),
            detail="adapter command timed out; placeholder fallback will be used",
            attempted=True,
            succeeded=False,
            commandPreview=command_preview,
            requestPath=str(request_path),
            logPath=str(log_path),
        )
    except OSError as error:
        log_path.write_text(f"command={command_preview}\nerror={error}\n", encoding="utf-8")
        return MediaGenerationResult(
            sceneId=context.sceneId,
            sceneTitle=context.sceneTitle,
            adapterKey=key,
            mode=status.mode,
            outputKind=status.outputKind,
            status="placeholder",
            outputPath=str(output_path),
            detail=f"adapter command could not start: {error}",
            attempted=True,
            succeeded=False,
            commandPreview=command_preview,
            requestPath=str(request_path),
            logPath=str(log_path),
        )

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"command exited with {completed.returncode}"
        return MediaGenerationResult(
            sceneId=context.sceneId,
            sceneTitle=context.sceneTitle,
            adapterKey=key,
            mode=status.mode,
            outputKind=status.outputKind,
            status="placeholder",
            outputPath=str(output_path),
            detail=f"adapter command failed; placeholder fallback will be used: {detail}",
            attempted=True,
            succeeded=False,
            commandPreview=command_preview,
            requestPath=str(request_path),
            logPath=str(log_path),
        )

    if not output_path.exists():
        return MediaGenerationResult(
            sceneId=context.sceneId,
            sceneTitle=context.sceneTitle,
            adapterKey=key,
            mode=status.mode,
            outputKind=status.outputKind,
            status="placeholder",
            outputPath=str(output_path),
            detail="adapter command completed without creating the requested output; placeholder fallback will be used",
            attempted=True,
            succeeded=False,
            commandPreview=command_preview,
            requestPath=str(request_path),
            logPath=str(log_path),
        )

    return MediaGenerationResult(
        sceneId=context.sceneId,
        sceneTitle=context.sceneTitle,
        adapterKey=key,
        mode=status.mode,
        outputKind=status.outputKind,
        status="generated",
        outputPath=str(output_path),
        detail="adapter command created the requested output",
        attempted=True,
        succeeded=True,
        commandPreview=command_preview,
        requestPath=str(request_path),
        logPath=str(log_path),
    )
