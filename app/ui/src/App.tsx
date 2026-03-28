import { useEffect, useState } from "react";
import { checkHealth, createDraft, type BridgeHealth, type DraftResult, type TemplateType } from "./lib/bridge";

const TEMPLATE_LABELS: Record<TemplateType, string> = {
  community_read: "커뮤니티 글 읽기",
  news_explainer: "뉴스/팩트 해설",
  reddit_translation: "해외 글 번역",
  ranking_list: "Top N 랭킹",
  origin_story: "기원/역사 스토리",
  vs_comparison: "A vs B 비교",
  myth_buster: "팩트체크/오해와진실",
  tutorial_steps: "단계별 튜토리얼",
  before_after: "비포/애프터",
  hot_take: "핫테이크/논쟁",
};

const TTS_LABELS: Record<string, string> = {
  edge: "Edge TTS (무료)",
  elevenlabs: "ElevenLabs",
  google: "Google Cloud TTS",
  "openai-tts": "OpenAI TTS",
};

const SUBTITLE_STYLE_LABELS: Record<string, string> = {
  "": "기본 (SRT)",
  default: "표준 스타일",
  news: "뉴스/해설",
  story: "스토리텔링",
  ranking: "랭킹/퀴즈",
  minimal: "미니멀",
  impact: "임팩트 (노랑 강조)",
};

/* CSS custom properties injected once at :root */
const STYLE_TAG_ID = "vs-theme";
if (!document.getElementById(STYLE_TAG_ID)) {
  const style = document.createElement("style");
  style.id = STYLE_TAG_ID;
  style.textContent = `
    :root {
      --vs-bg: #0f0f23;
      --vs-surface: #1a1a2e;
      --vs-surface2: #16213e;
      --vs-surface3: #1e293b;
      --vs-border: #333;
      --vs-text: #fff;
      --vs-text-muted: #888;
      --vs-text-secondary: #94a3b8;
      --vs-text-body: #cbd5e1;
      --vs-text-subtle: #64748b;
      --vs-text-display: #e2e8f0;
      --vs-accent: #6366f1;
      --vs-accent-disabled: #555;
      --vs-success: #22c55e;
      --vs-success-bg: #064e3b;
      --vs-success-text: #6ee7b7;
      --vs-success-text2: #a7f3d0;
      --vs-warning: #eab308;
      --vs-error: #ef4444;
      --vs-error-bg: #7f1d1d;
      --vs-error-text: #fca5a5;
    }
  `;
  document.head.appendChild(style);
}

export default function App() {
  const [prompt, setPrompt] = useState("");
  const [lang, setLang] = useState<"ko" | "en">("ko");
  const [templateType, setTemplateType] = useState<TemplateType>("news_explainer");
  const [ttsProvider, setTtsProvider] = useState("edge");
  const [voiceGender, setVoiceGender] = useState<"female" | "male">("female");
  const [subtitleStyle, setSubtitleStyle] = useState("");
  const [bridgeStatus, setBridgeStatus] = useState<"checking" | "connected" | "offline">("checking");
  const [availableProviders, setAvailableProviders] = useState<string[]>(["edge"]);
  const [availableTemplates, setAvailableTemplates] = useState<TemplateType[]>(Object.keys(TEMPLATE_LABELS) as TemplateType[]);
  const [draftResult, setDraftResult] = useState<DraftResult | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    checkHealth().then((h) => {
      if (h) {
        setBridgeStatus("connected");
        setAvailableProviders(h.tts_providers);
        if (h.template_types?.length) setAvailableTemplates(h.template_types as TemplateType[]);
      } else {
        setBridgeStatus("offline");
      }
    });
  }, []);

  const handleCreate = async () => {
    if (!prompt.trim() || creating) return;
    setCreating(true);
    setError(null);
    setDraftResult(null);
    try {
      const result = await createDraft(prompt, lang, ttsProvider, voiceGender, templateType, subtitleStyle);
      if (result.ok) {
        setDraftResult(result);
      } else {
        setError(result.error || "Failed to create draft");
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Bridge connection failed");
    } finally {
      setCreating(false);
    }
  };

  const statusColor = bridgeStatus === "connected"
    ? "var(--vs-success)" : bridgeStatus === "checking"
    ? "var(--vs-warning)" : "var(--vs-error)";

  const selectStyle: React.CSSProperties = {
    padding: "0.5rem", borderRadius: 6,
    background: "var(--vs-surface2)", color: "var(--vs-text)", border: "1px solid var(--vs-border)",
  };

  return (
    <div style={{ maxWidth: 640, margin: "0 auto", padding: "2rem 1rem", fontFamily: "system-ui, sans-serif" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: "1.5rem" }}>
        <h1 style={{ margin: 0, fontSize: "1.5rem" }}>Video Studio</h1>
        <span style={{
          width: 10, height: 10, borderRadius: "50%",
          background: statusColor, display: "inline-block",
        }} />
        <span style={{ fontSize: "0.8rem", color: "var(--vs-text-muted)" }}>
          {bridgeStatus === "connected" ? "Bridge Connected" : bridgeStatus === "checking" ? "Checking..." : "Bridge Offline"}
        </span>
      </div>

      {/* Prompt */}
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="영상 주제를 입력하세요 (예: 비트코인의 역사)"
        rows={3}
        style={{
          width: "100%", padding: "0.75rem", fontSize: "1rem",
          borderRadius: 8, border: "1px solid var(--vs-border)",
          background: "var(--vs-surface)", color: "var(--vs-text)",
          resize: "vertical", boxSizing: "border-box",
        }}
      />

      {/* Controls */}
      <div style={{ display: "flex", gap: 8, marginTop: "0.75rem", flexWrap: "wrap" }}>
        <select value={templateType} onChange={(e) => setTemplateType(e.target.value as TemplateType)}
          style={{ ...selectStyle, minWidth: 140 }}>
          {availableTemplates.map((t) => (
            <option key={t} value={t}>{TEMPLATE_LABELS[t] || t}</option>
          ))}
        </select>

        <select value={lang} onChange={(e) => setLang(e.target.value as "ko" | "en")}
          style={selectStyle}>
          <option value="ko">한국어</option>
          <option value="en">English</option>
        </select>

        <select value={ttsProvider} onChange={(e) => setTtsProvider(e.target.value)}
          style={selectStyle}>
          {availableProviders.map((p) => (
            <option key={p} value={p}>{TTS_LABELS[p] || p}</option>
          ))}
        </select>

        <select value={voiceGender} onChange={(e) => setVoiceGender(e.target.value as "female" | "male")}
          style={selectStyle}>
          <option value="female">여성</option>
          <option value="male">남성</option>
        </select>

        <select value={subtitleStyle} onChange={(e) => setSubtitleStyle(e.target.value)}
          style={{ ...selectStyle, minWidth: 120 }}>
          {Object.entries(SUBTITLE_STYLE_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
      </div>

      {/* Create button */}
      <button
        onClick={handleCreate}
        disabled={creating || bridgeStatus !== "connected" || !prompt.trim()}
        style={{
          marginTop: "1rem", width: "100%", padding: "0.75rem",
          fontSize: "1rem", fontWeight: 600, borderRadius: 8, border: "none",
          background: creating ? "var(--vs-accent-disabled)" : "var(--vs-accent)",
          color: "var(--vs-text)", cursor: creating ? "wait" : "pointer",
        }}
      >
        {creating ? "CapCut 초안 생성 중..." : "CapCut 초안 생성"}
      </button>

      {/* Error */}
      {error && (
        <div style={{ marginTop: "1rem", padding: "0.75rem", background: "var(--vs-error-bg)", borderRadius: 8, color: "var(--vs-error-text)" }}>
          {error}
        </div>
      )}

      {/* Result */}
      {draftResult && (
        <div style={{ marginTop: "1.5rem" }}>
          <div style={{
            padding: "1rem", background: "var(--vs-success-bg)", borderRadius: 8, color: "var(--vs-success-text)", marginBottom: "1rem",
          }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{draftResult.message}</div>
            {draftResult.total_duration && (
              <div style={{ fontSize: "0.85rem", color: "var(--vs-success-text2)" }}>
                {draftResult.total_duration}s / {draftResult.scenes?.length} scenes / TTS: {draftResult.tts_provider}
              </div>
            )}
            {draftResult.draft_path && (
              <div style={{ fontSize: "0.75rem", marginTop: 4, color: "var(--vs-success-text)", opacity: 0.7, wordBreak: "break-all" }}>
                {draftResult.draft_path}
              </div>
            )}
            {draftResult.steps && (
              <div style={{ fontSize: "0.75rem", marginTop: 4, color: "var(--vs-success-text2)", opacity: 0.6 }}>
                {draftResult.steps.join(" → ")}
              </div>
            )}
          </div>

          <h3 style={{ fontSize: "1rem", marginBottom: "0.5rem" }}>생성된 씬</h3>
          {draftResult.scenes?.map((scene) => (
            <div key={scene.scene_num} style={{
              padding: "0.75rem", marginBottom: 8, background: "var(--vs-surface3)", borderRadius: 8,
              borderLeft: `3px solid ${scene.has_image ? "var(--vs-success)" : "var(--vs-accent)"}`,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <span style={{ fontWeight: 600 }}>
                  {scene.rank != null ? `#${scene.rank} ` : ""}씬 {scene.scene_num}
                </span>
                <span style={{ fontSize: "0.75rem", color: "var(--vs-text-secondary)" }}>
                  {scene.duration}s {scene.emotion !== "neutral" ? scene.emotion : ""} {scene.has_image ? "📷" : ""}
                </span>
              </div>
              {scene.display_text && (
                <div style={{ fontSize: "0.85rem", color: "var(--vs-text-display)", marginBottom: 4, whiteSpace: "pre-line" }}>{scene.display_text}</div>
              )}
              <div style={{ fontSize: "0.9rem", color: "var(--vs-text-body)" }}>{scene.narration}</div>
              {scene.image_prompt && (
                <div style={{ fontSize: "0.75rem", color: "var(--vs-text-subtle)", marginTop: 4 }}>{scene.image_prompt}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
