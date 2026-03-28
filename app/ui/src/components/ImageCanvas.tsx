import { useState } from "react";
import { ImageIcon, Trash2, RefreshCw } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";

export default function ImageCanvas() {
  const { imageItems, imageQueueProcessing, draftResult } = useStudioState();
  const actions = useStudioActions();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const doneCount = imageItems.filter((i) => i.status === "done").length;
  const failedCount = imageItems.filter((i) => i.status === "failed").length;
  const selectedItem = imageItems.find((i) => i.id === selectedId);

  // Generate all images from draft
  const handleGenerateAll = () => {
    if (draftResult?.scenes) {
      actions.enqueueImages(draftResult.scenes);
    }
  };

  if (imageItems.length === 0) {
    return (
      <div className="canvas-empty">
        <div className="canvas-empty-icon"><ImageIcon size={28} /></div>
        <h2>이미지 캔버스</h2>
        <p>스토리보드에서 이미지를 생성하면 여기에 표시됩니다</p>
        {draftResult?.scenes && draftResult.scenes.length > 0 && (
          <button className="chip" onClick={handleGenerateAll}>
            전체 씬 이미지 생성
          </button>
        )}
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="image-canvas-header">
        <span style={{ flex: 1, fontWeight: 600, fontSize: "0.88rem" }}>
          이미지 ({doneCount}/{imageItems.length})
          {failedCount > 0 && <span style={{ color: "var(--error)", marginLeft: 8 }}>실패 {failedCount}</span>}
        </span>
        {imageQueueProcessing && (
          <span style={{ fontSize: "0.78rem", color: "var(--text-secondary)" }}>생성 중...</span>
        )}
        <button className="subtle-button" onClick={actions.clearImages}>
          <Trash2 size={12} /> 초기화
        </button>
      </div>

      {/* Progress */}
      {imageQueueProcessing && (
        <div className="batch-progress" style={{ marginTop: 12 }}>
          <span className="batch-progress-stats">{doneCount}/{imageItems.length} 완료</span>
          <div className="batch-progress-bar">
            <div
              className="batch-progress-fill"
              style={{ width: `${imageItems.length ? (doneCount / imageItems.length) * 100 : 0}%` }}
            />
          </div>
        </div>
      )}

      {/* Gallery */}
      <div className="image-gallery" style={{ marginTop: 12 }}>
        {imageItems.map((item) => (
          <div
            key={item.id}
            className={`image-gallery-item ${selectedId === item.id ? "selected" : ""}`}
          >
            <button
              className="image-gallery-select"
              onClick={() => setSelectedId(selectedId === item.id ? null : item.id)}
            >
              {item.status === "done" && item.result ? (
                <img src={item.result.url} alt={item.prompt} style={{ aspectRatio: "9/16" }} />
              ) : (
                <div className="scene-card-placeholder" style={{ aspectRatio: "9/16" }} />
              )}
            </button>
            {item.status === "failed" && (
              <button
                className="image-gallery-remove"
                style={{ opacity: 1, background: "var(--warning)" }}
                onClick={() => actions.retryImage(item.id)}
              >
                <RefreshCw size={10} />
              </button>
            )}
            {item.status !== "failed" && (
              <button className="image-gallery-remove" onClick={() => setSelectedId(null)}>
                <Trash2 size={10} />
              </button>
            )}
            {item.status === "generating" && (
              <div style={{
                position: "absolute", inset: 0,
                display: "flex", alignItems: "center", justifyContent: "center",
                background: "rgba(0,0,0,0.4)", backdropFilter: "blur(2px)",
                color: "#fff", fontSize: "0.75rem",
              }}>
                생성 중...
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Preview */}
      {selectedItem?.status === "done" && selectedItem.result && (
        <div className="image-preview-panel" style={{ marginTop: 16 }}>
          <div className="image-preview-img-wrap">
            <img src={selectedItem.result.url} alt={selectedItem.prompt} />
          </div>
          <div className="image-preview-info">
            <p className="image-preview-prompt">{selectedItem.prompt}</p>
            <span className="image-preview-meta">
              {selectedItem.engine} / {selectedItem.width}x{selectedItem.height}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
