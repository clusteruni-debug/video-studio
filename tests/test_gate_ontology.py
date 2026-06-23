from __future__ import annotations

import json
import re
from pathlib import Path

from worker.quality_gate_system import (
    FINAL_READINESS_GATE_KEYS,
    GATE_PHASES,
    RENDER_QUALITY_CHECK_KEYS,
)
from worker.render.production_mode_gate import (
    FORMAT_PROFILE_GATE_KEYS,
    FORMAT_PROFILES,
    LONGFORM_POWER_USER_GATE_KEYS,
    LONGFORM_PRODUCTION_GATE_KEYS,
    LONGFORM_STORYBOARD_GATE_KEYS,
    PROVIDER_ROLE_MATRIX_GATE_KEYS,
)
from worker.render.longform_workflow_gate import LONGFORM_WORKFLOW_GATE_KEYS
from worker.render.longform_minimum_release_gate import LONGFORM_MINIMUM_RELEASE_GATE_KEYS
from worker.render.longform_dryrun_readiness import LONGFORM_DRYRUN_READINESS_GATE_KEYS
from worker.render.topic_discovery_gate import TOPIC_DISCOVERY_GATE_KEYS


ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_PATH = ROOT / "config" / "gate-ontology.json"
DOC_PATH = ROOT / "docs" / "reference" / "gate-ontology.md"
GOLDEN_GATE_PATH = ROOT / "worker" / "render" / "golden_reference_gate.py"
GROK_ROUTES_PATH = ROOT / "worker" / "bridge" / "routes_grok.py"
SOURCE_ROUTES_PATH = ROOT / "worker" / "bridge" / "routes_sources.py"
PRODUCTION_PACKET_LOCK_PATH = ROOT / "worker" / "render" / "production_packet_lock.py"
PRODUCTION_MODE_GATE_PATH = ROOT / "worker" / "render" / "production_mode_gate.py"
LONGFORM_WORKFLOW_GATE_PATH = ROOT / "worker" / "render" / "longform_workflow_gate.py"
LONGFORM_MINIMUM_RELEASE_GATE_PATH = ROOT / "worker" / "render" / "longform_minimum_release_gate.py"
LONGFORM_DRYRUN_READINESS_GATE_PATH = ROOT / "worker" / "render" / "longform_dryrun_readiness.py"
TOPIC_DISCOVERY_GATE_PATH = ROOT / "worker" / "render" / "topic_discovery_gate.py"


def _load_ontology() -> dict:
    return json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))


def _read_project_file(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _entries_with_labels(ontology: dict):
    for section in (
        "phaseGates",
        "finalReadinessGates",
        "sourceAcquisitionGates",
        "sourceRightsGates",
        "activeProductionPacketLocks",
        "formatProfileGates",
        "providerRoleMatrixGates",
        "topicDiscoveryGates",
        "longformProductionGates",
        "longformStoryboardGates",
        "longformPowerUserGates",
        "longformWorkflowStageGates",
        "longformMinimumReleaseGates",
        "longformDryrunReadinessGates",
        "goldenReferenceOperationalChecks",
        "goldenReferenceTopLevelGates",
        "goldenReferenceSceneGates",
        "postEditSubcontracts",
    ):
        for entry in ontology[section]:
            yield f"{section}:{entry['gateKey']}", entry
    for entry in ontology["renderQualityGroups"]:
        yield f"renderQualityGroups:{entry['groupKey']}", entry
    for entry in ontology["evidenceSchemas"]:
        yield f"evidenceSchemas:{entry['schema']}", entry


def _assert_anchors_exist(label: str, entry: dict, anchor_key: str) -> None:
    anchors = entry.get(anchor_key) or []
    assert anchors, f"{label} missing {anchor_key}"
    for anchor in anchors:
        path = anchor["path"]
        file_path = ROOT / path
        assert file_path.exists(), f"{label} {anchor_key} path missing: {path}"
        text = file_path.read_text(encoding="utf-8")
        for symbol in anchor.get("symbols") or []:
            assert symbol in text, f"{label} {anchor_key} symbol missing: {path}::{symbol}"


def _production_packet_lock_check_keys(source: str) -> set[str]:
    direct_keys = set(re.findall(r'report\["checks"\]\["([^"]+)"\]', source))
    failure_keys = set(re.findall(r'_fail\(report,\s*"([^"]+)"', source))
    return direct_keys | failure_keys


def test_gate_ontology_links_existing_docs_code_and_tests():
    ontology = _load_ontology()
    assert ontology["schema"] == "video-studio.gate-ontology.v1"

    for label, entry in _entries_with_labels(ontology):
        assert entry.get("layer"), f"{label} missing layer"
        assert entry.get("genericity") == "global-generic", f"{label} must stay generic"
        assert entry.get("blockingMode") or label.startswith("evidenceSchemas:"), (
            f"{label} missing blockingMode"
        )
        doc_paths = entry.get("docPaths") or []
        assert doc_paths, f"{label} missing docPaths"
        for doc_path in doc_paths:
            assert (ROOT / doc_path).exists(), f"{label} doc path missing: {doc_path}"
        _assert_anchors_exist(label, entry, "codeAnchors")
        _assert_anchors_exist(label, entry, "testAnchors")


def test_gate_ontology_covers_unified_gate_registry():
    ontology = _load_ontology()

    phase_keys = {phase["phaseKey"] for phase in GATE_PHASES}
    ontology_phase_keys = {entry["phaseKey"] for entry in ontology["phaseGates"]}
    assert ontology_phase_keys == phase_keys

    render_keys = set(RENDER_QUALITY_CHECK_KEYS)
    covered_render_keys: list[str] = []
    for group in ontology["renderQualityGroups"]:
        covered_render_keys.extend(group["coveredKeys"])
    assert len(covered_render_keys) == len(set(covered_render_keys)), (
        "render-quality ontology groups must not cover a key more than once"
    )
    assert set(covered_render_keys) == render_keys

    final_keys = set(FINAL_READINESS_GATE_KEYS) | {"broad-operating-goal"}
    ontology_final_keys = {entry["gateKey"] for entry in ontology["finalReadinessGates"]}
    assert ontology_final_keys == final_keys


def test_gate_ontology_covers_source_acquisition_gate_inventory():
    ontology = _load_ontology()
    ontology_keys = {entry["gateKey"] for entry in ontology["sourceAcquisitionGates"]}
    assert ontology_keys == {
        "assetQualityGate",
        "grokMainSourceGate",
        "grokRenderPayloadReadiness",
    }

    source = GROK_ROUTES_PATH.read_text(encoding="utf-8")
    for symbol in (
        "_asset_quality_gate",
        "_grok_main_source_gate",
        "qualityGateRequired",
        "qualityGateReady",
        "mainSourceGate",
        "allReady",
    ):
        assert symbol in source


def test_gate_ontology_covers_source_rights_gate_inventory():
    ontology = _load_ontology()
    ontology_keys = {entry["gateKey"] for entry in ontology["sourceRightsGates"]}
    assert ontology_keys == {
        "editorialRightsGate",
        "operatorApprovedSourceFetch",
        "motionSourceReady",
    }

    source = SOURCE_ROUTES_PATH.read_text(encoding="utf-8")
    for symbol in (
        "rightsGate",
        "pilot-ready",
        "operatorApprovedSourceFetch",
        "operatorApprovedSourceFetch=true is required",
        "motionSourceReady",
        "bind fetched GIF/video source paths",
    ):
        assert symbol in source


def test_gate_ontology_covers_active_production_packet_lock_inventory():
    ontology = _load_ontology()
    ontology_keys = {entry["gateKey"] for entry in ontology["activeProductionPacketLocks"]}

    source = PRODUCTION_PACKET_LOCK_PATH.read_text(encoding="utf-8")
    source_keys = _production_packet_lock_check_keys(source)
    assert ontology_keys == source_keys


def test_gate_ontology_covers_production_mode_gate_inventory():
    ontology = _load_ontology()

    assert {entry["gateKey"] for entry in ontology["formatProfileGates"]} == set(
        FORMAT_PROFILE_GATE_KEYS
    )
    assert set(ontology["formatProfileGates"][0]["supportedProfiles"]) == set(FORMAT_PROFILES)
    assert {entry["gateKey"] for entry in ontology["providerRoleMatrixGates"]} == set(
        PROVIDER_ROLE_MATRIX_GATE_KEYS
    )
    assert {entry["gateKey"] for entry in ontology["topicDiscoveryGates"]} == set(
        TOPIC_DISCOVERY_GATE_KEYS
    )
    assert {entry["gateKey"] for entry in ontology["longformProductionGates"]} == set(
        LONGFORM_PRODUCTION_GATE_KEYS
    )
    assert {entry["gateKey"] for entry in ontology["longformStoryboardGates"]} == set(
        LONGFORM_STORYBOARD_GATE_KEYS
    )
    assert {entry["gateKey"] for entry in ontology["longformPowerUserGates"]} == set(
        LONGFORM_POWER_USER_GATE_KEYS
    )
    assert {entry["gateKey"] for entry in ontology["longformWorkflowStageGates"]} == set(
        LONGFORM_WORKFLOW_GATE_KEYS
    )
    assert {entry["gateKey"] for entry in ontology["longformMinimumReleaseGates"]} == set(
        LONGFORM_MINIMUM_RELEASE_GATE_KEYS
    )
    assert {entry["gateKey"] for entry in ontology["longformDryrunReadinessGates"]} == set(
        LONGFORM_DRYRUN_READINESS_GATE_KEYS
    )

    source = PRODUCTION_MODE_GATE_PATH.read_text(encoding="utf-8")
    for symbol in (
        "FORMAT_PROFILE_GATE_KEYS",
        "PROVIDER_ROLE_MATRIX_GATE_KEYS",
        "LONGFORM_PRODUCTION_GATE_KEYS",
        "LONGFORM_STORYBOARD_GATE_KEYS",
        "LONGFORM_POWER_USER_GATE_KEYS",
        "evaluate_production_mode_gate",
        "evaluate_provider_role_matrix",
        "longform_10m",
        "shortform_vertical",
    ):
        assert symbol in source

    workflow_source = LONGFORM_WORKFLOW_GATE_PATH.read_text(encoding="utf-8")
    for symbol in (
        "LONGFORM_WORKFLOW_STAGE_KEYS",
        "LONGFORM_WORKFLOW_GATE_KEYS",
        "evaluate_longform_workflow_gate",
        "longformWorkflowOrderGate",
        "longformWorkflowSeededFailureGate",
    ):
        assert symbol in workflow_source

    release_source = LONGFORM_MINIMUM_RELEASE_GATE_PATH.read_text(encoding="utf-8")
    for symbol in (
        "LONGFORM_MINIMUM_RELEASE_GATE_KEYS",
        "LONGFORM_MINIMUM_RELEASE_SCORE_WEIGHTS",
        "evaluate_longform_minimum_release_gate",
        "longformReleaseScoreGate",
        "MINIMUM_RELEASE_SCORE",
    ):
        assert symbol in release_source

    topic_source = TOPIC_DISCOVERY_GATE_PATH.read_text(encoding="utf-8")
    for symbol in (
        "TOPIC_DISCOVERY_GATE_KEYS",
        "evaluate_topic_discovery_gate",
        "topicSourceLedgerGate",
        "researchQueryPlanGate",
        "sourceAuthenticityGate",
        "audienceRetentionFitGate",
        "topicSelectionMatrixGate",
        "TOPIC_SELECTION_MINIMUM_SCORE",
    ):
        assert symbol in topic_source

    dryrun_source = LONGFORM_DRYRUN_READINESS_GATE_PATH.read_text(encoding="utf-8")
    for symbol in (
        "LONGFORM_DRYRUN_READINESS_GATE_KEYS",
        "evaluate_longform_dryrun_readiness",
        "dryrunTopicDiscoveryGate",
        "dryrunWorkflowGate",
        "dryrunFinalLibraryGate",
    ):
        assert symbol in dryrun_source


def test_gate_ontology_covers_golden_reference_source_inventory():
    ontology = _load_ontology()
    source = GOLDEN_GATE_PATH.read_text(encoding="utf-8")

    top_level_keys = set(re.findall(r'report\["checks"\]\["([^"]+)"\]\s*=', source))
    ontology_top_level_keys = {
        entry["gateKey"] for entry in ontology["goldenReferenceOperationalChecks"]
    } | {
        entry["gateKey"] for entry in ontology["goldenReferenceTopLevelGates"]
    }
    assert ontology_top_level_keys == top_level_keys

    scene_match = re.search(r"checks = \{(?P<body>.*?)\n    \}", source, re.S)
    assert scene_match, "could not locate _check_scene checks dictionary"
    scene_keys = set(re.findall(r'"([^"]+)":\s*_check_', scene_match.group("body")))
    ontology_scene_keys = {entry["gateKey"] for entry in ontology["goldenReferenceSceneGates"]}
    assert ontology_scene_keys == scene_keys

    subcontract_keys = set(
        re.findall(r"postEditGoldenReference\.([A-Za-z0-9]+) object is required", source)
    )
    ontology_subcontract_keys = {
        entry["gateKey"] for entry in ontology["postEditSubcontracts"]
    }
    assert ontology_subcontract_keys == subcontract_keys


def test_gate_ontology_covers_golden_reference_evidence_schemas():
    ontology = _load_ontology()
    source = GOLDEN_GATE_PATH.read_text(encoding="utf-8")

    schema_values = {
        value
        for _, value in re.findall(r'([A-Z_]+_SCHEMA)\s*=\s*"([^"]+)"', source)
        if value.startswith("video-studio.")
    }
    ontology_schema_values = {entry["schema"] for entry in ontology["evidenceSchemas"]}
    assert ontology_schema_values == schema_values


def test_gate_ontology_doc_mentions_every_registered_gate():
    ontology = _load_ontology()
    doc = DOC_PATH.read_text(encoding="utf-8")

    for section in (
        "phaseGates",
        "finalReadinessGates",
        "sourceAcquisitionGates",
        "sourceRightsGates",
        "activeProductionPacketLocks",
        "formatProfileGates",
        "providerRoleMatrixGates",
        "topicDiscoveryGates",
        "longformProductionGates",
        "longformStoryboardGates",
        "longformPowerUserGates",
        "longformWorkflowStageGates",
        "longformMinimumReleaseGates",
        "longformDryrunReadinessGates",
        "goldenReferenceOperationalChecks",
        "goldenReferenceTopLevelGates",
        "goldenReferenceSceneGates",
        "postEditSubcontracts",
    ):
        for entry in ontology[section]:
            assert f"`{entry['gateKey']}`" in doc
    for entry in ontology["renderQualityGroups"]:
        assert f"`{entry['groupKey']}`" in doc
    for entry in ontology["evidenceSchemas"]:
        assert f"`{entry['schema']}`" in doc


def test_gate_ontology_stays_generic_not_candidate_specific():
    text = ONTOLOGY_PATH.read_text(encoding="utf-8").lower()
    forbidden_terms = {
        "bottled-water",
        "bottle",
        "water bottle",
        "햇빛",
        "생수",
        "물병",
    }
    leaked_terms = sorted(term for term in forbidden_terms if term in text)
    assert not leaked_terms, f"gate ontology must stay reusable, leaked terms: {leaked_terms}"
