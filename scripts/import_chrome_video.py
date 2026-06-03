#!/usr/bin/env python3
"""Claude in Chrome -> video-studio import 헬퍼 (C1 반자동).

Claude in Chrome으로 grok/gemini에서 생성·다운로드한 mp4를 video-studio
브리지의 upload-mp4 엔드포인트로 넣어 기존 handoff 프로젝트의 scene에 등록한다.
이 경로는 video-studio가 허용하는 "operator-owned already-saved local MP4 import"에
해당한다 (운영자가 이미 저장 완료한 파일을 명시적으로 import).

설계 근거 (브리지 소스 검증)
---------------------------
- 엔드포인트: POST /api/grok-handoff/<project_id>/upload-mp4
  (routes_grok.py:12625 grok_handoff_upload_mp4_route)
- 필수 필드: operatorApproved=true, sceneId, fileBase64, fileName(.mp4)
  (routes_grok.py:9691 _decode_uploaded_mp4 — fileBase64/fileName 키 확인)
- 허용 경로: routes_media.py:9689 allowedRoutes에
  "operator-owned already-saved local MP4 import" 명시.
- 금지 경로(본 헬퍼가 피하는 것): "Chrome native download prompt",
  "Downloads watcher fallback" — 이건 *자동 감시* 경로. 본 헬퍼는 감시가 아니라
  운영자가 이미 저장한 파일을 직접 POST하므로 금지 대상이 아니다.

전제
----
- 대상 handoff 프로젝트(project_id)가 이미 생성돼 있어야 한다. 없으면 브리지가
  404("Grok handoff manifest not found")를 돌려준다. handoff 생성은 별도 단계.
- video-studio 브리지 실행 중: `npm run bridge` (포트 5161)

출력: stdout에 JSON 한 덩어리 (jq 파이프 가능).
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 5161


class BridgeError(Exception):
    """브리지 연결/전송 실패 (서버 미기동 등)."""


def _post(url: str, payload: dict, timeout: float) -> dict:
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


def resolve_file(file_arg: str, latest: bool, downloads_dir: Path) -> Path:
    """import할 mp4 경로 결정. --latest면 다운로드 폴더의 최신 .mp4."""
    if latest:
        if not downloads_dir.is_dir():
            raise FileNotFoundError(f"다운로드 폴더 없음: {downloads_dir}")
        mp4s = sorted(
            downloads_dir.glob("*.mp4"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not mp4s:
            raise FileNotFoundError(f"{downloads_dir}에 .mp4 파일 없음")
        return mp4s[0]
    path = Path(file_arg).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"파일 없음: {path}")
    if path.suffix.lower() != ".mp4":
        raise ValueError(f".mp4 파일이 아님: {path.name}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Claude in Chrome 다운로드 mp4 -> video-studio handoff scene import (C1 반자동)",
    )
    parser.add_argument("--project-id", required=True, help="대상 handoff projectId (이미 생성돼 있어야 함)")
    parser.add_argument("--scene-id", required=True, help="대상 sceneId (예: scene-01)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="import할 mp4 경로")
    src.add_argument("--latest", action="store_true", help="다운로드 폴더의 최신 .mp4 자동 선택")
    parser.add_argument(
        "--downloads-dir", default=str(Path.home() / "Downloads"),
        help="--latest용 폴더 (기본 ~/Downloads)",
    )
    parser.add_argument("--overwrite", action="store_true", help="기존 scene 시각 자산 덮어쓰기")
    parser.add_argument(
        "--no-preserve-candidates", action="store_true",
        help="기존 후보 자산 보존 안 함 (기본은 보존)",
    )
    parser.add_argument("--port", type=int, default=BRIDGE_PORT, help=f"브리지 포트 (기본 {BRIDGE_PORT})")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="POST 없이 payload 요약만 출력 (브리지 불필요, 자체 검증용)",
    )
    args = parser.parse_args(argv)

    try:
        mp4_path = resolve_file(
            args.file or "", args.latest, Path(args.downloads_dir).expanduser(),
        )
        file_bytes = mp4_path.read_bytes()
    except (FileNotFoundError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    encoded = base64.b64encode(file_bytes).decode("ascii")
    payload = {
        "operatorApproved": True,
        "sceneId": args.scene_id,
        "fileName": mp4_path.name,
        "fileBase64": encoded,
        "overwrite": bool(args.overwrite),
        "preserveCandidates": not args.no_preserve_candidates,
    }
    quoted = urllib.parse.quote(args.project_id, safe="")
    url = f"http://{BRIDGE_HOST}:{args.port}/api/grok-handoff/{quoted}/upload-mp4"

    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "mode": "dry-run",
            "url": url,
            "sceneId": args.scene_id,
            "file": str(mp4_path),
            "fileName": mp4_path.name,
            "fileBytes": len(file_bytes),
            "base64Chars": len(encoded),
            "note": "POST 안 함. 실제 import는 --dry-run 빼고 (브리지 실행 필요).",
        }, ensure_ascii=False, indent=2))
        return 0

    try:
        result = _post(url, payload, timeout=120)
    except BridgeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    out = {
        "ok": bool(result.get("ok", False)),
        "projectId": result.get("projectId") or args.project_id,
        "sceneId": args.scene_id,
        "fileName": mp4_path.name,
        "fileBytes": len(file_bytes),
        "error": result.get("error"),
        "reviewPacketUrl": result.get("reviewPacketUrl"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
