import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  FileVideo2,
  FolderOpen,
  Loader,
  PackageCheck,
  RefreshCcw,
  Smartphone,
  Wrench,
} from "lucide-react";
import { useStudioState } from "../context/StudioContext";

const BRIDGE_URL = "http://127.0.0.1:5161";

type SourceWorkflowStatus = {
  ok: boolean;
  status: string;
  acceptedCount: number;
  rejectedCount: number;
  browserBlockerCount: number;
  nextAction: string;
  acceptedSources?: Array<{ sourceId?: string; sceneId?: string; proofKind?: string; sourcePath?: string }>;
  error?: string;
};

type RenderHealthStatus = {
  ok: boolean;
  status: string;
  failureCategory: string;
  outputPath?: string;
  logPath?: string;
  nextAction: string;
  repairActions?: Record<string, string>;
  error?: string;
};

type DemoRenderResult = {
  ok: boolean;
  error?: string;
  failureCategory?: string;
  renderResult?: {
    outputPath?: string;
    logPath?: string;
    manifestPath?: string;
  };
};

type PhoneReviewStatus = {
  ok: boolean;
  status: string;
  nextAction: string;
  review?: {
    acceptedForPublishPacket?: boolean;
    decision?: string;
    renderId?: string;
    reviewedAt?: string;
  } | null;
  error?: string;
};

type PublishPacket = {
  ok: boolean;
  uploadAllowed: boolean;
  decision: string;
  blockers: string[];
  title?: string;
  description?: string;
  aiDisclosure?: string;
  operatorBoundary?: string;
  error?: string;
};

type ProviderReadiness = {
  ok: boolean;
  demoModeReady: boolean;
  counts: {
    ready: number;
    configRequired: number;
    manualOnly: number;
    blocked: number;
  };
  providers: Array<{
    key: string;
    label: string;
    function: string;
    state: string;
    modes: string[];
    requiredForDemo: boolean;
    repairAction: string;
  }>;
  error?: string;
};

type HumanModeWorklist = {
  ok: boolean;
  releaseBoundary: string;
  counts: {
    total: number;
    requiresRuntimeProof: number;
    blocked: number;
    sourceReady: number;
    docRefresh: number;
  };
  items: Array<{
    key: string;
    title: string;
    category: string;
    status: string;
    docPath: string;
    requiresRuntimeProof: boolean;
    nextAction: string;
    details?: string[];
  }>;
  error?: string;
};

function statusClass(status?: string) {
  if (status === "ready" || status === "pass") return "pass";
  if (status === "blocked" || status === "missing" || status?.startsWith("blocked")) return "fail";
  return "warn";
}

function statusLabel(status?: string) {
  if (status === "ready" || status === "pass") return "준비됨";
  if (status === "blocked" || status === "missing") return "차단";
  if (status === "manual-only") return "수동";
  if (status === "config-required") return "설정 필요";
  if (status === "optional-config") return "선택 설정";
  if (status === "pending-runtime-proof") return "런타임 증거 필요";
  if (status === "pending-source-proof") return "소스 증거 필요";
  if (status === "pending-render-proof") return "렌더 증거 필요";
  if (status === "blocked-external-proof") return "외부 증거 차단";
  if (status === "blocked-runtime-proof") return "런타임 증거 차단";
  if (status === "source-ready") return "소스 준비";
  if (status === "doc-refresh") return "문서 갱신";
  if (status === "paid-opt-in") return "유료 opt-in";
  return "대기";
}

async function readJson<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BRIDGE_URL}${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    signal: AbortSignal.timeout(12000),
  });
  const payload = await response.json() as T & { ok?: boolean; error?: string };
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `request failed: ${path}`);
  }
  return payload;
}

export function ProviderReadinessPanel() {
  const [status, setStatus] = useState<ProviderReadiness | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      setStatus(await readJson<ProviderReadiness>("/api/human-operator/provider-readiness"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "provider readiness를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="human-mvp-panel">
      <div className="gate-candidate-stack-head">
        <div>
          <strong>Provider readiness matrix</strong>
          <span>Demo Mode, Manual Production, Provider-Assisted의 필요 도구를 분리합니다.</span>
        </div>
        <button className="subtle-button" onClick={refresh} disabled={loading}>
          {loading ? <Loader size={13} className="spin" /> : <RefreshCcw size={13} />}
          갱신
        </button>
      </div>
      {error ? <p className="fail">{error}</p> : null}
      <div className="human-provider-grid">
        {(status?.providers ?? []).map((provider) => (
          <article key={provider.key} className={`human-provider-card ${statusClass(provider.state)}`}>
            <span>{provider.function}</span>
            <strong>{provider.label}</strong>
            <p>{provider.repairAction}</p>
            <small>{statusLabel(provider.state)} / {provider.modes.join(", ")}</small>
          </article>
        ))}
      </div>
      <div className="workspace-stat-strip">
        <span><CheckCircle2 size={14} /> ready {status?.counts.ready ?? 0}</span>
        <span><Wrench size={14} /> config {status?.counts.configRequired ?? 0}</span>
        <span><ClipboardCheck size={14} /> manual {status?.counts.manualOnly ?? 0}</span>
        <span><AlertTriangle size={14} /> blocked {status?.counts.blocked ?? 0}</span>
      </div>
    </div>
  );
}

export function HumanModeWorklistPanel() {
  const [status, setStatus] = useState<HumanModeWorklist | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      setStatus(await readJson<HumanModeWorklist>("/api/human-operator/worklist"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "human-mode worklist를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="human-mvp-panel">
      <div className="gate-candidate-stack-head">
        <div>
          <strong>Human-mode remaining work</strong>
          <span>문서상 잔여 작업을 설정/소스/런타임 proof로 나눕니다.</span>
        </div>
        <button className="subtle-button" onClick={refresh} disabled={loading}>
          {loading ? <Loader size={13} className="spin" /> : <RefreshCcw size={13} />}
          갱신
        </button>
      </div>
      {error ? <p className="fail">{error}</p> : null}
      <div className="human-worklist-grid">
        {(status?.items ?? []).map((item) => (
          <article key={item.key} className={`human-worklist-card ${statusClass(item.status)}`}>
            <div>
              <span>{item.category}</span>
              <strong>{item.title}</strong>
            </div>
            <p>{item.nextAction}</p>
            <small>{statusLabel(item.status)} / {item.requiresRuntimeProof ? "runtime proof" : "source/doc"}</small>
            <small>{item.docPath}</small>
          </article>
        ))}
      </div>
      <div className="workspace-stat-strip">
        <span><ClipboardCheck size={14} /> total {status?.counts.total ?? 0}</span>
        <span><AlertTriangle size={14} /> runtime proof {status?.counts.requiresRuntimeProof ?? 0}</span>
        <span><Wrench size={14} /> blocked {status?.counts.blocked ?? 0}</span>
        <span><CheckCircle2 size={14} /> source-ready {status?.counts.sourceReady ?? 0}</span>
      </div>
      <p className="human-panel-note">{status?.releaseBoundary || "Windows/browser/phone proof는 source-only 구현과 분리됩니다."}</p>
    </div>
  );
}

export function SourceReviewMvpPanel() {
  const { draftResult } = useStudioState();
  const [status, setStatus] = useState<SourceWorkflowStatus | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [sceneId, setSceneId] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const [notes, setNotes] = useState("");
  const [decision, setDecision] = useState<"accepted" | "rejected">("accepted");
  const [proofKind, setProofKind] = useState("local-upload");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scenes = draftResult?.scenes ?? [];

  async function refresh() {
    setError(null);
    try {
      setStatus(await readJson<SourceWorkflowStatus>("/api/human-operator/sources/status"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "source proof 상태를 불러오지 못했습니다.");
    }
  }

  async function saveReview() {
    setSaving(true);
    setError(null);
    try {
      await readJson<SourceWorkflowStatus>("/api/human-operator/sources/review", {
        method: "POST",
        body: JSON.stringify({ sourceId, sceneId, sourcePath, decision, proofKind, notes }),
      });
      setSourceId("");
      setSourcePath("");
      setNotes("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "source review 저장 실패");
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  const canSave = sourceId.trim().length > 0 || sourcePath.trim().length > 0;

  return (
    <div className="human-mvp-panel">
      <div className="gate-candidate-stack-head">
        <div>
          <strong>Accepted-source review</strong>
          <span>로컬 업로드와 browser proof를 구분해 source proof를 저장합니다.</span>
        </div>
        <span className={statusClass(status?.status)}>{statusLabel(status?.status)}</span>
      </div>

      {error ? <p className="fail">{error}</p> : null}

      <div className="human-form-grid">
        <label>
          <span>sourceId</span>
          <input value={sourceId} onChange={(event) => setSourceId(event.target.value)} placeholder="scene-01-local-video" />
        </label>
        <label>
          <span>scene</span>
          <select value={sceneId} onChange={(event) => setSceneId(event.target.value)}>
            <option value="">공통</option>
            {scenes.map((scene, index) => (
              <option key={scene.scene_num || index} value={`scene-${scene.scene_num || index + 1}`}>
                scene-{scene.scene_num || index + 1}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>proof</span>
          <select value={proofKind} onChange={(event) => setProofKind(event.target.value)}>
            <option value="local-upload">local upload</option>
            <option value="direct-import">direct import</option>
            <option value="stock-source">stock source</option>
            <option value="browser-proof">browser proof</option>
          </select>
        </label>
        <label>
          <span>decision</span>
          <select value={decision} onChange={(event) => setDecision(event.target.value as "accepted" | "rejected")}>
            <option value="accepted">accepted</option>
            <option value="rejected">rejected</option>
          </select>
        </label>
      </div>
      <label className="human-wide-field">
        <span>source path or URL</span>
        <input value={sourcePath} onChange={(event) => setSourcePath(event.target.value)} placeholder="storage/inputs/... or local://..." />
      </label>
      <label className="human-wide-field">
        <span>review notes</span>
        <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="why this source is accepted or rejected" />
      </label>
      <div className="human-action-row">
        <button className="workspace-primary-action" onClick={saveReview} disabled={!canSave || saving}>
          {saving ? <Loader size={14} className="spin" /> : <FolderOpen size={14} />}
          source decision 저장
        </button>
        <button className="workflow-secondary-action" onClick={refresh}>상태 갱신</button>
      </div>
      <div className="workspace-stat-strip">
        <span>accepted {status?.acceptedCount ?? 0}</span>
        <span>rejected {status?.rejectedCount ?? 0}</span>
        <span>browser blockers {status?.browserBlockerCount ?? 0}</span>
      </div>
      <p className="human-panel-note">{status?.nextAction || "accepted source proof가 production render의 첫 조건입니다."}</p>
    </div>
  );
}

export function RenderRecoveryPanel() {
  const [status, setStatus] = useState<RenderHealthStatus | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const repairAction = status?.repairActions?.[status.failureCategory] || status?.nextAction;

  async function refresh() {
    setError(null);
    try {
      setStatus(await readJson<RenderHealthStatus>("/api/human-operator/render-health"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "render health를 불러오지 못했습니다.");
    }
  }

  async function runDemoRender() {
    setRunning(true);
    setError(null);
    try {
      const result = await readJson<DemoRenderResult>("/api/human-operator/demo/render", { method: "POST" });
      if (!result.ok) throw new Error(result.error || "demo render failed");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "demo render 실행 실패");
      await refresh();
    } finally {
      setRunning(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="human-mvp-panel">
      <div className="gate-candidate-stack-head">
        <div>
          <strong>Render health and recovery</strong>
          <span>FFmpeg, manifest, source, subtitle, audio, permission 오류를 분류합니다.</span>
        </div>
        <span className={statusClass(status?.status)}>{statusLabel(status?.status)}</span>
      </div>
      {error ? <p className="fail">{error}</p> : null}
      <div className={`human-render-state ${statusClass(status?.status)}`}>
        <FileVideo2 size={18} />
        <div>
          <strong>{status?.failureCategory || "not-run"}</strong>
          <p>{repairAction || "No-LLM demo render를 실행해 render proof를 만드세요."}</p>
          {status?.outputPath ? <small>output: {status.outputPath}</small> : null}
          {status?.logPath ? <small>log: {status.logPath}</small> : null}
        </div>
      </div>
      <div className="human-action-row">
        <button className="workspace-primary-action" onClick={runDemoRender} disabled={running}>
          {running ? <Loader size={14} className="spin" /> : <PackageCheck size={14} />}
          No-LLM demo render 실행
        </button>
        <button className="workflow-secondary-action" onClick={refresh}>상태 갱신</button>
      </div>
    </div>
  );
}

export function PhoneReviewPublishPanel() {
  const { renderResult } = useStudioState();
  const [phoneStatus, setPhoneStatus] = useState<PhoneReviewStatus | null>(null);
  const [packet, setPacket] = useState<PublishPacket | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const renderPath = renderResult?.renderResult?.outputPath || "";
  const [renderId, setRenderId] = useState(renderResult?.renderResult?.outputPath || "");
  const [watchedDurationSec, setWatchedDurationSec] = useState("30");
  const [notes, setNotes] = useState("");
  const [decision, setDecision] = useState<"accepted" | "needs-fix" | "rejected">("needs-fix");
  const [checks, setChecks] = useState({
    captionsOk: false,
    sourceFitOk: false,
    audioOk: false,
    pacingOk: false,
    disclosureOk: false,
  });

  async function refresh() {
    setError(null);
    try {
      const [phone, publish] = await Promise.all([
        readJson<PhoneReviewStatus>("/api/human-operator/phone-review/status"),
        readJson<PublishPacket>("/api/human-operator/publish-packet"),
      ]);
      setPhoneStatus(phone);
      setPacket(publish);
      if (!renderId && renderResult?.renderResult?.outputPath) setRenderId(renderResult.renderResult.outputPath);
    } catch (err) {
      setError(err instanceof Error ? err.message : "phone review 상태를 불러오지 못했습니다.");
    }
  }

  async function saveReview() {
    setSaving(true);
    setError(null);
    try {
      await readJson<PhoneReviewStatus>("/api/human-operator/phone-review", {
        method: "POST",
        body: JSON.stringify({
          renderId: renderId || renderPath,
          watchedDurationSec,
          fullWatchCompleted: true,
          decision,
          ...checks,
          notes,
        }),
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "phone review 저장 실패");
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  const canSave = (renderId || renderPath).trim().length > 0;

  return (
    <div className="human-mvp-panel">
      <div className="gate-candidate-stack-head">
        <div>
          <strong>Phone review and publish packet</strong>
          <span>업로드는 자동화하지 않고 사람이 검수 증거를 남긴 뒤 packet만 확인합니다.</span>
        </div>
        <span className={statusClass(packet?.uploadAllowed ? "ready" : "blocked")}>
          {packet?.uploadAllowed ? "upload packet ready" : "publish blocked"}
        </span>
      </div>
      {error ? <p className="fail">{error}</p> : null}
      <div className="human-form-grid">
        <label>
          <span>render id/path</span>
          <input value={renderId} onChange={(event) => setRenderId(event.target.value)} placeholder="storage/renders/...mp4" />
        </label>
        <label>
          <span>watched seconds</span>
          <input value={watchedDurationSec} onChange={(event) => setWatchedDurationSec(event.target.value)} inputMode="numeric" />
        </label>
        <label>
          <span>decision</span>
          <select value={decision} onChange={(event) => setDecision(event.target.value as "accepted" | "needs-fix" | "rejected")}>
            <option value="needs-fix">needs-fix</option>
            <option value="accepted">accepted</option>
            <option value="rejected">rejected</option>
          </select>
        </label>
      </div>
      <div className="human-check-toggle-grid">
        {(Object.entries(checks) as Array<[keyof typeof checks, boolean]>).map(([key, checked]) => (
          <label key={key}>
            <input
              type="checkbox"
              checked={checked}
              onChange={(event) => setChecks((prev) => ({ ...prev, [key]: event.target.checked }))}
            />
            {key}
          </label>
        ))}
      </div>
      <label className="human-wide-field">
        <span>review notes</span>
        <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="phone viewport, captions, audio, pacing, source fit" />
      </label>
      <div className="human-action-row">
        <button className="workspace-primary-action" onClick={saveReview} disabled={!canSave || saving}>
          {saving ? <Loader size={14} className="spin" /> : <Smartphone size={14} />}
          phone review 저장
        </button>
        <button className="workflow-secondary-action" onClick={refresh}>packet 갱신</button>
      </div>
      <div className="human-publish-packet">
        <strong>{packet?.title || "Publish packet"}</strong>
        <p>{packet?.description || "render/source/phone review 증거가 모이면 upload blocker가 사라집니다."}</p>
        <small>{packet?.aiDisclosure || "AI disclosure pending"}</small>
        <div className="human-check-list">
          {(packet?.blockers ?? ["render-candidate-required", "accepted-source-required", "phone-review-required"]).map((blocker) => (
            <span key={blocker} className="fail">{blocker}</span>
          ))}
          {packet?.uploadAllowed ? <span className="pass">operator upload packet ready</span> : null}
        </div>
      </div>
      <p className="human-panel-note">{phoneStatus?.nextAction || packet?.operatorBoundary}</p>
    </div>
  );
}
