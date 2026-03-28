import { useState } from "react";
import { X, ImagePlus, Search } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";

type ImageSource = "pexels" | "flux";

const SOURCE_LABELS: Record<ImageSource, string> = {
  pexels: "Pexels",
  flux: "FLUX AI",
};

export default function SceneDetailPanel() {
  const { draftResult, selectedSceneIndex } = useStudioState();
  const actions = useStudioActions();
  const [editingPrompt, setEditingPrompt] = useState(false);
  const [promptDraft, setPromptDraft] = useState("");

  if (selectedSceneIndex === null || !draftResult?.scenes?.[selectedSceneIndex]) return null;

  const scene = draftResult.scenes[selectedSceneIndex];
  const currentSource = (scene.image_source as ImageSource) || "pexels";

  const handleSourceChange = (src: ImageSource) => {
    actions.editScene(selectedSceneIndex, "image_source", src);
  };

  const handlePromptEdit = () => {
    setPromptDraft(scene.image_prompt || "");
    setEditingPrompt(true);
  };

  const commitPrompt = () => {
    setEditingPrompt(false);
    if (promptDraft !== scene.image_prompt) {
      actions.editScene(selectedSceneIndex, "image_prompt", promptDraft);
    }
  };

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

      {/* Image source toggle */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: 6 }}>이미지 소스</div>
        <div className="mode-toggle duration-toggle">
          {(["pexels", "flux"] as ImageSource[]).map((src) => (
            <button
              key={src}
              className={`mode-toggle-btn duration-toggle-btn ${currentSource === src ? "active" : ""}`}
              onClick={() => handleSourceChange(src)}
            >
              {SOURCE_LABELS[src]}
            </button>
          ))}
        </div>
      </div>

      {/* Image prompt */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: 4 }}>
          {currentSource === "flux" ? "AI 이미지 프롬프트" : "검색어"}
        </div>
        {editingPrompt ? (
          <textarea
            className="editable-input"
            value={promptDraft}
            onChange={(e) => setPromptDraft(e.target.value)}
            onBlur={commitPrompt}
            onKeyDown={(e) => {
              if (e.key === "Escape") setEditingPrompt(false);
            }}
            rows={2}
            autoFocus
          />
        ) : (
          <div className="editable-text" onClick={handlePromptEdit}>
            {scene.image_prompt || <span className="editable-placeholder">이미지 프롬프트 입력...</span>}
          </div>
        )}
      </div>

      {/* Generate button */}
      <div style={{ marginBottom: 12 }}>
        <button
          className="chip"
          onClick={() => {
            if (scene.image_prompt) {
              actions.enqueueImages([scene]);
              actions.setActiveTab("images");
            }
          }}
          disabled={!scene.image_prompt}
        >
          {currentSource === "flux" ? (
            <><ImagePlus size={12} /> FLUX 이미지 생성</>
          ) : (
            <><Search size={12} /> Pexels 검색</>
          )}
        </button>
      </div>

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
    </div>
  );
}
