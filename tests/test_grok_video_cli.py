"""grok_video CLI 페이로드 구성 단위 테스트 (네트워크 없이 순수 함수만).

scripts/grok_video.py는 standalone 스크립트라 패키지 import가 아닌
importlib file-load 방식으로 불러온다.
"""
import importlib.util
import pathlib

_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "grok_video.py"
_SPEC = importlib.util.spec_from_file_location("grok_video", _PATH)
grok_video = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(grok_video)


def test_profile_payload_attach_mode():
    """기존 Chrome attach: launch/profile 승인 끄고 attach 승인 켠다."""
    p = grok_video.profile_payload(True, 9222, "Default")
    assert p["useDefaultChromeProfile"] is True
    assert p["attachDefaultChromeApproved"] is True
    assert p["launchBrowserApproved"] is False
    assert p["profileApproved"] is False
    assert p["browserProfileMode"] == "default-chrome-cdp-attach"
    assert p["remoteDebuggingPort"] == 9222


def test_profile_payload_isolated_mode():
    """격리 프로필 launch: launch/profile 승인 켜고 attach 끈다."""
    p = grok_video.profile_payload(False, 9333, "HandoffProfile")
    assert p["useDefaultChromeProfile"] is False
    assert p["attachDefaultChromeApproved"] is False
    assert p["launchBrowserApproved"] is True
    assert p["profileApproved"] is True
    assert p["browserProfileMode"] == "isolated-handoff-profile"
    assert p["browserProfileDirectory"] == "HandoffProfile"


def test_automation_payload_preflight_only():
    """--preflight: preflightOnly만, 생성/다운로드 트리거 플래그는 없어야."""
    p = grok_video.build_automation_payload(
        "scene-01", use_default_profile=True, port=9222,
        profile_dir="Default", wait_seconds=120, preflight=True,
    )
    assert p["preflightOnly"] is True
    assert p["operatorApproved"] is True
    assert p["browserAutomationApproved"] is True
    assert "generatePromptApproved" not in p
    assert "watchDownloadsApproved" not in p


def test_automation_payload_generate_mode():
    """기본 생성: generate 트리거, 다운로드 감시는 비활성(native prompt 함정 회피)."""
    p = grok_video.build_automation_payload(
        "scene-01", use_default_profile=False, port=9222,
        profile_dir="Default", wait_seconds=200, preflight=False,
    )
    assert p.get("preflightOnly") is not True
    assert p["operatorApproved"] is True
    assert p["browserAutomationApproved"] is True
    assert p["generatePromptApproved"] is True
    assert p["submitPromptApproved"] is False
    assert p["downloadResultApproved"] is False
    assert p["watchDownloadsApproved"] is False
    assert p["operatorReadyTimeoutSeconds"] == 200
    assert p["sceneId"] == "scene-01"
