"""Word-level alignment using faster-whisper for karaoke subtitle generation.

Pipeline: Edge TTS WAV → faster-whisper word_timestamps → word timing list
Spec reference: docs/RENDERING-SPEC.md §3.1
"""

from __future__ import annotations

import functools
import os
from pathlib import Path


@functools.lru_cache(maxsize=4)
def _get_whisper_model(model_size: str, device: str, compute_type: str):
    """Cached WhisperModel factory — avoids re-instantiation per request."""
    from faster_whisper import WhisperModel
    return WhisperModel(model_size, device=device, compute_type=compute_type)


def align_tts(wav_path: str, model_size: str = "base", language: str = "ko") -> list[dict]:
    """Extract per-word timestamps from a WAV file using faster-whisper.

    Parameters
    ----------
    wav_path:
        Path to the WAV audio file (typically from Edge TTS).
    model_size:
        Whisper model size. Default "base" for speed on CPU.
    language:
        Language code. "ko" for Korean, "en" for English.

    Returns
    -------
    List of ``{"word": str, "start": float, "end": float}`` dicts.
    """
    path = Path(wav_path)
    if not path.exists():
        raise FileNotFoundError(f"WAV file not found: {wav_path}")

    try:
        from faster_whisper import WhisperModel  # noqa: F401 — validate import
    except ImportError:
        raise ImportError(
            "faster-whisper is required for word alignment. "
            "Install with: pip install faster-whisper>=1.0"
        )

    # Use CPU by default; GPU if available
    device = "cuda" if _cuda_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    model = _get_whisper_model(model_size, device, compute_type)

    segments, _info = model.transcribe(
        str(path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
    )

    words: list[dict] = []
    for segment in segments:
        if not segment.words:
            continue
        for w in segment.words:
            words.append({
                "word": w.word.strip(),
                "start": round(w.start, 3),
                "end": round(w.end, 3),
            })

    # Filter out empty words
    words = [w for w in words if w["word"]]

    return words


def align_tts_fallback(text: str, duration_sec: float) -> list[dict]:
    """Estimate per-word timing proportionally by character count.

    Fallback when faster-whisper is not available or fails.
    Korean words have roughly uniform duration per character.
    """
    if duration_sec <= 0 or not text.strip():
        return []

    tokens = text.strip().split()
    total_chars = sum(len(w) for w in tokens)
    if total_chars == 0:
        return []

    result = []
    cursor = 0.0
    for word in tokens:
        word_dur = (len(word) / total_chars) * duration_sec
        result.append({
            "word": word,
            "start": round(cursor, 3),
            "end": round(cursor + word_dur, 3),
        })
        cursor += word_dur

    return result


def _cuda_available() -> bool:
    """Check if CUDA is available without importing torch at module level."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False
