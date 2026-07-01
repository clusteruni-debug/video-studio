import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  ClipboardCheck,
  Database as DatabaseIcon,
  FileVideo2,
  FolderOpen,
  ListChecks,
  SearchCheck,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import { useStudioActions, useStudioState, type StudioTab } from "../context/StudioContext";
import type { Scene } from "../lib/bridge";

type GateStatus = "pass" | "pending" | "blocked";
type GateFocus = "all" | "topic" | "plan" | "sources" | "edit" | "review";

type WorkflowGate = {
  id: string;
  label: string;
  status: GateStatus;
  detail: string;
  nextAction: string;
  tab: StudioTab;
  focus: GateFocus[];
  icon: typeof ShieldCheck;
};

type ProductionWorkflowGatePanelProps = {
  focus?: GateFocus;
  compact?: boolean;
};

type ServerGate = {
  stage: string;
  label?: string;
  status?: string;
  detail?: string;
  nextAction?: string;
};

type ProductionStatusResponse = {
  ok: boolean;
  productionStatus?: {
    truthSource?: string;
    workflowGates?: ServerGate[];
    nextAction?: {
      stage?: string;
      label?: string;
      status?: string;
      message?: string;
      tab?: StudioTab;
      source?: string;
    };
  };
};

const statusCopy: Record<GateStatus, string> = {
  pass: "통과",
  pending: "대기",
  blocked: "차단",
};

const BRIDGE_URL = "http://127.0.0.1:5161";

const stageConfig: Record<string, { tab: StudioTab; focus: GateFocus[]; icon: WorkflowGate["icon"] }> = {
  "material-intake": { tab: "topic", focus: ["all", "topic", "plan"], icon: SearchCheck },
  "source-ledger": { tab: "topic", focus: ["all", "topic", "sources"], icon: DatabaseIcon },
  "topic-discovery": { tab: "topic", focus: ["all", "topic", "plan"], icon: ShieldCheck },
  storyboard: { tab: "plan", focus: ["all", "plan", "sources"], icon: ListChecks },
  "source-acquisition": { tab: "sources", focus: ["all", "sources", "edit"], icon: FolderOpen },
  "prompt-quality": { tab: "plan", focus: ["all", "plan", "sources", "edit"], icon: ClipboardCheck },
  "asset-import-review": { tab: "sources", focus: ["all", "sources", "review"], icon: FolderOpen },
  "edit-assembly": { tab: "edit", focus: ["all", "edit", "review"], icon: SlidersHorizontal },
  "render-preflight": { tab: "edit", focus: ["all", "edit", "review"], icon: FileVideo2 },
  "quality-review": { tab: "review", focus: ["all", "review"], icon: ClipboardCheck },
  "publish-readiness": { tab: "review", focus: ["all", "review"], icon: ShieldCheck },
  "post-publish-learning": { tab: "advanced", focus: ["all", "review"], icon: ClipboardCheck },
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

function textReady(value: unknown) {
  return String(value || "").trim().length >= 8;
}

function gateClass(status: GateStatus) {
  if (status === "pass") return "pass";
  if (status === "blocked") return "fail";
  return "warn";
}

function normalizeGateStatus(status: string | undefined): GateStatus {
  if (status === "pass") return "pass";
  if (status === "pending") return "pending";
  return "blocked";
}

function gateFromServer(gate: ServerGate): WorkflowGate {
  const config = stageConfig[gate.stage] ?? { tab: "home" as StudioTab, focus: ["all"] as GateFocus[], icon: ShieldCheck };
  const status = normalizeGateStatus(gate.status);
  return {
    id: gate.stage,
    label: gate.label || gate.stage,
    status,
    detail: gate.detail || "",
    nextAction: gate.nextAction || gate.detail || "다음 제작 행동을 확인하세요.",
    tab: config.tab,
    focus: config.focus,
    icon: config.icon,
  };
}

function StatusIcon({ status }: { status: GateStatus }) {
  if (status === "pass") return <CheckCircle2 size={14} />;
  if (status === "blocked") return <AlertTriangle size={14} />;
  return <Circle size={14} />;
}

export default function ProductionWorkflowGatePanel({ focus = "all", compact = false }: ProductionWorkflowGatePanelProps) {
  const { prompt, draftResult, renderResult } = useStudioState();
  const actions = useStudioActions();
  const [serverStatus, setServerStatus] = useState<ProductionStatusResponse["productionStatus"] | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [serverCheckedAt, setServerCheckedAt] = useState<string | null>(null);
  const scenes = draftResult?.scenes ?? [];
  const sceneCount = scenes.length;
  const hasPrompt = prompt.trim().length > 0;
  const hasDraft = Boolean(draftResult?.ok && sceneCount > 0);
  const readySources = scenes.filter(sourceReady).length;
  const promptReady = scenes.filter((scene) => textReady(scene.image_prompt)).length;
  const continuityReady = scenes.filter((scene) => textReady(scene.source_rationale) || textReady(scene.continuity_note)).length;
  const hasRender = Boolean(renderResult?.renderResult?.outputPath);
  const hasManifest = Boolean(renderResult?.renderResult?.manifestPath);
  const hasQualityReport = Boolean(renderResult?.renderResult?.qualityReportPath);

  useEffect(() => {
    let alive = true;
    async function loadStatus() {
      try {
        const response = await fetch(`${BRIDGE_URL}/api/production/status`);
        const payload = await response.json() as ProductionStatusResponse;
        if (!response.ok || !payload.ok || !payload.productionStatus) {
          throw new Error("production-status-unavailable");
        }
        if (alive) {
          setServerStatus(payload.productionStatus);
          setServerError(null);
          setServerCheckedAt(new Date().toISOString());
        }
      } catch (err) {
        if (alive) {
          setServerStatus(null);
          setServerError(err instanceof Error ? err.message : "production-status-unavailable");
          setServerCheckedAt(null);
        }
      }
    }
    void loadStatus();
    const timer = window.setInterval(() => void loadStatus(), 15000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [sceneCount, readySources, promptReady, continuityReady, hasRender, hasManifest, hasQualityReport]);

  const localGates: WorkflowGate[] = [
    {
      id: "material-intake",
      label: "소재 입력",
      status: hasPrompt ? "pass" : "blocked",
      detail: hasPrompt ? "소재 메모가 제작 입력으로 준비되어 있습니다." : "소재 메모가 비어 있습니다.",
      nextAction: "소재 탭에서 후보를 찾고 검증한 뒤 기획으로 넘기세요.",
      tab: "topic",
      focus: ["all", "topic", "plan"],
      icon: SearchCheck,
    },
    {
      id: "topic-discovery",
      label: "소재 검증",
      status: hasPrompt ? "pending" : "blocked",
      detail: hasPrompt ? "게이트 탭에서 sourceLedger와 소재 검증 결과를 확인해야 합니다." : "소재 입력이 먼저 필요합니다.",
      nextAction: "소재 탭에서 sourceLedger, 후보 비교, 게이트 결과를 저장하세요.",
      tab: "topic",
      focus: ["all", "topic", "plan"],
      icon: ShieldCheck,
    },
    {
      id: "storyboard",
      label: "스토리보드",
      status: hasDraft ? "pass" : "blocked",
      detail: hasDraft ? `${sceneCount}개 씬 초안이 있습니다.` : "기획 초안이 아직 없습니다.",
      nextAction: "기획 단계에서 초안을 만들고 장면 약속을 확인하세요.",
      tab: "plan",
      focus: ["all", "plan", "sources"],
      icon: ListChecks,
    },
    {
      id: "source-acquisition",
      label: "소스 확보",
      status: !hasDraft ? "blocked" : readySources === sceneCount && sceneCount > 0 ? "pass" : readySources > 0 ? "pending" : "blocked",
      detail: hasDraft ? `${readySources}/${sceneCount}개 씬에 영상/이미지 소스가 있습니다.` : "스토리보드가 먼저 필요합니다.",
      nextAction: "소스 단계에서 장면별 영상/이미지와 출처 근거를 채우세요.",
      tab: "sources",
      focus: ["all", "sources", "edit"],
      icon: FolderOpen,
    },
    {
      id: "prompt-quality",
      label: "프롬프트 품질",
      status: !hasDraft ? "blocked" : promptReady === sceneCount && continuityReady === sceneCount ? "pass" : "pending",
      detail: hasDraft
        ? `프롬프트 ${promptReady}/${sceneCount}, 연속성/선택 근거 ${continuityReady}/${sceneCount}`
        : "장면 프롬프트를 검수할 초안이 없습니다.",
      nextAction: "장면별 물리 동작, 카메라, 금지 요소, continuity/선택 근거를 채우세요.",
      tab: "plan",
      focus: ["all", "plan", "sources", "edit"],
      icon: ClipboardCheck,
    },
    {
      id: "edit-assembly",
      label: "편집 조립",
      status: hasRender ? "pass" : hasDraft && readySources > 0 ? "pending" : "blocked",
      detail: hasRender ? "렌더 후보가 생성되었습니다." : "렌더 후보가 아직 없습니다.",
      nextAction: "편집 단계에서 컷 리듬, 자막, TTS, BGM을 확인하고 MP4 후보를 만드세요.",
      tab: "edit",
      focus: ["all", "edit", "review"],
      icon: SlidersHorizontal,
    },
    {
      id: "render-preflight",
      label: "렌더 전 점검",
      status: hasRender && hasManifest ? "pass" : hasRender ? "pending" : "blocked",
      detail: hasManifest ? "렌더 매니페스트가 연결되었습니다." : "렌더 매니페스트가 아직 없습니다.",
      nextAction: "렌더 manifest, 해상도, 자막 safe zone, 오디오 조건을 확인하세요.",
      tab: "edit",
      focus: ["all", "edit", "review"],
      icon: FileVideo2,
    },
    {
      id: "quality-review",
      label: "품질 검수",
      status: hasQualityReport ? "pass" : hasRender ? "pending" : "blocked",
      detail: hasQualityReport ? "품질 리포트가 연결되었습니다." : "실제 시청/품질 리포트가 아직 없습니다.",
      nextAction: "검수 단계에서 품질 리포트, 실제 시청, 실패 원인을 기록하세요.",
      tab: "review",
      focus: ["all", "review"],
      icon: ClipboardCheck,
    },
    {
      id: "publish-readiness",
      label: "게시 준비",
      status: hasQualityReport ? "pending" : "blocked",
      detail: hasQualityReport ? "게시 전 제목/썸네일/설명/최종 승인 증거가 필요합니다." : "품질 검수 전에는 게시 준비로 넘길 수 없습니다.",
      nextAction: "최종 승인, 업로드 금지 리스크, 제목/썸네일/설명 packet을 채우세요.",
      tab: "review",
      focus: ["all", "review"],
      icon: ShieldCheck,
    },
  ];

  const serverGates = useMemo(
    () => (serverStatus?.workflowGates ?? []).map(gateFromServer),
    [serverStatus],
  );
  const gates = serverGates.length > 0 ? serverGates : localGates;
  const visibleGates = gates.filter((gate) => focus === "all" || gate.focus.includes(focus));
  const passCount = visibleGates.filter((gate) => gate.status === "pass").length;
  const blockedCount = visibleGates.filter((gate) => gate.status === "blocked").length;
  const currentGate = serverStatus?.nextAction
    ? {
        id: serverStatus.nextAction.stage || "production-status",
        label: serverStatus.nextAction.label || "제작 상태",
        status: normalizeGateStatus(serverStatus.nextAction.status),
        detail: serverStatus.nextAction.message || "",
        nextAction: serverStatus.nextAction.message || "다음 제작 행동을 확인하세요.",
        tab: serverStatus.nextAction.tab || "home",
        focus: ["all"] as GateFocus[],
        icon: ShieldCheck,
      }
    : visibleGates.find((gate) => gate.status !== "pass") ?? visibleGates[visibleGates.length - 1];
  const CurrentIcon = currentGate?.icon;
  const sourceLabel = serverGates.length > 0
    ? `서버 production status 기준${serverCheckedAt ? " · refreshed" : ""}`
    : serverError
      ? "브리지 미연결: 화면 상태 fallback"
      : "화면 상태 fallback";

  return (
    <div className="gate-advanced-panel production-workflow-gate-panel">
      <div className="gate-candidate-stack-head">
        <div>
          <strong>{compact ? "제작 게이트" : "대시보드 제작 게이트"}</strong>
          <span>{sourceLabel}</span>
        </div>
        <div className="gate-selected-candidate-plan">
          <span>통과 {passCount}</span>
          <span>차단 {blockedCount}</span>
        </div>
      </div>

      {serverError ? (
        <div className="gate-help-note warn">
          <AlertTriangle size={14} />
          <span>서버 production status 확인 실패: fallback gate는 현재 화면 상태만 반영합니다.</span>
        </div>
      ) : null}

      {currentGate ? (
        <div className={`gate-help-note ${currentGate.status === "blocked" ? "warn" : ""}`}>
          {CurrentIcon ? <CurrentIcon size={14} /> : null}
          <span>{currentGate.label}: {currentGate.status === "pass" ? currentGate.detail : currentGate.nextAction}</span>
        </div>
      ) : null}

      <div className="gate-check-list">
        {visibleGates.map((gate) => {
          const Icon = gate.icon;
          return (
            <div key={gate.id} className={`gate-check-row ${gateClass(gate.status)}`}>
              <StatusIcon status={gate.status} />
              <div className="gate-check-meta">
                <span>{gate.label} · {statusCopy[gate.status]}</span>
                <p>{gate.detail}</p>
              </div>
              <button className="subtle-button" onClick={() => actions.setActiveTab(gate.tab)}>
                <Icon size={13} />
                열기
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
