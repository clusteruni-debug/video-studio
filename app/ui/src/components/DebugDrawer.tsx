import { X, RefreshCw } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";
import { operatorSteps } from "../lib/sample-data";

export default function DebugDrawer() {
  const { debugOpen, bridgeStatus, bridgeHealth } = useStudioState();
  const actions = useStudioActions();

  if (!debugOpen) return null;

  return (
    <div className="debug-overlay" onClick={actions.toggleDebug}>
      <div className="debug-drawer" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="debug-drawer-header">
          <h3>디버그 패널</h3>
          <button className="debug-drawer-close" onClick={actions.toggleDebug}>
            <X size={14} />
          </button>
        </div>

        <div className="debug-drawer-body">
          {/* Bridge status */}
          <div className="debug-section">
            <div className="debug-section-title">Bridge Status</div>
            <div className="debug-bridge-row">
              <span>상태</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span className={`bridge-dot bridge-dot-${bridgeStatus}`} />
                {bridgeStatus}
              </span>
            </div>
            {bridgeHealth && (
              <>
                <div className="debug-bridge-row">
                  <span>VectCut</span>
                  <span>{bridgeHealth.vectcut}</span>
                </div>
                <div className="debug-bridge-row">
                  <span>Groq</span>
                  <span>{bridgeHealth.groq}</span>
                </div>
                <div className="debug-bridge-row">
                  <span>Gemini</span>
                  <span>{bridgeHealth.gemini}</span>
                </div>
                <div className="debug-bridge-row">
                  <span>Pexels</span>
                  <span>{bridgeHealth.pexels}</span>
                </div>
                <div className="debug-bridge-row">
                  <span>Klipy</span>
                  <span>{bridgeHealth.klipy}</span>
                </div>
                <div className="debug-bridge-row">
                  <span>CapCut Draft</span>
                  <span style={{ fontSize: "0.72rem", wordBreak: "break-all" }}>
                    {bridgeHealth.capcut_draft_dir}
                    {bridgeHealth.capcut_draft_dir_exists ? " (exists)" : " (missing)"}
                  </span>
                </div>
              </>
            )}
            <button
              className="subtle-button"
              onClick={actions.recheckBridge}
              style={{ marginTop: 8 }}
            >
              <RefreshCw size={12} style={{ marginRight: 4 }} /> 재확인
            </button>
          </div>

          {/* TTS Providers */}
          {bridgeHealth?.tts_providers && (
            <div className="debug-section">
              <div className="debug-section-title">TTS Providers</div>
              <div className="tool-grid">
                {bridgeHealth.tts_providers.map((p) => (
                  <div key={p} className="tool-card">
                    <strong>{p}</strong>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tone Presets */}
          {bridgeHealth?.tone_presets && (
            <div className="debug-section">
              <div className="debug-section-title">Tone Presets</div>
              <div className="tool-grid">
                {Object.entries(bridgeHealth.tone_presets).map(([key, label]) => (
                  <div key={key} className="tool-card">
                    <strong>{key}</strong>
                    <small>{label}</small>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Operator Notes */}
          <div className="debug-section">
            <div className="debug-section-title">Operator Notes</div>
            <ul className="operator-list">
              {operatorSteps.map((step, i) => (
                <li key={i}>
                  <span style={{ color: "var(--text-tertiary)", flexShrink: 0 }}>{i + 1}.</span>
                  {step}
                </li>
              ))}
            </ul>
          </div>

          {/* Storage info */}
          <div className="debug-section">
            <div className="debug-section-title">Local Storage</div>
            <div className="storage-grid">
              <div>
                <strong>Keys</strong>
                <small style={{ color: "var(--text-tertiary)" }}>
                  {(() => {
                    try { return Object.keys(localStorage).filter((k) => k.startsWith("video-studio")).join(", ") || "(none)"; }
                    catch { return "(unavailable)"; }
                  })()}
                </small>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
