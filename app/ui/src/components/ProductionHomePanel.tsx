import { ArrowRight, CheckCircle2, Circle, ClipboardCheck, Film, FolderOpen, SearchCheck, SlidersHorizontal } from "lucide-react";
import { useStudioActions, useStudioState } from "../context/StudioContext";
import ProductionGateStatusPanel from "./ProductionGateStatusPanel";
import HumanOperatorP0Panel from "./HumanOperatorP0Panel";
import ProductionProcessAuditPanel from "./ProductionProcessAuditPanel";
import ProductionWorkflowGatePanel from "./ProductionWorkflowGatePanel";
import AutoStudioPanel from "./AutoStudioPanel";

type StageStatus = "done" | "current" | "blocked" | "idle";

const statusCopy: Record<StageStatus, string> = {
  done: "완료",
  current: "진행",
  blocked: "대기",
  idle: "준비",
};

function readySourceCount(scenes: NonNullable<ReturnType<typeof useStudioState>["draftResult"]>["scenes"] = []) {
  return scenes.filter((scene) => (
    scene._server_asset_path
    || scene._video_url
    || scene._upload_preview
    || scene._image_url
    || scene._selected_pexels_video
    || scene.has_image
  )).length;
}

export default function ProductionHomePanel() {
  const { creating, draftResult, prompt, renderResult, rendering } = useStudioState();
  const actions = useStudioActions();

  const scenes = draftResult?.scenes ?? [];
  const hasDraft = !!draftResult?.ok && scenes.length > 0;
  const sourceCount = readySourceCount(scenes);
  const hasAnySource = sourceCount > 0;
  const hasRender = !!renderResult?.renderResult?.outputPath;

  const hasTopicMemo = prompt.trim().length > 0;

  const nextAction = !hasDraft && !hasTopicMemo
    ? {
      title: "먼저 소재 후보를 찾으세요",
      body: "소재 탭에서 검색 표면을 열고 후보를 모은 뒤, 검증한 소재만 기획으로 넘깁니다.",
      label: "소재 찾기",
      disabled: false,
      onClick: () => actions.setActiveTab("topic"),
    }
    : !hasDraft
    ? {
      title: "검증한 소재로 기획 초안을 만드세요",
      body: "소재 메모에 핵심 질문과 선택 이유가 들어간 상태에서 초안을 만들면 이후 단계가 열립니다.",
      label: creating ? "초안 생성 중" : "기획 초안 만들기",
      disabled: !prompt.trim() || creating,
      onClick: actions.handleCreate,
    }
    : !hasAnySource
      ? {
        title: "소스 통일성을 먼저 확인하세요",
        body: "장면별 소스가 비어 있으면 편집 품질 점수는 올라가지 않습니다.",
        label: "소스 단계로 이동",
        disabled: false,
        onClick: () => actions.setActiveTab("sources"),
      }
      : !hasRender
        ? {
          title: "편집 단계에서 렌더 후보를 만드세요",
          body: "자막, TTS, BGM, 장면 리듬을 확인한 뒤 MP4 후보를 생성합니다.",
          label: "편집 단계로 이동",
          disabled: false,
          onClick: () => actions.setActiveTab("edit"),
        }
        : {
          title: "검수 단계에서 출시 가능 여부를 보세요",
          body: "최종 파일 경로, 품질 리포트, 남은 차단 조건을 한 화면에서 확인합니다.",
          label: "검수 단계로 이동",
          disabled: false,
          onClick: () => actions.setActiveTab("review"),
        };

  const stages = [
    {
      tab: "topic" as const,
      title: "소재",
      detail: hasTopicMemo ? "소재 메모 있음" : "후보 찾기부터",
      meta: "발견 -> 검증",
      status: hasDraft ? "done" as StageStatus : "current" as StageStatus,
      icon: SearchCheck,
    },
    {
      tab: "plan" as const,
      title: "기획",
      detail: hasDraft ? `${scenes.length}개 씬 초안` : "스토리보드 없음",
      meta: hasDraft ? "초안 있음" : "초안 필요",
      status: hasDraft ? "done" as StageStatus : "blocked" as StageStatus,
      icon: Film,
    },
    {
      tab: "sources" as const,
      title: "소스",
      detail: hasDraft ? `${sourceCount}/${scenes.length}개 씬 준비` : "기획 이후 진행",
      meta: "영상/이미지 통일성",
      status: hasAnySource ? "done" as StageStatus : hasDraft ? "current" as StageStatus : "blocked" as StageStatus,
      icon: FolderOpen,
    },
    {
      tab: "edit" as const,
      title: "편집",
      detail: hasRender ? "렌더 후보 있음" : "자막/오디오/리듬",
      meta: rendering ? "렌더 중" : "후보 제작",
      status: hasRender ? "done" as StageStatus : hasAnySource ? "current" as StageStatus : "blocked" as StageStatus,
      icon: SlidersHorizontal,
    },
    {
      tab: "review" as const,
      title: "검수",
      detail: hasRender ? "파일/품질 리포트 확인" : "렌더 이후 진행",
      meta: "출시 판단",
      status: hasRender ? "current" as StageStatus : "blocked" as StageStatus,
      icon: ClipboardCheck,
    },
  ];

  return (
    <section className="production-home">
      <div className="production-home-head">
        <div>
          <span className="workspace-kicker">제작 대시보드</span>
          <h1>다음 행동이 먼저 보이는 작업 흐름</h1>
          <p>소재 찾기, 기획, 소스, 편집, 검수 순서로 현재 상태를 정리합니다.</p>
        </div>
        <button className="workspace-primary-action" disabled={nextAction.disabled} onClick={nextAction.onClick}>
          {nextAction.label}
          <ArrowRight size={15} />
        </button>
      </div>

      <div className="next-action-panel">
        <span>다음 행동</span>
        <strong>{nextAction.title}</strong>
        <p>{nextAction.body}</p>
      </div>

      <AutoStudioPanel />

      <HumanOperatorP0Panel />

      <ProductionGateStatusPanel
        onOpenTopic={() => actions.setActiveTab("topic")}
        onOpenPlan={() => actions.setActiveTab("plan")}
      />

      <ProductionWorkflowGatePanel focus="all" compact />

      <ProductionProcessAuditPanel />

      <div className="production-stage-grid">
        {stages.map(({ tab, title, detail, meta, status, icon: Icon }) => (
          <button key={tab} className={`production-stage-card ${status}`} onClick={() => actions.setActiveTab(tab)}>
            <div className="production-stage-head">
              <Icon size={18} />
              <span>{statusCopy[status]}</span>
            </div>
            <strong>{title}</strong>
            <p>{detail}</p>
            <small>{meta}</small>
            {status === "done" ? <CheckCircle2 size={16} className="stage-check" /> : <Circle size={16} className="stage-check" />}
          </button>
        ))}
      </div>
    </section>
  );
}
