"""OpenAI Sora 2 video adapter script.

Usage:
    python scripts/sora2_video.py --prompt-path scene.prompt.txt --output-path scene.mp4

Requires: OPENAI_API_KEY environment variable.

Note: This adapter uses the OpenAI responses API with sora model.
The actual API surface may change — this is based on available documentation.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path
from urllib import error, request

OPENAI_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "sora"
DEFAULT_TIMEOUT_SEC = 300.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_DURATION_SEC = 5
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a video via Sora 2 API.")
    parser.add_argument("--prompt-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--duration-sec", type=int, default=DEFAULT_DURATION_SEC)
    parser.add_argument("--timeout-sec", type=float, default=DEFAULT_TIMEOUT_SEC)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--resolution", default="1080p", help="Output resolution")
    return parser


def _read_prompt(prompt_path: Path) -> str:
    raw_lines = prompt_path.read_text(encoding="utf-8").splitlines()
    filtered = [line.strip() for line in raw_lines
                if line.strip() and not line.strip().startswith(("Duration:", "Route:", "Output:", "Seed:"))]
    return ". ".join(filtered).strip()


def _generate_video(prompt: str, api_key: str, duration: int,
                     resolution: str, timeout_sec: float) -> bytes:
    payload = json.dumps({
        "model": DEFAULT_MODEL,
        "input": [{"role": "user", "content": prompt}],
        "tools": [{
            "type": "video_generation",
            "duration": duration,
            "resolution": resolution,
        }],
    }).encode("utf-8")

    req = request.Request(
        OPENAI_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    with request.urlopen(req, timeout=max(1.0, timeout_sec)) as response:
        body = json.loads(response.read().decode("utf-8"))

    # Extract video URL from response
    for item in body.get("output", []):
        if item.get("type") == "video_generation_call":
            video_url = item.get("video_url", "")
            if video_url:
                video_req = request.Request(video_url)
                with request.urlopen(video_req, timeout=max(1.0, timeout_sec)) as vr:
                    return vr.read()

    raise RuntimeError("No video URL found in Sora 2 response")


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
        prompt = _read_prompt(prompt_path)
        if not prompt:
            print("Empty prompt", file=sys.stderr)
            return 2
        output_path.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(1, args.max_attempts + 1):
            try:
                video_bytes = _generate_video(
                    prompt, api_key, args.duration_sec, args.resolution, args.timeout_sec,
                )
                output_path.write_bytes(video_bytes)
                print(json.dumps({
                    "ok": True, "outputPath": str(output_path),
                    "model": DEFAULT_MODEL, "bytes": len(video_bytes),
                    "attempt": attempt,
                }, ensure_ascii=False))
                return 0
            except error.HTTPError as exc:
                if exc.code in RETRYABLE_HTTP_STATUS and attempt < args.max_attempts:
                    time.sleep(2 ** attempt)
                    continue
                print(f"Sora 2 HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
                return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
