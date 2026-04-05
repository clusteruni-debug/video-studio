from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
PROJECT_ROOT = Path.cwd()


@dataclass(slots=True)
class ToolResolution:
    name: str
    ready: bool
    path: str | None
    resolvedPath: str | None
    source: str | None
    version: str | None
    detail: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _unique_candidates(candidates: list[tuple[Path, str]]) -> list[tuple[Path, str]]:
    seen: set[str] = set()
    deduped: list[tuple[Path, str]] = []

    for path, source in candidates:
        normalized = str(path).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append((path, source))

    return deduped


def _project_venv_scripts(project_root: Path) -> list[Path]:
    return [
        project_root / ".venv" / "Scripts",
        PROJECT_ROOT / ".venv" / "Scripts",
    ]


def _candidates_for(name: str, project_root: Path) -> list[tuple[Path, str]]:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    program_files = Path(os.environ.get("ProgramFiles", ""))
    program_data = Path(os.environ.get("ProgramData", ""))
    user_profile = Path(os.environ.get("USERPROFILE", ""))

    candidates: list[tuple[Path, str]] = []

    # Ollama resolver removed 2026-04 when the local LLM planner was retired.
    env_candidates = {
        "ffmpeg": ["VIDEO_STUDIO_FFMPEG_PATH", "FFMPEG_PATH"],
        "hf": ["VIDEO_STUDIO_HF_PATH", "HF_CLI_PATH"],
    }
    for env_name in env_candidates.get(name, []):
        value = os.environ.get(env_name)
        if value:
            candidates.append((Path(value), f"env:{env_name}"))

    which_path = shutil.which(name)
    if which_path:
        candidates.append((Path(which_path), "path"))

    if name == "ffmpeg":
        candidates.extend(
            [
                (local_app_data / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe", "winget-link"),
                (program_data / "chocolatey" / "bin" / "ffmpeg.exe", "chocolatey"),
                (Path("C:/ffmpeg/bin/ffmpeg.exe"), "default"),
                (program_files / "ffmpeg" / "bin" / "ffmpeg.exe", "program-files"),
            ]
        )
    elif name == "hf":
        for scripts_dir in _project_venv_scripts(project_root):
            candidates.append((scripts_dir / "hf.exe", "project-venv"))
        candidates.extend(
            [
                (user_profile / "AppData" / "Roaming" / "Python" / "Python314" / "Scripts" / "hf.exe", "python-roaming"),
                (user_profile / "AppData" / "Local" / "Programs" / "Python" / "Python314" / "Scripts" / "hf.exe", "python-local"),
                (user_profile / "AppData" / "Local" / "Python" / "bin" / "Scripts" / "hf.exe", "python-bin"),
            ]
        )

    return _unique_candidates([(path, source) for path, source in candidates if str(path)])


def resolve_tool(name: str, project_root: Path | str = PROJECT_ROOT) -> ToolResolution:
    resolved_project_root = Path(project_root).resolve()
    candidates = _candidates_for(name, resolved_project_root)

    for candidate, source in candidates:
        if os.path.lexists(str(candidate)):
            try:
                resolved_path = str(candidate.resolve(strict=False))
            except OSError:
                resolved_path = str(candidate)
            return ToolResolution(
                name=name,
                ready=False,
                path=str(candidate),
                resolvedPath=resolved_path,
                source=source,
                version=None,
                detail="path resolved; probe not yet executed",
            )

    return ToolResolution(
        name=name,
        ready=False,
        path=None,
        resolvedPath=None,
        source=None,
        version=None,
        detail="tool not found in PATH or common Windows install locations",
    )


def _probe_args(name: str) -> list[str]:
    if name == "ffmpeg":
        return ["-version"]
    return ["--version"]


def _run_probe(executable: str, name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [executable, *_probe_args(name)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=8,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )


def probe_tool(name: str, project_root: Path | str = PROJECT_ROOT) -> ToolResolution:
    resolution = resolve_tool(name, project_root=project_root)
    if not resolution.path:
        return resolution

    probe_candidates = [resolution.path]
    if resolution.resolvedPath and resolution.resolvedPath != resolution.path:
        probe_candidates.append(resolution.resolvedPath)

    last_error: OSError | None = None
    completed: subprocess.CompletedProcess[str] | None = None

    try:
        for candidate in probe_candidates:
            try:
                completed = _run_probe(candidate, name)
                if candidate == resolution.resolvedPath:
                    resolution.path = candidate
                break
            except OSError as error:
                last_error = error
                continue
    except subprocess.TimeoutExpired:
        resolution.detail = "probe timed out after 8 seconds"
        resolution.ready = False
        return resolution

    if completed is None:
        resolution.detail = str(last_error) if last_error else "probe failed before execution"
        resolution.ready = False
        return resolution

    combined_output = (completed.stdout or completed.stderr or "").strip()
    version_line = combined_output.splitlines()[0].strip() if combined_output else None
    resolution.version = version_line
    if completed.returncode == 0:
        resolution.ready = True
        resolution.detail = "ok"
    else:
        resolution.ready = False
        resolution.detail = version_line or f"probe exited with code {completed.returncode}"

    return resolution


def probe_tools(project_root: Path | str = PROJECT_ROOT) -> dict[str, ToolResolution]:
    return {
        tool_name: probe_tool(tool_name, project_root=project_root)
        for tool_name in ("ffmpeg", "hf")
    }
