from __future__ import annotations

from pathlib import Path

from flask import Flask

from worker.bridge import material_dryrun, material_library
from worker.bridge.routes_gates import gates_bp


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(material_library, "MATERIAL_LIBRARY_PATH", tmp_path / "topic-library" / "materials.json")
    monkeypatch.setattr(material_dryrun, "MATERIAL_DRYRUN_ROOT", tmp_path / "dry-runs" / "material-preflight")
    app = Flask(__name__)
    app.register_blueprint(gates_bp)
    return app.test_client()


def _path_from_payload(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return material_dryrun.PROJECT_ROOT / path


def test_material_dryrun_preflight_seeds_material_and_writes_artifacts(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post("/api/topic-library/materials/dryrun-preflight", json={"targetStage": "rough-cut"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["schema"] == "video-studio.material-dryrun-preflight.v1"
    assert payload["summary"]["createdSeed"] is True
    assert payload["summary"]["dryrunAllowed"] is True
    assert payload["summary"]["generationAllowed"] is True
    assert payload["summary"]["renderAllowed"] is True
    assert payload["summary"]["finalAllowed"] is False
    assert payload["summary"]["failedChecks"] == []
    assert payload["report"]["checks"]["dryrunTopicDiscoveryGate"]["status"] == "pass"
    assert payload["report"]["checks"]["dryrunMinimumReleaseGate"]["status"] == "skip"
    assert payload["report"]["checks"]["dryrunFinalLibraryGate"]["status"] == "skip"
    assert payload["packet"]["topicDiscoveryPacket"]["selection"]["selectedTopicId"] == "ai-video-dryrun-gate-map"

    paths = payload["summary"]["artifactPaths"]
    assert _path_from_payload(paths["packet"]).exists()
    assert _path_from_payload(paths["readinessReport"]).exists()
    assert _path_from_payload(paths["summary"]).exists()

    library = client.get("/api/topic-library/materials").get_json()
    assert library["stats"]["total"] == 1
    assert library["stats"]["withSourceLedger"] == 1
    assert library["stats"]["withTopicPass"] == 1
    assert library["summaries"][0]["evaluation"]["verdict"] == "review"
    assert library["summaries"][0]["evaluation"]["pendingChecks"] == ["observedSourceDepth"]
    assert library["summaries"][0]["evaluation"]["sourceCounts"]["observed"] == 0
    assert library["dryrunPreflight"]["available"] is True
    assert library["dryrunPreflight"]["dryrunAllowed"] is True


def test_material_dryrun_preflight_can_target_existing_material(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    seeded = client.post("/api/topic-library/materials/dryrun-preflight", json={"targetStage": "rough-cut"}).get_json()
    material_id = seeded["material"]["materialId"]

    response = client.post(
        "/api/topic-library/materials/dryrun-preflight",
        json={"materialId": material_id, "targetStage": "rough-cut"},
    )
    status = client.get("/api/topic-library/materials/dryrun-preflight")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["createdSeed"] is False
    assert payload["summary"]["materialId"] == material_id
    assert payload["report"]["dryrunAllowed"] is True
    assert status.status_code == 200
    assert status.get_json()["dryrunPreflight"]["materialId"] == material_id


def test_material_dryrun_status_keeps_latest_rough_cut_after_final_probe(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    rough_cut = client.post("/api/topic-library/materials/dryrun-preflight", json={"targetStage": "rough-cut"}).get_json()

    final_probe = client.post("/api/topic-library/materials/dryrun-preflight", json={"targetStage": "final"}).get_json()
    status = client.get("/api/topic-library/materials/dryrun-preflight").get_json()
    library = client.get("/api/topic-library/materials").get_json()

    assert final_probe["summary"]["targetStage"] == "final"
    assert final_probe["summary"]["dryrunAllowed"] is False
    assert final_probe["summary"]["failedChecks"] == ["dryrunMinimumReleaseGate", "dryrunFinalLibraryGate"]
    assert status["dryrunPreflight"]["targetStage"] == "rough-cut"
    assert status["dryrunPreflight"]["dryrunAllowed"] is True
    assert status["dryrunPreflight"]["artifactPaths"]["summary"] == rough_cut["summary"]["artifactPaths"]["summary"]
    assert library["dryrunPreflight"]["targetStage"] == "rough-cut"
    assert library["dryrunPreflight"]["dryrunAllowed"] is True


def test_material_dryrun_preflight_reports_missing_material(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).post(
        "/api/topic-library/materials/dryrun-preflight",
        json={"materialId": "missing-material"},
    )

    assert response.status_code == 404
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"] == "material-not-found"
