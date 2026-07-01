import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Database, FileCheck2, Loader, PlayCircle, RefreshCcw, ShieldCheck } from "lucide-react";

type MaterialSummary = {
  materialId: string;
  title: string;
  status: string;
  sourceCount: number;
  latestScore: number;
  updatedAt?: string;
  evaluation?: {
    score: number;
    verdict: string;
    blockedChecks?: string[];
  };
  lastGate?: {
    stage?: string;
    status?: string;
  } | null;
};

type MaterialLibraryStatus = {
  ok: boolean;
  stats?: {
    total: number;
    unused: number;
    withSourceLedger: number;
    withTopicPass: number;
  };
  summaries?: MaterialSummary[];
  dryrunPreflight?: DryrunPreflightStatus;
  error?: string;
};

type ProductionGateStatusPanelProps = {
  onOpenTopic: () => void;
  onOpenPlan: () => void;
};

type DryrunPreflightStatus = {
  available?: boolean;
  materialId?: string;
  materialTitle?: string;
  targetStage?: string;
  status?: string;
  dryrunAllowed?: boolean;
  generationAllowed?: boolean;
  renderAllowed?: boolean;
  finalAllowed?: boolean;
  failedChecks?: string[];
  artifactPaths?: {
    packet?: string;
    readinessReport?: string;
    summary?: string;
  };
  releaseBoundary?: string;
};

type DryrunPreflightResponse = {
  ok: boolean;
  summary?: DryrunPreflightStatus;
  error?: string;
};

type ProductionStatus = {
  truthSource?: string;
  nextAction?: {
    label?: string;
    status?: string;
    message?: string;
    detail?: string;
    tab?: string;
    source?: string;
  };
};

type ProductionStatusResponse = {
  ok: boolean;
  productionStatus?: ProductionStatus;
  error?: string;
};

const BRIDGE_URL = "http://127.0.0.1:5161";
const STALE_BRIDGE_MESSAGE = "현재 실행 중인 브리지가 오래된 코드입니다. 5161 bridge를 재시작해야 소재 DB API가 보입니다.";

function gateLabel(summary: MaterialSummary) {
  const gate = summary.lastGate;
  if (!gate?.stage) return "게이트 대기";
  if (gate.status === "pass") return `${gate.stage} 통과`;
  if (gate.status === "blocked") return `${gate.stage} 보완`;
  return `${gate.stage} ${gate.status || "대기"}`;
}

export default function ProductionGateStatusPanel({ onOpenTopic, onOpenPlan }: ProductionGateStatusPanelProps) {
  const [status, setStatus] = useState<MaterialLibraryStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [preflighting, setPreflighting] = useState(false);
  const [dryrunPreflight, setDryrunPreflight] = useState<DryrunPreflightStatus | null>(null);
  const [productionStatus, setProductionStatus] = useState<ProductionStatus | null>(null);
  const [productionStatusStale, setProductionStatusStale] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const latest = useMemo(() => status?.summaries?.[0] ?? null, [status]);
  const stats = status?.stats;
  const currentDryrun = dryrunPreflight ?? status?.dryrunPreflight ?? null;
  const hasReusableMaterial = Boolean((stats?.withSourceLedger ?? 0) > 0 || (stats?.withTopicPass ?? 0) > 0);
  const canonicalNext = productionStatus?.nextAction ?? null;

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${BRIDGE_URL}/api/topic-library/materials`);
      if (response.status === 404) throw new Error(STALE_BRIDGE_MESSAGE);
      const payload = await response.json() as MaterialLibraryStatus;
      if (!response.ok || !payload.ok) throw new Error(payload.error || "소재 DB 상태를 불러오지 못했습니다.");
      setStatus(payload);
      if (payload.dryrunPreflight?.available) setDryrunPreflight(payload.dryrunPreflight);
    } catch (err) {
      setProductionStatus(null);
      setProductionStatusStale("서버 production status를 새로 확인하지 못했습니다. 이전 서버 nextAction은 숨기고 소재 fallback만 표시합니다.");
      setError(err instanceof Error ? err.message : "소재 DB 상태를 불러오지 못했습니다.");
      setLoading(false);
      return;
    }

    try {
      const productionResponse = await fetch(`${BRIDGE_URL}/api/production/status`);
      if (productionResponse.status === 404) throw new Error(STALE_BRIDGE_MESSAGE);
      const productionPayload = await productionResponse.json() as ProductionStatusResponse;
      if (!productionResponse.ok || !productionPayload.ok || !productionPayload.productionStatus) {
        throw new Error(productionPayload.error || "서버 production status를 확인하지 못했습니다.");
      }
      setProductionStatus(productionPayload.productionStatus);
      setProductionStatusStale(null);
    } catch (err) {
      setProductionStatus(null);
      setProductionStatusStale(err instanceof Error ? `${err.message} 이전 서버 nextAction은 숨겼습니다.` : "서버 production status 실패: 이전 서버 nextAction은 숨겼습니다.");
    } finally {
      setLoading(false);
    }
  }

  async function runDryrunPreflight() {
    setPreflighting(true);
    setError(null);
    try {
      const response = await fetch(`${BRIDGE_URL}/api/topic-library/materials/dryrun-preflight`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ materialId: latest?.materialId, targetStage: "rough-cut" }),
      });
      if (response.status === 404) throw new Error(STALE_BRIDGE_MESSAGE);
      const payload = await response.json() as DryrunPreflightResponse;
      if (!response.ok || !payload.ok || !payload.summary) {
        throw new Error(payload.error || "Dry-run readiness report를 저장하지 못했습니다.");
      }
      setDryrunPreflight(payload.summary);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dry-run readiness report를 저장하지 못했습니다.");
    } finally {
      setPreflighting(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="gate-advanced-panel">
      <div className="gate-candidate-stack-head">
        <div>
          <strong>소재 DB / 제작 게이트 상태</strong>
          <span>외부 조사로 쌓은 소재를 중복, 출처, 게이트 기준으로 이어 봅니다.</span>
        </div>
        <button className="subtle-button" onClick={refresh} disabled={loading}>
          {loading ? <Loader size={13} className="spin" /> : <RefreshCcw size={13} />}
          새로고침
        </button>
      </div>

      {error ? (
        <div className="gate-help-note warn">
          <AlertTriangle size={14} />
          <span>{error}</span>
        </div>
      ) : null}

      {productionStatusStale ? (
        <div className="gate-help-note warn">
          <AlertTriangle size={14} />
          <span>{productionStatusStale}</span>
        </div>
      ) : null}

      <div className="workspace-stat-strip">
        <span><Database size={14} /> 누적 {stats?.total ?? 0}</span>
        <span><ShieldCheck size={14} /> 출처 보유 {stats?.withSourceLedger ?? 0}</span>
        <span><ShieldCheck size={14} /> 게이트 통과 {stats?.withTopicPass ?? 0}</span>
      </div>

      <div className="next-action-panel">
        <span>{canonicalNext ? "서버 production status 다음 행동" : "소재 레이어 다음 행동"}</span>
        <strong>{canonicalNext?.label || (hasReusableMaterial ? "저장된 소재를 기획으로 넘길 수 있습니다" : "먼저 조사 가능한 소재를 쌓아야 합니다")}</strong>
        <p>
          {canonicalNext?.message
            || (hasReusableMaterial
              ? "게이트 탭에서 저장된 소재를 선택하고 제작 핸드오프를 기획 메모에 반영하세요."
              : "소재 탭에서 후보를 찾고 실제 URL, 관찰 메모, 선택 이유를 저장하세요.")}
        </p>
        {canonicalNext?.detail ? <small>{canonicalNext.detail}</small> : null}
      </div>

      <div className="next-action-panel">
        <span>Dry-run 사전 준비</span>
        <strong>{currentDryrun?.dryrunAllowed ? "packet과 readiness report가 저장됐습니다" : "소재 seed, packet, readiness report를 먼저 고정하세요"}</strong>
        <p>
          {currentDryrun?.artifactPaths?.readinessReport
            ? `${currentDryrun.materialTitle || "선택 소재"} · ${currentDryrun.artifactPaths.readinessReport}`
            : "저장된 소재가 없으면 preflight seed를 만들고 rough-cut dry-run packet과 readiness report를 함께 저장합니다."}
        </p>
        {currentDryrun?.failedChecks?.length ? (
          <small>막힌 항목: {currentDryrun.failedChecks.join(", ")}</small>
        ) : null}
      </div>

      <button className="generate-button gate-primary-action" onClick={runDryrunPreflight} disabled={preflighting}>
        {preflighting ? <Loader size={14} className="spin" /> : currentDryrun?.dryrunAllowed ? <FileCheck2 size={14} /> : <PlayCircle size={14} />}
        {currentDryrun?.dryrunAllowed ? "Dry-run report 다시 저장" : "소재 seed + dry-run report 저장"}
      </button>

      {latest ? (
        <button className="production-stage-card current" onClick={onOpenTopic}>
          <div className="production-stage-head">
            <Database size={18} />
            <span>{gateLabel(latest)}</span>
          </div>
          <strong>{latest.title}</strong>
          <p>출처 {latest.sourceCount}개 · 후보 점수 {latest.latestScore} · 소재 평가 {latest.evaluation?.score ?? 0}/{latest.evaluation?.verdict ?? "대기"}</p>
          <small>{latest.updatedAt || "업데이트 시간 없음"}</small>
          <ArrowRight size={16} className="stage-check" />
        </button>
      ) : null}

      <div className="gate-secondary-actions">
        <button className="subtle-button" onClick={onOpenTopic}>
          <Database size={13} /> 소재 DB 열기
        </button>
        <button className="subtle-button" onClick={onOpenPlan} disabled={!hasReusableMaterial}>
          <ArrowRight size={13} /> 기획으로 이동
        </button>
      </div>
    </div>
  );
}
