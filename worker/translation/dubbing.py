"""Dubbing pipeline — transcribe → translate → re-synthesize.

Combines the transcription, translation, and TTS modules into a complete
foreign-content → Korean dubbing workflow.
"""

from __future__ import annotations

from pathlib import Path

from worker.translation.transcribe import transcribe_audio
from worker.translation.translate import translate_segments
from worker.tts.providers import generate_tts


def dub_audio(
    source_audio: Path,
    target_lang: str = "ko",
    tts_provider: str = "edge",
    voice_gender: str = "female",
    output_dir: Path | None = None,
    whisper_model: str = "base",
    translation_style: str = "natural",
) -> dict:
    """Full dubbing pipeline.

    Returns::

        {
            "source_language": "en",
            "target_language": "ko",
            "segments": [
                {
                    "start": 0.0, "end": 2.5,
                    "original": "Hello world",
                    "translated": "안녕하세요 세계",
                    "audio_path": "path/to/segment_000.mp3",
                }
            ],
            "audio_files": ["path/to/segment_000.mp3", ...],
        }
    """
    source_audio = Path(source_audio)
    if output_dir is None:
        output_dir = source_audio.parent / "dubbing_output"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Transcribe
    transcript = transcribe_audio(source_audio, model=whisper_model)
    source_lang = transcript.get("language", "en")

    # Step 2: Translate
    translated = translate_segments(
        transcript["segments"],
        source_lang=source_lang,
        target_lang=target_lang,
        style=translation_style,
    )

    # Step 3: Generate TTS for each translated segment
    audio_files: list[str] = []
    partial = False
    for i, seg in enumerate(translated):
        out_path = output_dir / f"segment_{i:03d}.mp3"
        try:
            generate_tts(
                text=seg["translated"],
                lang=target_lang,
                gender=voice_gender,
                provider=tts_provider,
                output_path=out_path,
            )
            if out_path.exists():
                seg["audio_path"] = str(out_path)
                audio_files.append(str(out_path))
            else:
                seg["audio_path"] = None
                seg["error"] = "TTS produced no output"
                partial = True
        except Exception as e:
            seg["audio_path"] = None
            seg["error"] = str(e)
            partial = True

    return {
        "source_language": source_lang,
        "target_language": target_lang,
        "segments": translated,
        "audio_files": audio_files,
        "partial": partial,
    }
