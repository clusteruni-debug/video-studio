import { X, ImagePlus } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";

export default function SceneDetailPanel() {
  const { draftResult, selectedSceneIndex } = useStudioState();
  const actions = useStudioActions();

  if (selectedSceneIndex === null || !draftResult?.scenes?.[selectedSceneIndex]) return null;

  const scene = draftResult.scenes[selectedSceneIndex];

  return (
    <div className="scene-detail">
      {/* Header */}
      <div className="scene-detail-header">
        <div className="scene-detail-title-group">
          <h3>씬 {scene.scene_num}</h3>
          <span className="route-badge route-local">LOCAL</span>
          <span className="scene-detail-duration">{scene.duration}s</span>
        </div>
        <button className="scene-detail-close" onClick={() => actions.selectScene(null)}>
          <X size={14} />
        </button>
      </div>

      {/* Image prompt */}
      {scene.image_prompt && (
        <p className="scene-detail-prompt">{scene.image_prompt}</p>
      )}

      {/* Meta */}
      <div className="scene-detail-meta">
        <div className="scene-detail-scores">
          <span>감정: {scene.emotion}</span>
          {scene.rank != null && <span>순위: #{scene.rank}</span>}
          <span>이미지: {scene.has_image ? "있음" : "없음"}</span>
        </div>
      </div>

      {/* Assets */}
      <div className="scene-detail-assets">
        {/* Narration */}
        <div className="scene-detail-asset-row">
          <div className="scene-detail-asset-info">
            <span className="scene-detail-asset-status">나레이션</span>
            <div style={{ fontSize: "0.85rem", lineHeight: 1.6, whiteSpace: "pre-line" }}>
              {scene.narration}
            </div>
          </div>
        </div>

        {/* Display text */}
        {scene.display_text && (
          <div className="scene-detail-asset-row">
            <div className="scene-detail-asset-info">
              <span className="scene-detail-asset-status">자막</span>
              <div style={{ fontSize: "0.85rem", lineHeight: 1.6, whiteSpace: "pre-line" }}>
                {scene.display_text}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Footer actions */}
      <div className="scene-detail-footer">
        <div>
          <strong>에셋</strong>
          <br />
          <small>{scene.has_image ? "이미지 준비됨" : "이미지 없음"}</small>
        </div>
        <div className="scene-detail-asset-actions">
          <button
            className="chip"
            onClick={() => {
              if (scene.image_prompt) {
                actions.enqueueImages([scene]);
                actions.setActiveTab("images");
              }
            }}
          >
            <ImagePlus size={12} /> 이미지 생성
          </button>
        </div>
      </div>
    </div>
  );
}
