import { useEffect, useRef } from "react";
import { Briefcase, Loader, CheckCircle, XCircle, Clock, Play } from "lucide-react";
import { useStudioState, useStudioActions } from "../context/StudioContext";

const STATUS_CONFIG: Record<string, { icon: typeof CheckCircle; color: string; dimBg: string; label: string }> = {
  queued: { icon: Clock, color: "var(--warning)", dimBg: "var(--warning-dim)", label: "대기" },
  pending: { icon: Clock, color: "var(--warning)", dimBg: "var(--warning-dim)", label: "대기" },
  running: { icon: Loader, color: "var(--accent)", dimBg: "var(--accent-dim)", label: "실행 중" },
  completed: { icon: CheckCircle, color: "var(--success)", dimBg: "var(--success-dim)", label: "완료" },
  failed: { icon: XCircle, color: "var(--error)", dimBg: "var(--error-dim)", label: "실패" },
};

export default function JobsPanel() {
  const { jobs, prompt, bridgeStatus } = useStudioState();
  const actions = useStudioActions();
  const mountedRef = useRef(false);

  // Fetch once on mount
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true;
      actions.refreshJobs();
    }
  }, [actions]);

  // Poll when there are running/queued jobs
  const hasRunning = jobs.some((j) => j.status === "queued" || j.status === "pending" || j.status === "running");
  useEffect(() => {
    if (!hasRunning) return;
    const id = setInterval(() => actions.refreshJobs(), 5000);
    return () => clearInterval(id);
  }, [hasRunning, actions]);

  return (
    <div>
      {/* Header */}
      <div className="canvas-header" style={{ marginBottom: 16 }}>
        <span className="canvas-header-title">작업 큐</span>
        <span className="canvas-header-meta">{jobs.length}개 작업</span>
      </div>

      {/* Submit button */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <button
          className="generate-button"
          style={{ maxWidth: 200, padding: "8px 16px" }}
          disabled={!prompt.trim() || bridgeStatus !== "connected"}
          onClick={actions.submitJob}
        >
          <Play size={14} /> 새 작업 제출
        </button>
        <button className="subtle-button" onClick={actions.refreshJobs}>
          새로고침
        </button>
      </div>

      {/* Jobs list */}
      {jobs.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {jobs.map((job) => {
            const cfg = STATUS_CONFIG[job.status] ?? STATUS_CONFIG.pending;
            const Icon = cfg.icon;
            return (
              <div key={job.job_id} className="scene-detail-asset-row" style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <Icon
                  size={16}
                  style={{
                    color: cfg.color, flexShrink: 0,
                    ...(job.status === "running" ? { animation: "spin 1s linear infinite" } : {}),
                  }}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "0.85rem", fontWeight: 500 }}>
                    {job.prompt.slice(0, 60)}{job.prompt.length > 60 ? "..." : ""}
                  </div>
                  <div style={{ fontSize: "0.72rem", color: "var(--text-tertiary)", display: "flex", gap: 8 }}>
                    <span className="route-badge" style={{
                      background: cfg.dimBg,
                      color: cfg.color,
                      fontSize: "0.65rem",
                    }}>
                      {cfg.label}
                    </span>
                    <span>{job.job_id.slice(0, 8)}</span>
                  </div>
                  {job.error && (
                    <div style={{ fontSize: "0.75rem", color: "var(--error)", marginTop: 4 }}>{job.error}</div>
                  )}
                  {job.result?.ok && (
                    <div style={{ fontSize: "0.75rem", color: "var(--success)", marginTop: 4 }}>
                      {job.result.scenes?.length}씬 / {job.result.total_duration?.toFixed(1)}s
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="canvas-empty" style={{ minHeight: 200 }}>
          <div className="canvas-empty-icon"><Briefcase size={28} /></div>
          <h2>작업 큐</h2>
          <p>프롬프트를 입력하고 작업을 제출하세요</p>
        </div>
      )}
    </div>
  );
}
