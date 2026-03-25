import { useEffect, useState } from "react";
import { checkHealth, createDraft, type BridgeHealth, type DraftResult } from "./lib/bridge";

export default function App() {
  const [prompt, setPrompt] = useState("");
  const [lang, setLang] = useState<"ko" | "en">("ko");
  const [ttsProvider, setTtsProvider] = useState("edge");
  const [voiceGender, setVoiceGender] = useState<"female" | "male">("female");
  const [bridgeStatus, setBridgeStatus] = useState<"checking" | "connected" | "offline">("checking");
  const [availableProviders, setAvailableProviders] = useState<string[]>(["edge"]);
  const [draftResult, setDraftResult] = useState<DraftResult | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    checkHealth().then((h) => {
      if (h) {
        setBridgeStatus("connected");
        setAvailableProviders(h.tts_providers);
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
      const result = await createDraft(prompt, lang, ttsProvider, voiceGender);
      if (result.ok) {
        setDraftResult(result);
      } else {
        setError(result.error || "Failed to create draft");
      }
    } catch (e: any) {
      setError(e.message || "Bridge connection failed");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div style={{ maxWidth: 640, margin: "0 auto", padding: "2rem 1rem", fontFamily: "system-ui, sans-serif" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: "1.5rem" }}>
        <h1 style={{ margin: 0, fontSize: "1.5rem" }}>Video Studio</h1>
        <span style={{
          width: 10, height: 10, borderRadius: "50%",
          background: bridgeStatus === "connected" ? "#22c55e" : bridgeStatus === "checking" ? "#eab308" : "#ef4444",
          display: "inline-block",
        }} />
        <span style={{ fontSize: "0.8rem", color: "#888" }}>
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
          borderRadius: 8, border: "1px solid #333", background: "#1a1a2e", color: "#fff",
          resize: "vertical", boxSizing: "border-box",
        }}
      />

      {/* Controls */}
      <div style={{ display: "flex", gap: 8, marginTop: "0.75rem", flexWrap: "wrap" }}>
        <select value={lang} onChange={(e) => setLang(e.target.value as any)}
          style={{ padding: "0.5rem", borderRadius: 6, background: "#16213e", color: "#fff", border: "1px solid #333" }}>
          <option value="ko">한국어</option>
          <option value="en">English</option>
        </select>

        <select value={ttsProvider} onChange={(e) => setTtsProvider(e.target.value)}
          style={{ padding: "0.5rem", borderRadius: 6, background: "#16213e", color: "#fff", border: "1px solid #333" }}>
          {availableProviders.map((p) => (
            <option key={p} value={p}>
              {p === "edge" ? "Edge TTS (무료)" : p === "elevenlabs" ? "ElevenLabs" : "Google Cloud TTS"}
            </option>
          ))}
        </select>

        <select value={voiceGender} onChange={(e) => setVoiceGender(e.target.value as any)}
          style={{ padding: "0.5rem", borderRadius: 6, background: "#16213e", color: "#fff", border: "1px solid #333" }}>
          <option value="female">여성</option>
          <option value="male">남성</option>
        </select>
      </div>

      {/* Create button */}
      <button
        onClick={handleCreate}
        disabled={creating || bridgeStatus !== "connected" || !prompt.trim()}
        style={{
          marginTop: "1rem", width: "100%", padding: "0.75rem",
          fontSize: "1rem", fontWeight: 600, borderRadius: 8, border: "none",
          background: creating ? "#555" : "#6366f1", color: "#fff", cursor: creating ? "wait" : "pointer",
        }}
      >
        {creating ? "CapCut 초안 생성 중..." : "CapCut 초안 생성"}
      </button>

      {/* Error */}
      {error && (
        <div style={{ marginTop: "1rem", padding: "0.75rem", background: "#7f1d1d", borderRadius: 8, color: "#fca5a5" }}>
          {error}
        </div>
      )}

      {/* Result */}
      {draftResult && (
        <div style={{ marginTop: "1.5rem" }}>
          <div style={{
            padding: "1rem", background: "#064e3b", borderRadius: 8, color: "#6ee7b7", marginBottom: "1rem",
          }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{draftResult.message}</div>
            {draftResult.total_duration && (
              <div style={{ fontSize: "0.85rem", color: "#a7f3d0" }}>
                {draftResult.total_duration}s / {draftResult.scenes?.length} scenes / TTS: {draftResult.tts_provider}
              </div>
            )}
            {draftResult.draft_path && (
              <div style={{ fontSize: "0.75rem", marginTop: 4, color: "#6ee7b7", opacity: 0.7, wordBreak: "break-all" }}>
                {draftResult.draft_path}
              </div>
            )}
            {draftResult.steps && (
              <div style={{ fontSize: "0.75rem", marginTop: 4, color: "#a7f3d0", opacity: 0.6 }}>
                {draftResult.steps.join(" → ")}
              </div>
            )}
          </div>

          <h3 style={{ fontSize: "1rem", marginBottom: "0.5rem" }}>생성된 씬</h3>
          {draftResult.scenes?.map((scene) => (
            <div key={scene.scene_num} style={{
              padding: "0.75rem", marginBottom: 8, background: "#1e293b", borderRadius: 8,
              borderLeft: `3px solid ${scene.has_image ? "#22c55e" : "#6366f1"}`,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <span style={{ fontWeight: 600 }}>씬 {scene.scene_num}</span>
                <span style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
                  {scene.duration}s {scene.has_image ? "📷" : ""}
                </span>
              </div>
              <div style={{ fontSize: "0.9rem", color: "#cbd5e1" }}>{scene.narration}</div>
              {scene.image_prompt && (
                <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: 4 }}>{scene.image_prompt}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
