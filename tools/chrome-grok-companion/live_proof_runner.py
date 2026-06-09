"""Live proof helper for the Video Studio AI Web Companion.

This tool does not click Generate, import results, call paid provider APIs, or
open Chrome download/save prompts. It only opens an operator-approved
autostart URL when requested and classifies the resulting extension event log.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GEMINI_BUILD_TAG = "20260607-gemini-image-handoff"
GROK_BUILD_TAG = "20260607-popup-state-fix"
BRIDGE_URL = "http://127.0.0.1:5161"


@dataclass(frozen=True)
class ProofTarget:
    provider: str
    autostart_url: str
    event_log: Path
    chrome_profile_dir: Path
    companion_extension_dir: Path
    remote_debugging_port: int


@dataclass(frozen=True)
class ProofResult:
    provider: str
    status: str
    event_log: str
    marker_seen: bool
    last_event: dict[str, Any] | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "eventLog": self.event_log,
            "markerSeen": self.marker_seen,
            "lastEvent": self.last_event,
            "detail": self.detail,
        }


def extension_dir(override: str = "") -> Path:
    if override:
        return Path(override).absolute()
    env_override = os.environ.get("VIDEO_STUDIO_COMPANION_EXTENSION_DIR", "")
    if env_override:
        return Path(env_override).absolute()
    raw = Path(__file__).parent.absolute()
    cwd_candidate = Path.cwd() / "tools" / "chrome-grok-companion"
    if (cwd_candidate / "manifest.json").exists():
        return cwd_candidate
    return raw


def project_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "tools" / "chrome-grok-companion" / "manifest.json").exists():
        return cwd
    return Path(__file__).resolve().parents[2]


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def event_has_marker(event: dict[str, Any], marker: str) -> bool:
    return event.get("build") == marker or marker in str(event.get("detail") or "")


def _is_control_success(event: dict[str, Any]) -> bool:
    event_type = str(event.get("eventType") or "")
    status = str(event.get("status") or "")
    if not any(token in event_type for token in ("fill", "generate", "prompt-fill", "autostart")):
        return False
    return status in {"filled", "clicked", "ready"}


def classify_gemini_events(events: list[dict[str, Any]], event_log: Path) -> ProofResult:
    marker_seen = any(event_has_marker(event, GEMINI_BUILD_TAG) for event in events)
    last_event = events[-1] if events else None
    if not events:
        return ProofResult(
            provider="gemini-web-image",
            status="blocked",
            event_log=str(event_log),
            marker_seen=False,
            last_event=None,
            detail="No Gemini extension event file/events were found.",
        )
    fill_events = [event for event in events if event.get("eventType") == "gemini-prompt-fill"]
    filled = [event for event in fill_events if event.get("status") == "filled"]
    failed = [
        event
        for event in events
        if str(event.get("eventType") or "").startswith("gemini-") and event.get("status") == "failed"
    ]
    if filled and marker_seen:
        proof_mode = str(filled[-1].get("proofMode") or "")
        source = str(filled[-1].get("source") or filled[-1].get("detail") or "")
        if proof_mode == "browser-control" or "browser-control" in source:
            detail = "Gemini prompt fill event and expected build marker were recorded through browser-control proof."
        else:
            detail = "Gemini prompt fill event and expected build marker were recorded."
        return ProofResult(
            provider="gemini-web-image",
            status="pass",
            event_log=str(event_log),
            marker_seen=True,
            last_event=filled[-1],
            detail=detail,
        )
    if failed:
        return ProofResult(
            provider="gemini-web-image",
            status="fail",
            event_log=str(event_log),
            marker_seen=marker_seen,
            last_event=failed[-1],
            detail="Gemini companion reported a failed content/command/target/fill step.",
        )
    return ProofResult(
        provider="gemini-web-image",
        status="blocked",
        event_log=str(event_log),
        marker_seen=marker_seen,
        last_event=last_event,
        detail="Gemini companion has not recorded gemini-prompt-fill with the expected build marker yet.",
    )


def classify_grok_events(events: list[dict[str, Any]], event_log: Path) -> ProofResult:
    marker_seen = any(event_has_marker(event, GROK_BUILD_TAG) for event in events)
    last_event = events[-1] if events else None
    if not events:
        return ProofResult(
            provider="grok-web-video",
            status="blocked",
            event_log=str(event_log),
            marker_seen=False,
            last_event=None,
            detail="No Grok extension event file/events were found.",
        )
    chat_successes = [
        event
        for event in events
        if "/c/" in str(event.get("currentUrl") or "") and _is_control_success(event)
    ]
    if chat_successes:
        return ProofResult(
            provider="grok-web-video",
            status="fail",
            event_log=str(event_log),
            marker_seen=marker_seen,
            last_event=chat_successes[-1],
            detail="Grok fill/generate succeeded on a general /c/* chat thread.",
        )
    non_imagine_successes = [
        event
        for event in events
        if _is_control_success(event)
        and str(event.get("currentUrl") or "")
        and "https://grok.com/imagine" not in str(event.get("currentUrl") or "")
    ]
    if non_imagine_successes:
        return ProofResult(
            provider="grok-web-video",
            status="fail",
            event_log=str(event_log),
            marker_seen=marker_seen,
            last_event=non_imagine_successes[-1],
            detail="Grok fill/generate succeeded outside the Imagine surface.",
        )
    if marker_seen:
        return ProofResult(
            provider="grok-web-video",
            status="pass",
            event_log=str(event_log),
            marker_seen=True,
            last_event=last_event,
            detail="Grok expected build marker was recorded and no /c/* or non-Imagine control success was found.",
        )
    return ProofResult(
        provider="grok-web-video",
        status="blocked",
        event_log=str(event_log),
        marker_seen=False,
        last_event=last_event,
        detail="Grok events exist, but the expected build marker is missing.",
    )


def classify_events(provider: str, event_log: Path) -> ProofResult:
    events = read_events(event_log)
    if provider == "gemini-web-image":
        return classify_gemini_events(events, event_log)
    if provider == "grok-web-video":
        return classify_grok_events(events, event_log)
    raise ValueError(f"unsupported provider: {provider}")


def default_chrome_path() -> str:
    candidates = [
        os.environ.get("VIDEO_STUDIO_CHROME_PATH", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        shutil.which("chrome.exe") or "",
        shutil.which("chrome") or "",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return ""


def gemini_autostart_url(bridge: str, episode_id: str, batch_id: str, cut_id: str) -> str:
    query = urllib.parse.urlencode({"operatorApproved": "true", "cutId": cut_id})
    command_url = f"{bridge}/api/episodes/{urllib.parse.quote(episode_id)}/browser-handoffs/gemini-web-image/{urllib.parse.quote(batch_id)}/extension-command?{query}"
    hash_params = urllib.parse.urlencode({
        "operatorApproved": "true",
        "videoStudioProvider": "gemini-web-image",
        "videoStudioAction": "fill-prompt",
        "videoStudioCommandUrl": command_url,
    })
    return f"https://gemini.google.com/app#{hash_params}"


def grok_autostart_url(bridge: str, project_id: str, scene_id: str) -> str:
    query = urllib.parse.urlencode({"operatorApproved": "true", "sceneId": scene_id})
    command_url = f"{bridge}/api/grok-handoff/{urllib.parse.quote(project_id)}/extension-command?{query}"
    hash_params = urllib.parse.urlencode({
        "operatorApproved": "true",
        "videoStudioGrokCommandUrl": command_url,
        "videoStudioAction": "fill-prompt",
    })
    return f"https://grok.com/imagine#{hash_params}"


def build_target(args: argparse.Namespace) -> ProofTarget:
    root = project_root()
    bridge = args.bridge.rstrip("/")
    profile_dir = Path(args.profile_dir or root / "storage" / "browser-profiles" / "video-studio-companion").resolve()
    companion_extension_dir = extension_dir(args.extension_dir)
    if args.provider == "gemini-web-image":
        if not args.episode_id:
            raise ValueError("--episode-id is required for Gemini proof.")
        batch_id = args.batch_id or "batch-001"
        cut_id = args.cut_id or "cut_001"
        return ProofTarget(
            provider=args.provider,
            autostart_url=args.autostart_url or gemini_autostart_url(bridge, args.episode_id, batch_id, cut_id),
            event_log=Path(args.event_log or root / "storage" / "episodes" / args.episode_id / "browser-handoffs" / "extension-events.jsonl"),
            chrome_profile_dir=profile_dir,
            companion_extension_dir=companion_extension_dir,
            remote_debugging_port=max(0, int(args.remote_debugging_port or 0)),
        )
    if args.provider == "grok-web-video":
        if not args.project_id:
            raise ValueError("--project-id is required for Grok proof.")
        scene_id = args.scene_id or "scene-01"
        return ProofTarget(
            provider=args.provider,
            autostart_url=args.autostart_url or grok_autostart_url(bridge, args.project_id, scene_id),
            event_log=Path(args.event_log or root / "storage" / "grok-handoffs" / args.project_id / "extension-events.jsonl"),
            chrome_profile_dir=profile_dir,
            companion_extension_dir=companion_extension_dir,
            remote_debugging_port=max(0, int(args.remote_debugging_port or 0)),
        )
    raise ValueError(f"unsupported provider: {args.provider}")


def open_chrome(target: ProofTarget, chrome_path: str) -> None:
    if not chrome_path:
        raise RuntimeError("Chrome executable not found. Pass --chrome-path or set VIDEO_STUDIO_CHROME_PATH.")
    companion_extension_dir = target.companion_extension_dir
    target.chrome_profile_dir.mkdir(parents=True, exist_ok=True)
    log_path = chrome_log_path(target.chrome_profile_dir)
    args = [
        chrome_path,
        f"--user-data-dir={target.chrome_profile_dir}",
        f"--disable-extensions-except={companion_extension_dir}",
        f"--load-extension={companion_extension_dir}",
        "--enable-extensions",
        "--disable-features=DisableLoadExtensionCommandLineSwitch",
        "--enable-logging",
        "--v=1",
        f"--log-file={log_path}",
        "--no-first-run",
        "--new-window",
    ]
    if target.remote_debugging_port:
        args.append(f"--remote-debugging-port={target.remote_debugging_port}")
    args.append(target.autostart_url)
    subprocess.Popen(args)


def profile_extension_path_seen(profile_dir: Path, companion_extension_dir: Path) -> bool:
    expected = str(companion_extension_dir).lower().replace("\\", "/")
    for relative in ("Default/Preferences", "Local State"):
        path = profile_dir / relative
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower().replace("\\", "/")
        except OSError:
            continue
        if expected in text or "video studio ai web companion" in text:
            return True
    return False


def chrome_log_path(profile_dir: Path) -> Path:
    return profile_dir / "chrome-extension-load.log"


def chrome_log_tail(profile_dir: Path, max_lines: int = 20) -> list[str]:
    path = chrome_log_path(profile_dir)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    interesting = [
        line for line in lines
        if "extension" in line.lower()
        or "chrome-grok-companion" in line.lower()
        or "manifest" in line.lower()
        or "error" in line.lower()
    ]
    return (interesting or lines)[-max_lines:]


def remote_debug_json(port: int, path: str) -> Any:
    if not port:
        return None
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=2.5) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def chrome_debug_summary(port: int) -> dict[str, Any]:
    version = remote_debug_json(port, "/json/version") or {}
    targets = remote_debug_json(port, "/json/list") or []
    if not isinstance(targets, list):
        targets = []
    extension_targets = [
        {
            "type": item.get("type", ""),
            "title": item.get("title", ""),
            "url": item.get("url", ""),
        }
        for item in targets
        if str(item.get("url", "")).startswith("chrome-extension://") or item.get("type") in {"service_worker", "background_page"}
    ]
    page_targets = [
        {
            "type": item.get("type", ""),
            "title": item.get("title", ""),
            "url": item.get("url", ""),
        }
        for item in targets
        if item.get("type") == "page"
    ]
    return {
        "browser": version.get("Browser", ""),
        "extensionTargetCount": len(extension_targets),
        "extensionTargets": extension_targets[:5],
        "pageTargets": page_targets[:5],
    }


def extension_load_status(target: ProofTarget, opened_chrome: bool, result: ProofResult) -> dict[str, Any]:
    profile_seen = profile_extension_path_seen(target.chrome_profile_dir, target.companion_extension_dir)
    debug = chrome_debug_summary(target.remote_debugging_port)
    extension_target_count = int(debug.get("extensionTargetCount", 0) or 0)
    if profile_seen or extension_target_count > 0:
        status = "loaded-or-visible"
        detail = "Companion extension registration or extension target was observed."
    elif opened_chrome and result.status == "blocked":
        status = "not-observed"
        detail = (
            "No companion extension registration or extension service worker target was observed after --load-extension; "
            "reload/load the unpacked extension in Chrome manually or use a Chrome/Chromium build that supports command-line extension loading."
        )
    else:
        status = "not-checked"
        detail = "Chrome was not opened by this run."
    return {
        "status": status,
        "detail": detail,
        "profileExtensionPathSeen": profile_seen,
        "debug": debug,
    }


def wait_for_result(target: ProofTarget, timeout_seconds: float, poll_seconds: float) -> ProofResult:
    deadline = time.time() + max(0.0, timeout_seconds)
    result = classify_events(target.provider, target.event_log)
    while timeout_seconds > 0 and time.time() < deadline:
        if result.status in {"pass", "fail"}:
            return result
        time.sleep(max(0.1, poll_seconds))
        result = classify_events(target.provider, target.event_log)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify or open Video Studio companion live proof URLs.")
    parser.add_argument("--provider", choices=["gemini-web-image", "grok-web-video"], required=True)
    parser.add_argument("--bridge", default=BRIDGE_URL)
    parser.add_argument("--episode-id", default="")
    parser.add_argument("--batch-id", default="batch-001")
    parser.add_argument("--cut-id", default="")
    parser.add_argument("--project-id", default="")
    parser.add_argument("--scene-id", default="")
    parser.add_argument("--autostart-url", default="")
    parser.add_argument("--event-log", default="")
    parser.add_argument("--profile-dir", default="")
    parser.add_argument("--chrome-path", default="")
    parser.add_argument("--extension-dir", default="")
    parser.add_argument("--remote-debugging-port", type=int, default=0)
    parser.add_argument(
        "--open",
        action="store_true",
        help="Launch an isolated Chrome profile for diagnostics only; signed-in live proof must use the operator's existing Chrome profile.",
    )
    parser.add_argument("--timeout", type=float, default=None, help="Seconds to wait for pass/fail evidence.")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = build_target(args)
    timeout = args.timeout
    if timeout is None:
        timeout = 90.0 if args.open else 0.0
    if args.open:
        open_chrome(target, args.chrome_path or default_chrome_path())
    result = wait_for_result(target, timeout, args.poll_interval)
    extension_status = extension_load_status(target, bool(args.open), result)
    payload = {
        **result.as_dict(),
        "autostartUrl": target.autostart_url,
        "chromeProfileDir": str(target.chrome_profile_dir),
        "extensionDir": str(target.companion_extension_dir),
        "extensionDirExists": (target.companion_extension_dir / "manifest.json").exists(),
        "profileExtensionPathSeen": extension_status["profileExtensionPathSeen"],
        "extensionLoadStatus": extension_status,
        "chromeLogPath": str(chrome_log_path(target.chrome_profile_dir)),
        "chromeLogTail": chrome_log_tail(target.chrome_profile_dir),
        "remoteDebuggingPort": target.remote_debugging_port,
        "openedChrome": bool(args.open),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{payload['provider']}: {payload['status']} - {payload['detail']}")
        print(f"eventLog: {payload['eventLog']}")
        print(f"markerSeen: {payload['markerSeen']}")
        if payload["lastEvent"]:
            print(f"lastEvent: {json.dumps(payload['lastEvent'], ensure_ascii=False)}")
        print(f"autostartUrl: {payload['autostartUrl']}")
        print(f"chromeProfileDir: {payload['chromeProfileDir']}")
        print(f"extensionDir: {payload['extensionDir']}")
        print(f"profileExtensionPathSeen: {payload['profileExtensionPathSeen']}")
        print(f"extensionLoadStatus: {payload['extensionLoadStatus']['status']} - {payload['extensionLoadStatus']['detail']}")
        print(f"chromeLogPath: {payload['chromeLogPath']}")
        print(f"remoteDebuggingPort: {payload['remoteDebuggingPort']}")
        if payload["chromeLogTail"]:
            print("chromeLogTail:")
            for line in payload["chromeLogTail"]:
                print(line)
    if result.status == "pass":
        return 0
    if result.status == "fail":
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
