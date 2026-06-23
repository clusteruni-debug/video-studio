import { useState } from "react";
import { ArrowRight, Briefcase, Layers, Library, ShieldCheck } from "lucide-react";
import BatchPanel from "./BatchPanel";
import GatesPanel from "./GatesPanel";
import JobsPanel from "./JobsPanel";
import { FinalVideoLibraryPanel } from "./RenderReviewPanel";
import ProductionProcessAuditPanel from "./ProductionProcessAuditPanel";
import ProductionWorkflowGatePanel from "./ProductionWorkflowGatePanel";

type AdvancedMode = "overview" | "gates" | "library" | "batch" | "jobs";

const ADVANCED_TOOLS: {
  mode: Exclude<AdvancedMode, "overview">;
  title: string;
  body: string;
  meta: string;
  icon: typeof ShieldCheck;
}[] = [
  {
    mode: "gates",
    title: "게이트 원본",
    body: "소재/롱폼 검증의 상세 입력과 실패 항목을 확인합니다.",
    meta: "검증 진단",
    icon: ShieldCheck,
  },
  {
    mode: "library",
    title: "최종 라이브러리",
    body: "렌더 후보, 증거 템플릿, 업로드 전 검수 자료를 점검합니다.",
    meta: "출시 증거",
    icon: Library,
  },
  {
    mode: "batch",
    title: "배치",
    body: "여러 변형 초안을 반복 생성할 때만 사용합니다.",
    meta: "반복 생성",
    icon: Layers,
  },
  {
    mode: "jobs",
    title: "작업 큐",
    body: "백그라운드 작업 상태와 실패 작업을 확인합니다.",
    meta: "운영 상태",
    icon: Briefcase,
  },
];

export default function AdvancedOpsPanel() {
  const [mode, setMode] = useState<AdvancedMode>("overview");
  const [detailOpen, setDetailOpen] = useState(false);
  const selectedTool = ADVANCED_TOOLS.find((tool) => tool.mode === mode);
  const SelectedIcon = selectedTool?.icon;

  const selectMode = (nextMode: AdvancedMode) => {
    setMode(nextMode);
    setDetailOpen(false);
  };

  return (
    <section className="workspace-panel">
      <div className="workspace-panel-head">
        <div>
          <span className="workspace-kicker">고급 운영</span>
          <h2>원본 게이트와 배치 작업은 필요할 때만 엽니다</h2>
          <p>일상 제작 화면에서는 숨기고, 문제 진단과 반복 실행이 필요할 때 이곳에서 확인합니다.</p>
        </div>
      </div>

      <div className="workflow-subnav">
        <button className={mode === "overview" ? "active" : ""} onClick={() => selectMode("overview")}>
          개요
        </button>
        <button className={mode === "gates" ? "active" : ""} onClick={() => selectMode("gates")}>
          <ShieldCheck size={14} />
          게이트 원본
        </button>
        <button className={mode === "library" ? "active" : ""} onClick={() => selectMode("library")}>
          <Library size={14} />
          최종 라이브러리
        </button>
        <button className={mode === "batch" ? "active" : ""} onClick={() => selectMode("batch")}>
          <Layers size={14} />
          배치
        </button>
        <button className={mode === "jobs" ? "active" : ""} onClick={() => selectMode("jobs")}>
          <Briefcase size={14} />
          작업 큐
        </button>
      </div>

      <div className="workspace-embedded-panel">
        {mode === "overview" && (
          <>
            <ProductionWorkflowGatePanel focus="all" compact />
            <ProductionProcessAuditPanel />
            <div className="advanced-overview-grid">
              {ADVANCED_TOOLS.map(({ mode: toolMode, title, body, meta, icon: Icon }) => (
                <button key={toolMode} className="advanced-overview-card" onClick={() => selectMode(toolMode)}>
                  <div className="advanced-overview-icon">
                    <Icon size={18} />
                  </div>
                  <div>
                    <span>{meta}</span>
                    <strong>{title}</strong>
                    <p>{body}</p>
                  </div>
                  <ArrowRight size={15} />
                </button>
              ))}
            </div>
          </>
        )}
        {selectedTool && SelectedIcon && (
          <div className="advanced-detail-shell">
            <div className="advanced-detail-intro">
              <div className="advanced-overview-icon">
                <SelectedIcon size={18} />
              </div>
              <div>
                <span>{selectedTool.meta}</span>
                <strong>{selectedTool.title}</strong>
                <p>{selectedTool.body}</p>
              </div>
              <button className="workflow-secondary-action" onClick={() => setDetailOpen((open) => !open)}>
                {detailOpen ? "세부 접기" : "세부 운영 패널 열기"}
              </button>
            </div>
            {!detailOpen && (
              <div className="advanced-detail-placeholder">
                <strong>기본 제작 흐름에서는 여기서 멈춥니다</strong>
                <p>아래 세부 패널은 원본 로그, 증거 경로, 배치 상태처럼 문제 진단용 정보가 많습니다. 필요한 경우에만 열어 확인하세요.</p>
              </div>
            )}
            {detailOpen && mode === "gates" && <GatesPanel />}
            {detailOpen && mode === "library" && <FinalVideoLibraryPanel autoLoad />}
            {detailOpen && mode === "batch" && <BatchPanel />}
            {detailOpen && mode === "jobs" && <JobsPanel />}
          </div>
        )}
      </div>
    </section>
  );
}
