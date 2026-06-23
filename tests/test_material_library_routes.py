from __future__ import annotations

from flask import Flask

from worker.bridge import material_library
from worker.bridge.routes_gates import gates_bp


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(material_library, "MATERIAL_LIBRARY_PATH", tmp_path / "topic-library" / "materials.json")
    app = Flask(__name__)
    app.register_blueprint(gates_bp)
    return app.test_client()


def _source(source_id: str, source_type: str) -> dict:
    return {
        "sourceId": source_id,
        "sourceType": source_type,
        "title": f"{source_id} title",
        "url": f"https://example.com/{source_id}",
        "capturedAt": "2026-06-22",
        "observation": "Concrete observed signal.",
    }


def _topic_packet() -> dict:
    return {
        "discoverySeed": "AI 공부 인증",
        "researchQueryPlan": [
            {"provider": "google-search", "surface": "search", "query": "AI 공부 인증", "intent": "search"},
            {"provider": "google-trends-kr", "surface": "trend", "query": "AI 공부 인증", "intent": "trend"},
            {"provider": "youtube-search", "surface": "video", "query": "AI 공부 인증", "intent": "video"},
            {"provider": "korean-community-scan", "surface": "community", "query": "AI 공부 인증", "intent": "community"},
        ],
        "sourceLedger": [
            _source("search-01", "google-search"),
            _source("trend-01", "google-trends-kr"),
            _source("trend-02", "naver-datalab"),
            _source("video-01", "youtube-search"),
            _source("community-01", "korean-community"),
        ],
        "topicCandidates": [
            {
                "topicId": "selected-topic",
                "workingTitle": "AI 공부 인증은 실제로 효과가 있을까",
                "centralQuestion": "AI 공부 인증은 왜 지금 반복되는가?",
            }
        ],
        "selection": {"selectedTopicId": "selected-topic"},
    }


def _candidate() -> dict:
    return {
        "id": "selected-topic",
        "title": "AI 공부 인증은 실제로 효과가 있을까",
        "centralQuestion": "AI 공부 인증은 왜 지금 반복되는가?",
        "searchSeed": "AI 공부 인증",
        "score": 88,
        "scoreBreakdown": {"freshness": 24, "sourceEvidence": 18},
        "rankingReason": "Source-backed candidate.",
        "nextPipelineAction": "Run topic gate.",
    }


def _storyboard_packet() -> dict:
    return {
        "beats": [
            {
                "beatId": "open",
                "promise": "첫 30초 안에 소재 질문과 출처 기반 검증 기준을 제시한다.",
            }
        ],
        "scenePlan": [{"sceneId": "scene-01", "sourceRefs": ["search-01", "trend-01"]}],
    }


def test_topic_library_materials_route_starts_empty(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).get("/api/topic-library/materials")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["stats"]["total"] == 0
    assert payload["materials"] == []


def test_topic_library_intake_persists_material_and_dedupes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = {
        "candidate": _candidate(),
        "topicPacket": _topic_packet(),
        "topicGateResult": {"ready": True, "failedChecks": [], "report": {"topicReady": True}},
    }

    first = client.post("/api/topic-library/materials/intake", json=body)
    second = client.post("/api/topic-library/materials/intake", json=body)

    assert first.status_code == 200
    first_payload = first.get_json()
    assert first_payload["ok"] is True
    assert first_payload["created"] is True
    assert first_payload["material"]["title"] == "AI 공부 인증은 실제로 효과가 있을까"
    assert first_payload["productionGates"]["currentStage"] == "storyboard"
    assert first_payload["productionGates"]["stages"][1]["status"] == "pass"
    assert first_payload["productionGates"]["stages"][2]["status"] == "pass"
    assert first_payload["productionHandoff"]["schema"] == "video-studio.material-production-handoff.v1"
    assert "AI 공부 인증은 실제로 효과가 있을까" in first_payload["productionHandoff"]["promptMemo"]
    assert first_payload["productionHandoff"]["nextDashboardAction"]["tab"] == "plan"
    assert first_payload["materialEvaluation"]["schema"] == "video-studio.material-evaluation-gate.v1"
    assert first_payload["materialEvaluation"]["score"] >= 80
    assert first_payload["materialEvaluation"]["verdict"] == "pass"

    assert second.status_code == 200
    second_payload = second.get_json()
    assert second_payload["created"] is False
    assert second_payload["duplicateCandidates"][0]["reason"] == "exact-dedupe-key"
    assert second_payload["stats"]["total"] == 1

    stored = client.get("/api/topic-library/materials").get_json()
    assert stored["stats"]["total"] == 1
    assert stored["stats"]["withSourceLedger"] == 1
    assert stored["stats"]["withTopicPass"] == 1
    assert stored["summaries"][0]["sourceCount"] == 5
    assert stored["summaries"][0]["evaluation"]["score"] >= 80

    material_id = first_payload["material"]["materialId"]
    handoff = client.get(f"/api/topic-library/materials/{material_id}/production-handoff")
    assert handoff.status_code == 200
    assert handoff.get_json()["productionHandoff"]["storyboardSeed"]["sourceLedgerRefs"] == [
        "search-01",
        "trend-01",
        "trend-02",
        "video-01",
        "community-01",
    ]


def test_topic_library_gate_event_and_orchestrate_routes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/api/topic-library/materials/intake",
        json={"candidate": _candidate(), "topicPacket": _topic_packet()},
    ).get_json()
    material_id = created["material"]["materialId"]

    event = client.post(
        f"/api/topic-library/materials/{material_id}/gate-event",
        json={"stage": "topic-discovery", "status": "pass", "failedChecks": []},
    )
    empty_report = client.post(
        "/api/production-gates/orchestrate",
        json={"materialId": material_id, "packets": {"storyboardPacket": {"beats": []}}},
    )
    proof_report = client.post(
        "/api/production-gates/orchestrate",
        json={"materialId": material_id, "packets": {"storyboardPacket": _storyboard_packet()}},
    )
    missing = client.post("/api/production-gates/orchestrate", json={"materialId": "missing"})

    assert event.status_code == 200
    assert event.get_json()["productionGates"]["currentStage"] == "storyboard"
    assert empty_report.status_code == 200
    empty_gate = empty_report.get_json()["gateReport"]
    assert empty_gate["stages"][3]["status"] == "pending"
    assert empty_gate["stages"][3]["failedChecks"][0].startswith("insufficientEvidence:")
    assert proof_report.status_code == 200
    assert proof_report.get_json()["gateReport"]["stages"][3]["status"] == "pass"
    assert missing.status_code == 404
    assert missing.get_json()["error"] == "material-not-found"


def test_production_process_audit_route_covers_all_stages(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).get("/api/production-gates/process-audit")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    audit = payload["audit"]
    assert audit["schema"] == "video-studio.production-process-gate-audit.v1"
    assert audit["stageCount"] == 12
    assert audit["coveredStageCount"] == 12
    assert audit["gapStageCount"] == 0
    assert audit["coverageVerdict"] == "pass"
    assert audit["proofVerdict"] == "review"
    assert audit["verdict"] == "review"
    assert audit["structuredProofStageCount"] >= 5
    assert {row["stage"] for row in audit["rows"]} >= {
        "material-intake",
        "source-ledger",
        "topic-discovery",
        "storyboard",
        "source-acquisition",
        "prompt-quality",
        "asset-import-review",
        "edit-assembly",
        "render-preflight",
        "quality-review",
        "publish-readiness",
        "post-publish-learning",
    }
