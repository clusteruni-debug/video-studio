import { AlertTriangle, CheckCircle2, ClipboardCheck, FileVideo2, RotateCcw } from "lucide-react";
import { useStudioActions, useStudioState } from "../context/StudioContext";
import ProductionWorkflowGatePanel from "./ProductionWorkflowGatePanel";

export default function ReviewWorkspacePanel() {
  const { draftResult, renderResult } = useStudioState();
  const actions = useStudioActions();
  const renderPath = renderResult?.renderResult?.outputPath;
  const qualityPath = renderResult?.renderResult?.qualityReportPath;
  const manifestPath = renderResult?.renderResult?.manifestPath;

  return (
    <section className="workspace-panel review-workspace">
      <div className="workspace-panel-head">
        <div>
          <span className="workspace-kicker">검수 단계</span>
          <h2>렌더 파일이 출시 후보인지 판단합니다</h2>
          <p>파일 존재만으로 통과시키지 않고 품질 리포트, 자막/음성 싱크, 소스 통일성을 함께 봅니다.</p>
        </div>
        <button className="workflow-secondary-action" onClick={() => actions.setActiveTab("edit")}>
          <RotateCcw size={14} />
          편집으로
        </button>
      </div>

      <ProductionWorkflowGatePanel focus="review" />

      {renderPath ? (
        <div className="review-result-layout">
          <article className="review-primary-card pass">
            <CheckCircle2 size={20} />
            <span>렌더 후보 있음</span>
            <strong>{renderPath}</strong>
            <p>이 파일은 검수 후보입니다. 출시 가능 판단은 품질 리포트와 실제 시청 검토 후에만 가능합니다.</p>
          </article>
          <div className="review-evidence-list">
            <div>
              <FileVideo2 size={16} />
              <span>렌더 파일</span>
              <strong>{renderPath}</strong>
            </div>
            <div>
              <ClipboardCheck size={16} />
              <span>매니페스트</span>
              <strong>{manifestPath || "없음"}</strong>
            </div>
            <div>
              <ClipboardCheck size={16} />
              <span>품질 리포트</span>
              <strong>{qualityPath || "없음"}</strong>
            </div>
          </div>
        </div>
      ) : (
        <div className="review-empty-state">
          <AlertTriangle size={22} />
          <strong>검수할 렌더 후보가 없습니다</strong>
          <p>{draftResult?.ok ? "편집 단계에서 MP4 후보를 먼저 생성하세요." : "기획 초안이 없어서 렌더 후보를 만들 수 없습니다."}</p>
          <button className="workspace-primary-action" onClick={() => actions.setActiveTab(draftResult?.ok ? "edit" : "plan")}>
            {draftResult?.ok ? "편집 단계로 이동" : "기획 단계로 이동"}
          </button>
        </div>
      )}
    </section>
  );
}
