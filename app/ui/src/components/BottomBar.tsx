import { Terminal, Play, Film } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";

export default function BottomBar() {
  const { bridgeStatus, creating, rendering, error, draftResult, renderResult } = useStudioState();
  const actions = useStudioActions();

  let statusMessage = "";
  let statusClass = "";
  if (creating) {
    statusMessage = "초안 생성 중...";
  } else if (rendering) {
    statusMessage = "MP4 렌더 중...";
  } else if (error) {
    statusMessage = error;
    statusClass = "error";
  } else if (renderResult?.renderResult?.outputPath) {
    statusMessage = renderResult.renderResult.outputPath;
    statusClass = "success";
  } else if (draftResult?.ok) {
    statusMessage = `${draftResult.scenes?.length ?? 0}씬 생성 완료`;
    statusClass = "success";
  }

  return (
    <div className="bottom-bar">
      <div className="bottom-bar-actions">
        <button className="bottom-bar-btn" onClick={actions.toggleDebug}>
          <Terminal size={14} style={{ verticalAlign: "middle", marginRight: 4 }} />
          디버그
        </button>
        <button
          className="bottom-bar-btn accent"
          disabled={!draftResult?.ok || creating || rendering}
          onClick={actions.renderCurrentDraft}
        >
          <Film size={14} style={{ verticalAlign: "middle", marginRight: 4 }} />
          MP4 렌더
        </button>
        <button
          className="bottom-bar-btn"
          disabled={!draftResult?.ok || creating || rendering}
          onClick={actions.submitJob}
        >
          <Play size={14} style={{ verticalAlign: "middle", marginRight: 4 }} />
          작업 큐 추가
        </button>
      </div>

      <span className={`bottom-bar-status ${statusClass}`}>
        {statusMessage}
      </span>

      <div className="bottom-bar-indicator">
        <span className={`bridge-dot bridge-dot-${bridgeStatus}`} />
      </div>
    </div>
  );
}
