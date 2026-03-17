import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import type { BudgetMode } from "../../../shared/contracts/plan";
import {
    fetchBridgeHealth,
    renderSmokeWithSSE,
    routePlanWithBridge,
    saveProjectWithBridge,
    type BridgeHealth,
    type SceneAssetUploadPayload,
} from "./lib/bridge";
import { samplePrompts } from "./lib/sample-data";
import {
    buildStudioProjectRecord,
    buildStudioProjectRecordFromWorker,
    type ProviderAvailability,
    type StudioProjectRecord,
} from "./lib/planner";
import { loadStoredProjects, saveStoredProjects } from "./lib/storage";
import ComposerPanel from "./components/ComposerPanel";
import StoryboardPanel from "./components/StoryboardPanel";
import ExecutionPanel from "./components/ExecutionPanel";
import {
    assetKey,
    createPreviewUrl,
    fileToBase64,
    localMediaPlanSummaryLabel,
    localMediaRenderSummaryLabel,
    plannerLabel,
    providerAvailabilityFromRecord,
    type BridgeStatus,
    type CopyState,
    type CopyTarget,
    type LocalSceneAsset,
    type RenderState,
    type SaveState,
    type SceneAssetRole,
} from "./components/shared";

export default function App() {
    const [prompt, setPrompt] = useState(samplePrompts[0]);
    const [budgetMode, setBudgetMode] = useState<BudgetMode>("standard");
    const [monthlyCapUsd, setMonthlyCapUsd] = useState(30);
    const [availability, setAvailability] = useState<ProviderAvailability>({
        premiumEnabled: true,
        sora2: true,
        veo3: false,
    });
    const [preferBridge, setPreferBridge] = useState(true);
    const [projects, setProjects] = useState<StudioProjectRecord[]>([]);
    const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
    const [copyState, setCopyState] = useState<CopyState>({ target: null, state: "idle" });
    const [bridgeStatus, setBridgeStatus] = useState<BridgeStatus>("checking");
    const [bridgeHealth, setBridgeHealth] = useState<BridgeHealth | null>(null);
    const [bridgeMessage, setBridgeMessage] = useState("로컬 브리지 상태를 확인하고 있습니다.");
    const [isGenerating, setIsGenerating] = useState(false);
    const [saveState, setSaveState] = useState<SaveState>({ status: "idle", message: "" });
    const [renderState, setRenderState] = useState<RenderState>({ status: "idle", message: "" });
    const [sceneAssets, setSceneAssets] = useState<Record<string, LocalSceneAsset>>({});
    const [clearedAssetKeys, setClearedAssetKeys] = useState<Record<string, true>>({});

    const initializedRef = useRef(false);

    useEffect(() => {
        const stored = loadStoredProjects();
        setProjects(stored);
        setSelectedProjectId(stored[0]?.id ?? null);
        initializedRef.current = true;
    }, []);

    useEffect(() => {
        if (initializedRef.current) {
            saveStoredProjects(projects);
        }
    }, [projects]);

    useEffect(() => {
        void refreshBridgeHealth();
    }, []);

    useEffect(() => {
        return () => {
            Object.values(sceneAssets).forEach((asset) => {
                if (asset.previewUrl) {
                    URL.revokeObjectURL(asset.previewUrl);
                }
            });
        };
    }, [sceneAssets]);

    const selectedProject = useMemo(
        () => projects.find((project) => project.id === selectedProjectId) ?? null,
        [projects, selectedProjectId],
    );

    const premiumSceneCount = useMemo(
        () => selectedProject?.routes.filter((route) => route.route !== "local").length ?? 0,
        [selectedProject],
    );

    const selectedProjectAssetCount = useMemo(() => {
        if (!selectedProject) return 0;
        const prefix = `${selectedProject.id}::`;
        return Object.keys(sceneAssets).filter((key) => key.startsWith(prefix)).length;
    }, [sceneAssets, selectedProject]);

    async function refreshBridgeHealth(): Promise<void> {
        setBridgeStatus("checking");
        setBridgeMessage("로컬 브리지 연결 상태를 다시 확인합니다.");
        try {
            const health = await fetchBridgeHealth();
            setBridgeHealth(health);
            setBridgeStatus("connected");
            setBridgeMessage(`브리지 연결 완료 · ${health.port} 포트에서 작업기를 사용할 수 있습니다.`);
        } catch (error) {
            setBridgeHealth(null);
            setBridgeStatus("offline");
            setBridgeMessage(error instanceof Error ? error.message : "브리지에 연결하지 못했습니다.");
        }
    }

    function selectSceneAsset(projectId: string, sceneId: string, role: SceneAssetRole, file: File | null): void {
        const key = assetKey(projectId, sceneId, role);
        setSceneAssets((current) => {
            const next = { ...current };
            const previous = next[key];
            if (previous?.previewUrl) {
                URL.revokeObjectURL(previous.previewUrl);
            }
            if (!file) {
                delete next[key];
                return next;
            }
            next[key] = { role, file, previewUrl: createPreviewUrl(file, role) };
            return next;
        });
        setClearedAssetKeys((current) => {
            const next = { ...current };
            delete next[key];
            return next;
        });
    }

    function clearSceneAsset(projectId: string, sceneId: string, role: SceneAssetRole): void {
        const key = assetKey(projectId, sceneId, role);
        setSceneAssets((current) => {
            const next = { ...current };
            const previous = next[key];
            if (previous?.previewUrl) {
                URL.revokeObjectURL(previous.previewUrl);
            }
            delete next[key];
            return next;
        });
        setClearedAssetKeys((current) => ({ ...current, [key]: true }));
    }

    async function serializeSceneAssets(projectId: string): Promise<SceneAssetUploadPayload[]> {
        const entries = Object.entries(sceneAssets).filter(([key]) => key.startsWith(`${projectId}::`));
        return Promise.all(
            entries.map(async ([key, asset]) => {
                const [, sceneId, role] = key.split("::");
                return {
                    sceneId,
                    role: role as SceneAssetRole,
                    fileName: asset.file.name,
                    mimeType: asset.file.type || "application/octet-stream",
                    base64: await fileToBase64(asset.file),
                };
            }),
        );
    }

    async function generateProject(): Promise<void> {
        const normalized = prompt.trim();
        if (!normalized || isGenerating) return;

        setIsGenerating(true);
        setSaveState({ status: "idle", message: "" });
        setRenderState({ status: "idle", message: "" });

        try {
            let nextRecord: StudioProjectRecord;

            if (preferBridge && bridgeStatus === "connected") {
                try {
                    const payload = await routePlanWithBridge({
                        prompt: normalized,
                        budgetMode,
                        availability,
                    });
                    nextRecord = buildStudioProjectRecordFromWorker({
                        projectId: `project-${Date.now()}`,
                        planner: payload.planner,
                        plan: payload.plan,
                        routes: payload.routes,
                        estimatedCostUsd: payload.estimatedTotalCostUsd,
                    });
                    setBridgeMessage(`브리지를 통해 장면 설계를 받아왔습니다. 기획 엔진: ${plannerLabel(payload.planner)}`);
                } catch (error) {
                    setBridgeStatus("error");
                    setBridgeMessage(
                        error instanceof Error
                            ? `${error.message} · 브라우저 임시 플래너로 대체합니다.`
                            : "브리지 호출에 실패해 브라우저 임시 플래너로 대체합니다.",
                    );
                    nextRecord = buildStudioProjectRecord({
                        prompt: normalized,
                        budgetMode,
                        monthlyCapUsd,
                        availability,
                    });
                }
            } else {
                nextRecord = buildStudioProjectRecord({
                    prompt: normalized,
                    budgetMode,
                    monthlyCapUsd,
                    availability,
                });
            }

            startTransition(() => {
                setProjects((current) => [nextRecord, ...current].slice(0, 8));
                setSelectedProjectId(nextRecord.id);
                setCopyState({ target: null, state: "idle" });
            });
        } finally {
            setIsGenerating(false);
        }
    }

    function removeProject(projectId: string): void {
        const nextProjects = projects.filter((project) => project.id !== projectId);
        const prefix = `${projectId}::`;
        startTransition(() => {
            setProjects(nextProjects);
            setSelectedProjectId((current) => (current === projectId ? nextProjects[0]?.id ?? null : current));
            setCopyState({ target: null, state: "idle" });
            setSaveState({ status: "idle", message: "" });
            setRenderState({ status: "idle", message: "" });
            setSceneAssets((current) => {
                const next = { ...current };
                Object.entries(next).forEach(([key, asset]) => {
                    if (key.startsWith(prefix)) {
                        if (asset.previewUrl) {
                            URL.revokeObjectURL(asset.previewUrl);
                        }
                        delete next[key];
                    }
                });
                return next;
            });
            setClearedAssetKeys((current) =>
                Object.fromEntries(Object.entries(current).filter(([key]) => !key.startsWith(prefix))),
            );
        });
    }

    async function copyCommand(target: CopyTarget, command: string): Promise<void> {
        try {
            await navigator.clipboard.writeText(command);
            setCopyState({ target, state: "copied" });
        } catch {
            setCopyState({ target, state: "failed" });
        }
    }

    async function exportJson(filename: string, payload: unknown): Promise<void> {
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        anchor.click();
        URL.revokeObjectURL(url);
    }

    async function saveProjectThroughBridge(): Promise<void> {
        if (!selectedProject || bridgeStatus !== "connected") return;

        setSaveState({ status: "saving", message: "프로젝트 파일을 storage 폴더에 저장하는 중입니다." });
        try {
            const sceneAssetPayload = await serializeSceneAssets(selectedProject.id);
            const response = await saveProjectWithBridge({
                prompt: selectedProject.plan.sourcePrompt,
                budgetMode: selectedProject.plan.budgetMode,
                projectId: selectedProject.id,
                sceneAssets: sceneAssetPayload,
                availability: providerAvailabilityFromRecord(selectedProject),
            });
            const nextRecord = buildStudioProjectRecordFromWorker({
                projectId: selectedProject.id,
                planner: response.planner,
                plan: response.plan,
                routes: response.routes,
                estimatedCostUsd: response.saveResult.estimatedTotalCostUsd,
                manifest: response.manifest,
            });
            startTransition(() => {
                setProjects((current) =>
                    current.map((project) => (project.id === selectedProject.id ? nextRecord : project)),
                );
            });
            setSaveState({
                status: "saved",
                message:
                    `저장 완료 · ${response.saveResult.inputDir} · 업로드 자산 ${response.saveResult.uploadedAssets?.length ?? 0}개` +
                    ` · ${localMediaPlanSummaryLabel(response.saveResult.localMediaSummary)}`,
            });
            setBridgeMessage(
                `프로젝트 ${response.saveResult.projectId} 저장이 끝났습니다. 기획 엔진: ${plannerLabel(response.planner)} · ${localMediaPlanSummaryLabel(response.saveResult.localMediaSummary)}`,
            );
        } catch (error) {
            setSaveState({
                status: "failed",
                message: error instanceof Error ? error.message : "프로젝트 저장에 실패했습니다.",
            });
        }
    }

    async function renderProjectThroughBridge(): Promise<void> {
        if (!selectedProject || bridgeStatus !== "connected") return;

        setRenderState({ status: "rendering", message: "실제 초안 렌더를 실행하는 중입니다." });
        try {
            const sceneAssetPayload = await serializeSceneAssets(selectedProject.id);
            const response = await renderSmokeWithSSE(
                {
                    prompt: selectedProject.plan.sourcePrompt,
                    budgetMode: selectedProject.plan.budgetMode,
                    projectId: selectedProject.id,
                    sceneAssets: sceneAssetPayload,
                    availability: providerAvailabilityFromRecord(selectedProject),
                },
                (progress) => {
                    setRenderState({
                        status: "rendering",
                        message: progress.message,
                    });
                },
            );
            const nextRecord = buildStudioProjectRecordFromWorker({
                projectId: selectedProject.id,
                planner: response.planner,
                plan: response.plan,
                routes: response.routes,
                estimatedCostUsd: response.saveResult.estimatedTotalCostUsd,
                manifest: response.manifest,
            });
            startTransition(() => {
                setProjects((current) =>
                    current.map((project) => (project.id === selectedProject.id ? nextRecord : project)),
                );
            });
            setRenderState({
                status: "rendered",
                message:
                    `렌더 완료 · ${response.renderResult.outputPath}` +
                    ` · ${localMediaRenderSummaryLabel(response.renderResult.localMediaSummary)}`,
            });
            setBridgeMessage(
                `초안 렌더가 완료되었습니다. ${response.renderResult.projectId} · 기획 엔진: ${plannerLabel(response.planner)} · ${localMediaRenderSummaryLabel(response.renderResult.localMediaSummary)}`,
            );
        } catch (error) {
            setRenderState({
                status: "failed",
                message: error instanceof Error ? error.message : "초안 렌더 실행에 실패했습니다.",
            });
        }
    }

    function handleSelectProject(projectId: string): void {
        setSelectedProjectId(projectId);
        setCopyState({ target: null, state: "idle" });
        setSaveState({ status: "idle", message: "" });
        setRenderState({ status: "idle", message: "" });
    }

    return (
        <div className="studio-shell">
            <div className="studio-glow studio-glow-left" />
            <div className="studio-glow studio-glow-right" />
            <div className="studio-noise" />

            <ComposerPanel
                prompt={prompt}
                onPromptChange={setPrompt}
                budgetMode={budgetMode}
                onBudgetModeChange={setBudgetMode}
                monthlyCapUsd={monthlyCapUsd}
                onMonthlyCapUsdChange={setMonthlyCapUsd}
                availability={availability}
                onAvailabilityChange={setAvailability}
                preferBridge={preferBridge}
                onPreferBridgeChange={setPreferBridge}
                bridgeStatus={bridgeStatus}
                bridgeHealth={bridgeHealth}
                bridgeMessage={bridgeMessage}
                premiumSceneCount={premiumSceneCount}
                selectedProjectAssetCount={selectedProjectAssetCount}
                selectedProject={selectedProject}
                isGenerating={isGenerating}
                onRefreshBridge={() => void refreshBridgeHealth()}
                onGenerate={() => void generateProject()}
            />

            <main className="workspace">
                <StoryboardPanel
                    selectedProject={selectedProject}
                    sceneAssets={sceneAssets}
                    clearedAssetKeys={clearedAssetKeys}
                    onSelectAsset={selectSceneAsset}
                    onClearAsset={clearSceneAsset}
                />

                <ExecutionPanel
                    selectedProject={selectedProject}
                    bridgeHealth={bridgeHealth}
                    bridgeStatus={bridgeStatus}
                    saveState={saveState}
                    renderState={renderState}
                    copyState={copyState}
                    projects={projects}
                    selectedProjectId={selectedProjectId}
                    onSave={() => void saveProjectThroughBridge()}
                    onRender={() => void renderProjectThroughBridge()}
                    onRefreshBridge={() => void refreshBridgeHealth()}
                    onCopyCommand={(target, command) => void copyCommand(target, command)}
                    onExportJson={(filename, payload) => void exportJson(filename, payload)}
                    onRemoveProject={removeProject}
                    onSelectProject={handleSelectProject}
                />
            </main>
        </div>
    );
}
