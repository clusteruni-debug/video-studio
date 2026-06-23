import { useState } from "react";
import { FileImage, FolderOpen } from "lucide-react";
import ImageCanvas from "./ImageCanvas";
import SourcesPanel from "./SourcesPanel";
import { useStudioState } from "../context/StudioContext";
import ProductionWorkflowGatePanel from "./ProductionWorkflowGatePanel";

type SourceWorkspaceMode = "library" | "generate";

export default function SourcesWorkspacePanel() {
  const [mode, setMode] = useState<SourceWorkspaceMode>("library");
  const { draftResult, imageItems } = useStudioState();
  const sceneCount = draftResult?.scenes?.length ?? 0;
  const imageDoneCount = imageItems.filter((item) => item.status === "done").length;

  return (
    <section className="workspace-panel">
      <div className="workspace-panel-head">
        <div>
          <span className="workspace-kicker">소스 단계</span>
          <h2>소스 수집과 생성은 같은 단계에서 관리합니다</h2>
          <p>장면별 소스가 비어 있으면 후편집 효과보다 먼저 막힙니다.</p>
        </div>
        <div className="workspace-stat-strip">
          <span>씬 {sceneCount}</span>
          <span>이미지 {imageDoneCount}</span>
        </div>
      </div>

      <ProductionWorkflowGatePanel focus="sources" />

      <div className="workflow-subnav">
        <button className={mode === "library" ? "active" : ""} onClick={() => setMode("library")}>
          <FolderOpen size={14} />
          소스 찾기
        </button>
        <button className={mode === "generate" ? "active" : ""} onClick={() => setMode("generate")}>
          <FileImage size={14} />
          이미지 생성
        </button>
      </div>

      <div className="workspace-embedded-panel">
        {mode === "library" ? <SourcesPanel /> : <ImageCanvas />}
      </div>
    </section>
  );
}
