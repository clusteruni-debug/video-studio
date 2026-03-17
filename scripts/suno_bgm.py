"""Suno AI BGM adapter script — AI-generated background music.

Usage:
    python scripts/suno_bgm.py --prompt-path scene.prompt.txt --output-path bgm.mp3

Requires: SUNO_API_KEY environment variable.

Note: Suno API access may require separate subscription.
This adapter follows the unofficial API pattern. [UNCERTAIN]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib import error, request

SUNO_API_URL = "https://api.suno.ai/v1/generation"
DEFAULT_TIMEOUT_SEC = 180.0
DEFAULT_MAX_ATTEMPTS = 3
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate background music via Suno AI.")
    parser.add_argument("--prompt-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--duration-sec", type=int, default=30)
    parser.add_argument("--timeout-sec", type=float, default=DEFAULT_TIMEOUT_SEC)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    return parser


def _read_prompt(prompt_path: Path) -> str:
    raw_lines = prompt_path.read_text(encoding="utf-8").splitlines()
    filtered = [line.strip() for line in raw_lines
                if line.strip() and not line.strip().startswith(("Duration:", "Route:", "Output:", "Seed:"))]
    return " ".join(filtered).strip()


def _generate_music(prompt: str, duration_sec: int, api_key: str, timeout_sec: float) -> bytes:
    payload = json.dumps({
        "prompt": f"Instrumental background music: {prompt}",
        "duration": duration_sec,
        "make_instrumental": True,
    }).encode("utf-8")

    req = request.Request(
        SUNO_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    with request.urlopen(req, timeout=max(1.0, timeout_sec)) as response:
        body = json.loads(response.read().decode("utf-8"))

    audio_url = body.get("audio_url") or body.get("data", [{}])[0].get("audio_url", "")
    if not audio_url:
        raise RuntimeError("No audio URL in Suno response")

    audio_req = request.Request(audio_url)
    with request.urlopen(audio_req, timeout=max(1.0, timeout_sec)) as audio_resp:
        return audio_resp.read()


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    api_key = os.environ.get("SUNO_API_KEY", "").strip()
    if not api_key:
        print("SUNO_API_KEY environment variable is not set.", file=sys.stderr)
        return 2

    prompt_path = Path(args.prompt_path).resolve()
    output_path = Path(args.output_path).resolve()

    if not prompt_path.exists():
        print(f"Prompt path does not exist: {prompt_path}", file=sys.stderr)
        return 2

    try:
        prompt = _read_prompt(prompt_path)
        if not prompt:
            prompt = "calm ambient background music"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(1, args.max_attempts + 1):
            try:
                audio_bytes = _generate_music(prompt, args.duration_sec, api_key, args.timeout_sec)
                output_path.write_bytes(audio_bytes)
                print(json.dumps({
                    "ok": True, "outputPath": str(output_path),
                    "model": "suno-v4", "bytes": len(audio_bytes),
                    "attempt": attempt,
                }, ensure_ascii=False))
                return 0
            except error.HTTPError as exc:
                if exc.code in RETRYABLE_HTTP_STATUS and attempt < args.max_attempts:
                    time.sleep(2 ** attempt)
                    continue
                print(f"Suno HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
                return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
