from __future__ import annotations

import base64

from flask import Flask

from worker.bridge import auto_studio, routes_auto_studio
from worker.bridge.routes_auto_studio import auto_studio_bp


def _status(key: str, *, ready: bool = False, mode: str = "stub"):
    return type(
        "AdapterStatus",
        (),
        {
            "to_dict": lambda self: {
                "key": key,
                "label": key,
                "mode": mode,
                "outputKind": "video" if key in {"grok", "wan", "pexels-video"} else "image",
                "model": key,
                "ready": ready,
                "fallbackAvailable": True,
                "entryPoint": None,
                "commandPreview": None,
                "detail": f"{key} test status",
            }
        },
    )()


def _discovery(seed: str, *, limit: int = 3) -> dict:
    return {
        "ok": True,
        "mode": "auto-hot-topic",
        "source": "test",
        "live": False,
        "seed": seed or "오늘 한국에서 가장 뜨거운 소재",
        "candidates": [
            {
                "id": "topic-1",
                "label": "1순위",
                "title": "AI 영상 스튜디오 자동화",
                "centralQuestion": "AI 영상 스튜디오는 어디까지 자동으로 만들 수 있는가?",
                "whyHot": "제작 시간이 줄어드는지 검증하기 좋은 소재입니다.",
                "viewerPromise": "자동 주제 선정부터 렌더 후보까지 이어지는 흐름을 보여줍니다.",
                "searchSeed": "AI 영상 자동화",
                "first30SecPromise": "자동 제작의 첫 병목을 먼저 보여준다.",
                "score": 88,
                "evidencePlan": ["search", "trend", "video", "community"],
                "researchLinks": [
                    {"surface": "search", "query": "AI 영상 자동화", "url": "https://example.test/search"},
                    {"surface": "video", "query": "AI 영상 제작", "url": "https://example.test/video"},
                ],
            }
        ],
        "sourceLedger": [],
        "researchQueryPlan": [],
    }


def _scenes(topic: str, lang: str, template_type: str, tone: str, **kwargs):
    return [
        {
            "scene_num": 1,
            "narration": "AI 영상 스튜디오가 먼저 소재를 고릅니다.",
            "display_text": "소재 자동 선정",
            "image_prompt": "Korean creator dashboard selecting trending topic, cinematic light",
            "emotion": "shock",
        },
        {
            "scene_num": 2,
            "narration": "그 다음 장면별 프롬프트와 에셋 후보를 만듭니다.",
            "display_text": "프롬프트와 에셋",
            "image_prompt": "vertical storyboard with image prompts and generated assets",
            "emotion": "neutral",
        },
    ], "test-llm"


def _client(tmp_path, monkeypatch):
    cache = tmp_path / "storage" / "cache"
    cache.mkdir(parents=True)
    monkeypatch.setattr(routes_auto_studio, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(auto_studio, "build_hot_topic_candidates", _discovery)
    monkeypatch.setattr(auto_studio, "generate_scenes_llm", _scenes)
    monkeypatch.setattr(
        auto_studio,
        "probe_local_media_adapters",
        lambda project_root: {
            "gemini-flash": _status("gemini-flash", ready=True, mode="command"),
            "pexels-video": _status("pexels-video"),
            "wan": _status("wan"),
            "grok": _status("grok"),
        },
    )

    def fake_route_image(scene: dict):
        output = cache / f"{len(list(cache.glob('*.png'))) + 1}.png"
        output.write_bytes(b"not-a-real-png-but-good-enough-for-source-copy")
        return str(output), "gemini-flash"

    monkeypatch.setattr(auto_studio, "route_image", fake_route_image)
    app = Flask(__name__)
    app.register_blueprint(auto_studio_bp)
    return app.test_client()


def test_auto_studio_provider_registry_includes_grok_and_future_slots(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.get("/api/auto-studio/providers")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["schema"] == "video-studio.auto-studio.asset-provider-registry.v1"
    assert "operator-handoff" in payload["executionModes"]
    assert "manual-import" in payload["executionModes"]
    assert payload["devProofRail"]["browserControl"].startswith("development proof rail")
    providers = {item["key"]: item for item in payload["providers"]}
    assert providers["grok"]["executionMode"] == "operator-handoff"
    assert providers["grok"]["handoffKind"] == "grok-imagine"
    assert providers["grok"]["canGenerateNow"] is False
    assert providers["grok"]["canImportResult"] is True
    assert providers["grok"]["requiresOperatorProof"] is True
    assert "/c/*" in providers["grok"]["proofBoundary"]
    assert providers["grok"]["devProofRail"]["acceptedAsProductFlow"] is False
    assert providers["gemini"]["executionMode"] == "operator-handoff"
    assert providers["gemini"]["canGenerateNow"] is False
    assert providers["seedance"]["executionMode"] == "manual-import"
    assert providers["custom-external"]["executionMode"] == "manual-import"
    assert payload["extensionContract"]["output"].startswith("SceneAssetPayload")


def test_auto_studio_run_builds_editable_draft_and_manifest(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/auto-studio/run",
        json={"assetProvider": "auto-image", "generateAssets": True, "renderMode": "draft"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["schema"] == "video-studio.auto-studio.run.v1"
    assert payload["status"] == "draft-ready"
    assert payload["publishReady"] is False
    assert payload["selectedCandidate"]["title"] == "AI 영상 스튜디오 자동화"
    assert payload["assetPipeline"]["selectedProvider"]["key"] == "auto-image"
    assert payload["assetPipeline"]["sceneAssetsAttached"] == 2
    assert payload["metrics"]["paidProviderUsage"] == 0
    assert len(payload["draftResult"]["scenes"]) == 2
    assert payload["draftResult"]["scenes"][0]["_server_asset_path"]
    assert payload["draftResult"]["scenes"][0]["_image_url"].startswith("http://127.0.0.1:5161/api/images/")
    assert payload["projectSave"]["saveResult"]["manifestPath"]
    assert (tmp_path / "storage" / "auto-studio" / "latest.json").exists()


def test_auto_studio_grok_path_is_manual_handoff_not_fake_asset(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    def fail_route_image(scene: dict):
        raise AssertionError("Grok handoff must not call image_router")

    monkeypatch.setattr(auto_studio, "route_image", fail_route_image)

    response = client.post(
        "/api/auto-studio/run",
        json={"assetProvider": "grok", "generateAssets": True, "renderMode": "draft"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "manual-handoff-required"
    assert payload["assetPipeline"]["selectedProvider"]["key"] == "grok"
    assert payload["assetPipeline"]["sceneAssetsAttached"] == 0
    assert len(payload["assetPipeline"]["handoffQueue"]) == 2
    assert payload["assetPipeline"]["handoffQueue"][0]["status"] == "queued"
    assert payload["assetPipeline"]["handoffQueue"][0]["targetUrl"] == "https://grok.com/imagine"
    assert payload["assetPipeline"]["handoffQueue"][0]["expectedFileName"] == "scene-01.grok.mp4"
    assert payload["assetPipeline"]["renderReadiness"]["renderReady"] is False
    assert payload["assetPipeline"]["renderReadiness"]["missingImportProofSceneIds"] == ["scene-01", "scene-02"]
    assert "requires handoff/import" in payload["assetPipeline"]["warnings"][0]
    assert {scene["image_source"] for scene in payload["draftScenes"]} == {"grok"}
    assert payload["draftResult"]["scenes"][0]["sceneId"] == "scene-01"
    assert payload["draftResult"]["scenes"][0]["_upload_kind"] == "video"


def test_auto_studio_handoff_smoke_render_blocks_without_import_proof(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/auto-studio/run",
        json={"assetProvider": "grok", "generateAssets": True, "renderMode": "smoke"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "render-blocked"
    assert payload["renderResult"] is None
    assert payload["assetPipeline"]["renderReadiness"]["renderReady"] is False
    assert payload["assetPipeline"]["warnings"][0].startswith("Render blocked")


def test_auto_studio_import_asset_writes_scene_payload_and_sidecar(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run_response = client.post(
        "/api/auto-studio/run",
        json={"assetProvider": "grok", "generateAssets": True, "renderMode": "draft"},
    )
    run_payload = run_response.get_json()
    task = run_payload["assetPipeline"]["handoffQueue"][0]

    response = client.post(
        "/api/auto-studio/import-asset",
        json={
            "runId": run_payload["runId"],
            "sceneId": task["sceneId"],
            "provider": task["provider"],
            "handoffTaskId": task["taskId"],
            "prompt": task["prompt"],
            "fileName": "scene-01.grok.mp4",
            "fileBase64": base64.b64encode(bytes.fromhex("00000018667479706d703432") + b"fake-mp4").decode("ascii"),
            "sourceSurface": "https://grok.com/imagine",
            "operatorNote": "human downloaded the MP4",
            "proofMode": "operator-local-import",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["schema"] == "video-studio.auto-studio.operator-import-provenance.v1"
    asset = payload["asset"]
    assert asset["sceneId"] == "scene-01"
    assert asset["role"] == "visual"
    assert asset["mimeType"] == "video/mp4"
    assert asset["sourcePath"].endswith("storage/auto-studio/imports/" + run_payload["runId"] + "/scene-01/scene-01-grok.mp4")
    sidecar_path = tmp_path / payload["provenancePath"]
    assert sidecar_path.exists()
    sidecar = sidecar_path.read_text(encoding="utf-8")
    assert '"provider": "grok"' in sidecar
    assert '"proofMode": "operator-local-import"' in sidecar
    updated = payload["run"]
    assert updated["assetPipeline"]["handoffQueue"][0]["status"] == "imported"
    assert updated["draftResult"]["scenes"][0]["_server_asset_path"] == asset["sourcePath"]


def test_auto_studio_import_asset_rejects_invalid_magic_and_oversized_payload(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run_payload = client.post(
        "/api/auto-studio/run",
        json={"assetProvider": "grok", "generateAssets": True, "renderMode": "draft"},
    ).get_json()
    task = run_payload["assetPipeline"]["handoffQueue"][0]

    invalid_magic = client.post(
        "/api/auto-studio/import-asset",
        json={
            "runId": run_payload["runId"],
            "sceneId": task["sceneId"],
            "provider": task["provider"],
            "handoffTaskId": task["taskId"],
            "fileName": "scene-01.grok.mp4",
            "fileBase64": base64.b64encode(b"not-an-mp4").decode("ascii"),
        },
    )
    assert invalid_magic.status_code == 400
    assert "magic-byte" in invalid_magic.get_json()["error"]

    monkeypatch.setattr(auto_studio, "AUTO_STUDIO_IMPORT_MAX_BYTES", 8)
    oversized = client.post(
        "/api/auto-studio/import-asset",
        json={
            "runId": run_payload["runId"],
            "sceneId": task["sceneId"],
            "provider": task["provider"],
            "handoffTaskId": task["taskId"],
            "fileName": "scene-01.grok.mp4",
            "fileBase64": base64.b64encode(bytes.fromhex("00000018667479706d703432")).decode("ascii"),
        },
    )
    assert oversized.status_code == 400
    assert "exceeds" in oversized.get_json()["error"]
