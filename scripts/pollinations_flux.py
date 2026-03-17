from __future__ import annotations

import argparse
import email.utils
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request

UNIFIED_ENDPOINT = "https://gen.pollinations.ai/image/"
LEGACY_ENDPOINT = "https://image.pollinations.ai/prompt/"
DEFAULT_MODEL = "flux"
DEFAULT_TIMEOUT_SEC = 120.0
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_INITIAL_BACKOFF_SEC = 8.0
DEFAULT_MAX_BACKOFF_SEC = 45.0
DEFAULT_BACKOFF_JITTER_SEC = 4.0
DEFAULT_MIN_REQUEST_GAP_SEC = 0.0
RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch a FLUX image from Pollinations and save it to the requested output path."
    )
    parser.add_argument("--prompt-path", required=True, help="Text file containing the prompt payload")
    parser.add_argument("--output-path", required=True, help="Image file path to write")
    parser.add_argument("--width", type=int, default=1024, help="Requested output width")
    parser.add_argument("--height", type=int, default=1024, help="Requested output height")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Pollinations image model name")
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=DEFAULT_TIMEOUT_SEC,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=_env_int("VIDEO_STUDIO_POLLINATIONS_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS),
        help="Total request attempts before failing",
    )
    parser.add_argument(
        "--initial-backoff-sec",
        type=float,
        default=_env_float("VIDEO_STUDIO_POLLINATIONS_INITIAL_BACKOFF_SEC", DEFAULT_INITIAL_BACKOFF_SEC),
        help="Initial backoff applied to retryable failures",
    )
    parser.add_argument(
        "--max-backoff-sec",
        type=float,
        default=_env_float("VIDEO_STUDIO_POLLINATIONS_MAX_BACKOFF_SEC", DEFAULT_MAX_BACKOFF_SEC),
        help="Upper bound for retry backoff seconds",
    )
    parser.add_argument(
        "--backoff-jitter-sec",
        type=float,
        default=_env_float("VIDEO_STUDIO_POLLINATIONS_BACKOFF_JITTER_SEC", DEFAULT_BACKOFF_JITTER_SEC),
        help="Random extra delay added to exponential backoff to reduce synchronized retries",
    )
    parser.add_argument(
        "--min-request-gap-sec",
        type=float,
        default=_env_float("VIDEO_STUDIO_POLLINATIONS_MIN_REQUEST_GAP_SEC", DEFAULT_MIN_REQUEST_GAP_SEC),
        help="Minimum delay between wrapper invocations to avoid anonymous queue overlap",
    )
    parser.add_argument(
        "--throttle-state-path",
        default=os.environ.get(
            "VIDEO_STUDIO_POLLINATIONS_STATE_PATH",
            str(Path("storage") / "cache" / "pollinations-rate-limit.json"),
        ),
        help="State file used to track the previous Pollinations invocation time",
    )
    parser.add_argument(
        "--endpoint-mode",
        default=_env_str("VIDEO_STUDIO_POLLINATIONS_ENDPOINT_MODE", "auto"),
        help="Endpoint mode: auto, unified, or legacy",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("VIDEO_STUDIO_POLLINATIONS_API_KEY", ""),
        help="Optional Pollinations API key; prefer a secret backend key when available",
    )
    parser.add_argument("--seed", type=int, help="Optional deterministic seed")
    return parser


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return raw


def _normalized_prompt(prompt_path: Path) -> str:
    raw_lines = prompt_path.read_text(encoding="utf-8").splitlines()
    filtered_lines = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("Duration:", "Route:", "Output:", "Seed:")):
            continue
        filtered_lines.append(stripped)

    prompt = ". ".join(filtered_lines).strip()
    if not prompt:
        raise ValueError(f"Prompt file is empty after normalization: {prompt_path}")
    return prompt


def _normalize_endpoint_mode(value: str) -> str:
    candidate = (value or "auto").strip().lower()
    if candidate in {"auto", "unified", "legacy"}:
        return candidate
    return "auto"


def _endpoint_candidates(mode: str, api_key: str | None) -> list[tuple[str, str]]:
    normalized = _normalize_endpoint_mode(mode)
    if normalized == "unified":
        return [("unified", UNIFIED_ENDPOINT)]
    if normalized == "legacy":
        return [("legacy", LEGACY_ENDPOINT)]
    if api_key:
        return [
            ("unified", UNIFIED_ENDPOINT),
            ("legacy", LEGACY_ENDPOINT),
        ]
    return [("legacy", LEGACY_ENDPOINT)]


def _request_url(
    base_url: str,
    prompt: str,
    width: int,
    height: int,
    model: str,
    seed: int | None,
) -> str:
    encoded_prompt = parse.quote(prompt, safe="")
    query = {
        "width": str(width),
        "height": str(height),
        "model": model,
    }
    if seed is not None:
        query["seed"] = str(seed)
    return f"{base_url}{encoded_prompt}?{parse.urlencode(query)}"


def _retry_after_seconds(headers) -> float | None:
    if not headers:
        return None

    raw_value = headers.get("Retry-After")
    if not raw_value:
        return None

    stripped = raw_value.strip()
    if not stripped:
        return None

    try:
        return max(0.0, float(stripped))
    except ValueError:
        pass

    try:
        retry_at = email.utils.parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)

    return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())


def _backoff_seconds(
    attempt_index: int,
    initial_backoff_sec: float,
    max_backoff_sec: float,
    jitter_sec: float,
    retry_after_sec: float | None = None,
) -> float:
    if retry_after_sec is not None:
        return max(0.0, retry_after_sec)

    exponent = max(0, attempt_index - 1)
    delay = max(0.0, initial_backoff_sec) * (2 ** exponent)
    return min(max(0.0, max_backoff_sec), delay) + random.uniform(0.0, max(0.0, jitter_sec))


def _request_once(url: str, timeout_sec: float, api_key: str | None) -> tuple[str, bytes]:
    headers = {
        "User-Agent": "video-studio-app/0.1",
        "Accept": "image/*",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = request.Request(
        url,
        headers=headers,
    )
    with request.urlopen(req, timeout=max(1.0, timeout_sec)) as response:
        return response.headers.get("Content-Type", ""), response.read()


def _looks_like_image(payload: bytes) -> bool:
    if payload.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")):
        return True
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return True
    return False


def _throttle_state_path(raw_path: str, cwd: Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return (cwd / candidate).resolve()


def _wait_for_min_gap(state_path: Path, min_gap_sec: float) -> None:
    if min_gap_sec <= 0:
        return

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except json.JSONDecodeError:
        return

    last_finished_at = float(state.get("lastInvocationFinishedAt", 0.0) or 0.0)
    if last_finished_at <= 0:
        return

    wait_sec = max(0.0, (last_finished_at + min_gap_sec) - time.time())
    if wait_sec <= 0:
        return

    print(
        f"Pollinations throttle active; waiting {wait_sec:.1f}s before the next request window.",
        file=sys.stderr,
    )
    time.sleep(wait_sec)


def _record_invocation_finished(state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"lastInvocationFinishedAt": time.time()}),
        encoding="utf-8",
    )


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    prompt_path = Path(args.prompt_path).resolve()
    output_path = Path(args.output_path).resolve()
    if not prompt_path.exists():
        print(f"Prompt path does not exist: {prompt_path}", file=sys.stderr)
        return 2

    try:
        prompt = _normalized_prompt(prompt_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        max_attempts = max(1, int(args.max_attempts))
        initial_backoff_sec = max(0.0, float(args.initial_backoff_sec))
        max_backoff_sec = max(initial_backoff_sec, float(args.max_backoff_sec))
        backoff_jitter_sec = max(0.0, float(args.backoff_jitter_sec))
        api_key = (args.api_key or "").strip() or None
        state_path = _throttle_state_path(args.throttle_state_path, Path.cwd())
        endpoint_candidates = [
            (
                endpoint_label,
                _request_url(
                    base_url=base_url,
                    prompt=prompt,
                    width=max(64, int(args.width)),
                    height=max(64, int(args.height)),
                    model=args.model.strip() or DEFAULT_MODEL,
                    seed=args.seed,
                ),
            )
            for endpoint_label, base_url in _endpoint_candidates(args.endpoint_mode, api_key=api_key)
        ]
        _wait_for_min_gap(state_path, max(0.0, float(args.min_request_gap_sec)))

        try:
            for attempt_index in range(1, max_attempts + 1):
                endpoint_label, url = endpoint_candidates[(attempt_index - 1) % len(endpoint_candidates)]
                try:
                    print(
                        f"Pollinations attempt {attempt_index}/{max_attempts} via {endpoint_label} endpoint.",
                        file=sys.stderr,
                    )
                    content_type, payload = _request_once(url, float(args.timeout_sec), api_key=api_key)
                    if not payload:
                        raise RuntimeError("Pollinations returned an empty response body")
                    if content_type and not content_type.lower().startswith("image/") and not _looks_like_image(payload):
                        preview = payload[:160].decode("utf-8", errors="replace").strip()
                        raise RuntimeError(
                            f"Pollinations returned unexpected content type: {content_type} ({preview})"
                        )

                    output_path.write_bytes(payload)
                    print(
                        json.dumps(
                            {
                                "ok": True,
                                "promptPath": str(prompt_path),
                                "outputPath": str(output_path),
                                "url": url,
                                "endpoint": endpoint_label,
                                "bytes": len(payload),
                                "contentType": content_type or None,
                                "attempt": attempt_index,
                                "maxAttempts": max_attempts,
                                "apiKeyConfigured": bool(api_key),
                            },
                            ensure_ascii=False,
                        )
                    )
                    return 0
                except error.HTTPError as exc:
                    detail = exc.read().decode("utf-8", errors="replace").strip()
                    message = f"Pollinations HTTP error {exc.code} via {endpoint_label}: {detail or exc.reason}"
                    if exc.code in RETRYABLE_HTTP_STATUS and attempt_index < max_attempts:
                        delay = _backoff_seconds(
                            attempt_index=attempt_index,
                            initial_backoff_sec=initial_backoff_sec,
                            max_backoff_sec=max_backoff_sec,
                            jitter_sec=backoff_jitter_sec,
                            retry_after_sec=_retry_after_seconds(exc.headers),
                        )
                        print(
                            f"{message} Retrying in {delay:.1f}s "
                            f"(attempt {attempt_index + 1}/{max_attempts}).",
                            file=sys.stderr,
                        )
                        time.sleep(delay)
                        continue

                    print(message, file=sys.stderr)
                    return 1
                except error.URLError as exc:
                    message = f"Pollinations request failed via {endpoint_label}: {exc.reason}"
                    if attempt_index < max_attempts:
                        delay = _backoff_seconds(
                            attempt_index=attempt_index,
                            initial_backoff_sec=initial_backoff_sec,
                            max_backoff_sec=max_backoff_sec,
                            jitter_sec=backoff_jitter_sec,
                        )
                        print(
                            f"{message} Retrying in {delay:.1f}s "
                            f"(attempt {attempt_index + 1}/{max_attempts}).",
                            file=sys.stderr,
                        )
                        time.sleep(delay)
                        continue

                    print(message, file=sys.stderr)
                    return 1
                except TimeoutError as exc:
                    message = f"Pollinations request timed out via {endpoint_label}: {exc}"
                    if attempt_index < max_attempts:
                        delay = _backoff_seconds(
                            attempt_index=attempt_index,
                            initial_backoff_sec=initial_backoff_sec,
                            max_backoff_sec=max_backoff_sec,
                            jitter_sec=backoff_jitter_sec,
                        )
                        print(
                            f"{message} Retrying in {delay:.1f}s "
                            f"(attempt {attempt_index + 1}/{max_attempts}).",
                            file=sys.stderr,
                        )
                        time.sleep(delay)
                        continue

                    print(message, file=sys.stderr)
                    return 1
                except RuntimeError as exc:
                    message = f"Pollinations response rejected via {endpoint_label}: {exc}"
                    if attempt_index < max_attempts:
                        delay = _backoff_seconds(
                            attempt_index=attempt_index,
                            initial_backoff_sec=initial_backoff_sec,
                            max_backoff_sec=max_backoff_sec,
                            jitter_sec=backoff_jitter_sec,
                        )
                        print(
                            f"{message} Retrying in {delay:.1f}s "
                            f"(attempt {attempt_index + 1}/{max_attempts}).",
                            file=sys.stderr,
                        )
                        time.sleep(delay)
                        continue

                    print(message, file=sys.stderr)
                    return 1
        finally:
            _record_invocation_finished(state_path)
    except Exception as exc:  # pragma: no cover - exercised through command adapter
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
