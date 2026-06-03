"""Local procedural foley helpers for no-voice Grok-first renders."""
from __future__ import annotations

from pathlib import Path

from worker.render.compose_ffmpeg import run_ffmpeg


PROCEDURAL_FOLEY_LICENSE = (
    "Operator-owned procedural audio generated locally by Video Studio with "
    "FFmpeg synthesis filters; no third-party samples."
)
PROCEDURAL_FOLEY_LICENSE_URL = "local://video-studio/license/procedural-foley"
PROCEDURAL_FOLEY_CREATOR = "Video Studio local procedural foley generator"


def infer_procedural_foley_pattern(scene: dict) -> str:
    """Infer a subtle foley pattern from viewer scene metadata."""
    scene_id = str(scene.get("sceneId") or "").lower()
    text = " ".join(
        str(scene.get(key) or "")
        for key in (
            "title",
            "subtitleText",
            "visualSourceIntent",
            "grokPrompt",
            "hookNote",
            "continuityNote",
        )
    ).lower()

    if any(term in text for term in ("kitchen", "fridge", "vegetable", "slice", "cutting", "board")):
        return "kitchen-prep"
    if any(term in text for term in ("subway", "train", "platform", "commute", "station")):
        return "commute-room"
    if any(term in text for term in ("mat", "stretch", "shoulder", "neck", "room rolls")):
        return "mat-rustle"
    if any(term in text for term in ("lowers the", "lowers the warm desk lamp", "closes notebook", "calm finish")):
        return "lamp-switch"
    if any(term in text for term in ("desk", "notebook", "write", "writing", "phone", "pen")):
        return "desk-notes"

    if scene_id.endswith("02"):
        return "kitchen-prep"
    if scene_id.endswith("03"):
        return "desk-notes"
    if scene_id.endswith("04"):
        return "mat-rustle"
    if scene_id.endswith("05"):
        return "lamp-switch"
    return "commute-room" if scene_id.endswith("01") else "soft-room"


def procedural_foley_label(pattern: str) -> str:
    labels = {
        "commute-room": "Subtle commute room tone and strap movement",
        "kitchen-prep": "Soft kitchen prep taps and room tone",
        "desk-notes": "Quiet desk pen taps and notebook texture",
        "mat-rustle": "Soft mat rustle and room movement",
        "lamp-switch": "Lamp switch click and late-room tone",
        "soft-room": "Subtle late-room ambience",
    }
    return labels.get(pattern, labels["soft-room"])


def _foley_components(pattern: str, duration_sec: float) -> list[dict[str, str]]:
    duration = max(float(duration_sec), 0.2)
    components = [
        {
            "source": f"anoisesrc=color=pink:amplitude=0.0045:sample_rate=48000:duration={duration:.3f}",
            "filter": "highpass=f=90,lowpass=f=3600,volume=0.55",
        }
    ]
    recipes = {
        "commute-room": [
            ("sine=frequency=155:sample_rate=48000:duration=0.080", "volume=0.030,adelay=420"),
            ("sine=frequency=210:sample_rate=48000:duration=0.055", "volume=0.022,adelay=1580"),
        ],
        "kitchen-prep": [
            ("sine=frequency=920:sample_rate=48000:duration=0.030", "volume=0.038,adelay=520"),
            ("sine=frequency=1160:sample_rate=48000:duration=0.026", "volume=0.030,adelay=1080"),
            ("anoisesrc=color=white:amplitude=0.014:sample_rate=48000:duration=0.090", "highpass=f=1300,lowpass=f=7600,afade=t=out:st=0.045:d=0.045,adelay=1640"),
        ],
        "desk-notes": [
            ("sine=frequency=1320:sample_rate=48000:duration=0.024", "volume=0.026,adelay=620"),
            ("sine=frequency=980:sample_rate=48000:duration=0.020", "volume=0.020,adelay=1240"),
            ("anoisesrc=color=white:amplitude=0.010:sample_rate=48000:duration=0.160", "highpass=f=1800,lowpass=f=7200,afade=t=out:st=0.100:d=0.060,adelay=1760"),
        ],
        "mat-rustle": [
            ("anoisesrc=color=brown:amplitude=0.016:sample_rate=48000:duration=0.240", "lowpass=f=2400,afade=t=in:st=0:d=0.040,afade=t=out:st=0.160:d=0.080,adelay=430"),
            ("anoisesrc=color=pink:amplitude=0.012:sample_rate=48000:duration=0.180", "lowpass=f=2100,afade=t=out:st=0.110:d=0.070,adelay=1560"),
        ],
        "lamp-switch": [
            ("sine=frequency=1700:sample_rate=48000:duration=0.018", "volume=0.032,adelay=520"),
            ("sine=frequency=620:sample_rate=48000:duration=0.040", "volume=0.018,adelay=570"),
        ],
        "soft-room": [
            ("sine=frequency=540:sample_rate=48000:duration=0.030", "volume=0.014,adelay=900"),
        ],
    }
    for source, audio_filter in recipes.get(pattern, recipes["soft-room"]):
        components.append({"source": source, "filter": audio_filter})
    return components


def _build_procedural_foley_args(output_path: Path, duration_sec: float, pattern: str) -> list[str]:
    components = _foley_components(pattern, duration_sec)
    input_args: list[str] = []
    filter_parts: list[str] = []
    labels: list[str] = []
    for index, component in enumerate(components):
        input_args.extend(["-f", "lavfi", "-i", component["source"]])
        label = f"a{index}"
        labels.append(f"[{label}]")
        filter_parts.append(f"[{index}:a]{component['filter']}[{label}]")
    fade_start = max(float(duration_sec) - 0.2, 0.0)
    filter_parts.append(
        "".join(labels)
        + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
        + f"atrim=0:{float(duration_sec):.3f},"
        + "afade=t=in:st=0:d=0.030,"
        + f"afade=t=out:st={fade_start:.3f}:d=0.200,"
        + "aformat=sample_rates=48000:channel_layouts=mono[aout]"
    )
    return [
        "-y",
        *input_args,
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[aout]",
        "-ar",
        "48000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]


def create_procedural_foley(
    *,
    ffmpeg_path: str,
    output_path: Path,
    duration_sec: float,
    pattern: str,
    log_lines: list[str],
) -> None:
    """Create a subtle local foley WAV without using stock samples or paid APIs."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_lines.append(f"procedural_foley=generate pattern={pattern} output={output_path}")
    run_ffmpeg(
        ffmpeg_path,
        _build_procedural_foley_args(output_path, duration_sec, pattern),
        log_lines,
    )


def procedural_foley_metadata(*, pattern: str, output_path: Path, project_root: Path) -> dict:
    rel_path = _relative_to_project(output_path, project_root)
    label = procedural_foley_label(pattern)
    return {
        "provider": "local-sfx",
        "kind": "sfx",
        "outputPath": rel_path,
        "sourceOrigin": "generated-procedural-local",
        "sourcePath": rel_path,
        "sourceProvider": "video-studio-procedural-foley",
        "sourceLabel": label,
        "title": label,
        "creator": PROCEDURAL_FOLEY_CREATOR,
        "sourceUrl": f"local://video-studio/procedural-foley/{pattern}",
        "sourceLicense": PROCEDURAL_FOLEY_LICENSE,
        "licenseUrl": PROCEDURAL_FOLEY_LICENSE_URL,
        "attribution": "Generated locally by Video Studio procedural foley; no external audio samples.",
        "attributionRequired": False,
    }


def _relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
