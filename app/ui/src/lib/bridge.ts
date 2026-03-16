import type { BudgetMode, ProjectPlan } from "../../../../shared/contracts/plan";
import type { RenderManifest } from "../../../../shared/contracts/render";
import type { RouteDecision } from "./planner";

const BRIDGE_URL = "http://127.0.0.1:5161";

export interface BridgeHealth {
    ok: boolean;
    service: string;
    port: number;
    projectRoot: string;
    pythonPath: string;
    tools: {
        ffmpeg: BridgeToolStatus;
        hf: BridgeToolStatus;
        ollama: BridgeToolStatus;
    };
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

export interface BridgeRoutePlanResult {
    plan: ProjectPlan;
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
    };
    plan: ProjectPlan;
    routes: RouteDecision[];
    manifest: RenderManifest;
}

export interface BridgeRenderProjectResult {
    ok: true;
    saveResult: BridgeSaveProjectResult["saveResult"];
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
