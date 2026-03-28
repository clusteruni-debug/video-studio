"""Audio transcription — Whisper-based with CLI fallback.

Uses the ``openai-whisper`` package when installed, otherwise falls back to
the ``whisper`` CLI binary.  Returns structured segments with timestamps.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


def transcribe_audio(
    audio_path: Path,
    language: str = "auto",
    model: str = "base",
) -> dict:
    """Transcribe an audio file.

    Returns::

        {
            "text": "full transcript",
            "segments": [{"start": 0.0, "end": 2.5, "text": "..."}],
            "language": "en",
        }
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Strategy 1: openai-whisper Python package
    try:
        return _transcribe_python(audio_path, language, model)
    except ImportError:
        pass

    # Strategy 2: whisper CLI
    try:
        return _transcribe_cli(audio_path, language, model)
    except FileNotFoundError:
        raise RuntimeError(
            "Whisper is not installed. Run: pip install openai-whisper  "
            "OR install the whisper CLI and ensure it is on PATH."
        )


def _transcribe_python(audio_path: Path, language: str, model: str) -> dict:
    """Use the ``whisper`` Python package directly."""
    import whisper  # type: ignore[import-untyped]

    model_obj = whisper.load_model(model)
    lang_arg = language if language != "auto" else None
    result = model_obj.transcribe(str(audio_path), language=lang_arg)
    return {
        "text": result["text"],
        "segments": [
            {"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in result.get("segments", [])
        ],
        "language": result.get("language", "unknown"),
    }


def _transcribe_cli(audio_path: Path, language: str, model: str) -> dict:
    """Fall back to the ``whisper`` command-line tool."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "whisper",
            str(audio_path),
            "--model", model,
            "--output_format", "json",
            "--output_dir", tmpdir,
        ]
        if language != "auto":
            cmd.extend(["--language", language])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"whisper CLI failed: {result.stderr[:500]}")

        json_files = list(Path(tmpdir).glob("*.json"))
        if not json_files:
            raise RuntimeError("whisper CLI produced no output")

        data = json.loads(json_files[0].read_text(encoding="utf-8"))
        return {
            "text": data.get("text", ""),
            "segments": [
                {"start": s["start"], "end": s["end"], "text": s["text"]}
                for s in data.get("segments", [])
            ],
            "language": data.get("language", "unknown"),
        }
