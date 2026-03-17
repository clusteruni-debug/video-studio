"""Google Veo 3 video adapter script.

Usage:
    python scripts/veo3_video.py --prompt-path scene.prompt.txt --output-path scene.mp4

Requires: GOOGLE_API_KEY environment variable.

Note: Uses the Gemini API video generation endpoint.
API surface may evolve — this follows available documentation.
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

VEO3_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/veo-002:predictLongRunning"
DEFAULT_TIMEOUT_SEC = 300.0
DEFAULT_MAX_ATTEMPTS = 3
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a video via Google Veo 3 API.")
    parser.add_argument("--prompt-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--timeout-sec", type=float, default=DEFAULT_TIMEOUT_SEC)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--duration-sec", type=int, default=5)
    parser.add_argument("--aspect-ratio", default="9:16")
    return parser


def _read_prompt(prompt_path: Path) -> str:
    raw_lines = prompt_path.read_text(encoding="utf-8").splitlines()
    filtered = [line.strip() for line in raw_lines
                if line.strip() and not line.strip().startswith(("Duration:", "Route:", "Output:", "Seed:"))]
    return ". ".join(filtered).strip()


def _generate_video(prompt: str, api_key: str, duration_sec: int,
                     aspect_ratio: str, timeout_sec: float) -> bytes:
    url = f"{VEO3_API_URL}?key={api_key}"
    payload = json.dumps({
        "instances": [{"prompt": prompt}],
        "parameters": {
            "aspectRatio": aspect_ratio,
            "sampleCount": 1,
            "durationSeconds": duration_sec,
        },
    }).encode("utf-8")

    req = request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=max(1.0, timeout_sec)) as response:
        body = json.loads(response.read().decode("utf-8"))

    # Handle long-running operation polling
    operation_name = body.get("name", "")
    if operation_name:
        poll_url = f"https://generativelanguage.googleapis.com/v1beta/{operation_name}?key={api_key}"
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            poll_req = request.Request(poll_url)
            with request.urlopen(poll_req, timeout=30) as poll_resp:
                poll_body = json.loads(poll_resp.read().decode("utf-8"))
            if poll_body.get("done"):
                predictions = poll_body.get("response", {}).get("predictions", [])
                if predictions:
                    b64 = predictions[0].get("bytesBase64Encoded", "")
                    if b64:
                        return base64.b64decode(b64)
                raise RuntimeError("Veo 3 completed but no video data found")
            time.sleep(5)
        raise RuntimeError("Veo 3 generation timed out")

    predictions = body.get("predictions", [])
    if predictions:
        b64 = predictions[0].get("bytesBase64Encoded", "")
        if b64:
            return base64.b64decode(b64)

    raise RuntimeError("No video data in Veo 3 response")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        print("GOOGLE_API_KEY environment variable is not set.", file=sys.stderr)
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
                    prompt, api_key, args.duration_sec, args.aspect_ratio, args.timeout_sec,
                )
                output_path.write_bytes(video_bytes)
                print(json.dumps({
                    "ok": True, "outputPath": str(output_path),
                    "model": "veo-3", "bytes": len(video_bytes),
                    "attempt": attempt,
                }, ensure_ascii=False))
                return 0
            except error.HTTPError as exc:
                if exc.code in RETRYABLE_HTTP_STATUS and attempt < args.max_attempts:
                    time.sleep(2 ** attempt)
                    continue
                print(f"Veo 3 HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
                return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
