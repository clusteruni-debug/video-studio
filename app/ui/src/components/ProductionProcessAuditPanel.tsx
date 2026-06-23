import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader, RefreshCcw, ShieldCheck } from "lucide-react";

type ProcessAuditRow = {
  stage: string;
  label: string;
  status: "covered" | "gap";
  coverageStatus?: "covered" | "gap";
  proofGrade?: string;
  proofRequiresRuntimeEvidence?: boolean;
  missing: string[];
  dashboardSurfaces: string[];
  gateAnchors: string[];
  testAnchors: string[];
  evidenceRequired: string[];
  nextAction: string;
};

type ProcessAuditResponse = {
  ok: boolean;
  audit?: {
    schema: "video-studio.production-process-gate-audit.v1";
    stageCount: number;
    coveredStageCount: number;
    gapStageCount: number;
    proofValidatorStageCount?: number;
    structuredProofStageCount?: number;
    coverageVerdict?: "pass" | "review";
    proofVerdict?: "pass" | "review";
    verdict: "pass" | "review";
    rows: ProcessAuditRow[];
  };
  error?: string;
};

const BRIDGE_URL = "http://127.0.0.1:5161";

export default function ProductionProcessAuditPanel() {
  const [payload, setPayload] = useState<ProcessAuditResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${BRIDGE_URL}/api/production-gates/process-audit`);
      const body = await response.json() as ProcessAuditResponse;
      if (!response.ok || !body.ok || !body.audit) {
        throw new Error(body.error || "전 과정 게이트 검수 결과를 불러오지 못했습니다.");
      }
      setPayload(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "전 과정 게이트 검수 결과를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  const audit = payload?.audit;
  const rows = audit?.rows ?? [];
  const gaps = rows.filter((row) => row.status !== "covered");
  const proofRuntimeRows = rows.filter((row) => row.proofRequiresRuntimeEvidence);

  return (
    <div className="gate-advanced-panel production-process-audit-panel">
      <div className="gate-candidate-stack-head">
        <div>
          <strong>전 과정 게이트 검수</strong>
          <span>현재 구현된 제작 프로세스가 대시보드, 게이트 코드, 테스트, 증거 요구사항에 매핑되어 있는지 확인합니다.</span>
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

      <div className="workspace-stat-strip">
        <span><ShieldCheck size={14} /> 단계 {audit?.stageCount ?? 0}</span>
        <span><CheckCircle2 size={14} /> coverage {audit?.coveredStageCount ?? 0}</span>
        <span><ShieldCheck size={14} /> validator {audit?.proofValidatorStageCount ?? 0}</span>
        <span><AlertTriangle size={14} /> runtime proof {audit?.structuredProofStageCount ?? proofRuntimeRows.length}</span>
        <span><AlertTriangle size={14} /> gap {audit?.gapStageCount ?? 0}</span>
      </div>

      <div className={`gate-help-note ${gaps.length || proofRuntimeRows.length ? "warn" : ""}`}>
        {gaps.length || proofRuntimeRows.length ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
        <span>
          {gaps.length
            ? "일부 제작 단계의 코드/테스트/대시보드 매핑이 비어 있습니다."
            : proofRuntimeRows.length
              ? "12개 제작 단계는 매핑됐지만, 일부 단계는 실제 source/import/render/review proof가 있어야 통과합니다."
              : "12개 제작 단계가 코드, 테스트, 대시보드 surface, 증거 요구사항에 매핑되어 있습니다."}
        </span>
      </div>

      <div className="gate-check-list">
        {rows.map((row) => (
          <div key={row.stage} className={`gate-check-row ${row.status === "covered" ? "pass" : "fail"}`}>
            {row.status === "covered" ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            <div className="gate-check-meta">
              <span>{row.label} · {row.status === "covered" ? "매핑됨" : "gap"}</span>
              <p>
                화면 {row.dashboardSurfaces.join(", ") || "없음"} · 코드 {row.gateAnchors.length} · 테스트 {row.testAnchors.length}
              </p>
              <small>
                {row.proofGrade || "coverage"}{row.proofRequiresRuntimeEvidence ? " · runtime evidence required" : ""} ·{" "}
                {row.evidenceRequired.slice(0, 4).join(", ")}
              </small>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
