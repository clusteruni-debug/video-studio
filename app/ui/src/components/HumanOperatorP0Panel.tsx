import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  FileVideo2,
  FolderOpen,
  Loader,
  MonitorCheck,
  PackageCheck,
  PlayCircle,
  RefreshCcw,
  Wrench,
} from "lucide-react";
import { useStudioActions, useStudioState } from "../context/StudioContext";
import type { Scene } from "../lib/bridge";
import { HumanModeWorklistPanel, ProviderReadinessPanel } from "./HumanOperatorMvpPanels";

const BRIDGE_URL = "http://127.0.0.1:5161";

type HumanOperatorCheck = {
  key: string;
  label: string;
  status: string;
  ready: boolean;
  required: boolean;
  detail?: string;
  path?: string;
  repairAction?: string;
};

type ProviderReadiness = {
  key: string;
  label: string;
  category: string;
  state: string;
  ready: boolean;
  detail: string;
};

type HumanOperatorStatus = {
  ok: boolean;
  schema?: string;
  setup?: {
    criticalReady: boolean;
    demoModeReady: boolean;
    blockingChecks: string[];
    checks: HumanOperatorCheck[];
    providerMatrix: ProviderReadiness[];
  };
  demo?: {
    prepared: boolean;
    demoDir?: string;
    renderSmokePayloadPath?: string;
    renderEndpoint?: string;
    requiresExternalAi?: boolean;
    requiresPaidProvider?: boolean;
    requiresBrowserHandoff?: boolean;
  };
  localSourceWorkflow?: {
    status: string;
    label: string;
    message: string;
    repairAction: string;
  };
  renderHealth?: {
    status: string;
    label: string;
    message: string;
    ffmpeg?: HumanOperatorCheck;
  };
  nextAction?: {
    status: string;
    label: string;
    message: string;
    tab?: "home" | "topic" | "plan" | "sources" | "edit" | "review" | "advanced";
  };
  operatorBlockers?: {
    counts?: {
      blocked?: number;
      inProgress?: number;
      externalDependency?: number;
      staleCandidates?: number;
    };
  };
  worklist?: {
    counts?: {
      total?: number;
      requiresRuntimeProof?: number;
      blocked?: number;
      sourceReady?: number;
    };
    releaseBoundary?: string;
  };
  error?: string;
};

type DemoPrepareResponse = HumanOperatorStatus["demo"] & {
  ok: boolean;
  summary?: {
    renderSmokePayloadPath?: string;
    materialPath?: string;
    releaseBoundary?: string;
  };
  renderSmokePayload?: Record<string, unknown>;
  error?: string;
};

function sourceReady(scene: Scene) {
  return Boolean(
    scene._server_asset_path
    || scene._video_url
    || scene._upload_preview
    || scene._image_url
    || scene._selected_pexels_video
    || scene.has_image,
  );
}

function statusLabel(value?: string) {
  if (value === "ready") return "준비됨";
  if (value === "blocked" || value === "missing") return "차단";
  if (value === "optional-missing" || value === "config-required") return "선택 설정";
  if (value === "manual-only") return "수동";
  return "대기";
}

function statusClass(value?: string) {
  if (value === "ready") return "pass";
  if (value === "blocked" || value === "missing") return "fail";
  return "warn";
}

export default function HumanOperatorP0Panel() {
  const { draftResult, renderResult } = useStudioState();
  const actions = useStudioActions();
  const [status, setStatus] = useState<HumanOperatorStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preparedSummary, setPreparedSummary] = useState<DemoPrepareResponse["summary"] | null>(null);

  const scenes = draftResult?.scenes ?? [];
  const sourceCount = useMemo(() => scenes.filter(sourceReady).length, [scenes]);
  const renderOutput = renderResult?.renderResult?.outputPath;
  const renderLog = renderResult?.renderResult?.logPath;
  const setupChecks = status?.setup?.checks ?? [];
  const blocking = status?.setup?.blockingChecks ?? [];
  const providers = status?.setup?.providerMatrix ?? [];
  const optionalReady = providers.filter((item) => item.ready).length;
  const blockerCounts = status?.operatorBlockers?.counts;
  const worklistCounts = status?.worklist?.counts;

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${BRIDGE_URL}/api/human-operator/status`, {
        signal: AbortSignal.timeout(8000),
      });
      const payload = await response.json() as HumanOperatorStatus;
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "human operator 상태를 불러오지 못했습니다.");
      }
      setStatus(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "human operator 상태를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  async function prepareDemo() {
    setPreparing(true);
    setError(null);
    try {
      const response = await fetch(`${BRIDGE_URL}/api/human-operator/demo/prepare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: AbortSignal.timeout(10000),
      });
      const payload = await response.json() as DemoPrepareResponse;
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "No-LLM demo packet을 준비하지 못했습니다.");
      }
      setPreparedSummary(payload.summary ?? null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No-LLM demo packet을 준비하지 못했습니다.");
    } finally {
      setPreparing(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  const nextTab = status?.nextAction?.tab;
  const setupReady = status?.setup?.criticalReady === true;
  const demoPrepared = status?.demo?.prepared === true;

  return (
    <div className="gate-advanced-panel human-operator-p0-panel">
      <div className="gate-candidate-stack-head">
        <div>
          <strong>Human operator P0</strong>
          <span>AI 계정 없이 첫 실행, 데모, 소스, 렌더 상태를 확인합니다.</span>
        </div>
        <button className="subtle-button" onClick={refresh} disabled={loading}>
          {loading ? <Loader size={13} className="spin" /> : <RefreshCcw size={13} />}
          상태 갱신
        </button>
      </div>

      {error ? (
        <div className="gate-help-note warn">
          <AlertTriangle size={14} />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="next-action-panel human-primary-action">
        <span>인간 사용자 다음 행동</span>
        <strong>{status?.nextAction?.label || "브리지 상태 확인"}</strong>
        <p>{status?.nextAction?.message || "5161 bridge가 켜져 있는지 확인하세요."}</p>
        <div className="human-action-row">
          {!demoPrepared ? (
            <button className="workspace-primary-action" onClick={prepareDemo} disabled={preparing || !setupReady}>
              {preparing ? <Loader size={14} className="spin" /> : <PackageCheck size={14} />}
              No-LLM demo 준비
            </button>
          ) : (
            <button className="workspace-primary-action" onClick={() => actions.setActiveTab("edit")}>
              <PlayCircle size={14} />
              데모 렌더 준비 보기
            </button>
          )}
          {nextTab ? (
            <button className="workflow-secondary-action" onClick={() => actions.setActiveTab(nextTab)}>
              <MonitorCheck size={14} />
              관련 화면 열기
            </button>
          ) : null}
        </div>
      </div>

      <div className="human-p0-grid">
        <div className={`human-p0-card ${setupReady ? "pass" : "fail"}`}>
          <div className="production-stage-head">
            {setupReady ? <CheckCircle2 size={18} /> : <Wrench size={18} />}
            <span>{setupReady ? "ready" : `${blocking.length} blocked`}</span>
          </div>
          <strong>First-run setup</strong>
          <p>{setupReady ? "Python, Node/npm, FFmpeg, storage가 데모 경로에 충분합니다." : "필수 로컬 도구가 아직 준비되지 않았습니다."}</p>
          <div className="human-check-list">
            {setupChecks.map((check) => (
              <span key={check.key} className={statusClass(check.status)}>
                {check.label}: {statusLabel(check.status)}
              </span>
            ))}
          </div>
        </div>

        <div className={`human-p0-card ${demoPrepared ? "pass" : "warn"}`}>
          <div className="production-stage-head">
            <PackageCheck size={18} />
            <span>{demoPrepared ? "prepared" : "not prepared"}</span>
          </div>
          <strong>No-LLM demo path</strong>
          <p>
            {demoPrepared
              ? `payload: ${preparedSummary?.renderSmokePayloadPath || status?.demo?.renderSmokePayloadPath || "prepared"}`
              : "외부 AI, paid provider, browser handoff 없이 실행할 데모 packet을 먼저 만듭니다."}
          </p>
          <small>{status?.demo?.requiresExternalAi ? "external AI required" : "external AI not required"}</small>
        </div>

        <div className={`human-p0-card ${sourceCount > 0 ? "pass" : "warn"}`}>
          <div className="production-stage-head">
            <FolderOpen size={18} />
            <span>{sourceCount}/{scenes.length || 0}</span>
          </div>
          <strong>Local source proof</strong>
          <p>{sourceCount > 0 ? "현재 초안에 operator-owned source 후보가 있습니다." : status?.localSourceWorkflow?.repairAction || "소스 탭에서 local upload proof를 남기세요."}</p>
          <button className="subtle-button" onClick={() => actions.setActiveTab("sources")}>소스 열기</button>
        </div>

        <div className={`human-p0-card ${renderOutput ? "pass" : statusClass(status?.renderHealth?.status)}`}>
          <div className="production-stage-head">
            <FileVideo2 size={18} />
            <span>{renderOutput ? "rendered" : statusLabel(status?.renderHealth?.status)}</span>
          </div>
          <strong>Render health</strong>
          <p>{renderOutput || status?.renderHealth?.message || "렌더 후보가 아직 없습니다."}</p>
          {renderLog ? <small>log: {renderLog}</small> : <small>{status?.renderHealth?.ffmpeg?.detail || "FFmpeg status unknown"}</small>}
        </div>
      </div>

      <div className="workspace-stat-strip">
        <span><MonitorCheck size={14} /> P0 setup {setupReady ? "ready" : "blocked"}</span>
        <span><PackageCheck size={14} /> demo {demoPrepared ? "prepared" : "pending"}</span>
        <span><FolderOpen size={14} /> local source {sourceCount}/{scenes.length || 0}</span>
        <span><FileVideo2 size={14} /> optional providers ready {optionalReady}</span>
        <span><AlertTriangle size={14} /> blockers {blockerCounts?.blocked ?? 0} / stale {blockerCounts?.staleCandidates ?? 0}</span>
        <span><ClipboardCheck size={14} /> residual proof {worklistCounts?.requiresRuntimeProof ?? 0}</span>
      </div>

      <ProviderReadinessPanel />
      <HumanModeWorklistPanel />
    </div>
  );
}
