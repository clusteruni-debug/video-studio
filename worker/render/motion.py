"""FFmpeg zoompan filter builders for still-image motion presets (Ken Burns effects)."""

from __future__ import annotations

import random as _random

MOTION_PRESETS = ("zoom_in", "zoom_out", "pan_left", "pan_right", "drift_up", "drift_down")


def zoompan_filter(
    preset: str,
    duration_sec: float,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
) -> str | None:
    """Return a zoompan filter string for the given *preset*.

    Returns ``None`` when *preset* is ``"none"`` or unrecognised so the caller
    can fall back to a static loop.
    """
    if preset == "none" or not preset:
        return None

    if preset == "random":
        preset = _random.choice(MOTION_PRESETS)

    frames = max(1, int(duration_sec * fps))
    size = f"{width}x{height}"

    builders = {
        "zoom_in": _zoom_in,
        "zoom_out": _zoom_out,
        "pan_left": _pan_left,
        "pan_right": _pan_right,
        "drift_up": _drift_up,
        "drift_down": _drift_down,
    }

    builder = builders.get(preset)
    if builder is None:
        return None

    return builder(frames=frames, size=size, fps=fps)


# ---------------------------------------------------------------------------
# Individual preset builders
# ---------------------------------------------------------------------------

def _zoom_in(*, frames: int, size: str, fps: int) -> str:
    """Slow zoom into centre (Ken Burns classic)."""
    return (
        f"zoompan=z='min(zoom+0.0015,1.3)'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={size}:fps={fps}"
    )


def _zoom_out(*, frames: int, size: str, fps: int) -> str:
    """Slow zoom out from centre."""
    return (
        f"zoompan=z='if(lte(zoom,1.0),1.3,max(1.001,zoom-0.0015))'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={size}:fps={fps}"
    )


def _pan_left(*, frames: int, size: str, fps: int) -> str:
    """Horizontal drift from right to left."""
    return (
        f"zoompan=z=1.15"
        f":x='(iw-iw/zoom)*(1-on/{frames})':y='(ih-ih/zoom)/2'"
        f":d={frames}:s={size}:fps={fps}"
    )


def _pan_right(*, frames: int, size: str, fps: int) -> str:
    """Horizontal drift from left to right."""
    return (
        f"zoompan=z=1.15"
        f":x='(iw-iw/zoom)*(on/{frames})':y='(ih-ih/zoom)/2'"
        f":d={frames}:s={size}:fps={fps}"
    )


def _drift_up(*, frames: int, size: str, fps: int) -> str:
    """Vertical drift from bottom to top."""
    return (
        f"zoompan=z=1.15"
        f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)*(1-on/{frames})'"
        f":d={frames}:s={size}:fps={fps}"
    )


def _drift_down(*, frames: int, size: str, fps: int) -> str:
    """Vertical drift from top to bottom."""
    return (
        f"zoompan=z=1.15"
        f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)*(on/{frames})'"
        f":d={frames}:s={size}:fps={fps}"
    )
