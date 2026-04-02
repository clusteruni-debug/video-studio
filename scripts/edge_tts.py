"""Edge TTS adapter script — free cross-platform text-to-speech via Microsoft Edge.

Usage:
    python scripts/edge_tts.py --prompt-path scene.prompt.txt --output-path scene.wav

Requires: pip install edge-tts
"""

from __future__ import annotations

# Prevent this script's directory from shadowing the real edge_tts package
import sys as _sys
_script_dir = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
if _script_dir in _sys.path:
    _sys.path.remove(_script_dir)

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

DEFAULT_VOICE_KO = "ko-KR-SunHiNeural"
DEFAULT_VOICE_EN = "en-US-AriaNeural"
DEFAULT_RATE = "+35%"
DEFAULT_VOLUME = "+0%"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate speech audio from a text prompt file using Edge TTS."
    )
    parser.add_argument("--prompt-path", required=True, help="Text file containing the speech text")
    parser.add_argument("--output-path", required=True, help="Audio file path to write (.mp3 or .wav)")
    parser.add_argument(
        "--voice",
        default=os.environ.get("VIDEO_STUDIO_EDGE_TTS_VOICE", ""),
        help="Edge TTS voice name (e.g. ko-KR-SunHiNeural)",
    )
    parser.add_argument(
        "--rate",
        default=os.environ.get("VIDEO_STUDIO_EDGE_TTS_RATE", DEFAULT_RATE),
        help="Speech rate adjustment (e.g. +10%%, -5%%)",
    )
    parser.add_argument(
        "--volume",
        default=os.environ.get("VIDEO_STUDIO_EDGE_TTS_VOLUME", DEFAULT_VOLUME),
        help="Volume adjustment (e.g. +20%%, -10%%)",
    )
    return parser


def _detect_language(text: str) -> str:
    """Simple heuristic: if text contains Korean characters, use Korean voice."""
    for char in text:
        if "\uac00" <= char <= "\ud7a3" or "\u3131" <= char <= "\u3163":
            return "ko"
    return "en"


def _select_voice(explicit_voice: str, text: str) -> str:
    if explicit_voice:
        return explicit_voice
    lang = _detect_language(text)
    return DEFAULT_VOICE_KO if lang == "ko" else DEFAULT_VOICE_EN


def _read_prompt(prompt_path: Path) -> str:
    """Read prompt file and extract just the speech text (skip metadata lines)."""
    raw_lines = prompt_path.read_text(encoding="utf-8").splitlines()
    filtered = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("Duration:", "Route:", "Output:", "Seed:")):
            continue
        filtered.append(stripped)
    text = " ".join(filtered).strip()
    if not text:
        raise ValueError(f"Prompt file is empty after filtering: {prompt_path}")
    return text


async def _synthesize(text: str, voice: str, rate: str, volume: str, output_path: Path) -> None:
    try:
        import edge_tts
    except ImportError:
        print("edge-tts is not installed. Run: pip install edge-tts", file=sys.stderr)
        raise SystemExit(1)

    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    await communicate.save(str(output_path))


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    prompt_path = Path(args.prompt_path).resolve()
    output_path = Path(args.output_path).resolve()

    if not prompt_path.exists():
        print(f"Prompt path does not exist: {prompt_path}", file=sys.stderr)
        return 2

    try:
        text = _read_prompt(prompt_path)
        voice = _select_voice(args.voice, text)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        asyncio.run(_synthesize(text, voice, args.rate, args.volume, output_path))

        if not output_path.exists():
            print("Edge TTS completed but output file was not created.", file=sys.stderr)
            return 1

        print(
            json.dumps(
                {
                    "ok": True,
                    "promptPath": str(prompt_path),
                    "outputPath": str(output_path),
                    "voice": voice,
                    "rate": args.rate,
                    "volume": args.volume,
                    "bytes": output_path.stat().st_size,
                },
                ensure_ascii=False,
            )
        )
        return 0

    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
