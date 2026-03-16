import type { BudgetMode, ProjectPlan, RouteHint, SceneSpec } from "../../../../shared/contracts/plan";
import { buildRenderManifest, type RenderManifest } from "../../../../shared/contracts/render";

export interface ProviderAvailability {
    premiumEnabled: boolean;
    sora2: boolean;
    veo3: boolean;
}

export interface RouteDecision {
    sceneId: string;
    route: RouteHint;
    estimatedCostUsd: number;
    reason: string;
}

export interface StudioProjectRecord {
    id: string;
    createdAt: string;
    updatedAt: string;
    plan: ProjectPlan;
    routes: RouteDecision[];
    estimatedCostUsd: number;
    manifest: RenderManifest;
}

function createStudioProjectRecord(input: {
    id: string;
    createdAt?: string;
    updatedAt?: string;
    plan: ProjectPlan;
    routes: RouteDecision[];
    estimatedCostUsd?: number;
}): StudioProjectRecord {
    const estimatedCostUsd = Number(
        (input.estimatedCostUsd ?? summarizeCost(input.routes)).toFixed(2),
    );
    const createdAt = input.createdAt ?? new Date().toISOString();
    const updatedAt = input.updatedAt ?? createdAt;

    return rehydrateStudioProjectRecord({
        id: input.id,
        createdAt,
        updatedAt,
        plan: input.plan,
        routes: input.routes,
        estimatedCostUsd,
    });
}

export function rehydrateStudioProjectRecord(record: Omit<StudioProjectRecord, "manifest"> & {
    manifest?: RenderManifest;
}): StudioProjectRecord {
    const estimatedCostUsd = Number(
        (record.estimatedCostUsd ?? summarizeCost(record.routes)).toFixed(2),
    );

    return {
        ...record,
        estimatedCostUsd,
        manifest:
            record.manifest ??
            buildRenderManifest({
                projectId: record.id,
                plan: record.plan,
                routes: record.routes,
                estimatedCostUsd,
            }),
    };
}

const SORA2_RATE_PER_SEC = 0.1;
const VEO3_FAST_RATE_PER_SEC = 0.15;

function clampScore(value: number): 1 | 2 | 3 | 4 | 5 {
    if (value <= 1) {
        return 1;
    }

    if (value >= 5) {
        return 5;
    }

    return Math.round(value) as 1 | 2 | 3 | 4 | 5;
}

function buildScene(
    id: string,
    title: string,
    prompt: string,
    durationSec: number,
    priority: number,
    humanRealism: number,
    nativeAudioNeed: number,
    canUseStillImage: boolean,
    subtitleText: string,
    routeHint: RouteHint = "local",
): SceneSpec {
    return {
        id,
        title,
        prompt,
        durationSec: Number(durationSec.toFixed(2)),
        priority: clampScore(priority),
        humanRealism: clampScore(humanRealism),
        nativeAudioNeed: clampScore(nativeAudioNeed),
        canUseStillImage,
        subtitleText,
        routeHint,
    };
}

function defaultMonthlyCap(budgetMode: BudgetMode, monthlyCapUsd?: number): number {
    if (typeof monthlyCapUsd === "number" && Number.isFinite(monthlyCapUsd)) {
        return Math.max(0, Number(monthlyCapUsd.toFixed(2)));
    }

    if (budgetMode === "premium") {
        return 100;
    }

    if (budgetMode === "standard") {
        return 30;
    }

    return 0;
}

export function createProjectPlan(input: {
    prompt: string;
    budgetMode: BudgetMode;
    monthlyCapUsd?: number;
}): ProjectPlan {
    const normalizedPrompt = input.prompt.trim();
    const lowered = normalizedPrompt.toLowerCase();

    let title = "Brand Promo Reel";
    let scenes: SceneSpec[] = [
        buildScene(
            "scene-01",
            "Opening Statement",
            "Premium opening composition that introduces the brand mood in one striking social-video shot",
            4,
            5,
            4,
            2,
            false,
            "A sharper story starts here.",
            input.budgetMode === "premium" ? "sora2" : "local",
        ),
        buildScene(
            "scene-02",
            "Value Snapshot",
            "Visual summary of the main value proposition with bold typography and clean transitions",
            5,
            3,
            2,
            1,
            true,
            "Designed to look better and land faster.",
        ),
        buildScene(
            "scene-03",
            "Proof Or Mood",
            "Text-driven short-form ad scene with stylish motion and tasteful background visuals",
            5,
            3,
            2,
            1,
            false,
            "Short-form content that feels intentional.",
        ),
        buildScene(
            "scene-04",
            "Final CTA",
            "Closing action card with logo, URL, and direct invitation to act",
            4,
            4,
            1,
            1,
            true,
            "Try it now and launch your next reel faster.",
        ),
    ];

    if (lowered.includes("cafe") || lowered.includes("coffee") || lowered.includes("bakery")) {
        title = "Warm Cafe Reel";
        scenes = [
            buildScene(
                "scene-01",
                "Warm Hook",
                "Steam rising from a fresh latte in a soft morning light, premium social-video opening",
                4,
                5,
                4,
                2,
                false,
                "Start your day with a calmer rhythm.",
                input.budgetMode !== "free" ? "sora2" : "local",
            ),
            buildScene(
                "scene-02",
                "Signature Menu",
                "Handcrafted pastries and coffee lineup on a textured wood table, editorial food styling",
                5,
                3,
                2,
                1,
                true,
                "Fresh pastry, slow coffee, no rush.",
            ),
            buildScene(
                "scene-03",
                "Community Mood",
                "Neighborhood customers chatting softly in a cozy cafe interior, natural background movement",
                6,
                4,
                3,
                2,
                false,
                "Stay for the mood, not just the caffeine.",
            ),
            buildScene(
                "scene-04",
                "Call To Action",
                "Cafe storefront at golden hour, warm ambient motion and inviting signage",
                4,
                4,
                2,
                1,
                true,
                "Visit today and make it your new routine.",
            ),
        ];
    } else if (
        lowered.includes("app") ||
        lowered.includes("software") ||
        lowered.includes("productivity")
    ) {
        title = "Productivity App Reel";
        scenes = [
            buildScene(
                "scene-01",
                "Problem Hook",
                "Busy phone notifications and cluttered tasks collapsing into a clean interface transition",
                3.5,
                4,
                2,
                1,
                false,
                "Too many tasks, not enough focus?",
            ),
            buildScene(
                "scene-02",
                "Core Product",
                "Minimal mobile app dashboard with one-tap task capture and clean charts",
                5,
                3,
                1,
                1,
                true,
                "Capture, sort, and finish work faster.",
            ),
            buildScene(
                "scene-03",
                "Benefit Montage",
                "Fast-paced interface walkthrough with simple motion graphics and progress feedback",
                6,
                4,
                1,
                1,
                false,
                "Plan once. Focus longer. Ship more.",
            ),
            buildScene(
                "scene-04",
                "Install CTA",
                "Clean logo lockup and app-store style end card, polished social ad look",
                3.5,
                4,
                1,
                1,
                true,
                "Download now and reclaim your day.",
            ),
        ];
    }

    return {
        version: 1,
        title,
        sourcePrompt: normalizedPrompt,
        aspectRatio: "9:16",
        budgetMode: input.budgetMode,
        monthlyCapUsd: defaultMonthlyCap(input.budgetMode, input.monthlyCapUsd),
        scenes,
    };
}

export function chooseRoute(
    scene: SceneSpec,
    budgetMode: BudgetMode,
    availability: ProviderAvailability,
): RouteDecision {
    if (budgetMode === "free" || !availability.premiumEnabled) {
        return {
            sceneId: scene.id,
            route: "local",
            estimatedCostUsd: 0,
            reason: "free-mode or premium disabled",
        };
    }

    if (scene.priority <= 3) {
        return {
            sceneId: scene.id,
            route: "local",
            estimatedCostUsd: 0,
            reason: "scene priority below premium threshold",
        };
    }

    if (scene.nativeAudioNeed >= 5 && availability.veo3) {
        return {
            sceneId: scene.id,
            route: "veo3",
            estimatedCostUsd: Number((scene.durationSec * VEO3_FAST_RATE_PER_SEC).toFixed(2)),
            reason: "audio-first premium scene",
        };
    }

    if (scene.humanRealism >= 4 && availability.sora2) {
        return {
            sceneId: scene.id,
            route: "sora2",
            estimatedCostUsd: Number((scene.durationSec * SORA2_RATE_PER_SEC).toFixed(2)),
            reason: "human realism requirement justifies premium video route",
        };
    }

    return {
        sceneId: scene.id,
        route: "local",
        estimatedCostUsd: 0,
        reason: "local fallback",
    };
}

export function routeProjectPlan(
    plan: ProjectPlan,
    availability: ProviderAvailability,
): RouteDecision[] {
    return plan.scenes.map((scene) => chooseRoute(scene, plan.budgetMode, availability));
}

export function summarizeCost(routes: RouteDecision[]): number {
    return Number(routes.reduce((sum, item) => sum + item.estimatedCostUsd, 0).toFixed(2));
}

export function buildStudioProjectRecord(input: {
    prompt: string;
    budgetMode: BudgetMode;
    monthlyCapUsd?: number;
    availability: ProviderAvailability;
}): StudioProjectRecord {
    const plan = createProjectPlan({
        prompt: input.prompt,
        budgetMode: input.budgetMode,
        monthlyCapUsd: input.monthlyCapUsd,
    });
    const routes = routeProjectPlan(plan, input.availability);
    const id = `project-${Date.now()}`;

    return createStudioProjectRecord({
        id,
        plan,
        routes,
    });
}

export function buildStudioProjectRecordFromWorker(input: {
    projectId?: string;
    plan: ProjectPlan;
    routes: RouteDecision[];
    estimatedCostUsd?: number;
}): StudioProjectRecord {
    return createStudioProjectRecord({
        id: input.projectId ?? `project-${Date.now()}`,
        plan: input.plan,
        routes: input.routes,
        estimatedCostUsd: input.estimatedCostUsd,
    });
}

export function buildWorkerCommand(record: StudioProjectRecord): string {
    const routeFlags = [
        record.routes.some((item) => item.route === "sora2") ? "--sora2" : "",
        record.routes.some((item) => item.route === "veo3") ? "--veo3" : "",
    ]
        .filter(Boolean)
        .join(" ");

    return `python -m worker.planner.route_plan --prompt "${record.plan.sourcePrompt.replaceAll('"', '\\"')}" --budget-mode ${record.plan.budgetMode}${routeFlags ? ` ${routeFlags}` : ""}`;
}

export function buildSavePlanCommand(record: StudioProjectRecord): string {
    const routeFlags = [
        record.routes.some((item) => item.route === "sora2") ? "--sora2" : "",
        record.routes.some((item) => item.route === "veo3") ? "--veo3" : "",
    ]
        .filter(Boolean)
        .join(" ");

    return `python -m worker.planner.save_plan --prompt "${record.plan.sourcePrompt.replaceAll('"', '\\"')}" --budget-mode ${record.plan.budgetMode}${routeFlags ? ` ${routeFlags}` : ""}`;
}

export function buildComposeCommand(record: StudioProjectRecord): string {
    return `ffmpeg -y -f concat -safe 0 -i "${record.manifest.concatFilePath}" -vf "subtitles=${record.manifest.subtitleFilePath},scale=1080:1920" -c:v libx264 -c:a aac "${record.manifest.outputPath}"`;
}
