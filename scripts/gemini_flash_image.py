"""Gemini 2.5 Flash image generation adapter script.

Free tier: 500 images/day via Gemini 2.5 Flash native image generation.
Uses the same GEMINI_API_KEY as Imagen 4 but through the generateContent endpoint.

Usage:
    python scripts/gemini_flash_image.py --prompt-path scene.prompt.txt --output-path scene.png

Requires: GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable.
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

MODEL = "gemini-2.5-flash-image"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
DEFAULT_TIMEOUT_SEC = 120.0
DEFAULT_MAX_ATTEMPTS = 3
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate an image via Gemini 2.5 Flash.")
    parser.add_argument("--prompt-path", required=True, help="Text file containing the prompt")
    parser.add_argument("--output-path", required=True, help="Image file path to write")
    parser.add_argument("--timeout-sec", type=float, default=DEFAULT_TIMEOUT_SEC)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    return parser


def _read_prompt(prompt_path: Path) -> str:
    raw_lines = prompt_path.read_text(encoding="utf-8").splitlines()
    filtered = [line.strip() for line in raw_lines
                if line.strip() and not line.strip().startswith(("Duration:", "Route:", "Output:", "Seed:"))]
    return " ".join(filtered).strip()


def _request_image(prompt: str, api_key: str, timeout_sec: float) -> bytes:
    url = f"{API_URL}?key={api_key}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["image", "text"]},
    }).encode("utf-8")

    req = request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=max(1.0, timeout_sec)) as response:
        body = json.loads(response.read().decode("utf-8"))

    candidates = body.get("candidates", [])
    if not candidates:
        raise ValueError("No candidates in response")

    parts = candidates[0].get("content", {}).get("parts", [])
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])

    raise ValueError("No inline image data in response parts")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    api_key = (
        os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
    )
    if not api_key:
        print("GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable is not set.", file=sys.stderr)
        return 2

    prompt_path = Path(args.prompt_path).resolve()
    output_path = Path(args.output_path).resolve()

    if not prompt_path.exists():
        print(f"Prompt path does not exist: {prompt_path}", file=sys.stderr)
        return 2

    try:
        prompt = _read_prompt(prompt_path)
        if not prompt:
            print("Empty prompt after filtering", file=sys.stderr)
            return 2
        output_path.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(1, args.max_attempts + 1):
            try:
                image_bytes = _request_image(prompt, api_key, args.timeout_sec)
                output_path.write_bytes(image_bytes)
                print(json.dumps({
                    "ok": True, "promptPath": str(prompt_path),
                    "outputPath": str(output_path), "model": MODEL,
                    "bytes": len(image_bytes), "attempt": attempt,
                }, ensure_ascii=False))
                return 0
            except error.HTTPError as exc:
                if exc.code in RETRYABLE_HTTP_STATUS and attempt < args.max_attempts:
                    time.sleep(2 ** attempt)
                    continue
                print(f"Gemini Flash HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
                return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
