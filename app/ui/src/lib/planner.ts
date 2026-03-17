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

export interface PlannerMeta {
    backend: string;
    model: string | null;
    fallbackUsed: boolean;
    detail: string;
}

export interface StudioProjectRecord {
    id: string;
    createdAt: string;
    updatedAt: string;
    planner?: PlannerMeta;
    plan: ProjectPlan;
    routes: RouteDecision[];
    estimatedCostUsd: number;
    manifest: RenderManifest;
}

function createStudioProjectRecord(input: {
    id: string;
    createdAt?: string;
    updatedAt?: string;
    planner?: PlannerMeta;
    plan: ProjectPlan;
    routes: RouteDecision[];
    estimatedCostUsd?: number;
    manifest?: RenderManifest;
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
        planner: input.planner,
        plan: input.plan,
        routes: input.routes,
        estimatedCostUsd,
        manifest: input.manifest,
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

function escapeShell(s: string): string {
    return s.replace(/[\\"$`!]/g, "\\$&");
}

const SORA2_RATE_PER_SEC = 0.1;
const VEO3_FAST_RATE_PER_SEC = 0.15;

function clampScore(value: number): 1 | 2 | 3 | 4 | 5 {
    if (!Number.isFinite(value) || value <= 1) {
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
    const isCafePrompt =
        lowered.includes("cafe") ||
        lowered.includes("coffee") ||
        lowered.includes("bakery") ||
        normalizedPrompt.includes("카페") ||
        normalizedPrompt.includes("커피") ||
        normalizedPrompt.includes("베이커리");
    const isProductivityPrompt =
        lowered.includes("app") ||
        lowered.includes("software") ||
        lowered.includes("productivity") ||
        normalizedPrompt.includes("앱") ||
        normalizedPrompt.includes("생산성") ||
        normalizedPrompt.includes("소프트웨어");
    const isBeautyPrompt =
        lowered.includes("beauty") ||
        lowered.includes("cosmetic") ||
        lowered.includes("skincare") ||
        normalizedPrompt.includes("화장품") ||
        normalizedPrompt.includes("뷰티") ||
        normalizedPrompt.includes("코스메틱") ||
        normalizedPrompt.includes("스킨케어");

    let title = "브랜드 프로모 릴스";
    let scenes: SceneSpec[] = [
        buildScene(
            "scene-01",
            "오프닝 선언",
            "브랜드 분위기를 강하게 여는 메인 오프닝 장면",
            4,
            5,
            4,
            2,
            false,
            "이 영상의 첫인상은 여기서 결정됩니다.",
            input.budgetMode === "premium" ? "sora2" : "local",
        ),
        buildScene(
            "scene-02",
            "핵심 가치 요약",
            "메인 가치 제안을 또렷한 타이포와 전환으로 정리하는 장면",
            5,
            3,
            2,
            1,
            true,
            "더 보기 좋고 더 빠르게 이해되도록 구성합니다.",
        ),
        buildScene(
            "scene-03",
            "분위기 혹은 근거",
            "짧은 광고 톤의 문장과 배경 비주얼로 설득력을 더하는 장면",
            5,
            3,
            2,
            1,
            false,
            "의도 있는 짧은 영상처럼 보이게 만듭니다.",
        ),
        buildScene(
            "scene-04",
            "마지막 행동 유도",
            "로고, 주소, 행동 유도를 담은 엔딩 카드",
            4,
            4,
            1,
            1,
            true,
            "지금 바로 시도하고 다음 릴스를 더 빨리 만드세요.",
        ),
    ];

    if (isCafePrompt) {
        title = "따뜻한 카페 릴스";
        scenes = [
            buildScene(
                "scene-01",
                "따뜻한 첫 장면",
                "부드러운 아침빛 속 라테 김이 오르는 고급 오프닝 컷",
                4,
                5,
                4,
                2,
                false,
                "조금 더 느리고 부드러운 아침을 시작해 보세요.",
                input.budgetMode !== "free" ? "sora2" : "local",
            ),
            buildScene(
                "scene-02",
                "시그니처 메뉴",
                "질감 있는 테이블 위에 페이스트리와 커피를 정갈하게 배치한 장면",
                5,
                3,
                2,
                1,
                true,
                "갓 구운 페이스트리와 천천히 내린 커피, 서두를 필요 없는 시간.",
            ),
            buildScene(
                "scene-03",
                "머무는 분위기",
                "동네 손님들이 편안하게 머무는 카페 내부와 자연스러운 움직임",
                6,
                4,
                3,
                2,
                false,
                "카페인은 이유일 뿐, 결국 남는 건 분위기입니다.",
            ),
            buildScene(
                "scene-04",
                "방문 유도",
                "노을빛이 스치는 매장 전면과 초대하듯 보이는 사인",
                4,
                4,
                2,
                1,
                true,
                "오늘 들러서 새로운 일상으로 만들어 보세요.",
            ),
        ];
    } else if (isProductivityPrompt) {
        title = "생산성 앱 릴스";
        scenes = [
            buildScene(
                "scene-01",
                "문제 제기",
                "복잡한 알림과 쌓인 업무가 정돈된 인터페이스로 전환되는 장면",
                3.5,
                4,
                2,
                1,
                false,
                "할 일은 너무 많고 집중은 자꾸 끊기지 않나요?",
            ),
            buildScene(
                "scene-02",
                "핵심 기능",
                "한 번의 탭으로 업무를 정리하는 미니멀한 모바일 대시보드",
                5,
                3,
                1,
                1,
                true,
                "빠르게 기록하고, 정리하고, 끝내는 흐름을 보여줍니다.",
            ),
            buildScene(
                "scene-03",
                "효과 강조",
                "짧고 빠른 인터페이스 흐름과 진행 피드백을 묶은 장면",
                6,
                4,
                1,
                1,
                false,
                "한 번 정리하고 더 오래 집중하고 더 많이 끝내세요.",
            ),
            buildScene(
                "scene-04",
                "설치 유도",
                "앱스토어 스타일의 정돈된 엔딩 카드와 로고 마감",
                3.5,
                4,
                1,
                1,
                true,
                "지금 설치하고 하루의 흐름을 다시 가져오세요.",
            ),
        ];
    } else if (isBeautyPrompt) {
        title = "뷰티 제품 티저";
        scenes = [
            buildScene(
                "scene-01",
                "첫 질감 클로즈업",
                "유리 용기와 크림 텍스처를 고급스럽게 잡아내는 첫 장면",
                4,
                5,
                4,
                1,
                false,
                "손끝에 닿기 전부터 질감이 다르게 느껴지는 제품입니다.",
                input.budgetMode !== "free" ? "sora2" : "local",
            ),
            buildScene(
                "scene-02",
                "핵심 성분 소개",
                "깨끗한 배경 위에 핵심 성분과 패키지를 함께 정리하는 장면",
                5,
                3,
                2,
                1,
                true,
                "복잡한 설명 대신 핵심 성분과 사용감을 짧게 전달합니다.",
            ),
            buildScene(
                "scene-03",
                "사용 분위기",
                "아침 루틴 속에서 자연스럽게 제품을 사용하는 무드 컷",
                5.5,
                4,
                3,
                2,
                false,
                "하루의 분위기를 정리하는 루틴처럼 보이게 구성합니다.",
            ),
            buildScene(
                "scene-04",
                "구매 유도 엔딩",
                "로고와 제품명, 한 줄 카피로 마무리하는 엔딩 카드",
                4,
                4,
                1,
                1,
                true,
                "지금 보고 바로 기억나는 제품 티저로 마감합니다.",
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
        planner: {
            backend: "browser-sample",
            model: null,
            fallbackUsed: false,
            detail: "브라우저 내장 초안 플래너를 사용했습니다.",
        },
        plan,
        routes,
    });
}

export function buildStudioProjectRecordFromWorker(input: {
    projectId?: string;
    planner?: PlannerMeta;
    plan: ProjectPlan;
    routes: RouteDecision[];
    estimatedCostUsd?: number;
    manifest?: RenderManifest;
}): StudioProjectRecord {
    return createStudioProjectRecord({
        id: input.projectId ?? `project-${Date.now()}`,
        planner: input.planner,
        plan: input.plan,
        routes: input.routes,
        estimatedCostUsd: input.estimatedCostUsd,
        manifest: input.manifest,
    });
}

export function buildWorkerCommand(record: StudioProjectRecord): string {
    const routeFlags = [
        record.routes.some((item) => item.route === "sora2") ? "--sora2" : "",
        record.routes.some((item) => item.route === "veo3") ? "--veo3" : "",
    ]
        .filter(Boolean)
        .join(" ");

    return `python -m worker.planner.route_plan --prompt "${escapeShell(record.plan.sourcePrompt)}" --budget-mode ${record.plan.budgetMode}${routeFlags ? ` ${routeFlags}` : ""}`;
}

export function buildSavePlanCommand(record: StudioProjectRecord): string {
    const routeFlags = [
        record.routes.some((item) => item.route === "sora2") ? "--sora2" : "",
        record.routes.some((item) => item.route === "veo3") ? "--veo3" : "",
    ]
        .filter(Boolean)
        .join(" ");

    return `python -m worker.planner.save_plan --prompt "${escapeShell(record.plan.sourcePrompt)}" --budget-mode ${record.plan.budgetMode}${routeFlags ? ` ${routeFlags}` : ""}`;
}

export function buildComposeCommand(record: StudioProjectRecord): string {
    return `ffmpeg -y -f concat -safe 0 -i "${record.manifest.concatFilePath}" -vf "subtitles=${record.manifest.subtitleFilePath},scale=1080:1920" -c:v libx264 -c:a aac "${record.manifest.outputPath}"`;
}
