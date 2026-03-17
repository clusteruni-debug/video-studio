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
import {
    buildStudioProjectRecord,
    buildStudioProjectRecordFromWorker,
    type ProviderAvailability,
    type StudioProjectRecord,
} from "./lib/planner";
import { loadStoredProjects, saveStoredProjects } from "./lib/storage";
import Sidebar from "./components/Sidebar";
import StoryboardPanel from "./components/StoryboardPanel";
import ImageCanvas from "./components/ImageCanvas";
import BottomBar from "./components/BottomBar";
import DebugDrawer from "./components/DebugDrawer";
import { ImageGenerationQueue, type QueueItem } from "./lib/image-queue";
import {
    assetKey,
    createPreviewUrl,
    fileToBase64,
    IMAGE_ENGINES,
    IMAGE_SIZES,
    localMediaPlanSummaryLabel,
    localMediaRenderSummaryLabel,
    plannerLabel,
    providerAvailabilityFromRecord,
    type BridgeStatus,
    type CopyState,
    type CopyTarget,
    type CreationMode,
    type GeneratedImage,
    type ImageInputMode,
    type ImageStatus,
    type LocalSceneAsset,
    type RenderState,
    type SaveState,
    type SceneAssetRole,
} from "./components/shared";

export default function App() {
    const [prompt, setPrompt] = useState("");
    const [budgetMode, setBudgetMode] = useState<BudgetMode>("standard");
    const [monthlyCapUsd, setMonthlyCapUsd] = useState(30);
    const [availability, setAvailability] = useState<ProviderAvailability>({
        premiumEnabled: false,
        sora2: false,
        veo3: false,
    });
    const [preferBridge, setPreferBridge] = useState(true);
    const [projects, setProjects] = useState<StudioProjectRecord[]>([]);
    const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
    const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null);
    const [showDebugDrawer, setShowDebugDrawer] = useState(false);
    const [copyState, setCopyState] = useState<CopyState>({ target: null, state: "idle" });
    const [bridgeStatus, setBridgeStatus] = useState<BridgeStatus>("checking");
    const [bridgeHealth, setBridgeHealth] = useState<BridgeHealth | null>(null);
    const [bridgeMessage, setBridgeMessage] = useState("로컬 브리지 상태를 확인하고 있습니다.");
    const [isGenerating, setIsGenerating] = useState(false);
    const [saveState, setSaveState] = useState<SaveState>({ status: "idle", message: "" });
    const [renderState, setRenderState] = useState<RenderState>({ status: "idle", message: "" });
    const [sceneAssets, setSceneAssets] = useState<Record<string, LocalSceneAsset>>({});
    const [clearedAssetKeys, setClearedAssetKeys] = useState<Record<string, true>>({});
    const [providerOverrides, setProviderOverrides] = useState<Record<string, Record<string, string>>>({});
    const [creationMode, setCreationMode] = useState<CreationMode>("video");
    const [generatedImages, setGeneratedImages] = useState<GeneratedImage[]>([]);
    const [selectedImageId, setSelectedImageId] = useState<string | null>(null);
    const [imageSizeIndex, setImageSizeIndex] = useState(3);
    const [imageEngineIndex, setImageEngineIndex] = useState(0);
    const [isGeneratingImage, setIsGeneratingImage] = useState(false);
    const [imageStatus, setImageStatus] = useState<ImageStatus>({ status: "idle", message: "" });
    const [imageInputMode, setImageInputMode] = useState<ImageInputMode>("single");
    const [batchPrompts, setBatchPrompts] = useState("");
    const [stylePrefix, setStylePrefix] = useState("");
    const [batchQueue, setBatchQueue] = useState<QueueItem[]>([]);
    const [isBatchProcessing, setIsBatchProcessing] = useState(false);
    const [isGeneratingSceneImages, setIsGeneratingSceneImages] = useState(false);
    const [sceneImageProgress, setSceneImageProgress] = useState("");

    const imageQueueRef = useRef<ImageGenerationQueue | null>(null);

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

    const sceneAssetsRef = useRef(sceneAssets);
    sceneAssetsRef.current = sceneAssets;
    useEffect(() => {
        return () => {
            Object.values(sceneAssetsRef.current).forEach((asset) => {
                if (asset.previewUrl) URL.revokeObjectURL(asset.previewUrl);
            });
        };
    }, []);

    const generatedImagesRef = useRef(generatedImages);
    generatedImagesRef.current = generatedImages;
    useEffect(() => {
        return () => {
            generatedImagesRef.current.forEach((img) => URL.revokeObjectURL(img.url));
            imageQueueRef.current?.clear();
            imageQueueRef.current = null;
        };
    }, []);

    const selectedProject = useMemo(
        () => projects.find((project) => project.id === selectedProjectId) ?? null,
        [projects, selectedProjectId],
    );

    const selectedProjectRef = useRef(selectedProject);
    selectedProjectRef.current = selectedProject;

    const premiumSceneCount = useMemo(
        () => selectedProject?.routes.filter((route) => route.route !== "local").length ?? 0,
        [selectedProject],
    );

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

    function handleProviderOverride(projectId: string, sceneId: string, provider: string): void {
        setProviderOverrides((current) => {
            const projectOverrides = { ...(current[projectId] ?? {}) };
            if (provider) {
                projectOverrides[sceneId] = provider;
            } else {
                delete projectOverrides[sceneId];
            }
            return { ...current, [projectId]: projectOverrides };
        });
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
                setSelectedSceneId(null);
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
            setSelectedSceneId(null);
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
            setProviderOverrides((current) => {
                const next = { ...current };
                delete next[projectId];
                return next;
            });
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
                providerOverrides: providerOverrides[selectedProject.id],
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
                    providerOverrides: providerOverrides[selectedProject.id],
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
        setSelectedSceneId(null);
        setCopyState({ target: null, state: "idle" });
        setSaveState({ status: "idle", message: "" });
        setRenderState({ status: "idle", message: "" });
    }

    function getOrCreateQueue(): ImageGenerationQueue {
        if (!imageQueueRef.current) {
            imageQueueRef.current = new ImageGenerationQueue({
                onItemUpdate: (items) => {
                    setBatchQueue(items);
                    const queue = imageQueueRef.current;
                    setIsBatchProcessing(queue?.isProcessing() ?? false);
                    const done = items.filter((i) => i.status === "done").length;
                    const failed = items.filter((i) => i.status === "failed").length;
                    const total = items.length;
                    const statusType = failed > 0 && !(queue?.isProcessing()) ? "error" as const : "idle" as const;
                    setImageStatus({ status: statusType, message: `배치: ${done}/${total} 완료${failed ? ` · ${failed} 실패` : ""}` });
                    const sceneItems = items.filter((i) => i.metadata?.sceneId);
                    if (sceneItems.length > 0) {
                        const sceneDone = sceneItems.filter((i) => i.status === "done").length;
                        setSceneImageProgress(`생성 중 (${sceneDone}/${sceneItems.length})`);
                    }
                },
                onImageCreated: (item) => {
                    if (!item.result) return;
                    const galleryUrl = URL.createObjectURL(item.result.file);
                    const newImage: GeneratedImage = {
                        id: `img-${item.id}`,
                        prompt: item.prompt,
                        url: galleryUrl,
                        file: item.result.file,
                        width: item.width,
                        height: item.height,
                        engine: item.engine,
                        createdAt: new Date().toISOString(),
                    };
                    setGeneratedImages((prev) => {
                        const next = [newImage, ...prev];
                        if (next.length > MAX_GALLERY_SIZE) {
                            next.slice(MAX_GALLERY_SIZE).forEach((img) => URL.revokeObjectURL(img.url));
                            return next.slice(0, MAX_GALLERY_SIZE);
                        }
                        return next;
                    });
                    setSelectedImageId(newImage.id);
                    const project = selectedProjectRef.current;
                    if (item.metadata?.sceneId && project) {
                        selectSceneAsset(project.id, item.metadata.sceneId, "visual", item.result.file);
                    }
                },
                onComplete: () => {
                    setIsBatchProcessing(false);
                    setIsGeneratingSceneImages(false);
                    setSceneImageProgress("");
                },
            });
        }
        return imageQueueRef.current;
    }

    const MAX_BATCH_SIZE = 100;

    function startBatchGeneration(): void {
        const lines = batchPrompts.split("\n").map((l) => l.trim()).filter(Boolean).slice(0, MAX_BATCH_SIZE);
        if (lines.length === 0) return;

        const queue = getOrCreateQueue();
        queue.clear();
        const size = IMAGE_SIZES[imageSizeIndex];
        const engine = IMAGE_ENGINES[imageEngineIndex];
        const prefix = stylePrefix.trim();

        for (const line of lines) {
            let filename: string | undefined;
            let rawPrompt: string;

            if (line.includes(": ")) {
                const colonIndex = line.indexOf(": ");
                filename = line.slice(0, colonIndex).trim();
                rawPrompt = line.slice(colonIndex + 2).trim();
            } else {
                rawPrompt = line;
            }

            const fullPrompt = prefix ? `${prefix}, ${rawPrompt}` : rawPrompt;
            queue.enqueue({
                id: crypto.randomUUID(),
                prompt: fullPrompt,
                originalPrompt: rawPrompt,
                width: size.width,
                height: size.height,
                engine: engine.key,
                filename,
            });
        }

        queue.start();
        setIsBatchProcessing(true);
        setImageStatus({ status: "idle", message: `배치 생성 시작 (${lines.length}개)` });
    }

    function stopBatch(): void {
        imageQueueRef.current?.stop();
        setIsBatchProcessing(false);
    }

    function retryAllFailed(): void {
        imageQueueRef.current?.retryAllFailed();
    }

    function generateSceneImages(): void {
        if (!selectedProject || isGeneratingSceneImages) return;
        const scenes = selectedProject.plan.scenes;
        if (scenes.length === 0) return;

        const queue = getOrCreateQueue();
        queue.clear();
        const prefix = stylePrefix.trim();

        for (let i = 0; i < scenes.length; i++) {
            const scene = scenes[i];
            const prompt = prefix ? `${prefix}, ${scene.prompt}` : scene.prompt;
            const slug = scene.title.replace(/[^a-zA-Z0-9가-힣]/g, "_").slice(0, 30);
            queue.enqueue({
                id: crypto.randomUUID(),
                prompt,
                originalPrompt: scene.prompt,
                width: 1920,
                height: 1080,
                engine: IMAGE_ENGINES[imageEngineIndex].key,
                filename: `scene_${String(i + 1).padStart(2, "0")}_${slug}`,
                metadata: { sceneId: scene.id },
            });
        }

        queue.start();
        setIsGeneratingSceneImages(true);
        setSceneImageProgress(`생성 중 (0/${scenes.length})`);
    }

    const imageGenAbortRef = useRef<AbortController | null>(null);
    const MAX_GALLERY_SIZE = 50;

    async function generateImage(): Promise<void> {
        if (imageInputMode === "batch") {
            startBatchGeneration();
            return;
        }
        const normalized = prompt.trim();
        if (!normalized || isGeneratingImage) return;
        setIsGeneratingImage(true);
        setImageStatus({ status: "idle", message: "" });
        try {
            const size = IMAGE_SIZES[imageSizeIndex];
            const engine = IMAGE_ENGINES[imageEngineIndex];
            const id = crypto.randomUUID();
            const encoded = encodeURIComponent(normalized);
            const apiUrl = `https://image.pollinations.ai/prompt/${encoded}?width=${size.width}&height=${size.height}&model=${engine.key}&nologo=true&seed=${Date.now()}`;
            imageGenAbortRef.current = new AbortController();
            const response = await fetch(apiUrl, {
                signal: imageGenAbortRef.current.signal,
            });
            if (!response.ok) throw new Error(`이미지 생성 실패 (${response.status})`);
            const blob = await response.blob();
            const mimeType = blob.type || "image/png";
            const ext = mimeType.includes("jpeg") || mimeType.includes("jpg") ? "jpg" : mimeType.includes("webp") ? "webp" : "png";
            const file = new File([blob], `image-${id}.${ext}`, { type: mimeType });
            const url = URL.createObjectURL(blob);
            const newImage: GeneratedImage = {
                id: `img-${id}`,
                prompt: normalized,
                url,
                file,
                width: size.width,
                height: size.height,
                engine: engine.key,
                createdAt: new Date().toISOString(),
            };
            setGeneratedImages((prev) => {
                const next = [newImage, ...prev];
                if (next.length > MAX_GALLERY_SIZE) {
                    next.slice(MAX_GALLERY_SIZE).forEach((img) => URL.revokeObjectURL(img.url));
                    return next.slice(0, MAX_GALLERY_SIZE);
                }
                return next;
            });
            setSelectedImageId(newImage.id);
            setImageStatus({ status: "success", message: "이미지 생성 완료" });
        } catch (error) {
            if (error instanceof DOMException && error.name === "AbortError") {
                setImageStatus({ status: "idle", message: "이미지 생성이 취소되었습니다." });
            } else {
                setImageStatus({ status: "error", message: error instanceof Error ? error.message : "이미지 생성에 실패했습니다." });
            }
        } finally {
            imageGenAbortRef.current = null;
            setIsGeneratingImage(false);
        }
    }

    function downloadImage(image: GeneratedImage): void {
        const anchor = document.createElement("a");
        anchor.href = image.url;
        anchor.download = image.file.name;
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
    }

    function downloadAllImages(): void {
        generatedImages.forEach((img, i) => {
            setTimeout(() => downloadImage(img), i * 300);
        });
    }

    function removeImage(id: string): void {
        setGeneratedImages((prev) => {
            const removed = prev.find((img) => img.id === id);
            if (removed) URL.revokeObjectURL(removed.url);
            return prev.filter((img) => img.id !== id);
        });
        setSelectedImageId((current) => (current === id ? null : current));
    }

    function useImageInVideo(image: GeneratedImage): void {
        if (!selectedProject) {
            setImageStatus({ status: "error", message: "영상 프로젝트를 먼저 생성한 뒤 다시 시도하세요." });
            return;
        }
        const firstScene = selectedProject.plan.scenes[0];
        if (!firstScene) {
            setImageStatus({ status: "error", message: "프로젝트에 장면이 없어 이미지를 배치할 수 없습니다." });
            return;
        }
        selectSceneAsset(selectedProject.id, firstScene.id, "visual", image.file);
        setSelectedSceneId(firstScene.id);
        setCreationMode("video");
    }

    return (
        <div className="studio-shell">
            {/* Top bar */}
            <header className="top-bar">
                <div className="top-bar-brand">
                    <span className={`bridge-dot bridge-dot-${bridgeStatus}`} />
                    <span className="top-bar-title">Video Studio</span>
                </div>
                <div className="top-bar-summary">
                    {selectedProject && (
                        <>
                            <span>{premiumSceneCount} 프리미엄</span>
                            <span>{selectedProject.manifest.totalDurationSec.toFixed(1)}초</span>
                        </>
                    )}
                </div>
                <button
                    className="top-bar-settings"
                    type="button"
                    onClick={() => setShowDebugDrawer(true)}
                    title="고급 설정 & 진단"
                >
                    ⚙
                </button>
            </header>

            {/* Body: sidebar + main canvas */}
            <div className="studio-body">
                <Sidebar
                    creationMode={creationMode}
                    onCreationModeChange={setCreationMode}
                    prompt={prompt}
                    onPromptChange={setPrompt}
                    imageSizeIndex={imageSizeIndex}
                    onImageSizeIndexChange={setImageSizeIndex}
                    imageEngineIndex={imageEngineIndex}
                    onImageEngineIndexChange={setImageEngineIndex}
                    budgetMode={budgetMode}
                    onBudgetModeChange={setBudgetMode}
                    monthlyCapUsd={monthlyCapUsd}
                    onMonthlyCapUsdChange={setMonthlyCapUsd}
                    availability={availability}
                    onAvailabilityChange={setAvailability}
                    preferBridge={preferBridge}
                    onPreferBridgeChange={setPreferBridge}
                    isGenerating={creationMode === "image" ? (isBatchProcessing || isGeneratingImage) : isGenerating}
                    onGenerate={creationMode === "image" ? () => void generateImage() : () => void generateProject()}
                    projects={projects}
                    selectedProjectId={selectedProjectId}
                    onSelectProject={handleSelectProject}
                    onRemoveProject={removeProject}
                    imageInputMode={imageInputMode}
                    onImageInputModeChange={setImageInputMode}
                    batchPrompts={batchPrompts}
                    onBatchPromptsChange={setBatchPrompts}
                    stylePrefix={stylePrefix}
                    onStylePrefixChange={setStylePrefix}
                />

                {creationMode === "image" ? (
                    <ImageCanvas
                        images={generatedImages}
                        selectedImageId={selectedImageId}
                        onSelectImage={setSelectedImageId}
                        onDownload={downloadImage}
                        onDownloadAll={downloadAllImages}
                        onUseInVideo={useImageInVideo}
                        onRemoveImage={removeImage}
                        batchQueue={batchQueue}
                        isBatchProcessing={isBatchProcessing}
                        onRetryAllFailed={retryAllFailed}
                        onStopBatch={stopBatch}
                    />
                ) : (
                    <StoryboardPanel
                        selectedProject={selectedProject}
                        sceneAssets={sceneAssets}
                        clearedAssetKeys={clearedAssetKeys}
                        providerOverrides={providerOverrides[selectedProject?.id ?? ""] ?? {}}
                        selectedSceneId={selectedSceneId}
                        onSelectScene={setSelectedSceneId}
                        onSelectAsset={selectSceneAsset}
                        onClearAsset={clearSceneAsset}
                        onProviderOverride={handleProviderOverride}
                        onGenerateSceneImages={generateSceneImages}
                        isGeneratingSceneImages={isGeneratingSceneImages}
                        sceneImageProgress={sceneImageProgress}
                    />
                )}
            </div>

            {/* Bottom bar */}
            <BottomBar
                creationMode={creationMode}
                selectedProject={selectedProject}
                bridgeStatus={bridgeStatus}
                saveState={saveState}
                renderState={renderState}
                imageStatus={imageStatus}
                selectedImage={generatedImages.find((img) => img.id === selectedImageId) ?? null}
                onSave={() => void saveProjectThroughBridge()}
                onRender={() => void renderProjectThroughBridge()}
                onRefreshBridge={() => void refreshBridgeHealth()}
                onDownloadImage={downloadImage}
                batchQueue={batchQueue}
                isBatchProcessing={isBatchProcessing}
            />

            {/* Debug drawer */}
            {showDebugDrawer && (
                <DebugDrawer
                    bridgeHealth={bridgeHealth}
                    bridgeStatus={bridgeStatus}
                    bridgeMessage={bridgeMessage}
                    selectedProject={selectedProject}
                    copyState={copyState}
                    onCopyCommand={(target, command) => void copyCommand(target, command)}
                    onExportJson={(filename, payload) => void exportJson(filename, payload)}
                    onRefreshBridge={() => void refreshBridgeHealth()}
                    onClose={() => setShowDebugDrawer(false)}
                />
            )}
        </div>
    );
}
