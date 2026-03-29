"""Storage cleanup — automatic and on-demand removal of stale generated assets.

Managed directories:
  storage/tts/        — TTS audio (timestamped folders)
  storage/cache/      — Image cache (Imagen results, logs kept)
  storage/renders/    — FFmpeg render outputs
  storage/thumbnails/ — Generated thumbnails
  CapCut drafts       — com.lveditor.draft/ folders

NOT managed (user assets, excluded from cleanup):
  storage/inputs/     — User-uploaded scene assets
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

# Files to always preserve during cleanup
_SKIP_NAMES = {".gitkeep", ".gitignore", "desktop.ini", "Thumbs.db"}

DEFAULT_MAX_AGE_DAYS = 7


def _dir_size(path: Path) -> int:
    """Total bytes of all files under path."""
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _count_items(path: Path) -> int:
    """Count immediate children (files and dirs)."""
    if not path.exists():
        return 0
    return sum(1 for _ in path.iterdir())


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    return f"{size_bytes / 1024 / 1024 / 1024:.1f} GB"


def _is_log_file(name: str) -> bool:
    """Check if a filename is a log file (handles compound extensions)."""
    return name.endswith(".log")


def _should_skip(child: Path) -> bool:
    """Check if a path should be preserved (dotfiles, symlinks, sentinel files)."""
    return child.name in _SKIP_NAMES or child.name.startswith(".") or child.is_symlink()


def storage_status(project_root: Path, capcut_draft_dir: Path | None = None) -> dict:
    """Return storage usage summary for each managed directory."""
    dirs = {
        "tts": project_root / "storage" / "tts",
        "cache": project_root / "storage" / "cache",
        "renders": project_root / "storage" / "renders",
        "thumbnails": project_root / "storage" / "thumbnails",
    }
    result: dict = {}
    for name, path in dirs.items():
        sz = _dir_size(path)
        result[name] = {
            "path": str(path),
            "items": _count_items(path),
            "size_bytes": sz,
            "size_display": format_size(sz),
        }
    # CapCut drafts
    if capcut_draft_dir and capcut_draft_dir.exists():
        draft_count = sum(1 for d in capcut_draft_dir.iterdir() if d.is_dir())
        sz = _dir_size(capcut_draft_dir)
        result["capcut_drafts"] = {
            "path": str(capcut_draft_dir),
            "items": draft_count,
            "size_bytes": sz,
            "size_display": format_size(sz),
        }
    return result


def cleanup_storage(
    project_root: Path,
    capcut_draft_dir: Path | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    dry_run: bool = False,
) -> dict:
    """Remove stale files older than max_age_days.

    Returns summary of deleted items per category.
    """
    cutoff = time.time() - (max_age_days * 86400)
    summary: dict[str, dict] = {}

    # --- TTS: each subfolder is a timestamped session ---
    tts_dir = project_root / "storage" / "tts"
    summary["tts"] = _cleanup_timestamped_dirs(tts_dir, cutoff, dry_run)

    # --- Cache: mixed files and dirs ---
    cache_dir = project_root / "storage" / "cache"
    summary["cache"] = _cleanup_mixed_dir(cache_dir, cutoff, dry_run)

    # --- Renders: project folders ---
    renders_dir = project_root / "storage" / "renders"
    summary["renders"] = _cleanup_timestamped_dirs(renders_dir, cutoff, dry_run)

    # --- Thumbnails: flat files ---
    thumbs_dir = project_root / "storage" / "thumbnails"
    summary["thumbnails"] = _cleanup_flat_files(thumbs_dir, cutoff, dry_run)

    # --- CapCut drafts ---
    if capcut_draft_dir and capcut_draft_dir.exists():
        summary["capcut_drafts"] = _cleanup_capcut_drafts(capcut_draft_dir, cutoff, dry_run)

    return summary


def _cleanup_timestamped_dirs(parent: Path, cutoff: float, dry_run: bool) -> dict:
    """Remove subdirectories whose newest file is older than cutoff."""
    removed = 0
    freed = 0
    if not parent.exists():
        return {"removed": 0, "freed_bytes": 0, "freed_display": "0 B"}
    for child in sorted(parent.iterdir()):
        if not child.is_dir() or _should_skip(child):
            continue
        newest = 0.0
        dir_size = 0
        for f in child.rglob("*"):
            if f.is_file():
                st = f.stat()
                if st.st_mtime > newest:
                    newest = st.st_mtime
                dir_size += st.st_size
        if newest > 0 and newest < cutoff:
            if not dry_run:
                shutil.rmtree(child, ignore_errors=True)
            removed += 1
            freed += dir_size
    return {"removed": removed, "freed_bytes": freed, "freed_display": format_size(freed)}


def _cleanup_mixed_dir(parent: Path, cutoff: float, dry_run: bool) -> dict:
    """Remove old files and old subdirectories. Keep logs, dotfiles, symlinks."""
    removed = 0
    freed = 0
    if not parent.exists():
        return {"removed": 0, "freed_bytes": 0, "freed_display": "0 B"}
    for child in sorted(parent.iterdir()):
        if _should_skip(child):
            continue
        if child.is_dir():
            newest = 0.0
            dir_size = 0
            for f in child.rglob("*"):
                if f.is_file():
                    st = f.stat()
                    if st.st_mtime > newest:
                        newest = st.st_mtime
                    dir_size += st.st_size
            if newest > 0 and newest < cutoff:
                if not dry_run:
                    shutil.rmtree(child, ignore_errors=True)
                removed += 1
                freed += dir_size
        elif child.is_file():
            if _is_log_file(child.name):
                continue
            if child.stat().st_mtime < cutoff:
                size = child.stat().st_size
                if not dry_run:
                    try:
                        child.unlink(missing_ok=True)
                    except OSError:
                        continue  # file locked by another process (Windows)
                removed += 1
                freed += size
    return {"removed": removed, "freed_bytes": freed, "freed_display": format_size(freed)}


def _cleanup_flat_files(parent: Path, cutoff: float, dry_run: bool) -> dict:
    """Remove old files in a flat directory."""
    removed = 0
    freed = 0
    if not parent.exists():
        return {"removed": 0, "freed_bytes": 0, "freed_display": "0 B"}
    for f in parent.iterdir():
        if _should_skip(f):
            continue
        if f.is_file() and f.stat().st_mtime < cutoff:
            size = f.stat().st_size
            if not dry_run:
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    continue  # file locked
            removed += 1
            freed += size
    return {"removed": removed, "freed_bytes": freed, "freed_display": format_size(freed)}


def _cleanup_capcut_drafts(draft_dir: Path, cutoff: float, dry_run: bool) -> dict:
    """Remove CapCut draft folders older than cutoff.

    Skips root_meta_info.json (only iterates directories).
    """
    removed = 0
    freed = 0
    for child in sorted(draft_dir.iterdir()):
        if not child.is_dir() or _should_skip(child):
            continue
        info_file = child / "draft_info.json"
        mtime = info_file.stat().st_mtime if info_file.exists() else child.stat().st_mtime
        if mtime < cutoff:
            dir_size = _dir_size(child)
            if not dry_run:
                shutil.rmtree(child, ignore_errors=True)
            removed += 1
            freed += dir_size
    return {"removed": removed, "freed_bytes": freed, "freed_display": format_size(freed)}
