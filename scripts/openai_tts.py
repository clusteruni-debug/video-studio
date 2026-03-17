"""OpenAI TTS adapter script.

Usage:
    python scripts/openai_tts.py --prompt-path scene.prompt.txt --output-path scene.mp3

Requires: OPENAI_API_KEY environment variable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib import error, request

OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"
DEFAULT_MODEL = "tts-1"
DEFAULT_VOICE = "alloy"
DEFAULT_TIMEOUT_SEC = 60.0
DEFAULT_MAX_ATTEMPTS = 3
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate speech via OpenAI TTS API.")
    parser.add_argument("--prompt-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--voice", default=os.environ.get("VIDEO_STUDIO_OPENAI_TTS_VOICE", DEFAULT_VOICE))
    parser.add_argument("--timeout-sec", type=float, default=DEFAULT_TIMEOUT_SEC)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    return parser


def _read_prompt(prompt_path: Path) -> str:
    raw_lines = prompt_path.read_text(encoding="utf-8").splitlines()
    filtered = [line.strip() for line in raw_lines
                if line.strip() and not line.strip().startswith(("Duration:", "Route:", "Output:", "Seed:"))]
    return " ".join(filtered).strip()


def _synthesize(text: str, model: str, voice: str, api_key: str, timeout_sec: float) -> bytes:
    payload = json.dumps({
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": "mp3",
    }).encode("utf-8")

    req = request.Request(
        OPENAI_TTS_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with request.urlopen(req, timeout=max(1.0, timeout_sec)) as response:
        return response.read()


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("OPENAI_API_KEY environment variable is not set.", file=sys.stderr)
        return 2

    prompt_path = Path(args.prompt_path).resolve()
    output_path = Path(args.output_path).resolve()

    if not prompt_path.exists():
        print(f"Prompt path does not exist: {prompt_path}", file=sys.stderr)
        return 2

    try:
        text = _read_prompt(prompt_path)
        if not text:
            print("Empty prompt", file=sys.stderr)
            return 2
        output_path.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(1, args.max_attempts + 1):
            try:
                audio_bytes = _synthesize(text, args.model, args.voice, api_key, args.timeout_sec)
                output_path.write_bytes(audio_bytes)
                print(json.dumps({
                    "ok": True, "outputPath": str(output_path),
                    "model": args.model, "voice": args.voice,
                    "bytes": len(audio_bytes), "attempt": attempt,
                }, ensure_ascii=False))
                return 0
            except error.HTTPError as exc:
                if exc.code in RETRYABLE_HTTP_STATUS and attempt < args.max_attempts:
                    time.sleep(2 ** attempt)
                    continue
                print(f"OpenAI TTS HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
                return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
