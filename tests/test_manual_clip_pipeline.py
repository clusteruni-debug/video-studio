"""Manual clip pipeline tests for Video Studio."""

import base64
import hashlib
import json
import os
import sys
import zlib
from pathlib import Path

from flask import Flask

from worker.bridge import image_router, routes_media
from worker.bridge.draft_executor import safe_resolve
from worker.bridge.routes_media import init_media_routes, media_bp
from worker.bridge.templates import build_template_prompt, get_live_channel_operating_templates
from worker.media.runtime import build_local_media_plan, generate_local_visual_asset
from worker.media.model_router import ProviderAvailability
from worker.planner.save_plan import save_project_bundle
from worker.render import compose, compose_ffmpeg
from worker.render.compose import SmokeRenderResult
from worker.render.compose_ffmpeg import write_render_quality_report
from worker.render.subtitles import generate_ass_subtitle


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _limit: int) -> bytes:
        return json.dumps({
            "videos": [
                {
                    "id": 101,
                    "url": "https://www.pexels.com/video/101/",
                    "duration": 6,
                    "image": "https://images.pexels.com/101.jpg",
                    "user": {"name": "Operator A"},
                    "video_files": [
                        {"width": 720, "height": 1280, "link": "https://videos.pexels.com/101-low.mp4"},
                        {"width": 1080, "height": 1920, "link": "https://videos.pexels.com/101.mp4"},
                    ],
                },
                {
                    "id": 202,
                    "url": "https://www.pexels.com/video/202/",
                    "duration": 8,
                    "image": "https://images.pexels.com/202.jpg",
                    "user": {"name": "Operator B"},
                    "video_files": [
                        {"width": 1080, "height": 1920, "link": "https://videos.pexels.com/202.mp4"},
                    ],
                },
            ]
        }).encode("utf-8")


def _valid_ffprobe_payload():
    return {
        "streams": [
            {
                "codec_type": "video",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": "30/1",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "6.000"},
    }


def _source_motion_evidence(status="pass", low_motion_scene_ids=None):
    low_motion_scene_ids = low_motion_scene_ids or []
    return {
        "status": status,
        "detail": "test source motion evidence",
        "tool": {"ready": True},
        "scenes": [
            {
                "sceneId": "scene-01",
                "provider": "upload",
                "status": "low-motion" if low_motion_scene_ids else "pass",
                "auditedSeconds": 4.0,
                "freezeDurationSeconds": 3.8 if low_motion_scene_ids else 0.2,
                "freezeRatio": 0.95 if low_motion_scene_ids else 0.05,
            }
        ],
        "lowMotionSceneIds": low_motion_scene_ids,
        "unavailableSceneIds": [],
        "auditedCount": 1,
        "totalVideoSources": 1,
    }


FULL_NARRATION = "Warm coffee fills the morning while the hands, steam, and small cafe sounds make the routine feel close and easy to follow."
CAPTION_REVIEW = (
    "Subject stays visible, caption placement is top-safe or lower-safe, and the Shorts UI danger zone remains clear. "
    "Compared against Korean Shorts references for first-two-second hook, 2-3s cut rhythm, caption safe-zone, and pacing."
)


def test_compose_tts_uses_only_explicit_viewer_narration():
    text, reason = compose._tts_narration_text_for_scene({
        "subtitleText": "첫 움직임",
        "narrationText": "퇴근길 발걸음이 느려지는 순간, 오늘의 루틴이 시작됩니다.",
    })
    assert text.startswith("퇴근길")
    assert reason == ""


def test_compose_tts_skips_subtitle_only_or_production_meta_text():
    subtitle_text, subtitle_reason = compose._tts_narration_text_for_scene({
        "subtitleText": "첫 움직임",
        "narrationText": "",
    })
    assert subtitle_text == ""
    assert subtitle_reason == "subtitle-only-not-viewer-narration"

    meta_text, meta_reason = compose._tts_narration_text_for_scene({
        "subtitleText": "아침 카페",
        "narrationText": "이번 영상은 조용한 루틴의 의도를 설명합니다.",
    })
    assert meta_text == ""
    assert meta_reason.startswith("production-meta-narration:")


def _current_quality_checks(**overrides):
    checks = {
        "outputSpec": {"status": "pass", "detail": "1080x1920 / 30fps / audio present"},
        "noPlaceholders": {"status": "pass", "detail": "no placeholder scenes"},
        "movingClipPriority": {"status": "pass", "detail": "all scenes use MP4 clips"},
        "sourceMotionEvidence": {"status": "pass", "detail": "source motion audit passed"},
        "zeroPaidProviders": {"status": "pass", "detail": "paidProviders=[]"},
        "captionSafePresets": {"status": "pass", "detail": "caption presets stay inside safe zone"},
        "subtitleArtifact": {"status": "pass", "detail": "captions.ass"},
        "manualSelectionEvidence": {"status": "pass", "detail": "manual rationale present"},
        "continuityEvidence": {"status": "pass", "detail": "continuity notes present"},
        "firstTwoSecondHook": {"status": "pass", "detail": "firstSceneHookReady=True"},
        "cutDensityPacing": {"status": "pass", "detail": "shortsCutDensityReady=True"},
        "aiSlopVisualFit": {"status": "pass", "detail": "all scene visual verdicts passed"},
        "stockAiClipFit": {"status": "pass", "detail": "source fit accepted"},
        "thumbnailFirstFrameStrength": {"status": "pass", "detail": "first-frame thumbnail review ready"},
        "stockOnlyCaveat": {"status": "pass", "detail": "source mix includes non-stock footage"},
        "ttsNarrationEvidence": {"status": "pass", "detail": "audio design ready"},
        "voicePolicyCompliance": {"status": "pass", "detail": "template voice policy ready"},
        "captionLayoutReview": {"status": "pass", "detail": "caption does not cover subject or Shorts UI"},
        "captionDensityAndSafeZone": {"status": "pass", "detail": "captions fit lower-mid Shorts safe zone"},
        "referenceEditGrammar": {"status": "pass", "detail": "reference edit grammar reflected in hook, cut rhythm, and safe-zone captions"},
        "assetReuseDiversity": {"status": "pass", "detail": "no repeated visual assets"},
        "freeAssetProvenance": {"status": "pass", "detail": "free asset source metadata retained"},
        "bgmAssetRotation": {"status": "pass", "detail": "BGM selected with project/template rotation evidence"},
        "bgmSoundQuality": {"status": "pass", "detail": "BGM is not procedural/beep/test-tone"},
        "templateSourcePlan": {"status": "pass", "detail": "template-specific source plan satisfied"},
        "publishReadinessGate": {"status": "pass", "detail": "status=ready"},
        "channelReadinessGate": {"status": "warn", "detail": "status=needs-original-footage"},
        "uploadReviewGate": {"status": "warn", "detail": "blocked until channel-ready"},
        "topTierReadinessGate": {"status": "warn", "detail": "status=needs-grok-local-hero"},
    }
    checks.update(overrides)
    return checks


def _top_tier_readiness(status="needs-grok-local-hero", ready=False):
    return {
        "status": status,
        "score": {"passed": 9 if ready else 8, "total": 13},
        "requiredFixes": [] if ready else ["For top-tier AI-assisted output, replace the first hook with a reviewed Grok app/web or local Wan/LTX/Hunyuan MP4."],
        "recommendedFixes": [],
        "summary": {
            "topTierEvidenceReady": ready,
            "grokOrLocalHeroReady": ready,
            "benchmarkGap": "none" if ready else "needs Grok/local AI hero",
        },
        "criteria": [
            {
                "key": "grokOrLocalHero",
                "label": "First hook has Grok/local AI MP4",
                "status": "pass" if ready else "fail",
                "detail": f"ready={ready}",
                "required": True,
            }
        ],
    }


def _media_test_client(project_root: Path):
    init_media_routes(
        "127.0.0.1",
        5161,
        project_root / "storage" / "tts",
        project_root,
        lambda _path: 1.0,
        lambda value: value,
        safe_resolve,
    )
    app = Flask(__name__)
    app.register_blueprint(media_bp)
    return app.test_client()


def test_regenerate_scene_tts_accepts_quality_rate_override(monkeypatch, tmp_path):
    captured = {}

    def fake_generate_tts(**kwargs):
        captured.update(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"fake tts")
        return True

    monkeypatch.setattr(routes_media, "generate_tts", fake_generate_tts)
    client = _media_test_client(tmp_path)

    response = client.post("/api/regenerate-scene-tts", json={
        "scene_num": 1,
        "narration": "여기서 힘이 딱 빠져요.",
        "tts_provider": "edge",
        "voice_gender": "female",
        "rate": "+8%",
        "pitch": "+0Hz",
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["rate"] == "+8%"
    assert payload["pitch"] == "+0Hz"
    assert captured["rate"] == "+8%"
    assert captured["pitch"] == "+0Hz"
    assert [item["key"] for item in payload["qualityCandidates"]] == [
        "ko-female-natural",
        "ko-female-clear",
        "ko-male-natural",
        "ko-male-clear",
    ]


def test_pexels_video_search_returns_curatable_candidates(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "test-key")
    monkeypatch.setattr(image_router.urllib_request, "urlopen", lambda *_args, **_kwargs: _FakeResponse())

    candidates = image_router.search_pexels_video_candidates("coffee steam", min_duration=5, per_page=8)

    assert [candidate["id"] for candidate in candidates] == ["101", "202"]
    assert candidates[0]["url"].endswith("101.mp4")
    assert candidates[0]["thumbnailUrl"].endswith("101.jpg")
    assert image_router.search_pexels_video("coffee steam", min_duration=5)["id"] == "101"


def test_free_asset_sourcing_packet_builds_template_specific_scene_plan(tmp_path):
    client = _media_test_client(tmp_path)

    response = client.post("/api/free-assets/sourcing-packet", json={
        "projectId": "persona-assets",
        "templateType": "persona_story",
        "draftScenes": [
            {
                "sceneId": "scene-01",
                "title": "비 오는 골목의 주인공",
                "display_text": "주인공이 네온 골목을 걷는다",
                "image_prompt": "cinematic rainy neon alley, same character, vertical video",
                "narration": "주인공이 같은 코트를 입고 골목으로 들어갑니다.",
                "duration": 5,
            }
        ],
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["templateType"] == "persona_story"
    assert payload["templateFamily"] == "AI persona/story Shorts"
    assert payload["preferredSourceOrder"][0] == "grok"
    assert payload["recommendedBgmMood"] == "cinematic"
    assert payload["packetPath"] == "storage/asset-packets/persona-assets/free-asset-sourcing-packet.json"
    assert payload["worksheetPath"] == "storage/asset-packets/persona-assets/free-asset-sourcing-worksheet.md"
    assert payload["layoutVariants"][0]["key"] == "character-continuity"
    assert payload["selectedTemplatePlaybook"]["templateType"] == "persona_story"
    assert "Grok app/web MP4" in payload["selectedTemplatePlaybook"]["primaryAssets"]
    assert "Pexels texture inserts only" in payload["scenes"][0]["freeAssetFallbacks"]
    assert payload["assetProductionRecipes"][0]["key"] == "grok-or-local-character-bible"
    assert "character/place/prop bible" in payload["assetProductionRecipes"][0]["proofFields"]
    assert payload["scenes"][0]["assetProductionRecipes"][0]["key"] == "grok-or-local-character-bible"
    assert payload["bgmPlan"]["recommendedMood"] == "cinematic"
    assert payload["bgmPlan"]["localLibrary"]["status"] == "empty"
    assert {item["method"] for item in payload["assetAcquisitionMethods"]} >= {
        "direct-upload",
        "grok-app-web",
        "local-video-model",
        "youtube-audio-library",
    }
    assert payload["scenes"][0]["assetSlots"][0]["provider"] == "grok"
    assert payload["scenes"][0]["layoutVariants"][0]["label"] == "character continuity"
    assert "Do not reuse" in payload["scenes"][0]["repeatGuard"]["rule"]
    urls = [
        item["searchUrl"]
        for item in payload["scenes"][0]["candidateSearches"]
        if item.get("searchUrl")
    ]
    assert any("pexels.com/search/videos" in url for url in urls)
    assert any("pixabay.com/videos/search" in url for url in urls)
    assert any("commons.wikimedia.org" in url for url in urls)
    assert {item["provider"] for item in payload["audioSources"]} >= {
        "youtube-audio-library",
        "mixkit",
        "freesound",
    }
    evidence_keys = {item["key"] for item in payload["evidenceSources"]}
    assert {
        "youtube-kr-shorts-workshop-2025",
        "youtube-audio-library",
        "pexels-video-api",
        "xai-imagine-pricing",
        "wan21-github",
    } <= evidence_keys
    assert any(item["templateType"] == "longform_deep_dive" for item in payload["templatePlaybook"])
    assert any("persona_story" in pattern for pattern in payload["koreanYoutubePatterns"])
    packet_path = tmp_path / payload["packetPath"]
    worksheet_path = tmp_path / payload["worksheetPath"]
    assert packet_path.exists()
    assert worksheet_path.exists()
    packet_file = json.loads(packet_path.read_text(encoding="utf-8"))
    worksheet_text = worksheet_path.read_text(encoding="utf-8")
    assert packet_file["projectId"] == "persona-assets"
    assert packet_file["scenes"][0]["repeatGuard"]["distinctKey"] == "persona_story:scene-01"
    assert "Free Asset Sourcing Worksheet" in worksheet_text
    assert "Selected Template Playbook" in worksheet_text
    assert "Zero-Paid Asset Production Recipes" in worksheet_text
    assert "Grok/local character continuity MP4" in worksheet_text
    assert "Evidence Sources" in worksheet_text
    assert "Add at least two candidates" in worksheet_text
    assert "Pexels Video" in worksheet_text


def test_live_channel_operating_templates_define_required_shortform_structures():
    templates = get_live_channel_operating_templates()

    assert set(templates) >= {
        "authentic_vlog_no_voice",
        "info_top_hook_lower_info",
        "ranking_chapter_card_compact",
        "longform_16x9_extension",
    }
    assert templates["authentic_vlog_no_voice"]["captionPreset"]["scene1"] == "top-hook"
    assert "no-voice" in templates["authentic_vlog_no_voice"]["bgmVoicePolicy"].lower()
    assert "lower-info" in templates["info_top_hook_lower_info"]["captionPreset"]["body"]
    assert "chapter-card" in templates["ranking_chapter_card_compact"]["label"]
    assert "16:9" in templates["longform_16x9_extension"]["platform"]

    prompt = build_template_prompt(
        topic="퇴근 루틴",
        lang_name="Korean",
        template_type="ranking_list",
        scene_count=4,
    )

    assert "LIVE CHANNEL OPERATING TEMPLATE" in prompt
    assert "ranking/list" in prompt
    assert "thumbnail/first-frame rule" in prompt


def test_save_project_bundle_preserves_grok_candidate_provenance(tmp_path):
    source = tmp_path / "source-grok.mp4"
    source.write_bytes(b"fake mp4")

    payload = save_project_bundle(
        prompt="Grok source provenance test",
        budget_mode="free",
        availability=ProviderAvailability(veo3=False, premium_enabled=False),
        planner_mode="sample",
        project_id="grok-provenance-test",
        project_root=tmp_path,
        template_type="news_explainer",
        draft_scenes=[
            {
                "sceneId": "scene-01",
                "title": "Hook",
                "display_text": "15초 리셋",
                "image_prompt": "worker subway platform vertical video",
                "duration": 3,
                "caption_preset": "top-hook",
                "audio_design_mode": "no-voice",
                "image_source": "grok",
                "selectedFileName": "source-grok.mp4",
                "selectedCandidateSummary": "Selected from three Grok handoff candidates because the first-second motion is clean.",
                "selectedCandidate": {
                    "fileName": "source-grok.mp4",
                    "sourceProvenance": {
                        "status": "local-mp4-download-unverified",
                        "acceptAsGrokMainSource": True,
                    },
                },
                "sourceProvenanceConfirmed": True,
                "sourceProvenanceNote": "Operator confirmed this came from the free Chrome/Grok handoff before render.",
            }
        ],
        scene_assets=[
            {
                "sceneId": "scene-01",
                "role": "visual",
                "kind": "video",
                "sourcePath": str(source),
                "fileName": "source-grok.mp4",
                "candidateCount": 3,
                "sourceProvenance": {
                    "status": "local-mp4-download-unverified",
                    "acceptAsGrokMainSource": True,
                },
            }
        ],
    )

    manifest = payload["manifest"]
    scene = manifest["scenes"][0]
    visual = next(asset for asset in manifest["assets"] if asset["role"] == "visual")
    assert scene["selectedFileName"] == "source-grok.mp4"
    assert scene["selectedCandidateSummary"].startswith("Selected from three Grok")
    assert scene["selectedCandidate"]["sourceProvenance"]["acceptAsGrokMainSource"] is True
    assert scene["sourceProvenanceConfirmed"] is True
    assert visual["candidateCount"] == 3
    assert visual["sourceProvenance"]["status"] == "local-mp4-download-unverified"


def test_free_asset_sourcing_packet_ranking_requires_distinct_sources(tmp_path):
    client = _media_test_client(tmp_path)

    response = client.post("/api/free-assets/sourcing-packet", json={
        "projectId": "ranking-assets",
        "templateType": "ranking_list",
        "draftScenes": [
            {"scene_num": 1, "display_text": "3위", "image_prompt": "Korean street food close up steam", "duration": 4},
            {"scene_num": 2, "display_text": "2위", "image_prompt": "Korean cafe dessert macro shot", "duration": 4},
        ],
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["templateType"] == "ranking_list"
    assert payload["sourceMix"].startswith("Pexels/Pixabay/Wikimedia")
    scene_keys = [scene["repeatGuard"]["distinctKey"] for scene in payload["scenes"]]
    assert scene_keys == ["ranking_list:scene-01", "ranking_list:scene-02"]
    assert payload["scenes"][0]["queries"][0] != payload["scenes"][1]["queries"][0]
    assert payload["assetProductionRecipes"][0]["key"] == "rank-distinct-candidate-cull"
    assert "candidate count" in payload["assetProductionRecipes"][0]["proofFields"]
    providers = {item["provider"] for item in payload["freeAssetSources"]}
    assert {"pexels-video", "pixabay-video", "wikimedia-commons", "mixkit"} <= providers
    assert any("one clip per item" in pattern for pattern in payload["koreanYoutubePatterns"])


def test_free_asset_sourcing_packet_covers_korean_longform_templates(tmp_path):
    client = _media_test_client(tmp_path)

    response = client.post("/api/free-assets/sourcing-packet", json={
        "projectId": "longform-assets",
        "templateType": "interview_documentary",
        "draftScenes": [
            {
                "sceneId": "scene-01",
                "display_text": "동네 서점 인터뷰",
                "image_prompt": "small bookstore interview hands documentary b-roll",
                "narration": "동네 서점이 살아남는 방식을 직접 인터뷰와 현장 B롤로 설명합니다.",
                "duration": 12,
            }
        ],
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["templateType"] == "interview_documentary"
    assert payload["templateFamily"] == "Korean interview/documentary"
    assert payload["preferredSourceOrder"][0] == "direct-upload"
    assert payload["layoutVariants"][0]["key"] == "observed-interview"
    assert payload["recommendedBgmMood"] == "calm"
    assert payload["scenes"][0]["layoutVariants"][1]["key"] == "tts-summary-doc"
    assert payload["assetProductionRecipes"][0]["key"] == "owned-interview-proof"
    assert "no voice imitation" in payload["assetProductionRecipes"][0]["proofFields"]
    providers = {item["provider"] for item in payload["freeAssetSources"]}
    assert {"freesound", "wikimedia-commons", "pexels-video", "youtube-audio-library"} <= providers
    assert any("interview_documentary" in pattern for pattern in payload["koreanYoutubePatterns"])


def test_dashboard_draft_uses_template_specific_bgm_mood(tmp_path):
    payload = save_project_bundle(
        prompt="manual persona short",
        budget_mode="free",
        availability=ProviderAvailability(),
        planner_mode="sample",
        project_id="persona-bgm-mood",
        project_root=tmp_path,
        draft_scenes=[
            {
                "sceneId": "scene-01",
                "scene_num": 1,
                "title": "Same character hook",
                "narration": FULL_NARRATION,
                "display_text": "Same character returns",
                "image_prompt": "consistent character, cinematic alley, vertical video",
                "image_source": "grok",
                "duration": 4,
            }
        ],
        template_type="persona_story",
    )

    plan = json.loads(Path(payload["saveResult"]["planPath"]).read_text(encoding="utf-8"))
    manifest = json.loads(Path(payload["saveResult"]["manifestPath"]).read_text(encoding="utf-8"))

    assert plan["bgmMood"] == "cinematic"
    assert manifest["templateType"] == "persona_story"


def test_select_bgm_track_records_project_template_rotation(tmp_path):
    mood_dir = tmp_path / "assets" / "bgm" / "cinematic"
    mood_dir.mkdir(parents=True)
    for name in ("quiet-city.mp3", "soft-pulse.mp3", "warm-room.mp3"):
        (mood_dir / name).write_bytes(b"")

    selection_key = "project-42:persona_story"
    first = compose_ffmpeg.select_bgm_track(tmp_path, mood="cinematic", selection_key=selection_key)
    second = compose_ffmpeg.select_bgm_track(tmp_path, mood="cinematic", selection_key=selection_key)

    assert first["path"] == second["path"]
    assert Path(first["path"]).parent == mood_dir
    assert first["candidateCount"] == 3
    assert first["selectionMethod"] == "stable-hash"
    assert first["selectionKey"] == selection_key


def test_select_bgm_track_prefers_provenance_ready_pool(tmp_path):
    mood_dir = tmp_path / "assets" / "bgm" / "cinematic"
    mood_dir.mkdir(parents=True)
    sidecar_a = mood_dir / "aaa-sidecar.wav"
    sidecar_b = mood_dir / "aab-sidecar.wav"
    missing = mood_dir / "zzz-missing.mp3"
    for track in (sidecar_a, sidecar_b, missing):
        track.write_bytes(b"")
    for track in (sidecar_a, sidecar_b):
        track.with_suffix(f"{track.suffix}.json").write_text(
            json.dumps({
                "sourceUrl": "https://example.com/free-audio",
                "sourceLicense": "CC0",
                "attribution": "none required",
            }),
            encoding="utf-8",
        )

    selected = compose_ffmpeg.select_bgm_track(
        tmp_path,
        mood="cinematic",
        selection_key="viewer-quality:authentic_vlog",
    )

    assert selected["candidateCount"] == 3
    assert selected["provenanceReadyCandidateCount"] == 2
    assert selected["path"].name in {sidecar_a.name, sidecar_b.name}
    assert selected["path"].name != missing.name


def test_select_bgm_track_falls_back_to_provenance_pool_when_mood_lacks_sidecars(tmp_path):
    calm_dir = tmp_path / "assets" / "bgm" / "calm"
    cinematic_dir = tmp_path / "assets" / "bgm" / "cinematic"
    calm_dir.mkdir(parents=True)
    cinematic_dir.mkdir(parents=True)
    calm_track = calm_dir / "calm-no-sidecar.mp3"
    sidecar_a = cinematic_dir / "aaa-sidecar.wav"
    sidecar_b = cinematic_dir / "aab-sidecar.wav"
    for track in (calm_track, sidecar_a, sidecar_b):
        track.write_bytes(b"")
    for track in (sidecar_a, sidecar_b):
        track.with_suffix(f"{track.suffix}.json").write_text(
            json.dumps({
                "sourceUrl": "local://video-studio/test-bgm",
                "sourceLicense": "operator-generated",
                "attribution": "test",
            }),
            encoding="utf-8",
        )

    selected = compose_ffmpeg.select_bgm_track(
        tmp_path,
        mood="calm",
        selection_key="viewer-quality:authentic_vlog",
    )

    assert selected["candidateCount"] == 3
    assert selected["provenanceReadyCandidateCount"] == 2
    assert selected["mood"] == "provenance-fallback"
    assert selected["requestedMood"] == "calm"
    assert selected["path"].parent == cinematic_dir
    assert selected["path"].name in {sidecar_a.name, sidecar_b.name}


def test_select_bgm_track_uses_mood_alias_before_global_fallback(tmp_path):
    calm_dir = tmp_path / "assets" / "bgm" / "calm"
    tech_house_dir = tmp_path / "assets" / "bgm" / "tech-house"
    calm_dir.mkdir(parents=True)
    tech_house_dir.mkdir(parents=True)
    (calm_dir / "calm-no-sidecar.mp3").write_bytes(b"")
    for name in ("minimal-techno.mp3", "swish-swed.mp3"):
        (tech_house_dir / name).write_bytes(b"")
    (tech_house_dir / "sources.json").write_text(
        json.dumps({
            "minimal-techno.mp3": {
                "sourceUrl": "https://mixkit.co/free-stock-music/tech-house/",
                "sourceLicense": "Mixkit Stock Music Free License",
                "attribution": "not required",
            },
            "swish-swed.mp3": {
                "sourceUrl": "https://mixkit.co/free-stock-music/tech-house/",
                "sourceLicense": "Mixkit Stock Music Free License",
                "attribution": "not required",
            },
        }),
        encoding="utf-8",
    )

    selected = compose_ffmpeg.select_bgm_track(
        tmp_path,
        mood="calm",
        selection_key="viewer-quality:authentic_vlog",
    )

    assert selected["path"].parent == tech_house_dir
    assert selected["mood"] == "tech-house"
    assert selected["requestedMood"] == "calm"
    assert selected["candidateCount"] == 3
    assert selected["provenanceReadyCandidateCount"] == 2
    assert "tech-house" in selected["moodCandidateDirs"]


def test_select_bgm_track_avoids_repeated_coffee_bed_when_alternatives_exist(tmp_path):
    upbeat_dir = tmp_path / "assets" / "bgm" / "upbeat"
    tech_house_dir = tmp_path / "assets" / "bgm" / "tech-house"
    upbeat_dir.mkdir(parents=True)
    tech_house_dir.mkdir(parents=True)
    coffee = upbeat_dir / "aaa-procedural-warm-coffee-bed.wav"
    coffee.write_bytes(b"")
    coffee.with_suffix(".wav.json").write_text(
        json.dumps({
            "sourceUrl": "local://video-studio/procedural",
            "sourceLicense": "operator-generated",
            "attribution": "local procedural bed",
        }),
        encoding="utf-8",
    )
    for name in ("minimal-techno.mp3", "swish-swed.mp3"):
        (tech_house_dir / name).write_bytes(b"")
    (tech_house_dir / "sources.json").write_text(
        json.dumps({
            "minimal-techno.mp3": {
                "sourceUrl": "https://mixkit.co/free-stock-music/tech-house/",
                "sourceLicense": "Mixkit Stock Music Free License",
                "attribution": "not required",
            },
            "swish-swed.mp3": {
                "sourceUrl": "https://mixkit.co/free-stock-music/tech-house/",
                "sourceLicense": "Mixkit Stock Music Free License",
                "attribution": "not required",
            },
        }),
        encoding="utf-8",
    )

    selected = compose_ffmpeg.select_bgm_track(
        tmp_path,
        mood="upbeat",
        selection_key="viewer-quality:ranking_list",
    )

    assert "coffee" not in selected["path"].name
    assert selected["path"].parent == tech_house_dir
    assert selected["provenanceReadyCandidateCount"] == 3


def test_select_bgm_track_avoids_procedural_beep_click_tracks_when_music_exists(tmp_path):
    upbeat_dir = tmp_path / "assets" / "bgm" / "upbeat"
    tech_house_dir = tmp_path / "assets" / "bgm" / "tech-house"
    upbeat_dir.mkdir(parents=True)
    tech_house_dir.mkdir(parents=True)
    for name in ("aaa-procedural-ranking-pulse.wav", "aab-procedural-soft-clicks.wav"):
        track = upbeat_dir / name
        track.write_bytes(b"")
        track.with_suffix(".wav.json").write_text(
            json.dumps({
                "sourceUrl": "local://ffmpeg-procedural-sine",
                "sourceLicense": "operator-generated",
                "attribution": "local sine/click placeholder",
            }),
            encoding="utf-8",
        )
    for name in ("minimal-techno.mp3", "swish-swed.mp3"):
        (tech_house_dir / name).write_bytes(b"")
    (tech_house_dir / "sources.json").write_text(
        json.dumps({
            "minimal-techno.mp3": {
                "sourceUrl": "https://mixkit.co/free-stock-music/tech-house/",
                "sourceLicense": "Mixkit Stock Music Free License",
                "attribution": "not required",
            },
            "swish-swed.mp3": {
                "sourceUrl": "https://mixkit.co/free-stock-music/tech-house/",
                "sourceLicense": "Mixkit Stock Music Free License",
                "attribution": "not required",
            },
        }),
        encoding="utf-8",
    )

    selected = compose_ffmpeg.select_bgm_track(
        tmp_path,
        mood="upbeat",
        selection_key="viewer-quality:ranking_list",
    )

    assert "procedural" not in selected["path"].name
    assert "click" not in selected["path"].name
    assert selected["path"].parent == tech_house_dir
    assert selected["provenanceReadyCandidateCount"] == 4


def test_append_bgm_asset_replaces_previous_global_bgm(tmp_path):
    mood_dir = tmp_path / "assets" / "bgm" / "cinematic"
    mood_dir.mkdir(parents=True)
    first_track = mood_dir / "first.wav"
    second_track = mood_dir / "second.wav"
    prepared = tmp_path / "storage" / "renders" / "bgm-prepared.wav"
    first_track.write_bytes(b"first")
    second_track.write_bytes(b"second")
    prepared.parent.mkdir(parents=True)
    prepared.write_bytes(b"prepared")

    manifest = {
        "assets": [
            {"id": "scene-01-audio", "sceneId": "scene-01", "role": "audio", "provider": "windows-speech"},
            {"id": "global-bgm", "sceneId": "global", "role": "audio", "provider": "local-bgm", "sourceLabel": "old"},
        ]
    }

    compose._append_bgm_asset(
        manifest,
        bgm_track=first_track,
        prepared_path=prepared,
        project_root=tmp_path,
        mood="cinematic",
        duration_sec=12,
        selection={"candidateCount": 2, "selectionMethod": "stable-hash", "selectionKey": "one"},
    )
    compose._append_bgm_asset(
        manifest,
        bgm_track=second_track,
        prepared_path=prepared,
        project_root=tmp_path,
        mood="cinematic",
        duration_sec=12,
        selection={"candidateCount": 2, "selectionMethod": "stable-hash", "selectionKey": "two"},
    )

    bgm_assets = [asset for asset in manifest["assets"] if asset.get("id") == "global-bgm"]
    assert len(bgm_assets) == 1
    assert bgm_assets[0]["sourcePath"].endswith("second.wav")
    assert manifest["assets"][0]["id"] == "scene-01-audio"


def test_free_asset_sourcing_packet_requires_scenes(tmp_path):
    client = _media_test_client(tmp_path)

    response = client.post("/api/free-assets/sourcing-packet", json={
        "templateType": "news_explainer",
        "draftScenes": [],
    })

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert "draftScenes" in payload["error"]


def test_local_video_generate_scene_requires_operator_approval(tmp_path):
    client = _media_test_client(tmp_path)

    response = client.post("/api/local-video/generate-scene", json={
        "provider": "wan",
        "sceneId": "scene-01",
        "prompt": "vertical alley shot",
    })

    payload = response.get_json()
    assert response.status_code == 403
    assert payload["ok"] is False
    assert "operatorApproved=true" in payload["error"]


def test_local_video_import_folder_requires_operator_approval(tmp_path):
    client = _media_test_client(tmp_path)
    source_dir = tmp_path / "wan-outputs"
    source_dir.mkdir()

    response = client.post("/api/local-video/import-folder", json={
        "sourceDir": str(source_dir),
        "draftScenes": [{"scene_num": 1, "display_text": "hook"}],
    })

    payload = response.get_json()
    assert response.status_code == 403
    assert payload["ok"] is False
    assert "operatorApproved=true" in payload["error"]


def test_local_video_import_folder_maps_named_and_ordered_mp4s_to_scene_assets(tmp_path):
    client = _media_test_client(tmp_path)
    source_dir = tmp_path / "local-model-outputs"
    source_dir.mkdir()
    (source_dir / "scene-02-payoff.mp4").write_bytes(b"scene two")
    (source_dir / "opening-hook.mp4").write_bytes(b"scene one")

    response = client.post("/api/local-video/import-folder", json={
        "operatorApproved": True,
        "projectId": "folder-intake-test",
        "sourceDir": str(source_dir),
        "draftScenes": [
            {"scene_num": 1, "display_text": "opening hook"},
            {"scene_num": 2, "display_text": "payoff"},
        ],
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["importedCount"] == 2
    assets = payload["assets"]
    assert [asset["sceneId"] for asset in assets] == ["scene-01", "scene-02"]
    by_scene = {asset["sceneId"]: asset for asset in assets}
    assert by_scene["scene-01"]["sourcePath"].endswith("storage/local-video-imports/folder-intake-test/scene-01/scene-01.local-folder.mp4")
    assert by_scene["scene-01"]["provider"] == "local-folder"
    assert by_scene["scene-01"]["previewUrl"].startswith("http://127.0.0.1:5161/api/local-video/preview")
    assert by_scene["scene-01"]["importMatch"] == "scene-order"
    assert by_scene["scene-02"]["importMatch"].startswith("filename-score")
    assert (tmp_path / by_scene["scene-01"]["sourcePath"]).read_bytes() == b"scene one"
    assert (tmp_path / by_scene["scene-02"]["sourcePath"]).read_bytes() == b"scene two"
    manifest = json.loads((tmp_path / payload["manifestPath"]).read_text(encoding="utf-8"))
    assert manifest["mode"] == "local-mp4-folder-intake"
    assert manifest["zeroPaid"] is True


def test_local_video_generate_scene_runs_command_and_returns_scene_asset(tmp_path, monkeypatch):
    client = _media_test_client(tmp_path)
    monkeypatch.setenv("VIDEO_STUDIO_WAN_MODE", "command")
    monkeypatch.setenv(
        "VIDEO_STUDIO_WAN_COMMAND",
        json.dumps([
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'fake mp4 bytes')",
            "{output_path}",
        ]),
    )

    response = client.post("/api/local-video/generate-scene", json={
        "operatorApproved": True,
        "provider": "wan",
        "projectId": "local-route-test",
        "sceneId": "scene-01",
        "title": "Neon hook",
        "prompt": "vertical cyberpunk alley, slow dolly push, no text",
        "durationSec": 4,
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["status"] == "generated"
    assert payload["adapterStatus"]["ready"] is True
    assert payload["asset"]["sourcePath"].endswith("storage/local-video/local-route-test/scene-01/outputs/scene-01.wan.mp4")
    assert payload["asset"]["previewUrl"].startswith("http://127.0.0.1:5161/api/local-video/preview")
    assert payload["asset"]["sourceGenerator"] == "wan"
    assert payload["asset"]["sourceGeneratorRequestPath"].endswith("scene-01.wan.request.json")
    assert payload["asset"]["sourceGeneratorPromptPath"].endswith("scene-01.wan.prompt.txt")
    assert payload["asset"]["sourceGeneratorLogPath"].endswith("scene-01.wan.command.log")
    assert sys.executable in payload["asset"]["sourceGeneratorCommand"]
    assert Path(payload["requestPath"]).exists()
    assert (tmp_path / payload["asset"]["sourcePath"]).read_bytes() == b"fake mp4 bytes"

    preview = client.get("/api/local-video/preview", query_string={"path": payload["asset"]["sourcePath"]})
    assert preview.status_code == 200


def test_local_video_generate_scene_requires_command_override_approval(tmp_path):
    client = _media_test_client(tmp_path)

    response = client.post("/api/local-video/generate-scene", json={
        "operatorApproved": True,
        "provider": "wan",
        "projectId": "local-override-approval",
        "sceneId": "scene-01",
        "prompt": "vertical alley shot",
        "commandTemplate": [sys.executable, "-c", "print('no run')"],
    })

    payload = response.get_json()
    assert response.status_code == 403
    assert payload["ok"] is False
    assert "commandOverrideApproved=true" in payload["error"]


def test_local_video_generate_scene_runs_approved_command_override_without_env(tmp_path, monkeypatch):
    client = _media_test_client(tmp_path)
    monkeypatch.setenv("VIDEO_STUDIO_WAN_MODE", "stub")
    monkeypatch.delenv("VIDEO_STUDIO_WAN_COMMAND", raising=False)

    response = client.post("/api/local-video/generate-scene", json={
        "operatorApproved": True,
        "commandOverrideApproved": True,
        "commandTemplate": [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'override mp4')",
            "{output_path}",
        ],
        "provider": "wan",
        "projectId": "local-override-test",
        "sceneId": "scene-01",
        "title": "Override hook",
        "prompt": "vertical local model shot, slow push, no text",
        "durationSec": 4,
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["status"] == "generated"
    assert payload["adapterStatus"]["mode"] == "command"
    assert payload["adapterStatus"]["detail"] == "operator-approved command override ready"
    assert payload["asset"]["sourceGenerator"] == "wan"
    assert payload["asset"]["sourcePath"].endswith("storage/local-video/local-override-test/scene-01/outputs/scene-01.wan.mp4")
    assert (tmp_path / payload["asset"]["sourcePath"]).read_bytes() == b"override mp4"
    request_json = json.loads(Path(payload["requestPath"]).read_text(encoding="utf-8"))
    assert request_json["commandOverrideApproved"] is True
    assert request_json["commandTemplateSource"] == "request"


def test_local_video_generate_scene_stub_writes_request_packet(tmp_path, monkeypatch):
    client = _media_test_client(tmp_path)
    monkeypatch.setenv("VIDEO_STUDIO_LTX_VIDEO_MODE", "stub")
    monkeypatch.delenv("VIDEO_STUDIO_LTX_VIDEO_COMMAND", raising=False)

    response = client.post("/api/local-video/generate-scene", json={
        "operatorApproved": True,
        "provider": "ltx-video",
        "projectId": "local-stub-test",
        "sceneId": "scene-02",
        "prompt": "vertical macro product shot, no text",
    })

    payload = response.get_json()
    request_path = Path(payload["requestPath"])
    prompt_path = Path(payload["promptPath"])
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["status"] == "placeholder"
    assert payload["asset"] is None
    assert payload["adapterStatus"]["mode"] == "stub"
    assert request_path.exists()
    assert prompt_path.exists()
    assert json.loads(request_path.read_text(encoding="utf-8"))["adapter"] == "ltx-video"


def test_dashboard_draft_scene_persists_selected_video_and_caption_preset(tmp_path):
    payload = save_project_bundle(
        prompt="manual coffee short",
        budget_mode="free",
        availability=ProviderAvailability(),
        planner_mode="sample",
        project_id="manual-test",
        project_root=tmp_path,
        draft_scenes=[
            {
                "sceneId": "scene-01",
                "scene_num": 1,
                "title": "Steam hook",
                "narration": "Steam rises before the first sip.",
                "display_text": "First sip",
                "image_prompt": "close coffee steam shot",
                "image_source": "pexels-video",
                "duration": 4,
                "caption_preset": "top-hook",
                "source_rationale": "Steam clip matches the opening cafe hook.",
                "continuity_note": "Warm cafe counter, shallow depth of field, slow push-in.",
                "hook_note": "Open on steam rising before the cup is revealed.",
                "originality_evidence": "Pexels clip is stock support footage, not channel-original hero footage.",
                "quality_review_note": "No watermark, no baked-in text, cup remains visible under lower caption safe zone.",
                "visual_quality_verdict": "pass",
                "thumbnail_review_note": "Use the steam reveal frame before text appears as the first-frame candidate.",
                "audio_mix_review_note": "Voice remains clear over low BGM; no clipping on headphones.",
                "platform_comparison_note": "Hook and pacing compared against current cafe Shorts; stock support still needs original hero.",
                "grok_prompt": "Vertical coffee steam reveal, no baked-in text.",
            }
        ],
        selected_pexels_videos={
            "scene-01": {
                "id": "101",
                "url": "https://videos.pexels.com/101.mp4",
                "width": 1080,
                "height": 1920,
                "duration": 6,
                "sourceUrl": "https://www.pexels.com/video/101/",
                "author": "Pexels Creator",
                "candidateCount": 4,
                "selectionMethod": "operator-selected-from-candidates",
                "selectionKey": "scene-01:101",
                "selectionRationale": "Selected from four reviewed Pexels candidates because steam motion starts immediately and fits the cafe hook.",
            }
        },
        subtitle_style="minimal",
        bgm_enabled=False,
    )

    manifest = json.loads(Path(payload["saveResult"]["manifestPath"]).read_text(encoding="utf-8"))
    scene = manifest["scenes"][0]
    visual = next(asset for asset in manifest["assets"] if asset["role"] == "visual")

    assert scene["visualKind"] == "video"
    assert scene["captionPreset"] == "top-hook"
    assert scene["subtitleText"] == "First sip"
    assert scene["narrationText"] == "Steam rises before the first sip."
    assert scene["sourceRationale"] == "Steam clip matches the opening cafe hook."
    assert scene["continuityNote"].startswith("Warm cafe counter")
    assert scene["hookNote"].startswith("Open on steam")
    assert scene["originalityEvidence"].startswith("Pexels clip")
    assert scene["qualityReviewNote"].startswith("No watermark")
    assert scene["visualQualityVerdict"] == "pass"
    assert scene["thumbnailReviewNote"].startswith("Use the steam reveal")
    assert scene["audioMixReviewNote"].startswith("Voice remains clear")
    assert scene["platformComparisonNote"].startswith("Hook and pacing")
    assert scene["grokPrompt"].startswith("Vertical coffee")
    assert visual["provider"] == "pexels-video"
    assert visual["sourceOrigin"] == "selected-stock"
    assert visual["sourceUrl"] == "https://videos.pexels.com/101.mp4"
    assert visual["sourcePageUrl"] == "https://www.pexels.com/video/101/"
    assert visual["sourceExternalId"] == "101"
    assert visual["creator"] == "Pexels Creator"
    assert visual["candidateCount"] == 4
    assert visual["selectionMethod"] == "operator-selected-from-candidates"
    assert visual["selectionKey"] == "scene-01:101"
    assert visual["selectedCandidateSummary"].startswith("Selected from four reviewed")
    assert manifest["bgmEnabled"] is False
    assert manifest["subtitleStyle"] == "minimal"


def test_grok_handoff_visual_source_reuses_existing_file_without_placeholder(tmp_path):
    source_path = Path("storage/grok-handoffs/runway/incoming/scene-01.mp4")
    source_file = tmp_path / source_path
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"grok-mp4")
    voice_path = Path("storage/uploads/scene-01.wav")
    voice_file = tmp_path / voice_path
    voice_file.parent.mkdir(parents=True, exist_ok=True)
    voice_file.write_bytes(b"voice")
    manifest = {
        "projectId": "grok-handoff-source-reuse",
        "cacheDir": "storage/inputs/grok-handoff-source-reuse",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Grok source reuse",
                "visualKind": "video",
                "cacheDir": "storage/inputs/grok-handoff-source-reuse/scene-01",
                "durationSec": 4,
                "route": "manual_clip",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "grok-handoff",
                "sourcePath": str(source_path).replace("\\", "/"),
                "outputPath": str(source_path).replace("\\", "/"),
                "sourceRecoveryReplacement": True,
            },
            {
                "provider": "operator-voice",
                "role": "audio",
                "sceneId": "scene-01",
                "kind": "voiceover",
                "sourceOrigin": "uploaded",
                "sourcePath": str(voice_path).replace("\\", "/"),
                "outputPath": str(voice_path).replace("\\", "/"),
            },
        ],
    }
    scene = manifest["scenes"][0]
    manifest_path = tmp_path / "render-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    plan = build_local_media_plan(manifest, manifest_path, project_root=tmp_path)
    assert plan.summary.uploadedVisuals == 1
    assert plan.summary.generationRequired == 0
    assert plan.scenes[0].visualSource == "uploaded"

    result = generate_local_visual_asset(
        manifest=manifest,
        manifest_path=manifest_path,
        scene=scene,
        project_root=tmp_path,
    )

    assert result.status == "uploaded"
    assert result.mode == "uploaded"
    assert result.outputPath == str(source_file)
    assert result.attempted is False
    assert result.succeeded is None
    assert "grok-handoff asset will be used" in result.detail


def test_selected_stock_visual_reuses_cached_mp4_before_network(tmp_path, monkeypatch):
    payload = save_project_bundle(
        prompt="manual cached stock short",
        budget_mode="free",
        availability=ProviderAvailability(),
        planner_mode="sample",
        project_id="cached-stock-test",
        project_root=tmp_path,
        draft_scenes=[
            {
                "sceneId": "scene-01",
                "title": "Cached stock hook",
                "narration": "A manually reviewed stock clip is already cached.",
                "display_text": "Cached stock",
                "image_source": "pexels-video",
                "duration": 4,
            }
        ],
        selected_pexels_videos={
            "scene-01": {
                "id": "101",
                "url": "https://videos.pexels.com/101.mp4",
                "sourceUrl": "https://www.pexels.com/video/101/",
            }
        },
    )
    manifest_path = Path(payload["saveResult"]["manifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scene = manifest["scenes"][0]
    visual = next(asset for asset in manifest["assets"] if asset["role"] == "visual")
    cached_mp4 = tmp_path / visual["outputPath"]
    cached_mp4.parent.mkdir(parents=True, exist_ok=True)
    cached_mp4.write_bytes(b"cached-selected-stock-mp4")
    cached_mp4.with_suffix(cached_mp4.suffix + ".source.json").write_text(
        json.dumps({
            "source": {
                "provider": visual["provider"],
                "sourceUrl": visual["sourceUrl"],
                "sourceExternalId": visual["sourceExternalId"],
            }
        }),
        encoding="utf-8",
    )

    def _unexpected_download(*_args, **_kwargs):
        raise AssertionError("cached selected stock should not be downloaded again")

    monkeypatch.setattr(image_router, "download_pexels_video", _unexpected_download)

    result = generate_local_visual_asset(
        manifest=manifest,
        manifest_path=manifest_path,
        scene=scene,
        project_root=tmp_path,
    )

    assert result.status == "generated"
    assert result.mode == "selected-stock"
    assert result.outputPath == str(cached_mp4)
    assert result.attempted is False
    assert result.succeeded is True


def test_selected_stock_visual_redownloads_when_cached_source_changes(tmp_path, monkeypatch):
    payload = save_project_bundle(
        prompt="manual changed stock short",
        budget_mode="free",
        availability=ProviderAvailability(),
        planner_mode="sample",
        project_id="changed-stock-test",
        project_root=tmp_path,
        draft_scenes=[
            {
                "sceneId": "scene-01",
                "title": "Changed stock hook",
                "narration": "The operator picked a better matching stock clip.",
                "display_text": "Changed stock",
                "image_source": "pexels-video",
                "duration": 4,
            }
        ],
        selected_pexels_videos={
            "scene-01": {
                "id": "202",
                "url": "https://videos.pexels.com/202.mp4",
                "sourceUrl": "https://www.pexels.com/video/202/",
            }
        },
    )
    manifest_path = Path(payload["saveResult"]["manifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scene = manifest["scenes"][0]
    visual = next(asset for asset in manifest["assets"] if asset["role"] == "visual")
    cached_mp4 = tmp_path / visual["outputPath"]
    cached_mp4.parent.mkdir(parents=True, exist_ok=True)
    cached_mp4.write_bytes(b"old-selected-stock-mp4")
    cached_mp4.with_suffix(cached_mp4.suffix + ".source.json").write_text(
        json.dumps({
            "source": {
                "provider": "pexels-video",
                "sourceUrl": "https://videos.pexels.com/101.mp4",
                "sourceExternalId": "101",
            }
        }),
        encoding="utf-8",
    )
    downloaded_urls: list[str] = []

    def _download_changed_stock(url: str, output_path: str):
        downloaded_urls.append(url)
        Path(output_path).write_bytes(b"new-selected-stock-mp4")
        return True

    monkeypatch.setattr(image_router, "download_pexels_video", _download_changed_stock)

    result = generate_local_visual_asset(
        manifest=manifest,
        manifest_path=manifest_path,
        scene=scene,
        project_root=tmp_path,
    )

    assert result.status == "generated"
    assert result.mode == "selected-stock"
    assert result.attempted is True
    assert result.succeeded is True
    assert downloaded_urls == ["https://videos.pexels.com/202.mp4"]
    assert cached_mp4.read_bytes() == b"new-selected-stock-mp4"
    source_sidecar = json.loads(cached_mp4.with_suffix(cached_mp4.suffix + ".source.json").read_text(encoding="utf-8"))
    assert source_sidecar["source"]["sourceUrl"] == "https://videos.pexels.com/202.mp4"
    assert source_sidecar["source"]["sourceExternalId"] == "202"


def test_create_scene_clip_loops_short_video_and_uses_narration_audio(monkeypatch, tmp_path):
    captured = {}

    def _capture_ffmpeg(_ffmpeg_path, args, _log_lines):
        captured["args"] = args

    monkeypatch.setattr(compose_ffmpeg, "run_ffmpeg", _capture_ffmpeg)

    compose_ffmpeg.create_scene_clip(
        ffmpeg_path="ffmpeg",
        visual_kind="video",
        visual_path=tmp_path / "short-source.mp4",
        audio_path=tmp_path / "narration.wav",
        clip_path=tmp_path / "clip.mp4",
        duration_sec=6.0,
        log_lines=[],
    )

    args = captured["args"]
    assert args[:4] == ["-y", "-stream_loop", "-1", "-i"]
    map_index = args.index("-map")
    assert args[map_index:map_index + 4] == ["-map", "0:v:0", "-map", "1:a:0"]
    video_filter = args[args.index("-vf") + 1]
    assert "flags=lanczos" in video_filter
    assert "unsharp=3:3:0.28:3:3:0.10" in video_filter
    assert "eq=contrast=1.025:saturation=1.030:gamma=1.010" in video_filter
    assert args[args.index("-preset") + 1] == "medium"
    assert args[args.index("-crf") + 1] == "18"
    assert args[args.index("-profile:v") + 1] == "high"
    assert str(tmp_path / "narration.wav") in args


def test_xfade_final_pass_applies_render_quality_filters(tmp_path):
    from worker.render.transitions import build_xfade_filter_complex

    result = build_xfade_filter_complex(
        clip_paths=[tmp_path / "clip-01.mp4", tmp_path / "clip-02.mp4"],
        durations=[3.2, 3.2],
        transition_type="fade",
        transition_duration=0.35,
        subtitle_file=tmp_path / "captions.ass",
    )

    assert result is not None
    _input_args, filter_complex = result
    assert "scale=1080:1920:flags=lanczos" in filter_complex
    assert "unsharp=3:3:0.18:3:3:0.06" in filter_complex
    assert "eq=contrast=1.010:saturation=1.010:gamma=1.005" in filter_complex
    assert "format=yuv420p[vout]" in filter_complex


def test_normalize_audio_duration_tempo_fits_long_tts_instead_of_hard_trim(monkeypatch, tmp_path):
    captured = {}
    log_lines = []

    def _capture_ffmpeg(_ffmpeg_path, args, _log_lines):
        captured["args"] = args

    monkeypatch.setattr(compose_ffmpeg, "_audio_duration_seconds", lambda *_args: 5.4)
    monkeypatch.setattr(compose_ffmpeg, "run_ffmpeg", _capture_ffmpeg)

    compose_ffmpeg.normalize_audio_duration(
        ffmpeg_path="ffmpeg",
        input_path=tmp_path / "slow-tts.wav",
        output_path=tmp_path / "fit.wav",
        duration_sec=4.5,
        log_lines=log_lines,
    )

    args = captured["args"]
    audio_filter = args[args.index("-af") + 1]
    assert audio_filter.startswith("atempo=1.20000,")
    assert "atrim=0:4.50" in audio_filter
    assert any("mode=tempo-fit" in line for line in log_lines)


def test_normalize_audio_duration_keeps_requested_ending_tail(monkeypatch, tmp_path):
    captured = {}
    log_lines = []

    def _capture_ffmpeg(_ffmpeg_path, args, _log_lines):
        captured["args"] = args

    monkeypatch.setattr(compose_ffmpeg, "_audio_duration_seconds", lambda *_args: 6.2)
    monkeypatch.setattr(compose_ffmpeg, "run_ffmpeg", _capture_ffmpeg)

    fit = compose_ffmpeg.normalize_audio_duration(
        ffmpeg_path="ffmpeg",
        input_path=tmp_path / "final-tts.wav",
        output_path=tmp_path / "fit.wav",
        duration_sec=7.8,
        voice_duration_sec=6.2,
        log_lines=log_lines,
    )

    args = captured["args"]
    audio_filter = args[args.index("-af") + 1]
    assert "atrim=0:7.80" in audio_filter
    assert fit["targetDurationSec"] == 7.8
    assert fit["voiceTargetDurationSec"] == 6.2
    assert fit["tailHoldSec"] == 1.6
    assert any("tail=1.60s" in line for line in log_lines)


def test_local_model_mp4_handoff_preserves_provider_and_source_intent(tmp_path):
    payload = save_project_bundle(
        prompt="manual local model short",
        budget_mode="free",
        availability=ProviderAvailability(),
        planner_mode="sample",
        project_id="local-handoff-test",
        project_root=tmp_path,
        draft_scenes=[
            {
                "sceneId": "scene-01",
                "scene_num": 1,
                "title": "Model hook",
                "narration": "The camera pushes through a neon alley.",
                "display_text": "Neon alley",
                "image_prompt": "consistent cyberpunk alley, slow dolly push",
                "image_source": "wan",
                "duration": 4,
                "upload_kind": "video",
                "caption_preset": "top-hook",
                "source_rationale": "Wan output keeps the same alley and camera move.",
                "continuity_note": "Neon magenta/cyan palette, wet pavement, no character swap.",
                "hook_note": "Start on a bright sign reflection in the first two seconds.",
                "grok_prompt": "Wan local prompt, 9:16 MP4, no baked-in text.",
            }
        ],
        scene_assets=[
            {
                "sceneId": "scene-01",
                "role": "visual",
                "fileName": "wan-alley.mp4",
                "mimeType": "video/mp4",
                "base64": base64.b64encode(b"fake mp4 bytes").decode("ascii"),
                "sourceGenerator": "wan",
                "sourceGeneratorRequestPath": "storage/local-video/local-handoff-test/scene-01/scene-01.wan.request.json",
                "sourceGeneratorPromptPath": "storage/local-video/local-handoff-test/scene-01/scene-01.wan.prompt.txt",
                "sourceGeneratorLogPath": "storage/local-video/local-handoff-test/scene-01/scene-01.wan.command.log",
                "sourceGeneratorCommand": "python wan.py --request scene-01.wan.request.json",
            }
        ],
    )

    manifest = json.loads(Path(payload["saveResult"]["manifestPath"]).read_text(encoding="utf-8"))
    scene = manifest["scenes"][0]
    visual = next(asset for asset in manifest["assets"] if asset["role"] == "visual")

    assert scene["visualKind"] == "video"
    assert scene["visualSourceIntent"] == "wan"
    assert scene["grokPrompt"].startswith("Wan local prompt")
    assert visual["provider"] == "wan"
    assert visual["sourceOrigin"] == "uploaded"
    assert visual["sourcePath"].endswith("uploads/scene-01/wan-alley.mp4")
    assert visual["sourceLabel"] == "wan local-model handoff: wan-alley.mp4"
    assert visual["sourceGenerator"] == "wan"
    assert visual["sourceGeneratorRequestPath"].endswith("scene-01.wan.request.json")
    assert visual["sourceGeneratorPromptPath"].endswith("scene-01.wan.prompt.txt")
    assert visual["sourceGeneratorLogPath"].endswith("scene-01.wan.command.log")
    assert visual["sourceGeneratorCommand"].startswith("python wan.py")


def test_caption_presets_skip_none_and_use_safe_layouts(tmp_path):
    out = tmp_path / "captions.ass"
    generate_ass_subtitle(
        words=[
            {"start_sec": 0, "end_sec": 2, "text": "Hidden", "caption_preset": "none"},
            {"start_sec": 2, "end_sec": 4, "text": "Hook", "caption_preset": "top-hook"},
            {"start_sec": 4, "end_sec": 6, "text": "Info", "caption_preset": "lower-info"},
        ],
        style_preset="minimal",
        highlight_mode="none",
        output_path=str(out),
    )

    content = out.read_text(encoding="utf-8")
    assert "Hidden" not in content
    assert "Dialogue: 0,0:00:02.00,0:00:03.35,TopHook" in content
    assert "Dialogue: 0,0:00:04.00,0:00:05.80,LowerInfo" in content
    assert "Style: LowerInfo" in content and ",2,72,170,540,1" in content


def test_top_hook_caption_is_large_short_and_animated(tmp_path):
    out = tmp_path / "captions.ass"
    generate_ass_subtitle(
        words=[
            {"start_sec": 0, "end_sec": 4.5, "text": "첫 2초에 향이 보인다", "caption_preset": "top-hook"},
        ],
        style_preset="minimal",
        highlight_mode="none",
        output_path=str(out),
    )

    content = out.read_text(encoding="utf-8")
    assert "Style: TopHook,Pretendard,78" in content
    assert "Style: CenterShort,Pretendard,64" in content
    assert "Style: LowerInfo,Pretendard,58" in content
    assert "Dialogue: 0,0:00:00.00,0:00:01.35,TopHook" in content
    assert "\\t(0,120,\\fscx112\\fscy112)" in content


def test_korean_punch_layout_uses_large_korean_text_without_visible_override_brace(tmp_path):
    out = tmp_path / "captions.ass"
    generate_ass_subtitle(
        words=[
            {
                "start_sec": 0,
                "end_sec": 3,
                "text": "폰 뒤집기",
                "caption_preset": "top-hook",
                "layout_variant_key": "korean-punch",
                "layout_variant_label": "폰 뒤집기",
                "layout_variant_y": 245,
            },
        ],
        style_preset="minimal",
        highlight_mode="none",
        output_path=str(out),
    )

    content = out.read_text(encoding="utf-8")
    assert "Style: KoreanPunch,Pretendard,118" in content
    assert "Dialogue: 4,0:00:00.04,0:00:01.49,KoreanPunch" in content
    assert ")}폰 뒤집기" in content
    assert ")}}폰 뒤집기" not in content


def test_korean_reference_caption_uses_sentence_length_two_line_safe_text(tmp_path):
    out = tmp_path / "captions.ass"
    generate_ass_subtitle(
        words=[
            {
                "start_sec": 0,
                "end_sec": 3,
                "text": "폰은 뒤집고 눈을 떼요",
                "caption_preset": "top-hook",
                "layout_variant_key": "korean-reference-caption",
                "layout_variant_y": 300,
                "layout_variant_max_chars": 8,
            },
        ],
        style_preset="minimal",
        highlight_mode="none",
        output_path=str(out),
    )

    content = out.read_text(encoding="utf-8")
    assert "Style: KoreanReference,Pretendard,88" in content
    assert "Dialogue: 4,0:00:00.04,0:00:01.99,KoreanReference" in content
    assert "폰은 뒤집고\\N눈을 떼요" in content
    assert ")}}폰은" not in content


def test_wrapped_ass_caption_uses_hard_newline_not_visible_backslash(tmp_path):
    out = tmp_path / "captions.ass"
    generate_ass_subtitle(
        words=[
            {
                "start_sec": 0,
                "end_sec": 3,
                "text": "오늘 밤 루틴을 5개로 줄입니다",
                "caption_preset": "top-hook",
            },
        ],
        style_preset="minimal",
        highlight_mode="none",
        output_path=str(out),
    )

    content = out.read_text(encoding="utf-8")
    assert "5개로" + "\\N" + "줄입니다" in content
    assert "5개로" + "\\\\N" + "줄입니다" not in content


def test_layout_variant_keys_render_distinct_ass_layers(tmp_path):
    out = tmp_path / "captions.ass"
    generate_ass_subtitle(
        words=[
            {
                "start_sec": 0,
                "end_sec": 5,
                "title": "3. 손이 보여야 진짜 같다",
                "text": "3. 손이 보여야 진짜 같다",
                "caption_preset": "lower-info",
                "layout_variant_key": "rank-countdown",
                "layout_variant_label": "rank countdown",
            },
            {
                "start_sec": 5,
                "end_sec": 10,
                "title": "빗속에서 멈춘 사람",
                "text": "우산을 다시 펼쳤다",
                "caption_preset": "top-hook",
                "layout_variant_key": "character-continuity",
                "layout_variant_label": "same character payoff",
            },
            {
                "start_sec": 10,
                "end_sec": 16,
                "title": "왜 이 장면이 남는가",
                "text": "원본 카드와 증거 컷을 분리한다",
                "caption_preset": "lower-info",
                "layout_variant_key": "chapter-evidence",
                "layout_variant_label": "chapter evidence",
            },
        ],
        style_preset="minimal",
        highlight_mode="none",
        output_path=str(out),
    )

    content = out.read_text(encoding="utf-8")
    assert "Style: RankBadge" in content
    assert "Style: RankTitle" in content
    assert "Style: StoryHook" in content
    assert "Style: ChapterKicker" in content
    assert "Style: ChapterTitle" in content
    assert "Dialogue: 3,0:00:00.00,0:00:01.35,RankBadge" in content
    assert "#3" in content
    assert "Dialogue: 2,0:00:05.00,0:00:06.55,StoryHook" in content
    assert "Dialogue: 3,0:00:10.00,0:00:11.25,ChapterKicker" in content


def test_routine_layout_variants_render_distinct_safe_layers(tmp_path):
    out = tmp_path / "captions.ass"
    generate_ass_subtitle(
        words=[
            {
                "start_sec": 0,
                "end_sec": 4,
                "title": "퇴근길 불빛",
                "text": "어깨 끈을 천천히 푼다",
                "caption_preset": "top-hook",
                "layout_variant_key": "routine-top-hook",
            },
            {
                "start_sec": 4,
                "end_sec": 8,
                "title": "손으로 저녁 시작",
                "text": "칼 대신 손이 먼저 보인다",
                "caption_preset": "lower-info",
                "layout_variant_key": "routine-lower-info",
                "layout_variant_note": "소리보다 손동작",
            },
        ],
        style_preset="minimal",
        highlight_mode="none",
        output_path=str(out),
    )

    content = out.read_text(encoding="utf-8")
    assert "Style: RoutineStep,Pretendard,44" in content
    assert "Style: RoutineHook,Pretendard,84" in content
    assert "Style: RoutineLower,Pretendard,62" in content
    assert "Style: RoutineDetail,Pretendard,46" in content
    assert "Dialogue: 3,0:00:00.00,0:00:01.10,RoutineStep" in content
    assert "Dialogue: 2,0:00:00.08,0:00:01.70,RoutineHook" in content
    assert "Dialogue: 1,0:00:01.28,0:00:02.50,RoutineDetail" in content
    assert "Dialogue: 3,0:00:04.00,0:00:05.05,RoutineStep" in content
    assert "Dialogue: 2,0:00:04.12,0:00:05.92,RoutineLower" in content
    assert "Dialogue: 1,0:00:05.34,0:00:06.50,RoutineDetail" in content
    assert "Dialogue: 0,0:00:06.05,0:00:07.10,RoutineDetail" in content
    assert "Style: RoutineLower,Pretendard,62" in content and ",1,78,210,690,1" in content
    dialogue_text = "\n".join(
        line.rsplit(",,", 1)[-1] for line in content.splitlines() if line.startswith("Dialogue:")
    )
    assert "어깨 끈을 천천히" in dialogue_text
    assert "푼다" in dialogue_text


def test_layout_variant_note_filters_production_meta_from_screen_text(tmp_path):
    out = tmp_path / "captions.ass"
    generate_ass_subtitle(
        words=[
            {
                "start_sec": 0,
                "end_sec": 4,
                "title": "집에 들어오면 물 먼저",
                "text": "물 한 컵으로 전환",
                "caption_preset": "lower-info",
                "layout_variant_key": "routine-lower-info",
                "layout_variant_note": "Caption safe: avoid y>1536 danger zone and don't cover 피사체",
            }
        ],
        style_preset="minimal",
        highlight_mode="none",
        output_path=str(out),
    )

    content = out.read_text(encoding="utf-8")
    dialogue_text = "\n".join(
        line.rsplit(",,", 1)[-1] for line in content.splitlines() if line.startswith("Dialogue:")
    )
    assert "Caption safe" not in dialogue_text
    assert "danger zone" not in dialogue_text
    assert "피사체" not in dialogue_text
    assert "물 한 컵으로 전환" in dialogue_text


def test_grok_first_layout_variants_render_viewer_captions_only(tmp_path):
    out = tmp_path / "captions.ass"
    generate_ass_subtitle(
        words=[
            {
                "start_sec": 0,
                "end_sec": 4,
                "title": "문이 열리는 순간",
                "text": "첫 1초에 손이 움직인다",
                "caption_preset": "top-hook",
                "layout_variant_key": "grok-first-hook",
                "layout_variant_note": "첫 프레임에 손동작",
            },
            {
                "start_sec": 4,
                "end_sec": 8,
                "title": "같은 가방",
                "text": "불빛만 바뀌고 인물은 유지",
                "caption_preset": "lower-info",
                "layout_variant_key": "grok-first-continuity",
                "layout_variant_note": "코트와 가방 유지",
            },
            {
                "start_sec": 8,
                "end_sec": 12,
                "title": "소품 확인",
                "text": "책상 위 빨간 노트",
                "caption_preset": "center-short",
                "layout_variant_key": "grok-first-proof",
                "layout_variant_note": "손이 노트 옆을 지난다",
            },
        ],
        style_preset="minimal",
        highlight_mode="none",
        output_path=str(out),
    )

    content = out.read_text(encoding="utf-8")
    assert "Style: GrokHook,Pretendard,84" in content
    assert "Style: GrokLower,Pretendard,64" in content and ",1,78,220,690,1" in content
    assert "Style: GrokContinuity,Pretendard,68" in content
    assert "Style: GrokProof,Pretendard,46" in content and ",1,78,220,430,1" in content
    assert "Dialogue: 4,0:00:00.00,0:00:01.05,ChapterKicker" in content
    assert "Dialogue: 3,0:00:00.06,0:00:01.41,GrokHook" in content
    assert "Dialogue: 2,0:00:00.72,0:00:02.42,GrokLower" not in content
    assert "Dialogue: 1,0:00:01.55,0:00:02.70,GrokProof" not in content
    assert "Dialogue: 4,0:00:04.00,0:00:05.05,ChapterKicker" in content
    assert "Dialogue: 2,0:00:04.06,0:00:05.41,GrokContinuity" in content
    assert "Dialogue: 1,0:00:04.75,0:00:06.45,GrokLower" in content
    assert "Dialogue: 0,0:00:05.65,0:00:06.90,GrokProof" not in content
    assert "Dialogue: 4,0:00:08.00,0:00:09.05,ChapterKicker" in content
    assert "Dialogue: 2,0:00:08.00,0:00:09.25,GrokProof" in content
    assert "Dialogue: 1,0:00:08.90,0:00:10.45,GrokLower" in content
    assert "Dialogue: 0,0:00:10.05,0:00:11.10,GrokProof" not in content
    dialogue_text = "\n".join(
        line.rsplit(",,", 1)[-1] for line in content.splitlines() if line.startswith("Dialogue:")
    )
    normalized_dialogue_text = dialogue_text.replace("\\N", " ")
    assert "Grok" not in dialogue_text
    assert "첫 1초에 손이 움직인다" in normalized_dialogue_text
    assert "문이 열리는 순간" not in dialogue_text
    assert "첫 프레임에 손동작" not in dialogue_text
    assert "코트와 가방 유지" not in dialogue_text
    assert "손이 노트 옆을 지난다" not in dialogue_text


def test_rank_layout_uses_title_rank_when_caption_text_has_no_number(tmp_path):
    out = tmp_path / "captions.ass"
    generate_ass_subtitle(
        words=[
            {
                "start_sec": 0,
                "end_sec": 5,
                "title": "5. 퇴근길 속도 낮추기",
                "text": "오늘은 집 가는 속도부터 낮춘다",
                "caption_preset": "lower-info",
                "layout_variant_key": "rank-countdown",
                "layout_variant_label": "rank countdown",
            }
        ],
        style_preset="minimal",
        highlight_mode="none",
        output_path=str(out),
    )

    content = out.read_text(encoding="utf-8")
    assert "#5" in content
    assert "#1" not in content
    assert "퇴근길 속도 낮추기" in content


def test_project_subtitles_preserves_layout_variant_metadata(tmp_path):
    out = tmp_path / "captions.srt"
    compose_ffmpeg.write_project_subtitles(
        out,
        [
            {
                "startSec": 0,
                "endSec": 5,
                "title": "2. 화면이 달라져야 한다",
                "subtitleText": "2. 화면이 달라져야 한다",
                "captionPreset": "lower-info",
                "layoutVariantKey": "rank-countdown",
                "layoutVariantLabel": "rank countdown",
                "layoutVariantNote": "rank badge plus proof chip",
            }
        ],
        subtitle_style="ranking",
    )

    content = out.with_suffix(".ass").read_text(encoding="utf-8")
    assert "Style: RankBadge" in content
    assert "Dialogue: 3,0:00:00.00,0:00:01.35,RankBadge" in content
    assert "Dialogue: 2,0:00:00.08,0:00:01.93,RankTitle" in content


def test_rank_layout_uses_title_rank_when_display_text_has_no_number(tmp_path):
    out = tmp_path / "captions.ass"
    generate_ass_subtitle(
        words=[
            {
                "start_sec": 0,
                "end_sec": 4,
                "title": "5. 퇴근길 속도 낮추기",
                "text": "오늘은 집 가는 속도부터 낮춘다",
                "caption_preset": "top-hook",
                "layout_variant_key": "rank-countdown",
            }
        ],
        style_preset="minimal",
        highlight_mode="none",
        output_path=str(out),
    )

    content = out.read_text(encoding="utf-8")
    assert "#5" in content
    assert "#1" not in content


def test_bgm_final_mix_keeps_music_audible(monkeypatch, tmp_path):
    captured = {}

    def fake_run_ffmpeg(ffmpeg_path, args, log_lines, cwd=None):
        captured["ffmpeg_path"] = ffmpeg_path
        captured["args"] = args
        captured["log_lines"] = log_lines
        captured["cwd"] = cwd

    monkeypatch.setattr(compose_ffmpeg, "run_ffmpeg", fake_run_ffmpeg)

    compose_ffmpeg.mix_bgm_into_output(
        ffmpeg_path="ffmpeg",
        video_path=tmp_path / "pre-bgm.mp4",
        bgm_path=tmp_path / "bgm-prepared.wav",
        output_path=tmp_path / "out.mp4",
        log_lines=[],
    )

    filter_complex = captured["args"][captured["args"].index("-filter_complex") + 1]
    assert "volume=0.550" in filter_complex
    assert "threshold=0.080" in filter_complex
    assert "ratio=2.60" in filter_complex
    assert "release=180" in filter_complex


def test_final_audio_loudness_normalization_uses_shorts_targets(monkeypatch, tmp_path):
    captured = {}

    def fake_run_ffmpeg(ffmpeg_path, args, log_lines, cwd=None):
        captured["ffmpeg_path"] = ffmpeg_path
        captured["args"] = args
        Path(args[-1]).write_bytes(b"normalized")

    monkeypatch.setattr(compose_ffmpeg, "run_ffmpeg", fake_run_ffmpeg)

    output_path = tmp_path / "out.mp4"
    output_path.write_bytes(b"original")
    log_lines = []

    applied = compose_ffmpeg.normalize_final_audio_loudness(
        ffmpeg_path="ffmpeg",
        video_path=output_path,
        output_path=output_path,
        log_lines=log_lines,
    )

    audio_filter = captured["args"][captured["args"].index("-af") + 1]
    assert applied is True
    assert "loudnorm=I=-14.0:TP=-1.5:LRA=11.0" in audio_filter
    assert "alimiter=limit=0.631:attack=5.0:release=50.0:level=false" in audio_filter
    assert captured["args"][captured["args"].index("-c:v") + 1] == "copy"
    assert captured["args"][captured["args"].index("-ar") + 1] == "48000"
    assert output_path.read_bytes() == b"normalized"
    assert (tmp_path / "out.pre-loudnorm.mp4").exists()
    assert any(line.startswith("audio_loudnorm=applied") for line in log_lines)
    assert any(line.startswith("audio_peak_limiter=applied TP=-4.0") for line in log_lines)


def test_final_outro_fade_applies_video_and_audio_fade(monkeypatch, tmp_path):
    captured = {}

    def fake_run_ffmpeg(ffmpeg_path, args, log_lines, cwd=None):
        captured["ffmpeg_path"] = ffmpeg_path
        captured["args"] = args
        Path(args[-1]).write_bytes(b"faded")

    monkeypatch.setattr(compose_ffmpeg, "_media_duration_seconds", lambda *_args: 20.0)
    monkeypatch.setattr(compose_ffmpeg, "run_ffmpeg", fake_run_ffmpeg)

    output_path = tmp_path / "out.mp4"
    output_path.write_bytes(b"original")
    log_lines = []

    applied = compose_ffmpeg.apply_final_outro_fade(
        ffmpeg_path="ffmpeg",
        video_path=output_path,
        output_path=output_path,
        fade_out_sec=0.9,
        log_lines=log_lines,
    )

    video_filter = captured["args"][captured["args"].index("-vf") + 1]
    audio_filter = captured["args"][captured["args"].index("-af") + 1]
    assert applied is True
    assert "fade=t=out:st=19.100:d=0.900:color=black" in video_filter
    assert "afade=t=out:st=19.100:d=0.900" in audio_filter
    assert output_path.read_bytes() == b"faded"
    assert (tmp_path / "out.pre-outro-fade.mp4").exists()
    assert any(line.startswith("final_outro_fade=applied") for line in log_lines)


def test_render_quality_report_records_pipeline_checks(tmp_path):
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "qa-test",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Steam hook",
                "subtitleText": "First sip",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this clip for visible steam motion.",
                "continuityNote": "Warm cafe palette and slow camera move.",
                "hookNote": "Steam rises in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "missing.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["noPlaceholders"]["status"] == "pass"
    assert report["checks"]["movingClipPriority"]["status"] == "pass"
    assert report["checks"]["sourceMotionEvidence"]["status"] == "warn"
    assert report["sourceMotionEvidence"]["status"] == "unavailable"
    assert report["checks"]["zeroPaidProviders"]["status"] == "pass"
    assert report["checks"]["subtitleArtifact"]["status"] == "pass"
    assert report["checks"]["manualSelectionEvidence"]["status"] == "pass"
    assert report["checks"]["continuityEvidence"]["status"] == "pass"
    assert report["checks"]["firstTwoSecondHook"]["status"] == "pass"
    assert report["checks"]["cutDensityPacing"]["status"] == "pass"
    assert report["checks"]["aiSlopVisualFit"]["status"] == "warn"
    assert report["checks"]["stockAiClipFit"]["status"] == "warn"
    assert report["checks"]["thumbnailFirstFrameStrength"]["status"] == "warn"
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "pass"
    assert report["checks"]["captionLayoutReview"]["status"] == "pass"
    assert report["checks"]["assetReuseDiversity"]["status"] == "pass"
    assert report["checks"]["sourceFirstSourceGate"]["status"] == "pass"
    assert report["checks"]["stockOnlyCaveat"]["status"] == "pass"
    assert report["checks"]["outputSpec"]["status"] == "fail"
    assert report["checks"]["publishReadinessGate"]["status"] == "fail"
    assert report["publishReadiness"]["status"] == "blocked"
    assert report["publishReadiness"]["requiredFixes"]
    assert report["gateSystem"]["systemVersion"] == "2026-06-08-unified-quality-gate-system-v1"
    assert report["gateSystem"]["surface"] == "render-quality-report"
    assert report["gateSystem"]["blockingPhaseKey"] == "render-quality"
    assert report["gateSystem"]["renderQualitySummary"]["checkCount"] == 53
    assert "outputSpec" in report["gateSystem"]["renderQualitySummary"]["failedOrMissingKeys"]
    assert report["productionReview"]["summary"]["uploadedVideoScenes"] == 1
    assert report["productionReview"]["scenes"][0]["sourceRationale"].startswith("Operator selected")


def test_render_quality_report_blocks_quality_iteration_without_ratchet(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "quality-ratchet-missing",
        "qualityIteration": "v27-source-rebuild",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "New hook source",
                "subtitleText": "First action",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected a new source because the prior baseline felt generic.",
                "continuityNote": "Same subject distance and natural handheld camera language.",
                "hookNote": "Visible action starts in the first second.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "quality-ratchet-missing.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    ratchet = report["qualityRatchet"]
    assert ratchet["required"] is True
    assert ratchet["status"] == "fail"
    assert ratchet["missingFields"] == [
        "previousBaseline",
        "rejectionCause",
        "changedLever",
        "expectedVisibleImprovement",
        "actualProof",
        "nextRatchet",
    ]
    assert report["checks"]["qualityRatchet"]["status"] == "fail"
    assert any("previousBaseline" in item for item in report["publishReadiness"]["requiredFixes"])


def test_render_quality_report_accepts_complete_quality_ratchet(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "quality-ratchet-complete",
        "qualityIteration": "v27-source-rebuild",
        "qualityRatchet": {
            "previousBaseline": "v26-render-polish final MP4 rejected at phone size.",
            "rejectionCause": "Opening source still read as generic AI footage and did not answer the viewer question.",
            "changedLever": ["source", "storyboard", "caption-layout"],
            "expectedVisibleImprovement": "The first second should show a concrete action instead of a static desk montage.",
            "actualProof": {
                "renderPath": "storage/renders/quality-ratchet-complete/v27.mp4",
                "contactSheet": "storage/qa/quality-ratchet-complete/contact-sheet.jpg",
                "phoneReview": "operator compared v26 and v27 at phone size",
            },
            "nextRatchet": "If still weak, replace scene-01 source before changing FFmpeg again.",
        },
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "New hook source",
                "subtitleText": "First action",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected a new source because the prior baseline felt generic.",
                "continuityNote": "Same subject distance and natural handheld camera language.",
                "hookNote": "Visible action starts in the first second.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "quality-ratchet-complete.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    ratchet = report["qualityRatchet"]
    assert ratchet["required"] is True
    assert ratchet["status"] == "pass"
    assert ratchet["missingFields"] == []
    assert ratchet["viewerFacingLever"] is True
    assert "source" in ratchet["viewerFacingTerms"]
    assert report["checks"]["qualityRatchet"]["status"] == "pass"
    quality_criterion = next(item for item in report["publishReadiness"]["criteria"] if item["key"] == "qualityRatchet")
    assert quality_criterion["status"] == "pass"


def test_render_quality_report_blocks_single_video_quality_sample_set(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "single-video-quality-claim",
        "qualitySampleSetRequired": True,
        "qualitySampleSet": {
            "minAcceptedSamples": 2,
            "samples": [
                {
                    "projectId": "single-video-quality-claim",
                    "status": "accepted",
                    "topic": "one proof topic",
                    "sourceFamilies": ["gif", "image"],
                    "mp4Path": "storage/renders/single-video-quality-claim/out.mp4",
                    "contactSheetPath": "storage/renders/single-video-quality-claim/contact.jpg",
                    "renderQualityStatus": "pass",
                    "warnCount": 0,
                    "humanVisualVerdict": "pass",
                    "sourceIntentVerdict": "pass",
                    "captionTtsVerdict": "pass",
                    "layoutVerdict": "pass",
                    "endingVerdict": "pass",
                }
            ],
        },
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "One proof",
                "subtitleText": "One proof",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this clip for visible motion.",
                "continuityNote": "Same source topic throughout.",
                "hookNote": "Visible source appears in the first second.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            }
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "single-video-quality-claim.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    sample_set = report["qualitySampleSet"]
    assert sample_set["status"] == "fail"
    assert "acceptedSamples>=2" in sample_set["missingFields"]
    assert "rejectedBaselines>=1" in sample_set["missingFields"]
    single_sample_issue = next(
        field for field in sample_set["missingFields"] if field.startswith("single-video-quality-claim:")
    )
    assert "mp4PathExists" in single_sample_issue
    assert "contactSheetPathExists" in single_sample_issue
    assert "audienceInterestVerdict=pass" in single_sample_issue
    assert report["checks"]["audienceInterestSourceFit"]["status"] == "fail"
    assert report["checks"]["qualitySampleSet"]["status"] == "fail"
    assert report["gateSystem"]["status"] == "blocked"


def test_render_quality_report_accepts_multi_video_quality_sample_set(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")

    sample_artifacts = [
        ("old-apollo-proof", tmp_path / "storage" / "renders" / "old-apollo-proof"),
        ("second-accepted-proof", tmp_path / "storage" / "renders" / "second-accepted-proof"),
        ("muybridge-proof", tmp_path / "storage" / "renders" / "muybridge-proof"),
    ]
    for _sample_id, sample_dir in sample_artifacts:
        sample_dir.mkdir(parents=True)
        (sample_dir / "out.mp4").write_bytes(b"fake mp4")
        (sample_dir / "contact.jpg").write_bytes(b"fake jpg")

    accepted_common = {
        "status": "accepted",
        "renderQualityStatus": "pass",
        "warnCount": 0,
        "audienceInterestVerdict": "pass",
        "audienceInterestScore": 4,
        "interestEvidence": "Search/social evidence shows viewers stop for surprising source-first visual proofs, not generic AI renders.",
        "uniqueSourceCount": 2,
        "duplicateSourceCount": 0,
        "humanVisualVerdict": "pass",
        "sourceIntentVerdict": "pass",
        "captionTtsVerdict": "pass",
        "captionTtsHumanVerdict": "pass",
        "captionTtsReview": "Caption and TTS were reviewed together at phone playback size; the spoken line lands inside the scene duration and matches the visible caption beat.",
        "motionStabilityVerdict": "pass",
        "motionStabilityReview": "The source motion is stable on playback with no artificial shake, floating zoom, or camera wobble introduced by the render.",
        "sourceRepetitionVerdict": "pass",
        "sourceRepetitionReview": "Repeated source use is either avoided or assigned a new scene purpose so the viewer does not see the same image recycled as filler.",
        "layoutVerdict": "pass",
        "endingVerdict": "pass",
    }
    manifest = {
        "projectId": "second-accepted-proof",
        "audienceInterest": {
            "targetAudience": "Korean Shorts viewers who stop for surprising visual proof clips",
            "interestDriver": "The hook promises a visible one-shot proof instead of another generic AI explainer.",
            "whyNowOrEvergreen": "AI-looking Shorts are common, so real source proof is the differentiator viewers can notice immediately.",
            "interestEvidence": "Operator review compares this against source-first visual proof Shorts and rejects generic AI-looking topics.",
            "evidenceItems": [
                {
                    "source": "Operator source review",
                    "signal": "Specific source-first proof clips held attention when the first frame posed a visible challenge.",
                    "relevance": "The sample-set proof must choose a viewer task before it chooses GIF or still sources.",
                },
                {
                    "source": "Render comparison notes",
                    "signal": "Generic AI-looking topics were rejected when the source did not prove the hook.",
                    "relevance": "The accepted sample needs source-led curiosity, not a broad trending claim.",
                },
            ],
            "scrollStopHook": "잠깐, 이건 진짜 소스로 보이네?",
            "sourceStrategy": "Use a fetched moving source for the proof beat and a still source only when the still frame clarifies the setup or payoff.",
            "commentPrompt": "Viewers can argue whether the source actually proves the claim.",
            "interestScore": 4,
            "audienceInterestVerdict": "pass",
        },
        "qualitySampleSetRequired": True,
        "qualitySampleSet": {
            "minAcceptedSamples": 2,
            "minRejectedBaselines": 1,
            "samples": [
                {
                    "projectId": "old-apollo-proof",
                    "status": "rejected",
                    "topic": "moon hammer feather",
                    "visibleFailure": "Gate pass did not make the GIF loop feel natural.",
                    "rejectionCause": "Only one proof and no sample diversity.",
                    "mp4Path": "storage/renders/old-apollo-proof/out.mp4",
                    "contactSheetPath": "storage/renders/old-apollo-proof/contact.jpg",
                    "humanVisualVerdict": "fail",
                },
                {
                    **accepted_common,
                    "projectId": "second-accepted-proof",
                    "topic": "moon hammer feather v2",
                    "sourceFamilies": ["gif", "image"],
                    "mp4Path": "storage/renders/second-accepted-proof/out.mp4",
                    "contactSheetPath": "storage/renders/second-accepted-proof/contact.jpg",
                },
                {
                    **accepted_common,
                    "projectId": "muybridge-proof",
                    "topic": "horse in motion",
                    "sourceFamilies": ["gif", "still"],
                    "mp4Path": "storage/renders/muybridge-proof/out.mp4",
                    "contactSheetPath": "storage/renders/muybridge-proof/contact.jpg",
                },
            ],
        },
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Second proof",
                "subtitleText": "Second proof",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this clip for visible motion.",
                "continuityNote": "Same source topic throughout.",
                "hookNote": "Visible source appears in the first second.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            }
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "second-accepted-proof.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    sample_set = report["qualitySampleSet"]
    assert sample_set["status"] == "pass"
    assert sample_set["acceptedSampleIds"] == ["second-accepted-proof", "muybridge-proof"]
    assert sample_set["rejectedBaselineIds"] == ["old-apollo-proof"]
    assert sample_set["acceptedTopicCount"] == 2
    assert sample_set["currentProjectIncluded"] is True
    assert sample_set["missingFields"] == []
    assert report["checks"]["qualitySampleSet"]["status"] == "pass"


def test_quality_sample_set_blocks_accepted_sample_without_human_playback_review(tmp_path):
    for sample_id in ("baseline-proof", "current-proof", "second-proof"):
        sample_dir = tmp_path / "storage" / "renders" / sample_id
        sample_dir.mkdir(parents=True)
        (sample_dir / "out.mp4").write_bytes(b"fake mp4")
        (sample_dir / "contact.jpg").write_bytes(b"fake jpg")

    accepted_common = {
        "status": "accepted",
        "sourceFamilies": ["gif", "image"],
        "mp4Path": "storage/renders/current-proof/out.mp4",
        "contactSheetPath": "storage/renders/current-proof/contact.jpg",
        "renderQualityStatus": "pass",
        "warnCount": 0,
        "audienceInterestVerdict": "pass",
        "audienceInterestScore": 4,
        "interestEvidence": "Concrete source and audience evidence explain why viewers would stop for this proof.",
        "uniqueSourceCount": 1,
        "duplicateSourceCount": 1,
        "humanVisualVerdict": "pass",
        "sourceIntentVerdict": "pass",
        "captionTtsVerdict": "pass",
        "layoutVerdict": "pass",
        "endingVerdict": "pass",
    }
    review = compose_ffmpeg._build_quality_sample_set_review(
        {
            "projectId": "current-proof",
            "qualitySampleSetRequired": True,
            "qualitySampleSet": {
                "samples": [
                    {
                        "projectId": "baseline-proof",
                        "status": "rejected",
                        "topic": "old weak proof",
                        "visibleFailure": "Playback had visible shake and poor caption/TTS sync.",
                        "mp4Path": "storage/renders/baseline-proof/out.mp4",
                        "contactSheetPath": "storage/renders/baseline-proof/contact.jpg",
                        "humanVisualVerdict": "fail",
                    },
                    {
                        **accepted_common,
                        "projectId": "current-proof",
                        "topic": "current proof",
                    },
                    {
                        **accepted_common,
                        "projectId": "second-proof",
                        "topic": "second proof",
                        "mp4Path": "storage/renders/second-proof/out.mp4",
                        "contactSheetPath": "storage/renders/second-proof/contact.jpg",
                    },
                ]
            },
        },
        project_root=tmp_path,
    )

    assert review["status"] == "fail"
    current_issue = next(field for field in review["missingFields"] if field.startswith("current-proof:"))
    assert "captionTtsHumanVerdict=pass" in current_issue
    assert "motionStabilityVerdict=pass" in current_issue
    assert "sourceRepetitionVerdict=pass" in current_issue
    assert "uniqueSourceCount>=2" in current_issue
    assert "intentionalSourceRepeatVerdict=pass" in current_issue
    assert "captionTtsReview>=48" in current_issue
    assert "motionStabilityReview>=48" in current_issue
    assert "sourceRepetitionReview>=48" in current_issue


def test_upload_candidate_blocks_local_only_and_missing_naturalness_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "local-only-upload-candidate",
        "renderPurpose": "upload-candidate",
        "uploadCandidate": True,
        "providerConsistencyMode": "local-only",
        "templateType": "authentic_vlog",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Desk start",
                "subtitleText": "Start smaller.",
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Local model fallback was used for a quick proof.",
                "continuityNote": "Same desk and light.",
                "hookNote": "The hand moves first.",
                "qualityReviewNote": "Subject remains visible.",
                "visualQualityVerdict": "pass",
                "visualSourceIntent": "wan",
            },
        ],
        "assets": [
            {
                "provider": "wan",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceGenerator": "wan",
                "sourceGeneratorRequestPath": "storage/local/request.json",
                "sourceGeneratorPromptPath": "storage/local/prompt.txt",
                "sourceGeneratorLogPath": "storage/local/log.txt",
            },
            {
                "provider": "local-bgm",
                "role": "audio",
                "sceneId": "global",
                "kind": "bgm",
                "sourceOrigin": "local-library",
                "sourcePath": "assets/bgm/calm/local.mp3",
                "sourceLabel": "Local Forecast - Elevator",
                "sourceUrl": "https://example.test/local-forecast",
                "sourceLicense": "local reusable music library",
                "candidateCount": 2,
                "selectionMethod": "stable-hash",
                "selectionKey": "local-only-upload-candidate",
            },
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "local-only.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["qualityRatchet"]["required"] is True
    assert report["checks"]["providerConsistency"]["status"] == "fail"
    assert "local-only is not allowed" in report["checks"]["providerConsistency"]["detail"]
    assert report["checks"]["antiAiNaturalness"]["status"] == "fail"
    assert report["checks"]["captionSystem"]["status"] == "fail"
    assert report["checks"]["viewerTakeaway"]["status"] == "fail"
    assert report["checks"]["qualityRatchet"]["status"] == "fail"
    assert report["publishReadiness"]["status"] == "blocked"
    assert any("Grok-only or Gemini-only" in item for item in report["publishReadiness"]["requiredFixes"])


def test_upload_candidate_accepts_grok_only_naturalness_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    scenes = []
    assets = []
    for idx, purpose in enumerate(("hook", "action"), start=1):
        scene_id = f"scene-{idx:02d}"
        scenes.append(
            {
                "sceneId": scene_id,
                "title": f"Natural beat {idx}",
                "subtitleText": "물 한 컵만 먼저" if idx == 1 else "첫 줄만 적기",
                "visualKind": "video",
                "captionPreset": "lower-info",
                "captionDisplayDurationSec": 1.4,
                "captionPurpose": purpose,
                "sourceRationale": "Selected Grok handoff take because the first second shows a real hand action with no generic montage.",
                "continuityNote": "Same Korean office desk, same notebook scale, same morning light, and restrained handheld phone framing.",
                "worldContinuityNote": "The desk, cup, notebook, hand distance, and natural light stay in the same believable world.",
                "actionMotivation": "The hand acts because the routine starts with one physical object before work.",
                "naturalnessReviewNote": "Phone-sized review says this does not read like a glossy AI ad sample; the motion is ordinary, imperfect, and tied to the desk routine.",
                "antiAiNaturalnessVerdict": "pass",
                "hookNote": "The hand action starts in the first second and gives the viewer a concrete routine cue.",
                "originalityEvidence": "Grok app/web MP4 imported through browser-control proof with prompt and selected-file evidence.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Use a frame where the hand and object state are readable without large text.",
                "audioMixReviewNote": "No-voice BGM stays under the visual action and does not fight captions.",
                "platformComparisonNote": "Compared against quiet Korean routine Shorts for restrained captions, first-second action, and phone-safe framing.",
                "layoutVariantKey": "grok-first-proof",
                "selectedFileName": f"{scene_id}.grok.mp4",
                "selectedCandidateSummary": "Take 2 is less glossy than take 1 and keeps the action readable at phone size.",
                "sourceReviewVerdict": "pass",
                "visualSourceIntent": "grok",
                "audioDesignMode": "no-voice",
                "visualLedNoVoiceApproved": True,
                "endingPurpose": "payoff" if idx == 2 else "",
                "endingPacingReview": (
                    "Final no-voice desk beat closes the routine with one small action and no abrupt caption-only stop."
                    if idx == 2
                    else ""
                ),
                "finalTakeawayReview": (
                    "Viewer leaves understanding that the morning routine works because it starts with one concrete desk action."
                    if idx == 2
                    else ""
                ),
                "endingVerdict": "pass" if idx == 2 else "",
            }
        )
        assets.append(
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": scene_id,
                "kind": "video",
                "sourceOrigin": "grok-handoff",
                "sourcePath": f"storage/grok-handoffs/natural/{scene_id}.grok.mp4",
                "sourceGenerator": "grok-app-web-handoff",
                "selectedFileName": f"{scene_id}.grok.mp4",
                "candidateCount": 2,
                "sourceProvenance": {
                    "status": "browser-native-original-download",
                    "acceptAsGrokMainSource": True,
                },
            }
        )
    assets.append(
        {
            "provider": "local-bgm",
            "role": "audio",
            "sceneId": "global",
            "kind": "bgm",
            "sourceOrigin": "local-library",
            "sourcePath": "assets/bgm/calm/local-forecast-elevator.mp3",
            "sourceLabel": "Local Forecast - Elevator",
            "sourceUrl": "https://example.test/local-forecast-elevator",
            "sourceLicense": "local reusable music library",
            "candidateCount": 2,
            "selectionMethod": "stable-hash",
            "selectionKey": "grok-only-naturalness-contract",
        }
    )
    manifest = {
        "projectId": "grok-only-naturalness-contract",
        "renderPurpose": "upload-candidate",
        "uploadCandidate": True,
        "providerConsistencyMode": "grok-only",
        "sourceFirstRequired": True,
        "templateType": "authentic_vlog",
        "audioDesignMode": "no-voice",
        "captionSystem": {
            "fixedPreset": "lower-info",
            "purposeByScene": {"scene-01": "hook", "scene-02": "action"},
        },
        "viewerTakeaway": {
            "understood": "A rushed morning can be stabilized by one small desk action.",
            "action": "Put water beside the notebook and write only the first task.",
            "feeling": "Calmer start, less automated productivity pressure.",
        },
        "qualityIteration": "v32-naturalness-gate",
        "qualityRatchet": {
            "previousBaseline": "v31 rendered technically but felt too AI-like and unclear.",
            "rejectionCause": "Caption placement and generic advice made the viewer ask what to do next.",
            "changedLever": ["source", "caption", "storyboard", "pacing"],
            "expectedVisibleImprovement": "The next render should feel like a small human desk routine, not an AI advice montage.",
            "actualProof": "Fixture proves Grok-only provider consistency, naturalness notes, caption system, and viewer takeaway are present.",
            "nextRatchet": "If still artificial, regenerate the source images/videos before touching FFmpeg.",
        },
        "scenes": scenes,
        "assets": assets,
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "grok-only.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 2, "generated": 0, "totalScenes": 2},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "video"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["providerConsistency"]["status"] == "pass"
    assert report["checks"]["antiAiNaturalness"]["status"] == "pass"
    assert report["checks"]["captionSystem"]["status"] == "pass"
    assert report["checks"]["viewerTakeaway"]["status"] == "pass"
    assert report["checks"]["qualityRatchet"]["status"] == "pass"
    assert report["publishReadiness"]["status"] == "ready"


def test_source_editorial_layout_gate_blocks_unreviewed_image_stage(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("unavailable"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "source-editorial-layout-missing",
        "renderPurpose": "source-first-web-image-mix-demo",
        "sourceEditorialLayoutRequired": True,
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Community image",
                "subtitleText": "이 이미지는 아직 위험합니다.",
                "narrationText": "이 이미지는 아직 위험합니다.",
                "visualKind": "image",
                "captionPreset": "lower-info",
                "captionPurpose": "hook",
                "sourceRationale": "Community image supports the topic.",
                "continuityNote": "One source image leads into an official reference.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "image"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "source-editorial.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "image"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["sourceEditorialLayout"]["required"] is True
    assert report["checks"]["sourceEditorialLayout"]["status"] == "fail"
    assert "imageFitPolicy" in report["checks"]["sourceEditorialLayout"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"
    assert any("image fit" in item for item in report["publishReadiness"]["requiredFixes"])


def test_source_editorial_layout_gate_accepts_caption_safe_image_stage(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("unavailable"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "source-editorial-layout-safe",
        "renderPurpose": "source-first-web-image-mix-demo",
        "sourceEditorialLayoutRequired": True,
        "captionSystem": {"fixedPreset": "lower-info", "purposeByScene": {"scene-01": "hook"}},
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Community image",
                "subtitleText": "이 이미지는 안전하게 들어갑니다.",
                "narrationText": "이 이미지는 안전하게 들어갑니다.",
                "visualKind": "image",
                "captionPreset": "lower-info",
                "captionPurpose": "hook",
                "sourceRationale": "Community image supports the topic.",
                "continuityNote": "One source image leads into an official reference.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "sourceEditorialLayout": {
                    "imageFitPolicy": "contain-stage",
                    "situationKey": "source context hook",
                    "sceneVisualDistinctId": "scene-01-community-image",
                    "situationImageFitReview": "This community image is the hook context for the scene and is not reused for another situation.",
                    "situationImageFitVerdict": "pass",
                    "subjectSafeZone": "Main subject is staged in the upper visual field, above the lower caption band.",
                    "captionSafeZone": "Caption stays in the lower-mid band and avoids the bottom Shorts UI area.",
                    "layoutSafetyReview": "The long source image is contained inside a fixed stage so it does not run underneath the caption.",
                    "captionCollisionReview": "Phone-sized review confirms the subtitle does not cover the subject or important source text.",
                    "captionCollisionVerdict": "pass",
                    "imageOverlapReview": "Single image stage has no overlapping source plates or stacked visual elements.",
                    "imageOverlapVerdict": "pass",
                    "dividerLineReview": "No visible black divider or accidental gutter line appears inside the staged image.",
                    "dividerLineVerdict": "pass",
                },
                "endingPurpose": "payoff",
                "endingPacingReview": "The final beat closes the source-context point instead of cutting off as a stray image.",
                "finalTakeawayReview": "The viewer leaves knowing that source images need safe placement before render.",
                "endingVerdict": "pass",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "image"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "source-editorial.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "image"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["sourceEditorialLayout"]["status"] == "pass"
    assert report["checks"]["sourceEditorialImageContext"]["status"] == "pass"
    assert report["checks"]["endingPayoff"]["status"] == "pass"
    assert report["sourceEditorialLayout"]["reviewedScenes"] == ["scene-01"]


def test_still_image_source_policy_blocks_generic_primary_web_image(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("unavailable"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "generic-primary-web-image-blocked",
        "renderPurpose": "source-first-web-image-mix-demo",
        "sourceEditorialLayoutRequired": True,
        "internetSourceContextRequired": True,
        "topic": "A practical explainer about why a phone battery drains faster in winter.",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Generic source image",
                "subtitleText": "사진 한 장으로는 부족합니다.",
                "narrationText": "사진 한 장으로는 부족합니다.",
                "visualKind": "image",
                "captionPreset": "lower-info",
                "captionPurpose": "context",
                "visualSourceIntent": "wikimedia-image",
                "sourceOrigin": "wikimedia-image",
                "sourceType": "internet-image",
                "sourceUrl": "https://commons.wikimedia.org/wiki/File:generic-phone.jpg",
                "sourceLocalPath": "storage/sources/generic-phone.jpg",
                "sourceSha256": "abc123abc123abc123abc123",
                "sourceBytes": 123456,
                "sourceMediaKind": "image",
                "sourceFetchStatus": "fetched",
                "sourceAcquisitionVerdict": "pass",
                "sourceAcquisitionReview": "The file was fetched into local storage with source metadata and a stable checksum.",
                "scenePurpose": "Establish the explainer setup before showing the real battery behavior.",
                "viewerJob": "Understand that the visual should prove a process, not just decorate the claim.",
                "sourceRationale": "The image shows a phone, but it does not demonstrate the actual cold-battery behavior.",
                "mediaChoiceRationale": "A still frame is only a weak topic illustration and does not show the process.",
                "stillFit": "The still only names the topic and does not carry a meme, reaction, capture, or data-card job.",
                "sourceContextVerdict": "pass",
                "continuityNote": "The edit should move from setup into an actual moving demonstration.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "sourceEditorialLayout": {
                    "imageFitPolicy": "contain-stage",
                    "situationKey": "generic explainer setup",
                    "sceneVisualDistinctId": "scene-01-generic-phone",
                    "situationImageFitReview": "The still is staged safely, but its job is only generic topic context.",
                    "situationImageFitVerdict": "pass",
                    "subjectSafeZone": "The phone stays above the lower caption band.",
                    "captionSafeZone": "Caption stays below the source plate and away from platform UI.",
                    "layoutSafetyReview": "The image is contained inside a safe source plate and does not crop the subject.",
                    "captionCollisionReview": "Phone-sized review confirms the subtitle does not cover the source subject.",
                    "captionCollisionVerdict": "pass",
                    "imageOverlapReview": "Single source plate has no overlapping image stack.",
                    "imageOverlapVerdict": "pass",
                    "dividerLineReview": "No black divider line appears inside the source plate.",
                    "dividerLineVerdict": "pass",
                },
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "image"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "source-editorial.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "image"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["sourceEditorialLayout"]["status"] == "pass"
    assert report["checks"]["internetSourceContext"]["status"] == "pass"
    assert report["checks"]["stillImageSourcePolicy"]["status"] == "fail"
    assert report["stillImageSourcePolicy"]["blockedScenes"] == [
        "scene-01:primary-still-image-source-not-meme-reaction-capture-card"
    ]
    assert any("generic web still images" in item for item in report["publishReadiness"]["requiredFixes"])


def test_still_image_source_policy_allows_meme_reaction_primary_image(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("unavailable"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "meme-reaction-primary-image-allowed",
        "renderPurpose": "source-first internet-meme-image proof",
        "sourceEditorialLayoutRequired": True,
        "internetSourceContextRequired": True,
        "topic": "A short reaction explainer about a recognizable meme frame.",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Reaction meme",
                "subtitleText": "이 표정이 포인트입니다.",
                "narrationText": "이 표정이 포인트입니다.",
                "visualKind": "image",
                "captionPreset": "lower-info",
                "captionPurpose": "hook",
                "visualSourceIntent": "meme-image",
                "sourceOrigin": "internet-meme",
                "sourceType": "reaction-image",
                "sourceUrl": "https://example.com/reaction-meme.jpg",
                "sourceLocalPath": "storage/sources/reaction-meme.jpg",
                "sourceSha256": "def456def456def456def456",
                "sourceBytes": 234567,
                "sourceMediaKind": "image",
                "sourceFetchStatus": "fetched",
                "sourceAcquisitionVerdict": "pass",
                "sourceAcquisitionReview": "The meme frame was fetched locally with source metadata and checksum evidence.",
                "scenePurpose": "Use the reaction still as the hook because the expression is the content.",
                "viewerJob": "Recognize the reaction frame before the narration explains the context.",
                "sourceRationale": "The meme image itself is the cultural object being explained, not generic decoration.",
                "mediaChoiceRationale": "A still image is correct because the exact reaction frame carries the joke and context.",
                "stillFit": "The meme frame itself is the subject, so motion would not add the viewer job.",
                "sourceContextVerdict": "pass",
                "continuityNote": "The edit opens on the meme frame and then explains the reaction context.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "sourceEditorialLayout": {
                    "imageFitPolicy": "contain-stage",
                    "situationKey": "reaction meme hook",
                    "sceneVisualDistinctId": "scene-01-reaction-meme",
                    "situationImageFitReview": "The exact reaction still is the scene subject and is not reused for another situation.",
                    "situationImageFitVerdict": "pass",
                    "subjectSafeZone": "The face stays above the lower caption band.",
                    "captionSafeZone": "Caption stays below the meme expression and clear of platform UI.",
                    "layoutSafetyReview": "The meme image is contained in a fixed stage without cropping the expression.",
                    "captionCollisionReview": "Phone-sized review confirms the subtitle does not cover the expression.",
                    "captionCollisionVerdict": "pass",
                    "imageOverlapReview": "Single image plate has no overlapping source plates.",
                    "imageOverlapVerdict": "pass",
                    "dividerLineReview": "No black divider line appears inside the meme plate.",
                    "dividerLineVerdict": "pass",
                },
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "image"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "source-editorial.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "image"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["internetSourceContext"]["status"] == "pass"
    assert report["checks"]["stillImageSourcePolicy"]["status"] == "pass"
    assert report["stillImageSourcePolicy"]["allowedPrimaryStillScenes"] == ["scene-01"]
    assert report["stillImageSourcePolicy"]["blockedScenes"] == []


def test_source_editorial_context_gate_blocks_duplicate_or_mismatched_images(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("unavailable"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    scenes = []
    for idx in (1, 2):
        scenes.append(
            {
                "sceneId": f"scene-0{idx}",
                "title": f"Source scene {idx}",
                "subtitleText": "상황 이미지가 맞아야 합니다.",
                "narrationText": "상황 이미지가 맞아야 합니다.",
                "visualKind": "image",
                "captionPreset": "lower-info",
                "captionPurpose": "context" if idx == 1 else "payoff",
                "sourceRationale": "Source editorial image is used for context.",
                "continuityNote": "The edit moves from one situation to another.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "sourceUrl": "https://example.com/reused-community-image.jpg",
                "sourceEditorialLayout": {
                    "imageFitPolicy": "cover-safe",
                    "situationKey": f"situation {idx}",
                    "sceneVisualDistinctId": "same-image-id",
                    "situationImageFitReview": "Too short.",
                    "situationImageFitVerdict": "fail" if idx == 2 else "pass",
                    "subjectSafeZone": "Subject stays above the lower caption band.",
                    "captionSafeZone": "Caption stays below the visual source plate.",
                    "layoutSafetyReview": "The image plate stays away from the subtitle area and does not crop the key subject.",
                    "captionCollisionReview": "Subtitle does not cover the visible source subject or phone UI.",
                    "captionCollisionVerdict": "pass",
                    "imageOverlapReview": "The image plate has no overlap with other source plates.",
                    "imageOverlapVerdict": "pass",
                    "dividerLineReview": "No black divider line appears inside the visual plate.",
                    "dividerLineVerdict": "pass",
                },
            }
        )
    scenes[-1].update({
        "endingPurpose": "payoff",
        "endingPacingReview": "The final scene closes the comparison instead of stopping abruptly.",
        "finalTakeawayReview": "The viewer understands that repeated images must be rejected.",
        "endingVerdict": "pass",
    })
    manifest = {
        "projectId": "source-editorial-context-duplicate",
        "renderPurpose": "source-first-web-image-mix-demo",
        "sourceEditorialLayoutRequired": True,
        "captionSystem": {
            "fixedPreset": "lower-info",
            "purposeByScene": {"scene-01": "context", "scene-02": "payoff"},
        },
        "scenes": scenes,
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "image"},
            {"provider": "upload", "role": "visual", "sceneId": "scene-02", "kind": "image"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-02", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "source-editorial.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 2, "generated": 0, "totalScenes": 2},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "image"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "image"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["sourceEditorialImageContext"]["status"] == "fail"
    assert "sceneVisualDistinctId unique" in report["checks"]["sourceEditorialImageContext"]["detail"]
    assert "visualAssetFingerprint/source unique" in report["checks"]["sourceEditorialImageContext"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"


def test_ending_payoff_gate_blocks_abrupt_final_scene(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("unavailable"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "source-editorial-abrupt-ending",
        "renderPurpose": "source-first-web-image-mix-demo",
        "sourceEditorialLayoutRequired": True,
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Abrupt final",
                "subtitleText": "끝입니다.",
                "narrationText": "끝입니다.",
                "visualKind": "image",
                "captionPreset": "lower-info",
                "captionPurpose": "context",
                "sourceRationale": "Final image is present but not shaped as an ending.",
                "continuityNote": "The scene appears after the proof beat.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "sourceEditorialLayout": {
                    "imageFitPolicy": "cover-safe",
                    "situationKey": "final image",
                    "sceneVisualDistinctId": "final-image-01",
                    "situationImageFitReview": "The final image matches the topic but does not yet define a payoff.",
                    "situationImageFitVerdict": "pass",
                    "subjectSafeZone": "Subject remains above the lower caption band.",
                    "captionSafeZone": "Caption remains below the source plate.",
                    "layoutSafetyReview": "The image plate does not cover the caption band.",
                    "captionCollisionReview": "Caption does not cover the subject.",
                    "captionCollisionVerdict": "pass",
                    "imageOverlapReview": "Single image has no overlap.",
                    "imageOverlapVerdict": "pass",
                    "dividerLineReview": "No black divider line.",
                    "dividerLineVerdict": "pass",
                },
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "image"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "source-editorial.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "image"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["endingPayoff"]["status"] == "fail"
    assert report["checks"]["endingTailPacing"]["status"] == "fail"
    assert "endingTailHoldSec" in report["checks"]["endingTailPacing"]["detail"]
    assert "endingPurpose" in report["checks"]["endingPayoff"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"


def test_ending_tail_pacing_blocks_blank_padding_and_short_rendered_caption(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("unavailable"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    final_scene = {
        "sceneId": "scene-01",
        "title": "Padded ending",
        "subtitleText": "공기 저항 때문이에요",
        "narrationText": "중력이 달라서가 아니에요. 공기가 없으니까 깃털이 안 밀려서, 망치처럼 같이 내려오는 거예요.",
        "durationSec": 8.8,
        "visualKind": "image",
        "captionPreset": "lower-info",
        "captionPurpose": "payoff",
        "captionDisplayDurationSec": 6.0,
        "sourceRationale": "Final image is the correct source context for the payoff.",
        "continuityNote": "The source context continues from the proof beat.",
        "qualityReviewNote": CAPTION_REVIEW,
        "visualQualityVerdict": "pass",
        "endingPurpose": "payoff",
        "endingPacingReview": "The final source still explains the result instead of adding a new unsupported visual.",
        "finalTakeawayReview": "The viewer remembers that air resistance is the reason.",
        "endingVerdict": "pass",
        "endingTailHoldSec": 2.4,
        "endingFadeOutSec": 0.9,
        "endingTailReview": "The final source remains on screen for a long visual and BGM hold after the spoken explanation.",
        "endingTailVerdict": "pass",
        "sourceEditorialLayout": {
            "imageFitPolicy": "cover-safe",
            "situationKey": "final image",
            "sceneVisualDistinctId": "final-image-01",
            "situationImageFitReview": "The final image matches the topic and keeps source context visible.",
            "situationImageFitVerdict": "pass",
            "subjectSafeZone": "Subject remains above the lower caption band.",
            "captionSafeZone": "Caption remains below the source plate.",
            "layoutSafetyReview": "The image plate does not cover the caption band.",
            "captionCollisionReview": "Caption does not cover the subject.",
            "captionCollisionVerdict": "pass",
            "imageOverlapReview": "Single image has no overlap.",
            "imageOverlapVerdict": "pass",
            "dividerLineReview": "No black divider line.",
            "dividerLineVerdict": "pass",
        },
    }
    manifest = {
        "projectId": "source-editorial-padded-ending",
        "renderPurpose": "source-first-web-image-mix-demo",
        "sourceEditorialLayoutRequired": True,
        "scenes": [final_scene],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "image"},
            {
                "provider": "edge-tts",
                "role": "audio",
                "sceneId": "scene-01",
                "kind": "voiceover",
                "audioDurationFit": {
                    "targetDurationSec": 8.8,
                    "voiceTargetDurationSec": 6.4,
                    "tailHoldSec": 2.4,
                    "speed": 1.136,
                    "mode": "tempo-fit",
                },
            },
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "source-editorial.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "image"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    detail = report["checks"]["endingTailPacing"]["detail"]
    assert report["checks"]["endingPayoff"]["status"] == "pass"
    assert report["checks"]["endingTailPacing"]["status"] == "fail"
    assert "endingTailHoldSec<=1.8" in detail
    assert "audioTailHoldSec<=1.8" in detail
    assert "endingVoiceTargetSec<=4.8" in detail
    assert "endingCaptionVoiceCoverage>=0.40" in detail
    assert "renderedCaptionDurationSec=1.8" in detail
    assert report["publishReadiness"]["status"] == "blocked"


def test_final_payoff_short_narration_can_pass_tts_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("unavailable"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "source-editorial-short-payoff-ending",
        "renderPurpose": "source-first-web-image-mix-demo",
        "sourceEditorialLayoutRequired": True,
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Context",
                "subtitleText": "달에서 봐야 해요",
                "narrationText": "먼저 화면에서 달 표면과 실험 조건을 같이 잡아야 해요. 그래야 다음 결과가 이해돼요.",
                "durationSec": 4.2,
                "visualKind": "image",
                "captionPreset": "lower-info",
                "captionPurpose": "context",
                "sourceRationale": "The first image gives the source context.",
                "continuityNote": "The edit starts from the moon setting.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
            },
            {
                "sceneId": "scene-02",
                "title": "Payoff",
                "subtitleText": "공기 없어서 같이 내려와요",
                "narrationText": "공기가 없으니까 깃털이 안 밀려요. 그래서 망치랑 같이 내려와요.",
                "durationSec": 5.6,
                "visualKind": "image",
                "captionPreset": "lower-info",
                "captionPurpose": "payoff",
                "captionDisplayDurationSec": 1.8,
                "sourceRationale": "The final image keeps the source context visible.",
                "continuityNote": "The final still resolves the GIF proof beat.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "endingPurpose": "payoff",
                "endingPacingReview": "The final still resolves the source proof in one spoken beat, then leaves only a compact BGM tail.",
                "finalTakeawayReview": "The viewer remembers that air resistance is why the feather does not lag behind.",
                "endingVerdict": "pass",
                "endingTailHoldSec": 1.2,
                "endingFadeOutSec": 0.8,
                "endingTailReview": "The final payoff narration ends before a compact visual and BGM tail, without blank padding.",
                "endingTailVerdict": "pass",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "image"},
            {"provider": "upload", "role": "visual", "sceneId": "scene-02", "kind": "image"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
            {
                "provider": "edge-tts",
                "role": "audio",
                "sceneId": "scene-02",
                "kind": "voiceover",
                "audioDurationFit": {
                    "targetDurationSec": 5.6,
                    "voiceTargetDurationSec": 4.4,
                    "tailHoldSec": 1.2,
                    "speed": 1.249,
                    "mode": "tempo-fit",
                },
            },
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "source-editorial.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 2, "generated": 0, "totalScenes": 2},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "image"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "image"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["thinNarrationScenes"] == []
    assert summary["finalPayoffShortNarrationScenes"] == ["scene-02"]
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "pass"
    assert "finalPayoffShortNarrationScenes=['scene-02']" in report["checks"]["ttsNarrationEvidence"]["detail"]


def test_conversational_copy_style_blocks_repetitive_caption_keyword(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    scenes = []
    assets = []
    for index, subtitle in enumerate(("같이 볼까요?", "같이 맞나요?", "같이 끝나요?"), start=1):
        scene_id = f"scene-{index:02d}"
        scenes.append(
            {
                "sceneId": scene_id,
                "title": f"Repeated copy {index}",
                "subtitleText": subtitle,
                "narrationText": "화면에서 실제 소스를 보면서 다음 차이를 바로 확인해 봐요.",
                "durationSec": 3.2,
                "visualKind": "image",
                "captionPreset": "lower-info",
                "captionPurpose": "proof",
                "sourceRationale": "The fetched source supports this viewer-facing proof beat.",
                "continuityNote": "The source sequence moves through related proof beats.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "visualSourceIntent": "internet-image",
                "sourceUrl": f"https://upload.wikimedia.org/example/source-{index}.jpg",
                "sourceLocalPath": f"storage/source-acquisition/repeated-copy/source-{index}.jpg",
                "sourceSha256": f"{index}" * 64,
                "sourceBytes": 12000 + index,
                "sourceMediaKind": "image",
                "sourceFetchStatus": "fetched",
                "sourceAcquisitionVerdict": "pass",
                "sourceContext": {
                    "topic": "repetition proof",
                    "scenePurpose": f"source proof beat {index}",
                    "viewerJob": "spot the concrete source change",
                    "selectionRationale": "The source image fits the proof beat.",
                    "mediaChoiceRationale": "A still image is enough for this proof beat.",
                    "stillFit": "The still source gives the viewer concrete context.",
                    "verdict": "pass",
                },
            }
        )
        assets.extend([
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": scene_id,
                "kind": "image",
                "sourceOrigin": "internet-image",
                "sourcePath": f"storage/source-acquisition/repeated-copy/source-{index}.jpg",
                "sourceUrl": f"https://upload.wikimedia.org/example/source-{index}.jpg",
                "sourceMediaKind": "image",
                "sourceFetchStatus": "fetched",
                "sourceAcquisitionVerdict": "pass",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": scene_id, "kind": "voiceover"},
        ])

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest={
            "projectId": "repetitive-caption-keyword",
            "internetSourceProofMode": True,
            "internetSourceAcquisitionRequired": True,
            "internetSourceContextRequired": True,
            "sourceEditorialLayoutRequired": True,
            "copyStylePrompt": {
                "tone": "conversational spoken short-form copy",
                "captionRule": "Captions must read like distinct viewer reactions, not the same phrase repeated.",
                "narrationRule": "TTS narration should sound spoken and avoid formal report language.",
                "ttsPacingRule": "Keep the spoken line short enough for the scene and align caption density.",
                "forbiddenPatterns": ["source beat", "proof scene", "caption label"],
                "referenceTakeaways": ["Each caption advances the beat.", "Repeated words need a clear callback purpose."],
            },
            "scenes": scenes,
            "assets": assets,
        },
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "repetitive-caption-keyword.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 3, "generated": 0, "totalScenes": 3},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "image"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "image"},
            {"sceneId": "scene-03", "status": "uploaded", "outputKind": "image"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    detail = report["checks"]["conversationalCopyStyle"]["detail"]
    assert report["checks"]["conversationalCopyStyle"]["status"] == "fail"
    assert "'같이': ['scene-01', 'scene-02', 'scene-03']" in detail


def test_render_quality_report_blocks_fallback_sine_instead_of_tts(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "fallback-sine-tts",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Hook with broken voice",
                "subtitleText": "The story needs a voice.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator uploaded a relevant moving hook clip.",
                "continuityNote": "Same warm palette and slow camera motion.",
                "hookNote": "The subject moves in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "fallback-sine", "role": "audio", "sceneId": "scene-01", "kind": "fallback-tone"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "fallback-sine.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "fail"
    assert "fallbackToneScenes=['scene-01']" in report["checks"]["ttsNarrationEvidence"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"
    assert any("viewer-facing narration" in item for item in report["publishReadiness"]["requiredFixes"])


def test_live_channel_quality_report_rejects_draft_only_windows_voice(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "live-channel-fresh-source-runway-20260531-01-render",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Fresh source hook",
                "subtitleText": "첫 장면",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator imported a reviewed moving clip for the hook.",
                "continuityNote": "Camera distance and subject motion stay consistent.",
                "hookNote": "Visible movement appears in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "windows-speech", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "draft-only-voice.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "fail"
    assert "strictLiveChannel=True" in report["checks"]["ttsNarrationEvidence"]["detail"]
    assert "draftOnlyVoiceoverScenes=['scene-01']" in report["checks"]["ttsNarrationEvidence"]["detail"]
    assert report["productionReview"]["summary"]["draftOnlyVoiceoverScenes"] == ["scene-01"]
    assert report["publishReadiness"]["status"] == "blocked"


def test_live_channel_quality_report_blocks_google_ai_studio_tts_as_paid_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "live-channel-paid-tts-blocked",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Paid TTS policy check",
                "subtitleText": "첫 장면",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator imported a reviewed moving clip for the hook.",
                "continuityNote": "Camera distance and subject motion stay consistent.",
                "hookNote": "Visible movement appears in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "google-ai-studio-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "paid-tts.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["zeroPaidProviders"]["status"] == "fail"
    assert "google-ai-studio-tts" in report["checks"]["zeroPaidProviders"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"


def test_live_channel_quality_report_allows_operator_owned_upload_voiceover(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    voiceover = tmp_path / "assets" / "voiceover" / "scene-01-voice.wav"
    voiceover.parent.mkdir(parents=True)
    voiceover.write_bytes(b"operator-owned-voiceover")
    manifest = {
        "projectId": "live-channel-fresh-source-runway-20260531-01-render",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Owned voice hook",
                "subtitleText": "첫 장면",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator imported a reviewed moving clip for the hook.",
                "continuityNote": "Camera distance and subject motion stay consistent.",
                "hookNote": "Visible movement appears in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {
                "provider": "upload",
                "role": "audio",
                "sceneId": "scene-01",
                "kind": "voiceover",
                "sourcePath": "assets/voiceover/scene-01-voice.wav",
                "sourceOrigin": "operator-owned-voiceover",
                "operatorOwned": True,
            },
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "owned-voice.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "pass"
    assert "strictLiveChannel=True" in report["checks"]["ttsNarrationEvidence"]["detail"]
    assert "draftOnlyVoiceoverScenes=[]" in report["checks"]["ttsNarrationEvidence"]["detail"]
    assert report["productionReview"]["summary"]["draftOnlyVoiceoverScenes"] == []


def test_render_quality_report_rejects_production_meta_narration(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "production-meta-narration",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Coffee macro",
                "subtitleText": "첫 컷은 자막을 줄입니다.",
                "narrationText": "두 번째 컷은 예쁜 컵이 아니라 추출되는 행동입니다. 시청자가 지금 무엇을 봐야 하는지 TTS로 짧게 짚고 화면은 그대로 둡니다.",
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this clip for visible extraction motion.",
                "continuityNote": "Warm cafe palette and slow camera move.",
                "hookNote": "Steam rises in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "meta.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    scene = report["productionReview"]["scenes"][0]
    assert summary["productionMetaNarrationScenes"] == ["scene-01"]
    assert "tts" in summary["productionMetaTermsByScene"]["scene-01"]
    assert scene["productionMetaNarrationTerms"]
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "fail"
    assert "productionMetaNarrationScenes=['scene-01']" in report["checks"]["ttsNarrationEvidence"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"


def test_render_quality_report_rejects_video_intent_script_and_meta_caption(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "viewer-intent-script",
        "templateType": "authentic_vlog",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Coffee intent",
                "subtitleText": "아침 카페",
                "narrationText": "이번 영상은 조용한 카페 루틴이 왜 편안하게 느껴지는지 그 의도를 설명합니다.",
                "visualKind": "video",
                "captionPreset": "top-hook",
                "captionDisplayDurationSec": 1.4,
                "sourceRationale": "Operator uploaded a moving cafe hook clip.",
                "continuityNote": "Warm cafe palette and slow camera move.",
                "hookNote": "Steam rises in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
            {
                "sceneId": "scene-02",
                "title": "Coffee action",
                "subtitleText": "이 영상의 의도",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "lower-info",
                "captionDisplayDurationSec": 1.6,
                "sourceRationale": "Operator uploaded a distinct extraction clip.",
                "continuityNote": "Warm cafe palette and slow camera move.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
            {"provider": "upload", "role": "visual", "sceneId": "scene-02", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-02", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "intent.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 2, "generated": 0, "totalScenes": 2},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "video"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["productionMetaNarrationScenes"] == ["scene-01"]
    assert summary["productionMetaSubtitleScenes"] == ["scene-02"]
    assert "이번영상은" in summary["productionMetaTermsByScene"]["scene-01"]
    assert "영상의의도" in summary["productionMetaTermsByScene"]["scene-02"]
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "fail"
    assert "productionMetaSubtitleScenes=['scene-02']" in report["checks"]["ttsNarrationEvidence"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"


def test_render_quality_report_rejects_subtitle_only_as_tts_narration(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "subtitle-only-not-tts",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Caption-only hook",
                "subtitleText": "This caption is not a spoken script.",
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator uploaded a moving hook clip.",
                "continuityNote": "Same palette and camera language.",
                "hookNote": "The subject moves in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "subtitle-only.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    scene = report["productionReview"]["scenes"][0]
    assert summary["subtitleOnlyNarrationScenes"] == ["scene-01"]
    assert summary["missingNarrationScenes"] == ["scene-01"]
    assert scene["subtitleOnlyNarrationFallback"] is True
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "fail"
    assert "subtitleOnlyNarrationScenes=['scene-01']" in report["checks"]["ttsNarrationEvidence"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"


def test_render_quality_report_allows_grok_first_no_voice_audio_design(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    scenes = []
    assets = [
        {
            "provider": "local-bgm",
            "role": "audio",
            "sceneId": "global",
            "kind": "bgm",
            "sourceOrigin": "local-library",
            "sourcePath": "assets/bgm/cinematic/grok-no-voice-bed.wav",
            "sourceLabel": "grok-no-voice-bed.wav",
            "sourceUrl": "https://example.invalid/free/grok-no-voice-bed",
            "sourceLicense": "CC0 test fixture",
            "candidateCount": 2,
            "selectionMethod": "stable-hash",
            "selectionKey": "persona-story-no-voice",
        }
    ]
    for index, preset in enumerate(("top-hook", "none"), start=1):
        scene_id = f"scene-{index:02d}"
        scenes.append(
            {
                "sceneId": scene_id,
                "title": f"Persona beat {index}",
                "subtitleText": "첫 움직임" if index == 1 else "",
                "visualKind": "video",
                "captionPreset": preset,
                "captionDisplayDurationSec": 1.3 if preset == "top-hook" else 0,
                "sourceRationale": "Operator accepted this Grok MP4 because the first-second motion, subject, and palette match the shot bible.",
                "continuityNote": "Same Korean office worker, navy coat, black backpack, teal-warm night palette, and handheld camera language.",
                "hookNote": "The character slows down and the platform lights move in the first two seconds." if index == 1 else "The beat continues the same character action.",
                "originalityEvidence": "Grok app/web MP4 imported through the handoff packet and accepted in the review packet; no paid API call.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Use the scene-01 frame with moving platform lights and no baked-in text." if index == 1 else "",
                "audioMixReviewNote": "No TTS is used; BGM stays audible but low enough that the Grok footage reads as natural raw footage.",
                "platformComparisonNote": "Compared against current Korean AI-assisted Shorts for hook, caption restraint, source motion, and artifact level.",
                "layoutVariantKey": "character-continuity" if index == 1 else "pov-diary",
                "selectedFileName": f"{scene_id}.grok.mp4",
                "selectedCandidateSummary": "Take 2 has cleaner motion than take 1 while preserving the same subject and shot bible.",
                "visualSourceIntent": "grok",
            }
        )
        assets.append(
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": scene_id,
                "kind": "video",
                "sourceOrigin": "grok-handoff",
                "sourcePath": f"storage/grok-handoffs/persona/story/{scene_id}.grok.mp4",
                "selectedFileName": f"{scene_id}.grok.mp4",
                "candidateCount": 2,
                "sourceProvenance": {
                    "status": "browser-native-original-download",
                    "acceptAsGrokMainSource": True,
                },
            }
        )

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest={
            "projectId": "grok-no-voice-persona",
            "templateType": "persona_story",
            "audioDesignMode": "no-voice",
            "scenes": scenes,
            "assets": assets,
        },
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "grok-no-voice.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 2, "generated": 0, "totalScenes": 2},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "video"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["noVoiceAudioDesignScenes"] == ["scene-01", "scene-02"]
    assert summary["missingNarrationScenes"] == []
    assert summary["missingNoVoiceAudioScenes"] == []
    assert summary["missingNoVoiceAudioReviewScenes"] == []
    assert summary["audioDesignModesByScene"] == {"scene-01": "no-voice", "scene-02": "no-voice"}
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "pass"
    assert report["publishReadiness"]["status"] == "ready"
    assert report["channelReadiness"]["status"] == "channel-ready"
    assert report["uploadReview"]["status"] == "ready"
    assert report["topTierReadiness"]["status"] == "top-tier-ready"
    audio_design = next(item for item in report["topTierReadiness"]["criteria"] if item["key"] == "audioDesign")
    assert audio_design["status"] == "pass"


def test_render_quality_report_rejects_no_voice_for_ranking_without_human_approval(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "ranking-no-voice-rejected",
        "templateType": "ranking_list",
        "audioDesignMode": "no-voice",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "#5 Water first",
                "subtitleText": "5위 물 먼저",
                "visualKind": "video",
                "captionPreset": "top-hook",
                "captionDisplayDurationSec": 1.2,
                "sourceRationale": "Operator selected this moving Grok MP4 because the hand action starts immediately.",
                "continuityNote": "Same desk, hand, bottle, warm light, and handheld camera rhythm.",
                "hookNote": "The hand grabs the bottle in the first second.",
                "originalityEvidence": "Grok app/web MP4 imported through handoff; no paid API call.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Use the moving bottle frame with no baked-in text.",
                "audioMixReviewNote": "BGM is present, but no TTS was intentionally requested in this failing fixture.",
                "platformComparisonNote": "Compared against ranking Shorts for hook clarity and caption position.",
                "layoutVariantKey": "rank-card",
                "selectedFileName": "scene-01.grok.mp4",
                "selectedCandidateSummary": "Take 2 has clearer first-second hand motion than take 1 and keeps the subject centered.",
                "visualSourceIntent": "grok",
            },
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "grok-handoff",
                "sourcePath": "storage/grok-handoffs/ranking/scene-01.grok.mp4",
                "selectedFileName": "scene-01.grok.mp4",
                "candidateCount": 2,
                "sourceProvenance": {
                    "status": "browser-native-original-download",
                    "acceptAsGrokMainSource": True,
                },
            },
            {
                "provider": "local-bgm",
                "role": "audio",
                "sceneId": "global",
                "kind": "bgm",
                "sourceOrigin": "local-library",
                "sourcePath": "assets/bgm/tech-house/minimal.mp3",
                "sourceLabel": "Minimal Mixkit bed",
                "sourceUrl": "https://mixkit.co/free-stock-music/tech-house/",
                "sourceLicense": "Mixkit Stock Music Free License",
                "candidateCount": 2,
                "selectionMethod": "stable-hash",
                "selectionKey": "ranking-no-voice-rejected",
            },
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "ranking-no-voice.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["voiceoverRequiredNoVoiceScenes"] == ["scene-01"]
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "fail"
    assert report["checks"]["voicePolicyCompliance"]["status"] == "fail"
    assert "voiceoverRequiredNoVoiceScenes=['scene-01']" in report["checks"]["ttsNarrationEvidence"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"
    assert any("TTS/voiceover" in item for item in report["publishReadiness"]["requiredFixes"])


def test_render_quality_report_blocks_grok_main_without_curation_and_source_provenance(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "grok-missing-curation",
        "templateType": "authentic_vlog",
        "audioDesignMode": "no-voice",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Routine hook",
                "subtitleText": "퇴근 후, 속도 낮추기",
                "visualKind": "video",
                "captionPreset": "top-hook",
                "captionDisplayDurationSec": 1.2,
                "sourceRationale": "Operator-selected Grok web handoff MP4 for scene-01.",
                "continuityNote": "Same worker, backpack, and teal-warm night palette continue through the scene.",
                "hookNote": "The platform lights move and the subject slows down in the first two seconds.",
                "originalityEvidence": "Grok Imagine web/app MP4 synced from handoff incoming folder for scene-01.",
                "qualityReviewNote": (
                    "Caption layout reviewed: subject stays visible and the caption avoids Shorts UI. "
                    "Candidate preview only; final Grok-main approval still needs extra original-download take curation."
                ),
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Use the opening motion frame with no baked-in text.",
                "audioMixReviewNote": "No-voice BGM and local ambience carry the scene without explanatory TTS.",
                "platformComparisonNote": "Compared against Korean routine Shorts for hook, caption restraint, and full-frame motion.",
                "layoutVariantKey": "grok-first-hook",
                "visualSourceIntent": "grok",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "grok-handoff",
                "sourcePath": "storage/grok-handoffs/routine/scene-01.grok.mp4",
            },
            {
                "provider": "local-bgm",
                "role": "audio",
                "sceneId": "global",
                "kind": "bgm",
                "sourceOrigin": "local-library",
                "sourcePath": "assets/bgm/tech-house/minimal.mp3",
                "sourceLabel": "Minimal test bed",
                "sourceUrl": "https://example.invalid/free/minimal",
                "sourceLicense": "Free test fixture",
                "candidateCount": 2,
                "selectionMethod": "stable-hash",
                "selectionKey": "grok-missing-curation",
            },
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "grok-missing-curation.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["missingGrokSourceCurationScenes"] == ["scene-01"]
    assert summary["missingGrokCandidateComparisonScenes"] == ["scene-01"]
    assert summary["missingGrokSelectedFileScenes"] == ["scene-01"]
    assert summary["missingGrokSourceProvenanceScenes"] == ["scene-01"]
    assert summary["grokPreviewCaveatScenes"] == ["scene-01"]
    assert report["checks"]["grokSourceCuration"]["status"] == "fail"
    assert report["publishReadiness"]["status"] == "blocked"
    assert any("Grok-main" in item for item in report["publishReadiness"]["requiredFixes"])
    assert report["topTierReadiness"]["status"] == "needs-publish-rework"
    assert report["checks"]["topTierReadinessGate"]["status"] == "warn"


def test_render_quality_report_blocks_reference_profile_without_generated_video_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    scenes = [
        {
            "sceneId": "scene-01",
            "title": "Mistake one",
            "subtitleText": "폼이 무너지는 첫 장면",
            "narrationText": FULL_NARRATION,
            "visualKind": "video",
            "captionPreset": "top-hook",
            "sourceRationale": "Local prototype footage was manually selected as a temporary reference stand-in.",
            "continuityNote": "Gym, subject, and prop continuity are plausible but not generated source proof.",
            "hookNote": "The first two seconds show the wrong setup clearly.",
            "originalityEvidence": "Temporary local prototype upload; not Grok, Gemini, or local generated footage.",
            "qualityReviewNote": CAPTION_REVIEW,
            "visualQualityVerdict": "pass",
            "stockAiClipFitVerdict": "pass",
            "thumbnailReviewNote": "Opening frame contains the clear mistake.",
            "audioMixReviewNote": "Voiceover remains audible above BGM with no clipping.",
            "platformComparisonNote": "Compared against reference ranking Shorts for hook, caption, and cut speed.",
            "visualSourceIntent": "local-reference-prototype",
        },
        {
            "sceneId": "scene-02",
            "title": "Mistake two",
            "subtitleText": "초보자가 흔히 놓치는 동작",
            "narrationText": FULL_NARRATION,
            "visualKind": "video",
            "captionPreset": "lower-info",
            "sourceRationale": "Another local prototype clip was selected because it roughly matches the script beat.",
            "continuityNote": "Same gym palette, but no external generation/import proof exists.",
            "hookNote": "Movement starts early enough for a Shorts beat.",
            "originalityEvidence": "Temporary local prototype upload; not Grok, Gemini, or local generated footage.",
            "qualityReviewNote": CAPTION_REVIEW,
            "visualQualityVerdict": "pass",
            "stockAiClipFitVerdict": "pass",
            "thumbnailReviewNote": "Support scene only; no thumbnail candidate.",
            "audioMixReviewNote": "Voiceover remains audible above BGM with no clipping.",
            "platformComparisonNote": "Compared against reference ranking Shorts for source fit and cut density.",
            "visualSourceIntent": "local-reference-prototype",
        },
    ]
    assets = [
        {
            "provider": "upload",
            "role": "visual",
            "sceneId": "scene-01",
            "kind": "video",
            "sourceOrigin": "uploaded",
            "sourcePath": "storage/uploads/reference-prototype/scene-01.mp4",
        },
        {
            "provider": "upload",
            "role": "visual",
            "sceneId": "scene-02",
            "kind": "video",
            "sourceOrigin": "uploaded",
            "sourcePath": "storage/uploads/reference-prototype/scene-02.mp4",
        },
        {"provider": "edge-tts", "role": "audio"},
    ]

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest={
            "projectId": "reference-info-ranking-short-test",
            "templateType": "ranking_list",
            "referenceProfilePath": "storage/episodes/reference-profile.json",
            "qualityGateRequired": True,
            "scenes": scenes,
            "assets": assets,
        },
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "reference-prototype.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 2, "generated": 0, "totalScenes": 2},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "video"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["sourceFirstRequired"] is True
    assert summary["sourceFirstReady"] is False
    assert summary["sourceFirstGeneratedSceneIds"] == []
    assert summary["sourceFirstBlockedSceneIds"] == ["scene-01", "scene-02"]
    assert summary["sourceFirstBlockReasonsByScene"] == {
        "scene-01": "requires-grok-gemini-local-generated-or-context-approved-internet-source",
        "scene-02": "requires-grok-gemini-local-generated-or-context-approved-internet-source",
    }
    assert report["checks"]["sourceFirstSourceGate"]["status"] == "fail"
    assert report["checks"]["stockAiClipFit"]["status"] == "fail"
    assert "sourceFirstBlockedSceneIds=['scene-01', 'scene-02']" in report["checks"]["stockAiClipFit"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"
    assert any("Grok/Gemini/local model MP4 sources" in item for item in report["publishReadiness"]["requiredFixes"])
    assert report["uploadReview"]["status"] == "blocked"
    assert report["checks"]["uploadReviewGate"]["status"] == "fail"


def test_render_quality_report_accepts_internet_gif_source_proof(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")

    scenes = []
    assets = [
        {
            "provider": "local-bgm",
            "role": "audio",
            "sceneId": "global",
            "kind": "bgm",
            "sourceOrigin": "local-library",
            "sourcePath": "assets/bgm/editorial/source-proof-bed.mp3",
            "sourceLabel": "source-proof-bed.mp3",
            "sourceUrl": "https://example.invalid/free/source-proof-bed",
            "sourceLicense": "CC0 test fixture",
            "candidateCount": 2,
            "selectionMethod": "stable-hash",
            "selectionKey": "internet-gif-proof",
        }
    ]
    for index in range(1, 3):
        scene_id = f"scene-{index:02d}"
        scenes.append(
            {
                "sceneId": scene_id,
                "title": f"Internet source beat {index}",
                "subtitleText": "GIF first?" if index == 1 else "watch the loop change it?",
                "narrationText": (
                    "Real GIF first, right? Not fake."
                    if index == 1
                    else "The loop changes the joke, right?"
                ),
                "durationSec": 3.2 if index == 1 else 4.4,
                "visualKind": "video",
                "captionPreset": "top-hook" if index == 1 else "lower-info",
                "captionPurpose": "hook" if index == 1 else "proof",
                "captionDisplayDurationSec": 1.35 if index == 1 else 1.8,
                "sourceRationale": "Operator selected this fetched internet GIF because the motion directly supports the commentary beat.",
                "continuityNote": "Both GIF beats use source-first editorial framing, visible motion, and restrained caption placement.",
                "hookNote": "The fetched GIF moves inside the first second, so the source proof is visible immediately.",
                "originalityEvidence": "Internet source proof mode: direct media URL was fetched locally with sha256, bytes, and source-fit review before render.",
                "qualityReviewNote": (
                    CAPTION_REVIEW + " The fetched reaction source stays visible while the top caption names the real source beat."
                    if index == 1
                    else CAPTION_REVIEW + " The looped motion remains visible above the lower caption so the proof reads as movement."
                ),
                "visualQualityVerdict": "pass",
                "stockAiClipFitVerdict": "pass",
                "thumbnailReviewNote": "The first GIF frame has motion context and no baked-in title or watermark risk in this proof.",
                "audioMixReviewNote": "Edge TTS stays intelligible over a real local BGM bed with no clipping in the proof mix.",
                "platformComparisonNote": "Compared against source-led Korean explainer Shorts for hook, proof visibility, caption restraint, and cut pacing.",
                "editBeatNote": (
                    "First beat uses a quick source hook."
                    if index == 1
                    else "Final beat resolves on a short source loop, a readable payoff caption, and a compact fade-out instead of blank tail padding."
                ),
                "layoutVariantKey": "source-proof-hook" if index == 1 else "source-proof-body",
                "layoutVariantNote": (
                    "Hook layout keeps the fetched reaction GIF large; the top caption names the real source without covering the moving subject."
                    if index == 1
                    else "Body layout uses a lower caption so the looped GIF motion remains visible and the proof beat reads as motion."
                ),
                "visualSourceIntent": "internet-meme-gif",
                "sceneIntentRole": "hook" if index == 1 else "proof",
                "sourceProofClaim": (
                    "The fetched GIF motion proves the fake-card reaction before any explanation."
                    if index == 1
                    else "The looped GIF motion proves that the payoff depends on movement, not a decorative still."
                ),
                "sourceViewerTask": (
                    "Notice that the viewer reaction comes from a real moving source."
                    if index == 1
                    else "Watch the repeated motion resolve the source-first proof."
                ),
                "sceneSourceBindingReview": (
                    "The hook uses the real GIF motion as the viewer question, so caption, narration, and layout point at the same moving reaction."
                    if index == 1
                    else "The proof beat uses looped GIF motion as the answer, so the payoff caption and lower layout keep the motion readable."
                ),
                "sceneSourceBindingVerdict": "pass",
                "sourceUrl": f"https://upload.wikimedia.org/example/source-{index}.gif",
                "sourceLocalPath": f"storage/source-acquisition/internet-gif-proof/raw/source-{index}.gif",
                "sourceSha256": f"{index}" * 64,
                "sourceBytes": 12000 + index,
                "sourceMediaKind": "gif",
                "sourceFetchStatus": "fetched",
                "sourceAcquisitionVerdict": "pass",
                "sourceAcquisitionReview": "Operator verified this direct GIF source was fetched locally with hash, byte size, source URL, and scene fit before render.",
                "sourceContext": {
                    "topic": "AI-only Shorts feel fake when they have no real source",
                    "scenePurpose": "replace an internal fake meme card with a real fetched reaction source",
                    "viewerJob": "show why source-first editing feels more concrete than generated filler",
                    "intentRole": "hook" if index == 1 else "proof",
                    "proofClaim": (
                        "The fetched GIF motion proves the fake-card reaction before any explanation."
                        if index == 1
                        else "The looped GIF motion proves that the payoff depends on movement, not a decorative still."
                    ),
                    "selectionRationale": "This fetched GIF is used for the reaction beat because its looped motion directly supports the criticism of fake meme cards.",
                    "mediaChoiceRationale": "GIF is selected here because the motion is the point of the joke and the viewer response.",
                    "motionFit": "The looped motion makes the reaction readable without needing a separate explanation.",
                    "verdict": "pass",
                },
                "captionCollisionReview": "Caption is placed in a safe zone and does not cover the moving source subject or platform UI.",
                "captionCollisionVerdict": "pass",
                "antiAiNaturalnessVerdict": "pass",
                "naturalnessReviewNote": "This proof uses a real fetched internet GIF rather than an invented AI card, so the visual source reads as concrete evidence.",
                "actionMotivation": "The GIF motion is used as commentary evidence.",
                "worldContinuityNote": "Both source GIF scenes share the same editorial proof frame and restrained caption rhythm.",
                "endingPurpose": "payoff" if index == 2 else "",
                "endingPacingReview": "Final GIF beat closes the proof with a short moving source, readable payoff caption, and no abrupt silence or late title card." if index == 2 else "",
                "finalTakeawayReview": "Viewer leaves understanding that source-first GIF acquisition fixes the fake-card problem." if index == 2 else "",
                "endingVerdict": "pass" if index == 2 else "",
                "endingTailHoldSec": 1.2 if index == 2 else 0,
                "endingFadeOutSec": 0.8 if index == 2 else 0,
                "endingTailReview": "Final GIF beat keeps the payoff source and caption in the same breath, then leaves a compact 1.2s BGM tail and fade so it closes without padding." if index == 2 else "",
                "endingTailVerdict": "pass" if index == 2 else "",
                "endingResolutionReview": "The final source loop, payoff caption, and spoken close land together before the short tail, so the ending resolves instead of padding." if index == 2 else "",
                "endingScreenAction": "Hold on the resolved moving GIF payoff while caption and voice close together." if index == 2 else "",
                "endingResolutionVerdict": "pass" if index == 2 else "",
            }
        )
        assets.extend([
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": scene_id,
                "kind": "video",
                "sourceOrigin": "internet-meme-gif",
                "sourceType": "meme-gif",
                "sourcePath": f"storage/source-acquisition/internet-gif-proof/raw/source-{index}.gif",
                "sourceUrl": f"https://upload.wikimedia.org/example/source-{index}.gif",
                "sourceLocalPath": f"storage/source-acquisition/internet-gif-proof/raw/source-{index}.gif",
                "sourceSha256": f"{index}" * 64,
                "sourceBytes": 12000 + index,
                "sourceMediaKind": "gif",
                "sourceFetchStatus": "fetched",
                "sourceAcquisitionVerdict": "pass",
                "sourceAcquisitionReview": "Operator verified this direct GIF source was fetched locally with hash, byte size, source URL, and scene fit before render.",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": scene_id, "kind": "voiceover"},
        ])

    manifest = {
        "projectId": "internet-meme-gif-quality-proof-test",
        "topic": "AI-only Shorts feel fake when they have no real source",
        "templateType": "authentic_vlog",
        "renderPurpose": "source-first internet-meme-gif quality proof",
        "sourceFirstRequired": True,
        "internetSourceProofMode": True,
        "internetSourceAcquisitionRequired": True,
        "internetSourceContextRequired": True,
        "sourceEditorialLayoutRequired": True,
        "captionSystem": {"fixedPreset": "mixed-by-scene"},
        "topicHookPayoff": {
            "topic": "AI-only Shorts feel fake when they have no real source",
            "hook": "What if the meme beat is a real fetched GIF instead of a fake card?",
            "payoff": "The source-first edit feels concrete because the motion proves the joke.",
            "viewerTakeaway": "Pick sources after the hook/payoff spine, then bind every scene to what that source proves.",
        },
        "visualFrameReview": {
            "contactSheetPath": "storage/renders/internet-gif-proof/contact-sheet-review.jpg",
            "reviewerType": "contact-sheet-human",
            "reviewNotes": "Phone-sized contact sheet review confirms the GIF source is the main visual object, captions stay clear, TTS pacing feels synced, and the final beat resolves without blank padding.",
            "sourceDominanceVerdict": "pass",
            "captionOcclusionVerdict": "pass",
            "layoutNaturalnessVerdict": "pass",
            "ttsCaptionSyncVerdict": "pass",
            "captionTtsHumanVerdict": "pass",
            "captionTtsReview": "Phone playback confirms the visible caption and spoken line carry the same idea in the same beat without rushing or drifting apart.",
            "motionStabilityVerdict": "pass",
            "motionStabilityReview": "The fetched GIF motion remains stable at phone size with no synthetic shake, floating crop, or wobbling zoom added by the render.",
            "sourceRepetitionVerdict": "pass",
            "sourceRepetitionReview": "Each repeated source appearance has a distinct hook or payoff purpose, so the edit does not recycle the same image as filler.",
            "endingResolutionVerdict": "pass",
            "sceneReviews": {
                "scene-01": {
                    "sourceVisibleVerdict": "pass",
                    "sourceDominanceVerdict": "pass",
                    "captionClearVerdict": "pass",
                    "motionStabilityVerdict": "pass",
                    "sourceRepetitionVerdict": "pass",
                    "review": "The hook frame keeps the real GIF large enough to read and the top caption does not cover the moving reaction.",
                },
                "scene-02": {
                    "sourceVisibleVerdict": "pass",
                    "sourceDominanceVerdict": "pass",
                    "captionClearVerdict": "pass",
                    "motionStabilityVerdict": "pass",
                    "sourceRepetitionVerdict": "pass",
                    "review": "The proof frame keeps loop motion visible above the lower caption and the final caption lands with the spoken close.",
                },
            },
        },
        "copyStylePrompt": {
            "tone": "conversational spoken short-form copy",
            "captionRule": "Captions must read like a viewer reaction, question, or short payoff rather than an internal scene label.",
            "narrationRule": "TTS narration must sound spoken, use direct viewer language, and avoid production labels or report-style phrasing.",
            "ttsPacingRule": "Keep TTS under the scene timing without tempo compression; captions must carry enough of the spoken idea to feel synced.",
            "forbiddenPatterns": ["source beat", "proof scene", "layout note", "caption label"],
            "referenceTakeaways": [
                "Lead with curiosity or a direct reaction in the first beat.",
                "Keep on-screen text short enough to read while the source stays visible.",
            ],
        },
        "viewerTakeaway": {
            "understood": "Fetched GIFs can replace fake internal meme cards.",
            "action": "Use local fetched source assets before layout and TTS.",
            "feeling": "concrete",
        },
        "qualityRatchet": {
            "previousBaseline": "Still-image webmix proof did not solve motion or source-first quality.",
            "rejectionCause": "Viewer could not tell the proof used real fetched internet motion sources.",
            "changedLever": "source acquisition, GIF motion, layout, caption, TTS, and audio proof",
            "expectedVisibleImprovement": "Every scene shows a moving fetched source with clean captions and voiceover.",
            "actualProof": "Render report accepts internetSourceAcquisition and sourceFirstSourceGate.",
            "nextRatchet": "Operator can replace proof GIFs with upload-reviewed rights-safe assets.",
        },
        "scenes": scenes,
        "assets": assets,
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "internet-gif-proof.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 2, "generated": 0, "totalScenes": 2},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "video"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["internetSourceProofMode"] is True
    assert summary["internetMotionSourceSceneIds"] == ["scene-01", "scene-02"]
    assert summary["sourceFirstReady"] is True
    assert summary["sourceFirstInternetSourceSceneIds"] == ["scene-01", "scene-02"]
    assert summary["weakUploadedOriginalityScenes"] == []
    assert report["internetSourceAcquisition"]["status"] == "pass"
    assert report["internetSourceAcquisition"]["motionReadyScenes"] == ["scene-01", "scene-02"]
    assert report["checks"]["internetSourceAcquisition"]["status"] == "pass"
    assert report["checks"]["internetSourceContext"]["status"] == "pass"
    assert report["checks"]["internetSourceEditorialIntegration"]["status"] == "pass"
    assert report["checks"]["topicHookPayoffStructure"]["status"] == "pass"
    assert report["checks"]["sceneSourceIntentBinding"]["status"] == "pass"
    assert report["checks"]["visualFrameReviewEvidence"]["status"] == "pass"
    assert report["checks"]["conversationalCopyStyle"]["status"] == "pass"
    assert report["checks"]["sourceLoopRhythm"]["status"] == "pass"
    assert report["checks"]["endingTailPacing"]["status"] == "pass"
    assert report["checks"]["sourceFirstSourceGate"]["status"] == "pass"
    assert report["checks"]["stockAiClipFit"]["status"] == "pass"
    assert report["checks"]["publishReadinessGate"]["status"] == "pass"
    assert report["checks"]["channelReadinessGate"]["status"] == "pass"
    assert report["checks"]["uploadReviewGate"]["status"] == "pass"
    assert report["checks"]["topTierReadinessGate"]["status"] == "pass"
    assert report["gateSystem"]["status"] == "pass"


def test_topic_hook_payoff_structure_blocks_source_dump_without_spine():
    review = compose_ffmpeg._build_topic_hook_payoff_structure_review(
        {
            "projectId": "source-dump-without-spine",
            "internetSourceProofMode": True,
            "internetSourceContextRequired": True,
            "scenes": [
                {
                    "sceneId": "scene-01",
                    "captionPurpose": "proof",
                    "subtitleText": "see the source?",
                    "sourceMediaKind": "gif",
                    "sourceContext": {"intentRole": "proof"},
                }
            ],
            "assets": [
                {
                    "provider": "upload",
                    "role": "visual",
                    "sceneId": "scene-01",
                    "kind": "video",
                    "sourceOrigin": "internet-meme-gif",
                    "sourceUrl": "https://upload.wikimedia.org/example/random.gif",
                    "sourceMediaKind": "gif",
                }
            ],
        }
    )

    assert review["status"] == "fail"
    assert "topicHookPayoff/narrativeSpine" in review["missingFields"]
    assert "firstSceneHookRole" in review["missingFields"]


def test_topic_hook_payoff_structure_blocks_spine_not_in_viewer_copy():
    review = compose_ffmpeg._build_topic_hook_payoff_structure_review(
        {
            "projectId": "spine-stuck-in-planning-not-copy",
            "internetSourceProofMode": True,
            "internetSourceContextRequired": True,
            "topicHookPayoff": {
                "topic": "2026 optical illusion comment debate",
                "hook": "Start with a fixation illusion that makes people notice their own perception changing.",
                "payoff": "Close on the comment split: different viewers lock onto different interpretations of the same source.",
                "viewerTakeaway": "The viewer should feel the ambiguity before the explanation arrives.",
            },
            "scenes": [
                {
                    "sceneId": "scene-01",
                    "captionPurpose": "hook",
                    "subtitleText": "움직임 먼저 보여요?",
                    "narrationText": "움직임 착시 먼저 보여요?",
                    "sceneIntentRole": "hook",
                    "sourceContext": {"intentRole": "hook"},
                },
                {
                    "sceneId": "scene-02",
                    "captionPurpose": "proof",
                    "subtitleText": "둘 중 뭐가 먼저 보여요?",
                    "narrationText": "오리에서 토끼로 바뀌는 순간 보이죠?",
                    "sceneIntentRole": "proof",
                    "sourceContext": {"intentRole": "proof"},
                },
                {
                    "sceneId": "scene-03",
                    "captionPurpose": "payoff",
                    "subtitleText": "평행선 댓글 갈리죠?",
                    "narrationText": "같은 평행선도 댓글 갈리죠?",
                    "sceneIntentRole": "payoff",
                    "sourceContext": {"intentRole": "payoff"},
                    "endingPurpose": "payoff",
                },
            ],
            "assets": [
                {
                    "role": "visual",
                    "sceneId": scene_id,
                    "kind": "image",
                    "sourceOrigin": "internet-image",
                    "sourceMediaKind": "image",
                    "sourceFetchStatus": "fetched",
                }
                for scene_id in ("scene-01", "scene-02", "scene-03")
            ],
        }
    )

    assert review["status"] == "fail"
    assert "hookAppearsInViewerCopy" in review["missingFields"]
    assert "payoffAppearsInViewerCopy" in review["missingFields"]


def test_audience_interest_source_fit_blocks_generic_trending_claim():
    review = compose_ffmpeg._build_audience_interest_source_fit_review(
        {
            "projectId": "generic-interest-claim",
            "qualitySampleSetRequired": True,
            "topicHookPayoff": {
                "topic": "some viral topic",
                "hook": "This is trending",
                "payoff": "People are interested because it is popular.",
                "viewerTakeaway": "The topic is popular.",
            },
            "audienceInterest": {
                "targetAudience": "Korean Shorts viewers",
                "interestDriver": "People are interested in this viral popular trending topic.",
                "whyNowOrEvergreen": "It is popular right now.",
                "scrollStopHook": "요즘 이거 봤죠?",
                "sourceStrategy": "Use a source that fits the context.",
                "commentPrompt": "What do you think?",
                "interestScore": 4,
                "audienceInterestVerdict": "pass",
            },
        }
    )

    assert review["status"] == "fail"
    assert "interestEvidence>=28 or evidenceItems>=1" in review["missingFields"]
    assert "nonGenericInterestEvidence" in review["missingFields"]


def test_audience_interest_source_fit_accepts_specific_viewer_demand():
    review = compose_ffmpeg._build_audience_interest_source_fit_review(
        {
            "projectId": "specific-interest-proof",
            "qualitySampleSetRequired": True,
            "topicHookPayoff": {
                "topic": "AI-looking Shorts versus real source proof",
                "hook": "잠깐, 이건 진짜 소스야?",
                "payoff": "The proof works because viewers can see the source, not just hear a claim.",
                "viewerTakeaway": "Source choice starts from viewer curiosity.",
            },
            "audienceInterest": {
                "targetAudience": "Korean Shorts viewers tired of generic AI explainer clips",
            "interestDriver": "The viewer gets a quick test: can a real internet source beat an AI-looking render?",
            "whyNowOrEvergreen": "Short-form feeds are crowded with generic AI visuals, so source-visible proof is a live quality differentiator.",
            "interestEvidence": "Manual reference review found source-first proof clips keep attention when the first frame poses a visible challenge.",
            "evidenceItems": [
                {
                    "source": "Manual reference review",
                    "signal": "Source-visible proof clips held attention when the first frame posed a visible challenge.",
                    "relevance": "The proof is judged by a concrete viewer task rather than a vague claim that a topic is popular.",
                },
                {
                    "source": "Source-first render comparison",
                    "signal": "Generic AI-looking topics were rejected when source choice did not prove the hook.",
                    "relevance": "The gate should require a specific curiosity reason before source/layout/TTS quality can count.",
                },
            ],
            "scrollStopHook": "이거 AI가 아니라 진짜 소스야?",
                "sourceStrategy": "Fetch motion sources only when motion proves the hook, and use stills only for setup or payoff context.",
                "commentPrompt": "Viewers can comment whether the source actually proves the claim.",
                "interestScore": 4,
                "audienceInterestVerdict": "pass",
            },
        }
    )

    assert review["status"] == "pass"
    assert review["missingFields"] == []


def test_scene_source_intent_binding_blocks_generic_context_fit_text():
    review = compose_ffmpeg._build_scene_source_intent_binding_review(
        {
            "projectId": "generic-source-intent",
            "internetSourceProofMode": True,
            "internetSourceContextRequired": True,
            "scenes": [
                {
                    "sceneId": "scene-01",
                    "captionPurpose": "proof",
                    "subtitleText": "this fits the context?",
                    "narrationText": "This source is contextually relevant, so it should fit the scene.",
                    "sourceContext": {
                        "intentRole": "proof",
                        "proofClaim": "The source is contextually relevant and appropriate for this scene.",
                        "viewerTask": "Accept that the source is contextually appropriate.",
                        "sceneSourceBindingReview": "The source is contextually relevant and appropriate for this scene because it fits the topic.",
                        "sceneSourceBindingVerdict": "pass",
                        "mediaChoiceRationale": "GIF is selected because motion is visible in the source.",
                        "motionFit": "The GIF has moving source evidence.",
                    },
                }
            ],
            "assets": [
                {
                    "provider": "upload",
                    "role": "visual",
                    "sceneId": "scene-01",
                    "kind": "video",
                    "sourceOrigin": "internet-meme-gif",
                    "sourceUrl": "https://upload.wikimedia.org/example/random.gif",
                    "sourceMediaKind": "gif",
                }
            ],
        }
    )

    assert review["status"] == "fail"
    assert "scene-01:sourceIntentNotGeneric" in review["missingScenes"][0]


def test_visual_frame_review_evidence_blocks_unreviewed_source_frames():
    review = compose_ffmpeg._build_visual_frame_review_evidence(
        {
            "projectId": "unreviewed-source-frames",
            "internetSourceProofMode": True,
            "internetSourceContextRequired": True,
            "scenes": [
                {
                    "sceneId": "scene-01",
                    "captionPurpose": "proof",
                    "sourceContext": {"intentRole": "proof"},
                }
            ],
            "assets": [
                {
                    "provider": "upload",
                    "role": "visual",
                    "sceneId": "scene-01",
                    "kind": "video",
                    "sourceOrigin": "internet-meme-gif",
                    "sourceUrl": "https://upload.wikimedia.org/example/random.gif",
                    "sourceMediaKind": "gif",
                }
            ],
        }
    )

    assert review["status"] == "fail"
    assert "visualFrameReview" in review["missingFields"]
    assert "allSourceScenesFrameReviewed" in review["missingFields"]


def test_visual_frame_review_evidence_blocks_shake_reuse_and_caption_tts_gaps():
    review = compose_ffmpeg._build_visual_frame_review_evidence(
        {
            "projectId": "old-style-human-review",
            "internetSourceProofMode": True,
            "internetSourceContextRequired": True,
            "visualFrameReview": {
                "contactSheetPath": "storage/renders/old-style-human-review/contact.jpg",
                "reviewerType": "contact-sheet-human",
                "reviewNotes": "This old review only says the source is visible and captions are not covering it, but it does not inspect playback shake, source reuse, or whether captions and TTS actually match.",
                "sourceDominanceVerdict": "pass",
                "captionOcclusionVerdict": "pass",
                "layoutNaturalnessVerdict": "pass",
                "ttsCaptionSyncVerdict": "pass",
                "endingResolutionVerdict": "pass",
                "sceneReviews": {
                    "scene-01": {
                        "sourceVisibleVerdict": "pass",
                        "sourceDominanceVerdict": "pass",
                        "captionClearVerdict": "pass",
                        "review": "Source is large enough and caption is clear, but this does not cover motion stability or source repetition.",
                    }
                },
            },
            "scenes": [
                {
                    "sceneId": "scene-01",
                    "captionPurpose": "proof",
                    "sourceContext": {"intentRole": "proof"},
                }
            ],
            "assets": [
                {
                    "provider": "upload",
                    "role": "visual",
                    "sceneId": "scene-01",
                    "kind": "video",
                    "sourceOrigin": "internet-meme-gif",
                    "sourceUrl": "https://upload.wikimedia.org/example/random.gif",
                    "sourceMediaKind": "gif",
                }
            ],
        }
    )

    assert review["status"] == "fail"
    assert "captionTtsHumanVerdict=pass" in review["missingFields"]
    assert "motionStabilityVerdict=pass" in review["missingFields"]
    assert "sourceRepetitionVerdict=pass" in review["missingFields"]
    assert "captionTtsReview>=80" in review["missingFields"]
    assert "motionStabilityReview>=80" in review["missingFields"]
    assert "sourceRepetitionReview>=80" in review["missingFields"]
    assert "scene-01:motionStabilityVerdict=pass,sourceRepetitionVerdict=pass" in review["missingScenes"]


def test_render_quality_report_blocks_contextless_internet_gif_source(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "contextless-internet-gif-proof-test",
        "topic": "AI-only Shorts feel fake when they have no real source",
        "templateType": "authentic_vlog",
        "renderPurpose": "source-first internet-meme-gif quality proof",
        "sourceFirstRequired": True,
        "internetSourceProofMode": True,
        "internetSourceAcquisitionRequired": True,
        "internetSourceContextRequired": True,
        "viewerTakeaway": {
            "understood": "Fetched GIFs need source context, not just a local file.",
            "action": "Bind each internet source to a scene purpose before render.",
            "feeling": "specific",
        },
        "qualityRatchet": {
            "previousBaseline": "Random GIF proof passed without a topic.",
            "rejectionCause": "The source did not explain why it belonged in the scene.",
            "changedLever": "internet source context gate",
            "expectedVisibleImprovement": "A contextless GIF should be blocked before publish review.",
            "actualProof": "Render report fails internetSourceContext.",
            "nextRatchet": "Add a topic, scene purpose, viewer job, and media choice rationale.",
        },
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Random source beat",
                "subtitleText": "맥락 없는 GIF",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "captionDisplayDurationSec": 1.2,
                "sourceRationale": "Operator selected this fetched internet GIF because it was available.",
                "continuityNote": "Single source proof scene.",
                "hookNote": "The clip moves in the first second.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "First frame is readable.",
                "audioMixReviewNote": "TTS is audible over the local BGM bed.",
                "platformComparisonNote": "Source-led Korean Shorts need source fit proof.",
                "layoutVariantKey": "source-proof-hook",
                "layoutVariantNote": "Main proof object with captions outside the subject zone.",
                "visualSourceIntent": "internet-meme-gif",
                "sourceUrl": "https://upload.wikimedia.org/example/random.gif",
                "sourceLocalPath": "storage/source-acquisition/contextless/raw/random.gif",
                "sourceSha256": "a" * 64,
                "sourceBytes": 12000,
                "sourceMediaKind": "gif",
                "sourceFetchStatus": "fetched",
                "sourceAcquisitionVerdict": "pass",
                "sourceAcquisitionReview": "Operator verified this direct GIF source was fetched locally with hash, byte size, source URL, and scene fit before render.",
                "captionCollisionReview": "Caption is placed in a safe zone and does not cover the moving source subject or platform UI.",
                "captionCollisionVerdict": "pass",
                "antiAiNaturalnessVerdict": "pass",
                "naturalnessReviewNote": "This test intentionally omits scene source context so the new gate can block it.",
                "actionMotivation": "The GIF motion is visible.",
                "worldContinuityNote": "Single scene proof.",
                "endingPurpose": "payoff",
                "endingPacingReview": "The final beat closes the context-gate test instead of cutting off abruptly.",
                "finalTakeawayReview": "Viewer leaves understanding that fetched media without scene context is not enough.",
                "endingVerdict": "pass",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "internet-meme-gif",
                "sourceType": "meme-gif",
                "sourcePath": "storage/source-acquisition/contextless/raw/random.gif",
                "sourceUrl": "https://upload.wikimedia.org/example/random.gif",
                "sourceLocalPath": "storage/source-acquisition/contextless/raw/random.gif",
                "sourceSha256": "a" * 64,
                "sourceBytes": 12000,
                "sourceMediaKind": "gif",
                "sourceFetchStatus": "fetched",
                "sourceAcquisitionVerdict": "pass",
                "sourceAcquisitionReview": "Operator verified this direct GIF source was fetched locally with hash, byte size, source URL, and scene fit before render.",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
            {
                "provider": "local-bgm",
                "role": "audio",
                "sceneId": "global",
                "kind": "bgm",
                "sourceOrigin": "local-library",
                "sourcePath": "assets/bgm/editorial/source-proof-bed.mp3",
                "sourceLabel": "source-proof-bed.mp3",
                "sourceUrl": "https://example.invalid/free/source-proof-bed",
                "sourceLicense": "CC0 test fixture",
                "candidateCount": 2,
                "selectionMethod": "stable-hash",
                "selectionKey": "contextless-internet-gif-proof",
            },
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "contextless-internet-gif-proof.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["internetSourceAcquisition"]["status"] == "pass"
    assert report["checks"]["internetSourceContext"]["status"] == "fail"
    assert "scenePurpose>=12" in report["checks"]["internetSourceContext"]["detail"]
    assert report["checks"]["sourceFirstSourceGate"]["status"] == "fail"
    assert report["gateSystem"]["status"] == "blocked"


def test_render_quality_report_blocks_internet_source_without_text_layout_integration(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "internet-source-decoupled-text-layout-test",
        "topic": "AI-only Shorts feel fake when they have no real source",
        "templateType": "authentic_vlog",
        "renderPurpose": "source-first internet-meme-gif quality proof",
        "sourceFirstRequired": True,
        "internetSourceProofMode": True,
        "internetSourceAcquisitionRequired": True,
        "internetSourceContextRequired": True,
        "viewerTakeaway": {
            "understood": "Fetched sources still need matching viewer text and layout.",
            "action": "Reject source-led scenes when captions and TTS ignore the selected source.",
            "feeling": "specific",
        },
        "qualityRatchet": {
            "previousBaseline": "Source acquisition could pass while text and layout stayed generic.",
            "rejectionCause": "The selected GIF did not shape the viewer-facing edit.",
            "changedLever": "internet source editorial integration gate",
            "expectedVisibleImprovement": "The gate blocks scenes where source context is separate from caption, TTS, and layout.",
            "actualProof": "Render report fails internetSourceEditorialIntegration while internetSourceContext passes.",
            "nextRatchet": "Rewrite subtitle, narration, and layout notes around the source context.",
        },
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Generic source beat",
                "subtitleText": "오늘의 핵심 장면",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "captionPurpose": "proof",
                "captionDisplayDurationSec": 1.2,
                "sourceRationale": "Operator selected this fetched internet GIF because the reaction beat supports the fake-card critique.",
                "continuityNote": "Single source proof scene.",
                "hookNote": "The clip moves in the first second.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "First frame is readable.",
                "audioMixReviewNote": "TTS is audible over the local BGM bed.",
                "platformComparisonNote": "Source-led Korean Shorts need source fit proof.",
                "layoutVariantKey": "source-proof-hook",
                "layoutVariantNote": "Generic proof layout keeps the subject visible and the caption in the safe zone.",
                "visualSourceIntent": "internet-meme-gif",
                "sourceUrl": "https://upload.wikimedia.org/example/reaction.gif",
                "sourceLocalPath": "storage/source-acquisition/decoupled/raw/reaction.gif",
                "sourceSha256": "b" * 64,
                "sourceBytes": 12000,
                "sourceMediaKind": "gif",
                "sourceFetchStatus": "fetched",
                "sourceAcquisitionVerdict": "pass",
                "sourceAcquisitionReview": "Operator verified this direct GIF source was fetched locally with hash, byte size, source URL, and scene fit before render.",
                "sourceContext": {
                    "topic": "AI-only Shorts feel fake when they have no real source",
                    "scenePurpose": "replace an internal fake meme card with a real fetched reaction source",
                    "viewerJob": "show why source-first editing feels more concrete than generated filler",
                    "selectionRationale": "This fetched GIF is used for the reaction beat because its looped motion directly supports the criticism of fake meme cards.",
                    "mediaChoiceRationale": "GIF is selected here because the motion is the point of the joke and the viewer response.",
                    "motionFit": "The looped motion makes the reaction readable without needing a separate explanation.",
                    "verdict": "pass",
                },
                "captionCollisionReview": "Caption is placed in a safe zone and does not cover the moving source subject or platform UI.",
                "captionCollisionVerdict": "pass",
                "antiAiNaturalnessVerdict": "pass",
                "naturalnessReviewNote": "This proof uses a real fetched internet GIF rather than an invented AI card.",
                "actionMotivation": "The GIF motion is used as commentary evidence.",
                "worldContinuityNote": "Single source proof.",
                "endingPurpose": "payoff",
                "endingPacingReview": "The final beat closes the source integration test instead of cutting off abruptly.",
                "finalTakeawayReview": "Viewer leaves understanding that text and layout must follow the source context.",
                "endingVerdict": "pass",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "internet-meme-gif",
                "sourceType": "meme-gif",
                "sourcePath": "storage/source-acquisition/decoupled/raw/reaction.gif",
                "sourceUrl": "https://upload.wikimedia.org/example/reaction.gif",
                "sourceLocalPath": "storage/source-acquisition/decoupled/raw/reaction.gif",
                "sourceSha256": "b" * 64,
                "sourceBytes": 12000,
                "sourceMediaKind": "gif",
                "sourceFetchStatus": "fetched",
                "sourceAcquisitionVerdict": "pass",
                "sourceAcquisitionReview": "Operator verified this direct GIF source was fetched locally with hash, byte size, source URL, and scene fit before render.",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
            {
                "provider": "local-bgm",
                "role": "audio",
                "sceneId": "global",
                "kind": "bgm",
                "sourceOrigin": "local-library",
                "sourcePath": "assets/bgm/editorial/source-proof-bed.mp3",
                "sourceLabel": "source-proof-bed.mp3",
                "sourceUrl": "https://example.invalid/free/source-proof-bed",
                "sourceLicense": "CC0 test fixture",
                "candidateCount": 2,
                "selectionMethod": "stable-hash",
                "selectionKey": "internet-source-decoupled-text-layout",
            },
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "internet-source-decoupled.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["internetSourceAcquisition"]["status"] == "pass"
    assert report["checks"]["internetSourceContext"]["status"] == "pass"
    assert report["checks"]["internetSourceEditorialIntegration"]["status"] == "fail"
    assert "viewerFacingSubtitle" in report["checks"]["internetSourceEditorialIntegration"]["detail"]
    assert report["checks"]["sourceFirstSourceGate"]["status"] == "pass"
    assert report["gateSystem"]["status"] == "blocked"


def test_conversational_copy_style_blocks_report_style_korean_source_copy():
    review = compose_ffmpeg._build_conversational_copy_style_review(
        {
            "projectId": "stiff-korean-source-copy-test",
            "internetSourceProofMode": True,
            "internetSourceContextRequired": True,
            "copyStylePrompt": {
                "tone": "구어체 쇼츠: 친구한테 바로 말하듯 설명한다.",
                "captionRule": "자막은 질문, 반응, 짧은 payoff처럼 읽혀야 하며 장면 라벨을 쓰지 않는다.",
                "narrationRule": "TTS 대본은 말하듯 쓰고 제작 메타 표현이나 보고서식 종결어미를 피한다.",
                "forbiddenPatterns": ["장면", "에서 시작", "확인합니다", "source beat"],
                "referenceTakeaways": [
                    "첫 비트는 호기심이나 반응으로 시작한다.",
                    "온스크린 텍스트는 한 호흡에 읽히게 짧게 유지한다.",
                ],
            },
            "scenes": [
                {
                    "sceneId": "scene-01",
                    "subtitleText": "깃털은 왜 늦지 않을까?",
                    "narrationText": "공기 없는 달에서 시작합니다. 같이 떨어지는 장면을 확인합니다.",
                    "captionPurpose": "hook",
                }
            ],
            "assets": [
                {
                    "role": "visual",
                    "sceneId": "scene-01",
                    "sourceOrigin": "internet-image",
                    "sourceType": "internet-image",
                    "sourceMediaKind": "image",
                    "sourceFetchStatus": "fetched",
                }
            ],
        }
    )

    assert review["status"] == "fail"
    assert "narrationFormalEnding" in review["missingScenes"][0]
    assert "viewerCopyForbiddenTerms" in review["missingScenes"][0]


def test_conversational_copy_style_blocks_bare_label_source_questions():
    review = compose_ffmpeg._build_conversational_copy_style_review(
        {
            "projectId": "bare-label-source-copy-test",
            "internetSourceProofMode": True,
            "internetSourceContextRequired": True,
            "templateType": "authentic_vlog",
            "copyStylePrompt": {
                "tone": "구어체 쇼츠: 친구한테 바로 말하듯 설명한다.",
                "captionRule": "자막은 라벨형 질문이나 명사만 나열한 source label이 아니라 hook, turn, payoff가 있는 반응이어야 한다.",
                "narrationRule": "TTS 대본은 짧아도 viewer task와 perceptual turn을 말해야 하며, 라벨만 반복하지 않는다.",
                "scriptQualityRule": "Bare label and noun-only captions fail; each beat needs a hook, viewer turn, or payoff action.",
                "forbiddenPatterns": ["장면", "source beat", "proof scene", "caption label"],
                "referenceTakeaways": [
                    "첫 비트는 호기심이나 반응으로 시작한다.",
                    "각 소스는 무엇이 바뀌는지 한 문장으로 말한다.",
                ],
            },
            "scenes": [
                {
                    "sceneId": "scene-01",
                    "subtitleText": "오리? 토끼?",
                    "narrationText": "오리 토끼 보여요?",
                    "captionPurpose": "proof",
                    "voiceoverStyle": "short-action-callout",
                    "durationSec": 2.8,
                }
            ],
            "assets": [
                {
                    "role": "visual",
                    "sceneId": "scene-01",
                    "kind": "image",
                    "sourceOrigin": "internet-image",
                    "sourceType": "internet-image",
                    "sourceMediaKind": "image",
                    "sourceFetchStatus": "fetched",
                }
            ],
        }
    )

    assert review["status"] == "fail"
    assert "subtitleBareLabelQuestion" in review["missingScenes"][0]


def test_conversational_copy_style_blocks_thin_reaction_tts_arc():
    review = compose_ffmpeg._build_conversational_copy_style_review(
        {
            "projectId": "thin-reaction-copy-test",
            "internetSourceProofMode": True,
            "internetSourceContextRequired": True,
            "templateType": "authentic_vlog",
            "copyStylePrompt": {
                "tone": "구어체 쇼츠: 친구한테 바로 말하듯 설명한다.",
                "captionRule": "자막은 라벨형 질문이나 명사만 나열한 source label이 아니라 hook, turn, payoff가 있는 반응이어야 한다.",
                "narrationRule": "TTS 대본은 짧아도 viewer task와 perceptual turn을 말해야 하며, 라벨만 반복하지 않는다.",
                "scriptQualityRule": "Bare label and noun-only captions fail; each beat needs a hook, viewer turn, or payoff action.",
                "forbiddenPatterns": ["장면", "source beat", "proof scene", "caption label"],
                "referenceTakeaways": [
                    "첫 비트는 호기심이나 반응으로 시작한다.",
                    "각 소스는 무엇이 바뀌는지 한 문장으로 말한다.",
                ],
            },
            "scenes": [
                {
                    "sceneId": "scene-01",
                    "subtitleText": "움직임 먼저 보여요?",
                    "narrationText": "움직임 착시 먼저 보여요?",
                    "captionPurpose": "hook",
                    "voiceoverStyle": "short-action-callout",
                    "durationSec": 2.8,
                },
                {
                    "sceneId": "scene-02",
                    "subtitleText": "얼굴 경계선 바뀌죠?",
                    "narrationText": "얼굴 경계선이 바뀌죠?",
                    "captionPurpose": "context",
                    "voiceoverStyle": "short-action-callout",
                    "durationSec": 2.8,
                },
                {
                    "sceneId": "scene-03",
                    "subtitleText": "평행선 댓글 갈리죠?",
                    "narrationText": "같은 평행선도 댓글 갈리죠?",
                    "captionPurpose": "payoff",
                    "voiceoverStyle": "short-action-callout",
                    "durationSec": 3.2,
                },
            ],
            "assets": [
                {
                    "role": "visual",
                    "sceneId": scene_id,
                    "kind": "image",
                    "sourceOrigin": "internet-image",
                    "sourceType": "internet-image",
                    "sourceMediaKind": "image",
                    "sourceFetchStatus": "fetched",
                }
                for scene_id in ("scene-01", "scene-02", "scene-03")
            ],
        }
    )

    assert review["status"] == "fail"
    assert "scene-01:hookNarrationTooThin,narrationThinReactionLine" in review["missingScenes"]
    assert "scene-02:contextNarrationTooThin,narrationThinReactionLine" in review["missingScenes"]
    assert "scene-03:payoffNarrationTooThin" in review["missingScenes"]


def test_conversational_copy_style_accepts_sentence_copy_with_viewer_turn():
    review = compose_ffmpeg._build_conversational_copy_style_review(
        {
            "projectId": "viewer-turn-source-copy-test",
            "internetSourceProofMode": True,
            "internetSourceContextRequired": True,
            "templateType": "authentic_vlog",
            "copyStylePrompt": {
                "tone": "구어체 쇼츠: 친구한테 바로 말하듯 설명한다.",
                "captionRule": "자막은 라벨형 질문이나 명사만 나열한 source label이 아니라 hook, turn, payoff가 있는 반응이어야 한다.",
                "narrationRule": "TTS 대본은 짧아도 viewer task와 perceptual turn을 말해야 하며, 라벨만 반복하지 않는다.",
                "scriptQualityRule": "Bare label and noun-only captions fail; each beat needs a hook, viewer turn, or payoff action.",
                "forbiddenPatterns": ["장면", "source beat", "proof scene", "caption label"],
                "referenceTakeaways": [
                    "첫 비트는 호기심이나 반응으로 시작한다.",
                    "각 소스는 무엇이 바뀌는지 한 문장으로 말한다.",
                ],
            },
            "scenes": [
                {
                    "sceneId": "scene-01",
                    "subtitleText": "둘 중 뭐가 먼저 보여요?",
                    "narrationText": "오리였던 선이 다시 보면 토끼 귀로 뒤집히는 순간 보이죠?",
                    "captionPurpose": "proof",
                    "voiceoverStyle": "short-action-callout",
                    "durationSec": 2.8,
                }
            ],
            "assets": [
                {
                    "role": "visual",
                    "sceneId": "scene-01",
                    "kind": "image",
                    "sourceOrigin": "internet-image",
                    "sourceType": "internet-image",
                    "sourceMediaKind": "image",
                    "sourceFetchStatus": "fetched",
                }
            ],
        }
    )

    assert review["status"] == "pass"
    assert review["reviewedScenes"] == ["scene-01"]


def test_tts_pacing_alignment_blocks_rap_speed_source_narration():
    review = compose_ffmpeg._build_tts_pacing_alignment_review(
        {
            "projectId": "rap-speed-tts-source-test",
            "internetSourceProofMode": True,
            "internetSourceContextRequired": True,
            "copyStylePrompt": {
                "tone": "구어체 쇼츠",
                "captionRule": "자막은 짧은 반응과 요약으로 쓰되 대본 핵심과 괴리되지 않게 둔다.",
                "narrationRule": "TTS 대본은 말하듯 짧게 쓰고 제작 메타 표현을 피한다.",
                "ttsPacingRule": "TTS 속도와 호흡을 장면 길이에 맞추며, 자막은 spoken idea와 같은 밀도로 맞춘다.",
                "forbiddenPatterns": ["장면", "에서 시작", "확인합니다"],
                "referenceTakeaways": [
                    "첫 비트는 호기심이나 반응으로 시작한다.",
                    "온스크린 텍스트는 한 호흡에 읽히게 짧게 유지한다.",
                ],
            },
            "scenes": [
                {
                    "sceneId": "scene-01",
                    "subtitleText": "왜 안 늦지?",
                    "narrationText": "지구에서는 깃털이 늦게 떨어지잖아요. 그런데 달에는 깃털을 붙잡을 공기가 거의 없어요. 그래서 여기서는 결과가 달라져요.",
                    "durationSec": 3.35,
                    "captionPurpose": "hook",
                }
            ],
            "assets": [
                {
                    "role": "visual",
                    "sceneId": "scene-01",
                    "sourceOrigin": "internet-image",
                    "sourceType": "internet-image",
                    "sourceMediaKind": "image",
                    "sourceFetchStatus": "fetched",
                },
                {
                    "role": "audio",
                    "sceneId": "scene-01",
                    "kind": "voiceover",
                    "provider": "edge-tts",
                    "audioDurationFit": {
                        "inputDurationSec": 10.06,
                        "targetDurationSec": 3.35,
                        "speed": 3.002,
                        "mode": "tempo-fit",
                    },
                },
            ],
        }
    )

    assert review["status"] == "fail"
    assert "audioTempoFitSpeed" in review["missingScenes"][0]
    assert "narrationKoreanCharsPerSec" in review["missingScenes"][0]


def test_render_quality_report_accepts_source_recovery_replacement_as_grok_curation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "grok-source-recovery-curated",
        "templateType": "authentic_vlog",
        "audioDesignMode": "no-voice",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Recovered routine hook",
                "subtitleText": "퇴근 후, 첫 동작부터",
                "visualKind": "video",
                "captionPreset": "top-hook",
                "captionDisplayDurationSec": 1.2,
                "sourceRationale": "Source recovery acceptance selected the replacement MP4 for rerender.",
                "continuityNote": "Same worker, desk, notebook, and warm office palette continue through the scene.",
                "hookNote": "The replacement starts visible phone-down motion inside the first two seconds.",
                "originalityEvidence": "Source recovery accepted replacement MP4 with recorded path and sha256.",
                "qualityReviewNote": "Operator accepted this source-recovery replacement after phone/source-fit review.",
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Phone-sized first-frame review passed for the replacement.",
                "audioMixReviewNote": "No-voice BGM and local ambience carry the source-recovery replacement.",
                "platformComparisonNote": "Replacement cleared source-fit review against Korean short-form routine references.",
                "layoutVariantKey": "grok-first-hook",
                "visualSourceIntent": "grok",
                "selectedFileName": "scene-01-fixed.mp4",
                "selectedCandidateSummary": (
                    "Source recovery acceptance selected this replacement after hook, motion, phone-frame, "
                    "source-fit, caption-safe, and continuity review."
                ),
                "sourceProvenanceConfirmed": True,
                "sourceProvenanceNote": "Source recovery acceptance recorded replacement path and sha256 before rerender.",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "grok-handoff",
                "sourcePath": "storage/source-recovery/routine/scene-01-fixed.mp4",
                "candidateCount": 1,
                "sourceRecoveryReplacement": True,
                "sourceRecoveryAcceptanceSha256": "acceptance-sha",
                "acceptedReplacementSha256": "replacement-sha",
                "sourceProvenance": {
                    "status": "local-mp4-source-unverified",
                    "acceptAsGrokMainSource": True,
                    "sourceKind": "source-recovery-accepted-replacement",
                },
            },
            {
                "provider": "local-bgm",
                "role": "audio",
                "sceneId": "global",
                "kind": "bgm",
                "sourceOrigin": "local-library",
                "sourcePath": "assets/bgm/tech-house/minimal.mp3",
                "sourceLabel": "Minimal test bed",
                "sourceUrl": "https://example.invalid/free/minimal",
                "sourceLicense": "Free test fixture",
                "candidateCount": 2,
                "selectionMethod": "stable-hash",
                "selectionKey": "grok-source-recovery-curated",
            },
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "grok-source-recovery-curated.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["missingGrokSourceCurationScenes"] == []
    assert summary["missingGrokCandidateComparisonScenes"] == []
    assert report["productionReview"]["scenes"][0]["grokSourceCuration"]["sourceRecoveryReplacement"] is True
    assert report["productionReview"]["scenes"][0]["grokSourceCuration"]["ready"] is True
    assert report["checks"]["grokSourceCuration"]["status"] == "pass"


def test_render_quality_report_blocks_rejected_grok_source_review(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "grok-rejected-source-review",
        "templateType": "authentic_vlog",
        "audioDesignMode": "no-voice",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Shoulder reset",
                "subtitleText": "어깨 힘 빼기",
                "visualKind": "video",
                "captionPreset": "top-hook",
                "captionDisplayDurationSec": 1.2,
                "sourceRationale": "Operator compared two Grok handoff MP4s and selected the local filename for testing.",
                "continuityNote": "Same worker, desk, notebook, and warm office palette continue through the scene.",
                "hookNote": "The shoulder motion starts in the first two seconds.",
                "originalityEvidence": "Already-saved Grok MP4 imported from the local handoff incoming folder.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Opening frame is clean and has no baked-in text.",
                "audioMixReviewNote": "No-voice BGM and local ambience carry the short visual beat.",
                "platformComparisonNote": "Compared against quiet Korean routine Shorts for pacing and caption restraint.",
                "layoutVariantKey": "grok-first-hook",
                "visualSourceIntent": "grok",
                "selectedFileName": "scene-01-v2-cleaner-but-rejected.mp4",
                "selectedCandidateSummary": (
                    "Selected from two Grok takes for technical comparison, but local source review rejected it for upload."
                ),
                "sourceProvenanceConfirmed": True,
                "sourceProvenanceNote": "Operator confirmed this is an already-saved local MP4, not a fresh browser download prompt.",
                "selectedCandidate": {
                    "fileName": "scene-01-v2-cleaner-but-rejected.mp4",
                    "reviewDecision": "rejected",
                    "sourceProvenance": {
                        "status": "local-mp4-source-unverified",
                        "acceptAsGrokMainSource": True,
                    },
                },
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "grok-handoff",
                "sourcePath": "storage/grok-handoffs/routine/scene-01-v2-cleaner-but-rejected.mp4",
                "candidateCount": 2,
            },
            {
                "provider": "local-bgm",
                "role": "audio",
                "sceneId": "global",
                "kind": "bgm",
                "sourceOrigin": "local-library",
                "sourcePath": "assets/bgm/tech-house/minimal.mp3",
                "sourceLabel": "Minimal test bed",
                "sourceUrl": "https://example.invalid/free/minimal",
                "sourceLicense": "Free test fixture",
                "candidateCount": 2,
                "selectionMethod": "stable-hash",
                "selectionKey": "grok-rejected-source-review",
            },
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "grok-rejected-source-review.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["grokSourceReviewVerdictScenes"] == []
    assert summary["rejectedGrokSourceReviewScenes"] == ["scene-01"]
    assert summary["missingGrokSourceCurationScenes"] == ["scene-01"]
    grok_fit = report["productionReview"]["scenes"][0]["grokSourceCuration"]
    assert grok_fit["sourceReviewVerdictStatus"] == "fail"
    curation = report["checks"]["grokSourceCuration"]
    assert curation["status"] == "fail"
    assert "rejectedSourceReviewScenes=['scene-01']" in curation["detail"]
    publish_criterion = next(item for item in report["publishReadiness"]["criteria"] if item["key"] == "grokSourceCuration")
    assert publish_criterion["status"] == "fail"
    assert publish_criterion["required"] is True
    assert any("direct-import or already-saved-local provenance" in item for item in report["publishReadiness"]["requiredFixes"])
    assert report["publishReadiness"]["status"] == "blocked"
    assert report["topTierReadiness"]["status"] == "needs-publish-rework"


def test_render_quality_report_rejects_no_voice_without_audio_bed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "silent-no-voice",
        "templateType": "persona_story",
        "audioDesignMode": "no-voice",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Silent Grok beat",
                "subtitleText": "첫 움직임",
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator accepted this Grok MP4 for visible first-second motion.",
                "continuityNote": "Same character, palette, and handheld camera language.",
                "hookNote": "The subject moves in the first two seconds.",
                "originalityEvidence": "Grok app/web MP4 imported through handoff; no paid API.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "audioMixReviewNote": "No voice is intended, but the bed is missing in this fixture.",
                "visualSourceIntent": "grok",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "grok-handoff",
                "sourcePath": "storage/grok-handoffs/silent/scene-01.grok.mp4",
            }
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "silent.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["noVoiceAudioDesignScenes"] == ["scene-01"]
    assert summary["missingNoVoiceAudioScenes"] == ["scene-01"]
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "fail"
    assert "missingNoVoiceAudioScenes=['scene-01']" in report["checks"]["ttsNarrationEvidence"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"


def test_render_quality_report_rejects_sparse_slow_caption_layout(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    scenes = []
    assets = []
    local_media = []
    for idx in range(5):
        scene_id = f"scene-{idx + 1:02d}"
        scenes.append(
            {
                "sceneId": scene_id,
                "title": f"Beat {idx + 1}",
                "subtitleText": "첫 2초: 손과 향" if idx == 0 else f"Detail {idx + 1}",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook" if idx == 0 else "none",
                "startSec": idx * 4.5,
                "endSec": (idx + 1) * 4.5,
                "durationSec": 4.5,
                "sourceRationale": f"Operator selected distinct moving clip {idx + 1}.",
                "continuityNote": "Warm cafe palette and slow camera move.",
                "hookNote": "The first two seconds show visible motion." if idx == 0 else "",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            }
        )
        assets.append({"provider": "upload", "role": "visual", "sceneId": scene_id, "kind": "video", "sourceOrigin": "uploaded"})
        assets.append({"provider": "edge-tts", "role": "audio", "sceneId": scene_id, "kind": "voiceover"})
        local_media.append({"sceneId": scene_id, "status": "uploaded", "outputKind": "video"})

    manifest = {"projectId": "sparse-caption-layout", "scenes": scenes, "assets": assets}

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "sparse.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 5, "generated": 0, "totalScenes": 5},
        local_media=local_media,
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["captionedSceneIds"] == ["scene-01"]
    assert summary["captionSparsePlan"] is True
    assert summary["longTopHookScenes"] == ["scene-01"]
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "pass"
    assert report["checks"]["captionLayoutReview"]["status"] == "fail"
    assert "captionSparsePlan=True" in report["checks"]["captionLayoutReview"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"


def test_render_quality_report_accepts_trimmed_top_hook_caption_duration(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    scenes = []
    assets = []
    local_media = []
    presets = ["top-hook", "lower-info", "center-short", "none"]
    for idx, preset in enumerate(presets):
        scene_id = f"scene-{idx + 1:02d}"
        scenes.append(
            {
                "sceneId": scene_id,
                "title": f"Beat {idx + 1}",
                "subtitleText": f"Viewer caption {idx + 1}",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": preset,
                "durationSec": 4.5,
                "captionDisplayDurationSec": 2.2 if preset == "top-hook" else 3.0,
                "sourceRationale": f"Operator selected distinct moving clip {idx + 1}.",
                "continuityNote": "Warm cafe palette and slow camera move.",
                "hookNote": "The first two seconds show visible motion." if idx == 0 else "",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            }
        )
        assets.append({"provider": "upload", "role": "visual", "sceneId": scene_id, "kind": "video", "sourceOrigin": "uploaded"})
        assets.append({"provider": "edge-tts", "role": "audio", "sceneId": scene_id, "kind": "voiceover"})
        local_media.append({"sceneId": scene_id, "status": "uploaded", "outputKind": "video"})

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest={"projectId": "trimmed-caption-layout", "scenes": scenes, "assets": assets},
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "trimmed.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 4, "generated": 0, "totalScenes": 4},
        local_media=local_media,
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["productionReview"]["summary"]["captionSparsePlan"] is False
    assert report["productionReview"]["summary"]["longTopHookScenes"] == []
    assert report["checks"]["captionLayoutReview"]["status"] == "pass"
    assert report["checks"]["captionDensityAndSafeZone"]["status"] == "pass"


def test_render_quality_report_blocks_missing_reference_edit_grammar(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "missing-reference-grammar",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Looks fine",
                "subtitleText": "The routine begins.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "captionDisplayDurationSec": 1.2,
                "sourceRationale": "Operator selected an owned moving clip for this scene.",
                "continuityNote": "Same desk and warm palette.",
                "hookNote": "Motion starts immediately.",
                "qualityReviewNote": "Subject is visible and the frame looks acceptable.",
                "visualQualityVerdict": "pass",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "uploaded",
                "sourcePath": "storage/uploads/reference-missing.mp4",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "reference-missing.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["referenceEditGrammarReady"] is False
    assert summary["missingReferenceEditGrammarScenes"] == ["scene-01"]
    assert "missing reference edit grammar scenes=['scene-01']" in summary["referenceEditGrammarIssues"]
    assert report["checks"]["referenceEditGrammar"]["status"] == "fail"
    criterion = next(item for item in report["publishReadiness"]["criteria"] if item["key"] == "referenceEditGrammar")
    assert criterion["status"] == "fail"
    assert report["publishReadiness"]["status"] == "blocked"


def test_render_quality_report_blocks_dense_shorts_captions(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "dense-caption-layout",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Dense hook",
                "subtitleText": "퇴근하고 집에 들어오자마자 모든 생각을 멈추는 아주 긴 첫 문장",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "captionDisplayDurationSec": 1.35,
                "sourceRationale": "Operator selected a moving Grok handoff hook clip.",
                "continuityNote": "Same subject, coat, and evening palette.",
                "hookNote": "Hand movement starts in the first second.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "visualSourceIntent": "grok",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "uploaded",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "dense.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["captionDensityIssueScenes"] == ["scene-01"]
    assert "too dense" in summary["captionDensityIssuesByScene"]["scene-01"]
    assert summary["captionSafeZonePolicy"]["lower-info"].startswith("lower-mid")
    assert report["checks"]["captionDensityAndSafeZone"]["status"] == "fail"
    assert report["publishReadiness"]["status"] == "blocked"
    assert any("burned-in captions" in item for item in report["publishReadiness"]["requiredFixes"])


def test_render_quality_report_blocks_captions_that_read_too_fast(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "too-fast-caption-layout",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Fast caption",
                "subtitleText": "손이 먼저 움직인다",
                "narrationText": "손이 먼저 움직입니다.",
                "visualKind": "video",
                "captionPreset": "top-hook",
                "captionDisplayDurationSec": 0.55,
                "sourceRationale": "Operator selected a moving Grok handoff hook clip.",
                "continuityNote": "Same subject and camera position.",
                "hookNote": "Hand movement starts in the first second.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "visualSourceIntent": "grok",
            }
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "fast-caption.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["captionDensityIssueScenes"] == ["scene-01"]
    assert "reads too fast" in summary["captionDensityIssuesByScene"]["scene-01"]
    assert report["checks"]["captionDensityAndSafeZone"]["status"] == "fail"
    assert report["publishReadiness"]["status"] == "blocked"


def test_render_quality_report_allows_tight_shortform_viewer_narration(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "tight-shortform-narration",
        "templateType": "authentic_vlog",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Coffee hook",
                "subtitleText": "오늘은 천천히",
                "narrationText": "커피 향이 올라오는 순간, 오늘의 속도가 조금 느려집니다.",
                "visualKind": "video",
                "captionPreset": "top-hook",
                "captionDisplayDurationSec": 2.2,
                "sourceRationale": "Operator uploaded a moving macro hook clip.",
                "continuityNote": "Warm cafe palette and slow camera move.",
                "hookNote": "Steam rises in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
            {
                "sceneId": "scene-02",
                "title": "Coffee action",
                "subtitleText": "손끝에서 시작",
                "narrationText": "뜨거운 물이 내려오면, 잔 안의 소리가 먼저 아침을 깨웁니다.",
                "visualKind": "video",
                "captionPreset": "lower-info",
                "captionDisplayDurationSec": 3.0,
                "sourceRationale": "Operator uploaded a moving extraction clip.",
                "continuityNote": "Warm cafe palette and slow camera move.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
            {"provider": "upload", "role": "visual", "sceneId": "scene-02", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-02", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "tight.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 2, "generated": 0, "totalScenes": 2},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "video"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["productionReview"]["summary"]["narrationMinCharsByScene"] == {
        "scene-01": 24,
        "scene-02": 24,
    }
    assert report["productionReview"]["summary"]["thinNarrationScenes"] == []
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "pass"


def test_render_quality_report_allows_short_action_voiceover_callout(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "short-action-callout",
        "templateType": "authentic_vlog",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Phone down",
                "subtitleText": "폰부터 뒤집기",
                "narrationText": "먼저, 폰을 뒤집어요.",
                "durationSec": 3.2,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "captionDisplayDurationSec": 1.05,
                "layoutVariantKey": "routine-action-command",
                "voiceoverStyle": "short-action-callout",
                "sourceRationale": "Operator selected a no-face hand/object action clip.",
                "continuityNote": "Desk, phone, and notebook remain in the same workspace.",
                "hookNote": "The phone turns down inside the first beat.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "callout.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    scene = report["productionReview"]["scenes"][0]
    assert summary["thinNarrationScenes"] == []
    assert summary["shortVoiceoverCalloutScenes"] == ["scene-01"]
    assert scene["shortVoiceoverCalloutApproved"] is True
    assert scene["requiredNarrationTextLength"] == 24
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "pass"
    assert report["publishReadiness"]["status"] == "ready"


def test_render_quality_report_flags_thin_longform_narration(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "thin-longform-narration",
        "templateType": "longform_deep_dive",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Long-form chapter",
                "subtitleText": "A chapter title is not enough.",
                "narrationText": "Short narration.",
                "visualKind": "video",
                "captionPreset": "lower-info",
                "sourceRationale": "Operator uploaded a relevant documentary-style clip.",
                "continuityNote": "Neutral palette and slow movement match the chapter.",
                "hookNote": "The document appears in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "longform-thin.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    scene = report["productionReview"]["scenes"][0]
    assert summary["thinNarrationScenes"] == ["scene-01"]
    assert summary["narrationMinCharsByScene"] == {"scene-01": 80}
    assert scene["requiredNarrationTextLength"] == 80
    assert report["checks"]["ttsNarrationEvidence"]["status"] == "fail"
    assert "requiredChars={'scene-01': 80}" in report["checks"]["ttsNarrationEvidence"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"


def test_render_quality_report_blocks_video_audio_duration_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "width": 1080,
                        "height": 1920,
                        "avg_frame_rate": "30/1",
                        "duration": "6.033333",
                    },
                    {
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "duration": "22.570000",
                    },
                ],
                "format": {"duration": "22.570000"},
            },
            "fake ffprobe",
        ),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "duration-mismatch",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Short video stream",
                "subtitleText": "Duration mismatch",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected a relevant moving hook clip.",
                "continuityNote": "Warm palette and slow camera motion.",
                "hookNote": "The subject moves in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "windows-speech", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "duration-mismatch.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["checks"]["outputSpec"]["status"] == "fail"
    assert "videoDuration=6.033333" in report["checks"]["outputSpec"]["detail"]
    assert "audioDuration=22.57" in report["checks"]["outputSpec"]["detail"]
    assert report["publishReadiness"]["status"] == "blocked"


def test_render_quality_report_fails_near_frozen_source_video(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("fail", ["scene-01"]),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "near-frozen-source",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Still mp4",
                "subtitleText": "Looks like motion",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this clip, but motion audit should catch the freeze.",
                "continuityNote": "Warm cafe palette.",
                "hookNote": "Claimed hook.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "upload",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "uploaded",
                "sourcePath": "storage/inputs/near-frozen-source/uploads/scene-01/still.mp4",
            },
            {"provider": "edge-tts", "role": "audio"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "ready.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["sourceMotionEvidence"]["lowMotionSceneIds"] == ["scene-01"]
    assert report["checks"]["sourceMotionEvidence"]["status"] == "fail"
    assert report["checks"]["movingClipPriority"]["status"] == "fail"
    assert report["publishReadiness"]["status"] == "blocked"
    assert any("real video clip" in item for item in report["publishReadiness"]["requiredFixes"])


def test_render_quality_report_counts_local_model_handoff_as_non_stock(tmp_path):
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "local-model-qa",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Neon hook",
                "subtitleText": "Neon alley",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Wan clip was selected after checking stable alley motion.",
                "continuityNote": "Same alley, wet pavement, matching color palette.",
                "hookNote": "Reflection appears immediately in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualSourceIntent": "wan",
            },
        ],
        "assets": [
            {
                "provider": "wan",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "uploaded",
                "sourceGenerator": "wan",
                "sourceGeneratorRequestPath": "storage/local-video/publish-ready-local/scene-01/scene-01.wan.request.json",
                "sourceGeneratorPromptPath": "storage/local-video/publish-ready-local/scene-01/scene-01.wan.prompt.txt",
                "sourceGeneratorLogPath": "storage/local-video/publish-ready-local/scene-01/scene-01.wan.command.log",
                "sourceGeneratorCommand": "python wan.py --request scene-01.wan.request.json",
            },
            {"provider": "edge-tts", "role": "audio"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "missing.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["localModelVideoScenes"] == 1
    assert summary["uploadedVideoScenes"] == 0
    assert summary["stockOnly"] is False
    assert report["checks"]["stockOnlyCaveat"]["status"] == "pass"


def test_publish_readiness_ready_for_valid_local_model_clip(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "publish-ready-local",
        "templateType": "persona_story",
        "sourceFirstRequired": True,
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Neon hook",
                "subtitleText": "Neon alley",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Wan clip was manually selected for stable camera motion.",
                "continuityNote": "Same wet alley, magenta/cyan palette, no prop drift.",
                "hookNote": "Bright reflection appears in the first two seconds.",
                "originalityEvidence": "Local Wan MP4 generated offline from the stored prompt; no paid API or baked-in text.",
                "qualityReviewNote": "Subject is visible, caption is top-safe, no watermark, and motion remains stable.",
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Use the bright reflection first frame; no baked-in text or watermark.",
                "audioMixReviewNote": "Narration is intelligible, BGM stays under voice, and no clipping is audible.",
                "platformComparisonNote": "Compared against current AI-assisted Shorts: hook, motion, caption placement, and artifact level are acceptable.",
                "visualSourceIntent": "wan",
            }
        ],
        "assets": [
            {
                "provider": "wan",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "uploaded",
                "sourceGenerator": "wan",
                "sourceGeneratorRequestPath": "storage/local-video/publish-ready-local/scene-01/scene-01.wan.request.json",
                "sourceGeneratorPromptPath": "storage/local-video/publish-ready-local/scene-01/scene-01.wan.prompt.txt",
                "sourceGeneratorLogPath": "storage/local-video/publish-ready-local/scene-01/scene-01.wan.command.log",
                "sourceGeneratorCommand": "python wan.py --request scene-01.wan.request.json",
            },
            {"provider": "edge-tts", "role": "audio"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "ready.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["sourceFirstRequired"] is True
    assert summary["sourceFirstReady"] is True
    assert summary["sourceFirstGeneratedSceneIds"] == ["scene-01"]
    assert summary["sourceFirstBlockedSceneIds"] == []
    assert report["checks"]["sourceFirstSourceGate"]["status"] == "pass"
    readiness = report["publishReadiness"]
    assert readiness["status"] == "ready"
    assert readiness["requiredFixes"] == []
    assert readiness["recommendedFixes"] == []
    assert readiness["score"]["passed"] == readiness["score"]["total"]
    assert report["checks"]["publishReadinessGate"]["status"] == "pass"
    channel = report["channelReadiness"]
    assert channel["status"] == "channel-ready"
    assert channel["requiredFixes"] == []
    assert channel["summary"]["originalClipScenes"] == 1
    assert channel["summary"]["firstSceneId"] == "scene-01"
    assert channel["summary"]["heroOriginalClipReady"] is True
    assert channel["summary"]["heroOriginalityEvidenceReady"] is True
    assert channel["summary"]["heroAiOrLocalReady"] is True
    assert channel["summary"]["originalClipSceneIds"] == ["scene-01"]
    assert channel["summary"]["localModelVideoScenes"] == 1
    assert channel["summary"]["originalityEvidenceScenes"] == ["scene-01"]
    assert channel["summary"]["qualityReviewScenes"] == ["scene-01"]
    assert report["checks"]["channelReadinessGate"]["status"] == "pass"
    provenance = report["productionReview"]["scenes"][0]["localGenerationProvenance"]
    assert provenance["hasGeneratorProvenance"] is True
    assert provenance["sourceGenerator"] == "wan"
    assert provenance["sourceGeneratorRequestPath"].endswith("scene-01.wan.request.json")
    assert provenance["sourceGeneratorPromptPath"].endswith("scene-01.wan.prompt.txt")
    assert provenance["sourceGeneratorLogPath"].endswith("scene-01.wan.command.log")
    assert provenance["sourceGeneratorCommand"].startswith("python wan.py")
    upload_review = report["uploadReview"]
    assert upload_review["status"] == "ready"
    assert upload_review["requiredFixes"] == []
    assert upload_review["manualReviewItems"] == []
    assert upload_review["summary"]["thumbnailReviewReady"] is True
    assert upload_review["summary"]["audioMixReviewReady"] is True
    assert upload_review["summary"]["platformComparisonReady"] is True
    assert report["checks"]["uploadReviewGate"]["status"] == "pass"
    top_tier = report["topTierReadiness"]
    assert top_tier["status"] == "top-tier-ready"
    assert top_tier["requiredFixes"] == []
    assert top_tier["summary"]["topTierEvidenceReady"] is True
    assert report["checks"]["topTierReadinessGate"]["status"] == "pass"


def test_upload_review_blocks_live_channel_original_source_mix_gap(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    scenes = []
    assets = [
        {
            "provider": "wan",
            "role": "visual",
            "sceneId": "scene-01",
            "kind": "video",
            "sourceOrigin": "uploaded",
            "sourceGenerator": "wan",
            "sourceGeneratorRequestPath": "storage/local-video/source-mix/scene-01/scene-01.wan.request.json",
            "sourceGeneratorPromptPath": "storage/local-video/source-mix/scene-01/scene-01.wan.prompt.txt",
            "sourceGeneratorLogPath": "storage/local-video/source-mix/scene-01/scene-01.wan.command.log",
            "sourceGeneratorCommand": "python wan.py --request scene-01.wan.request.json",
        },
    ]
    for index in range(1, 5):
        scene_id = f"scene-{index:02d}"
        is_hero = index == 1
        scenes.append(
            {
                "sceneId": scene_id,
                "title": f"Source mix scene {index}",
                "subtitleText": f"Beat {index}",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "lower-info" if index % 2 else "center-short",
                "sourceRationale": "Operator selected this moving clip for the planned beat and subject motion.",
                "continuityNote": "Warm palette, slow camera motion, and routine subject continuity stay consistent.",
                "hookNote": "The first motion beat is visible immediately." if is_hero else "This beat continues the same visual rhythm.",
                "originalityEvidence": (
                    "Local Wan MP4 generated offline from the stored prompt; no paid API."
                    if is_hero
                    else ""
                ),
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Use the first frame with clear subject shape." if is_hero else "",
                "audioMixReviewNote": "Narration is intelligible and the BGM stays below speech.",
                "platformComparisonNote": "Compared against current AI-assisted Shorts for hook, pacing, layout, and artifact level.",
                "layoutVariantKey": "hero_motion" if is_hero else f"support_broll_{index}",
                "visualSourceIntent": "wan" if is_hero else "pexels-video",
            }
        )
        if not is_hero:
            assets.append(
                {
                    "provider": "pexels-video",
                    "role": "visual",
                    "sceneId": scene_id,
                    "kind": "video",
                    "sourceOrigin": "selected-stock",
                    "sourceUrl": f"https://www.pexels.com/video/source-mix-{index}/",
                    "sourceExternalId": f"source-mix-{index}",
                    "sourceLabel": f"Pexels source mix {index}",
                }
            )
        assets.append(
            {
                "provider": "edge-tts",
                "role": "audio",
                "sceneId": scene_id,
                "kind": "voiceover",
                "sourcePath": f"storage/audio/source-mix/{scene_id}.mp3",
            }
        )

    manifest = {
        "projectId": "top-tier-source-mix",
        "templateType": "persona_story",
        "scenes": scenes,
        "assets": assets,
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "stock-heavy-with-hero.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 3, "totalScenes": 4},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-02", "status": "generated", "outputKind": "video"},
            {"sceneId": "scene-03", "status": "generated", "outputKind": "video"},
            {"sceneId": "scene-04", "status": "generated", "outputKind": "video"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    stock_fit = report["checks"]["stockAiClipFit"]
    assert stock_fit["status"] == "fail"
    assert "originalSourceMixRequired=True" in stock_fit["detail"]
    assert "originalSourceMixReady=False" in stock_fit["detail"]
    assert "stockSourceMixGapSceneIds=['scene-02', 'scene-03', 'scene-04']" in stock_fit["detail"]
    assert report["publishReadiness"]["status"] == "blocked"
    assert any("mismatched stock/AI clips" in item for item in report["publishReadiness"]["requiredFixes"])
    assert report["channelReadiness"]["status"] == "blocked"
    upload_review = report["uploadReview"]
    assert upload_review["status"] == "blocked"
    assert upload_review["summary"]["publishStatus"] == "blocked"
    assert upload_review["summary"]["originalSourceMixRequired"] is True
    assert upload_review["summary"]["originalSourceMixReady"] is False
    assert upload_review["summary"]["originalClipScenes"] == 1
    assert upload_review["summary"]["minOriginalScenes"] == 2
    assert upload_review["summary"]["stockVideoScenes"] == 3
    source_mix_upload = next(item for item in upload_review["criteria"] if item["key"] == "originalSourceMix")
    assert source_mix_upload["status"] == "fail"
    assert "minOriginalScenes=2" in source_mix_upload["detail"]
    assert any("at least half of scenes" in item for item in upload_review["requiredFixes"])
    assert report["checks"]["uploadReviewGate"]["status"] == "fail"
    top_tier = report["topTierReadiness"]
    assert top_tier["status"] == "needs-publish-rework"
    assert top_tier["summary"]["grokOrLocalHeroReady"] is True
    assert top_tier["summary"]["originalSourceMixReady"] is False
    assert top_tier["summary"]["publishStatus"] == "blocked"
    assert top_tier["summary"]["channelStatus"] == "blocked"
    assert top_tier["summary"]["uploadStatus"] == "blocked"
    assert top_tier["summary"]["originalClipScenes"] == 1
    assert top_tier["summary"]["minOriginalScenes"] == 2
    assert top_tier["summary"]["stockVideoScenes"] == 3
    source_mix = next(item for item in top_tier["criteria"] if item["key"] == "originalSourceMix")
    assert source_mix["status"] == "fail"
    assert "minOriginalScenes=2" in source_mix["detail"]
    assert any("at least half of scenes" in item for item in top_tier["requiredFixes"])
    assert report["checks"]["topTierReadinessGate"]["status"] == "warn"


def test_stock_ai_clip_fit_requires_explicit_verdict_for_selected_stock(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")

    scenes = [
        {
            "sceneId": "scene-01",
            "title": "Timer hook",
            "subtitleText": "20초 타이머",
            "narrationText": FULL_NARRATION,
            "visualKind": "video",
            "captionPreset": "top-hook",
            "sourceRationale": "Grok timer handoff starts with clear phone/timer motion.",
            "continuityNote": "Warm desk, phone, timer, and notebook match the reset routine.",
            "hookNote": "Timer appears immediately in the first two seconds.",
            "originalityEvidence": "Grok browser handoff MP4 was direct-imported through the upload endpoint.",
            "qualityReviewNote": CAPTION_REVIEW,
            "visualQualityVerdict": "pass",
            "thumbnailReviewNote": "Timer first frame is the hook candidate.",
            "audioMixReviewNote": "Voiceover remains above BGM and no clipping is audible.",
            "platformComparisonNote": "Compared against Shorts/Reels ranking hooks for pacing and layout.",
            "visualSourceIntent": "grok",
            "selectedFileName": "scene-01.grok.mp4",
            "selectedCandidateSummary": "Selected over stock phone-down footage because the timer reads immediately.",
            "selectedCandidate": {
                "sourceProvenance": {
                    "status": "browser-native-original-download",
                    "acceptAsGrokMainSource": True,
                }
            },
            "sourceProvenanceConfirmed": True,
            "sourceProvenanceNote": "Already-local direct import proof; no native browser download prompt is used.",
        },
        {
            "sceneId": "scene-02",
            "title": "Notebook proof",
            "subtitleText": "한 줄 적기",
            "narrationText": FULL_NARRATION,
            "visualKind": "video",
            "captionPreset": "lower-info",
            "sourceRationale": "Grok notebook handoff shows immediate pen motion.",
            "continuityNote": "Notebook and warm desk carry the same routine environment.",
            "hookNote": "Pen touches paper early in the clip.",
            "originalityEvidence": "Grok browser handoff MP4 was direct-imported through the upload endpoint.",
            "qualityReviewNote": CAPTION_REVIEW,
            "visualQualityVerdict": "pass",
            "thumbnailReviewNote": "Support scene only, not first-frame candidate.",
            "audioMixReviewNote": "Voiceover remains above BGM and no clipping is audible.",
            "platformComparisonNote": "Compared against Shorts/Reels ranking hooks for pacing and layout.",
            "visualSourceIntent": "grok",
            "selectedFileName": "scene-02.grok.mp4",
            "selectedCandidateSummary": "Selected notebook action over weaker alternate source clips.",
            "selectedCandidate": {
                "sourceProvenance": {
                    "status": "browser-native-original-download",
                    "acceptAsGrokMainSource": True,
                }
            },
            "sourceProvenanceConfirmed": True,
            "sourceProvenanceNote": "Already-local direct import proof; no native browser download prompt is used.",
        },
        {
            "sceneId": "scene-03",
            "title": "Neck tension reset",
            "subtitleText": "목 긴장 풀기",
            "narrationText": FULL_NARRATION,
            "visualKind": "video",
            "captionPreset": "lower-info",
            "sourceRationale": "Selected-stock Pexels neck-pain clip only fits after rewriting the beat.",
            "continuityNote": "Office laptop context is plausible but not the same worker or prop continuity.",
            "hookNote": "Neck discomfort is visible early enough for a rank beat.",
            "originalityEvidence": "Pexels stock support clip; not fresh Grok proof or owned footage.",
            "qualityReviewNote": CAPTION_REVIEW,
            "visualQualityVerdict": "pass",
            "thumbnailReviewNote": "Not a thumbnail candidate.",
            "audioMixReviewNote": "Voiceover remains above BGM and no clipping is audible.",
            "platformComparisonNote": "Stock support requires an explicit source-fit verdict before upload review.",
            "visualSourceIntent": "selected-stock",
        },
    ]
    assets = [
        {
            "provider": "upload",
            "role": "visual",
            "sceneId": "scene-01",
            "kind": "video",
            "sourceOrigin": "uploaded",
            "sourceProvenance": {
                "status": "browser-native-original-download",
                "acceptAsGrokMainSource": True,
            },
        },
        {
            "provider": "upload",
            "role": "visual",
            "sceneId": "scene-02",
            "kind": "video",
            "sourceOrigin": "uploaded",
            "sourceProvenance": {
                "status": "browser-native-original-download",
                "acceptAsGrokMainSource": True,
            },
        },
        {
            "provider": "pexels-video",
            "role": "visual",
            "sceneId": "scene-03",
            "kind": "video",
            "sourceOrigin": "selected-stock",
            "sourceUrl": "https://www.pexels.com/video/a-man-sitting-at-a-laptop-with-his-neck-in-pain-27430390/",
            "sourceExternalId": "27430390",
            "sourceLabel": "Pexels neck-pain source",
        },
        {"provider": "edge-tts", "role": "audio"},
    ]

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest={
            "projectId": "stock-fit-verdict-required",
            "templateType": "ranking_list",
            "scenes": scenes,
            "assets": assets,
        },
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "stock-fit.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 3, "generated": 0, "totalScenes": 3},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-03", "status": "uploaded", "outputKind": "video"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["originalSourceMixReady"] is True
    assert summary["missingStockAiClipFitVerdictScenes"] == ["scene-03"]
    stock_fit = report["checks"]["stockAiClipFit"]
    assert stock_fit["status"] == "fail"
    assert "missingStockAiClipFitVerdictScenes=['scene-03']" in stock_fit["detail"]
    assert report["uploadReview"]["status"] == "blocked"
    stock_fit_upload = next(item for item in report["uploadReview"]["criteria"] if item["key"] == "stockAiClipFit")
    assert stock_fit_upload["status"] == "fail"
    assert stock_fit_upload["required"] is True


def test_channel_readiness_requires_originality_and_quality_notes_for_upload(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "upload-needs-proof",
        "templateType": "authentic_vlog",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Upload hook",
                "subtitleText": "Uploaded motion",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "none",
                "sourceRationale": "Operator selected this uploaded MP4 for visible motion.",
                "continuityNote": "Same warm palette and slow motion.",
                "hookNote": "Motion starts in the first two seconds.",
                "visualSourceIntent": "upload",
            }
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "upload.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["publishReadiness"]["status"] == "ready"
    channel = report["channelReadiness"]
    assert channel["status"] == "needs-originality-proof"
    assert any("first hook MP4" in item for item in channel["requiredFixes"])
    assert any("quality review" in item for item in channel["requiredFixes"])
    assert channel["summary"]["originalClipSceneIds"] == []
    assert channel["summary"]["weakUploadedOriginalityScenes"] == ["scene-01"]
    assert channel["summary"]["missingOriginalityEvidenceScenes"] == []
    assert channel["summary"]["missingQualityReviewScenes"] == ["scene-01"]
    assert report["checks"]["channelReadinessGate"]["status"] == "warn"


def test_uploaded_local_mp4_does_not_count_as_original_without_owned_source_proof(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "weak-upload-proof",
        "templateType": "authentic_vlog",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Local MP4 hook",
                "subtitleText": "Motion starts the story.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "none",
                "sourceRationale": "Operator selected this local MP4 because the motion fits the cafe topic.",
                "continuityNote": "Warm palette and slow camera movement match the edit.",
                "hookNote": "Motion starts in the first two seconds.",
                "originalityEvidence": "Operator-selected local MP4 retained as direct handoff asset; no paid API source.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Opening frame is clean and usable as a thumbnail candidate.",
                "audioMixReviewNote": "Voice and BGM are balanced without clipping.",
                "platformComparisonNote": "Compared against current Shorts references for hook, caption placement, and artifact level.",
                "visualSourceIntent": "upload",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "uploaded",
                "sourcePath": "storage/uploads/operator-selected-local.mp4",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "weak-upload.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    scene_review = report["productionReview"]["scenes"][0]
    assert summary["uploadedVideoScenes"] == 1
    assert summary["originalClipSceneIds"] == []
    assert summary["weakUploadedOriginalityScenes"] == ["scene-01"]
    assert scene_review["uploadOriginalityStatus"] == "needs-owned-source-proof"
    assert "uploaded MP4 lacks owned/direct source proof" in scene_review["caveats"]
    channel = report["channelReadiness"]
    assert channel["status"] == "needs-originality-proof"
    assert channel["summary"]["originalClipScenes"] == 0
    assert channel["summary"]["weakUploadedOriginalityScenes"] == ["scene-01"]
    original_mix = next(item for item in channel["criteria"] if item["key"] == "originalFootageMix")
    assert original_mix["status"] == "fail"
    assert "weakUploadedOriginalityScenes=['scene-01']" in original_mix["detail"]
    assert report["uploadReview"]["status"] == "blocked"
    assert report["checks"]["channelReadinessGate"]["status"] == "warn"


def test_operator_uploaded_text_alone_does_not_count_as_original_proof(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "operator-uploaded-only",
        "templateType": "authentic_vlog",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Uploaded hook",
                "subtitleText": "Uploaded motion starts the story.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this original upload for the hook.",
                "continuityNote": "Same warm room, stable camera, consistent subject.",
                "hookNote": "Movement begins immediately.",
                "originalityEvidence": "Direct operator-uploaded MP4, no paid API.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Opening frame is clean.",
                "audioMixReviewNote": "Voice and BGM are balanced.",
                "platformComparisonNote": "Compared against Shorts references.",
                "visualSourceIntent": "upload",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "uploaded",
                "sourcePath": "storage/uploads/ambiguous-upload.mp4",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "ambiguous-upload.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    scene_review = report["productionReview"]["scenes"][0]
    summary = report["channelReadiness"]["summary"]
    assert scene_review["uploadOriginalityStatus"] == "needs-owned-source-proof"
    assert summary["originalClipSceneIds"] == []
    assert summary["weakUploadedOriginalityScenes"] == ["scene-01"]
    assert report["channelReadiness"]["status"] == "needs-originality-proof"


def test_rewrapped_stock_upload_does_not_count_as_original_even_with_owned_words(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "rewrapped-stock-upload",
        "templateType": "authentic_vlog",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Stock-like hook",
                "subtitleText": "The clip is relevant but not owned.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator uploaded a downloaded Pexels clip and marked it as owned.",
                "continuityNote": "Warm palette and stable camera motion.",
                "hookNote": "Movement begins immediately.",
                "originalityEvidence": "Operator-owned uploaded MP4; no paid API.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Opening frame is clean.",
                "audioMixReviewNote": "Voice and BGM are balanced.",
                "platformComparisonNote": "Compared against Shorts references.",
                "visualSourceIntent": "upload",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "uploaded",
                "sourceProvider": "pexels-video",
                "sourceUrl": "https://www.pexels.com/video/cafe-stock-123/",
                "sourcePath": "storage/uploads/pexels-cafe-stock.mp4",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "rewrapped-stock.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    scene_review = report["productionReview"]["scenes"][0]
    summary = report["channelReadiness"]["summary"]
    assert scene_review["uploadOriginalityStatus"] == "stock-rewrapped-upload"
    assert "stock/free-source provenance" in " ".join(scene_review["caveats"])
    assert summary["originalClipSceneIds"] == []
    assert summary["weakUploadedOriginalityScenes"] == ["scene-01"]
    assert report["channelReadiness"]["status"] == "needs-originality-proof"


def test_procedural_colorbar_upload_does_not_count_as_owned_original(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "procedural-upload-proof",
        "templateType": "ranking_list",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Synthetic hook",
                "subtitleText": "퇴근 후 3가지",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "lower-info",
                "sourceRationale": "Direct operator-uploaded local MP4 used as the first hook.",
                "continuityNote": "Local original hook introduces the reset/list theme.",
                "hookNote": "First two seconds contain a deliberate local original motion hook.",
                "originalityEvidence": "direct operator-uploaded local MP4; operator-owned original/procedural motion generated inside Video Studio, no paid API.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Opening frame is deliberate original hook.",
                "audioMixReviewNote": "Narration remains primary with low BGM.",
                "platformComparisonNote": "Compared against current Shorts references.",
                "layoutVariantKey": "rank-countdown",
                "visualSourceIntent": "upload",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "uploaded",
                "sourceLabel": "scene-01-direct-motion.mp4",
                "sourceLicense": "Operator-owned local/generated MP4 for Video Studio QA; no paid API",
                "sourceGenerator": "video-studio-local-render",
                "sourceGeneratorCommand": "local FFmpeg/direct motion clip render retained from direct-motion-clip-render-20260526-01",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "procedural-upload.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    scene_review = report["productionReview"]["scenes"][0]
    assert summary["originalClipSceneIds"] == []
    assert summary["weakUploadedOriginalityScenes"] == ["scene-01"]
    assert summary["proceduralPlaceholderScenes"] == ["scene-01"]
    assert scene_review["uploadOriginalityStatus"] == "procedural-placeholder"
    assert "procedural/test-pattern placeholder" in " ".join(scene_review["caveats"])
    assert report["publishReadiness"]["status"] == "blocked"
    assert any("test-pattern" in item for item in report["publishReadiness"]["requiredFixes"])
    assert report["uploadReview"]["status"] == "blocked"


def test_channel_readiness_rejects_quality_note_without_visual_verdict(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "quality-note-not-verdict",
        "templateType": "authentic_vlog",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Direct hook",
                "subtitleText": "Direct motion",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this direct uploaded MP4 for visible first-frame motion.",
                "continuityNote": "Warm palette and stable camera motion match the planned cut style.",
                "hookNote": "Motion starts in the first two seconds.",
                "originalityEvidence": "Direct operator-uploaded phone camera MP4 shot by operator; no paid API and no stock auto-pick.",
                "qualityReviewNote": "Subject is visible, caption is top-safe, no watermark, and motion remains stable.",
                "thumbnailReviewNote": "Opening frame is clean and usable as a thumbnail candidate.",
                "audioMixReviewNote": "Voice and BGM are balanced without clipping.",
                "platformComparisonNote": "Compared against current Shorts references for hook, caption placement, and artifact level.",
                "visualSourceIntent": "upload",
            }
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "note-only.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    channel = report["channelReadiness"]
    assert channel["status"] == "needs-visual-verdict"
    assert channel["summary"]["qualityReviewScenes"] == ["scene-01"]
    assert channel["summary"]["missingVisualVerdictScenes"] == ["scene-01"]
    assert channel["summary"]["visualVerdictReady"] is False
    upload_review = report["uploadReview"]
    assert upload_review["status"] == "blocked"
    assert any("visualQualityVerdict=pass" in item for item in upload_review["requiredFixes"])
    assert report["checks"]["uploadReviewGate"]["status"] == "fail"


def test_upload_review_ready_for_direct_original_upload_with_full_review(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "direct-original-ready",
        "templateType": "authentic_vlog",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Direct hook",
                "subtitleText": "Direct motion",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this direct uploaded MP4 for visible first-frame motion.",
                "continuityNote": "Warm palette and stable camera motion match the planned cut style.",
                "hookNote": "Motion starts in the first two seconds.",
                "originalityEvidence": "Direct operator-uploaded phone camera MP4 shot by operator; no paid API and no stock auto-pick.",
                "qualityReviewNote": "Subject is visible, caption is top-safe, no watermark, and motion remains stable.",
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Opening frame is clean and usable as a thumbnail candidate.",
                "audioMixReviewNote": "Voice and BGM are balanced without clipping.",
                "platformComparisonNote": "Compared against current Shorts references for hook, caption placement, and artifact level.",
                "visualSourceIntent": "upload",
            }
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "direct-ready.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["channelReadiness"]["status"] == "channel-ready"
    assert report["channelReadiness"]["summary"]["heroAiOrLocalReady"] is False
    upload_review = report["uploadReview"]
    assert upload_review["status"] == "ready"
    assert upload_review["requiredFixes"] == []
    assert upload_review["manualReviewItems"] == []
    grok_or_local = next(item for item in upload_review["criteria"] if item["key"] == "grokOrLocalHero")
    assert grok_or_local["status"] == "pass"
    assert "heroOriginalClipReady=True" in grok_or_local["detail"]
    assert report["checks"]["uploadReviewGate"]["status"] == "pass"
    top_tier = report["topTierReadiness"]
    assert top_tier["status"] == "needs-grok-local-hero"
    assert top_tier["summary"]["topTierEvidenceReady"] is False
    assert any("Grok app/web or local Wan/LTX/Hunyuan" in item for item in top_tier["requiredFixes"])
    assert report["checks"]["topTierReadinessGate"]["status"] == "warn"


def test_channel_readiness_requires_first_scene_original_hero_clip(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "hero-original-required",
        "templateType": "news_explainer",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Stock hook",
                "subtitleText": "Cafe hook",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Stock coffee steam clip matches the opener.",
                "continuityNote": "Warm cafe counter, shallow depth of field.",
                "hookNote": "Steam rises immediately in the first two seconds.",
                "qualityReviewNote": "Subject is visible, no watermark, and caption stays top-safe.",
                "stockAiClipFitVerdict": "pass",
                "visualSourceIntent": "pexels-video",
            },
            {
                "sceneId": "scene-02",
                "title": "Original insert",
                "subtitleText": "Local reveal",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "lower-info",
                "sourceRationale": "Wan clip was selected for matching cup angle.",
                "continuityNote": "Same warm palette and slow push-in.",
                "originalityEvidence": "Local Wan MP4 generated offline from the stored prompt; no paid API.",
                "qualityReviewNote": "Cup subject remains visible, lower caption is safe, no baked-in text, no compression artifacts.",
                "visualSourceIntent": "wan",
            },
        ],
        "assets": [
            {
                "provider": "pexels-video",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "selected-stock",
                "sourceUrl": "https://www.pexels.com/video/hero-stock-101/",
            },
            {"provider": "wan", "role": "visual", "sceneId": "scene-02", "kind": "video", "sourceOrigin": "uploaded"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-02", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "hero-mismatch.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 1, "totalScenes": 2},
        local_media=[
            {"sceneId": "scene-01", "status": "generated", "outputKind": "video"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "video"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["publishReadiness"]["status"] == "ready"
    channel = report["channelReadiness"]
    assert channel["status"] == "needs-hero-original-footage"
    assert channel["summary"]["originalClipScenes"] == 1
    assert channel["summary"]["originalClipSceneIds"] == ["scene-02"]
    assert channel["summary"]["firstSceneId"] == "scene-01"
    assert channel["summary"]["heroOriginalClipReady"] is False
    assert channel["summary"]["heroOriginalityEvidenceReady"] is False
    assert any("first hook scene" in item for item in channel["requiredFixes"])
    assert report["checks"]["channelReadinessGate"]["status"] == "warn"


def test_publish_readiness_flags_stock_only_and_missing_review_notes(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "publish-needs-rework",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Stock hook",
                "subtitleText": "Cafe",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
            }
        ],
        "assets": [
            {
                "provider": "pexels-video",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "selected-stock",
            },
            {"provider": "edge-tts", "role": "audio"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "stock.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 0, "generated": 1, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "generated", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    readiness = report["publishReadiness"]
    assert readiness["status"] == "blocked"
    assert any("caption" in item.lower() for item in readiness["requiredFixes"])
    assert any("stock-only" in item for item in readiness["recommendedFixes"])
    assert any("source-rationale" in item for item in readiness["recommendedFixes"])
    assert report["checks"]["publishReadinessGate"]["status"] == "fail"
    channel = report["channelReadiness"]
    assert channel["status"] == "blocked"
    assert any("direct upload" in item for item in channel["requiredFixes"])
    assert report["checks"]["channelReadinessGate"]["status"] == "fail"


def test_publish_readiness_keeps_curated_stock_as_review_draft(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "publish-curated-stock",
        "templateType": "news_explainer",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Steam hook",
                "subtitleText": "A quiet morning starts with motion.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected the stock clip for visible steam motion and matching cafe mood.",
                "continuityNote": "Warm palette, close-up coffee subject, and slow camera movement match the rest of the sequence.",
                "hookNote": "Steam appears immediately in the first two seconds before the title resolves.",
                "qualityReviewNote": CAPTION_REVIEW,
                "stockAiClipFitVerdict": "pass",
            }
        ],
        "assets": [
            {
                "provider": "pexels-video",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "selected-stock",
                "sourceUrl": "https://www.pexels.com/video/curated-stock-101/",
            },
            {"provider": "edge-tts", "role": "audio"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "curated-stock.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 0, "generated": 1, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "generated", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    readiness = report["publishReadiness"]
    summary = report["productionReview"]["summary"]
    assert summary["stockOnly"] is True
    assert summary["curatedStockReady"] is True
    assert readiness["status"] == "needs-rework"
    assert any("stock-only curated exports as review drafts" in item for item in readiness["recommendedFixes"])
    source_authorship = next(item for item in readiness["criteria"] if item["key"] == "sourceAuthorship")
    assert source_authorship["status"] == "warn"
    assert source_authorship["required"] is False
    assert report["checks"]["stockOnlyCaveat"]["status"] == "warn"
    assert report["checks"]["publishReadinessGate"]["status"] == "warn"
    channel = report["channelReadiness"]
    assert channel["status"] == "needs-publish-rework"
    assert channel["summary"]["publishStatus"] == "needs-rework"
    assert channel["summary"]["curatedStockReady"] is True
    assert channel["summary"]["originalClipScenes"] == 0
    assert any("direct upload" in item for item in channel["requiredFixes"])
    assert report["checks"]["channelReadinessGate"]["status"] == "warn"


def test_render_quality_report_tracks_selected_stock_candidate_curation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "stock-curation-ready",
        "templateType": "news_explainer",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Document texture",
                "subtitleText": "The claim needs visual context.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this Pexels clip from a four-candidate pool because the document motion matches the claim context.",
                "continuityNote": "Neutral desk palette and slow camera motion fit the evidence sequence.",
                "hookNote": "The document page movement is visible in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
            }
        ],
        "assets": [
            {
                "provider": "pexels-video",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "selected-stock",
                "sourceUrl": "https://videos.pexels.com/document-101.mp4",
                "sourcePageUrl": "https://www.pexels.com/video/document-101/",
                "sourceExternalId": "document-101",
                "sourceLabel": "Pexels document candidate 101",
                "creator": "Pexels Creator",
                "candidateCount": 4,
                "selectionMethod": "operator-selected-from-candidates",
                "selectionKey": "scene-01:document-101",
                "selectedCandidateSummary": "Selected from four Pexels candidates because this take has cleaner document motion and no baked-in text.",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "stock-curation-ready.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 0, "generated": 1, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "generated", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["stockCandidateCurationScenes"] == ["scene-01"]
    assert summary["stockCandidateCurationReadyScenes"] == ["scene-01"]
    assert summary["missingStockCandidateCurationScenes"] == []
    assert report["checks"]["stockCandidateCuration"]["status"] == "pass"
    top_tier = report["topTierReadiness"]
    curation = next(item for item in top_tier["criteria"] if item["key"] == "stockCandidateCuration")
    assert curation["status"] == "pass"
    assert top_tier["summary"]["stockCandidateCurationReady"] is True


def test_render_quality_report_flags_stock_without_candidate_pool_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "stock-curation-missing",
        "templateType": "news_explainer",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Implicit stock pick",
                "subtitleText": "A related stock clip appears.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Related Pexels clip.",
                "continuityNote": "Neutral palette and slow camera motion.",
                "hookNote": "Motion starts immediately.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
            }
        ],
        "assets": [
            {
                "provider": "pexels-video",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "selected-stock",
                "sourceUrl": "https://videos.pexels.com/implicit-101.mp4",
                "sourceExternalId": "implicit-101",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "stock-curation-missing.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 0, "generated": 1, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "generated", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["missingStockCandidateCurationScenes"] == ["scene-01"]
    assert summary["missingStockCandidateCountScenes"] == ["scene-01"]
    assert summary["missingStockCandidateCreatorScenes"] == ["scene-01"]
    assert summary["missingStockSelectionSummaryScenes"] == ["scene-01"]
    assert summary["stockCandidateCurationIssuesByScene"]["scene-01"] == [
        "candidateCount<2",
        "creator",
        "selectionSummary",
    ]
    assert report["checks"]["stockCandidateCuration"]["status"] == "warn"
    top_tier = report["topTierReadiness"]
    curation = next(item for item in top_tier["criteria"] if item["key"] == "stockCandidateCuration")
    assert curation["status"] == "fail"
    assert top_tier["summary"]["stockCandidateCurationReady"] is False


def test_template_source_review_flags_persona_story_without_grok_or_local_clip(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "persona-stock-only",
        "templateType": "persona_story",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "A familiar character returns",
                "subtitleText": "The same face has to carry the hook.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected stock motion for matching mood, but it is not a persistent character source.",
                "continuityNote": "Warm room, slow camera, and a single-person framing are consistent.",
                "hookNote": "The face appears immediately in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "stockAiClipFitVerdict": "pass",
            }
        ],
        "assets": [
            {
                "provider": "pexels-video",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "selected-stock",
                "sourceUrl": "https://www.pexels.com/video/persona-stock-201/",
                "sourceLabel": "manual stock candidate 201",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "persona.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 0, "generated": 1, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "generated", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    template_review = report["productionReview"]["templateSourceReview"]
    assert template_review["status"] == "warn"
    assert report["checks"]["templateSourcePlan"]["status"] == "warn"
    assert report["publishReadiness"]["status"] == "needs-rework"
    assert any("Grok app/web or local Wan/LTX/Hunyuan" in item for item in template_review["recommendedFixes"])


def test_template_source_review_accepts_direct_upload_authentic_vlog(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "authentic-vlog-upload",
        "templateType": "authentic_vlog",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Morning setup",
                "subtitleText": "A real desk setup starts the story.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "lower-info",
                "sourceRationale": "Operator uploaded owned phone footage because the hand movement and desk details match the topic.",
                "continuityNote": "Natural daylight, handheld movement, and the same desk palette continue across the edit.",
                "hookNote": "The hands enter frame immediately in the first two seconds.",
                "originalityEvidence": "Direct operator-uploaded MP4 from a phone camera, no paid API.",
                "qualityReviewNote": CAPTION_REVIEW,
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "uploaded",
                "sourcePath": "storage/uploads/authentic-vlog-hook.mp4",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "authentic-vlog.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["productionReview"]["templateSourceReview"]["status"] == "pass"
    assert report["checks"]["templateSourcePlan"]["status"] == "pass"


def test_template_source_review_accepts_grok_handoff_authentic_vlog(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "authentic-vlog-grok",
        "templateType": "authentic_vlog",
        "audioDesignMode": "no-voice",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Commute reset",
                "subtitleText": "퇴근 후, 속도 낮추기",
                "narrationText": "",
                "visualKind": "video",
                "captionPreset": "top-hook",
                "captionDisplayDurationSec": 1.2,
                "audioDesignMode": "no-voice",
                "sourceRationale": "Operator reviewed a Grok web handoff MP4 because the subject and motion match the routine hook.",
                "continuityNote": "Same worker, backpack, and teal-warm night palette continue through the scene.",
                "hookNote": "The platform lights move and the subject slows down in the first two seconds.",
                "originalityEvidence": "Grok app/web MP4 imported through manual handoff; no paid API.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "audioMixReviewNote": "No-voice BGM and local ambience carry the scene without explanatory TTS.",
                "platformComparisonNote": "Compared against Korean routine Shorts for hook, caption restraint, and full-frame motion.",
                "layoutVariantKey": "grok-first-hook",
            }
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "grok-handoff",
                "sourceGenerator": "grok-app-web-handoff",
                "sourcePath": "storage/grok-handoffs/routine/scene-01.grok.mp4",
            },
            {
                "provider": "local-bgm",
                "role": "audio",
                "sceneId": "global",
                "kind": "bgm",
                "sourceOrigin": "local-library",
                "sourcePath": "assets/bgm/tech-house/minimal.mp3",
                "sourceLabel": "Minimal test bed",
                "sourceUrl": "https://example.invalid/free/minimal",
                "sourceLicense": "Free test fixture",
                "candidateCount": 2,
                "selectionMethod": "stable-hash",
                "selectionKey": "authentic-vlog-grok",
            },
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "authentic-vlog-grok.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    review = report["productionReview"]["templateSourceReview"]
    assert review["status"] == "pass"
    assert "Grok/local handoff" in review["sourceMix"]
    assert report["checks"]["templateSourcePlan"]["status"] == "pass"


def test_template_source_review_flags_live_recap_without_direct_event_footage(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "live-recap-stock",
        "templateType": "live_recap",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Arrival",
                "subtitleText": "The queue sets the scene.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "lower-info",
                "sourceRationale": "Operator selected a rights-safe city/event texture, but no direct event footage is present.",
                "continuityNote": "Night venue palette and slow handheld motion are consistent.",
                "hookNote": "The crowd line appears immediately.",
                "qualityReviewNote": CAPTION_REVIEW,
            }
        ],
        "assets": [
            {
                "provider": "pexels-video",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "selected-stock",
                "sourceUrl": "https://www.pexels.com/video/event-stock-301/",
                "sourceLabel": "manual stock candidate 301",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "live-recap.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 0, "generated": 1, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "generated", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    review = report["productionReview"]["templateSourceReview"]
    assert review["status"] == "warn"
    assert review["family"] == "Korean live/event recap"
    assert any("direct event footage" in item for item in review["recommendedFixes"])


def test_template_source_review_fails_when_layout_variants_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "longform-no-layout-variants",
        "templateType": "longform_deep_dive",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Cold open",
                "subtitleText": "The chapter starts with evidence.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this clip because it shows the exact public document context.",
                "continuityNote": "Documentary tone, neutral palette, and slow camera movement fit the next scene.",
                "hookNote": "The evidence appears immediately in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
            },
            {
                "sceneId": "scene-02",
                "title": "Source card",
                "subtitleText": "The source card explains the claim.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this clip because it supports the same claim with a source card.",
                "continuityNote": "Same restrained documentary palette and camera language.",
                "qualityReviewNote": CAPTION_REVIEW,
            },
        ],
        "assets": [
            {"provider": "pexels-video", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "selected-stock", "sourceUrl": "https://www.pexels.com/video/evidence-101/"},
            {"provider": "pexels-video", "role": "visual", "sceneId": "scene-02", "kind": "video", "sourceOrigin": "selected-stock", "sourceUrl": "https://www.pexels.com/video/evidence-202/"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-02", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "longform.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 0, "generated": 2, "totalScenes": 2},
        local_media=[{"sceneId": "scene-01", "status": "generated", "outputKind": "video"}, {"sceneId": "scene-02", "status": "generated", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    review = report["productionReview"]["templateSourceReview"]
    assert review["status"] == "fail"
    assert review["counts"]["missingLayoutVariantScenes"] == 2
    assert report["productionReview"]["summary"]["missingLayoutVariantScenes"] == ["scene-01", "scene-02"]
    assert any("layout variant" in item for item in review["requiredFixes"])
    assert report["checks"]["templateSourcePlan"]["status"] == "fail"


def test_template_source_review_accepts_multi_scene_layout_variants(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "longform-layout-variants",
        "templateType": "longform_deep_dive",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Cold open",
                "subtitleText": "The chapter starts with evidence.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this clip because it shows the exact public document context.",
                "continuityNote": "Documentary tone, neutral palette, and slow camera movement fit the next scene.",
                "hookNote": "The evidence appears immediately in the first two seconds.",
                "qualityReviewNote": CAPTION_REVIEW,
                "layoutVariantKey": "chapter-evidence",
                "layoutVariantLabel": "chapter evidence",
                "layoutVariantNote": "cold open -> chapter card -> evidence cut",
            },
            {
                "sceneId": "scene-02",
                "title": "Source card",
                "subtitleText": "The source card explains the claim.",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "lower-info",
                "sourceRationale": "Operator selected this clip because it supports the same claim with a source card.",
                "continuityNote": "Same restrained documentary palette and camera language.",
                "qualityReviewNote": CAPTION_REVIEW,
                "layoutVariantKey": "documentary-explainer",
                "layoutVariantLabel": "documentary explainer",
                "layoutVariantNote": "human detail -> data context -> source quote",
            },
        ],
        "assets": [
            {"provider": "pexels-video", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "selected-stock", "sourceUrl": "https://www.pexels.com/video/evidence-101/"},
            {"provider": "pexels-video", "role": "visual", "sceneId": "scene-02", "kind": "video", "sourceOrigin": "selected-stock", "sourceUrl": "https://www.pexels.com/video/evidence-202/"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-02", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "longform.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 0, "generated": 2, "totalScenes": 2},
        local_media=[{"sceneId": "scene-01", "status": "generated", "outputKind": "video"}, {"sceneId": "scene-02", "status": "generated", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    review = report["productionReview"]["templateSourceReview"]
    assert review["status"] == "pass"
    assert review["counts"]["layoutVariantScenes"] == 2
    assert report["productionReview"]["summary"]["layoutVariantCounts"] == {
        "chapter-evidence": 1,
        "documentary-explainer": 1,
    }
    assert report["checks"]["templateSourcePlan"]["status"] == "pass"


def test_render_quality_report_flags_reused_visual_assets(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "reused-asset",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Hook",
                "subtitleText": "Hook",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this original upload for the hook.",
                "continuityNote": "Same warm room, stable camera, consistent subject.",
                "hookNote": "Movement begins immediately.",
                "originalityEvidence": "Direct operator-uploaded MP4, no paid API.",
                "qualityReviewNote": CAPTION_REVIEW,
            },
            {
                "sceneId": "scene-02",
                "title": "Repeat",
                "subtitleText": "Repeat",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "lower-info",
                "sourceRationale": "Operator reused the same clip as a placeholder.",
                "continuityNote": "Same warm room, stable camera, consistent subject.",
                "originalityEvidence": "Direct operator-uploaded MP4, no paid API.",
                "qualityReviewNote": CAPTION_REVIEW,
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded", "sourcePath": "storage/uploads/reused.mp4"},
            {"provider": "upload", "role": "visual", "sceneId": "scene-02", "kind": "video", "sourceOrigin": "uploaded", "sourcePath": "storage/uploads/reused.mp4"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-02", "kind": "voiceover"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "reused.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 2, "generated": 0, "totalScenes": 2},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "video"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["productionReview"]["summary"]["repeatedVisualAssetScenes"] == ["scene-02"]
    assert report["checks"]["assetReuseDiversity"]["status"] == "fail"
    assert report["publishReadiness"]["status"] == "needs-rework"
    assert any("repeated visual assets" in item for item in report["publishReadiness"]["recommendedFixes"])
    assert report["channelReadiness"]["status"] == "needs-publish-rework"


def test_render_quality_report_allows_intentional_source_loop_repeat(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    scenes = []
    assets = []
    for index, subtitle in enumerate(("First loop: watch the setup", "Second loop: catch the payoff"), start=1):
        scene_id = f"scene-{index:02d}"
        scenes.append(
            {
                "sceneId": scene_id,
                "title": f"Loop pass {index}",
                "subtitleText": subtitle,
                "narrationText": "Watch the same source loop again, but this pass changes what the viewer is looking for.",
                "durationSec": 3.2,
                "visualKind": "video",
                "captionPreset": "lower-info",
                "captionPurpose": "proof",
                "sourceRationale": "The repeated GIF is intentionally replayed so the second caption can redirect the viewer to the payoff.",
                "continuityNote": "Both loop passes use the same source to create a deliberate replay rhythm, not a filler repeat.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "sourceLoopGroupId": "reaction-loop",
                "sourceLoopRepeatApproved": True,
                "sourceLoopRhythmReview": "The same GIF loop is replayed with a different caption beat, so the repeat works as timing evidence instead of recycled filler.",
                "sourceLoopReframeEvidence": (
                    "Second pass uses a derived close-up path and starts later in the GIF, so the replay changes the viewer task."
                    if index == 2
                    else ""
                ),
                "sourceMediaKind": "gif",
            }
        )
        assets.extend(
            [
                {
                    "provider": "upload",
                    "role": "visual",
                    "sceneId": scene_id,
                    "kind": "video",
                    "sourceOrigin": "internet-meme-gif",
                    "sourceType": "meme-gif",
                    "sourceUrl": "https://upload.wikimedia.org/example/reaction-loop.gif",
                    "sourcePath": (
                        "storage/source-acquisition/reaction-loop/derived/reaction-loop-closeup.mp4"
                        if index == 2
                        else "storage/source-acquisition/reaction-loop/raw/reaction-loop.gif"
                    ),
                    "sourceMediaKind": "gif",
                    "sourceLoopGroupId": "reaction-loop",
                    "sourceLoopRepeatApproved": True,
                    "sourceLoopRhythmReview": "The same GIF loop is replayed with a different caption beat, so the repeat works as timing evidence instead of recycled filler.",
                    "sourceLoopReframeEvidence": (
                        "Second pass uses a derived close-up path and starts later in the GIF, so the replay changes the viewer task."
                        if index == 2
                        else ""
                    ),
                },
                {"provider": "edge-tts", "role": "audio", "sceneId": scene_id, "kind": "voiceover"},
            ]
        )

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest={"projectId": "intentional-source-loop", "scenes": scenes, "assets": assets},
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "intentional-source-loop.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 2, "generated": 0, "totalScenes": 2},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "video"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["repeatedVisualAssetScenes"] == []
    assert summary["approvedSourceLoopRepeatScenes"] == ["scene-02"]
    assert summary["approvedSourceLoopRepeatGroups"] == {"reaction-loop": ["scene-01", "scene-02"]}
    assert report["checks"]["assetReuseDiversity"]["status"] == "pass"
    assert report["checks"]["sourceLoopRhythm"]["status"] == "pass"


def test_source_loop_rhythm_blocks_same_file_replay_without_reframe(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    scenes = []
    assets = []
    for index, subtitle in enumerate(("watch the setup?", "catch the payoff?"), start=1):
        scene_id = f"scene-{index:02d}"
        scenes.append(
            {
                "sceneId": scene_id,
                "title": f"Loop pass {index}",
                "subtitleText": subtitle,
                "narrationText": "Watch the same source loop again, but this pass changes what the viewer is looking for.",
                "durationSec": 3.2,
                "visualKind": "video",
                "captionPreset": "lower-info",
                "captionPurpose": "proof",
                "sourceRationale": "The repeated GIF is intentionally replayed.",
                "continuityNote": "Both loop passes use the same source.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "sourceLoopGroupId": "reaction-loop",
                "sourceLoopRepeatApproved": True,
                "sourceLoopRhythmReview": "The same GIF loop is replayed with a different caption beat, so the repeat works as timing evidence instead of recycled filler.",
                "sourceMediaKind": "gif",
            }
        )
        assets.extend(
            [
                {
                    "provider": "upload",
                    "role": "visual",
                    "sceneId": scene_id,
                    "kind": "video",
                    "sourceOrigin": "internet-meme-gif",
                    "sourceType": "meme-gif",
                    "sourceUrl": "https://upload.wikimedia.org/example/reaction-loop.gif",
                    "sourcePath": "storage/source-acquisition/reaction-loop/raw/reaction-loop.gif",
                    "sourceMediaKind": "gif",
                    "sourceLoopGroupId": "reaction-loop",
                    "sourceLoopRepeatApproved": True,
                    "sourceLoopRhythmReview": "The same GIF loop is replayed with a different caption beat, so the repeat works as timing evidence instead of recycled filler.",
                },
                {"provider": "edge-tts", "role": "audio", "sceneId": scene_id, "kind": "voiceover"},
            ]
        )

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest={"projectId": "same-file-source-loop", "scenes": scenes, "assets": assets},
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "same-file-source-loop.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 2, "generated": 0, "totalScenes": 2},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "video"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    detail = report["checks"]["sourceLoopRhythm"]["detail"]
    assert report["checks"]["sourceLoopRhythm"]["status"] == "fail"
    assert "scene-02:sourceLoopReframeEvidence>=24" in detail
    assert "scene-02:sourceLoopDerivedPathDistinct" in detail


def test_render_quality_report_allows_distinct_uploads_with_shared_cache_label(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    scenes = []
    assets = []
    for index in range(1, 4):
        scene_id = f"scene-{index:02d}"
        scenes.append(
            {
                "sceneId": scene_id,
                "title": f"Distinct clip {index}",
                "subtitleText": f"clip {index}",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "lower-info" if index > 1 else "top-hook",
                "sourceRationale": "Operator selected a distinct free moving clip for this beat.",
                "continuityNote": "Same calm routine palette, different action beat.",
                "originalityEvidence": "Free moving clip used only as support footage.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
            }
        )
        assets.append(
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": scene_id,
                "kind": "video",
                "sourceOrigin": "uploaded",
                "sourceUrl": "local-cache-from-pexels-curated-recovery-routine",
                "sourcePath": f"storage/uploads/distinct-{index}.mp4",
                "outputPath": f"storage/uploads/distinct-{index}.mp4",
            }
        )
        assets.append({"provider": "edge-tts", "role": "audio", "sceneId": scene_id, "kind": "voiceover"})

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest={"projectId": "distinct-cache-label", "scenes": scenes, "assets": assets},
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "distinct.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 3, "generated": 0, "totalScenes": 3},
        local_media=[
            {"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-02", "status": "uploaded", "outputKind": "video"},
            {"sceneId": "scene-03", "status": "uploaded", "outputKind": "video"},
        ],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["productionReview"]["summary"]["repeatedVisualAssetScenes"] == []
    assert report["checks"]["assetReuseDiversity"]["status"] == "pass"


def test_render_quality_report_flags_missing_bgm_license_provenance(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "bgm-provenance",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Hook",
                "subtitleText": "Hook",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this original upload for the hook.",
                "continuityNote": "Same warm room, stable camera, consistent subject.",
                "hookNote": "Movement begins immediately.",
                "originalityEvidence": "Direct operator-uploaded MP4, no paid API.",
                "qualityReviewNote": CAPTION_REVIEW,
            },
        ],
        "assets": [
            {"provider": "upload", "role": "visual", "sceneId": "scene-01", "kind": "video", "sourceOrigin": "uploaded", "sourcePath": "storage/uploads/hook.mp4"},
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
            {"provider": "local-bgm", "role": "audio", "sceneId": "global", "kind": "bgm", "sourceOrigin": "local-library", "sourcePath": "assets/bgm/upbeat/starter.mp3", "sourceLabel": "starter.mp3"},
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "bgm.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["missingFreeAudioProvenanceAssets"] == ["global:local-bgm:bgm:starter.mp3"]
    assert summary["weakBgmSelectionAssets"] == ["global:local-bgm:bgm:starter.mp3"]
    assert report["checks"]["freeAssetProvenance"]["status"] == "warn"
    assert report["checks"]["bgmAssetRotation"]["status"] == "warn"
    assert report["publishReadiness"]["status"] == "needs-rework"


def test_render_quality_report_blocks_procedural_beep_bgm(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compose_ffmpeg,
        "_run_ffprobe_json",
        lambda _project_root, _output_path: (_valid_ffprobe_payload(), "fake ffprobe"),
    )
    monkeypatch.setattr(
        compose_ffmpeg,
        "_build_source_motion_evidence",
        lambda _project_root, _manifest: _source_motion_evidence("pass"),
    )
    render_dir = tmp_path / "renders"
    subtitle_path = render_dir / "captions.srt"
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.with_suffix(".ass").write_text("[Script Info]\n", encoding="utf-8")
    manifest = {
        "projectId": "beep-bgm-blocked",
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Hook",
                "subtitleText": "Hook",
                "narrationText": FULL_NARRATION,
                "visualKind": "video",
                "captionPreset": "top-hook",
                "sourceRationale": "Operator selected this original upload for the hook.",
                "continuityNote": "Same warm room, stable camera, consistent subject.",
                "hookNote": "Movement begins immediately.",
                "originalityEvidence": "Direct operator-uploaded MP4, no paid API.",
                "qualityReviewNote": CAPTION_REVIEW,
                "visualQualityVerdict": "pass",
                "thumbnailReviewNote": "Use the first motion frame with no baked-in text.",
                "audioMixReviewNote": "TTS is clear, but the BGM fixture is intentionally procedural and should fail.",
                "platformComparisonNote": "Compared against upload references for hook, layout, and audio balance.",
            },
        ],
        "assets": [
            {
                "provider": "upload",
                "role": "visual",
                "sceneId": "scene-01",
                "kind": "video",
                "sourceOrigin": "uploaded",
                "sourcePath": "storage/uploads/hook.mp4",
            },
            {"provider": "edge-tts", "role": "audio", "sceneId": "scene-01", "kind": "voiceover"},
            {
                "provider": "local-bgm",
                "role": "audio",
                "sceneId": "global",
                "kind": "bgm",
                "sourceOrigin": "local-library",
                "sourcePath": "assets/bgm/upbeat/aaa-procedural-ranking-pulse.wav",
                "sourceLabel": "aaa-procedural-ranking-pulse.wav",
                "sourceUrl": "local://ffmpeg-procedural-sine",
                "sourceLicense": "operator-generated",
                "attribution": "local sine/beep placeholder",
                "candidateCount": 2,
                "selectionMethod": "stable-hash",
                "selectionKey": "beep-bgm-blocked",
            },
        ],
    }

    report_path = write_render_quality_report(
        render_dir=render_dir,
        manifest=manifest,
        manifest_path=tmp_path / "render-manifest.json",
        output_path=tmp_path / "beep-bgm.mp4",
        project_root=tmp_path,
        local_media_summary={"placeholder": 0, "uploaded": 1, "generated": 0, "totalScenes": 1},
        local_media=[{"sceneId": "scene-01", "status": "uploaded", "outputKind": "video"}],
        subtitle_file_path=subtitle_path,
    )

    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    summary = report["productionReview"]["summary"]
    assert summary["placeholderBgmAssets"] == ["global:local-bgm:bgm:aaa-procedural-ranking-pulse.wav"]
    assert report["checks"]["bgmSoundQuality"]["status"] == "fail"
    assert report["checks"]["bgmAssetRotation"]["status"] == "fail"
    assert report["publishReadiness"]["status"] == "blocked"
    assert any("test-tone BGM" in item for item in report["publishReadiness"]["requiredFixes"])


def test_finalize_render_rejects_stale_quality_report_without_current_checks(tmp_path):
    client = _media_test_client(tmp_path)
    render_dir = tmp_path / "storage" / "renders" / "stale-ready-render"
    render_dir.mkdir(parents=True)
    output_path = render_dir / "ready.mp4"
    output_path.write_bytes(b"fake mp4")
    quality_path = render_dir / "render-quality-report.json"
    quality_path.write_text(json.dumps({
        "projectId": "stale-ready-render",
        "publishReadiness": {
            "status": "ready",
            "requiredFixes": [],
            "recommendedFixes": [],
        },
        "checks": {
            "outputSpec": {"status": "pass", "detail": "old narrow check only"},
            "noPlaceholders": {"status": "pass", "detail": "old narrow check only"},
        },
    }), encoding="utf-8")

    response = client.post("/api/finalize-render", json={
        "outputPath": str(output_path),
        "qualityReportPath": str(quality_path),
    })

    payload = response.get_json()
    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["error"] == "quality report is stale"
    assert "uploadReview" in payload["qualityReportFreshness"]["missingSections"]
    assert "ttsNarrationEvidence" in payload["qualityReportFreshness"]["missingChecks"]
    assert "captionLayoutReview" in payload["qualityReportFreshness"]["missingChecks"]
    assert "captionDensityAndSafeZone" in payload["qualityReportFreshness"]["missingChecks"]
    assert "bgmAssetRotation" in payload["qualityReportFreshness"]["missingChecks"]
    assert "topTierReadiness" in payload["qualityReportFreshness"]["missingSections"]
    assert "topTierReadinessGate" in payload["qualityReportFreshness"]["missingChecks"]
    assert any("Re-render with the current quality gate" in item for item in payload["requiredFixes"])
    audit_path = Path(payload["blockedQualityAuditPath"])
    assert audit_path.exists()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["qualityReportFreshness"]["ok"] is False
    assert not (tmp_path / "storage" / "final-videos" / "stale-ready-render").exists()


def test_finalize_render_copies_ready_publish_packet(tmp_path):
    client = _media_test_client(tmp_path)
    render_dir = tmp_path / "storage" / "renders" / "ready-render"
    render_dir.mkdir(parents=True)
    output_path = render_dir / "ready.mp4"
    manifest_path = tmp_path / "storage" / "inputs" / "ready-render" / "render-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    output_path.write_bytes(b"fake mp4")
    manifest_path.write_text("{}", encoding="utf-8")
    quality_path = render_dir / "render-quality-report.json"
    quality_path.write_text(json.dumps({
        "projectId": "ready-render",
        "manifestPath": str(manifest_path),
        "publishReadiness": {
            "status": "ready",
            "requiredFixes": [],
            "recommendedFixes": [],
            "criteria": [{"status": "pass", "label": "No placeholder media", "detail": "ok", "required": True}],
        },
        "channelReadiness": {
            "status": "needs-original-footage",
            "requiredFixes": ["Add at least one original MP4 clip."],
            "recommendedFixes": ["Add Grok or local AI hero clip evidence."],
            "summary": {
                "heroAiOrLocalReady": False,
                "heroOriginalClipReady": False,
            },
            "criteria": [
                {"status": "fail", "label": "Original or handoff MP4 present", "detail": "originalClipScenes=0", "required": True}
            ],
        },
        "uploadReview": {
            "status": "blocked",
            "requiredFixes": ["Create a channel-ready packet with first-scene original MP4 evidence before upload."],
            "manualReviewItems": ["Pick or generate a thumbnail/first-frame candidate before publishing."],
            "criteria": [
                {"status": "warn", "label": "Thumbnail / first-frame manual review", "detail": "manual", "required": False}
            ],
        },
        "topTierReadiness": _top_tier_readiness(),
        "checks": _current_quality_checks(),
        "productionReview": {
            "summary": {
                "stockOnly": False,
                "missingContinuityScenes": [],
                "missingQualityReviewScenes": [],
                "firstSceneHookReady": True,
                "missingRationaleScenes": [],
            },
        },
    }), encoding="utf-8")

    response = client.post("/api/finalize-render", json={
        "outputPath": str(output_path),
        "qualityReportPath": str(quality_path),
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    final_video = Path(payload["finalVideoPath"])
    checklist = Path(payload["publishChecklistPath"])
    quality_checklist = Path(payload["qualityChecklistPath"])
    quality_audit = Path(payload["qualityAuditPath"])
    publish_packet = Path(payload["publishPacketPath"])
    publish_packet_md = Path(payload["publishPacketMarkdownPath"])
    assert final_video.exists()
    assert Path(payload["finalQualityReportPath"]).exists()
    assert Path(payload["renderManifestPath"]).exists()
    assert checklist.exists()
    assert quality_checklist.exists()
    assert quality_audit.exists()
    assert publish_packet.exists()
    assert publish_packet_md.exists()
    checklist_text = checklist.read_text(encoding="utf-8")
    quality_text = quality_checklist.read_text(encoding="utf-8")
    quality_audit_json = json.loads(quality_audit.read_text(encoding="utf-8"))
    publish_packet_json = json.loads(publish_packet.read_text(encoding="utf-8"))
    publish_packet_text = publish_packet_md.read_text(encoding="utf-8")
    quality_audit_items = {item["key"]: item for item in payload["qualityAudit"]["checklist"]}
    assert payload["publishPacket"]["decision"]["key"] == "needs-edit"
    assert publish_packet_json["decision"]["key"] == "needs-edit"
    assert publish_packet_json["titleCandidates"]
    assert publish_packet_json["hashtags"]
    assert "uploadChecklist" in publish_packet_json
    assert "sceneReview" in publish_packet_json
    publish_actions_text = "\n".join(publish_packet_json["nextImprovementActions"])
    assert "Korean Shorts/long-form references" in publish_actions_text
    assert "generate and download" not in publish_actions_text
    assert "generate/download" not in publish_actions_text
    assert "generate and download" not in publish_packet_text
    assert "generate/download" not in publish_packet_text
    assert "## Scene Review" in publish_packet_text
    assert "## Upload Checklist" in publish_packet_text
    assert payload["channelReadiness"]["status"] == "needs-original-footage"
    assert payload["uploadReview"]["status"] == "blocked"
    assert payload["reviewFramePaths"] == []
    assert payload["audioLevel"]["ok"] is False
    assert payload["qualityAudit"]["summary"]["total"] == 20
    assert quality_audit_json["summary"]["total"] == 20
    assert payload["qualityAudit"]["metrics"]["acceptedScenes"] == 0
    assert payload["qualityAudit"]["metrics"]["qualityScore"] == payload["qualityAudit"]["summary"]["passed"]
    assert payload["qualityAudit"]["metrics"]["blockerCount"] >= 3
    assert any("uploadReview:status=blocked" in item for item in payload["qualityAudit"]["hardFailures"])
    assert any("topTierReadiness:status=needs-grok-local-hero" in item for item in payload["qualityAudit"]["hardFailures"])
    assert quality_audit_items["noPlaceholders"]["status"] == "pass"
    assert quality_audit_items["viewerAudioDesign"]["status"] == "pass"
    assert quality_audit_items["stockCandidateCuration"]["status"] == "pass"
    assert payload["qualityAudit"]["summary"]["stockCandidateCurationStatus"] == "not-recorded"
    assert quality_audit_items["bgmAssetRotation"]["status"] == "pass"
    assert quality_audit_items["youtubeBenchmarkGap"]["status"] == "check"
    assert payload["topTierReadiness"]["status"] == "needs-grok-local-hero"
    assert "publishReadiness: ready" in checklist_text
    assert "channelReadiness: needs-original-footage" in checklist_text
    assert "uploadReview: blocked" in checklist_text
    assert "topTierReadiness: needs-grok-local-hero" in checklist_text
    assert "## Top-Tier Required Fixes" in checklist_text
    assert "## Upload Manual Review" in checklist_text
    assert "Thumbnail / first-frame manual review" in checklist_text
    assert "Add at least one original MP4 clip." in checklist_text
    assert "Original or handoff MP4 present" in checklist_text
    assert "Final Upload Quality Checklist" in quality_text
    assert "Grok/local AI hero ready: False" in quality_text
    assert "Viewer audio design evidence" in quality_text
    assert "Full free TTS narration evidence" not in quality_text
    assert "TTS 내레이션이 실제 설명문을 읽음" not in quality_text
    assert "BGM rotation / reuse evidence: PASS" in quality_text
    assert "같은 BGM 기본 트랙 반복 사용 없음: PASS" in quality_text
    assert "reviewFrames: 0" in quality_text


def _ready_companion_readiness() -> dict:
    return {
        "profileDir": r"C:\Users\tester\AppData\Local\Google\Chrome\User Data\Default",
        "profileDetected": True,
        "loadUnpackedPath": r"C:\vibe\projects\video-studio\tools\chrome-grok-companion",
        "companionInstalled": True,
        "codexExtensionInstalled": True,
        "recognizedExtensions": [
            {"id": "video-studio", "name": "Video Studio Grok Companion", "isVideoStudioCompanion": True},
        ],
        "remoteDebuggingPort": 9222,
        "remoteDebuggingListening": True,
        "operatorReady": True,
        "setupRequired": False,
    }


def _setup_required_companion_readiness() -> dict:
    return {
        "profileDir": r"C:\Users\tester\AppData\Local\Google\Chrome\User Data\Default",
        "profileDetected": True,
        "loadUnpackedPath": r"C:\vibe\projects\video-studio\tools\chrome-grok-companion",
        "companionInstalled": False,
        "codexExtensionInstalled": True,
        "recognizedExtensions": [
            {"id": "codex", "name": "Codex", "isCodexExtension": True},
        ],
        "remoteDebuggingPort": 9222,
        "remoteDebuggingListening": False,
        "operatorReady": False,
        "setupRequired": True,
        "note": "Codex Chrome extension is not the Video Studio Grok Companion.",
    }


def test_finalize_render_rejects_channel_packet_when_channel_readiness_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _ready_companion_readiness)
    client = _media_test_client(tmp_path)
    render_dir = tmp_path / "storage" / "renders" / "channel-blocked-render"
    render_dir.mkdir(parents=True)
    output_path = render_dir / "ready.mp4"
    output_path.write_bytes(b"fake mp4")
    quality_path = render_dir / "render-quality-report.json"
    quality_path.write_text(json.dumps({
        "projectId": "channel-blocked-render",
        "publishReadiness": {
            "status": "ready",
            "requiredFixes": [],
            "recommendedFixes": [],
        },
        "channelReadiness": {
            "status": "needs-original-footage",
            "requiredFixes": ["Add Grok app/web or local Wan MP4 hero footage."],
            "recommendedFixes": ["Review thumbnail and audio mix."],
        },
        "uploadReview": {
            "status": "blocked",
            "requiredFixes": ["Create a channel-ready packet with first-scene original MP4 evidence before upload."],
            "manualReviewItems": ["Review thumbnail and audio mix."],
        },
        "topTierReadiness": _top_tier_readiness("needs-channel-evidence", False),
        "productionReview": {
            "summary": {
                "stockOnly": False,
                "missingContinuityScenes": [],
                "missingQualityReviewScenes": [],
                "firstSceneHookReady": True,
                "missingRationaleScenes": [],
            },
        },
        "checks": _current_quality_checks(),
    }), encoding="utf-8")

    response = client.post("/api/finalize-render", json={
        "outputPath": str(output_path),
        "qualityReportPath": str(quality_path),
        "requireChannelReady": True,
    })

    payload = response.get_json()
    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["error"] == "render is not channel-ready"
    assert payload["publishReadiness"]["status"] == "ready"
    assert payload["channelReadiness"]["status"] == "needs-original-footage"
    assert payload["topTierReadiness"]["status"] == "needs-channel-evidence"
    assert payload["requiredFixes"] == ["Add Grok app/web or local Wan MP4 hero footage."]
    assert payload["sourcePipelineStatus"]["paidApiPolicy"]["paidAiApiAllowed"] is False
    assert payload["sourcePipelineStatus"]["grok"]["apiIntegration"] is False
    assert payload["sourcePipelineStatus"]["grok"]["mode"] == "operator-approved-browser-handoff"
    assert "companionDirectImport" not in payload["sourcePipelineStatus"]["grok"]
    assert "browser-control" in payload["sourcePipelineStatus"]["grok"]["nextAction"]
    assert payload["sourcePipelineStatus"]["grok"]["bookmarkletDirectImport"]["available"] is True
    assert payload["sourcePipelineStatus"]["grok"]["bookmarkletDirectImport"]["avoidsChromeDownloadPrompt"] is True
    native_prompt_policy = payload["sourcePipelineStatus"]["grok"]["nativeDownloadPromptPolicy"]
    assert native_prompt_policy["allowedForCodexAutomation"] is False
    assert native_prompt_policy["allowedForGoalCompletion"] is False
    assert native_prompt_policy["blocksIfPromptAppears"] is True
    assert "Downloads watcher fallback" in native_prompt_policy["forbiddenActions"]
    assert "operator downloads/saves the MP4" in payload["sourcePipelineStatus"]["grok"]["nextAction"]
    assert "native browser download prompts" in native_prompt_policy["reason"].lower()
    assert "Do not let Codex click Chrome/Grok Download/Save/Export" in payload["sourcePipelineStatus"]["grok"]["nextAction"]
    assert payload["sourcePipelineStatus"]["localVideo"]["providers"]["wan"]["ready"] is False
    assert payload["sourcePipelineStatus"]["pexels"]["role"].startswith("free support footage")
    action_keys = [item["key"] for item in payload["nextActions"]]
    assert "add-grok-or-local-hero" in action_keys
    assert "add-original-hero-mp4" in action_keys
    hero_action = next(item for item in payload["nextActions"] if item["key"] == "add-grok-or-local-hero")
    assert "signed-in Grok UI" in hero_action["operatorAction"]
    assert "operator save/download and import" in hero_action["operatorAction"]
    assert "Do not press Grok Download/Save/Export" in hero_action["operatorAction"]
    assert "operator save/download" in hero_action["operatorAction"]
    assert "generate/download" not in hero_action["operatorAction"]
    assert "generate and download" not in hero_action["operatorAction"]
    audit_path = Path(payload["blockedQualityAuditPath"])
    assert audit_path.exists()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["promotion"]["finalVideos"] is False
    assert audit["promotion"]["requireChannelReady"] is True
    assert audit["promotion"]["requireTopTier"] is False
    assert audit["error"] == "render is not channel-ready"
    assert audit["channelReadiness"]["status"] == "needs-original-footage"
    assert audit["requiredFixes"] == ["Add Grok app/web or local Wan MP4 hero footage."]
    assert audit["sourcePipelineStatus"]["localVideo"]["anyReady"] is False
    assert audit["nextActions"][0]["key"] == "add-grok-or-local-hero"
    assert audit["summary"]["nextActionKeys"][:2] == ["add-grok-or-local-hero", "add-original-hero-mp4"]
    assert not (tmp_path / "storage" / "final-videos" / "channel-blocked-render").exists()


def test_finalize_render_copies_channel_ready_packet_when_required(tmp_path):
    client = _media_test_client(tmp_path)
    render_dir = tmp_path / "storage" / "renders" / "channel-ready-render"
    render_dir.mkdir(parents=True)
    output_path = render_dir / "ready.mp4"
    output_path.write_bytes(b"fake mp4")
    quality_path = render_dir / "render-quality-report.json"
    quality_path.write_text(json.dumps({
        "projectId": "channel-ready-render",
        "publishReadiness": {
            "status": "ready",
            "requiredFixes": [],
            "recommendedFixes": [],
        },
        "channelReadiness": {
            "status": "channel-ready",
            "requiredFixes": [],
            "recommendedFixes": [],
            "summary": {
                "heroAiOrLocalReady": True,
                "heroOriginalClipReady": True,
            },
        },
        "uploadReview": {
            "status": "ready",
            "requiredFixes": [],
            "manualReviewItems": [],
            "summary": {
                "captionLayoutReady": True,
                "assetDiversityReady": True,
                "freeAssetProvenanceReady": True,
                "audioMixReviewReady": True,
                "platformComparisonReady": True,
            },
        },
        "topTierReadiness": _top_tier_readiness("top-tier-ready", True),
        "productionReview": {
            "summary": {
                "stockOnly": False,
                "missingContinuityScenes": [],
                "missingQualityReviewScenes": [],
                "firstSceneHookReady": True,
                "missingRationaleScenes": [],
            },
        },
        "checks": _current_quality_checks(
            ttsNarrationEvidence={
                "status": "pass",
                "detail": "noVoiceAudioDesignScenes=['scene-01']; BGM/native audio review passed",
            },
            channelReadinessGate={"status": "pass", "detail": "status=channel-ready"},
            uploadReviewGate={"status": "pass", "detail": "status=ready"},
            topTierReadinessGate={"status": "pass", "detail": "status=top-tier-ready"},
        ),
    }), encoding="utf-8")

    response = client.post("/api/finalize-render", json={
        "outputPath": str(output_path),
        "qualityReportPath": str(quality_path),
        "requireChannelReady": True,
    })

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["channelReadyRequired"] is True
    assert payload["topTierReadiness"]["status"] == "top-tier-ready"
    assert payload["channelReadiness"]["status"] == "channel-ready"
    assert Path(payload["finalVideoPath"]).exists()
    assert Path(payload["qualityChecklistPath"]).exists()
    assert Path(payload["qualityAuditPath"]).exists()
    assert payload["qualityAudit"]["summary"]["channelReady"] is True
    assert payload["qualityAudit"]["summary"]["audioDesignReady"] is True
    assert payload["qualityAudit"]["summary"]["narrationReady"] is True
    assert payload["qualityAudit"]["metrics"]["qualityScore"] == payload["qualityAudit"]["summary"]["passed"]
    assert payload["qualityAudit"]["metrics"]["blockerCount"] == len(payload["qualityAudit"]["summary"]["checksNeeded"])
    assert "hardFailures" not in payload["qualityAudit"]
    assert Path(payload["publishPacketPath"]).exists()
    assert Path(payload["publishPacketMarkdownPath"]).exists()
    publish_packet = payload["publishPacket"]
    assert publish_packet["decision"]["key"] == "artifact-packet-ready"
    assert publish_packet["decision"]["label"] == "패킷 준비"
    assert publish_packet["decision"]["scope"] == "artifact-packet"
    assert publish_packet["decision"]["uploadApproval"] is False
    assert publish_packet["decision"]["sameDayUploadApproval"] is False
    assert "final-library pre-upload evidence" in publish_packet["decision"]["reason"]
    assert publish_packet["decisionScope"] == "artifact-packet"
    assert "artifact-scoped" in publish_packet["preUploadBoundary"]
    assert publish_packet["sameDayUploadDecision"]["status"] == "requires-final-library-evidence"
    assert publish_packet["sameDayUploadDecision"]["label"] == "사전 업로드 증거 필요"
    assert "업로드 가능" not in json.dumps(publish_packet, ensure_ascii=False)
    publish_packet_text = Path(payload["publishPacketMarkdownPath"]).read_text(encoding="utf-8")
    assert "decision: 패킷 준비 (artifact-packet-ready)" in publish_packet_text
    assert "업로드 가능" not in publish_packet_text
    quality_audit_items = {item["key"]: item for item in payload["qualityAudit"]["checklist"]}
    assert quality_audit_items["viewerAudioDesign"]["status"] == "pass"
    assert "noVoiceAudioDesignScenes=['scene-01']" in quality_audit_items["viewerAudioDesign"]["detail"]
    quality_text = Path(payload["qualityChecklistPath"]).read_text(encoding="utf-8")
    assert "Viewer audio design evidence" in quality_text
    assert "Full free TTS narration evidence" not in quality_text
    assert payload["audioLevel"]["ok"] is False


def test_finalize_render_rejects_top_tier_packet_without_grok_or_local_hero(tmp_path):
    client = _media_test_client(tmp_path)
    render_dir = tmp_path / "storage" / "renders" / "channel-ready-direct-only"
    render_dir.mkdir(parents=True)
    output_path = render_dir / "ready.mp4"
    output_path.write_bytes(b"fake mp4")
    quality_path = render_dir / "render-quality-report.json"
    quality_path.write_text(json.dumps({
        "projectId": "channel-ready-direct-only",
        "publishReadiness": {
            "status": "ready",
            "requiredFixes": [],
            "recommendedFixes": [],
        },
        "channelReadiness": {
            "status": "channel-ready",
            "requiredFixes": [],
            "recommendedFixes": [],
            "summary": {
                "heroAiOrLocalReady": False,
                "heroOriginalClipReady": True,
                "heroOriginalityEvidenceReady": True,
            },
        },
        "uploadReview": {
            "status": "ready",
            "requiredFixes": [],
            "manualReviewItems": [],
            "summary": {
                "narrationReady": True,
                "captionLayoutReady": True,
                "assetDiversityReady": True,
                "freeAssetProvenanceReady": True,
                "audioMixReviewReady": True,
                "platformComparisonReady": True,
            },
        },
        "topTierReadiness": _top_tier_readiness("needs-grok-local-hero", False),
        "productionReview": {
            "summary": {
                "stockOnly": False,
                "missingContinuityScenes": [],
                "missingQualityReviewScenes": [],
                "firstSceneHookReady": True,
                "missingRationaleScenes": [],
            },
        },
        "checks": _current_quality_checks(
            channelReadinessGate={"status": "pass", "detail": "status=channel-ready"},
            uploadReviewGate={"status": "pass", "detail": "status=ready"},
            topTierReadinessGate={"status": "warn", "detail": "status=needs-grok-local-hero"},
        ),
    }), encoding="utf-8")

    response = client.post("/api/finalize-render", json={
        "outputPath": str(output_path),
        "qualityReportPath": str(quality_path),
        "requireTopTier": True,
    })

    payload = response.get_json()
    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["error"] == "render is not top-tier-ready"
    assert payload["channelReadiness"]["status"] == "channel-ready"
    assert payload["topTierReadiness"]["status"] == "needs-grok-local-hero"
    assert any("Grok app/web or local Wan/LTX/Hunyuan" in item for item in payload["requiredFixes"])
    action_keys = [item["key"] for item in payload["nextActions"]]
    assert "add-grok-or-local-hero" in action_keys
    assert "complete-top-tier-gate" in action_keys
    grok_action = next(item for item in payload["nextActions"] if item["key"] == "add-grok-or-local-hero")
    assert "Grok app/web handoff path first" in grok_action["operatorAction"]
    assert "operator save/download" in grok_action["operatorAction"]
    assert "already-saved MP4 batch upload" in grok_action["operatorAction"]
    assert "generate and download" not in grok_action["operatorAction"]
    assert "generate/download" not in grok_action["operatorAction"]
    assert "approved Grok browser automation" not in grok_action["operatorAction"]
    audit = json.loads(Path(payload["blockedQualityAuditPath"]).read_text(encoding="utf-8"))
    assert audit["promotion"]["requireTopTier"] is True
    assert audit["topTierReadiness"]["status"] == "needs-grok-local-hero"
    assert not (tmp_path / "storage" / "final-videos" / "channel-ready-direct-only").exists()


def test_finalize_render_source_mix_block_surfaces_direct_import_action(tmp_path):
    client = _media_test_client(tmp_path)
    render_dir = tmp_path / "storage" / "renders" / "source-mix-blocked"
    render_dir.mkdir(parents=True)
    output_path = render_dir / "ready.mp4"
    output_path.write_bytes(b"fake mp4")
    quality_path = render_dir / "render-quality-report.json"
    source_mix_criterion = {
        "key": "originalSourceMix",
        "label": "Original/direct source mix",
        "status": "fail",
        "detail": "originalClipScenes=2, minOriginalScenes=3, stockVideoScenes=3",
        "required": True,
    }
    quality_path.write_text(json.dumps({
        "projectId": "source-mix-blocked",
        "publishReadiness": {
            "status": "ready",
            "requiredFixes": [],
            "recommendedFixes": [],
        },
        "channelReadiness": {
            "status": "channel-ready",
            "requiredFixes": [],
            "recommendedFixes": [],
            "summary": {
                "firstSceneId": "scene-01",
                "heroAiOrLocalReady": True,
                "heroOriginalClipReady": True,
                "heroOriginalityEvidenceReady": True,
            },
        },
        "uploadReview": {
            "status": "blocked",
            "requiredFixes": ["Replace at least half of scenes with original/direct moving MP4 source."],
            "manualReviewItems": [],
            "summary": {
                "originalSourceMixRequired": True,
                "originalSourceMixReady": False,
                "originalClipScenes": 2,
                "minOriginalScenes": 3,
                "stockVideoScenes": 3,
            },
            "criteria": [source_mix_criterion],
        },
        "topTierReadiness": {
            "status": "needs-original-source-mix",
            "score": {"passed": 12, "total": 13},
            "requiredFixes": ["Replace at least half of scenes with original/direct moving MP4 source."],
            "recommendedFixes": [],
            "summary": {
                "publishStatus": "ready",
                "channelStatus": "channel-ready",
                "uploadStatus": "blocked",
                "firstSceneId": "scene-01",
                "grokOrLocalHeroReady": True,
                "originalHeroReady": True,
                "originalSourceMixReady": False,
                "originalClipScenes": 2,
                "minOriginalScenes": 3,
                "stockVideoScenes": 3,
                "originalClipSceneIds": ["scene-01", "scene-04"],
                "topTierEvidenceReady": False,
            },
            "criteria": [source_mix_criterion],
        },
        "productionReview": {
            "summary": {
                "stockOnly": False,
                "missingContinuityScenes": [],
                "missingQualityReviewScenes": [],
                "firstSceneHookReady": True,
                "missingRationaleScenes": [],
                "stockVideoScenes": 3,
                "stockVideoSceneIds": ["scene-02", "scene-03", "scene-05"],
                "originalClipSceneIds": ["scene-01", "scene-04"],
            },
        },
        "checks": _current_quality_checks(
            channelReadinessGate={"status": "pass", "detail": "status=channel-ready"},
            uploadReviewGate={"status": "fail", "detail": "status=blocked"},
            topTierReadinessGate={"status": "warn", "detail": "status=needs-original-source-mix"},
        ),
    }), encoding="utf-8")

    response = client.post("/api/finalize-render", json={
        "outputPath": str(output_path),
        "qualityReportPath": str(quality_path),
        "requireTopTier": True,
    })

    payload = response.get_json()
    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["error"] == "render is not top-tier-ready"
    assert payload["topTierReadiness"]["status"] == "needs-original-source-mix"
    action_keys = [item["key"] for item in payload["nextActions"]]
    assert action_keys[0] == "fix-original-source-mix"
    source_mix_action = payload["nextActions"][0]
    assert "2/3" in source_mix_action["detail"]
    assert "scene-02, scene-03, scene-05" in source_mix_action["detail"]
    assert "Replace at least 1 stock/support scene" in source_mix_action["operatorAction"]
    assert "operator-owned manual download/import" in source_mix_action["operatorAction"]
    assert "already-saved MP4 batch import" in source_mix_action["operatorAction"]
    assert "Grok Download/Save/Export" in source_mix_action["operatorAction"]
    assert "Chrome native download prompts" in source_mix_action["operatorAction"]
    assert "Downloads watcher fallback" in source_mix_action["operatorAction"]
    assert "add-grok-or-local-hero" not in action_keys
    audit = json.loads(Path(payload["blockedQualityAuditPath"]).read_text(encoding="utf-8"))
    assert audit["nextActions"][0]["key"] == "fix-original-source-mix"
    assert audit["summary"]["nextActionKeys"][0] == "fix-original-source-mix"
    assert not (tmp_path / "storage" / "final-videos" / "source-mix-blocked").exists()


def test_finalize_render_visual_fit_failures_outrank_generic_top_tier_action(tmp_path, monkeypatch):
    client = _media_test_client(tmp_path)
    render_dir = tmp_path / "storage" / "renders" / "visual-fit-blocked"
    render_dir.mkdir(parents=True)
    output_path = render_dir / "ready.mp4"
    output_path.write_bytes(b"fake mp4")
    quality_path = render_dir / "render-quality-report.json"
    quality_path.write_text(json.dumps({
        "projectId": "visual-fit-blocked",
        "publishReadiness": {
            "status": "blocked",
            "requiredFixes": ["Replace mismatched stock/AI clips."],
            "recommendedFixes": [],
        },
        "channelReadiness": {
            "status": "blocked",
            "requiredFixes": ["Watch the render/contact sheet and pass each scene visual verdict."],
            "recommendedFixes": [],
            "summary": {
                "firstSceneId": "scene-01",
                "heroAiOrLocalReady": True,
                "heroOriginalClipReady": True,
                "heroOriginalityEvidenceReady": True,
            },
        },
        "uploadReview": {
            "status": "blocked",
            "requiredFixes": ["Resolve scene visual-fit failures before upload."],
            "manualReviewItems": [],
            "summary": {
                "originalSourceMixRequired": True,
                "originalSourceMixReady": True,
                "originalClipScenes": 3,
                "minOriginalScenes": 3,
                "stockVideoScenes": 2,
            },
        },
        "topTierReadiness": {
            "status": "needs-publish-rework",
            "score": {"passed": 15, "total": 21},
            "requiredFixes": ["Resolve publish-readiness before judging top-tier quality."],
            "recommendedFixes": [],
            "summary": {
                "publishStatus": "blocked",
                "channelStatus": "blocked",
                "uploadStatus": "blocked",
                "firstSceneId": "scene-01",
                "grokOrLocalHeroReady": True,
                "originalHeroReady": True,
                "originalSourceMixReady": True,
                "originalClipScenes": 3,
                "minOriginalScenes": 3,
                "stockVideoScenes": 2,
                "originalClipSceneIds": ["scene-01", "scene-04", "scene-05"],
                "topTierEvidenceReady": False,
            },
            "criteria": [
                {
                    "key": "originalSourceMix",
                    "label": "Original/direct source mix",
                    "status": "pass",
                    "detail": "originalClipScenes=3, minOriginalScenes=3, stockVideoScenes=2",
                    "required": True,
                }
            ],
        },
        "productionReview": {
            "summary": {
                "stockOnly": False,
                "missingContinuityScenes": [],
                "missingQualityReviewScenes": [],
                "firstSceneHookReady": True,
                "missingRationaleScenes": [],
                "originalClipSceneIds": ["scene-01", "scene-04", "scene-05"],
                "stockVideoSceneIds": ["scene-02", "scene-03"],
                "failedVisualVerdictScenes": ["scene-03"],
                "missingVisualVerdictScenes": [],
                "missingCaptionLayoutReviewScenes": ["scene-03", "scene-05"],
            },
        },
        "checks": _current_quality_checks(
            aiSlopVisualFit={
                "status": "fail",
                "detail": "failedVisualVerdictScenes=['scene-03']",
            },
            stockAiClipFit={
                "status": "fail",
                "detail": "failedVisualVerdictScenes=['scene-03']",
            },
            captionLayoutReview={
                "status": "fail",
                "detail": "missing=['scene-03', 'scene-05']",
            },
            channelReadinessGate={"status": "fail", "detail": "status=blocked"},
            uploadReviewGate={"status": "fail", "detail": "status=blocked"},
            topTierReadinessGate={"status": "warn", "detail": "status=needs-publish-rework"},
        ),
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_source_pipeline_status", lambda _report: {
        "sourceRecoveryPlan": {
            "status": "needs-source-recovery",
            "scenes": [
                {
                    "sceneId": "scene-03",
                    "status": "script-rewrite-needed",
                    "recommendedLane": "rewrite-selected-stock-fallback",
                    "selectedFileName": "scene-03-v4-20260603-grok.mp4",
                    "localReview": {
                        "verdict": "fail-upload-grade",
                        "uploadReady": False,
                    },
                    "pexelsCandidateFileName": "scene-03-pexels-27430390-neck-pain.mp4",
                    "pexelsVerdict": "conditional-fallback",
                    "pexelsRequiresScriptRewrite": True,
                    "pexelsRequiresPhoneFirstFrameReview": True,
                    "directRenderAllowed": False,
                    "operatorAction": "Rewrite scene-03 to fit the selected-stock fallback, then rerun phone-sized first-frame/caption/source-fit review.",
                }
            ],
        },
        "selectedStockRewriteComparison": {
            "available": True,
            "status": "comparison-only-not-upload-ready",
            "projectId": "live-channel-fresh-source-rewrite-20260603-01",
            "uploadReady": False,
            "originalClipScenes": 2,
            "minOriginalScenes": 3,
            "stockVideoScenes": 3,
            "heroOriginalReady": False,
            "sourceMixReady": False,
            "scenesById": {
                "scene-03": {
                    "sceneId": "scene-03",
                    "projectId": "live-channel-fresh-source-rewrite-20260603-01",
                    "visualVerdictPass": True,
                    "captionLayoutReviewed": True,
                    "sourceMixRegression": True,
                    "heroOriginalReady": False,
                    "uploadReady": False,
                    "originalClipScenes": 2,
                    "minOriginalScenes": 3,
                    "stockVideoScenes": 3,
                    "channelStatus": "needs-hero-original-footage",
                    "uploadStatus": "blocked",
                    "topTierStatus": "needs-channel-evidence",
                    "operatorAction": "Use this rewrite draft only as a comparison candidate.",
                }
            },
        },
    })

    response = client.post("/api/finalize-render", json={
        "outputPath": str(output_path),
        "qualityReportPath": str(quality_path),
        "requireTopTier": True,
    })

    payload = response.get_json()
    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["error"] == "render is not publish-ready"
    action_keys = [item["key"] for item in payload["nextActions"]]
    assert action_keys[:2] == ["fix-visual-fit-failures", "fix-caption-layout"]
    visual_action = payload["nextActions"][0]
    assert "scene-03" in visual_action["detail"]
    assert "sourceRecovery=scene-03" in visual_action["detail"]
    assert "rewrite-selected-stock-fallback" in visual_action["detail"]
    assert "scene-03-pexels-27430390-neck-pain.mp4" in visual_action["detail"]
    assert "rewriteDraft=live-channel-fresh-source-rewrite-20260603-01" in visual_action["detail"]
    assert "sourceMix=2/3" in visual_action["detail"]
    assert "heroOriginal=false" in visual_action["detail"]
    assert "operator-owned manual download/import" in visual_action["operatorAction"]
    assert "Chrome/Grok Download/Save/Export" in visual_action["operatorAction"]
    assert "Downloads watcher fallback blocked" in visual_action["operatorAction"]
    assert "Conditional selected-stock fallbacks" in visual_action["operatorAction"]
    assert "comparison-only evidence" in visual_action["operatorAction"]
    assert visual_action["sourceRecovery"][0]["sceneId"] == "scene-03"
    assert visual_action["sourceRecovery"][0]["recommendedLane"] == "rewrite-selected-stock-fallback"
    assert visual_action["sourceRecovery"][0]["pexelsRequiresScriptRewrite"] is True
    assert visual_action["sourceRecovery"][0]["pexelsRequiresPhoneFirstFrameReview"] is True
    rewrite_candidate = visual_action["sourceRecovery"][0]["selectedStockRewriteCandidate"]
    assert rewrite_candidate["projectId"] == "live-channel-fresh-source-rewrite-20260603-01"
    assert rewrite_candidate["visualVerdictPass"] is True
    assert rewrite_candidate["captionLayoutReviewed"] is True
    assert rewrite_candidate["uploadReady"] is False
    assert rewrite_candidate["sourceMixRegression"] is True
    assert "complete-top-tier-gate" in action_keys
    audit = json.loads(Path(payload["blockedQualityAuditPath"]).read_text(encoding="utf-8"))
    assert audit["metrics"]["acceptedScenes"] == 3
    assert audit["metrics"]["qualityScore"] == 15
    assert audit["metrics"]["blockerCount"] > 0
    assert any(item.startswith("aiSlopVisualFit:") for item in audit["hardFailures"])
    assert any(item.startswith("stockAiClipFit:") for item in audit["hardFailures"])
    assert audit["nextActions"][0]["key"] == "fix-visual-fit-failures"
    assert audit["nextActions"][0]["sourceRecovery"][0]["recommendedLane"] == "rewrite-selected-stock-fallback"
    assert audit["nextActions"][0]["sourceRecovery"][0]["selectedStockRewriteCandidate"]["uploadReady"] is False
    assert audit["summary"]["nextActionKeys"][:2] == ["fix-visual-fit-failures", "fix-caption-layout"]
    assert not (tmp_path / "storage" / "final-videos" / "visual-fit-blocked").exists()


def test_final_video_library_audit_ranks_existing_packets(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _ready_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    top_dir = final_root / "top-tier"
    upload_only_dir = final_root / "upload-only"
    missing_audit_dir = final_root / "missing-audit"
    top_dir.mkdir(parents=True)
    upload_only_dir.mkdir(parents=True)
    missing_audit_dir.mkdir(parents=True)
    (top_dir / "top.mp4").write_bytes(b"not a real mp4 but ffprobe is mocked")
    (upload_only_dir / "upload.mp4").write_bytes(b"not a real mp4 but ffprobe is mocked")
    (missing_audit_dir / "missing.mp4").write_bytes(b"not a real mp4 but ffprobe is mocked")
    _write_publish_packet_artifact(top_dir, "top")
    _write_publish_packet_artifact(upload_only_dir, "upload")

    (top_dir / "quality-audit.json").write_text(json.dumps({
        "summary": {
            "readyForUpload": True,
            "channelReady": True,
            "grokOrLocalHeroReady": True,
            "originalHeroReady": True,
            "narrationReady": True,
            "captionLayoutReady": True,
            "assetDiversityReady": True,
            "freeAssetProvenanceReady": True,
            "bgmRotationReady": True,
            "audioMixReviewReady": True,
            "platformComparisonReady": True,
            "topTierEvidenceReady": True,
            "benchmarkGap": "none",
        },
        "uploadReview": {"status": "ready"},
        "channelReadiness": {"status": "channel-ready"},
        "publishReadiness": {"status": "ready"},
    }), encoding="utf-8")
    (upload_only_dir / "quality-audit.json").write_text(json.dumps({
        "summary": {
            "readyForUpload": True,
            "channelReady": False,
            "grokOrLocalHeroReady": False,
            "originalHeroReady": True,
        },
        "uploadReview": {"status": "ready"},
        "channelReadiness": {"status": "needs-original-footage"},
        "publishReadiness": {"status": "ready"},
    }), encoding="utf-8")

    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["counts"]["withMp4"] == 3
    assert payload["counts"]["withQualityAudit"] == 2
    assert payload["counts"]["withPublishPacket"] == 2
    assert payload["counts"]["withPublishPacketContentReady"] == 2
    assert payload["counts"]["uploadReady"] == 2
    assert payload["counts"]["channelReady"] == 1
    assert payload["counts"]["topTierReady"] == 1
    assert payload["counts"]["missingQualityAudit"] == 1
    assert payload["counts"]["missingPublishPacketContent"] == 1
    assert payload["bestPacket"]["projectId"] == "top-tier"

    packets = {item["projectId"]: item for item in payload["packets"]}
    assert packets["top-tier"]["summary"]["topTierReady"] is True
    assert packets["top-tier"]["summary"]["publishPacketContentReady"] is True
    assert packets["top-tier"]["nextActions"][0]["key"] == "publish-review"
    assert "add-grok-or-local-hero" in packets["upload-only"]["summary"]["nextActionKeys"]
    upload_only_hero_action = next(
        item for item in packets["upload-only"]["nextActions"] if item["key"] == "add-grok-or-local-hero"
    )
    assert "browser-control" in upload_only_hero_action["operatorAction"]
    assert "operator save/download" in upload_only_hero_action["operatorAction"]
    assert "generate and download" not in upload_only_hero_action["operatorAction"]
    assert "generate/download" not in upload_only_hero_action["operatorAction"]
    assert "missing-quality-audit" in packets["missing-audit"]["summary"]["nextActionKeys"]
    assert payload["sourcePipelineStatus"]["paidApiPolicy"]["paidAiApiAllowed"] is False
    assert "companionDirectImport" not in payload["sourcePipelineStatus"]["grok"]
    assert "operator-owned local MP4 import" in payload["sourcePipelineStatus"]["paidApiPolicy"]["allowedAutomation"]
    assert payload["sourcePipelineStatus"]["grok"]["bookmarkletDirectImport"]["uploadEndpointDriven"] is True
    assert payload["sourcePipelineStatus"]["grok"]["bookmarkletDirectImport"]["operatorReady"] is True
    assert payload["sourcePipelineStatus"]["currentEvidence"]["heroAiOrLocalReady"] is True
    assert payload["sourcePipelineStatus"]["currentEvidence"]["heroOriginalClipReady"] is True
    assert payload["gateSystem"]["systemVersion"] == "2026-06-08-unified-quality-gate-system-v1"
    assert payload["gateSystem"] == payload["goalReadiness"]["gateSystem"]
    assert payload["gateSystem"]["surface"] == "final-video-library"
    assert payload["gateSystem"]["finalReadinessSummary"]["gateCount"] == 7
    assert "broad-operating-goal" in payload["gateSystem"]["finalReadinessSummary"]["blockingGateKeys"]
    assert payload["gateSystem"]["blockingPhaseKey"] in payload["gateSystem"]["finalReadinessSummary"]["blockingGateKeys"]
    assert payload["gateSystem"]["phaseStates"]
    assert payload["goalReadiness"]["artifactReady"] is True
    assert payload["goalReadiness"]["goalComplete"] is False
    assert payload["goalReadiness"]["overallStatus"] == "incomplete"
    assert payload["goalReadiness"]["liveGrokDirectImportProven"] is False
    requirement_keys = [item["key"] for item in payload["goalReadiness"]["requirements"]]
    assert requirement_keys == [
        "A-quality-cause-remediation",
        "B-dashboard-production-flow",
        "C-caption-layout-quality",
        "D-top-tier-ai-assisted-standard",
        "E-real-test-mp4",
    ]
    assert any("Artifact-level top-tier proof exists" in item for item in payload["goalReadiness"]["remainingGaps"])


def test_final_video_library_audit_blocks_longform_publish_ready_without_minimum_release_packet(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _ready_companion_readiness)
    client = _media_test_client(tmp_path)
    packet_dir = tmp_path / "storage" / "final-videos" / "longform-missing-release"
    _write_ready_final_video_packet(packet_dir, "longform-missing-release")
    for artifact_name in ("quality-audit.json", "render-quality-report.json"):
        path = packet_dir / artifact_name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.update({
            "formatProfile": "longform_10m",
            "durationSec": 610,
            "publishReadyClaim": True,
        })
        path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 610.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    packet = payload["bestPacket"]
    assert payload["counts"]["uploadReady"] == 0
    assert payload["counts"]["channelReady"] == 0
    assert payload["counts"]["topTierReady"] == 0
    assert packet["longformMinimumRelease"]["status"] == "fail"
    assert packet["summary"]["longformMinimumReleaseRequired"] is True
    assert packet["summary"]["longformMinimumReleaseReady"] is False
    assert "complete-longform-minimum-release" in packet["summary"]["nextActionKeys"]


def test_final_video_library_audit_allows_longform_publish_ready_with_passing_minimum_release_packet(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _ready_companion_readiness)
    client = _media_test_client(tmp_path)
    packet_dir = tmp_path / "storage" / "final-videos" / "longform-release-ready"
    _write_ready_final_video_packet(packet_dir, "longform-release-ready")
    (packet_dir / "longform-minimum-release-packet.json").write_text(
        json.dumps(_longform_minimum_release_packet()),
        encoding="utf-8",
    )
    for artifact_name in ("quality-audit.json", "render-quality-report.json"):
        path = packet_dir / artifact_name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.update({
            "formatProfile": "longform_10m",
            "durationSec": 610,
            "publishReadyClaim": True,
        })
        path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 610.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    packet = payload["bestPacket"]
    assert payload["counts"]["uploadReady"] == 1
    assert payload["counts"]["channelReady"] == 1
    assert payload["counts"]["topTierReady"] == 1
    assert packet["longformMinimumRelease"]["status"] == "pass"
    assert packet["summary"]["longformMinimumReleaseRequired"] is True
    assert packet["summary"]["longformMinimumReleaseReady"] is True


def test_final_video_library_audit_prefers_publish_packet_final_mp4_over_newer_auxiliary_mp4(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _ready_companion_readiness)
    client = _media_test_client(tmp_path)
    packet_dir = tmp_path / "storage" / "final-videos" / "top-tier-with-phone-preview"
    _write_ready_final_video_packet(packet_dir, "top-tier-with-phone-preview")
    final_video = packet_dir / "top-tier-with-phone-preview.mp4"
    phone_preview = packet_dir / "phone-preview-390w.mp4"
    phone_preview.write_bytes(b"phone preview mp4 is newer but not the final render")
    newer_mtime = final_video.stat().st_mtime + 10
    os.utime(phone_preview, (newer_mtime, newer_mtime))

    def fake_ffprobe(path):
        if Path(path).name == phone_preview.name:
            return {
                "ok": True,
                "width": 390,
                "height": 694,
                "frameRate": 30.0,
                "durationSeconds": 12.0,
                "hasAudio": True,
                "specReady": False,
            }
        return {
            "ok": True,
            "width": 1080,
            "height": 1920,
            "frameRate": 30.0,
            "durationSeconds": 12.0,
            "hasAudio": True,
            "specReady": True,
        }

    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", fake_ffprobe)

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["bestPacket"]["projectId"] == "top-tier-with-phone-preview"
    assert payload["bestPacket"]["finalVideoPath"].endswith("top-tier-with-phone-preview.mp4")
    assert payload["bestPacket"]["summary"]["topTierReady"] is True
    assert payload["counts"]["topTierReady"] == 1


def test_final_video_library_audit_blocks_incomplete_publish_packet_content(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _ready_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "incomplete-publish-packet"
    _write_ready_final_video_packet(packet_dir, "incomplete-publish-packet")
    (packet_dir / "publish-packet.json").write_text(json.dumps({
        "projectId": "incomplete-publish-packet",
        "finalMp4": str(packet_dir / "incomplete-publish-packet.mp4"),
        "titleCandidates": ["Has a title only"],
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    packet = payload["bestPacket"]
    assert payload["counts"]["withPublishPacket"] == 1
    assert payload["counts"]["withPublishPacketContentReady"] == 0
    assert payload["counts"]["uploadReady"] == 0
    assert payload["counts"]["channelReady"] == 0
    assert payload["counts"]["topTierReady"] == 0
    assert packet["hasPublishPacket"] is True
    assert packet["publishPacketAudit"]["ready"] is False
    assert packet["publishPacketAudit"]["status"] == "missing-fields"
    assert "thumbnailCandidates.firstFrame" in packet["publishPacketAudit"]["missingFields"]
    assert "shortcomings" in packet["publishPacketAudit"]["missingFields"]
    assert "artifact packet as ready" in packet["publishPacketAudit"]["operatorAction"]
    assert "uploadable" not in packet["publishPacketAudit"]["operatorAction"]
    assert packet["summary"]["publishPacketContentReady"] is False
    assert packet["summary"]["uploadReady"] is False
    assert packet["summary"]["channelReady"] is False
    assert packet["summary"]["topTierReady"] is False
    assert "complete-publish-packet" in packet["summary"]["nextActionKeys"]
    assert payload["goalReadiness"]["artifactReady"] is False
    assert payload["goalReadiness"]["goalComplete"] is False


def test_final_video_library_audit_blocks_unsafe_publish_packet_source_flow_guidance(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _ready_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "unsafe-source-flow"
    _write_ready_final_video_packet(packet_dir, "unsafe-source-flow")
    _write_publish_packet_artifact(packet_dir, "unsafe-source-flow")
    packet_path = packet_dir / "publish-packet.json"
    packet_payload = json.loads(packet_path.read_text(encoding="utf-8"))
    packet_payload["nextImprovementActions"] = [
        "Use the existing Chrome/Grok app to generate and download a short MP4, then import it."
    ]
    packet_path.write_text(json.dumps(packet_payload), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    packet = payload["bestPacket"]
    assert payload["counts"]["withPublishPacket"] == 1
    assert payload["counts"]["withPublishPacketContentReady"] == 0
    assert payload["counts"]["uploadReady"] == 0
    assert packet["publishPacketAudit"]["ready"] is False
    assert packet["publishPacketAudit"]["status"] == "missing-fields"
    assert "nextImprovementActions.safeSourceFlowGuidance" in packet["publishPacketAudit"]["missingFields"]
    assert "operator-owned local MP4 import" in packet["publishPacketAudit"]["operatorAction"]
    assert "already-saved MP4 batch upload" in packet["publishPacketAudit"]["operatorAction"]
    assert packet["summary"]["publishPacketContentReady"] is False
    assert packet["summary"]["uploadReady"] is False
    assert "complete-publish-packet" in packet["summary"]["nextActionKeys"]


def test_final_video_library_audit_exposes_stock_candidate_curation_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _ready_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "stock-curation-gap"
    packet_dir.mkdir(parents=True)
    (packet_dir / "curation-gap.mp4").write_bytes(b"not a real mp4 but ffprobe is mocked")
    _write_publish_packet_artifact(packet_dir, "stock-curation-gap", final_mp4_name="curation-gap.mp4")
    (packet_dir / "quality-audit.json").write_text(json.dumps({
        "summary": {
            "readyForUpload": True,
            "channelReady": True,
            "grokOrLocalHeroReady": True,
            "originalHeroReady": True,
            "audioDesignReady": True,
            "captionLayoutReady": True,
            "assetDiversityReady": True,
            "freeAssetProvenanceReady": True,
            "bgmRotationReady": True,
            "audioMixReviewReady": True,
            "platformComparisonReady": True,
            "topTierEvidenceReady": True,
            "benchmarkGap": "none",
        },
        "uploadReview": {"status": "ready"},
        "channelReadiness": {"status": "channel-ready"},
        "publishReadiness": {"status": "ready"},
    }), encoding="utf-8")
    (packet_dir / "render-quality-report.json").write_text(json.dumps({
        "projectId": "stock-curation-gap",
        "publishReadiness": {"status": "ready"},
        "channelReadiness": {
            "status": "channel-ready",
            "summary": {
                "heroAiOrLocalReady": True,
                "heroOriginalClipReady": True,
            },
        },
        "uploadReview": {
            "status": "ready",
            "summary": {
                "audioDesignReady": True,
                "captionLayoutReady": True,
                "assetDiversityReady": True,
                "freeAssetProvenanceReady": True,
                "bgmRotationReady": True,
                "audioMixReviewReady": True,
                "platformComparisonReady": True,
            },
        },
        "topTierReadiness": {
            "status": "top-tier-ready",
            "summary": {
                "topTierEvidenceReady": True,
                "stockCandidateCurationReady": False,
                "benchmarkGap": "missing stock candidate curation",
            },
        },
        "productionReview": {
            "summary": {
                "stockOnly": False,
                "firstSceneHookReady": True,
                "missingRationaleScenes": [],
                "missingContinuityScenes": [],
                "missingNarrationScenes": [],
                "thinNarrationScenes": [],
                "missingCaptionLayoutReviewScenes": [],
                "repeatedVisualAssetScenes": [],
                "missingFreeAssetProvenanceScenes": [],
                "missingFreeAudioProvenanceAssets": [],
                "stockCandidateCurationScenes": ["scene-01"],
                "stockCandidateCurationReadyScenes": [],
                "missingStockCandidateCurationScenes": ["scene-01"],
                "missingStockCandidateCountScenes": ["scene-01"],
                "missingStockCandidateCreatorScenes": ["scene-01"],
                "missingStockSelectionSummaryScenes": ["scene-01"],
                "stockCandidateCurationIssuesByScene": {
                    "scene-01": ["candidateCount<2", "creator", "selectionSummary"],
                },
            },
        },
        "checks": _current_quality_checks(
            stockCandidateCuration={
                "status": "warn",
                "detail": "scene-01 lacks candidate pool metadata",
            },
            channelReadinessGate={"status": "pass", "detail": "status=channel-ready"},
            uploadReviewGate={"status": "pass", "detail": "status=ready"},
            topTierReadinessGate={"status": "pass", "detail": "status=top-tier-ready"},
        ),
    }), encoding="utf-8")

    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["counts"]["topTierReady"] == 0
    assert payload["bestPacket"]["projectId"] == "stock-curation-gap"
    summary = payload["bestPacket"]["summary"]
    assert summary["channelReady"] is True
    assert summary["topTierReady"] is False
    assert summary["stockCandidateCurationStatus"] == "warn"
    assert summary["stockCandidateCurationReady"] is False
    assert summary["missingStockCandidateCurationScenes"] == ["scene-01"]
    assert "complete-stock-candidate-curation" in summary["nextActionKeys"]

    curation = payload["sourcePipelineStatus"]["pexels"]["candidateCuration"]
    assert curation["ready"] is False
    assert curation["missingScenes"] == ["scene-01"]
    assert curation["issuesByScene"]["scene-01"] == ["candidateCount<2", "creator", "selectionSummary"]
    assert "candidateCount>=2" in payload["sourcePipelineStatus"]["pexels"]["nextAction"]
    evidence = payload["sourcePipelineStatus"]["currentEvidence"]
    assert evidence["stockCandidateCurationStatus"] == "warn"
    assert evidence["stockCandidateCurationReady"] is False
    assert evidence["missingStockCandidateCurationScenes"] == ["scene-01"]
    top_tier_requirement = next(item for item in payload["goalReadiness"]["requirements"] if item["key"] == "D-top-tier-ai-assisted-standard")
    assert top_tier_requirement["status"] == "partial"
    assert any("Pexels stock candidate curation proof" in item for item in top_tier_requirement["missing"])
    assert payload["goalReadiness"]["goalComplete"] is False


def test_final_video_library_audit_reports_proof_monitor_companion_setup_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    handoff_dir = tmp_path / "storage" / "grok-handoffs" / "live-proof-handoff"
    handoff_dir.mkdir(parents=True)
    (handoff_dir / "handoff.json").write_text(json.dumps({
        "projectId": "live-proof-handoff",
        "scenes": [{"sceneId": "scene-03", "expectedFileName": "scene-03.grok.mp4"}],
        "latestCodexChromeObservation": {
            "postUrl": "https://grok.com/imagine/post/cd0ac4b6-efcb-4c5a-a91b-fcd04533910d?utm=drop",
            "currentUrl": "https://grok.com/imagine/post/cd0ac4b6-efcb-4c5a-a91b-fcd04533910d?utm=drop",
        },
    }), encoding="utf-8")
    final_root = tmp_path / "storage" / "final-videos"
    top_dir = final_root / "top-tier"
    top_dir.mkdir(parents=True)
    (top_dir / "top.mp4").write_bytes(b"not a real mp4 but ffprobe is mocked")
    _write_publish_packet_artifact(top_dir, "top-tier", final_mp4_name="top.mp4")
    (top_dir / "quality-audit.json").write_text(json.dumps({
        "summary": {
            "readyForUpload": True,
            "channelReady": True,
            "grokOrLocalHeroReady": True,
            "originalHeroReady": True,
            "captionLayoutReady": True,
            "topTierEvidenceReady": True,
        },
        "uploadReview": {"status": "ready"},
        "topTierReadiness": {"status": "top-tier-ready"},
        "checks": _current_quality_checks(),
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    assert "companionDirectImport" not in payload["sourcePipelineStatus"]["grok"]
    assert "operator downloads/saves the MP4" in payload["sourcePipelineStatus"]["grok"]["nextAction"]
    assert payload["sourcePipelineStatus"]["grok"]["bookmarkletDirectImport"]["operatorReady"] is True
    proof_monitor_url = payload["sourcePipelineStatus"]["grok"]["proofMonitorUrl"]
    assert proof_monitor_url.endswith(
        "/api/grok-handoff/live-proof-handoff/direct-import-proof?sceneId=scene-03"
    )
    assert payload["goalReadiness"]["proofMonitorUrl"] == proof_monitor_url
    observed_post_url = "https://grok.com/imagine/post/cd0ac4b6-efcb-4c5a-a91b-fcd04533910d"
    assert payload["sourcePipelineStatus"]["grok"]["observedPostUrl"] == observed_post_url
    assert payload["sourcePipelineStatus"]["grok"]["observedPostDownloadScriptUrl"].endswith(
        "/api/grok-handoff/live-proof-handoff/observed-post-download.js?operatorApproved=true&sceneId=scene-03"
    )
    assert payload["sourcePipelineStatus"]["grok"]["bookmarkletDirectImport"]["observedPostUrl"] == observed_post_url
    assert payload["sourcePipelineStatus"]["grok"]["bookmarkletDirectImport"]["observedPostDownloadScriptUrl"].endswith(
        "/api/grok-handoff/live-proof-handoff/observed-post-download.js?operatorApproved=true&sceneId=scene-03"
    )
    assert payload["goalReadiness"]["observedPostUrl"] == observed_post_url
    assert "Proof monitor:" in payload["sourcePipelineStatus"]["grok"]["nextAction"]
    assert f"Observed Grok post: {observed_post_url}" in payload["sourcePipelineStatus"]["grok"]["nextAction"]
    assert payload["goalReadiness"]["goalComplete"] is False
    assert any(
        "Capture live signed-in Chrome/Grok generation proof plus local MP4 import/review advancement" in item
        for item in payload["goalReadiness"]["remainingGaps"]
    )


def test_final_video_library_audit_surfaces_latest_handoff_fresh_import_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)

    downloads_dir = tmp_path / "Downloads"
    downloads_dir.mkdir()
    old_download = downloads_dir / "grok-video-old-retained.mp4"
    old_download.write_bytes(b"old retained source")
    old_epoch = 1780230000
    os.utime(old_download, (old_epoch, old_epoch))

    handoff_dir = tmp_path / "storage" / "grok-handoffs" / "fresh-runway"
    incoming_dir = handoff_dir / "incoming"
    incoming_dir.mkdir(parents=True)
    (handoff_dir / "handoff.json").write_text(json.dumps({
        "projectId": "fresh-runway",
        "createdAt": "2026-05-31T23:30:00",
        "defaultDownloadDir": str(downloads_dir),
        "incomingDir": str(incoming_dir),
        "productionQueueUrl": "http://127.0.0.1:5161/api/grok-handoff/fresh-runway/production-queue",
        "reviewPacketUrl": "http://127.0.0.1:5161/api/grok-handoff/fresh-runway/review-packet",
        "scenes": [
            {
                "sceneId": "scene-01",
                "expectedFileName": "scene-01.grok.mp4",
                "promptQuality": {"status": "ready"},
            },
            {
                "sceneId": "scene-02",
                "expectedFileName": "scene-02.grok.mp4",
                "promptQuality": {"status": "ready"},
            },
        ],
    }), encoding="utf-8")

    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "top-tier"
    packet_dir.mkdir(parents=True)
    (packet_dir / "top.mp4").write_bytes(b"not a real mp4 but ffprobe is mocked")
    _write_publish_packet_artifact(packet_dir, "top-tier", final_mp4_name="top.mp4")
    (packet_dir / "quality-audit.json").write_text(json.dumps({
        "summary": {
            "readyForUpload": True,
            "channelReady": True,
            "grokOrLocalHeroReady": True,
            "originalHeroReady": True,
            "captionLayoutReady": True,
            "topTierEvidenceReady": True,
            "benchmarkGap": "none",
        },
        "uploadReview": {"status": "ready"},
        "channelReadiness": {"status": "channel-ready"},
        "topTierReadiness": {"status": "top-tier-ready"},
        "checks": _current_quality_checks(),
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    latest = payload["sourcePipelineStatus"]["grok"]["latestHandoff"]
    assert latest["available"] is True
    assert latest["projectId"] == "fresh-runway"
    assert latest["status"] == "waiting-for-fresh-imports"
    assert latest["blocksOperatingGoal"] is True
    assert latest["importedScenes"] == 0
    assert latest["acceptedScenes"] == 0
    assert latest["missingScenes"] == ["scene-01", "scene-02"]
    preflight = latest["importPreflight"]
    assert latest["importPreflightSummary"] == preflight
    assert preflight["readyForReview"] is False
    assert preflight["presentScenes"] == 0
    assert preflight["readyScenes"] == 0
    assert preflight["missingScenes"] == ["scene-01", "scene-02"]
    assert preflight["needsImportScenes"] == ["scene-01", "scene-02"]
    assert preflight["nextSceneId"] == "scene-01"
    assert latest["scenes"][0]["importPreflight"]["readyForReview"] is False
    assert latest["downloadFreshness"]["freshCandidateCount"] == 0
    assert latest["downloadFreshness"]["excludedOldCandidateCount"] == 1
    assert latest["operatorDecision"]["status"] == "edit"
    assert latest["operatorDecision"]["label"] == "수정 필요"
    assert "Fresh Grok MP4 imports are missing" in latest["operatorDecision"]["detail"]
    assert "Older Downloads MP4s are excluded" in latest["operatorAction"]


def test_final_video_library_audit_prefers_live_channel_handoff_over_newer_toy_handoff(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)

    handoff_root = tmp_path / "storage" / "grok-handoffs"
    live_dir = handoff_root / "live-channel-fresh-source-runway"
    toy_dir = handoff_root / "video-project"
    live_dir.mkdir(parents=True)
    toy_dir.mkdir(parents=True)
    live_incoming = live_dir / "incoming"
    toy_incoming = toy_dir / "incoming"
    live_incoming.mkdir()
    toy_incoming.mkdir()
    (live_dir / "handoff.json").write_text(json.dumps({
        "projectId": "live-channel-fresh-source-runway",
        "createdAt": "2026-05-31T23:30:00",
        "qualityGateRequired": True,
        "grokMainSourceRequired": True,
        "sourceMixTotalScenes": 3,
        "incomingDir": str(live_incoming),
        "scenes": [
            {"sceneId": "scene-01", "expectedFileName": "scene-01.grok.mp4", "promptQuality": {"status": "ready"}},
            {"sceneId": "scene-02", "expectedFileName": "scene-02.grok.mp4", "promptQuality": {"status": "ready"}},
            {"sceneId": "scene-03", "expectedFileName": "scene-03.grok.mp4", "promptQuality": {"status": "ready"}},
        ],
    }), encoding="utf-8")
    (toy_dir / "handoff.json").write_text(json.dumps({
        "projectId": "video-project",
        "createdAt": "2026-06-03T10:13:10",
        "qualityGateRequired": False,
        "grokMainSourceRequired": False,
        "sourceMixTotalScenes": 1,
        "incomingDir": str(toy_incoming),
        "scenes": [
            {
                "sceneId": "scene-01",
                "expectedFileName": "scene-01.grok.mp4",
                "promptQuality": {"status": "needs-rewrite", "missing": ["sourceActionCue", "specificAction"]},
            },
        ],
    }), encoding="utf-8")
    old_epoch = 1780230000
    new_epoch = 1780245000
    os.utime(live_dir / "handoff.json", (old_epoch, old_epoch))
    os.utime(toy_dir / "handoff.json", (new_epoch, new_epoch))

    packet_dir = tmp_path / "storage" / "final-videos" / "top-tier"
    packet_dir.mkdir(parents=True)
    (packet_dir / "top.mp4").write_bytes(b"not a real mp4 but ffprobe is mocked")
    _write_publish_packet_artifact(packet_dir, "top-tier", final_mp4_name="top.mp4")
    (packet_dir / "quality-audit.json").write_text(json.dumps({
        "summary": {
            "readyForUpload": True,
            "channelReady": True,
            "grokOrLocalHeroReady": True,
            "originalHeroReady": True,
            "captionLayoutReady": True,
            "topTierEvidenceReady": True,
            "benchmarkGap": "none",
        },
        "uploadReview": {"status": "ready"},
        "channelReadiness": {"status": "channel-ready"},
        "topTierReadiness": {"status": "top-tier-ready"},
        "checks": _current_quality_checks(),
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    grok = payload["sourcePipelineStatus"]["grok"]
    latest = grok["latestHandoff"]
    assert latest["projectId"] == "live-channel-fresh-source-runway"
    assert latest["totalScenes"] == 3
    assert latest["missingScenes"] == ["scene-01", "scene-02", "scene-03"]
    assert grok["handoffSelection"]["selectedProjectId"] == "live-channel-fresh-source-runway"
    assert grok["handoffSelection"]["latestByMtimeProjectId"] == "video-project"
    assert grok["handoffSelection"]["preferredProductionHandoff"] is True
    assert "video-project" in grok["handoffSelection"]["nonSelectedLatestReason"]


def test_final_video_library_audit_surfaces_browser_generated_but_not_imported_grok_posts(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)

    handoff_dir = tmp_path / "storage" / "grok-handoffs" / "fresh-browser-generated-runway"
    incoming_dir = handoff_dir / "incoming"
    incoming_dir.mkdir(parents=True)
    (handoff_dir / "handoff.json").write_text(json.dumps({
        "projectId": "fresh-browser-generated-runway",
        "createdAt": "2026-05-31T23:30:00",
        "incomingDir": str(incoming_dir),
        "scenes": [
            {
                "sceneId": "scene-01",
                "expectedFileName": "scene-01.grok.mp4",
                "promptQuality": {"status": "ready"},
            },
            {
                "sceneId": "scene-02",
                "expectedFileName": "scene-02.grok.mp4",
                "promptQuality": {"status": "ready"},
            },
        ],
    }), encoding="utf-8")
    (handoff_dir / "browser-generation-proof.json").write_text(json.dumps({
        "schema": "video-studio.grok-browser-generation-proof.v1",
        "createdAt": "2026-06-01T04:35:00",
        "projectId": "fresh-browser-generated-runway",
        "sourceFlow": "existing signed-in Chrome/Grok Imagine web",
        "downloadStatus": "blocked-before-native-mp4-import",
        "generatedScenes": [
            {
                "sceneId": "scene-01",
                "expectedFileName": "scene-01.grok.mp4",
                "postUrl": "https://grok.com/imagine/post/fresh-scene-one",
                "shareUrl": "https://grok.com/imagine/post/fresh-scene-one?source=post-page",
                "observedAt": "2026-06-01T04:30:00",
                "video": {
                    "width": 720,
                    "height": 1280,
                    "durationSeconds": 6.041667,
                    "sourceHost": "assets.grok.com",
                },
                "downloadStatus": "Grok post observed, native MP4 import missing",
                "importedNativeMp4": False,
            },
        ],
        "downloadAttempts": ["downloadMedia opened blocked asset tab", "Grok download button did not create a local MP4"],
        "doesNotSatisfyFreshSourceProof": True,
    }), encoding="utf-8")

    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "top-tier"
    packet_dir.mkdir(parents=True)
    (packet_dir / "top.mp4").write_bytes(b"not a real mp4 but ffprobe is mocked")
    _write_publish_packet_artifact(packet_dir, "top-tier", final_mp4_name="top.mp4")
    (packet_dir / "quality-audit.json").write_text(json.dumps({
        "summary": {
            "readyForUpload": True,
            "channelReady": True,
            "grokOrLocalHeroReady": True,
            "originalHeroReady": True,
            "captionLayoutReady": True,
            "topTierEvidenceReady": True,
            "benchmarkGap": "none",
        },
        "uploadReview": {"status": "ready"},
        "channelReadiness": {"status": "channel-ready"},
        "topTierReadiness": {"status": "top-tier-ready"},
        "checks": _current_quality_checks(),
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    latest = payload["sourcePipelineStatus"]["grok"]["latestHandoff"]
    assert latest["status"] == "browser-generated-waiting-import"
    assert latest["importedScenes"] == 0
    assert latest["missingScenes"] == ["scene-01", "scene-02"]
    generation = latest["browserGenerationProof"]
    assert generation["status"] == "partial-generated-not-imported"
    assert generation["generatedScenes"] == 1
    assert generation["generatedSceneIds"] == ["scene-01"]
    assert generation["missingSceneIds"] == ["scene-02"]
    assert generation["doesNotSatisfyFreshSourceProof"] is True
    assert latest["scenes"][0]["browserGeneration"]["generated"] is True
    assert latest["scenes"][1]["browserGeneration"]["generated"] is False
    assert latest["operatorDecision"]["status"] == "edit"
    assert "browser generation is observed for 1/2 scenes" in latest["operatorDecision"]["detail"]
    assert "native MP4 imports are still missing" in latest["operatorDecision"]["detail"]
    assert payload["goalReadiness"]["goalComplete"] is False

    intake_response = client.post(
        "/api/final-video-library/fresh-source-intake",
        json={"projectId": "fresh-browser-generated-runway"},
    )
    assert intake_response.status_code == 200
    intake = json.loads((handoff_dir / "fresh-source-intake.template.json").read_text(encoding="utf-8"))
    assert intake["counts"]["browserGeneratedScenes"] == 1
    assert intake["browserGenerationProof"]["doesNotSatisfyFreshSourceProof"] is True
    assert "Grok browser generation was observed" in intake["requiredScenes"][0]["operatorAction"]
    assert "operator-owned manual download/import or explicit batch upload from an already saved MP4" in intake["requiredScenes"][0]["operatorAction"]
    assert "do not press Grok Download/Save/Export or any Chrome native download prompt from Codex automation" in intake["requiredScenes"][0]["operatorAction"]
    assert "Generate or acquire a native Grok MP4" in intake["requiredScenes"][1]["operatorAction"]
    assert "operator-owned manual download/import or explicit batch upload from an already-saved local MP4" in intake["requiredScenes"][1]["operatorAction"]


def test_final_video_library_audit_blocks_stale_or_invalid_fresh_imports(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)

    handoff_dir = tmp_path / "storage" / "grok-handoffs" / "fresh-preflight-runway"
    incoming_dir = handoff_dir / "incoming"
    incoming_dir.mkdir(parents=True)
    stale_scene = incoming_dir / "scene-01.grok.mp4"
    invalid_scene = incoming_dir / "scene-02.grok.mp4"
    stale_scene.write_bytes(b"old retained source")
    invalid_scene.write_bytes(b"fresh but not probe-ready")
    old_epoch = 1780230000
    fresh_epoch = 1780245000
    os.utime(stale_scene, (old_epoch, old_epoch))
    os.utime(invalid_scene, (fresh_epoch, fresh_epoch))
    (handoff_dir / "handoff.json").write_text(json.dumps({
        "projectId": "fresh-preflight-runway",
        "createdAt": "2026-05-31T23:30:00",
        "incomingDir": str(incoming_dir),
        "scenes": [
            {
                "sceneId": "scene-01",
                "expectedFileName": "scene-01.grok.mp4",
                "promptQuality": {"status": "ready"},
            },
            {
                "sceneId": "scene-02",
                "expectedFileName": "scene-02.grok.mp4",
                "promptQuality": {"status": "ready"},
            },
        ],
    }), encoding="utf-8")

    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "top-tier"
    packet_dir.mkdir(parents=True)
    final_video = packet_dir / "top.mp4"
    final_video.write_bytes(b"not a real mp4 but ffprobe is mocked")
    _write_publish_packet_artifact(packet_dir, "top-tier", final_mp4_name="top.mp4")
    (packet_dir / "quality-audit.json").write_text(json.dumps({
        "summary": {
            "readyForUpload": True,
            "channelReady": True,
            "grokOrLocalHeroReady": True,
            "originalHeroReady": True,
            "captionLayoutReady": True,
            "topTierEvidenceReady": True,
            "benchmarkGap": "none",
        },
        "uploadReview": {"status": "ready"},
        "channelReadiness": {"status": "channel-ready"},
        "topTierReadiness": {"status": "top-tier-ready"},
        "checks": _current_quality_checks(),
    }), encoding="utf-8")

    def fake_ffprobe(path):
        name = Path(path).name
        if name == "scene-02.grok.mp4":
            return {"ok": False, "error": "ffprobe failed", "specReady": False}
        return {
            "ok": True,
            "width": 1080,
            "height": 1920,
            "frameRate": 30.0,
            "durationSeconds": 12.0,
            "hasAudio": True,
            "specReady": True,
        }

    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", fake_ffprobe)

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    latest = payload["sourcePipelineStatus"]["grok"]["latestHandoff"]
    assert latest["status"] == "import-preflight-failed"
    assert latest["importedScenes"] == 2
    assert latest["missingScenes"] == []
    preflight = latest["importPreflight"]
    assert latest["importPreflightSummary"] == preflight
    assert preflight["readyForReview"] is False
    assert preflight["presentScenes"] == 2
    assert preflight["readyScenes"] == 0
    assert preflight["staleScenes"] == ["scene-01"]
    assert preflight["invalidScenes"] == ["scene-02"]
    assert preflight["needsImportScenes"] == ["scene-01", "scene-02"]
    assert latest["scenes"][0]["importPreflight"]["status"] == "stale"
    assert latest["scenes"][0]["importPreflight"]["readyForReview"] is False
    assert latest["scenes"][1]["importPreflight"]["status"] == "invalid-video"
    assert latest["scenes"][1]["importPreflight"]["readyForReview"] is False
    assert latest["operatorDecision"]["status"] == "edit"
    assert "source import preflight is failing" in latest["operatorDecision"]["detail"]
    assert "ffprobe-invalid" in latest["operatorDecision"]["nextAction"]
    assert payload["goalReadiness"]["goalComplete"] is False


def test_final_video_library_audit_surfaces_rejected_fresh_scene_backlog(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)

    handoff_dir = tmp_path / "storage" / "grok-handoffs" / "fresh-rejected-runway"
    incoming_dir = handoff_dir / "incoming"
    incoming_dir.mkdir(parents=True)
    (incoming_dir / "scene-01.grok.mp4").write_bytes(b"fresh accepted source")
    (incoming_dir / "scene-02.grok.mp4").write_bytes(b"fresh rejected source")
    (incoming_dir / "scene-02-v2-clean-candidate.mp4").write_bytes(b"fresh unreviewed replacement")
    fresh_epoch = 1780245000
    os.utime(incoming_dir / "scene-01.grok.mp4", (fresh_epoch, fresh_epoch))
    os.utime(incoming_dir / "scene-02.grok.mp4", (fresh_epoch, fresh_epoch))
    os.utime(incoming_dir / "scene-02-v2-clean-candidate.mp4", (fresh_epoch, fresh_epoch))
    (handoff_dir / "handoff.json").write_text(json.dumps({
        "projectId": "fresh-rejected-runway",
        "createdAt": "2026-05-31T23:30:00",
        "incomingDir": str(incoming_dir),
        "scenes": [
            {
                "sceneId": "scene-01",
                "expectedFileName": "scene-01.grok.mp4",
                "promptQuality": {"status": "ready"},
            },
            {
                "sceneId": "scene-02",
                "expectedFileName": "scene-02.grok.mp4",
                "promptQuality": {"status": "ready"},
            },
        ],
        "reviewDecisions": {
            "scene-01": {
                "accepted": True,
                "firstTwoSecondHook": True,
                "artifactFree": True,
                "continuityOk": True,
                "captionSafe": True,
                "shotLockMatch": True,
                "sceneAssemblyOk": True,
                "sourceProvenanceConfirmed": True,
                "visualQualityVerdict": "pass",
                "qualityReviewNote": "Accepted source clip starts with clear hand motion and leaves caption-safe space.",
                "selectedFileName": "scene-01.grok.mp4",
            },
            "scene-02": {
                "accepted": False,
                "firstTwoSecondHook": False,
                "artifactFree": False,
                "continuityOk": False,
                "captionSafe": False,
                "shotLockMatch": False,
                "sceneAssemblyOk": False,
                "sourceProvenanceConfirmed": False,
                "visualQualityVerdict": "needs-retry",
                "qualityReviewNote": (
                    "Rejected for upload-grade source review: weak first-frame/hook, AI anatomy artifacts, "
                    "stock-like insert feel, and unsafe caption-safe framing."
                ),
                "operatorNote": "Regenerate without face/body artifacts before render.",
                "selectedFileName": "scene-02.grok.mp4",
                "retryAttempt": 2,
                "nextRetryPrompt": "Regenerate scene-02 as a clean hands-only desk action.",
            },
        },
    }), encoding="utf-8")
    (handoff_dir / "browser-generation-proof.json").write_text(json.dumps({
        "schema": "video-studio.grok-browser-generation-proof.v1",
        "createdAt": "2026-06-03T10:00:00+09:00",
        "projectId": "fresh-rejected-runway",
        "downloadStatus": "browser-generation-observed-native-mp4-import-missing",
        "generatedScenes": [
            {
                "sceneId": "scene-02",
                "expectedFileName": "scene-02.grok.mp4",
                "postUrl": "https://grok.com/imagine/post/scene02retry",
                "shareUrl": "https://grok.com/imagine/post/scene02retry?source=post-page&platform=web",
                "observedAt": "2026-06-03T10:00:00+09:00",
                "video": {
                    "width": 720,
                    "height": 1280,
                    "durationSeconds": 6.04,
                    "sourceHost": "assets.grok.com",
                },
                "importedNativeMp4": False,
            },
        ],
    }), encoding="utf-8")
    qa_dir = tmp_path / "storage" / "qa" / "fresh-rejected-runway" / "free-pexels-replacement-research"
    downloads_dir = qa_dir / "downloads"
    downloads_dir.mkdir(parents=True)
    (downloads_dir / "scene-02-pexels-rewrite-fallback.mp4").write_bytes(b"selected stock fallback")
    (qa_dir / "replacement-review-20260603.json").write_text(json.dumps({
        "schema": "video-studio.free-pexels-replacement-review.v1",
        "projectId": "fresh-rejected-runway",
        "status": "source-triage-only",
        "uploadReady": False,
        "directPexelsUrlOnly": True,
        "doesNotSatisfy": ["fresh-source-proof", "final-mp4", "publish-packet"],
        "candidates": [
            {
                "sceneId": "scene-02",
                "provider": "pexels-video",
                "sourceOrigin": "selected-stock",
                "candidateFileName": "scene-02-pexels-rewrite-fallback.mp4",
                "localPath": "storage/qa/fresh-rejected-runway/free-pexels-replacement-research/downloads/scene-02-pexels-rewrite-fallback.mp4",
                "pexelsId": "123",
                "creator": "Pexels Creator",
                "sourcePageUrl": "https://www.pexels.com/video/123/",
                "ffprobe": {"width": 1080, "height": 1920, "frameRate": "30/1", "hasAudio": False},
                "verdict": "conditional-fallback",
                "uploadReady": False,
                "requiresScriptRewrite": True,
                "reason": "Only fits after rewriting this beat to selected stock.",
            },
        ],
    }), encoding="utf-8")
    local_review_dir = tmp_path / "storage" / "qa" / "fresh-rejected-runway" / "local-candidate-review"
    local_review_dir.mkdir(parents=True)
    (local_review_dir / "source-recovery-review-20260603.json").write_text(json.dumps({
        "schema": "video-studio.source-recovery-review.v1",
        "projectId": "fresh-rejected-runway",
        "reviewedAt": "2026-06-03T04:30:00+09:00",
        "status": "all-local-candidates-reviewed-upload-blocked",
        "uploadReady": False,
        "policy": {
            "chromeDownloadUi": False,
            "grokDownloadSaveExport": False,
            "nativeDownloadPromptBlocks": True,
        },
        "doesNotSatisfy": ["fresh-source-proof", "final-mp4", "publish-packet"],
        "scenes": [
            {
                "sceneId": "scene-02",
                "verdict": "fail-upload-grade",
                "uploadReady": False,
                "reviewedAllLocalCandidates": True,
                "reviewedCandidateCount": 2,
                "selectedFileName": "scene-02-v2-clean-candidate.mp4",
                "contactSheetPaths": [
                    "storage/qa/fresh-rejected-runway/local-candidate-review/scene-02-v2-contact.jpg"
                ],
                "failCategories": ["weak-first-2s-hook", "ai-slop-or-stock-mismatch"],
                "operatorAction": "Rewrite the scene to fit selected stock or regenerate through direct import.",
            },
        ],
        "operatorAction": "Local candidates were reviewed and remain blocked for upload-grade source acceptance.",
    }), encoding="utf-8")
    expanded_dir = tmp_path / "storage" / "qa" / "fresh-rejected-runway" / "scene-02-pexels-expanded-search-20260603"
    expanded_downloads_dir = expanded_dir / "downloads"
    expanded_downloads_dir.mkdir(parents=True)
    (expanded_downloads_dir / "scene-02-pexels-stretch-rewrite.mp4").write_bytes(b"expanded rewrite candidate")
    (expanded_dir / "scene-02-pexels-stretch-rewrite-contact.jpg").write_bytes(b"expanded contact")
    (expanded_dir / "candidate-search-results.json").write_text(json.dumps({
        "schema": "video-studio.scene-pexels-expanded-search.v1",
        "projectId": "fresh-rejected-runway",
        "sceneId": "scene-02",
        "candidateIds": ["8926991"],
        "candidates": [
            {
                "sceneId": "scene-02",
                "provider": "pexels-video",
                "pexelsId": "8926991",
                "query": "office worker neck stretch laptop",
                "creator": "Pexels Rewrite Creator",
                "sourcePageUrl": "https://www.pexels.com/video/8926991/",
                "downloadUrl": "https://videos.pexels.com/video-files/8926991/8926991-hd_1080_1920_30fps.mp4",
                "localPath": "storage/qa/fresh-rejected-runway/scene-02-pexels-expanded-search-20260603/downloads/scene-02-pexels-stretch-rewrite.mp4",
                "contactSheetPath": "storage/qa/fresh-rejected-runway/scene-02-pexels-expanded-search-20260603/scene-02-pexels-stretch-rewrite-contact.jpg",
            },
        ],
    }), encoding="utf-8")
    (expanded_dir / "expanded-search-review-20260603.json").write_text(json.dumps({
        "schema": "video-studio.scene-pexels-expanded-search-review.v1",
        "projectId": "fresh-rejected-runway",
        "sceneId": "scene-02",
        "status": "source-triage-only",
        "uploadReady": False,
        "reviewedCandidateCount": 1,
        "doesNotSatisfy": ["fresh-source-proof", "current-script-stock-fit-pass"],
        "candidates": [
            {
                "sceneId": "scene-02",
                "provider": "pexels-video",
                "pexelsId": "8926991",
                "query": "office worker neck stretch laptop",
                "creator": "Pexels Rewrite Creator",
                "sourcePageUrl": "https://www.pexels.com/video/8926991/",
                "downloadUrl": "https://videos.pexels.com/video-files/8926991/8926991-hd_1080_1920_30fps.mp4",
                "localPath": "storage/qa/fresh-rejected-runway/scene-02-pexels-expanded-search-20260603/downloads/scene-02-pexels-stretch-rewrite.mp4",
                "contactSheetPath": "storage/qa/fresh-rejected-runway/scene-02-pexels-expanded-search-20260603/scene-02-pexels-stretch-rewrite-contact.jpg",
                "verdict": "rewrite-candidate-not-current-script-pass",
                "uploadReady": False,
                "requiresScriptRewrite": True,
                "reason": "Useful only after rewriting this scene around visible stretch motion.",
            },
        ],
        "operatorAction": "Use expanded Pexels candidates only as rewrite source triage.",
    }), encoding="utf-8")

    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "top-tier"
    packet_dir.mkdir(parents=True)
    (packet_dir / "top.mp4").write_bytes(b"not a real mp4 but ffprobe is mocked")
    _write_publish_packet_artifact(packet_dir, "top-tier", final_mp4_name="top.mp4")
    (packet_dir / "quality-audit.json").write_text(json.dumps({
        "summary": {
            "readyForUpload": True,
            "channelReady": True,
            "grokOrLocalHeroReady": True,
            "originalHeroReady": True,
            "captionLayoutReady": True,
            "topTierEvidenceReady": True,
            "benchmarkGap": "none",
        },
        "uploadReview": {"status": "ready"},
        "channelReadiness": {"status": "channel-ready"},
        "topTierReadiness": {"status": "top-tier-ready"},
        "checks": _current_quality_checks(),
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    latest = payload["sourcePipelineStatus"]["grok"]["latestHandoff"]
    assert latest["status"] == "needs-review"
    assert latest["importedScenes"] == 2
    assert latest["acceptedScenes"] == 1
    assert latest["rejectedScenes"] == 1
    assert latest["rejectedSceneIds"] == ["scene-02"]
    assert latest["scenes"][1]["review"]["status"] == "rejected"
    assert latest["scenes"][1]["review"]["visualQualityVerdict"] == "needs-retry"
    assert "weak-first-2s-hook" in latest["liveFailCategories"]
    assert "weak-thumbnail-or-first-frame" in latest["liveFailCategories"]
    assert "ai-slop-or-stock-mismatch" in latest["liveFailCategories"]
    assert "caption-safe-zone-risk" in latest["liveFailCategories"]
    assert "source-provenance-missing" in latest["liveFailCategories"]
    assert latest["replacementBacklog"][0]["sceneId"] == "scene-02"
    assert "Regenerate scene-02" in latest["replacementBacklog"][0]["nextRetryPrompt"]
    assert latest["replacementBacklog"][0]["localCandidateCount"] == 2
    assert latest["replacementBacklog"][0]["readyLocalCandidateCount"] == 2
    assert latest["replacementBacklog"][0]["unreviewedLocalCandidateCount"] == 1
    assert latest["replacementBacklog"][0]["unreviewedLocalCandidates"] == ["scene-02-v2-clean-candidate.mp4"]
    assert "Review existing local replacement candidate" in latest["replacementBacklog"][0]["operatorAction"]
    assert latest["scenes"][1]["candidatePool"]["totalCandidates"] == 2
    assert latest["scenes"][1]["candidatePool"]["unreviewedReplacementCandidates"] == ["scene-02-v2-clean-candidate.mp4"]
    assert "operator-owned manual download/import" in latest["replacementBacklog"][0]["operatorAction"]
    assert "rejected 1 scene" in latest["operatorDecision"]["detail"]
    assert "Replace rejected scenes" in latest["operatorDecision"]["nextAction"]
    runway_items = {item["key"]: item for item in payload["goalReadiness"]["operatingRunwayChecklist"]}
    fresh_source_item = runway_items["fresh-source-import-review"]
    assert "Rejected 1 scene(s): scene-02" in fresh_source_item["detail"]
    assert "weak-first-2s-hook" in fresh_source_item["detail"]
    assert "Source recovery lanes:" in fresh_source_item["detail"]
    assert "selected-stock rewrite 1" in fresh_source_item["detail"]
    assert "expanded Pexels 1" in fresh_source_item["detail"]
    assert "Acceptance gate: missing" in fresh_source_item["detail"]
    assert "accepted 0/1" in fresh_source_item["detail"]
    assert "source-recovery-acceptance.json" in fresh_source_item["detail"]
    assert "Create source-recovery-acceptance.json" in fresh_source_item["nextAction"]
    recovery = payload["sourcePipelineStatus"]["sourceRecoveryPlan"]
    assert recovery["status"] == "needs-source-recovery"
    assert recovery["uploadReady"] is False
    assert recovery["directRenderAllowed"] is False
    assert recovery["blockedByNativeDownloadPrompt"] is True
    assert recovery["totalScenes"] == 1
    assert recovery["renderBlockerCount"] >= 6
    assert recovery["freshSourceProofBlockerCount"] == recovery["renderBlockerCount"]
    assert recovery["scenesBlockingRender"] == ["scene-02"]
    assert recovery["scenesBlockingFreshSourceProof"] == ["scene-02"]
    assert recovery["localReviewScenes"] == 0
    assert recovery["selectedStockRewriteAvailableScenes"] == 1
    assert recovery["regenerateDirectImportScenes"] == 0
    assert recovery["expandedPexelsSearchScenes"] == 1
    assert recovery["latestLocalReview"]["available"] is True
    assert recovery["latestLocalReview"]["structured"] is True
    assert recovery["latestLocalReview"]["status"] == "all-local-candidates-reviewed-upload-blocked"
    assert recovery["latestExpandedPexelsSearch"]["available"] is True
    assert recovery["latestExpandedPexelsSearch"]["status"] == "source-triage-only"
    assert recovery["latestExpandedPexelsSearch"]["candidateCount"] == 1
    assert recovery["latestExpandedPexelsSearch"]["rewriteCandidateCount"] == 1
    assert recovery["latestExpandedPexelsSearch"]["uploadReady"] is False
    assert recovery["reviewedLocalCandidateScenes"] == 1
    assert recovery["failedLocalCandidateScenes"] == 1
    recovery_scene = recovery["scenes"][0]
    assert recovery_scene["sceneId"] == "scene-02"
    assert recovery_scene["recommendedLane"] == "rewrite-selected-stock-fallback"
    assert recovery_scene["localReview"]["verdict"] == "fail-upload-grade"
    assert recovery_scene["selectedStockRewriteAvailable"] is True
    assert recovery_scene["pexelsVerdict"] == "conditional-fallback"
    assert recovery_scene["directRenderAllowed"] is False
    assert recovery_scene["blocksRender"] is True
    assert recovery_scene["blocksFreshSourceProof"] is True
    assert recovery_scene["renderBlockerCount"] == len(recovery_scene["renderBlockers"])
    assert recovery_scene["freshSourceProofBlockerCount"] == len(recovery_scene["freshSourceProofBlockers"])
    assert "AI slop or stock/AI clip mismatch failed source review" in recovery_scene["renderBlockers"]
    assert "source provenance missing" in recovery_scene["renderBlockers"]
    assert "selected-stock fallback requires script rewrite and phone-sized review before render" in recovery_scene["renderBlockers"]
    assert "expanded Pexels candidates are source triage only, not upload-ready" in recovery_scene["renderBlockers"]
    expanded = recovery_scene["expandedPexelsSearch"]
    assert expanded["status"] == "source-triage-only"
    assert expanded["candidateCount"] == 1
    assert expanded["rewriteCandidateCount"] == 1
    assert expanded["uploadReadyCandidates"] == 0
    assert expanded["candidates"][0]["pexelsId"] == "8926991"
    assert expanded["candidates"][0]["localFileExists"] is True
    assert expanded["candidates"][0]["contactSheetExists"] is True
    assert expanded["candidates"][0]["verdict"] == "rewrite-candidate-not-current-script-pass"
    assert recovery["directImportRunwayScenes"] == 1
    runway = recovery["scenes"][0]["directImportRunway"]
    assert runway["status"] == "post-direct-import-ready"
    assert runway["expectedFileName"] == "scene-02.grok.mp4"
    assert runway["observedPostUrl"] == "https://grok.com/imagine/post/scene02retry"
    assert runway["observedPostDownloadScriptUrl"].endswith(
        "/api/grok-handoff/fresh-rejected-runway/observed-post-download.js?operatorApproved=true&sceneId=scene-02"
    )
    assert runway["proofMonitorUrl"].endswith("/api/grok-handoff/fresh-rejected-runway/direct-import-proof?sceneId=scene-02")
    assert runway["uploadEndpoint"].endswith("/api/grok-handoff/fresh-rejected-runway/upload-mp4")
    assert runway["prompt"]["source"] == "replacement-backlog"
    assert "Regenerate scene-02" in runway["prompt"]["promptText"]
    assert "Grok Download" in runway["forbiddenActions"]
    assert "operator-owned manual download/import" in runway["allowedRoutes"]
    assert "expanded Pexels candidates only as rewrite triage" in recovery["operatorAction"]
    assert "Do not use Chrome/Grok Download/Save/Export" in recovery["operatorAction"]
    acceptance_status = payload["sourcePipelineStatus"]["sourceRecoveryAcceptance"]
    assert acceptance_status["status"] == "missing"
    assert acceptance_status["acceptedSceneCount"] == 0
    assert acceptance_status["incompleteSceneCount"] == 1
    assert acceptance_status["blocksRender"] is True
    assert acceptance_status["requiredArtifactPath"].endswith("source-recovery-acceptance.json")
    assert acceptance_status["missingFieldsByScene"]["scene-02"] == ["source-recovery-acceptance.json"]
    expanded_research = payload["sourcePipelineStatus"]["pexels"]["expandedSearch"]
    assert expanded_research["available"] is True
    assert expanded_research["candidateCount"] == 1
    assert expanded_research["candidates"][0]["pexelsId"] == "8926991"

    intake_response = client.post(
        "/api/final-video-library/fresh-source-intake",
        json={"projectId": "fresh-rejected-runway"},
    )
    assert intake_response.status_code == 200
    intake_payload = intake_response.get_json()
    assert intake_payload["sourceRecoveryPlan"]["status"] == "needs-source-recovery"
    assert intake_payload["sourceRecoveryExecutionChecklist"][0]["sceneId"] == "scene-02"
    assert intake_payload["sourceRecoveryExecutionChecklist"][0]["recommendedLane"] == "rewrite-selected-stock-fallback"
    intake = json.loads((handoff_dir / "fresh-source-intake.template.json").read_text(encoding="utf-8"))
    assert intake["counts"]["rejectedScenes"] == 1
    assert intake["counts"]["sourceRecoveryScenes"] == 1
    assert intake["counts"]["sourceRecoverySelectedStockRewriteScenes"] == 1
    assert intake["counts"]["sourceRecoveryDirectImportRunwayScenes"] == 1
    assert intake["sourceRecoveryPlan"]["status"] == "needs-source-recovery"
    assert intake["sourceRecoveryPlan"]["directRenderAllowed"] is False
    assert intake["sourceRecoveryPlan"]["scenes"][0]["sceneId"] == "scene-02"
    assert intake["sourceRecoveryPlan"]["scenes"][0]["recommendedLane"] == "rewrite-selected-stock-fallback"
    assert intake["sourceRecoveryPlan"]["renderBlockerCount"] == recovery["renderBlockerCount"]
    assert intake["sourceRecoveryPlan"]["scenes"][0]["blocksRender"] is True
    assert "source provenance missing" in intake["sourceRecoveryPlan"]["scenes"][0]["renderBlockers"]
    recovery_step = intake["sourceRecoveryExecutionChecklist"][0]
    assert recovery_step["sceneId"] == "scene-02"
    assert recovery_step["blocksRender"] is True
    assert recovery_step["blocksFreshSourceProof"] is True
    assert recovery_step["recommendedLane"] == "rewrite-selected-stock-fallback"
    assert "Rewrite the scene beat" in recovery_step["nextRequiredAction"]
    assert "Visible motion and viewer hook" in recovery_step["acceptanceCriteria"][1]
    assert recovery_step["recoveryInputs"]["selectedStockCandidateFileName"] == "scene-02-pexels-rewrite-fallback.mp4"
    assert recovery_step["recoveryInputs"]["expandedPexelsRewriteCandidates"] == 1
    assert recovery_step["recoveryInputs"]["directImportStatus"] == "post-direct-import-ready"
    assert recovery_step["recoveryInputs"]["observedPostUrl"] == "https://grok.com/imagine/post/scene02retry"
    assert "Grok Download" in recovery_step["recoveryInputs"]["forbiddenActions"]
    assert "not proof" in intake["sourceRecoveryBoundary"]
    assert intake["rejectedScenes"] == ["scene-02"]
    assert intake["replacementBacklog"][0]["sceneId"] == "scene-02"
    assert intake["replacementBacklog"][0]["unreviewedLocalCandidates"] == ["scene-02-v2-clean-candidate.mp4"]
    assert intake["requiredScenes"][1]["candidatePool"]["unreviewedReplacementCandidates"] == ["scene-02-v2-clean-candidate.mp4"]
    assert "weak-first-2s-hook" in intake["liveFailCategories"]
    assert "Rejected imported Grok MP4" in intake["requiredScenes"][1]["operatorAction"]
    assert "do not press Grok Download/Save/Export or any Chrome native download prompt from Codex automation" in intake["requiredScenes"][1]["operatorAction"]
    assert "sourceRecoveryExecutionChecklist" in intake["operatorChecklist"][3]
    assert intake["goalComplete"] is False

    acceptance_response = client.post(
        "/api/final-video-library/source-recovery-acceptance",
        json={"projectId": "fresh-rejected-runway"},
    )
    assert acceptance_response.status_code == 200
    acceptance_payload = acceptance_response.get_json()
    assert acceptance_payload["status"] == "written-not-proof"
    assert acceptance_payload["templateOnly"] is True
    assert acceptance_payload["proofArtifactCreated"] is False
    assert acceptance_payload["freshSourceProofCreated"] is False
    assert acceptance_payload["goalComplete"] is False
    assert acceptance_payload["directRenderAllowed"] is False
    assert acceptance_payload["uploadReady"] is False
    assert acceptance_payload["sourceRecoveryStatus"] == "needs-source-recovery"
    assert acceptance_payload["sourceRecoveryScenes"] == 1
    assert acceptance_payload["renderBlockerCount"] == recovery["renderBlockerCount"]
    assert acceptance_payload["scenesBlockingRender"] == ["scene-02"]
    assert acceptance_payload["sourceRecoveryExecutionChecklist"][0]["recommendedLane"] == "rewrite-selected-stock-fallback"
    assert acceptance_payload["acceptanceScenes"][0]["sceneId"] == "scene-02"
    assert acceptance_payload["acceptanceScenes"][0]["acceptanceStatus"] == "operator-review-required"
    assert acceptance_payload["acceptanceScenes"][0]["recommendedLane"] == "rewrite-selected-stock-fallback"
    assert acceptance_payload["acceptanceScenes"][0]["blocksRender"] is True
    assert acceptance_payload["acceptanceScenes"][0]["blocksFreshSourceProof"] is True
    assert "acceptedReplacementFileName" in acceptance_payload["acceptanceScenes"][0]["requiredAcceptanceFields"]
    assert "acceptedReplacementSha256" in acceptance_payload["acceptanceScenes"][0]["requiredAcceptanceFields"]
    assert "fresh-source-proof.json" in acceptance_payload["acceptanceScenes"][0]["doesNotSatisfy"]
    assert "fresh-source-proof.json" in acceptance_payload["doesNotSatisfy"]
    assert "not source proof" in acceptance_payload["sourceRecoveryBoundary"]
    acceptance_gate = acceptance_payload["sourceRecoveryAcceptanceStatus"]
    assert acceptance_gate["status"] == "template-only-not-accepted"
    assert acceptance_gate["templateOnly"] is True
    assert acceptance_gate["acceptedSceneCount"] == 0
    assert acceptance_gate["incompleteSceneCount"] == 1
    assert acceptance_gate["blocksRender"] is True
    assert "acceptedReplacementSha256" in acceptance_gate["scenes"][0]["requiredAcceptanceFields"]
    assert "acceptedReplacementSha256" in acceptance_gate["missingFieldsByScene"]["scene-02"]
    acceptance = json.loads((handoff_dir / "source-recovery-acceptance.template.json").read_text(encoding="utf-8"))
    assert acceptance["schema"] == "video-studio.source-recovery-acceptance.v1"
    assert acceptance["sourceRecoveryScenes"] == 1
    assert acceptance["acceptanceScenes"][0]["operatorDecisionTemplate"]["freshSourceProofReady"] is False
    assert acceptance["acceptanceScenes"][0]["recoveryInputs"]["selectedStockCandidateFileName"] == "scene-02-pexels-rewrite-fallback.mp4"
    assert acceptance["acceptanceScenes"][0]["directImportRunway"]["status"] == "post-direct-import-ready"
    assert acceptance["goalComplete"] is False

    blocked_rerender_plan = client.post(
        "/api/final-video-library/source-recovery-rerender-plan",
        json={"projectId": "fresh-rejected-runway"},
    )
    assert blocked_rerender_plan.status_code == 200
    blocked_rerender_payload = blocked_rerender_plan.get_json()
    assert blocked_rerender_payload["ok"] is False
    assert blocked_rerender_payload["status"] == "blocked-by-source-recovery-acceptance"
    assert blocked_rerender_payload["blockedBySourceRecoveryAcceptance"] is True
    assert blocked_rerender_payload["rerenderInputReady"] is False
    assert blocked_rerender_payload["proofArtifactCreated"] is False
    assert blocked_rerender_payload["freshSourceProofCreated"] is False
    assert blocked_rerender_payload["goalComplete"] is False
    assert blocked_rerender_payload["sourceRecoveryAcceptanceStatus"]["status"] == "template-only-not-accepted"
    assert blocked_rerender_payload["sourceRecoveryAcceptanceBlockerCount"] == 1
    assert "source-recovery-acceptance.json" in blocked_rerender_payload["requiredArtifactPath"]
    assert not (handoff_dir / "source-recovery-rerender-plan.template.json").exists()

    invalid_replacement = incoming_dir / "scene-02-invalid-source.txt"
    invalid_replacement.write_bytes(b"not a video source")
    invalid_packet = dict(acceptance)
    invalid_packet["templateOnly"] = False
    invalid_packet["doNotSubmitAsProof"] = True
    invalid_packet["acceptanceScenes"][0]["operatorDecision"] = {
        "accepted": True,
        "reviewStatus": "accepted",
        "acceptedReplacementFileName": "wrong-name.mp4",
        "acceptedReplacementPath": str(invalid_replacement),
        "acceptedReplacementSha256": _sha256_file(invalid_replacement),
        "reviewerId": "operator-test",
        "acceptedAt": "2026-06-03T12:00:00",
        "firstTwoSecondHookPass": True,
        "motionDensityPass": True,
        "aiSlopVisualFitPass": True,
        "stockAiClipFitPass": True,
        "captionSafeZonePass": True,
        "sourceProvenanceConfirmed": True,
        "phoneFirstFrameReviewPass": True,
        "continuityReviewPass": True,
        "reviewNotes": "Invalid replacement source should not clear rerender.",
        "rerenderRequired": True,
        "freshSourceProofReady": False,
    }
    (handoff_dir / "source-recovery-acceptance.json").write_text(
        json.dumps(invalid_packet, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    invalid_audit = client.get("/api/final-video-library/audit?limit=10").get_json()
    invalid_gate = invalid_audit["sourcePipelineStatus"]["sourceRecoveryAcceptance"]
    invalid_scene = invalid_gate["scenes"][0]
    assert invalid_gate["status"] == "operator-acceptance-incomplete"
    assert invalid_gate["acceptedSceneCount"] == 0
    assert invalid_gate["incompleteSceneCount"] == 1
    assert invalid_gate["blocksRender"] is True
    assert invalid_scene["acceptedReplacementPathCheck"]["ok"] is False
    assert invalid_scene["acceptedReplacementPathCheck"]["fileNameCheck"]["ok"] is False
    assert invalid_scene["acceptedReplacementPathCheck"]["videoCheck"]["ok"] is False
    assert invalid_scene["acceptedAtCheck"]["ok"] is False
    assert invalid_scene["acceptedAtCheck"]["timezoneProvided"] is False
    assert "acceptedReplacementFileName must match path basename scene-02-invalid-source.txt" in invalid_scene["missingFields"]
    assert "accepted replacement must be an MP4 file" in invalid_scene["missingFields"]
    assert "acceptedAt must include timezone offset" in invalid_scene["missingFields"]
    invalid_rerender_plan = client.post(
        "/api/final-video-library/source-recovery-rerender-plan",
        json={"projectId": "fresh-rejected-runway"},
    ).get_json()
    assert invalid_rerender_plan["ok"] is False
    assert invalid_rerender_plan["status"] == "blocked-by-source-recovery-acceptance"

    accepted_replacement = incoming_dir / "scene-02-v2-clean-candidate.mp4"
    accepted_packet = dict(acceptance)
    accepted_packet["templateOnly"] = False
    accepted_packet["doNotSubmitAsProof"] = True
    accepted_packet["acceptanceScenes"][0]["operatorDecision"] = {
        "accepted": True,
        "reviewStatus": "accepted",
        "acceptedReplacementFileName": accepted_replacement.name,
        "acceptedReplacementPath": str(accepted_replacement),
        "acceptedReplacementSha256": _sha256_file(accepted_replacement),
        "reviewerId": "operator-test",
        "acceptedAt": "2026-06-03T12:00:00+09:00",
        "firstTwoSecondHookPass": True,
        "motionDensityPass": True,
        "aiSlopVisualFitPass": True,
        "stockAiClipFitPass": True,
        "captionSafeZonePass": True,
        "sourceProvenanceConfirmed": True,
        "phoneFirstFrameReviewPass": True,
        "continuityReviewPass": True,
        "reviewNotes": "Accepted replacement source for rerender only.",
        "rerenderRequired": True,
        "freshSourceProofReady": False,
    }
    (handoff_dir / "source-recovery-acceptance.json").write_text(
        json.dumps(accepted_packet, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    acceptance_sha256 = _sha256_file(handoff_dir / "source-recovery-acceptance.json")
    accepted_audit = client.get("/api/final-video-library/audit?limit=10").get_json()
    accepted_gate = accepted_audit["sourcePipelineStatus"]["sourceRecoveryAcceptance"]
    assert accepted_gate["status"] == "accepted-replacements-ready-for-rerender"
    assert accepted_gate["templateOnly"] is False
    assert accepted_gate["acceptedSceneCount"] == 1
    assert accepted_gate["incompleteSceneCount"] == 0
    assert accepted_gate["blocksRender"] is False
    assert accepted_gate["blocksFreshSourceProof"] is True
    assert accepted_gate["proofArtifactCreated"] is False
    assert accepted_gate["freshSourceProofCreated"] is False
    assert accepted_gate["goalComplete"] is False
    assert accepted_gate["scenes"][0]["acceptedReplacementPathCheck"]["ok"] is True
    assert accepted_gate["scenes"][0]["acceptedReplacementPathCheck"]["fileNameCheck"]["ok"] is True
    assert accepted_gate["scenes"][0]["acceptedReplacementPathCheck"]["videoCheck"]["ok"] is True
    assert accepted_gate["scenes"][0]["acceptedAtCheck"]["ok"] is True
    assert accepted_gate["scenes"][0]["acceptedAtCheck"]["timezoneProvided"] is True
    accepted_runway_items = {item["key"]: item for item in accepted_audit["goalReadiness"]["operatingRunwayChecklist"]}
    accepted_fresh_source_item = accepted_runway_items["fresh-source-import-review"]
    assert "Acceptance gate: accepted-replacements-ready-for-rerender" in accepted_fresh_source_item["detail"]
    assert "accepted 1/1" in accepted_fresh_source_item["detail"]
    assert "Rerender with the accepted replacement sources" in accepted_fresh_source_item["nextAction"]
    assert accepted_audit["goalReadiness"]["goalComplete"] is False

    rerender_plan_response = client.post(
        "/api/final-video-library/source-recovery-rerender-plan",
        json={"projectId": "fresh-rejected-runway"},
    )
    assert rerender_plan_response.status_code == 200
    rerender_plan_payload = rerender_plan_response.get_json()
    assert rerender_plan_payload["ok"] is True
    assert rerender_plan_payload["status"] == "written-not-proof"
    assert rerender_plan_payload["templateOnly"] is True
    assert rerender_plan_payload["blockedBySourceRecoveryAcceptance"] is False
    assert rerender_plan_payload["sourceRecoveryAcceptanceCleared"] is True
    assert rerender_plan_payload["rerenderInputReady"] is True
    assert rerender_plan_payload["renderExecuted"] is False
    assert rerender_plan_payload["finalMp4Created"] is False
    assert rerender_plan_payload["proofArtifactCreated"] is False
    assert rerender_plan_payload["freshSourceProofCreated"] is False
    assert rerender_plan_payload["phoneReviewProofCreated"] is False
    assert rerender_plan_payload["platformAnalyticsProofCreated"] is False
    assert rerender_plan_payload["uploadReady"] is False
    assert rerender_plan_payload["goalComplete"] is False
    assert rerender_plan_payload["acceptedReplacementCount"] == 1
    assert rerender_plan_payload["sceneReplacements"][0]["sceneId"] == "scene-02"
    assert rerender_plan_payload["sceneReplacements"][0]["acceptedReplacementPath"] == str(accepted_replacement)
    assert rerender_plan_payload["sceneReplacements"][0]["acceptedReplacementSha256"] == _sha256_file(accepted_replacement)
    assert rerender_plan_payload["sceneReplacements"][0]["renderInputOverride"]["sourceRecoveryAcceptanceSha256"] == acceptance_sha256
    assert "fresh-source-proof.json" in rerender_plan_payload["doesNotSatisfy"]
    assert "does not render" in rerender_plan_payload["goalBoundary"]
    rerender_plan = json.loads((handoff_dir / "source-recovery-rerender-plan.template.json").read_text(encoding="utf-8"))
    assert rerender_plan["schema"] == "video-studio.source-recovery-rerender-plan.v1"
    assert rerender_plan["sourceRecoveryAcceptanceSha256"] == acceptance_sha256
    assert rerender_plan["sceneReplacements"][0]["renderInputOverride"]["sourcePath"] == str(accepted_replacement)
    assert rerender_plan["renderPlan"]["freshSourceProofRequiredAfterRerender"] is True
    assert rerender_plan["goalComplete"] is False


def test_final_video_library_audit_surfaces_free_pexels_replacement_research_without_goal_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)

    project_id = "fresh-pexels-replacement-runway"
    handoff_dir = tmp_path / "storage" / "grok-handoffs" / project_id
    incoming_dir = handoff_dir / "incoming"
    incoming_dir.mkdir(parents=True)
    (handoff_dir / "handoff.json").write_text(json.dumps({
        "projectId": project_id,
        "createdAt": "2026-05-31T23:30:00",
        "incomingDir": str(incoming_dir),
        "scenes": [
            {
                "sceneId": "scene-01",
                "expectedFileName": "scene-01.grok.mp4",
                "promptQuality": {"status": "ready"},
            },
            {
                "sceneId": "scene-03",
                "expectedFileName": "scene-03.grok.mp4",
                "promptQuality": {"status": "ready"},
            },
        ],
    }), encoding="utf-8")

    qa_dir = tmp_path / "storage" / "qa" / project_id / "free-pexels-replacement-research"
    downloads_dir = qa_dir / "downloads"
    downloads_dir.mkdir(parents=True)
    reframe_dir = qa_dir / "reframe-smoke-20260603"
    reframe_dir.mkdir(parents=True)
    (downloads_dir / "scene-01-pexels-phone-down.mp4").write_bytes(b"candidate source")
    (downloads_dir / "scene-03-pexels-neck-pain.mp4").write_bytes(b"candidate source")
    (reframe_dir / "scene-03-fullframe-1080x1920-30fps-6s.mp4").write_bytes(b"reframe smoke")
    (qa_dir / "scene-03-reframe-smoke-20260603.json").write_text(json.dumps({
        "schema": "video-studio.pexels-reframe-smoke.v1",
        "sceneId": "scene-03",
        "decision": {"uploadReady": False, "status": "conditional-fallback"},
    }), encoding="utf-8")
    (qa_dir / "scene-01-contact.jpg").write_bytes(b"contact")
    (qa_dir / "scene-03-contact.jpg").write_bytes(b"contact")
    (qa_dir / "replacement-review-20260603.json").write_text(json.dumps({
        "schema": "video-studio.free-pexels-replacement-review.v1",
        "projectId": project_id,
        "status": "source-triage-only",
        "uploadReady": False,
        "directPexelsUrlOnly": True,
        "chromeDownloadUi": False,
        "grokDownloadSaveExport": False,
        "notFreshGrokProof": True,
        "notPublishPacket": True,
        "notUploadReadyEvidence": True,
        "doesNotSatisfy": ["fresh-source-proof", "final-mp4", "publish-packet"],
        "candidates": [
            {
                "sceneId": "scene-01",
                "provider": "pexels-video",
                "sourceOrigin": "selected-stock",
                "candidateFileName": "scene-01-pexels-phone-down.mp4",
                "localPath": f"storage/qa/{project_id}/free-pexels-replacement-research/downloads/scene-01-pexels-phone-down.mp4",
                "contactSheetPath": f"storage/qa/{project_id}/free-pexels-replacement-research/scene-01-contact.jpg",
                "pexelsId": "9063076",
                "creator": "Pexels Creator",
                "sourcePageUrl": "https://www.pexels.com/video/9063076/",
                "ffprobe": {"width": 2160, "height": 4096, "frameRate": "25/1", "hasAudio": False},
                "verdict": "conditional-fallback",
                "uploadReady": False,
                "requiresScriptRewrite": True,
                "requiresPhoneFirstFrameReview": True,
                "reason": "Staged stock opener needs rewrite.",
            },
            {
                "sceneId": "scene-03",
                "provider": "pexels-video",
                "sourceOrigin": "selected-stock",
                "candidateFileName": "scene-03-pexels-neck-pain.mp4",
                "localPath": f"storage/qa/{project_id}/free-pexels-replacement-research/downloads/scene-03-pexels-neck-pain.mp4",
                "contactSheetPath": f"storage/qa/{project_id}/free-pexels-replacement-research/scene-03-contact.jpg",
                "pexelsId": "27430390",
                "creator": "Pexels Creator",
                "sourcePageUrl": "https://www.pexels.com/video/27430390/",
                "ffprobe": {"width": 1080, "height": 1920, "frameRate": "30000/1001", "hasAudio": False},
                "verdict": "fail-direct-use",
                "uploadReady": False,
                "requiresCropReframeTest": True,
                "reframeSmokePath": f"storage/qa/{project_id}/free-pexels-replacement-research/reframe-smoke-20260603/scene-03-fullframe-1080x1920-30fps-6s.mp4",
                "reframeSmokeReviewPath": f"storage/qa/{project_id}/free-pexels-replacement-research/scene-03-reframe-smoke-20260603.json",
                "reframeSmokeVerdict": "conditional-fallback-after-rewrite",
                "previousLowerEmptyAreaConcernCorrected": True,
                "reason": "Direct use fails the stock-fit review.",
            },
        ],
        "operatorAction": "Treat this as source triage only, not upload-ready evidence.",
    }), encoding="utf-8")

    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "top-tier"
    packet_dir.mkdir(parents=True)
    (packet_dir / "top.mp4").write_bytes(b"not a real mp4 but ffprobe is mocked")
    _write_publish_packet_artifact(packet_dir, "top-tier", final_mp4_name="top.mp4")
    (packet_dir / "quality-audit.json").write_text(json.dumps({
        "summary": {
            "readyForUpload": True,
            "channelReady": True,
            "grokOrLocalHeroReady": True,
            "originalHeroReady": True,
            "captionLayoutReady": True,
            "topTierEvidenceReady": True,
            "benchmarkGap": "none",
        },
        "uploadReview": {"status": "ready"},
        "channelReadiness": {"status": "channel-ready"},
        "topTierReadiness": {"status": "top-tier-ready"},
        "checks": _current_quality_checks(),
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    research = payload["sourcePipelineStatus"]["pexels"]["replacementResearch"]
    assert research["available"] is True
    assert research["projectId"] == project_id
    assert research["status"] == "source-triage-only"
    assert research["directPexelsUrlOnly"] is True
    assert research["chromeDownloadUi"] is False
    assert research["grokDownloadSaveExport"] is False
    assert research["notFreshGrokProof"] is True
    assert research["notUploadReadyEvidence"] is True
    assert research["uploadReady"] is False
    assert research["totalCandidates"] == 2
    assert research["conditionalFallbackCandidates"] == 1
    assert research["failedDirectUseCandidates"] == 1
    assert research["uploadReadyCandidates"] == 0
    assert research["videoOnlyNoAudioCandidates"] == 2
    assert research["scenes"] == ["scene-01", "scene-03"]
    assert "fresh-source-proof" in research["doesNotSatisfy"]
    assert "final-mp4" in research["doesNotSatisfy"]
    assert research["candidates"][0]["localFileExists"] is True
    assert research["candidates"][0]["contactSheetExists"] is True
    assert research["candidates"][0]["verdict"] == "conditional-fallback"
    assert research["candidates"][1]["verdict"] == "fail-direct-use"
    assert research["candidates"][1]["reframeSmokeExists"] is True
    assert research["candidates"][1]["reframeSmokeReviewExists"] is True
    assert research["candidates"][1]["reframeSmokeVerdict"] == "conditional-fallback-after-rewrite"
    assert research["candidates"][1]["previousLowerEmptyAreaConcernCorrected"] is True
    assert payload["goalReadiness"]["goalComplete"] is False


def test_final_video_library_fresh_source_intake_writes_template_without_goal_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)

    downloads_dir = tmp_path / "Downloads"
    downloads_dir.mkdir()
    old_download = downloads_dir / "grok-video-old-retained.mp4"
    old_download.write_bytes(b"old retained source")
    old_epoch = 1780230000
    os.utime(old_download, (old_epoch, old_epoch))

    handoff_dir = tmp_path / "storage" / "grok-handoffs" / "fresh-intake-runway"
    incoming_dir = handoff_dir / "incoming"
    incoming_dir.mkdir(parents=True)
    (handoff_dir / "handoff.json").write_text(json.dumps({
        "projectId": "fresh-intake-runway",
        "createdAt": "2026-05-31T23:30:00",
        "defaultDownloadDir": str(downloads_dir),
        "incomingDir": str(incoming_dir),
        "scenes": [
            {
                "sceneId": "scene-01",
                "expectedFileName": "scene-01.grok.mp4",
                "promptQuality": {"status": "ready"},
            },
            {
                "sceneId": "scene-02",
                "expectedFileName": "scene-02.grok.mp4",
                "promptQuality": {"status": "ready"},
            },
        ],
    }), encoding="utf-8")

    response = client.post(
        "/api/final-video-library/fresh-source-intake",
        json={"projectId": "fresh-intake-runway"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["projectId"] == "fresh-intake-runway"
    assert payload["templateOnly"] is True
    assert payload["proofArtifactCreated"] is False
    assert payload["freshSourceProofCreated"] is False
    assert payload["goalComplete"] is False
    assert payload["missingScenes"] == ["scene-01", "scene-02"]
    assert payload["importPreflightSummary"] == payload["importPreflight"]
    assert payload["importPreflight"]["readyForReview"] is False
    assert payload["importPreflight"]["presentScenes"] == 0
    assert payload["importPreflight"]["readyScenes"] == 0
    assert payload["importPreflight"]["missingScenes"] == ["scene-01", "scene-02"]
    assert payload["importPreflight"]["needsImportScenes"] == ["scene-01", "scene-02"]
    assert payload["downloadFreshness"]["freshCandidateCount"] == 0
    assert payload["downloadFreshness"]["excludedOldCandidateCount"] == 1
    assert "operator intake worksheet only" in payload["goalBoundary"]

    packet_path = handoff_dir / "fresh-source-intake.template.json"
    assert payload["path"] == str(packet_path)
    assert packet_path.exists()
    intake = json.loads(packet_path.read_text(encoding="utf-8"))
    assert intake["templateOnly"] is True
    assert intake["doNotSubmitAsProof"] is True
    assert intake["freshSourceProofCreated"] is False
    assert intake["goalComplete"] is False
    assert intake["sourcePolicy"]["paidAiApiAllowed"] is False
    assert "static image slideshow" in intake["sourcePolicy"]["disallowedFlow"]
    assert "Codex automation pressing Grok Download/Save/Export" in intake["sourcePolicy"]["disallowedFlow"]
    assert "Chrome native download prompts" in intake["sourcePolicy"]["disallowedFlow"]
    assert "Downloads watcher fallback" in intake["sourcePolicy"]["disallowedFlow"]
    assert intake["counts"]["oldDownloadsExcluded"] == 1
    assert intake["counts"]["preflightMissingScenes"] == 2
    assert intake["importPreflightSummary"] == intake["importPreflight"]
    assert intake["importPreflight"]["readyForReview"] is False
    assert [item["sceneId"] for item in intake["requiredScenes"]] == ["scene-01", "scene-02"]
    assert all("Generate or acquire a native Grok MP4" in item["operatorAction"] for item in intake["requiredScenes"])
    assert all("operator-owned manual download/import or explicit batch upload from an already-saved local MP4" in item["operatorAction"] for item in intake["requiredScenes"])
    assert all("without using Codex automation to press Grok Download/Save/Export or any Chrome native download prompt" in item["operatorAction"] for item in intake["requiredScenes"])
    assert any("broad live-channel" in item for item in intake["doesNotSatisfy"])

    audit_response = client.get("/api/final-video-library/audit?limit=10")
    assert audit_response.status_code == 200
    audit_payload = audit_response.get_json()
    assert audit_payload["goalReadiness"]["goalComplete"] is False


def test_latest_grok_handoff_operator_decision_keeps_accepted_source_in_rerender_lane():
    decision = routes_media._latest_grok_handoff_operator_decision(
        "accepted",
        total_scenes=2,
        imported_count=2,
        accepted_count=2,
        missing_scene_ids=[],
        download_freshness={"freshCandidateCount": 0},
    )

    assert decision["status"] == "rerender"
    assert decision["label"] == "재렌더 필요"
    assert "final MP4 and publish packet" in decision["detail"]


def _write_ready_final_video_packet(packet_dir: Path, project_id: str, production_summary: dict | None = None):
    packet_dir.mkdir(parents=True)
    (packet_dir / f"{project_id}.mp4").write_bytes(b"not a real mp4 but ffprobe is mocked")
    _write_publish_packet_artifact(packet_dir, project_id)
    ready_summary = {
        "readyForUpload": True,
        "channelReady": True,
        "grokOrLocalHeroReady": True,
        "originalHeroReady": True,
        "narrationReady": True,
        "captionLayoutReady": True,
        "assetDiversityReady": True,
        "freeAssetProvenanceReady": True,
        "bgmRotationReady": True,
        "audioMixReviewReady": True,
        "platformComparisonReady": True,
        "topTierEvidenceReady": True,
        "benchmarkGap": "none",
    }
    (packet_dir / "quality-audit.json").write_text(json.dumps({
        "summary": ready_summary,
        "uploadReview": {"status": "ready"},
        "channelReadiness": {"status": "channel-ready"},
        "publishReadiness": {"status": "ready"},
    }), encoding="utf-8")
    (packet_dir / "render-quality-report.json").write_text(json.dumps({
        "projectId": project_id,
        "summary": {**ready_summary, "topTierReady": True, "uploadReady": True},
        "publishReadiness": {"status": "ready"},
        "channelReadiness": {
            "status": "channel-ready",
            "summary": {
                "heroAiOrLocalReady": True,
                "heroOriginalClipReady": True,
            },
        },
        "uploadReview": {
            "status": "ready",
            "summary": {
                "narrationReady": True,
                "captionLayoutReady": True,
                "assetDiversityReady": True,
                "freeAssetProvenanceReady": True,
                "bgmRotationReady": True,
                "audioMixReviewReady": True,
                "platformComparisonReady": True,
            },
        },
        "topTierReadiness": {
            "status": "top-tier-ready",
            "summary": {
                "topTierEvidenceReady": True,
                "benchmarkGap": "none",
            },
        },
        "productionReview": {
            "summary": {
                "stockOnly": False,
                "firstSceneHookReady": True,
                "missingRationaleScenes": [],
                "missingContinuityScenes": [],
                "missingNarrationScenes": [],
                "thinNarrationScenes": [],
                "missingCaptionLayoutReviewScenes": [],
                "repeatedVisualAssetScenes": [],
                "missingFreeAssetProvenanceScenes": [],
                "missingFreeAudioProvenanceAssets": [],
                **(production_summary or {}),
            },
        },
        "checks": _current_quality_checks(
            channelReadinessGate={"status": "pass", "detail": "status=channel-ready"},
            uploadReviewGate={"status": "pass", "detail": "status=ready"},
            topTierReadinessGate={"status": "pass", "detail": "status=top-tier-ready"},
        ),
    }), encoding="utf-8")


def _longform_minimum_release_packet() -> dict:
    chapters = []
    for index in range(1, 7):
        chapter_id = f"chapter-{index:02d}"
        chapters.append({
            "chapterId": chapter_id,
            "title": f"Chapter {index}",
            "claim": f"Claim {index}",
            "segments": [
                {"segmentId": f"{chapter_id}-seg-01"},
                {"segmentId": f"{chapter_id}-seg-02"},
                {"segmentId": f"{chapter_id}-seg-03"},
            ],
            "evidence": [{
                "evidenceId": f"evidence-{index:02d}",
                "sourceUrl": f"https://example.com/evidence-{index}",
                "rightsStatus": "operator-approved",
            }],
        })
    return {
        "formatProfile": "longform_10m",
        "durationSec": 610,
        "chapters": chapters,
        "storyPackageReview": {
            "firstTenSecondExpectationMet": True,
            "titleThumbnailExpectationMet": True,
            "payoffPromiseResolved": True,
        },
        "sourceReviewImport": {
            "chapterContinuityPassRatio": 0.92,
            "primarySubjectIdentityDrift": False,
            "primarySubjectScaleJump": False,
            "unexplainedCameraWorldJump": False,
            "unresolvedSourceDefects": [],
            "acceptedChapterCount": 6,
            "acceptedSources": [{
                "sourceId": "source-001",
                "provider": "grok-web-video",
                "rightsStatus": "licensed",
                "commercialUseAllowed": True,
            }],
        },
        "scriptTtsCaptionReview": {
            "status": "pass",
            "voicePlan": {"provider": "edge-tts", "voiceId": "ko-KR-SunHiNeural", "targetWpm": 140},
            "maxCaptionTtsDriftSec": 0.18,
            "noDuplicateCaptionTts": True,
            "captionExplainsMissingVisual": False,
            "safeZoneReviewed": True,
        },
        "editorialReleaseReview": {
            "directedEdit": True,
            "motivatedCutPassRatio": 0.9,
            "layoutSafeZoneReviewed": True,
            "noUnboundEffectCues": True,
            "noHudComparisonReviewed": True,
            "unresolvedEditorialIssues": [],
        },
        "audioReleaseReview": {
            "audioStreamExists": True,
            "narrationDuckingEnabled": True,
            "chapterAudioBedsCovered": True,
            "everyCueBoundToVisibleEvent": True,
            "maxPeakDb": -4.0,
            "meanDb": -20.0,
        },
        "fullWatchReview": {
            "completed": True,
            "durationSec": 610,
            "reviewerRole": "operator",
            "unresolvedCriticalIssues": 0,
            "unresolvedMajorIssues": 0,
            "defectDensityPerMinute": 0.2,
            "retentionDipMitigationsReviewed": True,
            "chapterIssueLog": [{"chapterId": f"chapter-{index:02d}", "issues": []} for index in range(1, 7)],
        },
    }


def _write_publish_packet_artifact(packet_dir: Path, project_id: str, final_mp4_name: str | None = None):
    final_mp4_name = final_mp4_name or f"{project_id}.mp4"
    first_frame = packet_dir / "review-frame-01.jpg"
    second_frame = packet_dir / "review-frame-02.jpg"
    contact_sheet = packet_dir / "contact-sheet.jpg"
    for path in [first_frame, second_frame, contact_sheet]:
        path.write_bytes(b"fake jpg bytes")
    (packet_dir / "publish-packet.json").write_text(json.dumps({
        "projectId": project_id,
        "finalMp4": str(packet_dir / final_mp4_name),
        "thumbnailCandidates": {
            "firstFrame": str(first_frame),
            "reviewFrames": [str(first_frame), str(second_frame)],
            "contactSheet": str(contact_sheet),
        },
        "titleCandidates": ["Test upload title"],
        "description": "Short-form publish description.",
        "hashtags": ["#shorts"],
        "uploadChecklist": [{"key": "phoneWatch", "status": "pass"}],
        "shortcomings": ["Needs live platform learning after upload."],
        "nextImprovementActions": ["Compare first-frame retention on the next upload."],
    }), encoding="utf-8")


def _write_png_evidence(path: Path, width: int = 1080, height: int = 1920, min_bytes: int = 2048):
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            len(data).to_bytes(4, "big")
            + kind
            + data
            + zlib.crc32(kind + data).to_bytes(4, "big")
        )

    ihdr = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    payload = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")
    path.write_bytes(payload + (b"\0" * max(0, min_bytes - len(payload))))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _phone_review_evidence_digests(
    review_snapshot: Path,
    caption_frame: Path,
    thumbnail_frame: Path,
    audio_evidence: Path,
) -> dict:
    return {
        "reviewSnapshotSha256": _sha256_file(review_snapshot),
        "captionSafeZoneFrameSha256": _sha256_file(caption_frame),
        "thumbnailFirstFrameSha256": _sha256_file(thumbnail_frame),
        "audioMixEvidenceSha256": _sha256_file(audio_evidence),
    }


def _write_fresh_source_proof(packet_dir: Path, project_id: str, final_mp4_name: str | None = None, overrides: dict | None = None):
    final_mp4_name = final_mp4_name or f"{project_id}.mp4"
    handoff_manifest = packet_dir / "fresh-source-handoff.json"
    source_review = packet_dir / "fresh-source-review.json"
    render_manifest = packet_dir / "render-manifest.json"
    quality_audit = packet_dir / "quality-audit.json"
    publish_packet = packet_dir / "publish-packet.json"
    dashboard_smoke = packet_dir / "dashboard-smoke.json"
    for path, payload in [
        (handoff_manifest, {"projectId": "fresh-proof-handoff", "scenes": ["scene-01", "scene-02", "scene-03", "scene-04", "scene-05"]}),
        (source_review, {"status": "accepted", "acceptedSceneCount": 5, "rejectedSceneCount": 0}),
        (render_manifest, {"projectId": project_id, "outputPath": str(packet_dir / final_mp4_name)}),
        (dashboard_smoke, {
            "ok": True,
            "projectId": project_id,
            "surface": "final-library-dashboard",
            "browserRendered": True,
            "bridgeConnected": True,
            "finalLibraryPanelVisible": True,
            "preUploadReady": False,
            "visibleTexts": [
                "Final video library",
                project_id,
                "today upload decision: 수정 필요",
            ],
        }),
    ]:
        if not path.exists():
            path.write_text(json.dumps(payload), encoding="utf-8")
    payload = {
        "recordedAt": "2026-06-01T02:30:00+09:00",
        "sourceFlow": "operator-owned manual download/import or explicit already-saved MP4 batch upload",
        "topic": "different live-channel proof topic",
        "finalVideoPath": str(packet_dir / final_mp4_name),
        "finalVideoSha256": _sha256_file(packet_dir / final_mp4_name),
        "handoffProjectId": "fresh-proof-handoff",
        "renderedProjectId": project_id,
        "handoffManifestPath": str(handoff_manifest),
        "sourceReviewPath": str(source_review),
        "renderManifestPath": str(render_manifest),
        "qualityAuditPath": str(quality_audit),
        "publishPacketPath": str(publish_packet),
        "dashboardSmokePath": str(dashboard_smoke),
        "handoffManifestSha256": _sha256_file(handoff_manifest),
        "sourceReviewSha256": _sha256_file(source_review),
        "renderManifestSha256": _sha256_file(render_manifest),
        "qualityAuditSha256": _sha256_file(quality_audit),
        "publishPacketSha256": _sha256_file(publish_packet),
        "dashboardSmokeSha256": _sha256_file(dashboard_smoke),
        "importedSceneCount": 5,
        "acceptedSceneCount": 5,
        "differentTopic": True,
        "movingClipStitching": True,
        "sourceProvenanceReviewed": True,
        "qualityAuditPass": True,
        "publishPacketComplete": True,
        "dashboardSmokePass": True,
    }
    payload.update(overrides or {})
    (packet_dir / "fresh-source-proof.json").write_text(json.dumps(payload), encoding="utf-8")


def test_final_video_library_audit_accepts_bookmarklet_direct_import_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "bookmarklet-live-proof"
    packet_dir.mkdir(parents=True)
    (packet_dir / "bookmarklet.mp4").write_bytes(b"not a real mp4 but ffprobe is mocked")
    _write_publish_packet_artifact(packet_dir, "bookmarklet-live-proof", final_mp4_name="bookmarklet.mp4")
    ready_summary = {
        "readyForUpload": True,
        "channelReady": True,
        "grokOrLocalHeroReady": True,
        "originalHeroReady": True,
        "narrationReady": True,
        "captionLayoutReady": True,
        "assetDiversityReady": True,
        "freeAssetProvenanceReady": True,
        "bgmRotationReady": True,
        "audioMixReviewReady": True,
        "platformComparisonReady": True,
        "topTierEvidenceReady": True,
        "benchmarkGap": "none",
    }
    (packet_dir / "quality-audit.json").write_text(json.dumps({
        "summary": ready_summary,
        "uploadReview": {"status": "ready"},
        "channelReadiness": {"status": "channel-ready"},
        "publishReadiness": {"status": "ready"},
    }), encoding="utf-8")
    (packet_dir / "render-quality-report.json").write_text(json.dumps({
        "projectId": "bookmarklet-live-proof",
        "summary": {**ready_summary, "topTierReady": True, "uploadReady": True},
        "publishReadiness": {"status": "ready"},
        "channelReadiness": {
            "status": "channel-ready",
            "summary": {
                "heroAiOrLocalReady": True,
                "heroOriginalClipReady": True,
            },
        },
        "uploadReview": {
            "status": "ready",
            "summary": {
                "narrationReady": True,
                "captionLayoutReady": True,
                "assetDiversityReady": True,
                "freeAssetProvenanceReady": True,
                "bgmRotationReady": True,
                "audioMixReviewReady": True,
                "platformComparisonReady": True,
            },
        },
        "topTierReadiness": {
            "status": "top-tier-ready",
            "summary": {
                "topTierEvidenceReady": True,
                "benchmarkGap": "none",
            },
        },
        "productionReview": {
            "summary": {
                "stockOnly": False,
                "firstSceneHookReady": True,
                "missingRationaleScenes": [],
                "missingContinuityScenes": [],
                "missingNarrationScenes": [],
                "thinNarrationScenes": [],
                "missingCaptionLayoutReviewScenes": [],
                "repeatedVisualAssetScenes": [],
                "missingFreeAssetProvenanceScenes": [],
                "missingFreeAudioProvenanceAssets": [],
                "grokDirectImportEvidence": {
                    "sourceKind": "bookmarklet-post-blob-direct-fetch",
                    "eventType": "bookmarklet-post-direct-import",
                    "qualityNote": "visible-video-meets-floor:720x1280; bookmarklet-post-blob-direct-fetch; no-browser-download-prompt",
                },
            },
        },
        "checks": _current_quality_checks(
            channelReadinessGate={"status": "pass", "detail": "status=channel-ready"},
            uploadReviewGate={"status": "pass", "detail": "status=ready"},
            topTierReadinessGate={"status": "pass", "detail": "status=top-tier-ready"},
        ),
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["bestPacket"]["projectId"] == "bookmarklet-live-proof"
    bookmarklet = payload["sourcePipelineStatus"]["grok"]["bookmarkletDirectImport"]
    assert "companionDirectImport" not in payload["sourcePipelineStatus"]["grok"]
    assert bookmarklet["operatorReady"] is True
    assert bookmarklet["avoidsChromeDownloadPrompt"] is True
    assert payload["goalReadiness"]["liveGrokDirectImportProven"] is True
    assert payload["goalReadiness"]["liveGrokDirectImportProof"]["sourceKind"] == "bookmarklet-post-blob-direct-fetch"
    assert payload["goalReadiness"]["artifactGateComplete"] is True
    assert payload["goalReadiness"]["artifactRemainingGaps"] == []
    assert payload["goalReadiness"]["goalComplete"] is False
    assert payload["goalReadiness"]["operatingSystemComplete"] is False
    assert payload["goalReadiness"]["overallStatus"] == "artifact-gate-ready"
    assert payload["goalReadiness"]["operatorDecision"]["status"] == "edit"
    assert payload["goalReadiness"]["operatorDecision"]["label"] == "수정 필요"
    assert "Artifact gate is ready" in payload["goalReadiness"]["operatorDecision"]["detail"]
    assert payload["goalReadiness"]["preUploadReady"] is False
    assert payload["goalReadiness"]["preUploadDecision"]["status"] == "edit"
    assert payload["goalReadiness"]["preUploadDecision"]["label"] == "수정 필요"
    assert "fresh-source proof is missing" in payload["goalReadiness"]["preUploadDecision"]["detail"]
    assert "Same-day upload readiness" in payload["goalReadiness"]["preUploadBoundary"]
    runway = payload["goalReadiness"]["operatingRunwayChecklist"]
    assert [item["key"] for item in runway] == [
        "artifact-gate",
        "fresh-source-import-review",
        "fresh-source-proof",
        "phone-sized-human-review",
        "same-day-upload-decision",
        "platform-analytics-loop",
    ]
    assert runway[0]["status"] == "pass"
    assert runway[1]["status"] == "missing"
    assert runway[1]["blocksTodayUpload"] is True
    assert payload["goalReadiness"]["runwayChecklistSummary"]["readyForTodayUpload"] is False
    assert payload["goalReadiness"]["runwayChecklistSummary"]["primaryBlockerKey"] == "fresh-source-import-review"
    fresh_source = payload["goalReadiness"]["freshSourceRepeatability"]
    assert fresh_source["recorded"] is False
    assert fresh_source["ready"] is False
    assert fresh_source["status"] == "missing"
    assert fresh_source["artifactPath"].endswith("fresh-source-proof.json")
    assert fresh_source["templateArtifactPath"].endswith("fresh-source-proof.template.json")
    assert fresh_source["template"]["finalVideoPath"].endswith("bookmarklet.mp4")
    assert fresh_source["template"]["finalVideoSha256"] == _sha256_file(packet_dir / "bookmarklet.mp4")
    assert "fresh-source-proof.json" in fresh_source["operatorAction"]
    phone_review = payload["goalReadiness"]["phoneSizedHumanReview"]
    assert phone_review["recorded"] is False
    assert phone_review["ready"] is False
    assert phone_review["status"] == "missing"
    assert phone_review["artifactPath"].endswith("phone-review.json")
    assert phone_review["templateArtifactPath"].endswith("phone-review.template.json")
    assert phone_review["template"]["finalVideoPath"].endswith("bookmarklet.mp4")
    assert phone_review["template"]["finalVideoSha256"] == _sha256_file(packet_dir / "bookmarklet.mp4")
    assert phone_review["template"]["reviewerDecision"] == "needs-review"
    assert "full MP4" in phone_review["operatorAction"]
    platform_analytics = payload["goalReadiness"]["platformAnalytics"]
    assert platform_analytics["recorded"] is False
    assert platform_analytics["ready"] is False
    assert platform_analytics["status"] == "missing"
    assert platform_analytics["artifactPath"].endswith("platform-analytics.json")
    assert platform_analytics["templateArtifactPath"].endswith("platform-analytics.template.json")
    assert platform_analytics["template"]["finalVideoPath"].endswith("bookmarklet.mp4")
    assert platform_analytics["template"]["finalVideoSha256"] == _sha256_file(packet_dir / "bookmarklet.mp4")
    assert platform_analytics["template"]["decision"] == "missing"
    assert "2s hold" in platform_analytics["operatorAction"]
    assert any("fresh-source-proof.json" in item for item in payload["goalReadiness"]["remainingGaps"])


def test_final_video_library_evidence_templates_materializes_operator_worksheets(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "template-worksheet-live-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "template-worksheet-live-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    (packet_dir / "render-manifest.json").write_text(json.dumps({
        "projectId": "template-worksheet-live-proof",
        "outputPath": str(packet_dir / "template-worksheet-live-proof.mp4"),
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.post(
        "/api/final-video-library/evidence-templates",
        json={"projectId": "template-worksheet-live-proof", "limit": 10},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["goalComplete"] is False
    assert payload["proofArtifactsCreated"] is False
    assert "operator prep only" in payload["goalBoundary"]
    assert not (packet_dir / "phone-review.json").exists()
    assert not (packet_dir / "platform-analytics.json").exists()
    assert not (packet_dir / "fresh-source-proof.json").exists()

    phone_template_path = packet_dir / "phone-review.template.json"
    analytics_template_path = packet_dir / "platform-analytics.template.json"
    fresh_source_template_path = packet_dir / "fresh-source-proof.template.json"
    assert phone_template_path.exists()
    assert analytics_template_path.exists()
    assert fresh_source_template_path.exists()
    assert payload["templates"]["freshSourceRepeatability"]["proofArtifactCreated"] is False
    assert payload["templates"]["phoneSizedHumanReview"]["proofArtifactCreated"] is False
    assert payload["templates"]["platformAnalytics"]["proofArtifactCreated"] is False
    phone_template = json.loads(phone_template_path.read_text(encoding="utf-8"))
    analytics_template = json.loads(analytics_template_path.read_text(encoding="utf-8"))
    fresh_source_template = json.loads(fresh_source_template_path.read_text(encoding="utf-8"))
    assert fresh_source_template["templateOnly"] is True
    assert fresh_source_template["doNotSubmitAsProof"] is True
    assert fresh_source_template["targetProofArtifactPath"].endswith("fresh-source-proof.json")
    assert "operator-owned manual download/import" in fresh_source_template["sourceFlow"]
    assert fresh_source_template["finalVideoPath"].endswith("template-worksheet-live-proof.mp4")
    assert fresh_source_template["finalVideoSha256"] == _sha256_file(packet_dir / "template-worksheet-live-proof.mp4")
    assert fresh_source_template["renderManifestPath"].endswith("render-manifest.json")
    assert fresh_source_template["qualityAuditPath"].endswith("quality-audit.json")
    assert fresh_source_template["publishPacketPath"].endswith("publish-packet.json")
    assert fresh_source_template["handoffManifestPath"] == ""
    assert fresh_source_template["sourceReviewPath"] == ""
    assert fresh_source_template["dashboardSmokePath"].endswith("dashboard-smoke.json")
    assert fresh_source_template["handoffManifestSha256"] == ""
    assert fresh_source_template["sourceReviewSha256"] == ""
    assert fresh_source_template["renderManifestSha256"] == _sha256_file(packet_dir / "render-manifest.json")
    assert fresh_source_template["qualityAuditSha256"] == _sha256_file(packet_dir / "quality-audit.json")
    assert fresh_source_template["publishPacketSha256"] == _sha256_file(packet_dir / "publish-packet.json")
    assert fresh_source_template["dashboardSmokeSha256"] == ""
    fresh_digest_prefill = fresh_source_template["worksheetDigestPrefill"]
    assert "worksheet digest prefill only" in fresh_digest_prefill["note"].lower()
    assert {
        item["digestField"] for item in fresh_digest_prefill["prefilledFields"]
    } == {"renderManifestSha256", "qualityAuditSha256", "publishPacketSha256"}
    fresh_prefill_paths = {
        item["pathField"]: item["path"] for item in fresh_digest_prefill["prefilledFields"]
    }
    assert fresh_prefill_paths["renderManifestPath"] == fresh_source_template["renderManifestPath"]
    assert fresh_prefill_paths["qualityAuditPath"] == fresh_source_template["qualityAuditPath"]
    assert fresh_prefill_paths["publishPacketPath"] == fresh_source_template["publishPacketPath"]
    assert {
        item["digestField"] for item in fresh_digest_prefill["unresolvedFields"]
    } == {"handoffManifestSha256", "sourceReviewSha256", "dashboardSmokeSha256"}
    assert payload["templates"]["freshSourceRepeatability"]["digestPrefill"]["prefilledFields"] == fresh_digest_prefill["prefilledFields"]
    assert "timezone offset" in fresh_source_template["evidenceRequirements"]["recordedAt"]
    assert "projectId matches handoffProjectId" in fresh_source_template["evidenceRequirements"]["handoffManifestPath"]
    assert "acceptedSceneCount" in fresh_source_template["evidenceRequirements"]["sourceReviewPath"]
    assert "passes the publish packet content audit" in fresh_source_template["evidenceRequirements"]["publishPacketPath"]
    assert "Browser-rendered final-library dashboard smoke" in fresh_source_template["evidenceRequirements"]["dashboardSmokePath"]
    assert "today upload decision text" in fresh_source_template["evidenceRequirements"]["dashboardSmokePath"]
    assert "SHA-256 digest" in fresh_source_template["evidenceRequirements"]["handoffManifestSha256"]
    assert "SHA-256 digest" in fresh_source_template["evidenceRequirements"]["publishPacketSha256"]
    assert phone_template["reviewerType"] == "human"
    assert phone_template["reviewMethod"] == "real-phone-full-watch"
    assert phone_template["deviceViewport"] == "390x844"
    assert phone_template["watchDurationSeconds"] == 0
    assert phone_template["reviewSnapshotPath"] == ""
    assert phone_template["captionSafeZoneFramePath"] == ""
    assert phone_template["thumbnailFirstFramePath"] == ""
    assert phone_template["audioMixEvidencePath"] == ""
    assert phone_template["reviewSnapshotSha256"] == ""
    assert phone_template["captionSafeZoneFrameSha256"] == ""
    assert phone_template["thumbnailFirstFrameSha256"] == ""
    assert phone_template["audioMixEvidenceSha256"] == ""
    assert phone_template["worksheetDigestPrefill"]["prefilledFields"] == []
    assert {
        item["digestField"] for item in phone_template["worksheetDigestPrefill"]["unresolvedFields"]
    } == {
        "reviewSnapshotSha256",
        "captionSafeZoneFrameSha256",
        "thumbnailFirstFrameSha256",
        "audioMixEvidenceSha256",
    }
    assert "PNG/JPEG phone playback snapshot" in phone_template["evidenceRequirements"]["reviewSnapshotPath"]
    assert "JSON object" in phone_template["evidenceRequirements"]["audioMixEvidencePath"]
    assert "SHA-256 digest" in phone_template["evidenceRequirements"]["reviewSnapshotSha256"]
    assert "SHA-256 digest" in phone_template["evidenceRequirements"]["audioMixEvidenceSha256"]
    assert "timezone offset" in phone_template["evidenceRequirements"]["reviewedAt"]
    assert phone_template["reviewerDecision"] == "needs-review"
    assert phone_template["templateOnly"] is True
    assert phone_template["doNotSubmitAsProof"] is True
    assert phone_template["targetProofArtifactPath"].endswith("phone-review.json")
    assert phone_template["finalVideoSha256"] == _sha256_file(packet_dir / "template-worksheet-live-proof.mp4")
    assert "SHA-256 digest" in phone_template["evidenceRequirements"]["finalVideoSha256"]
    assert analytics_template["decision"] == "missing"
    assert analytics_template["analyticsSnapshotPath"].endswith("platform-analytics-snapshot.png")
    assert analytics_template["analyticsSnapshotSha256"] == ""
    assert analytics_template["worksheetDigestPrefill"]["prefilledFields"] == []
    assert analytics_template["worksheetDigestPrefill"]["unresolvedFields"][0]["digestField"] == "analyticsSnapshotSha256"
    assert analytics_template["finalVideoSha256"] == _sha256_file(packet_dir / "template-worksheet-live-proof.mp4")
    assert "SHA-256 digest" in analytics_template["evidenceRequirements"]["finalVideoSha256"]
    assert "PNG/JPEG platform analytics screenshot" in analytics_template["evidenceRequirements"]["analyticsSnapshotPath"]
    assert "SHA-256 digest" in analytics_template["evidenceRequirements"]["analyticsSnapshotSha256"]
    assert "timezone offsets" in analytics_template["evidenceRequirements"]["sampleWindow"]
    assert analytics_template["templateOnly"] is True
    assert analytics_template["doNotSubmitAsProof"] is True
    assert analytics_template["targetProofArtifactPath"].endswith("platform-analytics.json")

    audit_response = client.get("/api/final-video-library/audit?limit=10")
    assert audit_response.status_code == 200
    audit_payload = audit_response.get_json()
    assert audit_payload["goalReadiness"]["goalComplete"] is False
    assert audit_payload["goalReadiness"]["freshSourceRepeatability"]["status"] == "summary-only"
    assert audit_payload["goalReadiness"]["phoneSizedHumanReview"]["status"] == "missing"
    assert audit_payload["goalReadiness"]["platformAnalytics"]["status"] == "missing"


def test_final_video_library_fresh_source_evidence_route_prepares_drafts_without_goal_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "fresh-source-evidence-prep"
    _write_ready_final_video_packet(
        packet_dir,
        "fresh-source-evidence-prep",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    render_manifest = {
        "projectId": "fresh-source-evidence-prep",
        "outputPath": str(packet_dir / "fresh-source-evidence-prep.mp4"),
        "scenes": [
            {
                "sceneId": "scene-01",
                "title": "Hook",
                "visualSourceIntent": "grok",
                "selectedFileName": "scene-01-grok.mp4",
                "sourceProvenanceConfirmed": True,
                "sourceRationale": "Fresh Grok direct-import source candidate.",
                "continuityNote": "Starts the shoulder reset loop.",
                "hookNote": "Viewer-visible first-two-second tension hook.",
                "qualityReviewNote": "No visible watermark or malformed body part.",
                "visualQualityVerdictStatus": "pass",
                "captionPreset": "top-hook",
            },
            {
                "sceneId": "scene-02",
                "title": "Context",
                "visualSourceIntent": "selected-stock",
                "selectedFileName": "scene-02-pexels.mp4",
                "sourceProvenanceConfirmed": False,
                "sourceRationale": "Selected-stock rewrite candidate.",
                "qualityReviewNote": "Motion and clip fit are reviewable.",
                "visualQualityVerdictStatus": "pass",
                "stockAiClipFitVerdict": "pass",
                "captionPreset": "lower-safe",
            },
            {
                "sceneId": "scene-03",
                "title": "Payoff",
                "visualSourceIntent": "grok",
                "selectedFileName": "scene-03-needs-review.mp4",
                "sourceProvenanceConfirmed": True,
                "sourceRationale": "Needs manual body-shape review before acceptance.",
                "visualQualityVerdictStatus": "warn",
                "captionPreset": "lower-safe",
            },
        ],
    }
    (packet_dir / "render-manifest.json").write_text(json.dumps(render_manifest), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.post(
        "/api/final-video-library/fresh-source-evidence",
        json={"projectId": "fresh-source-evidence-prep", "limit": 10},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["status"] == "written-not-proof"
    assert payload["proofArtifactsCreated"] is False
    assert payload["freshSourceProofCreated"] is False
    assert payload["goalComplete"] is False
    assert payload["sceneCount"] == 3
    assert payload["candidateReadySceneCount"] == 2
    assert payload["reviewRequiredSceneCount"] == 3
    assert payload["acceptedSceneCount"] == 0
    assert payload["rejectedSceneCount"] == 0
    assert payload["operatorAcceptedSceneCount"] == 0
    assert payload["freshSourceProofReadySceneCount"] == 0
    assert payload["proofBlockerCount"] == 7
    assert payload["scenesWithProofBlockers"] == ["scene-01", "scene-02", "scene-03"]
    assert payload["sourceRecoveryAcceptanceStatus"]["status"] == "no-source-recovery-required"
    assert payload["sourceRecoveryAcceptanceBlockerCount"] == 0
    assert payload["freshSourceProofBlockedBySourceRecoveryAcceptance"] is False
    assert "does not create fresh-source-proof.json" in payload["goalBoundary"]
    assert not (packet_dir / "fresh-source-proof.json").exists()

    handoff_path = packet_dir / "fresh-source-handoff.template.json"
    review_path = packet_dir / "fresh-source-review.template.json"
    template_path = packet_dir / "fresh-source-proof.template.json"
    assert payload["artifactPaths"]["handoffManifestPath"] == str(handoff_path)
    assert payload["artifactPaths"]["sourceReviewPath"] == str(review_path)
    assert handoff_path.exists()
    assert review_path.exists()
    assert template_path.exists()

    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    template = json.loads(template_path.read_text(encoding="utf-8"))
    assert handoff["templateOnly"] is True
    assert handoff["doNotSubmitAsProof"] is True
    assert handoff["proofArtifactCreated"] is False
    assert handoff["freshSourceProofCreated"] is False
    assert handoff["sceneCount"] == 3
    assert handoff["candidateReadySceneCount"] == 2
    assert handoff["freshSourceProofReadySceneCount"] == 0
    assert handoff["proofBlockerCount"] == 7
    assert handoff["sourceRecoveryAcceptanceStatus"]["status"] == "no-source-recovery-required"
    assert handoff["sourceRecoveryAcceptanceBlockerCount"] == 0
    assert handoff["freshSourceProofBlockedBySourceRecoveryAcceptance"] is False
    assert handoff["scenes"][0]["operatorDecision"] == "needs-review"
    assert handoff["scenes"][0]["proofAccepted"] is False
    assert handoff["scenes"][0]["freshSourceProofReady"] is False
    assert "operator source review has not accepted this scene" in handoff["scenes"][0]["proofBlockers"]
    assert "first-two-second hook still needs phone-sized operator review" in handoff["scenes"][0]["proofBlockers"]
    assert "source provenance is not confirmed" in handoff["scenes"][1]["proofBlockers"]
    assert "selected-stock or Pexels fallback still needs explicit source-fit and phone-sized review" in handoff["scenes"][1]["proofBlockers"]
    assert "visual quality verdict is not pass/ready" in handoff["scenes"][2]["proofBlockers"]
    assert review["templateOnly"] is True
    assert review["doNotSubmitAsProof"] is True
    assert review["status"] == "needs-operator-review"
    assert review["reviewStatus"] == "needs-operator-review"
    assert review["acceptedSceneCount"] == 0
    assert review["rejectedSceneCount"] == 0
    assert review["reviewRequiredSceneCount"] == 3
    assert review["freshSourceProofReadySceneCount"] == 0
    assert review["proofBlockerCount"] == 7
    assert review["sourceRecoveryAcceptanceStatus"]["status"] == "no-source-recovery-required"
    assert review["sourceRecoveryAcceptanceBlockerCount"] == 0
    assert review["freshSourceProofBlockedBySourceRecoveryAcceptance"] is False
    assert all(scene["operatorDecision"] == "needs-review" for scene in review["scenes"])
    assert all(scene["freshSourceProofReady"] is False for scene in review["scenes"])

    assert template["templateOnly"] is True
    assert template["doNotSubmitAsProof"] is True
    assert template["targetProofArtifactPath"].endswith("fresh-source-proof.json")
    assert template["handoffManifestPath"] == str(handoff_path)
    assert template["sourceReviewPath"] == str(review_path)
    assert template["handoffManifestSha256"] == _sha256_file(handoff_path)
    assert template["sourceReviewSha256"] == _sha256_file(review_path)
    assert template["sourceEvidencePrep"]["status"] == "written-not-proof"
    assert template["sourceEvidencePrep"]["operatorReviewRequired"] is True
    assert template["sourceEvidencePrep"]["reviewRequiredSceneCount"] == 3
    assert template["sourceEvidencePrep"]["freshSourceProofReadySceneCount"] == 0
    assert template["sourceEvidencePrep"]["proofBlockerCount"] == 7
    assert template["sourceEvidencePrep"]["scenesWithProofBlockers"] == ["scene-01", "scene-02", "scene-03"]
    assert template["sourceEvidencePrep"]["sourceRecoveryAcceptanceStatus"]["status"] == "no-source-recovery-required"
    assert template["sourceEvidencePrep"]["sourceRecoveryAcceptanceBlockerCount"] == 0
    assert template["sourceEvidencePrep"]["freshSourceProofBlockedBySourceRecoveryAcceptance"] is False
    assert template["importedSceneCount"] == 0
    assert template["acceptedSceneCount"] == 0
    assert template["differentTopic"] is False
    assert template["movingClipStitching"] is False
    assert template["qualityAuditPass"] is False
    assert template["dashboardSmokePass"] is False
    assert payload["freshSourceTemplate"]["proofArtifactCreated"] is False

    audit_response = client.get("/api/final-video-library/audit?limit=10")
    assert audit_response.status_code == 200
    audit_payload = audit_response.get_json()
    fresh_source = audit_payload["goalReadiness"]["freshSourceRepeatability"]
    assert fresh_source["ready"] is False
    assert fresh_source["status"] != "pass"
    assert fresh_source["artifactPath"].endswith("fresh-source-proof.json")
    assert not Path(fresh_source["artifactPath"]).exists()


def test_final_video_library_evidence_templates_prefills_browser_rendered_dashboard_smoke_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "template-dashboard-smoke-prefill"
    _write_ready_final_video_packet(
        packet_dir,
        "template-dashboard-smoke-prefill",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    (packet_dir / "render-manifest.json").write_text(json.dumps({
        "projectId": "template-dashboard-smoke-prefill",
        "outputPath": str(packet_dir / "template-dashboard-smoke-prefill.mp4"),
    }), encoding="utf-8")
    dashboard_smoke = packet_dir / "dashboard-smoke.json"
    dashboard_smoke.write_text(json.dumps({
        "ok": True,
        "projectId": "template-dashboard-smoke-prefill",
        "surface": "final-library-dashboard",
        "browserRendered": True,
        "bridgeConnected": True,
        "finalLibraryPanelVisible": True,
        "visibleTexts": [
            "Final video library",
            "template-dashboard-smoke-prefill",
            "today upload decision: 수정 필요",
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.post(
        "/api/final-video-library/evidence-templates",
        json={"projectId": "template-dashboard-smoke-prefill", "limit": 10},
    )

    assert response.status_code == 200
    payload = response.get_json()
    fresh_template = json.loads((packet_dir / "fresh-source-proof.template.json").read_text(encoding="utf-8"))
    assert fresh_template["dashboardSmokePath"].endswith("dashboard-smoke.json")
    assert fresh_template["dashboardSmokeSha256"] == _sha256_file(dashboard_smoke)
    digest_prefill = fresh_template["worksheetDigestPrefill"]
    assert "dashboardSmokeSha256" in {item["digestField"] for item in digest_prefill["prefilledFields"]}
    assert "dashboardSmokeSha256" not in {item["digestField"] for item in digest_prefill["unresolvedFields"]}
    assert payload["templates"]["freshSourceRepeatability"]["digestPrefill"]["prefilledFields"] == digest_prefill["prefilledFields"]
    assert payload["proofArtifactsCreated"] is False
    assert not (packet_dir / "fresh-source-proof.json").exists()


def test_final_video_library_evidence_templates_rejects_api_only_dashboard_smoke_prefill(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "template-api-only-dashboard-smoke"
    _write_ready_final_video_packet(
        packet_dir,
        "template-api-only-dashboard-smoke",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    (packet_dir / "render-manifest.json").write_text(json.dumps({
        "projectId": "template-api-only-dashboard-smoke",
        "outputPath": str(packet_dir / "template-api-only-dashboard-smoke.mp4"),
    }), encoding="utf-8")
    dashboard_smoke = packet_dir / "dashboard-smoke.json"
    dashboard_smoke.write_text(json.dumps({
        "ok": True,
        "projectId": "template-api-only-dashboard-smoke",
        "preUploadReady": False,
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.post(
        "/api/final-video-library/evidence-templates",
        json={"projectId": "template-api-only-dashboard-smoke", "limit": 10},
    )

    assert response.status_code == 200
    fresh_template = json.loads((packet_dir / "fresh-source-proof.template.json").read_text(encoding="utf-8"))
    assert fresh_template["dashboardSmokePath"].endswith("dashboard-smoke.json")
    assert fresh_template["dashboardSmokeSha256"] == ""
    digest_prefill = fresh_template["worksheetDigestPrefill"]
    assert "dashboardSmokeSha256" not in {item["digestField"] for item in digest_prefill["prefilledFields"]}
    dashboard_unresolved = next(
        item for item in digest_prefill["unresolvedFields"] if item["digestField"] == "dashboardSmokeSha256"
    )
    assert "dashboard smoke invalid" in dashboard_unresolved["reason"]
    assert "browserRendered=true" in dashboard_unresolved["reason"]
    assert "today upload decision" in dashboard_unresolved["reason"]
    assert not (packet_dir / "fresh-source-proof.json").exists()


def test_final_video_library_dashboard_smoke_route_writes_browser_rendered_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "dashboard-smoke-route-valid"
    _write_ready_final_video_packet(
        packet_dir,
        "dashboard-smoke-route-valid",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    (packet_dir / "render-manifest.json").write_text(json.dumps({
        "projectId": "dashboard-smoke-route-valid",
        "outputPath": str(packet_dir / "dashboard-smoke-route-valid.mp4"),
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.post(
        "/api/final-video-library/dashboard-smoke",
        json={
            "projectId": "dashboard-smoke-route-valid",
            "surface": "final-library-dashboard",
            "browserRendered": True,
            "bridgeConnected": True,
            "finalLibraryPanelVisible": True,
            "preUploadReady": False,
            "visibleTexts": [
                "Final video library",
                "dashboard-smoke-route-valid",
                "today upload decision: 수정 필요",
            ],
            "url": "http://127.0.0.1:5173/",
            "userAgent": "pytest browser",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["status"] == "pass"
    assert payload["proofArtifactsCreated"] is False
    assert payload["freshSourceProofCreated"] is False
    assert payload["goalComplete"] is False
    smoke_path = packet_dir / "dashboard-smoke.json"
    assert payload["path"] == str(smoke_path)
    assert payload["sha256"] == _sha256_file(smoke_path)
    smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
    assert smoke["ok"] is True
    assert smoke["browserRendered"] is True
    assert smoke["bridgeConnected"] is True
    assert smoke["finalLibraryPanelVisible"] is True
    assert smoke["source"] == "video-studio-dashboard-ui"
    assert "fresh-source-proof.json" not in [path.name for path in packet_dir.iterdir()]
    fresh_template = json.loads((packet_dir / "fresh-source-proof.template.json").read_text(encoding="utf-8"))
    assert fresh_template["dashboardSmokePath"].endswith("dashboard-smoke.json")
    assert fresh_template["dashboardSmokeSha256"] == _sha256_file(smoke_path)
    assert "dashboardSmokeSha256" in {
        item["digestField"] for item in fresh_template["worksheetDigestPrefill"]["prefilledFields"]
    }


def test_final_video_library_dashboard_smoke_route_records_invalid_capture_without_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "dashboard-smoke-route-invalid"
    _write_ready_final_video_packet(
        packet_dir,
        "dashboard-smoke-route-invalid",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.post(
        "/api/final-video-library/dashboard-smoke",
        json={
            "projectId": "dashboard-smoke-route-invalid",
            "surface": "final-library-dashboard",
            "browserRendered": False,
            "bridgeConnected": True,
            "finalLibraryPanelVisible": True,
            "visibleTexts": ["Final video library", "dashboard-smoke-route-invalid"],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["status"] == "fail"
    assert "dashboard smoke must record browserRendered=true" in payload["issues"]
    assert "dashboard smoke visible text must include today upload decision" in payload["issues"]
    smoke_path = packet_dir / "dashboard-smoke.json"
    smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
    assert smoke["ok"] is False
    assert smoke["proofArtifactsCreated"] is False
    assert not (packet_dir / "fresh-source-proof.json").exists()
    fresh_template = json.loads((packet_dir / "fresh-source-proof.template.json").read_text(encoding="utf-8"))
    assert fresh_template["dashboardSmokeSha256"] == ""
    dashboard_unresolved = next(
        item for item in fresh_template["worksheetDigestPrefill"]["unresolvedFields"]
        if item["digestField"] == "dashboardSmokeSha256"
    )
    assert "dashboard smoke invalid" in dashboard_unresolved["reason"]
    assert "did not record ok=true" in dashboard_unresolved["reason"]


def test_final_video_library_phone_review_evidence_route_prepares_artifacts_without_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "phone-evidence-route"
    _write_ready_final_video_packet(
        packet_dir,
        "phone-evidence-route",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    def fake_phone_evidence(best_packet, _data):
        evidence_dir = Path(best_packet["packetDir"])
        review_snapshot = evidence_dir / "phone-review-snapshot.jpg"
        caption_frame = evidence_dir / "phone-caption-safe-zone.jpg"
        thumbnail_frame = evidence_dir / "phone-thumbnail-first-frame.jpg"
        audio_evidence = evidence_dir / "phone-audio-mix-evidence.json"
        _write_png_evidence(review_snapshot, width=390, height=844)
        _write_png_evidence(caption_frame, width=1080, height=1920)
        _write_png_evidence(thumbnail_frame, width=1080, height=1920)
        audio_evidence.write_text(json.dumps({
            "schema": "video-studio.phone-audio-mix-evidence.v1",
            "audioDevice": "operator-phone-headphones-required",
            "headphonesUsed": False,
            "audioMixReviewPass": False,
            "operatorReviewRequired": True,
        }), encoding="utf-8")
        artifact_paths = {
            "reviewSnapshotPath": str(review_snapshot),
            "captionSafeZoneFramePath": str(caption_frame),
            "thumbnailFirstFramePath": str(thumbnail_frame),
            "audioMixEvidencePath": str(audio_evidence),
        }
        artifact_checks = {
            field: routes_media._phone_review_artifact_check(field, Path(path))
            for field, path in artifact_paths.items()
        }
        return {
            "ok": True,
            "status": "prepared",
            "artifactPaths": artifact_paths,
            "artifactChecks": artifact_checks,
            "pendingFields": ["audioMixEvidencePath"],
            "issues": [],
        }

    monkeypatch.setattr(routes_media, "_write_phone_review_evidence_artifacts", fake_phone_evidence)

    response = client.post(
        "/api/final-video-library/phone-review-evidence",
        json={"projectId": "phone-evidence-route"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["status"] == "prepared"
    assert payload["proofArtifactsCreated"] is False
    assert payload["phoneReviewProofCreated"] is False
    assert payload["goalComplete"] is False
    assert "does not create phone-review.json" in payload["goalBoundary"]
    assert payload["pendingFields"] == ["audioMixEvidencePath"]
    assert not (packet_dir / "phone-review.json").exists()

    phone_template_path = packet_dir / "phone-review.template.json"
    phone_template = json.loads(phone_template_path.read_text(encoding="utf-8"))
    assert phone_template["templateOnly"] is True
    assert phone_template["doNotSubmitAsProof"] is True
    assert phone_template["reviewSnapshotPath"].endswith("phone-review-snapshot.jpg")
    assert phone_template["captionSafeZoneFramePath"].endswith("phone-caption-safe-zone.jpg")
    assert phone_template["thumbnailFirstFramePath"].endswith("phone-thumbnail-first-frame.jpg")
    assert phone_template["audioMixEvidencePath"].endswith("phone-audio-mix-evidence.json")
    assert phone_template["reviewSnapshotSha256"] == _sha256_file(packet_dir / "phone-review-snapshot.jpg")
    assert phone_template["captionSafeZoneFrameSha256"] == _sha256_file(packet_dir / "phone-caption-safe-zone.jpg")
    assert phone_template["thumbnailFirstFrameSha256"] == _sha256_file(packet_dir / "phone-thumbnail-first-frame.jpg")
    assert phone_template["audioMixEvidenceSha256"] == ""
    assert {
        item["digestField"] for item in phone_template["worksheetDigestPrefill"]["prefilledFields"]
    } == {
        "reviewSnapshotSha256",
        "captionSafeZoneFrameSha256",
        "thumbnailFirstFrameSha256",
    }
    audio_unresolved = next(
        item for item in phone_template["worksheetDigestPrefill"]["unresolvedFields"]
        if item["digestField"] == "audioMixEvidenceSha256"
    )
    assert "phone review evidence invalid" in audio_unresolved["reason"]
    assert "headphones evidence is missing" in audio_unresolved["reason"]
    assert payload["phoneTemplate"]["digestPrefill"]["prefilledFields"] == phone_template["worksheetDigestPrefill"]["prefilledFields"]
    assert not (packet_dir / "fresh-source-proof.json").exists()
    assert not (packet_dir / "platform-analytics.json").exists()


def test_final_video_library_audit_rejects_summary_only_fresh_source_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "summary-only-fresh-source"
    _write_ready_final_video_packet(
        packet_dir,
        "summary-only-fresh-source",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    fresh_source = payload["goalReadiness"]["freshSourceRepeatability"]
    assert fresh_source["recorded"] is False
    assert fresh_source["ready"] is False
    assert fresh_source["status"] == "summary-only"
    assert fresh_source["legacySummaryReady"] is True
    assert payload["goalReadiness"]["freshSourceBatchProven"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False


def test_final_video_library_audit_accepts_fresh_source_repeatability_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "fresh-source-live-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "fresh-source-live-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "fresh-source-live-proof")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    fresh_source = payload["goalReadiness"]["freshSourceRepeatability"]
    assert fresh_source["recorded"] is True
    assert fresh_source["ready"] is True
    assert fresh_source["status"] == "pass"
    assert fresh_source["missingFields"] == []
    assert fresh_source["failedFields"] == []
    assert fresh_source["finalVideoDigestCheck"]["ok"] is True
    assert fresh_source["finalVideoDigestCheck"]["actualSha256"] == _sha256_file(packet_dir / "fresh-source-live-proof.mp4")
    assert fresh_source["recordedAtCheck"]["ok"] is True
    assert fresh_source["recordedAtCheck"]["timezoneProvided"] is True
    evidence_paths = fresh_source["evidenceArtifactPaths"]
    assert evidence_paths["handoffManifestPath"].endswith("fresh-source-handoff.json")
    assert evidence_paths["sourceReviewPath"].endswith("fresh-source-review.json")
    assert evidence_paths["renderManifestPath"].endswith("render-manifest.json")
    assert evidence_paths["qualityAuditPath"].endswith("quality-audit.json")
    assert evidence_paths["publishPacketPath"].endswith("publish-packet.json")
    assert evidence_paths["dashboardSmokePath"].endswith("dashboard-smoke.json")
    evidence_checks = fresh_source["evidenceArtifactChecks"]
    assert evidence_checks["handoffManifestPath"]["ok"] is True
    assert evidence_checks["sourceReviewPath"]["ok"] is True
    assert evidence_checks["renderManifestPath"]["ok"] is True
    assert evidence_checks["qualityAuditPath"]["ok"] is True
    assert evidence_checks["publishPacketPath"]["ok"] is True
    assert evidence_checks["dashboardSmokePath"]["ok"] is True
    digest_checks = fresh_source["evidenceDigestChecks"]
    assert digest_checks["handoffManifestSha256"]["ok"] is True
    assert digest_checks["sourceReviewSha256"]["ok"] is True
    assert digest_checks["renderManifestSha256"]["ok"] is True
    assert digest_checks["qualityAuditSha256"]["ok"] is True
    assert digest_checks["publishPacketSha256"]["ok"] is True
    assert digest_checks["dashboardSmokeSha256"]["ok"] is True
    assert digest_checks["handoffManifestSha256"]["actualSha256"] == _sha256_file(packet_dir / "fresh-source-handoff.json")
    assert payload["goalReadiness"]["freshSourceBatchProven"] is True
    assert payload["goalReadiness"]["preUploadReady"] is False
    assert "phone-sized human review" in payload["goalReadiness"]["preUploadDecision"]["detail"]


def test_final_video_library_audit_requires_source_recovery_links_for_rerendered_fresh_source_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "fresh-source-recovery-rerender-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "fresh-source-recovery-rerender-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "fresh-source-recovery-rerender-proof")
    source_review_path = packet_dir / "fresh-source-review.json"
    source_review = json.loads(source_review_path.read_text(encoding="utf-8"))
    source_review.update({
        "sourceRecoveryAcceptanceStatus": {
            "status": "accepted-replacements-ready-for-rerender",
            "acceptedSceneCount": 1,
            "incompleteSceneCount": 0,
        },
        "sourceRecoveryAcceptanceBlockerCount": 0,
    })
    source_review_path.write_text(json.dumps(source_review), encoding="utf-8")
    proof_path = packet_dir / "fresh-source-proof.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["sourceReviewSha256"] = _sha256_file(source_review_path)
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    missing_response = client.get("/api/final-video-library/audit?limit=10")

    assert missing_response.status_code == 200
    missing_payload = missing_response.get_json()
    missing_fresh_source = missing_payload["goalReadiness"]["freshSourceRepeatability"]
    assert missing_fresh_source["recorded"] is True
    assert missing_fresh_source["ready"] is False
    assert missing_fresh_source["status"] == "needs-proof"
    assert missing_fresh_source["sourceRecoveryLinkRequired"] is True
    assert "sourceRecoveryAcceptanceArtifactPath" in missing_fresh_source["missingFields"]
    assert "sourceRecoveryAcceptanceSha256" in missing_fresh_source["missingFields"]
    assert "sourceRecoveryRerenderPlanPath" in missing_fresh_source["missingFields"]
    assert "sourceRecoveryRerenderPlanSha256" in missing_fresh_source["missingFields"]
    assert missing_fresh_source["evidenceArtifactChecks"]["sourceRecoveryAcceptanceArtifactPath"]["ok"] is False

    handoff_dir = tmp_path / "storage" / "grok-handoffs" / "fresh-source-recovery-handoff"
    incoming_dir = handoff_dir / "incoming"
    incoming_dir.mkdir(parents=True)
    accepted_replacement = incoming_dir / "scene-03-replacement.mp4"
    accepted_replacement.write_bytes(b"accepted replacement source")
    acceptance_path = handoff_dir / "source-recovery-acceptance.json"
    acceptance_payload = {
        "schema": "video-studio.source-recovery-acceptance.v1",
        "projectId": "fresh-source-recovery-handoff",
        "templateOnly": False,
        "doNotSubmitAsProof": True,
        "acceptanceScenes": [
            {
                "sceneId": "scene-03",
                "operatorDecision": {
                    "accepted": True,
                    "reviewStatus": "accepted",
                    "acceptedReplacementFileName": accepted_replacement.name,
                    "acceptedReplacementPath": str(accepted_replacement),
                    "acceptedReplacementSha256": _sha256_file(accepted_replacement),
                    "reviewerId": "operator-test",
                    "acceptedAt": "2026-06-03T12:00:00+09:00",
                },
            },
        ],
    }
    acceptance_path.write_text(json.dumps(acceptance_payload), encoding="utf-8")
    rerender_plan_path = handoff_dir / "source-recovery-rerender-plan.template.json"
    rerender_plan_payload = {
        "schema": "video-studio.source-recovery-rerender-plan.v1",
        "projectId": "fresh-source-recovery-handoff",
        "templateOnly": True,
        "doNotSubmitAsProof": True,
        "sourceRecoveryAcceptanceCleared": True,
        "rerenderInputReady": True,
        "sourceRecoveryAcceptanceArtifactPath": str(acceptance_path),
        "sourceRecoveryAcceptanceSha256": _sha256_file(acceptance_path),
        "sceneReplacements": [
            {
                "sceneId": "scene-03",
                "acceptedReplacementPath": str(accepted_replacement),
                "acceptedReplacementSha256": _sha256_file(accepted_replacement),
            },
        ],
        "renderPlan": {
            "freshSourceProofRequiredAfterRerender": True,
        },
    }
    rerender_plan_path.write_text(json.dumps(rerender_plan_payload), encoding="utf-8")
    proof.update({
        "sourceReviewSha256": _sha256_file(source_review_path),
        "sourceRecoveryAcceptanceArtifactPath": str(acceptance_path),
        "sourceRecoveryAcceptanceSha256": _sha256_file(acceptance_path),
        "sourceRecoveryRerenderPlanPath": str(rerender_plan_path),
        "sourceRecoveryRerenderPlanSha256": _sha256_file(rerender_plan_path),
    })
    proof_path.write_text(json.dumps(proof), encoding="utf-8")

    accepted_response = client.get("/api/final-video-library/audit?limit=10")

    assert accepted_response.status_code == 200
    accepted_payload = accepted_response.get_json()
    accepted_fresh_source = accepted_payload["goalReadiness"]["freshSourceRepeatability"]
    assert accepted_fresh_source["recorded"] is True
    assert accepted_fresh_source["ready"] is True
    assert accepted_fresh_source["status"] == "pass"
    assert accepted_fresh_source["missingFields"] == []
    assert accepted_fresh_source["failedFields"] == []
    assert accepted_fresh_source["sourceRecoveryLinkRequired"] is True
    link_requirement = accepted_fresh_source["sourceRecoveryLinkRequirement"]
    assert link_requirement["status"] == "accepted-replacements-ready-for-rerender"
    artifact_checks = accepted_fresh_source["evidenceArtifactChecks"]
    assert artifact_checks["sourceRecoveryAcceptanceArtifactPath"]["ok"] is True
    assert artifact_checks["sourceRecoveryRerenderPlanPath"]["ok"] is True
    digest_checks = accepted_fresh_source["evidenceDigestChecks"]
    assert digest_checks["sourceRecoveryAcceptanceSha256"]["ok"] is True
    assert digest_checks["sourceRecoveryRerenderPlanSha256"]["ok"] is True
    assert accepted_payload["goalReadiness"]["freshSourceBatchProven"] is True


def test_final_video_library_audit_rejects_fresh_source_evidence_digest_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "fresh-source-digest-mismatch"
    _write_ready_final_video_packet(
        packet_dir,
        "fresh-source-digest-mismatch",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(
        packet_dir,
        "fresh-source-digest-mismatch",
        overrides={"sourceReviewSha256": "0" * 64},
    )
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    fresh_source = payload["goalReadiness"]["freshSourceRepeatability"]
    assert fresh_source["recorded"] is True
    assert fresh_source["ready"] is False
    assert fresh_source["status"] == "fail"
    assert "sourceReviewSha256" in fresh_source["failedFields"]
    assert fresh_source["evidenceArtifactChecks"]["sourceReviewPath"]["ok"] is True
    digest_checks = fresh_source["evidenceDigestChecks"]
    assert digest_checks["sourceReviewSha256"]["ok"] is False
    assert digest_checks["sourceReviewSha256"]["actualSha256"] == _sha256_file(packet_dir / "fresh-source-review.json")
    assert "sourceReviewSha256 does not match sourceReviewPath bytes" in digest_checks["sourceReviewSha256"]["issues"]
    assert digest_checks["handoffManifestSha256"]["ok"] is True
    assert digest_checks["renderManifestSha256"]["ok"] is True
    assert payload["goalReadiness"]["freshSourceBatchProven"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False


def test_final_video_library_audit_rejects_api_only_dashboard_smoke(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "fresh-source-api-only-dashboard-smoke"
    _write_ready_final_video_packet(
        packet_dir,
        "fresh-source-api-only-dashboard-smoke",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "fresh-source-api-only-dashboard-smoke")
    dashboard_smoke = packet_dir / "dashboard-smoke.json"
    dashboard_smoke.write_text(json.dumps({
        "ok": True,
        "projectId": "fresh-source-api-only-dashboard-smoke",
        "preUploadReady": False,
    }), encoding="utf-8")
    proof_path = packet_dir / "fresh-source-proof.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["dashboardSmokeSha256"] = _sha256_file(dashboard_smoke)
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    fresh_source = payload["goalReadiness"]["freshSourceRepeatability"]
    assert fresh_source["recorded"] is True
    assert fresh_source["ready"] is False
    assert fresh_source["status"] == "fail"
    assert "dashboardSmokePath" in fresh_source["failedFields"]
    assert "dashboardSmokeSha256" not in fresh_source["failedFields"]
    dashboard_check = fresh_source["evidenceArtifactChecks"]["dashboardSmokePath"]
    assert dashboard_check["ok"] is False
    assert "dashboard smoke surface must be final-library-dashboard" in dashboard_check["issues"]
    assert "dashboard smoke must record browserRendered=true" in dashboard_check["issues"]
    assert "dashboard smoke must record bridgeConnected=true" in dashboard_check["issues"]
    assert "dashboard smoke must record finalLibraryPanelVisible=true" in dashboard_check["issues"]
    assert "dashboard smoke visible text must include renderedProjectId" in dashboard_check["issues"]
    assert "dashboard smoke visible text must include today upload decision" in dashboard_check["issues"]
    assert fresh_source["evidenceDigestChecks"]["dashboardSmokeSha256"]["ok"] is True
    assert payload["goalReadiness"]["freshSourceBatchProven"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False


def test_final_video_library_audit_rejects_weak_fresh_source_repeatability_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "fresh-source-weak-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "fresh-source-weak-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(
        packet_dir,
        "fresh-source-weak-proof",
        overrides={
            "sourceFlow": "Grok Download/Save/Export through Chrome native download prompt",
            "handoffManifestPath": str(packet_dir / "missing-handoff.json"),
            "sourceReviewPath": str(packet_dir / "missing-source-review.json"),
            "dashboardSmokePath": str(packet_dir / "missing-dashboard-smoke.json"),
            "importedSceneCount": 2,
            "acceptedSceneCount": 4,
        },
    )
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    fresh_source = payload["goalReadiness"]["freshSourceRepeatability"]
    assert fresh_source["recorded"] is True
    assert fresh_source["ready"] is False
    assert fresh_source["status"] == "fail"
    assert "sourceFlow" in fresh_source["failedFields"]
    assert "handoffManifestPath" in fresh_source["failedFields"]
    assert "sourceReviewPath" in fresh_source["failedFields"]
    assert "dashboardSmokePath" in fresh_source["failedFields"]
    assert "importedSceneCount" in fresh_source["failedFields"]
    assert "acceptedSceneCount" in fresh_source["failedFields"]
    assert payload["goalReadiness"]["freshSourceBatchProven"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False


def test_final_video_library_audit_rejects_fresh_source_placeholder_artifact_contents(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "fresh-source-placeholder-artifacts"
    _write_ready_final_video_packet(
        packet_dir,
        "fresh-source-placeholder-artifacts",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "fresh-source-placeholder-artifacts")
    for name in [
        "fresh-source-handoff.json",
        "fresh-source-review.json",
        "render-manifest.json",
        "quality-audit.json",
        "publish-packet.json",
        "dashboard-smoke.json",
    ]:
        (packet_dir / name).write_text(json.dumps({"notes": "placeholder only"}), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    fresh_source = payload["goalReadiness"]["freshSourceRepeatability"]
    assert fresh_source["recorded"] is True
    assert fresh_source["ready"] is False
    assert fresh_source["status"] == "fail"
    assert "handoffManifestPath" in fresh_source["failedFields"]
    assert "sourceReviewPath" in fresh_source["failedFields"]
    assert "renderManifestPath" in fresh_source["failedFields"]
    assert "qualityAuditPath" in fresh_source["failedFields"]
    assert "publishPacketPath" in fresh_source["failedFields"]
    assert "dashboardSmokePath" in fresh_source["failedFields"]
    checks = fresh_source["evidenceArtifactChecks"]
    assert checks["handoffManifestPath"]["ok"] is False
    assert "handoff manifest projectId does not match proof handoffProjectId" in checks["handoffManifestPath"]["issues"]
    assert checks["sourceReviewPath"]["ok"] is False
    assert "source review status is not accepted/pass/ready" in checks["sourceReviewPath"]["issues"]
    assert checks["publishPacketPath"]["ok"] is False
    assert "publish packet content audit is not ready" in checks["publishPacketPath"]["issues"][0]
    assert checks["dashboardSmokePath"]["ok"] is False
    assert "dashboard smoke did not record ok=true" in checks["dashboardSmokePath"]["issues"]
    assert fresh_source["evidenceArtifactPaths"] == {}
    assert payload["goalReadiness"]["freshSourceBatchProven"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False


def test_final_video_library_audit_rejects_fresh_source_proof_for_different_final_video(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "fresh-source-mismatch-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "fresh-source-mismatch-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(
        packet_dir,
        "fresh-source-mismatch-proof",
        overrides={"finalVideoPath": str(packet_dir / "different-final.mp4")},
    )
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    fresh_source = payload["goalReadiness"]["freshSourceRepeatability"]
    assert fresh_source["recorded"] is True
    assert fresh_source["ready"] is False
    assert fresh_source["status"] == "fail"
    assert "finalVideoPath" in fresh_source["failedFields"]
    assert payload["goalReadiness"]["freshSourceBatchProven"] is False


def test_final_video_library_audit_rejects_fresh_and_phone_proofs_without_timezone_timestamps(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "proof-timestamp-no-timezone"
    _write_ready_final_video_packet(
        packet_dir,
        "proof-timestamp-no-timezone",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(
        packet_dir,
        "proof-timestamp-no-timezone",
        overrides={"recordedAt": "2026-06-01T02:30:00"},
    )
    review_snapshot = packet_dir / "phone-review-snapshot.png"
    caption_frame = packet_dir / "phone-caption-safe-zone.png"
    thumbnail_frame = packet_dir / "phone-thumbnail-first-frame.png"
    audio_evidence = packet_dir / "phone-audio-mix-evidence.json"
    _write_png_evidence(review_snapshot, width=390, height=844)
    _write_png_evidence(caption_frame, width=1080, height=1920)
    _write_png_evidence(thumbnail_frame, width=1080, height=1920)
    audio_evidence.write_text(json.dumps({
        "audioDevice": "wired headphones",
        "headphonesUsed": True,
        "bgmVoiceBalancePass": True,
        "voiceoverPolicyPass": True,
        "bgmNonPlaceholderPass": True,
    }), encoding="utf-8")
    (packet_dir / "phone-review.json").write_text(json.dumps({
        "reviewedAt": "2026-06-01T00:20:00",
        "deviceClass": "phone-390x844",
        "deviceViewport": "390x844",
        "reviewerType": "human",
        "reviewerId": "operator-a",
        "reviewMethod": "real-phone-full-watch",
        "audioDevice": "wired headphones",
        "finalVideoPath": str(packet_dir / "proof-timestamp-no-timezone.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "proof-timestamp-no-timezone.mp4"),
        "reviewSnapshotPath": str(review_snapshot),
        "captionSafeZoneFramePath": str(caption_frame),
        "thumbnailFirstFramePath": str(thumbnail_frame),
        "audioMixEvidencePath": str(audio_evidence),
        **_phone_review_evidence_digests(review_snapshot, caption_frame, thumbnail_frame, audio_evidence),
        "watchDurationSeconds": 12.2,
        "headphonesUsed": True,
        "fullWatchCompleted": True,
        "captionSafeZonePass": True,
        "mobileReadabilityPass": True,
        "voiceoverPolicyPass": True,
        "bgmVoiceBalancePass": True,
        "bgmNonPlaceholderPass": True,
        "firstTwoSecondHookPass": True,
        "cutDensityPass": True,
        "aiSlopVisualFitPass": True,
        "stockAiClipFitPass": True,
        "thumbnailFirstFramePass": True,
        "reviewerDecision": "pass",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    fresh_source = payload["goalReadiness"]["freshSourceRepeatability"]
    assert fresh_source["recorded"] is True
    assert fresh_source["ready"] is False
    assert fresh_source["status"] == "fail"
    assert "recordedAt" in fresh_source["failedFields"]
    assert fresh_source["recordedAtCheck"]["ok"] is False
    assert fresh_source["recordedAtCheck"]["timezoneProvided"] is False
    assert "recordedAt must include timezone offset" in fresh_source["recordedAtCheck"]["issues"]
    phone_review = payload["goalReadiness"]["phoneSizedHumanReview"]
    assert phone_review["recorded"] is True
    assert phone_review["ready"] is False
    assert phone_review["status"] == "fail"
    assert "reviewedAt" in phone_review["failedFields"]
    assert phone_review["reviewedAtCheck"]["ok"] is False
    assert phone_review["reviewedAtCheck"]["timezoneProvided"] is False
    assert "reviewedAt must include timezone offset" in phone_review["reviewedAtCheck"]["issues"]
    assert payload["goalReadiness"]["freshSourceBatchProven"] is False
    assert payload["goalReadiness"]["phoneSizedHumanReviewReady"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False
    assert payload["goalReadiness"]["goalComplete"] is False
    assert payload["goalReadiness"]["operatingSystemComplete"] is False


def test_final_video_library_audit_accepts_phone_sized_human_review_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "phone-review-live-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "phone-review-live-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "phone-review-live-proof")
    review_snapshot = packet_dir / "phone-review-snapshot.jpg"
    caption_frame = packet_dir / "phone-caption-safe-zone.jpg"
    thumbnail_frame = packet_dir / "phone-thumbnail-first-frame.jpg"
    audio_evidence = packet_dir / "phone-audio-mix-evidence.json"
    _write_png_evidence(review_snapshot, width=390, height=844)
    _write_png_evidence(caption_frame, width=1080, height=1920)
    _write_png_evidence(thumbnail_frame, width=1080, height=1920)
    audio_evidence.write_text(json.dumps({
        "audioDevice": "wired headphones",
        "headphonesUsed": True,
        "bgmVoiceBalancePass": True,
        "voiceoverPolicyPass": True,
        "bgmNonPlaceholderPass": True,
    }), encoding="utf-8")
    (packet_dir / "phone-review.json").write_text(json.dumps({
        "reviewedAt": "2026-06-01T00:20:00+09:00",
        "deviceClass": "phone-390x844",
        "deviceViewport": "390x844",
        "reviewerType": "human",
        "reviewerId": "operator-a",
        "reviewMethod": "real-phone-full-watch",
        "audioDevice": "wired headphones",
        "finalVideoPath": str(packet_dir / "phone-review-live-proof.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "phone-review-live-proof.mp4"),
        "reviewSnapshotPath": str(review_snapshot),
        "captionSafeZoneFramePath": str(caption_frame),
        "thumbnailFirstFramePath": str(thumbnail_frame),
        "audioMixEvidencePath": str(audio_evidence),
        **_phone_review_evidence_digests(review_snapshot, caption_frame, thumbnail_frame, audio_evidence),
        "watchDurationSeconds": 12.2,
        "headphonesUsed": True,
        "fullWatchCompleted": True,
        "captionSafeZonePass": True,
        "mobileReadabilityPass": True,
        "voiceoverPolicyPass": True,
        "bgmVoiceBalancePass": True,
        "bgmNonPlaceholderPass": True,
        "firstTwoSecondHookPass": True,
        "cutDensityPass": True,
        "aiSlopVisualFitPass": True,
        "stockAiClipFitPass": True,
        "thumbnailFirstFramePass": True,
        "reviewerDecision": "pass",
        "notes": "Full phone-sized pre-upload watch passed.",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    phone_review = payload["goalReadiness"]["phoneSizedHumanReview"]
    assert phone_review["recorded"] is True
    assert phone_review["ready"] is True
    assert phone_review["status"] == "pass"
    assert phone_review["missingFields"] == []
    assert phone_review["failedFields"] == []
    assert phone_review["finalVideoDigestCheck"]["ok"] is True
    assert phone_review["finalVideoDigestCheck"]["actualSha256"] == _sha256_file(packet_dir / "phone-review-live-proof.mp4")
    assert phone_review["reviewedAtCheck"]["ok"] is True
    assert phone_review["reviewedAtCheck"]["timezoneProvided"] is True
    evidence_paths = phone_review["evidenceArtifactPaths"]
    assert evidence_paths["reviewSnapshotPath"].endswith("phone-review-snapshot.jpg")
    assert evidence_paths["captionSafeZoneFramePath"].endswith("phone-caption-safe-zone.jpg")
    assert evidence_paths["thumbnailFirstFramePath"].endswith("phone-thumbnail-first-frame.jpg")
    assert evidence_paths["audioMixEvidencePath"].endswith("phone-audio-mix-evidence.json")
    evidence_checks = phone_review["evidenceArtifactChecks"]
    assert evidence_checks["reviewSnapshotPath"]["ok"] is True
    assert evidence_checks["reviewSnapshotPath"]["width"] == 390
    assert evidence_checks["captionSafeZoneFramePath"]["height"] == 1920
    assert evidence_checks["audioMixEvidencePath"]["kind"] == "audio-mix-json"
    assert evidence_checks["audioMixEvidencePath"]["ok"] is True
    digest_checks = phone_review["evidenceDigestChecks"]
    assert digest_checks["reviewSnapshotSha256"]["ok"] is True
    assert digest_checks["reviewSnapshotSha256"]["actualSha256"] == _sha256_file(review_snapshot)
    assert digest_checks["captionSafeZoneFrameSha256"]["ok"] is True
    assert digest_checks["thumbnailFirstFrameSha256"]["ok"] is True
    assert digest_checks["audioMixEvidenceSha256"]["ok"] is True
    assert phone_review["template"]["reviewerDecision"] == "needs-review"
    assert phone_review["template"]["reviewerType"] == "human"
    assert phone_review["template"]["reviewMethod"] == "real-phone-full-watch"
    assert "watchDurationSeconds" in phone_review["requiredFields"]
    assert "reviewSnapshotPath" in phone_review["requiredFields"]
    assert payload["goalReadiness"]["phoneSizedHumanReviewReady"] is True
    assert payload["goalReadiness"]["preUploadReady"] is True
    assert payload["goalReadiness"]["preUploadDecision"]["status"] == "upload"
    assert payload["goalReadiness"]["preUploadDecision"]["label"] == "업로드 가능"
    assert "platform analytics" in payload["goalReadiness"]["preUploadDecision"]["nextAction"]
    runway_summary = payload["goalReadiness"]["runwayChecklistSummary"]
    assert runway_summary["readyForTodayUpload"] is True
    assert runway_summary["readyForOperatingGoal"] is False
    assert runway_summary["primaryBlockerKey"] == "platform-analytics-loop"
    runway = payload["goalReadiness"]["operatingRunwayChecklist"]
    assert runway[4]["status"] == "pass"
    assert runway[5]["status"] == "missing"
    assert runway[5]["blocksTodayUpload"] is False
    assert payload["goalReadiness"]["goalComplete"] is False
    assert payload["goalReadiness"]["operatingSystemComplete"] is False
    assert any("analytics" in item.lower() for item in payload["goalReadiness"]["remainingGaps"])


def test_final_video_library_audit_rejects_phone_review_evidence_digest_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "phone-review-evidence-digest-mismatch"
    _write_ready_final_video_packet(
        packet_dir,
        "phone-review-evidence-digest-mismatch",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "phone-review-evidence-digest-mismatch")
    review_snapshot = packet_dir / "phone-review-snapshot.png"
    caption_frame = packet_dir / "phone-caption-safe-zone.png"
    thumbnail_frame = packet_dir / "phone-thumbnail-first-frame.png"
    audio_evidence = packet_dir / "phone-audio-mix-evidence.json"
    _write_png_evidence(review_snapshot, width=390, height=844)
    _write_png_evidence(caption_frame, width=1080, height=1920)
    _write_png_evidence(thumbnail_frame, width=1080, height=1920)
    audio_evidence.write_text(json.dumps({
        "audioDevice": "wired headphones",
        "headphonesUsed": True,
        "bgmVoiceBalancePass": True,
        "voiceoverPolicyPass": True,
        "bgmNonPlaceholderPass": True,
    }), encoding="utf-8")
    evidence_digests = _phone_review_evidence_digests(
        review_snapshot,
        caption_frame,
        thumbnail_frame,
        audio_evidence,
    )
    evidence_digests["reviewSnapshotSha256"] = "0" * 64
    (packet_dir / "phone-review.json").write_text(json.dumps({
        "reviewedAt": "2026-06-01T00:20:00+09:00",
        "deviceClass": "phone-390x844",
        "deviceViewport": "390x844",
        "reviewerType": "human",
        "reviewerId": "operator-a",
        "reviewMethod": "real-phone-full-watch",
        "audioDevice": "wired headphones",
        "finalVideoPath": str(packet_dir / "phone-review-evidence-digest-mismatch.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "phone-review-evidence-digest-mismatch.mp4"),
        "reviewSnapshotPath": str(review_snapshot),
        "captionSafeZoneFramePath": str(caption_frame),
        "thumbnailFirstFramePath": str(thumbnail_frame),
        "audioMixEvidencePath": str(audio_evidence),
        **evidence_digests,
        "watchDurationSeconds": 12.2,
        "headphonesUsed": True,
        "fullWatchCompleted": True,
        "captionSafeZonePass": True,
        "mobileReadabilityPass": True,
        "voiceoverPolicyPass": True,
        "bgmVoiceBalancePass": True,
        "bgmNonPlaceholderPass": True,
        "firstTwoSecondHookPass": True,
        "cutDensityPass": True,
        "aiSlopVisualFitPass": True,
        "stockAiClipFitPass": True,
        "thumbnailFirstFramePass": True,
        "reviewerDecision": "pass",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    phone_review = payload["goalReadiness"]["phoneSizedHumanReview"]
    assert phone_review["recorded"] is True
    assert phone_review["ready"] is False
    assert phone_review["status"] == "fail"
    assert "reviewSnapshotSha256" in phone_review["failedFields"]
    assert phone_review["evidenceArtifactChecks"]["reviewSnapshotPath"]["ok"] is True
    assert phone_review["evidenceDigestChecks"]["reviewSnapshotSha256"]["ok"] is False
    assert phone_review["evidenceDigestChecks"]["reviewSnapshotSha256"]["actualSha256"] == _sha256_file(review_snapshot)
    assert "reviewSnapshotSha256 does not match reviewSnapshotPath bytes" in phone_review["evidenceDigestChecks"]["reviewSnapshotSha256"]["issues"]
    assert phone_review["evidenceDigestChecks"]["captionSafeZoneFrameSha256"]["ok"] is True
    assert phone_review["evidenceDigestChecks"]["thumbnailFirstFrameSha256"]["ok"] is True
    assert phone_review["evidenceDigestChecks"]["audioMixEvidenceSha256"]["ok"] is True
    assert payload["goalReadiness"]["phoneSizedHumanReviewReady"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False


def test_final_video_library_audit_rejects_phone_review_desktop_viewport_and_landscape_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "phone-review-desktop-landscape-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "phone-review-desktop-landscape-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "phone-review-desktop-landscape-proof")
    review_snapshot = packet_dir / "phone-review-snapshot.png"
    caption_frame = packet_dir / "phone-caption-safe-zone.png"
    thumbnail_frame = packet_dir / "phone-thumbnail-first-frame.png"
    audio_evidence = packet_dir / "phone-audio-mix-evidence.json"
    _write_png_evidence(review_snapshot, width=1024, height=640)
    _write_png_evidence(caption_frame, width=1920, height=1280)
    _write_png_evidence(thumbnail_frame, width=1920, height=1280)
    audio_evidence.write_text(json.dumps({
        "audioDevice": "wired headphones",
        "headphonesUsed": True,
        "bgmVoiceBalancePass": True,
        "voiceoverPolicyPass": True,
        "bgmNonPlaceholderPass": True,
    }), encoding="utf-8")
    (packet_dir / "phone-review.json").write_text(json.dumps({
        "reviewedAt": "2026-06-01T00:20:00+09:00",
        "deviceClass": "desktop-browser",
        "deviceViewport": "1920x1080",
        "reviewerType": "human",
        "reviewerId": "operator-a",
        "reviewMethod": "real-phone-full-watch",
        "audioDevice": "wired headphones",
        "finalVideoPath": str(packet_dir / "phone-review-desktop-landscape-proof.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "phone-review-desktop-landscape-proof.mp4"),
        "reviewSnapshotPath": str(review_snapshot),
        "captionSafeZoneFramePath": str(caption_frame),
        "thumbnailFirstFramePath": str(thumbnail_frame),
        "audioMixEvidencePath": str(audio_evidence),
        **_phone_review_evidence_digests(review_snapshot, caption_frame, thumbnail_frame, audio_evidence),
        "watchDurationSeconds": 12.2,
        "headphonesUsed": True,
        "fullWatchCompleted": True,
        "captionSafeZonePass": True,
        "mobileReadabilityPass": True,
        "voiceoverPolicyPass": True,
        "bgmVoiceBalancePass": True,
        "bgmNonPlaceholderPass": True,
        "firstTwoSecondHookPass": True,
        "cutDensityPass": True,
        "aiSlopVisualFitPass": True,
        "stockAiClipFitPass": True,
        "thumbnailFirstFramePass": True,
        "reviewerDecision": "pass",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    phone_review = payload["goalReadiness"]["phoneSizedHumanReview"]
    assert phone_review["recorded"] is True
    assert phone_review["ready"] is False
    assert phone_review["status"] == "fail"
    assert "deviceViewport" in phone_review["failedFields"]
    assert "reviewSnapshotPath" in phone_review["failedFields"]
    assert "captionSafeZoneFramePath" in phone_review["failedFields"]
    assert "thumbnailFirstFramePath" in phone_review["failedFields"]
    assert phone_review["deviceViewportCheck"]["ok"] is False
    assert "deviceViewport must be portrait" in phone_review["deviceViewportCheck"]["issues"]
    assert phone_review["evidenceArtifactChecks"]["reviewSnapshotPath"]["ok"] is False
    assert "image evidence must be portrait phone orientation" in phone_review["evidenceArtifactChecks"]["reviewSnapshotPath"]["issues"]
    assert phone_review["evidenceArtifactChecks"]["captionSafeZoneFramePath"]["requirePortrait"] is True
    assert payload["goalReadiness"]["phoneSizedHumanReviewReady"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False


def test_final_video_library_audit_rejects_phone_review_without_review_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "phone-review-missing-artifacts"
    _write_ready_final_video_packet(
        packet_dir,
        "phone-review-missing-artifacts",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "phone-review-missing-artifacts")
    (packet_dir / "phone-review.json").write_text(json.dumps({
        "reviewedAt": "2026-06-01T00:20:00+09:00",
        "deviceClass": "phone-390x844",
        "deviceViewport": "390x844",
        "reviewerType": "human",
        "reviewerId": "operator-a",
        "reviewMethod": "real-phone-full-watch",
        "audioDevice": "wired headphones",
        "finalVideoPath": str(packet_dir / "phone-review-missing-artifacts.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "phone-review-missing-artifacts.mp4"),
        "watchDurationSeconds": 12.2,
        "headphonesUsed": True,
        "fullWatchCompleted": True,
        "captionSafeZonePass": True,
        "mobileReadabilityPass": True,
        "voiceoverPolicyPass": True,
        "bgmVoiceBalancePass": True,
        "bgmNonPlaceholderPass": True,
        "firstTwoSecondHookPass": True,
        "cutDensityPass": True,
        "aiSlopVisualFitPass": True,
        "stockAiClipFitPass": True,
        "thumbnailFirstFramePass": True,
        "reviewerDecision": "pass",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    phone_review = payload["goalReadiness"]["phoneSizedHumanReview"]
    assert phone_review["recorded"] is True
    assert phone_review["ready"] is False
    assert phone_review["status"] == "needs-review"
    assert "reviewSnapshotPath" in phone_review["missingFields"]
    assert "captionSafeZoneFramePath" in phone_review["missingFields"]
    assert "thumbnailFirstFramePath" in phone_review["missingFields"]
    assert "audioMixEvidencePath" in phone_review["missingFields"]
    assert payload["goalReadiness"]["phoneSizedHumanReviewReady"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False


def test_final_video_library_audit_rejects_phone_review_placeholder_review_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "phone-review-placeholder-artifacts"
    _write_ready_final_video_packet(
        packet_dir,
        "phone-review-placeholder-artifacts",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "phone-review-placeholder-artifacts")
    review_snapshot = packet_dir / "phone-review-snapshot.jpg"
    caption_frame = packet_dir / "phone-caption-safe-zone.jpg"
    thumbnail_frame = packet_dir / "phone-thumbnail-first-frame.jpg"
    audio_evidence = packet_dir / "phone-audio-mix-evidence.json"
    review_snapshot.write_bytes(b"placeholder snapshot")
    caption_frame.write_bytes(b"placeholder caption frame")
    thumbnail_frame.write_bytes(b"placeholder thumbnail")
    audio_evidence.write_text(json.dumps({"notes": "placeholder only"}), encoding="utf-8")
    (packet_dir / "phone-review.json").write_text(json.dumps({
        "reviewedAt": "2026-06-01T00:20:00+09:00",
        "deviceClass": "phone-390x844",
        "deviceViewport": "390x844",
        "reviewerType": "human",
        "reviewerId": "operator-a",
        "reviewMethod": "real-phone-full-watch",
        "audioDevice": "wired headphones",
        "finalVideoPath": str(packet_dir / "phone-review-placeholder-artifacts.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "phone-review-placeholder-artifacts.mp4"),
        "reviewSnapshotPath": str(review_snapshot),
        "captionSafeZoneFramePath": str(caption_frame),
        "thumbnailFirstFramePath": str(thumbnail_frame),
        "audioMixEvidencePath": str(audio_evidence),
        **_phone_review_evidence_digests(review_snapshot, caption_frame, thumbnail_frame, audio_evidence),
        "watchDurationSeconds": 12.2,
        "headphonesUsed": True,
        "fullWatchCompleted": True,
        "captionSafeZonePass": True,
        "mobileReadabilityPass": True,
        "voiceoverPolicyPass": True,
        "bgmVoiceBalancePass": True,
        "bgmNonPlaceholderPass": True,
        "firstTwoSecondHookPass": True,
        "cutDensityPass": True,
        "aiSlopVisualFitPass": True,
        "stockAiClipFitPass": True,
        "thumbnailFirstFramePass": True,
        "reviewerDecision": "pass",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    phone_review = payload["goalReadiness"]["phoneSizedHumanReview"]
    assert phone_review["recorded"] is True
    assert phone_review["ready"] is False
    assert phone_review["status"] == "fail"
    assert "reviewSnapshotPath" in phone_review["failedFields"]
    assert "captionSafeZoneFramePath" in phone_review["failedFields"]
    assert "thumbnailFirstFramePath" in phone_review["failedFields"]
    assert "audioMixEvidencePath" in phone_review["failedFields"]
    assert phone_review["evidenceArtifactChecks"]["reviewSnapshotPath"]["ok"] is False
    assert "expected PNG/JPEG image evidence" in phone_review["evidenceArtifactChecks"]["reviewSnapshotPath"]["issues"]
    assert phone_review["evidenceArtifactChecks"]["audioMixEvidencePath"]["ok"] is False
    assert "audio device evidence is missing" in phone_review["evidenceArtifactChecks"]["audioMixEvidencePath"]["issues"]
    assert payload["goalReadiness"]["phoneSizedHumanReviewReady"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False


def test_final_video_library_audit_rejects_phone_review_missing_voiceover_and_clip_fit(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "phone-review-missing-live-quality-fields"
    _write_ready_final_video_packet(
        packet_dir,
        "phone-review-missing-live-quality-fields",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "phone-review-missing-live-quality-fields")
    (packet_dir / "phone-review.json").write_text(json.dumps({
        "reviewedAt": "2026-06-01T00:20:00+09:00",
        "deviceClass": "phone-390x844",
        "finalVideoPath": str(packet_dir / "phone-review-missing-live-quality-fields.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "phone-review-missing-live-quality-fields.mp4"),
        "headphonesUsed": True,
        "fullWatchCompleted": True,
        "captionSafeZonePass": True,
        "mobileReadabilityPass": True,
        "bgmVoiceBalancePass": True,
        "bgmNonPlaceholderPass": True,
        "firstTwoSecondHookPass": True,
        "cutDensityPass": True,
        "aiSlopVisualFitPass": True,
        "thumbnailFirstFramePass": True,
        "reviewerDecision": "pass",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    phone_review = payload["goalReadiness"]["phoneSizedHumanReview"]
    assert phone_review["recorded"] is True
    assert phone_review["ready"] is False
    assert phone_review["status"] == "needs-review"
    assert "reviewerType" in phone_review["missingFields"]
    assert "reviewerId" in phone_review["missingFields"]
    assert "reviewMethod" in phone_review["missingFields"]
    assert "watchDurationSeconds" in phone_review["missingFields"]
    assert "reviewSnapshotPath" in phone_review["missingFields"]
    assert "voiceoverPolicyPass" in phone_review["missingFields"]
    assert "stockAiClipFitPass" in phone_review["missingFields"]
    assert payload["goalReadiness"]["phoneSizedHumanReviewReady"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False


def test_final_video_library_audit_rejects_phone_review_without_human_full_watch(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "phone-review-weak-watch-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "phone-review-weak-watch-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "phone-review-weak-watch-proof")
    (packet_dir / "phone-review.json").write_text(json.dumps({
        "reviewedAt": "2026-06-01T00:20:00+09:00",
        "deviceClass": "phone-390x844",
        "deviceViewport": "390x844",
        "reviewerType": "automation",
        "reviewerId": "auto-smoke",
        "reviewMethod": "screenshot-scan",
        "audioDevice": "none",
        "finalVideoPath": str(packet_dir / "phone-review-weak-watch-proof.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "phone-review-weak-watch-proof.mp4"),
        "watchDurationSeconds": 3.0,
        "headphonesUsed": True,
        "fullWatchCompleted": True,
        "captionSafeZonePass": True,
        "mobileReadabilityPass": True,
        "voiceoverPolicyPass": True,
        "bgmVoiceBalancePass": True,
        "bgmNonPlaceholderPass": True,
        "firstTwoSecondHookPass": True,
        "cutDensityPass": True,
        "aiSlopVisualFitPass": True,
        "stockAiClipFitPass": True,
        "thumbnailFirstFramePass": True,
        "reviewerDecision": "pass",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    phone_review = payload["goalReadiness"]["phoneSizedHumanReview"]
    assert phone_review["recorded"] is True
    assert phone_review["ready"] is False
    assert phone_review["status"] == "fail"
    assert "reviewerType" in phone_review["failedFields"]
    assert "reviewMethod" in phone_review["failedFields"]
    assert "watchDurationSeconds" in phone_review["failedFields"]
    assert payload["goalReadiness"]["phoneSizedHumanReviewReady"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False


def test_final_video_library_audit_rejects_phone_review_for_different_final_video(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "phone-review-mismatch-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "phone-review-mismatch-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "phone-review-mismatch-proof")
    (packet_dir / "phone-review.json").write_text(json.dumps({
        "reviewedAt": "2026-06-01T00:20:00+09:00",
        "deviceClass": "phone-390x844",
        "deviceViewport": "390x844",
        "reviewerType": "human",
        "reviewerId": "operator-a",
        "reviewMethod": "real-phone-full-watch",
        "audioDevice": "wired headphones",
        "finalVideoPath": str(packet_dir / "different-final.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "phone-review-mismatch-proof.mp4"),
        "watchDurationSeconds": 12.2,
        "headphonesUsed": True,
        "fullWatchCompleted": True,
        "captionSafeZonePass": True,
        "mobileReadabilityPass": True,
        "voiceoverPolicyPass": True,
        "bgmVoiceBalancePass": True,
        "bgmNonPlaceholderPass": True,
        "firstTwoSecondHookPass": True,
        "cutDensityPass": True,
        "aiSlopVisualFitPass": True,
        "stockAiClipFitPass": True,
        "thumbnailFirstFramePass": True,
        "reviewerDecision": "pass",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    phone_review = payload["goalReadiness"]["phoneSizedHumanReview"]
    assert phone_review["recorded"] is True
    assert phone_review["ready"] is False
    assert phone_review["status"] == "fail"
    assert "finalVideoPath" in phone_review["failedFields"]
    assert payload["goalReadiness"]["preUploadReady"] is False
    assert payload["goalReadiness"]["preUploadDecision"]["status"] == "edit"


def test_final_video_library_audit_accepts_platform_analytics_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "platform-analytics-live-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "platform-analytics-live-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "platform-analytics-live-proof")
    snapshot_path = packet_dir / "platform-analytics-snapshot.png"
    _write_png_evidence(snapshot_path, width=1280, height=720)
    (packet_dir / "platform-analytics.json").write_text(json.dumps({
        "recordedAt": "2026-06-01T01:10:00+09:00",
        "platform": "youtube_shorts",
        "publishUrl": "https://www.youtube.com/shorts/platform-proof",
        "publishedAt": "2026-06-01T00:10:00+09:00",
        "metricSource": "YouTube Studio manual snapshot",
        "analyticsSnapshotPath": str(snapshot_path),
        "analyticsSnapshotSha256": _sha256_file(snapshot_path),
        "finalVideoPath": str(packet_dir / "platform-analytics-live-proof.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "platform-analytics-live-proof.mp4"),
        "sampleWindowHours": 1,
        "views": 128,
        "twoSecondHoldRate": 0.73,
        "fiveSecondHoldRate": 0.52,
        "averageViewDurationSeconds": 9.4,
        "rewatchRate": 0.08,
        "swipeAwayRate": 0.38,
        "decision": "iterate",
        "nextImprovementAction": "Test a stronger first-frame hook and shorter title on the next upload.",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    analytics = payload["goalReadiness"]["platformAnalytics"]
    assert analytics["recorded"] is True
    assert analytics["ready"] is True
    assert analytics["status"] == "recorded"
    assert analytics["missingFields"] == []
    assert analytics["failedFields"] == []
    assert analytics["finalVideoDigestCheck"]["ok"] is True
    assert analytics["finalVideoDigestCheck"]["actualSha256"] == _sha256_file(packet_dir / "platform-analytics-live-proof.mp4")
    assert analytics["evidenceArtifactPaths"]["analyticsSnapshotPath"].endswith("platform-analytics-snapshot.png")
    assert analytics["evidenceArtifactChecks"]["analyticsSnapshotPath"]["ok"] is True
    assert analytics["evidenceArtifactChecks"]["analyticsSnapshotPath"]["width"] == 1280
    assert analytics["snapshotDigestCheck"]["ok"] is True
    assert analytics["snapshotDigestCheck"]["actualSha256"] == _sha256_file(snapshot_path)
    assert analytics["sampleWindowCheck"]["ok"] is True
    assert analytics["sampleWindowCheck"]["timezoneProvided"]["recordedAt"] is True
    assert analytics["sampleWindowCheck"]["timezoneProvided"]["publishedAt"] is True
    assert analytics["nextImprovementActionCheck"]["ok"] is True
    assert analytics["template"]["analyticsSnapshotPath"].endswith("platform-analytics-snapshot.png")
    assert analytics["template"]["decision"] == "missing"
    assert payload["goalReadiness"]["platformAnalyticsRecorded"] is True
    assert payload["goalReadiness"]["preUploadReady"] is False
    assert payload["goalReadiness"]["preUploadDecision"]["status"] == "edit"
    assert "phone-sized human review" in payload["goalReadiness"]["preUploadDecision"]["detail"]
    assert payload["goalReadiness"]["goalComplete"] is False
    assert payload["goalReadiness"]["operatingSystemComplete"] is False
    assert any("phone-sized" in item.lower() for item in payload["goalReadiness"]["remainingGaps"])


def test_final_video_library_audit_rejects_platform_analytics_before_sample_window_elapsed(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "platform-analytics-premature-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "platform-analytics-premature-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "platform-analytics-premature-proof")
    snapshot_path = packet_dir / "platform-analytics-snapshot.png"
    _write_png_evidence(snapshot_path, width=1280, height=720)
    (packet_dir / "platform-analytics.json").write_text(json.dumps({
        "recordedAt": "2026-06-01T00:40:00+09:00",
        "platform": "youtube_shorts",
        "publishUrl": "https://www.youtube.com/shorts/platform-proof",
        "publishedAt": "2026-06-01T00:10:00+09:00",
        "metricSource": "YouTube Studio manual snapshot",
        "analyticsSnapshotPath": str(snapshot_path),
        "analyticsSnapshotSha256": _sha256_file(snapshot_path),
        "finalVideoPath": str(packet_dir / "platform-analytics-premature-proof.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "platform-analytics-premature-proof.mp4"),
        "sampleWindowHours": 1,
        "views": 128,
        "twoSecondHoldRate": 0.73,
        "fiveSecondHoldRate": 0.52,
        "averageViewDurationSeconds": 9.4,
        "rewatchRate": 0.08,
        "swipeAwayRate": 0.38,
        "decision": "iterate",
        "nextImprovementAction": "Test a stronger first-frame hook and shorter title on the next upload.",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    analytics = payload["goalReadiness"]["platformAnalytics"]
    assert analytics["recorded"] is True
    assert analytics["ready"] is False
    assert analytics["status"] == "fail"
    assert "recordedAt" in analytics["failedFields"]
    assert analytics["sampleWindowCheck"]["ok"] is False
    assert "recordedAt is before the declared platform sample window has elapsed" in analytics["sampleWindowCheck"]["issues"]
    assert analytics["evidenceArtifactChecks"]["analyticsSnapshotPath"]["ok"] is True
    assert payload["goalReadiness"]["platformAnalyticsRecorded"] is False
    assert payload["goalReadiness"]["goalComplete"] is False


def test_final_video_library_audit_rejects_platform_analytics_without_timezone_offsets(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "platform-analytics-no-timezone"
    _write_ready_final_video_packet(
        packet_dir,
        "platform-analytics-no-timezone",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "platform-analytics-no-timezone")
    snapshot_path = packet_dir / "platform-analytics-snapshot.png"
    _write_png_evidence(snapshot_path, width=1280, height=720)
    (packet_dir / "platform-analytics.json").write_text(json.dumps({
        "recordedAt": "2026-06-01T01:10:00",
        "platform": "youtube_shorts",
        "publishUrl": "https://www.youtube.com/shorts/platform-proof",
        "publishedAt": "2026-06-01T00:10:00",
        "metricSource": "YouTube Studio manual snapshot",
        "analyticsSnapshotPath": str(snapshot_path),
        "analyticsSnapshotSha256": _sha256_file(snapshot_path),
        "finalVideoPath": str(packet_dir / "platform-analytics-no-timezone.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "platform-analytics-no-timezone.mp4"),
        "sampleWindowHours": 1,
        "views": 128,
        "twoSecondHoldRate": 0.73,
        "fiveSecondHoldRate": 0.52,
        "averageViewDurationSeconds": 9.4,
        "rewatchRate": 0.08,
        "swipeAwayRate": 0.38,
        "decision": "iterate",
        "nextImprovementAction": "Test a stronger first-frame hook and shorter title on the next upload.",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    analytics = payload["goalReadiness"]["platformAnalytics"]
    assert analytics["recorded"] is True
    assert analytics["ready"] is False
    assert analytics["status"] == "fail"
    assert "recordedAt" in analytics["failedFields"]
    assert "publishedAt" in analytics["failedFields"]
    assert analytics["sampleWindowCheck"]["ok"] is False
    assert analytics["sampleWindowCheck"]["timezoneRequired"] is True
    assert analytics["sampleWindowCheck"]["timezoneProvided"]["recordedAt"] is False
    assert analytics["sampleWindowCheck"]["timezoneProvided"]["publishedAt"] is False
    assert "recordedAt must include timezone offset" in analytics["sampleWindowCheck"]["issues"]
    assert "publishedAt must include timezone offset" in analytics["sampleWindowCheck"]["issues"]
    assert analytics["evidenceArtifactChecks"]["analyticsSnapshotPath"]["ok"] is True
    assert analytics["snapshotDigestCheck"]["ok"] is True
    assert analytics["nextImprovementActionCheck"]["ok"] is True
    assert payload["goalReadiness"]["platformAnalyticsRecorded"] is False
    assert payload["goalReadiness"]["goalComplete"] is False
    assert payload["goalReadiness"]["operatingSystemComplete"] is False


def test_final_video_library_audit_rejects_platform_analytics_generic_next_action(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "platform-analytics-generic-next-action"
    _write_ready_final_video_packet(
        packet_dir,
        "platform-analytics-generic-next-action",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "platform-analytics-generic-next-action")
    snapshot_path = packet_dir / "platform-analytics-snapshot.png"
    _write_png_evidence(snapshot_path, width=1280, height=720)
    (packet_dir / "platform-analytics.json").write_text(json.dumps({
        "recordedAt": "2026-06-01T01:10:00+09:00",
        "platform": "youtube_shorts",
        "publishUrl": "https://www.youtube.com/shorts/platform-proof",
        "publishedAt": "2026-06-01T00:10:00+09:00",
        "metricSource": "YouTube Studio manual snapshot",
        "analyticsSnapshotPath": str(snapshot_path),
        "analyticsSnapshotSha256": _sha256_file(snapshot_path),
        "finalVideoPath": str(packet_dir / "platform-analytics-generic-next-action.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "platform-analytics-generic-next-action.mp4"),
        "sampleWindowHours": 1,
        "views": 128,
        "twoSecondHoldRate": 0.73,
        "fiveSecondHoldRate": 0.52,
        "averageViewDurationSeconds": 9.4,
        "rewatchRate": 0.08,
        "swipeAwayRate": 0.38,
        "decision": "iterate",
        "nextImprovementAction": "OK",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    analytics = payload["goalReadiness"]["platformAnalytics"]
    assert analytics["recorded"] is True
    assert analytics["ready"] is False
    assert analytics["status"] == "fail"
    assert "nextImprovementAction" in analytics["failedFields"]
    assert analytics["nextImprovementActionCheck"]["ok"] is False
    assert "nextImprovementAction is too generic for a platform learning loop" in analytics["nextImprovementActionCheck"]["issues"]
    assert "nextImprovementAction must name a metric or creative lever to test" in analytics["nextImprovementActionCheck"]["issues"]
    assert analytics["sampleWindowCheck"]["ok"] is True
    assert analytics["evidenceArtifactChecks"]["analyticsSnapshotPath"]["ok"] is True
    assert payload["goalReadiness"]["platformAnalyticsRecorded"] is False
    assert payload["goalReadiness"]["goalComplete"] is False


def test_final_video_library_audit_rejects_platform_analytics_snapshot_digest_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "platform-analytics-digest-mismatch"
    _write_ready_final_video_packet(
        packet_dir,
        "platform-analytics-digest-mismatch",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "platform-analytics-digest-mismatch")
    snapshot_path = packet_dir / "platform-analytics-snapshot.png"
    _write_png_evidence(snapshot_path, width=1280, height=720)
    (packet_dir / "platform-analytics.json").write_text(json.dumps({
        "recordedAt": "2026-06-01T01:10:00+09:00",
        "platform": "youtube_shorts",
        "publishUrl": "https://www.youtube.com/shorts/platform-proof",
        "publishedAt": "2026-06-01T00:10:00+09:00",
        "metricSource": "YouTube Studio manual snapshot",
        "analyticsSnapshotPath": str(snapshot_path),
        "analyticsSnapshotSha256": "0" * 64,
        "finalVideoPath": str(packet_dir / "platform-analytics-digest-mismatch.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "platform-analytics-digest-mismatch.mp4"),
        "sampleWindowHours": 1,
        "views": 128,
        "twoSecondHoldRate": 0.73,
        "fiveSecondHoldRate": 0.52,
        "averageViewDurationSeconds": 9.4,
        "rewatchRate": 0.08,
        "swipeAwayRate": 0.38,
        "decision": "iterate",
        "nextImprovementAction": "Test a stronger first-frame hook and shorter title on the next upload.",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    analytics = payload["goalReadiness"]["platformAnalytics"]
    assert analytics["recorded"] is True
    assert analytics["ready"] is False
    assert analytics["status"] == "fail"
    assert "analyticsSnapshotSha256" in analytics["failedFields"]
    assert analytics["snapshotDigestCheck"]["ok"] is False
    assert analytics["snapshotDigestCheck"]["actualSha256"] == _sha256_file(snapshot_path)
    assert "analyticsSnapshotSha256 does not match analyticsSnapshotPath bytes" in analytics["snapshotDigestCheck"]["issues"]
    assert analytics["sampleWindowCheck"]["ok"] is True
    assert analytics["nextImprovementActionCheck"]["ok"] is True
    assert analytics["evidenceArtifactChecks"]["analyticsSnapshotPath"]["ok"] is True
    assert payload["goalReadiness"]["platformAnalyticsRecorded"] is False
    assert payload["goalReadiness"]["goalComplete"] is False


def test_final_video_library_audit_rejects_copied_goal_proof_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "copied-template-live-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "copied-template-live-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(
        packet_dir,
        "copied-template-live-proof",
        overrides={
            "templateOnly": True,
            "doNotSubmitAsProof": True,
            "targetProofArtifactPath": str(packet_dir / "fresh-source-proof.json"),
        },
    )
    review_snapshot = packet_dir / "phone-review-snapshot.png"
    caption_frame = packet_dir / "phone-caption-safe-zone.png"
    thumbnail_frame = packet_dir / "phone-thumbnail-first-frame.png"
    audio_evidence = packet_dir / "phone-audio-mix-evidence.json"
    analytics_snapshot = packet_dir / "platform-analytics-snapshot.png"
    _write_png_evidence(review_snapshot, width=390, height=844)
    _write_png_evidence(caption_frame, width=1080, height=1920)
    _write_png_evidence(thumbnail_frame, width=1080, height=1920)
    _write_png_evidence(analytics_snapshot, width=1280, height=720)
    audio_evidence.write_text(json.dumps({
        "audioDevice": "wired headphones",
        "headphonesUsed": True,
        "bgmVoiceBalancePass": True,
        "voiceoverPolicyPass": True,
        "bgmNonPlaceholderPass": True,
    }), encoding="utf-8")
    (packet_dir / "phone-review.json").write_text(json.dumps({
        "reviewedAt": "2026-06-01T00:20:00+09:00",
        "deviceClass": "phone-390x844",
        "deviceViewport": "390x844",
        "reviewerType": "human",
        "reviewerId": "operator-a",
        "reviewMethod": "real-phone-full-watch",
        "audioDevice": "wired headphones",
        "finalVideoPath": str(packet_dir / "copied-template-live-proof.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "copied-template-live-proof.mp4"),
        "reviewSnapshotPath": str(review_snapshot),
        "captionSafeZoneFramePath": str(caption_frame),
        "thumbnailFirstFramePath": str(thumbnail_frame),
        "audioMixEvidencePath": str(audio_evidence),
        **_phone_review_evidence_digests(review_snapshot, caption_frame, thumbnail_frame, audio_evidence),
        "watchDurationSeconds": 12.2,
        "headphonesUsed": True,
        "fullWatchCompleted": True,
        "captionSafeZonePass": True,
        "mobileReadabilityPass": True,
        "voiceoverPolicyPass": True,
        "bgmVoiceBalancePass": True,
        "bgmNonPlaceholderPass": True,
        "firstTwoSecondHookPass": True,
        "cutDensityPass": True,
        "aiSlopVisualFitPass": True,
        "stockAiClipFitPass": True,
        "thumbnailFirstFramePass": True,
        "reviewerDecision": "pass",
        "templateOnly": True,
        "doNotSubmitAsProof": True,
        "targetProofArtifactPath": str(packet_dir / "phone-review.json"),
    }), encoding="utf-8")
    (packet_dir / "platform-analytics.json").write_text(json.dumps({
        "recordedAt": "2026-06-01T01:10:00+09:00",
        "platform": "youtube_shorts",
        "publishUrl": "https://www.youtube.com/shorts/copied-template-proof",
        "publishedAt": "2026-06-01T00:10:00+09:00",
        "metricSource": "YouTube Studio manual snapshot",
        "analyticsSnapshotPath": str(analytics_snapshot),
        "analyticsSnapshotSha256": _sha256_file(analytics_snapshot),
        "finalVideoPath": str(packet_dir / "copied-template-live-proof.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "copied-template-live-proof.mp4"),
        "sampleWindowHours": 1,
        "views": 128,
        "twoSecondHoldRate": 0.73,
        "fiveSecondHoldRate": 0.52,
        "averageViewDurationSeconds": 9.4,
        "rewatchRate": 0.08,
        "swipeAwayRate": 0.38,
        "decision": "iterate",
        "nextImprovementAction": "Test a stronger first-frame hook and shorter title on the next upload.",
        "templateOnly": True,
        "doNotSubmitAsProof": True,
        "targetProofArtifactPath": str(packet_dir / "platform-analytics.json"),
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    for proof_key in ("freshSourceRepeatability", "phoneSizedHumanReview", "platformAnalytics"):
        proof = payload["goalReadiness"][proof_key]
        assert proof["recorded"] is True
        assert proof["ready"] is False
        assert proof["status"] == "fail"
        assert "templateOnly" in proof["failedFields"]
        assert "doNotSubmitAsProof" in proof["failedFields"]
        assert "targetProofArtifactPath" in proof["failedFields"]
    assert payload["goalReadiness"]["freshSourceBatchProven"] is False
    assert payload["goalReadiness"]["phoneSizedHumanReviewReady"] is False
    assert payload["goalReadiness"]["platformAnalyticsRecorded"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False
    assert payload["goalReadiness"]["goalComplete"] is False
    assert payload["goalReadiness"]["operatingSystemComplete"] is False


def test_final_video_library_audit_rejects_goal_proofs_for_replaced_final_video_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "replaced-final-video-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "replaced-final-video-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    stale_digest = "0" * 64
    _write_fresh_source_proof(
        packet_dir,
        "replaced-final-video-proof",
        overrides={"finalVideoSha256": stale_digest},
    )
    review_snapshot = packet_dir / "phone-review-snapshot.png"
    caption_frame = packet_dir / "phone-caption-safe-zone.png"
    thumbnail_frame = packet_dir / "phone-thumbnail-first-frame.png"
    audio_evidence = packet_dir / "phone-audio-mix-evidence.json"
    analytics_snapshot = packet_dir / "platform-analytics-snapshot.png"
    _write_png_evidence(review_snapshot, width=390, height=844)
    _write_png_evidence(caption_frame, width=1080, height=1920)
    _write_png_evidence(thumbnail_frame, width=1080, height=1920)
    _write_png_evidence(analytics_snapshot, width=1280, height=720)
    audio_evidence.write_text(json.dumps({
        "audioDevice": "wired headphones",
        "headphonesUsed": True,
        "bgmVoiceBalancePass": True,
        "voiceoverPolicyPass": True,
        "bgmNonPlaceholderPass": True,
    }), encoding="utf-8")
    (packet_dir / "phone-review.json").write_text(json.dumps({
        "reviewedAt": "2026-06-01T00:20:00+09:00",
        "deviceClass": "phone-390x844",
        "deviceViewport": "390x844",
        "reviewerType": "human",
        "reviewerId": "operator-a",
        "reviewMethod": "real-phone-full-watch",
        "audioDevice": "wired headphones",
        "finalVideoPath": str(packet_dir / "replaced-final-video-proof.mp4"),
        "finalVideoSha256": stale_digest,
        "reviewSnapshotPath": str(review_snapshot),
        "captionSafeZoneFramePath": str(caption_frame),
        "thumbnailFirstFramePath": str(thumbnail_frame),
        "audioMixEvidencePath": str(audio_evidence),
        **_phone_review_evidence_digests(review_snapshot, caption_frame, thumbnail_frame, audio_evidence),
        "watchDurationSeconds": 12.2,
        "headphonesUsed": True,
        "fullWatchCompleted": True,
        "captionSafeZonePass": True,
        "mobileReadabilityPass": True,
        "voiceoverPolicyPass": True,
        "bgmVoiceBalancePass": True,
        "bgmNonPlaceholderPass": True,
        "firstTwoSecondHookPass": True,
        "cutDensityPass": True,
        "aiSlopVisualFitPass": True,
        "stockAiClipFitPass": True,
        "thumbnailFirstFramePass": True,
        "reviewerDecision": "pass",
    }), encoding="utf-8")
    (packet_dir / "platform-analytics.json").write_text(json.dumps({
        "recordedAt": "2026-06-01T01:10:00+09:00",
        "platform": "youtube_shorts",
        "publishUrl": "https://www.youtube.com/shorts/replaced-final-video-proof",
        "publishedAt": "2026-06-01T00:10:00+09:00",
        "metricSource": "YouTube Studio manual snapshot",
        "analyticsSnapshotPath": str(analytics_snapshot),
        "analyticsSnapshotSha256": _sha256_file(analytics_snapshot),
        "finalVideoPath": str(packet_dir / "replaced-final-video-proof.mp4"),
        "finalVideoSha256": stale_digest,
        "sampleWindowHours": 1,
        "views": 128,
        "twoSecondHoldRate": 0.73,
        "fiveSecondHoldRate": 0.52,
        "averageViewDurationSeconds": 9.4,
        "rewatchRate": 0.08,
        "swipeAwayRate": 0.38,
        "decision": "iterate",
        "nextImprovementAction": "Test a stronger first-frame hook and shorter title on the next upload.",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    actual_digest = _sha256_file(packet_dir / "replaced-final-video-proof.mp4")
    for proof_key in ("freshSourceRepeatability", "phoneSizedHumanReview", "platformAnalytics"):
        proof = payload["goalReadiness"][proof_key]
        assert proof["recorded"] is True
        assert proof["ready"] is False
        assert proof["status"] == "fail"
        assert "finalVideoSha256" in proof["failedFields"]
        assert proof["finalVideoDigestCheck"]["ok"] is False
        assert proof["finalVideoDigestCheck"]["actualSha256"] == actual_digest
        assert "finalVideoSha256 does not match finalVideoPath bytes" in proof["finalVideoDigestCheck"]["issues"]
    assert payload["goalReadiness"]["freshSourceBatchProven"] is False
    assert payload["goalReadiness"]["phoneSizedHumanReviewReady"] is False
    assert payload["goalReadiness"]["platformAnalyticsRecorded"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False
    assert payload["goalReadiness"]["goalComplete"] is False
    assert payload["goalReadiness"]["operatingSystemComplete"] is False


def test_final_video_library_audit_rejects_goal_evidence_paths_from_other_packet(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "cross-packet-evidence-target"
    donor_dir = final_root / "cross-packet-evidence-donor"
    _write_ready_final_video_packet(
        packet_dir,
        "cross-packet-evidence-target",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    donor_dir.mkdir(parents=True)
    donor_handoff = donor_dir / "borrowed-handoff.json"
    donor_review = donor_dir / "borrowed-source-review.json"
    donor_handoff.write_text(json.dumps({
        "projectId": "fresh-proof-handoff",
        "scenes": ["scene-01", "scene-02", "scene-03", "scene-04", "scene-05"],
    }), encoding="utf-8")
    donor_review.write_text(json.dumps({
        "status": "accepted",
        "acceptedSceneCount": 5,
        "rejectedSceneCount": 0,
    }), encoding="utf-8")
    _write_fresh_source_proof(
        packet_dir,
        "cross-packet-evidence-target",
        overrides={
            "handoffManifestPath": str(donor_handoff),
            "sourceReviewPath": str(donor_review),
        },
    )
    review_snapshot = donor_dir / "phone-review-snapshot.png"
    caption_frame = donor_dir / "phone-caption-safe-zone.png"
    thumbnail_frame = donor_dir / "phone-thumbnail-first-frame.png"
    audio_evidence = donor_dir / "phone-audio-mix-evidence.json"
    analytics_snapshot = donor_dir / "platform-analytics-snapshot.png"
    _write_png_evidence(review_snapshot, width=390, height=844)
    _write_png_evidence(caption_frame, width=1080, height=1920)
    _write_png_evidence(thumbnail_frame, width=1080, height=1920)
    _write_png_evidence(analytics_snapshot, width=1280, height=720)
    audio_evidence.write_text(json.dumps({
        "audioDevice": "wired headphones",
        "headphonesUsed": True,
        "bgmVoiceBalancePass": True,
        "voiceoverPolicyPass": True,
        "bgmNonPlaceholderPass": True,
    }), encoding="utf-8")
    (packet_dir / "phone-review.json").write_text(json.dumps({
        "reviewedAt": "2026-06-01T00:20:00+09:00",
        "deviceClass": "phone-390x844",
        "deviceViewport": "390x844",
        "reviewerType": "human",
        "reviewerId": "operator-a",
        "reviewMethod": "real-phone-full-watch",
        "audioDevice": "wired headphones",
        "finalVideoPath": str(packet_dir / "cross-packet-evidence-target.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "cross-packet-evidence-target.mp4"),
        "reviewSnapshotPath": str(review_snapshot),
        "captionSafeZoneFramePath": str(caption_frame),
        "thumbnailFirstFramePath": str(thumbnail_frame),
        "audioMixEvidencePath": str(audio_evidence),
        **_phone_review_evidence_digests(review_snapshot, caption_frame, thumbnail_frame, audio_evidence),
        "watchDurationSeconds": 12.2,
        "headphonesUsed": True,
        "fullWatchCompleted": True,
        "captionSafeZonePass": True,
        "mobileReadabilityPass": True,
        "voiceoverPolicyPass": True,
        "bgmVoiceBalancePass": True,
        "bgmNonPlaceholderPass": True,
        "firstTwoSecondHookPass": True,
        "cutDensityPass": True,
        "aiSlopVisualFitPass": True,
        "stockAiClipFitPass": True,
        "thumbnailFirstFramePass": True,
        "reviewerDecision": "pass",
    }), encoding="utf-8")
    (packet_dir / "platform-analytics.json").write_text(json.dumps({
        "recordedAt": "2026-06-01T01:10:00+09:00",
        "platform": "youtube_shorts",
        "publishUrl": "https://www.youtube.com/shorts/cross-packet-evidence-target",
        "publishedAt": "2026-06-01T00:10:00+09:00",
        "metricSource": "YouTube Studio manual snapshot",
        "analyticsSnapshotPath": str(analytics_snapshot),
        "analyticsSnapshotSha256": _sha256_file(analytics_snapshot),
        "finalVideoPath": str(packet_dir / "cross-packet-evidence-target.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "cross-packet-evidence-target.mp4"),
        "sampleWindowHours": 1,
        "views": 128,
        "twoSecondHoldRate": 0.73,
        "fiveSecondHoldRate": 0.52,
        "averageViewDurationSeconds": 9.4,
        "rewatchRate": 0.08,
        "swipeAwayRate": 0.38,
        "decision": "iterate",
        "nextImprovementAction": "Test a stronger first-frame hook and shorter title on the next upload.",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    fresh_source = payload["goalReadiness"]["freshSourceRepeatability"]
    assert fresh_source["recorded"] is True
    assert fresh_source["ready"] is False
    assert fresh_source["status"] == "fail"
    assert "handoffManifestPath" in fresh_source["failedFields"]
    assert "sourceReviewPath" in fresh_source["failedFields"]
    assert "outside the current final-video packet" in fresh_source["evidenceArtifactChecks"]["handoffManifestPath"]["issues"][0]
    phone_review = payload["goalReadiness"]["phoneSizedHumanReview"]
    assert phone_review["recorded"] is True
    assert phone_review["ready"] is False
    assert phone_review["status"] == "fail"
    for field in ("reviewSnapshotPath", "captionSafeZoneFramePath", "thumbnailFirstFramePath", "audioMixEvidencePath"):
        assert field in phone_review["failedFields"]
        assert "outside the current final-video packet" in phone_review["evidenceArtifactChecks"][field]["issues"][0]
    analytics = payload["goalReadiness"]["platformAnalytics"]
    assert analytics["recorded"] is True
    assert analytics["ready"] is False
    assert analytics["status"] == "fail"
    assert "analyticsSnapshotPath" in analytics["failedFields"]
    assert "analyticsSnapshotSha256" in analytics["failedFields"]
    assert "outside the current final-video packet" in analytics["evidenceArtifactChecks"]["analyticsSnapshotPath"]["issues"][0]
    assert analytics["snapshotDigestCheck"]["ok"] is False
    assert payload["goalReadiness"]["freshSourceBatchProven"] is False
    assert payload["goalReadiness"]["phoneSizedHumanReviewReady"] is False
    assert payload["goalReadiness"]["platformAnalyticsRecorded"] is False
    assert payload["goalReadiness"]["preUploadReady"] is False
    assert payload["goalReadiness"]["goalComplete"] is False
    assert payload["goalReadiness"]["operatingSystemComplete"] is False


def test_final_video_library_audit_rejects_weak_platform_analytics_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "platform-analytics-weak-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "platform-analytics-weak-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "platform-analytics-weak-proof")
    (packet_dir / "platform-analytics.json").write_text(json.dumps({
        "recordedAt": "2026-06-01T01:10:00+09:00",
        "platform": "youtube_shorts",
        "publishUrl": "https://example.com/not-a-short",
        "publishedAt": "2026-06-01T00:10:00+09:00",
        "metricSource": "manual text only",
        "analyticsSnapshotPath": str(packet_dir / "missing-snapshot.png"),
        "finalVideoPath": str(packet_dir / "platform-analytics-weak-proof.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "platform-analytics-weak-proof.mp4"),
        "sampleWindowHours": 1,
        "views": 0,
        "twoSecondHoldRate": 1.2,
        "fiveSecondHoldRate": 0.52,
        "averageViewDurationSeconds": 18.5,
        "rewatchRate": -0.1,
        "swipeAwayRate": 0.38,
        "decision": "iterate",
        "nextImprovementAction": "Try another hook.",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    analytics = payload["goalReadiness"]["platformAnalytics"]
    assert analytics["recorded"] is True
    assert analytics["ready"] is False
    assert analytics["status"] == "fail"
    assert "publishUrl" in analytics["failedFields"]
    assert "analyticsSnapshotPath" in analytics["failedFields"]
    assert "views" in analytics["failedFields"]
    assert "twoSecondHoldRate" in analytics["failedFields"]
    assert "averageViewDurationSeconds" in analytics["failedFields"]
    assert "rewatchRate" in analytics["failedFields"]
    assert payload["goalReadiness"]["platformAnalyticsRecorded"] is False


def test_final_video_library_audit_rejects_platform_analytics_placeholder_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "platform-analytics-placeholder-snapshot"
    _write_ready_final_video_packet(
        packet_dir,
        "platform-analytics-placeholder-snapshot",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "platform-analytics-placeholder-snapshot")
    snapshot_path = packet_dir / "platform-analytics-snapshot.png"
    snapshot_path.write_bytes(b"placeholder analytics screenshot")
    (packet_dir / "platform-analytics.json").write_text(json.dumps({
        "recordedAt": "2026-06-01T01:10:00+09:00",
        "platform": "youtube_shorts",
        "publishUrl": "https://www.youtube.com/shorts/platform-proof",
        "publishedAt": "2026-06-01T00:10:00+09:00",
        "metricSource": "YouTube Studio manual snapshot",
        "analyticsSnapshotPath": str(snapshot_path),
        "analyticsSnapshotSha256": _sha256_file(snapshot_path),
        "finalVideoPath": str(packet_dir / "platform-analytics-placeholder-snapshot.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "platform-analytics-placeholder-snapshot.mp4"),
        "sampleWindowHours": 1,
        "views": 128,
        "twoSecondHoldRate": 0.73,
        "fiveSecondHoldRate": 0.52,
        "averageViewDurationSeconds": 9.4,
        "rewatchRate": 0.08,
        "swipeAwayRate": 0.38,
        "decision": "iterate",
        "nextImprovementAction": "Test a stronger first-frame hook and shorter title on the next upload.",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    analytics = payload["goalReadiness"]["platformAnalytics"]
    assert analytics["recorded"] is True
    assert analytics["ready"] is False
    assert analytics["status"] == "fail"
    assert "analyticsSnapshotPath" in analytics["failedFields"]
    assert analytics["evidenceArtifactChecks"]["analyticsSnapshotPath"]["ok"] is False
    assert "expected PNG/JPEG image evidence" in analytics["evidenceArtifactChecks"]["analyticsSnapshotPath"]["issues"]
    assert payload["goalReadiness"]["platformAnalyticsRecorded"] is False
    assert payload["goalReadiness"]["goalComplete"] is False


def test_final_video_library_audit_rejects_platform_analytics_for_different_final_video(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "platform-analytics-mismatch-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "platform-analytics-mismatch-proof",
        {
            "liveSignedInGrokDirectImportProof": True,
            "freshGrokBatchProof": True,
        },
    )
    _write_fresh_source_proof(packet_dir, "platform-analytics-mismatch-proof")
    snapshot_path = packet_dir / "platform-analytics-snapshot.png"
    _write_png_evidence(snapshot_path, width=1280, height=720)
    (packet_dir / "platform-analytics.json").write_text(json.dumps({
        "recordedAt": "2026-06-01T01:10:00+09:00",
        "platform": "youtube_shorts",
        "publishUrl": "https://www.youtube.com/shorts/platform-proof",
        "publishedAt": "2026-06-01T00:10:00+09:00",
        "metricSource": "YouTube Studio manual snapshot",
        "analyticsSnapshotPath": str(snapshot_path),
        "analyticsSnapshotSha256": _sha256_file(snapshot_path),
        "finalVideoPath": str(packet_dir / "different-final.mp4"),
        "finalVideoSha256": _sha256_file(packet_dir / "platform-analytics-mismatch-proof.mp4"),
        "sampleWindowHours": 1,
        "views": 128,
        "twoSecondHoldRate": 0.73,
        "fiveSecondHoldRate": 0.52,
        "averageViewDurationSeconds": 9.4,
        "rewatchRate": 0.08,
        "swipeAwayRate": 0.38,
        "decision": "iterate",
        "nextImprovementAction": "Test a stronger first-frame hook and shorter title on the next upload.",
    }), encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    analytics = payload["goalReadiness"]["platformAnalytics"]
    assert analytics["recorded"] is True
    assert analytics["ready"] is False
    assert analytics["status"] == "fail"
    assert "finalVideoPath" in analytics["failedFields"]
    assert payload["goalReadiness"]["platformAnalyticsRecorded"] is False


def test_final_video_library_audit_accepts_paired_handoff_direct_import_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "handoff-log-live-proof"
    handoff_id = "handoff-log-live-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "handoff-log-live-proof",
        {
            "grokHandoffProjectId": handoff_id,
            "grokHandoffSceneIds": ["scene-01"],
        },
    )
    handoff_dir = tmp_path / "storage" / "grok-handoffs" / handoff_id
    incoming = handoff_dir / "incoming"
    incoming.mkdir(parents=True)
    imported_mp4 = incoming / "scene-01.grok.mp4"
    imported_mp4.write_bytes(b"direct bookmarklet mp4 bytes")
    (handoff_dir / "handoff.json").write_text(json.dumps({
        "projectId": handoff_id,
        "importHistory": [
            {
                "importedAt": "2026-05-29T12:01:00",
                "downloadDir": "",
                "sceneId": "scene-01",
                "importMode": "manual-browser-upload",
                "uploadedFileName": "scene-01.grok.mp4",
                "imported": [
                    {
                        "sceneId": "scene-01",
                        "expectedFileName": "scene-01.grok.mp4",
                        "fileName": "scene-01.grok.mp4",
                        "sourcePath": "storage/grok-handoffs/handoff-log-live-proof/incoming/scene-01.grok.mp4",
                        "originalPath": "browser-upload:scene-01.grok.mp4",
                        "importMode": "manual-browser-upload",
                    }
                ],
            }
        ],
    }), encoding="utf-8")

    (handoff_dir / "extension-events.jsonl").write_text(json.dumps({
        "updatedAt": "2026-05-29T12:01:01",
        "projectId": handoff_id,
        "sceneId": "scene-01",
        "expectedFileName": "scene-01.grok.mp4",
        "eventType": "bookmarklet-direct-import",
        "status": "imported",
        "sourceKind": "bookmarklet-blob-direct-fetch",
        "qualityNote": "visible-video-meets-floor:720x1280; bookmarklet-blob-direct-fetch; no-browser-download-prompt",
        "candidateUrl": "blob:https://grok.com/direct-import-candidate",
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    proof = payload["goalReadiness"]["liveGrokDirectImportProof"]
    assert payload["goalReadiness"]["liveGrokDirectImportProven"] is True
    assert proof["sourceKind"] == "bookmarklet-blob-direct-fetch"
    assert proof["eventType"] == "bookmarklet-direct-import"
    assert proof["handoffProjectId"] == handoff_id
    assert proof["sceneImported"] is True
    assert proof["sceneQueueAdvanced"] is True
    assert payload["goalReadiness"]["artifactGateComplete"] is True
    assert payload["goalReadiness"]["artifactRemainingGaps"] == []
    assert payload["goalReadiness"]["goalComplete"] is False
    assert payload["goalReadiness"]["operatingSystemComplete"] is False
    assert payload["goalReadiness"]["overallStatus"] == "artifact-gate-ready"


def test_final_video_library_audit_accepts_chrome_pageassets_direct_import_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "chrome-pageassets-live-proof"
    handoff_id = "chrome-pageassets-live-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "chrome-pageassets-live-proof",
        {
            "grokHandoffProjectId": handoff_id,
            "grokHandoffSceneIds": ["scene-01"],
        },
    )
    handoff_dir = tmp_path / "storage" / "grok-handoffs" / handoff_id
    incoming = handoff_dir / "incoming"
    incoming.mkdir(parents=True)
    imported_mp4 = incoming / "scene-01.grok.mp4"
    imported_mp4.write_bytes(b"chrome pageAssets mp4 bytes")
    (handoff_dir / "handoff.json").write_text(json.dumps({
        "projectId": handoff_id,
        "importHistory": [
            {
                "importedAt": "2026-05-29T12:10:00",
                "downloadDir": "",
                "sceneId": "scene-01",
                "importMode": "manual-browser-upload",
                "uploadedFileName": "scene-01.grok.mp4",
                "imported": [
                    {
                        "sceneId": "scene-01",
                        "expectedFileName": "scene-01.grok.mp4",
                        "fileName": "scene-01.grok.mp4",
                        "sourcePath": "storage/grok-handoffs/chrome-pageassets-live-proof/incoming/scene-01.grok.mp4",
                        "originalPath": "browser-upload:2ba3c820-c228-4e5b-9b97-b967dd568809.mp4",
                        "importMode": "manual-browser-upload",
                    }
                ],
            }
        ],
    }), encoding="utf-8")
    (handoff_dir / "extension-events.jsonl").write_text(json.dumps({
        "updatedAt": "2026-05-29T12:10:01",
        "projectId": handoff_id,
        "sceneId": "scene-01",
        "expectedFileName": "scene-01.grok.mp4",
        "eventType": "codex-chrome-page-assets-direct-import",
        "status": "imported",
        "sourceKind": "codex-chrome-page-assets-direct-fetch",
        "qualityNote": "original-download-source; codex-chrome-page-assets-direct-fetch; no-browser-download-prompt",
        "candidateUrl": "https://imagine-public.x.ai/imagine-public/share-videos/2ba3c820-c228-4e5b-9b97-b967dd568809.mp4",
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    proof = payload["goalReadiness"]["liveGrokDirectImportProof"]
    assert payload["goalReadiness"]["liveGrokDirectImportProven"] is True
    assert proof["sourceKind"] == "codex-chrome-page-assets-direct-fetch"
    assert proof["eventType"] == "codex-chrome-page-assets-direct-import"
    assert proof["handoffProjectId"] == handoff_id
    assert proof["sceneImported"] is True
    assert proof["sceneQueueAdvanced"] is True
    assert payload["goalReadiness"]["artifactGateComplete"] is True
    assert payload["goalReadiness"]["artifactRemainingGaps"] == []
    assert payload["goalReadiness"]["goalComplete"] is False
    assert payload["goalReadiness"]["operatingSystemComplete"] is False
    assert payload["goalReadiness"]["overallStatus"] == "artifact-gate-ready"


def test_final_video_library_audit_accepts_companion_blob_direct_import_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _ready_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "companion-blob-live-proof"
    handoff_id = "companion-blob-live-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "companion-blob-live-proof",
        {
            "grokHandoffProjectId": handoff_id,
            "grokHandoffSceneIds": ["scene-01"],
        },
    )
    handoff_dir = tmp_path / "storage" / "grok-handoffs" / handoff_id
    incoming = handoff_dir / "incoming"
    incoming.mkdir(parents=True)
    imported_mp4 = incoming / "scene-01.grok.mp4"
    imported_mp4.write_bytes(b"companion blob mp4 bytes")
    (handoff_dir / "handoff.json").write_text(json.dumps({
        "projectId": handoff_id,
        "importHistory": [
            {
                "importedAt": "2026-05-31T00:01:00",
                "downloadDir": "",
                "sceneId": "scene-01",
                "importMode": "manual-browser-upload",
                "uploadedFileName": "scene-01.grok.mp4",
                "imported": [
                    {
                        "sceneId": "scene-01",
                        "expectedFileName": "scene-01.grok.mp4",
                        "fileName": "scene-01.grok.mp4",
                        "sourcePath": "storage/grok-handoffs/companion-blob-live-proof/incoming/scene-01.grok.mp4",
                        "originalPath": "browser-upload:scene-01.grok.mp4",
                        "importMode": "manual-browser-upload",
                    }
                ],
            }
        ],
    }), encoding="utf-8")
    (handoff_dir / "extension-events.jsonl").write_text(json.dumps({
        "updatedAt": "2026-05-31T00:01:01",
        "projectId": handoff_id,
        "sceneId": "scene-01",
        "expectedFileName": "scene-01.grok.mp4",
        "eventType": "companion-blob-direct-import",
        "status": "imported",
        "sourceKind": "visible-video-blob-direct-fetch",
        "qualityNote": "visible-video-floor-met:720x1280; companion-blob-direct-fetch; no-browser-download-prompt",
        "candidateUrl": "blob:https://grok.com/visible-video-candidate",
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    proof = payload["goalReadiness"]["liveGrokDirectImportProof"]
    assert payload["goalReadiness"]["liveGrokDirectImportProven"] is True
    assert proof["sourceKind"] == "visible-video-blob-direct-fetch"
    assert proof["eventType"] == "companion-blob-direct-import"
    assert proof["handoffProjectId"] == handoff_id
    assert proof["sceneImported"] is True
    assert proof["sceneQueueAdvanced"] is True
    assert payload["goalReadiness"]["artifactGateComplete"] is True
    assert payload["goalReadiness"]["artifactRemainingGaps"] == []
    assert payload["goalReadiness"]["goalComplete"] is False
    assert payload["goalReadiness"]["operatingSystemComplete"] is False
    assert payload["goalReadiness"]["overallStatus"] == "artifact-gate-ready"


def test_final_video_library_audit_rejects_unpaired_handoff_direct_import_event(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _setup_required_companion_readiness)
    client = _media_test_client(tmp_path)
    final_root = tmp_path / "storage" / "final-videos"
    packet_dir = final_root / "handoff-log-unpaired-proof"
    handoff_id = "handoff-log-unpaired-proof"
    _write_ready_final_video_packet(
        packet_dir,
        "handoff-log-unpaired-proof",
        {
            "grokHandoffProjectId": handoff_id,
            "grokHandoffSceneIds": ["scene-01"],
        },
    )
    handoff_dir = tmp_path / "storage" / "grok-handoffs" / handoff_id
    handoff_dir.mkdir(parents=True)
    (handoff_dir / "handoff.json").write_text(json.dumps({
        "projectId": handoff_id,
        "importHistory": [],
    }), encoding="utf-8")
    (handoff_dir / "extension-events.jsonl").write_text(json.dumps({
        "updatedAt": "2026-05-29T12:01:01",
        "projectId": handoff_id,
        "sceneId": "scene-01",
        "expectedFileName": "scene-01.grok.mp4",
        "eventType": "bookmarklet-direct-import",
        "status": "imported",
        "sourceKind": "bookmarklet-blob-direct-fetch",
        "qualityNote": "visible-video-meets-floor:720x1280; bookmarklet-blob-direct-fetch; no-browser-download-prompt",
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(routes_media, "_run_final_video_ffprobe", lambda _path: {
        "ok": True,
        "width": 1080,
        "height": 1920,
        "frameRate": 30.0,
        "durationSeconds": 12.0,
        "hasAudio": True,
        "specReady": True,
    })

    response = client.get("/api/final-video-library/audit?limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["goalReadiness"]["liveGrokDirectImportProven"] is False
    assert payload["goalReadiness"]["liveGrokDirectImportProof"]["sourceKind"] == ""
    assert payload["goalReadiness"]["goalComplete"] is False
    assert any("Capture live signed-in Chrome/Grok generation proof plus local MP4 import/review advancement" in item for item in payload["goalReadiness"]["remainingGaps"])


def test_finalize_render_rejects_blocked_publish_packet(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_media, "_existing_chrome_companion_readiness", _ready_companion_readiness)
    client = _media_test_client(tmp_path)
    render_dir = tmp_path / "storage" / "renders" / "blocked-render"
    render_dir.mkdir(parents=True)
    output_path = render_dir / "blocked.mp4"
    output_path.write_bytes(b"fake mp4")
    quality_path = render_dir / "render-quality-report.json"
    quality_path.write_text(json.dumps({
        "projectId": "blocked-render",
        "publishReadiness": {
            "status": "blocked",
            "requiredFixes": ["Replace placeholder clips."],
            "recommendedFixes": ["Add continuity notes."],
        },
        "channelReadiness": {
            "status": "blocked",
            "requiredFixes": ["Resolve publishReadiness first."],
        },
        "uploadReview": {
            "status": "blocked",
            "requiredFixes": ["Resolve publishReadiness first."],
            "manualReviewItems": [],
        },
        "topTierReadiness": _top_tier_readiness("needs-publish-rework", False),
        "productionReview": {
            "summary": {
                "stockOnly": False,
                "missingContinuityScenes": [],
                "missingQualityReviewScenes": [],
                "firstSceneHookReady": True,
                "missingRationaleScenes": [],
            },
        },
        "checks": _current_quality_checks(
            publishReadinessGate={"status": "fail", "detail": "status=blocked"},
            channelReadinessGate={"status": "fail", "detail": "status=blocked"},
            uploadReviewGate={"status": "fail", "detail": "status=blocked"},
            topTierReadinessGate={"status": "warn", "detail": "status=needs-publish-rework"},
        ),
    }), encoding="utf-8")

    response = client.post("/api/finalize-render", json={
        "outputPath": str(output_path),
        "qualityReportPath": str(quality_path),
    })

    payload = response.get_json()
    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["error"] == "render is not publish-ready"
    assert payload["requiredFixes"] == ["Replace placeholder clips."]
    assert payload["channelReadiness"]["status"] == "blocked"
    assert payload["topTierReadiness"]["status"] == "needs-publish-rework"
    assert payload["sourcePipelineStatus"]["paidApiPolicy"]["paidAiApiAllowed"] is False
    assert payload["nextActions"]
    audit_path = Path(payload["blockedQualityAuditPath"])
    assert audit_path.exists()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["promotion"]["finalVideos"] is False
    assert audit["promotion"]["requireChannelReady"] is False
    assert audit["promotion"]["requireTopTier"] is False
    assert audit["error"] == "render is not publish-ready"
    assert audit["publishReadiness"]["status"] == "blocked"
    assert audit["requiredFixes"] == ["Replace placeholder clips."]
    assert audit["sourcePipelineStatus"]["grok"]["nextAction"].startswith("Use browser-control")
    assert "companionDirectImport" not in audit["sourcePipelineStatus"]["grok"]
    assert "complete-upload-review" in [item["key"] for item in audit["nextActions"]]
    assert not (tmp_path / "storage" / "final-videos" / "blocked-render").exists()


def test_render_result_serializes_inline_quality_report():
    result = SmokeRenderResult(
        ok=True,
        projectId="qa-inline",
        manifestPath="storage/inputs/qa-inline/render-manifest.json",
        outputPath="storage/renders/qa-inline/video-project.mp4",
        concatFilePath="storage/renders/qa-inline/concat.txt",
        subtitleFilePath="storage/renders/qa-inline/captions.srt",
        logPath="storage/renders/qa-inline/ffmpeg-smoke.log",
        ffmpeg={},
        sceneClipPaths=[],
        localMediaPlanPath="storage/cache/qa-inline/local-media-plan.json",
        localMediaReportPath="storage/renders/qa-inline/local-media-report.json",
        qualityReportPath="storage/renders/qa-inline/render-quality-report.json",
        qualityReport={"checks": {"outputSpec": {"status": "pass", "detail": "ok"}}},
        localMediaSummary={"placeholder": 0},
        localMedia=[],
    )

    payload = result.to_dict()

    assert payload["qualityReportPath"].endswith("render-quality-report.json")
    assert payload["qualityReport"]["checks"]["outputSpec"]["status"] == "pass"
