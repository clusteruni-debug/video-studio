import { useState, useEffect } from "react";
import { Layers, Loader, CheckCircle, XCircle } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";

export default function BatchPanel() {
  const { prompt, activeBatchId, batchStatus, batches, bridgeStatus } = useStudioState();
  const actions = useStudioActions();
  const [variants, setVariants] = useState(3);
  const [starting, setStarting] = useState(false);

  // Load batches on mount
  useEffect(() => {
    actions.refreshBatches();
  }, [actions]);

  const handleStart = async () => {
    setStarting(true);
    await actions.startBatch(variants);
    setStarting(false);
  };

  const isRunning = activeBatchId !== null;
  // Backend may use completed/failed or progress/total — handle both
  const batchDone = batchStatus ? ((batchStatus.completed ?? batchStatus.progress ?? 0) + (batchStatus.failed ?? 0)) : 0;
  const batchTotal = batchStatus ? (batchStatus.variants ?? batchStatus.total ?? 1) : 1;
  const progress = batchDone / Math.max(batchTotal, 1);

  return (
    <div>
      {/* Create batch form */}
      <div className="canvas-header" style={{ marginBottom: 16 }}>
        <span className="canvas-header-title">배치 생성</span>
        <span className="canvas-header-meta">
          동일 프롬프트로 여러 변형을 한번에 생성
        </span>
      </div>

      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", marginBottom: 16, flexWrap: "wrap" }}>
        <div className="sidebar-field compact" style={{ width: 140 }}>
          <span>변형 수 (1-10)</span>
          <input
            type="number"
            min={1}
            max={10}
            value={variants}
            onChange={(e) => setVariants(Math.min(10, Math.max(1, Number(e.target.value))))}
          />
        </div>
        <button
          className="generate-button"
          style={{ maxWidth: 200, padding: "8px 16px" }}
          disabled={!prompt.trim() || bridgeStatus !== "connected" || isRunning || starting}
          onClick={handleStart}
        >
          {starting ? (
            <><Loader size={14} style={{ animation: "spin 1s linear infinite" }} /> 시작 중...</>
          ) : (
            <><Layers size={14} /> 배치 생성</>
          )}
        </button>
      </div>

      {!prompt.trim() && (
        <p style={{ fontSize: "0.82rem", color: "var(--text-tertiary)" }}>
          왼쪽 사이드바에서 프롬프트를 먼저 입력하세요
        </p>
      )}

      {/* Active batch progress */}
      {isRunning && batchStatus && (
        <div className="batch-progress" style={{ marginBottom: 16 }}>
          <span className="batch-progress-stats">
            {batchDone} / {batchTotal} 완료
            {(batchStatus.failed ?? 0) > 0 && (
              <span style={{ color: "var(--error)", marginLeft: 8 }}>실패 {batchStatus.failed}</span>
            )}
          </span>
          <div className="batch-progress-bar">
            <div className="batch-progress-fill" style={{ width: `${progress * 100}%` }} />
          </div>
        </div>
      )}

      {/* Batch results */}
      {batchStatus?.results && batchStatus.results.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div className="summary-label" style={{ marginBottom: 8 }}>결과</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {batchStatus.results.map((r, i) => (
              <div key={i} className="scene-detail-asset-row" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {r.ok ? (
                  <CheckCircle size={14} style={{ color: "var(--success)", flexShrink: 0 }} />
                ) : (
                  <XCircle size={14} style={{ color: "var(--error)", flexShrink: 0 }} />
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "0.82rem" }}>
                    변형 #{i + 1} — {r.ok ? `${r.scenes?.length}씬` : r.error}
                  </div>
                  {r.ok && r.total_duration && (
                    <div style={{ fontSize: "0.72rem", color: "var(--text-tertiary)" }}>
                      {r.total_duration.toFixed(1)}s / {r.tts_provider}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Previous batches */}
      {batches.length > 0 && (
        <div>
          <div className="summary-label" style={{ marginBottom: 8 }}>이전 배치</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {batches.map((b) => (
              <div key={b.batch_id} className="scene-detail-asset-row" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Layers size={14} style={{ color: "var(--accent)", flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "0.82rem", fontWeight: 500 }}>{b.topic || b.batch_id}</div>
                  <div style={{ fontSize: "0.72rem", color: "var(--text-tertiary)" }}>
                    {b.completed}/{b.variants} 완료 {b.failed > 0 ? `· ${b.failed} 실패` : ""}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!isRunning && batches.length === 0 && (
        <div className="canvas-empty" style={{ minHeight: 200 }}>
          <div className="canvas-empty-icon"><Layers size={28} /></div>
          <h2>배치 생성</h2>
          <p>프롬프트를 입력하고 여러 변형을 한번에 생성하세요</p>
        </div>
      )}
    </div>
  );
}
