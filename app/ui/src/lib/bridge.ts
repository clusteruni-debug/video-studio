import type { BudgetMode, ProjectPlan } from "../../../../shared/contracts/plan";
import type { RenderManifest } from "../../../../shared/contracts/render";
import type { PlannerMeta, RouteDecision } from "./planner";

const BRIDGE_URL = "http://127.0.0.1:5161";

export interface SceneAssetUploadPayload {
    sceneId: string;
    role: "visual" | "audio";
    fileName: string;
    mimeType: string;
    base64: string;
}

export interface BridgeHealth {
    ok: boolean;
    service: string;
    port: number;
    projectRoot: string;
    pythonPath: string;
    planner: BridgePlannerStatus;
    tools: {
        ffmpeg: BridgeToolStatus;
        hf: BridgeToolStatus;
        ollama: BridgeToolStatus;
    };
    media: Record<string, BridgeMediaAdapterStatus>;
}

export interface BridgePlannerStatus {
    ready: boolean;
    backend: string;
    model: string | null;
    availableModels: string[];
    host: string;
    detail: string;
}

export interface BridgeToolStatus {
    name: string;
    ready: boolean;
    path: string | null;
    resolvedPath: string | null;
    source: string | null;
    version: string | null;
    detail: string | null;
}

export interface BridgeMediaAdapterStatus {
    key: string;
    label: string;
    mode: "off" | "stub" | "command" | string;
    outputKind: "image" | "video" | string;
    model: string;
    ready: boolean;
    fallbackAvailable: boolean;
    entryPoint: string | null;
    commandPreview: string | null;
    detail: string;
}

export interface BridgeLocalMediaSummary {
    totalScenes: number;
    uploadedVisuals?: number;
    generationRequired?: number;
    imageGenerations?: number;
    videoGenerations?: number;
    uploadedAudio?: number;
    autoAudioFallbacks?: number;
}

export interface BridgeLocalMediaRenderSummary {
    totalScenes: number;
    uploaded: number;
    generated: number;
    placeholder: number;
    attempted: number;
    succeeded: number;
    failed: number;
}

export interface BridgeLocalMediaSceneResult {
    sceneId: string;
    sceneTitle: string;
    adapterKey: string | null;
    mode: string;
    outputKind: string;
    status: string;
    outputPath: string;
    detail: string;
    attempted: boolean;
    succeeded: boolean | null;
    commandPreview?: string | null;
    requestPath?: string | null;
    logPath?: string | null;
}

export interface BridgeRoutePlanResult {
    plan: ProjectPlan;
    planner: PlannerMeta;
    routes: RouteDecision[];
    estimatedTotalCostUsd: number;
}

export interface BridgeSaveProjectResult {
    ok: true;
    saveResult: {
        projectId: string;
        inputDir: string;
        cacheDir: string;
        renderDir: string;
        planPath: string;
        routesPath: string;
        manifestPath: string;
        notesPath: string;
        estimatedTotalCostUsd: number;
        uploadedAssets?: Array<{
            sceneId: string;
            role: "visual" | "audio";
            fileName: string;
            storedPath: string;
            mimeType?: string | null;
        }>;
        localMediaPlanPath?: string;
        localMediaSummary?: BridgeLocalMediaSummary;
    };
    planner: PlannerMeta;
    plan: ProjectPlan;
    routes: RouteDecision[];
    manifest: RenderManifest;
}

export interface BridgeRenderProjectResult {
    ok: true;
    saveResult: BridgeSaveProjectResult["saveResult"];
    planner: PlannerMeta;
    plan: ProjectPlan;
    routes: RouteDecision[];
    manifest: RenderManifest;
    renderResult: {
        ok: boolean;
        projectId: string;
        manifestPath: string;
        outputPath: string;
        concatFilePath: string;
        subtitleFilePath: string;
        logPath: string;
        ffmpeg: BridgeToolStatus;
        sceneClipPaths: string[];
        localMediaPlanPath: string;
        localMediaReportPath: string;
        localMediaSummary: BridgeLocalMediaRenderSummary;
        localMedia: BridgeLocalMediaSceneResult[];
    };
}

export class BridgeRequestError extends Error {
    constructor(message: string) {
        super(message);
        this.name = "BridgeRequestError";
    }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${BRIDGE_URL}${path}`, {
        ...init,
        headers: {
            "Content-Type": "application/json",
            ...(init?.headers ?? {}),
        },
    });

    if (!response.ok) {
        const text = await response.text();
        throw new BridgeRequestError(text || `Bridge request failed with ${response.status}`);
    }

    return (await response.json()) as T;
}

export async function fetchBridgeHealth(): Promise<BridgeHealth> {
    return request<BridgeHealth>("/api/health");
}

export async function routePlanWithBridge(input: {
    prompt: string;
    budgetMode: BudgetMode;
    availability: {
        premiumEnabled: boolean;
        sora2: boolean;
        veo3: boolean;
    };
}): Promise<BridgeRoutePlanResult> {
    return request<BridgeRoutePlanResult>("/api/route-plan", {
        method: "POST",
        body: JSON.stringify(input),
    });
}

export async function saveProjectWithBridge(input: {
    prompt: string;
    budgetMode: BudgetMode;
    projectId: string;
    sceneAssets?: SceneAssetUploadPayload[];
    availability: {
        premiumEnabled: boolean;
        sora2: boolean;
        veo3: boolean;
    };
}): Promise<BridgeSaveProjectResult> {
    return request<BridgeSaveProjectResult>("/api/save-project", {
        method: "POST",
        body: JSON.stringify(input),
    });
}

export async function renderSmokeWithBridge(input: {
    prompt: string;
    budgetMode: BudgetMode;
    projectId: string;
    sceneAssets?: SceneAssetUploadPayload[];
    availability: {
        premiumEnabled: boolean;
        sora2: boolean;
        veo3: boolean;
    };
}): Promise<BridgeRenderProjectResult> {
    return request<BridgeRenderProjectResult>("/api/render-smoke", {
        method: "POST",
        body: JSON.stringify(input),
    });
}
