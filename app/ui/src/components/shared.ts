import type { BudgetMode } from "../../../../shared/contracts/plan";
import type {
    BridgeHealth,
    BridgeMediaAdapterStatus,
    BridgeLocalMediaSummary,
    BridgeLocalMediaRenderSummary,
    BridgeToolStatus,
} from "../lib/bridge";
import type {
    PlannerMeta,
    ProviderAvailability,
    RouteDecision,
    StudioProjectRecord,
} from "../lib/planner";

export type CopyTarget = "route" | "save" | "compose";
export type CopyState = { target: CopyTarget | null; state: "idle" | "copied" | "failed" };
export type BridgeStatus = "checking" | "connected" | "offline" | "error";
export type SaveState = { status: "idle" | "saving" | "saved" | "failed"; message: string };
export type RenderState = { status: "idle" | "rendering" | "rendered" | "failed"; message: string };
export type SceneAssetRole = "visual" | "audio";
export type LocalSceneAsset = {
    role: SceneAssetRole;
    file: File;
    previewUrl: string | null;
};

export const reasonMap: Record<string, string> = {
    "free-mode or premium disabled": "무료 모드이거나 프리미엄 라우팅이 꺼져 있어 로컬로 처리합니다.",
    "scene priority below premium threshold": "우선도가 낮아 비용을 쓰지 않고 로컬 경로로 둡니다.",
    "audio-first premium scene": "오디오 완성도가 중요해서 Veo 3 우선 장면으로 분류했습니다.",
    "human realism requirement justifies premium video route": "인물 자연스러움이 중요해 Sora 2 우선 장면으로 분류했습니다.",
    "local fallback": "기본 로컬 경로로 유지합니다.",
};

export function formatDate(value: string): string {
    return new Intl.DateTimeFormat("ko-KR", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    }).format(new Date(value));
}

export function formatUsd(value: number): string {
    return new Intl.NumberFormat("ko-KR", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
    }).format(value);
}

export function budgetModeLabel(mode: BudgetMode): string {
    if (mode === "free") return "무료";
    if (mode === "premium") return "프리미엄";
    return "표준";
}

export function routeLabel(route: RouteDecision["route"]): string {
    if (route === "sora2") return "Sora 2";
    if (route === "veo3") return "Veo 3";
    return "로컬";
}

export function routeHintCopy(route: RouteDecision["route"]): string {
    if (route === "sora2") return "핵심 장면";
    if (route === "veo3") return "오디오 우선";
    return "기본 경로";
}

export function visualKindLabel(value: string | undefined): string {
    if (value === "image") return "정지 이미지";
    if (value === "video") return "모션 소스";
    return "시각 소스";
}

export function audioKindLabel(value: string | undefined): string {
    if (value === "native") return "원본 오디오";
    if (value === "voiceover") return "보이스오버";
    return "오디오 없음";
}

export function copyLabel(copyState: CopyState, target: CopyTarget): string {
    if (copyState.target !== target) return "복사";
    if (copyState.state === "copied") return "복사됨";
    if (copyState.state === "failed") return "실패";
    return "복사";
}

export function bridgeSummary(status: BridgeStatus, health: BridgeHealth | null): string {
    if (status === "checking") return "브리지 확인 중";
    if (status === "connected" && health) return `${health.port} 포트 연결됨`;
    if (status === "error") return "브리지 오류, 브라우저 임시 플래너로 전환";
    return "브리지 오프라인";
}

export function plannerLabel(planner: PlannerMeta | null | undefined): string {
    if (!planner) return "기획 정보 없음";
    if (planner.backend === "ollama") return planner.model ? `Ollama · ${planner.model}` : "Ollama";
    if (planner.backend === "browser-sample") return "브라우저 임시 플래너";
    return planner.fallbackUsed ? "샘플 플래너 fallback" : "샘플 플래너";
}

export function plannerDetail(planner: PlannerMeta | null | undefined): string {
    if (!planner) return "아직 기획 엔진 정보가 없습니다.";
    return planner.detail;
}

export function plannerRuntimeLabel(health: BridgeHealth | null): string {
    if (!health) return "확인 전";
    if (health.planner.ready) {
        return health.planner.model ? `Ollama ${health.planner.model}` : "Ollama 준비됨";
    }
    return "샘플 플래너 대기";
}

export function plannerRuntimeDetail(health: BridgeHealth | null): string {
    if (!health) return "브리지 상태를 확인하면 기획 엔진 준비 상황이 표시됩니다.";
    return health.planner.detail;
}

export function toolTitle(name: string): string {
    if (name === "hf") return "Hugging Face CLI";
    if (name === "ollama") return "Ollama";
    return "FFmpeg";
}

export function toolState(tool: BridgeToolStatus | null | undefined): string {
    if (!tool) return "확인 전";
    if (tool.ready) {
        if (tool.source === "winget-link") return "설치 및 실행 확인";
        if (tool.source === "local-programs") return "로컬 프로그램 폴더에서 확인";
        if (tool.source === "path") return "PATH에서 확인";
        return "사용 가능";
    }
    return tool.detail ?? "아직 준비되지 않음";
}

export function toolPath(tool: BridgeToolStatus | null | undefined): string {
    return tool?.resolvedPath ?? tool?.path ?? "경로를 찾지 못했습니다.";
}

export function mediaAdapterTitle(adapter: BridgeMediaAdapterStatus): string {
    return adapter.key === "flux" ? "FLUX 어댑터" : "Wan 어댑터";
}

export function mediaAdapterState(adapter: BridgeMediaAdapterStatus | null | undefined): string {
    if (!adapter) return "확인 전";
    if (adapter.mode === "command" && adapter.ready) return "명령 실행 준비";
    if (adapter.mode === "stub") return "플레이스홀더 폴백";
    if (adapter.mode === "off") return "비활성";
    return adapter.detail;
}

export function mediaAdapterDetail(adapter: BridgeMediaAdapterStatus | null | undefined): string {
    if (!adapter) return "브리지 상태를 확인하면 로컬 생성기 준비 상황이 표시됩니다.";
    return `${adapter.model} · ${adapter.entryPoint ?? adapter.detail}`;
}

export function localMediaPlanSummaryLabel(summary: BridgeLocalMediaSummary | null | undefined): string {
    if (!summary) return "로컬 생성 계획 정보 없음";
    const parts = [`생성 대기 ${summary.generationRequired ?? 0}개`];
    if ((summary.uploadedVisuals ?? 0) > 0) {
        parts.push(`업로드 비주얼 ${summary.uploadedVisuals}개`);
    }
    return parts.join(" · ");
}

export function localMediaRenderSummaryLabel(summary: BridgeLocalMediaRenderSummary | null | undefined): string {
    if (!summary) return "로컬 생성 요약 없음";
    const parts = [
        `생성 ${summary.generated}개`,
        `업로드 ${summary.uploaded}개`,
        `폴백 ${summary.placeholder}개`,
    ];
    if (summary.failed > 0) {
        parts.push(`명령 실패 ${summary.failed}개`);
    }
    return parts.join(" · ");
}

export function localizeReason(reason: string | undefined): string {
    if (!reason) return "라우팅 사유 없음";
    return reasonMap[reason] ?? reason;
}

export function assetKey(projectId: string, sceneId: string, role: SceneAssetRole): string {
    return `${projectId}::${sceneId}::${role}`;
}

export function sceneAssetLabel(role: SceneAssetRole): string {
    return role === "visual" ? "장면 이미지/영상" : "장면 음성";
}

export function sceneAssetHint(role: SceneAssetRole): string {
    return role === "visual"
        ? "이미지나 짧은 영상을 넣으면 현재 장면 배경으로 우선 사용합니다."
        : "오디오를 넣으면 현재 장면 보이스오버 대신 그대로 씁니다.";
}

export function sceneAssetAccept(role: SceneAssetRole): string {
    return role === "visual" ? "image/*,video/*" : "audio/*,.wav,.mp3,.m4a,.aac";
}

export function createPreviewUrl(file: File, role: SceneAssetRole): string | null {
    if (role === "visual" && (file.type.startsWith("image/") || file.type.startsWith("video/"))) {
        return URL.createObjectURL(file);
    }
    return null;
}

export function manifestUploadedAsset(
    record: StudioProjectRecord | null,
    sceneId: string,
    role: SceneAssetRole,
    isCleared: boolean,
) {
    if (!record || isCleared) return null;
    const asset = record.manifest.assets.find((item) => item.sceneId === sceneId && item.role === role);
    return asset?.sourceOrigin === "uploaded" ? asset : null;
}

export function providerAvailabilityFromRecord(record: StudioProjectRecord): ProviderAvailability {
    return {
        premiumEnabled: record.routes.some((route) => route.route !== "local"),
        sora2: record.routes.some((route) => route.route === "sora2"),
        veo3: record.routes.some((route) => route.route === "veo3"),
    };
}

export async function fileToBase64(file: File): Promise<string> {
    return new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            const result = typeof reader.result === "string" ? reader.result : "";
            const encoded = result.includes(",") ? result.split(",")[1] : result;
            resolve(encoded);
        };
        reader.onerror = () => reject(reader.error ?? new Error("파일을 읽지 못했습니다."));
        reader.readAsDataURL(file);
    });
}
