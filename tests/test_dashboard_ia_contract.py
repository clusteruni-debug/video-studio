from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = ROOT / "app" / "ui" / "src"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_primary_navigation_is_workflow_not_implementation_modules():
    top_bar = _read("app/ui/src/components/TopBar.tsx")
    app = _read("app/ui/src/App.tsx")
    context = _read("app/ui/src/context/StudioContext.tsx")

    expected_tabs = ["home", "topic", "plan", "sources", "edit", "review", "advanced"]
    for tab in expected_tabs:
        assert f'tab: "{tab}"' in top_bar
        assert f'activeTab === "{tab}"' in app or tab == "home"

    assert 'activeTab: "home"' in context
    assert 'export type StudioTab = "home" | "topic" | "plan" | "sources" | "edit" | "review" | "advanced";' in context

    forbidden_primary_tabs = ["storyboard", "images", "gates", "batch", "jobs"]
    tab_config = re.search(r"const TAB_CONFIG:[\s\S]+?\];", top_bar)
    assert tab_config, "TopBar TAB_CONFIG must stay explicit and reviewable"
    tab_config_text = tab_config.group(0)
    for tab in forbidden_primary_tabs:
        assert f'tab: "{tab}"' not in tab_config_text


def test_advanced_raw_panels_require_explicit_disclosure():
    advanced = _read("app/ui/src/components/AdvancedOpsPanel.tsx")

    assert 'useState<AdvancedMode>("overview")' in advanced
    assert "setDetailOpen(false)" in advanced
    assert "세부 운영 패널 열기" in advanced
    assert "advanced-detail-placeholder" in advanced

    raw_panel_renders = [
        'detailOpen && mode === "gates" && <GatesPanel />',
        'detailOpen && mode === "library" && <FinalVideoLibraryPanel autoLoad />',
        'detailOpen && mode === "batch" && <BatchPanel />',
        'detailOpen && mode === "jobs" && <JobsPanel />',
    ]
    for render_guard in raw_panel_renders:
        assert render_guard in advanced

    assert "Source acquisition loop" not in advanced
    assert "Dashboard smoke" not in advanced


def test_ux_rescue_keeps_primary_actions_separate_from_advanced_controls():
    gates = _read("app/ui/src/components/GatesPanel.tsx")
    scene_detail = _read("app/ui/src/components/SceneDetailPanel.tsx")
    render_review = _read("app/ui/src/components/RenderReviewPanel.tsx")
    styles = _read("app/ui/src/styles.css")

    for required in [
        "gate-disclosure-panel gate-workflow-disclosure",
        "출처 초안과 소재 DB",
        "gate-next-action-card",
    ]:
        assert required in gates

    for required in [
        "grok-action-stack",
        "grok-primary-visible-actions",
        "Chrome 탭 / 동기화 고급 작업",
        "다운로드 경로 / 자동 생성 고급 작업",
    ]:
        assert required in scene_detail

    assert "render-action-disclosure" in render_review
    assert "source recovery 보조 작업" in render_review
    assert "grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));" in styles
    assert "white-space: normal;" in styles
    assert ".grok-action-disclosure" in styles


def test_sidebar_default_guidance_is_korean_production_copy():
    sidebar = _read("app/ui/src/components/Sidebar.tsx")

    for label in ["화면 구성", "사용 소스", "피할 것"]:
        assert f"<dt>{label}</dt>" in sidebar

    for forbidden in ["<dt>layout</dt>", "<dt>free assets</dt>", "<dt>avoid</dt>"]:
        assert forbidden not in sidebar


def test_topic_stage_starts_with_discovery_before_validation():
    gates = _read("app/ui/src/components/GatesPanel.tsx")
    source_draft = _read("app/ui/src/components/TopicSourceLedgerDraft.tsx")
    material_library = _read("app/ui/src/components/MaterialLibraryPanel.tsx")
    sidebar = _read("app/ui/src/components/Sidebar.tsx")
    home = _read("app/ui/src/components/ProductionHomePanel.tsx")
    auto_studio = _read("app/ui/src/components/AutoStudioPanel.tsx")
    scene_director = _read("app/ui/src/components/SceneDirectorPanel.tsx")
    bridge = _read("app/ui/src/lib/bridge.ts")
    auto_studio_backend = _read("worker/bridge/auto_studio.py")
    human_operator = _read("app/ui/src/components/HumanOperatorP0Panel.tsx")
    human_mvp = _read("app/ui/src/components/HumanOperatorMvpPanels.tsx")
    gate_status = _read("app/ui/src/components/ProductionGateStatusPanel.tsx")
    process_audit = _read("app/ui/src/components/ProductionProcessAuditPanel.tsx")
    workflow_gate = _read("app/ui/src/components/ProductionWorkflowGatePanel.tsx")
    storyboard = _read("app/ui/src/components/StoryboardPanel.tsx")
    sources_workspace = _read("app/ui/src/components/SourcesWorkspacePanel.tsx")
    edit_workspace = _read("app/ui/src/components/EditWorkspacePanel.tsx")
    review_workspace = _read("app/ui/src/components/ReviewWorkspacePanel.tsx")
    advanced = _read("app/ui/src/components/AdvancedOpsPanel.tsx")

    assert 'type GateMode = "discover" | "topic" | "longform";' in gates
    assert 'useState<GateMode>("discover")' in gates
    assert 'const HOT_DISCOVERY_SEED = "오늘 한국에서 가장 뜨거운 소재";' in gates
    assert "오늘 뜨는 소재부터 찾기" in gates
    assert "키워드가 없어도 시작합니다." in gates
    assert "탐색 키워드 (선택)" in gates
    assert "오늘 핫한 소재 찾기" in gates
    assert "discoveryMode: autoHot ? \"auto-hot-topic\" : \"keyword-filtered\"" in gates
    assert 'timeZone: "Asia/Seoul"' in gates
    assert "type DiscoveryCandidate" in gates
    assert "buildDiscoveryCandidates" in gates
    assert "fetchHotTopicCandidates" in gates
    assert "loadHotCandidates" in gates
    assert "type CandidateResearchLink" in source_draft
    assert "researchLinks" in gates
    assert "TopicSourceLedgerDraft" in gates
    assert "MaterialLibraryPanel" in gates
    assert "applyResearchLedgerDrafts" in gates
    assert "setLongformJson(stringify(longformSkeletonPacket(parsed.packet)))" in gates
    assert "후보 새로고침" in gates
    assert "실시간 뉴스 후보" in gates
    assert "fallback 후보" in gates
    assert "gate-topic-candidate" in gates
    assert "선택 후보 검증 링크" in gates
    assert "확인 후 sourceLedger에 추가" in gates
    assert "selectedCandidate.title" in gates
    assert "candidateToTopic" in gates
    assert "topicDiscoveryScaffoldPacket" in gates
    assert "topicCandidates: orderedCandidates.map" in gates
    assert "sourceLedger: candidateResult?.sourceLedger" in gates
    assert "실제 URL과 관찰 메모를 먼저 채운다." in gates
    assert "topicPassingExamplePacket" in gates
    assert "예시 데이터 보기" in gates
    assert "hasDiscoverySeed" not in gates
    assert "disabled={!hasDiscoverySeed}" not in gates

    for required in [
        "sourceLedger 반자동 입력",
        "실제 출처 URL",
        "관찰 메모",
        "sourceLedger 초안에 반영",
        "operator-${candidateId}-${link.surface}",
    ]:
        assert required in source_draft

    for required in [
        "소재 DB / 라이브러리",
        "/api/topic-library/materials",
        "/api/topic-library/materials/intake",
        "/api/topic-library/materials/${materialId}/production-handoff",
        "/api/topic-library/materials/dryrun-preflight",
        "중복 후보",
        "제작 게이트",
        "sourceLedger 보유",
        "productionHandoff",
        "materialEvaluation",
        "소재 평가 게이트",
        "소재 seed / packet / readiness report 준비",
        "Dry-run 사전 준비",
        "기획 메모에 반영",
        "현재 실행 중인 브리지가 오래된 코드입니다.",
    ]:
        assert required in material_library

    assert "<span>주제 / 프롬프트</span>" not in sidebar
    assert "<span>소재 메모</span>" in sidebar
    assert "상단의 소재 탭에서 후보부터 찾으세요" in sidebar
    assert "먼저 소재 후보를 찾으세요" in home
    assert "HumanOperatorP0Panel" in home
    assert "AutoStudioPanel" in home
    assert "ProductionGateStatusPanel" in home
    assert "ProductionWorkflowGatePanel" in home
    assert "ProductionProcessAuditPanel" in home
    assert "SourceReviewMvpPanel" in sources_workspace
    assert "RenderRecoveryPanel" in edit_workspace
    assert "PhoneReviewPublishPanel" in review_workspace
    assert '<ProductionWorkflowGatePanel focus="topic" />' in gates
    assert "ProductionProcessAuditPanel" in advanced

    for required in [
        "Auto Studio MVP",
        "actions.setDraftResult",
        "actions.setRenderResult",
        "SceneDirectorPanel",
    ]:
        assert required in auto_studio

    for required in [
        "/api/auto-studio/providers",
        "/api/auto-studio/run",
        "/api/auto-studio/import-asset",
        "AutoStudioProviderRegistry",
        "AutoStudioRunResult",
        "AutoStudioHandoffTask",
    ]:
        assert required in bridge

    for required in [
        "Grok Imagine handoff",
        "Gemini web handoff",
        "Seedance manual slot",
        "operator-handoff",
        "manual-import",
        "Grok /c/* redirects",
        "SceneAssetPayload-compatible adapter",
        "devProofRail",
    ]:
        assert required in auto_studio_backend

    for required in [
        "Scene Director",
        "Open Provider",
        "Copy Prompt",
        "Mark Generated",
        "Import File",
        "Use Fallback",
        "importAutoStudioSceneAsset",
        "updateAutoStudioHandoffTask",
        "operator-local-import",
    ]:
        assert required in scene_director

    workflow_contract = {
        "app/ui/src/components/StoryboardPanel.tsx": storyboard,
        "app/ui/src/components/SourcesWorkspacePanel.tsx": sources_workspace,
        "app/ui/src/components/EditWorkspacePanel.tsx": edit_workspace,
        "app/ui/src/components/ReviewWorkspacePanel.tsx": review_workspace,
        "app/ui/src/components/AdvancedOpsPanel.tsx": advanced,
    }
    for path, text in workflow_contract.items():
        assert "ProductionWorkflowGatePanel" in text, f"{path} must surface workflow gate status"

    for required in [
        "Human operator P0",
        "/api/human-operator/status",
        "/api/human-operator/demo/prepare",
        "No-LLM demo 준비",
        "First-run setup",
        "No-LLM demo path",
        "Local source proof",
        "Render health",
        "external AI not required",
        "ProviderReadinessPanel",
    ]:
        assert required in human_operator

    for required in [
        "Provider readiness matrix",
        "Demo Mode",
        "Manual Production",
        "Provider-Assisted",
        "/api/human-operator/provider-readiness",
        "Accepted-source review",
        "/api/human-operator/sources/status",
        "/api/human-operator/sources/review",
        "Render health and recovery",
        "/api/human-operator/render-health",
        "/api/human-operator/demo/render",
        "Phone review and publish packet",
        "/api/human-operator/phone-review",
        "/api/human-operator/publish-packet",
        "phone review 저장",
    ]:
        assert required in human_mvp

    for required in [
        "소재 DB / 제작 게이트 상태",
        "외부 조사로 쌓은 소재",
        "/api/topic-library/materials",
        "/api/production/status",
        "/api/topic-library/materials/dryrun-preflight",
        "Dry-run 사전 준비",
        "소재 seed + dry-run report 저장",
        "서버 production status 다음 행동",
        "현재 실행 중인 브리지가 오래된 코드입니다.",
        "소재 DB 열기",
        "기획으로 이동",
    ]:
        assert required in gate_status

    for required in [
        "전 과정 게이트 검수",
        "/api/production-gates/process-audit",
        "video-studio.production-process-gate-audit.v1",
        "현재 구현된 제작 프로세스가 대시보드, 게이트 코드, 테스트, 증거 요구사항에 매핑되어 있는지 확인합니다.",
        "12개 제작 단계가 코드, 테스트, 대시보드 surface, 증거 요구사항에 매핑되어 있습니다.",
    ]:
        assert required in process_audit

    for required in [
        "대시보드 제작 게이트",
        "소재 입력",
        "소재 검증",
        "스토리보드",
        "소스 확보",
        "프롬프트 품질",
        "편집 조립",
        "렌더 전 점검",
        "품질 검수",
        "게시 준비",
        "/api/production/status",
        "서버 production status 기준",
        "브리지 미연결: 화면 상태 fallback",
    ]:
        assert required in workflow_gate


def test_dashboard_ux_reference_doc_is_discoverable_and_enforceable():
    reference = _read("docs/reference/dashboard-ux-ia.md")

    for required in [
        "last_verified: 2026-06-25",
        "- video studio dashboard",
        "- dashboard UX",
        "- production workflow UI",
        "The reference ledger query for dashboard UX returns this document.",
        "sourceLedger",
        "material library",
        "production-wide gate",
        "dry-run readiness report",
        "/api/production/status",
        "/api/production/thin-loop/status",
    ]:
        assert required in reference

    for stage in ["`Home`", "`Topic`", "`Plan`", "`Sources`", "`Edit`", "`Review`", "`Advanced`"]:
        assert stage in reference


def test_production_status_panels_do_not_reuse_stale_server_truth():
    gate_status = _read("app/ui/src/components/ProductionGateStatusPanel.tsx")
    workflow_gate = _read("app/ui/src/components/ProductionWorkflowGatePanel.tsx")

    assert "setProductionStatus(null)" in gate_status
    assert "이전 서버 nextAction은 숨" in gate_status
    assert "productionStatusStale" in gate_status
    assert "window.setInterval" in workflow_gate
    assert "서버 production status 확인 실패" in workflow_gate
    assert "fallback gate는 현재 화면 상태만 반영" in workflow_gate
