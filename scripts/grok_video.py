#!/usr/bin/env python3
"""Claude Code -> grok Imagine 영상 생성 CLI.

로컬 video-studio 브리지(127.0.0.1:5161)를 호출해 grok.com/imagine 세션에
프롬프트를 주입하고 영상 생성을 트리거한다. xAI 유료 API를 쓰지 않고
운영자 Chrome의 grok 로그인 세션을 재사용한다 (브리지 automationContract와
동일 계약: usesPaidApi=False).

역할 경계
---------
이 CLI는 (1) handoff 생성, (2) 프롬프트 주입 + 생성 트리거까지 책임진다.
생성된 mp4를 잡아오는 추출 단계는 기존 Chrome Companion 확장 파이프라인이
담당한다 — 브라우저 native download prompt 함정 때문에 브리지의 다운로드
감시 경로(downloadResultApproved/watchDownloadsApproved)는 비활성으로 둔다
(근거: app/ui/src/context/StudioContext.tsx:1745, 1796-1799 — UI도 동일하게
generate만 트리거하고 다운로드 플래그는 false).

페이로드는 UI(StudioContext.tsx grokBrowserProfilePayload + runGrokBrowserAutomation)를
1:1 미러링한다.

사용 전제
---------
- video-studio 브리지 실행 중: `npm run bridge` (포트 5161)
- Chrome에 grok/SuperGrok 로그인 + remote debugging 포트(기본 9222) 활성
  또는 격리 핸드오프 프로필 모드

출력: stdout에 JSON 한 덩어리 (jq 파이프 가능).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 5161
GROK_AUTH_PROVIDER_DEFAULT = "x"
# 격리 핸드오프 프로필 기본 디렉토리명. attach 모드에서는 실제 Chrome 프로필명.
DEFAULT_PROFILE_DIRECTORY = "Default"


class BridgeError(Exception):
    """브리지 연결/전송 실패 (서버 미기동 등)."""


def _post(path: str, payload: dict, timeout: float) -> dict:
    url = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 브리지는 4xx/5xx에도 JSON 본문(ok/error)을 돌려준다 — 그대로 surface.
        body = exc.read().decode("utf-8", "replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"ok": False, "error": f"HTTP {exc.code}: {body[:300]}"}
    except urllib.error.URLError as exc:
        raise BridgeError(
            f"브리지 연결 실패 ({url}): {exc.reason}. "
            "'npm run bridge'로 브리지를 먼저 띄우세요."
        ) from exc


def profile_payload(use_default_profile: bool, port: int, profile_dir: str) -> dict:
    """StudioContext.grokBrowserProfilePayload 미러.

    use_default_profile=True  -> 이미 떠 있는 Chrome에 CDP attach
        (launch/profile 승인 불필요, attach 승인 필요)
    use_default_profile=False -> 격리 핸드오프 프로필을 새로 launch
    """
    return {
        "launchBrowserApproved": not use_default_profile,
        "profileApproved": not use_default_profile,
        "useDefaultChromeProfile": use_default_profile,
        "attachDefaultChromeApproved": use_default_profile,
        "browserProfileMode": (
            "default-chrome-cdp-attach" if use_default_profile
            else "isolated-handoff-profile"
        ),
        "browserProfileDirectory": profile_dir,
        "remoteDebuggingPort": port,
    }


def build_automation_payload(
    scene_id: str,
    *,
    use_default_profile: bool,
    port: int,
    profile_dir: str,
    wait_seconds: int,
    preflight: bool,
) -> dict:
    """browser-automation 페이로드 구성 (UI 미러).

    preflight=True  -> preflightOnly: 브라우저 연결만 확인, 생성/다운로드 안 함.
    preflight=False -> generatePromptApproved로 생성 트리거.
        다운로드 감시 플래그는 의도적으로 false (native download 함정 회피).
    """
    payload = {
        "sceneId": scene_id,
        "operatorApproved": True,
        "browserAutomationApproved": True,
        "authProviderPreference": GROK_AUTH_PROVIDER_DEFAULT,
        **profile_payload(use_default_profile, port, profile_dir),
    }
    if preflight:
        payload["preflightOnly"] = True
        return payload
    payload.update({
        "waitForOperatorReadyApproved": True,
        "authKickoffApproved": True,
        "authProviderKickoffApproved": True,
        "cookieRejectApproved": True,
        "operatorReadyTimeoutSeconds": wait_seconds,
        "operatorReadyPollIntervalSeconds": 2,
        "submitPromptApproved": False,
        "generatePromptApproved": True,
        "downloadResultApproved": False,
        "watchDownloadsApproved": False,
        "allowNewestFallback": False,
        "sinceHandoff": True,
        "downloadClickTimeoutSeconds": 0,
        "watchTimeoutSeconds": 0,
    })
    return payload


def create_handoff(prompt: str, project_id: str, duration: int) -> dict:
    payload = {
        "draftScenes": [{
            "sceneId": "scene-01",
            "scene_num": 1,
            "image_source": "grok",
            "grok_prompt": prompt,
            "duration": duration,
        }],
    }
    if project_id:
        payload["projectId"] = project_id
    return _post("/api/grok-handoff", payload, timeout=30)


def run_automation(project_id: str, payload: dict) -> dict:
    browser_wait = max(
        int(payload.get("operatorReadyTimeoutSeconds", 0) or 0),
        int(payload.get("watchTimeoutSeconds", 0) or 0),
        int(payload.get("downloadClickTimeoutSeconds", 0) or 0),
    )
    # bridge.ts apiRunGrokBrowserAutomation 미러: max(30s, min(1850s, wait+30)).
    timeout = max(30, min(1850, browser_wait + 30))
    quoted = urllib.parse.quote(project_id)
    return _post(f"/api/grok-handoff/{quoted}/browser-automation", payload, timeout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Claude Code -> grok Imagine 영상 생성 (구독 세션 재사용, 유료 API 미사용)",
    )
    parser.add_argument("--prompt", required=True, help="영상 생성 프롬프트")
    parser.add_argument("--project-id", default="", help="handoff projectId (생략 시 브리지가 자동 생성)")
    parser.add_argument("--duration", type=int, default=6, help="영상 길이(초), 기본 6")
    parser.add_argument(
        "--use-default-profile", action="store_true",
        help="이미 떠 있는 Chrome에 attach (remote-debugging 필요). 미지정 시 격리 프로필 launch",
    )
    parser.add_argument("--port", type=int, default=9222, help="Chrome remote debugging 포트 (기본 9222)")
    parser.add_argument("--profile-dir", default=DEFAULT_PROFILE_DIRECTORY, help="Chrome 프로필 디렉토리명")
    parser.add_argument("--wait", type=int, default=180, help="operator-ready 대기 최대 초 (기본 180)")
    parser.add_argument(
        "--preflight", action="store_true",
        help="브라우저 연결만 확인하는 dry-run (영상 생성/다운로드 안 함)",
    )
    args = parser.parse_args(argv)

    try:
        handoff = create_handoff(args.prompt, args.project_id, args.duration)
        project_id = handoff.get("projectId") or args.project_id
        if not project_id:
            print(json.dumps(
                {"ok": False, "error": "handoff 생성 실패 — projectId 없음", "response": handoff},
                ensure_ascii=False, indent=2,
            ))
            return 1
        scenes = handoff.get("scenes") or []
        scene_id = (scenes[0].get("sceneId") if scenes else None) or "scene-01"

        payload = build_automation_payload(
            scene_id,
            use_default_profile=args.use_default_profile,
            port=args.port,
            profile_dir=args.profile_dir,
            wait_seconds=args.wait,
            preflight=args.preflight,
        )
        result = run_automation(project_id, payload)
    except BridgeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    out = {
        "ok": bool(result.get("ok", False)),
        "projectId": project_id,
        "sceneId": scene_id,
        "mode": "preflight" if args.preflight else "generate",
        "automationStatus": result.get("automationStatus"),
        "error": result.get("error"),
    }
    if not args.preflight and out["ok"]:
        out["note"] = (
            "생성 트리거됨. 생성된 mp4는 Chrome Companion 확장이 잡아 "
            f"upload-mp4 -> import 한다. 진행 상태: GET /api/grok-handoff/{project_id}/status"
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
