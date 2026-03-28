import { Film } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";
import SceneDetailPanel from "./SceneDetailPanel";

export default function StoryboardPanel() {
  const { draftResult, selectedSceneIndex } = useStudioState();
  const actions = useStudioActions();

  if (!draftResult) {
    return (
      <div className="canvas-empty">
        <div className="canvas-empty-icon"><Film size={28} /></div>
        <h2>스토리보드</h2>
        <p>왼쪽에서 주제를 입력하고 초안을 생성하세요</p>
      </div>
    );
  }

  const scenes = draftResult.scenes ?? [];

  return (
    <div>
      {/* Header summary */}
      <div className="canvas-header">
        <span className="canvas-header-title">{draftResult.message || "초안 생성 완료"}</span>
        <span className="canvas-header-meta">
          {scenes.length}씬 / {draftResult.total_duration?.toFixed(1)}s / {draftResult.tts_provider}
        </span>
      </div>

      {/* Scene grid */}
      <div className="scene-grid" style={{ marginTop: 16 }}>
        {scenes.map((scene, i) => (
          <button
            key={scene.scene_num}
            className={`scene-card-visual ${selectedSceneIndex === i ? "selected" : ""}`}
            onClick={() => actions.selectScene(selectedSceneIndex === i ? null : i)}
          >
            <div className="scene-card-thumb">
              <div className="scene-card-placeholder" />
              <div className="scene-card-overlays">
                <span className="scene-card-duration">{scene.duration}s</span>
                {scene.emotion !== "neutral" && (
                  <span className="scene-card-duration">{scene.emotion}</span>
                )}
              </div>
            </div>
            <div className="scene-card-info">
              <strong>
                {scene.rank != null ? `#${scene.rank} ` : ""}씬 {scene.scene_num}
              </strong>
              <span>{scene.display_text?.slice(0, 50) || scene.narration.slice(0, 50)}</span>
            </div>
          </button>
        ))}
      </div>

      {/* Scene detail */}
      {selectedSceneIndex !== null && scenes[selectedSceneIndex] && (
        <div style={{ marginTop: 16 }}>
          <SceneDetailPanel />
        </div>
      )}
    </div>
  );
}
