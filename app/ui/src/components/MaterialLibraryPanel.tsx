import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, BookOpen, CheckCircle2, Circle, Database, FileCheck2, Loader, PlayCircle, RefreshCcw } from "lucide-react";

type MaterialLibraryCandidate = {
  id?: string;
  title?: string;
  centralQuestion?: string;
  searchSeed?: string;
  score?: number;
  scoreBreakdown?: Record<string, number>;
  rankingReason?: string;
  nextPipelineAction?: string;
  sourceStatus?: string;
};

type GateResultLike = {
  ready?: boolean;
  status?: string;
  failedChecks?: string[];
  report?: Record<string, unknown>;
};

type StageSnapshot = {
  stage: string;
  label: string;
  status: string;
  detail: string;
  nextAction: string;
  failedChecks?: string[];
};

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
};

type MaterialLibraryResponse = {
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

export type MaterialProductionHandoff = {
  schema: "video-studio.material-production-handoff.v1";
  materialId: string;
  title?: string;
  centralQuestion?: string;
  searchSeed?: string;
  promptMemo: string;
  storyboardSeed?: {
    openingPromise?: string;
    chapterPrompts?: Array<{ chapterId: string; promise: string }>;
    sourceLedgerRefs?: string[];
  };
  sourcePromptBibleSeed?: {
    researchSurfaces?: string[];
    sourceLedgerRefs?: Array<{ sourceId: string; title: string; sourceType: string; url?: string }>;
  };
  nextDashboardAction?: {
    tab: string;
    label: string;
    blockedUntil?: string[];
  };
};

type IntakeResponse = MaterialLibraryResponse & {
  created?: boolean;
  material?: {
    materialId: string;
    title: string;
  };
  duplicateCandidates?: Array<{
    materialId: string;
    title: string;
    reason: string;
    similarity: number;
  }>;
  productionGates?: {
    currentStage: string;
    overallStatus: string;
    nextAction: string;
    stages: StageSnapshot[];
  };
  productionHandoff?: MaterialProductionHandoff;
  materialEvaluation?: MaterialEvaluation;
};

type MaterialEvaluation = {
  schema: "video-studio.material-evaluation-gate.v1";
  score: number;
  verdict: "pass" | "review" | "blocked";
  blockedChecks: string[];
  pendingChecks: string[];
  nextAction: string;
  checks: Array<{
    key: string;
    label: string;
    status: "pass" | "pending" | "blocked";
    detail: string;
    nextAction: string;
  }>;
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

type MaterialLibraryPanelProps = {
  candidate: MaterialLibraryCandidate;
  topicPacket: Record<string, unknown>;
  topicGateResult?: GateResultLike | null;
  onUseProductionHandoff?: (handoff: MaterialProductionHandoff) => void;
};

const BRIDGE_URL = "http://127.0.0.1:5161";
const STALE_BRIDGE_MESSAGE = "현재 실행 중인 브리지가 오래된 코드입니다. 5161 bridge를 재시작해야 소재 DB API가 보입니다.";

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function statusLabel(status: string) {
  if (status === "pass") return "통과";
  if (status === "blocked") return "막힘";
  if (status === "pending") return "대기";
  return status || "대기";
}

function ShieldCheckIcon({ verdict }: { verdict: "pass" | "review" | "blocked" }) {
  if (verdict === "pass") return <CheckCircle2 size={14} />;
  if (verdict === "blocked") return <AlertTriangle size={14} />;
  return <Circle size={14} />;
}

function pickSourceCount(topicPacket: Record<string, unknown>) {
  return asArray(topicPacket.sourceLedger).length;
}

export default function MaterialLibraryPanel({ candidate, topicPacket, topicGateResult, onUseProductionHandoff }: MaterialLibraryPanelProps) {
  const [library, setLibrary] = useState<MaterialLibraryResponse | null>(null);
  const [lastIntake, setLastIntake] = useState<IntakeResponse | null>(null);
  const [selectedHandoff, setSelectedHandoff] = useState<MaterialProductionHandoff | null>(null);
  const [dryrunPreflight, setDryrunPreflight] = useState<DryrunPreflightStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dryrunLoading, setDryrunLoading] = useState(false);
  const [handoffLoadingId, setHandoffLoadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sourceCount = useMemo(() => pickSourceCount(topicPacket), [topicPacket]);

  async function refreshLibrary() {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${BRIDGE_URL}/api/topic-library/materials`);
      if (response.status === 404) throw new Error(STALE_BRIDGE_MESSAGE);
      const payload = await response.json() as MaterialLibraryResponse;
      if (!response.ok || !payload.ok) throw new Error(payload.error || "소재 라이브러리를 불러오지 못했습니다.");
      setLibrary(payload);
      if (payload.dryrunPreflight?.available) setDryrunPreflight(payload.dryrunPreflight);
    } catch (err) {
      setError(err instanceof Error ? err.message : "소재 라이브러리를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  async function loadProductionHandoff(materialId: string) {
    setHandoffLoadingId(materialId);
    setError(null);
    try {
      const response = await fetch(`${BRIDGE_URL}/api/topic-library/materials/${materialId}/production-handoff`);
      if (response.status === 404) throw new Error(STALE_BRIDGE_MESSAGE);
      const payload = await response.json() as { ok: boolean; productionHandoff?: MaterialProductionHandoff; error?: string };
      if (!response.ok || !payload.ok || !payload.productionHandoff) {
        throw new Error(payload.error || "제작 핸드오프를 불러오지 못했습니다.");
      }
      setSelectedHandoff(payload.productionHandoff);
    } catch (err) {
      setError(err instanceof Error ? err.message : "제작 핸드오프를 불러오지 못했습니다.");
    } finally {
      setHandoffLoadingId(null);
    }
  }

  async function saveMaterial() {
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(`${BRIDGE_URL}/api/topic-library/materials/intake`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          candidate,
          topicPacket,
          sourceLedger: topicPacket.sourceLedger ?? [],
          researchQueryPlan: topicPacket.researchQueryPlan ?? [],
          topicGateResult,
        }),
      });
      if (response.status === 404) throw new Error(STALE_BRIDGE_MESSAGE);
      const payload = await response.json() as IntakeResponse;
      if (!response.ok || !payload.ok) throw new Error(payload.error || "소재 저장에 실패했습니다.");
      setLastIntake(payload);
      if (payload.productionHandoff) setSelectedHandoff(payload.productionHandoff);
      setLibrary({ ok: true, stats: payload.stats, summaries: library?.summaries ?? [] });
      await refreshLibrary();
    } catch (err) {
      setError(err instanceof Error ? err.message : "소재 저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  async function runDryrunPreflight(materialId?: string) {
    setDryrunLoading(true);
    setError(null);
    try {
      const response = await fetch(`${BRIDGE_URL}/api/topic-library/materials/dryrun-preflight`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ materialId, targetStage: "rough-cut" }),
      });
      if (response.status === 404) throw new Error(STALE_BRIDGE_MESSAGE);
      const payload = await response.json() as DryrunPreflightResponse;
      if (!response.ok || !payload.ok || !payload.summary) {
        throw new Error(payload.error || "Dry-run packet과 readiness report를 저장하지 못했습니다.");
      }
      setDryrunPreflight(payload.summary);
      await refreshLibrary();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dry-run packet과 readiness report를 저장하지 못했습니다.");
    } finally {
      setDryrunLoading(false);
    }
  }

  useEffect(() => {
    void refreshLibrary();
  }, []);

  const stages = lastIntake?.productionGates?.stages ?? [];
  const summaries = library?.summaries ?? [];
  const materialEvaluation = lastIntake?.materialEvaluation;
  const dryrunMaterialId = lastIntake?.material?.materialId ?? summaries[0]?.materialId;
  const currentDryrun = dryrunPreflight ?? library?.dryrunPreflight ?? null;

  return (
    <div className="gate-advanced-panel material-library-panel">
      <div className="gate-candidate-stack-head">
        <div>
          <strong>소재 DB / 라이브러리</strong>
          <span>중복 여부와 제작 게이트 상태를 누적합니다.</span>
        </div>
        <button className="subtle-button" onClick={refreshLibrary} disabled={loading}>
          {loading ? <Loader size={13} className="spin" /> : <RefreshCcw size={13} />}
          새로고침
        </button>
      </div>

      <div className="gate-selected-candidate-plan">
        <span>누적 소재 {library?.stats?.total ?? 0}</span>
        <span>sourceLedger 보유 {library?.stats?.withSourceLedger ?? 0}</span>
        <span>소재 게이트 통과 {library?.stats?.withTopicPass ?? 0}</span>
        <span>현재 후보 출처 {sourceCount}</span>
      </div>

      <button className="generate-button gate-primary-action" onClick={saveMaterial} disabled={saving}>
        {saving ? <Loader size={14} className="spin" /> : <Database size={14} />}
        소재 라이브러리에 저장
      </button>

      <button className="generate-button gate-primary-action" onClick={() => runDryrunPreflight(dryrunMaterialId)} disabled={dryrunLoading}>
        {dryrunLoading ? <Loader size={14} className="spin" /> : currentDryrun?.dryrunAllowed ? <FileCheck2 size={14} /> : <PlayCircle size={14} />}
        {currentDryrun?.dryrunAllowed ? "Dry-run readiness report 다시 저장" : "소재 seed / packet / readiness report 준비"}
      </button>

      {error ? (
        <div className="gate-help-note warn">
          <AlertTriangle size={14} />
          <span>{error}</span>
        </div>
      ) : null}

      {lastIntake ? (
        <div className="gate-help-note">
          <CheckCircle2 size={14} />
          <span>{lastIntake.created ? "새 소재로 저장했습니다." : "기존 소재에 조사/게이트 이력을 병합했습니다."}</span>
        </div>
      ) : null}

      {selectedHandoff ? (
        <div className="gate-check-list">
          <div className="gate-check-row pass">
            <ArrowRight size={14} />
            <div className="gate-check-meta">
              <span>제작 핸드오프 준비됨</span>
              <p>{selectedHandoff.title || candidate.title} 소재를 기획 메모, 스토리보드 seed, 소스 프롬프트 bible seed로 넘길 수 있습니다.</p>
            </div>
          </div>
          {onUseProductionHandoff ? (
            <button className="generate-button gate-primary-action" onClick={() => onUseProductionHandoff(selectedHandoff)}>
              <ArrowRight size={14} />
              기획 메모에 반영
            </button>
          ) : null}
        </div>
      ) : null}

      {currentDryrun?.available || currentDryrun?.artifactPaths ? (
        <div className="gate-check-list">
          <div className={`gate-check-row ${currentDryrun.dryrunAllowed ? "pass" : "warn"}`}>
            {currentDryrun.dryrunAllowed ? <FileCheck2 size={14} /> : <AlertTriangle size={14} />}
            <div className="gate-check-meta">
              <span>Dry-run 사전 준비 · {currentDryrun.dryrunAllowed ? "통과" : "보완 필요"}</span>
              <p>{currentDryrun.artifactPaths?.readinessReport || "readiness report 저장 전입니다."}</p>
            </div>
          </div>
          {currentDryrun.releaseBoundary ? (
            <div className="gate-help-note">
              <BookOpen size={14} />
              <span>{currentDryrun.releaseBoundary}</span>
            </div>
          ) : null}
        </div>
      ) : null}

      {lastIntake?.duplicateCandidates?.length ? (
        <div className="gate-fail-list">
          <strong>중복 후보</strong>
          <div>
            {lastIntake.duplicateCandidates.map((item) => (
              <span key={item.materialId}>{item.title} {Math.round(item.similarity * 100)}%</span>
            ))}
          </div>
        </div>
      ) : null}

      {materialEvaluation ? (
        <div className="gate-check-list">
          <div className={`gate-check-row ${materialEvaluation.verdict === "pass" ? "pass" : materialEvaluation.verdict === "blocked" ? "fail" : "warn"}`}>
            <ShieldCheckIcon verdict={materialEvaluation.verdict} />
            <div className="gate-check-meta">
              <span>소재 평가 게이트 · {materialEvaluation.verdict} · {materialEvaluation.score}/100</span>
              <p>{materialEvaluation.nextAction}</p>
            </div>
          </div>
          {materialEvaluation.checks.map((check) => (
            <div key={check.key} className={`gate-check-row ${check.status === "pass" ? "pass" : check.status === "blocked" ? "fail" : "warn"}`}>
              <ShieldCheckIcon verdict={check.status === "pass" ? "pass" : check.status === "blocked" ? "blocked" : "review"} />
              <div className="gate-check-meta">
                <span>{check.label} · {statusLabel(check.status)}</span>
                <p>{check.detail}</p>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {stages.length ? (
        <div className="gate-check-list">
          {stages.map((stage) => (
            <div key={stage.stage} className={`gate-check-row ${stage.status === "pass" ? "pass" : stage.status === "blocked" ? "fail" : "warn"}`}>
              <BookOpen size={14} />
              <div className="gate-check-meta">
                <span>{stage.label} · {statusLabel(stage.status)}</span>
                <p>{stage.status === "pass" ? stage.detail : stage.nextAction}</p>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {summaries.length ? (
        <div className="gate-selected-candidate-plan">
          {summaries.slice(0, 4).map((item) => (
            <button
              key={item.materialId}
              className="subtle-button"
              onClick={() => loadProductionHandoff(item.materialId)}
              disabled={handoffLoadingId === item.materialId}
            >
              {handoffLoadingId === item.materialId ? <Loader size={13} className="spin" /> : <ArrowRight size={13} />}
              {item.title} · 출처 {item.sourceCount} · 평가 {item.evaluation?.score ?? 0}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
