export type BudgetMode = "free" | "standard" | "premium";
export type RouteHint = "local" | "sora2" | "veo3";
export type AspectRatio = "9:16";

export interface SceneSpec {
    id: string;
    title: string;
    prompt: string;
    durationSec: number;
    priority: 1 | 2 | 3 | 4 | 5;
    humanRealism: 1 | 2 | 3 | 4 | 5;
    nativeAudioNeed: 1 | 2 | 3 | 4 | 5;
    canUseStillImage: boolean;
    subtitleText: string;
    routeHint: RouteHint;
}

export interface ProjectPlan {
    version: 1;
    title: string;
    sourcePrompt: string;
    aspectRatio: AspectRatio;
    budgetMode: BudgetMode;
    monthlyCapUsd: number;
    scenes: SceneSpec[];
}

const ROUTE_HINTS: RouteHint[] = ["local", "sora2", "veo3"];
const BUDGET_MODES: BudgetMode[] = ["free", "standard", "premium"];

function clampScore(value: number): 1 | 2 | 3 | 4 | 5 {
    if (value <= 1) {
        return 1;
    }

    if (value >= 5) {
        return 5;
    }

    return Math.round(value) as 1 | 2 | 3 | 4 | 5;
}

export function normalizeBudgetMode(value: string): BudgetMode {
    return BUDGET_MODES.includes(value as BudgetMode) ? (value as BudgetMode) : "free";
}

export function normalizeRouteHint(value: string): RouteHint {
    return ROUTE_HINTS.includes(value as RouteHint) ? (value as RouteHint) : "local";
}

export function normalizeScene(scene: SceneSpec): SceneSpec {
    return {
        ...scene,
        durationSec: Number(scene.durationSec.toFixed(2)),
        priority: clampScore(scene.priority),
        humanRealism: clampScore(scene.humanRealism),
        nativeAudioNeed: clampScore(scene.nativeAudioNeed),
        routeHint: normalizeRouteHint(scene.routeHint),
    };
}

export function normalizeProjectPlan(plan: ProjectPlan): ProjectPlan {
    return {
        ...plan,
        budgetMode: normalizeBudgetMode(plan.budgetMode),
        monthlyCapUsd: Math.max(0, Number(plan.monthlyCapUsd.toFixed(2))),
        scenes: plan.scenes.map(normalizeScene),
    };
}
