import { useState, useRef, useEffect, useCallback } from "react";
import { Film, Plus, Trash2, ChevronUp, ChevronDown, Play, Square, RotateCcw } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";
import SceneDetailPanel from "./SceneDetailPanel";
import ProductionWorkflowGatePanel from "./ProductionWorkflowGatePanel";

function EditableText({
  value,
  onChange,
  placeholder,
  multiline,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  multiline?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const ref = useRef<HTMLTextAreaElement | HTMLInputElement>(null);

  useEffect(() => { if (!editing) setDraft(value); }, [value, editing]);
  useEffect(() => { if (editing) ref.current?.focus(); }, [editing]);

  if (!editing) {
    return (
      <div
        className="editable-text"
        onClick={() => setEditing(true)}
        title="클릭하여 편집"
      >
        {value || <span className="editable-placeholder">{placeholder}</span>}
      </div>
    );
  }

  const commit = () => {
    setEditing(false);
    if (draft !== value) onChange(draft);
  };

  if (multiline) {
    return (
      <textarea
        ref={ref as React.RefObject<HTMLTextAreaElement>}
        className="editable-input"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Escape") { setDraft(value); setEditing(false); } }}
        rows={3}
      />
    );
  }

  return (
    <input
      ref={ref as React.RefObject<HTMLInputElement>}
      className="editable-input"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") { setDraft(value); setEditing(false); }
      }}
    />
  );
}

export default function StoryboardPanel() {
  const { draftResult, selectedSceneIndex } = useStudioState();
  const actions = useStudioActions();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);

  const playTts = useCallback((url: string) => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
    }
    const audio = new Audio(url);
    audioRef.current = audio;
    setPlaying(true);
    audio.play().catch(() => {});
    audio.addEventListener("ended", () => setPlaying(false), { once: true });
  }, []);

  const stopTts = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    setPlaying(false);
  }, []);

  if (!draftResult) {
    return (
      <div className="storyboard-dashboard">
        <div className="canvas-empty">
          <div className="canvas-empty-icon"><Film size={28} /></div>
          <h2>스토리보드</h2>
          <p>왼쪽에서 주제를 입력하고 초안을 생성하세요</p>
        </div>
        <ProductionWorkflowGatePanel focus="plan" />
      </div>
    );
  }

  const scenes = draftResult.scenes ?? [];

  return (
    <div>
      {/* Header summary */}
      <div className="canvas-header">
        <span className="canvas-header-title">{draftResult.message || "초안 생성 완료"}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="canvas-header-meta">
            {scenes.length}씬 / {draftResult.total_duration?.toFixed(1)}s / {draftResult.tts_provider}
          </span>
          <button
            className="scene-action-btn"
            title="새로 시작"
            onClick={() => { stopTts(); actions.clearDraft(); }}
          >
            <RotateCcw size={14} />
          </button>
        </div>
      </div>

      <ProductionWorkflowGatePanel focus="plan" />

      {/* Scene list (vertical) */}
      <div className="scene-list" style={{ marginTop: 16 }}>
        {scenes.map((scene, i) => (
          (() => {
            const videoThumb = scene._upload_kind === "video"
              ? scene._upload_preview
              : (scene._video_url || scene._selected_pexels_video?.url || null);
            const imageThumb = videoThumb ? null : (scene._upload_preview || scene._image_url || null);
            return (
          <div
            key={`scene-${i}`}
            className={`scene-row ${selectedSceneIndex === i ? "selected" : ""}`}
            onClick={() => actions.selectScene(selectedSceneIndex === i ? null : i)}
          >
            {/* Left: scene number + thumbnail + emotion badge */}
            <div className="scene-row-num">
              {videoThumb ? (
                <video
                  src={videoThumb}
                  muted
                  playsInline
                  style={{ width: 36, height: 48, objectFit: "cover", borderRadius: 4 }}
                />
              ) : imageThumb ? (
                <img
                  src={imageThumb}
                  alt={`씬 ${scene.scene_num}`}
                  style={{ width: 36, height: 48, objectFit: "cover", borderRadius: 4 }}
                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
              ) : (
                <span className="scene-num-badge">{scene.scene_num}</span>
              )}
              {scene.emotion !== "neutral" && (
                <span className={`scene-emotion-badge scene-emotion-${scene.emotion}`}>{scene.emotion}</span>
              )}
            </div>

            {/* Center: editable narration + display_text */}
            <div className="scene-row-content" onClick={(e) => e.stopPropagation()}>
              <div className="scene-row-narration">
                <EditableText
                  value={scene.narration}
                  onChange={(v) => actions.editScene(i, "narration", v)}
                  placeholder="나레이션 입력..."
                  multiline
                />
              </div>
              <div className="scene-row-display-text">
                <EditableText
                  value={scene.display_text}
                  onChange={(v) => actions.editScene(i, "display_text", v)}
                  placeholder="자막 입력..."
                />
              </div>
            </div>

            {/* Right: actions */}
            <div className="scene-row-actions" onClick={(e) => e.stopPropagation()}>
              <button
                className="scene-action-btn"
                title="위로"
                disabled={i === 0}
                onClick={() => actions.reorderScene(i, i - 1)}
              >
                <ChevronUp size={14} />
              </button>
              <button
                className="scene-action-btn"
                title="아래로"
                disabled={i === scenes.length - 1}
                onClick={() => actions.reorderScene(i, i + 1)}
              >
                <ChevronDown size={14} />
              </button>
              <button
                className="scene-action-btn"
                title="씬 추가"
                onClick={() => actions.addScene(i)}
              >
                <Plus size={14} />
              </button>
              {scene._tts_url ? (
                <button
                  className="scene-action-btn"
                  title="TTS 미리듣기"
                  onClick={() => playTts(scene._tts_url!)}
                >
                  <Play size={14} />
                </button>
              ) : null}
              {playing && (
                <button
                  className="scene-action-btn"
                  title="정지"
                  onClick={stopTts}
                >
                  <Square size={14} />
                </button>
              )}
              <button
                className="scene-action-btn scene-action-delete"
                title="씬 삭제"
                disabled={scenes.length <= 1}
                onClick={() => actions.deleteScene(i)}
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
            );
          })()
        ))}
      </div>

      {/* Add scene at end */}
      <button
        className="scene-add-end"
        onClick={() => actions.addScene(scenes.length - 1)}
      >
        <Plus size={14} /> 씬 추가
      </button>

      {/* Mobile fallback: inline detail (hidden on desktop where right-panel shows) */}
      {selectedSceneIndex !== null && scenes[selectedSceneIndex] && (
        <div className="mobile-scene-detail">
          <SceneDetailPanel />
        </div>
      )}
    </div>
  );
}
