from __future__ import annotations

import json

from flask import Flask

from worker.bridge import material_library, production_status
from worker.bridge.routes_gates import gates_bp


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(material_library, "MATERIAL_LIBRARY_PATH", tmp_path / "topic-library" / "materials.json")
    monkeypatch.setattr(production_status, "ACTIVE_APPROVAL_PACKET_PATH", tmp_path / "approval-packets" / "ACTIVE.json")
    monkeypatch.setattr(
        production_status,
        "latest_material_dryrun_summary",
        lambda: {"available": False, "dryrunAllowed": False},
    )
    app = Flask(__name__)
    app.register_blueprint(gates_bp)
    return app.test_client()


def _source(source_id: str, source_type: str) -> dict:
    return {
        "sourceId": source_id,
        "sourceType": source_type,
        "title": f"{source_id} title",
        "url": f"https://example.com/{source_id}",
        "capturedAt": "2026-06-25",
        "observation": "Concrete observed signal.",
    }


def _topic_packet() -> dict:
    return {
        "discoverySeed": "AI 영상 제작 dry-run",
        "researchQueryPlan": [
            {"provider": "google-search", "surface": "search", "query": "AI 영상 제작", "intent": "search"},
            {"provider": "google-trends-kr", "surface": "trend", "query": "AI 영상 제작", "intent": "trend"},
            {"provider": "youtube-search", "surface": "video", "query": "AI 영상 제작", "intent": "video"},
            {"provider": "korean-community-scan", "surface": "community", "query": "AI 영상 제작", "intent": "community"},
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
                "workingTitle": "AI 영상 제작 dry-run에서 막히는 지점",
                "centralQuestion": "AI 영상 제작은 왜 dry-run에서 반복적으로 막히는가?",
            }
        ],
        "selection": {"selectedTopicId": "selected-topic"},
    }


def _intake_material(client):
    return client.post(
        "/api/topic-library/materials/intake",
        json={
            "candidate": {
                "id": "selected-topic",
                "title": "AI 영상 제작 dry-run에서 막히는 지점",
                "centralQuestion": "AI 영상 제작은 왜 dry-run에서 반복적으로 막히는가?",
                "searchSeed": "AI 영상 제작 dry-run",
                "score": 88,
            },
            "topicPacket": _topic_packet(),
            "topicGateResult": {"ready": True, "failedChecks": [], "report": {"topicReady": True}},
        },
    ).get_json()


def test_production_status_starts_from_material_library_when_empty(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).get("/api/production/status")

    assert response.status_code == 200
    payload = response.get_json()
    status = payload["productionStatus"]
    assert payload["ok"] is True
    assert status["schema"] == "video-studio.production-status-readmodel.v1"
    assert status["truthSource"] == "server-production-readmodel"
    assert status["materialLibrary"]["stats"]["total"] == 0
    assert status["nextAction"]["source"] == "material-library"
    assert status["nextAction"]["tab"] == "topic"
    assert status["workflowGates"] == []
    assert status["thinLoop"]["currentStage"] == "material"


def test_production_status_surfaces_server_gate_report_for_latest_material(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = _intake_material(client)

    response = client.get("/api/production/status")

    assert response.status_code == 200
    status = response.get_json()["productionStatus"]
    assert status["materialLibrary"]["latest"]["materialId"] == created["material"]["materialId"]
    assert status["gateReport"]["currentStage"] == "storyboard"
    assert status["nextAction"]["source"] == "production-gates"
    assert status["nextAction"]["stage"] == "storyboard"
    assert status["nextAction"]["tab"] == "plan"
    assert status["counts"]["total"] == 12
    assert status["thinLoop"]["currentStage"] == "rough-cut-dryrun"
    assert status["thinLoop"]["publishGate"]["status"] == "blocked"


def test_production_status_prioritizes_active_capcut_packet_blocker(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _intake_material(client)
    active_path = tmp_path / "approval-packets" / "ACTIVE.json"
    active_path.parent.mkdir(parents=True)
    active_path.write_text(
        json.dumps(
            {
                "packetId": "kr-curiosity-bottled-water-20260616",
                "taskId": "VIDEO-STUDIO-KR-CURIOSITY-APPROVAL-PACKET-20260616-01",
                "status": "active",
                "capcutHandoffRequired": True,
                "ffmpegOnlyFinalAllowed": False,
                "nextRequiredAction": {
                    "status": "capcut-auto-export-blocked-uia-home-draft-not-exposed",
                    "operatorAction": "CapCut에서 visible draft를 열고 export proof를 남기세요.",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/api/production/status")

    assert response.status_code == 200
    status = response.get_json()["productionStatus"]
    assert status["activePacket"]["blocked"] is True
    assert status["activePacket"]["capcutHandoffRequired"] is True
    assert status["nextAction"]["source"] == "active-approval-packet"
    assert status["nextAction"]["status"] == "blocked"
    assert status["nextAction"]["label"] == "CapCut export blocker"
    assert "visible draft" in status["nextAction"]["message"]
