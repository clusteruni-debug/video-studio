import { BarChart3, RefreshCw } from "lucide-react";
import type {
  UsageStats,
  UsageLimitDaily,
  UsageLimitHourlyMonthly,
  UsageLimitMonthly,
  UsageLimitNone,
} from "../lib/bridge";

interface UsageCardProps {
  stats: UsageStats | null;
  onRefresh?: () => void;
}

function pct(used: number, limit: number): number {
  if (limit <= 0) return 0;
  return Math.min(100, (used / limit) * 100);
}

function barColor(ratio: number): string {
  if (ratio >= 80) return "var(--error)";
  if (ratio >= 50) return "var(--warning)";
  return "var(--success)";
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

function fmtCost(n: number): string {
  return `$${n.toFixed(2)}`;
}

function ProgressBar({ used, limit }: { used: number; limit: number }) {
  const ratio = pct(used, limit);
  const color = barColor(ratio);
  return (
    <div
      style={{
        height: 4,
        background: "var(--bg-active)",
        borderRadius: 2,
        overflow: "hidden",
        marginTop: 3,
      }}
    >
      <div
        style={{
          height: "100%",
          width: `${ratio}%`,
          background: color,
          borderRadius: 2,
          transition: "width 0.3s ease",
        }}
      />
    </div>
  );
}

function ProviderRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: "0.72rem", color: "var(--text-tertiary)", marginBottom: 2 }}>
        {label}
      </div>
      {children}
    </div>
  );
}

export default function UsageCard({ stats, onRefresh }: UsageCardProps) {
  if (!stats || !stats.ok) return null;

  const { limits, session, monthly_total_cost_usd } = stats;

  // Total session calls
  const totalSessionCalls = Object.values(session).reduce((acc, s) => acc + s.calls, 0);

  // Check if any data to show
  const hasData =
    Object.keys(limits).length > 0 || totalSessionCalls > 0;
  if (!hasData) return null;

  // Providers to display (exclude unlimited free tier ones: edge-tts, wan, local-bgm)
  const FREE_UNLIMITED = new Set(["edge-tts", "wan", "edge", "local-bgm"]);
  const limitEntries = Object.entries(limits).filter(([key]) => !FREE_UNLIMITED.has(key));

  const dailyEntries = limitEntries.filter(([, v]) => v.cycle === "daily") as [string, UsageLimitDaily][];
  const hourlyMonthlyEntries = limitEntries.filter(([, v]) => v.cycle === "hourly+monthly") as [string, UsageLimitHourlyMonthly][];
  const monthlyEntries = limitEntries.filter(([, v]) => v.cycle === "monthly") as [string, UsageLimitMonthly][];
  const paidEntries = limitEntries.filter(([, v]) => v.cycle === "none") as [string, UsageLimitNone][];

  // Also show paid providers with session usage even if not in limits
  const sessionPaidProviders = Object.entries(session).filter(
    ([key, v]) => v.cost_usd > 0 && !limits[key] && !FREE_UNLIMITED.has(key)
  );

  const hasAnyRows =
    dailyEntries.length > 0 ||
    hourlyMonthlyEntries.length > 0 ||
    monthlyEntries.length > 0 ||
    paidEntries.length > 0 ||
    sessionPaidProviders.length > 0;

  if (!hasAnyRows && totalSessionCalls === 0) return null;

  const PROVIDER_LABELS: Record<string, string> = {
    "gemini": "Gemini",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "gemini-2.0-flash": "Gemini 2.0 Flash",
    "pexels": "Pexels",
    "google-tts": "Google TTS",
    "imagen": "Imagen",
    "veo3": "Veo 3",
    "dalle3": "DALL-E 3",
    "sora2": "Sora 2",
  };

  function providerLabel(key: string): string {
    return PROVIDER_LABELS[key] ?? key;
  }

  return (
    <div
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-sm)",
        padding: "10px 12px",
        fontSize: "0.78rem",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 5,
            color: "var(--text-secondary)",
            fontWeight: 600,
            fontSize: "0.72rem",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          }}
        >
          <BarChart3 size={12} />
          API 사용량
        </div>
        {onRefresh && (
          <button
            onClick={onRefresh}
            style={{
              background: "none",
              border: "none",
              padding: "2px 4px",
              color: "var(--text-tertiary)",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
            }}
            title="새로고침"
          >
            <RefreshCw size={11} />
          </button>
        )}
      </div>

      {/* Daily limit providers (Gemini) */}
      {dailyEntries.map(([key, entry]) => {
        const ratio = pct(entry.used, entry.limit);
        const color = barColor(ratio);
        const resetTime = entry.reset_at
          ? new Date(entry.reset_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })
          : null;
        return (
          <ProviderRow key={key} label={providerLabel(key)}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ color }}>
                {fmtNum(entry.used)} / {fmtNum(entry.limit)} <span style={{ color: "var(--text-tertiary)" }}>(오늘)</span>
              </span>
              {resetTime && (
                <span style={{ color: "var(--text-tertiary)", fontSize: "0.68rem" }}>
                  리셋 {resetTime}
                </span>
              )}
            </div>
            <ProgressBar used={entry.used} limit={entry.limit} />
          </ProviderRow>
        );
      })}

      {/* Hourly + Monthly (Pexels) */}
      {hourlyMonthlyEntries.map(([key, entry]) => {
        const ratioHour = pct(entry.used_hour, entry.limit_hour);
        const ratioMonth = pct(entry.used_month, entry.limit_month);
        return (
          <ProviderRow key={key} label={providerLabel(key)}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: barColor(ratioHour) }}>
                {fmtNum(entry.used_hour)} / {fmtNum(entry.limit_hour)}{" "}
                <span style={{ color: "var(--text-tertiary)" }}>(이 시간)</span>
              </span>
            </div>
            <ProgressBar used={entry.used_hour} limit={entry.limit_hour} />
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
              <span style={{ color: barColor(ratioMonth) }}>
                {fmtNum(entry.used_month)} / {fmtNum(entry.limit_month)}{" "}
                <span style={{ color: "var(--text-tertiary)" }}>(이번 달)</span>
              </span>
            </div>
            <ProgressBar used={entry.used_month} limit={entry.limit_month} />
          </ProviderRow>
        );
      })}

      {/* Monthly (Google TTS) */}
      {monthlyEntries.map(([key, entry]) => {
        const ratio = pct(entry.used_chars, entry.limit_chars);
        const color = barColor(ratio);
        return (
          <ProviderRow key={key} label={providerLabel(key)}>
            <div style={{ color }}>
              {fmtNum(entry.used_chars)} / {fmtNum(entry.limit_chars)} chars{" "}
              <span style={{ color: "var(--text-tertiary)" }}>(이번 달)</span>
            </div>
            <ProgressBar used={entry.used_chars} limit={entry.limit_chars} />
          </ProviderRow>
        );
      })}

      {/* No free tier paid providers (Imagen, Veo3, etc.) */}
      {paidEntries.map(([key, entry]) => (
        <ProviderRow key={key} label={providerLabel(key)}>
          <span style={{ color: entry.total_cost_usd > 0 ? "var(--warning)" : "var(--text-secondary)" }}>
            {entry.total_calls}회 · {fmtCost(entry.total_cost_usd)}
          </span>
        </ProviderRow>
      ))}

      {/* Session-only paid providers */}
      {sessionPaidProviders.map(([key, entry]) => (
        <ProviderRow key={key} label={providerLabel(key)}>
          <span style={{ color: "var(--warning)" }}>
            {entry.calls}회 · {fmtCost(entry.cost_usd)}
          </span>
        </ProviderRow>
      ))}

      {/* Footer */}
      <div
        style={{
          borderTop: "1px solid var(--border-subtle)",
          marginTop: 6,
          paddingTop: 6,
          display: "flex",
          justifyContent: "space-between",
          color: "var(--text-tertiary)",
          fontSize: "0.72rem",
        }}
      >
        <span>
          이번 달 총 비용:{" "}
          <span style={{ color: monthly_total_cost_usd > 0 ? "var(--warning)" : "var(--text-secondary)" }}>
            {fmtCost(monthly_total_cost_usd)}
          </span>
        </span>
        <span>세션 호출: {totalSessionCalls}회</span>
      </div>
    </div>
  );
}
