import { useState, useRef, useCallback, useEffect } from "react";
import { X, ImagePlus, Search, Upload, Sparkles, Play, Square, RefreshCw } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";

type ImageSource = "pexels" | "flux" | "imagen" | "upload";

const SOURCE_LABELS: Record<ImageSource, { label: string; icon: typeof Search }> = {
  pexels: { label: "Pexels", icon: Search },
  flux: { label: "FLUX AI", icon: Sparkles },
  imagen: { label: "Imagen 4", icon: Sparkles },
  upload: { label: "업로드", icon: Upload },
};
const SOURCE_KEYS: ImageSource[] = ["pexels", "flux", "imagen", "upload"];

export default function SceneDetailPanel() {
  const { draftResult, selectedSceneIndex } = useStudioState();
  const actions = useStudioActions();
  const [editingPrompt, setEditingPrompt] = useState(false);
  const [promptDraft, setPromptDraft] = useState("");
  const [editingNarration, setEditingNarration] = useState(false);
  const [narrationDraft, setNarrationDraft] = useState("");
  const [regenerating, setRegenerating] = useState(false);
  const [regeneratingImage, setRegeneratingImage] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Cleanup audio on scene switch or unmount
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.src = "";
        audioRef.current = null;
      }
      setPlaying(false);
    };
  }, [selectedSceneIndex]);

  const playTts = useCallback((url: string) => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current.src = ""; }
    const audio = new Audio(url);
    audioRef.current = audio;
    setPlaying(true);
    audio.play().catch(() => {});
    audio.addEventListener("ended", () => setPlaying(false), { once: true });
  }, []);

  const stopTts = useCallback(() => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current.src = ""; audioRef.current = null; }
    setPlaying(false);
  }, []);

  if (selectedSceneIndex === null || !draftResult?.scenes?.[selectedSceneIndex]) return null;

  const scene = draftResult.scenes[selectedSceneIndex];
  const currentSource = (scene.image_source as ImageSource) || "pexels";

  const handleSourceChange = (src: ImageSource) => {
    actions.editScene(selectedSceneIndex, "image_source", src);
    if (src === "upload") fileInputRef.current?.click();
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

  const handleNarrationEdit = () => {
    setNarrationDraft(scene.narration || "");
    setEditingNarration(true);
  };

  const commitNarration = () => {
    setEditingNarration(false);
    if (narrationDraft !== scene.narration) {
      actions.editScene(selectedSceneIndex, "narration", narrationDraft);
    }
  };

  const handleRegenTts = async () => {
    setRegenerating(true);
    try {
      await actions.regenerateSceneTts(selectedSceneIndex);
    } finally {
      setRegenerating(false);
    }
  };

  const handleRegenImage = async () => {
    setRegeneratingImage(true);
    try {
      await actions.regenerateSceneImage(selectedSceneIndex);
    } finally {
      setRegeneratingImage(false);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) actions.uploadSceneImage(selectedSceneIndex, file);
    e.target.value = "";
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
          {SOURCE_KEYS.map((src) => (
            <button
              key={src}
              className={`mode-toggle-btn duration-toggle-btn ${currentSource === src ? "active" : ""}`}
              onClick={() => handleSourceChange(src)}
            >
              {SOURCE_LABELS[src].label}
            </button>
          ))}
        </div>
      </div>

      {/* Image preview — upload preview takes priority, then server image */}
      {(scene._upload_preview || scene._image_url) && (
        <div style={{ marginBottom: 12, borderRadius: 6, overflow: "hidden", position: "relative" }}>
          <img
            src={scene._upload_preview || scene._image_url!}
            alt={scene._upload_preview ? "업로드 이미지" : "생성된 이미지"}
            style={{ width: "100%", maxHeight: 200, objectFit: "cover", display: "block" }}
          />
          {scene._image_url && !scene._upload_preview && scene.image_source && (
            <span style={{
              position: "absolute", bottom: 4, right: 4, fontSize: "0.65rem",
              background: "rgba(0,0,0,0.6)", color: "#fff", padding: "2px 6px", borderRadius: 4,
            }}>
              {scene.image_source}
            </span>
          )}
        </div>
      )}

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        style={{ display: "none" }}
        onChange={handleFileUpload}
      />

      {/* Upload button (when source is upload but no preview yet) */}
      {currentSource === "upload" && !scene._upload_preview && (
        <div style={{ marginBottom: 12 }}>
          <button className="chip" onClick={() => fileInputRef.current?.click()}>
            <Upload size={12} /> 이미지 선택
          </button>
        </div>
      )}

      {/* Image prompt (for non-upload sources) */}
      {currentSource !== "upload" && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: 4 }}>
            {currentSource === "pexels" ? "검색어" : "AI 이미지 프롬프트"}
          </div>
          {editingPrompt ? (
            <textarea
              className="editable-input"
              value={promptDraft}
              onChange={(e) => setPromptDraft(e.target.value)}
              onBlur={commitPrompt}
              onKeyDown={(e) => { if (e.key === "Escape") setEditingPrompt(false); }}
              rows={2}
              autoFocus
            />
          ) : (
            <div className="editable-text" onClick={handlePromptEdit}>
              {scene.image_prompt || <span className="editable-placeholder">이미지 프롬프트 입력...</span>}
            </div>
          )}
        </div>
      )}

      {/* Generate / regenerate button (for non-upload sources) */}
      {currentSource !== "upload" && (
        <div style={{ marginBottom: 12 }}>
          <button
            className="chip"
            onClick={handleRegenImage}
            disabled={!scene.image_prompt || regeneratingImage}
          >
            {regeneratingImage ? (
              <><RefreshCw size={12} className="spin" /> 생성 중...</>
            ) : currentSource === "pexels" ? (
              <><Search size={12} /> {scene._image_url ? "다른 이미지 검색" : "Pexels 검색"}</>
            ) : (
              <><ImagePlus size={12} /> {scene._image_url ? "이미지 재생성" : `${currentSource === "imagen" ? "Imagen 4" : "FLUX"} 생성`}</>
            )}
          </button>
        </div>
      )}

      {/* Narration editing */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: 4 }}>나레이션</div>
        {editingNarration ? (
          <textarea
            className="editable-input"
            value={narrationDraft}
            onChange={(e) => setNarrationDraft(e.target.value)}
            onBlur={commitNarration}
            onKeyDown={(e) => { if (e.key === "Escape") setEditingNarration(false); }}
            rows={4}
            autoFocus
          />
        ) : (
          <div className="editable-text" onClick={handleNarrationEdit} style={{ lineHeight: 1.6 }}>
            {scene.narration || <span className="editable-placeholder">나레이션 입력...</span>}
          </div>
        )}
      </div>

      {/* TTS preview + regenerate */}
      <div style={{ marginBottom: 12, display: "flex", gap: 8 }}>
        {scene._tts_url && (
          playing ? (
            <button className="chip" onClick={stopTts}>
              <Square size={12} /> 정지
            </button>
          ) : (
            <button className="chip" onClick={() => playTts(scene._tts_url!)}>
              <Play size={12} /> TTS 미리듣기
            </button>
          )
        )}
        <button
          className="chip"
          onClick={handleRegenTts}
          disabled={regenerating || !scene.narration}
          title="나레이션 텍스트로 TTS 재생성"
        >
          <RefreshCw size={12} className={regenerating ? "spin" : ""} />
          {regenerating ? "생성 중..." : "TTS 재생성"}
        </button>
      </div>

      {/* Meta */}
      <div className="scene-detail-meta">
        <div className="scene-detail-scores">
          <span>감정: {scene.emotion}</span>
          {scene.rank != null && <span>순위: #{scene.rank}</span>}
          <span>이미지: {(scene._image_url || scene._upload_preview) ? "있음" : scene.has_image ? "CapCut만" : "없음"}</span>
        </div>
      </div>

      {/* Display text */}
      {scene.display_text && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: 4 }}>자막 (FFmpeg용)</div>
          <div style={{ fontSize: "0.85rem", lineHeight: 1.6, whiteSpace: "pre-line", color: "var(--text-secondary)" }}>
            {scene.display_text}
          </div>
        </div>
      )}
    </div>
  );
}
