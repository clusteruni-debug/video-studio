import { AlertTriangle, X } from "lucide-react";

export interface PaidConfirmDialogProps {
  open: boolean;
  provider: string;
  action: string;
  estimatedCost: string;
  freeAlternative: string;
  onUseFree: () => void;
  onProceed: () => void;
  onClose: () => void;
}

export default function PaidConfirmDialog({
  open,
  provider,
  action,
  estimatedCost,
  freeAlternative,
  onUseFree,
  onProceed,
  onClose,
}: PaidConfirmDialogProps) {
  if (!open) return null;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0, 0, 0, 0.6)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "var(--bg-elevated)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-md)",
          padding: "20px 24px",
          width: 340,
          maxWidth: "90vw",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            marginBottom: 14,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <AlertTriangle size={16} style={{ color: "var(--warning)", flexShrink: 0 }} />
            <span style={{ fontWeight: 600, fontSize: "0.88rem" }}>유료 API 호출</span>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              padding: "2px 4px",
              color: "var(--text-tertiary)",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
            }}
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div style={{ fontSize: "0.82rem", color: "var(--text-secondary)", display: "flex", flexDirection: "column", gap: 8 }}>
          <div
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "var(--radius-sm)",
              padding: "10px 12px",
              display: "flex",
              flexDirection: "column",
              gap: 4,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--text-tertiary)" }}>제공자</span>
              <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{provider}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--text-tertiary)" }}>작업</span>
              <span style={{ color: "var(--text-primary)" }}>{action}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--text-tertiary)" }}>예상 비용</span>
              <span style={{ color: "var(--warning)", fontWeight: 600 }}>{estimatedCost}</span>
            </div>
          </div>

          {freeAlternative && (
            <div
              style={{
                background: "var(--success-dim)",
                border: "1px solid rgba(52, 199, 123, 0.2)",
                borderRadius: "var(--radius-sm)",
                padding: "8px 12px",
                fontSize: "0.78rem",
                color: "var(--success)",
              }}
            >
              무료 대안: {freeAlternative}
            </div>
          )}
        </div>

        {/* Buttons */}
        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          {freeAlternative && (
            <button
              onClick={onUseFree}
              style={{
                flex: 1,
                padding: "8px 12px",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                background: "var(--bg-surface)",
                color: "var(--text-primary)",
                fontWeight: 500,
                fontSize: "0.82rem",
                cursor: "pointer",
              }}
            >
              무료 대안 사용
            </button>
          )}
          <button
            onClick={onProceed}
            style={{
              flex: 1,
              padding: "8px 12px",
              border: "none",
              borderRadius: "var(--radius-sm)",
              background: "var(--warning)",
              color: "#fff",
              fontWeight: 600,
              fontSize: "0.82rem",
              cursor: "pointer",
            }}
          >
            유료 진행
          </button>
        </div>
      </div>
    </div>
  );
}
