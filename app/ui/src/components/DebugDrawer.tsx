import { useState } from "react";
import { X, RefreshCw, Trash2, HardDrive } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";
import { operatorSteps } from "../lib/sample-data";
import { getStorageStatus, cleanupStorage, type StorageStatusResult, type CleanupResult } from "../lib/bridge";

export default function DebugDrawer() {
  const { debugOpen, bridgeStatus, bridgeHealth } = useStudioState();
  const actions = useStudioActions();
  const [storageInfo, setStorageInfo] = useState<StorageStatusResult | null>(null);
  const [cleaning, setCleaning] = useState(false);
  const [cleanResult, setCleanResult] = useState<CleanupResult | null>(null);

  // Use CSS hidden instead of unmount to preserve state across open/close
  return (
    <div className="debug-overlay" onClick={actions.toggleDebug} style={debugOpen ? undefined : { display: "none" }}>
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

          {/* Server storage management */}
          <div className="debug-section">
            <div className="debug-section-title" style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <HardDrive size={13} /> 서버 스토리지
            </div>

            {storageInfo?.ok && (
              <div style={{ display: "grid", gap: 4, marginBottom: 8 }}>
                {(["tts", "cache", "renders", "thumbnails", "capcut_drafts"] as const).map((key) => {
                  const info = storageInfo[key];
                  if (!info) return null;
                  const labels: Record<string, string> = { tts: "TTS 음성", cache: "이미지 캐시", renders: "렌더 결과물", thumbnails: "썸네일", capcut_drafts: "CapCut 드래프트" };
                  return (
                    <div key={key} className="debug-bridge-row">
                      <span>{labels[key]}</span>
                      <span style={{ fontSize: "0.75rem" }}>{info.items}개 / {info.size_display}</span>
                    </div>
                  );
                })}
              </div>
            )}
            {storageInfo && !storageInfo.ok && (
              <div style={{ marginBottom: 8, fontSize: "0.75rem", color: "var(--error)" }}>연결 실패: {storageInfo.error}</div>
            )}

            <div style={{ display: "flex", gap: 6 }}>
              <button
                className="subtle-button"
                onClick={async () => {
                  const res = await getStorageStatus();
                  setStorageInfo(res);
                  setCleanResult(null);
                }}
              >
                <RefreshCw size={12} /> 용량 확인
              </button>
              <button
                className="subtle-button"
                style={{ color: "var(--warning)" }}
                disabled={cleaning}
                onClick={async () => {
                  if (!window.confirm("7일 이상 된 생성 파일을 삭제합니다. 계속하시겠습니까?")) return;
                  setCleaning(true);
                  try {
                    const res = await cleanupStorage(7);
                    setCleanResult(res);
                    const status = await getStorageStatus();
                    setStorageInfo(status);
                  } finally {
                    setCleaning(false);
                  }
                }}
              >
                <Trash2 size={12} /> {cleaning ? "정리 중..." : "7일+ 정리"}
              </button>
            </div>

            {cleanResult?.ok && (
              <div style={{ marginTop: 8, fontSize: "0.72rem", color: "var(--text-secondary)", lineHeight: 1.5 }}>
                {(["tts", "cache", "renders", "thumbnails", "capcut_drafts"] as const).map((key) => {
                  const r = cleanResult[key];
                  if (!r || r.removed === 0) return null;
                  const labels: Record<string, string> = { tts: "TTS", cache: "캐시", renders: "렌더", thumbnails: "썸네일", capcut_drafts: "CapCut" };
                  return <div key={key}>{labels[key]}: {r.removed}건 삭제 ({r.freed_display})</div>;
                })}
                {(["tts", "cache", "renders", "thumbnails", "capcut_drafts"] as const).every((k) => !cleanResult[k] || cleanResult[k]!.removed === 0) && (
                  <div>정리할 항목 없음</div>
                )}
              </div>
            )}
            {cleanResult && !cleanResult.ok && (
              <div style={{ marginTop: 8, fontSize: "0.72rem", color: "var(--error)" }}>정리 실패: {cleanResult.error}</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
