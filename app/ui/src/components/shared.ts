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

export type { QueueItem } from "../lib/image-queue";

export type CopyTarget = "route" | "save" | "compose";
export type CopyState = { target: CopyTarget | null; state: "idle" | "copied" | "failed" };
export type BridgeStatus = "checking" | "connected" | "offline" | "error";
export type SaveState = { status: "idle" | "saving" | "saved" | "failed"; message: string };
export type RenderState = { status: "idle" | "rendering" | "rendered" | "failed"; message: string };
export type SceneAssetRole = "visual" | "audio" | "sfx";
export type LocalSceneAsset = {
    role: SceneAssetRole;
    file: File;
    previewUrl: string | null;
};

export type CreationMode = "image" | "video";
export type ImageStatus = { status: "idle" | "success" | "error"; message: string };

export type ImageEngine = { key: string; label: string; description: string };

export const IMAGE_ENGINES: ImageEngine[] = [
    { key: "sana", label: "Sana", description: "Pollinations 기본 — 고품질 범용" },
    { key: "zimage", label: "ZImage", description: "디테일 강화 모델" },
];

export type GeneratedImage = {
    id: string;
    prompt: string;
    url: string;
    file: File;
    width: number;
    height: number;
    engine: string;
    createdAt: string;
};

export type ImageSize = { label: string; width: number; height: number };

export const IMAGE_SIZES: ImageSize[] = [
    { label: "128×128 (스프라이트)", width: 128, height: 128 },
    { label: "256×256 (보스)", width: 256, height: 256 },
    { label: "512×512 (정사각)", width: 512, height: 512 },
    { label: "1024×1024 (HD)", width: 1024, height: 1024 },
    { label: "16:9 가로 (1920×1080)", width: 1920, height: 1080 },
    { label: "9:16 세로 (1080×1920)", width: 1080, height: 1920 },
];

export type ImageInputMode = "single" | "batch";

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

const adapterTitles: Record<string, string> = {
    pollinations: "Pollinations FLUX",
    flux: "FLUX 로컬",
    dalle3: "DALL-E 3",
    imagen3: "Imagen 3",
    wan: "Wan 로컬",
    sora2: "Sora 2",
    veo3: "Veo 3",
    runway: "Runway Gen-3",
    "edge-tts": "Edge TTS",
    "windows-tts": "Windows TTS",
    elevenlabs: "ElevenLabs",
    "openai-tts": "OpenAI TTS",
    "local-bgm": "로컬 BGM",
    suno: "Suno BGM",
    "local-sfx": "로컬 SFX",
    freesound: "Freesound",
};

export function mediaAdapterTitle(adapter: BridgeMediaAdapterStatus): string {
    return adapterTitles[adapter.key] ?? `${adapter.key} 어댑터`;
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
    if (role === "visual") return "장면 이미지/영상";
    if (role === "sfx") return "장면 효과음";
    return "장면 음성";
}

export function sceneAssetHint(role: SceneAssetRole): string {
    if (role === "visual") return "이미지나 짧은 영상을 넣으면 현재 장면 배경으로 우선 사용합니다.";
    if (role === "sfx") return "효과음 파일을 넣으면 장면 오디오에 믹싱됩니다.";
    return "오디오를 넣으면 현재 장면 보이스오버 대신 그대로 씁니다.";
}

export function sceneAssetAccept(role: SceneAssetRole): string {
    if (role === "visual") return "image/*,video/*";
    return "audio/*,.wav,.mp3,.m4a,.aac";
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

export type VisualProviderOption = { key: string; label: string };

const imageProviderOptions: VisualProviderOption[] = [
    { key: "pollinations", label: "Pollinations FLUX" },
    { key: "flux", label: "FLUX 로컬" },
    { key: "dalle3", label: "DALL-E 3" },
    { key: "imagen3", label: "Imagen 3" },
];

const videoProviderOptions: VisualProviderOption[] = [
    { key: "wan", label: "Wan 로컬" },
    { key: "sora2", label: "Sora 2" },
    { key: "veo3", label: "Veo 3" },
    { key: "runway", label: "Runway Gen-3" },
];

export function visualProviderOptions(visualKind: string | undefined): VisualProviderOption[] {
    return visualKind === "video" ? videoProviderOptions : imageProviderOptions;
}

export function providerLabel(key: string): string {
    return adapterTitles[key] ?? key;
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
