import { Captions, Film, Music2, Play, Scissors, Volume2 } from "lucide-react";
import { useStudioActions, useStudioState } from "../context/StudioContext";
import ProductionWorkflowGatePanel from "./ProductionWorkflowGatePanel";

const editChecks = [
  {
    title: "컷과 리듬",
    body: "장면 전환은 길이가 끝나서가 아니라 새 정보나 행동 변화가 있을 때만 통과합니다.",
    icon: Scissors,
  },
  {
    title: "자막",
    body: "TTS를 그대로 반복하지 않고 핵심 판단과 화면 읽기를 돕는 문장으로 정리합니다.",
    icon: Captions,
  },
  {
    title: "음성",
    body: "장면 타이밍과 자막 위치가 어긋나면 렌더 전 기획 단계로 되돌립니다.",
    icon: Volume2,
  },
  {
    title: "BGM과 효과음",
    body: "효과음은 보이는 사건, 컷, 전환에 붙을 때만 사용합니다.",
    icon: Music2,
  },
];

export default function EditWorkspacePanel() {
  const { draftResult, rendering, renderResult } = useStudioState();
  const actions = useStudioActions();
  const scenes = draftResult?.scenes ?? [];
  const canRender = !!draftResult?.ok && scenes.length > 0 && !rendering;

  return (
    <section className="workspace-panel">
      <div className="workspace-panel-head">
        <div>
          <span className="workspace-kicker">편집 단계</span>
          <h2>렌더 전에 자막, 음성, 오디오, 컷 이유를 확인합니다</h2>
          <p>후편집은 장식이 아니라 화면 이해를 더 선명하게 만드는 층이어야 합니다.</p>
        </div>
        <button className="workspace-primary-action" disabled={!canRender} onClick={actions.renderCurrentDraft}>
          {rendering ? "렌더 중" : "MP4 렌더"}
          <Play size={15} />
        </button>
      </div>

      <div className="edit-readiness-strip">
        <div>
          <span>초안</span>
          <strong>{draftResult?.ok ? `${scenes.length}씬` : "없음"}</strong>
        </div>
        <div>
          <span>렌더</span>
          <strong>{renderResult?.renderResult?.outputPath ? "후보 있음" : "대기"}</strong>
        </div>
        <div>
          <span>다음</span>
          <strong>{renderResult?.renderResult?.outputPath ? "검수" : "렌더 후보"}</strong>
        </div>
      </div>

      <ProductionWorkflowGatePanel focus="edit" />

      <div className="edit-check-grid">
        {editChecks.map(({ title, body, icon: Icon }) => (
          <article key={title} className="edit-check-card">
            <Icon size={18} />
            <strong>{title}</strong>
            <p>{body}</p>
          </article>
        ))}
      </div>

      <div className="edit-action-row">
        <button className="workflow-secondary-action" onClick={() => actions.setActiveTab("plan")}>
          <Film size={14} />
          기획 수정
        </button>
        <button className="workflow-secondary-action" onClick={() => actions.setActiveTab("sources")}>
          소스 확인
        </button>
        <button className="workflow-secondary-action" onClick={() => actions.setActiveTab("review")} disabled={!renderResult?.renderResult?.outputPath}>
          검수로 이동
        </button>
      </div>
    </section>
  );
}
