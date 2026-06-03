import base64
import json

from flask import Flask

from worker.bridge.routes_media import init_media_routes, media_bp
from worker.media.model_router import ProviderAvailability
from worker.planner.save_plan import save_project_bundle
from worker.render import compose, compose_ffmpeg
from worker.render.bgm import free_audio_candidates, free_audio_sidecar_template


def _media_test_client(project_root):
    init_media_routes(
        "127.0.0.1",
        5161,
        project_root / "storage" / "tts",
        project_root,
        lambda _path: 1.0,
        lambda value: value,
        lambda value: value,
    )
    app = Flask(__name__)
    app.register_blueprint(media_bp)
    return app.test_client()


def test_free_audio_candidates_prioritize_template_and_mood():
    candidates = free_audio_candidates(template_type="persona_story", mood="cinematic", limit=4)

    assert candidates
    assert candidates[0]["mood"] == "cinematic"
    assert "persona_story" in candidates[0]["templateFamilies"]
    assert all(candidate["provider"] not in {"suno", "elevenlabs", "openai-tts"} for candidate in candidates)


def test_free_audio_candidates_can_exclude_medium_risk_sources():
    candidates = free_audio_candidates(template_type="authentic_vlog", mood="calm", include_risky=False)

    assert candidates
    assert {candidate["riskLevel"] for candidate in candidates} == {"low"}
    assert any(candidate["provider"] in {"mixkit", "freesound", "wikimedia-commons"} for candidate in candidates)


def test_free_audio_candidates_fallback_when_template_mood_has_no_exact_pool():
    candidates = free_audio_candidates(
        template_type="news_explainer",
        mood="tense",
        fallback_moods=["cinematic", "calm", "upbeat"],
        limit=5,
    )

    assert candidates
    assert all(candidate["matchReason"] in {"fallback-mood", "template-fallback"} for candidate in candidates)
    assert any(candidate["provider"] in {"youtube-audio-library", "mixkit", "pixabay-audio"} for candidate in candidates)


def test_free_audio_sidecar_template_has_provenance_fields():
    sidecar = free_audio_sidecar_template("freesound-cafe-ambience-seoul-naotokui")

    assert sidecar is not None
    assert sidecar["provider"] == "freesound"
    assert sidecar["sourceUrl"].startswith("https://freesound.org/")
    assert sidecar["sourceLicense"] == "Creative Commons 0 1.0"
    assert sidecar["licenseUrl"].startswith("https://creativecommons.org/")
    assert sidecar["downloadDate"] == ""
    assert "authentic_vlog" in sidecar["templateFamilies"]


def test_free_audio_sidecar_template_marks_attribution_required_assets():
    sidecar = free_audio_sidecar_template("fma-circuit-1000-handz")

    assert sidecar is not None
    assert sidecar["attributionRequired"] is True
    assert "1000 Handz" in sidecar["attribution"]
    assert sidecar["licenseUrl"].endswith("/by/4.0/")


def test_free_audio_candidates_include_korean_public_source_workflows():
    candidates = free_audio_candidates(
        template_type="kculture_fandom",
        mood="upbeat",
        fallback_moods=["cinematic", "calm"],
        limit=12,
    )
    providers = {candidate["provider"] for candidate in candidates}

    assert "gongu-copyright" in providers
    assert "kogl" in providers
    assert all(candidate["provider"] not in {"suno", "elevenlabs", "openai-tts"} for candidate in candidates)

    gongu = free_audio_sidecar_template("gongu-copyright-korean-sfx-source")
    assert gongu is not None
    assert gongu["provider"] == "gongu-copyright"
    assert gongu["attributionRequired"] is True
    assert gongu["sourceUrl"].startswith("https://gongu.copyright.or.kr/")
    assert "kculture_fandom" in gongu["templateFamilies"]

    kogl = free_audio_sidecar_template("kogl-type1-public-audio-source")
    assert kogl is not None
    assert kogl["provider"] == "kogl"
    assert kogl["licenseUrl"].startswith("https://www.mcst.go.kr/")
    assert "news_explainer" in kogl["templateFamilies"]


def test_imported_free_bgm_counts_as_local_rotation_with_source_provider(tmp_path):
    mood_dir = tmp_path / "assets" / "bgm" / "cinematic"
    mood_dir.mkdir(parents=True)
    track = mood_dir / "silent-descent.wav"
    prepared = tmp_path / "storage" / "renders" / "prepared-bgm.wav"
    track.write_bytes(b"fake-bgm")
    prepared.parent.mkdir(parents=True)
    prepared.write_bytes(b"prepared")
    track.with_suffix(f"{track.suffix}.json").write_text(
        json.dumps({
            "provider": "mixkit",
            "title": "Silent Descent",
            "artist": "Eugenio Mininni",
            "sourceUrl": "https://mixkit.co/free-stock-music/mood/melancholic/",
            "sourceLicense": "Mixkit Stock Music Free License",
            "licenseUrl": "https://mixkit.co/license/",
            "attributionRequired": False,
            "downloadDate": "2026-05-26",
        }),
        encoding="utf-8",
    )
    manifest = {"assets": []}

    compose._append_bgm_asset(
        manifest,
        bgm_track=track,
        prepared_path=prepared,
        project_root=tmp_path,
        mood="cinematic",
        duration_sec=24.0,
        selection={
            "candidateCount": 2,
            "selectionMethod": "stable-hash",
            "selectionKey": "project-42:persona_story",
        },
    )

    bgm_asset = manifest["assets"][0]
    assert bgm_asset["provider"] == "local-bgm"
    assert bgm_asset["sourceProvider"] == "mixkit"
    assert bgm_asset["sourceLabel"] == "Silent Descent"
    assert bgm_asset["sourceLicense"] == "Mixkit Stock Music Free License"
    assert bgm_asset["attributionRequired"] is False

    review = compose_ffmpeg._build_production_review(manifest, [])
    summary = review["summary"]
    expected_label = "global:local-bgm:bgm:Silent Descent"
    assert summary["freeAudioProvenanceAssets"] == [expected_label]
    assert summary["missingFreeAudioProvenanceAssets"] == []
    assert summary["bgmSelectionAssets"] == [expected_label]
    assert summary["weakBgmSelectionAssets"] == []
    assert summary["freeAudioCreditMissingAssets"] == []
    assert summary["youtubeDescriptionAudioCredits"]
    assert "Silent Descent" in summary["youtubeDescriptionAudioCredits"][0]
    assert "https://mixkit.co/license/" in summary["youtubeDescriptionAudioCredits"][0]


def test_operator_pinned_bgm_is_used_as_render_selection_evidence(tmp_path):
    mood_dir = tmp_path / "assets" / "bgm" / "cinematic"
    mood_dir.mkdir(parents=True)
    track = mood_dir / "operator-choice.wav"
    prepared = tmp_path / "storage" / "renders" / "prepared-bgm.wav"
    track.write_bytes(b"fake-bgm")
    prepared.parent.mkdir(parents=True)
    prepared.write_bytes(b"prepared")
    track.with_suffix(f"{track.suffix}.json").write_text(
        json.dumps({
            "provider": "mixkit",
            "title": "Operator Choice",
            "artist": "Local Curator",
            "sourceUrl": "https://mixkit.co/free-stock-music/",
            "sourceLicense": "Mixkit Stock Music Free License",
            "licenseUrl": "https://mixkit.co/license/",
            "attributionRequired": False,
            "downloadDate": "2026-05-26",
        }),
        encoding="utf-8",
    )
    manifest = {
        "bgmAsset": {
            "path": "assets/bgm/cinematic/operator-choice.wav",
            "candidateId": "mixkit-operator-choice",
            "mood": "cinematic",
            "operatorSelected": True,
        },
        "assets": [],
    }

    selection = compose._resolve_operator_bgm_selection(manifest, tmp_path, mood="upbeat")

    assert selection is not None
    assert selection["path"] == track.resolve()
    assert selection["selectionMethod"] == "operator-pinned"
    assert selection["selectionKey"] == "operator-pinned:mixkit-operator-choice"

    compose._append_bgm_asset(
        manifest,
        bgm_track=track,
        prepared_path=prepared,
        project_root=tmp_path,
        mood=selection["mood"],
        duration_sec=20.0,
        selection=selection,
    )
    review = compose_ffmpeg._build_production_review(manifest, [])
    summary = review["summary"]

    expected_label = "global:local-bgm:bgm:Operator Choice"
    assert summary["bgmSelectionAssets"] == [expected_label]
    assert summary["weakBgmSelectionAssets"] == []
    assert summary["freeAudioCreditMissingAssets"] == []


def test_save_project_bundle_persists_operator_pinned_bgm_asset(tmp_path):
    mood_dir = tmp_path / "assets" / "bgm" / "calm"
    mood_dir.mkdir(parents=True)
    track = mood_dir / "calm-pinned.wav"
    track.write_bytes(b"fake-bgm")

    payload = save_project_bundle(
        prompt="Pinned BGM manifest test",
        budget_mode="free",
        planner_mode="sample",
        project_id="pinned-bgm-test",
        project_root=tmp_path,
        availability=ProviderAvailability(),
        template_type="authentic_vlog",
        bgm_asset={
            "path": "assets/bgm/calm/calm-pinned.wav",
            "sidecarPath": "assets/bgm/calm/calm-pinned.wav.json",
            "provider": "local-bgm",
            "sourceProvider": "mixkit",
            "sourceUrl": "https://mixkit.co/free-stock-music/",
            "sourceLicense": "Mixkit Stock Music Free License",
            "licenseUrl": "https://mixkit.co/license/",
            "sourceLabel": "Calm Pinned",
            "mood": "calm",
            "candidateId": "mixkit-calm-pinned",
        },
    )

    bgm_asset = payload["manifest"]["bgmAsset"]
    assert bgm_asset["role"] == "bgm"
    assert bgm_asset["path"] == "assets/bgm/calm/calm-pinned.wav"
    assert bgm_asset["sourcePath"] == "assets/bgm/calm/calm-pinned.wav"
    assert bgm_asset["sourceOrigin"] == "operator-pinned"
    assert bgm_asset["operatorSelected"] is True
    assert bgm_asset["sourceProvider"] == "mixkit"


def test_free_audio_credit_export_requires_attribution_when_license_requires_it():
    manifest = {
        "assets": [
            {
                "id": "global-bgm",
                "sceneId": "global",
                "role": "audio",
                "provider": "local-bgm",
                "kind": "bgm",
                "sourceOrigin": "local-library",
                "sourceProvider": "free-music-archive",
                "sourceLabel": "Circuit",
                "sourceUrl": "https://freemusicarchive.org/music/1000-handz/example/circuit/",
                "sourceLicense": "Creative Commons Attribution 4.0 International",
                "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
                "attributionRequired": True,
                "candidateCount": 2,
                "selectionMethod": "stable-hash",
                "selectionKey": "project-42:ranking_list",
            }
        ],
        "scenes": [],
    }

    review = compose_ffmpeg._build_production_review(manifest, [])
    summary = review["summary"]
    expected_prefix = "global:local-bgm:bgm:Circuit"

    assert summary["freeAudioProvenanceAssets"] == [expected_prefix]
    assert summary["freeAudioCreditMissingAssets"] == [f"{expected_prefix}:missing=attribution"]
    assert summary["youtubeDescriptionAudioCredits"]
    assert "Circuit" in summary["youtubeDescriptionAudioCredits"][0]


def test_free_audio_credit_export_uses_supplied_attribution_line():
    manifest = {
        "assets": [
            {
                "id": "global-bgm",
                "sceneId": "global",
                "role": "audio",
                "provider": "local-bgm",
                "kind": "bgm",
                "sourceOrigin": "local-library",
                "sourceProvider": "free-music-archive",
                "sourceLabel": "Circuit",
                "sourceUrl": "https://freemusicarchive.org/music/1000-handz/example/circuit/",
                "sourceLicense": "Creative Commons Attribution 4.0 International",
                "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
                "attributionRequired": True,
                "attribution": "Circuit by 1000 Handz, licensed under CC BY 4.0.",
                "candidateCount": 2,
                "selectionMethod": "stable-hash",
                "selectionKey": "project-42:ranking_list",
            }
        ],
        "scenes": [],
    }

    review = compose_ffmpeg._build_production_review(manifest, [])
    summary = review["summary"]

    assert summary["freeAudioCreditMissingAssets"] == []
    assert summary["youtubeDescriptionAudioCredits"][0].startswith("Circuit by 1000 Handz")
    assert "Source: https://freemusicarchive.org/" in summary["youtubeDescriptionAudioCredits"][0]


def test_free_audio_candidates_route_returns_import_templates(tmp_path):
    client = _media_test_client(tmp_path)

    response = client.post("/api/free-assets/audio-candidates", json={
        "templateType": "persona_story",
        "mood": "cinematic",
        "limit": 3,
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["recommendedMood"] == "cinematic"
    assert payload["templateAudioPlan"]["templateType"] == "persona_story"
    assert payload["templateAudioPlan"]["layoutVariants"]
    assert payload["templateAudioPlan"]["sourceRoutes"]
    assert payload["candidates"]
    first = payload["candidates"][0]
    assert first["sidecarTemplate"]["sourceUrl"].startswith("https://")
    assert first["importPayloadTemplate"]["operatorApproved"] is False
    assert first["importPayloadTemplate"]["targetRole"] in {"bgm", "sfx"}


def test_free_audio_candidates_route_returns_template_fallback_plan_for_news(tmp_path):
    client = _media_test_client(tmp_path)

    response = client.post("/api/free-assets/audio-candidates", json={
        "templateType": "news_explainer",
        "variantKey": "headline-evidence",
        "mood": "tense",
        "limit": 6,
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["fallbackUsed"] is True
    assert payload["templateAudioPlan"]["selectedVariant"]["key"] == "headline-evidence"
    assert payload["templateAudioPlan"]["fallbackMoods"]
    assert payload["candidates"]
    assert payload["candidates"][0]["matchReason"] in {"fallback-mood", "template-fallback"}


def test_free_asset_sourcing_packet_includes_korean_public_source_routes(tmp_path):
    client = _media_test_client(tmp_path)

    response = client.post("/api/free-assets/sourcing-packet", json={
        "projectId": "korean-public-source-route",
        "templateType": "kculture_fandom",
        "draftScenes": [
            {
                "sceneId": "scene-01",
                "title": "Seoul stage-light context",
                "display_text": "공연장 주변 분위기",
                "narration": "권리 문제가 없는 도시와 현장 분위기 컷만 씁니다.",
                "image_prompt": "Seoul night street stage lights crowd queue",
            }
        ],
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True

    source_providers = {source["provider"] for source in payload["freeAssetSources"]}
    audio_providers = {source["provider"] for source in payload["audioSources"]}
    scene_search_providers = {
        source["provider"]
        for source in payload["scenes"][0]["candidateSearches"]
    }

    assert "gongu-copyright" in source_providers
    assert "kogl" in source_providers
    assert "gongu-copyright" in audio_providers
    assert "kogl" in audio_providers
    assert "kogl" in scene_search_providers
    assert any(
        source["provider"] == "gongu-copyright" and "gongu.copyright.or.kr" in source["searchUrl"]
        for source in payload["audioSources"]
    )
    assert any(
        source["provider"] == "kogl" and "kogl.or.kr" in source["searchUrl"]
        for source in payload["freeAssetSources"]
    )


def test_free_audio_import_requires_operator_approval(tmp_path):
    client = _media_test_client(tmp_path)
    source = tmp_path / "downloads" / "candidate.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"not-real-audio-but-copyable")

    response = client.post("/api/free-assets/import-audio", json={
        "sourcePath": str(source),
        "candidateId": "mixkit-silent-descent-eugenio-mininni",
    })

    assert response.status_code == 400
    assert "operatorApproved" in response.get_json()["error"]


def test_free_audio_import_copies_bgm_and_writes_sidecar(tmp_path):
    client = _media_test_client(tmp_path)
    source = tmp_path / "downloads" / "silent-descent.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"not-real-audio-but-copyable")

    response = client.post("/api/free-assets/import-audio", json={
        "operatorApproved": True,
        "sourcePath": str(source),
        "candidateId": "mixkit-silent-descent-eugenio-mininni",
        "targetRole": "bgm",
        "mood": "cinematic",
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["asset"]["role"] == "bgm"
    copied = tmp_path / payload["asset"]["path"]
    sidecar_path = tmp_path / payload["asset"]["sidecarPath"]
    assert copied.exists()
    assert copied.parent == tmp_path / "assets" / "bgm" / "cinematic"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["provider"] == "mixkit"
    assert sidecar["sourceUrl"].startswith("https://mixkit.co/")
    assert sidecar["sourceLicense"]
    assert sidecar["downloadDate"]
    assert sidecar["targetRole"] == "bgm"


def test_free_audio_import_accepts_browser_file_upload(tmp_path):
    client = _media_test_client(tmp_path)
    audio_bytes = b"browser-uploaded-audio"

    response = client.post("/api/free-assets/import-audio", json={
        "operatorApproved": True,
        "fileName": "silent-descent.mp3",
        "fileBase64": base64.b64encode(audio_bytes).decode("ascii"),
        "candidateId": "mixkit-silent-descent-eugenio-mininni",
        "targetRole": "bgm",
        "mood": "cinematic",
    })

    assert response.status_code == 200
    payload = response.get_json()
    copied = tmp_path / payload["asset"]["path"]
    sidecar_path = tmp_path / payload["asset"]["sidecarPath"]
    assert copied.read_bytes() == audio_bytes
    assert copied.parent == tmp_path / "assets" / "bgm" / "cinematic"
    assert payload["asset"]["importMethod"] == "browser-upload"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["originalFileName"] == "silent-descent.mp3"
    assert sidecar["importMethod"] == "browser-upload"
    assert sidecar["sourceUrl"].startswith("https://mixkit.co/")


def test_free_audio_import_rejects_browser_upload_without_audio_extension(tmp_path):
    client = _media_test_client(tmp_path)

    response = client.post("/api/free-assets/import-audio", json={
        "operatorApproved": True,
        "fileName": "license.txt",
        "fileBase64": base64.b64encode(b"not-audio").decode("ascii"),
        "candidateId": "mixkit-silent-descent-eugenio-mininni",
        "targetRole": "bgm",
        "mood": "cinematic",
    })

    assert response.status_code == 400
    assert "unsupported audio extension" in response.get_json()["error"]


def test_free_audio_import_can_target_sfx_library(tmp_path):
    client = _media_test_client(tmp_path)
    source = tmp_path / "downloads" / "whoosh.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"not-real-audio-but-copyable")

    response = client.post("/api/free-assets/import-audio", json={
        "operatorApproved": True,
        "sourcePath": str(source),
        "candidateId": "freesound-swooshes-susssounds",
        "targetRole": "sfx",
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["asset"]["role"] == "sfx"
    copied = tmp_path / payload["asset"]["path"]
    sidecar = json.loads((tmp_path / payload["asset"]["sidecarPath"]).read_text(encoding="utf-8"))
    assert copied.parent == tmp_path / "assets" / "sfx"
    assert sidecar["sourceLicense"] == "Creative Commons 0 1.0"
    assert sidecar["targetRole"] == "sfx"


def test_scene_sfx_asset_binding_preserves_free_audio_provenance(tmp_path):
    source = tmp_path / "assets" / "sfx" / "whoosh.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"not-real-audio-but-copyable")

    payload = save_project_bundle(
        prompt="SFX binding test",
        budget_mode="free",
        planner_mode="sample",
        project_id="sfx-binding-test",
        project_root=tmp_path,
        availability=ProviderAvailability(),
        template_type="ranking_list",
        draft_scenes=[{
            "sceneId": "scene-01",
            "scene_num": 1,
            "title": "Whoosh transition",
            "narration": "첫 장면 전환에서 짧은 효과음이 들어갑니다.",
            "display_text": "짧은 전환",
            "image_prompt": "vertical test scene",
            "duration": 3,
            "caption_preset": "lower-info",
        }],
        scene_assets=[{
            "sceneId": "scene-01",
            "role": "sfx",
            "fileName": "whoosh.wav",
            "mimeType": "audio/wav",
            "sourcePath": "assets/sfx/whoosh.wav",
            "provider": "local-sfx",
            "sourceProvider": "freesound",
            "sourceLabel": "Swooshes, whoosh, short, deep",
            "sourceUrl": "https://freesound.org/people/susssounds/sounds/752068/",
            "sourceLicense": "Creative Commons 0 1.0",
            "licenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
            "attribution": "",
        }],
    )

    sfx_asset = next(
        asset
        for asset in payload["manifest"]["assets"]
        if asset["sceneId"] == "scene-01" and asset["role"] == "sfx"
    )
    assert sfx_asset["provider"] == "local-sfx"
    assert sfx_asset["kind"] == "sfx"
    assert sfx_asset["sourceOrigin"] == "local-library"
    assert sfx_asset["sourceProvider"] == "freesound"
    assert sfx_asset["sourceUrl"].startswith("https://freesound.org/")
    assert sfx_asset["sourceLicense"] == "Creative Commons 0 1.0"
    assert sfx_asset["licenseUrl"].startswith("https://creativecommons.org/")
    assert sfx_asset["sourcePath"].startswith("storage/inputs/sfx-binding-test/uploads/scene-01/")

    review = compose_ffmpeg._build_production_review(payload["manifest"], [])
    summary = review["summary"]
    expected_label = "scene-01:local-sfx:sfx:Swooshes, whoosh, short, deep"
    assert summary["freeAudioProvenanceAssets"] == [expected_label]
    assert summary["missingFreeAudioProvenanceAssets"] == []
